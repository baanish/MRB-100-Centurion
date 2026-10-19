using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using HarmonyLib;
using NuclearOption.Networking;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Weapon bay cook-off (owner, 2026-10-19; docs/SPEC.md "Damage"; numbers in <see cref="BayCookoffRule"/>). The server
/// watches each bay's host part, fuselage_F forward and fuselage_R aft (the part the bay hardpoint sits on, which also holds
/// a fuel tank): once that tank has burned 5 s with a conventional store aboard, the bay goes off in one blast. Stock never
/// detonates a carried store from damage (MountedMissile is not IDamageable, Hardpoint.cs:46), so the bay is this mod's.
/// The server tells every peer through the SubmunitionDispenser pattern (SubmunitionDispenser.cs:46, 176): a damage marker
/// registered on the aircraft, hit with Unit.Damage, which reaches every observer as the reliable Unit.RpcDamage
/// (Unit.cs:1352-1392) and lands in <see cref="Marker.ApplyDamage"/>. Every peer then empties the bay without firing and
/// plays the blast; the server then detaches the bay host through the stock break path (Unit.DetachPart, RpcBreakPart,
/// Unit.cs:1437-1447), which follows the marker on the same reliable channel. BayCookoffRule.EffectName picks a stock
/// blast by yield, with its Shockwave set to that yield, whose overpressure damages every part nearby on the server
/// (Shockwave.cs:37), neighbours and the Centurion itself included; at or under 200 kg it is stock
/// fragmentation instead, as a stock warhead's is. Stock RPCs never reach a peer that joins later, so the server sends each
/// spent bay again as a state-only marker 5 s and 30 s after a new player appears: that peer empties the bay and detaches
/// its host with no blast, and every other peer already has it.
/// The marker's index must match on every peer: it registers here, from CenturionSystems' SetLocalSim postfix, after every
/// stock part has registered in its Awake and before the loadout spawns, the same point on every peer (the Centurion carries
/// no cargo, whose mounts register later). Each peer logs the index it got.
/// </summary>
sealed class BayCookoff : MonoBehaviour
{
    static readonly string[] HostNames = { "fuselage_F", "fuselage_R" };
    const float KgToKilotons = 1e-6f;
    /// <summary>DamageInfo.impactDamage carries the event: this plus the bay index for a blast, <see cref="StateCode"/> plus it
    /// for a state-only resend. Small whole numbers, so a stray hit on a wrong index would be a scratch.</summary>
    const int BlastCode = 1, StateCode = 3;
    static readonly float[] ResendDelaysS = { 5f, 30f };

    static readonly FieldInfo? OnFire = AccessTools.Field(typeof(FuelTank), "onFire");
    static readonly FieldInfo? TankPart = AccessTools.Field(typeof(FuelTank), "part");
    static readonly FieldInfo? Fired = AccessTools.Field(typeof(MountedMissile), "fired");
    static readonly MethodInfo? RemoveFromHardpoint = AccessTools.Method(typeof(MountedMissile), "RemoveFromHardpoint");
    static readonly FieldInfo? HardpointField = AccessTools.Field(typeof(Weapon), "hardpoint");
    static readonly FieldInfo? WeaponIndex = AccessTools.Field(typeof(WeaponStation), "weaponIndex");
    static readonly FieldInfo? Submunitions = AccessTools.Field(typeof(SubmunitionDispenser), "submunitions");
    static readonly FieldInfo? SubmunitionType = AccessTools.Field(typeof(SubmunitionDispenser), "submunitionType");
    static readonly Dictionary<WeaponInfo, float> Warheads = new();

    /// <summary>Blasts this peer has played, and the last one, for AgenticState().</summary>
    static int blasts;
    static float lastBlastKg = -1f;
    static string lastBlastBay = AircraftReadout.NoText;

    sealed class Bay
    {
        public readonly int Index;
        public readonly string Name;
        public readonly UnitPart Host;
        public readonly FuelTank? Tank;
        public readonly Transform BlastPoint;
        public readonly BayCookoffTimer Timer = new();
        /// <summary>This peer has emptied the bay (from a marker; on the server also once it sent the blast).</summary>
        public bool Spent;
        public bool BurnLogged, InertLogged;

