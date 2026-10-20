"""The Centurion's flight deck interior (docs/COCKPIT-DESIGN.md): built inside a copy of the detailed retracted
composite, textured on three 2048 PBR atlases, the 2048 switch kit atlas, a 1024 label atlas and stock shared materials,
rendered for review and saved as an export blend for tools/export_blockout.py.

blender -b --factory-startup <copy of centurion_m4_retracted.blend> --python art/blender/cockpit/flightdeck.py --
    --out <absolute folder> [--views d,w,m,e,x] [--samples 48] [--no-bake]

Writes into --out: textures/cockpit_{panel,console,shell,kit}_{b,m,n,ao}.png (flightdeck_uv.py's three atlases and
flightdeck_kit.py's: albedo, metal-smoothness, normal, AO), cockpit_labels_{b,e}.png (the legends' colour and cutout, and
their glow), the screen's
scanline tile and the camera marker; metrics_flightdeck.json (triangles against BUDGET_TRIS, nothing in the screen's
frustum, the hatch openings against the seat's path, each atlas's texel density by paint class), the renders, and
flightdeck.blend: the interior alone in a "Centurion" collection with flightdeck_int as its root, which
tools/export_blockout.py exports to art/export_cockpit. It refuses a blend under art/ or .cache/art/ and never saves over
its input.

Parts, all in the composite's frame (Blender X is the aircraft's left, the nose to -Y, Z up), each with its origin on
its pivot and world axes:
- flightdeck_int (layer 14 in game): lining, floor, aft wall and racks, panel, consoles, pedestal, overhead, window and
  hatch trims, pedals, levers, the coaming; the three atlas slots, the kit's, and the stock aircraft_structure (walls and
  frames, tinted by vertex colour), Matte_black (shroud and glareshield) and hotas (grips).
- labels (14): the legends, scales and placards (flightdeck_labels.py) on the label atlas: stencils cut out
  (Centurion_cockpit_labels), the powered legends transparent and glowing (Centurion_cockpit_legends).
- band_bezel (14): the screen's housing and the master warning lamps' housings on its hood; the panel atlas, the lamps'
  lenses on Matte_black.
- hatch_liner_L, hatch_liner_R (14): each escape hatch's liner and handle, which authoring parents to its hatch.
- warning_lenses (3): the caution, warning, annunciator and master warning lamps' lit faces on the stock
  CockpitWarningLight, which the stock CockpitWarningLights shows only while it flashes.
- band (3): the screen, a transparent sheet on the stock glass_int copy with the scanline tile (Centurion_band).
- band_marker (3): the camera marker, on its own transparent copy (Centurion_band_marker).
- tacScreen (3): five of the six displays, each one whole page of the 1024 x 512 tac screen canvas (tacScreenDisplay).
- glass_int (3): the inner panes on the stock canopy_int, which cracks.
- stick_L, stick_R, throttle_1, throttle_2: empties, the pivots of the stock meshes authoring places by reference
  (stock_pivots): Cockpit.joysticks (local X pitch, Z roll in Unity) and Cockpit.throttles (local X).
- wing_display: an empty, the wing display's page (canvas_w by canvas_h metres), where authoring stands the plugin's
  canvas."""

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import flightdeck_layout as fl  # noqa: E402
import flightdeck_detail  # noqa: E402
import flightdeck_kit as fk  # noqa: E402
import flightdeck_labels as lb  # noqa: E402
import flightdeck_paint as fp  # noqa: E402
import flightdeck_uv as fuv  # noqa: E402
from m4 import nose, nose_exits, render, texture  # noqa: E402
from m4 import surface as sf  # noqa: E402
from m4.blockout import load_blockout  # noqa: E402

REPO = HERE.parents[2]
BUDGET_TRIS = 36000  # docs/COCKPIT-DESIGN.md "Budget": drawn only in cockpit view
# ATLAS_SLOT tags the builders' faces; flightdeck_uv.assign_slots splits them over the three PBR atlases
ATLAS_SLOT, DISPLAY_SLOT, GLASS_SLOT = "Centurion_cockpit", "tacScreenDisplay", "canopy_int"
BAND_SLOT, MARKER_SLOT = "Centurion_band", "Centurion_band_marker"
# The legends: stencils cut out (alpha test alone, a variant the game ships), the powered legends on a transparent
# emissive copy of the stock warning-lamp material (the game ships no cut-out emissive Lit variant)
LABEL_SLOT, LEGEND_SLOT = "Centurion_cockpit_labels", "Centurion_cockpit_legends"

# Paint classes (flightdeck_paint reads them from the baked class map).
LINING, FLOOR, PANEL, CONSOLE, FRAME, BEZEL, RACK, KNOB, METAL, HANDLE, GRIP, OVERHEAD, HATCH, STRUCT, HAZARD = range(1, 16)
SMOOTH_CLASSES = (LINING, GRIP)

WALL = 0.08  # the lining's depth under the skin: the hatch panels' inner faces sit there too (fl.HATCH_DEPTH)
# Lining rings: forward into the nose's taper, where the screen's lowest lines of sight meet it, coarse ahead of the
# panel (only the shroud's hole and the commander's seat see there) and fine over the crew.
LINING_RINGS = tuple(round(0.30 + 0.25 * i, 4) for i in range(20)) + (5.15,) + tuple(round(5.225 + 0.075 * i, 4) for i in range(24))
LINING_DEG_FWD = 5.625  # ahead of the footwell, where only the shroud's hole and the commander's seat see the lining
LINING_DEG = 1.875  # lining columns: a third of the hull's
AFT_S = 6.95  # the aft wall, just ahead of the nose part's joint at 7.0, where fuselage_F's end cap closes it

# The screen (owner, locked): a section of a vertical cylinder of radius BAND_R about the centreline at station
# BAND_AXIS_S, concave toward the crew, from z BAND_Z[0] to BAND_Z[1], its ends where the pilot's line 19.8 deg
# outboard meets it; the black bezel BEZEL_W wide and BEZEL_DEPTH deep toward the crew; the panel on the same
# cylinder PANEL_GAP behind it.
BAND_AXIS_S, BAND_R, BAND_EDGE_AZ = 7.30, 1.60, 19.8
BAND_Z = (4.80, 4.95)
BEZEL_W, BEZEL_DEPTH, PANEL_GAP = 0.018, 0.06, 0.01
MARKER_OPACITY = 0.5  # the camera marker's alpha on its transparent material (owner: 25% was almost invisible)
DISPLAY_Z = (4.51, 4.75)  # the displays' openings, all this tall, each as wide as its page's shape gives
BEZEL_SIDE, BEZEL_GAP = 0.02, 0.006  # a display bezel's frame either side of its opening; the panel between two bezels
PANEL_R = BAND_R + PANEL_GAP
PANEL_PHI = 40.0  # the panel's wings wrap round the band's axis to here, standing on the side consoles
PANEL_DEPTH = 0.08  # the panel's top and bottom lips run this far forward from its face
EDGE_R = 0.014  # the panel's and consoles' exposed edges are rounded to this radius
KNEE_Z, FOOTWELL_S = 4.40, 5.15  # the panel's lower edge under the screen; the footwell's front bulkhead
CONSOLE_X, CONSOLE_TOP, CONSOLE_S = 0.86, 4.35, (5.40, 6.90)  # side consoles: inner wall, top, stations
PEDESTAL_X, PEDESTAL_TOP, PEDESTAL_AFT = 0.21, 4.38, 6.55
OVERHEAD_X, OVERHEAD_S, OVERHEAD_DROP = 0.17, (5.62, 6.88), 0.07  # between the hatches, below the lining
STICK_AT = (1.02, 6.28)  # x outboard, station: on the console top
# x either side, station and height of each throttle's pivot, inside the pedestal: the KR-67 throttle's grip stands
# 0.293 to 0.397 m above its pivot, reaching 0.001 to 0.148 m inboard of it, so its grip rests on the quadrant
THROTTLE_AT = (0.01, 6.05, 4.142)
THROTTLE_GRIP_X = 0.075  # the grips' centres either side, over their slots in the quadrant
CANVAS = (1024, 512)  # the tac screen's render texture, pixels
# The canvas's whole pages, as the stock Alkyon's tac screen mesh maps them (its UV islands, which match the
# RectTransforms in Centurion_TacScreen.prefab once their scale and rotation apply): x0, y0, x1, y1 in canvas pixels from
# the bottom left, and whether the canvas draws the page turned 90 deg (its up toward the canvas's -x, its right toward
# +y). The Alkyon's second engine panel (595.7, 1.6, 803.4, 253.9) is empty on our canvas: its engines are gone.
PAGES = {
    "radar": ((2.8, 146.1, 585.7, 488.5), False),  # MainPanel: the radar and map
    "pfd": ((289.8, 2.6, 521.4, 143.8), True),  # BasicFlightInstrument
    "gauges": ((16.1, 2.3, 264.5, 143.4), True),  # StatusGauges: fuel, throttle, IR, mass, TWR
    "engines": ((595.7, 257.0, 810.6, 509.4), False),  # Engine Panel1: both engines
    "stores": ((811.8, 191.8, 1012.2, 504.9), False),  # weaponPanel: the Centurion's top view and its bays
}
PAGE_INSET = 1.5  # px kept off each page's edge, so filtering never samples its neighbour
# The wing display (owner): the Centurion's own page, not one of the tac screen canvas's: dark glass under a world-space
# canvas authoring places on the wing_display pivot, where the plugin draws the wing's span and state
# (src/Centurion/WingDisplay.cs). As narrow as the stores page, which the extended wing's plan still spans.
WING_PAGE, WING_ASPECT = "wing", 0.64
# One whole page per display, from the pilot's outboard end (+X) across: the wing display, the pilot's flight display
# and radar, the engines in the middle, the stores page and the commander's own flight display.
DISPLAY_ORDER = (WING_PAGE, "pfd", "radar", "engines", "stores", "pfd")


def page_aspect(key):
    """A page's width over its height as it reads upright."""
    if key == WING_PAGE:
        return WING_ASPECT
    (x0, y0, x1, y1), turned = PAGES[key]
    w, h = x1 - x0, y1 - y0
    return h / w if turned else w / h


def page_uv(key, u, v):
    """The canvas UV of the point (u, v) of a page read upright, u across from its left and v up from its bottom, 0 to 1."""
    (x0, y0, x1, y1), turned = PAGES[key]
    x0, y0, x1, y1 = x0 + PAGE_INSET, y0 + PAGE_INSET, x1 - PAGE_INSET, y1 - PAGE_INSET
    if turned:  # the page's up runs toward the canvas's -x, its right toward +y
        return (x1 - (x1 - x0) * v) / CANVAS[0], (y0 + (y1 - y0) * u) / CANVAS[1]
    return (x0 + (x1 - x0) * u) / CANVAS[0], (y0 + (y1 - y0) * v) / CANVAS[1]
Y0 = 22.475


def st(s):
    return s - Y0


# ---------------- the composite's exterior, for the glass's edge as each eye sees it ----------------
class Skin:
    def __init__(self, names):
        dg = bpy.context.evaluated_depsgraph_get()
        self.trees = []
        for n in names:
            o = bpy.data.objects[n]
            me = o.evaluated_get(dg).to_mesh()
            vs = [o.matrix_world @ v.co for v in me.vertices]
            mats = [o.data.materials[p.material_index].name if p.material_index < len(o.data.materials) else "" for p in me.polygons]
            self.trees.append((BVHTree.FromPolygons(vs, [tuple(p.vertices) for p in me.polygons]), mats))

    def cast(self, origin, d):
        best = None
        for tree, mats in self.trees:
            h = tree.ray_cast(origin, d)
            if h[0] is not None and (best is None or h[3] < best[3]):
                best = (h[0], h[1], mats[h[2]], h[3])
        return best

    def exits_glass(self, eye, d):
        h = self.cast(eye + d * 40, -d)
        return h is None or h[2] == "glass" or h[3] > 39.95


