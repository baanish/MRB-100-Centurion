"""fuselage_aft's aft bay: the blockout's cavity (build_centurion.aft_bay_box) cut into the belly of fuselage_M and
fuselage_R, dark painted walls straight up from the doors' hinge lines to the roof, and dark structural fittings
as the forward bay's (m4/nose.py bay_interior): ring frames, longerons along the walls, the rack beam and ejector blocks over
the hardpoint, door actuators and end bulkhead stiffeners; and the doors' ribs. Nothing spans the opening: the doors
close against each other on the keel line. The cavity runs on through the part joint at 25, whose caps are notched to
its section, and each piece of the interior belongs to the part its station is on. A helper of fuselage_aft.py; it
declares no GROUP."""

import bmesh
from mathutils import Vector

from . import surface as sf
from .paint import INTERIOR
from .surface import N

PARTS = ("fuselage_M", "fuselage_R")  # the parts the bay is cut into, ahead of and behind their joint
BAY_K = (25, 39)  # the hull columns on the doors' hinge lines (fuselage_aft.DOOR_COLUMNS)
DOOR_SEAM = 0.35  # degrees between the two doors' inner edges on the keel line, as the forward bay's
# Ring frames, the forward bay's 1.2 m pitch kept off the ejector blocks, and the rack's ejector blocks, both as
# metres from the hardpoint (the doors' middle); door actuators as metres in from the doors' ends.
FRAMES = (-3.4, -2.2, -1.0, 0.2, 1.4, 2.6, 3.8)
EJECTORS = (-2.0, -0.7, 0.7, 2.0)
ACTUATORS = (2.0, 1.8)
ROOM = 0.05  # the structure stands this far above and below every stock mount's stores (check, bay_fit), as forward


def cut(bl, p, g, s0, s1, struct):
    """The cavity in hull Grid g of part p between its rings at stations s0 and s1 (the bay's ends, or the part's
    joint at 25 where the cavity runs on): the hull between the hinge columns comes out, walls go up from them to the
    roof, and across a joint the cap is notched to the cavity's section, so it meets the neighbour's notch."""
    k0, k1 = BAY_K
    st = g.stations
    r0, r1 = sf.ring_index(g, s0), sf.ring_index(g, s1)
    roof_z = bl.AFT_BAY_ROOF

    def roof(q, r, k):
        xe = g.V[r][k0].co.x
        return Vector((xe * (1 - 2 * (k - k0) / (k1 - k0)), q.y, roof_z))

    _, walls = sf.recess(p, g, r0, r1, k0, k1, roof, p.slots[0], INTERIOR)
    for r, ends in ((r0, walls[0:2 * (k1 - k0):2]), (r1, walls[1:2 * (k1 - k0):2])):
        if r in (0, len(st) - 1):
            notch(p, g, r, ends, struct)


def notch(p, g, r, ends, struct):
    """Open the cavity's end at joint ring r: drop its end wall (ends, the faces (V[r][k], V[r][k + 1], W[k + 1], W[k])
    from the hinge column k0 to k1) and the flat cap across the ring, and close the ring with a cap round the hull's
    outline above the bay (with any notch already in it, the AWACS well's) and the cavity's walls and roof below."""
    bm = p.bm
    k0, k1 = BAY_K
    walls = [ends[0].verts[3]] + [f.verts[2] for f in ends]  # W[k0] .. W[k1]: up the wall, across the roof, down
    bottom = set(g.V[r][k0 + 1:k1])
    y = g.V[r][k0].co.y  # the crown's vertex is gone where the AWACS well runs through the joint
    cap = [f for f in bm.faces if f not in ends and all(abs(v.co.y - y) < 1e-6 for v in f.verts)]
    for f in cap:
        f.normal_update()
    normal = sum((f.normal for f in cap), Vector())
    edges = {}
    for f in cap:
        for e in f.edges:
            edges[e] = edges.get(e, 0) + 1
    link = {}
    for e, n in edges.items():
        if n == 1:
            for a, b in ((e.verts[0], e.verts[1]), (e.verts[1], e.verts[0])):
                link.setdefault(a, []).append(b)
    start, end = g.V[r][k0], g.V[r][k1]
    rim, prev = [start], g.V[r][k0 + 1]
    while rim[-1] is not end:  # from the hinge at k0 round the top to the hinge at k1, the bay's bottom left out
        nxt = next(v for v in link[rim[-1]] if v is not prev)
        prev = rim[-1]
        rim.append(nxt)
    bmesh.ops.delete(bm, geom=cap + list(ends), context="FACES_ONLY")
    face = bm.faces.new(rim + walls[::-1])
    face.normal_update()
    if face.normal.dot(normal) < 0:
        face.normal_flip()
    loop = rim + walls[::-1]
    for a, b in zip(loop, loop[1:] + loop[:1]):
        sf.seam(bm, a, b)
    tris = bmesh.ops.triangulate(bm, faces=[face])["faces"]
    p.tag(tris, struct)
    bmesh.ops.delete(bm, geom=[v for v in bottom if v.is_valid and not v.link_faces], context="VERTS")
    loose = [e for e in bm.edges if not e.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="EDGES")


