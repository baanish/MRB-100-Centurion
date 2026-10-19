using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Debug.* hooks for scenarios that the framework can't set up, applied every physics step while Diagnostics.Enabled is
/// on. SpeedHoldMps moves the throttle, BallastKg adds
/// mass the way stores do, FlightAssist flips the stock pitch-limiter switch, Loadout picks the stores the loadout menu would,
/// Ignition throws the stock engine switch and CockpitLook turns the cockpit camera as the player's view controls would.
/// EjectionCamera follows the local dismounted pilot for screenshots after the sortie ends.
/// </summary>
static class ScenarioHooks
{
    // Autothrottle time constants, s, and the most acceleration a speed error asks, m/s2: 3 lets a big slow-down idle the
    // engines, which opens the airbrakes (splits open at exactly zero throttle, ControlSurfaceJob_Math.cs:64-72); a 0.5 cap
    // took 200 s to bring 240 m/s to 150 at 6 km (centurion_m2_paired_6km). A fixed PI on the speed error
    // (P 0.03, I 0.003 per m/s) was tuned for 4.4 m/s2 per unit throttle at 137 t low down; at 15 km and 159 t a unit buys
    // 1.6 m/s2, and at the best loiter speed drag barely changes with speed, so that loop rang with a 75 s period through the
    // altitude hold's climbs and never settled (GE.1 on step 6.1; tools/fm/centurion_speed_hold.py reproduces both).
    const float SpeedTau = 8f, AccelTau = 2f, AccelFilterTau = 1f, AccelMax = 3f;

    internal static ConfigEntry<bool> Diagnostics = null!;
    internal static ConfigEntry<float> SpeedHoldMps = null!;
    internal static ConfigEntry<bool> SpeedHoldEas = null!;
    internal static ConfigEntry<float> BallastKg = null!;
    internal static ConfigEntry<string> FlightAssist = null!;
    internal static ConfigEntry<string> Loadout = null!;
    internal static ConfigEntry<string> Ignition = null!;
    internal static ConfigEntry<string> CockpitLook = null!;
    internal static CenturionLog Log = null!;

    static FieldInfo? flyThrottle;
    static PropertyInfo? flyEngaged;
    static bool flyLookedUp;
    // The speed hold's state belongs to the aircraft it was flying; another local aircraft starts it afresh.
    static Aircraft? speedHeld;
    static float throttleTrim = float.NaN, lastSpeed, speedRate;
    // Per aircraft, since the mass stays on an aircraft the player leaves and must not be added again on return; a
    // destroyed aircraft's entry goes when the next one is added.
    static readonly Dictionary<Aircraft, float> ballastApplied = new();
    // The Debug.Loadout value last applied, so each change applies once; blank forgets it.
    static string loadoutApplied = "";
    static float ignitionAskedAt = float.NegativeInfinity;
    static readonly FieldInfo PanView = AccessTools.Field(typeof(CameraCockpitState), "panView");
    static readonly FieldInfo TiltView = AccessTools.Field(typeof(CameraCockpitState), "tiltView");
    static readonly FieldInfo ViewOffset = AccessTools.Field(typeof(CameraCockpitState), "viewOffset");
    static string lookApplied = "";
    static ConfigEntry<bool>? ejectionCamera;

    public static void FixedUpdate()
    {
        ejectionCamera ??= Diagnostics.ConfigFile.Bind("Debug", "EjectionCamera", false,
            "With Diagnostics.Enabled, orbit the local ejected pilot at 120 m and keep the delayed sortie map closed for screenshots");
        if (!Diagnostics.Value)
        {
            return;
        }

        if (ejectionCamera.Value && GameManager.GetLocalPilotDismounted(out PilotDismounted pilot))
        {
            CameraStateManager cam = SceneSingleton<CameraStateManager>.i;
            if (cam != null)
            {
                if (cam.followingUnit != pilot) cam.SetFollowingUnit(pilot);
                if (cam.currentState != cam.controlledState)
                {
                    cam.SwitchState(cam.controlledState);
                    cam.controlledState.SwitchPivotUp();
                    cam.controlledState.SetCustomPivot(Vector3.zero, new Vector3(30f, 200f + 180f, 0f));
                    cam.controlledState.SetCustomTransform(new Vector3(0f, 0f, -120f), Vector3.zero);
                }

                // Aircraft's delayed ShowMap otherwise covers the chutes five seconds after the sortie ends.
                if (DynamicMap.mapMaximized) SceneSingleton<DynamicMap>.i.Minimize();
            }
        }

        if (!GameManager.GetLocalAircraft(out Aircraft aircraft))
        {
            return;
        }

        HoldSpeed(aircraft);
        TankDiagnostics.ApplyHit(aircraft);
        HoldBallast(aircraft);
        HoldLoadout(aircraft);
        HoldIgnition(aircraft);
        HoldCockpitLook();
        if (FlightAssist.Value != "pilot" && aircraft.flightAssist != (FlightAssist.Value == "on"))
        {
            aircraft.SetFlightAssist(FlightAssist.Value == "on");
            Log.Stage("debug-flight-assist", $"Debug.FlightAssist: flight assist {FlightAssist.Value}, now {(aircraft.flightAssist ? "on" : "off")}");
        }
    }

