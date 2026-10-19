"""Part group 4: the engines. Two late-UltraFan adaptive-cycle engines, 4.25 m across, hung under the wing on pylons,
the lifting strut passing through each nacelle's core.

Parts: nacelle_1/2 (intake lip, acoustic liner, inlet cowl, fan cowl doors stepping down 12 mm onto the thrust
reverser's translating sleeve, the sleeve running on into the fan nozzle's trailing edge, the bypass duct, the fan case,
the splitter and core inlet behind the fan, the outlet guide vanes, the strut fillets on the duct wall, the generator
fairing with its cooling air hood, the chine, an inlet probe and drain masts), pylon_1/2 (from the inlet cowl's crown
into the wing's leading edge and lower skin, the aft fairing over the core cowl with its heat shield, filleted into the
wing and the cowls), fan_1/2 (spinner and 22 swept wide-chord blades about the fan part's spin axis) and nozzle_1/2
(the core cowl with the strut fillets, tapering aft to the core nozzle, and the tail plug).

Dimensions are the blockout's (build_centurion S6_ENGINE, S6_UF_OUTER, S6_UF_INNER): a 4.25 m nacelle on a 6.8 m cowl,
the fan 0.15 of the cowl behind the intake plane. The exhaust end is a large geared turbofan's on the blockout's
nozzle colliders: the fan nozzle 0.8 m behind the cowl, the core cowl's shoulder where the blockout's third-stream lip
was, the core nozzle where its core nozzle ended, the plug past its tip. The strut line is the blockout's
(s6_strut_line); its collars on the outer cowl belong to the struts group, the fillets where it crosses the bypass duct
and the core cowl to this one.

Engine positions are (a, theta): a in metres aft of the intake plane along the engine axis, theta in degrees round the
axis from the top, positive outboard. The left engine is built and the right one is its mirror image (MIRROR_PARTS:
nacelle_2 reuses nacelle_1's islands face for face); the fans are built the same way round, so both turn the same way.
pylon_2 is mirrored in shape but keeps its own islands, so the pylon stencils read right on both sides; the nacelles
carry symbols and lines only, since their text would read backwards on the right.

Fan faces, the duct, nozzle lip and tail plug use the shared trims (G4.1). The exposed core cowl and pylon heat
shield use satin metal paint on the atlas, so their service panels and heat bands survive the material split."""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import render
from . import surface as sf
from .surface import FITTING

GROUP = "engines"
PARTS = ("nacelle_1", "nacelle_2", "pylon_1", "pylon_2", "fan_1", "fan_2", "nozzle_1", "nozzle_2")
BUDGET_TRIS = 36000  # Lead's round 2 budget call, 2026-10-14: spend the extra 2,000 on visible silhouettes.
MIRROR_PARTS = {"nacelle_2": "nacelle_1", "nozzle_2": "nozzle_1"}
# Close-ups (m4/render.py's view form, positions (x, station, z)); the first four make the contact sheet.
VIEWS = {
    "eng34": (40, (16.5, 6.5, 1.6), (7.0, 18.2, 3.6)),
    "eng_side": (("ortho", 12.5, render.SIDE), (40.0, 19.0, 3.9), None),
    "eng_rear": (36, (15.5, 29.5, 2.4), (7.25, 21.9, 3.5)),
    "eng_intake": (34, (9.6, 6.0, 2.6), (7.25, 15.0, 3.3)),
    "eng_low": (30, (2.95, 10.5, 0.75), (6.6, 17.6, 2.4)),
    "eng_pylon": (34, (14.5, 12.8, 5.0), (7.25, 17.8, 5.2)),
    "eng_right": (40, (-16.5, 6.5, 1.6), (-7.0, 18.2, 3.6)),
    "eng_chine": (34, (3.4, 9.0, 5.6), (5.9, 15.6, 4.9)),
    "eng_tail": (("ortho", 6.5, render.SIDE), (40.0, 22.3, 3.4), None),
    "eng_tail_low": (32, (9.8, 31.5, 0.7), (7.25, 22.4, 3.1)),
}

# Paint classes past the shared ones (m4/surface.py 1 to 5, the wing 11 to 23).
COWL, SLEEVE, LIP, LINER, PYLON, GEN, CORE_COWL, HEAT_SHIELD = 41, 42, 43, 44, 45, 46, 47, 48

# ---------- nacelle ----------
SEG = 64  # nacelle ring vertices; vertex 0 on top, under the pylon
# The nacelle wall as one closed loop of (r, a, band from this point to the next, UV ring seam here), on the blockout's
# S6_UF_OUTER and S6_UF_INNER (r 2.125, L 6.8) with the corners rounded: the lip from its highlight, the inlet cowl,
# the fan cowl doors ending in a 12 mm step down onto the reverser sleeve, the sleeve's boat-tail running on past the
# cowl's 6.8 m into the fan nozzle (steepening to 13 deg at a 1.3 cm trailing edge, as one painted surface), the nozzle's
# inner wall converging to its exit, the bypass duct, the fan case's rub strip, the acoustic liner and the inner lip
# back to the highlight. The nozzle holds the blockout's petal collider (nozzle_1's first piece) inside its wall.
FAN_NOZZLE_TE = 7.6
WALL = (
    (1.944, -0.027, "lip", True), (1.975, -0.021, "lip", False), (2.006, -0.006, "lip", False),
    (2.040, 0.022, "lip", False), (2.072, 0.080, "lip", False), (2.098, 0.180, "lip", False),
    (2.116, 0.340, "lip", False),
    (2.125, 0.600, "cowl", True),  # lip joint
    (2.127, 1.550, "cowl", True),  # inlet cowl / fan cowl joint
    (2.124, 3.600, "sleeve", True),  # fan cowl trailing edge, then the step onto the sleeve
    (2.112, 3.606, "sleeve", False),
    (2.106, 4.000, "sleeve", False), (2.081, 4.600, "sleeve", False), (2.043, 5.200, "sleeve", False),
    (1.992, 5.750, "sleeve", False), (1.938, 6.250, "sleeve", False), (1.888, 6.800, "sleeve", False),
    (1.859, 7.050, "sleeve", False), (1.817, 7.300, "sleeve", False),
    (1.750, FAN_NOZZLE_TE, "matte", True),  # fan nozzle trailing edge
    (1.743, 7.612, "matte", False),
    (1.737, 7.600, "matte", False),
    (1.748, 7.350, "matte", False), (1.792, 7.100, "matte", False), (1.822, 6.800, "matte", False),
    (1.886, 2.600, "matte", False),
    (1.891, 1.550, "mech", False),  # fan case rub strip
    (1.888, 0.900, "liner", True),
    (1.876, 0.520, "liner", False),
    (1.860, 0.238, "lip", True),  # throat
    (1.866, 0.120, "lip", False), (1.884, 0.040, "lip", False), (1.912, -0.014, "lip", False),
)
WALL_TE = next(i for i, w in enumerate(WALL) if w[1] == FAN_NOZZLE_TE)
OUTER_A = np.array([w[1] for w in WALL[:WALL_TE + 1]])
OUTER_R = np.array([w[0] for w in WALL[:WALL_TE + 1]])
INNER = [(w[0], w[1]) for w in WALL[WALL_TE + 2:]]  # bypass duct and liner, aft to fore
INNER_A = np.array([a for _, a in INNER][::-1])
INNER_R = np.array([r for r, _ in INNER][::-1])
FAN_A = 1.02  # fan plane: 0.15 of the cowl behind the intake plane
# Behind the fan: the hub's continuation (the core inlet's inner wall) and the splitter, a closed ring whose outer face
# runs into the core cowl (nozzle part) at a = 2.72.
CORE_HUB = ((0.0, 1.40), (0.62, 1.40), (0.78, 2.85), (0.0, 2.85))
SPLITTER = ((0.856, 1.600, "mech"), (0.905, 1.700, "matte"), (0.985, 2.050, "matte"), (1.058, 2.800, "matte"),
            (1.000, 2.800, "matte"), (0.880, 2.000, "matte"), (0.836, 1.700, "mech"), (0.840, 1.625, "mech"))
SPLITTER_SEG = 40
OGV = (44, 2.06, 0.30, 0.98, 1.905, 42.0)  # count, leading edge a, chord, root and tip radius, turning (deg)
GENERATOR = (-135.0, 1.18, 3.48, 1.24, 0.30)  # theta (inboard, low), a from, to, width, height above the cowl
GEN_SEG = 32  # generator fairing vertices across its arc
GEN_LAND = 0.015  # its edges this far under the cowl
# The generator's cooling air hood on the fairing's crown: mouth a, length, half width, height. Its section runs round
# from the inboard foot, v = -1 marking the feet HOOD_BURY under the surface; the top corners are small radii.
GEN_HOOD = (1.56, 0.80, 0.20, 0.13)
HOOD_SECTION = ((-1.0, -1.0),) + tuple((math.cos(t), math.sin(t)) for t in np.linspace(math.pi, 0, 17)) + ((1.0, -1.0),)
HOOD_STATIONS = (0.0, 0.08, 0.2, 0.38, 0.58, 0.8, 1.0)  # fractions of its length
HOOD_LIP, HOOD_DUCT, HOOD_BURY = 0.014, 0.12, 0.05
# The nacelle chine on the inboard upper inlet cowl (about 10 o'clock seen from ahead on the left engine): a, theta,
# height, root and tip chord, sweep, thickness (of chord).
STRAKE = (1.02, -60.0, 0.30, 1.05, 0.40, 0.62, 0.035)
DRAIN_MASTS = ((3.15, 180.0, 0.14), (5.95, 172.0, 0.10))  # a, theta, height
INLET_PROBE = (0.42, 38.0, 0.13)  # a, theta, height into the intake

# ---------- fan ----------
FAN_BLADES = 22
# Blade sections from the root (inside the hub) to the tip: radius, chord, stagger from the plane of rotation (deg),
# thickness, camber (of chord), sweep aft and lag against the rotation (m). Wide chord, swept, the tip 2.4 cm inside
# the fan case.
BLADE = ((0.50, 0.46, 68.0, 0.066, 0.09, 0.00, 0.00),
         (0.72, 0.54, 57.0, 0.053, 0.085, -0.02, -0.015),
         (0.96, 0.63, 45.0, 0.040, 0.075, -0.055, -0.045),
         (1.22, 0.69, 35.0, 0.030, 0.060, -0.06, -0.04),
         (1.49, 0.70, 28.0, 0.022, 0.045, 0.00, 0.07),
         (1.72, 0.65, 23.0, 0.017, 0.035, 0.12, 0.25),
         (1.865, 0.56, 20.0, 0.014, 0.030, 0.24, 0.43))
