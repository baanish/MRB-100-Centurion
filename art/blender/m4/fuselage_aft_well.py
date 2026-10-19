"""fuselage_aft's AWACS well: the blockout's slot (build_centurion.cut_well_slot, the box bl.well_box()) cut through
the crown of a detailed hull part, its opening rolled over a lip into walls and a floor in aircraft_structure. A helper
of fuselage_aft.py; it declares no GROUP, so detail_centurion's group discovery passes over it."""

import math

import bmesh
from mathutils import Vector

from .surface import N, seam

LIP_DEG = (30.0, 60.0, 90.0)  # the lip's quarter round from the skin onto the wall, in these steps


def cut_well(bl, p, g, footprint, skin, struct, lip_cls):
    """Cut the slot through the hull Grid g of part p wherever its rings lie over the footprint: the stations (s0, s1)
    of the spine cover's ends, whose sides the hull's columns 1 and N - 1 follow there, with rings at s0 and s1 where
    they fall inside the part. The footprint is the slot grown by the lid's overlap: from each rim vertex the skin
    rolls over a quarter round, as deep as it is wide, onto the slot's wall, and the wall runs straight down to the
    slot's floor. Where the slot runs on through the part's joint, the cap there is notched to the same section, so it
    meets the neighbouring part's notch. The lip is skin (lip_cls); the walls, floor and caps are struct.
    Returns the lip's mirrored faces by hull row: {row: [(-X face, its +X twin)]}."""
    lo, hi = bl.well_box()
    slot = (lo.y + bl.Y0, hi.y + bl.Y0)
    s0, s1 = footprint
    st, bm = g.stations, p.bm
    rows = [r for r in range(len(st) - 1) if st[r] >= s0 - 1e-6 and st[r + 1] <= s1 + 1e-6]
    if not rows:
        return {}
    r0, r1 = rows[0], rows[-1] + 1
    open0, open1 = st[r0] > s0 + 1e-6, st[r1] < s1 - 1e-6  # the slot runs on through the part's joint there
    if (open0 and r0 != 0) or (open1 and r1 != len(st) - 1) or not (open0 or open1):
        raise SystemExit(f"{p.name}: the well's ends need rings at {s0:.3f} and {s1:.3f}, inside one part at most one")

    gone = {g.F.pop((r, k)) for r in range(r0, r1) for k in (N - 1, 0)}
    for r in [r for r, o in ((r0, open0), (r1, open1)) if o]:  # the flat cap across the joint
        ring = set(g.V[r])
        gone |= {f for v in g.V[r] for f in v.link_faces if all(u in ring for u in f.verts)}
    bmesh.ops.delete(bm, geom=list(gone), context="FACES")  # with the crown vertices only they used

    def foot(r, k):
        """The wall's foot under rim vertex (r, k): on the slot's side (the crown's on its centreline), at the slot's
        end on a closed end's ring."""
        s = slot[0] if r == r0 and not open0 else slot[1] if r == r1 and not open1 else st[r]
        return Vector(({1: hi.x, N - 1: lo.x, 0: 0.0}[k], bl.st(s), lo.z))

    right, left = [(r, 1) for r in range(r0, r1 + 1)], [(r, N - 1) for r in range(r0, r1 + 1)]
    if open0 and open1:
        paths = [right, left]
    elif open1:
        paths = [right[::-1] + [(r0, 0)] + left]  # round the front end across the crown
    else:
        paths = [right + [(r1, 0)] + left[::-1]]
    prof = {}
    for r, k in (key for path in paths for key in path):
        v, f = g.V[r][k], foot(r, k)
        h = Vector((f.x - v.co.x, f.y - v.co.y, 0.0))
        d = max(abs(h.x), abs(h.y))
        pts = [v.co + h * math.sin(math.radians(a)) - Vector((0, 0, d * (1 - math.cos(math.radians(a))))) for a in LIP_DEG]
        prof[r, k] = [v] + [bm.verts.new(q) for q in pts] + [bm.verts.new(f)]
        if k == 0:  # the crown splits the lip's halves, which may keep their own islands
            for a, b in zip(prof[r, k], prof[r, k][1:]):
                seam(bm, a, b)

    lips, structure = [], []
    for path in paths:
        for a, b in zip(path, path[1:]):
            A, B = prof[a], prof[b]
            for j in range(len(LIP_DEG) + 1):  # the lip's steps, then the wall
                (lips if j < len(LIP_DEG) else structure).append(bm.faces.new((A[j], B[j], B[j + 1], A[j + 1])))
    for r in range(r0, r1):
        q = [prof[r, 1][-1], prof[r + 1, 1][-1], prof[r + 1, N - 1][-1], prof[r, N - 1][-1]]
        end = next((e for e in (r, r + 1) if (e, 0) in prof), None)
        if end is None:
            structure.append(bm.faces.new(q))
            continue
        c = prof[end, 0][-1]  # the crown's foot lies on the floor's end edge: fan the row from it
        fan = q if end == r else q[2:] + q[:2]
        structure += [bm.faces.new((c, fan[i], fan[i + 1])) for i in range(3)]
    for r in [r for r, o in ((r0, open0), (r1, open1)) if o]:
        poly = [g.V[r][k] for k in range(1, N)] + prof[r, N - 1][1:] + prof[r, 1][1:][::-1]
        cap = bm.faces.new(poly)
        cap.normal_update()  # the triangulation projects the notched outline along it
        structure += bmesh.ops.triangulate(bm, faces=[cap])["faces"]
        for a, b in zip(poly, poly[1:] + poly[:1]):
            seam(bm, a, b)
    p.tag(lips, skin, lip_cls)
    p.tag(structure, struct)

    plus = [(f.calc_center_median(), f) for f in lips]
    pairs = {}
    for f in lips:
        c = f.calc_center_median()
        if c.x >= 0:
            continue
        m = Vector((-c.x, c.y, c.z))
        dist, twin = min(((q - m).length, t) for q, t in plus)
        if dist > 1e-5:
            raise SystemExit(f"{p.name}: a lip face at {tuple(round(x, 3) for x in c)} has no +X twin")
        row = max(r for r in range(len(st) - 1) if st[r] <= c.y + bl.Y0 + 1e-6)
        pairs.setdefault(row, []).append((f, twin))
    return pairs
