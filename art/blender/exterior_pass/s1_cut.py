"""Pass stage 1, cut: paint groups tagged, every seam bisected on its cut plane, flap and aileron coves, spoiler wells.
UNTESTED (written while Blender was unavailable).

1. Paint groups. The bake paints each texel by the detail group (m4/*.py) that built its face. The parts blend mixes
   groups inside one part (Centurion holds fuselage_M and the wing root's centre strip), so each face is tagged with an
   int attribute `paint_group` from the nearest face of the detail blend (.cache/art/m4), loaded beside it.
2. Seams. damage_parts.py gave each part whole faces by centroid, so a part's skin ends in a sawtooth around its cut.
   Here every face straddling a cut plane, on either part of the pair, is bisected on the plane and each piece goes to
   the part on its side, so both sides end on the plane itself. The planes are damage_tree.py's (CUTS below).
3. Coves. Each flap's and aileron's nose swings into the wing (sweep_surfaces.py: up to 0.24 m). The host's faces the
   nose crosses over its travel are removed and a cove wall is built round the hinge line at the nose's radius + 5 mm.
4. Spoiler wells, both sides (spoiler_well.py, generated from the round 3 sample).

blender --background --python s1_cut.py -- [--force]"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

ctx = P.begin("s1_cut", __file__)
DUP0 = {n: P.duplicate_faces(o) for n, o in P.part_objects()[0].items()}
FOLD0 = P.folded_skin_edges(welded=True)
BACK0 = P.folded_skin_edges(welded=True, back=True)
import damage_tree as T  # noqa: E402

report = {}

# ---- 1. paint groups ----
import detail_centurion as DC  # noqa: E402  (imports the m4 group modules; builds nothing)

group_names = list(DC.GROUPS)
# Each face's group is the one damage_parts cut it from (face attribute source_group): nearest-face tagging from a
# detail blend handed faces lying within 2 cm of another group's detail faces to that group's painter (three aft flank
# faces went to the sponson's and clipped the serial to "043"), and depended on which detail blend was at hand.
objs, _ = P.part_objects()
groups_of_cls = {}  # paint class -> the groups whose faces carry it in the parts as cut
for o in objs.values():
    me = o.data
    sg, ca = me.attributes.get("source_group"), me.attributes.get("cls")
    if sg is None or ca is None or ca.domain != "FACE":
        continue
    g_, c_ = [0] * len(me.polygons), [0] * len(me.polygons)
    sg.data.foreach_get("value", g_)
    ca.data.foreach_get("value", c_)
    for c, g in zip(c_, g_):
        if g:
            groups_of_cls.setdefault(c, set()).add(g)
# a face whose group does not paint its class goes to a group that does (a visual object cut with no group, a class
# shared across a seam). Classes 1 to 5 are surface.py's, shared by every group's painter.
SHARED_CLS = range(1, 6)


def painting_group(c, g):
    gs = groups_of_cls.get(c)
    return g if not c or c in SHARED_CLS or not gs or g in gs else min(gs)
untagged, far = 0, []
for o in objs.values():
    me = o.data
    attr = me.attributes.get("paint_group") or me.attributes.new("paint_group", "INT", "FACE")
    sg = me.attributes.get("source_group")
    if sg is None or sg.domain != "FACE":
        raise SystemExit(f"s1_cut: {o.name} has no source_group: rebuild the damage parts (BUILD.md step 4)")
    vals = [0] * len(me.polygons)
    sg.data.foreach_get("value", vals)
    untagged += vals.count(0)
    far += [o.name] * vals.count(0)
    if 0 in vals and any(vals):  # faces cut from no group's object take the nearest tagged face's group in their part
        from mathutils.kdtree import KDTree
        tagged = [(p.center.copy(), v) for p, v in zip(me.polygons, vals) if v]
        kd = KDTree(len(tagged))
        for i, (c, _) in enumerate(tagged):
            kd.insert(c, i)
        kd.balance()
        vals = [v or tagged[kd.find(p.center)[1]][1] for p, v in zip(me.polygons, vals)]
    pc = me.attributes.get("cls")
    if pc is not None and pc.domain == "FACE":
        cl = [0] * len(me.polygons)
        pc.data.foreach_get("value", cl)
        vals = [painting_group(c, v) for c, v in zip(cl, vals)]
    attr.data.foreach_set("value", vals)
from collections import Counter  # noqa: E402

# gate: every skin face's (class, group) pair is one the detail blend has, so its group's painter knows its class
unknown = Counter()
for o in P.part_objects()[0].values():  # afresh: the detail objects loaded above are gone
    me = o.data
    pc, pg = me.attributes.get("cls"), me.attributes.get("paint_group")
    if pc is None or pg is None or pc.domain != "FACE":
        continue
    sk = {i for i, m in enumerate(me.materials) if m and m.name == P.SKIN}
    cl, gr = [0] * len(me.polygons), [0] * len(me.polygons)
    pc.data.foreach_get("value", cl)
    pg.data.foreach_get("value", gr)
    for p in me.polygons:
        if p.material_index in sk and painting_group(cl[p.index], gr[p.index]) != gr[p.index]:
            unknown[(o.name, cl[p.index], gr[p.index])] += 1
if unknown:
    raise SystemExit(f"s1_cut: skin faces whose paint group does not paint their class: {dict(unknown.most_common(10))}")
report["paint_groups"] = {"groups": group_names, "faces_untagged": untagged,
                          "untagged_by_object": dict(Counter(far).most_common(12))}
P.trace("paint_groups")

# ---- 2. seams: (part a, part b, plane point, plane normal) in Blender world metres ----
def st(v):
    return Vector((0, v - T.ST0, 0)), Vector((0, 1, 0))


def zp(v):
    return Vector((0, 0, v)), Vector((0, 0, 1))


def xp(v):
    return Vector((v, 0, 0)), Vector((1, 0, 0))


CUTS = [("radome", "cockpit", *st(3.625)), ("cockpit", "fuselage_F", *st(T.CUT_COCKPIT)), ("cockpit", "bay_F", *st(T.CUT_COCKPIT)),
        ("fuselage_F", "Centurion", *st(T.CUT_FWD)), ("bay_F", "Centurion", *st(T.CUT_FWD)), ("bay_F", "fuselage_F", *zp(T.BAY_ROOF)),
        ("Centurion", "fuselage_R", *st(T.CUT_MID)), ("Centurion", "bay_A", *st(T.CUT_MID)), ("bay_A", "fuselage_R", *zp(T.BAY_ROOF)),
        ("fuselage_R", "tailcone", *st(T.CUT_AFT)), ("bay_A", "tailcone", *st(T.CUT_AFT)), ("tailcone", "tail_end", *st(T.CUT_TAIL))]
for s, sx in (("L", 1), ("R", -1)):
    n = "1" if s == "L" else "2"
    CUTS += [("Centurion", f"wing_root_{s}", *xp(sx * T.BODY_HALF)), (f"wing_root_{s}", f"wing_outer_{s}", *xp(sx * T.CUT_WING)),
             ("tailcone", f"vtail_{s}", *xp(sx * T.VTAIL_ROOT)), (f"nacelle_{n}", f"nozzle_{n}", *st(T.NOZZLE_SEAM)),
             (f"nacelle_{n}", f"pylon_{n}", *zp(T.PYLON[0])), (f"pylon_{n}", f"wing_root_{s}", *zp(T.PYLON[1])),
             ("Centurion", f"strut_inner_{s}", *xp(sx * T.STRUT_IN[0])), (f"strut_inner_{s}", f"nacelle_{n}", *xp(sx * T.STRUT_IN[1])),
             (f"nacelle_{n}", f"strut_outer_{s}", *xp(sx * T.STRUT_OUT[0])), (f"strut_outer_{s}", f"wing_outer_{s}", *zp(T.STRUT_OUT[1])),
             ("Centurion", f"sponson_{s}", *xp(sx * T.BODY_HALF))]


SEAM_TOL = 1e-4  # m: the seam's two sides share their vertices before the split, so they match to float precision; 0.1 mm
# leaves room for the world-to-local round trip (the diagnosis's fixed-seam limit is 1 mm, the Darkreach's 0.03 mm)


def cut_exterior(cuts):
    """The cuts on one continuous exterior: every part in a cut joins one world-space mesh, the
    skin welded where parts meet, so each cut plane splits the shared skin once and both sides keep the same seam
    vertices; the faces are then handed to the part on their side and the mesh split back into the parts. (The round 1
    pass cut each part in its own box and grafted the moved faces: seams 7.73 to 68.3 mm apart.)"""
    names = sorted({x for a, b, _, _ in cuts for x in (a, b)})
    objs = [bpy.data.objects[n] for n in names]
    bm = bmesh.new()
    own = bm.faces.layers.int.new("pass_owner")
    mats = []
    for k, o in enumerate(objs):
        local = [m.name if m else "" for m in o.data.materials]
        for n in local:
            if n not in mats:
                mats.append(n)
        tmp = o.data.copy()
        tmp.transform(o.matrix_world)
        first = len(bm.faces)
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        bm.faces.ensure_lookup_table()
        for fc in bm.faces[first:]:
            fc[own] = k
            fc.material_index = mats.index(local[fc.material_index]) if local else 0
    skin = mats.index(P.SKIN)
    sv = list(dict.fromkeys(v for fc in bm.faces if fc.material_index == skin for v in fc.verts))
    welded = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=sv, dist=1e-5)
    welded -= len(bm.verts)
    bm.verts.index_update()
    # coincident faces of neighbouring parts now share every vertex: one of each same-winding pair goes (sol2 2: 1,138
    # same-winding duplicates by stage 2), the inward copies (opposite winding) stay
    bm.normal_update()
    seen_, dups_ = {}, []
    for fc in bm.faces:
        key = frozenset(v.index for v in fc.verts)
        if any(o_.normal.dot(fc.normal) > 0.99 for o_ in seen_.get(key, [])):
            dups_.append(fc)
        else:
            seen_.setdefault(key, []).append(fc)
    bmesh.ops.delete(bm, geom=dups_, context="FACES_ONLY")
    moved = {}
    for a, b, co, no in cuts:
        ka, kb = names.index(a), names.index(b)
        side, box = {}, {}
        for k in (ka, kb):
            fs = [fc for fc in bm.faces if fc[own] == k]
            side[k] = 1 if sum(1 for fc in fs if (fc.calc_center_median() - co).dot(no) > 0) > len(fs) / 2 else -1
            cs = [v.co for fc in fs for v in fc.verts]
            box[k] = (Vector([min(c[i] for c in cs) for i in range(3)]) - Vector((0.3,) * 3), Vector([max(c[i] for c in cs) for i in range(3)]) + Vector((0.3,) * 3))
        if side[ka] == side[kb]:
            moved[f"{a}|{b}"] = "skipped: both parts lie on one side of the plane"
            continue
        lo = Vector([max(box[ka][0][i], box[kb][0][i]) for i in range(3)])  # where the two parts overlap
        hi = Vector([min(box[ka][1][i], box[kb][1][i]) for i in range(3)])
        inbox = lambda c: all(lo[i] <= c[i] <= hi[i] for i in range(3))  # noqa: E731
        near = [fc for fc in bm.faces if fc[own] in (ka, kb) and inbox(fc.calc_center_median())
                and min((v.co - co).dot(no) for v in fc.verts) < -1e-5 < 1e-5 < max((v.co - co).dot(no) for v in fc.verts)]
        if near:
            bmesh.ops.bisect_plane(bm, geom=near + list(dict.fromkeys(e for fc in near for e in fc.edges)) + list(dict.fromkeys(v for fc in near for v in fc.verts)),
                                   plane_co=co, plane_no=no)
        n = 0
        for fc in bm.faces:
            if fc[own] not in (ka, kb):
                continue
            c = fc.calc_center_median()
            d = (c - co).dot(no)
            if not inbox(c) or abs(d) > 0.6:
                continue
            want = ka if (d > 0) == (side[ka] > 0) else kb
            if fc[own] != want:
                fc[own] = want
                n += 1
        moved[f"{a}|{b}"] = {"moved_faces": n, "split_faces": len(near)}
    degenerate = len(bm.faces)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
    degenerate -= len(bm.faces)
    # the seams: skin edges whose two faces now belong to different parts, their ends in world space, for seam_gate
    SEAMS.clear()
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) == 2 and lf[0][own] != lf[1][own] and lf[0].material_index == skin and lf[1].material_index == skin:
            pair = tuple(sorted((names[lf[0][own]], names[lf[1][own]])))
            SEAMS.setdefault(pair, []).extend(v.co.copy() for v in e.verts)
    for k, o in enumerate(objs):
        sub = bm.copy()
        lay = sub.faces.layers.int["pass_owner"]
        bmesh.ops.delete(sub, geom=[fc for fc in sub.faces if fc[lay] != k], context="FACES")
        local = [m.name if m else "" for m in o.data.materials]
        for fc in sub.faces:
            n = mats[fc.material_index]
            if n not in local:
                local.append(n)
            fc.material_index = local.index(n)
        sub.faces.layers.int.remove(lay)
        sub.transform(o.matrix_world.inverted())
        me = o.data
        old = {m.name: m for m in me.materials if m}
        me.materials.clear()
        for n in local:
            me.materials.append(old.get(n) or bpy.data.materials.get(n) or bpy.data.materials.new(n))
        sub.to_mesh(me)
        sub.free()
    bm.free()
    return {"welded_vertices": welded, "duplicate_faces_removed": len(dups_), "dissolved_degenerate_faces": degenerate, "cuts": moved}


SEAMS = {}


def seam_gate(cuts):
    """Every seam vertex of the welded exterior (an edge between two parts' skin) is a vertex of both parts after the
    split, within SEAM_TOL. Returns the worst miss per part pair in mm, and the pairs over."""
    from mathutils.kdtree import KDTree
    trees = {}
    for name in dict.fromkeys(n for pair in SEAMS for n in pair):
        o = bpy.data.objects[name]
        pts = [o.matrix_world @ v.co for v in o.data.vertices]
        kd = KDTree(len(pts))
        for i, p in enumerate(pts):
            kd.insert(p, i)
        kd.balance()
        trees[name] = kd
    worst = {}
    for (a, b), pts in SEAMS.items():
        worst[f"{a}|{b}"] = round(max(max(trees[a].find(p)[2], trees[b].find(p)[2]) for p in pts) * 1000, 4)
    return worst, {k: v for k, v in worst.items() if v > SEAM_TOL * 1000}

report["seams"] = cut_exterior(CUTS)
report["seam_gap_mm"], bad = seam_gate(CUTS)
print("S1 seams", json.dumps(report["seams"]["cuts"])[:600], "\nS1 seam gaps mm (worst per cut)", report["seam_gap_mm"], flush=True)
if bad:
    raise SystemExit(f"s1_cut: seams apart over {SEAM_TOL * 1000} mm: {bad}")
P.trace("seams")
# ---- 3. coves: the host faces each flap and aileron nose crosses, replaced by a wall round its hinge line ----
TRAVEL = {"flap_": 30, "aileron_": 75}  # flaps down only (the sign that lowers the trailing edge); ailerons both ways
COVE_LOOSE = []
# The lips trimmed to each surface's swept envelope: off. Built and measured (round 3): the flaps' noses, 0.7 m ahead of
# hinges set deep in the wing, rise about 0.35 m over 30 degrees and pass through both lips, so the trim removed about
# 6 m2 of skin a flap and its sealing walls cost 1,100 to 1,500 quads a cove (16,000 triangles in all). So
# cut the lips locally, within the outer END_SHARE of each surface's span at each end, where
# check_travel found all of the ailerons' visible poke-through and two thirds of the flaps'. Built and measured: it cut
# 718 lip faces a flap 1 and left check_travel's visible area where it was (flaps 0.14 to 0.17 m2, ailerons 0.06 to
# 0.08), so it stays off
SWEPT_TRIM, END_SHARE = False, 0.1


def cove(surface, host):
    """The flaps' hinges sit about a quarter chord back (flap_L1's nose reaches 1.0 m ahead of its
    hinge), so the cove is the arc the nose sweeps over its travel, not a half cylinder round the hinge."""
    vis = bpy.data.objects[surface + "_visible"]
    hinge = bpy.data.objects[surface]
    ax = hinge.matrix_world.col[0].xyz.normalized()
    piv = hinge.matrix_world.translation.copy()
    # an aileron's cove follows its geometric lower half, as it always has (the spoiler's well is built against it)
    src = bpy.data.objects.get(surface + "_visible_lower") or vis
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.transform(src.matrix_world)
    rest = [v.co.copy() for v in bm.verts]
    tris = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    host_o = bpy.data.objects[host]
    hb = bmesh.new()
    hb.from_mesh(host_o.data)
    hb.transform(host_o.matrix_world)
    hb.faces.ensure_lookup_table()
    ht = BVHTree.FromBMesh(hb)
    rest_pairs = set(BVHTree.FromPolygons(rest, tris).overlap(ht))
    fwd = ax.cross(Vector((0, 0, 1))).normalized()
    fwd = fwd if fwd.y < 0 else -fwd  # toward the nose of the aircraft (Blender -Y)
    e2 = ax.cross(fwd)  # with fwd, a plane basis in which a +deg turn about ax adds deg to the angle
    radial = lambda p: ((p - piv) - ax * (p - piv).dot(ax)).length  # noqa: E731
    angle = lambda p: math.degrees(math.atan2((p - piv).dot(e2), (p - piv).dot(fwd)))  # noqa: E731
    turn = lambda deg: Matrix.Translation(piv) @ Matrix.Rotation(math.radians(deg), 4, ax) @ Matrix.Translation(-piv)  # noqa: E731
    nose = [p for p in rest if (p - piv).dot(fwd) > 0.0]
    nose_r = max((radial(p) for p in nose), default=0.0)
    travel = next(v for k, v in TRAVEL.items() if surface.startswith(k))
    if surface.startswith("flap_"):
        te = min(rest, key=lambda p: (p - piv).dot(fwd))
        sign = 1 if (turn(10) @ te).z < te.z else -1
        degs = range(0, sign * (travel + 1), sign * 2)
    else:
        degs = range(-travel, travel + 1, 2)
    hit, beyond, upper, hit_degs = set(), set(), set(), [0]
    for deg in degs:
        pts = [turn(deg) @ p for p in rest]
        for i, j in BVHTree.FromPolygons(pts, tris).overlap(ht):
            if (i, j) in rest_pairs:
                continue
            f = hb.faces[j]
            if radial(f.calc_center_median()) >= nose_r + 0.03:
                beyond.add(j)  # the trailing edge entering a stage at the clamshell's 75 degrees: not a cove's to clear
            elif f.normal.z > 0.5 and f.calc_center_median().z > piv.z:
                upper.add(j)  # the nose would come through the upper skin: kept, reported (a cove cannot hide it)
            else:
                hit.add(j)
                hit_degs.append(deg)
    # the cove's prism: the arc the nose's outer edge sweeps over the degrees it crossed the host, at nose_r + 5 mm,
    # between the radii at its two ends and the surface's span. The host skin is cut on the prism's own planes and only
    # what lies inside goes (round 1 removed whole crossed faces and left the wall loose)
    outer = [angle(p) for p in nose if radial(p) > 0.7 * nose_r] or [0.0]
    a0, a1 = min(outer) + min(hit_degs), max(outer) + max(hit_degs)
    a1 = min(a1, a0 + 180)
    ss = [(p - piv).dot(ax) for p in rest]
    s0, s1 = min(ss), max(ss)
    r = nose_r + 0.005
    n = max(2, math.ceil((a1 - a0) / 10))
    dirs = [fwd * math.cos(math.radians(a0 + (a1 - a0) * k / n)) + e2 * math.sin(math.radians(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]
    arc = [piv + d * r for d in dirs]
    planes = [(arc[k], (arc[k + 1] - arc[k]).cross(ax).normalized()) for k in range(n)]  # the chords
    planes += [(piv, dirs[0].cross(ax).normalized()), (piv, dirs[-1].cross(ax).normalized())]  # the two end radii
    planes += [(piv + ax * s0, ax), (piv + ax * s1, ax)]  # the span's ends
    half = math.radians((a1 - a0) / n / 2)

    def region(fc):
        c = fc.calc_center_median()
        s = (c - piv).dot(ax)
        return s0 - 0.05 < s < s1 + 0.05 and radial(c) < r + 0.2

    old_b = [(e.verts[0].co.copy(), e.verts[1].co.copy()) for e in hb.edges if e.is_boundary and e.link_faces and region(e.link_faces[0])]

    def on_old_border(m):
        for p0, p1 in old_b:
            d = p1 - p0
            t_ = max(0.0, min(1.0, (m - p0).dot(d) / max(d.length_squared, 1e-12)))
            if (p0 + d * t_ - m).length < 0.0005:
                return True
        return False
    for co, no in planes:
        fs = [fc for fc in hb.faces if region(fc)]
        if fs:
            bmesh.ops.bisect_plane(hb, geom=fs + list(dict.fromkeys(e for fc in fs for e in fc.edges)) + list(dict.fromkeys(v for fc in fs for v in fc.verts)), plane_co=co, plane_no=no)

    mid = piv + ax * ((s0 + s1) / 2) + (dirs[0] + dirs[len(dirs) // 2] + dirs[-1]).normalized() * r * 0.3  # a point inside
    sides = [(co, no, 1 if (mid - co).dot(no) > 0 else -1) for co, no in planes]

    def inside(c):
        """On the inner side of every cove plane: exact, since after the bisects no face crosses one."""
        return all((c - co).dot(no) * sg > 0 for co, no, sg in sides)

    skin_i = P.slot(host_o, P.SKIN)
    # the lower skin stays, as the upper does: what crosses it is the flap's track fairing, which hangs below the wing at
    # rest and swings up through it as the flap goes down (as on the shipped model). Removing the skin it crosses opened
    # a black slot a metre wide under the inner wing at rest (check_luma, bottom view). The crossed pieces are counted
    hb.normal_update()
    cand = [fc for fc in hb.faces if fc.material_index == skin_i and fc.normal.z < -0.5 and inside(fc.calc_center_median())]
    crossed = set()
    if cand:
        cv, cp = [], []
        for fc in cand:
            cp.append(list(range(len(cv), len(cv) + len(fc.verts))))
            cv += [v.co.copy() for v in fc.verts]
        ct = BVHTree.FromPolygons(cv, cp)
        at_rest = set(ct.overlap(BVHTree.FromPolygons(rest, tris)))
        for deg in degs:
            if deg:
                crossed |= {cand[i] for i, j in ct.overlap(BVHTree.FromPolygons([turn(deg) @ p for p in rest], tris)) if (i, j) not in at_rest}

    def kept_lower(fc):
        return fc.material_index == skin_i and fc.normal.z < -0.5

    gone = [fc for fc in hb.faces if inside(fc.calc_center_median()) and not (fc.normal.z > 0.5 and fc.calc_center_median().z > piv.z) and not kept_lower(fc)]
    bmesh.ops.delete(hb, geom=gone, context="FACES")
    hit = gone
    # the wall: the chords, the two end radii and the two span ends, one sheet facing into the cove (the only side
    # anything outside the wing can see), on the cut planes themselves so the cut skin's edges lie on it
    wall = []
    # the end caps and the two radial walls: their fan (or rectangle) clipped to the host wing's own section in that
    # plane, so they cover the wing's inside exactly (fans from the hinge axis stood out of the thin inner wing ahead of
    # its leading edge, found by s5's silhouette gate)
    import sections as SEC

    def clip(subject, clipper):
        """Sutherland-Hodgman: a polygon (any shape) clipped by a convex counter-clockwise one, both 2D."""
        out = subject
        for k in range(len(clipper)):
            a_, b_ = clipper[k], clipper[(k + 1) % len(clipper)]
            side = lambda p: (b_[0] - a_[0]) * (p[1] - a_[1]) - (b_[1] - a_[1]) * (p[0] - a_[0])  # noqa: E731
            inp, out = out, []
            for i in range(len(inp)):
                p, q = inp[i], inp[(i + 1) % len(inp)]
                sp, sq = side(p), side(q)
                if sp >= 0:
                    out.append(p)
                if (sp >= 0) != (sq >= 0) and sp != sq:
                    t_ = sp / (sp - sq)
                    out.append((p[0] + (q[0] - p[0]) * t_, p[1] + (q[1] - p[1]) * t_))
            if not out:
                break
        return out

    def ccw(poly):
        a2 = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
        return poly if a2 > 0 else poly[::-1]

    def face_in_plane(origin, u_ax, v_ax, normal, fan2d):
        for lp in SEC.section_loops(host_o, origin, normal):
            if len(lp) < 3:
                continue
            sub = [((p - origin).dot(u_ax), (p - origin).dot(v_ax)) for p in lp]
            res = clip(sub, ccw(fan2d))
            if len(res) >= 3:
                vs_ = [hb.verts.new(origin + u_ax * x + v_ax * y) for x, y in res]
                try:
                    wall.append(hb.faces.new(vs_))
                except ValueError:
                    pass

    sector = [(0.0, 0.0)] + [(r * math.cos(math.radians(a0 + (a1 - a0) * k / n)), r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]
    for k in range(n):  # the chords, each clipped to the wing's section in its own plane (unclipped, they rose out of the thin inner wing)
        cdir = (arc[k + 1] - arc[k]).normalized()
        face_in_plane(arc[k], ax, cdir, planes[k][1], [(s0, 0.0), (s1, 0.0), (s1, (arc[k + 1] - arc[k]).length), (s0, (arc[k + 1] - arc[k]).length)])
    for s_ in (s0, s1):
        face_in_plane(piv + ax * s_, fwd, e2, ax, sector)
    for d_ in (dirs[0], dirs[-1]):
        face_in_plane(piv, ax, d_, d_.cross(ax).normalized(), [(s0, 0.0), (s1, 0.0), (s1, r), (s0, r)])
    hb.normal_update()
    centre = piv + ax * ((s0 + s1) / 2) + (dirs[0] + dirs[-1]).normalized() * r * 0.5
    for fc in wall:
        if fc.normal.dot(centre - fc.calc_center_median()) < 0:
            fc.normal_flip()
    # ---- the kept lips trimmed to the surface's swept envelope over its game travel (sweep.py): the skin the surface
    # passes through goes, piece by piece at about TRIM_EDGE, and each opened edge gets a lining wall TRIM_WALL deep, so
    # the cut stays sealed. check_travel counted 3,000 to 32,000 pairs cutting the kept lips over full travel ----
    import sweep as SW
    entries_ = [e for e in SW.surfaces() if e[0].name == surface] if SWEPT_TRIM else []
    trees_ = [t for h_, m_, d_, _ in entries_ for t in SW.envelope(h_, m_, d_)]
    rest_tree_ = BVHTree.FromPolygons(*SW.world([m for _, ms, _, _ in entries_ for m in ms])) if entries_ else None
    TRIM_EDGE, TRIM_WALL = 0.12, 0.03  # 6 cm cost 3,500 wall quads a cove (43,000 triangles in all, past the budget)
    wall_set = set(wall)

    spo_ = bpy.data.objects.get(f"spoiler_{surface[-1]}_visible") if surface.startswith("aileron_") else None
    if spo_ is not None:  # the spoiler's footprint is left whole for its well (built after the coves on this skin)
        sp_pts = [spo_.matrix_world @ Vector(c_) for c_ in spo_.bound_box]
        sp_lo = Vector([min(p[i] for p in sp_pts) - 0.05 for i in range(3)])
        sp_hi = Vector([max(p[i] for p in sp_pts) + 0.05 for i in range(3)])

    def near_sweep(fc):
        c = fc.calc_center_median()
        s = (c - piv).dot(ax)
        if spo_ is not None and all(sp_lo[i] <= c[i] <= sp_hi[i] for i in range(3)):
            return False
        end_ = END_SHARE * (s1 - s0)
        return (fc.material_index == skin_i and fc not in wall_set and s0 - 0.1 < s < s1 + 0.1 and radial(c) < r + 0.15
                and (s < s0 + end_ or s > s1 - end_))

    def crossed_by_sweep():
        """The lip faces some pose of the surface crosses (only these are split: the whole lip at TRIM_EDGE would cost
        tens of thousands of triangles)."""
        fs = [fc for fc in hb.faces if near_sweep(fc)]
        if not fs:
            return []
        vs, ps = [], []
        for fc in fs:
            ps.append(list(range(len(vs), len(vs) + len(fc.verts))))
            vs += [v.co.copy() for v in fc.verts]
        ft = BVHTree.FromPolygons(vs, ps)
        at_rest_ = set(ft.overlap(rest_tree_))  # flush at rest is contact, not a cut (as check_travel counts)
        hit = set()
        for t in trees_:
            hit |= {i for i, j in ft.overlap(t) if (i, j) not in at_rest_}
        return [fs[i] for i in hit]

    edge_key = lambda e: frozenset((tuple(round(c, 5) for c in e.verts[0].co), tuple(round(c, 5) for c in e.verts[1].co)))  # noqa: E731
    open_before = {edge_key(e) for e in hb.edges if e.is_boundary}
    for _ in range(8 if SWEPT_TRIM else 0):  # subdivide the crossed lip faces until no edge of theirs is longer than TRIM_EDGE
        crossed_now = crossed_by_sweep()
        long_ = list(dict.fromkeys(e for fc in crossed_now for e in fc.edges if e.calc_length() > TRIM_EDGE))
        if not long_:
            break
        bmesh.ops.subdivide_edges(hb, edges=long_, cuts=1, use_grid_fill=True)
        bmesh.ops.triangulate(hb, faces=[fc for fc in hb.faces if near_sweep(fc) and len(fc.verts) > 3])
    hb.normal_update()  # (no dissolve here: collapsing the fresh triangles' short edges folded skin over skin)
    flat_ = [fc for fc in hb.faces if near_sweep(fc) and (fc.calc_area() < 1e-8 or fc.normal.length < 0.5)]  # no area or no normal (a bow-tie)
    if flat_:
        bmesh.ops.delete(hb, geom=flat_, context="FACES")
    hb.normal_update()
    cut_ = crossed_by_sweep() if SWEPT_TRIM else []  # every lip face the surface crosses goes (a slot at most TRIM_EDGE wider)
    bmesh.ops.delete(hb, geom=cut_, context="FACES")
    hb.normal_update()
    # skin folded over skin in the trimmed region (the split triangles can lie back over a neighbour): the smaller of each
    # same-facing pair on one edge, on the same side of it, goes (stage 1's fold gate counted 29 and 14 on the outer wings)
    fold_ = set()
    for e in dict.fromkeys(e for fc in hb.faces if near_sweep(fc) for e in fc.edges):
        fs_ = [f for f in e.link_faces if f.material_index == skin_i and f.normal.length > 0.5]
        if len(fs_) < 2:
            continue
        a_, b_ = e.verts[0].co, e.verts[1].co
        d_ = (b_ - a_).normalized()
        side_ = [((f.calc_center_median() - a_) - d_ * (f.calc_center_median() - a_).dot(d_)).normalized() for f in fs_]
        for i in range(len(fs_)):
            for j in range(i + 1, len(fs_)):
                if side_[i].dot(side_[j]) > 0.9 and fs_[i].normal.dot(fs_[j].normal) > 0.98:
                    fold_.add(min(fs_[i], fs_[j], key=lambda f: f.calc_area()))
    if fold_:
        bmesh.ops.delete(hb, geom=list(fold_), context="FACES")
        hb.normal_update()
    trim_walls = 0
    for e in [e for e in hb.edges if e.is_boundary and edge_key(e) not in open_before]:  # every edge the trim opened
        if e.link_faces and e.link_faces[0].material_index == skin_i and e.link_faces[0].normal.length > 0.5:
            n_ = e.link_faces[0].normal
            a_, b_ = e.verts
            q = [a_, b_, hb.verts.new(b_.co - n_ * TRIM_WALL), hb.verts.new(a_.co - n_ * TRIM_WALL)]
            try:
                wall.append(hb.faces.new(q))
                trim_walls += 1
            except ValueError:
                pass
    hb.normal_update()
    # gate: every skin edge the cut left open in the cove's reach lies on the wall
    hb.verts.index_update()
    wt = BVHTree.FromPolygons([v.co.copy() for v in hb.verts], [[v.index for v in fc.verts] for fc in wall])
    skin_i = P.slot(host_o, P.SKIN)
    loose = lips = lower_lips = 0

    def inside_reach(m):
        return all((m - co).dot(no) * sg > -0.005 for co, no, sg in sides)
    for e in hb.edges:
        if e.is_boundary and e.link_faces and e.link_faces[0].material_index == skin_i and region(e.link_faces[0]):
            m = (e.verts[0].co + e.verts[1].co) / 2
            lf = e.link_faces[0]
            if lf.normal.z > 0.5 and lf.calc_center_median().z > piv.z:
                lips += 1  # the upper skin the cove keeps over the nose, ending at the removed interior: its lip
                continue
            if kept_lower(lf) and inside_reach(m):
                lower_lips += 1  # the lower skin the cove keeps, ending at the removed interior (the spar web it met): its lip
                continue
            if abs(lf.normal.dot(ax)) > 0.9:
                continue  # the host's own end plate at the surface's bay end, parallel to the cove's end cap: it closes the cove
            if on_old_border(m):
                continue  # a border the host had before the cut (its trailing edge against the surface)
            if edge_key(e) in open_before:
                continue  # open before the swept trim, and accounted for then (a lip the trim's retriangulation moved below the hinge)
            lc = lf.calc_center_median()
            if any(abs((lc - co).dot(no)) < 0.001 and lf.normal.dot(no) * sg > 0.99 for co, no, sg in sides):
                continue  # host skin lying on a cove plane and facing into the cove is wall already (its section slice is empty)
            hitd = wt.find_nearest(m)
            if hitd[0] is not None and hitd[3] > 0.005 and radial(m) < r + 0.005 and s0 - 0.003 < (m - piv).dot(ax) < s1 + 0.003:
                loose += 1
                q = (m - piv) - ax * (m - piv).dot(ax)
                if loose <= 4:
                    print("S1 cove loose", surface, "s", round((m - piv).dot(ax), 3), "of", round(s0, 3), round(s1, 3), "radial", round(q.length, 3), "of", round(r, 3), "angle", round(math.degrees(math.atan2(q.dot(e2), q.dot(fwd))), 1), "arc", round(a0, 1), round(a1, 1), "to wall mm", round(hitd[3] * 1000, 1), "len mm", round(e.calc_length() * 1000, 1), "world", tuple(round(c, 3) for c in m), "faces", len(e.link_faces), "face normal", tuple(round(c, 2) for c in e.link_faces[0].normal), flush=True)
    COVE_LOOSE.append((surface, loose))
    li = P.slot(host_o, "pass_lining")
    for f in wall:
        f.material_index = li
    hb.transform(host_o.matrix_world.inverted())
    hb.to_mesh(host_o.data)
    hb.free()
    return {"host_faces_removed": len(hit), "nose_radius_m": round(nose_r, 3), "arc_deg": [round(a0, 1), round(a1, 1)],
            "upper_skin_crossed_kept": len(upper), "lower_skin_pieces_crossed_kept": len(crossed), "crossings_beyond_cove": len(beyond - upper),
            "loose_skin_edges": loose, "upper_skin_lip_edges": lips, "lower_skin_slot_edges": lower_lips,
            "swept_trim_faces": len(cut_), "swept_trim_walls": trim_walls}


# ---- 3a. the control surfaces made to clear the wing (lead, decision 2, 2026-11-23) ----
# Flaps: each nose cut back to an arc about its hinge that stays inside the wing through its travel (the hinge lines
# stay: they belong to the flight model and the animation): the arc's radius is the nearest skin of the host ahead of
# the hinge, less NOSE_CLEAR; the flap's faces past the arc and inside the wing at rest go (its external track fairings
# stay), cut on chord planes tangent to the arc, and the opening is closed by a nose wall.
# Ailerons: the authoring hangs a full copy of the aileron as the clamshell's lower half, so the whole aileron swung 75
# degrees both ways. Here the aileron splits on the chord plane through its hinge into real halves, each closed by its
# own inner face: aileron_X_visible (the upper half) and aileron_X_visible_lower, both under the hinge.
NOSE_CLEAR, NOSE_PLANES = 0.01, 9


def surface_frame(name):
    hinge = bpy.data.objects[name]
    ax = hinge.matrix_world.col[0].xyz.normalized()
    piv = hinge.matrix_world.translation.copy()
    fwd = ax.cross(Vector((0, 0, 1))).normalized()
    fwd = fwd if fwd.y < 0 else -fwd
    return hinge, ax, piv, fwd, ax.cross(fwd)


def copy_attrs_from_neighbours(bm, faces):
    """New faces take the paint class and group of a neighbour, so their group's painter knows them."""
    for lname in ("cls", "paint_group"):
        lay = bm.faces.layers.int.get(lname)
        if lay is None:
            continue
        for f in faces:
            nb = next((g for e in f.edges for g in e.link_faces if g is not f and g[lay]), None)
            if nb is not None:
                f[lay] = nb[lay]


