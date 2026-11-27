"""The rebuilt flight deck as a measured grey-box blockout, inside the locked nose, glass and camera band, at the existing
eye point, beside today's interior measured and rendered the same way.

blender -b --factory-startup <review.blend> --python flightdeck_layout.py -- --out <folder>
    [--views ahead,panel,left,right,commander,shoulder,plan] [--today] [--samples 48] [--measure-only]

Reads review.blend (the 0.1.3 build's composite plus today's interior, .cache/coaming/build2), never saves over it.
Keeps from today, unchanged: the nose shell and panes (exterior), the camera band, its housing and missile warning
lamp housings (band_bezel), the inner panes (glass_int), the hatch liners, the lamp lenses, the stock KR-67 sticks and
throttles on their pivots, and the shell (lining, floor, frames, aft wall: flightdeck_int less its panel, console and
switch-kit faces). Builds new: the main panel as two per-seat clusters and a centre stack under the band, the hood
between them and the band, lowered outboard panels, knee panels and footwells, side consoles, the pedestal and its
levers, the overhead, and the stock Darkreach ejection seats (by reference, from stock_cockpits.py's export).

Writes into --out: blockout.blend, blockout_measure.json and today_measure.json (flightdeck_measure's eye grid and
5 x 5 display rays from both builds), *_grid_*.png.npy, and the renders <build>_<view>.png at 2200 x 1238."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flightdeck_measure as cm  # noqa: E402
import flightdeck_stock as stock_scene  # noqa: E402

Y0 = cm.Y0
O = bpy.data.objects


def st(s):
    return s - Y0


def P(s, x, z):
    return Vector((x, st(s), z))


# ---------------------------------------------------------------- the layout
EYE = {1: P(6.55, 0.55, 5.00), -1: P(6.55, -0.55, 5.00)}  # side +1 the pilot (left, +X), -1 the commander
# A cluster's panel faces stand on a fan round the seat's eye in plan: top edge R_TOP from the eye at Z_TOP, bottom
# edge R_BOT at Z_BOT (12 deg of lean back), so each face looks at the eye within 13 deg and the band's lower housing
# overhangs the tops as a hood.
R_TOP, R_BOT, Z_TOP, Z_BOT = 0.84, 0.76, 4.77, 4.40
BEZEL, BEZEL_PROUD, GLASS_PROUD, GAP, SLAB = 0.022, 0.012, 0.004, 0.008, 0.03
OPEN_TOP, OPEN_H = 4.72, 0.215  # the display openings, under the line from the eye over the band housing
# Pages: canvas pixels across the page as it reads upright (the existing Centurion_TacScreen rects, flightdeck.PAGES;
# the wing page in the canvas rect the Alkyon's second engine panel left empty, 595.7..803.4 x 1.6..253.9) and aspect.
PAGE_PX = {"radar": 582.9, "pfd": 141.2, "stores": 200.4, "engines": 214.9, "gauges": 141.1, "wing": 161.0}
ASPECT = {"radar": 1.702, "pfd": 0.610, "stores": 0.640, "engines": 0.851, "gauges": 0.570, "wing": 0.640}
PAGE_RGB = {"radar": (0.10, 0.75, 0.25), "pfd": (0.15, 0.45, 0.95), "stores": (0.95, 0.65, 0.10),
            "engines": (0.90, 0.25, 0.20), "gauges": (0.65, 0.30, 0.90), "wing": (0.10, 0.80, 0.85)}
# The lowest outside view (glass or band) today from the pilot's eye, per az (data/today_grid_pilot.npy, 0.1.3's): every new
# panel top stays half a degree under it, so the new interior hides nothing today's shows the pilot.
_TODAY = np.load(HERE / "data" / "today_grid_pilot.npy")
_OUT = _TODAY[0] | _TODAY[1]
TODAY_LOW = {az: (int(np.where(_OUT[:, az + 90])[0].min()) - 45 if _OUT[:, az + 90].any() else None) for az in range(-90, 91)}


def plan(side, az):
    """Unit plan vector from a seat's eye at az (positive toward the centreline for both seats)."""
    a = math.radians(az)
    return Vector((-side * math.sin(a), -math.cos(a), 0.0))


def z_cap_at(p):
    """The highest a panel top may stand at plan point p: half a degree under the pilot's lowest view today along
    that az, a degree either side (the commander's eye never renders: only pilots[0] gets the player, Pilot.cs)."""
    v = Vector((p.x - EYE[1].x, p.y - EYE[1].y, 0))
    az = round(math.degrees(math.atan2(-v.x, -v.y)))
    lows = [TODAY_LOW.get(a) for a in (az - 1, az, az + 1)]
    lows = [x for x in lows if x is not None]
    if not lows:
        return 9.0
    return 5.00 - v.length * math.tan(math.radians(-min(lows) + 0.5))


def z_cap(az, r, side=1):
    exy = Vector((EYE[side].x, EYE[side].y, 0))
    return z_cap_at(exy + plan(side, az) * r)


