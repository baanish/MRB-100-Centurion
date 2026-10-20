using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using BepInEx.Configuration;
using UnityEngine;
using static System.FormattableString;

namespace Centurion;

/// <summary>
/// Cosmetic wing flex (docs/M2-DESIGN.md, "Wing flex"): every Centurion's render meshes bend outboard of the strut node, the
/// stiff braced inner wing stays straight. Only MeshFilters and the tip's lights and vortex emitters move: colliders, joints,
/// the liftNormal and CoM markers, and everything the aero job, the detach rule and the tear rule read stay where they are.
/// <para>
/// The bend is a uniformly loaded cantilever clamped at the node (zero offset and slope there), evaluated per vertex from the
/// vertex's position along the swept span axis in the inner wing's frame. The inner wing's root and outer pieces, stage 1,
/// stage 2 and its wingtip (the part tree's pieces, CenturionAuthor's CutParts) use the same function of position, so they
/// bend as one wing at every extension and stay nested. Its size comes from the load factor
/// <see cref="TelescopeController"/> computes on every peer from the aircraft's acceleration, through a spring-damper, then
/// scaled with the span outboard of the node. Near the ground the rigid colliders are what touch it, so there the bend fades
/// to the wing's weight droop, which its lift relieves with speed: on the runway at flying speed the drawn wing is the rigid one.
/// </para>
/// Nothing reads or swaps a wing part's mesh in the game (only rotors and the terrain touch MeshFilter.sharedMesh), damage
/// changes materials, not meshes (DamageMaterial.cs, AeroPart.DisableMaterialCleanup, AeroPart.cs:652-662), and a detached
/// part keeps its GameObject (UnitPart.Detach, UnitPart.cs:380-392; AeroPart.Detach, AeroPart.cs:290-312), so each bent
/// renderer gets its own copy of its mesh, and a torn stage goes back to its rest mesh. Complex physics unparents every part
/// (AeroPart.CreateRB, AeroPart.cs:334), so all poses are read from world transforms each frame.
/// </summary>
sealed class WingFlex : MonoBehaviour
{
    // The tear's load limit (WingTearRule), where TipRiseAtTearM holds.
    const float TearNz = 4f;
    // Below this radar altitude the flying bend fades to the ground's (Aircraft.radarAlt is 0 on the springs, Aircraft.cs:1800-1813):
    // in a 1 g flare h metres up the drawn tip sits about h / 6 above the collider's, so at 2 m the collider's tip meets the
    // ground at 8.3 deg of bank and the drawn one at 8.7, and on the runway at speed both at 5.6 (the full 1 g rise there
    // would draw 9.0). Over 15 m the 0.6 Hz spring keeps up with the fade at a 5 m/s sink: with a 5 m rise it sat 0.6 m above
    // the collider at 1.6 m and within 0.5 m after touchdown (run 20261013-082628), where over 5 m it lagged 1 m at
    // touchdown and then swung to 1.8 m below (run 20261013-072318).
    const float GroundFadeM = 15f;
    // The takeoff AI rotates at 0.7 x takeoffSpeed (CenturionAuthor, AIPilotTakeoffState.cs:130-137): about where the wing carries the weight.
    const float LiftoffFraction = 0.7f;
    // Re-bend a mesh only when the tip has moved this much since it was last bent, m.
    const float ResolutionM = 0.002f;
    const float MaxStepS = 1f / 60f;

    static readonly string[] Sides = { "L", "R" };

    static ConfigEntry<bool> flexOn = null!;
    static ConfigEntry<float> rise1g = null!, riseAtTear = null!, droop = null!, referenceSpan = null!, spanExponent = null!, frequency = null!, damping = null!;
    static CenturionLog log = null!;

