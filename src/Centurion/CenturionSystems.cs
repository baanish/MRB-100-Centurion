using System.Collections.Generic;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// A Centurion's record: added at first sight with its systems, and the one place a hook on a per-frame game method asks
/// whether an aircraft is a Centurion (<see cref="Of"/>) and finds its systems, so no hook compares definition keys or
/// searches components every step. The game calls Aircraft.SetLocalSim(bool) on every peer from OnStartClient, after
/// every component's Awake and before the loadout spawns (Aircraft.cs:1149, 1181, 1235), and again on an authority change,
/// so the attach is idempotent. SetLocalSim sets the physics mode before it returns (Aircraft.cs:1289-1305), whose
/// postfix has added the telescope by the time this one runs.
/// </summary>
sealed class CenturionSystems : MonoBehaviour
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("systems", typeof(Aircraft), nameof(Aircraft.SetLocalSim), new[] { typeof(bool) },
            postfix: AccessTools.Method(typeof(CenturionSystems), nameof(AfterSetLocalSim))),
    };

    /// <summary>Every Centurion on this peer from its first sight until it is destroyed: a mission without one costs a hook
    /// a count test, and with them one hash lookup on the instance id.</summary>
    static readonly Dictionary<Aircraft, CenturionSystems> Live = new();

    internal Aircraft Aircraft = null!;
    internal TelescopeController? Telescope;
    internal OwnerState Owner = null!;
    internal RadarSuite Radar = null!;
    internal AwacsBeam Beam = null!;
    internal CramGuard Cram = null!;
    /// <summary>The AI's AWACS pilot state, which replaces the stock combat state on an AWACS loadout (CenturionAwacsState.BeforeSwitchState).</summary>
    internal readonly CenturionAwacsState AwacsState = new();
    /// <summary>The strike AI's per-sortie state, made on its first high-profile step.</summary>
    internal AiHighStrike.Flight? Strike;
    internal BombRelease.Trigger Trigger = new();
    internal AiAirfieldRules.TaxiHold? TaxiHold;

    /// <summary>The one key test, for the cold paths that can run before first sight; everything else asks <see cref="Of"/>.</summary>
    internal static bool IsCenturion(AircraftDefinition? definition) => definition != null && definition.jsonKey == CenturionPlugin.JsonKey;

    /// <summary>The aircraft's record; null for any other aircraft, and for a Centurion before its first sight.</summary>
    internal static CenturionSystems? Of(Aircraft? aircraft) =>
        Live.Count != 0 && aircraft is not null && Live.TryGetValue(aircraft, out CenturionSystems systems) ? systems : null;

    // LoadHardpointSet applies the same restriction before fitting a mount. A lost beam keeps its loadout identity.
    internal bool IsAwacs => Aircraft.loadout != null && Aircraft.loadout.weapons.Count > 2
        && Aircraft.loadout.weapons[2] != null && Aircraft.loadout.weapons[2].jsonKey == AwacsBeam.AwacsKey
        && (Aircraft.NetworkHQ == null || !Aircraft.NetworkHQ.restrictedWeapons.Contains(Aircraft.loadout.weapons[2].name));

    static void AfterSetLocalSim(Aircraft __instance)
    {
        if (!IsCenturion(__instance.definition))
        {
            return;
        }

        if (!__instance.TryGetComponent(out CenturionSystems systems))
        {
            systems = __instance.gameObject.AddComponent<CenturionSystems>();
        }

        // BayCookoff registers its damage marker in its Awake, so its place among the adds sets the marker's index, which
        // must be the same on every peer: keep it last, as every peer adds them here in this order.
        systems.Aircraft = __instance;
        systems.Telescope = __instance.GetComponent<TelescopeController>();
        systems.Owner = AddIfMissing<OwnerState>(__instance);
        systems.Radar = AddIfMissing<RadarSuite>(__instance);
        systems.Beam = AddIfMissing<AwacsBeam>(__instance);
        systems.Cram = AddIfMissing<CramGuard>(__instance);
        AddIfMissing<FanSpin>(__instance);
        AddIfMissing<CabinEngineSound>(__instance);
        AddIfMissing<CockpitLevers>(__instance);
#if CENTURION_DEV
        AddIfMissing<CenturionAi>(__instance);
#endif
        AddIfMissing<BayCookoff>(__instance);
        SurfaceRules.Register(__instance);
        Live[__instance] = systems;
    }

    static T AddIfMissing<T>(Aircraft aircraft) where T : MonoBehaviour =>
        aircraft.TryGetComponent(out T existing) ? existing : aircraft.gameObject.AddComponent<T>();

    void OnDestroy()
    {
        Live.Remove(Aircraft);
        SurfaceRules.Forget(Aircraft);
    }
}
