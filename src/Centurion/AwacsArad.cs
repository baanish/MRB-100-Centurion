using System.Collections.Generic;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The AI AWACS's ARAD-116 shots (owner, docs/DECISIONS.md, 2026-10-18): salvoes of two at a hostile surface emitter, only from
/// outside its reach. <see cref="CenturionAwacsState"/> runs it, so only AI AWACS fire; a player's Centurion never does.
/// - A good target (<see cref="Choose"/>): a hostile surface unit its side tracks at an accurate position, whose radar is on,
///   inside the ARAD's range and line of sight, that stock's scoring lets the ARAD take (CombatAI.AnalyzeTarget, CombatAI.cs:107-170:
///   minRadar wants a live emission, and a target with more missiles at it than it needs scores 0). SAM and AA radars come
///   first, then stock's threat to this aircraft's type (the order CombatAI.DistributeTargets attacks in), then the longer reach.
/// - The safe distance is <see cref="ThreatRangeM"/> plus <see cref="MarginM"/>, slant, as stock's GetSafeStandoffDist measures:
///   it fires only from beyond it and never flies closer to make a shot.
/// - A salvo is two at one target, stock's SalvoFire on a two-entry target list (WeaponManager.cs:576-610), and one is in the
///   air at a time: the next waits until both are down or <see cref="ResolveS"/> has passed.
/// - The launch cone is the ARAD's minAlignment taken on the level bearing, as AiHighStrike.BeforeUseMissiles takes it. Out of
///   it, the orbit turns at the target at the orbit's height while one turn radius outside the safe distance (<see cref="TurnAim"/>).
/// </summary>
sealed class AwacsArad
{
    const float MarginM = 10000f, ResolveS = 60f;
    // A site's launchers and radar sit apart: an R9's radar truck carries no missiles of its own.
    const float SiteM = 2000f;
    // Launches follow Fire by the bay doors and stock's 1.1 fireInterval spacing; missiles registering later belong to no salvo.
    const float LaunchGraceS = 10f;
    // The turn hands back to the orbit this far inside the cone, so the next once-a-second check still finds it aligned.
    const float AimM = 8000f, TurnRetryS = 120f, ConeMarginDeg = 10f;

    Unit? aim;
    float aimSafeM, aimThreatM, aimConeDeg, turnBlockedUntil = float.NegativeInfinity;
    bool turning, open;
    Unit? salvoTarget;
    string salvoName = AircraftReadout.NoText;
    float firedAt;
    int salvo;
    readonly List<Missile> missiles = new();

    internal int MissilesInFlight
    {
        get
        {
            missiles.RemoveAll(missile => missile == null || missile.disabled);
            return missiles.Count;
        }
    }

    internal void Bind(Aircraft aircraft)
    {
        aircraft.onRegisterMissile -= OnMissile;
        aircraft.onRegisterMissile += OnMissile;
    }

    internal void Unbind(Aircraft aircraft)
    {
        aircraft.onRegisterMissile -= OnMissile;
        aim = null;
        turning = false;
    }

    void OnMissile(Missile missile)
    {
        if (open && salvoTarget != null && Time.timeSinceLevelLoad - firedAt < LaunchGraceS && missile.targetID == salvoTarget.persistentID)
            missiles.Add(missile);
    }

    /// <summary>Once a second: closes a salvo that is done, then picks a good target and fires on it once it is in the cone.</summary>
    internal void Tick(Aircraft aircraft, Pilot pilot, bool orbiting)
    {
        aim = null;
        if (open && !Resolved()) return;
        WeaponStation? station = Station(aircraft);
        if (!orbiting || station == null) return;
        aim = Choose(aircraft, station, out aimThreatM);
        if (aim == null)
        {
            turning = false;
            return;
        }
        aimSafeM = aimThreatM + MarginM;
        aimConeDeg = station.WeaponInfo.targetRequirements.minAlignment;
        if (AiHighStrike.LevelAngle(aircraft, aim.transform.position - aircraft.transform.position) >= aimConeDeg
            || !station.Ready() || station.SalvoInProgress)
        {
            return;
        }

        WeaponManager weapons = aircraft.weaponManager;
        if (weapons.currentWeaponStation != station) weapons.SetActiveStation(station.Number);
        List<Unit> targets = weapons.GetTargetList();
        targets.Clear();
        targets.Add(aim);
        targets.Add(aim);
        weapons.TargetListChanged();
        int rounds = station.Ammo;
        missiles.Clear();
        open = true;
        salvoTarget = aim;
        salvoName = aim.definition.unitName;
        firedAt = Time.timeSinceLevelLoad;
        salvo++;
        turning = false;
        pilot.Fire();
        float range = FastMath.Distance(aircraft.GlobalPosition(), aim.GlobalPosition());
        CenturionPlugin.Log.Info(Invariant(
            $"AWACS ARAD salvo {salvo}: 2 at {salvoName} ({aim.definition.jsonKey}, id {aim.persistentID}), range {range / 1000f:0.0} km, threat range {aimThreatM / 1000f:0.0} km, safe {aimSafeM / 1000f:0.0} km, {rounds} rounds before"));
        aim = null;
    }

    bool Resolved()
    {
        float age = Time.timeSinceLevelLoad - firedAt;
        int flying = MissilesInFlight;
        if (age < ResolveS && (flying > 0 || age < LaunchGraceS)) return false;
        open = false;
        bool destroyed = salvoTarget == null || salvoTarget.disabled;
        CenturionPlugin.Log.Info(Invariant(
            $"AWACS ARAD salvo {salvo} resolved after {age:0} s: {salvoName} {(destroyed ? "destroyed" : "still up")}, {flying} missile(s) still flying"));
        salvoTarget = null;
        return true;
    }

