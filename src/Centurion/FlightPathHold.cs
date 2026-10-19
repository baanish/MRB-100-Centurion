using System.Runtime.CompilerServices;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Hands-off flight for the Centurion's pilot: with the stick centred, the stock fly-by-wire holds the flight path the pilot
/// let go at instead of the attitude. Stock FlyByWire turns the stick into a target pitch rate and integrates its output until
/// the rate matches (ControlsFilter.cs:236-268), so a centred stick holds the attitude, and as the speed changes the alpha
/// that lift needs changes with it: full throttle from 292 kt level climbed 1,300 m in 110 s at the attitude it was let go at
/// (tools/fm centurion_turn.PathHold). Here a stick inside <see cref="Deadband"/> becomes the stick that asks the stock filter
/// for the pitch rate which brings the flight path back to the one captured at release, plus the pitch rate a level turn
/// needs at the bank it is flying; past <see cref="ReleaseBankDeg"/> it lets go. Below <see cref="EngageAglM"/> the stock attitude hold is left alone for the flare.
/// Runs in a postfix of PilotPlayerState.PlayerAxisControls, which writes the player's stick each physics step just before
/// Aircraft.FilterInputs (PilotPlayerState.cs:60-71); AI states and the framework's fly hold don't call it, so neither is
/// touched.
/// </summary>
static class FlightPathHold
{
    const string CenturionKey = "baanish_centurion";
    const float Deadband = 0.05f;
    const float EngageAglM = 15f;
    const float ReleaseBankDeg = 60f;
    // Flight-path error to pitch rate, 1/s: a 1 deg error asks 0.4 deg/s, settling in about 3 s at the stock filter's speed.
    const float PathGain = 0.4f;
    // rad/s, 2.9 deg/s, on the path correction only. The level turn's own pitch rate rides on top: clamped with it, or taken
    // at a 33 deg bank inside the 60 deg engagement, a 45 deg turn loses 375 to 406 m in 60 s, against 9 to 12 m this way
    // (tools/fm centurion_span.py --hands-off).
    const float MaxRate = 0.05f;
    // A release within this of level holds level: nobody lets go at exactly zero sink, and the -0.3 deg a settling hold left
    // lost 1.5 m/s (300 ft/min) at every speed in game (run 20261012-231432).
    const float LevelSnapDeg = 0.5f;

    static readonly AccessTools.FieldRef<ControlsFilter.FlyByWire, float>? GLimit =
        AccessTools.Field(typeof(ControlsFilter.FlyByWire), "gLimitPositive") == null ? null : AccessTools.FieldRefAccess<ControlsFilter.FlyByWire, float>("gLimitPositive");
    static readonly AccessTools.FieldRef<ControlsFilter.FlyByWire, float>? CornerSpeed =
        AccessTools.Field(typeof(ControlsFilter.FlyByWire), "cornerSpeed") == null ? null : AccessTools.FieldRefAccess<ControlsFilter.FlyByWire, float>("cornerSpeed");

    sealed class Held
    {
        public bool Engaged;
        public float PathRad;
        /// <summary>Time.fixedTime of the last physics step the player flew; an AI state or the framework's hold skip this
        /// postfix, and the path captured before them is stale when the player takes over again.</summary>
        public float LastStep = float.NegativeInfinity;
    }

    static readonly ConditionalWeakTable<Aircraft, Held> State = new();

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("path-hold", typeof(PilotPlayerState), "PlayerAxisControls",
            postfix: AccessTools.Method(typeof(FlightPathHold), nameof(AfterPlayerAxisControls))),
    };

    internal static CenturionLog Log = null!;

    static void AfterPlayerAxisControls(ControlInputs ___controlInputs, Pilot ___pilot)
    {
        if (CenturionPlugin.FeaturesOff.Contains("path-hold")) return;
        Aircraft aircraft = ___pilot.aircraft;
        if (aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != CenturionKey || GLimit == null || CornerSpeed == null)
        {
            return;
        }

        Held held = State.GetOrCreateValue(aircraft);
        if (Time.fixedTime - held.LastStep > 1.5f * Time.fixedDeltaTime)
        {
            held.Engaged = false;
        }

        held.LastStep = Time.fixedTime;
        Vector3 velocity = aircraft.CockpitRB().velocity;
        float speed = velocity.magnitude;
        float path = Mathf.Asin(Mathf.Clamp(velocity.y / Mathf.Max(speed, 1f), -1f, 1f));
        Transform t = aircraft.transform;
        float bank = Mathf.Atan2(-t.right.y, t.up.y);
        if (Mathf.Abs(___controlInputs.pitch) > Deadband || aircraft.radarAlt < EngageAglM || speed < 1f || Mathf.Abs(bank) > ReleaseBankDeg * Mathf.Deg2Rad)
        {
            held.Engaged = false;
            return;
        }

        if (!held.Engaged)
        {
            held.Engaged = true;
            held.PathRad = Mathf.Abs(path) < LevelSnapDeg * Mathf.Deg2Rad ? 0f : path;
            Log.Stage("path-hold", Invariant($"{aircraft.name}: stick centred at {path * Mathf.Rad2Deg:0.0} deg, holding a flight path of {held.PathRad * Mathf.Rad2Deg:0.0} deg"));
        }

        float cos = Mathf.Cos(bank);
        float noseUpRate = Mathf.Clamp(PathGain * (held.PathRad - path) / cos, -MaxRate, MaxRate) + 9.81f * Mathf.Cos(path) / speed * (1f / cos - cos);

        // The stick whose target pitch rate (FlyByWire.Filter, ControlsFilter.cs:236-246) is that rate; positive stick and
        // positive local x angular velocity are nose down.
        ControlsFilter.FlyByWire fbw = aircraft.GetControlsFilter().GetFlyByWire();
        float corner = CornerSpeed(fbw);
        float perStick = GLimit(fbw) * 9.81f / Mathf.Max(speed, corner * 0.75f);
        float q = speed * speed * aircraft.airDensity / (corner * corner * 1.225f);
        if (q < 1f)
        {
            perStick *= Mathf.Clamp(q, 0.3f, 1f);
        }

        ___controlInputs.pitch = Mathf.Clamp(___controlInputs.pitch - noseUpRate / perStick, -1f, 1f);
    }
}
