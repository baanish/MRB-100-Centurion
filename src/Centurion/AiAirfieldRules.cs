using System.Runtime.CompilerServices;
using HarmonyLib;
using NuclearOption.Networking;
using NuclearOption.SavedMission;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

static class AiAirfieldRules
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-spawn", typeof(Airbase), nameof(Airbase.TrySpawnAircraft),
            new[] { typeof(Player), typeof(AircraftDefinition), typeof(LiveryKey), typeof(Loadout), typeof(float) },
            prefix: AccessTools.Method(typeof(AiAirfieldRules), nameof(BeforeTrySpawnAircraft))),
        new("ai-runway", typeof(Airbase), nameof(Airbase.GetTakeoffRunway), new[] { typeof(Aircraft), typeof(float) },
            prefix: AccessTools.Method(typeof(AiAirfieldRules), nameof(BeforeGetTakeoffRunway))),
        new("hangar-hold", typeof(AIPilotTaxiState), nameof(AIPilotTaxiState.FixedUpdateState), new[] { typeof(Pilot) },
            postfix: AccessTools.Method(typeof(AiAirfieldRules), nameof(AfterTaxiStep))),
    };

    // The hangar_med door plane stands 22.5 to 23.1 m out from its spawn point (.cache/refresh/jointbreak/RCA.md, geometry).
    const float HangarHoldM = 30f;
    const float WingClearOfHangarM = 34f;
    // An AI Centurion taxis out at 12 kt at most, at every airbase. At the stock 16 to 22 kt its 19.5 m wheelbase turns wide
    // at taxiway junctions and puts the nose wheel on the grass: it leans there with its legs intact, and the stock taxi
    // state abandons an aircraft leaning 2.87 deg. Flown with the limit: 12 of 12 departures at Vigil Cay, 3 of 3 at Maris
    // and at Agrapol, no wheel on grass; about 75 s longer on Vigil Cay's east route; the taxi state's 30 s low-speed
    // timer peaked at 8.4 s. Arrivals taxi in under stock control.
    const float OutboundTaxiSpeedMps = 6f;

    /// <summary>A Centurion's taxi hold (<see cref="CenturionSystems.TaxiHold"/>), made on its first taxi step.</summary>
    internal sealed class TaxiHold
    {
        public readonly HangarGuard Guard;
        public float HeldSince = float.NaN;
        public TaxiHold(Aircraft aircraft) => Guard = new HangarGuard(aircraft);
    }

#if CENTURION_DEV
    static Mission? seenMission;
    static int spawnRejects;
    static string spawnRejected = AircraftReadout.NoText;

    public static int SpawnRejects { get { ResetMissionCounts(); return spawnRejects; } }
    public static string SpawnRejected { get { ResetMissionCounts(); return spawnRejected; } }

    static void ResetMissionCounts()
    {
        if (ReferenceEquals(seenMission, MissionManager.CurrentMission)) return;
        seenMission = MissionManager.CurrentMission;
        spawnRejects = 0;
        spawnRejected = AircraftReadout.NoText;
    }