    /// <summary>The WingFlex config and the component that gives each Centurion its flex (CenturionPlugin.Awake).</summary>
    internal static void Install(GameObject host, ConfigFile config, CenturionLog centurionLog)
    {
        log = centurionLog;
        flexOn = config.Bind("WingFlex", "Enabled", true, "Bend the wing's render meshes outboard of the strut node with the load (cosmetic: colliders and aero don't move)");
        rise1g = config.Bind("WingFlex", "TipRise1gM", 2.5f, new ConfigDescription(
            "Tip rise in level 1 g flight at the reference span against the unloaded wing, m (2.5 m is 8.2 ft)", new AcceptableValueRange<float>(0f, 30f)));
        riseAtTear = config.Bind("WingFlex", "TipRiseAtTearM", 7.5f, new ConfigDescription(
            "Tip rise at the 4 g tear limit at the reference span, m (7.5 m is 25 ft); between 1 and 4 g the wing stiffens toward it", new AcceptableValueRange<float>(0f, 60f)));
        droop = config.Bind("WingFlex", "GroundDroopM", 0.75f, new ConfigDescription(
            "Tip droop under the wing's own weight parked at the reference span, m (0.75 m is 2.5 ft); also the weight's share of every load", new AcceptableValueRange<float>(0f, 10f)));
        referenceSpan = config.Bind("WingFlex", "ReferenceSpanM", 0f, new ConfigDescription(
            "The span the three tip numbers hold at, m; 0 is the airframe's own fully extended span, read from its parts", new AcceptableValueRange<float>(0f, 300f)));
        spanExponent = config.Bind("WingFlex", "SpanExponent", 3f, new ConfigDescription(
            "Tip offsets scale with (span outboard of the node / its length at the reference span) to this power: 4 is a cantilever under a fixed load per metre, 3 a fixed total lift",
            new AcceptableValueRange<float>(0f, 6f)));
        frequency = config.Bind("WingFlex", "FrequencyHz", 0.6f, new ConfigDescription(
            "The flex's natural frequency, Hz: how fast the tips swing after a pull, a gust or a landing", new AcceptableValueRange<float>(0.05f, 5f)));
        damping = config.Bind("WingFlex", "DampingRatio", 0.15f, new ConfigDescription(
            "The flex's damping ratio: 1 settles without overshoot, lower swings longer", new AcceptableValueRange<float>(0.01f, 2f)));
        flexOn.SettingChanged += (_, _) => log.Info($"config WingFlex.Enabled = {flexOn.Value}");
        host.AddComponent<Attacher>();
    }

    /// <summary>Adds a WingFlex beside each live TelescopeController (local and remote) once.</summary>
    sealed class Attacher : MonoBehaviour
    {
        void Update()
        {
            foreach (TelescopeController telescope in TelescopeController.All)
            {
                if (!telescope.TryGetComponent(out WingFlex _))
                {
                    telescope.gameObject.AddComponent<WingFlex>().Bind(telescope);
                }
            }
        }
    }

    sealed class Rider
    {
        public Transform Transform = null!;
        public UnitPart Part = null!;
        public Vector3 RestPosition;
        public Quaternion RestRotation;
        public Vector3 Anchor;
    }

    sealed class Side
    {
        public string Name = "";
        public UnitPart Root = null!, Outer = null!, Stage2 = null!, Tip = null!;
        /// <summary>The bend frame in the inner wing's frame: s along the slide axis from the node, d up, c along the chord.</summary>
        public Matrix4x4 RootToBend, BendToRoot;
        /// <summary>
        /// The wingtip's own mesh and its outermost vertex along the span axis, stage 2's for when the tip is gone, and the
        /// outermost s of the inner wing with and without its outer piece (the tip once the stages are gone).
        /// </summary>
        public FlexMesh? TipMesh, StageMesh;
        public int TipIndex, StageIndex;
        public float RootTipS, OuterTipS, NodeLateral;
        /// <summary>The tip's distance from the centreline with both stages run out by their remaining travel: half the airframe's full span.</summary>
        public float FullLateral;
        public readonly List<FlexMesh> Meshes = new();
        public readonly List<Rider> Riders = new();
        /// <summary>This frame's bent length outboard of the node, tip offset and tip slope.</summary>
        public float Length, TipOffset, Scale;
        public float RiderOffset = float.NaN;
    }

    TelescopeController telescope = null!;
    Aircraft aircraft = null!;
    readonly List<Side> sides = new();
    bool broken, shown;
    float offset, rate;
    readonly Stopwatch watch = new();

    /// <summary>The wing's lift in g this frame (0 on the wheels), and the spring's target and state at the reference span, m.</summary>
    public float LiftG { get; private set; }
    public float Target { get; private set; }
    public float Offset => offset;
    /// <summary>The CPU time of the last frame's flex on this aircraft, ms, smoothed.</summary>
    public float CostMs { get; private set; }
    public int Vertices => sides.Sum(s => s.Meshes.Sum(m => m.VertexCount));

