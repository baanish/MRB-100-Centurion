"""Solid against solid: every pair of separate cockpit pieces whose surfaces pass through each other. The pieces are the
interior's loose parts (flightdeck_int split into connected pieces) and the other cockpit meshes (band_bezel,
warning_lenses, the levers, hatch liners); glass, the screen and the tac screen are left out. Two pieces interpenetrate
where a triangle of one crosses a triangle of the other at an angle (not lying on it: faces within 5 deg of parallel
are contact, not penetration), deeper than TOL. Prints the count of pairs and the worst, with where and what they are.
Visible pairs (a crossing point in sight from the sightline gate's camera positions) are counted per group too. A ratchet:
each group's pairs and visible pairs against interpenetration_baseline.json beside this script; the step fails (exit 1)
when a count rises above it, and --write-baseline writes the counts as the new baseline.
blender -b <export.blend> --python-exit-code 1 --python flightdeck_interpenetration.py -- <out.json> [--write-baseline]"""
import json
import sys
from collections import defaultdict

import bmesh
import bpy
from mathutils import geometry
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv_ = sys.argv[sys.argv.index("--") + 1:]
out = argv_[0]
TOL = 0.001  # a crossing shorter than this (along the two faces' line) is contact
SKIP = {"glass_int", "band", "band_marker", "tacScreen"}
pieces = []  # (name, material names, verts, tris, bbox lo, bbox hi)
for o in bpy.context.scene.objects:
    if o.type != "MESH" or o.name in SKIP:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bm.faces.ensure_lookup_table()
    seen = set()
    mats = [s.material.name if s.material else "" for s in o.material_slots]
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        stack, comp = [f0], []
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            comp.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        vmap, verts, tris, names = {}, [], [], set()
        for f in comp:
            names.add(mats[f.material_index] if f.material_index < len(mats) else "")
            ids = []
            for v in f.verts:
                if v.index not in vmap:
                    vmap[v.index] = len(verts)
                    verts.append(v.co.copy())
                ids.append(vmap[v.index])
            for k in range(1, len(ids) - 1):
                tris.append((ids[0], ids[k], ids[k + 1]))
        lo = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
        hi = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
        pieces.append((o.name + "#%d" % len(pieces), sorted(names), verts, tris, lo, hi))
    bm.free()
print("PIECES", len(pieces))
order = sorted(range(len(pieces)), key=lambda i: pieces[i][4].x)
trees = {}


def tree(i):
    if i not in trees:
        trees[i] = BVHTree.FromPolygons(pieces[i][2], pieces[i][3])
    return trees[i]


def normal(i, t):
    a, b, c = (pieces[i][2][k] for k in pieces[i][3][t])
    return (b - a).cross(c - a).normalized()


pairs = []
for ai, i in enumerate(order):
    lo_i, hi_i = pieces[i][4], pieces[i][5]
    for j in order[ai + 1:]:
        lo_j, hi_j = pieces[j][4], pieces[j][5]
        if lo_j.x > hi_i.x - TOL:
            break
        if lo_j.y > hi_i.y - TOL or lo_i.y > hi_j.y - TOL or lo_j.z > hi_i.z - TOL or lo_i.z > hi_j.z - TOL:
            continue
        hits = [(a, b) for a, b in tree(i).overlap(tree(j)) if abs(normal(i, a).dot(normal(j, b))) < 0.996]
        if hits:
            ps = [sum((pieces[i][2][k] for k in pieces[i][3][a]), Vector()) / 3 for a, _ in hits]
            c = sum(ps, Vector()) / len(ps)
            spread = max((p - c).length for p in ps)
            if spread < TOL and len(hits) < 2:
                continue
            pts = []
            for a, b in hits[:12]:
                ta = [pieces[i][2][k] for k in pieces[i][3][a]]
                tb = [pieces[j][2][k] for k in pieces[j][3][b]]
                for t1, t2 in ((ta, tb), (tb, ta)):  # where an edge of one triangle goes through the other
                    n1 = (t1[1] - t1[0]).cross(t1[2] - t1[0])
                    for e0, e1 in ((t2[0], t2[1]), (t2[1], t2[2]), (t2[2], t2[0])):
                        q = geometry.intersect_line_plane(e0, e1, t1[0], n1)
                        if q is not None and (q - e0).dot(q - e1) <= 0 and geometry.intersect_point_tri(q, *t1) is not None:
                            pts.append(q)
            pairs.append({"pts": [list(q) for q in pts[:24]], "a": pieces[i][0], "a_mats": pieces[i][1], "b": pieces[j][0], "b_mats": pieces[j][1],
                          "a_size": round((pieces[i][5] - pieces[i][4]).length, 3), "b_size": round((pieces[j][5] - pieces[j][4]).length, 3),
                          "crossings": len(hits), "at": [round(v, 3) for v in c], "station": round(c.y + 22.475, 3)})
