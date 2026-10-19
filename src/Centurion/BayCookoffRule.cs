using System;
using System.Collections.Generic;
using System.Linq;

namespace Centurion;

/// <summary>
/// The numbers of a weapon bay cook-off (owner, 2026-10-19; docs/SPEC.md "Damage"), free of the game so
/// tests/BayCookoff.Tests can run them: a bay goes off once its host's fuel tank has burned <see cref="BurnS"/> with a
/// conventional store aboard, in one blast of a quarter of the conventional warheads left, capped at 5,000 kg TNT.
/// Nuclear stores never count toward the trigger or the yield. <see cref="BayCookoff"/> applies them.
/// </summary>
static class BayCookoffRule
{
    public const float BurnS = 5f;
    public const float YieldFraction = 0.25f;
    public const float MaxBlastKg = 5000f;
    /// <summary>At or under this a blast is stock fragmentation (DamageEffects.BlastFrag), as a stock warhead's is (Missile.cs:166, 1732).</summary>
    public const float FragOnlyKg = 200f;
    /// <summary>Seconds between inventory checks of a bay that has burned long enough but holds nothing conventional.</summary>
    public const float RecheckS = 1f;

    /// <summary>
    /// Visual tiers deliberately promote at 500 and 2,500 kg: small blasts use the 100 kg effect, medium blasts the
    /// 1,000 kg effect, and the upper half of the 5,000 kg cap the container. These rounded cutoffs change only the
    /// stock effect family; damage always uses BlastKg, and MushroomCloud.yield uses that same kg value.
    /// </summary>
    public static string EffectName(float blastKg) => blastKg < 500f ? "explosion_100kg"
        : blastKg < 2500f ? "explosion_1000kg" : "AmmoCookoff10TContainer";

    /// <summary>A store's warhead in kg TNT: a dispenser's is its submunitions' together, any other its own.</summary>
    public static float StoreWarheadKg(float warheadKg, int submunitions, float submunitionKg) =>
        submunitions > 0 ? submunitions * submunitionKg : warheadKg;

    /// <summary>The unspent stores that trigger a cook-off.</summary>
    public static int Conventional(IEnumerable<(float WarheadKg, bool Nuclear)> stores) => stores.Count(s => !s.Nuclear);

    /// <summary>The blast of a bay holding these unspent stores, kg TNT.</summary>
    public static float BlastKg(IEnumerable<(float WarheadKg, bool Nuclear)> stores) =>
        Math.Min(YieldFraction * stores.Where(s => !s.Nuclear).Sum(s => s.WarheadKg), MaxBlastKg);
}

/// <summary>One bay's burn timer on the server: due once its tank has burned <see cref="BayCookoffRule.BurnS"/>, then every
/// <see cref="BayCookoffRule.RecheckS"/> until the bay is spent; a tank that stops burning starts it over.</summary>
sealed class BayCookoffTimer
{
    float nextCheckS;

    public float BurnedS { get; private set; }
    public bool Spent { get; private set; }

    /// <summary>One frame; true when the bay should take stock of its stores.</summary>
    public bool Step(bool burning, float dt)
    {
        if (Spent)
        {
            return false;
        }

        if (!burning)
        {
            BurnedS = nextCheckS = 0f;
            return false;
        }

        BurnedS += dt;
        if (BurnedS < BayCookoffRule.BurnS || BurnedS < nextCheckS)
        {
            return false;
        }

        nextCheckS = BurnedS + BayCookoffRule.RecheckS;
        return true;
    }

    public void MarkSpent() => Spent = true;
}
