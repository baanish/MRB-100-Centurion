using System.Collections.Generic;
using BepInEx.Configuration;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// The deployable AWACS beam on hardpoint set 2 (docs/M3-DESIGN.md, "AwacsBeam contract" and "Beam readout"): the
/// two-stage mast rises out of the spine well, then the end sections slide out, 12 s in all, whenever the aircraft is
/// not on the ground near a medium hangar and its radar master is on. The beam's radar reads no range until fully
/// deployed. The simulating peer runs it from the loadout, position, radar altitude, radar master and stock part-break RPC;
/// the others take its target from the owner's state (<see cref="OwnerState"/>). Added to each Centurion by <see cref="CenturionSystems"/>; binds the mount on attach
/// and each time the weapon manager spawns a loadout.
/// </summary>
sealed class AwacsBeam : MonoBehaviour
{
    /// <summary>WeaponMount.jsonKey of the beam mount (CenturionAuthor.AwacsKey).</summary>
    const string AwacsKey = "baanish_centurion_awacs";
    const int AwacsSet = 2;
    /// <summary>
    /// The mount's root part, found in partLookup since the simulating peer's CreateRB unparents it from the hardpoint
    /// (AeroPart.cs:319-353). Unity names a prefab's root after its file (CenturionAuthor's AwacsPrefabPath), and an
    /// instance after that, plus "(Clone)".
    /// </summary>
    const string MountRoot = "Centurion_AwacsBeam";
    /// <summary>The bomber's lid over the well: a renderer under fuselage_R with no collider (CenturionAuthor.AddVisual's name).</summary>
    const string CoverName = "spine_cover_mesh";
    const float TravelS = 12f;
    /// <summary>The mast rises over this share of the travel (8 s), the end sections slide out over the rest (4 s).</summary>
    const float MastShare = 2f / 3f;
    // Stowing takes 12 s, 144 m at the framework's 12 m/s taxi cap: taxiing in, the beam starts down 200 m from the
    // spawn point and is home 56 m out, before the nose reaches the door plane at 43.8 m (the span's guard is 130 m).
    const float GuardM = 200f;
    // At bind the fraction snaps rather than travels: deployed above this radar altitude outside the guard. Only the
    // simulating peer has radarAlt before InitializeUnit (Aircraft.cs:1206-1209), so the rule reruns for SnapS.
    const float SnapAltM = 10f, SnapS = 1f;
    const float RangeM = 150000f;
    /// <summary>Increment over the mount's 1.0 stowed drag: 5.2 game drag units deployed, or 2.6 m2 CdA
    /// on the healthy carrier (AeroJob_Math.cs:94-98). Cruise estimate and allowances: docs/M3-DESIGN.md, Drag.</summary>
    const float DeployedDragM2 = 4.2f;
    // hangar_med's door plane stands this far ahead of its spawn point along the spawn's forward (hangar_med.prefab:1137-1138).
    const float DoorAheadM = 22.8f;
    // A mission-placed aircraft's spawn hangar is the medium hangar whose spawn point it stands within this of.
    const float SpawnMatchM = 10f;

    /// <summary>Every live Centurion's beam, local and remote.</summary>
    internal static readonly List<AwacsBeam> All = new();

    internal static ConfigEntry<float> DebugAwacsCommand = null!;

    /// <summary>A moving piece of the mount: a mast stage or an end section, from its authored (stowed) local position to its marker's.</summary>
    sealed class Slide
    {
        public Transform Part = null!, Marker = null!;
        public Vector3 Home;
        public bool End;
    }

    Aircraft aircraft = null!;
    HangarGuard hangarGuard = null!;
    readonly List<Slide> slides = new();
    UnitPart? root;
    AeroPart? carrier;
    Transform? hardpoint;
    Radar? radar;
    Renderer? cover;
    /// <summary>The spawn point of the hangar the aircraft started in, which the door readouts measure against; null for
    /// an airborne start. <see cref="HangarGuard.Spawn"/> is the nearest hangar, which changes as the aircraft taxis.</summary>
    Transform? spawnHangar;
    Vector3 mast2InRoot;
    float deploy, target, appliedDrag, stowedDrag, snapUntil;
    bool fitted, lost, guard, ownerSnapped;
    string state = "none";