        public Bay(int index, string name, UnitPart host, FuelTank? tank, Transform blastPoint)
        {
            Index = index;
            Name = name;
            Host = host;
            Tank = tank;
            BlastPoint = blastPoint;
        }
    }

    /// <summary>The damage marker: only <see cref="ApplyDamage"/>, the RPC's landing on each peer, does anything.</summary>
    sealed class Marker : IDamageable
    {
        readonly BayCookoff owner;

        public Marker(BayCookoff owner) => this.owner = owner;

        public void ApplyDamage(float pierceDamage, float blastDamage, float fireDamage, float impactDamage) =>
            owner.Receive(pierceDamage, impactDamage);

        public void TakeDamage(float pierceDamage, float blastDamage, float amountAffected, float fireDamage, float ImpactDamage, PersistentID dealerID) { }
        public void TakeShockwave(Vector3 origin, float overpressure, float blastPower) { }
        public void Detach(Vector3 velocity, Vector3 relativePos) { }
        public ArmorProperties GetArmorProperties() => owner.root.GetArmorProperties();
        public Unit GetUnit() => owner.aircraft;
        public float GetMass() => 0f;
        public Transform GetTransform() => owner.transform;
    }

    Aircraft aircraft = null!;
    UnitPart root = null!;
    Bay[] bays = new Bay[0];
    byte markerId;
    readonly HashSet<PlayerRef> players = new();
    readonly List<float> resendAt = new();
    float nextRosterAt;

    static CenturionLog Log => CenturionPlugin.Log;

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        root = GetComponent<UnitPart>();
        markerId = aircraft.RegisterDamageable(new Marker(this));
        Log.Info($"cook-off on {aircraft.name}: damage marker at index {markerId} of {aircraft.damageables.Count} ({Role})");
        if (OnFire == null || TankPart == null || Fired == null || RemoveFromHardpoint == null || HardpointField == null || WeaponIndex == null)
        {
            Log.Error("cook-off: a stock field it reads is gone (FuelTank.onFire/part, MountedMissile.fired/RemoveFromHardpoint, Weapon.hardpoint, WeaponStation.weaponIndex); bays will not cook off");
            enabled = false;
            return;
        }

        var found = new List<Bay>();
        for (int i = 0; i < HostNames.Length; i++)
        {
            UnitPart? host = aircraft.partLookup.FirstOrDefault(p => p != null && p.name == HostNames[i]);
            if (host == null)
            {
                Log.Warning($"cook-off on {aircraft.name}: no {HostNames[i]} part, that bay is off");
                continue;
            }

            FuelTank? tank = aircraft.GetFuelTanks().FirstOrDefault(t => t != null && TankPart.GetValue(t) == (object)host);
            Hardpoint? hardpoint = aircraft.weaponManager.hardpointSets.SelectMany(s => s.hardpoints).FirstOrDefault(h => h.part == host);
            var bay = new Bay(i, host.name, host, tank, hardpoint != null && hardpoint.transform != null ? hardpoint.transform : host.transform);
            host.onPartDetached += _ => Log.Info($"cook-off on {aircraft.name}: {bay.Name} detached on this peer ({Role})");
            found.Add(bay);
            if (tank == null)
            {
                Log.Warning($"cook-off on {aircraft.name}: {host.name} holds no fuel tank, that bay never cooks off");
            }
        }

