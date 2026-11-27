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
        // Each part's donor on the stock SFB-81 Darkreach, the Centurion's BDF sibling (docs/DECISIONS.md 2026-11-21): the
        // Darkreach part that does its job (art/blender/damage_tree.py, the part map's "Section boundaries"). A part takes
        // its donor's armour, hit points, thresholds, impact damage and fragments as they stand in the game's asset, and its
        // joints the donor's strength per kilogram carried (DonorJointForce). Right-side parts take the left-side donor,
        // which the Darkreach mirrors.
        private static readonly Dictionary<string, string> PartDonors = new Dictionary<string, string>
        {
            { "Centurion", "Darkreach" }, { "radome", "nose" }, { "cockpit", "cockpit" }, { "fuselage_F", "fuselage_F" },
            { "bay_F", "gearbay_L" }, { "fuselage_R", "fuselage_R" }, { "bay_A", "gearbay_L" }, { "tailcone", "tail" },
            { "tail_end", "tail" },
            { "wing_root_L", "wing1b_L" }, { "wing_root_R", "wing1b_L" }, { "wing_outer_L", "wing2_L" }, { "wing_outer_R", "wing2_L" },
            { "wing_tele1_L", "wing2_L" }, { "wing_tele1_R", "wing2_L" }, { "wing_tele2_L", "wingtip_L" }, { "wing_tele2_R", "wingtip_L" },
            { "strut_inner_L", "wing1a_L" }, { "strut_inner_R", "wing1a_L" }, { "strut_outer_L", "wing1a_L" }, { "strut_outer_R", "wing1a_L" },
            { "pylon_1", "nacelle_L" }, { "pylon_2", "nacelle_L" }, { "nacelle_1", "engine_L" }, { "nacelle_2", "engine_L" },
            { "nozzle_1", "nozzle_L" }, { "nozzle_2", "nozzle_L" }, { "sponson_L", "gearbay_L" }, { "sponson_R", "gearbay_L" },
            { "vtail_L", "vstab1_L" }, { "vtail_R", "vstab1_L" }, { "vtail_tip_L", "vstab2_L" }, { "vtail_tip_R", "vstab2_L" },
            { "flap_L1", "flap_L" }, { "flap_L2", "flap_L" }, { "flap_R1", "flap_L" }, { "flap_R2", "flap_L" },
            { "ruddervator_L1", "rudder_L" }, { "ruddervator_L2", "rudder_L" }, { "ruddervator_R1", "rudder_L" }, { "ruddervator_R2", "rudder_L" },
            { "aileron_L", "aileron_L" }, { "aileron_R", "aileron_L" }, { "spoiler_L", "aileron_L" }, { "spoiler_R", "aileron_L" },
        };

        // The heaviest store each hardpoint registers, which its part's joint carries with the part (the part map's joint
        // table): the forward bay's PAB-80LR x196, the aft bay's AGM-99 x60 or PAB-80LR x216, the AWACS radome on the
        // spine, the C-RAM on the tail end.
        private static readonly Dictionary<string, float> HeaviestStoreKg = new Dictionary<string, float>
        {
            { "bay_F", 24500f }, { "bay_A", 27000f }, { "fuselage_R", 6000f }, { "tail_end", 300f },
        };

        // The fields a part copies from its donor.
        private static readonly string[] DonorDamageFields =
            { "hitPoints", "armorProperties", "impactDamage", "structuralThreshold", "integrityThreshold", "disintegrationEffects" };

        // A light airframe (owner, 2026-11-22, docs/DECISIONS.md): any missile hit is a kill, while a fighter cannon needs a
        // sustained burst, and the kill is the stock one ("keep it stock"): a wing, the tail or the nose leaving, the crew
        // lost, the ground. No part is critical, as on every stock aircraft. Every part keeps its donor's 100 hit points (the
        // stock rescale sets joint strength from them, AeroPart.ApplyDamage) and fire and impact tolerances (the fire chain
        // and landings do not move). Each kind divides its donor's pierce and blast tolerances by its own factors, which
        // multiply what a hit does. Blast is what a missile's fragments, flak and a cannon shell's small charge deal; pierce
        // is a cannon round's and a missile's penetrator's. At the donor's values a missile left
        // the tail cone 65 pierce and 34 blast from behind (4 makes it 202), the cockpit 12 pierce and 128 to 158 blast
        // head-on (the owner's cap of 1.5 makes it 204), and the rear fuselage about 246 from the side. One 27 mm round put
        // about 108 hp of pierce and 16 of blast into a wing, so structure takes a quarter of its donor's pierce and its blast
        // as is: about four rounds to sever a wing, and the cannon from astern takes the tail in 2 to 3 s, as on a Darkreach.
        private static readonly (float Pierce, float Blast, string[] Prefixes)[] LightAirframe =
        {
            (1f, 2f, new[] { "flap_", "aileron_", "spoiler_", "ruddervator_", "radome", "vtail_tip_" }),
            (1f, 1.5f, new[] { "cockpit" }),
            (1f, 4f, new[] { "Centurion", "fuselage_F", "fuselage_R", "tailcone", "tail_end" }),
            (1f, 2f, new[] { "bay_F", "bay_A" }),
            // A destroyed nacelle takes its wing (WingRootTrips), so the engine takes a fighter's rounds and shell splash
            // more slowly than structure: at structure's factors a burst on the engines took one in under a second, faster
            // than through the wing root. A missile's blast on it (about 500 hp at structure's factors) and a forward bay's
            // cook-off (about 480) still destroy it twice over at half.
            (0.1f, 0.5f, new[] { "nacelle_" }),
        };
        // Every other part: wing roots, outer wings, stages, struts, pylons, nacelles, sponsons, fins.
        private static readonly (float Pierce, float Blast) Structure = (0.25f, 1f);

        // Blast armour is deliberately the donor's everywhere, the centre section's 70 included. Every fragment ray from
        // below crosses the centre and gains 0.1 m of virtual distance per point (DamageEffects.FragTrace), so a missile
        // from directly below takes only flaps, as on the Darkreach (docs/DECISIONS.md, 2026-11-22).

        private static (float Pierce, float Blast) DamageScale(string part) =>
            LightAirframe.Where(k => k.Prefixes.Any(p => part == p || (p.EndsWith("_") && part.StartsWith(p))))
                .Select(k => (k.Pierce, k.Blast)).DefaultIfEmpty(Structure).First();

        private static float ToleranceFactor(string part, string field) =>
            field == "pierceTolerance" ? DamageScale(part).Pierce : field == "blastTolerance" ? DamageScale(part).Blast : 1f;

        private static readonly string[] ArmourFields =
            { "pierceArmor", "blastArmor", "fireArmor", "pierceTolerance", "blastTolerance", "fireTolerance", "overpressureLimit" };

        // The dry centre of gravity 0.1.3 flew with, retracted: each part's mass at its rigid body's centre of mass
        // (art/blender/damage_finalize.py), station and height above the ground in metres; extended, the stages' strokes
        // with 0.1.3's stage masses move it 0.318 m aft and 0.054 m down (the part map's "Centre of gravity").
        private static readonly Vector2 ShippedCg = new Vector2(20.575f, 4.498f), ShippedCgExtended = new Vector2(20.893f, 4.444f);
        private const float CgTolerance = 0.02f;
        private const int PartCount = 45, ShapeCount = 47;
        // AIPilotCombatModes.EjectionCheck bails out above 40 m when PartDamageTracker.GetDetachedRatio() > 0.12
        // (AIPilotCombatModes.cs:1241): a wing tear and one more lost part must stay under it, with the AWACS beam's mount
        // part fitted too.
        private const float EjectionRatio = 0.12f;

        private static Component DonorPart(string donor)
        {
            var darkreach = Load<GameObject>(DarkreachPrefab);
            var parts = darkreach.GetComponentsInChildren(GameType("AeroPart"), true);
            return donor == "Darkreach" ? darkreach.GetComponent(GameType("AeroPart"))
                : parts.SingleOrDefault(p => p.name == donor) ?? throw new MissingReferenceException("The Darkreach has no part " + donor);
        }

        private static float Mass(Component part) => new SerializedObject(part).FindProperty("mass").floatValue;

        // A part and everything hanging from it: its own and its descendants' dry masses and their heaviest stores.
        private static float CarriedKg(Build b, string part) =>
            b.Parts[part].GetComponentsInChildren(GameType("AeroPart"), true).Sum(p => Mass(p) + (HeaviestStoreKg.TryGetValue(p.name, out var kg) ? kg : 0f));

        // The donor's parent-joint force per kilogram of its own dry subtree, times the kilograms this part's joint carries:
        // a joint as strong for its load as the Darkreach's for its own.
        private static float DonorScaledForce(Build b, string part)
        {
            var donor = DonorPart(PartDonors[part]);
            var joints = new SerializedObject(donor).FindProperty("joints");
            if (joints.arraySize == 0)
                throw new InvalidDataException($"{part}'s donor {donor.name} has no joint to scale");
            var donorForce = joints.GetArrayElementAtIndex(0).FindPropertyRelative("breakForce").floatValue;
            var donorCarried = donor.GetComponentsInChildren(GameType("AeroPart"), true).Sum(Mass);
            return donorForce / donorCarried * CarriedKg(b, part);
        }

        // The parts whose braces carry main loads against the parts they brace: the
        // sponsons hold the main gear against the body, the bays and the tail cone; the struts hold the engines and the wing
        // against the body; the wing roots hold the wing against the body sections. A brace is as strong as its owner's
        // joint, so the solver shares the load across it and the tree joints between its two parts; a brace between two
        // such parts with a weaker joint on either side breaks that joint first, at full health (0.1.3 lost skin panels on
        // the runway that way). So each such brace ties its two parts to the stronger joint of the pair, and a part that
        // carries only itself keeps its donor-scaled strength and can break under load as a stock section does.
        private static readonly HashSet<string> MainLoadBraceOwners = new HashSet<string>
        {
            "sponson_L", "sponson_R", "strut_inner_L", "strut_inner_R", "strut_outer_L", "strut_outer_R", "wing_root_L", "wing_root_R",
        };

        // The +4 g design load at 199 t: every lifting part's share of the lift, over the whole lifting area at full span,
        // which TelescopeController adds to stage 1 and the roll surfaces (its StageAreaM2, AileronAreaM2, SpoilerAreaM2).
        private const float DesignLoadFactor = 4f, DesignMassKg = 199000f;
        private static readonly Dictionary<string, float> ExtensionAreaM2 = new Dictionary<string, float>
        {
            { "wing_tele1_L", 266f }, { "wing_tele1_R", 266f }, { "aileron_L", 54f }, { "aileron_R", 54f }, { "spoiler_L", 18f }, { "spoiler_R", 18f },
        };
        // An engine's thrust at its speed curve's peak, which its JetNozzle puts on the nozzle part (JetNozzle.cs:409).
        private const float MaxThrustN = 330000f * 1.25f;

        private static float LiftAreaM2(Component part) =>
            new SerializedObject(part).FindProperty("wingArea").floatValue + (ExtensionAreaM2.TryGetValue(part.name, out var add) ? add : 0f);

        // The main load a part's joint carries besides weight: the lift of the part and everything on it at the design
        // load, and an engine's thrust where a nozzle hangs from it. The tail's moving surfaces carry 6.5 times their drawn
        // area (Surfaces), so donor scaling by mass leaves the V-tail's joints far short of their lift.
        private static float LoadFloorN(Build b, string part)
        {
            var aeroType = GameType("AeroPart");
            var all = b.Root.GetComponentsInChildren(aeroType, true);
            var liftPerM2 = DesignLoadFactor * DesignMassKg * 9.81f / all.Sum(LiftAreaM2);
            var subtree = b.Parts[part].GetComponentsInChildren(aeroType, true);
            var thrust = b.Parts[part].GetComponentsInChildren(GameType("JetNozzle"), true).Length * MaxThrustN;
            return Mathf.Max(subtree.Sum(LiftAreaM2) * liftPerM2, thrust);
        }

        // Parts rated at their parent's strength per kilogram carried instead of their donor's. The radome hangs about 17 m
        // ahead of the centre of gravity, against the Darkreach nose's 13 m, so a pitch kick loads it harder: a stock
        // fragmentation shove from the aft bay's 100 kg cook-off turned the airframe 33 deg/s in one step and put 59 g on
        // the nose donor's 62 g joint (in game), which broke at full health. At the cockpit's rating it holds about 113 kN;
        // it still comes off at 0 hp, where the stock rescale sets a structural-threshold-0 part's joints to 0
        // (AeroPart.ApplyDamage).
        private static readonly Dictionary<string, string> RatedLikeParent = new Dictionary<string, string> { { "radome", "cockpit" } };

        // Parts tied to a neighbour's main-load group though no brace joins them. The tail end hangs 19 m behind the centre
        // of gravity on a 140 kN donor-scaled joint, and a 2,500 fpm touchdown broke it at full health before any leg, at
        // 199 t and light; the owner's gear ruling wants the legs to give first. At
        // the tail cone's group strength it leaves only when it or the tail cone is destroyed.
        private static readonly Dictionary<string, string> TiedWith = new Dictionary<string, string> { { "tail_end", "tailcone" } };

        // A part's joint force: its donor-scaled force or its load floor, the larger (or its parent's rating, RatedLikeParent),
        // raised to the stronger of each pair a main-load brace ties (MainLoadBraceOwners) or TiedWith names. The telescoping stages' braces
        // are free joints that carry nothing (TelescopeController) and tie nothing.
        private static float DonorJointForce(Build b, string part)
        {
            if (b.JointForce == null)
            {
                var own = b.Joints.Keys.ToDictionary(n => n, n => Mathf.Max(DonorScaledForce(b, n), LoadFloorN(b, n)));
                foreach (var entry in RatedLikeParent)
                    own[entry.Key] = Mathf.Max(own[entry.Key], own[entry.Value] / CarriedKg(b, entry.Value) * CarriedKg(b, entry.Key));
                var group = b.Joints.Keys.ToDictionary(n => n, n => n);
                string Find(string n) => group[n] == n ? n : group[n] = Find(group[n]);
                foreach (var entry in b.Joints.Where(e => MainLoadBraceOwners.Contains(e.Key)))
                    foreach (var other in entry.Value.Skip(1).Where(group.ContainsKey))
                        group[Find(other)] = Find(entry.Key);
                foreach (var entry in TiedWith)
                    group[Find(entry.Key)] = Find(entry.Value);
                b.JointForce = b.Joints.Keys.ToDictionary(n => n, n => b.Joints.Keys.Where(m => Find(m) == Find(n)).Max(m => own[m]));
                foreach (var g in b.Joints.Keys.GroupBy(Find).Where(g => g.Count() > 1))
                    b.Report.Add($"joint tie: {string.Join(", ", g.OrderBy(n => n))} at {g.Max(n => own[n]) / 1000:0} kN, from {g.OrderByDescending(n => own[n]).First()}");
                foreach (var n in b.Joints.Keys.OrderBy(n => n, StringComparer.Ordinal))
                    b.Report.Add($"joint table {n}: donor-scaled {DonorScaledForce(b, n) / 1000:0} kN, load floor {LoadFloorN(b, n) / 1000:0} kN, authored {b.JointForce[n] / 1000:0} kN");
            }
            return b.JointForce[part];
        }

        private static void AuthorDamage(Build b)
        {
            foreach (var entry in b.Parts)
            {
                var donor = new SerializedObject(DonorPart(PartDonors[entry.Key]));
                var so = new SerializedObject(b.Part(entry.Key));
                foreach (var field in DonorDamageFields)
                    so.CopyFromSerializedProperty(Prop(donor, field));
                foreach (var tolerance in new[] { "pierceTolerance", "blastTolerance" })
                    Prop(so, "armorProperties").FindPropertyRelative(tolerance).floatValue =
                        Prop(donor, "armorProperties").FindPropertyRelative(tolerance).floatValue / ToleranceFactor(entry.Key, tolerance);
                Prop(so, "criticalPart").boolValue = false;
                so.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        private static void CheckDamage(Build b)
        {
            var aeroType = GameType("AeroPart");
            var parts = b.Root.GetComponentsInChildren(aeroType, true);
            var problems = new List<string>();
            Physics.SyncTransforms();

            var shapes = parts.Sum(p => p.GetComponents<MeshCollider>().Length);
            if (parts.Length != PartCount || shapes != ShapeCount)
                problems.Add($"{parts.Length} parts with {shapes} collision shapes; the tree has {PartCount} and {ShapeCount}");

            foreach (var part in parts)
            {
                var name = b.Parts.First(p => p.Value == part.gameObject).Key;
                var hulls = part.GetComponents<MeshCollider>();
                if (hulls.Length == 0)
                {
                    problems.Add(name + " has no collision shape");
                    continue;
                }
                // Each shape convex as stored: every face outward and not degenerate, every vertex behind every face.
                foreach (var hull in hulls)
                    problems.AddRange(ShapeFaults(hull.sharedMesh).Select(f => $"{name}'s shape {hull.sharedMesh.name}: {f}"));
                var origin = part.transform.position;
                if (Vector3.Distance(hulls[0].ClosestPoint(origin), origin) > 1e-4f)
                    problems.Add($"{name}'s origin {origin} lies outside its own shape");
                // The donor's damage values, as they stand in the game's asset, but for the light airframe's tolerances.
                var donor = new SerializedObject(DonorPart(PartDonors[name]));
                var so = new SerializedObject(part);
                foreach (var field in DonorDamageFields.Where(f => f != "armorProperties"))
                    if (!SerializedProperty.DataEquals(Prop(so, field), Prop(donor, field)))
                        problems.Add($"{name}'s {field} isn't its donor {PartDonors[name]}'s");
                foreach (var field in ArmourFields)
                {
                    var factor = ToleranceFactor(name, field);
                    var expected = Prop(donor, "armorProperties").FindPropertyRelative(field).floatValue / factor;
                    if (Mathf.Abs(Prop(so, "armorProperties").FindPropertyRelative(field).floatValue - expected) > 1e-4f)
                        problems.Add($"{name}'s {field} isn't its donor {PartDonors[name]}'s{(factor != 1f ? $" over {factor:0.##}" : "")}");
                }
                if (Prop(so, "criticalPart").boolValue)
                    problems.Add($"{name} is a critical part; no stock aircraft has one");
                // A wing root holds its own joint with itself as tensor, then one joint to its engine pylon per trip part with
                // that part as tensor, and nothing else: a joint into the body would hold the wing on when a trip fires.
                var held = Enumerable.Range(0, Prop(so, "joints").arraySize).Select(i => Prop(so, "joints").GetArrayElementAtIndex(i))
                    .Select(j => (To: j.FindPropertyRelative("connectedPart").objectReferenceValue?.name,
                        Tensor: j.FindPropertyRelative("tensor").objectReferenceValue?.name)).ToList();
                if (WingRootTrips.TryGetValue(name, out var trips))
                {
                    var tensors = new[] { name }.Concat(trips).ToList();
                    var targets = new[] { ParentPart(b, name) }.Concat(trips.Select(_ => TripAnchor(b, name))).ToList();
                    if (!held.Select(j => j.Tensor).SequenceEqual(tensors) || !held.Select(j => j.To).SequenceEqual(targets))
                        problems.Add($"{name}'s joints are {string.Join(", ", held.Select(j => $"{j.To} (tensor {j.Tensor ?? "none"})"))}, " +
                            $"not {string.Join(", ", targets.Zip(tensors, (t, s) => $"{t} (tensor {s})"))}");
                }
                // A trip part's every joint break trips its wing, so each brace it owns has a tensor inside that wing.
                var tripped = TrippedWingRoot(name);
                if (tripped != null)
                    foreach (var brace in held.Skip(1).Where(j => j.Tensor == null || !InWing(b, tripped, j.Tensor)))
                        problems.Add($"{name} trips {tripped} but owns a brace to {brace.To} with tensor {brace.Tensor ?? "none"}, outside that wing");
                var scale = DamageScale(name);
                b.Report.Add($"light airframe {name}: pierce x{scale.Pierce:0.##}, blast x{scale.Blast:0.##}");
                var joints = Prop(so, "joints");
                for (var i = 1; i < joints.arraySize; i++)
                    if (joints.GetArrayElementAtIndex(i).FindPropertyRelative("tensor").objectReferenceValue == null)
                        problems.Add($"{name}'s brace to {joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue.name} has no tensor");
                if (joints.arraySize > 0)
                {
                    var force = DonorJointForce(b, name);
                    for (var i = 0; i < joints.arraySize; i++)
                    {
                        var joint = joints.GetArrayElementAtIndex(i);
                        if (Mathf.Abs(joint.FindPropertyRelative("breakForce").floatValue - force) > 1f || joint.FindPropertyRelative("breakTorque").floatValue != joint.FindPropertyRelative("breakForce").floatValue
                            || joint.FindPropertyRelative("anchor").objectReferenceValue != null)
                            problems.Add($"{name}'s joint {i} isn't its donor's strength with torque equal to force and no anchor");
                    }
                    b.Report.Add($"joint {name}: {force / 1000:0} kN (x10 in game; donor {PartDonors[name]} scaled to {CarriedKg(b, name):0} kg carried: {DonorScaledForce(b, name) / 1000:0}); " +
                        string.Join(", ", Enumerable.Range(0, joints.arraySize).Select(i => joints.GetArrayElementAtIndex(i)).Select(j =>
                            j.FindPropertyRelative("connectedPart").objectReferenceValue.name + (j.FindPropertyRelative("tensor").objectReferenceValue is Object t ? " (tensor " + t.name + ")" : ""))));
                }
            }

            foreach (var entry in TiedWith)
                if (DonorJointForce(b, entry.Key) != DonorJointForce(b, entry.Value))
                    problems.Add($"{entry.Key}'s joint is {DonorJointForce(b, entry.Key) / 1000:0} kN, not {entry.Value}'s group strength {DonorJointForce(b, entry.Value) / 1000:0} kN");

            // Jointed neighbours' shapes may overlap no deeper than the Darkreach's own do: once their joint breaks the solver
            // shoves an overlap apart, and stock lives with that much.
            var stock = DeepestJointedOverlap(Load<GameObject>(DarkreachPrefab), _ => false);
            var mine = DeepestJointedOverlap(b.Root, go => b.Blockout.Slide(go.name).HasValue);
            b.Report.Add($"jointed overlaps (not the stages): deepest {mine.Depth * 1000:0} mm, {mine.Pair}; the Darkreach's deepest {stock.Depth * 1000:0} mm, {stock.Pair}");
            if (mine.Depth > stock.Depth)
                problems.Add($"jointed shapes {mine.Pair} overlap {mine.Depth * 1000:0} mm, deeper than the Darkreach's deepest, {stock.Depth * 1000:0} mm ({stock.Pair})");

            // Dry centre of gravity, retracted and extended, against 0.1.3's.
            var slides = Parts.Where(p => b.Blockout.Slide(p.Name).HasValue).Select(p => b.Parts[p.Name].transform)
                .Select(t => (stage: t, rest: t.localPosition, end: t.parent.Find(t.name + "_extended").localPosition)).ToArray();
            Vector2 Cg()
            {
                var cg = CenterOfMass(b);
                return new Vector2(OriginStation - (cg.z + b.Blockout.Origin.z), cg.y + b.Blockout.Origin.y);
            }
            var retracted = Cg();
            foreach (var (stage, _, end) in slides)
                stage.localPosition = end;
            var extended = Cg();
            foreach (var (stage, rest, _) in slides)
                stage.localPosition = rest;
            foreach (var (pose, cg, shipped) in new[] { ("retracted", retracted, ShippedCg), ("extended", extended, ShippedCgExtended) })
            {
                b.Report.Add($"CG {pose}: station {cg.x:F3} m, {cg.y:F3} m up; 0.1.3 {shipped.x:F3}, {shipped.y:F3} ({(cg.x - shipped.x) * 1000:+0;-0} mm, {(cg.y - shipped.y) * 1000:+0;-0} mm)");
                if ((cg - shipped).magnitude > CgTolerance)
                    problems.Add($"the {pose} dry CG {cg} is more than {CgTolerance * 100:0} cm from 0.1.3's {shipped}");
            }

            // A wing tear takes stage 1 and the stage 2 on it, each side.
            var tear = new[] { "L", "R" }.Sum(s => b.Parts["wing_tele1_" + s].GetComponentsInChildren(aeroType, true).Length);
            foreach (var (what, lost, total) in new[] { ("a wing tear and one more part", tear + 1, parts.Length), ("the same with the AWACS beam", tear + 1, parts.Length + 1) })
            {
                b.Report.Add($"ejection ratio, {what}: {lost} of {total} parts, {(float)lost / total:P1} (AI bails out over {EjectionRatio:P0})");
                if ((float)lost / total >= EjectionRatio)
                    problems.Add($"{what} loses {lost} of {total} parts, over the AI's {EjectionRatio:P0} ejection ratio");
            }

            // Fuel stays in four body tanks with dry wings (docs/DECISIONS.md), each a FuelTank on its section's AeroPart.
            var layout = new[] { (Part: "Centurion", Kg: 15000f), (Part: "fuselage_F", Kg: 3000f), (Part: "fuselage_R", Kg: 3000f), (Part: "tailcone", Kg: 3000f) };
            foreach (var entry in layout)
            {
                var part = b.Part(entry.Part);
                var tanks = part.GetComponents(GameType("FuelTank"));
                var so = tanks.Length == 1 ? new SerializedObject(tanks[0]) : null;
                if (so == null || Prop(so, "part").objectReferenceValue != part || Prop(so, "fuelCapacity").floatValue != entry.Kg || Prop(so, "connectedTanks").arraySize != 0)
                    problems.Add(entry.Part + " requires one independent " + entry.Kg + " kg FuelTank on its AeroPart");
            }
            var allTanks = b.Root.GetComponentsInChildren(GameType("FuelTank"), true);
            if (allTanks.Length != layout.Length || allTanks.Sum(t => Prop(new SerializedObject(t), "fuelCapacity").floatValue) != 24000f)
                problems.Add("the Centurion requires four body tanks of 24,000 kg in all and no wing tanks");

            // Stock fire: a burning tank damages every collider inside a sphere on its transform of radius 1.5 x the mean
            // half extent of its part's first collider's bounds (FuelTank.cs:331-336). It must carry forward to centre to
            // rear to tail, back from the tail, and reach each bay.
            var reaches = new[]
            {
                ("fuselage_F", "Centurion"), ("Centurion", "fuselage_F"), ("Centurion", "fuselage_R"), ("fuselage_R", "tailcone"),
                ("tailcone", "fuselage_R"), ("fuselage_F", "bay_F"), ("Centurion", "bay_F"), ("Centurion", "bay_A"), ("fuselage_R", "bay_A"), ("tailcone", "bay_A"),
            };
            foreach (var (source, target) in reaches)
            {
                var from = b.Parts[source].transform.position;
                var extents = b.Parts[source].GetComponent<Collider>().bounds.extents;
                var radius = (extents.x + extents.y + extents.z) * 0.33333f * 1.5f;
                var distance = b.Parts[target].GetComponents<Collider>().Min(c => Vector3.Distance(from, c.ClosestPoint(from)));
                b.Report.Add($"tank fire reach: {source} -> {target}: radius {radius:F2} m, nearest collider {distance:F2} m, margin {radius - distance:+0.00;-0.00} m");
                if (distance > radius)
                    problems.Add($"{source}'s tank fire misses {target} by {distance - radius:F2} m");
            }

            if (problems.Count > 0)
                throw new InvalidDataException("Centurion damage checks failed:\n  " + string.Join("\n  ", problems));
            b.Report.Add($"damage checks passed: {parts.Length} parts, {shapes} convex shapes, every origin inside its shape, Darkreach donor armour and joints, every brace with a tensor, dry CG within {CgTolerance * 100:0} cm of 0.1.3's, four body tanks with the fire chain");
        }

        // The deepest overlap (Physics.ComputePenetration) between the solid colliders of any two parts a PartJoint links,
        // leaving out parts skip names; root is a prefab asset (instantiated for the measure) or a scene object.
        private static (float Depth, string Pair) DeepestJointedOverlap(GameObject root, Func<GameObject, bool> skip)
        {
            var aeroType = GameType("AeroPart");
            var instance = root.scene.IsValid() ? root : (GameObject)Object.Instantiate(root);
            try
            {
                Physics.SyncTransforms();
                var deepest = (Depth: 0f, Pair: "none");
                foreach (var part in instance.GetComponentsInChildren(aeroType, true).Where(p => !skip(p.gameObject)))
                {
                    var joints = new SerializedObject(part).FindProperty("joints");
                    for (var i = 0; i < joints.arraySize; i++)
                    {
                        var other = joints.GetArrayElementAtIndex(i).FindPropertyRelative("connectedPart").objectReferenceValue as Component;
                        if (other == null || skip(other.gameObject))
                            continue;
                        foreach (var a in part.GetComponents<Collider>().Where(c => c.enabled && !c.isTrigger))
                            foreach (var c in other.GetComponents<Collider>().Where(c => c.enabled && !c.isTrigger))
                                if (Physics.ComputePenetration(a, a.transform.position, a.transform.rotation, c, c.transform.position, c.transform.rotation, out _, out var depth)
                                    && depth > deepest.Depth)
                                    deepest = (depth, $"{part.name}/{other.name}");
                    }
                }
                return deepest;
            }
            finally
            {
                if (instance != root)
                    Object.DestroyImmediate(instance);
            }
        }

        // What a convex collider's stored triangles get wrong: a degenerate face, one facing in, a vertex in front of a
        // face, more than Unity keeps.
        private static IEnumerable<string> ShapeFaults(Mesh mesh)
        {
            var v = mesh.vertices;
            var t = mesh.triangles;
            if (t.Length / 3 > 255 || v.Distinct().Count() > 255)
                yield return $"{v.Distinct().Count()} points and {t.Length / 3} triangles, over Unity's 255";
            var centre = v.Aggregate(Vector3.zero, (s, p) => s + p) / v.Length;
            for (var i = 0; i < t.Length; i += 3)
            {
                var a = v[t[i]];
                var n = Vector3.Cross(v[t[i + 1]] - a, v[t[i + 2]] - a);
                if (n.magnitude < 2e-5f)
                {
                    yield return $"triangle {i / 3} is degenerate";
                    continue;
                }
                n.Normalize();
                if (Vector3.Dot(n, a - centre) <= 0)
                    yield return $"triangle {i / 3} faces in ({Vector3.Dot(n, a - centre):F4} m, area {Vector3.Cross(v[t[i + 1]] - a, v[t[i + 2]] - a).magnitude / 2:F6} m2, at {a})";
                else if (v.Max(p => Vector3.Dot(p - a, n)) > 1e-3f)
                    yield return $"triangle {i / 3} has a vertex {v.Max(p => Vector3.Dot(p - a, n)) * 1000:F2} mm in front of it";
            }
        }
    }
}