def interior(bl, surf, parts, door, joint, slots):
    """The bay's structure behind its doors (door: stations and angles, +X side), each piece on the part its station
    is on (parts: PARTS' Parts; joint: the station between them), the longerons split there."""
    SKIN, STRUCT, GLASS, MECH = slots[:4]
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    s0, s1, a0, _ = door
    hp = (s0 + s1) / 2
    zc = bl.AFT_BAY_ROOF
    ahead, behind = (parts[n] for n in PARTS)

    def owner(s):
        return ahead if s < joint else behind

    def edge(s):  # the left hinge line's x and z
        q = surf.point(s, a0)
        return q.x, q.z

    for s in (hp + d for d in FRAMES):
        xe, ze = edge(s)
        p = owner(s)
        for side in (1, -1):
            sf.box(p, Vector((side * (xe - 0.035), bl.st(s), (ze + zc) / 2)), (X, Y, Z), (0.07, 0.08, zc - ze), SKIN, INTERIOR)
        sf.box(p, Vector((0, bl.st(s), zc - 0.07)), (X, Y, Z), (2 * xe - 0.02, 0.08, 0.14), SKIN, INTERIOR)
    for a, b, p in ((s0, joint, ahead), (joint, s1, behind)):
        for side in (1, -1):  # straight: the hinge lines keep their x along the bay, onto the ramp too
            for z in (2.55, zc - 0.05):
                sf.tube(p, [Vector((side * (edge(s)[0] - 0.03), bl.st(s), z)) for s in (a, b)], 0.035, 6, SKIN, INTERIOR)
    for side in (1, -1):
        for s in (s0 + ACTUATORS[0], s1 - ACTUATORS[1]):
            xe, ze = edge(s)
            p = owner(s)
            a, b = Vector((side * (xe - 0.05), bl.st(s), 2.35)), Vector((side * (xe - 0.02), bl.st(s), ze + 0.05))
            sf.tube(p, [a, a + (b - a) * 0.6], 0.04, 8, MECH)
            sf.tube(p, [a + (b - a) * 0.55, b], 0.022, 8, MECH)
    sf.box(owner(hp), Vector((0, bl.st(hp), zc - 0.085)), (X, Y, Z), (0.2, 4.8, 0.17), MECH)
    for s in (hp + d for d in EJECTORS):  # ejector blocks a value step off the darker beam, so each reads on its own
        sf.box(owner(s), Vector((0, bl.st(s), zc - 0.085)), (X, Y, Z), (0.36, 0.1, 0.16), SKIN, INTERIOR)
    for s, d in ((s0, 1), (s1, -1)):
        for x in (0.0, 0.75, -0.75):
            zb = bl.fus_bottom_z(s, abs(x)) + 0.02
            sf.box(owner(s + d * 0.03), Vector((x, bl.st(s) + d * 0.03, (zb + zc) / 2)), (X, Y, Z), (0.07, 0.06, zc - zb),
                   SKIN, INTERIOR)


def door_ribs(bl, surf, p, door, side, struct):
    """A door's inner structure, seen when it opens, as the forward doors': curved ribs at the bay's frames and its
    ends and a beam along its middle, standing into the bay from the door's inner face."""
    s0, s1, a0, a1 = door
    hp = (s0 + s1) / 2
    for s in (s0 + 0.12,) + tuple(hp + d for d in FRAMES) + (s1 - 0.12,):
        corners = [(s - 0.025, a0 + 2.5), (s + 0.025, a0 + 2.5), (s + 0.025, a1 - 1.0), (s - 0.025, a1 - 1.0)]
        sf.surface_patch(p, surf, [(c, side * a) for c, a in corners], 1, 4, 0.008, -0.055, struct)
    am = (a0 + a1) / 2
    corners = [(s0 + 0.15, am - 0.8), (s1 - 0.15, am - 0.8), (s1 - 0.15, am + 0.8), (s0 + 0.15, am + 0.8)]
    sf.surface_patch(p, surf, [(c, side * a) for c, a in corners], 9, 1, 0.008, -0.07, struct)
    for s in (s0 + 0.3, hp - 2.2, hp, hp + 2.2, s1 - 0.3):
        corners = [(s - 0.06, a0 + 0.5), (s + 0.06, a0 + 0.5),
                   (s + 0.06, a0 + 3.0), (s - 0.06, a0 + 3.0)]
        sf.surface_patch(p, surf, [(c, side * a) for c, a in corners], 1, 1, 0.008, -0.06, struct)
    for s in (s0 + ACTUATORS[0], s1 - ACTUATORS[1]):
        corners = [(s - 0.065, am - 1.0), (s + 0.065, am - 1.0),
                   (s + 0.065, am + 1.0), (s - 0.065, am + 1.0)]
        sf.surface_patch(p, surf, [(c, side * a) for c, a in corners], 1, 1, -0.035, -0.105, struct)