def trim_flap_nose(surface, host):
    hinge, ax, piv, fwd, up = surface_frame(surface)
    vis = bpy.data.objects[surface + "_visible"]
    host_o = bpy.data.objects[host]
    hb_ = bmesh.new()
    hb_.from_mesh(host_o.data)
    hb_.transform(host_o.matrix_world)
    sk_h = P.slot(host_o, P.SKIN)
    radial = lambda p: ((p - piv) - ax * (p - piv).dot(ax)).length  # noqa: E731
    fb = bmesh.new()
    fb.from_mesh(vis.data)
    fb.transform(vis.matrix_world)
    ss = [(v.co - piv).dot(ax) for v in fb.verts]
    s0, s1 = min(ss), max(ss)
    hb_.normal_update()  # the lips the nose would meet: the upper and lower skins ahead of the hinge (faces at the hinge line
    near = [radial(v.co) for f in hb_.faces if f.material_index == sk_h and abs(f.normal.z) > 0.5 for v in f.verts  # read 11 mm)
            if s0 <= (v.co - piv).dot(ax) <= s1 and (v.co - piv).dot(fwd) > 0.05]
    host_tree = BVHTree.FromBMesh(hb_)
    hb_.free()
    if not near:
        fb.free()
        return {"skipped": "no host skin ahead of the hinge"}
    r_keep = min(near) - NOSE_CLEAR
    area0 = sum(f.calc_area() for f in fb.faces)
    tris0 = sum(len(f.verts) - 2 for f in fb.faces)
    dirs = [fwd * math.cos(math.radians(a)) + up * math.sin(math.radians(a)) for a in [-80 + 160 * k / (NOSE_PLANES - 1) for k in range(NOSE_PLANES)]]
    for d in dirs:  # only the nose region is cut (the whole flap cut on nine planes added 700 to 1,200 triangles)
        fs_ = [f for f in fb.faces if (f.calc_center_median() - piv).dot(fwd) > 0 and radial(f.calc_center_median()) > r_keep * 0.6]
        bmesh.ops.bisect_plane(fb, geom=list(dict.fromkeys(v for f in fs_ for v in f.verts)) + list(dict.fromkeys(e for f in fs_ for e in f.edges)) + fs_,
                               plane_co=piv + d * r_keep, plane_no=d)

    def inside_host(c):
        odd = 0
        for d_ in (Vector((0, 0, 1)), Vector((0.31, 0.53, -0.79)).normalized(), Vector((-0.67, 0.41, 0.62)).normalized()):
            n_, q = 0, c.copy()
            for _ in range(32):
                h = host_tree.ray_cast(q, d_, 20.0)
                if h[0] is None:
                    break
                n_ += 1
                q = h[0] + d_ * 1e-5
            odd += n_ % 2
        return odd >= 2
    gone = [f for f in fb.faces if (f.calc_center_median() - piv).dot(fwd) > 0
            and any((f.calc_center_median() - piv).dot(d) > r_keep + 1e-4 for d in dirs) and inside_host(f.calc_center_median())]
    bmesh.ops.delete(fb, geom=gone, context="FACES")
    edges_ = [e for e in fb.edges if e.is_boundary and all((v.co - piv).dot(fwd) > 0 for v in e.verts)]
    filled = P.fill_holes(fb, edges_)
    if filled:  # on the cut-out trim, as the aileron halves' closing faces (on the skin its UVs failed the density gate)
        filled = bmesh.ops.triangulate(fb, faces=filled, quad_method="BEAUTY", ngon_method="BEAUTY")["faces"]
        ti = P.slot(vis, "pass_trim_cut")
        for f in filled:
            f.material_index = ti
    fb.normal_update()
    for f in filled:  # the wall faces away from the hinge
        if f.normal.dot(f.calc_center_median() - piv) < 0:
            f.normal_flip()
    nose = [f for f in fb.faces if f.material_index == 0 and (f.calc_center_median() - piv).dot(fwd) > r_keep * 0.8 and abs(radial(f.calc_center_median()) - r_keep) < 0.02]
    copy_attrs_from_neighbours(fb, nose)
    area1 = sum(f.calc_area() for f in fb.faces)
    fb.transform(vis.matrix_world.inverted())
    fb.to_mesh(vis.data)
    fb.free()
    bm_chk = bmesh.new()
    bm_chk.from_mesh(vis.data)
    ahead_open = sum(1 for e in bm_chk.edges if e.is_boundary and all((vis.matrix_world @ v.co - piv).dot(fwd) > 0 for v in e.verts))
    bm_chk.free()
    return {"keep_radius_m": round(r_keep, 3), "faces_removed": len(gone), "area_removed_m2": round(area0 - area1, 3),
            "nose_wall_faces": len(filled), "open_edges_ahead_of_hinge": ahead_open,
            "triangles_added": sum(len(p.vertices) - 2 for p in vis.data.polygons) - tris0}


