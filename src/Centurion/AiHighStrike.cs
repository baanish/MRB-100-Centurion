using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// An AI Centurion carrying bombs or missiles flies the owner's doctrine: above the escorts at its loaded ceiling, extended,
/// releasing from far enough to saturate the defences, and above the reach of IR SAMs when alone (docs/DECISIONS.md,
/// 2026-10-15); a missile load launches from that height and speed too (owner, 2026-10-18).
/// The stock combat AI flies it as a jet striker instead: terrain following near 190 m and every attack mode aimed low,
/// and its height command is clamped to 8,000 m (AIPilotCombatModes.cs:1261); in the end-game Escalation one of seven
/// airborne bombers released, the rest died at 1,700 to 3,400 ft to IR SAMs, AAA, fighters and a corvette (run 20261016-004122).
/// <see cref="Steer"/>, from the AutoAim prefix (<see cref="BeforeAutoAim"/>), keeps each stock mode's bearing and
/// replaces its height in transit and attack (FlyingToTarget, NoTarget, Bombing, GlideBombing, UsingMissiles, BreakOffAttack):
/// - Below <see cref="NearGroundM"/> it climbs out on the stock terrain following, aimed a step above its height, so it
///   clears the hills it skimmed at 22 to 57 m and lost a wing stage to (run 20261016-043908, t=135 to 149), on the climb
///   hold's bearing (below) instead of stock's at the target.
/// - The cruise height, by mass, is 500 m under where its climb and turns still hold their speed and height, at most
///   57,000 ft (<see cref="CruiseAtMtowM"/>; tools/fm/centurion_cruise_band.py). It turns level, at a true
///   <see cref="BankDeg"/> (<see cref="LevelTurnAim"/>, <see cref="AutoAimBankScale"/>).
/// - Speed on pitch, the AWACS climb's law (<see cref="CenturionAwacsState.ClimbLeadPerMps"/>): it climbs at 150 m/s EAS up to
///   <see cref="ClimbSpeedMps"/> and cruises at <see cref="CruiseSpeedMps"/>, under the extended wing's drag rise at Mach 0.76;
///   banks are held to <see cref="BankDeg"/>. If the span schedule has retracted the wing (above 205 m/s EAS, so low down,
///   TelescopeController.AiSchedule), it slows until the schedule extends it again.
/// - Bomb ingress scales from 15,000 to 50,000 ft with the target's distance from the spawn airbase. It climbs on the
///   short circle where there is room to get aligned, or on the standoff racetrack. Missiles keep their previous ingress.
/// The stock attack modes then release from height: unguided bombs on the stock vacuum fall-time solution
/// (AIPilotCombatModes.cs:619-651), glide bombs once <see cref="GlideReleaseRatio"/> is met, on every target near the aim
/// point, missiles on the stock salvo (:904-917). A radar-missile evasion the C-RAM can't cover (<see cref="AiCramHold"/>) keeps stock's bearing and jammer at the
/// profile's height, bank and throttle; an IR one keeps the stock throttle cut. Once the rounds are gone the stock state takes over: NoTarget heads for the nearest friendly airbase
/// and after 15 s without a target hands over to the landing state (AIPilotCombatModes.cs:362-379); with rounds left it
/// waits out its own missiles in flight first (<see cref="BeforeNoTarget"/>).
/// </summary>
static class AiHighStrike
{
    // 500 m under where the AI's own sortie last holds in the replica, on the split tail with LevelTurnAim: the climb on the
    // hold, the cruise and a 180 deg break-off turn at 20 deg without departing, linear in mass and within the replica's
    // 250 m steps: 15,500 m (50,900 ft) at 198.7 t, 15,800 m at 188 t, 16,750 m at 157 t, the cap below about 136 t
    // (tools/fm/centurion_cruise_band.py, S62). Above it the turn departs as run 20261016-175733's did from 14,500 m on the
    // single ruddervator, before LevelTurnAim: it sinks 770 to 850 m and passes 215 m/s, at 8 deg of AoA, where the
    // fly-by-wire's alpha limiter has cut the pitch rate a stick asks to a quarter. The elevator still trims a 1.1 g turn at
    // 208 m/s within 0.7 of the stick to 53,800 ft at 198.7 t and 55,400 ft at 188 t.
    const float CruiseAtMtowM = 15500f, MtowKg = 198700f, CruisePerKgM = 0.0300f, CruiseCapM = 17374f;
    // Mach 0.69 and 0.72 at the game's 290 m/s above 10 km (LevelInfo.GetSpeedOfSound). The climb's 10 m/s overspeed
    // guard tops out near 212 m/s; the extended wing's drag rise starts at 220 m/s (Mach 0.76).
    const float ClimbEasMps = 150f, ClimbSpeedMps = 200f, CruiseSpeedMps = 208f, CruiseEnergyMps = 203f, CruiseEntryM = 300f;
    // 1.06 g in a level turn, under the 1.1 g the cruise height leaves room for; at 26 to 27 deg the climb hold's turns
    // saturated the elevator at 15 km (runs 20261016-040359 and -042205, t=424 to 457). The bank AutoAim allows, once
    // AutoAimBankScale is undone; at 208 m/s it turns on 12.1 km, 2.2 km outside the racetrack's 10 km end caps at most.
    const float BankDeg = 20f;
    // AutoAim's bank target is the waypoint's side against a lift of 1 / max(angle off, 5 deg) (AutopilotPlane.cs:79,
    // 105-107): 6 deg off still bids about 40 deg, so the bank holds at BankDeg through a turn.
    const float AimTurnDeg = 6f;
    // The share of that side angle's pull on the pitch axis LevelTurnAim takes off. All of it left a turn's pull to the
    // height error, which AutoAim's pitch loop builds slowly up there (its P is 0.04 of stick a degree, and the fly-by-wire
    // cuts the rate per stick to 0.3 and by the alpha limiter past 5 deg): a 180 deg turn at 20 deg sagged 330 to 410 m at
    // 16 to 16.5 km and 186 t. At 0.4 the 1.2 deg of pull it keeps at 20 deg of bank stays under the 1.4 deg a slow
    // bomber's command asks down (200 m in 8 km), so it still can't climb past its command, and the sag is 200 to 305 m
    // (tools/fm/ai_high_strike.py).
    const float PullCancel = 0.4f;
    // The span schedule extends below 190 m/s EAS (TelescopeController.AiSchedule); retracted, the bomber flies under it
    // until it does.
    const float ReextendEasMps = 180f;
    const float LookaheadM = 8000f, NearGroundM = 1000f, ClimbOutStepM = 250f;
    // The hold's standoff is at least 30 km: outside a Boltstrike's 15 km x 1.2 and short of the glide release.
    // A new target within HoldMoveM of the hold's anchor keeps the track: in G6.1 the AI switched among T1 and two K92
    // structures every 80 to 250 s (run 20261016-043908).
    const float HoldFloorM = 30000f, HoldMoveM = 5000f;
    // Start aligning during the last 1,600 m of climb, deliberately below the scaled release gate.
    // The circle gives room for the glide solution and one turn, with the proven 20 km minimum.
    const float BombTurnLeadM = 1600f, BombCircleMinM = 20000f, BombCircleMarginM = 2000f;
    const float BombCircleBankDeg = 28f, BombCircleBankCeilingM = 10000f;
    // Hold through the run and any retry. The offset leaves room for the height lost in a turn
    // without letting the energy climb carry a nearby attack back to cruise altitude.
    const float BombRunHeightMarginM = 600f;
    // The scaled ingress ruling is for bombs. Preserve the previous missile gate and threat standoff.
    const float MissileNearHomeM = 40000f, MissileNearIngressM = 6096f;
    // Stock releases a glide bomb once (height + 0.03 v^2) / slant range passes 0.2 (AIPilotCombatModes.cs:555-558): from
    // 55,000 ft that is 89 km, past any glide. 0.6 is the 25 km release of the 55,000 ft standoff case (slant 30 km), and
    // inside the 28 km release from 60,000 ft whose bombs destroyed 15 targets (docs/BALANCE.md, standoff).
    const float GlideReleaseRatio = 0.6f;
    // A level turn at BankDeg and the cruise speed has a 12.1 km radius. A missile target nearer than 1.5 radii and off the
    // launch alignment can sit inside the turn, where the bearing never comes round: in run 20261018-034423 the Tusko-B
    // bomber, given Vigil Cay's tower 12 nm out after sinking S1, circled it 6 to 19 km away at 54,000 ft for 2,800 s with
    // 41 rounds. Extended to 35 km, its turn back stays 25 km or more out and lines up.
    const float MissileExtendInM = 18000f, MissileExtendOutM = 35000f;
    // LookForMissileTargets' neighbourhood and target cap (CombatAI.cs:180-186).
    const float NeighbourM = 1000f;
    const int MaxGlideTargets = 16;
    const float RefreshS = 1f;

