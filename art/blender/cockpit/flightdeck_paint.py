"""The flight deck interior's maps and review renders (cockpit/flightdeck.py builds the geometry, flightdeck_uv.py lays
out the atlases, flightdeck_labels.py the legends).

Each PBR atlas is painted in numpy per texel from its baked world position, normal, paint class, pointiness and AO
(m4/texture.py's bake), so the paint follows the geometry wherever the pack put an island. Tones follow the stock
cockpit atlases as measured (.cache/cockpit/stock_measure/SPEC.md): mid greys (sRGB luminance about 70 to 80 on the
panels), near-black bezels and knobs, bare metal only on levers and toggles, metal map near 0 elsewhere. Relief
(switch plates, fasteners, rivets, seams, vents, tread, quilting, the bevel along every island edge) is painted as
height and turned into the tangent normal map; wear (chipped edges, polished contact areas, scratches), grime in the
AO's cavities and dust on the up-facing faces go into albedo and smoothness. The screen's scanline tile and the camera
marker are their own small maps."""

import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

import flightdeck_layout as fl
import flightdeck_uv as fuv
import flightdeck_kit as fk
import stock_reference
from m4 import render, texture
from m4.paint import fbm, normal_from_height, value_noise

REPO = Path(__file__).resolve().parents[3]
COMPOSITE_TEXTURES = REPO / ".cache" / "art" / "m4" / "textures"


def srgb(*c):
    return np.array(c, float) / 255.0


# class: (sRGB albedo, metal, smoothness)
BASE = {1: (srgb(84, 87, 90), 0.0, 0.36),  # lining: the hull's painted skin panels and stringers
        2: (srgb(50, 51, 50), 0.0, 0.24),  # floor
        3: (srgb(108, 112, 116), 0.0, 0.46),  # panel
        4: (srgb(104, 108, 112), 0.0, 0.45),  # console tops and walls
        5: (srgb(70, 73, 77), 0.0, 0.42),  # window and hatch trims
        6: (srgb(27, 28, 30), 0.0, 0.50),  # bezels
        7: (srgb(76, 80, 84), 0.0, 0.40),  # racks and the aft wall
        8: (srgb(24, 24, 25), 0.0, 0.42),  # knobs and keys
        9: (srgb(170, 172, 175), 0.9, 0.64),  # bare metal: toggles, levers, pedals
        10: (srgb(200, 156, 28), 0.0, 0.42),  # handles and guards
        11: (srgb(34, 34, 34), 0.0, 0.22),  # grips, pads and hoses
        12: (srgb(104, 108, 112), 0.0, 0.45),  # overhead
        13: (srgb(80, 84, 88), 0.0, 0.42),  # the hatches' liners
        14: (srgb(74, 77, 81), 0.0, 0.40),  # the hull frames
        15: (srgb(20, 20, 21), 0.0, 0.35)}  # the arming switch's hatched plate (the kit paints its bands)
MODULE = srgb(78, 81, 85)  # switch plates
BARE = srgb(188, 190, 194)  # aluminium under chipped paint
CHIP = srgb(34, 34, 36)  # the dark primer and grime a chipped edge shows, as on the stock cockpits
FASTENER = srgb(96, 98, 102)
GRIME = srgb(52, 44, 34)
DUST = srgb(122, 118, 108)
GUARD_RED = srgb(150, 26, 20)
HAZARD_YELLOW = srgb(206, 160, 26)
PAINTED = (3, 4, 5, 7, 12, 13, 14)  # painted metal classes: chips show bare aluminium (the lining's island
# edges are seams across its skin, not edges)
EDGE_PX = 16


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def rrect(u, v, u0, u1, v0, v1, r):
    cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
    hu, hv = abs(u1 - u0) / 2 - r, abs(v1 - v0) / 2 - r
    qu, qv = np.abs(u - cu) - hu, np.abs(v - cv) - hv
    return np.hypot(np.maximum(qu, 0), np.maximum(qv, 0)) + np.minimum(np.maximum(qu, qv), 0) - r


def edge_distance(island, n=EDGE_PX):
    """Per texel, its distance in texels to the nearest texel outside its island, up to n (0 outside)."""
    d = np.zeros(island.shape, float)
    cur = island.copy()
    for k in range(1, n + 1):
        er = cur.copy()
        er[1:] &= cur[:-1]
        er[:-1] &= cur[1:]
        er[:, 1:] &= cur[:, :-1]
        er[:, :-1] &= cur[:, 1:]
        d[cur & ~er] = k - 0.5
        cur = er
    d[cur] = n
    return d


