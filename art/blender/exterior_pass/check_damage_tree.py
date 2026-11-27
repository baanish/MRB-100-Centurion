"""Check that a pass blend keeps the damage worker's tree: the 45 parts and every object the authoring reads (names,
types, parents, world transforms, custom properties such as mass_kg, collider meshes in world space, blockout shapes),
against the parts blend. Render meshes and the pass's own new objects are expected to differ and are listed apart.
blender --background --python check_damage_tree.py -- <pass.blend> [<out.json>]"""
import hashlib
import json
import sys
from pathlib import Path

import bpy

KIT = Path(__file__).resolve().parent
REPO = KIT.parents[2]
sys.path.insert(0, str(REPO / "art" / "blender"))
import damage_tree as T  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
SOURCE = REPO / ".cache" / "art" / "m4_parts" / "centurion_m4_parts.blend"


def vhash(me, mw):
    h = hashlib.sha256()
    for v in me.vertices:
        h.update(str(tuple(round(c, 5) for c in (mw @ v.co))).encode())
    return h.hexdigest()[:12]


def props(o):
    out = {}
    for k in o.keys():
        if k.startswith("_RNA") or k == "cycles":
            continue
        v = o[k]
        if hasattr(v, "vertices"):
            from mathutils import Matrix
            out[k] = f"mesh:{vhash(v, Matrix.Identity(4))} {v.name} {len(v.vertices)}v{' =own data' if v == o.data else ''}"
        elif hasattr(v, "to_list"):
            out[k] = [round(x, 5) if isinstance(x, float) else x for x in v.to_list()]
        elif isinstance(v, float):
            out[k] = round(v, 5)
        elif isinstance(v, (int, str)):
            out[k] = v
        else:
            out[k] = str(type(v))
    return out


def snapshot():
    snap = {}
    for o in bpy.data.objects:
        colls = [c.name for c in o.users_collection]
        col = "Colliders" in colls
        snap[o.name] = {
            "type": o.type, "parent": o.parent.name if o.parent else None, "collections": sorted(colls),
            "world": [round(x, 5) for row in o.matrix_world for x in row], "props": props(o),
            "collider_mesh": vhash(o.data, o.matrix_world) if col and o.type == "MESH" else None,
            "render_mesh": vhash(o.data, o.matrix_world) if o.type == "MESH" and not col else None,
        }
    return snap


bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
a = snapshot()
bpy.ops.wm.open_mainfile(filepath=str(Path(args[0]).resolve()))
b = snapshot()
parts = set(T.tree())
missing = sorted(set(a) - set(b))
added = sorted(set(b) - set(a))
diff = {}
render_changed = []
for n in sorted(set(a) & set(b)):
    for k in ("type", "parent", "collections", "world", "props", "collider_mesh"):
        if a[n][k] != b[n][k]:
            d = diff.setdefault(n, {})
            if k == "world":
                d[k] = round(max(abs(x - y) for x, y in zip(a[n][k], b[n][k])), 5)
            elif k == "props":
                d[k] = {p: (a[n][k].get(p), b[n][k].get(p)) for p in set(a[n][k]) | set(b[n][k]) if a[n][k].get(p) != b[n][k].get(p)}
            else:
                d[k] = (a[n][k], b[n][k])
    if a[n]["render_mesh"] != b[n]["render_mesh"]:
        render_changed.append(n)
mass = {n: (a[n]["props"].get("mass_kg"), b[n]["props"].get("mass_kg")) for n in parts if n in a and n in b}
report = {"parts_in_tree": len(parts), "parts_present": sum(1 for n in parts if n in b and b[n]["type"] in ("MESH", "EMPTY")),
          "missing": missing, "added": added, "changed_besides_render_mesh": diff, "render_mesh_changed": len(render_changed),
          "mass_kg_differs": {n: v for n, v in mass.items() if v[0] != v[1]},
          "colliders_compared": sum(1 for n in a if a[n]["collider_mesh"])}
print("COMPARE", json.dumps(report), flush=True)
if len(args) > 1:
    Path(args[1]).resolve().write_text(json.dumps(report, indent=1))
