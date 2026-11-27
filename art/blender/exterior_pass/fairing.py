"""The flap fairings on their own hinges (the variant: variant.json "fairing_hinges", on in the shipped aircraft; off,
the fairings stay whole on the flaps). For each fairing with a pivot in baselines/fairing_hinges.json (each pivot the
point about which the rear half clears the fixed half through the flap's travel, found once by search), stage 1 builds:
  - the rear half out of its flap's mesh into `<flap>_fairing<k>_visible`, under a new hinge empty `<flap>_fairing<k>`
    at the pivot whose local X is the flap's hinge axis (the game turns it through the flap's own angle: a second
    ControlSurface on the flap's part, EXPORT.md section 2), parented where the flap's hinge is;
  - its open rim (where it met the flap's underside and sleeved over the fixed half) capped;
  - the flap's underside collar round the rear half's top (it wrapped the fairing, and hung under the flap once the
    rear half swung away) removed, and the opening closed flat;
  - the fixed front half cut square where the rear half begins at rest (its tail ran on inside the rear half) and capped.
  - the rear half telescoped (telescope()): its part ahead of MOUTH_F, under the wing, joins the fixed half as a shroud
    lined inside, and a sleeve SLEEVE_IN_M slimmer than the shroud runs forward from the rear half's front inside it, so
    as the rear half slides aft along the flap the joint stays closed.
New faces take their neighbours' paint class and group (s1_cut.copy_attrs_from_neighbours), so s4 lays their UVs and s6
paints them as the fairing's and flap's own. Stage 6 bakes the FLAP and FAIRING texels' occlusion a second time with
the flaps and fairings down, each texel taking the lighter (their faces that touch at rest baked black).
trim() then cuts each rear half (sleeve included) to clear its flap and the shroud at every angle. gate(), at the end of
stage 1, holds the motion: every 1 degree to 30, no rear half passes more than PEN_M into its flap, the other flaps and
fairings, the fixed wing (shroud and lining among it), the aileron or the spoiler, either way; its top stays within
TOP_GAP_M of its flap; its sleeve stays inside the shroud (the owner's build 33: "flap fairings are floating", then a
render with the rear half through its flap at 30 degrees; check_travel never looked at a gap or at a flap against its
own fairings)."""
import json
import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

import pass_common as P

COLLAR_REACH, COLLAR_FLAT = 0.04, 0.85  # flap faces this close to the rear half, and not this square to the flap's underside
# The rear half is every loose part of the flap mesh inside the fairing's box, not only the part its pivot row names:
# a piece of the fairing that is its own loose part (stage 3's inward twins are) stayed on the flap in the owner's
# picture and showed as thin slivers where the tail had been (2026-11-24). INSIDE_M is how far outside the box a piece
# may reach and still be the fairing's.
INSIDE_M = 0.02
LEFTOVER_IN_M = 0.03  # leftovers() looks this far inside the fairing's rest box (its edges touch the flap's caps)
CUT_GAP = 0.005  # the fixed half ends this far ahead of the rear half's front (flush, check_travel saw them touch at 0)
FAIRING_CLS = 18  # art/blender/m4/wing.py FAIRING, the paint class of every flap-track fairing's skin
WING_SKIN_CLS = 11  # art/blender/m4/wing.py WING, the wing's own skin, which the front-half cut takes only over a shroud
SHROUD_LAP_M = 0.02  # how far that skin runs on under a shroud's side
FAIRING_BELOW = 0.05  # the front-half cut takes faces this far below the rear half's top (the wing's lower skin) and lower
# The telescope, in the flap hinge's frame (Frame): the shroud's mouth at the flap hinge's station, where the wing's lower
# skin ends at the cove; the sleeve ends SLEEVE_SHORT_M aft of the rear half's front (short of the shroud's narrowing nose,
# which its rising front would meet), stands
# SLEEVE_IN_M inside the shroud's skin, and the lining LINING_IN_M inside it.
MOUTH_F, SLEEVE_SHORT_M, SLEEVE_IN_M, LINING_IN_M = 0.0, 0.33, 0.02, 0.003
RING_M = 0.18  # the sleeve's sections
SLEEVE_CLEAR_M = 0.01  # trim(): the sleeve's clearance inside the shroud (its faces span the walls' curve)
MOUTH_HOLD_M = 0.30  # trim(): how far out of the mouth the sleeve still keeps to its section
LINING = "pass_lining"
# carried(): the poses; the top edge's limits off the flap's lower skin either way; how far inside the mouth the
# sleeve's front must stay
POSES = list(range(0, 31, 1))
TOP_GAP_M, SLEEVE_INSIDE_M = 0.06, 0.01
# trim(): the least clearance a rear half keeps to its flap and to the fixed wing at every angle (the line between them
# reads as a seam, and the gate's 1 mm has room), checked every TRIM_STEP_DEG
CLEAR_M, TRIM_STEP_DEG = 0.007, 0.5


class Frame:
    """A flap's hinge frame: f forward of the hinge, u up from it, both across the hinge axis."""

    def __init__(self, flap):
        self.flap = flap
        self.H = flap.matrix_world.translation.copy()
        self.ax = flap.matrix_world.col[0].xyz.normalized()
        fwd = self.ax.cross(Vector((0, 0, 1))).normalized()
        self.fwd = fwd if fwd.y < 0 else -fwd
        up = self.ax.cross(self.fwd).normalized()
        self.up = up if up.z > 0 else -up
        vis = bpy.data.objects[flap.name + "_visible"]
        te = min((vis.matrix_world @ v.co for v in vis.data.vertices), key=self.f)
        self.down = 1 if (Matrix.Rotation(math.radians(10), 3, self.ax) @ (te - self.H)).dot(self.up) < (te - self.H).dot(self.up) else -1
        self.tree = BVHTree.FromPolygons([vis.matrix_world @ v.co for v in vis.data.vertices], [list(p.vertices) for p in vis.data.polygons])

    def f(self, p):
        return (p - self.H).dot(self.fwd)

    def u(self, p):
        return (p - self.H).dot(self.up)


