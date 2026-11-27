"""Braced trusses behind the holes, as the stock Darkreach shows them (the owner's two crops, 2026-11-23: ours read as
flat planks): in each opening bay, trusses standing in from the skin, each two chords following the skin's line, posts
at the ends and Warren diagonals between, as box members on the stock structure sheet's flange strip. A wing bay's
trusses run chordwise (ribs), a body bay's round the body (frames); a few side by side across the bay.

build(bm, uvl, bay) adds one bay's trusses to a world-space bmesh and returns the faces; bay_of(points, normals, kind,
skin_tree) works out the bay from its open points."""
import math

import bmesh
from mathutils import Vector

import trim

MEMBER_W, MEMBER_T = 0.08, 0.04  # box section: across the truss plane, and in it (5 by 2.5 cm read as wire in the sample)
MIN_DEPTH = 0.10  # a bay shallower than this gets no truss (the outer wing's telescoping stages leave 5 to 8 cm)
PANEL_M = 0.3  # diagonal spacing along the chords
TOP_IN = 0.10  # the top chord at most this far under the skin (a quarter of a bay's depth, at least 2 cm): at 6 cm a
# body frame's ends showed through the speckle as pale squares
DEPTH_MAX, FAR_CLEAR = 0.35, 0.02  # truss depth, and the clearance kept from the far skin
SPACING_M, PER_BAY = 0.35, 4  # trusses side by side across the bay, at least two, at most PER_BAY


def bay_of(points, normals, kind, skin_tree, far_tree=None):
    """{centre, nm, t1, t2, half1, half2, depth} for a bay's open points (world), or None when it is too thin. The depth
    runs to the first thing behind the bay in far_tree (everything that renders: the outer wing's far skin is not
    its own where the telescoping stages sit inside it), else in skin_tree."""
    c = sum(points, Vector()) / len(points)
    nm = sum(normals, Vector()).normalized()
    t1, t2 = _axes(nm, kind)
    d1 = [(p - c).dot(t1) for p in points]
    d2 = [(p - c).dot(t2) for p in points]
    return bay_at(c, nm, kind, max(0.3, (max(d1) - min(d1)) / 2 + 0.15), (max(d2) - min(d2)) / 2, skin_tree, far_tree,
                  (max(d1) + min(d1)) / 2, (max(d2) + min(d2)) / 2)


def _axes(nm, kind):
    ref = Vector((0, 1, 0))  # along the fuselage
    if kind == "wing":
        t1 = (ref - nm * ref.dot(nm)).normalized()  # chordwise: a rib
    else:
        t1 = nm.cross(ref).normalized()  # round the body: a frame
    return t1, nm.cross(t1).normalized()


def bay_at(c, nm, kind, half1, half2, skin_tree, far_tree=None, mid1=0.0, mid2=0.0):
    """The bay at skin point c with outward normal nm, half1 along its trusses and half2 across them."""
    t1, t2 = _axes(nm, kind)
    h = (far_tree or skin_tree).ray_cast(c - nm * 0.03, -nm, 8.0)  # (a fuselage is wider than 3 m)
    thick = (h[0] - c).length if h[0] is not None else DEPTH_MAX + TOP_IN + FAR_CLEAR  # a part open behind (a shell over
    # a bay that belongs to another part) is deep enough
    top_in = min(TOP_IN, max(0.02, 0.25 * thick))
    depth = min(DEPTH_MAX, thick - top_in - FAR_CLEAR)
    if depth < MIN_DEPTH:
        return None
    return {"centre": c, "nm": nm, "t1": t1, "t2": t2, "top_in": top_in, "half1": half1, "mid1": mid1, "half2": half2,
            "mid2": mid2, "depth": depth}


PANEL_HOLE_M2 = 0.15  # a body bay gets frames only behind a hole this big: behind speckle a frame shows as a few pixels


def hole_area_at(c, nm, kind, paint, span=1.6, step=0.02):
    """The open area (m2, at 0 HP) of the hole at skin point c: the damage field on a flat span-by-span grid in the
    skin's tangent plane, the connected open region nearest c."""
    import numpy as np

    import damage_field as DF
    t1, t2 = _axes(nm, kind)
    n = int(span / step)
    g = (np.arange(n) - n / 2 + 0.5) * step
    a, b = np.meshgrid(g, g)
    pos = np.array(tuple(c))[None] + a.reshape(-1, 1) * np.array(tuple(t1))[None] + b.reshape(-1, 1) * np.array(tuple(t2))[None]
    m = (DF.open_hp(pos, paint) > 0).reshape(n, n)
    if not m.any():
        return 0.0
    ys, xs = np.nonzero(m)
    j = int(np.argmin((ys - n / 2) ** 2 + (xs - n / 2) ** 2))
    region = np.zeros_like(m)
    region[ys[j], xs[j]] = True
    while True:  # grow from the open sample nearest c through open neighbours (8-connected; Blender's Python has no scipy)
        g_ = region.copy()
        g_[1:] |= region[:-1]
        g_[:-1] |= region[1:]
        g_[:, 1:] |= g_[:, :-1].copy()
        g_[:, :-1] |= g_[:, 1:].copy()
        g_ &= m
        if (g_ == region).all():
            return float(region.sum() * step * step)
        region = g_


