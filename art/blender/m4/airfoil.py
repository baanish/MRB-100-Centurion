"""Airfoil surfaces the lifting-surface groups share (wing, struts, V-tail): a section family as a parametric surface,
lofts into closed shells, ring builders, and the inverse map for the paint.

A section family is a function sec(x) -> (leading edge, chord, thickness, chord direction, thickness direction,
camber), every section the blockout's (build_centurion.airfoil: NACA four-digit thickness, blunt trailing edge) taken
with more points, so a detailed skin lies on the surface the colliders and checks were designed on. x is the family's
own span coordinate (semi-span for the wing, distance along the panel for the V-tail, along the member for a strut).

- AirfoilSurface: a section family as a surface point(x, sigma), so the shell builders in m4/surface.py
  (surface_patch, outline_frame) work on it. sigma runs from the lower trailing edge (-1) through the leading edge (0)
  to the upper trailing edge (+1), the chord fraction being sigma squared.
- table_section: a family interpolated from a table of sections.
- loft: rings into a closed shell on a Part, with UV seams, soft leading edges and per-face slots.
- Ring builders: ring (one section), inset_ring (a soft bevel's inner edge), aft_ring (a control surface's section
  with a rounded nose), fairing_ring (a superellipse fairing section).
- discharger: a static discharger on a trailing edge.
- SectionCoords: the inverse map, (x, chord fraction, chord, upper side) of baked texel positions, for the paint.
"""

import math

import numpy as np
from mathutils import Vector

from . import surface as sf


# ---------- section families ----------
def table_section(bl, table):
    """Sections interpolated from a table of (x, leading edge, chord, thickness), x ascending, in the blockout wing's
    chord and thickness directions and camber (the raked tip)."""
    xs = [r[0] for r in table]

    def sec(x):
        i = max(0, min(len(xs) - 2, next((k for k in range(len(xs) - 1) if x <= xs[k + 1]), len(xs) - 2)))
        f = (x - xs[i]) / (xs[i + 1] - xs[i])
        a, b = table[i], table[i + 1]
        return (a[1].lerp(b[1], f), a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f,
                bl.CDIR, bl.TDIR, bl.WING_CAMBER)
    return sec


def ring(bl, sec, x, n, cut=None):
    """The closed section at x: upper trailing edge, leading edge (index n), lower trailing edge (index 2n)."""
    le, c, t, cd, td, cam = sec(x)
    return bl.airfoil(le, c, t, cd, td, cam, n=n, cut=cut)


class AirfoilSurface:
    """A section family as a parametric surface, duck-typed like surface.Fuselage (point and normal of (s, a))."""

    def __init__(self, bl, sec):
        self.bl, self.sec = bl, sec

    def frac(self, x, t, upper):
        le, c, th, cd, td, cam = self.sec(x)
        return self.bl.airfoil_point(le, c, th, cd, td, cam, min(max(t, 0.0), 1.0), upper)

    def point(self, x, sigma, off=0.0):
        p = self.frac(x, sigma * sigma, sigma >= 0)
        return p + self.normal(x, sigma) * off if off else p

    def normal(self, x, sigma):
        dx, ds = 0.01, 0.004
        a = self.point(x + dx, sigma) - self.point(x - dx, sigma)
        b = self.point(x, sigma + ds) - self.point(x, sigma - ds)
        n = a.cross(b).normalized()
        le, c, th, cd, td, cam = self.sec(x)
        inner = self.bl.camber_point(le, c, cd, td, cam, 0.3)
        return n if n.dot(self.point(x, sigma) - inner) > 0 else -n


# ---------- rings ----------
def inset_ring(pts, cdir, tdir, d):
    """The ring moved d inward in its own plane: the inner edge of a soft bevel."""
    o = pts[0]
    q = [((p - o).dot(cdir), (p - o).dot(tdir)) for p in pts]
    n = len(q)
    area = sum(q[i][0] * q[(i + 1) % n][1] - q[(i + 1) % n][0] * q[i][1] for i in range(n))
    sgn = 1.0 if area > 0 else -1.0
    out = []
    for i in range(n):
        (x0, y0), (x1, y1) = q[i - 1], q[(i + 1) % n]
        tx, ty = x1 - x0, y1 - y0
        L = math.hypot(tx, ty) or 1.0
        out.append(pts[i] + cdir * (-ty / L * sgn * d) + tdir * (tx / L * sgn * d))
    return out


def aft_ring(bl, sec, x, t0, n, nose_pts=5, nose_k=0.6):
    """A control surface's section aft of chord fraction t0: the upper surface from the trailing edge forward, a
    rounded nose whose front sits on the camber line at t0, the lower surface back to the trailing edge.
    2 (n + 1) + nose_pts points; the nose's middle point is index n + 1 + nose_pts // 2."""
    le, c, th, cd, td, cam = sec(x)

    def P(t, up):
        return bl.airfoil_point(le, c, th, cd, td, cam, t, up)

    def C(t):
        return bl.camber_point(le, c, cd, td, cam, t)

    yu = (P(t0, True) - C(t0)).dot(td)
    nose = min(nose_k * yu, 0.3 * c * (1 - t0))
    tc = t0 + nose / c
    ts = [tc + (1 - tc) * k / n for k in range(n + 1)]
    ctr = C(tc)
    hu, hl = (P(tc, True) - ctr).dot(td), (P(tc, False) - ctr).dot(td)
    arc = []
    for i in range(1, nose_pts + 1):
        phi = math.pi / 2 - math.pi * i / (nose_pts + 1)
        h = hu * math.sin(phi) if phi >= 0 else -hl * math.sin(phi)
        arc.append(ctr - cd * (nose * math.cos(phi) ** 0.8) + td * h)
    return [P(t, True) for t in reversed(ts)] + arc + [P(t, False) for t in ts]