    /// <summary>True when the beam mount is on hardpoint set 2.</summary>
    public bool Fitted => fitted;

    /// <summary>Fitted, not lost, and fully deployed (<see cref="Deploy"/> is 1).</summary>
    public bool Deployed => fitted && !lost && slides.Count > 0 && deploy >= 1f;

    /// <summary>The deployment fraction, 0 stowed to 1 deployed.</summary>
    public float Deploy => deploy;

    /// <summary>The beam is heading for deployed (<see cref="OwnerState"/> sends it).</summary>
    public bool TargetUp => target >= 1f;

    /// <summary>The mount's radar; null when not fitted or lost.</summary>
    public Radar? BeamRadar => !fitted || lost || radar == null ? null : radar;

    public bool IsLocalPlayer => GameManager.GetLocalAircraft(out Aircraft local) && local == aircraft;
    public bool Simulated => aircraft.LocalSim;

    internal static void Install(ConfigFile config, CenturionLog log)
    {
        DebugAwacsCommand = config.Bind("Debug", "AwacsCommand", -1f, new ConfigDescription(
            "0 or 1 is the local player aircraft's beam target in place of the automatic rule (scenarios); radar master off, the hangar guard and a lost mount still hold it at 0; below 0 is off",
            new AcceptableValueRange<float>(-1f, 1f)));
        DebugAwacsCommand.SettingChanged += (_, _) => log.Info(Invariant($"config Debug.AwacsCommand = {DebugAwacsCommand.Value}"));
    }

    internal static void AddDefaults(Dictionary<string, object> state)
    {
        state["awacs_fitted"] = AircraftReadout.NotRead;
        state["awacs_state"] = AircraftReadout.NoText;
        state["awacs_target"] = AircraftReadout.NotRead;
        state["awacs_deploy"] = AircraftReadout.NotRead;
        state["awacs_guard"] = AircraftReadout.NotRead;
        state["awacs_mast_m"] = AircraftReadout.NotRead;
        state["awacs_cover"] = AircraftReadout.NotRead;
        state["awacs_ext_m"] = AircraftReadout.NotRead;
        state["awacs_top_m"] = AircraftReadout.NotRead;
        state["awacs_door_clear_m"] = AircraftReadout.NotRead;
        state["awacs_range_m"] = AircraftReadout.NotRead;
        state["awacs_drag_m2"] = AircraftReadout.NotRead;
        state["awacs_mount_offset_m"] = AircraftReadout.NotRead;
        state["remote_awacs_deploy"] = AircraftReadout.NotRead;
    }

    internal static void Read(Dictionary<string, object> state, Aircraft aircraft)
    {
        if (!aircraft.TryGetComponent(out AwacsBeam beam))
        {
            return;
        }

        state["awacs_fitted"] = beam.fitted ? 1 : 0;
        state["awacs_state"] = beam.state;
        if (beam.cover != null)
        {
            state["awacs_cover"] = beam.cover.enabled ? 1 : 0;
        }

        if (!beam.fitted)
        {
            return;
        }

        state["awacs_target"] = AircraftReadout.Round(beam.target);
        state["awacs_deploy"] = AircraftReadout.Round(beam.deploy);
        state["awacs_guard"] = beam.guard ? 1 : 0;
        state["awacs_drag_m2"] = AircraftReadout.Round(beam.stowedDrag + beam.appliedDrag);
        if (beam.radar != null)
        {
            state["awacs_range_m"] = AircraftReadout.Round(beam.radar.RadarParameters.maxRange);
        }

        if (beam.root == null || beam.slides.Count == 0)
        {
            return;
        }

        Transform root = beam.root.transform;
        float ends = 0f;
        foreach (Slide slide in beam.slides)
        {
            if (slide.End)
            {
                ends = Mathf.Max(ends, Vector3.Distance(slide.Part.localPosition, slide.Home));
            }
        }

        state["awacs_mast_m"] = AircraftReadout.Round(Vector3.Distance(root.InverseTransformPoint(beam.slides[1].Part.position), beam.mast2InRoot));
        state["awacs_ext_m"] = AircraftReadout.Round(ends);
        if (beam.hardpoint != null)
        {
            state["awacs_mount_offset_m"] = AircraftReadout.Round(Vector3.Distance(root.position, beam.hardpoint.position));
        }

        Transform? spawn = beam.spawnHangar;
        if (spawn != null)
        {
            float top = float.NegativeInfinity;
            foreach (Renderer renderer in root.GetComponentsInChildren<Renderer>())
            {
                top = Mathf.Max(top, renderer.bounds.max.y);
            }

            state["awacs_top_m"] = AircraftReadout.Round(top - spawn.position.y);
            state["awacs_door_clear_m"] = AircraftReadout.Round(beam.DoorClearance(spawn));
        }
    }

