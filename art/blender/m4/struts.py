"""Part group 5: the struts and sponsons.

Parts: strut_inner_L/R (body side to the node inside the engine core: the root fairing onto the body, the collar where
the strut enters the cowl), strut_outer_L/R (node to the wing at 19.4 m, 62% chord: the collar where it leaves the
cowl, the taper and the node fairing on the wing's lower skin), sponson_L/R (the main gear pod, faired into the body,
with the main gear well cut in) and geardoor_LM/RM's _visible meshes. Right-hand parts are the left's mirrored, face
for face, and reuse the left's UV islands (MIRROR_PARTS).

The strut follows the blockout's line and 18% section on a 2.25 m chord, with a 5 mm render trailing edge. Its root
fairing lands on the body and sponson union along a circular fillet over a wing-body flare. Tight quarter-round
collars terminate the skin inside the cowl and the node pod; the node closure is buried in the fixed wing.

The sponson is step 6.1's pod (build_centurion.sponson_section: stations 19.4 to 32.9, 1.85 m wide and 2.2 m tall,
an elliptic nose seated on the skin, a full section over the stowed bogie, a long tail running up into the body's
side) smooth-unioned with the body in every section, so it turns into the body along a fillet instead of meeting it
at a crease; over its nose and tail the union measures the pod in three dimensions, so the ends turn into the body
too. The main gear well is cut into its underside, between the door hinge line (x 2.05) and the lower outboard flank,
at the door's stations; the legs and wheels are the gear group's.

No text: every island here is shared with the right-hand side (MIRROR_PARTS), where text would read backwards, and the
entry script mirrors whole parts, so no island can be kept unique. Placards are plain ruled rectangles."""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

from . import airfoil as af
from . import render
from . import surface as sf
from .paint import INTERIOR
from .surface import DOOR, FITTING
from .struts_hull import conform_root_boundary, hull_triangles, land_root_column

GROUP = "struts"
PARTS = ("strut_inner_L", "strut_inner_R", "strut_outer_L", "strut_outer_R", "sponson_L", "sponson_R",
         "geardoor_LM_visible", "geardoor_RM_visible")
BUDGET_TRIS = 13400  # Lead's round 2 budget call, 2026-10-14; 400 more from the gear group for the hinge bump (HINGE_BUMP).
MIRROR_PARTS = {n: n.replace("_R", "_L", 1) for n in PARTS if "_R" in n}
# Close-ups (m4/render.py's view form); the first four make the contact sheet.
# The review sun shines from ahead, right and above, so the close-ups look at the right-hand side (x < 0), whose parts
# are the left's mirrored and wear the same maps.
VIEWS = {
    "strut34": (30, (-17.0, 5.5, 1.3), (-8.5, 19.2, 3.6)),
    "collar_out": (50, (-12.6, 15.4, 4.7), (-9.2, 19.9, 3.65)),
    "node": (34, (-21.2, 20.0, -0.6), (-19.1, 23.9, 5.2)),
    "side": (("ortho", 26.0, render.SIDE), (60.0, 22.5, 3.6), None),
    "well": (30, (-6.5, 20.0, -2.5), (-2.9, 25.4, 1.7)),  # under the ground (hidden), so the sky lights the well
    "root": (34, (-6.4, 11.0, 1.4), (-3.9, 17.8, 2.8)),
    "rear": (32, (-8.5, 37.5, 1.6), (-4.0, 24.0, 2.6)),
    "low": (30, (-11.0, 25.0, -8.0), (-6.0, 21.5, 3.0)),
    "fillet": (40, (-6.0, 33.0, 4.8), (-2.6, 27.5, 3.4)),
    "sponson_flank": (34, (-7.0, 21.0, 0.9), (-3.0, 26.0, 2.4)),  # under the right nacelle
    "root_close": (40, (-3.9, 13.0, 3.9), (-2.4, 17.4, 2.6)),
    "pod_fillet": (40, (-16.8, 21.6, 3.6), (-18.9, 23.5, 5.1)),
    "sponson_nose": (40, (-5.0, 17.0, -0.5), (-2.3, 19.8, 1.9)),
}

# Paint classes past the shared ones (m4/surface.py 1 to 5; the wing uses 11 to 23).
STRUT, ROOT_BOOT, COLLAR, NODE_POD, SPONSON = range(31, 36)
SKIN_CLASSES = (STRUT, ROOT_BOOT, COLLAR, NODE_POD, SPONSON, DOOR)

# ---------- strut ----------
# Section points a side (the blockout's 5), spaced as a half cosine to the power 1.5: about 11 to 25 degrees apart
# round the leading edge's nose, where facets show on the collars and fillets, sparse over the straight run to the
# blunt trailing edge. A ring is 2 SEC_N + 1 points.
SEC_N = 13
ROOT_SEC_N = 17
STRUT_TE = 0.0011  # 5 mm across the 2.25 m chord; the collider remains 28 mm inside the blockout skin
TE_NORMAL = 45.0  # Strut.normal at the trailing edge's two points, degrees off aft
# A collar's footprint sits this far inside the cowl, so its fillet crosses the faceted cowl at an angle (a clean
# line) instead of running tangent along it (a sawtooth on the facets).
COWL_IN = 0.02
# Where a fillet (fillet_column) meets the body or the node fairing: degrees into the surface at the landing, so it
# crosses a faceted neighbour along one clean line instead of grazing it, then the dive's angle and length (2 cm deep).
FILLET_LAND = (3.0, 60.0, 0.023)
# Root fairing on the body: a circular fillet of ROOT_R from the strut's skin onto the body (ROOT_ARC points from the
# landing to the strut), over a long flare of the chord and thickness (ROOT_FLARE at the body, gone ROOT_LEN along
# the axis) like a wing-body fairing's; plain flared rings at ROOT_STRUT_F of the way from the fillet to ROOT_LEN.
ROOT_R = 0.28  # continuous body fillet; its hull landing has no painted sealant lap
ROOT_BODY_IN = 0.018  # smooth analytic solve; the skin's landing is remapped onto detailed hull triangles
ROOT_FACET_IN = 0.005
ROOT_ARC = 10
ROOT_FLARE = 0.22
ROOT_LEN = 1.35
ROOT_STRUT_F = (0.45, 1.0)
# Collars on the cowl: a circular fillet of this radius between the cowl and the strut, its rings evenly spaced round
# the quarter circle (a tight bolted fitting, not a flare).
COLLAR_R = 0.11
COLLAR_RINGS = 5
COLLAR_T = tuple(COLLAR_R * (1 - math.cos(0.5 * math.pi * i / COLLAR_RINGS)) for i in range(COLLAR_RINGS + 1))
OUTER_MID = (13.0,)  # a plain ring on the outer segment, metres from the root (the segment is straight)
# The blockout's taper, from TAPER_START metres short of the node: each column's rings at these fractions of the way
# from its fillet onto the node fairing back to TAPER_START.
TAPER_START = 2.0
TAPER_U = (1.0, 0.66, 0.4, 0.2, 0.07)
# A quarter-round collar terminates each skin column inside the pod. Solving independent tangent fillets at the
# thin upper skin produced folds where the pod's surface changes normal rapidly.
POD_COLLAR_R, POD_COLLAR_ARC, POD_COLLAR_IN = 0.045, 6, 0.025
FOOT_INSET = 0.004  # the node fairing's top pressed into the wing's lower skin (the stages sit 11 mm above it)
# Node fairing on the wing's lower skin, round the strut's foot: metres ahead of and behind the node, half width,
# depth, its centre's offset outboard of the node, and its fullest section as a fraction of its length. The tail
# ends 30 cm ahead of the aileron hinge.
POD_FWD, POD_AFT, POD_W, POD_D, POD_DX, POD_VM = 1.3, 0.78, 0.44, 0.27, -0.22, 0.42
POD_RINGS = 15  # cosine spaced along the pod, so the nose and the pointed tail get the most rings
POD_ARC = 13  # points on the fairing's lower arc
POD_FLANGE = (0.05, 0.007)  # the attachment flange on the wing skin: width past the fairing's side, thickness


def surface_grad(f, p, e=1e-3):
    g = Vector(((f(p + Vector((e, 0, 0))) - f(p - Vector((e, 0, 0)))), (f(p + Vector((0, e, 0))) - f(p - Vector((0, e, 0)))),
                (f(p + Vector((0, 0, e))) - f(p - Vector((0, 0, e))))))
    return g.normalized()


def fillet_column(curve, normal, f, R, t_in, t_out, n_arc, land=FILLET_LAND):
    """One column of a circular fillet of radius R between a strut skin line and a surface. curve(t) is the column's
    point on the strut skin, t rising away from the surface (inside it at t_in, outside at t_out); normal(t) its
    outward skin normal; f(p) negative inside the surface. The fillet lies in the plane of the column's tangent and
    normal, tangent to the skin, and meets the surface land[0] degrees into it, then dives in at land[1] for land[2]:
    one clean crossing line on a faceted neighbour. Returns ([the dive point, the landing, ..., the tangent point on
    the skin], the tangent point's t)."""
    g = lambda t: f(curve(t))
    a_, b_ = t_in, t_out
    for _ in range(40):
        m = (a_ + b_) / 2
        a_, b_ = (m, b_) if g(m) < 0 else (a_, m)
    ts = (a_ + b_) / 2
    Q = curve(ts)
    al, dv, run = (math.radians(land[0]), math.radians(land[1]), land[2])
    for _ in range(14):
        A = curve(ts)
        da = curve(ts + 0.005) - curve(ts - 0.005)
        speed = da.length / 0.01
        a = da.normalized()
        n = normal(ts)
        b = (n - a * a.dot(n)).normalized()
        N = surface_grad(f, Q)
        Np = Vector((N.dot(a), N.dot(b))).normalized()
        D = Vector((-Np.y, Np.x)) if Np.x > 0 else Vector((Np.y, -Np.x))  # along the surface, out onto the fillet side
        nb = Np * math.cos(al) + D * math.sin(al)
        q = Vector(((Q - A).dot(a), (Q - A).dot(b)))
        c = Vector(((R + nb.dot(q) - nb.y * R) / nb.x, R))
        E = c - nb * R
        E3 = A + a * E.x + b * E.y
        N3 = surface_grad(f, E3)
        lo, hi = -0.15, 0.15
        for _ in range(40):
            m = (lo + hi) / 2
            lo, hi = (m, hi) if f(E3 + N3 * m) < 0 else (lo, m)
        Q = E3 + N3 * ((lo + hi) / 2)
        ts += c.x / speed
    u0 = -nb
    a0 = math.atan2(u0.y, u0.x)
    sweep = (-0.5 * math.pi - a0 + math.pi) % (2 * math.pi) - math.pi
    to3 = lambda v: A + a * v.x + b * v.y
    arc = [to3(Vector((c.x + R * math.cos(a0 + sweep * i / (n_arc - 1)), c.y + R * math.sin(a0 + sweep * i / (n_arc - 1)))))
           for i in range(n_arc - 1)] + [curve(ts)]
    dive = to3(E + (D * math.cos(dv) - Np * math.sin(dv)) * run)
    return [dive] + arc, ts


def collar_flare(t, S):
    """Chord and thickness scale t along the axis from the cowl: the fillet's offset h off the strut's skin is the
    quarter circle from h = COLLAR_R at the cowl to 0, tangent to the strut, at t = COLLAR_R."""
    u = min(max(t / COLLAR_R, 0.0), 1.0)
    h = COLLAR_R - math.sqrt(max(0.0, COLLAR_R ** 2 - (COLLAR_R * (1 - u)) ** 2))
    return 1.0 + 2 * h / S.ch, 1.0 + 2 * h / S.th


def pod_g(v):
    """The node fairing's size along its length (v from 0 at its nose to 1 at its tail): an elliptic nose, then a
    long concave taper to a point."""
    if v < POD_VM:
        return math.sqrt(max(0.0, 1 - ((POD_VM - v) / POD_VM) ** 2))
    w = (v - POD_VM) / (1 - POD_VM)
    return max(0.0, 1 - w * w) ** 1.4