def direction(az, el, side):
    """Unit vector from an eye: az outboard positive (side +1 is the left seat, +X), el up positive."""
    a, e = math.radians(az), math.radians(el)
    return Vector((side * math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def eye(side):
    return Vector((side * fl.EYE_X, st(fl.EYE_S), fl.EYE_Z))


def glass_edges(skin):
    """Per seat, the lowest elevation each azimuth's ray leaves through the glass: {side: {az: el}}."""
    out = {}
    for side in (1, -1):
        e, edge = eye(side), {}
        for az in range(-70, 91, 5):
            edge[az] = 60.0
            for el10 in range(-350, 600, 5):
                if skin.exits_glass(e, direction(az, el10 / 10, side)):
                    edge[az] = el10 / 10
                    break
        out[side] = edge
    return out


def interp_edge(edge, az):
    pts = sorted(edge.items())
    if az <= pts[0][0]:
        return pts[0][1]
    for (a0, e0), (a1, e1) in zip(pts, pts[1:]):
        if az <= a1:
            return e0 + (e1 - e0) * (az - a0) / (a1 - a0)
    return pts[-1][1]


# ---------------- the screen's cylinder ----------------
def cyl(phi, z, r=BAND_R):
    """A point on a cylinder about the screen's axis: phi in degrees, positive toward +X, 0 straight ahead."""
    a = math.radians(phi)
    return Vector((r * math.sin(a), st(BAND_AXIS_S) - r * math.cos(a), z))


def cyl_coords(p):
    """(phi, radius) of a point about the screen's axis."""
    dy = st(BAND_AXIS_S) - p.y
    return math.degrees(math.atan2(p.x, dy)), math.hypot(p.x, dy)


def cyl_hit(origin, d, r=BAND_R):
    ox, oy = origin.x, origin.y - st(BAND_AXIS_S)
    a = d.x ** 2 + d.y ** 2
    b = 2 * (ox * d.x + oy * d.y)
    c = ox ** 2 + oy ** 2 - r ** 2
    t = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)
    return origin + d * t, t


def band_axis():
    """(x, y) of the screen's and panel's vertical axis."""
    return (0.0, st(BAND_AXIS_S))


def band_phi():
    edge, _ = cyl_hit(eye(1), direction(BAND_EDGE_AZ, 0.0, 1))
    return math.degrees(math.atan2(edge.x, st(BAND_AXIS_S) - edge.y))


# Seats whose eye the player's camera takes: only pilots[0] gets the player (Pilot.cs), and it sits left. The mission
# commander's eye never renders, so what it would see through the screen or past the panel doesn't matter.
VIEW_SEATS = (1,)


def in_band(c, phi_b, tol_deg=1.0, tol_z=0.02):
    """A point ahead of the screen that the pilot sees through it, with the screen grown by the tolerances."""
    top, bottom = BAND_Z[1], BAND_Z[0]
    for side in VIEW_SEATS:
        e = eye(side)
        d = (c - e).normalized()
        if d.y >= 0:
            continue
        p, t = cyl_hit(e, d)
        if (c - e).length <= t:
            continue
        a = math.degrees(math.atan2(p.x, st(BAND_AXIS_S) - p.y))
        if abs(a) <= phi_b + tol_deg and bottom - tol_z <= p.z <= top + tol_z:
            return True
    return False


def panel_top(edges, phi, phi_b):
    """The panel's top edge at phi: the bezel's under the screen; beyond the screen's ends, the glass's lower edge as
    the nearer eye sees it."""
    if abs(phi) <= phi_b:
        return BAND_Z[1] + BEZEL_W
    p = cyl(phi, 0.0, PANEL_R)
    side = 1 if p.x >= 0 else -1
    v = p - eye(side)
    az = math.degrees(math.atan2(side * v.x, -v.y))
    return min(fl.EYE_Z - 0.03, fl.EYE_Z + math.hypot(v.x, v.y) * math.tan(math.radians(interp_edge(edges[side], az))))


# ---------------- mesh helpers ----------------
def faces(part, rows, slot, cls, loop=False, smooth=False):
    """Quads between rows of points (a Grid, open or closed round), tagged; returns them."""
    g = sf.Grid(part.bm, rows, loop=loop)
    fs = g.faces()
    part.tag(fs, slot, cls)
    for f in fs:
        f.smooth = smooth
    return fs


def facing(fs, want):
    for f in fs:
        f.normal_update()
        if f.normal.dot(want if isinstance(want, Vector) else want(f)) < 0:
            f.normal_flip()
    return fs


def poly(part, pts, slot, cls, want):
    f = part.bm.faces.new([part.bm.verts.new(p) for p in pts])
    part.tag([f], slot, cls)
    return facing([f], want)


AX = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))


def box(part, a, b, slot, cls):
    """An axis-aligned box between two opposite corners."""
    lo = Vector([min(p, q) for p, q in zip(a, b)])
    hi = Vector([max(p, q) for p, q in zip(a, b)])
    return sf.box(part, (lo + hi) / 2, AX, hi - lo, slot, cls)


def lining_point(surf, s, a, off=0.0):
    return surf.point(s, a, -WALL + off)


def floor_angle(surf, s):
    """The +X angle where the lining comes down to the floor (0 where its whole section is under it)."""
    lo, hi = 0.0, 180.0
    if lining_point(surf, s, 0.0).z <= fl.FLOOR_Z:
        return 0.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if lining_point(surf, s, mid).z > fl.FLOOR_Z else (lo, mid)
    return (lo + hi) / 2


def lining_x(surf, s, z):
    """The lining's half width at station s and height z."""
    lo, hi = 0.0, 179.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if lining_point(surf, s, mid).z > z else (lo, mid)
    return lining_point(surf, s, (lo + hi) / 2).x


def plane(s, a):
    return Vector((s, math.radians(a) * 1.9))


PANE_STEP, PANE_STEP_EDGE = 0.06, 0.01  # the panes' outline spacing, and where it crosses the edge of the screen's view


def pane_outlines(surf, phi_b):
    """The four panes' outlines as (station, angle) points, straight between corners in (station, angle), every
    PANE_STEP and every PANE_STEP_EDGE where the outline passes from behind the screen to above it: the window trims
    in the screen's view go (main), and there their cut ends stop just behind the screen's hood."""
    out = []
    for side in (1, -1):
        for corners in nose.PANES:
            c = nose.resolve(surf, corners, side)
            pts = []
            for e in range(4):
                (s0, a0), (s1, a1) = c[e], c[(e + 1) % 4]
                length = (surf.point(s1, a1) - surf.point(s0, a0)).length
                n = max(2, math.ceil(length / PANE_STEP))
                edge = [(s0 + (s1 - s0) * t / n, a0 + (a1 - a0) * t / n) for t in range(n + 1)]
                for (sa, aa), (sb, ab) in zip(edge, edge[1:]):
                    seen = [in_band(lining_point(surf, s, a), phi_b) for s, a in ((sa, aa), (sb, ab))]
                    m = max(1, math.ceil(length / n / PANE_STEP_EDGE)) if seen[0] != seen[1] else 1
                    pts += [(sa + (sb - sa) * t / m, aa + (ab - aa) * t / m) for t in range(m)]
            out.append(pts)
    return out


# ---------------- the shell: lining, floor, aft wall, footwell ----------------
def lining_triangulation(surf, holes):
    """The lining's triangles in (station, angle), the hole outlines as constraints: ahead of the footwell's bulkhead
    the whole section round to the keel (180 deg) by LINING_DEG_FWD columns, aft of it down to the floor line by
    LINING_DEG columns. Returns the points as (station, angle) and the index triples outside every hole and, aft of
    the bulkhead, above the floor."""
    rings = list(LINING_RINGS)
    s0, s1 = rings[0], rings[-1]
    fwd = [s for s in rings if s <= FOOTWELL_S + 1e-6]
    aft = [s for s in rings if s > FOOTWELL_S + 1e-6]
    edge = {s: floor_angle(surf, s) for s in rings}
    flat_holes = [[plane(s, a) for s, a in h] for h in holes]
    sb = fwd[-1]  # the bulkhead's ring: round to the keel, then up to the floor line
    boundary = ([(s0, a) for a in np.linspace(-180.0, 180.0, 97)] + [(s, 180.0) for s in fwd[1:]] + [(sb, edge[sb])]
                + [(s, edge[s]) for s in aft[:-1]] + [(s1, a) for a in np.linspace(edge[s1], -edge[s1], 80)]
                + [(s, -edge[s]) for s in aft[-2::-1]] + [(sb, -edge[sb])] + [(s, -180.0) for s in fwd[:0:-1]])
    steiner = []
    for s in rings[1:-1]:
        step = LINING_DEG_FWD if s < sb - 1e-6 else LINING_DEG
        top = 180.0 if s < sb - 1e-6 else edge[s]
        n = math.floor(top / step - 0.3)
        for k in range(-n, n + 1):
            q = plane(s, k * step)
            if not any(nose_exits.inside(q, h) or nose_exits.near(q, h, 0.03) for h in flat_holes):
                steiner.append((s, k * step))
    pts = boundary + [p for h in holes for p in h] + steiner
    flat = [plane(s, a) for s, a in pts]
    nb = len(boundary)
    cons, i0 = [], nb
    for h in holes:
        cons += [(i0 + i, i0 + (i + 1) % len(h)) for i in range(len(h))]
        i0 += len(h)
    # Holes may overlap (the screen's footprint runs onto the panes): the triangulation adds the crossing points,
    # so the points come back from its output, and a triangle inside any hole goes.
    co, _, tris, _, _, _ = delaunay_2d_cdt(flat, cons, [list(range(nb))], 1, 1e-9)
    pts = [(c.x, math.degrees(c.y / 1.9)) for c in co]
    out = []
    for t in tris:
        c2 = sum((co[i] for i in t), Vector((0, 0))) / 3
        if any(nose_exits.inside(c2, h) for h in flat_holes):
            continue
        c3 = sum((lining_point(surf, *pts[i]) for i in t), Vector()) / 3
        if c3.z < fl.FLOOR_Z and c3.y > st(FOOTWELL_S):
            continue
        out.append(list(t))
    return pts, out


APERTURE_GROW = 0.004  # the shroud starts this far outside the screen's edge, under its bezel


def aperture(phi_b):
    """The screen's edge grown by APERTURE_GROW, round it from its +X top corner: points on its cylinder."""
    g = APERTURE_GROW
    ph = phi_b + math.degrees(g / BAND_R)
    top, bottom = BAND_Z[1] + g, BAND_Z[0] - g
    n = 48
    ring = [cyl(ph - 2 * ph * k / n, top) for k in range(n + 1)]
    ring += [cyl(-ph, top + (bottom - top) * k / 3) for k in (1, 2)]
    ring += [cyl(-ph + 2 * ph * k / n, bottom) for k in range(n + 1)]
    ring += [cyl(ph, bottom + (top - bottom) * k / 3) for k in (1, 2)]
    return ring


def screen_footprint(surf, phi_b):
    """Where the pilot's lines of sight through the screen's grown edge meet the lining's surface, unbroken (near its
    ends the screen looks out where the side panes are): (station, angle) points, by ray casts."""
    return [sa for _, sa in sight_hits(surf, aperture(phi_b), -WALL)]


def sight_hits(surf, through, off):
    """Where the pilot's lines of sight through each point meet the fuselage's surface off metres out from the skin,
    unbroken by any hole: (the hit on the lining's triangulation, its (station, angle)) per point, by ray casts."""
    pts, tris = lining_triangulation(surf, [])
    co = [surf.point(s, a, off) for s, a in pts]
    tree = BVHTree.FromPolygons(co, tris)
    e = eye(1)
    out = []
    for p in through:
        d = (p - e).normalized()
        loc, _, i, _ = tree.ray_cast(p, d)
        if loc is None:
            raise SystemExit(f"sight_hits: the line through {tuple(round(c, 3) for c in p)} misses the surface")
        a, b, c = (co[k] for k in tris[i])
        w = barycentric(loc, a, b, c)
        out.append((loc, tuple(sum(w[j] * pts[tris[i][j]][m] for j in range(3)) for m in (0, 1))))
    return out


