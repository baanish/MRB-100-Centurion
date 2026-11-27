using System.Collections.Generic;
using System.Runtime.CompilerServices;
using HarmonyLib;
using NuclearOption.SavedMission;
using UnityEngine;
#if CENTURION_DEV
using System.Linq;
using NuclearOption.Networking;
using static System.FormattableString;
#endif

namespace Centurion;

static class AiSamLoadout
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-sam-loadout", typeof(AircraftParameters), nameof(AircraftParameters.GetRandomStandardLoadout),
            postfix: AccessTools.Method(typeof(AiSamLoadout), nameof(AfterStandardDraw))),
    };

    // Only the HQ deploy loop calls the standard picker. Saved aircraft and the player never pass through it.
    [HarmonyAfter("com.meridianworks")]
    static void AfterStandardDraw(AircraftParameters __instance, AircraftDefinition definition, FactionHQ hq, ref StandardLoadout? __result)
    {
        if (!CenturionSystems.IsCenturion(definition)) return;
        int livingSams = FindHostileSams(hq, out Unit? sam, out WeaponInfo? samWeapon);
        string policy = "stock";
        if (__result != null && livingSams > 0)
        {
            if (IsAwacs(__result)) policy = "awacs";
            else if (IsStrikeMissile(__result)) policy = "missiles";
            else
            {
                WeaponManager manager = definition.unitPrefab.GetComponent<Aircraft>().weaponManager;
                var missiles = new List<StandardLoadout>();
                foreach (StandardLoadout candidate in __instance.StandardLoadouts)
                {
                    if (!candidate.disabled && !IsAwacs(candidate) && IsStrikeMissile(candidate) && candidate.AllowedByHQ(manager, hq))
                        missiles.Add(candidate);
                }
                // Leaving a stock AWACS draw alone preserves its share of the original legal pool (normally 1 in 8).
                // Returning null would trigger an unrestricted per-bay draw in the hangar.
                if (missiles.Count == 0) policy = "no legal missile";
                else
                {
                    __result = missiles[Random.Range(0, missiles.Count)];
                    policy = "missiles";
                }
            }
        }
#if CENTURION_DEV
        Draw draw = RecordDraw(hq, sam, samWeapon, livingSams, policy, __result);
#else
        var draw = new Draw(policy, "");
        if (!draw.Restricted) return;
#endif
        if (__result == null) return;
        // The shared stock preset cannot carry the draw through the hangar queue.
        var loadout = new Loadout();
        loadout.weapons.AddRange(__result.loadout.weapons);
        Draws.Add(loadout, draw);
        __result = new StandardLoadout { Name = __result.Name, FuelRatio = __result.FuelRatio, loadout = loadout };
    }

    static bool IsAwacs(StandardLoadout preset) =>
        preset.loadout.weapons.Count > 2 && preset.loadout.weapons[2]?.jsonKey == AwacsBeam.AwacsKey;

    static bool IsStrikeMissile(StandardLoadout preset)
    {
        bool missile = false;
        for (int i = 0; i < 2 && i < preset.loadout.weapons.Count; i++)
        {
            WeaponMount mount = preset.loadout.weapons[i];
            if (mount == null || mount.info == null) continue;
            WeaponInfo weapon = mount.info;
            if (weapon.bomb || weapon.glideBomb) return false;
            missile |= weapon.missile && (weapon.effectiveness.antiSurface > 0f || weapon.effectiveness.antiRadar > 0f);
        }
        return missile;
    }

    static int FindHostileSams(FactionHQ hq, out Unit? sam, out WeaponInfo? samWeapon)
    {
        int living = 0;
        sam = null;
        samWeapon = null;
        // The loadout draw deliberately knows about launchers its HQ has never seen.
        // Otherwise the first bombers can learn a launcher exists by being shot down by it.
        foreach (Unit unit in UnitRegistry.allUnits)
        {
            if (unit == null || unit.NetworkHQ == hq) continue;
            WeaponInfo? weapon = LongRangeSamWeapon(unit);
            if (weapon == null) continue;
            living++;
            if (samWeapon != null && weapon.targetRequirements.maxRange <= samWeapon.targetRequirements.maxRange) continue;
            sam = unit;
            samWeapon = weapon;
        }
        return living;
    }

    static WeaponInfo? LongRangeSamWeapon(Unit unit)
    {
        if (!SamReach.IsLivingSurfaceUnit(unit.disabled, unit.NetworkHQ != null,
            unit is not (Aircraft or Missile) && unit.definition.typeIdentity.surface > 0f)) return null;
        WeaponInfo? longest = null;
        foreach (WeaponStation station in unit.weaponStations)
        {
            if (station == null || station.WeaponInfo == null) continue;
            WeaponInfo weapon = station.WeaponInfo;
            float range = weapon.targetRequirements.maxRange;
            if (!SamReach.IsLongRange(weapon.missile && !weapon.bomb && !weapon.glideBomb,
                weapon.effectiveness.antiAir, range, weapon.targetRequirements.maxAltitude)) continue;
            if (longest == null || range > longest.targetRequirements.maxRange) longest = weapon;
        }
        return longest;
    }

    sealed class Draw
    {
        internal Draw(string policy, string threat) { Policy = policy; Threat = threat; }
        internal string Policy { get; }
        internal string Threat { get; }
        internal bool Restricted => Policy == "missiles";
    }

    static readonly ConditionalWeakTable<Loadout, Draw> Draws = new();

    internal static bool WasRestricted(Aircraft aircraft) =>
        aircraft.loadout != null && Draws.TryGetValue(aircraft.loadout, out Draw draw) && draw.Restricted;

    internal static bool LauncherReachesClimb(FactionHQ hq, GlobalPosition home)
    {
        foreach (Unit unit in UnitRegistry.allUnits)
        {
            if (unit == null || unit.NetworkHQ == hq || LongRangeSamWeapon(unit) is not { } weapon) continue;
            GlobalPosition launcher = unit.GlobalPosition();
            if (SamReach.CoversClimbColumn(AwacsOrbit.LevelDistance(home, launcher), launcher.y, home.y,
                    weapon.targetRequirements.maxRange)) return true;
        }
        return false;
    }

