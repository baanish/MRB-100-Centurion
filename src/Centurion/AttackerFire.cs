using HarmonyLib;

namespace Centurion;

static class AttackerFire
{
    internal const string Feature = "attacker-fire";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new(Feature, typeof(UnitPart), nameof(UnitPart.TakeDamage),
            prefix: AccessTools.Method(typeof(AttackerFire), nameof(BeforePartDamage))),
        new(Feature, typeof(Turbofan), nameof(Turbofan.TakeDamage),
            prefix: AccessTools.Method(typeof(AttackerFire), nameof(BeforeEngineDamage))),
    };

    internal static void BeforePartDamage(UnitPart __instance, PersistentID dealerID, ref float fireDamage)
    {
        if (__instance is AeroPart && __instance.parentUnit is Aircraft aircraft)
            FilterFire(aircraft, __instance.name, dealerID, ref fireDamage);
    }

    internal static void BeforeEngineDamage(Turbofan __instance, PersistentID dealerID, ref float fireDamage)
    {
        if (__instance.GetUnit() is Aircraft aircraft)
            FilterFire(aircraft, __instance.name, dealerID, ref fireDamage);
    }

    // Unit IDs mark attacker fire even after the dealer despawns. None marks stock tank and particle fire.
    // Filter before armour and RpcDamage so every peer receives the server's unchanged non-fire damage.
    static void FilterFire(Aircraft aircraft, string receiver, PersistentID dealerID, ref float fireDamage)
    {
        if (CenturionPlugin.FeaturesOff.Contains(Feature) || !(fireDamage > 0f) || !dealerID.IsValid
            || !aircraft.IsServer || aircraft.definition == null || aircraft.definition.jsonKey != "baanish_centurion") return;
        float ignored = fireDamage;
        fireDamage = 0f;
        FireDamageDiagnostics.Ignored(aircraft);
        if (CenturionPlugin.Log.StageDue(Feature))
            CenturionPlugin.Log.StageLine(Feature, $"unit {aircraft.persistentID} ignored {ignored:0.###} fire from unit {dealerID} on {receiver}");
    }
}