    /// <summary>
    /// Debug.SpeedHoldMps: an autothrottle on true airspeed (or EAS with Debug.SpeedHoldEas), for comparing two states at one
    /// speed (G2.2 to G2.5, G2.7, GE.1). The speed error asks an acceleration (SpeedTau); the throttle's trim integrates the
    /// miss between that and the measured rate of change of speed (AccelTau); the power the climb takes, g vs / V, rides on
    /// top, so a climb the altitude hold flies costs throttle, not speed. Both turn into throttle through the thrust a unit of
    /// throttle buys now (Turbofan thrust is (staticThrust x altitude and speed factor) x spool, Turbofan.cs:396-398, and spool
    /// moves one for one with throttle), which keeps the loop the same speed at 15 km as at 6. The framework's fly hold pins the
    /// throttle it was given every frame (NoAgenticFramework Fly.ThrottlePostfix, Priority.Last), so this moves that pinned
    /// value; it acts only while the hold flies.
    /// </summary>
    static void HoldSpeed(Aircraft aircraft)
    {
        if (!flyLookedUp)
        {
            flyLookedUp = true;
            Type? fly = AccessTools.TypeByName("NoAgenticFramework.Fly");
            flyThrottle = fly == null ? null : AccessTools.Field(fly, "throttle");
            flyEngaged = fly == null ? null : AccessTools.Property(fly, "Engaged");
            if (flyThrottle == null || flyEngaged == null)
            {
                Log.Info("Debug.SpeedHoldMps: NO-Agentic-Framework's fly hold isn't loaded; the speed hold stays off");
            }
        }

        if (aircraft != speedHeld)
        {
            speedHeld = aircraft;
            throttleTrim = float.NaN;
        }

        float target = SpeedHoldMps.Value;
        if (target <= 0f || flyThrottle == null || flyEngaged == null || !(bool)flyEngaged.GetValue(null))
        {
            throttleTrim = float.NaN;
            return;
        }

        float perUnit = 0f; // m/s2 per unit throttle
        foreach (IEngine engine in aircraft.engineStates) // Turbofans list themselves here, not in engines (Turbofan.cs:163)
        {
            if (engine is Turbofan turbofan && turbofan.GetSpoolPercentage() > 0.01f)
            {
                perUnit += turbofan.GetThrust() / turbofan.GetSpoolPercentage();
            }
        }

        perUnit /= aircraft.GetMass();
        if (perUnit <= 0f)
        {
            throttleTrim = float.NaN;
            Log.Stage("debug-speed-hold", "no turbofan thrust to scale by; the throttle stays where the hold pinned it");
            return;
        }

        float altitude = aircraft.transform.GlobalPosition().y;
        Vector3 air = aircraft.CockpitRB().velocity - aircraft.GetWindVelocity();
        float tas = Mathf.Max(air.magnitude, 1f);
        float speed = SpeedHoldEas.Value ? tas * Mathf.Sqrt(LevelInfo.GetAirDensity(altitude) / LevelInfo.GetAirDensity(0f)) : tas;
        float dt = Time.fixedDeltaTime;
        float climb = Physics.gravity.magnitude * air.y / tas / perUnit;
        if (float.IsNaN(throttleTrim))
        {
            throttleTrim = (float)flyThrottle.GetValue(null) - climb; // start from the throttle the hold was given
            lastSpeed = speed;
            speedRate = 0f;
        }

        speedRate += ((speed - lastSpeed) / dt - speedRate) * dt / AccelFilterTau;
        lastSpeed = speed;
        float ask = Mathf.Clamp((target - speed) / SpeedTau, -AccelMax, AccelMax);
        throttleTrim = Mathf.Clamp(throttleTrim + (ask - speedRate) / (perUnit * AccelTau) * dt, -climb, 1f - climb);
        float throttle = Mathf.Clamp01(throttleTrim + climb);
        flyThrottle.SetValue(null, throttle);
        Log.Stage("debug-speed-hold", Invariant($"{(SpeedHoldEas.Value ? "EAS" : "TAS")} {speed:0.0} m/s, target {target:0.0}, throttle {throttle:0.000}"));
    }

