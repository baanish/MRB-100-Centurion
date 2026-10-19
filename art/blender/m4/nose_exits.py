"""The flight deck's exits in the nose (m4/nose.py, docs/COCKPIT-DESIGN.md): the escape hatch openings over the two
seats and the crew door opening on the left side, cut into the hull, walled and floored so the nose stays one closed
shell, and the panels that close them, each on its own part (the blockout's nose_hatch_L, nose_hatch_R and
nose_door_visible), so the game can blow the hatches off and swing the door.

The opening outlines and the hatch panels are rounded rectangles (flightdeck_layout): a hatch's in plan, as stations
and x outboard, the door's on the side, as stations and heights. The cut skin, the openings' floors and the panels'
faces are triangulated in (station, angle) space (mathutils.geometry.delaunay_2d_cdt), the outlines as constraint
edges and the hull grid's own points inside, so they keep the grid's density and lie on the fuselage surface as the
rest of the hull does. The hatch panels' skin is the hull's paint class, so the nose's paint runs on across the seam."""

import math

from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

import flightdeck_layout as fl

from . import surface as sf
from .paint import INTERIOR
from .surface import HULL, N

CUT_MARGIN = (0.15, 5.0)  # the cut skin reaches this far past the openings: metres along the body, degrees round it
# Hull grid points this close to an outline (metres in the triangulation's plane) give way to it. A fixed distance,
# not one tied to the outline's step: wider, the cut skin loses points along the nose's widest line and its triangles
# chord across the silhouette.
NEAR = 0.06
R_PARAM = 1.9  # metres per radian of angle in the triangulation's plane (the nose's mean half width here)


def plane(s, a):
    return Vector((s, math.radians(a) * R_PARAM))


def inside(q, poly):
    """Even-odd test of a 2D point against a polygon of 2D points."""
    hit = False
    for i in range(len(poly)):
        p0, p1 = poly[i], poly[i - 1]
        if (p0.y > q.y) != (p1.y > q.y) and q.x < p0.x + (q.y - p0.y) * (p1.x - p0.x) / (p1.y - p0.y):
            hit = not hit
    return hit


def near(q, poly, d):
    for i in range(len(poly)):
        a, b = poly[i - 1], poly[i]
        ab = b - a
        t = min(1.0, max(0.0, (q - a).dot(ab) / ab.length_squared))
        if (a + ab * t - q).length < d:
            return True
    return False


def triangulate(boundary, holes, steiner):
    """Triangles over a (station, angle) region: boundary and each hole loops of (s, a), steiner extra (s, a) points
    inside. Returns index triples into boundary + holes + steiner, those inside a hole dropped."""
    pts = boundary + [p for h in holes for p in h] + steiner
    flat = [plane(s, a) for s, a in pts]
    nb = len(boundary)
    edges, loops, i0 = [], [], nb
    for h in holes:
        edges += [(i0 + i, i0 + (i + 1) % len(h)) for i in range(len(h))]
        loops.append(flat[i0:i0 + len(h)])
        i0 += len(h)
    _, _, tris, orig, _, _ = delaunay_2d_cdt(flat, edges, [list(range(nb))], 1, 1e-9)
    out = []
    for t in tris:
        if any(len(orig[i]) != 1 for i in t):
            raise SystemExit("nose exits: the triangulation merged or added a vertex")
        idx = [orig[i][0] for i in t]
        c = sum((flat[i] for i in idx), Vector((0, 0))) / 3
        if not any(inside(c, loop) for loop in loops):
            out.append(idx)
    return out


def faces_on(part, surf, pts, verts, tris, slot, cls, outward):
    """Faces over verts for each triangle, wound along the surface normal at its centre (outward) or against it."""
    faces = []
    for idx in tris:
        vs = [verts[i] for i in idx]
        n = (vs[1].co - vs[0].co).cross(vs[2].co - vs[0].co)
        s, a = sum(pts[i][0] for i in idx) / 3, sum(pts[i][1] for i in idx) / 3
        if (n.dot(surf.normal(s, a)) > 0) != outward:
            vs.reverse()
        faces.append(part.bm.faces.new(vs))
    part.tag(faces, slot, cls)
    return faces