    internal static void ReadRemote(Dictionary<string, object> state)
    {
        foreach (AwacsBeam beam in All)
        {
            if (!beam.IsLocalPlayer && !beam.Simulated)
            {
                state["remote_awacs_deploy"] = AircraftReadout.Round(beam.deploy);
                return;
            }
        }
    }

    void Awake()
    {
        aircraft = GetComponent<Aircraft>();
        hangarGuard = new HangarGuard(aircraft);
        All.Add(this);
        aircraft.weaponManager.OnWeaponsLoaded += Bind;
        Bind();
    }

    void OnDestroy()
    {
        All.Remove(this);
        if (aircraft != null && aircraft.weaponManager != null)
        {
            aircraft.weaponManager.OnWeaponsLoaded -= Bind;
        }

        Unbind();
    }

    /// <summary>
    /// The mount on set 2, if it is the beam: its parts resolved from its root wherever the physics mode parented it,
    /// the lid hidden, and the fraction snapped (deployed above <see cref="SnapAltM"/> outside the guard, else stowed),
    /// with the pose, range gate and drag written at once. Each loadout is a fresh mount instance, authored stowed
    /// (WeaponManager.SpawnWeapons removes every mount first, WeaponManager.cs:340-352).
    /// </summary>
    void Bind()
    {
        Unbind();
        HardpointSet[] sets = aircraft.weaponManager.hardpointSets;
        if (sets.Length <= AwacsSet || sets[AwacsSet].hardpoints.Count == 0)
        {
            CenturionPlugin.Log.Warning($"AWACS beam on {aircraft.name}: no hardpoint set {AwacsSet}; the beam stays off");
            return;
        }

        if (spawnHangar == null)
        {
            spawnHangar = FindSpawnHangar();
        }

        Hardpoint point = sets[AwacsSet].hardpoints[0];
        cover = FindCover(point.part);
        ShowCover(true);
        WeaponMount? mount = sets[AwacsSet].weaponMount;
        if (mount == null || mount.jsonKey != AwacsKey)
        {
            SetState("none");
            return;
        }

        fitted = true;
        hardpoint = point.transform;
        carrier = point.part as AeroPart;
        stowedDrag = mount.emptyDrag;
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part != null && part.name.StartsWith(MountRoot))
            {
                root = part;
            }
        }

        radar = root != null ? root.GetComponent<Radar>() : null;
        Transform? rootTransform = root != null ? root.transform : null;
        Slide? mast1 = Rig(rootTransform, "awacs_mast_1", "awacs_mast_1_raised", false);
        Slide? mast2 = Rig(mast1?.Part, "awacs_mast_2", "awacs_mast_2_raised", false);
        Transform? beam = mast2?.Part.Find("awacs_beam");
        Slide? endF = Rig(beam, "awacs_beam_ext_F", "awacs_beam_ext_F_extended", true);
        Slide? endR = Rig(beam, "awacs_beam_ext_R", "awacs_beam_ext_R_extended", true);
        if (root == null || rootTransform == null || radar == null || carrier == null || mast1 == null || mast2 == null || endF == null || endR == null)
        {
            CenturionPlugin.Log.Warning($"AWACS beam on {aircraft.name}: the mount lacks its root part, radar, carrier, a mast stage, an end section or a marker; the beam stays stowed with no range");
            if (radar != null)
            {
                radar.RadarParameters.maxRange = 0f;
            }

            SetState("off");
            return;
        }

        slides.AddRange(new[] { mast1, mast2, endF, endR });
        mast2InRoot = rootTransform.InverseTransformPoint(mast2.Part.position);
        root.onPartDetached += OnMountDetached;
        root.onParentDetached += OnMountDetached;
        lost = root.IsDetached();
        ShowCover(false);
        snapUntil = Time.fixedTime + SnapS;
        target = deploy = Snap();
        Pose();
        Apply();
        CenturionPlugin.Log.Info(Invariant($"AWACS beam on {aircraft.name} ({(Simulated ? "simulated here" : "remote")}): bound, deploy {deploy:0}, drag {stowedDrag} m2 stowed + {DeployedDragM2} deployed"));
    }

    void Unbind()
    {
        if (root != null)
        {
            root.onPartDetached -= OnMountDetached;
            root.onParentDetached -= OnMountDetached;
        }

        if (carrier != null)
        {
            carrier.ModifyDrag(-appliedDrag);
        }

        appliedDrag = deploy = target = 0f;
        slides.Clear();
        root = null;
        carrier = null;
        hardpoint = null;
        radar = null;
        fitted = lost = guard = ownerSnapped = false;
    }

    static Slide? Rig(Transform? parent, string name, string marker, bool end)
    {
        Transform? part = parent != null ? parent.Find(name) : null;
        Transform? mark = parent != null ? parent.Find(marker) : null;
        return part == null || mark == null ? null : new Slide { Part = part, Marker = mark, Home = part.localPosition, End = end };
    }

    /// <summary>The spawning hangar's spawn point, or for a mission-placed aircraft the nearest medium hangar's while it
    /// stands within <see cref="SpawnMatchM"/> of it (at the first bind, still on its start pose); else null.</summary>
    Transform? FindSpawnHangar()
    {
        if (aircraft.NetworkspawningHangar != null)
        {
            return aircraft.NetworkspawningHangar.GetSpawnTransform();
        }

        Transform? nearest = hangarGuard.Spawn;
        return nearest != null && Vector3.ProjectOnPlane(nearest.position - aircraft.transform.position, Vector3.up).magnitude < SpawnMatchM ? nearest : null;
    }

    static Renderer? FindCover(UnitPart? carrierPart)
    {
        Transform? lid = carrierPart != null ? carrierPart.transform.Find(CoverName) : null;
        return lid != null ? lid.GetComponent<Renderer>() : null;
    }

    void FixedUpdate()
    {
        if (!fitted || slides.Count == 0)
        {
            return;
        }

        if (root == null)
        {
            Bind(); // the bound mount went without a loadout event (WeaponManager.RemoveWeapons)
            return;
        }

        guard = hangarGuard.Holds(GuardM);
        float command = DebugAwacsCommand.Value;
        float was = deploy;
        if (!Simulated && aircraft.TryGetComponent(out OwnerState owner) && owner.Received)
        {
            // An observer takes the owner's target, and on the first word its fraction too: the snap rule reads radar altitude,
            // which this copy may not have yet (Aircraft.cs:1206-1209), and on the ground outside the guard it reads stowed
            // while the owner's beam is up.
            target = !lost && owner.BeamUp ? 1f : 0f;
            deploy = ownerSnapped ? Mathf.MoveTowards(deploy, target, Time.fixedDeltaTime / TravelS) : target;
            ownerSnapped = true;
        }
        else
        {
            target = lost || guard || !RadarMaster ? 0f
                : command >= 0f && ScenarioHooks.Diagnostics.Value && IsLocalPlayer ? (command >= 0.5f ? 1f : 0f)
                : 1f;
            deploy = Time.fixedTime < snapUntil ? Snap() : Mathf.MoveTowards(deploy, target, Time.fixedDeltaTime / TravelS);
        }

        if (deploy != was)
        {
            Pose();
        }

        Apply();
    }

    bool RadarMaster => !aircraft.TryGetComponent(out RadarSuite suite) || suite.Master;

    float Snap() => !lost && RadarMaster && aircraft.radarAlt > SnapAltM && !hangarGuard.Holds(GuardM) ? 1f : 0f;

    /// <summary>Both mast stages over the first <see cref="MastShare"/> of the fraction (1.93 m each, 3.85 m in all), then both end sections (2.5 m each), each eased.</summary>
    void Pose()
    {
        float mast = Mathf.Clamp01(deploy / MastShare), ends = Mathf.Clamp01((deploy - MastShare) / (1f - MastShare));
        foreach (Slide slide in slides)
        {
            slide.Part.localPosition = Vector3.Lerp(slide.Home, slide.Marker.localPosition, Mathf.SmoothStep(0f, 1f, slide.End ? ends : mast));
        }
    }

    /// <summary>
    /// The range gate (RadarParameters is a public struct field, Radar.cs:42; every reader takes 0, Radar.cs:139, 156 and
    /// Aircraft.cs:765-775), the drag as a delta on what this applied, since stock code also changes dragArea
    /// (AeroPart.cs:275-278), and the state.
    /// </summary>
    void Apply()
    {
        if (radar != null)
        {
            radar.RadarParameters.maxRange = deploy >= 1f ? RangeM : 0f;
        }

        if (!lost && carrier != null)
        {
            float drag = DeployedDragM2 * deploy;
            carrier.ModifyDrag(drag - appliedDrag);
            appliedDrag = drag;
        }

        SetState(lost ? "lost" : deploy <= 0f ? "stowed" : deploy >= 1f ? "deployed"
            : target > deploy ? (deploy < MastShare ? "raising" : "extending")
            : deploy > MastShare ? "retracting" : "lowering");
    }

    /// <summary>
    /// The mount broke off (its joint, then the 0.5 m rule; Unit.DetachPart replicates it, Unit.cs:1437-1447), or a part it
    /// hangs from did, which raises only onParentDetached down the tree (UnitPart.cs:222-226); both fire for the mount's own
    /// break (UnitPart.cs:390-391), and a second call finds nothing left to undo. A mount
    /// radar never subscribed to damage, so its radar goes here: its OnDestroy hands the primary back
    /// (Radar.cs:84-99), which RadarSuite corrects the next frame. Lost until the loadout respawns.
    /// </summary>
    void OnMountDetached(UnitPart part)
    {
        lost = true;
        if (radar != null)
        {
            Destroy(radar);
        }

        radar = null;
        if (carrier != null)
        {
            carrier.ModifyDrag(-appliedDrag);
        }

        appliedDrag = 0f;
        SetState("lost");
    }

    void ShowCover(bool show)
    {
        if (cover != null)
        {
            cover.enabled = show;
        }
    }

    void SetState(string next)
    {
        if (next == state)
        {
            return;
        }

        state = next;
        CenturionPlugin.Log.Stage("awacs-" + aircraft.name, $"{aircraft.name}: AWACS beam {state}");
        // As the stock radar toggle tells the local player (Aircraft.cs:2463-2466); "none" is no beam to tell of.
        if (state != "none" && IsLocalPlayer && SceneSingleton<AircraftActionsReport>.i != null)
        {
            SceneSingleton<AircraftActionsReport>.i.ReportText("AWACS beam " + state, 5f);
        }
    }

    /// <summary>
    /// How far the aft-most point of any attached part's collider, the mount's included, stands past the spawn hangar's
    /// door plane, m; negative while anything is inside. Each collider counts by its world bounds, so this reads a little
    /// short of the shapes themselves.
    /// </summary>
    float DoorClearance(Transform spawn)
    {
        Vector3 forward = spawn.forward;
        Vector3 door = spawn.position + forward * DoorAheadM;
        float aft = float.PositiveInfinity;
        foreach (UnitPart part in aircraft.partLookup)
        {
            if (part == null || part.IsDetached())
            {
                continue;
            }

            foreach (Collider collider in part.GetComponentsInChildren<Collider>())
            {
                if (collider.isTrigger)
                {
                    continue;
                }

                Bounds b = collider.bounds;
                float reach = Mathf.Abs(forward.x) * b.extents.x + Mathf.Abs(forward.y) * b.extents.y + Mathf.Abs(forward.z) * b.extents.z;
                aft = Mathf.Min(aft, Vector3.Dot(b.center - door, forward) - reach);
            }
        }

        return aft;
    }
}
