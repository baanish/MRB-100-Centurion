using System.Collections.Generic;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.SavedMission;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Diagnostics.SortieLog: one "sortie:" line per event of each Centurion's sortie (spawn, takeoff, touchdown, AI state and
/// target, AWACS phase, weapon release, kill, damage, tear, ejection, loss, despawn, a 60 s snapshot) and a summary per
/// Centurion when the mission stops, written by the peer that simulates it: the host logs its AI, each player their own.
/// A player's Steam name is never written: a player-flown Centurion is "player &lt;id&gt;", an AI one its UniqueName or
/// "id &lt;id&gt;", any other unit its type (a player-flown one "player (&lt;type&gt;)") and faction. Feet, knots,
/// nautical miles; map positions (snapshots, AWACS phases, releases) in km. <see cref="CenturionAi"/> owns each
/// <see cref="Sortie"/> and polls it once a second; kills come from the kill-feed RPC (<see cref="CramPatches"/>), which a
/// host or single player runs once, locally.
/// </summary>
static class SortieLog
{
    /// <summary>AircraftDefinition.jsonKey of the Centurion (CenturionAuthor.JsonKey).</summary>
    const string CenturionKey = "baanish_centurion";
    const float PollS = 1f, SnapshotS = 60f, LossGraceS = 3f, DamageStep = 0.1f;
    const float FtPerM = 3.28084f, KtPerMps = 1.943844f, MPerNm = 1852f;

    internal static ConfigEntry<bool> Enabled = null!;

    static readonly Dictionary<PersistentID, Sortie> Sorties = new();
    static readonly List<Sortie> Despawns = new();
    static Mission? mission;
    static float missionT;

    static readonly AccessTools.FieldRef<AIPilotCombatModes, Unit>? CombatTarget = FieldRef<AIPilotCombatModes, Unit>("currentTarget");
    // Server only: Unit.RecordDamage credits each dealer, which ReportKilled reads for the kill message (Unit.cs:1271, 1520).
    static readonly AccessTools.FieldRef<Unit, Dictionary<PersistentID, float>>? DamageCredit = FieldRef<Unit, Dictionary<PersistentID, float>>("damageCredit");

    static AccessTools.FieldRef<T, F>? FieldRef<T, F>(string name) =>
        AccessTools.DeclaredField(typeof(T), name) != null ? AccessTools.FieldRefAccess<T, F>(name) : null;

    static float Now => MissionManager.IsRunning ? Time.timeSinceLevelLoad : missionT;

    static void Line(string who, string text) => CenturionPlugin.Log.Info(Invariant($"sortie: t={Now:0} {who} {text}"));

    internal static Sortie Begin(Aircraft aircraft, CenturionAwacsState awacs, string loadout, string spawnAirbase)
    {
        if (Sorties.Count > 0 && !ReferenceEquals(mission, MissionManager.CurrentMission)) Summarize();
        mission = MissionManager.CurrentMission;
        var sortie = new Sortie(aircraft, awacs, loadout);
        Sorties[aircraft.persistentID] = sortie;
        sortie.Spawn(spawnAirbase);
        return sortie;
    }

    /// <summary>Every frame: writes despawns while the mission runs, and the summary once it stops or changes.</summary>
    internal static void Update()
    {
        if (Sorties.Count == 0) return;
        if (!MissionManager.IsRunning || !ReferenceEquals(mission, MissionManager.CurrentMission))
        {
            Summarize();
            return;
        }
        missionT = Time.timeSinceLevelLoad;
        if (Despawns.Count == 0) return;
        foreach (Sortie sortie in Despawns) sortie.WriteDespawn();
        Despawns.Clear();
    }

    static void Summarize()
    {
        foreach (Sortie sortie in Sorties.Values) sortie.WriteSummary();
        Sorties.Clear();
        Despawns.Clear();
        mission = null;
    }

    internal static void Kill(PersistentID killerID, PersistentID killedID, KillType killedType)
    {
        if (killerID.IsValid && killerID != killedID && Sorties.TryGetValue(killerID, out Sortie killer))
            killer.Scored(Describe(killedID), killedType);
        if (Sorties.TryGetValue(killedID, out Sortie victim))
            victim.Died(killerID.IsValid ? Describe(killerID) : null, killedType);
    }

