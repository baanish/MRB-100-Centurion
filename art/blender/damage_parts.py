"""Re-cut the detailed Centurion into the 45-part damage tree (art/blender/damage_tree.py), in two Blender stages around
art/blender/damage_finalize.py:

    blender --background <detailed.blend> --python art/blender/damage_parts.py -- --stage cut --work <dir>
    python -I art/blender/damage_finalize.py <dir>
    blender --background <detailed.blend> --python art/blender/damage_parts.py -- --stage build --work <dir> --out <parts.blend>

The detailed blend is the export source of the 64-part aircraft (art/export/blockout.json's source_blend).

cut: for each new part, the old meshes it takes clipped by its cut planes (bmesh bisect), which give its share of each old
part's mass by skin area and the point cloud its collision shape is the convex hull of (after the part's own hull clips;
a control surface's shape is its visible mesh's). Also the 0.1.3 rigid bodies, for the centre of gravity to hold: each old
part's collider pieces (the "Colliders" collection), its pivot and mass. Writes <dir>/cut.json.

build: the parts blend tools/export_blockout.py exports. Each new part is a mesh object at its origin (damage_tree.ORIGINS)
holding the faces of its old meshes whose centroids fall inside its clips; no face is split, so every face keeps its UVs,
normals and material, and the textures need no rebake. The cuts leave open edges where a section meets its neighbour.
Its collision shapes (<dir>/parts.json from damage_finalize.py) go in "Colliders" under it, a control surface's under its
visible mesh; its LOD1 hull is the old LOD1 hulls' faces taken the same way; its _blockout_mesh is the blockout shape of
the old part it stands in for (damage_tree.SHAPE_OF, else the old part of its name), moved into its frame, which the
author measures the aero and fittings on. Doors, gear, hatches, fans, the laser turret, the spine covers and the control
surfaces' hinges stay their own objects under their new part.
"""
import json
import shutil
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import damage_tree as T  # noqa: E402

COLLECTION, COLLIDERS, LOD1 = "Centurion", "Colliders", "LOD1"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:]
    args = dict(zip([a.lstrip("-") for a in argv[0::2]], argv[1::2]))
    if args.get("stage") not in ("cut", "build") or "work" not in args or (args["stage"] == "build" and "out" not in args):
        raise SystemExit("usage: ... -- --stage cut|build --work DIR [--out PARTS.blend]")
    return args


def world_bmesh(obj):
    bm = bmesh.new()
    dg = bpy.context.evaluated_depsgraph_get()
    bm.from_object(obj.evaluated_get(dg), dg)
    bm.transform(obj.matrix_world)
    return bm


def mean_x(obj):
    me = obj.data
    return sum((obj.matrix_world @ v.co).x for v in me.vertices) / max(len(me.vertices), 1)


def planes_for(clip, cx):
    """(co, normal) planes whose positive side is kept; cx is the source's mean X (its side)."""
    out = []
    for axis, sign, value in clip:
        if axis in ("st", "z", "ax"):
            value -= 1e-3  # faces lying on a cut (bay walls, the bay roof) go to the side above, aft or outboard only
        elif axis == "x":
            value -= sign * 1e-3
        if axis == "st":
            out.append((Vector((0, value - T.ST0, 0)), Vector((0, sign, 0))))
        elif axis == "z":
            out.append((Vector((0, 0, value)), Vector((0, 0, sign))))
        elif axis in ("hinge", "hinge_own"):
            # the control surface's hinge line (its hinge empty's position and local X); the plane holds the line and
            # faces the surface's centroid, so the fixed part's shape ends at the hinge and the surface's starts there
            hinge = bpy.data.objects[sign]
            p = hinge.matrix_world.translation.copy()
            a = (hinge.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()
            vis = bpy.data.objects[sign + "_visible"]
            c = sum((vis.matrix_world @ v.co for v in vis.data.vertices), Vector()) / len(vis.data.vertices)
            n = (c - p) - (c - p).dot(a) * a
            n.normalize()
            out.append((p + n * value, n) if axis == "hinge_own" else (p + n * value, -n))
        elif axis == "x":
            out.append((Vector((value, 0, 0)), Vector((sign, 0, 0))))
        elif axis in ("stage_aft", "stage_fwd"):
            # the telescoping stages' trailing-edge line, square to the slide axis so it holds at every extension:
            # stage_aft keeps a control surface's shape aft of it plus `value`; stage_fwd keeps a shape forward of it
            s = 1 if cx >= 0 else -1
            n = Vector((-s * 0.25857, 0.96501, 0)).normalized()
            side = "L" if s > 0 else "R"
            te = max(n.dot(bpy.data.objects[st].matrix_world @ v.co) for st in (f"wing_tele1_{side}", f"wing_tele2_{side}")
                     for v in bpy.data.objects[st].data.vertices)
            out.append((n * (te + value), n) if axis == "stage_aft" else (n * (te - value), -n))
        elif axis == "ax" and sign > 0:
            s = 1 if cx >= 0 else -1
            out.append((Vector((s * value, 0, 0)), Vector((s, 0, 0))))
        elif axis == "ax":
            out.append((Vector((value, 0, 0)), Vector((-1, 0, 0))))
            out.append((Vector((-value, 0, 0)), Vector((1, 0, 0))))
    return out


def inside(point, planes):
    return all((point - co).dot(no) >= 0 for co, no in planes)


def clipped(bm, planes):
    for co, no in planes:
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no, clear_inner=True)
    return bm