# Per seat, left to right as that seat looks (pilot: outboard to inboard; commander mirrored by side), each module:
# (page or None, opening width, lowered). Widths: the page's aspect at OPEN_H, the lowered ones at their own height.
PILOT = [(None, 0.12, 0.19), ("wing", 0.19 * ASPECT["wing"], 0.19), ("pfd", OPEN_H * ASPECT["pfd"], None),
         ("radar", OPEN_H * ASPECT["radar"], None), ("stores", OPEN_H * ASPECT["stores"], None)]
COMMANDER = [(None, 0.12, 0.19), ("stores", 0.19 * ASPECT["stores"], 0.19), ("pfd", OPEN_H * ASPECT["pfd"], None),
             ("radar", OPEN_H * ASPECT["radar"], None)]
RADAR_AZ = 2.0  # the radar's centre, 2 deg inboard of the seat's line
CENTRE = ("engines", OPEN_H * ASPECT["engines"])
LOWER_R = (0.80, 0.73)  # lowered outboard modules: plan radius top, bottom


# ---------------------------------------------------------------- mesh helpers
def mesh_obj(name, verts, faces, mat, coll):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    o = bpy.data.objects.new(name, me)
    me.materials.append(mat)
    coll.objects.link(o)
    return o


class Builder:
    def __init__(self, coll):
        self.coll = coll
        self.parts = {}

    def add(self, key, verts, faces):
        v, f = self.parts.setdefault(key, ([], []))
        base = len(v)
        v += [Vector(p) for p in verts]
        f += [[base + i for i in face] for face in faces]

    def slab(self, key, quad, n, t0, t1):
        """A plate on quad (4 corners in order), from t0 to t1 along n."""
        a = [p + n * t0 for p in quad]
        b = [p + n * t1 for p in quad]
        self.add(key, a + b, [[0, 1, 2, 3][::-1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]])

    def box(self, key, c, size, rot=Matrix()):
        hx, hy, hz = (s / 2 for s in size)
        pts = [Vector((x, y, z)) for z in (-hz, hz) for y in (-hy, hy) for x in (-hx, hx)]
        pts = [c + rot @ p for p in pts]
        self.add(key, pts, [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]])

    def cyl(self, key, c, axis, r, h, n=12):
        axis = axis.normalized()
        u = axis.orthogonal().normalized()
        w = axis.cross(u)
        ring = [u * math.cos(2 * math.pi * k / n) * r + w * math.sin(2 * math.pi * k / n) * r for k in range(n)]
        verts = [c + p for p in ring] + [c + p + axis * h for p in ring]
        faces = [[k, (k + 1) % n, n + (k + 1) % n, n + k] for k in range(n)] + [list(range(n))[::-1], list(range(n, 2 * n))]
        self.add(key, verts, faces)

    def finish(self, mats):
        out = {}
        for key, (v, f) in self.parts.items():
            out[key] = mesh_obj("bo_" + key, v, f, mats[key.split(":")[0]], self.coll)
        return out


def quad_point(q, u, v):
    """q = (BL, BR, TR, TL); u across, v up, 0..1."""
    bl, br, tr, tl = q
    return bl.lerp(br, u).lerp(tl.lerp(tr, u), v)


def face_normal(q, eye):
    n = (q[1] - q[0]).cross(q[3] - q[0]).normalized()
    return n if n.dot(eye - (q[0] + q[2]) / 2) > 0 else -n


