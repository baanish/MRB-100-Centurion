"""Final collision shapes and masses for the damage part tree, between art/blender/damage_parts.py's cut and build stages.

python -I art/blender/damage_finalize.py <work dir>

Reads <work>/cut.json and writes <work>/parts.json.

Shapes: each part's point cloud (control surfaces' inset by damage_tree.SURFACE_INSET, half their thickness where
thinner), cut to at most 128 vertices by greedy farthest-point selection, rounded to 0.01 mm, and only then triangulated
as the convex hull of those rounded vertices with every face turned outward, so no face is reversed or degenerate. Unity
keeps 255 triangles in a convex mesh collider; 128 vertices make at most 252.

Masses: each part starts at its share of the 0.1.3 part masses by skin area (damage_parts.py cut), then the centre of
gravity is put back where 0.1.3's was by moving mass, Delta m_i = m_i (a + b Y_i + c Z_i), over every part but the
telescoping stages and the control surfaces (the stages keep 0.1.3's masses, so the span shift stays), total 124,700 kg.
The centre of gravity is the game's: each part flies as its own rigid body (Aircraft.SetComplexPhysics,
Aircraft.cs:1343-1359), whose centre of mass Unity derives from its colliders, uniform density, unless UnitPart.ModifyMass
sets it to the part's centerOfMass marker (UnitPart.cs:270-278), which fuel tanks and loaded hardpoints do. So each new
part's mass acts at its shape's volume centroid, where the author also puts its marker; in 0.1.3 at its collider pieces'
volume centroid, or for the four tank parts at their markers, the centres of their pieces' bounds
(CenturionAuthor.ConfigurePart). Aircraft.CalcCenterOfMass, which weighs transform positions, has no caller in the game.
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linprog, minimize
from scipy.spatial import ConvexHull, HalfspaceIntersection

sys.path.insert(0, str(Path(__file__).resolve().parent))
import damage_tree as T  # noqa: E402

MAX_VERTS = 128
MAX_TRIS = 255
DEGENERATE = 2e-5  # twice a triangle's area, m2, below which it is a sliver (Unity's Vector3.Normalize zeroes under 1e-5)
FIXED_MASS = ("stage", "surface")
TANKS = {"fuselage_F": 3000, "Centurion": 15000, "fuselage_R": 3000, "tailcone": 3000}
# fire links each tank section must reach: forward to centre to rear to tail, and back where the sphere allows
FIRE_LINKS = {"fuselage_F": ["Centurion", "bay_F"], "Centurion": ["fuselage_F", "fuselage_R", "bay_F", "bay_A"],
              "fuselage_R": ["tailcone", "bay_A"], "tailcone": ["fuselage_R", "bay_A"]}
OLD_TANKS = ("fuselage_M", "fuselage_F", "fuselage_R", "tailcone")
# 0.1.3's cockpit part, the donor's box part inside the nose: 2,000 kg at its BoxCollider's centre, Blender metres
# (Centurion.prefab: nose/cockpit at prefab (0, -0.2, 14.45), box centre (0, 0.475, 14.9)).
OLD_COCKPIT = (2000.0, (0.0, -16.375, 4.425))


def planes(v):
    return np.unique(ConvexHull(v).equations.round(12), axis=0)


def insphere(eq):
    a = np.c_[eq[:, :3], np.linalg.norm(eq[:, :3], axis=1)]
    return linprog([0, 0, 0, -1], A_ub=a, b_ub=-eq[:, 3], bounds=[(None, None)] * 4, method="highs").x


def inset(v, d):
    eq = planes(v)
    c = insphere(eq)
    eq[:, 3] += min(d, 0.5 * c[3])
    return HalfspaceIntersection(eq, c[:3]).intersections


def reduce(v, n=MAX_VERTS):
    """Greedy: keep the vertex farthest outside the hull of those kept, until n or none is outside."""
    v = np.unique(np.round(v, 6), axis=0)
    v = v[ConvexHull(v).vertices]
    if len(v) <= n:
        return v, 0.0
    a = int(np.argmax(np.linalg.norm(v - v.mean(0), axis=1)))
    b = int(np.argmax(np.linalg.norm(v - v[a], axis=1)))
    d = v[b] - v[a]
    c = int(np.argmax(np.linalg.norm(np.cross(v - v[a], d), axis=1)))
    e = int(np.argmax(np.abs((v - v[a]) @ np.cross(d, v[c] - v[a]))))
    keep = [a, b, c, e]
    while True:
        eq = planes(v[keep])
        out = (v @ eq[:, :3].T + eq[:, 3]).max(1)
        out[keep] = -1
        if len(keep) >= n or out.max() <= 1e-6:
            return v[keep], float(max(out.max(), 0.0))
        keep.append(int(out.argmax()))


def hull_mesh(v):
    """Triangles of the convex hull of the vertices as they will be stored (rounded), each facing out. A vertex lying on
    a hull edge between two others (a sliver triangle) is dropped; it sits within rounding of the hull."""
    v = np.unique(np.round(v, 5), axis=0)
    while True:
        h = ConvexHull(v)
        sliver = None
        for tri in h.simplices:
            a, b, c = v[tri]
            if np.linalg.norm(np.cross(b - a, c - a)) < DEGENERATE:
                # the vertex opposite the longest edge is the one between the other two
                edges = [np.linalg.norm(v[tri[(i + 1) % 3]] - v[tri[(i + 2) % 3]]) for i in range(3)]
                sliver = tri[int(np.argmax(edges))]
                break
        if sliver is None:
            break
        v = np.delete(v, sliver, axis=0)
    used = np.unique(h.simplices)
    vv = v[used]
    remap = {int(o): i for i, o in enumerate(used)}
    centre = vv.mean(0)
    faces = []
    for tri in h.simplices:
        f = [remap[int(x)] for x in tri]
        a, b, c = vv[f]
        if np.dot(np.cross(b - a, c - a), a - centre) < 0:
            f = [f[0], f[2], f[1]]
        faces.append(f)
    return dict(v=vv.tolist(), f=faces)


def check_hull(name, hull):
    """Convex, every face outward and not degenerate, at most 255 triangles: what Unity's convex collider keeps."""
    v, f = np.asarray(hull["v"]), np.asarray(hull["f"])
    problems = []
    if len(f) > MAX_TRIS or len(v) > MAX_TRIS:
        problems.append(f"{len(v)} vertices, {len(f)} triangles")
    centre = v.mean(0)
    for tri in f:
        a, b, c = v[tri]
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < DEGENERATE:
            problems.append(f"degenerate face {tri.tolist()}")
            continue
        n /= np.linalg.norm(n)
        if np.dot(n, a - centre) <= 0:
            problems.append(f"inward face {tri.tolist()}")
        elif ((v - a) @ n).max() > 1e-5:
            problems.append(f"face {tri.tolist()} has vertices {((v - a) @ n).max() * 1000:.3f} mm outside it")
    if problems:
        raise SystemExit(f"{name}: shape fails: {'; '.join(problems[:4])}")


