using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx;
using BepInEx.Bootstrap;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;
using Object = UnityEngine.Object;

namespace Centurion;

/// <summary>
/// Offers each <see cref="PackBayRecipes"/> rack on its bay when the weapon pack it comes from is installed, and nothing at
/// all when it is not: no mount, no key, no index, no asset. Once Blueprinter is Ready (its bundles registered and every
/// op applied, Blueprinter Plugin.cs:662) and each installed pack has finished its own startup, the pack's mount is looked
/// up by its exact key in Encyclopedia.WeaponLookup; a rack is built from it in memory and published the way Blueprinter
/// publishes a bundle's mounts (EncyclopediaLoader.Load: appended to weaponMounts, WeaponLookup and IndexLookup with its
/// LookupIndex, in ordinal key order), then added to its bay's weaponOptions as OpAddWeaponToHardpoint does.
/// The rack is the pack's own carried store, cloned into the recipe's grid. Each clone keeps the store's stock
/// MountedMissile and the pack's WeaponInfo, as the Centurion's own racks keep the stock bomb's (CenturionAuthor
/// AuthorBombMount), so the station, name, guidance, cost and mass per round are the pack's; only its place, priority and
/// downward rail are the recipe's, and it opens the hardpoint's doors (no doors or rotary of its own). Mass is the stock
/// sum of massPerRound over the stores (MountedMissile.AttachToHardpoint).
/// Appending after every existing entry leaves each other definition's network index as it was. Two peers agree on the
/// racks' indices only when they hold the same packs, which Blueprinter's version string already requires of a lobby join
/// (VersionGetterPatch adds every bundle's name and version to Application.version; SteamLobby.TryJoinLobby refuses a
/// mismatch, SteamLobby.cs:733).
/// </summary>
static class PackBayMounts
{
    const string BlueprinterGuid = "com.nikkorap.blueprinter";

    /// <summary>
    /// The plugin that makes a pack installed, by recipe pack. A donor key alone is not enough: the PAB-125HD's is the game's
    /// own mount, shipped disabled, which Meridian Works switches on (its StockRevival).
    /// </summary>
    static readonly Dictionary<string, string> PackGuids = new()
    {
        [PackBayRecipes.Aryx] = "AryxWeaponryExpansion",
        [PackBayRecipes.Meridian] = "com.meridianworks",
    };

    /// <summary>
    /// The shortest bomb interval a rack keeps. <see cref="BombRelease"/> releases one store from each bay per step at the
    /// bomb's own interval, and a client's releases are limited to 15 commands a second (Aircraft.cs:2835): the PAB-125HD's
    /// 0.10 s would ask for 20, at 0.15 s two bays ask for 13.3.
    /// </summary>
    const float MinBombInterval = 0.15f;

    /// <summary>True once this boot's racks are published or there are none to publish; <see cref="StartupHold"/> waits on it.</summary>
    internal static bool Done { get; private set; }

    static readonly AccessTools.FieldRef<MountedMissile, MountedMissile.RailDirection>? RailDirection = Field<MountedMissile.RailDirection>("railDirection");
    static readonly AccessTools.FieldRef<MountedMissile, float>? RailLength = Field<float>("railLength");
    static readonly AccessTools.FieldRef<MountedMissile, float>? RailSpeed = Field<float>("railSpeed");
    static readonly AccessTools.FieldRef<MountedMissile, float>? RailDelay = Field<float>("railDelay");
    static readonly AccessTools.FieldRef<MountedMissile, BayDoor[]>? BayDoors = Field<BayDoor[]>("bayDoors");
    static readonly AccessTools.FieldRef<MountedMissile, Transform>? RotaryTransform = Field<Transform>("rotaryTransform");
    static readonly AccessTools.FieldRef<WeaponMount, bool>? EventContent =
        AccessTools.Field(typeof(WeaponMount), "isEventContent") == null ? null : AccessTools.FieldRefAccess<WeaponMount, bool>("isEventContent");

    /// <summary>Inactive and kept across scenes: the racks' prefabs live under it, so nothing in them runs until a hardpoint spawns a copy.</summary>
    static GameObject? holder;

    static readonly HashSet<WeaponMount> Published = new();

    /// <summary>One slowed copy per pack bomb, shared by both bays so they stay one station.</summary>
    static readonly Dictionary<WeaponInfo, WeaponInfo> Slowed = new();