AILERON_END_TRIM = 0.14  # each aileron end pulled in along its hinge (the owner's call on the mock-up, 2026-11-23: at 30
# degrees both ends cut into the wing's end walls, which are not square to the hinge line)


def shorten_aileron(surface):
    """The aileron's render mesh scaled along its hinge line about its middle, each end AILERON_END_TRIM in (the
    mock-up's `shorten`; the collider and the hinge stay)."""
    hinge, ax, piv, fwd, up = surface_frame(surface)
    vis = bpy.data.objects[surface + "_visible"]
    vs = [vis.matrix_world @ v.co for v in vis.data.vertices]
    ss = [(p - piv).dot(ax) for p in vs]
    lo, hi = min(ss), max(ss)
    k = (hi - lo - 2 * AILERON_END_TRIM) / (hi - lo)
    mid = (lo + hi) / 2
    inv = vis.matrix_world.inverted()
    for v, p, s in zip(vis.data.vertices, vs, ss):
        v.co = inv @ (p + ax * ((mid + (s - mid) * k) - s))
    return {"length_m": round(hi - lo, 3), "now_m": round((hi - lo) * k, 3), "children_left_as_they_were": len(vis.children)}


SPLIT_MAX = 50.0  # CenturionAuthor's Clamshell maxSplit: each half turns this far from shut, opposite ways
SPLIT_NOSE_DEG = SPLIT_MAX + 1.0  # each half's nose kept this far round from straight ahead of the hinge line
SPLIT_SEAM = 0.002  # the shut halves' seam: their inner faces this far apart (lying on each other they read as crossing)


