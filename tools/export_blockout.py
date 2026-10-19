"""Export the Centurion blockout parts for Unity: one FBX per part plus blockout.json.

blender --background --factory-startup --python tools/export_blockout.py -- --blend <file.blend> [--out DIR]

Every mesh directly in the blend's "Centurion" collection is a part, exported in its retracted pose: a telescoping
stage that carries "rest_location" goes back to it first. Empties (control-surface and door hinges) are listed with
their pivot and axes and no FBX. Each <out>/<part>.fbx holds, at the origin:
- <part>, the render mesh in its own local space (origin = pivot, axes = the object's), with its custom split normals
  and one submesh per material slot;
- <part>_colmesh0, <part>_colmesh1, ...: the part's authored convex collider pieces, the objects of the "Colliders"
  collection parented to it with an identity transform (a part with none gets no collider);
- <part>_lod1: its LOD1 hull from the "LOD1" collection, parented the same way, with the 0.14 grey vertex colour
  "Col" written linear, so the stock LOD material reads it raw;
- <part>_shape, on a detailed (M4) part only: the blockout's mesh it replaced (the object's _blockout_mesh), which
  CenturionAuthor measures the aero, colliders and fittings on, so the detail never changes how the aircraft flies.
These are art/blender/build_centurion.py's step 3 conventions; its checks keep the pieces convex, inset and under
Unity's 255-triangle convex limit, which this script checks again. A detailed (M4) blend names the maps it baked into
textures/ beside it (its scene's m4_textures, art/blender/detail_centurion.py): each is copied to <out>/textures/ and
listed under "textures" with its hash, for CenturionAuthor's skin and trims.

FBX axis settings are .cache/research/art.md section 3: Blender (x, y, z) lands in Unity as (-x, z, -y), so the
nose (Blender -Y) is Unity +Z and the left wing (Blender +X) is Unity -X. blockout.json records each part's pivot,
local bounds, material slots with their triangle counts, and custom properties in both frames; CenturionAuthor
checks every imported mesh against it. Default --out is <repo>/art/export. Files this script wrote last time
are removed first (one by one, from the previous blockout.json), so a renamed part leaves nothing stale.
"""

import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from scrub_fbx import scrub_file
COLLECTION, COLLIDERS, LOD1 = "Centurion", "Colliders", "LOD1"
MAX_HULL = 255  # Unity's convex MeshCollider limit, in triangles


def to_unity(v):
    return [round(-v[0], 5), round(v[2], 5), round(-v[1], 5)]


def axes_unity(rotation):
    """The object's rotation as its Unity right, up and forward axes. With M the Blender-to-Unity basis change,
    Unity's rotation is M R M^T; its columns are M R applied to the Blender vectors that M maps to X, Y, Z."""
    m = rotation.to_matrix()
    basis = {"right": Vector((-1, 0, 0)), "up": Vector((0, 0, 1)), "forward": Vector((0, -1, 0))}
    return {key: to_unity(m @ v) for key, v in basis.items()}


def bounds_unity(lo, hi):
    a, b = to_unity(lo), to_unity(hi)
    return [min(a[i], b[i]) for i in range(3)], [max(a[i], b[i]) for i in range(3)]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = {"blend": None, "out": str(REPO / "art/export")}
    it = iter(argv)
    for flag in it:
        key = flag.lstrip("-")
        if key not in args:
            raise SystemExit(f"unknown argument {flag}")
        args[key] = next(it)
    if not args["blend"]:
        raise SystemExit("usage: ... -- --blend <file.blend> [--out DIR]")
    for key in ("blend", "out"):
        if not Path(args[key]).is_absolute():
            args[key] = str((Path.cwd() / args[key]).resolve())  # Blender resolves relative paths oddly
    return args


def json_value(value):
    if hasattr(value, "to_list"):
        return value.to_list()
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def retract(objs):
    for obj in objs:
        if "rest_location" in obj:
            obj.location = Vector(obj["rest_location"])
    bpy.context.view_layer.update()


def evaluated_mesh(obj, name):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    mesh.name = name
    return mesh


def tris(mesh):
    return sum(len(p.vertices) - 2 for p in mesh.polygons)


def material_tris(mesh):
    """Material slots in order with their triangle counts: Unity makes one submesh per used slot, in this order."""
    counts = [0] * len(mesh.materials)
    for p in mesh.polygons:
        counts[p.material_index] += len(p.vertices) - 2
    return [[m.name if m else "", n] for m, n in zip(mesh.materials, counts) if n > 0]


