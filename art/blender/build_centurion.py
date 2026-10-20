"""MRB-100 Centurion blockout, step 5: step 4 (the step 2 shape at docs/SPEC.md dimensions, plus what the Unity
export reads from the .blend: convex colliders, LOD1 hulls, skin-atlas UVs, material slots and baked smoothing, with
12 deg of tail-strike clearance) with each raked wingtip built into the last telescoping stage instead of a part of its
own. A tear sheds both stage 1 subtrees, and as separate parts they were 6 of 45, past the 12% of an aircraft's parts
that makes an AI pilot eject (PartDamageTracker); merged they are 4 of 43.

Step 6 (--step 6, the default) is the silhouette the owner settled at gate G1.6 (docs/PROPORTION-STUDY.md round 4,
docs/DECISIONS.md and docs/BLOCKOUT-S6.md): configure_step6 rebinds this step 5 library's numbers and builders, so
--step 5 still builds step 5 and m4/blockout.py's load_blockout, which never runs main(), still reads step 5.
Step 6.1 (--step 6.1, docs/BLOCKOUT-S61.md) is step 6 with the owner's changes after flying it: long telescoping
stages, a slimmer wing fairing and streamlined sponsons (configure_step61, on top of configure_step6).

blender --background --factory-startup --python art/blender/build_centurion.py -- [--step 5|6|6.1] [--span retracted,extended]
    [--out DIR] [--no-render] [--views orient|all|sheets]

--span takes retracted, extended, or a 0..1 extension value; a comma list runs each state in turn (default: both).
Each state rebuilds the "Centurion" collection from scratch, then writes metrics_<span>.json, the renders and
centurion_s<step>_<span>.blend into DIR (default <repo>/.cache/art/blockout_s<step>). Step 6 renders in the M4 review
look (Cycles) and composes the sheets once both states are built; --views orient renders only three quick frames to
check the axes, and --views sheets recomposes the sheets from renders already in DIR without building.

Axes: nose toward -Y, up +Z, the pilot's left wing (_L) on +X, ground at Z = 0, world Y = station - 21.5 so the
aircraft sits centred on the hangar spawn. Every mesh part has unit scale and its origin on its attachment point or
motion axis. Telescoping stages carry their slide axis and travel as custom properties, because the swept span axis
is not a world axis. Hinged parts follow the stock split: an empty named for the part sits on the hinge line with
local X along the hinge (pointing to world +X, or aft for a door, on both sides, so one sign moves both the same
way), and the mesh hangs under it as <name>_visible with an identity local transform. Gear doors are modelled open
(gear down); bay doors and control surfaces at rest.

Export data, for each render part <part> in the "Centurion" collection:
- <part>_colmesh, <part>_colmesh.001, ...: convex collider pieces of each load-carrying part (LOAD_PARTS), in the
  "Colliders" sub-collection. Each is parented to <part> with an identity local transform, so its mesh is already in
  the part's local space.
- <part>_lod1: one flat-shaded hull per detachable part (LOD1_PARTS), in the "LOD1" sub-collection, parented the same
  way, with the "LOD" material and a FLOAT_COLOR point attribute "Col" of 0.14 grey.
- Render parts carry one UV map, "UVMap": Centurion_skin faces packed into the 2048 atlas (mirrored twins share
  islands, see mirror_source), every other face box-projected at 1 UV per 2 m for the tiling trims. Material slots
  run in SLOT_ORDER, only those used. Normals are custom split normals from an applied Weighted Normal modifier.
"""

import colorsys
import contextlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convex  # noqa: E402  (beside this script, which Blender runs without a package)
import flightdeck_layout as fl  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
STEP = "s5"

# ---------- SPEC.md numbers ----------
LENGTH = 43.0
Y0 = LENGTH / 2
FUS_HALF_W, FUS_BOTTOM, FUS_TOP = 2.0, 1.6, 6.0  # 4.0 wide, 4.4 tall, bottom 1.6 above ground
WING_ROOT_TOP = 6.4
SWEEP = math.radians(-12.0)  # quarter-chord; negative is forward sweep, tips ahead of roots
DIHEDRAL = math.radians(-1.0)
INCIDENCE = math.radians(2.0)
WING_ROOT_LE_STATION = 15.4  # 7.2 m root chord inside the 15..23 wing box
CHORD = ((0.0, 7.2), (13.0, 4.6), (21.8, 4.2))  # (semi-span, chord)
# 12% root, 10% tip: thin enough that the SPEC nacelle height still leaves a pylon gap under the chord
THICK = ((0.0, 0.86), (13.0, 0.50), (21.8, 0.44))
WING_CAMBER = 0.015
RETRACTED_SEMISPAN = 21.8
WINGTIP_LATERAL = 1.8  # the raked tip's spanwise reach; the fixed wing ends this far inboard of 21.8
TRAVEL = 6.3  # per stage, along the swept span axis
SPAN_EXTENDED = 68.2  # SPEC's extended span, which the extended build is checked against
TELE_THICK_RATIO = 0.94
TELE = (("wing_tele1", 3.95, 9.0, 0.02), ("wing_tele2", 3.70, 8.6, 0.04))  # name, chord, length, inset from root tip
TIP_RAKE, TIP_UPSWEEP = math.radians(30.0), math.radians(12.0)
TIP_NECK = 0.06  # the tip cuff starts this far outboard of the last stage's end, 2 cm clear of the root end cap
# Step 6.1 rounds the tips (owner: "make the tips end in a more rounded thing not just a 90 degrees"): over the tip's
# outer part, from TIP_ROUND[0] of its reach, chord and thickness close elliptically about TIP_ROUND[1] of the chord
# from the leading edge, so both edges curve in and meet at a point with no corner in plan or section.
TIP_ROUND = None
STRUT_ROOT = (2.6, 19.0, 2.6)  # (off centreline, station, height)
STRUT_WING_X = 13.0
STRUT_NODE_CHORD = 0.65  # the node sits on the rear spar line
# The strut runs aft of both nozzles (it starts above the nacelle bottoms, so it can't pass under them), then leans
# forward to the node: cubic Bezier through these (off centreline, station, height) controls and the node.
STRUT_CTRL = ((6.0, 19.6, 2.95), (11.0, 19.0, 3.9))
JURY_T, JURY_TOP_CHORD = 0.5, 0.62  # jury strut from the strut's midpoint up to 62% chord, between the engines
NACELLE_Z = 3.6
# num, side, semi-span, intake station: the wing leading edge falls at about 57% of each nacelle's length
NACELLES = ((1, +1, 10.4, 10.75), (2, +1, 6.0, 11.45), (3, -1, 6.0, 11.45), (4, -1, 10.4, 10.75))
# The root sits high enough on the upswept cone to stay embedded above the tail-strike line; the span is cut to
# match, so the tips stay at about 7.5 m.
VTAIL_DIHEDRAL, VTAIL_ROOT_Z, VTAIL_ROOT_STATION = math.radians(32.0), 4.5, 33.0
VTAIL_TIP_ROUND = None  # step 6.1: (metres along the panel, chord fraction the tip closes on); see vtail_planform
VTAIL_ROOT_CHORD, VTAIL_TIP_CHORD, VTAIL_SPAN, VTAIL_SWEEP = 5.5, 2.4, 5.65, math.radians(38.0)
# The main bogie sits in the aft half of the strut-root fairing (centred on the strut root, station 19), 2 m behind
# it, which with the tail-cone ramp gives the tail-strike angle (SPEC "Landing gear").
MAIN_TRACK, NOSE_GEAR_STATION, MAIN_GEAR_STATION = 5.2, 6.0, 21.0
NOSE_PIVOT_Z = MAIN_PIVOT_Z = None  # gear leg tops; None: 0.3 and 0.6 m over FUS_BOTTOM, whatever a caller sets it to
MAIN_PIVOT_X = None  # the main legs' hinge half width; None: over the bogie, MAIN_TRACK / 2
NOSE_DOOR_BOTTOM = 1.05
SPONSON = "strutfairing"  # the strut-root fairing that holds the main bogie
TAIL_STRIKE_MIN_DEG = 12.0
TAIL_STRIKE_BAND, TAIL_STRIKE_KEY = None, "tail_strike_ge_12deg"  # band (deg); None: at least TAIL_STRIKE_MIN_DEG
LENGTH_LIMIT, HEIGHT_LIMIT, TAIL_TOP_LIMIT = 43.0, 7.6, None  # step 5's height limit is the V-tail tips'
# Main-strut sag at maximum takeoff mass with the nose wheel up: SPEC 199 t on two legs of CenturionAuthor's 6e6 N/m.
MAIN_STRUT_SAG = 199000 * 9.81 / (2 * 6.0e6)
BAYS = (("F", 7.0, 15.0, "fuselage_F"), ("A", 23.0, 31.0, "fuselage_R"))  # forward and aft bay stations
HANGAR_DOOR_W, HANGAR_DOOR_H, HANGAR_DEPTH = 45.78, 8.0, 45.0

# Material slots (art.md section 4): the livery-able skin atlas, then the shared stock trims. Bay and well interiors
# and the joint faces a part shows only once it has broken off take aircraft_structure. Glass stays a stock material;
# Centurion_gear stands in for the gear set (a custom 1024 set or SFB_gear, not chosen yet).
SKIN, MECH, STRUCT, GLASS, GEAR, LOD = "Centurion_skin", "jet_mechanical", "aircraft_structure", "glass", "Centurion_gear", "LOD"
SLOT_ORDER = (SKIN, MECH, STRUCT, GLASS, GEAR)
ATLAS, TEXEL_TARGET = 2048, 57.0  # skin atlas size and density (px per metre)

# Control surfaces on the fixed inner wing only (SPEC: no hinge on the telescoping stages).
# name suffix, semi-span from, to, kind. Flaps fill the gaps beside the pylons; ailerons and spoilers sit outboard
# of the strut node.
SURFACES = (("flap_{s}1", 2.75, 5.65, "flap"), ("flap_{s}2", 6.35, 10.05, "flap"),
            ("aileron_{s}", 13.5, 19.6, "aileron"), ("spoiler_{s}", 13.5, 19.4, "spoiler"))
FLAP_HINGE = 0.72  # chord fraction
SURF_GAP = 0.03  # spanwise gap between a surface's end and its cut-out
WING_UV_CUTS = (6.0, 13.0)  # semi-spans of the wing skin's spanwise UV cuts: the outer pylon and the strut node
WING_ROOT_BONDS = ()  # fuselage parts beside fuselage_M that the wing root also reaches into
# The retracted stages fill the inner wing outboard of x = 11.2 back to 2.96 m behind the quarter chord, so the
# aileron hinges just aft of the stage trailing edge: a 5 to 9% chord strip.
AILERON_HINGE_BEHIND_QC = 0.75 * TELE[0][1] + 0.06
SPOILER_CHORD = (0.56, 0.76)
RUDDERVATOR_HINGE, RUDDERVATOR_SPAN = 0.55, (0.55, 5.3)
SPLIT_TAIL = None  # step 6.1: the moving trailing edge cut into two surfaces (S61_SPLIT_TAIL); None, one surface a side

COS_G = math.cos(DIHEDRAL)
XI_PER_X = 1 / (COS_G * math.cos(SWEEP))  # distance along the swept span axis per metre of semi-span
CDIR = Vector((0, math.cos(INCIDENCE), -math.sin(INCIDENCE)))  # streamwise chord direction, aft, leading edge up
TDIR = Vector((0, math.sin(INCIDENCE), math.cos(INCIDENCE)))
X_ROOT_TIP = RETRACTED_SEMISPAN - WINGTIP_LATERAL
XI_ROOT_TIP = X_ROOT_TIP * XI_PER_X

scene = bpy.context.scene


def st(station):
    return station - Y0


def interp(table, x):
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1 or x1 == table[-1][0]:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)


def smooth(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def frame(axis, up=Vector((0, 0, 1))):
    """Rotation whose local X is the hinge axis (flipped to point to world +X, or aft when it lies along Y)."""
    x = axis.normalized()
    if x.x < -1e-6 or (abs(x.x) <= 1e-6 and x.y < 0):
        x = -x
    z = (up - x * up.dot(x)).normalized()
    return Matrix((x, z.cross(x), z)).transposed()


# ---------- geometry primitives (all build closed shells into a bmesh) ----------
def airfoil_point(le, chord, thick, cdir, tdir, camber, t, upper, te=0.006):
    yt = 5 * thick * (0.2969 * math.sqrt(t) - 0.1260 * t - 0.3516 * t ** 2 + 0.2843 * t ** 3 - 0.1036 * t ** 4) + te * chord * t
    yc = camber * chord * 4 * t * (1 - t)
    return le + cdir * (t * chord) + tdir * (yc + (yt if upper else -yt))


def camber_point(le, chord, cdir, tdir, camber, t):
    return le + cdir * (t * chord) + tdir * (camber * chord * 4 * t * (1 - t))


def airfoil(le, chord, thick, cdir, tdir, camber=0.0, n=10, te=0.006, cut=None):
    """Closed section, upper trailing edge to leading edge to lower trailing edge. cut: chord fraction where a
    control surface takes over; the points behind it fold onto a flat face at the cut (same point count)."""
    ts = [0.5 * (1 - math.cos(math.pi * k / n)) for k in range(n + 1)]

    def side(upper):
        pts = [airfoil_point(le, chord, thick, cdir, tdir, camber, t, upper, te) for t in ts[1:]]
        if cut is not None:
            behind = [i for i, t in enumerate(ts[1:]) if t > cut]
            face = airfoil_point(le, chord, thick, cdir, tdir, camber, cut, upper, te)
            mid = camber_point(le, chord, cdir, tdir, camber, cut)
            for j, i in enumerate(behind):
                pts[i] = face.lerp(mid, 0.95 * j / max(len(behind) - 1, 1))
        return pts

    return list(reversed(side(True))) + [le.copy()] + side(False)


def airfoil_aft(le, chord, thick, cdir, tdir, camber, t0, n=4, te=0.006):
    """The part of a section aft of chord fraction t0 (a control surface), with a flat front face."""
    ts = [t0 + (1 - t0) * k / n for k in range(n + 1)]
    upper = [airfoil_point(le, chord, thick, cdir, tdir, camber, t, True, te) for t in reversed(ts)]
    return upper + [airfoil_point(le, chord, thick, cdir, tdir, camber, t, False, te) for t in ts]


def loft(bm, rings, start="cap", end="cap", loop=False, seams=(), soft=(), ring_seams=(), cap_mat=(None, None)):
    """Skin rings of equal size. start/end: "cap" (flat, triangulated), a Vector (pole), or None (open, for loop).
    UV seams: seams are ring columns whose lengthwise edges are cut (soft ones stay smooth-shaded, as an airfoil
    leading edge), ring_seams are rings cut all the way round. cap_mat: material index for the start and end caps
    (a station joint, hidden while the part is attached), None to keep slot 0."""
    vr = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(vr[0])
    pairs = list(zip(vr, vr[1:])) + ([(vr[-1], vr[0])] if loop else [])
    soft_layer = bm.edges.layers.int.get("soft") or bm.edges.layers.int.new("soft")

    def cut(a, b, j):
        e = bm.edges.get((a, b))
        e.seam = True
        if j in soft:
            e[soft_layer] = 1

    faces = []
    for a, b in pairs:
        for j in range(n):
            k = (j + 1) % n
            faces.append(bm.faces.new((a[j], a[k], b[k], b[j])))
        for j in seams:
            cut(a[j], b[j], j)
    for r in ring_seams:
        for j in range(n):
            cut(vr[r][j], vr[r][(j + 1) % n], None)
    if loop:
        return faces
    for ring, end_kind, mat in ((vr[0], start, cap_mat[0]), (vr[-1], end, cap_mat[1])):
        if isinstance(end_kind, Vector):
            pole = bm.verts.new(end_kind)
            for j in range(n):
                faces.append(bm.faces.new((ring[j], ring[(j + 1) % n], pole)))
            for j in seams:
                cut(ring[j], pole, j)
        elif end_kind == "cap":
            # Zipped from both ends of the ring inward: the triangles depend only on vertex order, so mirrored twins
            # get the same faces and can share UVs face for face. Every ring here pairs its halves this way (airfoil
            # upper and lower surface, a panel's outer and inner arc).
            i, j, cap = 0, n - 1, []
            while j - i > 1:
                cap.append(bm.faces.new((ring[i], ring[i + 1], ring[j])))
                i += 1
                if j - i > 1:
                    cap.append(bm.faces.new((ring[i], ring[j - 1], ring[j])))
                    j -= 1
            for f in cap:
                f.material_index = mat or 0
            for j in range(n):
                cut(ring[j], ring[(j + 1) % n], None)
            faces += cap
    return faces


def revolve(bm, profile, center, seg=24, loop=False, shape=None, seams=(), ring_seams=()):
    """Spin an (radius, axial) profile about the +Y axis through center; radius 0 at either end makes a pole.
    shape(profile_index, segment_index, r, a) may return a reshaped (r, a) per vertex. Segment 0 is on top; seams
    are segment columns, ring_seams profile indices (see loft)."""
    pts = list(profile)
    start = end = "cap"
    first = 0
    if not loop and pts[0][0] == 0:
        start = center + Vector((0, pts.pop(0)[1], 0))
        first = 1
    if not loop and pts[-1][0] == 0:
        end = center + Vector((0, pts.pop()[1], 0))
    rings = []
    for pi, (r0, a0) in enumerate(pts):
        ring = []
        for i in range(seg):
            r, a = shape(pi + first, i, r0, a0) if shape else (r0, a0)
            ang = 2 * math.pi * i / seg
            ring.append(center + Vector((r * math.sin(ang), a, r * math.cos(ang))))
        rings.append(ring)
    return loft(bm, rings, start, end, loop, seams=seams, ring_seams=[r - first for r in ring_seams])


def cylinder(bm, p0, p1, radius, seg=12):
    axis = (p1 - p0).normalized()
    e1 = axis.orthogonal().normalized()
    e2 = axis.cross(e1)
    ring = lambda c: [c + (e1 * math.cos(2 * math.pi * i / seg) + e2 * math.sin(2 * math.pi * i / seg)) * radius for i in range(seg)]
    loft(bm, [ring(p0), ring(p1)])


def box(bm, center, size):
    sx, sy, sz = (s / 2 for s in size)
    rings = [[center + Vector((x * sx, y, z * sz)) for x, z in ((-1, -1), (1, -1), (1, 1), (-1, 1))] for y in (-sy, sy)]
    loft(bm, rings)


def sphere(bm, center, radius, seg=16, rows=8, seams=()):
    prof = [(radius * math.sin(math.pi * k / rows), -radius * math.cos(math.pi * k / rows)) for k in range(rows + 1)]
    prof[0], prof[-1] = (0, -radius), (0, radius)
    revolve(bm, prof, center, seg, seams=seams)


# ---------- fuselage ----------
FUS_P, FUS_N = 2.3, 32  # superellipse exponent, ring vertices (vertex 0 on top, angles clockwise seen from the nose)
FUS_KEEL = FUS_N // 2  # the bottom centreline vertex, where the fuselage tube is cut open for UVs
CHINE_K, CHINE_OUT = (10, 22), 0.07  # ring vertices at 112.5 and 247.5 degrees: a faint lower-side crease


def ell(u, e):
    u = min(max(u, 0.0), 1.0)
    return (1 - (1 - u) ** e) ** (1 / e)


UPSWEEP_START = 27.0  # a fuselage_R ring station, so the mesh carries the crease
UPSWEEP_SLOPE = math.tan(math.radians(TAIL_STRIKE_MIN_DEG))


def fus_profile(s):
    """Half-width, top and bottom height at a station: 787-style nose, constant barrel, upswept tail cone. The belly
    ramps up straight from UPSWEEP_START at the tail-strike angle, so it stays parallel to the line from the main
    wheels at TAIL_STRIKE_MIN_DEG instead of closing on it; the crown barely droops, leaving the turret room."""
    w = FUS_HALF_W * ell(s / 7.0, 1.6)
    top = NOSE_TIP_Z + (FUS_TOP - NOSE_TIP_Z) * ell(s / 9.0, 1.5)  # long crown over the flight deck
    bot = NOSE_TIP_Z - (NOSE_TIP_Z - FUS_BOTTOM) * ell(s / 4.5, 1.7)  # short chin, tip low as on the 787
    if s > UPSWEEP_START:
        bot = FUS_BOTTOM + UPSWEEP_SLOPE * (s - UPSWEEP_START)
    if s > 33:
        top = FUS_TOP - 0.4 * ((s - 33) / 9.95) ** 2
    if s > 32:
        w = FUS_HALF_W * (1 - 0.85 * ((s - 32) / 10.95) ** 2.0)
    return w, top, bot


def fus_point(s, deg, offset=0.0, scale=1.0):
    """Skin point at a station and an angle from the top (positive toward +X), pushed out radially by offset."""
    w, top, bot = fus_profile(s)
    zc, h = (top + bot) / 2, (top - bot) / 2
    a = math.radians(deg)
    sx, cz = math.sin(a), math.cos(a)
    p = Vector((w * math.copysign(abs(sx) ** (2 / FUS_P), sx), 0, h * math.copysign(abs(cz) ** (2 / FUS_P), cz))) * scale
    if offset:
        p += p.normalized() * offset
    return Vector((p.x, st(s), zc + p.z))


def chine(s):
    return smooth((s - 1.0) / 2.0) * (1 - smooth((s - 5.0) / 2.0))


def fus_ring(s, scale=1.0, with_chine=True):
    pts = [fus_point(s, 360 * k / FUS_N, scale=scale) for k in range(FUS_N)]
    if with_chine and chine(s) > 0:
        for k in CHINE_K:
            pts[k] = fus_point(s, 360 * k / FUS_N, CHINE_OUT * chine(s))
    return pts


def skin_panel(bm, stations, a0, a1, inner, outer, n_a=4, inner_mat=None):
    """A thin closed shell lying on the fuselage skin over a station range and an angle range, its outer face, inner
    face and two side strips cut into separate UV islands. inner_mat: material index for the inner face."""
    rings = []
    for s in stations:
        angs = [a0 + (a1 - a0) * k / n_a for k in range(n_a + 1)]
        rings.append([fus_point(s, a, outer) for a in angs] + [fus_point(s, a, inner) for a in reversed(angs)])
    faces = loft(bm, rings, seams=(0, n_a, n_a + 1, 2 * n_a + 1))
    if inner_mat is not None:
        per_ring = 2 * (n_a + 1)
        for i, f in enumerate(faces[:per_ring * (len(rings) - 1)]):
            if n_a + 1 <= i % per_ring <= 2 * n_a:
                f.material_index = inner_mat
    return faces


FUS_CENTER_Z = (FUS_TOP + FUS_BOTTOM) / 2
NOSE_TIP_Z = 3.0
TAIL_END = ((41.85, 0.8), (42.0, 0.5))  # (station, ring scale): the cone closes onto the laser turret
FUSELAGE = (  # name, ring stations, origin station (joint to the parent), parent
    ("radar_F_fairing", (0.15, 0.4, 0.8, 1.3, 1.9, 2.5), 2.5, "nose"),
    ("nose", (2.5, 3.0, 3.55, 4.0, 4.45, 4.85, 5.25, 6.1, 7.0), 7.0, "fuselage_F"),
    ("fuselage_F", (7.0, 8.5, 11.0, 13.0, 15.0), 15.0, "fuselage_M"),
    ("fuselage_M", (15.0, 19.0, 23.0), 19.0, None),
    ("fuselage_R", (23.0, 27.0, 28.0, 29.0, 30.0, 31.0), 23.0, "fuselage_M"),  # close rings on the ramp keep its hulls inset
    ("tailcone", (31.0, 32.5, 34.0, 35.5, 37.0, 38.5, 40.0, 41.0, 41.6), 31.0, "fuselage_R"),
)
# Four windscreen panes per the 787: (stations from, to, angles from, to) on the left side, mirrored right.
PANES = ((2.95, 3.9, 5.0, 48.0), (3.35, 4.75, 52.0, 80.0))


def build_fuselage(parts):
    """Every fuselage cap is a station joint. The radome carries its own collider pieces: without any, CenturionAuthor
    collides it on the hull of its mesh, which is over Unity's 255-triangle convex limit and outside the skin.
    Colliders follow the skin without the chine, whose crease would leave hollows a hull bridges."""
    for name, stations, origin_station, parent in FUSELAGE:
        bm = bmesh.new()
        rings = [fus_ring(s) for s in stations]
        smooth_rings = [fus_ring(s, with_chine=False) for s in stations]
        start = Vector((0, st(0.0), NOSE_TIP_Z)) if name == "radar_F_fairing" else "cap"
        if name == "tailcone":
            rings += [fus_ring(s, k) for s, k in TAIL_END]
            smooth_rings += [fus_ring(s, k, with_chine=False) for s, k in TAIL_END]
        if name in VISUAL_TAIL_PARTS:  # its colliders follow the skin the art draws, so hits land on what shows
            with visual_tail():  # rings 0.5 m apart over its taper, so no inset hull bows past the skin between them
                stations = sorted(set(stations) | {s0 + 0.5 * k for s0 in (stations[0],)
                                                   for k in range(int((stations[-1] - stations[0]) / 0.5) + 1)})
                smooth_rings = [fus_ring(s, with_chine=False) for s in stations]
                if name == "tailcone":
                    smooth_rings += [fus_ring(s, k, with_chine=False) for s, k in TAIL_END]
        # The radome dome is cut into a tip and a band, or one dome island stretches the checker near its base.
        loft(bm, rings, start, "cap", seams=(0, FUS_KEEL), cap_mat=(1, 1), ring_seams=(2,) if name == "radar_F_fairing" else ())
        mats, col = (SKIN, STRUCT), [{"rings": smooth_rings, "start": start, "end": "cap"}]
        if name == "nose":
            mats = (SKIN, STRUCT, GLASS)
            for s0, s1, a0, a1 in PANES:
                for sgn in (1, -1):
                    lo, hi = sorted((sgn * a0, sgn * a1))
                    for f in skin_panel(bm, [s0 + (s1 - s0) * k / 3 for k in range(4)], lo, hi, -0.01, 0.02, n_a=3):
                        f.material_index = 2
        add_part(parts, name, bm, Vector((0, st(origin_station), FUS_CENTER_Z)), parent, mats=mats, col=col)


def build_wingfairing(parts):
    """Dorsal wing-to-body fairing: a superellipse blister whose lower half hides in the fuselage, rising over the
    wing root and spilling past the shoulders under the wing so the root reads blended, not laid on top."""
    s0, s1, peak = 12.8, 26.5, 17.8
    rings = []
    for s in [s0 + (s1 - s0) * k / 22 for k in range(23)]:
        bw = smooth((s - s0) / 2.8) * (1 - smooth((s - 19.4) / (s1 - 19.4)))
        bt = 0.5 * (1 + math.cos(math.pi * min(abs(s - peak) / ((peak - s0) if s < peak else (s1 - peak)), 1.0)))
        w, top, bot = 1.45 + 1.0 * bw, 5.92 + 0.64 * bt, 3.9
        zc, h = (top + bot) / 2, (top - bot) / 2
        ring = []
        for k in range(32):
            a = 2 * math.pi * k / 32
            sx, cz = math.sin(a), math.cos(a)
            ring.append(Vector((w * math.copysign(abs(sx) ** (2 / 2.6), sx), st(s), zc + h * math.copysign(abs(cz) ** (2 / 2.6), cz))))
        rings.append(ring)
    bm = bmesh.new()
    loft(bm, rings, seams=(16,), cap_mat=(1, 1))
    # Its collider belongs to fuselage_M: one hull of barrel and fairing would bridge the step where the fairing
    # spills past the shoulders, so it is a separate piece.
    add_part(parts, "wingfairing", bm, Vector((0, st(19.0), FUS_TOP)), "fuselage_M", mats=(SKIN, STRUCT),
             col=[{"rings": rings, "start": "cap", "end": "cap", "owner": "fuselage_M"}],
             bonded_to="wing_root_L,wing_root_R,fuselage_F,fuselage_R")


# ---------- wing ----------
def span_axis(side, upsweep=0.0):
    g = DIHEDRAL + upsweep
    return Vector((side * math.cos(g) * math.cos(SWEEP), math.cos(g) * math.sin(SWEEP), math.sin(g)))


def _root_qc():
    ring = airfoil(-0.25 * CHORD[0][1] * CDIR, CHORD[0][1], THICK[0][1], CDIR, TDIR, WING_CAMBER)
    return Vector((0, st(WING_ROOT_LE_STATION + 0.25 * CHORD[0][1]), WING_ROOT_TOP - max(p.z for p in ring)))


ROOT_QC = _root_qc()


def qc_at(side, xi):
    return ROOT_QC + span_axis(side) * xi


def wing_le(side, x):
    c = interp(CHORD, x)
    return qc_at(side, x * XI_PER_X) - 0.25 * c * CDIR, c, interp(THICK, x)


def wing_lower(side, x, station, inset=0.0):
    le, c, t = wing_le(side, x)
    frac = min(max((st(station) - le.y) / (c * CDIR.y), 0.0), 1.0)
    return airfoil_point(le, c, t, CDIR, TDIR, WING_CAMBER, frac, False) + Vector((0, 0, inset))


def tele_section(side, xi, chord, thick):
    return airfoil(qc_at(side, xi) - 0.25 * chord * CDIR, chord, thick, CDIR, TDIR, WING_CAMBER)


AF_N = 10  # airfoil() default: 2n + 1 points, upper trailing edge (0), leading edge (n), lower trailing edge (2n)
AF_SEAMS = (0, AF_N, 2 * AF_N)
AFT_SEAMS = (0, 4, 5, 9)  # airfoil_aft() default: trailing edges and the flat front face of a control surface


def airframe(rings, start="cap", end="cap"):
    """Collider source for a lofted load-carrying part (see build_colliders)."""
    return [{"rings": rings, "start": start, "end": end}]


def surface_hinge_fraction(kind, x):
    if kind == "flap":
        return FLAP_HINGE
    c = interp(CHORD, x)
    return (0.25 * c + AILERON_HINGE_BEHIND_QC) / c


def build_wing(parts, side):
    sfx = "_L" if side > 0 else "_R"
    cuts = [(x0 - SURF_GAP, x1 + SURF_GAP, kind) for _, x0, x1, kind in SURFACES if kind != "spoiler"]
    xs = {0.0, 1.2, 2.4, 4.2, 6.0, 8.2, 10.4, 13.0, 16.5, X_ROOT_TIP, *WING_UV_CUTS}
    for a, b, _ in cuts:
        xs |= {a - 0.01, a, b, b + 0.01}
    rings = []
    for x in sorted(xs):
        le, c, t = wing_le(side, x)
        kind = next((k for a, b, k in cuts if a - 1e-6 <= x <= b + 1e-6), None)
        rings.append(airfoil(le, c, t, CDIR, TDIR, WING_CAMBER, cut=surface_hinge_fraction(kind, x) if kind else None))
    bm = bmesh.new()
    # Spanwise UV cuts at the outer pylon and the strut node break the 20 m skin into islands that pack.
    loft(bm, rings, seams=AF_SEAMS, soft=(AF_N,), cap_mat=(1, None),
         ring_seams=[sorted(xs).index(x) for x in WING_UV_CUTS])
    add_part(parts, "wing_root" + sfx, bm, ROOT_QC.copy(), "fuselage_M", mats=(SKIN, STRUCT), col=airframe(rings),
             bonded_to=",".join((["wing_root_R"] if side > 0 else []) + list(WING_ROOT_BONDS)))

    parent, thick = "wing_root" + sfx, interp(THICK, X_ROOT_TIP)
    axis = span_axis(side)
    for k, (name, chord, length, inset) in enumerate(TELE):
        thick *= TELE_THICK_RATIO
        outer = XI_ROOT_TIP - inset
        origin = qc_at(side, outer - length)
        # The middle ring marks the inner run that stays inside the parent even at full travel (bury_hidden_skin).
        run = outer - TRAVEL - 0.1
        xis = {outer - length, run, outer}
        if LONG_STAGES:
            xis |= {x * XI_PER_X for x in xs if outer - length < x * XI_PER_X < outer}
        xis = sorted(xis)
        rings = [tele_section(side, xi, chord, thick) for xi in xis]
        bm = bmesh.new()
        loft(bm, rings, seams=AF_SEAMS, soft=(AF_N,), cap_mat=(1, None))  # the inner end never leaves its parent
        if LONG_STAGES:
            col = airframe([rings[xis.index(run)], rings[-1]])
        else:
            col = airframe([rings[0], rings[-1]] if STAGE_COL_ENDS else rings)
        props = {}
        if STAGE_COL_ENDS:  # the volume its collider must keep (export_checks: stage_colliders_full)
            yz = [(p.y, p.z) for p in col[0]["rings"][0]]
            section = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(yz, yz[1:] + yz[:1]))) / 2
            props["col_ref_m3"] = round(section * abs(col[0]["rings"][1][0].x - col[0]["rings"][0][0].x), 3)
        if k == len(TELE) - 1:
            tip, tip_end = tip_rings(side, outer, chord, thick)
            loft(bm, tip, "cap", tip_end, seams=AF_SEAMS, soft=(AF_N,), cap_mat=(1, None))  # the root end sits inside the stage
            col += airframe(tip)
            props["tip_qc"] = list(qc_at(side, outer) - origin)  # where the tip's root quarter chord sits, in the part
        add_part(parts, name + sfx, bm, origin, parent, mats=(SKIN, STRUCT), col=col,
                 slide_axis=list(axis), travel_m=TRAVEL, chord_m=chord, thickness_m=round(thick, 4), **props)
        parent = name + sfx


def tip_rings(side, tip_xi, tip_chord, tip_thick):
    """Raked, upswept tip on the last stage. A short neck carries the stage section out to a cuff cut to the fixed
    wing's end section, so the retracted wing runs on without a step; extended, the cuff reads as a seal collar.
    The leading edge rakes aft by 30 degrees; the trailing edge continues the fixed wing's trailing-edge line, or with
    TIP_ROUND both close on a point. Returns the rings and the loft's end ("cap", or that point)."""
    base = qc_at(side, tip_xi + TIP_NECK)
    end_chord, end_thick = interp(CHORD, X_ROOT_TIP), interp(THICK, X_ROOT_TIP)
    rings = [tele_section(side, tip_xi - 0.05, tip_chord * 0.985, tip_thick * 0.985),
             tele_section(side, tip_xi + TIP_NECK, tip_chord, tip_thick)]
    w = span_axis(side, TIP_UPSWEEP)
    reach = (RETRACTED_SEMISPAN - 0.02 - abs(base.x)) / abs(w.x)
    fs = (0.0, 0.12, 0.35, 0.6, 0.85, 1.0) if TIP_ROUND is None else (0.0, 0.12, 0.3, 0.45, 0.6, 0.72, 0.83, 0.91, 0.97, 1.0)
    end = "cap"
    for f in fs:
        d = f * reach
        lateral = d * abs(w.x)
        te = base + w * d + 0.75 * end_chord * CDIR
        chord = end_chord - lateral * math.tan(TIP_RAKE) - 0.35 * f ** 3 * end_chord
        le, thick = te - chord * CDIR, end_thick * (1 - 0.55 * f)
        if TIP_ROUND is not None and f > TIP_ROUND[0]:
            g = (f - TIP_ROUND[0]) / (1 - TIP_ROUND[0])
            e = math.sqrt(max(0.0, 1 - g * g))
            le, chord, thick = le + (1 - e) * TIP_ROUND[1] * chord * CDIR, chord * e, thick * e
            if e == 0.0:
                end = camber_point(le, 1.0, CDIR, TDIR, 0.0, 0.0)
                break
        rings.append(airfoil(le, chord, thick, CDIR, TDIR, WING_CAMBER))
    return rings, end