def turn(fr, P, deg):
    """About the hinge axis through P, by deg of trailing edge down."""
    return Matrix.Translation(P) @ Matrix.Rotation(math.radians(fr.down * deg), 4, fr.ax) @ Matrix.Translation(-P)


def sleeve_front(fr, rear, telescoped=True):
    """The rear half's front: its section 2 mm behind its foremost point and every vertex ahead of that (the sleeve's
    front once telescope() has run); before it, the section where the sleeve's front will be. A section, since the
    rear half's top cap has no vertices along most of its length."""
    vs = [rear.matrix_world @ v.co for v in rear.data.vertices]
    at = max(fr.f(p) for p in vs) - (0.002 if telescoped else SLEEVE_SHORT_M)
    out = [p for p in vs if fr.f(p) >= at]
    for e in rear.data.edges:
        a, b = (vs[i] for i in e.vertices)
        fa, fb = fr.f(a), fr.f(b)
        if (fa - at) * (fb - at) < 0:
            out.append(a.lerp(b, (at - fa) / (fb - fa)))
    return out


PEN_M = 0.001  # the gate: a rear half and anything round it may pass through each other by no more than this


def _tris(objs, pose, skip_lining=False):
    """The objects' triangles posed by pose(obj), world space: (vertices, triangles, (object, vertex) per vertex)."""
    vs, ts, own = [], [], []
    for n, o in enumerate(objs):
        me = o.data
        me.calc_loop_triangles()
        mw = pose(o) @ o.matrix_world
        lining = {i for i, m in enumerate(me.materials) if m and m.name == LINING} if skip_lining else set()
        b = len(vs)
        vs += [mw @ v.co for v in me.vertices]
        own += [(n, i) for i in range(len(me.vertices))]
        ts += [tuple(b + i for i in lt.vertices) for lt in me.loop_triangles if lt.material_index not in lining]
    return vs, ts, own


RAYS = (Vector((0.0, 0.0, 1.0)), Vector((0.31, 0.53, -0.79)).normalized(), Vector((-0.67, 0.41, 0.62)).normalized())


def _inside(tree, p):
    """How deep p lies inside the closed surface in tree, 0 outside: the nearest face has p behind it and the crossings
    along at least two of three rays are odd."""
    q, n, _, d = tree.find_nearest(p, 1.0)
    if q is None or (p - q).dot(n) >= 0:
        return 0.0
    odd = 0
    for r in RAYS:
        k, x = 0, p.copy()
        for _ in range(32):
            h = tree.ray_cast(x, r, 60.0)
            if h[0] is None:
                break
            k, x = k + 1, h[0] + r * 1e-5
        odd += k % 2
    return d if odd >= 2 else 0.0


def _deepest(T, tree):
    """The deepest of triangle T's sample points (about 2 cm apart) inside the solid in tree."""
    n = min(15, max(1, int(max((T[1] - T[0]).length, (T[2] - T[0]).length, (T[2] - T[1]).length) / 0.02)))
    return max(_inside(tree, T[0] + (T[1] - T[0]) * (i / n) + (T[2] - T[0]) * (j / n)) for i in range(n + 1) for j in range(n + 1 - i))


def _crossings(av, at, bv, bt):
    """Triangles of a and of b that pass through each other by more than PEN_M: (a index, b index, depth, b normal),
    the depth that of the deepest sample of either inside the other's solid."""
    out = []
    ta, tb = BVHTree.FromPolygons(av, at), BVHTree.FromPolygons(bv, bt)
    for i, j in ta.overlap(tb):
        A, B = [av[k] for k in at[i]], [bv[k] for k in bt[j]]
        nb = (B[1] - B[0]).cross(B[2] - B[0])
        if nb.length == 0 or (A[1] - A[0]).cross(A[2] - A[0]).length == 0:
            continue
        depth = max(_deepest(A, tb), _deepest(B, ta))
        if depth > PEN_M:
            out.append((i, j, depth, nb.normalized()))
    return out


def _poser(frames, piv, flaps):
    """pose_of(obj, deg): the matrix that turns obj with its flap or fairing hinge to deg (identity for fixed parts)."""
    def pose_of(o, d):
        h = o.parent
        while h is not None and h.type != "EMPTY":
            h = h.parent
        if h is not None and h.get("fairing_of"):
            return turn(frames[h["fairing_of"]], piv[h.name], d)
        if h is not None and h.name in flaps:
            return turn(frames[h.name], frames[h.name].H, d)
        return Matrix.Identity(4)
    return pose_of


