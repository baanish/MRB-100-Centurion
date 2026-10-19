"""fuselage_aft's damage structure (m4/airframe.py): what fuselage_R shows when it breaks off or burns through, and
fuselage_M's face of their joint at 25. A helper of fuselage_aft.py; it declares no GROUP.

The aft body's air space, in section, is the hull's inside WALL in from the skin, less the aft bay's cavity (its walls
straight up from the doors' hinge lines to the roof) and the AWACS well's (its walls down to the floor), each backed by
WALL: section(). Lofted along the part it is the lining; at each joint the flat cap opens onto it as a break face. In
fuselage_R stand ring frames over the bay's frames and an open frame ring just inside each break, longerons and
systems runs (a cable bundle and a hydraulic line a side) that run on past both joints as broken ends, and torn skin
tongues past each break. fuselage_M's air space behind its joint is a compartment closed by the real bulkhead at the
bay's front wall (23.6), with its own joint frame, member ends and tongues."""

import math

from mathutils import Vector

from . import airframe as af
from . import surface as sf

ARC = 6  # lining segments a side between the bay wall and the well
BAY_POINTS = 8  # section points between the two bay walls' backs: up the walls, over the roof (under the bay aft of it)
FRAME = (0.05, 0.11, 0.006)  # ring frames: width, depth inward, how far their outer side sits behind the lining
LONGERON = (0.06, 0.06)  # width, depth
LONGERON_ARC = (2, 4)  # lining points on each side's arc that carry a longeron
# Systems runs a side: (lining point on the arc, inward offset, radius, strip): a cable bundle and a hydraulic line in the
# space behind the frames
SYSTEMS = ((3, 0.18, 0.04, "cable"), (5, 0.17, 0.022, "pipe"))
# Broken member ends: how far each longeron and systems run reaches past a joint (cycled), and the torn tongues' reach
# per arc segment from the bay wall up (0 none)
PAST = (0.16, 0.07, 0.12, 0.2, 0.09)
TONGUES = (0.0, 0.14, 0.22, 0.1, 0.0, 0.18)


def well_edges(bl):
    lo, hi = bl.well_box()
    return lo.y + bl.Y0, hi.y + bl.Y0, hi.x, lo.z


class Section:
    """The air space's section at any station as a closed loop of points in a fixed order: the +x arc from the bay
    wall's back up to the well (ARC + 1), the well's back down and across its floor (4), the -x arc back down
    (ARC + 1), then BAY_POINTS over the bay's back. Where the bay or the well is absent its points lie on the lining
    instead, so every station's loop has the same count and the loops loft."""

    def __init__(self, bl, surf, rim_deg, hinge_deg, roof):
        self.bl, self.surf = bl, surf
        self.rim_deg, self.hinge_deg, self.roof = rim_deg, hinge_deg, roof
        self.slot0, self.slot1, self.well_x, self.floor = well_edges(bl)

    def inner(self, s, deg):
        return self.surf.point(s, deg) - self.surf.normal(s, deg) * af.WALL

    def deg_for_inner_x(self, s, x, lo, hi):
        """The angle between lo and hi (inner x monotonic there) where the lining reaches half-width x."""
        f = lambda d: self.inner(s, d).x - x
        a, b = lo, hi
        fa = f(a)
        for _ in range(40):
            m = (a + b) / 2
            if (f(m) > 0) == (fa > 0):
                a, fa = m, f(m)
            else:
                b = m
        return (a + b) / 2

    def angles(self, s):
        """The arc's ends: the well side (+x, near the crown) and the bay side (+x, near the hinge)."""
        rim = self.surf.point(s, self.rim_deg)
        top = self.deg_for_inner_x(s, rim.x + 0.04, self.rim_deg, 90.0)
        xe = self.surf.point(s, self.hinge_deg).x
        low = self.deg_for_inner_x(s, xe + af.WALL + 0.01, 90.0, self.hinge_deg)
        return top, low, rim, xe

    def points(self, s, bay, well):
        top, low, rim, xe = self.angles(s)
        y = self.bl.st(s)
        arc = [low + (top - low) * i / ARC for i in range(ARC + 1)]
        plus = [self.inner(s, d) for d in arc]
        minus = [self.inner(s, -d) for d in reversed(arc)]
        if well:
            xw, drop = self.well_x + af.WALL, rim.z - (rim.x - self.well_x) - 0.04
            mid = [Vector((xw, y, drop)), Vector((xw, y, self.floor - af.WALL)),
                   Vector((-xw, y, self.floor - af.WALL)), Vector((-xw, y, drop))]
        else:
            mid = [self.inner(s, top * (1 - 2 * k / 5)) for k in range(1, 5)]
        if bay:
            xb, zr = xe + af.WALL, self.roof + af.WALL
            zq = minus[-1].z
            under = [Vector((-xb, y, (zq + zr) / 2)), Vector((-xb, y, zr))]
            under += [Vector((-xb + 2 * xb * k / 5, y, zr)) for k in range(1, 5)]
            under += [Vector((xb, y, zr)), Vector((xb, y, (zq + zr) / 2))]
        else:
            under = [self.inner(s, -low - (360.0 - 2 * low) * k / (BAY_POINTS + 1)) for k in range(1, BAY_POINTS + 1)]
        return plus + mid + minus + under


