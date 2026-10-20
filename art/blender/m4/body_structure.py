"""The body's damage structure (m4/airframe.py) for every fuselage section the art builds thin-walled: fuselage_F (with
F2), fuselage_M, fuselage_R and the tail cone (with tail_end). The nose and flight deck stay the cockpit's.

A section's air space, in section, is the hull's inside WALL in from the skin, less the bays' cavities (walls straight up
from the doors' hinge lines to the roof) and the AWACS well's (walls down to its floor), each backed by WALL: Section.
Lofted along the part it is the lining, with rows only where the body's section changes; at each joint the flat cap
opens onto it as a break face. In it stand an open frame ring just inside each break and each station cut
(part_splits), side frames every FRAME_PITCH, a longeron a side and one along every line the part's panels come away
on, a systems run a side, torn skin tongues past each break, and, where the section carries fuel (TANKS), its wet
compartment: a sealed box with fuel lines that run on past the nearest joint as broken ends. Lean by design
(owner, 2026-10-18: "Go leaner")."""

import math

from mathutils import Vector

import part_splits as ps

from . import airframe as af

ARC = 6  # lining segments a side between the bay wall (or the keel) and the well (or the crown)
BAY_POINTS = 8  # section points over the bay's back (under the bay where there is none)
FRAME = (0.05, 0.11, 0.006)  # ring frames: width, depth inward, how far their outer side sits behind the lining
FRAME_PITCH = 2.4  # m between side frames (every other bay frame)
LONGERON = (0.06, 0.06)  # width, depth
LONGERON_ARC = 3  # the lining point on each side's arc that carries the side longeron
SYSTEMS = ((4, 0.18, 0.04, "cable"), (4, 0.17, 0.025, "pipe"))  # +x, -x: arc point, inward offset, radius, strip
PAST = (0.16, 0.07, 0.12, 0.2, 0.09)  # how far members run on past a joint (cycled)
TONGUES = (0.0, 0.16, 0.0, 0.12, 0.0, 0.18)  # torn tongue reach per arc segment from the bay wall up (0 none)
SEAM_OFFSET = 3.0  # degrees a cut-line longeron stands off the panel's edge, on the core's side
ROW_TOL = 0.01  # m: lining rows are added until the loft between rows stays this close to the section
# The wet compartments (fuel moved out of the wings, 2026-10-18): (stations from, to, half width, bottom, top) of the
# sealed box, inside the core's air space
# sealed box, inside the core's air space, and the stations its two fuel lines run to (forward, aft), past which they
# end broken; each line stays in the air space (never through a bay)
TANKS = {"fuselage_M": ((17.6, 23.4, 1.2, 1.7, 3.1), (17.0, 17.0)),  # the centre box, 15,000 kg, under the wing box
         "fuselage_F": ((8.0, 11.9, 1.2, 4.45, 5.25), (7.0, 12.0)),  # forward, 3,000 kg, a saddle on the forward bay's roof
         "fuselage_R": ((26.0, 31.5, 1.3, 4.47, 4.84), (25.0, 33.0)),  # aft, 3,000 kg, between the bay's roof and the well
         "tailcone": ((33.6, 37.4, 1.0, 2.6, 3.6), (33.0, 38.3))}  # tail, 3,000 kg, over the belly ramp