def area(bm):
    return sum(f.calc_area() for f in bm.faces)


# ---------- cut ----------

def old_bodies():
    """The 0.1.3 rigid bodies: each mass part's pivot, mass and collider pieces (world vertices). A control surface's body
    was the hull of its visible mesh's blockout shape (CenturionAuthor.BuildSurfaces)."""
    out = {}
    pieces = {}
    for ob in bpy.data.collections[COLLIDERS].all_objects:
        if ob.type == "MESH" and ob.parent is not None:
            pieces.setdefault(ob.parent.name, []).append([list(ob.matrix_world @ v.co) for v in ob.data.vertices])
    for name, kg in T.PREFAB_KG.items():
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue  # the cockpit box part has no blend object
        hulls = pieces.get(name)
        if hulls is None:
            vis = bpy.data.objects[name + "_visible"]
            shape = vis.get("_blockout_mesh") or vis.data
            hulls = [[list(vis.matrix_world @ v.co) for v in shape.vertices]]
        out[name] = dict(kg=kg, pivot=list(ob.matrix_world.translation), hulls=hulls)
    return out


def stage_cut(work):
    t = T.tree()
    full_area = {}
    for ob in bpy.data.objects:
        if ob.type == "MESH":
            bm = world_bmesh(ob)
            full_area[ob.name] = area(bm)
            bm.free()
    out = {}
    for name, p in t.items():
        hull_pts, mass, rows = {}, 0.0, []
        for src, clip in p["sources"]:
            ob = bpy.data.objects.get(src)
            if ob is None or ob.type != "MESH":
                raise SystemExit(f"{name}: source {src} missing")
            cx = mean_x(ob)
            bm = clipped(world_bmesh(ob), planes_for(clip, cx))
            if not bm.faces:
                bm.free()
                continue
            a = area(bm)
            owner = src.replace("_visible", "")
            share = T.PREFAB_KG.get(owner, 0.0) * a / full_area[src]
            mass += share
            rows.append(dict(source=src, kg=round(share, 3), area=round(a, 3)))
            if p["hull_clip"]:
                clipped(bm, planes_for(p["hull_clip"], cx))
            group = next((k for k, g in enumerate(p["hull_groups"]) if src in g), 0)
            hull_pts.setdefault(group, []).extend(list(v.co) for v in bm.verts)
            bm.free()
        if name == "cockpit":
            mass += T.PREFAB_KG["cockpit"]
            rows.append(dict(source="cockpit (0.1.3 box part)", kg=T.PREFAB_KG["cockpit"], area=0))
        for vis in p["visual"]:
            mass += T.PREFAB_KG[vis]
            rows.append(dict(source=vis, kg=T.PREFAB_KG[vis], area=0))
        out[name] = dict(kind=p["kind"], parent=p["parent"], braces=p["braces"], donor=p["donor"], base_kg=mass,
                         sources=rows, hull_points=[hull_pts[k] for k in sorted(hull_pts)])
    (work / "cut.json").write_text(json.dumps(dict(parts=out, old=old_bodies())))
    print(f"[damage_parts] cut {len(out)} parts, {sum(v['base_kg'] for v in out.values()):.1f} kg by skin share")


# ---------- build ----------

def source_groups():
    """Detail object name -> its group's number (1 up, in detail_centurion.GROUPS' order), the number the exterior pass
    paints each face by. Recorded on every face as it is cut (face attribute source_group), so the pass never has to
    guess a face's group from whatever detail blend lies nearest (it handed three aft flank faces to the sponson's painter
    and clipped the serial to "043")."""
    import detail_centurion as DC
    from m4 import partition
    # a group's objects are its PARTS and the pieces part_splits cuts from them (tail_end_upper, fuselage_F_upper...),
    # as detail_centurion.swap_group holds it to
    return {name: i + 1 for i, (g, mod) in enumerate(DC.GROUPS.items())
            for name in list(mod.PARTS) + partition.piece_names(mod.PARTS)}