def split_aileron(surface):
    hinge, ax, piv, fwd, up = surface_frame(surface)
    # World up, whichever way the hinge's x runs: both aileron hinges' frame gives down, so the half the game raises was
    # the geometric lower one and the halves swung through each other at every split (0.97 m deep at full split).
    up = up if up.z > 0 else -up
    vis = bpy.data.objects[surface + "_visible"]
    me = vis.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(vis.matrix_world)
    halves = {}
    for side, keep_up in (("upper", True), ("lower", False)):
        hb2 = bm.copy()
        cut = piv + up * (SPLIT_SEAM / 2 if keep_up else -SPLIT_SEAM / 2)
        bmesh.ops.bisect_plane(hb2, geom=hb2.verts[:] + hb2.edges[:] + hb2.faces[:], plane_co=cut, plane_no=up)
        drop = [f for f in hb2.faces if ((f.calc_center_median() - cut).dot(up) > 0) != keep_up]
        bmesh.ops.delete(hb2, geom=drop, context="FACES")
        edges_ = [e for e in hb2.edges if e.is_boundary and all(abs((v.co - cut).dot(up)) < 1e-4 for v in e.verts)]
        filled = bmesh.ops.holes_fill(hb2, edges=edges_, sides=0)["faces"] if edges_ else []
        if filled:  # the half's own closing inner face, on the trim slot (structure seen when the clamshell opens)
            ti = P.slot(vis, "pass_trim_cut")
            for f in filled:
                f.material_index = ti
            bmesh.ops.triangulate(hb2, faces=filled, quad_method="BEAUTY", ngon_method="BEAUTY")
        hb2.normal_update()
        open_ = sum(1 for e in hb2.edges if e.is_boundary)
        hb2.transform(vis.matrix_world.inverted())
        halves[side] = (hb2, len(filled), open_)
    bm.free()
    halves["upper"][0].to_mesh(me)
    halves["upper"][0].free()
    lower_me = bpy.data.meshes.new(vis.name + "_lower")
    halves["lower"][0].to_mesh(lower_me)
    halves["lower"][0].free()
    for m in me.materials:
        lower_me.materials.append(m)
    lower = bpy.data.objects.new(vis.name + "_lower", lower_me)
    for c in vis.users_collection:
        c.objects.link(lower)
    lower.parent = vis.parent
    lower.matrix_world = vis.matrix_world.copy()
    for k in vis.keys():
        lower[k] = vis[k]
    return {"upper_closing_faces": halves["upper"][1], "lower_closing_faces": halves["lower"][1],
            "upper_open_edges": halves["upper"][2], "lower_open_edges": halves["lower"][2]}


