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
            ("fuselage_M", "large"), ("fuselage_F", "large"), ("fuselage_R", "large"),
            ("nose", "med"), ("cockpit", "med"), ("tailcone", "small"),
            ("wing_root_L", "small"), ("wing_root_R", "small"),
            ("wing_tele1_L", "small"), ("wing_tele1_R", "small"),
            ("wing_tele2_L", "small"), ("wing_tele2_R", "small"),
            ("nacelle_1", "med"), ("nacelle_2", "med"),
            ("nozzle_1", "small"), ("nozzle_2", "small"),
            ("vtail_L", "small"), ("vtail_R", "small"),
            ("sponson_L", "small"), ("sponson_R", "small"),
        };

        private static GameObject FragmentEffect(string size) =>
            Load<GameObject>(Stock + "GameObject/fragments_" + size + "_PLACEHOLDER.prefab");

        // Same-part FuelTanks follow these pivots. The aft fire must reach the tail's collider and vice versa.
        private static readonly (string Part, float Aft)[] TankPivotOffsets =
        {
            ("fuselage_R", 5.5f), ("tailcone", 0.5f),
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
    }
}
