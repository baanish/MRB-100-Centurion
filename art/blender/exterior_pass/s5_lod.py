"""Pass stage 5, the simple model: one hull per damage part (its LOD1 object, so a part that leaves takes its hull),
about 8,000 triangles for the aircraft as the Darkreach's 7,862 (FRAMES.md section 9: 916 today, which pops), on the
skin material alone.

Each part's hull is its own exterior as a viewer sees it (faces whose outward ray leaves the aircraft: the skin, an
intake's duct, a nozzle's inside, the glazing; not the inward twins nor the structure behind the skin), decimated to
its share of 8,000 by visible skin area. The skin keeps its own UVs through the decimation, so the hull wears the bake,
the liveries and the roundels; the visible faces that are not skin (ducts, nozzles, glazing) take an empty corner of
the atlas, which is black. A part with no visible skin (the gear legs) keeps today's hull on the LOD material.

blender --background --python s5_lod.py -- [--force]"""
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

ctx = P.begin("s5_lod", __file__)
TARGET = 8_000
HELPER = ("Colliders", "LOD1")


def drawn(o):
    return o.type == "MESH" and "_lod1" not in o.name and "_colmesh" not in o.name and not any(c.name in HELPER for c in o.users_collection)


# visibility is judged with the wing extended: retracted, the stages' skin sits inside the outer wing, and their hulls
# came out as tip fragments, so the silhouette shrank at the switch with the wing out. The hulls are built there (in
# their own frames, which slide with the stages) and the stages go back to rest at the end.
import render_rig as L  # noqa: E402

L.set_extension(1.0)
bpy.context.view_layer.update()
verts, polys = [], []
for o in bpy.data.objects:
    if drawn(o) and not o.hide_render:
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        polys += [[base + i for i in p.vertices] for p in o.data.polygons]
WORLD = BVHTree.FromPolygons(verts, polys)


def empty_uv():
    """A point of the atlas no skin island covers, far from every island: its texels stay black in every map."""
    n = 128
    used = [[False] * n for _ in range(n)]
    for o in bpy.data.objects:
        if not drawn(o) or not o.data.uv_layers:
            continue
        sk = {i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN}
        uv = o.data.uv_layers[0].data
        for p in o.data.polygons:
            if p.material_index in sk:
                for li in p.loop_indices:
                    u, v = uv[li].uv
                    used[min(n - 1, max(0, int(v * n)))][min(n - 1, max(0, int(u * n)))] = True
    best, far = (0.995, 0.995), -1
    for i in range(n):
        for j in range(n):
            if used[i][j]:
                continue
            d = min((abs(i - a) + abs(j - b) for a in range(max(0, i - 6), min(n, i + 7)) for b in range(max(0, j - 6), min(n, j + 7)) if used[a][b]), default=99)
            if d > far:
                best, far = ((j + 0.5) / n, (i + 0.5) / n), d
    return best


DARK = empty_uv()


import damage_tree as T  # noqa: E402

PARTS = set(T.tree())
SURFACES = {n for n, s in T.tree().items() if s["kind"] == "surface"}


def own_meshes(owner):
    """The part's mesh and the meshes hanging under it (doors, hatches, fairings), not crossing into another part."""
    out, stack = [owner], list(owner.children)
    lower = bpy.data.objects.get(owner.name + "_lower")  # an aileron's lower half (s1) hangs beside it under the hinge
    if lower is not None:
        stack.append(lower)
    while stack:
        c = stack.pop()
        base = c.name.replace("_visible", "")
        if base in PARTS or not drawn(c) and c.type == "MESH":
            continue
        if c.type == "MESH" and drawn(c) and not c.name.startswith(("spoiler_L_", "spoiler_R_")):
            out.append(c)
        stack += list(c.children)
    return out


def exterior(owner):
    """The faces of the part's own meshes a viewer outside can see, in world space with their UVs: (bmesh, visible
    skin area)."""
    bm = bmesh.new()
    tw, is_skin = [], []
    for o in own_meshes(owner):
        me = o.data
        if not me.uv_layers:
            continue
        t = [0] * len(me.polygons)
        if "twin_src" in me.attributes:
            me.attributes["twin_src"].data.foreach_get("value", t)
        if "liner" in me.attributes:
            ln_ = [0] * len(me.polygons)
            me.attributes["liner"].data.foreach_get("value", ln_)
            t = [a or b for a, b in zip(t, ln_)]
        names = [m.name if m else "" for m in me.materials]
        pr = [0] * len(me.polygons)  # trim stage 4 painted on the skin's primer (s4_uv "primer"): structure, not hull
        if "primer" in me.attributes:
            me.attributes["primer"].data.foreach_get("value", pr)
        is_skin += [bool(names) and names[min(p.material_index, len(names) - 1)] == P.SKIN and not pr[p.index] for p in me.polygons]
        tw += t
        tmp = me.copy()
        tmp.transform(o.matrix_world)
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    for f, s in zip(bm.faces, is_skin):  # 0 skin, 1 anything else, for the steps below
        f.material_index = 0 if s else 1
    sk = {0}
    bm.faces.ensure_lookup_table()
    uvl = bm.loops.layers.uv.active or (bm.loops.layers.uv[0] if bm.loops.layers.uv else None)
    # the part's whole skin (no outward-ray filter: it dropped 913 of 1,992 nacelle faces and left holes, sol2 6); the
    # twins, liners and every non-skin face go, and each opening the part leaves (its cuts, an intake's mouth) is
    # closed by a cap on the atlas's black point, so the hull is a continuous silhouette
    gone = [f for f in bm.faces if tw[f.index] or f.material_index not in sk]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
    area = sum(f.calc_area() for f in bm.faces)
    before = set(bm.faces)
    bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
    for f in bm.faces:
        if f not in before and uvl is not None:
            for l in f.loops:
                l[uvl].uv = DARK
    return bm, area


