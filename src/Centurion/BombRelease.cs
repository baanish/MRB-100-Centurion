using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Both bays release together when they hold the same bomb, each bay keeping the bomb's own fireInterval as its cooldown.
/// Stock pools the two racks into one WeaponStation (one per WeaponInfo, WeaponManager.cs:404-439) and releases one store
/// per WeaponManager.Fire, gated by that station's single interval (WeaponStation.Ready, WeaponStation.cs:114-121; Fire,
/// WeaponManager.cs:560-588): a held trigger ripples PAB-250s at 0.15 s, the next frame after it (0.17 s at 60 fps).
/// Here a release step takes the next store and, when it sits in the other bay, the one after it too, but only for a held
/// trigger (Fire called on consecutive frames, PilotPlayerState.cs:182-185, for at least one interval) or a salvo on two or
/// more targets (stock SalvoFire's one store per target, WeaponManager.cs:578-610, taken two targets a step). A press shorter
/// than one interval on one target still releases one store, and the AI's single-target drop (one Fire every 4 s,
/// AIPilotCombatModes.cs:647-652) stays stock.
/// Every release is still the stock LaunchMount, which each peer replays as "the station's next store" (RpcLaunchMissile,
/// Aircraft.cs:2593-2615), so the station's stores are reordered to alternate bays on every peer as the loadout spawns
/// (SortWeapons runs there on each, WeaponManager.cs:454-463), each bay keeping its stock lower-layers-first order.
/// A client sends one CmdLaunchMissile per store, rate-limited to 15 a second with a 45 burst and an error penalty
/// (Aircraft.cs:2835). Two PAB-250s per 0.17 s step is 12 a second, so each bay keeps the bomb's own interval: a shorter
/// one with both bays releasing would outrun the limit and lose releases on the server.
/// </summary>
static class BombRelease
{
    const string CenturionKey = "baanish_centurion";
    // Stock spaces a salvo's releases this many fireIntervals apart (WeaponManager.cs:581).
    const float SalvoSpacing = 1.1f;

