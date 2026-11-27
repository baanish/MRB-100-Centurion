"""The finished sample: the pilot's main display module (the radar page in its bezel, the panel round it, the switch
strip under it, the hood and the module's side rails) modelled and textured to final quality on one 2048 x 1024 trim
sheet (flightdeck_texture_noise.py), in the blockout, rendered from the pilot's eye beside the same crop of today's panel and of
the stock Darkreach's main panel, all three under one light rig calibrated to the game.

blender -b --factory-startup <out>/blockout.blend --python flightdeck_plates.py -- --out <folder> --tex <tex folder>
    [--samples 96] [--sun 3.0] [--sky 0.6] [--exposure 0.0] [--flood 0]

The rig approximates the cockpit view in game: the nose and radar fairing hidden (Aircraft.exteriorRenderers), so
light reaches the deck only through the panes and the band and past the interior's own shell; a sun 50 deg up and
35 deg left of the nose, a sky dome; no fill. --flood adds today's flood (CenturionAuthor.FlightDeck.cs:157-169) as a
point light of that many watts at its place (station 6.2, z 5.05). The exposure is set once, so that the Darkreach's
sunlit light grey panel face measures about sRGB 120, as it does in game (darkreach_panel_close.png: 123; the
author's note in CenturionAuthor.FlightDeck.cs:157: 119). Writes sample_*.png, crop_*.png and sample_metrics.json."""

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flightdeck_layout as bo  # noqa: E402
import flightdeck_measure as cm  # noqa: E402
import flightdeck_stock as stock_scene  # noqa: E402

O = bpy.data.objects
FIELD_PXM = 1500.0  # px/m on panel faces (digest-cockpit rule 10: stock panel faces about 1,500)


# ---------------------------------------------------------------- UV regions
class Trim:
    def __init__(self, layout):
        self.W, self.H = layout["size"]
        self.strips = layout["strips"]
        self.labels = layout["labels"]
        self.hw = layout["hardware"]

    def uv(self, px, py):
        return (px / self.W, 1.0 - py / self.H)

    def strip(self, name, s_m, t, pxm=FIELD_PXM, offset=0.0):
        """Along a strip: s_m metres along (tiles in U), t 0..1 across (0 the strip's bottom row)."""
        x0, y0, x1, y1 = self.strips[name] if name in self.strips else self.hw[name]
        u = (s_m + offset) * pxm / self.W + x0 / self.W
        return (u, 1.0 - (y1 - t * (y1 - y0)) / self.H)

    def cell(self, rect, fu, fv):
        x0, y0, x1, y1 = rect
        return self.uv(x0 + fu * (x1 - x0), y1 - fv * (y1 - y0))


class Mesh:
    """Faces with UVs in a module's local frame (x across, y up the face, z toward the eye), turned to world at the end."""
    def __init__(self):
        self.faces = []  # (points, uvs, material index)

    def face(self, pts, uvs, mat=0):
        self.faces.append(([Vector(p) for p in pts], list(uvs), mat))

    def build(self, name, frame, mats, coll):
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.new("UVMap")
        for pts, uvs, mat in self.faces:
            vs = [bm.verts.new(frame @ p) for p in pts]
            try:
                f = bm.faces.new(vs)
            except ValueError:
                continue
            f.material_index = mat
            for loop, uv in zip(f.loops, uvs):
                loop[uvl].uv = uv
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for m in mats:
            me.materials.append(m)
        o = bpy.data.objects.new(name, me)
        coll.objects.link(o)
        return o


def inset(poly, d):
    """A convex CCW polygon moved inward by d."""
    n = len(poly)
    out = []
    for i in range(n):
        p0, p1, p2 = Vector(poly[i - 1]), Vector(poly[i]), Vector(poly[(i + 1) % n])
        e0, e1 = (p1 - p0).normalized(), (p2 - p1).normalized()
        n0, n1 = Vector((-e0.y, e0.x)), Vector((-e1.y, e1.x))
        bis = (n0 + n1).normalized()
        out.append(p1 + bis * d / max(0.2, bis.dot(n0)))
    return [tuple(p) for p in out]


