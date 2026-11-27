"""Skin triangles whose UVs collapse to a line (pass_common.uv_collapsed): such a face smears a streak of whatever its
line crosses (the split ailerons' closing faces drew the roundel's green that way). Reports per object, the moving
surfaces and doors first, each triangle's place; fails when any skin triangle collapses.
blender --background <blend> --python check_uv_collapse.py -- [<out.json>]"""
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

MOVING = ("flap_", "aileron_", "spoiler_", "ruddervator_", "baydoor_", "geardoor_", "nose_door", "nose_hatch")


def helper(o):
    return "_colmesh" in o.name or "_lod1" in o.name or o.name.endswith(("_blockout_mesh", "_shape")) or any(
        c.name in ("Colliders", "LOD1") for c in o.users_collection)


rows, tris = {}, 0
for o in sorted(bpy.data.objects, key=lambda o: o.name):
    if o.type != "MESH" or helper(o) or not o.data.uv_layers:
        continue
    me = o.data
    names = [m.name if m else "" for m in me.materials]
    if P.SKIN not in names:
        continue
    skin = names.index(P.SKIN)
    uv = me.uv_layers.active.data
    me.calc_loop_triangles()
    for lt in me.loop_triangles:
        if lt.material_index != skin or lt.area < 1e-5:
            continue
        if P.uv_collapsed([me.vertices[v].co for v in lt.vertices], [uv[i].uv for i in lt.loops]):
            r = rows.setdefault(o.name, [0, 0.0])
            r[0] += 1
            r[1] += lt.area
            tris += 1
            c = o.matrix_world @ lt.center
            print("UVCOLLAPSE  ", o.name, "at", [round(x, 2) for x in c], "m2", round(lt.area, 3),
                  "uv", [tuple(round(x, 3) for x in uv[i].uv) for i in lt.loops], flush=True)
order = sorted(rows.items(), key=lambda kv: (not kv[0].startswith(MOVING), -kv[1][1]))
for name, (n, m2) in order:
    print("UVCOLLAPSE", name, "triangles", n, "m2", round(m2, 3), flush=True)
print("UVCOLLAPSE total skin triangles", tris, flush=True)
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args:
    Path(args[0]).write_text(json.dumps([{"object": k, "triangles": v[0], "m2": round(v[1], 4)} for k, v in order], indent=1))
if tris:
    raise SystemExit(f"check_uv_collapse: {tris} skin triangles collapse to a line across the atlas")
