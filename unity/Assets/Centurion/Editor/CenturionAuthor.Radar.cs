using UnityEditor;
using UnityEngine;

namespace Centurion.Editor
{
    public static partial class CenturionAuthor
    {
        // These names are also the built-in slots in RadarSuite.
        private const string FrontRadarName = "radar_F_fairing";
        private const string RearRadarName = "radar_R";

        private static void BuildRadars(Build b)
        {
            var front = b.Parts[FrontRadarName].GetComponent(GameType("Radar"));
            Set(front, "attachedUnit", b.Aircraft);
            Set(front, "part", b.Part(FrontRadarName));
            TuneAirframeRadar(front, 60000f);

            var rear = new GameObject(RearRadarName);
            rear.transform.SetParent(b.Parts["tailcone"].transform, false);
            rear.transform.SetPositionAndRotation(b.Blockout.Local("radar_R_fairing"), Quaternion.LookRotation(Vector3.back, Vector3.up));
            var radar = rear.AddComponent(GameType("Radar"));
            Set(radar, "attachedUnit", b.Aircraft);
            Set(radar, "scanner", rear.transform);
            Set(radar, "part", b.Part("tailcone"));
            TuneAirframeRadar(radar, 40000f);
            b.Report.Add("radars: nose 60000 m and tail 40000 m, 60 deg half-cones, 4 s scans");
        }

        private static void TuneAirframeRadar(Component radar, float range)
        {
            Set(radar, "RadarParameters.maxRange", range);
            Set(radar, "RadarParameters.maxSignal", 4f);
            Set(radar, "RadarParameters.minSignal", 0.5f);
            Set(radar, "RadarParameters.clutterFactor", 0.3f);
            Set(radar, "RadarParameters.dopplerFactor", 0.1f);
            Set(radar, "radarCone", 60f);
            Set(radar, "jamTolerance", 0.5f);
            Set(radar, "powerDraw", 3f);
            Set(radar, "checkInterval", 4f);
            Set(radar, "alertCheckInterval", 4f);
            Set(radar, "visualRange", 0f);
            Set(radar, "magnification", 0f);
            Set(radar, "maxSpeed", 0f);
            var so = new SerializedObject(radar);
            Prop(so, "rotators").arraySize = 0;
            Prop(so, "shared").boolValue = false;
            so.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}