# a crossing is visible when nothing stands between one of its points and one of the sightline gate's camera positions:
# the eye, the sideways slide of a look past 33 deg (0.10 to 0.20 m either way), the sway sphere (7.5 cm, 26 ways)
allv, allp = [], []
for o in bpy.context.scene.objects:
    if o.type == "MESH" and o.name not in SKIP:
        me = o.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        b0 = len(allv)
        allv += [o.matrix_world @ v.co for v in me.vertices]
        allp += [[b0 + k for k in f.vertices] for f in me.polygons]
scene = BVHTree.FromPolygons(allv, allp)
EYE = Vector((0.55, -15.925, 5.0))
cams = [EYE] + [EYE + Vector((s * d, 0, 0)) for d in (0.10, 0.14, 0.17, 0.20) for s in (1, -1)]
cams += [EYE + Vector((dx, dy, dz)).normalized() * 0.075 for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if dx or dy or dz]
for p_ in pairs:
    p_["visible"] = False
    for q in p_["pts"]:
        q = Vector(q)
        for c_ in cams:
            d_ = q - c_
            if scene.ray_cast(c_, d_.normalized(), d_.length - 0.002)[0] is None:
                p_["visible"] = True
                p_["seen_at"] = [round(v, 3) for v in q]
                break
        if p_["visible"]:
            break
    del p_["pts"]
OLD = {"aircraft_structure", "Centurion_cockpit_shell", "Centurion_cockpit_console", "Matte_black"}
for p_ in pairs:
    a_, b_ = set(p_["a_mats"]), set(p_["b_mats"])
    p_["group"] = ("old shell / old shell" if a_ <= OLD and b_ <= OLD else "ours / old shell" if a_ <= OLD or b_ <= OLD
                   else "hardware under 3 cm in a plate" if min(p_["a_size"], p_["b_size"]) < 0.03 else "ours / ours")
pairs.sort(key=lambda p: -p["crossings"])
by_mats = defaultdict(int)
for p in pairs:
    by_mats[" / ".join(sorted(("+".join(p["a_mats"]), "+".join(p["b_mats"]))))] += 1
json.dump({"pairs": len(pairs), "groups": {g: [sum(1 for p in pairs if p["group"] == g), sum(1 for p in pairs if p["group"] == g and p["visible"])] for g in ("ours / ours", "hardware under 3 cm in a plate", "ours / old shell", "old shell / old shell")}, "all": pairs, "worst": pairs[:60], "by_materials": dict(sorted(by_mats.items(), key=lambda kv: -kv[1]))},
          open(out, "w"), indent=1)
print("INTERPENETRATION", len(pairs), "pairs of separate cockpit pieces pass through each other;", sum(p["visible"] for p in pairs), "of them visible")
for g in ("ours / ours", "hardware under 3 cm in a plate", "ours / old shell", "old shell / old shell"):
    print("  %-32s %4d pairs, %4d visible" % (g, sum(1 for p in pairs if p["group"] == g), sum(1 for p in pairs if p["group"] == g and p["visible"])))
for k_, (nm, ms, vs, ts, lo, hi) in enumerate(pieces):
    c_ = (lo + hi) / 2
    if 0.55 < c_.x < 0.95 and 5.6 < c_.y + 22.475 < 5.95 and 4.55 < c_.z < 4.9:
        print("CORNER PIECE", nm, ms, "x %.3f..%.3f st %.3f..%.3f z %.3f..%.3f" % (lo.x, hi.x, hi.y + 22.475, lo.y + 22.475, lo.z, hi.z), len(ts), "tris")
for p in pairs[:25]:
    print("  ", p["crossings"], p["a"], p["a_mats"], "x", p["b"], p["b_mats"], "at", p["at"], "station", p["station"])

from pathlib import Path  # noqa: E402

base_path = Path(__file__).resolve().parent / "interpenetration_baseline.json"
now = {g: {"pairs": sum(1 for p in pairs if p["group"] == g), "visible": sum(1 for p in pairs if p["group"] == g and p["visible"])}
       for g in ("ours / ours", "hardware under 3 cm in a plate", "ours / old shell", "old shell / old shell")}
if "--write-baseline" in argv_:
    base_path.write_text(json.dumps(now, indent=1) + chr(10), encoding="utf-8")
    print("INTERPENETRATION baseline written", now)
else:
    base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
    rose = [f"{g} {k} {now[g][k]} > {base[g][k]}" for g in now if g in base for k in ("pairs", "visible") if now[g][k] > base[g][k]]
    print("INTERPENETRATION ratchet:", "PASS" if not rose else "FAIL: " + "; ".join(rose))
    if rose:
        sys.exit(1)