#if CENTURION_DEV
    static Mission? mission;
    static int draws, restricted, bombDraws, awacsDraws, noThreatDraws, trackedDraws, lastLivingSams;
    static float nextInventoryAt;
    static string inventory = AircraftReadout.NoText;
    static string lastPolicy = AircraftReadout.NoText, lastThreat = AircraftReadout.NoText;

    static void ResetMission()
    {
        if (ReferenceEquals(mission, MissionManager.CurrentMission)) return;
        mission = MissionManager.CurrentMission;
        draws = restricted = bombDraws = awacsDraws = noThreatDraws = trackedDraws = lastLivingSams = 0;
        nextInventoryAt = 0f;
        inventory = AircraftReadout.NoText;
        lastPolicy = lastThreat = AircraftReadout.NoText;
    }

    static Draw RecordDraw(FactionHQ hq, Unit? sam, WeaponInfo? weapon, int livingSams, string policy, StandardLoadout? preset)
    {
        ResetMission();
        string threat = sam != null && weapon != null
            ? Invariant($"{sam.definition.unitName} ({sam.definition.jsonKey}, id {sam.persistentID}), {weapon.weaponName}, {weapon.targetRequirements.maxRange / 1852f:0.0} nmi [{weapon.targetRequirements.maxRange / 1000f:0.0} km]")
            : AircraftReadout.NoText;
        var draw = new Draw(policy, threat);
        draws++;
        if (draw.Restricted) restricted++;
        if (sam == null) noThreatDraws++;
        foreach (TrackingInfo track in hq.trackingDatabase.Values)
        {
            if (!track.TryGetUnit(out Unit unit) || unit == null || unit.NetworkHQ == hq || LongRangeSamWeapon(unit) == null)
                continue;
            trackedDraws++;
            break;
        }
        lastLivingSams = livingSams;
        lastPolicy = policy;
        lastThreat = threat;
        if (SortieLog.Enabled.Value)
            SortieLog.LoadoutDraw(hq, preset?.Name ?? AircraftReadout.NoText, Describe(draw), livingSams);
        if (preset == null) return draw;
        if (IsAwacs(preset)) awacsDraws++;
        else if (preset.loadout.weapons.Exists(mount => mount != null && mount.info != null && (mount.info.bomb || mount.info.glideBomb)))
            bombDraws++;

        return draw;
    }

    static string Describe(Draw draw) => $"SAM draw {draw.Policy}, restricted {(draw.Restricted ? "yes" : "no")}, threat {draw.Threat}";

    internal static string Describe(Aircraft aircraft) =>
        aircraft.loadout != null && Draws.TryGetValue(aircraft.loadout, out Draw draw) ? Describe(draw) : "no HQ draw";

    internal static void LogInventory()
    {
        if (!SortieLog.Enabled.Value || !MissionManager.IsRunning || !NetworkManagerNuclearOption.i.Server.Active) return;
        ResetMission();
        float now = Time.timeSinceLevelLoad;
        if (now < nextInventoryAt) return;
        nextInventoryAt = now + 1f;

        var counts = new SortedDictionary<string, int>(System.StringComparer.Ordinal);
        foreach (FactionHQ hq in FactionRegistry.GetAllHQs()) counts[hq.faction.factionName] = 0;
        foreach (Unit unit in UnitRegistry.allUnits)
        {
            if (unit == null || LongRangeSamWeapon(unit) == null) continue;
            string faction = unit.NetworkHQ.faction.factionName;
            counts.TryGetValue(faction, out int count);
            counts[faction] = count + 1;
        }
        string current = string.Join(", ", counts.Select(pair => $"{pair.Key} {pair.Value}"));
        if (current == inventory) return;
        inventory = current;
        SortieLog.SamInventory(inventory);
    }

    internal static void Read(Dictionary<string, object> state, Aircraft? aircraft)
    {
        ResetMission();
        state["ai_sam_draws"] = draws;
        state["ai_sam_restricted_draws"] = restricted;
        state["ai_sam_bomb_draws"] = bombDraws;
        state["ai_sam_awacs_draws"] = awacsDraws;
        state["ai_sam_no_threat_draws"] = noThreatDraws;
        state["ai_sam_tracked_draws"] = trackedDraws;
        state["ai_sam_last_enemy_alive"] = lastLivingSams;
        state["ai_sam_inventory"] = inventory;
        state["ai_sam_last_policy"] = lastPolicy;
        state["ai_sam_last_threat"] = lastThreat;
        state["ai_sam_sortie_draw"] = aircraft != null ? Describe(aircraft) : AircraftReadout.NoText;
    }
#endif
}