def world_mesh(src):
    """src's evaluated mesh (modifiers applied, as the exporter takes it) in world space."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(src.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    me.transform(src.matrix_world)
    return me


def faces_inside(mesh, planes_list):
    """Per face of a world-space mesh, the index of the first planes set its centroid satisfies, or -1."""
    return [next((i for i, pl in enumerate(planes_list) if inside(poly.center, pl)), -1) for poly in mesh.polygons]


def corners(me, faces=None):
    """Corner normals and first UVs of the given faces (all by default), face by face, corner by corner."""
    normals = me.corner_normals
    uv = me.uv_layers[0].data if me.uv_layers else None
    out = []
    for poly in (me.polygons if faces is None else (me.polygons[f] for f in faces)):
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            out.append(tuple(normals[li].vector) + (tuple(uv[li].uv) if uv else (0.0, 0.0)))
    return np.array(out).reshape(-1, 5)


def unmoved(name, before, after):
    """Normals within their 16-bit storage's rounding (0.3 degrees), UVs exactly. A degenerate face's corners have no
    normal in the source (zero length); Blender gives them one, which is no change."""
    if after.shape != before.shape:
        raise SystemExit(f"{name}: the re-cut changed its corner count, {before.shape} to {after.shape}")
    real = np.linalg.norm(before[:, :3], axis=1) > 0.5
    d = np.r_[np.abs(after - before)[real].max(0)[:3], np.abs(after - before).max(0)[3:]]
    if d[:3].max() > 5e-3 or d[3:].max() > 1e-6:
        raise SystemExit(f"{name}: the re-cut moved a normal by {d[:3].max():.4f} or a UV by {d[3:].max():.6f}")


def piece(world, keep, name):
    """A copy of a world-space mesh with only the faces whose flags in keep are set. Custom normals are stored relative
    to each corner's fan of faces, which the cut changes at its edge, so the kept corners get their normals back."""
    kept = [i for i, k in enumerate(keep) if k]
    before = corners(world, kept)
    me = world.copy()
    me.name = name
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f, k in zip(bm.faces, keep) if not k], context="FACES")
    bm.to_mesh(me)
    bm.free()
    if world.has_custom_normals:
        me.normals_split_custom_set([tuple(r[:3]) for r in before])
    unmoved(name, before, corners(me))
    return me


def merge(meshes, name):
    """One mesh of the given ones, their material slots united and every corner's normal kept."""
    mats, normals, custom = [], [], any(m.has_custom_normals for m in meshes)
    bm = bmesh.new()
    for me in meshes:
        remap = []
        for m in me.materials:
            if m not in mats:
                mats.append(m)
            remap.append(mats.index(m))
        start = len(bm.faces)
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        for f in bm.faces[start:]:
            f.material_index = remap[f.material_index] if remap else 0
        normals.append(corners(me))
    out = bpy.data.meshes.new(name)
    bm.to_mesh(out)
    bm.free()
    for m in mats:
        out.materials.append(m)
    expected = np.vstack(normals)
    if custom:
        out.normals_split_custom_set([tuple(r[:3]) for r in expected])
    unmoved(name, expected, corners(out))
    for me in meshes:
        bpy.data.meshes.remove(me)
    return out


def place(ob, origin, parent):
    """Puts a world-space mesh object's origin at `origin`, unrotated, under `parent` with its location in the parent's
    frame (as the source blend parents, which the exporter's rest_location assumes), the mesh where it was."""
    ob.data.transform(Matrix.Translation(-Vector(origin)))
    world = Matrix.Translation(Vector(origin))
    if parent is not None:
        ob.parent = parent
        ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.matrix_basis = parent.matrix_world.inverted() @ world
    else:
        ob.matrix_basis = world
    bpy.context.view_layer.update()  # matrix_world is only recomputed on an update; the part's children read it
    if (ob.matrix_world.translation - Vector(origin)).length > 1e-6:
        raise SystemExit(f"{ob.name} landed at {ob.matrix_world.translation}, not {origin}")


def hull_object(name, hull, frame, coll, parent):
    """A collider piece: hull dict(v=world vertices, f=triangles) in the frame of `parent` (whose world matrix is frame)."""
    inv = frame.inverted()
    me = bpy.data.meshes.new(name)
    me.from_pydata([list(inv @ Vector(v)) for v in hull["v"]], [], hull["f"])
    me.update()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.parent = parent
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = Matrix.Identity(4)
    return ob


