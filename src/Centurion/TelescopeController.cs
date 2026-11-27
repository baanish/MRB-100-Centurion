using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Configuration;
using HarmonyLib;
using NuclearOption.NetworkTransforms;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The telescoping wing (docs/M2-DESIGN.md, "TelescopeController contract"). Every physics step, on every peer, it rate-limits
/// the Custom Axis 1 command to the extension, schedules stage 1's wing area and Mach drag rise, the body's drag rise, the roll surfaces' area and the drag rudders,
/// and slides both stages, writing each stage's UnitPart.attachInfo.localPosition to where the stage should be: the stock
/// detach rule measures against it (AeroPart.CheckAttachment, AeroPart.cs:265-281) and MergeWithParent restores it
/// (AeroPart.cs:514-522). Where the aircraft is simulated it also owns the command (the hangar guard, Debug.SpanCommand and
/// the AI schedule) and the tear (<see cref="WingTearRule"/>), which reaches the other peers through the stock part-break RPC;
/// they set the extension and any stage loss they missed from the owner's state (<see cref="OwnerState"/>).
/// Added to each Centurion when the game first sets its physics mode (Aircraft.SetLocalSim, Aircraft.cs:1289-1305).
/// </summary>
sealed class TelescopeController : MonoBehaviour, IWingAngleGauge
{
    const float TravelS = 8f;
    // Step 6's ratio of game to geometric area on the 2x span (150 to 40 m2, so 266 to stage 1 and 2's 71 m2 of run-out a side):
    // the 199 t extended aircraft lifts off at 6.4 deg (docs/M2-DESIGN.md, step 6.1).
    const float StageAreaM2 = 266f;
    // Torn roots deliberately cost 25% more thrust than clean/retracted at half fuel, no payload, 9 km/Mach 0.8.
    // tools/fm/centurion_torn_drag.py: q=12.920 kPa; deltaD=q*dragArea/2 (AeroJob_Math.cs:94-96), so 6.95 m2 per
    // root adds 89.79 kN before retrim. Clean 136.7 t needs 297.31 kN total; torn 127.7 t needs 284.32 kN without
    // this penalty and 371.61 kN with it (+24.99%). At 6 km/180 m/s the torn hold stays within 13 m of altitude.
    const float TornRootDragM2 = 6.95f;
    // Stage 1's drag rise: dragArea 2 c (Mach - M0)^2 x its current wingArea, c 25, so it scales with the panel area (step 6's
    // c 45 on 150 m2 is the same force). It is the extended aircraft's speed limit (there is no speed tear): full-throttle
    // level flight tops out at Mach 0.80 and a 10 deg dive from 9 km settles at Mach 0.81, under G2.7's 0.82 and 0.86, while
    // Mach 0.80 level at 9 km (G2.5) still holds at spool 0.90 (tools/fm centurion_span.py mach_rise, --envelope).
    const float DragRiseMach = 0.76f, DragRiseGain = 50f;
    // The inner wing's and body's drag rise, whatever the extension: dragArea 2 c (Mach - M0)^2 x each part's wingArea, c 25.
    // The game's own transonic factor adds at most 15% between Mach 0.8 and 1.2 (AeroJob_Math.cs:108-116) and its airfoils
    // carry no Mach data, so without this the retracted aircraft ran on to Mach 0.96 at 9 km, where the engines' speed
    // thrust stops it near 280 m/s TAS. With it it tops out at Mach 0.85 at 6 km and 0.88 at 9 to 11 km (tools/fm
    // centurion_span.py body_rise), as a B-52 does.
    const float BodyRiseMach = 0.82f, BodyRiseGain = 50f;
    // The inner wing and the tail cone are cut into pieces (CenturionAuthor's CutParts), each carrying its share.
    static readonly string[] BodyRiseParts = { "wing_root_L", "wing_root_R", "wing_outer_L", "wing_outer_R", "fuselage_F",
        "fuselage_R", "cockpit", "tailcone", "tail_end" };
    // Added to the authored 12 and 4 m2 at full extension, 5.5 times them: stage 1's area 25 m out multiplies the roll
    // damping, and with these the extended roll rate is 9.7 deg/s at 6 km and 150 m/s, as on step 6.
    const float AileronAreaM2 = 54f, SpoilerAreaM2 = 18f;
    // The full span adds this to the authored radarSize (CenturionAuthor, 13 retracted), so 26 extended: the span doubles the
    // footprint the Chimera-scaled value rests on (owner, 2026-10-19).
    // Above 1.0 every stock radar already sees it at twice its maxRange (Radar.cs:174-204, RadarParams.cs:26-43), so the
    // extension costs margin against ground clutter and the jammer, not detection range.
    const float ExtendedRcs = 13f;
    // Drag rudders (B-2 style split ailerons): yaw input adds up to this dragArea to the aileron on the side the nose should
    // turn toward. With the V-tail it holds one engine out at 199 t from 84 m/s, against 90 on the tail alone and the 96 m/s
    // rotation (docs/M2-DESIGN.md, step 6.1). The ailerons' stock splits would do it from data, but they follow the
    // fly-by-wire's yaw output, and a split's servo lag inside its yaw-rate loop set the hold's high-speed turn oscillating
    // (centurion_circuit, run 20261012-234630; tools/fm centurion_turn split_forces), so the splits are only the airbrakes.
    // DragRudderSplits shows the drag rudders on the splits without their drag. The FilterInputs prefix captures the input
    // and the sent copy carries it (OwnerState's snapshot postfix), so without the owner-state patches they stay shut.
    const float DragRudderM2 = 20f;
    // They open only past this much yaw input, fully at full input, and take DragRudderTravelS to travel. The input is the yaw
    // before the fly-by-wire (Aircraft.FilterInputs): its output, 3 x (input - yaw rate) + 0.05 x sideslip in degrees with the
    // Alkyon's yawTightness and yawWeathervaning (ControlsFilter.cs:280-286), passes 0.75 from a quarter of the input or the
    // damper alone, so an autopilot's small corrections opened them. Reading the input also keeps the travel time out of that loop.
    const float DragRudderFrom = 0.75f, DragRudderTravelS = 1f;
    // The medium hangar (UnitDefinition hangar_med, the only one the Centurion fits) is 79.9 m wide and its spawn point is its
    // floor centre, 22.6 m behind the front, so its corners are 46 m from that point; the extended tips are 44.5 m from the
    // aircraft's origin (43.6 m out, 9.1 m behind it). Within HangarReachM of the spawn point a tip can touch the building
    // at some heading; straight in, the tips clear the front from 31.7 m. Every medium hangar stands at least 115 m from a
    // runway's centreline (the plugin's geometry log, both maps), so no takeoff or landing roll passes inside it.
    const float HangarReachM = 46f + 44.5f;
    // Distance the stages are home by, beyond the reach.
    const float HangarMarginM = 10f;
    // CmdBreakPart allows 60 calls, refilled 10 a second (Unit.cs:1449); a tear asks twice a second until the detach comes back.
    const float TearRetryS = 0.5f;
    // Stage 1's centerOfLift torque reaches the airframe only through its slider, and PhysX first turns it into the stage's
    // own angular velocity and clamps that to Rigidbody.maxAngularVelocity before it solves the joints. The game's 14 rad/s
    // (Physics.defaultMaxAngularSpeed) on the stage's 1,607 kg m2 at 60 Hz let 1.35 MN m a side through, a quarter of a heavy
    // takeoff's 5.1, so above about 3 deg the extended aircraft pitched up as if the offset were missing. 1,000 passes 96 MN m.
    const float StageSpinCap = 1000f;
    // A remote copy's velocity is written on from the network snapshot each rendered frame (ApplySnapshot,
    // AircraftNetworkTransform.cs:457-488; snapshots about every 0.05 s), not integrated from its forces, so one physics
    // step's difference depends on how frames and snapshots fall across it, and a correction lands in a single step. Remote
    // Nz drives only the wing flex (the tear runs where the aircraft is simulated), so there it is the acceleration
    // low-passed over this, longer than the snapshot interval and short against the flex's 0.6 Hz...
    const float RemoteAccelTauS = 0.25f;
    // ...and a step that changes the velocity by more than this is a correction (a warp, a late or bunched snapshot, a
    // joiner's first), left out: a 4.5 g pull adds about 2 m/s in one 0.05 s interval.
    const float RemoteJumpMps = 10f;
    // The airborne AI schedule, on equivalent airspeed alone: extend below one, retract above the other, hold in between.
    // Deliberately no Mach limit: one retracted the wing at the cruise height, where the retracted aircraft can't hold
    // height (docs/GATES.md G2.12), and drag already stops the extended aircraft near Mach 0.80.
    const float ExtendBelowEas = 190f, RetractAboveEas = 205f;
    // An observer follows the owner's extension (OwnerState) at twice the travel rate, so a gap a lost snapshot leaves closes
    // in under a second, and jumps a gap wider than this (a late joiner's first word, a long loss) at once.
    const float FollowRate = 2f, FollowJump = 0.25f;
    // A stage the owner has lost and this copy still carries, for this long, is one whose part-break RPC this peer never got
    // (it joined after it): it comes off here as the RPC would take it (Unit.cs:2193-2203). The RPC is reliable and sent before
    // the snapshot carrying the loss, so on a peer that was present it lands first.
    const float ReplayGraceS = 1f;