class Strut:
    """The strut line on one side and points of its sections. The right side's frame is the left's mirrored, so the
    two sides build face for face (the blockout's own right-hand frame has its thickness axis pointing down)."""

    def __init__(self, bl, side, section_n=SEC_N):
        self.bl, self.side = bl, side
        self.section_n = section_n
        ts = [(1 - math.cos(0.5 * math.pi * k / section_n)) ** 1.5 for k in range(section_n + 1)]
        self.sec = ([(ts[k], True) for k in range(section_n, 0, -1)] + [(0.0, True)]
                    + [(ts[k], False) for k in range(1, section_n + 1)])
        root, hub, node = bl.s6_strut_line(1)
        ax = (node - root).normalized()
        cd = (Vector((0, 1, 0)) - ax * ax.y).normalized()
        td = ax.cross(cd).normalized()
        m = lambda v: Vector((side * v.x, v.y, v.z))
        self.root, self.hub, self.node, self.ax, self.cd, self.td = (m(v) for v in (root, hub, node, ax, cd, td))
        self.length, self.d_hub = (node - root).length, (hub - root).length
        self.d_in, self.d_out = bl.s6_cowl_crossings(1, root, node)
        self.ch, self.th = bl.S6_STRUT["chord"], bl.S6_STRUT["thick"]

    def point(self, d, j, kc=1.0, kt=1.0):
        """Section point j at distance d along the line from the root, the chord scaled kc and the thickness kt."""
        c = self.ch * kc
        t, up = self.sec[j]
        le = self.root + self.ax * d - self.cd * (0.4 * c)
        return self.bl.airfoil_point(le, c, self.th * kt, self.cd, self.td, 0.0, t, up, te=STRUT_TE)

    def normal(self, d, j, kc=1.0, kt=1.0):
        """The outward skin normal at section point j (across the section, perpendicular to the axis). The blunt
        trailing edge's two points lean TE_NORMAL degrees off aft, up and down, so a fillet round the edge fans
        evenly from the upper skin through aft to the lower instead of leaving one wide flat strip."""
        M = len(self.sec)
        if j in (0, M - 1):
            a = math.radians(TE_NORMAL)
            return (self.cd * math.cos(a) + self.td * (math.sin(a) if self.sec[j][1] else -math.sin(a))).normalized()
        n = (self.point(d, (j + 1) % M, kc, kt) - self.point(d, (j - 1) % M, kc, kt)).cross(self.ax).normalized()
        return n if n.dot(self.point(d, j, kc, kt) - self.root - self.ax * d) > 0 else -n

    def ring(self, ds, kc=1.0, kt=1.0):
        ds = ds if isinstance(ds, (list, tuple)) else [ds] * len(self.sec)
        return [self.point(d, j, kc, kt) for j, d in enumerate(ds)]

    def crossing(self, j, kc, kt, sdf, d_from, d_to, step=0.02):
        """The distance from d_from toward d_to where section point j first changes side of sdf (negative inside)."""
        f = lambda d: sdf(self.point(d, j, kc, kt))
        n = max(2, int(abs(d_to - d_from) / step))
        a, fa = d_from, f(d_from)
        for i in range(1, n + 1):
            b = d_from + (d_to - d_from) * i / n
            fb = f(b)
            if (fa > 0) != (fb > 0):
                for _ in range(40):
                    m = (a + b) / 2
                    fm = f(m)
                    a, fa, b = (m, fm, b) if (fa > 0) == (fm > 0) else (a, fa, m)
                return (a + b) / 2
            a, fa = b, fb
        raise SystemExit(f"strut section point {j} never crosses its surface between {d_from:.2f} and {d_to:.2f}")


def body_sdf(bl, margin):
    """Horizontal distance outside the fuselage skin, less margin (negative inside)."""
    return lambda p: abs(p.x) - bl.side_x_s6(p.y + bl.Y0, p.z) + margin


def body_distance3(bl):
    """Metres outside the fuselage's analytic skin, about (negative inside), with a gradient along its normal."""
    def f(p):
        w, top, bot = bl.fus_profile(p.y + bl.Y0)
        zc, h = (top + bot) / 2, (top - bot) / 2
        return (math.hypot(p.x / w, (p.z - zc) / h) - 1) * min(w, h)
    return f


def pod_distance(bl, S):
    """About metres outside the node fairing (negative inside): its superellipse section under the wing's lower skin
    (pod_g along its length, the flange's thickness straight down from the skin), read over the plan beyond its
    ends too."""
    xc, s0, s1 = pod_frame(bl, S)
    side, ft = S.side, POD_FLANGE[1]

    def f(p):
        s = p.y + bl.Y0
        v = (s - s0) / (s1 - s0)
        g = pod_g(min(max(v, 0.0), 1.0))
        hw, dp = max(POD_W * g, 1e-3), max(POD_D * g ** 1.2, ft + 1e-3)
        under = bl.wing_lower(side, abs(p.x), s).z - p.z
        lat = abs(p.x - xc) / hw
        q = (lat ** 2.6 + (max(under - ft, 0.0) / (dp - ft)) ** 2.6) ** (1 / 2.6)
        return (q - 1) * min(hw, dp) + max(-v, v - 1, 0.0) * (s1 - s0)
    return f


def duct_r(bl, u):
    """The UltraFan bypass duct's outer wall radius over the nacelle's maximum, u of the cowl aft of the intake."""
    table = sorted((a, f) for f, a in bl.S6_UF_INNER)
    u = min(max(u, table[0][0]), table[-1][0])
    for (a0, f0), (a1, f1) in zip(table, table[1:]):
        if u <= a1:
            return f0 + (f1 - f0) * (u - a0) / (a1 - a0)
    return table[-1][1]


def cowl_sdf(bl, margin, duct=False):
    """Radial distance outside the nacelle's outer skin (or its duct wall), less margin (negative inside)."""
    _, _, x, front = bl.NACELLES[0]
    r, y0 = bl.S6_ENGINE["od"] / 2, bl.st(front)

    def sdf(p):
        u = (p.y - y0) / bl.NACELLE_LEN
        rad = math.hypot(abs(p.x) - x, p.z - bl.NACELLE_Z)
        return rad - r * (duct_r(bl, u) if duct else bl.uf_r(u)) + margin
    return sdf


def zones_tag(zones, struct_rings, SKIN, STRUCT):
    """face_tag for a strut loft: faces from ring r take zones[r]'s class, faces running inside a surface STRUCT."""
    def tag(r, k):
        if r in struct_rings:
            return STRUCT, 0
        return SKIN, zones[r]
    return tag


def build_inner(bl, p, S, slots, body_hull):
    """Root fairing on the body, the plain strut, the collar where it enters the cowl, then on through the cowl wall
    and the bypass duct to the node inside the core."""
    SKIN, STRUCT = slots[0], slots[1]
    M = len(S.sec)
    body, hull = body_sdf(bl, 0.0), body_distance3(bl)
    SP = Sponson(bl, S.side)

    def f(q):
        a = hull(q)
        if q.y + bl.Y0 < SP.nose - 0.3:
            return a + ROOT_BODY_IN
        b = SP.sdf(q.y + bl.Y0, abs(q.x), q.z)
        h = max(0.18 - abs(a - b), 0.0) / 0.18
        return min(a, b) - 0.045 * h * h + ROOT_BODY_IN
    k0 = 1.0 + ROOT_FLARE
    cols = []
    for j in range(M):
        tc = S.crossing(j, k0, k0, body, -1.6, 1.6)  # the flared skin's corner with the body
        k = lambda t, tc=tc: 1.0 + ROOT_FLARE * max(0.0, 1 - (t - tc) / ROOT_LEN) ** 2
        pts, ts = fillet_column(lambda t, j=j, k=k: S.point(t, j, k(t), k(t)), lambda t, j=j, k=k: S.normal(t, j, k(t), k(t)),
                                f, ROOT_R, tc - 0.3, tc + 0.6, ROOT_ARC, land=(3.0, 60.0, 0.035))
        pts = land_root_column(pts, body_hull, f, ROOT_FACET_IN)
        pts = pts[:2] + pts[4:]  # fund the triangle-crossing landing with two shallow interior arc rows
        cols.append(pts + [S.point(t, j, k(t), k(t)) for t in (ts + (tc + ROOT_LEN - ts) * u for u in ROOT_STRUT_F)])
    rings = [list(r) for r in zip(*cols)]
    zones = [ROOT_BOOT] * len(rings)
    zones[-1] = STRUT  # the plain strut from the root fairing to the collar
    foot = [c[1] for c in cols]
    cowl = cowl_sdf(bl, COWL_IN)
    kc0, kt0 = collar_flare(0.0, S)
    entry = [S.crossing(j, kc0, kt0, cowl, S.d_in + 1.5, S.d_in - 1.3) for j in range(M)]
    for t in reversed(COLLAR_T):
        rings.append(S.ring([d - t for d in entry], *collar_flare(t, S)))
        zones.append(COLLAR)
    first_hidden = len(rings) - 1
    rings.append(S.ring([d + 0.06 for d in entry], kc0, kt0))  # inside the cowl wall
    duct = cowl_sdf(bl, -0.01, duct=True)
    wall = [S.crossing(j, 1.0, 1.0, duct, S.d_in - 0.6, S.d_hub) for j in range(M)]
    rings.append(S.ring(wall))  # 1 cm inside the wall, at the duct's outer wall
    zones += [STRUCT, STRUT]
    for d in (S.d_hub - bl.S6_STRUT_JOIN, S.d_hub + 0.12):
        rings.append(S.ring(d))
        zones.append(STRUT)
    check_monotone(rings[ROOT_ARC - 2:], S, "strut_inner")  # the fillet turns back along the axis on the acute side
    hidden = {0, first_hidden, first_hidden + 1, len(rings) - 2}  # the dive, the cowl wall, the core
    grid = af.loft(p, rings, SKIN, STRUT, seams=(0, S.section_n, 2 * S.section_n), soft=(S.section_n,), ring_seams=(first_hidden,),
            cap_slot=(STRUCT, STRUCT), cap_cls=(0, 0), face_tag=zones_tag(zones, hidden, SKIN, STRUCT))
    conform_root_boundary(p, grid, body_hull, ROOT_FACET_IN)
    return {"root_foot": foot, "cowl_entry": entry}


def build_outer(bl, p, S, slots):
    """From the node inside the core out through the bypass duct and the cowl wall, the collar where it leaves the
    cowl, the plain strut, the blockout's taper to the wing (narrowed to fit_chord, thinned under the skin) and the
    node fairing round its foot."""
    SKIN, STRUCT = slots[0], slots[1]
    M = len(S.sec)
    rings, zones = [], []
    for d in (S.d_hub - 0.12, S.d_hub + bl.S6_STRUT_JOIN):
        rings.append(S.ring(d))
        zones.append(STRUT)
    duct = cowl_sdf(bl, -0.01, duct=True)
    wall = [S.crossing(j, 1.0, 1.0, duct, S.d_hub + 0.3, S.d_out + 0.4) for j in range(M)]
    rings.append(S.ring(wall))
    zones.append(STRUCT)
    cowl = cowl_sdf(bl, COWL_IN)
    kc0, kt0 = collar_flare(0.0, S)
    exit_ = [S.crossing(j, kc0, kt0, cowl, S.d_out - 1.2, S.d_out + 1.3) for j in range(M)]
    rings.append(S.ring([d - 0.06 for d in exit_], kc0, kt0))
    zones.append(STRUCT)
    first_shown = len(rings)
    for t in COLLAR_T:
        rings.append(S.ring([d + t for d in exit_], *collar_flare(t, S)))
        zones.append(COLLAR)
    zones[-1] = STRUT
    for d in OUTER_MID:
        rings.append(S.ring(d))
        zones.append(STRUT)
    fit, thin = taper(bl, S)
    f = pod_distance(bl, S)
    radius, arc = POD_COLLAR_R, POD_COLLAR_ARC
    cols = []
    for j in range(M):
        curve = lambda t: S.point(S.length - t, j, fit(t), thin(t))
        normal = lambda t: S.normal(S.length - t, j, fit(t), thin(t))
        lo, hi = 0.0, TAPER_START
        for _ in range(35):
            t = (lo + hi) / 2
            lo, hi = (t, hi) if f(curve(t) + normal(t) * radius) < 0 else (lo, t)
        entry = (lo + hi) / 2 - POD_COLLAR_IN
        plain = [curve(entry + radius + (TAPER_START - entry - radius) * u) for u in TAPER_U[:-1]]
        collar = []
        for k in range(arc, -1, -1):
            a = math.pi * k / (2 * arc)
            t = entry + radius * (1 - math.cos(a))
            q = curve(t) + normal(t) * (radius * (1 - math.sin(a)))
            collar.append(q)
        cols.append(plain + collar)
    rings += [list(r) for r in zip(*cols)]
    # The planar closure is inside the fixed wing, below the stages' 11 mm gap. It cannot leave a thin blade at the pod.
    cap_x = max(q.x for q in rings[-1])
    z0, z1 = min(q.z for q in rings[-1]), max(q.z for q in rings[-1])
    rings[-1] = [Vector((cap_x, q.y, bl.wing_lower(S.side, abs(cap_x), q.y + bl.Y0).z
                        + 0.002 + 0.005 * (q.z - z0) / (z1 - z0))) for q in rings[-1]]
    zones += [STRUT] * (len(TAPER_U) - 1) + [NODE_POD] * (arc + 1)
    check_monotone(rings[:len(rings) - arc], S, "strut_outer")
    # the core, the cowl wall (the duct between shows) and the fillet's dive into the node fairing
    hidden = {0, first_shown - 2, first_shown - 1, len(rings) - 2}
    af.loft(p, rings, SKIN, STRUT, seams=(0, S.section_n, 2 * S.section_n), soft=(S.section_n,), ring_seams=(first_shown,),
            end=sum(rings[-1], Vector()) / M, cap_slot=(STRUCT, STRUCT), cap_cls=(0, 0),
            face_tag=zones_tag(zones, hidden, SKIN, STRUCT))
    bmesh.ops.triangulate(p.bm, faces=p.bm.faces[:], quad_method="BEAUTY", ngon_method="EAR_CLIP")
    node_pod(bl, p, S, slots)
    p.bm.normal_update()
    return {"cowl_exit": exit_}


