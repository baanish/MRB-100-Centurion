"""Measured sections of the pass's skin, and structure members built on them.

Round 1 fitted its frames to a farthest-point outline in 16 to 48 sectors, so frame edges stood outside the skin
wherever it curved inward between samples, and it mapped each face onto its trim strip on its own, so the strip's
direction jumped from face to face (the zigzag). Here a member's outline is the skin itself, cut by the member's plane
(or, at a cut, the seam's own boundary edges); inset in that plane; and its UVs run continuously along the member,
broken only where the strip's length runs out (a new piece starts at u0 on its own vertices).
"""
import math

import bmesh
from mathutils import Vector

import trim

SKIN = "Centurion_skin"


def skin_bm(o):
    """The object's outward skin (no twins, no liners) in world space."""
    me = o.data
    sk = {i for i, m in enumerate(me.materials) if m and m.name == SKIN}
    tw = [0] * len(me.polygons)
    if "twin_src" in me.attributes:
        me.attributes["twin_src"].data.foreach_get("value", tw)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(o.matrix_world)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in sk or tw[f.index]], context="FACES")
    return bm


class Loop(list):
    """An ordered chain of points that knows whether it closes on itself (its last point links back to its first): the
    distance between the ends cannot say, since a closed loop's last edge is as long as any other (85 and 96 mm on the
    inner wing and pylon seams)."""
    is_closed = False