    static readonly string[] Sides = { "L", "R" };

    static readonly FieldInfo? AttachInfoField = AccessTools.Field(typeof(UnitPart), "attachInfo");
    static readonly FieldInfo? LocalPositionField = AttachInfoField == null ? null : AccessTools.Field(AttachInfoField.FieldType, "localPosition");
    // Written by reference every step: FieldInfo.SetValue would box the Vector3 four times a step on every peer.
    static readonly AccessTools.FieldRef<object, Vector3>? LocalPosition =
        LocalPositionField == null ? null : AccessTools.FieldRefAccess<Vector3>(AttachInfoField!.FieldType, "localPosition");
    static readonly FieldInfo? StreamliningField = AccessTools.Field(typeof(AeroPart), "streamlining");
    static readonly FieldInfo? WingAreaField = AccessTools.Field(typeof(AeroPart), "wingArea");
#if CENTURION_DEV
    static readonly FieldInfo? ParentPartField = AttachInfoField == null ? null : AccessTools.Field(AttachInfoField.FieldType, "parentPart");
    static readonly FieldInfo? LocalRotationField = AttachInfoField == null ? null : AccessTools.Field(AttachInfoField.FieldType, "localRotation");
#endif

    internal static readonly PatchTarget[] PatchTargets =
    {
        // A stage this peer took off from the owner's state is already detached; a part-break RPC arriving after it would
        // detach it again, and AeroPart.Detach adds a second Rigidbody (AeroPart.cs:299-309).
        new("owner-state", typeof(Unit), "UserCode_RpcBreakPart_-1087911989", new[] { typeof(byte), typeof(Vector3Compressed), typeof(Vector3Compressed) },
            prefix: AccessTools.Method(typeof(TelescopeController), nameof(BeforeBreakPart))),
        new("telescope", typeof(Aircraft), nameof(Aircraft.SetComplexPhysics),
            postfix: AccessTools.Method(typeof(TelescopeController), nameof(AfterComplexPhysics))),
        new("telescope", typeof(Aircraft), nameof(Aircraft.SetSimplePhysics),
            postfix: AccessTools.Method(typeof(TelescopeController), nameof(AfterSimplePhysics))),
        // The stock AI states write Custom Axis 1 as a flap command in this step (AIPilotTakeoffState.cs:85-118,
        // AIPilotLandingState.cs:291, 393, 453); the schedule overwrites it straight after, before anything reads it.
        new("telescope", typeof(Pilot), nameof(Pilot.Pilot_OnAeroInputsApplied),
            postfix: AccessTools.Method(typeof(TelescopeController), nameof(AfterPilotStep))),
        // The player's state and the AI's autopilot each write the stick and then filter it in place (PilotPlayerState.cs:59-70,
        // AutopilotPlane.cs:121-122): every aircraft, every physics step.
        new("telescope", typeof(Aircraft), nameof(Aircraft.FilterInputs),
            prefix: AccessTools.Method(typeof(TelescopeController), nameof(BeforeFilterInputs))),
    };

    internal static CenturionLog Log = null!;
#if CENTURION_DEV
    internal static ConfigEntry<bool> Diagnostics = null!;
    internal static ConfigEntry<float> SpanCommand = null!;
    internal static ConfigEntry<float> StageMaxAngularVelocity = null!;
    internal static ConfigEntry<bool> PitchBudgetEnabled = null!;
    internal static ConfigEntry<bool> DebugTear = null!;

    /// <summary>Every live Centurion's controller, local and remote, for the readout.</summary>
    internal static readonly List<TelescopeController> All = new();
#endif

    sealed class Stage
    {
        public AeroPart Part = null!;
        public AeroPart Parent = null!;
        /// <summary>That side's wing root, whose loss takes the whole wing (<see cref="OneStage1Lost"/>); null if absent.</summary>
        public AeroPart? Root;
        public object AttachInfo = null!;
        public Vector3 Retracted, Extended;
        public ConfigurableJoint? Slider;
        /// <summary>The position last written to the stage's pose and slider; NaN after a physics mode change, which rebuilt both.</summary>
        public Vector3 Placed = new(float.NaN, float.NaN, float.NaN);
#if CENTURION_DEV
        public float Offset;
#endif
#if CENTURION_DEV
        public float AngleDeg, JointTorque;
#endif
        public float DetachAskedAt = float.NegativeInfinity;
        /// <summary>When the owner's state first showed this stage lost while it is still on here.</summary>
        public float OwnerLostAt = float.PositiveInfinity;
        public bool Freed, CollisionsReleased, Replayed;
    }

