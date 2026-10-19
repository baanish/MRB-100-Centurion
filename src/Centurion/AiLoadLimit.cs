using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The AI flies the extended wing inside its tear limits (docs/SPEC.md "Telescoping and tear limits"). While a stock AI state
/// flies a Centurion whose span is out past <see cref="WingTearRule.MinExtension"/>, or going there, the pitch stick it hands
/// the fly-by-wire is clamped so the load factor it asks for stays between <see cref="MinNz"/> and <see cref="MaxNz"/>, 1 g
/// inside each tear limit. The stock combat AI knows nothing of the tear: its radar-missile evasion dives for 10 m above the
/// terrain (AIPilotCombatModes.EvadeModeRadar, AIPilotCombatModes.cs:1160-1197) and its bomb runs push over while banked, and
/// at full span it pushed 0.5 to 0.8 of nose-down stick, which the fly-by-wire's 3.5 g per stick made -1.2 to -1.7 g held past
/// 0.5 s, tearing both stages off (runs 20261015-022637 and 20261015-025122 balance_strike_centurion). Clamping the stick, not
/// retracting the span, keeps the AI's span schedule (the AWACS orbits extended, the bomber cruises extended) and reads as a
/// pilot easing over: at 0 g a 215 m/s aircraft noses over at 2.6 deg/s. The 1 g margin is the fly-by-wire's overshoot, which
/// swung the load about 1 g either side of its target in those runs. The player's stick is never touched: flying the extended
/// wing inside its limits stays the player's skill.
/// Runs in a prefix of Aircraft.FilterInputs, where AutopilotPlane.AutoAim hands every AI state's stick to the filter
/// (AutopilotPlane.cs:121-122); the player's state calls it too (PilotPlayerState.cs:68) and is left alone.
/// </summary>
static class AiLoadLimit
{
    const string CenturionKey = "baanish_centurion";
    const float MinNz = 0f, MaxNz = 3f;

    static readonly AccessTools.FieldRef<ControlsFilter.FlyByWire, float>? GLimit = FlyByWireField("gLimitPositive");
    static readonly AccessTools.FieldRef<ControlsFilter.FlyByWire, float>? CornerSpeed = FlyByWireField("cornerSpeed");
    static readonly AccessTools.FieldRef<ControlsFilter.FlyByWire, float>? MaxPitchRate = FlyByWireField("maxPitchAngularVel");
    static readonly AccessTools.FieldRef<ControlsFilter.FlyByWire, float>? LimitFactor = FlyByWireField("limitFactorSmoothed");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-load-limit", typeof(Aircraft), nameof(Aircraft.FilterInputs),
            prefix: AccessTools.Method(typeof(AiLoadLimit), nameof(BeforeFilterInputs))),
    };

    static AccessTools.FieldRef<ControlsFilter.FlyByWire, float>? FlyByWireField(string name) =>
        AccessTools.Field(typeof(ControlsFilter.FlyByWire), name) == null ? null : AccessTools.FieldRefAccess<ControlsFilter.FlyByWire, float>(name);

    static void BeforeFilterInputs(Aircraft __instance)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-load-limit")) return;
        Aircraft aircraft = __instance;
        if (aircraft.definition == null || aircraft.definition.jsonKey != CenturionKey || !aircraft.LocalSim
            || aircraft.pilots.Length == 0 || aircraft.pilots[0].currentState is not PilotBaseState state || state is PilotPlayerState
            || GLimit == null || CornerSpeed == null || MaxPitchRate == null || LimitFactor == null
            || !aircraft.TryGetComponent(out TelescopeController telescope)
            || Mathf.Max(telescope.Extension, telescope.Command) <= WingTearRule.MinExtension)
        {
            return;
        }

        ControlsFilter filter = aircraft.GetControlsFilter();
        ControlsFilter.FlyByWire? fbw = filter != null ? filter.GetFlyByWire() : null;
        if (fbw == null || !fbw.Enabled)
        {
            return;
        }

        // FlyByWire.Filter's stick to pitch-rate gain (ControlsFilter.cs:240-253); its alpha limiter only lowers it.
        float speed = Mathf.Max(aircraft.speed, 1f);
        float corner = CornerSpeed(fbw);
        float perStick = GLimit(fbw) * 9.81f / Mathf.Max(speed, corner * 0.75f);
        float q = speed * speed * aircraft.airDensity / (corner * corner * 1.225f);
        if (q < 1f)
        {
            perStick *= Mathf.Clamp(q, 0.3f, 1f);
        }

        perStick = Mathf.Lerp(MaxPitchRate(fbw), perStick, LimitFactor(fbw));
        if (perStick < 1e-4f)
        {
            return;
        }

        // Positive stick asks a nose-down rate; a nose-up rate r adds r x speed / g to the load factor along the cockpit's up,
        // which with gravity in is what the tear reads (TelescopeController.ReadFlight).
        float upY = aircraft.cockpit.xform.up.y;
        float stickPerG = 9.81f / (speed * perStick);
        ControlInputs inputs = aircraft.GetInputs();
        float stick = inputs.pitch;
        float clamped = Mathf.Clamp(Mathf.Clamp(stick, -(MaxNz - upY) * stickPerG, -(MinNz - upY) * stickPerG), -1f, 1f);
        if (clamped == stick)
        {
            return;
        }

        inputs.pitch = clamped;
        if (CenturionPlugin.Log.StageDue("ai-load-limit"))
        {
            CenturionPlugin.Log.StageLine("ai-load-limit", Invariant(
                $"{aircraft.name} ({state.GetType().Name}): pitch stick {stick:0.00} held to {clamped:0.00} for {MinNz:0} to +{MaxNz:0} g at extension {telescope.Extension:0.00}, {speed:0} m/s, load factor {telescope.Nz:0.00}"));
        }
    }
}
