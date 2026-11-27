"""Pass stage 4, UVs: the owner's livery split, one unwrap and pack of the whole exterior at 6 px gutters, copies and
twins given their originals' new UVs, and the pass_* slots mapped onto production materials. UNTESTED as a stage (the
pack itself is test_pack.py's, which ran: 60.0 px/m at 6 px).

- Owners: every skin face whose UVs no earlier face repeats, plus every face of the split parts (the right wing set,
  nacelle_2, the right outboard flap: docs/DECISIONS.md 2026-11-21). Twins (twin_src > 0) are never owners.
- Unwrap: angle based on the marked seams (the cut seams of s1 included), average island scale, concave pack with
  rotation, 3/2048 margin (6 px on the 4096 atlas).
- Copies: a face that repeated an owner's UVs before takes that owner's new UVs, loop by loop, matched by position
  (mirrored across x = 0 for a right-hand copy).
- Twins: their original's UVs, loop by loop, matched by vertex.
- Slots: pass_trim and pass_trim_rail -> Centurion_trim (the stock sheet, opaque), pass_trim_cut -> Centurion_trim_cut
  (the stock sheet, alpha cut at 0.394), pass_honeycomb -> honeycomb (stock), pass_lining / pass_paint / pass_chrome /
  pass_steel -> jet_mechanical on the mod's swatches (duct, fitting, nozzle, spinner).
Writes pass/atlas_record.json (Blender version, a hash of every skin UV) for the atlas guard.

blender --background --python s4_uv.py -- [--force]"""
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402
from export_parts import _degenerate  # noqa: E402

ctx = P.begin("s4_uv", __file__)
ATLAS = 4096
MARGIN = 3 / 2048
SPLIT = ("wing_root_R", "wing_outer_R", "wing_tele1_R", "wing_tele2_R", "nacelle_2", "flap_R2_visible")
SWATCH = {"fitting": 0, "fan": 1, "spinner": 2, "duct": 3, "nozzle": 4, "plug": 5}
centre = lambda r: ((SWATCH[r] % 4 + 0.5) / 4, (SWATCH[r] // 4 + 0.5) / 2)  # noqa: E731 (detail_centurion.mech_trim)
SLOT_MAP = {"pass_trim": ("Centurion_trim", None), "pass_trim_rail": ("Centurion_trim", None), "pass_trim_cut": ("Centurion_trim_cut", None),
            "pass_honeycomb": ("honeycomb", None), "pass_lining": ("jet_mechanical", "duct"), "pass_paint": ("jet_mechanical", "fitting"),
            "pass_chrome": ("jet_mechanical", "nozzle"), "pass_steel": ("jet_mechanical", "spinner")}

objs, _ = P.part_objects()
skin_objs = [(o, {i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN}) for o in objs.values()]
skin_objs = [(o, s) for o, s in skin_objs if s]


def uvs(o):
    me = o.data
    a = [0.0] * (len(me.loops) * 2)
    me.uv_layers["UVMap"].data.foreach_get("uv", a)
    return a


def twin_of(o):
    a = o.data.attributes.get("twin_src")
    if a is None:
        return [0] * len(o.data.polygons)
    v = [0] * len(o.data.polygons)
    a.data.foreach_get("value", v)
    return v


# ---- the roundels' footprints cut out of their skin ----
# The roundels' footprints (art/textures/faction_marks.py PLACEMENTS, read as data: that module needs PIL) are drawn
# MARK_DENSITY times denser: at the skin's 60 px/m a 1.85 m mark's colour edges stair-stepped from 3 m (the owner's tail
# cone shot, build 38). The skin under each is first cut along its box, so only the box is dense and not the whole faces
# under it (70 m2 of them for 22 m2 of box). The faces are triangulated first and each cut splits triangles in their own
# plane, so the skin does not move; a corner within FOOT_SNAP of a cut takes it, so no sliver is left. The atlas floor
# and the packer's density leave the footprints out.
MARK_DENSITY, FOOT_MARGIN, FOOT_SNAP = 1.5, 0.05, 0.02


def footprint_boxes():
    import ast
    src = (P.REPO / "art" / "textures" / "faction_marks.py").read_text()
    start = src.index("PLACEMENTS = (")
    placements = ast.literal_eval(src[src.index("(", start):src.index("\n)", start) + 2])
    return [(part.format(side=s), face, a * (1 if s == "L" else -1), b, width / 2 + FOOT_MARGIN)
            for _, part, face, (a, b), width in placements if face in ("upper", "lower") for s in "LR"]


def in_footprint(ws, n, box, inside):
    """A face (world corners ws, normal n) on the box's side of the skin: its centre inside the box, or any overlap."""
    _, face, cx, cy, half = box
    if not (n.z > 0.3 if face == "upper" else n.z < -0.3):
        return False
    if inside:
        c = sum(ws, Vector()) / len(ws)
        return abs(c.x - cx) < half and abs(c.y - cy) < half
    return min(w.x for w in ws) < cx + half and max(w.x for w in ws) > cx - half and min(w.y for w in ws) < cy + half and max(w.y for w in ws) > cy - half


FOOT_BOXES, FOOT_CUT = footprint_boxes(), {}
for o, slots in skin_objs:
    boxes = [b for b in FOOT_BOXES if b[0] == o.name]
    if not boxes:
        continue
    mw, inv = o.matrix_world, o.matrix_world.inverted()
    names = sorted(a.name for a in o.data.attributes)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    twin = bm.faces.layers.int.get("twin_src")
    n0 = len(bm.faces)
    # as the export will (export_parts.drop_degenerate), so each cut lies in a flat triangle: the skin's quads under a
    # mark are up to 20 mm from flat, and cut whole they would fold along new lines
    bm.normal_update()
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3 and f.material_index in slots and not (twin and f[twin])
                                     and any(in_footprint([mw @ v.co for v in f.verts], mw.to_3x3() @ f.normal, b, False) for b in boxes)],
                          quad_method="BEAUTY", ngon_method="BEAUTY")
    for box in boxes:
        _, _, cx, cy, half = box
        for axis, at in ((Vector((1, 0, 0)), cx - half), (Vector((1, 0, 0)), cx + half), (Vector((0, 1, 0)), cy - half), (Vector((0, 1, 0)), cy + half)):
            bm.normal_update()
            fs = [f for f in bm.faces if f.material_index in slots and not (twin and f[twin])
                  and in_footprint([mw @ v.co for v in f.verts], mw.to_3x3() @ f.normal, box, False)]
            geom = fs + list({e for f in fs for e in f.edges}) + list({v for f in fs for v in f.verts})
            bmesh.ops.bisect_plane(bm, geom=geom, dist=FOOT_SNAP, plane_co=inv @ (axis * at), plane_no=(mw.to_3x3().transposed() @ axis).normalized())
    # the zero-height triangles of quads with three corners in line, which the export drops anyway
    bm.normal_update()
    flat = [f for f in bm.faces if len(f.verts) == 3 and f.material_index in slots and not (twin and f[twin])
            and _degenerate(*(v.co for v in f.verts)) and any(in_footprint([mw @ v.co for v in f.verts], mw.to_3x3() @ f.normal, b, False) for b in boxes)]
    bmesh.ops.delete(bm, geom=flat, context="FACES_ONLY")
    bm.to_mesh(o.data)
    bm.free()
    if sorted(a.name for a in o.data.attributes) != names:
        raise SystemExit(f"s4_uv: cutting {o.name}'s roundel footprints lost attributes")
    FOOT_CUT[o.name] = len(o.data.polygons) - n0
print("S4 roundel footprints cut, new faces", FOOT_CUT, flush=True)

# ---- owners and copies, from today's UVs ----
seen, seen_pos, owners, copies = {}, {}, defaultdict(list), []
order = sorted(skin_objs, key=lambda t: (t[0].name in SPLIT, t[0].name.endswith(("_R", "_R_visible", "_2"))))
for o, slots in order:
    uv = uvs(o)
    tw = twin_of(o)
    mw, me = o.matrix_world, o.data
    # faces by place, left side first: two faces on the same UVs (the aft bay's mirrored rim slivers) gave the texels
    # to the lower face index, which flipped with any change upstream
    for p in sorted(me.polygons, key=lambda p: (lambda c: (-round(c.x, 4), round(c.y, 4), round(c.z, 4), p.index))(mw @ p.center)):
        if p.material_index not in slots or tw[p.index]:
            continue
        key = tuple(sorted((round(uv[2 * li], 5), round(uv[2 * li + 1], 5)) for li in p.loop_indices))
        # a mirrored copy merged alike in s1 keeps its shape but not always its old UVs: matched by position too
        pos = tuple(sorted(tuple(round(c, 3) for c in (abs(w.x), w.y, w.z)) for w in (mw @ me.vertices[v].co for v in p.vertices)))
        uc = (sum(k[0] for k in key) / len(key), sum(k[1] for k in key) / len(key))
        src = seen.get(key)
        if src is None and pos in seen_pos:  # by position only where both already used the same texels (a copy before)
            cand, cuc = seen_pos[pos]
            if abs(cuc[0] - uc[0]) < 0.01 and abs(cuc[1] - uc[1]) < 0.01:
                src = cand
        if src is None or o.name in SPLIT:
            if src is None:
                seen[key] = (o.name, p.index)
                seen_pos[pos] = ((o.name, p.index), uc)
            owners[o.name].append(p.index)
        else:
            copies.append((o.name, p.index, src))