def volume_centroid(v):
    """Volume and centroid of the convex hull of v."""
    v = np.asarray(v)
    h = ConvexHull(v)
    base = v.mean(0)
    tet = v[h.simplices]
    w = np.abs(np.linalg.det(tet - base)) / 6
    return float(w.sum()), np.average((tet.sum(1) + base) / 4, axis=0, weights=w)


def body_centroid(hulls):
    """A rigid body's centre of mass from its convex pieces at uniform density, as Unity derives it."""
    vc = [volume_centroid(h) for h in hulls]
    return sum(w * c for w, c in vc) / sum(w for w, _ in vc)


def inside_by(p, v):
    """How far p lies inside the convex hull of v (negative: outside), m."""
    eq = planes(v)
    return float(-(eq[:, :3] @ p + eq[:, 3]).max())


def dist_to_hull(p, v):
    eq = planes(v)
    if (eq[:, :3] @ p + eq[:, 3]).max() <= 0:
        return 0.0
    cons = {"type": "ineq", "fun": lambda x: -(eq[:, :3] @ x + eq[:, 3]), "jac": lambda x: -eq[:, :3]}
    r = minimize(lambda x: 0.5 * np.sum((x - p) ** 2), v.mean(0), jac=lambda x: x - p, constraints=cons, method="SLSQP",
                 options={"ftol": 1e-12, "maxiter": 500})
    return float(np.sqrt(2 * r.fun))


