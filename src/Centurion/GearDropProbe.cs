using System;
using System.Collections.Generic;
using System.Linq;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.Jobs;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>Controlled touchdowns observe stock suspension, terrain drag and attachment failures.</summary>
static class GearDropProbe
{
    static ConfigEntry<float>? command;
    static ConfigEntry<float>? mass;
    static ConfigEntry<float>? groundSpeed;
    static ConfigEntry<float>? pitch, rightOffset, fuelFraction, derotate, flapDegrees;
    static Aircraft? tested;
    static LandingGear[] legs = Array.Empty<LandingGear>();
    static float requested, started, touchdown;
    static float releaseSpeed;
    static int broken, joints;
    static bool running, contacted;
    static bool derotated;
    static float firstContactTime;
    static float lastCommand = -1f;
    static readonly Dictionary<LandingGear, float> peaks = new();
    static readonly Dictionary<LandingGear, float> dragRatio = new();
    static readonly Dictionary<LandingGear, Vector2> contactSpeeds = new();
    static readonly HashSet<LandingGear> contacts = new();
    static LandingGear? detachedLeg;
    static readonly AccessTools.FieldRef<LandingGear, float> Compression = AccessTools.FieldRefAccess<LandingGear, float>("compressionDistance");
    static readonly AccessTools.FieldRef<LandingGear, float> Travel = AccessTools.FieldRefAccess<LandingGear, float>("suspensionTravel");
    static readonly AccessTools.FieldRef<LandingGear, Transform> Cast = AccessTools.FieldRefAccess<LandingGear, Transform>("castPoint");
    static readonly AccessTools.FieldRef<LandingGear, AeroPart> Part = AccessTools.FieldRefAccess<LandingGear, AeroPart>("attachedPart");
    static Harmony? observer;
    static readonly AccessTools.FieldRef<ControlSurface, PtrAllocation<ControlSurfaceFields>> SurfaceFields =
        AccessTools.FieldRefAccess<ControlSurface, PtrAllocation<ControlSurfaceFields>>("JobFields");

