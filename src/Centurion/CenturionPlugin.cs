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
/// install and the telescoping wing (<see cref="TelescopeController"/>). Only a dev build (CENTURION_DEV,
/// tools/Build-Centurion.ps1 -Dev) has the diagnostics behind Diagnostics.Enabled: the per-mission geometry log, the damage
/// log, AgenticState() for NO-Agentic-Framework and the Debug.* holds; and Capture.*, which records playtest video
/// (FrameCapture). A release build binds none of those sections and removes them from an older version's config.
/// </summary>
[BepInPlugin(Guid, "MRB-100 Centurion", Version)]
public sealed class CenturionPlugin : BaseUnityPlugin
{
    public const string Guid = "baanish.centurion";
    public const string Version = "0.2.0";

    /// <summary>
    /// Seconds between a mission starting and the geometry log, so airbases a client or a carrier registers after the
    /// mission start are included.
    /// </summary>
    const float GeometryDelayS = 3f;

    /// <summary>AircraftDefinition.jsonKey of the Centurion (CenturionAuthor.JsonKey); <see cref="CenturionSystems.IsCenturion"/> tests it.</summary>
    internal const string JsonKey = "baanish_centurion";

    /// <summary>
    /// Every Harmony patch the mod installs. A game method carries at most one of them: where two rules hook the same
    /// per-frame method, one patch tests for a Centurion once and runs both.
    /// </summary>
    static readonly PatchTarget[] PatchTargets = TelescopeController.PatchTargets.Concat(SurfaceRules.PatchTargets).Concat(SpanGauge.PatchTargets)
        .Concat(CenturionSystems.PatchTargets).Concat(RadarSuite.PatchTargets).Concat(CramPatches.PatchTargets).Concat(MissileJamming.PatchTargets)
        .Concat(CenturionAwacsState.PatchTargets).Concat(AiAirfieldRules.PatchTargets).Concat(BayLoadoutRule.PatchTargets)
        .Concat(OwnerState.PatchTargets).Concat(StartupHold.PatchTargets).Concat(BombRelease.PatchTargets)
        .Concat(AiCramHold.PatchTargets).Concat(AiBombExtend.PatchTargets)
        .Concat(AiHighStrike.PatchTargets).Concat(StockMissionSupply.PatchTargets)
        .Concat(AiSamLoadout.PatchTargets).Concat(TensorRelease.PatchTargets)
#if CENTURION_DEV
        .Concat(PlayerInputHold.PatchTargets).Concat(PowerReadout.PatchTargets)
#endif
        .ToArray();

    internal static CenturionLog Log = null!;

    /// <summary>Features whose patch target was missing or failed; their code stands down.</summary>
    internal static HashSet<string> FeaturesOff = new();

    Harmony harmony = null!;
    bool missionRunning;
    float geometryLogAt = float.PositiveInfinity;
#if CENTURION_DEV
    ConfigEntry<bool> diagnostics = null!;
    ConfigEntry<bool> stageLogging = null!;
    ConfigEntry<float> spanCommand = null!;
    ConfigEntry<bool> pluginActive = null!;
    readonly List<Behaviour> paused = new();
    readonly List<Renderer> undrawn = new();
    readonly Dictionary<Renderer, UnityEngine.Rendering.ShadowCastingMode> shadowModes = new();
    DamageLog damageLog = null!;
#endif
    /// <summary>The config sections only a dev build binds. 0.1.x wrote them to every player's file.</summary>
    static readonly string[] DevSections = { "Diagnostics", "Debug", "Capture" };

