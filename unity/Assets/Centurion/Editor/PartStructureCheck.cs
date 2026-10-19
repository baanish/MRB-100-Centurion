using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Centurion.Editor
{
    // Checks that the aircraft holds together on the peer that simulates it. There Aircraft.SetComplexPhysics gives every
    // AeroPart with mass its own Rigidbody (AeroPart.CreateRB) and turns each serialized PartJoint into a FixedJoint at
    // ten times its break force and torque (AeroPart.CreateJoints); Aircraft.PartChecker then runs
    // AeroPart.CheckAttachment, which detaches any part more than 0.5 m from where it spawned in its parent part's frame
    // (UnitPart.CreateAttachInfo takes that spawn offset in Awake, so it can't be authored wrong, only drift).
    internal static class PartStructureCheck
    {
        public const float DetachDistance = 0.5f;
        // A settled part may move this far in its parent's frame; sound parts hold to about a millimetre. An unbraced
        // chain of FixedJoints (wing_root and two stages) sags about 3 cm at the tip, and more solver iterations
        // don't stiffen it (they raise the peak joint load), so M2's unbraced sliding stages need their own figure.
        public const float SettleTolerance = 0.01f;
        private const float SettleSeconds = 3f;
        private const float Step = 1f / 60f; // the game's Fixed Timestep

        // The game's layer collision matrix (its ProjectSettings/DynamicsManager.asset): the layers each layer collides
        // with. Every other pair, the Cockpit interior layer 3 included, never collides. This project collides everything.
        private static readonly Dictionary<int, int[]> StockCollisions = new Dictionary<int, int[]>
        {
            { 0, new[] { 0, 6, 11, 14 } }, { 6, new[] { 0, 10, 11, 14 } }, { 10, new[] { 6, 11 } },
            { 11, new[] { 0, 6, 10, 11, 14 } }, { 14, new[] { 0, 6, 11, 14 } },
        };

        public sealed class SettledPart
        {
            public string Name, Parent;
            public float MaxDrift, WorstForceRatio, WorstTorqueRatio;
            public int DetachStep = -1, BrokenJoints;
        }

        // Every structural problem with the prefab, and notes on how the settle went.
        public static List<string> Problems(GameObject prefab, List<string> notes)
        {
            var aeroType = GameType("AeroPart");
            var problems = new List<string>();
            foreach (var part in prefab.GetComponentsInChildren(aeroType, true))
            {
                var so = new SerializedObject(part);
                var joints = so.FindProperty("joints");
                // UnitPart.Awake takes the part on the transform parent as the parent part; the root has none.
                var parent = part.transform.parent != null ? part.transform.parent.GetComponent(aeroType) : null;
                if (part.transform.parent == null)
                {
                    if (joints.arraySize != 0)
                        problems.Add("the root part has joints");
                    continue;
                }
                if (parent == null)
                {
                    problems.Add(part.name + " isn't a direct child of a part");
                    continue;
                }
                // AeroPart.Awake reads joints[0] as the attachment; CreateRB fills an empty joints[0] with the parent.
                var toParent = Enumerable.Range(0, joints.arraySize).Where(i => joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue == parent).ToArray();
                if (toParent.Length != 1 || toParent[0] != 0)
                    problems.Add($"{part.name}: {toParent.Length} PartJoints to its parent {parent.name}{(toParent.Length == 1 ? " but not first" : "")}; it needs exactly one, as joints[0]");
                // UnitPart.Awake sizes a part (collisionSize) from the collider on its own GameObject only. Without one,
                // AeroJob_Math divides by that zero size and throws the NaN force away: the part makes no lift or drag. Its
                // Rigidbody would also get Unity's unit inertia tensor (1 kg m2 whatever its mass), which the joint solver
                // can't hold still, and aero torque (AeroPart.ApplyJobFields) spins.
                if (!part.GetComponents<Collider>().Any(c => !c.isTrigger))
                    problems.Add($"{part.name}: no collider on its own GameObject, so the game drops its lift and drag");
            }
            problems.AddRange(RadarMountProblems(prefab, notes));

            var settled = Settle(prefab, SettleSeconds);
            foreach (var p in settled.Where(p => p.MaxDrift > SettleTolerance || p.BrokenJoints > 0))
                problems.Add($"{Describe(p)} (tolerance {SettleTolerance * 100:0} cm)");
            notes.Add($"settled {settled.Count} parts {SettleSeconds:0} s parked; most drift: " + string.Join("; ", settled.Take(3).Select(Describe)));
            return problems;
        }

        // Replays SetComplexPhysics on a copy of the prefab in a scene of its own and lets it settle, the root held still
        // in place of the gear, with the game's step, gravity, solver and depenetration settings and layer matrix.
        // Worst drift first.
        public static List<SettledPart> Settle(GameObject prefab, float seconds)
        {
            var aeroType = GameType("AeroPart");
            if (Physics.gravity != new Vector3(0, -9.81f, 0) || Physics.defaultSolverIterations != 6 || Physics.defaultSolverVelocityIterations != 1)
                throw new InvalidOperationException("The project's gravity or solver iterations differ from the game's (-9.81, 6, 1)");
            var scene = EditorSceneManager.NewPreviewScene();
            try
            {
                var instance = Object.Instantiate(prefab);
                SceneManager.MoveGameObjectToScene(instance, scene);
                var colliders = instance.GetComponentsInChildren<Collider>(true);
                for (var i = 0; i < colliders.Length; i++)
                    for (var j = i + 1; j < colliders.Length; j++)
                        if (!(StockCollisions.TryGetValue(colliders[i].gameObject.layer, out var hits) && hits.Contains(colliders[j].gameObject.layer)))
                            Physics.IgnoreCollision(colliders[i], colliders[j]);

                var root = instance.GetComponent<Rigidbody>();
                var parts = instance.GetComponentsInChildren(aeroType, true);
                var serialized = parts.ToDictionary(p => p, p => new SerializedObject(p));
                var attach = new Dictionary<Component, (Component parent, Vector3 local)>();
                foreach (var part in parts.Where(p => p.transform.parent != null && p.transform.parent.GetComponent(aeroType) != null))
                {
                    var parent = part.transform.parent.GetComponent(aeroType);
                    attach[part] = (parent, parent.transform.InverseTransformPoint(part.transform.position));
                }
                root.isKinematic = true;
                var body = parts.ToDictionary(p => p, p => root);
                foreach (var part in parts.Where(p => attach.ContainsKey(p) && serialized[p].FindProperty("mass").floatValue != 0))
                {
                    part.transform.SetParent(null, true);
                    var rb = part.gameObject.AddComponent<Rigidbody>();
                    rb.mass = serialized[part].FindProperty("mass").floatValue;
                    rb.drag = 0;
                    rb.angularDrag = 0;
                    rb.sleepThreshold = 0;
                    body[part] = rb;
                }
                foreach (var rb in body.Values.Distinct())
                    rb.maxDepenetrationVelocity = 5;
                Physics.SyncTransforms();
                var joints = new List<(Component part, FixedJoint joint, float force, float torque)>();
                foreach (var part in parts.Where(p => body[p] != root))
                {
                    var list = serialized[part].FindProperty("joints");
                    for (var i = 0; i < list.arraySize; i++)
                    {
                        var element = list.GetArrayElementAtIndex(i);
                        var connected = (Component)element.FindPropertyRelative("connectedPart").objectReferenceValue ?? (i == 0 ? attach[part].parent : null);
                        if (connected == null || !body.ContainsKey(connected))
                            throw new InvalidOperationException(part.name + " has a PartJoint to nothing on the aircraft");
                        var joint = part.gameObject.AddComponent<FixedJoint>();
                        var anchor = (Transform)element.FindPropertyRelative("anchor").objectReferenceValue;
                        if (anchor != null)
                            joint.anchor = anchor.position - body[part].position;
                        joint.connectedBody = body[connected];
                        joint.enableCollision = false;
                        var force = element.FindPropertyRelative("breakForce").floatValue * 10f;
                        var torque = element.FindPropertyRelative("breakTorque").floatValue * 10f;
                        joint.breakForce = force;
                        joint.breakTorque = torque;
                        var solver = element.FindPropertyRelative("solverIterations").intValue;
                        if (solver != 6)
                            body[part].solverIterations = solver;
                        joints.Add((part, joint, force, torque));
                    }
                }

                var results = attach.ToDictionary(a => a.Key, a => new SettledPart { Name = a.Key.name, Parent = a.Value.parent.name });
                for (var step = 1; step <= Mathf.RoundToInt(seconds / Step); step++)
                {
                    scene.GetPhysicsScene().Simulate(Step);
                    foreach (var (part, joint, force, torque) in joints.Where(j => j.joint != null))
                    {
                        results[part].WorstForceRatio = Mathf.Max(results[part].WorstForceRatio, joint.currentForce.magnitude / force);
                        results[part].WorstTorqueRatio = Mathf.Max(results[part].WorstTorqueRatio, joint.currentTorque.magnitude / torque);
                    }
                    foreach (var (part, (parent, local)) in attach)
                    {
                        var drift = Vector3.Distance(parent.transform.InverseTransformPoint(part.transform.position), local);
                        results[part].MaxDrift = Mathf.Max(results[part].MaxDrift, drift);
                        if (drift > DetachDistance && results[part].DetachStep < 0)
                            results[part].DetachStep = step;
                    }
                }
                foreach (var (part, joint, _, _) in joints.Where(j => j.joint == null))
                    results[part].BrokenJoints++;
                return results.Values.OrderByDescending(r => r.MaxDrift).ToList();
            }
            finally
            {
                EditorSceneManager.ClosePreviewScene(scene);
            }
        }

        // A radar mount whose root is a part (the AWACS beam, as stock Radome1) becomes a rigidbody of its own on the simulating
        // peer, jointed to its hardpoint's part (Hardpoint.SpawnMount, AeroPart.CreateRB and CreateJoints). Its root needs
        // exactly one PartJoint, which CreateRB fills with that part; a collider on its own GameObject; mass above 0, since
        // with 0 CreateRB sets the aircraft's rigidbody mass to it instead; and no parentUnit, so UnitPart.Awake takes the
        // hardpoint's part. A Weapon anywhere in it would make it a selectable station. Every mount an authored loadout
        // carries is checked.
        private static List<string> RadarMountProblems(GameObject aircraft, List<string> notes)
        {
            var problems = new List<string>();
            var definition = new SerializedObject(new SerializedObject(aircraft.GetComponent(GameType("Aircraft"))).FindProperty("definition").objectReferenceValue);
            var parameters = new SerializedObject(definition.FindProperty("aircraftParameters").objectReferenceValue);
            var mounts = new HashSet<Object>();
            void Collect(SerializedProperty weapons)
            {
                for (var i = 0; i < weapons.arraySize; i++)
                    if (weapons.GetArrayElementAtIndex(i).objectReferenceValue is Object mount && mount != null)
                        mounts.Add(mount);
            }
            var loadouts = parameters.FindProperty("loadouts");
            for (var i = 0; i < loadouts.arraySize; i++)
                Collect(loadouts.GetArrayElementAtIndex(i).FindPropertyRelative("weapons"));
            var standard = parameters.FindProperty("StandardLoadouts");
            for (var i = 0; i < standard.arraySize; i++)
                Collect(standard.GetArrayElementAtIndex(i).FindPropertyRelative("loadout").FindPropertyRelative("weapons"));

            var aeroType = GameType("AeroPart");
            foreach (var mount in mounts)
            {
                var so = new SerializedObject(mount);
                var prefab = so.FindProperty("prefab").objectReferenceValue as GameObject;
                if (!so.FindProperty("radar").boolValue || prefab == null || prefab.GetComponent(aeroType) == null)
                    continue;
                var key = so.FindProperty("jsonKey").stringValue;
                var part = new SerializedObject(prefab.GetComponent(aeroType));
                var joints = part.FindProperty("joints").arraySize;
                var colliders = prefab.GetComponents<Collider>().Count(c => !c.isTrigger);
                var mass = part.FindProperty("mass").floatValue;
                var weapons = prefab.GetComponentsInChildren(GameType("Weapon"), true).Length;
                if (joints != 1)
                    problems.Add($"radar mount {key}: {joints} PartJoints on its root part; it needs exactly one, or its rigidbody drifts off the hardpoint and detaches");
                if (colliders == 0)
                    problems.Add($"radar mount {key}: no collider on its root part's own GameObject");
                if (mass <= 0)
                    problems.Add($"radar mount {key}: root part mass {mass}; at 0 CreateRB sets the aircraft's rigidbody mass to 0");
                if (part.FindProperty("parentUnit").objectReferenceValue != null)
                    problems.Add($"radar mount {key}: its root part names a parentUnit; UnitPart.Awake must take the hardpoint's part");
                if (weapons > 0)
                    problems.Add($"radar mount {key}: {weapons} Weapon components, which would make it a weapon station");
                notes.Add($"radar mount {key}: {joints} PartJoint, {colliders} root colliders, {mass:0} kg, {weapons} Weapon components");
            }
            return problems;
        }

        public static string Describe(SettledPart p) =>
            $"{p.Name} moved {p.MaxDrift * 100:0.0} cm on {p.Parent}{(p.DetachStep > 0 ? $", past the {DetachDistance} m detach line at {p.DetachStep * Step:0.00} s" : "")}" +
            $"{(p.BrokenJoints > 0 ? $", {p.BrokenJoints} joints broke" : "")}, peak joint load {p.WorstForceRatio:P0} of break force, {p.WorstTorqueRatio:P0} of break torque";

        private static Type GameType(string name) =>
            Type.GetType(name + ", Assembly-CSharp") ?? throw new TypeLoadException("Game type " + name + " isn't loaded");
    }
}
