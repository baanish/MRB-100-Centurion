using System;
using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace Centurion;

/// <summary>
/// The values behind CenturionPlugin.AgenticState(), read from the local player's aircraft (any aircraft, stock
/// included). Every key is present on every call (the framework reads a key it doesn't get as missing); a value that
/// can't be read, including every Centurion-only key until its system exists, holds <see cref="NotRead"/>, or
/// <see cref="NoText"/> for a text key. The remote_* keys read the first Centurion another peer simulates, as this peer
/// sees it (merged physics, G2.1).
/// </summary>
public static class AircraftReadout
{
    /// <summary>Out of range for every key, signed ones included (roll rate, pitch).</summary>
    public const double NotRead = -999;

    /// <summary>Any text key that can't be read.</summary>
    public const string NoText = "none";

    public static Dictionary<string, object> Read(bool enabled)
    {
        var state = new Dictionary<string, object>
        {
            ["mass_kg"] = NotRead,
            ["fuel_kg"] = NotRead,
            ["ejected_crew_count"] = NotRead,
            ["ejected_chute_count"] = NotRead,
            ["fans_found"] = NotRead,
            ["fan_1_rpm_ratio"] = NotRead,
            ["fan_2_rpm_ratio"] = NotRead,
            ["fan_1_turn_deg"] = NotRead,
            ["fan_2_turn_deg"] = NotRead,
            ["aoa_deg"] = NotRead,
            ["span_cmd"] = NotRead,
            ["span_frac"] = NotRead,
            ["span_locked"] = NotRead,
            ["wing_area_m2"] = NotRead,
            ["torn_root_drag_m2"] = NotRead,
            ["rcs"] = NotRead,
            ["flap_deg"] = NotRead,
            ["panel_offset_max_m"] = NotRead,
            ["panel_offset_peak_m"] = NotRead,
            ["stage1_offset_m"] = NotRead,
            ["stage2_offset_m"] = NotRead,
            ["stage1_angle_deg"] = NotRead,
            ["flex_pitch_deg"] = NotRead,
            ["flex_part"] = NoText,
            ["cg_y_m"] = NotRead,
            ["cg_z_m"] = NotRead,
            ["stage1_com_x_m"] = NotRead,
            ["stage1_com_z_m"] = NotRead,
            ["stage1_job_force_kn"] = NotRead,
            ["stage1_job_torque_pitch_knm"] = NotRead,
            ["stage1_expected_torque_pitch_knm"] = NotRead,
            ["stage1_joint_torque_knm"] = NotRead,
            ["budget_stage_force_knm"] = NotRead,
            ["budget_stage_torque_knm"] = NotRead,
            ["budget_stage_torque_clamped_knm"] = NotRead,
            ["budget_stage_clamp_ratio"] = NotRead,
            ["budget_wing_root_knm"] = NotRead,
            ["budget_tail_knm"] = NotRead,
            ["budget_other_knm"] = NotRead,
            ["budget_thrust_knm"] = NotRead,
            ["budget_applied_knm"] = NotRead,
            ["budget_dhdt_knm"] = NotRead,
            ["budget_residual_knm"] = NotRead,
            ["inertia_pitch_kgm2"] = NotRead,
            ["inertia_pitch_point_kgm2"] = NotRead,
            ["mach"] = NotRead,
            ["eas_mps"] = NotRead,
            ["nz"] = NotRead,
            ["tear"] = NoText,
            ["physics"] = NoText,
            ["detached_ratio"] = NotRead,
            ["remote_span_cmd"] = NotRead,
            ["remote_span_frac"] = NotRead,
            ["remote_panel_offset_max_m"] = NotRead,
            ["remote_panel_offset_peak_m"] = NotRead,
            ["remote_detached_stages"] = NotRead,
            ["remote_physics"] = NoText,
            ["roll_rate_dps"] = NotRead,
            ["pitch_deg_trim"] = NotRead,
            ["spoiler_L_deg"] = NotRead,
            ["spoiler_R_deg"] = NotRead,
            ["aileron_L_deg"] = NotRead,
            ["aileron_R_deg"] = NotRead,
            ["spoiler_L_split_deg"] = NotRead,
            ["spoiler_R_split_deg"] = NotRead,
            ["aileron_L_split_deg"] = NotRead,
            ["aileron_R_split_deg"] = NotRead,
            ["drag_rudder_yaw"] = NotRead,
            ["drag_rudder_L"] = NotRead,
            ["drag_rudder_R"] = NotRead,
            ["remote_drag_rudder_yaw"] = NotRead,
            ["remote_drag_rudder_L"] = NotRead,
            ["remote_drag_rudder_R"] = NotRead,
            ["remote_bomb_ammo"] = NotRead,
            ["torn_stage_dist_m"] = NotRead,
            ["wingflex_lift_g"] = NotRead,
            ["wingflex_target_m"] = NotRead,
            ["wingflex_offset_m"] = NotRead,
            ["wingflex_tip_L_m"] = NotRead,
            ["wingflex_tip_R_m"] = NotRead,
            ["wingflex_navlight_L_m"] = NotRead,
            ["wingflex_navlight_R_m"] = NotRead,
            ["wingflex_vertices"] = NotRead,
            ["wingflex_cost_ms"] = NotRead,
        };

        RadarSuite.AddDefaults(state);
        TankDiagnostics.AddDefaults(state);
        AwacsBeam.AddDefaults(state);
        CramGuard.AddDefaults(state);
        PowerReadout.AddDefaults(state);
        MissileJamming.AddDefaults(state);
        CenturionAi.AddDefaults(state);
        OwnerState.AddDefaults(state);
        BayCookoff.AddDefaults(state);
        FireDamageDiagnostics.Read(state, enabled);

        if (!enabled)
        {
            return state;
        }

        TelescopeController? remote = TelescopeController.All.FirstOrDefault(t => !t.IsLocalPlayer && !t.Simulated);
        if (remote != null)
        {
            state["remote_span_cmd"] = Round(remote.Command);
            state["remote_span_frac"] = Round(remote.Extension);
            state["remote_panel_offset_max_m"] = Round(Mathf.Max(remote.StageOffset(0), remote.StageOffset(1)));
            state["remote_panel_offset_peak_m"] = Round(remote.PeakOffset);
            state["remote_detached_stages"] = remote.DetachedStages;
            state["remote_physics"] = remote.PhysicsMode;
            state["remote_drag_rudder_yaw"] = Round(remote.DragRudderYaw);
            state["remote_drag_rudder_L"] = Round(remote.DragRudderOpen(-1f));
            state["remote_drag_rudder_R"] = Round(remote.DragRudderOpen(1f));
            if (remote.TryGetComponent(out Aircraft remoteAircraft))
            {
                state["remote_bomb_ammo"] = BombRelease.BayBombAmmo(remoteAircraft);
            }
        }

        RadarSuite.ReadRemote(state);
        AwacsBeam.ReadRemote(state);
        CramGuard.ReadRemote(state);
        PowerReadout.ReadRemote(state);
        CenturionAi.Read(state);
        OwnerState.ReadPeers(state);
        BayCookoff.Read(state);

        GameManager.GetLocalAircraft(out Aircraft aircraft);
        GameManager.GetLocalPilotDismounted(out PilotDismounted ejectedPilot);
        if (aircraft != null || ejectedPilot != null)
        {
            // The dismounted player's parent survives the loss of GetLocalAircraft; never count another aircraft's crew.
            PersistentID parent = aircraft != null ? aircraft.persistentID : ejectedPilot.parentUnit;
            var crew = UnitRegistry.allUnits.OfType<PilotDismounted>()
                .Where(p => p != null && !p.disabled && p.parentUnit == parent && p.animationState != PilotDismounted.PilotState.dead)
                .ToArray();
            state["ejected_crew_count"] = crew.Select(p => p.pilotNumber).Distinct().Count();
            state["ejected_chute_count"] = crew.Where(p => p.NetworkchuteDeployedNetwork).Select(p => p.pilotNumber).Distinct().Count();
        }

        if (aircraft == null)
        {
            return state;
        }

        state["mass_kg"] = Round(aircraft.GetMass());
        state["fuel_kg"] = Round(aircraft.GetFuelQuantity());
        TankDiagnostics.Read(aircraft, state);
        if (aircraft.TryGetComponent(out FanSpin fanSpin)) fanSpin.Read(state);
        var fanEngines = aircraft.engineStates.OfType<Turbofan>().OrderBy(e => e.name).ToArray();
        for (int i = 0; i < Mathf.Min(2, fanEngines.Length); i++) state[$"fan_{i + 1}_rpm_ratio"] = Round(fanEngines[i].GetRPMRatio());

        float wingArea = 0f;
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part is AeroPart aero && aero != null && !aero.IsDetached())
            {
                wingArea += aero.GetWingArea();
            }
        }

        state["wing_area_m2"] = Round(wingArea);
        state["rcs"] = Round(aircraft.RCS);
        FlapPreset.Read(aircraft, state);
        state["detached_ratio"] = Round(aircraft.partDamageTracker.GetDetachedRatio());

        if (aircraft.TryGetComponent(out TelescopeController telescope))
        {
            state["span_cmd"] = Round(telescope.Command);
            state["span_frac"] = Round(telescope.Extension);
            state["span_locked"] = telescope.Locked ? 1 : 0;
            state["torn_root_drag_m2"] = Round(telescope.TornRootDragArea);
            state["drag_rudder_yaw"] = Round(telescope.DragRudderYaw);
            state["drag_rudder_L"] = Round(telescope.DragRudderOpen(-1f));
            state["drag_rudder_R"] = Round(telescope.DragRudderOpen(1f));
            state["stage1_offset_m"] = Round(telescope.StageOffset(0));
            state["stage2_offset_m"] = Round(telescope.StageOffset(1));
            state["stage1_angle_deg"] = Round(telescope.StageAngle(0));
            state["flex_pitch_deg"] = Round(telescope.FlexPitchDeg);
            state["flex_part"] = telescope.FlexPart;
            state["cg_y_m"] = Round(telescope.CenterOfMassLocal.y);
            state["cg_z_m"] = Round(telescope.CenterOfMassLocal.z);
            state["stage1_com_x_m"] = Round(telescope.Stage1CenterOfMassLocal.x);
            state["stage1_com_z_m"] = Round(telescope.Stage1CenterOfMassLocal.z);
            state["stage1_job_force_kn"] = Round(telescope.Stage1JobForce / 1000f);
            state["stage1_job_torque_pitch_knm"] = Round(telescope.Stage1JobTorquePitch / 1000f);
            state["stage1_expected_torque_pitch_knm"] = Round(telescope.Stage1ExpectedTorquePitch / 1000f);
            state["stage1_joint_torque_knm"] = Round(telescope.StageJointTorque(0) / 1000f);
            if (telescope.Budget is PitchBudget budget)
            {
                // Pitch moments about the centre of mass, + nose up (PitchBudget).
                state["budget_stage_force_knm"] = Round(budget.StageForce / 1000f);
                state["budget_stage_torque_knm"] = Round(budget.StageTorque / 1000f);
                state["budget_stage_torque_clamped_knm"] = Round(budget.StageTorqueClamped / 1000f);
                state["budget_stage_clamp_ratio"] = Round(budget.StageClampRatio);
                state["budget_wing_root_knm"] = Round(budget.WingRoot / 1000f);
                state["budget_tail_knm"] = Round(budget.Tail / 1000f);
                state["budget_other_knm"] = Round(budget.OtherAero / 1000f);
                state["budget_thrust_knm"] = Round(budget.Thrust / 1000f);
                state["budget_applied_knm"] = Round(budget.Applied / 1000f);
                state["budget_dhdt_knm"] = Round(budget.MomentumRate / 1000f);
                state["budget_residual_knm"] = Round(budget.Residual / 1000f);
                state["inertia_pitch_kgm2"] = Round(budget.InertiaPitch);
                state["inertia_pitch_point_kgm2"] = Round(budget.PointMassPitch);
            }

            state["panel_offset_max_m"] = Round(Mathf.Max(telescope.StageOffset(0), telescope.StageOffset(1)));
            state["panel_offset_peak_m"] = Round(telescope.PeakOffset);
            state["mach"] = Round(telescope.Mach);
            state["eas_mps"] = Round(telescope.EasMps);
            state["nz"] = Round(telescope.Nz);
            state["tear"] = telescope.TearState;
            state["physics"] = telescope.PhysicsMode;
            float torn = telescope.TornStageDistance;
            if (!float.IsNaN(torn))
            {
                state["torn_stage_dist_m"] = Round(torn);
            }
        }

        if (aircraft.TryGetComponent(out WingFlex flex))
        {
            // The spring's state at WingFlex.ReferenceSpanM, and each side's rendered tip vertex and nav light offset up the aircraft.
            state["wingflex_lift_g"] = Round(flex.LiftG);
            state["wingflex_target_m"] = Round(flex.Target);
            state["wingflex_offset_m"] = Round(flex.Offset);
            state["wingflex_tip_L_m"] = float.IsNaN(flex.TipOffset(0)) ? NotRead : Round(flex.TipOffset(0));
            state["wingflex_tip_R_m"] = float.IsNaN(flex.TipOffset(1)) ? NotRead : Round(flex.TipOffset(1));
            state["wingflex_navlight_L_m"] = float.IsNaN(flex.RiderOffset(0)) ? NotRead : Round(flex.RiderOffset(0));
            state["wingflex_navlight_R_m"] = float.IsNaN(flex.RiderOffset(1)) ? NotRead : Round(flex.RiderOffset(1));
            state["wingflex_vertices"] = flex.Vertices;
            state["wingflex_cost_ms"] = Round(flex.CostMs);
        }

        ReadRollSurfaces(aircraft, state);

        RadarSuite.Read(state, aircraft);
        AwacsBeam.Read(state, aircraft);
        CramGuard.Read(state, aircraft);
        PowerReadout.Read(state, aircraft);
        MissileJamming.Read(state, aircraft);

        UnitPart cockpit = aircraft.cockpit;
        Rigidbody rb = aircraft.CockpitRB();
        if (cockpit != null && rb != null)
        {
            Vector3 forward = cockpit.transform.forward;
            // Unity is left-handed: positive spin about the nose axis lifts the right wing, so negate for right-roll positive.
            state["roll_rate_dps"] = Round(-Vector3.Dot(rb.angularVelocity, forward) * Mathf.Rad2Deg);
            // Pitch attitude now; a scenario reads it once trimmed (G2.9).
            state["pitch_deg_trim"] = Round(Mathf.Asin(Mathf.Clamp(forward.y, -1f, 1f)) * Mathf.Rad2Deg);
            // Body angle of attack: the airflow's angle below the nose in the cockpit's symmetry plane (G2.2).
            Vector3 air = cockpit.transform.InverseTransformDirection(rb.velocity - aircraft.GetWindVelocity());
            state["aoa_deg"] = Round(Mathf.Atan2(-air.y, air.z) * Mathf.Rad2Deg);
        }

        return state;
    }

    /// <summary>
    /// Each spoiler's and aileron's deflection about its hinge (the job's summed channel angle, + trailing edge up on the
    /// Centurion's hinges) and its split's opening, from the ControlSurface job fields the stock job turns the surface by
    /// (ControlSurfaceJob_Math.cs:62-72). Parts sit on their own rigidbodies in complex physics, so the surfaces are found
    /// through partLookup, not the aircraft's children.
    /// </summary>
    static unsafe void ReadRollSurfaces(Aircraft aircraft, Dictionary<string, object> state)
    {
        if (JobFields == null)
        {
            return;
        }

        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part == null || !(part.name.StartsWith("spoiler_") || part.name.StartsWith("aileron_")) || !part.TryGetComponent(out ControlSurface surface))
            {
                continue;
            }

            NuclearOption.Jobs.ControlSurfaceFields* fields = JobFields(surface).ptr;
            if (fields != null)
            {
                state[part.name + "_deg"] = Round(fields->currentPitch + fields->currentRoll + fields->currentYaw);
                state[part.name + "_split_deg"] = Round(fields->splitAmount);
            }
        }
    }

    static readonly AccessTools.FieldRef<ControlSurface, NuclearOption.Jobs.PtrAllocation<NuclearOption.Jobs.ControlSurfaceFields>>? JobFields =
        AccessTools.Field(typeof(ControlSurface), "JobFields") == null ? null
            : AccessTools.FieldRefAccess<ControlSurface, NuclearOption.Jobs.PtrAllocation<NuclearOption.Jobs.ControlSurfaceFields>>("JobFields");

    internal static double Round(float value) => Math.Round(value, 3);
}