class Section:
    """The air space's section at any station as a closed loop of points in a fixed order: the +x arc from the bay
    wall's back (or the keel side) up to the well (or the crown) (ARC + 1), the well's back down and across its floor
    (4), the -x arc back down (ARC + 1), then BAY_POINTS over the bay's back. Where a bay or the well is absent its
    points lie on the lining instead, so every station's loop has the same count and the loops loft."""

    def __init__(self, bl, surf, rim_deg, hinge_deg, roof, bays, well, seams=()):
        self.bl, self.surf = bl, surf
        self.rim_deg, self.hinge_deg, self.roof = rim_deg, hinge_deg, roof
        self.bays, self.well = bays, well
        lo, hi = bl.well_box()
        self.well_x, self.floor = hi.x, lo.z
        # the panel seams the side arcs run through (degrees from the top, largest first) and the arc segments between
        # each two of the arc's ends and seams (fix_arc): a seam is always an arc point, so the lining parts along the
        # skin's seam and the wall between them is a wall, not a sheet under the panel's skin
        self.seams = sorted({abs(e) for e in seams}, reverse=True)
        self.segments = [ARC]

    def fix_arc(self, s):
        """Share the arc's ARC segments between its pieces at station s in proportion to their angles, at least one
        each, once for the whole section, so a seam keeps its index on every ring."""
        top, low, _, _ = self.angles(s)
        ends = [low] + self.seams + [top]
        spans = [a - b for a, b in zip(ends, ends[1:])]
        if any(d <= 0 for d in spans) or len(spans) > ARC:
            raise SystemExit(f"panel seams {self.seams} don't fit the lining's arc from {low:.1f} to {top:.1f} deg")
        self.segments = [1] * len(spans)
        while sum(self.segments) < ARC:
            k = max(range(len(spans)), key=lambda i: spans[i] / self.segments[i])
            self.segments[k] += 1

    def arc(self, s, low, top):
        """The side arc's ARC + 1 angles from low to top, through every seam."""
        ends = [low] + self.seams + [top]
        if any(a <= b for a, b in zip(ends, ends[1:])):
            raise SystemExit(f"panel seams {self.seams} leave the lining's arc from {low:.1f} to {top:.1f} deg at station {s:.2f}")
        out = [low]
        for (a, b), n in zip(zip(ends, ends[1:]), self.segments):
            out += [a + (b - a) * i / n for i in range(1, n + 1)]
        return out

    def has_bay(self, s):
        return any(b0 <= s <= b1 for b0, b1 in self.bays)

    def has_well(self, s):
        return self.well is not None and self.well[0] <= s <= self.well[1]

    def inner(self, s, deg):
        return self.surf.point(s, deg) - self.surf.normal(s, deg) * af.WALL

    def deg_for_inner_x(self, s, x, lo, hi):
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
        rim = self.surf.point(s, self.rim_deg)
        top = self.deg_for_inner_x(s, rim.x + 0.04, self.rim_deg, 90.0)
        xe = self.surf.point(s, self.hinge_deg).x
        low = self.deg_for_inner_x(s, xe + af.WALL + 0.01, 90.0, self.hinge_deg)
        return top, low, rim, xe

    def points(self, s, bay, well):
        top, low, rim, xe = self.angles(s)
        y = self.bl.st(s)
        arc = self.arc(s, low, top)
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
    area = sum(a.x * b.z - b.x * a.z for a, b in zip(pts, pts[1:] + pts[:1]))
    sign = 1.0 if area > 0 else -1.0
    out = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        d = b - a
        n = Vector((-d.z, 0.0, d.x)) * sign
        out.append(n.normalized() if n.length > 1e-9 else Vector((0, 0, 1)))
    return out


def inward_edges(pts):
    area = sum(a.x * b.z - b.x * a.z for a, b in zip(pts, pts[1:] + pts[:1]))
    sign = 1.0 if area > 0 else -1.0
    out = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        n = Vector((-(b.z - a.z), 0.0, b.x - a.x)) * sign
        out.append(n.normalized() if n.length > 1e-9 else Vector((0, 0, 1)))
    return out


def arc_indices(side):
    if side > 0:
        return list(range(ARC + 1))
    first = ARC + 1 + 4
    return list(range(first + ARC, first - 1, -1))


def ring(part, pts, share=None):
    out = []
    for i, p in enumerate(pts):
        if share is not None and (share[i].co - p).length < 1e-7:
            out.append(share[i])
        else:
            out.append(part.bm.verts.new(p))
    return out


def rows(sec, s0, s1, switches):
    """Lining stations from s0 to s1: the ends, each section switch (doubled: (s, before, after)), and rows added
    between until the straight loft stays within ROW_TOL of the true section."""
    marks = sorted({s0, s1} | {s for s, _, _ in switches if s0 < s < s1})

    def state(s, side):  # the cavities at s, just before (side -1) or after (+1) any switch there
        bay, well = sec.has_bay(s), sec.has_well(s)
        for t, before, after in switches:
            if abs(t - s) < 1e-9:
                bay, well = before if side < 0 else after
        return bay, well

    out = []
    for a, b in zip(marks, marks[1:]):
        seg = [a, b]
        changed = True
        while changed:
            changed = False
            for i in range(len(seg) - 1):
                m = (seg[i] + seg[i + 1]) / 2
                if seg[i + 1] - seg[i] < 0.5:
                    continue
                st_ = state(m, 1)
                pa, pb, pm = (sec.points(x, *st_) for x in (seg[i], seg[i + 1], m))
                if max((u.lerp(v, 0.5) - w).length for u, v, w in zip(pa, pb, pm)) > ROW_TOL:
                    seg.insert(i + 1, m)
                    changed = True
                    break
        for x in seg[:-1]:
            out.append((x,) + state(x, 1))
        out.append((b,) + state(b, -1))
    merged = [out[0]]
    for r in out[1:]:
        if abs(r[0] - merged[-1][0]) < 1e-9 and r[1:] == merged[-1][1:]:
            continue
        merged.append(r)
    return merged


