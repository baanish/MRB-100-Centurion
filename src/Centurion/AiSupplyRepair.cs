using System.Collections.Generic;
using NuclearOption.Networking;
using NuclearOption.SavedMission;

namespace Centurion;

/// <summary>
/// Gives each faction HQ back the mission's aircraft supplies it dropped at load. FactionHQ.OnMissionLoad resolves every
/// supply key through Encyclopedia.Lookup and skips any it can't (FactionHQ.cs:1023-1028); Blueprinter's aircraft are not
/// in the lookup yet at that point, so a mission's Centurions never reached AircraftSupply and the HQ never deployed one
/// (G6.3's run: supply 10 in the mission, 0 in the HQ). Runs on the server a few seconds into each mission, before the
/// HQ's first deploy tick matters; an entry the HQ already holds is left alone.
/// </summary>
static class AiSupplyRepair
{
    public static void Apply(CenturionLog log)
    {
        Mission? mission = MissionManager.CurrentMission;
        if (mission == null || !NetworkManagerNuclearOption.i.Server.Active)
        {
            return;
        }

        foreach (FactionHQ hq in FactionRegistry.GetAllHQs())
        {
            string? name = hq.faction?.factionName;
            MissionFaction? saved = name == null ? null : mission.factions.Find(f => f.factionName == name);
            if (saved == null)
            {
                continue;
            }

            // A mission may list one type more than once; the HQ adds every entry (FactionHQ.cs:491-503, 1023-1028), so sum them.
            var dropped = new Dictionary<AircraftDefinition, int>();
            foreach (UnitCount supply in saved.supplies)
            {
                if (Encyclopedia.Lookup.TryGetValue(supply.UnitType, out UnitDefinition definition)
                    && definition is AircraftDefinition aircraft && !hq.AircraftSupply.ContainsKey(aircraft))
                    dropped[aircraft] = (dropped.TryGetValue(aircraft, out int count) ? count : 0) + supply.Count;
            }

            foreach (KeyValuePair<AircraftDefinition, int> entry in dropped)
            {
                hq.ModifyUnitSupply(entry.Key, entry.Value);
                log.Info($"ai supply: restored {entry.Value} {entry.Key.jsonKey} to {saved.factionName}, dropped at mission load");
            }
        }
    }
}