def plate(m, t, poly, z0, z1, bevel, top, top_pxm=FIELD_PXM, offset=0.0, side="side"):
    """A bevelled prism: top face on strip `top` (U along x, V fitted across the plate's height, so the strip's
    border wear lands on the plate's edges), a worn chamfer on the edge strip, sides on `side`."""
    poly = [tuple(p) for p in poly]
    ins = inset(poly, bevel) if bevel > 0 else poly
    ys = [p[1] for p in poly]
    lo, hi = min(ys), max(ys)
    m.face([(x, y, z1) for x, y in ins], [t.strip(top, x, (y - lo) / (hi - lo), top_pxm, offset) for x, y in ins])
    n = len(poly)
    per = 0.0
    for i in range(n):
        a, b = Vector(poly[i]), Vector(poly[(i + 1) % n])
        ia, ib = Vector(ins[i]), Vector(ins[(i + 1) % n])
        L = (b - a).length
        if bevel > 0:
            m.face([(a.x, a.y, z1 - bevel), (b.x, b.y, z1 - bevel), (ib.x, ib.y, z1), (ia.x, ia.y, z1)],
                   [t.strip("edge", per, 0.0, 2048), t.strip("edge", per + L, 0.0, 2048), t.strip("edge", per + L, 1.0, 2048),
                    t.strip("edge", per, 1.0, 2048)])
        m.face([(a.x, a.y, z0), (b.x, b.y, z0), (b.x, b.y, z1 - bevel), (a.x, a.y, z1 - bevel)],
               [t.strip(side, per, 0.0), t.strip(side, per + L, 0.0), t.strip(side, per + L, 1.0), t.strip(side, per, 1.0)])
        per += L


def cap(m, t, centre, r, z0, z1, sides, top_rect, side_strip="knob_side"):
    cx, cy = centre
    ring = [(cx + r * math.cos(2 * math.pi * k / sides), cy + r * math.sin(2 * math.pi * k / sides)) for k in range(sides)]
    m.face([(x, y, z1) for x, y in ring], [t.cell(top_rect, 0.5 + (x - cx) / (2 * r), 0.5 + (y - cy) / (2 * r)) for x, y in ring])
    for k in range(sides):
        a, b = ring[k], ring[(k + 1) % sides]
        m.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)],
               [t.strip(side_strip, k * 0.004, 0.0, 6000), t.strip(side_strip, (k + 1) * 0.004, 0.0, 6000),
                t.strip(side_strip, (k + 1) * 0.004, 1.0, 6000), t.strip(side_strip, k * 0.004, 1.0, 6000)])


def keycap(m, t, centre, w, h, z0, z1, rect, bevel=0.001):
    cx, cy = centre
    poly = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    ins = inset(poly, bevel)
    m.face([(x, y, z1) for x, y in ins], [t.cell(rect, (x - poly[0][0]) / w, (y - poly[0][1]) / h) for x, y in ins])
    for i in range(4):
        a, b, ia, ib = poly[i], poly[(i + 1) % 4], ins[i], ins[(i + 1) % 4]
        m.face([(a[0], a[1], z1 - bevel), (b[0], b[1], z1 - bevel), (ib[0], ib[1], z1), (ia[0], ia[1], z1)],
               [t.strip("bezel", 0, 0.9), t.strip("bezel", 0.01, 0.9), t.strip("bezel", 0.01, 1.0), t.strip("bezel", 0, 1.0)])
        m.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1 - bevel), (a[0], a[1], z1 - bevel)],
               [t.strip("side", 0, 0), t.strip("side", 0.01, 0), t.strip("side", 0.01, 1), t.strip("side", 0, 1)])


def placard(m, t, centre, w, h, z, word):
    cx, cy = centre
    rect = t.labels[word]
    m.face([(cx - w / 2, cy - h / 2, z), (cx + w / 2, cy - h / 2, z), (cx + w / 2, cy + h / 2, z), (cx - w / 2, cy + h / 2, z)],
           [t.cell(rect, 0, 0), t.cell(rect, 1, 0), t.cell(rect, 1, 1), t.cell(rect, 0, 1)])


def fastener(m, t, centre, z):
    cap(m, t, centre, 0.0042, z, z + 0.0022, 6, t.hw["fastener"], "side")