    static readonly AccessTools.FieldRef<WeaponStation, int>? WeaponIndex =
        AccessTools.Field(typeof(WeaponStation), "weaponIndex") == null ? null : AccessTools.FieldRefAccess<WeaponStation, int>("weaponIndex");
    static readonly AccessTools.FieldRef<Weapon, Hardpoint>? HardpointOf =
        AccessTools.Field(typeof(Weapon), "hardpoint") == null ? null : AccessTools.FieldRefAccess<Weapon, Hardpoint>("hardpoint");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("bomb-release", typeof(WeaponStation), nameof(WeaponStation.SortWeapons),
            postfix: AccessTools.Method(typeof(BombRelease), nameof(AfterSortWeapons))),
        new("bomb-release", typeof(WeaponManager), nameof(WeaponManager.Fire),
            prefix: AccessTools.Method(typeof(BombRelease), nameof(BeforeFire))),
    };

    sealed class Trigger
    {
        public int LastFrame = int.MinValue;
        public float PressedAt;
        public WeaponStation? Station;
    }

    static readonly ConditionalWeakTable<WeaponManager, Trigger> Triggers = new();

    /// <summary>The stores left in the aircraft's bomb stations as this peer has them, for comparing an owner with its copies.</summary>
    internal static int BayBombAmmo(Aircraft aircraft) => aircraft.weaponStations.Where(s => IsBayBomb(aircraft, s)).Sum(s => s.Ammo);

    static bool IsBayBomb(Aircraft aircraft, WeaponStation station) =>
        aircraft != null && aircraft.definition != null && aircraft.definition.jsonKey == CenturionKey
        && station.WeaponInfo != null && (station.WeaponInfo.bomb || station.WeaponInfo.glideBomb);

    /// <summary>The bays' stores, each bay in its stock order, taken one from each bay in turn.</summary>
    static void AfterSortWeapons(WeaponStation __instance, Aircraft aircraft)
    {
        if (CenturionPlugin.FeaturesOff.Contains("bomb-release")) return;
        if (HardpointOf == null || !IsBayBomb(aircraft, __instance))
        {
            return;
        }

        List<List<Weapon>> bays = __instance.Weapons.GroupBy(w => HardpointOf(w)).Select(g => g.ToList()).ToList();
        if (bays.Count < 2)
        {
            return;
        }

        int total = __instance.Weapons.Count;
        __instance.Weapons.Clear();
        for (int i = 0; __instance.Weapons.Count < total; i++)
        {
            foreach (List<Weapon> bay in bays.Where(b => i < b.Count))
            {
                __instance.Weapons.Add(bay[i]);
            }
        }

        CenturionPlugin.Log.Info(Invariant($"bomb release on {aircraft.name}: {__instance.WeaponInfo.weaponName} from {bays.Count} bays ({string.Join(" + ", bays.Select(b => b.Count))}), alternating"));
    }

    static bool BeforeFire(WeaponManager __instance, Aircraft ___aircraft, List<Unit> ___targetList)
    {
        if (CenturionPlugin.FeaturesOff.Contains("bomb-release")) return true;
        WeaponStation station = __instance.currentWeaponStation;
        if (station == null || WeaponIndex == null || HardpointOf == null || !IsBayBomb(___aircraft, station))
        {
            return true;
        }

        bool held = Held(__instance, station);
        // Stock's own gates (WeaponManager.cs:562, 572); anything they stop, stock stops too.
        if (station.SafetyIsOn(___aircraft) || ___aircraft.remoteSim || !station.Ready() || station.SalvoInProgress)
        {
            return true;
        }

        if (___targetList.Count > 1)
        {
            station.SalvoInProgress = true;
            __instance.StartCoroutine(PairedSalvo(___aircraft, station, ___targetList.ToList()));
            return false;
        }

        if (!held)
        {
            return true;
        }

        Unit? target = ___targetList.Count == 0 ? null : ___targetList[0];
        GlobalPosition aimpoint = ___aircraft.GlobalPosition() + ___aircraft.transform.forward * 50000f;
        station.LaunchMount(___aircraft, target, aimpoint);
        bool pair = NextStoreInOtherBay(station);
        if (pair)
        {
            station.LaunchMount(___aircraft, target, aimpoint);
        }

        CenturionPlugin.Log.Stage("bomb-ripple", Invariant($"{___aircraft.name}: trigger held, {(pair ? 2 : 1)} {station.WeaponInfo.weaponName}, {station.Ammo} left"));
        return false;
    }

    /// <summary>
    /// Counts this Fire call into the current press and says whether the trigger has been held for one interval. The player's
    /// trigger calls Fire every frame it is down; a gap of a frame, or another station, starts a new press.
    /// </summary>
    static bool Held(WeaponManager manager, WeaponStation station)
    {
        Trigger trigger = Triggers.GetOrCreateValue(manager);
        float now = Time.timeSinceLevelLoad;
        if (Time.frameCount - trigger.LastFrame > 1 || trigger.Station != station)
        {
            trigger.PressedAt = now;
            trigger.Station = station;
        }

        trigger.LastFrame = Time.frameCount;
        return now - trigger.PressedAt >= station.WeaponInfo.fireInterval;
    }

    /// <summary>Whether the station's next store is in another bay than the one it just released.</summary>
    static bool NextStoreInOtherBay(WeaponStation station)
    {
        int next = WeaponIndex!(station);
        return next > 0 && next < station.Weapons.Count && HardpointOf!(station.Weapons[next]) != HardpointOf(station.Weapons[next - 1]);
    }

    /// <summary>
    /// Stock SalvoFire (WeaponManager.cs:590-610) with up to two targets a step, one store each from different bays: a target
    /// gone or disabled is skipped as stock skips it, and a step whose next store is in the same bay releases one.
    /// </summary>
    static IEnumerator PairedSalvo(Aircraft aircraft, WeaponStation station, List<Unit> targets)
    {
        var interval = new WaitForSeconds(station.WeaponInfo.fireInterval * SalvoSpacing);
        int i = 0;
        while (i < targets.Count)
        {
            int released = 0;
            while (i < targets.Count && (released == 0 || released == 1 && NextStoreInOtherBay(station)))
            {
                Unit unit = targets[i++];
                if (unit != null && !unit.disabled)
                {
                    station.LaunchMount(aircraft, unit, default);
                    released++;
                }
            }

            CenturionPlugin.Log.Stage("bomb-salvo", Invariant($"{aircraft.name}: salvo step, {released} {station.WeaponInfo.weaponName} on {released} targets, {targets.Count - i} targets to go"));
            yield return interval;
        }

        station.SalvoInProgress = false;
    }
}