def inward_normals(pts):
    """Each loop point's direction into the air space, in its station plane (x, z)."""
    area = sum(a.x * b.z - b.x * a.z for a, b in zip(pts, pts[1:] + pts[:1]))
    sign = 1.0 if area > 0 else -1.0
    out = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        d = (b - a)
        n = Vector((-d.z, 0.0, d.x)) * sign
        out.append(n.normalized() if n.length > 1e-9 else Vector((0, 0, 1)))
    return out


def inward_edges(pts):
    """Each loop edge's (from point j to j + 1) direction into the air space, in its station plane (x, z)."""
    area = sum(a.x * b.z - b.x * a.z for a, b in zip(pts, pts[1:] + pts[:1]))
    sign = 1.0 if area > 0 else -1.0
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        n = Vector((-(b.z - a.z), 0.0, b.x - a.x)) * sign
        out.append(n.normalized() if n.length > 1e-9 else Vector((0, 0, 1)))
    return out


def arc_indices(side):
    """Loop indices of a side's arc points, from the bay wall up to the well."""
    if side > 0:
        return list(range(ARC + 1))
    first = ARC + 1 + 4
    return list(range(first + ARC, first - 1, -1))


def make_section(bl, surf):
    from .fuselage_aft import BAY_DOOR, spine_extent
    return Section(bl, surf, spine_extent(bl)[2], BAY_DOOR[2], bl.AFT_BAY_ROOF)


def ring(part, pts, share=None):
    """BMVerts for a loop, reusing share's vertex wherever the point coincides (a section that changes in its own
    station plane)."""
    out = []
    for i, p in enumerate(pts):
        if share is not None and (share[i].co - p).length < 1e-7:
            out.append(share[i])
        else:
            out.append(part.bm.verts.new(p))
    return out


def lining(part, sec, stations):
    """Loft the lining over stations: (station, bay, well) triples, a repeated station meaning the section changes
    there. Faces face the air space: in a section's plane toward its inside; where the section changes at one
    station, toward the side whose section lacks the cavity there (the face backs the cavity's end wall). Returns the
    rings of BMVerts."""
    rings = []
    for s, bay, well in stations:
        prev = rings[-1] if rings and abs(stations[len(rings) - 1][0] - s) < 1e-9 else None
        rings.append(ring(part, sec.points(s, bay, well), prev))
    inward = [inward_edges([v.co for v in r]) for r in rings]

    def facing(r, j):
        if abs(stations[r][0] - stations[r + 1][0]) < 1e-9:
            return Vector((0, 1 if sum(stations[r + 1][1:]) < sum(stations[r][1:]) else -1, 0))
        return inward[r][j]
    af.loft(part, rings, "lining", facing)
    return rings


def frame(part, pts, normals, indices, closed):
    """A ring frame through the loop points at indices (pushed FRAME[2] behind the lining), an open U facing inward."""
    w, d, e = FRAME
    path = [pts[i] for i in indices]
    inward = [normals[i] for i in indices]
    along = [Vector((0, 1, 0))] * len(path)
    section = [(-w / 2, -e), (-w / 2, d), (w / 2, d), (w / 2, -e)]
    return af.sweep(part, path, inward, along, section, ("web", "flange", "web", None), closed=closed,
                    caps=None if closed else ("plate", "plate"))


def member(part, sec, s0, s1, index, bay_at, well_at, kind):
    """A longeron (kind None) or a systems run ((inward, radius, strip)) along stations s0 to s1 at loop point index,
    following the lining (bay_at(s), well_at(s) say which section applies)."""
    rows = sorted({s0, s1} | {s for s in (29.36, 30.4, 31.3, 32.36) if s0 < s < s1})
    pts, normals, tangents = [], [], []
    for s in rows:
        loop = sec.points(s, bay_at(s), well_at(s))
        n = inward_normals(loop)
        pts.append(loop[index])
        normals.append(n[index])
        tangents.append((loop[(index + 1) % len(loop)] - loop[index - 1]).normalized())
    if kind is None:
        w, d = LONGERON
        section = [(-w / 2, -FRAME[2]), (-w / 2, d), (w / 2, d), (w / 2, -FRAME[2])]
        return af.sweep(part, pts, normals, tangents, section, ("web", "flange", "web", None), caps=("torn", "torn"))
    off, radius, strip = kind
    return af.tube(part, [p + n * off for p, n in zip(pts, normals)], radius, strip, caps=("torn", "torn"))