    sealed class Scheduled
    {
        public AeroPart Part = null!;
        public float AreaPerExtension, AppliedArea, AppliedDrag;
        /// <summary>The authored wingArea a body part's drag rise scales with; 0 for the scheduled surfaces.</summary>
        public float RiseArea;
        /// <summary>+1 on the right, -1 on the left for a drag rudder: the yaw input that opens it; 0 for none.</summary>
        public float YawSide;
        /// <summary>An inner wing root, which carries the torn root's drag once a stage is gone.</summary>
        public bool Root;
    }

    Aircraft aircraft = null!;
    WingTearRule tear = null!;
    readonly List<Stage>[] stages = { new(), new() }; // [0] stage 1 L and R, [1] stage 2 L and R
    readonly List<Stage> allStages = new();
    readonly List<Scheduled> panels = new(), rollSurfaces = new(), bodyParts = new();
    HangarGuard hangarGuard = null!;
    OwnerState? owner;
    SurfaceMotionSound motionSound = null!;
    bool locked, broken, tearing, snapRetract, ownerStateOff;
    float aiCommand, stickYaw, dragRudderL, dragRudderR, appliedRcs;
    Vector3 velocityPrev, accelFiltered;
#if CENTURION_DEV
    readonly List<(UnitPart part, UnitPart parent, Quaternion rest)> flexParts = new();
    readonly HashSet<Rigidbody> massBodies = new();
#endif

    public float Command { get; private set; }
    public float Extension { get; private set; }
    public float Mach { get; private set; }
    public float EasMps { get; private set; }
    public float Nz { get; private set; } = 1f;
    public bool Locked => locked;
    public bool IsLocalPlayer => GameManager.GetLocalAircraft(out Aircraft local) && local == aircraft;
#if CENTURION_DEV
    public float TornRootDragArea { get; private set; }
    public string TearState => tear.State;
    public string PhysicsMode => aircraft.simplePhysics ? "simple" : "complex";
    public bool Simulated => aircraft.LocalSim;
    /// <summary>The largest pitch bend of any part against its parent since the last read (complex physics, diagnostics), degrees, + nose up.</summary>
    public float FlexPitchDeg { get; private set; }
    public string FlexPart { get; private set; } = "none";
    /// <summary>The largest bend about any axis of a tail part (rear fuselage aft) against its parent, degrees: the owner's
    /// ruling is that the tail is as rigid as a stock aircraft's and only the wing flexes (docs/DECISIONS.md, 2026-11-24).</summary>
    public float TailBendDeg { get; private set; }
    public string TailBendPart { get; private set; } = "none";
    /// <summary>The aircraft's centre of mass from every part's rigidbody, in the root part's frame (complex physics, diagnostics).</summary>
    public Vector3 CenterOfMassLocal { get; private set; }
    /// <summary>Stage 1 left's rigidbody centre of mass, where the game applies its force, in the root part's frame.</summary>
    public Vector3 Stage1CenterOfMassLocal { get; private set; }
    /// <summary>Stage 1 left's aero force as the job computed it, N, and the pitch component (about the aircraft's right axis, + nose
    /// down) of the torque the job computed and of the torque its centerOfLift should give for that force, N m.</summary>
    public float Stage1JobForce { get; private set; }
    public float Stage1JobTorquePitch { get; private set; }
    public float Stage1ExpectedTorquePitch { get; private set; }
    /// <summary>The pitch-moment budget (complex physics, diagnostics); null until the first diagnostics step.</summary>
    public PitchBudget? Budget { get; private set; }
#endif
    // The HUD's span gauge (SpanGauge) reads the extension in percent. SetLocalSim adds this controller before the local
    // player's HUD extras spawn (Aircraft.cs:1181, 1227), so the stock gauge finds it when its HUDAppManager starts.
    public float GetWingAngle() => Extension * 100f;
    public float GetLowerAngleLimit() => 0f;
    public float GetUpperAngleLimit() => 100f;
    /// <summary>How far the drag rudder on a side (+1 right, -1 left) should open for this yaw input, 0 to 1.</summary>
    internal static float DragRudderOpening(float yawSide, float yaw) => Mathf.Clamp01((yawSide * yaw - DragRudderFrom) / (1f - DragRudderFrom));
    /// <summary>How far the drag rudder on a side (+1 right, -1 left) is open, 0 to 1: its drag and its drawn splits both follow this.</summary>
    internal float DragRudderOpen(float yawSide) => yawSide > 0f ? dragRudderR : dragRudderL;
    /// <summary>The yaw input the drag rudders follow: on the simulating peer the one before the fly-by-wire, on a copy the owner's.</summary>
    public float DragRudderYaw => aircraft.LocalSim ? stickYaw : aircraft.GetInputs().yaw;
    /// <summary>The yaw input the sent copy carries in place of the fly-by-wire's output (OwnerState's snapshot postfix).</summary>
    internal float SentYaw => stickYaw;
#if CENTURION_DEV
    public float StageOffset(int stage) => stages[stage].Count == 0 ? 0f : stages[stage].Max(s => s.Offset);
    /// <summary>The largest angle between a stage and the part it slides on (they are built aligned), degrees.</summary>
    public float StageAngle(int stage) => stages[stage].Count == 0 ? 0f : stages[stage].Max(s => s.AngleDeg);
    /// <summary>The largest torque a stage's slider carries (Joint.currentTorque), N m; 0 in merged physics.</summary>
    public float StageJointTorque(int stage) => stages[stage].Count == 0 ? 0f : stages[stage].Max(s => s.JointTorque);
    /// <summary>The nearest torn stage 1's distance from the aircraft's root, m; NaN while none is off (or once the debris is gone).</summary>
    public float TornStageDistance
    {
        get
        {
            float nearest = float.NaN;
            foreach (Stage stage in stages[0])
            {
                if (stage.Part != null && stage.Part.IsDetached())
                {
                    float d = Vector3.Distance(stage.Part.transform.position, aircraft.transform.position);
                    nearest = float.IsNaN(nearest) ? d : Mathf.Min(nearest, d);
                }
            }

            return nearest;
        }
    }

    /// <summary>The largest stage offset any physics step has measured on this aircraft.</summary>
    public float PeakOffset { get; private set; }
#endif
    /// <summary>
    /// The lost stages as <see cref="OwnerState"/> sends them: bit 0 stage 1 left, 1 stage 1 right, 2 stage 2 left, 3 stage 2
    /// right. A stage 2 counts only when it came off its stage 1; one riding a lost stage 1 goes with it.
    /// </summary>
    public int LostMask
    {
        get
        {
            if (broken)
            {
                return 0;
            }

            int mask = 0;
            for (int side = 0; side < 2; side++)
            {
                Stage inner = stages[0][side], outer = stages[1][side];
                if (inner.Part == null || inner.Part.IsDetached())
                {
                    mask |= 1 << side;
                }
                else if (outer.Part == null || outer.Part.IsDetached())
                {
                    mask |= 4 << side;
                }
            }

            return mask;
        }
    }

