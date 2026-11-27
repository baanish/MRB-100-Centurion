"""Shared plumbing for the exterior pass stages (Blender side).

Each stage is one script: it opens the previous stage's blend, does its work, saves <PASS>/<stage>.blend and writes
<PASS>/<stage>.json (input and script hashes, Blender version, timings, its report), PASS being .cache/art/exterior_pass.
A stage whose record matches its current input and script is skipped, so the chain restarts from the first stale stage.

Stage order: s1_cut (seams bisected, coves, spoiler wells) -> s2_structure (closing members, wing and tail structure,
honeycomb cores) -> s3_twins (two-sided skin) -> s4_uv (livery split, unwrap, 6 px pack, twin and trim UVs) -> s5_lod
(hull coordinates and normals) -> s6_bake (the one bake: maps, damage map, liveries)."""
import hashlib
import json
import sys
import time
from pathlib import Path

import bpy

KIT = Path(__file__).resolve().parent
REPO = KIT.parents[2]
BASELINES = KIT / "baselines"
PASS = (REPO / ".cache" / "art" / "exterior_pass").resolve()
SOURCE = (REPO / ".cache" / "art" / "m4_parts" / "centurion_m4_parts.blend").resolve()
DETAIL = (REPO / ".cache" / "art" / "m4" / "centurion_m4_retracted.blend").resolve()
STAGES = ["s1_cut", "s2_structure", "s3_twins", "s4_uv", "s5_lod", "s6_bake"]
SKIN = "Centurion_skin"
sys.path.insert(0, str(REPO / "art" / "blender"))


def game_texture(name):
    """A texture from the builder's asset export of the game (`game_export` in tools/local-paths.json, its Assets
    folder), which the repository never holds: the stock jet_mechanical sheet the structure is mapped onto. Without
    one, the copies a remote run brings (Run-Pass.ps1 -Remote, in .cache/art/game_textures)."""
    paths = REPO / "tools" / "local-paths.json"
    root = json.loads(paths.read_text()).get("game_export") if paths.exists() else ""
    if not root and (REPO / ".cache" / "art" / "game_textures" / "Texture2D" / name).exists():
        root = REPO / ".cache" / "art" / "game_textures"
    if not root:
        raise SystemExit("set game_export in tools/local-paths.json (the game's asset export, its Assets folder)")
    path = Path(root) / "Texture2D" / name
    if not path.exists():
        raise SystemExit(f"{path} not found: game_export in tools/local-paths.json must hold the game's Texture2D")
    return path


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def kit_sha(script):
    """The stage script with every module it builds with."""
    mods = sorted(p for p in KIT.glob("*.py") if not p.name.startswith(("s1_", "s2_", "s3_", "s4_", "s5_", "s6_")))
    h = hashlib.sha256()
    for p in [Path(script)] + mods:
        h.update(sha(p).encode())
    return h.hexdigest()[:16]


def input_of(stage):
    i = STAGES.index(stage)
    return SOURCE if i == 0 else PASS / f"{STAGES[i - 1]}.blend"


def begin(stage, script):
    """Open the stage's input; exit 0 at once if its record is current (restartable), unless --force."""
    PASS.mkdir(parents=True, exist_ok=True)
    src = input_of(stage)
    if not src.exists():
        raise SystemExit(f"{stage}: input {src} is missing; run the stage before it")
    rec = PASS / f"{stage}.json"
    key = {"input": sha(src), "script": kit_sha(script), "blender": bpy.app.version_string}
    if rec.exists() and (PASS / f"{stage}.blend").exists() and "--force" not in sys.argv:
        old = json.loads(rec.read_text())
        if all(old.get(k) == v for k, v in key.items()):
            print(f"PASS {stage}: up to date, skipped", flush=True)
            raise SystemExit(0)
    bpy.ops.wm.open_mainfile(filepath=str(src))
    _TRACE[:] = [stage, 0]
    trace("input")
    return {"stage": stage, "t0": time.time(), **key}