RIB_PITCH, RIB_CLEAR = 0.25, 0.008  # the backdrop's rib lines: spacing, and the gap left under the skin


def backdrop_ribs(bm, corners, nm, kind, depth):
    """Shallow ribs standing on a thin bay's dark backdrop (the sheet through `corners`, `depth` under the skin): a line
    every RIB_PITCH, running as a truss would (chordwise in a wing, round a body), each one web standing up to
    RIB_CLEAR under the skin, cut at the sheet's edges. Returns the faces (to be mapped on the flange strip)."""
    t1, t2 = _axes(nm, kind)
    c = sum(corners, Vector()) / len(corners)
    q = [((p - c).dot(t1), (p - c).dot(t2)) for p in corners]
    h = max(0.004, depth - RIB_CLEAR)
    faces = []
    lo2, hi2 = min(b for _, b in q), max(b for _, b in q)
    k = math.floor(lo2 / RIB_PITCH) + 1
    while k * RIB_PITCH < hi2:
        y = k * RIB_PITCH
        xs = []  # where the line t2 = y crosses the sheet's outline
        for (a0, b0), (a1, b1) in zip(q, q[1:] + q[:1]):
            if (b0 - y) * (b1 - y) < 0:
                xs.append(a0 + (a1 - a0) * (y - b0) / (b1 - b0))
        if len(xs) >= 2 and max(xs) - min(xs) > 0.1:
            a, b = min(xs) + 0.03, max(xs) - 0.03
            base = [c + t1 * x + t2 * y for x in (a, b)]
            plane = [p + nm * 1e-3 for p in base]  # a millimetre off the sheet, so the two never fight
            v = [bm.verts.new(p) for p in plane] + [bm.verts.new(p + nm * h) for p in reversed(plane)]
            faces.append(bm.faces.new(v))  # one web standing on the sheet (the structure material draws both sides)
        k += 1
    return faces


def _box(bm, p0, p1, across, inplane):
    """Four side faces of a box member from p0 to p1."""
    a, b = across * (MEMBER_W / 2), inplane * (MEMBER_T / 2)
    rings = [[bm.verts.new(p + s1 * a + s2 * b) for s1, s2 in ((-1, -1), (1, -1), (1, 1), (-1, 1))] for p in (p0, p1)]
    return [bm.faces.new((rings[0][k], rings[0][(k + 1) % 4], rings[1][(k + 1) % 4], rings[1][k])) for k in range(4)]


def build(bm, uvl, bay, skin_tree=None, far_tree=None):
    """Adds the bay's trusses to bm (world space) and returns their faces. With skin_tree, each truss's chords end where
    the skin above them leaves, and a truss is dropped unless every node has skin above it; with far_tree, unless every
    bottom node also has the far skin under it within FAR_CLEAR to a metre (the section curves away from the centre's
    depth)."""
    c0, nm, t1, t2 = bay["centre"], bay["nm"], bay["t1"], bay["t2"]
    n = max(2, min(PER_BAY, int(2 * bay["half2"] / SPACING_M) + 1))
    top_in = bay["top_in"]
    faces = []
    for k in range(n):
        off = bay["mid2"] + (0.0 if n == 1 else (k / (n - 1) - 0.5) * max(min(2 * bay["half2"], SPACING_M * (n - 1)), SPACING_M))
        base = c0 + t2 * off + t1 * bay["mid1"]
        half = bay["half1"]
        if skin_tree is not None:  # the chords end where the skin above them leaves (the bay's curve)
            for s in (-1, 1):
                while half > 0.25:
                    p = base + t1 * (s * half) - nm * top_in
                    h = skin_tree.ray_cast(p, nm, top_in + 0.08)
                    if h[0] is not None:
                        break
                    half -= 0.05
        npanel = max(2, round(2 * half / PANEL_M))
        top = [base - nm * top_in + t1 * (-half + 2 * half * i / npanel) for i in range(npanel + 1)]
        bot = [p - nm * bay["depth"] for p in top]
        if skin_tree is not None and not all(  # every node under the skin: its own skin above it, along the bay's normal
                skin_tree.ray_cast(p, nm, top_in + bay["depth"] + 0.1)[0] is not None for p in top + bot):
            continue  # (a bay at a wing tip took the tip cap's normal and stood its truss out of the skin)
        if far_tree is not None and not all(
                (lambda h: h[0] is not None and (h[0] - p).length >= FAR_CLEAR / 2)(far_tree.ray_cast(p - nm * 1e-3, -nm, 1.0)) for p in bot):
            continue
        members = [(top[0], top[-1], t1), (bot[0], bot[-1], t1), (top[0], bot[0], nm), (top[-1], bot[-1], nm)]
        for i in range(npanel):  # Warren diagonals, alternating
            a, b = (top[i], bot[i + 1]) if i % 2 == 0 else (bot[i], top[i + 1])
            members.append((a, b, (b - a).normalized()))
        for p0, p1, ax in members:
            fs = _box(bm, p0, p1, t2, ax.cross(t2).normalized())
            faces += trim.apply(bm, fs, (p1 - p0).normalized(), "flange")
    return faces