    void Awake()
    {
        Log = new CenturionLog(Logger);
        TelescopeController.Log = Log;
#if !CENTURION_DEV
        RemoveDevSettings();
        Log.Info($"MRB-100 Centurion {Version} ({Guid}); release build; stage logging off");
#else
        damageLog = new DamageLog(Log);
        diagnostics = Config.Bind("Diagnostics", "Enabled", false,
            "Log runways, map bounds and medium hangars on each mission load, fill AgenticState(), and apply the Debug.* settings");
        stageLogging = Config.Bind("Diagnostics", "StageLogging", true,
            "Log each stage the mod crosses (spawn, damage, physics mode, extension, tear, radar, C-RAM, AI), at most one line per key per second");
        spanCommand = Config.Bind("Debug", "SpanCommand", -1f, new ConfigDescription(
            "0 to 1 is the local player Centurion's span command in place of its pilot's axis and the AI schedule (scenarios); the hangar guard and a lost span still hold it at 0; below 0 is off",
            new AcceptableValueRange<float>(-1f, 1f)));
        PlayerInputHold.Diagnostics = diagnostics;
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
            new AcceptableValueList<string>("", "Centurion", "fuselage_F", "fuselage_R", "tailcone")));
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
            "pan,tilt,raise[,fov] holds the cockpit camera's view: degrees right, degrees down, head raised 0 to 0.15 m, and optionally the field of view in degrees, 20 to 120 (scenario screenshots); blank is off"));
        ScenarioHooks.CockpitSeat = Config.Bind("Debug", "CockpitSeat", "pilot", new ConfigDescription(
            "commander puts the local player aircraft's cockpit camera at the mission commander's helmet camera point (Aircraft.pilots[1]), where CockpitLook turns it; pilot is the stock eye",
            new AcceptableValueList<string>("pilot", "commander")));

        gameObject.AddComponent<FrameCapture>().Bind(Log,
            Config.Bind("Capture", "Enabled", false,
                "Record the game's frame as numbered JPGs plus frames.json while on (tools/Make-Video.ps1 makes the MP4); each enable writes a new folder"),
            Config.Bind("Capture", "Fps", 20, new ConfigDescription("Frames captured per real second", new AcceptableValueRange<int>(1, 60))),
            Config.Bind("Capture", "MaxSeconds", 60f, new ConfigDescription("Capture turns itself off after this many real seconds",
                new AcceptableValueRange<float>(1f, 600f))),
            Config.Bind("Capture", "Folder", "", "Where capture folders go; empty is BepInEx/captures, the run's profile in an agentic run"));
        PowerReadout.Install(Config, Log);
        TelescopeController.DebugTear = Config.Bind("Debug", "Tear", false,
            "While true, tears both stage 1 panels off the local player Centurion once its span is fully out, through the load tear's own path (scenarios)");
        pluginActive = Config.Bind("Debug", "PluginActive", true,
            "False removes every Harmony patch and disables every component of this plugin, true puts them back: a slices step's on and off for the plugin's own frame cost");
        pluginActive.SettingChanged += (_, _) => SetPluginActive(pluginActive.Value);
        ConfigEntry<bool> drawOthers = Config.Bind("Debug", "DrawOtherAircraft", true,
            "False stops drawing every aircraft but the local player's (their renderers off; physics, AI and the camera untouched), true draws them again: a slices step's on and off for what drawing them costs");
        drawOthers.SettingChanged += (_, _) => SetOthersDrawn(drawOthers.Value);
        ConfigEntry<bool> othersShadows = Config.Bind("Debug", "OtherAircraftShadows", true,
            "False stops every aircraft but the local player's casting shadows, true restores them: a slices step's on and off for what their shadows cost");
        othersShadows.SettingChanged += (_, _) => SetOthersShadows(othersShadows.Value);
        ConfigEntry<int> othersLod = Config.Bind("Debug", "OtherAircraftLod", -1, new ConfigDescription(
            "0 or above holds every aircraft but the local player's at that LOD level; -1 leaves their LOD groups to the camera: a slices step's on and off for what the full-detail level costs",
            new AcceptableValueRange<int>(-1, 3)));
        othersLod.SettingChanged += (_, _) => SetOthersLod(othersLod.Value);
#endif
        WingFlex.Install(Config, Log);
        RadarSuite.Install(Config, Log);
        AwacsBeam.Install(Config, Log);
        CramGuard.Install(Config, Log);
#if CENTURION_DEV
        CenturionAi.Install(Config, Log);
#endif
        OwnerState.Install(Config, Log);

#if CENTURION_DEV
        HideDevSettings();
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

        Log.Info(Invariant($"MRB-100 Centurion {Version} ({Guid}); dev build; Diagnostics.Enabled={diagnostics.Value} Diagnostics.StageLogging={stageLogging.Value} Debug.SpanCommand={spanCommand.Value} Debug.PitchCommand={PlayerInputHold.Pitch.Value} Debug.RollCommand={PlayerInputHold.Roll.Value} Debug.ThrottleCommand={PlayerInputHold.Throttle.Value} Debug.SpeedHoldMps={ScenarioHooks.SpeedHoldMps.Value} Debug.BallastKg={ScenarioHooks.BallastKg.Value} Debug.FlightAssist={ScenarioHooks.FlightAssist.Value}"));
        harmony = new Harmony(Guid);
        FeaturesOff = PatchTarget.InstallAll(harmony, PatchTargets, Log, diagnostics.Value);