def hatch_loop(surf, side, inset=0.0):
    """A hatch outline as (station, angle) points on the side's half of the crown."""
    return [(s, surf.deg_for_x(s, side * x, lower=False)) for s, x in fl.hatch_outline(inset)]


def door_loop(surf, inset=0.0):
    """The crew door's outline as (station, angle) points on the left side."""
    return [(s, surf.deg_for_z(s, z)) for s, z in fl.door_outline(inset)]


def grid_points(g, r0, r1, k0, k1):
    """The hull grid's points strictly inside a window of rings r0..r1 and columns k0..k1, as (s, a, vertex)."""
    return [(g.stations[r], sf.ring_deg(k), g.V[r][k % N]) for r in range(r0 + 1, r1) for k in range(k0 + 1, k1)]


def cut_window(part, surf, g, holes, slot, cls):
    """Replace the hull faces over the openings with skin triangulated round them, from CUT_MARGIN outside the
    holes' extent. Returns, per hole, its outer ring as (s, a, vertex) and the removed grid points inside it."""
    bm = part.bm
    s_lo = min(s for h in holes for s, _ in h) - CUT_MARGIN[0]
    s_hi = max(s for h in holes for s, _ in h) + CUT_MARGIN[0]
    a_lo = min(a for h in holes for _, a in h) - CUT_MARGIN[1]
    a_hi = max(a for h in holes for _, a in h) + CUT_MARGIN[1]
    r0 = max(r for r, s in enumerate(g.stations) if s <= s_lo)
    r1 = min((r for r, s in enumerate(g.stations) if s >= s_hi), default=len(g.stations) - 1)
    k0, k1 = math.floor(a_lo / sf.ring_deg(1)), math.ceil(a_hi / sf.ring_deg(1))
    cut = [g.F.pop((r, k % N)) for r in range(r0, r1) for k in range(k0, k1)]
    old_edges = {e for f in cut for e in f.edges}
    for f in cut:
        bm.faces.remove(f)

    def grid(r, k):
        return g.stations[r], sf.ring_deg(k), g.V[r][k % N]

    boundary = ([grid(r0, k) for k in range(k0, k1 + 1)] + [grid(r, k1) for r in range(r0 + 1, r1 + 1)]
                + [grid(r1, k) for k in range(k1 - 1, k0 - 1, -1)] + [grid(r, k0) for r in range(r1 - 1, r0, -1)])
    flat = [[plane(s, a) for s, a in h] for h in holes]
    keep, under = [], [[] for _ in holes]
    for q in grid_points(g, r0, r1, k0, k1):
        p = plane(q[0], q[1])
        hit = [i for i, h in enumerate(flat) if inside(p, h) or near(p, h, NEAR)]
        if not hit:
            keep.append(q)
            continue
        if inside(p, flat[hit[0]]) and not near(p, flat[hit[0]], NEAR):
            under[hit[0]].append((q[0], q[1]))
        bm.verts.remove(q[2])
    rings = [[(s, a, bm.verts.new(surf.point(s, a))) for s, a in h] for h in holes]
    pts = [(s, a) for s, a, _ in boundary] + [(s, a) for r in rings for s, a, _ in r] + [(s, a) for s, a, _ in keep]
    verts = [v for _, _, v in boundary] + [v for r in rings for _, _, v in r] + [v for _, _, v in keep]
    faces_on(part, surf, pts, verts, triangulate(pts[:len(boundary)], holes, pts[len(boundary) + sum(map(len, holes)):]),
             slot, cls, outward=True)
    for e in old_edges:  # the grid's edges the triangulation didn't reuse
        if e.is_valid and not e.link_faces:
            bm.edges.remove(e)
    return list(zip(rings, under))


