using NuclearOption.SavedMission;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// One-shot diagnostics per mission load, for gates G0.3 (every runway length, the longest recorded in SPEC.md) and G0.4
/// (playable bounds and medium-hangar base positions, for the AWACS standoff). Positions are global (floating-origin
/// independent) metres.
/// </summary>
public static class MissionGeometryLog
{
    /// <summary>The medium hangar's UnitDefinition key (hangar_med.asset); the Centurion only fits these.</summary>
    const string MediumHangarKey = "hangar_med";

    const string CenturionKey = "baanish_centurion";

    public static void Write(CenturionLog log)
    {
        AircraftDefinition? centurion = Encyclopedia.Lookup.TryGetValue(CenturionKey, out UnitDefinition definition) ? definition as AircraftDefinition : null;
        Mission? mission = MissionManager.CurrentMission;
        LevelInfo level = NetworkSceneSingleton<LevelInfo>.i;
        string map = mission == null ? "?" : mission.MapKey.Path;
        log.Info($"geometry: mission '{mission?.Name}' map '{map}'");

        if (level != null && level.LoadedMapSettings != null)
        {
            // The game's own bounds check (ClientAuthChecks_Simple) treats |x| and |z| past half of MapSize as off the map.
            Vector2 size = level.LoadedMapSettings.MapSize;
            log.Info(Invariant($"geometry: map bounds x {-size.x / 2f:F0} to {size.x / 2f:F0}, z {-size.y / 2f:F0} to {size.y / 2f:F0} (MapSize {size.x:F0} x {size.y:F0}, settings '{level.LoadedMapSettings.name}')"));
        }
        else
        {
            log.Warning("geometry: no LoadedMapSettings; map bounds unknown");
        }

        string longestName = "none";
        float longest = 0f;
        int airbases = 0;
        foreach (Airbase airbase in FactionRegistry.airbaseLookup.Values)
        {
            if (airbase == null)
            {
                continue;
            }

            airbases++;
            string name = AirbaseName(airbase);
            Airbase.Runway[]? runways = airbase.runways;
            if (runways == null || runways.Length == 0)
            {
                log.Info($"runway: '{name}' has no runways");
            }
            else
            {
                foreach (Airbase.Runway runway in runways)
                {
                    GlobalPosition start = runway.Start.GlobalPosition(), end = runway.End.GlobalPosition();
                    log.Info(Invariant($"runway: '{name}' {runway.GetName(false)} length {runway.Length:F1} m takeoff={runway.Takeoff} landing={runway.Landing} start {start.x:F1}, {start.y:F1}, {start.z:F1} end {end.x:F1}, {end.y:F1}, {end.z:F1}"));
                    if (runway.Length > longest)
                    {
                        longest = runway.Length;
                        longestName = $"'{name}' {runway.GetName(false)}";
                    }
                }
            }

            int medium = 0;
            foreach (Hangar hangar in airbase.hangars)
            {
                if (hangar == null || !hangar.TryGetComponent(out Unit unit) || unit.definition == null || unit.definition.jsonKey != MediumHangarKey)
                {
                    continue;
                }

                if (medium++ == 0 && airbase.center != null)
                {
                    GlobalPosition c = airbase.center.GlobalPosition();
                    log.Info(Invariant($"medium-hangar base: '{name}' center {c.x:F1}, {c.y:F1}, {c.z:F1}"));
                }

                GlobalPosition p = hangar.transform.GlobalPosition();
                bool takesCenturion = centurion != null && System.Array.IndexOf(hangar.GetAvailableAircraft(), centurion) >= 0;
                log.Info(Invariant($"medium hangar: '{name}' {hangar.name} at {p.x:F1}, {p.y:F1}, {p.z:F1} yaw {hangar.transform.eulerAngles.y:F1} priority {hangar.GetPriority():F1} takes the Centurion {takesCenturion}"));
            }
        }

        log.Info(Invariant($"geometry: {airbases} airbases; longest runway {longestName} {longest:F1} m"));

        // The HQ deploys AI aircraft from Encyclopedia.i.aircraft and its supply map (FactionHQ.cs:912-961); a player's spawn looks the key up instead.
        bool listed = centurion != null && Encyclopedia.i.aircraft.Contains(centurion);
        foreach (FactionHQ hq in FactionRegistry.GetAllHQs())
        {
            int supply = centurion != null && hq.AircraftSupply.TryGetValue(centurion, out var held) ? held.Count : 0;
            log.Info(Invariant($"ai supply: {hq.faction?.factionName} Centurion {supply}, AI limit {hq.AIAircraftLimit}, in the aircraft list {listed}"));
        }
    }

    internal static string AirbaseName(Airbase airbase)
    {
        SavedAirbase saved = airbase.SavedAirbase;
        if (saved == null)
        {
            return airbase.name;
        }

        return string.IsNullOrEmpty(saved.DisplayName) ? saved.UniqueName : saved.DisplayName;
    }
}