def _arr(seq, attr, n, dtype):
    import numpy as np
    a = np.empty(len(seq) * n, dtype=dtype)
    seq.foreach_get(attr, a)
    return a.tobytes()


def mesh_hash(me):
    """A mesh's content, exactly: vertices, faces, material slots, UV layers and attributes."""
    import numpy as np
    h = hashlib.sha256()
    h.update(_arr(me.vertices, "co", 3, np.float32))
    h.update(_arr(me.polygons, "loop_total", 1, np.int32))
    h.update(_arr(me.loops, "vertex_index", 1, np.int32))
    h.update(_arr(me.polygons, "material_index", 1, np.int32))
    h.update(_arr(me.polygons, "use_smooth", 1, np.bool_))
    h.update(repr([m.name if m else None for m in me.materials]).encode())
    for uv in me.uv_layers:
        h.update(uv.name.encode())
        h.update(_arr(uv.data, "uv", 2, np.float32))
    kinds = {"FLOAT": (1, "value", np.float32), "INT": (1, "value", np.int32), "INT8": (1, "value", np.int32),
             "BOOLEAN": (1, "value", np.bool_), "FLOAT_VECTOR": (3, "vector", np.float32), "FLOAT2": (2, "vector", np.float32)}
    for at in sorted(me.attributes, key=lambda a: a.name):
        if at.name.startswith(".") or at.data_type not in kinds:
            continue
        n, key, dt = kinds[at.data_type]
        h.update(f"{at.name}:{at.domain}".encode())
        h.update(_arr(at.data, key, n, dt))
    return h.hexdigest()[:16]


def content_hashes():
    """Every object's type, parent, collections, transform, custom properties and mesh content, hashed exactly: two
    runs of a stage are the same when these are (a .blend's own bytes are not a measure: it stores addresses)."""
    import numpy as np
    out = {}
    for o in sorted(bpy.data.objects, key=lambda o: o.name):
        h = hashlib.sha256()
        h.update(f"{o.type}|{o.parent.name if o.parent else ''}|{sorted(c.name for c in o.users_collection)}".encode())
        h.update(np.array(o.matrix_world, dtype=np.float64).tobytes())
        h.update(repr(sorted((k, _prop(o[k])) for k in o.keys() if not k.startswith("_RNA"))).encode())
        if o.type == "MESH":
            h.update(mesh_hash(o.data).encode())
        out[o.name] = h.hexdigest()[:16]
    out["~scene"] = hashlib.sha256(repr(sorted((k, _prop(bpy.context.scene[k])) for k in bpy.context.scene.keys())).encode()).hexdigest()[:16]
    return out


def _prop(v):
    """A custom property's value without addresses: a datablock by its type and name (str() prints its address)."""
    if isinstance(v, bpy.types.ID):
        return f"{type(v).__name__}:{v.name}"
    if hasattr(v, "to_list"):
        return repr(v.to_list())
    if hasattr(v, "to_dict"):
        return repr(sorted(v.to_dict().items()))
    return repr(v)


ATLAS_PX = 4096
COLLAPSE_MIN_PX, COLLAPSE_THIN = 6.0, 0.05  # see uv_collapsed


def uv_stretch(p, uv):
    """The map from one triangle's surface to the atlas, as its two singular values in texels a metre (3D corners p,
    UV corners uv)."""
    import math
    e1, e2 = p[1] - p[0], p[2] - p[0]
    a = e1.length
    n = e1.cross(e2)
    if a < 1e-9 or n.length < 1e-12:
        return 0.0, 0.0
    x = e1 / a
    y = n.normalized().cross(x)
    bx, by = e2.dot(x), e2.dot(y)
    if abs(by) < 1e-9:  # a corner in line with the other two (a cut ngon's loop triangle): no surface to map
        return 0.0, 0.0
    d1, d2 = (uv[1] - uv[0]) * ATLAS_PX, (uv[2] - uv[0]) * ATLAS_PX
    j = ((d1.x / a, (d2.x - d1.x * bx / a) / by), (d1.y / a, (d2.y - d1.y * bx / a) / by))
    s = sum(v * v for row in j for v in row)
    det = abs(j[0][0] * j[1][1] - j[0][1] * j[1][0])
    big = math.sqrt(max(0.0, (s + math.sqrt(max(0.0, s * s - 4 * det * det))) / 2))
    return big, (det / big if big > 0 else 0.0)