def toggle(m, t, centre, z, angle=15):
    cap(m, t, centre, 0.0065, z, z + 0.004, 12, t.hw["knob"], "knob_side")  # collar
    cx, cy = centre
    a = math.radians(angle)
    tip = Vector((cx, cy + 0.018 * math.sin(a), z + 0.004 + 0.018 * math.cos(a)))
    base = Vector((cx, cy, z + 0.004))
    d = (tip - base).normalized()
    u = d.cross(Vector((1, 0, 0))).normalized()
    v = d.cross(u)
    r0, r1, n = 0.0022, 0.0016, 6
    ring0 = [base + (u * math.cos(2 * math.pi * k / n) + v * math.sin(2 * math.pi * k / n)) * r0 for k in range(n)]
    ring1 = [tip + (u * math.cos(2 * math.pi * k / n) + v * math.sin(2 * math.pi * k / n)) * r1 for k in range(n)]
    for k in range(n):
        m.face([ring0[k], ring0[(k + 1) % n], ring1[(k + 1) % n], ring1[k]],
               [t.cell(t.hw["toggle"], k / n, 0), t.cell(t.hw["toggle"], (k + 1) / n, 0), t.cell(t.hw["toggle"], (k + 1) / n, 1),
                t.cell(t.hw["toggle"], k / n, 1)])
    m.face(ring1, [t.cell(t.hw["toggle"], 0.5, 0.5)] * n)


# ---------------------------------------------------------------- the module
def module_frame():
    """The pilot's radar module from the blockout's layout: its face quad and a local frame on it."""
    layout = json.load(open(OUT_BLOCK / "blockout_layout.json"))
    edges = layout["edges_pilot"]
    k = [m[0] for m in bo.PILOT].index("radar")
    a0, a1 = edges[k], edges[k + 1]
    exy = Vector((bo.EYE[1].x, bo.EYE[1].y, 0))
    zt0, zt1 = min(bo.Z_TOP, bo.z_cap(a0, bo.R_TOP)), min(bo.Z_TOP, bo.z_cap(a1, bo.R_TOP))
    bl = exy + bo.plan(1, a0) * bo.R_BOT + Vector((0, 0, bo.Z_BOT))
    br = exy + bo.plan(1, a1) * bo.R_BOT + Vector((0, 0, bo.Z_BOT))
    tr = exy + bo.plan(1, a1) * bo.R_TOP + Vector((0, 0, zt1))
    tl = exy + bo.plan(1, a0) * bo.R_TOP + Vector((0, 0, zt0))
    ex = (br - bl).normalized()
    mid_b, mid_t = (bl + br) / 2, (tl + tr) / 2
    ey = (mid_t - mid_b)
    ey = (ey - ex * ey.dot(ex)).normalized()
    ez = ex.cross(ey)
    if ez.dot(bo.EYE[1] - mid_b) < 0:
        ez, ex = -ez, -ex
    frame = Matrix((ex, ey, ez)).transposed().to_4x4()
    frame.translation = mid_b
    inv = frame.inverted()
    disp = next(d for d in layout["displays"] if d[0] == "radar_pilot")
    q = [inv @ Vector(p) for p in disp[2]]
    return frame, [inv @ p for p in (bl, br, tr, tl)], q, (a0, a1)