    /// <summary>Whether a mount is one of this boot's pack racks (<see cref="BayLoadoutRule"/>).</summary>
    internal static bool IsPackRack(WeaponMount? mount) => mount != null && Published.Contains(mount);

    static AccessTools.FieldRef<MountedMissile, T>? Field<T>(string name) =>
        AccessTools.Field(typeof(MountedMissile), name) == null ? null : AccessTools.FieldRefAccess<MountedMissile, T>(name);

    /// <summary>
    /// Called every frame until <see cref="Done"/>. Waits for Blueprinter and for every installed pack's startup; a pack still
    /// starting when a mission begins skips every pack's racks for this boot: racks published ahead of that pack's late
    /// indexing would move its network indices.
    /// </summary>
    internal static void Update()
    {
        if (Done)
        {
            return;
        }

        if (!Chainloader.PluginInfos.TryGetValue(BlueprinterGuid, out var blueprinter))
        {
            Done = true;
            return;
        }

        string? state = blueprinter.Instance?.GetType().Assembly.GetType("Blueprinter.Api")?.GetProperty("CurrentState")?.GetValue(null)?.ToString();
        if (state is not null and not "Ready" and not "Failed")
        {
            return;
        }

        if (state != "Ready")
        {
            Done = true;
            CenturionPlugin.Log.Warning($"pack racks: none offered, Blueprinter's state is {state ?? "unreadable (no Blueprinter.Api.CurrentState)"}");
            return;
        }

        var ready = new Dictionary<string, bool?>();
        foreach (var pack in PackGuids)
        {
            ready[pack.Key] = Chainloader.PluginInfos.TryGetValue(pack.Value, out PluginInfo plugin) ? PackReady(plugin) : null;
        }

        if (ready.Values.Any(r => r == false))
        {
            if (MissionManager.IsRunning)
            {
                Done = true;
                CenturionPlugin.Log.Warning("pack racks: none offered, a pack was still starting when the first mission began");
            }

            return;
        }

        Done = true;
        try
        {
            Publish(ready);
        }
        catch (Exception e)
        {
            CenturionPlugin.Log.Error($"pack racks: none offered: {e}");
        }
    }

    /// <summary>
    /// True once an installed pack's own startup has finished, false while it runs, null when it failed or cannot be read.
    /// Aryx registers everything through Blueprinter. Meridian Works registers and indexes its mounts, switches the PAB-125HD
    /// on and applies its event gate from a StartupRunner that tries every 2 s and disables itself after its one pass, or
    /// after 120 tries; that pass found its mounts when EncyclopediaRegistration.ResolvedMounts is not empty
    /// (Meridian Works 1.3.0.0, StartupRunner.Update).
    /// </summary>
    static bool? PackReady(PluginInfo plugin)
    {
        if (plugin.Metadata.GUID != PackGuids[PackBayRecipes.Meridian])
        {
            return true;
        }

        Assembly? meridian = plugin.Instance?.GetType().Assembly;
        Type? runner = meridian?.GetType("MeridianWorks.StartupRunner");
        var mounts = meridian?.GetType("MeridianWorks.EncyclopediaRegistration")
            ?.GetProperty("ResolvedMounts", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null) as ICollection;
        if (runner == null || mounts == null)
        {
            return null;
        }

        if (Resources.FindObjectsOfTypeAll(runner).Any(o => o is Behaviour { enabled: true }))
        {
            return false;
        }

        return mounts.Count > 0 ? true : null;
    }

