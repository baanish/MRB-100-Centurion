using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// The laser C-RAM on hardpoint set 3: keeps the turret automatic, strips any non-missile target, counts acquisitions, shots
/// and kills (docs/M3-DESIGN.md, "CramGuard contract" and "C-RAM readout"). Added to each Centurion by
/// <see cref="CenturionSystems"/>; runs before Turret and Laser in the same physics step.
/// </summary>
[DefaultExecutionOrder(-10)]
sealed class CramGuard : MonoBehaviour
{
    /// <summary>Every live Centurion's guard, local and remote.</summary>
    internal static readonly List<CramGuard> All = new();

    /// <summary>The aircraft whose turret is a bound C-RAM, for <see cref="CramPatches"/>.</summary>
    internal static readonly HashSet<Unit> Carriers = new();

    internal static ConfigEntry<bool> CoverEscorts = null!;
    internal static ConfigEntry<bool> DebugCramFire = null!;

    Aircraft aircraft = null!;
    WeaponStation? station;
    Turret? turret;
    Laser? laser;
    Transform? cone;
    static readonly FieldInfo? ManualField = AccessTools.Field(typeof(Turret), "manual");
    static readonly AccessTools.FieldRef<Turret, FiringCone[]>? FiringCones =
        AccessTools.Field(typeof(Turret), "firingCones") == null ? null : AccessTools.FieldRefAccess<Turret, FiringCone[]>("firingCones");
    // Under 5% the capacitor reads as run out (docs/M3-DESIGN.md, G3.7): each draw scales with the stock supply curve, which
    // tends to 0 with the charge, so the laser there barely burns.
    const float CapacitorEmpty = 0.05f;
    internal readonly List<WeaponStation> AiStations = new();
    enum MissileClass { Self, Escort, Untargeted, Other }
    sealed class Acquisition
    {
        internal Missile Missile = null!;
        internal MissileClass Class;
        internal float FiredAt = float.NegativeInfinity;
    }
    readonly Dictionary<PersistentID, Acquisition> acquired = new();
    /// <summary>The last time this copy's laser fired with each missile as its target, on every peer: a remote copy fires as
    /// the owner's firing state repeats it (Unit.cs:1125-1153) at the station targets the server sends (Unit.cs:2054-2064).</summary>
    readonly Dictionary<PersistentID, float> firedOn = new();
    readonly HashSet<PersistentID> killed = new();
    readonly int[] acquisitions = new int[4];
    readonly int[] kills = new int[4];
    int shots, strips, coneMissiles, coneAir, coneGround, unmirroredFires;
    float lastObservedFire = float.NegativeInfinity, nonMissileFireS, bothSince = float.PositiveInfinity, nextConeCheck, mirroredAt = float.NegativeInfinity;
    bool boundWarning;
    string? repeatKey;
    string RepeatKey => repeatKey ??= "cram-remote-" + aircraft.persistentID.Id;

    public bool IsLocalPlayer => GameManager.GetLocalAircraft(out Aircraft local) && local == aircraft;
    public bool Simulated => aircraft.LocalSim;