def check_monotone(rings, S, name):
    """Every section point must move along the axis ring after ring, or the loft folds."""
    for j in range(len(rings[0])):
        d = [(r[j] - S.root).dot(S.ax) for r in rings]
        bad = [i for i in range(len(d) - 1) if d[i + 1] <= d[i]]
        if bad:
            raise SystemExit(f"{name}: section point {j} folds back between rings {bad} ({[round(x, 3) for x in d]})")


def taper(bl, S):
    """The blockout's taper toward the node as chord and thickness scales of t, metres short of the node: narrowed to
    fit_chord over TAPER_START, thinned to pass 6 cm under the wing's lower skin (the floor eased in, so the fillet
    onto the node fairing reads a smooth skin)."""
    ch, th = S.ch, S.th
    fit = lambda t: 1.0 - (1 - bl.S6_STRUT["fit_chord"] / ch) * max(0.0, 1 - t / TAPER_START)

    def thin(t):
        q = S.root + S.ax * (S.length - t)
        h = min(bl.wing_lower(S.side, abs(v.x), v.y + bl.Y0).z - v.z
                for v in (q - 0.4 * ch * fit(t) * S.cd, q, q + 0.6 * ch * fit(t) * S.cd))
        a, b = 0.03, 2 * (h - 0.06)
        return min(1.0, 0.5 * (a + b + math.sqrt((a - b) ** 2 + 0.02 ** 2)) / th)
    return fit, thin


def pod_frame(bl, S):
    """The node fairing's centre x and its first and last stations."""
    return S.node.x + S.side * POD_DX, S.node.y + bl.Y0 - POD_FWD, S.node.y + bl.Y0 + POD_AFT


def node_pod(bl, p, S, slots):
    """The node fairing: a pod aligned with the flow on the wing's lower skin round the strut's foot, its top pressed
    into the skin, a thin attachment flange round its base on the skin, ending in a point ahead of the aileron cove."""
    SKIN = slots[0]
    side = S.side
    xc, s0, s1 = pod_frame(bl, S)
    skin_in = lambda x, s: bl.wing_lower(side, abs(x), s, inset=FOOT_INSET).z
    skin = lambda x, s: bl.wing_lower(side, abs(x), s).z
    fw, ft = POD_FLANGE
    rings = []
    for i in range(1, POD_RINGS + 1):
        v = 0.5 * (1 - math.cos(math.pi * i / (POD_RINGS + 1)))
        s = s0 + (s1 - s0) * v
        g = pod_g(v)
        fade = min((s1 - s) / 0.15, 1.0)
        fade = fade * fade * (3 - 2 * fade)
        hw, dp, fl = POD_W * g, POD_D * g ** 1.2, fw * g ** 0.5 * fade
        y = bl.st(s)
        arc = []
        for k in range(1, POD_ARC - 1):  # outboard side, down round the bottom, to the inboard side
            a = math.pi / 2 - math.pi * k / (POD_ARC - 1)
            sx = math.copysign(abs(math.sin(a)) ** (2 / 2.6), math.sin(a))
            cz = abs(math.cos(a)) ** (2 / 2.6)
            x = xc + side * hw * sx
            arc.append(Vector((x, y, skin(x, s) - ft - (dp - ft) * cz)))
        lip = lambda e: [Vector((xc + e * side * (hw + fl), y, skin_in(xc + e * side * (hw + fl), s))),
                         Vector((xc + e * side * (hw + fl), y, skin(xc + e * side * (hw + fl), s) - 0.6 * ft)),
                         Vector((xc + e * side * (hw + fl / 3), y, skin(xc + e * side * (hw + fl / 3), s) - ft))]
        ring = lip(1) + arc + lip(-1)[::-1]
        for k in (1, 2, 3):  # back across the top, inside the skin
            x = xc + side * hw * (-1 + 0.5 * k)
            ring.append(Vector((x, y, skin_in(x, s))))
        rings.append(ring)
    nose = Vector((xc, bl.st(s0), skin_in(xc, s0)))
    tail = Vector((xc, bl.st(s1), skin_in(xc, s1)))
    af.loft(p, rings, SKIN, NODE_POD, seams=(POD_ARC + 2,), start=nose, end=tail)


# ---------- sponson ----------
# Smooth-union radius between pod and body (the fillets) above and below, scaled with the pod's size: the blockout's
# fillets run about 0.45 m a side (S61_SPONSON "fillet"). The lower one's radius by station, eased between the
# entries: wide ahead of the gear well, where nothing hangs on the belly; under the well no wider than keeps the main
# door's hinge line on the skin; beside the aft bay door (23.6 to 32.6) landing outboard of its hinge at 141 deg,
# widening again as the pod's tail rises up the side.
SPONSON_K_HI = 0.8
SPONSON_K_LO = ((22.2, 0.45), (23.0, 0.38), (28.0, 0.38), (29.0, 0.4), (30.0, 0.45), (31.0, 0.5))
# The body in the union sits this far inside the hull: enough to clear the 64-vertex
# hull's facets, so the fillet shows down to where it crosses the hull (on a column of its own, junctions()).
SPONSON_BODY_IN = 0.015
SPONSON_K_Z = (2.3, 3.4)  # heights over which the radius grows from the lower fillet's to the upper's
SPONSON_END_K = 0.6  # the radius shrinks with the pod toward its ends, to no less than this fraction
# Over the nose and tail the pod's distance is three-dimensional: the nearest of its sections this far either side,
# sampled this finely along the body.
POD_WINDOW, POD_STEP = 0.5, 0.025
# The tail's fillet ends under the skin by the tail cone's joint, 10 cm behind the pod's tail (a part may not cross
# it): its radius at most the first plus the second times the metres short of the joint. The nose's likewise from
# SPONSON_LEAD's first ring, which stays clear of the strut root fillet's footprint ending just ahead of it.
SPONSON_JOINT_K = (0.06, 1.6)
# The pod's inboard side is cut off by a plane rising from the main door's hinge line (x 2.05), leaning inboard by
# CHAMFER_LEAN degrees from upright, so the sponson stays clear of the aft bay door, whose hinge runs at 141 deg
# round the body. Upright, the cut stands furthest from that hinge, which leaves the lower fillet the widest radius
# that still lands outboard of it.
CHAMFER = (2.04, 1.40)
CHAMFER_LEAN = 0.0
# The ring runs from the top fillet (its end under the wing fairing, which reaches down to z 4.6 inside the body)
PHI = (16.0, 222.0)  # ray angles from the section's origin, degrees from up toward outboard: top fillet to the belly
PHI_N = 64
# Columns from PHI[0] to the upper junction with the hull, and from the lower junction to PHI[1]: one column runs
# on each junction line at every station, so the line follows the grid instead of hopping between columns (a
# saw-tooth along the pod's tail, where the junction runs diagonally across fixed-angle columns).
JUNCTION_COLS = (2, 2)
FILLET_CLUSTER = 0.6  # columns at the junctions this much closer together than the even spacing (0 even)
# Those columns sink under the skin, metres from the junction's: the union runs only 1.5 cm under it there, where
# the aft bay doors' flat panels dip into the belly's curve.
INSIDE_SINK = (0.05, 0.2)
RAY_MIN_X = 0.5
# Beside the aft bay (build_centurion aft_bay_box: a cavity between its doors' hinge lines), the columns past the lower
# junction stop on the union's body skin (SPONSON_BODY_IN under the hull) BAY_WALL_GAP outboard of the bay's wall
# instead of running on inboard, the first sunk no further (its face runs on from the junction close along the skin,
# as elsewhere), the last BAY_SINK[1], so the pod's hidden closure stays in the body's solid side, out of the cavity;
# over the bay's stations and BAY_REACH beyond, so no face between two rings reaches into it.
BAY_WALL_GAP, BAY_REACH, BAY_SINK = 0.012, 0.6, (0.0, 0.2)
CLOSE_PHI = (300.0,)  # the hidden closure runs through the body's solid side
# Rings ahead of the well, as fractions of the nose (S61_SPONSON nose to full), and aft of it, as fractions of the
# run from the well's end to the tail: closer where the pod turns into the body.
SPONSON_NOSE_F = (0.0, 0.008, 0.02, 0.04, 0.07, 0.11, 0.16, 0.23, 0.32, 0.44, 0.59, 0.77)
SPONSON_TAIL_F = (0.12, 0.26, 0.40, 0.54, 0.66, 0.76, 0.84, 0.90, 0.945, 0.975, 1.0)
# Rings ahead of the nose and behind the tail (metres), where the end fillets run out onto the body: the outermost
# lies wholly under the skin. The lead rings sink SPONSON_LEAD_SINK further, so the nose meets the hull along its
# junction columns: the nose fillet's run-out ahead of it stood up to 24 mm proud, grazing the hull's facets.
SPONSON_LEAD = (0.17, 0.07)
SPONSON_LEAD_SINK = 0.025
SPONSON_TRAIL = (0.08,)
WELL_S = (23.1, 27.9)  # the main gear well's stations: the door's, 4.8 m centred on the bogie at 25.5
WELL_ROWS = 4
WELL_OUT = 0.82  # the well's outboard edge: this fraction of the pod's half width outboard of its centre
WELL_CEILING = 2.95  # the well's roof, and 8 cm under the body's skin where that is lower
WELL_WALL_IN = 0.12  # the outboard wall leans this far inboard from its edge to the roof
DOOR_X = (2.05, 2.66)  # the main door: from its hinge line (the blockout's) to its free edge, closed
DOOR_GAP, DOOR_T = 0.012, 0.045
# The leg door's free-edge corners, cut back (metres along the station, across): the door hangs in the rest pose with
# that edge lowest, where square corners make it read as a shelf (m4/gear.py). The main door's free edge runs out over
# the same corners in tabs, so the closed doors leave no triangle of the well open between them.
LEG_DOOR_CHAMFER = (0.3, 0.14)
# Owner: "it should be a bump on the sponson. it should flow over it so that it's aerodynamically sound. and the hinge
# should be inside the plane". The main gear's hinge axis runs inside the pod (bl.MAIN_PIVOT_X), and the skin swells
# over the leg's top into a body of revolution about that axis: radius r over the barrel, metres either side of the
# hinge's station, closing to end_r (inside the pod) along a rounded nose ahead and a longer taper aft, smooth-unioned
# into the pod over k.
HINGE_BUMP = {"r": 0.22, "barrel": 0.75, "fore": 0.9, "aft": 1.5, "end_r": 0.04, "k": 0.03}
# The leg's slot: over half_len either side of the hinge's station the skin is cut from the bump's band (degrees round
# the hinge from level outboard, where the bump is its round section to 3 mm) down to the well, and the leg's sleeve
# (m4/gear.py), a body of revolution about the hinge just under the bump, shows in the band; the leg door closes the
# rest. Swung down, the door's edge on the band's lower line lands the leg's fold (gear.MAIN_RETRACT_DEG, 120 deg)
# round, so the band spans more than that, or the door would come to rest through the bump: with the hinge 0.10 m
# inside the pod at 2.1 m, r 0.22 and k 0.03 the skin is the round section to 3 mm from -72 to 56.5 deg, the bump
# 12 cm proud. Over the bump one column runs on the band's top line, and the slot opens between it and the well's
# outboard edge (cut_leg_slot).
LEG_SLOT = {"band_deg": (-71.0, 56.0), "half_len": 0.6}
# The slot's top wall runs from the band's top round the leg's sleeve, through these angles round the hinge at in
# metres under the skin (no further out than reach), then to the well's roof: the sleeve's faces that show with the
# gear up sit in the open well at rest, where the composite's bury pass leaves them on the skin, not sealed in the bump.
SLOT_WALL = {"deg": (60.0, 68.0, 78.0, 90.0, 102.0, 114.0), "in": 0.003, "reach": 0.235}
# Columns over the bump: where the bump stands, the columns from the one nearest BUMP_PHI to the opening's inboard
# edge spread by arc length, BUMP_ROUND times as dense on its round section, plus BUMP_TURN metres per radian the skin
# turns, so the round section and its fillets get the columns the flank gives up (the bump spans some 17 deg of ray
# angle, 5 of the even columns, and faceted at 28 deg its facets sagged past the sleeve under it).
BUMP_PHI, BUMP_ROUND, BUMP_TURN = 75.0, 10.0, 0.15
# The formation strip on the aft outboard flank, (station, phi) corners: 0.08 m wide, about 0.6 m long, slanted as the
# nose's and the aft body's.
FORMATION = ((28.62, 74.0), (28.70, 74.0), (28.93, 106.0), (28.85, 106.0))


def eased(table, s):
    """The (station, value) table at s: smoothstep between entries, held past its ends."""
    if s <= table[0][0]:
        return table[0][1]
    for (s0, a), (s1, b) in zip(table, table[1:]):
        if s <= s1:
            v = (s - s0) / (s1 - s0)
            return a + (b - a) * v * v * (3 - 2 * v)
    return table[-1][1]


