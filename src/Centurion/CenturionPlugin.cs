using System;
using System.Collections.Generic;
using System.Linq;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The MRB-100 Centurion plugin: config (BepInEx/config/baanish.centurion.cfg), the "[Centurion]" logger, the Harmony
/// install, the telescoping wing (<see cref="TelescopeController"/>), and the diagnostics behind Diagnostics.Enabled: the
/// per-mission geometry log, the damage log, AgenticState() for NO-Agentic-Framework, and the Debug.* holds; Capture.* records
/// playtest video (<see cref="FrameCapture"/>).
/// </summary>
[BepInPlugin(Guid, "MRB-100 Centurion", Version)]
public sealed class CenturionPlugin : BaseUnityPlugin
{
    public const string Guid = "baanish.centurion";
    public const string Version = "0.1.2";

    /// <summary>
    /// Seconds between a mission starting and the geometry log, so airbases a client or a carrier registers after the
    /// mission start are included.
    /// </summary>
    const float GeometryDelayS = 3f;

    /// <summary>Every Harmony patch the mod installs; the C-RAM adds its two (systems-design section 5).</summary>
    static readonly PatchTarget[] PatchTargets = PlayerInputHold.PatchTargets.Concat(TelescopeController.PatchTargets).Concat(SpoilerRule.PatchTargets).Concat(FlightPathHold.PatchTargets).Concat(SpanGauge.PatchTargets)
        .Concat(CenturionSystems.PatchTargets).Concat(RadarSuite.PatchTargets).Concat(CramPatches.PatchTargets).Concat(PowerReadout.PatchTargets).Concat(MissileJamming.PatchTargets)
        .Concat(CenturionAwacsState.PatchTargets).Concat(AiAirfieldRules.PatchTargets).Concat(BayLoadoutRule.PatchTargets).Concat(FlapPreset.PatchTargets)
        .Concat(OwnerState.PatchTargets).Concat(StartupHold.PatchTargets).Concat(BombRelease.PatchTargets)
        .Concat(CombatHeightHold.PatchTargets).Concat(AiLoadLimit.PatchTargets).Concat(AiCramHold.PatchTargets).Concat(AiBombExtend.PatchTargets)
        .Concat(AiHighStrike.PatchTargets).Concat(AttackerFire.PatchTargets)
        .ToArray();

    internal static CenturionLog Log = null!;

    /// <summary>Features whose patch target was missing or failed; their code stands down.</summary>
    internal static HashSet<string> FeaturesOff = new();

    ConfigEntry<bool> diagnostics = null!;
    ConfigEntry<bool> stageLogging = null!;
    ConfigEntry<float> spanCommand = null!;
    Harmony harmony = null!;
    DamageLog damageLog = null!;
    bool missionRunning;
    float geometryLogAt = float.PositiveInfinity;