    static string Describe(PersistentID id)
    {
        if (Sorties.TryGetValue(id, out Sortie sortie)) return sortie.Who + " [" + sortie.Faction + "]";
        if (!UnitRegistry.TryGetPersistentUnit(id, out PersistentUnit unit) || unit.definition == null) return "unit " + id;
        Faction faction = unit.GetFaction();
        string type = string.IsNullOrEmpty(unit.definition.unitName) ? unit.definition.jsonKey : unit.definition.unitName;
        string who = unit.definition.jsonKey == CenturionKey ? CenturionName(unit.player != null, unit.unit, id)
            : unit.player != null ? "player (" + type + ")" : type;
        return who + " [" + (faction != null ? faction.factionName : "no faction") + "]";
    }

    static string CenturionName(bool player, Unit? unit, PersistentID id) =>
        player ? "player " + id : unit != null && !string.IsNullOrEmpty(unit.UniqueName) ? unit.UniqueName : "id " + id;

    static string NearestAirbase(Vector3 position)
    {
        Airbase? nearest = null;
        float best = float.PositiveInfinity;
        foreach (Airbase airbase in FactionRegistry.airbaseLookup.Values)
        {
            if (airbase == null || airbase.center == null) continue;
            float distance = (airbase.center.position - position).sqrMagnitude;
            if (distance >= best) continue;
            best = distance;
            nearest = airbase;
        }
        return nearest == null ? "no airbase"
            : Invariant($"{MissionGeometryLog.AirbaseName(nearest)} ({Mathf.Sqrt(best) / MPerNm:0.0} nm)");
    }

    internal sealed class Sortie
    {
        readonly Aircraft aircraft;
        readonly CenturionAwacsState awacs;
        readonly bool player;
        readonly string loadout;
        readonly int[] kills = new int[5];
        int[] ammo = System.Array.Empty<int>(), burst = System.Array.Empty<int>();
        string[] burstFrom = System.Array.Empty<string>();
        Dictionary<PersistentID, float>? credit;
        TelescopeController? telescope;
        PersistentID target;
        string state = "", awacsPhase = "", awacsHome = "", awacsAnchor = "", fate = "alive", despawnNear = "";
        float nextPollAt, nextSnapshotAt, disabledAt, awacsStandoffM, hpLogged = 1f;
        int partCount, damageEventsSeen, takeoffs, released;
        bool airborne, ejected, torn, locked, disabled, ended;

        internal string Who { get; }
        internal string Faction { get; }

        internal Sortie(Aircraft aircraft, CenturionAwacsState awacs, string loadout)
        {
            this.aircraft = aircraft;
            this.awacs = awacs;
            this.loadout = loadout;
            player = aircraft.Player != null;
            Who = CenturionName(player, aircraft, aircraft.persistentID);
            Faction = aircraft.NetworkHQ != null ? aircraft.NetworkHQ.faction.factionName : "no faction";
        }

        Pilot? Pilot => aircraft.pilots.Length > 0 ? aircraft.pilots[0] : null;
        float AltFt => aircraft.transform.GlobalPosition().y * FtPerM;
        float SpeedKt => (aircraft.CockpitRB().velocity - aircraft.GetWindVelocity()).magnitude * KtPerMps;

        internal void Spawn(string spawnAirbase)
        {
            // An air spawn starts at speed; radar altitude can still read 0 on the first physics step.
            airborne = aircraft.radarAlt > 5f || aircraft.CockpitRB().velocity.sqrMagnitude > 900f;
            SyncAmmo();
            nextSnapshotAt = Time.timeSinceLevelLoad + SnapshotS;
            Line(Who, Invariant($"spawn {Faction}, {(player ? "player" : "AI")}, loadout {loadout}, from {spawnAirbase}, {AltFt:0} ft, {(airborne ? "airborne" : "on ground")}, {Rounds()} rounds"));
        }