# ---------------------------------------------------------------- building
def build_cluster(b, side, modules, displays):
    """One seat's modules on its fan; returns the plan points of its inboard top and bottom edge."""
    eye = EYE[side]
    exy = Vector((eye.x, eye.y, 0))
    # angular widths at the opening's mid radius
    r_mid = (R_TOP + R_BOT) / 2
    widths = [(w + 2 * BEZEL + GAP) for _, w, _ in modules]
    radar_i = [m[0] for m in modules].index("radar")
    a_radar0 = RADAR_AZ - math.degrees(widths[radar_i] / r_mid) / 2
    edges = [a_radar0]
    for w in widths[:radar_i][::-1]:
        edges.insert(0, edges[0] - math.degrees(w / r_mid))
    a = a_radar0
    for w in widths[radar_i:]:
        a += math.degrees(w / r_mid)
        edges.append(a)
    for k, (page, w, lowered) in enumerate(modules):
        a0, a1 = edges[k], edges[k + 1]
        rt, rb = (LOWER_R if lowered else (R_TOP, R_BOT))
        # the pilot's caps, mirrored for the commander so the panel stays symmetric
        zt0, zt1 = min(Z_TOP, z_cap(a0, rt, side)), min(Z_TOP, z_cap(a1, rt, side))
        # the straight top edge between the corners stays under the cap along its whole length
        over = max(zt0 + (zt1 - zt0) * f - z_cap(a0 + (a1 - a0) * f, rt, side) for f in (0.25, 0.5, 0.75))
        if over > 0:
            zt0, zt1 = zt0 - over, zt1 - over
        if lowered:
            zt0 = zt1 = min(zt0, zt1)
        q = (exy + plan(side, a0) * rb + Vector((0, 0, Z_BOT)), exy + plan(side, a1) * rb + Vector((0, 0, Z_BOT)),
             exy + plan(side, a1) * rt + Vector((0, 0, zt1)), exy + plan(side, a0) * rt + Vector((0, 0, zt0)))
        # no knee under the module: nothing hangs below the control strips into the footwell (docs/DECISIONS.md), so
        # the pedals stay in sight from the eye and a seated pilot's legs have a clear path to them; the panel's
        # backing wall (flightdeck_build.py panel_backing) closes the space behind
        if side == -1:  # keep the quad's u running toward the pilot's right in the world
            q = (q[1], q[0], q[3], q[2])
        n = face_normal(q, eye)
        b.slab("panel", q, n, -SLAB, 0.0)
        if page is None:
            continue
        top = min(OPEN_TOP, min(zt0, zt1) - BEZEL - 0.008)
        if not lowered and min(zt0, zt1) < Z_TOP - 0.005:
            top -= 0.026  # a module stepped down under the side pane: its opening clears the flat hood's lip
        if not lowered and max(abs(q[2].x), abs(q[3].x)) <= 0.80:  # the hood: flat from the module's top back to the
            # band, over the eye's line to the opening; only under the band's housing (x within 0.80 m), beyond its ends
            # nothing needs closing and a plate there would rise into the side pane's lowest view
            b.slab("hood", (q[3], q[2], band_crew_face(q[2]), band_crew_face(q[3])), Vector((0, 0, 1)), -0.012, 0.0)
        h = lowered or OPEN_H
        bot = top - h

        def at(u, z, q=q):
            # the face's v is linear in z between its bottom edge and the top edge's z at that u
            zt = q[3].z + (q[2].z - q[3].z) * u
            return quad_point(q, u, (z - Z_BOT) / (zt - Z_BOT))
        width = (q[1] - q[0]).length * 0.5 + (q[2] - q[3]).length * 0.5
        u0, u1 = 0.5 - w / (2 * width), 0.5 + w / (2 * width)
        ub0, ub1 = u0 - BEZEL / width, u1 + BEZEL / width
        opening = (at(u0, bot), at(u1, bot), at(u1, top), at(u0, top))
        frame = [(at(ub0, bot - BEZEL), at(ub1, bot - BEZEL), at(ub1, bot), at(ub0, bot)),
                 (at(ub0, top), at(ub1, top), at(ub1, top + BEZEL), at(ub0, top + BEZEL)),
                 (at(ub0, bot), at(u0, bot), at(u0, top), at(ub0, top)),
                 (at(u1, bot), at(ub1, bot), at(ub1, top), at(u1, top))]
        for f in frame:
            b.slab("bezel", f, n, 0.0, BEZEL_PROUD)
        # bezel keys: four a side on the radar, two under the small pages
        if page == "radar":
            for kk in range(4):
                for uu in (ub0 + BEZEL / width * 0.5, u1 + BEZEL / width * 0.5):
                    c = at(uu, bot + h * (0.2 + 0.2 * kk))
                    b.box("keys", c + n * (BEZEL_PROUD + 0.004), (0.012, 0.012, 0.012), n.to_track_quat("Z", "Y").to_matrix())
        disp = [p + n * GLASS_PROUD for p in opening]
        b.add("display:%s:%d:%s" % (page, side, k), disp, [[0, 1, 2, 3]])
        displays.append(("%s_%s" % (page, "pilot" if side == 1 else "commander"), page, tuple(disp), (PAGE_PX[page],)))
    return edges


def band_crew_face(p):
    """The point at p's height on the band's own cylinder (r 1.60 about station 7.30) plus the panel's 1 cm gap,
    along the line from p toward that axis: the hood closes the void between a module's top and the band housing,
    and from the eye it sits behind the housing's lower edge."""
    if BAND_RADIUS is not None:  # the reshaped band (flightdeck_screen.py), when flightdeck_build builds against it
        import flightdeck_screen as band_shape
        return band_shape.crew_face(p, BAND_RADIUS)
    axis = Vector((0.0, st(7.30), p.z))
    d = (p - axis)
    d.z = 0
    return axis + d.normalized() * 1.61


BAND_RADIUS = None  # flightdeck_build.py sets the reshaped band's radius here before it builds the panel


def centre_display(b, q, n, u0, u1, page, displays, name):
    top, bot = OPEN_TOP, OPEN_TOP - OPEN_H

    def at(u, z):
        return quad_point(q, u, (z - Z_BOT) / (Z_TOP - Z_BOT))
    width = (q[1] - q[0]).length
    ub0, ub1 = u0 - BEZEL / width, u1 + BEZEL / width
    for f in ((at(ub0, bot - BEZEL), at(ub1, bot - BEZEL), at(ub1, bot), at(ub0, bot)),
              (at(ub0, top), at(ub1, top), at(ub1, top + BEZEL), at(ub0, top + BEZEL)),
              (at(ub0, bot), at(u0, bot), at(u0, top), at(ub0, top)),
              (at(u1, bot), at(ub1, bot), at(ub1, top), at(u1, top))):
        b.slab("bezel", f, n, 0.0, BEZEL_PROUD)
    disp = [p + n * GLASS_PROUD for p in (at(u0, bot), at(u1, bot), at(u1, top), at(u0, top))]
    b.add("display:%s:0:%s" % (page, name), disp, [[0, 1, 2, 3]])
    displays.append((name, page, tuple(disp), (PAGE_PX[page],)))


