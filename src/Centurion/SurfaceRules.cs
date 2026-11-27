using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using NuclearOption.Jobs;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The Centurion's two rules on its stock control surfaces, written into a surface's job fields after the stock
/// ControlSurface.UpdateJobFields fills them (ControlSurface.cs:160-174) and before the job turns the surface. The game
/// calls that for every surface of every aircraft every physics step (ControlJobSettings.cs:127), so the postfix returns
/// on one dictionary miss for any surface not registered at first sight. Both rules run on every peer from what each
/// computes for itself, so nothing is sent: the lift is simulated by the owning peer alone, and elsewhere the angle is visual.
/// <para>
/// Spoilers rise only, on the side whose aileron goes up. Stock ControlSurface has no one-sided deflection: each channel
/// servoes to input x range and clamps to +-|range| (ControlSurfaceJob_Math.cs:52-60; brakeRange is copied into the job
/// fields but never read), and the one-sided split only follows idle throttle and yaw (:64-72). So the roll input that would
/// lower a spoiler is zeroed in its fields; the job still servoes it back down at servoSpeed.
/// </para>
/// <para>
/// Flaps run 30° for takeoff and 15° for landing (docs/SPEC.md, the flap row). Stock flaps have one deflection: the job
/// servoes a flap to -pitchRange while the gear is extending or down and stows it otherwise, clamping it to -pitchRange..0
/// every step (ControlSurfaceJob_Math.cs:62-72). So the preset is written into its pitchRange, the same rule for the player
/// and the AI:
/// - on the ground below <see cref="DepartureSpeedMps"/> (taxiing out, lined up, or slowed after a landing): takeoff;
/// - airborne once the flap is fully stowed, before the gear lowers: landing;
/// - otherwise the preset in the fields stands, so the takeoff preset stays through the climb's retraction, a landing's
///   rollout keeps 15° until it slows, and a go-around keeps the landing preset.
/// Only an increase is written while a flap is out, which the job servoes into; a decrease would clamp the flap there in
/// one step.
/// </para>
/// </summary>
static class SurfaceRules
{
    const float TakeoffDeg = 30f, LandingDeg = 15f;
    /// <summary>Taxi speed: below it on the ground the next roll is a departure. Above the AI's taxi targets
    /// (AIPilotTaxiState.cs:408-459), well under touchdown, where 30° of flap adds about a tenth of the weight in lift.</summary>
    const float DepartureSpeedMps = 20f;
    /// <summary>Radar altitude above which the aircraft is off the runway: the takeoff AI's own test (AIPilotTakeoffState.cs:104).</summary>
    const float AirborneAltM = 1f;
    /// <summary>The flaps stow at this, 20 s from the takeoff preset, where the authored 10 deg/s took the lift away 3 s after
    /// gear up and the climbing aircraft sank (owner, 2026-10-17: "belly flop"). They extend at the authored rate.</summary>
    const float StowDegPerS = 1.5f;

    internal static readonly AccessTools.FieldRef<ControlSurface, PtrAllocation<ControlSurfaceFields>>? JobFields =
        AccessTools.Field(typeof(ControlSurface), "JobFields") == null ? null : AccessTools.FieldRefAccess<ControlSurface, PtrAllocation<ControlSurfaceFields>>("JobFields");
    static readonly AccessTools.FieldRef<ControlSurface, GameObject>? VisibleMesh =
        AccessTools.Field(typeof(ControlSurface), "visibleMesh") == null ? null : AccessTools.FieldRefAccess<ControlSurface, GameObject>("visibleMesh");
    static readonly AccessTools.FieldRef<ControlSurface, float>? AuthoredServoSpeed =
        AccessTools.Field(typeof(ControlSurface), "servoSpeed") == null ? null : AccessTools.FieldRefAccess<ControlSurface, float>("servoSpeed");

    /// <summary>A registered surface: a spoiler's sign of the roll input that raises it, or a flap's aircraft and authored servo speed.</summary>
    sealed class Rule
    {
        public Aircraft Aircraft = null!;
        public float Rise;
        public bool Flap;
        public float AuthoredServo;
    }