        bays = found.ToArray();
    }

    string Role => aircraft.IsServer ? "server" : "client";

    void Update()
    {
        if (!aircraft.IsServer)
        {
            return;
        }

        foreach (Bay bay in bays)
        {
            bool burning = bay.Tank != null && !bay.Host.IsDetached() && (bool)OnFire!.GetValue(bay.Tank);
            if (burning && !bay.BurnLogged)
            {
                bay.BurnLogged = true;
                Log.Info(Invariant($"cook-off on {aircraft.name}: {bay.Name} tank on fire, timer started ({BayCookoffRule.BurnS:0} s)"));
            }

            if (bay.Timer.Step(burning, Time.deltaTime))
            {
                Due(bay);
            }
        }

        ResendForLateJoiners();
    }

    /// <summary>The server's check once a bay's tank has burned long enough: an inventory, then the blast if anything conventional is left.</summary>
    void Due(Bay bay)
    {
        List<MountedMissile> stores = Unspent(bay);
        var load = stores.Select(s => (WarheadKg(s.info), s.info.nuclear)).ToList();
        int conventional = BayCookoffRule.Conventional(load);
        if (conventional == 0)
        {
            if (!bay.InertLogged)
            {
                bay.InertLogged = true;
                Log.Info(Invariant($"cook-off on {aircraft.name}: {bay.Name} burned {bay.Timer.BurnedS:0.0} s with no conventional store ({Inventory(stores)}): no cook-off"));
            }

            return;
        }

        float blastKg = BayCookoffRule.BlastKg(load);
        bay.Timer.MarkSpent();
        Log.Info(Invariant($"cook-off on {aircraft.name}: {bay.Name} burned {bay.Timer.BurnedS:0.0} s; inventory {Inventory(stores)}; yield {blastKg:0.#} kg TNT"));
        var marker = new DamageInfo(blastKg * KgToKilotons, 0f, 0f, BlastCode + bay.Index);
        aircraft.Damage(markerId, marker);
        Log.Info(Invariant($"cook-off on {aircraft.name}: {bay.Name} event sent (marker {markerId}, {blastKg:0.#} kg)"));
        // A host runs the RPC here as it sends it; a dedicated server has no local client to, and its shockwave is the one
        // that does damage.
        if (!bay.Spent)
        {
            Receive(marker.pierceDamage.Decompress(), marker.impactDamage.Decompress());
        }

        // After the marker, on the same reliable channel: each peer empties the bay while its host is still attached.
        aircraft.DetachPart(bay.Host.id, aircraft.rb.velocity, bay.Host.transform.position - aircraft.transform.position);
        Log.Info($"cook-off on {aircraft.name}: {bay.Name} detach sent through the stock break path");
    }

    /// <summary>Every peer: the marker arrived. A blast plays once per bay; a state-only resend empties and detaches quietly.</summary>
    void Receive(float pierce, float impact)
    {
        int code = Mathf.RoundToInt(impact);
        bool blast = code < StateCode;
        int index = code - (blast ? BlastCode : StateCode);
        Bay? bay = bays.FirstOrDefault(b => b.Index == index);
        if (bay == null)
        {
            Log.Warning(Invariant($"cook-off on {aircraft.name}: marker with code {impact:0.###} names no bay here ({Role}); ignored"));
            return;
        }

        // Each peer blows what its copy of the bay holds, the server's own inventory unless a launch is still on its way. The
        // server's figure rides along as a half float (about 2 kg coarse at 5,000), only to show a disagreement in the log.
        float blastKg = BayCookoffRule.BlastKg(Unspent(bay).Select(s => (WarheadKg(s.info), s.info.nuclear)));
        Log.Info(Invariant($"cook-off on {aircraft.name}: {bay.Name} event received ({(blast ? "blast" : "state only")}, {blastKg:0.#} kg here, {pierce / KgToKilotons:0} kg sent, {Role}{(bay.Spent ? ", bay already spent here" : "")})"));
        if (blast && bay.Spent)
        {
            return;
        }

        bool first = !bay.Spent;
        bay.Spent = true;
        bay.Timer.MarkSpent();
        Vector3 at = bay.BlastPoint.position;
        int lost = Empty(bay);
        Log.Info($"cook-off on {aircraft.name}: {bay.Name} emptied, {lost} stores lost without firing ({Role})");
        if (blast)
        {
            Blast(at, blastKg);
            blasts++;
            lastBlastKg = blastKg;
            lastBlastBay = bay.Name;
        }
        else if (!bay.Host.IsDetached())
        {
            // A late joiner missed the RpcBreakPart; UnitPart.Detach is what that RPC would have run here (Unit.cs:2193-2203).
            bay.Host.Detach(aircraft.rb.velocity, bay.Host.transform.position - aircraft.transform.position);
            Log.Info($"cook-off on {aircraft.name}: {bay.Name} detached from the server's spent state, no blast ({(first ? "first word" : "repeat")})");
        }
    }

    void Blast(Vector3 at, float blastKg)
    {
        string effectName = BayCookoffRule.EffectName(blastKg);
        // The stock weapon prefabs reference both explosions; HLT-M and munitions containers reference the container.
        // Encyclopedia preloads their UnitDefinitions and NetworkManagerNuclearOption.RegisterPrefabs visits every prefab.
        GameObject[] loaded = Resources.FindObjectsOfTypeAll<Shockwave>().Select(s => s.transform.root.gameObject)
            .Where(g => !g.scene.IsValid()).ToArray();
        // The damage rides on the effect's Shockwave, so a missing tier falls back to the 1,000 kg effect, never to nothing.
        GameObject? explosion = loaded.FirstOrDefault(g => g.name == effectName);
        if (explosion == null)
        {
            explosion = loaded.FirstOrDefault(g => g.name == "explosion_1000kg");
        }

        bool fragOnly = blastKg <= BayCookoffRule.FragOnlyKg;
        if (explosion == null)
        {
            Log.Warning($"cook-off: {effectName} is not loaded; the blast has no effect or shockwave");
        }
        else
        {
            GameObject effect = Instantiate(explosion, Datum.origin);
            effect.transform.SetPositionAndRotation(at, Quaternion.identity);
            // MushroomCloud scales the container's visuals in Start; the smaller effects have fixed particles.
            if (effect.GetComponentInChildren<MushroomCloud>() is { } cloud)
            {
                cloud.yield = blastKg;
            }

            // Shockwave reads its yield in Start, next frame. Below 0.0002 kt it touches nothing (Shockwave.Start),
            // so a frag-only blast keeps the shockwave just under that and BlastFrag is its sole damage path.
            float shockKg = fragOnly ? Mathf.Min(blastKg, BayCookoffRule.FragOnlyKg * 0.999f) : blastKg;
            if (effect.GetComponentInChildren<Shockwave>() is { } shockwave)
            {
                shockwave.SetOwner(PersistentID.None, shockKg * KgToKilotons);
            }

            if (fragOnly)
            {
                Destroy(effect, 30f); // as Missile.Warhead.Detonate does for a small blast
            }
        }

        if (fragOnly)
        {
            DamageEffects.BlastFrag(blastKg, at, PersistentID.None, PersistentID.None);
        }

        Log.Info(Invariant($"cook-off on {aircraft.name}: blast {blastKg:0.#} kg TNT ({(fragOnly ? "fragmentation" : "shockwave")}, {Role}), effect {effectName}"));
    }

    /// <summary>
    /// Every unspent store in the bay goes as if fired (MountedMissile.Fire's own bookkeeping: fired, no ammo, its mass, drag
    /// and RCS off the hardpoint once) but launches nothing. Each station's spent stores then sit just before its next index,
    /// so the next trigger pull takes a live store (WeaponStation.LaunchMount fires Weapons[weaponIndex]) and the order every
    /// peer replays launches in stays the same.
    /// </summary>
    int Empty(Bay bay)
    {
        int lost = 0;
        foreach (WeaponStation station in aircraft.weaponStations)
        {
            var spent = station.Weapons.OfType<MountedMissile>().Where(w => IsUnspentIn(w, bay)).Cast<Weapon>().ToList();
            if (spent.Count == 0)
            {
                continue;
            }

            foreach (MountedMissile store in spent.Cast<MountedMissile>())
            {
                Fired!.SetValue(store, true);
                store.ammo = 0;
                RemoveFromHardpoint!.Invoke(store, null);
                store.gameObject.SetActive(false);
            }

            int index = (int)WeaponIndex!.GetValue(station);
            int before = station.Weapons.Take(index).Count(w => !spent.Contains(w));
            var order = station.Weapons.Where(w => !spent.Contains(w)).ToList();
            order.InsertRange(before, spent);
            station.Weapons.Clear();
            station.Weapons.AddRange(order);
            WeaponIndex.SetValue(station, before + spent.Count);
            if (NetworkManagerNuclearOption.i.Server.Active)
            {
                station.AccountAmmo();
            }
            else
            {
                station.Ammo -= spent.Count; // as WeaponStation.UpdateLastFired counts a client's launches
            }

            station.Updated();
            lost += spent.Count;
        }

        return lost;
    }

    List<MountedMissile> Unspent(Bay bay) => aircraft.weaponStations.SelectMany(s => s.Weapons.OfType<MountedMissile>())
        .Where(w => IsUnspentIn(w, bay)).ToList();

    static bool IsUnspentIn(MountedMissile store, Bay bay) =>
        store != null && store.ammo > 0 && !(bool)Fired!.GetValue(store) && HardpointField!.GetValue(store) is Hardpoint h && h.part == bay.Host;

    static string Inventory(List<MountedMissile> stores) => stores.Count == 0 ? "empty"
        : string.Join(", ", stores.GroupBy(s => s.info).Select(g => g.Key.nuclear
            ? $"{g.Count()} {g.Key.weaponName} (nuclear, excluded)"
            : Invariant($"{g.Count()} {g.Key.weaponName} ({WarheadKg(g.Key):0.#} kg each)")));

    /// <summary>A store's warhead from its prefab's Missile (Missile.GetYield); a dispenser's is its submunitions'.</summary>
    static float WarheadKg(WeaponInfo info)
    {
        if (Warheads.TryGetValue(info, out float kg))
        {
            return kg;
        }

        kg = 0f;
        if (info.weaponPrefab != null && info.weaponPrefab.TryGetComponent(out Missile missile))
        {
            int count = 0;
            float each = 0f;
            var dispenser = info.weaponPrefab.GetComponentInChildren<SubmunitionDispenser>(true);
            if (dispenser != null && Submunitions?.GetValue(dispenser) is GameObject[] subs && SubmunitionType?.GetValue(dispenser) is WeaponInfo sub
                && sub.weaponPrefab != null && sub.weaponPrefab.TryGetComponent(out Missile subMissile))
            {
                count = subs.Length;
                each = subMissile.GetYield();
            }

            kg = BayCookoffRule.StoreWarheadKg(missile.GetYield(), count, each);
        }

        Warheads[info] = kg;
        return kg;
    }

    /// <summary>The server, once a second: a player it hasn't seen means a peer that missed every blast; each spent bay goes again.</summary>
    void ResendForLateJoiners()
    {
        float now = Time.unscaledTime;
        if (now >= nextRosterAt)
        {
            nextRosterAt = now + 1f;
            bool joined = false;
            foreach (PlayerRef player in UnitRegistry.playerLookup.Keys)
            {
                joined |= players.Add(player);
            }

            if (joined && bays.Any(b => b.Spent))
            {
                resendAt.AddRange(ResendDelaysS.Select(d => now + d));
                Log.Info($"cook-off on {aircraft.name}: a player joined, spent bays go again in {string.Join(" and ", ResendDelaysS)} s");
            }
        }

        if (resendAt.RemoveAll(t => now >= t) == 0)
        {
            return;
        }

        foreach (Bay bay in bays.Where(b => b.Spent))
        {
            aircraft.Damage(markerId, new DamageInfo(0f, 0f, 0f, StateCode + bay.Index));
            Log.Info($"cook-off on {aircraft.name}: {bay.Name} spent state resent for a late joiner");
        }
    }

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        state["cookoff_blasts"] = AircraftReadout.NotRead;
        state["cookoff_last_kg"] = AircraftReadout.NotRead;
        state["cookoff_last_bay"] = AircraftReadout.NoText;
    }

    /// <summary>Blasts this peer has played for any Centurion, and the last one's yield and bay.</summary>
    internal static void Read(Dictionary<string, object> state)
    {
        state["cookoff_blasts"] = blasts;
        state["cookoff_last_kg"] = AircraftReadout.Round(lastBlastKg);
        state["cookoff_last_bay"] = lastBlastBay;
    }
}
