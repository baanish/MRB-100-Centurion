using UnityEngine;

namespace Centurion;

/// <summary>
/// Where the AWACS aims. Climb and orbit fly a racetrack: its near leg crosses the anchor-to-home line at the standoff,
/// square to it, and its far leg lies two turn radii behind, toward home, so the aircraft never comes inside the standoff
/// and always turns away from the threat. The stock jammer orbit this replaced (an arc round the anchor with reversals at
/// its ends) wandered: at full fuel its reversals bled speed and the first sortie drifted 64 km out. Recovery circles home
/// on the jammer's radial law. A bomber climbing short of its target flies the same racetrack (<see cref="AiHighStrike"/>).
/// </summary>
static class AwacsOrbit
{
    internal const float TurnRadiusM = 10000f;
    const float LegHalfM = 20000f, LookaheadM = 8000f, StepM = 400f, MapMarginM = 5000f;

    internal static float LevelDistance(GlobalPosition from, GlobalPosition to)
    {
        Vector3 delta = to - from;
        delta.y = 0f;
        return delta.magnitude;
    }

    /// <summary>
    /// The level distance from the anchor to the <see cref="Racetrack"/>'s farthest point: the far edge of an end cap, a
    /// turn of <see cref="TurnRadiusM"/> round the spine's end, which lies <see cref="LegHalfM"/> to the side of the axis and
    /// standoff + <see cref="TurnRadiusM"/> out. The map clamp only shortens it (a projection into the map, which holds the
    /// anchor, moves the centre no farther from it).
    /// </summary>
    internal static float FarthestM(float standoff) =>
        Mathf.Sqrt((standoff + TurnRadiusM) * (standoff + TurnRadiusM) + LegHalfM * LegHalfM) + TurnRadiusM;

    /// <summary>The largest standoff whose whole track stays within <paramref name="reachM"/> of the anchor (FarthestM inverted); 0 if none.</summary>
    internal static float CoverageStandoff(float reachM)
    {
        float inner = reachM - TurnRadiusM;
        return inner > LegHalfM ? Mathf.Sqrt(inner * inner - LegHalfM * LegHalfM) - TurnRadiusM : 0f;
    }

    /// <summary>The jammer's circle law (AIPilotCombatModes.cs:805-827): round <paramref name="centre"/> at <paramref name="radius"/>.</summary>
    internal static GlobalPosition Circle(GlobalPosition position, Vector3 forward, GlobalPosition centre, float radius, float height)
    {
        Vector3 toCentre = centre - position;
        toCentre.y = 0f;
        Vector3 tangent = Vector3.Cross(toCentre, Vector3.up);
        if (Vector3.Dot(tangent, forward) < Vector3.Dot(-tangent, forward)) tangent = -tangent;
        float error = (toCentre.magnitude - radius) / radius;
        // SPEC uses level distance; stock uses slant (AIPilotCombatModes.cs:499). Stock gain, including its always-true
        // Abs(error) > -0.4 test (AIPilotCombatModes.cs:813-826).
        error *= error < 0.4f ? 0.5f : 3f;
        GlobalPosition destination = position + Vector3.RotateTowards(tangent, toCentre, error, 1f).normalized * 8000f;
        destination.y = height;
        return destination;
    }

    /// <summary>
    /// Pure pursuit on the racetrack: from the track point nearest the aircraft, walk <see cref="LookaheadM"/> along it in
    /// the travel direction and aim there. <paramref name="direction"/> (+1 or -1) is picked once, as the way nearer the
    /// aircraft's heading, and kept until the caller resets it to 0 (a new anchor).
    /// </summary>
    internal static GlobalPosition Racetrack(GlobalPosition position, Vector3 forward, GlobalPosition anchor, GlobalPosition home,
        float standoff, float height, Vector2 mapSize, ref int direction)
    {
        Vector3 axis = home - anchor;
        axis.y = 0f;
        axis = axis.sqrMagnitude > 1f ? axis.normalized : Vector3.forward;
        Vector3 side = Vector3.Cross(Vector3.up, axis);
        GlobalPosition centre = anchor + axis * (standoff + TurnRadiusM);
        // Keep both turn circles inside the map less its margin (MapSize x and y are the world x and z extents; Ignus is
        // twice as wide as it is deep). A centre outside that box (bases near an edge) moves in first: there the map wins
        // over the standoff. Then slide the legs along the side axis, then shorten them.
        float hx = Mathf.Max(0f, mapSize.x * 0.5f - MapMarginM - TurnRadiusM), hz = Mathf.Max(0f, mapSize.y * 0.5f - MapMarginM - TurnRadiusM);
        centre.x = Mathf.Clamp(centre.x, -hx, hx);
        centre.z = Mathf.Clamp(centre.z, -hz, hz);
        var flat = new Vector3(centre.x, 0f, centre.z);
        float plus = Reach(flat, side, hx, hz), minus = Reach(flat, -side, hx, hz);
        float half = Mathf.Min(LegHalfM, (plus + minus) * 0.5f);
        centre += side * Mathf.Clamp(0f, half - minus, plus - half);

        Vector3 local = position - centre;
        local.y = 0f;
        Vector3 here = Nearest(local, side, axis, half);
        Vector3 level = new Vector3(forward.x, 0f, forward.z).normalized;
        if (direction == 0)
            direction = Vector3.Dot(Tangent(here, side, half), level) >= 0f ? 1 : -1;
        for (float walked = 0f; walked < LookaheadM; walked += StepM)
            here = Nearest(here + Tangent(here, side, half) * (direction * StepM), side, axis, half);

        GlobalPosition destination = centre + here;
        destination.y = height;
        return destination;
    }

    /// <summary>The track point nearest <paramref name="local"/> (relative to the racetrack's centre): a segment of
    /// half-length <paramref name="half"/> along <paramref name="side"/>, swept by the turn radius.</summary>
    static Vector3 Nearest(Vector3 local, Vector3 side, Vector3 axis, float half)
    {
        Vector3 spine = side * Mathf.Clamp(Vector3.Dot(local, side), -half, half);
        Vector3 off = local - spine;
        off.y = 0f;
        // From the spine itself, start on the near leg (toward the anchor, -axis).
        if (off.sqrMagnitude < 1f) off = -axis;
        return spine + off.normalized * TurnRadiusM;
    }

    /// <summary>The track's direction at a track point, turning about the spine (+1 sense; the caller multiplies).</summary>
    static Vector3 Tangent(Vector3 onTrack, Vector3 side, float half)
    {
        Vector3 spine = side * Mathf.Clamp(Vector3.Dot(onTrack, side), -half, half);
        Vector3 normal = (onTrack - spine).normalized;
        return Vector3.Cross(normal, Vector3.up);
    }

    /// <summary>How far from <paramref name="from"/> along <paramref name="dir"/> a point stays inside the box of half-sizes <paramref name="hx"/> by <paramref name="hz"/>.</summary>
    static float Reach(Vector3 from, Vector3 dir, float hx, float hz)
    {
        float reach = float.PositiveInfinity;
        if (dir.x > 1e-6f) reach = Mathf.Min(reach, (hx - from.x) / dir.x);
        if (dir.x < -1e-6f) reach = Mathf.Min(reach, (-hx - from.x) / dir.x);
        if (dir.z > 1e-6f) reach = Mathf.Min(reach, (hz - from.z) / dir.z);
        if (dir.z < -1e-6f) reach = Mathf.Min(reach, (-hz - from.z) / dir.z);
        return Mathf.Max(0f, reach);
    }
}
