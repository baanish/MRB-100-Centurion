using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using NuclearOption.Jobs;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The Centurion's spoilers rise only, on the side whose aileron goes up. Stock ControlSurface has no one-sided deflection:
/// each channel servoes to input x range and clamps to +-|range| (ControlSurfaceJob_Math.cs:52-60; brakeRange is copied into
/// the job fields but never read), and the one-sided split only follows idle throttle and yaw (:64-72). So after the stock
/// UpdateJobFields copies the inputs into a spoiler's job fields (ControlSurface.cs:183-197), the roll input that would lower
/// it is zeroed there, on every peer, before the job turns the surface. The job still servoes it back down at servoSpeed.
/// </summary>
static class SpoilerRule
{
    static readonly AccessTools.FieldRef<ControlSurface, PtrAllocation<ControlSurfaceFields>>? JobFields =
        AccessTools.Field(typeof(ControlSurface), "JobFields") == null ? null : AccessTools.FieldRefAccess<ControlSurface, PtrAllocation<ControlSurfaceFields>>("JobFields");
    static readonly AccessTools.FieldRef<ControlSurface, GameObject>? VisibleMesh =
        AccessTools.Field(typeof(ControlSurface), "visibleMesh") == null ? null : AccessTools.FieldRefAccess<ControlSurface, GameObject>("visibleMesh");

    /// <summary>Each live Centurion spoiler and the sign of the roll input that raises it.</summary>
    static readonly Dictionary<ControlSurface, float> Rise = new();

    internal static readonly PatchTarget[] PatchTargets =
    {
        new("spoilers", typeof(ControlSurface), nameof(ControlSurface.UpdateJobFields),
            postfix: AccessTools.Method(typeof(SpoilerRule), nameof(AfterUpdateJobFields))),
    };

    internal static CenturionLog Log = null!;

    /// <summary>
    /// The job turns visibleMesh by the summed angle about its local X (ControlSurfaceJob_Math.cs:62-63), so a spoiler rises for
    /// the roll input whose angle (input x rollRange) lifts its trailing edge, read off the hinge in the aircraft's frame.
    /// </summary>
    internal static unsafe void Register(Aircraft aircraft)
    {
        if (CenturionPlugin.FeaturesOff.Contains("spoilers") || JobFields == null || VisibleMesh == null)
        {
            Log.Warning("spoilers: ControlSurface.JobFields or visibleMesh is missing in this game build, so the spoilers deflect both ways");
            return;
        }

        // Through partLookup: by the time the telescope binds, complex physics has unparented every part onto its own
        // rigidbody (AeroPart.CreateRB, AeroPart.cs:334), so the surfaces are no longer the aircraft's children.
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part == null || !part.name.StartsWith("spoiler_") || !part.TryGetComponent(out ControlSurface surface))
            {
                continue;
            }

            PtrAllocation<ControlSurfaceFields> fields = JobFields(surface);
            if (fields.ptr == null)
            {
                continue;
            }

            Transform hinge = VisibleMesh(surface).transform;
            Vector3 aft = -aircraft.transform.forward;
            float trailingEdgeUp = Mathf.Sign(Vector3.Dot(Quaternion.AngleAxis(1f, hinge.right) * aft - aft, aircraft.transform.up));
            float rise = Mathf.Sign(fields.ptr->rollRange) * trailingEdgeUp;
            Rise[surface] = rise;
            Log.Info(Invariant($"spoilers: {surface.name} on {aircraft.name} rises on roll input {(rise > 0 ? "+" : "-")}"));
        }
    }

    /// <summary>The aircraft's spoilers leave the rule with it (TelescopeController.OnDestroy), and any surface already destroyed.</summary>
    internal static void Forget(Aircraft aircraft)
    {
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part != null && part.TryGetComponent(out ControlSurface surface))
            {
                Rise.Remove(surface);
            }
        }

        foreach (ControlSurface gone in Rise.Keys.Where(s => s == null).ToList())
        {
            Rise.Remove(gone);
        }
    }

    static unsafe void AfterUpdateJobFields(ControlSurface __instance)
    {
        if (CenturionPlugin.FeaturesOff.Contains("spoilers")) return;
        if (Rise.Count == 0 || !Rise.TryGetValue(__instance, out float rise))
        {
            return;
        }

        ControlSurfaceFields* fields = JobFields!(__instance).ptr;
        if (fields != null && fields->controlInputs.roll * rise < 0f)
        {
            fields->controlInputs.roll = 0f;
        }
    }
}