class Sponson:
    """The sponson's skin as a surface point(s, phi): the pod smooth-unioned with the body in the section at station
    s, read along a ray from an origin inside both at angle phi (degrees from up toward outboard). Duck-typed like
    surface.Fuselage, so surface_patch and outline_frame work on it."""

    def __init__(self, bl, side):
        self.bl, self.side = bl, side
        self.sp = sp = bl.S61_SPONSON
        self.nose, self.tail, self.hh = sp["nose"], sp["tail"], sp["half_h"]
        self.cache = {}
        self.joint = next(rs for n, rs, _, _ in bl.FUSELAGE if n == "fuselage_R")[-1]  # the tail cone's joint
        lean = math.radians(CHAMFER_LEAN)
        self.cut, self.cut_n = CHAMFER, (-math.cos(lean), -math.sin(lean))  # the cut-off side: inboard (and down)
        self.bay = bl.aft_bay_box(BAY_WALL_GAP) if bl.AFT_BAY_ROOF else None
        self.hinge = (bl.MAIN_PIVOT_X, bl.MAIN_PIVOT_Z, bl.MAIN_GEAR_STATION)  # the main gear's, left side (x, z, station)

    def bump_r(self, s):
        """The hinge bump's radius about the hinge axis at station s, 0 off its ends."""
        b, u = HINGE_BUMP, s - self.hinge[2]
        t = (abs(u) - b["barrel"]) / (b["fore"] if u < 0 else b["aft"])
        if t >= 1.0:
            return 0.0
        return b["r"] if t <= 0.0 else b["end_r"] + (b["r"] - b["end_r"]) * (1 - t * t) ** 0.75

    def hinge_phi(self, s, deg):
        """The ray angle of the skin point deg round the hinge from level outboard (up positive) at station s."""
        hx, hz = self.hinge[:2]
        a = math.radians(deg)
        dx, dz = math.cos(a), math.sin(a)
        lo, hi = 0.0, 0.6
        for _ in range(36):
            m = (lo + hi) / 2
            lo, hi = (m, hi) if self.sdf(s, hx + dx * m, hz + dz * m) < 0 else (lo, m)
        o = self.frame(s)[4]
        return math.degrees(math.atan2(hx + dx * lo - o[0], hz + dz * lo - o[1]))

    def in_bay(self, s):
        """Station s is beside the aft bay (BAY_REACH either side of it included)."""
        return self.bay is not None and self.bay[0].y - BAY_REACH <= self.bl.st(s) <= self.bay[1].y + BAY_REACH

    def body(self, s):
        w, top, bot = self.bl.fus_profile(s)
        return w, (top + bot) / 2, (top - bot) / 2

    def frame(self, s):
        """Pod centre (x, z), its outboard half width and half height, the ray origin, its size (1 over the full
        section), the body's section and the inboard half width at station s (left side, x outboard)."""
        if s in self.cache:
            return self.cache[s]
        px, pz, a, a_in, b = self.bl.sponson_section(min(max(s, self.nose), self.tail))
        f = b / self.hh
        w, zc, h = self.body(s)
        dx, dz = -px, zc - pz
        L = math.hypot(dx, dz)
        ix, iz = dx / L, dz / L  # toward the body's centre
        a, a_in, b = max(a, 1e-3), max(a_in, 1e-3), max(b, 1e-3)
        # inside the pod and the body's skin less SPONSON_BODY_IN, also where the pod has shrunk onto the skin at its ends
        o = (px + ix * (0.45 * f + 0.25), pz + iz * (0.45 * f + 0.25))
        out = (px, pz, a, b, o, f, (w, zc, h), a_in)
        self.cache[s] = out
        return out

    def pod_section_d(self, s, x, z):
        """Metres outside the pod's own section at station s (nose to tail), the chamfer cut off."""
        px, pz, a, b, o, f, _, a_in = self.frame(s)
        a = a if x > px else a_in
        ex, ez = (x - px) / a, (z - pz) / b
        q = math.hypot(ex, ez)
        g = math.hypot(ex / a, ez / b)
        dp = (q - 1) * q / g if g > 1e-9 else -min(a, b)
        return max(dp, (x - self.cut[0]) * self.cut_n[0] + (z - self.cut[1]) * self.cut_n[1])

    def pod_d(self, s, x, z):
        """Metres outside the pod in three dimensions: over its nose and tail, where the section changes fast along
        the body, the nearest of the sections within POD_WINDOW, so the fillet also turns the pod's ends into the
        body (a section-by-section union leaves the nose and the tail standing on the skin at a crease)."""
        sp = self.sp
        inside = self.pod_section_d(s, x, z) if self.nose <= s <= self.tail else None
        if sp["full"] + POD_WINDOW <= s <= sp["aft"] - POD_WINDOW or (inside is not None and inside <= 0):
            return inside
        best = 1e9 if inside is None else inside
        lo, hi = max(self.nose, s - POD_WINDOW), min(self.tail, s + POD_WINDOW)
        slices = [i * POD_STEP for i in range(math.ceil(lo / POD_STEP), math.floor(hi / POD_STEP) + 1)]
        for s2 in slices + [x_ for x_ in (self.nose, self.tail) if lo <= x_ <= hi]:
            best = min(best, math.hypot(s - s2, max(self.pod_section_d(s2, x, z), 0.0)))
        return best

    def sdf(self, s, x, z):
        """Metres outside the skin: the pod and body's union with the hinge bump smooth-unioned on."""
        d = self.sdf_plain(s, x, z)
        r = self.bump_r(s)
        if r <= 0.0:
            return d
        k = HINGE_BUMP["k"]
        db = math.hypot(x - self.hinge[0], z - self.hinge[1]) - r
        hk = max(k - abs(d - db), 0.0) / k
        return min(d, db) - hk * hk * k / 4

    def sdf_plain(self, s, x, z):
        """Metres outside the pod and body's union, without the hinge bump."""
        f, (w, zc, h) = self.frame(s)[5:7]
        qb = math.hypot(x / w, (z - zc) / h)
        db = (qb - 1) * min(w, h) + SPONSON_BODY_IN
        dp = self.pod_d(s, x, z)
        lo, hi = SPONSON_K_Z
        u = min(max((z - lo) / (hi - lo), 0.0), 1.0)
        k_lo = eased(SPONSON_K_LO, s)
        k = max(f, SPONSON_END_K) * (k_lo + (SPONSON_K_HI - k_lo) * u * u * (3 - 2 * u))
        k = min(k, SPONSON_JOINT_K[0] + SPONSON_JOINT_K[1] * max(min(self.joint - s, s - self.nose + SPONSON_LEAD[0]), 0.0))
        if k <= 1e-6:
            return min(db, dp)
        hk = max(k - abs(db - dp), 0.0) / k
        return min(db, dp) - hk * hk * k / 4

    def local(self, s, phi):
        """(x, z) on the left side where the ray at phi leaves the union."""
        o = self.frame(s)[4]
        ph = math.radians(phi)
        dx, dz = math.sin(ph), math.cos(ph)
        f = lambda t: self.sdf(s, o[0] + dx * t, o[1] + dz * t)
        a, fa = 0.0, f(0.0)
        if fa >= 0:
            raise SystemExit(f"sponson ray origin outside the skin at station {s:.2f}")
        t = 0.03
        while True:
            fb = f(t)
            if fb > 0:
                break
            a, t = t, t + 0.03
            if t > 6.0:
                raise SystemExit(f"sponson ray at {phi:.1f} deg never leaves the skin at station {s:.2f}")
        b = t
        for _ in range(36):
            m = (a + b) / 2
            if f(m) > 0:
                b = m
            else:
                a = m
        r = (a + b) / 2
        if dx < 0:  # a ray running inboard stops short of the centreline, inside the body, where it stays hidden
            r = min(r, (o[0] - RAY_MIN_X) / -dx)
        x, z = o[0] + dx * r, o[1] + dz * r
        if dx < 0 and self.in_bay(s) and x < self.bay[1].x:  # beside the aft bay: on the union's body skin at its wall
            w, zc, h = self.body(s)
            q = 1 - SPONSON_BODY_IN / min(w, h)
            x = self.bay[1].x
            z = zc - h * math.sqrt(max(q * q - (x / w) ** 2, 0.0))
        return x, z

    def point(self, s, phi, off=0.0):
        x, z = self.local(s, phi)
        p = Vector((self.side * x, self.bl.st(s), z))
        return p + self.normal(s, phi) * off if off else p

    def normal(self, s, phi):
        a = self.point(s + 0.01, phi) - self.point(s - 0.01, phi)
        b = self.point(s, phi + 0.2) - self.point(s, phi - 0.2)
        n = a.cross(b).normalized()
        o = self.frame(s)[4]
        c = Vector((self.side * o[0], self.bl.st(s), o[1]))
        return n if n.dot(self.point(s, phi) - c) > 0 else -n

    def inside_point(self, s, phi, r=0.1):
        o = self.frame(s)[4]
        ph = math.radians(phi)
        return Vector((self.side * (o[0] + math.sin(ph) * r), self.bl.st(s), o[1] + math.cos(ph) * r))

    def phi_for_x(self, s, x, lo, hi):
        """The phi in [lo, hi] where the skin reaches half-width x (x falling as phi grows there)."""
        for _ in range(40):
            m = (lo + hi) / 2
            if self.local(s, m)[0] > x:
                lo = m
            else:
                hi = m
        return (lo + hi) / 2

    def well_edges(self, s):
        """The well's inboard (hinge line) and outboard edges at station s, as phi."""
        px, pz, a, b, o, k = self.frame(s)[:6]
        out = self.phi_for_x(s, px + WELL_OUT * a, 95.0, 178.0)
        inb = self.phi_for_x(s, DOOR_X[0], 160.0, 215.0)
        return out, inb


def junctions(SP, stations):
    """Per station, the ray angles where the skin crosses the hull above and below the pod (the junction lines);
    where the pod is still under the skin, its nearest station's."""
    def outside(s, phi):
        x, z = SP.local(s, phi)
        w, zc, h = SP.body(s)
        return math.hypot(x / w, (z - zc) / h) > 1.0

    def edge(s, a, b):
        oa = outside(s, a)
        for _ in range(30):
            m = (a + b) / 2
            a, b = (m, b) if outside(s, m) == oa else (a, m)
        return (a + b) / 2
    found = []
    for s in stations:
        grid = [PHI[0] + (PHI[1] - PHI[0]) * k / 103 for k in range(104)]
        flags = [outside(s, f) for f in grid]
        ins = [k for k in range(103) if flags[k] != flags[k + 1]]
        found.append((edge(s, grid[ins[0]], grid[ins[0] + 1]), edge(s, grid[ins[-1]], grid[ins[-1] + 1]))
                     if len(ins) >= 2 else None)
    known = [i for i, f in enumerate(found) if f]
    return [f or found[min(known, key=lambda j: abs(j - i))] for i, f in enumerate(found)]


def column_phis(edges):
    """PHI_N column angles with one on each junction line (JUNCTION_COLS columns beyond each), closer together
    toward the junctions (FILLET_CLUSTER), where the fillets turn the skin into the hull's."""
    (a, b), (n1, n3) = edges, JUNCTION_COLS
    n2 = PHI_N - n1 - n3
    g = lambda t: t - FILLET_CLUSTER * math.sin(2 * math.pi * t) / (2 * math.pi)
    return ([PHI[0] + (a - PHI[0]) * k / n1 for k in range(n1)] + [a + (b - a) * g(k / (n2 - 1)) for k in range(n2)]
            + [b + (PHI[1] - b) * k / n3 for k in range(1, n3 + 1)])


def sponson_stations(SP):
    sp = SP.sp
    well = [WELL_S[0] + (WELL_S[1] - WELL_S[0]) * i / WELL_ROWS for i in range(WELL_ROWS + 1)]
    # over the hinge bump: the slot's ends, the barrel's ends, and the nose and tail at fractions of their run
    h, b = SP.hinge[2], HINGE_BUMP
    slot = [h - LEG_SLOT["half_len"], h + LEG_SLOT["half_len"]]
    well = [s for s in well if min(abs(s - x) for x in slot) > 0.06] + slot
    bump = [h - b["barrel"] - b["fore"] * t for t in (0.0, 0.5, 0.75, 0.9)]
    bump += [h + b["barrel"] + b["aft"] * t for t in (0.0, 0.3, 0.6, 0.85)]
    for s in sorted(bump):
        if min(abs(s - w) for w in well) > 0.06:
            well.append(s)
    return ([sp["nose"] - d for d in SPONSON_LEAD] + [sp["nose"] + (sp["full"] - sp["nose"]) * f for f in SPONSON_NOSE_F]
            + sorted(well) + [WELL_S[1] + (sp["tail"] - WELL_S[1]) * f for f in SPONSON_TAIL_F] + [sp["tail"] + d for d in SPONSON_TRAIL])