    static readonly Dictionary<ControlSurface, Rule> Rules = new();

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("surface-rules", typeof(ControlSurface), nameof(ControlSurface.UpdateJobFields),
            postfix: AccessTools.Method(typeof(SurfaceRules), nameof(AfterUpdateJobFields))),
    };

    /// <summary>
    /// The aircraft's flaps and spoilers, through partLookup: complex physics has unparented every part onto its own
    /// rigidbody (AeroPart.CreateRB, AeroPart.cs:334), so the surfaces are no longer the aircraft's children. The job turns
    /// visibleMesh by the summed angle about its local X (ControlSurfaceJob_Math.cs:62-63), so a spoiler rises for the roll
    /// input whose angle (input x rollRange) lifts its trailing edge, read off the hinge in the aircraft's frame.
    /// </summary>
    internal static unsafe void Register(Aircraft aircraft)
    {
        if (JobFields == null || VisibleMesh == null)
        {
            CenturionPlugin.Log.Warning("surface rules: ControlSurface.JobFields or visibleMesh is missing in this game build, so the spoilers deflect both ways and the flaps keep one angle");
            return;
        }

        // Every ControlSurface on a part: a flap whose fairings turn on their own hinges carries one more per fairing
        // (CenturionAuthor.AddFairings), and each must take the flap's presets and stow.
        foreach (ControlSurface surface in aircraft.partLookup.Where(p => p != null).SelectMany(p => p.GetComponents<ControlSurface>()))
        {
            UnitPart part = surface.GetComponent<UnitPart>();
            ControlSurfaceFields* fields = JobFields(surface).ptr;
            if (fields == null)
            {
                continue;
            }

            if (fields->flap)
            {
                Rules[surface] = new Rule { Aircraft = aircraft, Flap = true, AuthoredServo = AuthoredServoSpeed != null ? AuthoredServoSpeed(surface) : float.NaN };
            }
            else if (part.name.StartsWith("spoiler_"))
            {
                Transform hinge = VisibleMesh(surface).transform;
                Vector3 aft = -aircraft.transform.forward;
                float trailingEdgeUp = Mathf.Sign(Vector3.Dot(Quaternion.AngleAxis(1f, hinge.right) * aft - aft, aircraft.transform.up));
                float rise = Mathf.Sign(fields->rollRange) * trailingEdgeUp;
                Rules[surface] = new Rule { Aircraft = aircraft, Rise = rise };
                CenturionPlugin.Log.Info(Invariant($"spoilers: {surface.name} on {aircraft.name} rises on roll input {(rise > 0 ? "+" : "-")}"));
            }
        }
    }

    /// <summary>The aircraft's surfaces leave the rules with it, and any surface already destroyed.</summary>
    internal static void Forget(Aircraft aircraft)
    {
        foreach (ControlSurface gone in Rules.Where(r => r.Key == null || r.Value.Aircraft == aircraft).Select(r => r.Key).ToList())
        {
            Rules.Remove(gone);
        }
    }

    /// <summary>A flap's angle out, degrees, and its servo rate, for the flap motion sound; false for anything else.</summary>
    internal static unsafe bool ReadFlapMotion(ControlSurface surface, out float angle, out float speed)
    {
        angle = speed = 0f;
        if (JobFields == null) return false;
        ControlSurfaceFields* fields = JobFields(surface).ptr;
        if (fields == null || !fields->flap || fields->IsDetached) return false;
        angle = -fields->currentPitch;
        speed = fields->servoSpeed;
        return true;
    }

    /// <summary>A flap's commanded angle out, degrees: its preset (pitchRange, 15 for landing or 30 for takeoff) while the
    /// gear is extending or down, which the job servoes it to, else 0 (stowed); false for anything else. For the cockpit's
    /// flap lever (<see cref="CockpitLevers"/>).</summary>
    internal static unsafe bool ReadFlapCommand(ControlSurface surface, out float angle)
    {
        angle = 0f;
        if (JobFields == null) return false;
        ControlSurfaceFields* fields = JobFields(surface).ptr;
        if (fields == null || !fields->flap || fields->IsDetached) return false;
        bool gearDown = fields->gearState == LandingGear.GearState.Extending || fields->gearState == LandingGear.GearState.LockedExtended;
        angle = gearDown ? fields->pitchRange : 0f;
        return true;
    }

#if CENTURION_DEV
    /// <summary>The readout's flap_deg: the furthest any flap is out, degrees down.</summary>
    internal static void Read(Aircraft aircraft, Dictionary<string, object> state)
    {
        float deg = 0f;
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part != null && part.TryGetComponent(out ControlSurface surface) && ReadFlapMotion(surface, out float angle, out _)) deg = Mathf.Max(deg, angle);
        }
        state["flap_deg"] = AircraftReadout.Round(deg);
    }
#endif

    static unsafe void AfterUpdateJobFields(ControlSurface __instance)
    {
        if (Rules.Count == 0 || !Rules.TryGetValue(__instance, out Rule rule))
        {
            return;
        }

        ControlSurfaceFields* fields = JobFields!(__instance).ptr;
        if (fields == null)
        {
            return;
        }

        if (!rule.Flap)
        {
            if (fields->controlInputs.roll * rule.Rise < 0f)
            {
                fields->controlInputs.roll = 0f;
            }

            return;
        }

        // The job moves a flap at servoSpeed both ways (ControlSurfaceJob_Math.cs:62-72), copied once when its fields are
        // made (ControlSurface.cs:147), so it is set every step: out at the authored rate while the gear is extending or
        // down, in at StowDegPerS otherwise.
        bool gearDown = fields->gearState == LandingGear.GearState.Extending || fields->gearState == LandingGear.GearState.LockedExtended;
        if (!float.IsNaN(rule.AuthoredServo))
            fields->servoSpeed = gearDown ? rule.AuthoredServo : StowDegPerS;

        Aircraft aircraft = rule.Aircraft;
        float preset = fields->pitchRange;
        if (aircraft.radarAlt <= AirborneAltM && aircraft.speed < DepartureSpeedMps)
            preset = TakeoffDeg;
        else if (aircraft.radarAlt > AirborneAltM && fields->currentPitch == 0f)
            preset = LandingDeg;
        if (preset == fields->pitchRange) return;

        fields->pitchRange = preset;
        CenturionPlugin.Log.Stage("flap-preset", Invariant(
            $"{aircraft.name} {(preset == TakeoffDeg ? "takeoff" : "landing")} {preset:F0} deg at radar alt {aircraft.radarAlt:F1} m, {aircraft.speed:F1} m/s, flap {-fields->currentPitch:F1} deg"));
    }
}