    /// <summary>
    /// Debug.BallastKg: payload mass on the centre fuselage (the root part), through UnitPart.ModifyMass as stores add theirs
    /// (UnitPart.cs:270-277). Stock bay weapons carry at most 12 t, so maximum takeoff mass (G2.6) needs it.
    /// </summary>
    static void HoldBallast(Aircraft aircraft)
    {
        ballastApplied.TryGetValue(aircraft, out float applied);
        float target = Mathf.Max(BallastKg.Value, 0f);
        if (Mathf.Approximately(target, applied) || !aircraft.TryGetComponent(out AeroPart root))
        {
            return;
        }

        root.ModifyMass(target - applied);
        Log.Info(Invariant($"Debug.BallastKg: {target:0} kg on {root.name} (was {applied:0}); aircraft mass {aircraft.GetMass():0} kg"));
        foreach (Aircraft gone in ballastApplied.Keys.Where(a => a == null).ToList())
        {
            ballastApplied.Remove(gone);
        }

        ballastApplied[aircraft] = target;
    }

    /// <summary>
    /// Debug.Loadout: on the host, a StandardLoadout by name (or the aircraft's first loadout for "empty") copied into the
    /// aircraft's loadout, the loadout menu's path (LoadoutSelector.UpdateWeapons): the host's setter raises the change the
    /// weapon manager respawns the stores on, and the loadout syncs to the other peers.
    /// </summary>
    static void HoldLoadout(Aircraft aircraft)
    {
        string wanted = Loadout.Value;
        if (wanted == "")
        {
            loadoutApplied = "";
            return;
        }

        if (wanted == loadoutApplied || !aircraft.IsHost)
        {
            return;
        }

        loadoutApplied = wanted;
        AircraftParameters parameters = aircraft.definition.aircraftParameters;
        NuclearOption.SavedMission.Loadout? source = wanted == "empty"
            ? parameters.loadouts[0]
            : parameters.StandardLoadouts.FirstOrDefault(l => l.Name == wanted)?.loadout;
        if (source == null)
        {
            Log.Warning($"Debug.Loadout: {aircraft.definition.unitName} has no standard loadout named {wanted}");
            return;
        }

        aircraft.Networkloadout = new NuclearOption.SavedMission.Loadout { weapons = new List<WeaponMount>(source.weapons) };
        Log.Info($"Debug.Loadout: {wanted} on {aircraft.name}");
    }

    /// <summary>
    /// Debug.CockpitLook: "pan,tilt,raise" holds the cockpit camera's view where the player's Pan View, Tilt View and Move
    /// Vertical controls would put it (CameraCockpitState.cs:150-170): pan degrees right, tilt degrees down, the head raised
    /// 0 to 0.15 m. The camera turns toward it at the player's view smoothing; it eases back to centre once blank.
    /// </summary>
    static void HoldCockpitLook()
    {
        string wanted = CockpitLook.Value.Trim();
        CameraStateManager cam = SceneSingleton<CameraStateManager>.i;
        if (cam == null || cam.currentState != cam.cockpitState)
        {
            return;
        }

        if (wanted == "")
        {
            if (lookApplied != "")
            {
                PanView.SetValue(cam.cockpitState, 0f);
                TiltView.SetValue(cam.cockpitState, 0f);
                ViewOffset.SetValue(cam.cockpitState, 0f);
                lookApplied = "";
                Log.Info("Debug.CockpitLook: the view back to centre");
            }

            return;
        }

        string[] parts = wanted.Split(',');
        if (parts.Length != 3 || !float.TryParse(parts[0], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float pan)
            || !float.TryParse(parts[1], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float tilt)
            || !float.TryParse(parts[2], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float raise))
        {
            if (wanted != lookApplied)
            {
                lookApplied = wanted;
                Log.Warning($"Debug.CockpitLook: \"{wanted}\" isn't pan,tilt,raise");
            }

            return;
        }

        PanView.SetValue(cam.cockpitState, Mathf.Clamp(pan, -165f, 165f));
        TiltView.SetValue(cam.cockpitState, Mathf.Clamp(tilt, -65f, 65f));
        ViewOffset.SetValue(cam.cockpitState, Mathf.Clamp(raise, 0f, 0.15f));
        if (wanted != lookApplied)
        {
            lookApplied = wanted;
            Log.Info(Invariant($"Debug.CockpitLook: pan {pan:0} deg, tilt {tilt:0} deg, head raised {raise:0.00} m"));
        }
    }

    /// <summary>
    /// Debug.Ignition: the stock engine switch (the server flips the ignition on the owner's call), at most once a second
    /// while the ignition differs, since the call is rate-limited (Aircraft.cs:803).
    /// </summary>
    static void HoldIgnition(Aircraft aircraft)
    {
        if (Ignition.Value == "pilot" || aircraft.Ignition == (Ignition.Value == "on") || Time.fixedTime - ignitionAskedAt < 1f)
        {
            return;
        }

        ignitionAskedAt = Time.fixedTime;
        aircraft.CmdToggleIgnition();
        Log.Stage("debug-ignition", $"Debug.Ignition: ignition {Ignition.Value}, was {(aircraft.Ignition ? "on" : "off")}");
    }
}