    /// <summary>The bent tip's offset on one side, m, + up (NaN while unbound).</summary>
    public float TipOffset(int side) => side < sides.Count ? sides[side].TipOffset : float.NaN;
    /// <summary>How far that side's nav light has moved up the aircraft from its unbent place, m: the riders follow the tip.</summary>
    public float RiderOffset(int side) => side < sides.Count ? sides[side].RiderOffset : float.NaN;

    void Bind(TelescopeController owner)
    {
        telescope = owner;
        aircraft = owner.GetComponent<Aircraft>();
        var parts = aircraft.partLookup.Where(p => p != null).GroupBy(p => p.name).ToDictionary(g => g.Key, g => g.First());
        foreach (string name in Sides)
        {
            string? problem = BindSide(name, parts, out Side? side);
            if (problem != null)
            {
                broken = true;
                foreach (FlexMesh mesh in sides.SelectMany(s => s.Meshes).Concat(side?.Meshes ?? Enumerable.Empty<FlexMesh>()))
                {
                    Destroy(mesh);
                }

                sides.Clear();
                log.Error($"wing flex off on {aircraft.name}: {problem}");
                return;
            }

            sides.Add(side!);
        }

        Side left = sides[0];
        log.Info(Invariant($"wing flex on {aircraft.name}: node {left.NodeLateral:0.00} m out, full span {2f * left.FullLateral:0.00} m, {left.OuterTipS:0.00} m of inner wing past it, {sides.Sum(s => s.Meshes.Count)} meshes ({Vertices} vertices) and {sides.Sum(s => s.Riders.Count)} riders"));
    }

