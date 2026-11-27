using HarmonyLib;

namespace Centurion;

/// <summary>
/// A Centurion part can hold several braces with the same tensor (bay_A three with fuselage_R, tailcone two, bay_F three with
/// fuselage_F). Stock AeroPart.Part_OnTensorBreak releases every such brace only while the camera is within 1 km
/// (displayDetail at least 1); further away, and always on a dedicated server, it releases the first and stops
/// (AeroPart.cs:236-247), so the rest hold a destroyed body section and everything under it on the aircraft. This releases
/// them all at any range, as stock does up close, without the break sound.
/// </summary>
static class TensorRelease
{
    internal static readonly PatchTarget[] PatchTargets =
    {
        new("tensor-release", typeof(AeroPart), "Part_OnTensorBreak", new[] { typeof(UnitPart) },
            postfix: AccessTools.Method(typeof(TensorRelease), nameof(AfterTensorBreak))),
    };

    static void AfterTensorBreak(AeroPart __instance, UnitPart part)
    {
        if (CenturionSystems.Of(__instance.parentUnit as Aircraft) == null) return;
        foreach (PartJoint brace in __instance.Joints)
        {
            if (brace.tensor == part && brace.joint != null)
            {
                brace.joint.breakForce = 0f;
                brace.joint.breakTorque = 0f;
            }
        }
    }
}