def barycentric(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11, d20, d21 = v0.dot(v0), v0.dot(v1), v1.dot(v1), v2.dot(v0), v2.dot(v1)
    den = d00 * d11 - d01 * d01
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return (1 - v - w, v, w)


def build_lining(part, surf, holes):
    """The lining WALL under the skin over the whole flight deck, open only at the panes, the hatches and the screen's
    footprint (the last hole of holes), so the deck is closed from every seat and the aft wall."""
    bm = part.bm
    pts, tris = lining_triangulation(surf, holes)
    verts = {}

    def vert(i):
        if i not in verts:
            verts[i] = bm.verts.new(lining_point(surf, *pts[i]))
        return verts[i]

    made = []
    for idx in tris:
        f = bm.faces.new([vert(i) for i in idx])
        s, a = sum(pts[i][0] for i in idx) / 3, sum(pts[i][1] for i in idx) / 3
        f.normal_update()
        if f.normal.dot(surf.normal(s, a)) > 0:
            f.normal_flip()
        f.smooth = True
        made.append(f)
    part.tag(made, ATLAS_SLOT, LINING)
    s0 = LINING_RINGS[0]  # its front end closed, in the radome's tip
    front = [bm.verts.new(lining_point(surf, s0, a)) for a in np.linspace(-180.0, 180.0, 96, endpoint=False)]
    part.tag(facing(sf.cap(bm, front), Vector((0, 1, 0))), ATLAS_SLOT, LINING)


def build_shroud(part, surf, footprint, phi_b):
    """The screen's shroud: walls from just outside its edge along the pilot's lines of sight to the lining's hole
    round its footprint. Edge-on from the pilot's eye behind the bezel, they close the view into the nose from
    anywhere else; through the screen the world shows inside them."""
    e = eye(1)
    axis = (cyl(0.0, sum(BAND_Z) / 2) - e).normalized()
    ring = aperture(phi_b)
    near = [p + (p - e).normalized() * 0.002 for p in ring]
    far = [lining_point(surf, s, a) for s, a in footprint]
    bm, fs = part.bm, []
    vn, vf = [bm.verts.new(p) for p in near], [bm.verts.new(p) for p in far]
    for i in range(len(ring)):
        j = (i + 1) % len(ring)
        f = bm.faces.new((vn[i], vn[j], vf[j], vf[i]))
        c = f.calc_center_median()
        toward = e + axis * (c - e).dot(axis) - c
        fs += facing([f], toward)
    part.tag(fs, ATLAS_SLOT, PANEL)


def build_floor(part, surf):
    """The deck floor from the footwell's bulkhead to the aft wall, out to the lining; the footwell's bulkhead from the
    floor to the panel's lower edge; the aft wall closing the lining's ring."""
    up, aft, fwd = Vector((0, 0, 1)), Vector((0, 1, 0)), Vector((0, -1, 0))
    rows = []
    for s in [FOOTWELL_S + (AFT_S - FOOTWELL_S) * i / 9 for i in range(10)]:
        w = lining_x(surf, s, fl.FLOOR_Z + 0.002)
        rows.append([Vector((x, st(s), fl.FLOOR_Z)) for x in np.linspace(-w, w, 7)])
    facing(faces(part, rows, ATLAS_SLOT, FLOOR), up)
    w0, w1 = lining_x(surf, FOOTWELL_S, fl.FLOOR_Z + 0.002), lining_x(surf, FOOTWELL_S, KNEE_Z)
    y = st(FOOTWELL_S)
    poly(part, [(-w0, y, fl.FLOOR_Z), (w0, y, fl.FLOOR_Z), (w1, y, KNEE_Z), (-w1, y, KNEE_Z)], ATLAS_SLOT, PANEL, aft)
    a = floor_angle(surf, AFT_S)
    ring = [lining_point(surf, AFT_S, x) for x in np.linspace(-a, a, 37)]
    ring = [Vector((p.x, p.y, max(p.z, fl.FLOOR_Z))) for p in ring]
    bm = part.bm
    vs = [bm.verts.new(p) for p in ring]
    fs = sf.cap(bm, vs)
    part.tag(fs, ATLAS_SLOT, RACK)
    facing(fs, fwd)


# ---------------- the panel, the screen and the displays ----------------
def build_panel(part, edges, phi_b):
    """The panel on the screen's cylinder PANEL_GAP behind the screen: under the screen from KNEE_Z to the screen's
    bottom, its wings beyond the screen's ends from the floor (or the console top) to the glass's edge, with lips
    running PANEL_DEPTH forward along its top and its lower edge, its exposed edges rounded to EDGE_R."""
    cols = [-PANEL_PHI + 0.5 * k for k in range(int(4 * PANEL_PHI) + 1)]

    def span(phi):
        x = abs(cyl(phi, 0, PANEL_R).x)
        if abs(phi) <= phi_b:
            return KNEE_Z, BAND_Z[0]
        return (CONSOLE_TOP if x > CONSOLE_X else fl.FLOOR_Z), panel_top(edges, phi, phi_b)

    def profile(p, wing):
        """The panel's section at p as (radius, height) points round its rounded edge onto a lip, and that edge's
        centre: under the screen from the lower lip up the face; on a wing from its foot up the face over the top."""
        q = [(PANEL_R + EDGE_R * (1 - math.cos(math.radians(t))), math.sin(math.radians(t))) for t in (0, 30, 60, 90)]
        if wing:
            lo, top = span(p)
            return ([(PANEL_R, lo)] + [(r, top - EDGE_R + EDGE_R * u) for r, u in q] + [(PANEL_R + PANEL_DEPTH, top)],
                    (PANEL_R + EDGE_R, top - EDGE_R))
        return ([(PANEL_R + PANEL_DEPTH, KNEE_Z)] + [(r, KNEE_Z + EDGE_R - EDGE_R * u) for r, u in q[::-1]]
                + [(PANEL_R, BAND_Z[0])], (PANEL_R + EDGE_R, KNEE_Z + EDGE_R))

    def outward(f, wing):
        c = f.calc_center_median()
        phi, _ = cyl_coords(c)
        r, z = profile(phi, wing)[1]
        return c - cyl(phi, z, r)

    for lo_side in (-1, 0, 1):
        sel = [p for p in cols if (abs(p) <= phi_b + 1e-6 if lo_side == 0 else (p * lo_side > phi_b - 1e-6))]
        # each section runs to the screen's end exactly, where its neighbour starts, not to the last column short of it
        ends = [-phi_b, phi_b] if lo_side == 0 else [lo_side * phi_b]
        sel = sorted(set(ends + sel), key=lambda p: p * (lo_side or 1))
        wing = lo_side != 0  # under the screen the world shows over the panel's top: no lip there
        n = len(profile(sel[0], wing)[0])
        rows = [[cyl(p, profile(p, wing)[0][k][1], profile(p, wing)[0][k][0]) for p in sel] for k in range(n)]
        facing(faces(part, rows, ATLAS_SLOT, PANEL), lambda f, w=wing: outward(f, w))
        if wing:
            for p in (lo_side * phi_b, lo_side * PANEL_PHI):  # the wing's ends: below the knee edge, and outboard
                z0, z1 = (fl.FLOOR_Z, KNEE_Z) if abs(p) == phi_b else span(p)
                q = [cyl(p, z0, PANEL_R), cyl(p, z1, PANEL_R), cyl(p, z1, PANEL_R + PANEL_DEPTH), cyl(p, z0, PANEL_R + PANEL_DEPTH)]
                n = (cyl(p + 1, 0, PANEL_R) - cyl(p, 0, PANEL_R)) * math.copysign(1.0, p)
                poly(part, q, ATLAS_SLOT, PANEL, -n if abs(p) == phi_b else n)  # the knee well's wall faces in


def build_glareshield(part, skin, edges, phi_b):
    """Over each panel wing, a shelf from the top lip's front edge forward along the nearer eye's line over it to just
    short of the windscreen's base: edge-on from the eye, it closes the space ahead of the panel from any other head
    position. Faces the screen sees through are left out."""
    for sgn in (1, -1):
        cols = [sgn * (phi_b + (PANEL_PHI - phi_b) * k / 24) for k in range(25)]
        near_row, far_row = [], []
        for phi in cols:
            p = cyl(phi, panel_top(edges, phi, phi_b), PANEL_R + PANEL_DEPTH)
            d = (p - eye(sgn)).normalized()
            hit = skin.cast(p + d * 0.01, d)
            q = hit[0] - d * 0.12 if hit else p + d * 0.5
            near_row.append(p)
            far_row.append(q)
        fs = facing(faces(part, [near_row, far_row], ATLAS_SLOT, PANEL), Vector((0, 0, 1)))
        drop = [f for f in fs if any(in_band(p, phi_b, 0.0, 0.0) for p in [v.co for v in f.verts] + [f.calc_center_median()])]
        bmesh.ops.delete(part.bm, geom=drop, context="FACES")


def build_band(phi_b, parts):
    """The screen sheet, its bezel (BEZEL_W wide, BEZEL_DEPTH deep toward the crew) and the camera marker in its
    bottom corner at the pilot's end (owner, round 4)."""
    top, bottom = BAND_Z[1], BAND_Z[0]
    n = 48
    angles = [-phi_b + 2 * phi_b * k / n for k in range(n + 1)]
    sheet = parts["band"]
    fs = faces(sheet, [[cyl(a, bottom) for a in angles], [cyl(a, top) for a in angles]], BAND_SLOT, 0)
    facing(fs, lambda f: Vector((-f.calc_center_median().x, st(BAND_AXIS_S) - f.calc_center_median().y, 0)))
    toward = lambda f: Vector((-f.calc_center_median().x, st(BAND_AXIS_S) - f.calc_center_median().y, 0))
    build_screen_housing(parts["band_bezel"], phi_b)
    # the marker: a quad just in front of the sheet, inside the bezel at the +X end, UV 0..1 over the marker texture
    mk = parts["band_marker"]
    w, h = 0.085, 0.022
    a1 = phi_b - math.degrees(0.012 / BAND_R)
    a0 = a1 - math.degrees(w / BAND_R)
    z0 = bottom + 0.008
    q = [cyl(a1, z0, BAND_R - 0.003), cyl(a0, z0, BAND_R - 0.003), cyl(a0, z0 + h, BAND_R - 0.003), cyl(a1, z0 + h, BAND_R - 0.003)]
    f = mk.bm.faces.new([mk.bm.verts.new(p) for p in q])
    mk.tag([f], MARKER_SLOT, 0)
    facing([f], toward)
    uv = mk.bm.loops.layers.uv.verify()
    for loop, (u, v) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop[uv].uv = (u, v)
    mk.uv_done = True


# The master warning lamps (owner: "bigger, and horizontal ... they should have a thing when they are off"), built as the
# KR-67 builds its own: a housing in the cockpit mesh with the lamp's face laid over it on a renderer of its own, which the
# stock CockpitWarningLights shows only while it flashes. One under the screen on each seat's line straight ahead (the
# pilot's eye meets the screen at about 20 deg; owner: "the warning lights should be under the pano display"), filling
# the height from the display bezels' top edge to the screen's lower edge, the frame's 18 mm bar and the gap under it:
# the KR-67 strips loose on the coaming read as lamps floating in the windows, and on the glareshield's lip the owner
# wanted them lower. Each housing (the screen housing's, band_bezel, in its paint) stands WARNING_LAMP_PROUD in front of
# the frame's face and runs back to the display bezels' face, so it sits on the bar and on the bezels' tops, a bezel ring
# round a recessed lens of dark glass (Matte_black) that the lamp's face covers when lit (warning_lenses): a horizontal
# strip about twice the KR-67 lamp's 23 x 38 mm face.
WARNING_LAMP_PHI = 20.0
WARNING_LAMP_BODY = (0.096, 0.029)  # the housing: along the bar, and tall, up to BAND_Z[0]
WARNING_LAMP_PROUD = 0.004  # any more and the housing's lower edge hides the pages' tops from a raised head
WARNING_LAMP_LENS = (0.084, 0.026)  # the lens window in the bezel ring, which stands RING proud of the lens
WARNING_LAMP_RING = 0.003
WARNING_LAMP_FACE = (0.082, 0.024)  # the lit face, just over the lens


def build_warning_lamps(part, lenses):
    """The two master warning lamps under the screen (WARNING_LAMP_*): housings and lenses on part, lit faces on lenses."""
    import flightdeck_detail as fdd
    fd = sys.modules[__name__]
    r_in = BAND_R - BEZEL_DEPTH
    w, h = WARNING_LAMP_BODY
    lw, lh = WARNING_LAMP_LENS
    bottom = BAND_Z[0] - h  # a millimetre over the display bezels' top (DISPLAY_Z[1] + 0.02)
    front = r_in - WARNING_LAMP_PROUD
    d = PANEL_R - BEZEL_HOUSING - front  # back to the display bezels' face
    for side in (1, -1):
        a = math.radians(side * WARNING_LAMP_PHI)
        along = Vector((math.cos(a), math.sin(a), 0.0))
        toward = toward_point(cyl(side * WARNING_LAMP_PHI, bottom))
        base = cyl(side * WARNING_LAMP_PHI, bottom, front)  # the face's bottom middle
        centre = base - toward * (d / 2) + Vector((0, 0, h / 2))
        # depth away from the crew: sf.box turns its end caps outward only on a left-handed (x, y, z)
        fdd.cbox(part, fd, centre, (along, -toward, Vector((0, 0, 1))), (w, d, h), BEZEL, c=0.003)
        face_mid = base + Vector((0, 0, h / 2))
        for du, dv, sw, sh in ((0, (lh + h) / 4, w, (h - lh) / 2), (0, -(lh + h) / 4, w, (h - lh) / 2),
                               ((lw + w) / 4, 0, (w - lw) / 2, lh), (-(lw + w) / 4, 0, (w - lw) / 2, lh)):
            fdd.cbox(part, fd, face_mid + along * du + Vector((0, 0, dv)) + toward * (WARNING_LAMP_RING / 2),
                     (along, -toward, Vector((0, 0, 1))), (sw, WARNING_LAMP_RING, sh), BEZEL, c=0.0008)
        def quad(into, lift, rw, rh):
            """A rectangle rw by rh on the face's middle, lift toward the crew, on into."""
            pts = [face_mid + toward * lift + along * (sx * rw / 2) + Vector((0, 0, sy * rh / 2))
                   for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            return facing([into.bm.faces.new([into.bm.verts.new(p) for p in pts])], toward)

        part.tag(quad(part, 0.0003, lw, lh), fuv.MATTE_SLOT, BEZEL)  # the dark lens
        lenses.tag(quad(lenses, 0.0008, *WARNING_LAMP_FACE), fdd.WARNING_SLOT, KNOB)  # the lit face


BEZEL_COLS = 24  # columns along the screen frame's long edges: a chord of 2.4 deg sags 0.3 mm on its radius
HOOD_REACH = 0.042  # how far the hood over the screen reaches toward the crew from the bezel's face
HOOD_CREST = (0.028, 0.010)  # the hood's highest line: toward the crew from the bezel's face, above the frame's top


def build_screen_housing(part, phi_b):
    """The screen's housing on band_bezel: its frame BEZEL_W wide (BEZEL_DEPTH deep toward the crew) swept round the
    opening as one mitred profile, from the glass out: a wall back from the glass with a step out, an inner chamfer to
    the frame's face, the face, its outer edge rounded into the rims back to the panel; a hood over the top reaching
    HOOD_REACH toward the crew with a rolled lip, above every line of sight through the screen; bolts along the face."""
    top, bottom = BAND_Z[1], BAND_Z[0]
    r_in = BAND_R - BEZEL_DEPTH
    da = math.degrees(BEZEL_W / BAND_R)
    bm = part.bm

    def ring(grow_in, grow_out, r, outer=False):
        """The opening (or with outer, the frame's outline) grown by grow metres, at radius r: points round it, the bottom
        edge from +phi to -phi then the top edge back."""
        g = grow_out if outer else grow_in
        ph = phi_b + (da if outer else 0.0) + math.degrees(g / BAND_R)
        lo = bottom - (BEZEL_W if outer else 0.0) - g
        hi = top + (BEZEL_W if outer else 0.0) + g
        cols = [ph - 2 * ph * k / BEZEL_COLS for k in range(BEZEL_COLS + 1)]
        return [cyl(a, lo, r) for a in cols] + [cyl(a, hi, r) for a in cols[::-1]]

    prof = [ring(0.0, 0, BAND_R), ring(0.0, 0, r_in + 0.030), ring(0.003, 0, r_in + 0.030), ring(0.003, 0, r_in + 0.004),
            ring(0.007, 0, r_in), ring(0, -0.004, r_in, True), ring(0, -0.0012, r_in + 0.0012, True), ring(0, 0.0, r_in + 0.004, True),
            ring(0, 0.0, PANEL_R, True)]
    g = sf.Grid(bm, prof, loop=True)
    frame = g.faces()
    front = g.F[4, BEZEL_COLS // 2]  # on the face, mid bottom
    front.normal_update()
    if front.normal.dot(toward_point(front.calc_center_median())) < 0:
        for f in frame:
            f.normal_flip()
    part.tag(frame, ATLAS_SLOT, BEZEL)
    # the hood: a strip over the top, its section from the rim forward and up, a rolled lip, back under to the face
    T = top + BEZEL_W
    sec = [(r_in + 0.004, T), (r_in - HOOD_CREST[0], T + HOOD_CREST[1]), (r_in - HOOD_REACH + 0.004, T + 0.008), (r_in - HOOD_REACH, T + 0.002),
           (r_in - HOOD_REACH + 0.006, T - 0.003), (r_in, T - 0.0025)]
    ph = phi_b + da
    cols = [ph - 2 * ph * k / BEZEL_COLS for k in range(BEZEL_COLS + 1)]
    hood = faces(part, [[cyl(a, z, r) for a in cols] for r, z in sec], ATLAS_SLOT, BEZEL)
    for a in (cols[0], cols[-1]):
        hood.append(bm.faces.new([bm.verts.new(cyl(a, z, r)) for r, z in sec]))
    for f in hood:
        c = f.calc_center_median()
        f.normal_update()
        phi_c, _ = cyl_coords(c)
        if f.normal.dot(c - cyl(phi_c, T + 0.003, r_in - HOOD_REACH / 2)) < 0:
            f.normal_flip()
    part.tag(hood, ATLAS_SLOT, BEZEL)
    # bolts along the face: ten on each long edge, two on each end
    zc = BEZEL_W - 0.0105
    for z in (top + zc, bottom - zc):
        for k in range(10):
            a = -phi_b + 2 * phi_b * (k + 0.5) / 10
            p = cyl(a, z, r_in)
            sf.revolve_axis(part, ((0.0024, 0.0), (0.0022, 0.0010), (0.0, 0.0016)), p, toward_point(p), 6, ATLAS_SLOT, METAL)
    for sgn in (1, -1):
        for z in (bottom + 0.035, top - 0.035):
            p = cyl(sgn * (phi_b + da / 2 + math.degrees(0.0015 / BAND_R)), z, r_in)
            sf.revolve_axis(part, ((0.0024, 0.0), (0.0022, 0.0010), (0.0, 0.0016)), p, toward_point(p), 6, ATLAS_SLOT, METAL)


def display_page(key):
    """The width of page key's lit face on the glass: the opening's height less PAGE_MARGIN top and bottom, at its aspect."""
    return (DISPLAY_Z[1] - DISPLAY_Z[0] - 2 * PAGE_MARGIN) * page_aspect(key)


def display_opening(key):
    """The width at the panel's radius of the opening that holds page key with PAGE_MARGIN of dark glass either side of
    it on the glass's radius."""
    return (display_page(key) + 2 * PAGE_MARGIN) * PANEL_R / DISPLAY_GLASS_R


def display_layout():
    """Each display of DISPLAY_ORDER as (centre angle in degrees, opening width), from the +X end: bezels BEZEL_GAP apart,
    the row centred under the screen."""
    spans = [display_opening(k) + 2 * BEZEL_SIDE for k in DISPLAY_ORDER]
    x = (sum(spans) + BEZEL_GAP * (len(spans) - 1)) / 2  # arc, metres toward +X from straight ahead
    out = []
    for key, span in zip(DISPLAY_ORDER, spans):
        out.append((math.degrees((x - span / 2) / PANEL_R), display_opening(key)))
        x -= span + BEZEL_GAP
    return out


DISPLAY_NAMES = {"pfd": "PFD", "radar": "RADAR", "engines": "ENG", "stores": "STORES", "gauges": "FUEL", WING_PAGE: "WING"}
BEZEL_HOUSING = 0.03  # how far the displays' bezels stand toward the crew
# The displays' glass, 5 mm behind the bezels' inner chamfer, and the dark margin round each lit page on it: a deeper
# well's lip hid the pages' edges from the seats (owner, in game); check_display_uvs.py holds the margin clear of the
# bezels from both seats' head positions.
DISPLAY_GLASS_R = PANEL_R - BEZEL_HOUSING + 0.008
PAGE_MARGIN = 0.008


def toward_point(p):
    """The horizontal direction from a point toward the screen's and panel's axis: the way the panel faces."""
    return Vector((-p.x, st(BAND_AXIS_S) - p.y, 0)).normalized()
KEY_LEGENDS = {"pfd": ("MENU", "BARO", "MINS", "FPV", "HSI", "BRT"), "radar": ("MAP", "PLAN", "RNG -", "RNG +", "TFC", "WX"),
               "engines": ("ENG", "FUEL", "HYD", "ELEC", "GEN", "BRT"), "stores": ("STRS", "BAY", "SEL", "ARM", "JETT", "BRT"),
               "gauges": ("FUEL", "THR", "IR", "MASS", "TWR", "BRT"), WING_PAGE: ("PLAN", "SPAN", "AUTO", "TEAR", "TEST", "BRT")}


def build_displays(parts, labels):
    """The six displays on the panel (five on tacScreen): each opening is its page's shape (display_layout), and the page of
    the canvas it carries (DISPLAY_ORDER) sits whole and upright in it on DISPLAY_GLASS_R, PAGE_MARGIN of dark glass
    (Matte_black, flightdeck_int) round it; the wing display's opening all dark glass, its page the plugin's canvas;
    their bezels, the kit's for that page shape, with a row of keys under each (flightdeck_int), the keys' backlit
    legends and each display's name under it."""
    scr, deck = parts["tacScreen"], parts["flightdeck_int"]
    uv = scr.bm.loops.layers.uv.verify()
    z0, z1 = DISPLAY_Z
    m, r_face = PAGE_MARGIN, DISPLAY_GLASS_R
    toward = lambda f: Vector((-f.calc_center_median().x, st(BAND_AXIS_S) - f.calc_center_median().y, 0))
    for (ac, w), key in zip(display_layout(), DISPLAY_ORDER):
        dw = math.degrees(w / PANEL_R)
        dp = math.degrees(display_page(key) / r_face)
        wide = [ac + dw / 2 - dw * k / 4 for k in range(5)]
        if key == WING_PAGE:
            glass = [[[cyl(c, z, r_face) for c in wide] for z in (z0, z1)]]
        else:
            cols = [ac + dp / 2 - dp * k / 4 for k in range(5)]  # from the +X end: the page's left edge
            fs = facing(faces(scr, [[cyl(c, z0 + m, r_face) for c in cols], [cyl(c, z1 - m, r_face) for c in cols]], DISPLAY_SLOT, 0),
                        toward)
            for f in fs:
                for loop in f.loops:
                    p = loop.vert.co
                    phi, _ = cyl_coords(p)
                    loop[uv].uv = page_uv(key, (ac + dp / 2 - phi) / dp, (p.z - z0 - m) / (z1 - z0 - 2 * m))
            # the dark glass round the page: strips over and under it the opening's width, and either side of it
            glass = [[[cyl(c, z, r_face) for c in wide] for z in zs] for zs in ((z0, z0 + m), (z1 - m, z1))]
            glass += [[[cyl(c, z, r_face) for c in cs] for z in (z0 + m, z1 - m)]
                      for cs in ((ac + dw / 2, ac + dp / 2), (ac - dp / 2, ac - dw / 2))]
        for rows in glass:
            facing(faces(deck, rows, fuv.MATTE_SLOT, BEZEL), toward)
        deck.kit.place_turned(deck, "bezel_" + key, ac)  # its bezel, keys and screws (flightdeck_kit.model_bezel)
        rr = PANEL_R - BEZEL_HOUSING
        keys = [cyl(ac + dw / 2 - dw * (k + 0.5) / 6, z0 - 0.017, rr - 0.008) for k in range(6)]
        r = math.radians(ac)
        inward = Vector((-math.sin(r), math.cos(r), 0))
        labels.row(KEY_LEGENDS[key], keys, inward, Vector((0, 0, 1)), cap=0.0032, rgb=lb.LIT_DIM, lit=lb.LIT_GREEN, axis=band_axis())
        build_key_rail(deck, labels, ac, key, w)


RAIL_Z = (KNEE_Z + 0.006, DISPLAY_Z[0] - 0.032)  # under each display's bezel, down to the panel's knee edge
RAIL_PROUD, PAD_PROUD = 0.005, 0.004  # the rail's step off the panel, its pads' off the rail
RAIL_SEAM = 0.004  # the recessed seam between neighbouring sections


def curved_step(part, a0, a1, z0, z1, r, proud, ch, cls, cols=4):
    """A plate on the panel's cylinder from angle a0 to a1 and height z0 to z1, its face proud of radius r, its top and
    bottom edges chamfered ch, its ends square."""
    prof = [(z0, r), (z0 + ch, r - proud), (z1 - ch, r - proud), (z1, r)]
    angles = [a0 + (a1 - a0) * k / cols for k in range(cols + 1)]
    back = cyl((a0 + a1) / 2, (z0 + z1) / 2, r + 0.05)
    fs = faces(part, [[cyl(a, z, rr) for a in angles] for z, rr in prof], ATLAS_SLOT, cls)
    for a in (a0, a1):
        fs.append(part.bm.faces.new([part.bm.verts.new(cyl(a, z, rr)) for z, rr in prof]))
    part.tag(fs, ATLAS_SLOT, cls)
    return facing(fs, lambda f: f.calc_center_median() - back)


def build_key_rail(deck, labels, ac, key, w):
    """Under a display's bezel (its opening w wide), a stepped rail section as wide as the bezel: a plate RAIL_PROUD off
    the panel with a seam to its neighbours, the display's name in its middle, a raised pad either side with two of the
    kit's pushbuttons on one and annunciator lamps (three, or two on a narrow display) on the stock warning-lamp
    material on the other."""
    import flightdeck_detail as fdd
    fd = sys.modules[__name__]
    span = w + 2 * BEZEL_SIDE
    half = math.degrees((span / 2 + (BEZEL_GAP - RAIL_SEAM) / 2) / PANEL_R)
    z0, z1 = RAIL_Z
    zm = (z0 + z1) / 2
    curved_step(deck, ac - half, ac + half, z0, z1, PANEL_R, RAIL_PROUD, 0.002, PANEL)
    pad_m = min(0.075, (span - 0.07) / 2)
    pad_w, inset = math.degrees(pad_m / PANEL_R), math.degrees(0.006 / PANEL_R)
    lamps = (-1, 0, 1) if pad_m >= 0.07 else (-0.5, 0.5)
    face = PANEL_R - RAIL_PROUD - PAD_PROUD
    for sgn in (1, -1):
        edge = ac + sgn * (half - inset)
        curved_step(deck, min(edge, edge - sgn * pad_w), max(edge, edge - sgn * pad_w), z0 + 0.012, z1 - 0.012, PANEL_R - RAIL_PROUD,
                    PAD_PROUD, 0.0015, PANEL, cols=1)
        mid = edge - sgn * pad_w / 2
        step = math.degrees(0.022 / PANEL_R)
        for k in ((-0.8, 0.8) if sgn > 0 else lamps):
            a = mid + k * step
            n = toward_point(cyl(a, zm, face))
            if sgn > 0:
                fdd.button(deck, fd, cyl(a, zm, face), n, Vector((0, 0, 1)))
            else:
                fdd.warning_lens(deck, fd, cyl(a, zm, face) + n * 0.0003, n)
    inward = toward_point(cyl(ac, zm, PANEL_R))
    labels.add(DISPLAY_NAMES[key], cyl(ac, zm, PANEL_R - RAIL_PROUD), inward, Vector((0, 0, 1)), cap=0.008, axis=band_axis())


# ---------------- furniture ----------------
def build_consoles(part, surf, edges, phi_b):
    """The side consoles along each wall from CONSOLE_S, inner wall at CONSOLE_X, out to the lining; the centre
    pedestal from the panel to PEDESTAL_AFT with its throttle quadrant; the overhead console between the hatches."""
    s0, s1 = CONSOLE_S
    for side in (1, -1):
        rows = []
        stations = [s0 + (s1 - s0) * i / 15 for i in range(16)]
        for s in stations:
            xo = lining_x(surf, s, CONSOLE_TOP)
            rows.append([Vector((side * x, st(s), CONSOLE_TOP)) for x in np.linspace(CONSOLE_X + EDGE_R, xo, 6)])
        facing(faces(part, rows, ATLAS_SLOT, CONSOLE), Vector((0, 0, 1)))
        # the inner wall up to the console's rounded inner edge
        corner = [Vector((side * (CONSOLE_X + EDGE_R * (1 - math.cos(math.radians(t)))), 0,
                          CONSOLE_TOP - EDGE_R + EDGE_R * math.sin(math.radians(t)))) for t in (0, 30, 60, 90)]
        rows = [[Vector((side * CONSOLE_X, st(s), fl.FLOOR_Z)) for s in stations]]
        rows += [[q + Vector((0, st(s), 0)) for s in stations] for q in corner]
        cx = side * (CONSOLE_X + EDGE_R)
        facing(faces(part, rows, ATLAS_SLOT, CONSOLE),
               lambda f, cx=cx: f.calc_center_median() - Vector((cx, f.calc_center_median().y, CONSOLE_TOP - EDGE_R)))
        xo = lining_x(surf, s1, CONSOLE_TOP)
        poly(part, [(side * CONSOLE_X, st(s1), fl.FLOOR_Z), (side * lining_x(surf, s1, fl.FLOOR_Z + 0.01), st(s1), fl.FLOOR_Z),
                    (side * xo, st(s1), CONSOLE_TOP), (side * CONSOLE_X, st(s1), CONSOLE_TOP)], ATLAS_SLOT, CONSOLE, Vector((0, 1, 0)))
        # the armrest behind the stick (the stick and its boot are the KR-67's, by reference)
        x, s = STICK_AT
        flightdeck_detail.cbox(part, sys.modules[__name__], Vector((side * x, st((s + 0.14 + 6.86) / 2), CONSOLE_TOP + 0.035)), AX,
                               (0.14, 6.86 - s - 0.14, 0.07), GRIP, c=0.014)
    # pedestal
    y_fwd = st(BAND_AXIS_S) - math.sqrt(PANEL_R ** 2 - PEDESTAL_X ** 2)
    yf, ya = y_fwd + 0.002, st(PEDESTAL_AFT)
    w, c = PEDESTAL_X, 0.008  # the top's side edges chamfered c
    top = [[Vector((x, y, PEDESTAL_TOP)) for x in (-w + c, -0.12, 0.12, w - c)] for y in np.linspace(yf, ya, 6)]
    facing(faces(part, top, ATLAS_SLOT, CONSOLE), Vector((0, 0, 1)))
    for sgn in (1, -1):
        facing(faces(part, [[Vector((sgn * (w - c), y, PEDESTAL_TOP)) for y in (yf, ya)], [Vector((sgn * w, y, PEDESTAL_TOP - c)) for y in (yf, ya)]],
                     ATLAS_SLOT, CONSOLE), Vector((sgn, 0, 1)))
        facing(faces(part, [[Vector((sgn * w, y, z)) for y in (yf, ya)] for z in (fl.FLOOR_Z, PEDESTAL_TOP - c)], ATLAS_SLOT, CONSOLE),
               Vector((sgn, 0, 0)))
    poly(part, [(-w, ya, fl.FLOOR_Z), (w, ya, fl.FLOOR_Z), (w, ya, PEDESTAL_TOP - c), (w - c, ya, PEDESTAL_TOP), (-w + c, ya, PEDESTAL_TOP),
                (-w, ya, PEDESTAL_TOP - c)], ATLAS_SLOT, CONSOLE, Vector((0, 1, 0)))
    # the throttle quadrant: a raised block with a slot each side for the two levers
    xq, sq = 0.11, (5.88, 6.22)
    flightdeck_detail.cbox(part, sys.modules[__name__], Vector((0, st(sum(sq) / 2), PEDESTAL_TOP + 0.025)), AX,
                           (2 * xq, sq[1] - sq[0], 0.05), CONSOLE, c=0.006)
    # flap and span levers aft of the quadrant, the gear lever at the pedestal's forward end
    for x, knob, h in ((-0.15, (0.05, 0.02, 0.025), 0.10), (0.15, (0.03, 0.05, 0.02), 0.10), (0.0, None, 0.16)):
        s = 6.36 if knob else 5.82
        base = Vector((x, st(s), PEDESTAL_TOP + (0.0 if knob else 0.0)))
        top_ = base + Vector((0, 0.02 if knob else 0.03, h))
        sf.tube(part, [base, top_], 0.007, 6, ATLAS_SLOT, METAL)
        if knob:
            box(part, top_ - Vector(knob) / 2, top_ + Vector(knob) / 2, ATLAS_SLOT, KNOB)
        else:  # the gear lever's wheel
            sf.revolve_axis(part, ((0.028, -0.008), (0.028, 0.008)), top_, Vector((1, 0, 0)), 12, ATLAS_SLOT, KNOB)
        box(part, (x - 0.012, st(s + 0.10), PEDESTAL_TOP), (x + 0.012, st(s - 0.10), PEDESTAL_TOP + 0.004), ATLAS_SLOT, KNOB)
    # overhead console: a shallow box hanging under the lining's crown
    o0, o1 = OVERHEAD_S
    rows = []
    for s in np.linspace(o0, o1, 8):
        zc = lining_point(surf, s, 0.0).z
        rows.append([Vector((x, st(s), zc - OVERHEAD_DROP)) for x in np.linspace(-OVERHEAD_X, OVERHEAD_X, 4)])
    facing(faces(part, rows, ATLAS_SLOT, OVERHEAD), Vector((0, 0, -1)))
    for sgn in (1, -1):
        side_rows = [[Vector((sgn * OVERHEAD_X, st(s), lining_point(surf, s, 0.0).z + dz)) for s in np.linspace(o0, o1, 8)]
                     for dz in (-OVERHEAD_DROP, 0.01)]
        facing(faces(part, side_rows, ATLAS_SLOT, OVERHEAD), Vector((sgn, 0, 0)))
    for s, want in ((o0, Vector((0, -1, 0))), (o1, Vector((0, 1, 0)))):
        zc = lining_point(surf, s, 0.0).z
        poly(part, [(-OVERHEAD_X, st(s), zc - OVERHEAD_DROP), (OVERHEAD_X, st(s), zc - OVERHEAD_DROP),
                    (OVERHEAD_X, st(s), zc + 0.01), (-OVERHEAD_X, st(s), zc + 0.01)], ATLAS_SLOT, OVERHEAD, want)


def build_pedals(part):
    """Each seat's rudder pedals in the footwell, on arms up into the panel's underside (modelled, not animated)."""
    for side in (1, -1):
        for dx in (-0.12, 0.12):
            x = side * fl.EYE_X + dx
            c = Vector((x, st(5.42), 3.93))
            n = Vector((0, 0.5, 0.866))
            sf.box(part, c, (Vector((1, 0, 0)), n.cross(Vector((1, 0, 0))), n), (0.09, 0.20, 0.025), ATLAS_SLOT, METAL)
            sf.tube(part, [c + Vector((0, -0.02, 0.06)), Vector((x, st(5.50), KNEE_Z - 0.02))], 0.012, 6, ATLAS_SLOT, METAL)


def build_aft_wall(part, surf, labels):
    """Avionics racks against the aft wall outboard of the seats, each with line-replaceable boxes (a screwed face
    plate each) and their handles."""
    for side in (1, -1):
        x0, x1 = 0.95, min(1.55, lining_x(surf, AFT_S, 4.9) - 0.02)
        flightdeck_detail.cbox(part, sys.modules[__name__], Vector((side * (x0 + x1) / 2, st((6.72 + AFT_S) / 2), (fl.FLOOR_Z + 4.90) / 2)),
                               AX, (x1 - x0, AFT_S - 6.72, 4.90 - fl.FLOOR_Z), RACK, c=0.006)
        for k in range(3):
            z0 = fl.FLOOR_Z + 0.08 + 0.37 * k
            lo = Vector((min(side * (x0 + 0.03), side * (x1 - 0.03)), st(6.70), z0))
            hi = Vector((max(side * (x0 + 0.03), side * (x1 - 0.03)), st(6.72), z0 + 0.32))
            flightdeck_detail.cbox(part, sys.modules[__name__], (lo + hi) / 2, AX, hi - lo, RACK, c=0.003)
            labels.plate(((lo.x + hi.x) / 2, lo.y, z0 + 0.16), (0, -1, 0), (0, 0, 1), abs(hi.x - lo.x) - 0.006, 0.314,
                         rgb=fp.srgb(60, 64, 68))
            for dx in (0.12, (x1 - x0) - 0.12):
                hx = side * (x0 + dx)
                sf.tube(part, [Vector((hx, st(6.70), z0 + 0.12)), Vector((hx, st(6.67), z0 + 0.13)),
                               Vector((hx, st(6.67), z0 + 0.19)), Vector((hx, st(6.70), z0 + 0.20))], 0.006, 6, ATLAS_SLOT, METAL)


FRAME_STATIONS = (5.62, 6.12, 6.62)  # the hull frames the walls show, between the gaspers, lights and handles
FRAME_DEPTH, FRAME_W, FRAME_STEP = 0.035, 0.024, 3.0


def build_structure(part, surf, holes):
    """The walls' bare structure: a hull frame at each of FRAME_STATIONS, a flange FRAME_DEPTH deep and FRAME_W wide
    standing in from the lining round its ring, broken where the ring crosses an opening (holes, as (station, angle)
    outlines) or runs inside a console or the overhead. The stringers and skin panels between are painted."""
    flat = [[plane(s, a) for s, a in h] for h in holes]
    y = Vector((0, 1, 0))
    for s in FRAME_STATIONS:
        edge = floor_angle(surf, s)
        n = int(2 * edge / FRAME_STEP)
        angles = [-edge + 2 * edge * k / n for k in range(n + 1)]

        def clear(a):
            p = lining_point(surf, s, a)
            for ds in (-FRAME_W / 2, 0.0, FRAME_W / 2):
                q = plane(s + ds, a)
                if any(nose_exits.inside(q, h) or nose_exits.near(q, h, 0.02) for h in flat):
                    return False
            in_console = p.z < CONSOLE_TOP + 0.01 and abs(p.x) > CONSOLE_X - 0.01 and CONSOLE_S[0] - 0.01 <= s <= CONSOLE_S[1] + 0.01
            in_overhead = abs(p.x) < OVERHEAD_X + 0.01 and OVERHEAD_S[0] - 0.01 <= s <= OVERHEAD_S[1] + 0.01 and p.z > 5.1
            return not (in_console or in_overhead or p.z < fl.FLOOR_Z + 0.01)

        runs, run = [], []
        for a in angles:
            if clear(a):
                run.append(a)
            else:
                if len(run) > 1:
                    runs.append(run)
                run = []
        if len(run) > 1:
            runs.append(run)
        for run in runs:
            secs = []
            for a in run:
                p, inn = lining_point(surf, s, a), -surf.normal(s, a)
                secs.append([p - y * (FRAME_W / 2), p - y * (FRAME_W / 2) + inn * FRAME_DEPTH, p + y * (FRAME_W / 2) + inn * FRAME_DEPTH,
                             p + y * (FRAME_W / 2)])
            g = sf.Grid(part.bm, secs, loop=False)
            for (r, k), f in g.F.items():
                a = run[r]
                facing([f], (-y, -surf.normal(s, a), y)[k])
            ends = [part.bm.faces.new([g.V[0][i] for i in range(4)]), part.bm.faces.new([g.V[-1][i] for i in range(4)])]
            facing([ends[0]], (lining_point(surf, s, run[0]) - lining_point(surf, s, run[1])))
            facing([ends[1]], (lining_point(surf, s, run[-1]) - lining_point(surf, s, run[-2])))
            part.tag(g.faces() + ends, ATLAS_SLOT, STRUCT)


COAMING_UNDER = 0.003  # how far under the pilot's line of sight over the hood's crest the coaming meets the glass


def build_coaming(part, surf, footprint):
    """The glareshield's coaming over the screen: from the screen housing's top rim forward to the lining where the
    shroud's top wall meets it, along the top edge of the screen's footprint, and on out through the windscreen's reveal
    to just inside the inner glass, COAMING_UNDER under the pilot's line of sight over the hood's crest, so it seals the
    reveal under the panes' lower edges. All of it lies under the crest from the pilot's eye, which sees the glass
    straight over the hood: a coaming lapping the lining above that line read in game as a dark bar over the screen
    (owner). The windscreen's centre post and the window trims run down into it: their ends, cut where the screen's view
    starts (main), lie under it. Returns the coaming's faces."""
    r_in = BAND_R - BEZEL_DEPTH
    T = BAND_Z[1] + BEZEL_W
    ph = band_phi() + math.degrees(APERTURE_GROW / BAND_R)
    phis = [ph - 2 * ph * k / 48 for k in range(49)]
    near = [cyl(a, T + 0.001, r_in + 0.004) for a in phis]
    far = [lining_point(surf, s, a) for s, a in footprint[:49]]  # aperture()'s top edge, as build_shroud's
    under = [cyl(a, T + HOOD_CREST[1] - COAMING_UNDER, r_in - HOOD_CREST[0]) for a in phis]
    glass = [loc for loc, _ in sight_hits(surf, under, -0.012)]  # build_glass's panes stand 1 cm under the skin
    # Continue the screen housing's finish over the seal. Its depth lies outside slot_for's panel radius.
    return (facing(faces(part, [near, far], fuv.PANEL_SLOT, BEZEL), Vector((0, 0, 1)))
            + facing(faces(part, [far, glass], fuv.PANEL_SLOT, BEZEL), lambda f: eye(1) - f.calc_center_median()))


def coaming_seen(objs, coaming):
    """Points on the coaming (each face's centre and toward its corners) that the pilot's eye reaches past the screen's
    hood, against every mesh the cockpit view draws."""
    verts, polys = [], []
    for o in objs.values():
        me = o.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        polys += [tuple(base + i for i in p.vertices) for p in me.polygons]
    tree = BVHTree.FromPolygons(verts, polys)
    e, out = eye(1), []
    for c, n, corners in coaming:
        for q in [c] + [c + (v - c) * 0.8 for v in corners]:
            d = q + n * 1e-4 - e
            hit = tree.ray_cast(e, d.normalized(), d.length + 0.002)
            if d.dot(n) < 0 and (hit[0] is None or hit[3] >= d.length - 0.0015):
                out.append([round(x, 3) for x in q])
    return out


def frame_strip(part, surf, loop, w_out, w_in, proud, reveal, cls):
    """A trim round an outline of (station, angle) points on the lining: w_out over the lining, standing proud toward
    the cabin, and w_in over the opening, returning reveal metres outward toward the skin (the window's reveal)."""
    pts = [lining_point(surf, s, a) for s, a in loop]
    nrm = [surf.normal(s, a) for s, a in loop]
    centre = sum(pts, Vector()) / len(pts)
    rings = []
    m = len(pts)
    for i in range(m):
        t0 = (pts[i] - pts[i - 1]).normalized()
        t1 = (pts[(i + 1) % m] - pts[i]).normalized()
        n = nrm[i]
        b = (n.cross(t0).normalized() + n.cross(t1).normalized()).normalized()
        if b.dot(pts[i] - centre) < 0:
            b = -b
        p = pts[i]
        sec = [p + b * w_out, p + b * (w_out - 0.008) - n * (proud * 0.7), p + b * (w_out * 0.5) - n * proud,
               p - b * (w_in * 0.4) - n * proud, p - b * w_in - n * (proud * 0.6), p - b * w_in + n * reveal]
        rings.append((sec, sum(sec, Vector()) / len(sec)))
    bm, fs = part.bm, []
    verts = [[bm.verts.new(q) for q in r] for r, _ in rings]
    for i in range(m):
        j = (i + 1) % m
        for k in range(len(rings[i][0]) - 1):  # a rounded section: each face faces away from the section's middle
            f = bm.faces.new((verts[i][k], verts[j][k], verts[j][k + 1], verts[i][k + 1]))
            fs += facing([f], (rings[i][0][k] + rings[i][0][k + 1]) / 2 - rings[i][1])
    part.tag(fs, ATLAS_SLOT, cls)
    return fs


# The hatch liners sit this far inside the lining, over the hatch panels' own inner faces, whose coarser flat triangles
# sag up to 6 mm in across the roof.
HATCH_LINER_IN = 0.010


def build_hatch_liner(part, surf, loop):
    """An escape hatch's inner liner: its opening's outline on the lining, filled, HATCH_LINER_IN inside so it covers
    the hatch panel's inner face (painted for the skin, not the cabin). It goes with the hatch when it jettisons."""
    flat = [plane(s, a) for s, a in loop]
    n = len(loop)
    s_lo, s_hi = min(s for s, _ in loop), max(s for s, _ in loop)
    a_lo, a_hi = min(a for _, a in loop), max(a for _, a in loop)
    steiner = [(s, a) for s in np.arange(s_lo + 0.1, s_hi, 0.1) for a in np.arange(a_lo + 2.0, a_hi, 3.0)
               if nose_exits.inside(plane(s, a), flat) and not nose_exits.near(plane(s, a), flat, 0.03)]
    pts = list(loop) + steiner
    co, _, tris, _, _, _ = delaunay_2d_cdt([plane(s, a) for s, a in pts], [(i, (i + 1) % n) for i in range(n)],
                                            [list(range(n))], 1, 1e-9)
    st_a = [(c.x, math.degrees(c.y / 1.9)) for c in co]
    vs = [part.bm.verts.new(lining_point(surf, s, a, -HATCH_LINER_IN)) for s, a in st_a]
    made = []
    for t in tris:
        f = part.bm.faces.new([vs[i] for i in t])
        s, a = sum(st_a[i][0] for i in t) / 3, sum(st_a[i][1] for i in t) / 3
        f.normal_update()
        if f.normal.dot(surf.normal(s, a)) > 0:
            f.normal_flip()
        f.smooth = True
        made.append(f)
    part.tag(made, ATLAS_SLOT, HATCH)


def build_trims(part, surf, panes, hatches, labels, liners):
    """Window frames round each pane, their reveals back to the inner glass; a trim round each hatch opening that hides
    the panel's seam; each hatch's liner (liners: {side: part}) with its jettison handle on the inboard edge, and the
    handle's placard on the wall outboard."""
    for loop in panes:
        frame_strip(part, surf, loop, 0.035, 0.012, 0.018, WALL - 0.012, FRAME)
    for side, loop in zip((1, -1), hatches):
        frame_strip(part, surf, loop, 0.035, 0.03, 0.014, 0.0, FRAME)
        build_hatch_liner(liners[side], surf, loop)
        s = sum(fl.HATCH_S) / 2
        a = surf.deg_for_x(s, side * (fl.HATCH_X[0] + 0.05), lower=False)
        p, n = lining_point(surf, s, a, -HATCH_LINER_IN), surf.normal(s, a)
        pts = [p - n * 0.006 + Vector((0, d, 0)) for d in (-0.07, 0.07)]
        sf.tube(liners[side], [pts[0], pts[0] - n * 0.05, pts[1] - n * 0.05, pts[1]], 0.009, 6, ATLAS_SLOT, HANDLE)
        a = surf.deg_for_x(s, side * (fl.HATCH_X[1] + 0.09), lower=False)
        labels.add("EMERG EXIT\nPULL HANDLE", lining_point(surf, s, a), -surf.normal(s, a), Vector((0, 0, 1)), cap=0.006,
                   rgb=lb.BLACK, plate=lb.YELLOW, lift=0.003)


def build_glass(part, surf, panes):
    """The inner panes 1 cm under the skin over each pane outline grown 1.5 cm, facing the cabin."""
    for side in (1, -1):
        for corners in nose.PANES:
            c = nose.resolve(surf, corners, side)
            rows = []
            for i in range(7):
                row = []
                for j in range(5):
                    s, a = sf.bilinear(c, i / 6, j / 4)
                    row.append(surf.point(s, a, -0.01))
                rows.append(row)
            fs = faces(part, rows, GLASS_SLOT, 0)
            facing(fs, lambda f: -surf.normal(*sf.bilinear(c, 0.5, 0.5)))
    uv = part.bm.loops.layers.uv.verify()
    for f in part.bm.faces:
        for loop in f.loops:
            p = loop.vert.co
            loop[uv].uv = (p.x * 0.5 + 0.5, (p.y - st(4.0)) * 0.3 + p.z * 0.3)
    part.uv_done = True


def clip_glass(part, phi_b):
    """The inner panes less what the pilot sees through the screen: cut along the planes through the eye and the screen's
    grown edge over its top and ends (the shroud's and the coaming's lines), and that part dropped. Dropped by whole faces,
    the panes stopped short of the coaming and the shroud, and the sky showed untinted between them (owner, in game)."""
    e = eye(1)
    ring = aperture(phi_b)
    n = 48  # aperture(): the top edge's segments, then the -X end's three, the bottom edge's, the +X end's three

    def view(p):
        d = p - e
        return math.degrees(math.atan2(d.x, -d.y)), math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))

    top_and_ends = list(range(n)) + [n, n + 1, n + 2] + [2 * n + 3, 2 * n + 4, 2 * n + 5]
    for k in top_and_ends:
        p, q = ring[k], ring[(k + 1) % len(ring)]
        (ap, ep), (aq, eq) = view(p), view(q)
        lo_a, hi_a, lo_e, hi_e = min(ap, aq) - 0.5, max(ap, aq) + 0.5, min(ep, eq) - 0.5, max(ep, eq) + 0.5
        normal = (p - e).cross(q - e).normalized()
        near = []
        for f in part.bm.faces:
            vs = [view(v.co) for v in f.verts]
            if (min(a for a, _ in vs) <= hi_a and max(a for a, _ in vs) >= lo_a and min(z for _, z in vs) <= hi_e
                    and max(z for _, z in vs) >= lo_e):
                near.append(f)
        if near:
            geom = list({v for f in near for v in f.verts}) + list({ed for f in near for ed in f.edges}) + near
            bmesh.ops.bisect_plane(part.bm, geom=geom, plane_co=e, plane_no=normal)
    g = APERTURE_GROW
    drop = [f for f in part.bm.faces if in_band(f.calc_center_median(), phi_b, math.degrees(g / BAND_R), g)
            and cyl_coords(f.calc_center_median())[1] > BAND_R]
    bmesh.ops.delete(part.bm, geom=drop, context="FACES")


# ---------------- the stock parts, by reference ----------------
# Pivots (empties) where authoring places stock meshes whole (CenturionAuthor.FlightDeck.cs), each with the stock mesh,
# its stock material and whether it is mirrored for the hand that works it: the KR-67's sidesticks (Cockpit.joysticks;
# the mesh's own pivot, 8 cm above its foot, so its foot rests on the console), its throttles (Cockpit.throttles; the
# grip 0.293 to 0.397 m above the pivot rests on the quadrant). The pilot's stick and throttle are mirrored copies of
# the KR-67's right-handed stick and left-handed throttle.
STOCK_TRIS = {"Multirole1_joystick": 1890, "Multirole1_throttle": 880}


def stock_pivots():
    """{name: (stock mesh, stock material, mirrored, location, turn about Z in radians)}."""
    x, s = STICK_AT
    tx, ts, tz = THROTTLE_AT
    out = {}
    for side, tag, n in ((1, "L", "1"), (-1, "R", "2")):
        out["stick_" + tag] = ("Multirole1_joystick", "hotas", side > 0, Vector((side * x, st(s), CONSOLE_TOP + 0.08)), 0.0)
        out["throttle_" + n] = ("Multirole1_throttle", "hotas", side > 0, Vector((side * tx, st(ts), tz)), 0.0)
    return out


WING_CANVAS_LIFT = 0.0005  # the wing display's flat canvas stands this far in front of its curved glass at its sides


def wing_canvas():
    """The wing display's flat canvas: its centre, its right (the crew's) and its half width and height."""
    ac, _ = display_layout()[DISPLAY_ORDER.index(WING_PAGE)]
    hw, hh = display_page(WING_PAGE) / 2, (DISPLAY_Z[1] - DISPLAY_Z[0]) / 2 - PAGE_MARGIN
    r = math.sqrt((DISPLAY_GLASS_R - WING_CANVAS_LIFT) ** 2 - hw ** 2)
    a = math.radians(ac)
    return cyl(ac, sum(DISPLAY_Z) / 2, r), -Vector((math.cos(a), math.sin(a), 0.0)), hw, hh


def add_wing_display_pivot(coll, root):
    """The wing display's canvas as an empty under the root (wing_canvas): at its centre, turned to face the crew as the
    panel does there, carrying its width and height (canvas_w, canvas_h), where authoring stands the plugin's canvas."""
    loc, right, hw, hh = wing_canvas()
    e = bpy.data.objects.new("wing_display", None)
    e.empty_display_size = 0.05
    e.rotation_euler = (0.0, 0.0, math.atan2(-right.y, -right.x))
    e["canvas_w"], e["canvas_h"] = 2 * hw, 2 * hh
    coll.objects.link(e)
    e.parent = root
    e.matrix_parent_inverse.identity()
    e.location = loc - root.location
    return e


def add_stock_pivots(coll, root):
    """The pivots as empties under the root, carrying their stock mesh, material and mirroring for the export."""
    made = {}
    for name, (mesh, mat, mirrored, loc, turn) in stock_pivots().items():
        e = bpy.data.objects.new(name, None)
        e.empty_display_size = 0.05
        e.location = loc
        e.rotation_euler = (0.0, 0.0, turn)
        e["stock_mesh"], e["stock_material"], e["mirror"] = mesh, mat, int(mirrored)
        coll.objects.link(e)
        e.parent = root
        e.matrix_parent_inverse.identity()
        e.location = loc - root.location
        made[name] = e
    return made


# ---------------- objects ----------------
PART_NAMES = ("flightdeck_int", "labels", "warning_lenses", "hatch_liner_L", "hatch_liner_R", "band_bezel", "band",
              "band_marker", "tacScreen", "glass_int")


def material(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def to_object(part, origin, coll):
    bm = part.bm
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    used = sorted({f.material_index for f in bm.faces})  # slots no face uses would export as empty submeshes
    for f in bm.faces:
        f.material_index = used.index(f.material_index)
    part.slots = [part.slots[i] for i in used]
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.verts.ensure_lookup_table()
    bmesh.ops.translate(bm, vec=-origin, verts=bm.verts)
    me = bpy.data.meshes.new(part.name)
    bm.to_mesh(me)
    bm.free()
    for slot in part.slots:
        me.materials.append(material(slot))
    o = bpy.data.objects.new(part.name, me)
    o.location = origin
    coll.objects.link(o)
    if "UVMap" not in me.uv_layers and len(me.uv_layers):
        me.uv_layers[0].name = "UVMap"
    me.set_sharp_from_angle(angle=math.radians(35))
    return o


def tri_count(o):
    return sum(len(p.vertices) - 2 for p in o.data.polygons)


# ---------------- checks ----------------
def band_frustum_check(objs, phi_b):
    """Faces of the interior's opaque parts with a corner or centre that either eye sees through the screen."""
    bad = {}
    for o in objs:
        hits = []
        for p in o.data.polygons:
            c = o.matrix_world @ p.center
            if in_band(c, phi_b, 0.0, 0.0) and cyl_coords(c)[1] > BAND_R + 0.002:
                hits.append([round(c.x, 3), round(c.y + Y0, 3), round(c.z, 3)])
        if hits:
            bad[o.name] = hits[:20]
    return bad


# Aircraft.exteriorRenderers: what the game hides in cockpit view (CenturionAuthor.PlaceSystems), and the interior's
# see-through parts: the inner panes, the screen and its marker.
COCKPIT_HIDDEN = ("nose", "radar_F_fairing")
GLAZING = ("glass_int", "band", "band_marker")


def unglazed_view(objs):
    """Sightlines from the pilot's head positions (flightdeck_uv.head_positions; the camera only takes the pilot's seat)
    over the forward half that leave the interior with no glazing on the way, the parts the game hides in cockpit view
    passed: to the sky, or to an exterior mesh the game draws. Each as (head offset, azimuth, elevation, what it reaches).
    The owner saw untinted sky in game where the inner panes stopped short of the coaming."""
    interior = set(objs)
    verts, polys, owner = [], [], []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.hide_render or o.name in COCKPIT_HIDDEN or o.name == "kit_library":  # the kit's, built only to bake
            continue
        me = o.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        polys += [tuple(base + i for i in p.vertices) for p in me.polygons]
        owner += [o.name] * len(me.polygons)
    tree = BVHTree.FromPolygons(verts, polys)
    out = []
    for e in fuv.head_positions(sys.modules[__name__], 1):
        for az in [k + 0.5 for k in range(-90, 90, 2)]:  # half steps: an axis-aligned ray can slip along a ring's edges
            for el in [k + 0.5 for k in range(-40, 60, 2)]:
                d = direction(az, el, 1)
                origin, glazed, reached = e, False, "sky"
                while True:
                    hit = tree.ray_cast(origin, d, 100.0)
                    if hit[0] is None:
                        break
                    name = owner[hit[2]]
                    if name in GLAZING:
                        glazed = True
                        origin = hit[0] + d * 0.0005
                        continue
                    reached = None if name in interior else name
                    break
                if reached and not glazed:
                    out.append(([round(v, 2) for v in e - eye(1)], az, el, reached))
    return out


def glass_texture_check(path):
    """The repeating glass UVs require a uniform, translucent base map. Donor pane silhouettes paint false frames."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        rgba = np.array(image.pixels[:]).reshape(-1, 4)
        low, high = np.rint(rgba.min(axis=0) * 255).astype(int), np.rint(rgba.max(axis=0) * 255).astype(int)
        return {"rgba_min": low.tolist(), "rgba_max": high.tolist(),
                "pass": bool(np.array_equal(low, high) and 0 < low[3] < 128)}
    finally:
        bpy.data.images.remove(image)


def hatch_clearance():
    """The hatch opening against the escape path (docs/COCKPIT-DESIGN.md "Escape"): the pilot capsule (radius 0.25 m,
    0.40 m below to 0.90 m above the Pilot root) and the seat's 0.99 m length swept along the rail, where they pass the
    roof's height, and the dismounted pilot's head; the least margin inside the outline in plan."""
    import flightdeck_layout as L
    rail = Vector((0.024, -0.230, 0.973))
    out = {}
    for side in (1, -1):
        root = Vector((side * L.EYE_X, st(L.EYE_S - 0.17), L.EYE_Z - 0.73))
        r = Vector((side * rail.x, rail.y, rail.z))
        margins = []
        for t in np.linspace(0.0, 1.5, 31):
            c = root + r * t
            for dz in np.linspace(-0.40, 0.90, 14):
                q = c + r * (dz / r.z)
                if 5.10 < q.z < 5.75:  # the roof's band over the hatches
                    for ang in range(0, 360, 15):
                        x = q.x + 0.25 * math.cos(math.radians(ang))
                        s = q.y + Y0 + 0.25 * math.sin(math.radians(ang))
                        margins.append(plan_margin(side * x, s))
        out["L" if side > 0 else "R"] = round(min(margins), 3)
    return out


def plan_margin(x, s):
    """Signed distance inside the left hatch's rounded rectangle in plan (x outboard, station)."""
    (s0, s1), (x0, x1), r = fl.HATCH_S, fl.HATCH_X, fl.HATCH_CORNER
    cu, cv = (s0 + s1) / 2, (x0 + x1) / 2
    hu, hv = (s1 - s0) / 2 - r, (x1 - x0) / 2 - r
    qu, qv = abs(s - cu) - hu, abs(x - cv) - hv
    return -(math.hypot(max(qu, 0), max(qv, 0)) + min(max(qu, qv), 0) - r)


# ---------------- main ----------------
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--views", default="d,w,m,e,x")
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--no-bake", action="store_true")
    a = ap.parse_args(argv)
    a.out = Path(a.out)
    if not a.out.is_absolute():
        raise SystemExit("Pass an absolute --out: Blender resolves relative paths against its own cwd.")
    blend = Path(bpy.data.filepath).resolve()
    if "art" in blend.parts:
        raise SystemExit(f"refusing to work on {blend}: copy it under .cache/cockpit first")
    return a


def main():
    a = parse_args()
    out = a.out
    (out / "textures").mkdir(parents=True, exist_ok=True)
    bl = load_blockout()
    global Y0
    Y0 = bl.Y0
    surf = sf.Fuselage(bl)
    for o in bpy.data.objects:
        if o.name.endswith("_lod1") or "_colmesh" in o.name:
            o.hide_render = True
    skin = Skin(("radar_F_fairing", "nose", "fuselage_F"))
    edges = glass_edges(skin)
    phi_b = band_phi()
    panes = pane_outlines(surf, phi_b)
    hatches = [nose_exits.hatch_loop(surf, side) for side in (1, -1)]

    parts = {n: sf.Part(n, (ATLAS_SLOT,)) for n in PART_NAMES}
    for p in parts.values():
        p.uv_done = False
    deck = parts["flightdeck_int"]
    labels = lb.Labels()
    kit = fk.Kit(sys.modules[__name__])
    for p in parts.values():
        p.kit = kit
    deck.lenses = parts["warning_lenses"]  # the warning lamps' lenses: their own renderer, which the game flashes
    build_floor(deck, surf)
    build_panel(deck, edges, phi_b)
    build_glareshield(deck, skin, edges, phi_b)
    build_consoles(deck, surf, edges, phi_b)
    build_pedals(deck)
    build_aft_wall(deck, surf, labels)
    flightdeck_detail.build_details(deck, sys.modules[__name__], surf, edges, phi_b, labels)
    build_band(phi_b, parts)
    build_warning_lamps(parts["band_bezel"], parts["warning_lenses"])
    build_displays(parts, labels)
    footprint = screen_footprint(surf, phi_b)
    build_lining(deck, surf, panes + hatches + [footprint])
    build_structure(deck, surf, panes + hatches + [footprint])
    build_shroud(deck, surf, footprint, phi_b)
    build_trims(deck, surf, panes, hatches, labels, {1: parts["hatch_liner_L"], -1: parts["hatch_liner_R"]})
    build_glass(parts["glass_int"], surf, panes)
    drop = [f for f in deck.bm.faces if f[deck.cls] in (FRAME, 0) and in_band(f.calc_center_median(), phi_b)
            and cyl_coords(f.calc_center_median())[1] > BAND_R]  # window frames where the screen shows the world below them
    bmesh.ops.delete(deck.bm, geom=drop, context="FACES")
    clip_glass(parts["glass_int"], phi_b)
    coaming = [(f.calc_center_median(), f.normal.copy(), [v.co.copy() for v in f.verts])
               for f in build_coaming(deck, surf, footprint)]
    flightdeck_detail.build_plates(deck, sys.modules[__name__], labels)
    label_density, label_rasters, label_pos = lb.build(labels, parts["labels"], LABEL_SLOT, LEGEND_SLOT)
    fd = sys.modules[__name__]
    for n in ("flightdeck_int", "hatch_liner_L", "hatch_liner_R"):
        fuv.assign_slots(parts[n], fd)
    fuv.assign_slots(parts["band_bezel"], fd, fuv.PANEL_SLOT)

    coll = bpy.data.collections.new("Flightdeck")
    bpy.context.scene.collection.children.link(coll)
    origins = {"flightdeck_int": Vector((0, st(fl.EYE_S), fl.FLOOR_Z))}
    objs = {}
    for name, part in parts.items():
        c = origins.get(name)
        if c is None:
            vs = [v.co for v in part.bm.verts]
            c = sum(vs, Vector()) / len(vs)
        objs[name] = to_object(part, c, coll)
    root = objs["flightdeck_int"]
    for name, o in objs.items():  # the root has world axes, so a child's offset is its origin less the root's
        if o is not root:
            o.parent = root
            o.matrix_parent_inverse.identity()
            o.location = o.location - root.location
    pivots = add_stock_pivots(coll, root)
    add_wing_display_pivot(coll, root)
    bpy.context.view_layer.update()
    for o in objs.values():
        for p in o.data.polygons:
            p.use_smooth = False
        cls = np.zeros(len(o.data.polygons), np.int32)
        if "cls" in o.data.attributes:
            o.data.attributes["cls"].data.foreach_get("value", cls)
        for p in o.data.polygons:
            p.use_smooth = int(cls[p.index]) in SMOOTH_CLASSES or o.name in ("band", "tacScreen", "glass_int")

    atlas_objs = [objs[n] for n in ("flightdeck_int", "hatch_liner_L", "hatch_liner_R", "band_bezel")]
    import check_display_uvs
    pages_ok, pages = check_display_uvs.check(objs["tacScreen"], fd, [objs[n] for n in ("flightdeck_int", "band_bezel", "labels")])
    print("FLIGHTDECK display pages", "PASS" if pages_ok else "FAIL", json.dumps(pages))
    culled = fuv.cull_unseen(atlas_objs, fd, occluders=[objs["tacScreen"]])
    print("FLIGHTDECK culled", json.dumps(culled))
    uvr = fuv.layout_uvs(atlas_objs, fd, fuv.head_positions(fd), occluders=[objs["tacScreen"]])
    print("FLIGHTDECK uv", json.dumps({k: uvr[k] for k in ("density", "live_m2", "uv_fill", "faces")}))
    fuv.tile_uvs(atlas_objs, fd)
    fuv.structure_tint(atlas_objs)
    fp.uv_band(objs["band"], BAND_AXIS_S, BAND_R, Y0)
    tris = {n: tri_count(o) for n, o in objs.items()}
    tris.update({n: STOCK_TRIS[e["stock_mesh"]] for n, e in pivots.items()})  # the stock meshes authoring places on them
    total = sum(tris.values())
    metrics = {"tris": {"value": total, "limit": BUDGET_TRIS, "pass": total <= BUDGET_TRIS, "parts": tris},
               "band": {"phi_deg": round(phi_b, 2), "x_m": round(cyl(phi_b, 0).x, 3),
                        "stations": [round(BAND_AXIS_S - BAND_R, 3), round(cyl(phi_b, 0).y + Y0, 3)], "z": list(BAND_Z)},
               "nothing_in_screen_view": {"faces": band_frustum_check([objs[n] for n in ("flightdeck_int", "band_bezel")], phi_b)},
               "hatch_margin_m": {"value": hatch_clearance(), "limit": ">= 0.01 inside the outline"},
               "outside_seen_unglazed": {"sightlines": unglazed_view(objs)},
               "coaming_hidden": {"seen": coaming_seen(objs, coaming)},
               "atlas_px_per_m": uvr["density"],
               "atlas_live_m2": uvr["live_m2"],
               "atlas_uv_fill": uvr["uv_fill"],
               "kit_px_per_m": kit.density,
               "display_pages": {"pass": pages_ok, "faces": pages},
               "atlas_faces": uvr["faces"],
               "labels": {"quads": len(labels.items), "tris": tris["labels"], "limit": lb.MAX_LABELS,
                          "px_per_m": label_density, "floor": lb.LABEL_MIN_PX_PER_M},
               "glass_edge_deg": {str(k): v for k, v in edges[1].items()}}
    metrics["nothing_in_screen_view"]["pass"] = not metrics["nothing_in_screen_view"]["faces"]
    metrics["hatch_margin_m"]["pass"] = all(v >= 0.01 for v in metrics["hatch_margin_m"]["value"].values())
    metrics["outside_seen_unglazed"]["pass"] = not metrics["outside_seen_unglazed"]["sightlines"]
    metrics["coaming_hidden"]["pass"] = not metrics["coaming_hidden"]["seen"]
    print("FLIGHTDECK tris", json.dumps(tris), "total", total)

    maps = {}
    if not a.no_bake:
        for slot in fuv.PBR_SLOTS:
            maps[slot] = fp.paint_slot(atlas_objs, slot, out / "textures", fd, uvr, labels.plates, labels.hoses)
        maps[fk.KIT_SLOT] = kit.paint(out / "textures")
    maps.update(lb.paint(labels, label_rasters, label_pos, out / "textures"))
    maps.update(fp.small_maps(out / "textures"))
    metrics["glass_tint"] = glass_texture_check(maps["glass"])
    metrics["maps"] = {k: (str(v) if isinstance(v, Path) else {kk: str(vv) for kk, vv in v.items()}) for k, v in maps.items()}
    (out / "metrics_flightdeck.json").write_text(json.dumps(metrics, indent=1))
    for name in ("outside_seen_unglazed", "coaming_hidden", "glass_tint"):
        if not metrics[name]["pass"]:
            raise RuntimeError(f"FLIGHTDECK {name} FAIL: {metrics[name]}")
    renders = fp.review(objs, maps, a.views.split(","), a.samples, out, sys.modules[__name__], edges)
    metrics["renders"] = [str(r) for r in renders]
    (out / "metrics_flightdeck.json").write_text(json.dumps(metrics, indent=1))
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "review.blend"), copy=True)  # the review scene, for diagnostics
    save_export_blend(objs, out, maps)
    print("FLIGHTDECK done", json.dumps({k: v for k, v in metrics.items() if k != "glass_edge_deg"}))


def save_export_blend(objs, out, maps):
    """The interior alone, as tools/export_blockout.py reads a blend: its parts and the stock pivots in a "Centurion"
    collection with empty "Colliders" and "LOD1" sub-collections, and the maps it carries named in the scene's
    m4_textures."""
    keep = set(objs.values()) | {o for o in bpy.data.objects if o.type == "EMPTY" and ("stock_mesh" in o or "canvas_w" in o)}
    for o in list(bpy.data.objects):
        if o not in keep:
            bpy.data.objects.remove(o)
    for c in list(bpy.data.collections):
        if c.name != "Flightdeck":
            bpy.data.collections.remove(c)
    coll = bpy.data.collections["Flightdeck"]
    coll.name = "Centurion"
    for name in ("Colliders", "LOD1"):
        coll.children.link(bpy.data.collections.new(name))
    for o in objs.values():  # the review look linked object materials; the export reads the mesh's slots
        for slot in o.material_slots:
            slot.link = "DATA"
    files = [p for v in maps.values() for p in (v.values() if isinstance(v, dict) else [v])]
    bpy.context.scene["m4_textures"] = sorted(Path(p).name for p in files)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "flightdeck.blend"), check_existing=False)


if __name__ == "__main__":
    main()
