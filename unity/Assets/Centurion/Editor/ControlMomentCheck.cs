using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace Centurion.Editor
{
    // Checks from geometry alone that every control surface turns the aircraft the way its input asks. For each channel
    // with a range, a +1 input deflects the surface toward that range about its hinge (ControlSurfaceJob_Math: visibleMesh
    // turns about its local X and carries the lift transform under it). That changes the part's lift in level airflow from
    // ahead (AeroJob_Math: -normalize(Cross(v, liftRight)) x Cl(alpha), odd and rising through zero), and the change,
    // applied at the part's centre of mass plus centerOfLift as AeroPart.ApplyJobFields does, must turn the aircraft about
    // its centre of mass the way the fly-by-wire closes its loops (ControlsFilter.FlyByWire.Filter): +pitch nose down
    // (+x), +roll right wing down (-z), +yaw nose right (+y). A flipped range, a hinge along the wrong axis, a lift
    // transform that doesn't turn with the surface, or a V-tail mixing pitch and yaw with one side's sign wrong all fail.
    internal static class ControlMomentCheck
    {
        private const float ProbeDeg = 1f;
        // A channel's net moment on another axis, as a fraction of its own: the V-tail's yaw rolls the aircraft about 0.4
        // as much as it yaws it (the ruddervators sit above the CoM), and one side's sign wrong gives well over 1.
        private const float CrossCouplingLimit = 0.6f;

        private static readonly (string Name, string Range, int Axis, float Sign)[] Channels =
        {
            ("pitch", "pitchRange", 0, 1f), ("roll", "rollRange", 2, -1f), ("yaw", "yawRange", 1, 1f),
        };

        public static List<string> Problems(GameObject prefab, List<string> notes)
        {
            var problems = new List<string>();
            var root = prefab.transform;
            var cg = CenterOfMass(prefab);
            var totals = new Vector3[Channels.Length];
            var counts = new int[Channels.Length];
            foreach (var surface in prefab.GetComponentsInChildren(GameType("ControlSurface"), true))
            {
                var so = new SerializedObject(surface);
                if (so.FindProperty("flap").boolValue)
                    continue; // a flap ignores the stick
                var visible = ((GameObject)so.FindProperty("visibleMesh").objectReferenceValue).transform;
                var part = new SerializedObject(so.FindProperty("attachedSurface").objectReferenceValue);
                var partTransform = ((Component)part.targetObject).transform;
                var lift = (Transform)part.FindProperty("liftNormal").objectReferenceValue ?? partTransform;
                var com = (Transform)part.FindProperty("centerOfMass").objectReferenceValue ?? partTransform;
                var liftRest = Quaternion.Inverse(root.rotation) * lift.rotation;
                var hinge = root.InverseTransformDirection(visible.right);
                var arm = root.InverseTransformPoint(com.position) + liftRest * part.FindProperty("centerOfLift").vector3Value - cg;
                var turns = lift.IsChildOf(visible);
                for (var c = 0; c < Channels.Length; c++)
                {
                    var range = so.FindProperty(Channels[c].Range).floatValue;
                    if (range == 0)
                        continue;
                    var deflected = turns ? Quaternion.AngleAxis(Mathf.Sign(range) * ProbeDeg, hinge) * liftRest : liftRest;
                    var moment = Vector3.Cross(arm, Lift(deflected) - Lift(liftRest));
                    totals[c] += moment;
                    counts[c]++;
                    notes.Add($"control {surface.name} {Channels[c].Name} {range:+0;-0}: moment {Format(moment)}");
                    if (moment[Channels[c].Axis] * Channels[c].Sign <= 0)
                        problems.Add($"{surface.name}'s +{Channels[c].Name} turns the aircraft the wrong way or not at all: moment {Format(moment)}");
                }
            }
            for (var c = 0; c < Channels.Length; c++)
            {
                var own = totals[c][Channels[c].Axis] * Channels[c].Sign;
                if (counts[c] == 0 || own <= 0)
                {
                    problems.Add($"+{Channels[c].Name} turns the aircraft the wrong way or not at all: net moment {Format(totals[c])} from {counts[c]} surfaces");
                    continue;
                }
                for (var axis = 0; axis < 3; axis++)
                    if (axis != Channels[c].Axis && Mathf.Abs(totals[c][axis]) > CrossCouplingLimit * own)
                        problems.Add($"+{Channels[c].Name}'s net moment {Format(totals[c])} turns the aircraft more about {"xyz"[axis]} than {CrossCouplingLimit} of its own axis");
            }
            notes.Add($"control moments about the CoM, +1 input, {ProbeDeg:0} deg probe in unit airflow (+x nose down, +y nose right, -z right wing down):"
                + $" pitch {Format(totals[0])}, roll {Format(totals[1])}, yaw {Format(totals[2])}");
            return problems;
        }

        // The game's lift direction and sign for unit airflow along the aircraft's forward, with a lift slope of 1 per rad.
        private static Vector3 Lift(Quaternion lift)
        {
            var v = Vector3.forward;
            var local = Quaternion.Inverse(lift) * v;
            return -Vector3.Cross(v, lift * Vector3.right).normalized * Mathf.Atan2(local.y, local.z);
        }

        // Empty: the parts' own masses at their CoM children, in the root's frame.
        private static Vector3 CenterOfMass(GameObject prefab)
        {
            var sum = Vector3.zero;
            var mass = 0f;
            foreach (var part in prefab.GetComponentsInChildren(GameType("AeroPart"), true))
            {
                var so = new SerializedObject(part);
                var m = so.FindProperty("mass").floatValue;
                var com = (Transform)so.FindProperty("centerOfMass").objectReferenceValue ?? part.transform;
                sum += m * prefab.transform.InverseTransformPoint(com.position);
                mass += m;
            }
            return sum / mass;
        }

        private static string Format(Vector3 v) => $"({v.x:+0.000;-0.000}, {v.y:+0.000;-0.000}, {v.z:+0.000;-0.000})";

        private static Type GameType(string name) =>
            Type.GetType(name + ", Assembly-CSharp") ?? throw new TypeLoadException("Game type " + name + " isn't loaded");
    }
}