    string? BindSide(string name, Dictionary<string, UnitPart> parts, out Side? side)
    {
        side = null;
        if (!parts.TryGetValue("wing_root_" + name, out UnitPart root) || !parts.TryGetValue("wing_outer_" + name, out UnitPart outer)
            || !parts.TryGetValue("wing_tele1_" + name, out UnitPart stage1) || !parts.TryGetValue("wing_tele2_" + name, out UnitPart stage2)
            || !parts.TryGetValue("wing_tip_" + name, out UnitPart tipPart) || !parts.TryGetValue("strut_outer_" + name, out UnitPart strut))
        {
            return $"no wing_root, wing_outer, wing_tele1, wing_tele2, wing_tip or strut_outer on side {name}";
        }

        // The span axis is stage 1's slide (CenturionAuthor.AddSlideEnds, on the outer wing it slides in), from its retracted
        // position: a late joiner's copy can already be fully out when this binds (TelescopeController jumps it to the
        // owner's extension). The bend frame is the root's, which the outer wing shares.
        Transform rootT = root.transform, outerT = outer.transform;
        Transform? end = outerT.Find(stage1.name + "_extended");
        if (end == null || telescope.RetractedPosition(stage1) is not Vector3 retracted)
        {
            return $"{outer.name} has no {stage1.name}_extended marker, or {stage1.name} is not a telescope stage";
        }

        Vector3 travel = rootT.InverseTransformVector(outerT.TransformVector(end.localPosition - retracted));
        if (travel.magnitude < 0.5f)
        {
            return Invariant($"{stage1.name}'s slide is {travel.magnitude:0.00} m, too short to read its axis");
        }

        // The run left to full extension, from wherever the stage is now.
        Vector3 slide = rootT.InverseTransformVector(outerT.TransformVector(end.localPosition - outerT.InverseTransformPoint(stage1.transform.position)));
        Vector3 span = travel.normalized;
        Vector3 up = (Vector3.up - Vector3.Dot(Vector3.up, span) * span).normalized;
        Vector3 chord = Vector3.Cross(span, up);

        // The node: the strut's outermost point along the span axis, where the strut meets the wing.
        if (!TryReadVertices(strut, out Vector3[] strutVertices))
        {
            return $"{strut.name}'s mesh isn't readable";
        }

        Matrix4x4 strutToRoot = rootT.worldToLocalMatrix * strut.transform.localToWorldMatrix;
        Vector3 node = strutVertices.Select(v => strutToRoot.MultiplyPoint3x4(v)).OrderByDescending(p => Vector3.Dot(p, span)).First();

        var s = new Side { Name = name, Root = root, Outer = outer, Stage2 = stage2, Tip = tipPart };
        s.RootToBend = Matrix4x4.identity;
        s.RootToBend.SetRow(0, new Vector4(span.x, span.y, span.z, -Vector3.Dot(span, node)));
        s.RootToBend.SetRow(1, new Vector4(up.x, up.y, up.z, -Vector3.Dot(up, node)));
        s.RootToBend.SetRow(2, new Vector4(chord.x, chord.y, chord.z, -Vector3.Dot(chord, node)));
        s.BendToRoot = s.RootToBend.inverse;
        s.NodeLateral = Mathf.Abs(aircraft.transform.InverseTransformPoint(rootT.TransformPoint(node)).x);
        side = s;

        foreach (UnitPart part in new[] { root, outer, stage1, stage2, tipPart })
        {
            // The part's own mesh and its LOD1 hull (CenturionAuthor.AddLods) bend; every other non-part child that shows
            // something (the nav light and its effects, the vortex emitter) rides the bent surface rigidly.
            foreach (Transform child in part.transform.Cast<Transform>().Prepend(part.transform))
            {
                bool own = child == part.transform || child.name == part.name + "_lod1";
                if (own && child.TryGetComponent(out MeshFilter filter))
                {
                    var mesh = child.gameObject.AddComponent<FlexMesh>();
                    if (!mesh.Bind(filter, part))
                    {
                        Destroy(mesh);
                        return $"{child.name}'s mesh isn't readable";
                    }

                    s.Meshes.Add(mesh);
                }
                else if (!own && !child.TryGetComponent(out UnitPart _) && (child.GetComponentInChildren<Renderer>(true) != null || child.GetComponentInChildren<Light>(true) != null))
                {
                    Vector3 anchor = child.TryGetComponent(out MeshFilter riderMesh) && riderMesh.sharedMesh != null
                        ? riderMesh.sharedMesh.bounds.center : Vector3.zero;
                    s.Riders.Add(new Rider { Transform = child, Part = part, RestPosition = child.localPosition, RestRotation = child.localRotation, Anchor = anchor });
                }
            }
        }

        s.RootTipS = s.Meshes.Where(m => m.Part == root).Max(m => MaxS(m, out _));
        s.OuterTipS = s.Meshes.Where(m => m.Part == root || m.Part == outer).Max(m => MaxS(m, out _));
        s.TipMesh = s.Meshes.FirstOrDefault(m => m.transform == tipPart.transform);
        s.StageMesh = s.Meshes.FirstOrDefault(m => m.transform == stage2.transform);
        if (s.TipMesh == null || s.StageMesh == null)
        {
            return $"{tipPart.name} or {stage2.name} has no mesh of its own";
        }

        MaxS(s.TipMesh, out s.TipIndex);
        MaxS(s.StageMesh, out s.StageIndex);

        // Each stage's remaining run to its _extended marker (CenturionAuthor.AddSlideEnds), added to the tip where it is now.
        Transform? end2 = stage1.transform.Find(stage2.name + "_extended");
        if (end2 == null)
        {
            return $"{stage1.name} has no {stage2.name}_extended marker";
        }

        Vector3 run2 = stage1.transform.TransformVector(end2.localPosition - stage1.transform.InverseTransformPoint(stage2.transform.position));
        Vector3 tipFull = s.TipMesh.transform.TransformPoint(s.TipMesh.RestVertices[s.TipIndex]) + rootT.TransformVector(slide) + run2;
        s.FullLateral = Mathf.Abs(aircraft.transform.InverseTransformPoint(tipFull).x);
        return null;

        float MaxS(FlexMesh mesh, out int index)
        {
            Matrix4x4 toBend = s.RootToBend * rootT.worldToLocalMatrix * mesh.transform.localToWorldMatrix;
            index = 0;
            float max = float.NegativeInfinity;
            for (int i = 0; i < mesh.RestVertices.Length; i++)
            {
                float along = toBend.MultiplyPoint3x4(mesh.RestVertices[i]).x;
                if (along > max)
                {
                    max = along;
                    index = i;
                }
            }

            return max;
        }
    }

    static bool TryReadVertices(UnitPart part, out Vector3[] vertices)
    {
        vertices = part.TryGetComponent(out MeshFilter filter) && filter.sharedMesh != null && filter.sharedMesh.isReadable ? filter.sharedMesh.vertices : System.Array.Empty<Vector3>();
        return vertices.Length > 0;
    }