#endif

    static bool BeforeTrySpawnAircraft(Airbase __instance, Player player, AircraftDefinition definition,
        ref Airbase.TrySpawnResult __result)
    {
        if (player != null || !CenturionSystems.IsCenturion(definition)) return true;
#if CENTURION_DEV
        ResetMissionCounts();
#endif
        if (HasTakeoffRunway(__instance, definition.aircraftParameters.takeoffDistance)) return true;
#if CENTURION_DEV
        spawnRejects++;
        spawnRejected = MissionGeometryLog.AirbaseName(__instance);
#endif
        __result = default;
        return false;
    }

    /// <summary>
    /// A taxiing Centurion stays parked, throttle 0 and full brake, while the medium hangar it stands in is still opening its
    /// doors. A hangar spawn (DoorSequenceNormal) or a taxi from a mission-placed spot opens the doors as the aircraft starts,
    /// and the stock taxi brakes only for 8 s (AIPilotTaxiState.cs:417) against the 15 s the doors take, so the 43.6 m span met
    /// the still-opening 46 m door (run 20261122-025914-dmg_hangar_exit). The stock waitForOpenBeforeSpawn is deliberately not
    /// used: it runs DoorSequenceCarrier, which closes the doors right after the spawn, and they shut on the Centurion 11 s
    /// later (run 20261122-035801-dmg_ai_hangar_spawn). The 15 s hold stays under the taxi's 30 s stuck timer
    /// (AIPilotTaxiState.IsStuck).
    /// </summary>
    static void AfterTaxiStep(Pilot pilot)
    {
        if (CenturionSystems.Of(pilot.aircraft) is not { } systems) return;
        Aircraft aircraft = systems.Aircraft;
        TaxiHold hold = systems.TaxiHold ??= new TaxiHold(aircraft);
        Hangar? hangar = hold.Guard.OpeningNear(HangarHoldM);
        if (hangar != null)
        {
            ControlInputs inputs = aircraft.GetInputs();
            inputs.throttle = 0f;
            inputs.brake = 1f;
            if (float.IsNaN(hold.HeldSince))
            {
                hold.HeldSince = Time.timeSinceLevelLoad;
                CenturionPlugin.Log.Info(Invariant($"hangar-hold: {aircraft.name} parked until {hangar.name}'s doors are fully open ({hangar.NetworkdoorState.openAmount:0.00} open)"));
            }
        }
        else if (!float.IsNaN(hold.HeldSince))
        {
            CenturionPlugin.Log.Info(Invariant($"hangar-hold: {aircraft.name} released after {Time.timeSinceLevelLoad - hold.HeldSince:0.0} s"));
            hold.HeldSince = float.NaN;
        }

        if (hangar != null) return;
        FollowHangarDeparture(pilot, aircraft);
        if (pilot.currentState is not AIPilotTaxiState || pilot.flightInfo.HasTakenOff || aircraft.Player != null) return;

        ControlInputs taxiInputs = aircraft.GetInputs();
        taxiInputs.throttle = Mathf.Min(taxiInputs.throttle,
            Mathf.Clamp(0.5f + (OutboundTaxiSpeedMps - aircraft.speed) * 0.3f, 0.01f, 0.5f));
        if (aircraft.speed > OutboundTaxiSpeedMps) taxiInputs.brake = Mathf.Max(taxiInputs.brake, 1f);
    }

    static void FollowHangarDeparture(Pilot pilot, Aircraft aircraft)
    {
        if (pilot.currentState is not AIPilotTaxiState || pilot.flightInfo.HasTakenOff) return;
        Hangar? hangar = aircraft.NetworkspawningHangar;
        if (hangar == null || hangar.parentAirbase == null || hangar.parentAirbase.AttachedAirbase ||
            !hangar.TryGetComponent(out Unit unit) || unit.definition?.jsonKey != "hangar_med") return;
        Transform? spawn = hangar.GetSpawnTransform();
        if (spawn == null) return;

        // The stock 10 m rollout can turn a retracted wing back into the 22.6 m door jamb.
        Vector3 offset = aircraft.transform.position - spawn.position;
        float distance = Vector3.Dot(offset, spawn.forward);
        if (distance < 10f || distance >= WingClearOfHangarM) return;
        float crossTrack = Vector3.Dot(offset, spawn.right);
        if (Mathf.Abs(crossTrack) > 3f) return;

        float headingError = Mathf.DeltaAngle(aircraft.transform.eulerAngles.y, spawn.eulerAngles.y);
        float intercept = Mathf.Atan2(crossTrack, 20f) * Mathf.Rad2Deg;
        aircraft.GetInputs().yaw = Mathf.Clamp((headingError - intercept) * 0.04f, -1f, 1f);
    }

    static void BeforeGetTakeoffRunway(Airbase __instance, Aircraft aircraft, ref float takeoffDist)
    {
        if (!CenturionSystems.IsCenturion(aircraft.definition)) return;
        float minimum = aircraft.definition.aircraftParameters.takeoffDistance;
        // Keep the stock attempt when no qualifying runway exists, including a player's taxi at a short base.
        if (takeoffDist < minimum && HasTakeoffRunway(__instance, minimum)) takeoffDist = minimum;
    }

    static bool HasTakeoffRunway(Airbase airbase, float minimum)
    {
        foreach (Airbase.Runway runway in airbase.runways)
            if (runway.Takeoff && runway.Length >= minimum) return true;
        return false;
    }
}
