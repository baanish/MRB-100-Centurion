namespace Centurion;

static class SamReach
{
    // Round the 33.3 km slant to a bomber at 50,000 ft and 16 nmi up to 34 km.
    // This policy counts long-range launchers anywhere in the mission until they are lost or destroyed.
    internal const float LongRangeM = 34000f;
    internal const float BomberHeightM = 15240f;

    internal static bool IsLivingSurfaceUnit(bool disabled, bool hasFaction, bool surface) =>
        !disabled && hasFaction && surface;

    internal static bool IsLongRange(bool missile, float antiAir, float rangeM, float ceilingM) =>
        missile && antiAir > 0f && rangeM >= LongRangeM && ceilingM >= BomberHeightM;

    // Use the climb column above home as a stable proxy. A base outside this envelope keeps the height rule
    // even if the later outbound leg takes the bomber closer to a launcher.
    internal static bool CoversClimbColumn(float horizontalM, float launcherMslM, float homeMslM, float rangeM)
    {
        float topMslM = System.Math.Max(homeMslM, BomberHeightM);
        float verticalM = launcherMslM < homeMslM ? homeMslM - launcherMslM : System.Math.Max(0f, launcherMslM - topMslM);
        return horizontalM * horizontalM + verticalM * verticalM <= rangeM * rangeM;
    }
}