def build_centre(b, displays, edges_p, edges_c):
    """The centre stack between the pilot's stores page and the commander's radar: one face across the gap between the
    two fans' inboard top edges, leaning back as they do, which turns it about 11 deg toward the pilot. It carries the
    engines and the status gauges (fuel, throttle, mass, thrust to weight) side by side."""
    tp = Vector((EYE[1].x, EYE[1].y, 0)) + plan(1, edges_p[-1]) * R_TOP + Vector((0, 0, Z_TOP))
    tc = Vector((EYE[-1].x, EYE[-1].y, 0)) + plan(-1, edges_c[-1]) * R_TOP + Vector((0, 0, Z_TOP))
    bp = Vector((EYE[1].x, EYE[1].y, 0)) + plan(1, edges_p[-1]) * R_BOT + Vector((0, 0, Z_BOT))
    bc = Vector((EYE[-1].x, EYE[-1].y, 0)) + plan(-1, edges_c[-1]) * R_BOT + Vector((0, 0, Z_BOT))
    # turned about its middle until it faces the pilot's eye in plan, with a cheek each side to the fans' edges
    mid = (bp + bc + tc + tp) / 4
    want = Vector((EYE[1].x - mid.x, EYE[1].y - mid.y, 0)).normalized()
    have = (tc - tp).cross(Vector((0, 0, 1)))
    have = Vector((have.x, have.y, 0)).normalized()
    if have.dot(want) < 0:
        have = -have
    turn = Matrix.Rotation(have.to_2d().angle_signed(want.to_2d()) * -1, 3, "Z")
    pivot = Vector((mid.x, mid.y, 0))
    tp2, tc2, bp2, bc2 = (pivot + turn @ (v - pivot) for v in (tp, tc, bp, bc))
    for a_, b_ in (((tp, bp), (tp2, bp2)), ((tc, bc), (tc2, bc2))):
        cheek = (a_[1], b_[1], b_[0], a_[0])
        b.slab("panel", cheek, face_normal(cheek, EYE[1]), -0.01, 0.0)
        b.slab("hood", (a_[0], b_[0], band_crew_face(b_[0]), band_crew_face(a_[0])), Vector((0, 0, 1)), -0.012, 0.0)
    tp, tc, bp, bc = tp2, tc2, bp2, bc2
    q = (bp, bc, tc, tp)
    n = face_normal(q, EYE[1])
    b.slab("panel", q, n, -SLAB, 0.0)
    knee = (bp + Vector((0, -0.22, -0.22)), bc + Vector((0, -0.22, -0.22)), bc, bp)
    b.slab("panel", knee, face_normal(knee, EYE[1]), -0.02, 0.0)
    b.slab("hood", (tp, tc, band_crew_face(tc), band_crew_face(tp)), Vector((0, 0, 1)), -0.012, 0.0)
    width = (bc - bp).length
    we, wg = CENTRE[1], OPEN_H * ASPECT["gauges"]
    # the pilot-side margin wide enough that the cheek never hides the engines page's edge from the pilot
    u = (0.06 + BEZEL) / width
    centre_display(b, q, n, u, u + we / width, "engines", displays, "engines")
    u2 = u + we / width + (2 * BEZEL + 0.012) / width
    centre_display(b, q, n, u2, u2 + wg / width, "gauges", displays, "gauges")
    return q


def build_consoles(b):
    """Side consoles outboard of each seat (today's footprint: inner wall x 0.86, top z 4.35, stations 5.40 to 6.90)
    with Dzus-rail modules 146 mm wide on top, the stick's well left open round its pivot (x 1.02, station 6.28)."""
    for side in (1, -1):
        x0, x1 = 0.86 * side, 1.38 * side
        c = P(6.15, (x0 + x1) / 2, (3.75 + 4.35) / 2)
        b.box("console", c, (abs(x1 - x0), 1.50, 0.60))
        cols = [0.885, 1.035, 1.185]
        rows = [(5.45, 5.62), (5.65, 5.86), (5.89, 6.10), (6.13, 6.43), (6.46, 6.62), (6.65, 6.86)]
        for xi, xc in enumerate(cols):
            for ri, (s0, s1) in enumerate(rows):
                if xi < 2 and ri == 3:
                    continue  # the stick well
                cx = (xc + 0.073) * side
                b.box("module", P((s0 + s1) / 2, cx, 4.355), (0.142, s1 - s0 - 0.006, 0.010))
                # a knob or two and a toggle per module
                n = 1 + (xi + ri) % 3
                for k in range(n):
                    px = cx + side * (-0.04 + 0.04 * k)
                    if (xi + ri + k) % 2:
                        b.cyl("knob", P((s0 + s1) / 2, px, 4.36), Vector((0, 0, 1)), 0.011, 0.018)
                    else:
                        b.box("knob", P((s0 + s1) / 2, px, 4.375), (0.006, 0.006, 0.03))
        # the stick well's bezel
        b.box("module", P(6.28, 1.02 * side, 4.352), (0.20, 0.26, 0.006))