def uv_collapsed(p, uv):
    """A triangle whose UVs collapse to a line: stretched one way (over COLLAPSE_MIN_PX texels a metre), almost nothing
    the other (under COLLAPSE_THIN of that). It smears a streak of whatever its line crosses; a triangle whose corners
    share one point is a flat colour and is not collapsed."""
    big, small = uv_stretch(p, uv)
    return big > COLLAPSE_MIN_PX and small < COLLAPSE_THIN * big


_TRACE = [None, 0]


def trace(step):
    """With PASS_TRACE=<tag> set, every object's content hash after this step, written to
    <PASS>/trace/<tag>_<stage>_<n>_<step>.json: two traced runs of a stage show the first step where they part."""
    import os
    tag = os.environ.get("PASS_TRACE")
    if not tag:
        return
    _TRACE[1] += 1
    d = PASS / "trace"
    d.mkdir(exist_ok=True)
    (d / f"{tag}_{_TRACE[0]}_{_TRACE[1]:02d}_{step}.json").write_text(json.dumps(content_hashes(), indent=0))


def finish(ctx, report):
    trace("output")
    out = PASS / f"{ctx['stage']}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(out), check_existing=False, compress=True)
    rec = {k: v for k, v in ctx.items() if k != "t0"}
    rec.update(seconds=round(time.time() - ctx["t0"], 1), output=str(out), output_sha=sha(out), report=report)
    (PASS / f"{ctx['stage']}.json").write_text(json.dumps(rec, indent=1, default=str))
    print(f"PASS {ctx['stage']}: done in {rec['seconds']} s -> {out}", flush=True)


def part_objects():
    """The 45 parts' meshes and their visible children (surfaces, doors), no helpers."""
    import damage_tree as T
    names = set(T.tree())
    out = {}
    for o in bpy.data.objects:
        if o.type != "MESH" or "_colmesh" in o.name or "_lod1" in o.name or o.name.endswith(("_blockout_mesh", "_shape")):
            continue
        if any(c.name in ("Colliders", "LOD1") for c in o.users_collection):
            continue
        out[o.name] = o
    return out, names


def slot(obj, mat_name):
    """The index of a material slot on obj, appending the material (created empty if new) when missing."""
    for i, m in enumerate(obj.data.materials):
        if m and m.name == mat_name:
            return i
    obj.data.materials.append(bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name))
    return len(obj.data.materials) - 1


def budget():
    return {r["part"]: r for r in json.loads((BASELINES / "budget.json").read_text())["parts"]}


def tris(obj, mats=None):
    me = obj.data
    return sum(len(p.vertices) - 2 for p in me.polygons
               if mats is None or (p.material_index < len(me.materials) and me.materials[p.material_index]
                                   and me.materials[p.material_index].name in mats))


def duplicate_faces(obj, where=None):
    """Faces lying exactly on another face of the same object with the same winding (stage
    2 built one centre-body ring twice, 1,138 such faces). The inward twins (opposite winding) are not counted. where,
    a list, collects each duplicate's first corner and material slot."""
    seen, dup = {}, 0
    mw = obj.matrix_world
    for p in obj.data.polygons:
        key = tuple(sorted(tuple(round(c, 5) for c in (mw @ obj.data.vertices[v].co)) for v in p.vertices))
        n = (mw.to_3x3() @ p.normal).normalized()
        for m in seen.get(key, []):
            if m.dot(n) > 0.99:
                dup += 1
                if where is not None:
                    where.append((key[0], p.material_index, len(p.vertices)))
                break
        seen.setdefault(key, []).append(n)
    return dup