    public int DetachedStages
    {
        get
        {
            int detached = 0;
            foreach (Stage stage in allStages)
            {
                if (stage.Part == null || stage.Part.IsDetached())
                {
                    detached++;
                }
            }

            return detached;
        }
    }

    static void AfterComplexPhysics(Aircraft __instance) => For(__instance)?.OnComplexPhysics();

    static void AfterSimplePhysics(Aircraft __instance) => For(__instance)?.OnSimplePhysics();

    /// <summary>A stage's retracted position in the frame of the part it slides on, as authored; null for any other part.</summary>
    public Vector3? RetractedPosition(UnitPart part) => allStages.Find(s => s.Part == part)?.Retracted;

    static bool BeforeBreakPart(Unit __instance, byte partID) =>
        !(__instance is Aircraft aircraft && CenturionSystems.Of(aircraft)?.Telescope is { } controller
            && controller.allStages.Exists(s => s.Replayed && s.Part != null && s.Part.id == partID));

    /// <summary>The Centurion's two rules on the stick: the yaw input before the fly-by-wire, which the drag rudders follow,
    /// and the AI's load limit on the pitch stick (<see cref="AiLoadLimit"/>).</summary>
    static void BeforeFilterInputs(Aircraft __instance)
    {
        if (CenturionSystems.Of(__instance)?.Telescope is not { } controller)
        {
            return;
        }

        controller.stickYaw = __instance.GetInputs().yaw;
        AiLoadLimit.Apply(__instance, controller);
    }

    static void AfterPilotStep(Pilot __instance)
    {
        if (CenturionSystems.Of(__instance.aircraft)?.Telescope is { broken: false } controller && controller.aircraft.LocalSim)
        {
            controller.OwnCommand();
        }
    }

    /// <summary>The aircraft's controller, added on first sight; null for any other aircraft or when the game lacks a member it needs.</summary>
    static TelescopeController? For(Aircraft aircraft)
    {
        if (!CenturionSystems.IsCenturion(aircraft.definition))
        {
            return null;
        }

        if (aircraft.TryGetComponent(out TelescopeController existing))
        {
            return existing.broken ? null : existing;
        }

        var controller = aircraft.gameObject.AddComponent<TelescopeController>();
        controller.Bind(aircraft);
        return controller.broken ? null : controller;
    }

    void Bind(Aircraft owner)
    {
        aircraft = owner;
        motionSound = SurfaceMotionSound.For(aircraft);
        hangarGuard = new HangarGuard(aircraft);
        tear = new WingTearRule(Log);
        // Without its complex-physics postfix the stages keep stock FixedJoints while attachInfo slides, and the stock rule
        // detaches a stage once it is 0.5 m off (AeroPart.cs:271-279); without the others the command or the sliders go stale.
        if (CenturionPlugin.FeaturesOff.Contains("telescope"))
        {
            Stop("a telescope patch is missing (see the Harmony lines), so the span stays retracted");
            return;
        }

        if (LocalPosition == null || StreamliningField == null || WingAreaField == null)
        {
            Stop("UnitPart.attachInfo.localPosition, AeroPart.streamlining or AeroPart.wingArea is missing in this game build");
            return;
        }

        var parts = aircraft.partLookup.OfType<AeroPart>().ToDictionary(p => p.name);
        foreach (string side in Sides)
        {
            for (int i = 0; i < 2; i++)
            {
                string name = "wing_tele" + (i + 1) + "_" + side;
                string parentName = i == 0 ? "wing_outer_" + side : "wing_tele1_" + side; // stage 1 slides in the outer wing
                if (!parts.TryGetValue(name, out AeroPart part) || !parts.TryGetValue(parentName, out AeroPart parent))
                {
                    Stop($"no {name} on {parentName}");
                    return;
                }

                Transform end = parent.transform.Find(name + "_extended");
                if (end == null)
                {
                    Stop($"{parentName} has no {name}_extended marker (CenturionAuthor's slide ends)");
                    return;
                }

                object attach = AttachInfoField!.GetValue(part);
                var stage = new Stage { Part = part, Parent = parent, Root = parts.TryGetValue("wing_root_" + side, out AeroPart root) ? root : null,
                    AttachInfo = attach, Extended = end.localPosition, Retracted = LocalPosition(attach) };
                stages[i].Add(stage);
                allStages.Add(stage);
            }

            panels.Add(new Scheduled { Part = parts["wing_tele1_" + side], AreaPerExtension = StageAreaM2 });
            rollSurfaces.Add(new Scheduled { Part = parts["aileron_" + side], AreaPerExtension = AileronAreaM2, YawSide = side == "R" ? 1f : -1f });
            rollSurfaces.Add(new Scheduled { Part = parts["spoiler_" + side], AreaPerExtension = SpoilerAreaM2 });
        }

        // The root part (the centre fuselage) and the named body and inner wing parts.
        foreach (AeroPart part in parts.Values.Where(p => p.gameObject == aircraft.gameObject || BodyRiseParts.Contains(p.name)))
        {
            bodyParts.Add(new Scheduled { Part = part, RiseArea = (float)WingAreaField!.GetValue(part), Root = part.name == "wing_root_L" || part.name == "wing_root_R" });
        }

#if CENTURION_DEV
        if (ParentPartField != null && LocalRotationField != null)
        {
            foreach (UnitPart part in aircraft.partLookup)
            {
                object? info = AttachInfoField!.GetValue(part);
                if (info != null && ParentPartField.GetValue(info) is UnitPart parent)
                {
                    flexParts.Add((part, parent, (Quaternion)LocalRotationField.GetValue(info)));
                }
            }
        }
#endif

        // Without the sent copy the drag rudders would open on the fly-by-wire's output on every other peer, so they stay shut;
        // a copy also needs the owner's state to replay a lost stage.
        ownerStateOff = CenturionPlugin.FeaturesOff.Contains("owner-state");
        if (ownerStateOff)
        {
            Log.Warning("drag rudders off: an owner-state patch is missing (see the Harmony lines)");
        }

        gameObject.AddComponent<DragRudderSplits>().Bind(aircraft, this, rollSurfaces.Where(s => s.YawSide != 0f).Select(s => (s.Part, s.YawSide)));
        WingDisplay.Attach(aircraft, this);
        gameObject.AddComponent<WingFlex>().Bind(this);
        foreach (Stage stage in stages[0]) stage.Parent.onJointBroken += ReleaseOuterWingBraces;
        foreach (Stage stage in stages[0]) stage.Part.onJointBroken += ReleaseBrokenStage;
#if CENTURION_DEV
        All.Add(this);
#endif
        Log.Info(Invariant($"telescope on {aircraft.name} ({(aircraft.LocalSim ? "simulated here" : "remote")}): travel {TravelS} s, stage 1 {StageAreaM2} m2 a side, stage travel {Vector3.Distance(stages[0][0].Retracted, stages[0][0].Extended):0.00} m, body drag rise on {bodyParts.Count} parts, {bodyParts.Sum(b => b.RiseArea):0} m2"));
    }

    void Stop(string why)
    {
        broken = true;
        Log.Error("telescope off: " + why);
    }