def build_pedestal(b):
    """The centre pedestal from the centre stack's foot back to the seats (today's: half width 0.21, top 4.38, aft
    end 6.55) with the throttle quadrant round the stock throttles' pivots (station 6.05), the span lever left of it and
    the flap lever right, a radio and trim module aft."""
    b.box("console", P(6.23, 0.0, 4.065), (0.42, 0.64, 0.63))
    b.box("module", P(6.06, 0.0, 4.385), (0.24, 0.28, 0.012))  # throttle quadrant plate
    for x in (0.075, -0.075):
        b.box("slot", P(6.06, x, 4.392), (0.014, 0.24, 0.004))
    # span lever (left, toward the pilot) and flap lever (right): a gate and a T handle each
    for x, h in ((0.165, 0.16), (-0.165, 0.12)):
        b.box("module", P(6.10, x, 4.385), (0.06, 0.24, 0.012))
        b.box("lever", P(6.12, x, 4.39 + h / 2), (0.012, 0.012, h))
        b.box("lever", P(6.12, x, 4.39 + h), (0.05, 0.022, 0.022))
    for s0, s1 in ((6.22, 6.36), (6.38, 6.53)):
        b.box("module", P((s0 + s1) / 2, 0.0, 4.385), (0.40, s1 - s0 - 0.006, 0.010))
        for k in range(4):
            b.cyl("knob", P((s0 + s1) / 2, -0.12 + 0.08 * k, 4.39), Vector((0, 0, 1)), 0.012, 0.02)


def build_overhead(b):
    """The overhead between the hatches (today's: half width 0.17, stations 5.62 to 6.88, 7 cm under the lining)."""
    b.box("overhead", P(6.25, 0.0, 5.345), (0.34, 1.20, 0.07))
    for k in range(6):
        s = 5.72 + 0.18 * k
        b.box("overhead", P(s, 0.0, 5.307), (0.30, 0.16, 0.008))
        for j in range(5):
            b.box("overhead", P(s, -0.10 + 0.05 * j, 5.29), (0.006, 0.006, 0.03))


def build_footwells(b):
    """Footwells under the panel: a bulkhead at station 5.15 (today's FOOTWELL_S) and the rudder pedals."""
    for side in (1, -1):
        b.box("console", P(5.13, 0.55 * side, 4.05), (0.60, 0.04, 0.60))
        for dx in (-0.11, 0.11):
            b.box("lever", P(5.40, (0.55 + dx) * side, 3.95), (0.08, 0.03, 0.22),
                  Matrix.Rotation(math.radians(-20), 3, "X"))


def build_gear_handle(b, edges):
    """The gear handle on the pilot's outboard panel, beyond the lowered wing display, under the side pane's edge."""
    a = (edges[0] + edges[1]) / 2
    exy = Vector((EYE[1].x, EYE[1].y, 0))
    p = exy + plan(1, a) * (LOWER_R[0] + LOWER_R[1]) / 2 + Vector((0, 0, 4.52))
    toward = (EYE[1] - p).normalized()
    b.box("module", p + toward * 0.005, (0.07, 0.07, 0.16), toward.to_track_quat("Y", "Z").to_matrix())
    b.box("lever", p + toward * 0.05 + Vector((0, 0, 0.03)), (0.05, 0.05, 0.03), toward.to_track_quat("Y", "Z").to_matrix())
    b.box("lever", p + toward * 0.03, (0.012, 0.05, 0.012), toward.to_track_quat("Y", "Z").to_matrix())


