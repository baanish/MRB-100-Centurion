namespace Centurion;

static class AiMissileLaunch
{
    internal static bool IsStrikeMissile(bool missile, bool bomb, float muzzleVelocity, float antiSurface, float antiRadar) =>
        missile && !bomb && muzzleVelocity <= 0f && (antiSurface > 0f || antiRadar > 0f);

    internal static bool HasSolution(bool accurate, bool obscured, bool overHorizon,
        float distance, float minRange, float maxRange) =>
        accurate && (overHorizon || !obscured) && distance >= minRange && distance < maxRange;
}