    void Awake()
    {
        Log = new CenturionLog(Logger);
        damageLog = new DamageLog(Log);
        diagnostics = Config.Bind("Diagnostics", "Enabled", false,
            "Log runways, map bounds and medium hangars on each mission load, fill AgenticState(), and apply the Debug.* settings");
        stageLogging = Config.Bind("Diagnostics", "StageLogging", true,
            "Log each stage the mod crosses (spawn, damage, physics mode, extension, tear, radar, C-RAM, AI), at most one line per key per second");
        spanCommand = Config.Bind("Debug", "SpanCommand", -1f, new ConfigDescription(
            "0 to 1 is the local player Centurion's span command in place of its pilot's axis and the AI schedule (scenarios); the hangar guard and a lost span still hold it at 0; below 0 is off",
            new AcceptableValueRange<float>(-1f, 1f)));
        PlayerInputHold.Diagnostics = diagnostics;
        TelescopeController.Log = Log;
        SpoilerRule.Log = Log;
        FlightPathHold.Log = Log;
        TelescopeController.Diagnostics = diagnostics;
        TelescopeController.SpanCommand = spanCommand;
        TelescopeController.PitchBudgetEnabled = Config.Bind("Diagnostics", "PitchBudget", false,
            "With Diagnostics.Enabled, compute the local player Centurion's pitch-moment budget every physics step (complex physics) for AgenticState()'s budget_* keys");
        SortieLog.Enabled = Config.Bind("Diagnostics", "SortieLog", false,
            "Log one sortie: line per event of every Centurion this peer simulates (spawn, takeoff, AI state and target, AWACS phase, releases, kills, damage, loss, a 60 s snapshot) and a summary per Centurion when the mission stops");
        TelescopeController.StageMaxAngularVelocity = Config.Bind("Debug", "StageMaxAngularVelocity", -1f, new ConfigDescription(
            "Above 0, replaces the local player Centurion's attached stage 1 Rigidbody.maxAngularVelocity, rad/s (complex physics); 14, the game's default, brings back the clamp that drops its centerOfLift torque; 0 or below keeps the mod's 1000",
            new AcceptableValueRange<float>(-1f, 100000f)));
        PlayerInputHold.Pitch = Config.Bind("Debug", "PitchCommand", PlayerInputHold.Off, new ConfigDescription(
            "-1 to 1 holds the local player aircraft's pitch input at this, in the game's sign: negative is nose-up, -1 full nose-up; -999 is off",
            new AcceptableValueRange<float>(PlayerInputHold.Off, 1f)));
        PlayerInputHold.Throttle = Config.Bind("Debug", "ThrottleCommand", PlayerInputHold.Off, new ConfigDescription(
            "0 to 1 holds the local player aircraft's throttle input at this; -999 is off",
            new AcceptableValueRange<float>(PlayerInputHold.Off, 1f)));
        PlayerInputHold.Roll = Config.Bind("Debug", "RollCommand", PlayerInputHold.Off, new ConfigDescription(
            "-1 to 1 holds the local player aircraft's roll input at this, positive right wing down; -999 is off",
            new AcceptableValueRange<float>(PlayerInputHold.Off, 1f)));
        PlayerInputHold.Yaw = Config.Bind("Debug", "YawCommand", PlayerInputHold.Off, new ConfigDescription(
            "-1 to 1 holds the local player aircraft's yaw input at this, positive nose right; -999 is off",
            new AcceptableValueRange<float>(PlayerInputHold.Off, 1f)));
        ScenarioHooks.Log = Log;
        ScenarioHooks.Diagnostics = diagnostics;
        TankDiagnostics.Hit = Config.Bind("Debug", "TankHit", "", new ConfigDescription(
            "With Diagnostics.Enabled, once per change apply stock net damage to the named tank part on the local server Centurion; blank rearms",
            new AcceptableValueList<string>("", "fuselage_M", "fuselage_F", "fuselage_R", "tailcone")));
        ScenarioHooks.SpeedHoldMps = Config.Bind("Debug", "SpeedHoldMps", 0f, new ConfigDescription(
            "Above 0, moves the throttle NO-Agentic-Framework's fly hold pins so the local player aircraft holds this true airspeed (EAS with SpeedHoldEas); 0 is off",
            new AcceptableValueRange<float>(0f, 400f)));
        ScenarioHooks.SpeedHoldEas = Config.Bind("Debug", "SpeedHoldEas", false, "SpeedHoldMps is equivalent airspeed instead of true airspeed");
        ScenarioHooks.BallastKg = Config.Bind("Debug", "BallastKg", 0f, new ConfigDescription(
            "Payload mass added to the local player aircraft's root part, as stores add theirs (maximum takeoff mass tests); 0 is none",
            new AcceptableValueRange<float>(0f, 100000f)));
        ScenarioHooks.FlightAssist = Config.Bind("Debug", "FlightAssist", "pilot", new ConfigDescription(
            "on or off sets the local player aircraft's stock flight assist (pitch limiter) switch; pilot leaves it to the pilot",
            new AcceptableValueList<string>("pilot", "on", "off")));
        ScenarioHooks.Loadout = Config.Bind("Debug", "Loadout", "", new ConfigDescription(
            "A StandardLoadout name, or empty for the first of the aircraft's loadouts: on the host, once per change, sets the local player aircraft's loadout to a copy of it (scenarios); blank is off"));
        ScenarioHooks.Ignition = Config.Bind("Debug", "Ignition", "pilot", new ConfigDescription(
            "on or off sets the local player aircraft's engine ignition through the stock engine switch, at most once a second while it differs; pilot leaves it to the pilot",
            new AcceptableValueList<string>("pilot", "on", "off")));
        ScenarioHooks.CockpitLook = Config.Bind("Debug", "CockpitLook", "", new ConfigDescription(
            "pan,tilt,raise holds the cockpit camera's view: degrees right, degrees down, head raised 0 to 0.15 m (scenario screenshots); blank is off"));

        gameObject.AddComponent<FrameCapture>().Bind(Log,
            Config.Bind("Capture", "Enabled", false,
                "Record the game's frame as numbered JPGs plus frames.json while on (tools/Make-Video.ps1 makes the MP4); each enable writes a new folder"),
            Config.Bind("Capture", "Fps", 20, new ConfigDescription("Frames captured per real second", new AcceptableValueRange<int>(1, 60))),
            Config.Bind("Capture", "MaxSeconds", 60f, new ConfigDescription("Capture turns itself off after this many real seconds",
                new AcceptableValueRange<float>(1f, 600f))),
            Config.Bind("Capture", "Folder", "", "Where capture folders go; empty is BepInEx/captures, the run's profile in an agentic run"));
        WingFlex.Install(gameObject, Config, Log);
        RadarSuite.Install(Config, Log);
        AwacsBeam.Install(Config, Log);
        CramGuard.Install(Config, Log);
        PowerReadout.Install(Config, Log);
        CenturionAi.Install(Config, Log);
        OwnerState.Install(Config, Log);
        TelescopeController.DebugTear = Config.Bind("Debug", "Tear", false,
            "While true, tears both stage 1 panels off the local player Centurion once its span is fully out, through the load tear's own path (scenarios)");

        Log.StageEnabled = stageLogging.Value;
        stageLogging.SettingChanged += (_, _) => Log.StageEnabled = stageLogging.Value;
        diagnostics.SettingChanged += (_, _) => Log.Info($"config Diagnostics.Enabled = {diagnostics.Value}");
        stageLogging.SettingChanged += (_, _) => Log.Info($"config Diagnostics.StageLogging = {stageLogging.Value}");
        spanCommand.SettingChanged += (_, _) => Log.Info(Invariant($"config Debug.SpanCommand = {spanCommand.Value}"));
        TelescopeController.StageMaxAngularVelocity.SettingChanged += (_, _) => Log.Info(Invariant($"config Debug.StageMaxAngularVelocity = {TelescopeController.StageMaxAngularVelocity.Value}"));
        PlayerInputHold.Pitch.SettingChanged += (_, _) => Log.Stage("debug-pitch", Invariant($"Debug.PitchCommand = {PlayerInputHold.Pitch.Value}"));
        PlayerInputHold.Throttle.SettingChanged += (_, _) => Log.Stage("debug-throttle", Invariant($"Debug.ThrottleCommand = {PlayerInputHold.Throttle.Value}"));
        PlayerInputHold.Roll.SettingChanged += (_, _) => Log.Stage("debug-roll", Invariant($"Debug.RollCommand = {PlayerInputHold.Roll.Value}"));
        ScenarioHooks.SpeedHoldMps.SettingChanged += (_, _) => Log.Stage("debug-speed", Invariant($"Debug.SpeedHoldMps = {ScenarioHooks.SpeedHoldMps.Value}"));
        ScenarioHooks.Loadout.SettingChanged += (_, _) => Log.Info($"config Debug.Loadout = {ScenarioHooks.Loadout.Value}");
        ScenarioHooks.Ignition.SettingChanged += (_, _) => Log.Info($"config Debug.Ignition = {ScenarioHooks.Ignition.Value}");

        Log.Info(Invariant($"MRB-100 Centurion {Version} ({Guid}); Diagnostics.Enabled={diagnostics.Value} Diagnostics.StageLogging={stageLogging.Value} Debug.SpanCommand={spanCommand.Value} Debug.PitchCommand={PlayerInputHold.Pitch.Value} Debug.RollCommand={PlayerInputHold.Roll.Value} Debug.ThrottleCommand={PlayerInputHold.Throttle.Value} Debug.SpeedHoldMps={ScenarioHooks.SpeedHoldMps.Value} Debug.BallastKg={ScenarioHooks.BallastKg.Value} Debug.FlightAssist={ScenarioHooks.FlightAssist.Value}"));
        harmony = new Harmony(Guid);
        FeaturesOff = PatchTarget.InstallAll(harmony, PatchTargets, Log);
    }