#else
        harmony = new Harmony(Guid);
        FeaturesOff = PatchTarget.InstallAll(harmony, PatchTargets, Log, diagnostics: false);
#endif
        StockMissionSupply.Install(Config);
    }

#if CENTURION_DEV
    /// <summary>
    /// Configuration Manager lists a setting tagged "Advanced" only with its Advanced settings box ticked, which keeps the
    /// dev sections out of the owner's way in a playtest. A description's tags are fixed at Bind, so each dev entry gets a
    /// tagged copy of its description here instead of a tag on every Bind call. Scenarios set these keys through the
    /// config file and are unaffected.
    /// </summary>
    void HideDevSettings()
    {
        System.Reflection.FieldInfo? description = AccessTools.Field(typeof(ConfigEntryBase), "<Description>k__BackingField");
        if (description == null)
        {
            Log.Warning("config: ConfigEntryBase's description field is missing; the dev settings stay in Configuration Manager's default view");
            return;
        }

        foreach (ConfigDefinition key in Config.Keys.Where(key => DevSections.Contains(key.Section)))
        {
            ConfigDescription was = Config[key].Description;
            description.SetValue(Config[key], new ConfigDescription(was.Description, was.AcceptableValues, "Advanced"));
        }
    }
#else
    /// <summary>
    /// BepInEx writes back every key its file held, bound or not (ConfigFile.OrphanedEntries), so a 0.1.x player's
    /// Diagnostics.StageLogging = true and Debug.* keys would stay in the file forever. Keyed off the sections, not their
    /// values: a release build binds nothing in them, so every key there is a dev build's. Runs before the first Bind, which
    /// saves the file.
    /// </summary>
    void RemoveDevSettings()
    {
        if (AccessTools.Property(typeof(ConfigFile), "OrphanedEntries")?.GetValue(Config) is not Dictionary<ConfigDefinition, string> orphaned)
        {
            Log.Warning("config: ConfigFile.OrphanedEntries missing; Diagnostics, Debug and Capture keys from an older version stay in the file");
            return;
        }

        List<ConfigDefinition> dev = orphaned.Keys.Where(key => DevSections.Contains(key.Section)).ToList();
        if (dev.Count == 0)
        {
            return;
        }

        foreach (ConfigDefinition key in dev)
        {
            orphaned.Remove(key);
        }

        Config.Save();
        Log.Info($"config: removed {dev.Count} {string.Join(", ", DevSections)} settings an older version wrote");
    }
#endif

    // Every plugin has loaded by the first Start, so NOAutopilot is visible to Chainloader here, not in Awake.
    void Start() => NoAutopilotProfile.Install();

    void OnDestroy() => harmony?.UnpatchSelf();

