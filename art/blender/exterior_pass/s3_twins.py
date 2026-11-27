"""Pass stage 3, two-sided skin where it can be seen from inside: an inward copy of each skin face s2 tagged `opens`
(a hole can open it, or its back is seen through one), in the same mesh, slot and UVs. Everywhere else the skin stays
one-sided and the triangles go to structure, as the Darkreach's outer wing does (78 two-sided pairs). Doors, hatches
and gear stay one-sided, as the Darkreach's gear doors and canopy frame are. Each copy carries the face attribute `twin_src` (its original's index + 1; 0 on originals), so
s4_uv gives it its original's UVs after the repack. UNTESTED (written while Blender was unavailable).

blender --background --python s3_twins.py -- [--force]"""
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

LINER_DEPTH = 0.012

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

ctx = P.begin("s3_twins", __file__)
SINGLE = ("geardoor_", "baydoor_", "nose_hatch", "nose_door", "gear_", "wheel_", "fan_", "laser_")
LINED = ("wing_root", "wing_outer", "wing_tele", "vtail", "strut_", "pylon_")
objs, _ = P.part_objects()
report = {}
for name, o in sorted(objs.items()):
    # SINGLE parts are closed shells, where an inward copy faces into the solid; on a gear door it also cancels the
    # skin's facing, which the authoring reads to find the way the door shuts (CenturionAuthor.CloseGearDoor)
    if name.startswith(("pass_",) + SINGLE):
        continue
    skin = [i for i, m in enumerate(o.data.materials) if m and m.name == P.SKIN]
    if not skin:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.faces.ensure_lookup_table()
    src = bm.faces.layers.int.get("twin_src") or bm.faces.layers.int.new("twin_src")
    ln = bm.faces.layers.int.get("liner") or bm.faces.layers.int.new("liner")  # before any face is held: a new layer frees them
    tv = bm.loops.layers.int.get("twin_vert") or bm.loops.layers.int.new("twin_vert")  # each twin corner's original vertex + 1
    bm.verts.index_update()
    op = bm.faces.layers.int.get("opens")  # s2: the skin a hole can open and the skin seen through one
    if op is None:
        raise SystemExit(f"s3_twins: {name} has no `opens` tags from s2")
    originals = [f for f in bm.faces if f.material_index in skin and f[src] == 0 and f[op]]
    dup = bmesh.ops.duplicate(bm, geom=originals)
    new_faces = [g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)]
    fresh = set(new_faces)
    bmesh.ops.reverse_faces(bm, faces=new_faces)
    fresh_v = {v for f_ in new_faces for v in f_.verts}
    orig_of = {b: a for a, b in dup["vert_map"].items() if b in fresh_v and a not in fresh_v}
    for f_a, f_b in dup["face_map"].items():  # the map holds both directions: tag only the copies
        if f_b in fresh and f_a not in fresh:
            f_b[src] = f_a.index + 1
            for l in f_b.loops:  # the corner's original vertex, so s4 gives it exactly its original corner's UV (sol2: 298 twins drifted)
                l[tv] = orig_of[l.vert].index + 1
    untagged = [f for f in new_faces if f[src] == 0]
    if untagged:
        raise SystemExit(f"s3_twins: {name}: {len(untagged)} copies lost their original")
    if name.startswith(LINED):
        # In the wings, tails, struts and pylons the inward copy is a liner 12 mm in: through a hole in one skin the
        # opposite skin's inside showed painted and lit (round 3, and the pass's review); the liner is dark (s4 gives
        # it the atlas's empty black corner) and, facing inward on the culled skin material, never hides its own
        # skin's holes. Same triangles, same slot.
        bm.normal_update()
        push = {}
        for f_ in new_faces:
            f_[ln] = 1
            for v in f_.verts:
                push[v] = push.get(v, Vector()) + f_.normal  # the faces' mean, not the last face's
        # each liner vertex goes LINER_DEPTH in, or 40% of the way to the skin across from it where the shell is thinner:
        # a fixed 12 mm carried the pylons' liner tabs out past their thin ends
        tree_ = BVHTree.FromBMesh(bm)
        for v, n in push.items():
            if n.length < 1e-9:
                continue
            n = n.normalized()
            hit = tree_.ray_cast(v.co + n * 0.0005, n, 1.0)
            d = (hit[0] - v.co).length if hit[0] is not None else 1.0
            v.co += n * min(LINER_DEPTH, 0.4 * d)
    bm.to_mesh(o.data)
    bm.free()
    report[name] = len(new_faces)
report["total_twin_faces"] = sum(v for v in report.values())

# the stage channels kept clear once more, now the stages' own inward copies exist (s2 cleared against stand-ins at fixed
# depths; one backdrop face of wing_outer_R still met tele1_R's liner, which sits up to 12 mm or 40% of the way in):
# a part's inner faces (not its skin) crossing a nested stage, anywhere in its travel, go
cleared = {}
for o in [o for o in bpy.data.objects if o.type == "MESH" and any(s.parent == o and "slide_axis" in s for s in bpy.data.objects)]:
    vs, ps = [], []
    for s in [s for s in bpy.data.objects if s.type == "MESH" and s.parent == o and "slide_axis" in s]:
        ws = [s.matrix_world @ v.co for v in s.data.vertices]
        for ext in (0.0, 0.25, 0.5, 0.75, 1.0):
            d = (o.matrix_world @ s.matrix_parent_inverse).to_3x3() @ (Vector(s["slide_axis"]) * (s["travel_m"] * ext))
            b = len(vs)
            vs += [p + d for p in ws]
            ps += [[b + i for i in q.vertices] for q in s.data.polygons]
    nest = BVHTree.FromPolygons(vs, ps)
    skin_i = P.slot(o, P.SKIN)
    cb = bmesh.new()
    cb.from_mesh(o.data)
    cb.transform(o.matrix_world)
    inner = [f for f in cb.faces if f.material_index != skin_i]
    iv, ip = [], []
    for f in inner:
        ip.append(list(range(len(iv), len(iv) + len(f.verts))))
        iv += [v.co.copy() for v in f.verts]
    gone = sorted({i for i, _ in BVHTree.FromPolygons(iv, ip).overlap(nest)}) if ip else []
    if gone:
        bmesh.ops.delete(cb, geom=[inner[i] for i in gone], context="FACES")
        cb.transform(o.matrix_world.inverted())
        cb.to_mesh(o.data)
    cb.free()
    cleared[o.name] = len(gone)
report["stage_channel_cleared"] = cleared
print("S3 stage channels cleared", cleared, flush=True)
import fairing  # noqa: E402
if fairing.variant_on():  # the twins are new loose parts: none of a fairing's may land on its flap
    report["fairing_leftovers"] = fairing.leftovers()
    if any(report["fairing_leftovers"].values()):
        raise SystemExit(f"s3: flap faces left inside a fairing that swings away: {report['fairing_leftovers']}")
P.finish(ctx, report)