def trim_split_noses(surface):
    """Ahead of the hinge line the two halves turn towards each other, overlapping by the angle between them, up to twice
    SPLIT_MAX: each half keeps its nose only from SPLIT_NOSE_DEG round from straight ahead, so fully open they meet there,
    and shut they leave an empty wedge inside the cove's lips. After the coves, which follow the uncut lower half."""
    hinge, ax, piv, fwd, up = surface_frame(surface)
    up = up if up.z > 0 else -up
    t = math.radians(SPLIT_NOSE_DEG)
    out = {}
    for o, s in ((bpy.data.objects[surface + "_visible"], 1), (bpy.data.objects[surface + "_visible_lower"], -1)):
        nose = up * (s * math.cos(t)) - fwd * math.sin(t)  # kept where (p - piv).dot(nose) >= 0
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        tris0 = sum(len(f.verts) - 2 for f in bm.faces)
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=piv, plane_no=nose)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if (f.calc_center_median() - piv).dot(nose) < 0], context="FACES")
        edges_ = [e for e in bm.edges if e.is_boundary and all(abs((v.co - piv).dot(nose)) < 1e-4 for v in e.verts)]
        filled = bmesh.ops.holes_fill(bm, edges=edges_, sides=0)["faces"] if edges_ else []
        if filled:  # on the trim slot, as the half's inner face
            ti = P.slot(o, "pass_trim_cut")
            for f in filled:
                f.material_index = ti
            filled = bmesh.ops.triangulate(bm, faces=filled, quad_method="BEAUTY", ngon_method="BEAUTY")["faces"]
        bm.normal_update()
        for f in filled:  # facing into the wedge, away from the half
            if f.normal.dot(nose) > 0:
                f.normal_flip()
        out[o.name] = {"nose_faces": len(filled), "open_edges": sum(1 for e in bm.edges if e.is_boundary),
                       "triangles_added": sum(len(f.verts) - 2 for f in bm.faces) - tris0}
        bm.transform(o.matrix_world.inverted())
        bm.to_mesh(o.data)
        bm.free()
    return out