def penetration(poses):
    """Per built fairing, the worst depth (m) and flap angle at which its rear half (sleeve included) and each neighbour
    pass through each other, every flap and fairing at the pose's angle: its own flap, the side's other flaps and
    fairings, the fixed wing (the shroud and its lining among it), the aileron and the spoiler at rest; with where on
    the rear half at rest (f, u in its flap hinge's frame)."""
    fairs = sorted((o for o in bpy.data.objects if o.get("fairing_of")), key=lambda o: o.name)
    flaps = {o.name: o for o in bpy.data.objects if o.name.startswith("flap_") and o.type == "EMPTY" and not o.get("fairing_of")
             and bpy.data.objects.get(o.name + "_visible") is not None}
    frames = {n: Frame(f) for n, f in flaps.items()}
    pose_of = _poser(frames, {e.name: e.matrix_world.translation.copy() for e in fairs}, flaps)
    out = {}
    for e in fairs:
        side = e["fairing_of"][5]
        rear = next(c for c in e.children if c.type == "MESH")
        fr = frames[e["fairing_of"]]
        groups = {"own flap": [bpy.data.objects[e["fairing_of"] + "_visible"]],
                  "other flaps": [bpy.data.objects[n + "_visible"] for n in flaps if n[5] == side and n != e["fairing_of"]],
                  "other fairings": [next(c for c in o.children if c.type == "MESH") for o in fairs if o is not e and o["fairing_of"][5] == side],
                  "fixed wing": [bpy.data.objects[n + side] for n in ("wing_root_", "wing_outer_", "wing_tele1_", "wing_tele2_") if n + side in bpy.data.objects],
                  "aileron": [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("aileron_" + side + "_visible")],
                  "spoiler": [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("spoiler_" + side) and "_lod1" not in o.name and "_colmesh" not in o.name]}
        res = {}
        for d in poses:
            av, at, _ = _tris([rear], lambda o: pose_of(o, d), skip_lining=True)
            back = pose_of(rear, d).inverted()
            for k, objs in groups.items():
                if not objs:
                    continue
                bv, bt, _ = _tris(objs, lambda o: pose_of(o, d))
                for i, _j, depth, _n in _crossings(av, at, bv, bt):
                    if depth > res.get(k, (0.0,))[0]:
                        c = back @ (sum((av[x] for x in at[i]), Vector()) / 3)
                        res[k] = (depth, d, round(fr.f(c), 2), round(fr.u(c), 2))
        out[rear.name] = {k: {"depth_m": round(v[0], 4), "deg": v[1], "rest_f_u": v[2:]} for k, v in res.items()}
    return out


def variant_on():
    p = Path(__file__).resolve().parent / "variant.json"
    return p.exists() and json.loads(p.read_text()).get("fairing_hinges", False)


def _parts(bm):
    bm.verts.ensure_lookup_table()
    seen, parts = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, part = [v], set()
        seen.add(v.index)
        while stack:
            a = stack.pop()
            part.add(a.index)
            for e in a.link_edges:
                b = e.other_vert(a)
                if b.index not in seen:
                    seen.add(b.index)
                    stack.append(b)
        parts.append(part)
    return parts


def _box(pts, grow):
    return ([min(p[i] for p in pts) - grow for i in range(3)], [max(p[i] for p in pts) + grow for i in range(3)])


def _within(co, box):
    return all(box[0][i] <= co[i] <= box[1][i] for i in range(3))


def _fairing_set(bm, parts, seed, box):
    """The seed part with every other loose part lying wholly inside box: the whole fairing, whatever its pieces."""
    out = set(seed)
    for p in parts:
        if p is not seed and all(_within(bm.verts[i].co, box) for i in p):
            out |= p
    return out


def _cap(bm, edges, skin_i, copy_attrs, facing=None):
    caps = P.fill_holes(bm, edges)
    if caps:  # (a cap as one n-gon draws as a fan of slivers: their stretched UVs pulled wing_root's density p5 under its floor)
        caps = bmesh.ops.triangulate(bm, faces=caps, quad_method="BEAUTY", ngon_method="BEAUTY")["faces"]
    for f in caps:
        f.material_index = skin_i
    bm.normal_update()
    if facing is not None:
        for f in caps:
            if f.normal.dot(facing(f)) < 0:
                f.normal_flip()
    copy_attrs(bm, caps)
    _own_uvs(bm, caps)
    return caps


def _own_uvs(bm, faces):
    """UVs off the atlas and unique to each corner's position, so s4 takes each face as an owner and unwraps it. A fill
    leaves zero UVs, and s4 made every such face a copy of the first one it met, anywhere on the aircraft."""
    uv = bm.loops.layers.uv.get("UVMap")
    if uv is not None:
        for f in faces:
            for lp in f.loops:
                c = lp.vert.co
                lp[uv].uv = (3.0 + c.x * 0.01 + c.z * 0.0037, 3.0 + c.y * 0.01 + c.z * 0.0011)


def _skin_top(rb, fr, skin_i):
    """The rear half's top (where it met the flap and the wing, made as structure the neighbour hid) painted as its
    skin: it rides CLEAR_M under the flap now, in sight."""
    rb.normal_update()
    top = max(fr.u(v.co) for v in rb.verts)
    cls, group = rb.faces.layers.int.get("cls"), rb.faces.layers.int.get("paint_group")
    skin = [f for f in rb.faces if f.material_index == skin_i]
    faces = [f for f in rb.faces if f.material_index != skin_i and f.normal.dot(fr.up) > 0.7 and fr.u(f.calc_center_median()) > top - 0.08]
    for f in faces:
        f.material_index = skin_i
        if cls is not None and skin:
            f[cls] = FAIRING_CLS
        if group is not None and skin:
            f[group] = skin[0][group]
    _own_uvs(rb, faces)


