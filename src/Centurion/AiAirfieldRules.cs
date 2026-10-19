using HarmonyLib;
using NuclearOption.Networking;
using NuclearOption.SavedMission;

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
    };

    const string CenturionKey = "baanish_centurion";

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

    static bool BeforeTrySpawnAircraft(Airbase __instance, Player player, AircraftDefinition definition,
        ref Airbase.TrySpawnResult __result)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-spawn")) return true;
        if (player != null || definition?.jsonKey != CenturionKey) return true;
        ResetMissionCounts();
        if (HasTakeoffRunway(__instance, definition.aircraftParameters.takeoffDistance)) return true;
        spawnRejects++;
        spawnRejected = MissionGeometryLog.AirbaseName(__instance);
        __result = default;
        return false;
    }

    static void BeforeGetTakeoffRunway(Airbase __instance, Aircraft aircraft, ref float takeoffDist)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-runway")) return;
        if (aircraft.definition.jsonKey != CenturionKey) return;
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
