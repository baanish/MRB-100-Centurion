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
        private static void AuthorDarkreachMounts(GameObject aircraft, Dictionary<string, Object> weapons,
            List<(string Key, int Set)> modMounts)
        {
            var racks = new[]
            {
                ("tusko", "AShM3_internalx4_stack", 4, 650f, 24, 24, 24),
                ("auger", "bomb_penetrator1_internalx4", 4, 1000f, 10, 16, 20),
                ("arad", "ARM1_internalx4", 4, 400f, 0, 16, 16),
                ("ashm300", "AShM1_internalx4_stack", 4, 600f, 20, 18, 18),
                ("gbm500lr", "bomb_500_glide_internalx6", 6, 500f, 32, 32, 36),
                ("gpon15", "nuclearBomb1_internalx4_stack", 4, 400f, 16, 50, 60),
                ("gpon250", "nuclearBomb1_strategic_internalx4_stack", 4, 400f, 16, 50, 60),
                ("piledriver", "BallisticMissile1_internalx2", 2, 2500f, 8, 6, 6),
                ("piledriver20kt", "BallisticMissile1_tacNuke_internalx2", 2, 2500f, 8, 6, 6),
                ("demolition", "bomb_demolition_internal", 1, 10000f, 2, 2, 2),
                // ALM-C450 alone overlaps tandem store bounds by 6.4 cm; cross-section gaps stay 0.0801 m.
                ("almc450", "CruiseMissile1_internalx4", 4, 900f, 20, 12, 9),
                ("alnd4", "CruiseMissile20kt_internalx2", 2, 1280f, 8, 4, 6),
                ("agm99", "AShM2_internalx8", 6, 450f, 32, 50, 60),
                ("pab80lr", "bomb_glide1_quad_inernal", 4, 125f, 0, 196, 216),
            };
            var stockKeys = new[]
            {
                "AShM3_internalx4_stack", "bomb_penetrator1_internalx4", "ARM1_internalx4", "AShM1_internalx4_stack",
                "bomb_500_glide_internalx6", "nuclearBomb1_internalx2", "nuclearBomb1_internalx4_stack",
                "nuclearBomb1_strategic_internalx2", "nuclearBomb1_strategic_internalx4_stack",
                "bomb_250_rotaryx10", "bomb_250_glide_rotaryx10", "bomb_500_rotaryx6", "BallisticMissile1_internalx2",
                "BallisticMissile1_tacNuke_internalx2", "bomb_demolition_internal", "bomb_250_rotaryx30", "bomb_250_glide_rotaryx30",
                "bomb_glide1_quad_inernal", "CruiseMissile1_internalx4", "CruiseMissile20kt_internalx2", "AShM2_internalx8",
            };
            foreach (var key in new[] { "baanish_centurion_irms2_192", "baanish_centurion_irms2_189" })
            {
                AssetDatabase.DeleteAsset(ModFolder + "/OpAddWeaponToHardpoint_" + key + ".asset");
                AssetDatabase.DeleteAsset(ModFolder + "/" + key + ".asset");
                AssetDatabase.DeleteAsset(ModFolder + "/" + key + "_Info.asset");
                AssetDatabase.DeleteAsset(ModFolder + "/" + key + ".prefab");
            }
            foreach (var path in Directory.GetFiles(ModFolder, "baanish_centurion_aam*").Where(p => !p.EndsWith(".meta", StringComparison.Ordinal)))
                if (!AssetDatabase.DeleteAsset(path.Replace('\\', '/')))
                    throw new IOException("Could not remove retired AAM rack " + path);
            AssetDatabase.DeleteAsset(ModFolder + "/OpAddWeaponToHardpoint_AAM3_single_internal.asset");
            foreach (var pair in FindWeaponMounts(stockKeys)) weapons[pair.Key] = pair.Value;
            var bays = new[] { FindDeep(aircraft.transform, "hardpoint_bay_forward"), FindDeep(aircraft.transform, "hardpoint_bay_aft") };
            var triangles = bays.Select(bay => BayTriangles(aircraft, bay)).ToArray();
            foreach (var key in stockKeys.Except(BayWeapons))
            {
                var stock = new SerializedObject(weapons[key]);
                var prefab = (GameObject)Prop(stock, "prefab").objectReferenceValue;
                var bounds = BombStoreBounds(prefab.transform, prefab.transform);
                bounds.center += prefab.transform.localPosition;
                for (var set = 0; set < 2; set++)
                    if (RackFits(bounds, triangles[set])) modMounts.Add((key, set));
                if (!modMounts.Any(m => m.Key == key))
                    AssetDatabase.DeleteAsset(ModFolder + "/OpAddWeaponToHardpoint_" + key + ".asset");
            }
            // forward_bin and aft_bin: the most rounds each bay takes before the payload and balance limits.
            var report = new List<string> { "munition,forward_key,aft_key,forward_grid,aft_grid,count,payload_kg,moment_tm,fuel_ratio,forward_bin,aft_bin" };
            foreach (var (slug, stockKey, stockCount, mass, darkreachCount, forwardCount, aftCount) in racks)
            {
                var stock = new SerializedObject(weapons[stockKey]);
                var prefab = (GameObject)Prop(stock, "prefab").objectReferenceValue;
                var template = prefab.GetComponentsInChildren(GameType("MountedMissile"))[0];
                var size = BombStoreBounds(template.transform, prefab.transform).size;
                var tandemGap = slug == "almc450" ? -0.0640f : BombStoreGap;
                var gap = new Vector3(BombStoreGap, BombStoreGap, tandemGap);
                var candidates = new List<(int Columns, int Layers, int Tandem, int Count)>[2];
                for (var set = 0; set < 2; set++)
                {
                    candidates[set] = new List<(int, int, int, int)>();
                    for (var columns = 1; columns <= 12; columns++)
                        for (var layers = 1; layers <= 10; layers++)
                            for (var tandem = 1; tandem <= 4; tandem++)
                            {
                                var extent = Vector3.Scale(size + gap, new Vector3(columns, layers, tandem)) - gap;
                                var bounds = new Bounds(new Vector3(0, BombGridTop - BombHardpointHeight - extent.y * 0.5f, 0), extent);
                                if (RackFits(bounds, triangles[set])) candidates[set].Add((columns, layers, tandem, columns * layers * tandem));
                            }
                }
                // Maximum payload among centred rectangular grids; ties favour the smaller pitch moment.
                // The owner lets the PAB-80LR fill both bays, 51.5 t ("close enough", 2026-10-17); every other pair stays within 50 t.
                var payloadCap = slug == "pab80lr" ? 51500f : 50000f;
                // Two demolition bombs a bay sit 23.6 t*m nose-down, about 12 cm of CG on this aircraft; the owner takes it
                // ("Centimeters is nothing", 2026-10-17).
                // Owner: "21, allow 33 t*m" (2026-10-18): ALM-C450 12 + 9 is -32.886 t*m. Other pairs stay within 20 t*m.
                var momentCap = slug == "demolition" ? 25f : slug == "almc450" ? 33f : 20f;
                var pairs = (from f in candidates[0] from a in candidates[1]
                    let payload = (f.Count + a.Count) * mass
                    let moment = mass * (f.Count * (12f - BombEmptyCgStation) + a.Count * (28.1f - BombEmptyCgStation)) / 1000f
                    where payload <= payloadCap && Mathf.Abs(moment) <= momentCap && f.Count + a.Count > darkreachCount
                    orderby payload descending, Mathf.Abs(moment), f.Layers + a.Layers
                    select (Forward: f, Aft: a, Payload: payload, Moment: moment)).ToArray();
                if (pairs.Length == 0) throw new InvalidDataException(slug + ": no bay-safe load greater than Darkreach " + darkreachCount);
                var best = pairs[0];
                if (best.Forward.Count != forwardCount || best.Aft.Count != aftCount)
                    throw new InvalidDataException($"{slug}: the bays now take {best.Forward.Count} " +
                        $"({best.Forward.Columns}x{best.Forward.Layers}x{best.Forward.Tandem}) forward and {best.Aft.Count} " +
                        $"({best.Aft.Columns}x{best.Aft.Layers}x{best.Aft.Tandem}) aft, not the pinned {forwardCount} and {aftCount}; remeasure before shipping");
                var keys = new string[2];
                for (var set = 0; set < 2; set++)
                {
                    if (slug == "arad" && set == 1) continue;
                    var grid = set == 0 ? best.Forward : best.Aft;
                    var key = keys[set] = $"baanish_centurion_{slug}_{grid.Count}";
                    if (!weapons.ContainsKey(key)) weapons[key] = AuthorBombMount(weapons[stockKey], key, stockCount,
                        grid.Columns, grid.Layers, mass, size, grid.Tandem, true, tandemGap);
                    modMounts.Add((key, set));
                }
                // A rack whose pinned count changed leaves its old mount behind; nothing would offer it, but the bundle would carry it.
                foreach (var path in Directory.GetFiles(ModFolder, $"baanish_centurion_{slug}_*").Where(p => !p.EndsWith(".meta", StringComparison.Ordinal)))
                    if (!keys.Contains(Path.GetFileNameWithoutExtension(path)) && !AssetDatabase.DeleteAsset(path.Replace('\\', '/')))
                        throw new IOException("Could not remove retired rack " + path);
                var fuel = keys[1] == null ? 1f : BombLoadoutFuel(weapons[keys[0]], weapons[keys[1]], null, payloadCap, momentCap);
                string Grid((int Columns, int Layers, int Tandem, int Count) g) => $"{g.Columns}x{g.Layers}x{g.Tandem}";
                var count = best.Forward.Count + (keys[1] == null ? 0 : best.Aft.Count);
                var rackMoment = mass * (best.Forward.Count * (12f - BombEmptyCgStation) + (keys[1] == null ? 0 : best.Aft.Count) * (28.1f - BombEmptyCgStation)) / 1000f;
                var line = FormattableString.Invariant($"{slug},{keys[0]},{keys[1]},{Grid(best.Forward)},{(keys[1] == null ? "" : Grid(best.Aft))},{count},{count * mass},{rackMoment},{fuel},{candidates[0].Max(c => c.Count)},{candidates[1].Max(c => c.Count)}");
                report.Add(line);
                Debug.Log("[Centurion] Rack " + line);
            }
            Directory.CreateDirectory(Path.Combine(RepoRoot, ".cache/munitions"));
            File.WriteAllLines(Path.Combine(RepoRoot, ".cache/munitions/racks.csv"), report);
        }

        private static Vector3[][] BayTriangles(GameObject aircraft, Transform bay)
        {
            var triangles = new List<Vector3[]>();
            foreach (var filter in aircraft.GetComponentsInChildren<MeshFilter>(true))
            {
                if (filter.name.EndsWith("_lod1") || filter.sharedMesh == null) continue;
                var vertices = filter.sharedMesh.vertices.Select(v => bay.InverseTransformPoint(filter.transform.TransformPoint(v))).ToArray();
                var indices = filter.sharedMesh.triangles;
                for (var i = 0; i < indices.Length; i += 3)
                {
                    var triangle = new[] { vertices[indices[i]], vertices[indices[i + 1]], vertices[indices[i + 2]] };
                    if (triangle.All(v => v.x > 1.85f) || triangle.All(v => v.x < -1.85f) || triangle.All(v => v.y > 1f) ||
                        triangle.All(v => v.y < -2.3f) || triangle.All(v => v.z > 4.7f) || triangle.All(v => v.z < -4.7f)) continue;
                    triangles.Add(triangle);
                }
            }
            return triangles.ToArray();
        }

        private static bool RackFits(Bounds bounds, Vector3[][] triangles)
        {
            if (bounds.min.x < -1.6299f || bounds.max.x > 1.6299f || bounds.min.y < 1.3f - BombHardpointHeight ||
                bounds.max.y > BombGridTop - BombHardpointHeight + 0.0001f || bounds.min.z < -4.3999f || bounds.max.z > 4.3999f) return false;
            bounds.Expand(0.2f);
            foreach (var triangle in triangles)
            {
                var a = triangle[0] - bounds.center;
                var b = triangle[1] - bounds.center;
                var c = triangle[2] - bounds.center;
                var extent = bounds.extents;
                bool Separates(Vector3 axis)
                {
                    var pa = Vector3.Dot(a, axis); var pb = Vector3.Dot(b, axis); var pc = Vector3.Dot(c, axis);
                    var radius = Vector3.Dot(extent, new Vector3(Mathf.Abs(axis.x), Mathf.Abs(axis.y), Mathf.Abs(axis.z)));
                    return Mathf.Min(pa, Mathf.Min(pb, pc)) > radius || Mathf.Max(pa, Mathf.Max(pb, pc)) < -radius;
                }
                if (Separates(Vector3.right) || Separates(Vector3.up) || Separates(Vector3.forward) || Separates(Vector3.Cross(b-a, c-a))) continue;
                var separated = false;
                foreach (var edge in new[] { b-a, c-b, a-c })
                    if (Separates(Vector3.Cross(edge, Vector3.right)) || Separates(Vector3.Cross(edge, Vector3.up)) ||
                        Separates(Vector3.Cross(edge, Vector3.forward))) { separated = true; break; }
                if (!separated) return false;
            }
            return true;
        }
    }
}
