using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    // The laser C-RAM mount, tail eye and collider clearance contract.
    public static partial class CenturionAuthor
    {
        // The mount's WeaponMount.jsonKey, the encyclopedia key the loadout SyncVar carries: never changes after release.
        private const string CramKey = "baanish_centurion_cram";

        // The fairing stays on the airframe; only the emitter leaves with the weapon.
        private static readonly string[] CramOwnedParts = { "laser_barrel" };
        private const float CramMass = 300f;
        private const float CramConeAngle = 80f;
        // The part the turret's dome, its hardpoint and its eye sit on: the tail's end (the part tree's cut at 38.3),
        // whose blockout mass includes the removable hardware's.
        private const string CramHost = "tail_end";
        private const string CramPrefabPath = ModFolder + "/Centurion_Cram.prefab";

        // The lens (the tail's back end, art/blender/m4/fuselage_aft_laser.py): the Medusa lens's amber metal, opaque, as
        // Centurion_glass is (owner: the stock EW1_glass "is too transparent, make it opaque"; it showed the structure
        // behind it). The blockout's laser_lens slot takes it.
        private const string LensSlot = "laser_lens";
        private static readonly Color32 LensTint = new Color32(239, 152, 104, 255);
        private const float LensSmoothness = 0.95f;

        private static Material AuthorLens()
        {
            var lens = OpaqueLit(SlotMaterials["jet_mechanical"], "Centurion_lens");
            lens.SetTexture("_BaseMap", null);
            lens.SetTexture("_MainTex", null);
            lens.SetTexture("_MetallicGlossMap", null);
            lens.DisableKeyword("_METALLICSPECGLOSSMAP");
            lens.SetColor("_BaseColor", LensTint);
            lens.SetColor("_Color", LensTint);
            lens.SetFloat("_Metallic", 1f);
            lens.SetFloat("_Smoothness", LensSmoothness);
            return SaveAsset(lens, SkinFolder + "/Centurion_lens.mat");
        }

        private static Object AuthorCramMount(Dictionary<string, PartMeshes> meshes)
        {
            var blockout = Blockout.Load(ExportFolder);
            var info = Object.Instantiate(Load<Object>(Stock + "MonoBehaviour/Laser_APS2_PLACEHOLDER.asset"));
            info.name = "Centurion_Cram_Info";
            var so = new SerializedObject(info);
            Prop(so, "weaponPrefab").objectReferenceValue = null;
            Prop(so, "weaponName").stringValue = "120 kW Laser C-RAM";
            Prop(so, "shortName").stringValue = "C-RAM 120KW";
            foreach (var field in new[] { "antiSurface", "antiAir", "antiRadar" }) Num(so, "effectiveness." + field, 0);
            Num(so, "effectiveness.antiMissile", 1);
            Prop(so, "targetRequirements.lineOfSight").boolValue = true;
            foreach (var field in new[] { "minAltitude", "minRange", "minIR", "minRadar", "minAlignment", "minOwnerSpeed", "minValue" })
                Num(so, "targetRequirements." + field, 0);
            Num(so, "targetRequirements.maxAltitude", 100000);
            Num(so, "targetRequirements.maxSpeed", 100000);
            Num(so, "targetRequirements.maxRange", 8000);
            Num(so, "pK", 0.01);
            Num(so, "armorTierEffectiveness", 1);
            Num(so, "fireInterval", 0);
            Num(so, "muzzleVelocity", 3e8);
            Num(so, "maxSpeed", -1);
            Num(so, "costPerRound", 0);
            Num(so, "massPerRound", 0);
            foreach (var field in new[] { "useWeaponDoors", "boresight", "laserGuided", "missile", "bomb", "glideBomb", "gun", "overHorizon", "nuclear", "strategic", "jammer", "troops", "hideInDisplay", "cargo", "rearmGround", "rearmShip", "sling" })
                Prop(so, field).boolValue = false;
            Prop(so, "energy").boolValue = true;
            so.ApplyModifiedPropertiesWithoutUndo();
            if (Prop(new SerializedObject(info), "costPerRound").floatValue != 0)
                throw new InvalidDataException("C-RAM cover requires the carrier's only zero-cost weapon");
            info = SaveAsset(info, ModFolder + "/Centurion_Cram_Info.asset");

            var root = new GameObject("cram_mount");
            try
            {
                var yaw = CramChild("cram_yaw", root.transform);
                yaw.localRotation = Quaternion.Euler(0, 180, 0);
                var cone = CramChild("cram_cone_aft", yaw);
                var turret = CramChild("laser_turret", yaw);
                var barrel = CramChild("laser_barrel", turret);
                var pivot = blockout.Local("laser_turret");
                barrel.position = blockout.Local("laser_barrel") - pivot;
                foreach (var name in CramOwnedParts)
                {
                    var visual = CramChild(name + "_mesh", barrel);
                    visual.position = blockout.Local(name) - pivot;
                    visual.rotation = blockout.Rotation(name);
                    visual.gameObject.AddComponent<MeshFilter>().sharedMesh = meshes[name].Render;
                    visual.gameObject.AddComponent<MeshRenderer>().sharedMaterials = meshes[name].Materials;
                    if (meshes[name].Lod1 != null)
                    {
                        var hull = CramChild(name + "_lod1", visual);
                        hull.gameObject.AddComponent<MeshFilter>().sharedMesh = meshes[name].Lod1;
                        hull.gameObject.AddComponent<MeshRenderer>().sharedMaterials = meshes[name].Lod1Materials;
                    }
                }
                var laserObject = Object.Instantiate(Load<GameObject>(Stock + "GameObject/Laser_EW1_PLACEHOLDER.prefab"), barrel, false);
                laserObject.name = "laser";
                laserObject.transform.localPosition = Vector3.zero;
                laserObject.transform.localRotation = Quaternion.identity;
                var laser = laserObject.GetComponent(GameType("Laser"));
                Set(laser, "info", info);
                Set(laser, "attachedUnit", (Object)null);
                var laserSo = new SerializedObject(laser);
                Num(laserSo, "power", 120); // the Medusa's Laser_EW1 (owner, 2026-10-16: "the same as the Medusa")
                Num(laserSo, "maxAngle", 60);
                Num(laserSo, "fireDamage", 40); // the Medusa's too: less power, less damage
                Num(laserSo, "blastDamage", 0);
                Prop(laserSo, "vehicularPowerSupply").boolValue = false;
                Prop(laserSo, "modifyPitch").boolValue = true;
                Num(laserSo, "startPitchMultiplier", 3);
                Num(laserSo, "pitchFallRate", 10);
                Prop(laserSo, "damageAtRange").animationCurveValue = AnimationCurve.Linear(0, 1, 16000, 0);
                ((Transform)Prop(laserSo, "directionTransform").objectReferenceValue).name = "aim";
                laserSo.ApplyModifiedPropertiesWithoutUndo();

                var turretSo = new SerializedObject(turret.gameObject.AddComponent(GameType("Turret")));
                Prop(turretSo, "targetAcquisitionMode").enumValueIndex = 3;
                Prop(turretSo, "targetDetectors").arraySize = 0;
                Prop(turretSo, "criticalParts").arraySize = 0;
                var stations = Prop(turretSo, "weaponStations");
                stations.arraySize = 1;
                var weapons = stations.GetArrayElementAtIndex(0).FindPropertyRelative("Weapons");
                weapons.arraySize = 1;
                weapons.GetArrayElementAtIndex(0).objectReferenceValue = laser;
                var cones = Prop(turretSo, "firingCones");
                cones.arraySize = 1;
                var firingCone = cones.GetArrayElementAtIndex(0);
                firingCone.FindPropertyRelative("transform").objectReferenceValue = cone;
                firingCone.FindPropertyRelative("coneAngle").floatValue = CramConeAngle;
                firingCone.FindPropertyRelative("exclusion").boolValue = false;
                Num(turretSo, "traverseRate", 150);
                Num(turretSo, "traverseRange", 360);
                Num(turretSo, "elevationRate", 90);
                Num(turretSo, "minElevation", -90);
                Num(turretSo, "maxElevation", 90);
                Num(turretSo, "targetAssessmentInterval", 0.5);
                Num(turretSo, "lockTime", 0.2);
                Prop(turretSo, "elevationTransform").objectReferenceValue = barrel;
                Prop(turretSo, "onlyDefensive").boolValue = false;
                Prop(turretSo, "newTargetSearchAfterFire").boolValue = false;
                turretSo.ApplyModifiedPropertiesWithoutUndo();

                var renderers = root.GetComponentsInChildren<MeshRenderer>();
                var lod = root.AddComponent<LODGroup>();
                lod.SetLODs(new[] { new LOD(0.05f, renderers.Where(r => !r.name.EndsWith("_lod1")).Cast<Renderer>().ToArray()),
                    new LOD(0.001f, renderers.Where(r => r.name.EndsWith("_lod1")).Cast<Renderer>().ToArray()) });
                lod.RecalculateBounds();
                var colors = new SerializedObject(root.AddComponent(GameType("ColorableMount")));
                Prop(colors, "colorableRenderers").arraySize = 0;
                var skins = Prop(colors, "skinnableRenderers");
                skins.arraySize = renderers.Length;
                for (var i = 0; i < renderers.Length; i++) skins.GetArrayElementAtIndex(i).objectReferenceValue = renderers[i];
                colors.ApplyModifiedPropertiesWithoutUndo();
                var mount = ScriptableObject.CreateInstance(GameType("WeaponMount"));
                mount.name = "Centurion_Cram";
                var mountSo = new SerializedObject(mount);
                Prop(mountSo, "jsonKey").stringValue = CramKey;
                Prop(mountSo, "mountName").stringValue = "120 kW Laser C-RAM";
                Prop(mountSo, "prefab").objectReferenceValue = SavePrefab(root, CramPrefabPath);
                Prop(mountSo, "info").objectReferenceValue = info;
                Prop(mountSo, "turret").boolValue = true;
                Prop(mountSo, "colorable").boolValue = true;
                Prop(mountSo, "GearSafety").boolValue = false;
                Prop(mountSo, "GroundSafety").boolValue = true;
                Num(mountSo, "ammo", 1);
                Num(mountSo, "emptyMass", CramMass);
                Num(mountSo, "mass", CramMass);
                Num(mountSo, "emptyDrag", 0);
                Num(mountSo, "emptyCost", 2.5);
                mountSo.ApplyModifiedPropertiesWithoutUndo();
                return SaveAsset(mount, ModFolder + "/Centurion_Cram.asset");
            }
            finally { Object.DestroyImmediate(root); }
        }

        private static Transform CramChild(string name, Transform parent)
        {
            var child = new GameObject(name).transform;
            child.SetParent(parent, false);
            return child;
        }

        private static void CheckFixedDome(Build b)
        {
            var dome = b.Visuals["laser_turret"];
            if (dome.parent != b.Parts[CramHost].transform || dome.GetComponentsInChildren<Collider>(true).Length != 0
                || dome.GetComponentsInChildren(GameType("AeroPart"), true).Length != 0
                || dome.GetComponent<MeshRenderer>() == null || dome.Find("laser_turret_lod1") == null)
                throw new InvalidDataException("Laser dome must have both render LODs under " + CramHost + ", without physics");
            var mount = Load<GameObject>(CramPrefabPath);
            if (mount.GetComponentsInChildren<MeshRenderer>(true).Any(r => r.name.StartsWith("laser_turret"))
                || mount.GetComponentsInChildren<Collider>(true).Length != 0)
                throw new InvalidDataException("Removable C-RAM must carry no dome renderers or colliders");
            b.Report.Add($"Laser dome: fixed LOD0/LOD1 on {CramHost}; removable hardware {CramMass} kg, zero drag/colliders");
        }

        // The tail TargetDetector that feeds the C-RAM's track list.
        private static void BuildCramEye(Build b)
        {
            var eye = CramChild("cram_eye", b.Parts[CramHost].transform);
            eye.position = b.Root.transform.TransformPoint(b.Blockout.Local("laser_turret"));
            var scanner = CramChild("cram_eye_scan", eye);
            scanner.rotation = b.Root.transform.rotation * Quaternion.Euler(0, 180, 0);
            var detector = eye.gameObject.AddComponent(GameType("TargetDetector"));
            Set(detector, "attachedUnit", b.Aircraft);
            Set(detector, "scanner", scanner);
            Set(detector, "part", b.Part(CramHost));
            Set(detector, "checkInterval", 0.5f);
            Set(detector, "alertCheckInterval", 0f);
            Set(detector, "visualRange", 10000f);
            Set(detector, "magnification", 4f);
            Set(detector, "maxSpeed", 3000f);
            var so = new SerializedObject(detector);
            Prop(so, "shared").boolValue = false;
            Prop(so, "rotators").arraySize = 0;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        // Fails the build when a ray from the turret's pivot inside the firing cone meets the airframe.
        private static void CheckCramCone(Build b)
        {
            var pivot = b.Root.transform.TransformPoint(b.Blockout.Local("laser_turret"));
            // A stock placeholder part (the cloned cockpit's EjectionSeat) has a MeshCollider whose mesh Blueprinter fills in
            // only in game; with no shape here, ClosestPoint returns the pivot itself.
            var colliders = b.Root.GetComponentsInChildren<Collider>(true)
                .Where(c => c.enabled && !c.isTrigger && !(c is MeshCollider mesh && mesh.sharedMesh == null)).ToArray();
            if (colliders.Length == 0) throw new InvalidDataException("C-RAM cone check has no airframe colliders");
            var slides = Parts.Where(p => b.Blockout.Slide(p.Name).HasValue).Select(p => b.Parts[p.Name].transform)
                .Select(t => (stage: t, rest: t.localPosition, end: t.parent.Find(t.name + "_extended").localPosition)).ToArray();
            try
            {
                foreach (var extension in new[] { 0f, 1f })
                {
                    foreach (var slide in slides) slide.stage.localPosition = Vector3.Lerp(slide.rest, slide.end, extension);
                    Physics.SyncTransforms();
                    foreach (var collider in colliders)
                        if ((collider.ClosestPoint(pivot) - pivot).sqrMagnitude < 0.000001f)
                            throw new InvalidDataException("C-RAM pivot is inside airframe collider " + collider.name);
                    for (var angle = 0; angle <= CramConeAngle; angle += 2)
                        for (var azimuth = 0; azimuth < 360; azimuth += 2)
                        {
                            var direction = b.Root.transform.rotation * Quaternion.Euler(0, 180, 0)
                                * Quaternion.AngleAxis(azimuth, Vector3.forward) * Quaternion.AngleAxis(angle, Vector3.up) * Vector3.forward;
                            var ray = new Ray(pivot, direction);
                            foreach (var collider in colliders)
                                if (collider.Raycast(ray, out var hit, 8000))
                                    throw new InvalidDataException($"C-RAM cone {angle}/{azimuth} hits {collider.name} at {hit.distance:F3} m, span {extension}");
                        }
                }
                b.Report.Add($"C-RAM: {CramConeAngle} degree cone clear of airframe colliders at both spans");
            }
            finally
            {
                foreach (var slide in slides) slide.stage.localPosition = slide.rest;
                Physics.SyncTransforms();
            }
        }
    }
}
