using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using HarmonyLib;
using NuclearOption.Jobs;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The pitch-moment budget about the aircraft's centre of mass on the simulating peer in complex physics (diagnostics). The
/// applied side is every AeroPart's job force at its rigidbody's centre of mass plus its job torque, as AeroPart.ApplyJobFields
/// adds them (AeroPart.cs:641-649), and every JetNozzle's thrust at its thrust transform (JetNozzle.cs:407-410). The measured
/// side is the rate of change of the angular momentum summed over every part's rigidbody, from one physics step to the next.
/// The aero job is scheduled and applied in UniTask's FixedUpdate timing (JobManager.cs:228-250), which runs ahead of scripts'
/// FixedUpdate, so the forces read here are the ones the coming physics step integrates. Gravity acts at each rigidbody's
/// centre of mass and adds nothing about the aircraft's. Landing gear forces are left out, so on the ground the residual is
/// mostly theirs. Pitch values are about the aircraft's right axis, + nose up, N m.
/// </summary>
sealed class PitchBudget
{
    static readonly FieldInfo? JobFieldsField = AccessTools.Field(typeof(AeroPart), "JobFields");
    static readonly FieldInfo? NozzlePartField = AccessTools.Field(typeof(JetNozzle), "part");
    static readonly FieldInfo? NozzleTransformField = AccessTools.Field(typeof(JetNozzle), "thrustTransform");
    static readonly FieldInfo? NozzleThrustField = AccessTools.Field(typeof(JetNozzle), "totalThrust");
    static readonly FieldInfo? NozzleProportionField = AccessTools.Field(typeof(JetNozzle), "thrustProportion");

    readonly Aircraft aircraft;
    readonly CenturionLog log;
    readonly List<JetNozzle> nozzles;
    readonly StringBuilder parts = new();
    Vector3 momentumPrev;
    float appliedPrev = float.NaN;
    float partsLoggedAt = float.NegativeInfinity;

    public float StageForce { get; private set; }
    public float StageTorque { get; private set; }
    /// <summary>Stage 1's job torque as it survives the pre-solve clamp of each stage rigidbody's angular velocity to
    /// Rigidbody.maxAngularVelocity, modelled from the stage's own inertia (see <see cref="Clamped"/>).</summary>
    public float StageTorqueClamped { get; private set; }
    /// <summary>The largest |angular velocity| a stage 1 rigidbody would reach this step with its job torque and no joint, over
    /// its Rigidbody.maxAngularVelocity; above 1 the clamp cuts the torque before the joint can pass it on.</summary>
    public float StageClampRatio { get; private set; }
    public float WingRoot { get; private set; }
    public float Tail { get; private set; }
    public float OtherAero { get; private set; }
    public float Thrust { get; private set; }
    public float Applied { get; private set; }
    /// <summary>The pitch component of dH/dt over the last physics step, and that less what was applied for it.</summary>
    public float MomentumRate { get; private set; }
    public float Residual { get; private set; }
    /// <summary>Pitch inertia about the centre of mass: every rigidbody's own tensor plus its mass at its distance, kg m2;
    /// and the point-mass part alone, which the replica scales by 2.</summary>
    public float InertiaPitch { get; private set; }
    public float PointMassPitch { get; private set; }

    public PitchBudget(Aircraft aircraft, CenturionLog log)
    {
        this.aircraft = aircraft;
        this.log = log;
        nozzles = aircraft.partLookup.Where(p => p != null).SelectMany(p => p.GetComponentsInChildren<JetNozzle>(true)).Distinct().ToList();
    }

