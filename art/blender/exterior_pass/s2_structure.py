"""Pass stage 2, structure: closing members on both sides of every cut, wing and V-tail structure, the stage sleeve and
lower liners, strut spars, honeycomb cores in every control surface. UNTESTED (written while Blender was unavailable).

Everything joins the part's own mesh, as the stock jets carry structure: members on pass_trim_* slots with UV0 on the
stock sheet's strips (trim.py, the Darkreach's rates), linings on pass_lining, cores on pass_honeycomb with UV0 in
metres over HC_TILE. s4_uv maps the pass_* slots onto the production materials. The recipes are the round 3 samples'
generalised to every part; counts are checked against baselines/budget.json.

blender --background --python s2_structure.py -- [--force]"""
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

ctx = P.begin("s2_structure", __file__)
DUP0 = {n: P.duplicate_faces(o) for n, o in P.part_objects()[0].items()}
import damage_tree as T  # noqa: E402
import trim  # noqa: E402

exec(compile("def st(v):" + Path(Path(__file__).parent / "s1_cut.py").read_text().split("def st(v):")[1].split("SEAM_TOL =")[0],
             "s1_cuts", "exec"))  # CUTS, st, zp, xp: the same planes as stage 1
WING_KINDS = ("wing", "stage", "tail", "strut", "engine")
HC_TILE = 0.8
CORE = 0.008  # honeycomb core depth under a control surface's skin; round 3's 5 mm read flush (damage_wing_0hp 1)
report = {"parts": {}}
added = {}


def part_bm(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    return bm


def canonical_order(bm):
    """Vertices by position, faces by their vertices: bmesh.ops.extrude_edge_only builds its new elements in an order
    that changes run to run (the same geometry, numbered differently), and the export would follow it."""
    rank = {v: i for i, v in enumerate(sorted(bm.verts, key=lambda v: v.co.to_tuple()))}  # sort() takes numbers only
    bm.verts.sort(key=lambda v: rank[v])
    bm.verts.index_update()
    rank = {f: i for i, f in enumerate(sorted(bm.faces, key=lambda f: sorted(v.index for v in f.verts)))}
    bm.faces.sort(key=lambda f: rank[f])
    bm.faces.index_update()


def outline(o, co, no, sectors=48):
    """The part's skin cut by the plane: points on it, as a loop ordered round their centroid (convex-ish sections)."""
    bm = part_bm(o)
    skin = P.slot(o, P.SKIN)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index != skin], context="FACES")
    r = bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces), plane_co=co, plane_no=no)
    pts = [v.co.copy() for v in r["geom_cut"] if isinstance(v, bmesh.types.BMVert)]
    bm.free()
    if len(pts) < 6:
        return [], None
    c = sum(pts, Vector()) / len(pts)
    e1 = no.orthogonal().normalized()
    e2 = no.cross(e1)
    ang = lambda p: math.atan2((p - c).dot(e2), (p - c).dot(e1))  # noqa: E731
    out = []
    for k in range(sectors):  # even angles round the centroid, the farthest point in each sector
        a0, a1 = -math.pi + 2 * math.pi * k / sectors, -math.pi + 2 * math.pi * (k + 1) / sectors
        sec = [p for p in pts if a0 <= ang(p) < a1]
        if sec:
            out.append(max(sec, key=lambda p: (p - c).length))
    return out, c


def ring_member(bm, loop, c, no, inset, hole, depth=0.012, sheets=2):
    """A frame or rib on the plane: between the loop inset by `inset` metres and an opening `hole` of the section's size,
    `sheets` faces `depth` apart, with a lip round the opening and a cap round the edge. Returns its faces. The inset is
    absolute: a fraction of the section left a 45 mm gap under a 6 m body's skin (round 3, break_body_side). Wing ribs
    take one sheet: two cut sheets 12 mm apart read as two offset rows of holes (round 3, break_wing_end)."""
    if len(loop) < 6:  # a sliver of a section (the part's tip): no member
        return []
    outer = [p - (p - c).normalized() * inset for p in loop]
    inner = [c + (p - c) * hole for p in loop]
    n = len(loop)
    fs = []
    for dz, flip in ((0.0, False), (depth, True))[:sheets]:
        vo = [bm.verts.new(p + no * dz) for p in outer]
        vi = [bm.verts.new(p + no * dz) for p in inner]
        for k in range(n):
            q = (vo[k], vo[(k + 1) % n], vi[(k + 1) % n], vi[k])
            fs.append(bm.faces.new(q[::-1] if flip else q))
    for loop_, d in ((inner, 0.04), (outer, 0.03)):
        a = [bm.verts.new(p - no * (d / 2)) for p in loop_]
        b = [bm.verts.new(p + no * (d / 2 + depth)) for p in loop_]
        fs += [bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k])) for k in range(n)]
    return fs


def frame_axes(no):
    """In the plane with normal no: chord (world y with no removed) and up (toward +z)."""
    ch = Vector((0, 1, 0)) - no * no.y
    ch = ch.normalized() if ch.length > 1e-3 else no.orthogonal().normalized()
    up = no.cross(ch)
    return ch, (up if up.z >= 0 else -up)


def spar_points(loop, c, ch, up, f):
    """Top and bottom skin points at chord fraction f of the section, inset 20 mm."""
    s = [(p - c).dot(ch) for p in loop]
    y = min(s) + (max(s) - min(s)) * f
    near = sorted(loop, key=lambda p: abs((p - c).dot(ch) - y))[:6]
    top = max(near, key=lambda p: (p - c).dot(up)) - up * 0.02
    bot = min(near, key=lambda p: (p - c).dot(up)) + up * 0.02
    return top, bot


def slab(bm, q, s):
    """A closed slab from the quad (or polygon) q, thickened by +-s (break_sample.slab)."""
    v1 = [bm.verts.new(p - s) for p in q]
    v2 = [bm.verts.new(p + s) for p in q]
    fs = [bm.faces.new(v1), bm.faces.new(list(reversed(v2)))]
    fs += [bm.faces.new((v1[k], v2[k], v2[(k + 1) % len(q)], v1[(k + 1) % len(q)])) for k in range(len(q))]
    return fs


SPAR_IN = 1.2  # metres the spar runs back inside the part from the closing web (break_sample.py: to 1.5 m)


def spar_stub(bm, top, bot, out, length, ch, back=SPAR_IN):
    """An I-beam spar running `back` inside the part and `length` past the rib along `out`, its web torn in a
    zigzag at the free end and its caps stopping at different lengths (break_sample.web, generalised off the wing's x
    axis): one continuous member through the closing web, as the hand-fit break had."""
    SPAR_IN = back  # noqa: N806
    steps = 6
    a_top, a_bot = top + out * length, bot + out * length
    edge = [a_top.lerp(a_bot, k / steps) + out * (0.05 if k % 2 else 0.0) for k in range(steps + 1)]
    fs = slab(bm, edge + [bot - out * SPAR_IN, top - out * SPAR_IN], ch * 0.0125)  # web 25 mm
    w, t = ch * 0.055, (top - bot).normalized() * 0.006  # caps 110 by 12 mm
    for p, off, cut in ((top, -1, 0.07), (bot, 1, -0.04)):
        q0, q1 = p + (top - bot).normalized() * 0.006 * off - out * SPAR_IN, p + out * (length + cut)
        fs += slab(bm, [q0 - w, q1 - w, q1 + w, q0 + w], t)
    return fs


def span_axis(o):
    """The part's longest principal axis (world), from its skin vertices."""
    np = __import__("numpy")
    pts = np.array([tuple(o.matrix_world @ v.co) for v in o.data.vertices])
    w, v = np.linalg.eigh(np.cov((pts - pts.mean(0)).T))
    a = Vector(v[:, -1])
    return a if a.dot(Vector((1, 1, 1))) >= 0 else -a, Vector(pts.min(0)), Vector(pts.max(0)), Vector(pts.mean(0))


# The weapon bays' stores, which the pass's structure must stay out of: CenturionAuthor's rack test (Bombs.cs RackFits)
# takes every grid within x 1.63 m, 2.25 m below to 0.58 m above its hardpoint (3.55 m up, at stations 12 and 28.1:
# Blender y -10.475 and 5.625) and 4.4 m fore and aft, and keeps every mesh 0.1 m clear of it. bay_F's closing member
# on its centre cut plane hung 0.18 m into it, and stopped the build.
STORES_BOX = [((-1.73, y_ - 4.5, 3.55 - 2.25 - 0.1), (1.73, y_ + 4.5, 3.55 + 0.58 + 0.1)) for y_ in (-10.475, 5.625)]
report["stores_cleared_faces"] = 0


def in_stores(co):
    return any(all(lo[i] <= co[i] <= hi[i] for i in range(3)) for lo, hi in STORES_BOX)


def clear_stores(bm_world):
    """What reaches into a bay's stores is cut at the stores' top, and the part below goes."""
    for lo, hi in STORES_BOX:
        near = [f for f in bm_world.faces if any(lo[0] <= v.co.x <= hi[0] and lo[1] <= v.co.y <= hi[1] and lo[2] <= v.co.z < hi[2] for v in f.verts)]
        if not near:
            continue
        geom = list(dict.fromkeys(v for f in near for v in f.verts)) + list(dict.fromkeys(e for f in near for e in f.edges)) + near
        bmesh.ops.bisect_plane(bm_world, geom=geom, plane_co=Vector((0, 0, hi[2])), plane_no=Vector((0, 0, 1)))
        inside = [f for f in bm_world.faces if in_stores(f.calc_center_median())]
        bmesh.ops.delete(bm_world, geom=inside, context="FACES")
        report["stores_cleared_faces"] += len(inside)


# the control surfaces' swept envelopes (sweep.py), the fairings' among them: a member there would be cut by the surface
# over its travel; every join keeps out of them now, as the stations always did
import sweep as SW  # noqa: E402

ENVELOPES = []
MOVING = set()
for hinge_, moving_, degs_, _ in SW.surfaces():
    vs_ = [p for d in degs_ for p in SW.world(moving_, SW.turn(hinge_, d))[0]]
    ENVELOPES.append((Vector([min(p[i] for p in vs_) for i in range(3)]), Vector([max(p[i] for p in vs_) for i in range(3)]),
                      SW.envelope(hinge_, moving_, degs_), hinge_.matrix_world.col[0].xyz.normalized()))
    MOVING |= {m.name for m in moving_}
ENVELOPE_NEAR_M = 0.06  # how far along a hinge line past a surface's end a fixed member still counts as in its way


def in_envelope(c, near=0.0):
    return any(any(all(lo[i] - near <= (c + ax * s)[i] <= hi[i] + near for i in range(3)) and SW.inside(c + ax * s, trees)
                   for s in ((0.0, near, -near) if near else (0.0,)))
               for lo, hi, trees, ax in ENVELOPES)


report["structure_faces_dropped_in_sweep"] = {}


def clear_sweep(o, bm_world):
    """A fixed part's new structure out of every surface's swept volume (and ENVELOPE_NEAR_M past its ends), as the
    stations always were: a member there would be cut by the surface over its travel."""
    if o.name in MOVING:
        return
    gone = [f for f in bm_world.faces if in_envelope(f.calc_center_median(), ENVELOPE_NEAR_M)]
    if gone:
        bmesh.ops.delete(bm_world, geom=gone, context="FACES")
        report["structure_faces_dropped_in_sweep"][o.name] = report["structure_faces_dropped_in_sweep"].get(o.name, 0) + len(gone)


