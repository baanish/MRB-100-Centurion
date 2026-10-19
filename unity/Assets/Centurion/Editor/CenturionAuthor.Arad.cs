using System.IO;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    public static partial class CenturionAuthor
    {
        private const string AradKey = "baanish_centurion_arad8";

        private static Object AuthorAradMount(Object stockMount)
        {
            var stock = new SerializedObject(stockMount);
            var info = Prop(stock, "info").objectReferenceValue;  // the stock ARAD-116, not a copy
            AssetDatabase.DeleteAsset(ModFolder + "/Centurion_Arad8_Info.asset");

            var root = Object.Instantiate((GameObject)Prop(stock, "prefab").objectReferenceValue);
            try
            {
                var missiles = root.GetComponentsInChildren(GameType("MountedMissile"));
                if (missiles.Length != 4)
                    throw new InvalidDataException("ARAD-116 x8 requires the stock x4's four mounted missiles");
                foreach (var missile in missiles)
                {
                    var position = missile.transform.localPosition;
                    if (Mathf.Abs(Mathf.Abs(position.x) - 0.3f) > 0.001f ||
                        Mathf.Min(Mathf.Abs(position.y + 0.174f), Mathf.Abs(position.y - 0.344f)) > 0.001f ||
                        Mathf.Abs(position.z + 0.03f) > 0.001f)
                        throw new InvalidDataException("ARAD-116 x4's stock layout changed");
                    var outer = Object.Instantiate(missile.gameObject, missile.transform.parent, false);
                    outer.transform.localPosition = new Vector3(Mathf.Sign(position.x) * 0.9f, position.y, position.z);
                }
                missiles = root.GetComponentsInChildren(GameType("MountedMissile"));
                if (missiles.Length != 8)
                    throw new InvalidDataException("ARAD-116 x8 requires eight mounted missiles");
                for (var i = 0; i < missiles.Length; i++)
                {
                    var missile = missiles[i];
                    // The stock x4 names two siblings "ARM1", which SavePrefab refuses (Blueprinter's path re-linking).
                    missile.name = "arad_" + i;
                    var weapon = new SerializedObject(missile);
                    if (Prop(weapon, "ammo").intValue != 1)
                        throw new InvalidDataException("Each ARAD-116 slot requires one round");
                    Prop(weapon, "info").objectReferenceValue = info;
                    weapon.ApplyModifiedPropertiesWithoutUndo();
                }

                var mount = Object.Instantiate(stockMount);
                mount.name = "Centurion_Arad8";
                var so = new SerializedObject(mount);
                Prop(so, "jsonKey").stringValue = AradKey;
                Prop(so, "mountName").stringValue = "ARAD-116 x8";
                Prop(so, "prefab").objectReferenceValue = SavePrefab(root, ModFolder + "/Centurion_Arad8.prefab");
                Prop(so, "info").objectReferenceValue = info;
                Num(so, "ammo", missiles.Length);
                // The exported stock mount's cached mass can be stale; use its WeaponInfo's per-round mass.
                Num(so, "mass", Prop(so, "emptyMass").floatValue +
                    Prop(new SerializedObject(info), "massPerRound").floatValue * missiles.Length);
                so.ApplyModifiedPropertiesWithoutUndo();
                return SaveAsset(mount, ModFolder + "/Centurion_Arad8.asset");
            }
            finally { Object.DestroyImmediate(root); }
        }
    }
}