def build_surfaces(parts, side):
    sfx = "L" if side > 0 else "R"
    for pattern, x0, x1, kind in SURFACES:
        name = pattern.format(s=sfx)
        xa, xb = x0, x1
        rings, hinges = [], []
        for x in (xa, (xa + xb) / 2, xb):
            le, c, t = wing_le(side, x)
            if kind == "spoiler":
                t0, t1 = SPOILER_CHORD
                ts = [t0 + (t1 - t0) * k / 3 for k in range(4)]
                top = [airfoil_point(le, c, t, CDIR, TDIR, WING_CAMBER, u, True) + TDIR * 0.035 for u in reversed(ts)]
                bot = [airfoil_point(le, c, t, CDIR, TDIR, WING_CAMBER, u, True) + TDIR * 0.004 for u in ts]
                rings.append(top + bot)
                hinges.append(airfoil_point(le, c, t, CDIR, TDIR, WING_CAMBER, t0, True) + TDIR * 0.02)
            else:
                t0 = surface_hinge_fraction(kind, x) + 0.02 / c
                rings.append(airfoil_aft(le, c, t, CDIR, TDIR, WING_CAMBER, t0))
                hinges.append(camber_point(le, c, CDIR, TDIR, WING_CAMBER, t0))
        bm = bmesh.new()
        loft(bm, rings, seams=(0, 3, 4, 7) if kind == "spoiler" else AFT_SEAMS)
        hinge_axis = hinges[-1] - hinges[0]
        add_hinged(parts, name, bm, hinges[0], "wing_root_" + sfx, hinge_axis)


STRUT_AF_N = 5


def build_struts(parts, side):
    sfx = "_L" if side > 0 else "_R"
    le, c, _ = wing_le(side, STRUT_WING_X)
    node = wing_lower(side, STRUT_WING_X, le.y + Y0 + STRUT_NODE_CHORD * c)
    root = Vector((side * STRUT_ROOT[0], st(STRUT_ROOT[1]), STRUT_ROOT[2]))
    ctrl = [root] + [Vector((side * x, st(s), z)) for x, s, z in STRUT_CTRL] + [node]

    def point(t):
        u = 1 - t
        return ctrl[0] * u ** 3 + ctrl[1] * (3 * u * u * t) + ctrl[2] * (3 * u * t * t) + ctrl[3] * t ** 3

    def tangent(t):
        u = 1 - t
        return ((ctrl[1] - ctrl[0]) * (3 * u * u) + (ctrl[2] - ctrl[1]) * (6 * u * t) + (ctrl[3] - ctrl[2]) * (3 * t * t)).normalized()

    def section(p, axis, chord, thick):
        cd = (Vector((0, 1, 0)) - axis * axis.y).normalized()
        td = axis.cross(cd).normalized()
        return airfoil(p - 0.4 * chord * cd, chord, thick, cd, td, n=STRUT_AF_N, te=0.01)

    # Root flares into the fairing, running 0.5 m inside it. The foot is pressed flat onto the wing skin, only 2 cm
    # deep, because the retracted stages fill the wing right behind the skin at the node.
    rings = [section(root - tangent(0) * 0.5, tangent(0), 0.85 * 1.45, 0.26 * 1.45)]
    for t in (0.0, 0.06, 0.14, 0.26, 0.4, 0.55, 0.7, 0.82, 0.92):
        k = 1 + 0.45 * max(0.0, 1 - t / 0.16) ** 2
        rings.append(section(point(t), tangent(t), 0.85 * k, 0.26 * k))
    foot = section(node, tangent(1), 0.85, 0.26)
    rings.append([Vector((p.x, p.y, wing_lower(side, abs(p.x), p.y + Y0, inset=0.02).z)) for p in foot])
    bm = bmesh.new()
    seams = (0, STRUT_AF_N, 2 * STRUT_AF_N)
    loft(bm, rings, seams=seams, soft=(STRUT_AF_N,), cap_mat=(1, 1))  # both ends buried: in the pod, on the wing
    # LOD1 can't be a hull of a bent strut: a coarse sweep of four sections through the bend, four points each.
    lod = [[r[k] for k in (0, 3, 5, 7)] for r in (rings[1], rings[4], rings[7], rings[-1])]
    # The collider stops at the last true section: the foot pressed flat onto the wing twists into a hollow.
    add_part(parts, "strut" + sfx, bm, root, "wing_root" + sfx, mats=(SKIN, STRUCT), col=airframe(rings[:-1]), lod=lod,
             bonded_to="strutfairing" + sfx)

    m = point(JURY_T)
    jle, jc, _ = wing_le(side, abs(m.x))
    top = wing_lower(side, abs(m.x), jle.y + Y0 + JURY_TOP_CHORD * jc, inset=0.1)
    axis = (top - m).normalized()
    rings = [section(m - axis * 0.12, axis, 0.45, 0.14), section(top, axis, 0.45, 0.14)]
    bm = bmesh.new()
    loft(bm, rings, seams=seams, soft=(STRUT_AF_N,), cap_mat=(1, 1))
    add_part(parts, "jury_strut" + sfx, bm, m, "strut" + sfx, mats=(SKIN, STRUCT), col=airframe(rings),
             bonded_to="wing_root" + sfx)

    # Strut-root fairing: a pod bulging 0.6 m past the fuselage side, holding the main bogie. It stays inside the
    # fuselage_M stations so it never overlaps the neighbouring fuselage parts.
    bm = bmesh.new()
    cx, cz, s0, half = side * 1.9, 2.4, STRUT_ROOT[1], 3.95
    rings = []
    for u in (-0.96, -0.85, -0.6, -0.25, 0.1, 0.45, 0.75, 0.92):
        f = (1 - abs(u) ** 2.5) ** 0.5
        rings.append([Vector((cx + 0.75 * f * math.sin(2 * math.pi * k / 16), st(s0 + u * half), cz + 1.2 * f * math.cos(2 * math.pi * k / 16)))
                      for k in range(16)])
    poles = Vector((cx, st(s0 - half), cz)), Vector((cx, st(s0 + half), cz))
    loft(bm, rings, *poles, seams=(8,))
    add_part(parts, "strutfairing" + sfx, bm, Vector((side * FUS_HALF_W, st(s0), cz)), "fuselage_M",
             col=airframe(rings, *poles))


# ---------- engines ----------
NACELLE_OUTER = ((1.48, -0.02), (1.53, 0.0), (1.575, 0.08), (1.6, 0.3), (1.6, 1.6), (1.56, 2.8), (1.46, 4.0), (1.32, 5.2))
NACELLE_INNER = ((1.22, 5.2), (1.32, 4.0), (1.42, 1.8), (1.425, 0.6), (1.385, 0.18), (1.40, 0.05), (1.44, -0.01))
NACELLE_LEN, FAN_STATION_OFFSET, FAN_BLADES = 5.2, 0.9, 20
CORE_DUCT = (0, 1)  # NACELLE_INNER segments aft of the fan: 5.2 to 4.0 m and 4.0 to 1.8 m
SPINNER_PROFILE = ((0, -0.55), (0.22, -0.42), (0.38, -0.2), (0.46, 0.05), (0.47, 0.25), (0, 0.3))
SLEEVE_PROFILE = ((1.27, -0.3), (1.30, 0.0), (1.22, 0.45), (1.14, 0.75), (1.10, 0.75), (1.14, 0.3), (1.16, -0.3))
CORE_PROFILE = ((0, -0.3), (0.95, -0.3), (0.93, 0.35), (0.80, 0.85), (0.60, 0.87), (0.50, 1.05), (0.28, 1.3), (0, 1.5))
CHEVRONS, CHEVRON_LEN = 12, 0.22
PYLON_ROOT_DEPTH = 0.15  # how far the pylon runs into the nacelle crown and into the wing underside


def nacelle_crown(a):
    return NACELLE_Z + interp([(ax, r) for r, ax in NACELLE_OUTER[2:]], min(max(a, 0.08), NACELLE_LEN))


def build_engines(parts):
    for num, side, x, front in NACELLES:
        sfx = "_L" if side > 0 else "_R"
        intake = Vector((side * x, st(front), NACELLE_Z))
        bm = bmesh.new()
        # UV: cowl, rear annulus, duct and lip strip, each cut along the crown and keel into mirror halves.
        n_out = len(NACELLE_OUTER)
        faces = revolve(bm, NACELLE_OUTER + NACELLE_INNER, intake, seg=32, loop=True, seams=(0, 16),
                        ring_seams=(0, n_out - 1, n_out, n_out + len(NACELLE_INNER) - 1))
        for r in CORE_DUCT:  # the duct behind the fan face is engine core, never seen past the blades
            for f in faces[(n_out + r) * 32:(n_out + r + 1) * 32]:
                f.material_index = 1
        # The collider is the solid cowl: the fan and nozzle fill the duct.
        cowl = [[intake + Vector((r * math.sin(2 * math.pi * i / 32), a, r * math.cos(2 * math.pi * i / 32))) for i in range(32)]
                for r, a in NACELLE_OUTER]
        add_part(parts, f"nacelle_{num}", bm, intake, f"pylon_{num}", mats=(SKIN, MECH), col=airframe(cowl))

        # Fan: spinner set back 0.35 m inside the lip and 20 twisted wide-chord blades.
        fan_c = intake + Vector((0, FAN_STATION_OFFSET, 0))
        bm = bmesh.new()
        revolve(bm, SPINNER_PROFILE, fan_c, seg=16)
        for i in range(FAN_BLADES):
            phi = 2 * math.pi * (i + 0.5) / FAN_BLADES
            er, et = Vector((math.sin(phi), 0, math.cos(phi))), Vector((math.cos(phi), 0, -math.sin(phi)))
            rings = []
            for r, beta, chord, th in ((0.4, 58, 0.36, 0.06), (0.9, 42, 0.42, 0.045), (1.37, 28, 0.46, 0.03)):
                b = math.radians(beta)
                cd = et * math.cos(b) + Vector((0, 1, 0)) * math.sin(b)
                nd = er.cross(cd).normalized()
                c = fan_c + er * r
                rings.append([c + cd * (u * chord / 2) + nd * (v * th / 2) for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
            loft(bm, rings)
        add_part(parts, f"fan_{num}", bm, fan_c, f"nacelle_{num}", mats=(MECH,), spin_axis=[0.0, 1.0, 0.0])

        # Nozzle: a fan sleeve with a chevron-serrated trailing edge round a core cowl and plug.
        rear = intake + Vector((0, NACELLE_LEN, 0))
        seg = 2 * CHEVRONS

        def chevron(pi, i, r, a):
            if pi in (3, 4):  # trailing-edge rings, outer and inner
                return (r - 0.05, a + CHEVRON_LEN) if i % 2 == 0 else (r, a - 0.03)
            return r, a

        bm = bmesh.new()
        n_sl = len(SLEEVE_PROFILE)
        revolve(bm, SLEEVE_PROFILE, rear, seg=seg, loop=True, shape=chevron, seams=(0, CHEVRONS), ring_seams=(0, 3, 4, n_sl - 1))
        for f in revolve(bm, CORE_PROFILE, rear, seg=seg):
            f.material_index = 1
        add_part(parts, f"nozzle_{num}", bm, rear, f"nacelle_{num}", mats=(SKIN, MECH))

        # Pylon: a swept blade from the nacelle crown up into the wing underside, a lens section thickest at 40% of
        # its depth. The leading edge rises from behind the intake lip to tuck under the wing leading edge; the
        # trailing fairing runs aft over the fan sleeve and closes up under the wing.
        le, c, _ = wing_le(side, x)
        le_station = le.y + Y0

        def ring(s, bot, top, half):
            mid = bot + 0.4 * (top - bot)
            return [Vector((side * x + dx * half, st(s), z)) for dx, z in
                    ((-0.7, bot), (0.7, bot), (1.0, mid), (0.75, top), (-0.75, top), (-1.0, mid))]

        def crown(s):
            return nacelle_crown(s - front) - PYLON_ROOT_DEPTH

        def under(s):
            return wing_lower(side, x, s).z + PYLON_ROOT_DEPTH

        rings = [ring(front + 0.7, crown(front + 0.7), crown(front + 0.7) + 0.2, 0.09),
                 ring(le_station - 0.2, crown(le_station - 0.2), le.z - 0.06, 0.22),
                 ring(le_station + 0.45, crown(le_station + 0.45), under(le_station + 0.45), 0.25),
                 ring(front + 4.4, crown(front + 4.4), under(front + 4.4), 0.25),
                 ring(front + 6.0, under(front + 6.0) - 0.34, under(front + 6.0), 0.11)]
        bm = bmesh.new()
        loft(bm, rings, seams=(0, 1, 3, 4))
        attach = wing_lower(side, x, le_station + 0.25 * c)
        add_part(parts, f"pylon_{num}", bm, Vector((side * x, attach.y, attach.z)), "wing_root" + sfx,
                 col=airframe(rings))


# ---------- tail ----------
def vtail_section(side, d, cut=None, t0=None):
    span_dir = Vector((side * math.cos(VTAIL_DIHEDRAL), 0, math.sin(VTAIL_DIHEDRAL)))
    normal = Vector((-side * math.sin(VTAIL_DIHEDRAL), 0, math.cos(VTAIL_DIHEDRAL)))
    root_le = Vector((side * 1.45, st(VTAIL_ROOT_STATION), VTAIL_ROOT_Z))
    f = d / VTAIL_SPAN
    chord = VTAIL_ROOT_CHORD + (VTAIL_TIP_CHORD - VTAIL_ROOT_CHORD) * f
    le = root_le + span_dir * d + Vector((0, d * math.tan(VTAIL_SWEEP), 0))
    thick = chord * (0.10 - 0.03 * max(f, 0))
    if t0 is not None:
        return airfoil_aft(le, chord, thick, Vector((0, 1, 0)), normal, 0.0, t0), camber_point(le, chord, Vector((0, 1, 0)), normal, 0.0, t0)
    return airfoil(le, chord, thick, Vector((0, 1, 0)), normal, cut=cut), root_le


def build_vtail(parts, side):
    sfx = "_L" if side > 0 else "_R"
    d0, d1 = RUDDERVATOR_SPAN
    ds = sorted({-0.45, 0.0, 2.0, 4.2, VTAIL_SPAN, d0 - SURF_GAP - 0.01, d0 - SURF_GAP, d1 + SURF_GAP, d1 + SURF_GAP + 0.01})
    rings = [vtail_section(side, d, RUDDERVATOR_HINGE if d0 - SURF_GAP - 1e-6 <= d <= d1 + SURF_GAP + 1e-6 else None)[0] for d in ds]
    root_le = vtail_section(side, 0.0)[1]
    bm = bmesh.new()
    loft(bm, rings, seams=AF_SEAMS, soft=(AF_N,), cap_mat=(1, None))  # the root end is buried in the tail cone
    add_part(parts, "vtail" + sfx, bm, root_le + Vector((0, 0.25 * VTAIL_ROOT_CHORD, 0)), "tailcone",
             mats=(SKIN, STRUCT), col=airframe(rings))

    t0 = RUDDERVATOR_HINGE + 0.02 / VTAIL_TIP_CHORD
    secs = [vtail_section(side, d, t0=t0) for d in (d0, (d0 + d1) / 2, d1)]
    bm = bmesh.new()
    loft(bm, [r for r, _ in secs], seams=AFT_SEAMS)
    add_hinged(parts, "ruddervator" + sfx, bm, secs[0][1], "vtail" + sfx, secs[-1][1] - secs[0][1],
               up=Vector((-side * math.sin(VTAIL_DIHEDRAL), 0, math.cos(VTAIL_DIHEDRAL))))


def build_tail_systems(parts):
    _, top, bot = fus_profile(TAIL_END[-1][0])
    zc = (top + bot) / 2
    ball = Vector((0, st(42.3), zc))
    bm = bmesh.new()
    sphere(bm, ball, 0.44, seams=(8,))
    add_part(parts, "laser_turret", bm, ball, "tailcone")
    bm = bmesh.new()
    cylinder(bm, ball, Vector((0, st(42.95), zc)), 0.06, seg=8)
    add_part(parts, "laser_barrel", bm, ball, "laser_turret", mats=(MECH,))
    # Tail radar: a dielectric panel wrapping the underside of the upswept cone, scanner looking aft and down.
    bm = bmesh.new()
    skin_panel(bm, (38.9, 39.6, 40.3, 41.0, 41.5), 118, 242, -0.01, 0.035, n_a=8, inner_mat=1)
    add_part(parts, "radar_R_fairing", bm, fus_point(40.2, 180), "tailcone", mats=(SKIN, STRUCT))


# ---------- doors ----------
BAY_HINGE_DEG = 141.0  # each bay door's hinge line, degrees round from the crown on the +X side


def build_baydoors(parts):
    """Belly doors over each bay, closed, hinged on their outboard edges."""
    for bay, s0, s1, parent in BAYS:
        for sfx, a0, a1, hinge_a in (("L", BAY_HINGE_DEG, 178.6, BAY_HINGE_DEG),
                                     ("R", 181.4, 360.0 - BAY_HINGE_DEG, 360.0 - BAY_HINGE_DEG)):
            stations = [s0 + 0.4 + (s1 - s0 - 0.8) * k / 4 for k in range(5)]
            bm = bmesh.new()
            skin_panel(bm, stations, a0, a1, 0.006, 0.045, n_a=5, inner_mat=1)
            hinge = fus_point((s0 + s1) / 2, hinge_a, 0.02)
            add_hinged(parts, f"baydoor_{bay}{sfx}", bm, hinge, parent, Vector((0, 1, 0)), mats=(SKIN, STRUCT))


def fus_bottom_z(s, x):
    w, top, bot = fus_profile(s)
    zc, h = (top + bot) / 2, (top - bot) / 2
    return zc - h * (1 - min(abs(x) / w, 1.0) ** FUS_P) ** (1 / FUS_P)


def door_plate(bm, x, stations, top_fn, bottom, inner, thick=0.04):
    """A vertical door plate; inner (+1 or -1) is the x direction its well-side face looks, which takes slot 1."""
    rings = [[Vector((x + dx, st(s), z)) for dx, z in ((-thick / 2, bottom), (thick / 2, bottom), (thick / 2, top_fn(s)), (-thick / 2, top_fn(s)))]
             for s in stations]
    faces = loft(bm, rings, seams=(0, 1, 2, 3))
    for i, f in enumerate(faces[:4 * (len(rings) - 1)]):
        if i % 4 == (1 if inner > 0 else 3):  # face 1 looks +x, face 3 looks -x
            f.material_index = 1


def build_geardoors(parts):
    """Gear doors, open with the gear down: nose doors either side of the nose leg, main doors along each pod."""
    for sfx, side in (("L", 1), ("R", -1)):
        x = side * 0.72
        stations = (3.95, 5.4, 6.85)
        bm = bmesh.new()
        door_plate(bm, x, stations, lambda s: fus_bottom_z(s, x) + 0.04, NOSE_DOOR_BOTTOM, inner=-side)
        hinge = Vector((x, st(5.4), fus_bottom_z(5.4, x)))
        add_hinged(parts, f"geardoor_F{sfx}", bm, hinge, "nose", Vector((0, 1, 0)), mats=(SKIN, STRUCT))

        # Main door on the pod's inboard underside; its top edge follows the pod skin.
        cx, xd = side * 1.9, side * 1.5

        def pod_z(s):
            f = (1 - min(abs((s - STRUT_ROOT[1]) / 3.95), 1.0) ** 2.5) ** 0.5
            sn = min(abs(xd - cx) / (0.75 * f), 1.0)
            return 2.4 - 1.2 * f * math.sqrt(1 - sn * sn) + 0.05

        bm = bmesh.new()
        door_plate(bm, xd, (16.6, 17.8, 19.0, 20.2, 21.4), pod_z, 0.75, inner=side)
        hinge = Vector((xd, st(STRUT_ROOT[1]), pod_z(STRUT_ROOT[1]) - 0.05))
        add_hinged(parts, f"geardoor_{sfx}M", bm, hinge, "strutfairing_" + sfx, Vector((0, 1, 0)), mats=(SKIN, STRUCT))


# ---------- landing gear placeholders ----------
def build_gear(parts):
    pivot = Vector((0, st(NOSE_GEAR_STATION), FUS_BOTTOM + 0.3 if NOSE_PIVOT_Z is None else NOSE_PIVOT_Z))
    axle = Vector((0, st(NOSE_GEAR_STATION), 0.55))
    bm = bmesh.new()
    cylinder(bm, pivot, axle, 0.14)
    cylinder(bm, axle + Vector((-0.25, 0, 0)), axle + Vector((0.25, 0, 0)), 0.08)
    add_part(parts, "gear_F", bm, pivot, "nose", mats=(GEAR,), retracts="forward")
    bm = bmesh.new()
    for dx in (-0.4, 0.4):
        cylinder(bm, axle + Vector((dx - 0.15, 0, 0)), axle + Vector((dx + 0.15, 0, 0)), 0.55, seg=16)
    add_part(parts, "wheel_F", bm, axle, "gear_F", mats=(GEAR,))

    for side, sfx in ((1, "LM"), (-1, "RM")):
        x = side * MAIN_TRACK / 2
        pivot = Vector((x if MAIN_PIVOT_X is None else side * MAIN_PIVOT_X, st(MAIN_GEAR_STATION),
                        FUS_BOTTOM + 0.6 if MAIN_PIVOT_Z is None else MAIN_PIVOT_Z))
        beam = Vector((x, st(MAIN_GEAR_STATION), 0.6))
        bm = bmesh.new()
        cylinder(bm, pivot, beam + Vector((0, 0, 0.1)), 0.18)
        box(bm, beam, (0.3, 3.2, 0.25))
        add_part(parts, "gear_" + sfx, bm, pivot, f"{SPONSON}_" + ("L" if side > 0 else "R"), mats=(GEAR,))
        bm = bmesh.new()
        for dy in (-1.4, 0.0, 1.4):
            for dx in (-0.42, 0.42):
                c = beam + Vector((dx, dy, 0))
                cylinder(bm, c - Vector((0.18, 0, 0)), c + Vector((0.18, 0, 0)), 0.6, seg=16)
        add_part(parts, "wheel_" + sfx, bm, beam, "gear_" + sfx, mats=(GEAR,))


# ---------- scene assembly ----------
def add_part(parts, name, bm, origin, parent, mats=(SKIN,), basis=None, col=None, lod=None, **props):
    """mats: material names indexed by face material_index. col: collider sources, each {"rings", "start", "end"}
    as for loft, plus "owner" when the collider belongs to another part (see build_colliders). lod: rings lofted
    into the LOD1 mesh in place of a hull."""
    parts.append({"name": name, "bm": bm, "origin": origin, "parent": parent, "mats": mats, "basis": basis,
                  "col": col or [], "lod": lod, "props": props})


def add_hinged(parts, name, bm, hinge, parent, axis, mats=(SKIN,), up=Vector((0, 0, 1))):
    basis = frame(axis, up)
    add_part(parts, name, None, hinge, parent, basis=basis, hinge_axis=list(basis.col[0]))
    add_part(parts, name + "_visible", bm, hinge, name, mats=mats, basis=basis)


# Viewport and Workbench colours only: the game look comes from the baked atlas and the stock trims.
MATERIALS = {SKIN: (0.62, 0.62, 0.62, 1.0), MECH: (0.28, 0.28, 0.29, 1.0), STRUCT: (0.42, 0.43, 0.42, 1.0),
             GLASS: (0.06, 0.07, 0.08, 1.0), GEAR: (0.50, 0.50, 0.51, 1.0), LOD: (0.14, 0.14, 0.14, 1.0)}


def remove_objects(objs):
    for obj in list(objs):
        data = obj.data
        bpy.data.objects.remove(obj)
        if data is not None and data.users == 0:
            store = {bpy.types.Mesh: bpy.data.meshes, bpy.types.TextCurve: bpy.data.curves,
                     bpy.types.Camera: bpy.data.cameras}.get(type(data), bpy.data.lights)
            store.remove(data)


def reset_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is not None:
        remove_objects(coll.all_objects)
        for child in coll.children_recursive:
            bpy.data.collections.remove(child)
        bpy.data.collections.remove(coll)
    coll = bpy.data.collections.new(name)
    scene.collection.children.link(coll)
    return coll


def material(name, rgba):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = rgba
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
    return mat


def set_extension(objs, extension):
    for obj in objs.values():
        if "slide_axis" in obj:
            obj.location = Vector(obj["rest_location"]) + Vector(obj["slide_axis"]) * (TRAVEL * extension)
    bpy.context.view_layer.update()


EXTRA_BUILDERS = ()  # parts a later step adds (step 6: the spine cover)
PART_SPLITS = False  # step 6.1: the finer part tree (art/blender/part_splits.py), applied after the colliders


def build(extension):
    """Build the aircraft and its export data at rest, then slide the stages to extension. Returns the render parts
    by name and a report of the export stages."""
    coll = reset_collection("Centurion")
    subs = {}
    for name in ("Colliders", "LOD1"):
        subs[name] = bpy.data.collections.new(name)
        coll.children.link(subs[name])
    mats = {k: material(k, v) for k, v in MATERIALS.items()}
    parts = []
    build_fuselage(parts)
    build_wingfairing(parts)
    for side in (1, -1):
        build_wing(parts, side)
        build_surfaces(parts, side)
        build_struts(parts, side)
        build_vtail(parts, side)
    build_engines(parts)
    build_tail_systems(parts)
    build_baydoors(parts)
    build_geardoors(parts)
    build_gear(parts)
    for extra in EXTRA_BUILDERS:
        extra(parts)

    objs, world = {}, {}
    for p in parts:
        m = Matrix.Translation(p["origin"]) @ (p["basis"] or Matrix.Identity(3)).to_4x4()
        world[p["name"]] = m
        if p["bm"] is None:
            obj = bpy.data.objects.new(p["name"], None)
            obj.empty_display_type, obj.empty_display_size = "ARROWS", 0.8
        else:
            bm = p["bm"]
            orient_outward(bm)
            bmesh.ops.transform(bm, matrix=m.inverted(), verts=bm.verts)
            me = bpy.data.meshes.new(p["name"])
            bm.to_mesh(me)
            bm.free()
            for k in p["mats"]:
                me.materials.append(mats[k])
            obj = bpy.data.objects.new(p["name"], me)
        coll.objects.link(obj)
        for k, v in p["props"].items():
            obj[k] = v
        objs[p["name"]] = obj
    for p in parts:
        obj = objs[p["name"]]
        if p["parent"]:
            obj.parent = objs[p["parent"]]
            obj.matrix_parent_inverse.identity()
            obj.matrix_basis = world[p["parent"]].inverted() @ world[p["name"]]
        else:
            obj.matrix_basis = world[p["name"]]
    for obj in objs.values():
        if "slide_axis" in obj:
            obj["rest_location"] = list(obj.location)
    bpy.context.view_layer.update()
    if WELL_OPEN:
        cut_well_slot(objs, mats[STRUCT])
    if AFT_BAY_ROOF:
        cut_box(objs, AFT_BAY_SKINS, *aft_bay_box(), mats[STRUCT], "aft_bay")

    report = {"buried_skin_faces": bury_hidden_skin(objs, mats[STRUCT])}
    for obj in objs.values():
        if obj.type == "MESH":
            order_slots(obj)
    report["colliders"] = build_colliders(parts, objs, world, subs["Colliders"])
    if PART_SPLITS:
        import part_splits
        report["splits"] = part_splits.apply_blockout(sys.modules[__name__], objs, world, subs["Colliders"], mats,
                                                       report["colliders"])
    report["lod1"] = build_lod1(parts, objs, world, subs["LOD1"], mats[LOD])
    report["uv"] = unwrap_skin(objs)
    report["hard_edges"] = bake_normals(objs)
    set_extension(objs, extension)
    return objs, report


# ---------- material slots ----------
BURY_DEPTH = 0.002


BAY_COVER = 0.06  # skin this close under a closed bay door is the bay opening
# Spacing of the points a skin face is tested at besides its corners. Corners alone bury a long hull face whose two ends
# sit in different parts with skin showing between them: fuselage_M's 6.6 m belly quads, one end in the strut root
# fairing and the other in the sponson, showed the stock structure trim in game between the two.
FACE_SAMPLE = 0.25


def mesh_geo(meshes):
    """Each mesh's world vertices, BVH tree and bounds; a thin-walled detailed part (m4/airframe.py) answers with its
    closed envelope, the hull before its joints opened, so what was sealed inside it stays sealed."""
    geo = {}
    for o in meshes:
        v, p = world_mesh(o)
        env = o.get("_envelope_mesh")
        if env is not None:
            mw = o.matrix_world
            ev, ep = [mw @ x.co for x in env.vertices], [tuple(q.vertices) for q in env.polygons]
            geo[o.name] = (v, BVHTree.FromPolygons(ev, ep), bounds(v))
            continue
        geo[o.name] = (v, BVHTree.FromPolygons(v, p), bounds(v))
    return geo


def buried_verts(verts, others):
    """Which points sit more than BURY_DEPTH inside any of the other closed meshes (tree, box)."""
    hidden = [False] * len(verts)
    for tree, box_ in others:
        for i, p in enumerate(verts):
            if hidden[i] or not boxes_touch((p, p), box_, 0.0):
                continue
            loc, normal, _, dist = tree.find_nearest(p)
            hidden[i] = (p - loc).dot(normal) < 0 and dist > BURY_DEPTH and inside(p, tree)
    return hidden


def face_samples(verts, face):
    """Points over a face no more than FACE_SAMPLE apart, corners included: a barycentric grid on each fan triangle.
    The same face on another pose's verts gives its points in the same order."""
    pts, v0 = [], verts[face[0]]
    for i in range(1, len(face) - 1):
        a, b = verts[face[i]] - v0, verts[face[i + 1]] - v0
        n = max(1, math.ceil(max(a.length, b.length, (b - a).length) / FACE_SAMPLE))
        pts += [v0 + a * (p / n) + b * (q / n) for p in range(n + 1) for q in range(n + 1 - p)]
    return pts


def bury_hidden_skin(objs, struct):
    """Skin faces nobody sees while the aircraft is whole move to aircraft_structure, so they cost no atlas texels
    and show as structure once a part has broken off:
    - faces sealed inside other parts at rest, at every point FACE_SAMPLE apart over the face (a wing root in the
      fuselage, the fairing's lower half, a strut root in its pod, a pylon's ends in the nacelle and wing);
    - a telescoping stage's faces still inside its chain at full extension (inside at every extension);
    - fuselage skin under a closed bay door, which is the bay opening.
    A face moves only if it is hidden on every part sharing its UV islands, so mirrored twins keep matching
    materials. Returns faces moved per part."""
    meshes = [o for o in objs.values() if o.type == "MESH"]
    geo = mesh_geo(meshes)
    set_extension(objs, 1.0)
    chain_geo = mesh_geo([o for o in meshes if wing_chain(o)])
    set_extension(objs, 0.0)
    doors = {o.name: geo[o.name][1] for o in meshes if o.name.startswith("baydoor_")}
    hidden_faces = {}
    for a in meshes:
        skin = slot_faces(a, SKIN)
        if not skin:
            continue
        verts, _, abox = geo[a.name]
        others = [(tree, box_) for b, (_, tree, box_) in geo.items()
                  if b != a.name and not (wing_chain(a) and wing_chain(a) == wing_chain(objs[b])) and boxes_touch(abox, box_, 0.0)]
        # A stage sits inside its root at rest, wherever else that is (step 6.1's run into the body), so only full
        # extension tells which of its faces stay hidden.
        stage = wing_chain(a) and a.name[:-2] in WING_STAGES
        hidden = [False] * len(verts) if stage else buried_verts(verts, others)
        chain_others = None
        if wing_chain(a):
            chain_others = [(tree, box_) for b, (_, tree, box_) in chain_geo.items()
                            if b != a.name and wing_chain(objs[b]) == wing_chain(a)]
            ext = buried_verts(chain_geo[a.name][0], chain_others)
            hidden = [h or e for h, e in zip(hidden, ext)]

        def covered(face):
            """Every sample point over the face hidden, by the same rest-or-extension rule as the corners."""
            pts = face_samples(verts, face)
            sealed = [False] * len(pts) if stage else buried_verts(pts, others)
            if chain_others is not None:
                ext = buried_verts(face_samples(chain_geo[a.name][0], face), chain_others)
                sealed = [h or e for h, e in zip(sealed, ext)]
            return all(sealed)

        mw = a.matrix_world
        rot = mw.to_3x3()
        faces = set()
        for i in skin:
            f = a.data.polygons[i]
            if all(hidden[v] for v in f.vertices) and covered(f.vertices):
                faces.add(i)
            elif doors:
                n = (rot @ f.normal).normalized()
                c = mw @ f.center + n * 0.001
                if any(name != a.name and tree.ray_cast(c, n, BAY_COVER)[0] is not None
                       for name, tree in doors.items()):
                    faces.add(i)
        hidden_faces[a.name] = faces
    moved = {}
    for name, faces in hidden_faces.items():
        twins = [n for n in hidden_faces if (mirror_source(n) or n) == (mirror_source(name) or name)]
        if all(len(objs[n].data.polygons) == len(objs[name].data.polygons) for n in twins):
            faces = set.intersection(*(hidden_faces[n] for n in twins))
        if not faces:
            continue
        me = objs[name].data
        if STRUCT not in [m.name for m in me.materials]:
            me.materials.append(struct)
        k = [m.name for m in me.materials].index(STRUCT)
        for i in faces:
            me.polygons[i].material_index = k
        moved[name] = len(faces)
    return moved


def order_slots(obj):
    """Material slots in SLOT_ORDER, only those a face uses, so submesh 0 is the skin wherever there is skin."""
    me = obj.data
    names = [m.name for m in me.materials]
    by_name = {m.name: m for m in me.materials}
    used = sorted({names[p.material_index] for p in me.polygons}, key=SLOT_ORDER.index)
    index = [used.index(names[p.material_index]) for p in me.polygons]
    me.materials.clear()
    for name in used:
        me.materials.append(by_name[name])
    me.polygons.foreach_set("material_index", index)


def slot_faces(obj, name):
    slots = [m.name for m in obj.data.materials]
    if name not in slots:
        return []
    k = slots.index(name)
    return [p.index for p in obj.data.polygons if p.material_index == k]


# ---------- colliders ----------
LOAD_PARTS = (("nose", "fuselage_F", "fuselage_M", "fuselage_R", "tailcone")
              + tuple(f"{p}_{s}" for s in "LR" for p in ("wing_root", "wing_tele1", "wing_tele2", "strut",
                                                          "jury_strut", "strutfairing", "vtail"))
              + tuple(f"{p}_{n}" for n in range(1, 5) for p in ("nacelle", "pylon")))
COL_INSET = 0.028  # every hull face plane moves this far inside the skin, leaving 8 mm for shallow hollows
COL_MIN_DEPTH = 0.02  # and no sampled point of a collider may sit shallower than this
COL_INSET_EXACT = False  # step 6 sets it: convex.inset_hull rebuilds insets its fast path collapses
# Step 6 sets it: a telescoping stage's collider lofts only its two end sections. Its middle ring (the run that stays
# inside the parent, for bury_hidden_skin) is a copy of the ends moved along the stage, so the hull has faces across
# nearly collinear points whose normals point anywhere, and their moved planes cut the inset to a sliver: stage 1's
# came out 0.24 of about 7 m3, which left it 42 kg m2 of pitch inertia in game, too little to hold stage 2's slider.
STAGE_COL_ENDS = False
# Step 6.1 sets it: each stage runs nearly the root's length, its inner run inside the body when retracted. The stage
# takes a ring at each of the root's sections, so the nesting and slide checks see it beside every cut-out; its collider
# lofts only the run that can leave the parent (from the middle ring to the outer end), which clears the body's
# collider retracted and still starts inside the parent at full travel; and the engine pylon's top, which the stages
# now slide over, is held 10 cm into the wing's underside (build_engines_s6).
LONG_STAGES = False
# Step 6.1 sets it: the AWACS spine well is open. Its slot is cut through the crown skins (cut_well_slot), and every
# part's collider but fuselage_R's stands clear of it (clear_of_well), since the beam mount's joint excludes only
# fuselage_R (docs/M3-DESIGN.md "Airframe work for the well").
WELL_OPEN = False
COL_MAX_VERTS = 128  # SPEC allows 255; 128 also keeps a hull under PhysX's 255-polygon limit
EXTENSIONS_CHECKED = (0.0, 0.5, 1.0)  # stage extensions the overlap and collider checks run at


def extension_key(e):
    """An extension as a metrics key: one decimal where that is exact ("0.5"), else two ("0.25")."""
    return f"{e:.1f}" if round(e, 1) == e else f"{e:.2f}"
SLIVER = 0.05  # two rings this close (a cut-out's edge) may fall between pieces instead of forming one


def signed_depth(tree, p):
    """How far inside a closed surface p sits (negative outside)."""
    loc, normal, _, dist = tree.find_nearest(p)
    return dist if (p - loc).dot(normal) < 0 else -dist


def signed_volume(faces):
    """Six times the signed volume the faces' fans enclose about the origin, summed in double precision: mathutils
    works in single, where a small shell far from the origin (a V-tail tip's hinge fitting, 24 m out) reads noise."""
    vol = 0.0
    for f in faces:
        (ax, ay, az), *rest = [tuple(v.co) for v in f.verts]
        for (bx, by, bz), (cx, cy, cz) in zip(rest, rest[1:]):
            vol += ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx)
    return vol


def orient_outward(bm):
    """recalc_face_normals, then every closed shell it left with a negative volume turned out: its heuristic can pick
    the wrong side of a shell with paper-thin sections (step 6's strut foot, a V-tail run of cut sections)."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.faces.index_update()
    seen = set()
    for f in bm.faces:
        if f.index in seen:
            continue
        shell, stack = [], [f]
        seen.add(f.index)
        while stack:
            g = stack.pop()
            shell.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        if signed_volume(shell) < 0:
            bmesh.ops.reverse_faces(bm, faces=shell)


def envelope(src):
    bm = bmesh.new()
    loft(bm, src["rings"], src["start"], src["end"])
    orient_outward(bm)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return tree


def collider_piece(points, tree):
    """The inset convex hull of points, thinned to COL_MAX_VERTS, with the depth of its vertices, face centres and
    edge midpoints inside the skin; None when the inset leaves nothing."""
    pts = np.array([p[:] for p in points])
    for budget in (120, 90, 64, 48, 36, 28):  # the inset can add vertices where many planes meet (a pole)
        hull = convex.inset_hull(convex.simplify_hull(pts, budget), COL_INSET, COL_INSET_EXACT)
        if hull is None:
            return None
        if len(hull[0]) <= COL_MAX_VERTS:
            break
    v, t = hull
    tri = v[t]
    samples = np.concatenate([v, tri.mean(1), ((tri + tri[:, [1, 2, 0]]) / 2).reshape(-1, 3)])
    depth = [signed_depth(tree, Vector(s)) for s in samples]
    return {"verts": v, "tris": t, "min_depth": min(depth), "vertex_depth": (min(depth[:len(v)]), max(depth[:len(v)]))}


def collider_pieces(src):
    """Split a lofted source into convex pieces along its rings: a piece grows ring by ring while its inset hull stays
    COL_MIN_DEPTH inside the skin, so no hull bridges a cut-out, a bend or a fairing's step. Neighbouring pieces
    share their boundary ring. Returns the pieces and the indices of rings skipped as slivers."""
    rings, start, end = src["rings"], src["start"], src["end"]
    tree = envelope(src)
    last = len(rings) - 1

    def points(i, j):
        pts = [p for r in rings[i:j + 1] for p in r]
        if i == 0 and isinstance(start, Vector):
            pts.append(start)
        if j == last and isinstance(end, Vector):
            pts.append(end)
        return pts

    def centre(ring):
        return sum(ring, Vector()) / len(ring)

    pieces, skipped, i = [], [], 0
    while i < last:
        best, j = None, i + 1
        while j <= last:
            piece = collider_piece(points(i, j), tree)
            if piece is None or piece["min_depth"] < COL_MIN_DEPTH:
                break
            best, j = (j, piece), j + 1
        if best is None:
            if (centre(rings[i + 1]) - centre(rings[i])).length < SLIVER:
                skipped.append(i)
                i += 1
                continue
            best = (i + 1, collider_piece(points(i, i + 1), tree))  # kept though shallow; the metrics flag it
        if best[1] is not None:
            pieces.append(best[1])
        i = best[0]
    return pieces, skipped


def hull_object(name, verts, tris, to_local, parent, coll):
    """A mesh object from world-space hull data, parented to its part with an identity local transform."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([to_local @ Vector(v) for v in verts], [], [tuple(int(i) for i in t) for t in tris])
    me.update()
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
    obj.parent = parent
    obj.matrix_parent_inverse.identity()
    obj.matrix_basis = Matrix.Identity(4)
    obj.hide_render = True
    return obj


def build_colliders(parts, objs, world, coll):
    """<part>_colmesh, <part>_colmesh.001, ... for every load-carrying part, in the part's local space."""
    sources = {}
    for p in parts:
        for src in p["col"]:
            sources.setdefault(src.get("owner", p["name"]), []).append(src)
    report = {}
    for owner, srcs in sources.items():
        pieces, skipped = [], 0
        for src in srcs:
            got, skip = collider_pieces(src)
            if WELL_OPEN and owner != "fuselage_R":
                tree = envelope(src)
                got = [clear_of_well(piece, tree) for piece in got]
            if AFT_BAY_ROOF and owner in AFT_BAY_SKINS:
                tree = envelope(src)
                got = [q for piece in got for q in clear_of_aft_bay(piece, tree)]
            if NOSE_EXITS and owner == "nose":
                tree = envelope(src)
                got = [q for piece in got for q in clear_of_hatches(piece, tree)]
            pieces, skipped = pieces + got, skipped + len(skip)
        for k, piece in enumerate(pieces):
            name = f"{owner}_colmesh" + (f".{k:03d}" if k else "")
            hull_object(name, piece["verts"], piece["tris"], world[owner].inverted(), objs[owner], coll)
            report[name] = {"owner": owner, "verts": len(piece["verts"]), "tris": len(piece["tris"]),
                            "min_depth_m": round(piece["min_depth"], 4),
                            "vertex_depth_m": [round(d, 4) for d in piece["vertex_depth"]],
                            "sliver_rings_skipped": skipped}
            for clip in ("well_clip", "aft_bay_clip", "hatch_clip"):
                if clip in piece:
                    report[name][clip] = piece[clip]
    return report


# ---------- LOD1 ----------
LOD1_GREY = 0.14
LOD1_TOTAL_MIN = 800  # "about 1000"


def lod1_table():
    """Detachable part: (hull vertex budget, parts folded into its hull). A hull of V vertices has 2V - 4
    triangles. A budget of None lofts the part's lod rings instead (the bent strut)."""
    t = {"radar_F_fairing": (12, ()), "nose": (17, ()), "fuselage_F": (17, ()), "fuselage_M": (17, ("wingfairing",)),
         "fuselage_R": (17, ()), "tailcone": (17, ("radar_R_fairing",)), "laser_turret": (9, ("laser_barrel",)),
         "gear_F": (12, ("wheel_F",))}
    for s in "LR":
        t.update({f"wing_root_{s}": (17, (f"flap_{s}1_visible", f"flap_{s}2_visible", f"aileron_{s}_visible")),
                  f"wing_tele1_{s}": (17, ()), f"wing_tele2_{s}": (17, ()),
                  f"strut_{s}": (None, ()), f"jury_strut_{s}": (9, ()), f"strutfairing_{s}": (17, ()),
                  f"vtail_{s}": (17, (f"ruddervator_{s}_visible",)), f"gear_{s}M": (17, (f"wheel_{s}M",))})
    for n in range(1, 5):
        t.update({f"nacelle_{n}": (17, (f"nozzle_{n}",)), f"pylon_{n}": (12, ())})
    return t


LOD1_PARTS = lod1_table()


def build_lod1(parts, objs, world, coll, mat):
    """One flat-shaded <part>_lod1 per detachable part, coloured by a 0.14 grey vertex attribute for the stock LOD
    material (liveries never reach LOD1)."""
    lofts = {p["name"]: p["lod"] for p in parts if p["lod"]}
    report = {}
    for name, (budget, extras) in LOD1_PARTS.items():
        if budget is None:
            bm = bmesh.new()
            loft(bm, lofts[name])
            bmesh.ops.triangulate(bm, faces=bm.faces[:])
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.verts.index_update()
            verts = np.array([v.co[:] for v in bm.verts])
            tris = np.array([[v.index for v in f.verts] for f in bm.faces])
            bm.free()
        else:
            pts = np.array([c[:] for n in (name,) + extras for c in world_mesh(objs[n])[0]])
            verts, tris = convex.hull_mesh(convex.simplify_hull(pts, budget))
        obj = hull_object(name + "_lod1", verts, tris, world[name].inverted(), objs[name], coll)
        me = obj.data
        me.materials.append(mat)
        col = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        col.data.foreach_set("color", [LOD1_GREY, LOD1_GREY, LOD1_GREY, 1.0] * len(me.vertices))
        me.color_attributes.active_color = col
        me.color_attributes.render_color_index = me.color_attributes.active_color_index
        report[obj.name] = {"tris": len(me.polygons), "verts": len(me.vertices)}
    return report


# ---------- skin atlas UVs ----------
UV_MARGIN_PX = 4
TRIM_UV_PER_M = 0.5  # box projection for faces on the tiling trims
MIRRORED = ("wing_", "flap_", "aileron_", "spoiler_", "strut", "jury_strut_", "sponson_", "vtail_", "ruddervator_")
UV_GROUPS = (("fuselage", ("radar_", "nose", "fuselage_", "tailcone", "tail_end", "cheek_", "wingfairing", "baydoor_",
                           "geardoor_F", "laser_", "spine_")),
             ("wing", ("wing_", "flap_", "aileron_", "spoiler_")),
             ("struts", ("strut", "jury_strut_", "sponson_", "geardoor_LM", "geardoor_RM")),
             ("nacelles", ("nacelle_", "pylon_", "nozzle_", "fan_")),
             ("vtail", ("vtail_", "ruddervator_")))
UV_GROUP_COLOURS = {"fuselage": (0.35, 0.55, 0.85), "wing": (0.40, 0.75, 0.40), "struts": (0.90, 0.60, 0.25),
                    "nacelles": (0.85, 0.35, 0.35), "vtail": (0.65, 0.45, 0.85)}


def uv_group(name):
    return next((g for g, prefixes in UV_GROUPS if name.startswith(prefixes)), None)


def mirror_source(name):
    """The twin whose UV islands a mirrored part reuses, or None for a part with its own islands. SPEC: wing, strut,
    nacelle and V-tail islands are mirrored (overlapping UVs); the fuselage stays unique so markings read the right
    way on both sides. The four nacelles and nozzles are one mesh, so all four share engine 1's islands; pylons
    differ per engine and only mirror (3 and 4 reuse 2 and 1)."""
    if name.startswith(("nacelle_", "nozzle_")):
        kind, num = name.split("_")
        return f"{kind}_1" if num != "1" else None
    if name.startswith("pylon_"):
        twin = PYLON_TWINS.get(int(name.split("_")[1]))
        return f"pylon_{twin}" if twin else None
    if name.startswith(MIRRORED) and "_R" in name:
        return name.replace("_R", "_L", 1)
    return None


# Revolved parts whose -x half reuses the +x half's islands (SPEC: mirrored nacelle islands), by revolve segment
# count: face r * seg + i lies on the +x side for i < seg / 2, and vertex r * seg + j mirrors r * seg + (seg - j) % seg.
HALF_MIRRORED = {"nacelle_1": 32, "nozzle_1": 2 * CHEVRONS}
PYLON_TWINS = {3: 2, 4: 1}  # pylon: the pylon whose islands it mirrors


def half_faces(obj, faces):
    seg = HALF_MIRRORED.get(obj.name)
    return faces if seg is None else [i for i in faces if i % seg < seg // 2]


def mirror_halves(obj):
    """Copy the +x half's UVs onto the -x half of a HALF_MIRRORED part; returns loops or faces that failed to match."""
    seg, me = HALF_MIRRORED[obj.name], obj.data
    uv = me.uv_layers["UVMap"].data
    skin, bad = set(slot_faces(obj, SKIN)), 0
    for i in skin:
        r, c = divmod(i, seg)
        if c < seg // 2:
            continue
        src = r * seg + seg - 1 - c
        if src not in skin:
            bad += 1
            continue
        by_vert = {me.loops[li].vertex_index: uv[li].uv.copy() for li in me.polygons[src].loop_indices}
        for li in me.polygons[i].loop_indices:
            vr, vc = divmod(me.loops[li].vertex_index, seg)
            mirrored = by_vert.get(vr * seg + (seg - vc) % seg)
            if mirrored is None:
                bad += 1
            else:
                uv[li].uv = mirrored
    return bad


def box_project(obj):
    me = obj.data
    uv = (me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")).data
    for p in me.polygons:
        axis = max(range(3), key=lambda i: abs(p.normal[i]))
        a, b = (i for i in range(3) if i != axis)
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv[li].uv = (co[a] * TRIM_UV_PER_M, co[b] * TRIM_UV_PER_M)


def select_faces(obj, faces):
    me = obj.data
    picked = set(faces)
    me.polygons.foreach_set("select", [p.index in picked for p in me.polygons])
    verts = {v for i in picked for v in me.polygons[i].vertices}
    me.vertices.foreach_set("select", [v.index in verts for v in me.vertices])
    me.edges.foreach_set("select", [e.vertices[0] in verts and e.vertices[1] in verts for e in me.edges])


def skin_areas(obj, faces=None):
    """World and UV area of an object's skin faces (or of the given faces)."""
    me = obj.data
    uv = me.uv_layers["UVMap"].data
    world_a = uv_a = 0.0
    for i in slot_faces(obj, SKIN) if faces is None else faces:
        p = me.polygons[i]
        world_a += p.area
        pts = [uv[li].uv for li in p.loop_indices]
        uv_a += abs(sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1]))) / 2
    return world_a, uv_a