def telescope(rb, fr, copy_attrs, skin_i, lining_i):
    """The rear half (rb, world space) split at the mouth: rb keeps the part aft of it, capped at the cut, and gains the
    sleeve (a copy of the part ahead, SLEEVE_IN_M in, from the cap to SLEEVE_SHORT_M short of its front, capped there);
    the part ahead and its lining (LINING_IN_M in, facing inward, slot lining_i) come back as a new bmesh for the fixed
    half. rb is lined the same way."""
    role = rb.faces.layers.int.new("telescope")
    sleeve_end = max(fr.f(v.co) for v in rb.verts) - SLEEVE_SHORT_M
    # and sections along the body (and below, the sleeve), so trim() has vertices to move where it moves them unevenly
    # (the caps are fans of slivers the length of the part)
    body_rings = [MOUTH_F - 0.08, MOUTH_F - 0.15, MOUTH_F - 0.25, MOUTH_F - 1.2, MOUTH_F - 1.6, MOUTH_F - 2.0]
    for at in [MOUTH_F - CUT_GAP, MOUTH_F, sleeve_end] + body_rings:
        bmesh.ops.bisect_plane(rb, geom=list(rb.verts) + list(rb.edges) + list(rb.faces), plane_co=fr.H + fr.fwd * at, plane_no=fr.fwd)
    fc = {f: fr.f(f.calc_center_median()) for f in rb.faces}
    bmesh.ops.delete(rb, geom=[f for f in rb.faces if MOUTH_F - CUT_GAP <= fc[f] <= MOUTH_F], context="FACES")
    ahead = [f for f in rb.faces if fc[f] > MOUTH_F]
    for f in rb.faces:
        f[role] = 1 if fc[f] < MOUTH_F else 2

    def copy(faces, tag, inset):
        geom = list(dict.fromkeys(v for f in faces for v in f.verts)) + list(dict.fromkeys(e for f in faces for e in f.edges)) + faces
        new = [g for g in bmesh.ops.duplicate(rb, geom=geom)["geom"] if isinstance(g, bmesh.types.BMFace)]
        for f in new:
            f[role] = tag
        rb.normal_update()
        moved = list(dict.fromkeys(v for f in new for v in f.verts))
        normals = [v.normal.copy() for v in moved]
        for v, n in zip(moved, normals):
            v.co -= n * inset
        return new, moved

    sleeve, sv = copy([f for f in ahead if fc[f] < sleeve_end], 3, SLEEVE_IN_M)
    for v in sv:  # its back rim onto the body's cap
        if v.is_boundary and fr.f(v.co) < MOUTH_F + 0.03:
            v.co += fr.fwd * (MOUTH_F - CUT_GAP - fr.f(v.co))
    for at in [MOUTH_F + 0.06] + [MOUTH_F + k * RING_M for k in range(1, 20) if MOUTH_F + k * RING_M < sleeve_end - 0.05]:
        bmesh.ops.bisect_plane(rb, geom=list(dict.fromkeys(v for f in sleeve for v in f.verts)) + list(dict.fromkeys(e for f in sleeve for e in f.edges)) + sleeve,
                               plane_co=fr.H + fr.fwd * at, plane_no=fr.fwd)
        sleeve = [f for f in rb.faces if f[role] == 3]
    _own_uvs(rb, sleeve)
    lining, _ = copy(ahead, 4, LINING_IN_M)
    bmesh.ops.reverse_faces(rb, faces=lining)
    for f in lining:
        f.material_index = lining_i
    body_cut = [e for e in rb.edges if e.is_boundary and e.link_faces[0][role] == 1]
    for f in _cap(rb, body_cut, skin_i, copy_attrs, facing=lambda f: fr.fwd):
        f[role] = 1
    sleeve_cut = [e for e in rb.edges if e.is_boundary and e.link_faces[0][role] == 3 and min(fr.f(v.co) for v in e.verts) > sleeve_end - 0.05]
    for f in _cap(rb, sleeve_cut, skin_i, copy_attrs, facing=lambda f: fr.fwd):
        f[role] = 3
    # the rear half lined too: what a hole in it looks onto (s2 gives a fairing no honeycomb core)
    inner, _ = copy([f for f in rb.faces if f[role] in (1, 3)], 1, LINING_IN_M)
    bmesh.ops.reverse_faces(rb, faces=inner)
    for f in inner:
        f.material_index = lining_i
    shroud = rb.copy()
    srole = shroud.faces.layers.int.get("telescope")
    bmesh.ops.delete(shroud, geom=[f for f in shroud.faces if f[srole] in (1, 3)], context="FACES")
    bmesh.ops.delete(rb, geom=[f for f in rb.faces if f[role] in (2, 4)], context="FACES")
    rb.faces.layers.int.remove(role)
    shroud.faces.layers.int.remove(srole)
    return shroud, {"shroud_faces": len(ahead), "sleeve_faces": len(sleeve), "lining_faces": len(lining), "sleeve_end_f": round(sleeve_end, 3)}


def _join(host, bm, materials):
    """The bmesh (world space, slots as materials) joined into host, its materials matched or added by the join."""
    me = bpy.data.meshes.new(host.name + "_shroud")
    bm.to_mesh(me)
    bm.free()
    for m in materials:
        me.materials.append(m)
    tmp = bpy.data.objects.new(me.name, me)
    for c in host.users_collection:
        c.objects.link(tmp)
    with bpy.context.temp_override(active_object=host, object=host, selected_objects=[host, tmp], selected_editable_objects=[host, tmp]):
        bpy.ops.object.join()


