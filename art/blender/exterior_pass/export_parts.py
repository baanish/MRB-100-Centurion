"""What the export needs from the stage 6 blend beyond the bake.
- The spoiler actuators into the export. tools/export_blockout.py exports the meshes directly in the "Centurion"
  collection; s1 builds each spoiler's two actuators (cylinder on the wing, rod on the spoiler's hinge) in its own
  `pass_spoiler_<side>` collection, so the first staged export left all eight out. Stage 6 links them into "Centurion"
  as well; each then exports as its own FBX under its parent (EXPORT.md section 2).
- No degenerate triangles. Unity's model import drops a triangle whose corners weld to two or fewer points, and
  CenturionAuthor.ImportBlockout then finds a slot one triangle short of blockout.json and stops (tail_end's trim,
  4,191 against 4,192). Such faces carry no texels, so removing them changes no map.
- The source's normals again. The source carries custom split normals (build_centurion.bake_normals: hard over 50
  degrees or at a material change, face-area weighted); the stages' mesh rebuilds lose them, and smooth vertex normals
  shade across the spine lids' 1 cm joint dips as ramps of light and dark (the owner's dorsal strip: corners up to 27
  degrees off their faces). They are baked once more, the same way, on the triangles that export, and the hull's and
  radome's faces keep the fuselage surface's own normals the source gave them (detail_centurion.hull_normals, which the
  stages carry): face-area weighting per part split their shading wherever a part or a damage piece ends, a 3 to 6
  degree step along the forward fuselage's flanks and round the radome's joint.
Standalone, on a finished stage 6 blend (no rebake):  blender --background <blend> --python export_parts.py -- --save"""
import sys

import bmesh
import bpy

WELD_M = 1e-5  # corners closer than this weld into one point on import


def actuators_into_export():
    top = bpy.data.collections["Centurion"]
    linked = []
    for side in ("L", "R"):
        for o in bpy.data.collections[f"pass_spoiler_{side}"].objects:
            if o.type == "MESH" and o.name not in top.objects:
                top.objects.link(o)
                linked.append(o.name)
    return sorted(linked)


def _degenerate(a, b, c):
    longest = max((a - b).length, (b - c).length, (c - a).length)
    shortest = min((a - b).length, (b - c).length, (c - a).length)
    return shortest < WELD_M or (b - a).cross(c - a).length < WELD_M * max(longest, WELD_M) * 0.1  # under a micron tall


def drop_degenerate():
    """Every exported mesh as triangles, its degenerate ones removed. A quad with three collinear corners holds a
    zero-height triangle on one diagonal; Unity triangulates polygons its own way and drops what comes out degenerate, so
    only an export of triangles keeps its counts equal to blockout.json's."""
    from m4.texture import triangulate_split
    dropped = {}
    for o in bpy.data.collections["Centurion"].objects:
        if o.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        triangulate_split(bm, [f for f in bm.faces if len(f.verts) > 3], o.name)  # as the bake's proxy is (m4/texture.py)
        gone = [f for f in bm.faces if _degenerate(*(v.co for v in f.verts))]
        bmesh.ops.delete(bm, geom=gone, context="FACES_ONLY")
        bm.to_mesh(o.data)
        bm.free()
        if gone:
            dropped[o.name] = len(gone)
    return dropped


def export_normals():
    """Every exported mesh's split normals baked as the source's were (build_centurion.bake_normals). Returns hard
    edges per mesh."""
    import build_centurion as BC
    objs = {o.name: o for o in bpy.data.collections["Centurion"].objects if o.type == "MESH"}
    kept = {n: surface_normals(o.data) for n, o in objs.items()}
    hard = BC.bake_normals(objs)
    for n, o in objs.items():
        if kept[n]:
            loops = [tuple(c.vector) for c in o.data.corner_normals]
            for li, v in kept[n].items():
                loops[li] = v
            o.data.normals_split_custom_set(loops)
    share_part_seams(objs, kept)
    flat_inner_faces(objs)
    return hard


