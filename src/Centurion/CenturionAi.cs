using System.Collections.Generic;
using System.Linq;
using BepInEx.Configuration;
using NuclearOption.SavedMission;
using UnityEngine;
using static Centurion.AircraftReadout;

namespace Centurion;

/// <summary>AI diagnostics and loadout identity, independent of weapon-mount initialization.</summary>
sealed class CenturionAi : MonoBehaviour
{
    internal static readonly List<CenturionAi> All = new();
    static readonly SortedDictionary<string, int> Loadouts = new(System.StringComparer.Ordinal);
    static Mission? seenMission;
    static int loadoutCustoms;
    static CenturionLog log = null!;

    Aircraft aircraft = null!;
    readonly List<UnitPart> damageParts = new();
    bool seen, counted, airborne;
    float onGroundAt = float.NegativeInfinity;
    float airborneAt, taxiMaxMps, cramSelectedS, energyModeS;
    int takeoffs, touchdowns, damageEvents;
    string loadoutName = NoText, spawnAirbase = NoText;
    SortieLog.Sortie? sortie;

    internal CenturionAwacsState AwacsState { get; } = new();
    Pilot? Pilot => aircraft.pilots.Length > 0 ? aircraft.pilots[0] : null;
    public bool IsLocalPlayer => GameManager.GetLocalAircraft(out Aircraft local) && local == aircraft;
    public bool Simulated => aircraft.LocalSim;
    bool AiFlown => Simulated && !IsLocalPlayer && aircraft.Player == null
        && Pilot != null && Pilot.currentState != null && Pilot.currentState is not PilotPlayerState;

    // LoadHardpointSet applies the same restriction before fitting a mount. A lost beam keeps its loadout identity.
    internal bool IsAwacs => aircraft.loadout != null && aircraft.loadout.weapons.Count > 2
        && aircraft.loadout.weapons[2] != null && aircraft.loadout.weapons[2].jsonKey == "baanish_centurion_awacs"
        && (aircraft.NetworkHQ == null || !aircraft.NetworkHQ.restrictedWeapons.Contains(aircraft.loadout.weapons[2].name));