def build(row, copy_attrs):
    """One fairing; returns its report row. bms are in world space and written back."""
    flap, k = row["flap"], row["part"]
    hinge, vis = bpy.data.objects[flap], bpy.data.objects[flap + "_visible"]
    host = bpy.data.objects[f"wing_root_{flap[5]}"]
    pivot, axis = Vector(row["pivot_world"]), Vector(row["axis_world"])
    skin_f = P.slot(vis, P.SKIN)
    bm = bmesh.new()
    bm.from_mesh(vis.data)
    bm.transform(vis.matrix_world)
    parts = _parts(bm)
    bm.verts.ensure_lookup_table()
    box = _box([bm.verts[i].co for i in parts[k]], INSIDE_M)
    rear = _fairing_set(bm, parts, parts[k], box)
    anchor = min(parts[k])
    rear_faces = [f for f in bm.faces if all(v.index in rear for v in f.verts)]
    rtree = BVHTree.FromPolygons([v.co.copy() for v in bm.verts], [[v.index for v in f.verts] for f in rear_faces])
    rpts = [bm.verts[i].co.copy() for i in rear]
    y_cut, top_z = min(p.y for p in rpts) - CUT_GAP, max(p.z for p in rpts)
    x_lo, x_hi = min(p.x for p in rpts), max(p.x for p in rpts)
    bm.normal_update()
    others = [f for f in bm.faces if not all(v.index in rear for v in f.verts)]
    ring = [f for f in others if 0.04 < (rtree.find_nearest(f.calc_center_median(), 0.4)[3] or 9) < 0.4 and f.normal.z < -0.5]
    under = sum((f.normal for f in ring), Vector()).normalized() if ring else Vector((0, 0, -1))
    # the collar is the fairing's own: within its span (the flap's trailing-edge face, one face along most of the span
    # where a fairing's tail reaches it, went too and left the flap open there, the owner's "hole" in build 33)
    span = hinge.matrix_world.col[0].xyz.normalized()
    s_lo, s_hi = min(p.dot(span) for p in rpts) - INSIDE_M, max(p.dot(span) for p in rpts) + INSIDE_M
    collar = [f for f in others if rtree.find_nearest(f.calc_center_median(), COLLAR_REACH)[0] is not None and f.normal.dot(under) < COLLAR_FLAT
              and all(s_lo <= v.co.dot(span) <= s_hi for v in f.verts)]
    bmesh.ops.delete(bm, geom=collar, context="FACES_ONLY")
    rim = [e for e in bm.edges if e.is_boundary and not all(v.index in rear for v in e.verts)
           and rtree.find_nearest(e.verts[0].co, 0.1)[0] is not None]
    flap_caps = _cap(bm, rim, skin_f, copy_attrs, facing=lambda f: under)
    # the rear half's own open rim
    rim_r = [e for e in bm.edges if e.is_boundary and all(v.index in rear for v in e.verts)]
    rc = sum(rpts, Vector()) / len(rpts)
    rear_caps = _cap(bm, rim_r, skin_f, copy_attrs, facing=lambda f: f.calc_center_median() - rc)
    # out of the flap's mesh into its own
    bm.verts.ensure_lookup_table()
    parts = _parts(bm)
    rear = _fairing_set(bm, parts, next(p for p in parts if anchor in p), box)  # the caps joined some pieces; take them all again
    pieces = sum(1 for p in parts if p <= rear)
    rb = bm.copy()
    rb.verts.ensure_lookup_table()
    bmesh.ops.delete(rb, geom=[v for v in rb.verts if v.index not in rear], context="VERTS")
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in rear], context="VERTS")
    bm.transform(vis.matrix_world.inverted())
    bm.to_mesh(vis.data)
    bm.free()
    empty = bpy.data.objects.new(f"{flap}_fairing{k}", None)
    for c in hinge.users_collection:
        c.objects.link(empty)
    rot = hinge.matrix_world.to_3x3().normalized()
    empty.matrix_world = Matrix.Translation(pivot) @ rot.to_4x4()
    empty.parent = hinge.parent
    empty.matrix_parent_inverse = hinge.parent.matrix_world.inverted() if hinge.parent else Matrix.Identity(4)
    empty.matrix_world = Matrix.Translation(pivot) @ rot.to_4x4()
    empty["fairing_of"] = flap
    empty["telescoped"] = True
    lining = bpy.data.materials.get(LINING) or bpy.data.materials.new(LINING)
    fr = Frame(hinge)
    _skin_top(rb, fr, skin_f)
    shroud, scope = telescope(rb, fr, copy_attrs, skin_f, len(vis.data.materials))
    me = bpy.data.meshes.new(f"{flap}_fairing{k}_visible")
    rb.transform(vis.matrix_world.inverted())
    rb.to_mesh(me)
    rb.free()
    for m in list(vis.data.materials) + [lining]:
        me.materials.append(m)
    obj = bpy.data.objects.new(me.name, me)
    for c in vis.users_collection:
        c.objects.link(obj)
    obj.parent = empty
    obj.matrix_parent_inverse = empty.matrix_world.inverted()
    obj.matrix_world = vis.matrix_world.copy()
    # the fixed front half cut square where the rear half begins
    skin_h = P.slot(host, P.SKIN)
    hb = bmesh.new()
    hb.from_mesh(host.data)
    hb.transform(host.matrix_world)
    # only the fairing, below the wing's lower skin (to top_z + 0.02 the zone took the wing root's own lower skin and
    # cove aft of the cut too: 165 to 232 faces a fairing, holes the flaps showed through)
    under_wing = top_z - FAIRING_BELOW
    cls_ = hb.faces.layers.int.get("cls")
    # and the fairing's own skin above that line, where it meets the wing: left whole there, the rim's top ended in steps
    low = lambda f: f.calc_center_median().z < under_wing or (cls_ is not None and f[cls_] == FAIRING_CLS)  # noqa: E731
    zone = [f for f in hb.faces if x_lo - 0.05 <= f.calc_center_median().x <= x_hi + 0.05 and low(f)
            and abs(f.calc_center_median().y - y_cut) < 1.5]
    geom = list(dict.fromkeys(v for f in zone for v in f.verts)) + list(dict.fromkeys(e for f in zone for e in f.edges)) + zone
    cut = bmesh.ops.bisect_plane(hb, geom=geom, plane_co=Vector((0, y_cut, 0)), plane_no=Vector((0, 1, 0)))
    cut_e = [e for e in cut["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    in_zone = lambda f: (x_lo - 0.05 <= f.calc_center_median().x <= x_hi + 0.05 and low(f)  # noqa: E731
                         and y_cut < f.calc_center_median().y < y_cut + 1.5)
    # The wing's own skin only over the shroud: at flap 1 the root's lower skin lies 1 mm under under_wing, and its faces
    # 0.45 m wide went whole from x_lo - 0.05, the shroud's inboard wall standing at x 4.10 (a 12 cm by 1 m slot, daylight
    # through it). Each is cut SHROUD_LAP_M inside the shroud's sides (its walls lean in toward the top: cut at its widest,
    # a 1 cm slit stayed at the skin); the piece between goes.
    is_wing = lambda f: cls_ is not None and f[cls_] == WING_SKIN_CLS  # noqa: E731
    b = (min(v.co.x for v in shroud.verts) + SHROUD_LAP_M, max(v.co.x for v in shroud.verts) - SHROUD_LAP_M)
    over = []
    for f in [f for f in hb.faces if is_wing(f) and in_zone(f)]:
        if max(v.co.x for v in f.verts) <= b[0] or min(v.co.x for v in f.verts) >= b[1]:
            continue
        cut_ = [f]
        for xc in b:
            geom = [g for p_ in cut_ if p_.is_valid for g in (*p_.verts, *p_.edges, p_)]
            res = bmesh.ops.bisect_plane(hb, geom=list(dict.fromkeys(geom)), plane_co=Vector((xc, 0, 0)), plane_no=Vector((1, 0, 0)))
            cut_ = [g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)]
        over += [p_ for p_ in cut_ if p_.is_valid and b[0] < p_.calc_center_median().x < b[1]]
    # Only the front half's tail inside the rear half goes: the split between the halves is raked, so a plane at the rear
    # half's foremost point (its top) also took the front half's underside ahead of the split, which nothing replaced
    # (the owner's build 54: a hole 0.2 to 0.55 m ahead of the joint, the canoe's buried top and lining seen through it)
    def inside_rear(f):
        c = f.calc_center_median()
        loc, n, _, _ = rtree.find_nearest(c, 0.6)
        return loc is not None and (c - loc).dot(n) < 0
    gone = list(dict.fromkeys([f for f in hb.faces if in_zone(f) and not is_wing(f) and inside_rear(f)] + over))
    bmesh.ops.delete(hb, geom=gone, context="FACES")
    host_caps = _cap(hb, [e for e in cut_e if e.is_valid and e.is_boundary], skin_h, copy_attrs, facing=lambda f: Vector((0, 1, 0)))
    hb.transform(host.matrix_world.inverted())
    hb.to_mesh(host.data)
    hb.free()
    _join(host, shroud, list(vis.data.materials) + [lining])
    return {"object": obj.name, "hinge": empty.name, "pieces_moved": pieces, "collar_faces": len(collar), "flap_caps": len(flap_caps),
            "rear_caps": len(rear_caps), "front_half_faces_cut": len(gone), "front_half_caps": len(host_caps), **scope}