def fire_radius(v):
    """FuelTank's fire sphere: 1.5 x the mean half extent of the tank part's first collider's bounds (FuelTank.cs:331-336)."""
    return 1.5 * float(np.sum((v.max(0) - v.min(0)) / 2)) / 3


def clip_hull(v, n, d, gap):
    """The convex hull of v cut to the side n.x + d >= gap (n a unit outward normal of the other shape's face)."""
    v = np.asarray(v)
    h = ConvexHull(v)
    s = v @ n + d - gap
    keep = list(v[s >= 0])
    for tri in h.simplices:
        for i, j in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            if (s[i] < 0) != (s[j] < 0):
                keep.append(v[i] + (v[j] - v[i]) * (s[i] / (s[i] - s[j])))
    return np.asarray(keep)


def separation(v, keep):
    """The face of keep's hull that v lies farthest outside of (or least inside): (gap along it, normal, offset)."""
    eq = planes(keep)
    gaps = (np.asarray(v) @ eq[:, :3].T + eq[:, 3]).min(0)
    i = int(np.argmax(gaps))
    return float(gaps[i]), eq[i, :3], float(eq[i, 3])


def trim_shapes(parts, final):
    """Keeps each pair in damage_tree.CLEAR_PAIRS, neighbours that touch with no joint between them, CLEAR_GAP apart: the
    first part's shape is cut on the face of the second's that separates them best, which moves it least. Returns
    {pair: depth cut, mm, and the share of the shape's volume kept}."""
    trims = {}
    for a, b in T.CLEAR_PAIRS:
        for ka, ha in enumerate(final[a]["hulls"]):
            for hb in final[b]["hulls"]:
                found, n, d = separation(ha["v"], np.asarray(hb["v"]))
                if found >= T.CLEAR_GAP - 1e-6:
                    continue
                before = volume_centroid(ha["v"])[0]
                red, _ = reduce(clip_hull(ha["v"], n, d, T.CLEAR_GAP))
                ha = hull_mesh(red)
                check_hull(f"{a} shape {ka} cut clear of {b}", ha)
                kept = volume_centroid(ha["v"])[0] / before
                if kept < 0.7:
                    raise SystemExit(f"{a}: cutting it {T.CLEAR_GAP * 1000:.0f} mm clear of {b} keeps only {kept:.0%} of its shape")
                final[a]["hulls"][ka] = ha
                trims[f"{a}/{b}"] = f"{(T.CLEAR_GAP - found) * 1000:.1f} mm, {kept:.0%} kept"
    return trims


def old_cg(old):
    """0.1.3's dry centre of gravity, retracted, from its rigid bodies: each part's mass at its pieces' volume centroid,
    a tank part's at its marker."""
    total, moment = OLD_COCKPIT[0], OLD_COCKPIT[0] * np.array(OLD_COCKPIT[1])
    for name, b in old.items():
        hulls = [np.asarray(h) for h in b["hulls"]]
        if name in OLD_TANKS:
            allv = np.vstack(hulls)
            point = (allv.min(0) + allv.max(0)) / 2
        else:
            point = body_centroid(hulls)
        total += b["kg"]
        moment += b["kg"] * point
    return total, moment / total