def join_into(o, bm_world, slot_name, along=None, trim_name=None, uv_metres=None):
    """Graft a world-space bmesh into o's mesh on slot_name, with trim UVs (or metre UVs for cores)."""
    clear_stores(bm_world)
    clear_sweep(o, bm_world)
    bm_world.normal_update()
    seen, twice = set(), []  # a section loop that doubles back along a seam (the cockpit's centre plane) bands it twice
    for f in bm_world.faces:
        key = (tuple(sorted(tuple(round(c, 5) for c in v.co) for v in f.verts)), tuple(round(c, 2) for c in f.normal))
        (twice.append(f) if key in seen else seen.add(key))
    if twice:
        bmesh.ops.delete(bm_world, geom=twice, context="FACES")
    faces = list(bm_world.faces)
    if trim_name:
        trim.apply(bm_world, faces, along, trim_name)
    elif uv_metres:
        uv = bm_world.loops.layers.uv.get("UVMap") or bm_world.loops.layers.uv.new("UVMap")
        for f in bm_world.faces:
            across = f.normal.cross(uv_metres).normalized() if f.normal.cross(uv_metres).length > 1e-6 else f.normal.orthogonal()
            for l in f.loops:
                l[uv].uv = (l.vert.co.dot(uv_metres) / HC_TILE, l.vert.co.dot(across) / HC_TILE)
    si = P.slot(o, slot_name)
    for f in bm_world.faces:
        f.material_index = si
    bm_world.transform(o.matrix_world.inverted())
    me = bpy.data.meshes.new("graft")
    bm_world.to_mesh(me)
    n = sum(len(p.vertices) - 2 for p in me.polygons)  # triangles, as the budget counts
    bm_world.free()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.from_mesh(me)
    bm.to_mesh(o.data)
    bm.free()
    bpy.data.meshes.remove(me)
    added[o.name] = added.get(o.name, 0) + n


tree = T.tree()
import sections as S  # noqa: E402

NEW_FACES = {}  # part -> [(world corners, label)] of the members this stage adds, for the outside-the-skin gate
CLIP_PROUD = "--no-clip" not in sys.argv  # --no-clip: build as before, so the gate shows what it catches


PROUD_M = 0.002  # a member vertex further than this outside the exterior shell shows through the paint


def proud(p):
    """How far p stands outside the exterior shell, by the nearest shell face's outward normal (negative inside)."""
    loc, n, _, _ = SKIN_BVH.find_nearest(p)
    return -1.0 if loc is None else (p - loc).dot(n)


OWN_SHELL = {}  # telescoping stage -> its own skin, world space (the exterior shell leaves out the nested stages' skins)


def proud_own(o, p):
    """How far p stands outside a telescoping stage's own skin (negative inside; -1 for any other part). Inside: the
    skin straight above and straight below, each met from within (the nearest face's normal misjudged points off the
    stage's rounded edges, and the dark sleeve over it met members standing 15 mm out)."""
    if "slide_axis" not in o:
        return -1.0
    if o.name not in OWN_SHELL:
        sk = {i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN}
        vs = [o.matrix_world @ v.co for v in o.data.vertices]
        OWN_SHELL[o.name] = BVHTree.FromPolygons(vs, [list(q.vertices) for q in o.data.polygons if q.material_index in sk])
    t = OWN_SHELL[o.name]
    loc, _, _, dist = t.find_nearest(p)
    if loc is not None and dist <= PROUD_M:
        return -1.0
    for d in (Vector((0, 0, 1)), Vector((0, 0, -1))):
        h = t.ray_cast(p, d, 10.0)
        if h[0] is None or h[1].dot(d) <= 0:
            return 1.0
    return -1.0


def keep(o, bm_world, label=""):
    """Record the members joined into o, clipping first every face with a vertex standing proud of the skin: the
    six-axis vote passed members whose edges showed through the paint (the look's 35 poke-through flags). A telescoping
    stage's members are held to its own skin as well: standing out of it they crossed its parent's structure as it
    slid (check_tele_clear.py), unseen by the exterior shell."""
    gone = [f for f in bm_world.faces if any(proud(v.co) > PROUD_M or proud_own(o, v.co) > PROUD_M for v in f.verts)] if CLIP_PROUD else []
    if gone:
        d = report.setdefault("members_clipped_proud", {})
        d[label.split(" ")[0]] = d.get(label.split(" ")[0], 0) + len(gone)
        bmesh.ops.delete(bm_world, geom=gone, context="FACES")
    NEW_FACES.setdefault(o.name, []).extend(([v.co.copy() for v in f.verts], label) for f in bm_world.faces)


# ---- the intact aircraft's exterior shell, and the test a member must pass (structure ahead of
# 371 skin sites on fuselage_F, 728 on Centurion): a point is inside when at least four of six axis rays from it first
# meet the shell from behind. The shell: skin faces from which a ray along the normal, or tilted 30 degrees four ways,
# leaves the aircraft (nested skins, the stages inside the wings and the bays' own walls, are not it). Closing members
# and stations are built against it; the gate at the end holds every member to it ----
from mathutils.bvhtree import BVHTree  # noqa: E402

sv, sp = [], []
for ob in bpy.data.objects:
    if ob.type != "MESH" or "_lod1" in ob.name or "_colmesh" in ob.name or any(c.name in ("Colliders", "LOD1") for c in ob.users_collection):
        continue
    sk_ = {i for i, m in enumerate(ob.data.materials) if m and m.name == P.SKIN}
    for p in ob.data.polygons:
        if p.material_index in sk_:
            base = len(sv)
            sv += [ob.matrix_world @ ob.data.vertices[v].co for v in p.vertices]
            sp.append(list(range(base, base + len(p.vertices))))
ALL_SKIN = BVHTree.FromPolygons(sv, sp)
ext_poly = []
for poly in sp:
    pts_ = [sv[i] for i in poly]
    c_ = sum(pts_, Vector()) / len(pts_)
    n_ = (pts_[1] - pts_[0]).cross(pts_[2] - pts_[0])
    if n_.length < 1e-12:
        continue
    n_.normalize()
    t1 = n_.orthogonal().normalized()
    t2 = n_.cross(t1)
    for d in (n_, (n_ + t1 * 0.58).normalized(), (n_ - t1 * 0.58).normalized(), (n_ + t2 * 0.58).normalized(), (n_ - t2 * 0.58).normalized()):
        if ALL_SKIN.ray_cast(c_ + d * 0.002, d, 80.0)[0] is None:
            ext_poly.append(poly)
            break
SKIN_BVH = BVHTree.FromPolygons(sv, ext_poly)
print("S2 exterior shell", len(ext_poly), "of", len(sp), "skin faces", flush=True)
AXES = [Vector(v) for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]


def inside_shell(c):
    votes = 0
    for d in AXES:
        hit = SKIN_BVH.ray_cast(c, d, 60.0)
        votes += hit[0] is not None and hit[1].dot(d) > 0
    return votes >= 4


SHEET_PNG = P.game_texture("jet_mechanical_AlbedoTransparency.png")
_sheet = bpy.data.images.load(str(SHEET_PNG))
SHEET_W, SHEET_H = _sheet.size
import numpy as _np  # noqa: E402

SHEET_A = _np.array(_sheet.pixels[:], dtype=_np.float32).reshape(SHEET_H, SHEET_W, 4)[..., 3]
bpy.data.images.remove(_sheet)
BREAK_WEBS, BODY_CUTS = {}, []