def _world_tree(objs):
    vs, ps = [], []
    for o in objs:
        mw, b = o.matrix_world, len(vs)
        vs += [mw @ v.co for v in o.data.vertices]
        ps += [[b + i for i in p.vertices] for p in o.data.polygons]
    return BVHTree.FromPolygons(vs, ps)


def trim(e):
    """The rear half under hinge e (sleeve and lining included) cut to keep CLEAR_M off its flap and inside the shroud's
    lining at every angle (every TRIM_STEP_DEG). Against its flap a rear half only translates, by (R^-1 - I)(pivot -
    hinge), which runs off the flap's line by up to 5 cm: each vertex, carried into the flap's rest frame, goes down to
    CLEAR_M under the flap's lower skin above it (and under its trailing edge just ahead). In the shroud the sleeve rises
    and falls: each of its vertices keeps SLEEVE_CLEAR_M inside the side walls (toward the middle along the span: the hinge
    turns about the span, so a vertex keeps its span position), under the ceiling (the lining's, or the
    wing's lower skin where that runs through the shroud) and over the floor (up and down along the rear half's own up),
    each read along a line through it, so no face's winding counts; MOUTH_HOLD_M out of the mouth it keeps to the
    mouth's section. Returns (the most any vertex moved, sleeve vertices squeezed between ceiling and floor)."""
    fr = Frame(bpy.data.objects[e["fairing_of"]])
    piv = e.matrix_world.translation.copy()
    rear = next(c for c in e.children if c.type == "MESH")
    host = bpy.data.objects[f"wing_root_{fr.flap.name[5]}"]
    me, mw = rear.data, rear.matrix_world
    rest = [mw @ v.co for v in me.vertices]
    s_lo, s_hi = min((p - fr.H).dot(fr.ax) for p in rest) - 0.05, max((p - fr.H).dot(fr.ax) for p in rest) + 0.05
    flap_tree = _world_tree([bpy.data.objects[fr.flap.name + "_visible"]])
    hw = host.matrix_world
    hv = [hw @ v.co for v in host.data.vertices]
    lin = {i for i, m in enumerate(host.data.materials) if m and m.name == LINING}
    roof = max(fr.u(p) for p in rest) + 0.02  # the shroud's lining, not the wing's own linings above it
    cavity = [list(p.vertices) for p in host.data.polygons if p.material_index in lin
              and s_lo <= (hw @ p.center - fr.H).dot(fr.ax) <= s_hi and fr.f(hw @ p.center) > MOUTH_F - 0.01 and fr.u(hw @ p.center) < roof]
    lining_tree = BVHTree.FromPolygons(hv, cavity)
    host_tree = _world_tree([host])
    bm = bmesh.new()
    bm.from_mesh(me)
    sleeve = set().union(*(pt for pt in _parts(bm) if min(fr.f(rest[i]) for i in pt) > MOUTH_F - CUT_GAP - 0.002))  # wholly ahead of the cut
    bm.free()
    moved, inward = [0.0] * len(rest), [0.0] * len(rest)  # along the rear half's up; toward its middle along the span
    mid = (s_lo + s_hi) / 2
    walls = set()
    for k in range(int(round(30 / TRIM_STEP_DEG)) + 1):
        d = k * TRIM_STEP_DEG
        mr = turn(fr, piv, d)
        slide = (turn(fr, fr.H, d).inverted() @ mr) @ Vector() - Vector()  # the rear half against its flap
        up = (mr.to_3x3() @ fr.up).normalized()
        for i in range(len(rest)):
            side = 1 if (rest[i] - fr.H).dot(fr.ax) > mid else -1
            p = rest[i] + fr.up * moved[i] - fr.ax * side * inward[i]
            # straight up, and 4 and 8 cm ahead: the flap's trailing edge reaches over a tail tip that has no flap above it
            for ahead in (0.0, 0.04, 0.08):
                h = flap_tree.ray_cast(p + slide + fr.fwd * ahead - fr.up * 0.5, fr.up, 1.0)
                if h[0] is not None:
                    room = (h[0] - (p + slide + fr.fwd * ahead)).dot(fr.up) - CLEAR_M
                    if room < 0:
                        moved[i] += room
                        p = rest[i] + fr.up * moved[i] - fr.ax * side * inward[i]
            w = mr @ p
            if i not in sleeve or fr.f(w) <= MOUTH_F - MOUTH_HOLD_M or not s_lo <= (w - fr.H).dot(fr.ax) <= s_hi:
                continue
            # just out of the mouth, it keeps to the mouth's own section (a face from it to a vertex inside crosses the rim)
            w = w + fr.fwd * max(0.0, MOUTH_F + 0.01 - fr.f(w))
            # the side wall at w's height, from the middle out (the hinge turns about the span, so w's span position is its
            # rest one): in to CLEAR_M inside it
            off = (w - fr.H).dot(fr.ax) - mid
            h = lining_tree.ray_cast(w - fr.ax * off, fr.ax * side, 1.0)
            if h[0] is not None and abs(off) > h[3] - SLEEVE_CLEAR_M:
                inward[i] += abs(off) - (h[3] - SLEEVE_CLEAR_M)
                w = w - fr.ax * side * (abs(off) - (h[3] - SLEEVE_CLEAR_M))
            top = lining_tree.ray_cast(w + fr.up * (0.6 - fr.u(w)), -fr.up, 2.0)  # the lining's ceiling over w, from above
            low = lining_tree.ray_cast(w - fr.up * (2.0 + fr.u(w)), fr.up, 3.0)  # and its floor under w, from below
            if top[0] is None or low[0] is None or fr.u(top[0]) <= fr.u(low[0]):
                continue  # past the shroud's footprint
            roof = host_tree.ray_cast(low[0] + fr.up * 0.002, fr.up, 2.0)  # the wing's lower skin runs through some shrouds
            if roof[0] is not None and fr.u(roof[0]) < fr.u(top[0]):
                top = roof
            over, under = fr.u(w) - (fr.u(top[0]) - SLEEVE_CLEAR_M), (fr.u(low[0]) + SLEEVE_CLEAR_M) - fr.u(w)
            if over > 0 and under > 0:
                walls.add(i)  # squeezed: the shroud is lower there than the sleeve allows
            elif over > 0:
                moved[i] -= over / up.dot(fr.up)
            elif under > 0:
                moved[i] += under / up.dot(fr.up)
    if max(max(abs(m) for m in moved), max(inward)) > 0.4:
        raise SystemExit(f"fairing.trim: {rear.name} would move a vertex {max(max(abs(m) for m in moved), max(inward)):.2f} m")
    lining = {i for i, m in enumerate(me.materials) if m and m.name == LINING}
    inner = {i for p in me.polygons if p.material_index in lining for i in p.vertices}
    skin = [i for i in range(len(rest)) if i not in inner]
    kd = KDTree(len(skin))
    for n_, i in enumerate(skin):
        kd.insert(rest[i], n_)
    kd.balance()
    for i in inner:  # the lining keeps inside its skin: it moves with the skin it lines
        j = skin[kd.find(rest[i])[1]]
        moved[i], inward[i] = moved[j], inward[j]
    inv = mw.inverted()
    for p, m, n, v in zip(rest, moved, inward, me.vertices):
        v.co = inv @ (p + fr.up * m - fr.ax * (1 if (p - fr.H).dot(fr.ax) > mid else -1) * n)
    me.update()
    return max(max(abs(m) for m in moved), max(inward)), len(walls)