def line_opening(part, surf, ring, under, depth, slot, cls):
    """An opening's walls from its outer ring down depth under the skin, and its floor across there, triangulated
    over the grid points under it so it follows the surface."""
    bm = part.bm
    low = [(s, a, bm.verts.new(surf.point(s, a, -depth))) for s, a, _ in ring]
    centre = sum((v.co for _, _, v in low), Vector()) / len(low)
    walls = []
    for i in range(len(ring)):
        j = (i + 1) % len(ring)
        quad = (ring[i][2], ring[j][2], low[j][2], low[i][2])
        f = bm.faces.new(quad)
        f.normal_update()
        if f.normal.dot(centre - sum((v.co for v in quad), Vector()) / 4) < 0:
            f.normal_flip()
        walls.append(f)
        sf.seam(bm, ring[i][2], ring[j][2])
        sf.seam(bm, low[i][2], low[j][2])
    part.tag(walls, slot, cls)
    inner = [(s, a, bm.verts.new(surf.point(s, a, -depth))) for s, a in under]
    pts = [(s, a) for s, a, _ in low] + [(s, a) for s, a, _ in inner]
    verts = [v for _, _, v in low] + [v for _, _, v in inner]
    faces_on(part, surf, pts, verts, triangulate(pts[:len(low)], [], pts[len(low):]), slot, cls, outward=True)


def vestibule(bl, part, ring, slot, mech):
    """The room the crew door opens into (fl.VESTIBULE_X, PASSAGE_*, STEPS): straight in from the doorway's ring on the
    skin to a wall at VESTIBULE_X, with the passage's mouth in that wall; the passage running in over the gear well's
    roof to PASSAGE_X; two steps up to it; a ladder on its aft wall up to the flight deck's floor hatch. Its faces face
    into the room and take the interior paint, so the nose stays a closed shell round it."""
    bm = part.bm
    x_in, (p0, p1), (z0, z1), x_end = fl.VESTIBULE_X, fl.PASSAGE_S, fl.PASSAGE_Z, fl.PASSAGE_X
    outline = fl.door_outline()
    if len(outline) != len(ring):
        raise SystemExit("nose exits: the door's ring and outline disagree")
    inner = [bm.verts.new(Vector((x_in, bl.st(s), z))) for s, z in outline]
    centre = Vector((x_in + 0.35, bl.st(sum(fl.CREW_DOOR[:2]) / 2), (fl.CREW_DOOR[2] + fl.CREW_DOOR[3]) / 2))

    def into(fs, c):
        for f in fs:
            f.normal_update()
            if f.normal.dot(c - f.calc_center_median()) < 0:
                f.normal_flip()
        return fs

    walls = []
    for i in range(len(ring)):
        j = (i + 1) % len(ring)
        walls.append(bm.faces.new((ring[i][2], ring[j][2], inner[j], inner[i])))
        sf.seam(bm, ring[i][2], ring[j][2])
    part.tag(into(walls, centre), slot, INTERIOR)
    # the inboard wall: the door's outline at VESTIBULE_X with the passage's mouth cut in it
    mouth_sz = [(p0, z0), (p1, z0), (p1, z1), (p0, z1)]
    mouth = [bm.verts.new(Vector((x_in, bl.st(s), z))) for s, z in mouth_sz]
    pts = [Vector((s, z)) for s, z in outline] + [Vector(q) for q in mouth_sz]
    nb = len(outline)
    _, _, tris, orig, _, _ = delaunay_2d_cdt(pts, [(nb + k, nb + (k + 1) % 4) for k in range(4)], [list(range(nb))], 1, 1e-9)
    verts = inner + mouth
    back = []
    for t in tris:
        idx = [orig[i][0] for i in t]
        c = sum((pts[i] for i in idx), Vector((0, 0))) / 3
        if p0 < c.x < p1 and z0 < c.y < z1:
            continue
        back.append(bm.faces.new([verts[i] for i in idx]))
    part.tag(into(back, centre), slot, INTERIOR)
    # the passage: a box from the mouth in to PASSAGE_X
    end = [bm.verts.new(Vector((x_end, bl.st(s), z))) for s, z in mouth_sz]
    pc = Vector(((x_in + x_end) / 2, bl.st((p0 + p1) / 2), (z0 + z1) / 2))
    box = [bm.faces.new((mouth[k], mouth[(k + 1) % 4], end[(k + 1) % 4], end[k])) for k in range(4)]
    box.append(bm.faces.new(end))
    part.tag(into(box, pc), slot, INTERIOR)
    # two steps up the inboard wall to the passage's floor, and the ladder up its aft wall to the floor hatch
    zb = fl.CREW_DOOR[2]
    for top, depth in fl.STEPS:
        sf.box(part, Vector((x_in + depth / 2, bl.st((p0 + p1) / 2), (zb + top) / 2)),
               (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))), (depth, p1 - p0, top - zb), slot, INTERIOR)
    axes = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
    y = bl.st(p1 - 0.06)
    for x in (-0.17, 0.17):
        sf.box(part, Vector((x, y, (z0 + z1) / 2)), axes, (0.025, 0.025, z1 - z0), mech)
    for k in range(4):
        sf.box(part, Vector((0.0, y, z0 + 0.20 + 0.22 * k)), axes, (0.32, 0.02, 0.02), mech)