report["surfaces"] = {}
for s in "LR":
    for surf, host in ((f"flap_{s}1", f"wing_root_{s}"), (f"flap_{s}2", f"wing_root_{s}")):
        report["surfaces"][surf] = trim_flap_nose(surf, host)
    report["surfaces"][f"aileron_{s}_end_trim"] = shorten_aileron(f"aileron_{s}")
    report["surfaces"][f"aileron_{s}"] = split_aileron(f"aileron_{s}")
print("S1 surfaces", json.dumps(report["surfaces"]), flush=True)
P.trace("surfaces")

report["coves"] = {}  # the coves first (their trim leaves the spoiler's footprint whole), then the wells
for s in "LR":
    for surf, host in ((f"flap_{s}1", f"wing_root_{s}"), (f"flap_{s}2", f"wing_root_{s}"), (f"aileron_{s}", f"wing_outer_{s}")):
        report["coves"][surf] = cove(surf, host)
if any(n for _, n in COVE_LOOSE):
    raise SystemExit(f"s1_cut: cove cuts left skin edges off the wall: {COVE_LOOSE}")
P.trace("coves")

# ---- 3b. the wing's end wall at each flap's outboard end trimmed to the flap's swept footprint (the owner's call,
# 2026-11-23): the flap's end is not square to its hinge, so going down it passes through the wing's face beside it.
# The host faces within END_WALL_REACH of that end that some pose crosses go (contact at rest is not a cut) ----
END_WALL_REACH = 0.3


def end_wall_trim(surface, host):
    import sweep as SW
    hinge, ax, piv, fwd, up = surface_frame(surface)
    entries = [e for e in SW.surfaces() if e[0].name == surface]
    if not entries:
        return {"skipped": "no sweep entry"}
    _, moving, degs, _ = entries[0]
    pts = [p for m in moving for p in (m.matrix_world @ v.co for v in m.data.vertices)]
    ss = [(p - piv).dot(ax) for p in pts]
    s0, s1 = min(ss), max(ss)
    end_s = max((s0, s1), key=lambda s: abs((piv + ax * s).x))  # the outboard end
    trees = SW.envelope(hinge, moving, degs)
    rest = BVHTree.FromPolygons(*SW.world(moving))
    host_o = bpy.data.objects[host]
    hb = bmesh.new()
    hb.from_mesh(host_o.data)
    hb.transform(host_o.matrix_world)
    hb.faces.ensure_lookup_table()
    near = [f for f in hb.faces if abs((f.calc_center_median() - piv).dot(ax) - end_s) < END_WALL_REACH]
    if not near:
        hb.free()
        return {"faces_removed": 0}
    vs, ps = [], []
    for f in near:
        ps.append(list(range(len(vs), len(vs) + len(f.verts))))
        vs += [v.co.copy() for v in f.verts]
    ft = BVHTree.FromPolygons(vs, ps)
    at_rest = {i for i, _ in ft.overlap(rest)}
    hit = set()
    for t in trees:
        hit |= {i for i, _ in ft.overlap(t)} - at_rest
    gone = [near[i] for i in hit]
    area = sum(f.calc_area() for f in gone)
    bmesh.ops.delete(hb, geom=gone, context="FACES")
    hb.transform(host_o.matrix_world.inverted())
    hb.to_mesh(host_o.data)
    hb.free()
    return {"faces_removed": len(gone), "area_m2": round(area, 4)}


report["end_walls"] = {f"flap_{s}{k}": end_wall_trim(f"flap_{s}{k}", f"wing_root_{s}") for s in "LR" for k in (1, 2)}
print("S1 end walls", json.dumps(report["end_walls"]), flush=True)
P.trace("end_walls")
report["split_noses"] = {s: trim_split_noses(f"aileron_{s}") for s in "LR"}  # before the lips are pulled clear of them
print("S1 split noses", json.dumps(report["split_noses"]), flush=True)

# ---- 3c. the lips pulled clear of the surfaces' sweep (the flaps' and ailerons' remaining cut-
# through): every host vertex some pose of the surface sweeps through, on the skin round its cove, moves forward
# (away from the hinge, in the chord plane) by whole centimetres until no pose holds it, up to LIP_PULL_MAX. No new
# triangles: the swept trim that cut the lips into a slot cost 16,000 ----
LIP_PULL_MAX, LIP_PULL_STEP = 0.15, 0.01  # (at 0.40 the inner flaps kept the same 4 vertices inside: depth buys nothing)


LOCAL_MAX = 0.15
PULL = {"flap_L1": False, "flap_R1": False}  # the inner flaps' lips stay where they were (116 mm
# from the flap at 0); pulling them forward bought nothing there and widened the gap