    internal static void Update(Aircraft aircraft)
    {
        command ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropFpm", 0f,
            "With Diagnostics.Enabled, once per mission drop the stationary local aircraft onto its runway at this nominal downward feet/min; 0 disables. Uses stock gear, gravity, collisions and joints.");
        mass ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropMassKg", 0f,
            "GearDropFpm target aircraft mass in kg; adds the difference as root ballast immediately before the drop. 0 preserves the loaded mass.");
        groundSpeed ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropSpeedMps", 0f,
            "GearDropFpm forward ground speed in m/s at release; 0 isolates vertical impact, -1 uses the stock mass-scaled landing speed.");
        pitch ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropPitchDeg", 0f, "Nose-up release attitude in degrees relative to the settled aircraft.");
        rightOffset ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropRightM", 0f, "Translate release right of the runway in metres; raycast the actual surface before release.");
        fuelFraction ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropFuelFraction", -1f, "Fuel fraction set through FuelTank.Refuel before release; -1 preserves fuel.");
        derotate ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropDerotateDegS", 0f, "Once, 0.15 seconds after first wheel contact, set a coherent nose-down pitch rate in degrees/s to exercise nose slap.");
        flapDegrees ??= ScenarioHooks.Diagnostics.ConfigFile.Bind("Debug", "GearDropFlapDeg", -1f, "Set settled flap deflection and preset at release in degrees; -1 preserves flaps. Centurion landing uses 15, while a runway spawn selects takeoff flaps.");
        if (lastCommand != command.Value)
        {
            lastCommand = command.Value;
            ScenarioHooks.Log.Info(Invariant($"gear-drop command={command.Value} gear={aircraft.gearState} speed={aircraft.speed:0.000} tested={aircraft == tested}"));
        }
        if (running)
        {
            foreach (LandingGear leg in legs.Where(g => g != null))
            {
                peaks[leg] = Mathf.Max(peaks[leg], Compression(leg));
            }
            if (contacted && !derotated && derotate.Value > 0f && Time.fixedTime - firstContactTime >= 0.15f)
            {
                derotated = true;
                var root = aircraft.GetComponent<AeroPart>().rb;
                float before = Vector3.Dot(root.angularVelocity, aircraft.transform.right);
                var spin = aircraft.transform.right * (derotate.Value * Mathf.Deg2Rad - before);
                foreach (Rigidbody body in aircraft.partLookup.Select(p => p.rb).Where(b => b != null).Distinct())
                {
                    body.velocity += Vector3.Cross(spin, body.worldCenterOfMass - root.worldCenterOfMass);
                    body.angularVelocity += spin;
                }
                aircraft.velocityPrev = aircraft.CockpitRB().velocity;
                foreach (Pilot pilot in aircraft.pilots)
                    pilot.velocityPrev = pilot.GetRB().velocity;
                ScenarioHooks.Log.Info(Invariant($"gear-drop derotate rate={derotate.Value:0.0} elapsed={Time.fixedTime-started:0.000} before={before*Mathf.Rad2Deg:0.00}"));
            }
            if (Time.fixedTime - started >= 6f)
            {
                running = false;
                ScenarioHooks.Log.Info(Invariant($"gear-drop result nominal={requested:0} fpm mass={aircraft.GetMass():0} kg broken={broken} joints={joints} contact={contacted} observed={touchdown:0.0} fpm"));
                foreach (LandingGear leg in legs.Where(g => g != null))
                    ScenarioHooks.Log.Info(Invariant($"gear-drop peak {leg.name} compression={peaks[leg]:0.000} m"));
            }
            return;
        }
        if (command.Value <= 0f || aircraft == tested) return;
        legs = aircraft.partLookup.SelectMany(p => p.GetComponentsInChildren<LandingGear>()).Distinct().ToArray();
        if (legs.Length != 3 || aircraft.gearState != LandingGear.GearState.LockedExtended || aircraft.speed > 0.5f)
        {
            return;
        }
        tested = aircraft;
        if (fuelFraction.Value >= 0f)
            foreach (FuelTank tank in aircraft.GetFuelTanks()) tank.Refuel(Mathf.Clamp01(fuelFraction.Value));
        if (mass.Value > 0f) aircraft.GetComponent<AeroPart>().ModifyMass(mass.Value - aircraft.GetMass());
        var bodies = aircraft.partLookup.Select(p => p.rb).Where(rb => rb != null).Distinct().ToArray();
        var cg = bodies.Aggregate(Vector3.zero, (v, b) => v + b.worldCenterOfMass * b.mass) / bodies.Sum(b => b.mass);
        ScenarioHooks.Log.Info(Invariant($"gear-drop balance cg={aircraft.transform.InverseTransformPoint(cg).ToString("F4")} mass={bodies.Sum(b => b.mass):0.0} fuel={aircraft.GetFuelTanks().Sum(t => t.fuelMass):0.0}"));
        var supports = legs.Select(g => Cast(g).position - Cast(g).up * Travel(g)).ToArray();
        float Cross(Vector3 a, Vector3 b) => a.x * b.z - a.z * b.x;
        float area = Cross(supports[1] - supports[0], supports[2] - supports[0]);
        float share1 = Cross(cg - supports[0], supports[2] - supports[0]) / area;
        float share2 = Cross(supports[1] - supports[0], cg - supports[0]) / area;
        var shares = new[] { 1f - share1 - share2, share1, share2 };
        for (int i = 0; i < legs.Length; i++)
            ScenarioHooks.Log.Info(Invariant($"gear-drop static {legs[i].name} share={shares[i]:0.000000} loadN={shares[i]*aircraft.GetMass()*9.81f:0.0}"));
        foreach (LandingGear leg in legs)
            ScenarioHooks.Log.Info($"gear-drop support {leg.name} free={aircraft.transform.InverseTransformPoint(Cast(leg).position - Cast(leg).up * Travel(leg)).ToString("F4")}");
        var pivot = aircraft.transform.position;
        var rotation = Quaternion.AngleAxis(-pitch.Value, aircraft.transform.right);
        var offset = Vector3.ProjectOnPlane(aircraft.transform.right, Vector3.up).normalized * rightOffset.Value;
        float lift = float.NegativeInfinity;
        foreach (LandingGear leg in legs)
        {
            var free = pivot + rotation * (Cast(leg).position - Cast(leg).up * Travel(leg) - pivot) + offset;
            var surfaces = Physics.RaycastAll(free + Vector3.up * 100f, Vector3.down, 200f,
                    ~((int)PhysicsLayers.ExclusionZonesMask | (int)PhysicsLayers.IgnoreCollisionsMask))
                .Where(h => !bodies.Contains(h.rigidbody)).OrderBy(h => h.distance).ToArray();
            if (surfaces.Length == 0)
                throw new InvalidOperationException("Gear drop has no surface under " + leg.name);
            var surface = surfaces[0];
            lift = Mathf.Max(lift, surface.point.y + 0.05f - free.y);
        }
        offset += Vector3.up * lift;
        var positions = bodies.ToDictionary(b => b, b => pivot + rotation * (b.position - pivot) + offset);
        var rotations = bodies.ToDictionary(b => b, b => rotation * b.rotation);
        foreach (Rigidbody body in bodies.OrderBy(b => b.transform.GetComponentsInParent<Rigidbody>().Length))
        {
            body.transform.SetPositionAndRotation(positions[body], rotations[body]);
            body.position = positions[body];
            body.rotation = rotations[body];
        }
        Physics.SyncTransforms();
        requested = command.Value;
        releaseSpeed = groundSpeed.Value < 0f
            ? aircraft.GetAircraftParameters().landingSpeed * Mathf.Sqrt(aircraft.GetMass() / aircraft.definition.aircraftInfo.maxWeight)
            : groundSpeed.Value;
        foreach (Rigidbody body in bodies)
        {
            body.velocity = Vector3.down * (requested * 0.3048f / 60f)
                + Vector3.ProjectOnPlane(aircraft.transform.forward, Vector3.up).normalized * releaseSpeed;
            body.angularVelocity = Vector3.zero;
        }
        // The release changes the initial state; its velocity jump is not an impact.
        aircraft.velocityPrev = aircraft.CockpitRB().velocity;
        foreach (Pilot pilot in aircraft.pilots)
            pilot.velocityPrev = pilot.GetRB().velocity;
        if (releaseSpeed > 0f)
        {
            // A landing arrives with brakes released; the settled fixture has accumulated the stock parking brake.
            aircraft.speed = bodies[0].velocity.magnitude;
            aircraft.GetInputs().brake = 0f;
            foreach (LandingGear leg in legs) AccessTools.Field(typeof(LandingGear), "brakeStrength").SetValue(leg, 0f);
        }
        if (flapDegrees.Value >= 0f) SetLandingFlaps(aircraft, flapDegrees.Value);
        peaks.Clear();
        contacts.Clear();
        dragRatio.Clear();
        contactSpeeds.Clear();
        detachedLeg = null;
        derotated = false;
        broken = joints = 0;
        contacted = false;
        touchdown = 0f;
        foreach (LandingGear leg in legs)
        {
            peaks[leg] = 0f;
            dragRatio[leg] = 0f;
            contactSpeeds[leg] = Vector2.zero;
            leg.onGearBreak += Broke;
            AeroPart part = Part(leg);
            ScenarioHooks.Log.Info(Invariant($"gear-drop leg {leg.name} on {part.name} mass={part.rb.mass:0} travel={Travel(leg):0.000} spring={Read(leg, "springRate"):0} damping={Read(leg, "dampingRate"):0} limit={Read(leg, "maxCompression"):0.000} area={Read(leg, "contactArea"):0.000000} hinge={((Transform)AccessTools.Field(typeof(LandingGear), "gearHinge").GetValue(leg)).localEulerAngles}"));
        }
        foreach (UnitPart part in aircraft.partLookup) part.onJointBroken += JointBroke;
        if (observer == null)
        {
            observer = new Harmony("baanish.centurion.gear-drop-observer");
            observer.Patch(AccessTools.Method(typeof(LandingGear), "FixedUpdate"),
                prefix: new HarmonyMethod(typeof(GearDropProbe), nameof(BeforeGear)));
            observer.Patch(AccessTools.Method(typeof(LandingGear), "LandingGear_OnPartDetached"),
                prefix: new HarmonyMethod(typeof(GearDropProbe), nameof(BeforeDetached)),
                postfix: new HarmonyMethod(typeof(GearDropProbe), nameof(AfterDetached)));
        }
        started = Time.fixedTime;
        running = true;
        ScenarioHooks.Log.Info(Invariant($"gear-drop start nominal={requested:0} fpm mass={aircraft.GetMass():0} kg lift={lift:0.000} m dt={Time.fixedDeltaTime:0.0000} speed={releaseSpeed:0.0} m/s type={aircraft.definition.jsonKey} pitch={pitch.Value:0.0} right={rightOffset.Value:0.0} derotate={derotate.Value:0.0} brakes={aircraft.GetInputs().brake:0.00} actualPitch={Mathf.Asin(aircraft.transform.forward.y)*Mathf.Rad2Deg:0.00} flap={flapDegrees.Value:0.0}"));
    }

    static unsafe void SetLandingFlaps(Aircraft aircraft, float degrees)
    {
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (!part.TryGetComponent(out ControlSurface surface)) continue;
            ControlSurfaceFields* fields = SurfaceFields(surface).ptr;
            if (fields == null || !fields->flap) continue;
            fields->pitchRange = degrees;
            fields->currentPitch = -degrees;
        }
    }

    static float Read(LandingGear gear, string field) => (float)AccessTools.Field(typeof(LandingGear), field).GetValue(gear);

    static void BeforeGear(LandingGear __instance)
    {
        if (!running || !peaks.ContainsKey(__instance)) return;
        Transform cast = Cast(__instance);
        if (!Physics.Linecast(cast.position, cast.position - cast.up * Travel(__instance), out RaycastHit hit,
                ~((int)PhysicsLayers.ExclusionZonesMask | (int)PhysicsLayers.IgnoreCollisionsMask))) return;
        Vector3 velocity = Part(__instance).rb.GetPointVelocity(hit.point);
        bool tarmac = hit.collider.sharedMaterial != GameAssets.i.terrainMaterial;
        float observed = -Vector3.Dot(hit.normal, velocity) * 60f / 0.3048f;
        contactSpeeds[__instance] = new Vector2(observed, Vector3.ProjectOnPlane(velocity, hit.normal).magnitude);
        if (!contacted) { contacted = true; touchdown = observed; firstContactTime = Time.fixedTime; }
        if (contacts.Add(__instance))
            ScenarioHooks.Log.Info(Invariant($"gear-drop contact nominal={requested:0} fpm observed={observed:0.0} fpm tarmac={tarmac} compression={Travel(__instance)-hit.distance:0.000} elapsed={Time.fixedTime-started:0.0000} leg={__instance.name} gs={Vector3.ProjectOnPlane(velocity, hit.normal).magnitude:0.00} surface={hit.collider.name}"));
        float pressure = (Read(__instance, "compressionForce") + Read(__instance, "dampingForce")) / (Read(__instance, "contactArea") * 10000f);
        GlobalPosition gp = __instance.transform.GlobalPosition();
        float roughness = 5f + Mathf.Sin(gp.x * 0.8f) + Mathf.Cos(gp.z * 0.37f) + Mathf.Sin(gp.z * 0.8f) + Mathf.Cos(gp.z * 0.37f);
        float speed = Read(__instance, "wheelSpeed");
        float depth = tarmac ? 0f : Mathf.Lerp(Read(__instance, "groundDepth"), Mathf.Max(pressure * 0.003f / roughness, 0f), 3f * Time.deltaTime / Mathf.Clamp(speed * 0.1f, 1f, 3f));
        dragRatio[__instance] = tarmac ? 0f : 2.5f * depth * depth * Mathf.Abs(speed) * pressure * pressure / Read(__instance, "springRate");
    }

    static void Broke(LandingGear gear)
    {
        if (!running) return;
        broken++;
        float hinge = ((Transform)AccessTools.Field(typeof(LandingGear), "gearHinge").GetValue(gear)).localEulerAngles.x;
        ScenarioHooks.Log.Info(Invariant($"gear-drop break {gear.name} compression={Compression(gear):0.000} peak={peaks[gear]:0.000} limit={Read(gear, "maxCompression"):0.000} compressionCheck={Compression(gear) > Read(gear, "maxCompression")} hinge={hinge:0.00000} hingeCheck={hinge > 10f} dragRatio={dragRatio[gear]:0.000} dragCheck={dragRatio[gear] > 1f} hostDetached={detachedLeg == gear} host={Part(gear).name} elapsed={Time.fixedTime-started:0.000} sampleFpm={contactSpeeds[gear].x:0.0} sampleGs={contactSpeeds[gear].y:0.00}"));
    }

    static void BeforeDetached(LandingGear __instance) => detachedLeg = __instance;
    static void AfterDetached() => detachedLeg = null;

    static void JointBroke(UnitPart part)
    {
        if (!running) return;
        joints++;
        ScenarioHooks.Log.Info(Invariant($"gear-drop joint {part.name} hp={part.hitPoints:0.0}"));
    }
}