def panel(part, surf, loop, steiner, top, bottom, slot_top, cls_top, slot_rest, cls_rest, mirror=False):
    """A closed panel over an outline of (station, angle) points: its outer face top and its inner face bottom metres
    off the surface, triangulated over the steiner points, and its edge walls. mirror builds the -X twin of the
    outline's panel, vertex for vertex, so its faces copy the source's UVs."""
    bm = part.bm
    tris = triangulate(loop, [], steiner)
    pts = loop + steiner
    sign = -1 if mirror else 1

    def at(s, a, off):
        p = surf.point(s, a, off)
        return bm.verts.new(Vector((sign * p.x, p.y, p.z)))

    T = [at(s, a, top) for s, a in pts]
    B = [at(s, a, bottom) for s, a in pts]
    m_pts = [(s, sign * a) for s, a in pts]
    outer = faces_on(part, surf, m_pts, T, tris, slot_top, cls_top, outward=True)
    inner = faces_on(part, surf, m_pts, B, tris, slot_rest, cls_rest, outward=False)
    n = len(loop)
    centre = sum((v.co for v in T[:n]), Vector()) / n
    sides = []
    for i in range(n):
        j = (i + 1) % n
        f = bm.faces.new((T[i], T[j], B[j], B[i]))
        f.normal_update()
        if f.normal.dot(sum((v.co for v in (T[i], T[j])), Vector()) / 2 - centre) < 0:
            f.normal_flip()
        sides.append(f)
        sf.seam(bm, T[i], T[j])
        sf.seam(bm, B[i], B[j])
    sf.seam(bm, T[0], B[0])
    part.tag(sides, slot_rest, cls_rest)
    return outer, inner, sides


def inside_points(g, loop, column_step=1):
    """The hull grid's (station, angle) points well inside an outline, every column_step-th column, as panel steiner
    points."""
    flat = [plane(s, a) for s, a in loop]
    out = []
    for r, s in enumerate(g.stations):
        for k in range(-N // 4, N // 2 + 1, column_step):
            p = plane(s, sf.ring_deg(k))
            if inside(p, flat) and not near(p, flat, NEAR):
                out.append((s, sf.ring_deg(k)))
    return out


def build(bl, surf, p, g, exits, slots):
    """Cut the hatch and door openings into the nose hull g (sf.hull's grid on part p) and build their panels on the
    exit parts: exits maps nose_hatch_L, nose_hatch_R and nose_door_visible to their sf.Part."""
    SKIN, STRUCT = slots[0], slots[1]
    hatches = [hatch_loop(surf, side) for side in (1, -1)]
    for ring, under in cut_window(p, surf, g, hatches, SKIN, HULL):
        line_opening(p, surf, ring, under, fl.HATCH_DEPTH, STRUCT, 0)
    door = door_loop(surf)
    for ring, _ in cut_window(p, surf, g, [door], SKIN, HULL):
        vestibule(bl, p, ring, SKIN, slots[3])

    loop = hatch_loop(surf, 1, fl.HATCH_GAP)
    steiner = inside_points(g, loop)
    for name, mirror in (("nose_hatch_L", False), ("nose_hatch_R", True)):
        panel(exits[name], surf, loop, steiner, 0.0, -fl.HATCH_DEPTH, SKIN, HULL, STRUCT, 0, mirror)
    loop = door_loop(surf, fl.DOOR_GAP)
    panel(exits["nose_door_visible"], surf, loop, inside_points(g, loop, 2), 0.0, -fl.DOOR_THICK, SKIN, HULL, STRUCT, 0)