    void OnDisable()
    {
        if (motionSound != null) motionSound.WingMotion(0f, true);
    }

    void OnDestroy()
    {
        foreach (Stage stage in stages[0])
        {
            if (stage.Parent != null) stage.Parent.onJointBroken -= ReleaseOuterWingBraces;
            if (stage.Part != null) stage.Part.onJointBroken -= ReleaseBrokenStage;
        }
#if CENTURION_DEV
        All.Remove(this);
#endif
    }

    void ReleaseOuterWingBraces(UnitPart outerWing)
    {
        if (!isActiveAndEnabled || !aircraft.LocalSim) return;

        // The stock tensors release these braces when the whole wing leaves. The outer wing can lose its
        // own joint first, leaving the strut pinned to the inner strut and nacelle across that break.
        bool left = outerWing.name == "wing_outer_L";
        string outerStrut = left ? "strut_outer_L" : "strut_outer_R";
        string innerStrut = left ? "strut_inner_L" : "strut_inner_R";
        string nacelle = left ? "nacelle_1" : "nacelle_2";
        foreach (AeroPart owner in aircraft.partLookup.OfType<AeroPart>())
        {
            if (owner == null) continue;
            string? held = owner.name == outerStrut ? innerStrut : owner.name == nacelle ? outerStrut : null;
            if (held == null) continue;

            foreach (PartJoint brace in owner.Joints)
            {
                if (brace.connectedPart == null || brace.connectedPart.name != held || brace.joint == null) continue;
                Log.Stage("outer wing brace " + owner.name, Invariant($"{owner.name} to {held} released after {outerWing.name} broke, was {brace.joint.breakForce:0} N and {brace.joint.breakTorque:0} N m"));
                // A physics break on the nacelle would trip the wing root even at full health.
                Destroy(brace.joint);
            }
        }
    }

    /// <summary>
    /// A stage 1 panel whose slider breaks (at 0 hp the stock rescale zeroes its break force, AeroPart.cs:554-563, and a hit
    /// never detaches an AeroPart, UnitPart.cs:326) stays on the aircraft until the stock rule takes it off 0.5 m out
    /// (AeroPart.cs:265-279), and its hulls, nested in the outer wing, collide with it until then: that contact broke the outer
    /// strut, then the wing root. So the panel and its stage 2 stop touching the aircraft at the break; the stock rule still
    /// detaches it, and the symmetric jettison follows through <see cref="OneStage1Lost"/>.
    /// </summary>
    void ReleaseBrokenStage(UnitPart panel)
    {
        if (!isActiveAndEnabled || panel.IsDetached()) return;
        ReleaseTornColliders(panel);
    }

    /// <summary>
    /// AeroPart.CreateJoints has just given each part FixedJoints that lock the pose it was created in (AeroPart.cs:355-375).
    /// Each stage's joint to the part it slides on becomes a ConfigurableJoint locked on all six axes whose connected anchor
    /// is the commanded position, moved every step, so the stage is held as rigidly as a stock FixedJoint wherever it is.
    /// It goes into the stock PartJoint, so merging destroys it (AeroPart.cs:523-529) and damage scales its break force
    /// (AeroPart.cs:554-563). Stage 2's brace to the inner wing becomes a free ConfigurableJoint: it only keeps their nested
    /// colliders from colliding, as a stock joint does (enableCollision false).
    /// </summary>
    void OnComplexPhysics()
    {
        foreach (List<Stage> list in stages)
        {
            foreach (Stage stage in list.Where(s => s.Part != null && !s.Part.IsDetached()))
            {
                PartJoint[] joints = stage.Part.Joints;
                for (int i = 0; i < joints.Length; i++)
                {
                    bool slider = i == 0;
                    if (joints[i].joint != null)
                    {
                        Destroy(joints[i].joint);
                    }

                    var joint = stage.Part.gameObject.AddComponent<ConfigurableJoint>();
                    joint.connectedBody = joints[i].connectedPart.rb;
                    joint.enableCollision = false;
                    var motion = slider ? ConfigurableJointMotion.Locked : ConfigurableJointMotion.Free;
                    joint.xMotion = joint.yMotion = joint.zMotion = motion;
                    joint.angularXMotion = joint.angularYMotion = joint.angularZMotion = motion;
                    // As AeroPart.CreateJoints sets its FixedJoints (AeroPart.cs:367-368).
                    joint.breakForce = joints[i].breakForce * 10f;
                    joint.breakTorque = joints[i].breakTorque * 10f;
                    if (slider)
                    {
                        joint.autoConfigureConnectedAnchor = false;
                        joint.anchor = Vector3.zero;
                        joint.connectedAnchor = Commanded(stage);
                        stage.Slider = joint;
                        stage.Placed = joint.connectedAnchor;
                    }

                    joints[i].joint = joint;
                }
            }
        }

    }

    /// <summary>MergeWithParent has destroyed the sliders with the other joints and put each stage at attachInfo.localPosition.</summary>
    void OnSimplePhysics()
    {
        foreach (Stage stage in allStages)
        {
            stage.Slider = null;
            stage.Placed = new Vector3(float.NaN, float.NaN, float.NaN);
        }

    }

    void FixedUpdate()
    {
        if (broken || aircraft == null)
        {
            return;
        }

        float dt = Time.fixedDeltaTime;
        if (!locked) locked = DetachedStages > 0;

        float rate = 1f;
        if (aircraft.LocalSim)
        {
            Command = OwnCommand();
        }
        else if ((owner ??= CenturionSystems.Of(aircraft)?.Owner) is { Received: true } state)
        {
            ReplayOwnerLoss(state);
            Command = state.Extension;
            rate = FollowRate;
            snapRetract = Mathf.Abs(Command - Extension) > FollowJump;
        }
        else
        {
            Command = locked ? 0f : Mathf.Clamp01(aircraft.GetInputs().customAxis1);
        }

        ReleaseTornColliders();

        float previousExtension = Extension;
        bool snapped = snapRetract && Extension != Command;
        Extension = snapped ? Command : Mathf.MoveTowards(Extension, Command, rate * dt / TravelS);
        snapRetract = false;
        // A delta, as for the wing area: the hardpoints add their mounts' RCS to the same field (Hardpoint.cs:96, 167-169).
        aircraft.ModifyRCS(ExtendedRcs * Extension - appliedRcs);
        appliedRcs = ExtendedRcs * Extension;
        ReadFlight(dt);
        ScheduleAero(dt);
        Slide(snapped);
        CapStageSpin();
#if CENTURION_DEV
        if (Diagnostics.Value && !aircraft.simplePhysics && IsLocalPlayer)
        {
            MeasureFlex();
            if (aircraft.LocalSim && PitchBudgetEnabled.Value)
            {
                Budget ??= new PitchBudget(aircraft, Log);
                Budget.Step(dt);
            }
        }

        if (aircraft.LocalSim && (tear.Step(Extension, Nz, dt) || !tearing && (OneStage1Lost() || DebugTearDue())))
#else
        if (aircraft.LocalSim && (tear.Step(Extension, Nz, dt) || !tearing && OneStage1Lost()))
#endif
        {
            tearing = true;
        }

        if (tearing)
        {
            tearing = !Tear();
        }
        motionSound.WingMotion(Mathf.Clamp01(Mathf.Abs(Extension - previousExtension) * TravelS / (rate * dt)),
            snapped || locked || tearing || DetachedStages > 0 || !isActiveAndEnabled);
    }