        // A wreck bounces: once disabled, its radar-altitude flips are wreck motion, not a sortie (run 20261016-004122 logged
        // twelve after one death).
        internal void Takeoff()
        {
            if (airborne || aircraft.disabled) return;
            airborne = true;
            takeoffs++;
            Line(Who, Invariant($"takeoff near {NearestAirbase(aircraft.transform.position)}, {SpeedKt:0} kt"));
        }

        internal void Touchdown()
        {
            if (!airborne || aircraft.disabled) return;
            airborne = false;
            Line(Who, Invariant($"touchdown near {NearestAirbase(aircraft.transform.position)}, {SpeedKt:0} kt"));
        }

        /// <summary>Every physics step; does its work once a second, and nothing once the sortie has ended.</summary>
        internal void Poll(int damageEvents)
        {
            float now = Time.timeSinceLevelLoad;
            if (now < nextPollAt) return;
            nextPollAt = now + PollS;
            Pilot? pilot = Pilot;
            // A crippled AI often ejects after the kill (AIPilotCombatModes.cs:1230-1249).
            if (!ejected && pilot != null && pilot.ejected)
            {
                ejected = true;
                Line(Who, Invariant($"ejected, {AltFt:0} ft, {SpeedKt:0} kt, hp {Hp() * 100f:0}%"));
            }
            if (ended) return;
            if (pilot != null && !player) PilotState(pilot);
            Releases();
            if (damageEvents != damageEventsSeen)
            {
                damageEventsSeen = damageEvents;
                Damage();
            }
            if (telescope == null) aircraft.TryGetComponent(out telescope);
            if (!torn && telescope != null && telescope.TearState == "torn")
            {
                torn = true;
                Line(Who, Invariant($"wing torn, span {telescope.Extension * 100f:0}%, {AltFt:0} ft, {SpeedKt:0} kt"));
            }
            // A stage shot off locks the span without the tear rule firing, and the AI then flies stock (AiHighStrike.Steer):
            // the stage line that says so carries no id (run 20261017-010052, bomber 1408).
            if (!locked && telescope != null && telescope.Locked)
            {
                locked = true;
                Line(Who, Invariant($"span locked, a stage gone, {AltFt:0} ft, {SpeedKt:0} kt"));
            }
            if (!disabled && aircraft.disabled)
            {
                disabled = true;
                disabledAt = now;
                FlushBursts();
                Line(Who, Invariant($"disabled, {AltFt:0} ft, {SpeedKt:0} kt, {(aircraft.IsLanded() ? "landed" : "airborne")}, hp {Hp() * 100f:0}%"));
            }
            // A client's kill RPC and the disabled sync arrive apart; the server sends no kill for a landed despawn (Aircraft.cs:2148).
            if (disabled && now - disabledAt >= LossGraceS)
            {
                ended = true;
                fate = aircraft.IsLanded() ? "landed and despawned" : "crashed";
                Line(Who, $"lost with no kill message: {fate}, near {NearestAirbase(aircraft.transform.position)}");
                return;
            }
            if (now >= nextSnapshotAt)
            {
                nextSnapshotAt = now + SnapshotS;
                Snapshot(pilot);
            }
        }

        void PilotState(Pilot pilot)
        {
            bool awacsActive = pilot.currentState == awacs;
            // A state's display name is null until it sets one (PilotBaseState.cs:77-80): the combat state names itself only
            // on a mode change (AIPilotCombatModes.cs:1048-1093), so it is nameless while it keeps its first mode.
            string current = pilot.GetCurrentState() ?? "";
            if (current != state)
            {
                if (!awacsActive) Line(Who, $"state {(state.Length == 0 ? "none" : state)} -> {(current.Length == 0 ? "none" : current)}");
                state = current;
            }
            if (awacsActive && (awacs.Phase != awacsPhase || awacs.HomeName != awacsHome || awacs.AnchorName != awacsAnchor
                || Mathf.Abs(awacs.StandoffM - awacsStandoffM) >= MPerNm))
            {
                awacsPhase = awacs.Phase;
                awacsHome = awacs.HomeName;
                awacsAnchor = awacs.AnchorName;
                awacsStandoffM = awacs.StandoffM;
                Line(Who, Invariant($"awacs {awacsPhase}, home {awacsHome}, anchor {awacsAnchor}, standoff {awacsStandoffM / MPerNm:0} nm, anchor {AnchorNm()} nm away, {AltFt:0} ft, {Position()}"));
            }
            Unit? unit = pilot.currentState is AIPilotCombatModes combat && CombatTarget != null ? CombatTarget(combat) : null;
            PersistentID id = unit != null ? unit.persistentID : PersistentID.None;
            if (id == target) return;
            target = id;
            Line(Who, unit != null
                ? Invariant($"target {Describe(id)}, {(unit.transform.position - aircraft.transform.position).magnitude / MPerNm:0.0} nm")
                : "target none");
        }