    /// <summary>The ARAD station with rounds left: a missile that wants a radar emission (minRadar), whatever the rack.</summary>
    static WeaponStation? Station(Aircraft aircraft)
    {
        foreach (WeaponStation station in aircraft.weaponStations)
            if (station != null && station.Ammo > 0 && station.WeaponInfo != null && station.WeaponInfo.missile
                && station.WeaponInfo.targetRequirements.minRadar > 0f)
                return station;
        return null;
    }

    static bool IsHostileSurface(Unit unit, FactionHQ hq) => unit != null && !unit.disabled && unit.NetworkHQ != null
        && unit.NetworkHQ != hq && unit is not Aircraft && unit is not Missile && unit.radarAlt < 10f;

    Unit? Choose(Aircraft aircraft, WeaponStation station, out float threatM)
    {
        threatM = 0f;
        FactionHQ hq = aircraft.NetworkHQ;
        if (hq == null) return null;
        TargetRequirements requirements = station.WeaponInfo.targetRequirements;
        GlobalPosition position = aircraft.GlobalPosition();
        Unit? best = null;
        (bool AntiAir, float Threat, float Reach) bestKey = default;
        int emitters = 0, inRange = 0, outside = 0;
        foreach (TrackingInfo tracking in hq.trackingDatabase.Values)
        {
            if (!tracking.TryGetUnit(out Unit unit) || !IsHostileSurface(unit, hq) || !unit.HasRadarEmission()
                || !hq.IsTargetPositionAccurate(unit, 1000f))
            {
                continue;
            }

            emitters++;
            float distance = FastMath.Distance(position, tracking.lastKnownPosition);
            if (distance >= requirements.maxRange || distance <= requirements.minRange) continue;
            inRange++;
            float reach = ThreatRangeM(hq, unit, tracking.lastKnownPosition);
            if (distance <= reach + MarginM) continue;
            outside++;
            if ((requirements.lineOfSight && !unit.LineOfSight(aircraft.transform.position, 1000f))
                || CombatAI.AnalyzeTarget(station, aircraft, tracking, 0f, distance).opportunity <= 0f)
            {
                continue;
            }

            var key = (reach > 0f || unit.definition.roleIdentity.antiAir > 0f, aircraft.definition.ThreatPosedBy(unit.definition.roleIdentity), reach);
            if (best != null && key.CompareTo(bestKey) <= 0) continue;
            best = unit;
            bestKey = key;
            threatM = reach;
        }

        if (best == null && emitters > 0 && CenturionPlugin.Log.StageDue("awacs-arad"))
        {
            CenturionPlugin.Log.StageLine("awacs-arad", Invariant(
                $"{aircraft.name} {aircraft.persistentID}: no ARAD shot: {emitters} hostile surface emitter(s) tracked, {inRange} inside {requirements.maxRange / 1000f:0} km, {outside} outside their threat range plus {MarginM / 1000f:0} km, none lockable there"));
        }
        return best;
    }

    /// <summary>
    /// The longest anti-air reach (WeaponInfo.effectiveness.antiAir above 0) of the target and every hostile surface unit its
    /// side tracks within <see cref="SiteM"/> of it: the SAM it carries or its site's. Units carry their stations' maxRange
    /// (Unit.GetMaxRange, Unit.cs:894), which for a ship counts its anti-ship missiles too, so the stations are read here.
    /// </summary>
    static float ThreatRangeM(FactionHQ hq, Unit target, GlobalPosition at)
    {
        float reach = 0f;
        foreach (TrackingInfo tracking in hq.trackingDatabase.Values)
        {
            if (!tracking.TryGetUnit(out Unit unit) || (unit != target && (!IsHostileSurface(unit, hq)
                || !FastMath.InRange(tracking.lastKnownPosition, at, SiteM))))
            {
                continue;
            }

            foreach (WeaponStation station in unit.weaponStations)
                if (station != null && station.WeaponInfo != null && station.WeaponInfo.effectiveness.antiAir > 0f)
                    reach = Mathf.Max(reach, station.WeaponInfo.targetRequirements.maxRange);
        }
        return reach;
    }

    /// <summary>
    /// With a good target out of the launch cone, the orbit's destination turned at it, at the orbit's height, while the AWACS
    /// is a turn radius or more outside the safe distance, until it is <see cref="ConeMarginDeg"/> inside the cone; a turn that
    /// comes inside that distance gives way to the orbit for <see cref="TurnRetryS"/>.
    /// </summary>
    internal bool TurnAim(Aircraft aircraft, GlobalPosition position, float height, ref GlobalPosition destination)
    {
        if (aim == null || aim.disabled)
        {
            turning = false;
            return false;
        }

        float now = Time.timeSinceLevelLoad;
        bool roomy = FastMath.Distance(position, aim.GlobalPosition()) > aimSafeM + AwacsOrbit.TurnRadiusM;
        if (turning && !roomy)
        {
            turning = false;
            turnBlockedUntil = now + TurnRetryS;
        }
        else if (!turning && roomy && now >= turnBlockedUntil)
        {
            turning = true;
        }
        if (!turning) return false;

        Vector3 toward = aim.transform.position - aircraft.transform.position;
        if (AiHighStrike.LevelAngle(aircraft, toward) < aimConeDeg - ConeMarginDeg) return false;
        toward.y = 0f;
        if (toward.sqrMagnitude < 1f) return false;
        GlobalPosition turned = position + toward.normalized * AimM;
        turned.y = height;
        destination = turned;
        return true;
    }
}