    /// <summary>
    /// Where the aircraft is simulated: the command, written back to Custom Axis 1 so it replicates. Nothing extends a lost
    /// span or inside the hangar guard; then Debug.SpanCommand on the local player; then, while a stock AI state flies the
    /// aircraft (an AI pilot, or the framework's fly modes on the player), the AI schedule; else the pilot's own axis.
    /// </summary>
    float OwnCommand()
    {
        ControlInputs inputs = aircraft.GetInputs();
        float command;
        HangarGuardAction guard = locked ? HangarGuardAction.Clear : hangarGuard.Approach(HangarReachM, HangarMarginM, Extension, TravelS);
        if (locked || guard != HangarGuardAction.Clear)
        {
            command = 0f;
            snapRetract |= guard == HangarGuardAction.Snap;
        }
#if CENTURION_DEV
        else if (SpanCommand.Value >= 0f && Diagnostics.Value && IsLocalPlayer)
        {
            command = SpanCommand.Value;
        }
#endif
        else if (aircraft.pilots.Length > 0 && aircraft.pilots[0].currentState is PilotBaseState state && state is not PilotPlayerState)
        {
            command = AiSchedule(state);
        }
        else
        {
            command = Mathf.Clamp01(inputs.customAxis1);
        }

        inputs.customAxis1 = command;
        return command;
    }

    float AiSchedule(PilotBaseState state)
    {
        aiCommand = state switch
        {
            PilotParkedState or AIPilotTaxiState => 0f,
            AIPilotTakeoffState or AIPilotLandingState or AIPilotShortLandingState => 1f,
            _ when EasMps < ExtendBelowEas => 1f,
            _ when EasMps > RetractAboveEas => 0f,
            _ => aiCommand,
        };
        return aiCommand;
    }

    /// <summary>
    /// Mach from the airspeed and the speed of sound at the aircraft's altitude, the inputs the aero job's transonic factor
    /// uses (AeroJob_Math.cs:83-100); EAS from the game's air density; load factor along the aircraft's up from the cockpit's
    /// acceleration plus gravity (filtered on a remote copy, <see cref="RemoteAccelTauS"/>). Stock Aircraft.gForce is |dv|/g
    /// with no gravity term, so it reads 0 in level flight (Aircraft.cs:1869-1873).
    /// </summary>
    void ReadFlight(float dt)
    {
        Rigidbody rb = aircraft.CockpitRB();
        Vector3 velocity = rb.velocity;
        float altitude = aircraft.transform.GlobalPosition().y;
        float tas = (velocity - aircraft.GetWindVelocity()).magnitude;
        Mach = tas / LevelInfo.GetSpeedOfSound(altitude);
        EasMps = tas * Mathf.Sqrt(LevelInfo.GetAirDensity(altitude) / LevelInfo.GetAirDensity(0f));
        if (velocityPrev != Vector3.zero)
        {
            Vector3 accel = (velocity - velocityPrev) / dt;
            if (!aircraft.LocalSim)
            {
                if ((velocity - velocityPrev).magnitude < RemoteJumpMps)
                {
                    accelFiltered += (accel - accelFiltered) * Mathf.Min(dt / RemoteAccelTauS, 1f);
                }

                accel = accelFiltered;
            }

            Nz = Vector3.Dot(accel / 9.81f + Vector3.up, aircraft.cockpit.transform.up);
        }

        velocityPrev = velocity;
    }

    /// <summary>
    /// Deltas against what this controller applied, never absolute sets: stock adds streamlining to dragArea when a child
    /// breaks off (AeroPart.cs:275-278). The job reads both fields every step (AeroPart.UpdateJobFields, AeroPart.cs:502-512);
    /// remote peers run no aero job (AeroPart.cs:113), but keeping the fields current there keeps a handover consistent.
    /// </summary>
    void ScheduleAero(float dt)
    {
        float rise = Mach > DragRiseMach ? DragRiseGain * (Mach - DragRiseMach) * (Mach - DragRiseMach) : 0f;
        foreach (Scheduled panel in panels)
        {
            float area = panel.AreaPerExtension * Extension;
            Apply(panel, area, rise * area);
        }

        float bodyRise = Mach > BodyRiseMach ? BodyRiseGain * (Mach - BodyRiseMach) * (Mach - BodyRiseMach) : 0f;
#if CENTURION_DEV
        TornRootDragArea = 0f;
#endif
        foreach (Scheduled body in bodyParts)
        {
            float tornDrag = locked && body.Root && body.Part != null && !body.Part.IsDetached() ? TornRootDragM2 : 0f;
            Apply(body, 0f, bodyRise * body.RiseArea + tornDrag);
#if CENTURION_DEV
            TornRootDragArea += tornDrag;
#endif
        }

        // The airbrakes are the surfaces' stock splits (CenturionAuthor's Surfaces); the drag rudders are here.
        float yaw = ownerStateOff ? 0f : DragRudderYaw;
        dragRudderL = Mathf.MoveTowards(dragRudderL, DragRudderOpening(-1f, yaw), dt / DragRudderTravelS);
        dragRudderR = Mathf.MoveTowards(dragRudderR, DragRudderOpening(1f, yaw), dt / DragRudderTravelS);
        foreach (Scheduled surface in rollSurfaces)
        {
            Apply(surface, surface.AreaPerExtension * Extension, surface.YawSide == 0f ? 0f : DragRudderM2 * DragRudderOpen(surface.YawSide));
        }
    }

    static void Apply(Scheduled s, float area, float drag)
    {
        if (s.Part == null || s.Part.IsDetached())
        {
            return;
        }

        s.Part.ModifyWingArea(area - s.AppliedArea);
        s.AppliedArea = area;
        s.Part.ModifyDrag(drag - s.AppliedDrag);
        s.AppliedDrag = drag;
    }

#if CENTURION_DEV
    /// <summary>
    /// Each part's pitch against the pose it spawned in on its parent (UnitPart.CreateAttachInfo, UnitPart.cs:173-180): on the
    /// simulating peer every part is its own rigidbody on joints (AeroPart.CreateJoints), which bend under load. Only the
    /// local player's aircraft, which is all AgenticState reads, and without allocating, since it runs every physics step.
    /// </summary>
    static bool IsTailPart(string name) => name is "fuselage_R" or "tailcone" or "tail_end"
        || name.StartsWith("vtail_", System.StringComparison.Ordinal) || name.StartsWith("ruddervator_", System.StringComparison.Ordinal);

