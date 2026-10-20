using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Centurion.Editor
{
    public static partial class CenturionAuthor
    {
        private static void PlaceWingtipLights(Build b)
        {
            foreach (var side in new[] { "L", "R" })
            {
                var stage = b.Parts["wing_tip_" + side].transform;
                var tip = b.Meshes[stage.name].Shape.vertices.Select(stage.TransformPoint)
                    .OrderByDescending(v => Mathf.Abs(v.x)).First();
                var nav = stage.Find("navlight_" + side);
                // The donor lamp's mesh centre is almost a metre outboard of its pivot. Mount the lamp on the
                // rounded tip's actual outermost vertex, not the empty corner of its bounding box.
                nav.position = tip - nav.TransformVector(nav.GetComponent<MeshFilter>().sharedMesh.bounds.center);
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
    }
}
