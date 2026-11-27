"""The flap fairings' pivots (baselines/fairing_hinges.json). Turned through its flap's angle about its own pivot, a rear
half moves against its flap by one translation, (R^-1 - I)(pivot - hinge): it slides aft along the flap's underside
and drifts off that line, by about 4.8% of the pivot's drop below the hinge across 0 to 30 degrees (1.8 m down: 17 cm
into the flap at 30). The search keeps, for each rear half, the pivot with the least drift across POSES (fairing.trim
then cuts the rear half CLEAR_M under the flap at its closest, so the drift is the seam's whole variation) of those
that still move its tail TAIL_AFT_M aft at 30 degrees, the owner's approved motion (aft and down with the flap), and
keep its sleeve's front inside the shroud. A left fairing and its right mirror take one pivot, in their own frames.
An s1_cut blend built with or without the telescope serves (the pivots change no geometry).
blender -b <s1_cut.blend> --python fairing_pivots.py -- <out.json>  (copy out.json over baselines/fairing_hinges.json)"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fairing  # noqa: E402

POSES = list(range(0, 31, 1))
FWD = [round(i * 0.02, 2) for i in range(0, 31)]  # pivot forward of the flap hinge, m
UP = [round(-0.5 - i * 0.05, 2) for i in range(0, 21)]  # pivot below it, m
TAIL_AFT_M = 0.10
MARGIN_M = 0.01  # the sleeve's front this much further inside than carried() asks: the section here is taken before the telescope

table = {}  # (flap number, part) -> {side: {(fwd, up): row}}
for e in sorted((o for o in bpy.data.objects if o.get("fairing_of")), key=lambda o: o.name):
    fr = fairing.Frame(bpy.data.objects[e["fairing_of"]])
    rear = next(c for c in e.children if c.type == "MESH")
    rv = [rear.matrix_world @ v.co for v in rear.data.vertices]
    flap = bpy.data.objects[fr.flap.name + "_visible"]
    under = [(flap.matrix_world.to_3x3() @ p.normal).normalized() * p.area for p in flap.data.polygons
             if (flap.matrix_world.to_3x3() @ p.normal).normalized().dot(fr.up) < -0.7]
    into = -sum(under, Vector()).normalized()  # into the flap across its lower skin (the coarse flap mesh's faces span the fairings)
    tail = min(rv, key=fr.f)
    front = fairing.sleeve_front(fr, rear, bool(e.get("telescoped")))
    part = int(e.name.rsplit("fairing", 1)[1])
    rows = table.setdefault((fr.flap.name[-1], part), {}).setdefault(fr.flap.name[5], {})
    for pf in FWD:
        for pu in UP:
            P = fr.H + fr.fwd * pf + fr.up * pu
            m30 = fairing.turn(fr, P, 30)
            aft = fr.f(tail) - fr.f(m30 @ tail)
            if aft < TAIL_AFT_M:
                continue
            inside = min(fr.f(fairing.turn(fr, P, d) @ p) for d in POSES[::3] for p in front) - fairing.MOUTH_F
            if inside < fairing.SLEEVE_INSIDE_M + MARGIN_M:
                continue
            drift = [((fairing.turn(fr, fr.H, d).inverted() @ fairing.turn(fr, P, d)) @ Vector()).dot(into) for d in POSES]
            rows[(pf, pu)] = {"flap": fr.flap.name, "part": part, "pivot_world": [round(c, 4) for c in P],
                              "axis_world": [round(c, 5) for c in fr.ax], "flap_hinge_world": [round(c, 3) for c in fr.H],
                              "pivot_fwd_m": pf, "pivot_up_m": pu, "drift_span_m": round(max(drift) - min(drift), 4),
                              "sleeve_inside_m": round(inside, 3), "tail_aft_30_m": round(aft, 3),
                              "tail_down_30_m": round(fr.u(tail) - fr.u(m30 @ tail), 3)}

out = []
for (n, part), sides in sorted(table.items()):
    common = set.intersection(*(set(r) for r in sides.values()))
    if not common:
        raise SystemExit(f"fairing_pivots: no pivot moves fairing {part} of flap {n}'s tail {TAIL_AFT_M} m aft with its sleeve inside")
    key = min(sorted(common), key=lambda k: max(r[k]["drift_span_m"] for r in sides.values()))
    for side in sorted(sides):
        out.append(sides[side][key])
        print("PIVOT", sides[side][key], flush=True)
out.sort(key=lambda r: (r["flap"], r["part"]))
Path(sys.argv[sys.argv.index("--") + 1]).write_text(json.dumps(out, indent=1) + "\n")