    void LateUpdate()
    {
        if (broken || aircraft == null)
        {
            return;
        }

        if (!flexOn.Value)
        {
            if (shown)
            {
                Show(false);
            }

            return;
        }

        if (!shown)
        {
            Show(true);
        }

        watch.Restart();
        Spring(Time.deltaTime);
        foreach (Side side in sides)
        {
            BendSide(side);
        }

        watch.Stop();
        CostMs = Mathf.Lerp(CostMs, (float)watch.Elapsed.TotalMilliseconds, 0.1f);
    }

    void Show(bool flexed)
    {
        shown = flexed;
        foreach (Side side in sides)
        {
            foreach (FlexMesh mesh in side.Meshes.Where(m => m != null && !m.Part.IsDetached()))
            {
                mesh.Show(flexed);
            }

            foreach (Rider rider in side.Riders.Where(r => r.Transform != null && !r.Part.IsDetached()))
            {
                rider.Transform.localPosition = rider.RestPosition;
                rider.Transform.localRotation = rider.RestRotation;
            }

            if (!flexed && side.Tip != null && !side.Tip.IsDetached())
            {
                side.TipOffset = 0f;
                side.RiderOffset = float.IsNaN(side.RiderOffset) ? float.NaN : 0f;
            }
        }
    }

    /// <summary>
    /// The tip offset at the reference span the load asks for, and a spring-damper toward it. Flying, it is TipRise1gM per g up
    /// to 1 g, and past it the wing stiffens so the 4 g tear limit gives TipRiseAtTearM. On the wheels it is the weight's
    /// GroundDroopM per g, less the share of the weight the wing lifts at this speed, so at flying speed the drawn wing is the
    /// rigid one the colliders are; between the runway and GroundFadeM the two blend.
    /// </summary>
    void Spring(float dt)
    {
        float nz = Mathf.Clamp(telescope.Nz, -3f, 6f);
        float liftoff = LiftoffFraction * aircraft.GetAircraftParameters().takeoffSpeed;
        float airborne = Mathf.Clamp01(aircraft.radarAlt / GroundFadeM);
        float lifting = liftoff > 0f ? Mathf.Clamp01(telescope.EasMps * telescope.EasMps / (liftoff * liftoff)) : 1f;
        LiftG = nz * Mathf.Lerp(lifting, 1f, airborne);

        float r1 = rise1g.Value;
        float linear = r1 * nz;
        float stiffening = r1 > 0f ? (riseAtTear.Value - r1) / ((TearNz - 1f) * r1) : 1f;
        float flying = linear <= r1 ? linear : r1 + (linear - r1) * stiffening;
        Target = Mathf.Lerp(-droop.Value * nz * (1f - lifting), flying, airborne);

        float omega = 2f * Mathf.PI * frequency.Value;
        for (float left = Mathf.Min(dt, 0.25f); left > 0f; left -= MaxStepS)
        {
            float step = Mathf.Min(left, MaxStepS);
            rate += (omega * omega * (Target - offset) - 2f * damping.Value * omega * rate) * step;
            offset += rate * step;
        }
    }

