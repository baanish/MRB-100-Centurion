using System.Collections.Generic;
using HarmonyLib;
using NuclearOption.Jobs;
using UnityEngine;

namespace Centurion;

/// <summary>
/// Shows the coded drag rudders on the ailerons' split halves, as the Darkreach's split ailerons show theirs. Visual only:
/// the drag is TelescopeController's dragArea, and the stock split stays the airbrakes alone (yawSplitFactor 0), because a
/// split follows the fly-by-wire's yaw output and its servo lag in that yaw-rate loop set the hold's high-speed turn
/// oscillating (docs/M2-DESIGN.md, "Airbrakes"). The stock job writes each half's
/// localRotation once per physics step, rest x AngleAxis(+-splitAmount, right) (ControlSurfaceJob_Math.cs:64-72, applied by
/// SetLocalRotationJob inside JobManager's FixedUpdate), so this writes them again in LateUpdate, after it on every rendered
/// frame, by the same rule with the larger of the stock opening (idle-throttle airbrakes) and the drag rudder's, maxSplit
/// fully open. The halves hang under the aileron's hinge, a part WingFlex leaves rigid, so they stay on the aileron. The
/// opening is the controller's, the one the drag scales with, so the drawn surface never lags or leads the drag; a remote
/// copy computes it from the owner's yaw input in the snapshot (TelescopeController's sent copy), so it shows the owner's rudders.
/// </summary>
sealed class DragRudderSplits : MonoBehaviour
{
    static readonly AccessTools.FieldRef<ControlSurface, PtrAllocation<ControlSurfaceFields>>? JobFields =
        AccessTools.Field(typeof(ControlSurface), "JobFields") == null ? null : AccessTools.FieldRefAccess<ControlSurface, PtrAllocation<ControlSurfaceFields>>("JobFields");

    sealed class Split
    {
        public AeroPart Part = null!;
        public ControlSurface Surface = null!;
        public Transform Upper = null!, Lower = null!;
        public float YawSide;
    }

    Aircraft aircraft = null!;
    TelescopeController telescope = null!;
    readonly List<Split> splits = new();

    /// <summary>Each drag rudder's aileron and the yaw sign that opens it (TelescopeController.DragRudderOpen).</summary>
    internal void Bind(Aircraft owner, TelescopeController controller, IEnumerable<(AeroPart aileron, float yawSide)> rudders)
    {
        aircraft = owner;
        telescope = controller;
        foreach ((AeroPart aileron, float yawSide) in rudders)
        {
            if (JobFields == null || !aileron.TryGetComponent(out ControlSurface surface) || !surface.GetJobTransforms(out _, out Transform upper, out Transform lower))
            {
                TelescopeController.Log.Warning($"drag rudders on {owner.name}: {aileron.name} has no stock split halves or this game build lacks ControlSurface.JobFields, so its drag rudder doesn't show");
                continue;
            }

            splits.Add(new Split { Part = aileron, Surface = surface, Upper = upper, Lower = lower, YawSide = yawSide });
        }
    }

    unsafe void LateUpdate()
    {
        if (aircraft == null || telescope == null)
        {
            return;
        }

        foreach (Split split in splits)
        {
            if (split.Surface == null || split.Part.IsDetached())
            {
                continue;
            }

            ControlSurfaceFields* fields = JobFields!(split.Surface).ptr;
            if (fields == null)
            {
                continue;
            }

            float angle = Mathf.Max(fields->splitAmount, fields->maxSplit * telescope.DragRudderOpen(split.YawSide));
            split.Upper.localRotation = fields->restingSplitRotation * Quaternion.AngleAxis(angle, Vector3.right);
            split.Lower.localRotation = fields->restingSplitRotation * Quaternion.AngleAxis(-angle, Vector3.right);
        }
    }
}
