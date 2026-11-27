using System.Collections.Generic;
using System.Runtime.CompilerServices;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.Networking;
using NuclearOption.SavedMission;

[assembly: InternalsVisibleTo("StockMissionSupply.Tests")]

namespace Centurion;

/// <summary>
/// In the stock operations that have a BDF Darkreach factory, has that one factory build the Centurion and the
/// Darkreach in turn (owner, 2026-11-21: in stock missions as the Icarus is, BDF only; docs/SPEC.md "Stock missions").
/// BDF starts with none: a starting reserve was overpowered (owner, 2026-11-24), so the first arrives with the
/// factory's first delivery. The host's setting decides, read at each mission load. Missions without such
/// a factory keep their stock supply, and the mission editor is left alone, since it saves a factory's live production
/// type back into the mission. The factory alternates through its own timer: a second SetFactory call would start a
/// second timer, so the first call is repointed in a prefix and each later swap follows ProduceUnit.
/// </summary>
static class StockMissionSupply
{
    internal const string Faction = "Boscali";
    internal const string Darkreach = "Darkreach";

    internal static readonly Dictionary<string, string> Factories = new()
    {
        ["Domination"] = "NorthFac7",
        ["Domination Co-op as BDF"] = "NorthFac7",
        ["Domination Co-op as PALA"] = "NorthFac7",
        ["Escalation"] = "NorthFac7",
        ["Escalation Co-op as BDF"] = "NorthFac7",
        ["Escalation Co-op as PALA"] = "NorthFac7",
        ["Terminal Control"] = "BDF_southFac9",
        ["Terminal Control Co-op as BDF"] = "BDF_southFac9",
        ["Terminal Control Co-op as PALA"] = "BDF_southFac9",
    };

    internal static PatchTarget[] PatchTargets => new PatchTarget[]
    {
        new("stock-supply", typeof(Factory), nameof(Factory.SetFactory), new[] { typeof(string), typeof(float) },
            prefix: AccessTools.Method(typeof(StockMissionSupply), nameof(BeforeSetFactory))),
        new("stock-supply", typeof(Factory), "ProduceUnit",
            postfix: AccessTools.Method(typeof(StockMissionSupply), nameof(AfterProduceUnit))),
    };

    static ConfigEntry<bool>? enabled;
    static Mission? selectedMission;
    static string? selectedFactory;

    internal static void Install(ConfigFile config)
    {
        enabled = config.Bind("Missions", "StockMissionSupply", true,
            "In stock Domination, Escalation, Terminal Control and their co-op variants, have one BDF factory alternate between the Centurion and the Darkreach. The host's setting applies from the next mission load");
    }

    static string? MissionFactory(Mission? mission)
    {
        if (mission?.LoadKey is not { } key || !Factories.TryGetValue(key.Name, out string factory))
        {
            return null;
        }

        // Customize Mission retains the name but drops the source group. Require the stock factory in that copy.
        return key.Group == MissionGroup.BuiltIn || (key.Group == MissionGroup.Temp && key.Key == "CurrentMission"
            && mission.buildings.Exists(b => b.UniqueName == factory && b.faction == Faction
                && b.factoryOptions?.productionType == Darkreach)) ? factory : null;
    }

    static string? ActiveFactory()
    {
        if (CenturionPlugin.FeaturesOff.Contains("stock-supply") || GameManager.gameState == GameState.Editor
            || GameManager.IsPlayingFromEditor || !NetworkManagerNuclearOption.i.Server.Active)
        {
            return null;
        }

        // The stock mission manager clears its load event on teardown. Each stock load and restart has its own Mission.
        Mission? mission = MissionManager.CurrentMission;
        if (!ReferenceEquals(mission, selectedMission))
        {
            selectedMission = mission;
            selectedFactory = enabled?.Value == true ? MissionFactory(mission) : null;
        }

        return selectedFactory;
    }

    public static void Apply()
    {
        if (ActiveFactory() is not { } factoryName || !Encyclopedia.Lookup.TryGetValue(CenturionPlugin.JsonKey, out UnitDefinition definition)
            || definition is not AircraftDefinition centurion)
        {
            return;
        }

        // Blueprinter may have registered the Centurion after SetFactory. Keep the timer already running.
        if (FindFactory(factoryName) is { } factory && IsMissionFactory(factory)
            && factory.productionUnit?.jsonKey == Darkreach)
        {
            SetProduction(factory, centurion);
        }
    }

    static bool IsMissionFactory(Factory factory) => factory.attachedUnit != null
        && factory.attachedUnit.UniqueName == ActiveFactory() && factory.attachedUnit.NetworkHQ != null
        && factory.attachedUnit.NetworkHQ.faction?.factionName == Faction;

    internal static string NextProduction(string current) => current == CenturionPlugin.JsonKey ? Darkreach : CenturionPlugin.JsonKey;

    static void BeforeSetFactory(Factory __instance, ref string productionType)
    {
        if (productionType != Darkreach || !IsMissionFactory(__instance))
        {
            return;
        }

        string next = NextProduction(productionType);
        if (Encyclopedia.Lookup.ContainsKey(next))
        {
            // A second SetFactory call would start a second production timer.
            productionType = next;
        }
    }

    static void AfterProduceUnit(Factory __instance)
    {
        if (!IsMissionFactory(__instance) || __instance.productionUnit?.jsonKey is not (Darkreach or CenturionPlugin.JsonKey))
        {
            return;
        }

        string built = __instance.productionUnit.jsonKey;
        if (!Encyclopedia.Lookup.TryGetValue(NextProduction(built), out UnitDefinition next))
        {
            return;
        }

        SetProduction(__instance, next);
    }

    // The existing timer reads productionUnit when it fires again.
    static void SetProduction(Factory factory, UnitDefinition next)
    {
        factory.NetworkproductionUnit = next;
        factory.attachedUnit.NetworkunitName = next.code + " factory";
    }

    static Factory? FindFactory(string name) => UnitRegistry.customIDLookup.TryGetValue(name, out Unit unit) && unit != null
        && !unit.disabled && unit.TryGetComponent<Factory>(out var factory) ? factory : null;

#if CENTURION_DEV
    internal static Dictionary<string, object> AddReadout(Dictionary<string, object> state)
    {
        Factory? factory = MissionFactory(MissionManager.CurrentMission) is { } name ? FindFactory(name) : null;
        state["stock_factory"] = factory?.attachedUnit.UniqueName ?? AircraftReadout.NoText;
        state["stock_factory_next"] = factory?.ProductionUnit?.jsonKey ?? AircraftReadout.NoText;
        state["stock_factory_last_s"] = factory?.lastProductionTime ?? AircraftReadout.NotRead;
        state["stock_factory_interval_s"] = factory?.ProductionInterval ?? AircraftReadout.NotRead;
        return state;
    }
#endif
}