    // HarmonyX reads an enum field through its underlying int, so the modes are read every step without boxing.
    static readonly AccessTools.FieldRef<AIPilotCombatModes, int>? AttackMode = IntField("attackMode");
    static readonly AccessTools.FieldRef<AIPilotCombatModes, int>? EvadeMode = IntField("evadeMode");
    static readonly AccessTools.FieldRef<AIPilotCombatModes, Unit>? CombatTarget =
        AccessTools.Field(typeof(AIPilotCombatModes), "currentTarget") != null ? AccessTools.FieldRefAccess<AIPilotCombatModes, Unit>("currentTarget") : null;
    static readonly AccessTools.FieldRef<AIPilotCombatModes, bool>? TargetAccurate = TargetFlag("targetAccurate");
    static readonly AccessTools.FieldRef<AIPilotCombatModes, bool>? TargetObscured = TargetFlag("targetObscured");

    static AccessTools.FieldRef<AIPilotCombatModes, bool>? TargetFlag(string name) =>
        AccessTools.Field(typeof(AIPilotCombatModes), name) != null ? AccessTools.FieldRefAccess<AIPilotCombatModes, bool>(name) : null;
    static readonly int[] HighModes =
    {
        Mode("AttackMode", "FlyingToTarget"), Mode("AttackMode", "NoTarget"), Mode("AttackMode", "Bombing"),
        Mode("AttackMode", "GlideBombing"), Mode("AttackMode", "UsingMissiles"), Mode("AttackMode", "BreakOffAttack"),
    };
    static readonly int EvadeNone = Mode("EvadeMode", "None"), EvadeRadar = Mode("EvadeMode", "Radar");
    static readonly int UsingMissiles = Mode("AttackMode", "UsingMissiles");
    static bool reportedMissing;