# ---------------------------------------------------------------- scene
def clay(name, srgb, rough=0.7, emit=None, alpha=1.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    lin = tuple(((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in srgb)
    bsdf.inputs["Base Color"].default_value = (*lin, 1)
    bsdf.inputs["Roughness"].default_value = rough
    if emit:
        bsdf.inputs["Emission Color"].default_value = (*emit, 1)
        bsdf.inputs["Emission Strength"].default_value = 1.2
    if alpha < 1:
        bsdf.inputs["Alpha"].default_value = alpha
    return m


def kept_shell(coll, mat):
    """Today's shell: flightdeck_int less its panel, console, switch-kit and grip faces."""
    src = O["flightdeck_int"]
    me = src.data.copy()
    bm = bmesh.new()
    bm.from_mesh(me)
    names = [s.material.name if s.material else "" for s in src.material_slots]
    w = src.matrix_world

    def goes(f):
        """Today's panel, consoles, pedestal, switch kit and grips, and the displays' dark glass; the footwell, the
        consoles' outer walls and the shroud into the nose stay."""
        m = names[f.material_index]
        c = w @ f.calc_center_median()
        s, x, z = c.y + Y0, abs(c.x), c.z
        if m in ("cc_cockpit_kit", "stockref_hotas"):
            return True
        if x < 0.40 and 5.60 < s < 6.05 and 4.30 < z < 4.79:  # today's structure under the band between the seats
            return True
        if m == "cc_cockpit_panel":
            return z > 4.15 and s > 5.45
        if m == "cc_cockpit_console":
            return x < 1.36 and z < 4.42 and 5.38 < s < 6.92
        if m == "stockref_Matte_black":
            return 4.38 < z < 4.79 and s > 5.60
        return False
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if goes(f)], context="FACES")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("bo_shell", me)
    o.matrix_world = src.matrix_world
    me.materials.clear()
    me.materials.append(mat)
    coll.objects.link(o)
    return o


def setup_world(samples):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            if any(d.type == kind for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == kind
                scene.cycles.device = "GPU"
                break
        except TypeError:
            continue
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 2200, 1238, 100
    scene.view_settings.view_transform = "AgX"
    scene.render.film_transparent = False
    # outside: a ground plane and a sky gradient, so the band and the panes show a horizon
    if "bo_ground" not in O:
        me = bpy.data.meshes.new("bo_ground")
        me.from_pydata([(-3000, -3000, 0), (3000, -3000, 0), (3000, 3000, 0), (-3000, 3000, 0)], [], [(0, 1, 2, 3)])
        g = bpy.data.objects.new("bo_ground", me)
        me.materials.append(clay("bo_ground", (0.55, 0.50, 0.42), 0.95))
        scene.collection.objects.link(g)
    w = scene.world
    nt = w.node_tree
    bg = nt.nodes.get("Background")
    grad = nt.nodes.new("ShaderNodeTexGradient")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.5, 0.75
    ramp.color_ramp.elements[0].color = (0.75, 0.82, 0.90, 1)
    ramp.color_ramp.elements[1].color = (0.25, 0.45, 0.80, 1)
    nt.links.new(sep.outputs["Z"], ramp.inputs[0])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.0


def view_cam(name, loc, az, el, lens=18.0, ortho=None):
    cam = bpy.data.objects.get(name) or bpy.data.objects.new(name, bpy.data.cameras.new(name))
    if cam.name not in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.link(cam)
    cam.data.clip_start, cam.data.clip_end = 0.01, 5000
    cam.location = loc
    if ortho:
        cam.data.type, cam.data.ortho_scale = "ORTHO", ortho
        cam.rotation_euler = (0, 0, math.pi)
    else:
        cam.data.type, cam.data.lens, cam.data.sensor_width = "PERSP", lens, 36
        d = cm.direction(az, el)
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return cam


VIEWS = {  # name: (seat or location, az, el, lens)
    "ahead": ("pilot", 0, -6, 18), "panel": ("pilot", 6, -28, 20), "left": ("pilot", -62, -14, 18),
    "right": ("pilot", 58, -16, 18), "commander": ("commander", -8, -12, 18),
    "shoulder": (P(6.86, 0.05, 5.22), -16.0, -24.0, 20), "plan": (P(6.0, 0.0, 9.0), 0, -90, None),
}


def render(path, cam):
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def measure(label, cats, displays, out, ext):
    res = {}
    for seat, eye_t in (("pilot", cm.PILOT_EYE), ("commander", cm.COMMANDER_EYE)):
        eye = cm.eye_vec(eye_t)
        azs, els, grid, covered = cm.eye_grid(eye, cats, *ext)
        cm.grid_image(azs, els, grid, covered, out / ("%s_grid_%s.png" % (label, seat)))
        np.save(out / ("%s_grid_%s.npy" % (label, seat)),
                np.stack([grid == k for k in ("glass", "band", "display", "opaque", "leak")] + [covered]))
        res["grid_" + seat] = cm.grid_summary(azs, els, grid, covered)
        leaks = cm.leak_sphere(eye, cats)
        res["leaks_" + seat] = {"count_3deg": len(leaks), "first": leaks[:20]}
    eye = cm.eye_vec(cm.PILOT_EYE)
    blockers = {k: v for k, v in cats.items() if k != "display"}
    res["displays_pilot"] = cm.display_rays(eye, displays, blockers)
    json.dump(res, open(out / ("%s_measure.json" % label), "w"), indent=1, default=str)
    return res


def view_cones(coll, displays, glass_az):
    """Flat fans at z 5.62 from the pilot's eye: the real glass's az span at eye level (blue), the band's (teal) and each
    display's (its page colour)."""
    eye = EYE[1]
    z = 5.05
    fans = [("cone_band", (-19.8, 64.0), (0.1, 0.8, 0.7), 1.15, 0.18)]
    for name, page, quad, _ in displays:
        az = [cm.angles_of(p - eye)[0] for p in quad]
        fans.append(("cone_" + name, (min(az), max(az)), PAGE_RGB[page], 0.95, 0.45))
    for name, (a0, a1), rgb, r, alpha in fans:
        pts = [Vector((eye.x, eye.y, z))]
        for k in range(17):
            a = a0 + (a1 - a0) * k / 16
            d = cm.direction(a, 0)
            pts.append(Vector((eye.x + d.x * r, eye.y + d.y * r, z)))
        m = clay("m_" + name, rgb, 0.5, emit=rgb, alpha=alpha)
        m.blend_method = "BLEND" if hasattr(m, "blend_method") else None
        mesh_obj(name, pts, [[0, k, k + 1] for k in range(1, 17)], m, coll)


def label_displays(coll, displays, eye_of):
    for name, page, quad, _ in displays:
        c = sum(quad, Vector()) / 4
        n = (quad[1] - quad[0]).cross(quad[3] - quad[0]).normalized()
        eye = eye_of(name)
        if n.dot(eye - c) < 0:
            n = -n
        cu = bpy.data.curves.new("lbl_" + name, "FONT")
        cu.body = page.upper()
        cu.align_x, cu.align_y = "CENTER", "CENTER"
        cu.size = 0.028 if page != "radar" else 0.05
        t = bpy.data.objects.new("lbl_" + name, cu)
        right = (quad[1] - quad[0]).normalized()
        up = n.cross(right).normalized()
        if up.z < 0:
            up, right = -up, -right
        t.matrix_world = Matrix.Translation(c + n * 0.002) @ Matrix((right, up, n)).transposed().to_4x4()
        t.data.materials.append(clay("lbl", (1, 1, 1), 0.5, emit=(1, 1, 1)))
        coll.objects.link(t)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--today", action="store_true", help="also render today's interior in clay from the same views")
    ap.add_argument("--measure-only", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene

    m_kept, m_new = clay("bo_kept", (0.42, 0.42, 0.43)), clay("bo_new", (0.66, 0.66, 0.64))
    mats = {"panel": m_new, "bezel": clay("bo_bezel", (0.22, 0.22, 0.23)), "keys": clay("bo_keys", (0.30, 0.30, 0.30)),
            "hood": m_new, "console": m_new, "overhead": m_new, "module": clay("bo_module", (0.33, 0.33, 0.34)),
            "knob": clay("bo_knob", (0.12, 0.12, 0.12)), "slot": clay("bo_slot", (0.05, 0.05, 0.05)),
            "lever": clay("bo_lever", (0.85, 0.75, 0.20)), "display": clay("bo_display", (0, 0, 0))}

    # today's objects: exterior hidden as in cockpit view, today's interior kept for measuring and the --today renders
    ext_objs = [O[n] for n in ("nose", "fuselage_F", "nose_hatch_L", "nose_hatch_R", "nose_door_visible")]
    ext = cm.exterior_trees(ext_objs)
    for n in ("nose", "radar_F_fairing", "nose_lod1", "radar_F_fairing_lod1"):
        if n in O:
            O[n].hide_render = True
    for o in O:
        if o.users_collection and o.users_collection[0].name in ("Colliders", "LOD1"):
            o.hide_render = True

    coll = bpy.data.collections.new("Blockout")
    scene.collection.children.link(coll)
    b = Builder(coll)
    displays = []
    edges_p = build_cluster(b, 1, PILOT, displays)
    edges_c = build_cluster(b, -1, COMMANDER, displays)
    build_centre(b, displays, edges_p, edges_c)
    build_consoles(b)
    build_pedestal(b)
    build_overhead(b)
    build_footwells(b)
    build_gear_handle(b, edges_p)
    page_mats = {p: clay("bo_page_" + p, (0.02, 0.02, 0.02), 0.3, emit=rgb) for p, rgb in PAGE_RGB.items()}
    for key in list(b.parts):
        if key.startswith("display:"):
            mats[key] = page_mats[key.split(":")[1]]
    built = {}
    for key, (v, f) in b.parts.items():
        mat = mats[key] if key in mats else mats[key.split(":")[0]]
        built[key] = mesh_obj("bo_" + key.replace(":", "_"), v, f, mat, coll)
    shell = kept_shell(coll, m_kept)
    # the kept parts: today's objects themselves, which today's measurement shares
    kept_opaque = [O[n] for n in ("band_bezel", "hatch_liner_L", "hatch_liner_R", "warning_lenses")] + \
        [o for o in O if o.name.startswith("stockref_Multirole1")]
    seats, dr_eye = stock_scene.import_stock(HERE.parents[2] / ".cache" / "art" / "cockpit" / "stock" / "darkreach", lambda p: p["name"] == "EjectionSeat",
                                             tag="_seat")
    # the Darkreach's left seat sits under its pilot's eye: move it so that eye lands on each Centurion eye
    pilot_seat = min(seats, key=lambda o: (o.matrix_world @ o.data.vertices[0].co - dr_eye).length)
    for o in seats:
        if o is not pilot_seat:
            bpy.data.objects.remove(o)
    seat_l = pilot_seat
    seat_l.data.transform(Matrix.Translation(EYE[1] - dr_eye))
    seat_r = seat_l.copy()
    seat_r.data = seat_l.data.copy()
    seat_r.data.transform(Matrix.Scale(-1, 4, Vector((1, 0, 0))))
    seat_r.data.flip_normals()
    for o in (seat_l, seat_r):
        for c in o.users_collection:
            c.objects.unlink(o)
        coll.objects.link(o)

    new_opaque = [o for k, o in built.items() if not k.startswith("display:")] + [shell, seat_l, seat_r]
    new_displays = [o for k, o in built.items() if k.startswith("display:")]
    cats_new = {"glass": cm.tree([O["glass_int"]]), "band": cm.tree([O["band"]]), "display": cm.tree(new_displays),
                "opaque": cm.tree(new_opaque + kept_opaque)}
    res_new = measure("blockout", cats_new, displays, out, ext)
    # today with the same seats, so the two tables differ only in the interior
    today_opaque = [O[n] for n in ("flightdeck_int", "labels")] + kept_opaque + [seat_l, seat_r]
    cats_today = {"glass": cats_new["glass"], "band": cats_new["band"], "display": cm.tree([O["tacScreen"]]),
                  "opaque": cm.tree(today_opaque)}
    res_today = measure("today", cats_today, [], out, ext)
    tris = {o.name: len(o.data.polygons) for o in new_opaque + new_displays}
    json.dump({"displays": [(n, p, [list(v) for v in q], px) for n, p, q, px in displays], "edges_pilot": edges_p,
               "edges_commander": edges_c, "faces": tris}, open(out / "blockout_layout.json", "w"), indent=1)
    for r in res_new["displays_pilot"]:
        print("NEW", r)
    print("NEWGRID", json.dumps(res_new["grid_pilot"]["share_pct"]), "TODAYGRID", json.dumps(res_today["grid_pilot"]["share_pct"]))
    print("LEAKS new", res_new["leaks_pilot"], res_new["leaks_commander"]["count_3deg"], "today", res_today["leaks_pilot"], res_today["leaks_commander"]["count_3deg"])
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "blockout.blend"), copy=True)
    if args.measure_only:
        return

    label_displays(coll, displays, lambda n: EYE[1] if n.endswith("pilot") or n == "engines" else EYE[-1])
    glass_az = (-90, 68)
    cones = bpy.data.collections.new("Cones")
    scene.collection.children.link(cones)
    view_cones(cones, [d for d in displays if d[0].endswith("pilot")], glass_az)
    setup_world(args.samples)
    today_coll = bpy.data.collections["Flightdeck"]
    clay_today = {}

    def show(build):
        for o in coll.objects:
            o.hide_render = build != "blockout" and o not in (seat_l, seat_r)
        for o in today_coll.objects:
            o.hide_render = build != "today" and o.name not in ("band", "band_bezel", "band_marker", "glass_int",
                                                                 "hatch_liner_L", "hatch_liner_R", "warning_lenses")
        O["labels"].hide_render = True
        for o in cones.objects:
            o.hide_render = True
        if build == "today" and not clay_today:
            clay_today["done"] = True
            fd = O["flightdeck_int"]
            for s in fd.material_slots:
                if s.material and s.material.name != "stockref_Matte_black":
                    s.material = m_kept if s.material.name in ("cc_cockpit_shell", "stockref_aircraft_structure") else m_new
            # today's displays in the same page colours, the wing display as a quad on its canvas pivot
            ts = O["tacScreen"]
            ts.data.materials.clear()
            keys = list(PAGE_RGB)
            for p in keys:
                ts.data.materials.append(page_mats[p])
            uv = ts.data.uv_layers.active.data
            rects = {"radar": (2.8, 146.1, 585.7, 488.5), "pfd": (289.8, 2.6, 521.4, 143.8),
                     "engines": (595.7, 257.0, 810.6, 509.4), "stores": (811.8, 191.8, 1012.2, 504.9)}
            for poly in ts.data.polygons:
                cu = sum(uv[l].uv.x for l in poly.loop_indices) / poly.loop_total * 1024
                cv = sum(uv[l].uv.y for l in poly.loop_indices) / poly.loop_total * 512
                page = next(k for k, (x0, y0, x1, y1) in rects.items() if x0 - 2 <= cu <= x1 + 2 and y0 - 2 <= cv <= y1 + 2)
                poly.material_index = keys.index(page)
            e = O["wing_display"]
            m3 = e.matrix_world.to_3x3()
            r, u, c = m3.col[0].normalized(), m3.col[2].normalized(), e.matrix_world.translation
            w, h = e["canvas_w"] / 2, e["canvas_h"] / 2
            wq = mesh_obj("today_wing", [c - r * w - u * h, c + r * w - u * h, c + r * w + u * h, c - r * w + u * h],
                          [[0, 1, 2, 3]], page_mats["wing"], today_coll)
            wq.location += (EYE[1] - c).normalized() * 0.003
    for view in args.views.split(","):
        seat, az, el, lens = VIEWS[view]
        loc = EYE[1] if seat == "pilot" else EYE[-1] if seat == "commander" else seat
        cam = view_cam("bo_cam_" + view, loc, az, el, lens or 18, ortho=3.1 if view == "plan" else None)
        for build in (("blockout", "today") if args.today else ("blockout",)):
            show(build)
            if view == "plan":  # the roof lifted off: the camera sits just under the lining, the overhead hidden
                for n in ("hatch_liner_L", "hatch_liner_R", "bo_overhead"):
                    O[n].hide_render = True
                for o in cones.objects:
                    o.hide_render = build != "blockout"  # the cones are the new layout's
                cam.location = P(6.05, 0.0, 5.10)
            render(out / ("%s_%s.png" % (build, view)), cam)


if __name__ == "__main__":
    main()
