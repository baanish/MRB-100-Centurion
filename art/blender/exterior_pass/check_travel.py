"""The control surfaces through their full travel: they must not visibly cut into the wing (the owner). Every flap, aileron half and ruddervator turns about its hinge over its game travel (sweep.py), at every
STEP_DEG; at each pose:
(i) poke-through: moving surface seen from outside on a triangle that crosses a fixed face, at a point on that face's
    outer side within REACH_M of it (the piece that has come through): from the six axis views and two chase views, an
    orthographic ray grid GRID_M apart over the surface; each such first hit counts its cell's area.
    Limit VISIBLE_M2 a surface a pose. Crossings with nothing seen (inside the wing or the cove) are reported only;
(ii) flicker: a moving face lying within FLICKER_M of a fixed face it overlaps, parallel to it. Limit 0, rest included;
(iii) the cove's seal is s1's gate.
blender --background <blend> --python check_travel.py -- <out.json> [--record]  (--record: a FAIL is written, not raised)"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
import sweep as SW  # noqa: E402

STEP_DEG, GRID_M, VISIBLE_M2, FLICKER_M, REACH_M = 5, 0.02, 0.001, 0.001, 0.15
from mathutils.geometry import closest_point_on_tri  # noqa: E402
VIEWS = [Vector(v).normalized() for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (0.5, 1.0, 0.6), (-0.5, 1.0, 0.6))]
out = Path(sys.argv[sys.argv.index("--") + 1]).resolve()


def tris(objs, m=None, owners=None):
    vs, ts, normals = [], [], []
    for o in objs:
        if owners is not None:
            o.data.calc_loop_triangles()
            mats = [m.name.replace("Centurion_", "") if m else "" for m in o.data.materials] or [""]
            owners += [f"{o.name}/{mats[min(lt.material_index, len(mats) - 1)]}" for lt in o.data.loop_triangles]
        me = o.data
        me.calc_loop_triangles()
        mw = (m @ o.matrix_world) if m is not None else o.matrix_world
        b = len(vs)
        vs += [mw @ v.co for v in me.vertices]
        for lt in me.loop_triangles:
            a, b_, c = (vs[b + i] for i in lt.vertices)
            ts.append([b + i for i in lt.vertices])
            n = (b_ - a).cross(c - a)
            normals.append(n.normalized() if n.length > 0 else n)
    return vs, ts, normals


report, fails = {}, []
fixed_all = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and not SW.helper(o)]
for hinge, moving, degs, label in SW.surfaces():
    mset = set(moving)
    # a flap and its fairings on their own hinges (fairing.py) move together: neither is fixed geometry in the
    # other's sweep, since this check turns one surface against the rest at rest and would read each against the other
    # at the wrong angle; fairing.gate() turns them together and holds them apart
    flap_of = hinge.get("fairing_of") or hinge.name
    pair = {o for o in fixed_all if o.parent is not None and (o.parent.get("fairing_of") == flap_of or o.parent.name == flap_of)}
    fixed = [o for o in fixed_all if o not in mset and o not in pair and not o.name.startswith((hinge.name + "_visible",))]
    fowner = []
    fv, ft, fn = tris(fixed, owners=fowner)
    through = {}
    ftree = BVHTree.FromPolygons(fv, ft)
    poses = sorted(set(range(min(degs), max(degs) + 1, STEP_DEG)) | {min(degs), max(degs), 0})
    ax = hinge.matrix_world.col[0].xyz.normalized()
    piv = hinge.matrix_world.translation.copy()
    worst_vis, flick, hidden, crossing_poses, worst_where = (0.0, None), 0, 0, 0, None
    fwd = ax.cross(Vector((0, 0, 1))).normalized()
    fwd = fwd if fwd.y < 0 else -fwd
    upv = ax.cross(fwd)
    if upv.z < 0:
        upv = -upv
    local = []
    s_all = [(o.matrix_world @ v.co - piv).dot(ax) for o in moving for v in o.data.vertices]
    s_lo, s_hi = min(s_all), max(s_all)
    for d in poses:
        m = SW.turn(hinge, d)
        mv, mt, mn = tris(moving, m)
        mtree = BVHTree.FromPolygons(mv, mt)
        crossing = {}
        for a, b in mtree.overlap(ftree):
            pa, pb = [mv[i] for i in mt[a]], [fv[i] for i in ft[b]]
            nb = fn[b]
            if nb.length == 0:
                continue
            da = [(p - pb[0]).dot(nb) for p in pa]
            if max(abs(x) for x in da) < FLICKER_M and abs(mn[a].dot(nb)) > 0.99:
                flick += 1  # (ii) lying on the fixed face: they fight for depth
            elif min(da) < -FLICKER_M and max(da) > FLICKER_M:
                crossing.setdefault(a, []).append(b)  # it passes through the fixed face
        if not crossing:
            continue
        crossing_poses += 1
        allv, allt = list(fv), [list(t) for t in ft]
        base = len(allv)
        allv += mv
        allt += [[base + i for i in t] for t in mt]
        stree = BVHTree.FromPolygons(allv, allt)
        nf = len(ft)
        vis_area, where = 0.0, None
        for view in VIEWS:
            t1 = view.orthogonal().normalized()
            t2 = view.cross(t1)
            u = [p.dot(t1) for p in mv]
            w = [p.dot(t2) for p in mv]
            c0 = view * (100.0 + max(p.dot(view) for p in mv))
            seen, at = 0, None
            for i in range(int((max(u) - min(u)) / GRID_M) + 2):
                for j in range(int((max(w) - min(w)) / GRID_M) + 2):
                    o_ = c0 + t1 * (min(u) + i * GRID_M) + t2 * (min(w) + j * GRID_M)
                    h = stree.ray_cast(o_, -view, 400.0)
                    if h[0] is None or h[2] < nf or (h[2] - nf) not in crossing:
                        continue
                    for b in crossing[h[2] - nf]:  # out on the fixed face's outer side, beside it: it came through
                        pb = [fv[i] for i in ft[b]]
                        if (h[0] - pb[0]).dot(fn[b]) > 0 and (closest_point_on_tri(h[0], *pb) - h[0]).length < REACH_M:
                            seen += 1
                            through[fowner[b]] = through.get(fowner[b], 0) + 1
                            at = at or tuple(round(x, 2) for x in h[0])
                            if len(local) < 400:  # the rest pose of the seen point, in the hinge's frame (forward, up)
                                p0 = SW.turn(hinge, -d) @ h[0]
                                local.append(((p0 - piv).dot(fwd), (p0 - piv).dot(upv), ((p0 - piv).dot(ax) - s_lo) / max(s_hi - s_lo, 1e-6)))
                            break
            if seen * GRID_M * GRID_M > vis_area:
                vis_area, where = seen * GRID_M * GRID_M, at
        if vis_area > worst_vis[0]:
            worst_vis, worst_where = (vis_area, d), where
        if vis_area <= VISIBLE_M2:
            hidden += 1
    rec = {"poses": len(poses), "worst_visible_m2": round(worst_vis[0], 4), "at_deg": worst_vis[1], "first_seen_at": worst_where,
           "flicker_pairs": flick, "poses_crossing": crossing_poses, "poses_crossing_hidden_only": hidden,
           "came_through": dict(sorted(through.items(), key=lambda kv: -kv[1])[:4])}
    if local:  # where on the surface it comes through: forward of the hinge (+) or aft, above (+) or below, metres
        fs_, us_ = sorted(p[0] for p in local), sorted(p[1] for p in local)
        rec["rest_fwd_m_p10_p50_p90"] = [round(fs_[int(len(fs_) * q)], 2) for q in (0.1, 0.5, 0.9)]
        rec["rest_up_m_p10_p50_p90"] = [round(us_[int(len(us_) * q)], 2) for q in (0.1, 0.5, 0.9)]
        rec["span_share_in_end_10pct"] = round(sum(1 for p in local if p[2] < 0.1 or p[2] > 0.9) / len(local), 2)
    report[label] = rec
    print("TRAVEL", label, rec, flush=True)
    if worst_vis[0] > VISIBLE_M2 or flick:
        fails.append(f"{label}: visible {worst_vis[0]:.4f} m2 at {worst_vis[1]} deg, flicker {flick}")
out.write_text(json.dumps({"limits": {"visible_m2": VISIBLE_M2, "flicker_m": FLICKER_M, "step_deg": STEP_DEG}, "surfaces": report, "fails": fails}, indent=1))
print("TRAVEL", len(fails), "fails", fails, flush=True)
if fails and "--record" in sys.argv:  # Run-Pass records it, as stage 2's hole gate, and goes on (lead's decision pending)
    print("TRAVEL FAIL recorded in", out, flush=True)
elif fails:
    raise SystemExit("check_travel: " + "; ".join(fails))