lod_coll = bpy.data.collections.get("LOD1")
for s in sorted(SURFACES):  # the control surfaces had no hull: each gets its own, under its visible mesh
    vis = bpy.data.objects.get(s + "_visible")
    if vis is None or any("_lod1" in c.name for c in vis.children):
        continue
    h = bpy.data.objects.new(s + "_lod1", bpy.data.meshes.new(s + "_lod1"))
    (lod_coll or bpy.context.scene.collection).objects.link(h)
    h.parent = vis
    h.matrix_parent_inverse.identity()
    h.matrix_basis.identity()
bpy.context.view_layer.update()
owners = {}
for lod in [o for o in bpy.data.objects if o.type == "MESH" and "_lod1" in o.name and o.parent is not None]:
    bm, area = exterior(lod.parent)
    owners[lod.name] = (lod, bm, area)
total = sum(a for _, _, a in owners.values())
skin = bpy.data.materials.get(P.SKIN)
report = {}
for name, (lod, bm, area) in owners.items():
    if area <= 0 or not bm.faces or lod.parent.name.startswith("gear_"):
        bm.free()
        # a gear leg wears little skin and its wheels none: its hull is its own meshes, wheels included (sol2 6's gate: the wheels had none),
        # convex per mesh, on the LOD material
        gb = bmesh.new()
        for o in own_meshes(lod.parent):
            tmpm = o.data.copy()
            tmpm.transform(lod.matrix_world.inverted() @ o.matrix_world)
            part = bmesh.new()
            part.from_mesh(tmpm)
            bpy.data.meshes.remove(tmpm)
            if part.verts:
                hull = bmesh.ops.convex_hull(part, input=part.verts[:])
                bmesh.ops.delete(part, geom=[g for g in hull["geom_unused"] + hull["geom_interior"] if isinstance(g, bmesh.types.BMVert)], context="VERTS")
                for f in part.faces:  # source faces lying on the hull keep their own slot index: all onto the LOD slot
                    f.material_index = 0
                gm = bpy.data.meshes.new("g")
                part.to_mesh(gm)
                gb.from_mesh(gm)
                bpy.data.meshes.remove(gm)
            part.free()
        if gb.faces:
            bmesh.ops.triangulate(gb, faces=gb.faces[:])
            old = lod.data
            gm = bpy.data.meshes.new(lod.data.name + "_pass")
            gb.to_mesh(gm)
            gm.materials.append(bpy.data.materials.get("LOD") or bpy.data.materials.new("LOD"))
            lod.data = gm
            if old.users == 0:
                bpy.data.meshes.remove(old)
        gb.free()
        report[name] = {"tris": sum(len(p.vertices) - 2 for p in lod.data.polygons), "kept": "no skin: convex hulls of its own meshes on the LOD material"}
        continue
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.transform(lod.matrix_world.inverted())
    me = bpy.data.meshes.new(lod.data.name + "_pass")
    bm.to_mesh(me)
    bm.free()
    tris = len(me.polygons)
    want = max(24, round(TARGET * area / total))
    tmp = bpy.data.objects.new("lod_tmp", me)
    bpy.context.scene.collection.objects.link(tmp)
    if tris > want:
        # planar first: merging near-flat regions keeps the outline and the thin silhouette edges a collapse shrinks
        # (sol2 6 and this stage's gate: the inner wings' front silhouette lost 9%); then collapse what is left over
        pl = tmp.modifiers.new("planar", "DECIMATE")
        pl.decimate_type, pl.angle_limit, pl.delimit = "DISSOLVE", math.radians(4.0), {"UV"}
        tri = tmp.modifiers.new("tri", "TRIANGULATE")
        dg = bpy.context.evaluated_depsgraph_get()
        mid_ = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        if len(mid_.polygons) > want:
            tmp2 = bpy.data.objects.new("lod_tmp2", mid_)
            bpy.context.scene.collection.objects.link(tmp2)
            mod = tmp2.modifiers.new("dec", "DECIMATE")
            mod.decimate_type, mod.ratio, mod.use_collapse_triangulate = "COLLAPSE", want / len(mid_.polygons), True
            dg = bpy.context.evaluated_depsgraph_get()
            out = bpy.data.meshes.new_from_object(tmp2.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            bpy.data.objects.remove(tmp2)
            bpy.data.meshes.remove(mid_)
        else:
            out = mid_
    else:
        out = me.copy()
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(me)
    out.materials.clear()
    out.materials.append(skin)
    for p in out.polygons:
        p.material_index = 0
    out.shade_smooth()
    out.set_sharp_from_angle(angle=math.radians(40))
    old = lod.data
    lod.data = out
    if old.users == 0:
        bpy.data.meshes.remove(old)
    report[name] = {"tris": len(out.polygons), "want": want, "from": tris}
report["total_tris"] = sum(v["tris"] for v in report.values() if isinstance(v, dict))
report["dark_uv"] = DARK
def silhouettes(ext, n=120):
    """Six orthographic ray grids over the aircraft: where the detailed model is hit and the hulls are not (holes), and
    the reverse (spikes), as shares of the detailed silhouette (sol2 6: the nacelle hull was torn)."""
    L.set_extension(ext)
    bpy.context.view_layer.update()

    owner_of, first_poly = [], {}

    def tree_of(objs, record=False):
        vs, ps = [], []
        for o in objs:
            b = len(vs)
            vs += [o.matrix_world @ v.co for v in o.data.vertices]
            ps += [[b + i for i in p.vertices] for p in o.data.polygons]
            if record:
                first_poly[o.name] = len(owner_of)
                owner_of.extend((o.name, o.data.materials[p.material_index].name if o.data.materials and o.data.materials[p.material_index] else "") for p in o.data.polygons)
        return BVHTree.FromPolygons(vs, ps), vs
    detail, dv = tree_of([o for o in bpy.data.objects if drawn(o) and not o.hide_render], record=True)
    culprits = {}
    hulls, _ = tree_of([o for o in bpy.data.objects if o.type == "MESH" and "_lod1" in o.name])
    lo = Vector([min(v[i] for v in dv) for i in range(3)])
    hi = Vector([max(v[i] for v in dv) for i in range(3)])
    out = {}
    for axis in range(3):
        for sgn in (1, -1):
            a, b = [i for i in range(3) if i != axis]
            hits = holes = spikes = 0
            for i in range(n):
                for j in range(n):
                    p = Vector((0.0, 0.0, 0.0))
                    p[a] = lo[a] + (hi[a] - lo[a]) * (i + 0.5) / n
                    p[b] = lo[b] + (hi[b] - lo[b]) * (j + 0.5) / n
                    p[axis] = (hi[axis] + 1) if sgn > 0 else (lo[axis] - 1)
                    d = Vector((0.0, 0.0, 0.0))
                    d[axis] = -sgn
                    rd = detail.ray_cast(p, d, 200.0)
                    hd = rd[0] is not None
                    hh = hulls.ray_cast(p, d, 200.0)[0] is not None
                    hits += hd
                    holes += hd and not hh
                    if hd and not hh:
                        key_ = owner_of[rd[2]]
                        culprits.setdefault(("xyz"[axis],) + key_, []).append((tuple(round(c, 2) for c in rd[0]), tuple(round(c, 2) for c in rd[1]), rd[2] - first_poly[key_[0]]))
                    spikes += hh and not hd
            out[f"{'xyz'[axis]}{'+' if sgn > 0 else '-'}"] = (round(holes / max(hits, 1), 4), round(spikes / max(hits, 1), 4))
    for k_, v_ in sorted(culprits.items(), key=lambda kv: -len(kv[1]))[:14]:  # which part and slot the hulls miss, and where
        print("S5 holes", ext, k_, len(v_), v_[:: max(1, len(v_) // 4)][:4], flush=True)
    return out


sil = {"retracted": silhouettes(0.0), "extended": silhouettes(1.0)}
report["silhouettes_holes_spikes"] = sil
print("S5 silhouettes (holes, spikes)", sil, flush=True)
bad = {f"{k} {v}": s for k, d in sil.items() for v, s in d.items() if s[0] > 0.03 or s[1] > 0.05}
L.set_extension(0.0)
bpy.context.view_layer.update()
if bad:
    raise SystemExit(f"s5_lod: the hulls' silhouette misses or overshoots the detail's: {bad}")
print("S5 simple model", report["total_tris"], "triangles on", sum(1 for v in report.values() if isinstance(v, dict) and "want" in v), "hulls", flush=True)
P.finish(ctx, report)