    static void Publish(Dictionary<string, bool?> ready)
    {
        if (RailDirection == null || RailLength == null || RailSpeed == null || RailDelay == null || BayDoors == null || RotaryTransform == null)
        {
            CenturionPlugin.Log.Warning("pack racks: none offered, MountedMissile has no rail, door or rotary fields to set");
            return;
        }

        Encyclopedia encyclopedia = Encyclopedia.i;
        if (!Encyclopedia.Lookup.TryGetValue(CenturionPlugin.JsonKey, out UnitDefinition definition) || definition.unitPrefab == null
            || definition.unitPrefab.GetComponent<Aircraft>() is not { } centurion)
        {
            CenturionPlugin.Log.Warning("pack racks: none offered, the Centurion is not in the encyclopedia");
            return;
        }

        HardpointSet[] sets = centurion.weaponManager.hardpointSets;
        var built = new List<(PackBayRecipe Recipe, WeaponMount Mount)>();
        foreach (IGrouping<string, PackBayRecipe> pack in PackBayRecipes.All.OrderBy(r => r.Key, StringComparer.Ordinal).GroupBy(r => r.Pack))
        {
            bool installed = Chainloader.PluginInfos.ContainsKey(PackGuids[pack.Key]);
            if (!installed || ready[pack.Key] != true)
            {
                string why = !installed ? "not installed" : "startup did not finish (see its log)";
                string line = $"pack racks: {pack.Key} {why}; racks not offered: {pack.Count()}";
                if (installed) CenturionPlugin.Log.Warning(line);
                else CenturionPlugin.Log.Info(line);
                continue;
            }

            foreach (PackBayRecipe recipe in pack)
            {
                if (!Encyclopedia.WeaponLookup.TryGetValue(recipe.DonorKey, out WeaponMount donor) || !donor.IsAllowed(includeEventContent: true))
                {
                    CenturionPlugin.Log.Warning($"pack racks: {recipe.Key} not offered, {pack.Key} has no enabled {recipe.DonorKey}");
                }
                else if (Build(recipe, donor) is { } mount)
                {
                    built.Add((recipe, mount));
                }
            }
        }

        foreach ((PackBayRecipe recipe, WeaponMount mount) in built)
        {
            encyclopedia.weaponMounts.Add(mount);
            Encyclopedia.WeaponLookup.Add(mount.jsonKey, mount);
            ((INetworkDefinition)mount).LookupIndex = encyclopedia.IndexLookup.Count;
            encyclopedia.IndexLookup.Add(mount);
            sets[recipe.Bay].weaponOptions.Add(mount);
            Published.Add(mount);
            CenturionPlugin.Log.Info(Invariant($"pack racks: {mount.jsonKey} offered on {sets[recipe.Bay].name}: {mount.mountName}, {mount.mass:0} kg, from {recipe.DonorKey}, index {((INetworkDefinition)mount).LookupIndex}"));
        }
    }