    // AutopilotPlane.AutoAim's lowest height scale (AutopilotPlane.cs:46).
    const float LowestScale = 0.1f;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-high-strike", typeof(AIPilotCombatModes), "AssessHQTargets",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeAssessHQTargets)),
            postfix: AccessTools.Method(typeof(AiHighStrike), nameof(AfterAssessHQTargets))),
        new("ai-high-strike", typeof(CombatAI), nameof(CombatAI.AnalyzeTarget),
            postfix: AccessTools.Method(typeof(AiHighStrike), nameof(AfterAnalyzeTarget))),
        // Every AI aircraft's steering, every physics step (AIPilotCombatModes.cs:1251-1262 and the other states' AutoAim calls).
        new("ai-high-strike", typeof(AutopilotPlane), nameof(AutopilotPlane.AutoAim),
            new[] { typeof(GlobalPosition), typeof(bool), typeof(bool), typeof(bool), typeof(float), typeof(float), typeof(bool), typeof(float), typeof(Vector3) },
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeAutoAim))),
        new("ai-high-strike", typeof(AIPilotCombatModes), "UseGlideBombs",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeUseGlideBombs))),
        // The one patch on UseBombs: AiBombExtend's run extension is its mode check's half.
        new("ai-high-strike", typeof(AIPilotCombatModes), "UseBombs",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeUseBombs))),
        new("ai-high-strike", typeof(AIPilotCombatModes), "UseMissiles",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeUseMissiles))),
        new("ai-high-strike", typeof(AIPilotCombatModes), "NoTarget",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeNoTarget))),
        new("ai-high-strike", typeof(CombatAI), nameof(CombatAI.LookForMissileTargets),
            postfix: AccessTools.Method(typeof(AiHighStrike), nameof(AfterLookForMissileTargets))),
        // Stock queues neighbouring targets in a salvo. Recheck their own floor at the actual mount release.
        new("ai-high-strike", typeof(WeaponStation), nameof(WeaponStation.LaunchMount),
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeLaunchMount))),
    };

    /// <summary>Per aircraft (<see cref="CenturionSystems.Strike"/>): the cruise height, refreshed once a second, and the climb hold's racetrack.</summary>
    internal sealed class Flight
    {
        internal float MassKg, CruiseM, CruiseAt = float.NegativeInfinity;
        internal bool Holding;
        internal int Direction;
        // The target position the hold circles, and where the hold began: the track lies on the side the bomber came from.
        internal GlobalPosition Anchor, From;
        internal float StandoffM = HoldFloorM, StandoffAt = float.NegativeInfinity;
        internal float ThreatStandoffM;
        internal float ClimbCoverageAt = float.NegativeInfinity;
        internal bool ClimbCovered;
        // Flying away from a missile target too near to line up on (MissileExtend).
        internal Unit? ExtendTarget;
        internal bool Extending;
        // Its own missiles, from Unit.RegisterMissile (Missile.cs:798) until they hit, miss or are shot down.
        internal readonly List<Missile> Missiles = new();
#if CENTURION_DEV
        internal string LastReleaseHold = AircraftReadout.NoText;
        internal PersistentID LockedTarget;
        internal string LockedTargetName = AircraftReadout.NoText, LastLockRelease = AircraftReadout.NoText;
#endif

        internal int MissilesInFlight()
        {
            Missiles.RemoveAll(missile => missile == null || missile.disabled);
            return Missiles.Count;
        }
    }

    static AccessTools.FieldRef<AIPilotCombatModes, int>? IntField(string name)
    {
        try { return AccessTools.FieldRefAccess<AIPilotCombatModes, int>(name); }
        catch (Exception) { return null; }
    }

    static int Mode(string enumName, string name)
    {
        Type? type = AccessTools.Inner(typeof(AIPilotCombatModes), enumName);
        return type != null && Enum.IsDefined(type, name) ? Convert.ToInt32(Enum.Parse(type, name)) : int.MinValue;
    }

    /// <summary>Bombs, glide bombs and missiles left: the Tusko-B and AShM-300 presets carry no bombs and fly the profile too.</summary>
    internal static int StrikeRounds(Aircraft aircraft)
    {
        int rounds = 0;
        foreach (WeaponStation station in aircraft.weaponStations)
            if (station != null && station.Ammo > 0 && station.WeaponInfo != null
                && (station.WeaponInfo.bomb || station.WeaponInfo.glideBomb || station.WeaponInfo.missile))
                rounds += station.Ammo;
        return rounds;
    }

    static bool HasInboundRound(Flight flight, Unit target, bool missiles) =>
        flight.Missiles.Count != 0 && flight.Missiles.Exists(round => round != null && !round.disabled
            && round.targetID == target.persistentID && round.GetWeaponInfo() is { } info
            && (missiles ? info.missile && !info.glideBomb && !info.bomb : info.glideBomb || info.bomb));

    static void AfterAnalyzeTarget(Unit analyzer, TrackingInfo trackingInfo, ref OpportunityThreat __result)
    {
        if (__result.opportunity <= 0f || analyzer is not Aircraft aircraft || aircraft.Player != null
            || CenturionSystems.Of(aircraft) is not { IsAwacs: false, Strike: { } flight } systems
            || !WingFlies(systems) || !trackingInfo.TryGetUnit(out Unit target) || !HasInboundRound(flight, target, missiles: true))
            return;

        // Stock can score a target as viable while it has exactly the requested number of missiles inbound.
        __result = new OpportunityThreat(0f, __result.threat);
    }

    static bool BeforeAssessHQTargets(Aircraft ___aircraft, Unit? ___currentTarget, ref WeaponInfo? ___currentWeaponInfo,
        ref TrackingInfo? ___currentTargetTracking, ref bool ___allowTargetAssessment, out Unit? __state)
    {
        __state = ___currentTarget;
        if (___aircraft.Player != null || CenturionSystems.Of(___aircraft) is not { IsAwacs: false } systems) return true;
        if (!WingFlies(systems))
        {
            if (systems.Strike is { } stock) ReportLock(___aircraft, stock, null, "wing stage lost");
            return true;
        }
        if (ReferenceEquals(___currentTarget, null)) return true;

        Flight flight = CurrentFlight(systems);
        WeaponStation selected = ___aircraft.weaponManager.currentWeaponStation;
        // WeaponManager reads the live target list for the life of the salvo. Leave it alone until the last rack fires.
        if (selected != null && selected.SalvoInProgress) return true;
        string? reason = ReleaseTargetLock(___aircraft, flight, ___currentTarget, selected, out WeaponStation? replacement);
        if (reason == null)
        {
            if (replacement != selected)
            {
                ___aircraft.weaponManager.currentWeaponStation = replacement;
                ___currentWeaponInfo = replacement!.WeaponInfo;
            }
            ___currentTargetTracking = ___aircraft.NetworkHQ.GetTrackingData(___currentTarget!.persistentID);
            ReportLock(___aircraft, flight, ___currentTarget, null);
            return false;
        }

        ReportLock(___aircraft, flight, null, reason);
        // Bombing can close stock's assessment gate. Open it when the assignment is no longer usable.
        ___allowTargetAssessment = true;
        return true;
    }

    static string? ReleaseTargetLock(Aircraft aircraft, Flight flight, Unit target, WeaponStation? selected,
        out WeaponStation? replacement)
    {
        replacement = null;
        if (target == null || target.disabled) return "target destroyed";
        FactionHQ hq = aircraft.NetworkHQ;
        if (target.NetworkHQ == null || target.NetworkHQ == hq) return "target no longer hostile";
        if (hq == null || !hq.TryGetKnownPosition(target, out GlobalPosition known)
            || !hq.IsTargetPositionAccurate(target, 1000f) || hq.GetTrackingData(target.persistentID) is not { } track)
            return "track lost";
        if (HasInboundRound(flight, target, missiles: true)) return "salvo away";

        float range = (known - aircraft.GlobalPosition()).magnitude;
        bool armed = false, saturated = false;
        foreach (WeaponStation station in aircraft.weaponStations)
        {
            if (station == null || station.Cargo || station.Ammo <= 0 || station.WeaponInfo is not { } weapon
                || !weapon.bomb && !weapon.glideBomb && !weapon.missile)
                continue;
            armed = true;
            if (track.missileAttacks > weapon.CalcAttacksNeeded(target))
            {
                saturated = true;
                // TargetIDChanged also counts guided bombs as inbound. A bomb pass keeps its assignment
                // until the bomb hits or misses, so its own glide bomb does not trigger the missile handoff.
                if (station == selected && (weapon.bomb || weapon.glideBomb) && HasInboundRound(flight, target, missiles: false))
                {
                    replacement = station;
                    return null;
                }
            }
            // Use the same broad search range as ChooseHQTarget. A climb, turn or temporary line-of-sight issue
            // delays the attack without invalidating the assignment.
            if (CombatAI.AnalyzeTarget(station, aircraft, track, 0f, range, 100f).opportunity <= 0f) continue;
            if (station == selected)
            {
                replacement = station;
                return null;
            }
            replacement ??= station;
        }
        if (replacement != null) return null;
        if (!armed) return "strike racks empty";
        return saturated ? "target saturated" : "target unsuitable for remaining weapons";
    }

    static void AfterAssessHQTargets(Aircraft ___aircraft, Unit? ___currentTarget, Unit? __state)
    {
        if (___currentTarget == null || ___currentTarget == __state || ___aircraft.Player != null
            || CenturionSystems.Of(___aircraft) is not { IsAwacs: false } systems || !WingFlies(systems))
            return;
        ReportLock(___aircraft, CurrentFlight(systems), ___currentTarget, null);
    }

    [System.Diagnostics.Conditional("CENTURION_DEV")]
    static void ReportLock(Aircraft aircraft, Flight flight, Unit? target, string? release)
    {
#if CENTURION_DEV
        PersistentID id = target != null ? target.persistentID : default;
        if (id == flight.LockedTarget) return;
        SortieLog.TargetLock(aircraft, id, flight.LockedTarget, release);
        flight.LockedTarget = id;
        flight.LockedTargetName = target == null ? AircraftReadout.NoText
            : string.IsNullOrEmpty(target.UniqueName) ? target.definition.unitName : target.UniqueName;
        if (release != null) flight.LastLockRelease = release;
#endif
    }

#if CENTURION_DEV
    /// <summary>For the AI readout: the strike AI's own missiles in flight, 0 before its first high-profile step.</summary>
    internal static int MissilesInFlight(Aircraft aircraft) => CenturionSystems.Of(aircraft)?.Strike?.MissilesInFlight() ?? 0;

    internal static void ReadIngress(Aircraft aircraft, AIPilotCombatModes combat, Dictionary<string, object> state)
    {
        if (CenturionSystems.Of(aircraft)?.Strike is not { } flight) return;
        float? homeRangeM = TargetHomeRangeM(aircraft, CombatTarget?.Invoke(combat));
        state["ai_target_home_range_m"] = homeRangeM ?? -1f;
        state["ai_ingress_m"] = IngressHeight(flight, homeRangeM, HasBombSelected(aircraft));
        state["ai_last_release_hold"] = flight.LastReleaseHold;
        state["ai_missile_launch_rule"] = !AiSamLoadout.WasRestricted(aircraft) ? "height (unrestricted draw)"
            : AllowClimbLaunch(aircraft, flight) ? "climb (reachable long-range SAM)" : "height (no reachable long-range SAM)";
        state["ai_locked_target"] = flight.LockedTargetName;
        state["ai_last_lock_release"] = flight.LastLockRelease;
    }
