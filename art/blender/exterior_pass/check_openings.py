"""Openings in the closed aircraft: wherever a part's outer skin ends, rays from outside are cast at points just past
that edge, and where they see into the aircraft there is an opening. Reports per object the edge length that sees in,
what it sees and where; the moving surfaces first.

The edges: every edge of an outer skin face (Centurion_skin, not twin_src) with no other outer skin face of the same
object on it: the mesh's open edges and the lines where skin meets structure or another material.

The rays: five a point (along the skin's normal, and 45 degrees off it across and along the edge), aimed just past the
edge. A ray sees in when its first face lies a depth behind the aim point and is structure (Centurion_trim_cut),
honeycomb, or the back of outer skin (the inside of the hull, where a twin or nothing is drawn). A face nearer the aim
point is the hull's own surface there, whatever its material (flush trim, a well's lip). Back faces are skipped, as
the game culls them; a ray that meets the back of outer skin, or any face, short of the aim point started inside the
aircraft or is blocked, and gives no verdict. Twins lie on the outer skin with the opposite winding and are left out of
the rays' scene, the back of the skin standing in for them.

Two kinds of edge, two rules. An open edge (no other face on it) is a hole wherever a ray aimed OPEN_AIM past it sees
in OPEN_DEEP behind: a sliver a few millimetres wide counts (the split ailerons' end ribs). An edge where the skin turns
into the part's own structure (a door's or panel's edge, a well's wall) is built that way, and counts only where rays
aimed at both WIDE_AIMS see in WIDE_DEEP behind: a gap narrower than the far aim is a panel line.

The pose is the blend's own, every surface at rest and closed. Records; does not stop.
blender --background <blend> --python check_openings.py -- [<out.json>]"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

INTERIOR = {"Centurion_trim_cut": "structure", "pass_trim_cut": "structure", "honeycomb": "honeycomb"}
OPEN_AIM, OPEN_DEEP = 0.002, 0.003  # metres past an open edge; behind the aim point: inside the hull, not its surface
WIDE_AIMS, WIDE_DEEP = (0.003, 0.012), 0.01
STEP = 0.05  # a sample every 5 cm along an edge (an edge shorter than that: its middle)
REACH = 6.0  # the rays start this far out
NEAR = 0.002  # a face this much short of the aim point blocks the ray
TILT = math.radians(45)
CELL = 0.25
MOVING = ("flap_", "aileron_", "spoiler_", "ruddervator_", "baydoor_", "geardoor_", "nose_door", "nose_hatch")
OTHER, SKIN_OUT = 0, 1  # face kinds in the scene besides the INTERIOR values


def face_flags(me, name):
    at = me.attributes.get(name)
    vals = [0] * len(me.polygons)
    if at is not None and at.domain == "FACE":
        at.data.foreach_get("value", vals)
    return vals


objs = sorted(P.part_objects()[0].values(), key=lambda o: o.name)
verts, polys, kind = [], [], []
for o in objs:
    me, mw = o.data, o.matrix_world
    base = len(verts)
    verts.extend(mw @ v.co for v in me.vertices)
    twin = face_flags(me, "twin_src")
    names = [m.name if m else "" for m in me.materials]
    for p in me.polygons:
        mat = names[p.material_index] if p.material_index < len(names) else ""
        if mat == P.SKIN and twin[p.index]:
            continue
        polys.append([base + v for v in p.vertices])
        kind.append(INTERIOR.get(mat) or (SKIN_OUT if mat == P.SKIN else OTHER))
tree = BVHTree.FromPolygons(verts, polys)
print("OPENINGS faces", len(polys), "objects", len(objs), flush=True)


def seen(q, v, deep):
    """What a ray from outside along -v sees at q, deep or more behind it: "structure", "honeycomb", "skin inside",
    "outside" or None (no verdict)."""
    d = -v
    start = q + v * REACH
    o_ = start
    for _ in range(64):
        loc, nrm, i, _ = tree.ray_cast(o_, d, REACH * 2)
        if loc is None:
            return "outside"
        depth = (loc - start).dot(d) - REACH
        back = nrm.dot(d) > 0
        if depth < -NEAR:
            if back and kind[i] != SKIN_OUT:
                o_ = loc + d * 1e-4
                continue
            return None
        if depth < deep or (back and kind[i] != SKIN_OUT):
            if not back:
                return "outside"
            o_ = loc + d * 1e-4
            continue
        if back:
            return "skin inside"
        return kind[i] if isinstance(kind[i], str) else "outside"
    return None


rows = {}
for o in objs:
    me, mw = o.data, o.matrix_world
    names = [m.name if m else "" for m in me.materials]
    if P.SKIN not in names:
        continue
    twin = face_flags(me, "twin_src")
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(mw)
    bm.normal_update()
    skin = names.index(P.SKIN)
    outer = lambda f: f.material_index == skin and not twin[f.index] and f.normal.length > 0.5  # noqa: E731
    length, by_kind, cells, edges = 0.0, defaultdict(float), defaultdict(lambda: [0.0, defaultdict(float)]), 0
    for e in bm.edges:
        fs = [f for f in e.link_faces if outer(f)]
        if len(fs) != 1:
            continue
        a, b = e.verts[0].co, e.verts[1].co
        L = (b - a).length
        if L < 1e-3:
            continue
        edges += 1
        f = fs[0]
        n, dv = f.normal, (b - a) / L
        t = dv.cross(n)
        if t.dot((a + b) / 2 - f.calc_center_median()) < 0:
            t = -t
        dirs = [n] + [(n * math.cos(TILT) + s * math.sin(TILT)).normalized() for s in (t, -t, dv, -dv)]
        aims, deep = ((OPEN_AIM,), OPEN_DEEP) if len(e.link_faces) == 1 else (WIDE_AIMS, WIDE_DEEP)
        k = max(1, round(L / STEP))
        for j in range(k):
            p = a + (b - a) * ((j + 0.5) / k)
            per_aim = [[h for h in (seen(p + t * aim, v, deep) for v in dirs) if h not in (None, "outside")] for aim in aims]
            if not all(per_aim):
                continue
            hits = [h for hs in per_aim for h in hs]
            seg = L / k
            what = ("open edge to " if len(aims) == 1 else "wide gap to ") + max(sorted(set(hits)), key=hits.count)
            length += seg
            by_kind[what] += seg
            c = cells[(round(p.x / CELL) * CELL, round(p.y / CELL) * CELL, round(p.z / CELL) * CELL)]
            c[0] += seg
            c[1][what] += seg
    bm.free()
    if length > 0:
        rows[o.name] = {"object": o.name, "m": round(length, 3), "sees": {k_: round(v, 3) for k_, v in sorted(by_kind.items())},
                        "edges_checked": edges,
                        "where": [{"at": [round(x, 2) for x in k_], "m": round(v[0], 3), "sees": max(sorted(v[1]), key=v[1].get)}
                                  for k_, v in sorted(cells.items(), key=lambda kv: -kv[1][0])[:6]]}
order = sorted(rows.values(), key=lambda r: (not r["object"].startswith(MOVING), -r["m"]))
for r in order:
    print("OPENINGS", r["object"], "m", r["m"], r["sees"], flush=True)
    for w in r["where"]:
        print("OPENINGS    at", w["at"], "m", w["m"], w["sees"], flush=True)
print("OPENINGS total m", round(sum(r["m"] for r in order), 3), "objects", len(order), flush=True)
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args:
    Path(args[0]).write_text(json.dumps(order, indent=1))
