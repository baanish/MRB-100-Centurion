using System;
using System.Collections.Generic;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;
using static Centurion.AircraftReadout;

namespace Centurion;

/// <summary>
/// Keeps the nose, tail and AWACS radars on the stock toggle's master state on every peer. The primary is the deployed
/// beam, then the nose, then the tail. Each slot reports distinct targets from its last completed scan.
/// </summary>
sealed class RadarSuite : MonoBehaviour
{
    const string FrontName = "radar_F_fairing";
    const string RearName = "radar_R";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("radar-master", typeof(Aircraft), "UserCode_RpcToggleRadar_1325449311", new[] { typeof(bool) },
            postfix: AccessTools.Method(typeof(RadarSuite), nameof(AfterToggle))),
    };

    /// <summary>Every live Centurion's suite, local and remote.</summary>
    internal static readonly List<RadarSuite> All = new();

    internal static ConfigEntry<string> DebugRadar = null!;
    static ConfigEntry<bool> diagnostics = null!;
    static CenturionLog log = null!;

    Aircraft aircraft = null!;
    AwacsBeam? beam;
    readonly RadarSlot front = new();
    readonly RadarSlot rear = new();
    readonly RadarSlot awacs = new();
    float nextToggleAt;
    /// <summary>The master in the owner's last state word this copy acted on; null before the first.</summary>
    bool? ownerMaster;

    /// <summary>
    /// The stock radar toggle's state, carried to all three radars; true until the toggle is used, as every stock radar starts
    /// on. The toggle is a reliable RPC a late joiner never got (Aircraft.cs:791-802), so an observer also takes it from the
    /// owner's state (<see cref="OwnerState"/>): on the first word and whenever the word's master changes, so a word sent
    /// before an RPC that already landed doesn't undo it.
    /// </summary>
    public bool Master { get; private set; } = true;

    public bool IsLocalPlayer => GameManager.GetLocalAircraft(out Aircraft local) && local == aircraft;
    public bool Simulated => aircraft.LocalSim;

    internal static void Install(ConfigFile config, CenturionLog log)
    {
        RadarSuite.log = log;
        if (!config.TryGetEntry("Diagnostics", "Enabled", out diagnostics))
        {
            throw new InvalidOperationException("RadarSuite requires Diagnostics.Enabled to be bound before Install");
        }
        DebugRadar = config.Bind("Debug", "Radar", "pilot", new ConfigDescription(
            "on or off drives the local player aircraft's radar master through the Radar key's call, at most once a second while it differs; pilot leaves it to the pilot",
            new AcceptableValueList<string>("pilot", "on", "off")));
        DebugRadar.SettingChanged += (_, _) => log.Info($"config Debug.Radar = {DebugRadar.Value}");
    }

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        state["radar_primary"] = AircraftReadout.NoText;
        state["radar_master"] = AircraftReadout.NotRead;
        foreach (string slot in new[] { "front", "rear", "awacs" })
        {
            state[$"radar_{slot}_on"] = AircraftReadout.NotRead;
            state[$"radar_{slot}_tracks"] = AircraftReadout.NotRead;
            state[$"radar_{slot}_scan_age_s"] = AircraftReadout.NotRead;
            state[$"radar_{slot}_detect_age_s"] = AircraftReadout.NotRead;
        }

        state["radar_awacs_track_max_m"] = AircraftReadout.NotRead;
        state["remote_radar_master"] = AircraftReadout.NotRead;
    }

    internal static void Read(Dictionary<string, object> state, Aircraft aircraft)
    {
        if (!aircraft.TryGetComponent(out RadarSuite suite))
        {
            return;
        }

        TargetDetector? primary = aircraft.radar;
        state["radar_primary"] = primary == null ? NoText : primary == suite.front.Radar ? "front"
            : primary == suite.rear.Radar ? "rear" : primary == suite.awacs.Radar ? "awacs" : "other";
        state["radar_master"] = suite.Master ? 1 : 0;
        suite.front.Read(state, "front");
        suite.rear.Read(state, "rear");
        suite.awacs.Read(state, "awacs");
        if (suite.awacs.Radar != null && suite.awacs.Tracks > 0)
        {
            state["radar_awacs_track_max_m"] = Round(suite.awacs.TrackMaxM);
        }
    }

    internal static void ReadRemote(Dictionary<string, object> state)
    {
        foreach (RadarSuite suite in All)
        {
            if (suite != null && !suite.IsLocalPlayer && !suite.Simulated)
            {
                state["remote_radar_master"] = suite.Master ? 1 : 0;
                break;
            }
        }
    }

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part != null && part.name == FrontName)
            {
                front.Bind(part.GetComponent<Radar>());
            }
            if (part != null && part.name == "tailcone")
            {
                rear.Bind(part.transform.Find(RearName)?.GetComponent<Radar>());
            }
        }
        if (front.Radar == null) log.Warning($"radar: missing {FrontName}");
        if (rear.Radar == null) log.Warning($"radar: missing {RearName}");
        aircraft.radar = front.Radar;
        aircraft.weaponManager.OnWeaponsLoaded += BindAwacs;
        All.Add(this);
    }

    void BindAwacs()
    {
        beam = GetComponent<AwacsBeam>();
        awacs.Bind(beam != null ? beam.BeamRadar : null);
    }

    void Update()
    {
        if (beam == null) beam = GetComponent<AwacsBeam>();
        awacs.Bind(beam != null ? beam.BeamRadar : null);
        RadarSlot? primary = awacs.Alive && beam != null && beam.Deployed ? awacs
            : front.Alive ? front : rear.Alive ? rear : null;
        if (primary != null) aircraft.radar = primary.Radar;

        if (CenturionPlugin.FeaturesOff.Contains("radar-master")) return;
        if (!aircraft.LocalSim && aircraft.TryGetComponent(out OwnerState owner) && owner.Received && owner.RadarMaster != ownerMaster)
        {
            ownerMaster = owner.RadarMaster;
            SetMaster(owner.RadarMaster, "owner state");
        }
        if (front.Alive && front.Radar!.activated != Master) front.Radar.activated = Master;
        if (rear.Alive && rear.Radar!.activated != Master) rear.Radar.activated = Master;
        if (awacs.Alive && awacs.Radar!.activated != Master) awacs.Radar.activated = Master;

        if (diagnostics.Value && IsLocalPlayer && aircraft.radar != null && DebugRadar.Value != "pilot"
            && (DebugRadar.Value == "on") != Master && Time.unscaledTime >= nextToggleAt)
        {
            nextToggleAt = Time.unscaledTime + 1f;
            aircraft.CmdToggleRadar();
            log.Stage("debug-radar", $"request {DebugRadar.Value}");
        }
    }

    static void AfterToggle(Aircraft __instance, bool activated)
    {
        if (CenturionPlugin.FeaturesOff.Contains("radar-master")) return;
        if (__instance.TryGetComponent(out RadarSuite suite))
        {
            suite.SetMaster(activated, "toggle");
        }
    }

    void SetMaster(bool activated, string source)
    {
        if (Master == activated)
        {
            return;
        }

        Master = activated;
        front.ClearLatch();
        rear.ClearLatch();
        awacs.ClearLatch();
        log.Info($"radar master: {activated} ({source}, {aircraft.persistentID})");
    }

    void OnDestroy()
    {
        aircraft.weaponManager.OnWeaponsLoaded -= BindAwacs;
        front.Bind(null);
        rear.Bind(null);
        awacs.Bind(null);
        All.Remove(this);
    }

    sealed class RadarSlot
    {
        internal Radar? Radar { get; private set; }
        internal bool Alive => Radar != null && Radar.IsOperational();
        internal int Tracks { get; private set; }
        internal float TrackMaxM { get; private set; }
        readonly HashSet<PersistentID> pending = new();
        float pendingMaxM;
        float lastScanTime;
        float lastDetectTime;

        internal void Bind(Radar? radar)
        {
            if (ReferenceEquals(Radar, radar)) return;
            // Unity's destroyed-object null comparison must not skip managed event unsubscription.
            if (!ReferenceEquals(Radar, null))
            {
                Radar!.onScan -= OnScan;
                Radar.onDetectTarget -= OnDetectTarget;
            }
            Radar = radar;
            ClearLatch();
            lastScanTime = lastDetectTime = Time.time;
            if (Radar != null)
            {
                Radar.onScan += OnScan;
                Radar.onDetectTarget += OnDetectTarget;
                log.Info($"radar bound: {Radar.name}");
            }
        }

        internal void ClearLatch()
        {
            Tracks = 0;
            TrackMaxM = pendingMaxM = (float)NotRead;
            pending.Clear();
        }

        void OnDetectTarget(Unit target)
        {
            pending.Add(target.persistentID);
            pendingMaxM = Mathf.Max(pendingMaxM, Vector3.Distance(Radar!.GetScanPoint().position, target.transform.position));
            lastDetectTime = Time.time;
        }

        void OnScan()
        {
            // onScan follows request submission, so pending holds the previous scan's returned detections.
            Tracks = pending.Count;
            TrackMaxM = pendingMaxM;
            pending.Clear();
            pendingMaxM = (float)NotRead;
            lastScanTime = Time.time;
        }

        internal void Read(Dictionary<string, object> state, string slot)
        {
            if (Radar == null) return;
            state[$"radar_{slot}_on"] = Radar.activated ? 1 : 0;
            state[$"radar_{slot}_tracks"] = Tracks;
            state[$"radar_{slot}_scan_age_s"] = Round(Time.time - lastScanTime);
            state[$"radar_{slot}_detect_age_s"] = Round(Time.time - lastDetectTime);
        }
    }
}