def first_hits_into(o, co, inward, loop):
    """Rays straight into a body cut from 0.3 m outside, over a grid inside its section: the share whose first hit on
    the part is its frame, braces or stubs (pass_trim), the rest by slot. The cut mask."""
    me, mw = o.data, o.matrix_world
    vs = [mw @ v.co for v in me.vertices]
    tree = BVHTree.FromPolygons(vs, [list(p.vertices) for p in me.polygons])
    mats = [me.materials[p.material_index].name if me.materials[p.material_index] else "" for p in me.polygons]
    c = sum(loop, Vector()) / len(loop)
    hits, n = {}, 0
    for i in range(0, len(loop), max(1, len(loop) // 24)):
        for t in (0.15, 0.35, 0.55, 0.75, 0.92):
            p = c + (loop[i] - c) * t + (co - c).dot(inward) * inward - inward * 0.3
            h = tree.ray_cast(p, inward, 1.3)
            n += 1
            k = "none" if h[0] is None else ("frame" if mats[h[2]].startswith("pass_trim") else mats[h[2]])
            hits[k] = hits.get(k, 0) + 1
    return {k: round(v / max(n, 1), 3) for k, v in hits.items()}


def clipped_share(f, uvl):
    """The share of a face's area the stock sheet's alpha cuts at 0.394 (the hex openings), sampled at 16 points."""
    uvs = [l[uvl].uv for l in f.loops]
    n = 0
    for s in range(4):
        for t in range(4):
            a, b = (s + 0.5) / 4, (t + 0.5) / 4
            p = uvs[0] + (uvs[1] - uvs[0]) * a + (uvs[-1] - uvs[0]) * b * (1 - a) if len(uvs) == 3 else \
                (uvs[0] * (1 - a) + uvs[1] * a) * (1 - b) + (uvs[3] * (1 - a) + uvs[2] * a) * b
            n += SHEET_A[min(SHEET_H - 1, int(p.y * SHEET_H)), min(SHEET_W - 1, int(p.x * SHEET_W))] < 0.394
    return n / 16


INHERITED_PLATES = ("aircraft_structure", "Centurion_airframe")


def hull_2d(points, no):
    """The convex hull of points in the plane with normal no, as world points (a footprint from open chains too)."""
    e1, e2 = S.basis(no)
    q = sorted({(round(p.dot(e1), 4), round(p.dot(e2), 4)) for p in points})
    if len(q) < 3:
        return []
    cross = lambda o_, a, b: (a[0] - o_[0]) * (b[1] - o_[1]) - (a[1] - o_[1]) * (b[0] - o_[0])  # noqa: E731
    lo, hi = [], []
    for p in q:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(q):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return [e1 * x + e2 * y for x, y in lo[:-1] + hi[:-1]]


def clear_footprint(o, co, inward, outline, depth=0.6):
    """The inherited flat plates (the source's structure and damage lining) lying in a body cut's footprint (the convex
    hull of its outline) within depth of its plane go: they stood ahead of the frame and read as the break face
    (26% of the rays into the aft body's cut met them first). Returns the faces removed."""
    me, mw = o.data, o.matrix_world
    drop = {i for i, m in enumerate(me.materials) if m and m.name in INHERITED_PLATES}
    outline = hull_2d(outline, inward)
    if not drop or len(outline) < 3:
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    gone = []
    nm = mw.to_3x3().inverted().transposed()
    bm.normal_update()
    for f in bm.faces:
        if f.material_index in drop and abs((nm @ f.normal).normalized().dot(inward)) > 0.8:  # facing the break: the backing
            c = mw @ f.calc_center_median()  # (bay walls and cockpit floors run along the body and stay)
            if 0.0 <= (c - co).dot(inward) <= depth and S.point_in(c, outline, inward):
                gone.append(f)
    if gone:
        bmesh.ops.delete(bm, geom=gone, context="FACES")
        bm.to_mesh(me)
    bm.free()
    return len(gone)


def face_inside(f):
    """Every corner of the face inside the skin: a centre test let a stringer's corner poke through a thin wing's far
    skin, and the distant model's silhouette gate saw it (9% holes front-on)."""
    return inside_shell(f.calc_center_median()) and all(inside_shell(v.co) for v in f.verts)  # (and its centre, as the gate tests)


OWN_TREES = {}


def own_clip(name):
    """The own-skin test only on wing-like parts (wings, stages, tails, struts, pylons): a body section's own skin is an
    open shell where a bay's walls stand inside the fuselage (bay_A), the test dropped its closures' faces, and the
    unwrap then collapsed 106 of bay_A's skin faces (its density gate failed); the floating webs were on the struts."""
    return tree.get(name, {}).get("kind") in WING_KINDS


def inside_own(name, c, need=3):
    """c inside the part's own skin: at least `need` of the six axis rays meet that skin from within (its open cut lets
    one or two escape). The exterior shell holds the neighbour across the cut too, so a closing web standing past the
    part's own end, inside the neighbour, passed it and floated free once the neighbour broke away (strut_outer_L)."""
    if name not in OWN_TREES:  # (own_skin_tree is defined further down, with the lattice)
        o_ = bpy.data.objects[name]
        sk_ = {i for i, m in enumerate(o_.data.materials) if m and m.name == P.SKIN}
        vs_ = [o_.matrix_world @ v.co for v in o_.data.vertices]
        OWN_TREES[name] = BVHTree.FromPolygons(vs_, [list(p.vertices) for p in o_.data.polygons if p.material_index in sk_] or [[0, 0, 0]])
    t = OWN_TREES[name]
    votes = 0
    for d in AXES:
        hit = t.ray_cast(c, d, 60.0)
        votes += hit[0] is not None and hit[1].dot(d) > 0
    return votes >= need


def inside_only(bm, name, own=True):
    """A closing member is built inside the skin, the part's own as well as the aircraft's: the faces that would stand
    out of either are not built (counted per part). By centre: it lies on the open cut, where its corners' axis rays
    escape through the opening. own=False for the torn spar stubs, which stand out of the break by design."""
    out_ = [f for f in bm.faces if not inside_shell(f.calc_center_median()) or (own and own_clip(name) and not inside_own(name, f.calc_center_median()))]
    if out_:
        d = report.setdefault("closing_faces_dropped_outside", {})
        d[name] = d.get(name, 0) + len(out_)
        bmesh.ops.delete(bm, geom=out_, context="FACES")


# ---- closing members: one per part and cut plane (two cuts on one plane, fuselage_F and bay_F against the centre
# body, built the ring twice in round 1), on the skin's own section 30 mm inside the cut ----
planes, closures = {}, {}


def backing_panel(o, name, co, inward, no, seam_pts, seam_len):
    """A body break's panel following the section 0.45 m behind the frame, recessed behind the braces (the opening shows
    depth), in lit painted metal (the dark lining read as a black cap behind the frame); the slice of the seam's own
    section, its length within half to one and a half times the seam's."""
    c_seam = sum(seam_pts, Vector()) / len(seam_pts)
    deep = [lp2 for lp2 in S.section_loops(o, co + inward * 0.45, no) if S.closed(lp2) and 0.5 * seam_len < S.length(lp2) < 1.5 * seam_len]
    deep.sort(key=lambda lp2: (sum(lp2, Vector()) / len(lp2) - c_seam - inward * 0.45).length)
    if deep:
        ring_pts = S.inset(S.resample(deep[0], 48), no, 0.02)
    else:  # partial frames on an open shell (bay_A's walls at the tailcone cut): the seam's own outline, its convex hull
        # on the cut plane, 0.45 m in
        from mathutils.geometry import convex_hull_2d
        e1_, e2_ = S.basis(no)
        q_ = [((p - c_seam).dot(e1_), (p - c_seam).dot(e2_)) for p in seam_pts]
        hull_ = convex_hull_2d(q_)
        if len(hull_) < 3:
            return
        ring_pts = [c_seam + e1_ * q_[i][0] + e2_ * q_[i][1] + inward * 0.45 for i in hull_]
    lb = bmesh.new()
    cd_ = sum(ring_pts, Vector()) / len(ring_pts)
    ring_pts = [cd_ + (p - cd_) * 0.7 for p in ring_pts]  # partial: the panel stops short of the skin, its edge in the shadow
    fc = lb.faces.new([lb.verts.new(p) for p in ring_pts])
    lb.normal_update()
    if fc.normal.dot(-inward) < 0:
        fc.normal_flip()
    inside_only(lb, name)
    print("S2 backing panel", name, round(co.dot(no), 2), "from", "its section" if deep else "the seam's outline",
          "kept" if lb.faces else "dropped as outside", flush=True)
    keep(o, lb, "liner")
    join_into(o, lb, "pass_paint")


for a, b, co, no in CUTS:
    for name in (a, b):
        key = (name, round(co.dot(no), 4), tuple(round(c, 3) for c in no))
        planes.setdefault(key, (name, co, no))
for name, co, no in planes.values():
    o = bpy.data.objects[name]
    side = 1 if sum(((o.matrix_world @ p.center) - co).dot(no) > 0 for p in o.data.polygons) > len(o.data.polygons) / 2 else -1
    inward = no * side
    wingish = tree[name]["kind"] in WING_KINDS
    # the seam itself: this part's open skin edges in the cut plane (a slice of the part, as round 1 and the first try
    # here took, can cross the whole part: a horizontal pylon cut sliced the inner wing into a 17 m loop)
    def closure_of(found):
        """Closed seam loops over 0.4 m, or else the open chains bridged into one (the aft body's five, the fin root's
        eight): [] when neither gives one."""
        good = [lp for lp in found if S.closed(lp) and S.length(lp) > 0.4]
        if good:
            return good, "closed"
        b_ = S.bridge([lp for lp in found if len(lp) >= 2], no)
        if b_ is not None and S.length(b_) > 0.4:
            return [b_], "bridged"
        part_ = [lp for lp in found if len(lp) >= 3 and S.length(lp, closed=False) > 0.3]  # chains of different shells:
        return (part_, "partial frames") if part_ else ([], "")  # a partial frame along each, its open ends accounted for

    found = S.boundary_loops(o, co, no)
    seams, how = closure_of(found)
    if seams and not how.startswith("partial") and own_clip(name):  # a wing-like part's closed or bridged seam must be its own cut end: its middle,
        # 30 mm in, inside the part's own skin (a partial ring's middle lies in its opening, where the rays escape: 11 of
        # them moved for nothing, and the plates their clearing took broke bay_A's UV density)
        allp_ = [p for lp_ in seams for p in lp_]
        mid_ = sum(allp_, Vector()) / len(allp_) + inward * 0.03
        if not inside_own(name, mid_):
            report.setdefault("closures_moved_to_own_end", []).append(f"{name}@{round(co.dot(no), 2)}")
            seams = []
    if not seams:  # the part ends short of the cut plane (the inner wing beside the body, 657 mm): its own end
        kp = [o.matrix_world @ v.co for v in o.data.vertices]
        end = min(kp, key=lambda p: abs((p - co).dot(no)))
        co = co + no * (end - co).dot(no)
        found = S.boundary_loops(o, co, no, tol=0.01)
        seams, how = closure_of(found)
        how = how and how + " at the part's own end"
        if not seams:  # its end is closed skin, no seam: the closure goes on its own section 30 mm inside that end
            for step in (0.03, 0.06, 0.1, 0.15, 0.2, 0.3):  # inward past any lip reaching beyond the part proper (the
                found = S.section_loops(o, co + inward * step, no)  # wing root's fairing lip: 0.24 m round at 30 mm in)
                if sum(S.length(lp) for lp in found) > 2.0:
                    break
            co = co + inward * step
            seams, how = closure_of(found)
            how = how and how + f" on its section {step * 1000:.0f} mm in"
    closures[(name, round(co.dot(no), 3))] = (how if seams else "NONE", len(found), [len(lp) for lp in seams])
    loops = [[p + inward * 0.01 for p in lp] for lp in seams]
    if not loops:
        continue
    if not wingish:
        cleared_ = clear_footprint(o, co, inward, [p for lp in loops for p in lp] if how.startswith("partial") else loops[0])
        if cleared_:
            report.setdefault("inherited_plates_cleared", {})[f"{name}@{round(co.dot(no), 2)}"] = cleared_
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    ch_, up_ = frame_axes(no)
    if how.startswith("partial"):
        centre_ = sum((p for lp in loops for p in lp), Vector()) / sum(len(lp) for lp in loops)
        for lp in loops:
            S.open_band(bm, lp, centre_, 0.5 if wingish else 0.75, "wing_web" if wingish else "body_web", uvl)
        if not wingish:  # braces across the opening 0.12 m in, as on the closed rings
            e1_, e2_ = S.basis(no)
            allp = [p for lp in loops for p in lp]
            for ax_ in (e1_, e2_):
                ext = [(p - centre_).dot(ax_) for p in allp]
                a_, b_ = centre_ + ax_ * min(ext) * 0.8 + inward * 0.12, centre_ + ax_ * max(ext) * 0.8 + inward * 0.12
                w_ = ax_.cross(no).normalized() * 0.05
                f_ = bm.faces.new([bm.verts.new(p) for p in (a_ - w_, b_ - w_, b_ + w_, a_ + w_)])
                for l, uv_ in zip(f_.loops, ((0.28, 0.98), (0.56, 0.98), (0.56, 0.94), (0.28, 0.94))):
                    l[uvl].uv = uv_
        BODY_CUTS.append((name, co.copy(), inward.copy(), [p.copy() for lp in loops for p in lp]))
        loops = []
    webs_ = []
    for lp in loops:
        if wingish:  # the rib web across the whole section, its hex openings along the chord, as the Darkreach's break web
            webs_ += S.web_plate(bm, lp, no, ch_, up_, "wing_web", uvl)
        else:  # a frame ring: the opening is the section scaled toward its centroid (a mitred inset crossed thin sections)
            dense = S.resample(lp, max(12, min(64, int(S.length(lp) / 0.12))))
            cc = sum(dense, Vector()) / len(dense)
            outer = S.inset(dense, no, 0.015)
            inner = [cc + (p - cc) * 0.8 for p in outer]
            for k in range(2):
                S.band(bm, [p + inward * (0.012 * k) for p in outer], [p + inward * (0.012 * k) for p in inner], "body_web", uvl, flip=bool(k))
            S.band(bm, inner, [p + inward * 0.06 for p in inner], "flange", uvl)  # the ring's return flange
            # two braces across the opening 0.12 m in, so a member crosses the view ahead of the recessed panel
            # (the broad backing read as the frame)
            e1_, e2_ = S.basis(no)
            for ax_ in (e1_, e2_):
                ext = [(p - cc).dot(ax_) for p in inner]
                a_, b_ = cc + ax_ * min(ext) * 0.98 + inward * 0.12, cc + ax_ * max(ext) * 0.98 + inward * 0.12
                w_ = ax_.cross(no).normalized() * 0.05
                f_ = bm.faces.new([bm.verts.new(p) for p in (a_ - w_, b_ - w_, b_ + w_, a_ + w_)])
                for l, uv_ in zip(f_.loops, ((0.28, 0.98), (0.56, 0.98), (0.56, 0.94), (0.28, 0.94))):
                    l[uvl].uv = uv_  # the body web strip's corrugation (trim.TRIMS["body_web"])
    inside_only(bm, name)
    if loops and not wingish:
        BODY_CUTS.append((name, co.copy(), inward.copy(), [p.copy() for p in loops[0]]))
    if webs_ and loops:  # the web's share of its section, and its clipped (hex) share on the stock sheet
        e1_, e2_ = S.basis(no)
        sec_area = 0.0
        for lp in loops:
            q_ = [(p.dot(e1_), p.dot(e2_)) for p in lp]
            sec_area += abs(sum(q_[i][0] * q_[(i + 1) % len(q_)][1] - q_[(i + 1) % len(q_)][0] * q_[i][1] for i in range(len(q_)))) / 2
        live = [f for f in webs_ if f.is_valid]
        web_area = sum(f.calc_area() for f in live)
        clip_a = sum(f.calc_area() * clipped_share(f, uvl) for f in live)
        BREAK_WEBS[f"{name}@{round(co.dot(no), 2)}"] = {"web_share_of_section": round(web_area / max(sec_area, 1e-9), 3),
                                                        "clipped_share": round(clip_a / max(web_area, 1e-9), 3)}
    keep(o, bm, f"closing {round(co.dot(no), 2)} {how}")
    join_into(o, bm, "pass_trim_cut" if wingish else "pass_trim")
    if not loops and how.startswith("partial") and not wingish:  # the panel behind partial frames too: without it the
        # aft body's break looked down an empty, unlit tube (break_bay_A_from_tailcone, median luma 0.09)
        allp_ = [p for lp_ in seams for p in lp_]
        backing_panel(o, name, co, inward, no, allp_, sum(S.length(lp_, closed=False) for lp_ in seams))
    if not loops:
        continue
    lp = loops[0]
    c = sum(lp, Vector()) / len(lp)
    if tree[name]["kind"] in ("wing", "stage", "tail"):  # three spars torn 0.07 to 0.16 m past the rib, out of the break (not the thin struts and pylons, where they stood out of the skin)
        ch, up = frame_axes(no)
        sb = bmesh.new()
        stubs_ = []
        for f, length_ in ((0.15, 0.16), (0.45, 0.11), (0.7, 0.07)):
            top, bot = spar_points(S.inset(S.resample(lp, 48), no, 0.02), c, ch, up, f)
            # back no further than the skin behind the rib: at a wing's horizontal cut (the tip rail) inward is the
            # wing's depth, and a 1.2 m run stood out above and below it (the distant model's front silhouette)
            h_ = SKIN_BVH.ray_cast((top + bot) / 2 + inward * 0.01, inward, SPAR_IN)
            depth_ = SPAR_IN if h_[0] is None else h_[3]
            back_ = max(0.05, min(SPAR_IN, depth_ - 0.03))
            # nor into a spoiler's well (the stringers' box): the rear spar stub's top cap ran 1.17 m into the outer
            # wing across the well and read as a pale strip on its floor when the panel rose (audit of build 49, 36)
            for sp_ in (bpy.data.objects.get(f"spoiler_{s_}_visible") for s_ in "LR"):
                if sp_ is not None:
                    mi_ = sp_.matrix_world.inverted()
                    lo_ = [min(c_[i] for c_ in sp_.bound_box) - 0.03 - 0.25 * (i == 2) for i in range(3)]
                    hi_ = [max(c_[i] for c_ in sp_.bound_box) + 0.03 for i in range(3)]
                    in_ = [k_ / 50 for k_ in range(int(back_ * 50) + 1) if any(all(lo_[i] <= (mi_ @ (p_ + inward * k_ / 50))[i] <= hi_[i] for i in range(3))
                                                                         for p_ in (top + ch * 0.055, top - ch * 0.055, bot + ch * 0.055, bot - ch * 0.055))]
                    back_ = max(0.05, in_[0] - 0.02) if in_ else back_
            stubs_.append(spar_stub(sb, top, bot, -inward, length_, ch, back=back_))
        inside_only(sb, name, own=False)
        key_ = f"{name}@{round(co.dot(no), 2)}"
        if key_ in BREAK_WEBS:  # a spar end counts when most of its faces were built (inside the skin)
            BREAK_WEBS[key_]["spar_ends"] = sum(1 for fs_ in stubs_ if sum(f_.is_valid for f_ in fs_) > len(fs_) / 2)
        keep(o, sb, "spar stubs")
        join_into(o, sb, "pass_trim", along=up, trim_name="flange")
    else:
        backing_panel(o, name, co, inward, no, seams[0], S.length(seams[0]))
# gate: every part closes every cut it has, and says how (the seam graph lost real loops silently)
report["closures"] = {f"{n}@{d}": v for (n, d), v in closures.items()}
print("S2 closures", {k: v[0] for k, v in report["closures"].items()}, flush=True)
missing_ = [k for k, v in report["closures"].items() if v[0] == "NONE"]
if missing_:
    raise SystemExit(f"s2_structure: break faces with no closure: {missing_}")
# gate: the selected thick wing break (inner to outer wing, both sides): a web over 90% of its section, three spar ends
# through it, and 8 to 20% of its area in the stock web's hex openings
report["break_webs"] = BREAK_WEBS
print("S2 break webs", {k: v for k, v in BREAK_WEBS.items() if "@12.6" in k or "@-12.6" in k}, flush=True)
bad_webs = {k: v for k, v in BREAK_WEBS.items() if ("@12.6" in k or "@-12.6" in k) and not (
    v["web_share_of_section"] >= 0.9 and v.get("spar_ends", 0) >= 3 and 0.08 <= v["clipped_share"] <= 0.20)}
if bad_webs:
    raise SystemExit(f"s2_structure: the thick wing break's web, spars or openings miss their marks: {bad_webs}")
# gate: rays into the sampled aft-body break meet its frame, braces or stubs first at least 25% of the time (step 5)
report["body_cut_first_hits"] = {f"{n}@{round(c_.dot(i_), 2)}": first_hits_into(bpy.data.objects[n], c_, i_, lp_) for n, c_, i_, lp_ in BODY_CUTS}
print("S2 body cut first hits", {k: v.get("frame", 0) for k, v in report["body_cut_first_hits"].items()}, flush=True)
low_ = {k: v for k, v in report["body_cut_first_hits"].items() if k.startswith("fuselage_R@") and v.get("frame", 0) < 0.25}
if low_:
    raise SystemExit(f"s2_structure: the aft body's break shows its frame under 25% of the way in: {low_}")
# ---- structure where holes open, sized to each part's budget (budget.json structure_add) ----
# Wing kinds: ribs across the span axis (round the stage channel where a stage sits inside: damage3.py's recipe) and a
# rear spar web between them. Body kinds: ring frames across the fuselage axis. Stations are spread evenly over the
# part's span, as many as its budget pays for at RIB_TRIS / FRAME_TRIS each (at least two where it has any budget).
# triangles each station costs as built: a rib round the stage channel 16 quads, a holed rib 16 quads plus two 16-quad
# flanges, a body frame two 32-quad sheets plus two flanges; a spar bay 2
CHANNEL_RIB_TRIS, RIB_TRIS, FRAME_TRIS, SPAR_TRIS = 32, 96, 256, 2
STAGE_OF = {"wing_outer_L": "wing_tele1_L", "wing_outer_R": "wing_tele1_R"}
closing_used = dict(added)


def exterior_tris():
    """check_tris.py's count: every rendered mesh but LOD hulls, colliders and blockout shapes."""
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or o.hide_render or "_lod1" in o.name or "_colmesh" in o.name or o.name.endswith(("_blockout_mesh", "_shape")):
            continue
        if any(c.name in ("Colliders", "LOD1") for c in o.users_collection):
            continue
        n += sum(len(p.vertices) - 2 for p in o.data.polygons)
    return n


def skin_tris(o):
    sk = {i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN}  # P.slot would add the slot
    return sum(len(p.vertices) - 2 for p in o.data.polygons if p.material_index in sk)



report["station_faces_dropped_outside"] = {}
report["station_faces_dropped_in_sweep"] = {}
# Structure takes what is left of the owner's 230,000 after the cut, the wells, the closing members and what stages 2
# and 3 will still add (the cores and sleeves here, the two-sided skin in s3), shared by the budget's proportions. It
# was sized from the budget alone and the pass came out at 265,000 (s1's wells and cuts ran over theirs).
SINGLE = ("geardoor_", "baydoor_", "nose_hatch", "nose_door", "gear_", "wheel_", "fan_", "laser_")  # s3_twins.SINGLE
parts_now, _ = P.part_objects()
# ---- the skin a hole can open: the only skin that gets an inward copy (s3) or a core under it:
# two-sided skin everywhere took 74,989 triangles and left structure none; the Darkreach copies 78 pairs on its outer
# wing and spends the rest on structure. A face is tagged `opens` when any of its sample points, or one OPEN_MARGIN
# from it along the axes, lies in a cell that opens by 0 HP (damage_field: the same field the bake paints) ----
sys.path.insert(0, str(P.REPO / "art" / "blender"))
import numpy as np  # noqa: E402
from m4 import paint  # noqa: E402

import damage_field as DF  # noqa: E402

OPEN_MARGIN = 0.1  # past the bake's 6 px gutter (0.1 m at 60 px/m) and a cell edge's ragged reach (BORDER + RAG)
DILATE = np.array([(0, 0, 0), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)], float) * OPEN_MARGIN


def openable(o):
    """(flags, points): o's skin faces any of whose samples (dilated) lies in a cell open by 0 HP, and per such face up
    to SEE_PTS of its open sample points with the face's outward normal, for the sight lines."""
    me, mw = o.data, o.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    sk = {i for i, m in enumerate(me.materials) if m and m.name == P.SKIN}
    me.calc_loop_triangles()
    rng = np.random.default_rng(7)
    pts, owner, gates = [], [], {}
    for lt in me.loop_triangles:
        if me.polygons[lt.polygon_index].material_index not in sk:
            continue
        a, b, c = (np.array(mw @ me.vertices[v].co) for v in lt.vertices)
        k = int(min(64, max(4, lt.area / 0.01)))
        r1, r2 = np.sqrt(rng.random(k)), rng.random(k)
        tri = a * (1 - r1)[:, None] + b * (r1 * (1 - r2))[:, None] + c * (r1 * r2)[:, None]
        gate = np.array([a + (b - a) * s + (c - a) * t for s, t in DF.SIGHT_BARY])  # the gate's own points first
        gates.setdefault(lt.polygon_index, []).extend(gate)
        pts.append(np.vstack([gate, a, b, c, tri]))
        owner += [lt.polygon_index] * (len(gate) + k + 3)
    flags = [0] * len(me.polygons)
    sights = []
    if pts:
        P_ = np.vstack(pts)
        hit = np.zeros(len(P_), bool)
        for d in DILATE:
            hit |= np.asarray(DF.opens_by_0hp(P_ + d, paint))
        per = {}
        for j in np.nonzero(hit)[0]:
            per.setdefault(owner[j], []).append(j)
        for i, js in per.items():
            flags[i] = 1
            n = (nm @ me.polygons[i].normal).normalized()
            sights += [(Vector(P_[j]), n, k < SEE_PTS) for k, j in enumerate(js)]  # straight in from every open point, tilted from a few
            # and straight in from each of the gate's own sample points: the bake's texel there can be open where this
            # field's point is not (check_damage_area met one such ray from the inner strut)
            sights += [(Vector(g), n, False) for g in gates.get(i, [])]
    return flags, sights


SEE_PTS = 4
OPEN_POINTS = {}  # part -> [(open point, outward normal)]: the holes' sight lines, for the coverage gate at the end
SEE_DIRS = [(0.0, 0.0)] + [(40.0, a) for a in range(0, 360, 45)]  # (tilt from straight in, azimuth) of the sight lines


def tag_openable(objs):
    """Write the face attribute `opens`: the skin a hole can open, and the skin whose back a sight line from inside a
    hole meets first (the opposite skin's inside, which must show painted and lit, not culled to the sky). Returns
    {part: (tagged skin triangles, skin triangles)}."""
    flags, sights = {}, []
    for n_, o in objs.items():
        flags[n_], s = openable(o)
        sights += s
        OPEN_POINTS[n_] = [(p, n) for p, n, _ in s]
    vs, ps, own = [], [], []
    for n_, o in objs.items():  # every part's skin, so a hole near a seam can see into the next part
        me, mw = o.data, o.matrix_world
        sk = {i for i, m in enumerate(me.materials) if m and m.name == P.SKIN}
        b = len(vs)
        vs += [mw @ v.co for v in me.vertices]
        for p in me.polygons:
            if p.material_index in sk:
                ps.append([b + i for i in p.vertices])
                own.append((n_, p.index, (mw.to_3x3().inverted().transposed() @ p.normal).normalized()))
    tree = BVHTree.FromPolygons(vs, ps)
    seen = 0
    for p, n, tilted in sights:
        t = n.orthogonal().normalized()
        u = n.cross(t)
        for tilt, az in (SEE_DIRS if tilted else SEE_DIRS[:1]):
            r, a = math.radians(tilt), math.radians(az)
            d = (-n * math.cos(r) + (t * math.cos(a) + u * math.sin(a)) * math.sin(r)).normalized()
            h = tree.ray_cast(p + d * 0.02, d, 40.0)  # from 20 mm in, as check_damage_area looks
            if h[0] is not None:
                n2, fi, fn = own[h[2]]
                if fn.dot(d) > 0 and not flags[n2][fi]:  # its back faces the hole
                    flags[n2][fi] = 1
                    seen += 1
    out = {}
    for n_, o in objs.items():
        me = o.data
        a_ = me.attributes.get("opens") or me.attributes.new("opens", "INT", "FACE")
        a_.data.foreach_set("value", flags[n_])
        sk = {i for i, m in enumerate(me.materials) if m and m.name == P.SKIN}
        out[n_] = (sum(len(p.vertices) - 2 for p in me.polygons if flags[n_][p.index]), sum(len(p.vertices) - 2 for p in me.polygons if p.material_index in sk))
    print("S2 sight lines from", len(sights), "open points; added", seen, "faces seen through holes", flush=True)
    return out


# every part, doors and gear too: a door or a leg seen through a hole needs its inner side (check_damage_area's gate)
opens_tris = tag_openable({n_: o for n_, o in parts_now.items() if not n_.startswith("pass_")})
report["openable_skin"] = {n_: {"tagged_tris": t, "skin_tris": s} for n_, (t, s) in opens_tris.items()}
twins_next = sum(t for t, _ in opens_tris.values())
cores_next = sum(t for n_, (t, _) in opens_tris.items() if n_.endswith("_visible") and n_.startswith(("flap_", "aileron_", "ruddervator_")))
print("S2 openable skin", twins_next, "of", sum(s for _, s in opens_tris.values()), "skin triangles take an inward copy", flush=True)
P.trace("openable")
# ---- stringers: box members along each part just under its skin, the member a hole's view crosses first (sol3/
# the holes showed the sleeve, lining and inward skin with nothing in front; the
# hand-fit wing sample ran six 25 x 20 mm strips 12 mm under the skin). Each station's section is set to start at its
# most forward (wing) or highest (body) point and wind one way, so a stringer keeps its place round the section ----
def mid_z_of(o):
    """The body section's own height of centre: its skin's middle in z."""
    zs = [(o.matrix_world @ v.co).z for v in o.data.vertices]
    return (min(zs) + max(zs)) / 2


STRINGERS = {"wing_root": 12, "wing_outer": 12, "fuselage_R": 16, "fuselage_F": 16, "tailcone": 12, "vtail_tip": 8, "vtail_": 8}
STRINGER_STEP, STRINGER_IN, STRINGER_W, STRINGER_D = 0.6, 0.015, 0.05, 0.02  # hat sections 50 mm wide, 20 deep


def aligned_section(o, co, ax, wingish):
    lps = S.section_loops(o, co, ax)
    lp = next((x for x in lps if S.closed(x) and S.length(x) > 0.8), None) or S.bridge(lps, ax)
    if lp is None:  # open chains of different shells (the aft body's bay openings): the longest alone
        lp = max(lps, key=lambda x: S.length(x, closed=False), default=None)
        if lp is None or S.length(lp, closed=False) < 0.8:
            return None
    lp = S.resample(lp, 96)
    e1, e2 = S.basis(ax)
    c = sum(lp, Vector()) / len(lp)
    area = sum(((lp[k] - c).dot(e1)) * ((lp[(k + 1) % len(lp)] - c).dot(e2)) - ((lp[(k + 1) % len(lp)] - c).dot(e1)) * ((lp[k] - c).dot(e2)) for k in range(len(lp)))
    if area < 0:
        lp = lp[::-1]
    start = min(range(len(lp)), key=lambda k: lp[k].y) if wingish else max(range(len(lp)), key=lambda k: lp[k].z)
    return lp[start:] + lp[:start], c


def stringers(o, prefix, count):
    wingish = tree.get(o.name.replace("_visible", ""), {}).get("kind") in WING_KINDS
    ax, lo, hi, mid = span_axis(o)
    if prefix.startswith(("wing_",)):
        ax = Vector((1, 0, 0)) if mid.x > 0 else Vector((-1, 0, 0))
    elif not wingish:
        ax = Vector((0, 1, 0))
    s_lo, s_hi = min(lo.dot(ax), hi.dot(ax)) + 0.1, max(lo.dot(ax), hi.dot(ax)) - 0.1
    n_st = max(2, int((s_hi - s_lo) / STRINGER_STEP) + 1)
    rails = [[] for _ in range(count)]
    for k in range(n_st):
        s = s_lo + (s_hi - s_lo) * k / (n_st - 1)
        sec = aligned_section(o, ax * s + (mid - ax * mid.dot(ax)), ax, wingish)
        for j in range(count):
            if sec is None:
                rails[j].append(None)
                continue
            lp, c = sec
            p = lp[int(len(lp) * (j + 0.5) / count) % len(lp)]
            n_in = (c - p).normalized()
            rails[j].append((p + n_in * STRINGER_IN, n_in))
    bm = bmesh.new()
    for rail in rails:
        for a, b in zip(rail, rail[1:]):
            if a is None or b is None or (a[0] - b[0]).length > 2 * STRINGER_STEP:
                continue
            t = (b[0] - a[0]).normalized()
            wa, wb = t.cross(a[1]).normalized() * STRINGER_W / 2, t.cross(b[1]).normalized() * STRINGER_W / 2
            ring_a = [a[0] - wa, a[0] + wa, a[0] + wa + a[1] * STRINGER_D, a[0] - wa + a[1] * STRINGER_D]
            ring_b = [b[0] - wb, b[0] + wb, b[0] + wb + b[1] * STRINGER_D, b[0] - wb + b[1] * STRINGER_D]
            va, vb = [bm.verts.new(p) for p in ring_a], [bm.verts.new(p) for p in ring_b]
            for i in range(4):
                bm.faces.new([va[i], va[(i + 1) % 4], vb[(i + 1) % 4], vb[i]])
    # on the body, points along a piece's edges too, 0.1 m apart: pieces up to 0.85 m long crossed the refuelling
    # receptacle's slipway with both ends and their middles under skin (not on a wing, whose thin skin misleads the
    # nearest face's normal)
    def edge_proud(e):
        a, b = e.verts[0].co, e.verts[1].co
        n = max(2, math.ceil((b - a).length / 0.1))
        return any(proud(a.lerp(b, k / n)) > PROUD_M for k in range(1, n))
    out_ = [f for f in bm.faces if not face_inside(f) or in_envelope(f.calc_center_median())
            or (not wingish and any(edge_proud(e) for e in f.edges))]
    # nor in a spoiler's well, a box in the panel's own swept frame (its world box held half the outer wing's
    # stringers): the split raises the panel 50 degrees, and stringers across the well read as stray grey bars
    wells = [(sp.matrix_world.inverted(), [min(c[i] for c in sp.bound_box) - 0.03 - 0.25 * (i == 2) for i in range(3)],
              [max(c[i] for c in sp.bound_box) + 0.03 for i in range(3)])
             for sp in (bpy.data.objects.get(f"spoiler_{s}_visible") for s in "LR") if sp is not None]
    out_ += [f for f in bm.faces if f not in out_ and any(all(lo[i] <= (mi @ p)[i] <= hi[i] for i in range(3))
                                                          for p in [f.calc_center_median(), *(v.co for v in f.verts)]
                                                          for mi, lo, hi in wells)]
    bmesh.ops.delete(bm, geom=out_, context="FACES")
    return bm


# the inherited damage lining (Centurion_airframe) in the body sections, pressed 25 mm under the skin, recessed 0.18 m
# toward the body's axis, so the frames and stringers stand ahead of it (63% of the rays
# into the aft body's holes met the lining first)
LINING_RECESS = 0.18
report["lining_recessed"] = {}
# Not in the weapon bays (bay_F, bay_A), whose lining is the stores' walls and roof (recessed, it went into the racks'
# clearance and stopped the build), and never a corner a skin face shares (it dragged bay_A's wall tops 7.5 cm inboard).
for o in [x for x in P.part_objects()[0].values() if x.name.startswith(("fuselage_", "tailcone", "Centurion"))]:
    me, mw = o.data, o.matrix_world
    li_ = {i for i, m in enumerate(me.materials) if m and m.name == "Centurion_airframe"}
    if not li_:
        continue
    bm = bmesh.new()
    bm.from_mesh(me)
    vs_ = {v for f in bm.faces if f.material_index in li_ for v in f.verts if all(g.material_index in li_ for g in v.link_faces)}
    axis_x = sum(((mw @ v.co).x for v in vs_), 0.0) / max(1, len(vs_))
    mwi = mw.inverted()
    for v in vs_:
        w = mw @ v.co
        r = Vector((w.x - axis_x, 0.0, w.z - mid_z_of(o)))
        if r.length > LINING_RECESS + 0.05:
            v.co = mwi @ (w - r.normalized() * LINING_RECESS)
    bm.to_mesh(me)
    bm.free()
    report["lining_recessed"][o.name] = len(vs_)
report["stringers"] = {}
for o in [x for x in P.part_objects()[0].values() if not x.name.endswith("_visible")]:
    prefix = next((k for k in STRINGERS if o.name.startswith(k)), None)
    if prefix is None:
        continue
    bm = stringers(o, prefix, STRINGERS[prefix])
    if bm.faces:
        report["stringers"][o.name] = sum(len(f.verts) - 2 for f in bm.faces)
        keep(o, bm, "stringers")
        join_into(o, bm, "pass_trim", along=Vector((0, 1, 0)) if not o.name.startswith(("wing_", "vtail")) else Vector((1, 0, 0)), trim_name="flange")
    else:
        bm.free()
print("S2 stringers", report["stringers"], flush=True)

# ---- the lattice behind the holes, as the stock does it cheaply (lead, decision 1b, 2026-11-23): under each opening,
# one sheet on the cut-out trim's perforated web 50 mm under the skin, through four of the opening's extreme points
# (each moved in along its own normal, so the sheet follows the curve), and a second, corrugated, 0.13 m in where the
# bay is deeper than 0.25 m: a few triangles an opening, in front of the sleeve, the lining and the far skin ----
LATTICE_DEPTHS = ((0.05, "wing_web"), (0.13, "body_web"))
LATTICE_DEEP_BAY_M = 0.25  # the second sheet only in a bay this thick (built before the allowance, which pays for it)


def own_skin_tree(o):
    """The part's own skin, world space: a lattice sheet must lie under its own part's skin, not another's (the outer
    wing's root sheets passed under the inner wing's skin, which it telescopes into, and stood out of both)."""
    sk = {i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN}
    vs = [o.matrix_world @ v.co for v in o.data.vertices]
    return BVHTree.FromPolygons(vs, [list(p.vertices) for p in o.data.polygons if p.material_index in sk] or [[0, 0, 0]])


def sheet_inside(f, out, depth, own):
    """A lattice sheet is one flat face across a whole bay: under a curved skin it can stand out between its corners
    (the distant model's front silhouette caught a 0.33 m2 sheet edge-on), so it is tested on a 5 by 5 grid, and from
    each grid point the ray straight out (`out`, the bay's mean normal) must meet the skin within the sheet's depth and
    0.1 m: the axis-ray vote passed points a few millimetres proud of a curved skin (the look flagged bright tabs
    through the painted skin on most parts)."""
    vs = [v.co for v in f.verts]
    if not face_inside(f):
        return False
    pts = [a.lerp(b, 0.5) for a, b in zip(vs, vs[1:] + vs[:1])] if len(vs) != 4 else \
        [vs[0].lerp(vs[1], i / 4).lerp(vs[3].lerp(vs[2], i / 4), j / 4) for i in range(5) for j in range(5)]
    for p in pts:
        if not inside_shell(p):
            return False
        h = own.ray_cast(p + out * 1e-3, out, depth + 0.1)
        if h[0] is None:
            return False
    return True


DARK_MIN_M = 0.016  # a thin bay's backdrop at least this far in: s3's inward copies of the skin sit 2 to 12 mm under it
INWARD_CLEAR = 0.015  # a thin bay's backdrop keeps this from the next skin in (the telescoping stage's; at 8 mm it met
# the stage's lining)


STAGE_TWIN_M = (0.002, 0.004, 0.006, 0.008, 0.010, 0.012)  # s3's inward skin copies sit 2 to 12 mm in: the stage's skin at these depths
NESTED = {}  # part -> every face of the telescoping stages nested in it (skin, rails, the source's own structure), at
# five points of their travel (build_centurion.py: rest_location + slide_axis x travel_m x extension, parent space)


def nested_tree(o):
    if o.name not in NESTED:
        vs, ps = [], []
        for s in bpy.data.objects:
            if s.type == "MESH" and s.parent == o and "slide_axis" in s:
                ws = [s.matrix_world @ v.co for v in s.data.vertices]
                n3 = s.matrix_world.to_3x3().inverted().transposed()
                ns = [(n3 @ v.normal).normalized() for v in s.data.vertices]
                sk = P.slot(s, P.SKIN)
                skin_ps = [q for q in s.data.polygons if q.material_index == sk]
                # the stage as it is, and its skin at each STAGE_TWIN_M in
                layers = [(ws, s.data.polygons)] + [([p - n * t for p, n in zip(ws, ns)], skin_ps) for t in STAGE_TWIN_M]
                for ext in (0.0, 0.25, 0.5, 0.75, 1.0):
                    d = (o.matrix_world @ s.matrix_parent_inverse).to_3x3() @ (Vector(s["slide_axis"]) * (s["travel_m"] * ext))
                    for lv, lp in layers:
                        b = len(vs)
                        vs += [p + d for p in lv]
                        ps += [[b + i for i in q.vertices] for q in lp]
        NESTED[o.name] = BVHTree.FromPolygons(vs, ps) if ps else None
    return NESTED[o.name]


def clear_inward(f, out, o):
    """A thin bay's backdrop is flat across a curved skin, so its middle sags toward the next skin in, and its edges
    cut the next skin's rounded sides (check_tele_clear caught the outer wing's crossing its stage's skin and rails):
    neither the sheet nor its copy INWARD_CLEAR further in may cross any skin, or anything of a stage nested in o (its
    own skin lies above it)."""
    vs = [v.co.copy() for v in f.verts]
    nest = nested_tree(o)
    for off in (0.0, INWARD_CLEAR):
        t = BVHTree.FromPolygons([p - out * off for p in vs], [list(range(len(vs)))])
        if t.overlap(ALL_SKIN) or (nest is not None and t.overlap(nest)):
            return False
    return True


def lattice_sheet(bm, uvl, corners, normals, depth, strip):
    (u0, u1, v0, v1), tpm, _ = trim.TRIMS[strip]
    L = trim.strip_metres(strip)
    across_m = (v1 - v0) * trim.ATLAS_PX / (tpm * 0.55)
    pts = [p - n * depth for p, n in zip(corners, normals)]
    t1 = (pts[1] - pts[0]).normalized()
    origin = pts[0]
    f = bm.faces.new([bm.verts.new(p) for p in pts])
    for l, p in zip(f.loops, pts):
        a, b = (p - origin).dot(t1), (p - origin).cross(t1).length
        l[uvl].uv = (u0 + min(1.0, a / L) * (u1 - u0), v1 - min(1.0, b / across_m) * (v1 - v0))
    f.normal_update()  # facing out through the opening: a back face is culled for the eye but still shades (the game's and
    if f.normal.dot(sum(normals, Vector())) < 0:  # the review's rule), so an inward sheet left the holes black
        f.normal_flip()
    return f


# ---- the owner, 2026-11-23 afternoon ("shapes good, make thin bays dark"): braced trusses in every bay deep enough
# (truss.py: 8 by 4 cm members, at least truss.MIN_DEPTH deep; a body bay only behind a hole of truss.PANEL_HOLE_M2),
# the bay's lattice moved behind them as the backdrop; a thin bay (the outer wing's middle, over its telescoping
# stage) a near-black backdrop just under the skin with shallow rib lines, where the stage's skin showed through the
# holes as a flat brown sheet. Trusses take TRUSS_BUDGET of the 260,000 cap first, the stations the rest;
# the biggest openings get theirs first ----
import truss as TR  # noqa: E402

THIN_M = 0.15  # a bay this thick or thinner (outer skin to the next skin in) gets the dark backdrop, no truss
TRUSS_BUDGET = 24_000  # the trusses' triangles; the stations below get what is left to TOTAL_TARGET (about 5,000)
report["lattice"], report["trusses"], report["backdrops"] = {}, {}, {}


def bays_of(name_, pts_):
    """The part's opening bays: the panel grid's cells, each split by which way its points face (a cell across a thin
    wing holds both skins), with at least four points each: [(points, normals, outward normal, thickness)]."""
    P_ = np.array([tuple(p) for p, _ in pts_])
    groups = {}
    for (p, n), c in zip(pts_, map(tuple, DF.panel_index(P_, paint))):
        groups.setdefault(c, []).append((p, n))
    out = []
    for grp in groups.values():
        ref = grp[0][1]
        for side in (1, -1):
            g = [pn for pn in grp if (pn[1].dot(ref) >= 0) == (side == 1)]
            if len(g) < 4:
                continue
            nm = sum((n for _, n in g), Vector()).normalized()
            c_ = sum((p for p, _ in g), Vector()) / len(g)
            h = FAR_SKIN.ray_cast(c_ - nm * 0.01, -nm, 3.0)
            out.append(([p for p, _ in g], [n for _, n in g], nm, (h[0] - c_).length if h[0] is not None else 0.0))
    return out


# A bay's depth is measured to the skin and to the nacelles' whole meshes: the bypass ducts' walls are on the nacelles'
# structure and mechanical slots, so measured on ALL_SKIN a bay on the reverser sleeve ran through the wall to the core
# cowl and its trusses stood 0.35 m into the open duct, black marks in the nozzle (audit of build 49, finding 28)
fv, fp = list(sv), list(sp)
for ob in (x for x in bpy.data.objects if x.type == "MESH" and x.name.startswith("nacelle_") and "_colmesh" not in x.name
           and "_lod1" not in x.name):
    for q in ob.data.polygons:
        fp.append(list(range(len(fv), len(fv) + len(q.vertices))))
        fv += [ob.matrix_world @ ob.data.vertices[v].co for v in q.vertices]
FAR_SKIN = BVHTree.FromPolygons(fv, fp)
BAYS = {}
for name_, pts_ in OPEN_POINTS.items():
    if bpy.data.objects.get(name_) is not None and pts_ and not name_.startswith(SINGLE) and not name_.endswith("_visible"):
        BAYS[name_] = bays_of(name_, pts_)
# the truss bays: deep enough, a body's only behind a panel-sized hole, the most open points first, to the budget
cands = []
for name_, bays_ in BAYS.items():
    kind_ = "wing" if tree.get(name_, {}).get("kind") in WING_KINDS else "body"
    for k_, (ps, ns, nm, thick) in enumerate(bays_):
        if thick > THIN_M and (kind_ == "wing" or TR.hole_area_at(sum(ps, Vector()) / len(ps), nm, kind_, paint) >= TR.PANEL_HOLE_M2):
            cands.append((len(ps), name_, k_, kind_))
cands.sort(reverse=True)
OWN_SKIN = {n_: own_skin_tree(bpy.data.objects[n_]) for n_ in BAYS}
TRUSS_BM = {}  # part -> its trusses (world bmesh, flange strip UVs)
BACK = {}  # (part, bay) -> the depth of the lattice sheet behind its trusses
TRUSS_TRIS = 0
report["trusses_out_of_the_stores"] = 0  # a truss reaching into a bay's stores is not built (a clipped one would hang open)

for _, n_, k_, kd_ in cands:  # built in order until the budget is spent (a bay whose trusses do not fit costs nothing)
    if TRUSS_TRIS >= TRUSS_BUDGET:
        break
    ps, ns, nm, thick = BAYS[n_][k_]
    bay_ = TR.bay_of(ps, ns, kd_, OWN_SKIN[n_], FAR_SKIN)
    if bay_ is None:
        continue
    if n_ not in TRUSS_BM:
        TRUSS_BM[n_] = bmesh.new()
        TRUSS_BM[n_].loops.layers.uv.new("UVMap")
    bmt = TRUSS_BM[n_]
    fs_ = TR.build(bmt, bmt.loops.layers.uv["UVMap"], bay_, OWN_SKIN[n_], ALL_SKIN)
    if fs_ and any(in_stores(v.co) for f in fs_ if f.is_valid for v in f.verts):
        bmesh.ops.delete(bmt, geom=[f for f in fs_ if f.is_valid], context="FACES")
        report["trusses_out_of_the_stores"] += 1
        continue
    if fs_:
        TRUSS_TRIS += sum(len(f.verts) - 2 for f in fs_ if f.is_valid)
        BACK[(n_, k_)] = bay_["top_in"] + bay_["depth"] + 0.01
report["truss_bays"] = {"built": len(BACK), "candidates": len(cands), "estimate_triangles": TRUSS_TRIS}
TRUSS_TRIS, RIB_TRIS = 0, 0  # counted again after the proud clip, as joined

for name_, bays_ in BAYS.items():
    o = bpy.data.objects.get(name_)
    kind_ = "wing" if tree.get(name_, {}).get("kind") in WING_KINDS else "body"
    own_ = OWN_SKIN[name_]
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    bmt = TRUSS_BM.get(name_) or bmesh.new()
    meta = {}  # sheet -> (its bay's outward normal, its depth, dark), for sheet_inside and the ribs
    for k_, (ps, ns, nm, thick) in enumerate(bays_):
        t1 = nm.orthogonal().normalized()
        t2 = nm.cross(t1)
        ex = [max(zip(ps, ns), key=lambda pn: pn[0].dot(t1)), max(zip(ps, ns), key=lambda pn: pn[0].dot(t2)),
              min(zip(ps, ns), key=lambda pn: pn[0].dot(t1)), min(zip(ps, ns), key=lambda pn: pn[0].dot(t2))]
        if len({tuple(round(c, 3) for c in p) for p, _ in ex}) < 4:
            continue
        # on a wing the deep sheet is the dark backdrop, not the corrugated web: that strip is polished metal on the stock
        # sheet (metal 0.95, smoothness 0.55) and, seen from below through a flap's cove at 30 degrees, its flat 0.4 m2
        # sheets mirrored the sky as chrome bands; the dark patch's zero occlusion keeps it dark in the game
        sheets = LATTICE_DEPTHS if kind_ != "wing" else (LATTICE_DEPTHS[0], (LATTICE_DEPTHS[1][0], "dark"))
        if thick <= THIN_M:  # under the inward copies s3 makes 2 to 12 mm in, and INWARD_CLEAR above the next skin
            sheets = ((min(0.03, max(DARK_MIN_M, 0.4 * thick)), "dark"),) if thick >= DARK_MIN_M + INWARD_CLEAR + 0.004 else ()
        elif (name_, k_) in BACK:  # the lattice moves behind the trusses: one sheet, the bay's backdrop
            sheets = ((BACK[(name_, k_)], LATTICE_DEPTHS[0][1]),)
        for depth, strip in sheets:
            if depth == LATTICE_DEPTHS[1][0] and thick < LATTICE_DEEP_BAY_M:
                continue
            try:
                meta[lattice_sheet(bm, uvl, [p for p, _ in ex], [n for _, n in ex], depth, strip)] = (nm, depth, strip == "dark")
            except ValueError:
                pass
    out_ = []
    for f in list(bm.faces):  # a sheet standing out at its edges shrinks toward its bay's centre before it is given up
        c0 = f.calc_center_median()
        orig = [v.co.copy() for v in f.verts]
        for k in (0.0, 0.15, 0.3, 0.45):
            for v, p in zip(f.verts, orig):
                v.co = c0 + (p - c0) * (1 - k)
            if sheet_inside(f, *meta[f][:2], own_) and (not meta[f][2] or clear_inward(f, meta[f][0], o)):
                break
        else:
            out_.append(f)
            continue
        if in_envelope(f.calc_center_median()):
            out_.append(f)
    report.setdefault("lattice_sheets_dropped", {})[name_] = (len(out_), len(meta))
    bmesh.ops.delete(bm, geom=out_, context="FACES")
    # a sheet through four offset points is not flat: tested as a quad (a polygon tree's own diagonal) it cleared the
    # stage while the triangles drawn, on the other diagonal, crossed it (wing_outer_R): each sheet is tested again as
    # the two triangles it will be drawn as, and goes when they cross
    for f in [f for f in bm.faces if meta.get(f, (0, 0, False))[2] and len(f.verts) == 4]:
        a_, b_, c_, d_ = (v.co.copy() for v in f.verts)
        tri_ = BVHTree.FromPolygons([a_, b_, c_, d_], [[0, 1, 2], [0, 2, 3], [0, 1, 3], [1, 2, 3]])
        nest_t_ = nested_tree(o)
        if tri_.overlap(ALL_SKIN) or (nest_t_ is not None and tri_.overlap(nest_t_)):
            bmesh.ops.delete(bm, geom=[f], context="FACES")
    dark = [f for f in bm.faces if meta.get(f, (0, 0, False))[2]]
    for f in dark:  # the dark backdrop's rib lines, on the flange strip
        nm, depth, _ = meta[f]
        ribs = TR.backdrop_ribs(bm, [v.co.copy() for v in f.verts], nm, kind_, depth)
        if ribs:
            RIB_TRIS += sum(len(g.verts) - 2 for g in trim.apply(bm, ribs, TR._axes(nm, kind_)[0], "flange"))
    report["backdrops"][name_] = len(dark)
    if bm.faces:
        report["lattice"][name_] = sum(len(f.verts) - 2 for f in bm.faces)
        keep(o, bm, "lattice")
        join_into(o, bm, "pass_trim_cut")
    else:
        bm.free()
    if bmt.faces:
        keep(o, bmt, "truss")
        n_ = sum(len(f.verts) - 2 for f in bmt.faces)
        report["trusses"][name_] = n_
        TRUSS_TRIS += n_
        join_into(o, bmt, "pass_trim_cut")
    else:
        bmt.free()
print("S2 lattice", report["lattice"], "triangles", sum(report["lattice"].values()), flush=True)
print("S2 trusses", report["trusses"], "triangles", TRUSS_TRIS, "of", TRUSS_BUDGET, report["truss_bays"],
      "dark backdrops", sum(report["backdrops"].values()), "rib triangles", RIB_TRIS, flush=True)

SLEEVES = 1_000
# the owner's 260,000 (check_tris.py holds the pass to it plus 3%): the stations fill what the trusses and everything
# before them leave, to TOTAL_TARGET, 3,800 under the gate for the stages after this one
TOTAL_TARGET = 264_000
allowance = TOTAL_TARGET - exterior_tris() - twins_next - cores_next - SLEEVES
wants, full = {}, {}
DENSITY = json.loads((P.BASELINES / "budget.json").read_text())["densities"]  # the Darkreach's structure triangles per m2 of skin, by kind
for name, want in P.budget().items():
    if want.get("kind") != "surface":  # what the part lacks of the Darkreach's density, after its own and the closing members
        full[name] = DENSITY[want["kind"]] * want["skin_m2"]
        wants[name] = max(0, int(full[name] - want.get("structure_now", 0) - closing_used.get(name, 0)))
share = min(1.0, max(0.0, allowance / max(1, sum(wants.values()))))
report["structure_share"] = {"allowance": allowance, "wanted": sum(wants.values()), "share": round(share, 3),
                             "twins_next": twins_next, "cores_next": cores_next}
print("S2 structure allowance", report["structure_share"], flush=True)
for name, want in sorted(P.budget().items()):
    # the part's structure budget plus what its closing members left of theirs (they came in under 250 a side)
    add = int(wants.get(name, 0) * share)
    o = bpy.data.objects.get(name) or bpy.data.objects.get(name + "_visible")
    if add <= 0 or o is None or want.get("kind") == "surface":
        continue  # control surfaces get their honeycomb core below
    wingish = tree.get(name, {}).get("kind") in WING_KINDS
    ax, lo, hi, mid = span_axis(o)
    if wingish and name.startswith(("wing_", "pylon_")):
        ax = Vector((1, 0, 0)) if mid.x > 0 else Vector((-1, 0, 0))
    elif not wingish:
        ax = Vector((0, 1, 0))  # fuselage sections: frames across the body's length
    s_lo, s_hi = min(lo.dot(ax), hi.dot(ax)), max(lo.dot(ax), hi.dot(ax))
    per = (CHANNEL_RIB_TRIS if name in STAGE_OF else RIB_TRIS) + SPAR_TRIS if wingish else FRAME_TRIS
    stage = bpy.data.objects.get(STAGE_OF.get(name, ""))

    def build_stations(n):
        ss = [s_lo + (s_hi - s_lo) * (k + 0.5) / n for k in range(n)]
        bm = bmesh.new()
        spar_pts, up = [], None
        for s in ss:
            co = ax * s + (mid - ax * mid.dot(ax))
            lps = [lp for lp in S.section_loops(o, co, ax) if S.closed(lp) and S.length(lp) > 0.4]
            if not lps:
                continue
            loop = S.resample(lps[0], 16 if wingish else 32)
            c = sum(loop, Vector()) / len(loop)
            if wingish and stage is not None:  # rib round the stage channel, inner edge 12% outside the stage's section
                sls = [lp for lp in S.section_loops(stage, co, ax) if S.closed(lp)]
                if sls:
                    sl = S.resample(sls[0], 16)
                    sc = sum(sl, Vector()) / len(sl)
                    outer = S.inset(S.resample(lps[0], 16), ax, 0.015)
                    inner = S.inset(sl, ax, -0.02)  # 20 mm clear of the stage's own skin
                    dense = S.resample(S.inset(sls[0], ax, -0.02), 96)  # each outer point paired with the stage edge in its direction
                    e1, e2 = S.basis(ax)
                    ang = lambda p: math.atan2((p - sc).dot(e2), (p - sc).dot(e1))  # noqa: E731
                    inner = [min(dense, key=lambda q: abs(math.remainder(ang(q) - ang(p), math.tau))) for p in outer]
                    S.band(bm, outer, inner, "wing_web", bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap"))  # one sheet: the structure shader draws both sides
            else:
                # the opening scaled toward the section's centroid (a rib keeps half its section as web, a frame a ring):
                # sections are star-shaped about it, so the opening stays inside. A mitred inset of 22% of the section's
                # extent crossed the opposite skin on thin sections and stood out of it (struts, stages, V-tail tips)
                dense = S.resample(lps[0], max(12, min(64, int(S.length(lps[0]) / 0.12))))
                cc = sum(dense, Vector()) / len(dense)
                outer = S.inset(dense, ax, 0.015)
                inner = [cc + (p - cc) * (0.5 if wingish else 0.82) for p in outer]
                uvl = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
                for k in range(1 if wingish else 2):
                    off = ax * (0.012 * k)
                    S.band(bm, [p + off for p in outer], [p + off for p in inner], "wing_web" if wingish else "body_web", uvl, flip=bool(k))
            if wingish:
                ch, up = frame_axes(ax)
                spar_pts.append(spar_points(loop, c, ch, up, 0.72))
        spars = [bm.faces.new([bm.verts.new(p) for p in (a_bot, a_top, b_top, b_bot)])  # rear spar web, one sheet a bay
                 for (a_top, a_bot), (b_top, b_bot) in zip(spar_pts, spar_pts[1:])]
        if spars:
            trim.apply(bm, spars, ax, "wing_web")
        return bm, up

    # a first build at the estimated count measures what a station really costs here (sections often have fewer points
    # than sectors), then the count that fills the part's budget, no closer than 0.25 m apart
    n = max(2, add // per)
    bm, up = build_stations(n)
    built = sum(len(f.verts) - 2 for f in bm.faces)
    n2 = min(max(n, int(n * add / built)) if built else n, max(2, int((s_hi - s_lo) / 0.25)))
    if n2 > n:
        bm.free()
        bm, up = build_stations(n2)
    out_ = [f for f in bm.faces if not face_inside(f)]
    if out_:  # a station is built inside the skin: what would stand out of it is not built
        report["station_faces_dropped_outside"][name] = len(out_)
        bmesh.ops.delete(bm, geom=out_, context="FACES")
    swept_ = [f for f in bm.faces if in_envelope(f.calc_center_median())]
    if swept_:  # nor where a control surface swings through
        report["station_faces_dropped_in_sweep"][name] = len(swept_)
        bmesh.ops.delete(bm, geom=swept_, context="FACES")
    if bm.faces:
        keep(o, bm, "stations")
        join_into(o, bm, "pass_trim_cut" if wingish else "pass_trim")  # the UVs are the members' own (sections.band)
    else:
        bm.free()

# ---- the stage sleeve (damage3.py): stage 1's top skin seen through an outer-wing hole reads as painted skin, so a dark
# opaque sheet 15 mm over it, fixed to the wing. Round 3 drew it grey and it filled the holes (damage_wing_60hp 2). ----
SLEEVE_RIB_W = 0.02  # the width of a lit rib line on the dark sleeve
for name, stage_name in STAGE_OF.items():
    o, st_o = bpy.data.objects.get(name), bpy.data.objects.get(stage_name)
    if o is None or st_o is None:
        continue
    xs = [(o.matrix_world @ v.co).x for v in o.data.vertices]
    x_lo, x_hi = min(xs), max(xs)
    sb = part_bm(st_o)
    sb.normal_update()
    bmesh.ops.delete(sb, geom=[f for f in sb.faces if f.normal.z < 0.3 or not x_lo <= f.calc_center_median().x <= x_hi], context="FACES")
    sb.normal_update()
    nrm_ = {v: v.normal.copy() for v in sb.verts}
    for v in sb.verts:  # along the skin's normal (straight up, the sloping faces near the stage's edges sank into it),
        # 15 mm or half the gap to the next skin out, where the stage runs closer under the wing's skin than 30 mm
        h_ = ALL_SKIN.ray_cast(v.co + nrm_[v] * 1e-4, nrm_[v], 0.03)
        v.co += nrm_[v] * (0.015 if h_[0] is None else max(0.002, h_[3] / 2))
    NESTED.pop(o.name, None)  # the stage as it now is, its stations built
    nest_ = nested_tree(o)  # no face crossing a skin, or the stage anywhere in its travel (check_tele_clear.py)
    tsb_ = BVHTree.FromBMesh(sb)
    sb.faces.ensure_lookup_table()
    bad_ = {i for i, _ in tsb_.overlap(ALL_SKIN)} | ({i for i, _ in tsb_.overlap(nest_)} if nest_ is not None else set())
    bmesh.ops.delete(sb, geom=[sb.faces[i] for i in bad_], context="FACES")
    report.setdefault("sleeve_faces_dropped_crossing", {})[name] = len(bad_)
    # the owner, 2026-11-23 ("make thin bays dark"): on pass_lining s4 gave it the duct swatch, and through the outer
    # wing's holes it read as brown painted tiles. It goes on the stock sheet's black patch (trim "dark"), with a lit
    # rib line (the flange strip) every truss.RIB_PITCH across the span, so it reads as a dark bay with ribs
    x_ = Vector((1, 0, 0))
    k_ = math.floor(x_lo / TR.RIB_PITCH) + 1
    while k_ * TR.RIB_PITCH < x_hi:
        for edge_x in (k_ * TR.RIB_PITCH - SLEEVE_RIB_W / 2, k_ * TR.RIB_PITCH + SLEEVE_RIB_W / 2):
            geom = sb.verts[:] + sb.edges[:] + sb.faces[:]
            bmesh.ops.bisect_plane(sb, geom=geom, plane_co=x_ * edge_x, plane_no=x_)
        k_ += 1
    uvs_ = sb.loops.layers.uv.get("UVMap") or sb.loops.layers.uv.new("UVMap")
    (du0, du1, dv0, dv1), _, _ = trim.TRIMS["dark"]
    (fu0, fu1, fv0, fv1), _, _ = trim.TRIMS["flange"]
    for f in sb.faces:
        x = f.calc_center_median().x
        rib = abs(x - round(x / TR.RIB_PITCH) * TR.RIB_PITCH) < SLEEVE_RIB_W / 2
        for l in f.loops:  # one flat colour each: the patch's middle, the flange strip's middle
            l[uvs_].uv = ((fu0 + fu1) / 2, (fv0 + fv1) / 2) if rib else ((du0 + du1) / 2, (dv0 + dv1) / 2)
    join_into(o, sb, "pass_trim_cut")

# ---- the stage channels kept clear: everything a part carries inside but its skin (the source's
# own structure, this stage's members, the sleeve) that crosses a telescoping stage nested in it, anywhere in the
# stage's travel, goes (check_tele_clear.py counted about 1,700 such triangle pairs in the outer wings at rest) ----
report["stage_channel_cleared"] = {}
for o in [o for o in bpy.data.objects if o.type == "MESH" and any(s.parent == o and "slide_axis" in s for s in bpy.data.objects)]:
    NESTED.pop(o.name, None)
    nest_ = nested_tree(o)
    if nest_ is None:
        continue
    skin_i = P.slot(o, P.SKIN)
    cb = bmesh.new()
    cb.from_mesh(o.data)
    cb.transform(o.matrix_world)
    cb.faces.ensure_lookup_table()
    inner = [f for f in cb.faces if f.material_index != skin_i]
    vs_, ps_ = [], []
    for f in inner:
        ps_.append(list(range(len(vs_), len(vs_) + len(f.verts))))
        vs_ += [v.co.copy() for v in f.verts]
    gone = sorted({i for i, _ in BVHTree.FromPolygons(vs_, ps_).overlap(nest_)}) if ps_ else []
    report["stage_channel_cleared"][o.name] = len(gone)
    if gone:
        bmesh.ops.delete(cb, geom=[inner[i] for i in gone], context="FACES")
        cb.transform(o.matrix_world.inverted())
        cb.to_mesh(o.data)
    cb.free()
print("S2 stage channels cleared", report["stage_channel_cleared"], flush=True)

P.trace("stage_channels")
# ---- honeycomb cores: every control surface's skin, 5 mm in, facing out ----
for o in list(bpy.data.objects):
    if o.type != "MESH" or not o.name.endswith("_visible") or not o.name.startswith(("flap_", "aileron_", "ruddervator_")):  # not the spoilers: their frame takes the structure slot (skin, structure, core would be three)
        continue
    if "_fairing" in o.name:  # a flap fairing's rear half is no control surface: its core showed as a bright edge in its joint (build 33)
        continue
    bm = part_bm(o)
    skin = P.slot(o, P.SKIN)
    # an aileron's upper half is closed by its inner face on the trim slot (s1_cut.split_aileron): the thickness below
    # is measured to that face too, or the core crossed it and hung in the split, a grid of its walls over the dark
    # inner face whenever the halves opened (build 48)
    bounds = [skin, P.slot(o, "pass_trim_cut")] if o.name.startswith("aileron_") else [skin]
    tree_ = BVHTree.FromPolygons([v.co.copy() for v in bm.verts],
                                 [[v.index for v in f.verts] for f in bm.faces if f.material_index in bounds])
    op = bm.faces.layers.int.get("opens")  # the core only under skin a hole can open
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index != skin or (op is not None and not f[op])], context="FACES")
    bm.normal_update()
    # where the surface is thinner than three offsets (the trailing edge) the offset core would cross the opposite skin
    # and stand out past it: drop those faces (a likely cause of round 3's slivers past the aileron's trailing edge)
    thin = [f for f in bm.faces if (h := tree_.ray_cast(f.calc_center_median() - f.normal * 1e-4, -f.normal, 3 * CORE))[0] is not None]
    bmesh.ops.delete(bm, geom=thin, context="FACES")
    bm.normal_update()
    normal = {v: v.normal.copy() for v in bm.verts}
    # a face's centre can pass that test while a corner, offset along a normal that leans through a bound (an aileron's
    # end face meeting its inner face at a slant), lands outside it and crosses the lower half at full split: drop the
    # faces round any offset more than the pass's crossing tolerance (fairing.PEN_M, 1 mm) out
    out = {f for v in bm.verts if (h := tree_.find_nearest(p := v.co - normal[v] * CORE))[0] is not None and (p - h[0]).dot(h[1]) > 0.001
           for f in v.link_faces}
    if out:
        bmesh.ops.delete(bm, geom=list(out), context="FACES")
        bm.normal_update()
        normal = {v: v.normal.copy() for v in bm.verts}
    for v in bm.verts:
        v.co -= normal[v] * CORE
    # a wall from the core's edge back up to the skin, so a hole reaching the core's edge shows its depth
    # (round 3, damage_aileron_0hp 2: the core ended in a straight cut with no side face)
    ext = bmesh.ops.extrude_edge_only(bm, edges=[e for e in bm.edges if e.is_boundary])
    for nv in (g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)):
        src = next((e.other_vert(nv) for e in nv.link_edges if e.other_vert(nv) in normal), None)
        if src is not None:
            nv.co = src.co + normal[src] * CORE * 0.9
    canonical_order(bm)
    hinge = o.parent
    while hinge is not None and hinge.type != "EMPTY":
        hinge = hinge.parent
    span = hinge.matrix_world.col[0].xyz.normalized() if hinge else Vector((1, 0, 0))
    join_into(o, bm, "pass_honeycomb", uv_metres=span)