def lining(part, sec, stations):
    rings_ = []
    for s, bay, well in stations:
        prev = rings_[-1] if rings_ and abs(stations[len(rings_) - 1][0] - s) < 1e-9 else None
        rings_.append(ring(part, sec.points(s, bay, well), prev))
    inward = [inward_edges([v.co for v in r]) for r in rings_]

    def facing(r, j):
        if abs(stations[r][0] - stations[r + 1][0]) < 1e-9:
            return Vector((0, 1 if sum(stations[r + 1][1:]) < sum(stations[r][1:]) else -1, 0))
        return inward[r][j]
    af.loft(part, rings_, "lining", facing)
    return rings_


def frame(part, pts, normals, indices, closed, faces=("web", "flange", "web", None)):
    w, d, e = FRAME
    path = [pts[i] for i in indices]
    inward = [normals[i] for i in indices]
    along = [Vector((0, 1, 0))] * len(path)
    section = [(-w / 2, -e), (-w / 2, d), (w / 2, d), (w / 2, -e)]
    return af.sweep(part, path, inward, along, section, faces, closed=closed,
                    caps=None if closed else ("plate", "plate"))


def run_points(sec, rows_, s0, s1, where):
    """Points, inward normals and tangents along the lining from s0 to s1 at where(loop, s) -> (point, normal, tangent)."""
    stations = sorted({s0, s1} | {r[0] for r in rows_ if s0 < r[0] < s1})
    pts, normals, tangents = [], [], []
    for s in stations:
        loop = sec.points(s, sec.has_bay(s), sec.has_well(s))
        p, n, t = where(loop, s)
        pts.append(p)
        normals.append(n)
        tangents.append(t)
    return pts, normals, tangents


def at_even(sec, side, i):
    """The side arc's i-th point were it run evenly from its low end to its top: the side longeron's and the systems
    runs' place, whatever seams the lining's arc runs through (Section.arc)."""
    def where(loop, s):
        top, low, _, _ = sec.angles(s)
        return at_angle(sec, side * (low + (top - low) * i / ARC))(loop, s)
    return where


def at_angle(sec, deg):
    def where(loop, s):
        p = sec.inner(s, deg)
        n = -sec.surf.normal(s, deg)
        n = Vector((n.x, 0.0, n.z)).normalized()
        return p, n, Vector((0, 1, 0)).cross(n).normalized()
    return where


def longeron(part, pts, normals, tangents):
    w, d = LONGERON
    section = [(-w / 2, -FRAME[2]), (-w / 2, d), (w / 2, d), (w / 2, -FRAME[2])]
    return af.sweep(part, pts, normals, tangents, section, ("web", "flange", "web", None), caps=("torn", "torn"))


def seam_angles(name):
    """The angles round the body along which this part's panels come away (cheeks aside), each stood off SEAM_OFFSET
    on the core's side (a seam between two panels: on one of them)."""
    return [e + i * SEAM_OFFSET for e, i in band_edges(name)]


def band_edges(name):
    """The angles round the body along which this part's panels come away (cheeks aside), each with the side its core
    lies on (-1, +1)."""
    edges = []
    for spec in ps.SPLITS:
        if spec["kind"] != "panel" or ps.root_source(spec["name"]) != name:
            continue
        if ps.BY_NAME.get(spec["source"], {}).get("kind") == "panel":
            continue
        lo, hi = spec["region"][1:3]
        for edge, into in ((lo, -1.0), (hi, 1.0)):
            if not any(abs(edge - e) < 1 for e, _ in edges):
                edges.append((edge, into))
    return edges


def tank(part, box, ends):
    """A wet compartment: the sealed box on the trim's wet strip, and two fuel lines from its ends at mid height that
    run on to the stations ends (forward, aft) and a little past them, broken."""
    s0, s1, hw, z0, z1 = box
    y0, y1 = part_y(s0), part_y(s1)
    c = [Vector((x, y, z)) for y in (y0, y1) for z in (z0, z1) for x in (-hw, hw)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 2, 6, 4), (1, 5, 7, 3), (2, 3, 7, 6), (0, 4, 5, 1))
    bm = part.bm
    verts = [bm.verts.new(p) for p in c]
    centre = sum(c, Vector()) / 8
    for idx in faces:
        vs = [verts[i] for i in idx]
        L = [(vs[1].co - vs[0].co).length, (vs[2].co - vs[1].co).length]
        uv = [(0.0, af.strip_v("wet", 0)), (L[0] * af.UV_PER_M, af.strip_v("wet", 0)),
              (L[0] * af.UV_PER_M, af.strip_v("wet", 1)), (0.0, af.strip_v("wet", 1))]
        f = af.face(part, vs, uv)
        af.orient(f, f.calc_center_median() - centre)
    zl = (z0 + z1) / 2
    for x, end in ((0.5 * hw, ends[0]), (-0.5 * hw, ends[1])):
        a = y0 if end <= s0 else y1
        b = part_y(end) + (-0.18 if end <= s0 else 0.22)
        af.tube(part, [Vector((x, a, zl)), Vector((x, b, zl))], 0.03, "pipe", caps=("plate", "torn"))


