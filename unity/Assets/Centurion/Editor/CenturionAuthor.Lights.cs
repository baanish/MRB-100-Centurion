using System;
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
        // Each tip's nav light is the lens modelled on it (art/blender/m4/wing.py build_tip, NAV_LENS: wing_tele2's
        // light_red or light_green submesh). The donor's lamp was shaped for the Alkyon's tip and hung in two strips 2 to
        // 15 cm off this one (owner, build 33: "floating nav lights"). NavLights lights only its entry's own renderer, so
        // the lens moves off the stage's mesh onto that renderer, and the lamp's glow and light sit just off the lens.
        private const float NavGlowOut = 0.02f;

        private static void PlaceWingtipLights(Build b)
        {
            foreach (var side in new[] { "L", "R" })
            {
                var stage = b.Parts["wing_tele2_" + side].transform;
                var meshes = b.Meshes[stage.name];
                var filter = stage.GetComponent<MeshFilter>();
                var lensMaterial = Load<Material>(SlotMaterials[side == "L" ? "light_red" : "light_green"]);
                var lens = Array.IndexOf(meshes.Materials, lensMaterial);
                if (filter == null || filter.sharedMesh != meshes.Render || lens < 0)
                    throw new InvalidDataException($"{stage.name}: no {lensMaterial.name} submesh on its own renderer; the tip's nav lens is missing.");

                var source = meshes.Render;
                var keep = Enumerable.Range(0, source.subMeshCount).Where(s => s != lens).ToArray();
                var rest = Object.Instantiate(source);
                rest.name = source.name + "_nolens";
                rest.subMeshCount = keep.Length;
                for (var s = 0; s < keep.Length; s++)
                    rest.SetTriangles(source.GetTriangles(keep[s]), s, false);
                meshes.Render = SaveMesh(rest);
                meshes.Materials = keep.Select(s => meshes.Materials[s]).ToArray();
                filter.sharedMesh = meshes.Render;
                stage.GetComponent<MeshRenderer>().sharedMaterials = meshes.Materials;

                var triangles = source.GetTriangles(lens);
                var used = triangles.Distinct().ToArray();
                var index = used.Select((v, i) => (v, i)).ToDictionary(p => p.v, p => p.i);
                var vertices = source.vertices;
                var normals = source.normals;
                var uv = source.uv;
                var lensMesh = new Mesh { name = "navlight_" + side + "_lens", vertices = used.Select(v => vertices[v]).ToArray() };
                if (normals.Length > 0)
                    lensMesh.normals = used.Select(v => normals[v]).ToArray();
                if (uv.Length > 0)
                    lensMesh.uv = used.Select(v => uv[v]).ToArray();
                lensMesh.triangles = triangles.Select(v => index[v]).ToArray();
                lensMesh.RecalculateBounds();

                var nav = stage.Find("navlight_" + side);
                var glow = nav.Find("navlight_" + side + "_effects");
                var glowRotation = glow.rotation;
                nav.localPosition = Vector3.zero;
                nav.localRotation = Quaternion.identity;
                nav.localScale = Vector3.one;
                nav.GetComponent<MeshFilter>().sharedMesh = SaveMesh(lensMesh);
                // The glow and light just off the lens's crown, along its mean vertex normal: the lens is a closed shell,
                // so its face normals sum to zero.
                var outward = normals.Length == 0 ? Vector3.zero : used.Aggregate(Vector3.zero, (s, v) => s + normals[v]) / used.Length;
                if (outward.magnitude < 0.05f)
                    throw new InvalidDataException($"{stage.name}: the nav lens has no outward direction (mean vertex normal {outward}), so its glow can't be placed.");
                outward.Normalize();
                var crown = used.Select(v => vertices[v]).OrderByDescending(v => Vector3.Dot(v, outward)).First();
                glow.SetPositionAndRotation(stage.TransformPoint(crown + outward * NavGlowOut), glowRotation);
                b.Report.Add($"nav light {side}: the tip's lens, {triangles.Length / 3} triangles, glow at {glow.position} facing {stage.TransformDirection(outward)}");
            }
        }

        // The NavLights entry that switches a light, found by its renderer.
        private static SerializedProperty NavLightEntry(SerializedObject navLights, Renderer light)
        {
            var lights = Prop(navLights, "navLights");
            return Enumerable.Range(0, lights.arraySize).Select(lights.GetArrayElementAtIndex)
                .Single(e => e.FindPropertyRelative("renderer").objectReferenceValue == light);
        }

        // The donor's gear light (a spot light and its glow, NavLights' first entry) stayed at the Alkyon's offset on the
        // leg, on top of the Centurion's nose tyre. It moves onto the taxi lamp, the top lamp on the nose leg's light bar
        // (art/blender/m4/gear.py build_nose): 0.17 m ahead of gear_F's origin, 1.31 m above the ground, aimed 4 degrees
        // down, with the light on the lens 8 cm out along the aim.
        private const float TaxiLampAhead = 0.17f, TaxiLampHeight = 1.31f, TaxiLampLens = 0.08f;
        private static readonly Vector3 TaxiLampAim = new Vector3(0, -0.07f, 1).normalized;

        private static void PlaceTaxiLight(Build b)
        {
            var light = FindDeep(b.Root.transform, "gearlight_F");
            var lamp = new Vector3(0, TaxiLampHeight - b.Blockout.Origin.y, b.Blockout.Local("gear_F").z + TaxiLampAhead);
            light.SetPositionAndRotation(lamp + TaxiLampAim * TaxiLampLens, Quaternion.LookRotation(TaxiLampAim, Vector3.up));
            b.Report.Add($"taxi light on the nose leg's lamp bar at {light.position}, aimed {light.forward}");
        }

        // Every light stands on the aircraft: each connected piece of a light mesh (a submesh in a light material, or a
        // nav light's renderer) touches a face that is not a light, with a vertex within LightContactM of it or an edge
        // through it (a lens ring buried in its base, a strip's sides through the skin). Pieces are joined through shared
        // positions, since the importer splits vertices at hard edges. The donor's wingtip lamp stood 2 to 15 cm off the
        // new tip in build 33 and nothing failed.
        private const float LightContactM = 0.005f;

        private static void CheckLightsOnSkin(Build b)
        {
            var lightMaterials = new HashSet<Material>(new[] { "navlight_L", "navlight_R", "light_red_off", "light_green_off", "gearLight" }
                .Select(l => AssetDatabase.LoadAssetAtPath<Material>(Stock + "Material/" + l + "_PLACEHOLDER.mat")).Where(m => m != null));
            var pieces = new List<(string Where, Vector3[] Tris)>();
            var other = new List<Vector3>();
            foreach (var renderer in b.Root.GetComponentsInChildren<MeshRenderer>(true).Where(r => !b.Lod1.Contains(r)))
            {
                var mesh = renderer.GetComponent<MeshFilter>()?.sharedMesh;
                if (mesh == null)
                    continue;
                var world = mesh.vertices.Select(renderer.transform.TransformPoint).ToArray();
                var materials = renderer.sharedMaterials;
                for (var s = 0; s < mesh.subMeshCount; s++)
                {
                    var tris = mesh.GetTriangles(s);
                    var light = renderer.name.StartsWith("navlight_") || s < materials.Length && lightMaterials.Contains(materials[s]);
                    if (!light)
                    {
                        other.AddRange(tris.Select(i => world[i]));
                        continue;
                    }
                    var where = $"{PathOf(renderer.transform, b.Root.transform)} [{(s < materials.Length && materials[s] != null ? materials[s].name : "?")}]";
                    pieces.AddRange(LightPieces(tris, world).Select(p => (where, p)));
                }
            }
            var boxes = new Bounds[other.Count / 3];
            for (var t = 0; t < boxes.Length; t++)
            {
                boxes[t] = new Bounds(other[3 * t], Vector3.zero);
                boxes[t].Encapsulate(other[3 * t + 1]);
                boxes[t].Encapsulate(other[3 * t + 2]);
            }
            var problems = new List<string>();
            foreach (var (where, tris) in pieces)
            {
                var box = new Bounds(tris[0], Vector3.zero);
                foreach (var p in tris)
                    box.Encapsulate(p);
                var near = Near(box, LightContactM).ToArray();
                var touching = near.Any(t => tris.Any(p => (ClosestOnTriangle(p, other[3 * t], other[3 * t + 1], other[3 * t + 2]) - p).magnitude <= LightContactM))
                    || near.Any(t => Enumerable.Range(0, tris.Length).Any(k =>
                        SegmentHitsTriangle(tris[k], tris[k - k % 3 + (k + 1) % 3], other[3 * t], other[3 * t + 1], other[3 * t + 2])));
                if (touching)
                    continue;
                var gap = Near(box, 1f).Select(t => tris.Min(p => (ClosestOnTriangle(p, other[3 * t], other[3 * t + 1], other[3 * t + 2]) - p).magnitude))
                    .DefaultIfEmpty(float.PositiveInfinity).Min();
                problems.Add($"{where}: {tris.Length / 3} triangles at {box.center} stand {gap * 1000:F0} mm off the nearest face that is not a light");
            }
            if (problems.Count > 0)
                throw new InvalidDataException("Lights off the skin (limit " + LightContactM * 1000 + " mm):\n" + string.Join("\n", problems));
            b.Report.Add($"lights: {pieces.Count} pieces, each on the skin within {LightContactM * 1000} mm");

            IEnumerable<int> Near(Bounds piece, float reach)
            {
                piece.Expand(2 * reach);
                return Enumerable.Range(0, boxes.Length).Where(t => boxes[t].Intersects(piece));
            }
        }

        // A light submesh's connected pieces, as world triangle lists; vertices at one position count as one.
        private static IEnumerable<Vector3[]> LightPieces(int[] tris, Vector3[] world)
        {
            var root = Enumerable.Range(0, world.Length).ToArray();
            int Find(int x)
            {
                while (root[x] != x)
                    x = root[x] = root[root[x]];
                return x;
            }
            var byPosition = new Dictionary<Vector3Int, int>();
            foreach (var i in tris.Distinct())
            {
                var key = Vector3Int.RoundToInt(world[i] * 10000f);
                if (byPosition.TryGetValue(key, out var first))
                    root[Find(i)] = Find(first);
                else
                    byPosition[key] = i;
            }
            for (var t = 0; t < tris.Length; t += 3)
            {
                root[Find(tris[t + 1])] = Find(tris[t]);
                root[Find(tris[t + 2])] = Find(tris[t]);
            }
            return Enumerable.Range(0, tris.Length / 3).GroupBy(t => Find(tris[3 * t]))
                .Select(g => g.SelectMany(t => new[] { world[tris[3 * t]], world[tris[3 * t + 1]], world[tris[3 * t + 2]] }).ToArray());
        }

        // The point of triangle abc nearest p (Ericson, Real-Time Collision Detection, 5.1.5).
        private static Vector3 ClosestOnTriangle(Vector3 p, Vector3 a, Vector3 b, Vector3 c)
        {
            Vector3 ab = b - a, ac = c - a, ap = p - a;
            float d1 = Vector3.Dot(ab, ap), d2 = Vector3.Dot(ac, ap);
            if (d1 <= 0 && d2 <= 0)
                return a;
            var bp = p - b;
            float d3 = Vector3.Dot(ab, bp), d4 = Vector3.Dot(ac, bp);
            if (d3 >= 0 && d4 <= d3)
                return b;
            var vc = d1 * d4 - d3 * d2;
            if (vc <= 0 && d1 >= 0 && d3 <= 0)
                return a + ab * (d1 / (d1 - d3));
            var cp = p - c;
            float d5 = Vector3.Dot(ab, cp), d6 = Vector3.Dot(ac, cp);
            if (d6 >= 0 && d5 <= d6)
                return c;
            var vb = d5 * d2 - d1 * d6;
            if (vb <= 0 && d2 >= 0 && d6 <= 0)
                return a + ac * (d2 / (d2 - d6));
            var va = d3 * d6 - d5 * d4;
            if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0)
                return b + (c - b) * ((d4 - d3) / (d4 - d3 + (d5 - d6)));
            var sum = va + vb + vc;
            return sum == 0 ? a : a + ab * (vb / sum) + ac * (vc / sum);
        }

        // Whether segment pq crosses triangle abc (Moller and Trumbore).
        private static bool SegmentHitsTriangle(Vector3 p, Vector3 q, Vector3 a, Vector3 b, Vector3 c)
        {
            Vector3 d = q - p, e1 = b - a, e2 = c - a;
            var h = Vector3.Cross(d, e2);
            var det = Vector3.Dot(e1, h);
            if (Mathf.Abs(det) < 1e-12f)
                return false;
            var s = p - a;
            var u = Vector3.Dot(s, h) / det;
            if (u < 0 || u > 1)
                return false;
            var k = Vector3.Cross(s, e1);
            var v = Vector3.Dot(d, k) / det;
            if (v < 0 || u + v > 1)
                return false;
            var t = Vector3.Dot(e2, k) / det;
            return t >= 0 && t <= 1;
        }
    }
}