    void MeasureFlex()
    {
        float worst = 0f, worstTail = 0f;
        foreach ((UnitPart part, UnitPart parent, Quaternion rest) in flexParts)
        {
            if (part == null || parent == null || part.IsDetached())
            {
                continue;
            }

            Quaternion bend = Quaternion.Inverse(parent.transform.rotation * rest) * part.transform.rotation;
            float pitch = -Mathf.DeltaAngle(0f, bend.eulerAngles.x);
            if (Mathf.Abs(pitch) > Mathf.Abs(worst))
            {
                worst = pitch;
                FlexPart = part.name;
            }

            // Not Quaternion.Angle: it returns 0 under 0.16 deg.
            float angle = 2f * Mathf.Asin(Mathf.Min(1f, new Vector3(bend.x, bend.y, bend.z).magnitude)) * Mathf.Rad2Deg;
            if (IsTailPart(part.name) && angle > worstTail)
            {
                worstTail = angle;
                TailBendPart = part.name;
            }
        }

        FlexPitchDeg = worst;
        TailBendDeg = worstTail;

        Transform root = aircraft.transform;
        Vector3 sum = Vector3.zero;
        float mass = 0f;
        massBodies.Clear();
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part != null && !part.IsDetached() && massBodies.Add(part.rb))
            {
                sum += part.rb.mass * root.InverseTransformPoint(part.rb.worldCenterOfMass);
                mass += part.rb.mass;
            }
        }

        CenterOfMassLocal = sum / mass;
        Stage1CenterOfMassLocal = root.InverseTransformPoint(stages[0][0].Part.rb.worldCenterOfMass);
        ReadStageJob(stages[0][0].Part);
    }
#endif

    /// <summary>
    /// Stage 1's own rigidbody (complex physics) gets <see cref="StageSpinCap"/> while attached and the game's default once it
    /// is debris, where its centerOfLift torque would spin it up unchecked. Debug.StageMaxAngularVelocity replaces the attached
    /// cap on the local player; the game's 14 brings the clamp back.
    /// </summary>
    void CapStageSpin()
    {
#if CENTURION_DEV
        float attached = StageMaxAngularVelocity.Value > 0f && Diagnostics.Value && IsLocalPlayer ? StageMaxAngularVelocity.Value : StageSpinCap;
#else
        float attached = StageSpinCap;
#endif
        foreach (Stage stage in stages[0])
        {
            if (stage.Part == null || stage.Part.rb == null || stage.Part.rb == aircraft.rb)
            {
                continue;
            }

            Rigidbody rb = stage.Part.rb;
            float cap = stage.Part.IsDetached() ? Physics.defaultMaxAngularSpeed : attached;
            if (rb.maxAngularVelocity != cap)
            {
                rb.maxAngularVelocity = cap;
            }
        }
    }

#if CENTURION_DEV
    /// <summary>
    /// The force and torque AeroJob_Math left in the part's job fields for ApplyJobFields to add (AeroPart.cs:598-650), and the
    /// torque the job's own formula gives for that force, Cross(F, -liftRotation x centerOfLift) (AeroJob_Math.cs:126-131).
    /// </summary>
    void ReadStageJob(AeroPart part)
    {
        if (!PitchBudget.TryReadJob(part, out NuclearOption.Jobs.AeroPartFields fields))
        {
            return;
        }

        Vector3 right = aircraft.transform.right;
        Vector3 expected = Vector3.Cross(fields.force, -(part.LiftNormal.rotation * fields.centerOfLift));
        Stage1JobForce = fields.force.magnitude;
        Stage1JobTorquePitch = fields.hasForce == NuclearOption.Jobs.JobForceType.ForceAndTorque ? Vector3.Dot(fields.torque, right) : 0f;
        Stage1ExpectedTorquePitch = Vector3.Dot(expected, right);
    }
#endif

    /// <summary>
    /// A stage nests inside the part it slides on, so their hulls overlap at every extension (most of stage 1 is inside the
    /// inner wing at 0.3). Attached, their joints keep them from colliding (enableCollision false); once a stage is off, by
    /// the tear or the stock rule, on this peer or another, its joints are gone or never existed (a remote copy gets a fresh
    /// Rigidbody inside the aircraft's compound collider, AeroPart.cs:299-309), and PhysX jams the overlapping hulls: the
    /// owner's torn stage hung from the root, clipping, after "joints released" (playtest 20261012-213053). So on every peer
    /// the torn stage 1 and the stage 2 riding it stop colliding with every part still on the aircraft, and fall clear.
    /// </summary>
    void ReleaseTornColliders(UnitPart? broken = null)
    {
        // stage 1 with the stage 2 riding it, or a stage 2 torn off on its own
        foreach (Stage stage in allStages)
        {
            if (stage.CollisionsReleased || stage.Part == null || !(stage.Part.IsDetached() || stage.Part == broken))
            {
                continue;
            }

            stage.CollisionsReleased = true;
            var torn = new HashSet<Collider>(stage.Part.GetComponentsInChildren<Collider>(true));
            foreach (Stage outer in stages[1].Where(s => s.Parent == stage.Part && s.Part != null && !s.CollisionsReleased))
            {
                outer.CollisionsReleased = true;
                torn.UnionWith(outer.Part.GetComponentsInChildren<Collider>(true));
            }

            var kept = new HashSet<Collider>();
            foreach (UnitPart part in aircraft.partLookup.Where(p => p != null && !p.IsDetached()))
            {
                kept.UnionWith(part.GetComponentsInChildren<Collider>(true).Where(c => !torn.Contains(c)));
            }

            foreach (Collider a in torn)
            {
                foreach (Collider b in kept)
                {
                    Physics.IgnoreCollision(a, b, true);
                }
            }

            Log.Info(Invariant($"telescope on {aircraft.name}: {stage.Part.name} is off; its {torn.Count} colliders no longer touch the aircraft's {kept.Count}"));
        }
    }

    Vector3 Commanded(Stage stage) => Vector3.Lerp(stage.Retracted, stage.Extended, Extension);

    /// <summary>
    /// Moves each stage to the commanded extension. After a snap, in complex physics, each stage's own rigidbody is put
    /// there too, parent first (allStages runs stage 1 before the stage 2 on it): the slider would drag it over in one step,
    /// and the stock rule detaches a stage 0.5 m off (AeroPart.cs:271-279).
    /// </summary>
    void Slide(bool snapped)
    {
        foreach (Stage stage in allStages)
        {
            if (stage.Part == null || stage.Part.IsDetached())
            {
                continue;
            }

            Vector3 commanded = Commanded(stage);
            LocalPosition!(stage.AttachInfo) = commanded;
            // A held extension leaves the pose and the slider's anchor where the last step put them: setting a joint's anchor
            // reconfigures the PhysX joint, four times a step on every Centurion.
            bool moved = commanded != stage.Placed;
            stage.Placed = commanded;
            if (aircraft.simplePhysics)
            {
                if (moved)
                {
                    stage.Part.transform.localPosition = commanded;
                }
            }
            else
            {
                if (snapped && stage.Part.rb != stage.Parent.rb)
                {
                    Vector3 world = stage.Parent.transform.TransformPoint(commanded);
                    stage.Part.transform.position = world;
                    stage.Part.rb.position = world;
                    stage.Part.rb.velocity = stage.Parent.rb.GetPointVelocity(world);
                }

                if (stage.Slider != null && moved)
                {
                    stage.Slider.connectedAnchor = commanded;
                }
            }

#if CENTURION_DEV
            // What the stock detach rule measures (AeroPart.cs:271-272).
            stage.Offset = Vector3.Distance(stage.Parent.transform.InverseTransformPoint(stage.Part.transform.position), commanded);
            PeakOffset = Mathf.Max(PeakOffset, stage.Offset);
            stage.AngleDeg = Quaternion.Angle(stage.Parent.transform.rotation, stage.Part.transform.rotation);
            stage.JointTorque = stage.Slider != null ? stage.Slider.currentTorque.magnitude : 0f;
#endif
        }
    }

    /// <summary>
    /// Stages the owner has lost (<see cref="OwnerState.Lost"/>) that are still on this copy after <see cref="ReplayGraceS"/>
    /// come off through UnitPart.Detach, the call the part-break RPC makes (Unit.cs:2193-2203): stage 2 follows a stage 1
    /// (UnitPart.cs:222-226), and the lock and <see cref="ReleaseTornColliders"/> follow the detach.
    /// </summary>
    void ReplayOwnerLoss(OwnerState state)
    {
        if (ownerStateOff)
        {
            return;
        }

        for (int bit = 0; bit < 4; bit++)
        {
            Stage stage = stages[bit / 2][bit % 2];
            if ((state.Lost & (1 << bit)) == 0 || stage.Part == null || stage.Part.IsDetached())
            {
                stage.OwnerLostAt = float.PositiveInfinity;
                continue;
            }

            if (float.IsPositiveInfinity(stage.OwnerLostAt))
            {
                stage.OwnerLostAt = Time.time;
            }
            else if (Time.time - stage.OwnerLostAt >= ReplayGraceS)
            {
                stage.Replayed = true;
                stage.Part.Detach(aircraft.rb.velocity, stage.Part.transform.position - aircraft.transform.position);
                Log.Info($"telescope on {aircraft.name}: {stage.Part.name} is gone on the simulating peer, detached here from its state");
            }
        }
    }