def build_sample(t, coll, mats):
    frame, face, disp, (a0, a1) = module_frame()
    m = Mesh()
    xs = [p.x for p in disp]
    ysd = [p.y for p in disp]
    dx0, dx1, dy0, dy1 = min(xs), max(xs), min(ysd), max(ysd)
    hf = max(p.y for p in face)
    left_b, right_b = face[0].x, face[1].x
    left_t, right_t = face[3].x, face[2].x

    def half(y):  # the module's edges at height y
        f = y / hf
        return left_b + (left_t - left_b) * f, right_b + (right_t - right_b) * f
    # the base face behind everything (the blockout slab's front), the upper panel plate and the switch strip
    ys = dy0 - 0.030
    l0, r0 = half(0.004)
    l1, r1 = half(ys - 0.004)
    l2, r2 = half(ys + 0.003)
    l3, r3 = half(hf - 0.003)
    rail = 0.022
    plate(m, t, [(l2 + rail, ys + 0.003), (r2 - rail, ys + 0.003), (r3 - rail, hf - 0.003), (l3 + rail, hf - 0.003)],
          0.0, 0.007, 0.002, "field", offset=0.37)
    plate(m, t, [(l0 + rail, 0.004), (r0 - rail, 0.004), (r1 - rail, ys - 0.004), (l1 + rail, ys - 0.004)],
          0.0, 0.006, 0.0015, "field", offset=0.11)
    # side rails: the frame between modules, a touch prouder, fastened
    for side in (0, 1):
        lb, lt = (left_b, left_t) if side == 0 else (right_b - rail, right_t - rail)
        poly = [(lb, 0.0), (lb + rail, 0.0), (lt + rail, hf), (lt, hf)]
        plate(m, t, poly, 0.0, 0.014, 0.0025, "field", 2200, offset=0.6 + side)
        for y in (0.03, ys + 0.02, (ys + hf) / 2, hf - 0.025):
            xl, xr = half(y)
            fastener(m, t, ((xl + rail / 2) if side == 0 else (xr - rail / 2), y), 0.014)
    # the display bezel: a frame swept round the opening, chamfered inside and out, the glass 8 mm down
    bx, bt, bb = 0.024, 0.020, 0.030
    ox0, ox1, oy0, oy1 = dx0 - bx, dx1 + bx, dy0 - bb, dy1 + bt
    zb, zf = 0.007, 0.022

    def ring(f):  # the frame's outline at fraction f across its bars (0 outer, 1 inner)
        return [(ox0 + f * bx, oy0 + f * bb), (ox1 - f * bx, oy0 + f * bb), (ox1 - f * bx, oy1 - f * bt), (ox0 + f * bx, oy1 - f * bt)]
    prof = [(0.0, zb, "side"), (0.0, zf - 0.0025, "edge"), (0.1, zf, "bezel"), (0.88, zf, "edge"), (1.0, zf - 0.003, "side"),
            (1.0, 0.012, None)]
    bars = [(0, "bottom"), (1, "right"), (2, "top"), (3, "left")]
    for (fa, za, kind), (fb, zb2, _) in zip(prof, prof[1:]):
        ra, rb = ring(fa), ring(fb)
        for i, _name in bars:
            j = (i + 1) % 4
            pa0, pa1, pb0, pb1 = ra[i], ra[j], rb[i], rb[j]
            L = (Vector(pa1) - Vector(pa0)).length
            if kind == "bezel":
                uvs = [t.strip("bezel", 0, 0.05), t.strip("bezel", L, 0.05, 2600), t.strip("bezel", L, 0.95, 2600), t.strip("bezel", 0, 0.95)]
                uvs[1] = t.strip("bezel", L, 0.05, 2600)
            else:
                st_ = kind
                uvs = [t.strip(st_, 0, 0), t.strip(st_, L, 0, 2600), t.strip(st_, L, 1, 2600), t.strip(st_, 0, 1)]
            m.face([(pa0[0], pa0[1], za), (pa1[0], pa1[1], za), (pb1[0], pb1[1], zb2), (pb0[0], pb0[1], zb2)], uvs)
    # bezel keys, four a side, rockers and the brightness knob on the bottom bar, the legends on placards
    for k in range(4):
        y = dy0 + (dy1 - dy0) * (0.20 + 0.2 * k)
        keycap(m, t, (dx0 - bx / 2, y), 0.013, 0.011, zf, zf + 0.006, t.hw["osb"])
        keycap(m, t, (dx1 + bx / 2, y), 0.013, 0.011, zf, zf + 0.006, t.hw["osb"])
    for x, word in ((dx0 + 0.03, "GAIN"), (dx1 - 0.03, "CONT")):
        keycap(m, t, (x, oy0 + bb * 0.42), 0.026, 0.010, zf, zf + 0.004, t.hw["osb"])
        placard(m, t, (x + (0.03 if word == "GAIN" else -0.03), oy0 + bb * 0.42), 0.022, 0.0065, zf + 0.0003, word)
    cap(m, t, ((dx0 + dx1) / 2, oy0 + bb * 0.45), 0.008, zf, zf + 0.009, 16, t.hw["knob"])
    placard(m, t, ((dx0 + dx1) / 2 + 0.022, oy0 + bb * 0.45), 0.016, 0.0065, zf + 0.0003, "BRT")
    placard(m, t, (dx0 + 0.035, oy1 - bt * 0.5), 0.03, 0.0075, zf + 0.0003, "RADAR")
    # the switch strip: master arm under its red guard, bay doors, jettison in hazard, range and mode, test
    zs = 0.006
    cy = ys * 0.42
    py = ys * 0.80
    xs_ = [l1 + rail + 0.03 + (r1 - l1 - 2 * rail - 0.06) * f for f in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]
    toggle(m, t, (xs_[0], cy), zs, 10)
    gx = xs_[0]
    plate(m, t, [(gx - 0.011, cy - 0.016), (gx + 0.011, cy - 0.016), (gx + 0.011, cy + 0.012), (gx - 0.011, cy + 0.012)],
          zs, zs + 0.004, 0.001, "guard_red", 4000)
    for (x0_, x1_) in ((gx - 0.011, gx - 0.009), (gx + 0.009, gx + 0.011)):
        plate(m, t, [(x0_, cy - 0.016), (x1_, cy - 0.016), (x1_, cy + 0.012), (x0_, cy + 0.012)], zs + 0.004, zs + 0.026, 0.0,
              "guard_red", 4000, side="guard_red")
    plate(m, t, [(gx - 0.011, cy + 0.010), (gx + 0.011, cy + 0.010), (gx + 0.011, cy + 0.012), (gx - 0.011, cy + 0.012)],
          zs + 0.004, zs + 0.026, 0.0, "guard_red", 4000, side="guard_red")
    placard(m, t, (xs_[0], py), 0.040, 0.0085, zs + 0.0003, "MASTER ARM")
    toggle(m, t, (xs_[1], cy), zs, -18)
    placard(m, t, (xs_[1], py), 0.040, 0.0085, zs + 0.0003, "BAY DOORS")
    placard(m, t, (xs_[1] + 0.018, cy + 0.008), 0.018, 0.006, zs + 0.0003, "OPEN")
    placard(m, t, (xs_[1] + 0.018, cy - 0.010), 0.018, 0.006, zs + 0.0003, "CLOSE")
    hz = xs_[2]
    for (a, b) in (((hz - 0.016, cy - 0.016), (hz + 0.016, cy - 0.012)), ((hz - 0.016, cy + 0.012), (hz + 0.016, cy + 0.016)),
                   ((hz - 0.016, cy - 0.012), (hz - 0.012, cy + 0.012)), ((hz + 0.012, cy - 0.012), (hz + 0.016, cy + 0.012))):
        m.face([(a[0], a[1], zs + 0.0004), (b[0], a[1], zs + 0.0004), (b[0], b[1], zs + 0.0004), (a[0], b[1], zs + 0.0004)],
               [t.strip("hazard", a[0] * 3, 0, 4000), t.strip("hazard", b[0] * 3, 0, 4000), t.strip("hazard", b[0] * 3, 1, 4000),
                t.strip("hazard", a[0] * 3, 1, 4000)])
    keycap(m, t, (hz, cy), 0.020, 0.020, zs, zs + 0.007, t.hw["button_amber"], 0.0015)
    placard(m, t, (hz, py), 0.026, 0.0085, zs + 0.0003, "JETT")
    for x, word in ((xs_[3], "RANGE"), (xs_[4], "MODE")):
        cap(m, t, (x, cy), 0.009, zs, zs + 0.012, 16, t.hw["knob"])
        placard(m, t, (x, py), 0.030, 0.0085, zs + 0.0003, word)
    keycap(m, t, (xs_[5], cy), 0.018, 0.018, zs, zs + 0.006, t.hw["button_green"], 0.0015)
    placard(m, t, (xs_[5], py), 0.024, 0.0085, zs + 0.0003, "TEST")
    for x in (l1 + rail + 0.008, r1 - rail - 0.008):
        for y in (0.012, ys - 0.012):
            fastener(m, t, (x, y), zs)
    for x in (l3 + rail + 0.01, r3 - rail - 0.01):
        for y in (ys + 0.015, hf - 0.015):
            fastener(m, t, (x, y), 0.007)
    # the hood's front lip: a rolled edge along the module's top, the glare shield above it dark
    lt_, rt_ = half(hf)
    n = 6
    for k in range(n):
        a_, b_ = math.pi / 2 * k / n, math.pi / 2 * (k + 1) / n
        r = 0.010
        pa = (hf - r + r * math.sin(a_), r * math.cos(a_))  # (y, z): from the face's top, rolling over toward the eye
        pb = (hf - r + r * math.sin(b_), r * math.cos(b_))
        m.face([(lt_, pa[0], pa[1] + 0.004), (rt_, pa[0], pa[1] + 0.004), (rt_, pb[0], pb[1] + 0.004), (lt_, pb[0], pb[1] + 0.004)],
               [t.strip("dark", lt_, 0.96 - 0.02 * k, 2000), t.strip("dark", rt_, 0.96 - 0.02 * k, 2000),
                t.strip("dark", rt_, 0.94 - 0.02 * k, 2000), t.strip("dark", lt_, 0.94 - 0.02 * k, 2000)])
    obj = m.build("sample_module", frame, [mats["trim"]], coll)
    # the glass: the radar page from the canvas, 8 mm under the bezel's face
    g = Mesh()
    x0, y0, x1, y1 = 2.8 + 1.5, 146.1 + 1.5, 585.7 - 1.5, 488.5 - 1.5
    g.face([(dx0, dy0, 0.014), (dx1, dy0, 0.014), (dx1, dy1, 0.014), (dx0, dy1, 0.014)],
           [(x0 / 1024, y0 / 512), (x1 / 1024, y0 / 512), (x1 / 1024, y1 / 512), (x0 / 1024, y1 / 512)])
    glass = g.build("sample_glass", frame, [mats["screen"]], coll)
    return obj, glass, frame, (a0, a1)