def members(part, sec, s0, s1, bay_at, well_at, past_fore, past_aft, k0=0):
    """The longerons and systems runs from s0 to s1, each running on past either end by the PAST cycle where that end
    is a joint (past_fore, past_aft)."""
    k = k0
    for side in (1, -1):
        arc = arc_indices(side)
        for i in LONGERON_ARC:
            a = s0 - (PAST[k % len(PAST)] if past_fore else 0.0)
            b = s1 + (PAST[(k + 2) % len(PAST)] if past_aft else 0.0)
            member(part, sec, a, b, arc[i], bay_at, well_at, None)
            k += 1
        for i, off, radius, strip in SYSTEMS:
            a = s0 - (PAST[k % len(PAST)] * 1.5 if past_fore else 0.0)
            b = s1 + (PAST[(k + 3) % len(PAST)] * 1.5 if past_aft else 0.0)
            member(part, sec, a, b, arc[i], bay_at, well_at, (off, radius, strip))
            k += 1


def tongues(part, loop, out_dir):
    """Torn skin tongues past a break along both arcs of the lining's loop there."""
    normals = inward_normals([v.co for v in loop])
    for side in (1, -1):
        idx = arc_indices(side)
        edge = [loop[i].co for i in idx]
        inward = [normals[i] for i in idx]
        lengths = TONGUES if side > 0 else TONGUES[3:] + TONGUES[:3]
        af.teeth(part, edge, inward, out_dir, lengths)


def build_fuselage_R(bl, surf, p, slots, joints, bay_end):
    """fuselage_R between its joints (25, 33): the lining with the bay's cavity to bay_end, the break faces, frames,
    members and tongues."""
    j0, j1 = joints
    sec = make_section(bl, surf)
    p.envelope = p.bm.copy()
    e = bay_end + af.WALL
    stations = [(j0, True, True), (29.36, True, True), (30.4, True, True), (31.3, True, True), (32.36, True, True),
                (e, True, True), (e, False, True), (j1, False, True)]
    rings = lining(p, sec, stations)
    af.open_joint(p, bl.st(j0), slots, rings[0], Vector((0, -1, 0)))
    af.open_joint(p, bl.st(j1), slots, rings[-1], Vector((0, 1, 0)))
    for s, bay, closed in ((j0 + 0.12, True, True), (27.1, True, False), (28.3, True, False), (29.5, True, False),
                           (30.7, True, False), (31.9, True, False), (j1 - 0.12, False, True)):
        pts = sec.points(s, bay, True)
        n = inward_normals(pts)
        if closed:
            frame(p, pts, n, list(range(len(pts))), True)
        else:
            for side in (1, -1):
                frame(p, pts, n, arc_indices(side), False)
    members(p, sec, j0, j1, lambda s: s < e - 1e-9, lambda s: True, True, True)
    tongues(p, rings[0], Vector((0, -1, 0)))
    tongues(p, rings[-1], Vector((0, 1, 0)))


def build_fuselage_M_aft(bl, surf, p, slots, joint, bulkhead):
    """fuselage_M's compartment behind the real bulkhead at the bay's front wall (bulkhead) to its joint at 25: the
    lining (the well's notch from the well's front end), the break face, the bulkhead with its stiffeners, the joint
    frame, member ends and tongues."""
    sec = make_section(bl, surf)
    centre = sum(bl.fus_profile(joint)[1:]) / 2
    p.envelope = p.bm.copy()
    b = bulkhead + af.WALL
    w = sec.slot0 - af.WALL
    stations = [(b, True, False), (w, True, False), (w, True, True), (joint, True, True)]
    rings = lining(p, sec, stations)
    af.open_joint(p, bl.st(joint), slots, rings[-1], Vector((0, 1, 0)))
    centre_v = Vector((0, bl.st(b), centre))
    af.fill(p, rings[0], None, Vector((0, 1, 0)), "plate", centre_v)
    pts = sec.points(joint - 0.12, True, True)
    frame(p, pts, inward_normals(pts), list(range(len(pts))), True)
    # the bulkhead's stiffeners: vertical hats from the bay roof's back up to the lining, and a beam across
    roof = bl.AFT_BAY_ROOF + af.WALL
    for x in (-1.5, -0.75, 0.0, 0.75, 1.5):
        deg = surf.deg_for_x(b, x, lower=False) if x else 0.0
        top = sec.inner(b, deg).z - 0.03
        path = [Vector((x, bl.st(b), roof)), Vector((x, bl.st(b), top))]
        af.sweep(p, path, [Vector((0, 1, 0))] * 2, [Vector((1, 0, 0))] * 2,
                 [(-0.04, -0.002), (-0.025, 0.09), (0.025, 0.09), (0.04, -0.002)], ("web", "flange", "web", None),
                 caps=("plate", "plate"))
    zb = roof + 0.9
    half = sec.inner(b, surf.deg_for_z(b, zb)).x - 0.03
    af.sweep(p, [Vector((-half, bl.st(b), zb)), Vector((half, bl.st(b), zb))], [Vector((0, 1, 0))] * 2,
             [Vector((0, 0, 1))] * 2, [(-0.05, -0.002), (-0.035, 0.12), (0.035, 0.12), (0.05, -0.002)],
             ("web", "flange", "web", None), caps=("plate", "plate"))
    members(p, sec, b, joint, lambda s: True, lambda s: s > w + 1e-9, False, True, k0=3)
    tongues(p, rings[-1], Vector((0, 1, 0)))
