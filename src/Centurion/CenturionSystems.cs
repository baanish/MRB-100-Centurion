using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// First sight of a Centurion for the M3 systems (docs/M3-DESIGN.md, "First sight and rebinding"). The game calls
/// Aircraft.SetLocalSim(bool) on every peer from OnStartClient, after every component's Awake and before the loadout spawns
/// (Aircraft.cs:1149, 1181, 1235), and again on an authority change, so the attach is idempotent. A postfix of its own keeps
/// the systems off the telescope's feature switch.
/// </summary>
static class CenturionSystems
{
    /// <summary>AircraftDefinition.jsonKey of the Centurion (CenturionAuthor.JsonKey).</summary>
    const string CenturionKey = "baanish_centurion";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("systems", typeof(Aircraft), nameof(Aircraft.SetLocalSim), new[] { typeof(bool) },
            postfix: AccessTools.Method(typeof(CenturionSystems), nameof(AfterSetLocalSim))),
    };

    static void AfterSetLocalSim(Aircraft __instance)
    {
        if (CenturionPlugin.FeaturesOff.Contains("systems")) return;
        if (__instance.definition == null || __instance.definition.jsonKey != CenturionKey)
        {
            return;
        }

        AddIfMissing<OwnerState>(__instance);
        AddIfMissing<RadarSuite>(__instance);
        AddIfMissing<AwacsBeam>(__instance);
        AddIfMissing<CramGuard>(__instance);
        AddIfMissing<FanSpin>(__instance);
        AddIfMissing<CabinEngineSound>(__instance);
        AddIfMissing<CenturionAi>(__instance);
        AddIfMissing<BayCookoff>(__instance);
        AddIfMissing<TankFireSpread>(__instance);
    }

    static void AddIfMissing<T>(Aircraft aircraft) where T : MonoBehaviour
    {
        if (!aircraft.TryGetComponent<T>(out _))
        {
            aircraft.gameObject.AddComponent<T>();
        }
    }
}
