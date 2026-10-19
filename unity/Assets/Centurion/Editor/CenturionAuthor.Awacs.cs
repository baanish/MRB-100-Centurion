using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Blueprinter;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    // The AWACS beam mount's authoring (docs/M3-DESIGN.md "AWACS beam"): the mount prefab from art/blender/awacs_mount.py's
    // export in art/export_awacs, imported as the airframe is, its WeaponMount and WeaponInfo, and the envelope
    // check. With no export there is no mount, which leaves set 2 empty.
    public static partial class CenturionAuthor
    {
        // The mount's WeaponMount.jsonKey, the encyclopedia key the loadout SyncVar carries: never changes after release.
        private const string AwacsKey = "baanish_centurion_awacs";
        private const string AwacsRoot = "awacs_base";
        private const string AwacsBlockoutFolder = ModFolder + "/AwacsMount";
        // Unity names a prefab's root after its file, and AwacsBeam finds the spawned mount by that name (AwacsBeam.MountRoot).
        private const string AwacsPrefabPath = ModFolder + "/Centurion_AwacsBeam.prefab";
        private const string AwacsMountPath = ModFolder + "/Centurion_AwacsBeam.asset";
        private const string AwacsInfoPath = ModFolder + "/Centurion_AwacsBeam_Info.asset";
        private const string AwacsPaintPath = SkinFolder + "/Centurion_mount.mat";
        // The design's AWACS radar range; AwacsBeam writes 0 until the beam is fully deployed.
        private const float AwacsRangeM = 150000f;
        // AwacsEnvelopeCheck: the least gap from any mount collider to any part collider but fuselage_R's (the mount's joint
        // pair, which never collides), and the stowed top above wheel contact (SPEC's 7.6 m less 0.15 m).
        private const float AwacsGapM = 0.10f, AwacsStowedTopM = 7.45f;
        private static string AwacsExportFolder => Path.Combine(RepoRoot, "art", "export_awacs");

        // Each mast stage and end section, the marker it rises or slides to, and whether it moves with the ends (the last
        // third of the travel) rather than the mast (the first two thirds), as AwacsBeam moves them.
        private static readonly (string Part, string Marker, bool End)[] AwacsSlides =
        {
            ("awacs_mast_1", "awacs_mast_1_raised", false), ("awacs_mast_2", "awacs_mast_2_raised", false),
            ("awacs_beam_ext_F", "awacs_beam_ext_F_extended", true), ("awacs_beam_ext_R", "awacs_beam_ext_R_extended", true),
        };

        // The WeaponMount asset, or null while there is no mount export.
        private static Object AuthorAwacsMount()
        {
            if (!File.Exists(Path.Combine(AwacsExportFolder, "blockout.json")))
            {
                Debug.Log("[Centurion] AWACS mount: no export in art/export_awacs, so set 2 carries no beam");
                return null;
            }
            var mount = Blockout.Load(AwacsExportFolder, AwacsRoot);
            BlueprinterAssets.EnsureFolder(AwacsBlockoutFolder);
            var slots = new Dictionary<string, Material>
            {
                { SkinSlot, AuthorMountPaint(mount) },
                { "aircraft_structure", Load<Material>(SlotMaterials["aircraft_structure"]) },
                { "LOD", Load<Material>(SlotMaterials["LOD"]) },
            };
            var prefab = AuthorAwacsPrefab(mount, ImportBlockout(mount, slots, AwacsExportFolder, AwacsBlockoutFolder));

            // Cloned from stock Radome: no effectiveness, energy 1 (MonoBehaviour/Radome.asset:17-21, 60).
            var info = Object.Instantiate(Load<Object>(Stock + "MonoBehaviour/Radome_PLACEHOLDER.asset"));
            info.name = Path.GetFileNameWithoutExtension(AwacsInfoPath);
            var iso = new SerializedObject(info);
            Prop(iso, "weaponName").stringValue = "AWACS Beam";
            Prop(iso, "shortName").stringValue = "AWACS";
            Prop(iso, "description").stringValue = "Long-range radar on a two-stage mast that rises out of the spine. It lies flush in its well on the ground near a hangar and deploys clear of it.";
            iso.ApplyModifiedPropertiesWithoutUndo();
            info = SaveAsset(info, AwacsInfoPath);

            // Cloned from stock Radome1 (radar 1, colorable, GearSafety and GroundSafety off), with the beam's numbers
            // (docs/M3-DESIGN.md "Mass, drag, RCS, cost"): emptyMass rides fuselage_R, the mount part carries its own 1,500 kg.
            var weaponMount = Object.Instantiate(Load<Object>(Stock + "MonoBehaviour/Radome1_PLACEHOLDER.asset"));
            weaponMount.name = Path.GetFileNameWithoutExtension(AwacsMountPath);
            var so = new SerializedObject(weaponMount);
            Prop(so, "prefab").objectReferenceValue = prefab;
            Prop(so, "jsonKey").stringValue = AwacsKey;
            Prop(so, "info").objectReferenceValue = info;
            Prop(so, "mountName").stringValue = "AWACS Beam";
            Num(so, "emptyMass", 4500);
            Num(so, "mass", 6000);
            Num(so, "emptyDrag", 1.0);
            Num(so, "drag", 1.0);
            Num(so, "emptyRCS", 0.05);
            Num(so, "RCS", 0.05);
            Num(so, "emptyCost", 13);
            so.ApplyModifiedPropertiesWithoutUndo();
            Debug.Log("[Centurion] AWACS mount: " + AwacsPrefabPath + " from " + mount.SourceBlend);
            return SaveAsset(weaponMount, AwacsMountPath);
        }

        // The mount's paint: its own baked maps (art/blender/awacs_mount_detail.py) on the stock ColorableAttachment shader,
        // as the stock radomes have it, which ColorableMount tints with the livery's first colour where _Paint is 1. A
        // mount export without them (the graybox) gets flat grey. The mount can't share the AircraftSkin material: a
        // livery's texture is the airframe atlas.
        private static readonly (string Property, string File, bool SRgb, bool NormalMap)[] MountMaps =
        {
            ("_BaseColor", "awacs_b.png", true, false), ("_Metallic", "awacs_m.png", false, false), ("_Normal", "awacs_n.png", false, true),
            ("_AO", "awacs_ao.png", false, false), ("_Paint", "awacs_paint.png", false, false),
        };

        private static Material AuthorMountPaint(Blockout mount)
        {
            AssetDatabase.DeleteAsset(SkinFolder + "/Centurion_mount_graybox.mat");
            if (MountMaps.All(m => mount.Textures.ContainsKey(m.File)))
            {
                var baked = new Material(Load<Shader>(Stock + "Shader/Shader Graphs_ColorableAttachment_PLACEHOLDER.shader")) { name = "Centurion_mount" };
                foreach (var map in MountMaps)
                    baked.SetTexture(map.Property, ImportExportTexture(mount, map.File, map.SRgb, map.NormalMap, AwacsExportFolder));
                baked.SetColor("_Color", Liveries[0].Paint[0]);
                baked.SetFloat("_Gloss", 0f);
                return SaveAsset(baked, AwacsPaintPath);
            }
            var paint = OpaqueLit(SlotMaterials["jet_mechanical"], "Centurion_mount");
            paint.SetTexture("_BaseMap", null);
            paint.SetTexture("_MainTex", null);
            paint.SetTexture("_MetallicGlossMap", null);
            paint.DisableKeyword("_METALLICSPECGLOSSMAP");
            paint.SetColor("_BaseColor", GrayboxPaint);
            paint.SetColor("_Color", GrayboxPaint);
            paint.SetFloat("_Metallic", 0f);
            paint.SetFloat("_Smoothness", 0.4f);
            return SaveAsset(paint, AwacsPaintPath);
        }

        // The prefab tree of docs/M3-DESIGN.md "Mount prefab", authored stowed: the export's parts at their pivots under
        // their Blender parents, each mesh with its convex pieces and LOD1 hull; the root alone is a part (Radome1's
        // AeroPart and Radar, with the beam's numbers) on layer 0 with no NetworkIdentity, as Radome1.
        private static GameObject AuthorAwacsPrefab(Blockout mount, Dictionary<string, PartMeshes> meshes)
        {
            var root = new GameObject(Path.GetFileNameWithoutExtension(AwacsPrefabPath));
            try
            {
                var nodes = new Dictionary<string, Transform> { [AwacsRoot] = root.transform };
                int Depth(string name) => mount.Parts[name].BlenderParent == null ? 0 : 1 + Depth(mount.Parts[name].BlenderParent);
                foreach (var part in mount.Parts.Values.Where(p => p.Name != AwacsRoot).OrderBy(p => Depth(p.Name)).ThenBy(p => p.Name, StringComparer.Ordinal))
                {
                    var t = new GameObject(part.Name).transform;
                    t.SetParent(nodes[part.BlenderParent], false);
                    t.SetPositionAndRotation(mount.Local(part.Name), mount.Rotation(part.Name));
                    nodes[part.Name] = t;
                }

                var renderers = new List<Renderer>();
                var hulls = new List<Renderer>();
                foreach (var entry in meshes.OrderBy(m => m.Key, StringComparer.Ordinal))
                {
                    var go = nodes[entry.Key].gameObject;
                    go.AddComponent<MeshFilter>().sharedMesh = entry.Value.Render;
                    var renderer = go.AddComponent<MeshRenderer>();
                    renderer.sharedMaterials = entry.Value.Materials;
                    renderers.Add(renderer);
                    foreach (var piece in entry.Value.Colliders)
                    {
                        var col = go.AddComponent<MeshCollider>();
                        col.sharedMesh = piece;
                        col.convex = true;
                    }
                    if (entry.Value.Lod1 == null)
                        continue;
                    var lod = new GameObject(entry.Key + "_lod1");
                    lod.transform.SetParent(go.transform, false);
                    lod.AddComponent<MeshFilter>().sharedMesh = entry.Value.Lod1;
                    var hull = lod.AddComponent<MeshRenderer>();
                    hull.sharedMaterials = entry.Value.Lod1Materials;
                    hulls.Add(hull);
                }

                var radome = Load<GameObject>(Stock + "GameObject/Radome1_PLACEHOLDER.prefab");
                var aeroType = GameType("AeroPart");
                var aero = root.AddComponent(aeroType);
                EditorUtility.CopySerialized(radome.GetComponent(aeroType), aero);
                var so = new SerializedObject(aero);
                Prop(so, "parentUnit").objectReferenceValue = null; // UnitPart.Awake takes the hardpoint's part (UnitPart.cs:140-152)
                Num(so, "mass", mount.Mass(AwacsRoot)); // above 0, or CreateRB zeroes the aircraft's rigidbody mass (AeroPart.cs:321-328)
                Num(so, "wingArea", 0);
                Num(so, "dragArea", 0);
                // Exactly one joint, which CreateRB fills with the hardpoint's part; with none the mount would drift off and detach.
                var joints = Prop(so, "joints");
                joints.arraySize = 1;
                var joint = joints.GetArrayElementAtIndex(0);
                joint.FindPropertyRelative("connectedPart").objectReferenceValue = null;
                joint.FindPropertyRelative("tensor").objectReferenceValue = null;
                joint.FindPropertyRelative("anchor").objectReferenceValue = null;
                joint.FindPropertyRelative("solverIterations").intValue = 12;
                joint.FindPropertyRelative("breakForce").floatValue = 400000f;
                joint.FindPropertyRelative("breakTorque").floatValue = 400000f;
                so.ApplyModifiedPropertiesWithoutUndo();

                var radarType = GameType("Radar");
                var radar = root.AddComponent(radarType);
                EditorUtility.CopySerialized(radome.GetComponent(radarType), radar);
                var rso = new SerializedObject(radar);
                Prop(rso, "scanner").objectReferenceValue = nodes["awacs_scanner"];
                Prop(rso, "rotators").arraySize = 0;
                Num(rso, "RadarParameters.maxRange", AwacsRangeM);
                Num(rso, "powerDraw", 15);
                rso.ApplyModifiedPropertiesWithoutUndo();

                var colorable = new SerializedObject(root.AddComponent(GameType("ColorableMount")));
                var list = Prop(colorable, "colorableRenderers");
                list.arraySize = renderers.Count;
                for (var i = 0; i < renderers.Count; i++)
                    list.GetArrayElementAtIndex(i).objectReferenceValue = renderers[i];
                Prop(colorable, "skinnableRenderers").arraySize = 0;
                colorable.ApplyModifiedPropertiesWithoutUndo();

                // As the airframe's FinishRoot: the meshes to 5% of the screen, then the LOD1 hulls to 0.1%.
                var group = root.AddComponent<LODGroup>();
                group.SetLODs(new[] { new LOD(0.05f, renderers.ToArray()), new LOD(0.001f, hulls.ToArray()) });
                group.RecalculateBounds();
                return SavePrefab(root, AwacsPrefabPath);
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        // AwacsEnvelopeCheck: the mount posed at hardpoint_dorsal for deploy 0, 0.05, ..., 1, as AwacsBeam moves it. Fails
        // the build when any mount collider comes within AwacsGapM of a part collider other than fuselage_R's, or the stowed
        // top stands over AwacsStowedTopM above wheel contact; reports the least gap, where, and the stowed top.
        private static void CheckAwacsEnvelope(Build b, Object mount)
        {
            if (mount == null)
            {
                b.Report.Add("AWACS envelope: no beam mount authored, not checked");
                return;
            }
            var prefab = (GameObject)new SerializedObject(mount).FindProperty("prefab").objectReferenceValue;
            var beam = (GameObject)Object.Instantiate(prefab, FindDeep(b.Root.transform, "hardpoint_dorsal"), false);
            try
            {
                var aeroType = GameType("AeroPart");
                var mine = beam.GetComponentsInChildren<Collider>(true);
                var carrier = b.Parts["fuselage_R"];
                var airframe = b.Root.GetComponentsInChildren<Collider>(true).Where(c => c.enabled && !c.isTrigger && !mine.Contains(c))
                    .Select(c => (collider: c, part: c.GetComponentInParent(aeroType, true))).Where(c => c.part != null && c.part.gameObject != carrier).ToArray();
                var slides = AwacsSlides.Select(s => (part: FindDeep(beam.transform, s.Part), end: s.End)).ToArray();
                var homes = slides.Select(s => s.part.localPosition).ToArray();
                var raised = AwacsSlides.Select(s => FindDeep(beam.transform, s.Marker).localPosition).ToArray();
                var least = (gap: float.PositiveInfinity, piece: "", part: "", deploy: 0f);
                var stowedTop = 0f;
                for (var k = 0; k <= 20; k++)
                {
                    var deploy = k / 20f;
                    float mast = Mathf.Clamp01(1.5f * deploy), ends = Mathf.Clamp01(3f * deploy - 2f);
                    for (var i = 0; i < slides.Length; i++)
                        slides[i].part.localPosition = Vector3.Lerp(homes[i], raised[i], Mathf.SmoothStep(0f, 1f, slides[i].end ? ends : mast));
                    Physics.SyncTransforms();
                    if (k == 0)
                        stowedTop = beam.GetComponentsInChildren<Renderer>(true).Max(r => r.bounds.max.y) + b.Blockout.Origin.y;
                    foreach (var piece in mine)
                        foreach (var (collider, part) in airframe)
                        {
                            var near = piece.bounds;
                            near.Expand(2f);
                            if (!near.Intersects(collider.bounds))
                                continue;
                            var gap = ColliderGap(piece, collider);
                            if (gap < least.gap)
                                least = (gap, PathOf(piece.transform, beam.transform), part.name, deploy);
                        }
                }
                b.Report.Add($"AWACS envelope: deploy 0 to 1 by 0.05, {mine.Length} mount colliders against {airframe.Length} part colliders but fuselage_R's: " +
                             $"least gap {least.gap:F3} m, {least.piece} to {least.part} at deploy {least.deploy:F2} (limit {AwacsGapM}); stowed top {stowedTop:F2} m above wheel contact (limit {AwacsStowedTopM})");
                var problems = new List<string>();
                if (least.gap < AwacsGapM)
                    problems.Add($"the mount's {least.piece} comes within {least.gap:F3} m of {least.part}'s collider at deploy {least.deploy:F2}; the limit is {AwacsGapM} m");
                if (stowedTop > AwacsStowedTopM)
                    problems.Add($"the stowed mount's top stands {stowedTop:F2} m above wheel contact; the limit is {AwacsStowedTopM} m");
                if (problems.Count > 0)
                    throw new InvalidDataException("AWACS envelope check failed:\n  " + string.Join("\n  ", problems));
            }
            finally
            {
                Object.DestroyImmediate(beam);
                Physics.SyncTransforms();
            }
        }

        // The least distance between two convex colliders, 0 when they overlap: PhysX's penetration test, else closest points
        // passed back and forth between the two shapes, which settles on the nearest pair for convex shapes.
        private static float ColliderGap(Collider a, Collider b)
        {
            if (Physics.ComputePenetration(a, a.transform.position, a.transform.rotation, b, b.transform.position, b.transform.rotation, out _, out _))
                return 0f;
            var pa = a.ClosestPoint(b.bounds.center);
            var pb = b.ClosestPoint(pa);
            for (var i = 0; i < 16; i++)
            {
                pa = a.ClosestPoint(pb);
                pb = b.ClosestPoint(pa);
            }
            return Vector3.Distance(pa, pb);
        }
    }
}