def clearance(fr, rear, piv, poses):
    """The rear half's top against its flap: per pose the least distance from its upward faces' samples, where the
    flap is above them, up to the flap's lower skin; returns (least, most) of that over the poses (m)."""
    me = rear.data
    me.calc_loop_triangles()
    mw = rear.matrix_world
    tops = []
    for lt in me.loop_triangles:
        if (mw.to_3x3() @ lt.normal).normalized().dot(fr.up) > 0.5 and me.materials[lt.material_index].name == P.SKIN:
            a, b, c = (mw @ me.vertices[i].co for i in lt.vertices)
            tops += [a + (b - a) * u + (c - a) * w for u, w in ((1 / 3, 1 / 3), (0.1, 0.1), (0.8, 0.1), (0.1, 0.8))]
    lines = []
    for d in poses:
        back = turn(fr, fr.H, d).inverted() @ turn(fr, piv, d)  # into the flap's rest frame
        gaps = [h[3] for h in (fr.tree.ray_cast(back @ p, fr.up, 0.3) for p in tops) if h[0] is not None]
        if gaps:
            lines.append(min(gaps))
    return (min(lines), max(lines)) if lines else (None, None)


def carried():
    """Per built fairing, through POSES: whether its rear half (sleeve included) passes into anything, its top's
    clearance to its flap (least and most over the travel), and how far its foremost part stays ahead of the fixed
    half's aft end (under zero the joint stands open)."""
    out = {}
    pen = penetration(POSES)
    for e in sorted((o for o in bpy.data.objects if o.get("fairing_of")), key=lambda o: o.name):
        fr = Frame(bpy.data.objects[e["fairing_of"]])
        rear = next(c for c in e.children if c.type == "MESH")
        host = bpy.data.objects[f"wing_root_{fr.flap.name[5]}"]
        rv = [rear.matrix_world @ v.co for v in rear.data.vertices]
        s_lo, s_hi = min((p - fr.H).dot(fr.ax) for p in rv), max((p - fr.H).dot(fr.ax) for p in rv)
        top = max(fr.u(p) for p in rv)
        cls = host.data.attributes["cls"].data
        hv = [host.matrix_world @ v.co for v in host.data.vertices]
        fixed = [hv[i] for p in host.data.polygons if cls[p.index].value == FAIRING_CLS for i in p.vertices]
        fixed = [p for p in fixed if s_lo - 0.02 <= (p - fr.H).dot(fr.ax) <= s_hi + 0.02 and fr.u(p) < top - 0.03]
        mouth = min(fr.f(p) for p in fixed)
        P_ = e.matrix_world.translation.copy()
        least, most = clearance(fr, rear, P_, POSES)
        inside = min(fr.f(turn(fr, P_, d) @ p) for d in POSES for p in sleeve_front(fr, rear)) - mouth
        into = {k: v for k, v in pen[rear.name].items() if v["depth_m"] > PEN_M}
        fails = [f"into {k} {v['depth_m'] * 1000:.0f} mm at {v['deg']} deg" for k, v in into.items()]
        fails += [w for w, bad in (("top off the flap", most is None or most > TOP_GAP_M), ("joint open", inside < SLEEVE_INSIDE_M)) if bad]
        out[rear.name] = {"top_clearance_m": [None if least is None else round(least, 3), None if most is None else round(most, 3)],
                          "fixed_aft_f_m": round(mouth, 3), "front_inside_m": round(inside, 3), "penetration": pen[rear.name], "fails": fails}
        print("FAIRING CARRIED", rear.name, out[rear.name], flush=True)
    return out