#if CENTURION_DEV
    /// <summary>
    /// Debug.Tear on the local player's Centurion: both stage 1 panels come off through <see cref="Tear"/> once the span is
    /// fully out, for a check that needs the tear before another peer joins (G7.1's late joiner).
    /// </summary>
    bool DebugTearDue()
    {
        if (!DebugTear.Value || !Diagnostics.Value || !IsLocalPlayer || Extension < 1f || DetachedStages > 0)
        {
            return false;
        }

        Log.Stage("tear-debug", $"{aircraft.name}: Debug.Tear, tearing both stage 1 panels");
        return true;
    }
#endif

    /// <summary>
    /// One stage 1 is off by any route (a hit, a joint, the stock rule) and the other is still on. Left to the lock's 8 s
    /// slew, the intact panel lifts alone: at 199 t and 120 m/s (233 kt) its 9.9 MN m is 45% of full aileron, and stick
    /// centred the aircraft banks 71 deg in 10 s; with only its area zeroed its mass still rolls it 2 deg the other way, and
    /// with both off it stays level (tools/fm centurion_span.py --one-side). So the intact one follows through
    /// <see cref="Tear"/>, as G2.8 has both panels off after a tear. Once either wing root is gone it does not fire: the
    /// aircraft has lost a wing, and throwing off the other panel would only read as a second, unexplained loss.
    /// </summary>
    bool OneStage1Lost()
    {
        int counted = 0;
        int lost = 0;
        foreach (Stage stage in stages[0])
        {
            // `is not null` first: a root that was found and later destroyed (Unity null) is gone, not absent.
            if (stage.Root is not null && (stage.Root == null || stage.Root.IsDetached()))
            {
                continue;
            }

            counted++;
            if (stage.Part == null || stage.Part.IsDetached())
            {
                lost++;
            }
        }

        if (counted != 2 || lost != 1)
        {
            return false;
        }

        // GameMessage is the stock local notification path (GameplayUI.cs:171-173); never broadcast the cue to observers.
        if (IsLocalPlayer && SceneSingleton<GameplayUI>.i != null)
            SceneSingleton<GameplayUI>.i.GameMessage("Outer wing lost. Symmetric emergency jettison.");
        return true;
    }

    /// <summary>
    /// Both stage 1 panels go off through the stock detach, which reaches every peer as Unit.RpcBreakPart (Unit.cs:1437-1447,
    /// 2193-2203), and nothing is committed here until it comes back: from a client it is a CmdBreakPart the server's rate
    /// limit can drop (Unit.cs:1449, 2276), so a panel still attached is asked for again every <see cref="TearRetryS"/>. Once
    /// UnitPart.Detach has run on this peer (UnitPart.cs:380-392), the joints holding the subtree to the inner wing go, which
    /// Detach leaves in complex physics, and the panel's streamlining joins its parent's drag as AeroPart.CheckAttachment adds
    /// it (AeroPart.cs:274-278). Stage 2 follows its parent off (UnitPart.cs:222-226), and every peer then sees a stage detached
    /// and locks the extension at 0. True once both panels are off.
    /// </summary>
    bool Tear()
    {
        bool done = true;
        foreach (Stage stage in stages[0])
        {
            if (stage.Part == null || stage.Freed)
            {
                continue;
            }

            bool asked = !float.IsNegativeInfinity(stage.DetachAskedAt);
            if (stage.Part.IsDetached() && !asked)
            {
                stage.Freed = true; // the stock rule took it off first, streamlining and all
                continue;
            }

            if (!stage.Part.IsDetached())
            {
                if (Time.time < stage.DetachAskedAt + TearRetryS)
                {
                    done = false;
                    continue;
                }

                stage.DetachAskedAt = Time.time;
                aircraft.DetachPart(stage.Part.id, stage.Part.rb.velocity, stage.Part.transform.position - aircraft.transform.position);
                if (!stage.Part.IsDetached())
                {
                    done = false;
                    continue;
                }
            }

            foreach (Stage outer in stages[1].Where(s => s.Parent == stage.Part))
            {
                foreach (PartJoint joint in outer.Part.Joints.Where(j => j.connectedPart != stage.Part && j.joint != null))
                {
                    Destroy(joint.joint);
                }
            }

            foreach (PartJoint joint in stage.Part.Joints.Where(j => j.joint != null))
            {
                Destroy(joint.joint);
            }

            float streamlining = (float)StreamliningField!.GetValue(stage.Part);
            if (streamlining > 0f)
            {
                stage.Parent.ModifyDrag(streamlining);
            }

            stage.Freed = true;
            Log.Info(Invariant($"telescope on {aircraft.name}: {stage.Part.name} detach confirmed {Time.time - stage.DetachAskedAt:0.000} s after it was asked, joints released"));
        }

        return done;
    }
}
