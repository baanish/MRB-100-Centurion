"""The damage's open skin per part (pin per-part open area at 60 and 0 HP). The game's shader
opens a texel where D * (alpha - 0.52) + 0.02 < 0, D = 1 - HP / 100, alpha from the damage map. Every outward skin
triangle of each part (twins, liners, UV copies out) is sampled at 16 points spread over it; the open share times its
area gives the open square metres. Writes the per-part table; with --against, fails when a part's open area moved by
more than TOL of its skin from the pinned table (a characterization pin: a change to the damage design re-pins it).
blender --background pass/s6_bake.blend --python check_damage_area.py -- <dmg_b.png> <out.json> [--against <pin.json>]"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import damage_field as DF  # noqa: E402

# The pin: the totals at 60, 30 and 0 HP within TOTAL_TOL of the pinned; each part within PART_TOL
# of its pinned open area or PART_FLOOR_M2, whichever is larger. A UV repack moves a small part's texels (a few doors by 3
# to 20%) with the damage field unchanged; the totals still catch a change to the field
TOTAL_TOL, PART_TOL, PART_FLOOR_M2 = 0.01, 0.03, 0.05
args = sys.argv[sys.argv.index("--") + 1:]
im = bpy.data.images.load(str(Path(args[0]).resolve()))  # (Blender reads a bare relative path against the drive root)
w, h = im.size
alpha = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, im.channels)[..., 3]
out = Path(args[1]).resolve()
against = Path(args[args.index("--against") + 1]).resolve() if "--against" in args else None
BARY = [(a, b) for a in np.linspace(0.05, 0.95, 6) for b in np.linspace(0.05, 0.95, 6) if a + b < 0.98][:16]


def opened(al, hp):
    d = 1.0 - hp / 100.0
    return d * (al - 0.52) + 0.02 < 0


parts = {}
for o in bpy.data.objects:
    if o.type != "MESH" or "_lod1" in o.name or "_colmesh" in o.name or any(c.name in ("Colliders", "LOD1") for c in o.users_collection):
        continue
    me = o.data
    sk = {i for i, m in enumerate(me.materials) if m and m.name == "Centurion_skin"}
    if not sk or not me.uv_layers:
        continue
    skip = [0] * len(me.polygons)
    for name in ("twin_src", "liner", "uv_copy"):
        a = me.attributes.get(name)
        if a is not None and a.domain == "FACE":
            v = [0] * len(me.polygons)
            a.data.foreach_get("value", v)
            skip = [x or y for x, y in zip(skip, v)]
    me.calc_loop_triangles()
    uv = me.uv_layers[0].data
    area = o60 = o30 = o0 = 0.0
    for lt in me.loop_triangles:
        if me.polygons[lt.polygon_index].material_index not in sk or skip[lt.polygon_index]:
            continue
        A, B, C = (np.array(uv[li].uv) for li in lt.loops)
        pts = np.array([A + (B - A) * s + (C - A) * t for s, t in BARY])
        xs = np.clip((pts[:, 0] * w).astype(int), 0, w - 1)
        ys = np.clip((pts[:, 1] * h).astype(int), 0, h - 1)
        al = alpha[ys, xs]
        area += lt.area
        o60 += lt.area * opened(al, 60).mean()
        o30 += lt.area * opened(al, 30).mean()  # reported, not pinned (the owner's 60, 30, 0 comparison)
        o0 += lt.area * opened(al, 0).mean()
    if area > 0:
        parts[o.name] = {"skin_m2": round(area, 2), "open_m2_60hp": round(o60, 3), "open_m2_30hp": round(o30, 3), "open_m2_0hp": round(o0, 3)}
# ---- sight lines through the open skin: from every sample open at 0 HP, rays into the part, straight
# in and tilted 40 degrees eight ways; the first thing met must face the ray (an inward copy, a liner, structure) or be
# open sky. A skin face met from behind is culled in the game: the hole shows through the aircraft ----
from mathutils import Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

rend = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and "_lod1" not in o.name and "_colmesh" not in o.name
        and not o.name.endswith(("_blockout_mesh", "_shape")) and not any(c.name in ("Colliders", "LOD1") for c in o.users_collection)]
vs, ps, info = [], [], []
for o in rend:
    me, mw = o.data, o.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    sk = {i for i, m in enumerate(me.materials) if m and m.name == "Centurion_skin"}
    inner = [0] * len(me.polygons)  # s2's `opens`: the face has an inward copy (a coincident twin may be what a ray returns)
    if me.attributes.get("opens") is not None:
        me.attributes["opens"].data.foreach_get("value", inner)
    if me.attributes.get("uv_copy") is not None:  # a control surface's fittings, moved onto the skin's paint by s4 after s2
        cp_ = [0] * len(me.polygons)  # tagged: closed hardware, not skin a hole looks onto (s2's own rays saw every other copy)
        me.attributes["uv_copy"].data.foreach_get("value", cp_)
        inner = [a or b for a, b in zip(inner, cp_)]
    b = len(vs)
    vs += [mw @ v.co for v in me.vertices]
    for p in me.polygons:
        ps.append([b + i for i in p.vertices])
        info.append((o.name, p.index, p.material_index in sk and not inner[p.index], (nm @ p.normal).normalized()))
tree = BVHTree.FromPolygons(vs, ps)
straight_bad, tilt_bad, rays, worst, samples, slivers = 0, 0, 0, {}, [], 0
for o in rend:
    me, mw = o.data, o.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    sk = {i for i, m in enumerate(me.materials) if m and m.name == "Centurion_skin"}
    if not sk or not me.uv_layers:
        continue
    skip = [0] * len(me.polygons)
    for name in ("twin_src", "liner", "uv_copy"):
        a = me.attributes.get(name)
        if a is not None and a.domain == "FACE":
            v = [0] * len(me.polygons)
            a.data.foreach_get("value", v)
            skip = [x or y for x, y in zip(skip, v)]
    uv = me.uv_layers[0].data
    me.calc_loop_triangles()
    for lt in me.loop_triangles:
        if me.polygons[lt.polygon_index].material_index not in sk or skip[lt.polygon_index]:
            continue
        A, B, C = (np.array(uv[li].uv) for li in lt.loops)
        Pw = [mw @ me.vertices[vv].co for vv in lt.vertices]
        uv_px = abs(np.cross(B - A, C - A)) / 2 * w * h
        if lt.area > 1e-8 and (uv_px / lt.area) ** 0.5 < 10.0:  # no texels of its own: the bake's gutter fill from its UV neighbours
            slivers += 1  # decides its alpha (the cockpit's frame strips, about 2 px/m as shipped)
            continue
        n = (nm @ me.polygons[lt.polygon_index].normal).normalized()
        t1 = n.orthogonal().normalized()
        t2 = n.cross(t1)
        for s, t in DF.SIGHT_BARY:
            q = A + (B - A) * s + (C - A) * t
            if not opened(alpha[min(h - 1, int(q[1] * h)), min(w - 1, int(q[0] * w))], 0):
                continue
            p = Pw[0] + (Pw[1] - Pw[0]) * s + (Pw[2] - Pw[0]) * t
            for k in range(9):
                if k == 0:
                    d = -n
                else:
                    a = math.radians(45 * (k - 1))
                    d = (-n * math.cos(math.radians(40)) + (t1 * math.cos(a) + t2 * math.sin(a)) * math.sin(math.radians(40))).normalized()
                rays += 1
                hh = tree.ray_cast(p + d * 0.02, d, 40.0)  # past the face's own twin (on it) and liner (12 mm in), which open with it
                if hh[0] is None:
                    continue
                on, fi, bare_skin, fn = info[hh[2]]
                if bare_skin and fn.dot(d) > 0:  # a skin face with no inner copy, met from behind
                    if k == 0:
                        straight_bad += 1
                        worst[on] = worst.get(on, 0) + 1
                        if len(samples) < 12:
                            samples.append({"from": o.name, "face": lt.polygon_index, "at": [round(x, 3) for x in p], "met": on, "met_face": fi,
                                            "distance": round((hh[0] - p).length, 3)})
                    else:
                        tilt_bad += 1
sight = {"rays": rays, "straight_onto_missing_inner_face": straight_bad, "tilted_onto_missing_inner_face": tilt_bad, "by_part_met": worst, "samples": samples,
         "triangles_under_10px_per_m_not_judged": slivers}
print("DAMAGE SIGHT", sight, flush=True)
fails = []
if straight_bad:
    fails.append(f"{straight_bad} opened samples look straight onto a skin face's back (no inner face): {dict(sorted(worst.items(), key=lambda kv: -kv[1])[:6])}")
tot = {k: round(sum(r[k] for r in parts.values()), 2) for k in ("skin_m2", "open_m2_60hp", "open_m2_30hp", "open_m2_0hp")}
floored, unpinned = 0, []
if against is not None:
    pin = json.loads(against.read_text())["parts"]
    for k in ("open_m2_60hp", "open_m2_30hp", "open_m2_0hp"):
        want = sum(p.get(k, 0) for p in pin.values())
        if abs(tot[k] - want) > TOTAL_TOL * want:
            fails.append(f"total {k}: {tot[k]} m2 against the pinned {round(want, 2)}")
    for n, r in parts.items():
        p = pin.get(n)
        if not p:
            continue
        floored += any(PART_TOL * p[k] < PART_FLOOR_M2 for k in ("open_m2_60hp", "open_m2_0hp"))
        if any(abs(r[k] - p[k]) > max(PART_TOL * p[k], PART_FLOOR_M2) for k in ("open_m2_60hp", "open_m2_0hp")):
            fails.append(f"{n}: open {r['open_m2_60hp']}/{r['open_m2_0hp']} m2 against the pinned {p['open_m2_60hp']}/{p['open_m2_0hp']}")
    for n in sorted(pin.keys() - parts.keys()):  # renamed, or its skin no longer counted: the totals alone would let it go
        fails.append(f"{n}: pinned with open {pin[n]['open_m2_60hp']}/{pin[n]['open_m2_0hp']} m2, missing from this run (re-pin if removed on purpose)")
    unpinned = sorted(parts.keys() - pin.keys())  # a part the pass creates or splits after the pin: only the totals hold it
    print("DAMAGE AREA parts held to the 0.05 m2 floor:", floored, "of", len(parts), "| not in the pin:", unpinned, flush=True)
out.write_text(json.dumps({"rule": "open where D*(alpha-0.52)+0.02<0", "parts": parts, "sight": sight, "fails": fails,
                           "parts_on_the_floor": floored, "not_pinned": unpinned}, indent=1))
print("DAMAGE AREA", tot, len(fails), "fails", fails[:6], flush=True)
if fails:
    raise SystemExit("check_damage_area: " + "; ".join(fails[:10]))
