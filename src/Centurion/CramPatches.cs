using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// The C-RAM's Harmony patches: cram-cover (escort cover and untargeted missiles), cram-ai (the C-RAM out of the AI pilot's
/// weapon choice) and cram-kills (kills from the kill-feed RPC, on every peer, also feeding <see cref="SortieLog"/>); docs/M3-DESIGN.md, "Patches". The C-RAM is
/// the Centurion's only zero-cost weapon, which cram-cover keys on so AAMs and HUD selection keep stock priorities.
/// </summary>
static class CramPatches
{
    const float LaserRange = 8000f;
    static readonly AccessTools.FieldRef<Laser, Transform> TargetTransform = AccessTools.FieldRefAccess<Laser, Transform>("currentTargetTransform");
    static readonly AccessTools.FieldRef<Laser, Transform> DirectionTransform = AccessTools.FieldRefAccess<Laser, Transform>("directionTransform");
    static readonly AccessTools.FieldRef<Laser, float> MaxAngle = AccessTools.FieldRefAccess<Laser, float>("maxAngle");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("cram-emission", typeof(Laser), nameof(Laser.Fire),
            prefix: AccessTools.Method(typeof(CramPatches), nameof(BeforeLaserFire))),
        new("cram-emission", typeof(Laser), "FixedUpdate",
            transpiler: AccessTools.Method(typeof(CramPatches), nameof(LimitLaserEmission))),
        new("cram-emission", typeof(Laser), nameof(Laser.LateUpdate),
            postfix: AccessTools.Method(typeof(CramPatches), nameof(AfterLaserLateUpdate))),
        new("cram-cover", typeof(Missile), nameof(Missile.InterceptPriority), new[] { typeof(Unit), typeof(float), typeof(float) },
            postfix: AccessTools.Method(typeof(CramPatches), nameof(AfterInterceptPriority))),
        // CombatAI.AnalyzeTarget asks InterceptPriority only above 1 m of radar altitude (CombatAI.cs:147), so the same rule
        // also applies to a missile at or under it.
        new("cram-cover", typeof(CombatAI), nameof(CombatAI.AnalyzeTarget), new[] { typeof(WeaponStation), typeof(Unit), typeof(TrackingInfo), typeof(float), typeof(float), typeof(float) },
            postfix: AccessTools.Method(typeof(CramPatches), nameof(AfterAnalyzeTarget))),
        new("cram-ai", typeof(CombatAI), nameof(CombatAI.ChooseHQTarget), new[] { typeof(Unit), typeof(float), typeof(List<WeaponStation>) },
            prefix: AccessTools.Method(typeof(CramPatches), nameof(BeforeChooseHQTarget))),
        new("cram-kills", typeof(MessageManager), "UserCode_RpcKillMessage_635947223", new[] { typeof(PersistentID), typeof(PersistentID), typeof(KillType) },
            postfix: AccessTools.Method(typeof(CramPatches), nameof(AfterKillMessage))),
    };

    static bool BeforeLaserFire(Laser __instance)
    {
        var guard = CramGuard.ForLaser(__instance);
        if (guard == null) return true;
        // A failed emission patch must not leave the stock unbounded linecast active (Laser.cs:275).
        if (CenturionPlugin.FeaturesOff.Contains("cram-emission")) return false;
        // Fire stamps the station before emission (Laser.cs:217-219); rejected trigger holds must not count as shots.
        // Use the same part or last-known aim point and slew as FixedUpdate (Laser.cs:243-252).
        var part = TargetTransform(__instance);
        var target = __instance.GetTarget();
        Vector3 endpoint = part != null ? part.position : __instance.transform.position + __instance.transform.forward * 20000f;
        if (target != null && !__instance.attachedUnit.NetworkHQ.IsTargetBeingTracked(target)
            && __instance.attachedUnit.NetworkHQ.TryGetKnownPosition(target, out var known)) endpoint = known.ToLocalPosition();
        Vector3 direction = Vector3.RotateTowards(__instance.transform.forward, endpoint - __instance.transform.position,
            MaxAngle(__instance) * Mathf.Deg2Rad, 0f);
        return LaserPathAllowed(__instance, guard, direction, ref endpoint);
    }

    static IEnumerable<CodeInstruction> LimitLaserEmission(IEnumerable<CodeInstruction> instructions, MethodBase original)
    {
        var code = instructions.ToList();
        var commanded = AccessTools.Field(typeof(Laser), "fireCommanded");
        // Gate the final aim point before power, particles, beam or damage (Laser.cs:259-297), including remote fire.
        if (original.GetMethodBody()?.LocalVariables.FirstOrDefault()?.LocalType != typeof(Vector3)
            || code.Count(i => i.LoadsField(commanded)) != 1)
            throw new InvalidOperationException("Laser.FixedUpdate emission layout changed");
        foreach (var instruction in code)
        {
            yield return instruction;
            if (!instruction.LoadsField(commanded)) continue;
            yield return new CodeInstruction(OpCodes.Ldarg_0);
            yield return new CodeInstruction(OpCodes.Ldloca_S, (byte)0);
            yield return new CodeInstruction(OpCodes.Call, AccessTools.Method(typeof(CramPatches), nameof(LaserEmissionAllowed)));
        }
    }

    static bool LaserEmissionAllowed(bool commanded, Laser weapon, ref Vector3 endpoint)
    {
        if (!commanded) return false;
        var guard = CramGuard.ForLaser(weapon);
        return guard == null || LaserPathAllowed(weapon, guard, DirectionTransform(weapon).forward, ref endpoint);
    }

    static bool LaserPathAllowed(Laser weapon, CramGuard guard, Vector3 direction, ref Vector3 endpoint)
    {
        Vector3 origin = DirectionTransform(weapon).position;
        Vector3 offset = endpoint - origin;
        if (!guard.WithinLaserCone(direction) || !guard.WithinLaserCone(offset)) return false;
        if (offset.sqrMagnitude > LaserRange * LaserRange)
        {
            if (weapon.GetTarget() != null) return false;
            // Unassigned manual aim uses a 20 km endpoint (Laser.cs:243); keep free aim but bound its linecast.
            endpoint = origin + offset.normalized * LaserRange;
        }
        return true;
    }

    static void AfterLaserLateUpdate(Laser __instance, Renderer ___beamRenderer)
    {
        if (CenturionPlugin.FeaturesOff.Contains("cram-emission")) return;
        var guard = CramGuard.ForLaser(__instance);
        if (guard == null || !___beamRenderer.enabled) return;
        // LateUpdate follows a moving hit part after emission (Laser.cs:234-238); bound the rendered beam too.
        var beam = ___beamRenderer.transform;
        if (!guard.WithinLaserCone(beam.forward)) ___beamRenderer.enabled = false;
        else
        {
            Vector3 scale = beam.localScale;
            scale.z = Mathf.Min(scale.z, LaserRange);
            beam.localScale = scale;
        }
    }

    static void AfterInterceptPriority(Missile __instance, Unit toUnit, float interceptorValue, ref float __result)
    {
        if (CenturionPlugin.FeaturesOff.Contains("cram-cover")) return;
        if (interceptorValue != 0f || !CramGuard.Carriers.Contains(toUnit)) return;
        if (CoverPriority(__instance, toUnit) is float priority) __result = priority;
    }

    static void AfterAnalyzeTarget(WeaponStation weaponStation, Unit analyzer, TrackingInfo trackingInfo, ref OpportunityThreat __result)
    {
        if (CenturionPlugin.FeaturesOff.Contains("cram-cover")) return;
        if (__result.opportunity == 0f || weaponStation.WeaponInfo.costPerRound != 0f || !CramGuard.Carriers.Contains(analyzer)) return;
        if (!trackingInfo.TryGetUnit(out Unit unit) || unit is not Missile missile || unit.radarAlt > 1f || missile.targetID == analyzer.persistentID) return;
        if (CoverPriority(missile, analyzer) == 0f) __result = new OpportunityThreat(0f, __result.threat);
    }

    /// <summary>The C-RAM's priority for a missile not aimed at its carrier: 1 untargeted, the cover rule for one aimed at another unit, null (stock) for one aimed at a missile.</summary>
    static float? CoverPriority(Missile missile, Unit carrier)
    {
        if (!UnitRegistry.TryGetUnit(missile.targetID, out Unit target) || target == null || target.disabled) return 1f;
        if (target is not Missile) return target.NetworkHQ == carrier.NetworkHQ && CramGuard.CoverEscorts.Value ? 1f : 0f;
        return null;
    }

    static void BeforeChooseHQTarget(Unit searcher, ref List<WeaponStation> stationList)
    {
        if (CenturionPlugin.FeaturesOff.Contains("cram-ai")) return;
        if (CramGuard.Carriers.Contains(searcher) && searcher.TryGetComponent<CramGuard>(out var guard))
            stationList = guard.AiStations;
    }

    static void AfterKillMessage(PersistentID killerID, PersistentID killedID, KillType killedType)
    {
        if (CenturionPlugin.FeaturesOff.Contains("cram-kills")) return;
        if (SortieLog.Enabled.Value) SortieLog.Kill(killerID, killedID, killedType);
        if (killedType == KillType.Missile && UnitRegistry.TryGetUnit(killerID, out Unit killer)
            && CramGuard.Carriers.Contains(killer) && killer.TryGetComponent<CramGuard>(out var guard))
            guard.CountKill(killedID);
    }
}
