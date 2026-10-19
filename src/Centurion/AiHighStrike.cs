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
/// <see cref="Steer"/>, called from <see cref="CombatHeightHold"/>'s AutoAim prefix, keeps each stock mode's bearing and
/// replaces its height in transit and attack (FlyingToTarget, NoTarget, Bombing, GlideBombing, UsingMissiles, BreakOffAttack):
/// - Below <see cref="NearGroundM"/> it climbs out on the stock terrain following, aimed a step above its height, so it
///   clears the hills it skimmed at 22 to 57 m and lost a wing stage to (run 20261016-043908, t=135 to 149), on the climb
///   hold's bearing (below) instead of stock's at the target.
/// - The cruise height, by mass, is 500 m under where its climb and turns still hold their speed and height, at most
///   57,000 ft (<see cref="CruiseAtMtowM"/>; tools/fm/centurion_cruise_band.py). It turns level, at a true
///   <see cref="BankDeg"/> (<see cref="LevelTurnAim"/>, <see cref="AutoAimBankScale"/>).
/// - Speed on pitch, the AWACS climb's law (<see cref="CenturionAwacsState.ClimbLeadPerMps"/>): it climbs at 150 m/s EAS up to
///   <see cref="ClimbSpeedMps"/> and cruises at <see cref="CruiseSpeedMps"/>, under the span schedule's retract at Mach 0.75
///   (217 m/s above 10 km, TelescopeController.AiSchedule), so the wing stays out; banks are held to <see cref="BankDeg"/>.
///   If the schedule retracts the wing anyway, it slows under Mach 0.70 until the schedule extends it again.
/// - Below its ingress height (50,000 ft, or its cruise height if lower) and short of its target it climbs on the AWACS
///   racetrack at a standoff from the target instead of pressing in, so it ingresses high.
/// The stock attack modes then release from height: unguided bombs on the stock vacuum fall-time solution
/// (AIPilotCombatModes.cs:619-651), glide bombs once <see cref="GlideReleaseRatio"/> is met, on every target near the aim
/// point, missiles on the stock salvo (:904-917). A radar-missile evasion the C-RAM can't cover (<see cref="AiCramHold"/>) keeps stock's bearing and jammer at the
/// profile's height, bank and throttle; an IR one keeps the stock throttle cut. Once the rounds are gone the stock state takes over: NoTarget heads for the nearest friendly airbase
/// and after 15 s without a target hands over to the landing state (AIPilotCombatModes.cs:362-379); with rounds left it
/// waits out its own missiles in flight first (<see cref="BeforeNoTarget"/>).
/// </summary>
static class AiHighStrike
{
    const string CenturionKey = "baanish_centurion";
    // 500 m under where the AI's own sortie last holds in the replica, on the split tail with LevelTurnAim: the climb on the
    // hold, the cruise and a 180 deg break-off turn at 20 deg without departing, linear in mass and within the replica's
    // 250 m steps: 15,500 m (50,900 ft) at 198.7 t, 15,800 m at 188 t, 16,750 m at 157 t, the cap below about 136 t
    // (tools/fm/centurion_cruise_band.py, S62). Above it the turn departs as run 20261016-175733's did from 14,500 m on the
    // single ruddervator, before LevelTurnAim: it sinks 770 to 850 m and passes 215 m/s, at 8 deg of AoA, where the
    // fly-by-wire's alpha limiter has cut the pitch rate a stick asks to a quarter. The elevator still trims a 1.1 g turn at
    // 208 m/s within 0.7 of the stick to 53,800 ft at 198.7 t and 55,400 ft at 188 t.
    const float CruiseAtMtowM = 15500f, MtowKg = 198700f, CruisePerKgM = 0.0300f, CruiseCapM = 17374f;
    // Mach 0.69 and 0.72 at the game's 290 m/s above 10 km (LevelInfo.GetSpeedOfSound). The climb's 10 m/s overspeed
    // guard tops out near 212 m/s; the span schedule retracts past 217 m/s.
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
    // The span schedule extends below Mach 0.70 and 190 m/s EAS (TelescopeController.AiSchedule); retracted, the bomber
    // flies under both until it does. At 214 m/s and 10 km (Mach 0.74) it otherwise stayed retracted for 2,500 s
    // (run 20261016-043908).
    const float ReextendMps = 195f, ReextendEasMps = 180f;
    const float LookaheadM = 8000f, NearGroundM = 1000f, ClimbOutStepM = 250f;
    // 50,000 ft. The hold's standoff is at least 30 km: outside a Boltstrike's 15 km x 1.2 and short of the glide release.
    // A new target within HoldMoveM of the hold's anchor keeps the track: in G6.1 the AI switched among T1 and two K92
    // structures every 80 to 250 s (run 20261016-043908).
    const float IngressHeightM = 15240f, HoldFloorM = 30000f, HoldMoveM = 5000f;
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
    static readonly int[] HighModes =
    {
        Mode("AttackMode", "FlyingToTarget"), Mode("AttackMode", "NoTarget"), Mode("AttackMode", "Bombing"),
        Mode("AttackMode", "GlideBombing"), Mode("AttackMode", "UsingMissiles"), Mode("AttackMode", "BreakOffAttack"),
    };
    static readonly int EvadeNone = Mode("EvadeMode", "None"), EvadeRadar = Mode("EvadeMode", "Radar");
    static readonly int UsingMissiles = Mode("AttackMode", "UsingMissiles");
    // Keyed by the aircraft's combat state, which lives as long as its pilot; the table lets a dead one go.
    static readonly ConditionalWeakTable<AIPilotCombatModes, Flight> Flights = new();
    static bool reportedMissing;

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-high-strike", typeof(AIPilotCombatModes), "UseGlideBombs",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeUseGlideBombs))),
        new("ai-high-strike", typeof(AIPilotCombatModes), "UseBombs",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeUseBombs))),
        new("ai-high-strike", typeof(AIPilotCombatModes), "UseMissiles",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeUseMissiles))),
        new("ai-high-strike", typeof(AIPilotCombatModes), "NoTarget",
            prefix: AccessTools.Method(typeof(AiHighStrike), nameof(BeforeNoTarget))),
        new("ai-high-strike", typeof(CombatAI), nameof(CombatAI.LookForMissileTargets),
            postfix: AccessTools.Method(typeof(AiHighStrike), nameof(AfterLookForMissileTargets))),
    };

    /// <summary>Per aircraft: the cruise height, refreshed once a second, the wing, and the climb hold's racetrack.</summary>
    sealed class Flight
    {
        internal float MassKg, CruiseM, CruiseAt = float.NegativeInfinity;
        internal TelescopeController? Telescope;
        internal bool Holding;
        internal int Direction;
        // The target position the hold circles, and where the hold began: the track lies on the side the bomber came from.
        internal GlobalPosition Anchor, From;
        internal float StandoffM = HoldFloorM, StandoffAt = float.NegativeInfinity;
        // Flying away from a missile target too near to line up on (MissileExtend).
        internal Unit? ExtendTarget;
        internal bool Extending;
        // Its own missiles, from Unit.RegisterMissile (Missile.cs:798) until they hit, miss or are shot down.
        internal readonly List<Missile> Missiles = new();

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

    static bool IsCenturion(Aircraft aircraft) =>
        aircraft != null && aircraft.definition != null && aircraft.definition.jsonKey == CenturionKey;

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

    /// <summary>For the AI readout: the combat state's own missiles in flight, 0 before its first high-profile step.</summary>
    internal static int MissilesInFlight(Pilot pilot) =>
        pilot.AICombatState != null && Flights.TryGetValue(pilot.AICombatState, out Flight flight) ? flight.MissilesInFlight() : 0;

    /// <summary>The level angle from the nose's heading to a point: a level bomber at height sees its target 30 deg or more below the nose.</summary>
    internal static float LevelAngle(Aircraft aircraft, Vector3 toTarget)
    {
        Vector3 forward = aircraft.transform.forward;
        forward.y = 0f;
        toTarget.y = 0f;
        return Vector3.Angle(forward, toTarget);
    }

    internal static float CruiseHeight(float massKg) => Mathf.Min(CruiseAtMtowM + (MtowKg - massKg) * CruisePerKgM, CruiseCapM);

    /// <summary>
    /// The aircraft's <see cref="Flight"/> with its wing and its cruise height, refreshed once a second, for <see cref="Steer"/>
    /// ahead of its early returns and for the release floor alike: with the height set only by the profile above
    /// <see cref="NearGroundM"/>, a bomber that never climbed that high had none, and the floor let it release at any height
    /// (run 20261016-225312: 16 GBM-500LR from 2,542 and 3,390 ft).
    /// </summary>
    static Flight CurrentFlight(AIPilotCombatModes combat, Aircraft aircraft)
    {
        if (!Flights.TryGetValue(combat, out Flight flight))
        {
            // Made on the first high-profile step or launch check, before any launch in combat.
            flight = Flights.GetValue(combat, _ => new Flight());
            aircraft.onRegisterMissile += flight.Missiles.Add;
        }
        if (flight.Telescope == null) aircraft.TryGetComponent(out flight.Telescope);
        float now = Time.timeSinceLevelLoad;
        if (now >= flight.CruiseAt)
        {
            flight.CruiseAt = now + RefreshS;
            flight.MassKg = aircraft.GetMass();
            flight.CruiseM = CruiseHeight(flight.MassKg);
        }
        return flight;
    }

    /// <summary>
    /// For a Centurion with bombs in a transit or attack mode, replaces AutoAim's destination with the high profile's and
    /// returns true; false leaves the stock command to <see cref="CombatHeightHold"/>, which below <see cref="NearGroundM"/> it
    /// has set to follow the terrain <see cref="ClimbOutStepM"/> above the bomber's height, on the climb hold's bearing.
    /// </summary>
    internal static bool Steer(Aircraft aircraft, AIPilotCombatModes combat, ref GlobalPosition destination, ref bool aimVelocity,
        ref bool followTerrain, ref float bankAllowed, ref float altitudeHold)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-high-strike")) return false;
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

        Flight flight = CurrentFlight(combat, aircraft);
        // A lost stage locks the span retracted (TelescopeController.FixedUpdate); the retracted wing can't fly the profile.
        if (flight.Telescope == null || flight.Telescope.Locked) return false;
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
                if (CenturionPlugin.Log.StageDue("ai-climb-out"))
                {
                    CenturionPlugin.Log.StageLine("ai-climb-out", Invariant(
                        $"{aircraft.name} {aircraft.persistentID} {aircraft.pilots[0].GetCurrentState()}: radar alt {aircraft.radarAlt:0} m, {(dodging ? "dodging a radar missile" : Invariant($"{AwacsOrbit.LevelDistance(position, flight.Anchor) / 1000f:0.0} km from the target, on the hold at {flight.StandoffM / 1000f:0} km"))}"));
                }
            }
            return false;
        }

        float speed = (velocity - aircraft.GetWindVelocity()).magnitude;
        bool retracted = flight.Telescope.Command < 0.5f;
        float height = retracted ? ReextendHeight(position.y, speed, out float throttle)
            : CommandHeight(position.y, speed, flight.CruiseM, out throttle);

        Vector3 ahead = destination - position;
        ahead.y = 0f;
        bool extending = !dodging && MissileExtend(aircraft, combat, flight, position, ref ahead);
        if (ahead.sqrMagnitude < 1f) ahead = new Vector3(aircraft.transform.forward.x, 0f, aircraft.transform.forward.z);
        GlobalPosition aim = position + ahead.normalized * LookaheadM;
        aim.y = height;
        bool holding = !dodging && ClimbHoldAim(aircraft, combat, flight, position, height, ref aim);

        destination = LevelTurnAim(aircraft, position, velocity, aim);
        aimVelocity = true;
        followTerrain = false;
        bankAllowed = Mathf.Min(bankAllowed, BankDeg / AutoAimBankScale(aircraft, position, velocity, velocity - aircraft.GetWindVelocity(), destination));
        // Dodging, the profile's throttle, not stock's full throttle (:1196): at the cruise height the command can't take the
        // excess as climb, so full throttle runs the speed up toward the span schedule's 217 m/s retract.
        if (!evading || dodging) aircraft.GetInputs().throttle = throttle;
        if (CenturionPlugin.Log.StageDue("ai-high-strike"))
        {
            float path = Mathf.Asin(Mathf.Clamp(velocity.y / Mathf.Max(velocity.magnitude, 1f), -1f, 1f)) * Mathf.Rad2Deg;
            float roll = Vector3.SignedAngle(aircraft.transform.up, Vector3.up, aircraft.transform.forward);
            CenturionPlugin.Log.StageLine("ai-high-strike", Invariant(
                $"{aircraft.name} {aircraft.persistentID} {aircraft.pilots[0].GetCurrentState()}: {flight.MassKg / 1000f:0.0} t, cruise {flight.CruiseM:0} m, at {position.y:0} m and {speed:0} m/s, path {path:0.0} deg, bank {roll:0} deg, command {height:0} m, throttle {throttle:0.00}{(retracted ? ", retracted: slowing to re-extend" : "")}{(holding ? Invariant($", climbing on the hold at {flight.StandoffM / 1000f:0} km") : extending ? ", extending from its missile target" : "")}{(dodging ? ", dodging a radar missile" : evading ? ", evading (stock throttle)" : "")}"));
        }

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

        float climb = Mathf.Min(ClimbEasMps * Mathf.Sqrt(LevelInfo.GetAirDensity(0f) / LevelInfo.GetAirDensity(y)), ClimbSpeedMps);
        throttle = Mathf.Clamp(1f - 0.1f * (speed - climb - CenturionAwacsState.ClimbOverspeedMps), CenturionAwacsState.ThrottleFloor, 1f);
        return Mathf.Min(cruise, y + Mathf.Clamp(CenturionAwacsState.ClimbLeadPerMps * (speed - climb), -200f, CenturionAwacsState.ClimbLeadMaxM));
    }

    /// <summary>Retracted: throttle back and pitch for a speed under both of the span schedule's extend limits.</summary>
    static float ReextendHeight(float y, float speed, out float throttle)
    {
        float target = Mathf.Min(ReextendMps, ReextendEasMps * Mathf.Sqrt(LevelInfo.GetAirDensity(0f) / LevelInfo.GetAirDensity(y)));
        throttle = Mathf.Clamp(0.6f + 0.1f * (target - speed), CenturionAwacsState.ThrottleFloor, 1f);
        return y + Mathf.Clamp(CenturionAwacsState.ClimbLeadPerMps * (speed - target), -500f, 1000f);
    }

    /// <summary>
    /// Below its ingress height (<see cref="IngressHeightM"/>, or the cruise height if lower), once within a racetrack's depth of
    /// the standoff from its target, the bomber climbs on <see cref="AwacsOrbit.Racetrack"/> round the target's position, on the
    /// side it came from, instead of pressing in. The hold latches: the track's end caps reach past the entry distance
    /// (<see cref="AwacsOrbit.FarthestM"/>), so it ends only at the ingress height, when the target is gone, or when the target
    /// moves to one more than <see cref="HoldMoveM"/> from the anchor, which starts a new track from where the bomber is.
    /// </summary>
    static bool ClimbHoldAim(Aircraft aircraft, AIPilotCombatModes combat, Flight flight, GlobalPosition position, float height, ref GlobalPosition aim)
    {
        Unit? target = CombatTarget?.Invoke(combat);
        FactionHQ hq = aircraft.NetworkHQ;
        if (position.y >= Mathf.Min(IngressHeightM, flight.CruiseM - CruiseEntryM) || target == null || target.disabled || hq == null
            || !hq.TryGetKnownPosition(target, out GlobalPosition known))
        {
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
            flight.StandoffM = Mathf.Max(HoldFloorM, CombatAI.GetSafeStandoffDist(anchor, hq));
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
    static bool MissileExtend(Aircraft aircraft, AIPilotCombatModes combat, Flight flight, GlobalPosition position, ref Vector3 ahead)
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
            return false;
        }

        Vector3 away = position - known;
        away.y = 0f;
        float distance = away.magnitude;
        if (!flight.Extending && distance < MissileExtendInM && LevelAngle(aircraft, -away) >= station.WeaponInfo.targetRequirements.minAlignment)
            flight.Extending = true;
        else if (flight.Extending && distance > MissileExtendOutM)
            flight.Extending = false;
        if (distance > 1f) ahead = flight.Extending ? away : -away;
        return flight.Extending;
    }

    /// <summary>
    /// Below its ingress height (<see cref="IngressHeightM"/>, or the cruise height if lower) a Centurion flying the high profile
    /// doesn't release. Stock releases unguided bombs whenever the vacuum fall time matches (AIPilotCombatModes.cs:646-652), at
    /// any height: a bomber that took a target 18.5 km away on its climb released 7 PAB-250 from 29,700 ft (run
    /// 20261016-212151, t=373 to 518). A wing locked retracted can't climb to it, so it releases as stock.
    /// </summary>
    static bool BelowIngress(AIPilotCombatModes combat, Aircraft aircraft)
    {
        Flight flight = CurrentFlight(combat, aircraft);
        return flight.Telescope != null && !flight.Telescope.Locked
            && aircraft.GlobalPosition().y < Mathf.Min(IngressHeightM, flight.CruiseM - CruiseEntryM);
    }

    /// <summary>Stock's unguided attack (AIPilotCombatModes.cs:589-670) for a Centurion, skipped below its ingress height, where
    /// <see cref="Steer"/> flies it.</summary>
    static bool BeforeUseBombs(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-high-strike")) return true;
        return checkMode || !IsCenturion(___aircraft) || !BelowIngress(__instance, ___aircraft);
    }

    /// <summary>
    /// Stock's missile launch (AIPilotCombatModes.cs:893-927) for a Centurion, skipped below its ingress height, where
    /// <see cref="Steer"/> flies it; the mode checks (:869-891) still run. Stock enters the mode at any height once the target
    /// is inside maxRange (:305), and the HQ's target can be anywhere it knows of (CombatAI.cs:261-269, 285): the AShM-300's
    /// 250 km and over-the-horizon flight (info_AShM1.asset) put most of a theatre in reach of the runway, so stock launches
    /// in the climb-out, slow and low, and with the Tusko-B's 60 km (AShM3_info.asset) once the target clears the horizon.
    /// From height it launches as stock does (:904-917) with the alignment taken on the level bearing, as
    /// <see cref="BeforeUseGlideBombs"/> takes it: stock's minAlignment (30 deg for both missiles) is measured from the nose
    /// (targetAngle, :500), and from 16 km any target nearer than about 28 km lies further below the nose than that. Stock's
    /// break-off inside twice minRange (:918-927) is left out: from the ingress height the slant range is never that short.
    /// </summary>
    static bool BeforeUseMissiles(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft, Pilot ___pilot, Unit ___currentTarget,
        WeaponInfo ___currentWeaponInfo, Vector3 ___targetVector, float ___targetDist, ref float ___lastFiredTime)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-high-strike")) return true;
        if (checkMode || !IsCenturion(___aircraft)) return true;
        if (BelowIngress(__instance, ___aircraft)) return false;
        Flight flight = CurrentFlight(__instance, ___aircraft);
        if (flight.Telescope == null || flight.Telescope.Locked || ___currentWeaponInfo == null || ___currentTarget == null
            || ___currentTarget.disabled || ___currentWeaponInfo.muzzleVelocity > 0f)
        {
            return true;
        }

        float now = Time.timeSinceLevelLoad;
        if (___targetDist >= ___currentWeaponInfo.targetRequirements.maxRange || now - ___lastFiredTime <= 2.5f
            || LevelAngle(___aircraft, ___targetVector) >= ___currentWeaponInfo.targetRequirements.minAlignment)
        {
            return false;
        }

        WeaponManager weapons = ___aircraft.weaponManager;
        List<Unit> targets = weapons.GetTargetList();
        targets.Clear();
        int count = CombatAI.LookForMissileTargets(___aircraft, ___currentTarget, weapons.currentWeaponStation, targets);
        weapons.TargetListChanged();
        if (count > 0)
        {
            ___pilot.Fire();
            ___lastFiredTime = now;
        }

        return false;
    }

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
        if (CenturionPlugin.FeaturesOff.Contains("ai-high-strike")) return;
        if (!checkMode || !IsCenturion(___aircraft) || !Flights.TryGetValue(__instance, out Flight flight)
            || StrikeRounds(___aircraft) == 0)
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
    /// <see cref="GlideReleaseRatio"/> and the alignment taken on the level bearing. Stock's minAlignment (30 deg for the
    /// PAB-250LR and GBM-500LR, info_bomb_250_glide.asset) is measured from the nose (targetAngle, AIPilotCombatModes.cs:500),
    /// and a level bomber at 16.3 km sees the target 33.8 deg below its nose at the 0.6 point, so stock would never release.
    /// </summary>
    static bool BeforeUseGlideBombs(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft, Pilot ___pilot, Unit ___currentTarget, WeaponInfo ___currentWeaponInfo,
        Vector3 ___targetVector, float ___targetDist, float ___targetAngle, bool ___targetObscured, ControlInputs ___controlInputs,
        ref float ___aimEffort, ref bool ___followTerrain, ref float ___bombLastDropped, ref float ___lastFiredTime)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-high-strike")) return true;
        if (!checkMode || !IsCenturion(___aircraft) || ___currentTarget == null || ___currentTarget.disabled || ___currentWeaponInfo == null
            || ___targetDist < ___currentWeaponInfo.targetRequirements.minRange)
        {
            return true;
        }

        ___followTerrain = ___targetAngle > 20f;
        ___controlInputs.throttle = 1f;
        ___aimEffort = 0.5f;
        float above = (___aircraft.GlobalPosition() - ___currentTarget.GlobalPosition()).y;
        float now = Time.timeSinceLevelLoad;
        if (BelowIngress(__instance, ___aircraft) || (above + ___aircraft.speed * ___aircraft.speed * 0.03f) / ___targetDist < GlideReleaseRatio || ___targetObscured
            || now - ___bombLastDropped <= 5f || LevelAngle(___aircraft, ___targetVector) >= ___currentWeaponInfo.targetRequirements.minAlignment)
        {
            return false;
        }

        WeaponManager weapons = ___aircraft.weaponManager;
        List<Unit> targets = weapons.GetTargetList();
        targets.Clear();
        int count = CombatAI.LookForMissileTargets(___aircraft, ___currentTarget, weapons.currentWeaponStation, targets);
        weapons.TargetListChanged();
        if (count > 0)
        {
            ___bombLastDropped = now;
            ___lastFiredTime = now;
            ___pilot.Fire();
        }

        return false;
    }

    /// <summary>
    /// A glide release lists, beside the target, the units within 1 km of it that are inside the weapon's 10 km maxRange of
    /// the aircraft and its nose cone (CombatAI.cs:191); from a 25 km release at height that leaves the target alone. For a
    /// Centurion's glide bombs this adds the neighbours stock dropped for that range or that cone, with the cone taken on the
    /// level bearing as <see cref="BeforeUseGlideBombs"/> does and stock's other tests, so one release saturates.
    /// </summary>
    static void AfterLookForMissileTargets(Aircraft aircraft, Unit currentTarget, WeaponStation weaponStation, List<Unit> outTargets, ref int __result)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-high-strike")) return;
        if (__result <= 0 || __result >= MaxGlideTargets || !IsCenturion(aircraft) || weaponStation == null || weaponStation.WeaponInfo == null
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
            if (tracking == null || LevelAngle(aircraft, item.transform.position - aircraft.transform.position) >= weapon.targetRequirements.minAlignment
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