P.trace("cores")

# ---- the budget, part by part ----
budget = P.budget()
for name, n in sorted(added.items()):
    owner = name.replace("_visible", "")
    want = budget.get(owner, {})
    report["parts"][name] = {"added_tris": n, "budget_structure_closing_core": want.get("structure_add", 0) + want.get("closing", 0) + want.get("core", 0)}
# ---- gate: no member this stage added stands outside the assembled skin of the intact aircraft (once
# structure stood ahead of 371 skin sites on fuselage_F, 728 on Centurion). Every vertex of every member face within PROUD_M
# of the exterior shell or inside it (a six-axis vote on face centres passed members the look saw through the paint) ----
outside = {}
for name, cs in NEW_FACES.items():
    n_out = 0
    labels = {}
    for vs_, lab in cs:
        if any(proud(v) > PROUD_M for v in vs_):
            n_out += 1
            labels[lab.split(" ")[0]] = labels.get(lab.split(" ")[0], 0) + 1
    if n_out:
        outside[name] = (n_out, len(cs), labels)
report["members_outside_skin"] = outside
print("S2 members outside the skin", outside, flush=True)
if outside:
    raise SystemExit(f"s2_structure: members stand outside the skin: {outside}")
report["duplicate_faces"] = P.duplicate_gate("s2_structure", DUP0)
# gate: through the holes, members come first. From every point a hole can open on
# the sampled parts, a ray straight in from 20 mm under the skin; its first hit within 1 m is a member (this stage's
# frames, stations, stringers, spars: pass_trim*) or backing (sleeve, lining, paint, the far skin, inherited plates)
HOLE_GATES = {"wing_outer_L": (0.40, None), "fuselage_R": (0.45, None), "vtail_tip_L": (0.30, 0.10)}
# a member: this stage's frames, stations, stringers and spars, and the source's own structure plates and mechanisms
# (the Darkreach's holes show its mechanical structure the same way); linings, paint, skin and the sleeve are backing
MEMBER_SLOTS = ("pass_trim", "aircraft_structure", "jet_mechanical")
rv_, rp_, rm_ = [], [], []
for ob in [x for x in bpy.data.objects if x.type == "MESH" and not x.hide_render and "_lod1" not in x.name and "_colmesh" not in x.name
           and not x.name.endswith(("_blockout_mesh", "_shape")) and not any(c.name in ("Colliders", "LOD1") for c in x.users_collection)]:
    b_ = len(rv_)
    rv_ += [ob.matrix_world @ v.co for v in ob.data.vertices]
    for p in ob.data.polygons:
        rp_.append([b_ + i for i in p.vertices])
        m_ = ob.data.materials[p.material_index] if ob.data.materials else None
        rm_.append(m_.name if m_ else "")
