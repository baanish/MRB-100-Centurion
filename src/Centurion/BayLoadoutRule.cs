using HarmonyLib;
using NuclearOption.SavedMission;

namespace Centurion;

static class BayLoadoutRule
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("bay-loadout", typeof(WeaponManager), nameof(WeaponManager.SpawnWeapons),
            prefix: AccessTools.Method(typeof(BayLoadoutRule), nameof(BeforeSpawnWeapons))),
        new("bay-loadout", typeof(WeaponManager), nameof(WeaponManager.SelectAIAircraftWeapons),
            postfix: AccessTools.Method(typeof(BayLoadoutRule), nameof(AfterSelectAIAircraftWeapons))),
    };

    // Saved and network loadouts bypass the selector's preclusion checks; the beam owns the rear bay. A pack rack loads only
    // on the bay that offers it: a saved mission can name it on another, which SavedLoadout.GetWeaponMount then finds in
    // the encyclopedia (SavedLoadout.cs:37-41). Every peer runs this on the same loadout and options, so all agree.
    static void BeforeSpawnWeapons(Aircraft ___aircraft)
    {
        if (!CenturionSystems.IsCenturion(___aircraft.definition)) return;
        var weapons = ___aircraft.loadout?.weapons;
        if (weapons == null) return;
        if (weapons.Count > 2 && weapons[2]?.jsonKey == AwacsBeam.AwacsKey) weapons[1] = null;
        HardpointSet[] sets = ___aircraft.weaponManager.hardpointSets;
        for (int i = 0; i < weapons.Count && i < sets.Length; i++)
        {
            if (PackBayMounts.IsPackRack(weapons[i]) && !sets[i].weaponOptions.Contains(weapons[i])) weapons[i] = null;
        }
    }

    // The AI never carries a pack rack. HQ deployment takes StandardLoadouts (FactionHQ.cs:950), which hold none; a hangar
    // spawn with no loadout picks each bay at random from every legal option (Hangar.cs:652, WeaponManager.cs:86-110), so
    // a pack rack it drew leaves that bay empty. The server picks before the loadout is sent, so clients get it so.
    static void AfterSelectAIAircraftWeapons(Aircraft ___aircraft, Loadout __result)
    {
        if (!CenturionSystems.IsCenturion(___aircraft.definition)) return;
        for (int i = 0; i < __result.weapons.Count; i++)
        {
            if (PackBayMounts.IsPackRack(__result.weapons[i])) __result.weapons[i] = null;
        }
    }
}