    internal static void Install(ConfigFile config, CenturionLog logger)
    {
        log = logger;
    }

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        foreach (string key in new[]
        {
            "ai_count", "ai_cram_selected_s", "ai_energy_mode_s", "ai_awacs", "ai_fuel_frac", "ai_fuel_kg",
            "ai_alt_msl_m", "ai_alt_agl_m", "ai_tas_mps", "ai_eas_mps", "ai_mach", "ai_x", "ai_z", "ai_hdg_deg",
            "ai_airborne", "ai_airborne_s", "ai_takeoffs", "ai_touchdowns", "ai_taxi_max_mps", "ai_damage_events",
            "ai_alive", "ai_ejected", "ai_span_frac", "ai_span_cmd", "ai_beam_deploy", "ai_beam_range_m",
            "ai_awacs_standoff_m", "ai_awacs_anchor_dist_m", "ai_awacs_anchor_changes", "ai_awacs_orbit_s",
            "ai_awacs_recovery_fuel_frac", "ai_hostile_air_tracks", "ai_loadout_customs", "ai_spawn_rejects",
            "ai_strike_rounds", "ai_missiles_in_flight",
        }) state[key] = NotRead;
        foreach (string key in new[]
        {
            "ai_name", "ai_state", "ai_weapon", "ai_loadout", "ai_spawn_airbase", "ai_tear", "ai_beam_state",
            "ai_awacs_phase", "ai_awacs_home", "ai_awacs_anchor", "ai_loadouts", "ai_spawn_rejected",
        }) state[key] = NoText;
    }

    internal static void Read(Dictionary<string, object> state)
    {
        ResetMissionCounts();
        CenturionAi? watched = null;
        int count = 0;
        foreach (CenturionAi ai in All)
        {
            if (ai == null || !ai.AiFlown) continue;
            count++;
            watched ??= ai;
        }
        state["ai_count"] = count;
        state["ai_loadouts"] = Loadouts.Count == 0 ? NoText : string.Join(";", Loadouts.Select(p => $"{p.Key}:{p.Value}"));
        state["ai_loadout_customs"] = loadoutCustoms;
        state["ai_spawn_rejects"] = AiAirfieldRules.SpawnRejects;
        state["ai_spawn_rejected"] = AiAirfieldRules.SpawnRejected;
        if (watched != null) watched.ReadWatched(state);
    }

    internal static void ReadRemote(Dictionary<string, object> state) { }

    static void ResetMissionCounts()
    {
        if (ReferenceEquals(seenMission, MissionManager.CurrentMission)) return;
        seenMission = MissionManager.CurrentMission;
        Loadouts.Clear();
        loadoutCustoms = 0;
    }

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        All.Add(this);
    }

    void FirstSight()
    {
        seen = true;
        Airbase? airbase = aircraft.NetworkspawningHangar != null ? aircraft.NetworkspawningHangar.parentAirbase : null;
        if (airbase == null && aircraft.NetworkHQ != null)
            aircraft.NetworkHQ.AnyNearAirbase(aircraft.transform.position, out airbase);
        spawnAirbase = airbase != null ? MissionGeometryLog.AirbaseName(airbase) : "mission";
        loadoutName = "custom";
        foreach (StandardLoadout standard in aircraft.definition.aircraftParameters.StandardLoadouts ?? System.Array.Empty<StandardLoadout>())
        {
            if (standard.loadout.weapons.Count == aircraft.loadout.weapons.Count
                && standard.loadout.weapons.Zip(aircraft.loadout.weapons, (a, b) => ReferenceEquals(a, b)).All(equal => equal))
            {
                loadoutName = standard.Name;
                break;
            }
        }
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part == null) continue;
            damageParts.Add(part);
            part.onApplyDamage += OnDamage;
        }
        log.Info($"AI first sight: {aircraft.persistentID}, loadout {loadoutName}, spawn {spawnAirbase}");
    }

    void FixedUpdate()
    {
        if (!Simulated) return;
        ResetMissionCounts();
        if (!seen) FirstSight();
        SortieLog.Sortie? active = SortieLog.Enabled.Value && MissionManager.IsRunning ? sortie ??= SortieLog.Begin(aircraft, AwacsState, loadoutName, spawnAirbase) : null;
        if (AiFlown && !counted)
        {
            counted = true;
            Loadouts.TryGetValue(loadoutName, out int count);
            Loadouts[loadoutName] = count + 1;
            if (loadoutName == "custom") loadoutCustoms++;
        }
        if (aircraft.radarAlt < 1f) onGroundAt = Time.fixedTime;
        bool nowAirborne = Time.fixedTime - onGroundAt > 0.5f;
        if (nowAirborne && !airborne)
        {
            takeoffs++;
            airborneAt = Time.fixedTime;
            active?.Takeoff();
        }
        else if (!nowAirborne && airborne)
        {
            touchdowns++;
            active?.Touchdown();
        }
        airborne = nowAirborne;
        if (!airborne)
        {
            Vector3 velocity = aircraft.CockpitRB().velocity;
            taxiMaxMps = Mathf.Max(taxiMaxMps, new Vector2(velocity.x, velocity.z).magnitude);
        }
        WeaponStation station = aircraft.weaponManager.currentWeaponStation;
        if (airborne && station != null && station.WeaponInfo != null && station.WeaponInfo.energy)
            cramSelectedS += Time.fixedDeltaTime;
        if (Pilot != null && Pilot.GetCurrentState() == "Using Energy Weapon") energyModeS += Time.fixedDeltaTime;
        active?.Poll(damageEvents);
    }

    void OnDamage(UnitPart.OnApplyDamage damage) => damageEvents++;

    void ReadWatched(Dictionary<string, object> state)
    {
        Pilot pilot = Pilot!;
        GlobalPosition position = aircraft.transform.GlobalPosition();
        float tas = (aircraft.CockpitRB().velocity - aircraft.GetWindVelocity()).magnitude;
        state["ai_name"] = string.IsNullOrEmpty(aircraft.UniqueName) ? $"id {aircraft.persistentID}" : aircraft.UniqueName;
        state["ai_state"] = pilot.GetCurrentState();
        WeaponStation station = aircraft.weaponManager.currentWeaponStation;
        state["ai_weapon"] = station != null && station.WeaponInfo != null ? station.WeaponInfo.weaponName : NoText;
        state["ai_awacs"] = IsAwacs ? 1 : 0;
        state["ai_fuel_frac"] = Round(aircraft.GetFuelLevel());
        state["ai_fuel_kg"] = Round(aircraft.GetFuelQuantity());
        state["ai_alt_msl_m"] = Round(position.y);
        state["ai_alt_agl_m"] = Round(aircraft.radarAlt);
        state["ai_tas_mps"] = Round(tas);
        state["ai_eas_mps"] = Round(tas * Mathf.Sqrt(LevelInfo.GetAirDensity(position.y) / LevelInfo.GetAirDensity(0f)));
        state["ai_mach"] = Round(tas / LevelInfo.GetSpeedOfSound(position.y));
        state["ai_x"] = Round(position.x);
        state["ai_z"] = Round(position.z);
        state["ai_hdg_deg"] = Round(aircraft.transform.eulerAngles.y);
        state["ai_alive"] = aircraft.disabled ? 0 : 1;
        state["ai_ejected"] = pilot.ejected || pilot.dead ? 1 : 0;
        state["ai_strike_rounds"] = AiHighStrike.StrikeRounds(aircraft);
        state["ai_missiles_in_flight"] = IsAwacs ? AwacsState.Arad.MissilesInFlight : AiHighStrike.MissilesInFlight(pilot);
        if (seen)
        {
            state["ai_loadout"] = loadoutName;
            state["ai_spawn_airbase"] = spawnAirbase;
            state["ai_airborne"] = airborne ? 1 : 0;
            state["ai_airborne_s"] = airborne ? Round(Time.fixedTime - airborneAt) : 0d;
            state["ai_takeoffs"] = takeoffs;
            state["ai_touchdowns"] = touchdowns;
            state["ai_taxi_max_mps"] = Round(taxiMaxMps);
            state["ai_damage_events"] = damageEvents;
            state["ai_cram_selected_s"] = Round(cramSelectedS);
            state["ai_energy_mode_s"] = Round(energyModeS);
        }
        if (aircraft.TryGetComponent(out TelescopeController telescope))
        {
            state["ai_span_frac"] = Round(telescope.Extension);
            state["ai_span_cmd"] = Round(telescope.Command);
            state["ai_tear"] = telescope.TearState;
        }
        var beam = new Dictionary<string, object>();
        AwacsBeam.AddDefaults(beam);
        AwacsBeam.Read(beam, aircraft);
        state["ai_beam_state"] = beam["awacs_state"];
        state["ai_beam_deploy"] = beam["awacs_deploy"];
        state["ai_beam_range_m"] = beam["awacs_range_m"];
        if (IsAwacs)
        {
            state["ai_awacs_phase"] = pilot.currentState == AwacsState ? AwacsState.Phase : NoText;
            state["ai_awacs_home"] = AwacsState.HomeName;
            state["ai_awacs_anchor"] = AwacsState.AnchorName;
            state["ai_awacs_standoff_m"] = Round(AwacsState.StandoffM);
            state["ai_awacs_anchor_dist_m"] = Round(AwacsState.AnchorDistM);
            state["ai_awacs_anchor_changes"] = AwacsState.AnchorChanges;
            state["ai_awacs_orbit_s"] = Round(AwacsState.OrbitS);
            state["ai_awacs_recovery_fuel_frac"] = Round(AwacsState.RecoveryFuelFrac);
        }
        if (aircraft.NetworkHQ != null)
        {
            int tracks = 0;
            foreach (TrackingInfo track in aircraft.NetworkHQ.trackingDatabase.Values)
                if (track.TryGetUnit(out Unit unit) && unit is Aircraft && unit.NetworkHQ != null && unit.NetworkHQ != aircraft.NetworkHQ
                    && aircraft.NetworkHQ.IsTargetBeingTracked(unit)) tracks++;
            state["ai_hostile_air_tracks"] = tracks;
        }
    }

    void OnDestroy()
    {
        All.Remove(this);
        foreach (UnitPart part in damageParts)
            if (!ReferenceEquals(part, null)) part.onApplyDamage -= OnDamage;
        sortie?.Despawned();
    }
}