ALL_TREE = BVHTree.FromPolygons(rv_, rp_)
report["hole_first_hits"], low_holes = {}, {}
for part, (need, near) in HOLE_GATES.items():
    pts = OPEN_POINTS.get(part, [])
    member, depths, n, by = 0, [], 0, {}
    for p, nrm in pts[::max(1, len(pts) // 400)]:
        h = ALL_TREE.ray_cast(p - nrm * 0.02, -nrm, 1.0)
        n += 1
        k_ = "none" if h[0] is None else rm_[h[2]]
        by[k_] = by.get(k_, 0) + 1
        if h[0] is not None and rm_[h[2]].startswith(MEMBER_SLOTS):
            member += 1
            depths.append((h[0] - p).length)
    share = member / max(n, 1)
    depths.sort()
    rec = {"rays": n, "member_first": round(share, 3), "member_depth_median_m": round(depths[len(depths) // 2], 3) if depths else None,
           "nearest_member_m": round(depths[0], 3) if depths else None, "first_hit_by_slot": {k: round(v / n, 3) for k, v in sorted(by.items(), key=lambda kv: -kv[1])[:6]}}
    report["hole_first_hits"][part] = rec
    if share < need or (near is not None and (not depths or depths[0] > near)):
        low_holes[part] = rec
print("S2 hole first hits", report["hole_first_hits"], flush=True)
report["hole_gate"] = "FAIL" if low_holes else "pass"
if low_holes:  # recorded, not stopping the stages after: the review waits on this gate (lead, round 3)
    print("S2 HOLE GATE FAIL: through the holes, members do not come first:", low_holes, flush=True)


# ---- the right engine's structure as the left's mirror ----
# The nacelles leave stage 1 as mirror images, but the members built here for each (a budget spent in order, rays cast
# into each one's own skin) came out different: 336 of nacelle_1's added faces and 438 of nacelle_2's had no mirror
# twin, and from behind the right duct showed members at odd angles the left did not (build 43). nacelle_2's added
# members (every pass_* slot) are replaced by nacelle_1's, mirrored across x = 0.
def mirror_added_members(src, dst):
    def strip(o, keep_pass):
        bm = bmesh.new()
        bm.from_mesh(o.data)
        names = [m.name if m else "" for m in o.data.materials]
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if names[f.material_index].startswith("pass_") != keep_pass], context="FACES")
        return bm
    bm = strip(dst, False)
    bm.to_mesh(dst.data)
    bm.free()
    twin = bpy.data.objects.new(dst.name + "__mirror", src.data.copy())
    bpy.context.scene.collection.objects.link(twin)
    bm = strip(twin, True)
    to_dst = dst.matrix_world.inverted() @ Matrix.Scale(-1, 4, Vector((1, 0, 0))) @ src.matrix_world
    bmesh.ops.transform(bm, matrix=to_dst, verts=bm.verts)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)  # the mirror turned every face inside out
    bm.to_mesh(twin.data)
    bm.free()
    twin.matrix_world = dst.matrix_world.copy()
    with bpy.context.temp_override(active_object=dst, selected_editable_objects=[dst, twin]):
        bpy.ops.object.join()


mirror_added_members(bpy.data.objects["nacelle_1"], bpy.data.objects["nacelle_2"])
print("S2 nacelle_2's added members: nacelle_1's, mirrored", flush=True)

# structure per part as the Darkreach counts it (every triangle not skin, glass or a light), against its density
NOT_STRUCTURE = (P.SKIN, "glass", "light_")
per_part, tot_s, tot_full = {}, 0, 0.0
for name, f in full.items():
    o = bpy.data.objects.get(name) or bpy.data.objects.get(name + "_visible")
    if o is None:
        continue
    me = o.data
    s = sum(len(p.vertices) - 2 for p in me.polygons
            if not (me.materials and me.materials[p.material_index] and me.materials[p.material_index].name.startswith(NOT_STRUCTURE)))
    per_part[name] = {"structure_tris": s, "darkreach_density_tris": int(f), "share": round(s / f, 3) if f else None}
    tot_s, tot_full = tot_s + s, tot_full + f
report["structure_per_part"] = per_part
report["darkreach_structure_share"] = round(tot_s / tot_full, 3) if tot_full else None
print("S2 structure", tot_s, "triangles,", report["darkreach_structure_share"], "of the Darkreach's density", flush=True)
P.finish(ctx, report)
