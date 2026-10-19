using System;
using System.Reflection;
using HarmonyLib;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The AI Centurion extends away from a target it has passed and turns back for another bomb run. Stock bombing
/// (AIPilotCombatModes.UseBombs, AIPilotCombatModes.cs:589-680) steers at the target and leaves the run only on a break-off
/// when the slant range drops under 2000 + 0.5 x radar alt + 3.6 x speed with the target more than 20 deg off the nose
/// (:605). Slant range includes the height, so above about 5.6 km over the target that test can never pass, and a jet
/// turns tight enough not to need it. The Centurion turns at about 3.3 deg/s up there (1.6 g, 216 m/s: a 3.7 km radius):
/// after its first salvo at the K92 column it flew a 4 km circle round the rest at 7.2 km for 24 minutes, never within
/// 10 deg of the target at the 8 km release range (run 20261015-113555 balance_sortie_centurion; the Darkreach, banking
/// past 75 deg, came round inside the same run mode). AiLoadLimit's 0 to +3 g clamp is not what holds it: it flew 1.6 g.
/// So for a Centurion with bombs the prefix on UseBombs breaks off on the horizontal range instead, inside
/// <see cref="ExtendRange"/>, and the prefix on BreakOffAttack flies the 15 s break-off directly away from the target
/// (stock flies it at the nearest friendly airbase, or skips it with none in reach), so the turn back starts heading away
/// and ends pointed at the target about as far out as it began. Each break-off inside the range restarts the 15 s, which
/// carries the aircraft about 3 km past it before the stock run turns it back.
/// </summary>
static class AiBombExtend
{
    const string CenturionKey = "baanish_centurion";
    // UseBombs' off-the-nose angle and BreakOffAttack's length (AIPilotCombatModes.cs:605-608).
    const float OffRunDeg = 20f, BreakOffSeconds = 15f;

    static readonly MethodInfo? SetCombatMode = AccessTools.Method(typeof(AIPilotCombatModes), "SetCombatMode");
    static readonly object? BreakOffMode = AttackMode("BreakOffAttack");

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-bomb-extend", typeof(AIPilotCombatModes), "UseBombs",
            prefix: AccessTools.Method(typeof(AiBombExtend), nameof(BeforeUseBombs))),
        new("ai-bomb-extend", typeof(AIPilotCombatModes), "BreakOffAttack",
            prefix: AccessTools.Method(typeof(AiBombExtend), nameof(BeforeBreakOffAttack))),
    };

    static object? AttackMode(string name)
    {
        Type? mode = AccessTools.Inner(typeof(AIPilotCombatModes), "AttackMode");
        return mode != null && Enum.IsDefined(mode, name) ? Enum.Parse(mode, name) : null;
    }

    static bool IsCenturion(Aircraft aircraft) =>
        aircraft != null && aircraft.definition != null && aircraft.definition.jsonKey == CenturionKey;

    /// <summary>
    /// Twice the authored turningRadius, the stock standoff for turning back onto a target (RetreatToStandoff,
    /// AIPilotCombatModes.cs:472): no circle the aircraft can fly holds a target farther out than its diameter, so the
    /// circling the stock run falls into always trips the break-off. A drop from high enough to outreach that uses the
    /// stock release range instead: the bombs' vacuum fall time at the aircraft's horizontal speed (:617-623).
    /// </summary>
    static float ExtendRange(Aircraft aircraft, Unit target, WeaponInfo weapon)
    {
        Vector3 release = aircraft.rb.velocity + aircraft.transform.forward * weapon.muzzleVelocity;
        float drop = aircraft.transform.position.y - (target.transform.position.y + weapon.airburstHeight);
        float releaseRange = Mathf.Max(Kinematics.FallTime(drop, release.y), 0f) * new Vector2(release.x, release.z).magnitude;
        return Mathf.Max(2f * aircraft.GetAircraftParameters().turningRadius, releaseRange);
    }

    static bool BeforeUseBombs(AIPilotCombatModes __instance, bool checkMode, Aircraft ___aircraft, Unit ___currentTarget,
        WeaponInfo ___currentWeaponInfo, Vector3 ___targetVector, ref float ___breakOffTimer, ref bool ___allowTargetAssessment)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-bomb-extend")) return true;
        if (!checkMode || SetCombatMode == null || BreakOffMode == null || !IsCenturion(___aircraft)
            || ___currentTarget == null || ___currentTarget.disabled || ___currentWeaponInfo == null)
        {
            return true;
        }

        Vector3 toTarget = ___targetVector;
        toTarget.y = 0f;
        Vector3 forward = ___aircraft.transform.forward;
        forward.y = 0f;
        float offRun = Vector3.Angle(forward, toTarget);
        float range = toTarget.magnitude;
        float extendRange = ExtendRange(___aircraft, ___currentTarget, ___currentWeaponInfo);
        if (offRun <= OffRunDeg || range >= extendRange)
        {
            return true;
        }

        ___breakOffTimer = BreakOffSeconds;
        SetCombatMode.Invoke(__instance, new[] { BreakOffMode });
        ___allowTargetAssessment = true;
        if (CenturionPlugin.Log.StageDue("ai-bomb-extend"))
        {
            CenturionPlugin.Log.StageLine("ai-bomb-extend", Invariant(
                $"{___aircraft.name} {___currentTarget.unitName} {range:F0} m out, {offRun:F0} deg off the nose, inside {extendRange:F0} m: extending"));
        }

        return false;
    }

    static bool BeforeBreakOffAttack(bool checkMode, Aircraft ___aircraft, Unit ___currentTarget, WeaponInfo ___currentWeaponInfo,
        Vector3 ___targetVector, ControlInputs ___controlInputs, ref float ___breakOffTimer, ref GlobalPosition ___destination,
        ref bool ___aimVelocity, ref bool ___followTerrain)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-bomb-extend")) return true;
        // The last second runs stock, which ends the break-off into FlyingToTarget.
        if (!checkMode || ___breakOffTimer < 1f || !IsCenturion(___aircraft) || ___currentWeaponInfo == null || !___currentWeaponInfo.bomb
            || ___currentTarget == null || ___currentTarget.disabled)
        {
            return true;
        }

        ___breakOffTimer -= 1f;
        Vector3 away = -___targetVector;
        away.y = 0f;
        ___destination = ___aircraft.GlobalPosition() + away.normalized * 1000f;
        ___aimVelocity = true;
        ___followTerrain = true;
        ___controlInputs.throttle = 1f;
        return false;
    }
}
