using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

static class FireDamageDiagnostics
{
    sealed class Hits
    {
        internal int Count;
        internal float LastAt;
    }

    static readonly ConditionalWeakTable<Aircraft, Hits> IgnoredHits = new();
    static readonly FieldInfo? EngineHp = AccessTools.Field(typeof(Turbofan), "hitPoints");
    static readonly FieldInfo? OnFire = AccessTools.Field(typeof(FuelTank), "onFire");

    internal static void Ignored(Aircraft aircraft)
    {
        Hits hits = IgnoredHits.GetValue(aircraft, _ => new Hits());
        hits.Count++;
        hits.LastAt = Time.timeSinceLevelLoad;
    }

    internal static void Read(Dictionary<string, object> state, bool enabled)
    {
        var values = new Dictionary<string, object>();
        foreach (string key in new[] { "targets", "part_count", "engine_count", "tank_count", "min_part_hp", "min_engine_hp", "burning_tanks", "ignored_hits", "last_ignored_age_s" })
            values[key] = AircraftReadout.NotRead;
        state["attacker_fire"] = values;
        if (!enabled) return;
        Aircraft[] targets = UnitRegistry.allAircraft.Where(a => a != null && a.definition != null && a.definition.jsonKey == "baanish_centurion").ToArray();
        values["targets"] = targets.Length;
        if (targets.Length != 1) return;
        Aircraft target = targets[0];
        UnitPart[] parts = target.partLookup.Where(p => p != null && p is AeroPart).ToArray();
        Turbofan[] engines = target.engineStates.OfType<Turbofan>().ToArray();
        values["part_count"] = parts.Length;
        values["engine_count"] = engines.Length;
        values["tank_count"] = target.GetFuelTanks().Count;
        if (parts.Length > 0) values["min_part_hp"] = parts.Min(p => p.hitPoints);
        if (engines.Length > 0 && EngineHp != null) values["min_engine_hp"] = engines.Min(e => (float)EngineHp.GetValue(e));
        if (OnFire != null) values["burning_tanks"] = target.GetFuelTanks().Count(t => t != null && (bool)OnFire.GetValue(t));
        bool hit = IgnoredHits.TryGetValue(target, out Hits hits);
        values["ignored_hits"] = hit ? hits.Count : 0;
        if (hit) values["last_ignored_age_s"] = Time.timeSinceLevelLoad - hits.LastAt;
    }
}