part_y = None  # bl.st, set by build_section


def build_section(bl, surf, part, slots, s0, s1, bays=(), well=None, open_ends=(True, True)):
    """A thin-walled section of the body between stations s0 and s1: the lining (with the cavities bays, a list of
    (from, to), and well, (from, to) or None), the break faces at the open ends, frames, longerons (one a side and one
    on every panel seam), systems runs, tongues and the part's wet compartment (TANKS)."""
    global part_y
    part_y = bl.st
    from .fuselage_aft import BAY_DOOR, spine_extent
    sec = Section(bl, surf, spine_extent(bl)[2], BAY_DOOR[2], bl.AFT_BAY_ROOF, list(bays), well,
                  [e for e, _ in band_edges(part.name)])
    sec.fix_arc((s0 + s1) / 2)
    if part.envelope is None:
        part.envelope = part.bm.copy()
    switches = []
    for b0, b1 in bays:
        switches += [(b0 - af.WALL, (False, None), (True, None)), (b1 + af.WALL, (True, None), (False, None))]
    if well is not None:
        switches += [(well[0] - af.WALL, (None, False), (None, True)), (well[1] + af.WALL, (None, True), (None, False))]
    sw = []
    for s, before, after in switches:
        if not s0 < s < s1:
            continue
        b, w = sec.has_bay(s), sec.has_well(s)
        sw.append((s, (before[0] if before[0] is not None else b, before[1] if before[1] is not None else w),
                   (after[0] if after[0] is not None else b, after[1] if after[1] is not None else w)))
    rows_ = rows(sec, s0, s1, sw)
    rings_ = lining(part, sec, rows_)
    outs = (Vector((0, -1, 0)), Vector((0, 1, 0)))
    for open_, loop, out in zip(open_ends, (rings_[0], rings_[-1]), outs):
        if open_:
            af.open_joint(part, bl.st(s0 if out.y < 0 else s1), slots, loop, out)
            tongues(part, sec, s0 if out.y < 0 else s1, out)
    cuts = [ps.region(bl, s["region"])[0][0].y + bl.Y0 for s in ps.SPLITS
            if s["kind"] == "cut" and s["source"] == part.name and s["region"][0] == "station_gt"]
    ring_at = [s0 + 0.12] * open_ends[0] + [s1 - 0.12] * open_ends[1] + [c + d for c in cuts for d in (-0.12, 0.12)]
    for s in ring_at:
        pts = sec.points(s, sec.has_bay(s), sec.has_well(s))
        frame(part, pts, inward_normals(pts), list(range(len(pts))), True, ("web", "flange", None, None))
    s = s0 + FRAME_PITCH / 2
    while s < s1 - 0.6:
        if all(abs(s - r) > 0.5 for r in ring_at):
            pts = sec.points(s, sec.has_bay(s), sec.has_well(s))
            n = inward_normals(pts)
            for side in (1, -1):
                frame(part, pts, n, arc_indices(side), False)
        s += FRAME_PITCH
    k = 0
    a, b = s0 - PAST[0] * open_ends[0], s1 + PAST[2] * open_ends[1]
    for side in (1, -1):
        longeron(part, *run_points(sec, rows_, a, b, at_even(sec, side, LONGERON_ARC)))
    for deg in seam_angles(part.name):
        longeron(part, *run_points(sec, rows_, s0 - PAST[k % 5] * open_ends[0], s1 + PAST[(k + 2) % 5] * open_ends[1],
                                   at_angle(sec, deg)))
        k += 1
    for side, (i, off, radius, strip) in zip((1, -1), SYSTEMS):
        pts, normals, _ = run_points(sec, rows_, s0 - 0.24 * open_ends[0], s1 + 0.3 * open_ends[1],
                                     at_even(sec, side, i))
        af.tube(part, [p + n * off for p, n in zip(pts, normals)], radius, strip, caps=("torn", "torn"))
    if part.name in TANKS:
        tank(part, *TANKS[part.name])
    return rings_


def tongues(part, sec, s, out_dir):
    """Torn skin tongues past the break at station s, TONGUES reach per segment of each side arc as it runs evenly
    (at_even), whatever seams the lining's arc runs through."""
    for side in (1, -1):
        edge, inward = zip(*[at_even(sec, side, i)(None, s)[:2] for i in range(ARC + 1)])
        lengths = TONGUES if side > 0 else TONGUES[3:] + TONGUES[:3]
        af.teeth(part, list(edge), list(inward), out_dir, lengths)