    void BendSide(Side side)
    {
        if (side.Root == null || side.Root.IsDetached())
        {
            return;
        }

        Transform rootT = side.Root.transform;
        Matrix4x4 worldToBend = side.RootToBend * rootT.worldToLocalMatrix;
        Matrix4x4 bendToWorld = rootT.localToWorldMatrix * side.BendToRoot;
        // The outermost piece still on: the wingtip, stage 2, else the inner wing's end with or without its outer piece.
        bool tipOn = side.Tip != null && !side.Tip.IsDetached(), stageOn = side.Stage2 != null && !side.Stage2.IsDetached();
        FlexMesh? tipMesh = tipOn ? side.TipMesh : stageOn ? side.StageMesh : null;
        int tipIndex = tipOn ? side.TipIndex : side.StageIndex;
        float innerS = side.Outer != null && !side.Outer.IsDetached() ? side.OuterTipS : side.RootTipS;
        Vector3 tipWorld = tipMesh != null ? tipMesh.transform.TransformPoint(tipMesh.RestVertices[tipIndex])
            : bendToWorld.MultiplyPoint3x4(new Vector3(innerS, 0f, 0f));
        side.Length = Mathf.Max(worldToBend.MultiplyPoint3x4(tipWorld).x, 0.01f);

        float lateral = Mathf.Abs(aircraft.transform.InverseTransformPoint(tipWorld).x) - side.NodeLateral;
        float reference = (referenceSpan.Value > 0f ? referenceSpan.Value / 2f : side.FullLateral) - side.NodeLateral;
        side.Scale = lateral > 0f && reference > 0f ? Mathf.Pow(lateral / reference, spanExponent.Value) : 0f;
        float tip = offset * side.Scale;

        foreach (FlexMesh mesh in side.Meshes)
        {
            if (mesh == null || mesh.Part == null)
            {
                continue;
            }

            if (mesh.Part.IsDetached())
            {
                mesh.Show(false); // a torn stage is no longer the wing's: its rest mesh
                continue;
            }

            mesh.Bend(worldToBend, bendToWorld, tip, side.Length);
        }

        if (tipMesh != null)
        {
            Vector3 moved = tipMesh.BentVertex(tipIndex) - tipMesh.RestVertices[tipIndex];
            side.TipOffset = Vector3.Dot(tipMesh.transform.TransformVector(moved), aircraft.transform.up);
        }

        foreach (Rider rider in side.Riders)
        {
            if (rider.Transform == null || rider.Part == null)
            {
                continue;
            }

            if (rider.Part.IsDetached())
            {
                rider.Transform.localPosition = rider.RestPosition;
                rider.Transform.localRotation = rider.RestRotation;
                continue;
            }

            Transform parent = rider.Transform.parent;
            // Bend at the visible fitting, since the donor nav lamp's pivot is nearly a metre away from its mesh.
            Vector3 rest = parent.TransformPoint(rider.RestPosition + rider.RestRotation * Vector3.Scale(rider.Anchor, rider.Transform.localScale));
            Vector3 q = worldToBend.MultiplyPoint3x4(rest);
            Shape(q.x, tip, side.Length, out float w, out float theta, out float shortening);
            Vector3 bent = bendToWorld.MultiplyPoint3x4(Bent(q, w, theta, shortening));
            Vector3 spanWorld = bendToWorld.MultiplyVector(Vector3.right);
            Vector3 tilted = bendToWorld.MultiplyVector(new Vector3(Mathf.Cos(theta), Mathf.Sin(theta), 0f));
            rider.Transform.rotation = Quaternion.FromToRotation(spanWorld, tilted) * parent.rotation * rider.RestRotation;
            rider.Transform.position = bent - rider.Transform.TransformVector(rider.Anchor);
            if (rider.Transform.name.StartsWith("navlight_"))
            {
                side.RiderOffset = Vector3.Dot(bent - rest, aircraft.transform.up);
            }
        }
    }

    /// <summary>
    /// A cantilever under a uniform load, clamped at s = 0 with its tip at s = length: offset w = tip (6x^2 - 4x^3 + x^4) / 3
    /// with x = s / length, its slope's angle theta, and how far the bent centreline falls short of s along the span axis,
    /// (1/2) the integral of w'^2 ds. Past the tip (the raked tip's outermost vertex can sit beyond the tip vertex used for
    /// the length) it carries on straight at the tip's slope.
    /// </summary>
    static void Shape(float s, float tip, float length, out float w, out float theta, out float shortening)
    {
        if (s <= 0f || tip == 0f)
        {
            w = theta = shortening = 0f;
            return;
        }

        float x = Mathf.Min(s / length, 1f);
        float x2 = x * x, x3 = x2 * x, x4 = x3 * x;
        w = tip * (6f * x2 - 4f * x3 + x4) / 3f;
        float slope = tip / length * (4f * x - 4f * x2 + 4f / 3f * x3);
        float integral = 3f * x3 - 4.5f * x4 + 3f * x4 * x - x3 * x3 + x4 * x3 / 7f;
        shortening = 8f / 9f * tip * tip / length * integral;
        if (s > length)
        {
            float past = s - length;
            w += slope * past;
            shortening += past * (1f - 1f / Mathf.Sqrt(1f + slope * slope));
        }

        theta = Mathf.Atan(slope);
    }

    /// <summary>A point (s, d, c) in the bend frame on the bent wing: its section turned by theta about the chord, about the centreline.</summary>
    static Vector3 Bent(Vector3 q, float w, float theta, float shortening)
    {
        float sin = Mathf.Sin(theta), cos = Mathf.Cos(theta);
        return new Vector3(q.x - shortening - q.y * sin, w + q.y * cos, q.z);
    }