    /// <summary>The rack, or null (with a warning) when the pack's mount is not the one the recipe was measured from.</summary>
    static WeaponMount? Build(PackBayRecipe recipe, WeaponMount donor)
    {
        MountedMissile? template = donor.prefab != null ? donor.prefab.GetComponentsInChildren<MountedMissile>(true).FirstOrDefault() : null;
        WeaponInfo? info = template != null ? template.info : null;
        Missile? missile = info != null && info.weaponPrefab != null ? info.weaponPrefab.GetComponent<Missile>() : null;
        if (template == null || info == null || missile == null || missile.definition == null || missile.definition.jsonKey != recipe.ProjectileKey)
        {
            CenturionPlugin.Log.Warning($"pack racks: {recipe.Key} not offered, {recipe.DonorKey} no longer carries {recipe.ProjectileKey}");
            return null;
        }

        if (recipe.Event && EventContent == null)
        {
            CenturionPlugin.Log.Warning($"pack racks: {recipe.Key} not offered, WeaponMount has no isEventContent field");
            return null;
        }

        // Pack meshes load unreadable, so the runtime box is the corners of each mesh's bounds: it holds the measured vertex
        // box and exceeds it only where a part is turned (Meridian's fins, the Black Arrow's 0.03 m the most).
        Quaternion turn = Quaternion.Inverse(donor.prefab!.transform.rotation) * template.transform.rotation;
        Bounds box = StoreBox(template.transform, donor.prefab.transform);
        var lo = new Vector3(recipe.StoreBox[0], recipe.StoreBox[1], recipe.StoreBox[2]);
        var hi = new Vector3(recipe.StoreBox[3], recipe.StoreBox[4], recipe.StoreBox[5]);
        Vector3 below = lo - box.min, above = box.max - hi;
        if (Quaternion.Angle(turn, Quaternion.identity) > 0.5f || Mathf.Min(below.x, below.y, below.z, above.x, above.y, above.z) < -0.002f
            || Mathf.Max(below.x, below.y, below.z, above.x, above.y, above.z) > 0.04f)
        {
            CenturionPlugin.Log.Warning(Invariant($"pack racks: {recipe.Key} not offered, {recipe.DonorKey}'s store spans {box.min} to {box.max} m turned {Quaternion.Angle(turn, Quaternion.identity):0.0} deg, measured {lo} to {hi} m level"));
            return null;
        }

        WeaponInfo flight = info;
        if ((info.bomb || info.glideBomb) && info.fireInterval < MinBombInterval && !Slowed.TryGetValue(info, out flight))
        {
            flight = Slowed[info] = Object.Instantiate(info);
            flight.name = info.name;
            flight.fireInterval = MinBombInterval;
        }

        if (holder == null)
        {
            holder = new GameObject("Centurion pack racks");
            holder.SetActive(false);
            Object.DontDestroyOnLoad(holder);
        }

        var root = new GameObject(recipe.Key);
        root.transform.SetParent(holder.transform, false);
        Vector3 centre = (lo + hi) * 0.5f;
        foreach (PackBaySlot slot in PackBayRecipes.Slots(recipe))
        {
            GameObject store = Object.Instantiate(template.gameObject, root.transform, false);
            store.name = $"store_{slot.Layer}_{slot.Row}_{slot.Column}";
            store.transform.localRotation = Quaternion.identity;
            store.transform.localPosition = new Vector3(slot.X, slot.Y, slot.Z) - centre;
            MountedMissile weapon = store.GetComponent<MountedMissile>();
            weapon.info = flight;
            weapon.ammo = 1;
            weapon.priority = slot.Priority;
            RailDirection!(weapon) = MountedMissile.RailDirection.Down;
            RailLength!(weapon) = slot.Rail;
            RailSpeed!(weapon) = PackBayRecipes.RailSpeed;
            RailDelay!(weapon) = PackBayRecipes.RailDelay;
            BayDoors!(weapon) = Array.Empty<BayDoor>();
            RotaryTransform!(weapon) = null!;
        }

        var mount = ScriptableObject.CreateInstance<WeaponMount>();
        mount.name = recipe.Key;
        mount.jsonKey = recipe.Key;
        mount.prefab = root;
        mount.info = flight;
        mount.ammo = recipe.Rounds;
        // The game's event content flag offers the rack only where the mission allows event content (WeaponMount.IsAllowed);
        // the name follows the LEGACY racks' "LEGACY: ..." with EVENT.
        mount.mountName = $"{(recipe.Event ? "EVENT: " : "")}{info.weaponName} x{recipe.Rounds}";
        if (recipe.Event) EventContent!(mount) = true;
        // The prefab is inactive, so Initialize counts no stores and keeps the ammo, name and info set here; it sets the mass.
        mount.Initialize();
        int stores = root.GetComponentsInChildren<MountedMissile>(true).Length;
        if (stores != recipe.Rounds || mount.ammo != recipe.Rounds || Mathf.Abs(mount.mass - flight.massPerRound * recipe.Rounds) > 0.5f)
        {
            CenturionPlugin.Log.Warning(Invariant($"pack racks: {recipe.Key} not offered, built {stores} stores, ammo {mount.ammo}, {mount.mass:0} kg for {recipe.Rounds}"));
            Object.Destroy(root);
            Object.Destroy(mount);
            return null;
        }

        return mount;
    }

    /// <summary>
    /// The box of the store's meshes about its origin, in metres of the mount's frame, from the corners of each mesh's
    /// bounds. Measured in the mount's frame rather than the store's own, so a store carried at a scale (the PAB-3000LR's
    /// 0.7) reads at the size it is drawn; its clone keeps that scale under the rack's unscaled root.
    /// </summary>
    static Bounds StoreBox(Transform store, Transform mount)
    {
        Vector3 origin = mount.InverseTransformPoint(store.position);
        Bounds box = default;
        bool first = true;
        foreach (MeshFilter filter in store.GetComponentsInChildren<MeshFilter>())
        {
            if (filter.sharedMesh == null) continue;
            Bounds local = filter.sharedMesh.bounds;
            for (int corner = 0; corner < 8; corner++)
            {
                Vector3 point = local.center + Vector3.Scale(local.extents, new Vector3((corner & 1) == 0 ? -1 : 1, (corner & 2) == 0 ? -1 : 1, (corner & 4) == 0 ? -1 : 1));
                point = mount.InverseTransformPoint(filter.transform.TransformPoint(point)) - origin;
                if (first) box = new Bounds(point, Vector3.zero);
                else box.Encapsulate(point);
                first = false;
            }
        }

        return box;
    }
}