BLADE_X = tuple(0.5 * (1 + math.cos(math.pi * k / 8)) for k in range(9))
BLADE_STACK = 0.03
SPINNER = ((0, -0.980), (0.035, -0.966), (0.100, -0.890), (0.200, -0.760), (0.300, -0.620), (0.400, -0.470),
           (0.480, -0.330), (0.550, -0.190), (0.595, -0.060), (0.615, 0.050), (0.618, 0.120), (0.618, 0.400),
           (0.600, 0.440), (0, 0.450))  # a cone, its tip 4 cm behind the intake plane
SPINNER_SEG = 32

# ---------- nozzle (a from the cowl's trailing edge, a = 6.8) ----------
# The saved third-stream collider reaches r 1.150 at a 1.24, inside the nominal profile's r 1.179 shoulder.
# A straight 13.8 deg cone clears it and the core collider's r 0.971 through a 1.90, reaching r 0.99 at a 1.92.
CORE_EXIT = 2.26
CORE = ((0.0, -4.000, "matte"), (1.058, -4.000, "matte"), (1.126, 0.000, "core"),
        (1.235, 0.550, "core"), (1.261, 0.700, "core"), (1.264, 0.800, "core"),
        (0.915, CORE_EXIT - 0.040, "mech"),
        (0.905, CORE_EXIT, "mech"),
        (0.894, CORE_EXIT + 0.012, "matte"), (0.883, CORE_EXIT, "matte"), (0.955, 1.700, "matte"),
        (0.0, 1.700, None))
CORE_TE = next(i for i, c in enumerate(CORE) if c[1] == CORE_EXIT)
CORE_SEG = 64
# A 17.5 deg plug flank continues the converging cowl, with a rounded tip 1.88 m beyond the exit.
PLUG = ((0.0, 1.550), (0.665, 1.550), (0.670, 1.920), (0.660, 2.030),
        (0.044, 3.985), (0.020, 4.060), (0.006, 4.105), (0.0, 4.140))
PLUG_SEG = 48

# ---------- pylon (stations) ----------
PYLON_NOSE, PYLON_TAIL = 15.30, 24.53  # the tail 2 cm short of the wing's trailing edge (24.55 at the pylon)
PYLON_STATIONS = (15.36, 15.50, 15.75, 16.05, 16.40, 17.00, 17.15, 17.20, 17.42, 17.55, 17.75, 18.05, 18.18, 18.32, 18.45,
                  20.55, 20.95, 21.10, 21.30, 21.55, 21.80, 22.20, 22.32, 22.45, 22.58,
                  22.72, 22.86, 23.00, 23.16, 23.32, 23.50, 23.70, 23.92, 24.16, 24.34, 24.44, 24.51)
# The aft fairing's heat shield leaves the core cowl's crown over its shoulder and rises in one S-curve over these
# stations, tangent to the crown and to the wing's lower skin, closing at the trailing edge's height; the canoe between
# flaps 1 and 2 is its tail.
CANOE_LIFT = (22.20, PYLON_TAIL)
CORE_FILLET_FADE = (21.80, 22.95)  # the fillet fades before the lifted keel clears the core
PYLON_CREST_DROP = -0.03  # the crest runs into the leading edge's nose this far over its stagnation line
CREST_BURY = 0.10  # the crest's centre this far behind the leading edge is 8 cm or more inside the nose
# The forward fairing's keel this far under the cowl's crown, so its sides meet the cowl near full width and cover the
# blockout's collider, whose side kink sits low under step 6.1's clamped top (10 cm into the wing); never closer than
# 2 cm to the bypass duct, where it would show inside the intake and cut the fan.
PYLON_KEEL = 0.30
# Its top runs this far into the wing under the cowl (the blockout's step 6.1 clamp), since the stages slide over it
# inside the wing; aft of the cowl, 7 cm.
PYLON_TOP_IN = 0.10
PYLON_HALF = ((15.30, 0.0), (15.36, 0.06), (15.50, 0.12), (15.75, 0.18), (16.05, 0.23), (16.40, 0.28), (16.80, 0.30),
              (17.30, 0.33), (17.80, 0.35), (18.40, 0.36), (22.20, 0.36), (22.40, 0.31), (22.56, 0.27), (22.90, 0.23),
              (23.32, 0.19), (23.70, 0.145), (23.92, 0.10), (24.16, 0.055), (24.34, 0.028),
              (24.44, 0.013), (24.51, 0.003), (24.53, 0.0))
PYLON_P = 2.0  # rounded crest and keel shoulders
PYLON_CREST = (0.22, 0.12)  # height of the crest's shoulders under the leading edge, and once inside the wing
PYLON_KEEL_ROUND = (0.18, 0.32)  # height of the keel's shoulders inside the cowls, and where the tail lifts off the core
# Fillets (rule 9): circular arcs tangent to the pylon's side and to the wing's lower skin, the fan cowl and sleeve, or
# the core cowl, the arc's end FILLET_LAND inside the neighbour so it lands a few degrees into its facets along one
# line instead of grazing them. Each grows from nothing where the pylon first meets its neighbour (over FILLET_GROW of
# depth) and together they leave at least 3 cm of straight side between the cowl and the wing.
FILLET_WING, FILLET_COWL, FILLET_CORE, FILLET_MIN, FILLET_LAND = 0.20, 0.14, 0.10, 0.015, 0.008
FILLET_GROW = 0.08
FILLET_SINK = 0.03  # hidden section points inside a neighbour at least this deep, never close and parallel to its skin
FILLET_N, SIDE_N, COWL_N = 3, 4, 2  # arc points inside each wing and cowl fillet; side points between the fillets
# The wing's lower skin under the pylon and its fillets: half width by station. The flaps sit either side of the aft
# fairing from station 22.1, so the wing fillet narrows to the blockout's 0.36 there; the wing keeps this skin plain.
PYLON_FOOTPRINT = ((15.0, 0.58), (21.30, 0.58), (21.80, 0.36), (23.0, 0.36))


def footprint(s):
    return float(np.interp(s, *zip(*PYLON_FOOTPRINT)))


def outer_r(a):
    return float(np.interp(a, OUTER_A, OUTER_R))


def cowl_chord_radius(radius, theta):
    """Radius on the faceted cowl, shared by the blister landing and its sealant paint."""
    half_step = math.pi / SEG
    facet_angle = np.radians(theta) % (2 * half_step) - half_step
    return radius * math.cos(half_step) / np.cos(facet_angle)


def inner_r(a):
    return float(np.interp(a, INNER_A, INNER_R))


def core_r(a):
    """The core cowl's outer radius at a (from the intake plane)."""
    pts = [(r, ar + 6.8) for r, ar, _ in CORE[1:CORE_TE + 1]]
    return float(np.interp(a, [p[1] for p in pts], [p[0] for p in pts]))


def axis_point(origin, r, a, deg):
    t = math.radians(deg)
    return origin + Vector((r * math.sin(t), a, r * math.cos(t)))


def radial(deg):
    t = math.radians(deg)
    return Vector((math.sin(t), 0, math.cos(t)))


def revolve(part, origin, profile, seg, tags, loop=False, shape=None, seams=(), ring_seams=(), phase=0.0):
    """Spin (r, a) points about the engine axis (+Y through origin; vertex 0 on top, angles growing toward +X).
    tags[i] is (slot, cls) for the band from point i to the next. With loop the last band closes back to point 0;
    otherwise a zero radius at an end makes a pole, and any other end is capped flat in its band's tag.
    shape(i, k, r, a) may move ring vertices. phase turns the ring (degrees). Returns the vertex rings."""
    bm = part.bm
    pts = list(profile)
    first = 1 if not loop and pts[0][0] == 0 else 0
    stop = len(pts) - 1 if not loop and pts[-1][0] == 0 else len(pts)
    rings = []
    for i in range(first, stop):
        r, a = pts[i]
        rings.append([axis_point(origin, *(shape(i, k, r, a) if shape else (r, a)), phase + 360.0 * k / seg)
                      for k in range(seg)])
    g = sf.Grid(bm, rings, loop=True)
    V, n = g.V, len(rings)
    for ri in range(n - 1):
        part.tag([g.F[ri, k] for k in range(seg)], *tags[ri + first])
    for k in seams:
        g.seam_column(k)
    for i in ring_seams:
        g.seam_ring(i - first)
    if loop:
        part.tag([bm.faces.new((V[n - 1][k], V[n - 1][(k + 1) % seg], V[0][(k + 1) % seg], V[0][k])) for k in range(seg)],
                 *tags[n - 1])
        for k in seams:
            sf.seam(bm, V[n - 1][k], V[0][k])
        return V
    for ring, is_first in ((V[0], True), (V[-1], False)):
        pole = first if is_first else stop < len(pts)
        tag = tags[0] if is_first else tags[len(pts) - 2]
        if pole:
            p = bm.verts.new(origin + Vector((0, pts[0 if is_first else -1][1], 0)))
            fan = [bm.faces.new((ring[(k + 1) % seg], ring[k], p) if is_first else (ring[k], ring[(k + 1) % seg], p))
                   for k in range(seg)]
            part.tag(fan, *tag)
            for k in seams:
                sf.seam(bm, ring[k], p)
        else:
            part.tag(sf.cap(bm, ring[::-1] if is_first else ring), *tag)
    return V


def mirror_x(part):
    """The right-hand engine: the left one's vertices mirrored, so faces keep their order and twins share islands."""
    for v in part.bm.verts:
        v.co.x = -v.co.x


class CowlSurface:
    """The outer cowl as a surface in (a, theta), duck-typed like surface.Fuselage for surface_patch."""

    def __init__(self, origin):
        self.o = origin

    def point(self, a, deg, off=0.0):
        return axis_point(self.o, outer_r(a) + off, a, deg)

    def normal(self, a, deg):
        da = 0.02
        slope = (outer_r(a + da) - outer_r(a - da)) / (2 * da)
        return (radial(deg) - Vector((0, slope, 0))).normalized()