    public void Step(float dt)
    {
        if (JobFieldsField == null)
        {
            return;
        }

        Vector3 right = aircraft.transform.right;
        List<Rigidbody> bodies = aircraft.partLookup.Where(p => p != null && !p.IsDetached() && p.rb != null).Select(p => p.rb).Distinct().ToList();
        float mass = 0f;
        Vector3 centre = Vector3.zero, velocity = Vector3.zero;
        foreach (Rigidbody rb in bodies)
        {
            mass += rb.mass;
            centre += rb.mass * rb.worldCenterOfMass;
            velocity += rb.mass * rb.velocity;
        }

        centre /= mass;
        velocity /= mass;

        Vector3 momentum = Vector3.zero;
        float inertia = 0f, pointMass = 0f;
        foreach (Rigidbody rb in bodies)
        {
            Vector3 r = rb.worldCenterOfMass - centre;
            momentum += InertiaTimes(rb, rb.angularVelocity) + rb.mass * Vector3.Cross(r, rb.velocity - velocity);
            float arm = Vector3.Cross(right, r).sqrMagnitude;
            pointMass += rb.mass * arm;
            inertia += rb.mass * arm + Vector3.Dot(right, InertiaTimes(rb, right));
        }

        InertiaPitch = inertia;
        PointMassPitch = pointMass;
        if (!float.IsNaN(appliedPrev))
        {
            MomentumRate = -Vector3.Dot(momentum - momentumPrev, right) / dt;
            Residual = MomentumRate - appliedPrev;
        }

        momentumPrev = momentum;

        float stageForce = 0f, stageTorque = 0f, stageClamped = 0f, clampRatio = 0f, wingRoot = 0f, tail = 0f, other = 0f;
        // Stage lines print once a second at most; build the per-part line only when it will print.
        bool logParts = log.StageEnabled && Time.unscaledTime - partsLoggedAt >= 1f;
        parts.Clear();
        foreach (UnitPart unitPart in aircraft.partLookup)
        {
            if (unitPart is not AeroPart part || part == null || part.IsDetached() || !TryReadJob(part, out AeroPartFields fields)
                || fields.hasForce == JobForceType.NoForce)
            {
                continue;
            }

            float force = -Vector3.Dot(Vector3.Cross(part.rb.worldCenterOfMass - centre, fields.force), right);
            float torque = fields.hasForce == JobForceType.ForceAndTorque ? -Vector3.Dot(fields.torque, right) : 0f;
            string name = part.name;
            if (name.StartsWith("wing_tele1"))
            {
                stageForce += force;
                stageTorque += torque;
                (Vector3 passed, float ratio) = Clamped(part.rb, fields.hasForce == JobForceType.ForceAndTorque ? fields.torque : Vector3.zero, dt);
                stageClamped += -Vector3.Dot(passed, right);
                clampRatio = Mathf.Max(clampRatio, ratio);
            }
            else if (name.StartsWith("wing_root") || name.StartsWith("wing_outer"))
            {
                wingRoot += force + torque;
            }
            else if (name.StartsWith("vtail") || name.StartsWith("ruddervator"))
            {
                tail += force + torque;
            }
            else
            {
                other += force + torque;
            }

            if (logParts && (force != 0f || torque != 0f))
            {
                parts.Append(Invariant($" {name} {(force + torque) / 1000f:0}"));
            }
        }

        float thrust = 0f;
        if (NozzlePartField != null && NozzleTransformField != null && NozzleThrustField != null && NozzleProportionField != null)
        {
            foreach (JetNozzle nozzle in nozzles.Where(n => n != null))
            {
                if (NozzlePartField.GetValue(nozzle) is UnitPart owner && owner != null && !owner.IsDetached()
                    && (float)NozzleProportionField.GetValue(nozzle) > 0f && NozzleTransformField.GetValue(nozzle) is Transform at)
                {
                    Vector3 f = at.forward * (float)NozzleThrustField.GetValue(nozzle);
                    thrust += -Vector3.Dot(Vector3.Cross(at.position - centre, f), right);
                }
            }
        }

        StageForce = stageForce;
        StageTorque = stageTorque;
        StageTorqueClamped = stageClamped;
        StageClampRatio = clampRatio;
        WingRoot = wingRoot;
        Tail = tail;
        OtherAero = other;
        Thrust = thrust;
        Applied = stageForce + stageTorque + wingRoot + tail + other + thrust;
        appliedPrev = Applied;
        if (logParts)
        {
            partsLoggedAt = Time.unscaledTime;
            log.Stage("pitch-budget-parts", Invariant($"pitch moments about the CoM, kN m, + nose up:{parts} thrust {thrust / 1000f:0}; dH/dt {MomentumRate / 1000f:0}, residual {Residual / 1000f:0}, I {InertiaPitch:0} (point masses {PointMassPitch:0}) kg m2"));
        }
    }

    /// <summary>
    /// The torque a rigidbody keeps of an applied torque after PhysX turns it into velocity and clamps the velocity to
    /// maxAngularVelocity, which it does before the joints are solved (bodyCoreComputeUnconstrainedVelocity in the PhysX 4
    /// solver), so a joint can only pass on what survives. Also the unclamped |angular velocity| over the cap.
    /// </summary>
    public static (Vector3 passed, float ratio) Clamped(Rigidbody rb, Vector3 torque, float dt)
    {
        Vector3 before = rb.angularVelocity;
        Vector3 after = before + InertiaInverseTimes(rb, torque) * dt;
        float ratio = after.magnitude / rb.maxAngularVelocity;
        if (ratio > 1f)
        {
            after /= ratio;
        }

        return (InertiaTimes(rb, after - before) / dt, ratio);
    }

    /// <summary>The job fields AeroJob_Math left for ApplyJobFields (AeroPart.cs:598-650); false where the part runs no job.</summary>
    public static unsafe bool TryReadJob(AeroPart part, out AeroPartFields fields)
    {
        fields = default;
        if (JobFieldsField == null || JobFieldsField.GetValue(part) is not PtrAllocation<AeroPartFields> allocation || allocation.ptr == null)
        {
            return false;
        }

        fields = *allocation.ptr;
        return true;
    }

    static Vector3 InertiaTimes(Rigidbody rb, Vector3 v)
    {
        Quaternion principal = rb.rotation * rb.inertiaTensorRotation;
        return principal * Vector3.Scale(rb.inertiaTensor, Quaternion.Inverse(principal) * v);
    }

    static Vector3 InertiaInverseTimes(Rigidbody rb, Vector3 v)
    {
        Quaternion principal = rb.rotation * rb.inertiaTensorRotation;
        Vector3 local = Quaternion.Inverse(principal) * v, i = rb.inertiaTensor;
        return principal * new Vector3(local.x / i.x, local.y / i.y, local.z / i.z);
    }
}