def stage_build(work, out_path):
    t = T.tree()
    final = json.loads((work / "parts.json").read_text())["parts"]
    centurion = bpy.data.collections[COLLECTION]
    colliders = bpy.data.collections[COLLIDERS]
    lods = bpy.data.collections[LOD1]
    old_parts = [n for n in T.PREFAB_KG if bpy.data.objects.get(n) is not None and bpy.data.objects[n].type == "MESH"]

    # where each face of each old mesh goes: (old object -> [(part, planes)]) from every part's render sources
    takers = {}
    for name, p in t.items():
        if p["kind"] == "surface":
            continue
        for src, clip in p["sources"]:
            if src not in p["hull_only"]:
                ob = bpy.data.objects[src]
                takers.setdefault(src, []).append((name, planes_for(clip, mean_x(ob))))
        for vis in p["visual"]:
            takers.setdefault(vis, []).append((name, []))
    lod_of = {ob.parent.name: ob for ob in lods.all_objects if ob.parent is not None}
    # the old objects step aside so the new parts take their names (an old part's own name included)
    old = {n: bpy.data.objects[n] for n in old_parts}
    taken = {n: bpy.data.objects[n] for n in takers}
    for ob in set(old.values()) | set(taken.values()):
        ob.name = "old." + ob.name

    pieces, lod_pieces, report = {}, {}, {}
    group_of = source_groups()
    for src, parts in takers.items():
        world = world_mesh(taken[src])
        sg = world.attributes.get("source_group") or world.attributes.new("source_group", "INT", "FACE")
        sg.data.foreach_set("value", [group_of.get(src.split(".")[0], 0)] * len(world.polygons))
        owner = faces_inside(world, [pl for _, pl in parts])
        missing = owner.count(-1)
        if missing:
            raise SystemExit(f"{src}: {missing} of {len(owner)} faces fall in no part's clips")
        for i, (name, _) in enumerate(parts):
            keep = [o == i for o in owner]
            if any(keep):
                pieces.setdefault(name, []).append(piece(world, keep, f"{name}<{src}"))
                report.setdefault(name, []).append(f"{src} {sum(keep)}/{len(keep)}")
        bpy.data.meshes.remove(world)
        lod = lod_of.get(src)
        if lod is not None:
            world = world_mesh(lod)
            # a LOD1 hull face outside every clip stays with the first taker
            lod_owner = [max(o, 0) for o in faces_inside(world, [pl for _, pl in parts])]
            for i, (name, _) in enumerate(parts):
                keep = [o == i for o in lod_owner]
                if any(keep):
                    lod_pieces.setdefault(name, []).append(piece(world, keep, f"{name}<{lod.name}"))
            bpy.data.meshes.remove(world)

    # the parts, parents before children
    made = {}
    order = []
    def visit(n):
        if n in order:
            return
        if t[n]["parent"]:
            visit(t[n]["parent"])
        order.append(n)
    for n in t:
        visit(n)
    for name in order:
        p = t[name]
        if p["kind"] == "surface":
            continue
        ob = bpy.data.objects.new(name, merge(pieces[name], name))
        centurion.objects.link(ob)
        parent = made.get(p["parent"])
        place(ob, T.ORIGINS[name], parent)
        ob["mass_kg"] = final[name]["mass"]
        shapes = []
        for o in T.SHAPE_OF.get(name, [name] if name in old else []):
            src = old[o]
            m = (src.get("_blockout_mesh") or src.data).copy()
            m.transform(ob.matrix_world.inverted() @ src.matrix_world)
            shapes.append(m)
        if shapes:
            shape = shapes[0]
            if len(shapes) > 1:
                bm = bmesh.new()
                for m in shapes:
                    bm.from_mesh(m)
                bm.to_mesh(shape)
                bm.free()
            shape.name = name + "_blockout"
            shape.materials.clear()
            ob["_blockout_mesh"] = shape
        if p["kind"] == "stage":
            src = old[name]
            for key in ("slide_axis", "travel_m", "chord_m", "thickness_m", "col_ref_m3", "tip_qc"):
                if key in src:
                    ob[key] = src[key]
        made[name] = ob
        for k, hull in enumerate(final[name]["hulls"]):
            hull_object(f"{name}_colmesh{k}", hull, ob.matrix_world, colliders, ob)
        if name in lod_pieces:
            lod = bpy.data.objects.new(name + "_lod1", merge(lod_pieces[name], name + "_lod1"))
            lods.objects.link(lod)
            lod.data.transform(ob.matrix_world.inverted())
            lod.parent = ob
            lod.matrix_parent_inverse = Matrix.Identity(4)
            lod.matrix_basis = Matrix.Identity(4)

    # stages: the exporter puts each at rest_location (its local location on its slide parent) before exporting
    for name, ob in made.items():
        if t[name]["kind"] == "stage":
            ob["rest_location"] = list(ob.matrix_local.translation)

    # control surfaces: their shapes under their visible meshes
    for name, p in t.items():
        if p["kind"] != "surface":
            continue
        vis = bpy.data.objects[name + "_visible"]
        bpy.data.objects[name]["part_origin"] = list(T.ORIGINS[name])  # the surface part's origin; its hinge is the empty
        for k, hull in enumerate(final[name]["hulls"]):
            hull_object(f"{name}_visible_colmesh{k}", hull, vis.matrix_world, colliders, vis)

    # rigs and hinges onto their new parts, where they stand
    for name, p in t.items():
        for rig in p["rigs"]:
            r = bpy.data.objects[rig]
            host = made[name]
            mw = r.matrix_world.copy()
            r.parent = host
            r.matrix_parent_inverse = host.matrix_world.inverted()
            r.matrix_world = mw
            bpy.context.view_layer.update()
            if (r.matrix_world.translation - mw.translation).length > 1e-5:
                raise SystemExit(f"{rig} moved re-parenting onto {name}")
    for spine in ("spine_cover", "spine_cover_A"):
        if "mass_kg" in bpy.data.objects[spine]:
            del bpy.data.objects[spine]["mass_kg"]  # fuselage_R's mass has it, as 0.1.3's did

    # a mesh with no mass of its own that the parts took (the tail radar's fairing) leaves an empty where it stood, under
    # the part that took most of it, for the fittings placed on it
    for n, ob in taken.items():
        if n in old:
            continue
        host = max(takers[n], key=lambda tp: sum(int(r.split()[-1].split("/")[0]) for r in report.get(tp[0], []) if r.startswith(n + " ")))[0]
        marker = bpy.data.objects.new(n, None)
        centurion.objects.link(marker)
        marker.parent = made[host]
        marker.matrix_parent_inverse = made[host].matrix_world.inverted()
        marker.matrix_world = ob.matrix_world.copy()
        bpy.context.view_layer.update()

    # the old parts and every mesh the parts took, their collider pieces and LOD1 hulls go
    doomed = [old[n] for n in old_parts] + [ob for n, ob in taken.items() if n not in old]
    doomed += [ob for ob in colliders.all_objects if ob.parent in doomed]
    doomed += [ob for ob in lods.all_objects if ob.parent in doomed]
    orphans = [ob.name for ob in bpy.data.objects if ob.parent in doomed and ob not in doomed]
    if orphans:
        raise SystemExit(f"objects still hang on old parts: {orphans}")
    for ob in doomed:
        bpy.data.objects.remove(ob)
    leftovers = [o.name for o in centurion.objects if o.type == "MESH" and o.parent is None and o.name != "Centurion"]
    if leftovers:
        raise SystemExit(f"meshes left without a part: {leftovers}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    source_textures = Path(bpy.data.filepath).parent / "textures"
    if source_textures.exists():
        shutil.copytree(source_textures, out_path.parent / "textures", dirs_exist_ok=True)
    # the detailed blend these parts were cut from, by its bytes
    bpy.context.scene["detail_source_sha256"] = __import__("hashlib").sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()
    # the meshes kept whole (the surfaces, the doors) are their detail objects: their group by their own name
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name not in colliders.all_objects and o.name not in lods.all_objects]
    for me in dict.fromkeys(o.data for o in meshes if "source_group" not in o.data.attributes):
        names = [o.name for o in meshes if o.data is me]
        g = next((group_of[n.split(".")[0]] for n in names if n.split(".")[0] in group_of), 0)
        me.attributes.new("source_group", "INT", "FACE").data.foreach_set("value", [g] * len(me.polygons))
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path))
    (work / "build_report.json").write_text(json.dumps(report, indent=1))
    print(f"[damage_parts] built {len(made)} parts, {sum(len(h['hulls']) for h in final.values())} collider pieces, "
          f"{len(lod_pieces)} LOD1 hulls: {out_path}")


def main():
    args = parse_args()
    work = Path(args["work"]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if args["stage"] == "cut":
        stage_cut(work)
    else:
        stage_build(work, Path(args["out"]).resolve())


main()