def leftovers():
    """Per built fairing, the faces of its flap's mesh still inside the fairing's rest box (LEFTOVER_IN_M in from each
    side): what would stay behind on the flap as the fairing swings down. Stages 1 and 3 fail on any."""
    out = {}
    for e in [o for o in bpy.data.objects if o.get("fairing_of")]:
        vis = next((c for c in e.children if c.type == "MESH"), None)
        flap_vis = bpy.data.objects.get(e["fairing_of"] + "_visible")
        if vis is None or flap_vis is None:
            continue
        box = _box([vis.matrix_world @ v.co for v in vis.data.vertices], -LEFTOVER_IN_M)
        mw = flap_vis.matrix_world
        ws = [mw @ v.co for v in flap_vis.data.vertices]
        # wholly inside: the flap's own lower skin runs the span in faces whose centres can land in the fairing's band
        left = [p for p in flap_vis.data.polygons if all(_within(ws[i], box) for i in p.vertices)]
        out[vis.name] = len(left)
        for p in left[:12]:
            m = flap_vis.data.materials[p.material_index]
            print("FAIRING LEFTOVER", vis.name, tuple(round(c, 3) for c in mw @ p.center), "normal",  # what stays, for the log
                  tuple(round(c, 2) for c in (mw.to_3x3() @ p.normal).normalized()), "area_cm2", round(p.area * 1e4, 1),
                  "material", m.name if m else None, "box", [[round(c, 3) for c in b] for b in box], flush=True)
    return out


def build_all(copy_attrs):
    rows = json.loads((P.BASELINES / "fairing_hinges.json").read_text())
    by_flap = {}
    for r in rows:  # a flap's fairings by descending part index, so taking one out leaves the others' indices
        if "pivot_world" in r:
            by_flap.setdefault(r["flap"], []).append(r)
    out = {}
    for flap, rs in by_flap.items():
        for r in sorted(rs, key=lambda r: -r["part"]):
            out[f"{flap}_fairing{r['part']}"] = build(r, copy_attrs)
    for e in sorted((o for o in bpy.data.objects if o.get("fairing_of")), key=lambda o: o.name):
        most, walls = trim(e)
        out[e.name]["trimmed_m"], out[e.name]["trim_walls"] = round(most, 3), walls
    return out


def gate():
    """carried(), stopping the stage on any rear half that fails it."""
    res = carried()
    bad = {k: v["fails"] for k, v in res.items() if v["fails"]}
    if bad:
        raise SystemExit(f"fairing: rear halves not carried through the flap's travel: {bad}")
    return res