def density(world_a, uv_a):
    return ATLAS * math.sqrt(uv_a / world_a) if world_a else 0.0


def copy_uvs(src, dst):
    """Give dst (a mirrored twin, same topology) src's UVs loop for loop, matched by vertex index since mirroring
    reverses face winding. Returns the number of loops or skin faces that failed to match."""
    s, d = src.data, dst.data
    if len(s.polygons) != len(d.polygons):
        return len(d.loops)
    suv, duv = s.uv_layers["UVMap"].data, d.uv_layers["UVMap"].data
    skin = slot_faces(dst, SKIN)
    bad = len(set(slot_faces(src, SKIN)) ^ set(skin))
    for i in skin:
        ps, pd = s.polygons[i], d.polygons[i]
        by_vert = {s.loops[li].vertex_index: suv[li].uv.copy() for li in ps.loop_indices}
        for li in pd.loop_indices:
            uv = by_vert.get(d.loops[li].vertex_index)
            if uv is None:
                bad += 1
            else:
                duv[li].uv = uv
    return bad


def unwrap_skin(objs):
    """Unwrap every unique part's skin faces along the seams marked at build time, equalise island scale, pack into
    the atlas, scale down to TEXEL_TARGET if the pack came out denser, then copy islands onto mirrored twins."""
    meshes = [o for o in objs.values() if o.type == "MESH"]
    for o in meshes:
        box_project(o)
    unique = [o for o in meshes if mirror_source(o.name) is None and slot_faces(o, SKIN)]
    for o in meshes:
        o.select_set(False)
    for o in unique:
        select_faces(o, half_faces(o, slot_faces(o, SKIN)))
        o.select_set(True)
    bpy.context.view_layer.objects.active = unique[0]
    tools = scene.tool_settings
    tools.mesh_select_mode = (False, False, True)
    tools.use_uv_select_sync = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.0)
    bpy.ops.uv.average_islands_scale()

    def pack(shape):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.uv.pack_islands(rotate=True, shape_method=shape, margin_method="FRACTION", margin=UV_MARGIN_PX / ATLAS)
        bpy.ops.object.mode_set(mode="OBJECT")
        return density(*map(sum, zip(*(skin_areas(o, half_faces(o, slot_faces(o, SKIN))) for o in unique))))

    tried = {shape: pack(shape) for shape in ("AABB", "CONVEX", "CONCAVE")}
    best = max(tried, key=tried.get)
    packed = pack(best)
    k = min(1.0, TEXEL_TARGET / packed)
    for o in unique:
        uv = o.data.uv_layers["UVMap"].data
        for i in slot_faces(o, SKIN):
            for li in o.data.polygons[i].loop_indices:
                uv[li].uv *= k
    mismatched = {name: mirror_halves(objs[name]) for name in HALF_MIRRORED}
    mismatched.update({o.name: copy_uvs(objs[mirror_source(o.name)], o) for o in meshes
                       if mirror_source(o.name) and slot_faces(o, SKIN)})
    coverage, overlap, image = uv_raster(unique)
    return {"packed_px_per_m": round(packed, 2), "pack_tries": {s: round(d, 2) for s, d in tried.items()},
            "scaled_by": round(k, 4), "unique_parts": len(unique),
            "mirrored_parts": len(mismatched), "mirror_mismatches": {n: c for n, c in mismatched.items() if c},
            "coverage": round(coverage, 4), "overlap_fraction": round(overlap, 5), "image": image}


def uv_raster(objs, size=ATLAS):
    """Rasterise the unique skin islands at atlas resolution: coverage, the fraction of texels claimed twice (shared
    edges count too, so a few hundredths of a percent is the floor), and a layout image coloured by part group."""
    count = np.zeros((size, size), np.uint8)
    rgb = np.full((size, size, 3), 0.08, np.float32)
    edges = []
    for o in objs:
        colour = np.array(UV_GROUP_COLOURS[uv_group(o.name)], np.float32)
        me = o.data
        uv = np.empty(len(me.loops) * 2)
        me.uv_layers["UVMap"].data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2) * size
        skin = set(half_faces(o, slot_faces(o, SKIN)))
        me.calc_loop_triangles()
        for lt in me.loop_triangles:
            if lt.polygon_index not in skin:
                continue
            a, b, c = uv[list(lt.loops)]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-9:
                continue
            lo = np.clip(np.floor(np.minimum(np.minimum(a, b), c)).astype(int), 0, size - 1)
            hi = np.clip(np.ceil(np.maximum(np.maximum(a, b), c)).astype(int), 0, size - 1)
            x, y = np.meshgrid(np.arange(lo[0], hi[0] + 1) + 0.5, np.arange(lo[1], hi[1] + 1) + 0.5)
            w = [(q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]) for p, q in ((b, c), (c, a), (a, b))]
            hit = ((w[0] >= 0) & (w[1] >= 0) & (w[2] >= 0)) | ((w[0] <= 0) & (w[1] <= 0) & (w[2] <= 0))
            count[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1][hit] += 1
            rgb[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1][hit] = colour
        for i in skin:
            loops = list(me.polygons[i].loop_indices)
            edges += [(uv[a], uv[b]) for a, b in zip(loops, loops[1:] + loops[:1])]
    p0, p1 = (np.array(e) for e in zip(*edges))
    steps = np.ceil(np.linalg.norm(p1 - p0, axis=1) * 2).astype(int) + 1
    t = np.concatenate([np.linspace(0, 1, n) for n in steps])
    idx = np.repeat(np.arange(len(p0)), steps)
    pts = np.clip((p0[idx] + (p1 - p0)[idx] * t[:, None]).astype(int), 0, size - 1)
    rgb[pts[:, 1], pts[:, 0]] *= 0.45
    return float((count > 0).mean()), float((count > 1).mean()), rgb


# ---------- smoothing ----------
SHARP_ANGLE = math.radians(50.0)


def bake_normals(objs):
    """Hard edges where faces meet at more than SHARP_ANGLE or change material, except the soft-flagged airfoil
    leading edges; then a Weighted Normal modifier (face area, keep sharp) is applied, so the low-poly hull reads
    crisp and the export carries custom split normals. Returns hard edges per part."""
    hard_edges = {}
    for o in objs.values():
        if o.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        soft = bm.edges.layers.int.get("soft")
        n = 0
        for e in bm.edges:
            f = e.link_faces
            hard = len(f) == 2 and (f[0].material_index != f[1].material_index or
                                    (e.calc_face_angle(0.0) > SHARP_ANGLE and not (soft and e[soft])))
            e.smooth = not hard
            n += hard
        for f in bm.faces:
            f.smooth = True
        bm.to_mesh(o.data)
        bm.free()
        if "soft" in o.data.attributes:
            o.data.attributes.remove(o.data.attributes["soft"])
        mod = o.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        mod.mode, mod.keep_sharp = "FACE_AREA", True
        with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
            bpy.ops.object.modifier_apply(modifier=mod.name)
        hard_edges[o.name] = n
    return hard_edges


# ---------- metrics ----------
def world_mesh(obj):
    """World vertices and polygons of a mesh object, or of a list of them merged (fixed_wing)."""
    if isinstance(obj, (list, tuple)):
        verts, polys = [], []
        for o in obj:
            v, p = world_mesh(o)
            polys += [tuple(len(verts) + i for i in poly) for poly in p]
            verts += v
        return verts, polys
    mw = obj.matrix_world
    return [mw @ v.co for v in obj.data.vertices], [tuple(p.vertices) for p in obj.data.polygons]


def fixed_wing(objs, s):
    """The fixed wing of side s ("_L"/"_R") whole: wing_root and, with the finer part tree, its outer piece
    (part_splits), for the checks that measure the stages against the fixed wing."""
    return [objs[n + s] for n in ("wing_root", "wing_outer") if n + s in objs]