def lip_pullback(surface, host):
    pull = PULL.get(surface, True)
    import sweep as SW
    entries = [e for e in SW.surfaces() if e[0].name == surface]
    if not entries:
        return {"skipped": "no sweep entry"}
    trees = [t for h_, m_, d_, _ in entries for t in SW.envelope(h_, m_, d_)]
    hinge, ax, piv, fwd, up = surface_frame(surface)
    pts = [p for _, ms, _, _ in entries for m in ms for p in (m.matrix_world @ v.co for v in m.data.vertices)]
    ss = [(p - piv).dot(ax) for p in pts]
    s0, s1 = min(ss), max(ss)
    reach = max(((p - piv) - ax * (p - piv).dot(ax)).length for p in pts)
    host_o = bpy.data.objects[host]
    me = host_o.data
    mw, inv = host_o.matrix_world, host_o.matrix_world.inverted()
    skin_i = P.slot(host_o, P.SKIN)
    near = {v for p in me.polygons if p.material_index == skin_i for v in p.vertices}
    spo = bpy.data.objects.get(f"spoiler_{surface[-1]}_visible") if surface.startswith("aileron_") else None
    if spo is not None:  # the spoiler's footprint stays whole for its well, as in the cove (the clamshell's noses reach it)
        sp_pts = [spo.matrix_world @ Vector(c_) for c_ in spo.bound_box]
        lo_, hi_ = ([f(p[i] for p in sp_pts) + g for i in range(3)] for f, g in ((min, -0.05), (max, 0.05)))
        near = {v for v in near if not all(lo_[i] <= (mw @ me.vertices[v].co)[i] <= hi_[i] for i in range(3))}
    rest = BVHTree.FromPolygons(*SW.world([m for _, ms, _, _ in entries for m in ms]))  # the surface at 0: the lip's gap to it
    gaps = []  # (before, after) for each pulled vertex: its distance to the surface at rest
    moved, stuck_at = 0, []
    for vi in near:
        w = mw @ me.vertices[vi].co
        s = (w - piv).dot(ax)
        if not (s0 - 0.05 < s < s1 + 0.05) or ((w - piv) - ax * s).length > reach + 0.05:
            continue
        if not SW.inside(w, trees):
            continue
        if not pull:  # (the inner flaps: forward pulling only widened the gap at 0): left where they are, unless no
            # forward pull would clear them, the four the local fix below takes
            if all(SW.inside(w + fwd * (k * LIP_PULL_STEP), trees) for k in range(1, int(LIP_PULL_MAX / LIP_PULL_STEP) + 1)):
                stuck_at.append(vi)
            continue
        for k in range(1, int(LIP_PULL_MAX / LIP_PULL_STEP) + 1):
            q = w + fwd * (k * LIP_PULL_STEP)
            if not SW.inside(q, trees):
                gaps.append((rest.find_nearest(w)[3], rest.find_nearest(q)[3]))
                me.vertices[vi].co = inv @ q
                moved += 1
                break
        else:
            stuck_at.append(vi)
    # the vertices no forward pull clears (the same four a side on the inner flaps at any depth): which feature they are
    # on (the paint classes round them), and one local fix, each moved the least way out of the sweep up, down or along
    # the span, at most LOCAL_MAX
    cls = me.attributes.get("cls")
    cv = [0] * len(me.polygons)
    if cls is not None and cls.domain == "FACE":
        cls.data.foreach_get("value", cv)
    v_cls = {}
    for p in me.polygons:
        for v in p.vertices:
            v_cls.setdefault(v, set()).add(cv[p.index])
    where, fixed = [], 0
    for vi in stuck_at:
        w = mw @ me.vertices[vi].co
        where.append({"at": [round(c, 3) for c in w], "classes": sorted(v_cls.get(vi, ()))})
        best = None
        for d in (up, -up, ax, -ax):
            for k in range(1, int(LOCAL_MAX / LIP_PULL_STEP) + 1):
                q = w + d * (k * LIP_PULL_STEP)
                if not SW.inside(q, trees):
                    if best is None or k < best[0]:
                        best = (k, q)
                    break
        if best is not None:
            me.vertices[vi].co = inv @ best[1]
            fixed += 1
    me.update()
    return {"vertices_pulled": moved, "left_inside": len(stuck_at) - fixed, "stuck_moved_locally": fixed, "stuck": where,
            "gap_at_0_m_before_after": [round(max(g[0] for g in gaps), 3), round(max(g[1] for g in gaps), 3)] if gaps else None}


report["lip_pullback"] = {surf: lip_pullback(surf, host) for s in "LR" for surf, host in
                          ((f"flap_{s}1", f"wing_root_{s}"), (f"flap_{s}2", f"wing_root_{s}"), (f"aileron_{s}", f"wing_outer_{s}"))}
print("S1 lip pullback", json.dumps(report["lip_pullback"]), flush=True)
P.trace("lip_pullback")

# ---- 3d. the variant: the flap fairings' rear halves on their own hinges (fairing.py; off by default) ----
import fairing  # noqa: E402

if fairing.variant_on():
    report["fairing_hinges"] = fairing.build_all(copy_attrs_from_neighbours)
    print("S1 fairing hinges", json.dumps(report["fairing_hinges"]), flush=True)
    report["fairing_leftovers"] = fairing.leftovers()
    if any(report["fairing_leftovers"].values()):
        raise SystemExit(f"s1: flap faces left inside a fairing that swings away: {report['fairing_leftovers']}")
print("S1 seams", json.dumps(report["seams"]), "\nS1 coves", json.dumps(report["coves"]), "\nS1 paint", report["paint_groups"], flush=True)
P.trace("fairings")

# ---- 4. spoiler wells ----
import spoiler_well  # noqa: E402

report["spoilers"] = {}
for s in "LR":
    report["spoilers"][s] = spoiler_well.build(s)
    wing = bpy.data.objects[f"wing_outer_{s}"]
    vis = bpy.data.objects[f"spoiler_{s}_visible"]
    for name, into in ((f"pass_well_{s}", wing), (f"pass_well_fittings_{s}", wing), (f"pass_pins_fixed_{s}", wing),
                       (f"pass_frame_{s}", vis), (f"pass_pins_moving_{s}", vis)):
        o = bpy.data.objects.get(name)
        if o is None:
            continue
        with bpy.context.temp_override(active_object=into, selected_editable_objects=[into, o]):
            bpy.ops.object.join()
    if report["spoilers"][s].get("frame_through_panel_pairs"):  # the frame crossed the panel 282 times
        raise SystemExit(f"s1_cut: spoiler {s}'s frame crosses its panel: {report['spoilers'][s]['frame_through_panel_pairs']} pairs")
    if any(r for _, r in report["spoilers"][s]["sweep_intersections"]):
        raise SystemExit(f"s1_cut: spoiler {s} crosses the wing: {report['spoilers'][s]['sweep_intersections'][:3]}")
P.trace("spoilers")

# ---- 4b. the ruddervators' ends closed up to the fixed fin (the outer ruddervator's cove end
# showed a wedge of gap widening to the trailing edge; the moving surface's end is extended, the fin, a damage part's
# outline, stays). Each end vertex moves along the hinge line to END_GAP short of the fixed geometry it faces, if that
# lies within END_REACH ----
END_GAP, END_REACH = 0.003, 0.15
fix_v, fix_p = [], []
for o in P.part_objects()[0].values():
    if o.name.startswith("ruddervator_"):
        continue
    b_ = len(fix_v)
    fix_v += [o.matrix_world @ v.co for v in o.data.vertices]
    fix_p += [[b_ + i for i in p.vertices] for p in o.data.polygons]
FIXED = BVHTree.FromPolygons(fix_v, fix_p)
report["ruddervator_ends"] = {}
for o in sorted((o for o in P.part_objects()[0].values() if o.name.startswith("ruddervator_") and o.name.endswith("_visible")), key=lambda o: o.name):
    hinge = bpy.data.objects[o.name[:-len("_visible")]]
    ax = hinge.matrix_world.col[0].xyz.normalized()
    piv = hinge.matrix_world.translation
    mw, mi = o.matrix_world, o.matrix_world.inverted()
    ss = [(mw @ v.co - piv).dot(ax) for v in o.data.vertices]
    lo, hi = min(ss), max(ss)
    moved, worst = 0, 0.0
    for v, s in zip(o.data.vertices, ss):
        for end, d in ((hi, ax), (lo, -ax)):
            if abs(s - end) > 0.005:
                continue
            p = mw @ v.co
            h = FIXED.ray_cast(p + d * 1e-4, d, END_REACH)
            if h[0] is not None and h[3] > END_GAP:
                v.co = mi @ (p + d * (h[3] - END_GAP))
                moved += 1
                worst = max(worst, h[3] - END_GAP)
    o.data.update()
    report["ruddervator_ends"][o.name] = {"vertices_moved": moved, "longest_m": round(worst, 3)}
print("S1 ruddervator ends", report["ruddervator_ends"], flush=True)
P.trace("ruddervator_ends")

