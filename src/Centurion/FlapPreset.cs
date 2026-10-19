using System.Collections.Generic;
using HarmonyLib;
using NuclearOption.Jobs;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The Centurion's flaps run 30° for takeoff and 15° for landing (docs/SPEC.md, the flap row). Stock flaps have one
/// deflection: the job servoes a flap to -pitchRange while the gear is extending or down and stows it otherwise, clamping
/// it to -pitchRange..0 every step (ControlSurfaceJob_Math.cs:62-72). So after the stock UpdateJobFields fills a Centurion
/// flap's job fields (ControlSurface.cs:160-174), the preset is written into its pitchRange, the same rule for the player
/// and the AI:
/// - on the ground below <see cref="DepartureSpeedMps"/> (taxiing out, lined up, or slowed after a landing): takeoff;
/// - airborne once the flap is fully stowed, before the gear lowers: landing;
/// - otherwise the preset in the fields stands, so the takeoff preset stays through the climb's retraction, a landing's
///   rollout keeps 15° until it slows, and a go-around keeps the landing preset.
/// Only an increase is written while a flap is out, which the job servoes into; a decrease would clamp the flap there in
/// one step. The rule reads only what every peer computes for itself (radar altitude and speed from the replicated
/// transform and rigidbody, the flap's own job state from the replicated gear state), so nothing is sent over the network:
/// the lift is simulated by the owning peer alone, and elsewhere the flap angle is visual.
/// </summary>
static class FlapPreset
{
    const string CenturionKey = "baanish_centurion";
    const float TakeoffDeg = 30f, LandingDeg = 15f;
    /// <summary>Taxi speed: below it on the ground the next roll is a departure. Above the AI's taxi targets
    /// (AIPilotTaxiState.cs:408-459), well under touchdown, where 30° of flap adds about a tenth of the weight in lift.</summary>
    const float DepartureSpeedMps = 20f;
    /// <summary>Radar altitude above which the aircraft is off the runway: the takeoff AI's own test (AIPilotTakeoffState.cs:104).</summary>
    const float AirborneAltM = 1f;
    /// <summary>The flaps stow at this, 20 s from the takeoff preset, where the authored 10 deg/s took the lift away 3 s after
    /// gear up and the climbing aircraft sank (owner, 2026-10-17: "belly flop"). They extend at the authored rate.</summary>
    const float StowDegPerS = 1.5f;

    static readonly AccessTools.FieldRef<ControlSurface, PtrAllocation<ControlSurfaceFields>>? JobFields =
        AccessTools.Field(typeof(ControlSurface), "JobFields") == null ? null : AccessTools.FieldRefAccess<ControlSurface, PtrAllocation<ControlSurfaceFields>>("JobFields");
    static readonly AccessTools.FieldRef<ControlSurface, Aircraft>? AircraftOf =
        AccessTools.Field(typeof(ControlSurface), "aircraft") == null ? null : AccessTools.FieldRefAccess<ControlSurface, Aircraft>("aircraft");
    static readonly AccessTools.FieldRef<ControlSurface, float>? AuthoredServoSpeed =
        AccessTools.Field(typeof(ControlSurface), "servoSpeed") == null ? null : AccessTools.FieldRefAccess<ControlSurface, float>("servoSpeed");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("flap-preset", typeof(ControlSurface), nameof(ControlSurface.UpdateJobFields),
            postfix: AccessTools.Method(typeof(FlapPreset), nameof(AfterUpdateJobFields))),
    };

    /// <summary>The readout's flap_deg: the furthest any flap is out, degrees down.</summary>
    internal static unsafe void Read(Aircraft aircraft, Dictionary<string, object> state)
    {
        if (JobFields == null) return;
        float deg = 0f;
        // Each flap's ControlSurface sits on its own part (CenturionAuthor's Surfaces), which complex physics takes out of the
        // aircraft's hierarchy (AeroPart.cs:334), so the parts are walked rather than the root's children.
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part == null || !part.TryGetComponent(out ControlSurface surface)) continue;
            ControlSurfaceFields* fields = JobFields(surface).ptr;
            if (fields != null && fields->flap) deg = Mathf.Max(deg, -fields->currentPitch);
        }
        state["flap_deg"] = AircraftReadout.Round(deg);
    }

    internal static unsafe bool ReadMotion(ControlSurface surface, out float angle, out float speed)
    {
        angle = speed = 0f;
        if (JobFields == null) return false;
        ControlSurfaceFields* fields = JobFields(surface).ptr;
        if (fields == null || !fields->flap || fields->IsDetached) return false;
        angle = -fields->currentPitch;
        speed = fields->servoSpeed;
        return true;
    }

    static unsafe void AfterUpdateJobFields(ControlSurface __instance)
    {
        if (CenturionPlugin.FeaturesOff.Contains("flap-preset")) return;
        if (JobFields == null || AircraftOf == null) return;
        ControlSurfaceFields* fields = JobFields(__instance).ptr;
        if (fields == null || !fields->flap) return;
        Aircraft aircraft = AircraftOf(__instance);
        if (aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != CenturionKey) return;

        SurfaceMotionSound.For(aircraft);

        // The job moves a flap at servoSpeed both ways (ControlSurfaceJob_Math.cs:62-72), copied once when its fields are
        // made (ControlSurface.cs:147), so it is set every step: out at the authored rate while the gear is extending or
        // down, in at StowDegPerS otherwise.
        bool gearDown = fields->gearState == LandingGear.GearState.Extending || fields->gearState == LandingGear.GearState.LockedExtended;
        if (AuthoredServoSpeed != null)
            fields->servoSpeed = gearDown ? AuthoredServoSpeed(__instance) : StowDegPerS;

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
