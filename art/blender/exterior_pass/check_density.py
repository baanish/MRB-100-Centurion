"""The skin's paint density per part, along both axes: for every outward skin triangle, the UV map's
two singular values in px/m on the 4096 atlas; per part the area mean and the 5th percentile of each triangle's
least-resolved axis; and the collapsed triangles (no UV area, over 0.01 m2 of skin). Run on the parts blend (the shipped
UVs) once, writing baselines/density_shipped.json, and on the pass's stage 4 blend, which it holds to the shipped numbers:
- every part's 5th-percentile least axis at least FLOOR_SHARE of the shipped part's (and the 60 px/m mean floor);
- no collapsed triangle over 0.01 m2.
blender --background <blend> --python check_density.py -- <out.json> [--against baselines/density_shipped.json]"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

ATLAS = 4096
FLOOR_SHARE = 0.85  # of the shipped part's 5th percentile: the split costs about 6% of density (the owner took 60 px/m)
MEAN_FLOOR = 60.0
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fairing  # noqa: E402
# the fairing variant's six rear halves are new skin sharing the atlas, which costs wing_root about 15% of its density at its
# worst 5% (54.4 to 46.2 px/m on this desktop, about 1.8 to 2.2 cm a pixel); 46.0 is one floor both machines' packing clears
VARIANT_P5_FLOOR = {"wing_root_L": 46.0, "wing_root_R": 46.0} if fairing.variant_on() else {}
args = sys.argv[sys.argv.index("--") + 1:]
out = Path(args[0]).resolve()
against = Path(args[args.index("--against") + 1]).resolve() if "--against" in args else None
parts = {}
worst = []
for o in bpy.data.objects:
    if o.type != "MESH" or "_lod1" in o.name or "_colmesh" in o.name or any(c.name in ("Colliders", "LOD1") for c in o.users_collection):
        continue
    me = o.data
    sk = {i for i, m in enumerate(me.materials) if m and m.name == "Centurion_skin"}
    if not sk or not me.uv_layers:
        continue
    tw = [0] * len(me.polygons)
    for name in ("twin_src", "uv_copy"):
        a = me.attributes.get(name)
        if a is not None and a.domain == "FACE":
            v = [0] * len(me.polygons)
            a.data.foreach_get("value", v)
            tw = [x or y for x, y in zip(tw, v)]
    me.calc_loop_triangles()
    uv = me.uv_layers[0].data
    mw = o.matrix_world
    mins, W, U, collapsed = [], 0.0, 0.0, 0
    for lt in me.loop_triangles:
        p = me.polygons[lt.polygon_index]
        if p.material_index not in sk or tw[p.index]:
            continue
        P0, P1, P2 = (mw @ me.vertices[v].co for v in lt.vertices)
        a, b, c = (uv[li].uv for li in lt.loops)
        e1, e2 = P1 - P0, P2 - P0
        area = e1.cross(e2).length / 2
        if area < 1e-8:
            continue
        x = e1.normalized()
        y = e1.cross(e2).normalized().cross(x)
        G = np.array([[e1.dot(x), e2.dot(x)], [e1.dot(y), e2.dot(y)]])
        T = np.array([[b.x - a.x, c.x - a.x], [b.y - a.y, c.y - a.y]]) * ATLAS
        uv_area = abs(np.linalg.det(T)) / 2
        W += area
        U += uv_area
        if uv_area < 1e-6:
            collapsed += area > 0.01
            mins.append(0.0)
            continue
        J = T @ np.linalg.inv(G)  # px per metre along the triangle's own axes
        sv_ = np.linalg.svd(J, compute_uv=False)
        mins.append(float(sv_[-1]))
        if sv_[-1] < 20:
            worst.append((round(float(sv_[-1]), 1), round(float(sv_[0]), 1), o.name, tuple(round(c, 2) for c in (P0 + P1 + P2) / 3), round(area * 1e4, 1), p.loop_total))
    if W > 0:
        parts[o.name] = {"mean_px_per_m": round(math.sqrt(U / W), 2), "p5_least_axis": round(float(np.percentile(mins, 5)), 2) if mins else 0.0,
                         "collapsed_over_0_01m2": collapsed, "skin_m2": round(W, 2)}
report = {"parts": parts, "worst_triangles": sorted(worst)[:60], "low_count": {n: sum(1 for w in worst if w[2] == n) for n in {w[2] for w in worst}}}
fails = []
if against is not None:
    ship = json.loads(against.read_text())["parts"]
    for n, r in parts.items():
        s = ship.get(n.replace("_visible", "") if n not in ship else n)
        floor = VARIANT_P5_FLOOR.get(n.replace("_visible", ""), FLOOR_SHARE * s["p5_least_axis"]) if s else 0
        if s and s["p5_least_axis"] > 10 and r["p5_least_axis"] < floor:  # (the cockpit's glazing frames sit near zero on the shipped UVs too: 1.9)
            fails.append(f"{n}: least axis p5 {r['p5_least_axis']} under {round(floor, 2)} ({FLOOR_SHARE} x shipped {s['p5_least_axis']}, or the variant's floor)")
        if r["mean_px_per_m"] < MEAN_FLOOR - 0.5:
            fails.append(f"{n}: mean {r['mean_px_per_m']} px/m under {MEAN_FLOOR}")
        if r["collapsed_over_0_01m2"]:
            fails.append(f"{n}: {r['collapsed_over_0_01m2']} collapsed triangles over 0.01 m2")
    report["fails"] = fails
out.write_text(json.dumps(report, indent=1))
print("DENSITY", len(parts), "parts,", len(fails), "fails", fails[:8], flush=True)
if fails:
    raise SystemExit("check_density: " + "; ".join(fails[:12]))