def fill_holes(bm, edges):
    """bmesh.ops.holes_fill, then every boundary ring it gave up on (one clean ring, no ends or branches: the flap
    nose) closed as one ngon. Returns the new faces, not triangulated. Not for the distant model's hulls: capping the
    rings holes_fill leaves there raised its silhouette misses from 3% to 4%."""
    import bmesh
    filled = list(bmesh.ops.holes_fill(bm, edges=edges, sides=0)["faces"]) if edges else []
    left = dict.fromkeys(e for e in edges if e.is_valid and e.is_boundary)  # in the edges' order: a ring starts where
    while left:  # its first edge is, run after run (a set's pop() started it at whichever edge hashed first)
        e0 = next(iter(left))
        del left[e0]
        ring, v = [e0.verts[0]], e0.verts[1]
        while v is not ring[0]:
            ring.append(v)
            e1 = next((e for e in v.link_edges if e in left), None)
            if e1 is None:
                break
            del left[e1]
            v = e1.other_vert(v)
        if v is ring[0] and len(ring) >= 3:
            try:
                filled.append(bm.faces.new(ring))
            except ValueError:
                pass
    return filled


def folded_skin_edges(welded=False, back=False):
    """Skin folded over skin: two skin faces on one edge, in one plane, on the same side of it and facing the same way
    (s1's needle collapse once dragged a corner 0.7 m across wing_outer_L's lower skin). back=True counts the pairs
    facing opposite ways instead: an inner cap lying back to back with the skin, which the source has where parts
    butt (bay_A's bars end to end, a hinge bracket's base on the lower skin). welded=True measures a welded copy of
    each part, the baseline a stage is held to. Twins and liners are left out. {part: (edges, [(place, faces)])}."""
    import bmesh
    out = {}
    for name, o in part_objects()[0].items():
        me, mw = o.data, o.matrix_world
        if welded:
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
            me = bpy.data.meshes.new("_fold_probe")
            bm.to_mesh(me)
            bm.free()
            for m in o.data.materials:
                me.materials.append(m)
        sk = {i for i, m in enumerate(me.materials) if m and m.name == SKIN}
        skip = [0] * len(me.polygons)
        for an in ("twin_src", "liner"):
            a = me.attributes.get(an)
            if a is not None and a.domain == "FACE":
                v = [0] * len(me.polygons)
                a.data.foreach_get("value", v)
                skip = [x or y for x, y in zip(skip, v)]
        by_edge = {}
        for p in me.polygons:
            if p.material_index in sk and not skip[p.index]:
                for k in p.edge_keys:
                    by_edge.setdefault(k, []).append(p)
        bad = []
        for k, fs in by_edge.items():
            if len(fs) < 2:
                continue
            a, b = (mw @ me.vertices[i].co for i in k)
            d = (b - a).normalized()
            sides = []
            for p in fs:
                w = mw @ p.center - a
                w = (w - d * w.dot(d)).normalized()
                sides.append((w, (mw.to_3x3() @ p.normal).normalized()))
            pair = next(((fs[i].index, fs[j].index) for i in range(len(sides)) for j in range(i + 1, len(sides))
                         if sides[i][0].dot(sides[j][0]) > 0.9 and (sides[i][1].dot(sides[j][1]) < -0.98 if back else sides[i][1].dot(sides[j][1]) > 0.98)), None)
            if pair:
                bad.append(((a + b) / 2, pair))
        if welded:
            bpy.data.meshes.remove(me)
        if bad:
            out[name] = (len(bad), [(tuple(round(c, 3) for c in m), pr) for m, pr in bad[:4]])
    return out


def duplicate_gate(stage, before):
    """No part gains duplicated faces in this stage; before: {name: count} taken when the stage opened its input."""
    objs, _ = part_objects()
    after = {n: duplicate_faces(o) for n, o in objs.items()}
    worse = {n: (before.get(n, 0), c) for n, c in after.items() if c > before.get(n, 0)}
    if worse:
        at = {}
        for n in worse:
            duplicate_faces(objs[n], at.setdefault(n, []))
        raise SystemExit(f"{stage}: duplicated faces added: {worse}, at (corner, slot, sides) {({n: w[:4] for n, w in at.items()})}")
    return sum(after.values())