# ---- unwrap and pack ----
# On copies that hold only each part's owner faces (their vertices, edges and seams), so nothing else of the part moves
# the result: packed in the parts themselves, the layout shifted with the structure the stages before add (a truss more
# or less) and the damage pin's parts with it, 3 to 14% ("a check that needs its baseline re-saved
# after every structure change guards nothing"). The UVs go back onto the parts' owner faces after the pack.
PACK_COPY = {}  # part name -> (its copy, the part's polygon index of each copy face)
# the aft bay's side panels wrap its lower corner in one island each; unwrapped whole they stretch to p5 31 px/m (they
# had passed only while stage 1's sliver clean-up tore holes along that corner). Seamed on edges sharper than 25 degrees
# they reach 60; 35 degrees left 48. The wing roots' flap-fairing shrouds, boxes on the underside, had pulled their
# islands to p5 43 px/m (floor 46); seamed the same way, 56
SHARP_SEAM_PARTS, SHARP_SEAM = ("bay_A", "wing_root"), math.radians(25)
# The V-tail's hinge coves are painted dark (m4/tail.py COVE, class 66) on faces that share islands with the light skin
# round them: the paint changed across texels along the diagonal lip and filtered into a saw-tooth dark edge along each
# ruddervator hinge line, seen from 3 m. Seamed into islands of their own, each side's texels end at the lip.
COVE_SEAM_PARTS, TAIL_COVE = ("vtail",), 66
FOOT = {}  # part name -> its copy's face indices inside a roundel's footprint
for o, slots in skin_objs:
    own = owners.get(o.name, [])
    if not own:
        continue
    src = o.data
    suv = src.uv_layers["UVMap"].data
    cb = bmesh.new()
    cuv = cb.loops.layers.uv.new("UVMap")
    vmap = {}
    for pi in own:
        p = src.polygons[pi]
        vs_ = [vmap[vi] if vi in vmap else vmap.setdefault(vi, cb.verts.new(src.vertices[vi].co)) for vi in p.vertices]
        try:
            f = cb.faces.new(vs_)
        except ValueError:  # a second owner face on the same corners (both sides of a thin sheet): its own vertices
            f = cb.faces.new([cb.verts.new(src.vertices[vi].co) for vi in p.vertices])
        for l, li in zip(f.loops, p.loop_indices):
            l[cuv].uv = suv[li].uv
    seam_keys = {e.key for e in src.edges if e.use_seam}
    inv = {bv: vi for vi, bv in vmap.items()}
    for e in cb.edges:
        if e.verts[0] in inv and e.verts[1] in inv:
            e.seam = tuple(sorted((inv[e.verts[0]], inv[e.verts[1]]))) in seam_keys
    if o.name.startswith(SHARP_SEAM_PARTS):
        cb.normal_update()
        for e in cb.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > SHARP_SEAM:
                e.seam = True
    cls_ = src.attributes.get("cls")
    if cls_ is not None and o.name.startswith(COVE_SEAM_PARTS):
        cl = [0] * len(src.polygons)
        cls_.data.foreach_get("value", cl)
        cb.faces.ensure_lookup_table()  # in creation order: the copy's face k is the part's polygon own[k]
        cove = {f: cl[own[k]] == TAIL_COVE for k, f in enumerate(cb.faces)}
        for e in cb.edges:
            if len(e.link_faces) == 2 and cove[e.link_faces[0]] != cove[e.link_faces[1]]:
                e.seam = True
    boxes = [b for b in FOOT_BOXES if b[0] == o.name]
    if boxes:
        cb.normal_update()
        cb.faces.index_update()
        mw_ = o.matrix_world
        sel_ = {f.index for f in cb.faces if any(in_footprint([mw_ @ v.co for v in f.verts], mw_.to_3x3() @ f.normal, b, True) for b in boxes)}
        for e in cb.edges:
            inn = [f.index in sel_ for f in e.link_faces]
            if any(inn) and not all(inn):
                e.seam = True
        FOOT[o.name] = sel_
    cme = bpy.data.meshes.new(o.name + "__pack")
    cb.to_mesh(cme)
    cb.free()
    c = bpy.data.objects.new(o.name + "__pack", cme)
    bpy.context.scene.collection.objects.link(c)
    c.matrix_world = o.matrix_world.copy()
    PACK_COPY[o.name] = (c, list(own))
FOOT_PART = {n: {PACK_COPY[n][1][k] for k in ks} for n, ks in FOOT.items()}  # the same faces by the part's index
print("S4 roundel footprints", {n: len(k) for n, k in FOOT.items()}, flush=True)
SKIN_OBJS_PARTS, OWNERS_PARTS = skin_objs, owners
skin_objs = [(PACK_COPY[o.name][0], {0}) for o, _ in SKIN_OBJS_PARTS if o.name in PACK_COPY]
owners = {c.name: list(range(len(own))) for c, own in PACK_COPY.values()}
for x in bpy.context.view_layer.objects:
    x.select_set(False)
act = None
for o, _ in skin_objs:
    fs = set(owners.get(o.name, ()))
    o.data.polygons.foreach_set("select", [p.index in fs for p in o.data.polygons])
    if fs:
        o.select_set(True)
        act = o
bpy.context.view_layer.objects.active = act
ts = bpy.context.scene.tool_settings
ts.mesh_select_mode = (False, False, True)
ts.use_uv_select_sync = True


SURFACE_PREFIXES, STRETCH_ITERS = ("flap_",), 40  # (on the ruddervators too it put both under their density floor)