def trim_material(tex):
    m = bpy.data.materials.new("sample_trim")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    def img(name, colour=True):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(str(tex / name))
        n.interpolation = "Cubic"
        if not colour:
            n.image.colorspace_settings.name = "Non-Color"
        return n
    b, ao, ms, nm = img("trim_b.png"), img("trim_ao.png", False), img("trim_m.png", False), img("trim_n.png", False)
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(b.outputs["Color"], mix.inputs[6])
    nt.links.new(ao.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(ms.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(ms.outputs["Alpha"], inv.inputs[1])
    nt.links.new(inv.outputs[0], bsdf.inputs["Roughness"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nm.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def screen_material(tex, strength):
    m = bpy.data.materials.new("sample_screen")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = bpy.data.images.load(str(tex / "canvas.png"))
    bsdf.inputs["Base Color"].default_value = (0.005, 0.005, 0.005, 1)
    bsdf.inputs["Roughness"].default_value = 0.08
    nt.links.new(n.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = strength
    return m


def rig(args):
    scene = bpy.context.scene
    bo.setup_world(args.samples)
    scene.render.resolution_x, scene.render.resolution_y = 2200, 1375
    scene.view_settings.view_transform = "Standard"  # the game's own grading is not modelled; a plain sRGB transfer
    scene.view_settings.exposure = args.exposure
    for o in O:
        if o.type == "LIGHT":
            o.hide_render = True
    sun = bpy.data.objects.new("sample_sun", bpy.data.lights.new("sample_sun", "SUN"))
    sun.data.energy, sun.data.angle = args.sun, math.radians(1.0)
    # 50 deg up, from 35 deg left of the nose: the light travels aft, right and down
    d = cm.direction(-35, 50)
    sun.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(sun)
    scene.world.node_tree.nodes.get("Background").inputs["Strength"].default_value = args.sky
    if args.flood:
        fl = bpy.data.objects.new("sample_flood", bpy.data.lights.new("sample_flood", "POINT"))
        fl.data.energy, fl.data.color = args.flood, (1.0, 0.95, 0.88)
        fl.data.use_shadow = False
        fl.location = bo.P(6.2, 0.0, 5.05)
        scene.collection.objects.link(fl)


def sample_srgb(path_img, cam, point, half=10):
    """Median sRGB luminance of the rendered pixels round a world point."""
    scene = bpy.context.scene
    co = world_to_camera_view(scene, cam, point)
    img = bpy.data.images.load(str(path_img))
    w, h = img.size
    px = list(img.pixels)
    cx, cy = int(co.x * w), int(co.y * h)
    vals = []
    for y in range(max(0, cy - half), min(h, cy + half)):
        for x in range(max(0, cx - half), min(w, cx + half)):
            i = (y * w + x) * 4
            vals.append(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2])
    vals.sort()
    bpy.data.images.remove(img)
    return round(255 * vals[len(vals) // 2], 1) if vals else None


def ray_point(eye, az, el, objs):
    t = cm.tree(objs)
    h = t.ray_cast(eye + cm.direction(az, el) * 0.03, cm.direction(az, el), 4.0)
    return h[0]


def main():
    global OUT_BLOCK
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tex", required=True)
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--sun", type=float, default=3.0)
    ap.add_argument("--sky", type=float, default=0.6)
    ap.add_argument("--exposure", type=float, default=0.0)
    ap.add_argument("--flood", type=float, default=0.0)
    ap.add_argument("--only", default="new,today,darkreach")
    ap.add_argument("--calib", action="store_true", help="also render the wide calibration views")
    ap.add_argument("--suffix", default="")
    args = ap.parse_args(argv)
    out, tex = Path(args.out), Path(args.tex)
    out.mkdir(parents=True, exist_ok=True)
    OUT_BLOCK = Path(bpy.data.filepath).parent
    scene = bpy.context.scene
    t = Trim(json.load(open(tex / "trim_layout.json")))
    mats = {"trim": trim_material(tex), "screen": screen_material(tex, 1.6)}
    coll = bpy.data.collections.new("Sample")
    scene.collection.children.link(coll)
    obj, glass, frame, (a0, a1) = build_sample(t, coll, mats)
    # take the blockout's radar module out from under the sample (faces whose centre lies inside the module's az span
    # from the pilot's eye, above the knee)
    eye = bo.EYE[1]
    for o in list(bpy.data.collections["Blockout"].objects):
        if o.type != "MESH" or not o.name.startswith("bo_") or o.name in ("bo_shell",):
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        dead = []
        for f in bm.faces:
            c = o.matrix_world @ f.calc_center_median()
            az = cm.angles_of(c - eye)[0]
            if a0 + 0.2 < az < a1 - 0.2 and 4.39 < c.z < 4.80 and (c - eye).length < 1.2:
                dead.append(f)
        bmesh.ops.delete(bm, geom=dead, context="FACES")
        bm.to_mesh(o.data)
        bm.free()
    for o in O:  # labels off in the finished renders
        if o.name.startswith("lbl_") or o.name.startswith("cone_"):
            o.hide_render = True
    # today's tac screen lit with the same stand-in canvas as the sample's glass
    O["tacScreen"].data.materials.clear()
    O["tacScreen"].data.materials.append(mats["screen"])
    # the blockout's other pages on the same canvas, each quad (BL, BR, TR, TL) mapped to its page's rect
    rects = {"radar": ((2.8, 146.1, 585.7, 488.5), False), "pfd": ((289.8, 2.6, 521.4, 143.8), True),
             "gauges": ((16.1, 2.3, 264.5, 143.4), True), "engines": ((595.7, 257.0, 810.6, 509.4), False),
             "stores": ((811.8, 191.8, 1012.2, 504.9), False), "wing": ((595.7, 1.6, 803.4, 253.9), False)}
    for o in O:
        if not o.name.startswith("bo_display_"):
            continue
        (x0, y0, x1, y1), turned = rects[o.name.split("_")[2]]
        corners = [(0, 0), (1, 0), (1, 1), (0, 1)]
        uvl = o.data.uv_layers.new(name="UVMap").data
        for poly in o.data.polygons:
            for k, li in enumerate(poly.loop_indices):
                fu, fv = corners[k % 4]
                if turned:
                    uvl[li].uv = ((x1 - (x1 - x0) * fv) / 1024, (y0 + (y1 - y0) * fu) / 512)
                else:
                    uvl[li].uv = ((x0 + (x1 - x0) * fu) / 1024, (y0 + (y1 - y0) * fv) / 512)
        o.data.materials.clear()
        o.data.materials.append(mats["screen"])
    rig(args)
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons) + 2
    view = (frame @ Vector((0, 0.13, 0))) - eye
    az, el = cm.angles_of(view)
    results = {"sample_tris": tris, "sample_faces": len(obj.data.polygons)}
    cam = bo.view_cam("sample_cam", eye, az, el, 30)
    today = bpy.data.collections["Flightdeck"]
    block = bpy.data.collections["Blockout"]

    def show(which):
        for o in block.objects:
            o.hide_render = which != "new" and o.name not in ("stock_seat_EjectionSeat", "stock_seat_EjectionSeat.001")
        for o in coll.objects:
            o.hide_render = which != "new"
        keep = ("band", "band_bezel", "band_marker", "glass_int", "hatch_liner_L", "hatch_liner_R", "warning_lenses")
        for o in today.objects:
            o.hide_render = which not in ("today", "today_flood") and o.name not in keep
        if "today_wing" in O:
            O["today_wing"].hide_render = True
    if "new" in args.only:
        show("new")
        cam.data.lens = 30
        render(out / ("sample_new.png".replace(".png", args.suffix + ".png")), cam)
        p = ray_point(eye, 2, -36, [obj])
        results["new_panel_srgb"] = sample_srgb(out / ("sample_new.png".replace(".png", args.suffix + ".png")), cam, p, 6) if p else None
        p_strip = frame @ Vector((-0.10, 0.06, 0.0))
        caz, cel = cm.angles_of(p_strip - eye)
        render(out / ("sample_new_close.png".replace(".png", args.suffix + ".png")), bo.view_cam("sample_cam_close", eye, caz, cel, 75))
        cam_wide = bo.view_cam("sample_cam_wide", eye, az, el - 2, 20)
        render(out / ("sample_new_wide.png".replace(".png", args.suffix + ".png")), cam_wide)
    if "today" in args.only:
        show("today")
        render(out / ("sample_today.png".replace(".png", args.suffix + ".png")), cam)
        if args.calib:
            render(out / ("calib_today_flood%d.png" % args.flood), bo.view_cam("calib_cam", eye, 0, -20, 18))
        p = ray_point(eye, 2, -36, [O["flightdeck_int"]])
        results["today_panel_srgb"] = sample_srgb(out / ("sample_today.png".replace(".png", args.suffix + ".png")), cam, p, 6) if p else None
    if "darkreach" in args.only:
        for o in list(block.objects) + list(coll.objects) + list(today.objects):
            o.hide_render = True
        for o in O:
            if o.users_collection and o.users_collection[0].name in ("Centurion", "Flightdeck"):
                o.hide_render = True
        # the Darkreach's cockpit view, by reference: its cockpit list and everything not on its exterior list,
        # moved so its eye sits 40 m to the side of the Centurion's at the same height (same sun, sky and ground)
        off = Vector((40.0, 0.0, 0.0))
        parts, dr_eye = stock_scene.import_stock(HERE.parents[2] / ".cache" / "art" / "cockpit" / "stock" / "darkreach", lambda p: p["list"] != "exterior" and p["active"],
                                                 offset=Vector(), tag="_dr")
        shift = (eye + off) - dr_eye
        for o in parts:
            o.data.transform(Matrix.Translation(shift))
        dr_eye_w = dr_eye + shift
        # aim at the Darkreach's radar page as the Centurion's camera aims at its own
        ts = next(o for o in parts if o.name.startswith("stock_dr_tacScreen"))
        uvl = ts.data.uv_layers.active.data
        pts = [ts.matrix_world @ ts.data.vertices[ts.data.loops[li].vertex_index].co for poly in ts.data.polygons
               for li in poly.loop_indices if uvl[li].uv.y * 512 > 143 and uvl[li].uv.x * 1024 < 589]
        radar_c = sum(pts, Vector()) / len(pts)
        ts.data.materials.clear()
        ts.data.materials.append(mats["screen"])
        daz, del_ = cm.angles_of(radar_c - dr_eye_w)
        cam_dr = bo.view_cam("sample_cam_dr", dr_eye_w, az, el, 30)  # the same crop as the Centurion's
        render(out / ("sample_darkreach.png".replace(".png", args.suffix + ".png")), cam_dr)
        if args.calib:
            render(out / "calib_darkreach.png", bo.view_cam("calib_cam_dr", dr_eye_w, 0, -20, 18))
        p = ray_point(dr_eye_w, daz - 20, del_ - 2, [o for o in parts if "cockpit_int" in o.name])
        results["darkreach_panel_srgb"] = sample_srgb(out / ("sample_darkreach.png".replace(".png", args.suffix + ".png")), cam_dr, p, 6) if p else None
        results["darkreach_radar"] = {"az": round(daz, 1), "el": round(del_, 1), "dist": round((radar_c - dr_eye_w).length, 3)}
    results["rig"] = vars(args)
    prev = out / "sample_metrics.json"
    old = json.load(open(prev)) if prev.exists() else {}
    old.update(results)
    json.dump(old, open(prev, "w"), indent=1)
    print("SAMPLE", json.dumps(results))


def clay_page(name):
    return bpy.data.materials.get("sample_screen")


def render(path, cam):
    bo.render(path, cam)


OUT_BLOCK = None
if __name__ == "__main__":
    main()