    /// <summary>
    /// One renderer's own copy of its mesh, bent from the rest vertices. It lives on the renderer's GameObject, so the copy goes
    /// with the renderer, including a torn stage that outlives its aircraft.
    /// </summary>
    sealed class FlexMesh : MonoBehaviour
    {
        public UnitPart Part = null!;
        MeshFilter filter = null!;
        Renderer? meshRenderer;
        Mesh original = null!, copy = null!;
        Vector3[] restNormals = null!, vertices = null!, normals = null!;
        Vector4[] restTangents = null!, tangents = null!;
        float bentTip, bentLength = float.NaN;

        public Vector3[] RestVertices { get; private set; } = null!;
        public int VertexCount => RestVertices.Length;
        /// <summary>Vertex i as last bent, in the mesh's frame.</summary>
        public Vector3 BentVertex(int i) => vertices[i];

        public bool Bind(MeshFilter meshFilter, UnitPart part)
        {
            filter = meshFilter;
            Part = part;
            original = meshFilter.sharedMesh;
            if (original == null || !original.isReadable)
            {
                return false;
            }

            meshRenderer = GetComponent<Renderer>();
            copy = Instantiate(original);
            copy.name = original.name + "_flex";
            copy.MarkDynamic();
            RestVertices = original.vertices;
            restNormals = original.normals;
            restTangents = original.tangents;
            vertices = (Vector3[])RestVertices.Clone();
            normals = (Vector3[])restNormals.Clone();
            tangents = (Vector4[])restTangents.Clone();
            return true;
        }

        public void Show(bool flexed)
        {
            Mesh shown = flexed ? copy : original;
            if (filter.sharedMesh != shown)
            {
                filter.sharedMesh = shown;
                bentLength = float.NaN;
            }
        }

        public void Bend(Matrix4x4 worldToBend, Matrix4x4 bendToWorld, float tip, float length)
        {
            // Unseen (no camera or shadow draws it, as for the LOD level not in use) or unchanged: it keeps the last shape.
            if (meshRenderer != null && !meshRenderer.isVisible
                || Mathf.Abs(tip - bentTip) < ResolutionM && Mathf.Abs(length - bentLength) < ResolutionM)
            {
                return;
            }

            bentTip = tip;
            bentLength = length;
            Matrix4x4 toBend = worldToBend * transform.localToWorldMatrix;
            Matrix4x4 fromBend = transform.worldToLocalMatrix * bendToWorld;
            bool hasNormals = restNormals.Length == RestVertices.Length, hasTangents = restTangents.Length == RestVertices.Length;
            for (int i = 0; i < RestVertices.Length; i++)
            {
                Vector3 q = toBend.MultiplyPoint3x4(RestVertices[i]);
                Shape(q.x, tip, length, out float w, out float theta, out float shortening);
                if (w == 0f)
                {
                    vertices[i] = RestVertices[i];
                    if (hasNormals)
                    {
                        normals[i] = restNormals[i];
                    }

                    if (hasTangents)
                    {
                        tangents[i] = restTangents[i];
                    }

                    continue;
                }

                vertices[i] = fromBend.MultiplyPoint3x4(Bent(q, w, theta, shortening));
                float sin = Mathf.Sin(theta), cos = Mathf.Cos(theta);
                if (hasNormals)
                {
                    normals[i] = fromBend.MultiplyVector(Turn(toBend.MultiplyVector(restNormals[i]), sin, cos));
                }

                if (hasTangents)
                {
                    Vector4 t = restTangents[i];
                    Vector3 turned = fromBend.MultiplyVector(Turn(toBend.MultiplyVector(t), sin, cos));
                    tangents[i] = new Vector4(turned.x, turned.y, turned.z, t.w);
                }
            }

            copy.vertices = vertices;
            if (hasNormals)
            {
                copy.normals = normals;
            }

            if (hasTangents)
            {
                copy.tangents = tangents;
            }

            copy.RecalculateBounds();
        }

        static Vector3 Turn(Vector3 v, float sin, float cos) => new(v.x * cos - v.y * sin, v.x * sin + v.y * cos, v.z);

        void OnDestroy()
        {
            if (copy != null)
            {
                Destroy(copy);
            }
        }
    }
}
