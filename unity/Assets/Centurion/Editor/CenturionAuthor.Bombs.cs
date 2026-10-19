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
        private const string Bomb500ForwardKey = "baanish_centurion_b500_45";
        private const string Bomb500AftKey = "baanish_centurion_b500_48";
        private const string Bomb250ForwardKey = "baanish_centurion_b250_90";
        private const string Bomb250AftKey = "baanish_centurion_b250_108";
        private const string BombGlideForwardKey = "baanish_centurion_b250lr_84";
        private const string BombGlideAftKey = "baanish_centurion_b250lr_90";

        // Fixed stock orientation, default 0.08 m store gaps, 0.10 m to the detailed bay structure. The roof rack reaches
        // down to 4.23 m. Aft fit assumes the forward cross-section at stations 23.6 to 32.6, hardpoint 28.1 / 3.55 m;
        // remeasure against the final aft meshes before shipping. Presets maximize payload within 20 t*m of the
        // empty CG at station 20.64 (Parts' mass model). Mesh extents round up the stock vertex measurements.
        private const float BombStoreGap = 0.0801f;
        private const float BombGridTop = 4.1299f;
        private const float BombHardpointHeight = 3.55f;
        private const float BombEmptyCgStation = 20.64f;
        // Dense upper layers retain stock rails as slow as 1 m/s; cover the 2.93 s travel and door motion.
        private const float DenseBayDoorHold = 4f;

        private static void AuthorBombMounts(Dictionary<string, Object> weapons, List<(string Key, int Set)> modMounts)
        {
            var racks = new[]
            {
                (Bomb500ForwardKey, "bomb_500_internalx12", 12, 5, 3, 500f, new Vector3(0.41968f, 0.43636f, 2.73131f)),
                (Bomb500AftKey, "bomb_500_internalx12", 12, 4, 4, 500f, new Vector3(0.41968f, 0.43636f, 2.73131f)),
                (Bomb250ForwardKey, "bomb_250_internalx18", 18, 5, 6, 250f, new Vector3(0.28620f, 0.30005f, 2.25149f)),
                (Bomb250AftKey, "bomb_250_internalx18", 18, 6, 6, 250f, new Vector3(0.28620f, 0.30005f, 2.25149f)),
                (BombGlideForwardKey, "bomb_250_glide_internalx8", 8, 7, 4, 270f, new Vector3(0.28318f, 0.33788f, 2.25149f)),
                (BombGlideAftKey, "bomb_250_glide_internalx8", 8, 5, 6, 270f, new Vector3(0.28318f, 0.33788f, 2.25149f)),
            };
            foreach (var (key, stockKey, stockCount, columns, layers, mass, size) in racks)
            {
                weapons[key] = AuthorBombMount(weapons[stockKey], key, stockCount, columns, layers, mass, size);
                modMounts.Add((key, 0));
                modMounts.Add((key, 1));
            }
        }

        private static Object AuthorBombMount(Object stockMount, string key, int stockCount, int columns, int layers,
            float massPerRound, Vector3 size, int tandem = 3, bool denseMissile = false, float tandemGap = BombStoreGap)
        {
            var count = columns * layers * tandem;
            var stock = new SerializedObject(stockMount);
            if (!denseMissile && (!Prop(stock, "missileBay").boolValue || !Prop(stock, "sortWeapons").boolValue ||
                Prop(stock, "emptyMass").floatValue != 0))
                throw new InvalidDataException(key + ": stock bay rack settings changed");
            // The rack carries the stock weapon itself (its name, stats and icon), not a copy.
            var info = Prop(stock, "info").objectReferenceValue;
            AssetDatabase.DeleteAsset(ModFolder + "/" + key + "_Info.asset");
            var bomb = (GameObject)Prop(new SerializedObject(info), "weaponPrefab").objectReferenceValue;
            var missile = bomb.GetComponent(GameType("Missile"));
            var definition = Prop(new SerializedObject(missile), "definition").objectReferenceValue;
            if (Prop(new SerializedObject(definition), "mass").floatValue != massPerRound)
                throw new InvalidDataException(key + ": stock bomb mass changed");
            if (denseMissile && key.StartsWith("baanish_centurion_auger_", StringComparison.Ordinal))
            {
                // The game also has a mounted mesh with this name; name-only rebinding can select it instead of the missile,
                // so the Auger keeps one copy of its stock info, pointing at a renamed projectile.
                info = Object.Instantiate(info);
                var infoSo = new SerializedObject(info);
                var projectile = Object.Instantiate(bomb);
                projectile.name = "Centurion_Auger_Projectile";
                try { Prop(infoSo, "weaponPrefab").objectReferenceValue = SavePrefab(projectile, ModFolder + "/Centurion_Auger_Projectile.prefab"); }
                finally { Object.DestroyImmediate(projectile); }
                infoSo.ApplyModifiedPropertiesWithoutUndo();
                info.name = "Centurion_Auger_Info";
                info = SaveAsset(info, ModFolder + "/" + info.name + ".asset");
            }
            var name = Prop(new SerializedObject(info), "weaponName").stringValue;

            var root = Object.Instantiate((GameObject)Prop(stock, "prefab").objectReferenceValue);
            try
            {
                root.transform.localPosition = Vector3.zero;
                root.transform.localRotation = Quaternion.identity;
                root.transform.localScale = Vector3.one;
                var stores = root.GetComponentsInChildren(GameType("MountedMissile"));
                if (stores.Length != stockCount || (!denseMissile && (root.transform.childCount != stockCount ||
                    stores.Any(s => s.transform.parent != root.transform))))
                    throw new InvalidDataException(key + ": stock store hierarchy changed");
                var template = stores[0];
                if (denseMissile)
                {
                    var clean = new GameObject(key);
                    var copy = Object.Instantiate(template.gameObject, clean.transform, true);
                    Object.DestroyImmediate(root);
                    root = clean;
                    template = copy.GetComponent(GameType("MountedMissile"));
                    stores = new[] { template };
                }
                var bounds = BombStoreBounds(template.transform, root.transform);
                if (Mathf.Abs(bounds.size.x - size.x) > 0.0001f ||
                    Mathf.Abs(bounds.size.y - size.y) > 0.0001f || Mathf.Abs(bounds.size.z - size.z) > 0.0001f)
                    throw new InvalidDataException(key + ": stock bomb mesh extents changed");
                var offset = bounds.center - template.transform.localPosition;
                foreach (var store in stores.Skip(1)) Object.DestroyImmediate(store.gameObject);
                var pitch = size + new Vector3(BombStoreGap, BombStoreGap, tandemGap);
                for (var layer = 0; layer < layers; layer++)
                    for (var row = 0; row < tandem; row++)
                        for (var column = 0; column < columns; column++)
                        {
                            var slot = layer == 0 && row == 0 && column == 0 ? template.gameObject :
                                Object.Instantiate(template.gameObject, root.transform, false);
                            slot.name = $"bomb_{layer}_{row}_{column}";
                            var center = new Vector3((column - (columns - 1) * 0.5f) * pitch.x,
                                BombGridTop - BombHardpointHeight - size.y * 0.5f - (layers - 1 - layer) * pitch.y,
                                (row - (tandem - 1) * 0.5f) * pitch.z);
                            slot.transform.localPosition = center - offset;
                            var weapon = new SerializedObject(slot.GetComponent(GameType("MountedMissile")));
                            if (Prop(weapon, "railDirection").enumValueIndex != 1 ||
                                Prop(weapon, "rotaryTransform").objectReferenceValue != null ||
                                Prop(weapon, "bayDoors").arraySize != 0)
                                throw new InvalidDataException(key + ": stock downward bay release changed");
                            Prop(weapon, "info").objectReferenceValue = info;
                            if (denseMissile)
                            {
                                // Ignite only after the entire store clears the closed-door height, including upper layers.
                                Num(weapon, "railLength", Mathf.Max(Prop(weapon, "railLength").floatValue, BombGridTop - 1.3f + 0.1f));
                                if (Prop(weapon, "railSpeed").floatValue <= 0f)
                                    throw new InvalidDataException(key + ": stock rail speed is not positive");
                                if (Prop(weapon, "railDelay").floatValue + Prop(weapon, "railLength").floatValue /
                                    Prop(weapon, "railSpeed").floatValue > DenseBayDoorHold - 0.5f)
                                    throw new InvalidDataException(key + ": rail travel outlasts the bay doors");
                            }
                            Num(weapon, "ammo", 1);
                            // WeaponStation sorts ascending priority; clear lower layers before any upper rail travels down.
                            Num(weapon, "priority", layer);
                            weapon.ApplyModifiedPropertiesWithoutUndo();
                        }
                if (root.GetComponentsInChildren(GameType("MountedMissile")).Length != count)
                    throw new InvalidDataException(key + ": bomb count mismatch");
                var mount = Object.Instantiate(stockMount);
                mount.name = key;
                var so = new SerializedObject(mount);
                Prop(so, "jsonKey").stringValue = key;
                Prop(so, "mountName").stringValue = name + " x" + count;
                Prop(so, "prefab").objectReferenceValue = SavePrefab(root, ModFolder + "/" + key + ".prefab");
                Prop(so, "info").objectReferenceValue = info;
                Num(so, "ammo", count);
                Num(so, "mass", massPerRound * count);
                if (denseMissile)
                {
                    Prop(so, "missileBay").boolValue = true;
                    Prop(so, "sortWeapons").boolValue = true;
                    Num(so, "emptyMass", 0f);
                    Num(so, "drag", 0f);
                    Num(so, "emptyDrag", 0f);
                    Num(so, "RCS", 0f);
                    Num(so, "emptyRCS", 0f);
                }
                so.ApplyModifiedPropertiesWithoutUndo();
                return SaveAsset(mount, ModFolder + "/" + key + ".asset");
            }
            finally { Object.DestroyImmediate(root); }
        }

        private static Bounds BombStoreBounds(Transform store, Transform root)
        {
            var bounds = new Bounds();
            var first = true;
            foreach (var mesh in store.GetComponentsInChildren<MeshFilter>())
                foreach (var vertex in mesh.sharedMesh.vertices)
                {
                    var point = root.InverseTransformPoint(mesh.transform.TransformPoint(vertex));
                    if (first) bounds = new Bounds(point, Vector3.zero);
                    else bounds.Encapsulate(point);
                    first = false;
                }
            if (first) throw new InvalidDataException("Stock bomb has no mesh vertices");
            return bounds;
        }

        private static float BombLoadoutFuel(Object forward, Object aft, Object cover, float payloadCap = 50000f, float momentCap = 20f)
        {
            var forwardMass = Prop(new SerializedObject(forward), "mass").floatValue;
            var aftMass = Prop(new SerializedObject(aft), "mass").floatValue;
            var mass = forwardMass + aftMass + (cover != null ? Prop(new SerializedObject(cover), "mass").floatValue : 0f);
            if (mass > payloadCap) throw new InvalidDataException($"Bomb preset exceeds the {payloadCap} kg payload limit");
            var moment = (forwardMass * (12f - BombEmptyCgStation) + aftMass * (28.1f - BombEmptyCgStation)) / 1000f;
            if (Mathf.Abs(moment) > momentCap) throw new InvalidDataException($"Bomb preset exceeds the {momentCap} t*m balance limit");
            return Mathf.Min(1f, (199000f - EmptyMass - mass) / 24000f);
        }
    }
}
