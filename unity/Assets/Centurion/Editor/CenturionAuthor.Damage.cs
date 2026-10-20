using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    public static partial class CenturionAuthor
    {
        // Stock assigns fragments by role, not a mass threshold: Medusa's 900 kg fuselage uses large,
        // its 900 kg engines small; Darkreach's 3,155 kg nozzles small, its 3,556 kg engines medium.
        private static readonly (string Part, string Size)[] PartFragments =
        {
            ("fuselage_M", "large"), ("fuselage_F", "large"), ("fuselage_F2", "large"), ("fuselage_R", "large"),
            ("nose", "med"), ("cockpit", "med"), ("tailcone", "small"), ("tail_end", "small"),
            ("wing_root_L", "small"), ("wing_root_R", "small"), ("wing_outer_L", "small"), ("wing_outer_R", "small"),
            ("wing_tele1_L", "small"), ("wing_tele1_R", "small"),
            ("wing_tele2_L", "small"), ("wing_tele2_R", "small"), ("wing_tip_L", "small"), ("wing_tip_R", "small"),
            ("nacelle_1", "med"), ("nacelle_2", "med"),
            ("nozzle_1", "small"), ("nozzle_2", "small"),
            ("vtail_L", "small"), ("vtail_R", "small"), ("vtail_tip_L", "small"), ("vtail_tip_R", "small"),
            ("sponson_L", "small"), ("sponson_R", "small"), ("sponson_tail_L", "small"), ("sponson_tail_R", "small"),
            ("fuselage_F_upper", "small"), ("fuselage_F2_upper", "small"), ("fuselage_M_flank_L", "small"), ("fuselage_M_flank_R", "small"),
            ("fuselage_R_upper_L", "small"), ("fuselage_R_upper_R", "small"), ("tailcone_upper", "small"),
        };

        private static GameObject FragmentEffect(string size) =>
            Load<GameObject>(Stock + "GameObject/fragments_" + size + "_PLACEHOLDER.prefab");

        // How each part takes damage and holds on, in five classes after the stock bombers (Darkreach, Alkyon, EW1:
        // .cache/damage/stock_armour.py): armour subtracts from a hit and tolerance divides what gets through
        // (UnitPart.TakeDamage); a joint's strength falls with its part's hit points to nothing at the structural threshold
        // (AeroPart.ApplyDamage), from JointG times the weight the joint carries (at least JointFloor), which the game
        // multiplies by 10 (AeroPart.CreateJoints). Main box: the sections and wing roots that carry everything, tough as
        // the Darkreach's fuselage. Primary: the structure that carries aero or engine loads, the Darkreach's wings and
        // engines. Secondary: ends and fairings whose loss leaves the aircraft whole. Panel: the skin panels, cheeks,
        // flap-track fairings and wingtips, which carry no aero load and come off as their hit points run out, as the
        // stock tips and cheeks do. Surface: the control surfaces, the stock surfaces' armour on joints as strong as
        // before, since they carry their own aero load.
        private enum Toughness { MainBox, Primary, Secondary, Panel, Surface }

        // Skin must burn without shedding in the first 30 s. Fire tolerance leaves weapon and collision damage alone.
        private static bool IsSlowBurnSkin(string part) => PartToughness[part] == Toughness.Panel
            || part == "sponson_tail_L" || part == "sponson_tail_R" || part == "wingfairing" || part == "radar_F_fairing"
            || part == "tailcone_upper";
        private const float SkinFireTolerance = 40f;
        // Size for a tank host hit hard enough to ignite (49 HP) to hold its skin through the 20 s cook-off (owner: skin
        // need only last about 30 s): 16.5/6 HP/s takes its joints near zero around 27 s, while neighbouring tanks still
        // lose enough HP to puncture and catch fire.
        // The upper tail shell carries V-tail joints and sees up to 90 raw fire HP/s; at 100 it retains 64 HP at 40 s.
        private const float TankStructureFireTolerance = 6f;
        private const float TailShellFireTolerance = 100f;
        private static float? SlowBurnFireTolerance(string part) => part == "tailcone_upper" ? TailShellFireTolerance
            : IsSlowBurnSkin(part) ? SkinFireTolerance
            : part == "fuselage_M" || part == "fuselage_F" || part == "fuselage_R" || part == "tailcone"
                ? TankStructureFireTolerance : (float?)null;

        private static readonly Dictionary<Toughness, (float Pierce, float Blast, float PierceTolerance, float BlastTolerance, float Structural, float JointG, float JointFloor)> ToughnessValues =
            new Dictionary<Toughness, (float, float, float, float, float, float, float)>
            {
                { Toughness.MainBox, (20, 70, 30, 5, -25, 60, 2e5f) },
                { Toughness.Primary, (20, 70, 10, 5, -25, 60, 2e5f) },
                { Toughness.Secondary, (15, 60, 5, 3, -25, 30, 5e4f) },
                { Toughness.Panel, (10, 50, 3, 2, 0, 15, 2e4f) },
                { Toughness.Surface, (10, 40, 3, 2, 0, 60, 2e5f) },
            };

        private static readonly Dictionary<string, Toughness> PartToughness = new Dictionary<string, Toughness>
        {
            { "fuselage_M", Toughness.MainBox }, { "fuselage_F2", Toughness.MainBox }, { "fuselage_F", Toughness.MainBox },
            { "fuselage_R", Toughness.MainBox }, { "wing_root_L", Toughness.MainBox }, { "wing_root_R", Toughness.MainBox },
            { "cockpit", Toughness.MainBox },
            { "nose", Toughness.Primary }, { "tailcone", Toughness.Primary }, { "tailcone_upper", Toughness.Primary },
            { "sponson_L", Toughness.Primary }, { "sponson_R", Toughness.Primary },
            { "wing_outer_L", Toughness.Primary }, { "wing_outer_R", Toughness.Primary },
            { "wing_tele1_L", Toughness.Primary }, { "wing_tele1_R", Toughness.Primary },
            { "wing_tele2_L", Toughness.Primary }, { "wing_tele2_R", Toughness.Primary },
            { "strut_inner_L", Toughness.Primary }, { "strut_inner_R", Toughness.Primary },
            { "strut_outer_L", Toughness.Primary }, { "strut_outer_R", Toughness.Primary },
            { "pylon_1", Toughness.Primary }, { "pylon_2", Toughness.Primary },
            { "nacelle_1", Toughness.Primary }, { "nacelle_2", Toughness.Primary },
            { "vtail_L", Toughness.Primary }, { "vtail_R", Toughness.Primary },
            { "tail_end", Toughness.Secondary }, { "sponson_tail_L", Toughness.Secondary }, { "sponson_tail_R", Toughness.Secondary },
            { "vtail_tip_L", Toughness.Secondary }, { "vtail_tip_R", Toughness.Secondary },
            { "nozzle_1", Toughness.Secondary }, { "nozzle_2", Toughness.Secondary },
            { "radar_F_fairing", Toughness.Secondary }, { "wingfairing", Toughness.Secondary },
            { "fuselage_F_upper", Toughness.Panel }, { "fuselage_F2_upper", Toughness.Panel },
            { "fuselage_M_flank_L", Toughness.Panel }, { "fuselage_M_flank_R", Toughness.Panel },
            { "fuselage_R_upper_L", Toughness.Panel }, { "fuselage_R_upper_R", Toughness.Panel },
            { "tail_end_upper", Toughness.Panel }, { "cheek_L", Toughness.Panel }, { "cheek_R", Toughness.Panel },
            { "flap_track_L1", Toughness.Panel }, { "flap_track_L2", Toughness.Panel },
            { "flap_track_R1", Toughness.Panel }, { "flap_track_R2", Toughness.Panel },
            { "wing_tip_L", Toughness.Panel }, { "wing_tip_R", Toughness.Panel },
            { "flap_L1", Toughness.Surface }, { "flap_L2", Toughness.Surface }, { "flap_R1", Toughness.Surface }, { "flap_R2", Toughness.Surface },
            { "spoiler_L", Toughness.Surface }, { "spoiler_R", Toughness.Surface }, { "aileron_L", Toughness.Surface }, { "aileron_R", Toughness.Surface },
            { "ruddervator_L1", Toughness.Surface }, { "ruddervator_L2", Toughness.Surface },
            { "ruddervator_R1", Toughness.Surface }, { "ruddervator_R2", Toughness.Surface },
        };

        private static float JointForce(string part, float carriedKg)
        {
            var t = ToughnessValues[PartToughness[part]];
            return Mathf.Max(t.JointFloor, carriedKg * 9.81f * t.JointG);
        }

        // Where two parts meet: the middle of their colliders' common bounds (a cut piece's cut face, a section's joint
        // ring), or, where the bounds don't touch, of the gap between them; an empty under part named for the other.
        private static Transform JointAnchor(GameObject part, GameObject other)
        {
            Bounds BoundsOf(GameObject go) =>
                go.GetComponents<Collider>().Where(c => !(c is MeshCollider m && m.sharedMesh == null)).Select(c => c.bounds).Aggregate((a, c) => { a.Encapsulate(c); return a; });
            var a = BoundsOf(part);
            var o = BoundsOf(other);
            var lo = Vector3.Max(a.min, o.min);
            var hi = Vector3.Min(a.max, o.max);
            var name = "joint_" + other.name;
            var anchor = part.transform.Find(name);
            if (anchor == null)
                anchor = new GameObject(name) { layer = part.layer }.transform;
            anchor.SetParent(part.transform, false);
            anchor.position = (lo + hi) / 2;
            return anchor;
        }

        // Same-part FuelTanks follow these pivots. The aft fire must reach the tail's collider and vice versa. fuselage_F's
        // pivot is its old joint at station 17, inside fuselage_F2 since the part tree's cut at 12: it moves forward to its
        // tank's middle (station 9.95, art/blender/m4/body_structure.py TANKS), where its leaks and fires start.
        private static readonly (string Part, float Aft)[] TankPivotOffsets =
        {
            ("fuselage_F", -7.05f), ("fuselage_R", 5.5f), ("tailcone", 0.5f),
        };

        private static void PlaceBodyTanks(Build b)
        {
            foreach (var entry in TankPivotOffsets)
            {
                var go = b.Parts[entry.Part];
                if (go.transform.lossyScale != Vector3.one || Quaternion.Angle(go.transform.rotation, Quaternion.identity) > 0.001f)
                    throw new InvalidDataException(entry.Part + " tank pivot requires an axis-aligned, unit-scale part");
                var children = go.transform.Cast<Transform>().Select(t => (Transform: t, Position: t.position)).ToArray();
                var offset = new Vector3(0, 0, -entry.Aft);
                var meshes = new Dictionary<Mesh, Mesh>();
                Mesh Shift(Mesh source)
                {
                    if (meshes.TryGetValue(source, out var saved)) return saved;
                    var shifted = Object.Instantiate(source);
                    shifted.name = entry.Part + "_tank_origin_" + source.name;
                    shifted.vertices = source.vertices.Select(v => v - offset).ToArray();
                    shifted.RecalculateBounds();
                    saved = SaveMesh(shifted);
                    meshes.Add(source, saved);
                    return saved;
                }
                var cg = CenterOfMass(b);
                go.GetComponent<MeshFilter>().sharedMesh = Shift(go.GetComponent<MeshFilter>().sharedMesh);
                foreach (var collider in go.GetComponents<MeshCollider>())
                    collider.sharedMesh = Shift(collider.sharedMesh);
                go.transform.position += offset;
                foreach (var child in children) child.Transform.position = child.Position;
                if (Vector3.Distance(cg, CenterOfMass(b)) > 0.0001f
                    || children.Any(c => Vector3.Distance(c.Transform.position, c.Position) > 0.0001f))
                    throw new InvalidDataException(entry.Part + " tank pivot changed the CG or a child position");
                foreach (var pair in meshes)
                {
                    var original = pair.Key.vertices;
                    var shifted = pair.Value.vertices;
                    if (original.Length != shifted.Length
                        || original.Where((v, i) => (v - shifted[i] - offset).magnitude > 0.0001f).Any())
                        throw new InvalidDataException(entry.Part + " tank pivot changed mesh geometry");
                }
            }
        }

        private static void AuthorDamage(Build b)
        {
            // All systems and LODs are in place, but joints have not yet been authored at the final pivots.
            PlaceBodyTanks(b);
            foreach (var entry in b.Parts)
            {
                var so = new SerializedObject(b.Part(entry.Key));
                var effects = Prop(so, "disintegrationEffects");
                effects.arraySize = 0;
                foreach (var fragment in PartFragments.Where(f => f.Part == entry.Key))
                {
                    effects.arraySize++;
                    effects.GetArrayElementAtIndex(effects.arraySize - 1).objectReferenceValue = FragmentEffect(fragment.Size);
                }
                var t = ToughnessValues[PartToughness[entry.Key]];
                Prop(so, "armorProperties.pierceArmor").floatValue = t.Pierce;
                Prop(so, "armorProperties.blastArmor").floatValue = t.Blast;
                Prop(so, "armorProperties.pierceTolerance").floatValue = t.PierceTolerance;
                Prop(so, "armorProperties.blastTolerance").floatValue = t.BlastTolerance;
                if (SlowBurnFireTolerance(entry.Key) is float fireTolerance)
                {
                    Prop(so, "armorProperties.fireArmor").floatValue = 0f;
                    Prop(so, "armorProperties.fireTolerance").floatValue = fireTolerance;
                }
                Prop(so, "structuralThreshold").floatValue = t.Structural;
                so.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        private static void CheckDamage(Build b)
        {
            var parts = b.Root.GetComponentsInChildren(GameType("AeroPart"), true);
            if (PartFragments.Length * 35 < parts.Length * 14)
                throw new InvalidDataException("Fragment coverage must reach Darkreach's 14/35 parts");
            foreach (var fragment in PartFragments)
            {
                var effects = Prop(new SerializedObject(b.Part(fragment.Part)), "disintegrationEffects");
                if (effects.arraySize != 1 || effects.GetArrayElementAtIndex(0).objectReferenceValue != FragmentEffect(fragment.Size))
                    throw new InvalidDataException(fragment.Part + " requires fragments_" + fragment.Size + " placeholder reference");
            }
            CheckToughness(b, parts);
            CheckPartTree(b, parts);
            // Sliding stages occupy the inner wings. Fuel stays in the body, with no cross-tank leak connections.
            var layout = new[] { (Part: "fuselage_M", Kg: 15000f), (Part: "fuselage_F", Kg: 3000f),
                (Part: "fuselage_R", Kg: 3000f), (Part: "tailcone", Kg: 3000f) };
            foreach (var entry in layout)
            {
                var part = b.Part(entry.Part);
                var tanks = part.GetComponents(GameType("FuelTank"));
                if (tanks.Length != 1)
                    throw new InvalidDataException(entry.Part + " requires one same-part FuelTank");
                var so = new SerializedObject(tanks[0]);
                if (Prop(so, "part").objectReferenceValue != part || Prop(so, "fuelCapacity").floatValue != entry.Kg
                    || Prop(so, "connectedTanks").arraySize != 0)
                    throw new InvalidDataException(entry.Part + " requires an independent " + entry.Kg + " kg tank on its AeroPart");
            }
            var allTanks = b.Root.GetComponentsInChildren(GameType("FuelTank"), true);
            if (allTanks.Length != layout.Length || allTanks.Sum(t => Prop(new SerializedObject(t), "fuelCapacity").floatValue) != 24000f)
                throw new InvalidDataException("Centurion requires four body tanks with 24000 kg total capacity and no wing tanks");
            Physics.SyncTransforms();
            foreach (var source in layout)
            {
                var part = b.Part(source.Part);
                var extents = part.GetComponent<Collider>().bounds.extents;
                var radius = (extents.x + extents.y + extents.z) * 0.33333f * 1.5f;
                foreach (var target in layout)
                {
                    var distance = b.Part(target.Part).GetComponents<Collider>()
                        .Min(c => Vector3.Distance(part.transform.position, c.ClosestPoint(part.transform.position)));
                    var reaches = distance <= radius;
                    if ((source.Part == "fuselage_R" && target.Part == "tailcone"
                        || source.Part == "tailcone" && target.Part == "fuselage_R") && !reaches)
                        throw new InvalidDataException(source.Part + " fire must reach " + target.Part);
                    b.Report.Add($"Tank fire reach: {source.Part} -> {target.Part}: radius {radius:F3} m, collider distance {distance:F3} m, reaches {reaches}");
                }
            }
            b.Report.Add($"Damage checks passed: fragments {PartFragments.Length}/{parts.Length}; 4 same-part body tanks, 24000 kg; fuselage_M 15000, fuselage_F 3000, fuselage_R 3000, tailcone 3000; no wing tanks");
        }

        // Every AeroPart has a toughness class and carries its armour, threshold and joint strengths; no two joints link
        // the same pair of parts.
        private static void CheckToughness(Build b, Component[] parts)
        {
            var aeroType = GameType("AeroPart");
            var pairs = new HashSet<(Object, Object)>();
            foreach (var part in parts)
            {
                var name = b.Parts.First(p => p.Value == part.gameObject).Key;
                if (!PartToughness.TryGetValue(name, out var cls))
                    throw new InvalidDataException(name + " has no toughness class (PartToughness)");
                var t = ToughnessValues[cls];
                var so = new SerializedObject(part);
                if (Prop(so, "armorProperties.pierceArmor").floatValue != t.Pierce || Prop(so, "armorProperties.blastArmor").floatValue != t.Blast
                    || Prop(so, "armorProperties.pierceTolerance").floatValue != t.PierceTolerance || Prop(so, "armorProperties.blastTolerance").floatValue != t.BlastTolerance
                    || Prop(so, "structuralThreshold").floatValue != t.Structural)
                    throw new InvalidDataException($"{name} doesn't carry its {cls} armour");
                if (SlowBurnFireTolerance(name) is float fireTolerance && (Prop(so, "armorProperties.fireArmor").floatValue != 0f
                    || Prop(so, "armorProperties.fireTolerance").floatValue != fireTolerance))
                    throw new InvalidDataException(name + " requires fire armour 0 and fire tolerance " + fireTolerance);
                var carried = part.GetComponentsInChildren(aeroType, true).Sum(p => new SerializedObject(p).FindProperty("mass").floatValue);
                var joints = Prop(so, "joints");
                for (var i = 0; i < joints.arraySize; i++)
                {
                    var joint = joints.GetArrayElementAtIndex(i);
                    var other = joint.FindPropertyRelative("connectedPart").objectReferenceValue;
                    if (!pairs.Add((part, other)) || !pairs.Add((other, part)))
                        throw new InvalidDataException($"{name} has a second joint to {other.name}");
                    if (Mathf.Abs(joint.FindPropertyRelative("breakForce").floatValue - JointForce(name, carried)) > 1f
                        || joint.FindPropertyRelative("anchor").objectReferenceValue == null)
                        throw new InvalidDataException($"{name}'s joint to {other.name} isn't its {cls} strength at its anchor");
                }
                b.Report.Add($"toughness {name}: {cls}, armour {t.Pierce}/{t.Blast}, tolerance {t.PierceTolerance}/{t.BlastTolerance}, structural {t.Structural}, joints {JointForce(name, carried):0} N (x10 in game) for {carried:0} kg carried");
            }
        }

        // The part tree as the blockout cut it (art/blender/part_splits.py): every blockout part with a mass is an AeroPart
        // or a visual piece on the part that carries its mass, and each cut part's pieces carry the whole's area and moment.
        private static void CheckPartTree(Build b, Component[] parts)
        {
            var names = new HashSet<string>(parts.Select(p => b.Parts.First(e => e.Value == p.gameObject).Key));
            foreach (var part in b.Blockout.Parts.Values.Where(p => p.Props.ContainsKey("mass_kg")))
            {
                var visual = VisualPieces.Any(v => v.Piece == part.Name);
                if (names.Contains(part.Name) == visual)
                    throw new InvalidDataException($"{part.Name} is {(visual ? "both a visual piece and an AeroPart" : "neither an AeroPart nor a visual piece")}");
            }
            foreach (var group in CutParts)
            {
                var whole = Parts.Single(p => p.Name == group[0]);
                var sos = group.Select(n => new SerializedObject(b.Part(n))).ToArray();
                var area = sos.Sum(so => so.FindProperty("wingArea").floatValue);
                var drag = sos.Sum(so => so.FindProperty("dragArea").floatValue);
                if (Mathf.Abs(area - whole.WingArea) > 0.001f || Mathf.Abs(drag - whole.DragArea) > 0.001f)
                    throw new InvalidDataException($"{string.Join(" + ", group)} carry {area} m2 and {drag} drag, not {whole.Name}'s {whole.WingArea} and {whole.DragArea}");
            }
            b.Report.Add($"part tree: {names.Count} AeroParts, visual pieces {string.Join(", ", VisualPieces.Select(v => v.Piece + " on " + v.Part))}; cut parts keep their area and drag: {string.Join("; ", CutParts.Select(g => string.Join(" + ", g)))}");
        }
    }
}