def box_blur(img, r):
    """A (2r+1) square box blur of a 2D image, edges clamped."""
    k = 2 * r + 1
    p = np.pad(img, r, mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


class Atlas:
    """Paint layers over the valid texels of one slot's baked buffers."""

    def __init__(self, buf, density_img, y0):
        self.valid = sel = buf["valid"]
        self.pos, self.nrm, self.cls = buf["pos"][sel], buf["nrm"][sel], buf["cls"][sel]
        self.ao, self.curv = buf["ao"][sel], buf["curv"][sel]
        self.n = int(sel.sum())
        self.dens = density_img[sel]
        self.px = 1.0 / self.dens  # metres per texel
        self.edge = edge_distance(buf["island"])[sel] * self.px  # metres to the island's edge
        self.albedo = np.zeros((self.n, 3))
        self.metal, self.smooth, self.height = np.zeros(self.n), np.zeros(self.n), np.zeros(self.n)
        for k, (rgb, m, s) in BASE.items():
            on = self.cls == k
            self.albedo[on], self.metal[on], self.smooth[on] = rgb, m, s
        self.s = self.pos[:, 1] + y0  # station

    def on(self, *classes):
        return np.isin(self.cls, classes)

    def paint(self, cov, rgb=None, smooth=None, metal=None, height=None):
        cov = np.clip(cov, 0, 1)
        if rgb is not None:
            self.albedo += (np.asarray(rgb) - self.albedo) * cov[:, None]
        if smooth is not None:
            self.smooth += (smooth - self.smooth) * cov
        if metal is not None:
            self.metal += (metal - self.metal) * cov
        if height is not None:
            self.height += height * cov

    def fill(self, sdf, mask=1.0):
        return smoothstep(self.px * 0.7, -self.px * 0.7, sdf) * mask

    def line(self, d, width, mask=1.0):
        return smoothstep(width / 2 + self.px * 0.7, width / 2 - self.px * 0.7, d) * mask

    def groove(self, d, mask, width=0.0025, depth=-0.0008, darken=0.5):
        c = self.line(d, width, mask)
        self.albedo *= (1 - darken * c)[:, None]
        self.smooth -= 0.1 * c
        self.height += depth * smoothstep(width / 2 + self.px, 0.0, d) * mask

    def fastener(self, u, v, cu, cv, r, mask, kind="screw", angle=0.0):
        """A fastener head at (cu, cv) in a face's (u, v) metres: screw (domed, cross recess), dzus (flush ring and a
        quarter-turn slot) or rivet (a low dome in the surface's own paint)."""
        du, dv = u - cu, v - cv
        d = np.hypot(du, dv)
        inside = self.fill(d - r, mask)
        if not inside.any():
            return
        t = np.clip(d / r, 0, 1)
        if kind == "rivet":
            self.height += inside * 0.0004 * np.sqrt(1 - t * t)
            self.albedo *= (1 - 0.18 * self.line(np.abs(d - r), 0.0006, mask))[:, None]
            return
        self.paint(inside, rgb=FASTENER, metal=0.7, smooth=0.48)
        self.height += inside * (0.0006 * np.sqrt(1 - t * t) if kind == "screw" else 0.0002)
        ca, sa = math.cos(angle), math.sin(angle)
        a = du * ca + dv * sa
        b = -du * sa + dv * ca
        w = r * 0.22
        slot = (np.abs(b) < w / 2) & (np.abs(a) < r * 0.75)
        if kind == "screw":
            slot |= (np.abs(a) < w / 2) & (np.abs(b) < r * 0.75)
        cut = slot * inside
        self.albedo *= (1 - 0.7 * cut)[:, None]
        self.height -= cut * 0.0005
        ring = self.line(np.abs(d - r), 0.0008, mask)
        self.albedo *= (1 - 0.55 * ring)[:, None]
        if kind == "dzus":
            self.albedo *= (1 - 0.35 * self.line(np.abs(d - r * 0.62), 0.0006, mask))[:, None]


# ---------------- frames on surfaces ----------------
def panel_uv(cv, fd):
    """(arc metres, positive toward +X; height) on the panel's cylinder."""
    phi = np.arctan2(cv.pos[:, 0], fd.st(fd.BAND_AXIS_S) - cv.pos[:, 1])
    return phi * fd.PANEL_R, cv.pos[:, 2]


def plate_frame(cv, c, n, t, tol):
    """(u, v) in a plate's frame (u to the reader's right, v up), and the texels on its plane facing its way."""
    c, n, t = np.asarray(c), np.asarray(n), np.asarray(t)
    right = np.cross(t, n)
    d = cv.pos - c
    on = (np.abs(d @ n) < tol) & (cv.nrm @ n > 0.6)
    return d @ right, d @ t, on


def draw_plates(cv, plates):
    """The switch plates the builders registered (flightdeck_labels.Labels.plate, modelled by
    flightdeck_detail.build_plates): each its own shade of the plate grey, a dark line where it meets the surface,
    fasteners at its corners; hazard plates in yellow and black bands; lever slots recessed."""
    for i, p in enumerate(plates):
        u, v, on = plate_frame(cv, p["c"], p["n"], p["t"], p["tol"])
        w, h = p["w"], p["h"]
        on &= (np.abs(u) < w / 2 + 0.01) & (np.abs(v) < h / 2 + 0.01)
        if not on.any():
            continue
        m = on.astype(float)
        if p["kind"] == "round":
            sdf = np.hypot(u, v) - w / 2
        else:
            sdf = rrect(u, v, -w / 2, w / 2, -h / 2, h / 2, min(0.006, w / 4, h / 4))
        inside = cv.fill(sdf, m)
        if p["kind"] == "slot":
            cv.paint(inside, rgb=srgb(12, 12, 12), smooth=0.15, height=-0.004)
            brush = (np.abs(((v * 900.0) % 1.0) - 0.5) < 0.2) * inside
            cv.albedo *= (1 - 0.3 * brush)[:, None]
            continue
        if p["kind"] == "hazard":
            hazard(cv, inside, u + v, period=0.02)
            continue
        tint = 0.94 + 0.12 * ((i * 0.618) % 1.0)
        cv.paint(inside, rgb=(p["rgb"] if p["rgb"] is not None else MODULE) * tint, smooth=0.38, metal=0.0)
        cv.albedo *= (1 - 0.5 * cv.line(np.abs(sdf - 0.0004), 0.0012, m))[:, None]
        if p["kind"] == "module" and h > 0.07:  # a label strip along its top edge, as the stock panels carry
            strip = cv.fill(np.maximum(sdf + 0.004, h / 2 - 0.018 - v), m)
            cv.paint(strip * 0.85, rgb=MODULE * 0.62, smooth=0.3)
        if p["kind"] == "module" and min(w, h) > 0.05:
            inset = 0.009
            for su in (-1, 1):
                for sv in (-1, 1):
                    cv.fastener(u, v, su * (w / 2 - inset), sv * (h / 2 - inset), 0.0042, m, "dzus",
                                angle=math.radians(25 + 40 * ((i + su + 2 * sv) % 3)))


def hazard(cv, mask, along, period=0.05):
    """Yellow and black diagonal bands: along is a coordinate that runs across the bands."""
    band = ((along / period) % 1.0) < 0.5
    cv.paint(mask * band, rgb=srgb(14, 14, 14), smooth=0.3)
    cv.paint(mask * ~band, rgb=HAZARD_YELLOW, smooth=0.3)


# ---------------- areas ----------------
def paint_panel(cv, fd):
    """The main panel: rivet rows along its lips, seams between the display modules, the wings' rivet columns; the
    screen housing's seams, screws, grain and finish; the keys' worn tops."""
    P = cv.on(fd.PANEL).astype(float)
    if not P.any() and not cv.on(fd.BEZEL).any():
        return
    arc, z = panel_uv(cv, fd)
    layout = fd.display_layout()
    face = P * (np.abs(cv.nrm[:, 2]) < 0.5)
    mids = [(math.radians(a) * fd.PANEL_R - (wa / 2 + fd.BEZEL_SIDE) + math.radians(b) * fd.PANEL_R + (wb / 2 + fd.BEZEL_SIDE)) / 2
            for (a, wa), (b, wb) in zip(layout, layout[1:])]  # halfway across the gap between neighbouring bezels
    for m in mids:  # seams between the display modules, under the screen
        cv.groove(np.abs(arc - m), face * (z < fd.BAND_Z[0] - 0.004), width=0.0022)
    phi_b = math.radians(fd.band_phi()) * fd.PANEL_R
    for sgn in (1, -1):  # the seam where each wing meets the centre section, and the wing's own module seam
        for a in (phi_b + 0.004, phi_b + 0.20):
            cv.groove(np.abs(arc - sgn * a), face, width=0.0022)
    pitch = 0.028
    k = np.round(arc / pitch) * pitch
    for zz in (fd.KNEE_Z + 0.010,):  # a rivet row along the knee edge
        cv.fastener(arc, z, k, zz, 0.0016, face * (np.abs(arc) < phi_b), "rivet")
    wing = face * (np.abs(arc) > phi_b + 0.02)
    kz = np.round(z / pitch) * pitch
    for a in (phi_b + 0.012, phi_b + 0.19, phi_b + 0.212):
        for sgn in (1, -1):
            cv.fastener(arc, z, sgn * a, kz, 0.0016, wing, "rivet")
    # the screen's housing (its bolts are modelled): seams splitting the frame and hood into three sections with a
    # screw either side, rivets along the hood's top, a fine cast grain and a satin finish that varies over it
    S = cv.on(fd.BEZEL).astype(float) * (z > fd.BAND_Z[0] - fd.BEZEL_W - 0.006)
    arc_b = np.arctan2(cv.pos[:, 0], fd.st(fd.BAND_AXIS_S) - cv.pos[:, 1]) * fd.BAND_R
    for a in (-0.275, 0.275):
        cv.groove(np.abs(arc_b - a), S, width=0.0015, depth=-0.0005, darken=0.6)
        for d in (-0.008, 0.008):
            for zz in (fd.BAND_Z[0] - fd.BEZEL_W / 2, fd.BAND_Z[1] + fd.BEZEL_W / 2):
                cv.fastener(arc_b, z, a + d, zz, 0.0016, S * (np.abs(cv.nrm[:, 2]) < 0.5), "screw", angle=0.5)
    hood = S * (cv.nrm[:, 2] > 0.6) * (z > fd.BAND_Z[1] + fd.BEZEL_W)
    cv.fastener(arc_b, z, np.round(arc_b / 0.06) * 0.06, fd.BAND_Z[1] + fd.BEZEL_W + 0.007,
                0.0014, hood, "rivet")
    cv.height += S * 0.00005 * (value_noise(cv.pos, 0.0009, seed=71) - 0.5)
    cv.smooth += S * 0.14 * (fbm(cv.pos, 0.05, 2, seed=72) - 0.5)
    # keys: lighter and smoother where thumbs press
    K = cv.on(fd.KNOB).astype(float) * (np.abs(cv.nrm[:, 2]) < 0.5)
    cv.paint(K * 0.6, rgb=srgb(44, 45, 47))
    cv.paint(K * smoothstep(0.0, 0.004, cv.edge) * 0.5, smooth=0.55)


def paint_consoles(cv, fd):
    """Console tops' inboard rivet rail, the inner walls' rivets, seams and kick scuffs, the pedestal's sides, the
    overhead's sides; red guards; brushed toggles; knurled knobs."""
    x, s, z = cv.pos[:, 0], cv.s, cv.pos[:, 2]
    C = cv.on(fd.CONSOLE, fd.OVERHEAD).astype(float)
    top = C * (cv.nrm[:, 2] > 0.8)
    xo = np.abs(x)
    pitch = 0.035
    ks = np.round(s / pitch) * pitch
    # the console and pedestal tops show only in the seams between their panels: dark there
    floor = top * ((np.abs(z - fd.CONSOLE_TOP) < 0.002) * (xo > fd.CONSOLE_X) + (np.abs(z - fd.PEDESTAL_TOP) < 0.002) * (xo < fd.PEDESTAL_X))
    cv.paint(floor, rgb=srgb(34, 35, 37), smooth=0.25)
    rail = top * (np.abs(z - fd.CONSOLE_TOP) < 0.01) * (xo > fd.CONSOLE_X)
    cv.fastener(xo, s, fd.CONSOLE_X + 0.026, ks, 0.0018, rail, "rivet")
    cv.groove(np.abs(xo - (fd.CONSOLE_X + 0.04)), rail, width=0.002)
    wall = C * (np.abs(cv.nrm[:, 0]) > 0.8)
    kz = np.round(z / pitch) * pitch
    cv.fastener(s, z, ks, fd.CONSOLE_TOP - 0.03, 0.0018, wall * (z > 4.0), "rivet")
    for seam_s in (5.85, 6.40):
        cv.groove(np.abs(s - seam_s), wall, width=0.0022)
        for d in (-0.012, 0.012):
            cv.fastener(s, z, seam_s + d, kz, 0.0016, wall * (z < fd.CONSOLE_TOP - 0.05), "rivet")
    # boots and knees scuff the walls' lower halves
    scuff = wall * smoothstep(4.15, 3.85, z) * (fbm(cv.pos, 0.12, 3, seed=21) > 0.55)
    cv.paint(scuff * 0.6, rgb=srgb(40, 40, 40), smooth=0.45)
    # the pedestal's forward face plate and its sides' seam
    ped = C * (np.abs(cv.nrm[:, 0]) > 0.8) * (xo < fd.PEDESTAL_X + 0.01)
    cv.fastener(s, z, ks, fd.PEDESTAL_TOP - 0.02, 0.0018, ped, "rivet")
    # guards red; toggles brushed; knobs knurled round their skirts
    H = cv.on(fd.HANDLE).astype(float)
    cv.paint(H, rgb=GUARD_RED, smooth=0.42)
    M = cv.on(fd.METAL).astype(float)
    brush = value_noise(cv.pos * np.array([1.0, 1.0, 60.0]), 0.01, seed=31)
    cv.smooth += M * (brush - 0.5) * 0.2
    K = cv.on(fd.KNOB).astype(float) * (np.abs(cv.nrm[:, 2]) < 0.6)
    ang = np.arctan2(cv.nrm[:, 1], cv.nrm[:, 0])
    knurl = (np.abs(((ang * 24 / math.pi) % 1.0) - 0.5) < 0.22) * K
    cv.height += knurl * 0.0003
    cv.albedo *= (1 - 0.25 * knurl)[:, None]


STRINGER_PITCH = 0.14  # metres of girth between the walls' stringers


def paint_shell(cv, fd):
    """The walls' bare structure: skin panels between the modelled frames, stringers along them riveted to the skin,
    lap joints halfway between frames; rivet rows down the frames' flanges; window trims, hazard bands round the hatch
    openings and on their liners' ribs; the floor's tread plate and worn walkway, the racks' vents, the shroud and
    glareshield matte black."""
    x, s, z = cv.pos[:, 0], cv.s, cv.pos[:, 2]
    L = cv.on(fd.LINING).astype(float)
    girth = np.arctan2(x, z - 3.45) * 1.9
    stations = np.array(fd.FRAME_STATIONS)
    near_frame = stations[np.argmin(np.abs(s[:, None] - stations[None, :]), axis=1)]
    ds = s - near_frame
    dg = np.abs(((girth + STRINGER_PITCH / 2) % STRINGER_PITCH) - STRINGER_PITCH / 2)  # from the nearest stringer
    stringer = L * (dg < 0.011)
    cv.height += 0.0025 * L * smoothstep(0.013, 0.009, dg)
    cv.paint(stringer * 0.4, rgb=BASE[14][0])
    kg = np.round(s / 0.03) * 0.03
    cv.fastener(dg, s, 0.0, kg, 0.0018, stringer, "rivet")
    lap = L * (np.abs(np.abs(ds) - 0.25) < 0.02)  # a lap joint halfway between frames, two rows of rivets
    cv.groove(np.abs(np.abs(ds) - 0.25), L, width=0.0015, depth=-0.0004, darken=0.35)
    kl = np.round(girth / 0.025) * 0.025
    for off in (0.24, 0.26):
        cv.fastener(np.abs(ds), girth, off, kl, 0.0017, lap, "rivet")
    panel = np.floor((s - 5.0) / 0.25) * 7 + np.floor(girth / STRINGER_PITCH)  # each skin panel its own shade
    cv.albedo *= (1 + 0.05 * L * (((panel * 0.618) % 1.0) - 0.5))[:, None]
    # the hull frames: a rivet row down the middle of each flange's inner face
    St = cv.on(fd.STRUCT).astype(float)
    flange = St * (np.abs(ds) < 0.008)
    cv.fastener(ds, girth, 0.0, np.round(girth / 0.03) * 0.03, 0.0019, flange, "rivet")
    # window and hatch frames: rivets on a lattice; hazard bands round the hatches
    F = cv.on(fd.FRAME).astype(float)
    hx0, hx1 = fl.HATCH_X
    hs0, hs1 = fl.HATCH_S
    # a narrow hatched strip round each hatch opening on its trim, as the stock cockpits mark theirs
    out = rrect(s, np.abs(x), hs0, hs1, hx0, hx1, fl.HATCH_CORNER)  # metres outside the opening, in plan
    strip = F * (z > 5.0) * (out > 0.012) * (out < 0.026)
    hazard(cv, strip, s + np.abs(x), period=0.016)
    # floor: diamond tread, a worn walkway between the seats and the hatch's outline
    Fl = cv.on(fd.FLOOR).astype(float)
    a, b = (x + s) / 0.03, (x - s) / 0.03
    da, db = np.abs((a % 1.0) - 0.5), np.abs((b % 1.0) - 0.5)
    dia = Fl * ((da < 0.12) ^ (db < 0.12))
    cv.height += dia * 0.0007
    walk = Fl * smoothstep(0.35, 0.10, np.abs(x)) * (fbm(cv.pos, 0.2, 3, seed=43) > 0.4)
    seat = Fl * smoothstep(0.30, 0.15, np.abs(np.abs(x) - fl.EYE_X)) * smoothstep(6.0, 6.2, s)
    cv.paint((walk + seat) * dia * 0.7, rgb=srgb(118, 118, 116), metal=0.6, smooth=0.5)
    h0, h1, hw = fl.FLOOR_HATCH
    cv.groove(np.abs(rrect(s, x, h0, h1, -hw, hw, 0.03)), Fl, width=0.006, depth=-0.002, darken=0.6)
    # racks: vent slots in the line-replaceable boxes' faces (their plates and screws are registered)
    R = cv.on(fd.RACK).astype(float) * (cv.nrm[:, 1] < -0.8)
    xo = np.abs(x)
    box = R * (s < 6.715) * (s > 6.69)
    zr = (z - fl.FLOOR_Z - 0.08) % 0.37
    vents = box * (zr > 0.17) * (zr < 0.29) * (((xo - 0.98) % 0.20) > 0.05) * (((xo - 0.98) % 0.20) < 0.17)
    slot = (np.abs(((z * 100.0) % 1.0) - 0.5) < 0.22) * vents
    cv.albedo *= (1 - 0.65 * slot)[:, None]
    cv.height -= slot * 0.0015
    # the hatch liners: stringers fore and aft, one cross rib at mid length, rivets along both
    Hl = cv.on(fd.HATCH).astype(float)
    dg = np.abs(((girth + 0.06) % 0.12) - 0.06)
    dx = np.abs(s - sum(fl.HATCH_S) / 2)
    cv.height += 0.002 * Hl * smoothstep(0.012, 0.008, dg) + 0.003 * Hl * smoothstep(0.016, 0.012, dx)
    cv.paint(Hl * (dx < 0.014) * 0.5, rgb=BASE[14][0])
    cv.fastener(dg, s, 0.0, np.round(s / 0.03) * 0.03, 0.0017, Hl * (dg < 0.01), "rivet")
    cv.fastener(dx, girth, 0.0, np.round(girth / 0.03) * 0.03, 0.0018, Hl * (dx < 0.012), "rivet")
    # the shroud and glareshield matte near-black
    sh = cv.on(fd.PANEL).astype(float)
    cv.paint(sh, rgb=srgb(22, 22, 23), smooth=0.1)
    # extinguisher red, hatch handles and the floor hatch's handle in hazard stripes
    H = cv.on(fd.HANDLE).astype(float)
    ext = H * (z < 4.3) * (s > 6.7)
    cv.paint(ext, rgb=srgb(160, 24, 18), smooth=0.5)
    hazard(cv, H * (1 - ext), x + z + s, period=0.03)


def finish(cv, slot):
    """Variation, wear, grime and dust over the layout, then clamp."""
    p = cv.pos
    mott = fbm(p, 0.6, 3, seed=3) - 0.5
    fine = value_noise(p, 0.04, seed=9) - 0.5
    cv.albedo *= (1 + 0.08 * mott + 0.03 * fine)[:, None]
    cv.smooth += 0.06 * (fbm(p, 0.25, 2, seed=7) - 0.5)
    # the bevel every island edge carries, read by the normal map as a rounded edge
    soft = ~cv.on(1, 2, 11)
    bevel = (1 - smoothstep(0.0, 0.0028, cv.edge)) * soft
    cv.height -= 0.0006 * bevel
    # chipped paint along convex edges, heavy as on the stock cockpits, heaviest within a hand's reach
    reach = smoothstep(4.95, 4.45, p[:, 2]) * smoothstep(0.0, 0.4, 1.4 - np.abs(np.abs(p[:, 0]) - 0.55))
    convex = smoothstep(0.50, 0.57, cv.curv)
    edge = (1 - smoothstep(0.0008, 0.007 + 0.004 * reach, cv.edge)) * np.maximum(convex, 0.45)
    chips = smoothstep(0.45 - 0.1 * reach, 0.6 - 0.1 * reach, value_noise(p, 0.005, seed=5) * 0.6 + fbm(p, 0.06, 2, seed=6) * 0.6)
    worn = np.clip(edge * chips * 2.2, 0, 1)
    painted = cv.on(*PAINTED).astype(float)
    # chips dark, as the stock cockpits wear: a sliver of bright metal at the very edge, primer and grime behind it
    cv.paint(worn * painted, rgb=CHIP, smooth=0.28)
    lip = (1 - smoothstep(0.0, 0.0012, cv.edge)) * worn * painted
    cv.paint(lip * 0.6, rgb=BARE, metal=0.7, smooth=0.55)
    # the controls hands work: knobs and keys polished grey at their edges, guards and handles chipped to dark primer
    touched = (1 - smoothstep(0.0, 0.004, cv.edge)) * smoothstep(0.35, 0.55, value_noise(p, 0.004, seed=7))
    cv.paint(np.clip(worn * 0.6 + touched * 0.7, 0, 1) * cv.on(6, 8, 11) * 0.7, rgb=srgb(70, 70, 72), smooth=0.62)
    cv.paint(np.clip(worn * 1.4, 0, 1) * cv.on(10), rgb=CHIP, metal=0.0, smooth=0.3)
    # a few fine scratches
    sc = np.zeros(cv.n)
    for k, d in enumerate(((1, 30, 30), (30, 1, 30), (30, 30, 1))):
        q = p * np.array(d, float)
        streak = np.abs(value_noise(q, 0.4, seed=50 + k) - 0.5) < 0.006
        sc = np.maximum(sc, streak * (fbm(p, 0.15, 2, seed=60 + k) > 0.72))
    sc = sc * cv.on(3, 4, 12, 2, 7, 13)
    cv.albedo *= (1 + 0.10 * sc)[:, None]
    cv.smooth += 0.10 * sc
    # grime in the cavities the AO finds, dust on what faces up
    grime = smoothstep(0.92, 0.45, cv.ao) * (0.55 + 0.45 * fbm(p, 0.3, 2, seed=11))
    cv.albedo = cv.albedo * (1 - 0.35 * grime[:, None]) + GRIME * 0.25 * grime[:, None]
    cv.smooth -= 0.12 * grime
    dust = smoothstep(0.6, 0.95, cv.nrm[:, 2]) * smoothstep(0.45, 0.75, fbm(p, 0.2, 3, seed=13)) * ~cv.on(9)
    cv.albedo += (DUST - cv.albedo) * (0.12 * dust)[:, None]
    cv.smooth -= 0.08 * dust
    cv.albedo = np.clip(cv.albedo, 0, 1)
    cv.smooth = np.clip(cv.smooth, 0.04, 0.9)
    cv.metal = np.clip(cv.metal, 0, 1)


SLOT_FILES = {fuv.PANEL_SLOT: "cockpit_panel", fuv.CONSOLE_SLOT: "cockpit_console", fuv.SHELL_SLOT: "cockpit_shell"}


def draw_hoses(cv, hoses):
    """Corrugations round the registered hoses: a ring every HOSE_PITCH along each, in the height map."""
    for pts, radius in hoses:
        pts = np.asarray(pts, float)
        best_d, best_t = np.full(cv.n, np.inf), np.zeros(cv.n)
        run = 0.0
        for a, b in zip(pts, pts[1:]):
            ab = b - a
            L2 = float(ab @ ab)
            t = np.clip(((cv.pos - a) @ ab) / L2, 0.0, 1.0)
            d = np.linalg.norm(cv.pos - (a + t[:, None] * ab), axis=1)
            closer = d < best_d
            best_d[closer], best_t[closer] = d[closer], run + t[closer] * math.sqrt(L2)
            run += math.sqrt(L2)
        on = (best_d < radius * 1.3) & cv.on(8, 11)
        ring = np.cos(2 * math.pi * best_t / HOSE_PITCH)
        cv.height += on * 0.0007 * ring
        cv.albedo *= (1 - 0.18 * on * (ring < -0.6))[:, None]


HOSE_PITCH = 0.007


AO_FLOOR = 0.5  # the darkest the AO map takes indirect light: the enclosed deck lives on it, the stock maps' medians are 0.5


def save_maps(cv, buf, density_img, folder, stem, size):
    """An atlas's albedo, metal-smoothness, normal (from the painted height) and AO (the baked AO darkened in the
    height's recesses) as <stem>_{b,m,n,ao}.png; returns their paths."""
    valid = buf["valid"]
    H = W = size
    albedo = np.zeros((H, W, 3)) + cv.albedo.mean(axis=0)
    ms = np.zeros((H, W, 4))
    ms[..., 3] = 0.3
    height = np.zeros((H, W))
    albedo[valid] = cv.albedo
    ms[valid, 0:3] = cv.metal[:, None]
    ms[valid, 3] = cv.smooth
    height[valid] = cv.height
    normal = normal_from_height(height, valid, density_img)
    cavity = np.clip((height - box_blur(height, 3)) * 400.0, -0.35, 0.1)  # recesses darken: 1 mm below its mean is -0.35
    ao = np.ones((H, W, 3))
    ao[valid] = np.clip((AO_FLOOR + (1 - AO_FLOOR) * buf["ao"][valid]) * (1 + cavity[valid]), 0, 1)[:, None]
    return {"albedo": texture.save_image(albedo, folder / f"{stem}_b.png", srgb=True),
            "metal_smooth": texture.save_image(ms, folder / f"{stem}_m.png"),
            "normal": texture.save_image(normal, folder / f"{stem}_n.png"),
            "ao": texture.save_image(ao, folder / f"{stem}_ao.png")}


def paint_slot(objs, slot, folder, fd, uvr, plates, hoses):
    """Bake one PBR slot's buffers, paint it, write <name>_{b,m,n,ao}.png; returns their paths."""
    size = fuv.ATLAS
    proxy = texture.make_proxy(objs, slot, {o.name: uvr["dead"][o.name] | uvr["mirrored"][o.name] for o in objs})
    buf = texture.bake_buffers(proxy, size, ao_samples=96, ao_distance=0.25)
    bpy.data.objects.remove(proxy)
    names = {v: k for k, v in fuv_class_names(fd).items()}
    dens_by_cls = {names[n]: d for n, d in uvr["density"][slot].items()}
    floor = min(dens_by_cls.values())
    density_img = np.full(buf["cls"].shape, floor, float)
    for k, d in dens_by_cls.items():
        density_img[buf["cls"] == k] = d
    cv = Atlas(buf, density_img, fd.Y0)
    if slot == fuv.PANEL_SLOT:
        paint_panel(cv, fd)
    elif slot == fuv.CONSOLE_SLOT:
        paint_consoles(cv, fd)
    else:
        paint_shell(cv, fd)
    draw_plates(cv, plates)
    draw_hoses(cv, hoses)
    finish(cv, slot)
    return save_maps(cv, buf, density_img, folder, SLOT_FILES[slot], size)


def fuv_class_names(fd):
    return {k: fuv.fd_class_name(fd, k) for k in range(1, 16)}


SCAN_TILE, SCAN_LINES, SCAN_TILE_M = 64, 8, 0.032  # a 64 px tile of 8 scanlines over 3.2 cm: a 4 mm period


def uv_band(obj, axis_s, r, y0):
    """The screen's UVs in metres of arc and height over SCAN_TILE_M, so the tile repeats at its physical size."""
    me = obj.data
    if "UVMap" not in me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uv = me.uv_layers["UVMap"].data
    mw = obj.matrix_world
    for p in me.polygons:
        for li in p.loop_indices:
            q = mw @ me.vertices[me.loops[li].vertex_index].co
            phi = math.atan2(q.x, (axis_s - y0) - q.y)
            uv[li].uv = (-phi * r / SCAN_TILE_M, q.z / SCAN_TILE_M)


def small_maps(folder):
    """The scanline tile (colour and alpha: lines darker and more opaque) and the camera marker (a red circle and EXT
    CAM in white on clear, full alpha where drawn; the material's alpha takes it to flightdeck.MARKER_OPACITY)."""
    t = SCAN_TILE
    row = (np.arange(t) + 0.5) % (t / SCAN_LINES) / (t / SCAN_LINES)
    line = smoothstep(0.55, 0.75, row) * smoothstep(1.0, 0.8, row)
    tile = np.ones((t, t, 4))
    tile[..., 0:3] = (1.0 - 0.55 * line)[:, None, None]
    tile[..., 3] = (0.75 + 0.25 * line)[:, None]
    band = texture.save_image(tile, folder / "cockpit_band.png", srgb=True)
    W, H = 256, 64
    img = np.zeros((H, W, 4))
    yy, xx = np.mgrid[0:H, 0:W] + 0.5
    circle = smoothstep(1.0, -1.0, np.hypot(xx - 30, yy - 32) - 18)
    img[..., 0:3] += circle[..., None] * np.array([0.95, 0.06, 0.04])
    img[..., 3] = np.maximum(img[..., 3], circle)
    m = texture.text_mask("EXT CAM", px_height=40)
    mh, mw = m.shape
    oy, ox = (H - mh) // 2, 60
    h_, w_ = min(mh, H - oy), min(mw, W - ox)
    text = np.zeros((H, W))
    text[oy:oy + h_, ox:ox + w_] = m[:h_, :w_]
    img[..., 0:3] = img[..., 0:3] * (1 - text[..., None]) + text[..., None] * 0.92
    img[..., 3] = np.maximum(img[..., 3], text)
    marker = texture.save_image(img, folder / "cockpit_marker.png", srgb=True)
    return {"band": band, "marker": marker}


# ---------------- review ----------------
PAGE_COLOURS = {"radar": (0.10, 0.55, 0.30), "pfd": (0.20, 0.45, 0.85), "gauges": (0.75, 0.55, 0.10), "engines": (0.80, 0.25, 0.20),
                "stores": (0.60, 0.30, 0.75)}


def canvas_test_image(path, fd):
    """The review's stand-in for the live tac screen canvas: each page of fd.PAGES tinted and outlined in its own colour
    and named, with TOP over the name, drawn the way the canvas draws that page (turned 90 deg where it turns), so a
    render shows which page each display carries, whole and which way up; the rest of the canvas dark."""
    W, H = fd.CANVAS
    img = np.zeros((H, W, 3)) + np.array([0.02, 0.02, 0.02])
    yy, xx = np.mgrid[0:H, 0:W] + 0.5
    for key, ((x0, y0, x1, y1), turned) in fd.PAGES.items():
        col = np.array(PAGE_COLOURS[key])
        inside = (xx > x0) & (xx < x1) & (yy > y0) & (yy < y1)
        edge = np.minimum.reduce([np.abs(xx - x0), np.abs(xx - x1), np.abs(yy - y0), np.abs(yy - y1)])
        img[inside] = col * 0.25
        img[inside & (edge < 3)] = col
        name, up = texture.text_mask(key.upper(), px_height=60), texture.text_mask("TOP", px_height=40)
        w = max(name.shape[1], up.shape[1])
        stack = np.zeros((name.shape[0] + up.shape[0], w))  # rows run bottom-up: the name below, TOP above
        stack[:name.shape[0], (w - name.shape[1]) // 2:(w - name.shape[1]) // 2 + name.shape[1]] = name
        stack[name.shape[0]:, (w - up.shape[1]) // 2:(w - up.shape[1]) // 2 + up.shape[1]] = up
        if turned:  # the canvas draws this page turned: its top toward -x
            stack = np.rot90(stack, -1)
        k = min(0.8 * (x1 - x0) / stack.shape[1], 0.8 * (y1 - y0) / stack.shape[0], 1.0)
        hs, ws = max(1, int(stack.shape[0] * k)), max(1, int(stack.shape[1] * k))
        ri = (np.arange(hs) / k).astype(int).clip(0, stack.shape[0] - 1)
        ci = (np.arange(ws) / k).astype(int).clip(0, stack.shape[1] - 1)
        small = stack[ri][:, ci]
        oy, ox = int((y0 + y1) / 2 - hs / 2), int((x0 + x1) / 2 - ws / 2)
        img[oy:oy + hs, ox:ox + ws] = img[oy:oy + hs, ox:ox + ws] * (1 - small[..., None]) + small[..., None] * np.array([0.95, 0.95, 0.9])
    return texture.save_image(img, path, srgb=True)


def node_material(name, build):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(build(nt), out.inputs["Surface"])
    return m


def image_node(nt, path, data=False):
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = texture.load_image(path, data=data)
    return t


def look(objs, maps, folder, fd):
    """Review materials: the composite in its baked maps, each interior atlas, the labels cut out with their powered
    legends glowing, the screen as alpha blending over the world, the marker, the inner glass clear, the displays a
    stand-in glow."""
    render.style_shared({"skin": "Centurion_skin", "struct": "aircraft_structure", "mech": "jet_mechanical", "glass": "glass",
                         "gear": "Centurion_gear"}, (0.38, 0.39, 0.405))
    skin_maps = {"albedo": COMPOSITE_TEXTURES / "centurion_b.png", "ao": COMPOSITE_TEXTURES / "centurion_ao.png",
                 "metal_smooth": COMPOSITE_TEXTURES / "centurion_m.png", "normal": COMPOSITE_TEXTURES / "centurion_n.png"}
    skin = render.preview_material("cc_skin_preview", skin_maps)
    for o in bpy.data.objects:
        if o.type == "MESH":
            for slot in o.material_slots:
                if slot.material and slot.material.name == "Centurion_skin":
                    slot.link = "OBJECT"
                    slot.material = skin
    mats = {}
    for slot in fuv.PBR_SLOTS:
        if slot in maps:
            mats[slot] = render.preview_material("cc_" + SLOT_FILES[slot], maps[slot])
        else:
            mats[slot] = bpy.data.materials.new("cc_flat_" + slot)
            render.principled(mats[slot], (0.07, 0.075, 0.08), 0.65, 0.0)
    mats.update(stock_reference.stock_materials())
    if fk.KIT_SLOT in maps:
        mats[fk.KIT_SLOT] = render.preview_material("cc_cockpit_kit", maps[fk.KIT_SLOT])

    def band(nt):
        uvn = nt.nodes.new("ShaderNodeUVMap")
        uvn.uv_map = "UVMap"
        tile = image_node(nt, maps["band"])
        tile.interpolation = "Closest"
        nt.links.new(uvn.outputs["UV"], tile.inputs["Vector"])
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        tint = nt.nodes.new("ShaderNodeMix")
        tint.data_type, tint.blend_type = "RGBA", "MULTIPLY"
        tint.inputs["Factor"].default_value = 1.0
        tint.inputs["A"].default_value = (0.80, 0.92, 0.95, 1)
        nt.links.new(tile.outputs["Color"], tint.inputs["B"])
        nt.links.new(tint.outputs["Result"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.8
        alpha = nt.nodes.new("ShaderNodeMath")
        alpha.operation = "MULTIPLY"
        alpha.inputs[1].default_value = 0.25
        nt.links.new(tile.outputs["Alpha"], alpha.inputs[0])
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(alpha.outputs[0], mix.inputs["Fac"])
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(bsdf.outputs[0], mix.inputs[2])
        return mix.outputs[0]

    def cutout(nt, image_key, opacity, emission_key=None):
        uvn = nt.nodes.new("ShaderNodeUVMap")
        uvn.uv_map = "UVMap"
        img = image_node(nt, maps[image_key])
        nt.links.new(uvn.outputs["UV"], img.inputs["Vector"])
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.7
        if emission_key:
            em = image_node(nt, maps[emission_key])
            nt.links.new(uvn.outputs["UV"], em.inputs["Vector"])
            nt.links.new(em.outputs["Color"], bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = 3.0
        alpha = nt.nodes.new("ShaderNodeMath")
        if opacity is None:  # a cutout at half coverage, as URP's alpha clipping
            alpha.operation = "GREATER_THAN"
            alpha.inputs[1].default_value = 0.5
        else:
            alpha.operation = "MULTIPLY"
            alpha.inputs[1].default_value = opacity
        nt.links.new(img.outputs["Alpha"], alpha.inputs[0])
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(alpha.outputs[0], mix.inputs["Fac"])
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(bsdf.outputs[0], mix.inputs[2])
        return mix.outputs[0]

    def glass(nt):
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        tr.inputs["Color"].default_value = (0.93, 0.95, 0.94, 1)
        gl = nt.nodes.new("ShaderNodeBsdfGlossy")
        gl.inputs["Roughness"].default_value = 0.05
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.inputs["Fac"].default_value = 0.05
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(gl.outputs[0], mix.inputs[2])
        return mix.outputs[0]

    standin = canvas_test_image(folder / "review_canvas_pages.png", fd)

    def display(nt):
        uvn = nt.nodes.new("ShaderNodeUVMap")
        uvn.uv_map = "UVMap"
        img = image_node(nt, standin)
        nt.links.new(uvn.outputs["UV"], img.inputs["Vector"])
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Strength"].default_value = 2.0
        nt.links.new(img.outputs["Color"], em.inputs["Color"])
        return em.outputs[0]

    mats.update({"Centurion_band": node_material("cc_band_review", band),
                 "Centurion_band_marker": node_material("cc_marker_review", lambda nt: cutout(nt, "marker", fd.MARKER_OPACITY)),
                 "canopy_int": node_material("cc_glass_review", glass),
                 "tacScreenDisplay": node_material("cc_display_review", display)})
    if "labels" in maps:
        mats[fd.LABEL_SLOT] = node_material("cc_labels_review", lambda nt: cutout(nt, "labels", None))
        mats[fd.LEGEND_SLOT] = node_material("cc_legends_review", lambda nt: cutout(nt, "labels", None, "labels_emission"))
    for o in objs.values():
        for slot in o.material_slots:
            m = slot.material
            if m is not None and m.name in mats:
                slot.link = "OBJECT"
                slot.material = mats[m.name]


def short_final(fd, pitch_deg=6.0, glide_deg=3.0, dist_m=2000.0, threshold_m=300.0):
    """Ground and a 3,000 x 45 m runway as the pilot sees them on final: dist_m short of the aim point on a glide_deg
    path, pitched pitch_deg nose up; the aircraft stays put and the ground turns about the eye."""
    import bmesh
    earth = bpy.data.objects.new("cc_earth", None)
    earth.location = fd.eye(1)
    earth.rotation_euler = (math.radians(pitch_deg), 0, 0)
    bpy.context.scene.collection.objects.link(earth)
    h = dist_m * math.tan(math.radians(glide_deg))
    made = []
    for name, centre, size, rgb in (("cc_grass", (0, -dist_m, -h - 0.05), (30000, 30000, 0.02), (0.12, 0.30, 0.08)),
                                    ("cc_runway", (0, -(dist_m - threshold_m) - 1500, -h), (45, 3000, 0.02), (0.02, 0.02, 0.02))):
        bm = bmesh.new()
        r = bmesh.ops.create_cube(bm, size=1.0)
        for v in r["verts"]:
            v.co = Vector((centre[0] + v.co.x * size[0], centre[1] + v.co.y * size[1], centre[2] + v.co.z * size[2]))
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        m = bpy.data.materials.new(name)
        render.principled(m, rgb, 0.9, 0.0)
        me.materials.append(m)
        o = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(o)
        o.parent = earth
        made.append(o)
    return made


def camera(name, loc, target=None, rot=None, lens=18.0):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    cam.data.lens, cam.data.clip_start, cam.data.clip_end = lens, 0.01, 40000
    cam.location = Vector(loc)
    cam.rotation_euler = rot if rot is not None else (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(cam)
    return cam


def shoot(cam, path, samples, res=(1600, 900), engine="CYCLES"):
    """engine EEVEE lights like the game's URP: the sun with shadows, the sky's ambient unoccluded but for the AO maps,
    where Cycles' path tracing leaves an enclosed flight deck far darker than the game draws it."""
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.engine = "BLENDER_EEVEE" if engine == "EEVEE" else "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.eevee.taa_render_samples = samples
    scene.eevee.use_shadows = True
    scene.eevee.use_raytracing = False
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = *res, 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)
    scene.view_settings.view_transform = "AgX"
    scene.render.film_transparent = False
    bpy.ops.render.render(write_still=True)
    print("RENDER", path)
    return Path(path)


# lit like the game's cockpit: daylight through the panes, no studio fill, in EEVEE
CLOSE_UPS = ("p", "k", "o", "q", "r", "s", "j", "h", "u", "zpl", "zpr", "zcl", "zcr", "g0", "g1", "g2", "g3", "g4", "g5")


def review(objs, maps, views, samples, out, fd, edges):
    """The owner's review renders: d the pilot's eye on short final, w the flight deck from the aft wall, m the screen's
    outboard end and marker from the pilot's eye, e the hatches and door from above, x and y the crew door open and
    closed, v the vestibule, c the commander's seat; the close-ups p the panel, k the pilot's console, o the overhead,
    z<seat><end> each end of the screen's frame from each seat (p pilot, c commander; l the +X end, r the -X end), g0 to
    g5 each display from the pilot's eye in DISPLAY_ORDER, all at one scale."""
    if not views or views == [""]:
        return []
    look(objs, maps, out, fd)
    scene = bpy.context.scene
    render.use_gpu(scene) if not render.game_running() else None
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.62, 0.68, 0.76, 1)  # a neutral, slightly blue daylight sky
    bg.inputs["Strength"].default_value = 1.0
    sun = bpy.data.objects.new("cc_sun", bpy.data.lights.new("cc_sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.5, math.radians(2)
    sun.rotation_euler = (math.radians(40), math.radians(-20), math.radians(150))
    scene.collection.objects.link(sun)
    # the review views also get a soft fill under the roof and the vestibule's dome light; the close-ups do not
    fill = bpy.data.objects.new("cc_fill", bpy.data.lights.new("cc_fill", "AREA"))
    fill.data.energy, fill.data.size = 40, 1.2
    fill.location = Vector((0, fd.st(6.8), 5.30))
    fill.visible_camera = False
    scene.collection.objects.link(fill)
    dome = bpy.data.objects.new("cc_vestibule", bpy.data.lights.new("cc_vestibule", "POINT"))
    dome.data.energy, dome.data.shadow_soft_size = 25, 0.1
    dome.location = Vector((1.1, fd.st(6.40), 3.45))
    scene.collection.objects.link(dome)
    stock_parts(objs, fd)
    ground = short_final(fd)
    me = bpy.data.meshes.new("cc_apron")
    me.from_pydata([(-200, -200, 0), (200, -200, 0), (200, 200, 0), (-200, 200, 0)], [], [(0, 1, 2, 3)])
    gm = bpy.data.materials.new("cc_apron")
    render.principled(gm, (0.16, 0.16, 0.155), 0.85, 0.0)
    me.materials.append(gm)
    apron = bpy.data.objects.new("cc_apron", me)
    scene.collection.objects.link(apron)
    hinge = bpy.data.objects.get("nose_door")
    rest = hinge.rotation_euler.copy() if hinge else None
    open_angle = door_open_angle(hinge) if hinge else 0.0
    eye = fd.eye(1)
    st = fd.st
    shots = {
        "d": (camera("cc_d", eye, rot=(math.radians(90), 0, math.radians(180)), lens=18.0), "short_final_pilot_eye"),
        "w": (camera("cc_w", (0.0, st(6.90), 5.15), target=(0.0, st(4.9), 4.75), lens=11.0), "wide_interior"),
        "m": (camera("cc_m", eye, target=fd.cyl(fd.band_phi() - 4, fd.BAND_Z[0] + 0.06), lens=30.0), "screen_and_camera_marker"),
        "e": (camera("cc_e", (3.2, st(10.5), 9.4), target=(0.0, st(6.2), 5.3), lens=38.0), "escape_hatches"),
        "x": (camera("cc_x", (4.4, st(9.0), 2.75), target=(1.2, st(6.35), 2.7), lens=26.0), "crew_door_open"),
        "y": (camera("cc_y", (4.4, st(9.0), 2.75), target=(1.2, st(6.35), 2.7), lens=26.0), "crew_door_closed"),
        "v": (camera("cc_v", (4.3, st(6.75), 2.85), target=(0.6, st(6.55), 2.75), lens=22.0), "vestibule_steps_and_ladder"),
        "c": (camera("cc_c", fd.eye(-1), rot=(math.radians(90), 0, math.radians(180)), lens=18.0), "commander_seat"),
        "p": (camera("cc_p", eye, target=fd.cyl(6.0, 4.52, fd.PANEL_R), lens=32.0), "closeup_panel"),
        "k": (camera("cc_k", eye + Vector((0.0, 0.05, 0.0)), target=(1.22, st(6.30), fd.CONSOLE_TOP), lens=26.0), "closeup_console"),
        "q": (camera("cc_q", eye, rot=(math.radians(76), 0, math.radians(180)), lens=16.0), "pilot_eye_wide"),
        "r": (camera("cc_r", (0.0, st(6.45), 4.66), target=fd.cyl(0.0, 4.60, fd.PANEL_R), lens=17.0), "displays_page_test"),
        "s": (camera("cc_s", eye + Vector((0.05, 0.20, 0.06)), target=fd.cyl(fd.band_phi() - 2.0, fd.BAND_Z[1] + 0.01,
                                                                                 fd.BAND_R - fd.BEZEL_DEPTH), lens=40.0),
              "closeup_screen_edge"),
        "o": (camera("cc_o", eye + Vector((-0.05, 0.10, -0.05)), target=(0.0, st(6.05), 5.30), lens=24.0), "closeup_overhead"),
        "j": (camera("cc_j", eye, target=fd.cyl(0.0, fd.BAND_Z[1] + fd.BEZEL_W + 0.03, fd.BAND_R - fd.BEZEL_DEPTH + 0.05), lens=60.0), "post_foot_pilot"),
        "h": (camera("cc_h", fd.eye(-1), target=fd.cyl(0.0, fd.BAND_Z[1] + fd.BEZEL_W + 0.03, fd.BAND_R - fd.BEZEL_DEPTH + 0.05), lens=60.0), "post_foot_commander"),
        "u": (camera("cc_u", (0.25, st(6.05), 5.32), target=fd.cyl(0.0, fd.BAND_Z[1] + fd.BEZEL_W + 0.03, fd.BAND_R - fd.BEZEL_DEPTH + 0.05), lens=45.0), "post_foot_above"),
    }
    frame_end = fd.band_phi() + math.degrees(fd.BEZEL_W / fd.BAND_R)
    for seat, who in ((1, "pilot"), (-1, "commander")):
        for end, which in ((1, "l"), (-1, "r")):
            target = fd.cyl(end * frame_end, sum(fd.BAND_Z) / 2, fd.BAND_R - fd.BEZEL_DEPTH + 0.03)
            shots[f"z{who[0]}{which}"] = (camera(f"cc_z{who[0]}{which}", fd.eye(seat), target=target, lens=40.0),
                                          f"screen_end_{'plus' if end > 0 else 'minus'}_x_from_{who}")
    for i, ((ac, w), key) in enumerate(zip(fd.display_layout(), fd.DISPLAY_ORDER)):
        target = fd.cyl(ac, sum(fd.DISPLAY_Z) / 2, fd.DISPLAY_GLASS_R)
        shots[f"g{i}"] = (camera(f"cc_g{i}", eye, target=target, lens=36.0 * 9 / 16 * (target - eye).length / 0.32),
                          f"display_{i}_{key}_pilot_eye")
    paths = []
    for v in views:
        cam, label = shots[v]
        exterior = v in ("e", "x", "y", "v")
        for n in ("nose", "radar_F_fairing"):  # Aircraft.exteriorRenderers: hidden in cockpit view
            bpy.data.objects[n].hide_render = not exterior
        for o in ground:
            o.hide_render = exterior
        apron.hide_render = not exterior
        fill.hide_render = dome.hide_render = v in CLOSE_UPS
        # the close-ups' daylight is set so the panel's brightest tenth matches the stock Darkreach's in game
        bg.inputs["Strength"].default_value, sun.data.energy = (2.0, 5.0) if v in CLOSE_UPS else (1.0, 3.5)
        if hinge:
            hinge.rotation_euler = rest.copy()
            if v in ("x", "v"):
                hinge.rotation_euler.rotate_axis("X", open_angle)
        paths.append(shoot(cam, out / f"{v}_{label}.png", samples, engine="EEVEE" if v in CLOSE_UPS else "CYCLES"))
    if hinge:
        hinge.rotation_euler = rest
    return paths


def stock_parts(objs, fd):
    """The stock meshes authoring places on the deck's stock pivots (flightdeck.stock_pivots: the KR-67 sticks,
    throttles and warning-light strips), in the review scene only, each on its pivot as authoring will place it."""
    mats = stock_reference.stock_materials()
    for e in [o for o in bpy.data.objects if "stock_mesh" in o]:
        loc, rot, _ = e.matrix_world.decompose()
        stock_reference.place(e["stock_mesh"], loc, rotation_z=rot.to_euler().z, mirror=bool(e["mirror"]),
                              material=mats[e["stock_material"]])


def door_open_angle(hinge, deg=100.0):
    """The turn about the hinge's local X that swings the door outward (toward +X) by deg."""
    door = next(c for c in hinge.children if c.type == "MESH")
    rest = hinge.rotation_euler.copy()
    best = None
    for sign in (1, -1):
        hinge.rotation_euler = rest.copy()
        hinge.rotation_euler.rotate_axis("X", sign * math.radians(deg / 2))
        bpy.context.view_layer.update()
        c = door.matrix_world @ (sum((Vector(b) for b in door.bound_box), Vector()) / 8)
        if best is None or c.x > best[0]:
            best = (c.x, sign)
    hinge.rotation_euler = rest
    bpy.context.view_layer.update()
    return best[1] * math.radians(deg)