def spread_columns(SP, s, ph, k0, k1, samples=160):
    """Columns k0..k1 of a ring respread between their (kept) end angles by arc length (BUMP_ROUND times as dense on
    the hinge bump's round section) plus BUMP_TURN metres per radian the skin turns."""
    fs = [ph[k0] + (ph[k1] - ph[k0]) * i / samples for i in range(samples + 1)]
    pts = [SP.local(s, f) for f in fs]
    heading = [math.atan2(b[1] - a[1], b[0] - a[0]) for a, b in zip(pts, pts[1:])]
    turn = [0.0] + [abs((h1 - h0 + math.pi) % (2 * math.pi) - math.pi) for h0, h1 in zip(heading, heading[1:])] + [0.0]
    r = SP.bump_r(s)
    cum = [0.0]
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        mid = ((a[0] + b[0]) / 2 - SP.hinge[0], (a[1] + b[1]) / 2 - SP.hinge[1])
        dense = BUMP_ROUND if r > 0.0 and abs(math.hypot(*mid) - r) < 0.005 else 1.0
        cum.append(cum[-1] + math.dist(a, b) * dense + BUMP_TURN * (turn[i] + turn[i + 1]) / 2)
    out, i = list(ph), 0
    for k in range(k0 + 1, k1):
        target = cum[-1] * (k - k0) / (k1 - k0)
        while cum[i + 1] < target:
            i += 1
        out[k] = fs[i] + (fs[i + 1] - fs[i]) * (target - cum[i]) / (cum[i + 1] - cum[i])
    return out


def build_sponson(bl, p, side, slots):
    SKIN, STRUCT, GLASS, MECH, RED, WHITE, FORMATION_L = slots
    SP = Sponson(bl, side)
    stations = sponson_stations(SP)
    edges = junctions(SP, stations)
    phis = column_phis(edges[min(range(len(stations)), key=lambda i: abs(stations[i] - 25.5))])
    # the well's edge columns: the columns nearest its edges at the bogie
    out_mid, in_mid = SP.well_edges(25.5)
    k_out = min(range(PHI_N), key=lambda k: abs(phis[k] - out_mid))
    k_in = min(range(PHI_N), key=lambda k: abs(phis[k] - in_mid))
    k_bump = min(range(PHI_N), key=lambda k: abs(phis[k] - BUMP_PHI))
    r_well = [i for i, s in enumerate(stations) if WELL_S[0] - 1e-6 <= s <= WELL_S[1] + 1e-6]
    hs, top = SP.hinge[2], LEG_SLOT["band_deg"][1]

    def well_phis(i, s, k_top=None):
        ph = column_phis(edges[i])
        a, b = SP.well_edges(s)
        for k in range(k_out, k_in + 1):
            ph[k] = a + (b - a) * (k - k_out) / (k_in - k_out)
        if SP.bump_r(s) > 0.0:
            if k_top is None:
                return spread_columns(SP, s, ph, k_bump, k_out)
            ph[k_top] = SP.hinge_phi(s, top)
            ph = spread_columns(SP, s, spread_columns(SP, s, ph, k_bump, k_top), k_top, k_out)
        return ph
    # the column on the leg slot's top line: where the spread puts the band's top at the hinge, pinned there throughout
    i_h = min(range(len(stations)), key=lambda i: abs(stations[i] - hs))
    ph_h, phi_top = well_phis(i_h, hs), SP.hinge_phi(hs, top)
    k_top = min(range(k_bump + 1, k_out), key=lambda k: abs(ph_h[k] - phi_top))
    rings, ring_phis = [], []
    for i, s in enumerate(stations):
        ph = well_phis(i, s, k_top) if i in r_well else column_phis(edges[i])
        ring_phis.append(ph)
        o = SP.frame(s)[4]
        o3 = Vector((side * o[0], bl.st(s), o[1]))
        n1, n3 = JUNCTION_COLS
        low = BAY_SINK if SP.in_bay(s) else INSIDE_SINK
        sink = [INSIDE_SINK[n1 - 1 - k] if k < n1 else low[k - (PHI_N - 1 - n3) - 1] if k > PHI_N - 1 - n3 else 0.0
                for k in range(PHI_N)]
        pts = [SP.point(s, f) for f in ph]
        lead = SPONSON_LEAD_SINK if s < SP.nose else 0.0
        rings.append([p_ + (o3 - p_).normalized() * (d + lead) for p_, d in zip(pts, sink)] + [SP.inside_point(s, f) for f in CLOSE_PHI])
    g = sf.Grid(p.bm, rings)
    p.tag(g.faces(), SKIN, SPONSON)
    M = PHI_N + len(CLOSE_PHI)
    p.tag([g.F[r, k] for r in range(len(rings) - 1) for k in range(PHI_N - 1, M)], STRUCT)  # the closure, inside
    p.tag(sf.cap(p.bm, g.V[0][::-1]), STRUCT)
    p.tag(sf.cap(p.bm, g.V[-1]), STRUCT)
    g.seam_column(PHI_N - 1)
    g.seam_column(0)
    g.seam_column(JUNCTION_COLS[0])
    g.seam_column(PHI_N - JUNCTION_COLS[1] - 1)
    g.stations = stations

    def roof(q, r, k):
        s = stations[r]
        t = (k - k_out) / (k_in - k_out)
        x_out = abs(g.V[r][k_out].co.x) - WELL_WALL_IN
        x = x_out + (DOOR_X[0] - x_out) * t
        z = min(WELL_CEILING, bl.fus_bottom_z(s, x) - 0.08)
        return Vector((side * x, q.y, z))

    _, walls = sf.recess(p, g, r_well[0], r_well[-1], k_out, k_in, roof, SKIN, INTERIOR)
    slot = [i for i, s in enumerate(stations) if abs(s - hs) <= LEG_SLOT["half_len"] + 1e-6]
    cut_leg_slot(p, g, SP, slot[0], slot[-1], k_top, k_out, walls, SKIN)
    well_structure(bl, p, side, slots)
    sf.surface_patch(p, SP, list(FORMATION), 1, 6, 0.008, -0.012, FORMATION_L)
    return SP, {"stations": stations, "k_out": k_out, "k_in": k_in}


def cut_leg_slot(p, g, SP, r0, r1, k_top, k_out, walls, slot):
    """Open the leg's slot over rings r0..r1, from column k_top (the band's top line) to k_out (the well's outboard
    edge): the skin there comes away, with the well's outboard wall beside it (sf.recess's walls on k_out), and a wall
    from the slot's top line round the sleeve (SLOT_WALL) and a flat end wall at each end close it onto the well roof's
    outboard edge, so the part stays one closed shell."""
    bm, V = p.bm, g.V
    hx, hz = SP.hinge[:2]
    roof = {}
    for f in list(walls):
        vs = list(f.verts)
        for r in range(r0, r1):
            if vs[0] is V[r][k_out] and vs[1] is V[r + 1][k_out]:
                roof[r], roof[r + 1] = vs[3], vs[2]
                bm.faces.remove(f)
    for r in range(r0, r1):
        for k in range(k_top, k_out):
            bm.faces.remove(g.F.pop((r, k)))
    for r in range(r0 + 1, r1):
        for k in range(k_top + 1, k_out + 1):
            bm.verts.remove(V[r][k])
    arc = {}
    for r in range(r0, r1 + 1):
        s, y = g.stations[r], V[r][k_top].co.y
        arc[r] = []
        for deg in SLOT_WALL["deg"]:
            a = math.radians(deg)
            lo, hi = 0.0, 0.6
            for _ in range(30):
                m = (lo + hi) / 2
                lo, hi = (m, hi) if SP.sdf(s, hx + math.cos(a) * m, hz + math.sin(a) * m) < 0 else (lo, m)
            d = min(lo - SLOT_WALL["in"], SLOT_WALL["reach"])
            arc[r].append(bm.verts.new((SP.side * (hx + math.cos(a) * d), y, hz + math.sin(a) * d)))
    lines = [[V[r][k_top]] + arc[r] + [roof[r]] for r in range(r0, r1 + 1)]
    faces = [bm.faces.new((lines[i][j], lines[i + 1][j], lines[i + 1][j + 1], lines[i][j + 1]))
             for i in range(r1 - r0) for j in range(len(lines[0]) - 1)]
    for r in (r0, r1):
        faces.append(bm.faces.new([V[r][k] for k in range(k_top, k_out + 1)] + [roof[r]] + arc[r][::-1]))
    p.tag(faces, slot, INTERIOR)


def well_structure(bl, p, side, slots):
    """Roof frames and wall longerons in dark interior paint."""
    SKIN = slots[0]
    X, Y, Z = Vector((side, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))  # X mirrored, so the twins match vertex for vertex
    for s in (24.0, 25.5, 27.0):
        sf.box(p, Vector((side * 2.98, bl.st(s), WELL_CEILING - 0.085)), (X, Y, Z), (0.6, 0.08, 0.14), SKIN, INTERIOR)
    s0, s1 = WELL_S[0] + 0.1, WELL_S[1] - 0.1
    sf.box(p, Vector((side * 2.12, bl.st((s0 + s1) / 2), 1.95)), (X, Y, Z), (0.1, s1 - s0, 0.1), SKIN, INTERIOR)
    sf.box(p, Vector((side * 3.16, bl.st((s0 + s1) / 2), WELL_CEILING - 0.065)), (X, Y, Z), (0.1, s1 - s0, 0.1), SKIN, INTERIOR)
    # Fittings stay against the roof and walls, outside the retracted bogie's swept volume.
    for s, x, z, size in ((24.25, 3.12, 2.77, (0.19, 0.28, 0.20)),
                           (26.65, 3.12, 2.77, (0.18, 0.24, 0.20))):
        sf.box(p, Vector((side * x, bl.st(s), z)), (X, Y, Z), size, SKIN, INTERIOR)
    for dx in (0.0, 0.045):
        sf.tube(p, [Vector((side * (3.12 + dx), bl.st(s), 2.86)) for s in (23.5, 27.5)],
                0.012, 6, SKIN, INTERIOR)
    a, b = Vector((side * 2.16, bl.st(24.75), 2.03)), Vector((side * 2.16, bl.st(24.25), 1.95))
    sf.tube(p, [a, a.lerp(b, 0.6)], 0.045, 10, SKIN, INTERIOR)
    sf.tube(p, [a.lerp(b, 0.55), b], 0.022, 8, SKIN, INTERIOR)
    hinge = bpy.data.objects["geardoor_LM"].matrix_world.translation
    for s in (23.45, 24.75, 26.25, 27.55):
        sf.box(p, Vector((side * (hinge.x + 0.045), bl.st(s), hinge.z + 0.055)),
               (X, Y, Z), (0.10, 0.20, 0.12), SKIN, INTERIOR)


def door_stiffener(p, pts, nrm, axis, index, width, depth, slot, cls=0):
    """A rib or longeron follows the skin normals, with its foot buried 1 mm into the inner face."""
    if axis == 0:
        line, normals = pts[index], nrm[index]
        tangent = Vector((0, 1, 0))
    else:
        line, normals = [row[index] for row in pts], [row[index] for row in nrm]
        tangent = Vector((1, 0, 0))
    patch = [[q - tangent * width / 2 for q in line], [q + tangent * width / 2 for q in line]]
    return sum(sf.slab(p, patch, [normals, normals], -DOOR_T + 0.001, -DOOR_T - depth,
                       slot, slot, cls=cls, cls_rest=cls), [])


