"""The bake's AO on the outward skin, per part, against the shipped bake (intact painted triangles
baked near AO zero). For every exposed outward skin face (twins, liners and UV copies left out; exposed: a ray along its
normal, or tilted 30 degrees four ways, leaves the aircraft, as stage 2's exterior shell; skin buried under another
layer, such as the V-tail root's, bakes dark rightly and nobody sees it) the AO map is read at its UV centroid; per
part, the area share under DARK and the area-weighted mean. Run on the parts blend with the shipped AO
once, writing baselines/ao_shipped.json; on the pass's stage 5 blend with the pass's AO, held to it:
- the whole skin's dark share at most the shipped share plus WHOLE_SLACK;
- each part's dark share at most its shipped share plus PART_SLACK (parts the pass renames compare by base name; a part
  with no shipped counterpart is held to the whole skin's shipped share, and listed).
blender --background <blend> --python check_ao.py -- <ao.png> <out.json> [--against baselines/ao_shipped.json]"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

DARK = 0.15  # the diagnosis's black patches sat at AO 38 to 44 of 255 (0.15 to 0.17)
WHOLE_SLACK = 0.01
PART_SLACK = 0.05  # a part's dark share moves with its new UV layout and cut edges; five points is a visible patch
args = sys.argv[sys.argv.index("--") + 1:]
im = bpy.data.images.load(str(Path(args[0]).resolve()))  # (Blender reads a bare relative path against the drive root)
w, h = im.size
px = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, im.channels)[..., 0]
out = Path(args[1]).resolve()
against = Path(args[args.index("--against") + 1]).resolve() if "--against" in args else None
def flags(me, names):
    out = [0] * len(me.polygons)
    for name in names:
        a = me.attributes.get(name)
        if a is not None and a.domain == "FACE":
            v = [0] * len(me.polygons)
            a.data.foreach_get("value", v)
            out = [x or y for x, y in zip(out, v)]
    return out


render = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and "_lod1" not in o.name and "_colmesh" not in o.name
          and not o.name.endswith(("_blockout_mesh", "_shape")) and not any(c.name in ("Colliders", "LOD1") for c in o.users_collection)]
vs, ps = [], []
for o in render:  # the aircraft as it is seen: no twins or liners (they face inward)
    me, mw = o.data, o.matrix_world
    inward = flags(me, ("twin_src", "liner"))
    b = len(vs)
    vs += [mw @ v.co for v in me.vertices]
    ps += [[b + i for i in p.vertices] for p in me.polygons if not inward[p.index]]
tree = BVHTree.FromPolygons(vs, ps)


def exposed(c, n):
    t = n.orthogonal().normalized()
    u = n.cross(t)
    for d in (n, (n + t * 0.577).normalized(), (n - t * 0.577).normalized(), (n + u * 0.577).normalized(), (n - u * 0.577).normalized()):
        if tree.ray_cast(c + n * 0.001, d, 100.0)[0] is None:
            return True
    return False


parts, tot = {}, np.zeros(3)
for o in render:
    me = o.data
    sk = {i for i, m in enumerate(me.materials) if m and m.name == "Centurion_skin"}
    if not sk or not me.uv_layers:
        continue
    skip = flags(me, ("twin_src", "liner", "uv_copy"))
    mw, nm = o.matrix_world, o.matrix_world.to_3x3().inverted().transposed()
    uv = me.uv_layers[0].data
    acc = np.zeros(3)  # area, dark area, area x AO
    for p in me.polygons:
        if p.material_index not in sk or skip[p.index] or not exposed(mw @ p.center, (nm @ p.normal).normalized()):
            continue
        u = sum(uv[li].uv.x for li in p.loop_indices) / p.loop_total
        v = sum(uv[li].uv.y for li in p.loop_indices) / p.loop_total
        val = float(px[min(h - 1, max(0, int(v * h))), min(w - 1, max(0, int(u * w)))])
        acc += (p.area, p.area * (val < DARK), p.area * val)
    if acc[0] > 0:
        parts[o.name] = {"dark_share": round(acc[1] / acc[0], 4), "mean": round(acc[2] / acc[0], 3), "skin_m2": round(acc[0], 2)}
        tot += acc
report = {"whole": {"dark_share": round(tot[1] / tot[0], 4), "mean": round(tot[2] / tot[0], 3), "skin_m2": round(tot[0], 1)}, "parts": parts}
fails = []
if against is not None:
    ship = json.loads(against.read_text())
    if report["whole"]["dark_share"] > ship["whole"]["dark_share"] + WHOLE_SLACK:
        fails.append(f"whole skin dark share {report['whole']['dark_share']} over shipped {ship['whole']['dark_share']} + {WHOLE_SLACK}")
    report["held_to_whole"] = []
    for n, r in parts.items():
        s = ship["parts"].get(n) or ship["parts"].get(n.replace("_visible", ""))
        if s is None:  # a part the pass creates or splits (a fairing, a lower aileron half): no shipped part to compare
            report["held_to_whole"].append(n)
            s = ship["whole"]
        if r["dark_share"] > s["dark_share"] + PART_SLACK:
            fails.append(f"{n}: dark share {r['dark_share']} over shipped {s['dark_share']} + {PART_SLACK}")
    report["fails"] = fails
out.write_text(json.dumps(report, indent=1))
print("AO whole", report["whole"], "|", len(fails), "fails", fails[:8], "| held to the whole skin's share:", report.get("held_to_whole"), flush=True)
if fails:
    raise SystemExit("check_ao: " + "; ".join(fails[:12]))
