"""Convex hull tools for collider and LOD1 hulls: build a hull, thin it to a vertex budget, inset it by a fixed
distance, and measure the gap between two hulls. Runs inside Blender (bmesh, mathutils) with numpy.

Points are float arrays of shape (N, 3) in one shared frame. A hull is (verts, tris): an (M, 3) array and a (K, 3)
int array of triangles wound outward.
"""

from itertools import combinations

import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def hull_mesh(points):
    """Convex hull of a point set, or None when the points span no volume."""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 4:
        return None
    bm = bmesh.new()
    res = bmesh.ops.convex_hull(bm, input=[bm.verts.new(tuple(p)) for p in pts])
    drop = {v for v in res["geom_interior"] + res["geom_unused"] if isinstance(v, bmesh.types.BMVert)}
    bmesh.ops.delete(bm, geom=list(drop), context="VERTS")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.index_update()
    verts = np.array([v.co[:] for v in bm.verts])
    tris = np.array([[v.index for v in f.verts] for f in bm.faces], dtype=int).reshape(-1, 3)
    bm.free()
    if len(tris) < 4:
        return None
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    cross = np.cross(b - a, c - a)
    flip = (cross * (a - verts.mean(0))).sum(1) < 0
    tris[flip] = tris[flip][:, ::-1]
    if abs((a * np.cross(b, c)).sum()) / 6 < 1e-9:
        return None
    return verts, tris