def flat_inner_faces(objs):
    """Each split aileron half's flat inner face shades as one plane: stage 1's sliver merges leave end-rib corners up
    to 3.5 mm off the cut plane, which tilts a few of the face's 3 m sliver triangles by up to 17 degrees, and flat
    shaded they drew a diagonal line across the open split's face (audit of build 49, finding 5). Moving those corners
    onto the plane moved them toward the other half and failed the split gate, so the shading takes the plane instead:
    every loop of the face, the area-weighted mean of its faces' normals."""
    from mathutils import Vector
    out = {}
    for n, o in objs.items():
        if not (n.startswith("aileron_") and n.endswith(("_visible", "_visible_lower"))):
            continue
        me, r3 = o.data, o.matrix_world.to_3x3()
        cls, prim = me.attributes.get("cls"), me.attributes.get("primer")
        if cls is None or prim is None:
            continue
        sign = 1 if n.endswith("_lower") else -1  # the lower half's inner face looks up, the upper's down
        faces = [p for p in me.polygons if prim.data[p.index].value and cls.data[p.index].value == 19
                 and (r3 @ p.normal).normalized().z * sign > 0.9]
        if not faces:
            continue
        plane = sum((p.normal * p.area for p in faces), Vector()).normalized()
        loops = [tuple(c.vector) for c in me.corner_normals]
        for p in faces:
            for li in p.loop_indices:
                loops[li] = tuple(plane)
        me.normals_split_custom_set(loops)
        out[n] = len(faces)
    print("EXPORT PARTS split halves' inner faces shaded flat, faces", out, flush=True)


SEAM_SMOOTH_DEG = 25.0  # parts' faces meeting closer than this at a shared point are one surface and shade as one


def share_part_seams(objs, kept):
    """One normal at every point where two parts' outward skin faces meet as one smooth surface: the fuselage surface's
    own normal where a part keeps it (hull, radome), else the mean of the loops there. Each part baked its own rim
    normals, 3 to 11 degrees apart across a part edge (Centurion, fuselage_R, bay_A and the sponson behind the wing root),
    and under a low sun that split drew rectangular tone blocks along the part edges (audit of build 49, findings 12
    and 14). Faces meeting at a sharper angle (a wing root on the hull) keep their own."""
    import math
    from collections import defaultdict

    from mathutils import Vector
    lim = math.cos(math.radians(SEAM_SMOOTH_DEG))
    at = defaultdict(list)  # world point -> [(part, loop, world loop normal, world face normal, kept)]
    for n, o in objs.items():
        if any(t in n for t in ("_lod1", "_colmesh", "_shape")):  # the far model and colliders are no part of the skin
            continue
        me, mw = o.data, o.matrix_world
        r3 = mw.to_3x3()
        skin = {i for i, m in enumerate(me.materials) if m and m.name == "Centurion_skin"}
        tw = me.attributes.get("twin_src")
        for p in me.polygons:
            if p.material_index not in skin or (tw is not None and tw.data[p.index].value):
                continue
            fn = (r3 @ p.normal).normalized()
            for li in p.loop_indices:
                w = mw @ me.vertices[me.loops[li].vertex_index].co
                at[tuple(round(c, 4) for c in w)].append((n, li, (r3 @ me.corner_normals[li].vector).normalized(), fn, li in kept[n]))
    new = defaultdict(dict)  # part -> {loop: world normal}
    for ls in at.values():
        if len({e[0] for e in ls}) < 2:
            continue
        for n, li, ln, fn, _ in ls:
            group = [e for e in ls if e[3].dot(fn) >= lim]
            if len({e[0] for e in group}) < 2:
                continue
            ref = [e[2] for e in group if e[4]]
            v = ref[0] if ref else sum((e[2] for e in group), Vector()).normalized()
            if v.angle(ln) > 1e-4:
                new[n][li] = v
    for n, ch in new.items():
        o = objs[n]
        inv = o.matrix_world.to_3x3().inverted()
        loops = [tuple(c.vector) for c in o.data.corner_normals]
        for li, v in ch.items():
            loops[li] = tuple((inv @ v).normalized())
        o.data.normals_split_custom_set(loops)
    print("EXPORT PARTS part seams shaded as one surface, loops per part", {n: len(c) for n, c in sorted(new.items())}, flush=True)


SURFACE_CLASSES = (1, 2)  # m4/surface.py HULL and RADOME: the faces detail_centurion.hull_normals sets


def surface_normals(me):
    """{loop: normal} of the outer faces on the fuselage surface's own normals (stage 3's inward twins left out)."""
    cls, twin = me.attributes.get("cls"), me.attributes.get("twin_src")
    if cls is None or cls.domain != "FACE":
        return {}
    return {li: tuple(me.corner_normals[li].vector) for p in me.polygons
            if cls.data[p.index].value in SURFACE_CLASSES and not (twin is not None and twin.data[p.index].value)
            for li in p.loop_indices}


if __name__ == "__main__" and "--save" in sys.argv:
    print("EXPORT PARTS linked", actuators_into_export(), flush=True)
    print("EXPORT PARTS degenerate faces dropped", drop_degenerate(), flush=True)
    print("EXPORT PARTS normals, hard edges", sum(export_normals().values()), flush=True)
    bpy.ops.wm.save_mainfile()