def children_in(collection_name, objects):
    """Objects of a sub-collection by the name of the part they are parented to, each checked to sit exactly on it."""
    coll = bpy.data.collections.get(collection_name)
    if coll is None:
        raise SystemExit(f"no '{collection_name}' collection; export needs a step 3 blockout or later")
    result = {}
    for obj in sorted(coll.all_objects, key=lambda o: o.name):
        if obj.type != "MESH" or obj.parent is None or obj.parent.name not in objects:
            raise SystemExit(f"{collection_name}/{obj.name} is not a mesh parented to a {COLLECTION} part")
        offset = obj.parent.matrix_world.inverted() @ obj.matrix_world
        if any(abs(offset[i][j] - Matrix.Identity(4)[i][j]) > 1e-5 for i in range(4) for j in range(4)):
            raise SystemExit(f"{obj.name} is not at an identity transform under {obj.parent.name}")
        result.setdefault(obj.parent.name, []).append(obj)
    return result


def mesh_bounds(mesh):
    lo = [min(v.co[i] for v in mesh.vertices) for i in range(3)]
    hi = [max(v.co[i] for v in mesh.vertices) for i in range(3)]
    return lo, hi


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_fbx(path, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    # Unity's import silently drops an n-gon it finds self-intersecting under its own projection, and a non-planar
    # face can pass Blender's test yet fail Unity's; exported as triangles, nothing is left to drop. Counts are equal.
    for obj in objects:
        if obj.type == "MESH":
            tri = obj.modifiers.new("export_ngons", "TRIANGULATE")
            tri.min_vertices, tri.ngon_method, tri.keep_custom_normals = 5, "BEAUTY", True
    # No tangents: they need triangles or quads, and Unity computes its own on import.
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH", "EMPTY"},
                             apply_scale_options="FBX_SCALE_ALL", axis_forward="-Z", axis_up="Y",
                             bake_space_transform=True, mesh_smooth_type="FACE", use_tspace=False, colors_type="LINEAR",
                             add_leaf_bones=False, bake_anim=False, path_mode="STRIP")
    scrub_file(path)


def remove_previous(out):
    manifest = out / "blockout.json"
    if not manifest.exists():
        return
    previous = json.loads(manifest.read_text(encoding="utf-8"))
    for part in previous.get("parts", {}).values():
        stale = out / (part["fbx"] or "")
        if part["fbx"] and stale.exists():
            stale.unlink()
    for name in previous.get("textures", {}):
        stale = out / "textures" / name
        if stale.exists():
            stale.unlink()
    manifest.unlink()


def copy_textures(blend, out):
    """The detailed blend's baked maps (its scene's m4_textures), copied beside the FBXs: {file name: sha256}."""
    source = Path(blend).parent / "textures"
    maps = [source / name for name in bpy.context.scene.get("m4_textures", [])]
    missing = [p.name for p in maps if not p.exists()]
    if missing:
        raise SystemExit(f"{blend} names maps that are not in {source}: {', '.join(missing)}")
    if maps:
        (out / "textures").mkdir(exist_ok=True)
    for p in maps:
        (out / "textures" / p.name).write_bytes(p.read_bytes())
    return {p.name: sha256(p) for p in maps}


