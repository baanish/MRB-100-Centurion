using System.Collections.Generic;
using HarmonyLib;

namespace Centurion;

/// <summary>
/// An AI Centurion holds its course against missiles its C-RAM can take and lets the laser work (owner, 2026-10-15: "it can just
/// ignore the missiles shot at it from angles where the laser can shoot them down"). The stock combat AI's radar evasion turns
/// across the missile and dives for 10 m above the terrain at full throttle (AIPilotCombatModes.EvadeModeRadar,
/// AIPilotCombatModes.cs:1160-1197), which throws away a bomb run from 6 km and is the push that tore the extended wing.
/// While every missile aimed at the aircraft passes <see cref="CramGuard.CanEngage"/>, the stock evasion still runs, so its
/// countermeasure choices (flares, the jammer) stand, and the postfix puts back the course, height, terrain following, aim and
/// throttle the attack mode had set before it, so the AI flies on as if unwarned. One missile the laser can't take (head-on,
/// outside the aft cone, an empty capacitor, no C-RAM fitted) and the stock evasion runs whole, inside <see cref="AiLoadLimit"/>,
/// except that a bomber on <see cref="AiHighStrike"/>'s profile dodges a radar missile at the profile's height.
/// AIPilotCombatModes flies AI pilots, and the framework's fly mode standing in for one; the player's own state never runs it.
/// </summary>
static class AiCramHold
{
    const string CenturionKey = "baanish_centurion";

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("ai-cram-hold", typeof(AIPilotCombatModes), "RunEvadeMode",
            prefix: AccessTools.Method(typeof(AiCramHold), nameof(BeforeRunEvadeMode)),
            postfix: AccessTools.Method(typeof(AiCramHold), nameof(AfterRunEvadeMode))),
    };

    /// <summary>What the stock evasion overwrites (EvadeModeIR and EvadeModeRadar, AIPilotCombatModes.cs:1144-1197).</summary>
    readonly struct Course
    {
        public Course(GlobalPosition destination, float targetHeight, float aimEffort, float throttle, bool followTerrain, bool aimVelocity)
        {
            Destination = destination;
            TargetHeight = targetHeight;
            AimEffort = aimEffort;
            Throttle = throttle;
            FollowTerrain = followTerrain;
            AimVelocity = aimVelocity;
        }

        public GlobalPosition Destination { get; }
        public float TargetHeight { get; }
        public float AimEffort { get; }
        public float Throttle { get; }
        public bool FollowTerrain { get; }
        public bool AimVelocity { get; }
    }

    /// <summary>
    /// How many missiles aimed at a Centurion its C-RAM covers: 0 with none aimed at it, -1 if one is aimed at it that the
    /// laser can't take or it has no C-RAM. Above 0 the AI holds its course through the stock evasion.
    /// </summary>
    internal static int Covered(Aircraft aircraft, List<Missile> missileAlerts)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-cram-hold")) return -1;
        if (aircraft == null || aircraft.definition == null || aircraft.definition.jsonKey != CenturionKey
            || !aircraft.TryGetComponent(out CramGuard guard))
        {
            return -1;
        }

        int covered = 0;
        foreach (Missile missile in missileAlerts)
        {
            if (missile == null || missile.disabled || missile.targetID != aircraft.persistentID)
            {
                continue;
            }

            if (!guard.CanEngage(missile, out string why))
            {
                if (CenturionPlugin.Log.StageDue("ai-cram-evade"))
                {
                    CenturionPlugin.Log.StageLine("ai-cram-evade", $"{aircraft.persistentID}: evading missile {missile.persistentID}: {why}");
                }

                return -1;
            }

            covered++;
        }

        return covered;
    }

    static void BeforeRunEvadeMode(Aircraft ___aircraft, List<Missile> ___missileAlerts, ControlInputs ___controlInputs, GlobalPosition ___destination,
        float ___targetHeight, float ___aimEffort, bool ___followTerrain, bool ___aimVelocity, out Course? __state)
    {
        __state = null;
        if (CenturionPlugin.FeaturesOff.Contains("ai-cram-hold")) return;
        int covered = Covered(___aircraft, ___missileAlerts);
        if (covered <= 0)
        {
            return;
        }

        __state = new Course(___destination, ___targetHeight, ___aimEffort, ___controlInputs.throttle, ___followTerrain, ___aimVelocity);
        if (CenturionPlugin.Log.StageDue("ai-cram-hold"))
        {
            CenturionPlugin.Log.StageLine("ai-cram-hold", $"{___aircraft.persistentID}: holding course, the C-RAM covers {covered} missile(s)");
        }
    }

    static void AfterRunEvadeMode(Course? __state, ref GlobalPosition evadeDestination, ControlInputs ___controlInputs, ref GlobalPosition ___destination,
        ref float ___targetHeight, ref float ___aimEffort, ref bool ___followTerrain, ref bool ___aimVelocity)
    {
        if (CenturionPlugin.FeaturesOff.Contains("ai-cram-hold")) return;
        if (__state is not { } held)
        {
            return;
        }

        evadeDestination = ___destination = held.Destination;
        ___targetHeight = held.TargetHeight;
        ___aimEffort = held.AimEffort;
        ___controlInputs.throttle = held.Throttle;
        ___followTerrain = held.FollowTerrain;
        ___aimVelocity = held.AimVelocity;
    }
}