#if CENTURION_DEV
    void FixedUpdate() => ScenarioHooks.FixedUpdate();

    /// <summary>Every renderer of every aircraft but the local player's (any type: the Darkreach baseline uses it too).</summary>
    static IEnumerable<Renderer> OtherAircraftRenderers()
    {
        GameManager.GetLocalAircraft(out Aircraft local);
        foreach (Aircraft aircraft in FindObjectsOfType<Aircraft>())
        {
            if (aircraft == local) continue;
            foreach (UnitPart part in aircraft.partLookup)
            {
                if (part == null) continue;
                foreach (Renderer renderer in part.GetComponentsInChildren<Renderer>()) yield return renderer;
            }
        }
    }

    /// <summary>
    /// Debug.DrawOtherAircraft: the off side of a frame-cost measurement draws no aircraft but the player's, from the same
    /// camera, so the background and every aircraft's simulation stay as they are. A part's renderers, its effects' and its
    /// lights' included; a flex mesh no camera draws is not bent (WingFlex.FlexMesh.Bend), so their wing flex goes with them.
    /// </summary>
    void SetOthersDrawn(bool drawn)
    {
        foreach (Renderer renderer in undrawn)
        {
            if (renderer != null) renderer.enabled = true;
        }

        undrawn.Clear();
        if (!drawn)
        {
            foreach (Renderer renderer in OtherAircraftRenderers())
            {
                if (!renderer.enabled) continue;
                renderer.enabled = false;
                undrawn.Add(renderer);
            }
        }

        Log.Info($"config Debug.DrawOtherAircraft = {drawn} ({undrawn.Count} renderers off)");
    }

    /// <summary>Debug.OtherAircraftShadows: false stops every other aircraft's renderers casting shadows, true restores each one's own mode.</summary>
    void SetOthersShadows(bool cast)
    {
        foreach (KeyValuePair<Renderer, UnityEngine.Rendering.ShadowCastingMode> entry in shadowModes)
        {
            if (entry.Key != null) entry.Key.shadowCastingMode = entry.Value;
        }

        shadowModes.Clear();
        if (!cast)
        {
            foreach (Renderer renderer in OtherAircraftRenderers())
            {
                if (renderer.shadowCastingMode == UnityEngine.Rendering.ShadowCastingMode.Off || shadowModes.ContainsKey(renderer)) continue;
                shadowModes[renderer] = renderer.shadowCastingMode;
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            }
        }

        Log.Info($"config Debug.OtherAircraftShadows = {cast} ({shadowModes.Count} renderers' shadows off)");
    }

    /// <summary>Debug.OtherAircraftLod: 0 or above holds every other aircraft's LOD groups at that level (LODGroup.ForceLOD), below 0 hands them back.</summary>
    static void SetOthersLod(int level)
    {
        GameManager.GetLocalAircraft(out Aircraft local);
        int groups = 0;
        foreach (Aircraft aircraft in FindObjectsOfType<Aircraft>())
        {
            if (aircraft == local) continue;
            foreach (UnitPart part in aircraft.partLookup)
            {
                if (part == null) continue;
                foreach (LODGroup group in part.GetComponentsInChildren<LODGroup>())
                {
                    group.ForceLOD(level);
                    groups++;
                }
            }
        }

        Log.Info($"config Debug.OtherAircraftLod = {level} ({groups} LOD groups)");
    }

    /// <summary>Debug.PluginActive: the off side of a frame-cost measurement runs the game as if the plugin had no hooks and no components.</summary>
    void SetPluginActive(bool active)
    {
        if (active)
        {
            FeaturesOff = PatchTarget.InstallAll(harmony, PatchTargets, Log, diagnostics.Value);
            foreach (Behaviour behaviour in paused)
            {
                if (behaviour != null) behaviour.enabled = true;
            }

            paused.Clear();
        }
        else
        {
            harmony.UnpatchSelf();
            foreach (MonoBehaviour behaviour in FindObjectsOfType<MonoBehaviour>())
            {
                if (behaviour != this && behaviour.enabled && behaviour.GetType().Assembly == typeof(CenturionPlugin).Assembly)
                {
                    behaviour.enabled = false;
                    paused.Add(behaviour);
                }
            }
        }

        Log.Info($"config Debug.PluginActive = {active}");
    }
#endif

    void Update()
    {
#if CENTURION_DEV
        Log.Tick();
        damageLog.Update(diagnostics.Value && Log.StageEnabled);
        SortieLog.Update();
#endif
        PackBayMounts.Update();
        LiveryWorkshopTag.Update(Log);

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

        try
        {
            StockMissionSupply.Apply();
        }
        catch (Exception e)
        {
            Log.Error($"stock supply failed: {e}");
        }

#if CENTURION_DEV
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
#endif
    }

#if CENTURION_DEV
    /// <summary>
    /// Read by NO-Agentic-Framework into every sample as mods.baanish.centurion.&lt;key&gt; (its AGENTS.md); every key is
    /// returned from the first call. See <see cref="AircraftReadout"/>.
    /// </summary>
    public Dictionary<string, object> AgenticState()
    {
        try
        {
            return StockMissionSupply.AddReadout(AircraftReadout.Read(diagnostics.Value));
        }
        catch (Exception e)
        {
            Log.Stage("agentic-state", $"read failed: {e.GetType().Name}: {e.Message}");
            return AircraftReadout.Read(false);
        }
    }
#endif
}