def main():
    args = parse_args()
    out = Path(args["out"])
    out.mkdir(parents=True, exist_ok=True)
    remove_previous(out)
    bpy.ops.wm.open_mainfile(filepath=args["blend"])
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        raise SystemExit(f"no '{COLLECTION}' collection in {args['blend']}")
    objs = [o for o in coll.objects if o.type in ("MESH", "EMPTY")]
    retract(objs)
    by_name = {o.name: o for o in objs}
    parts = sorted(by_name)
    colliders = children_in(COLLIDERS, by_name)
    lods = children_in(LOD1, by_name)

    # Free the part names for the exported objects: Unity names an imported mesh after its FBX node.
    parent_of = {o.name: o.parent.name if o.parent else None for o in objs}
    for obj in coll.all_objects:
        obj.name = "source_" + obj.name
    scratch = bpy.data.collections.new("export_scratch")
    bpy.context.scene.collection.children.link(scratch)
    report = {}
    for name in parts:
        obj = by_name[name]
        pivot, rotation, scale = obj.matrix_world.decompose()
        if any(abs(s - 1) > 1e-5 for s in scale):
            raise SystemExit(f"{name}: scale is not 1; apply it in the blockout")
        props = {k: json_value(obj[k]) for k in obj.keys() if not k.startswith("_")}
        for key in ("slide_axis", "spin_axis"):
            if key in props:
                props[key + "_unity"] = to_unity(props[key])
        entry = {"fbx": None, "blender_parent": parent_of[name], "pivot_blender": [round(c, 5) for c in pivot],
                 "pivot_unity": to_unity(pivot), "axes_unity": axes_unity(rotation), "props": props}
        report[name] = entry
        if obj.type == "EMPTY":
            continue
        meshes = [(name, evaluated_mesh(obj, name))]
        meshes += [(f"{name}_colmesh{i}", evaluated_mesh(c, f"{name}_colmesh{i}")) for i, c in enumerate(colliders.get(name, []))]
        if "_blockout_mesh" in obj:
            shape = obj["_blockout_mesh"].copy()
            shape.name = f"{name}_shape"
            shape.materials.clear()
            meshes.append((shape.name, shape))
        if name in lods:
            if len(lods[name]) > 1:
                raise SystemExit(f"{name} has {len(lods[name])} LOD1 hulls; expected one")
            meshes.append((f"{name}_lod1", evaluated_mesh(lods[name][0], f"{name}_lod1")))
        temps = [bpy.data.objects.new(n, m) for n, m in meshes]
        for temp in temps:
            scratch.objects.link(temp)
        fbx = out / f"{name}.fbx"
        export_fbx(fbx, temps)

        render = meshes[0][1]
        lo, hi = mesh_bounds(render)
        pieces = []
        for piece_name, mesh in meshes[1:]:
            if piece_name.endswith(("_lod1", "_shape")):
                continue
            if len(mesh.vertices) > MAX_HULL or tris(mesh) > MAX_HULL:
                raise SystemExit(f"{piece_name}: {len(mesh.vertices)} vertices, {tris(mesh)} triangles; Unity's convex limit is {MAX_HULL}")
            clo, chi = mesh_bounds(mesh)
            pieces.append({"name": piece_name, "verts": len(mesh.vertices), "tris": tris(mesh), "bounds_unity": list(bounds_unity(clo, chi))})
        lod = next((m for n, m in meshes if n.endswith("_lod1")), None)
        shape = next((m for n, m in meshes if n.endswith("_shape")), None)
        entry.update({
            "fbx": fbx.name,
            "sha256": sha256(fbx),
            "bounds_blender": [[round(c, 5) for c in lo], [round(c, 5) for c in hi]],
            "bounds_unity": list(bounds_unity(lo, hi)),
            "tris": tris(render),
            "materials": material_tris(render),
            "colliders": pieces,
            "lod1": {"tris": tris(lod)} if lod else None,
        })
        if shape:
            entry["shape"] = {"tris": tris(shape), "bounds_blender": [[round(c, 5) for c in v] for v in mesh_bounds(shape)]}
        for temp in temps:
            bpy.data.objects.remove(temp)
        for _, mesh in meshes:
            bpy.data.meshes.remove(mesh)

    manifest = {
        # Repo-relative, since the export is committed in the public repo and an absolute path names this machine.
        "source_blend": Path(args["blend"]).resolve().relative_to(REPO).as_posix() if Path(args["blend"]).resolve().is_relative_to(REPO) else Path(args["blend"]).name,
        "source_sha256": sha256(args["blend"]),
        "axes": "Unity = (-x, z, -y) of Blender; pivots are world positions, bounds are part-local (in axes_unity)",
        "parts": report,
        "textures": copy_textures(args["blend"], out),
    }
    (out / "blockout.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    meshes = [p for p in report.values() if p["fbx"]]
    print(f"[export_blockout] {len(meshes)} meshes and {len(report) - len(meshes)} empties to {out}; "
          f"{sum(len(p['colliders']) for p in meshes)} collider pieces on {sum(1 for p in meshes if p['colliders'])} parts, "
          f"{sum(1 for p in meshes if p['lod1'])} LOD1 hulls ({sum(p['lod1']['tris'] for p in meshes if p['lod1'])} tris), "
          f"{len(manifest['textures'])} textures")


if __name__ == "__main__":
    main()