def main():
    work = Path(sys.argv[1]).resolve()
    cut = json.loads((work / "cut.json").read_text())
    parts, old = cut["parts"], cut["old"]
    total_old, target = old_cg(old)
    if abs(total_old - T.TOTAL_KG) > 1:
        raise SystemExit(f"0.1.3's parts weigh {total_old} kg, not {T.TOTAL_KG}")

    final, notes = {}, []
    for name, p in parts.items():
        hulls = []
        for k, pts in enumerate(p["hull_points"]):
            v = np.asarray(pts)
            if p["kind"] == "surface":
                v = inset(v, T.SURFACE_INSET)
            red, retreat = reduce(v)
            hull = hull_mesh(red)
            check_hull(f"{name} shape {k}", hull)
            hulls.append(hull)
            notes.append((name, k, len(hull["f"]), retreat))
        final[name] = dict(kind=p["kind"], hulls=hulls, base_kg=p["base_kg"], origin=list(T.ORIGINS[name]))

    trims = trim_shapes(parts, final)
    for name, f in final.items():
        f["centroid"] = body_centroid([h["v"] for h in f["hulls"]]).tolist()
    for (root, tip), share in T.MASS_SPLITS.items():
        both = final[root]["base_kg"] + final[tip]["base_kg"]
        final[root]["base_kg"], final[tip]["base_kg"] = share * both, (1 - share) * both

    names = list(final)
    m0 = np.array([final[n]["base_kg"] for n in names])
    pos = np.array([final[n]["centroid"] for n in names])
    free = np.array([final[n]["kind"] not in FIXED_MASS for n in names])
    basis_cols = np.c_[np.ones(len(names)), pos[:, 1], pos[:, 2]]
    need = np.array([T.TOTAL_KG - m0.sum(), *(T.TOTAL_KG * target[1:] - (m0[:, None] * pos[:, 1:]).sum(0))])
    basis = basis_cols * (m0 * free)[:, None]
    coef = np.linalg.solve(basis_cols.T @ basis, need)
    m = m0 + basis @ coef
    for i, n in enumerate(names):
        final[n]["mass"] = round(float(m[i]), 1)
    final["Centurion"]["mass"] = round(final["Centurion"]["mass"] + T.TOTAL_KG - sum(final[n]["mass"] for n in names), 1)
    cg = sum(final[n]["mass"] * pos[i] for i, n in enumerate(names)) / T.TOTAL_KG

    # origins inside their own main shape; tank fire reaching along the chain and to each bay
    for n in names:
        depth = inside_by(np.asarray(final[n]["origin"]), np.asarray(final[n]["hulls"][0]["v"]))
        final[n]["origin_depth"] = depth
        if depth <= 0:
            raise SystemExit(f"{n}: origin {final[n]['origin']} lies {-depth * 1000:.1f} mm outside its shape")
    reach = {}
    for src, targets in FIRE_LINKS.items():
        main_v = np.asarray(final[src]["hulls"][0]["v"])
        r = fire_radius(main_v)
        for tgt in targets:
            d = min(dist_to_hull(np.asarray(final[src]["origin"]), np.asarray(h["v"])) for h in final[tgt]["hulls"])
            reach[f"{src} -> {tgt}"] = round(r - d, 3)
            if r - d <= 0:
                raise SystemExit(f"{src}'s fire ({r:.2f} m) misses {tgt} by {d - r:.2f} m")

    (work / "parts.json").write_text(json.dumps(dict(parts=final, target_cg=target.tolist(), cg=cg.tolist(), coef=coef.tolist(),
                                                    fire_reach=reach, trims=trims)))
    st = lambda y: y + T.ST0
    print(f"[damage_finalize] 0.1.3 CG station {st(target[1]):.4f}, {target[2]:.4f} m up; new {st(cg[1]):.4f}, {cg[2]:.4f} "
          f"({(cg[1] - target[1]) * 1000:+.2f}, {(cg[2] - target[2]) * 1000:+.2f} mm); max tris "
          f"{max(x[2] for x in notes)}, max retreat {max(x[3] for x in notes) * 1000:.0f} mm; "
          f"shallowest origin {min(final[n]['origin_depth'] for n in names) * 1000:.1f} mm in")
    print("[damage_finalize] trimmed: " + ", ".join(f"{k} {v}" for k, v in trims.items()))
    print("[damage_finalize] fire reach margins, m: " + ", ".join(f"{k} {v:+.2f}" for k, v in reach.items()))
    change = sorted(((final[n]["mass"] / final[n]["base_kg"] - 1, n) for n in names if final[n]["base_kg"]), key=lambda x: -abs(x[0]))
    print("[damage_finalize] largest mass changes: " + ", ".join(f"{n} {final[n]['base_kg']:.0f} -> {final[n]['mass']:.0f} kg ({d * 100:+.1f}%)" for d, n in change[:6]))


if __name__ == "__main__":
    main()