def unwrap_owners():
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.0)
    # the flaps' islands relaxed: ABF squeezes their thin trailing edges (flap_L2's least axis sat at the
    # density floor, 47 to 49 px/m on 2 cm2 triangles at the edge, once its nose trim took 100 triangles out of the count)
    keep = {}
    for o in bpy.context.objects_in_mode:
        bm = bmesh.from_edit_mesh(o.data)
        keep[o.name] = [f.select for f in bm.faces]
        on = o.name.startswith(SURFACE_PREFIXES)
        for f in bm.faces:
            f.select_set(f.select and on)
        bmesh.update_edit_mesh(o.data)
    if any(o.name.startswith(SURFACE_PREFIXES) for o in bpy.context.objects_in_mode):
        bpy.ops.uv.minimize_stretch(iterations=STRETCH_ITERS)
    for o in bpy.context.objects_in_mode:
        bm = bmesh.from_edit_mesh(o.data)
        for f, s in zip(bm.faces, keep[o.name]):
            f.select_set(s)
        bmesh.update_edit_mesh(o.data)
    bpy.ops.uv.average_islands_scale()
    for o in bpy.context.objects_in_mode:  # the roundels' footprints drawn MARK_DENSITY times denser
        sel_ = FOOT.get(o.name[:-len("__pack")])
        if not sel_:
            continue
        bm = bmesh.from_edit_mesh(o.data)
        bm.faces.ensure_lookup_table()
        uvl = bm.loops.layers.uv.active
        loops = [l for i in sel_ for l in bm.faces[i].loops]
        cen = sum((l[uvl].uv for l in loops), loops[0][uvl].uv * 0) / len(loops)
        for l in loops:
            l[uvl].uv = cen + (l[uvl].uv - cen) * MARK_DENSITY
        bmesh.update_edit_mesh(o.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    align_islands()


# Each island turned so its part's panel lines run along the texel grid: the body's and engines' along their station
# axis (y), the wings', tail's and control surfaces' along the span (x). The unwrap leaves islands at any angle and the
# pack turned them further (the nozzle's skin 8.5 deg off the grid, the V-tail tips 37): a one-texel line slanting
# across the grid steps from texel to texel, and the core cowl's panel outlines read as drawn by hand.
SPAN_PARTS = ("wing", "vtail", "ruddervator", "flap", "aileron", "spoiler", "strut", "stage")


def uv_islands(faces, uvl):
    """{face: island number}: faces joined by an edge whose two corners match in UV on both sides."""
    island, todo = {}, set(faces)
    k = 0
    while todo:
        stack = [todo.pop()]
        island[stack[0]] = k
        while stack:
            f = stack.pop()
            for lp in f.loops:
                for g_lp in lp.edge.link_loops:
                    g = g_lp.face
                    if g is f or g not in todo:
                        continue
                    a0, a1 = lp[uvl].uv, lp.link_loop_next[uvl].uv
                    b0, b1 = g_lp[uvl].uv, g_lp.link_loop_next[uvl].uv
                    same = (g_lp.vert is lp.vert and (b0 - a0).length < 1e-6 and (b1 - a1).length < 1e-6) or \
                           (g_lp.vert is not lp.vert and (b0 - a1).length < 1e-6 and (b1 - a0).length < 1e-6)
                    if same:
                        todo.discard(g)
                        island[g] = k
                        stack.append(g)
        k += 1
    return island


def align_islands():
    for o, _ in skin_objs:
        own = set(owners.get(o.name, ()))
        if not own:
            continue
        ax = Vector((1, 0, 0)) if o.name.startswith(SPAN_PARTS) else Vector((0, 1, 0))
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        bm.faces.ensure_lookup_table()
        uvl = bm.loops.layers.uv["UVMap"]
        island = uv_islands([f for f in bm.faces if f.index in own], uvl)
        acc = defaultdict(lambda: [0.0, 0.0])
        for f, i in island.items():
            l0, l1, l2 = f.loops[0], f.loops[1], f.loops[2]
            e1, e2 = l1.vert.co - l0.vert.co, l2.vert.co - l0.vert.co
            n = e1.cross(e2)
            if n.length < 1e-12:
                continue
            nn = n.normalized()
            d = ax - nn * ax.dot(nn)
            g = ((e1.dot(e1), e1.dot(e2)), (e1.dot(e2), e2.dot(e2)))
            det = g[0][0] * g[1][1] - g[0][1] * g[1][0]
            if d.length < 0.3 or abs(det) < 1e-18:
                continue
            r1, r2 = d.dot(e1), d.dot(e2)
            s, t = (r1 * g[1][1] - r2 * g[0][1]) / det, (r2 * g[0][0] - r1 * g[1][0]) / det
            duv = (l1[uvl].uv - l0[uvl].uv) * s + (l2[uvl].uv - l0[uvl].uv) * t
            if duv.length < 1e-12:
                continue
            w = f.calc_area() * d.length
            ang = math.atan2(duv.y, duv.x) * 4  # angles mod 90 degrees, averaged on the circle
            acc[i][0] += w * math.cos(ang)
            acc[i][1] += w * math.sin(ang)
        turn = {i: -math.atan2(sv, cv) / 4 for i, (cv, sv) in acc.items() if cv or sv}
        for i, rot in turn.items():
            if abs(rot) < 1e-6:
                continue
            lps = [lp for f, j in island.items() if j == i for lp in f.loops]
            c = sum((lp[uvl].uv for lp in lps), Vector((0.0, 0.0))) / len(lps)
            cr, sr = math.cos(rot), math.sin(rot)
            for lp in lps:
                u = lp[uvl].uv - c
                lp[uvl].uv = c + Vector((u.x * cr - u.y * sr, u.x * sr + u.y * cr))
        bm.transform(o.matrix_world.inverted())
        bm.to_mesh(o.data)
        bm.free()


unwrap_owners()


def owner_density():
    W_ = U_ = 0.0
    for o, _ in skin_objs:
        me, mw = o.data, o.matrix_world
        uv = me.uv_layers["UVMap"].data
        foot = FOOT.get(o.name[:-len("__pack")], ())
        for i in owners.get(o.name, []):
            if i in foot:
                continue
            li = list(me.polygons[i].loop_indices)
            vs = [mw @ me.vertices[me.loops[l].vertex_index].co for l in li]
            for k in range(1, len(li) - 1):
                W_ += ((vs[k] - vs[0]).cross(vs[k + 1] - vs[0])).length / 2
                a, b, c = uv[li[0]].uv, uv[li[k]].uv, uv[li[k + 1]].uv
                U_ += abs((b - a).cross(c - a)) / 2
    return ATLAS * math.sqrt(U_ / W_)


# the same islands packed with a few settings, the densest kept (the 6 px gutter fixed by the owner's decision)
# No free rotation, so the islands keep align_islands' alignment to the texel grid (ANY turned them to any angle):
# quarter turns, or the turn to an island's tightest box, which for these islands is the aligned one (measured: the
# share of skin within 1 and 5 degrees of the grid unchanged; CARDINAL alone packed 57.8 to 60.6 px/m run to run)
VARIANTS = [("AXIS_ALIGNED", "CONCAVE"), ("CARDINAL", "CONCAVE")]


def pack(rot, shape):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.hide(unselected=True)  # only the owners in the edit meshes: the packer's result moved with the parts'
    # other faces (clipping the stages' members out of their own skins left the skin unchanged and took the pack from
    # 59.7 to 59.4 px/m)
    bpy.ops.uv.pack_islands(rotate=True, rotate_method=rot, shape_method=shape, margin_method="FRACTION", margin=MARGIN)
    bpy.ops.mesh.reveal(select=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    return owner_density()


SPLIT_ALL = False  # set when the wings' split alone leaves the pack under the floor: every part's long islands split too


def split_wing_islands():
    """Seam each wing skin's owner faces along the constant-span edge loop nearest its middle, so the long wing islands
    pack as two (the remaining lever short of the gutter), then unwrap again. With SPLIT_ALL, every part over 3 m
    long is split the same way across its longest axis."""
    for o, slots in skin_objs:
        wing = o.name.startswith(("wing_root", "wing_outer", "wing_tele"))
        me, mw = o.data, o.matrix_world
        own = set(owners.get(o.name, ()))
        pts = [mw @ me.vertices[v].co for i in own for v in me.polygons[i].vertices]
        if not pts or not (wing or SPLIT_ALL):
            continue
        ax = 0 if wing else max(range(3), key=lambda a: max(p[a] for p in pts) - min(p[a] for p in pts))
        xs = sorted({round(p[ax], 3) for p in pts})
        if len(xs) < 4 or (not wing and xs[-1] - xs[0] < 3.0):
            continue
        mid = (xs[0] + xs[-1]) / 2
        xc = min(xs, key=lambda x: abs(x - mid))
        edges = {k for i in own for k in me.polygons[i].edge_keys}
        for e in me.edges:
            if e.key in edges and all(abs((mw @ me.vertices[v].co)[ax] - xc) < 0.004 for v in e.vertices):
                e.use_seam = True
    unwrap_owners()


def uv_snapshot():
    snap = {}
    for o, _ in skin_objs:
        a = [0.0] * (2 * len(o.data.loops))
        o.data.uv_layers["UVMap"].data.foreach_get("uv", a)
        snap[o.name] = a
    return snap


SEEN = []  # every pack's (density, layout): the densest is kept, wherever it came from (one machine's split pack
# reached 60.56 and the repacks that followed, each from its own layout, never got back there)


def pack_seen(*v):
    d = pack(*v)
    SEEN.append((d, uv_snapshot()))
    return d


# every part's long islands split, every run: one seam layout. Splitting only when a pack fell short gave the islands a
# different seam layout run to run, and the damage pin's parts moved 7 to 9% with the field unchanged
SPLIT_ALL = True
split_wing_islands()


# The accepted layout (baselines/uv_layout_pin.npz): every island whose faces all match the pin's faces (world centre
# within PIN_TOL on each axis, every corner within PIN_TOL) takes the pinned UVs exactly and is locked; the rest are
# scaled to the pinned islands' texel density and placed round them (place_free). Blender's exact-shape packer lays the
# same islands out differently run to run (four runs on one stage 3 blend, 60.31 to 60.38 px/m, a fixed hash seed and
# one thread alike), so without the pin no build was reproducible. An island that does not fit costs only itself: it
# shrinks to the density floor, and if it still finds no gap the build stops naming it; a free repack accepted as the
# new pin would move every groove and the livery kit's templates with it. The gate after the pack fails if a pinned
# island moved; the report lists the islands placed afresh per part and why, and each placement (`placed`). Every run writes the layout it packed, the packed faces as
# they leave the packer, to .cache/art/exterior_pass/uv_layout.npz: accepting a build's layout is copying that file over
# the pin. PASS_UV_PIN names another pin file, or "none" packs freely.
PIN_TOL = 0.001  # m
PIN = os.environ.get("PASS_UV_PIN") or str(Path(__file__).resolve().parent / "baselines" / "uv_layout_pin.npz")
PIN = None if PIN == "none" or not Path(PIN).exists() else PIN
PINNED = {}  # part: {face index: [uv per corner]}, the gate's record
FREE = {}  # part: [[face index, ...] per island the pin does not hold]
KEPT_PLACE = set()  # (part, island): changed islands carried back to their pinned place
KEPT_FACES = {}  # part: [[face index, ...] per such island]


def apply_pin(path):
    import numpy as np
    z = np.load(path)
    parts, fpart, centre, ncorner = list(z["parts"]), z["face_part"], z["centre"], z["ncorner"]
    cxyz, cuv = z["corner_xyz"], z["corner_uv"]
    start = np.concatenate([[0], np.cumsum(ncorner)])
    report, free, areas = {}, FREE, [0.0, 0.0]  # areas: the pinned faces' UV and world area
    for o, _ in skin_objs:
        own = set(owners.get(o.name, ()))
        part = o.name[:-len("__pack")] if o.name.endswith("__pack") else o.name
        if not own:
            continue
        rows = np.flatnonzero(fpart == parts.index(part)) if part in parts else np.array([], int)
        tree = KDTree(len(rows))  # small faces' centres lie within a millimetre of each other (the radome's tip)
        for k_, r in enumerate(rows):
            tree.insert(Vector(centre[r]), k_)
        tree.balance()
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        bm.faces.ensure_lookup_table()
        uvl = bm.loops.layers.uv["UVMap"]
        island = uv_islands([f for f in bm.faces if f.index in own], uvl)
        found, why = {}, defaultdict(int)
        for f in island:
            cands = [rows[k_] for _, k_, _ in tree.find_range(f.calc_center_median(), PIN_TOL)] if len(rows) else []
            cands = [r for r in cands if ncorner[r] == len(f.loops)]
            if not cands:
                why["face new or moved"] += 1
                continue
            for r in cands:  # the candidate whose every corner lies on one of this face's
                pts, uvs = cxyz[start[r]:start[r + 1]], cuv[start[r]:start[r + 1]]
                got = []
                for lp in f.loops:
                    d = np.linalg.norm(pts - np.array(lp.vert.co), axis=1)
                    if d.min() > PIN_TOL:
                        break
                    got.append(tuple(uvs[int(d.argmin())]))
                else:
                    found[f] = got
                    break
            else:
                why["corner moved"] += 1
        whole = {i for i in set(island.values()) if all(f in found for f, j in island.items() if j == i)}
        # an island that changed keeps its place: the similarity (turn, scale, shift) that takes its matched faces' UVs
        # to the pinned ones, fitted by least squares, carries the whole island there (no matched face: placed afresh)
        for i in set(island.values()) - whole:
            pairs = [(lp[uvl].uv.copy(), Vector(uv)) for f, j in island.items() if j == i and f in found
                     for lp, uv in zip(f.loops, found[f])]
            if len(pairs) < 3:
                continue
            src = np.array([tuple(p) for p, _ in pairs])
            dst = np.array([tuple(q) for _, q in pairs])
            A = np.zeros((2 * len(src), 4))
            A[0::2] = np.column_stack([src[:, 0], -src[:, 1], np.ones(len(src)), np.zeros(len(src))])
            A[1::2] = np.column_stack([src[:, 1], src[:, 0], np.zeros(len(src)), np.ones(len(src))])
            a, b, tx, ty = np.linalg.lstsq(A, dst.ravel(), rcond=None)[0]
            for f, j in island.items():
                if j == i:
                    for lp in f.loops:
                        u, v = lp[uvl].uv
                        lp[uvl].uv = (a * u - b * v + tx, b * u + a * v + ty)
            KEPT_PLACE.add((o.name, i))
            KEPT_FACES.setdefault(o.name, []).append([f.index for f, j in island.items() if j == i])
        PINNED[o.name] = {}
        for f, i in island.items():
            pin_ = i in whole
            for lp, uv in zip(f.loops, found.get(f, [None] * len(f.loops))):
                if pin_:
                    lp[uvl].uv = uv
                lp[uvl].pin_uv = pin_
            if pin_:
                PINNED[o.name][f.index] = found[f]
                areas[0] += uv_area(f, uvl)
                areas[1] += f.calc_area()
        free[o.name] = [[f.index for f, j in island.items() if j == i] for i in set(island.values()) - whole
                        if (o.name, i) not in KEPT_PLACE]
        n_isl = len(set(island.values()))
        report[part] = {"islands": n_isl, "repacked": n_isl - len(whole), "kept_in_place": n_isl - len(whole) - len(free[o.name]),
                        "why": dict(why)}
        bm.transform(o.matrix_world.inverted())
        bm.to_mesh(o.data)
        bm.free()
    # the free islands at the pinned islands' texel density, so the packer only has to place them
    global PIN_DENSITY
    PIN_DENSITY = areas[0] / max(areas[1], 1e-12)
    # a carried-back island the fit scaled off the pinned density is placed afresh instead: a fit from a few matched
    # corners scaled a 15-face cockpit island 241 times (2477 x 2281 texels), and with no gap that size builds 47 and
    # 48 fell back to a free repack of the whole atlas; the sound fits land within 3% of the pinned density
    for o, _ in skin_objs:
        for faces in list(KEPT_FACES.get(o.name, [])):
            k = island_scale(o, faces)
            if k is not None and not 0.8 < k < 1.25:
                KEPT_FACES[o.name].remove(faces)
                free.setdefault(o.name, []).append(faces)
                report[o.name.removesuffix("__pack")]["kept_in_place"] -= 1
                print("S4 carried back off density, placed afresh:", o.name, len(faces), "faces, scale", round(1 / k, 2), flush=True)
    for o, _ in skin_objs:
        for faces in free.get(o.name, []):
            fit_density(o, faces)
    moved = {p: r for p, r in report.items() if r["repacked"]}
    print("S4 pinned layout", path, "islands", sum(r["islands"] for r in report.values()), "repacked",
          sum(r["repacked"] for r in report.values()), moved, flush=True)
    return report


PIN_DENSITY = None  # the pinned faces' UV area per m2 of skin


def island_scale(o, faces):
    """The linear scale that takes an island's UVs to PIN_DENSITY (None for an island with no UV or skin area)."""
    me, mw = o.data, o.matrix_world
    uv = me.uv_layers["UVMap"].data
    au = aw = 0.0
    for fi in faces:
        li = list(me.polygons[fi].loop_indices)
        us = [uv[l].uv for l in li]
        au += abs(sum(a.x * b.y - b.x * a.y for a, b in zip(us, us[1:] + us[:1]))) / 2
        vs = [mw @ me.vertices[me.loops[l].vertex_index].co for l in li]
        aw += sum(((vs[k] - vs[0]).cross(vs[k + 1] - vs[0])).length / 2 for k in range(1, len(vs) - 1))
    return math.sqrt(PIN_DENSITY * aw / au) if au > 0 and aw > 0 else None


def fit_density(o, faces):
    """An island's UVs scaled about their centre to PIN_DENSITY."""
    k = island_scale(o, faces)
    if k is None:
        return
    me = o.data
    uv = me.uv_layers["UVMap"].data
    lis = [l for fi in faces for l in me.polygons[fi].loop_indices]
    c = sum((uv[l].uv for l in lis), Vector((0.0, 0.0))) / len(lis)
    for l in lis:
        uv[l].uv = c + (uv[l].uv - c) * k


def uv_area(f, uvl):
    uv = [lp[uvl].uv for lp in f.loops]
    return abs(sum(a.x * b.y - b.x * a.y for a, b in zip(uv, uv[1:] + uv[:1]))) / 2


def write_layout(path):
    """The packed faces as they leave the packer (the pin's format): per face its part, world centre, corner count, and
    each corner's world position and UV."""
    import numpy as np
    parts, fpart, centre, ncorner, cxyz, cuv = [], [], [], [], [], []
    for o, _ in skin_objs:
        own = owners.get(o.name, ())
        if not own:
            continue
        part = o.name[:-len("__pack")] if o.name.endswith("__pack") else o.name
        parts.append(part)
        me, mw = o.data, o.matrix_world
        uv = me.uv_layers["UVMap"].data
        for i in sorted(own):
            p = me.polygons[i]
            fpart.append(len(parts) - 1)
            centre.append(tuple(mw @ p.center))
            ncorner.append(p.loop_total)
            for li in p.loop_indices:
                cxyz.append(tuple(mw @ me.vertices[me.loops[li].vertex_index].co))
                cuv.append(tuple(uv[li].uv))
    np.savez_compressed(path, parts=np.array(parts), face_part=np.array(fpart, np.int32), centre=np.array(centre, np.float64),
                        ncorner=np.array(ncorner, np.int16), corner_xyz=np.array(cxyz, np.float32), corner_uv=np.array(cuv, np.float64))


def pin_gate():
    """Every pinned island where the pin put it: a pinned corner more than a millionth of the atlas off fails."""
    off = defaultdict(int)
    for o, _ in skin_objs:
        rec = PINNED.get(o.name)
        if not rec:
            continue
        uv = o.data.uv_layers["UVMap"].data
        for fi, uvs in rec.items():
            p = o.data.polygons[fi]
            if any(abs(uv[li].uv[0] - u) > 1e-6 or abs(uv[li].uv[1] - v) > 1e-6 for li, (u, v) in zip(p.loop_indices, uvs)):
                off[o.name] += 1
    if off:
        raise SystemExit(f"s4_uv: pinned islands moved in the pack (faces per part): {dict(off)}")


SHRINK_FLOOR = 0.85  # an island that fits nowhere at the pinned density may shrink to this share of it, a 2% step at a
# time: check_density's FLOOR_SHARE, the least a part's worst 5% may keep of its shipped density
PLACED = []  # per island placed round the pin: part, faces, how, turned, scale; the report's record


def mark_tri(m, a, b, c):
    """Marks on the square grid m over the atlas the cells a UV triangle overlaps: the cells in its box that no edge of
    the triangle separates from it (a cell's half width projected on the edge's normal)."""
    import numpy as np
    n = m.shape[0]
    us, vs = (a[0], b[0], c[0]), (a[1], b[1], c[1])
    c0, c1 = max(0, int(min(us) * n)), min(n - 1, int(max(us) * n))
    r0, r1 = max(0, int(min(vs) * n)), min(n - 1, int(max(vs) * n))
    if c1 < c0 or r1 < r0:
        return
    X, Y = np.meshgrid((np.arange(c0, c1 + 1) + 0.5) / n, (np.arange(r0, r1 + 1) + 0.5) / n)
    ok = np.ones(X.shape, bool)
    s = math.copysign(1.0, (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    for p, q in ((a, b), (b, c), (c, a)):
        nx, ny = -(q[1] - p[1]) * s, (q[0] - p[0]) * s  # the edge's inward normal
        ok &= (X - p[0]) * nx + (Y - p[1]) * ny >= -0.5 / n * (abs(nx) + abs(ny))
    m[r0:r1 + 1, c0:c1 + 1] |= ok


def polys_cells(polys, n):
    """Every cell of an n grid the UV polygons (lists of (u, v)) overlap, as a boolean grid; each polygon as a fan,
    whose triangles together cover it."""
    import numpy as np
    m = np.zeros((n, n), bool)
    for ps in polys:
        for k in range(1, len(ps) - 1):
            mark_tri(m, ps[0], ps[k], ps[k + 1])
    return m


def first_true(a):
    """(row, col) of a 2D boolean array's first True in row order, or None. Without np.nonzero and np.argwhere, which
    crashed Blender 5.3's numpy now and then on the remote host (an access violation inside nonzero, two runs in four
    on the same input)."""
    f = a.ravel()
    i = int(f.argmax())
    return divmod(i, a.shape[1]) if f[i] else None


def place_free(cells=2048):
    """The islands the pin does not hold, placed into the atlas space it leaves: Blender's packer, asked to keep pinned
    islands locked, laid new ones over them (42,351 shared 2-texel cells on build 47's first pinned run). The pinned
    faces take the cells their triangles cover. Each free island, largest first, goes to the first spot in row order (as
    is or a quarter turn, which keeps align_islands' alignment) where its box grown by the gutter is empty; failing
    that, where its own triangles grown by the gutter are (it may sit in another island's concave side); failing that,
    the same 2% smaller at a time down to SHRINK_FLOOR. The same spot every run. An island that fits nowhere stops the
    build naming it: every other island keeps its pinned place either way."""
    import numpy as np
    pad = int(math.ceil(MARGIN * cells)) + 1
    occ = np.zeros((cells, cells), bool)

    def face_polys(o, faces):
        uv = o.data.uv_layers["UVMap"].data
        return [[tuple(uv[li].uv) for li in o.data.polygons[fi].loop_indices] for fi in faces]
    for o, _ in skin_objs:
        if PINNED.get(o.name):
            occ |= polys_cells(face_polys(o, PINNED[o.name]), cells)
    # a changed island carried back to its place holds it unless its new shape runs onto taken cells: then it is
    # placed afresh with the new ones
    moved_on = defaultdict(list)
    for o, _ in skin_objs:
        for faces in KEPT_FACES.get(o.name, []):
            mine = polys_cells(face_polys(o, faces), cells)
            if (mine & occ).any():
                moved_on[o.name].append(faces)
            else:
                occ |= mine
    jobs = []
    for o, _ in skin_objs:
        for faces in FREE.get(o.name, []) + moved_on.get(o.name, []):
            uv = o.data.uv_layers["UVMap"].data
            lis = [li for fi in faces for li in o.data.polygons[fi].loop_indices]
            us = [uv[li].uv.copy() for li in lis]
            lo = Vector((min(c.x for c in us), min(c.y for c in us)))
            hi = Vector((max(c.x for c in us), max(c.y for c in us)))
            jobs.append(((hi - lo).x * (hi - lo).y, o.name, faces[0], o, faces, lis, lo, hi))
    jobs.sort(key=lambda j: (-j[0], j[1], j[2]))

    def box_spot(w, h):  # the first cell (row, col) whose window of the grown box is empty
        cw, ch = int(math.ceil(w * cells)) + 2 * pad, int(math.ceil(h * cells)) + 2 * pad
        if cw > cells or ch > cells:
            return None
        sat = np.pad(occ.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        win = sat[ch:, cw:] - sat[:-ch, cw:] - sat[ch:, :-cw] + sat[:-ch, :-cw]
        return first_true(win == 0)

    def shape_spot(polys, w, h):  # the first cell whose window the island's own cells, grown by the gutter, leave empty
        mw_, mh_ = int(math.ceil(w * cells)) + 2 * pad + 1, int(math.ceil(h * cells)) + 2 * pad + 1
        if mw_ > cells or mh_ > cells:
            return None
        m = polys_cells([[((u + pad / cells), (v + pad / cells)) for u, v in ps] for ps in polys], cells)[:mh_, :mw_]
        sat = np.pad(m.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        ys, xs = np.arange(mh_), np.arange(mw_)
        r0, r1 = np.clip(ys - pad, 0, mh_), np.clip(ys + pad + 1, 0, mh_)
        c0, c1 = np.clip(xs - pad, 0, mw_), np.clip(xs + pad + 1, 0, mw_)
        grown = (sat[r1][:, c1] - sat[r0][:, c1] - sat[r1][:, c0] + sat[r0][:, c0]) > 0
        k = np.zeros((cells, cells))
        k[:mh_, :mw_] = grown
        hits = np.fft.irfft2(np.fft.rfft2(occ.astype(float)) * np.conj(np.fft.rfft2(k)), s=occ.shape)
        return first_true(hits[:cells - mh_ + 1, :cells - mw_ + 1] < 0.5)
    for _, _, _, o, faces, lis, lo, hi in jobs:
        uv = o.data.uv_layers["UVMap"].data
        size = hi - lo
        spot = None
        for k in range(0, int((1 - SHRINK_FLOOR) / 0.02 + 1e-9) + 1):
            scale = 1 - 0.02 * k
            for how in ("box", "shape"):
                for turn in (False, True):
                    w, h = ((size.y, size.x) if turn else (size.x, size.y))
                    w, h = w * scale, h * scale
                    if how == "box":
                        rc = box_spot(w, h)
                    else:
                        local = [[((d.y, size.x * scale - d.x) if turn else (d.x, d.y)) for d in ((uv[li].uv - lo) * scale
                                  for li in o.data.polygons[fi].loop_indices)] for fi in faces]
                        rc = shape_spot(local, w, h)
                    if rc is not None:
                        spot = (turn, (rc[1] + pad) / cells, (rc[0] + pad) / cells, scale, how)
                        break
                if spot:
                    break
            if spot:
                break
        if spot is None:
            mw = o.matrix_world
            aw = sum(((mw @ vs[k] - mw @ vs[0]).cross(mw @ vs[k + 1] - mw @ vs[0])).length / 2 for fi in faces
                     for vs in [[o.data.vertices[v].co for v in o.data.polygons[fi].vertices]] for k in range(1, len(vs) - 1))
            raise SystemExit(f"s4_uv: no room round the pinned layout for {o.name}'s island at face {faces[0]} ({len(faces)} "
                             f"faces, {aw:.3f} m2 of skin, {size.x * ATLAS * SHRINK_FLOOR:.0f} x "
                             f"{size.y * ATLAS * SHRINK_FLOOR:.0f} texels at {SHRINK_FLOOR} of the pinned density, gutter "
                             "aside): no gap that size is left in the atlas")
        turn, x, y, scale, how = spot
        for li in lis:
            d = (uv[li].uv - lo) * scale
            uv[li].uv = (x + d.y, y + (size.x * scale - d.x)) if turn else (x + d.x, y + d.y)
        occ |= polys_cells(face_polys(o, faces), cells)
        PLACED.append({"part": o.name.removesuffix("__pack"), "face": faces[0], "faces": len(faces), "how": how,
                       "turned": turn, "scale": round(scale, 2), "texels": [round(size.x * scale * ATLAS), round(size.y * scale * ATLAS)],
                       "carried_back_but_overlapping": faces in moved_on.get(o.name, [])})
        print("S4 placed", PLACED[-1], flush=True)
    return len(PLACED)


PIN_REPORT = apply_pin(PIN) if PIN else None
if PIN:  # the pinned islands stay; the free ones are placed round them, the same way every run
    placed = place_free()
    keep_d = owner_density()
    print("S4 pinned pack: free islands placed", placed, "density", round(keep_d, 2), "px/m", flush=True)
    if keep_d < 60.0:
        raise SystemExit(f"s4_uv: the pinned layout reaches {keep_d:.2f} px/m, under the 60 floor")
else:
    tried = {v: pack_seen(*v) for v in VARIANTS}
    for v, d in tried.items():
        print("S4 pack, long islands split", *v, round(d, 2), "px/m", flush=True)
    # the packer starts from the islands' current places: packing the best setting again from its own layout gains a
    # little, but wanders, so the densest of every pack is the layout kept
    final, (keep_d, keep_uv) = [], max(SEEN, key=lambda t: t[0])
    for setting in ([] if keep_d >= 60.0 else sorted(tried, key=tried.get, reverse=True)[:3]):  # the three best, repacked
        for _ in range(40):  # the packer's result wanders about 1 px/m run to run: repack until the floor is cleared (two
            # settings at 24 each stopped at 59.99 once the stock-matched damage field changed the inner copies)
            final.append((setting, pack(*setting)))
            if final[-1][1] > keep_d:
                keep_d, keep_uv = final[-1][1], uv_snapshot()
            if keep_d >= 60.0:
                break
        if keep_d >= 60.0:
            break
    for o, _ in skin_objs:
        o.data.uv_layers["UVMap"].data.foreach_set("uv", keep_uv[o.name])
    print("S4 pack kept", [(s[0], round(d, 2)) for s, d in final], "densest", round(keep_d, 2), flush=True)
pin_gate()
write_layout(P.PASS / "uv_layout.npz")
for name_, (c_, own_) in PACK_COPY.items():  # the copies' UVs back onto the parts' owner faces, loop by loop
    src_, dst_ = c_.data.uv_layers["UVMap"].data, bpy.data.objects[name_].data.uv_layers["UVMap"].data
    dpolys_ = bpy.data.objects[name_].data.polygons
    for k_, pi_ in enumerate(own_):
        for lc_, lo_ in zip(c_.data.polygons[k_].loop_indices, dpolys_[pi_].loop_indices):
            dst_[lo_].uv = src_[lc_].uv
    me_ = c_.data
    bpy.data.objects.remove(c_)
    bpy.data.meshes.remove(me_)
skin_objs, owners = SKIN_OBJS_PARTS, OWNERS_PARTS

# small owner faces the unwrap collapsed (the cove trims' rim facets, 3 to 53 cm2 on wing_outer_R): a flat paint from
# the nearest healthy owner face's UV centre, as copies (their texels are that face's). Over 0.01 m2 they stay, for
# check_density's collapsed-triangle gate
COLLAPSED_PX, COLLAPSED_M2 = 25.0, 0.01  # least axis, px/m, and area: a sliver this small reads as flat paint anyway
flat_rims, copy_faces_extra = {}, {}


def least_axis_px(vs, uvs):
    """The least singular value of a triangle's UV map in px/m on the atlas (check_density's measure)."""
    e1, e2 = vs[1] - vs[0], vs[2] - vs[0]
    n = e1.cross(e2)
    if n.length < 1e-12:
        return 0.0
    x = e1.normalized()
    y = n.normalized().cross(x)
    g = ((e1.dot(x), e2.dot(x)), (e1.dot(y), e2.dot(y)))
    t = ((uvs[1].x - uvs[0].x, uvs[2].x - uvs[0].x), (uvs[1].y - uvs[0].y, uvs[2].y - uvs[0].y))
    det = g[0][0] * g[1][1] - g[0][1] * g[1][0]
    gi = ((g[1][1] / det, -g[0][1] / det), (-g[1][0] / det, g[0][0] / det))
    j = [[(t[r][0] * gi[0][c] + t[r][1] * gi[1][c]) * ATLAS for c in range(2)] for r in range(2)]
    s2 = sum(v * v for row in j for v in row)
    d2 = abs(j[0][0] * j[1][1] - j[0][1] * j[1][0])
    return math.sqrt(max(0.0, (s2 - math.sqrt(max(0.0, s2 * s2 - 4 * d2 * d2))) / 2))
for o, _ in skin_objs:
    me, mw = o.data, o.matrix_world
    uv = me.uv_layers["UVMap"].data
    own = set(owners.get(o.name, ()))
    bad, good = [], []
    for i in own:
        p = me.polygons[i]
        li = list(p.loop_indices)
        vs = [mw @ me.vertices[me.loops[l].vertex_index].co for l in li]
        a3 = sum(((vs[k] - vs[0]).cross(vs[k + 1] - vs[0])).length / 2 for k in range(1, len(li) - 1))
        least = min(least_axis_px([vs[0], vs[k], vs[k + 1]], [uv[li[0]].uv, uv[li[k]].uv, uv[li[k + 1]].uv]) for k in range(1, len(li) - 1))
        (bad if a3 < COLLAPSED_M2 and least < COLLAPSED_PX else good).append(i)
    if not bad or not good:
        continue
    kd = KDTree(len(good))
    for k, i in enumerate(good):
        kd.insert(mw @ me.polygons[i].center, k)
    kd.balance()
    for i in bad:
        src = me.polygons[good[kd.find(mw @ me.polygons[i].center)[1]]]
        c = sum((uv[l].uv for l in src.loop_indices), Vector((0.0, 0.0))) / src.loop_total
        for l in me.polygons[i].loop_indices:
            uv[l].uv = c
        copy_faces_extra.setdefault(o.name, set()).add(i)
    flat_rims[o.name] = len(bad)
print("S4 collapsed rim facets painted flat", flat_rims, flush=True)

def world_loops(o, idx):
    me = o.data
    p = me.polygons[idx]
    return [(li, o.matrix_world @ me.vertices[me.loops[li].vertex_index].co) for li in p.loop_indices]


# ---- copies take their owner's new UVs, matched by position (mirrored for a right-hand copy) ----
bad_copies = 0
for name, idx, (oname, oidx) in copies:
    o, src = bpy.data.objects[name], bpy.data.objects[oname]
    dst_uv, src_uv = o.data.uv_layers["UVMap"].data, src.data.uv_layers["UVMap"].data
    sl = world_loops(src, oidx)
    for li, p in world_loops(o, idx):
        cands = [(min((q - p).length, (q - Vector((-p.x, p.y, p.z))).length), sli) for sli, q in sl]
        d, sli = min(cands)
        bad_copies += d > 0.002
        dst_uv[li].uv = src_uv[sli].uv
# ---- twins take their original's UVs, matched by vertex position ----
twin_mismatch = 0
for o, slots in skin_objs:
    tw = twin_of(o)
    me = o.data
    uv = me.uv_layers["UVMap"].data
    tva = me.attributes.get("twin_vert")
    tvv = [0] * len(me.loops)
    if tva is not None:
        tva.data.foreach_get("value", tvv)
    lin = [0] * len(me.polygons)
    if me.attributes.get("liner") is not None:
        me.attributes["liner"].data.foreach_get("value", lin)
    for p in me.polygons:
        if tw[p.index]:
            orig = me.polygons[tw[p.index] - 1]
            by_vert = {me.loops[li].vertex_index: li for li in orig.loop_indices}
            for li in p.loop_indices:
                sli = by_vert.get(tvv[li] - 1)
                if sli is None:
                    # a liner whose original the roundel cut split: it takes the primer point below whatever its UVs
                    twin_mismatch += not lin[p.index]
                    continue
                uv[li].uv = uv[sli].uv
if twin_mismatch:
    raise SystemExit(f"s4_uv: {twin_mismatch} twin corners have no original corner (s3's twin_vert)")

# ---- the liners (s3: the wing-type parts' inward copies, 12 mm in) take a point of the atlas no island covers, far
# from every island: black in the albedo and the liveries, never opened by the damage map ----
LINER_PATCH_PX, GUTTER_PX = 24, 6  # the primer block s6 paints, and the atlas gutter round it


def empty_uv(n=1024, taken=()):
    """The centre of a block LINER_PATCH_PX + 2 GUTTER_PX texels square that no skin triangle touches: each triangle's
    UV bounding box marked on an n grid (conservative: a long thin triangle marks all it might cross; counting island
    corners alone put the primer inside a centre-body skin triangle), then the free block farthest
    from any mark. taken: centres of blocks already given out, kept clear. Only flat-painted faces use a block."""
    import numpy as np
    used = np.zeros((n, n), bool)
    half = (LINER_PATCH_PX + 2 * GUTTER_PX) / 4096 / 2
    for cu, cv_ in taken:
        used[max(0, int((cv_ - half) * n)):int((cv_ + half) * n) + 1, max(0, int((cu - half) * n)):int((cu + half) * n) + 1] = True
    for o, slots in skin_objs:
        me = o.data
        uv = me.uv_layers["UVMap"].data
        ln = [0] * len(me.polygons)
        if me.attributes.get("liner") is not None:
            me.attributes["liner"].data.foreach_get("value", ln)
        for p in me.polygons:
            if p.material_index in slots and not ln[p.index]:
                us = [uv[li].uv.x for li in p.loop_indices]
                vs = [uv[li].uv.y for li in p.loop_indices]
                used[max(0, int(min(vs) * n)):min(n, int(max(vs) * n) + 1), max(0, int(min(us) * n)):min(n, int(max(us) * n) + 1)] = True
    cell = 4096 // n
    k = -(-(LINER_PATCH_PX + 2 * GUTTER_PX) // cell)  # cells the block needs
    sat = np.pad(used.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    free = (sat[k:, k:] - sat[:-k, k:] - sat[k:, :-k] + sat[:-k, :-k]) == 0  # free[i, j]: the block from (i, j) is empty
    if not free.any():
        raise SystemExit("s4_uv: no empty block left on the atlas for the liners' primer")
    while True:  # the free area shrunk a cell at a time until one more step would empty it: the most open place
        nxt = free.copy()
        nxt[1:, :] &= free[:-1, :]
        nxt[:-1, :] &= free[1:, :]
        nxt[:, 1:] &= free[:, :-1]
        nxt[:, :-1] &= free[:, 1:]
        nxt[0, :] = nxt[-1, :] = nxt[:, 0] = nxt[:, -1] = False
        if not nxt.any():
            break
        free = nxt
    i, j = (int(x) for x in np.argwhere(free)[0])
    return ((j + k / 2) / n, (i + k / 2) / n)


DARK_UV = empty_uv()
# The recesses' point, a second empty block, painted dark in stage 6: the control surfaces' trim (their split halves'
# inner faces, closing faces and fittings) and the spoiler wells. On the liners' primer they read as a pale flat slab
# in the sun, as bright as the skin, and a pale strip along a shut split (build 47).
RECESS_UV = empty_uv(taken=[DARK_UV])
# The shaded recesses' point, a third block, painted near the skin's own tone in stage 6: a recess face that faces down
# or sideways at rest (a spoiler's underside and its ribs, an upper split half's inner face) shows only in shade when the
# split opens, lit by ambient light alone, and on the dark recess tone it read RGB 8 to 20 on screen, a black void with
# the spoiler's sunlit rib sides drawn over it as a grid (builds 47 to 49). Faces up (a lower half's inner face, a
# well's floor) catch the sun and keep the dark point.
RECESS_SHADE_UV = empty_uv(taken=[DARK_UV, RECESS_UV])
# The spoilers' ribs' point, a fourth block: a spoiler's sideways recess faces, its underside's stiffener ribs. Their
# sides catch the sun when the split opens while the panels between them stay in the gap's shade, and on the panels'
# tone they drew 1 px light lines at seven times the panels' brightness (build 50): a wireframe on black
RECESS_RIB_UV = empty_uv(taken=[DARK_UV, RECESS_UV, RECESS_SHADE_UV])
RECESS_SUN_Z = 0.5  # a recess face whose world normal's z at rest reaches this takes the sunlit point


def recess_point(o, p):
    z = (o.matrix_world.to_3x3() @ p.normal).normalized().z
    if z >= RECESS_SUN_Z:
        return RECESS_UV
    return RECESS_RIB_UV if o.name.startswith("spoiler_") and z > -RECESS_SUN_Z else RECESS_SHADE_UV


liners = 0
for o, slots in skin_objs:
    a = o.data.attributes.get("liner")
    if a is None:
        continue
    flags = [0] * len(o.data.polygons)
    a.data.foreach_get("value", flags)
    uv = o.data.uv_layers["UVMap"].data
    for p in o.data.polygons:
        if flags[p.index]:
            liners += 1
            for li in p.loop_indices:
                uv[li].uv = DARK_UV
print("S4 liners", liners, "faces on the empty atlas point", DARK_UV, flush=True)

# A flap track fairing's joint shows its insides at flaps up (a crescent over the rear half's top, where the flap's nose
# sweeps) and as the rear half slides aft: the linings of the shroud, the rear half and the sleeve, and the shroud's
# liners. On the stock sheet's lining patch, the primer or any fixed dark tone they read pale on a dark livery and
# black on a pale one (the owner's builds 53 and 54). Within JOINT_REACH_M of the joint each goes onto the skin atlas
# at the UV centre of the nearest outer skin face of its own part, a copy, so it shows the livery of the skin it lines.
import fairing  # noqa: E402

JOINT_REACH_M = 0.3
joints = []
for e_ in (o for o in bpy.data.objects if o.get("fairing_of")):
    fr_ = fairing.Frame(bpy.data.objects[e_["fairing_of"]])
    rear_ = next(c for c in e_.children if c.type == "MESH")
    rv_ = [rear_.matrix_world @ v.co for v in rear_.data.vertices]
    sp_ = [(p_ - fr_.H).dot(fr_.ax) for p_ in rv_]
    us_ = [fr_.u(p_) for p_ in rv_ if abs(fr_.f(p_) - fairing.MOUTH_F) < 0.05]
    axis_ = fr_.H + fr_.ax * ((min(sp_) + max(sp_)) / 2) + fr_.up * ((min(us_) + max(us_)) / 2)  # the fairing's axis at the joint
    joints.append((fr_, min(sp_) - 0.02, max(sp_) + 0.02, axis_))


def in_joint(ws):
    """Whether a face (its world vertices) lies inside a fairing within JOINT_REACH_M of its joint: not the cove's own
    linings beside it."""
    for fr_, lo, hi, axis_ in joints:
        if (min(abs(fr_.f(w) - fairing.MOUTH_F) for w in ws) <= JOINT_REACH_M and all(lo <= (w - fr_.H).dot(fr_.ax) <= hi for w in ws)
                and all(((w - axis_) - fr_.fwd * (w - axis_).dot(fr_.fwd)).length < 0.35 for w in ws)):
            return True
    return False


joint_lined = {}
for o, slots in skin_objs:
    if not (o.name.startswith("wing_root_") or "_fairing" in o.name):
        continue
    me, mw = o.data, o.matrix_world
    names = [m.name if m else "" for m in me.materials]
    if P.SKIN not in names:
        continue
    si = names.index(P.SKIN)
    lin = me.attributes.get("liner")
    tw = me.attributes.get("twin_src")
    flag = lambda a, i: a is not None and a.data[i].value  # noqa: E731
    uv = me.uv_layers["UVMap"].data
    outer = [p for p in me.polygons if p.material_index == si and not flag(lin, p.index) and not flag(tw, p.index)]
    if not outer:
        continue
    kd = KDTree(len(outer))
    for n_, p in enumerate(outer):
        kd.insert(mw @ p.center, n_)
    kd.balance()
    moved = 0
    for p in me.polygons:
        inside = names[p.material_index] == fairing.LINING or (p.material_index == si and flag(lin, p.index))
        if not inside:
            continue
        if not in_joint([mw @ me.vertices[v].co for v in p.vertices]):
            continue
        src = outer[kd.find(mw @ p.center)[1]]
        c = sum((uv[li].uv for li in src.loop_indices), Vector((0.0, 0.0))) / src.loop_total
        for li in p.loop_indices:
            uv[li].uv = c
        p.material_index = si
        copy_faces_extra.setdefault(o.name, set()).add(p.index)
        moved += 1
    joint_lined[o.name] = moved
print("S4 fairing joints' linings and liners onto their skin's livery", joint_lined, flush=True)

# ---- mark every face whose texels are another face's (copies and twins), for the bake's proxy ----
copy_faces = defaultdict(set)
for n_, fs_ in copy_faces_extra.items():  # the collapsed rim facets painted flat above
    copy_faces[n_] |= fs_
for name, idx, _ in copies:
    copy_faces[name].add(idx)
for o, slots in skin_objs:
    for i, t in enumerate(twin_of(o)):
        if t:
            copy_faces[o.name].add(i)
    a = o.data.attributes.get("uv_copy") or o.data.attributes.new("uv_copy", "INT", "FACE")
    a.data.foreach_set("value", [1 if p.index in copy_faces[o.name] else 0 for p in o.data.polygons])

# ---- two slots a part, as the Darkreach draws (FRAMES.md section 9: 214 draw calls a pass against its 123) ----
# Each part keeps its skin (with its inward twins) and puts everything else on ONE slot, Centurion_trim_cut: the stock
# jet_mechanical sheet cut at alpha 0.394, the material the Darkreach's own structure uses (wing2_L: skin twins and
# jet_mechanical). Glass, the lights, the gear's own material and the LOD material stay apart.
#   - the pass's trims (pass_trim, pass_trim_rail, pass_trim_cut): their strip UVs as s2 laid them;
#   - linings, paint, chrome, steel, and the old jet_mechanical swatches (mod sheet, UV at each swatch's centre): a flat
#     patch of the stock sheet nearest the swatch's colour;
#   - the interior structure (aircraft_structure) and the damage lining (Centurion_airframe), and the honeycomb cores:
#     each face box-mapped onto a patch of the stock sheet (a detailed grey panel; the dark lining; the hex band).
import numpy as np  # noqa: E402

import detail_centurion as DC  # noqa: E402

# kept apart: the cores keep the stock honeycomb, metre-mapped (round 1 folded them onto the
# perforated wing web); the laser's lens stays opaque, as Unity authors it (sol3: on the cutout sheet it printed a lattice)
KEEP = ("Centurion_skin", "glass", "Centurion_gear", "LOD", "honeycomb", "pass_honeycomb", "laser_lens")
STRUCT = "Centurion_trim_cut"
SHEET = P.game_texture("jet_mechanical_AlbedoTransparency.png")
HEX = (0.377, 0.867, 0.667, 0.940)  # trim.TRIMS["wing_web"], the hex band


def sheet_patches(targets):
    """{name: (srgb, wanted spread)} -> {name: (u0, v0, u1, v1)}: the opaque 16 px block of the stock sheet nearest each
    colour with about the wanted texture in it."""
    im = bpy.data.images.load(str(SHEET))
    w, h = im.size
    px = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(im)
    B = 16
    blk = px[:h // B * B, :w // B * B].reshape(h // B, B, w // B, B, 4)
    mean, spread = blk[..., :3].mean((1, 3)), blk[..., :3].std((1, 3)).mean(-1)
    solid = blk[..., 3].min((1, 3)) > 0.95
    mi = bpy.data.images.load(str(SHEET).replace("AlbedoTransparency", "MetallicSmoothness"))
    mp = np.array(mi.pixels[:], dtype=np.float32).reshape(h, w, 4)[:h // B * B, :w // B * B].reshape(h // B, B, w // B, B, 4)
    bpy.data.images.remove(mi)
    gloss = mp[..., 0].mean((1, 3)) + mp[..., 3].mean((1, 3))  # metal plus smoothness: matte patches preferred (the cove's lining read as chrome)
    ai = bpy.data.images.load(str(SHEET).replace("AlbedoTransparency", "Occlusion"))
    aop = np.array(ai.pixels[:], dtype=np.float32).reshape(h, w, 4)[:h // B * B, :w // B * B, 0].reshape(h // B, B, w // B, B)
    bpy.data.images.remove(ai)
    lit = aop.min((1, 3)) > 0.15  # the stock AO under the patch: the round 1 lining patch had AO 0 and baked black (sol2 3)
    out = {}
    for k, (c, want) in targets.items():
        cost = np.linalg.norm(mean - np.asarray(c), axis=-1) + 2 * np.abs(spread - want) + 0.5 * gloss + 10 * ~solid + 10 * ~lit
        i, j = np.unravel_index(int(cost.argmin()), cost.shape)
        out[k] = ((j * B + 2) / w, (i * B + 2) / h, ((j + 1) * B - 2) / w, ((i + 1) * B - 2) / h)
    return out


sw = {k: tuple(c / 255 for c in v[0]) for k, v in DC.MECH_SWATCHES.items()}
PATCH = sheet_patches({**{k: (c, 0.01) for k, c in sw.items()}, "lining": ((0.05, 0.05, 0.055), 0.01),
                       "structure": ((0.42, 0.43, 0.44), 0.06)})
FLAT = {"pass_lining": "lining", "pass_paint": "fitting", "pass_chrome": "nozzle", "pass_steel": "spinner", "Centurion_airframe": "lining"}
BOXED = {"aircraft_structure": "structure"}
SWATCH_ORDER = list(DC.MECH_SWATCHES)  # mech_trim's cells: 4 across, 2 up, in this order


def box_face(uv, me, p, rect):
    """The face laid flat in its own plane and fitted inside rect, keeping its proportions."""
    n = p.normal
    e1 = n.orthogonal().normalized()
    e2 = n.cross(e1)
    cs = [(me.vertices[me.loops[li].vertex_index].co.dot(e1), me.vertices[me.loops[li].vertex_index].co.dot(e2)) for li in p.loop_indices]
    x0, y0 = min(c[0] for c in cs), min(c[1] for c in cs)
    span = max(max(c[0] for c in cs) - x0, max(c[1] for c in cs) - y0, 1e-6)
    u0, v0, u1, v1 = rect
    for li, (x, y) in zip(p.loop_indices, cs):
        uv[li].uv = (u0 + (x - x0) / span * (u1 - u0), v0 + (y - y0) / span * (v1 - v0))


struct_mat = bpy.data.materials.get(STRUCT) or bpy.data.materials.new(STRUCT)
# The engines keep the mod's own swatch sheet (jet_mechanical -> Centurion_mech: DC.MECH_SWATCHES, no occlusion map)
# instead of the stock sheet: folded there, the fan, duct and plug swatches landed on matte blocks whose stock occlusion
# (0.20 to 0.39) cut ambient light and reflections to a fifth, so in shade the intake read as a black disc and the
# bypass duct as unlit black, and the nacelles' structure members on the sheet's polished strips showed in the duct as
# bright fragments (the owner's b.png and c.png). Every other slot on an engine part folds onto the duct swatch.
ENGINE_PARTS = DC.MECH_DUCT_PARTS + ("fan_",)
MECH = "jet_mechanical"
_duct = SWATCH_ORDER.index("duct")
DUCT_UV = ((_duct % 4 + 0.5) / 4, (_duct // 4 + 0.5) / 2)
folded = defaultdict(int)
for o in [x for x in bpy.data.objects if x.type == "MESH" and "_colmesh" not in x.name and "_lod1" not in x.name
          and not any(c.name in ("Colliders", "LOD1") for c in x.users_collection)]:
    me = o.data
    if not me.materials:
        continue
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uv = me.uv_layers[0].data
    names = [m.name if m else "" for m in me.materials]
    fold = {i for i, n in enumerate(names) if n and not n.startswith(KEEP) and not n.startswith("light_")}
    if not fold:
        continue
    engine = o.name.startswith(ENGINE_PARTS)
    for p in me.polygons:
        i = p.material_index
        if i not in fold:
            continue
        n = names[i]
        folded[n] += 1
        if engine:
            if n != MECH:  # the swatch faces keep their swatch centres
                for li in p.loop_indices:
                    uv[li].uv = DUCT_UV
            continue
        if n in FLAT:
            rect = PATCH[FLAT[n]]
        elif n in BOXED:
            rect = HEX if BOXED[n] == "hex" else PATCH[BOXED[n]]
            box_face(uv, me, p, rect)
            continue
        elif n == "jet_mechanical":
            c = sum((uv[li].uv for li in p.loop_indices), Vector((0.0, 0.0))) / p.loop_total
            cell = min(int(c.y * 2), 1) * 4 + min(int(c.x * 4), 3)
            rect = PATCH[SWATCH_ORDER[cell]] if cell < len(SWATCH_ORDER) else PATCH["fitting"]
        else:
            continue  # the trims keep their strip UVs
        cu, cv = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        for li in p.loop_indices:
            uv[li].uv = (cu, cv)
    # the slots: every folded slot becomes the one structure slot (an engine's: the swatch sheet); unused slots go
    into = MECH if engine else STRUCT
    target = {i: (into if i in fold else names[i]) for i in range(len(names))}
    order = []
    for p in me.polygons:
        t = target[p.material_index]
        if t not in order:
            order.append(t)
    order.sort(key=lambda n: n != P.SKIN)  # the skin on slot 0: UnitPart.SetLivery paints slot 0 only
    idx = [order.index(target[p.material_index]) for p in me.polygons]
    mats = {n: (struct_mat if n == STRUCT else bpy.data.materials.get(MECH) or bpy.data.materials.new(MECH) if n == MECH
                else me.materials[names.index(n)]) for n in order}
    me.materials.clear()
    for n in order:
        me.materials.append(mats[n])
    me.polygons.foreach_set("material_index", idx)
report_fold = dict(folded)
for o_ in bpy.data.objects:  # the cores on the stock honeycomb material, by its own name
    if o_.type == "MESH":
        for i_, m_ in enumerate(o_.data.materials):
            if m_ and m_.name == "pass_honeycomb":
                o_.data.materials[i_] = bpy.data.materials.get("honeycomb") or bpy.data.materials.new("honeycomb")
# a control surface's core takes its second slot, so its few trim faces (hinge fittings, end members, the split
# halves' closing faces) go onto the skin, every corner of a face on the recesses' point (RECESS_UV, painted dark in the
# albedo and every livery), marked as copies so the bake leaves their texels alone: skin plus honeycomb,
# the two slots a control surface draws today. An aileron's lower half (s1) has no core but takes the same: its closing
# face on the stock sheet's polished metal mirrored the sky as chrome whenever the clamshell opened. Each corner once
# took the centre of the skin triangle nearest it, so a big flat face's corners landed in different islands and the face
# drew a streak across the atlas (the owner's split aileron edges, roundel green among them). A spoiler's underside
# goes the same way: the split aileron's rising upper half bares it, and on the stock sheet it drew a bright metal grid
# in the open split and white dashes along a shut one (a scratch build's loud trim colour showed it, builds 43 to 45)
painted_fittings = {}
for o, slots in skin_objs:
    me = o.data
    names = [m.name if m else "" for m in me.materials]
    spoiler = o.name.startswith("spoiler_") and o.name.endswith("_visible")
    if STRUCT not in names or ("honeycomb" not in names and not o.name.endswith("_visible_lower") and not spoiler):
        continue
    si, ti = names.index(P.SKIN), names.index(STRUCT)
    uv = me.uv_layers["UVMap"].data
    cp = [0] * len(me.polygons)
    me.attributes["uv_copy"].data.foreach_get("value", cp)
    # marked, so stage 5 builds no far hull from them: on the skin a spoiler's actuator fittings stood out of its hull as
    # spikes (silhouette overshoot from ahead 4.2 to 8.6%)
    pr = (me.attributes.get("primer") or me.attributes.new("primer", "INT", "FACE")).data
    moved = 0
    for p in me.polygons:
        if p.material_index != ti:
            continue
        at = recess_point(o, p)
        for li in p.loop_indices:
            uv[li].uv = at
        p.material_index = si
        cp[p.index] = 1
        pr[p.index].value = 1
        moved += 1
    me.attributes["uv_copy"].data.foreach_set("value", cp)
    me.materials.pop(index=ti)
    painted_fittings[o.name] = moved
print("S4 control-surface trim onto the skin's paint", painted_fittings, flush=True)
# The fuel jettison pipe (m4/wing.py JETTISON_PIPE, on wing_root_<side>) goes onto the recesses' point the same way, as
# the dischargers on the control surfaces: on the stock sheet's pale tan fitting patch it read as a bare rod hanging off
# the trailing edge
JETTISON_PIPE = 26
jettison_faces = {}
for o, slots in skin_objs:
    me = o.data
    pc = me.attributes.get("cls")
    if not o.name.startswith("wing_root_") or pc is None:
        continue
    cl = [0] * len(me.polygons)
    pc.data.foreach_get("value", cl)
    names = [m.name if m else "" for m in me.materials]
    si, uv = names.index(P.SKIN), me.uv_layers["UVMap"].data
    cp, pr = [0] * len(me.polygons), me.attributes.get("primer") or me.attributes.new("primer", "INT", "FACE")
    me.attributes["uv_copy"].data.foreach_get("value", cp)
    moved = 0
    for p in me.polygons:
        if cl[p.index] != JETTISON_PIPE:
            continue
        at = recess_point(o, p)
        for li in p.loop_indices:
            uv[li].uv = at
        p.material_index = si
        cp[p.index] = 1
        pr.data[p.index].value = 1
        moved += 1
    me.attributes["uv_copy"].data.foreach_set("value", cp)
    jettison_faces[o.name] = moved
print("S4 jettison pipe onto the skin's paint", jettison_faces, flush=True)
if len(jettison_faces) != 2 or not all(jettison_faces.values()):
    raise SystemExit(f"s4_uv: the jettison pipe is missing from a wing root: {jettison_faces}")
# The spoiler wells (spoiler_well.py: the well, its ribs, frame and fittings in wing_outer_<side>'s trim slots) go onto
# the recesses' point the same way: the spoiler rises 50 degrees when the split opens (CenturionAuthor:
# SplitKind.Rise), and on the stock sheet the well drew the bright metal grid under it and the white dashes along its
# shut edge (builds 43 to 46; the spoiler's own underside, moved in build 46, was not it; a scratch build that painted
# only these faces magenta showed the whole grid and nothing else). A well face: a wing_outer face on the structure slot
# whose centre lies under the spoiler at rest, within its plan box and WELL_DEPTH below it.
WELL_DEPTH, WELL_MARGIN = 0.25, 0.03
wells = {}
for side in ("L", "R"):
    o, sp = bpy.data.objects[f"wing_outer_{side}"], bpy.data.objects[f"spoiler_{side}_visible"]
    cs = [sp.matrix_world @ Vector(c) for c in sp.bound_box]
    lo = [min(c[i] for c in cs) - WELL_MARGIN for i in range(3)]
    hi = [max(c[i] for c in cs) + WELL_MARGIN for i in range(3)]
    lo[2] -= WELL_DEPTH
    me = o.data
    names = [m.name if m else "" for m in me.materials]
    si, ti = names.index(P.SKIN), names.index(STRUCT)
    uv = me.uv_layers["UVMap"].data
    cp = [0] * len(me.polygons)
    me.attributes["uv_copy"].data.foreach_get("value", cp)
    pr = (me.attributes.get("primer") or me.attributes.new("primer", "INT", "FACE")).data
    mw = o.matrix_world
    moved = 0
    for p in me.polygons:
        c = mw @ p.center
        if p.material_index != ti or not all(lo[i] <= c[i] <= hi[i] for i in range(3)):
            continue
        at = recess_point(o, p)
        for li in p.loop_indices:
            uv[li].uv = at
        p.material_index = si
        cp[p.index] = 1
        pr[p.index].value = 1
        moved += 1
    me.attributes["uv_copy"].data.foreach_set("value", cp)
    wells[o.name] = moved
print("S4 spoiler wells onto the recesses' point", RECESS_UV, wells, flush=True)
print("S4 slots folded onto", STRUCT, report_fold, "patches", {k: [round(x, 3) for x in v] for k, v in PATCH.items()}, flush=True)
# ---- no skin face's UVs collapsed to a line (check_uv_collapse.py): such a face smears a streak of whatever its line
# crosses; it takes its own UVs' centre at every corner instead, a flat sample of the paint where it sits (8 faces of a
# closed box inside the cockpit and 3 slivers at the outer wings' trailing edges were the last) ----
flattened = {}
for o in P.part_objects()[0].values():
    me = o.data
    names = [m.name if m else "" for m in me.materials]
    if P.SKIN not in names or not me.uv_layers:
        continue
    skin, uv = names.index(P.SKIN), me.uv_layers["UVMap"].data
    me.calc_loop_triangles()
    bad = {lt.polygon_index for lt in me.loop_triangles if lt.material_index == skin
           and P.uv_collapsed([me.vertices[v].co for v in lt.vertices], [uv[i].uv for i in lt.loops])}
    cp = [0] * len(me.polygons)
    me.attributes["uv_copy"].data.foreach_get("value", cp)
    for pi in sorted(bad):
        p = me.polygons[pi]
        c = sum((uv[li].uv for li in p.loop_indices), Vector((0.0, 0.0))) / p.loop_total
        for li in p.loop_indices:
            uv[li].uv = c
        cp[pi] = 1  # a copy, as the painted fittings are: the bake leaves its texels to the faces round it
    me.attributes["uv_copy"].data.foreach_set("value", cp)
    if bad:
        flattened[o.name] = len(bad)
print("S4 collapsed skin faces flattened to a point", flattened, flush=True)
# ---- density and the atlas record ----
W = U = 0.0
per = {}
for o, slots in skin_objs:
    fs = [i for i in owners.get(o.name, []) if i not in FOOT_PART.get(o.name, ())]  # the roundels' footprints left out
    me, mw = o.data, o.matrix_world
    uv = me.uv_layers["UVMap"].data
    wa = ua = 0.0
    for i in fs:
        li = list(me.polygons[i].loop_indices)
        vs = [mw @ me.vertices[me.loops[l].vertex_index].co for l in li]
        for k in range(1, len(li) - 1):
            wa += ((vs[k] - vs[0]).cross(vs[k + 1] - vs[0])).length / 2
            a, b, c = uv[li[0]].uv, uv[li[k]].uv, uv[li[k + 1]].uv
            ua += abs((b - a).cross(c - a)) / 2
    W, U = W + wa, U + ua
    if wa:
        per[o.name] = {"px_per_m": round(ATLAS * math.sqrt(ua / wa), 1), "unique_m2": round(wa, 2)}
h = hashlib.sha256()
for o, _ in sorted(skin_objs, key=lambda t: t[0].name):
    h.update(o.name.encode())
    h.update(bytes(str([round(x, 6) for x in uvs(o)]), "ascii"))
px = round(ATLAS * math.sqrt(U / W), 2)
(P.PASS / "atlas_record.json").write_text(json.dumps({"blender": bpy.app.version_string, "uv_sha256": h.hexdigest(), "px_per_m": px}, indent=1))
if px < 60.0:
    (P.PASS / "s4_uv_short.json").write_text(json.dumps({"px_per_m": px, "unique_m2": round(W, 1), "parts": per}, indent=1))
    raise SystemExit(f"s4_uv: the pack reaches {px} px/m, under the 60 floor")
P.finish(ctx, {"folded_onto_structure": report_fold, "px_per_m": px, "per_part_px_per_m": per, "copies": len(copies), "copies_off_by_2mm": bad_copies,
               "owners": sum(map(len, owners.values())), "liner_uv": list(DARK_UV), "recess_uv": list(RECESS_UV), "recess_shade_uv": list(RECESS_SHADE_UV), "recess_rib_uv": list(RECESS_RIB_UV),
               "spoiler_wells": wells, "uv_pin": {"file": PIN, "parts": PIN_REPORT, "placed": PLACED}})
