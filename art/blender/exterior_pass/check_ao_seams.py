"""The baked AO across the seams between damage parts of one skin: wherever two parts' outer skin faces meet on an edge
(the seams stage 1 cut on one plane, so their vertices coincide), the AO 1 cm into each face from the edge's middle,
and per pair of parts the mean and worst step, where it is, listed when the mean is over STEP. A part's AO should run
on across its seam as the skin does (the forward flank's fuselage_F against bay_F read 1.00 against 0.97).
blender --background <s6_bake.blend> --python check_ao_seams.py -- <ao.png> [<out.json>]"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

STEP, INSET, SMOOTH = 0.01, 0.01, 0.94  # SMOOTH: the two faces' normals within 20 degrees, one skin running on
a = sys.argv[sys.argv.index("--") + 1:]
im = bpy.data.images.load(str(Path(a[0]).resolve()))
w, h = im.size
px = np.empty(w * h * 4, np.float32)
im.pixels.foreach_get(px)
ao = px.reshape(h, w, 4)[..., 0]


def sample(uv):
    x, y = min(w - 1, max(0, int(uv[0] * w))), min(h - 1, max(0, int(uv[1] * h)))
    return float(ao[y, x])


edges = defaultdict(list)  # rounded edge key -> [(part, AO 1 cm into its face)]
for o in P.part_objects()[0].values():
    me, mw = o.data, o.matrix_world
    names = [m.name if m else "" for m in me.materials]
    if P.SKIN not in names:
        continue
    sk = names.index(P.SKIN)
    flags = {}
    for n in ("twin_src", "uv_copy"):
        at = me.attributes.get(n)
        v = [0] * len(me.polygons)
        if at is not None and at.domain == "FACE":
            at.data.foreach_get("value", v)
        flags[n] = v
    uv = me.uv_layers.active.data
    part = o.name.replace("_visible", "").replace("_lower", "")
    for p in me.polygons:
        if p.material_index != sk or flags["twin_src"][p.index]:
            continue
        vs = [mw @ me.vertices[i].co for i in p.vertices]
        nrm = (mw.to_3x3() @ p.normal).normalized()
        uvs = [uv[li].uv for li in p.loop_indices]
        c3, cu = sum(vs, vs[0] * 0) / len(vs), sum(uvs, uvs[0] * 0) / len(uvs)
        for k in range(len(vs)):
            a3, b3 = vs[k], vs[(k + 1) % len(vs)]
            m3, mu = (a3 + b3) / 2, (uvs[k] + uvs[(k + 1) % len(vs)]) / 2
            d = (c3 - m3).length
            if d < 1e-6:
                continue
            q = mu + (cu - mu) * min(1.0, INSET / d)
            key = tuple(sorted((tuple(round(x, 4) for x in a3), tuple(round(x, 4) for x in b3))))
            edges[key].append((part, sample(q), tuple(round(x, 2) for x in m3), nrm))
pairs = defaultdict(list)
for key, side in edges.items():
    parts = {s[0] for s in side}
    if len(side) != 2 or len(parts) != 2 or side[0][3].dot(side[1][3]) < SMOOTH:
        continue  # a junction (a strut on a wing, a wing on the body) darkens its corner on purpose: only one skin's seams
    (pa, va, at, _), (pb, vb, _, _) = sorted(side, key=lambda s: s[0])
    pairs[(pa, pb)].append((vb - va, at))
rows = []
for (pa, pb), steps in sorted(pairs.items()):
    d = np.array([s for s, _ in steps])
    worst = max(steps, key=lambda s: abs(s[0]))
    rows.append({"parts": [pa, pb], "edges": len(steps), "mean_step": round(float(d.mean()), 4),
                 "mean_abs": round(float(np.abs(d).mean()), 4), "worst": round(worst[0], 3), "at": worst[1]})
over = [r for r in rows if abs(r["mean_step"]) > STEP]
for r in sorted(over, key=lambda r: -abs(r["mean_step"])):
    print("AOSEAM", r["parts"][0], "/", r["parts"][1], "edges", r["edges"], "mean step", r["mean_step"], "worst", r["worst"], "at", r["at"], flush=True)
print("AOSEAM pairs", len(rows), "over", STEP, ":", len(over), flush=True)
if len(a) > 1:
    Path(a[1]).write_text(json.dumps(rows, indent=1))