        string AnchorNm() => awacs.AnchorDistM >= 0f ? Invariant($"{awacs.AnchorDistM / MPerNm:0}") : "n/a";

        /// <summary>Map position in km, the mission file's globalPosition x and z, so a track can be plotted.</summary>
        string Position()
        {
            GlobalPosition p = aircraft.transform.GlobalPosition();
            return Invariant($"x {p.x / 1000f:0.0} km, z {p.z / 1000f:0.0} km");
        }

        void SyncAmmo()
        {
            List<WeaponStation> stations = aircraft.weaponStations;
            if (ammo.Length != stations.Count)
            {
                ammo = new int[stations.Count];
                burst = new int[stations.Count];
                burstFrom = new string[stations.Count];
            }
            for (int i = 0; i < stations.Count; i++) ammo[i] = stations[i].Ammo;
        }

        /// <summary>A burst is a run of seconds in which a station's ammo fell; it is written the first second it does not.</summary>
        void Releases()
        {
            List<WeaponStation> stations = aircraft.weaponStations;
            if (ammo.Length != stations.Count)
            {
                FlushBursts();
                SyncAmmo();
                return;
            }
            for (int i = 0; i < stations.Count; i++)
            {
                int left = stations[i].Ammo;
                if (left < ammo[i])
                {
                    if (burst[i] == 0) burstFrom[i] = ReleasePoint();
                    burst[i] += ammo[i] - left;
                }
                else if (burst[i] > 0) Flush(i);
                ammo[i] = left;
            }
        }

        void FlushBursts()
        {
            for (int i = 0; i < burst.Length; i++)
                if (burst[i] > 0) Flush(i);
        }

        /// <summary>Also runs after the station list has changed size (a loadout change), so a station index may be gone.</summary>
        void Flush(int station)
        {
            List<WeaponStation> stations = aircraft.weaponStations;
            WeaponStation? weapons = station < stations.Count ? stations[station] : null;
            string name = weapons != null && weapons.WeaponInfo != null ? weapons.WeaponInfo.weaponName : "station " + station;
            string left = weapons != null ? weapons.Ammo.ToString(System.Globalization.CultureInfo.InvariantCulture) : "?";
            released += burst[station];
            Line(Who, $"release {burst[station]} x {name}, {left} left, {burstFrom[station]}");
            burst[station] = 0;
        }

        /// <summary>Where a burst began: height, the AI's level range to its target, and map position.</summary>
        string ReleasePoint()
        {
            Pilot? pilot = Pilot;
            Unit? unit = pilot != null && pilot.currentState is AIPilotCombatModes combat && CombatTarget != null ? CombatTarget(combat) : null;
            string range = "";
            if (unit != null)
            {
                Vector3 toTarget = unit.transform.position - aircraft.transform.position;
                toTarget.y = 0f;
                range = Invariant($", target {toTarget.magnitude / MPerNm:0.0} nm");
            }
            return Invariant($"from {AltFt:0} ft{range}, {Position()}");
        }

        int Rounds()
        {
            int rounds = 0;
            foreach (WeaponStation station in aircraft.weaponStations) rounds += station.Ammo;
            return rounds;
        }

        /// <summary>Mean part hit points over 100 (UnitPart's full, UnitPart.cs:157), a detached or removed part counting 0.</summary>
        float Hp()
        {
            float sum = 0f;
            int count = 0;
            foreach (UnitPart part in aircraft.partLookup)
            {
                if (part == null) continue;
                count++;
                if (!part.IsDetached()) sum += Mathf.Clamp(part.hitPoints, 0f, 100f);
            }
            partCount = Mathf.Max(partCount, count);
            return partCount == 0 ? 1f : sum / (100f * partCount);
        }