def build_door(bl, p, SP, side, slots):
    """The main gear door built closed (its outer face flush with the sponson's underside, from the hinge line to its
    free edge, which runs out in tabs over the leg door's cut-back corners; its edges painted as its face; inner face
    and stiffeners on the structure trim, hinge knuckles on the mechanical trim) and swung 90 degrees down about the
    blockout's hinge, its rest pose with the gear down."""
    SKIN, STRUCT, GLASS, MECH = slots[:4]
    hinge_l = bpy.data.objects["geardoor_LM"].matrix_world.translation.copy()
    hinge = Vector((side * hinge_l.x, hinge_l.y, hinge_l.z))
    s0, s1 = WELL_S[0] + 0.03, WELL_S[1] - 0.03
    cl, cx = LEG_DOOR_CHAMFER
    rows = [s0, s0 + cl, (s0 + s1) / 2, s1 - cl, s1]
    nu, nv = len(rows) - 1, 10
    pts, nrm = [], []
    for s in rows:
        tab = cx * max(0.0, 1 - (s - s0) / cl, 1 - (s1 - s) / cl)
        row_p, row_n = [], []
        for j in range(nv + 1):
            x = DOOR_X[0] + DOOR_GAP + (DOOR_X[1] - DOOR_X[0] - 2 * DOOR_GAP) * j / nv + (tab if j == nv else 0.0)
            ph = SP.phi_for_x(s, x, 140.0, 215.0)
            row_p.append(SP.point(s, ph))
            row_n.append(SP.normal(s, ph))
        pts.append(row_p)
        nrm.append(row_n)
    top, bottom, sides = sf.slab(p, pts, nrm, 0.0, -DOOR_T, SKIN, STRUCT, cls=DOOR, cls_rest=0)
    p.tag(sides, SKIN, DOOR)  # the edges show in the gaps round the closed door: the bright structure trim read as seams
    faces = top + bottom + sides
    # stiffeners on the inner face: three ribs across and a beam along the middle
    for i in (1, 2, 3):
        faces += door_stiffener(p, pts, nrm, 0, i, 0.05, 0.07, STRUCT)
    faces += door_stiffener(p, pts, nrm, 1, nv // 2, 0.06, 0.06, STRUCT)
    for s in (23.45, 24.75, 26.25, 27.55):
        faces += sf.box(p, Vector((hinge.x, bl.st(s), hinge.z)), (Vector((side, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))),
                        (0.07, 0.16, 0.07), MECH)
        q = pts[min(range(len(rows)), key=lambda i: abs(rows[i] - s))][0]
        a = Vector((hinge.x, bl.st(s), hinge.z))
        b = Vector((q.x, bl.st(s), q.z)) - nrm[0][0] * DOOR_T
        d = (b - a).normalized()
        faces += sf.box(p, (a + b) / 2, (Vector((0, 1, 0)), d, Vector((0, 1, 0)).cross(d)),
                        (0.08, (b - a).length + 0.03, 0.05), MECH)
    sf.rotate_about(p, faces, hinge, Vector((0, 1, 0)), side * math.pi / 2)


# ---------- build ----------
def build(bl, surf, slots):
    parts = {}

    def part(name):
        parts[name] = sf.Part(name, (slots[0],))
        return parts[name]

    S = Strut(bl, 1, ROOT_SEC_N)
    build_inner(bl, part("strut_inner_L"), S, slots, hull_triangles(bl, surf, slots))
    S = Strut(bl, 1)
    build_outer(bl, part("strut_outer_L"), S, slots)
    SP, _ = build_sponson(bl, part("sponson_L"), 1, slots)
    build_door(bl, part("geardoor_LM_visible"), SP, 1, slots)
    # Keep the denser root outline and class boundaries; spend the cap on curved silhouettes, not shallow edges.
    for name in ("strut_inner_L", "sponson_L"):
        p = parts[name]
        p.bm.normal_update()
        for edge in p.bm.edges:
            if len(edge.link_faces) != 2 or edge.link_faces[0][p.cls] != edge.link_faces[1][p.cls]:
                edge.seam = True
        edges = [e for e in p.bm.edges if not any(f[p.cls] == ROOT_BOOT for f in e.link_faces)]
        verts = [v for v in p.bm.verts if not any(f[p.cls] == ROOT_BOOT for f in v.link_faces)]
        bmesh.ops.dissolve_limit(p.bm, angle_limit=math.radians(3.5), verts=verts, edges=edges,
                                delimit={"SEAM", "MATERIAL"})
        bmesh.ops.triangulate(p.bm, faces=p.bm.faces[:], quad_method="BEAUTY", ngon_method="EAR_CLIP")
    for right, left in MIRROR_PARTS.items():
        twin = parts[right] = sf.Part(right, parts[left].slots)
        twin.bm.free()
        # Match the entry's collapsed-edge cleanup before mirroring; applying it to each twin can reorder faces.
        bm = parts[left].bm
        while True:
            count = (len(bm.verts), len(bm.edges), len(bm.faces))
            bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
            if count == (len(bm.verts), len(bm.edges), len(bm.faces)):
                break
        twin.bm = parts[left].bm.copy()
        bmesh.ops.transform(twin.bm, matrix=Matrix.Scale(-1, 4, (1, 0, 0)), verts=twin.bm.verts)
        for face in twin.bm.faces:
            face.normal_flip()
        twin.cls = twin.bm.faces.layers.int["cls"]
    return parts


# ---------- checks ----------
def check(bl, objs):
    """No overlap between this group's parts and any unjointed part at extension 0, 0.5 and 1 (the stages pass over
    the strut's node); the right-hand parts mirror the left's vertex for vertex; the gear well and door against the
    blockout's bogie; the strut's foot inside the node fairing. Leaves the stages as found."""
    scene = {o.name: o for o in bpy.data.collections["Centurion"].all_objects
             if o.type == "MESH" and o.users_collection[0].name not in ("Colliders", "LOD1")}
    stages = {n: o for n, o in scene.items() if "slide_axis" in o}
    saved = {n: o.location.copy() for n, o in stages.items()}
    mine = set(objs)

    def near(o, margin=0.3):
        lo, hi = bl.bounds(bl.world_mesh(o)[0])
        return lo - Vector((margin,) * 3), hi + Vector((margin,) * 3)
    by_ext = {}
    for e in (0.0, 0.5, 1.0):
        bl.set_extension(stages, e)
        boxes = {n: near(o) for n, o in scene.items()}
        pick = {n: o for n, o in scene.items() if n in mine or any(
            all(boxes[n][0][i] <= boxes[m][1][i] and boxes[m][0][i] <= boxes[n][1][i] for i in range(3)) for m in mine)}
        found = bl.overlaps({**pick, **objs})
        by_ext[f"{e:.1f}"] = {k: v for k, v in found.items() if any(part in k.split("~") for part in mine)}
    for n, o in stages.items():
        o.location = saved[n]
    bpy.context.view_layer.update()
    res = {"no_overlap_unjointed_parts": {"value": by_ext, "pass": not any(by_ext.values())}}

    worst = {}
    for r, l in MIRROR_PARTS.items():
        vr, vl = bl.world_mesh(objs[r])[0], bl.world_mesh(objs[l])[0]
        if len(vr) != len(vl):
            worst[r] = f"{len(vr)} vertices against {len(vl)}"
            continue
        tree = KDTree(len(vl))
        for i, q in enumerate(vl):
            tree.insert(q, i)
        tree.balance()
        worst[r] = round(max(tree.find(Vector((-a.x, a.y, a.z)))[2] for a in vr), 6)
    res["right_mirrors_left"] = {"value": worst, "limit": "1e-4 m", "pass": all(isinstance(v, float) and v < 1e-4 for v in worst.values())}
    face_misses = {}
    for right, left in MIRROR_PARTS.items():
        rv, rf = bl.world_mesh(objs[right])
        lv, lf = bl.world_mesh(objs[left])
        face_misses[right] = sum(len(a) != len(b) or any(
            min((Vector((-rv[i].x, rv[i].y, rv[i].z)) - lv[j]).length for j in b) > 1e-4 for i in a)
            for a, b in zip(rf, lf)) + abs(len(rf) - len(lf))
    res["mirror_faces_correspond"] = {"value": face_misses, "limit": "zero faces out of order",
                                      "pass": not any(face_misses.values())}

    door, wheel = objs["geardoor_LM_visible"], scene["wheel_LM"]
    dv = bl.world_mesh(door)[0]
    gap = bl.min_distance(door, wheel)
    res["main_door_rest_pose"] = {"value": {"lowest_z": round(min(v.z for v in dv), 3), "to_wheels_m": round(gap, 3)},
                                  "limit": "lowest above 0.3 m, 5 cm clear of the wheels", "pass": min(v.z for v in dv) > 0.3 and gap > 0.05}
    res["strut_foot_in_node_fairing"] = foot_report(bl, objs["strut_outer_L"])
    res["node_clear_aileron_deflection"] = node_aileron_clearance(bl, objs)
    res["main_gear_well"] = {"value": well_report(bl), "pass": True}
    return res


def node_aileron_clearance(bl, objs):
    from .wing import DEFLECT
    gaps, hits = {}, {}
    for side in ("L", "R"):
        hinge = bpy.data.objects[f"aileron_{side}"]
        aileron = bpy.data.objects[f"aileron_{side}_visible"]
        rest = hinge.matrix_basis.copy()
        lo, hi = DEFLECT["aileron"]
        for degree in range(int(lo), int(hi) + 1, 5):
            hinge.matrix_basis = rest @ Matrix.Rotation(math.radians(degree), 4, "X")
            bpy.context.view_layer.update()
            key = f"{side}@{degree:+d}"
            gaps[key] = round(bl.min_distance(objs[f"strut_outer_{side}"], aileron), 3)
            count = bl.clash_faces(objs[f"strut_outer_{side}"], aileron)
            if count:
                hits[key] = count
        hinge.matrix_basis = rest
    bpy.context.view_layer.update()
    return {"value": {"gaps_m": gaps, "intersections": hits}, "limit": "clear through the full aileron range",
            "pass": not hits and min(gaps.values()) > 0.015}


THIN_UNDER = 0.08


def foot_report(bl, obj):
    """Strut vertices near the node within THIN_UNDER of the wing's lower skin (the thinned taper and the foot) must sit
    inside the node fairing (in its plan outline and above its underside), or the thin part shows as a blade. Deeper
    down the strut is still near full section and enters the fairing through its wall."""
    S = Strut(bl, 1)
    xc, s0, s1 = pod_frame(bl, S)
    me = obj.data
    mw = obj.matrix_world
    cls = np.zeros(len(me.polygons), np.int32)
    me.attributes["cls"].data.foreach_get("value", cls)
    pod = {i for p in me.polygons if cls[p.index] == NODE_POD for i in p.vertices}
    worst, n_out, n = 0.0, 0, 0
    for vt in me.vertices:
        if vt.index in pod:
            continue
        q = mw @ vt.co
        s = q.y + bl.Y0
        if not (s0 < s < s1) or abs(q.x - S.node.x) > 1.2:
            continue
        under = bl.wing_lower(1, abs(q.x), s).z - q.z
        if not 0.002 < under < THIN_UNDER or (q - S.node).length > 1.3:
            continue
        n += 1
        g = pod_g((s - s0) / (s1 - s0))
        hw, dp = POD_W * g, POD_D * g ** 1.2
        lat = abs(q.x - xc) / max(hw, 1e-6)
        depth = dp * max(0.0, 1 - min(lat, 1.0) ** 2.6) ** (1 / 2.6)  # the fairing's superellipse arc
        miss = max(under - depth, (lat - 1) * hw)
        if miss > 0.002:
            n_out += 1
            worst = max(worst, miss)
    return {"value": {"strut_vertices_under_skin": n, "outside_fairing": n_out, "worst_m": round(worst, 3)},
            "limit": "none outside by more than 2 mm", "pass": n_out == 0}


def well_report(bl):
    """The well left for the gear group (left side; the right mirrors it)."""
    SP = Sponson(bl, 1)
    rows = {}
    for s in (WELL_S[0], 25.5, WELL_S[1]):
        out, inb = SP.well_edges(s)
        xo, zo = SP.local(s, out)
        xi, zi = SP.local(s, inb)
        rows[f"{s:.1f}"] = {"opening_inboard_xz": [round(xi, 3), round(zi, 3)], "opening_outboard_xz": [round(xo, 3), round(zo, 3)],
                            "roof_z_outboard": WELL_CEILING, "roof_z_at_hinge": round(min(WELL_CEILING, bl.fus_bottom_z(s, DOOR_X[0]) - 0.08), 3),
                            "outboard_wall_top_x": round(xo - WELL_WALL_IN, 3)}
    hx, hz, hs = SP.hinge
    top = SP.local(hs, SP.hinge_phi(hs, LEG_SLOT["band_deg"][1]))
    return {"stations": list(WELL_S), "length_m": round(WELL_S[1] - WELL_S[0], 2), "sections": rows,
            "door_covers_x": list(DOOR_X), "open_with_gear_down_x": [DOOR_X[1], rows["25.5"]["opening_outboard_xz"][0]],
            "leg_slot_stations": [hs - LEG_SLOT["half_len"], hs + LEG_SLOT["half_len"]],
            "leg_slot_top_xz": [round(top[0], 3), round(top[1], 3)],
            "bogie_blockout": "wheels x 3.055 to 4.255, stations 23.5 to 27.5, z 0 to 1.2",
            "hinge_xz_station": [round(hx, 3), round(hz, 3), hs], "hinge_bump": HINGE_BUMP}


# ---------- paint layout ----------
# Line weights, fastener spacing and colours follow nose.py: a part or primary joint is a 0.02 m line with fastener
# rows either side, a skin lap 0.016 m with none, an access panel 0.016 m with fastener rows round it.
PAINT_RGB = (0.38, 0.39, 0.405)  # paint.PAINT[HULL]
DARK = (0.10, 0.105, 0.11)
SEALANT = (0.20, 0.205, 0.21)
SATIN = ((0.46, 0.47, 0.48), 0.54, 0.2)  # the wing's bare metal (leading-edge strip): rgb, smoothness (skin 0.42), metal
RED_LINE = 0.022  # the wing's red line weight
RED = (0.55, 0.10, 0.08)
STENCIL = (0.80, 0.80, 0.78)
UNDERSIDE = 0.06  # the strut's lower skin this much darker, so its flat faces read apart
# Strut: spanwise lines as chord fractions (front spar, rear spar, trailing-edge closure), all primary; the
# leading-edge strip's aft edge (a bonded lap); chordwise splices with doubler straps, metres from the root on the
# outer segment; access panels (metres from the root, chord fraction, size along and across, side).
STRUT_SPARS = (0.15, 0.62, 0.86)
LE_STRIP = 0.09
STRUT_SPLICES = (10.3, 13.4)
SPLICE_STRAP = 0.16  # the doubler strap's width over a splice
STRUT_PANELS = ((11.6, 0.4, 0.55, 0.32, -1), (14.6, 0.4, 0.55, 0.32, -1), (16.0, 0.35, 0.4, 0.26, -1),
                (5.95, 0.42, 0.4, 0.26, -1), (12.0, 0.38, 0.7, 0.36, 1), (8.4, 0.4, 0.5, 0.3, -1),
                (9.0, 0.38, 0.45, 0.3, 1), (15.4, 0.38, 0.5, 0.32, 1), (13.0, 0.74, 0.36, 0.18, -1))
ROOT_JOINT = 1.05  # the root fairing's joint to the strut, metres along the axis from the body
COLLAR_FLANGE = 0.30  # the collar fitting's flange line on the strut, metres along the axis from the cowl
# Sponson, on (station, psi): psi is the angle round the pod's own centre at that station, 0 at its bottom, 90
# outboard, 180 on top, so a line of constant psi follows the pod into its nose and tail like a stringer.
# Full-girth joints (primary: nose cap, the door's ends carried up the flank, tail cone); the skin between them in
# bands between longitudinal laps on stringer lines, each band split at its own frames (part-girth laps, staggered
# band to band like brickwork, so no frame runs the full girth); access panels (station from, to, psi from, to);
# placards (station, psi, width, height); the jacking point and the ground point (station, psi); drains (station,
# psi); the flush inlet (station from, to, psi); the louvres (station from, to, psi, count). The well's opening runs
# from the door's hinge (psi -40) to psi 55 between the door's stations.
SPONSON_RINGS = (20.35, WELL_S[0] - 0.02, WELL_S[1] + 0.02, 30.3)
SPONSON_BANDS = ((-60.0, 20.0, (21.9, 29.3)), (20.0, 62.0, (21.7, 29.0)), (62.0, 95.0, (21.3, 24.4, 26.6, 29.4)),
                 (95.0, 128.0, (21.9, 25.5, 28.75)), (128.0, 158.0, (22.5, 26.0, 29.2)),
                 (158.0, 200.0, (21.6, 24.8, 28.2)))
# Access panels stand at least 7 degrees (about 0.12 m) and 0.15 m clear of every lap and joint, or their edges
# read as doubled lines.
SPONSON_PANELS = ((20.6, 21.05, 70.0, 87.0), (20.85, 21.45, 102.0, 121.0), (21.95, 22.55, 30.0, 52.0),
                  (22.45, 22.85, 102.0, 121.0), (23.5, 24.15, 136.0, 151.0), (23.6, 24.2, 70.0, 87.0),
                  (26.0, 26.5, 102.0, 121.0), (26.85, 27.55, 70.0, 87.0), (28.15, 28.65, 136.0, 151.0),
                  (29.35, 29.9, 30.0, 50.0), (29.6, 30.0, 70.0, 87.0), (30.6, 31.05, 102.0, 121.0),
                  (21.0, 21.5, -30.0, 0.0))
SPONSON_PLACARDS = ((21.62, 80.0, 0.2, 0.11), (22.5, 12.0, 0.16, 0.09), (28.3, 112.0, 0.18, 0.1), (25.0, 108.0, 0.16, 0.09))
JACK = (22.15, 10.0)
GROUND_POINT = (22.95, 34.0)
DRAINS = ((20.6, 2.0), (22.8, -6.0), (28.3, 4.0), (29.8, -2.0), (30.9, 6.0))
FLUSH_INLET = (21.15, 21.75, 142.0)
LOUVRES = (28.1, 28.55, 40.0, 8)
FASTEN_PITCH = 0.09


def paint(cv, text_mask):
    """The group's paint over a Canvas (m4/paint.py). text_mask is unused: see the module note on text."""
    np = cv.xp
    bl = cv.surf.bl
    cls = cv.cls
    pos, nrm = cv.pos.copy(), cv.nrm.copy()
    neg = pos[:, 0] < 0  # right-hand texels share the left's islands: read them on the left
    pos[neg, 0] *= -1
    nrm[neg, 0] *= -1
    for c in SKIN_CLASSES:
        m = cls == c
        cv.albedo[m] = PAINT_RGB
        cv.smooth[m] = 0.42
    on = lambda *cs: np.isin(cls, cs).astype(float)
    paint_strut(cv, bl, pos, nrm, on)
    paint_node_pod(cv, bl, pos, on(NODE_POD))
    paint_sponson(cv, bl, pos, nrm, on(SPONSON))
    paint_door(cv, bl, pos, on(DOOR))


def placard(cv, u, v, centre, size, mask):
    """A plain ruled placard (no text: the islands are shared with the mirrored side): an outline and three rules."""
    np = cv.xp
    from .paint import rrect_sdf
    (cu, cv_), (w, h) = centre, size
    sdf = rrect_sdf(u, v, cu - w / 2, cu + w / 2, cv_ - h / 2, cv_ + h / 2, 0.01)
    inside = cv.fill_coverage(sdf) * mask
    cv.paint(cv.coverage(np.abs(sdf), 0.008) * mask, rgb=STENCIL)
    for k in (-1, 0, 1):
        d = np.abs(v - (cv_ + k * h * 0.25))
        cv.paint(cv.coverage(d, 0.006) * inside * (np.abs(u - cu) < w / 2 - 0.025), rgb=STENCIL)


def body_distance(cv, pos):
    """Metres outside the fuselage skin, along the ray from the section's centre (the body is a superellipse)."""
    np = cv.xp
    s = pos[:, 1] + cv.coords.bl.Y0
    w, top, bot = cv.coords._profile(s)
    zc, h = (top + bot) / 2, np.maximum((top - bot) / 2, 1e-3)
    P = cv.coords.bl.FUS_P
    q = (np.abs(pos[:, 0] / w) ** P + np.abs((pos[:, 2] - zc) / h) ** P) ** (1 / P)
    return np.hypot(pos[:, 0], pos[:, 2] - zc) * (1 - 1 / np.maximum(q, 1e-6))


def paint_strut(cv, bl, pos, nrm, on):
    np = cv.xp
    from .paint import rrect_sdf, smoothstep
    ST, RB, CO = on(STRUT), on(ROOT_BOOT), on(COLLAR)
    STR = ST + RB + CO
    S = Strut(bl, 1)
    vec = lambda v: np.array(tuple(v))
    root, ax, cd, td = vec(S.root), vec(S.ax), vec(S.cd), vec(S.td)
    rel = pos - root
    D, C, T = rel @ ax, rel @ cd, rel @ td  # metres along the line from the root; aft of the line; off the chord plane
    UP = (nrm @ td) > 0
    up, lo = UP.astype(float), (~UP).astype(float)
    U = (C + 0.4 * S.ch) / S.ch  # chord fraction on the plain section
    girth = C + 2 * T  # a coordinate along a chordwise line, for fastener rows on it
    near = STR > 0
    A_body = np.full(cv.n, 99.0)
    A_body[near] = axis_distance_sdf(pos[near], -ax, lambda p: body_distance(cv, p))
    cc = cowl_centre(bl)
    A_cowl = np.minimum(axis_distance(pos, ax, lambda p: cowl_radius(bl, p), centre=cc),
                        axis_distance(pos, -ax, lambda p: cowl_radius(bl, p), centre=cc))
    out_cowl = (np.hypot(pos[:, 0] - cc[0], pos[:, 2] - cc[1]) > cowl_radius(bl, pos) - 0.03).astype(float)
    plain = ST * (A_body > ROOT_JOINT + 0.02) * (A_cowl > COLLAR_FLANGE + 0.02) * out_cowl

    # panel tones: each panel between the joints differs a little; the underside is a shade darker
    cell = np.searchsorted(np.array((0.0, S.d_in, S.d_out) + STRUT_SPLICES), D) * 8 + np.searchsorted(np.array(STRUT_SPARS), U) * 2 + UP
    cell = cell * 8 + np.clip(cv.cls - 30, 0, 7)
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    cv.albedo *= (1 + 0.045 * tone * STR - UNDERSIDE * lo * STR)[:, None]

    # leading-edge strip in satin bare metal, from the body to the wing, round the fairings too; a bonded lap behind it
    rgb, smooth, metal = SATIN
    cv.paint(smoothstep(LE_STRIP + 0.005, LE_STRIP - 0.005, U) * STR, rgb=rgb, smooth=smooth, metal=metal)
    cv.groove(np.abs(U - LE_STRIP) * S.ch, mask=STR * out_cowl)
    # spars and the trailing-edge closure: spanwise primary lines with fastener rows
    for u0 in STRUT_SPARS:
        d = np.abs(U - u0) * S.ch
        cv.groove(d, 0.02, mask=plain)
        splice = np.min([np.abs(D - x) for x in STRUT_SPLICES], axis=0)
        cv.fasteners(d, D, 0.03, FASTEN_PITCH, mask=plain * (d < 0.08) * (splice < SPLICE_STRAP))
    # splices: a chordwise joint under a doubler strap, two fastener rows each side
    for x in STRUT_SPLICES:
        d = np.abs(D - x)
        cv.paint(cv.coverage(d, SPLICE_STRAP) * plain, rgb=(0.36, 0.37, 0.385), height=0.0008)
        cv.groove(np.abs(d - SPLICE_STRAP / 2), 0.008, -0.0012, 0.2, mask=plain)
        cv.groove(d, 0.02, mask=plain)
        for o in (0.03, 0.06):
            cv.fasteners(d, girth, o, FASTEN_PITCH, mask=plain * (d < 0.08))
    for x, u, wl, wc, s in STRUT_PANELS:
        sdf = rrect_sdf(D, (U - u) * S.ch, x - wl / 2, x + wl / 2, -wc / 2, wc / 2, 0.05)
        m = ST * (lo if s < 0 else up)
        cv.groove(np.abs(sdf), mask=m)
        cv.fasteners(np.abs(sdf), D + C, 0.026, mask=m * (np.abs(sdf) < 0.05))
    placard(cv, D, (U - 0.4) * S.ch, (12.55, 0.0), (0.2, 0.11), ST * up)
    # drain holes on the lower skin by the trailing edge
    for x in np.arange(9.0, 17.5, 2.4):
        r = np.hypot(D - x, (U - 0.9) * S.ch)
        cv.paint(cv.fill_coverage(r - 0.012) * ST * lo, rgb=DARK, height=-0.002)
    # The cowl landing has sealant and fasteners; both fairings keep their outer joint on the strut.
    for A, m, joint in ((A_body, (RB + ST) * out_cowl, ROOT_JOINT), (A_cowl, (CO + ST) * out_cowl, COLLAR_FLANGE)):
        if joint == COLLAR_FLANGE:
            cv.paint(cv.coverage(A, 0.03) * m, rgb=SEALANT, smooth=0.3)
            cv.fasteners(np.abs(A - 0.05), girth, 0.0, FASTEN_PITCH, mask=m * (A < 0.1))
        d = np.abs(A - joint)
        cv.groove(d, 0.02, mask=m)
        cv.fasteners(d, girth, 0.03, FASTEN_PITCH, mask=m * (d < 0.08))


def paint_node_pod(cv, bl, pos, NP):
    """The node fairing: a fastener row round its flange, the joint between its two halves, an attachment access
    panel on its outboard flank, a drain at its lowest point."""
    np = cv.xp
    from .paint import rrect_sdf
    if not NP.any():
        return
    S = Strut(bl, 1)
    xc, s0, s1 = pod_frame(bl, S)
    st = pos[:, 1] + bl.Y0
    from .paint import to_host
    gap = np.asarray(node_pod_height(bl, to_host(pos), to_host(NP > 0)))  # metres under the wing's lower skin
    v = np.clip((st - s0) / (s1 - s0), 0, 1)
    g = np.where(v < POD_VM, np.sqrt(np.maximum(0.0, 1 - ((POD_VM - v) / POD_VM) ** 2).astype(float)),
                 np.maximum(0.0, 1 - ((v - POD_VM) / (1 - POD_VM)) ** 2) ** 1.4)
    hw = POD_W * g
    lat = pos[:, 0] - xc  # outboard positive
    on_flange = NP * (gap < POD_FLANGE[1] + 0.003)
    cv.fasteners(np.abs(np.abs(lat) - (hw + 0.6 * POD_FLANGE[0] * np.sqrt(g))), st, 0.0, 0.07, 0.006, mask=on_flange)
    cv.paint(on_flange * (np.abs(np.abs(lat) - hw) < 0.015), rgb=SEALANT, smooth=0.3)
    sn = S.node.y + bl.Y0 + 0.05
    cv.groove(np.abs(st - sn), 0.02, mask=NP * (gap > 0.012))
    cv.fasteners(np.abs(st - sn), gap + np.abs(lat), 0.03, FASTEN_PITCH, mask=NP * (gap > 0.03))
    sdf = rrect_sdf(st, gap, sn - 0.62, sn - 0.12, 0.05, 0.2, 0.03)
    cv.groove(np.abs(sdf), mask=NP * (lat > 0))
    cv.fasteners(np.abs(sdf), st + gap, 0.022, mask=NP * (lat > 0) * (np.abs(sdf) < 0.04))
    r = np.hypot(st - (sn + 0.45), lat)
    cv.paint(cv.fill_coverage(r - 0.015) * NP * (gap > 0.08), rgb=DARK, height=-0.002)


def sponson_frame_table(bl):
    """The pod's centre, outboard half width, half height and inboard half width at stations along it, for the
    paint's (station, psi) coordinates."""
    SP = Sponson(bl, 1)
    ss = np.arange(SP.nose, SP.tail + 0.025, 0.025)
    rows = np.array([SP.frame(float(s))[:4] + (SP.frame(float(s))[7],) for s in ss])
    return ss, rows


def sponson_coords(bl, ss, rows, P):
    """(station, psi, the pod's mean radius) of points P: psi in degrees round the pod's own section, 0 at its
    bottom, + outboard, on the pod's inboard half width inboard of its centre."""
    from .paint import np
    s = P[:, 1] + bl.Y0
    px, pz, a, b, a_in = (np.interp(s, ss, rows[:, i]) for i in range(5))
    psi = np.degrees(np.arctan2((P[:, 0] - px) / np.where(P[:, 0] > px, a, a_in), (pz - P[:, 2]) / b))
    psi = np.where(psi < -120.0, psi + 360.0, psi)  # past the top onto the upper fillet, not round from the bottom
    return s, psi, np.sqrt((a * a + b * b) / 2)


def paint_sponson(cv, bl, pos, nrm, SPN):
    np = cv.xp
    from .paint import poly_sdf, rrect_sdf
    if not SPN.any():
        return
    ss, rows = sponson_frame_table(bl)
    st, psi, r_eff = sponson_coords(bl, ss, rows, pos)
    arc = np.radians(psi) * r_eff  # about metres round the pod
    to_arc = lambda deg: np.radians(deg) * r_eff
    # Lines are drawn at a width in metres on the skin, as the nose's: a distance in (station, arc) is divided by the
    # field's gradient along the skin, which (station, arc) leaves far from 1 over the pod's ends and its fillets.
    tang = lambda g: g - np.sum(g * nrm, axis=1)[:, None] * nrm
    G_st = tang(np.tile((0.0, 1.0, 0.0), (len(pos), 1)))
    G_arc = np.zeros_like(pos)
    for i in range(3):
        P = pos.copy()
        P[:, i] += 1e-3
        _, psi_i, r_i = sponson_coords(bl, ss, rows, P)
        G_arc[:, i] = (np.radians((psi_i - psi + 180.0) % 360.0 - 180.0) * r_eff + np.radians(psi) * (r_i - r_eff)) / 1e-3
    G_arc = tang(G_arc)

    def skin_d(fn):
        """|fn(station, arc)| as metres along the skin."""
        f0 = fn(st, arc)
        fu, fv = (fn(st + 1e-3, arc) - f0) / 1e-3, (fn(st, arc + 1e-3) - f0) / 1e-3
        return np.abs(f0) / np.maximum(np.linalg.norm(fu[:, None] * G_st + fv[:, None] * G_arc, axis=1), 0.25)
    db = body_distance(cv, pos)  # off the body's skin
    w, top, bot = cv.coords._profile(st)
    zc = (top + bot) / 2
    nb = np.stack([pos[:, 0], np.zeros(len(pos)), pos[:, 2] - zc], axis=1)
    nb /= np.linalg.norm(nb, axis=1)[:, None] + 1e-9
    slope = np.sqrt(np.clip(1 - np.sum(nrm * nb, axis=1) ** 2, 0.0025, 1.0))
    pod = SPN * (db > 0.1)
    s0, s1 = SPONSON_RINGS[0], SPONSON_RINGS[-1]
    inside = (st > s0) * (st < s1)

    # panel tones between the joints: each band's cells between its own frames
    cell = np.zeros(len(st), np.int64)
    for i, (p0, p1, splits) in enumerate(SPONSON_BANDS):
        m = (psi >= p0) & (psi < p1)
        cell[m] = (i + 1) * 64 + np.searchsorted(np.array(sorted(SPONSON_RINGS + splits)), st[m])
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    cv.albedo *= (1 + 0.04 * tone * SPN)[:, None]
    # the fillet's edge on the body: a sealant line exactly on it, a fastener row on the sponson beside it
    edge = db / slope  # metres along the skin from the edge
    cv.paint(cv.coverage(np.abs(edge), 0.03) * SPN, rgb=SEALANT, smooth=0.3)
    cv.fasteners(np.abs(edge - 0.05), st + arc, 0.0, FASTEN_PITCH, mask=SPN * (edge < 0.1))
    # full-girth joints: nose cap, the door's ends carried up the flank, tail cone
    for x in SPONSON_RINGS:
        d = skin_d(lambda u, v: u - x)
        cv.groove(d, 0.02, mask=pod)
        cv.fasteners(d, arc, 0.03, FASTEN_PITCH, mask=pod * (d < 0.08))
    # longitudinal laps between the bands and each band's frame laps (no fasteners)
    for p0, p1, splits in SPONSON_BANDS:
        cv.groove(skin_d(lambda u, v: v - to_arc(p1)), mask=pod * inside)
        for x in splits:
            cv.groove(skin_d(lambda u, v: u - x), mask=pod * (psi > p0) * (psi < p1))
    for t0, t1, p0, p1 in SPONSON_PANELS:
        d = skin_d(lambda u, v: rrect_sdf(u, v - to_arc((p0 + p1) / 2), t0, t1, -to_arc((p1 - p0) / 2), to_arc((p1 - p0) / 2), 0.05))
        cv.groove(d, mask=pod)
        cv.fasteners(d, st + arc, 0.026, mask=pod * (d < 0.05))
    for t, p0, wd, ht in SPONSON_PLACARDS:
        placard(cv, st, arc - to_arc(p0), (t, 0.0), (wd, ht), pod)
    # jacking point: a red ring round a dark socket, as the aft body's
    js, jp = JACK
    r = np.hypot(st - js, arc - to_arc(jp))
    cv.paint(cv.coverage(np.abs(r - 0.07), RED_LINE) * SPN, rgb=RED)
    cv.paint(cv.fill_coverage(r - 0.03) * SPN, rgb=DARK, height=-0.003)
    # ground point: a stud in a bare ring; drains: small dark holes along the keel
    gs, gp = GROUND_POINT
    r = np.hypot(st - gs, arc - to_arc(gp))
    cv.paint(cv.fill_coverage(r - 0.035) * pod, rgb=SATIN[0], smooth=SATIN[1], metal=SATIN[2])
    cv.paint(cv.fill_coverage(r - 0.012) * pod, rgb=DARK, height=0.002)
    for ds, dp_ in DRAINS:
        cv.paint(cv.fill_coverage(np.hypot(st - ds, arc - to_arc(dp_)) - 0.012) * SPN, rgb=DARK, height=-0.002)
    # flush (NACA) inlet on the upper flank, opening aft
    t0, t1, p0 = FLUSH_INLET
    v = arc - to_arc(p0)
    sdf = poly_sdf(st, v, [(t0, 0.0), (t1, -0.09), (t1, 0.09)])
    cv.paint(cv.fill_coverage(sdf) * pod, rgb=(0.16, 0.16, 0.17), height=-0.012)
    cv.groove(skin_d(lambda u, w: poly_sdf(u, w - to_arc(p0), [(t0, 0.0), (t1, -0.09), (t1, 0.09)])), 0.012, mask=pod)
    # cooling louvres in a recessed frame on the aft lower flank
    t0, t1, p0, n = LOUVRES
    half = to_arc(9.0)
    v = arc - to_arc(p0)
    cv.groove(skin_d(lambda u, w: rrect_sdf(u, w - to_arc(p0), t0 - 0.05, t1 + 0.05, -half - 0.05, half + 0.05, 0.03)), mask=pod)
    for i in range(n):
        si = t0 + (t1 - t0) * i / (n - 1)
        past = np.maximum(np.abs(v) - half, 0.0)  # the slots run round the pod, half either side of psi
        cv.paint(cv.coverage(np.hypot(st - si, past), 0.026) * pod, rgb=DARK, height=-0.006, smooth=0.3)
        cv.paint(cv.coverage(np.hypot(st - si - 0.022, past), 0.012) * pod, rgb=(0.46, 0.47, 0.48), height=0.0015)
    # a dark surround under the formation strip, as the wing tip's
    SP = Sponson(bl, 1)
    fs = []
    for s_, ph in FORMATION:
        q = SP.point(s_, ph)
        fx, fz, fa, fb = (np.interp(s_, ss, rows[:, i]) for i in range(4))
        fs.append((s_, math.radians(math.degrees(math.atan2((q.x - fx) / fa, (fz - q.z) / fb))) * math.sqrt((fa * fa + fb * fb) / 2)))
    sdf = poly_sdf(st, arc, fs)
    cv.paint(cv.coverage(np.abs(sdf - 0.015), 0.03) * SPN, rgb=DARK, smooth=0.3)


def paint_door(cv, bl, pos, DR):
    """The main gear door: a thin red edge line, a fastener row round its edge and on its ribs, the hinge line."""
    np = cv.xp
    if not DR.any():
        return
    st = pos[:, 1] + bl.Y0
    hl = bpy.data.objects["geardoor_LM"].matrix_world.translation
    h = np.hypot(pos[:, 0] - hl.x, pos[:, 2] - hl.z)
    s0, s1 = WELL_S[0] + 0.03, WELL_S[1] - 0.03
    cl, cx = LEG_DOOR_CHAMFER
    tab = cx * np.clip(np.maximum(1 - (st - s0) / cl, 1 - (s1 - st) / cl), 0.0, None)
    h1 = float(h[(DR > 0) & (tab == 0)].max()) + tab  # the free edge, out over the tabs at the ends
    edge = np.minimum(np.minimum(st - s0, s1 - st), h1 - h)
    cv.paint(DR * cv.coverage(np.abs(edge - 0.025), 0.022), rgb=RED)
    cv.fasteners(np.abs(edge - 0.07), st + h, 0.0, mask=DR * (np.abs(edge - 0.07) < 0.03) * (h > 0.08))
    for x in (s0 + cl, (s0 + s1) / 2, s1 - cl):
        cv.fasteners(np.abs(st - x), h, 0.0, mask=DR * (np.abs(st - x) < 0.03) * (edge > 0.1))
    cv.groove(np.abs(h - 0.05), mask=DR * (edge > 0.04))
    placard(cv, st, h, (24.0, 0.33), (0.18, 0.1), DR)


def cowl_centre(bl):
    return np.array((bl.NACELLES[0][2], bl.NACELLE_Z))


def cowl_radius(bl, p):
    from .paint import np
    _, _, x, front = bl.NACELLES[0]
    u = np.clip((p[:, 1] - bl.st(front)) / bl.NACELLE_LEN, 0.0, 1.0)
    table = [(a, f) for f, a in bl.S6_UF_OUTER[1:]]
    return bl.S6_ENGINE["od"] / 2 * np.interp(u, [a for a, _ in table], [f for _, f in table])


def axis_distance(pos, direction, radius, centre, iters=2):
    """Metres from each point along direction to a cylinder along Y (centre (x, z), radius(points)): the cowl.
    Points whose line misses it get a large distance."""
    from .paint import np
    a = np.array((direction[0], direction[2]))
    q = np.stack([pos[:, 0] - centre[0], pos[:, 2] - centre[1]], axis=1)
    aa = a @ a
    t = np.zeros(len(pos))
    hit = pos.copy()
    for _ in range(iters):
        R = radius(hit)
        qa = q @ a
        disc = qa * qa - aa * (np.sum(q * q, axis=1) - R * R)
        root = (-qa - np.sqrt(np.maximum(disc, 0))) / aa
        alt = (-qa + np.sqrt(np.maximum(disc, 0))) / aa
        t = np.where(np.abs(root) < np.abs(alt), root, alt)
        t = np.where(disc < 0, 99.0, t)
        hit = pos + np.outer(t, direction)
    return np.abs(t)


def axis_distance_sdf(pos, direction, sdf, lo=-0.4, hi=2.6, iters=30):
    """Metres from each point along direction to where sdf (metres outside a surface, of points) changes sign, by
    bisection over [lo, hi]; points whose segment never crosses get a large distance."""
    from .paint import np
    d = np.asarray(direction)
    f = lambda t: sdf(pos + t[:, None] * d)
    a, b = np.full(len(pos), lo), np.full(len(pos), hi)
    fa, fb = f(a), f(b)
    ok = (fa > 0) != (fb > 0)
    for _ in range(iters):
        m = (a + b) / 2
        fm = f(m)
        same = (fm > 0) == (fa > 0)
        a, fa = np.where(same, m, a), np.where(same, fm, fa)
        b = np.where(same, b, m)
    return np.where(ok, np.abs((a + b) / 2), 99.0)


def node_pod_height(bl, pos, mask):
    """Metres below the wing's lower skin (left side), for the node fairing's texels (mask)."""
    out = np.zeros(len(pos))
    for i in np.nonzero(mask)[0]:
        p = pos[i]
        out[i] = bl.wing_lower(1, abs(float(p[0])), float(p[1]) + bl.Y0).z - float(p[2])
    return out
