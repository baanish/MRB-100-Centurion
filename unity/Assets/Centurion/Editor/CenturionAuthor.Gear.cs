using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Centurion.Editor
{
    public static partial class CenturionAuthor
    {
        // BuildGear's last step: suspension limits, then the art's folding and wheel rig.
        private static void RigGearAsArt(Build b)
        {
            // More runway stroke, with extra nose room during derotation.
            foreach (var gearName in new[] { "gear_L", "gear_R", "gear_F" })
            {
                var gear = FindDeep(b.Root.transform, gearName);
                var so = new SerializedObject(gear.GetComponent(GameType("LandingGear")));
                var limit = gearName == "gear_F" ? 0.90f : 0.80f;
                if (limit >= Prop(so, "suspensionTravel").floatValue)
                    throw new InvalidDataException($"{gearName}: compression limit {limit} must leave suspension travel.");
                Prop(so, "maxCompression").floatValue = limit;
                so.ApplyModifiedPropertiesWithoutUndo();
                b.Report.Add($"gear {gearName}: max compression {limit} m");
            }
            FoldNoseLegAsArt(b);
            SpinMainWheels(b, "gear_L", "wheel_LM");
            SpinMainWheels(b, "gear_R", "wheel_RM");
        }

        // The nose leg folds as the art retracts it (art/blender/m4/gear.py nose_fit: NoseRetractDeg forward and up about
        // gear_F's origin, an axis across the aircraft) into the well the nose doors close under, ahead of the forward
        // bay. The donor's fold (92 degrees aft about its own hinge 0.63 m higher, shifted by hingeFoldMotion) put the
        // wheels 0.63 m through the bay's front wall at station 7.4. The hinge moves onto the art's pivot with the leg kept
        // where it stands, so the rest pose and bump stop don't change.
        private const float NoseRetractDeg = 128f; // art/blender/m4/gear.py NOSE_RETRACT_DEG
        private static void FoldNoseLegAsArt(Build b)
        {
            var gear = FindDeep(b.Root.transform, "gear_F");
            var so = new SerializedObject(gear.GetComponent(GameType("LandingGear")));
            var hinge = (Transform)Prop(so, "gearHinge").objectReferenceValue;
            var pivot = b.Blockout.Local("gear_F");
            if (Mathf.Abs(Vector3.Dot(hinge.right, Vector3.right)) < 0.999f)
                throw new InvalidDataException($"gear_F: the fold hinge's axis {hinge.right} isn't across the aircraft, as the art's is.");
            var held = hinge.Cast<Transform>().Select(t => (t, t.position, t.rotation)).ToArray();
            hinge.position = pivot;
            foreach (var (t, position, rotation) in held)
                t.SetPositionAndRotation(position, rotation);
            var wheel = b.Blockout.Local("wheel_F") - pivot;
            var degrees = (Quaternion.AngleAxis(NoseRetractDeg, hinge.right) * wheel).z > wheel.z ? NoseRetractDeg : -NoseRetractDeg;
            Prop(so, "foldDegrees").floatValue = degrees;
            Prop(so, "hingeFoldMotion").vector3Value = Vector3.zero;
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"gear gear_F folds {degrees} deg about {pivot} (the art's hinge), wheels forward");
        }

        // The stock chock pair (two blocks and the tie ropes between them, at z 0) came sized to the Alkyon's wheels and
        // floated inside the Centurion's in the selection preview (AircraftSelectionMenu, Aircraft.ShowGroundEquipment). Each
        // pair stands on the ground under its wheel's centre, half the wheel radius tall, with every block vertex 2 cm clear
        // of the front and rear tyre rows and the ropes 3 cm clear of the tyres' sides.
        private static void PlaceChocks(Build b, Transform gear, string blockoutWheel, float radius)
        {
            var chocks = gear.GetComponentsInChildren<Transform>(true).Single(t => t.name == "chocks");
            var vertices = chocks.GetComponent<MeshFilter>().sharedMesh.vertices;
            var ropes = vertices.Where(v => Mathf.Abs(v.z) < 0.05f).ToArray();
            var blocks = vertices.Except(ropes).ToArray();
            var wheel = b.Blockout.Parts[blockoutWheel];
            var rows = Mathf.Max(-wheel.Min.z, wheel.Max.z) - radius; // the outer axles' distance from the wheel's centre
            var sy = 0.5f * radius / vertices.Max(v => v.y);
            float TyreFront(float height) => Mathf.Sqrt(radius * radius - (radius - height) * (radius - height));
            var sz = blocks.Max(v => (rows + TyreFront(v.y * sy) + 0.02f) / Mathf.Abs(v.z));
            var sx = (Mathf.Max(-wheel.Min.x, wheel.Max.x) + 0.03f) / ropes.Min(v => Mathf.Abs(v.x));
            chocks.SetPositionAndRotation(b.Blockout.Local(blockoutWheel) - Vector3.up * radius, b.Root.transform.rotation);
            chocks.localScale = new Vector3(sx, sy, sz);
            b.Report.Add($"chocks under {blockoutWheel} at {chocks.position}, scale {chocks.localScale}");
        }

        // LandingGear rolls each transform in its wheels list about its own local X at ground speed over the wheel radius.
        // The nose's wheel mesh hangs under the donor's wheel_F, which is on that list, but each main bogie's six wheels
        // come in one mesh with its beam (art/blender/m4/gear.py build_main), hung under the unsprung leg, which doesn't
        // turn, and the list held the donor's two emptied wheels. So each wheel, one closed shell in that mesh, moves onto
        // its own transform on its axle, local X along the axle to the right as the donor's wheels, and those are the list.
        private static void SpinMainWheels(Build b, string gearName, string blockoutWheel)
        {
            var gear = FindDeep(b.Root.transform, gearName);
            var so = new SerializedObject(gear.GetComponent(GameType("LandingGear")));
            var radius = Prop(so, "wheelRadius").floatValue;
            var bogie = b.Visuals[blockoutWheel];
            var mesh = bogie.GetComponent<MeshFilter>().sharedMesh;
            var materials = bogie.GetComponent<MeshRenderer>().sharedMaterials;
            var vertices = mesh.vertices;

            // Shells: vertices joined by triangles, welded by position across the importer's UV and normal splits.
            var shell = new int[vertices.Length];
            var first = new Dictionary<Vector3, int>();
            for (var i = 0; i < vertices.Length; i++)
                shell[i] = first.TryGetValue(vertices[i], out var same) ? same : (first[vertices[i]] = i);
            int Shell(int i)
            {
                while (shell[i] != i)
                    i = shell[i] = shell[shell[i]];
                return i;
            }
            for (var s = 0; s < mesh.subMeshCount; s++)
            {
                var triangles = mesh.GetTriangles(s);
                for (var k = 0; k < triangles.Length; k += 3)
                {
                    shell[Shell(triangles[k + 1])] = Shell(triangles[k]);
                    shell[Shell(triangles[k + 2])] = Shell(triangles[k]);
                }
            }
            var bounds = new Dictionary<int, Bounds>();
            for (var i = 0; i < vertices.Length; i++)
            {
                var point = bogie.TransformPoint(vertices[i]);
                var root = Shell(i);
                if (bounds.TryGetValue(root, out var box))
                    box.Encapsulate(point);
                else
                    box = new Bounds(point, Vector3.zero);
                bounds[root] = box;
            }

            // A wheel is a disc the wheel radius round an axle across the aircraft.
            bool Fits(float size) => Mathf.Abs(size - 2 * radius) < 0.05f * radius;
            var wheels = bounds.Where(s => Fits(s.Value.size.y) && Fits(s.Value.size.z) && s.Value.size.x < radius)
                .OrderBy(s => -s.Value.center.z).ThenBy(s => s.Value.center.x).ToArray();
            if (wheels.Length == 0)
                throw new InvalidDataException($"{blockoutWheel}: no wheel {2 * radius} m across in its mesh to turn.");
            var spinning = new List<Transform>();
            foreach (var (root, box) in wheels.Select(s => (s.Key, s.Value)))
            {
                var wheel = new GameObject($"{blockoutWheel}_{spinning.Count + 1}") { layer = b.Root.layer }.transform;
                wheel.SetParent(bogie, false);
                wheel.SetPositionAndRotation(box.center, b.Root.transform.rotation);
                var (piece, pieceMaterials) = MeshPiece(mesh, materials, wheel.name, i => Shell(i) == root, wheel.worldToLocalMatrix * bogie.localToWorldMatrix);
                wheel.gameObject.AddComponent<MeshFilter>().sharedMesh = piece;
                wheel.gameObject.AddComponent<MeshRenderer>().sharedMaterials = pieceMaterials;
                spinning.Add(wheel);
            }
            var turning = new HashSet<int>(wheels.Select(s => s.Key));
            var (rest, restMaterials) = MeshPiece(mesh, materials, blockoutWheel + "_bogie", i => !turning.Contains(Shell(i)), Matrix4x4.identity);
            bogie.GetComponent<MeshFilter>().sharedMesh = rest;
            bogie.GetComponent<MeshRenderer>().sharedMaterials = restMaterials;

            var list = Prop(so, "wheels");
            list.arraySize = spinning.Count;
            for (var i = 0; i < spinning.Count; i++)
                list.GetArrayElementAtIndex(i).objectReferenceValue = spinning[i];
            if (Prop(so, "dust").objectReferenceValue == null)
                throw new InvalidDataException($"{gearName}: LandingGear takes its dust from wheels[0] when it has none, and the new wheels carry none.");
            so.ApplyModifiedPropertiesWithoutUndo();
            b.Report.Add($"gear {gearName}: {spinning.Count} wheels turn on their axles, " +
                string.Join(", ", spinning.Select(w => w.position.ToString("F2"))));
        }

        // The triangles whose first corner keep takes, out of every submesh, as a saved mesh in the space toLocal maps
        // into, with the materials of the submeshes it keeps.
        private static (Mesh mesh, Material[] materials) MeshPiece(Mesh source, Material[] materials, string name, Func<int, bool> keep, Matrix4x4 toLocal)
        {
            var map = new Dictionary<int, int>();
            var submeshes = new List<int[]>();
            var kept = new List<Material>();
            for (var s = 0; s < source.subMeshCount; s++)
            {
                var triangles = source.GetTriangles(s);
                var picked = new List<int>();
                for (var k = 0; k < triangles.Length; k += 3)
                {
                    if (!keep(triangles[k]))
                        continue;
                    for (var c = k; c < k + 3; c++)
                    {
                        if (!map.TryGetValue(triangles[c], out var index))
                            map[triangles[c]] = index = map.Count;
                        picked.Add(index);
                    }
                }
                if (picked.Count == 0)
                    continue;
                submeshes.Add(picked.ToArray());
                kept.Add(materials[s]);
            }
            var order = map.OrderBy(m => m.Value).Select(m => m.Key).ToArray();
            var vertices = source.vertices;
            var normals = source.normals;
            var tangents = source.tangents;
            var uv = source.uv;
            var colors = source.colors;
            var piece = new Mesh { name = name, indexFormat = source.indexFormat };
            piece.vertices = order.Select(i => toLocal.MultiplyPoint3x4(vertices[i])).ToArray();
            if (normals.Length > 0)
                piece.normals = order.Select(i => toLocal.MultiplyVector(normals[i])).ToArray();
            if (tangents.Length > 0)
                piece.tangents = order.Select(i =>
                {
                    var t = toLocal.MultiplyVector(tangents[i]);
                    return new Vector4(t.x, t.y, t.z, tangents[i].w);
                }).ToArray();
            if (uv.Length > 0)
                piece.uv = order.Select(i => uv[i]).ToArray();
            if (colors.Length > 0)
                piece.colors = order.Select(i => colors[i]).ToArray();
            piece.subMeshCount = submeshes.Count;
            for (var s = 0; s < submeshes.Count; s++)
                piece.SetTriangles(submeshes[s], s);
            piece.RecalculateBounds();
            return (SaveMesh(piece), kept.ToArray());
        }
    }
}
