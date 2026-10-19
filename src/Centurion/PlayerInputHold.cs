using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// Debug.PitchCommand, Debug.RollCommand, Debug.YawCommand and Debug.ThrottleCommand: hold the local player's pitch, roll, yaw and throttle inputs
/// for scenarios, since
/// the framework's `act hold` holds only Throttle and its `fly` modes hand the pilot to the game's AI. Unlike Custom
/// Axis 1 (Debug.SpanCommand), PilotPlayerState rewrites them from the player's controls: pitch, roll and yaw in PlayerAxisControls
/// every physics step, just before Aircraft.FilterInputs reads it, and throttle in PlayerThrottleAxis1Controls every
/// frame. So each value is written in a postfix of the method that writes it, and a plain FixedUpdate write would lose.
/// Pitch is in the game's sign, negative nose-up: ControlsFilter's LimitAoA pushes the nose down by adding positive
/// pitch, and its fly-by-wire turns pitch into a target pitch rate that, with the nose wheel loaded, it clamps to
/// nose-up only (negative local x).
/// </summary>
static class PlayerInputHold
{
    /// <summary>The value that leaves an input to the player's controls.</summary>
    public const float Off = -999f;

    internal static ConfigEntry<bool> Diagnostics = null!;
    internal static ConfigEntry<float> Pitch = null!;
    internal static ConfigEntry<float> Roll = null!;
    internal static ConfigEntry<float> Yaw = null!;
    internal static ConfigEntry<float> Throttle = null!;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("debug-inputs", typeof(PilotPlayerState), "PlayerAxisControls",
            postfix: AccessTools.Method(typeof(PlayerInputHold), nameof(HoldPitchAndThrottle))),
        new("debug-inputs", typeof(PilotPlayerState), "PlayerThrottleAxis1Controls",
            postfix: AccessTools.Method(typeof(PlayerInputHold), nameof(HoldThrottle))),
    };

    /// <summary>
    /// Writes throttle here too, every physics step: PlayerControls skips the throttle while the game has flight controls
    /// off. Pitch, roll and yaw are never written outside the physics step, where they would overwrite the fly-by-wire's output.
    /// </summary>
    static void HoldPitchAndThrottle(ControlInputs ___controlInputs, Pilot ___pilot)
    {
        if (CenturionPlugin.FeaturesOff.Contains("debug-inputs")) return;
        HoldThrottle(___controlInputs, ___pilot);
        if (Pitch.Value != Off && IsLocalPlayer(___pilot))
        {
            ___controlInputs.pitch = Mathf.Clamp(Pitch.Value, -1f, 1f);
        }

        if (Roll.Value != Off && IsLocalPlayer(___pilot))
        {
            ___controlInputs.roll = Mathf.Clamp(Roll.Value, -1f, 1f);
        }

        if (Yaw.Value != Off && IsLocalPlayer(___pilot))
        {
            ___controlInputs.yaw = Mathf.Clamp(Yaw.Value, -1f, 1f);
        }
    }

    static void HoldThrottle(ControlInputs ___controlInputs, Pilot ___pilot)
    {
        if (CenturionPlugin.FeaturesOff.Contains("debug-inputs")) return;
        if (Throttle.Value != Off && IsLocalPlayer(___pilot))
        {
            ___controlInputs.throttle = Mathf.Clamp01(Throttle.Value);
        }
    }

    static bool IsLocalPlayer(Pilot pilot) =>
        Diagnostics.Value && GameManager.GetLocalAircraft(out Aircraft aircraft) && aircraft == pilot.aircraft;
}