class GeneratorSurface:
    """The generator fairing as a surface in (a, phi), phi from 0 (outboard foot) to 180 (inboard foot): a blister
    standing off the cowl by its height times a bell across (flat-crowned, its flanks running tangent into the cowl)
    and a profile along (a rounded nose rising tangent off the cowl, a long taper aft). Its edges sit GEN_LAND under
    the cowl, so it lands a few degrees into it along one line (rule 9)."""

    def __init__(self, origin):
        self.o = origin
        self.th, self.a0, self.a1, self.w, self.h = GENERATOR

    def bulge(self, a):
        u = (a - self.a0) / (self.a1 - self.a0)
        if u <= 0 or u >= 1:
            return 0.0
        t = min(1.0, u / 0.16)
        nose = 0.5 * (1 - math.cos(math.pi * t))
        t = min(1.0, (1 - u) / 0.5)
        return nose * 0.5 * (1 - math.cos(math.pi * t))

    def point(self, a, phi, off=0.0):
        u = math.cos(math.radians(phi))
        bell = max(1 - abs(u) ** 2.5, 0.0) ** 1.2
        # Bury the last ring 2 cm, so the shallow tail cannot graze successive cowl facets.
        tail_sink = 0.020 * max(0.0, min(1.0, (a - (self.a1 - 0.15)) / 0.15))
        rise = self.h * self.bulge(a) * bell - GEN_LAND - tail_sink
        radius = outer_r(a)
        theta = self.th + math.degrees(0.5 * self.w * u / radius)
        # Land on the cowl's chords; an analytic circle crosses each facet along the shallow aft taper.
        radius = cowl_chord_radius(radius, theta)
        p = axis_point(self.o, radius + rise, a, theta)
        return p + self.normal(a, phi) * off if off else p

    def normal(self, a, phi):
        da, dp = 0.01, 1.0
        u = self.point(a + da, phi) - self.point(a - da, phi)
        v = self.point(a, phi + dp) - self.point(a, phi - dp)
        n = u.cross(v).normalized()
        c = self.o + Vector((0, a, 0))
        return n if n.dot(self.point(a, phi) - c) > 0 else -n


# ---------- build ----------
def build(bl, surf, slots):
    SKIN, STRUCT, _, MECH = slots[:4]
    tags = {"lip": (SKIN, LIP), "cowl": (SKIN, COWL), "sleeve": (SKIN, SLEEVE), "liner": (SKIN, LINER),
            "matte": (STRUCT, 0), "mech": (MECH, 0), "core": (SKIN, CORE_COWL)}
    parts = {}
    num, side, x, front = bl.NACELLES[0]
    origin = Vector((x, bl.st(front), bl.NACELLE_Z))
    strut = strut_crossings(bl, origin)
    for num, side, x, front in bl.NACELLES:
        p = parts[f"nacelle_{num}"] = sf.Part(f"nacelle_{num}", (SKIN,))
        nacelle(bl, p, origin, tags, strut, slots)
        q = parts[f"pylon_{num}"] = sf.Part(f"pylon_{num}", (SKIN,))
        pylon(bl, q, origin, front, slots)
        z = parts[f"nozzle_{num}"] = sf.Part(f"nozzle_{num}", (MECH,))
        nozzle(bl, z, origin, tags, strut, slots)
        if side < 0:
            for part in (p, q, z):
                mirror_x(part)
        f = parts[f"fan_{num}"] = sf.Part(f"fan_{num}", (MECH,))
        fan(f, Vector((side * x, bl.st(front) + FAN_A, bl.NACELLE_Z)), MECH)
    return parts


def nacelle(bl, p, origin, tags, strut, slots):
    SKIN, STRUCT, _, MECH = slots[:4]
    nacelle_wall(p, origin, tags)
    # behind the fan: the core inlet's hub wall, the splitter, the outlet guide vanes
    revolve(p, origin, CORE_HUB, 32, [(STRUCT, 0)] * (len(CORE_HUB) - 1))
    revolve(p, origin, [(r, a) for r, a, _ in SPLITTER], SPLITTER_SEG, [tags[b] for _, _, b in SPLITTER], loop=True)
    ogvs(bl, p, origin, MECH)
    for d, toward in strut["wall"]:  # inside the duct, out of every view: the coarser section
        strut_fillet(bl, p, origin, inner_r, d, toward, free=-1, slot=STRUCT, n=4)
    generator(p, origin, SKIN, STRUCT, MECH)
    a, t, h, c0, c1, sweep, thick = STRAKE
    base = axis_point(origin, outer_r(a), a, t)
    sf.blade(p, base, radial(t), Vector((0, -1, 0)), h, c0, c1, sweep, thick, SKIN, FITTING, npts=8)
    for a, t, h in DRAIN_MASTS:
        base = axis_point(origin, outer_r(a), a, t)
        sf.blade(p, base, radial(t), Vector((0, -1, 0)), h, 0.15, 0.07, 0.07, 0.14, SKIN, FITTING)
    a, t, h = INLET_PROBE
    base = axis_point(origin, float(np.interp(a, INNER_A, INNER_R)), a, t)
    sf.blade(p, base, -radial(t), Vector((0, -1, 0)), h, 0.07, 0.04, 0.03, 0.18, MECH, 0)