def chain(edges):
    """Edges (pairs of hashable vertex keys with positions) into ordered loops: [Loop, ...] (open chains too). Keys must
    be stable vertex identities: id() of a bmesh wrapper is not (a 60-edge seam came out as no loop)."""
    adj = {}
    pos = {}
    for (ka, pa), (kb, pb) in edges:
        if ka == kb:
            continue
        adj.setdefault(ka, []).append(kb)
        adj.setdefault(kb, []).append(ka)
        pos[ka], pos[kb] = pa, pb
    seen, loops = set(), []
    for start in adj:
        if start in seen:
            continue
        # begin at an open end if this component has one
        comp, stack = [], [start]
        while stack:
            k = stack.pop()
            if k in comp:
                continue
            comp.append(k)
            stack += [n for n in adj[k] if n not in comp]
        ends = [k for k in comp if len(adj[k]) == 1]
        k = first = ends[0] if ends else start
        loop, prev, last = Loop(), None, None
        while k is not None and k not in seen:
            seen.add(k)
            loop.append(pos[k])
            last = k
            nxt = [n for n in adj[k] if n != prev and n not in seen]
            prev, k = k, (nxt[0] if nxt else None)
        loop.is_closed = not ends and len(loop) >= 3 and first in adj.get(last, [])
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def section_loops(o, co, no):
    """The skin cut by the plane: ordered loops of world points, longest first."""
    bm = skin_bm(o)
    res = bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces), plane_co=co, plane_no=no)
    bm.verts.index_update()  # the cut's new vertices get indices too: stable keys for chain()
    keyed = [((e.verts[0].index, e.verts[0].co.copy()), (e.verts[1].index, e.verts[1].co.copy()))
             for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    bm.free()
    return sorted(chain(keyed), key=lambda lp: -length(lp))


def boundary_loops(o, co, no, tol=0.002):
    """The skin's open edges lying in the plane (a cut's seam), as ordered loops, longest first."""
    bm = skin_bm(o)
    bm.verts.index_update()
    keyed = [((e.verts[0].index, e.verts[0].co.copy()), (e.verts[1].index, e.verts[1].co.copy())) for e in bm.edges
             if e.is_boundary and all(abs((v.co - co).dot(no)) < tol for v in e.verts)]
    bm.free()
    return sorted(chain(keyed), key=lambda lp: -length(lp))


def bridge(chains, no):
    """Open chains lying in one plane joined into one closed loop: each chain in turn round their common centroid,
    oriented to start at the end nearer the previous chain's last point. The aft body's cut has five open chains and the
    fin root's eight: each bridge is a straight edge across a gap in the skin's seam."""
    pts = [p for c in chains for p in c]
    if len(pts) < 3:
        return None
    c0 = sum(pts, Vector()) / len(pts)
    e1, e2 = basis(no)
    ang = lambda c: math.atan2(((sum(c, Vector()) / len(c)) - c0).dot(e2), ((sum(c, Vector()) / len(c)) - c0).dot(e1))  # noqa: E731
    out, gaps = Loop(), 0.0
    for ch in sorted(chains, key=ang):
        ch = list(ch)
        if out and (ch[-1] - out[-1]).length < (ch[0] - out[-1]).length:
            ch.reverse()
        if out:
            gaps += (ch[0] - out[-1]).length
        out.extend(ch)
    gaps += (out[0] - out[-1]).length
    if gaps > 0.25 * length(out):
        return None  # mostly bridge: the chains belong to different shells (fuselage_F's plane bridged to 35 m)
    out.is_closed = True
    return out


def open_band(bm, chain, centre, k, strip, uv):
    """A partial frame along one open chain: quads between the chain and its points scaled k toward centre (the plane's
    section centroid, so the band lies inside), the strip along the chain. Returns the faces."""
    (u0, u1, v0, v1), tpm, _ = trim.TRIMS[strip]
    L = trim.strip_metres(strip)
    across_m = (v1 - v0) * trim.ATLAS_PX / (tpm * 0.55)
    inner = [centre + (p - centre) * k for p in chain]
    s, faces = 0.0, []
    for i in range(len(chain) - 1):
        seg = (chain[i + 1] - chain[i]).length
        ua, ub = (s % L) / L, (s % L + seg) / L
        if ub > 1.0:
            ua, ub = 0.0, min(1.0, seg / L)
        s += seg
        quad = [chain[i], chain[i + 1], inner[i + 1], inner[i]]
        if (quad[0] - quad[3]).length < 1e-4 or seg < 1e-4:
            continue
        try:
            f = bm.faces.new([bm.verts.new(p) for p in quad])
        except ValueError:
            continue
        w = [0.0, 0.0, (chain[i + 1] - inner[i + 1]).length, (chain[i] - inner[i]).length]
        for l, u, d in zip(f.loops, (ua, ub, ub, ua), w):
            l[uv].uv = (u0 + u * (u1 - u0), v1 - min(1.0, d / across_m) * (v1 - v0))
        faces.append(f)
    return faces


def length(loop, closed=True):
    n = len(loop)
    return sum((loop[(k + 1) % n] - loop[k]).length for k in range(n if closed else n - 1))


def basis(no):
    e1 = no.orthogonal().normalized()
    return e1, no.cross(e1).normalized()


def closed(loop):
    return loop.is_closed if isinstance(loop, Loop) else (loop[0] - loop[-1]).length < 0.05


def inset(loop, no, d):
    """The loop offset d metres into itself, in its plane (negative d: outward)."""
    n = len(loop)
    e1, e2 = basis(no)
    pts = [(p.dot(e1), p.dot(e2)) for p in loop]
    area = sum(pts[k][0] * pts[(k + 1) % n][1] - pts[(k + 1) % n][0] * pts[k][1] for k in range(n))
    sgn = 1 if area > 0 else -1  # counter-clockwise: the inside is to the left of each edge
    out = []
    for k in range(n):
        a, b, c = loop[k - 1], loop[k], loop[(k + 1) % n]
        normals = []
        for p, q in ((a, b), (b, c)):
            t = q - p
            if t.length > 1e-9:
                normals.append(no.cross(t).normalized() * sgn)
        m = sum(normals, Vector()) if normals else Vector()
        if m.length < 1e-9:
            out.append(b.copy())
            continue
        m.normalize()
        cosh = max(0.35, min(1.0, m.dot(normals[0])))  # mitre, capped at sharp corners
        out.append(b + m * (d / cosh))
    return out


def resample(loop, n):
    """n points evenly spaced by arc length round the closed loop, from its first point."""
    total = length(loop)
    pts, acc, k = [], 0.0, 0
    seg = [(loop[i], loop[(i + 1) % len(loop)]) for i in range(len(loop))]
    lens = [(b - a).length for a, b in seg]
    for j in range(n):
        target = total * j / n
        while k < len(seg) - 1 and acc + lens[k] < target:
            acc += lens[k]
            k += 1
        t = (target - acc) / lens[k] if lens[k] > 1e-12 else 0.0
        pts.append(seg[k][0].lerp(seg[k][1], max(0.0, min(1.0, t))))
    return pts


def point_in(p, loop, no):
    e1, e2 = basis(no)
    x, y = p.dot(e1), p.dot(e2)
    poly = [(q.dot(e1), q.dot(e2)) for q in loop]
    inside = False
    for k in range(len(poly)):
        (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def web_plate(bm, loop, no, ch, up, strip, uv, inset_m=0.015, step=0.08):
    """A rib web filling a wing-like section, as the Darkreach's break web: chord-wise quads from the upper skin to the
    lower at stations `step` apart, `inset_m` in from both skins and both ends, the strip running along the chord (the
    stock web's hex openings in a row) and across the section's depth. Returns the faces."""
    (u0, u1, v0, v1), tpm, _ = trim.TRIMS[strip]
    L = trim.strip_metres(strip)
    across_m = (v1 - v0) * trim.ATLAS_PX / (tpm * 0.55)
    c = sum(loop, Vector()) / len(loop)
    xy = [((p - c).dot(ch), (p - c).dot(up)) for p in loop]
    x_lo, x_hi = min(x for x, _ in xy) + inset_m, max(x for x, _ in xy) - inset_m
    if x_hi <= x_lo:
        return []
    per_piece = max(1, round(L / step))  # columns a strip piece holds, so a quad never straddles two pieces
    m = max(1, math.ceil((x_hi - x_lo) / L * per_piece))
    n = len(xy)
    cols = []
    for k in range(m + 1):
        x = x_lo + (x_hi - x_lo) * k / m
        ys = []
        for i in range(n):  # the section's crossings of the station line
            (xa, ya), (xb, yb) = xy[i], xy[(i + 1) % n]
            if (xa - x) * (xb - x) <= 0 and xa != xb:
                ys.append(ya + (yb - ya) * (x - xa) / (xb - xa))
        ys.sort()  # inside runs between crossings 0-1, 2-3, ...: the deepest one (a section of two pieces, a wing and a
        spans = [(ys[i + 1], ys[i]) for i in range(0, len(ys) - 1, 2)]  # tip pod, had its web from top to bottom across the gap)
        if spans:
            top, bot = max(spans, key=lambda s: s[0] - s[1])
            if top - bot > 2.5 * inset_m:
                cols.append((k, x, top - inset_m, bot + inset_m))
    faces = []
    for (ka, xa, ta, ba), (kb, xb, tb, bb) in zip(cols, cols[1:]):
        if kb != ka + 1:
            continue  # a gap in the section (a slot): no quad across it
        ua = (ka % per_piece) / per_piece
        ub = ua + 1.0 / per_piece
        quad = [(xa, ta, ua, v1), (xb, tb, ub, v1), (xb, bb, ub, v0), (xa, ba, ua, v0)]
        f = bm.faces.new([bm.verts.new(c + ch * x + up * y) for x, y, _, _ in quad])
        for l, (_, _, u, v) in zip(f.loops, quad):  # the web's full depth on the strip's full height: its hex row in the
            l[uv].uv = (u0 + u * (u1 - u0), v)  # web's middle, its opaque margins top and bottom
        faces.append(f)
    return faces


def band(bm, outer, inner, strip, uv, flip=False, width_m=None):
    """Quads between two closed point loops of equal length: continuous UVs along the band, the strip's length per
    piece (a piece starts at u0 on its own vertices), outer edge at v1 and inner at v1 less the band's width in strip
    units. Returns the faces."""
    (u0, u1, v0, v1), tpm, _ = trim.TRIMS[strip]
    L = trim.strip_metres(strip)
    across_m = (v1 - v0) * trim.ATLAS_PX / (tpm * 0.55)  # the strip's height at about 55% of its length rate (sol2: ~100 px/m across)
    n = len(outer)
    s = [0.0]
    for k in range(n):
        s.append(s[-1] + (outer[(k + 1) % n] - outer[k]).length)
    pieces = max(1, math.ceil(s[-1] / L))
    piece_len = s[-1] / pieces
    faces = []
    for j in range(pieces):
        ks = [k for k in range(n) if j * piece_len <= s[k] < (j + 1) * piece_len + 1e-9] + [None]
        ks = [k for k in ks if k is not None]
        if not ks:
            continue
        ks.append((ks[-1] + 1) % n)  # close the piece on its next point
        vo, vi = [], []
        for k in ks:
            sk = s[k] if k != 0 or ks.index(k) == 0 else s[-1]
            t = (sk - j * piece_len) / piece_len
            w = (outer[k] - inner[k]).length
            vo.append((bm.verts.new(outer[k]), (u0 + min(max(t, 0), 1) * (u1 - u0), v1)))
            vi.append((bm.verts.new(inner[k]), (u0 + min(max(t, 0), 1) * (u1 - u0), v1 - min(1.0, w / across_m) * (v1 - v0))))
        for a in range(len(ks) - 1):
            q = [vo[a], vo[a + 1], vi[a + 1], vi[a]]
            f = bm.faces.new([x[0] for x in (q[::-1] if flip else q)])
            for l in f.loops:
                l[uv].uv = next(x[1] for x in q if x[0] is l.vert)
            faces.append(f)
    return faces


def ring(bm, loop, no, inset_m, hole_m, strip, sheets=1, depth=0.012, push=None):
    """A frame or rib on its section: the loop inset by inset_m, an opening inset by hole_m, `sheets` faces `depth`
    apart along push (into the part). Continuous strip UVs. Returns the faces."""
    uv = bm.loops.layers.uv.get("UVMap") or bm.loops.layers.uv.new("UVMap")
    pts = resample(loop, max(12, min(64, int(length(loop) / 0.12))))
    outer = inset(pts, no, inset_m)
    inner = inset(pts, no, hole_m)
    faces = []
    push = push if push is not None else no
    for k in range(sheets):
        off = push * (depth * k)
        faces += band(bm, [p + off for p in outer], [p + off for p in inner], strip, uv, flip=bool(k))
    return faces