    internal static void Install(ConfigFile config, CenturionLog log)
    {
        CoverEscorts = config.Bind("Cram", "CoverEscorts", true,
            "Missiles aimed at another unit (an escort or any friendly) are C-RAM targets; false leaves the C-RAM to missiles aimed at this aircraft and untargeted ones. The server and the owning client both choose turret targets, so peers should match");
        DebugCramFire = config.Bind("Debug", "CramFire", false,
            "While true, fires the local player aircraft's C-RAM every physics step, the stock path the trigger reaches (scenarios)");
        CoverEscorts.SettingChanged += (_, _) => log.Info($"config Cram.CoverEscorts = {CoverEscorts.Value}");
        DebugCramFire.SettingChanged += (_, _) => log.Info($"config Debug.CramFire = {DebugCramFire.Value}");
        log.Info($"config Cram.CoverEscorts = {CoverEscorts.Value}; Debug.CramFire = {DebugCramFire.Value}");
        if (ManualField == null) log.Warning("C-RAM: Turret.manual missing; laser_auto unreadable");
    }

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        foreach (string key in new[]
        {
            "laser_shots", "laser_firing", "laser_kills", "laser_target_hp_frac",
            "laser_kills_self", "laser_kills_escort", "laser_kills_untargeted",
            "laser_acquired_self", "laser_acquired_escort", "laser_acquired_untargeted",
            "laser_guard_strips", "laser_fire_nonmissile_s", "laser_auto", "laser_hold_fire", "laser_cover_escorts",
            "laser_cone_missiles", "laser_cone_air", "laser_cone_ground", "laser_cone_both_streak_s",
            "remote_laser_kills", "remote_laser_acquired_self", "remote_laser_shots", "remote_laser_unmirrored_fires", "remote_laser_pid",
        })
        {
            state[key] = AircraftReadout.NotRead;
        }
    }

    internal static void Read(Dictionary<string, object> state, Aircraft aircraft)
    {
        if (aircraft.TryGetComponent<CramGuard>(out var guard)) guard.ReadLocal(state);
    }

    internal static void ReadRemote(Dictionary<string, object> state)
    {
        foreach (var guard in All)
        {
            if (guard == null || guard.IsLocalPlayer || guard.Simulated || guard.turret == null) continue;
            state["remote_laser_kills"] = guard.killed.Count;
            state["remote_laser_acquired_self"] = guard.acquisitions[(int)MissileClass.Self];
            state["remote_laser_shots"] = guard.shots;
            state["remote_laser_unmirrored_fires"] = guard.unmirroredFires;
            state["remote_laser_pid"] = (double)guard.aircraft.persistentID.Id;
            break;
        }
    }

    internal static CramGuard? ForLaser(Laser weapon) => weapon.attachedUnit != null
        && weapon.attachedUnit.TryGetComponent<CramGuard>(out var guard) && guard.laser == weapon ? guard : null;

    internal bool WithinLaserCone(Vector3 direction) => cone != null && !aircraft.disabled
        && Vector3.Angle(cone.forward, direction) <= 80f;

    bool Firing => station != null && lastObservedFire > float.NegativeInfinity
        && Time.timeSinceLevelLoad - station.LastFiredTime < 0.25f;

    void ReadLocal(Dictionary<string, object> state)
    {
        if (turret == null || laser == null || station == null) return;
        state["laser_shots"] = shots;
        state["laser_target_hp_frac"] = AircraftReadout.NotRead;
        if (laser.GetTarget() is { } target)
        {
            var parts = target.GetAllParts();
            float health = 0f;
            foreach (var part in parts) health += part.IsDetached() ? 0f : Mathf.Clamp01(part.hitPoints / 100f);
            if (parts.Count > 0) state["laser_target_hp_frac"] = health / parts.Count;
        }
        state["laser_firing"] = Firing ? 1 : 0;
        state["laser_kills"] = killed.Count;
        foreach (var entry in new[] { ("self", MissileClass.Self), ("escort", MissileClass.Escort), ("untargeted", MissileClass.Untargeted) })
        {
            state["laser_kills_" + entry.Item1] = kills[(int)entry.Item2];
            state["laser_acquired_" + entry.Item1] = acquisitions[(int)entry.Item2];
        }
        state["laser_guard_strips"] = strips;
        state["laser_fire_nonmissile_s"] = Math.Round(nonMissileFireS, 3);
        state["laser_auto"] = ManualField?.GetValue(turret) is bool manual ? (manual ? 0 : 1) : AircraftReadout.NotRead;
        if (IsLocalPlayer && SceneSingleton<CombatHUD>.i != null)
            state["laser_hold_fire"] = SceneSingleton<CombatHUD>.i.turretAutoControl ? 0 : 1;
        state["laser_cover_escorts"] = CoverEscorts.Value ? 1 : 0;
        state["laser_cone_missiles"] = coneMissiles;
        state["laser_cone_air"] = coneAir;
        state["laser_cone_ground"] = coneGround;
        state["laser_cone_both_streak_s"] = Math.Round(Mathf.Max(0, Time.timeSinceLevelLoad - bothSince), 3);
    }

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        All.Add(this);
        aircraft.weaponManager.OnWeaponsLoaded += Bind;
    }

    void Bind()
    {
        Carriers.Remove(aircraft);
        station = null;
        turret = null;
        laser = null;
        cone = null;
        AiStations.Clear();
        AiStations.AddRange(aircraft.weaponStations);
        coneMissiles = coneAir = coneGround = 0;
        bothSince = float.PositiveInfinity;
        lastObservedFire = float.NegativeInfinity;
        var sets = aircraft.weaponManager.hardpointSets;
        if (sets.Length <= 3 || sets[3].weaponMount == null || sets[3].weaponMount.jsonKey != "baanish_centurion_cram") return;
        foreach (var candidate in aircraft.weaponStations)
            if (candidate.WeaponInfo == sets[3].weaponMount.info) { station = candidate; break; }
        if (station != null && station.Turrets.Count > 0 && station.Weapons.Count > 0)
        {
            turret = station.Turrets[0];
            laser = station.Weapons[0] as Laser;
            // With emission patches rolled back, stop the stock unbounded damage loop too.
            if (laser != null && CenturionPlugin.FeaturesOff.Contains("cram-emission")) laser.enabled = false;
            if (turret != null) cone = turret.transform.parent.Find("cram_cone_aft");
        }
        if (turret == null || laser == null || cone == null)
        {
            if (!boundWarning) CenturionPlugin.Log.Warning("C-RAM: missing station, turret, laser or cram_cone_aft; guard off");
            boundWarning = true;
            turret = null;
            return;
        }
        AiStations.Remove(station!);
        Carriers.Add(aircraft);
        CenturionPlugin.Log.Info($"C-RAM bound: {aircraft.persistentID}, station {station!.Number}");
    }

    void FixedUpdate()
    {
        if (turret == null || laser == null || station == null || aircraft.disabled)
        {
            Carriers.Remove(aircraft);
            return;
        }
        float now = Time.timeSinceLevelLoad;
        // A player who selects the C-RAM aims it, as stock turrets do (WeaponStation.SetStationActive sets the turret manual,
        // WeaponStation.cs:62-86): with the view, or at a designated target of any kind. Any other station hands it back
        // to automatic missile defence (owner, 2026-10-17). AI pilots never select it (CramPatches).
        bool pilotAiming = aircraft.Player != null && aircraft.weaponManager.currentWeaponStation == station;
        Unit laserTarget = laser.GetTarget();
        // LastFiredTime starts at zero on an unused station; only a positive, advancing stamp starts a burst.
        if (station.LastFiredTime > 0f && station.LastFiredTime > lastObservedFire)
        {
            if (station.LastFiredTime - lastObservedFire > 0.25f) shots++;
            lastObservedFire = station.LastFiredTime;
        }
        Unit target = turret.GetTarget();
        if (Simulated && target is Missile missile && !missile.disabled && !acquired.ContainsKey(missile.persistentID))
        {
            MissileClass kind = Classify(missile);
            acquired.Add(missile.persistentID, new Acquisition { Missile = missile, Class = kind });
            acquisitions[(int)kind]++;
            missile.onDisableUnit += OnMissileDisabled;
        }
        if (now - station.LastFiredTime < 0.1f && station.LastFiredTime > 0f)
        {
            if (laserTarget is Missile firedMissile)
            {
                firedOn[firedMissile.persistentID] = station.LastFiredTime;
                if (acquired.TryGetValue(firedMissile.persistentID, out var acquisition)) acquisition.FiredAt = station.LastFiredTime;
            }
            else if (laserTarget != null && !laserTarget.disabled)
                nonMissileFireS += Time.fixedDeltaTime;
        }
        if (!Simulated) CountUnmirrored(now);
        if (!Simulated && aircraft.IsServer && !aircraft.IsClient) MirrorOnDedicatedServer();
        if (!pilotAiming && target != null && !target.disabled && target is not Missile)
        {
            turret.SetTarget(PersistentID.None, station.Number);
            laser.SetTarget(null);
            strips++;
        }
        else if (!pilotAiming && laserTarget != null && !laserTarget.disabled && laserTarget is not Missile)
        {
            laser.SetTarget(null);
            strips++;
        }
        if (IsLocalPlayer && TelescopeController.Diagnostics.Value && DebugCramFire.Value) station.Fire(aircraft, null);
        if (now >= nextConeCheck)
        {
            nextConeCheck = now + 1f;
            CountCone(now);
        }
    }

    /// <summary>
    /// The laser's damage is applied only where the server runs (Laser.cs:293), and a listen host repeats a client's laser
    /// through two paths a dedicated server lacks: the firing state's hook runs only on a host (Unit.cs:465-473), and the station
    /// targets the server's turret search picks reach weapons only through a ClientRpc, which never runs locally without a local
    /// client (Mirage ClientRpcSender.ShouldInvokeLocally). So on a dedicated server this copy's station takes the server
    /// turret's own target and fires while the owner's firing state has it set, as RemoteFireWeaponStation does on a host.
    /// </summary>
    void MirrorOnDedicatedServer()
    {
        Unit? target = turret!.GetTarget();
        if (laser!.GetTarget() != target)
        {
            // WeaponStation.SetStationTargets for its one turret and one weapon (WeaponStation.cs:310-348).
            turret.SetTarget(target != null ? target.persistentID : PersistentID.None, station!.Number);
            laser.SetTarget(target);
        }
        if (aircraft.NetworkremoteWeaponStates.Get(station!.Number)) station.RemoteFireAuto(aircraft);
    }

    /// <summary>
    /// Whether this C-RAM can take a missile, by the stock turret's own tests (Turret.AssessTargetPriority, Turret.cs:459-468): the
    /// missile inside the turret's firing cone from the turret (CenturionAuthor.Cram's CramConeAngle) and tracked by the HQ, which
    /// the turret's acquisition needs; and the capacitor above <see cref="CapacitorEmpty"/>. Range is left out on purpose: a
    /// missile aimed at this aircraft comes inside the laser's range before it arrives. <see cref="AiCramHold"/> reads it; why
    /// not, for its log, when false.
    /// </summary>
    internal bool CanEngage(Missile missile, out string why)
    {
        why = CenturionPlugin.FeaturesOff.Contains("cram-emission") ? "C-RAM emission disabled"
            : turret == null || laser == null || station == null || aircraft.disabled || FiringCones == null ? "no C-RAM fitted"
            : aircraft.GetPowerSupply() is not { } power || power.GetCharge() < CapacitorEmpty ? "capacitor empty"
            : !FiringConeChecker.VectorWithinFiringCones(FiringCones(turret), missile.transform.position - turret.transform.position, out _) ? "outside the C-RAM cone"
            : aircraft.NetworkHQ == null || aircraft.NetworkHQ.GetTrackingData(missile.persistentID) == null ? "not tracked"
            : "";
        return why.Length == 0;
    }

    MissileClass Classify(Missile missile)
    {
        if (missile.targetID == aircraft.persistentID) return MissileClass.Self;
        if (!UnitRegistry.TryGetUnit(missile.targetID, out Unit target) || target == null || target.disabled) return MissileClass.Untargeted;
        return target is Missile ? MissileClass.Other : MissileClass.Escort;
    }

    void OnMissileDisabled(Unit unit)
    {
        unit.onDisableUnit -= OnMissileDisabled;
        // Keep the acquisition and firing stamp: the replicated kill message can arrive after the unit disables.
    }

    /// <summary>
    /// A kill message naming this aircraft as the killer of a missile counts only if this copy's laser fired on that missile:
    /// in the last second, or in this step, since on the server the laser's damage kills the missile and sends the message
    /// inside the same physics step as the shot (Laser.cs:293-297), before <see cref="FixedUpdate"/> stamps it. A bomb's
    /// fragments that kill a missile name the carrier too (DamageEffects.cs:113), and never count.
    /// </summary>
    internal void CountKill(PersistentID id)
    {
        float now = Time.timeSinceLevelLoad;
        bool firingAt = laser != null && station != null && laser.GetTarget() is Missile target && target.persistentID == id
            && station.LastFiredTime > 0f && now - station.LastFiredTime < 0.1f;
        bool firedAt = firedOn.TryGetValue(id, out float at) && now - at <= 1f;
        if (!firingAt && !firedAt)
        {
            CenturionPlugin.Log.Stage("cram-kill-other", $"{aircraft.persistentID}: missile {id} killed by something other than the laser; not counted");
            return;
        }
        if (!killed.Add(id)) return;
        if (acquired.TryGetValue(id, out var acquisition)) kills[(int)acquisition.Class]++;
        CenturionPlugin.Log.Info($"C-RAM kill: {aircraft.persistentID} killed missile {id} ({(Simulated ? "simulated here" : "remote")}, {killed.Count} in all)");
    }

    /// <summary>
    /// A remote copy fires only while the owner's firing state has the station set (Unit.RemoteFireWeaponStation); a shot
    /// with the state clear for longer than a sync interval or two would be this peer engaging on its own.
    /// </summary>
    void CountUnmirrored(float now)
    {
        if (aircraft.NetworkremoteWeaponStates.Get(station!.Number))
        {
            mirroredAt = now;
            if (CenturionPlugin.Log.StageDue(RepeatKey))
            {
                Unit? aimedAt = laser!.GetTarget();
                float offBarrel = aimedAt != null ? Vector3.Angle(laser.transform.forward, aimedAt.transform.position - laser.transform.position) : float.NaN;
                CenturionPlugin.Log.StageLine(RepeatKey, $"{aircraft.persistentID}: repeating the owner's fire; laser target {(aimedAt != null ? aimedAt.persistentID.ToString() : "none")}, turret target {(turret!.GetTarget() is { } t ? t.persistentID.ToString() : "none")}, barrel {offBarrel:0.0} deg off it, capacitor {(aircraft.GetPowerSupply() is { } power ? power.GetChargeKJ() : float.NaN):0} kJ");
            }
        }
        if (station.LastFiredTime > 0f && now - station.LastFiredTime < 0.1f && station.LastFiredTime - mirroredAt > 0.3f)
        {
            unmirroredFires++;
            mirroredAt = now; // one count per burst
            CenturionPlugin.Log.Warning($"C-RAM on {aircraft.persistentID}: fired here without the owner's firing state");
        }
    }

    void CountCone(float now)
    {
        coneMissiles = coneAir = coneGround = 0;
        var hq = aircraft.NetworkHQ;
        if (hq != null && cone != null)
            foreach (var track in hq.trackingDatabase.Values)
            {
                if (!track.TryGetUnit(out Unit unit) || unit == null || unit.disabled || unit.NetworkHQ == hq
                    || !hq.IsTargetPositionAccurate(unit, 10f)) continue;
                Vector3 offset = track.GetPosition() - cone.GlobalPosition();
                if (offset.sqrMagnitude > 8000f * 8000f || Vector3.Angle(cone.forward, offset) > 80f) continue;
                if (unit is Missile) coneMissiles++;
                else if (unit is Aircraft) coneAir++;
                else if (unit is GroundVehicle || unit is Building || unit is Ship) coneGround++;
            }
        if (coneAir == 0 || coneGround == 0) bothSince = float.PositiveInfinity;
        else if (float.IsPositiveInfinity(bothSince)) bothSince = now;
    }

    void OnDestroy()
    {
        All.Remove(this);
        Carriers.Remove(aircraft);
        aircraft.weaponManager.OnWeaponsLoaded -= Bind;
        foreach (var acquisition in acquired.Values)
            if (acquisition.Missile != null) acquisition.Missile.onDisableUnit -= OnMissileDisabled;
    }
}