def hull_planes(verts, tris):
    """Outward unit normals n and offsets d of a hull's faces: inside is n.x <= d. Slivers are dropped."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    length = np.linalg.norm(n, axis=1)
    keep = length > 1e-10
    n = n[keep] / length[keep, None]
    return n, (n * a[keep]).sum(1)


def simplify_hull(points, max_verts):
    """At most max_verts of the hull's own vertices, chosen greedily as the point farthest outside the hull of those
    chosen so far, so the result stays inside the original hull and keeps its extremes."""
    hull = hull_mesh(points)
    if hull is None:
        return None
    v = hull[0]
    if len(v) <= max_verts:
        return v
    i0 = int(np.argmin(v[:, 0]))
    i1 = int(np.linalg.norm(v - v[i0], axis=1).argmax())
    axis = (v[i1] - v[i0]) / np.linalg.norm(v[i1] - v[i0])
    w = v - v[i0]
    i2 = int(np.linalg.norm(w - np.outer(w @ axis, axis), axis=1).argmax())
    normal = np.cross(v[i1] - v[i0], v[i2] - v[i0])
    i3 = int(np.abs(w @ normal).argmax())
    pick = [i0, i1, i2, i3]
    while len(pick) < max_verts:
        sub = hull_mesh(v[pick])
        if sub is None:
            break
        n, d = hull_planes(*sub)
        outside = (v @ n.T - d).max(1)
        k = int(outside.argmax())
        if outside[k] < 1e-6:
            break
        pick.append(k)
    return v[pick]


def merge_close(points, tol):
    """Collapse points that share a tol-sized grid cell."""
    _, first = np.unique(np.round(points / tol), axis=0, return_index=True)
    return points[np.sort(first)]


def inset_hull(points, dist, exact_fallback=False):
    """The hull of points with every face plane moved inward by dist, or None when nothing survives. Candidate
    vertices are the intersections of each plane triple meeting at one original vertex, kept when they satisfy every
    moved plane; where the inset swallows a small face the result can only come out smaller, never larger.
    exact_fallback: when that result is far smaller than the inset should be, intersect every plane triple instead
    (blockout step 6; step 5 was built without it)."""
    hull = hull_mesh(points)
    if hull is None:
        return None
    v, t = hull
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a)
    length = np.linalg.norm(n, axis=1)
    ok = length > 1e-12
    n[ok] /= length[ok, None]
    d = (n * a).sum(1) - dist
    triples = set()
    for vi in range(len(v)):
        faces = [f for f in np.nonzero((t == vi).any(1) & ok)[0]]
        distinct = []
        for f in faces:  # coplanar triangles of one face give a singular triple; keep one plane each
            if all(abs(n[f] @ n[g] - 1) > 1e-9 or abs(d[f] - d[g]) > 1e-7 for g in distinct):
                distinct.append(f)
        triples.update(combinations(distinct, 3))
    if not triples:
        return None
    tri = np.array(sorted(triples))
    A, rhs = n[tri], d[tri]
    solvable = np.abs(np.linalg.det(A)) > 1e-8
    if not solvable.any():
        return None
    x = np.linalg.solve(A[solvable], rhs[solvable][..., None])[..., 0]
    keep = (x @ n[ok].T - d[ok]).max(1) <= 1e-6
    out = hull_mesh(merge_close(x[keep], 1e-4)) if keep.sum() >= 4 else None
    # Where small faces vanish, the inset's corners come from planes that never met at one vertex, so on a long thin
    # hull of many near-coplanar faces the result above can collapse to a sliver. Then intersect every plane triple.
    area = (length[ok] / 2).sum()
    expected = volume(v, t) - area * dist
    if exact_fallback and expected > 0 and (out is None or volume(*out) < 0.75 * expected):
        out = inset_exact(n[ok], d[ok])
    return out


def volume(verts, tris):
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    return abs((a * np.cross(b, c)).sum()) / 6


def inset_exact(n, d, chunk=200000):
    """The vertices of the intersection of the half-spaces n.x <= d, by solving every triple of distinct planes."""
    _, first = np.unique(np.round(np.c_[n, d], 7), axis=0, return_index=True)
    n, d = n[first], d[first]
    found = []
    triples = np.array(list(combinations(range(len(n)), 3)))
    for i in range(0, len(triples), chunk):
        tri = triples[i:i + chunk]
        A, rhs = n[tri], d[tri]
        solvable = np.abs(np.linalg.det(A)) > 1e-8
        x = np.linalg.solve(A[solvable], rhs[solvable][..., None])[..., 0]
        found.append(x[(x @ n.T - d).max(1) <= 1e-6])
    x = np.concatenate(found) if found else np.zeros((0, 3))
    return hull_mesh(merge_close(x, 1e-4)) if len(x) >= 4 else None


def hull_edges(tris):
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    return np.unique(e, axis=0)


def segment_distance(p1, q1, p2, q2):
    """Smallest distance between any segment p1-q1 (N, 3) and any segment p2-q2 (M, 3) (Ericson, RTCD 5.1.9)."""
    d1, d2 = q1 - p1, q2 - p2
    r = p1[:, None, :] - p2[None, :, :]
    a = (d1 * d1).sum(1)[:, None]
    e = (d2 * d2).sum(1)[None, :]
    f = (d2[None] * r).sum(2)
    c = (d1[:, None] * r).sum(2)
    b = d1 @ d2.T
    den = a * e - b * b
    s = np.where(den > 1e-12, np.clip((b * f - c * e) / np.where(den > 1e-12, den, 1.0), 0, 1), 0.0)
    t = (b * s + f) / e
    s = np.where(t < 0, np.clip(-c / a, 0, 1), np.where(t > 1, np.clip((b - c) / a, 0, 1), s))
    t = np.clip(t, 0, 1)
    diff = r + d1[:, None] * s[..., None] - d2[None] * t[..., None]
    return float(np.sqrt((diff ** 2).sum(2).min()))


def hull_gap(a, b):
    """Smallest distance between two convex hulls (verts, tris), 0.0 when they touch or overlap."""
    (av, at), (bv, bt) = a, b
    an, ad = hull_planes(av, at)
    bn, bd = hull_planes(bv, bt)
    if ((av @ bn.T - bd).max(1) <= 0).any() or ((bv @ an.T - ad).max(1) <= 0).any():
        return 0.0
    ta = BVHTree.FromPolygons([Vector(x) for x in av], at.tolist())
    tb = BVHTree.FromPolygons([Vector(x) for x in bv], bt.tolist())
    if ta.overlap(tb):
        return 0.0
    vertex_face = min(min(tb.find_nearest(Vector(x))[3] for x in av), min(ta.find_nearest(Vector(x))[3] for x in bv))
    ea, eb = hull_edges(at), hull_edges(bt)
    edge_edge = segment_distance(av[ea[:, 0]], av[ea[:, 1]], bv[eb[:, 0]], bv[eb[:, 1]])
    return min(vertex_face, edge_edge)