def fairing_ring(centre, across, up, half_w, top, bottom, m=12, p=2.6):
    """A closed superellipse section, half_w wide, from bottom to top along up (offsets from centre). Point 0 is on
    top, so a seam there is hidden when the top is buried."""
    zc, hh = (top + bottom) / 2, (top - bottom) / 2
    pts = []
    for k in range(m):
        a = 2 * math.pi * k / m
        s, c = math.sin(a), math.cos(a)
        pts.append(centre + across * (half_w * math.copysign(abs(s) ** (2 / p), s))
                   + up * (zc + hh * math.copysign(abs(c) ** (2 / p), c)))
    return pts


# ---------- shells ----------
def loft(part, rings, slot, cls, seams=(), soft=(), ring_seams=(), start="cap", end="cap", cap_slot=None,
         cap_cls=None, face_tag=None):
    """Rings of equal size lofted into a closed shell: each end closed by a zipped cap ("cap") or a fan to a pole
    (a Vector). cap_slot, cap_cls: (start, end) for the caps, None for the side's. face_tag(r, k) may return a
    (slot, cls) for the face from ring r to r + 1 between columns k and k + 1. soft: columns whose lengthwise edges
    stay smooth-shaded past the blockout's 50 degree hard-edge angle (leading edges). Returns the Grid."""
    bm = part.bm
    g = sf.Grid(bm, rings, loop=True)
    part.tag(g.faces(), slot, cls)
    if face_tag:
        for (r, k), f in g.F.items():
            t = face_tag(r, k)
            if t:
                part.tag([f], *t)
    for k in seams:
        g.seam_column(k)
    for r in ring_seams:
        g.seam_ring(r)
    if soft:
        lay = bm.edges.layers.int.get("soft") or bm.edges.layers.int.new("soft")
        for k in soft:
            for r in range(len(rings) - 1):
                e = bm.edges.get((g.V[r][k], g.V[r + 1][k]))
                if e is not None:
                    e[lay] = 1
    n = len(rings[0])
    caps = []
    for which, kind in ((0, start), (1, end)):
        ring_v = g.V[0][::-1] if which == 0 else g.V[-1]
        cs = (cap_slot or (None, None))[which] or slot
        cc = (cap_cls or (None, None))[which]
        cc = cls if cc is None else cc
        if kind == "cap":
            faces = sf.cap(bm, ring_v)
        elif isinstance(kind, Vector):
            pole = bm.verts.new(kind)
            faces = [bm.faces.new((ring_v[k], ring_v[(k + 1) % n], pole)) for k in range(n)]
            sf.seam(bm, ring_v[0], pole)
        else:
            continue
        part.tag(faces, cs, cc)
        caps.append(faces)
    g.caps = caps
    return g


def discharger(part, base, aft, up, slot, length=0.24, r=0.009):
    """A static discharger: a thin tapered rod running aft from a trailing edge, its root buried in the edge."""
    a = aft.normalized()
    return sf.revolve_axis(part, ((r * 1.6, -0.03), (r * 1.4, 0.02), (r, 0.05), (r * 0.6, length - 0.01), (0, length)),
                           base, a, 5, slot, sf.FITTING, ref=up)


# ---------- paint coordinates ----------
class SectionCoords:
    """(x, chord fraction, chord, upper side) of points near a section family, from sections sampled along it.
    origin and axis: x is measured along axis from origin (the V-tail); by default it is |world x| (the wing)."""

    def __init__(self, sec, xs, origin=None, axis=None):
        rows = [sec(float(x)) for x in xs]
        self.xs = np.asarray(xs, float)
        self.le = np.array([tuple(r[0]) for r in rows])
        self.c = np.array([r[1] for r in rows])
        self.cdir, self.tdir = np.array(tuple(rows[0][3])), np.array(tuple(rows[0][4]))
        self.origin = None if origin is None else np.array(tuple(origin))
        self.axis = None if axis is None else np.array(tuple(axis))

    def locate(self, pos, nrm):
        x = np.abs(pos[:, 0]) if self.axis is None else (pos - self.origin) @ self.axis
        le = np.stack([np.interp(x, self.xs, self.le[:, i]) for i in range(3)], axis=1)
        c = np.interp(x, self.xs, self.c)
        u = ((pos - le) @ self.cdir) / c
        return x, u, c, (nrm @ self.tdir) > 0

    def plane(self, pos):
        """Chordwise and thickness-wise offsets (metres) from the leading edge, in the section plane."""
        x = np.abs(pos[:, 0]) if self.axis is None else (pos - self.origin) @ self.axis
        le = np.stack([np.interp(x, self.xs, self.le[:, i]) for i in range(3)], axis=1)
        return (pos - le) @ self.cdir, (pos - le) @ self.tdir