#endif

    /// <summary>The level angle from the nose's heading to a point: a level bomber at height sees its target 30 deg or more below the nose.</summary>
    internal static float LevelAngle(Aircraft aircraft, Vector3 toTarget)
    {
        Vector3 forward = aircraft.transform.forward;
        forward.y = 0f;
        toTarget.y = 0f;
        return Vector3.Angle(forward, toTarget);
    }

    /// <summary>
    /// The profile's one launch cone, for bombs, glide bombs and missiles alike: the weapon's minAlignment taken on the level
    /// bearing. Stock measures it from the nose (targetAngle, AIPilotCombatModes.cs:500), and from the ingress height any
    /// target inside the release ranges lies further below the nose than the 30 deg every one of these weapons asks.
    /// </summary>
    static bool Aligned(Aircraft aircraft, Vector3 toTarget, WeaponInfo weapon) => LevelAngle(aircraft, toTarget) < weapon.targetRequirements.minAlignment;

    static float? HomeRangeM(Aircraft aircraft, GlobalPosition known)
    {
        Hangar? hangar = aircraft.NetworkspawningHangar;
        Airbase? home = hangar != null ? hangar.parentAirbase : null;
        return home != null ? AwacsOrbit.LevelDistance(home.center.GlobalPosition(), known) : (float?)null;
    }

    static float? TargetHomeRangeM(Aircraft aircraft, Unit? target) =>
        target != null && !target.disabled && aircraft.NetworkHQ != null
        && aircraft.NetworkHQ.TryGetKnownPosition(target, out GlobalPosition known) ? HomeRangeM(aircraft, known) : null;

    static bool HasBombSelected(Aircraft aircraft) =>
        aircraft.weaponManager.currentWeaponStation?.WeaponInfo is { } weapon && (weapon.bomb || weapon.glideBomb);

    static float IngressHeight(Flight flight, float? homeRangeM, bool bombs)
    {
        float cruiseEntryM = flight.CruiseM - CruiseEntryM;
        if (bombs) return AiStrikeIngress.Height(homeRangeM, cruiseEntryM);
        return homeRangeM <= MissileNearHomeM ? Mathf.Min(MissileNearIngressM, cruiseEntryM) : AiStrikeIngress.Height(null, cruiseEntryM);
    }

    static float BombCircleRadius(Flight flight, float? homeRangeM, float ingressM)
    {
        if (!homeRangeM.HasValue) return 0f;
        float turnM = ClimbSpeedMps * ClimbSpeedMps / (9.81f * Mathf.Tan(BombCircleBankDeg * Mathf.Deg2Rad));
        float slantM = (ingressM + 0.03f * ClimbSpeedMps * ClimbSpeedMps) / GlideReleaseRatio;
        float levelM = Mathf.Sqrt(Mathf.Max(0f, slantM * slantM - ingressM * ingressM));
        float radiusM = Mathf.Max(BombCircleMinM, levelM + turnM + BombCircleMarginM);
        // Leave an approach leg of up to one quarter-turn arc from home to the circle.
        // At 20 nmi a single turn radius sent the bomber out on the racetrack, and it released at cruise height.
        float approachM = Mathf.PI * 0.5f * turnM;
        return homeRangeM <= radiusM + approachM && flight.ThreatStandoffM <= radiusM ? radiusM : 0f;
    }

    /// <summary>Stock's salvo on the current target and its neighbours (AIPilotCombatModes.cs:904-917, 561-568); true if it fired.</summary>
    static bool Release(Aircraft aircraft, Pilot pilot, Unit target)
    {
        WeaponManager weapons = aircraft.weaponManager;
        List<Unit> targets = weapons.GetTargetList();
        targets.Clear();
        int count = CombatAI.LookForMissileTargets(aircraft, target, weapons.currentWeaponStation, targets);
        weapons.TargetListChanged();
        if (count > 0)
        {
            pilot.Fire();
        }

        return count > 0;
    }

    /// <summary>
    /// The combat AI's terrain following, as stock tunes it for jets, flew the AI Centurion into the sea after takeoff. Two
    /// stock rules in AutopilotPlane.AutoAim do it, and for a Centurion in AIPilotCombatModes this prefix undoes both, unless
    /// the high profile (<see cref="Steer"/>) flies it:
    /// - The height is scaled by Lerp(0.1, 1, (airspeed - 0.9 x landingSpeed) / landingSpeed) (AutopilotPlane.cs:46), full only
    ///   at 1.9 x landingSpeed. Jets cruise past that; at the Centurion's landingSpeed 105 it takes 200 m/s, so after takeoff
    ///   (90 to 120 m/s) the combat AI's 190 m command became 14 to 60 m. The prefix divides the height by the same scale.
    /// - Unless aimVelocity is set, the nose, not the flight path, points at the waypoint (AutopilotPlane.cs:34), and the
    ///   combat AI sets it only in break-off, retreat and radar evasion (AIPilotCombatModes.cs:447, 487, 1177). The waypoint
    ///   sits about 2 km ahead (TerrainWarningSystem.cs:49), so a 100 m rise is 2.5 degrees; the Centurion flies 5 degrees of
    ///   alpha at those speeds, so with its nose on the waypoint it sank at 2 degrees. The prefix aims the flight path.
    /// The landing states keep both stock rules, so the approach, which landingSpeed also sets, is untouched; the takeoff and
    /// AWACS states do not follow terrain.
    /// </summary>
    static void BeforeAutoAim(AutopilotPlane __instance, ref GlobalPosition destination, ref bool aimVelocity, ref float bankAllowed,
        ref bool followTerrain, ref float altitudeHold)
    {
        if (CenturionSystems.Of(__instance.aircraft) is not { } systems) return;
        Aircraft aircraft = systems.Aircraft;
        if (aircraft.pilots.Length == 0 || aircraft.pilots[0].currentState is not AIPilotCombatModes combat) return;
        if (Steer(systems, combat, ref destination, ref aimVelocity, ref followTerrain, ref bankAllowed, ref altitudeHold)) return;
        if (!followTerrain) return;

        // AirspeedChecker.GetAirspeed (Autopilot.cs:109-117): forward airspeed against the wind, recomputed each call.
        float airspeed = Vector3.Dot(aircraft.cockpit.xform.forward,
            aircraft.rb.velocity - NetworkSceneSingleton<LevelInfo>.i.GetWind(aircraft.GlobalPosition()));
        float landingSpeed = aircraft.GetAircraftParameters().landingSpeed;
        altitudeHold /= Mathf.Lerp(LowestScale, 1f, (airspeed - landingSpeed * 0.9f) / landingSpeed);
        aimVelocity = true;
    }

    internal static float CruiseHeight(float massKg) => Mathf.Min(CruiseAtMtowM + (MtowKg - massKg) * CruisePerKgM, CruiseCapM);

    /// <summary>
    /// The aircraft's <see cref="Flight"/> with its wing and its cruise height, refreshed once a second, for <see cref="Steer"/>
    /// ahead of its early returns and for the release floor alike: with the height set only by the profile above
    /// <see cref="NearGroundM"/>, a bomber that never climbed that high had none, and the floor let it release at any height
    /// (run 20261016-225312: 16 GBM-500LR from 2,542 and 3,390 ft).
    /// </summary>
    static Flight CurrentFlight(CenturionSystems systems)
    {
        if (systems.Strike is not { } flight)
        {
            // Made on the first high-profile step or launch check, before any launch in combat.
            systems.Strike = flight = new Flight();
            systems.Aircraft.onRegisterMissile += flight.Missiles.Add;
        }
        float now = Time.timeSinceLevelLoad;
        if (now >= flight.CruiseAt)
        {
            flight.CruiseAt = now + RefreshS;
            flight.MassKg = systems.Aircraft.GetMass();
            flight.CruiseM = CruiseHeight(flight.MassKg);
        }
        return flight;
    }

    /// <summary>The wing the profile needs: none, or one locked retracted by a lost stage (TelescopeController.FixedUpdate), can't fly it.</summary>
    static bool WingFlies(CenturionSystems systems) => systems.Telescope != null && !systems.Telescope.Locked;

    /// <summary>
    /// For a Centurion with bombs in a transit or attack mode, replaces AutoAim's destination with the high profile's and
    /// returns true; false leaves the stock command to <see cref="BeforeAutoAim"/>'s height hold, which below
    /// <see cref="NearGroundM"/> it has set to follow the terrain <see cref="ClimbOutStepM"/> above the bomber's height, on the
    /// climb hold's bearing.
    /// </summary>
    static bool Steer(CenturionSystems systems, AIPilotCombatModes combat, ref GlobalPosition destination, ref bool aimVelocity,
        ref bool followTerrain, ref float bankAllowed, ref float altitudeHold)
    {
        Aircraft aircraft = systems.Aircraft;
        if (AttackMode == null || EvadeMode == null)
        {
            if (!reportedMissing)
            {
                reportedMissing = true;
                CenturionPlugin.Log.Warning("ai-high-strike: AIPilotCombatModes.attackMode or evadeMode unreadable; the AI bombers fly stock");
            }
            return false;
        }
        if (Array.IndexOf(HighModes, AttackMode(combat)) < 0 || StrikeRounds(aircraft) == 0) return false;
        int evade = EvadeMode(combat);
        bool evading = evade != EvadeNone && AiCramHold.Covered(aircraft, aircraft.GetMissileWarningSystem().knownMissiles) <= 0;
        // "Dodge but hold height" (owner, docs/DECISIONS.md, 2026-10-17): from a radar missile the laser can't take it keeps
        // stock's evasion bearing (EvadeModeRadar's destination, AIPilotCombatModes.cs:1188-1190) and jammer (:1179-1187) but
        // flies this profile's height and bank, not stock's 10 m over the terrain (:1162, clamped to maxRadius at :1261) or
        // its pull-up inside 2 s of impact (:1191-1195). Stock's dive took every climbing bomber in the end-game Escalation
        // back down among the IR SAMs and guns (run 20261016-225312).
        bool dodging = evading && evade == EvadeRadar;

        Flight flight = CurrentFlight(systems);
        if (!WingFlies(systems)) return false;
        GlobalPosition position = aircraft.GlobalPosition();
        Vector3 velocity = aircraft.CockpitRB().velocity;
        if (aircraft.radarAlt < NearGroundM)
        {
            // Stock terrain following, aimed a step above the current height so it keeps climbing over rising ground, on the
            // climb hold's bearing at the profile's bank. Stock's bearing is the target's (AIPilotCombatModes.cs:293, 573-576):
            // in the end-game Escalation, its targets 9 to 16 nm from the runway, each bomber's 60 to 100 s climb-out closed on
            // the target's radar SAMs, whose launches dove it back to the terrain from 640 to 920 m (run 20261016-225312).
            // The 180 deg turn onto the hold at 20 deg climbs as straight flight does (tools/fm/ai_climb_out.py).
            followTerrain = true;
            altitudeHold = Mathf.Max(altitudeHold, aircraft.radarAlt + ClimbOutStepM);
            GlobalPosition track = destination;
            if (dodging || ClimbHoldAim(aircraft, combat, flight, position, position.y, ref track))
            {
                // Following the terrain, AutoAim takes only the bearing from the destination (AutopilotPlane.cs:48-53).
                track.y = position.y;
                destination = track;
                bankAllowed = Mathf.Min(bankAllowed, BankDeg / AutoAimBankScale(aircraft, position, velocity, velocity - aircraft.GetWindVelocity(), track));
            }
            return false;
        }

        float speed = (velocity - aircraft.GetWindVelocity()).magnitude;
        bool retracted = systems.Telescope!.Command < 0.5f;
        float height = retracted ? ReextendHeight(position.y, speed, out float throttle)
            : CommandHeight(position.y, speed, flight.CruiseM, out throttle);

        float? homeRangeM = HasBombSelected(aircraft) ? TargetHomeRangeM(aircraft, CombatTarget?.Invoke(combat)) : null;
        float bombIngressM = IngressHeight(flight, homeRangeM, true);
        if (!evading && bombIngressM < IngressHeight(flight, null, true))
        {
            float runHeight = bombIngressM + BombRunHeightMarginM;
            if (height > runHeight)
            {
                height = runHeight;
                if (!retracted)
                    throttle = Mathf.Clamp(0.6f + 0.1f * (ClimbSpeed(position.y) - speed), CenturionAwacsState.ThrottleFloor, 1f);
            }
        }

        Vector3 ahead = destination - position;
        ahead.y = 0f;
        if (!dodging) MissileExtend(aircraft, combat, flight, position, ref ahead);
        if (ahead.sqrMagnitude < 1f) ahead = new Vector3(aircraft.transform.forward.x, 0f, aircraft.transform.forward.z);
        GlobalPosition aim = position + ahead.normalized * LookaheadM;
        aim.y = height;
        if (!dodging) ClimbHoldAim(aircraft, combat, flight, position, height, ref aim);

        destination = LevelTurnAim(aircraft, position, velocity, aim);
        aimVelocity = true;
        followTerrain = false;
        float bank = BankDeg;
        if (!evading && position.y < BombCircleBankCeilingM && HasBombSelected(aircraft))
        {
            if (BombCircleRadius(flight, homeRangeM, bombIngressM) > 0f)
                bank = BombCircleBankDeg;
        }
        bankAllowed = Mathf.Min(bankAllowed, bank / AutoAimBankScale(aircraft, position, velocity, velocity - aircraft.GetWindVelocity(), destination));
        // Dodging, the profile's throttle, not stock's full throttle (:1196): at the cruise height the command can't take the
        // excess as climb, so full throttle runs the speed up into the extended wing's drag rise.
        if (!evading || dodging) aircraft.GetInputs().throttle = throttle;
        return true;
    }

    /// <summary>
    /// The aim for a level turn. AutoAim pitches by the angle from the velocity to its waypoint about the wings' axis
    /// (AutopilotPlane.cs:115) and banks toward the waypoint's side within bankAllowed (:105-108). A waypoint far to the side,
    /// as the racetrack's 8 km lookahead is on its 10 km turn (23 deg off the velocity), reaches the pitch axis through the
    /// bank: with the bank capped the bomber pulled itself into climbing turns past its height command at full throttle,
    /// bleeding from 201 to 167 m/s with the command 200 m below it (run 20261016-175733, t=968 to 1148), then sank and
    /// overspeeded past the span schedule's retract. So the aim sits at most <see cref="AimTurnDeg"/> off the velocity's
    /// heading and <see cref="LookaheadM"/> out at the command's angle, less <see cref="PullCancel"/> of the side angle times
    /// tan(bank) that AutoAim would read on the pitch axis (tools/fm/ai_high_strike.py).
    /// </summary>
    static GlobalPosition LevelTurnAim(Aircraft aircraft, GlobalPosition position, Vector3 velocity, GlobalPosition aim)
    {
        Vector3 level = new Vector3(velocity.x, 0f, velocity.z), to = aim - position;
        float rise = to.y;
        to.y = 0f;
        if (level.sqrMagnitude < 1f || to.sqrMagnitude < 1f) return aim;
        float turn = Mathf.Clamp(Vector3.SignedAngle(level, to, Vector3.up), -AimTurnDeg, AimTurnDeg);
        float bank = Mathf.Clamp(Vector3.SignedAngle(aircraft.transform.up, Vector3.up, aircraft.transform.forward), -45f, 45f);
        GlobalPosition turned = position + Quaternion.AngleAxis(turn, Vector3.up) * level.normalized * LookaheadM;
        turned.y = position.y + LookaheadM * (rise / to.magnitude - Mathf.Tan(PullCancel * turn * Mathf.Deg2Rad * Mathf.Tan(bank * Mathf.Deg2Rad)));
        return turned;
    }

    /// <summary>
    /// AutoAim's scaling of bankAllowed (AutopilotPlane.cs:96-99): by height, by 1.2 or, sinking faster than about 4 m/s, 0.5
    /// (its Mathf.Clamp has the bounds reversed), and by max((airspeed / cornerSpeed)^2, 0.45), the airspeed true along the
    /// nose (Autopilot.cs:108-117). It made <see cref="BankDeg"/> 15.9 deg level at 208 m/s and 6.6 deg sinking.
    /// </summary>
    static float AutoAimBankScale(Aircraft aircraft, GlobalPosition position, Vector3 velocity, Vector3 air, GlobalPosition aim)
    {
        float num3 = Mathf.Clamp01(Vector3.Dot(aircraft.transform.forward, air) / aircraft.GetAircraftParameters().cornerSpeed);
        float sink = ((aim - position).normalized.y - velocity.y) * 0.05f + 1f >= 1.2f ? 0.5f : 1.2f;
        return Mathf.Clamp(aircraft.radarAlt * 0.003f - 1f, 0.6f, 1.2f) * sink * Mathf.Max(num3 * num3, 0.45f);
    }

    /// <summary>Speed on pitch: the height 8 km ahead, and the throttle (CenturionAwacsState's climb and orbit laws).</summary>
    static float CommandHeight(float y, float speed, float cruise, out float throttle)
    {
        if (y >= cruise - CruiseEntryM)
        {
            // Slow above the cruise height, a 1,000 m dive lead at full throttle overshot from 187 to 218 m/s, the tail too weak
            // up there to pull out in time, and the schedule retracted the wing (run 20261016-111517, t=1140 to 1200).
            throttle = Mathf.Clamp(0.6f + 0.1f * (CruiseSpeedMps - speed), CenturionAwacsState.ThrottleFloor, 1f);
            return Mathf.Min(cruise, y + Mathf.Clamp(CenturionAwacsState.ClimbLeadPerMps * (speed - CruiseEnergyMps), -200f,
                CenturionAwacsState.ClimbLeadMaxM));
        }

        float climb = ClimbSpeed(y);
        throttle = Mathf.Clamp(1f - 0.1f * (speed - climb - CenturionAwacsState.ClimbOverspeedMps), CenturionAwacsState.ThrottleFloor, 1f);
        return Mathf.Min(cruise, y + Mathf.Clamp(CenturionAwacsState.ClimbLeadPerMps * (speed - climb), -200f, CenturionAwacsState.ClimbLeadMaxM));
    }

    static float ClimbSpeed(float y) =>
        Mathf.Min(ClimbEasMps * Mathf.Sqrt(LevelInfo.GetAirDensity(0f) / LevelInfo.GetAirDensity(y)), ClimbSpeedMps);

    /// <summary>Retracted: throttle back and pitch for a speed under the span schedule's extend limit.</summary>
    static float ReextendHeight(float y, float speed, out float throttle)
    {
        float target = ReextendEasMps * Mathf.Sqrt(LevelInfo.GetAirDensity(0f) / LevelInfo.GetAirDensity(y));
        throttle = Mathf.Clamp(0.6f + 0.1f * (target - speed), CenturionAwacsState.ThrottleFloor, 1f);
        return y + Mathf.Clamp(CenturionAwacsState.ClimbLeadPerMps * (speed - target), -500f, 1000f);
    }

    /// <summary>
    /// Below its ingress height (<see cref="AiStrikeIngress"/>), once within a racetrack's depth of
    /// the standoff from its target, the bomber climbs on <see cref="AwacsOrbit.Racetrack"/> round the target's position, on the
    /// side it came from, instead of pressing in. The hold latches: the track's end caps reach past the entry distance
    /// (<see cref="AwacsOrbit.CoverageStandoff"/>), so it ends only at the ingress height, when the target is gone, or when the target
    /// moves to one more than <see cref="HoldMoveM"/> from the anchor, which starts a new track from where the bomber is.
    /// </summary>
    static bool ClimbHoldAim(Aircraft aircraft, AIPilotCombatModes combat, Flight flight, GlobalPosition position, float height, ref GlobalPosition aim)
    {
        Unit? target = CombatTarget?.Invoke(combat);
        FactionHQ hq = aircraft.NetworkHQ;
        if (position.y >= IngressHeight(flight, null, false) || target == null || target.disabled || hq == null
            || !hq.TryGetKnownPosition(target, out GlobalPosition known))
        {
            flight.Holding = false;
            return false;
        }

        bool bombs = HasBombSelected(aircraft);
        float? homeRangeM = HomeRangeM(aircraft, known);
        float ingressM = IngressHeight(flight, homeRangeM, bombs);
        if (position.y >= ingressM)
        {
            flight.Holding = false;
            return false;
        }

        WeaponInfo? weapon = aircraft.weaponManager.currentWeaponStation?.WeaponInfo;
        if (!bombs && weapon != null && IsEarlyStrikeMissile(weapon) && AllowClimbLaunch(aircraft, flight)
            && TargetAccurate != null && TargetObscured != null
            && HasMissileSolution(weapon, TargetAccurate(combat), TargetObscured(combat), FastMath.Distance(position, known)))
        {
            // Turn to use the shot during the climb. Keep the standoff while it is masked or out of range.
            flight.Holding = false;
            return false;
        }

        if (flight.Holding && AwacsOrbit.LevelDistance(flight.Anchor, known) > HoldMoveM) flight.Holding = false;
        GlobalPosition anchor = flight.Holding ? flight.Anchor : known;
        float now = Time.timeSinceLevelLoad;
        if (now - flight.StandoffAt >= RefreshS)
        {
            // Escape distance from the target's known ground threats, which ring the target the hold faces (CombatAI.cs:73-88).
            flight.StandoffAt = now;
            flight.ThreatStandoffM = CombatAI.GetSafeStandoffDist(anchor, hq);
            flight.StandoffM = Mathf.Max(HoldFloorM, flight.ThreatStandoffM);
        }

        float circleM = bombs ? BombCircleRadius(flight, homeRangeM, ingressM) : 0f;
        if (circleM > 0f)
        {
            flight.Holding = false;
            if (position.y >= ingressM - BombTurnLeadM) return false;
            aim = AwacsOrbit.Circle(position, aircraft.transform.forward, known, circleM, height);
            return true;
        }

        if (!flight.Holding)
        {
            if (AwacsOrbit.LevelDistance(position, known) >= flight.StandoffM + 2f * AwacsOrbit.TurnRadiusM) return false;
            flight.Holding = true;
            flight.Anchor = anchor;
            flight.From = position;
            flight.Direction = 0;
        }

        aim = AwacsOrbit.Racetrack(position, aircraft.transform.forward, flight.Anchor, flight.From, flight.StandoffM, height,
            NetworkSceneSingleton<LevelInfo>.i.LoadedMapSettings.MapSize, ref flight.Direction);
        return true;
    }

    /// <summary>
    /// In UsingMissiles, a target nearer than <see cref="MissileExtendInM"/> and off the launch alignment (<see cref="BeforeUseMissiles"/>)
    /// latches a heading straight away from it until <see cref="MissileExtendOutM"/>, then turns back at it. Otherwise the
    /// heading is the target's known position: UseMissiles sets no destination for a weapon without muzzleVelocity
    /// (AIPilotCombatModes.cs:898-903), so after the HQ switches targets in the mode (AssessHQTargets, :401-421) stock's
    /// course still points at the last one FlyToTarget set (:293).
    /// </summary>
    static void MissileExtend(Aircraft aircraft, AIPilotCombatModes combat, Flight flight, GlobalPosition position, ref Vector3 ahead)
    {
        WeaponStation station = aircraft.weaponManager.currentWeaponStation;
        Unit? target = CombatTarget?.Invoke(combat);
        FactionHQ hq = aircraft.NetworkHQ;
        if (target != flight.ExtendTarget)
        {
            flight.ExtendTarget = target;
            flight.Extending = false;
        }
        if (AttackMode!(combat) != UsingMissiles || station == null || station.WeaponInfo == null || target == null || target.disabled
            || hq == null || !hq.TryGetKnownPosition(target, out GlobalPosition known))
        {
            flight.Extending = false;
            return;
        }

        Vector3 away = position - known;
        away.y = 0f;
        float distance = away.magnitude;
        if (!flight.Extending && distance < MissileExtendInM && !Aligned(aircraft, -away, station.WeaponInfo))
            flight.Extending = true;
        else if (flight.Extending && distance > MissileExtendOutM)
            flight.Extending = false;
        if (distance > 1f) ahead = flight.Extending ? away : -away;
    }

    /// <summary>
    /// Below its ingress height (<see cref="AiStrikeIngress"/>) a Centurion flying the high profile
    /// doesn't release. Stock releases unguided bombs whenever the vacuum fall time matches (AIPilotCombatModes.cs:646-652), at
    /// any height: a bomber that took a target 18.5 km away on its climb released 7 PAB-250 from 29,700 ft (run
    /// 20261016-212151, t=373 to 518). A locked wing falls back to stock steering and missile release.
    /// Bombs still obey their release floor.
    /// </summary>
    static bool BelowIngress(CenturionSystems systems, Unit? target, bool bombs)
    {
        Flight flight = CurrentFlight(systems);
        Aircraft aircraft = systems.Aircraft;
        float altitudeM = aircraft.GlobalPosition().y;
        return (bombs || WingFlies(systems)) && altitudeM < IngressHeight(flight, null, false)
            && altitudeM < IngressHeight(flight, TargetHomeRangeM(aircraft, target), bombs);
    }

    static bool BeforeLaunchMount(WeaponStation __instance, Unit owner, Unit? target)
    {
        if (owner is not Aircraft aircraft || aircraft.Player != null || !aircraft.LocalSim || target == null
            || __instance.WeaponInfo is not { } weapon || !weapon.bomb && !weapon.glideBomb
            || CenturionSystems.Of(aircraft) is not { } systems)
            return true;
        if (!BelowIngress(systems, target, bombs: true)) return true;
        NoteReleaseHold(systems, "salvo target ingress height");
        return false;
    }

    [System.Diagnostics.Conditional("CENTURION_DEV")]
    static void NoteReleaseHold(CenturionSystems systems, string gate)
    {
#if CENTURION_DEV
        if (systems.Strike is { } flight) flight.LastReleaseHold = gate;
#endif
    }

    /// <summary>
    /// Stock's unguided attack (AIPilotCombatModes.cs:589-670) for a Centurion: its mode check (checkMode true) may extend the
    /// run past the target instead (<see cref="AiBombExtend.TryExtend"/>), and its release (checkMode false) is skipped below
    /// the ingress height, where <see cref="Steer"/> flies it.
    /// </summary>
    static bool BeforeUseBombs(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft, Unit ___currentTarget,
        WeaponInfo ___currentWeaponInfo, Vector3 ___targetVector, ref float ___breakOffTimer, ref bool ___allowTargetAssessment)
    {
        if (CenturionSystems.Of(___aircraft) is not { } systems) return true;
        if (checkMode)
        {
            // On a lowered approach the target can still be ahead and closing inside the extension radius.
            // Keep the first intercept instead of switching to the 15 second outbound leg before alignment.
            Flight flight = CurrentFlight(systems);
            Vector3 velocity = ___aircraft.rb.velocity;
            bool closing = velocity.x * ___targetVector.x + velocity.z * ___targetVector.z > 0f;
            if (closing && WingFlies(systems)
                && IngressHeight(flight, TargetHomeRangeM(___aircraft, ___currentTarget), true) < IngressHeight(flight, null, true))
                return true;
            return !AiBombExtend.TryExtend(__instance, ___aircraft, ___currentTarget, ___currentWeaponInfo, ___targetVector, ref ___breakOffTimer, ref ___allowTargetAssessment);
        }
        bool belowIngress = BelowIngress(systems, ___currentTarget, bombs: true);
        // Stock owns the fall solution and release, so dev telemetry identifies the handoff.
        NoteReleaseHold(systems, belowIngress ? "ingress height" : "stock bomb solution");
        return !belowIngress;
    }

    /// <summary>
    /// Stock's missile launch (AIPilotCombatModes.cs:893-927) for a Centurion, skipped below its ingress height, where
    /// <see cref="Steer"/> flies it; the mode checks (:869-891) still run. Stock enters the mode at any height once the target
    /// is inside maxRange (:305), and the HQ's target can be anywhere it knows of (CombatAI.cs:261-269, 285): the AShM-300's
    /// 250 km and over-the-horizon flight (info_AShM1.asset) put most of a theatre in reach of the runway, so stock launches
    /// in the climb-out, slow and low, and with the Tusko-B's 60 km (AShM3_info.asset) once the target clears the horizon.
    /// From height it launches as stock does (:904-917) in the profile's launch cone (<see cref="Aligned"/>): from 16 km any
    /// target nearer than about 28 km lies further below the nose than stock's 30 deg. Stock's break-off inside twice minRange
    /// (:918-927) is left out: from the ingress height the slant range is never that short.
    /// A restricted strike missile draw may release below ingress if a live launcher covers the climb above home.
    /// </summary>
    static bool BeforeUseMissiles(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft, Pilot ___pilot, Unit ___currentTarget,
        WeaponInfo ___currentWeaponInfo, Vector3 ___targetVector, float ___targetDist, bool ___targetAccurate,
        bool ___targetObscured, ref float ___lastFiredTime)
    {
        if (checkMode || CenturionSystems.Of(___aircraft) is not { } systems) return true;
        Flight flight = CurrentFlight(systems);
        bool belowIngress = BelowIngress(systems, ___currentTarget, bombs: false);
        bool earlyStrike = belowIngress && ___currentWeaponInfo != null && IsEarlyStrikeMissile(___currentWeaponInfo)
            && AllowClimbLaunch(___aircraft, flight);
        if (belowIngress && !earlyStrike)
        {
            NoteReleaseHold(systems, "ingress height");
            return false;
        }
        if (!WingFlies(systems) || ___currentWeaponInfo == null || ___currentTarget == null
            || ___currentTarget.disabled || ___currentWeaponInfo.muzzleVelocity > 0f)
        {
            return true;
        }

        float now = Time.timeSinceLevelLoad;
        // The salvo reads the live target list until the final round. Its first round can be aimed at a neighbour.
        if (___aircraft.weaponManager.currentWeaponStation?.SalvoInProgress == true) NoteReleaseHold(systems, "salvo in progress");
        else if (HasInboundRound(flight, ___currentTarget, missiles: true)) NoteReleaseHold(systems, "salvo in flight");
        else if (earlyStrike && (!HasMissileSolution(___currentWeaponInfo, ___targetAccurate, ___targetObscured, ___targetDist)
            || ___aircraft.speed < ___currentWeaponInfo.targetRequirements.minOwnerSpeed)) NoteReleaseHold(systems, "missile launch solution");
        else if (!(___targetDist < ___currentWeaponInfo.targetRequirements.maxRange)) NoteReleaseHold(systems, "missile range");
        else if (!(now - ___lastFiredTime > 2.5f)) NoteReleaseHold(systems, "release cooldown");
        else if (!Aligned(___aircraft, ___targetVector, ___currentWeaponInfo)) NoteReleaseHold(systems, "level alignment");
        else if (!Release(___aircraft, ___pilot, ___currentTarget)) NoteReleaseHold(systems, "salvo targets");
        else
        {
            NoteReleaseHold(systems, "missile released");
            ___lastFiredTime = now;
        }

        return false;
    }

    static bool AllowClimbLaunch(Aircraft aircraft, Flight flight)
    {
        if (!AiSamLoadout.WasRestricted(aircraft) || aircraft.NetworkHQ == null) return false;
        Hangar? hangar = aircraft.NetworkspawningHangar;
        Airbase? home = hangar != null ? hangar.parentAirbase : null;
        if (home == null) return false;
        float now = Time.timeSinceLevelLoad;
        if (now - flight.ClimbCoverageAt >= RefreshS)
        {
            flight.ClimbCoverageAt = now;
            flight.ClimbCovered = AiSamLoadout.LauncherReachesClimb(aircraft.NetworkHQ, home.center.GlobalPosition());
        }
        return flight.ClimbCovered;
    }

    static bool IsEarlyStrikeMissile(WeaponInfo weapon) =>
        AiMissileLaunch.IsStrikeMissile(weapon.missile, weapon.bomb || weapon.glideBomb, weapon.muzzleVelocity,
            weapon.effectiveness.antiSurface, weapon.effectiveness.antiRadar);

    static bool HasMissileSolution(WeaponInfo weapon, bool accurate, bool obscured, float distance) =>
        AiMissileLaunch.HasSolution(accurate, obscured, weapon.overHorizon, distance,
            weapon.targetRequirements.minRange, weapon.targetRequirements.maxRange);

    /// <summary>
    /// Stock NoTarget hands any aircraft to the landing state after 15 s without a target (AIPilotCombatModes.cs:362-369);
    /// once an HQ target has been chosen (EnemyContact, :417) nothing resets that clock (:371-375). A missile in flight counts
    /// against its target (Missile.cs:1188) and a target with more attacks than it needs scores 0 (CombatAI.cs:112), so
    /// after salvoes at every target it knows, a missile bomber finds none for 15 s and lands with rounds aboard, which go
    /// back to stock (Aircraft.ReturnToInventory, Aircraft.cs:2229-2241), and the HQ sends another out: the take off,
    /// launch, land loop the owner reported (2026-10-18). While a Centurion has rounds left and its own missiles are still
    /// flying, the clock stays at zero, so it stays up, on the stock course home at the profile's height, until they land;
    /// a target that survives scores again and it attacks again. Low fuel still sends it home (:351-354), and once it has
    /// fired everything stock lands it to rearm.
    /// </summary>
    static void BeforeNoTarget(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft, ref float ___timeWithoutTarget)
    {
        if (!checkMode || CenturionSystems.Of(___aircraft)?.Strike is not { } flight || StrikeRounds(___aircraft) == 0)
        {
            return;
        }

        int inFlight = flight.MissilesInFlight();
        if (inFlight == 0) return;
        ___timeWithoutTarget = 0f;
        if (CenturionPlugin.Log.StageDue("ai-missile-wait"))
        {
            CenturionPlugin.Log.StageLine("ai-missile-wait", Invariant(
                $"{___aircraft.name} {___aircraft.persistentID}: no target, {inFlight} own missile(s) in flight: staying up, at {___aircraft.GlobalPosition().y:0} m"));
        }
    }

    /// <summary>
    /// A Centurion's glide release: stock's check (AIPilotCombatModes.cs:546-570) with the release held until
    /// <see cref="GlideReleaseRatio"/>, in the profile's launch cone (<see cref="Aligned"/>): a level bomber at 16.3 km sees the
    /// target 33.8 deg below its nose at the 0.6 point, past the PAB-250LR's and GBM-500LR's 30 deg
    /// (info_bomb_250_glide.asset), so stock would never release.
    /// </summary>
    static bool BeforeUseGlideBombs(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft, Pilot ___pilot, Unit ___currentTarget, WeaponInfo ___currentWeaponInfo,
        Vector3 ___targetVector, float ___targetDist, float ___targetAngle, bool ___targetObscured, ControlInputs ___controlInputs,
        ref float ___aimEffort, ref bool ___followTerrain, ref float ___bombLastDropped, ref float ___lastFiredTime)
    {
        if (!checkMode || CenturionSystems.Of(___aircraft) is not { } systems || ___currentTarget == null || ___currentTarget.disabled || ___currentWeaponInfo == null
            || ___targetDist < ___currentWeaponInfo.targetRequirements.minRange)
        {
            return true;
        }

        ___followTerrain = ___targetAngle > 20f;
        ___controlInputs.throttle = 1f;
        ___aimEffort = 0.5f;
        float above = (___aircraft.GlobalPosition() - ___currentTarget.GlobalPosition()).y;
        float now = Time.timeSinceLevelLoad;
        if (BelowIngress(systems, ___currentTarget, bombs: true)) NoteReleaseHold(systems, "ingress height");
        else if (!((above + ___aircraft.speed * ___aircraft.speed * 0.03f) / ___targetDist >= GlideReleaseRatio)) NoteReleaseHold(systems, "glide ratio");
        else if (___targetObscured) NoteReleaseHold(systems, "line of sight");
        else if (!(now - ___bombLastDropped > 5f)) NoteReleaseHold(systems, "release cooldown");
        else if (!Aligned(___aircraft, ___targetVector, ___currentWeaponInfo)) NoteReleaseHold(systems, "level alignment");
        else if (!Release(___aircraft, ___pilot, ___currentTarget)) NoteReleaseHold(systems, "salvo targets");
        else
        {
            ___bombLastDropped = now;
            ___lastFiredTime = now;
        }

        return false;
    }

    /// <summary>
    /// A glide release lists, beside the target, the units within 1 km of it that are inside the weapon's 10 km maxRange of
    /// the aircraft and its nose cone (CombatAI.cs:191); from a 25 km release at height that leaves the target alone. For a
    /// Centurion's glide bombs this adds the neighbours stock dropped for that range or that cone, in the profile's launch
    /// cone (<see cref="Aligned"/>) and by stock's other tests, so one release saturates.
    /// </summary>
    static void AfterLookForMissileTargets(Aircraft aircraft, Unit currentTarget, WeaponStation weaponStation, List<Unit> outTargets, ref int __result)
    {
        if (__result <= 0 || __result >= MaxGlideTargets || CenturionSystems.Of(aircraft) == null || weaponStation == null || weaponStation.WeaponInfo == null
            || !weaponStation.WeaponInfo.glideBomb || aircraft.NetworkHQ == null || !aircraft.NetworkHQ.TryGetKnownPosition(currentTarget, out GlobalPosition known))
        {
            return;
        }

        WeaponInfo weapon = weaponStation.WeaponInfo;
        foreach (Unit item in BattlefieldGrid.GetUnitsInRangeEnumerable(known, NeighbourM))
        {
            if (item == currentTarget || item.NetworkHQ == null || item.NetworkHQ == aircraft.NetworkHQ || outTargets.Contains(item)) continue;
            TrackingInfo tracking = aircraft.NetworkHQ.GetTrackingData(item.persistentID);
            // AnalyzeTarget as LookForBombingTargets calls it, at 1 km and 100 x maxRange (CombatAI.cs:358), since at its true
            // range it scores 0 past maxRange (CombatAI.cs:163).
            if (tracking == null || !Aligned(aircraft, item.transform.position - aircraft.transform.position, weapon)
                || !FastMath.InRange(tracking.lastKnownPosition, item.GlobalPosition(), 20f)
                || (weapon.targetRequirements.lineOfSight && !item.LineOfSight(aircraft.transform.position, 1000f))
                || CombatAI.AnalyzeTarget(weaponStation, aircraft, tracking, 0f, 1000f, 100f).opportunity <= 0f)
            {
                continue;
            }

            int attacks = Mathf.Max(Mathf.FloorToInt(weapon.CalcAttacksNeeded(item)), 1) - tracking.missileAttacks;
            if (attacks <= 0) continue;
            for (int i = 0; i < attacks; i++) outTargets.Add(item);
            if (++__result >= MaxGlideTargets) break;
        }
    }
}
