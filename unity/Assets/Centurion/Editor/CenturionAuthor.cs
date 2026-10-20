using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using Blueprinter;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    // Authors the MRB-100 Centurion graybox into the mod folder from two inputs: the Alkyon placeholder
    // (FastBomber1), whose systems are kept, and the blockout export of tools/export_blockout.py, which
    // replaces its art, aero tree and gear. Rerunnable: every asset is rewritten in place at a fixed path,
    // so GUIDs survive a rerun. Game types live in the imported Assembly-CSharp, which an asmdef can't
    // reference, so their fields are set through SerializedObject by name; a renamed field throws.
    public static partial class CenturionAuthor
    {
        private const string ModFolder = "Assets/Blueprinter/Mods/centurion";
        private const string BlockoutFolder = ModFolder + "/Blockout";
        private const string MeshFolder = ModFolder + "/Meshes";
        private const string LiveryFolder = ModFolder + "/Liveries";
        private const string SkinFolder = ModFolder + "/Skin";
        private const string SkinPath = SkinFolder + "/Centurion_skin.mat";
        private const string PrefabPath = ModFolder + "/Centurion.prefab";
        private const string DefinitionPath = ModFolder + "/Centurion.asset";
        private const string ParametersPath = ModFolder + "/Centurion_Parameters.asset";
        private const string StatusDisplayPath = ModFolder + "/Centurion_StatusDisplay.prefab";
        private const string HudExtrasPath = ModFolder + "/Centurion_HUDExtras.prefab";
        private const string Stock = "Assets/Blueprinter/_donotship/";
        private const string DonorPrefab = Stock + "GameObject/FastBomber1_PLACEHOLDER.prefab";
        private const string DonorDefinition = Stock + "MonoBehaviour/FastBomber1_PLACEHOLDER.asset";
        private const string DonorParameters = Stock + "MonoBehaviour/FastBomber1_Parameters_PLACEHOLDER.asset";
        private const string DonorStatusDisplay = Stock + "GameObject/StatusDisplay_FastBomber1_PLACEHOLDER.prefab";

        public const string JsonKey = "baanish_centurion";
        private const float EmptyMass = 125000f - CramMass;
        private const int HardpointSetCount = 4;
        private const string HangarUnitKey = "hangar_med";
        // The blockout origin is station 22.475, the middle of the 44.95 m length, so the aircraft sits centred on the hangar
        // spawn. The prefab root (the fuselage_M pivot, station 21.0) sits SpawnForward ahead of it; checked against the
        // export in AuthorPrefab.
        private const float OriginStation = 22.475f;
        private const float SpawnForward = 1.475f;

        // The blockout's material slots (art/blender/build_centurion.py SLOT_ORDER, and LOD), remapped by name on import
        // to materials. The skin is the mod's own (AuthorSkin), which takes the livery; the rest are the shared trims and
        // the Alkyon's glass and gear.
        private const string SkinSlot = "Centurion_skin";
        private const string AirframeSlot = "Centurion_airframe"; // art/blender/m4/airframe.py SLOT
        private static readonly Dictionary<string, string> SlotMaterials = new Dictionary<string, string>
        {
            { "jet_mechanical", Stock + "Material/jet_mechanical_PLACEHOLDER.mat" },
            { "aircraft_structure", Stock + "Material/aircraft_structure_PLACEHOLDER.mat" },
            { "glass", Stock + "Material/FastBomber1_glass_PLACEHOLDER.mat" },
            { "Centurion_gear", Stock + "Material/SFB_gear_PLACEHOLDER.mat" },
            { "LOD", Stock + "Material/LOD_PLACEHOLDER.mat" },
            // The detailed meshes' lights (art/blender/detail_centurion.py LIGHTS and the wing's STOCK_SLOTS): the stock red
            // nav light for the beacons and the red nav, the stock green nav light for the green nav, the stock white gear
            // light for the strobes and the slipway, and the stock unlit pale green for the formation strips.
            { "light_red", Stock + "Material/navlight_L_PLACEHOLDER.mat" },
            { "light_green", Stock + "Material/navlight_R_PLACEHOLDER.mat" },
            { "light_white", Stock + "Material/gearLight_PLACEHOLDER.mat" },
            { "light_formation", Stock + "Material/light_green_off_PLACEHOLDER.mat" },
        };

        // The detailed skin's baked maps (tools/export_blockout.py copies them from the M4 composite's textures/ into
        // the export) on the AircraftSkin properties, with how each imports. The game sets _Livery and _Glossiness per
        // renderer from the LiveryData at spawn (UnitPart.SetLivery), on material slot 0 only; _BasecolorDmg multiplies
        // the albedo, metal and smoothness as hit points fall and burns through where its alpha is under 0.5.
        private static readonly (string Property, string File, bool SRgb, bool NormalMap)[] SkinMaps =
        {
            ("_Basecolor", "centurion_b.png", true, false), ("_Metallic", "centurion_m.png", false, false),
            ("_Normal", "centurion_n.png", false, true), ("_AO", "centurion_ao.png", false, false),
            ("_BasecolorDmg", "centurion_dmg_b.png", true, false), ("_NormalDmg", "centurion_dmg_n.png", false, true),
        };
        // The gear trim (art/blender/m4/gear.py) on the stock gear material's Lit properties.
        private static readonly (string Property, string File, bool SRgb, bool NormalMap)[] GearMaps =
        {
            ("_BaseMap", "gear_trim_b.png", true, false), ("_MainTex", "gear_trim_b.png", true, false),
            ("_MetallicGlossMap", "gear_trim_m.png", false, false), ("_BumpMap", "gear_trim_n.png", false, true),
        };
        // The mechanical swatch trim (art/blender/detail_centurion.py MECH_SWATCHES) on a copy of the stock jet_mechanical
        // material's Lit properties: that stock sheet is an atlas of pipes and fan decals, 40% of it cut out by alpha, so
        // faces box-projected onto it showed holes and fragments (the fans and nozzles).
        private static readonly (string Property, string File, bool SRgb, bool NormalMap)[] MechMaps =
        {
            ("_BaseMap", "mech_trim_b.png", true, false), ("_MainTex", "mech_trim_b.png", true, false),
            ("_MetallicGlossMap", "mech_trim_m.png", false, false),
        };
        // The damage structure's trim (art/blender/m4/airframe.py: frames, lining, members, torn edges, the tanks' sealed
        // walls) on its own copy of the stock Lit material, as the mech trim; seen only where the skin burns through or a
        // part comes away.
        private static readonly (string Property, string File, bool SRgb, bool NormalMap)[] AirframeMaps =
        {
            ("_BaseMap", "airframe_b.png", true, false), ("_MainTex", "airframe_b.png", true, false),
            ("_MetallicGlossMap", "airframe_m.png", false, false), ("_BumpMap", "airframe_n.png", false, true),
        };
        // The windscreen and lenses: opaque tinted glazing (sRGB) with the sky's reflection, as the opaque stock canopies are.
        // The Alkyon's glass is transparent over its own canopy layout, which the Centurion's panes, solid slabs laid over
        // the hull, can't use.
        private static readonly Color32 GlassTint = new Color32(24, 30, 36, 255);
        private const float GlassSmoothness = 0.93f;
        // aircraft_structure (door inner faces, joints, cut-out walls, skin a neighbour hides) in the bays' dark interior
        // paint (art/blender/m4/paint.py INTERIOR), as every review render shows it. The stock trim is a bright, fully
        // glossy greeble (sRGB 189 against the skin's 97): on the Darkreach it lines only the cockpit, and here it read as
        // untextured white wherever a gap or an open door showed it.
        private static readonly Color32 StructurePaint = new Color32(26, 27, 28, 255);
        private const float StructureSmoothness = 0.3f;
        private const int SkinMapSize = 4096; // G4.1's one skin atlas; Unity's importer default would halve it

        // Bomber stores only; ARADs register on the forward bay. Neither configuration carries air-to-air missiles.
        private static readonly string[] BayWeapons = { "bomb_500_internalx8", "bomb_500_internalx12", "bomb_250_internalx18", "bomb_250_glide_internalx8", "ARM1_internalx4" };

        // Airfoil indices into AircraftParameters.airfoils. The game's lift curves are odd functions of an
        // alpha whose sign convention isn't settled, so camber (cl0 in .cache/research/systems-design.md
        // section 7) is expressed as extra incidence on the lift transform: CL = cl0 + a*alpha equals
        // a*(alpha + cl0/a). That keeps the curve shaped like every stock one.
        private const int WingAirfoil = 0, PanelAirfoil = 1, TailAirfoil = 2, FlapAirfoil = 3;
        // -0.2°: the inner wing's lift normal sits 0.2° under its 1.5° rig and the body's 0.2° nose-down, so the retracted
        // aircraft flies nose-up at its top speed (+0.5° at 494 kt at sea level and 127 t, where step 6's +0.87° gave -0.4°)
        // now that the extended wing carries the takeoff (docs/M2-DESIGN.md, step 6.1).
        private const float WingCamberDeg = -0.2f;
        // The V-tail's and its moving surfaces' whole incidence, whatever the mesh's rig: trimmed level cruise at medium load
        // (162 t: half fuel, 25 t payload) holds the stick within 0.05 of neutral (the outboard surfaces within 1.5°) at 3 km
        // and 170 m/s and at 9 km and Mach 0.76, either span; empty trims up to 0.08 trailing edge down, full up to 0.08 up
        // (owner, 2026-10-13). With the single ruddervator at -5.36° every load trimmed 1.8° to 5.6° down
        // (tools/fm/centurion_span.py --trim).
        private const float TailIncidenceDeg = -3.0f;
        // The telescoping stages' lift-normal incidence, washed out so they carry little at cruise and a lot at the high
        // alphas of takeoff, slow flight and altitude (docs/M2-DESIGN.md).
        private const float StageIncidenceDeg = -2f;

        private enum Lift { None, Body, Wing }

        private sealed class PartSpec
        {
            public string Name, Parent, Reuse;
            public float? Mass; // null: the blockout's mass_kg
            public float WingArea, DragArea, ExtraIncidence, FuelKg, LiftAft;
            public float? Incidence; // the lift normal's whole incidence, whatever the mesh's rig; ExtraIncidence then unused
            public int Airfoil;
            public Lift Lift;
            public bool KeepDonorMesh;
            public string[] Braces = Array.Empty<string>();
        }

        private enum SurfaceKind { Flap, Roll, PitchYaw }

        // Stock split surfaces (ControlSurfaceJob_Math.cs:64-72): a clamshell's halves open up and down, as the Darkreach's
        // ailerons do; a rising one moves only its upper half, the panel, and keeps an empty lower one.
        private enum SplitKind { None, Clamshell, Rise }

        private sealed class SurfaceSpec
        {
            public string Name, Host;
            public float SpanIn, SpanOut, ChordFraction, Area, RangeA, RangeB, ServoSpeed, ExtraIncidence;
            public float? Incidence; // as PartSpec.Incidence
            public SurfaceKind Kind;
            public int Airfoil;
            public SplitKind Split;
            public float MaxSplit, SplitDrag;
        }

        // Parents before children. Masses are the blockout's mass_kg (docs/BLOCKOUT-S6.md "Masses") and sum to EmptyMass
        // with the surfaces; the nose and tail cone carry the radar, laser and capacitor mass where step 6.1's balance put it
        // (2,626 kg moved from the tail cone to the nose against round 4), which holds the empty CG at station 20.64, 42.7%
        // of the swept wing's MAC, with 24.9% on the nose gear (docs/BLOCKOUT-S6.md "CG and nose gear", BLOCKOUT-S61.md).
        // Areas: inner wing 180 and fuselage 50 m² as SPEC. The game has no downwash, so every square metre of tail adds as
        // much stability as control: the V-tail's fixed panels carry 4 m² each and the split tail's surfaces 28 and 56
        // (Surfaces), which lifts the 199 t extended aircraft off at 77 m/s under the takeoff AI and holds one engine out on
        // the tail alone from 69 m/s, with a static margin near 4.4 m extended and 6.1 m retracted (docs/M2-DESIGN.md, "The
        // split tail").
        // Braces are extra PartJoints to neighbours whose hulls touch, as the Alkyon's cross joints do (the blend's
        // bonded_to declarations, docs/BLOCKOUT-S6.md "Joints"); WriteJoints resolves them once every part exists.
        // The finer part tree (art/blender/part_splits.py, docs/M4-ART-PLAN.md "Damage structure") cuts sections, the wing
        // roots, the stage 2 tips, the V-tail tips and the sponsons' tails into pieces, and lays skin panels round the
        // body; a cut part's area and drag are on its first piece here and SplitLift shares them out (CutParts).
        private static readonly PartSpec[] Parts =
        {
            Body("fuselage_M", null, 20, 1.0f, "", 15000),
            Body("fuselage_F2", "fuselage_M", 0, 0, null, 0, "wingfairing"),
            Body("fuselage_F", "fuselage_F2", 12, 1.0f, "fuselage_F", 3000),
            Body("nose", "fuselage_F", 4, 0.6f, "fuselage_F/fuselage_FF"),
            // The flight deck: the Alkyon cockpit's systems on the Centurion's own interior and crew (BuildFlightDeck).
            new PartSpec { Name = "cockpit", Parent = "nose", Reuse = "fuselage_F/fuselage_FF/cockpit", Mass = 2000, DragArea = 0, Braces = new[] { "radar_F_fairing" } },
            new PartSpec { Name = "radar_F_fairing", Parent = "nose", Reuse = "fuselage_F/fuselage_FF/nose", DragArea = 0.05f },
            Body("fuselage_R", "fuselage_M", 10, 1.0f, "fuselage_R", 3000),
            Body("tailcone", "fuselage_R", 4, 0.6f, "fuselage_R/tail", 3000),
            Body("tail_end", "tailcone", 0, 0, null),
            // Skin panels round the body: a band of skin, lining and members over its core, no lift or drag of their own
            // (the core keeps the shape the aero is measured on). The V-tails stand on the tail cone's upper half.
            Plain("fuselage_F_upper", "fuselage_F", 0, null, "fuselage_F2_upper", "nose"),
            Plain("cheek_L", "fuselage_F_upper", 0, null, "fuselage_F"), Plain("cheek_R", "fuselage_F_upper", 0, null, "fuselage_F"),
            Plain("fuselage_F2_upper", "fuselage_F2", 0, null, "wingfairing"),
            Plain("fuselage_M_flank_L", "fuselage_M", 0, null, "sponson_L", "fuselage_F2_upper"),
            Plain("fuselage_M_flank_R", "fuselage_M", 0, null, "sponson_R", "fuselage_F2_upper"),
            Plain("fuselage_R_upper_L", "fuselage_R", 0, null, "fuselage_M_flank_L", "sponson_L"),
            Plain("fuselage_R_upper_R", "fuselage_R", 0, null, "fuselage_M_flank_R", "sponson_R"),
            Plain("tailcone_upper", "tailcone", 0, null, "fuselage_R_upper_L", "fuselage_R_upper_R"),
            Plain("tail_end_upper", "tail_end", 0, null, "tailcone_upper"),
            Tail("vtail_L", "tailcone_upper", 4, "tailcone", "fuselage_R", "tail_end", "tail_end_upper"),
            Tail("vtail_R", "tailcone_upper", 4, "tailcone", "fuselage_R", "tail_end", "tail_end_upper"),
            Tail("vtail_tip_L", "vtail_L", 0), Tail("vtail_tip_R", "vtail_R", 0),
            Plain("sponson_L", "fuselage_M", 0.4f, "gearbay_L", "fuselage_R"),
            Plain("sponson_R", "fuselage_M", 0.4f, "gearbay_R", "fuselage_R"),
            Plain("sponson_tail_L", "sponson_L", 0, null, "fuselage_R", "tailcone", "fuselage_R_upper_L"),
            Plain("sponson_tail_R", "sponson_R", 0, null, "fuselage_R", "tailcone", "fuselage_R_upper_R"),
            // The swept-back wing's root runs from station 14.69, over fuselage_F2, to 24.44, short of fuselage_R. Its lift acts
            // at the mean aerodynamic chord's quarter point (station 19.4), 0.7 m ahead of its hull centre; the outer wing
            // (outboard of 10.7 m) takes its share of the area at the same station (SplitLift).
            WingRoot("wing_root_L", "wingroot_L", "wing_root_R", "fuselage_F2", "fuselage_F2_upper", "fuselage_M_flank_L"),
            WingRoot("wing_root_R", "wingroot_R", "fuselage_F2", "fuselage_F2_upper", "fuselage_M_flank_R"),
            WingOuter("wing_outer_L", "wing_root_L"), WingOuter("wing_outer_R", "wing_root_R"),
            Plain("wingfairing", "fuselage_M", 0, null, "wing_root_L", "wing_root_R"),
            // Telescoping stages, each jointed first to the stage it slides on (TelescopeController makes those joints
            // sliders): stage 1 on the outer wing. Both nest in the root and the outer wing as well, so they are braced to
            // them: a jointed pair doesn't collide. Stage 2 carries the raked tip (blockout step 5), a piece of its own. Areas
            // are the retracted ones; the controller gives stage 1 its area with the extension. Stage 1's lift acts at its
            // hull centre: the swept-back wing moves the neutral point only 0.4 m on extension, where the forward-swept one
            // needed the lift 6 m aft (docs/M2-DESIGN.md).
            Stage("wing_tele1_L", "wing_outer_L", 0f, "wing_root_L"), Stage("wing_tele2_L", "wing_tele1_L", 0f, "wing_outer_L", "wing_root_L"),
            Stage("wing_tele1_R", "wing_outer_R", 0f, "wing_root_R"), Stage("wing_tele2_R", "wing_tele1_R", 0f, "wing_outer_R", "wing_root_R"),
            Plain("wing_tip_L", "wing_tele2_L", 0), Plain("wing_tip_R", "wing_tele2_R", 0),
            // Flap-track fairings, under the inner wing at each flap.
            Plain("flap_track_L1", "wing_root_L", 0, null, "flap_L1"), Plain("flap_track_L2", "wing_root_L", 0, null, "flap_L2"),
            Plain("flap_track_R1", "wing_root_R", 0, null, "flap_R1"), Plain("flap_track_R2", "wing_root_R", 0, null, "flap_R2"),
            // Engine 1 on the left wing, 2 on the right. The aft pylon fairing sits on the core cowl, so the pylon is braced
            // to the nozzle.
            Plain("pylon_1", "wing_root_L", 0, null, "nozzle_1"), Plain("nacelle_1", "pylon_1", 0.6f, null, "wing_root_L"), Plain("nozzle_1", "nacelle_1", 0),
            Plain("pylon_2", "wing_root_R", 0, null, "nozzle_2"), Plain("nacelle_2", "pylon_2", 0.6f, null, "wing_root_R"), Plain("nozzle_2", "nacelle_2", 0),
            // The truss: one straight line from the body side through the engine's axis to the wing, split at the node inside
            // the nacelle into two collinear segments, each braced to the nacelle and the core it passes through (the
            // nozzle part) and to each other, so losing an engine leaves the strut whole from body to wing. The inner one's
            // flared root reaches over station 17 onto fuselage_F2; the outer one meets the outer wing. Each lifts with half
            // its exposed planform (3.5 and 12.4 m² of 7.0 and 24.8) on a symmetric section whose chord runs with the flow, at
            // its own centre of mass: at the full planform the 199 t retracted roll reaches the end of the longest runway
            // 3 m/s short of liftoff, at half 6.5 (docs/M2-DESIGN.md, step 6).
            Wing("strut_inner_L", "fuselage_M", 3.5f, WingAirfoil, 0f, null, 0, "nacelle_1", "nozzle_1", "strut_outer_L", "fuselage_F2"),
            Wing("strut_outer_L", "wing_outer_L", 12.4f, WingAirfoil, 0f, null, 0, "nacelle_1", "nozzle_1"),
            Wing("strut_inner_R", "fuselage_M", 3.5f, WingAirfoil, 0f, null, 0, "nacelle_2", "nozzle_2", "strut_outer_R", "fuselage_F2"),
            Wing("strut_outer_R", "wing_outer_R", 12.4f, WingAirfoil, 0f, null, 0, "nacelle_2", "nozzle_2"),
        };

        // A part the finer part tree cut in two flies as the whole did: its pieces share the whole's area and drag in the
        // shares that keep its moment (SplitLift), and their sections, chords and lift frame are measured on their shapes
        // together, which make up the whole's (ShapeGroup). The first piece carries the whole's name, spec and lift frame.
        private static readonly string[][] CutParts =
        {
            new[] { "fuselage_F", "fuselage_F2" }, new[] { "tailcone", "tail_end" },
            new[] { "wing_root_L", "wing_outer_L" }, new[] { "wing_root_R", "wing_outer_R" },
            new[] { "vtail_L", "vtail_tip_L" }, new[] { "vtail_R", "vtail_tip_R" },
            new[] { "wing_tele2_L", "wing_tip_L" }, new[] { "wing_tele2_R", "wing_tip_R" },
        };

        // The part tree's pieces the game draws but does not damage, each a mesh on the part that carries its mass: the
        // spine cover's lids, which the AWACS beam hides (AwacsBeam's cover) and whose colliders would stand in its envelope.
        private static readonly (string Piece, string Part)[] VisualPieces = { ("spine_cover", "fuselage_R"), ("spine_cover_A", "fuselage_R") };

        // Spans are |x| in metres from the centreline; the hinge sits ChordFraction of the local chord ahead of
        // the trailing edge. Flaps between the fuselage and the pylon and outboard of it; spoilers and ailerons
        // outboard of them (SPEC "Wing"); the split tail's surfaces on the trailing 38% of the V-tail. The blockout's hinges and
        // meshes override these spans where it has them. Each hangs from the piece of the part tree it sits on: the ailerons
        // and spoilers from the outer wing, the outboard ruddervators from the V-tail tips.
        // The split tail (owner, 2026-10-16: "Make the entire trailing edge movable and split it into two, so that we can bias
        // one towards pitch and one towards yaw, but if needed, both can do both"): each panel's whole trailing edge moves, as
        // ruddervator_*1 inboard, biased to yaw (pitch 15, yaw 25), low beside the body where its side force rolls the aircraft
        // least, and ruddervator_*2 outboard into the rounded tip, biased to pitch (30, 8). The game turns a surface by the sum
        // of its pitch, roll and yaw, each clamped to its own range (ControlSurfaceJob_Math.cs:52-75), so the ranges are the
        // bias and either surface does both. Each carries 6.5 times its drawn area (4.35 and 8.57 m²), so a 1.1 g turn at
        // 208 m/s trims within 0.7 of the stick at 57,000 ft fully loaded, where the single ruddervator ran out near 49,000 ft
        // (tools/fm/centurion_span.py S62).
        // Spoiler and aileron areas are the retracted ones: TelescopeController grows them 5.5 times with the span, since
        // stage 1's area 25 m out multiplies the roll damping. The flaps carry 7.5 m² each, so the retracted wing, which flies
        // nose-up, still lands at 199 t without striking the tail.
        // Airbrakes as stock aircraft have them: at exactly idle throttle every split opens to maxSplit, and each drags
        // splitAmount (deg) x splitDrag x air density x v^2 (ControlSurface.cs:252-258). The Darkreach's ailerons split to 30 deg
        // at 0.1. Here the splits take no yaw (yawSplitFactor 0): a split travels at the surface's servoSpeed, and that lag in the
        // fly-by-wire's yaw-rate loop set the hold's high-speed turn oscillating (centurion_circuit, run 20261012-234630). The
        // drag rudders are TelescopeController's, applied at once.
        private static readonly SurfaceSpec[] Surfaces =
        {
            Surface("flap_L1", "wing_root_L", 3.5f, 6.65f, 0.28f, SurfaceKind.Flap, 7.5f, 30, 0, 10),
            Surface("flap_L2", "wing_root_L", 7.85f, 12.4f, 0.28f, SurfaceKind.Flap, 7.5f, 30, 0, 10),
            Surface("spoiler_L", "wing_outer_L", 12.8f, 19.4f, 0.2f, SurfaceKind.Roll, 4, 15, 0, 40, SplitKind.Rise, 50, 0.03f),
            Surface("aileron_L", "wing_outer_L", 12.8f, 19.6f, 0.25f, SurfaceKind.Roll, 12, 25, 0, 40, SplitKind.Clamshell, 50, 0.1f),
            Surface("flap_R1", "wing_root_R", 3.5f, 6.65f, 0.28f, SurfaceKind.Flap, 7.5f, 30, 0, 10),
            Surface("flap_R2", "wing_root_R", 7.85f, 12.4f, 0.28f, SurfaceKind.Flap, 7.5f, 30, 0, 10),
            Surface("spoiler_R", "wing_outer_R", 12.8f, 19.4f, 0.2f, SurfaceKind.Roll, 4, 15, 0, 40, SplitKind.Rise, 50, 0.03f),
            Surface("aileron_R", "wing_outer_R", 12.8f, 19.6f, 0.25f, SurfaceKind.Roll, 12, 25, 0, 40, SplitKind.Clamshell, 50, 0.1f),
            Surface("ruddervator_L1", "vtail_L", 2.81f, 4.59f, 0.38f, SurfaceKind.PitchYaw, 28, 15, 25, 40),
            Surface("ruddervator_L2", "vtail_tip_L", 4.66f, 8.27f, 0.38f, SurfaceKind.PitchYaw, 56, 30, 8, 40),
            Surface("ruddervator_R1", "vtail_R", 2.81f, 4.59f, 0.38f, SurfaceKind.PitchYaw, 28, 15, 25, 40),
            Surface("ruddervator_R2", "vtail_tip_R", 4.66f, 8.27f, 0.38f, SurfaceKind.PitchYaw, 56, 30, 8, 40),
        };

        private static PartSpec Body(string name, string parent, float area, float drag, string reuse, float fuel = 0, params string[] braces) =>
            new PartSpec { Name = name, Parent = parent, WingArea = area, DragArea = drag, Airfoil = WingAirfoil, ExtraIncidence = WingCamberDeg, Lift = Lift.Body, Reuse = reuse, FuelKg = fuel, Braces = braces };

        private static PartSpec Wing(string name, string parent, float area, int airfoil, float extra, string reuse = null, float fuel = 0, params string[] braces) =>
            new PartSpec { Name = name, Parent = parent, WingArea = area, DragArea = 0.05f, Airfoil = airfoil, ExtraIncidence = extra, Lift = Lift.Wing, Reuse = reuse, FuelKg = fuel, Braces = braces };

        private static PartSpec WingRoot(string name, string reuse, params string[] braces) =>
            new PartSpec { Name = name, Parent = "fuselage_M", WingArea = 72, DragArea = 0.05f, Airfoil = WingAirfoil, ExtraIncidence = WingCamberDeg, LiftAft = -0.7f, Lift = Lift.Wing, Reuse = reuse, Braces = braces };

        private static PartSpec WingOuter(string name, string root, params string[] braces) =>
            new PartSpec { Name = name, Parent = root, Airfoil = WingAirfoil, ExtraIncidence = WingCamberDeg, Lift = Lift.Wing, Braces = braces };

        private static PartSpec Tail(string name, string parent, float area, params string[] braces) =>
            new PartSpec { Name = name, Parent = parent, WingArea = area, DragArea = area > 0 ? 0.05f : 0, Airfoil = TailAirfoil, Incidence = TailIncidenceDeg, Lift = Lift.Wing, Braces = braces };

        private static PartSpec Plain(string name, string parent, float drag, string reuse = null, params string[] braces) =>
            new PartSpec { Name = name, Parent = parent, DragArea = drag, Reuse = reuse, Braces = braces };

        private static PartSpec Stage(string name, string parent, float liftAft, params string[] braces) =>
            new PartSpec { Name = name, Parent = parent, Airfoil = PanelAirfoil, Incidence = StageIncidenceDeg, LiftAft = liftAft, Lift = Lift.Wing, Braces = braces };

        private static SurfaceSpec Surface(string name, string host, float spanIn, float spanOut, float chord, SurfaceKind kind, float area, float rangeA, float rangeB, float servo,
            SplitKind split = SplitKind.None, float maxSplit = 0, float splitDrag = 0)
        {
            var tail = host.StartsWith("vtail", StringComparison.Ordinal);
            // Roll surfaces fly CTN_tail, which doesn't stall at full deflection as CTN_wing does; flaps fly CTN_flap.
            return new SurfaceSpec
            {
                Name = name, Host = host, SpanIn = spanIn, SpanOut = spanOut, ChordFraction = chord, Kind = kind, Area = area,
                RangeA = rangeA, RangeB = rangeB, ServoSpeed = servo, Airfoil = kind == SurfaceKind.Flap ? FlapAirfoil : tail || kind == SurfaceKind.Roll ? TailAirfoil : WingAirfoil,
                Incidence = tail ? TailIncidenceDeg : (float?)null, ExtraIncidence = tail ? 0 : WingCamberDeg, Split = split, MaxSplit = maxSplit, SplitDrag = splitDrag,
            };
        }

        private static string RepoRoot => Directory.GetParent(Application.dataPath).Parent.FullName;
        private static string ExportFolder => Path.Combine(RepoRoot, "art", "export");

        [MenuItem("Centurion/Author aircraft")]
        private static void AuthorFromMenu()
        {
            typeof(CenturionBuild).GetMethod("InitializeGameTasks", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, null);
            Author();
        }

        public static void Author()
        {
            var blockout = Blockout.Load(ExportFolder);
            foreach (var folder in new[] { BlockoutFolder, MeshFolder, LiveryFolder, SkinFolder })
                BlueprinterAssets.EnsureFolder(folder);
            AssetDatabase.DeleteAsset(ModFolder + "/OpAddLoadingScreens_centurion_placeholder.asset");
            AssetDatabase.DeleteAsset(ModFolder + "/centurion_placeholder_loading_screen.png");
            var skin = AuthorSkin(blockout);
            SavedMeshes.Clear();
            var meshes = ImportBlockout(blockout, SlotMaterialMap(skin, AuthorGear(blockout), AuthorMech(blockout), AuthorGlass(), AuthorAirframe(blockout)));

            var weapons = FindWeaponMounts(BayWeapons);
            // The mod's own mounts: null while a system's authoring is a stub, which leaves its loadout slot and op out.
            var modMounts = new List<(string Key, int Set)>();
            AuthorBombMounts(weapons, modMounts);
            weapons[AradKey] = AuthorAradMount(weapons["ARM1_internalx4"]);
            modMounts.Add((AradKey, 0));
            var awacsMount = AuthorAwacsMount();
            if (awacsMount != null)
            {
                weapons[AwacsKey] = awacsMount;
                modMounts.Add((AwacsKey, 2));
            }
            var cramMount = AuthorCramMount(meshes);
            if (cramMount != null)
            {
                weapons[CramKey] = cramMount;
                modMounts.Add((CramKey, 3));
            }
            var liveries = AuthorLiveries(blockout, (Texture2D)skin.GetTexture("_Livery"));
            var statusDisplay = AuthorDamageDiagram();
            var hudExtras = AuthorSpanGaugeHud();
            var parameters = AuthorParameters(weapons, liveries, statusDisplay, hudExtras);
            var definition = AuthorDefinition(parameters);
            var prefab = AuthorPrefab(blockout, meshes, definition, awacsMount);
            AuthorDarkreachMounts(prefab, weapons, modMounts);
            AuthorStandardLoadouts(parameters, weapons);
            Set(definition, "unitPrefab", prefab);
            foreach (var guid in AssetDatabase.FindAssets("t:Mesh", new[] { MeshFolder }))
                if (!SavedMeshes.Contains(AssetDatabase.GUIDToAssetPath(guid)))
                    AssetDatabase.DeleteAsset(AssetDatabase.GUIDToAssetPath(guid));
            AssetDatabase.SaveAssets();

            OpReferenceIndex.Refresh();
            AuthorOps(modMounts);
            AssetDatabase.SaveAssets();
            Debug.Log("[Centurion] Authored " + PrefabPath + " from " + blockout.SourceBlend);
        }

        // ---------- blockout ----------

        private sealed class BlockoutPart
        {
            public string Name, Fbx, Sha256, BlenderParent;
            public Vector3 Pivot, Min, Max;
            public Quaternion Rotation;
            public string[] Materials = Array.Empty<string>();
            public int[] MaterialTris = Array.Empty<int>();
            public int ColliderCount;
            public bool HasLod1;
            public Dictionary<string, object> Props;
        }

        private sealed class Blockout
        {
            public string SourceBlend;
            public Dictionary<string, BlockoutPart> Parts = new Dictionary<string, BlockoutPart>();
            public Dictionary<string, string> Textures = new Dictionary<string, string>(); // file name -> sha256
            public Vector3 Origin;

            public bool Has(string name) => Parts.ContainsKey(name);

            // Prefab space: the root is the fuselage_M pivot, so a blockout position u lands at u - Origin.
            public Vector3 Local(string name) => Parts[name].Pivot - Origin;

            public Quaternion Rotation(string name) => Parts[name].Rotation;

            // A part's mass_kg (a control surface's on its hinge empty).
            public float Mass(string name) =>
                Parts.TryGetValue(name, out var p) && p.Props.TryGetValue("mass_kg", out var m) ? Convert.ToSingle(m) : throw new InvalidDataException(name + " has no mass_kg in the blockout");

            // A mesh part (an FBX) as opposed to an empty such as a control-surface or door hinge.
            public bool HasMesh(string name) => Parts.TryGetValue(name, out var part) && part.Fbx != null;

            public static Blockout Load(string folder, string root = "fuselage_M")
            {
                var path = Path.Combine(folder, "blockout.json");
                if (!File.Exists(path))
                    throw new FileNotFoundException("Run tools/export_blockout.py first.", path);
                var json = (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(path));
                var result = new Blockout { SourceBlend = (string)json["source_blend"] };
                if (json.TryGetValue("textures", out var textures))
                    foreach (var entry in (Dictionary<string, object>)textures)
                        result.Textures[entry.Key] = (string)entry.Value;
                foreach (var entry in (Dictionary<string, object>)json["parts"])
                {
                    var part = (Dictionary<string, object>)entry.Value;
                    var bounds = part.TryGetValue("bounds_unity", out var b) ? (List<object>)b : null;
                    var axes = (Dictionary<string, object>)part["axes_unity"];
                    var slots = part.TryGetValue("materials", out var m) ? ((List<object>)m).Cast<List<object>>().ToArray() : new List<object>[0];
                    var lod1 = part.TryGetValue("lod1", out var l) ? l as Dictionary<string, object> : null;
                    result.Parts[entry.Key] = new BlockoutPart
                    {
                        Name = entry.Key, Fbx = part["fbx"] as string, Sha256 = part.TryGetValue("sha256", out var sha) ? (string)sha : null,
                        Pivot = Vec(part["pivot_unity"]), Min = bounds != null ? Vec(bounds[0]) : Vector3.zero, Max = bounds != null ? Vec(bounds[1]) : Vector3.zero,
                        Rotation = Quaternion.LookRotation(Vec(axes["forward"]), Vec(axes["up"])),
                        BlenderParent = part["blender_parent"] as string,
                        Materials = slots.Select(s => (string)s[0]).ToArray(),
                        MaterialTris = slots.Select(s => Convert.ToInt32(s[1])).ToArray(),
                        ColliderCount = part.TryGetValue("colliders", out var c) ? ((List<object>)c).Count : 0,
                        HasLod1 = lod1 != null,
                        Props = (Dictionary<string, object>)part["props"],
                    };
                }
                if (!result.Parts.ContainsKey(root))
                    throw new InvalidDataException($"The blockout has no {root}, the root part.");
                result.Origin = result.Parts[root].Pivot;
                return result;
            }

            // A telescoping stage's slide: its unit axis in prefab space and its travel in metres; null for any other part.
            public (Vector3 Axis, float Travel)? Slide(string name) =>
                Parts.TryGetValue(name, out var p) && p.Props.ContainsKey("travel_m") ? (Vec(p.Props["slide_axis_unity"]), Convert.ToSingle(p.Props["travel_m"])) : ((Vector3, float)?)null;

            // Span with every telescoping stage run out by its travel along its slide axis (stage 2 carries the tips).
            public float ExtendedSpan()
            {
                var tips = new[] { "wing_tip_L", "wing_tip_R" }.Select(n => Parts[n]).ToArray();
                var span = tips.Max(t => t.Pivot.x + t.Max.x) - tips.Min(t => t.Pivot.x + t.Min.x);
                foreach (var stage in Parts.Values.Where(p => p.Props.ContainsKey("travel_m")))
                    span += Convert.ToSingle(stage.Props["travel_m"]) * Mathf.Abs(Vec(stage.Props["slide_axis_unity"]).x);
                return span;
            }

            private static Vector3 Vec(object value)
            {
                var list = (List<object>)value;
                return new Vector3(Convert.ToSingle(list[0]), Convert.ToSingle(list[1]), Convert.ToSingle(list[2]));
            }
        }

        private sealed class PartMeshes
        {
            // Shape: what the physics and aero are measured on. A detailed (M4) part's export carries the blockout mesh it
            // replaced as <part>_shape, so chords, spans, collider hulls, engine and fitting positions stay the blockout's
            // and the detail never changes how the aircraft flies; a blockout part's shape is its render mesh.
            public Mesh Render, Lod1, Shape;
            public Mesh[] Colliders;
            public Material[] Materials, Lod1Materials; // one per submesh, as the importer remapped them
        }

        // Blockout slot name -> the material it stands for.
        private static Dictionary<string, Material> SlotMaterialMap(Material skin, Material gear, Material mech, Material glass, Material airframe)
        {
            var map = SlotMaterials.ToDictionary(s => s.Key, s => Load<Material>(s.Value));
            map[SkinSlot] = skin;
            if (gear != null)
                map["Centurion_gear"] = gear;
            if (mech != null)
                map["jet_mechanical"] = mech;
            map["glass"] = glass;
            if (airframe != null)
                map[AirframeSlot] = airframe;
            map["aircraft_structure"] = AuthorStructure();
            map[LensSlot] = AuthorLens();
            return map;
        }

        private static Dictionary<string, PartMeshes> ImportBlockout(Blockout blockout, Dictionary<string, Material> slots,
            string exportFolder = null, string assetFolder = BlockoutFolder)
        {
            exportFolder = exportFolder ?? ExportFolder;
            var slotOf = slots.ToDictionary(s => s.Value, s => s.Key);
            var meshParts = blockout.Parts.Values.Where(p => p.Fbx != null).ToArray();
            var wanted = new HashSet<string>(meshParts.Select(p => assetFolder + "/" + p.Fbx));
            foreach (var guid in AssetDatabase.FindAssets("t:Model", new[] { assetFolder }))
            {
                var stale = AssetDatabase.GUIDToAssetPath(guid);
                if (!wanted.Contains(stale))
                    AssetDatabase.DeleteAsset(stale);
            }

            var result = new Dictionary<string, PartMeshes>();
            foreach (var part in meshParts.OrderBy(p => p.Name, StringComparer.Ordinal))
            {
                var source = Path.Combine(exportFolder, part.Fbx);
                var target = assetFolder + "/" + part.Fbx;
                var bytes = File.ReadAllBytes(source);
                if (Sha256(bytes) != part.Sha256)
                    throw new InvalidDataException(part.Fbx + " doesn't match blockout.json; rerun the export.");
                if (!File.Exists(target) || !File.ReadAllBytes(target).SequenceEqual(bytes))
                {
                    File.WriteAllBytes(target, bytes);
                    AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport);
                }
                ConfigureModelImporter(target, slots);

                var assets = AssetDatabase.LoadAllAssetsAtPath(target).OfType<Mesh>().ToArray();
                var meshes = new PartMeshes
                {
                    Render = assets.SingleOrDefault(m => m.name == part.Name),
                    Colliders = Enumerable.Range(0, part.ColliderCount).Select(i => assets.SingleOrDefault(m => m.name == part.Name + "_colmesh" + i)).ToArray(),
                    Lod1 = part.HasLod1 ? assets.SingleOrDefault(m => m.name == part.Name + "_lod1") : null,
                };
                meshes.Shape = assets.SingleOrDefault(m => m.name == part.Name + "_shape") ?? meshes.Render;
                if (meshes.Render == null || meshes.Colliders.Contains(null) || part.HasLod1 && meshes.Lod1 == null)
                    throw new InvalidDataException($"{target} lacks the {part.Name} mesh, one of its {part.ColliderCount} collider pieces or its LOD1 hull; it holds [{string.Join(", ", assets.Select(a => a.name))}].");
                // Catches an axis or scale slip in the FBX round trip before it reaches the prefab.
                var bounds = meshes.Render.bounds;
                if ((bounds.min - part.Min).magnitude > 0.02f || (bounds.max - part.Max).magnitude > 0.02f)
                    throw new InvalidDataException($"{part.Name}: imported bounds {bounds.min}..{bounds.max} differ from the export's {part.Min}..{part.Max}.");
                // The importer orders submeshes its own way and remaps each slot to its material by name; every submesh's
                // triangles must match its slot's in the export, and no slot may be left on an imported material.
                var renderers = AssetDatabase.LoadAssetAtPath<GameObject>(target).GetComponentsInChildren<MeshRenderer>(true);
                Material[] MaterialsOf(Mesh mesh) => renderers.Single(r => r.GetComponent<MeshFilter>().sharedMesh == mesh).sharedMaterials;
                meshes.Materials = MaterialsOf(meshes.Render);
                meshes.Lod1Materials = meshes.Lod1 != null ? MaterialsOf(meshes.Lod1) : null;
                var submeshes = Enumerable.Range(0, meshes.Render.subMeshCount)
                    .Select(i => (slot: i < meshes.Materials.Length && meshes.Materials[i] != null && slotOf.TryGetValue(meshes.Materials[i], out var slot) ? slot : "?", tris: (int)meshes.Render.GetSubMesh(i).indexCount / 3)).ToArray();
                if (submeshes.Length != part.Materials.Length || submeshes.Any(m => Array.IndexOf(part.Materials, m.slot) < 0 || part.MaterialTris[Array.IndexOf(part.Materials, m.slot)] != m.tris)
                    || meshes.Lod1Materials != null && meshes.Lod1Materials.Any(m => m == null || !slotOf.ContainsKey(m)))
                    throw new InvalidDataException($"{part.Name}: imported submeshes [{string.Join(", ", submeshes.Select(m => m.slot + " " + m.tris))}] don't match its slots [{string.Join(", ", part.Materials.Zip(part.MaterialTris, (s, n) => s + " " + n))}], or a slot has no stock material.");
                foreach (var collider in meshes.Colliders)
                {
                    // Flat shading splits vertices per face; the hull limit counts distinct points.
                    var points = collider.vertices.Distinct().Count();
                    if (points > 255 || collider.triangles.Length / 3 > 255)
                        throw new InvalidDataException($"{collider.name} has {points} points and {collider.triangles.Length / 3} triangles; the limit is 255.");
                }
                // The stock LOD material reads the vertex colour raw: the blockout writes 0.14 grey.
                if (meshes.Lod1 != null && (meshes.Lod1.colors.Length != meshes.Lod1.vertexCount || meshes.Lod1.colors.Any(c => Mathf.Abs(c.r - 0.14f) > 0.01f)))
                    throw new InvalidDataException($"{meshes.Lod1.name} lacks its 0.14 grey vertex colour ({meshes.Lod1.colors.Length} colours, first {(meshes.Lod1.colors.Length > 0 ? meshes.Lod1.colors[0].ToString() : "none")}).");
                if (slots.TryGetValue(SkinSlot, out var skin))
                    (meshes.Render, meshes.Materials) = SkinFirst(meshes.Render, meshes.Materials, skin);
                result[part.Name] = meshes;
            }
            return result;
        }

        // The mesh with the skin's submesh first (a copy in MeshFolder), or the mesh itself when it already is. The game
        // sets a livery on material slot 0 only (UnitPart.SetLivery); the importer put aircraft_structure first on the
        // tail cone, sponsons, struts, wing stages and wing fairing, which kept the baked grey under every livery.
        private static (Mesh Mesh, Material[] Materials) SkinFirst(Mesh mesh, Material[] materials, Material skin)
        {
            var first = Array.IndexOf(materials, skin);
            if (first <= 0)
                return (mesh, materials);
            var order = new[] { first }.Concat(Enumerable.Range(0, materials.Length).Where(i => i != first)).ToArray();
            var copy = Object.Instantiate(mesh);
            copy.name = mesh.name + "_skinfirst";
            for (var i = 0; i < order.Length; i++)
                copy.SetTriangles(mesh.GetTriangles(order[i]), i, false);
            return (SaveMesh(copy), order.Select(i => materials[i]).ToArray());
        }

        private static void ConfigureModelImporter(string path, Dictionary<string, Material> slots)
        {
            var importer = (ModelImporter)AssetImporter.GetAtPath(path);
            var changed = false;
            void Apply<T>(T current, T wanted, Action<T> set)
            {
                if (EqualityComparer<T>.Default.Equals(current, wanted))
                    return;
                set(wanted);
                changed = true;
            }
            Apply(importer.globalScale, 1f, v => importer.globalScale = v);
            Apply(importer.useFileScale, true, v => importer.useFileScale = v);
            Apply(importer.bakeAxisConversion, false, v => importer.bakeAxisConversion = v);
            Apply(importer.isReadable, true, v => importer.isReadable = v);
            Apply(importer.meshCompression, ModelImporterMeshCompression.Off, v => importer.meshCompression = v);
            Apply(importer.materialImportMode, ModelImporterMaterialImportMode.ImportStandard, v => importer.materialImportMode = v);
            Apply(importer.materialLocation, ModelImporterMaterialLocation.InPrefab, v => importer.materialLocation = v);
            var remaps = importer.GetExternalObjectMap();
            foreach (var slot in slots)
            {
                var id = new AssetImporter.SourceAssetIdentifier(typeof(Material), slot.Key);
                if (!remaps.TryGetValue(id, out var current) || current != slot.Value)
                {
                    importer.AddRemap(id, slot.Value);
                    changed = true;
                }
            }
            Apply(importer.importAnimation, false, v => importer.importAnimation = v);
            Apply(importer.animationType, ModelImporterAnimationType.None, v => importer.animationType = v);
            Apply(importer.importCameras, false, v => importer.importCameras = v);
            Apply(importer.importLights, false, v => importer.importLights = v);
            Apply(importer.importBlendShapes, false, v => importer.importBlendShapes = v);
            Apply(importer.importNormals, ModelImporterNormals.Import, v => importer.importNormals = v);
            Apply(importer.addCollider, false, v => importer.addCollider = v);
            if (changed)
                importer.SaveAndReimport();
        }

        // ---------- definition, parameters, liveries, status display ----------

        private static Dictionary<string, Object> FindWeaponMounts(IEnumerable<string> keys)
        {
            var wanted = new HashSet<string>(keys);
            var found = new Dictionary<string, Object>();
            foreach (var guid in AssetDatabase.FindAssets("t:WeaponMount", new[] { Stock + "MonoBehaviour" }))
            {
                var asset = AssetDatabase.LoadMainAssetAtPath(AssetDatabase.GUIDToAssetPath(guid));
                var key = new SerializedObject(asset).FindProperty("jsonKey")?.stringValue;
                if (key != null && wanted.Contains(key))
                    found[key] = asset;
            }
            var missing = wanted.Where(k => !found.ContainsKey(k)).ToArray();
            if (missing.Length > 0)
                throw new InvalidDataException("Stock weapon mounts not found: " + string.Join(", ", missing));
            return found;
        }

        private sealed class LiveryEntry
        {
            public string Name;
            public Object Faction, Data;
        }

        // The graybox paint (sRGB): the flat neutral grey of the review renders.
        private static readonly Color32 GrayboxPaint = new Color32(96, 96, 96, 255);

        // The skin on the stock AircraftSkin shader, with flat maps the mod owns: the Alkyon's maps follow its own UVs,
        // not the blockout's. Channels as the stock skins hold them (.cache/research/art.md "Texture channels"); the
        // damage maps are flat at the Alkyon's means. An export of the detailed (M4) composite carries the baked 4096 atlas
        // instead (SkinMaps), and the skin takes that.
        private static Material AuthorSkin(Blockout blockout)
        {
            if (SkinMaps.All(m => blockout.Textures.ContainsKey(m.File)))
            {
                var baked = new Material(Load<Shader>(Stock + "Shader/Shader Graphs_AircraftSkin_PLACEHOLDER.shader")) { name = "Centurion_skin" };
                foreach (var map in SkinMaps)
                    baked.SetTexture(map.Property, ImportExportTexture(blockout, map.File, map.SRgb, map.NormalMap));
                baked.SetTexture("_Livery", baked.GetTexture("_Basecolor"));
                baked.SetFloat("_HitPoints", 100f);
                baked.SetFloat("_Glossiness", 0f);
                return SaveAsset(baked, SkinPath);
            }
            var flatNormal = new Color32(128, 128, 255, 255);
            var albedo = AuthorFlatTexture(LiveryFolder + "/centurion_graybox.png", GrayboxPaint, true, false);
            var skin = new Material(Load<Shader>(Stock + "Shader/Shader Graphs_AircraftSkin_PLACEHOLDER.shader")) { name = "Centurion_skin" };
            skin.SetTexture("_Basecolor", albedo);
            skin.SetTexture("_Livery", albedo);
            skin.SetTexture("_Metallic", AuthorFlatTexture(SkinFolder + "/centurion_graybox_m.png", new Color32(0, 0, 0, 102), true, false)); // A: smoothness 0.4
            skin.SetTexture("_Normal", AuthorFlatTexture(SkinFolder + "/centurion_graybox_n.png", flatNormal, false, true));
            skin.SetTexture("_AO", AuthorFlatTexture(SkinFolder + "/centurion_graybox_ao.png", new Color32(255, 255, 255, 255), false, false));
            skin.SetTexture("_BasecolorDmg", AuthorFlatTexture(SkinFolder + "/centurion_graybox_dmg_b.png", new Color32(210, 208, 208, 165), true, false));
            skin.SetTexture("_NormalDmg", AuthorFlatTexture(SkinFolder + "/centurion_graybox_dmg_n.png", flatNormal, false, true));
            skin.SetFloat("_HitPoints", 100f);
            skin.SetFloat("_Glossiness", 0f);
            return SaveAsset(skin, SkinPath);
        }

        // The gear trim on a copy of the stock gear material, when the export carries it; else null (the stock gear).
        private static Material AuthorGear(Blockout blockout)
        {
            if (!GearMaps.All(m => blockout.Textures.ContainsKey(m.File)))
                return null;
            var gear = new Material(Load<Material>(SlotMaterials["Centurion_gear"])) { name = "Centurion_gear" };
            foreach (var map in GearMaps)
                gear.SetTexture(map.Property, ImportExportTexture(blockout, map.File, map.SRgb, map.NormalMap));
            gear.SetTexture("_OcclusionMap", null);
            return SaveAsset(gear, SkinFolder + "/Centurion_gear.mat");
        }

        // The mechanical swatch trim on an opaque copy of the stock jet_mechanical material, when the export carries it;
        // else null (the stock trim).
        private static Material AuthorMech(Blockout blockout)
        {
            if (!MechMaps.All(m => blockout.Textures.ContainsKey(m.File)))
                return null;
            var mech = OpaqueLit(SlotMaterials["jet_mechanical"], "Centurion_mech");
            foreach (var map in MechMaps)
                mech.SetTexture(map.Property, ImportExportTexture(blockout, map.File, map.SRgb, map.NormalMap));
            mech.SetFloat("_Smoothness", 1f); // the swatches carry smoothness in the metal map's alpha
            return SaveAsset(mech, SkinFolder + "/Centurion_mech.mat");
        }

        // The damage structure's trim, when the export carries it (a detailed export with the damage structure); else null.
        private static Material AuthorAirframe(Blockout blockout)
        {
            if (!AirframeMaps.All(m => blockout.Textures.ContainsKey(m.File)))
                return null;
            var airframe = OpaqueLit(SlotMaterials["jet_mechanical"], "Centurion_airframe");
            foreach (var map in AirframeMaps)
                airframe.SetTexture(map.Property, ImportExportTexture(blockout, map.File, map.SRgb, map.NormalMap));
            airframe.EnableKeyword("_NORMALMAP");
            airframe.SetFloat("_Smoothness", 1f); // the trim carries smoothness in the metal map's alpha
            return SaveAsset(airframe, SkinFolder + "/Centurion_airframe.mat");
        }

        private static Material AuthorGlass()
        {
            var glass = OpaqueLit(SlotMaterials["jet_mechanical"], "Centurion_glass");
            glass.SetTexture("_BaseMap", null);
            glass.SetTexture("_MainTex", null);
            glass.SetTexture("_MetallicGlossMap", null);
            glass.DisableKeyword("_METALLICSPECGLOSSMAP");
            glass.SetColor("_BaseColor", GlassTint);
            glass.SetColor("_Color", GlassTint);
            glass.SetFloat("_Metallic", 0f);
            glass.SetFloat("_Smoothness", GlassSmoothness);
            return SaveAsset(glass, SkinFolder + "/Centurion_glass.mat");
        }

        private static Material AuthorStructure()
        {
            var structure = OpaqueLit(SlotMaterials["jet_mechanical"], "Centurion_structure");
            structure.SetTexture("_BaseMap", null);
            structure.SetTexture("_MainTex", null);
            structure.SetTexture("_MetallicGlossMap", null);
            structure.DisableKeyword("_METALLICSPECGLOSSMAP");
            structure.SetColor("_BaseColor", StructurePaint);
            structure.SetColor("_Color", StructurePaint);
            structure.SetFloat("_Metallic", 0f);
            structure.SetFloat("_Smoothness", StructureSmoothness);
            return SaveAsset(structure, SkinFolder + "/Centurion_structure.mat");
        }

        // A copy of a stock Lit material, opaque (no alpha clip), with its normal and occlusion maps off and a white base.
        private static Material OpaqueLit(string stockPath, string name)
        {
            var m = new Material(Load<Material>(stockPath)) { name = name };
            m.SetFloat("_AlphaClip", 0f);
            m.SetFloat("_AlphaToMask", 0f);
            m.DisableKeyword("_ALPHATEST_ON");
            m.SetOverrideTag("RenderType", "Opaque");
            m.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Geometry;
            m.SetTexture("_BumpMap", null);
            m.DisableKeyword("_NORMALMAP");
            m.SetTexture("_OcclusionMap", null);
            m.DisableKeyword("_OCCLUSIONMAP");
            m.SetColor("_BaseColor", Color.white);
            m.SetColor("_Color", Color.white);
            return m;
        }

        // A baked map from the export (the airframe's, or exportFolder's), copied into the skin folder (checked against
        // its hash) and imported at up to SkinMapSize, compressed with mipmaps, in the colour space and type the stock
        // skin maps use.
        private static Texture2D ImportExportTexture(Blockout blockout, string file, bool sRgb, bool normalMap, string exportFolder = null)
        {
            var bytes = File.ReadAllBytes(Path.Combine(exportFolder ?? ExportFolder, "textures", file));
            if (Sha256(bytes) != blockout.Textures[file])
                throw new InvalidDataException(file + " doesn't match blockout.json; rerun the export.");
            var path = SkinFolder + "/" + file;
            if (!File.Exists(path) || !File.ReadAllBytes(path).SequenceEqual(bytes))
            {
                File.WriteAllBytes(path, bytes);
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            }
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            var type = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
            if (importer.textureType != type || importer.sRGBTexture != sRgb || importer.maxTextureSize != SkinMapSize
                || !importer.mipmapEnabled || importer.textureCompression != TextureImporterCompression.Compressed || importer.crunchedCompression)
            {
                importer.textureType = type;
                importer.sRGBTexture = sRgb;
                importer.maxTextureSize = SkinMapSize;
                importer.mipmapEnabled = true;
                importer.textureCompression = TextureImporterCompression.Compressed;
                importer.crunchedCompression = false;
                importer.SaveAndReimport();
            }
            return Load<Texture2D>(path);
        }

        // A flat 64² texture the mod owns, imported with the colour space and type the stock skin maps use.
        private static Texture2D AuthorFlatTexture(string path, Color32 colour, bool sRgb, bool normalMap)
        {
            var texture = new Texture2D(64, 64, TextureFormat.RGBA32, false);
            texture.SetPixels32(Enumerable.Repeat(colour, 64 * 64).ToArray());
            var png = texture.EncodeToPNG();
            Object.DestroyImmediate(texture);
            if (!File.Exists(path) || !File.ReadAllBytes(path).SequenceEqual(png))
            {
                File.WriteAllBytes(path, png);
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            }
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            var type = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
            if (importer.textureType != type || importer.sRGBTexture != sRgb)
            {
                importer.textureType = type;
                importer.sRGBTexture = sRgb;
                importer.SaveAndReimport();
            }
            return Load<Texture2D>(path);
        }

        // The four liveries, as art/blender/m4/livery.py LIVERIES paints them (key, name, faction, sRGB paint and camo
        // tones). The paint is LiveryData.Colors[0], which ColorableMount's renderers (the AWACS mount) take as _Color.
        private static readonly (string Key, string Name, string Faction, Color32[] Paint)[] Liveries =
        {
            ("bdf_matte_gray", "BDF Matte Gray", "Boscali", new[] { new Color32(97, 99, 103, 255) }),
            ("bdf_forest_green", "BDF Forest Green", "Boscali", new[] { new Color32(55, 70, 50, 255) }),
            ("pala_matte_black", "PALA Matte Black", "Primeva", new[] { new Color32(32, 33, 34, 255) }),
            ("pala_desert_camo", "PALA Desert Camo", "Primeva", new[] { new Color32(168, 145, 107, 255), new Color32(120, 92, 64, 255), new Color32(199, 181, 148, 255) }),
        };

        // Each livery's Texture is its full albedo on the skin atlas (the export's centurion_livery_<key>.png), which
        // UnitPart.SetLivery sets as _Livery; an export without them (the graybox) gives every livery the skin's own.
        private static List<LiveryEntry> AuthorLiveries(Blockout blockout, Texture2D skinLivery)
        {
            var liveryType = GameType("LiveryData");
            var result = new List<LiveryEntry>();
            foreach (var old in new[] { "centurion_bdf_graybox", "centurion_pala_graybox" })
                AssetDatabase.DeleteAsset(LiveryFolder + "/" + old + ".asset");
            foreach (var (key, name, faction, paint) in Liveries)
            {
                var file = "centurion_livery_" + key + ".png";
                var data = ScriptableObject.CreateInstance(liveryType);
                data.name = "centurion_" + key;
                var so = new SerializedObject(data);
                Prop(so, "Texture").objectReferenceValue = blockout.Textures.ContainsKey(file) ? ImportExportTexture(blockout, file, true, false) : skinLivery;
                Prop(so, "Glossiness").floatValue = 0f;
                var colors = Prop(so, "Colors");
                colors.arraySize = paint.Length;
                for (var i = 0; i < paint.Length; i++)
                {
                    colors.GetArrayElementAtIndex(i).FindPropertyRelative("Color").colorValue = paint[i];
                    colors.GetArrayElementAtIndex(i).FindPropertyRelative("Count").intValue = 1;
                }
                so.ApplyModifiedPropertiesWithoutUndo();
                result.Add(new LiveryEntry
                {
                    Name = name,
                    Faction = Load<Object>(Stock + "MonoBehaviour/" + faction + "_PLACEHOLDER.asset"),
                    Data = SaveAsset(data, LiveryFolder + "/" + data.name + ".asset"),
                });
            }
            return result;
        }

        private static Behaviour ImageOf(Transform t) => t.GetComponents<Behaviour>().Single(c => c.GetType().Name == "Image");

        private static Object AuthorParameters(Dictionary<string, Object> weapons, List<LiveryEntry> liveries, GameObject statusDisplay, GameObject hudExtras)
        {
            var parameters = Object.Instantiate(Load<Object>(DonorParameters));
            parameters.name = Path.GetFileNameWithoutExtension(ParametersPath);
            var so = new SerializedObject(parameters);
            Prop(so, "aircraftName").stringValue = JsonKey;
            Num(so, "rankRequired", 6);

            var airfoils = Prop(so, "airfoils");
            airfoils.arraySize = 4;
            // CTN_wing stops gaining lift at 0.25 rad and stays flat to 0.31: at the takeoff AI's capped attitude the 199 t
            // retracted aircraft can't lift off the longest runway, while a light one still reaches its touchdown lift
            // (docs/M2-DESIGN.md, G2.6).
            SetAirfoil(airfoils.GetArrayElementAtIndex(WingAirfoil), "CTN_wing", 4.6f, 0.25f, 0.030f, 5.5f, 0.06f);
            SetAirfoil(airfoils.GetArrayElementAtIndex(PanelAirfoil), "CTN_panel", 7.0f, 0.27f, 0.006f, 0.3f);
            // CTN_tail holds its peak from 0.30 to 0.45 rad (17 to 26°), so a tail surface far into its throw still lifts.
            SetAirfoil(airfoils.GetArrayElementAtIndex(TailAirfoil), "CTN_tail", 4.0f, 0.30f, 0.012f, 1.0f, 0.15f);
            // A deflected flap's own lift is all the game gives it: it doesn't raise its parent wing's (AeroJob_Math), and a
            // bigger or steeper stock flap adds more drag than lift. CTN_flap stands in for the lift the flap adds across its
            // wing strip, about +1.2 CL over the two flapped strips at the 30° takeoff preset, with CTN_wing's drag, so the
            // 199 t extended roll clears 50 ft in about 1,540 m (docs/SPEC.md, the flap row; src/Centurion/FlapPreset.cs).
            SetFlapAirfoil(airfoils.GetArrayElementAtIndex(FlapAirfoil), airfoils.GetArrayElementAtIndex(WingAirfoil), 18f);

            Object W(string key) => key != null && weapons.TryGetValue(key, out var mount) ? mount : null;
            var loadouts = Prop(so, "loadouts");
            loadouts.arraySize = 2;
            SetWeapons(loadouts.GetArrayElementAtIndex(0).FindPropertyRelative("weapons"), null, null, null, W(CramKey));
            SetWeapons(loadouts.GetArrayElementAtIndex(1).FindPropertyRelative("weapons"), W(Bomb500ForwardKey), W(Bomb500AftKey), null, W(CramKey));
            Num(so, "DefaultFuelLevel", 0.6f);
            // The donor's takeoff music is the Alkyon's own theme ("Alkyon AB-4.ogg", played at every gear-down liftoff,
            // Aircraft.cs:1812-1819); the Centurion stays silent until its own sound set (M5).
            Prop(so, "takeoffMusic").objectReferenceValue = null;

            var liveriesProp = Prop(so, "liveries");
            liveriesProp.arraySize = liveries.Count;
            for (var i = 0; i < liveries.Count; i++)
            {
                var entry = liveriesProp.GetArrayElementAtIndex(i);
                entry.FindPropertyRelative("name").stringValue = liveries[i].Name;
                entry.FindPropertyRelative("faction").objectReferenceValue = liveries[i].Faction;
                var reference = entry.FindPropertyRelative("assetReference");
                reference.FindPropertyRelative("m_AssetGUID").stringValue = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(liveries[i].Data));
                reference.FindPropertyRelative("m_SubObjectName").stringValue = string.Empty;
            }
            Prop(so, "StatusDisplay").objectReferenceValue = statusDisplay;
            Prop(so, "HUDExtras").objectReferenceValue = hudExtras;

            // AI tuning for a 125 to 199 t bomber (start values; M2 and M6 tune them). Speeds from tools/fm/centurion_built.py.
            Num(so, "aircraftGLimit", 2.5f);
            Num(so, "maxSpeed", 250f);
            // The takeoff AI holds the nose down until 0.7 x takeoffSpeed, then pulls for 9.5° (AIPilotTakeoffState.cs:130-137,
            // 176), and the tail strikes at 10.49° (blockout step 6). With CTN_flap at 30° the 199 t extended aircraft asks for
            // rotation at 70 m/s, lifts the nose at 75 and lifts off at 79 with the tail 7.9° clear; at 130 it waited until 91.
            Num(so, "takeoffSpeed", 100f);
            // The landing and takeoff AIs only use runways at least this long (AIPilotLandingState.cs:99, 184), and
            // AiAirfieldRules keeps the AI Centurion off bases without one. The 199 t extended roll to 50 ft, 1,545 m at the
            // worst pitch inertia, plus 10% for the replica, is 90% of 1,907 m: Vigil Cay's 1,907.4 m runway, the shortest at a
            // base whose medium hangar fits it.
            Num(so, "takeoffDistance", 1907f);
            Num(so, "turningRadius", 6000f);
            // AutoAim climbs at most 0.9 x (airspeed / cornerSpeed)^2 rad (AutopilotPlane.cs:47-54); at 280 that demand
            // meets what the engines sustain at about 105 m/s and 10° alpha, short of the 13° stall, up to 160 t.
            Num(so, "cornerSpeed", 280f);
            Num(so, "approachSpeed", 80f);
            // At maxWeight, scaled by sqrt(mass / maxWeight) (AIPilotLandingState.cs:96): touchdown at about 1.19 x the
            // flaps-down stall at any mass (82 m/s at 132 t, 101 at 199 t). On the runway the landing AI aims the nose about
            // 10° up (a point 100 m on and 18 m up, :399-425) and goes around once radar altitude passes 1 m (:376); at 130
            // the wing lifted the light aircraft off again. The AI lands extended, and at 105 the 199 t touchdown is 105 m/s with
            // the rollout on the wheels (tools/fm/centurion_landing.py, centurion_span.py).
            Num(so, "landingSpeed", 105f);
            Num(so, "shortLandingSpeed", 80f);
            Num(so, "cruiseThrottle", 0.8f);
            Num(so, "minimumRadarAlt", 200f);
            Num(so, "groundTurningRadius", 40f);
            so.ApplyModifiedPropertiesWithoutUndo();
            return SaveAsset(parameters, ParametersPath);
        }

        // Odd lift curve through zero (camber lives in the lift transform's incidence), linear to stall, flat for
        // plateau rad, then the stock post-stall shape; drag symmetric, cd0 + k*alpha^2 to the top of the curve. Linear
        // tangents so the game's 128-bin chart reproduces the keys (tools/fm/centurion_span.py author_airfoil).
        private static void SetAirfoil(SerializedProperty airfoil, string name, float slope, float stall, float cd0, float k, float plateau = 0f)
        {
            var clMax = slope * stall;
            var top = stall + plateau;
            var lift = new List<Vector2> { new Vector2(0, 0), new Vector2(stall, clMax) };
            if (plateau > 0)
                lift.Add(new Vector2(top, clMax));
            lift.AddRange(new[] { new Vector2(top + 0.09f, clMax * 0.75f), new Vector2(0.785f, 1.10f), new Vector2(1.57f, 0), new Vector2(3.1416f, 0) });
            var drag = new List<Vector2>();
            for (var a = 0f; a < top; a += 0.05f)
                drag.Add(new Vector2(a, cd0 + k * a * a));
            drag.Add(new Vector2(top, cd0 + k * top * top));
            drag.Add(new Vector2(top + 0.09f, cd0 + k * top * top + 0.12f));
            drag.AddRange(new[] { new Vector2(0.785f, 0.60f), new Vector2(1.57f, 0.65f), new Vector2(3.1416f, 0.02f) });
            airfoil.FindPropertyRelative("name").stringValue = name;
            airfoil.FindPropertyRelative("liftCoef").animationCurveValue = LinearCurve(lift, odd: true);
            airfoil.FindPropertyRelative("dragCoef").animationCurveValue = LinearCurve(drag, odd: false);
        }

        // CTN_wing's lift times 1 + (gain - 1) x clamp01((|alpha| - 20°) / 5°), its drag unchanged: below 20° of local
        // incidence a flap flies CTN_wing, so stowed and trimmed it lifts as before. Keys at the game's 128 chart angles
        // (Airfoil.cs:17-36) with linear tangents, so the chart is exactly these samples (tools/fm/centurion_span.py).
        private static void SetFlapAirfoil(SerializedProperty flap, SerializedProperty wing, float gain)
        {
            var wingLift = wing.FindPropertyRelative("liftCoef").animationCurveValue;
            var lift = new List<Vector2>();
            for (var i = 64; i <= 128; i++)
            {
                var alpha = i < 128 ? (i - 64) * 0.04908734f : 3.1416f;
                var blend = Mathf.Clamp01((Mathf.Abs(alpha) - 20f * Mathf.Deg2Rad) / (5f * Mathf.Deg2Rad));
                lift.Add(new Vector2(alpha, wingLift.Evaluate(alpha) * (1f + (gain - 1f) * blend)));
            }
            flap.FindPropertyRelative("name").stringValue = "CTN_flap";
            flap.FindPropertyRelative("liftCoef").animationCurveValue = LinearCurve(lift, odd: true);
            flap.FindPropertyRelative("dragCoef").animationCurveValue = wing.FindPropertyRelative("dragCoef").animationCurveValue;
        }

        private static AnimationCurve LinearCurve(List<Vector2> positive, bool odd)
        {
            var points = positive.Where(p => p.x > 0).Reverse().Select(p => new Vector2(-p.x, odd ? -p.y : p.y)).Concat(positive).ToList();
            var keys = points.Select(p => new Keyframe(p.x, p.y)).ToArray();
            for (var i = 0; i < keys.Length; i++)
            {
                var inSlope = i > 0 ? (keys[i].value - keys[i - 1].value) / (keys[i].time - keys[i - 1].time) : 0f;
                var outSlope = i < keys.Length - 1 ? (keys[i + 1].value - keys[i].value) / (keys[i + 1].time - keys[i].time) : 0f;
                keys[i].inTangent = i > 0 ? inSlope : outSlope;
                keys[i].outTangent = i < keys.Length - 1 ? outSlope : inSlope;
            }
            return new AnimationCurve(keys) { preWrapMode = WrapMode.ClampForever, postWrapMode = WrapMode.ClampForever };
        }

        private static void SetWeapons(SerializedProperty list, params Object[] weapons)
        {
            if (weapons.Length != HardpointSetCount)
                throw new ArgumentException("A loadout needs one entry per hardpoint set.");
            list.arraySize = weapons.Length;
            for (var i = 0; i < weapons.Length; i++)
                list.GetArrayElementAtIndex(i).objectReferenceValue = weapons[i];
        }

        // The racks AuthorDarkreachMounts adds exist only once the prefab is authored, so the presets are set after it.
        private static void AuthorStandardLoadouts(Object parameters, Dictionary<string, Object> weapons)
        {
            var so = new SerializedObject(parameters);
            Object W(string key) => key != null && weapons.TryGetValue(key, out var mount) ? mount : null;
            var standard = new List<(string name, Object[] weapons, float fuel)>
            {
                ("Bombs 500 x93", new[] { W(Bomb500ForwardKey), W(Bomb500AftKey), null, W(CramKey) }, BombLoadoutFuel(W(Bomb500ForwardKey), W(Bomb500AftKey), W(CramKey))),
                ("Bombs 250 x198", new[] { W(Bomb250ForwardKey), W(Bomb250AftKey), null, W(CramKey) }, BombLoadoutFuel(W(Bomb250ForwardKey), W(Bomb250AftKey), W(CramKey))),
                ("Glide Bombs 250 x174", new[] { W(BombGlideForwardKey), W(BombGlideAftKey), null, W(CramKey) }, BombLoadoutFuel(W(BombGlideForwardKey), W(BombGlideAftKey), W(CramKey))),
                // The AI picks presets evenly (AircraftParameters.GetRandomStandardLoadout), so each bomber preset also makes an
                // HQ-deployed Centurion an AWACS less often. Rack keys are AuthorDarkreachMounts' pinned counts.
                ("Glide Bombs 500 x68", new[] { W("baanish_centurion_gbm500lr_32"), W("baanish_centurion_gbm500lr_36"), null, W(CramKey) }, BombLoadoutFuel(W("baanish_centurion_gbm500lr_32"), W("baanish_centurion_gbm500lr_36"), W(CramKey))),
                ("Tusko-B x48", new[] { W("baanish_centurion_tusko_24"), W("baanish_centurion_tusko_24"), null, W(CramKey) }, BombLoadoutFuel(W("baanish_centurion_tusko_24"), W("baanish_centurion_tusko_24"), W(CramKey))),
                ("AShM-300 x36", new[] { W("baanish_centurion_ashm300_18"), W("baanish_centurion_ashm300_18"), null, W(CramKey) }, BombLoadoutFuel(W("baanish_centurion_ashm300_18"), W("baanish_centurion_ashm300_18"), W(CramKey))),
                ("Bombs 500 x16", new[] { W("bomb_500_internalx8"), W("bomb_500_internalx8"), null, W(CramKey) }, 1.0f),
            };
            // The aft bay stays empty under the beam's mast sleeve (BuildBays); without a beam mount there is no AWACS to offer.
            // The forward bay's dense ARAD rack, 16 rounds, which the AI AWACS fires in pairs (AwacsArad; owner, 2026-10-18).
            if (weapons.ContainsKey(AwacsKey))
                standard.Add(("AWACS", new[] { W("baanish_centurion_arad_16"), null, W(AwacsKey), W(CramKey) }, 1.0f));
            var standardProp = Prop(so, "StandardLoadouts");
            standardProp.arraySize = standard.Count;
            for (var i = 0; i < standard.Count; i++)
            {
                var entry = standardProp.GetArrayElementAtIndex(i);
                entry.FindPropertyRelative("disabled").boolValue = false;
                entry.FindPropertyRelative("Name").stringValue = standard[i].name;
                entry.FindPropertyRelative("FuelRatio").floatValue = standard[i].fuel;
                SetWeapons(entry.FindPropertyRelative("loadout").FindPropertyRelative("weapons"), standard[i].weapons);
            }
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static Object AuthorDefinition(Object parameters)
        {
            var definition = Object.Instantiate(Load<Object>(DonorDefinition));
            definition.name = Path.GetFileNameWithoutExtension(DefinitionPath);
            var so = new SerializedObject(definition);
            Prop(so, "jsonKey").stringValue = JsonKey;
            Prop(so, "unitName").stringValue = "MRB-100 Centurion";
            Prop(so, "code").stringValue = "MRB-100";
            // friendlyIcon and hostileIcon stay the donor's hudIcon_aircraft: every stock aircraft's HUD contact is that triangle.
            Prop(so, "mapIcon").objectReferenceValue = ImportSprite(ModFolder + "/Icons/centurion_map.png");
            Prop(so, "description").stringValue = "Long-endurance multirole bomber with a telescoping high wing, two geared turbofans, nose and tail radars, and a laser point-defence turret. Carries bombs or cruise missiles in two internal bays, or an AWACS radome.";
            // Retracted, scaled by footprint from Aryx's MC-260 Chimera (radarSize 9 at 34.6 x 40.2 m; owner, 2026-10-19):
            // TelescopeController adds up to 13 as the wing extends.
            Num(so, "radarSize", 13f);
            // At 0 the C-RAM never fires: a turret scores a target by its weapon's effectiveness times the carrier's role.
            Num(so, "roleIdentity.antiMissile", 0.3f);
            Num(so, "length", 44.95f);
            Num(so, "width", 43.6f); // retracted span: the hangar clearance radius uses it
            Num(so, "height", 7.51f); // the V-tail tips
            Num(so, "value", 500f);
            Num(so, "mass", EmptyMass);
            Num(so, "manpower", 2); // the pilot and the mission commander; mission statistics count crew one by one
            // spawnOffset and restRotation come from the gear in SetRestPose.
            Prop(so, "aircraftParameters").objectReferenceValue = parameters;
            var info = Prop(so, "aircraftInfo");
            Num(info.FindPropertyRelative("emptyWeight"), EmptyMass);
            Num(info.FindPropertyRelative("maxWeight"), 199000f);
            Num(info.FindPropertyRelative("maxSpeed"), 950f);
            Num(info.FindPropertyRelative("stallSpeed"), 290f);
            Num(info.FindPropertyRelative("maneuverability"), 3f);
            so.ApplyModifiedPropertiesWithoutUndo();
            return SaveAsset(definition, DefinitionPath);
        }

        private static void AuthorOps(List<(string Key, int Set)> modMounts)
        {
            var offered = new HashSet<string>(BayWeapons.Concat(modMounts.Select(m => m.Key)), StringComparer.Ordinal);
            foreach (var path in Directory.GetFiles(ModFolder, "OpAddWeaponToHardpoint_*.asset"))
                if (!offered.Contains(Path.GetFileNameWithoutExtension(path).Substring("OpAddWeaponToHardpoint_".Length)))
                    if (!AssetDatabase.DeleteAsset(path.Replace('\\', '/')))
                        throw new IOException("Could not remove retired hardpoint operation " + path);
            var index = OpReferenceIndex.Load();
            if (index == null || !index.Aircraft.Exists(a => a.jsonKey == JsonKey))
                throw new InvalidDataException("OpReferenceIndex doesn't list " + JsonKey + " after Refresh.");
            var hangar = index.HangarUnits.Find(h => h.jsonKey == HangarUnitKey)
                ?? throw new InvalidDataException("OpReferenceIndex has no hangar unit " + HangarUnitKey + ".");
            var sets = index.Aircraft.Find(a => a.jsonKey == JsonKey).hardpointNames;
            if (sets.Count != HardpointSetCount)
                throw new InvalidDataException(JsonKey + " indexes " + sets.Count + " hardpoint sets, expected " + HardpointSetCount + ".");

            var hangarOp = ScriptableObject.CreateInstance<OpAddAircraftToHangars>();
            hangarOp.name = "OpAddAircraftToHangars_centurion";
            hangarOp.aircraftJsonKey = JsonKey;
            hangarOp.hangars.Add(new OpAddAircraftToHangars.HangarTarget { hangarUnitJsonKey = hangar.jsonKey, hangarNames = new List<string>(hangar.hangarNames) });
            SaveAsset(hangarOp, ModFolder + "/" + hangarOp.name + ".asset");

            void AddWeaponOp(string weapon, params int[] hardpointIndices)
            {
                var op = ScriptableObject.CreateInstance<OpAddWeaponToHardpoint>();
                op.name = "OpAddWeaponToHardpoint_" + weapon;
                op.weaponJsonKey = weapon;
                op.aircraft.Add(new OpAddWeaponToHardpoint.AircraftTarget { aircraftJsonKey = JsonKey, hardpointIndices = new List<int>(hardpointIndices) });
                SaveAsset(op, ModFolder + "/" + op.name + ".asset");
            }
            foreach (var weapon in BayWeapons)
            {
                if (!index.Weapons.Contains(weapon))
                    throw new InvalidDataException("OpReferenceIndex has no weapon " + weapon + ".");
                AddWeaponOp(weapon, weapon == "ARM1_internalx4" ? new[] { 0 } : new[] { 0, 1 });
            }
            // The index lists stock weapons only, so the mod's own mounts skip that check.
            foreach (var mount in modMounts.GroupBy(m => m.Key))
                AddWeaponOp(mount.Key, mount.Select(m => m.Set).Distinct().ToArray());
            Debug.Log($"[Centurion] Ops: hangar {hangar.jsonKey} [{string.Join(", ", hangar.hangarNames)}]; {BayWeapons.Length} bay weapons on sets 0 and 1 and {modMounts.Count} mod mounts of [{string.Join(", ", sets)}]");
        }

        // ---------- prefab ----------

        private sealed class Build
        {
            public GameObject Root;
            public Blockout Blockout;
            public Dictionary<string, PartMeshes> Meshes;
            public Material Skin;
            public Component Aircraft;
            public readonly Dictionary<string, GameObject> Parts = new Dictionary<string, GameObject>();
            public readonly Dictionary<string, List<string>> Joints = new Dictionary<string, List<string>>(); // part -> parent, then braces
            public readonly Dictionary<string, Transform> Visuals = new Dictionary<string, Transform>();
            public readonly List<Renderer> Lod1 = new List<Renderer>();
            public readonly List<string> Report = new List<string>();

            public Transform Donor(string path) => Root.transform.Find(path) ?? throw new MissingReferenceException("Alkyon has no " + path);
            public Component Part(string name) => Parts[name].GetComponent(GameType("AeroPart"));

            public Material[] MaterialsFor(string blockoutName) => Meshes[blockoutName].Materials;
        }

        private static GameObject AuthorPrefab(Blockout blockout, Dictionary<string, PartMeshes> meshes, Object definition, Object awacsMount)
        {
            var root = (GameObject)Object.Instantiate(Load<GameObject>(DonorPrefab), Vector3.zero, Quaternion.identity);
            try
            {
                root.name = Path.GetFileNameWithoutExtension(PrefabPath);
                var build = new Build { Root = root, Blockout = blockout, Meshes = meshes };
                build.Aircraft = root.GetComponent(GameType("Aircraft"));
                if (Mathf.Abs(blockout.Origin.z - SpawnForward) > 0.01f)
                    throw new InvalidDataException($"fuselage_M's pivot moved to {blockout.Origin}; update SpawnForward.");
                build.Skin = Load<Material>(SkinPath);
                Set(build.Aircraft, "definition", definition);

                var calibration = CalibrateSurfaceSigns(build);
                StripDonor(build);
                BuildParts(build);
                SplitLift(build);
                AddSlideEnds(build);
                BuildSurfaces(build, calibration);
                Object.DestroyImmediate(calibration.Template.gameObject);
                TuneFlyByWire(build);
                PlaceSystems(build);
                PlaceFlareEjectors(build);
                PlaceWingtipLights(build);
                PlaceVaporCone(build);
                BuildEngines(build);
                SwapEngineAudio(build);
                AddSurfaceAudio(build);
                BuildGear(build);
                BuildBays(build);
                BuildRadars(build);
                BuildCramEye(build);
                BuildFlightDeck(build);
                BuildCockpitDisplay(build);
                SetRestPose(build, definition);
                AttachLeftovers(build);
                AddLods(build);
                CheckFixedDome(build);
                ListLiveryRenderers(build);
                FinishRoot(build);
                AuthorDamage(build);
                WriteJoints(build);
                Validate(build, awacsMount);
                CheckDamage(build);
                CheckEngineAudio(build);
                CheckSurfaceAudio(build);
                foreach (var line in build.Report)
                    Debug.Log("[Centurion] " + line);
                return SavePrefab(root, PrefabPath);
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        // Removes what the Centurion doesn't have (anatomy.md section 3) and renames the shell's reused parts.
        private static void StripDonor(Build b)
        {
            var root = b.Root;
            // The Alkyon's WSO goes; BuildFlightDeck replaces its whole crew. Duplicate siblings get distinct names: patch paths
            // resolve by name.
            // Keep pieces that live inside parts about to go: engines, nozzles, nav lights, wingtip vortices.
            var keep = new Dictionary<string, Transform>();
            foreach (var path in new[] { "wingroot_L/engines_L/engine1", "wingroot_L/engines_L/engine2", "wingroot_R/engines_R/engine3", "wingroot_R/engines_R/engine4",
                         "wingroot_L/engines_L/nozzles_L/nozzle1", "wingroot_L/engines_L/nozzles_L/nozzle2", "wingroot_R/engines_R/nozzles_R/nozzle3", "wingroot_R/engines_R/nozzles_R/nozzle4",
                         "wingroot_L/wing1_L/wing2_L/wingtip_L/navlight_L", "wingroot_R/wing1_R/wing2_R/wingtip_R/navlight_R",
                         "wingroot_L/wing1_L/wing2_L/wingtip_L/wingtipvortex_L", "wingroot_R/wing1_R/wing2_R/wingtip_R/wingtipvortex_R" })
            {
                var t = b.Donor(path);
                t.SetParent(root.transform, true);
                keep[t.name] = t;
            }
            // The wingtip nav lights' NavLights entries name the doomed wingtips as their part, and DestroyWithReferences
            // would drop the whole entry, leaving the light lit for good. They lose only the part; PlaceSystems gives them
            // the stage that carries the light.
            var navLights = new SerializedObject(root.GetComponent(GameType("NavLights")));
            foreach (var light in new[] { "navlight_L", "navlight_R" })
                NavLightEntry(navLights, keep[light].GetComponent<Renderer>()).FindPropertyRelative("part").objectReferenceValue = null;
            navLights.ApplyModifiedPropertiesWithoutUndo();
            var doomed = new List<Object>();
            void Doom(string path) => doomed.Add(b.Donor(path).gameObject);
            foreach (var path in new[]
                     {
                         "fuselage_F/fuselage_FF/cockpit/WSO", "fuselage_F/fuselage_FF/cheek_FL", "fuselage_F/fuselage_FF/cheek_FR", "fuselage_F/cheek_RL", "fuselage_F/cheek_RR",
                         "fuselage_F/gearDoorHinge_FL1", "fuselage_F/gearDoorHinge_FR1", "intake_L", "intake_R",
                         "gearbay_L/gearDoorHinge_LL1", "gearbay_L/gearDoorHinge_L1", "gearbay_R/gearDoorHinge_R1", "gearbay_R/gearDoorHinge_RR1",
                         "wingroot_L/wingHinge_La", "wingroot_R/wingHinge_Ra", "wingroot_L/wing1_L", "wingroot_R/wing1_R", "wingroot_L/engines_L", "wingroot_R/engines_R",
                         "weaponBay_forward", "weaponBay_combined", "fuselage_R/weaponBay_rear", "ladder",
                     })
                Doom(path);
            // Afterburners: the Centurion's geared fans have none.
            foreach (var nozzle in new[] { "nozzle1", "nozzle2", "nozzle3", "nozzle4" })
            {
                var jet = keep[nozzle].GetComponent(GameType("JetNozzle"));
                var so = new SerializedObject(jet);
                var afterburners = Prop(so, "afterburners");
                for (var i = 0; i < afterburners.arraySize; i++)
                    foreach (var field in new[] { "flameRenderer", "nozzleGlowRenderer", "source" })
                    {
                        var target = afterburners.GetArrayElementAtIndex(i).FindPropertyRelative(field).objectReferenceValue as Component;
                        if (target != null && target.gameObject != jet.gameObject && !doomed.Contains(target.gameObject))
                            doomed.Add(target.gameObject);
                    }
                afterburners.arraySize = 0;
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            // Two engines: the Alkyon's engines 3 and 4 go with their nozzles, and so do their entries in the capacitor's
            // powerSources and every other list holding them.
            doomed.AddRange(new[] { "engine3", "engine4", "nozzle3", "nozzle4" }.Select(n => (Object)keep[n].gameObject));
            // Both swing-wing controllers (wing sweep on the root, tail fold on fuselage_R) and the gear bays' tanks.
            doomed.AddRange(root.GetComponentsInChildren(GameType("SwingWingController"), true));
            doomed.Add(b.Donor("gearbay_L").GetComponent(GameType("FuelTank")));
            doomed.Add(b.Donor("gearbay_R").GetComponent(GameType("FuelTank")));
            // The Alkyon's LoD meshes under the parts this build reuses. The kept cockpit's goes too: it sits inside the nose
            // and radar fairing, whose LOD1 hulls draw that far out.
            foreach (var spec in Parts.Where(p => p.Reuse != null))
            {
                var part = spec.Reuse == "" ? root.transform : b.Donor(spec.Reuse);
                doomed.AddRange(part.Cast<Transform>().Where(t => t.name == "LoD").Select(t => (Object)t.gameObject));
            }
            doomed.AddRange(WarningLampObjects(root));
            DestroyWithReferences(b, doomed);

            // Alkyon names that mean something else now (the Alkyon's "nose" is the radar fairing).
            b.Donor("fuselage_F/fuselage_FF/nose").name = "radar_F_fairing";
            b.Donor("fuselage_F/fuselage_FF").name = "nose";
            b.Donor("fuselage_R/tail").name = "tailcone";
            b.Donor("gearbay_L").name = "sponson_L";
            b.Donor("gearbay_R").name = "sponson_R";
            b.Donor("wingroot_L").name = "wing_root_L";
            b.Donor("wingroot_R").name = "wing_root_R";
        }

        // A PartSpec.Reuse path (the Alkyon's names) as it reads after StripDonor's renames.
        private static string Renamed(string donorPath) =>
            donorPath.Replace("fuselage_FF/nose", "nose/radar_F_fairing").Replace("fuselage_FF", "nose").Replace("fuselage_R/tail", "fuselage_R/tailcone")
                .Replace("gearbay_", "sponson_").Replace("wingroot_", "wing_root_");

        // Deletes objects after removing every reference to them from the remaining components: a list entry that
        // holds one is removed (a nav light, a gear door), a plain field is cleared and reported.
        private static void DestroyWithReferences(Build b, List<Object> doomedRoots)
        {
            var doomed = new HashSet<Object>();
            foreach (var target in doomedRoots)
            {
                if (target is GameObject go)
                    foreach (var t in go.GetComponentsInChildren<Transform>(true))
                    {
                        doomed.Add(t.gameObject);
                        foreach (var c in t.GetComponents<Component>())
                            doomed.Add(c);
                    }
                else
                    doomed.Add(target);
            }
            foreach (var component in b.Root.GetComponentsInChildren<Component>(true))
            {
                if (component == null || doomed.Contains(component))
                    continue;
                var so = new SerializedObject(component);
                var elements = new List<(string array, int index)>();
                var fields = new List<string>();
                var it = so.GetIterator();
                while (it.Next(true))
                {
                    if (it.propertyType != SerializedPropertyType.ObjectReference || it.objectReferenceValue == null || !doomed.Contains(it.objectReferenceValue))
                        continue;
                    var match = Regex.Match(it.propertyPath, @"^(.*)\.Array\.data\[(\d+)\][^\[\]]*$");
                    if (match.Success)
                        elements.Add((match.Groups[1].Value, int.Parse(match.Groups[2].Value)));
                    else
                        fields.Add(it.propertyPath);
                }
                foreach (var path in fields)
                {
                    so.FindProperty(path).objectReferenceValue = null;
                    b.Report.Add($"cleared {PathOf(component.transform, b.Root.transform)}:{component.GetType().Name}.{path}");
                }
                foreach (var (array, index) in elements.Distinct().OrderByDescending(e => e.array.Length).ThenByDescending(e => e.index))
                {
                    var list = so.FindProperty(array);
                    if (index >= list.arraySize)
                        continue; // two dead references in one entry
                    var element = list.GetArrayElementAtIndex(index);
                    if (element.propertyType == SerializedPropertyType.ObjectReference)
                        element.objectReferenceValue = null;
                    list.DeleteArrayElementAtIndex(index);
                }
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            foreach (var target in doomedRoots.Where(t => t != null && !(t is GameObject)))
                Object.DestroyImmediate(target);
            foreach (var target in doomedRoots.OfType<GameObject>().Where(t => t != null))
                Object.DestroyImmediate(target);
        }

        private static void BuildParts(Build b)
        {
            var aeroType = GameType("AeroPart");
            var template = b.Donor("wing_root_L").GetComponent(aeroType);
            var templateCopy = new GameObject("aeropart_template").AddComponent(aeroType);
            EditorUtility.CopySerialized(template, templateCopy);
            // The reused donor parts, found by their donor paths before any part moves under a new one (fuselage_F under
            // fuselage_F2).
            var donors = Parts.Where(p => p.Reuse != null).ToDictionary(p => p.Name, p => p.Reuse == "" ? b.Root : b.Donor(Renamed(p.Reuse)).gameObject);
            try
            {
                foreach (var spec in Parts)
                {
                    GameObject go;
                    if (spec.Reuse != null)
                    {
                        go = donors[spec.Name];
                        go.name = spec.Parent == null ? b.Root.name : spec.Name;
                    }
                    else
                    {
                        go = new GameObject(spec.Name) { layer = b.Root.layer };
                        go.transform.SetParent(b.Parts[spec.Parent].transform, false);
                        EditorUtility.CopySerialized(templateCopy, go.AddComponent(aeroType));
                    }
                    b.Parts[spec.Name] = go;
                    if (spec.Parent != null && go.transform.parent != b.Parts[spec.Parent].transform)
                        go.transform.SetParent(b.Parts[spec.Parent].transform, true);
                    if (b.Blockout.HasMesh(spec.Name))
                    {
                        // Sections, hulls and lift frames assume a part mesh in prefab axes.
                        if (Quaternion.Angle(b.Blockout.Rotation(spec.Name), Quaternion.identity) > 0.01f)
                            throw new InvalidDataException(spec.Name + " is rotated in the blockout; an aero part's mesh must be axis-aligned.");
                        go.transform.SetPositionAndRotation(b.Blockout.Local(spec.Name), Quaternion.identity);
                        if (!spec.KeepDonorMesh)
                            SetMeshes(b, go, spec.Name);
                    }
                    else if (!spec.KeepDonorMesh)
                    {
                        RemoveMeshes(go);
                    }
                    var mass = (spec.Mass ?? b.Blockout.Mass(spec.Name)) + VisualPieces.Where(v => v.Part == spec.Name).Sum(v => b.Blockout.Mass(v.Piece));
                    // The blockout includes the removable laser hardware in the mass of the part its turret sits on.
                    if (spec.Name == CramHost) mass -= CramMass;
                    ConfigurePart(b, go, mass, spec.WingArea, spec.DragArea, spec.Airfoil, !spec.KeepDonorMesh);
                    AddJoint(b, spec.Name, spec.Parent, spec.Braces);
                    var tank = go.GetComponent(GameType("FuelTank"));
                    if (spec.FuelKg > 0)
                    {
                        if (tank == null)
                        {
                            // Keep the tank on its AeroPart for Unit.RpcFuelTankStatus's same-transform lookup.
                            tank = go.AddComponent(GameType("FuelTank"));
                            EditorUtility.CopySerialized(b.Root.GetComponent(GameType("FuelTank")), tank);
                        }
                        Set(tank, "fuelCapacity", spec.FuelKg);
                        Set(tank, "part", go.GetComponent(aeroType));
                    }
                    else if (tank != null)
                        Object.DestroyImmediate(tank);
                }
                // Once every part stands: a cut part's lift frame is measured on all its pieces' shapes (ShapeGroup).
                foreach (var spec in Parts.Where(p => p.Lift != Lift.None))
                    SetLiftNormal(b, spec, b.Parts[spec.Name]);
            }
            finally
            {
                Object.DestroyImmediate(templateCopy.gameObject);
            }
        }

        // Where each telescoping stage's pivot sits at full extension: an empty "<stage>_extended" under the part it slides
        // on, its travel along the blockout's slide axis from the retracted pose. TelescopeController slides the stage from its
        // spawn pose to this marker, and ColliderOverlaps checks the same path.
        private static void AddSlideEnds(Build b)
        {
            foreach (var spec in Parts.Where(p => b.Blockout.Slide(p.Name).HasValue))
            {
                var (axis, travel) = b.Blockout.Slide(spec.Name).Value;
                var parent = b.Parts[spec.Parent].transform;
                var end = parent.Find(spec.Name + "_extended") ?? new GameObject(spec.Name + "_extended") { layer = parent.gameObject.layer }.transform;
                end.SetParent(parent, false);
                end.position = b.Parts[spec.Name].transform.position + axis * travel;
            }
        }

        private static void SetMeshes(Build b, GameObject go, string blockoutName)
        {
            var meshes = b.Meshes[blockoutName];
            Ensure<MeshFilter>(go).sharedMesh = meshes.Render;
            Ensure<MeshRenderer>(go).sharedMaterials = b.MaterialsFor(blockoutName);
            // The blockout's convex pieces, or for a part without any (a nozzle inside its nacelle's cowl) the hull of
            // its mesh: a part's Rigidbody with no collider gets Unity's unit inertia tensor (PartStructureCheck).
            foreach (var old in go.GetComponents<MeshCollider>())
                Object.DestroyImmediate(old);
            foreach (var piece in meshes.Colliders.DefaultIfEmpty(meshes.Shape))
            {
                var col = go.AddComponent<MeshCollider>();
                col.sharedMesh = piece;
                col.convex = true;
            }
        }

        private static void RemoveMeshes(GameObject go)
        {
            foreach (var c in go.GetComponents<MeshCollider>())
                Object.DestroyImmediate(c);
            if (go.TryGetComponent<MeshRenderer>(out var renderer))
                Object.DestroyImmediate(renderer);
            if (go.TryGetComponent<MeshFilter>(out var filter))
                Object.DestroyImmediate(filter);
        }

        private static void ConfigurePart(Build b, GameObject go, float mass, float wingArea, float dragArea, int airfoil, bool ownDamageRenderers)
        {
            var part = go.GetComponent(GameType("AeroPart"));
            var so = new SerializedObject(part);
            Prop(so, "parentUnit").objectReferenceValue = b.Aircraft;
            Prop(so, "mass").floatValue = mass;
            Prop(so, "wingArea").floatValue = wingArea;
            Prop(so, "dragArea").floatValue = dragArea;
            Prop(so, "airfoil").intValue = airfoil;
            Prop(so, "streamlining").floatValue = 0;
            Prop(so, "centerOfLift").vector3Value = Vector3.zero;
            Prop(so, "connectedAnchor").objectReferenceValue = null;
            Prop(so, "liftNormal").objectReferenceValue = null;
            Prop(so, "disintegrateObjects").arraySize = 0;
            if (ownDamageRenderers)
            {
                var renderers = Prop(so, "damageMaterial").FindPropertyRelative("renderers");
                var own = go.GetComponent<MeshRenderer>();
                renderers.arraySize = own != null ? 1 : 0;
                if (own != null)
                    renderers.GetArrayElementAtIndex(0).objectReferenceValue = own;
            }
            // The mass centre for UnitPart.ModifyMass (fuel, stores): the centre of the hulls' bounds, or the pivot.
            var com = go.transform.Find("CoM") ?? new GameObject("CoM") { layer = go.layer }.transform;
            com.SetParent(go.transform, false);
            var hulls = go.GetComponents<MeshCollider>();
            var hullBounds = hulls.Select(c => c.sharedMesh.bounds).DefaultIfEmpty().Aggregate((a, c) => { a.Encapsulate(c); return a; });
            com.position = hulls.Length > 0 ? go.transform.TransformPoint(hullBounds.center) : go.transform.position;
            Prop(so, "centerOfMass").objectReferenceValue = com;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void AddJoint(Build b, string name, string parent, IEnumerable<string> braces)
        {
            if (parent == null)
                return;
            b.Joints[name] = new[] { parent }.Concat(braces).ToList();
        }

        // The joints' solver iterations (AeroPart.CreateJoints sets each part's Rigidbody to them; PhysX runs a jointed island
        // at its bodies' highest). The part tree hangs heavy ends on light cut cores: fuselage_F (2.55 t) carries the nose,
        // cockpit and panels (13.3 t) on fuselage_F2 (2.95 t), where the 39-part tree's fuselage_F weighed as much as the
        // nose. The iterative solver's sag grows with that mass ratio: parked, fuselage_F sat 1.7 cm off fuselage_F2 at 12
        // iterations, 0.6 cm at 30 and 0.4 cm at 40 (PartStructureCheck, 1 cm tolerance; the anchors made no difference).
        private const int JointSolverIterations = 40;

        // Serialized PartJoints: the first to the parent part (AeroPart.Awake reads joints[0]), then braces.
        // Strength scales with the mass the joint carries, by the part's toughness (Toughness, CenturionAuthor.Damage.cs);
        // the game multiplies it by 10 on the simulating peer. Each joint is pinned where its two parts meet (JointAnchor):
        // a cut piece on its cut, a section on its section line, so a bending load is measured, and breaks it, there.
        private static void WriteJoints(Build b)
        {
            var aeroType = GameType("AeroPart");
            var breakSound = new SerializedObject(b.Donor("wing_root_L").GetComponent(aeroType)).FindProperty("joints");
            Object sound = null;
            if (breakSound.arraySize > 0)
                sound = breakSound.GetArrayElementAtIndex(0).FindPropertyRelative("breakSound").objectReferenceValue;
            Physics.SyncTransforms();
            foreach (var go in b.Parts.Values)
            {
                var part = go.GetComponent(aeroType);
                var so = new SerializedObject(part);
                var joints = Prop(so, "joints");
                var name = b.Parts.First(p => p.Value == go).Key;
                var list = b.Joints.TryGetValue(name, out var l) ? l : new List<string>();
                joints.arraySize = list.Count;
                var carried = go.GetComponentsInChildren(aeroType, true).Sum(p => new SerializedObject(p).FindProperty("mass").floatValue);
                for (var i = 0; i < list.Count; i++)
                {
                    var force = JointForce(name, carried);
                    var joint = joints.GetArrayElementAtIndex(i);
                    joint.FindPropertyRelative("connectedPart").objectReferenceValue = b.Part(list[i]);
                    joint.FindPropertyRelative("tensor").objectReferenceValue = null;
                    joint.FindPropertyRelative("solverIterations").intValue = JointSolverIterations;
                    joint.FindPropertyRelative("breakForce").floatValue = force;
                    joint.FindPropertyRelative("breakTorque").floatValue = force * 5f;
                    joint.FindPropertyRelative("anchor").objectReferenceValue = JointAnchor(go, b.Parts[list[i]]);
                    joint.FindPropertyRelative("breakSound").objectReferenceValue = sound;
                    joint.FindPropertyRelative("joint").objectReferenceValue = null;
                }
                so.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        // ---------- lift transforms and control surfaces ----------

        // Points where the mesh crosses the plane x = value, in prefab space.
        private static List<Vector3> SectionAtX(Mesh mesh, Vector3 offset, float x)
        {
            var points = new List<Vector3>();
            var v = mesh.vertices;
            var t = mesh.triangles;
            for (var i = 0; i < t.Length; i += 3)
                for (var e = 0; e < 3; e++)
                {
                    var a = v[t[i + e]] + offset;
                    var c = v[t[i + (e + 1) % 3]] + offset;
                    if ((a.x - x) * (c.x - x) > 0 || Mathf.Approximately(a.x, c.x))
                        continue;
                    points.Add(Vector3.Lerp(a, c, (x - a.x) / (c.x - a.x)));
                }
            return points;
        }

        // Leading and trailing edge at x: the section's most forward point, and the middle of its aft edge (a trailing
        // edge, or the flat face where a control surface's cut-out ends the section). edge is that aft edge's height.
        private static (Vector3 le, Vector3 te, float edge) Section(Build b, string part, float x)
        {
            var points = ShapeGroup(part).SelectMany(p => SectionAtX(b.Meshes[p].Shape, b.Parts[p].transform.position, x)).ToList();
            if (points.Count < 2)
                throw new InvalidDataException($"{part} has no section at x = {x}");
            var aftZ = points.Min(p => p.z);
            var aft = points.Where(p => p.z < aftZ + 0.05f).OrderBy(p => p.y).ToList();
            // A lone aft point (each triangle finds its edge crossings, so it shows up twice): the skins end at different
            // chord stations, as when a canted surface is sliced beside a cut-out's end.
            var edge = aft.Last().y - aft.First().y < 0.001f ? float.PositiveInfinity : aft.Last().y - aft.First().y;
            return (points.OrderByDescending(p => p.z).First(), (aft.First() + aft.Last()) / 2, edge);
        }

        private static (Vector3 le, Vector3 te) Chord(Build b, string part, float x)
        {
            var (le, te, _) = Section(b, part, x);
            return (le, te);
        }

        // A section through a control surface's cut-out ends at the cut face, partway along the chord, so a chord line
        // drawn to it doesn't run at the surface's incidence (the top of a flap cut-out is 3.9° off). The lift frame takes
        // its chord from the station nearest x whose aft edge is a trailing edge: under 3% of the chord thick.
        private static Vector3 TrailingEdgeChord(Build b, string part, float x)
        {
            var bounds = GroupShapeBounds(b, part);
            for (var d = 0f; d < bounds.size.x; d += 0.25f)
                foreach (var probe in new[] { x - d, x + d })
                {
                    if (probe < bounds.min.x + 0.05f || probe > bounds.max.x - 0.05f)
                        continue;
                    var (le, te, edge) = Section(b, part, probe);
                    if (edge < 0.03f * Vector3.Distance(le, te))
                        return le - te;
                }
            throw new InvalidDataException($"{part} has no section ending in a trailing edge");
        }

        // Streamwise lift frame: Z along the chord (leading edge ahead), Y the surface normal. The game reads
        // alpha in this frame, so a swept or canted surface must not tilt Z out of the streamwise chord.
        private static Quaternion LiftFrame(Vector3 span, Vector3 chord)
        {
            var normal = Vector3.Cross(chord, span).normalized;
            if (normal.y < 0)
                normal = -normal;
            return Quaternion.LookRotation(chord.z < 0 ? -chord : chord, normal);
        }

        // The lift frame turned about its span axis by `extra` degrees nose up, or until its incidence (the chord's pitch) is
        // `incidence`. A canted surface's chord pitches by the cosine of its cant, so the turn is divided by it
        // (tools/fm centurion_span.py _with_incidence).
        private static Quaternion Rigged(Quaternion frame, float? incidence, float extra)
        {
            var rig = Mathf.Atan2((frame * Vector3.forward).y, (frame * Vector3.forward).z) * Mathf.Rad2Deg;
            return frame * Quaternion.Euler(-(incidence.HasValue ? (incidence.Value - rig) / (frame * Vector3.up).y : extra), 0, 0);
        }

        // Hinge frame: X along the hinge line (ControlSurface turns its visibleMesh about local X), Y the normal.
        private static Quaternion HingeFrame(Vector3 hinge, Vector3 chord)
        {
            var normal = Vector3.Cross(chord, hinge).normalized;
            if (normal.y < 0)
                normal = -normal;
            var forward = Vector3.Cross(hinge, normal).normalized;
            return Quaternion.LookRotation(forward.z < 0 ? -forward : forward, normal);
        }

        private static void SetLiftNormal(Build b, PartSpec spec, GameObject go)
        {
            var lift = go.transform.Find(spec.Name + "_liftNormal") ?? new GameObject(spec.Name + "_liftNormal") { layer = go.layer }.transform;
            lift.SetParent(go.transform, false);
            var mesh = b.Meshes.TryGetValue(spec.Name, out var m) ? m.Shape : null;
            if (spec.Lift == Lift.Wing && mesh != null)
            {
                // Area centroid of the upper skin, then the quarter chord of the section through it; a cut part's pieces
                // all take the whole's (ShapeGroup).
                var centroid = UpperSkinCentroid(b, spec.Name);
                var (le, te) = Chord(b, spec.Name, centroid.x);
                var (le2, _) = Chord(b, spec.Name, centroid.x + (centroid.x < 0 ? 0.5f : -0.5f));
                var quarter = Vector3.Lerp(le, te, 0.25f);
                lift.position = new Vector3(quarter.x, (le.y + te.y) / 2, quarter.z);
                lift.rotation = Rigged(LiftFrame(le2 - le, TrailingEdgeChord(b, spec.Name, centroid.x)), spec.Incidence, spec.ExtraIncidence);
            }
            else
            {
                lift.position = mesh != null ? go.transform.TransformPoint(mesh.bounds.center) : go.transform.position;
                lift.rotation = Quaternion.Euler(-spec.ExtraIncidence, 0, 0);
            }
            Set(go.GetComponent(GameType("AeroPart")), "liftNormal", lift);
            // The aero job adds Cross(force, -liftRotation x centerOfLift) as torque (AeroJob_Math.cs:126-131), which moves the
            // part's force LiftAft metres aft along the fuselage while its weight stays at its hull.
            var centerOfLift = Quaternion.Inverse(lift.rotation) * new Vector3(0, 0, -spec.LiftAft);
            Set(go.GetComponent(GameType("AeroPart")), "centerOfLift", centerOfLift);
            var pitch = -Mathf.Asin(Vector3.Dot(lift.forward, Vector3.up)) * Mathf.Rad2Deg;
            if (spec.WingArea > 0 || spec.LiftAft != 0)
                b.Report.Add($"lift {spec.Name}: {spec.WingArea} m2 at {lift.position} (incidence {-pitch:F2} deg, normal {lift.up}, centerOfLift {centerOfLift.x:F3}, {centerOfLift.y:F3}, {centerOfLift.z:F3})");
        }

        // In prefab space, over the part's shape group.
        private static Vector3 UpperSkinCentroid(Build b, string part)
        {
            var sum = Vector3.zero;
            var area = 0f;
            foreach (var piece in ShapeGroup(part))
            {
                var mesh = b.Meshes[piece].Shape;
                var offset = b.Parts[piece].transform.position;
                var v = mesh.vertices;
                var t = mesh.triangles;
                for (var i = 0; i < t.Length; i += 3)
                {
                    var cross = Vector3.Cross(v[t[i + 1]] - v[t[i]], v[t[i + 2]] - v[t[i]]);
                    var normal = cross.normalized;
                    if (normal.y < 0.3f)
                        continue;
                    var a = cross.magnitude / 2;
                    sum += a * ((v[t[i]] + v[t[i + 1]] + v[t[i + 2]]) / 3 + offset);
                    area += a;
                }
            }
            return area > 0 ? sum / area : GroupShapeBounds(b, part).center;
        }

        // The pieces whose shapes together make up part's whole (CutParts), part among them; part alone if it wasn't cut.
        private static string[] ShapeGroup(string part) => CutParts.FirstOrDefault(g => g.Contains(part)) ?? new[] { part };

        // The shape group's bounds in prefab space.
        private static Bounds GroupShapeBounds(Build b, string part)
        {
            var pieces = ShapeGroup(part).Select(n =>
            {
                var bounds = b.Meshes[n].Shape.bounds;
                bounds.center += b.Parts[n].transform.position;
                return bounds;
            });
            return pieces.Aggregate((a, c) => { a.Encapsulate(c); return a; });
        }

        // Shares each cut part's area and drag between its two pieces (CutParts) so that their lift, each at its own centre
        // of mass (complex physics gives every part a Rigidbody, AeroPart.ApplyJobFields), adds up to the whole's: the
        // shares that keep the whole's moment along the cut's axis (along the span for a wing or V-tail, the body for a
        // section), and for a wing piece a centerOfLift that puts its lift at the whole's lift station.
        private static void SplitLift(Build b)
        {
            foreach (var group in CutParts)
            {
                var whole = Parts.Single(p => p.Name == group[0]);
                if (whole.WingArea == 0 && whole.DragArea == 0)
                    continue;
                var coms = group.Select(n => ((Transform)Prop(new SerializedObject(b.Part(n)), "centerOfMass").objectReferenceValue).position).ToArray();
                var union = group.SelectMany(n => b.Parts[n].GetComponents<MeshCollider>().Select(c =>
                {
                    var bounds = c.sharedMesh.bounds; // parts are axis-aligned at unit scale (BuildParts)
                    bounds.center = c.transform.TransformPoint(bounds.center);
                    return bounds;
                })).Aggregate((a, c) => { a.Encapsulate(c); return a; });
                var spanwise = whole.Lift == Lift.Wing;
                float Along(Vector3 p) => spanwise ? Mathf.Abs(p.x) : p.z;
                // a0 + a1 = A and a0 x0 + a1 x1 = A x, x the whole's centre (its hulls' bounds, as ConfigurePart takes it)
                var share = (Along(union.center) - Along(coms[0])) / (Along(coms[1]) - Along(coms[0]));
                if (share <= 0 || share >= 1)
                    throw new InvalidDataException($"{string.Join(", ", group)}: no area split keeps {whole.Name}'s moment (piece share {share:F3})");
                var shares = new[] { 1 - share, share };
                // The whole's lift station: its centre, LiftAft metres aft (prefab -z)
                var station = union.center.z - whole.LiftAft;
                for (var i = 0; i < group.Length; i++)
                {
                    var part = b.Part(group[i]);
                    Set(part, "wingArea", whole.WingArea * shares[i]);
                    Set(part, "dragArea", whole.DragArea * shares[i]);
                    var aft = spanwise ? coms[i].z - station : 0f;
                    var lift = (Transform)Prop(new SerializedObject(part), "liftNormal").objectReferenceValue;
                    Set(part, "centerOfLift", Quaternion.Inverse(lift.rotation) * new Vector3(0, 0, -aft));
                    b.Report.Add($"lift split {whole.Name}: {group[i]} {whole.WingArea * shares[i]:F3} m2, drag {whole.DragArea * shares[i]:F3}, centre of mass {coms[i]}, lift {aft:F3} m aft of it");
                }
            }
        }

        private sealed class SignCalibration
        {
            public float Pitch, Roll, Yaw;
            public Component Template; // the Alkyon aileron's ControlSurface, copied out before the strip
        }

        // Change in the game's lift force (AeroJob_Math.Execute, odd lift curve, unit airflow from ahead) when a
        // surface's lift transform turns +1 degree about its hinge (ControlSurface rotates visibleMesh about local X).
        private static Vector3 DeflectionForce(Quaternion lift, Vector3 hingeAxis)
        {
            Vector3 Force(Quaternion r)
            {
                var v = Vector3.forward;
                var local = Quaternion.Inverse(r) * v;
                var n = Vector3.Cross(v, r * Vector3.right).normalized;
                return -n * Mathf.Atan2(local.y, local.z);
            }
            return Force(Quaternion.AngleAxis(1f, hingeAxis) * lift) - Force(lift);
        }

        // Reads which way a positive range moves the aircraft from the Alkyon's own surfaces, so the Centurion's
        // ranges get the same sense whatever the hinge orientation.
        private static SignCalibration CalibrateSurfaceSigns(Build b)
        {
            var cg = b.Donor("CoM").position;
            float Sense(string path, string range, int axis)
            {
                var surface = b.Donor(path).GetComponent(GameType("ControlSurface"));
                var so = new SerializedObject(surface);
                var visible = ((GameObject)Prop(so, "visibleMesh").objectReferenceValue).transform;
                var part = Prop(so, "attachedSurface").objectReferenceValue;
                var lift = (Transform)new SerializedObject(part).FindProperty("liftNormal").objectReferenceValue ?? ((Component)part).transform;
                if (!lift.IsChildOf(visible))
                    throw new InvalidDataException(path + ": the lift transform doesn't turn with the surface; can't calibrate.");
                var torque = Vector3.Cross(lift.position - cg, DeflectionForce(lift.rotation, visible.rotation * Vector3.right));
                return Mathf.Sign(Prop(so, range).floatValue * torque[axis]);
            }
            var c = new SignCalibration
            {
                Pitch = Sense("wingroot_L/engines_L/nozzles_L/elevator_L", "pitchRange", 0),
                Roll = Sense("wingroot_L/wing1_L/wing2_L/aileron_L", "rollRange", 2),
                Yaw = Sense("wingroot_L/engines_L/rudder_L", "yawRange", 1),
            };
            if (c.Pitch != Sense("wingroot_R/engines_R/nozzles_R/elevator_R", "pitchRange", 0) || c.Roll != Sense("wingroot_R/wing1_R/wing2_R/aileron_R", "rollRange", 2)
                || c.Yaw != Sense("wingroot_R/engines_R/rudder_R", "yawRange", 1))
                throw new InvalidDataException("The Alkyon's left and right surfaces disagree on control sense.");
            var surfaceType = GameType("ControlSurface");
            c.Template = new GameObject("surface_template").AddComponent(surfaceType);
            EditorUtility.CopySerialized(b.Donor("wingroot_L/wing1_L/wing2_L/aileron_L").GetComponent(surfaceType), c.Template);
            b.Report.Add($"control sense from the Alkyon: pitch {c.Pitch:+0;-0}, roll {c.Roll:+0;-0}, yaw {c.Yaw:+0;-0} (torque sign about X, Z, Y per +1 input)");
            return c;
        }

        private static void BuildSurfaces(Build b, SignCalibration sense)
        {
            var aeroType = GameType("AeroPart");
            var surfaceType = GameType("ControlSurface");
            var cg = CenterOfMass(b);
            foreach (var spec in Surfaces)
            {
                var host = b.Parts[spec.Host];
                var side = host.transform.position.x + b.Meshes[spec.Host].Shape.bounds.center.x < 0 ? -1f : 1f;
                var visibleName = spec.Name + "_visible";
                var authored = b.Blockout.Has(spec.Name) && !b.Blockout.HasMesh(spec.Name) && b.Blockout.HasMesh(visibleName);
                var spanIn = spec.SpanIn;
                var spanOut = spec.SpanOut;
                if (authored)
                {
                    var xs = Corners(b.Meshes[visibleName].Shape.bounds).Select(c => Mathf.Abs((b.Blockout.Rotation(visibleName) * c + b.Blockout.Local(visibleName)).x)).ToArray();
                    // Sections come from the host, so stay inside its span.
                    var hostXs = Corners(GroupShapeBounds(b, spec.Host)).Select(c => Mathf.Abs(c.x)).ToArray();
                    spanIn = Mathf.Max(xs.Min(), hostXs.Min()) + 0.1f;
                    spanOut = Mathf.Min(xs.Max(), hostXs.Max()) - 0.1f;
                }
                var (leIn, teIn) = Chord(b, spec.Host, side * spanIn);
                var (leOut, teOut) = Chord(b, spec.Host, side * spanOut);
                var hingeIn = Vector3.Lerp(teIn, leIn, spec.ChordFraction);
                var hingeOut = Vector3.Lerp(teOut, leOut, spec.ChordFraction);
                var chord = TrailingEdgeChord(b, spec.Host, side * (spanIn + spanOut) / 2);
                var hingeAxis = authored ? b.Blockout.Rotation(spec.Name) * Vector3.right : hingeOut - hingeIn;
                var hingePoint = authored ? b.Blockout.Local(spec.Name) : (hingeIn + hingeOut) / 2;

                // Part at its pivot (identity rotation, so a blockout hull fits), hinge on the hinge line with
                // local X along it; under the hinge, the streamwise lift transform and the visible mesh.
                var go = new GameObject(spec.Name) { layer = b.Root.layer };
                go.transform.SetParent(host.transform, false);
                go.transform.SetPositionAndRotation(hingePoint, Quaternion.identity);
                var hinge = new GameObject(spec.Name + "_hinge") { layer = go.layer }.transform;
                hinge.SetParent(go.transform, false);
                hinge.SetPositionAndRotation(hingePoint, HingeFrame(hingeAxis, chord));
                var lift = new GameObject(spec.Name + "_liftNormal") { layer = go.layer }.transform;
                lift.SetParent(hinge, false);
                lift.SetPositionAndRotation(hingePoint, Rigged(LiftFrame(hingeAxis, chord), spec.Incidence, spec.ExtraIncidence));
                var visible = new GameObject(visibleName) { layer = go.layer };
                visible.transform.SetParent(hinge, false);
                if (authored)
                {
                    visible.transform.SetPositionAndRotation(b.Blockout.Local(visibleName), b.Blockout.Rotation(visibleName));
                    visible.AddComponent<MeshFilter>().sharedMesh = b.Meshes[visibleName].Render;
                    b.Visuals[visibleName] = visible.transform;
                }
                else
                {
                    visible.transform.SetPositionAndRotation(hingePoint, Quaternion.identity);
                    visible.AddComponent<MeshFilter>().sharedMesh = SaveMesh(Slab(spec.Name + "_slab", new[] { hingeIn, hingeOut, teOut, teIn }.Select(p => p - hingePoint).ToArray(), hinge.up, 0.08f));
                }
                visible.AddComponent<MeshRenderer>().sharedMaterials = authored ? b.MaterialsFor(visibleName) : new[] { b.Skin };
                // Split halves at the hinge's pose, as the Darkreach's aileron_R_upper_visible and _lower_visible sit under its
                // surface; the job turns them +-splitAmount about the hinge line from their rest rotation.
                Transform upper = null, lower = null;
                MeshRenderer lowerHalf = null;
                if (spec.Split != SplitKind.None)
                {
                    upper = new GameObject(spec.Name + "_split_upper") { layer = go.layer }.transform;
                    upper.SetParent(hinge, false);
                    lower = new GameObject(spec.Name + "_split_lower") { layer = go.layer }.transform;
                    lower.SetParent(hinge, false);
                    visible.transform.SetParent(upper, true);
                    if (spec.Split == SplitKind.Clamshell)
                    {
                        var half = Object.Instantiate(visible, lower, true);
                        half.name = visibleName + "_lower";
                        lowerHalf = half.GetComponent<MeshRenderer>();
                    }
                }
                // The hull of the mesh at rest, on the part's own GameObject as stock surfaces have it: the game sizes a
                // part from that collider, and without one drops its aero force (PartStructureCheck).
                // The hull is the surface's shape (the blockout's), so a detailed surface collides as the blockout's did.
                var rest = authored ? b.Meshes[visibleName].Shape : visible.GetComponent<MeshFilter>().sharedMesh;
                var toPart = go.transform.worldToLocalMatrix * visible.transform.localToWorldMatrix;
                var hullMesh = new Mesh { name = spec.Name + "_hull", vertices = rest.vertices.Select(v => toPart.MultiplyPoint3x4(v)).ToArray(), triangles = rest.triangles };
                hullMesh.RecalculateBounds();
                var hullCollider = go.AddComponent<MeshCollider>();
                hullCollider.sharedMesh = SaveMesh(hullMesh);
                hullCollider.convex = true;

                EditorUtility.CopySerialized(b.Part(spec.Host), go.AddComponent(aeroType));
                ConfigurePart(b, go, b.Blockout.Mass(spec.Name), spec.Area, 0, spec.Airfoil, false);
                var part = new SerializedObject(go.GetComponent(aeroType));
                var renderers = Prop(part, "damageMaterial").FindPropertyRelative("renderers");
                renderers.arraySize = lowerHalf != null ? 2 : 1;
                renderers.GetArrayElementAtIndex(0).objectReferenceValue = visible.GetComponent<MeshRenderer>();
                if (lowerHalf != null)
                    renderers.GetArrayElementAtIndex(1).objectReferenceValue = lowerHalf;
                Prop(part, "liftNormal").objectReferenceValue = lift;
                part.ApplyModifiedPropertiesWithoutUndo();
                b.Parts[spec.Name] = go;
                AddJoint(b, spec.Name, spec.Host, Array.Empty<string>());

                var force = DeflectionForce(lift.rotation, hinge.right);
                var torque = Vector3.Cross(lift.position - cg, force);
                // The upper half turns +splitAmount, so +1 degree about the hinge must lift the trailing edge (cut lift).
                if (spec.Split != SplitKind.None && Vector3.Dot(force, lift.up) >= 0)
                    throw new InvalidDataException(spec.Name + ": the upper split half would open downward.");
                float pitch = 0, roll = 0, yaw = 0;
                var flap = spec.Kind == SurfaceKind.Flap;
                if (flap)
                {
                    // A deployed flap sits at -pitchRange (ControlSurfaceJob_Math), so +1 degree must cut lift.
                    if (Vector3.Dot(force, lift.up) >= 0)
                        throw new InvalidDataException(spec.Name + ": a negative deflection would lower the flap's lift.");
                    pitch = spec.RangeA;
                }
                else if (spec.Kind == SurfaceKind.Roll)
                {
                    roll = sense.Roll * Mathf.Sign(torque.z) * spec.RangeA;
                }
                else
                {
                    pitch = sense.Pitch * Mathf.Sign(torque.x) * spec.RangeA;
                    yaw = sense.Yaw * Mathf.Sign(torque.y) * spec.RangeB;
                }
                var surface = go.AddComponent(surfaceType);
                EditorUtility.CopySerialized(sense.Template, surface);
                var so = new SerializedObject(surface);
                Prop(so, "pitchRange").floatValue = pitch;
                Prop(so, "rollRange").floatValue = roll;
                Prop(so, "yawRange").floatValue = yaw;
                Prop(so, "brakeRange").floatValue = 0;
                Prop(so, "attachedSurface").objectReferenceValue = go.GetComponent(aeroType);
                Prop(so, "visibleMesh").objectReferenceValue = hinge.gameObject;
                Prop(so, "flap").boolValue = flap;
                Prop(so, "servoSpeed").floatValue = spec.ServoSpeed;
                Prop(so, "splitDrag").floatValue = spec.SplitDrag;
                Prop(so, "maxSplit").floatValue = spec.MaxSplit;
                Prop(so, "yawSplitFactor").floatValue = 0;
                Prop(so, "splitUpper").objectReferenceValue = upper;
                Prop(so, "splitLower").objectReferenceValue = lower;
                Prop(so, "splitSound").objectReferenceValue = null;
                so.ApplyModifiedPropertiesWithoutUndo();
                b.Report.Add($"surface {spec.Name}: {spec.Area} m2, pitch {pitch}, roll {roll}, yaw {yaw}, flap {flap}, split {spec.Split} to {spec.MaxSplit} at {spec.SplitDrag}, hinge at {hingePoint} along {hinge.right}, |x| {spanIn:F1} to {spanOut:F1}{(authored ? ", blockout hinge and mesh" : ", slab mesh")}");
            }
        }

        // The fly-by-wire pitch channel (ControlsFilter.FlyByWire.Filter) for this bomber; the rest stays the Alkyon's.
        // The pitch-rate target is gLimitPositive x 9.81 / speed. At 3.5 the wing, not the fly-by-wire, is the limit: a full
        // aft stick extended at mid weight peaks at 4.2 g from 230 m/s at 6 km, past the 4 g tear, but at 3.1 g at 9 km and
        // 230 m/s and 2.9 g at 180 m/s, where the alpha limiter and the speed it bleeds stop it first.
        // Below cornerSpeed the target shrinks by (speed / cornerSpeed)^2, at least 0.3, which
        // sets how fast the nose comes up on the runway: at the Alkyon's 200 a light takeoff needs 2,350 m, past Agrapol's
        // 2,310. alphaLimiter backs the target off from 5° of body alpha: with alphaLimiterStrength 0.25 it holds the 199 t
        // takeoff AI at 9.1° (rotating at 97 m/s, aiming for 9.5°), under step 6's 10.49° tail strike, so the retracted roll
        // never lifts off the longest runway (G2.6); at 7° the retracted roll reaches 11.1° and strikes the tail. Numbers from
        // tools/fm/centurion_span.py.
        private static void TuneFlyByWire(Build b)
        {
            const float gLimitPositive = 3.5f;
            var filter = new SerializedObject(new SerializedObject(b.Aircraft).FindProperty("controlsFilter").objectReferenceValue);
            Num(filter, "flyByWire.gLimitPositive", gLimitPositive);
            Num(filter, "flyByWire.cornerSpeed", 150f);
            Num(filter, "flyByWire.alphaLimiter", 5f);
            Num(filter, "flyByWire.alphaLimiterStrength", 0.25f);
            // The yaw channel: rudder = yawTightness x (yaw input as a rate in rad/s - yaw rate) + 0.05 x sideslip in degrees
            // (ControlsFilter.cs:280-286), not rescaled below cornerSpeed. At 55,000 ft the aerodynamic yaw damping (as rho v) is
            // a quarter of the circuit's, and with the donor's 3 an autopilot's heading loop (AutoAim's yaw P 0.05 a degree)
            // swung the rudder stop to stop after a yaw doublet: sideslip to 25 deg, 1,250 m lost (run 20261016-203625). At 1.5
            // the replica settles inside 5 deg of sideslip 9 to 11 s after the same doublet at 55,000 to 57,000 ft and loses 99 to
            // 151 m, against 20 to 25 s and 580 to 700 m at 3 (tools/fm/yaw_doublet.py). A full pedal still pins the rudder
            // below 19 deg/s of yaw rate, so one engine out holds as before.
            Num(filter, "flyByWire.yawTightness", 1.5f);
            filter.ApplyModifiedPropertiesWithoutUndo();

            // The autopilot's pitch PID (every AI state and the framework's hold fly through AutopilotPlane.AutoAim) turns an
            // angle error into a stick input, which the fly-by-wire above scales by gLimitPositive (ControlsFilter.cs:241), so
            // the loop's gain is the PID times gLimitPositive. (0.07, 0.005, 0.01) at 2 g fixed the hold's limit cycle (19 s,
            // +-55 m at 9 km and 236 m/s in game with the Alkyon's integral) without over-rotating the takeoff AI; scaled by
            // 2 / gLimitPositive the loop is unchanged. Left at (0.07, 0.005, 0.01) with 3.5 g, the 199 t retracted takeoff
            // over-rotates into a tail strike (G2.6) in tools/fm/centurion_span.py.
            var autopilot = new SerializedObject(b.Root.GetComponentsInChildren(GameType("AutopilotPlane"), true).Single());
            Prop(autopilot, "forwardFlightController.pitchFlightPID.PID").vector3Value = new Vector3(0.07f, 0.005f, 0.01f) * (2f / gLimitPositive);
            autopilot.ApplyModifiedPropertiesWithoutUndo();
        }

        // ---------- systems: cockpit, radar, cameras, engines, gear, bays ----------

        // The flare dispensers are cartridge plates a side in two places (owner: "not side by side, in different
        // locations"): art/blender/m4/nose.py FLARES on fuselage_F's lower sides below the cheeks (stations 9.95 to 10.85,
        // 121 to 135 deg from the crown), and fuselage_aft.py FLARES on fuselage_R above the sponsons' tails (32.0 to
        // 32.9, 80 to 94 deg). Each point sits 5 cm off its plate's centre (FlarePlates: blockout station, x out and height)
        // on a MainBox core: the forward plate is fuselage_F's own skin; the aft plate's skin is the fuselage_R_upper
        // panel's, its points stay on fuselage_R, so a lost panel leaves them throwing from the hole. Owner,
        // 2026-10-19: "up the flares to 400 and add 2 more dispensers so they deploy 4 at a time": a release
        // (FlareEjector.Fire) ejects ejectionGrouping flares from successive points, so with four points and a grouping of
        // four each release throws one from every plate (FlareEjector.cs:110-137). The Alkyon's two points came along
        // under the sponsons at station 27, inside the main gear bays, so the flares appeared under the aircraft.
        // FlareEjector.EjectFlare spawns each flare at its point and throws it along the point's +Z at 15 to 35 m/s plus
        // its part's velocity; from both plates that line clears every collider at both spans.
        private static readonly (string Part, float Station, float Out, float Height, string Suffix)[] FlarePlates =
            { ("fuselage_F", 10.4f, 2.118f, 2.146f, "_fwd"), ("fuselage_R", 32.45f, 2.80f, 4.233f, "") };
        private const int FlareRounds = 400;
        private static readonly Vector3 FlareThrow = new Vector3(0.8f, -0.55f, -0.25f); // outboard (+X side), down, aft

        private static void PlaceFlareEjectors(Build b)
        {
            var ejector = b.Root.GetComponent(GameType("FlareEjector"));
            var so = new SerializedObject(ejector);
            var points = so.FindProperty("ejectionPoints");
            if (points.arraySize != 2)
                throw new InvalidDataException($"the donor's FlareEjector has {points.arraySize} ejection points, not one a side");
            var donor = Enumerable.Range(0, 2).Select(i => (Transform)points.GetArrayElementAtIndex(i).FindPropertyRelative("transform").objectReferenceValue).ToArray();
            points.arraySize = FlarePlates.Length * donor.Length;
            var k = 0;
            foreach (var plate in FlarePlates)
                foreach (var source in donor)
                {
                    // The aft plate keeps the donor's points; the forward plate takes a copy of each.
                    var hull = b.Parts[plate.Part];
                    var t = plate.Suffix == "" ? source : Object.Instantiate(source.gameObject, hull.transform, true).transform;
                    t.name = source.name + plate.Suffix;
                    var side = source.name.EndsWith("_L", StringComparison.Ordinal) ? -1f : 1f; // the left wing is -X in the prefab
                    t.SetParent(hull.transform, true);
                    t.SetPositionAndRotation(
                        new Vector3(side * plate.Out, plate.Height - b.Blockout.Origin.y, OriginStation - plate.Station - b.Blockout.Origin.z),
                        Quaternion.LookRotation(Vector3.Scale(FlareThrow, new Vector3(side, 1f, 1f)), Vector3.up));
                    var point = points.GetArrayElementAtIndex(k++);
                    point.FindPropertyRelative("transform").objectReferenceValue = t;
                    point.FindPropertyRelative("part").objectReferenceValue = hull.GetComponent(GameType("AeroPart"));
                    b.Report.Add($"flares: {t.name} on {plate.Part} at {t.position}, throwing along {t.forward}");
                }
            Prop(so, "ejectionGrouping").intValue = points.arraySize;
            Prop(so, "ammo").intValue = FlareRounds;
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"flares: {FlareRounds} rounds, {points.arraySize} points, {points.arraySize} a release every {Prop(so, "ejectionInterval").floatValue} s");
        }

        // The transonic vapour cone, VaporEffect's local-space emitter, which VaporEmitter.Emit turns into the airflow and
        // plays past an angle of attack that falls from 30 degrees 40 m/s under the speed of sound to 0 at it. It came at
        // the Alkyon's spot (its fuselage_F joint, inside the Centurion's fuselage_M) and size, a cone of radius 1 m for the
        // Alkyon's body of 1.23 m half-height (its fuselage_F mesh). It moves 40% back on the inner wing's root chord
        // (stations 14.69 to 24.44), where the body and the thickest part of the wing root meet, onto the body section's
        // centre there, and scales with that section's half-height.
        private const float VaporConeStation = 18.6f, AlkyonBodyHalfHeight = 1.23f;

        private static void PlaceVaporCone(Build b)
        {
            var cone = b.Root.transform.Find("vaporCone");
            // The scale reaches the shape, the particle size and the speed only in the Local scaling mode.
            if (cone.GetComponent<ParticleSystem>().main.scalingMode != ParticleSystemScalingMode.Local)
                throw new InvalidDataException("vaporCone's particle system no longer scales by its own transform");
            var z = OriginStation - VaporConeStation - b.Blockout.Origin.z;
            var section = SectionAlongZ(b.Meshes["fuselage_M"].Shape, b.Parts["fuselage_M"].transform.position, z);
            var top = section.Max(p => p.y);
            var bottom = section.Min(p => p.y);
            cone.position = new Vector3(0, (top + bottom) / 2, z);
            cone.localScale = Vector3.one * ((top - bottom) / 2 / AlkyonBodyHalfHeight);
            b.Report.Add($"vapour cone at {cone.position}, scale {cone.localScale.x:F2}");
        }

        private static void PlaceSystems(Build b)
        {
            // The flight deck is BuildFlightDeck's. In cockpit view the camera turns exteriorRenderers off
            // (CameraCockpitState.cs:68, Aircraft.SetCockpitRenderers): the nose skin and the radar fairing hide, the world
            // shows through the interior's panes and its screen under them (docs/COCKPIT-DESIGN.md "Forward view").
            var nose = b.Parts["nose"];
            var noseBounds = ShapeBounds(b, "nose");
            var aircraft = new SerializedObject(b.Aircraft);
            var exterior = Prop(aircraft, "exteriorRenderers");
            foreach (var part in new[] { "nose", "radar_F_fairing" })
            {
                exterior.arraySize++;
                exterior.GetArrayElementAtIndex(exterior.arraySize - 1).objectReferenceValue = b.Parts[part].GetComponent<MeshRenderer>();
            }
            aircraft.ApplyModifiedPropertiesWithoutUndo();

            // Radar under the nose cone; target cameras at both ends.
            var radar = b.Parts["radar_F_fairing"].transform;
            var tip = noseBounds.max.z;
            if (!b.Blockout.Has("radar_F_fairing"))
                radar.position = new Vector3(0, nose.transform.position.y, tip - 1.2f);
            var targetCamF = radar.Find("targetCamPoint_F");
            // TargetCam uses a 2 m near plane and an unrestricted look rotation. Keep the ground-looking mounts low
            // and beyond the render hulls, including the radome and fixed laser dome that Shape omits.
            const float targetCamClearance = 2.5f;
            var chinHeight = 0.5f - b.Blockout.Origin.y;
            targetCamF.position = new Vector3(0, chinHeight, radar.position.z + b.Meshes["radar_F_fairing"].Render.bounds.max.z + targetCamClearance);
            var tail = b.Parts["tailcone"].transform;
            var domeEnd = b.Blockout.Local("laser_turret").z + b.Meshes["laser_turret"].Render.bounds.min.z;
            tail.Find("targetCamPoint_R").position = new Vector3(0, chinHeight, domeEnd - targetCamClearance);
            // The landing camera (the game's Landing Camera setting, TargetCam.camMountLanding) kept the Alkyon's spot on
            // the tail, which on this tail cone is inside the aft bay (station 31.4). Station 36.0, 1.90 m up, sits under the
            // belly 3.4 m behind the bay, where the stock bombers carry it, with all twelve main wheels in its view.
            tail.Find("landingCam").localPosition = new Vector3(0f, -2.05f, -3f);

            // Nav lights and vortex emitters at the raked tips, on the wingtip pieces: stage 2's vertices (with its tip's)
            // outboard of the inner wing's end.
            foreach (var side in new[] { "L", "R" })
            {
                var stage = b.Parts["wing_tip_" + side].transform;
                var inner = GroupShapeBounds(b, "wing_root_" + side);
                var rootEnd = Mathf.Max(Mathf.Abs(inner.min.x), Mathf.Abs(inner.max.x));
                var tipVerts = ShapeGroup("wing_tele2_" + side).SelectMany(n => b.Meshes[n].Shape.vertices.Select(b.Parts[n].transform.TransformPoint))
                    .Where(v => Mathf.Abs(v.x) > rootEnd).ToArray();
                var tb = new Bounds(tipVerts[0], Vector3.zero);
                foreach (var v in tipVerts)
                    tb.Encapsulate(v);
                var outer = side == "L" ? tb.min.x : tb.max.x;
                var nav = b.Root.transform.Find("navlight_" + side);
                nav.SetParent(stage, true);
                nav.position = new Vector3(outer, tb.center.y, tb.center.z);
                // The wingtip or a part it hangs from tearing off fires the tip's onParentDetached (UnitPart.Detach and
                // UnitPart_OnParentDetached), which puts the light out (NavLights.NavLight_OnDetachedFromUnit).
                var navLights = new SerializedObject(b.Root.GetComponent(GameType("NavLights")));
                NavLightEntry(navLights, nav.GetComponent<Renderer>()).FindPropertyRelative("part").objectReferenceValue = b.Part(stage.name);
                navLights.ApplyModifiedPropertiesWithoutUndo();
                var vortex = b.Root.transform.Find("wingtipvortex_" + side);
                vortex.SetParent(stage, true);
                vortex.position = new Vector3(outer, tb.center.y, tb.min.z);
            }
        }

        private static List<Vector3> SectionAlongZ(Mesh mesh, Vector3 offset, float z)
        {
            var swapped = new List<Vector3>();
            var v = mesh.vertices;
            var t = mesh.triangles;
            for (var i = 0; i < t.Length; i += 3)
                for (var e = 0; e < 3; e++)
                {
                    var a = v[t[i + e]] + offset;
                    var c = v[t[i + (e + 1) % 3]] + offset;
                    if ((a.z - z) * (c.z - z) > 0 || Mathf.Approximately(a.z, c.z))
                        continue;
                    swapped.Add(Vector3.Lerp(a, c, (z - a.z) / (c.z - a.z)));
                }
            if (swapped.Count == 0)
                throw new InvalidDataException("The nose mesh has no section at z = " + z);
            return swapped;
        }

        // Unchanged to 10 km, then set by the two ceiling points (G2.12): the retracted aircraft runs out of thrust at 13.2 km,
        // the extended one holds 17.5 km at spool 0.86 (docs/M2-DESIGN.md, step 6).
        private static readonly AnimationCurve AltitudeThrust = Smooth(new Keyframe(0, 1), new Keyframe(10000, 1), new Keyframe(13500, 0.42f), new Keyframe(17500, 0.306f), new Keyframe(18500, 0.276f));
        private static readonly AnimationCurve SpeedThrust = LinearCurve(new List<Vector2> { new Vector2(0, 1), new Vector2(200, 1.25f), new Vector2(250, 1.15f), new Vector2(290, 0.6f), new Vector2(310, 0) }, odd: false);

        private static AnimationCurve Smooth(params Keyframe[] keys)
        {
            var curve = new AnimationCurve(keys);
            for (var i = 0; i < keys.Length; i++)
                AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
            for (var i = 0; i < keys.Length; i++)
                AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
            curve.preWrapMode = WrapMode.ClampForever;
            curve.postWrapMode = WrapMode.ClampForever;
            return curve;
        }

        // Alkyon engine K and nozzle K go to nacelle_K and nozzle_K (1 left, 2 right; SPEC thrust and fuel flow). Fuel flow
        // follows spool alone (Turbofan.cs:388), scaled from the Alkyon's 270 kN to the 330 kN engines:
        // 0.042 + (1.162 - 0.042) * 330 / 270 = 1.411 kg/s at full spool; idle flow stays 0.042 kg/s.
        private const float HeatHazeOpacity = 0.5f; // of the donor's
        private static void BuildEngines(Build b)
        {
            const int engines = 2;
            for (var k = 1; k <= engines; k++)
            {
                var nacelle = b.Parts["nacelle_" + k];
                var nozzlePart = b.Parts["nozzle_" + k];
                var nacelleBounds = b.Meshes["nacelle_" + k].Shape.bounds;
                var engine = FindDeep(b.Root.transform, "engine" + k);
                engine.SetParent(nacelle.transform, true);
                engine.SetPositionAndRotation(nacelle.transform.TransformPoint(nacelleBounds.center), Quaternion.identity);
                var capsule = engine.GetComponent<CapsuleCollider>();
                capsule.center = Vector3.zero;
                capsule.direction = 2;
                capsule.radius = Mathf.Min(nacelleBounds.extents.x, nacelleBounds.extents.y) - 0.3f;
                capsule.height = nacelleBounds.size.z - 0.6f;

                var nozzle = FindDeep(b.Root.transform, "nozzle" + k);
                nozzle.SetParent(nozzlePart.transform, true);
                var nozzleBounds = b.Meshes["nozzle_" + k].Shape.bounds;
                nozzle.SetPositionAndRotation(nozzlePart.transform.TransformPoint(new Vector3(nozzleBounds.center.x, nozzleBounds.center.y, nozzleBounds.min.z)), Quaternion.identity);
                Set(nozzle.GetComponent(GameType("JetNozzle")), "part", nozzlePart.GetComponent(GameType("AeroPart")));
                // The donor's heat haze leaves the nozzle exit right over the sponson's top, where at the donor's opacity
                // its distortion reads as white smoke streaming along the hull; half keeps the shimmer.
                var jetSo = new SerializedObject(nozzle.GetComponent(GameType("JetNozzle")));
                foreach (var field in new[] { "opacityMin", "opacityMax" })
                    Prop(jetSo, "heatHaze").FindPropertyRelative(field).floatValue *= HeatHazeOpacity;
                jetSo.ApplyModifiedPropertiesWithoutUndo();

                if (b.Blockout.Has("fan_" + k))
                    AddFan(b, k, nacelle.transform);

                var fan = engine.GetComponent(GameType("Turbofan"));
                var so = new SerializedObject(fan);
                Prop(so, "staticThrust").floatValue = 330000f;
                Prop(so, "minDensity").floatValue = 0.10f;
                Prop(so, "altitudeThrust").animationCurveValue = AltitudeThrust;
                Prop(so, "speedThrust").animationCurveValue = SpeedThrust;
                Prop(so, "fuelConsumptionMin").floatValue = 0.042f;
                Prop(so, "fuelConsumptionMax").floatValue = 1.411f;
                Prop(so, "turbineMaxPitch").floatValue = 1.2f;
                Prop(so, "part").objectReferenceValue = nacelle.GetComponent(GameType("AeroPart"));
                var critical = Prop(so, "criticalParts");
                critical.arraySize = 2;
                foreach (var (i, part, weight) in new[] { (0, nacelle, 1.0f), (1, nozzlePart, 0.5f) })
                {
                    var entry = critical.GetArrayElementAtIndex(i);
                    entry.FindPropertyRelative("part").objectReferenceValue = part.GetComponent(GameType("AeroPart"));
                    entry.FindPropertyRelative("threshold").floatValue = 70f;
                    entry.FindPropertyRelative("weight").floatValue = weight;
                }
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            if (b.Root.GetComponentsInChildren(GameType("Turbofan"), true).Length != engines || b.Root.GetComponentsInChildren(GameType("JetNozzle"), true).Length != engines)
                throw new InvalidDataException($"Expected {engines} Turbofans and JetNozzles after the engine move.");

            // Capacitor on the two engines (SPEC "Systems placement"); its powerSources are engine1-2 once StripDonor
            // removed engines 3 and 4.
            var power = b.Root.GetComponent(GameType("PowerSupply"));
            // 2,000 kJ in game: RadarJammer.Awake adds its 100 kJ to maxCharge (RadarJammer.cs:35-45).
            Set(power, "maxCharge", 1900f);
            // The whine and the HUD bar saturate at maxPower: at the stock 60 they stay flat above 94 kW, so maxPower matches the laser's draw.
            Set(power, "maxPower", 120f);
            Set(power, "chargePerRPM", 0.010f);
            var sources = Prop(new SerializedObject(power), "powerSources").arraySize;
            if (sources != engines)
                throw new InvalidDataException($"The capacitor has {sources} power sources, expected {engines}.");
        }

        // Darkreach gear values scaled by 1.5 for the heavier aircraft, except the damping. The main legs are critically
        // damped at light weight (2 x sqrt(2 x springRate x 132 t) is 1.26e6 per leg), so a touchdown doesn't rebound into a
        // float the landing AI goes around from (tools/fm/centurion_landing.py). The nose leg is critically damped on its
        // 32 t share of the empty mass (2 x sqrt(1.8e6 x 32 t) is 4.8e5): the step 6 wing touches down nearly flat, nose and
        // mains together, and at 1.5e5 a 7 m/s touchdown at 199 t pushed it past its 0.65 m maxCompression. The bump stop sits suspensionTravel
        // above the ground, so the free wheel touches it (LandingGear casts down suspensionTravel from it).
        private static void BuildGear(Build b)
        {
            var ground = -b.Blockout.Origin.y;
            void Gear(string gearPath, Transform mount, string blockoutGear, string blockoutWheel, string part, float travel, float radius, float spring, float damping, params string[] doorNames)
            {
                var gear = b.Root.transform.Find(gearPath) ?? FindDeep(b.Root.transform, gearPath.Split('/').Last());
                var bump = gear.Find("bumpstop");
                var wheelCentre = b.Blockout.Local(blockoutWheel);
                mount.position += new Vector3(wheelCentre.x, ground + travel, wheelCentre.z) - bump.position;
                var unsprung = gear.Cast<Transform>().First(t => t.name.StartsWith("gear_unsprung", StringComparison.Ordinal));
                unsprung.position = bump.position - bump.up * (travel - radius);

                // The Alkyon's struts and wheels give way to the blockout's; lights, audio and chocks stay.
                foreach (var r in gear.GetComponentsInChildren<MeshRenderer>(true).Where(r => r.name != "chocks").ToArray())
                {
                    if (r.TryGetComponent<MeshFilter>(out var filter))
                        Object.DestroyImmediate(filter);
                    Object.DestroyImmediate(r);
                }
                AddVisual(b, blockoutGear, gear);
                var wheels = unsprung.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name.StartsWith("wheel_", StringComparison.Ordinal)) ?? unsprung;
                AddVisual(b, blockoutWheel, gearPath.EndsWith("gear_F", StringComparison.Ordinal) ? wheels : unsprung);
                PlaceChocks(b, gear, blockoutWheel, radius);

                var box = gear.GetComponent<BoxCollider>();
                box.center = gear.InverseTransformPoint(Vector3.Lerp(gear.position, bump.position, 0.5f));
                box.size = new Vector3(0.4f, Mathf.Max(0.3f, (gear.position - bump.position).magnitude), 0.4f);

                var so = new SerializedObject(gear.GetComponent(GameType("LandingGear")));
                var doors = Prop(so, "gearDoors");
                doors.arraySize = 0;
                foreach (var name in doorNames.Where(d => b.Blockout.Has(d) && b.Blockout.HasMesh(d + "_visible")))
                {
                    var doorMount = new GameObject(name) { layer = b.Root.layer }.transform;
                    doorMount.SetParent(b.Parts[part].transform, false);
                    var hinge = new GameObject(name + "_hinge") { layer = b.Root.layer }.transform;
                    hinge.SetParent(doorMount, false);
                    var panel = new GameObject(name + "_visible") { layer = b.Root.layer }.transform;
                    panel.SetParent(hinge, false);
                    RigDoor(doorMount, hinge, panel, b.Blockout.Local(name), b.Blockout.Rotation(name) * Vector3.right,
                        b.Meshes[name + "_visible"].Render, b.Blockout.Rotation(name + "_visible"), b.Blockout.Local(name + "_visible"));
                    var angle = CloseGearDoor(panel, b.Blockout.Local(name), b.Blockout.Rotation(name) * Vector3.right);
                    panel.gameObject.AddComponent<MeshRenderer>().sharedMaterials = b.MaterialsFor(name + "_visible");
                    b.Visuals[name + "_visible"] = panel;
                    b.Visuals[name] = doorMount;
                    doors.arraySize++;
                    var entry = doors.GetArrayElementAtIndex(doors.arraySize - 1);
                    entry.FindPropertyRelative("transform").objectReferenceValue = hinge;
                    entry.FindPropertyRelative("closedAngle").vector3Value = Vector3.zero;
                    entry.FindPropertyRelative("openAngle").vector3Value = new Vector3(0, 0, angle);
                }
                Prop(so, "attachedPart").objectReferenceValue = b.Part(part);
                Prop(so, "suspensionTravel").floatValue = travel;
                Prop(so, "wheelRadius").floatValue = radius;
                Prop(so, "springRate").floatValue = spring;
                Prop(so, "dampingRate").floatValue = damping;
                so.ApplyModifiedPropertiesWithoutUndo();
                b.Report.Add($"gear {gear.name} on {part}: bump stop {bump.position}, travel {travel}, wheel radius {radius}, spring {spring:0}, damping {damping:0}");
            }

            var nose = b.Parts["nose"].transform;
            var noseHinge = b.Root.transform.Find("gearhinge_F");
            var armTarget = b.Root.transform.Find("gear_F_armtarget");
            noseHinge.SetParent(nose, true);
            armTarget.SetParent(noseHinge, true);
            Gear("nose/gearhinge_F/gear_F", noseHinge, "gear_F", "wheel_F", "nose", 0.95f, 0.55f, 1.8e6f, 4.8e5f, "geardoor_FL", "geardoor_FR");
            Gear("gear_L", b.Parts["sponson_L"].transform.Find("gearMount_L"), "gear_LM", "wheel_LM", "sponson_L", 1.6f, 0.6f, 6e6f, 1.2e6f, "geardoor_LM");
            Gear("gear_R", b.Parts["sponson_R"].transform.Find("gearMount_R"), "gear_RM", "wheel_RM", "sponson_R", 1.6f, 0.6f, 6e6f, 1.2e6f, "geardoor_RM");
            FoldMainLegAsArt(b, "gear_L", "gear_LM", "wheel_LM");
            FoldMainLegAsArt(b, "gear_R", "gear_RM", "wheel_RM");
            RigGearAsArt(b);
            PlaceTaxiLight(b);
        }

        // The main legs fold as the art retracts them (art/blender/m4/gear.py retract_main: MainRetractDeg inboard and up
        // about gear_LM's origin, a fore-and-aft axis), so the leg door the leg carries closes the well's outboard strip
        // the main door leaves. The donor's fold (88 degrees about its own mount, shifted by hingeFoldMotion) left that
        // strip open in flight. The hinge moves onto the art's pivot with the leg kept where it stands, so the rest pose and
        // bump stop don't change. The game doesn't shorten the strut as the art does (MAIN_SHRINK), which only carries the
        // bogie deeper inside the body.
        private const float MainRetractDeg = 120f; // art/blender/m4/gear.py MAIN_RETRACT_DEG
        private static void FoldMainLegAsArt(Build b, string gearName, string blockoutGear, string blockoutWheel)
        {
            var gear = FindDeep(b.Root.transform, gearName);
            var so = new SerializedObject(gear.GetComponent(GameType("LandingGear")));
            var hinge = (Transform)Prop(so, "gearHinge").objectReferenceValue;
            var pivot = b.Blockout.Local(blockoutGear);
            if (Mathf.Abs(Vector3.Dot(hinge.right, Vector3.forward)) < 0.999f)
                throw new InvalidDataException($"{gearName}: the fold hinge's axis {hinge.right} isn't fore-and-aft, as the art's is.");
            var held = hinge.Cast<Transform>().Select(t => (t, t.position, t.rotation)).ToArray();
            hinge.position = pivot;
            foreach (var (t, position, rotation) in held)
                t.SetPositionAndRotation(position, rotation);
            var wheel = b.Blockout.Local(blockoutWheel) - pivot;
            var degrees = Mathf.Abs(pivot.x + (Quaternion.AngleAxis(MainRetractDeg, hinge.right) * wheel).x) < Mathf.Abs(pivot.x + wheel.x)
                ? MainRetractDeg : -MainRetractDeg;
            Prop(so, "foldDegrees").floatValue = degrees;
            Prop(so, "hingeFoldMotion").vector3Value = Vector3.zero;
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"gear {gearName} folds {degrees} deg about {pivot} (the art's hinge)");
        }

        // Visual-only child carrying a blockout mesh at its pivot (fans, gear struts, wheels). The suffix keeps
        // it apart from the Alkyon transform of the same name it often hangs under.
        private static void AddVisual(Build b, string blockoutName, Transform parent)
        {
            var go = new GameObject(blockoutName + "_mesh") { layer = b.Root.layer };
            go.transform.SetParent(parent, true);
            go.transform.SetPositionAndRotation(b.Blockout.Local(blockoutName), b.Blockout.Rotation(blockoutName));
            go.AddComponent<MeshFilter>().sharedMesh = b.Meshes[blockoutName].Render;
            b.Visuals[blockoutName] = go.transform;
            go.AddComponent<MeshRenderer>().sharedMaterials = b.MaterialsFor(blockoutName);
        }

        // A door: mount on the hinge line with local Z along it (BayDoor and LandingGear.GearDoor both turn
        // local Z), an animated hinge under it at identity when closed, and the panel under that. Returns the
        // angle that swings the panel down.
        private static float RigDoor(Transform mount, Transform hinge, Transform panel, Vector3 pivot, Vector3 hingeAxis, Mesh mesh, Quaternion panelRotation, Vector3 panelPosition)
        {
            mount.SetPositionAndRotation(pivot, Quaternion.LookRotation(hingeAxis, Vector3.ProjectOnPlane(Vector3.up, hingeAxis)));
            hinge.SetPositionAndRotation(pivot, mount.rotation);
            panel.SetPositionAndRotation(panelPosition, panelRotation);
            Ensure<MeshFilter>(panel.gameObject).sharedMesh = mesh;
            var centre = panel.TransformPoint(mesh.bounds.center) - pivot;
            return (Quaternion.AngleAxis(90f, hingeAxis) * centre).y < centre.y ? 90f : -90f;
        }

        // The gear doors are authored open, hanging 90 degrees down with the gear (build_centurion.build_geardoors, the
        // detail pass's nose.gear_door and struts.build_door), but LandingGear.GearDoor reads the hinge at identity as
        // closed and snaps it there once the gear is up (LandingGear.MoveGear), as the stock doors are authored closed.
        // So the panel swings shut about the hinge the way that turns its outer skin (submesh 0) to face down, and the
        // returned open angle swings it back to the authored pose.
        private static float CloseGearDoor(Transform panel, Vector3 pivot, Vector3 hingeAxis)
        {
            var mesh = panel.GetComponent<MeshFilter>().sharedMesh;
            var vertices = mesh.vertices;
            var skin = mesh.GetTriangles(0);
            var normal = Vector3.zero;
            for (var i = 0; i < skin.Length; i += 3)
                normal += Vector3.Cross(vertices[skin[i + 1]] - vertices[skin[i]], vertices[skin[i + 2]] - vertices[skin[i]]);
            normal = panel.TransformDirection(normal);
            var shut = (Quaternion.AngleAxis(90f, hingeAxis) * normal).y < (Quaternion.AngleAxis(-90f, hingeAxis) * normal).y ? 90f : -90f;
            var swing = Quaternion.AngleAxis(shut, hingeAxis);
            panel.SetPositionAndRotation(pivot + swing * (panel.position - pivot), swing * panel.rotation);
            return -shut;
        }

        // Hardpoint sets per SPEC: forward bay, aft bay, dorsal, laser. Bays use the Alkyon's BayDoors, on the
        // blockout's door hinges and panels when it has them, else on generated 8 m slabs.
        private static void BuildBays(Build b)
        {
            var fwd = b.Parts["fuselage_F"].transform;
            var aft = b.Parts["fuselage_R"].transform;
            var bottom = ShapeBounds(b, "fuselage_M").min.y - 0.03f;
            float Station(float s) => OriginStation - s - b.Blockout.Origin.z;
            Component Door(string hingePath, string blockoutDoor, Transform parent, float x, float zCentre, int side)
            {
                var mount = b.Root.transform.Find(hingePath) ?? throw new MissingReferenceException(hingePath);
                mount.SetParent(parent, true);
                var hinge = mount.GetChild(0);
                var panel = hinge.GetChild(0);
                float angle;
                if (b.Blockout.Has(blockoutDoor) && b.Blockout.HasMesh(blockoutDoor + "_visible"))
                {
                    var visible = blockoutDoor + "_visible";
                    angle = RigDoor(mount, hinge, panel, b.Blockout.Local(blockoutDoor), b.Blockout.Rotation(blockoutDoor) * Vector3.right,
                        b.Meshes[visible].Render, b.Blockout.Rotation(visible), b.Blockout.Local(visible));
                    b.Visuals[visible] = panel;
                    b.Visuals[blockoutDoor] = mount;
                    Ensure<MeshRenderer>(panel.gameObject).sharedMaterials = b.MaterialsFor(visible);
                }
                else
                {
                    var w = 0.95f * side;
                    var slab = SaveMesh(Slab("baydoor_" + (side > 0 ? "L" : "R") + "_slab",
                        new[] { new Vector3(0, 0, -4), new Vector3(0, 0, 4), new Vector3(w, 0, 4), new Vector3(w, 0, -4) }, Vector3.up, 0.06f));
                    var pivot = new Vector3(x, bottom, zCentre);
                    angle = RigDoor(mount, hinge, panel, pivot, Vector3.forward, slab, Quaternion.identity, pivot);
                    Ensure<MeshRenderer>(panel.gameObject).sharedMaterials = new[] { b.Skin };
                }
                var door = hinge.GetComponent(GameType("BayDoor"));
                Set(door, "hingeAngle", angle);
                return door;
            }
            float BayCentre(string door, float station) => b.Blockout.Has(door) ? b.Blockout.Local(door).z : Station(station);
            var fz = BayCentre("baydoor_FL", 11);
            var az = BayCentre("baydoor_AL", 27);
            var forwardDoors = new[] { Door("bayDoorHinge_FL1", "baydoor_FL", fwd, -0.95f, fz, 1), Door("bayDoorHinge_FR1", "baydoor_FR", fwd, 0.95f, fz, -1) };
            var aftDoors = new[] { Door("fuselage_R/bayDoorHinge_RL1", "baydoor_AL", aft, -0.95f, az, 1), Door("fuselage_R/bayDoorHinge_RR1", "baydoor_AR", aft, 0.95f, az, -1) };

            Transform Point(string name, Transform parent, Vector3 position)
            {
                var t = new GameObject(name) { layer = b.Root.layer }.transform;
                t.SetParent(parent, false);
                t.position = position;
                return t;
            }
            // The AWACS spine well (stations 24.74 to 34.84): its lids, spine_cover and spine_cover_A (VisualPieces), show on
            // the bomber, and the dorsal mount goes on the crown at the forward lid's pivot, the mast sleeve's station, under
            // fuselage_R, which carries its mass and joint (docs/M3-DESIGN.md "Hardpoint"). AwacsBeam hides the lids when the
            // beam is fitted.
            AddVisual(b, "spine_cover", aft);
            AddVisual(b, "spine_cover_A", aft);
            var tail = b.Parts[CramHost].transform;
            AddVisual(b, "laser_turret", tail);
            var sets = new (string name, Transform point, string part, Component[] doors)[]
            {
                ("Forward Bay", Point("hardpoint_bay_forward", fwd, new Vector3(0, -0.4f, fz)), "fuselage_F", forwardDoors),
                ("Aft Bay", Point("hardpoint_bay_aft", aft, new Vector3(0, -0.4f, az)), "fuselage_R", aftDoors),
                ("Dorsal", Point("hardpoint_dorsal", aft, b.Blockout.Local("spine_cover")), "fuselage_R", new Component[0]),
                ("Laser C-RAM", Point("hardpoint_laser", tail, b.Blockout.Local("laser_turret")), CramHost, new Component[0]),
            };
            var manager = b.Parts["cockpit"].GetComponent(GameType("WeaponManager"));
            var so = new SerializedObject(manager);
            var list = Prop(so, "hardpointSets");
            list.arraySize = sets.Length;
            for (var i = 0; i < sets.Length; i++)
            {
                var set = list.GetArrayElementAtIndex(i);
                set.FindPropertyRelative("name").stringValue = sets[i].name;
                // The beam's mast sleeve hangs into the aft bay: sets 1 and 2 never carry mounts together (docs/M3-DESIGN.md "What Blueprinter needs").
                var precluding = set.FindPropertyRelative("precludingHardpointSets");
                precluding.arraySize = i == 1 || i == 2 ? 1 : 0;
                if (precluding.arraySize > 0)
                    precluding.GetArrayElementAtIndex(0).intValue = 3 - i;
                set.FindPropertyRelative("SymmetryWithPrev").boolValue = false;
                set.FindPropertyRelative("SymmetryName").stringValue = string.Empty;
                var options = set.FindPropertyRelative("weaponOptions");
                options.arraySize = 1; // index 0 is "empty"; mounts arrive through OpAddWeaponToHardpoint
                options.GetArrayElementAtIndex(0).objectReferenceValue = null;
                set.FindPropertyRelative("weaponMount").objectReferenceValue = null;
                var hardpoints = set.FindPropertyRelative("hardpoints");
                hardpoints.arraySize = 1;
                var hp = hardpoints.GetArrayElementAtIndex(0);
                hp.FindPropertyRelative("transform").objectReferenceValue = sets[i].point;
                hp.FindPropertyRelative("part").objectReferenceValue = b.Part(sets[i].part);
                var doors = hp.FindPropertyRelative("bayDoors");
                doors.arraySize = sets[i].doors.Length;
                for (var d = 0; d < sets[i].doors.Length; d++)
                    doors.GetArrayElementAtIndex(d).objectReferenceValue = sets[i].doors[d];
                hp.FindPropertyRelative("doorOpenDuration").floatValue = sets[i].doors.Length > 0 ? DenseBayDoorHold : 0f;
                hp.FindPropertyRelative("pylonOptions").arraySize = 0;
                hp.FindPropertyRelative("Pylon").objectReferenceValue = null;
                hp.FindPropertyRelative("Plug").objectReferenceValue = null;
                hp.FindPropertyRelative("BuiltInWeapons").arraySize = 0;
                hp.FindPropertyRelative("BuiltInTurrets").arraySize = 0;
                hp.FindPropertyRelative("HardpointIndex").intValue = i;
            }
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        // Blockout parts no table gives a role (a later blockout step's additions) ride along as plain meshes
        // under their nearest placed Blender ancestor, so they show in game and in the report.
        private static void AttachLeftovers(Build b)
        {
            foreach (var part in b.Blockout.Parts.Values.OrderBy(p => p.Name, StringComparer.Ordinal))
            {
                if (b.Parts.ContainsKey(part.Name) || b.Visuals.ContainsKey(part.Name) || CramOwnedParts.Contains(part.Name))
                    continue;
                if (part.Fbx == null)
                {
                    b.Report.Add($"note: blockout empty {part.Name} has no role yet; skipped");
                    continue;
                }
                Transform parent = null;
                for (var name = part.BlenderParent; name != null && parent == null; name = b.Blockout.Has(name) ? b.Blockout.Parts[name].BlenderParent : null)
                    parent = b.Parts.TryGetValue(name, out var go) ? go.transform : b.Visuals.TryGetValue(name, out var visual) ? visual : null;
                parent = parent != null ? parent : b.Root.transform;
                AddVisual(b, part.Name, parent);
                b.Report.Add($"note: blockout part {part.Name} has no role yet; added as a mesh under {parent.name}");
            }
        }

        // Each blockout LOD1 hull on the part or visual it belongs to, at identity (the export puts it in that mesh's space).
        private static void AddLods(Build b)
        {
            foreach (var entry in b.Meshes.Where(m => m.Value.Lod1 != null && !CramOwnedParts.Contains(m.Key)).OrderBy(m => m.Key, StringComparer.Ordinal))
            {
                var owner = b.Parts.TryGetValue(entry.Key, out var part) ? part.transform
                    : b.Visuals.TryGetValue(entry.Key, out var visual) ? visual : throw new InvalidDataException(entry.Key + " has a LOD1 hull but no place in the prefab");
                var go = new GameObject(entry.Key + "_lod1") { layer = b.Root.layer };
                go.transform.SetParent(owner, false);
                go.AddComponent<MeshFilter>().sharedMesh = entry.Value.Lod1;
                var renderer = go.AddComponent<MeshRenderer>();
                renderer.sharedMaterials = entry.Value.Lod1Materials;
                b.Lod1.Add(renderer);
            }
        }

        // Every renderer wearing the skin goes in its part's damageMaterial.renderers, the only renderers UnitPart.SetLivery
        // paints (and UnitPart tints with damage). The doors, the wing fairing, the spine cover and the tail radar panel
        // were missing, so they kept the baked grey under every livery.
        private static void ListLiveryRenderers(Build b)
        {
            var aeroType = GameType("AeroPart");
            foreach (var renderer in b.Root.GetComponentsInChildren<MeshRenderer>(true).Where(r => r.sharedMaterials.Contains(b.Skin)))
            {
                var owner = renderer.transform;
                while (owner.GetComponent(aeroType) == null)
                    owner = owner.parent;
                var so = new SerializedObject(owner.GetComponent(aeroType));
                var list = so.FindProperty("damageMaterial").FindPropertyRelative("renderers");
                if (Enumerable.Range(0, list.arraySize).Any(i => list.GetArrayElementAtIndex(i).objectReferenceValue == renderer))
                    continue;
                list.arraySize++;
                list.GetArrayElementAtIndex(list.arraySize - 1).objectReferenceValue = renderer;
                so.ApplyModifiedPropertiesWithoutUndo();
                b.Report.Add($"livery: {PathOf(renderer.transform, b.Root.transform)} listed on {owner.name}");
            }
        }

        // Two levels as stock: the full meshes, then the LOD1 hulls down to 0.1% of the screen. The size is the extended
        // span, so the switch distance doesn't move as the wing telescopes.
        private static void FinishRoot(Build b)
        {
            b.Root.GetComponent<Rigidbody>().mass = EmptyMass;
            var lod = b.Root.GetComponent<LODGroup>();
            var renderers = b.Root.GetComponentsInChildren<Renderer>(true).Where(r => r.gameObject.layer != 3 && !(r is ParticleSystemRenderer)).ToArray();
            var hulls = b.Lod1.ToArray();
            var full = renderers.Except(hulls).ToArray();
            lod.SetLODs(new[] { new LOD(0.05f, full), new LOD(0.001f, hulls) });
            lod.RecalculateBounds();
            lod.size = b.Blockout.ExtendedSpan();
            b.Report.Add($"LODGroup: {full.Length} renderers to 5% of the screen, {hulls.Length} LOD1 hulls to 0.1%, size {lod.size:F2} m (extended span)");
        }

        // ---------- validation and report ----------

        private static Vector3 CenterOfMass(Build b)
        {
            var aeroType = GameType("AeroPart");
            var sum = Vector3.zero;
            var mass = 0f;
            foreach (var part in b.Root.GetComponentsInChildren(aeroType, true))
            {
                var so = new SerializedObject(part);
                var m = so.FindProperty("mass").floatValue;
                var com = (Transform)so.FindProperty("centerOfMass").objectReferenceValue;
                sum += m * (com != null ? com.position : part.transform.position);
                mass += m;
            }
            return sum / mass;
        }

        private static void Validate(Build b, Object awacsMount)
        {
            var aeroType = GameType("AeroPart");
            var parts = b.Root.GetComponentsInChildren(aeroType, true);
            var problems = new List<string>();
            var total = parts.Sum(p => new SerializedObject(p).FindProperty("mass").floatValue);
            if (Mathf.Abs(total - EmptyMass) > 1f)
                problems.Add($"AeroPart masses sum to {total}, not {EmptyMass}");

            foreach (var part in parts)
            {
                var so = new SerializedObject(part);
                var joints = so.FindProperty("joints");
                if (part.gameObject == b.Root)
                {
                    if (joints.arraySize != 0)
                        problems.Add("the root part has joints");
                    continue;
                }
                var parentPart = part.transform.parent.GetComponent(aeroType);
                if (parentPart == null)
                    problems.Add(part.name + " isn't a direct child of a part (UnitPart.Awake looks only at the parent)");
                else if (joints.arraySize == 0 || joints.GetArrayElementAtIndex(0).FindPropertyRelative("connectedPart").objectReferenceValue != parentPart)
                    problems.Add(part.name + ": joints[0] doesn't connect to its parent part");
                if (so.FindProperty("parentUnit").objectReferenceValue != b.Aircraft)
                    problems.Add(part.name + ": parentUnit isn't the Aircraft");
            }

            // G1.5: exactly one controlling Pilot, at index 0 (the player's, Pilot_OnInitialize), and at most one more.
            var pilots = b.Root.GetComponentsInChildren(GameType("Pilot"), true);
            var listed = new SerializedObject(b.Aircraft).FindProperty("pilots");
            var listedPilots = Enumerable.Range(0, listed.arraySize).Select(i => listed.GetArrayElementAtIndex(i).objectReferenceValue).ToArray();
            if (pilots.Length < 1 || pilots.Length > 2 || listedPilots.Length != pilots.Length || listedPilots.Any(p => p == null || !pilots.Contains(p))
                || listedPilots[0] == null || ((Component)listedPilots[0]).name != "Pilot")
                problems.Add($"{pilots.Length} Pilot components, Aircraft.pilots [{string.Join(", ", listedPilots.Select(p => p == null ? "null" : p.name))}]; expected the pilot first and at most the mission commander after");
            foreach (var banned in new[] { "SwingWingController", "HighLiftDevice" })
                if (b.Root.GetComponentsInChildren(GameType(banned), true).Length > 0)
                    problems.Add("a " + banned + " remains");
            foreach (var surface in b.Root.GetComponentsInChildren(GameType("ControlSurface"), true))
            {
                var so = new SerializedObject(surface);
                if (so.FindProperty("attachedSurface").objectReferenceValue == null || so.FindProperty("visibleMesh").objectReferenceValue == null)
                    problems.Add(surface.name + ": ControlSurface without a part or hinge");
            }
            foreach (var t in b.Root.GetComponentsInChildren<Transform>(true))
            {
                var dupes = t.Cast<Transform>().GroupBy(c => c.name).Where(g => g.Count() > 1).Select(g => g.Key).ToArray();
                if (dupes.Length > 0)
                    problems.Add($"{PathOf(t, b.Root.transform)} has duplicate children: {string.Join(", ", dupes)}");
            }
            foreach (var component in b.Root.GetComponentsInChildren<Component>(true))
                if (component == null)
                    problems.Add("a missing script remains");
            foreach (var targetCam in b.Root.GetComponentsInChildren(GameType("TargetCam"), true))
                if (Prop(new SerializedObject(targetCam), "targetScreenRenderer").objectReferenceValue == null)
                    problems.Add($"{PathOf(targetCam.transform, b.Root.transform)}: TargetCam without a targetScreenRenderer");
            problems.AddRange(LiveryCoverage(b, awacsMount));
            problems.AddRange(ColliderOverlaps(b));
            problems.AddRange(EscapeProbe(b));
            if (problems.Count > 0)
                throw new InvalidDataException("Centurion prefab checks failed:\n  " + string.Join("\n  ", problems));

            CheckAwacsEnvelope(b, awacsMount);
            CheckCramCone(b);
            CheckTargetCameraClearance(b);
            ReportParts(b, parts);
        }

        // A conservative surface check: every render mesh lies inside its transformed vertex bounds. Rejecting
        // bounds within 2.5 m also rejects every surface within the game's 2 m near plane plus a 0.5 m margin.
        private static void CheckTargetCameraClearance(Build b)
        {
            const float clearance = 2.5f;
            var cameras = new[] { b.Parts["radar_F_fairing"].transform.Find("targetCamPoint_F"), b.Parts["tailcone"].transform.Find("targetCamPoint_R") };
            if (cameras.Any(t => t == null)) throw new InvalidDataException("Target camera mount missing");
            var meshes = b.Root.GetComponentsInChildren<MeshFilter>(true).Where(f => f.sharedMesh != null)
                .Select(f => (filter: f, vertices: f.sharedMesh.vertices)).Where(m => m.vertices.Length > 0).ToArray();
            if (meshes.Length == 0) throw new InvalidDataException("Target camera clearance check has no meshes");
            var slides = Parts.Where(p => b.Blockout.Slide(p.Name).HasValue).Select(p => b.Parts[p.Name].transform)
                .Select(t => (stage: t, rest: t.localPosition, end: t.parent.Find(t.name + "_extended").localPosition)).ToArray();
            var rotations = new List<(Transform hinge, Quaternion rest, Quaternion up, Quaternion down)>();
            foreach (var gear in b.Root.GetComponentsInChildren(GameType("LandingGear"), true))
            {
                var so = new SerializedObject(gear);
                var hinge = (Transform)Prop(so, "gearHinge").objectReferenceValue;
                rotations.Add((hinge, hinge.localRotation, Quaternion.Euler(hinge.localEulerAngles + new Vector3(Prop(so, "foldDegrees").floatValue, 0, 0)), hinge.localRotation));
                var doors = Prop(so, "gearDoors");
                for (var i = 0; i < doors.arraySize; i++)
                {
                    var door = doors.GetArrayElementAtIndex(i);
                    var t = (Transform)door.FindPropertyRelative("transform").objectReferenceValue;
                    if (t != null) rotations.Add((t, t.localRotation, Quaternion.Euler(door.FindPropertyRelative("closedAngle").vector3Value), Quaternion.Euler(door.FindPropertyRelative("openAngle").vector3Value)));
                }
            }
            var bays = b.Root.GetComponentsInChildren(GameType("BayDoor"), true).Select(door =>
                (hinge: door.transform, rest: door.transform.localRotation, angle: Prop(new SerializedObject(door), "hingeAngle").floatValue)).ToArray();
            var minimum = float.PositiveInfinity;
            try
            {
                foreach (var extension in new[] { 0f, 1f })
                foreach (var gearDown in new[] { false, true })
                foreach (var bayOpen in new[] { false, true })
                {
                    foreach (var slide in slides) slide.stage.localPosition = Vector3.Lerp(slide.rest, slide.end, extension);
                    foreach (var rotation in rotations) rotation.hinge.localRotation = gearDown ? rotation.down : rotation.up;
                    foreach (var bay in bays) bay.hinge.localRotation = bay.rest * Quaternion.Euler(0, 0, bayOpen ? bay.angle : 0);
                    foreach (var mesh in meshes)
                    {
                        var bounds = new Bounds(mesh.filter.transform.TransformPoint(mesh.vertices[0]), Vector3.zero);
                        foreach (var vertex in mesh.vertices) bounds.Encapsulate(mesh.filter.transform.TransformPoint(vertex));
                        foreach (var camera in cameras)
                        {
                            var distance = Vector3.Distance(camera.position, bounds.ClosestPoint(camera.position));
                            if (distance < clearance - 0.001f)
                                throw new InvalidDataException($"Target camera {camera.name}: {distance:F3} m from {PathOf(mesh.filter.transform, b.Root.transform)} mesh bounds, requires {clearance:F2} m; span {extension}, gear down {gearDown}, bays open {bayOpen}");
                            minimum = Mathf.Min(minimum, distance);
                        }
                    }
                }
                b.Report.Add($"Target cameras: >= {clearance:F2} m hull clearance at both spans, gear up/down, bays closed/open; minimum mesh bounds clearance {minimum:F3} m; F {cameras[0].position}, R {cameras[1].position}");
            }
            finally
            {
                foreach (var slide in slides) slide.stage.localPosition = slide.rest;
                foreach (var rotation in rotations) rotation.hinge.localRotation = rotation.rest;
                foreach (var bay in bays) bay.hinge.localRotation = bay.rest;
            }
        }

        // Every renderer and material slot on the aircraft and the AWACS mount, listed in the report against the livery
        // rule: a surface takes the livery unless it is glass, a light, the laser lens, metal trim (fan blades, nozzles,
        // fittings), gear, hidden structure, a LOD1 hull or the wheel chocks. The airframe's livery reaches the skin on
        // slot 0 of a renderer its part lists in damageMaterial.renderers (UnitPart.SetLivery); the mount's reaches
        // Centurion_mount on a renderer ColorableMount lists, where its _Paint mask is 1 (the stock shader showed the pale
        // base under PALA Matte Black wherever the mask fell under 1). Leading edges, tip caps, collars, the beam and its
        // mast are livery surfaces: their satin finish is painted in the livery's colours (art/blender/m4/livery.py), so
        // no other material may stand in for them. The flight deck under the cockpit part (its interior, crew and seats) is
        // drawn only in cockpit view, on its own materials.
        private static List<string> LiveryCoverage(Build b, Object awacsMount)
        {
            var nonLivery = new Dictionary<string, string>
            {
                { SkinFolder + "/Centurion_glass.mat", "glazing" },
                { SkinFolder + "/Centurion_lens.mat", "the laser turret's lens" },
                { SkinFolder + "/Centurion_mech.mat", "fan blades, spinners, nozzles, probes and actuators" },
                { SkinFolder + "/Centurion_gear.mat", "the gear legs and wheels" },
                { SkinFolder + "/Centurion_structure.mat", "joint faces, cut-out walls, door inner faces and skin a neighbour hides" },
                { SkinFolder + "/Centurion_airframe.mat", "the damage structure under the skin: frames, lining, members, break faces" },
                { SlotMaterials["LOD"], "a LOD1 hull" },
                { Stock + "Material/GroundSupportEquipment_PLACEHOLDER.mat", "the wheel chocks" },
            };
            foreach (var light in new[] { "navlight_L", "navlight_R", "light_red_off", "light_green_off", "gearLight" })
                nonLivery.Add(Stock + "Material/" + light + "_PLACEHOLDER.mat", "a light");
            var why = nonLivery.Select(e => (Material: AssetDatabase.LoadAssetAtPath<Material>(e.Key), Why: e.Value))
                .Where(e => e.Material != null).ToDictionary(e => e.Material, e => e.Why);

            var aeroType = GameType("AeroPart");
            var cockpit = b.Part("cockpit");
            var problems = new List<string>();
            foreach (var renderer in b.Root.GetComponentsInChildren<MeshRenderer>(true).OrderBy(r => PathOf(r.transform, b.Root.transform), StringComparer.Ordinal))
            {
                var path = PathOf(renderer.transform, b.Root.transform);
                var owner = renderer.GetComponentInParent(aeroType, true);
                // The hatch liners ride on the nose's hatches so they leave with a jettisoned hatch; they are the flight
                // deck's inner face, painted on its own materials.
                if (owner == cockpit || renderer.name.StartsWith("hatch_liner_", StringComparison.Ordinal))
                {
                    b.Report.Add($"livery map: {path}: the flight deck, its own materials");
                    continue;
                }
                var list = owner == null ? null : new SerializedObject(owner).FindProperty("damageMaterial").FindPropertyRelative("renderers");
                var listed = list != null && Enumerable.Range(0, list.arraySize).Any(i => list.GetArrayElementAtIndex(i).objectReferenceValue == renderer);
                var slots = renderer.sharedMaterials;
                var line = new List<string>();
                for (var i = 0; i < slots.Length; i++)
                {
                    var m = slots[i];
                    if (m == b.Skin)
                    {
                        line.Add($"{i} livery skin{(listed ? ", listed" : ", NOT LISTED")}");
                        if (i != 0)
                            problems.Add($"{path} wears the skin on slot {i}; UnitPart.SetLivery paints slot 0 only");
                        if (!listed)
                            problems.Add($"{path} wears the skin, but {(owner == null ? "no part owns it" : owner.name + "'s damageMaterial.renderers misses it")}, so no livery reaches it");
                    }
                    else if (m != null && why.TryGetValue(m, out var reason))
                        line.Add($"{i} {m.name} ({reason})");
                    else
                    {
                        line.Add($"{i} {(m == null ? "none" : m.name)} (NO LIVERY)");
                        problems.Add($"{path} slot {i} wears {(m == null ? "no material" : m.name)}, which takes no livery and is none of the non-livery finishes");
                    }
                }
                b.Report.Add($"livery map: {path}: {string.Join("; ", line)}");
            }

            if (awacsMount == null)
            {
                b.Report.Add("livery map: no AWACS mount authored");
                return problems;
            }
            var prefab = (GameObject)new SerializedObject(awacsMount).FindProperty("prefab").objectReferenceValue;
            var paint = Load<Material>(AwacsPaintPath);
            var lod = Load<Material>(SlotMaterials["LOD"]);
            var colorable = prefab.GetComponent(GameType("ColorableMount"));
            var tinted = colorable == null ? null : new SerializedObject(colorable).FindProperty("colorableRenderers");
            foreach (var renderer in prefab.GetComponentsInChildren<MeshRenderer>(true))
            {
                var path = PathOf(renderer.transform, null);
                var slots = renderer.sharedMaterials;
                if (slots.Length == 1 && slots[0] == lod)
                {
                    b.Report.Add($"livery map: {path}: 0 {lod.name} (a LOD1 hull)");
                    continue;
                }
                var listed = tinted != null && Enumerable.Range(0, tinted.arraySize).Any(i => tinted.GetArrayElementAtIndex(i).objectReferenceValue == renderer);
                b.Report.Add($"livery map: {path}: {string.Join("; ", slots.Select((m, i) => $"{i} {(m == null ? "none" : m.name)}"))}{(listed ? ", colorable" : ", NOT COLORABLE")}");
                if (slots.Length != 1 || slots[0] != paint)
                    problems.Add($"{path} wears {string.Join(", ", slots.Select(m => m == null ? "none" : m.name))}; only {paint.name} takes ColorableMount's livery colour");
                if (!listed)
                    problems.Add($"{path} isn't in ColorableMount.colorableRenderers, so no livery colour reaches it");
            }
            var mask = paint.HasProperty("_Paint") ? paint.GetTexture("_Paint") : null;
            if (mask != null)
            {
                var image = new Texture2D(2, 2);
                image.LoadImage(File.ReadAllBytes(AssetDatabase.GetAssetPath(mask)));
                var partial = image.GetPixels32().Count(p => p.r != 0 && p.r != 255);
                Object.DestroyImmediate(image);
                b.Report.Add($"livery map: the mount's _Paint mask has {partial} texels between 0 and 1");
                if (partial > 0)
                    problems.Add($"the mount's _Paint mask ({AssetDatabase.GetAssetPath(mask)}) has {partial} texels between 0 and 1, which show the pale base instead of the livery colour");
            }
            return problems;
        }

        // Colliders on different parts collide unless a PartJoint links the two parts (FixedJoint enableCollision = false, and
        // TelescopeController's ConfigurableJoints the same), and an overlap blows the aircraft apart. The stages slide, so the
        // check runs at each of CheckedExtensions, every stage moved that fraction of the way to its slide end.
        private static readonly float[] CheckedExtensions = { 0f, 0.25f, 0.5f, 0.75f, 1f };

        private static List<string> ColliderOverlaps(Build b)
        {
            var aeroType = GameType("AeroPart");
            var problems = new List<string>();
            Physics.SyncTransforms();
            var linked = new HashSet<(Object, Object)>();
            foreach (var part in b.Root.GetComponentsInChildren(aeroType, true))
            {
                var joints = new SerializedObject(part).FindProperty("joints");
                for (var i = 0; i < joints.arraySize; i++)
                {
                    var other = joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue;
                    linked.Add((part, other));
                    linked.Add((other, part));
                }
            }
            // The authored hulls are inset clear of each other, so the check proves it can see an overlap on a hull and
            // a copy of it 10 cm away.
            var probe = b.Root.GetComponent<MeshCollider>();
            if (probe == null || !Physics.ComputePenetration(probe, probe.transform.position, probe.transform.rotation, probe, probe.transform.position + Vector3.up * 0.1f, probe.transform.rotation, out _, out _))
                problems.Add("the overlap check can't see a fuselage hull overlapping a copy of itself; it would miss real overlaps");
            var colliders = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger)
                .Select(c => (collider: c, part: (Object)c.GetComponentInParent(aeroType, true))).ToArray();
            var slides = Parts.Where(p => b.Blockout.Slide(p.Name).HasValue).Select(p => b.Parts[p.Name].transform)
                .Select(t => (stage: t, rest: t.localPosition, end: t.parent.Find(t.name + "_extended").localPosition)).ToArray();
            foreach (var extension in CheckedExtensions)
            {
                foreach (var (stage, rest, end) in slides)
                    stage.localPosition = Vector3.Lerp(rest, end, extension);
                Physics.SyncTransforms();
                for (var i = 0; i < colliders.Length; i++)
                    for (var j = i + 1; j < colliders.Length; j++)
                    {
                        var (a, pa) = colliders[i];
                        var (c, pc) = colliders[j];
                        if (pa == pc || linked.Contains((pa, pc)) || !a.bounds.Intersects(c.bounds))
                            continue;
                        if (Physics.ComputePenetration(a, a.transform.position, a.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth) && depth > 0.005f)
                            problems.Add($"extension {extension:0.00}: collider overlap {depth:F3} m: {PathOf(a.transform, b.Root.transform)} ({pa.name}) and {PathOf(c.transform, b.Root.transform)} ({pc.name}); joint the parts or inset the hulls");
                    }
            }
            foreach (var (stage, rest, _) in slides)
                stage.localPosition = rest;
            Physics.SyncTransforms();
            b.Report.Add($"collider overlaps: {colliders.Length} colliders, {slides.Length} sliding stages, checked at extensions {string.Join(", ", CheckedExtensions)}: {problems.Count} problems");
            return problems;
        }

        private static void ReportParts(Build b, Component[] parts)
        {
            var cg = CenterOfMass(b);
            var station = OriginStation - (cg.z + b.Blockout.Origin.z);
            b.Report.Add($"parts: {parts.Length} AeroParts, {parts.Sum(p => new SerializedObject(p).FindProperty("mass").floatValue):0} kg empty, CG station {station:F2} m, height {cg.y + b.Blockout.Origin.y:F2} m above ground");
            foreach (var part in parts.OrderBy(p => PathOf(p.transform, b.Root.transform), StringComparer.Ordinal))
            {
                var so = new SerializedObject(part);
                var hulls = part.GetComponents<MeshCollider>();
                var collider = hulls.Length > 0 ? $"{hulls.Length} hulls {hulls.Sum(c => c.sharedMesh.triangles.Length / 3)} tris" : part.GetComponent<Collider>() != null ? part.GetComponent<Collider>().GetType().Name : "none";
                var joints = so.FindProperty("joints");
                var links = Enumerable.Range(0, joints.arraySize).Select(i => joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue?.name);
                b.Report.Add($"part {PathOf(part.transform, b.Root.transform)}: {so.FindProperty("mass").floatValue:0} kg, wing {so.FindProperty("wingArea").floatValue} m2, drag {so.FindProperty("dragArea").floatValue}, airfoil {so.FindProperty("airfoil").intValue}, collider {collider}, joints [{string.Join(", ", links)}]");
            }

            var np = NeutralPoint(b);
            b.Report.Add($"neutral point estimate station {OriginStation - (np + b.Blockout.Origin.z):F2} m; CG {station:F2} m; static margin {cg.z - np:F2} m; " +
                $"main gear {OriginStation - (b.Blockout.Local("wheel_LM").z + b.Blockout.Origin.z) - station:F2} m behind the CG");
        }

        // Static neutral point estimate (prefab z): lift-slope-weighted centre of the lifting parts, a canted
        // surface's share cut by the square of its normal's vertical component. A part's lift acts at its own centre of
        // mass, not at its lift transform: the simulating peer gives every part a Rigidbody (Aircraft.SetComplexPhysics)
        // and AeroPart.ApplyJobFields adds the force to it. No downwash or body terms.
        private static float NeutralPoint(Build b)
        {
            float sum = 0, weight = 0;
            foreach (var part in b.Root.GetComponentsInChildren(GameType("AeroPart"), true))
            {
                var so = new SerializedObject(part);
                var lift = (Transform)so.FindProperty("liftNormal").objectReferenceValue ?? part.transform;
                var com = (Transform)so.FindProperty("centerOfMass").objectReferenceValue ?? part.transform;
                var w = so.FindProperty("wingArea").floatValue * lift.up.y * lift.up.y;
                sum += w * com.position.z;
                weight += w;
            }
            return sum / weight;
        }

        private sealed class Leg
        {
            public string Name;
            public Vector3 Contact; // the wheel's bottom with the spring free, in prefab space
            public float Travel, Spring;
        }

        // Spawns the aircraft already sitting on its springs, as every geared stock definition does: its spawnOffset.y
        // is the root's height at rest on the gear (the Alkyon's 2.80 m against 2.81 computed this way, the SFB's 4.15
        // against 4.145) and its restRotation the pitch it rests at. The empty mass sits at the CG; the nose leg and the
        // main legs share it by lever arm, and each leg shortens by its load over springRate (LandingGear casts
        // suspensionTravel down from castPoint, or the bump stop). The ground line through the shortened contacts gives
        // the height under the root and the pitch. spawnOffset.z puts the blockout origin on the hangar spawn point.
        private static void SetRestPose(Build b, Object definition)
        {
            var legs = b.Root.GetComponentsInChildren(GameType("LandingGear"), true).Select(g =>
            {
                var so = new SerializedObject(g);
                var cast = Prop(so, "castPoint").objectReferenceValue as Transform;
                if (cast == null)
                    cast = ((GameObject)Prop(so, "bumpStop").objectReferenceValue).transform;
                var travel = Prop(so, "suspensionTravel").floatValue;
                return new Leg { Name = g.name, Contact = cast.position - cast.up * travel, Travel = travel, Spring = Prop(so, "springRate").floatValue };
            }).ToArray();
            var frontZ = legs.Max(l => l.Contact.z);
            var nose = legs.Where(l => l.Contact.z > frontZ - 0.5f).ToArray();
            var mains = legs.Except(nose).ToArray();
            if (mains.Length == 0)
                throw new InvalidDataException($"Expected main legs behind the nose leg; found {legs.Length} legs.");
            var noseZ = nose.Average(l => l.Contact.z);
            var mainZ = mains.Average(l => l.Contact.z);
            var noseShare = (CenterOfMass(b).z - mainZ) / (noseZ - mainZ);
            var weight = EmptyMass * 9.81f;
            var lines = new List<string>();
            float RestY(Leg[] group, float load) => group.Average(l =>
            {
                var compression = load / group.Length / l.Spring;
                if (compression >= l.Travel)
                    throw new InvalidDataException($"{l.Name} would bottom out at rest ({compression:F2} m of {l.Travel} m travel)");
                lines.Add($"{l.Name} {load / group.Length / 1000:0} kN, {compression:F3} m");
                return l.Contact.y + compression;
            });
            var noseY = RestY(nose, noseShare * weight);
            var mainY = RestY(mains, (1 - noseShare) * weight);
            var slope = (noseY - mainY) / (noseZ - mainZ);
            var height = slope * mainZ - mainY;
            var noseUp = Mathf.Atan(-slope) * Mathf.Rad2Deg;

            var def = new SerializedObject(definition);
            Prop(def, "spawnOffset").vector3Value = new Vector3(0, height, b.Blockout.Origin.z);
            Prop(def, "restRotation").vector3Value = new Vector3(-noseUp, 0, 0);
            def.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"rest pose: spawnOffset.y {height:F3} m, restRotation.x {-noseUp:F3} deg ({noseUp:F2} deg nose up); free wheels {-mains.Average(l => l.Contact.y):F3} m " +
                $"under the root; {noseShare:P1} of {EmptyMass / 1000:0} t on the nose; {string.Join("; ", lines)}");
        }

        // ---------- helpers ----------

        private static Bounds WorldBounds(Renderer renderer) => renderer.bounds;

        // A part's shape (PartMeshes.Shape) in world space: the bounds its renderer had on the blockout.
        private static Bounds ShapeBounds(Build b, string part)
        {
            var t = b.Parts[part].transform;
            var corners = Corners(b.Meshes[part].Shape.bounds).Select(t.TransformPoint).ToArray();
            var bounds = new Bounds(corners[0], Vector3.zero);
            foreach (var c in corners)
                bounds.Encapsulate(c);
            return bounds;
        }

        private static IEnumerable<Vector3> Corners(Bounds bounds)
        {
            for (var i = 0; i < 8; i++)
                yield return bounds.center + Vector3.Scale(bounds.extents, new Vector3((i & 1) == 0 ? -1 : 1, (i & 2) == 0 ? -1 : 1, (i & 4) == 0 ? -1 : 1));
        }

        // GetComponent's editor "null" is a live object to ??, so look it up with TryGetComponent.
        private static T Ensure<T>(GameObject go) where T : Component => go.TryGetComponent<T>(out var c) ? c : go.AddComponent<T>();

        private static Transform FindDeep(Transform root, string name) =>
            root.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == name) ?? throw new MissingReferenceException("No " + name + " under " + root.name);

        private static string PathOf(Transform t, Transform root)
        {
            var parts = new List<string>();
            for (var x = t; x != null && x != root; x = x.parent)
                parts.Add(x.name);
            parts.Reverse();
            return parts.Count == 0 ? root.name : string.Join("/", parts);
        }

        // A closed box between four coplanar corners, thickness along normal; front faces point outward.
        private static Mesh Slab(string name, Vector3[] corners, Vector3 normal, float thickness)
        {
            var half = normal.normalized * thickness / 2;
            var v = corners.Select(c => c + half).Concat(corners.Select(c => c - half)).ToArray();
            var quads = new[] { new[] { 0, 1, 2, 3 }, new[] { 7, 6, 5, 4 }, new[] { 0, 4, 5, 1 }, new[] { 1, 5, 6, 2 }, new[] { 2, 6, 7, 3 }, new[] { 3, 7, 4, 0 } };
            var centre = v.Aggregate(Vector3.zero, (s, p) => s + p) / v.Length;
            var tris = new List<int>();
            foreach (var q in quads)
                foreach (var tri in new[] { new[] { q[0], q[1], q[2] }, new[] { q[0], q[2], q[3] } })
                {
                    var faceCentre = (v[tri[0]] + v[tri[1]] + v[tri[2]]) / 3;
                    var n = Vector3.Cross(v[tri[1]] - v[tri[0]], v[tri[2]] - v[tri[0]]);
                    tris.AddRange(Vector3.Dot(n, faceCentre - centre) >= 0 ? tri : new[] { tri[0], tri[2], tri[1] });
                }
            var mesh = new Mesh { name = name, vertices = v, triangles = tris.ToArray() };
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        // Generated meshes written this run; Author deletes the rest of MeshFolder (a slab the blockout replaced).
        private static readonly HashSet<string> SavedMeshes = new HashSet<string>();

        private static Mesh SaveMesh(Mesh mesh)
        {
            var path = MeshFolder + "/" + mesh.name + ".asset";
            SavedMeshes.Add(path);
            return SaveAsset(mesh, path);
        }

        // Writes into an existing asset when there is one, so its GUID (and every reference to it) survives.
        private static T SaveAsset<T>(T fresh, string path) where T : Object
        {
            var existing = AssetDatabase.LoadMainAssetAtPath(path);
            if (existing == null)
            {
                AssetDatabase.CreateAsset(fresh, path);
                return fresh;
            }
            if (existing.GetType() != fresh.GetType())
                throw new InvalidDataException(path + " holds a " + existing.GetType().Name + ", not a " + fresh.GetType().Name);
            var name = fresh.name;
            EditorUtility.CopySerialized(fresh, existing);
            existing.name = name;
            EditorUtility.SetDirty(existing);
            Object.DestroyImmediate(fresh);
            return (T)existing;
        }

        // Blueprinter re-links each reference to a stock asset by hierarchy path through Transform.Find, which reaches only
        // the first of same-named siblings: a duplicate's stock references load null (the ARAD x8 rack's null WeaponInfo).
        private static GameObject SavePrefab(GameObject instance, string path)
        {
            var duplicate = instance.GetComponentsInChildren<Transform>(true)
                .GroupBy(t => AnimationUtility.CalculateTransformPath(t, instance.transform)).FirstOrDefault(g => g.Count() > 1);
            if (duplicate != null)
                throw new InvalidDataException(path + " has two transforms at '" + duplicate.Key + "'; Blueprinter would leave the second's stock references null");
            var prefab = PrefabUtility.SaveAsPrefabAsset(instance, path, out var success);
            if (!success)
                throw new InvalidOperationException("Could not save " + path);
            return prefab;
        }

        private static T Load<T>(string path) where T : Object =>
            AssetDatabase.LoadAssetAtPath<T>(path) ?? throw new FileNotFoundException("Missing asset", path);

        private static Type GameType(string name) =>
            Type.GetType(name + ", Assembly-CSharp") ?? throw new TypeLoadException("Game type " + name + " isn't loaded");

        private static SerializedProperty Prop(SerializedObject so, string path) =>
            so.FindProperty(path) ?? throw new MissingFieldException(so.targetObject.GetType().Name, path);

        private static void Set(Object target, string path, Object value)
        {
            var so = new SerializedObject(target);
            Prop(so, path).objectReferenceValue = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void Set(Object target, string path, float value)
        {
            var so = new SerializedObject(target);
            Num(Prop(so, path), value);
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void Set(Object target, string path, Vector3 value)
        {
            var so = new SerializedObject(target);
            Prop(so, path).vector3Value = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void Num(SerializedObject so, string path, double value) => Num(Prop(so, path), value);

        // Sets a number whether the game declares the field int or float.
        private static void Num(SerializedProperty property, double value)
        {
            if (property.propertyType == SerializedPropertyType.Integer)
                property.intValue = (int)Math.Round(value);
            else if (property.propertyType == SerializedPropertyType.Float)
                property.floatValue = (float)value;
            else
                throw new InvalidDataException(property.propertyPath + " is " + property.propertyType + ", not a number");
        }

        private static string Sha256(byte[] bytes)
        {
            using (var sha = System.Security.Cryptography.SHA256.Create())
                return string.Concat(sha.ComputeHash(bytes).Select(x => x.ToString("x2")));
        }

        // ---------- G1.5 identity check ----------

        // Batch entry for tools/Check-Identity.ps1: scans the built bundle and the authored assets for gate G1.5's
        // static parts. Prints one "[Centurion] G1.5 PASS" or "[Centurion] G1.5 FAIL" line.
        public static void CheckIdentity()
        {
            var problems = new List<string>();
            var notes = new List<string>();
            var info = JsonUtility.FromJson<ModInfoFile>(File.ReadAllText(ModFolder + "/modinfo.json"));
            var bundlePath = Path.Combine(RepoRoot, "build", "centurion_" + info.version + ".nobp");
            if (!File.Exists(bundlePath))
                throw new FileNotFoundException("Build first (tools/Build-Centurion.ps1).", bundlePath);

            // Names of every stock mesh, texture and sprite the export holds (the placeholders mirror it).
            var stockNames = new HashSet<string>(StringComparer.Ordinal);
            foreach (var folder in new[] { "Mesh", "Texture2D", "Sprite" })
                foreach (var file in Directory.GetFiles(Stock + folder, "*_PLACEHOLDER.*").Where(f => !f.EndsWith(".meta", StringComparison.Ordinal)))
                    stockNames.Add(Path.GetFileNameWithoutExtension(file).Replace("_PLACEHOLDER", ""));
            // Fingerprints of the donor's meshes, the likeliest thing to be copied by mistake: vertex count and
            // bounds (readable or not in the bundle), and a vertex hash where the bundle copy is readable.
            var donorHashes = new Dictionary<string, string>();
            foreach (var path in AssetDatabase.GetDependencies(DonorPrefab, true).Where(p => p.StartsWith(Stock + "Mesh/", StringComparison.Ordinal)))
                foreach (var mesh in AssetDatabase.LoadAllAssetsAtPath(path).OfType<Mesh>())
                {
                    donorHashes[MeshHash(mesh)] = mesh.name;
                    donorHashes[MeshShape(mesh)] = mesh.name;
                }

            AssetBundle.UnloadAllAssetBundles(true);
            var bundle = AssetBundle.LoadFromFile(bundlePath) ?? throw new InvalidDataException("Unity can't open " + bundlePath);
            try
            {
                var meshes = bundle.LoadAllAssets<Mesh>();
                var textures = bundle.LoadAllAssets<Texture>();
                foreach (var mesh in meshes)
                {
                    if (stockNames.Contains(mesh.name))
                        problems.Add("bundle mesh " + mesh.name + " has a stock name");
                    if (donorHashes.TryGetValue(MeshShape(mesh), out var shaped))
                        problems.Add("bundle mesh " + mesh.name + " has the vertex count and bounds of stock " + shaped);
                    else if (mesh.isReadable && donorHashes.TryGetValue(MeshHash(mesh), out var stock))
                        problems.Add("bundle mesh " + mesh.name + " has the vertices of stock " + stock);
                }
                foreach (var texture in textures)
                    if (stockNames.Contains(texture.name))
                        problems.Add("bundle texture " + texture.name + " has a stock name");
                notes.Add($"bundle holds {meshes.Length} meshes and {textures.Length} textures, none stock");

                var prefab = bundle.LoadAllAssets<GameObject>().FirstOrDefault(g => g.GetComponent(GameType("Aircraft")) != null)
                    ?? throw new InvalidDataException("The bundle holds no aircraft prefab.");
                var pilots = prefab.GetComponentsInChildren(GameType("Pilot"), true).Length;
                if (pilots < 1 || pilots > 2)
                    problems.Add(pilots + " pilot seats; G1.5 allows the pilot and at most one more");
                var swing = prefab.GetComponentsInChildren(GameType("SwingWingController"), true).Length;
                if (swing != 0)
                    problems.Add(swing + " SwingWingControllers");
                var sets = new SerializedObject(prefab.GetComponentInChildren(GameType("WeaponManager"), true)).FindProperty("hardpointSets").arraySize;
                var definition = new SerializedObject(new SerializedObject(prefab.GetComponent(GameType("Aircraft"))).FindProperty("definition").objectReferenceValue);
                var parameters = new SerializedObject(definition.FindProperty("aircraftParameters").objectReferenceValue);
                var lengths = new List<int>();
                var loadouts = parameters.FindProperty("loadouts");
                for (var i = 0; i < loadouts.arraySize; i++)
                    lengths.Add(loadouts.GetArrayElementAtIndex(i).FindPropertyRelative("weapons").arraySize);
                var standard = parameters.FindProperty("StandardLoadouts");
                for (var i = 0; i < standard.arraySize; i++)
                    lengths.Add(standard.GetArrayElementAtIndex(i).FindPropertyRelative("loadout").FindPropertyRelative("weapons").arraySize);
                if (lengths.Any(l => l != sets))
                    problems.Add($"loadout lengths [{string.Join(", ", lengths)}] against {sets} hardpoint sets");
                notes.Add($"{pilots} crew, {swing} SwingWingController, {sets} hardpoint sets, loadout lengths [{string.Join(", ", lengths)}]");
                notes.Add("definition " + definition.FindProperty("jsonKey").stringValue + " \"" + definition.FindProperty("unitName").stringValue + "\"");
                problems.AddRange(PartStructureCheck.Problems(prefab, notes));
                problems.AddRange(ControlMomentCheck.Problems(prefab, notes));
            }
            finally
            {
                bundle.Unload(true);
            }

            // Liveries and the status display are mod assets (authored source; the bundle's copies come from them).
            var source = new SerializedObject(Load<Object>(ParametersPath));
            var liveries = source.FindProperty("liveries");
            for (var i = 0; i < liveries.arraySize; i++)
            {
                var guid = liveries.GetArrayElementAtIndex(i).FindPropertyRelative("assetReference").FindPropertyRelative("m_AssetGUID").stringValue;
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (!path.StartsWith(ModFolder + "/", StringComparison.Ordinal))
                    problems.Add("livery " + i + " points outside the mod: " + (path == "" ? guid : path));
            }
            var status = AssetDatabase.GetAssetPath(source.FindProperty("StatusDisplay").objectReferenceValue);
            if (!status.StartsWith(ModFolder + "/", StringComparison.Ordinal))
                problems.Add("status display is " + status);
            notes.Add($"{liveries.arraySize} liveries and status display {status} in the mod folder");

            foreach (var note in notes)
                Debug.Log("[Centurion] G1.5 " + note);
            if (problems.Count > 0)
                Debug.Log("[Centurion] G1.5 FAIL: " + string.Join("; ", problems));
            else
                Debug.Log("[Centurion] G1.5 PASS: " + Path.GetFileName(bundlePath));
        }

        [Serializable]
        private sealed class ModInfoFile
        {
            public string version;
        }

        // Just enough JSON for blockout.json: objects as dictionaries, arrays as lists, numbers as doubles.
        private static class MiniJson
        {
            public static object Parse(string text)
            {
                var i = 0;
                var value = Value(text, ref i);
                Skip(text, ref i);
                if (i != text.Length)
                    throw new InvalidDataException("Trailing data in JSON at " + i);
                return value;
            }

            private static void Skip(string s, ref int i)
            {
                while (i < s.Length && char.IsWhiteSpace(s[i]))
                    i++;
            }

            private static object Value(string s, ref int i)
            {
                Skip(s, ref i);
                switch (s[i])
                {
                    case '{':
                        var obj = new Dictionary<string, object>();
                        i++;
                        Skip(s, ref i);
                        if (s[i] == '}') { i++; return obj; }
                        while (true)
                        {
                            Skip(s, ref i);
                            var key = (string)Value(s, ref i);
                            Skip(s, ref i);
                            Expect(s, ref i, ':');
                            obj[key] = Value(s, ref i);
                            Skip(s, ref i);
                            if (s[i] == '}') { i++; return obj; }
                            Expect(s, ref i, ',');
                        }
                    case '[':
                        var list = new List<object>();
                        i++;
                        Skip(s, ref i);
                        if (s[i] == ']') { i++; return list; }
                        while (true)
                        {
                            list.Add(Value(s, ref i));
                            Skip(s, ref i);
                            if (s[i] == ']') { i++; return list; }
                            Expect(s, ref i, ',');
                        }
                    case '"':
                        var sb = new StringBuilder();
                        i++;
                        while (s[i] != '"')
                        {
                            if (s[i] == '\\')
                            {
                                i++;
                                var c = s[i];
                                if (c == 'u') { sb.Append((char)Convert.ToInt32(s.Substring(i + 1, 4), 16)); i += 4; }
                                else sb.Append(c == 'n' ? '\n' : c == 't' ? '\t' : c == 'r' ? '\r' : c == 'b' ? '\b' : c == 'f' ? '\f' : c);
                            }
                            else
                            {
                                sb.Append(s[i]);
                            }
                            i++;
                        }
                        i++;
                        return sb.ToString();
                    default:
                        if (s.Substring(i).StartsWith("true", StringComparison.Ordinal)) { i += 4; return true; }
                        if (s.Substring(i).StartsWith("false", StringComparison.Ordinal)) { i += 5; return false; }
                        if (s.Substring(i).StartsWith("null", StringComparison.Ordinal)) { i += 4; return null; }
                        var start = i;
                        while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0)
                            i++;
                        if (start == i)
                            throw new InvalidDataException("Unexpected '" + s[i] + "' in JSON at " + i);
                        return double.Parse(s.Substring(start, i - start), System.Globalization.CultureInfo.InvariantCulture);
                }
            }

            private static void Expect(string s, ref int i, char c)
            {
                if (s[i] != c)
                    throw new InvalidDataException("Expected '" + c + "' in JSON at " + i);
                i++;
            }
        }

        private static string MeshShape(Mesh mesh) =>
            $"{mesh.vertexCount}|{mesh.bounds.center.x:F3},{mesh.bounds.center.y:F3},{mesh.bounds.center.z:F3}|{mesh.bounds.extents.x:F3},{mesh.bounds.extents.y:F3},{mesh.bounds.extents.z:F3}";

        private static string MeshHash(Mesh mesh)
        {
            var sb = new StringBuilder();
            foreach (var v in mesh.vertices)
                sb.Append(v.x.ToString("F4")).Append(',').Append(v.y.ToString("F4")).Append(',').Append(v.z.ToString("F4")).Append(';');
            return mesh.vertexCount + ":" + Sha256(Encoding.ASCII.GetBytes(sb.ToString()));
        }
    }
}