        void Damage()
        {
            float hp = Hp();
            if (hp > hpLogged) hpLogged = hp;
            if (hpLogged - hp < DamageStep) return;
            Line(Who, Invariant($"damage hp {hp * 100f:0}% (was {hpLogged * 100f:0}%){Attacker()}"));
            hpLogged = hp;
        }

        /// <summary>The dealer with the most damage credit since the last damage line, on the server only.</summary>
        string Attacker()
        {
            Dictionary<PersistentID, float>? now = DamageCredit != null ? DamageCredit(aircraft) : null;
            if (now == null) return "";
            credit ??= new Dictionary<PersistentID, float>();
            PersistentID best = PersistentID.None;
            float most = 0f;
            foreach (KeyValuePair<PersistentID, float> pair in now)
            {
                credit.TryGetValue(pair.Key, out float before);
                if (pair.Value - before <= most) continue;
                most = pair.Value - before;
                best = pair.Key;
            }
            credit.Clear();
            foreach (KeyValuePair<PersistentID, float> pair in now) credit[pair.Key] = pair.Value;
            return best.IsValid ? ", by " + Describe(best) : "";
        }

        void Snapshot(Pilot? pilot)
        {
            string span = telescope != null ? Invariant($"{telescope.Extension * 100f:0}%") : "n/a";
            string awacsText = pilot != null && pilot.currentState == awacs
                ? Invariant($", awacs {awacs.Phase}, anchor {AnchorNm()} nm, standoff {awacs.StandoffM / MPerNm:0} nm") : "";
            Line(Who, Invariant($"snapshot {AltFt:0} ft, {SpeedKt:0} kt, hdg {aircraft.transform.eulerAngles.y:000}, {Position()}, fuel {aircraft.GetFuelLevel() * 100f:0}%, span {span}, hp {Hp() * 100f:0}%, state {(player ? "player" : state)}, target {(target.IsValid ? Describe(target) : "none")}, {Rounds()} rounds left, {Kills()}{awacsText}"));
        }

        string Kills()
        {
            var parts = new List<string>();
            for (int i = 0; i < kills.Length; i++)
                if (kills[i] > 0) parts.Add(kills[i] + " " + ((KillType)i).ToString().ToLowerInvariant());
            return parts.Count == 0 ? "no kills" : "kills " + string.Join(", ", parts);
        }

        internal void Scored(string victim, KillType killedType)
        {
            kills[(int)killedType]++;
            Line(Who, $"kill {killedType.ToString().ToLowerInvariant()} ({killedType.GetVerb(true)}): {victim}, {Kills()}");
        }

        internal void Died(string? killer, KillType killedType)
        {
            if (ended) return;
            ended = true;
            FlushBursts();
            fate = killer != null ? $"{killedType.GetVerb(true)} by {killer}" : $"{killedType.GetVerb(false)}, no damage credit";
            Line(Who, aircraft != null ? Invariant($"death: {fate}, {AltFt:0} ft, {SpeedKt:0} kt, hp {Hp() * 100f:0}%") : $"death: {fate}");
        }

        /// <summary>From CenturionAi.OnDestroy; written by <see cref="Update"/> only if the mission is still running, so a teardown stays quiet.</summary>
        internal void Despawned()
        {
            if (ended) return;
            ended = true;
            despawnNear = aircraft != null ? NearestAirbase(aircraft.transform.position) : "unknown";
            Despawns.Add(this);
        }

        internal void WriteDespawn()
        {
            FlushBursts();
            fate = airborne ? "despawned in flight" : "landed and despawned";
            Line(Who, $"{fate}, near {despawnNear}");
        }

        internal void WriteSummary()
        {
            for (int i = 0; i < burst.Length; i++) released += burst[i];
            Line(Who, $"summary {Faction}, {(player ? "player" : "AI")}, loadout {loadout}, {takeoffs} takeoffs, {released} rounds released, {Kills()}, {fate}{(ejected ? ", ejected" : "")}");
        }
    }
}