# ---- 5. no zero-area skin: the spoiler holes' bisects leave slivers (sol2: 159 on wing_outer_L) ----
for o in P.part_objects()[0].values():
    bm_ = bmesh.new()
    bm_.from_mesh(o.data)
    n0 = len(bm_.faces)
    bmesh.ops.dissolve_degenerate(bm_, dist=1e-5, edges=bm_.edges[:])
    sk_ = {i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN}
    for _ in range(6):  # welding a removed sliver's ends can leave the next one: until none
        flat_ = [fc for fc in bm_.faces if fc.material_index in sk_ and fc.calc_area() < 1e-8]  # long collinear slivers the dissolve leaves
        if not flat_:
            break
        vs_ = list(dict.fromkeys(v for fc in flat_ for v in fc.verts))
        bmesh.ops.delete(bm_, geom=flat_, context="FACES_ONLY")
        bmesh.ops.remove_doubles(bm_, verts=[v for v in vs_ if v.is_valid], dist=1e-6)
        bmesh.ops.dissolve_degenerate(bm_, dist=1e-5, edges=bm_.edges[:])
    bm_.normal_update()  # same-winding coincident faces (the source has some; they fight for depth) go before triangulating
    seen2_, dup2_ = {}, []
    for fc in bm_.faces:
        key = tuple(sorted(tuple(round(c, 5) for c in v.co) for v in fc.verts))
        if any(n_.dot(fc.normal) > 0.99 for n_ in seen2_.get(key, [])):
            dup2_.append(fc)
        else:
            seen2_.setdefault(key, []).append(fc.normal.copy())
    if dup2_:
        bmesh.ops.delete(bm_, geom=dup2_, context="FACES_ONLY")
    ngons_ = [fc for fc in bm_.faces if fc.material_index in sk_ and len(fc.verts) > 4]  # the hole cuts leave long concave n-gons, which unwrap to needles (sol2 5)
    if ngons_:
        bmesh.ops.triangulate(bm_, faces=ngons_, quad_method="BEAUTY", ngon_method="BEAUTY")
    # needles: skin triangles under 1 mm altitude (the hole cuts leave them; sol2 2 counted 103 on wing_outer_L) unwrap
    # unstably and throw a corner across the atlas. One with a short edge loses it; a cap (every edge long, the apex
    # within 1 mm of the long edge) has that edge split under its apex and the two merged at the apex, since collapsing
    # a cap's shortest edge drags a corner up to half its length and folds the neighbours (wing_outer_L: 0.7 m, edges
    # of four and five faces)
    SLIVER = 0.004  # altitude: 1 mm left slivers of a few mm by the aileron coves that unwrap squashed (wing_outer_R, p5 36 px/m)
    for pass_ in range(8):
        shorts, caps = set(), []
        for fc in bm_.faces:
            if fc.material_index in sk_ and len(fc.verts) == 3:
                es = sorted(fc.edges, key=lambda e: e.calc_length())
                longest = es[-1].calc_length()
                if longest > 0 and 2 * fc.calc_area() / longest < SLIVER:
                    if es[0].calc_length() < 2 * SLIVER:
                        shorts.add(es[0])
                    else:
                        caps.append((fc, es[-1], next(v for v in fc.verts if v not in es[-1].verts)))
        if not shorts and not caps:
            break
        if shorts:
            bmesh.ops.collapse(bm_, edges=[e for e in shorts if e.is_valid], uvs=True)
        for v in bm_.verts:
            v.tag = False
        for fc, e, apex in caps:
            if not (fc.is_valid and e.is_valid and apex.is_valid) or apex in e.verts:
                continue
            # one merge a neighbourhood a pass: a fan of caps on one far corner (an aileron's end rib) has each cap's
            # neighbour across its long edge as the next cap, and merging on a neighbour's stale edge opened the fan
            a_, b_ = e.verts
            d_ = b_.co - a_.co
            t_ = (apex.co - a_.co).dot(d_) / d_.length_squared
            if not 0.0 < t_ < 1.0:
                continue
            near_ = [v for f_ in e.link_faces for v in f_.verts]
            if any(v.tag for v in near_):
                continue
            for v in near_:
                v.tag = True
            # a cap still here after four passes is part of a lens thinner than SLIVER, where merging at the apex makes the
            # next cap (the aft bay's side panels kept 12 through every pass): its apex goes onto the long edge instead
            at_ = apex.co.copy() if pass_ < 4 else a_.co + d_ * t_
            bmesh.ops.delete(bm_, geom=[fc], context="FACES_ONLY")  # the cap goes; the face across the long edge closes onto the apex
            _, nv = bmesh.utils.edge_split(e, a_, t_)
            bmesh.ops.pointmerge(bm_, verts=[nv, apex], merge_co=at_)
            # the face across is now a quad with a straight corner at the apex: split from the apex, not across it
            kept_ = apex if apex.is_valid else nv  # pointmerge keeps one of the two
            wide = [f_ for f_ in kept_.link_faces if len(f_.verts) > 3 and f_.material_index in sk_]
            if wide:
                bmesh.ops.triangulate(bm_, faces=wide, quad_method="BEAUTY", ngon_method="BEAUTY")
        bmesh.ops.dissolve_degenerate(bm_, dist=1e-5, edges=bm_.edges[:])
    last_ = [fc for fc in bm_.faces if fc.material_index in sk_ and fc.calc_area() < 1e-8]
    if last_:  # what the welds cannot close: a face of no area covers nothing, so it simply goes
        bmesh.ops.delete(bm_, geom=last_, context="FACES_ONLY")
    # skin folded back over skin (the cove trims' fine triangles after the sliver merges): the smaller face of each
    # same-facing pair on one edge, on the same side of it, goes; the larger still covers the place
    bm_.normal_update()
    fold_ = set()
    for e in bm_.edges:
        fs_ = [f for f in e.link_faces if f.material_index in sk_ and f.normal.length > 0.5]
        if len(fs_) < 2:
            continue
        a_, b_ = e.verts[0].co, e.verts[1].co
        if (b_ - a_).length < 1e-9:
            continue
        d_ = (b_ - a_).normalized()
        side_ = [((f.calc_center_median() - a_) - d_ * (f.calc_center_median() - a_).dot(d_)).normalized() for f in fs_]
        for i in range(len(fs_)):
            for j in range(i + 1, len(fs_)):
                if side_[i].dot(side_[j]) > 0.9 and fs_[i].normal.dot(fs_[j].normal) > 0.98:
                    fold_.add(min(fs_[i], fs_[j], key=lambda f: f.calc_area()))
    if fold_:
        bmesh.ops.delete(bm_, geom=list(fold_), context="FACES_ONLY")
    bm_.to_mesh(o.data)
    bm_.free()
    bad_ = {p.index for p in o.data.polygons if p.area < 1e-8 and p.material_index in sk_}  # a bow-tie ngon: bmesh's area is not the mesh's
    if bad_:
        bm_ = bmesh.new()
        bm_.from_mesh(o.data)
        bm_.faces.ensure_lookup_table()
        bmesh.ops.delete(bm_, geom=[bm_.faces[i] for i in bad_], context="FACES_ONLY")
        bm_.to_mesh(o.data)
        bm_.free()
zero = {o.name: sum(1 for p in o.data.polygons if p.area < 1e-8 and o.data.materials and o.data.materials[p.material_index] and o.data.materials[p.material_index].name == P.SKIN) for o in P.part_objects()[0].values()}
zero = {k: v for k, v in zero.items() if v}
thin = {}
for o in P.part_objects()[0].values():
    sk2 = {i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN}
    o.data.calc_loop_triangles()
    n_ = 0
    for lt in o.data.loop_triangles:
        if o.data.polygons[lt.polygon_index].material_index in sk2:
            ps = [o.data.vertices[v].co for v in lt.vertices]
            longest = max((ps[i] - ps[(i + 1) % 3]).length for i in range(3))
            n_ += longest > 0 and 2 * lt.area / longest < 0.001
    if n_:
        thin[o.name] = n_
report["skin_triangles_under_1mm_altitude"] = thin
print("S1 needles left", thin, flush=True)
report["zero_area_skin"] = zero
if zero:
    raise SystemExit(f"s1_cut: zero-area skin faces: {zero}")
folded = P.folded_skin_edges()
report["folded_skin_edges"] = {"source_welded": FOLD0, "after": folded}
back_after = P.folded_skin_edges(back=True)
report["back_to_back_skin_edges"] = {"source_welded": {n: v[0] for n, v in BACK0.items()}, "after": {n: v[0] for n, v in back_after.items()}}
print("S1 folds", {n: v[0] for n, v in folded.items()}, "back to back, source", report["back_to_back_skin_edges"]["source_welded"], "after", report["back_to_back_skin_edges"]["after"], flush=True)
added = {n: (FOLD0.get(n, (0,))[0], v) for n, v in folded.items() if v[0] > FOLD0.get(n, (0,))[0]}
if added:
    bpy.ops.wm.save_as_mainfile(filepath=str(P.PASS / "s1_cut_failed.blend"))  # for the probes
    raise SystemExit(f"s1_cut: skin folded over skin, beyond the welded source's: {added}")

# (round 1 merged coplanar skin fragments here to save triangles; the merged faces unwrapped with collapsed and
# stretched UVs)

report["duplicate_faces"] = P.duplicate_gate("s1_cut", DUP0)
if fairing.variant_on():  # on the finished geometry: step 5's clean-up of the slivers and doubles the cuts leave counts
    report["fairings_carried"] = fairing.gate()
import split_gate  # noqa: E402

report["split_halves_clear"] = split_gate.gate()
P.trace("end")
P.finish(ctx, report)