    void OnDestroy() => harmony?.UnpatchSelf();

    void FixedUpdate() => ScenarioHooks.FixedUpdate();

    void Update()
    {
        Log.Tick();
        damageLog.Update(diagnostics.Value && Log.StageEnabled);
        SortieLog.Update();

        bool running = MissionManager.IsRunning;
        if (running && !missionRunning)
        {
            geometryLogAt = Time.unscaledTime + GeometryDelayS;
        }
        else if (!running)
        {
            geometryLogAt = float.PositiveInfinity;
        }

        missionRunning = running;
        if (Time.unscaledTime < geometryLogAt)
        {
            return;
        }

        geometryLogAt = float.PositiveInfinity;
        try
        {
            AiSupplyRepair.Apply(Log);
        }
        catch (Exception e)
        {
            Log.Error($"ai supply repair failed: {e}");
        }

        if (!diagnostics.Value)
        {
            return;
        }

        try
        {
            MissionGeometryLog.Write(Log);
        }
        catch (Exception e)
        {
            Log.Error($"geometry log failed: {e}");
        }
    }

    /// <summary>
    /// Read by NO-Agentic-Framework into every sample as mods.baanish.centurion.&lt;key&gt; (its AGENTS.md); every key is
    /// returned from the first call. See <see cref="AircraftReadout"/>.
    /// </summary>
    public Dictionary<string, object> AgenticState()
    {
        try
        {
            return AircraftReadout.Read(diagnostics.Value);
        }
        catch (Exception e)
        {
            Log.Stage("agentic-state", $"read failed: {e.GetType().Name}: {e.Message}");
            return AircraftReadout.Read(false);
        }
    }
}
