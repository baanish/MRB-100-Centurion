using HarmonyLib;

namespace Centurion;

static class BayLoadoutRule
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("bay-loadout", typeof(WeaponManager), nameof(WeaponManager.SpawnWeapons),
            prefix: AccessTools.Method(typeof(BayLoadoutRule), nameof(BeforeSpawnWeapons))),
    };

    // Saved and network loadouts bypass the selector's preclusion checks; the beam owns the rear bay.
    static void BeforeSpawnWeapons(Aircraft ___aircraft)
    {
        if (CenturionPlugin.FeaturesOff.Contains("bay-loadout")) return;
        if (___aircraft.definition?.jsonKey != "baanish_centurion") return;
        var weapons = ___aircraft.loadout?.weapons;
        if (weapons == null || weapons.Count <= 2 || weapons[2]?.jsonKey != "baanish_centurion_awacs") return;
        weapons[1] = null;
    }
}