def nacelle_wall(p, origin, tags):
    """Keep 64 points on the lip and exterior, 32 on the enclosed dark duct."""
    bm = p.bm
    rings = []
    for r, a, band, _ in WALL:
        count = SEG // 2 if band in ("matte", "mech") and a < FAN_NOZZLE_TE else SEG
        rings.append([bm.verts.new(axis_point(origin, r, a, 360.0 * k / count)) for k in range(count)])
    for i, ra in enumerate(rings):
        rb = rings[(i + 1) % len(rings)]
        faces = []
        if len(ra) == len(rb):
            faces = [bm.faces.new((ra[k], ra[(k + 1) % len(ra)], rb[(k + 1) % len(rb)], rb[k]))
                     for k in range(len(ra))]
        else:
            dense, coarse = (ra, rb) if len(ra) > len(rb) else (rb, ra)
            for k in range(len(coarse)):
                a, b, c = dense[2 * k], dense[2 * k + 1], dense[(2 * k + 2) % len(dense)]
                d, e = coarse[k], coarse[(k + 1) % len(coarse)]
                for verts in ((a, b, d), (b, e, d), (b, c, e)):
                    faces.append(bm.faces.new(verts if dense is ra else verts[::-1]))
        p.tag(faces, *tags[WALL[i][2]])
        for k in (0, 1):
            sf.seam(bm, ra[k * len(ra) // 2], rb[k * len(rb) // 2])
        if WALL[i][3]:
            for k in range(len(ra)):
                sf.seam(bm, ra[k], ra[(k + 1) % len(ra)])


def ogvs(bl, p, origin, slot):
    """Outlet guide vanes across the bypass duct behind the fan: thin cambered vanes leaning with the swirl."""
    count, a_le, chord, r0, r1, turn = OGV
    for i in range(count):
        th = 360.0 * (i + 0.5) / count
        rings = []
        for r, lean in ((r0, 0.0), (r1, 0.10)):
            n_r = radial(th + 6.0 * (r - r0) / (r1 - r0))
            tang = Vector((0, 1, 0)).cross(n_r).normalized()
            cd = (Vector((0, 1, 0)) * math.cos(math.radians(turn)) + tang * math.sin(math.radians(turn))).normalized()
            td = n_r.cross(cd).normalized()
            le = origin + Vector((0, a_le + lean, 0)) + n_r * r
            rings.append(bl.airfoil(le, chord, 0.030, cd, td, 0.10, n=3, te=0.004))
        g = sf.Grid(p.bm, rings, loop=True)
        p.tag(g.faces() + sf.cap(p.bm, g.V[0][::-1]) + sf.cap(p.bm, g.V[-1]), slot)


def generator(p, origin, SKIN, STRUCT, MECH):
    """The integrated drive generator's fairing on the lower inboard fan cowl: a long blister rising from an
    elliptical nose, a ram hood on its crown, tapering aft before the reverser step."""
    gs = GeneratorSurface(origin)
    th, a0, a1, w, h = GENERATOR
    # The flat crown needs no intermediate rings; concentrate them where the aft landing curves.
    stations = tuple(np.linspace(a0, a0 + 0.37, 7)) + (a0 + 1.2, a0 + 1.55, a0 + 1.72, a0 + 1.92,
                                                     a0 + 2.1, a1 - 0.15, a1 - 0.10, a1 - 0.05, a1)
    m = GEN_SEG
    rings = []
    for a in stations:
        ring = [gs.point(a, 180.0 * i / m) for i in range(m + 1)]
        rings.append(ring)
    g = sf.Grid(p.bm, rings, loop=True)  # the base chord closes the arc inside the cowl wall
    p.tag([g.F[r, k] for r in range(len(stations) - 1) for k in range(m)], SKIN, GEN)
    p.tag([g.F[r, m] for r in range(len(stations) - 1)] + sf.cap(p.bm, g.V[0][::-1]) + sf.cap(p.bm, g.V[-1]), STRUCT)
    g.seam_column(0)
    g.seam_column(m)
    ram_hood(p, gs, *GEN_HOOD, SKIN, STRUCT)


def ram_hood(p, surf, a0, length, half, height, SKIN, STRUCT):
    """A ram air hood on the crown (phi 90) of a surface in (a, phi): a rounded scoop section, its
    front lip round a dark duct running 12 cm aft, the hood easing down to flush at a0 + length. The walls'
    feet sit HOOD_BURY under the surface. One closed shell: duct end, lip, outer skin, tail."""
    lip, depth = HOOD_LIP, HOOD_DUCT

    def frame(a):
        c, n = surf.point(a, 90.0), surf.normal(a, 90.0)
        t = (surf.point(a, 91.0) - surf.point(a, 89.0)).normalized()
        return c, n, t

    def ring(a, w, hgt, scale=1.0, sink=0.0, feet=HOOD_BURY):
        c, n, t = frame(a)
        return [c + t * (u * w * scale) + n * (-feet if v < 0 else v * hgt * scale - sink) for u, v in HOOD_SECTION]

    # the duct's floor stands 2 cm over the hood's buried bottom, so the shell never touches itself
    rings = [ring(a0 + depth, half - lip, height - lip, 0.7, feet=HOOD_BURY - 0.02),
             ring(a0 + lip, half - lip, height - lip, feet=HOOD_BURY - 0.02),
             ring(a0, half - lip / 2, height - lip / 2, feet=HOOD_BURY - 0.01)]
    for t in HOOD_STATIONS:
        # the section keeps 3 cm of height, sunk as the hood eases down, so the tail cap never degenerates
        f = 1.0 - (lambda x: x * x * (3 - 2 * x))(min(1.0, max(0.0, (t - 0.12) / 0.88)))
        hgt = max(height * f, 0.03)
        sink = hgt - height * f - 0.004 if hgt > height * f else 0.0
        rings.append(ring(a0 + length * t, half * (1 - 0.3 * t), hgt, sink=sink))
    g = sf.Grid(p.bm, rings, loop=True)
    n = len(HOOD_SECTION)
    p.tag([g.F[0, k] for k in range(n)] + sf.cap(p.bm, g.V[0][::-1]), STRUCT)
    p.tag([g.F[r, k] for r in range(1, len(rings) - 1) for k in range(n)] + sf.cap(p.bm, g.V[-1]), SKIN, GEN)
    g.seam_ring(1)
    g.seam_ring(2)
    g.seam_column(0)


def strut_crossings(bl, origin):
    """Where the strut line crosses the duct wall and the core cowl, as (distance from the strut root, the direction
    along the line toward the duct's free side)."""
    root, hub, node = bl.s6_strut_line(1)
    ax = (node - root).normalized()
    length = (node - root).length

    def excess(d, fn):
        q = root + ax * d
        a = q.y - origin.y
        return math.hypot(q.x - origin.x, q.z - origin.z) - fn(a)

    out = {}
    for key, fn, free in (("wall", inner_r, -1), ("core", core_r, 1)):
        ds = [length * i / 800 for i in range(801)]
        found = []
        for d0, d1 in zip(ds, ds[1:]):
            a0 = (root + ax * d0).y - origin.y
            if not 0.5 < a0 < 7.9:
                continue
            e0, e1 = excess(d0, fn), excess(d1, fn)
            if (e0 > 0) != (e1 > 0):
                for _ in range(40):
                    m = (d0 + d1) / 2
                    if (excess(m, fn) > 0) == (e0 > 0):
                        d0 = m
                    else:
                        d1 = m
                d = (d0 + d1) / 2
                g = excess(d + 0.05, fn) - excess(d - 0.05, fn)
                found.append((d, free * (1 if g > 0 else -1)))
        out[key] = found
    out["root"], out["ax"] = root, ax
    return out


def strut_fillet(bl, p, origin, radius_fn, d_cross, toward, free, slot, n=6):
    """A fillet where the strut crosses a revolved surface of the duct: rings of the strut's section, thickened, whose
    every point is slid along the strut onto the surface (the foot, 3 cm under it, and the edge on it), then two rings
    climbing the strut and closing onto it. free: +1 where the free side is outside the surface (the core cowl),
    -1 inside it (the duct wall)."""
    root, hub, node = bl.s6_strut_line(1)
    ax = (node - root).normalized()
    ch, th = bl.S6_STRUT["chord"], bl.S6_STRUT["thick"]
    cd = (Vector((0, 1, 0)) - ax * ax.y).normalized()
    td = ax.cross(cd).normalized()

    def offsets(kc, kt):
        return [q - cd * (0.4 * ch * kc) for q in bl.airfoil(Vector(), ch * kc, th * kt, cd, td, n=n, te=0.01)]

    def excess(q):
        a = q.y - origin.y
        return math.hypot(q.x - origin.x, q.z - origin.z) - radius_fn(a)

    def foot(o, target):
        f = lambda d: excess(root + ax * d + o) - target
        lo, hi = d_cross - 1.2, d_cross + 1.2
        ds = [lo + (hi - lo) * i / 96 for i in range(97)]
        best = None
        for d0, d1 in zip(ds, ds[1:]):
            if (f(d0) > 0) != (f(d1) > 0) and (best is None or abs(d0 - d_cross) < abs(best[0] - d_cross)):
                best = (d0, d1)
        if best is None:
            return d_cross
        d0, d1 = best
        for _ in range(36):
            m = (d0 + d1) / 2
            d0, d1 = (m, d1) if (f(m) > 0) == (f(d0) > 0) else (d0, m)
        return (d0 + d1) / 2

    rings = []
    for kc, kt, rise, target in ((1.03, 1.60, 0.0, -free * 0.03), (1.03, 1.60, 0.0, 0.0), (1.02, 1.46, 0.025, None),
                                 (1.0, 1.22, 0.10, None), (0.97, 0.95, 0.22, None)):
        ring = []
        for o0, o in zip(offsets(1.0, 1.0), offsets(kc, kt)):
            d = foot(o0, 0.0)
            if target is not None:
                d = foot(o, target)
            ring.append(root + ax * (d + toward * rise) + o)
        rings.append(ring)
    g = sf.Grid(p.bm, rings, loop=True)
    g.seam_column(0)
    p.tag(g.faces() + sf.cap(p.bm, g.V[0][::-1]) + sf.cap(p.bm, g.V[-1]), slot)


def fan(p, centre, mech):
    revolve(p, centre, SPINNER, SPINNER_SEG, [(mech, 0)] * (len(SPINNER) - 1))
    for b in range(FAN_BLADES):
        theta = 2 * math.pi * (b + 0.5) / FAN_BLADES
        rings = [[p.bm.verts.new(v) for v in blade_section(centre, theta, *sec, xs=BLADE_X[::2] if sec[0] < 0.8 else BLADE_X)]
                 for sec in BLADE]
        faces = []
        for ra, rb in zip(rings, rings[1:]):
            i, j = 0, 0
            while i < len(ra) - 1 or j < len(rb) - 1:
                ta, tb = (i + 1) / (len(ra) - 1), (j + 1) / (len(rb) - 1)
                if abs(ta - tb) < 1e-6:
                    faces.append(p.bm.faces.new((ra[i], ra[i + 1], rb[j + 1], rb[j])))
                    i, j = i + 1, j + 1
                elif ta < tb:
                    faces.append(p.bm.faces.new((ra[i], ra[i + 1], rb[j])))
                    i += 1
                else:
                    faces.append(p.bm.faces.new((ra[i], rb[j + 1], rb[j])))
                    j += 1
            faces.append(p.bm.faces.new((ra[-1], ra[0], rb[0], rb[-1])))
        p.tag(faces + sf.cap(p.bm, rings[0][::-1]) + sf.cap(p.bm, rings[-1]), mech)


def blade_section(centre, theta, r, chord, stagger, thick, camber, sweep, lag, xs=BLADE_X):
    """One blade section on the cylinder of radius r: upper side from the trailing to the leading edge, lower side
    back. Chord-wise u runs aft and against the rotation; points are wrapped onto the cylinder so the tip follows the
    fan case."""
    b = math.radians(stagger)
    cb, sb = math.cos(b), math.sin(b)
    out = []
    for upper, side_xs in ((True, xs), (False, xs[-2::-1])):
        for x in side_xs:
            yt = max(5 * thick * (0.2969 * math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1015 * x ** 4), 0.0015)
            v = camber * chord * 4 * x * (1 - x) + (yt if upper else -yt)
            u = (x - 0.5) * chord
            tang = lag + u * cb - v * sb
            axial = BLADE_STACK + sweep + u * sb + v * cb
            phi = theta + tang / r
            out.append(centre + Vector((r * math.sin(phi), axial, r * math.cos(phi))))
    return out


def nozzle(bl, p, origin, tags, strut, slots):
    SKIN, STRUCT, _, MECH = slots[:4]
    rear = origin + Vector((0, 6.8, 0))
    revolve(p, rear, [(r, a) for r, a, _ in CORE], CORE_SEG, [tags[b] for _, _, b in CORE[:-1]],
            seams=(0, CORE_SEG // 2))
    revolve(p, rear, PLUG, PLUG_SEG, [(MECH, 0)] * (len(PLUG) - 1))
    for d, toward in strut["core"]:
        strut_fillet(bl, p, origin, core_r, d, toward, free=1, slot=STRUCT, n=12)


def pylon(bl, p, origin, front, slots):
    """Sections from the inlet cowl's crown into the wing's leading edge and lower skin, then the aft fairing dropping
    behind the cowl's trailing edge onto the core cowl and closing up under the wing. Each section is the bare pylon
    (superellipse crest and keel shoulders on straight sides) with circular fillets turning it into the wing and into
    the fan cowl, sleeve or core cowl wherever it meets them (pylon_section). Built on the left. Faces sealed in the
    nacelle, the core or the wing take aircraft_structure (bury_hidden_skin finishes the job), the aft fairing's lower
    half the satin metal heat shield."""
    SKIN, STRUCT, _, MECH = slots[:4]
    Z, X = bl.NACELLE_Z, origin.x
    le, chord, thick = bl.wing_le(1, X)
    le_st = le.y + bl.Y0
    te_st = front + 6.8

    def crown(s):
        return Z + outer_r(s - front)

    def wing_z(x, s):
        return bl.wing_lower(1, x, s).z

    def wing_thick(s):
        frac = min(max((s - le_st) / chord, 0.0), 1.0)
        return bl.airfoil_point(le, chord, thick, bl.CDIR, bl.TDIR, bl.WING_CAMBER, frac, True).z - wing_z(X, s)

    z0, zle = crown(PYLON_NOSE), le.z - PYLON_CREST_DROP  # no lower: the blockout's forward collider

    def top(s):
        if s < le_st:
            u = (s - PYLON_NOSE) / (le_st - PYLON_NOSE)
            return z0 + (zle - z0) * (1 - (1 - u) ** 1.8)
        # at the nose's height until the lower skin drops past it, then 10 cm into the wing (7 cm aft of the cowl); the
        # swept nose reaches the outboard side last, so the crest holds its height until the nose is over all of it.
        # Toward the trailing edge the wing thins, so the canoe's top stays under its middle.
        out = wing_z(X + float(np.interp(s, *zip(*PYLON_HALF))), s)
        if s < te_st:
            return min(zle, max(wing_z(X, s), out) + PYLON_TOP_IN)
        return wing_z(X, s) + min(0.07, 0.45 * wing_thick(s))

    def bottom(s):
        if s <= te_st - 0.15:
            return max(crown(s) - PYLON_KEEL, Z + inner_r(s - front) + 0.02)
        # 12 cm into the core cowl, so the rounded underside still covers the blockout's flat one; then the heat shield
        # (under the blockout's collider) leaves the cowl as it boat-tails away and rises into the canoe, which runs aft
        # under the wing between flaps 1 and 2 and closes at the trailing edge's height
        core = Z + core_r(s - front) - 0.12
        return core + (wing_z(X, s) - core) * ease(*CANOE_LIFT, s)

    rings = []
    for s in PYLON_STATIONS:
        a = s - front
        cowl = s <= te_st - 0.15
        floor = Circle(Z, outer_r(a) if cowl else core_r(a))
        zt, zk, hb = top(s), bottom(s), float(np.interp(s, *zip(*PYLON_HALF)))
        # planned radii, capped by the room between the floor and the wing (or the crest, ahead of the wing)
        rw = FILLET_WING + (0.12 - FILLET_WING) * ease(21.3, 21.8, s) - 0.04 * ease(*CANOE_LIFT, s)  # 8 cm on the canoe
        rb = (FILLET_COWL * ease(15.3, 15.8, s) * (1 - ease(20.3, 20.95, s)) if cowl
              else FILLET_CORE * ease(21.2, 21.6, s) * (1 - ease(*CORE_FILLET_FADE, s)))
        zf = floor.zc + math.sqrt(max(floor.R ** 2 - hb * hb, 0.0))
        room = min(min(zt, wing_z(X - hb, s), wing_z(X + hb, s)) - zf - 0.03, 2.0)
        if not cowl:  # the canoe's fillets no deeper than its side
            room = min(room, min(wing_z(X - hb, s), wing_z(X + hb, s)) - zk)
        free = zt < min(wing_z(X - hb, s), wing_z(X + hb, s))  # the crest clear of the wing: no wing fillet
        rw, rb = max(min(rw, 0.58 * room), FILLET_MIN), max(min(rb, (0.75 if free else 0.42) * room), FILLET_MIN)
        # the side kneed in near the top where the wing fillet must land inside the footprint
        ht = min(hb, footprint(s) - rw - 0.08)  # the landing's overrun stays inside the footprint too
        rv = float(np.interp(s, (le_st, le_st + 0.7), PYLON_CREST))
        rk = float(np.interp(s, (22.0, 22.4), PYLON_KEEL_ROUND))
        rv, rk = min(rv, 0.45 * (zt - zk)), min(rk, 0.35 * (zt - zk))
        knee = max(zk + rk, zt - rv - 0.42)
        outline = pylon_outline(zt, zk, hb, ht, rv, rk, knee)
        # Hold the bare crest through the wing's rounded nose; an early fillet curls around its steep lower skin.
        # Start 0.4 m past the buried nose landing and grow over the next 0.6 m.
        halves = []
        for sg in (1, -1):
            start = max(bl.wing_le(1, X + sg * (hb + rw))[0].y + bl.Y0 + 0.05, le_st + CREST_BURY) + 0.4
            halves.append(pylon_section(outline, Ceiling(lambda w, sg=sg: wing_z(X + sg * w, s)),
                                        rw, floor, rb, ease(start, start + 0.6, s),
                                        1.0 if cowl else 1 - ease(*CORE_FILLET_FADE, s)))
        y = bl.st(s)
        out = [Vector((X, y, zt))] + [Vector((X + w, y, z)) for w, z in halves[0]] + [Vector((X, y, zk))]
        rings.append(out + [Vector((X - w, y, z)) for w, z in reversed(halves[1])])
    bm = p.bm
    g = sf.Grid(bm, rings, loop=True)
    nose = bm.verts.new(Vector((X, bl.st(PYLON_NOSE), crown(PYLON_NOSE) - 0.03)))
    tail = bm.verts.new(Vector((X, bl.st(PYLON_TAIL), wing_z(X, PYLON_TAIL) + 0.005)))
    n = len(rings[0])
    faces = g.faces()
    faces += [bm.faces.new((g.V[0][(k + 1) % n], g.V[0][k], nose)) for k in range(n)]
    tail_fan = [bm.faces.new((g.V[-1][k], g.V[-1][(k + 1) % n], tail)) for k in range(n)]
    faces += tail_fan
    # the heat shield: aft of the cowl, the lower half of each side from its middle side point down, on whole columns
    # so its edge runs along the section points
    low = lambda k: min(k, n - 1 - k) >= 1 + FILLET_N + 4 + SIDE_N // 2
    heat = {g.F[r, k] for r, st_ in enumerate(PYLON_STATIONS[:-1]) if st_ > te_st for k in range(n) if low(k)}
    heat |= {f for k, f in enumerate(tail_fan) if low(k)}
    for k in (0, n // 2):
        g.seam_column(k)
        sf.seam(bm, g.V[0][k], nose)
        sf.seam(bm, g.V[-1][k], tail)
    y0 = origin.y

    def sealed(v):
        a, s = v.co.y - y0, v.co.y + bl.Y0
        r = math.hypot(v.co.x - X, v.co.z - Z)
        in_nacelle = -0.02 < a < FAN_NOZZLE_TE and r < outer_r(a) - 0.004
        in_core = a > 6.8 and r < core_r(a) - 0.004
        in_wing = s > bl.wing_le(1, v.co.x)[0].y + bl.Y0 + 0.02 and v.co.z > wing_z(v.co.x, s) + 0.004
        return in_nacelle or in_core, in_wing

    for f in faces:
        state = [sealed(v) for v in f.verts]
        if all(st[0] for st in state) or all(st[1] for st in state):
            p.tag([f], STRUCT)
        elif f in heat:
            p.tag([f], SKIN, HEAT_SHIELD)
        else:
            p.tag([f], SKIN, PYLON)


def ease(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def pylon_outline(zt, zk, hb, ht, rv, rk, knee, n=24):
    """One side of the bare pylon section as dense (w, z) points, w out from its centre plane, from the crest's top
    centre to the keel's bottom centre: the crest's superellipse shoulder (half width ht), the side (kneed out to hb
    below the knee height), the keel's shoulder (half width hb)."""
    e = 2 / PYLON_P
    pts = [(ht * math.sin(t) ** e, zt - rv + rv * math.cos(t) ** e) for t in (0.5 * math.pi * i / n for i in range(n + 1))]
    if ht < hb - 1e-4:
        pts.append((hb, knee))
    pts += [(hb * math.cos(t) ** e, zk + rk - rk * math.sin(t) ** e) for t in (0.5 * math.pi * i / n for i in range(n + 1))]
    return pts


class Ceiling:
    """The wing's lower skin over one side of a pylon section: its height z(w) above the point w out from the centre
    plane."""

    def __init__(self, z):
        self.z = z

    def sd(self, w, z):  # positive in the air under the skin
        return self.z(w) - z

    def frame(self, u):
        """The skin's point above w = u, the unit normal into the wing and the tangent away from the pylon."""
        m = (self.z(u + 0.01) - self.z(u - 0.01)) / 0.02
        k = math.hypot(1.0, m)
        return (u, self.z(u)), (-m / k, 1 / k), (1 / k, m / k)


class Circle:
    """A cowl's section about the engine axis at height zc: the fan cowl and sleeve, or the core cowl."""

    def __init__(self, zc, R):
        self.zc, self.R = zc, R

    def sd(self, w, z):  # positive in the air outside the cowl
        return math.hypot(w, z - self.zc) - self.R

    def frame(self, u):
        u = min(max(u, 0.0), 0.95 * self.R)
        n = (u / self.R, math.sqrt(1 - (u / self.R) ** 2))
        return (self.R * n[0], self.zc + self.R * n[1]), (-n[0], -n[1]), (n[1], -n[0])


def polyline_nearest(pts, q):
    """The nearest point on the polyline to q, and its arc length from the polyline's start."""
    best, along, run = None, 0.0, 0.0
    for (ax, az), (bx, bz) in zip(pts, pts[1:]):
        dx, dz = bx - ax, bz - az
        ll = dx * dx + dz * dz
        t = 0.0 if ll < 1e-14 else min(1.0, max(0.0, ((q[0] - ax) * dx + (q[1] - az) * dz) / ll))
        px, pz = ax + dx * t, az + dz * t
        d = math.hypot(q[0] - px, q[1] - pz)
        if best is None or d < best[0]:
            best, along = (d, (px, pz)), run + t * math.sqrt(ll)
        run += math.sqrt(ll)
    return best[0], best[1], along


def polyline_at(pts, s):
    """The point at arc length s along the polyline."""
    for (ax, az), (bx, bz) in zip(pts, pts[1:]):
        ll = math.hypot(bx - ax, bz - az)
        if s <= ll and ll > 0:
            return ax + (bx - ax) * s / ll, az + (bz - az) * s / ll
        s -= ll
    return pts[-1]


def inside_half(pts, q):
    """q inside the section's half bounded by the outline and its centre plane (ray parity)."""
    poly, inside = pts + [pts[0]], False
    for (ax, az), (bx, bz) in zip(poly, poly[1:]):
        if (az > q[1]) != (bz > q[1]) and q[0] < ax + (q[1] - az) * (bx - ax) / (bz - az):
            inside = not inside
    return inside


def end_fillet(outline, nbr, r, n_arc, reach, strength=1.0):
    """The fillet where the outline's end (its first point) runs into a neighbour. Returns the FILLET_N + 4 (or
    COWL_N + 4) section points from the end outward and the arc length along the outline where the fillet leaves it.
    Inside the neighbour: a point between the end and the landing, the landing overrun (3 cm on, 1.5 cm in), the arc's
    end FILLET_LAND in, the arc, its tangent point T on the outline. Blend the same points onto the bare outline as
    the keel leaves the core or the crest enters the wing, so no column jumps when a fillet ends."""
    sd = [nbr.sd(w, z) for w, z in outline]
    count = n_arc + 4
    bare = [polyline_at(outline, reach * k / count) for k in range(1, count + 1)]
    strength *= ease(0.0, FILLET_SINK + 0.08, -min(sd))
    if strength <= 0.0:
        return bare, reach
    r *= max(ease(0.0, FILLET_GROW, -min(sd)), 0.02)
    i = next(i for i in range(len(outline)) if sd[i] > 0)
    t = sd[i - 1] / (sd[i - 1] - sd[i])
    cross = outline[i - 1][0] + (outline[i][0] - outline[i - 1][0]) * t

    def gap(u):
        foot, n_in, _ = nbr.frame(u)
        c = (foot[0] - n_in[0] * r, foot[1] - n_in[1] * r)
        d = polyline_nearest(outline, c)[0]
        return (-d if inside_half(outline, c) else d) - r

    lo, hi = max(cross - r - 0.05, 0.0), cross + 4 * r + 0.1
    for _ in range(48):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if gap(mid) < 0 else (lo, mid)
    foot, n_in, t_out = nbr.frame(hi)
    c = (foot[0] - n_in[0] * r, foot[1] - n_in[1] * r)
    _, tp, s_t = polyline_nearest(outline, c)
    a_t = math.atan2(tp[1] - c[1], tp[0] - c[0])
    a_l = math.atan2(foot[1] - c[1], foot[0] - c[0])
    turn = (a_l - a_t + math.pi) % (2 * math.pi) - math.pi
    arc = [(c[0] + r * math.cos(a_t + turn * f) + n_in[0] * FILLET_LAND * f * f,
            c[1] + r * math.sin(a_t + turn * f) + n_in[1] * FILLET_LAND * f * f)
           for f in (k / (n_arc + 1) for k in range(n_arc, 0, -1))]
    land = (foot[0] + n_in[0] * FILLET_LAND, foot[1] + n_in[1] * FILLET_LAND)
    over = (foot[0] + t_out[0] * 0.03 + n_in[0] * 0.015, foot[1] + t_out[1] * 0.03 + n_in[1] * 0.015)
    mid = ((outline[0][0] + over[0]) / 2, (outline[0][1] + over[1]) / 2)
    if nbr.sd(*mid) > -FILLET_SINK:  # a chord grazing the skin from inside would z-fight it
        f_m, n_m, _ = nbr.frame(mid[0])
        mid = (f_m[0] + n_m[0] * FILLET_SINK, f_m[1] + n_m[1] * FILLET_SINK)
    fillet = [mid, over, land] + arc + [tp]
    return [(b[0] + (f[0] - b[0]) * strength, b[1] + (f[1] - b[1]) * strength)
            for b, f in zip(bare, fillet)], reach + (s_t - reach) * strength


def pylon_section(outline, ceiling, rw, floor, rb, top_strength, bottom_strength):
    """One side of a pylon section, top to bottom between the centre points: the wing fillet,
    SIDE_N points down the bare outline between the fillets (spaced by arc length and turning, so the shoulders keep
    their points), the floor's fillet."""
    run = [0.0]
    for (ax, az), (bx, bz) in zip(outline, outline[1:]):
        run.append(run[-1] + math.hypot(bx - ax, bz - az))
    rev = outline[::-1]
    top_reach_scale = 0.25 + 0.75 * top_strength
    top, s_top = end_fillet(outline, ceiling, rw, FILLET_N, min(0.30, 0.45 * run[-1]) * top_reach_scale, top_strength)
    bot, s_bot = end_fillet(rev, floor, rb, COWL_N, min(0.25, 0.45 * (run[-1] - s_top)), bottom_strength)
    if s_top + s_bot > 0.9 * run[-1]:  # a free crest's points ride at most 0.45 of what the floor's fillet leaves
        top, s_top = end_fillet(outline, ceiling, rw, FILLET_N, min(0.30, 0.45 * (run[-1] - s_bot)) * top_reach_scale, top_strength)
    if 0.0 < top_strength < 1.0:  # a growing fillet's points blend across the corner: any under the wing stay on the side
        top = [polyline_nearest(outline, q)[1] if ceiling.sd(*q) > 0 and inside_half(outline, q) else q for q in top]
    s0, s1 = s_top, run[-1] - s_bot
    # weight: arc length plus a quarter metre a radian of turning
    ang = [math.atan2(bz - az, bx - ax) for (ax, az), (bx, bz) in zip(outline, outline[1:])]
    wt, acc = [0.0], 0.0
    for i in range(1, len(outline)):
        turn = abs((ang[i - 1] - ang[i - 2] + math.pi) % (2 * math.pi) - math.pi) if i >= 2 else 0.0
        acc += (run[i] - run[i - 1]) + 0.25 * turn
        wt.append(acc)
    w0, w1 = float(np.interp(s0, run, wt)), float(np.interp(s1, run, wt))
    side = [polyline_at(outline, float(np.interp(w0 + (w1 - w0) * k / (SIDE_N + 1), wt, run)))
            for k in range(1, SIDE_N + 1)]
    return top + side + bot[::-1]


# ---------- checks ----------
def check(bl, objs):
    """Engine checks on the detailed meshes in the whole scene: no clash with the struts, wing, sponson or body
    (bl.engine_clashes, the strut's mounts excepted), the fan tips inside the fan case, the pylon inside its wing
    footprint, every collider vertex of the engine parts still inside the detailed skin (the colliders stay the
    blockout's), and the right engine the left's mirror."""
    scene = {o.name: o for o in bpy.data.collections["Centurion"].objects}
    res = {}
    clashes = bl.engine_clashes(scene)
    res["engine_clear_of_struts_wing_body"] = {"value": clashes, "pass": not clashes}
    gaps, foot, outside = {}, {}, {}
    for num, side, x, front in bl.NACELLES:
        cx, y0, Z = side * x, bl.st(front), bl.NACELLE_Z
        fv = bl.world_mesh(objs[f"fan_{num}"])[0]
        gaps[f"fan_{num}"] = round(min(inner_r(v.y - y0) - math.hypot(v.x - cx, v.z - Z) for v in fv), 4)
        pv = bl.world_mesh(objs[f"pylon_{num}"])[0]
        inw = [v for v in pv if v.z > bl.wing_lower(1, abs(v.x), v.y + bl.Y0).z - 0.01 and v.y + bl.Y0 > 17.3]
        foot[f"pylon_{num}"] = round(max(abs(abs(v.x) - x) - footprint(v.y + bl.Y0) for v in inw), 4)
        cover = shell_trees(bl, [objs[n] for n in (f"nacelle_{num}", f"nozzle_{num}", f"pylon_{num}")]
                            + [scene["wing_root" + ("_L" if side > 0 else "_R")]])
        for n in (f"nacelle_{num}", f"nozzle_{num}", f"pylon_{num}"):
            for c in objs[n].children:
                if "_colmesh" not in c.name:
                    continue
                bad = [v for v in bl.world_mesh(c)[0] if not any(
                    all(lo[i] - 1e-3 <= v[i] <= hi[i] + 1e-3 for i in range(3)) and bl.inside(v, tree) for tree, lo, hi in cover)]
                if bad:
                    worst = max(min(tree.find_nearest(v)[3] for tree, _, _ in cover) for v in bad)
                    outside[c.name] = {"vertices_outside": len(bad), "worst_m": round(worst, 4)}
    res["fan_tip_clearance"] = {"value": gaps, "limit": "at least 0.015 m inside the fan case", "pass": all(g >= 0.015 for g in gaps.values())}
    res["pylon_wing_footprint"] = {"value": foot, "limit": f"most outside |x| = {bl.NACELLES[0][2]} +- PYLON_FOOTPRINT "
                                   f"{PYLON_FOOTPRINT} by station: at most 0.001 m", "pass": all(d <= 1e-3 for d in foot.values())}
    res["colliders_inside_skin"] = {"value": outside, "pass": not outside}
    dev = {}
    for kind in ("nacelle", "nozzle", "pylon"):
        a, b = (np.array([tuple(v) for v in bl.world_mesh(objs[f"{kind}_{n}"])[0]]) for n in (1, 2))
        dev[kind] = round(float(np.abs(a * np.array([-1, 1, 1]) - b).max()), 5) if a.shape == b.shape else "face counts differ"
    res["right_engine_mirrors_left"] = {"value": dev, "pass": all(isinstance(d, float) and d < 1e-4 for d in dev.values())}
    return res


def shell_trees(bl, objs):
    """A BVH tree and bounds per closed shell of the objects, so a point's inside test (ray parity) is per shell and
    overlapping shells (a fillet on the core cowl, the plug through the core nozzle's floor) cannot cancel each other."""
    out = []
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        seen = set()
        for f in bm.faces:
            if f.index in seen:
                continue
            comp, stack = [], [f]
            seen.add(f.index)
            while stack:
                g = stack.pop()
                comp.append(g)
                for e in g.edges:
                    for h in e.link_faces:
                        if h.index not in seen:
                            seen.add(h.index)
                            stack.append(h)
            vs = sorted({v.index for g in comp for v in g.verts})
            idx = {vi: k for k, vi in enumerate(vs)}
            bm.verts.ensure_lookup_table()
            co = [bm.verts[vi].co.copy() for vi in vs]
            tree = BVHTree.FromPolygons(co, [tuple(idx[v.index] for v in g.verts) for g in comp])
            out.append((tree, [min(c[i] for c in co) for i in range(3)], [max(c[i] for c in co) for i in range(3)]))
        bm.free()
    return out


# ---------- paint layout ----------
# Nacelle positions are (a, theta) as the geometry's, theta positive outboard; a side of 0 paints both sides, +1
# outboard only, -1 inboard only.
JOINTS = ((0.60, 0.020, 2), (1.55, 0.016, 2), (3.60, 0.016, 1))  # a, groove width, fastener rows
HINGE_LINE, LATCH_LINE = 17.0, 180.0  # |theta| of the fan cowl and sleeve hinges beside the pylon, and the latch split
SPLITS = ((HINGE_LINE, 1.55, FAN_NOZZLE_TE), (LATCH_LINE, 1.55, FAN_NOZZLE_TE))  # |theta|, a from, to
PANELS = (  # a from, to, theta from, to, corner radius, side
    (2.05, 2.55, 70.0, 88.0, 0.05, 1),  # oil service door
    (1.95, 2.40, 68.0, 86.0, 0.05, -1),  # starter air valve access
    (2.75, 3.25, 136.0, 154.0, 0.04, 1),  # pressure relief doors
    (2.70, 3.05, 100.0, 112.0, 0.03, 1),
    (4.05, 4.50, 32.0, 58.0, 0.05, 0),  # reverser actuator access
    (5.15, 5.50, 150.0, 162.0, 0.04, 0),  # reverser lockout
    (0.95, 1.30, 50.0, 66.0, 0.03, 1),  # inlet probe access
    (1.10, 1.35, 158.0, 172.0, 0.03, 0),  # inlet drain door
    (1.75, 2.00, 28.0, 40.0, 0.03, 0),
    (4.70, 5.00, 118.0, 130.0, 0.03, -1),
    (4.75, 5.35, 28.0, 48.0, 0.05, 0),  # sleeve: reverser control access, upper
    (5.85, 6.25, 112.0, 128.0, 0.04, 0),  # sleeve: blocker door inspection, lower
)
HINGES = (1.85, 2.55, 3.25, 4.25, 5.05, 5.85)  # hinge fittings along the hinge lines
LATCHES = (1.90, 2.40, 2.90, 3.35, 4.95, 5.50, 6.05)  # along the bottom split: 4 on the fan cowl, 3 on the sleeve
# Ring joints on the reverser sleeve: the translating cowl's split from the fixed structure ahead of it (a moving joint,
# no fasteners) and its aft joint (a, groove width, fastener rows). They stop short of the strut doublers.
SLEEVE_JOINTS = ((4.55, 0.018, 0), (6.30, 0.016, 1))
HOIST = ((1.40, 97.0), (3.80, 97.0))  # yellow hoist points, both sides
FIRE_ACCESS = (2.25, 118.0, 0.06)  # a, theta, radius: outboard
FAN_ARC = (0.95, 32.0, 164.0)  # the red fan-plane danger band: a, |theta| from, to
ARC_ARROWS = (55.0, 90.0, 125.0)
GRILLES = ((1.16, 1.40, 148.0, 158.0, "louvre"), (2.95, 3.18, -98.0, -108.0, "mesh"))  # clear of the red fan-plane line
PLACARDS = ((2.68, 79.0, 0.22, 0.07), (2.12, 170.0, 0.26, 0.07), (1.40, 104.0, 0.18, 0.05), (4.62, 46.0, 0.2, 0.06))
LINER_SPLICES = (0.0, 60.0, 120.0, 180.0)
# The strut's attachment doubler round each collar (the collar is the struts group's): the collar's footprint on the
# cowl reaches 1.3 m ahead of the crossing, 1.6 m behind it and 0.33 m either side (the struts group's numbers); the
# doubler frames it with a constant margin, its ends rounded.
DOUBLER = (1.30, 1.60, 0.33, 0.12)  # fore, aft, half girth of the footprint, margin
GEN_LINES = (1.55, 2.40)  # panel joints across the generator fairing
PYLON_LINES = (1.75, 2.85, 4.10, 5.40, 6.55)  # a: frames down the pylon side
PYLON_PANELS = ((2.00, 2.70, 0.08, 0.30, 0.04), (4.30, 5.20, 0.06, 0.30, 0.05), (5.60, 6.30, 0.06, 0.28, 0.04))
# On the aft fairing's flat side (the pylon over the cowl is all fillet): a, height, radius of the fire bottle
# discharge indicator; a, height, letter height of "ENG 1" and "ENG 2"
PYLON_FIRE = (7.55, 0.16, 0.045)
PYLON_TEXT = (7.05, 0.20, 0.075)

PAINT_COWL = (0.38, 0.39, 0.405)  # paint.PAINT[HULL]
# The satin bare metal every group uses for leading-edge strips, lips and bare fittings (the wing's leading edge), on
# the lip only within LIP_BAND (m, in the wall's (r, a) plane) of the highlight.
SATIN, SATIN_SMOOTH, SATIN_METAL = (0.46, 0.47, 0.48), 0.54, 0.2  # the wing's SATIN
LIP_BAND = 0.15
PAINT_LINER = (0.12, 0.10, 0.09)  # dark maroon-brown, as the stock intakes (art.md "Markings")
DARK = (0.10, 0.105, 0.11)
RED = (0.55, 0.10, 0.08)  # the wing's red, at its keep-clear line weight
RED_LINE = 0.022  # the wing's line weight
SEALANT, SEAL_RISE = (0.17, 0.17, 0.18), 0.004  # the generator fairing's sealant bead: within this rise of the cowl
YELLOW = (0.80, 0.62, 0.12)
STENCIL = (0.80, 0.80, 0.78)
PLACARD = ((0.50, 0.51, 0.52), (0.30, 0.305, 0.31))  # the wing's low-vis plate and rules


class EngineCoords:
    """(a, theta, r) of texel positions about the left engine's axis: the right engine's texels share the left's
    islands, so |x| reads them on the left. theta grows outboard."""

    def __init__(self, bl):
        num, side, x, front = bl.NACELLES[0]
        self.x, self.y0, self.z = x, bl.st(front), bl.NACELLE_Z

    def locate(self, pos):
        dx = np.abs(pos[:, 0]) - self.x
        dz = pos[:, 2] - self.z
        return pos[:, 1] - self.y0, np.degrees(np.arctan2(dx, dz)), np.hypot(dx, dz)


def collar_spots(bl):
    """(a, theta) where the strut line crosses the outer cowl, in and out: the centres of the attachment doublers."""
    root, hub, node = bl.s6_strut_line(1)
    ax = (node - root).normalized()
    num, side, x, front = bl.NACELLES[0]
    out = []
    for d in bl.s6_cowl_crossings(1, root, node):
        q = root + ax * d
        out.append((q.y - bl.st(front), math.degrees(math.atan2(q.x - x, q.z - bl.NACELLE_Z))))
    return out


def stamp(cv, img, U, V, px_per_m, mask, rgb):
    """Stamp a raster (rows bottom-up, 1 = ink) with its centre at U = V = 0, U along the text and V up, in metres."""
    np = cv.xp
    img = np.asarray(img)
    f = int(px_per_m * cv.px / 1.5)
    if f >= 2:
        hh, ww = (img.shape[0] // f) * f, (img.shape[1] // f) * f
        img = img[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
        px_per_m /= f
    h, w = img.shape
    lu, lv = U * px_per_m + w / 2, V * px_per_m + h / 2
    inside = (lu >= 0) & (lu < w - 1) & (lv >= 0) & (lv < h - 1) & (mask > 0)
    cov = np.zeros(cv.n)
    x, y = lu[inside], lv[inside]
    x0, y0 = x.astype(int), y.astype(int)
    tx, ty = x - x0, y - y0
    cov[inside] = (img[y0, x0] * (1 - tx) * (1 - ty) + img[y0, x0 + 1] * tx * (1 - ty)
                   + img[y0 + 1, x0] * (1 - tx) * ty + img[y0 + 1, x0 + 1] * tx * ty)
    cv.paint(cov * mask, rgb=rgb)


def paint(cv, text_mask):
    """The engines' paint over a Canvas (m4/paint.py). Only engine classes are touched; FITTING shells keep the
    canvas's fitting paint and wear."""
    np = cv.xp
    from .paint import fbm, poly_sdf, rrect_sdf, smoothstep, value_noise
    bl = cv.surf.bl
    a, th, r = EngineCoords(bl).locate(cv.pos.astype(float))
    cowl, sleeve, lip, liner, pyl, gen, core, heat = (cv.on(c) for c in (COWL, SLEEVE, LIP, LINER, PYLON, GEN, CORE_COWL, HEAT_SHIELD))
    for m, rgb, smooth, metal in ((cowl, PAINT_COWL, 0.42, 0.03), (sleeve, PAINT_COWL, 0.42, 0.03),
                                  (gen, PAINT_COWL, 0.42, 0.03), (pyl, PAINT_COWL, 0.42, 0.03),
                                  (lip, PAINT_COWL, 0.42, 0.03), (liner, PAINT_LINER, 0.22, 0.03),
                                  (core, SATIN, SATIN_SMOOTH, SATIN_METAL), (heat, SATIN, SATIN_SMOOTH, SATIN_METAL)):
        cv.albedo[m], cv.smooth[m], cv.metal[m] = rgb, smooth, metal
    C = (cowl | sleeve).astype(float)
    L, P, G = lip.astype(float), pyl.astype(float), gen.astype(float)
    R = np.interp(a, OUTER_A, OUTER_R)
    arc = R * np.radians(th)
    ath = np.abs(th)

    def arc_to(t0):
        """Signed girth from the line at theta t0 (positive toward larger theta), wrapped."""
        return R * np.radians(((th - t0 + 180.0) % 360.0) - 180.0)

    # The cowl is a serviceable metal shell; the final band is heat tinted ahead of the bright nozzle lip.
    N = core.astype(float)
    cv.paint(N * smoothstep(8.65, 8.96, a), rgb=(0.36, 0.30, 0.25), smooth=0.38)
    for sg in (1, -1):
        girth = r * np.radians(((th - sg * 90.0 + 180) % 360) - 180)
        cv.groove(np.abs(girth), 0.016, mask=N)
        for la in (7.90, 8.35, 8.70):
            sdf = rrect_sdf(a, girth, la - 0.07, la + 0.07, -0.028, 0.028, 0.01)
            cv.paint(cv.fill_coverage(sdf) * N, rgb=DARK, smooth=0.3, height=-0.002)
        for a0, a1, t0, t1 in ((7.85, 8.18, 45.0, 68.0), (8.32, 8.65, 112.0, 139.0)):
            v0, v1 = sorted((math.radians(sg * t0), math.radians(sg * t1)))
            sdf = rrect_sdf(a, r * np.radians(th), a0, a1, r * v0, r * v1, 0.035)
            cv.groove(np.abs(sdf), 0.014, mask=N)
            cv.fasteners(np.abs(sdf), a + r * np.radians(th), 0.025, mask=N * (np.abs(sdf) < 0.06))

    H = heat.astype(float)
    heat_h = cv.pos[:, 2] - bl.NACELLE_Z
    for joint in (7.10, 7.80, 8.55, 9.20):
        d = np.abs(a - joint)
        cv.groove(d, 0.016, mask=H)
        cv.fasteners(d, heat_h, 0.025, 0.08, mask=H * (d < 0.06))

    # panel tones: each panel between the joints and splits differs a few percent, Darkreach-like
    cell = np.searchsorted(np.array([0.60, 1.55, 3.60]), a) * 8 + np.searchsorted(np.array([HINGE_LINE, 90.0, 179.0]), ath)
    cell = cell * 2 + (th > 0)
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    cv.albedo *= (1 + 0.05 * tone * (C + G))[:, None]
    # the sleeve a shade darker and smoother than the fan cowl: a separate composite part
    cv.albedo *= (1 - 0.035 * sleeve)[:, None]

    # lip: one satin metal band round the highlight (every leading edge's metal), the rest of the lip painted
    hr, ha = WALL[0][0], WALL[0][1]
    cv.paint(L * cv.fill_coverage(np.hypot(r - hr, a - ha) - LIP_BAND), rgb=SATIN, smooth=SATIN_SMOOTH, metal=SATIN_METAL)

    # joints and splits: fastener rows on these primary joints only
    CL = np.clip(C + L, 0, 1)
    for j, w, rows in JOINTS:
        d = np.abs(a - j)
        cv.groove(d, w, mask=CL)
        if rows == 2:
            cv.fasteners(d, arc, 0.04, mask=CL * (d < 0.08))
        else:
            cv.fasteners(np.abs(a - j - 0.035), arc, 0.0, mask=C * (d < 0.08))
    for t, a0, a1 in SPLITS:  # the hinge lines beside the pylon and the latch line along the bottom, darker
        m = C * smoothstep(a0 - 0.01, a0, a) * smoothstep(a1 + 0.01, a1, a)
        d = np.abs(R * np.radians(ath - t))
        cv.groove(d, 0.02, darken=0.55, mask=m)
        cv.fasteners(d, a, 0.035, mask=m * (d < 0.08))

    # the strut's attachment doublers framing each collar's footprint with a constant margin: a raised plate with a
    # fastener row
    fore, aft, girth, margin = DOUBLER
    clear = np.ones(cv.n)
    for ca, ct in collar_spots(bl):
        hw = girth + margin
        v = arc_to(ct)
        sdf = rrect_sdf(a, v, ca - fore - margin, ca + aft + margin, -hw, hw, hw)
        m = C * (np.sign(th) == np.sign(ct))
        cv.paint(cv.fill_coverage(sdf) * m, height=0.0015)
        cv.groove(np.abs(sdf), 0.014, mask=m)
        cv.fasteners(np.abs(sdf + 0.035), a + v, 0.02, 0.07, mask=m * (np.abs(sdf + 0.035) < 0.05))
        clear *= 1 - cv.fill_coverage(sdf - 0.05) * m

    S = sleeve.astype(float) * clear
    for j, w, rows in SLEEVE_JOINTS:
        d = np.abs(a - j)
        cv.groove(d, w, darken=0.35 if rows else 0.55, mask=S)
        if rows:
            cv.fasteners(np.abs(a - j - 0.035), arc, 0.0, mask=S * (d < 0.08))

    # access panels
    for a0, a1, t0, t1, rad, side in PANELS:
        for sg in ((1, -1) if side == 0 else (side,)):
            am = (a0 + a1) / 2
            Rm = float(np.interp(am, OUTER_A, OUTER_R))
            v0, v1 = sorted((Rm * math.radians(sg * t0), Rm * math.radians(sg * t1)))
            sdf = rrect_sdf(a, arc, a0, a1, v0, v1, rad)
            cv.groove(np.abs(sdf), mask=C)
            cv.fasteners(np.abs(sdf), a + arc, 0.028, mask=C * (np.abs(sdf) < 0.06))

    # hinge fittings along the hinge lines, latches along the bottom split with red trigger tabs
    for sg in (1, -1):
        v = arc_to(sg * HINGE_LINE)
        for ha in HINGES:
            sdf = rrect_sdf(a, v, ha - 0.05, ha + 0.05, -0.02, 0.02, 0.006)
            cv.paint(cv.fill_coverage(sdf) * C, rgb=DARK, smooth=0.3, height=0.002)
    v = arc_to(LATCH_LINE)
    for la in LATCHES:
        sdf = rrect_sdf(a, v, la - 0.12, la + 0.12, -0.035, 0.035, 0.012)
        cv.paint(cv.fill_coverage(sdf) * C, rgb=DARK, smooth=0.3, height=-0.003)
        cv.groove(np.abs(sdf), 0.012, mask=C)
        cv.paint(cv.fill_coverage(rrect_sdf(a, v, la + 0.07, la + 0.11, -0.03, 0.03, 0.006)) * C, rgb=RED)
    for ha, ht in HOIST:
        for sg in (1, -1):
            sdf = rrect_sdf(a, arc_to(sg * ht), ha - 0.04, ha + 0.04, -0.04, 0.04, 0.008)
            cv.paint(cv.fill_coverage(sdf) * C, rgb=YELLOW)
            cv.paint(cv.fill_coverage(np.hypot(a - ha, arc_to(sg * ht)) - 0.015) * C, rgb=DARK, height=-0.003)
    fa, ft, fr = FIRE_ACCESS
    d = np.hypot(a - fa, arc_to(ft))
    cv.paint(cv.coverage(np.abs(d - fr), RED_LINE) * C, rgb=RED)
    cv.paint(cv.fill_coverage(d - fr + 0.025) * C, rgb=DARK, height=-0.002)

    # the fan-plane danger band, arrows pointing forward at the intake
    ia, t0, t1 = FAN_ARC
    m = C * smoothstep(t0 - 1, t0, ath) * smoothstep(t1 + 1, t1, ath)
    cv.paint(cv.coverage(np.abs(a - ia), RED_LINE) * m, rgb=RED)
    for t in ARC_ARROWS:
        for sg in (1, -1):
            vv = arc_to(sg * t)
            tri = [(ia - 0.14, 0.0), (ia - 0.04, -0.05), (ia - 0.04, 0.05)]
            cv.paint(cv.fill_coverage(poly_sdf(a, vv, tri)) * C, rgb=RED)

    # grilles
    for a0, a1, t0, t1, kind in GRILLES:
        vv = arc_to((t0 + t1) / 2)
        Rm = float(np.interp((a0 + a1) / 2, OUTER_A, OUTER_R))
        hw = Rm * math.radians(abs(t1 - t0)) / 2
        sdf = rrect_sdf(a, vv, a0, a1, -hw, hw, 0.015)
        inside = cv.fill_coverage(sdf) * C
        cv.paint(inside, rgb=(0.14, 0.14, 0.15), smooth=0.25, height=-0.004)
        if kind == "louvre":
            slat = np.abs(((a - a0) % 0.03) - 0.015) < 0.005
            cv.paint(inside * slat, rgb=(0.30, 0.31, 0.32), height=0.003)
        else:
            mesh = (np.abs(((a - a0) % 0.035) - 0.0175) < 0.005) | (np.abs((vv % 0.035) - 0.0175) < 0.005)
            cv.paint(inside * mesh, rgb=(0.32, 0.33, 0.34), height=0.0015)
        cv.groove(np.abs(sdf), 0.014, mask=C)
        cv.fasteners(np.abs(sdf), a + vv, 0.022, mask=C * (np.abs(sdf) < 0.05))

    # placards: small light plates ruled with lines of fine print, which read either way round
    for pa, pt, pw, ph in PLACARDS:
        for sg in (1, -1):
            vv = arc_to(sg * pt)
            sdf = rrect_sdf(a, vv, pa - pw / 2, pa + pw / 2, -ph / 2, ph / 2, 0.006)
            plate = cv.fill_coverage(sdf) * C
            cv.paint(plate, rgb=PLACARD[0], smooth=0.35)
            rows = (np.abs(((vv + ph / 2) % 0.016) - 0.008) < 0.003) & (np.abs(a - pa) < pw / 2 - 0.015)
            cv.paint(plate * rows * (np.abs(vv) < ph / 2 - 0.01), rgb=PLACARD[1])

    # exhaust soot over the sleeve's tail, heavier underneath
    soot = smoothstep(5.2, FAN_NOZZLE_TE, a) * (0.55 + 0.45 * fbm(cv.pos * np.array([3.0, 0.5, 3.0]), 0.5, 2, seed=23))
    soot *= 0.5 + 0.5 * smoothstep(60.0, 150.0, ath)
    cv.albedo *= (1 - 0.30 * soot * C)[:, None]
    cv.smooth -= 0.08 * soot * C

    # liner: acoustic panels with splice lines and a fine perforation mottle
    LN = liner.astype(float)
    for t in LINER_SPLICES:
        d = r * np.radians(np.abs(((ath - t + 180.0) % 360.0) - 180.0))
        cv.groove(d, 0.02, -0.002, 0.5, mask=LN)
    cv.groove(np.abs(a - 0.52), 0.016, -0.002, 0.4, mask=LN)
    cv.albedo *= (1 + 0.14 * (value_noise(cv.pos, 0.05, seed=27) - 0.5) * LN)[:, None]
    perf = (np.abs(((a * 40.0) % 1.0) - 0.5) < 0.18) & (np.abs(((r * np.radians(th) * 40.0) % 1.0) - 0.5) < 0.18)
    cv.paint(LN * perf * 0.5, rgb=(0.07, 0.06, 0.055))

    # generator fairing: two joints across it, a sealant line where it lands on the cowl and a fastener row above it
    rise = r - cowl_chord_radius(R, th)
    for ga in GEN_LINES:
        cv.groove(np.abs(a - ga), 0.016, mask=G)
        cv.fasteners(np.abs(a - ga), r * np.radians(th), 0.03, mask=G * (np.abs(a - ga) < 0.06))
    cv.paint(cv.coverage(rise, 2 * SEAL_RISE) * G, rgb=SEALANT, smooth=0.3)
    d = np.abs(rise - 0.035)
    cv.fasteners(d, a, 0.0, 0.08, mask=G * (rise < 0.06))

    # pylon: frames, access panels, the fire indicator, soot behind the nozzle, its stencils
    crown = bl.NACELLE_Z + np.interp(np.minimum(a, 6.8), OUTER_A, OUTER_R)
    h = cv.pos[:, 2] - crown
    for la in PYLON_LINES:
        d = np.abs(a - la)
        cv.groove(d, mask=P)
        cv.fasteners(d, h, 0.03, mask=P * (d < 0.06))
    for a0, a1, h0, h1, rad in PYLON_PANELS:
        sdf = rrect_sdf(a, h, a0, a1, h0, h1, rad)
        cv.groove(np.abs(sdf), mask=P)
        cv.fasteners(np.abs(sdf), a + h, 0.028, mask=P * (np.abs(sdf) < 0.06))
    fa, fh, fr = PYLON_FIRE
    d = np.hypot(a - fa, h - fh)
    cv.paint(cv.coverage(np.abs(d - fr), 0.016) * P, rgb=RED)
    cv.paint(cv.fill_coverage(d - fr + 0.02) * P, rgb=(0.85, 0.82, 0.25))
    psoot = smoothstep(6.6, 7.6, a) * (0.5 + 0.5 * fbm(cv.pos * np.array([3.0, 0.6, 3.0]), 0.4, 2, seed=29))
    psoot *= smoothstep(0.5, 0.0, cv.pos[:, 2] - bl.NACELLE_Z - 1.3)
    cv.albedo *= (1 - 0.35 * psoot * P)[:, None]
    # stencils: pylon_2 keeps its own islands, so its text reads right; it runs aft on the face seen from +x
    ta, tz, tl = PYLON_TEXT
    sgn = np.sign(cv.nrm[:, 0] + 1e-9)
    for body, on_x in (("ENG 1", 1.0), ("ENG 2", -1.0)):
        mask = P * (np.sign(cv.pos[:, 0]) == on_x) * (np.abs(cv.nrm[:, 0]) > 0.5)
        stamp(cv, text_mask(body), sgn * (a - ta), h - tz, 48 / (tl * 1.4), mask, STENCIL)