def shell_stats(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    nonmanifold = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    verts, polys = world_mesh(obj)
    vol = 0.0
    for poly in polys:
        for i in range(1, len(poly) - 1):
            vol += verts[poly[0]].dot(verts[poly[i]].cross(verts[poly[i + 1]])) / 6
    return nonmanifold, vol


def outside_count(child, parent):
    """Vertices of child outside parent; on the last stage, only the stage's own, inboard of its tip's root."""
    verts, polys = world_mesh(parent)
    bvh = BVHTree.FromPolygons(verts, polys)
    x_max = abs((child.matrix_world @ Vector(child["tip_qc"])).x) + 1e-3 if "tip_qc" in child else math.inf
    out = 0
    for p in (v for v in world_mesh(child)[0] if abs(v.x) <= x_max):
        loc, normal, _, _ = bvh.find_nearest(p)
        if (p - loc).dot(normal) > 1e-4:
            out += 1
    return out


def clash_faces(a, b):
    trees = [BVHTree.FromPolygons(*world_mesh(o)) for o in (a, b)]
    return len(trees[0].overlap(trees[1]))


def min_distance(a, b):
    tree = BVHTree.FromPolygons(*world_mesh(b))
    return min(tree.find_nearest(p)[3] for p in world_mesh(a)[0])


def engine_clashes(objs):
    """Surface intersections between each engine and the struts, wing and fuselage it must clear (pylons excluded)."""
    found = {}
    for num, side, _, _ in NACELLES:
        sfx = "_L" if side > 0 else "_R"
        for eng in (f"nacelle_{num}", f"nozzle_{num}"):
            for other in tuple(n + sfx for n in ENGINE_CLEAR_OF) + ("fuselage_F", "fuselage_M"):
                if other in bonds(objs[eng]) or eng in bonds(objs[other]):
                    continue  # mounted through it by design (step 6: the strut through the nacelle)
                n = clash_faces(objs[eng], objs[other])
                if n:
                    found[f"{eng}~{other}"] = n
    return found


NACELLE_UNDER_BAND = (0.40, 0.50)  # share of the cowl length behind the wing leading edge
ENGINE_CLEAR_OF = ("strut", "jury_strut", "wing_root", "strutfairing")  # per side; the first is the strut beside the nozzle
WING_CHAIN = ("wing_root", "wing_outer", "wing_tele1", "wing_tele2", "wing_tip")
WING_STAGES = ("wing_tele1", "wing_tele2", "wing_tip")  # the chain's sliding members


def joint_parent(obj):
    p = obj.parent
    while p is not None and p.type == "EMPTY":
        p = p.parent
    return p


def bonds(obj):
    return {b for b in obj.get("bonded_to", "").split(",") if b}


def wing_chain(obj):
    """The side ("_L" or "_R") of the telescoping chain obj belongs to, or None."""
    return obj.name[-2:] if obj.name[:-2] in WING_CHAIN else None


def jointed(a, b):
    """Parts allowed to interpenetrate: parent and child, the telescoping chain of one wing (the stages pass through
    each other's end caps by design; stages_nested_retracted checks them), or a declared bond (one part mounted on
    another along a joint, e.g. a strut end in its fairing)."""
    if joint_parent(a) == b or joint_parent(b) == a:
        return True
    if wing_chain(a) and wing_chain(a) == wing_chain(b):
        return True
    return b.name in bonds(a) or a.name in bonds(b)


def inside_root(a, b, objs):
    """A stage and a part its wing root runs into (the root's parent or a declared bond): the stages nest in the root
    (stages_nested_retracted, the slide clearance) and leave it only past its tip, so they meet such a part only
    inside the root, as step 6.1's long stages pass through the body and the wing fairing. Render meshes only;
    colliders keep jointed's rule."""
    for s, o in ((a, b), (b, a)):
        side = wing_chain(s)
        root = objs.get("wing_root" + side) if side and s.name[:-2] in WING_STAGES else None
        if root is not None and (joint_parent(root) == o or o.name in bonds(root) or root.name in bonds(o)):
            return True
    return False


def bounds(verts):
    return (Vector((min(c.x for c in verts), min(c.y for c in verts), min(c.z for c in verts))),
            Vector((max(c.x for c in verts), max(c.y for c in verts), max(c.z for c in verts))))


def box_gap(a, b):
    """Largest per-axis separation between two (lo, hi) boxes; negative when they overlap on every axis."""
    return max(max(b[0][k] - a[1][k], a[0][k] - b[1][k]) for k in range(3))


def boxes_touch(a, b, margin):
    return box_gap(a, b) <= margin


def inside(p, tree, d=Vector((0.0123, 0.0071, 1.0))):
    hits, origin, d = 0, p.copy(), d.normalized()
    while hits < 400:
        loc = tree.ray_cast(origin, d)[0]
        if loc is None:
            break
        hits, origin = hits + 1, loc + d * 1e-5
    return hits % 2 == 1


# A thin-walled panel (m4/partition.py) is open where a torn lip turns in, and one ray can pass that opening: two of
# three rays in different directions must read inside
BURIED_RAYS = (Vector((0.0123, 0.0071, 1.0)), Vector((0.71, 0.0093, -0.7)), Vector((-0.0061, 1.0, 0.0137)))


def buried(p, tree):
    return sum(inside(p, tree, d) for d in BURIED_RAYS) >= 2


def overlaps(objs):
    meshes = sorted((o for o in objs.values() if o.type == "MESH"), key=lambda o: o.name)
    data = {}
    for o in meshes:
        v, p = world_mesh(o)
        lo = Vector((min(c.x for c in v), min(c.y for c in v), min(c.z for c in v)))
        hi = Vector((max(c.x for c in v), max(c.y for c in v), max(c.z for c in v)))
        data[o.name] = (v, BVHTree.FromPolygons(v, p), lo, hi)
    found = {}
    for i, a in enumerate(meshes):
        for b in meshes[i + 1:]:
            A, B = data[a.name], data[b.name]
            if any(A[2][k] > B[3][k] or B[2][k] > A[3][k] for k in range(3)) or jointed(a, b) or inside_root(a, b, objs):
                continue
            n = len(A[1].overlap(B[1]))
            if n:
                found[f"{a.name}~{b.name}"] = f"{n} intersecting face pairs"
            elif buried(A[0][0], B[1]) or buried(B[0][0], A[1]):
                found[f"{a.name}~{b.name}"] = "one inside the other"
    return found


def world_hull(obj):
    mw = obj.matrix_world
    verts = np.array([(mw @ v.co)[:] for v in obj.data.vertices])
    return verts, np.array([tuple(p.vertices) for p in obj.data.polygons])


def collider_gaps(names, near=1.5):
    """Gaps between colliders of parts that are not jointed (step 2's rules, by owning part), for pairs whose boxes
    come within near metres. Returns (gap, a, b) sorted, 0.0 meaning touching or overlapping."""
    hulls = {}
    for n in names:
        obj = bpy.data.objects[n]
        v, t = world_hull(obj)
        hulls[n] = (v, t, (Vector(v.min(0)), Vector(v.max(0))), obj.parent)
    found = []
    ordered = sorted(names)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            A, B = hulls[a], hulls[b]
            if A[3] is B[3] or jointed(A[3], B[3]) or box_gap(A[2], B[2]) > near:
                continue
            found.append((round(convex.hull_gap(A[:2], B[:2]), 4), a, b))
    return sorted(found)


def convexity_error(obj):
    """Relative volume a collider misses against the convex hull of its own vertices (0 when convex). PhysX cooks
    that hull from the vertices anyway; this proves the triangles already are it."""
    v, t = world_hull(obj)
    return float(1 - mesh_volume(v, t) / mesh_volume(*convex.hull_mesh(v)))


def mesh_volume(v, t):
    return abs((v[t[:, 0]] * np.cross(v[t[:, 1]], v[t[:, 2]])).sum()) / 6


def export_checks(objs, report):
    """Checks on what the exporter reads: colliders (at extension 0, 0.5 and 1), LOD1, material slots, UVs and
    normals. Leaves the stages at extension 0."""
    checks, cols, lods = {}, report["colliders"], report["lod1"]
    owners = {c["owner"] for c in cols.values()}
    missing = sorted(set(LOAD_PARTS) - owners)
    checks["colliders_cover_load_parts"] = {"load_parts": len(LOAD_PARTS), "collider_pieces": len(cols),
                                            "missing": missing, "pass": not missing}
    most = max(cols.values(), key=lambda c: c["verts"])
    checks["colliders_le_255_verts"] = {"max_verts": most["verts"], "max_tris": max(c["tris"] for c in cols.values()),
                                        "limit": "<= 255 vertices (SPEC); built to <= 128 so tris stay < 255",
                                        "pass": most["verts"] <= COL_MAX_VERTS}
    shallow = {n: c["min_depth_m"] for n, c in cols.items() if c["min_depth_m"] < COL_MIN_DEPTH - 1e-4}
    checks["colliders_inset_2_to_3cm"] = {
        "vertex_depth_m": [min(c["vertex_depth_m"][0] for c in cols.values()), max(c["vertex_depth_m"][1] for c in cols.values())],
        "min_surface_depth_m": min(c["min_depth_m"] for c in cols.values()),
        "note": f"faces planes moved {COL_INSET} m in; depth sampled at vertices, face centres and edge midpoints",
        "too_shallow": shallow, "pass": not shallow}
    errors = {n: convexity_error(bpy.data.objects[n]) for n in cols}
    bent = {n: round(e, 6) for n, e in errors.items() if abs(e) > 1e-4}
    checks["colliders_convex"] = {"max_volume_missing_vs_own_hull": round(max(errors.values()), 7), "limit": "1e-4",
                                  "not_convex": bent, "pass": not bent}
    # A stage's inertia in game comes from its collider: step 6's first stage 1 hull collapsed to 0.24 of about 7 m3,
    # too little to hold stage 2's slider (STAGE_COL_ENDS).
    kept = {}
    for n, c in cols.items():
        o = bpy.data.objects[c["owner"]]
        if "col_ref_m3" in o:
            kept[o.name] = kept.get(o.name, 0.0) + mesh_volume(*world_hull(bpy.data.objects[n])) / o["col_ref_m3"]
    if kept:
        checks["stage_colliders_full"] = {"volume_over_lofted_section": {n: round(r, 3) for n, r in kept.items()},
                                          "limit": ">= 0.7", "pass": all(r >= 0.7 for r in kept.values())}
    by_ext, overall = {}, None
    for e in EXTENSIONS_CHECKED:
        set_extension(objs, e)
        gaps = collider_gaps(cols)
        by_ext[extension_key(e)] = {"min_gap_m": gaps[0][0], "closest": [f"{a}~{b} {g:.3f}" for g, a, b in gaps[:6]]}
        if overall is None or gaps[0][0] < overall[0]:
            overall = (gaps[0][0], f"{gaps[0][1]}~{gaps[0][2]}", e)
    set_extension(objs, 0.0)
    checks["colliders_clear_unjointed"] = {"min_gap_m": overall[0], "pair": overall[1], "at_extension": overall[2],
                                           "by_extension": by_ext, "pass": overall[0] > 0.001}

    tris = {n: c["tris"] for n, c in lods.items()}
    total = sum(tris.values())
    lod_objs = [bpy.data.objects[n] for n in lods]
    checks["lod1_10_to_30_tris"] = {"out_of_range": {n: t for n, t in tris.items() if not 10 <= t <= 30},
                                    "parts": len(tris), "pass": all(10 <= t <= 30 for t in tris.values())}
    checks["lod1_total_about_1000"] = {"value": total, "limit": f"<= 1000 (SPEC), at least {LOD1_TOTAL_MIN}",
                                       "pass": LOD1_TOTAL_MIN <= total <= 1000}
    checks["lod1_flat_grey"] = {"pass": all(not any(p.use_smooth for p in o.data.polygons) and "Col" in o.data.color_attributes
                                            and o.data.materials[0].name == LOD for o in lod_objs)}

    meshes = [o for o in objs.values() if o.type == "MESH"]
    bad_slots = {o.name: [m.name for m in o.data.materials] for o in meshes
                 if len(o.data.materials) > 3 or any(m.name not in SLOT_ORDER for m in o.data.materials)}
    faces = {m: sum(len(slot_faces(o, m)) for o in meshes) for m in SLOT_ORDER}
    checks["material_slots"] = {"faces_per_material": faces, "buried_skin_faces_to_structure": sum(report["buried_skin_faces"].values()),
                                "bad": bad_slots, "limit": "<= 3 slots per renderer, names from SLOT_ORDER", "pass": not bad_slots}

    groups, per_part = {}, {}
    for o in meshes:
        g = uv_group(o.name)
        if g is None or not slot_faces(o, SKIN):
            continue
        wa, ua = skin_areas(o)
        groups.setdefault(g, [0.0, 0.0, 0.0])
        groups[g][0] += wa
        groups[g][1] += ua
        if mirror_source(o.name) is None:
            groups[g][2] += skin_areas(o, half_faces(o, slot_faces(o, SKIN)))[1]
        if wa > 1.0:
            per_part[o.name] = density(wa, ua)
    table = {g: {"skin_m2": round(wa, 1), "px_per_m": round(density(wa, ua), 1), "unique_uv_fraction": round(ua_u, 4)}
             for g, (wa, ua, ua_u) in groups.items()}
    spread = (min(per_part.values()), max(per_part.values()))
    uv = report["uv"]
    checks["uv_texel_density"] = {"groups": table, "part_range_px_per_m": [round(s, 1) for s in spread],
                                  "target": TEXEL_TARGET, "limit": "every part with > 1 m2 of skin within 10% of 57",
                                  "pass": all(abs(d / TEXEL_TARGET - 1) <= 0.10 for d in per_part.values())}
    checks["uv_packing"] = {"coverage": uv["coverage"], "overlap_fraction": uv["overlap_fraction"],
                            "packed_px_per_m_before_scaling": uv["packed_px_per_m"], "pack_tries": uv["pack_tries"], "scaled_by": uv["scaled_by"],
                            "unique_parts": uv["unique_parts"], "mirrored_parts": uv["mirrored_parts"],
                            "pass": uv["overlap_fraction"] < 0.002}
    checks["uv_mirrors_match"] = {"mismatches": uv["mirror_mismatches"], "pass": not uv["mirror_mismatches"]}
    flat = [o.name for o in meshes if not o.data.has_custom_normals]
    checks["custom_normals"] = {"hard_edges": sum(report["hard_edges"].values()), "missing": flat, "pass": not flat}
    return checks


BUDGET = (("fuselage", 25000, ("nose", "fuselage_", "tailcone", "tail_end", "cheek_", "wingfairing")),
          ("wing_and_struts", 20000, ("wing_", "strut", "jury_strut", "sponson_")),
          ("surfaces", 4000, ("flap_", "aileron_", "spoiler_")), ("vtail", 5000, ("vtail", "ruddervator")),
          ("nacelles", 36000, ("nacelle_", "pylon_", "fan_", "nozzle_")), ("gear", 16000, ("gear_", "wheel_", "geardoor_")),
          ("bays", 8000, ("baydoor_", "spine_")), ("systems", 6000, ("radar_", "laser_")))


def budget_group(name):
    return next(g for g, _, prefixes in BUDGET if name.startswith(prefixes))


def tip_step(objs, side):
    """Retracted: the tip cuff against the fixed wing's end section (chord and thickness), and the gap between."""
    sfx = "_L" if side > 0 else "_R"
    root = world_mesh(fixed_wing(objs, sfx))[0]
    x_end = max(abs(v.x) for v in root)
    end = [v for v in root if abs(abs(v.x) - x_end) < 1e-3]
    tip = world_mesh(objs["wing_tele2" + sfx])[0]
    x_cuff = abs(qc_at(side, XI_ROOT_TIP - TELE[1][3] + TIP_NECK).x)
    cuff = [v for v in tip if abs(abs(v.x) - x_cuff) < 1e-3]
    ext = lambda vs, d: max(v.dot(d) for v in vs) - min(v.dot(d) for v in vs)
    d_chord, d_thick = ext(cuff, CDIR) - ext(end, CDIR), ext(cuff, TDIR) - ext(end, TDIR)
    gap = x_cuff - x_end
    return {"root_end_chord": round(ext(end, CDIR), 3), "cuff_chord": round(ext(cuff, CDIR), 3),
            "chord_step": round(d_chord, 3), "thickness_step": round(d_thick, 3), "gap_m": round(gap, 3),
            "pass": abs(d_chord) < 0.03 and abs(d_thick) < 0.02 and 0 < gap < 0.05}


def main_contact(objs):
    """The main wheels' runway contact in the airframe's frame with the struts sagged: in game each main leg casts
    from its bogie centre (CenturionAuthor puts the bump stop over the wheel_LM pivot)."""
    return Vector((0, objs["wheel_LM"].matrix_world.translation.y, MAIN_STRUT_SAG))


def tail_strike(objs):
    """Body pitch at which the runway first touches anything behind the main wheels (gear excluded), pivoting on
    the main contact with the struts sagged at maximum takeoff mass. The takeoff AI aims about 9.5 deg nose up
    (SPEC "Landing gear") and the landing rollout about 10 (CenturionAuthor's landingSpeed note)."""
    c = main_contact(objs)
    worst = None
    for name, o in objs.items():
        if o.type != "MESH" or name.startswith(("gear_", "wheel_")):
            continue
        for v in world_mesh(o)[0]:
            if v.y > c.y + 0.5:
                deg = math.degrees(math.atan2(v.z - c.z, v.y - c.y))
                if worst is None or deg < worst[0]:
                    worst = (deg, name, v)
    deg, name, v = worst
    if TAIL_STRIKE_BAND is None:
        limit, ok = f">= {TAIL_STRIKE_MIN_DEG} deg", deg >= TAIL_STRIKE_MIN_DEG
    else:
        limit, ok = f"{TAIL_STRIKE_BAND[0]} to {TAIL_STRIKE_BAND[1]} deg", TAIL_STRIKE_BAND[0] <= deg <= TAIL_STRIKE_BAND[1]
    return {"value": round(deg, 2), "limit": limit, "pass": ok,
            "first_contact": {"part": name, "station": round(v.y + Y0, 3), "height_m": round(v.z, 3)},
            "main_contact": {"station": round(c.y + Y0, 3), "strut_sag_m": round(MAIN_STRUT_SAG, 3)}}


def measure(objs, extension, label, report):
    meshes = {n: o for n, o in objs.items() if o.type == "MESH"}
    allv = [v for o in meshes.values() for v in world_mesh(o)[0]]
    lo = Vector((min(v.x for v in allv), min(v.y for v in allv), min(v.z for v in allv)))
    hi = Vector((max(v.x for v in allv), max(v.y for v in allv), max(v.z for v in allv)))
    length, span, height = hi.y - lo.y, hi.x - lo.x, hi.z
    parts, bad_shells, inward = {}, [], []
    groups = {g: 0 for g, _, _ in BUDGET}
    for name, o in sorted(meshes.items()):
        verts = world_mesh(o)[0]
        dims = [round(max(getattr(v, a) for v in verts) - min(getattr(v, a) for v in verts), 3) for a in "xyz"]
        tris = sum(len(p.vertices) - 2 for p in o.data.polygons)
        nonmanifold, vol = shell_stats(o)
        if nonmanifold:
            bad_shells.append(name)
        if vol <= 0:
            inward.append(name)
        group = budget_group(name)
        groups[group] += tris
        parts[name] = {"dims_xyz_m": dims, "tris": tris, "budget_group": group,
                       "origin_world": [round(c, 3) for c in o.matrix_world.translation],
                       "material_slots": [m.name for m in o.data.materials], "uv_mirror_of": mirror_source(name),
                       "skin_px_per_m": round(density(*skin_areas(o)), 1)}
    for name, o in sorted(objs.items()):
        if o.type == "EMPTY":
            parts[name] = {"hinge_empty_for": name + "_visible", "hinge_axis": [round(c, 4) for c in o["hinge_axis"]],
                           "origin_world": [round(c, 3) for c in o.matrix_world.translation]}

    def check(value, ok, limit):
        return {"value": value, "limit": limit, "pass": bool(ok)}

    checks = {
        f"length_le_{LENGTH_LIMIT}": check(round(length, 3), length <= LENGTH_LIMIT + 1e-6, f"<= {LENGTH_LIMIT} m"),
        f"height_lt_{HEIGHT_LIMIT}": check(round(height, 3), height < HEIGHT_LIMIT, f"< {HEIGHT_LIMIT} m (gear down)"),
    }
    if TAIL_TOP_LIMIT is not None:
        top = max(v.z for n, o in meshes.items() if n.startswith(("vtail", "ruddervator")) for v in world_mesh(o)[0])
        checks[f"tail_tops_lt_{TAIL_TOP_LIMIT}"] = check(round(top, 3), top < TAIL_TOP_LIMIT, f"< {TAIL_TOP_LIMIT} m")
        checks["hangar_depth_centred"] = check({"nose_m": round(-HANGAR_DEPTH / 2 - lo.y, 3), "tail_m": round(HANGAR_DEPTH / 2 - hi.y, 3)},
                                               lo.y > -HANGAR_DEPTH / 2 and hi.y < HANGAR_DEPTH / 2,
                                               f"inside the {HANGAR_DEPTH} m hangar with the spawn at its centre (Y = 0)")
    if extension == 0:
        checks["retracted_span_lt_43.8"] = check(round(span, 3), span < 43.8, "< 43.8 m")
        checks["hangar_door_fit"] = check(f"{span:.2f} x {height:.2f}", span < HANGAR_DOOR_W and height < HANGAR_DOOR_H,
                                          f"{HANGAR_DOOR_W} x {HANGAR_DOOR_H} m door")
        checks["hangar_depth_fit"] = check(round(length, 3), length < HANGAR_DEPTH, f"< {HANGAR_DEPTH} m deep")
        nested = {f"{c}{s}_outside_{p}{s}": outside_count(objs[c + s], fixed_wing(objs, s) if p == "wing_root" else objs[p + s])
                  for s in ("_L", "_R") for c, p in (("wing_tele1", "wing_root"), ("wing_tele2", "wing_tele1"))}
        checks["stages_nested_retracted"] = {"outside_vertices": nested, "pass": not any(nested.values())}
        for side, s in ((1, "_L"), (-1, "_R")):
            checks[f"retracted_tip_step{s}"] = tip_step(objs, side)
    elif extension == 1:
        checks[f"span_extended_{SPAN_EXTENDED}"] = check(round(span, 3), abs(span - SPAN_EXTENDED) <= 0.25,
                                                         f"{SPAN_EXTENDED} +- 0.25 m (SPEC)")
    for s in ("_L", "_R"):
        tele = objs["wing_tele2" + s]
        root_y, tip_y = objs["wing_root" + s].matrix_world.translation.y, (tele.matrix_world @ Vector(tele["tip_qc"])).y
        if SWEEP < 0:
            checks[f"wingtip{s}_forward_of_root"] = {"root_qc_y": round(root_y, 3), "tip_y": round(tip_y, 3),
                                                     "ahead_by_m": round(root_y - tip_y, 3), "pass": tip_y < root_y}
        else:  # step 6: swept back
            checks[f"wingtip{s}_aft_of_root"] = {"root_qc_y": round(root_y, 3), "tip_y": round(tip_y, 3),
                                                 "behind_by_m": round(tip_y - root_y, 3), "pass": tip_y > root_y}
    checks[TAIL_STRIKE_KEY] = tail_strike(objs)
    clashes = engine_clashes(objs)
    checks["engines_clear_struts_wing_fuselage"] = {"intersecting_face_pairs": clashes, "pass": not clashes}
    under = {}
    for num, side, x, front in NACELLES:
        le_station = wing_le(side, x)[0].y + Y0
        under[f"nacelle_{num}"] = round((front + NACELLE_LEN - le_station) / NACELLE_LEN, 3)
    lo_f, hi_f = NACELLE_UNDER_BAND
    checks["nacelle_length_under_chord"] = {"fraction": under, "limit": f"{lo_f:.2f} to {hi_f:.2f} of the cowl behind the leading edge",
                                            "pass": all(lo_f <= f <= hi_f for f in under.values())}
    gaps = {f"nacelle_{n}~wing_root": round(min_distance(objs[f"nacelle_{n}"], objs["wing_root" + ("_L" if sd > 0 else "_R")]), 3)
            for n, sd, _, _ in NACELLES}
    strut = ENGINE_CLEAR_OF[0]
    gaps.update({f"nozzle_{n}~{strut}": round(min_distance(objs[f"nozzle_{n}"], objs[strut + ("_L" if sd > 0 else "_R")]), 3)
                 for n, sd, _, _ in NACELLES})
    checks["clearance_min_m"] = {"value": gaps, "note": "informational: nearest vertex-to-surface distance"}
    by_ext = {}
    for e in EXTENSIONS_CHECKED:
        set_extension(objs, e)
        by_ext[extension_key(e)] = overlaps(objs)
    set_extension(objs, extension)
    checks["no_overlap_unjointed_parts"] = {
        "by_extension": by_ext, "pass": not any(by_ext.values()),
        "jointed_means": "parent and child (through hinge empties), one wing's telescoping chain, or a declared bond; "
                         "a stage also with what its root runs into (inside_root)",
        "declared_bonds": sorted(f"{o.name}~{b}" for o in objs.values() for b in bonds(o))}
    checks["closed_shells"] = {"nonmanifold_parts": bad_shells, "pass": not bad_shells}
    checks["normals_outward"] = {"inward_parts": inward, "pass": not inward}
    budget = {g: {"tris": groups[g], "budget": b, "pass": groups[g] <= b} for g, b, _ in BUDGET}
    checks["triangle_budget"] = {"groups": budget, "total": sum(groups.values()), "total_budget": 120000,
                                 "pass": all(v["pass"] for v in budget.values()) and sum(groups.values()) <= 120000}
    checks.update(export_checks(objs, report))
    set_extension(objs, extension)
    return {
        "span_state": label, "extension": extension, "step": STEP,
        "axes": "nose -Y, up +Z, left wing +X, ground Z=0, Y = station - 21.5",
        "overall_m": {"length": round(length, 3), "span": round(span, 3), "height": round(height, 3)},
        "total_tris": sum(p.get("tris", 0) for p in parts.values()), "part_count": len(meshes),
        "all_pass": all(c["pass"] for c in checks.values() if "pass" in c),
        "checks": checks, "parts": parts, "colliders": report["colliders"], "lod1": report["lod1"],
    }


# ---------- renders ----------
def overlay(coll, name, bars, mat):
    bm = bmesh.new()
    for center, size in bars:
        box(bm, Vector(center), size)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
    return obj


def label(coll, name, text, loc, rot, size, mat):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body, cu.size, cu.align_x = text, size, "CENTER"
    obj = bpy.data.objects.new(name, cu)
    obj.location, obj.rotation_euler = loc, rot
    obj.data.materials.append(mat)
    coll.objects.link(obj)
    return obj


def build_render_rig():
    coll = reset_collection("Centurion_render")
    red = material("overlay_red", (0.85, 0.08, 0.05, 1.0))
    t, hw = 0.2, HANGAR_DOOR_W / 2
    door_y = 30.0  # behind the aircraft as seen from the front camera
    door = [overlay(coll, "hangar_door", [
        ((-hw - t / 2, door_y, HANGAR_DOOR_H / 2), (t, t, HANGAR_DOOR_H + 2 * t)),
        ((hw + t / 2, door_y, HANGAR_DOOR_H / 2), (t, t, HANGAR_DOOR_H + 2 * t)),
        ((0, door_y, HANGAR_DOOR_H + t / 2), (HANGAR_DOOR_W + 2 * t, t, t)),
        ((0, door_y, -t / 2), (HANGAR_DOOR_W + 2 * t, t, t))], red),
        label(coll, "hangar_door_label", f"medium hangar door {HANGAR_DOOR_W} x {HANGAR_DOOR_H} m",
              (0, door_y, HANGAR_DOOR_H + 1.0), (math.radians(90), 0, 0), 1.4, red)]
    hd = HANGAR_DEPTH / 2
    foot = [overlay(coll, "hangar_footprint", [
        ((-hw - t / 2, 0, -0.5), (t, HANGAR_DEPTH + 2 * t, t)),
        ((hw + t / 2, 0, -0.5), (t, HANGAR_DEPTH + 2 * t, t)),
        ((0, -hd - t / 2, -0.5), (HANGAR_DOOR_W + 2 * t, t, t)),
        ((0, hd + t / 2, -0.5), (HANGAR_DOOR_W + 2 * t, t, t))], red),
        label(coll, "hangar_footprint_label", f"hangar {HANGAR_DOOR_W} wide x {HANGAR_DEPTH} m deep, door at the nose",
              (0, -hd - 1.6, -0.5), (0, 0, math.pi), 1.4, red)]
    cam = bpy.data.objects.new("render_cam", bpy.data.cameras.new("render_cam"))
    cam.data.clip_end = 1000
    coll.objects.link(cam)
    scene.camera = cam
    return cam, door, foot


VIEWS = {  # name: (ortho scale or (lens,) for perspective, location, rotation or look-at target, overlay)
    "front": (76, (0, -120, 3.8), (90, 0, 0), None),
    "top": (76, (0, 0, 80), (0, 0, 180), None),  # nose up, as the three-view
    "side": (48, (120, 0, 3.8), (90, 0, 90), None),  # from the left (+X) side, nose to the left
    "low34": ((25,), (36, -46, 15), (2.0, -2.0, 4.0), None),  # front-left, above the wing so the sweep reads
    "hero": ((50,), (50, -64, 40), (0.0, 0.0, 3.0), None),  # high front-left three-quarter, as r3_hero
    "closeup": ((40,), (15, -32, 8.0), (3.0, -14.0, 4.0), None),  # nose, windscreen, inner engine and pylon
    "front_hangar": (52, (0, -120, 4.0), (90, 0, 0), "door"),
    "top_hangar": (82, (0, 0, 80), (0, 0, 180), "foot"),
}


def render_views(out, label_, extension, rig):
    cam, door, foot = rig
    workbench_look()
    written = []
    for view, (_, _, _, ov) in VIEWS.items():
        if ov and extension != 0:
            continue
        for o in door:
            o.hide_render = ov != "door"
        for o in foot:
            o.hide_render = ov != "foot"
        written.append(shoot(cam, view, out / f"{view}_{label_}.png"))
    for o in door + foot:
        o.hide_render = True
    return written


def workbench_look():
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1600, 1000, 100
    scene.render.image_settings.file_format = "PNG"
    scene.display.render_aa = "16"
    sh = scene.display.shading
    sh.light, sh.color_type = "STUDIO", "MATERIAL"
    sh.show_cavity, sh.cavity_type = True, "BOTH"
    sh.show_object_outline, sh.object_outline_color = True, (0.05, 0.05, 0.05)
    sh.show_shadows = False
    scene.world = scene.world or bpy.data.worlds.new("World")
    scene.world.color = (0.80, 0.81, 0.83)
    scene.view_settings.view_transform = "Standard"


def render_tail_strike(out, label_, rig, objs):
    """Side views on a runway line: at rest, and pitched TAIL_STRIKE_MIN_DEG nose up about the main contact with the
    struts sagged (the rigid wheels sink by the sag)."""
    coll = bpy.data.collections["Centurion_render"]
    red = bpy.data.materials["overlay_red"]
    c = main_contact(objs)
    marks = [overlay(coll, "runway", [((0, 0, -0.05), (1.0, 60.0, 0.1))], red)]
    written = [shoot(rig[0], "side", out / f"side_runway_rest_{label_}.png")]
    marks.append(label(coll, "runway_label", f"runway; pitched {TAIL_STRIKE_MIN_DEG:.0f} deg about the main wheels, "
                       f"struts sagged {MAIN_STRUT_SAG:.2f} m", (0, 0, -1.6), (math.radians(90), 0, math.radians(90)), 1.2, red))
    roots = [o for o in objs.values() if o.parent is None]
    rest = {o: o.matrix_world.copy() for o in roots}
    pitch = (Matrix.Translation((0, c.y, 0)) @ Matrix.Rotation(-math.radians(TAIL_STRIKE_MIN_DEG), 4, "X")
             @ Matrix.Translation(-c))
    for o in roots:
        o.matrix_world = pitch @ rest[o]
    written.append(shoot(rig[0], "side", out / f"side_runway_pitch{TAIL_STRIKE_MIN_DEG:.0f}_{label_}.png"))
    for o in roots:
        o.matrix_world = rest[o]
    remove_objects(marks)
    return written


def shoot(cam, view, path, res=(1600, 1000)):
    scale, loc, rot, _ = VIEWS[view]
    cam.location = loc
    if isinstance(scale, tuple):
        cam.data.type, cam.data.lens = "PERSP", scale[0]
        cam.rotation_euler = (Vector(rot) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    else:
        cam.data.type, cam.data.ortho_scale = "ORTHO", scale
        cam.rotation_euler = tuple(math.radians(a) for a in rot)
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return str(path)


def save_png(rgb, path):
    """Write an (h, w, 3) array, row 0 at the bottom as Blender stores images, to a PNG."""
    h, w = rgb.shape[:2]
    img = bpy.data.images.new(Path(path).stem, w, h, alpha=False)
    px = np.ones((h, w, 4), np.float32)
    px[..., :3] = rgb
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw, img.file_format = str(path), "PNG"
    img.save()
    bpy.data.images.remove(img)
    return str(path)


def contact_sheet(tiles, path, columns=2):
    arrays = []
    for t in tiles:
        img = bpy.data.images.load(t)
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        arrays.append(px.reshape(h, w, 4)[..., :3])
        bpy.data.images.remove(img)
    rows = [np.hstack(arrays[i:i + columns]) for i in range(0, len(arrays), columns)]
    return save_png(np.vstack(rows[::-1]), path)  # rows run bottom-up, so the first tile row goes on top


def checker_image(cell=32):
    """A 2048 checker of 32 px cells (0.56 m at 57 px/m), each 256 px block tinted its own hue so islands show their
    orientation and an uneven density shows as uneven squares."""
    y, x = np.mgrid[0:ATLAS, 0:ATLAS]
    check = ((x // cell + y // cell) % 2).astype(np.float32)
    hues = np.array([colorsys.hsv_to_rgb((k * 0.618) % 1.0, 0.45, 1.0) for k in range(64)], np.float32)
    tint = hues[(x // 256) * 8 + y // 256]
    rgb = tint * (0.45 + 0.5 * check)[..., None]
    img = bpy.data.images.new("uv_checker", ATLAS, ATLAS, alpha=False)
    px = np.ones((ATLAS, ATLAS, 4), np.float32)
    px[..., :3] = rgb
    img.pixels.foreach_set(px.ravel())
    return img


def render_export_views(out, label_, rig, objs, report):
    """Collider overlay, LOD1 sheet, UV checker views and the UV layout."""
    cam = rig[0]
    sh = scene.display.shading
    meshes = [o for o in objs.values() if o.type == "MESH"]
    cols = [bpy.data.objects[n] for n in report["colliders"]]
    lods = [bpy.data.objects[n] for n in report["lod1"]]
    written = []

    owners = sorted({o.parent.name for o in cols})
    for o in meshes:
        o.color = (0.85, 0.85, 0.85, 1.0)
    for o in cols:
        k = int(o.name.rsplit(".", 1)[1]) if "." in o.name else 0
        hue = (owners.index(o.parent.name) * 0.618) % 1.0
        o.color = (*colorsys.hsv_to_rgb(hue, 0.8, 0.95 - 0.3 * (k % 2)), 1.0)
        o.hide_render = False
    sh.color_type, sh.show_xray, sh.xray_alpha = "OBJECT", True, 0.35
    for view in ("hero", "top", "side", "closeup"):
        written.append(shoot(cam, view, out / f"colliders_{view}_{label_}.png"))
    sh.show_xray = False
    for o in cols:
        o.hide_render = True

    for o in meshes:
        o.hide_render = True
    for o in lods:
        o.hide_render = False
    sh.color_type = "VERTEX"
    (out / "tiles").mkdir(exist_ok=True)
    tiles = [shoot(cam, v, out / "tiles" / f"lod1_{v}_{label_}.png", (800, 500)) for v in ("front", "top", "side", "hero")]
    written.append(contact_sheet(tiles, out / f"lod1_sheet_{label_}.png"))
    for o in lods:
        o.hide_render = True
    for o in meshes:
        o.hide_render = False

    mat = bpy.data.materials[SKIN]
    nodes = mat.node_tree.nodes
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = checker_image()
    nodes.active = tex
    link = mat.node_tree.links.new(tex.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
    sh.color_type = "TEXTURE"
    for view in ("hero", "top", "closeup"):
        written.append(shoot(cam, view, out / f"uvcheck_{view}_{label_}.png"))
    mat.node_tree.links.remove(link)
    image = tex.image
    nodes.remove(tex)
    bpy.data.images.remove(image)
    sh.color_type = "MATERIAL"
    written.append(save_png(report["uv"]["image"], out / "uv_layout.png"))
    return written


# =====================================================================================================================
# Step 6: the settled silhouette
# =====================================================================================================================
# Owner picks at gate G1.6 (docs/DECISIONS.md, 2026-10-12): airframe E with the 6.19 m round body and the M4 nose's shape,
# a 1.5 deg incidence wing, two 4.25 m late-UltraFans hung under the wing as an airliner hangs them, a straight truss
# strut from the body side through the engine's axis to the wing near the retracted tip (the nacelle on its pylon
# braces it, so there is no jury strut), the strut-echo V-tail, a 10.5 deg tail strike, and the AWACS spine well behind
# the wing box under a spine cover; then the owner's review changes in S6_WING, S6_STRUT and S6_VTAIL (a swept-back
# wing with a 25% larger chord, a bigger strut through the engine's centre, a smaller, flatter V-tail) and in S6_BODY_D,
# S6_NOSE and S6_AFT (a slimmer 5.5 m body with longer ends; docs/BLOCKOUT-S6.md "Owner changes"). Stations are the
# finished aircraft's:
# proportion_study.py built round 4 on step 5 stations and stretched a 2 m plug in afterwards.
S6_LENGTH = 44.95  # radome tip to the laser barrel's muzzle
# The round body (owner, second review: "It feels too short"; at the 45 m hangar limit it must read longer instead):
# 5.5 m across, from round 4's 6.19, so the length is 8.2 diameters (7.3 before). The belly stays 1.2 m up, so the
# strike geometry holds and the crown, wing and engines come down 0.69 m.
S6_BODY_D, S6_BODY_BOTTOM = 5.5, 1.2
# The M4 nose (art/blender/m4/nose.py works on step 5's 4.4 m tall nose) at the body's height. Along the body, "len"
# scales the radome and the panes and "taper" the profile's run from the tip to the full section, both against step 5's
# nose (round 4 had 6.19 / 4.4 = 1.41 for both): a longer, sharper taper (owner: "longer-looking ends"), with the
# windscreen held ahead of station 7, where the forward bay starts.
S6_NOSE = {"len": 1.45, "taper": 1.65}
# Aft body: the crown holds to "crown" and droops "droop" over "droop_len"; the sides hold to "side" and close by "close"
# over "close_len"; the belly ramps up from S6_UPSWEEP at S6_RAMP_DEG, which puts the strike at 10.5 deg (round 4's
# --tune_strike 10.5). The second review's longer, slimmer tail cone starts its taper about 2 m sooner than round 4's
# (crown 39.5, droop 0.5 over 4.5; sides 38.0, close 0.35 over 7.0) and ends narrower round the laser turret.
S6_AFT = {"crown": 37.0, "droop": 1.2, "droop_len": 7.0, "side": 37.5, "close": 0.55, "close_len": 7.0}
BOAT_TAIL = None  # step 6.1's tail cone (S61_BOAT_TAIL), which replaces S6_AFT's crown and sides
S6_UPSWEEP, S6_RAMP_DEG = 30.86, 10.45
RAMP_BLEND = 0.0  # step 6.1 blends the belly into the ramp (fus_profile_s6)
PANEL_PROUD = {}  # step 6.1: how far the spine cover and the tail radar panel stand off the skin (m)
# The wing (owner: "the main wing chord should be higher" and "just make them normal sweep"): swept back 15 deg at the
# quarter chord, as the truss-braced X-66 sweeps for a Mach 0.7 to 0.8 cruise (a truss-braced wing's thin, long
# panels want little sweep; 15 deg puts the drag rise past Mach 0.76 without moving the lift far aft), with every
# chord and thickness, the stages' included, 25% larger. The wing moves along the body so its mean chord's quarter
# point stays at round 4's station 19.4, the CG target 1.24 m behind it. The stages' travel along the swept span axis
# grows by cos 12 / cos 15 so the extended span stays 68.2 m.
S6_WING = {"sweep": 15.0, "chord_scale": 1.25, "mac_qc_station": 19.4, "travel": 6.3 * math.cos(math.radians(12.0)) / math.cos(math.radians(15.0))}
# Round 4's sponson (centred at 25.0, 5.6 m a half), holding the main bogie at 25.5; the strut roots on the body above it.
S6_SPONSON = {"station": 25.0, "half_len": 5.6, "half_w": 1.0, "half_h": 1.5, "cz": 2.6, "inset": 0.15}
# The late-UltraFan: a 4.25 m nacelle on a 6.8 m cowl (L/D 1.6) at semi-span "x", its intake plane "ahead_of_le" in
# front of the wing leading edge (30% of the 9.6 m nacelle ahead of it, the rest under the wing), hung on its pylon
# with its crown "crown_gap" under the wing's lower skin. The truss is one straight diagonal from the body side to the
# wing node at 19.4 m through the engine's axis (owner: "passing through the center of the engine"), crossing it
# "strut_u" of the cowl aft of the intake (aft of the fan, over the core; at 0.70 the 2.25 m chord's trailing edge stays
# ahead of the fan nozzle's exit). The engine and the node fix the line; its root is where the line meets the body
# (configure_step6).
S6_ENGINE = {"od": 4.25, "cowl": 6.8, "x": 7.25, "ahead_of_le": 2.9, "crown_gap": 0.32, "strut_u": 0.70,
             "petals": 16, "petal_len": 0.64, "core_len": 1.28, "plug_len": 0.85, "fan_blades": 22}
# The strut is a lifting member too (owner: "slightly bigger and contribute some aerodynamic lift", then "the truss
# chord should also be bigger"): an 18% symmetric section on a 2.25 m chord, narrowing to "fit_chord" at the wing.
S6_STRUT = {"chord": 2.25, "thick": 0.405, "fit_chord": 1.0}
S6_STRUT_JOIN = 0.3  # each segment's collider stops this far short of the node, where the two segments meet
# The fairing collar where the strut passes through the cowl: (offset along the strut, chord and thickness factors).
# Step 6.1 swells it as a cosine-squared bulge that runs out into the strut at both ends, its end rings just inside it.
COLLAR = ((-0.45, 1.03, 1.05), (-0.15, 1.3, 1.8), (0.15, 1.3, 1.8), (0.45, 1.03, 1.05))
S61_COLLAR = tuple((o, 0.99 + 0.31 * math.cos(math.pi * o / 1.4) ** 2, 0.99 + 0.81 * math.cos(math.pi * o / 1.4) ** 2)
                   for o in (-0.7, -0.5, -0.3, -0.15, 0.0, 0.15, 0.3, 0.5, 0.7))
# Round 4's strut-echo V-tail (root low on the aft body at the owner's 40 deg) grown to about 50 m2 a panel and moved as
# far aft as that area allows (owner: "the tail fin should be at the very rear"): the tips' trailing edges end at
# station 44.8, beside the laser turret, and the root rises 0.1 m with it to stay above the strike line. A round body
# under the 7.5 m tip cap leaves only about 5 m of each panel outside the skin, so the area takes 10 m chords; the root
# can't go further aft, where the narrowing, rising tail cone no longer holds it, nor the tip past the 45 m length.
# Then the owner: "Make the rear fin smaller. It's too big imo, 75% of the chord." chord_scale cuts every chord, the
# ruddervators' with it, about the trailing edges, which stay where they were, so the leading edges move aft; the root
# line holds. Then a flatter V, the panels lengthened so the tips still reach the 7.5 m cap: the owner's 30 deg, which
# clears the nacelles and the fan exhaust seen from behind on the slimmer body, whose lower wing hangs the engines
# 0.69 m lower (on the 6.19 m body it crossed the nacelles). The root line moves in with the slimmer body,
# 1.70 m x 2.75 / 3.095 off the centreline, as deep in the aft body's side as before.
S6_VTAIL = {"dihedral": 30.0, "root_z": 3.3, "root_x": 1.51, "root_station": 30.6, "root_chord": 10.0,
            "tip_chord": 9.6, "tip_te_station": 44.8, "hinge": 0.62, "root_buried": 0.3, "chord_scale": 0.75}
S6_TAIL_TIP_MAX = 7.5  # top of the V-tail tips, 0.1 m under the 7.6 m cap
S6_WELL = {"behind_wing": 0.30, "length": 10.10, "width": 0.86, "depth": 1.71}  # docs/M3-DESIGN.md "Blockout measurements"
# The UltraFan nacelle wall (proportion_study.py round 4): (radius over the outer radius, distance aft of the intake plane
# over the cowl length), outer skin from the highlight to the trailing edge, then the bypass duct forward to the lip.
S6_UF_OUTER = ((0.915, -0.004), (0.95, 0.0), (0.975, 0.012), (0.993, 0.04), (1.0, 0.09), (1.0, 0.5), (0.985, 0.66),
               (0.955, 0.8), (0.915, 0.92), (0.89, 1.0))
S6_UF_INNER = ((0.855, 1.0), (0.87, 0.75), (0.885, 0.45), (0.89, 0.2), (0.885, 0.1), (0.875, 0.035), (0.885, 0.01),
               (0.9, -0.003))
# AeroPart masses (kg): round 4's split of CenturionAuthor's 125,000 (the twin's engine groups; the step 5 strut's 1,200
# and jury strut's 500 shared by length between the two segments), then s6_masses moves systems mass between the tail
# cone and the nose so the empty CG sits where round 4 measured it. The cockpit is the Alkyon's donor part, booked on
# the nose; every control surface is 500.
S6_MASS = {"fuselage_M": 15100, "fuselage_F": 8500, "nose": 5958.56, "cockpit": 2000, "radar_F_fairing": 500,
           "fuselage_R": 11000, "tailcone": 7041.44,
           **{f"{p}_{s}": kg for s in "LR" for p, kg in (("vtail", 1500), ("sponson", 3500), ("wing_root", 12500),
                                                         ("strut_inner", 410), ("strut_outer", 1290),
                                                         ("wing_tele1", 2200), ("wing_tele2", 2300))},
           **{f"{p}_{n}": kg for n in (1, 2) for p, kg in (("pylon", 1450), ("nacelle", 8200), ("nozzle", 1600))}}
S6_MASS_STEP6 = dict(S6_MASS)  # before step 6.1's finer part tree moves mass onto its pieces
S6_SURFACE_MASS, S6_EMPTY_MASS = 500, 125000
CONTROL_SURFACES = ("flap_", "aileron_", "spoiler_", "ruddervator_")
S6_CG_TARGET = 20.64  # round 4's strut-echo V-tail airframe (docs/PROPORTION-STUDY.md round 4 "Physics impact")
S6_ROTATION_MS = 98.0  # the 199 t extended rotation speed (SPEC "V-tail")
S6_REF = REPO / ".cache" / "art" / "proportion_study_r4"  # round 4's E4_vee renders, the "before" in the sheets
S6_LABEL = "Step 6"  # the renders' caption prefix
# The before/after sheet's left column: folder, file name, and the caption to stamp (None: the renders carry their own).
S6_BEFORE = (S6_REF, "E4_vee_{v}_retracted.png", "Round 4 (before)")
build_fuselage_s5 = build_fuselage


def uf_r(u):
    """The UltraFan cowl's outer radius over its maximum, u of the cowl length aft of the intake plane."""
    table = [(a, f) for f, a in S6_UF_OUTER[1:]]
    u = min(max(u, 0.0), 1.0)
    for (a0, f0), (a1, f1) in zip(table, table[1:]):
        if u <= a1:
            return f0 + (f1 - f0) * (u - a0) / (a1 - a0)
    return table[-1][1]


def configure_step6():
    """Rebind the step 5 numbers and builders to step 6 (module globals, as proportion_study.py does from outside)."""
    g = globals()
    k = S6_NOSE["len"]
    top = S6_BODY_BOTTOM + S6_BODY_D
    g.update(STEP="s6", LENGTH=S6_LENGTH, Y0=S6_LENGTH / 2, FUS_HALF_W=S6_BODY_D / 2, FUS_BOTTOM=S6_BODY_BOTTOM, FUS_TOP=top,
             FUS_P=2.0, WING_ROOT_TOP=top + 0.4, DIHEDRAL=math.radians(-2.5), INCIDENCE=math.radians(1.5),
             WING_ROOT_LE_STATION=19.25,
             SWEEP=math.radians(S6_WING["sweep"]), TRAVEL=S6_WING["travel"],
             CHORD=tuple((x, S6_WING["chord_scale"] * c) for x, c in ((0.0, 7.8), (13.0, 4.3), (21.8, 2.9))),
             THICK=tuple((x, S6_WING["chord_scale"] * t) for x, t in ((0.0, 0.94), (13.0, 0.51), (21.8, 0.32))),
             TELE=tuple((n, S6_WING["chord_scale"] * c, ln, inset) for n, c, ln, inset in (("wing_tele1", 2.72, 9.0, 0.02),
                                                                                            ("wing_tele2", 2.52, 8.6, 0.04))),
             TIP_RAKE=math.radians(32.0), TIP_UPSWEEP=math.radians(8.0))
    g.update(FUS_CENTER_Z=(FUS_TOP + FUS_BOTTOM) / 2, NOSE_TIP_Z=FUS_BOTTOM + (3.0 - 1.6) / 4.4 * (FUS_TOP - FUS_BOTTOM),
             COS_G=math.cos(DIHEDRAL), CDIR=Vector((0, math.cos(INCIDENCE), -math.sin(INCIDENCE))),
             TDIR=Vector((0, math.sin(INCIDENCE), math.cos(INCIDENCE))), AILERON_HINGE_BEHIND_QC=0.75 * TELE[0][1] + 0.06)
    g.update(XI_PER_X=1 / (COS_G * math.cos(SWEEP)))
    g.update(XI_ROOT_TIP=X_ROOT_TIP * XI_PER_X, ROOT_QC=_root_qc())
    g.update(WING_ROOT_LE_STATION=WING_ROOT_LE_STATION + S6_WING["mac_qc_station"] - s6_wing_mac()[1])
    g.update(ROOT_QC=_root_qc())
    g.update(S6_WELL_START=ROOT_QC.y + Y0 + 0.75 * CHORD[0][1] * CDIR.y + S6_WELL["behind_wing"])

    radome = tuple(round(s * k, 3) for s in (0.15, 0.4, 0.8, 1.3, 1.9, 2.5))
    g.update(fus_profile=fus_profile_s6, PANES=tuple((s0 * k, s1 * k, a0, a1) for s0, s1, a0, a1 in PANES),
             FUSELAGE=(("radar_F_fairing", radome, radome[-1], "nose"),
                       ("nose", (radome[-1], 4.0, 4.45, 4.85, 5.25, 5.7, 6.1, 6.55, 7.0), 7.0, "fuselage_F"),
                       ("fuselage_F", (7.0, 8.5, 10.0, 11.5, 13.0, 15.0, 17.0), 17.0, "fuselage_M"),
                       ("fuselage_M", (17.0, 21.0, 25.0), 21.0, None),
                       ("fuselage_R", (25.0, 27.0, 29.0, 30.0, S6_UPSWEEP, 32.0, 33.0), 25.0, "fuselage_M"),
                       ("tailcone", (33.0, 34.5, 36.0, 37.5, 39.0, 40.5, 42.0, 43.0, 43.6), 33.0, "fuselage_R")),
             TAIL_END=((43.85, 0.8), (44.0, 0.5)), UPSWEEP_START=S6_UPSWEEP,
             UPSWEEP_SLOPE=math.tan(math.radians(S6_RAMP_DEG)), TAIL_STRIKE_MIN_DEG=10.5,
             TAIL_STRIKE_BAND=(10.4, 10.6), TAIL_STRIKE_KEY="tail_strike_10.5deg",
             BAYS=(("F", 7.0, 17.0, "fuselage_F"), ("A", 25.0, 33.0, "fuselage_R")))
    # The main bogies sit 1.055 m outboard of the sponson's centre, as on round 4's body with its track widened to 8.0 m
    # so the inner wheels clear the sponson's underside; the sponsons move in with the slimmer body, and the track with them.
    g.update(MAIN_TRACK=2 * (FUS_HALF_W - S6_SPONSON["inset"] + 1.055), MAIN_GEAR_STATION=25.5, NOSE_PIVOT_Z=FUS_BOTTOM + 0.3, MAIN_PIVOT_Z=2.2,
             NOSE_DOOR_BOTTOM=0.65, SPONSON="sponson", STRUT_WING_X=19.4, STRUT_NODE_CHORD=0.62,
             # the body parts beside fuselage_M (stations 17 to 25) that the root chord also spans
             WING_ROOT_BONDS=tuple(n for n, lo, hi in (("fuselage_F", 7.0, 17.0), ("fuselage_R", 25.0, 33.0))
                                   if WING_ROOT_LE_STATION < hi and WING_ROOT_LE_STATION + CHORD[0][1] > lo),
             COL_INSET_EXACT=True, STAGE_COL_ENDS=True,
             NACELLE_UNDER_BAND=(0.50, 0.70))  # owner: the nacelle mostly under the wing, a smaller fan overhang

    # The engine hangs from the wing, its crown crown_gap under the lower skin where the two come closest. The strut
    # line runs from the wing node through the engine's axis strut_u of the cowl aft of the intake, and its root is
    # where that line, run on inboard, meets the body's skin.
    e, x = S6_ENGINE, S6_ENGINE["x"]
    r, L = e["od"] / 2, e["cowl"]
    le_station = wing_le(1, x)[0].y + Y0
    front = le_station - e["ahead_of_le"]
    axis_z = min(wing_lower(1, x, front + L * u).z - r * uf_r(u) for u in (i / 100 for i in range(101))
                 if front + L * u >= le_station) - e["crown_gap"]
    node = s6_wing_node(1)
    hub = Vector((x, st(front + e["strut_u"] * L), axis_z))
    inward = (hub - node).normalized()
    inside = lambda p: abs(p.x) <= side_x_s6(p.y + Y0, p.z)
    a, b = 0.0, 0.0
    while not inside(hub + inward * b):
        a, b = b, b + 0.25
    for _ in range(40):
        m = (a + b) / 2
        a, b = (a, m) if inside(hub + inward * m) else (m, b)
    root = hub + inward * a
    g.update(STRUT_ROOT=(root.x, root.y + Y0, root.z),
             S6_STRUT_ROOT_PART=next(n for n, rs, _, _ in FUSELAGE if rs[0] <= root.y + Y0 <= rs[-1]))
    g.update(NACELLE_LEN=L, NACELLE_Z=axis_z, NACELLES=((1, 1, x, round(front, 3)), (2, -1, x, round(front, 3))),
             # flap 1 starts outboard of the wing fairing's spill under the root
             SURFACES=(("flap_{s}1", FUS_HALF_W + 0.75, x - 0.6, "flap"), ("flap_{s}2", x + 0.6, 12.4, "flap"),
                       ("aileron_{s}", 12.8, 19.6, "aileron"), ("spoiler_{s}", 12.8, 19.4, "spoiler")),
             WING_UV_CUTS=(x, 13.0))
    # The two collar close-ups look at where the left strut enters the cowl's inboard side and leaves its outboard side:
    # the entry from behind, low, between the sponson and the nacelle, the exit from ahead, low, outboard of the cowl.
    # The crossings move with every change to the wing, body or engine.
    line_root, _, line_node = s6_strut_line(1)
    axis = (line_node - line_root).normalized()
    p_in, p_out = (line_root + axis * d for d in s6_cowl_crossings(1, line_root, line_node))
    at = lambda p, dx, ds, z: (round(p.x + dx, 2), round(p.y + Y0 + ds, 2), z)
    S6_VIEWS["collar_in"] = (("persp", 32), at(p_in, -0.9, 4.2, 1.0), at(p_in, 0, 0, round(p_in.z, 2)),
                             "strut entering the nacelle, from behind inboard, low")
    S6_VIEWS["collar_out"] = (("persp", 32), at(p_out, 2.3, -5.4, 1.2), at(p_out, 0, 0, round(p_out.z, 2)),
                              "strut leaving the nacelle, from ahead outboard, low")

    configure_vtail(S6_VTAIL)

    sides = tuple(f"{p}_{s}" for s in "LR" for p in ("wing_root", "wing_tele1", "wing_tele2", "strut_inner",
                                                     "strut_outer", "sponson", "vtail"))
    g.update(sponson_section=sponson_section_s6, sponson_skin=None,
             SPONSON_RINGS=tuple(S6_SPONSON["station"] + u * S6_SPONSON["half_len"]
                                 for u in (-1, -0.96, -0.85, -0.6, -0.25, 0.1, 0.45, 0.75, 0.92, 1)))
    g.update(build_fuselage=build_fuselage_s6, build_wingfairing=build_wingfairing_s6, build_struts=build_struts_s6,
             build_vtail=build_vtail_s6, build_engines=build_engines_s6, build_tail_systems=build_tail_systems_s6,
             build_geardoors=build_geardoors_s6, EXTRA_BUILDERS=(build_spine_cover,),
             LOAD_PARTS=("nose", "fuselage_F", "fuselage_M", "fuselage_R", "tailcone") + sides
             + tuple(f"{p}_{n}" for n in (1, 2) for p in ("nacelle", "pylon", "nozzle")),
             LOD1_PARTS=lod1_table_s6(), HALF_MIRRORED={}, PYLON_TWINS={2: 1},
             ENGINE_CLEAR_OF=("strut_inner", "strut_outer", "wing_root", "sponson"),
             LENGTH_LIMIT=45.0, HEIGHT_LIMIT=8.0, TAIL_TOP_LIMIT=7.6, EXTENSIONS_CHECKED=(0.0, 0.25, 0.5, 0.75, 1.0),
             LOD1_TOTAL_MIN=0)


# ---------- step 6.1 ----------
# The owner's calls after flying step 6 (docs/DECISIONS.md, docs/BLOCKOUT-S61.md); everything else is step 6's.
# The span twice the retracted one (owner: "381ft is a bit ridiculous. Maybe we can try 2x."): the travel that adds the
# retracted span again, on stages long enough to keep about 3 m inside their parents at full travel (lengths along the
# swept span axis; chords, thickness and insets stay step 6's). Retracted, they run from 5.9 and 6.3 m out, past the
# pylon, to the root's tip; each collider covers the run that can leave its parent (LONG_STAGES): 87.1 m extended.
S61_STAGE_LENGTHS, S61_TRAVEL, S61_SPAN_EXTENDED = (14.6, 14.2), 11.29, 87.1
# "This wing attachment area is too bulky", then "the hump can be more streamlined still": a teardrop over the wing
# root (build_wingfairing_s61). Its top rises over the crown by "rise" (3 cm over the root's top skin), from "start"
# metres ahead of the root's leading edge to the peak at "peak" of the root chord (its thickest point), and closes to the
# AWACS well; both ramps are smoothsteps, so it leaves and rejoins the crown tangentially, and it starts and ends
# "bury" under the skin. Each section runs level across the top and curves down to meet the body tangentially, from
# "phi_end" degrees round the body from the crown at its ends to "phi_mid" over the wing root (C-17, A400M).
S61_FAIRING = {"start": -4.0, "peak": 0.30, "rise": 0.43, "bury": 0.06, "phi_end": 22.0, "phi_mid": 56.0}
# "The gear pods need to be more streamlined": a long, low pod with an elliptic nose that starts where step 6's did,
# behind the strut root, a full section from "full" to "aft" that holds the stowed bogie, and a tail whose centre runs up
# and inboard to (tail_x, tail_z) as the section shrinks (by 1 - q ** tail_power), into the body's side short of
# station 33, where the tail cone starts. 2.2 m tall (from 3.0), its bottom 5 cm higher and its outer edge where step
# 6's was, so the track holds and the inner wheels keep 7 cm under it; narrower inboard than outboard, so its underside
# meets the body outboard of the aft bay doors' hinges.
S61_SPONSON = {"nose": 19.4, "full": 23.3, "aft": 27.7, "tail": 32.9, "inset": 0.15, "cz": 2.25, "half_w": 1.0,
               "half_w_in": 0.85, "half_h": 1.1, "tail_z": 3.1, "tail_power": 1.6, "fillet": 0.45, "door_deg": 139.5}
# Owner: "the design should just flow into each other with natural lines". The pod's nose and tail sit on the body's
# skin, and where its skin meets the body's it turns into it along a fillet (sponson_skin_s61) about "fillet" metres a
# side, the lower one ending on the body short of "door_deg" round from the crown, where the aft bay doors' hinges are.
S61_SPONSON_RINGS = (19.4, 19.5, 19.75, 20.2, 20.9, 21.8, 22.6, 23.3, 27.7, 28.2, 28.7, 29.2, 29.7, 30.2, 30.7, 31.2,
                     31.7, 32.2, 32.6, 32.9)
S61_MAIN_HINGE = (0.10, 2.1)  # the main gear's hinge axis: metres inside the pod's outboard flank, height (configure_step61)
# Owner, flying the lens dome: "does the tail need to be so wide and bulbous if there is nothing in there?" The tail
# cone holds only the V-tail roots (34.98 to 40.6, low on its sides), the aft-facing tail radar under its panel (40.9 to
# 43.5; a dish about 1 m across, as the Alkyon's nose radar it copies has room for) and the laser emitter, so it closes
# into a boat-tail: the crown droops from "crown", the sides close from "side" (to "side_power", slow while they still
# hold the roots: the ruddervators' root stays where it was, 1.45 m out along the panel) and the belly leaves its ramp
# at "belly", each reaching the tip's section at "at", the laser turret's TAIL_END: "half_w" by "top" over step 6's
# section centre there (fus_profile_s6), the turret's pivot height, so the C-RAM's pivot and hardpoint stay put.
S61_BOAT_TAIL = {"at": 44.0, "top": 5.21, "half_w": 0.75, "crown": 36.0, "side": 37.5, "side_power": 2.0,
                 "belly": 40.0}
# Owner, 2026-10-18: "make the tail a bit less bulbous and more streamlined/planeish", "just a model edit"; 2026-10-19,
# of a near-straight taper to a 1.0 x 0.78 m end: "too pointy imo. keep it subtly curved like a real plane". The art's
# aft body curves down from station 33 at its crown and in from 37.5 at its sides, slimmer than S61_BOAT_TAIL all the
# way, into a 1.36 x 1.12 m end (its centre held, so the laser turret keeps its pivot) that it reaches at 12 deg in side
# view and 14 in plan, so the lens, which carries the taper on (m4/fuselage_aft_laser.py), rounds it off blunt. Owner,
# 2026-10-20: "The top should curve down, the bottom should curve up": a crown_slope under 1.5 (hermite_law's least
# that never bends back) flattens the crown into the end, which reads as an up-turn (fuselage_aft.crown_profile). The skin
# under the V-tail roots comes in up to 7 cm, over roots buried 0.3 m whose fillets land on the art's skin. Only the
# art and the tail's colliders follow it (visual_tail); the blockout's shapes, which the flight model is measured on,
# keep S61_BOAT_TAIL.
S61_BOAT_TAIL_VISUAL = {"at": 44.0, "top": 5.12, "half_w": 0.68, "crown": 33.0, "side": 37.5, "side_power": 2.0,
                        "crown_slope": 1.5, "side_slope": 0.8, "belly": 40.0}
VISUAL_TAIL_PARTS = ()  # step 6.1: the parts whose colliders follow the art's aft body
# Owner, 2026-10-16: "Make the entire trailing edge movable and split it into two, so that we can bias one towards pitch
# and one towards yaw, but if needed, both can do both." The moving trailing edge runs from the root, where the inboard
# surface turned to its full throw either way still stands root_clear outside the aft body's skin, into the rounded tip,
# whose last tip_cap metres stay fixed (the tail light, formation strips and a discharger). It is cut at split metres
# along the panel, gap wide: surface 1 inboard, biased to yaw, low beside the body where its side force rolls the
# aircraft least; surface 2 outboard, biased to pitch. ranges: each surface's (pitch, yaw) range in degrees, as
# CenturionAuthor's Surfaces; the game turns a surface by their sum (ControlSurfaceJob_Math.cs:52-75), so the two differ
# by at most 32 deg, and both turn about one hinge line. Chordwise ends at the split then clear each other only if the gap
# exceeds 2 r tan(sweep) sin(difference / 2) / cos(sweep), r the noses' radius about the hinge (0.18 m there): 7 cm.
S61_SPLIT_TAIL = {"root_clear": 0.1, "tip_cap": 0.56, "split": 3.6, "gap": 0.08, "ranges": ((15.0, 25.0), (30.0, 8.0))}


def sponson_section_s61(s):
    """Step 6.1's pod (S61_SPONSON) at station s on the left side, as sponson_section_s6 gives step 6's."""
    p = S61_SPONSON
    if not p["nose"] <= s <= p["tail"]:
        return None
    cx, cz, f = FUS_HALF_W - p["inset"], p["cz"], 1.0
    if s < p["full"]:
        f = math.sqrt(max(0.0, 1 - ((p["full"] - s) / (p["full"] - p["nose"])) ** 2))
        cx = side_x_s6(p["nose"], cz) + (cx - side_x_s6(p["nose"], cz)) * f  # the nose on the skin
    elif s > p["aft"]:
        q = (s - p["aft"]) / (p["tail"] - p["aft"])
        m = smooth(q)  # the centre turns off its line tangentially
        cx, cz, f = cx + (side_x_s6(p["tail"], p["tail_z"]) - cx) * m, cz + (p["tail_z"] - cz) * m, 1 - q ** p["tail_power"]
    return cx, cz, p["half_w"] * f, p["half_w_in"] * f, p["half_h"] * f


def sponson_skin_s61(s):
    """The pod's render section at station s, left side, as (x, z) points: its exposed arc, turned into the body's skin
    by a fillet at each end (Hermite curves matching both skins' slopes), then back inside the body. The collider keeps
    the plain, convex pod (sponson_section)."""
    p = S61_SPONSON
    cx, cz, a_out, a_in, b = sponson_section(s)
    w, top, bot = fus_profile(s)
    zc, h = (top + bot) / 2, (top - bot) / 2
    pod = lambda t: Vector((cx + (a_out if math.sin(t) > 0 else a_in) * math.sin(t), cz + b * math.cos(t)))
    pod_tan = lambda t: Vector(((a_out if math.sin(t) > 0 else a_in) * math.cos(t), -b * math.sin(t))).normalized()
    out = lambda q: (q.x / w) ** 2 + ((q.y - zc) / h) ** 2 > 1
    ts = [2 * math.pi * i / 720 for i in range(720)]
    flags = [out(pod(t)) for t in ts]
    start = next(i for i in range(720) if flags[i] and not flags[i - 1])  # the exposed arc, clockwise from its top end
    end = next(i for i in range(start, start + 720) if not flags[(i + 1) % 720]) % 720

    def edge(i, j):  # where the pod crosses the skin between samples i (one side) and j
        lo, hi = ts[i], ts[i] + ((ts[j] - ts[i]) % (2 * math.pi))
        for _ in range(30):
            m = (lo + hi) / 2
            lo, hi = (m, hi) if out(pod(m)) == out(pod(lo)) else (lo, m)
        return (lo + hi) / 2
    t_a, t_b = edge(start - 1, start), edge(end, (end + 1) % 720)
    if t_b < t_a:
        t_b += 2 * math.pi
    body = lambda phi, k=1.0: Vector((w * math.sin(phi) * k, zc + h * math.cos(phi) * k))
    body_tan = lambda phi: Vector((w * math.cos(phi), -h * math.sin(phi))).normalized()
    phi_of = lambda q: math.atan2(q.x / w, (q.y - zc) / h)
    size = b / p["half_h"]  # the fillets shrink with the pod toward its ends
    arc = lambda d, phi: d / math.hypot(w * math.cos(phi), h * math.sin(phi))  # body angle for d metres of skin
    d = p["fillet"] * size
    t_a2, t_b2 = t_a + d / max(a_out, a_in, b), t_b - d / max(a_out, a_in, b)
    phi_a, phi_b = phi_of(pod(t_a)), phi_of(pod(t_b))
    phi_a2 = phi_a - arc(d, phi_a)
    phi_b2 = min(phi_b + arc(d, phi_b), max(phi_b + 0.002, math.radians(p["door_deg"])))
    ka, kb = (body(phi_a2) - pod(t_a2)).length, (body(phi_b2) - pod(t_b2)).length  # handles the span they bridge
    fa = hermite(body(phi_a2), body_tan(phi_a2) * ka, pod(t_a2), pod_tan(t_a2) * ka, 5)
    mid = [pod(t_a2 + (t_b2 - t_a2) * i / 12) for i in range(1, 12)]
    fb = hermite(pod(t_b2), pod_tan(t_b2) * kb, body(phi_b2), body_tan(phi_b2) * kb, 5)
    inner = [body(phi_b2 + (phi_a2 - phi_b2) * i / 6, 0.9) for i in range(1, 6)]
    return fa + mid + fb + inner


def hermite(p0, t0, p1, t1, n):
    """n + 1 points of the cubic Hermite curve from p0 (tangent t0) to p1 (tangent t1)."""
    out = []
    for i in range(n + 1):
        u = i / n
        out.append(p0 * (2 * u ** 3 - 3 * u ** 2 + 1) + t0 * (u ** 3 - 2 * u ** 2 + u)
                   + p1 * (-2 * u ** 3 + 3 * u ** 2) + t1 * (u ** 3 - u ** 2))
    return out


def body_point(s, phi, scale=1.0):
    """The body's skin at station s, phi radians round from the crown toward +x, scaled about the section's centre;
    and the skin's tangent there, toward larger phi."""
    w, top, bot = fus_profile(s)
    zc, h = (top + bot) / 2, (top - bot) / 2
    p = Vector((w * math.sin(phi) * scale, st(s), zc + h * math.cos(phi) * scale))
    return p, Vector((w * math.cos(phi), 0, -h * math.sin(phi))).normalized()


def build_wingfairing_s61(parts):
    """The step 6.1 wing fairing (S61_FAIRING): each section a level top over the wing root that curves down to meet
    the body's skin tangentially (a Hermite curve from the top to the skin, matching the skin's slope), closed inside
    the body; along the body a smoothstep teardrop that leaves and rejoins the crown tangentially, its sections
    narrowing to its ends, both buried under the skin. Its hump ends ahead of the AWACS well, so the spine cover lies
    on the round crown. No collider: the long stages run through it inside the root, whose collider and the body's
    fill it."""
    p = S61_FAIRING
    s0, peak, s1 = WING_ROOT_LE_STATION + p["start"], WING_ROOT_LE_STATION + p["peak"] * CHORD[0][1], S6_WELL_START - 0.1
    rings, n = [], 40
    for s in [s0 + (s1 - s0) * i / n for i in range(n + 1)]:
        k = smooth((s - s0) / (peak - s0)) if s < peak else smooth((s1 - s) / (s1 - peak))
        top = fus_profile(s)[1] + (p["rise"] + p["bury"]) * k - p["bury"]
        phi = math.radians(p["phi_end"] + (p["phi_mid"] - p["phi_end"]) * k)
        arcs = []
        for side in (-1, 1):
            skin, tan = body_point(s, side * phi)
            crest = Vector((0, st(s), top))
            span = (skin - crest).length
            arcs.append(hermite(crest, Vector((side * span, 0, 0)), skin, tan * side * span, 12))
        upper = list(reversed(arcs[0])) + arcs[1][1:]  # -x skin over the crest to +x skin
        inner = [body_point(s, phi - 2 * phi * j / 8, 0.9)[0] for j in range(1, 8)]  # back under, inside the body
        rings.append(upper + inner)
    for ring in (rings[0], rings[-1]):
        for q in ring:
            w, top_, bot = fus_profile(q.y + Y0)
            zc, h = (top_ + bot) / 2, (top_ - bot) / 2
            if (q.x / w) ** 2 + ((q.z - zc) / h) ** 2 > 1.002:  # on the skin at the junction, never past it
                raise SystemExit(f"wingfairing end ring at station {q.y + Y0:.2f} pokes out of the body at {tuple(round(c, 2) for c in q)}")
    bm = bmesh.new()
    loft(bm, rings, seams=(len(rings[0]) - 4,), cap_mat=(1, 1))
    add_part(parts, "wingfairing", bm, Vector((0, st(21.0), FUS_TOP)), "fuselage_M", mats=(SKIN, STRUCT),
             bonded_to="wing_root_L,wing_root_R,fuselage_F,fuselage_R")


def configure_step61():
    """Step 6 with the owner's step 6.1 changes: long stages, a slimmer wing fairing, streamlined sponsons; M3's open
    AWACS spine well (WELL_OPEN); the longer aft bay, a cavity (AFT_BAY_ROOF); and the flight deck's escape hatches
    and crew door (build_flightdeck_exits, NOSE_EXITS)."""
    configure_step6()
    g = globals()
    g.update(STEP="s61", S6_LABEL="Step 6.1", TRAVEL=S61_TRAVEL, SPAN_EXTENDED=S61_SPAN_EXTENDED, LONG_STAGES=True, WELL_OPEN=True,
             TELE=tuple((n, c, length, inset) for (n, c, _, inset), length in zip(TELE, S61_STAGE_LENGTHS)),
             build_wingfairing=build_wingfairing_s61, sponson_section=sponson_section_s61,
             sponson_skin=sponson_skin_s61, SPONSON_RINGS=S61_SPONSON_RINGS,
             S6_BEFORE=(REPO / ".cache" / "art" / "blockout_s6", "{v}_retracted.png", None))
    # Owner: "the hinge should be inside the plane". The main legs hinge inside the pod's outboard flank (S61_MAIN_HINGE),
    # where step 6 hung them over the bogie, outside it; the sponson's skin swells over the leg's top (m4/struts.py
    # HINGE_BUMP) and the strut rakes out from the hinge to its foot, so the wheels stay put. The hinge sits lower than
    # step 6's 2.2 m: the shorter leg stows the bogie further outboard, clear of the aft bay.
    inset, z = S61_MAIN_HINGE
    cx, cz, a, _, b = sponson_section_s61(MAIN_GEAR_STATION)
    g.update(MAIN_PIVOT_X=cx + a * math.sqrt(1 - ((z - cz) / b) ** 2) - inset, MAIN_PIVOT_Z=z)
    # The belly turns into the tail-strike ramp over 1.5 m either side of its start: 7 cm higher at the corner, the ramp
    # itself (and so the strike at the aft bay door, station 32.6) unchanged; rings along the blend carry it.
    # The AWACS spine cover and the tail radar's panel near-flush, 1.2 cm proud (4.5 and 3.5 cm on step 6).
    g.update(PANEL_PROUD={"spine": 0.012, "radar_R": 0.012})
    g.update(COLLAR=S61_COLLAR, RAMP_BLEND=1.5, FUSELAGE=tuple((n, (25.0, 27.0, 29.0, 29.36, 29.9, 30.4, S6_UPSWEEP, 31.3, 31.8, 32.36, 33.0), o, par)
                                         if n == "fuselage_R" else (n, rs, o, par) for n, rs, o, par in FUSELAGE))
    # The tail cone closes onto the laser turret along a parabola in its section's scale from station 43.5, where the tail
    # radar's panel ends, leaving the cone's line tangentially (step 6 stepped in at 43.6); the end stays at 44.0, so the
    # turret holds its place. The ring at 36.75 splits the run where the boat-tail's crown starts down while its sides
    # still hold, whose two rings alone hull 9 mm proud of the skin between them (the colliders' inset check); the rings
    # 0.75 m apart from 37.5 keep the closing sides' turns in plan under the silhouette report's 5 deg (8 at 1.5 m).
    g.update(FUSELAGE=tuple((n, (33.0, 34.5, 36.0, 36.75, 37.5, 38.25, 39.0, 39.75, 40.5, 41.25, 42.0, 43.0, 43.5), o, par)
                            if n == "tailcone" else (n, rs, o, par) for n, rs, o, par in FUSELAGE),
             TAIL_END=tuple((s_, 1 - 0.45 * ((s_ - 43.5) / 0.5) ** 2) for s_ in (43.6, 43.7, 43.8, 43.9, 44.0)),
             BOAT_TAIL=S61_BOAT_TAIL)
    # Owner: "Drop the tail fin chord by another 25%" (0.75 to 0.5625, cut as before about the trailing edges) and
    # "make the tips end in a more rounded thing": the V-tail's last 1.5 m and the wingtip's outer 45% close
    # elliptically on a point 0.75 of the chord back, a curved rake with no corner.
    configure_vtail({**S6_VTAIL, "chord_scale": 0.5625}, tip_round=(1.5, 0.75), split=S61_SPLIT_TAIL)
    for s in "LR":  # each panel's LOD1 hull takes its split tail's surfaces
        LOD1_PARTS[f"vtail_{s}"] = (LOD1_PARTS[f"vtail_{s}"][0], tuple(n + "_visible" for n, _ in ruddervator_spans("_" + s)))
    g.update(TIP_ROUND=(0.55, 0.75))
    # Owner: the aft bay holds the 500 kg bombs x12 (8.53 m) as the forward one does, with a real cavity. Its doors keep
    # their aft end (32.6, the tail strike's first contact) and run forward 1.8 m, 1.4 m into fuselage_M's belly
    # (fuselage_R is 8 m long), so the hardpoint at the doors' middle moves to 28.1; the roof is the forward bay's
    # (m4/nose.py BAY_CEILING). fuselage_R's LOD1 takes the doors, which close the cavity's opening.
    g.update(BAYS=(BAYS[0], ("A", 23.2, 33.0, "fuselage_R")), AFT_BAY_ROOF=4.40)
    # The flight deck's own escape hatches and crew door, and the nose collider's notch over the hatches
    # (docs/COCKPIT-DESIGN.md). Their panels close the nose's skin, so the silhouettes trace them with it.
    g.update(EXTRA_BUILDERS=EXTRA_BUILDERS + (build_flightdeck_exits,), NOSE_EXITS=True,
             SMOOTH_BODY=SMOOTH_BODY + ("nose_hatch_L", "nose_hatch_R", "nose_door_visible"))
    LOD1_PARTS["fuselage_R"] = (LOD1_PARTS["fuselage_R"][0],
                                LOD1_PARTS["fuselage_R"][1] + ("baydoor_AL_visible", "baydoor_AR_visible"))
    # Damage stage 2 (owner, 2026-10-18): the finer part tree, each piece's mass taken from its source, and LOD1 hulls
    # on the cores (folding their panels) and the larger pieces only (owner: "skip them on the tiniest pieces").
    import part_splits
    masses = dict(S6_MASS_STEP6)
    for name, kg in part_splits.mass_moves().items():
        masses[name] = masses.get(name, 0.0) + kg
    g.update(PART_SPLITS=True, S6_MASS=masses, VISUAL_TAIL_PARTS=("tailcone",))
    for s in "LR":
        LOD1_PARTS[f"wing_root_{s}"] = (17, (f"flap_{s}1_visible", f"flap_{s}2_visible", f"flap_track_{s}1", f"flap_track_{s}2"))
        LOD1_PARTS[f"wing_outer_{s}"] = (17, (f"aileron_{s}_visible", f"spoiler_{s}_visible"))
        LOD1_PARTS[f"wing_tele2_{s}"] = (17, (f"wing_tip_{s}",))
        LOD1_PARTS[f"vtail_{s}"] = (17, (f"ruddervator_{s}1_visible",))
        LOD1_PARTS[f"vtail_tip_{s}"] = (12, (f"ruddervator_{s}2_visible",))
        LOD1_PARTS[f"sponson_tail_{s}"] = (9, ())
    LOD1_PARTS["fuselage_F"] = (17, ("fuselage_F_upper", "cheek_L", "cheek_R"))
    LOD1_PARTS["fuselage_F2"] = (17, ("fuselage_F2_upper",))
    LOD1_PARTS["fuselage_M"] = (17, ("wingfairing", "fuselage_M_flank_L", "fuselage_M_flank_R"))
    LOD1_PARTS["fuselage_R"] = (17, ("spine_cover", "spine_cover_A", "fuselage_R_upper_L", "fuselage_R_upper_R",
                                     "baydoor_AL_visible", "baydoor_AR_visible"))
    LOD1_PARTS["tailcone"] = (17, ("tailcone_upper",))
    LOD1_PARTS["tail_end"] = (17, ("tail_end_upper", "radar_R_fairing"))
    # The extended wing is 87 m across: wider frames, and a wider lens on the hero camera.
    S6_STATE_CAMERA["extended"] = {"hero": ("persp", 36), "top": ("ortho", 94), "front": ("ortho", 94),
                                   "rear_full": ("ortho", 94)}


def configure_vtail(t, tip_round=None, split=None):
    """The V-tail from a shape dict (S6_VTAIL): chord_scale cuts every chord, the ruddervators' with it, about the
    trailing edges, which stay where they were, so the leading edges move aft; the root line holds. The panel runs out
    to the 7.5 m tip cap. tip_round: step 6.1's rounded tip (VTAIL_TIP_ROUND), the ruddervator ending short of it.
    split: the split tail (S61_SPLIT_TAIL), whose moving trailing edge runs into the rounded tip."""
    g = globals()
    dih = math.radians(t["dihedral"])
    k = t["chord_scale"]
    root_chord, tip_chord = k * t["root_chord"], k * t["tip_chord"]
    tip_half_thick = 0.5 * 0.07 * tip_chord * math.cos(dih)
    span = (S6_TAIL_TIP_MAX - t["root_z"] - tip_half_thick) / math.sin(dih)
    if tip_round is not None:  # the rounded tip tops out short of its end: run the panel out until it meets the cap
        def top(sp):
            def z(d):
                g_ = max(0.0, (d - sp + tip_round[0]) / tip_round[0])
                chord = (root_chord + (tip_chord - root_chord) * d / sp) * math.sqrt(max(0.0, 1 - g_ * g_))
                return t["root_z"] + d * math.sin(dih) + 0.5 * chord * (0.10 - 0.03 * d / sp) * math.cos(dih)
            return max(z(sp * i / 400) for i in range(401))
        lo, hi = span, span + 2.0
        for _ in range(40):
            lo, hi = (lo, (lo + hi) / 2) if top((lo + hi) / 2) > S6_TAIL_TIP_MAX else ((lo + hi) / 2, hi)
        span = lo
    root_station = t["root_station"] + (1 - k) * t["root_chord"]  # the root's trailing edge stays put
    # The leading-edge sweep that puts the tip's trailing edge at tip_te_station.
    sweep = math.atan2(t["tip_te_station"] - tip_chord - root_station, span)
    g.update(VTAIL_DIHEDRAL=dih, VTAIL_SWEEP=sweep, VTAIL_ROOT_CHORD=root_chord,
             VTAIL_TIP_CHORD=tip_chord, VTAIL_ROOT_STATION=root_station, VTAIL_ROOT_Z=t["root_z"],
             VTAIL_ROOT_X=t["root_x"], VTAIL_SPAN=span, RUDDERVATOR_HINGE=t["hinge"], vtail_section=vtail_section_s6,
             VTAIL_TIP_ROUND=tip_round, SPLIT_TAIL=split)
    if split is None:
        g.update(RUDDERVATOR_SPAN=(ruddervator_root_s6(), VTAIL_SPAN - (0.35 if tip_round is None else tip_round[0] + 0.05)))
    else:
        g.update(RUDDERVATOR_SPAN=(split_root_s6(split["root_clear"], sum(split["ranges"][0])), VTAIL_SPAN - split["tip_cap"]))


def fus_profile_s6(s):
    """Round 4's body: the step 5 nose profile on the round body (side-view lengths by S6_NOSE's taper, plan-view
    lengths by the width over step 5's 4.0 m and the same taper over the body's height scale, so the nose keeps the
    M4's point from above), a round barrel, and the heavy-lifter aft body over a belly ramp parallel to the strike line."""
    a, taper = S6_AFT, S6_NOSE["taper"]
    w = FUS_HALF_W * ell(s / (7.0 * FUS_HALF_W / 2.0 * taper / (S6_BODY_D / 4.4)), 1.6)
    top = NOSE_TIP_Z + (FUS_TOP - NOSE_TIP_Z) * ell(s / (9.0 * taper), 1.5)
    bot = NOSE_TIP_Z - (NOSE_TIP_Z - FUS_BOTTOM) * ell(s / (4.5 * taper), 1.7)
    u = s - UPSWEEP_START
    if u > -RAMP_BLEND:  # the belly turns up into the ramp along a parabola RAMP_BLEND metres either side (C1)
        bot = FUS_BOTTOM + UPSWEEP_SLOPE * (u if u >= RAMP_BLEND else (u + RAMP_BLEND) ** 2 / (4 * RAMP_BLEND))
    bt = BOAT_TAIL
    if bt is not None:
        q = lambda start: (s - bt[start]) / (bt["at"] - bt[start])
        ramp_end = FUS_BOTTOM + UPSWEEP_SLOPE * (bt["at"] - UPSWEEP_START)
        centre = (FUS_TOP - a["droop"] * ((bt["at"] - a["crown"]) / a["droop_len"]) ** 2 + ramp_end) / 2  # step 6's
        # a slope key: leave level, arrive at that slope (a near-straight taper into the end, not a pinch)
        law = lambda u, key, power: hermite_law(u, bt[key]) if key in bt else u ** power
        if s > bt["crown"]:
            top = FUS_TOP - (FUS_TOP - bt["top"]) * law(q("crown"), "crown_slope", 2)
        if s > bt["side"]:
            w = FUS_HALF_W - (FUS_HALF_W - bt["half_w"]) * law(q("side"), "side_slope", bt["side_power"])
        if s > bt["belly"]:
            bot += (2 * centre - bt["top"] - ramp_end) * q("belly") ** 2
        return w, top, bot
    if s > a["crown"]:
        top = FUS_TOP - a["droop"] * ((s - a["crown"]) / a["droop_len"]) ** 2
    if s > a["side"]:
        w = FUS_HALF_W * (1 - a["close"] * (min(s - a["side"], a["close_len"]) / a["close_len"]) ** 1.8)
    return w, top, bot


def hermite_law(u, k):
    """0 to 1 over u, leaving level and arriving at slope k."""
    return (3 - k) * u * u + (k - 2) * u ** 3


@contextlib.contextmanager
def visual_tail():
    """The aft body as the art draws it (S61_BOAT_TAIL_VISUAL), for what follows the skin the player sees: the art's
    hulls and the tail's colliders. The flight model's shapes keep BOAT_TAIL."""
    global BOAT_TAIL
    saved = BOAT_TAIL
    BOAT_TAIL = S61_BOAT_TAIL_VISUAL or saved
    try:
        yield
    finally:
        BOAT_TAIL = saved


def side_x_s6(s, z):
    """Half width of the fuselage skin at a station and height (0 above or below it)."""
    w, top, bot = fus_profile(s)
    zc, h = (top + bot) / 2, (top - bot) / 2
    u = abs(z - zc) / h
    return 0.0 if u >= 1 else w * (1 - u ** FUS_P) ** (1 / FUS_P)


def build_fuselage_s6(parts):
    """Step 5's fuselage on the step 6 stations, with round 4's blocking of the M4 nose details: a dark surround as a
    frame round each of the four panes and a centre post between the front pair (beside the glass, never under it),
    and a dark joint band where the radome meets the nose."""
    build_fuselage_s5(parts)
    k, bm = S6_NOSE["len"], next(p for p in parts if p["name"] == "nose")["bm"]
    w, da = 0.12 * k, 4.0  # frame width along the fuselage (m) and round it (deg)
    strips = [((PANES[0][0], PANES[0][1]), -PANES[0][2], PANES[0][2])]  # the centre post
    for s0, s1, a0, a1 in PANES:
        for sg in (1, -1):
            lo, hi = sorted((sg * a0, sg * a1))
            strips += [((s0 - w, s0), lo - da, hi + da), ((s1, s1 + w), lo - da, hi + da),
                       ((s0, s1), lo - da, lo), ((s0, s1), hi, hi + da)]
    for (s0, s1), a0, a1 in strips:
        for f in skin_panel(bm, [s0 + (s1 - s0) * i / 4 for i in range(5)], a0, a1, -0.01, 0.016, n_a=3):
            f.material_index = 1
    j = FUSELAGE[0][2]
    for f in skin_panel(bm, (j, j + 0.035 * k, j + 0.07 * k), -179.0, 179.0, -0.01, 0.012, n_a=36):
        f.material_index = 1


def build_wingfairing_s6(parts):
    """Step 5's dorsal fairing, widened by the body's width over step 5's 4.0 m and raised with the crown (round 4); its
    hump ends ahead of the AWACS spine well, so the spine cover lies on the round crown. Its stations are round 4's
    against that wing's 7.8 m root chord from station 19.25, moved and stretched with the root chord."""
    ws = lambda s: WING_ROOT_LE_STATION + (s - 19.25) * CHORD[0][1] / 7.8
    s0, s1, peak, hump_end = ws(16.8), ws(30.5), ws(21.8), S6_WELL_START - 0.1
    k, dz = FUS_HALF_W / 2.0, FUS_TOP - 6.0
    rings = []
    n = round(34 * (s1 - s0) / 13.7)  # denser than round 4 (22 over its 13.7 m), so the stretched hull and its end ramps stay inset
    for s in [s0 + (s1 - s0) * i / n for i in range(n + 1)]:
        bw = smooth((s - s0) / 2.8) * (1 - smooth((s - ws(23.4)) / (s1 - ws(23.4))))
        bt = 0.5 * (1 + math.cos(math.pi * min(abs(s - peak) / ((peak - s0) if s < peak else (hump_end - peak)), 1.0)))
        # Over its first and last 2.8 m the ring grows out of one buried in the body's local section (0.55 of its
        # half-width, 0.15 m under its crown), so both ends blend out of the skin with no cap showing: the front starts
        # on the nose taper, where the crown is still under the fairing's flat top.
        f = smooth((s - s0) / 2.8) * (1 - smooth((s - s1 + 2.8) / 2.8))
        wb, topb, _ = fus_profile(s)
        w = 0.55 * wb + ((1.45 + 1.0 * bw) * k - 0.55 * wb) * f
        top, bot = topb - 0.15 + (5.92 + dz + 0.64 * bt - topb + 0.15) * f, 3.9 + dz
        zc, h = (top + bot) / 2, (top - bot) / 2
        ring = []
        for i in range(32):
            a = 2 * math.pi * i / 32
            sx, cz = math.sin(a), math.cos(a)
            ring.append(Vector((w * math.copysign(abs(sx) ** (2 / 2.6), sx), st(s), zc + h * math.copysign(abs(cz) ** (2 / 2.6), cz))))
        rings.append(ring)
    for ring in (rings[0], rings[-1]):  # each capped end ring inside the body, 3% short of its skin
        for p in ring:
            wb, topb, botb = fus_profile(p.y + Y0)
            zc, h = (topb + botb) / 2, (topb - botb) / 2
            if (abs(p.x) / wb) ** FUS_P + (abs(p.z - zc) / h) ** FUS_P > 0.97 ** FUS_P:
                raise SystemExit(f"wingfairing end ring at station {p.y + Y0:.2f} pokes out of the body at {tuple(round(c, 2) for c in p)}")
    bm = bmesh.new()
    loft(bm, rings, seams=(16,), cap_mat=(1, 1))
    add_part(parts, "wingfairing", bm, Vector((0, st(21.0), FUS_TOP)), "fuselage_M", mats=(SKIN, STRUCT),
             col=[{"rings": rings, "start": "cap", "end": "cap", "owner": "fuselage_M"}],
             bonded_to="wing_root_L,wing_root_R,fuselage_F,fuselage_R")


def s6_wing_node(side):
    """The strut's wing node: on the lower skin at the rear spar near the retracted tip."""
    le, c, _ = wing_le(side, STRUT_WING_X)
    return wing_lower(side, STRUT_WING_X, le.y + Y0 + STRUT_NODE_CHORD * c)


def s6_strut_line(side):
    """The strut's straight line: the root on the body's side, the node where it crosses the engine's semi-span on the
    engine's axis, and the wing node."""
    root = Vector((side * STRUT_ROOT[0], st(STRUT_ROOT[1]), STRUT_ROOT[2]))
    wing = s6_wing_node(side)
    return root, root.lerp(wing, (S6_ENGINE["x"] - STRUT_ROOT[0]) / (abs(wing.x) - STRUT_ROOT[0])), wing


def s6_cowl_crossings(side, root, wing):
    """Distances along the strut line from the root where it passes through the nacelle's outer skin, in and out."""
    num, _, x, front = next(n for n in NACELLES if n[1] == side)
    r, L = S6_ENGINE["od"] / 2, NACELLE_LEN
    centre = Vector((side * x, st(front), NACELLE_Z))
    ax, length = (wing - root).normalized(), (wing - root).length

    def outside(d):
        p = root + ax * d
        u = (p.y - centre.y) / L
        return math.hypot(p.x - centre.x, p.z - centre.z) - (r * uf_r(u) if 0 <= u <= 1 else 0.0)
    ds = [length * i / 400 for i in range(401)]
    out = []
    for a, b in zip(ds, ds[1:]):
        if (outside(a) > 0) != (outside(b) > 0):
            for _ in range(40):
                m = (a + b) / 2
                a, b = (m, b) if (outside(a) > 0) == (outside(m) > 0) else (a, m)
            out.append((a + b) / 2)
    return out


def strut_section(p, axis, chord, thick):
    """A strut section round p, its chord in the flow direction squared off against the member's axis."""
    cd = (Vector((0, 1, 0)) - axis * axis.y).normalized()
    td = axis.cross(cd).normalized()
    return airfoil(p - 0.4 * chord * cd, chord, thick, cd, td, n=STRUT_AF_N, te=0.01)


def build_struts_s6(parts, side):
    """The truss: one straight diagonal from the body's side to the wing's rear spar near the retracted tip, through
    the engine's axis. The nacelle is its node (owner: "the nacelle will be acting as what is transferring the
    force"): the line is split where it crosses the engine's semi-span, inside the core, into two collinear segments,
    the inner one jointed to the body part it roots on and the outer one to the wing, both braced to the nacelle,
    which carries the node's load to the wing through its pylon (the jury strut's job until step 5), to the core they
    pass through (the nozzle part), and to each other. A fairing collar rings the strut where it enters and leaves the
    cowl. Then the sponson that holds the main bogie."""
    sfx, num = ("_L", 1) if side > 0 else ("_R", 2)
    ch, th = S6_STRUT["chord"], S6_STRUT["thick"]
    root, hub, node = s6_strut_line(side)
    ax, length, d_hub = (node - root).normalized(), (node - root).length, (hub - root).length
    d_in, d_out = s6_cowl_crossings(side, root, node)
    seams = (0, STRUT_AF_N, 2 * STRUT_AF_N)
    flare = lambda d: 1 + 0.45 * max(0.0, 1 - d / 1.8) ** 2  # step 5's flare into the root fairing over 1.8 m
    sec = lambda d, k=1.0, kt=1.0: strut_section(root + ax * d, ax, ch * k, th * kt)

    def collar(bm, d):
        """A fairing collar round the strut where it passes through the cowl: wider and much thicker at the skin."""
        loft(bm, [sec(d + o, kc, kt) for o, kc, kt in COLLAR], seams=seams, soft=(STRUT_AF_N,))

    rings = [sec(-0.5, 1.45, 1.45)] + [sec(t * d_in, flare(t * d_in), flare(t * d_in))
                                        for t in (0.0, 0.06, 0.14, 0.3, 0.5, 0.75)]
    rings += [sec(d_hub - S6_STRUT_JOIN), sec(d_hub), sec(d_hub + 0.12)]
    bm = bmesh.new()
    loft(bm, rings, seams=seams, soft=(STRUT_AF_N,), cap_mat=(1, 1))  # buried in the body and in the outer segment
    collar(bm, d_in)
    # The root fairing spans the stations of its flared chord: braced to every body part beside the one it roots on.
    lo, hi = (f(q.y for r in rings[:3] for q in r) + Y0 for f in (min, max))
    body = [n for n, rs, _, _ in FUSELAGE if n != S6_STRUT_ROOT_PART and rs[0] < hi and rs[-1] > lo]
    add_part(parts, "strut_inner" + sfx, bm, root, S6_STRUT_ROOT_PART, mats=(SKIN, STRUCT), col=airframe(rings[:-2]),
             bonded_to=",".join([f"nacelle_{num}", f"nozzle_{num}", "strut_outer" + sfx] + body),
             line_root=list(root), line_node=list(hub))

    # Over its last 2 m the chord narrows to fit_chord, so the wing fitting stays ahead of the aileron. The line meets
    # the wing's lower skin at a shallow angle, so near the node it also thins: its top stays 6 cm under the skin
    # across its chord (the retracted stages sit 2 to 4 cm inside the skin there), at least 3 cm thick; the foot is
    # pressed flat onto the skin 4 mm deep.
    fit = lambda d: 1.0 - (1 - S6_STRUT["fit_chord"] / ch) * max(0.0, 1 - d / 2.0)  # chord factor d metres short of the node
    cd = (Vector((0, 1, 0)) - ax * ax.y).normalized()

    def thin(d):
        """Thickness factor d metres short of the node: twice the skin's least height over the line across the chord."""
        p = root + ax * (length - d)
        h = min(wing_lower(side, abs(q.x), q.y + Y0).z - q.z for q in (p - 0.4 * ch * fit(d) * cd, p, p + 0.6 * ch * fit(d) * cd))
        return min(1.0, max(0.03, 2 * (h - 0.06)) / th)
    rings = [sec(d_hub - 0.12), sec(d_hub), sec(d_hub + S6_STRUT_JOIN)]
    rings += [sec(d_hub + (length - d_hub) * t) for t in (0.25, 0.5, 0.75)]
    rings += [sec(length - d, fit(d), thin(d)) for d in (2.0, 1.5, 1.0, 0.7, 0.45, 0.2)]
    foot = sec(length, fit(0.0), 0.03 / th)
    rings.append([Vector((p.x, p.y, wing_lower(side, abs(p.x), p.y + Y0, inset=0.004).z)) for p in foot])
    bm = bmesh.new()
    loft(bm, rings, seams=seams, soft=(STRUT_AF_N,), cap_mat=(1, 1))
    collar(bm, d_out)
    # Its collider stops 0.7 m short of the node, ahead of the thinnest sections, and takes two more sections in each
    # step of the taper, where chord and thickness shrink at different rates and a two-section hull bows out of the skin.
    taper = rings[6:10]
    col = rings[2:6] + [[u.lerp(v, f / 3) for u, v in zip(a, b)] for a, b in zip(taper, taper[1:]) for f in range(3)] + [taper[-1]]
    add_part(parts, "strut_outer" + sfx, bm, node, "wing_root" + sfx, mats=(SKIN, STRUCT), col=airframe(col),
             bonded_to=f"nacelle_{num},nozzle_{num}", line_root=list(hub), line_node=list(node))
    build_sponson(parts, side)


def sponson_section_s6(s):
    """Round 4's pod (S6_SPONSON) at station s on the left side: (centre x, centre z, outboard and inboard half-widths,
    half-height), shrinking to its centre at either end; None past them."""
    p = S6_SPONSON
    u = (s - p["station"]) / p["half_len"]
    if abs(u) > 1 + 1e-9:  # the end stations come back through a subtraction
        return None
    f = (1 - min(abs(u), 1.0) ** 2.5) ** 0.5
    return FUS_HALF_W - p["inset"], p["cz"], p["half_w"] * f, p["half_w"] * f, p["half_h"] * f


def build_sponson(parts, side):
    """The pod that holds the main bogie: sponson_section lofted through SPONSON_RINGS' stations, between poles at
    the first and last."""
    sfx, ends = ("_L" if side > 0 else "_R"), (SPONSON_RINGS[0], SPONSON_RINGS[-1])
    rings = []
    for s in SPONSON_RINGS[1:-1]:
        cx, cz, a_out, a_in, b = sponson_section(s)
        rings.append([Vector((side * (cx + (a_out if sn > 0 else a_in) * sn), st(s), cz + b * cs))
                      for sn, cs in ((math.sin(2 * math.pi * i / 16), math.cos(2 * math.pi * i / 16)) for i in range(16))])
    poles = [Vector((side * sponson_section(s)[0], st(s), sponson_section(s)[1])) for s in ends]
    skin = rings if sponson_skin is None else [[Vector((side * q.x, st(s), q.y)) for q in sponson_skin(s)]
                                                 for s in SPONSON_RINGS[1:-1]]
    bm = bmesh.new()
    loft(bm, skin, *poles, seams=(8 if sponson_skin is None else len(skin[0]) - 3,))
    mid = sum(ends) / 2
    add_part(parts, "sponson" + sfx, bm, Vector((side * FUS_HALF_W, st(mid), sponson_section(mid)[1])), "fuselage_M",
             col=airframe(rings, *poles), bonded_to="fuselage_R")


def build_engines_s6(parts):
    """A blockout late-UltraFan a side (round 4's builder at 4.0 m): a big fan in a slim nacelle, a generator fairing
    with cooling scoops on the cowl's lower inboard side, variable-area fan nozzle petals, a third-stream exit ring
    stepping down the core cowl, and a stout core nozzle round a short plug. The pylon carries it under the wing as an
    airliner's does; the strut runs through the nacelle's lower part (build_struts_s6)."""
    e = S6_ENGINE
    r, L, seg = e["od"] / 2, e["cowl"], 48
    Y = Vector((0, 1, 0))
    outer = [(r * f, L * a) for f, a in S6_UF_OUTER]
    inner = [(r * f, L * a) for f, a in S6_UF_INNER]
    pl, cl, plug_len = e["petal_len"], e["core_len"], e["plug_len"]
    rt, rti = r * S6_UF_OUTER[-1][0], r * S6_UF_INNER[0][0]
    # The nozzle's collider: the petal ring as a solid, then the core cowl, core nozzle and plug behind it.
    petal_env = ((rt - 0.025, 0.0), (rt - 0.11, pl))
    core_env = ((0.54 * r, pl + 0.05), (0.555 * r, pl + 0.62), (0.47 * r, pl + 0.7), (0.47 * r, pl + cl),
                (0.3 * r, pl + cl + 0.1), (0.2 * r, pl + cl + 0.6 * plug_len))

    def oriented_box(bm, base, axes, size):
        pts = [base + axes[0] * (sx * size[0] / 2) + axes[1] * (sy * size[1] / 2) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        return loft(bm, [pts, [p + axes[2] * size[2] for p in pts]])

    for num, side, x, front in NACELLES:
        sfx = "_L" if side > 0 else "_R"
        c = Vector((side * x, st(front), NACELLE_Z))
        rad = lambda th: Vector((side * math.sin(math.radians(th)), 0, math.cos(math.radians(th))))
        ring = lambda centre, rr, a: [centre + Y * a + rad(360 * i / 32) * rr for i in range(32)]
        bm = bmesh.new()
        n_out = len(outer)
        faces = revolve(bm, outer + inner, c, seg=seg, loop=True, seams=(0, seg // 2),
                        ring_seams=(0, n_out - 1, n_out, len(outer + inner) - 1))
        for f in faces[n_out * seg:(n_out + 2) * seg]:  # the bypass duct behind the fan
            f.material_index = 1
        # Generator fairing on the lower inboard cowl: a long blister with two cooling scoops at its nose, ending ahead
        # of the strut's collar.
        th, w, h, u0, u1 = -135.0, 1.28, 0.31, 0.16, 0.62
        n_r = rad(th)
        t_r = Y.cross(n_r).normalized()
        bulge = lambda u: math.sin(math.pi * (u - u0) / (u1 - u0)) ** 0.6 if u0 < u < u1 else 0.0
        rings = []
        for u in (u0, u0 + 0.04, u0 + 0.12, u0 + 0.25, u0 + 0.37, u0 + 0.45, u1):
            base = c + Y * (L * u) + n_r * (r * uf_r(u) - 0.1)
            rings.append([base + t_r * (0.5 * w * max(bulge(u), 0.05) * math.cos(math.pi * i / 10))
                          + n_r * ((0.1 + h * bulge(u)) * math.sin(math.pi * i / 10)) for i in range(11)])
        loft(bm, rings, seams=(0, 10))  # cut at the arc's ends so its crown and flat base unwrap apart
        for dt in (-0.26, 0.26):
            p = c + Y * (L * (u0 + 0.08)) + n_r * (r * uf_r(u0 + 0.08) + h * bulge(u0 + 0.08) - 0.05) + t_r * dt
            for f in oriented_box(bm, p, (t_r, Y, n_r), (0.29, 0.47, 0.13)):
                f.material_index = 1
        add_part(parts, f"nacelle_{num}", bm, c, f"pylon_{num}", mats=(SKIN, MECH),
                 col=airframe([ring(c, rr, a) for rr, a in outer]))

        # Fan: a big spinner and wide-chord blades out to the fan case, 0.15 of the cowl behind the intake plane.
        fc = c + Y * (0.15 * L)
        bm = bmesh.new()
        revolve(bm, [(0, -0.36 * r), (0.18 * r, -0.248 * r), (0.26 * r, -0.08 * r), (0.29 * r, 0.1), (0.29 * r, 0.4), (0, 0.45)], fc, seg=24)
        for i in range(e["fan_blades"]):
            phi = 2 * math.pi * (i + 0.5) / e["fan_blades"]
            er, et = Vector((math.sin(phi), 0, math.cos(phi))), Vector((math.cos(phi), 0, -math.sin(phi)))
            rings = []
            for rr, beta, chord, tk in ((0.27, 58, 0.44, 0.07), (0.55, 42, 0.52, 0.05), (0.85, 28, 0.56, 0.035)):
                b = math.radians(beta)
                cd = et * math.cos(b) + Y * math.sin(b)
                nd = er.cross(cd).normalized()
                p = fc + er * (rr * r)
                rings.append([p + cd * (u * chord / 2) + nd * (q * tk / 2) for u, q in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
            loft(bm, rings)
        add_part(parts, f"fan_{num}", bm, fc, f"nacelle_{num}", mats=(MECH,), spin_axis=[0.0, 1.0, 0.0])

        # Nozzle: variable-area petals off the cowl's trailing edge, notched between petals, the core cowl with the
        # third-stream exit ring stepping it down, the core nozzle and the plug.
        rear = c + Y * L
        petals = [(rt - 0.025, 0.0), (rt - 0.11, pl), (rti - 0.07, pl), (rti - 0.01, 0.0)]

        def notch(pi, i, rr, a):
            return (rr, a - 0.25) if pi in (1, 2) and i % 6 == 0 else (rr, a)
        bm = bmesh.new()
        np_seg = 6 * e["petals"]
        revolve(bm, petals, rear, seg=np_seg, loop=True, shape=notch, seams=(0, np_seg // 2), ring_seams=(0, 1, 2, 3))
        core = [(0.0, -0.6 * L), (0.5 * r, -0.6 * L), (0.53 * r, 0.0), (0.54 * r, pl + 0.55), (0.555 * r, pl + 0.62),
                (0.49 * r, pl + 0.64), (0.47 * r, pl + cl), (0.4 * r, pl + cl + 0.02), (0.0, pl + cl + 0.02)]
        faces = revolve(bm, core, rear, seg=seg, seams=(0, seg // 2), ring_seams=(2, 4))
        for f in faces[3 * seg:4 * seg] + faces[5 * seg:]:  # the third-stream exit face and the core nozzle
            f.material_index = 1
        plug = [(0.0, pl + cl - 0.4), (0.3 * r, pl + cl - 0.4), (0.3 * r, pl + cl + 0.1),
                (0.2 * r, pl + cl + 0.6 * plug_len), (0.0, pl + cl + plug_len)]
        for f in revolve(bm, plug, rear, seg=seg // 2):
            f.material_index = 1
        add_part(parts, f"nozzle_{num}", bm, rear, f"nacelle_{num}", mats=(SKIN, MECH),
                 col=airframe([ring(rear, rr, a) for rr, a in petal_env])
                 + airframe([ring(rear, rr, a) for rr, a in core_env], "cap", rear + Y * (pl + cl + plug_len)))

        # Pylon: from the cowl's crown into the wing's leading edge and underside, then an aft fairing over the core
        # cowl that closes up under the wing ahead of the trailing edge. It carries the strut node (inside the nacelle)
        # on the wing, so the strut braces against it.
        le, ch, _ = wing_le(side, x)
        le_st = le.y + Y0
        sp = le_st + 4.4  # the aft fairing's middle, over the core cowl behind the fan nozzle petals
        crown = lambda s: NACELLE_Z + r * uf_r((s - front) / L) - 0.12
        core_top = NACELLE_Z + 0.53 * r - 0.05
        # Into the wing's underside: 15 cm where the wing is deep, 6 cm over its thin aft quarter.
        under = lambda s, depth=0.15: wing_lower(side, x, s).z + depth

        def pring(s, bot, top, half):
            mid = bot + 0.4 * (top - bot)
            return [Vector((side * x + dx * half, st(s), z)) for dx, z in
                    ((-0.7, bot), (0.7, bot), (1.0, mid), (0.75, top), (-0.75, top), (-1.0, mid))]
        s_nose, s_le, s_cowl = le_st - 1.9, le_st - 0.8, front + L - 0.25
        rings = [pring(s_nose, crown(s_nose), crown(s_nose) + 0.12, 0.12),
                 pring(s_le, crown(s_le), max(le.z - 0.25, crown(s_le) + 0.3), 0.30),
                 pring(le_st - 0.2, crown(le_st - 0.2), max(le.z - 0.12, crown(le_st - 0.2) + 0.3), 0.32),
                 pring(le_st + 0.4, crown(le_st + 0.4), under(le_st + 0.4), 0.34),
                 pring(s_cowl, crown(s_cowl), under(s_cowl), 0.36),
                 pring(sp - 0.55, core_top, under(sp - 0.55, 0.06), 0.36),
                 pring(sp + 0.55, core_top, under(sp + 0.55, 0.06), 0.36),
                 pring(sp + 0.8, core_top + 0.25, under(sp + 0.8, 0.06), 0.28),
                 pring(sp + 0.95, under(sp + 0.95, 0.06) - 0.35, under(sp + 0.95, 0.06), 0.16)]
        # Three rings between each pair: the sections twist between rings, and the shorter spans keep each collider
        # hull within the 2 cm inset.
        rings = [[u.lerp(v, f / 4) for u, v in zip(a, b)] for a, b in zip(rings, rings[1:]) for f in range(4)] + [rings[-1]]
        if LONG_STAGES:
            # The long stages pass over it inside the wing: its top follows the underside 10 cm deep, where the straight
            # runs between rings cut up to 24 cm into the curved skin. Each top stays level and the sides' kink stays at
            # 0.4 of the height (pring), so the sections don't warp and its collider hulls stay inset.
            for ring in rings:
                z = min(min(p.z, wing_lower(side, abs(p.x), p.y + Y0).z + 0.10) for p in ring[3:5])
                for i in (3, 4):
                    ring[i].z = z
                for i in (2, 5):
                    ring[i].z = ring[0].z + 0.4 * (z - ring[0].z)
        bm = bmesh.new()
        loft(bm, rings, seams=(0, 1, 3, 4))
        attach = wing_lower(side, x, le_st + 0.25 * ch)
        add_part(parts, f"pylon_{num}", bm, Vector((side * x, attach.y, attach.z)), "wing_root" + sfx,
                 col=airframe(rings), bonded_to=f"nozzle_{num}")


def vtail_planform(d):
    """The V-tail panel d metres along its span: its leading edge's station and its chord. With VTAIL_TIP_ROUND (step
    6.1) the last VTAIL_TIP_ROUND[0] metres close elliptically about VTAIL_TIP_ROUND[1] of the chord from the leading
    edge, both edges curving in to meet at the tip: no corner in plan or section."""
    chord = VTAIL_ROOT_CHORD + (VTAIL_TIP_CHORD - VTAIL_ROOT_CHORD) * d / VTAIL_SPAN
    le = VTAIL_ROOT_STATION + d * math.tan(VTAIL_SWEEP)
    if VTAIL_TIP_ROUND is not None and d > VTAIL_SPAN - VTAIL_TIP_ROUND[0]:
        g = (d - VTAIL_SPAN + VTAIL_TIP_ROUND[0]) / VTAIL_TIP_ROUND[0]
        e = math.sqrt(max(0.0, 1 - g * g))
        le, chord = le + (1 - e) * VTAIL_TIP_ROUND[1] * chord, chord * e
    return le, chord


def vtail_section_s6(side, d, cut=None, t0=None):
    """step 5's vtail_section with the root line low on the aft body's side (VTAIL_ROOT_X), as round 4 rooted it."""
    span_dir = Vector((side * math.cos(VTAIL_DIHEDRAL), 0, math.sin(VTAIL_DIHEDRAL)))
    normal = Vector((-side * math.sin(VTAIL_DIHEDRAL), 0, math.cos(VTAIL_DIHEDRAL)))
    root_le = Vector((side * VTAIL_ROOT_X, st(VTAIL_ROOT_STATION), VTAIL_ROOT_Z))
    f = d / VTAIL_SPAN
    le_station, chord = vtail_planform(d)
    le = root_le + span_dir * d + Vector((0, le_station - VTAIL_ROOT_STATION, 0))
    thick = chord * (0.10 - 0.03 * max(f, 0))
    if t0 is not None:
        return airfoil_aft(le, chord, thick, Vector((0, 1, 0)), normal, 0.0, t0), camber_point(le, chord, Vector((0, 1, 0)), normal, 0.0, t0)
    return airfoil(le, chord, thick, Vector((0, 1, 0)), normal, cut=cut), root_le


def ruddervator_root_s6():
    """The ruddervator's root end along the panel: where its whole chord stands 0.25 m off the aft body's skin."""
    dih, d = VTAIL_DIHEDRAL, 0.0
    while d < VTAIL_SPAN / 2:
        x, z = VTAIL_ROOT_X + d * math.cos(dih), VTAIL_ROOT_Z + d * math.sin(dih)
        chord = VTAIL_ROOT_CHORD + (VTAIL_TIP_CHORD - VTAIL_ROOT_CHORD) * d / VTAIL_SPAN
        s_le = VTAIL_ROOT_STATION + d * math.tan(VTAIL_SWEEP)
        if all(x - side_x_s6(s_le + chord * (RUDDERVATOR_HINGE + (1 - RUDDERVATOR_HINGE) * i / 5), z) >= 0.25 for i in range(6)):
            return round(d, 2)
        d += 0.05
    raise SystemExit("no ruddervator root clear of the aft body")


def vtail_hinge_fraction(d, t):
    """The local chord fraction at d of the straight line at chord fraction t of the panel's unrounded planform: the
    hinge line stays straight where the rounded tip draws both edges in, so it runs further back in the local chord."""
    le, chord = vtail_planform(d)
    chord0 = VTAIL_ROOT_CHORD + (VTAIL_TIP_CHORD - VTAIL_ROOT_CHORD) * d / VTAIL_SPAN
    return (VTAIL_ROOT_STATION + d * math.tan(VTAIL_SWEEP) + t * chord0 - le) / chord


def vtail_hinge_point(side, d):
    """The ruddervators' hinge line on the panel at d: the chord line at the surfaces' front face (build_vtail_s6's t0)."""
    t0 = RUDDERVATOR_HINGE + 0.02 / VTAIL_TIP_CHORD
    return vtail_section(side, d, t0=vtail_hinge_fraction(d, t0))[1]


def split_root_s6(clear, throw):
    """The split tail's root end along the panel, to 5 cm: the first d where the inboard surface's section, turned
    `throw` degrees either way about the hinge line, stands `clear` metres outside the aft body's skin at every point."""
    side, dih = 1, VTAIL_DIHEDRAL
    axis = (vtail_hinge_point(side, VTAIL_SPAN / 2) - vtail_hinge_point(side, 0.0)).normalized()
    t0 = RUDDERVATOR_HINGE + 0.02 / VTAIL_TIP_CHORD
    d = 0.0
    while d < VTAIL_SPAN / 2:
        ring = vtail_section(side, d, t0=vtail_hinge_fraction(d, t0))[0]
        hc = vtail_hinge_point(side, d)
        turned = [hc + Matrix.Rotation(math.radians(a), 3, axis) @ (p - hc) for a in (-throw, 0.0, throw) for p in ring]
        if all(p.x - side_x_s6(p.y + Y0, p.z) >= clear for p in turned):
            return round(d, 2)
        d += 0.05
    raise SystemExit("no split-tail root clear of the aft body")


def ruddervator_spans(sfx):
    """(name, (d0, d1)) of each moving surface on one V-tail panel, d along it from its root leading edge: the single
    ruddervator, or with SPLIT_TAIL the inboard surface 1 and the outboard surface 2 either side of its split."""
    d0, d1 = RUDDERVATOR_SPAN
    if SPLIT_TAIL is None:
        return [("ruddervator" + sfx, (d0, d1))]
    s, g = SPLIT_TAIL["split"], SPLIT_TAIL["gap"] / 2
    return [(f"ruddervator{sfx}1", (d0, s - g)), (f"ruddervator{sfx}2", (s + g, d1))]


def build_vtail_s6(parts, side):
    """Round 4's V-tail panels (vtail_panels: span stations scaled to the panel), braced to fuselage_R, which holds the
    root's forward end."""
    sfx, (d0, d1), span, gap = ("_L" if side > 0 else "_R"), RUDDERVATOR_SPAN, VTAIL_SPAN, SURF_GAP
    ends = {span}
    if VTAIL_TIP_ROUND is not None:  # the rounded tip's sections, closing on a pole at the tip
        L = VTAIL_TIP_ROUND[0]
        ends = {span - L * (1 - u) for u in (0.0, 0.3, 0.55, 0.72, 0.85, 0.93, 0.98)}
    ds = sorted({-S6_VTAIL["root_buried"], 0.0, 0.45 * span, 0.8 * span, d0 - gap - 0.01, d0 - gap, d1 + gap,
                 d1 + gap + 0.01} | ends)
    rings = [vtail_section(side, d, vtail_hinge_fraction(d, RUDDERVATOR_HINGE) if d0 - gap - 1e-6 <= d <= d1 + gap + 1e-6
                           else None)[0] for d in ds]
    root_le = vtail_section(side, 0.0)[1]
    tip = "cap"
    if VTAIL_TIP_ROUND is not None:
        span_dir = Vector((side * math.cos(VTAIL_DIHEDRAL), 0, math.sin(VTAIL_DIHEDRAL)))
        tip = root_le + span_dir * span + Vector((0, vtail_planform(span)[0] - VTAIL_ROOT_STATION, 0))
    bm = bmesh.new()
    loft(bm, rings, "cap", tip, seams=AF_SEAMS, soft=(AF_N,), cap_mat=(1, None))  # the root end is buried in the aft body
    # The collider takes two more sections in each span over 0.5 m: the panel tapers and sweeps between its rings, so
    # a long span's hull bows past the 2 cm inset. It is lofted in three runs, split at the ruddervator cut-out's
    # ends: a 1 cm wall from a full section to a cut one makes the inside test misread points beside it.
    col = []
    for lo, hi in ((ds[0], d0 - gap - 0.01), (d0 - gap, d1 + gap), (d1 + gap + 0.01, ds[-1])):
        idx = [i for i, d in enumerate(ds) if lo - 1e-6 <= d <= hi + 1e-6]
        run = [[u.lerp(v, f / 3) for u, v in zip(rings[i], rings[i + 1])] for i in idx[:-1]
               for f in (range(3) if ds[i + 1] - ds[i] > 0.5 else (0,))] + [rings[idx[-1]]]
        col += airframe(run)
    add_part(parts, "vtail" + sfx, bm, root_le + Vector((0, 0.25 * VTAIL_ROOT_CHORD, 0)), "tailcone",
             mats=(SKIN, STRUCT), col=col, bonded_to="fuselage_R")
    t0 = RUDDERVATOR_HINGE + 0.02 / VTAIL_TIP_CHORD
    axis = vtail_hinge_point(side, d1) - vtail_hinge_point(side, d0)  # one straight line for every surface on the panel
    for name, (a, b) in ruddervator_spans(sfx):
        secs = [vtail_section(side, d, t0=vtail_hinge_fraction(d, t0)) for d in sorted({a, (a + b) / 2, b} | {e for e in ends if a < e < b})]
        bm = bmesh.new()
        loft(bm, [r for r, _ in secs], seams=AFT_SEAMS)
        add_hinged(parts, name, bm, secs[0][1], "vtail" + sfx, axis,
                   up=Vector((-side * math.sin(VTAIL_DIHEDRAL), 0, math.cos(VTAIL_DIHEDRAL))))


def build_tail_systems_s6(parts):
    """Step 5's laser turret and tail radar on the step 6 tail cone."""
    _, top, bot = fus_profile(TAIL_END[-1][0])
    zc = (top + bot) / 2
    ball = Vector((0, st(44.3), zc))
    bm = bmesh.new()
    sphere(bm, ball, 0.44, seams=(8,))
    add_part(parts, "laser_turret", bm, ball, "tailcone")
    bm = bmesh.new()
    cylinder(bm, ball, Vector((0, st(S6_LENGTH), zc)), 0.06, seg=8)
    add_part(parts, "laser_barrel", bm, ball, "laser_turret", mats=(MECH,))
    bm = bmesh.new()
    # Narrower round the keel than step 5's 118 to 242 deg, clear of the V-tail roots' trailing edges.
    skin_panel(bm, (40.9, 41.6, 42.3, 43.0, 43.5), 140, 220, -0.01, PANEL_PROUD.get("radar_R", 0.035), n_a=8, inner_mat=1)
    add_part(parts, "radar_R_fairing", bm, fus_point(42.2, 180), "tailcone", mats=(SKIN, STRUCT))


def build_spine_cover(parts):
    """The bomber's lid over the AWACS spine well (docs/M3-DESIGN.md "Blockout measurements": a 10.10 x 0.86 m slot
    0.30 m behind the wing box): a skin panel 3 cm past the slot all round. It carries no load and its mass is
    fuselage_R's; the AWACS loadout hides it, and its mount fills the slot."""
    s0, s1 = S6_WELL_START - 0.03, S6_WELL_START + S6_WELL["length"] + 0.03
    a = math.degrees(math.asin((S6_WELL["width"] / 2 + 0.03) / FUS_HALF_W))
    bm = bmesh.new()
    skin_panel(bm, [s0 + (s1 - s0) * i / 6 for i in range(7)], -a, a, 0.006, PANEL_PROUD.get("spine", 0.045), n_a=4, inner_mat=1)
    add_part(parts, "spine_cover", bm, fus_point((s0 + s1) / 2, 0.0), "fuselage_R", mats=(SKIN, STRUCT))


def deg_at_x(s, x):
    """The upper-side angle where the skin at station s reaches half width |x| (the chine ignored)."""
    w = fus_profile(s)[0]
    return math.copysign(math.degrees(math.asin(min(1.0, abs(x) / w) ** (FUS_P / 2))), x)


def deg_at_z(s, z):
    """The +X side angle where the skin at station s reaches height z (the chine ignored)."""
    _, top, bot = fus_profile(s)
    c = max(-1.0, min(1.0, (z - (top + bot) / 2) / ((top - bot) / 2)))
    return math.degrees(math.acos(math.copysign(abs(c) ** (FUS_P / 2), c)))


def build_flightdeck_exits(parts):
    """Step 6.1: the flight deck's escape hatch over each seat and its crew door (docs/COCKPIT-DESIGN.md), each a part
    of its own so the game can blow it off or swing it: nose_hatch_L and nose_hatch_R, and the door on its hinge
    (nose_door, local X up its forward edge) with nose_door_visible under it. Panels lie on the skin with their inner
    face at the opening's depth. They carry no load and no mass of their own (the nose's). m4/nose_exits.py cuts the
    openings and builds the finished, rounded panels on these parts.

    The door wraps 56 deg round the nose's side, so its forward edge bows out 25 cm from the chord between its ends:
    turned about that chord, the bow would swing into the skin ahead of the door. The hinge runs parallel to the chord
    DOOR_HINGE_OUT outboard of the edge's outermost point, so every point of the edge swings aft into the doorway."""
    (s0, s1), (x0, x1) = fl.HATCH_S, fl.HATCH_X
    sm = (s0 + s1) / 2
    for sfx, side in (("L", 1), ("R", -1)):
        bm = bmesh.new()
        a0, a1 = sorted((deg_at_x(sm, side * x0), deg_at_x(sm, side * x1)))
        skin_panel(bm, [s0 + (s1 - s0) * i / 4 for i in range(5)], a0, a1, -fl.HATCH_DEPTH, 0.004, n_a=4, inner_mat=1)
        add_part(parts, f"nose_hatch_{sfx}", bm, fus_point(sm, (a0 + a1) / 2), "nose", mats=(SKIN, STRUCT))
    d0, d1, z0, z1 = fl.CREW_DOOR
    bm = bmesh.new()
    dm = (d0 + d1) / 2
    skin_panel(bm, [d0 + (d1 - d0) * i / 4 for i in range(5)], deg_at_z(dm, z1), deg_at_z(dm, z0), -fl.DOOR_THICK, 0.004,
               n_a=4, inner_mat=1)
    s = d0 + fl.DOOR_GAP
    edge = [fus_point(s, deg_at_z(s, z0 + fl.DOOR_CORNER + (z1 - z0 - 2 * fl.DOOR_CORNER) * i / 12)) for i in range(13)]
    lo, hi = edge[0], edge[-1]
    axis = (hi - lo).normalized()
    out = Vector((axis.z, 0.0, -axis.x)).normalized()  # across the chord in the station's plane, outboard (+X)
    if out.x < 0:
        out = -out
    lo = lo + out * (max((p - lo).dot(out) for p in edge) + DOOR_HINGE_OUT)
    add_hinged(parts, "nose_door", bm, lo, "nose", axis, mats=(SKIN, STRUCT), up=Vector((1, 0, 0)))


DOOR_HINGE_OUT = 0.04  # the crew door's hinge stands this far outboard of its forward edge (and the chine's crease)


WELL_SKINS = ("fuselage_M", "fuselage_R", "tailcone")  # the crown skins the well's slot runs through
WELL_CLEAR = 0.10  # M3's AwacsEnvelopeCheck gap: other parts' colliders stand this far back from well_box(WELL_CLEAR)


def well_box(margin=0.0):
    """The AWACS spine well as world (lo, hi) corners, grown by margin on every side but the top, which is 8 m, over any
    crown: S6_WELL["length"] from S6_WELL_START, S6_WELL["width"] across, S6_WELL["depth"] down from the crown."""
    s0, s1 = S6_WELL_START, S6_WELL_START + S6_WELL["length"]
    floor = min(fus_profile(s)[1] for s in (s0, (s0 + s1) / 2, s1)) - S6_WELL["depth"]
    w = S6_WELL["width"] / 2 + margin
    return Vector((-w, st(s0 - margin), floor - margin)), Vector((w, st(s1 + margin), 8.0))


def box_corners(lo, hi):
    return np.array([[x, y, z] for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)])


def cut_well_slot(objs, struct):
    """Step 6.1: the well's slot through the crown skins (WELL_SKINS), as a pocket down to the well's floor whose walls
    and floor take aircraft_structure. The bomber's spine_cover closes it; the beam mount's liner lines it."""
    cut_box(objs, WELL_SKINS, *well_box(), struct, "well")


def cut_box(objs, names, lo, hi, struct, label):
    """The box (lo, hi) cut out of each named part by an exact boolean, its walls taking aircraft_structure."""
    bm = bmesh.new()
    box(bm, (lo + hi) / 2, hi - lo)
    orient_outward(bm)
    me = bpy.data.meshes.new(label + "_cutter")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(struct)
    cutter = bpy.data.objects.new(label + "_cutter", me)
    scene.collection.objects.link(cutter)
    for name in names:
        o = objs[name]
        mod = o.modifiers.new(label, "BOOLEAN")
        mod.operation, mod.object, mod.solver, mod.material_mode = "DIFFERENCE", cutter, "EXACT", "TRANSFER"
        with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
            bpy.ops.object.modifier_apply(modifier=mod.name)
    remove_objects([cutter])
    bpy.context.view_layer.update()


# Step 6.1 sets it: the aft bay is a cavity, the box between its doors' hinge lines (BAY_HINGE_DEG) up to this roof
# over the doors' stations, cut through AFT_BAY_SKINS, whose colliders stand COL_INSET back from it as from the skin
# (clear_of_aft_bay). The forward bay stays the solid body under its doors; only the detail pass hollows it.
AFT_BAY_ROOF = None
AFT_BAY_SKINS = ("fuselage_M", "fuselage_R")


def aft_bay_box(margin=0.0):
    """The aft bay's cavity as world (lo, hi) corners, grown by margin on every side but the bottom, which is the
    ground: the doors' stations (build_baydoors, 0.4 m inside the bay's) between their hinge lines, up to AFT_BAY_ROOF."""
    _, s0, s1, _ = BAYS[-1]
    a, b = s0 + 0.4, s1 - 0.4
    x = min(fus_point(s, BAY_HINGE_DEG).x for s in (a, (a + b) / 2, b)) + margin
    return Vector((-x, st(a - margin), 0.0)), Vector((x, st(b + margin), AFT_BAY_ROOF + margin))


def clear_of_aft_bay(piece, tree):
    """Step 6.1: a collider piece reaching into aft_bay_box(COL_INSET) splits into convex pieces round it: the whole
    section ahead of it and behind it, and over its stations the part above its roof and either side of its walls.
    A piece already clear comes back alone. tree is the piece's skin envelope, for its depths as collider_piece
    measures them."""
    lo, hi = aft_bay_box(COL_INSET)
    v, t = piece["verts"], piece["tris"]
    if box_gap((Vector(v.min(0)), Vector(v.max(0))), (lo, hi)) > 0.0:
        return [piece]
    X, Y, Z = np.eye(3)
    over = [(Y, hi.y), (-Y, -lo.y)]  # (n, d): keep n.x <= d
    regions = {"ahead": [(Y, lo.y)], "behind": [(-Y, -hi.y)], "roof": over + [(-Z, -hi.z)],
               "left": over + [(Z, hi.z), (-X, -hi.x)], "right": over + [(Z, hi.z), (X, lo.x)]}
    return clip_regions(piece, tree, regions, "aft_bay_clip")


# Step 6.1 sets it: the nose's collider opens over the flight deck's escape hatches (clear_of_hatches).
NOSE_EXITS = False


def clear_of_hatches(piece, tree):
    """Step 6.1: the nose's collider piece split into convex pieces that leave each escape hatch's path open above
    fl.NOTCH_Z (docs/COCKPIT-DESIGN.md "Collider notch"): the whole piece below it, and above it the parts ahead of and
    behind the hatches, a centre spine between them and a cap outboard of each."""
    X, Y, Z = np.eye(3)
    (s0, s1), (x0, x1), z = fl.NOTCH_S, fl.NOTCH_X, fl.NOTCH_Z
    up, over = [(-Z, -z)], [(-Y, -st(s0)), (Y, st(s1))]  # (n, d): keep n.x <= d
    regions = {"below": [(Z, z)], "ahead": up + [(Y, st(s0))], "behind": up + [(-Y, -st(s1))],
               "spine": up + over + [(X, x0), (-X, x0)], "left": up + over + [(-X, -x1)], "right": up + over + [(X, -x1)]}
    return clip_regions(piece, tree, regions, "hatch_clip")


def clip_regions(piece, tree, regions, label):
    """A collider piece cut into one convex piece per region, each region a list of planes (n, d) keeping n.x <= d;
    a region the piece doesn't reach, or reaches with under 0.01 m3, is dropped. tree is the piece's skin envelope, for
    the depths as collider_piece measures them; each piece records its region under label."""
    v, t = piece["verts"], piece["tris"]
    whole = convex.volume(v, t)
    out = []
    for region, planes in regions.items():
        hull = (v, t)
        for n, d in planes:
            hull = clip_hull(*hull, n, d) if hull is not None else None
        if hull is None or convex.volume(*hull) < 0.01:
            continue
        cv, ct = hull
        if len(cv) > COL_MAX_VERTS:
            cv, ct = convex.hull_mesh(convex.simplify_hull(cv, COL_MAX_VERTS))
        tri = cv[ct]
        samples = np.concatenate([cv, tri.mean(1), ((tri + tri[:, [1, 2, 0]]) / 2).reshape(-1, 3)])
        depth = [signed_depth(tree, Vector(s)) for s in samples]
        out.append({"verts": cv, "tris": ct, "min_depth": min(depth),
                    "vertex_depth": (min(depth[:len(cv)]), max(depth[:len(cv)])),
                    label: {"region": region, "volume_m3": round(convex.volume(cv, ct), 3), "of_piece_m3": round(whole, 3)}})
    return out


def aft_bay_report(objs):
    """The aft bay as built: its doors and hardpoint (CenturionAuthor.BuildBays: the doors' middle, 0.4 m under the
    root); rays up through its opening (the doors aside) meeting nothing under its roof; AFT_BAY_SKINS' colliders
    COL_INSET or more from the cavity, with the centre of each part's hull bounds (where ConfigurePart puts its CoM)
    and its hulls' volume."""
    lo, hi = aft_bay_box()
    door = objs["baydoor_AL"].matrix_world.translation
    verts, polys = [], []  # the boolean leaves concave n-gons, which only FromPolygons' own fill triangulates right
    for n, o in objs.items():
        if o.type == "MESH" and not n.startswith("baydoor_A"):
            v, p = world_mesh(o)
            polys += [tuple(i + len(verts) for i in q) for q in p]
            verts += v
    tree = BVHTree.FromPolygons(verts, polys)
    hits = [tree.ray_cast(Vector((lo.x + 0.05 + (hi.x - lo.x - 0.1) * j / 8, lo.y + 0.05 + (hi.y - lo.y - 0.1) * i / 40,
                                  0.5)), Vector((0, 0, 1)))[0] for i in range(41) for j in range(9)]
    lowest = min((h.z for h in hits if h is not None), default=math.inf)
    box_hull = convex.hull_mesh(box_corners(lo, hi))
    gaps, hulls = {}, {}
    for c in bpy.data.collections["Colliders"].objects:
        if c.parent.name in AFT_BAY_SKINS:
            v, t = world_hull(c)
            gaps[c.name] = round(convex.hull_gap((v, t), box_hull), 3)
            hulls.setdefault(c.parent.name, []).append((v, t))
    parts = {}
    for owner, hs in sorted(hulls.items()):
        allv = np.vstack([v for v, _ in hs])
        c = (allv.min(0) + allv.max(0)) / 2
        parts[owner] = {"pieces": len(hs), "collider_m3": round(sum(convex.volume(v, t) for v, t in hs), 2),
                        "collider_bounds_centre": [round(c[0], 3), round(c[1] + Y0, 3), round(c[2], 3)]}
    near = min(gaps, key=gaps.get)
    return {"door_stations": [round(lo.y + Y0, 2), round(hi.y + Y0, 2)], "hinge_half_width_m": round(hi.x, 3),
            "roof_m": AFT_BAY_ROOF, "hardpoint": [0.0, round(door.y + Y0, 3),
                                                  round(objs["fuselage_M"].matrix_world.translation.z - 0.4, 3)],
            "lowest_hit_up_through_opening_m": round(lowest, 3), "collider_gaps_m": gaps, "nearest": [near, gaps[near]],
            "limit_m": COL_INSET, "parts": parts,
            "pass": lowest >= AFT_BAY_ROOF - 1e-3 and gaps[near] >= COL_INSET - 1e-3}


def clip_hull(v, t, n, d):
    """The convex hull (v, t) cut by the plane n.x = d, keeping n.x <= d: its vertices on that side and where its edges
    cross the plane. None when nothing is left."""
    side = v @ n - d
    e = convex.hull_edges(t)
    a, b = side[e[:, 0]], side[e[:, 1]]
    cross = (a < 0) & (b > 0) | (a > 0) & (b < 0)
    p, q = v[e[cross, 0]], v[e[cross, 1]]
    pts = np.vstack([v[side <= 0], p + (q - p) * (a[cross] / (a[cross] - b[cross]))[:, None]])
    return convex.hull_mesh(convex.merge_close(pts, 1e-4)) if len(pts) >= 4 else None


def clear_of_well(piece, tree):
    """Step 6.1: a collider piece within WELL_CLEAR of well_box(WELL_CLEAR) loses its corner there to one plane, which
    keeps it convex: of the planes across the body that stand WELL_CLEAR back from that box, tilted 0 to 90 deg from
    level and leaning away from the well, the one that keeps the most of the piece. A piece already clear comes back
    as it is. tree is the piece's skin envelope, for its depths as collider_piece measures them."""
    lo, hi = well_box(WELL_CLEAR)
    corners = box_corners(lo, hi)
    box_hull = convex.hull_mesh(corners)
    v, t = piece["verts"], piece["tris"]
    if box_gap((Vector(v.min(0)), Vector(v.max(0))), (lo, hi)) > WELL_CLEAR or convex.hull_gap((v, t), box_hull) >= WELL_CLEAR:
        return piece
    ahead = v[:, 1].mean() < (lo.y + hi.y) / 2  # fuselage_M's piece ends at the well's front, the tail cone's at its back
    best = None
    for deg in range(91):
        a = math.radians(deg)
        n = np.array([0.0, math.sin(a) if ahead else -math.sin(a), math.cos(a)])
        hull = clip_hull(v, t, n, (corners @ n).min() - WELL_CLEAR)
        if hull is not None and (best is None or convex.volume(*hull) > best[0]):
            best = (convex.volume(*hull), deg, hull)
    if best is None:
        raise SystemExit(f"a collider piece at station {v[:, 1].mean() + Y0:.2f} lies inside the AWACS well's clearance")
    cv, ct = best[2]
    if len(cv) > COL_MAX_VERTS:
        cv, ct = convex.hull_mesh(convex.simplify_hull(cv, COL_MAX_VERTS))
    tri = cv[ct]
    samples = np.concatenate([cv, tri.mean(1), ((tri + tri[:, [1, 2, 0]]) / 2).reshape(-1, 3)])
    depth = [signed_depth(tree, Vector(s)) for s in samples]
    return {"verts": cv, "tris": ct, "min_depth": min(depth), "vertex_depth": (min(depth[:len(cv)]), max(depth[:len(cv)])),
            "well_clip": {"plane_deg_from_level": best[1], "volume_kept": round(convex.volume(cv, ct) / convex.volume(v, t), 3),
                          "gap_to_clearance_box_m": round(convex.hull_gap((cv, ct), box_hull), 3)}}


def build_geardoors_s6(parts):
    """Step 5's nose doors, reaching down to NOSE_DOOR_BOTTOM under the lower belly; the main doors run along each
    sponson's inboard underside beside the bogie."""
    for sfx, side in (("L", 1), ("R", -1)):
        x = side * 0.72
        bm = bmesh.new()
        door_plate(bm, x, (3.95, 5.4, 6.85), lambda s: fus_bottom_z(s, x) + 0.04, NOSE_DOOR_BOTTOM, inner=-side)
        # The hinge follows the belly, which climbs about 6.6 deg over the door; a level axis left a wedge of sky over
        # the open door's forward end (art review round 1). m4/nose.gear_door swings the art about the same line.
        hinge = Vector((x, st(3.98), fus_bottom_z(3.98, x)))
        hinge_end = Vector((x, st(6.82), fus_bottom_z(6.82, x)))
        add_hinged(parts, f"geardoor_F{sfx}", bm, hinge, "nose", (hinge_end - hinge).normalized(),
                   mats=(SKIN, STRUCT))

        xd = side * (sponson_section(MAIN_GEAR_STATION)[0] - 0.55)

        def pod_z(s):
            cx, cz, a_out, a_in, b = sponson_section(s)
            d = abs(xd) - cx
            sn = min(abs(d) / (a_out if d > 0 else a_in), 1.0)
            return cz - b * math.sqrt(1 - sn * sn) + 0.05

        bm = bmesh.new()
        door_plate(bm, xd, [MAIN_GEAR_STATION + d for d in (-2.4, -1.2, 0.0, 1.2, 2.4)], pod_z, 0.75, inner=side)
        hinge = Vector((xd, st(MAIN_GEAR_STATION), pod_z(MAIN_GEAR_STATION) - 0.05))
        add_hinged(parts, f"geardoor_{sfx}M", bm, hinge, "sponson_" + sfx, Vector((0, 1, 0)), mats=(SKIN, STRUCT))


def lod1_table_s6():
    t = {"radar_F_fairing": (12, ()), "nose": (17, ()), "fuselage_F": (17, ()), "fuselage_M": (17, ("wingfairing",)),
         "fuselage_R": (17, ("spine_cover",)), "tailcone": (17, ("radar_R_fairing",)),
         "laser_turret": (9, ("laser_barrel",)), "gear_F": (12, ("wheel_F",))}
    for s in "LR":
        t.update({f"wing_root_{s}": (17, (f"flap_{s}1_visible", f"flap_{s}2_visible", f"aileron_{s}_visible")),
                  f"wing_tele1_{s}": (17, ()), f"wing_tele2_{s}": (17, ()), f"strut_inner_{s}": (12, ()),
                  f"strut_outer_{s}": (12, ()), f"sponson_{s}": (17, ()),
                  f"vtail_{s}": (17, (f"ruddervator_{s}_visible",)), f"gear_{s}M": (17, (f"wheel_{s}M",))})
    for n in (1, 2):
        t.update({f"nacelle_{n}": (17, (f"nozzle_{n}",)), f"pylon_{n}": (12, ())})
    return t


# ---------- step 6 measurements ----------
def s6_mass_rows(objs, masses):
    """(name, kg, bounds centre) as ConfigurePart places each AeroPart's CoM: a hinged surface's is its _visible mesh's,
    the cockpit's the nose's."""
    rows = []
    for name, kg in masses.items():
        o = objs["nose" if name == "cockpit" else name]
        if o.type == "EMPTY":
            o = objs[name + "_visible"]
        lo, hi = bounds(world_mesh(o)[0])
        rows.append((name, kg, (lo + hi) / 2))
    return rows


def s6_cg(objs, masses):
    rows = s6_mass_rows(objs, masses)
    m = sum(kg for _, kg, _ in rows)
    c = sum((kg * p for _, kg, p in rows), Vector()) / m
    return m, Vector((c.x, c.y + Y0, c.z))  # (kg, (x, station, height))


def s6_masses(objs):
    """S6_MASS and the control surfaces, with systems mass moved from the tail cone to the nose (or back) so the
    retracted empty CG sits at S6_CG_TARGET. Writes mass_kg on each part (a surface's on its hinge empty)."""
    masses = dict(S6_MASS)
    masses.update({n: S6_SURFACE_MASS for n, o in objs.items() if o.type == "EMPTY" and n.startswith(CONTROL_SURFACES)})
    for s in ("_L", "_R"):  # the split tail's surfaces share the single ruddervator's mass by span
        spans = ruddervator_spans(s)
        whole = sum(b - a for _, (a, b) in spans)
        masses.update({n: S6_SURFACE_MASS * (b - a) / whole for n, (a, b) in spans})
    set_extension(objs, 0.0)
    m, before = s6_cg(objs, masses)
    centre = {n: p for n, _, p in s6_mass_rows(objs, {"nose": 0, "tailcone": 0})}
    moved = (before.y - S6_CG_TARGET) * m / (centre["tailcone"].y - centre["nose"].y)
    masses["tailcone"] -= moved
    masses["nose"] += moved
    for n, kg in masses.items():
        if n in objs:
            objs[n]["mass_kg"] = round(kg, 2)
    return {"kg": masses, "moved_tailcone_to_nose_kg": round(moved, 1), "cg_before_station": round(before.y, 3)}


def silhouette_gap(objs, a_names, b_names, axes, cell=0.02):
    """Two part sets' silhouettes in an orthographic view (axes: the two world coordinates kept), rasterised at `cell`:
    the gap between them, or the overlapping area when they cross (proportion_study.py round 4)."""
    from mathutils.kdtree import KDTree

    def tris(names):
        out = []
        for n in names:
            o = objs[n]
            pts = np.array([(p[axes[0]], p[axes[1]]) for p in world_mesh(o)[0]])
            for poly in o.data.polygons:
                ids = poly.vertices
                out += [(pts[ids[0]], pts[ids[i]], pts[ids[i + 1]]) for i in range(1, len(ids) - 1)]
        return np.array(out)
    ta, tb = tris(a_names), tris(b_names)
    lo = np.minimum(ta.reshape(-1, 2).min(0), tb.reshape(-1, 2).min(0)) - 0.1
    hi = np.maximum(ta.reshape(-1, 2).max(0), tb.reshape(-1, 2).max(0)) + 0.1
    shape = tuple(np.ceil((hi - lo) / cell).astype(int) + 1)

    def raster(T):
        mask = np.zeros(shape, bool)
        for a, b, c in T:
            i0 = np.floor((np.minimum(np.minimum(a, b), c) - lo) / cell).astype(int)
            i1 = np.ceil((np.maximum(np.maximum(a, b), c) - lo) / cell).astype(int)
            gx, gy = np.meshgrid(np.arange(i0[0], i1[0] + 1), np.arange(i0[1], i1[1] + 1), indexing="ij")
            px, py = lo[0] + gx * cell, lo[1] + gy * cell
            d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(d) < 1e-12:
                continue
            l1 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
            l2 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
            mask[gx, gy] |= (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        return mask
    ma, mb = raster(ta), raster(tb)
    both = ma & mb
    if both.any():
        return {"overlap_m2": round(float(both.sum()) * cell * cell, 3), "gap_m": 0.0}
    edge = lambda m: np.argwhere(m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1)))
    ea, eb = edge(ma), edge(mb)
    tree = KDTree(len(eb))
    for i, (x, y) in enumerate(eb):
        tree.insert((float(x), float(y), 0.0), i)
    tree.balance()
    return {"overlap_m2": 0.0, "gap_m": round(min(tree.find((float(x), float(y), 0.0))[2] for x, y in ea) * cell, 2)}


# ---------- smoothness (owner: "the design should just flow into each other with natural lines") ----------
SMOOTH_KINK_DEG = 5.0  # a silhouette slope jump or a junction crease past this is reported
SMOOTH_BODY = ("radar_F_fairing", "nose", "fuselage_F", "fuselage_M", "fuselage_R", "tailcone", "wingfairing",
               "spine_cover", "radar_R_fairing", "sponson_L", "sponson_R")
# Where one shape meets another, left side (the right mirrors it): part a's skin where it meets part b's.
SMOOTH_JUNCTIONS = (("wingfairing", "fuselage_M"), ("wingfairing", "fuselage_F"), ("wingfairing", "wing_root_L"),
                    ("wing_root_L", "wingfairing"), ("sponson_L", "fuselage_M"), ("sponson_L", "fuselage_R"),
                    ("strut_inner_L", "fuselage_M"), ("strut_inner_L", "fuselage_F"), ("strut_inner_L", "nacelle_1"),
                    ("strut_outer_L", "nacelle_1"), ("strut_outer_L", "wing_root_L"), ("pylon_1", "wing_root_L"),
                    ("pylon_1", "nacelle_1"), ("vtail_L", "fuselage_R"), ("vtail_L", "tailcone"),
                    ("radar_F_fairing", "nose"), ("laser_turret", "tailcone"))


def smooth_tree(objs, names):
    """One BVH over the named parts' triangles, and each triangle's part."""
    verts, tris, owner = [], [], []
    for n in names:
        v, p = world_mesh(objs[n])
        for poly in p:
            tris += [(len(verts) + poly[0], len(verts) + poly[i], len(verts) + poly[i + 1]) for i in range(1, len(poly) - 1)]
            owner += [n] * (len(poly) - 2)
        verts += v
    return BVHTree.FromPolygons(verts, tris), owner


def outline_kinks(pts, parts, view, label, window=3):
    """Turning angles of a sampled outline (2D points in order) over `window` samples a side, as local maxima past
    SMOOTH_KINK_DEG: (degrees, view, where, part)."""
    found = []
    turn = [0.0] * len(pts)
    for i in range(window, len(pts) - window):
        a, b, c = pts[i - window], pts[i], pts[i + window]
        if None in (a, b, c):
            continue
        u, v = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        turn[i] = abs(math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])))
    for i in range(1, len(pts) - 1):
        if turn[i] > SMOOTH_KINK_DEG and turn[i] >= turn[i - 1] and turn[i] > turn[i + 1]:
            found.append((round(turn[i], 1), view, label(pts[i]), parts[i]))
    return found


def smoothness_report(objs, step=0.05):
    """The lever for the owner's rule that every junction flows: slope jumps past SMOOTH_KINK_DEG in the body's side
    (crown and belly), top and front silhouettes (SMOOTH_BODY: fuselage, wing fairing, sponsons), and the crease
    angle between their visible skins where each SMOOTH_JUNCTIONS pair meets (0 deg tangent, 90 a butt joint). Facets of the
    blockout's lofts show as small jumps at ring stations. Rerun it on any pass: smoothness_report(objs)."""
    tree, owner = smooth_tree(objs, SMOOTH_BODY)
    stations = [k * step for k in range(int(S6_LENGTH / step) + 1)]
    xs = [k * 0.02 for k in range(int(4.0 / 0.02))]
    kinks = []
    for name, z0, d in (("side crown", 30.0, -1.0), ("side belly", -5.0, 1.0)):
        pts, parts = [], []
        for s in stations:
            best = None
            for x in xs:
                loc, _, i, _ = tree.ray_cast(Vector((x, st(s), z0)), Vector((0, 0, d)))
                if loc is not None and (best is None or (loc.z - best[0]) * -d > 0):
                    best = (loc.z, owner[i])
            pts.append(None if best is None else (s, best[0]))
            parts.append(None if best is None else best[1])
        kinks += outline_kinks(pts, parts, name, lambda p: f"station {p[0]:.2f}, {p[1]:.2f} m up")
    pts, parts = [], []
    for s in stations:
        best = None
        for z in (k * 0.02 for k in range(40, 380)):
            loc, _, i, _ = tree.ray_cast(Vector((20.0, st(s), z)), Vector((-1, 0, 0)))
            if loc is not None and (best is None or loc.x > best[0]):
                best = (loc.x, owner[i])
        pts.append(None if best is None else (s, best[0]))
        parts.append(None if best is None else best[1])
    kinks += outline_kinks(pts, parts, "top, left side", lambda p: f"station {p[0]:.2f}, {p[1]:.2f} m out")
    pts, parts = [], []
    hit = lambda x, z: tree.ray_cast(Vector((x, st(-1.0), z)), Vector((0, 1, 0)))
    for k in range(361):
        th = math.radians(k * 0.5)
        lo, hi = 0.0, 6.0
        for _ in range(22):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if hit(mid * math.sin(th), FUS_CENTER_Z + mid * math.cos(th))[0] is not None else (lo, mid)
        res = hit(lo * math.sin(th), FUS_CENTER_Z + lo * math.cos(th))
        pts.append((lo * math.sin(th), FUS_CENTER_Z + lo * math.cos(th)))
        parts.append(owner[res[2]] if res[0] is not None else None)
    kinks += outline_kinks(pts, parts, "front, left side", lambda p: f"{p[0]:.2f} m out, {p[1]:.2f} m up")

    creases = {}
    for a, b in SMOOTH_JUNCTIONS:
        bv, bp = world_mesh(objs[b])
        btree = mesh_geo([objs[b]])[b][1]  # a thin-walled part's envelope: its lining is no surface to meet
        blo, bhi = bounds(bv)
        av, ap = world_mesh(objs[a])
        skin = set(slot_faces(objs[a], SKIN))  # visible skin only: caps and buried faces carry aircraft_structure
        angles = []
        for f, poly in enumerate(ap):
            if f not in skin:
                continue
            for t in range(1, len(poly) - 1):
                p0, p1, p2 = av[poly[0]], av[poly[t]], av[poly[t + 1]]
                if not boxes_touch(bounds([p0, p1, p2]), (blo, bhi), 0.05):
                    continue
                na = (p1 - p0).cross(p2 - p0)
                if na.length < 1e-12:
                    continue
                na.normalize()
                n = min(40, max(1, math.ceil(max((p1 - p0).length, (p2 - p0).length) / step)))
                for i in range(n + 1):
                    for j in range(n + 1 - i):
                        q = p0 + (p1 - p0) * (i / n) + (p2 - p0) * (j / n)
                        loc, nb, _, dist = btree.find_nearest(q, 0.04)
                        if loc is not None and (q - loc).dot(nb) >= 0:
                            angles.append((math.degrees(na.angle(nb)), q))
        if angles:
            angles.sort(key=lambda r: r[0])
            deg, q = angles[-1]
            creases[f"{a}~{b}"] = {"max_deg": round(deg, 1), "p90_deg": round(angles[int(0.9 * (len(angles) - 1))][0], 1),
                                   "median_deg": round(angles[len(angles) // 2][0], 1),
                                   "at": [round(q.x, 2), round(q.y + Y0, 2), round(q.z, 2)], "samples": len(angles)}
        else:
            creases[f"{a}~{b}"] = {"samples": 0, "note": "no skin within 4 cm"}
    kinks.sort(key=lambda k: -k[0])
    return {"limit_deg": SMOOTH_KINK_DEG, "silhouette_kinks": [{"deg": d, "view": v, "at": w, "part": p} for d, v, w, p in kinks],
            "junction_creases": creases}


def s6_vtail_areas():
    """One panel outboard of the skin (measured as round 4 does: the root's exposed run starts where the root line
    leaves the body at mid root chord), its ruddervator, and the area-weighted quarter-chord station."""
    n, dih, span = 200, VTAIL_DIHEDRAL, VTAIL_SPAN
    c = lambda d: vtail_planform(d)[1]
    d_skin = max(side_x_s6(VTAIL_ROOT_STATION + 0.5 * VTAIL_ROOT_CHORD, VTAIL_ROOT_Z) - VTAIL_ROOT_X, 0.0) / math.cos(dih)
    step = (span - d_skin) / n
    ds = [d_skin + step * (k + 0.5) for k in range(n)]
    area = sum(c(d) for d in ds) * step
    qc = sum(c(d) * (vtail_planform(d)[0] + 0.25 * c(d)) for d in ds) * step / area
    d0, d1 = RUDDERVATOR_SPAN

    def moving(a, b):  # the area aft of the straight hinge line between a and b
        return sum(c(d) * (1 - vtail_hinge_fraction(d, RUDDERVATOR_HINGE)) for d in (a + (b - a) * (k + 0.5) / n for k in range(n))) * (b - a) / n
    rv = moving(d0, d1)
    surfaces = {name: {"span_m": [round(a, 2), round(b, 2)], "m2": round(moving(a, b), 2)} for name, (a, b) in ruddervator_spans("_L")}
    return {"panel_m2_each": round(area, 1), "ruddervator_m2_each": round(rv, 1), "dihedral_deg": round(math.degrees(dih), 1),
            "span_along_panel_m": round(span, 2), "exposed_from_m": round(d_skin, 2), "ruddervator_span_m": [d0, round(d1, 2)],
            "moving_surfaces_left": surfaces,
            "pitch_effective_m2_total": round(2 * area * math.cos(dih) ** 2, 1),
            "yaw_effective_m2_total": round(2 * area * math.sin(dih) ** 2, 1), "quarter_chord_station": round(qc, 2),
            "root": {"station": VTAIL_ROOT_STATION, "chord": VTAIL_ROOT_CHORD, "x": VTAIL_ROOT_X, "z": VTAIL_ROOT_Z},
            "tip_chord": VTAIL_TIP_CHORD, "sweep_deg": round(math.degrees(VTAIL_SWEEP), 1)}


def s6_planform(objs, step=0.1):
    """Fixed wing and stages seen from above (rays down through a grid): exposed area outside the body sides and
    the gross area with the body's share (round 4's measure)."""
    verts, tris = [], []
    for n, o in objs.items():
        if o.type == "MESH" and n.startswith(("wing_root", "wing_outer", "wing_tele", "wing_tip")):
            v, p = world_mesh(o)
            tris += [tuple(len(verts) + i for i in poly) for poly in p]
            verts += v
    tree = BVHTree.FromPolygons(verts, tris)
    lo, hi = bounds(verts)
    hits = 0
    for x in np.arange(lo.x, hi.x, step):
        if abs(x) <= FUS_HALF_W:
            continue
        for y in np.arange(lo.y, hi.y, step):
            hits += tree.ray_cast(Vector((x, y, 30.0)), Vector((0, 0, -1)))[0] is not None
    exposed = hits * step * step
    return exposed, exposed + 2 * FUS_HALF_W * CHORD[0][1]


def s6_body_volume(step=0.05):
    """The fuselage's volume from its profile (superellipse sections, the chine ignored), its barrel section, and each
    bay's share under the body's centre line, the half the bays and their stores take."""
    area = lambda s: (lambda w, top, bot: 4 * w * (top - bot) / 2 * math.gamma(1 + 1 / FUS_P) ** 2 / math.gamma(1 + 2 / FUS_P))(*fus_profile(s))
    vol = lambda s0, s1, k=1.0: k * step * sum(area(s0 + step * (i + 0.5)) for i in range(round((s1 - s0) / step)))
    return {"volume_m3": round(vol(0.0, TAIL_END[-1][0]), 1), "barrel_section_m2": round(area(21.0), 2),
            "bays_lower_half_m3": {f"{bay} {s0:g} to {s1:g}": round(vol(s0, s1, 0.5), 1) for bay, s0, s1, _ in BAYS}}


def s6_wing_mac():
    n = 200
    xs = [X_ROOT_TIP * (k + 0.5) / n for k in range(n)]
    cs = [interp(CHORD, x) for x in xs]
    qcs = [qc_at(1, x * XI_PER_X).y + Y0 for x in xs]
    return sum(c * c for c in cs) / sum(cs), sum(c * q for c, q in zip(cs, qcs)) / sum(cs)


def s6_stage_slide(objs):
    """At each checked extension, how deep each stage's skin sits inside its parent's (the slide clearance, metres;
    negative: through the parent's skin), over the stage's run still inside the parent and short of the raked tip."""
    out = {}
    for e in EXTENSIONS_CHECKED:
        set_extension(objs, e)
        row = {}
        for s in ("_L", "_R"):
            for c, p in (("wing_tele1", "wing_root"), ("wing_tele2", "wing_tele1")):
                child, parent = objs[c + s], (fixed_wing(objs, s) if p == "wing_root" else objs[p + s])
                pv, pp = world_mesh(parent)
                tree = BVHTree.FromPolygons(pv, pp)
                x_end = max(abs(v.x) for v in pv) - 0.1
                if "tip_qc" in child:
                    x_end = min(x_end, abs((child.matrix_world @ Vector(child["tip_qc"])).x))
                depths = [signed_depth(tree, v) for v in world_mesh(child)[0] if abs(v.x) < x_end]
                row[f"{c}{s}_in_{p}{s}_m"] = round(min(depths), 4)
        out[f"{e:.2f}"] = row
    set_extension(objs, 0.0)
    return out


def s6_surface_sweep(objs, sfx):
    """Each wing surface at its deflection limits (flaps 30 deg down, ailerons 25 either way; CenturionAuthor's
    ranges) against the strut, nacelle and nozzle under them: nearest distance and intersecting faces."""
    out = {}
    num = 1 if sfx == "L" else 2
    under = [objs[n] for n in (f"strut_inner_{sfx}", f"strut_outer_{sfx}", f"nacelle_{num}", f"nozzle_{num}")]
    for name, deg in ((f"flap_{sfx}1", -30), (f"flap_{sfx}2", -30), (f"aileron_{sfx}", -25), (f"aileron_{sfx}", 25)):
        hinge, mesh = objs[name], objs[name + "_visible"]
        rest = hinge.matrix_basis.copy()
        hinge.matrix_basis = rest @ Matrix.Rotation(math.radians(deg), 4, "X")  # local X is the hinge; minus is down
        bpy.context.view_layer.update()
        near = min(under, key=lambda o: min(min_distance(mesh, o), min_distance(o, mesh)))
        out[f"{name}_{deg:+d}deg"] = {"nearest": near.name,
                                      "min_m": round(min(min_distance(mesh, near), min_distance(near, mesh)), 3),
                                      "intersecting_face_pairs": sum(clash_faces(mesh, o) for o in under)}
        hinge.matrix_basis = rest
    bpy.context.view_layer.update()
    return out


def s6_report(objs, masses):
    """Step 6's own numbers at rest (retracted): mass and balance, ground attitude, the engine install, the strut, the
    V-tail against the nacelle and the jet, one engine out, the AWACS spine well, stage slides and the tear's part loss."""
    set_extension(objs, 0.0)
    e, x = S6_ENGINE, S6_ENGINE["x"]
    r = e["od"] / 2
    station = lambda p: round(p.y + Y0, 3)
    pt = lambda p: [round(p.x, 2), station(p), round(p.z, 2)]
    out = {}

    m, cg = s6_cg(objs, masses["kg"])
    nose_w, main_w = objs["wheel_F"].matrix_world.translation, objs["wheel_LM"].matrix_world.translation
    s_nose, s_main = station(nose_w), station(main_w)
    mac, qbar = s6_wing_mac()
    c = main_contact(objs)
    static = math.degrees(math.atan2(c.z - min(v.z for v in world_mesh(objs["wheel_F"])[0]), c.y - nose_w.y))
    strike = tail_strike(objs)
    tail_names = ("vtail", "ruddervator")
    tail_strike_deg = min(math.degrees(math.atan2(v.z - c.z, v.y - c.y)) for n, o in objs.items()
                          if o.type == "MESH" and n.startswith(tail_names) for v in world_mesh(o)[0] if v.y > c.y + 0.5)
    out["mass_and_balance"] = {
        "empty_kg": round(m, 2), "pass_125000": abs(m - S6_EMPTY_MASS) < 0.5, **{k: v for k, v in masses.items() if k != "kg"},
        "cg_station": round(cg.y, 3), "cg_height_m": round(cg.z, 3), "cg_target_station": S6_CG_TARGET,
        "mac_m": round(mac, 2), "mac_quarter_chord_station": round(qbar, 2),
        "cg_percent_mac": round(100 * (cg.y - (qbar - 0.25 * mac)) / mac, 1),
        "nose_gear_station": s_nose, "main_gear_station": s_main, "main_behind_cg_m": round(s_main - cg.y, 2),
        "nose_gear_share": round((s_main - cg.y) / (s_main - s_nose), 3)}
    out["ground"] = {"static_attitude_deg": round(static, 2), "strike_deg": strike["value"],
                     "strike_first_contact": strike["first_contact"], "rotation_from_static_deg": round(strike["value"] - static, 2),
                     "tail_surfaces_first_touch_deg": round(tail_strike_deg, 2),
                     "belly_m": round(min(v.z for v in world_mesh(objs["fuselage_M"])[0]), 2)}
    # The main bogie stowed: its wheel box (six 1.2 m wheels on the 2.8 m beam, 1.2 x 4.0 x 1.2 m) centred in the left
    # sponson's section at the gear station must sit inside the pod or the body.
    cx, cz = sponson_section(MAIN_GEAR_STATION)[:2]
    trees = [BVHTree.FromPolygons(*world_mesh(objs[n])) for n in ("sponson_L", "fuselage_M", "fuselage_R")]
    stowed = min(max(signed_depth(t, Vector((cx + dx, st(MAIN_GEAR_STATION + ds), cz + dz))) for t in trees)
                 for dx in (-0.6, 0.0, 0.6) for ds in (-2.0, -1.0, 0.0, 1.0, 2.0) for dz in (-0.6, 0.0, 0.6))
    out["main_bogie_stowed"] = {"box_m": [1.2, 4.0, 1.2], "centre": [round(cx, 2), MAIN_GEAR_STATION, round(cz, 2)],
                                "least_depth_m": round(stowed, 3), "limit": ">= 0.05", "pass": stowed >= 0.05}

    le_st = wing_le(1, x)[0].y + Y0
    front = NACELLES[0][3]
    nac = world_mesh(objs["nacelle_1"])[0]
    noz = world_mesh(objs["nozzle_1"])[0]
    overall = max(v.y for v in noz) + Y0 - front
    out["engine"] = {"outer_diameter_m": e["od"], "cowl_m": e["cowl"], "overall_m": round(overall, 2),
                     "semi_span_m": x, "axis_height_m": round(NACELLE_Z, 3), "intake_station": round(front, 2),
                     "wing_le_station": round(le_st, 2), "ahead_of_le_m": round(le_st - front, 2),
                     "share_of_nacelle_ahead_of_le": round((le_st - front) / overall, 3),
                     "share_of_cowl_ahead_of_le": round((le_st - front) / e["cowl"], 3),
                     "ground_clearance_m": round(min(v.z for v in nac), 2),
                     "crown_to_wing_m": round(min_distance(objs["nacelle_1"], objs["wing_root_L"]), 3),
                     "to_sponson_m": round(min_distance(objs["nacelle_1"], objs["sponson_L"]), 2),
                     "to_fuselage_m": round(min(min_distance(objs["nacelle_1"], objs[f]) for f in ("fuselage_M", "fuselage_F")), 2),
                     "od_over_body": round(e["od"] / (2 * FUS_HALF_W), 2)}

    hub, root = Vector(objs["strut_inner_L"]["line_node"]), Vector(objs["strut_inner_L"]["line_root"])
    node = Vector(objs["strut_outer_L"]["line_node"])
    di, do = hub - root, node - hub
    group = ("nacelle_1", "nozzle_1", "fan_1")
    d_in, d_out = s6_cowl_crossings(1, root, node)
    ax = (node - root).normalized()
    axis = Vector((x, 0, NACELLE_Z))
    radial = lambda v: math.hypot(v.x - axis.x, v.z - axis.z)
    strut = {"root": pt(root), "node_in_nacelle": pt(hub), "wing_node": pt(node),
             "length_m": round((node - root).length, 2), "inner_m": round(di.length, 2), "outer_m": round(do.length, 2),
             "segments_angle_deg": round(math.degrees(di.angle(do)), 3),
             "rise_front_view_deg": round(math.degrees(math.atan2(node.z - root.z, node.x - root.x)), 1),
             "lean_plan_deg": round(math.degrees(math.atan2(root.y - node.y, node.x - root.x)), 1),
             "longest_free_length_m": round(max(di.length, do.length), 2),
             "crosses_cowl_at_u": round((hub.y + Y0 - NACELLES[0][3]) / NACELLE_LEN, 3),
             "under_engine_axis_m": round(NACELLE_Z - hub.z, 2),
             "nearest_to_engine_axis_m": round(radial(hub) * math.cos(math.atan2(node.z - root.z, node.x - root.x)), 2),
             "enters_cowl": pt(root + ax * d_in), "leaves_cowl": pt(root + ax * d_out)}
    # Its lifting area: the chord over the length outside the sponson, the nacelle and the wing.
    def in_sponson(v):
        sec = sponson_section(v.y + Y0)
        if sec is None or sec[4] == 0:
            return False
        cx, cz, a_out, a_in, b = sec
        d = v.x - cx
        return (d / (a_out if d > 0 else a_in)) ** 2 + ((v.z - cz) / b) ** 2 < 1
    d_sp = next(i * 0.01 for i in range(2000) if not in_sponson(root + ax * (i * 0.01)))
    ch, inner, outer = S6_STRUT["chord"], d_in - d_sp, (node - root).length - d_out
    strut["section"] = {"chord_m": ch, "thickness_m": S6_STRUT["thick"], "t_over_c": round(S6_STRUT["thick"] / ch, 2),
                        "airfoil": "symmetric NACA four-digit, chord along the flow"}
    strut["planform_m2_each_side"] = {"inner": round(ch * inner, 1), "outer": round(ch * outer, 1),
                                      "total": round(ch * (inner + outer), 1),
                                      "exposed_length_m": [round(inner, 2), round(outer, 2)]}
    skin = wing_lower(1, STRUT_WING_X, node.y + Y0) - wing_lower(1, STRUT_WING_X - 1.0, node.y + Y0)  # front view
    strut["meets_wing_skin_at_deg"] = round(strut["rise_front_view_deg"] - math.degrees(math.atan2(skin.z, skin.x)), 1)
    for view, axes in (("front_or_rear", (0, 2)), ("side", (1, 2)), ("top", (0, 1))):
        strut[f"vs_engine_{view}"] = silhouette_gap(objs, ("strut_inner_L", "strut_outer_L"), group, axes)
    strut["to_core_and_nozzle_3d_m"] = round(min(min_distance(objs[s], objs["nozzle_1"]) for s in ("strut_inner_L", "strut_outer_L")), 3)
    strut["to_fan_3d_m"] = round(min(min_distance(objs[s], objs["fan_1"]) for s in ("strut_inner_L", "strut_outer_L")), 3)
    # The jets, as straight-aft cylinders off the fan nozzle petals and the core nozzle: how far ahead of the fan
    # nozzle's exit the strut stays, and how close any of it behind the exit comes to either jet.
    petal_exit, fan_r = objs["nozzle_1"].matrix_world.translation.y + e["petal_len"], r * S6_UF_OUTER[-1][0] - 0.11
    sv = [v for s in ("strut_inner_L", "strut_outer_L") for v in world_mesh(objs[s])[0]]
    behind = [v for v in sv if v.y > petal_exit and radial(v) < fan_r + 1.0]
    strut["exhaust"] = {"strut_aft_of_fan_nozzle_exit_within_1m_of_the_jet": len(behind),
                        "aftmost_strut_point_near_the_jet_vs_exit_m": round(max(v.y for v in sv if radial(v) < fan_r + 1.0) - petal_exit, 2),
                        "fan_stream_radius_m": round(fan_r, 2)}
    strut["surfaces_at_limits_vs_outer"] = s6_surface_sweep(objs, "L")
    out["strut"] = strut

    va = s6_vtail_areas()
    left_surfaces = tuple(n + "_visible" for n, _ in ruddervator_spans("_L"))
    span = max(v.x for o in objs.values() if o.type == "MESH" for v in world_mesh(o)[0]) * 2
    exposed, gross = s6_planform(objs)
    lv = va["quarter_chord_station"] - cg.y
    sy, sp = va["yaw_effective_m2_total"], va["pitch_effective_m2_total"]
    tail_top = max(v.z for n, o in objs.items() if o.type == "MESH" and n.startswith(tail_names) for v in world_mesh(o)[0])
    tail_x = max(v.x for n, o in objs.items() if o.type == "MESH" and n.startswith(tail_names) for v in world_mesh(o)[0])
    out["vtail"] = {**va, "tail_top_m": round(tail_top, 3), "tail_span_m": round(2 * tail_x, 2),
                    "arm_m": round(lv, 2), "wing_gross_m2": round(gross, 1), "wing_exposed_m2": round(exposed, 1),
                    "horizontal_volume": round(sp * lv / (gross * mac), 3), "vertical_volume": round(sy * lv / (gross * span), 4),
                    "rear_view_vs_nacelle": silhouette_gap(objs, ("vtail_L",) + left_surfaces, ("nacelle_1", "nozzle_1"), (0, 2)),
                    "rear_view_to_fan_stream_m": round(min(radial(v) - fan_r for n in ("vtail_L",) + left_surfaces
                                                           for v in world_mesh(objs[n])[0]), 2),
                    "fan_stream_radius_m": round(fan_r, 2)}
    # One engine out at takeoff thrust, sea level: the speed where full rudder holds the yaw, with round 3's side-force
    # coefficient of 0.6 on the yaw-effective area (read across, not as a certified number). T5a: 33.4 m2 on 19.44 m.
    held = lambda kn, s_l: round(math.sqrt(kn * 1000 * x / (0.5 * 1.225 * 0.6 * s_l)), 1)
    out["engine_out"] = {f"{kn:.0f}_kN": {"yaw_kN_m": round(kn * x), "vtail_holds_from_m_s": held(kn, sy * lv),
                                           "T5a_would_hold_from_m_s": held(kn, 33.4 * 19.44)} for kn in (270.0, 300.0)}
    out["engine_out"].update({"yaw_volume_m3": round(sy * lv, 1), "T5a_yaw_volume_m3": round(33.4 * 19.44, 1),
                              "round4_vtail_yaw_volume_m3": round(32.2 * 15.56, 1), "rotation_m_s": S6_ROTATION_MS,
                              "round4_at_6m": "V-tail 94 / 99 m/s, T5a 82 / 87 m/s (270 / 300 kN)"})

    s0 = S6_WELL_START
    s1 = s0 + S6_WELL["length"]
    crown = [fus_profile(s)[1] for s in (s0, (s0 + s1) / 2, s1)]
    floor = min(crown) - S6_WELL["depth"]
    box_lo, box_hi = Vector((-S6_WELL["width"] / 2, st(s0), floor)), Vector((S6_WELL["width"] / 2, st(s1), max(crown)))
    dist = lambda v: Vector([max(box_lo[i] - v[i], 0.0, v[i] - box_hi[i]) for i in range(3)]).length
    near = lambda names: round(min(dist(v) for n in names for v in world_mesh(objs[n])[0]), 2)
    cut = ("fuselage_R", "tailcone", "wingfairing", "spine_cover", "fuselage_M")
    others = [n for n, o in objs.items() if o.type == "MESH" and n not in cut]
    nearest = min(others, key=lambda n: near((n,)))
    out["awacs_well"] = {"stations": [round(s0, 2), round(s1, 2)], "crown_m": [round(z, 2) for z in crown],
                         "floor_m": round(floor, 2), "wing_box_to_well_m": near(("wing_root_L", "wing_root_R")),
                         "tail_to_well_m": near(("vtail_L", "vtail_R") + tuple(n + "_visible" for s in ("_L", "_R") for n, _ in ruddervator_spans(s))),
                         "nearest_uncut_part": [nearest, near((nearest,))],
                         "belly_under_mast_m": round(fus_profile((s0 + s1) / 2)[2], 2), "skins_cut": list(cut)}
    if WELL_OPEN:
        # The beam mount's joint excludes only fuselage_R: every other part's collider stands WELL_CLEAR back from the
        # well grown by WELL_CLEAR, and a ray down the well's centreline from 8 m meets nothing above its floor (the
        # bomber's lids, spine_cover and the part tree's other visual pieces, aside).
        lo, hi = well_box(WELL_CLEAR)
        box_hull = convex.hull_mesh(box_corners(lo, hi))
        gaps = {}
        for c in bpy.data.collections["Colliders"].objects:
            v, t = world_hull(c)
            if c.parent.name != "fuselage_R" and box_gap((Vector(v.min(0)), Vector(v.max(0))), (lo, hi)) < 1.0:
                gaps[c.name] = round(convex.hull_gap((v, t), box_hull), 3)
        import part_splits
        lids = ("spine_cover",) + part_splits.VISUAL
        tree, _ = smooth_tree(objs, [n for n, o in objs.items() if o.type == "MESH" and n not in lids])
        floor = well_box()[0].z
        hits = [tree.ray_cast(Vector((0.0, st(s), 8.0)), Vector((0, 0, -1)))[0] for s in
                (s0 + 0.05 + (s1 - s0 - 0.1) * k / 100 for k in range(101))]
        top_hit = max((h.z for h in hits if h is not None), default=-math.inf)
        closest = min(gaps, key=gaps.get) if gaps else None
        out["awacs_well_clear"] = {
            "clearance_box": {"stations": [round(lo.y + Y0, 2), round(hi.y + Y0, 2)], "half_width_m": round(hi.x, 2),
                              "from_m": round(lo.z, 2)},
            "limit_m": WELL_CLEAR, "collider_gaps_m": gaps, "nearest": [closest, gaps.get(closest)],
            "slot_ray_highest_hit_m": round(top_hit, 3), "floor_m": round(floor, 3), "slot_open": top_hit <= floor + 1e-3,
            "pass": all(g >= WELL_CLEAR - 1e-4 for g in gaps.values()) and top_hit <= floor + 1e-3}
    if AFT_BAY_ROOF:
        out["aft_bay"] = aft_bay_report(objs)

    surfaces = [n for n, o in objs.items() if o.type == "EMPTY" and n.startswith(CONTROL_SURFACES)]
    aero = len(LOAD_PARTS) + 2 + len(surfaces)  # + radar_F_fairing and the cockpit
    out["body"] = {"diameter_m": S6_BODY_D, "length_over_diameter": round(S6_LENGTH / S6_BODY_D, 2), **s6_body_volume()}
    out["tear_part_loss"] = {"aero_parts": aero, "lost_in_a_tear": 4, "ratio": round(4 / aero, 4), "limit": "< 0.12",
                             "pass": 4 / aero < 0.12,
                             "note": "a tear sheds wing_tele1 and wing_tele2 on both sides; step 5 lost 4 of 43"}
    out["stage_slide"] = s6_stage_slide(objs)
    out["smoothness"] = smoothness_report(objs)
    return out


# ---------- step 6 renders: the M4 review look ----------
PAINT_SRGB, RADOME_SRGB = (0.38, 0.39, 0.405), (0.33, 0.335, 0.34)  # m4/paint.py's hull and radome greys
# name: (("persp", lens) or ("ortho", scale), camera (x, station, z), look-at (x, station, z) or euler deg, caption).
# The first ten are round 4's cameras (proportion_study.py VIEWS), so the sheets' before and after frames match.
S6_VIEWS = {
    "hero": (("persp", 50), (56.0, -50.5, 44.0), (0.0, 21.5, 3.0), "3/4 from front left"),
    "side": (("ortho", 50), (120.0, 21.5, 3.8), (90, 0, 90), "side"),
    "top": (("ortho", 76), (0.0, 21.5, 80.0), (0, 0, 180), "top, nose up"),
    "front": (("ortho", 76), (0.0, -98.5, 3.8), (90, 0, 0), "front"),
    "rear": (("ortho", 30), (0.0, 141.5, 4.6), (90, 0, 180), "rear, tail close"),
    "rear_full": (("ortho", 76), (0.0, 141.5, 3.8), (90, 0, 180), "rear"),
    "front_span": (("ortho", 48), (0.0, -98.5, 4.4), (90, 0, 0), "front"),
    "rear_span": (("ortho", 48), (0.0, 141.5, 4.4), (90, 0, 180), "rear"),
    "engine34": (("persp", 40), (1.6, -5.5, 1.5), (6.0, 12.5, 4.0), "round 4's engine camera, low ahead inboard"),
    "strut_r4": (("persp", 38), (24.0, 41.5, 1.2), (9.0, 20.5, 3.6), "low behind the left wing"),
    "install34": (("persp", 35), (20.0, 2.0, 2.2), (7.0, 19.5, 4.8), "engine install, 3/4 from front left, low"),
    "install_side": (("ortho", 17), (120.0, 20.5, 4.4), (90, 0, 90), "engine install, side"),
    "collar_in": (("persp", 32), (1.5, 11.0, 0.7), (6.4, 20.2, 2.7), "strut entering the nacelle, from ahead, low"),
    "collar_out": (("persp", 32), (14.5, 28.5, 1.0), (8.6, 20.4, 3.2), "strut leaving the nacelle, from behind, low"),
    "tail_end": (("persp", 35), (17.0, 58.0, 5.5), (1.5, 40.0, 4.8), "tail end, from behind left"),
    "front_left": (("ortho", 24), (8.0, -98.5, 4.4), (90, 0, 0), "front, left wing: strut through the engine"),
    "rear_left": (("ortho", 24), (8.0, 141.5, 4.4), (90, 0, 180), "rear, left wing: V-tail, nacelle, strut"),
    "front_hangar": (("ortho", 52), (0.0, -98.5, 4.0), (90, 0, 0), "hangar door, retracted"),
    "top_hangar": (("ortho", 82), (0.0, S6_LENGTH / 2, 80.0), (0, 0, 180), "hangar footprint, spawn at its centre"),
}
S6_STATE_CAMERA = {"retracted": {"hero": ("persp", 62), "front": ("ortho", 50), "rear_full": ("ortho", 50)}}
S6_STATE_VIEWS = {"retracted": ("hero", "side", "top", "front_span", "rear_span", "rear", "side_strike", "side_pitch",
                                "front_hangar", "top_hangar", "engine34", "strut_r4", "install34", "install_side",
                                "collar_in", "collar_out", "tail_end", "front_left", "rear_left"),
                  "extended": ("hero", "side", "top", "front", "rear_full", "rear")}


def s6_rig():
    """Step 5's render collection (hangar overlays, camera) plus round 4's sun, ground, sky and strike lines, in Cycles."""
    from m4 import render as m4r
    cam, door, foot = build_render_rig()
    coll = bpy.data.collections["Centurion_render"]
    sun = bpy.data.objects.new("s6_sun", bpy.data.lights.new("s6_sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.2, math.radians(2.5)
    sun.rotation_euler = (math.radians(42), math.radians(12), math.radians(-35))
    coll.objects.link(sun)
    me = bpy.data.meshes.new("s6_ground")
    me.from_pydata([(-2000, -2000, 0), (2000, -2000, 0), (2000, 2000, 0), (-2000, 2000, 0)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new("s6_ground", me)
    gm = material("s6_ground", (0.16, 0.16, 0.155, 1.0))
    m4r.principled(gm, (0.16, 0.16, 0.155), 0.85, 0.0)
    me.materials.append(gm)
    coll.objects.link(ground)
    lines = {}
    for name, rgb, deg in (("strike_red", (0.6, 0.03, 0.02), TAIL_STRIKE_MIN_DEG), ("strike_amber", (0.8, 0.45, 0.02), 9.5)):
        mat = material(name, (*rgb, 1.0))
        m4r.principled(mat, rgb, 0.6, 0.0, tuple(min(1.0, 1.5 * c) for c in rgb), 1.5)
        lines[name] = (overlay(coll, name, [((0, 20.0, 0), (0.6, 40.0, 0.1))], mat), deg)
    runway = overlay(coll, "s6_runway", [((0, 0, -0.05), (0.6, 90.0, 0.12))], bpy.data.materials["strike_red"])
    for o in [runway] + [o for o, _ in lines.values()]:
        o.hide_render = True
    world = scene.world = scene.world or bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.55, 0.6, 0.68, 1)
    bg.inputs["Strength"].default_value = 0.9
    scene.view_settings.view_transform = "Standard"
    scene.render.engine = "CYCLES"
    m4r.use_gpu(scene)
    scene.cycles.use_denoising = True
    return {"cam": cam, "door": door, "foot": foot, "ground": ground, "lines": lines, "runway": runway}


def s6_style(objs):
    from m4 import render as m4r
    m = bpy.data.materials
    m4r.principled(m[SKIN], tuple(m4r.srgb_to_linear(PAINT_SRGB)), 0.6, 0.0)
    m4r.principled(m[STRUCT], (0.11, 0.115, 0.11), 0.7, 0.2)
    m4r.principled(m[MECH], (0.06, 0.06, 0.065), 0.45, 0.8)
    m4r.principled(m[GLASS], (0.008, 0.011, 0.010), 0.3, 0.0)  # slightly rough: the faceted panes read as one dark pane
    m4r.principled(m[GEAR], (0.16, 0.16, 0.165), 0.55, 0.3)
    radome = material("s6_radome", (0.5, 0.5, 0.5, 1.0))
    m4r.principled(radome, tuple(m4r.srgb_to_linear(RADOME_SRGB)), 0.5, 0.0)
    objs["radar_F_fairing"].data.materials[0] = radome
    for o in bpy.data.collections["Centurion"].all_objects:
        if o.name.endswith("_lod1") or "_colmesh" in o.name:
            o.hide_render = True


def s6_stamp(r, caption, width):
    """Burn the caption, and nothing else, into the top of each rendered frame."""
    r.use_stamp = True
    for attr in dir(r):
        if attr.startswith("use_stamp_") and attr != "use_stamp_note":
            setattr(r, attr, False)
    r.use_stamp_note, r.stamp_note_text, r.stamp_font_size = True, caption, max(14, width // 60)
    r.stamp_foreground, r.stamp_background = (1, 1, 1, 1), (0, 0, 0, 0.65)


def s6_captioned_copy(src, dst, caption, res=(1600, 1000)):
    """A copy of an image with a caption stamped on it as the step 6 frames carry theirs, rendered through a scratch
    scene's sequencer."""
    sc = bpy.data.scenes.new("s6_caption")
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.view_settings.view_transform = "Standard"  # pass the source's colours through unchanged
    sc.sequence_editor_create().strips.new_image("src", str(src), 1, 1)
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = *res, 100
    r.use_sequencer = True
    s6_stamp(r, caption, res[0])
    r.image_settings.file_format = "PNG"
    r.filepath = str(dst)
    sc.frame_start = sc.frame_end = sc.frame_current = 1
    bpy.ops.render.render(write_still=True, scene=sc.name)
    bpy.data.scenes.remove(sc)
    return dst


def s6_shoot(rig, view, path, state, caption, samples=48, res=(1600, 1000)):
    (kind, k), loc, aim, _ = S6_VIEWS[view]
    kind, k = S6_STATE_CAMERA.get(state, {}).get(view, (kind, k))
    cam = rig["cam"]
    cam.location = Vector((loc[0], st(loc[1]), loc[2]))
    if kind == "ortho":
        cam.data.type, cam.data.ortho_scale = "ORTHO", k
        cam.rotation_euler = tuple(math.radians(a) for a in aim)
    else:
        cam.data.type, cam.data.lens = "PERSP", k
        cam.rotation_euler = (Vector((aim[0], st(aim[1]), aim[2])) - cam.location).to_track_quat("-Z", "Y").to_euler()
    r = scene.render
    s6_stamp(r, caption, res[0])
    scene.cycles.samples = samples
    r.resolution_x, r.resolution_y, r.resolution_percentage = *res, 100
    r.image_settings.file_format = "PNG"
    r.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return str(path)


def render_s6(out, state, objs, mode):
    """The state's views (or, for mode "orient", three quick frames to check the axes) in the M4 review look."""
    rig = s6_rig()
    s6_style(objs)
    for o in rig["door"] + rig["foot"]:
        o.hide_render = True
    if mode == "orient":
        return [s6_shoot(rig, v, out / f"orient_{v}_{state}.png", state, f"ORIENT {v}: nose to -Y, left wing +X",
                         samples=8, res=(800, 500)) for v in ("front_span", "side", "top")]
    ext = "" if state == "retracted" else ", extended"
    written = []
    for view in S6_STATE_VIEWS[state]:
        path, cap = out / f"{view}_{state}.png", f"{S6_LABEL}: {S6_VIEWS.get(view, (0, 0, 0, ''))[3]}{ext}"
        if view == "side_strike":  # ground lines from the main contact: red at the strike, amber at the AI's 9.5 deg
            c = main_contact(objs)
            for o, deg in rig["lines"].values():
                o.location, o.rotation_euler, o.hide_render = c, (math.radians(deg), 0, 0), False
            written.append(s6_shoot(rig, "side", path, state, f"{S6_LABEL}: strike lines from the main wheels, red "
                                    f"{TAIL_STRIKE_MIN_DEG} deg, amber 9.5 deg (takeoff AI)"))
            for o, _ in rig["lines"].values():
                o.hide_render = True
        elif view == "side_pitch":  # pitched to the strike angle about the sagged main contact (as step 5's view)
            c = main_contact(objs)
            roots = [o for o in objs.values() if o.parent is None]
            rest = {o: o.matrix_world.copy() for o in roots}
            pitch = (Matrix.Translation((0, c.y, 0)) @ Matrix.Rotation(-math.radians(TAIL_STRIKE_MIN_DEG), 4, "X")
                     @ Matrix.Translation(-c))
            for o in roots:
                o.matrix_world = pitch @ rest[o]
            rig["runway"].hide_render = False
            written.append(s6_shoot(rig, "side", path, state, f"{S6_LABEL}: pitched {TAIL_STRIKE_MIN_DEG} deg about the "
                                    f"main wheels, struts sagged {MAIN_STRUT_SAG:.2f} m: the belly meets the runway"))
            rig["runway"].hide_render = True
            for o in roots:
                o.matrix_world = rest[o]
        elif view in ("front_hangar", "top_hangar"):
            for o in rig["door"] if view == "front_hangar" else rig["foot"]:
                o.hide_render = False
            rig["ground"].hide_render = view == "top_hangar"
            written.append(s6_shoot(rig, view, path, state, cap))
            for o in rig["door"] + rig["foot"]:
                o.hide_render = True
            rig["ground"].hide_render = False
        else:
            written.append(s6_shoot(rig, view, path, state, cap))
    return written


def s6_sheet(tiles, path, columns=2, size=(1280, 800)):
    """Tiles scaled to size, `columns` across (2560 px for two), top row first; a missing tile leaves a grey gap."""
    arrays = []
    for t in tiles:
        if t is None or not Path(t).exists():
            arrays.append(np.full((size[1], size[0], 3), 0.3, np.float32))
            continue
        img = bpy.data.images.load(str(t))
        img.scale(*size)
        px = np.empty(size[0] * size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        arrays.append(px.reshape(size[1], size[0], 4)[..., :3])
        bpy.data.images.remove(img)
    while len(arrays) % columns:
        arrays.append(np.full((size[1], size[0], 3), 0.3, np.float32))
    rows = [np.hstack(arrays[i:i + columns]) for i in range(0, len(arrays), columns)]
    return save_png(np.vstack(rows[::-1]), path)


def s6_sheets(out):
    """The 2560 px sheets. before_after pairs S6_BEFORE's renders (left) with this build's (right)."""
    ret = lambda v: out / f"{v}_retracted.png"
    (out / "tiles").mkdir(exist_ok=True)
    ref, name, caption = S6_BEFORE
    before = {v: ref / name.format(v=v) if caption is None else
              s6_captioned_copy(ref / name.format(v=v), out / "tiles" / f"before_r4_{v}.png", f"{caption}: {S6_VIEWS[v][3]}")
              for v in ("hero", "side", "front_span", "rear_span", "engine34") if (ref / name.format(v=v)).exists()}
    sheets = {
        "sheet_s6_retracted.png": [ret(v) for v in ("hero", "side", "top", "front_span", "rear_span", "side_strike")],
        "sheet_s6_extended.png": [out / f"{v}_extended.png" for v in ("hero", "side", "top", "front", "rear_full", "rear")],
        "sheet_s6_install.png": [ret(v) for v in ("collar_in", "collar_out", "install_side", "tail_end",
                                                  "front_left", "rear_left")],
        "sheet_s6_ground_hangar.png": [ret(v) for v in ("side_pitch", "side_strike", "front_hangar", "top_hangar",
                                                        "install34", "rear")],
        "sheet_s6_before_after.png": [p for v in ("hero", "side", "front_span", "rear_span", "engine34")
                                      for p in (before.get(v), ret(v))],
    }
    return [s6_sheet(tiles, out / name) for name, tiles in sheets.items()]


# ---------- main ----------
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    spans, out, render, step, views = "retracted,extended", None, True, "6", "all"
    i = 0
    while i < len(argv):
        if argv[i] == "--span":
            spans, i = argv[i + 1], i + 1
        elif argv[i] == "--out":
            out, i = Path(argv[i + 1]), i + 1
        elif argv[i] == "--step":
            step, i = argv[i + 1], i + 1
        elif argv[i] == "--views":
            views, i = argv[i + 1], i + 1
        elif argv[i] == "--no-render":
            render = False
        else:
            raise SystemExit(f"unknown argument {argv[i]}")
        i += 1
    if step not in ("5", "6", "6.1") or views not in ("all", "orient", "sheets"):
        raise SystemExit("--step takes 5, 6 or 6.1, --views orient, all or sheets")
    if out is not None and not out.is_absolute():
        raise SystemExit("Pass an absolute --out: Blender resolves relative paths against its own cwd.")
    states = []
    for s in spans.split(","):
        e = {"retracted": 0.0, "extended": 1.0}.get(s)
        e = float(s) if e is None else e
        if not 0.0 <= e <= 1.0:
            raise SystemExit(f"--span {s}: extension must be within 0..1")
        states.append((e, "retracted" if e == 0 else "extended" if e == 1 else f"e{e:.2f}"))
    return states, out, render, step, views


def save_blend(out, label_):
    for o in bpy.data.collections["Colliders"].objects:
        o.display_type = "WIRE"
    bpy.context.view_layer.layer_collection.children["Centurion"].children["LOD1"].hide_viewport = True
    bpy.ops.wm.save_as_mainfile(filepath=str(out / f"centurion_{STEP}_{label_}.blend"), check_existing=False)


def main():
    states, out, render, step, views = parse_args()
    {"5": lambda: None, "6": configure_step6, "6.1": configure_step61}[step]()
    out = out or REPO / ".cache" / "art" / f"blockout_{STEP}"
    out.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0  # no .blend1 backups beside the numbered outputs
    default = bpy.data.collections.get("Collection")  # factory-startup cube, light and camera
    if default is not None:
        remove_objects(default.all_objects)
    if views == "sheets":  # recompose the step 6 sheets from the renders already in out
        print("CENTURION sheets: " + ", ".join(s6_sheets(out)))
        return
    for extension, label_ in states:
        objs, report = build(extension)
        masses = s6_masses(objs) if STEP.startswith("s6") else None  # balanced retracted, then back to this state's pose
        set_extension(objs, extension)
        metrics = measure(objs, extension, label_, report)
        if STEP.startswith("s6"):
            metrics["step6"] = s6_report(objs, masses)
            set_extension(objs, extension)
            save_blend(out, label_)  # before the render look restyles the materials
            if render:
                written = []
                if views == "all":
                    rig = build_render_rig()
                    workbench_look()
                    written = render_export_views(out, label_, rig, objs, report)
                metrics["renders"] = written + render_s6(out, label_, objs, views)
        elif render:
            rig = build_render_rig()
            metrics["renders"] = (render_views(out, label_, extension, rig)
                                  + (render_tail_strike(out, label_, rig, objs) if extension == 0 else [])
                                  + render_export_views(out, label_, rig, objs, report))
        (out / f"metrics_{label_}.json").write_text(json.dumps(metrics, indent=1, default=str))
        if not STEP.startswith("s6"):
            save_blend(out, label_)
        summary = {k: (v["pass"] if "pass" in v else v.get("value")) for k, v in metrics["checks"].items()}
        print(f"CENTURION {label_}: {json.dumps(metrics['overall_m'])} tris={metrics['total_tris']} "
              f"parts={metrics['part_count']} all_pass={metrics['all_pass']} {json.dumps(summary)}")
        if "step6" in metrics:
            for key, value in metrics["step6"].items():
                print(f"CENTURION {label_} {key}: {json.dumps(value, default=str)}")
        ts = metrics["checks"][TAIL_STRIKE_KEY]
        hit, mc = ts["first_contact"], ts["main_contact"]
        print(f"CENTURION {label_} tail strike: {'PASS' if ts['pass'] else 'FAIL'} {ts['value']} deg ({ts['limit']}); "
              f"first contact {hit['part']} at station {hit['station']}, {hit['height_m']} m up; main wheels at station "
              f"{mc['station']}, struts sagged {mc['strut_sag_m']} m")
    if STEP.startswith("s6") and render and views == "all":
        print("CENTURION sheets: " + ", ".join(s6_sheets(out)))


if __name__ == "__main__":
    main()
