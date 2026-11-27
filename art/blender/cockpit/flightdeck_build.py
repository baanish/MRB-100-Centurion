"""The second sample: the whole main panel across both seats, the centre stack and pedestal, and both side consoles
with their wall breaker panels, finished in near-black on one trim sheet (flightdeck_textures.py) with the stock
Switches1 hardware (kit_parts.py) instanced on them, every control on a labelled panel of a real system
(flightdeck_panels.py), in the blockout's approved layout (flightdeck_layout.py), rendered under the calibrated rig (flightdeck_plates.py).

blender -b --factory-startup <blockout>/blockout.blend --python flightdeck_build.py -- --out <folder> [--samples 96]
    [--flood 11.2] [--exposure 0.16] [--views panel,left,right,shoulder,close_left,close_centre] [--suffix ""]

Writes the renders, s2_metrics.json (triangles, unique meshes, the exact control, placard, fastener and panel
counts per view) and sample2.blend."""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flightdeck_layout as bo  # noqa: E402
import flightdeck_measure as cm  # noqa: E402
import flightdeck_panels as P2  # noqa: E402
import flightdeck_plates as sp  # noqa: E402

O = bpy.data.objects
# The stock Switches1 pieces by role, each checked against kit.json's triangle count when loaded.
ROLE = {"bushing": ("kit_10", 130), "lever": ("kit_06", 70), "ptr": ("kit_07", 220), "stk": ("kit_21", 224),
        "big": ("kit_23", 214), "knl": ("kit_44", 78), "skt": ("kit_35", 118), "key": ("kit_12", 18),
        "cap": ("kit_45", 18), "lamp": ("kit_24", 70), "pull": ("kit_28", 180), "guard": ("kit_38", 52),
        "handle": ("kit_14", 298), "grip": ("kit_22", 108), "flipguard": ("kit_25", 206)}
FLIPGUARD_HOLE = (0.0037, 0.0003)  # where the stock flip guard's hole sits in its own frame
KNOB_TOP = {"knl": 0.006, "big": 0.011, "stk": 0.022, "skt": 0.014, "ptr": 0.011}  # heights of the stock knobs' tops
CONTROLS = []  # (kind, world point)
PLACARDS, FASTENERS, PANELS = [], [], []


GROUPS = []  # (name, world centre, size m, seat): one close crop each
SCREENS = {}  # display name -> (page, world quad on its module's plane)
CAUTION = []  # the centre stack's caution strip, waiting on the other modules
MODULE_QUADS = []  # every display module's face, to find the edges two modules share
HOOD_HALF = [0.0]  # how far out from the centreline the glare hoods reach (m), for the plate behind the displays
FLUSH_GAP = 0.0005  # metres a part mounted against another stands off it: laid exactly flush, the pair counted as passing
# through each other or not as unrelated parts moved the deck's rounding (flightdeck_interpenetration.py)
GROUP_AXES = {}  # crop group -> (the panel's outward normal, the way its labels read up)


# ---------------------------------------------------------------- geometry accumulation
class Acc:
    def __init__(self):
        self.faces = []

    def build(self, name, mats, coll):
        m = sp.Mesh()
        m.faces = self.faces
        return m.build(name, Matrix(), mats, coll)


class FM:
    """Faces given in a local frame, stored in world space."""
    def __init__(self, acc, frame):
        self.acc, self.frame = acc, frame

    def face(self, pts, uvs, mat=0):
        self.acc.faces.append(([self.frame @ Vector(p) for p in pts], list(uvs), mat))


NAMED = []  # (panel title, kind, label, world point, frame): every labelled control, for the proof cameras
MARKS = []  # (kind, world start, world end, frame): every knob index line
CARDS = []  # every carded face: id, frame, inverse, x0, y0, w, h (in the frame), z of its top, paint, items
FALLBACK = set()  # words placed where no card is: they still need a label cell
KEY_WORDS = {"BRT", "CON"}  # every legend a key carries, so the texture pass makes only those faces


def card_new(frame, x0, y0, w, h, z, paint):
    c = {"id": "c%04d" % len(CARDS), "frame": frame, "inv": frame.inverted(), "x0": x0, "y0": y0, "w": w, "h": h, "z": z,
         "paint": paint, "items": []}
    CARDS.append(c)
    return c


# the stock throttle lever as the game draws and moves it: its mesh (the placeholder in the repo holds the stock
# vertices), on authoring's pivots (station 6.05, x +-0.01, z 4.142; throttle_1 mirrored, a negative x scale), turned
# about its own x by throttle * THROTTLE_RANGE (Cockpit.cs:41) from authoring's mount THROTTLE_REST deg aft
THROTTLE_MESH = HERE.parents[2] / "unity" / "Assets" / "Blueprinter" / "_donotship" / "Mesh" / "Multirole1_throttle_PLACEHOLDER.asset"
THROTTLE_PIVOTS = ((0.01, 6.05, 4.142, -1.0), (-0.01, 6.05, 4.142, 1.0))  # Blender x, station, z, Unity x scale
THROTTLE_REST, THROTTLE_RANGE, THROTTLE_GRIP_Y = -10.0, 40.0, 0.31  # mount deg, travel deg; the grip above this local y
# 10 deg aft: the grip then clears the quadrant by 12 mm or more over its whole travel (at 20 aft its wide base sank
# 2 cm into the top at idle, at none it sank as far at full); CenturionAuthor.FlightDeck.cs ThrottleRestDeg


def throttle_sweep(rest=THROTTLE_REST, steps=21):
    """Each lever's vertices over its travel, as (Blender x, station, z, local y) per step."""
    import re
    import struct
    text = THROTTLE_MESH.read_text()
    n = int(re.search(r"m_VertexCount: (\d+)", text).group(1))
    raw = bytes.fromhex(re.search(r"_typelessdata: ([0-9a-f]+)", text).group(1))
    vs = [struct.unpack_from("<3f", raw, i * (len(raw) // n)) for i in range(n)]
    out = []
    for x0, st0, z0, sx in THROTTLE_PIVOTS:
        pts = []
        for k in range(steps):
            a = math.radians(rest + THROTTLE_RANGE * k / (steps - 1))
            ca, sa = math.cos(a), math.sin(a)
            for x, y, z in vs:  # Unity's x turn: +y toward +z (forward); Unity x is Blender -x, Unity z is -station
                pts.append((x0 - sx * x, st0 - (y * sa + z * ca), z0 + (y * ca - z * sa), y))
        out.append(pts)
    return out


def stalk_footprint(pts, top_z):
    """Where a lever passes through the quadrant's top over its travel: (x min, x max, station min, station max)."""
    below = [p for p in pts if p[2] < top_z + 0.002]
    return (min(p[0] for p in below), max(p[0] for p in below), min(p[1] for p in below), max(p[1] for p in below))


def lever_sweep_faults(top_z, cuts, rest=THROTTLE_REST):
    """Vertices of the throttles over their travel that meet the quadrant: under its top outside their own cut (x
    centre, half width, station fore and aft ends), a grip under its top, or the two grips overlapping."""
    faults = 0
    sweeps = throttle_sweep(rest)
    for pts, (xc, hw, sf, sa_) in zip(sweeps, cuts):
        for x, st, z, y in pts:
            if z < top_z + 0.002 and (y > THROTTLE_GRIP_Y or not (abs(x - xc) <= hw - 0.002 and sf + 0.002 <= st <= sa_ - 0.002)):
                faults += 1
    grips = [[p for p in pts if p[3] > THROTTLE_GRIP_Y] for pts in sweeps]
    if min(p[0] for p in grips[0]) < max(p[0] for p in grips[1]) + 0.004:
        faults += 1
    return faults


# the levers the plugin moves (src/Centurion/CockpitLevers.cs): each its own part in the export, its mesh about the
# rest end of its travel, its travel in its props (slide_axis, travel_m), and the slot it slides in for lever_slot_faults
LEVERS = {}  # name -> (Acc, rest base, far base, (slot frame, x0, x1, y0, y1, surface z))


def lever_begin(ctx):
    """Starts a lever's own mesh: what is built until lever_end goes into it, not the deck."""
    held = ctx["acc"]
    ctx["acc"] = Acc()
    return held


def lever_end(ctx, held, name, rest, far, slot):
    """Ends a lever's mesh begun by lever_begin: rest and far are its base at each end of its travel (world)."""
    LEVERS[name] = (ctx["acc"], rest.copy(), far.copy(), slot)
    ctx["acc"] = held


def lever_slot_faults(steps=21):
    """Each lever's vertices over its travel that pass under the surface it slides on outside its slot (2 mm clear of
    the slot's sides and ends): its stalk must stay in its slot and its grip over the surface."""
    faults = {}
    for name, (acc_, rest, far, (frame, x0, x1, y0, y1, zs)) in LEVERS.items():
        inv = frame.inverted()
        n_ = 0
        for k in range(steps):
            d_ = (far - rest) * (k / (steps - 1))
            for pts, _, _ in acc_.faces:
                for v in pts:
                    q = inv @ (v + d_)
                    if q.z < zs - 0.0005 and not (x0 + 0.002 <= q.x <= x1 - 0.002 and y0 + 0.002 <= q.y <= y1 - 0.002):
                        n_ += 1
        faults[name] = n_
    return faults


LAMP_HOUSING_OUT = 0.003  # metres the missile warning lamps' housings move toward the crew off the screen's frame


def lamp_housings_out(bezel):
    """The missile warning lamps' housings on band_bezel (art/blender/cockpit/flightdeck.py build_warning_lamps, a flat
    housing WARNING_LAMP_PROUD in front of the screen's curved frame, 9.6 cm wide over each seat's radar) moved
    LAMP_HOUSING_OUT toward the crew: on the 4.5 m frame their outer ends sank into
    it, plates passing through each other over the pilot's flight display. Done here, on the export's copy, as the game
    draws it."""
    import bmesh as _bmh
    import flightdeck_screen as band_shape
    axis_y = bo.st(band_shape.axis_station(bo.BAND_RADIUS or band_shape.R0))
    mw = bezel.matrix_world
    bm = _bmh.new()
    bm.from_mesh(bezel.data)
    bm.faces.ensure_lookup_table()
    seen, moved = set(), 0
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        stack, comp = [f0], []
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            comp.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        vs = {v for f in comp for v in f.verts}
        ws = [mw @ v.co for v in vs]
        c_ = sum(ws, Vector()) / len(ws)
        span = max(w.x for w in ws) - min(w.x for w in ws)
        if 0.45 < abs(c_.x) < 0.85 and 4.765 < c_.z < 4.805 and 5.74 < c_.y - bo.st(0.0) < 5.86 and span < 0.35:
            out = Vector((-c_.x, axis_y - c_.y, 0.0)).normalized() * LAMP_HOUSING_OUT
            d_ = mw.inverted().to_3x3() @ out
            for v in vs:
                v.co += d_
            moved += 1
    bm.to_mesh(bezel.data)
    bm.free()
    print("LAMP HOUSINGS", moved, "pieces of band_bezel moved %.0f mm toward the crew" % (LAMP_HOUSING_OUT * 1000))


def caption_texts(cards):
    """Every printed text on the cards, as (world point, text), from CARDS or a card spec's records."""
    out = []
    for c in cards:
        frame = c["frame"] if isinstance(c["frame"], Matrix) else Matrix(c["frame"])
        for it in c["items"]:
            if it[0] == "text":
                out.append((frame @ Vector((c["x0"] + it[1], c["y0"] + it[2], c["z"])), it[4]))
    return out


def caption_mismatches(spec_path):
    """Controls whose nearest caption on the sheet the textures were baked from (the card spec at spec_path) is not
    their nearest caption in this build's layout. Card ids follow the order panels are built in, so a build that keeps
    the sheets (-KeepTextures) after panels moved draws each panel's old neighbour's captions under its controls: the
    overhead's TRIM and EXT LIGHTS rows swapped controls but kept each other's lettering."""
    import json as json_
    baked = caption_texts(json_.load(open(spec_path))["cards"])
    now = caption_texts(CARDS)

    def nearest(pts, p):
        best = min(pts, key=lambda q: (q[0] - p).length, default=None)
        return best[1] if best is not None and (best[0] - p).length < 0.05 else None
    bad = [(title, label) for title, kind, label, p, _ in NAMED if label and nearest(now, p) != nearest(baked, p)]
    print("CAPTIONS", len(bad), "of", sum(1 for n_ in NAMED if n_[2]), "labelled controls under another control's caption", bad[:8])
    return len(bad)


def card_at(frame, x, y, z, tol=0.0025):
    """The card whose face holds the point (x, y, z) of `frame`, and the point in the card's own metres, or None."""
    p_ = frame @ Vector((x, y, z))
    for c in reversed(CARDS):
        q_ = c["inv"] @ p_
        lx, ly = q_.x - c["x0"], q_.y - c["y0"]
        if -1e-4 <= lx <= c["w"] + 1e-4 and -1e-4 <= ly <= c["h"] + 1e-4 and abs(q_.z - c["z"]) < tol:
            return c, lx, ly
    return None


def card_uv(t, c, lx, ly):
    rect = t.cards.get(c["id"])
    if rect is None:  # the spec pass: no card baked yet
        return (0.0, 0.0)
    pxm = (rect[2] - rect[0]) / c["w"]
    return t.uv(rect[0] + lx * pxm, rect[3] - ly * pxm)


def card_prism(ctx, frame, x0, y0, x1, y1, z0, z1, bevel, paint):
    """A rectangular plate whose top face is a card: sides on the side strip, a worn chamfer, the top on its own region
    of the sheet. Returns the card, to which items are added in the plate's own metres from (x0, y0)."""
    t = ctx["t"]
    fm = FM(ctx["acc"], frame)
    c = card_new(frame, x0, y0, x1 - x0, y1 - y0, z1, paint)
    o = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    i = [(x0 + bevel, y0 + bevel), (x1 - bevel, y0 + bevel), (x1 - bevel, y1 - bevel), (x0 + bevel, y1 - bevel)]
    zc = z1 - bevel
    run = 0.0
    for k in range(4):
        j = (k + 1) % 4
        ln = ((o[j][0] - o[k][0]) ** 2 + (o[j][1] - o[k][1]) ** 2) ** 0.5
        fm.face([(o[k][0], o[k][1], z0), (o[j][0], o[j][1], z0), (o[j][0], o[j][1], zc), (o[k][0], o[k][1], zc)],
                [t.strip("side", run, 0), t.strip("side", run + ln, 0), t.strip("side", run + ln, 1), t.strip("side", run, 1)])
        fm.face([(o[k][0], o[k][1], zc), (o[j][0], o[j][1], zc), (i[j][0], i[j][1], z1), (i[k][0], i[k][1], z1)],
                [t.strip("edge", run, 0.1), t.strip("edge", run + ln, 0.1), t.strip("edge", run + ln, 0.9), t.strip("edge", run, 0.9)])
        run += ln
    c["top"] = (fm, [(q[0], q[1]) for q in i], z1)
    return c


def clip_poly(poly, rect):
    """A convex polygon (2D points) clipped to an axis-aligned rectangle (x0, y0, x1, y1)."""
    out_ = list(poly)
    for axis, val, keep_greater in ((0, rect[0], True), (0, rect[2], False), (1, rect[1], True), (1, rect[3], False)):
        if not out_:
            break
        src, out_ = out_, []
        for k in range(len(src)):
            a, b = src[k], src[(k + 1) % len(src)]
            ina = (a[axis] >= val) if keep_greater else (a[axis] <= val)
            inb = (b[axis] >= val) if keep_greater else (b[axis] <= val)
            if ina:
                out_.append(a)
            if ina != inb:
                f = (val - a[axis]) / (b[axis] - a[axis])
                out_.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out_ if len(out_) >= 3 else []


def _inside(poly, q, eps=1e-7):
    """Whether point q lies strictly inside the convex polygon `poly` (anticlockwise or clockwise)."""
    s = 0
    for k in range(len(poly)):
        a, b = poly[k], poly[(k + 1) % len(poly)]
        cr = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
        if abs(cr) <= eps:
            return False
        s += 1 if cr > 0 else -1
    return abs(s) == len(poly)


ISLAND_GAP = 0.0004  # metres of paint kept between two lettering islands side by side on a card
ISLANDS_TOUCHING = [0, 0]  # island pairs closer than that on their cards: as baked, and as built


def touching_islands(rects):
    """Pairs of a card's lettering islands that overlap or stand closer than ISLAND_GAP side by side or one over the
    other: their faces lie in the card's plane, so where they meet they fight for the same pixels."""
    n_ = 0
    for i, a_ in enumerate(rects):
        for b_ in rects[i + 1:]:
            gx = max(a_[0], b_[0]) - min(a_[2], b_[2])
            gy = max(a_[1], b_[1]) - min(a_[3], b_[3])
            n_ += max(gx, gy) < ISLAND_GAP - 1e-6
    return n_


def build_card_tops(t):
    """Every card's top face, in its own plane: its lettering islands as faces on the ink sheet (material 1), the paint
    round them as rectangles on the card (material 0), cut along the islands' edges, so the grain runs on across the cut
    (both sample the same paint field) and only the lettering gains resolution."""
    for c in CARDS:
        if "top" not in c:
            continue
        fm, poly, z = c["top"]
        isl = t.ink.get("islands", {}).get(c["id"], [])
        ox, oy = c["x0"], c["y0"]
        rects = [[i["m"][0] + ox, i["m"][1] + oy, i["m"][2] + ox, i["m"][3] + oy, list(i["px"])] for i in isl]
        ISLANDS_TOUCHING[0] += touching_islands(rects)
        # islands side by side keep ISLAND_GAP of paint between them, taken from their margins: where two touched (HDG
        # HOLD between ALT HOLD and COMBAT HT) their holes met in the paint's polygon, its triangulation laid paint in
        # the lettering's plane over it, and the two flickered
        for lo_, hi_, olo, ohi in ((0, 2, 1, 3), (1, 3, 0, 2)):  # side by side, then one over the other
            for a_ in rects:
                for b_ in rects:
                    if (a_ is b_ or a_[lo_] > b_[lo_] or min(a_[ohi], b_[ohi]) - max(a_[olo], b_[olo]) <= 0
                            or b_[lo_] - a_[hi_] >= ISLAND_GAP):
                        continue
                    d_ = (ISLAND_GAP - (b_[lo_] - a_[hi_])) / 2
                    for r_, side, sgn in ((a_, hi_, -1.0), (b_, lo_, 1.0)):
                        k_ = (r_[4][hi_] - r_[4][lo_]) / (r_[hi_] - r_[lo_])  # the sheet's pixels per metre this way
                        r_[side] += sgn * d_
                        r_[4][side] += sgn * d_ * k_
        ISLANDS_TOUCHING[1] += touching_islands(rects)
        inside = [r for r in rects if len(clip_poly(poly, r[:4])) == 4 and all(_inside(poly, q) for q in
                                                                           ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])))]
        if len(inside) == len(rects):
            # the paint round the islands as one polygon with a hole per island, triangulated whole: its vertices are
            # the card's corners and the islands' only, so no vertex lies inside another face's edge
            from mathutils.geometry import tessellate_polygon
            loops = [[Vector((q[0], q[1], 0)) for q in poly]] + [[Vector((r[0], r[1], 0)), Vector((r[2], r[1], 0)), Vector((r[2], r[3], 0)),
                                                                   Vector((r[0], r[3], 0))] for r in rects]
            flat = [v for lp in loops for v in lp]
            for tri in tessellate_polygon(loops):
                q3 = [flat[k] for k in tri]
                if (q3[1] - q3[0]).cross(q3[2] - q3[0]).z < 0:
                    q3 = q3[::-1]
                fm.face([(q.x, q.y, z) for q in q3], [card_uv(t, c, q.x - ox, q.y - oy) for q in q3])
        bx0, bx1 = min(q[0] for q in poly), max(q[0] for q in poly)
        by0, by1 = min(q[1] for q in poly), max(q[1] for q in poly)
        ys = [] if len(inside) == len(rects) else sorted({by0, by1} | {v for r in rects for v in (r[1], r[3]) if by0 < v < by1})
        for ya, yb in zip(ys, ys[1:]):
            spans = sorted((r[0], r[2]) for r in rects if r[1] < yb - 1e-9 and r[3] > ya + 1e-9)
            x = bx0
            for sa, sb in spans + [(bx1, bx1)]:
                if sa > x + 1e-9:
                    f = clip_poly(poly, (x, ya, sa, yb))
                    if f:
                        fm.face([(q[0], q[1], z) for q in f], [card_uv(t, c, q[0] - ox, q[1] - oy) for q in f])
                x = max(x, sb)
        for r in rects:
            f = clip_poly(poly, r[:4])
            if not f:
                continue
            X0, Y0, X1, Y1 = r[4]

            def uv(q, r=r, X0=X0, Y0=Y0, X1=X1, Y1=Y1):
                return t.uv(X0 + (q[0] - r[0]) / (r[2] - r[0]) * (X1 - X0), Y1 - (q[1] - r[1]) / (r[3] - r[1]) * (Y1 - Y0))
            fm.face([(q[0], q[1], z) for q in f], [uv(q) for q in f], mat=1)


def cellc(t, name):
    """The UV at the centre of a solid-colour cell."""
    return t.cell(t.hw[name] if name in t.hw else t.labels[name], 0.5, 0.5)


def solid(fm, t, pts, name, bottom=True):
    """A hexahedron from 8 points (the bottom 4, then the top 4 above them), every face on one solid cell; `bottom`
    False leaves out the face it stands on."""
    uv = cellc(t, name)
    b, u = pts[:4], pts[4:]
    for f in ([list(reversed(b))] if bottom else []) + [list(u)] + [[b[i], b[(i + 1) % 4], u[(i + 1) % 4], u[i]] for i in range(4)]:
        fm.face(f, [uv] * 4)


def keycap2(ctx, frame, centre, w, h, z0, z1, face_rect, frame_w=0.0015, bev=0.0009, mat=0):
    """A push key: a dark frame it sits in, light sides, a bright chamfer round its face, the face on its cell (a
    legend, or a display key's plain face)."""
    t = ctx["t"]
    fm = FM(ctx["acc"], frame)
    cx, cy = centre

    def rect(dw, dh, z):
        return [(cx - dw / 2, cy - dh / 2, z), (cx + dw / 2, cy - dh / 2, z), (cx + dw / 2, cy + dh / 2, z), (cx - dw / 2, cy + dh / 2, z)]
    zb = z0 + 0.0008
    solid(fm, t, rect(w + 2 * frame_w, h + 2 * frame_w, z0) + rect(w + 2 * frame_w, h + 2 * frame_w, zb), "keyframe", bottom=False)
    sides, tops, inner = rect(w, h, zb), rect(w, h, z1 - bev), rect(w - 2 * bev, h - 2 * bev, z1)
    k, e = cellc(t, "keyside"), cellc(t, "keyedge")
    for i in range(4):
        j = (i + 1) % 4
        fm.face([sides[i], sides[j], tops[j], tops[i]], [k] * 4)
        fm.face([tops[i], tops[j], inner[j], inner[i]], [e] * 4)
    fm.face(inner, [t.cell(face_rect, 0, 0), t.cell(face_rect, 1, 0), t.cell(face_rect, 1, 1), t.cell(face_rect, 0, 1)], mat=mat)


def cylinder(fm, t, c, axis, r, half, sides, name, ends=None, caps=True):
    """A closed cylinder about `axis` ("x", "y" or "z") through c, on one solid cell (its end caps on `ends`)."""
    uv = cellc(t, name)
    uv_end = cellc(t, ends) if ends else uv
    import math as _m
    ring = []
    for k in range(sides):
        a = 2 * _m.pi * k / sides
        u, v = r * _m.cos(a), r * _m.sin(a)
        ring.append((u, v))

    def pt(u, v, s):
        if axis == "y":
            return (c[0] + u, c[1] + s, c[2] + v)
        return (c[0] + s, c[1] + u, c[2] + v) if axis == "x" else (c[0] + u, c[1] + v, c[2] + s)
    for k in range(sides):
        (u0, v0), (u1, v1) = ring[k], ring[(k + 1) % sides]
        fm.face([pt(u0, v0, -half), pt(u1, v1, -half), pt(u1, v1, half), pt(u0, v0, half)], [uv] * 4)
    if caps:
        fm.face([pt(u, v, half) for u, v in ring], [uv_end] * sides)
        fm.face([pt(u, v, -half) for u, v in reversed(ring)], [uv_end] * sides)


GUARD_OPEN = 0.0  # degrees the cover stands open: closed over the toggle, as the static interior ships; GUARD_OPEN env var overrides


def guard(ctx, frame, x, y, z):
    """A hinged guard in the stock Darkreach cover's form (stock/darkreach/cockpit_int__9.obj):
    a hood with no floor, a sloped back plate over the hinge, a lid, a front wall down to the panel and two side walls,
    1 mm thick with every cut edge shown, a 0.6 mm chamfer where lid meets side, on a pin through two knuckles inside
    its back corners and two fixed lugs outside them: 13.5 mm wide, 24 mm from the pin, 13 mm tall, over a guarded
    toggle whose lever tops out 11.6 mm up, 10 mm from the pin. The pin runs along the panel's y on the toggle's right,
    so the open cover (GUARD_OPEN deg) stands beside its toggle, its dark inside and cut edges toward the toggle, and
    hides nothing above it: hinged at its upper end, as the stock cover is, it stood 27 mm tall in front of the title."""
    import math as _m
    import os as _os
    t = ctx["t"]
    fm = FM(ctx["acc"], frame)
    ang = _m.radians(float(_os.environ.get("GUARD_OPEN", GUARD_OPEN)))
    W, Lc, H, th, bev, wb, wh = 0.0135, 0.024, 0.013, 0.001, 0.0010, 0.0003, 0.0035
    hx = x + 0.010  # the pin's axis, along the panel's y, wh above the panel, 10 mm to the toggle's right
    ca, sa = _m.cos(ang), _m.sin(ang)

    def P(u, s, w):  # cover point (u from the pin toward the free end, s across, w up, closed) to the panel frame
        u_, w_ = u * ca - (w - wh) * sa, wh + u * sa + (w - wh) * ca
        return (hx - u_, y + s, z + w_)
    cap = t.hw["guard_cap"]

    def cu(fu, fv):
        return t.cell(cap, 0.1 + 0.8 * min(1, max(0, fu)), 0.12 + 0.76 * min(1, max(0, fv)))
    edge_uv, dark_uv = t.cell(cap, 0.5, 0.03), cellc(t, "guard_dark")
    centre = Vector(P(Lc * 0.5, 0.0, H * 0.45))

    def face(pts, uvs, inward=False):  # wound so its normal faces away from (or, inside, toward) the cover's middle
        v = [Vector(q) for q in pts]
        n = Vector((0, 0, 0))
        for k in range(len(v)):
            a, b = v[k], v[(k + 1) % len(v)]
            n += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
        mid = sum(v, Vector()) / len(v)
        if (n.dot(mid - centre) < 0) != inward:
            pts, uvs = list(reversed(pts)), list(reversed(uvs))
        fm.face(pts, uvs)

    def offset(R, d):  # the profile R (u, w) moved d inward (to its right walking back to front), corners mitred
        segs = []
        for (u0, w0), (u1, w1) in zip(R, R[1:]):
            L_ = _m.hypot(u1 - u0, w1 - w0)
            segs.append(((w1 - w0) / L_, -(u1 - u0) / L_))
        out = [(R[0][0] + segs[0][0] * d, R[0][1] + segs[0][1] * d)]
        for k in range(1, len(R) - 1):
            a, b = segs[k - 1], segs[k]
            m = (a[0] + b[0], a[1] + b[1])
            s_ = d / (1 + a[0] * b[0] + a[1] * b[1])
            out.append((R[k][0] + m[0] * s_, R[k][1] + m[1] * s_))
        out.append((R[-1][0] + segs[-1][0] * d, R[-1][1] + segs[-1][1] * d))
        return out
    R = round_corners([(-0.0025, 0.0055), (0.0050, H), (Lc, H), (Lc, wb)], 0.0012)  # back plate, lid, front wall
    Rb, Rt = offset(R, bev), offset(R, th)
    arc = [0.0]
    for (u0, w0), (u1, w1) in zip(R, R[1:]):
        arc.append(arc[-1] + _m.hypot(u1 - u0, w1 - w0))
    hs, hb, ht = W / 2, W / 2 - bev, W / 2 - th
    for k in range(len(R) - 1):
        a, b = R[k], R[k + 1]
        fa, fb = arc[k] / arc[-1], arc[k + 1] / arc[-1]
        face([P(a[0], -hb, a[1]), P(b[0], -hb, b[1]), P(b[0], hb, b[1]), P(a[0], hb, a[1])], [cu(fa, 0), cu(fb, 0), cu(fb, 1), cu(fa, 1)])
        for sg in (-1, 1):  # the chamfer, the worn edge
            face([P(a[0], sg * hb, a[1]), P(b[0], sg * hb, b[1]), P(Rb[k + 1][0], sg * hs, Rb[k + 1][1]), P(Rb[k][0], sg * hs, Rb[k][1])], [edge_uv] * 4)
        c, d_ = Rt[k], Rt[k + 1]  # the lid's underside
        face([P(c[0], -ht, c[1]), P(d_[0], -ht, d_[1]), P(d_[0], ht, d_[1]), P(c[0], ht, c[1])], [dark_uv] * 4, inward=True)
    for sg in (-1, 1):
        side = [(Rb[0][0], wb)] + Rb + [(Rb[-1][0], wb)]
        face([P(u, sg * hs, w) for u, w in side], [cu((u - R[0][0]) / (Lc - R[0][0]), w / H) for u, w in side])
        inner = [(Rt[0][0], wb)] + Rt + [(Rt[-1][0], wb)]
        face([P(u, sg * ht, w) for u, w in inner], [dark_uv] * len(inner), inward=True)
        # the cut edges, 1 mm across: the side wall's foot, its back edge
        face([P(Rb[0][0], sg * hs, wb), P(Rb[-1][0], sg * hs, wb), P(Rt[-1][0], sg * ht, wb), P(Rt[0][0], sg * ht, wb)], [edge_uv] * 4)
        face([P(Rb[0][0], sg * hs, wb), P(Rb[0][0], sg * hs, Rb[0][1]), P(Rt[0][0], sg * ht, Rt[0][1]), P(Rt[0][0], sg * ht, wb)], [edge_uv] * 4)
    # the front wall's foot and the back plate's lower edge, across the width
    for e_, eb, et in ((R[-1], Rb[-1], Rt[-1]), (R[0], Rb[0], Rt[0])):
        face([P(eb[0], -hs, eb[1]), P(e_[0], -hb, e_[1]), P(e_[0], hb, e_[1]), P(eb[0], hs, eb[1]), P(et[0], ht, et[1]), P(et[0], -ht, et[1])], [edge_uv] * 6)
    # the hinge: a dark pin through two red knuckles in the cover's back corners and two red lugs fixed to the panel
    rf = FM(ctx["round"], frame)
    cylinder(rf, t, (hx, y, z + wh), "y", 0.0012, hs + 0.0034, 8, "pin", ends="keyedge")
    for sg in (-1, 1):  # the knuckles: 6-sided, their ends against the walls and the pin, so no caps
        cylinder(fm, t, P(0.0, sg * (ht - 0.0018), wh), "y", 0.0021, 0.0018, 6, "guard_red", caps=False)
        a_, b_ = sorted((y + sg * (hs + 0.0003), y + sg * (hs + 0.0025)))
        lug(fm, t, hx, a_, b_, z, wh)


def toggle(ctx, frame, x, y, z, s, lever, tilt):
    """A toggle switch in 84 triangles, the stock one's size: a hex nut 12 mm across corners and 2.5 mm tall, a
    10-sided threaded barrel 7.2 mm across to 9 mm up, an 8-sided lever tapering from 2.6 to 3.2 mm across, `lever`
    long to the middle of a 4.2 mm ball that grows out of it (one mesh, no seam), leaned `tilt` deg about the panel's x.
    The nut and barrel plated, lever and ball bright. `s` scales the nut and barrel (a guarded toggle's is 0.64). On the
    round accumulator, so barrel, lever and ball shade round (edges under 50 deg) and the nut's corners stay sharp."""
    t = ctx["t"]
    fm = FM(ctx["round"], frame)
    plated, bright = cellc(t, "tmetal"), cellc(t, "keyedge")

    def ring(n, r, zz, rot=0.0):
        return [(x + r * math.cos(rot + 2 * math.pi * k / n), y + r * math.sin(rot + 2 * math.pi * k / n), zz) for k in range(n)]

    def band(a, b, uv):
        for k in range(len(a)):
            j = (k + 1) % len(a)
            fm.face([a[k], a[j], b[j], b[k]], [uv] * 4)
    zn, zb = z + 0.0025 * s, z + 0.009 * s
    nut = ring(6, 0.006 * s, zn)
    band(ring(6, 0.006 * s, z), nut, plated)
    fm.face(nut, [plated] * 6)
    top = ring(10, 0.0036 * s, zb, math.pi / 10)
    band(ring(10, 0.0036 * s, zn, math.pi / 10), top, plated)
    fm.face(top, [plated] * 10)
    a_ = math.radians(tilt)
    d = Vector((0, -math.sin(a_), math.cos(a_)))
    ex = Vector((1, 0, 0))
    side = d.cross(ex).normalized()  # each ring runs anticlockwise about d: faces point out

    def lring(c, r, n=8):
        return [tuple(c + ex * r * math.cos(2 * math.pi * k / n) + side * r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    k_ = min(1.0, s * 1.3)
    rb = 0.0021 * k_
    foot, ball = Vector((x, y, zb)), Vector((x, y, zb)) + d * lever
    neck = ball - d * rb * 0.75  # where the shaft meets the ball
    shaft = lring(foot, 0.0013 * k_)
    collar = lring(neck, 0.0016 * k_)
    band(shaft, collar, bright)
    equator = lring(ball, rb)
    band(collar, equator, bright)
    apex = tuple(ball + d * rb)
    for k in range(8):
        fm.face([equator[k], equator[(k + 1) % 8], apex], [bright] * 3)


def lamp(ctx, frame, x, y, z, lens_rect):
    """An indicator lamp in 60 triangles (the stock housing and a flat lens took 98): a 12-sided housing 12 mm across
    and 4 mm tall, its top a ring round a lens 6.8 mm across that domes 1.2 mm, so the lens takes a highlight instead of
    reading as a flat disc; shaded round."""
    t = ctx["t"]
    fm = FM(ctx["round"], frame)
    dark = cellc(t, "pin")
    n, ro, ri, z1 = 12, 0.006, 0.0034, z + 0.004

    def ring(r, zz):
        return [(x + r * math.cos(2 * math.pi * k / n), y + r * math.sin(2 * math.pi * k / n), zz) for k in range(n)]
    base, rim, lip = ring(ro, z), ring(ro, z1), ring(ri, z1)
    for k in range(n):
        j = (k + 1) % n
        fm.face([base[k], base[j], rim[j], rim[k]], [dark] * 4)
        fm.face([rim[k], rim[j], lip[j], lip[k]], [dark] * 4)

    def luv(q):
        return t.cell(lens_rect, 0.5 + (q[0] - x) / (2 * ri), 0.5 + (q[1] - y) / (2 * ri))
    top = (x, y, z1 + 0.0012)
    for k in range(n):
        j = (k + 1) % n
        fm.face([lip[k], lip[j], top], [luv(lip[k]), luv(lip[j]), luv(top)])


def round_corners(R, r):
    """A profile polyline with each inner corner cut by two segments `r` back along its sides (a rounded edge)."""
    out = [R[0]]
    for k in range(1, len(R) - 1):
        p, a, b = Vector(R[k]), Vector(R[k - 1]), Vector(R[k + 1])
        pa, pb = p + (a - p).normalized() * r, p + (b - p).normalized() * r
        mid = (pa + pb) / 2 + (p - (pa + pb) / 2) * 0.45
        out += [tuple(pa), tuple(mid), tuple(pb)]
    return out + [R[-1]]


def lug(fm, t, hx, y0, y1, z, wh):
    """A hinge lug: a tab 4.4 mm wide standing from the panel to the pin's height, its top rounded round the pin."""
    uv = cellc(t, "guard_red")
    prof = [(hx - 0.0022, z), (hx + 0.0022, z)] + [(hx + 0.0022 * math.cos(math.pi * k / 4), z + wh + 0.0022 * math.sin(math.pi * k / 4)) for k in range(5)]
    for k in range(len(prof)):
        a, b = prof[k], prof[(k + 1) % len(prof)]
        fm.face([(a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1])], [uv] * 4)
    fm.face([(q[0], y1, q[1]) for q in prof], [uv] * len(prof))
    fm.face([(q[0], y0, q[1]) for q in reversed(prof)], [uv] * len(prof))


def frame_of(origin, ex, ey):
    ex, ey = ex.normalized(), ey.normalized()
    ez = ex.cross(ey).normalized()
    m = Matrix((ex, ey, ez)).transposed().to_4x4()
    m.translation = origin
    return m


def face_frame(q, toward):
    """A frame on a quad (BL, BR, TR, TL): origin mid-bottom, x along the bottom, y up the face, z toward `toward`;
    x flips if needed so text reads left to right for whoever looks from `toward`."""
    bl, br, tr, tl = q
    ex = (br - bl).normalized()
    ey = (tl + tr) / 2 - (bl + br) / 2
    ey = (ey - ex * ey.dot(ex)).normalized()
    if ex.cross(ey).dot(toward - (bl + br) / 2) < 0:
        ex = -ex
    return frame_of((bl + br) / 2, ex, ey)


# ---------------------------------------------------------------- the stock kit
_kit_meshes = {}


OWN_KIT = {"knl", "big", "ptr", "stk", "pull", "pull_red", "grip"}  # flightdeck_knobs.py's shapes, which ship; the kit's could not
_own = {}


def kit_mesh(role):
    if role in OWN_KIT:
        import flightdeck_knobs as own_kit
        me = own_kit.mesh(role, _own["t"])
        if not me.materials:
            me.materials.append(_own["trim"])
        return me
    return stock_kit_mesh(role)


def stock_kit_mesh(role):
    """A stock piece by role, loaded once. The bat lever is turned so its own long axis stands on +Z with its foot at
    the origin: the VT-7 mounts it leaning, and its frame from kit_parts.py keeps that lean."""
    if role not in _kit_meshes:
        name, tris = ROLE[role]
        with bpy.data.libraries.load(str(HERE.parents[2] / ".cache" / "art" / "cockpit" / "kit" / "kit.blend")) as (src, dst):
            dst.meshes = [name]
        me = dst.meshes[0]
        got = sum(len(p.vertices) - 2 for p in me.polygons)
        assert got == tris, (role, name, got, tris)
        if role == "lever":
            import numpy as np
            co = np.array([v.co[:] for v in me.vertices])
            c = co.mean(0)
            w, vec = np.linalg.eigh(np.cov((co - c).T))
            axis = Vector(vec[:, -1]).normalized()
            if axis.z < 0:
                axis = -axis
            rot = axis.rotation_difference(Vector((0, 0, 1))).to_matrix().to_4x4()
            me.transform(rot @ Matrix.Translation(-Vector(c)))
            zmin = min(v.co.z for v in me.vertices)
            me.transform(Matrix.Translation((0, 0, -zmin)))
        import bmesh as _bmk
        bk = _bmk.new()  # the export keeps every triangle loose: welded, smoothing has neighbours to blend
        bk.from_mesh(me)
        _bmk.ops.remove_doubles(bk, verts=bk.verts, dist=1e-6)
        bk.to_mesh(me)
        bk.free()
        if me.has_custom_normals:
            me.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(me.loops))
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(50))
        _kit_meshes[role] = me
    return _kit_meshes[role]


def place(coll, role, frame, at, rot=0.0, tilt=0.0, mat=None, scale=1.0):
    """A stock piece on a panel frame: its base on the panel's surface, square to the panel's x axis, turned `rot`
    about the panel normal and leaned `tilt` about the panel's x axis. Uniform scale only."""
    o = bpy.data.objects.new("s2k_" + role, kit_mesh(role))
    o.matrix_world = frame @ Matrix.Translation(Vector(at)) @ Matrix.Rotation(math.radians(rot), 4, "Z") @         Matrix.Rotation(math.radians(tilt), 4, "X") @ Matrix.Scale(scale, 4)
    if mat is not None:
        o.material_slots[0].link = "OBJECT"
        o.material_slots[0].material = mat
    coll.objects.link(o)
    return o


LENS = (('lens_red', ('FIRE', 'OVHT', 'WARN', 'FAIL', 'HOT', 'XMIT', 'TEAR', 'LOCK')), ('lens_amber', ('LO', 'CAUT', 'EMPTY', 'SKID', 'ICE', 'IMBAL', 'UNLOCK', 'TIMER', 'TRIM')))
DIAL = {"knl": 0.008, "big": 0.015, "ptr": 0.0125, "stk": 0.0123}  # knob radii that take a printed scale round them


def lens_for(label):
    for cell, words in LENS:
        if any(w_ in label.split() for w_ in words):
            return cell
    return "lens_green"



CONTACT_R = {"tog": 0.0072, "togw": 0.0072, "gtog": 0.0072, "lamp": 0.0068, "pull": 0.0085, "knl": 0.0088, "big": 0.0158,
             "ptr": 0.0130, "stk": 0.0130, "skt": 0.0130}  # a control's footprint: the soft contact shadow baked round it


_knob_bvh = {}


def knob_profile(kind):
    """The stock knob's own top, sampled once: the direction its index runs (a pointed knob's molded pointer; +y for a
    round one) and the surface height along it, (r, z) in metres at scale 1, from a ray straight down every 0.5 mm."""
    if kind in _knob_bvh:
        return _knob_bvh[kind]
    from mathutils.bvhtree import BVHTree as _B
    me = kit_mesh(kind)
    verts = [v.co.copy() for v in me.vertices]
    tree = _B.FromPolygons(verts, [tuple(pl.vertices) for pl in me.polygons])
    zmax = max(v.z for v in verts)
    rmax = max((v.x * v.x + v.y * v.y) ** 0.5 for v in verts)
    direction = Vector((0, 1, 0))
    if kind == "ptr":  # the pointer reaches furthest among the vertices standing in its upper half
        tall = [v for v in verts if v.z > 0.55 * zmax]
        far = max(tall, key=lambda v: v.x * v.x + v.y * v.y)
        direction = Vector((far.x, far.y, 0)).normalized()
    prof = []
    r = 0.0
    while r < rmax:
        q = direction * r
        hit = tree.ray_cast(Vector((q.x, q.y, zmax + 0.01)), Vector((0, 0, -1)), zmax + 0.02)
        prof.append((r, hit[0].z if hit[0] is not None else None))
        r += 0.0005
    _knob_bvh[kind] = (direction, prof, zmax, rmax)
    return _knob_bvh[kind]


def knob_mark(ctx, kind, frame, x, y, z, scale=1.0):
    """A white index 1.2 mm wide painted on the knob's own top, 0.1 mm proud of it: on a round knob's flat top inside
    its rim, along a pointed knob's crown and down its ramp, on a stacked knob's outer land."""
    direction, prof, zmax, rmax = knob_profile(kind)
    if kind == "stk":  # the outer land: the highest hits away from the centre hole
        land = max(zz for rr, zz in prof if zz is not None)
        run = [(rr, zz) for rr, zz in prof if zz is not None and zz > land - 0.0012]
    elif kind == "ptr":  # the crown, then down the ramp until the pointer's side
        run = []
        for rr, zz in prof:
            if zz is None or zz < 0.58 * zmax:
                break
            run.append((rr, zz))
    else:  # a flat top: from the centre to 62 % of the radius
        run = [(rr, zz) for rr, zz in prof if zz is not None and rr <= 0.62 * rmax and zz > zmax - 0.0006]
    if kind == "ptr":  # it stops 1.5 mm short of the pointer's end, where the moulding narrows under it
        run = [(rr, zz) for rr, zz in run if rr <= run[-1][0] - 0.0015]
    if len(run) < 2:
        return
    t_ = ctx["t"]
    m_ = cellc(t_, "mark")
    fm = FM(ctx["acc"], frame)
    side = Vector((-direction.y, direction.x, 0)) * 0.0006 / scale
    # every 0.5 mm sample, each lifted 0.12 mm along the surface's own normal there, so the line bends with the
    # moulding instead of bridging its change of slope
    pts = []
    for k, (rr, zz) in enumerate(run):
        a_, b_ = run[max(0, k - 1)], run[min(len(run) - 1, k + 1)]
        slope = (b_[1] - a_[1]) / max(1e-9, b_[0] - a_[0])
        n_ = Vector((-slope, 1.0)).normalized()
        pts.append((direction * (rr + n_.x * 0.00012) + Vector((0, 0, zz + n_.y * 0.00012))) * scale)
    base = Vector((x, y, z))
    for a, b in zip(pts, pts[1:]):
        fm.face([base + a - side * scale, base + b - side * scale, base + b + side * scale, base + a + side * scale], [m_] * 4)
    MARKS.append((kind, frame @ (base + pts[0]), frame @ (base + pts[-1]), frame))


def control(ctx, kind, frame, x, y, z, label="", knob_scale=1.0):
    coll, red, t = ctx["coll"], ctx["red"], ctx["t"]
    CONTROLS.append((kind, frame @ Vector((x, y, z))))
    found = card_at(frame, x, y, z)
    if found and kind in CONTACT_R:
        found[0]["items"].append(["ao", found[1], found[2], CONTACT_R[kind] * knob_scale])
    if found and kind == "key":
        found[0]["items"].append(["aorect", found[1] - 0.0085, found[2] - 0.0078, found[1] + 0.0085, found[2] + 0.0078])
    if kind in ("tog", "togw", "gtog"):
        g_ = kind == "gtog"
        toggle(ctx, frame, x, y, z, 0.64 if g_ else 1.0, 0.0042 if g_ else 0.022, -20 if g_ else -14)  # a guarded lever ends 11.5 mm up, under the closed lid (12 mm inside)
        if kind == "gtog":
            guard(ctx, frame, x, y, z)
    elif kind == "key":
        lg = P2.legend(label) if label else ""
        KEY_WORDS.add(lg)  # "" too: a plain light face

        face = t.ink_labels.get("key:" + lg)
        keycap2(ctx, frame, (x, y), 0.014, 0.0124, z, z + 0.0045, face or t.hw["osb"], mat=1 if face else 0)
    elif kind == "lamp":  # a lamp: a dark housing, its domed lens in the colour of what it reports
        lamp(ctx, frame, x, y, z, t.hw[lens_for(label)])
    elif kind == "pull":  # a T-handled pull, short, red when it is a fire handle
        place(coll, "pull_red" if ctx.get("fire") else "pull", frame, (x, y, z), scale=0.6)
        if ctx.get("fire"):  # a red ring at its foot, so a black stem never reads as an exposed post
            sp.cap(FM(ctx["round"], frame), t, (x, y), 0.0075, z, z + 0.0012, 20, t.hw["guard_red"], "bezel")
    elif kind == "cb":
        fm = FM(ctx["acc"], frame)
        sp.cap(fm, ctx["t"], (x, y), 0.0055, z, z + 0.006, 8, ctx["t"].hw["cb"], "side")
    elif kind == "ann":
        pass  # drawn by the caller with its legend
    elif kind == "key":
        place(coll, "key", frame, (x, y, z), scale=0.8)
    elif kind != "gap":
        place(coll, kind, frame, (x, y, z), scale=knob_scale)
        fm = FM(ctx["acc"], frame)
        if kind in DIAL and found:  # the knob's printed scale, ticks over 270 deg, painted into the face round it
            r_k = DIAL[kind] * knob_scale
            found[0]["items"].append(["dial", found[1], found[2], r_k + 0.0012, r_k + 0.0050])
        if kind in ("knl", "big", "ptr", "stk"):
            knob_mark(ctx, kind, frame, x, y, z, knob_scale)


def placard(ctx, frame, x, y, z, word, h=0.0085, style="label", maxw=None, align="c"):
    t = ctx["t"]
    found = card_at(frame, x, y, z)
    if found and style == "label":  # stencilled into the face's own paint, zero offset ("l": x is the left end)
        c, lx, ly = found
        c["items"].append(["text", lx, ly, h, word, maxw or 0.0, align])
        PLACARDS.append(frame @ Vector((x, y, z)))
        return
    FALLBACK.add(word)
    key = style + ":" + word
    if ctx.get("spec") and key not in t.labels:
        return  # the spec pass: this word's cell comes with the next texture pass
    rect = t.labels[key]  # a word with no cell on the trim sheet is a missing label: flightdeck_textures must list it
    w = h * (rect[2] - rect[0]) / (rect[3] - rect[1])  # the cell's own aspect: text never squeezed
    if maxw and w > maxw:  # narrower than its column, so it never runs into its neighbour's label
        h, w = h * maxw / w, maxw
    fm = FM(ctx["acc"], frame)
    fm.face([(x - w / 2, y - h / 2, z), (x + w / 2, y - h / 2, z), (x + w / 2, y + h / 2, z), (x - w / 2, y + h / 2, z)],
            [t.cell(rect, 0, 0), t.cell(rect, 1, 0), t.cell(rect, 1, 1), t.cell(rect, 0, 1)])
    PLACARDS.append(frame @ Vector((x, y, z)))


def fastener(ctx, frame, x, y, z):
    found = card_at(frame, x, y, z)
    if found:  # its seat's shadow baked in the face's own maps; the head itself is the shared domed disc below
        c, lx, ly = found
        c["items"].append(["screwseat", lx, ly, 0.0023])
    fm = FM(ctx["acc"], frame)
    # a flush Dzus head: one 10-sided face 0.2 mm over the panel, on the plated-head cell (8 triangles, not the 28 a
    # raised cap costs; some 450 of them carry the deck)
    fm = FM(ctx["acc"], frame)
    rect = ctx["t"].hw["fastener"]
    ring = [(math.cos(2 * math.pi * k / 8), math.sin(2 * math.pi * k / 8)) for k in range(8)]
    ro = 0.0023 / math.cos(math.pi / 8)  # the octagon round the 4.6 mm head; the cell paints its corners panel dark
    fm.face([(x + ro * c, y + ro * s_, z + 0.00005) for c, s_ in ring], [ctx["t"].cell(rect, 0.5 + 0.5 * c, 0.5 + 0.5 * s_) for c, s_ in ring])
    FASTENERS.append(frame @ Vector((x, y, z)))


GUARD_CLEAR = 0.0  # the open cover stands beside its toggle, so a guarded first row needs no extra room under its title


def title_clear_of_stems(ctx, frame, w, h, title, rows, z, right, aft):
    """Where a panel's title goes so no toggle's lever stands over it from the seat that uses the panel (both seats on
    the pedestal): each lever's silhouette runs from its foot to where the eye's ray past its tip meets the plate, and
    the title tries its given corner, then the other end of its edge, then the other edge (stems
    over MISSION COMP, RECORDER, OXYGEN and others). panel()'s own row layout, repeated for each placement."""
    rect = ctx["t"].labels.get("label:" + title)
    tw = 0.010 * (rect[2] - rect[0]) / (rect[3] - rect[1]) if rect else 0.04
    c = frame @ Vector((w / 2, h / 2, z))
    eyes = [bo.EYE[1], bo.EYE[-1]] if abs(c.x) < 0.3 else [min((bo.EYE[1], bo.EYE[-1]), key=lambda e: (e - c).length)]
    inv = frame.inverted()
    eyes_l = [inv @ e for e in eyes]
    guard_first = rows[0] and rows[0][0][0] == "gtog"

    def crossings(right_, aft_):
        x0 = (w - 0.012 - tw) if right_ else 0.012
        yt = 0.0095 if aft_ else h - 0.0095
        box = (x0 - 0.0015, yt - 0.0065, x0 + tw + 0.0015, yt + 0.0065)
        top = (h - 0.004) if aft_ else h - 0.020 - (GUARD_CLEAR if any(k_ == "gtog" for k_, _ in rows[0]) else 0.0)
        pitch = (top - 0.004 - (0.020 if aft_ else 0.0)) / len(rows)
        n_ = 0
        for r, row in enumerate(rows):
            yc = top - pitch * (r + 0.5) + 0.006
            cw = (w - 0.016) / len(row)
            for ci, (kind, _) in enumerate(row):
                if kind not in ("tog", "togw"):
                    continue
                base = Vector((0.008 + cw * (ci + 0.5), yc, z))
                tip = base + Vector((0.0, -0.022 * math.sin(math.radians(14)), 0.022 * math.cos(math.radians(14))))
                for el in eyes_l:
                    if el.z <= tip.z:
                        continue
                    shadow = el + (tip - el) * ((z - el.z) / (tip.z - el.z))
                    if any(box[0] - 0.002 < p.x < box[2] + 0.002 and box[1] < p.y < box[3]
                           for p in (base.lerp(shadow, k / 12) for k in range(13))):
                        n_ += 1
        return n_
    options = [(right, aft), (not right, aft), (right, not aft), (not right, not aft)]
    options = [o for o in options if (o[1] or o[0] or not guard_first)  # an open guard stands under a left top title
               and (o[1] or not aft)]  # a title put aft by its caller is hidden along the top
    best = min(options, key=lambda o: (crossings(*o), options.index(o)))
    STEM_TITLES.append((title, crossings(right, aft), best != (right, aft), crossings(*best)))
    return best


STEM_TITLES = []  # (title, levers over it where it was asked for, moved, levers over it where it went)


def panel(ctx, frame, w, h, title, rows, z0=0.0, thick=0.003, centre_title=False, blank=True, title_aft=False,
          title_right=False):
    """A Dzus panel on its frame (x 0..w across, y 0..h up, z out): a carded plate (its title, labels, scales and
    screws baked into its own region of the sheet), rows of controls."""
    t = ctx["t"]
    card = card_prism(ctx, frame, 0, 0, w, h, z0, z0 + thick, 0.0016, "field")
    card["title"] = title
    z = z0 + thick
    for fx, fy in ((0.005, 0.005), (w - 0.005, 0.005), (0.005, h - 0.005), (w - 0.005, h - 0.005)):
        fastener(ctx, frame, fx, fy, z)
    PANELS.append((title, frame @ Vector((w / 2, h / 2, z))))
    top = h
    if not title and not rows and blank:  # a blanking plate on an unused rail position, stencilled as one
        placard(ctx, frame, w / 2, h / 2, z + 0.0002, "SPARE", 0.008)
    if title:
        # a guard first in the top row stands open 27 mm tall under a left-hand title: the title goes right
        if rows and rows[0] and rows[0][0][0] == "gtog" and rows[0][-1][0] != "gtog" and not title_aft and not centre_title:
            title_right = True
        if rows and not centre_title:
            title_right, title_aft = title_clear_of_stems(ctx, frame, w, h, title, rows, z, title_right, title_aft)
        rect = ctx["t"].labels.get("label:" + title)
        tw = 0.010 * (rect[2] - rect[0]) / (rect[3] - rect[1]) if rect else 0.04
        # the title along the top edge; along the aft edge where the top one would be hidden from the seat
        placard(ctx, frame, (w / 2) if centre_title else (w - 0.012) if title_right else 0.012, 0.0095 if title_aft else h - 0.0095,
                z + 0.0002, title, 0.011, align="c" if centre_title else "r" if title_right else "l")
        top = (h - 0.004) if title_aft else h - 0.020 - (GUARD_CLEAR if rows and any(k_ == "gtog" for k_, _ in rows[0]) else 0.0)
    n = len(rows)
    if not n:
        return
    pitch = (top - 0.004 - (0.020 if title_aft else 0.0)) / n
    for r, row in enumerate(rows):
        yc = top - pitch * (r + 0.5) + 0.006
        cells = len(row)
        cw = (w - 0.016) / cells
        x_left = 0.008
        if all(k_ == "key" for k_, _ in row) and all(k_ == "key" for r_ in rows for k_, _ in r_):
            cw = min(cw, 0.021)  # a keypad: keys close together, as stock keypads are
            x_left = (w - cw * cells) / 2
        for c, (kind, label) in enumerate(row):
            xc = x_left + cw * (c + 0.5)
            if kind == "ann":
                continue
            ctx["fire"] = label.startswith("FIRE") or label.startswith("CUTOFF")
            control(ctx, kind, frame, xc, yc, z, label)
            NAMED.append((title, kind, label, frame @ Vector((xc, yc, z)), frame))
            if label and (kind != "key" or P2.legend(label) != label):
                drop = 0.021 if kind == "gtog" else (DIAL[kind] + 0.0095) if kind in DIAL else min(0.019, pitch * 0.42)
                placard(ctx, frame, xc, yc - drop, z + 0.0002, label, 0.0095, maxw=cw * 0.96)


def plate2(m, t, poly, z0, z1, bevel, top, top_pxm=1500.0, offset=0.0, side="side"):
    """flightdeck_plates.plate with isotropic UVs: the top maps at one density both ways (at most `top_pxm`, less when the
    plate is taller than its strip), its long side along the strip's U, centred across the strip, so nothing
    stretches; chamfers on the worn edge strip, sides on `side`."""
    poly = [tuple(p) for p in poly]
    ins = sp.inset(poly, bevel) if bevel > 0 else poly
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    along_y = h > w
    rect0 = t.strips[top] if top in t.strips else t.hw[top]
    if len(ins) == 4 and min(w, h) * top_pxm > 0.92 * (rect0[3] - rect0[1]):
        # bands across the short side, each mapped at full density, then the chamfer and sides as below
        q = [Vector((x, y, z1)) for x, y in ins]
        if along_y:  # U along y: start at the edge running along y
            q = [q[1], q[2], q[3], q[0]] if (q[1] - q[0]).length < (q[2] - q[1]).length else q
        band_m = 0.92 * (rect0[3] - rect0[1]) / top_pxm
        p0, p1, p2, p3 = q
        n_ = max(1, math.ceil(max((p3 - p0).length, (p2 - p1).length) / band_m))
        for k in range(n_):
            a0, b0 = p0.lerp(p3, k / n_), p1.lerp(p2, k / n_)
            a1, b1 = p0.lerp(p3, (k + 1) / n_), p1.lerp(p2, (k + 1) / n_)
            bh = (a1 - a0).length * top_pxm / (rect0[3] - rect0[1])
            L_ = (b0 - a0).length
            m.face([a0, b0, b1, a1], [t.strip(top, offset, 0.5 - bh / 2, top_pxm), t.strip(top, offset + L_, 0.5 - bh / 2, top_pxm),
                                      t.strip(top, offset + L_, 0.5 + bh / 2, top_pxm), t.strip(top, offset, 0.5 + bh / 2, top_pxm)])
        ins_done = True
    else:
        ins_done = False
    x0_, y0_ = min(xs), min(ys)
    span = w if along_y else h
    rect = t.strips[top] if top in t.strips else t.hw[top]
    strip_px = rect[3] - rect[1]
    pxm = min(top_pxm, 0.92 * strip_px / max(span, 1e-6))

    def uv(x, y):
        s_, c_ = ((y - y0_), (x - x0_ - w / 2)) if along_y else ((x - x0_), (y - y0_ - h / 2))
        return t.strip(top, s_, 0.5 + c_ * pxm / strip_px, pxm, offset)
    if not ins_done:
        m.face([(x, y, z1) for x, y in ins], [uv(x, y) for x, y in ins])
    n = len(poly)
    per = 0.0
    for i in range(n):
        a_, b_ = Vector(poly[i]), Vector(poly[(i + 1) % n])
        ia, ib = Vector(ins[i]), Vector(ins[(i + 1) % n])
        L = (b_ - a_).length
        if bevel > 0:
            m.face([(a_.x, a_.y, z1 - bevel), (b_.x, b_.y, z1 - bevel), (ib.x, ib.y, z1), (ia.x, ia.y, z1)],
                   [t.strip("edge", per, 0.0, 2048), t.strip("edge", per + L, 0.0, 2048), t.strip("edge", per + L, 1.0, 2048),
                    t.strip("edge", per, 1.0, 2048)])
        hz = (z1 - bevel) - z0
        sv = min(1.0, hz * 1500 / 24)
        m.face([(a_.x, a_.y, z0), (b_.x, b_.y, z0), (b_.x, b_.y, z1 - bevel), (a_.x, a_.y, z1 - bevel)],
               [t.strip(side, per, 0.5 - sv / 2), t.strip(side, per + L, 0.5 - sv / 2), t.strip(side, per + L, 0.5 + sv / 2),
                t.strip(side, per, 0.5 + sv / 2)])
        per += L


sp.plate = plate2  # every plate in this module, and flightdeck_plates' helpers, map isotropically


def tube(ctx, pts, r=0.006, sides=6, strip="cable"):
    """A cable along a polyline, on the cable strip (or a rod, on another strip)."""
    t = ctx["t"]
    acc = ctx["acc"]
    run = 0.0
    rings = []
    for i, p in enumerate(pts):
        d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        u = d.orthogonal().normalized()
        v = d.cross(u)
        rings.append([p + (u * math.cos(2 * math.pi * k / sides) + v * math.sin(2 * math.pi * k / sides)) * r for k in range(sides)])
    for i in range(len(pts) - 1):
        L = (pts[i + 1] - pts[i]).length
        for k in range(sides):
            a, b = rings[i][k], rings[i][(k + 1) % sides]
            c, d = rings[i + 1][(k + 1) % sides], rings[i + 1][k]
            acc.faces.append(([a, b, c, d], [t.strip(strip, run, k / sides, 1500), t.strip(strip, run, (k + 1) / sides, 1500),
                                             t.strip(strip, run + L, (k + 1) / sides, 1500), t.strip(strip, run + L, k / sides, 1500)], 0))
        run += L


def banded(ctx, q, strip, pxm=900.0, run0=0.0):
    """A world quad (p0, p1, p2, p3) mapped isotropically onto a strip: U along p0->p1, V along p0->p3, split into
    bands no taller than the strip holds at `pxm`, so a big face never stretches."""
    t = ctx["t"]
    p0, p1, p2, p3 = q
    rect = t.strips[strip]
    band_m = 0.92 * (rect[3] - rect[1]) / pxm
    hgt = max((p3 - p0).length, (p2 - p1).length)
    n = max(1, math.ceil(hgt / band_m))
    for k in range(n):
        f0, f1 = k / n, (k + 1) / n
        a0, b0 = p0.lerp(p3, f0), p1.lerp(p2, f0)
        a1, b1 = p0.lerp(p3, f1), p1.lerp(p2, f1)
        L = (b0 - a0).length
        bh = (a1 - a0).length
        v0, v1 = 0.5 - bh * pxm / (rect[3] - rect[1]) / 2, 0.5 + bh * pxm / (rect[3] - rect[1]) / 2
        ctx["acc"].faces.append(([a0, b0, b1, a1], [t.strip(strip, run0, v0, pxm), t.strip(strip, run0 + L, v0, pxm),
                                                    t.strip(strip, run0 + L, v1, pxm), t.strip(strip, run0, v1, pxm)], 0))


def box(ctx, lo, hi, top="struct", side="struct", pxm=900):
    """An axis-aligned body, every face banded isotropically on its strip and wound outward; top=None leaves the top
    open. The corners may come in any order (callers give stations aft to forward, which is Blender y high to low):
    unsorted, the faces wound inward and Unity culled them from every seat."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    run0 = (x0 + y0) * 0.7
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    z0, z1 = sorted((z0, z1))
    P = [Vector((x, y, z)) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    for k, (a_, b_, c_, d_) in {"top": (4, 5, 7, 6), "f": (0, 1, 5, 4), "b": (3, 2, 6, 7), "l": (2, 0, 4, 6), "r": (1, 3, 7, 5)}.items():
        if k == "top" and top is None:
            continue
        banded(ctx, (P[a_], P[b_], P[c_], P[d_]), top if k == "top" else side, pxm, run0=run0)


# ---------------------------------------------------------------- the main panel
class Rec(bo.Builder):
    def __init__(self):
        super().__init__(None)
        self.slabs = []

    def slab(self, key, quad, n, t0, t1):
        self.slabs.append((key, [Vector(p) for p in quad], n, t0, t1))

    def add(self, key, verts, faces):
        pass

    def box(self, *a, **k):
        pass

    def cyl(self, *a, **k):
        pass


PAGE_RECTS = {"radar": ((2.8, 146.1, 585.7, 488.5), False), "pfd": ((289.8, 2.6, 521.4, 143.8), True),
              "gauges": ((16.1, 2.3, 264.5, 143.4), True), "engines": ((595.7, 257.0, 810.6, 509.4), False),
              "stores": ((811.8, 191.8, 1012.2, 504.9), False), "wing": ((595.7, 1.6, 803.4, 253.9), False)}


def screens(displays, mat, coll):
    m = sp.Mesh()
    for name, page, quad, _ in displays:
        (x0, y0, x1, y1), turned = PAGE_RECTS[page]
        uvs = []
        for fu, fv in ((0, 0), (1, 0), (1, 1), (0, 1)):
            if turned:
                uvs.append(((x1 - (x1 - x0) * fv) / 1024, (y0 + (y1 - y0) * fu) / 512))
            else:
                uvs.append(((x0 + (x1 - x0) * fu) / 1024, (y0 + (y1 - y0) * fv) / 512))
        m.face(SCREENS[name][1], uvs)
    return m.build("s2_screens", Matrix(), [mat], coll)


CONES = []  # (eye, page quad, page centre): every display's sight cone from the eye of its seat. The margin is 10 mm:
# the blockout's page quads lean a few mm inside the bezel rectangle the screens fill


def cone_planes(eye, quad, centre):
    """The four planes through the eye and each edge of the page, each with its normal toward the page's centre."""
    planes = []
    for i in range(4):
        a, b = Vector(quad[i]), Vector(quad[(i + 1) % 4])
        n_ = (a - eye).cross(b - eye).normalized()
        if n_.dot(centre - eye) < 0:
            n_ = -n_
        planes.append(n_)
    return planes


def grown(quad, by):
    """The page quad grown by `by` metres in its own plane: the bezel and its key columns round the page."""
    c_ = sum(quad, Vector()) / 4
    return [c_ + (v - c_) + (v - c_).normalized() * by * 1.414 for v in quad]


def in_cone(p_, eye, quad, centre, margin=0.010):
    if (p_ - eye).dot(centre - eye) <= 0 or (p_ - eye).length > (centre - eye).length + 0.05:
        return False  # behind the eye, or beyond the page
    return all((p_ - eye).dot(n_) > -margin for n_ in cone_planes(eye, quad, centre))


def poly_samples(poly, n=7):
    """Points over a convex polygon: a fan of n x n samples from its first vertex."""
    pts = []
    for i in range(1, len(poly) - 1):
        a, b, c = poly[0], poly[i], poly[i + 1]
        for u in range(n + 1):
            for v in range(n + 1 - u):
                pts.append(a + (b - a) * (u / n) + (c - a) * (v / n))
    return pts


def clip_out_of_cones(poly, margin=0.010, cones=None):
    """A convex polygon (world points) with every part inside a display's sight cone cut away, one edge plane per
    cone: the plane that leaves the most of the polygon outside. cones: those to clip by, all by default."""
    for eye, quad, centre in (CONES if cones is None else cones):
        if not any(in_cone(v, eye, quad, centre, margin) for v in poly_samples(poly)):
            continue
        best = None
        for n_ in cone_planes(eye, quad, centre):
            s = [(v - eye).dot(n_) + margin for v in poly]
            keep = sum(max(0.0, -x) for x in s)
            if best is None or keep > best[0]:
                best = (keep, n_)
        n_ = best[1]
        out_ = []
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            sa, sb = (a - eye).dot(n_) + margin, (b - eye).dot(n_) + margin
            if sa <= 0:
                out_.append(a)
            if (sa <= 0) != (sb <= 0):
                out_.append(a.lerp(b, sa / (sa - sb)))
        poly = out_
        if len(poly) < 3:
            return []
    return poly


def main_panel(ctx):
    rec = Rec()
    displays = []
    edges_p = bo.build_cluster(rec, 1, bo.PILOT, displays)
    edges_c = bo.build_cluster(rec, -1, bo.COMMANDER, displays)
    bo.build_centre(rec, displays, edges_p, edges_c)
    t = ctx["t"]
    pilot = bo.EYE[1]
    MODULE_QUADS[:] = [q for key, q, n, t0, t1 in rec.slabs if key == "panel" and abs(t0 + bo.SLAB) < 1e-6]
    CONES[:] = [(bo.EYE[1] if (d_[0].endswith("pilot") or d_[0] in ("engines", "gauges")) else bo.EYE[-1],
                 grown([Vector(v) for v in d_[2]], 0.028), sum((Vector(v) for v in d_[2]), Vector()) / 4) for d_ in displays]
    hoods, cheek_hoods = [], []
    after_cheek = False
    for key, q, n, t0, t1 in rec.slabs:
        cheek = after_cheek
        after_cheek = key == "panel" and abs(t0 + 0.01) < 1e-6  # bo.build_centre lays each cheek, then its hood
        if key == "panel" and abs(t0 + bo.SLAB) < 1e-6:
            module(ctx, q, n, displays)
        elif key == "hood":
            if (q[1] - q[0]).length < 0.10:
                continue  # the blockout's hoods over the centre stack's cheeks: slivers that cut across the status page
            pts = [p + n * t1 for p in q]
            if pts[0].x < pts[1].x:  # its front edge running toward -X, from the pilot's side across
                pts = [pts[1], pts[0], pts[3], pts[2]]
            hoods.append(pts)
            if cheek:
                cheek_hoods.append(pts)
        elif key == "panel":  # knees and cheeks: dark plates with a fastener row
            fr = face_frame(q, pilot if (q[0] - bo.EYE[1]).length < (q[0] - bo.EYE[-1]).length else bo.EYE[-1])
            inv = fr.inverted()
            loc = [inv @ p for p in q]
            fm = FM(ctx["acc"], fr)
            thick = 0.02 if abs(t0 + 0.02) < 1e-6 else 0.003  # knees 2 cm; the centre stack's cheeks thin
            if thick < 0.01:  # a cheek: cut back to just outside every display's sight cone
                # 22 mm clear of the cone (at 10 a cheek's corner stood over the pilot's stores bezel)
                clipped = clip_out_of_cones([Vector(v) for v in q], margin=0.022)
                if len(clipped) < 3:
                    continue
                # and under the glare hoods' plate (its underside 4 mm under the modules' tops): the pilot's, cut to a
                # wedge by the cones, stood its top edge up to 4.773 through the plate by the engine display, an X of
                # hair lines under the rail in game
                z_cut, under = bo.Z_TOP - 0.010, []
                for k_, p_ in enumerate(clipped):
                    p2_ = clipped[(k_ + 1) % len(clipped)]
                    if p_.z <= z_cut:
                        under.append(p_)
                    if (p_.z - z_cut) * (p2_.z - z_cut) < 0:
                        under.append(p_.lerp(p2_, (z_cut - p_.z) / (p2_.z - p_.z)))
                if len(under) < 3:
                    continue
                loc = [inv @ v for v in under]
            sp.plate(fm, t, [(p.x, p.y) for p in loc], -thick, 0.0, 0.0015 if thick > 0.01 else 0.0, "dark", offset=0.3)
            if thick > 0.01:  # the knees: a fastener row; the centre stack's thin cheeks none (their top row stood by the
                # hoods' corner, plated heads turned to the pilot that read as pale points at the screen's foot)
                xs = sorted(p.x for p in loc)
                for k in range(4):
                    fastener(ctx, fr, xs[0] + (xs[-1] - xs[0]) * (0.1 + 0.8 * k / 3), max(p.y for p in loc) - 0.01, 0.0)
    glare_hoods(ctx, hoods, cheek_hoods)
    close_module_joins(ctx)
    return displays


def glare_hoods(ctx, hoods, cheek_hoods):
    """The modules' glare hoods, flat at their tops' height from each module's top edge back to the band housing, as
    continuous plates: each run of hoods whose corners meet (within 1 cm) is one 4 mm plate with a worn chamfer on its
    outline only. One plate per module drew a chamfered seam at every join,
    and where the pilot's fan meets the centre face the joining hood stood as a lit triangle between its neighbours'
    edges (build 15 in game: pale down-pointing triangles over the stores and engine displays)."""
    t = ctx["t"]
    hoods = sorted(hoods, key=lambda h: -(h[0].x + h[1].x))
    runs = []
    for h in hoods:
        if runs and (runs[-1][-1][1] - h[0]).length < 0.01:
            runs[-1].append(h)
        else:
            runs.append([h])
    z = hoods[0][0].z if hoods else 0.0
    frh = frame_of(Vector((0.0, 0.0, z)), Vector((1, 0, 0)), Vector((0, 1, 0)))
    HOOD_HALF[0] = max((abs(p.x) for h in hoods for p in h), default=0.0)
    for run in runs:
        front = [run[0][0]] + [h[1] for h in run]
        back = [run[0][3]] + [h[2] for h in run]
        poly = [(p.x, p.y) for p in front] + [(p.x, p.y) for p in reversed(back)]
        sp.plate(FM(ctx["acc"], frh), t, poly, -0.004, 0.0, 0.0015, "dark", offset=0.6)
        # no fasteners on it: their plated heads, at the screen's foot in the pilot's forward view, read as pale points.
        # No fascia along a cheek's hood: no module's top stands under its front, which runs back from the stack's
        # corner to the fan's, and the strip hung there crossed the plate's own chamfer in an X under the rail
        glare_fascia(ctx, front, back, z, [any(h is c_ for c_ in cheek_hoods) for h in run])
    print("GLARE HOODS", len(hoods), "hoods in", len(runs), "plates;", len(cheek_hoods), "over cheeks, without fascia")


FASCIA_DROP, FASCIA_PROUD, FASCIA_LIP = 0.012, 0.0015, 0.008  # further proud, its cap stands in the pilot's
# sightline to the centre display's top bezel


def glare_fascia(ctx, front, back, z, bare):
    """The glare shield's front: one strip FASCIA_DROP deep hung FASCIA_PROUD proud of the plate's whole front line
    (the modules' top edges), mitred where the line turns, capped over to the plate and rolled FASCIA_LIP back under
    its foot: the junction reads as one part over the stack, as the stock Darkreach's glare shield over its displays,
    and the modules' tops, joins and plate corners behind it never show their own edges. bare[i] leaves segment i
    (front[i] to front[i + 1]) to the plate's own edge."""
    def seg_n(k):  # segment k's normal in plan, away from the plate (toward the crew)
        t_ = front[k + 1] - front[k]
        n_ = Vector((-t_.y, t_.x, 0)).normalized()
        return n_ if n_.dot((front[k] + front[k + 1]) / 2 - (back[k] + back[k + 1]) / 2) > 0 else -n_

    def out(i):  # the crew's side of the front line at its point i, mitred between its segments
        ns = [seg_n(k) for k in (i - 1, i) if 0 <= k < len(front) - 1]
        m = sum(ns, Vector()).normalized()
        return m / max(0.5, m.dot(ns[0]))
    offs = [out(i) for i in range(len(front))]
    for i in range(len(front) - 1):
        if bare[i]:
            continue
        a_, b_ = front[i], front[i + 1]
        ao, bo_ = a_ + offs[i] * FASCIA_PROUD, b_ + offs[i + 1] * FASCIA_PROUD
        low = Vector((0, 0, -FASCIA_DROP))
        # its face from the plate's height down past the module's own top: a module whose top stands lower than the
        # plate (the pilot's flight display, its corner under the side pane's cap) left an open slot between the
        # plate's edge and the fascia, a dark notch at its shoulder beside the radar
        up_a, up_b = Vector((0, 0, max(0.0, z - a_.z))), Vector((0, 0, max(0.0, z - b_.z)))
        cap = [a_ + up_a, b_ + up_b, bo_ + up_b, ao + up_a]
        quads = [(cap, "dark", Vector((0, 0, 1)))]
        # the face and its lip in 1 cm pieces, each reaching FASCIA_DROP under the module's top but stopping 1 mm over
        # a display's bezel that stands above it (the pilot's flight display's, over its lowered module): hung to the
        # full drop, the face went through that bezel's top bar
        m_ = max(1, math.ceil((b_ - a_).length / 0.01))
        for k in range(m_):
            pa, pb = ao.lerp(bo_, k / m_), ao.lerp(bo_, (k + 1) / m_)
            ua, ub = up_a.lerp(up_b, k / m_), up_a.lerp(up_b, (k + 1) / m_)
            oa, ob = offs[i].lerp(offs[i + 1], k / m_), offs[i].lerp(offs[i + 1], (k + 1) / m_)
            la, lb = (fascia_foot(q_, q_ + u_) for q_, u_ in ((pa, ua), (pb, ub)))
            quads += [([pa + la, pb + lb, pb + ub, pa + ua], "dark", offs[i]),
                      ([pa + la, pb + lb, pb + lb - ob * FASCIA_LIP, pa + la - oa * FASCIA_LIP], "edge", Vector((0, 0, -1)))]
        for q, strip, want in quads:
            flip = (q[1] - q[0]).cross(q[3] - q[0]).dot(want) < 0
            if flip:
                q = [q[1], q[0], q[3], q[2]]
            banded(ctx, q, strip, 900)


BEZEL_TOPS = []  # each display bezel's top edge, its front face's two ends (world), for the fascia to stop over


def fascia_foot(p, top):
    """The fascia's foot under its point p (on the module's top line, `top` its upper end): FASCIA_DROP down, or 1 mm over
    a bezel whose top edge stands within 4 cm behind or in front of p and above that, as an offset from p."""
    foot = -FASCIA_DROP
    for l_, r_ in BEZEL_TOPS:
        d_ = r_ - l_
        f_ = (p - l_).dot(d_) / d_.length_squared
        q_ = l_ + d_ * f_
        if -0.01 <= f_ <= 1.01 and (Vector((q_.x - p.x, q_.y - p.y, 0))).length < 0.04:
            foot = max(foot, q_.z + 0.001 - p.z)
    return Vector((0, 0, min(foot, top.z - p.z - 0.002)))


def close_module_joins(ctx):
    """A dark strip 12 mm back in each joint between two display modules standing side by side (bo.GAP, 8 mm apart):
    across the cabin the pilot looked through the joint between the commander's flight display and stores modules,
    past the backing wall's end, and out of the right side pane (build 15 in game: a pair of sky slivers)."""
    n_j = 0
    quads = [[Vector(v) for v in q] for q in MODULE_QUADS]
    for ia, A in enumerate(quads):
        for B in quads[ia + 1:]:
            for (i, j) in ((0, 3), (1, 2)):
                for (k, l) in ((0, 3), (1, 2)):
                    if (A[i] - B[k]).length < 0.03 and (A[j] - B[l]).length < 0.03:
                        na = (A[1] - A[0]).cross(A[3] - A[0]).normalized()
                        nb = (B[1] - B[0]).cross(B[3] - B[0]).normalized()
                        fa = na if na.dot(bo.EYE[1] - A[0]) > 0 or na.dot(bo.EYE[-1] - A[0]) > 0 else -na
                        fb = nb if nb.dot(bo.EYE[1] - B[0]) > 0 or nb.dot(bo.EYE[-1] - B[0]) > 0 else -nb
                        q = [A[i] - fa * 0.012, B[k] - fb * 0.012, B[l] - fb * 0.012, A[j] - fa * 0.012]
                        if (q[1] - q[0]).cross(q[3] - q[0]).dot(fa + fb) < 0:
                            q = [q[1], q[0], q[3], q[2]]
                        banded(ctx, q, "dark", 900)
                        n_j += 1
    # and on the commander's side, behind each module edge no neighbour shares, a dark flange 3 cm out and 12 mm back:
    # across the cabin the pilot's eye passed between the commander's outboard module and the skirt's end, under the
    # skirt's foot (which the pilot's sightline to that display holds up), and out of the right side pane (build 15 and
    # 16 in game: a pair of sky slivers between his flight display and stores modules)
    n_f = 0
    for ia, A in enumerate(quads):
        if sum(A, Vector()).x / 4 > 0:
            continue
        na = (A[1] - A[0]).cross(A[3] - A[0]).normalized()
        fa = na if na.dot(bo.EYE[1] - A[0]) > 0 else -na
        c = sum(A, Vector()) / 4
        for (i, j) in ((0, 3), (1, 2)):
            if any((A[i] - B[k]).length < 0.03 and (A[j] - B[l]).length < 0.03
                   for ib, B in enumerate(quads) if ib != ia for (k, l) in ((0, 3), (1, 2))):
                continue
            mid = (A[i] + A[j]) / 2
            out = (mid - c) - fa * (mid - c).dot(fa)
            out = (out - (A[j] - A[i]).normalized() * out.dot((A[j] - A[i]).normalized())).normalized()
            q = [A[i] - fa * 0.012, A[j] - fa * 0.012, A[j] - fa * 0.012 + out * 0.03, A[i] - fa * 0.012 + out * 0.03]
            if (q[1] - q[0]).cross(q[3] - q[0]).dot(fa) < 0:
                q = [q[1], q[0], q[3], q[2]]
            banded(ctx, q, "dark", 900)
            n_f += 1
    print("MODULE JOINS", n_j, "closed;", n_f, "flanges behind the commander's open module edges")


def corner_cheeks(ctx, radius, half, foot):
    """The forward corners closed: a dark cheek on each side, on the camera screen's own cylinder
    (so nothing stands behind the screen), from the skirt's end out into the side wall and from the modules' tops up
    into the coaming. Lining and backs forward of the screen cannot close them: the screen shows through to them
    (flightdeck_cut.py takes them away). Columns 2 cm along the arc; each column's foot by the skirt's rule (stopping where it
    would stand in front of a display), its top 4 mm into 0.1.3's coaming, the last column 5 mm into the wall."""
    import flightdeck_screen as band_shape
    src = O["flightdeck_int"]  # 0.1.3's flight deck: its side wall and coaming
    wall = BVHTree.FromPolygons([src.matrix_world @ v.co for v in src.data.vertices], [tuple(p.vertices) for p in src.data.polygons])

    def inside(s, z):  # the wall's inner face lies outboard of the cylinder's point
        p = band_shape.new_point(s, 0.005, z, radius)
        sgn = 1.0 if s > 0 else -1.0
        h = wall.ray_cast(p, Vector((sgn, 0, 0)), 0.8)
        return h[0] is not None and h[1].x * sgn < 0

    def roof(s):  # into the coaming over it; on the pilot's side no higher than the bezel's top, where his windscreen's
        # corner glass begins. On the commander's side (only the pilot's view counts) up into the coaming: capped, it
        # left a slit between its top and the coaming over the screen's right end, out to the right side pane
        p = band_shape.new_point(s, 0.005, 4.95, radius)
        h = wall.ray_cast(p, Vector((0, 0, 1)), 0.3)
        if h[0] is None:
            return 4.985
        return min(h[0].z + 0.004, 4.985) if s > 0 else h[0].z + 0.004
    # the side panes (the nose's glass turned sideways): a cheek's top no higher than where, from either seat, it would
    # stand across one (from across the cabin a cheek to the coaming cut a diagonal out of the far side window's
    # forward edge)
    nose = O["nose"]
    nw = nose.matrix_world
    side = [p_ for p_ in nose.data.polygons if nose.material_slots[p_.material_index].material
            and nose.material_slots[p_.material_index].material.name == "glass" and abs((nw.to_3x3() @ p_.normal).normalized().x) > 0.5]
    panes = BVHTree.FromPolygons([nw @ v.co for v in nose.data.vertices], [tuple(p_.vertices) for p_ in side])
    # the inner panes the game draws (the nose is hidden in cockpit view), and the wall, for what lies behind a column
    gi = O["glass_int"]
    gw = gi.matrix_world
    drawn = BVHTree.FromPolygons([gw @ v.co for v in gi.data.vertices], [tuple(p_.vertices) for p_ in gi.data.polygons])

    # the pilot's eye: a column's foot rises to the side pane's top wherever he sees the pane behind it, so the side
    # pane's forward part stays open to the display stack (the owner wants that window; window_bezels frames it). With
    # the head box from both seats the feet stayed down and walled it off (builds 13 and 15). The side openings are
    # pinned in flightdeck_sightlines (PANE_OPENINGS).
    heads = [bo.EYE[1]]
    import flightdeck_window as win

    def glazed_behind(s, z):  # from every one of those heads, a drawn pane is the first thing past the column's point
        p = band_shape.new_point(s, 0.005, z, radius)
        for e in heads:
            d = (p - e).normalized()
            g, w = drawn.ray_cast(p + d * 0.002, d, 3.0), wall.ray_cast(p + d * 0.002, d, 3.0)
            if g[0] is None or (w[0] is not None and w[3] < g[3]):
                return False
            # and only over glass inside the side window's frame: past its outline the cheek stays down, lapping the
            # frame, so no glass shows between them (build 16 in game: a triangle of sky between the frame's forward
            # jamb, the cheek and the sill's top corner, where the pane ran on past the frame)
            if not win.cheek_may_open(g[0].y - bo.st(0.0), g[0].z):
                return False
        return True

    def across_pane(s, z):
        p = band_shape.new_point(s, 0.005, z, radius)
        d = (p - bo.EYE[1]).normalized()
        if panes.ray_cast(p, d, 3.0)[0] is None:
            return False
        g = drawn.ray_cast(p + d * 0.002, d, 3.0)  # and only over glass inside the side window's frame
        return g[0] is not None and win.cheek_may_open(g[0].y - bo.st(0.0), g[0].z)
    ax = Vector((0.0, bo.st(band_shape.axis_station(radius)), 4.75))
    n_q = 0
    for sgn in (1, -1):
        cols = []
        s = half - 0.03  # 3 cm in behind the skirt's end: from the pilot's eye across the cabin a slit showed out of the
        # right pane between the commander's outboard module and the cheek's first column, under the skirt's foot
        while s < half + 0.5:
            zt, zb = roof(sgn * s), foot(sgn * s, 4.95, 4.55)
            while zt > zb and (not inside(sgn * s, zt - 0.004) or across_pane(sgn * s, zt)):
                zt -= 0.005
            if zt <= zb:  # past the wall at every height: back to where it starts, 5 mm in
                lo, hi = cols[-1][0] if cols else half, s
                for _ in range(12):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if inside(sgn * mid, (zb + cols[-1][2]) / 2 if cols else 4.8) else (lo, mid)
                if cols:
                    cols.append((hi + 0.005, cols[-1][1], cols[-1][2]))
                break
            # its foot no lower than a drawn side pane's top: under it the column stood in the side window's opening,
            # across the pane's forward edge, from both seats (where only the hidden nose glass lies behind, the column
            # is all that closes the opening)
            zf = zt
            while zf - 0.005 > zb and not glazed_behind(sgn * s, zf - 0.005):
                zf -= 0.005
            cols.append((s, zb if zf - 0.005 <= zb else zf, zt))
            s += 0.02
        for (s0, b0, t0), (s1, b1, t1) in zip(cols, cols[1:]):
            off = 0.007 if s0 < half else 0.005  # where it laps the skirt, 2 mm behind it
            q = [band_shape.new_point(sgn * s0, off, b0, radius), band_shape.new_point(sgn * s1, off, b1, radius),
                 band_shape.new_point(sgn * s1, off, t1, radius), band_shape.new_point(sgn * s0, off, t0, radius)]
            flip = (q[1] - q[0]).cross(q[3] - q[0]).dot(ax - (q[0] + q[2]) / 2) < 0
            if flip:  # wound to face the crew
                q = [q[1], q[0], q[3], q[2]]
            # the dark finish, its grain run on from column to column (each column started the strip afresh and the
            # cheek read as a repeat of 2 cm patches in game); in the frame's light finish, lit by the sun, its cut
            # edge ended abruptly in a pale point across each pane's forward corner
            banded(ctx, q, "dark", 900, run0=-s1 if flip else s0)
            # its top returned 17 mm toward the cabin, a lip facing down, dark as the face (a worn light lip drew the
            # same pale edge)
            lip = [band_shape.new_point(sgn * s0, 0.005, t0, radius), band_shape.new_point(sgn * s1, 0.005, t1, radius),
                   band_shape.new_point(sgn * s1, -0.012, t1, radius), band_shape.new_point(sgn * s0, -0.012, t0, radius)]
            flip = (lip[1] - lip[0]).cross(lip[3] - lip[0]).z > 0
            if flip:
                lip = [lip[1], lip[0], lip[3], lip[2]]
            banded(ctx, lip, "dark", 900, run0=-s1 if flip else s0)
            n_q += 1
        if len(cols) > 3:  # a panel break across its middle: a 4 mm dark seam, 2 mm proud
            sm, bm_, tm = cols[len(cols) // 2]
            q = [band_shape.new_point(sgn * (sm - 0.002), 0.003, bm_, radius), band_shape.new_point(sgn * (sm + 0.002), 0.003, bm_, radius),
                 band_shape.new_point(sgn * (sm + 0.002), 0.003, tm, radius), band_shape.new_point(sgn * (sm - 0.002), 0.003, tm, radius)]
            if (q[1] - q[0]).cross(q[3] - q[0]).dot(ax - (q[0] + q[2]) / 2) < 0:
                q = [q[1], q[0], q[3], q[2]]
            banded(ctx, q, "dark", 900)
    print("CORNER CHEEKS", n_q, "columns, both sides")


def panel_backing(ctx):
    """A dark wall at station 5.375, just forward of every module, from the console tops to the coaming: the modules
    are front plates on a panel whose body today's mesh no longer has, so the wedges between neighbours that lean
    differently, and the gaps under the band, looked into the nose (hidden in cockpit view) and out (flightdeck_sightlines.py on
    the first export, both seats). Outboard of 1.0 m it stops at z 4.62, under the side panes' foot."""
    # Its top at 4.70, under every sightline through the camera band from both seats (the band's foot at 4.80, 0.85 m
    # ahead of the pilot's eye, falls to 4.72 here; from the commander's to 4.77): up to 4.95, the wall stood behind
    # the whole band, which shows the world through the hidden nose, and blanked it (0 of 369 rays
    # through the band reached the outside, against 356 in 0.1.3).
    # and the band's foot carried down: a dark skirt on the band's own cylinder, 5 mm behind the sheet, from the
    # band's foot (z 4.80) to the hoods' height, a little longer than the band and its bezel: between the hoods and
    # the band a head lowered to the band's foot looked level through a slot to the outside
    import flightdeck_screen as band_shape
    radius = bo.BAND_RADIUS or band_shape.R0
    half = band_shape.ARC0 / 2 * (band_shape.K if bo.BAND_RADIUS else 1.0) + 0.03
    n = 96  # 2 cm segments, so the foot follows the modules' tops
    acc = ctx["acc"]
    vs_, ps_ = [], []
    for pts, _, _ in acc.faces:
        ps_.append(list(range(len(vs_), len(vs_) + len(pts))))
        vs_ += pts
    built = BVHTree.FromPolygons(vs_, ps_)

    def foot(s, z_top=4.80, z_low=4.70, reach=0.15):  # down to z_low, stopping where a seat's eye would see the skirt in
        # front of something within `reach` (on the flatter cylinder it crosses the outer modules, and a fixed foot ran
        # through their displays). A foot set on whatever lay under it rested on the thin sheets forward of the hoods, with open air
        # below, and a head low and forward looked up under them and out.
        z = z_top
        while z > z_low:
            p = band_shape.new_point(s, 0.005, z - 0.003, radius)
            for e in (bo.EYE[1],):  # the pilot's eye: only the player's view counts
                d = (p - e).normalized()
                seen = built.ray_cast(e, d, (p - e).length - 0.002)[0] is None
                h = built.ray_cast(p + d * 0.001, d, reach)
                if seen and h[0] is not None and h[1].dot(d) < 0 and abs(h[1].z) < 0.7 and h[1].y > 0.3:
                    # a face turned to the crew (a module's frame, over its display), not a top sheet or a side: the
                    # skirt stops 2 mm over it (lapping 6 mm, on the flatter screen it stood across the tops of the
                    # commander's radar and flight display as a black sawtooth)
                    return z + 0.002
            z -= 0.003
        return z_low
    # a floor for the skirt from the displays' bezels: every sightline from the pilot's eye to a point 15 mm outside a
    # display's page crosses the skirt's cylinder somewhere, and the skirt stays 3 mm over each crossing, so it never
    # stands across a bezel (on the 4.5 m cylinder it passes in front of the commander's flight display top: flightdeck_sightlines.py's bezel sightlines)
    ax_y = bo.st(band_shape.axis_station(radius))
    rr = radius + 0.005
    floor_pts = []
    for _, quad in SCREENS.values():
        qv = [Vector(v) for v in quad]
        c_ = sum(qv, Vector()) / 4
        for k in range(4):
            a_, b_ = qv[k], qv[(k + 1) % 4]
            for j in range(12):
                q_ = a_.lerp(b_, (j + 0.5) / 12)
                q_ = q_ + (q_ - c_).normalized() * 0.015
                for e in (bo.EYE[1],):
                    d_ = q_ - e
                    px, py, dx, dy = e.x, e.y - ax_y, d_.x, d_.y
                    A, B, C = dx * dx + dy * dy, 2 * (px * dx + py * dy), px * px + py * py - rr * rr
                    disc = B * B - 4 * A * C
                    if A < 1e-12 or disc < 0:
                        continue
                    for t_ in ((-B - math.sqrt(disc)) / (2 * A), (-B + math.sqrt(disc)) / (2 * A)):
                        if 0.0 < t_ < 1.0:
                            P = e + d_ * t_
                            if P.y < ax_y:  # the forward side of the cylinder
                                floor_pts.append((radius * math.atan2(P.x, ax_y - P.y), P.z))

    def bezel_floor(s_):
        zs = [z_ for s1_, z_ in floor_pts if abs(s1_ - s_) < 0.012]
        return max(zs) + 0.003 if zs else 0.0
    corner_cheeks(ctx, radius, half, lambda s_, *a: max(foot(s_, *a), bezel_floor(s_)))
    # down to 4.55 (was 4.70, over the backing wall): the screen now shows through to where the wall stood, which
    # flightdeck_cut.py takes away, and a head lowered looked under the screen's foot and out
    # (stopping only on a frame within 3 cm: at 15 cm the panel backs behind the centre stack held it at 4.71, and a
    # head low and forward looked level between the centre displays and out)
    # each end of a 2 cm column at the highest foot within 1 cm of it, so it never dips over a frame between samples
    ss = [-half + 2 * half * k / n for k in range(n + 1)]
    def module_floor(s_):
        """The top of a display module under the plate behind the displays here, 2 mm up: a module leaning back under
        the screen's foot (the pilot's flight display) had that plate hang 1 mm in front of its face, a dark V with a
        flickering pale blade under the lamp housing."""
        p_ = band_shape.new_point(s_, 0.012, 4.70, radius)
        best = 0.0
        for q_ in MODULE_QUADS:
            a_, b_ = Vector(q_[3]), Vector(q_[2])  # the module's top edge
            d_ = b_ - a_
            f_ = Vector((p_.x - a_.x, p_.y - a_.y, 0)).dot(Vector((d_.x, d_.y, 0))) / max(1e-9, Vector((d_.x, d_.y, 0)).length_squared)
            if -0.02 <= f_ <= 1.02:
                e_ = a_ + d_ * min(1.0, max(0.0, f_))
                if Vector((e_.x - p_.x, e_.y - p_.y, 0)).length < 0.06:
                    best = max(best, e_.z + 0.002)
        return best

    def face_seat(s_):
        """Past the glare hoods' ends, where the plate behind the displays meets a module's face (within 6 mm of its
        plane, or through it, in the 6 cm under its top edge, between its ends): the plate's foot on that module's top
        edge, 1 mm behind the face; or None. Raised there as over the hoods, it opened see-through slits past the
        commander's flight display's outboard end and over the pilot's (flightdeck_sightlines.py TOPS)."""
        p_ = band_shape.new_point(s_, 0.012, 4.70, radius)
        best = None
        for q_ in MODULE_QUADS:
            v_ = [Vector(c_) for c_ in q_]
            a_, b_ = v_[3], v_[2]  # the module's top edge
            d_ = b_ - a_
            f_ = Vector((p_.x - a_.x, p_.y - a_.y, 0)).dot(Vector((d_.x, d_.y, 0))) / max(1e-9, Vector((d_.x, d_.y, 0)).length_squared)
            if 0.0 <= f_ <= 1.0:
                e_ = a_ + d_ * f_
                n_ = (v_[1] - v_[0]).cross(v_[3] - v_[0]).normalized()
                g_ = [(band_shape.new_point(s_, 0.012, z_, radius) - e_).dot(n_) for z_ in (e_.z, e_.z - 0.06)]
                if (g_[0] * g_[1] <= 0 or min(abs(g_[0]), abs(g_[1])) < 0.006) and (best is None or e_.z > best.z):
                    best = e_ - n_ * (0.001 if n_.dot(bo.EYE[1] - e_) > 0 else -0.001)
        return best

    def seat_ends(s0_, s1_):
        """Where between s0_ and s1_ face_seat turns on or off, to 0.1 mm."""
        k_ = 4
        ss_ = [s0_ + (s1_ - s0_) * j_ / k_ for j_ in range(k_ + 1)]
        on_ = [face_seat(s_) is not None for s_ in ss_]
        ends_ = []
        for j_ in range(k_):
            if on_[j_] != on_[j_ + 1]:
                a_, b_ = ss_[j_], ss_[j_ + 1]
                while b_ - a_ > 0.0001:
                    m_ = (a_ + b_) / 2
                    a_, b_ = (m_, b_) if (face_seat(m_) is not None) == on_[j_] else (a_, m_)
                ends_.append((a_ + b_) / 2)
        return ends_
    feet = [min(4.80, max([foot(s_ + d_, 4.80, 4.55, 0.03) for d_ in (-0.01, -0.005, 0.0, 0.005, 0.01)] + [bezel_floor(s_)]))
            for s_ in ss]
    # under the glare plate's height the skirt is seen only through the wedge between two modules set at different
    # angles (Stores and Engine 1), where in game the sun lit the frame's light finish to pale triangles: that part is
    # in the dark finish. None over the centre stack (inboard of 0.35 m): there the plate behind the displays and the
    # stack's modules close every sightline under the plate (flightdeck_sightlines.py, unchanged with none to 0.6 m),
    # and where the stack's turned face stands its corner forward of the screen's foot this part's foot, stepping
    # between 4.55 and 4.77 every 2 cm, hung in front of that face as dark teeth over the engine display
    # (the near-black without the dark strip's panel joints: cut to a centimetre over a hood, its Dzus heads and seams
    # floated over the pilot's flight display as loose bits; mapped at 337.5 px/m so its 24 px strip bands the faces
    # 6.5 cm tall, as the dark strip's 64 px did at 900)
    z_plate = bo.Z_TOP - 0.003
    for k in range(n):
        s0, s1, f0, f1 = ss[k], ss[k + 1], feet[k], feet[k + 1]
        # a column held over 5 cm higher at one end only by a frame within a centimetre past it (at both its own ends the
        # foot reaches the floor) stands at that height rather than sloping across: past the pilot's flight display the
        # slope from its frame's height to the open gap beside it stood over the display's top outboard corner as a
        # dark tab
        if abs(f0 - f1) > 0.05 and all(foot(s_, 4.80, 4.55, 0.03) <= 4.55 for s_ in (s0, s1)):
            f0 = f1 = max(f0, f1)
        ax = Vector((0.0, bo.st(band_shape.axis_station(radius)), 4.75))
        for lo0, lo1, hi, strip in ((min(f0, z_plate), min(f1, z_plate), z_plate, "side"),
                                    (max(f0, z_plate), max(f1, z_plate), 4.80, "struct")):
            if min(lo0, lo1) >= hi or (strip == "side" and abs(band_shape.new_point((s0 + s1) / 2, 0.005, hi, radius).x) < 0.35):
                continue
            q = [band_shape.new_point(s0, 0.005, lo0, radius), band_shape.new_point(s1, 0.005, lo1, radius),
                 band_shape.new_point(s1, 0.005, hi, radius), band_shape.new_point(s0, 0.005, hi, radius)]
            flip = (q[1] - q[0]).cross(q[3] - q[0]).dot(ax - (q[0] + q[2]) / 2) < 0
            if flip:  # wound to face the crew, inside the cylinder
                q = [q[1], q[0], q[3], q[2]]
            banded(ctx, q, strip, 337.5 if strip == "side" else 900, run0=-s1 if flip else s0)  # above the plate the frame's finish, as the cheeks
    # behind the displays, 12 mm forward of the screen's cylinder and under its foot, the screen's whole width: the
    # gaps between the centre stack's pages showed sky or runway behind, and so did the slits between the skirt's foot
    # and the housings' tops, as light seams over the commander's displays
    n_back = int(round(2 * half / 0.02))
    cones = [(e_, c_, (c_ - e_).length, cone_planes(e_, q_, c_)) for e_, q_, c_ in CONES]

    def in_a_cone(p_):  # in_cone's test on the cone pulled 12 mm in: about 16 mm round the page, past its bezel's edge
        return any((p_ - e_).dot(c_ - e_) > 0 and (p_ - e_).length <= L_ + 0.05 and all((p_ - e_).dot(n_) > 0.012 for n_ in pl)
                   for e_, c_, L_, pl in cones)
    zs = []
    for k in range(n_back):
        s0, s1 = -half + 2 * half * k / n_back, -half + 2 * half * (k + 1) / n_back
        # its foot above the displays' sight cones: the commander's flight display leans forward past the cylinder,
        # and the plate stood across its top bezel
        z0 = 4.795
        while z0 > 4.45 and not any(in_a_cone(band_shape.new_point(s_, 0.012, z0 - 0.004, radius)) for s_ in (s0, (s0 + s1) / 2, s1)):
            z0 -= 0.004
        zs.append(z0)
    # over the glare hoods (to 3 cm past their ends) the plate stands raised over the modules: hung low it went through
    # the hoods. So it does past their end on the pilot's side, over his lowered flight display, whose bezel bar stands
    # over the module's top edge (set on that edge the plate went through the bar). Past their end on the commander's
    # side it keeps its full depth but where it meets a module's face (face_seat).
    in_hoods = [band_shape.new_point(-half + 2 * half * (k + 0.5) / n_back, 0.012, 4.70, radius).x >= -HOOD_HALF[0] - 0.03
                for k in range(n_back)]
    zr = [min(4.795, max([z0] + [module_floor(s_) for s_ in (-half + 2 * half * (k + f_) / n_back for f_ in (0, 0.5, 1))]))
          if in_hoods[k] else z0 for k, z0 in enumerate(zs)]
    # where the plate stands raised, a backstop 8 cm further forward (past the hoods' forward edge) from 4.5 cm under the
    # raised foot (or the plate's own height over the sight cones) up to it (under 4.78, clear of the sightlines through
    # the screen), 5 columns either side: raised alone, the plate opened see-through slits over the module tops to the
    # windows (flightdeck_sightlines.py TOPS)
    near = [range(max(0, k - 5), min(n_back, k + 6)) for k in range(n_back)]
    raised = [any(zr[j] > zs[j] + 0.001 for j in near[k]) for k in range(n_back)]
    stop = [min(4.78, max(zr[j] for j in near[k])) for k in range(n_back)]
    zb_low = [max(zs[k], stop[k] - 0.045) for k in range(n_back)]
    ax = Vector((0.0, bo.st(band_shape.axis_station(radius)), 4.6))

    def back_quad(q, sa, sb, strip="dark"):
        flip = (q[1] - q[0]).cross(q[3] - q[0]).dot(ax - (q[0] + q[2]) / 2) < 0
        if flip:
            q = [q[1], q[0], q[3], q[2]]
        banded(ctx, q, strip, 900, run0=-sb if flip else sa)
    for d_, low, hi in ((0.012, zr, None), (0.080, zb_low, stop)):
        for k in range(n_back):
            if hi is not None and not raised[k]:
                continue
            s0, s1 = -half + 2 * half * k / n_back, -half + 2 * half * (k + 1) / n_back
            # each edge at the higher of the two columns it joins: one continuous foot line, never below either column's
            # cone limit (flat per column it stepped 4 mm every 2 cm, a dark point over the pilot's flight display in game)
            za = max(low[k], low[k - 1]) if k > 0 else low[k]
            zb = max(low[k], low[k + 1]) if k + 1 < n_back else low[k]
            top = 4.795 if hi is None else hi[k]
            if low[k] > top - 0.005:
                continue
            if hi is None and in_hoods[k]:
                back_quad([band_shape.new_point(s0, d_, za, radius), band_shape.new_point(s1, d_, zb, radius),
                           band_shape.new_point(s1, d_, top, radius), band_shape.new_point(s0, d_, top, radius)], s0, s1)
                continue
            if hi is not None:
                # in 5 mm by half-height pieces, leaving out any that would go through a part already built (a centre
                # module's side)
                for i_ in range(4):
                    sa, sb = s0 + (s1 - s0) * i_ / 4, s0 + (s1 - s0) * (i_ + 1) / 4
                    fa, fb = za + (zb - za) * i_ / 4, za + (zb - za) * (i_ + 1) / 4
                    for ua, ub in ((0.0, 0.5), (0.5, 1.0)):
                        q = [band_shape.new_point(sa, d_, fa + (top - fa) * ua, radius), band_shape.new_point(sb, d_, fb + (top - fb) * ua, radius),
                             band_shape.new_point(sb, d_, fb + (top - fb) * ub, radius), band_shape.new_point(sa, d_, fa + (top - fa) * ub, radius)]
                        if not built.overlap(BVHTree.FromPolygons(q, [[0, 1, 2, 3]])):
                            back_quad(q, sa, sb)
                continue
            cuts = [s0] + [c_ + h_ for c_ in seat_ends(s0, s1) for h_ in (-0.00005, 0.00005)] + [s1]

            def foot_at(s_, z_):
                m_ = face_seat(s_)
                if m_ is not None and z_ < m_.z < 4.795:
                    return m_
                return band_shape.new_point(s_, 0.012, min(4.795, max(z_, m_.z if m_ is not None else 0.0)), radius)
            for sa, sb in zip(cuts, cuts[1:]):
                pa = foot_at(sa, za + (zb - za) * (sa - s0) / (s1 - s0))
                pb = foot_at(sb, za + (zb - za) * (sb - s0) / (s1 - s0))
                if min(pa.z, pb.z) > 4.79:
                    continue
                back_quad([pa, pb, band_shape.new_point(sb, 0.012, 4.795, radius), band_shape.new_point(sa, 0.012, 4.795, radius)], sa, sb)
    y = bo.st(5.375)
    for x0, x1, z1 in ((1.0, -1.0, 4.70), (1.22, 1.0, 4.62), (-1.0, -1.22, 4.62)):
        # wound to face aft, toward the crew
        banded(ctx, (Vector((x0, y, 4.36)), Vector((x1, y, 4.36)), Vector((x1, y, z1)), Vector((x0, y, z1))), "dark", 900)


def module(ctx, q, n, displays):
    """One display module face, finished: plate, side frames, the display's bezel with keys, its switch strip; or,
    for a face with no display (the pilot's outboard filler), the gear panel."""
    t = ctx["t"]
    eye = bo.EYE[1] if (q[0] - bo.EYE[1]).length < (q[0] - bo.EYE[-1]).length else bo.EYE[-1]
    fr = face_frame(q, eye)
    inv = fr.inverted()
    loc = [inv @ p for p in q]
    fm = FM(ctx["acc"], fr)
    hf = max(p.y for p in loc)
    # the displays on this face
    mine = []
    for name, page, quad, _ in displays:
        c = inv @ (sum((Vector(p) for p in quad), Vector()) / 4)
        if abs(c.z) < 0.03 and min(p.x for p in loc) < c.x < max(p.x for p in loc) and 0 < c.y < hf:
            mine.append((name, page, [inv @ Vector(p) for p in quad]))
    # out of the centre stack's sight cones (pages turned to the pilot): the pilot's stores module's inboard edge stood
    # over the stack's page beside it, across its bezel. Not the other modules' cones: neighbours cut back from each
    # other's left a gap to the outside between them
    own = [fr @ (sum(quad_, Vector()) / 4) for _, _, quad_ in mine]
    stack = [c_ for c_ in CONES if abs(c_[2].x) < 0.35 and all((c_[2] - o_).length >= 0.01 for o_ in own)]
    plate_poly = [(p.x, p.y) for p in (inv @ v for v in clip_out_of_cones([fr @ Vector((p.x, p.y, 0.007)) for p in loc], cones=stack))]
    side_seat = 1 if eye is bo.EYE[1] else -1
    GROUP_AXES.setdefault((mine[0][0] if mine else "gear_panel"), None)
    GROUP_AXES[(mine[0][0] if mine else "gear_panel")] = GROUP_AXES[(mine[0][0] if mine else "gear_panel")] or (fr.to_3x3().col[2].normalized(), fr.to_3x3().col[1].normalized())
    GROUPS.append(((mine[0][0] if mine else "gear_panel"), fr @ Vector(((min(p.x for p in loc) + max(p.x for p in loc)) / 2, hf / 2, 0.01)),
                   max(max(p.x for p in loc) - min(p.x for p in loc), hf) * 1.05, side_seat))
    sp.plate(fm, t, plate_poly, 0.0, 0.007, 0.0016, "field", offset=0.37)
    PANELS.append(("module", fr @ Vector((0, hf / 2, 0.007))))
    # side frames, proud, fastened
    rail = 0.020
    lx = sorted(loc, key=lambda p: p.x)
    for side in (0, 1):
        b0, t0_ = (loc[0], loc[3]) if loc[0].x < loc[1].x else (loc[1], loc[2])
        if side:
            b0, t0_ = (loc[1], loc[2]) if loc[0].x < loc[1].x else (loc[0], loc[3])
        s = 1 if side == 0 else -1
        bw, tw_ = fr @ Vector((b0.x, b0.y, 0)), fr @ Vector((t0_.x, t0_.y, 0))
        if any(q_ is not q and any(((bw - Vector(q_[i])).length < 0.02 and (tw_ - Vector(q_[j])).length < 0.02)
                                   for i, j in ((0, 3), (1, 2), (3, 0), (2, 1))) for q_ in MODULE_QUADS):
            continue  # an edge shared with the next module: no rail there, so the two bezels' keys keep their gap
        poly = [(b0.x, b0.y), (b0.x + s * rail, b0.y), (t0_.x + s * rail, t0_.y), (t0_.x, t0_.y)]
        if any(in_cone(p_, *c_) for p_ in poly_samples([fr @ Vector((px_, py_, 0.010)) for px_, py_ in poly]) for c_ in CONES):
            continue  # it would stand in a display's sightline from its seat: left off
        if s < 0:
            poly = [poly[1], poly[0], poly[3], poly[2]]
        sp.plate(fm, t, poly, 0.0, 0.010, 0.002, "dark", 2200, offset=0.5 + side)
        for f in (0.08, 0.35, 0.62, 0.9):
            fastener(ctx, fr, b0.x + s * rail / 2 + (t0_.x - b0.x) * f, hf * f, 0.010)
    # a module standing over a console closes its foot down to the console top: left open, its side rails' ends stood
    # over the console's front panels as loose dark slivers
    a_, b_ = (fr @ Vector((p.x, p.y, 0.010)) for p in loc[:2])
    if min(abs(a_.x), abs(b_.x)) > 0.86 and min(a_.z, b_.z) > 4.36:
        wm = FM(ctx["acc"], Matrix.Identity(4))
        a0, b0_ = (fr @ Vector((p.x, p.y, 0.0)) for p in loc[:2])
        down = [Vector((v.x, v.y, 4.356)) for v in (a_, b_, b0_, a0)]
        span = (b_ - a_).length
        for pts in ([a_, b_, down[1], down[0]], [a0, a_, down[0], down[3]], [b_, b0_, down[2], down[1]]):
            uvs = [t.strip("dark", 0, 1), t.strip("dark", span, 1), t.strip("dark", span, 0), t.strip("dark", 0, 0)]
            wm.face(pts, uvs)
            # and its other side: wound one way only, the foot faced away from one seat or the other and the game
            # drew only its edges, as slivers from the bezel to the console
            wm.face(pts[::-1], uvs[::-1])
    if any(pg == "engines" for _, pg, _ in mine):
        CAUTION.append((fr, loc, rail, mine))  # built once every module stands, so it can start where the pilot sees
    if not mine:
        # the gear panel: three green lamps, the handle
        w = max(p.x for p in loc) - min(p.x for p in loc) - 2 * rail
        x0 = min(p.x for p in loc) + rail
        sub = fr @ Matrix.Translation((x0 + 0.004, 0.02, 0.007))
        wp, hp = w - 0.008, hf - 0.05
        panel(ctx, sub, wp, hp, "GEAR", [], centre_title=True)
        sm = FM(ctx["acc"], sub)
        zp = 0.003
        if side_seat < 0:  # the commander's: the three gear lights repeated, no lever
            for k, word in enumerate(("NOSE", "LEFT", "RIGHT")):
                lx, ly = wp * (0.2 + 0.3 * k), hp * 0.42
                sp.cap(sm, t, (lx, ly), 0.0065, zp, zp + 0.004, 16, t.hw["lens_green"], "bezel")
                CONTROLS.append(("lamp", sub @ Vector((lx, ly, zp))))
                placard(ctx, sub, lx, ly - 0.014, zp + 0.0002, word, 0.0065)
            return
        # top: the three gear-down lights, each labelled under it
        for k, word in enumerate(("NOSE", "LEFT", "RIGHT")):
            lx, ly = wp * (0.2 + 0.3 * k), hp - 0.034
            sp.cap(sm, t, (lx, ly), 0.0065, zp, zp + 0.004, 16, t.hw["lens_green"], "bezel")
            CONTROLS.append(("lamp", sub @ Vector((lx, ly, zp))))
            placard(ctx, sub, lx, ly - 0.014, zp + 0.0002, word, 0.0065)
        # middle: the gear lever in its gated slot, UP at the slot's head and DOWN at its foot, set down
        gx, g0, g1 = wp * 0.36, 0.072, hp - 0.068
        gc = card_at(sub, gx, (g0 + g1) / 2, zp)
        gc[0]["items"].append(["slot", gx - 0.005, g0, gx + 0.005, g1])
        placard(ctx, sub, gx + 0.026, g1 - 0.004, zp + 0.0002, "UP", 0.0085)
        placard(ctx, sub, gx + 0.026, g0 + 0.004, zp + 0.0002, "DOWN", 0.0085)
        ky = g0 + 0.010
        held = lever_begin(ctx)  # the handle slides its slot from DOWN (its rest) to UP
        solid(FM(ctx["acc"], sub), t, [(gx - 0.0025, ky - 0.0025, zp), (gx + 0.0025, ky - 0.0025, zp), (gx + 0.0025, ky + 0.0025, zp), (gx - 0.0025, ky + 0.0025, zp),
                      (gx - 0.0025, ky - 0.0025, 0.030), (gx + 0.0025, ky - 0.0025, 0.030), (gx + 0.0025, ky + 0.0025, 0.030), (gx - 0.0025, ky + 0.0025, 0.030)],
              "keyedge")  # the lever's shaft, out of its slot
        cylinder(FM(ctx["acc"], sub), t, (gx, ky, 0.040), "x", 0.011, 0.008, 28, "white")  # the wheel, its axle across
        lever_end(ctx, held, "lever_gear", sub @ Vector((gx, ky, zp)), sub @ Vector((gx, g1 - 0.010, zp)),
                  (sub, gx - 0.005, gx + 0.005, g0, g1, zp))
        CONTROLS.append(("handle", sub @ Vector((gx, ky, 0.03))))
        # foot: the alternate release, a pull handle in a yellow and black frame, its label beside it
        ax, ay, hf_ = wp * 0.30, 0.034, 0.013
        gc[0]["items"].append(["hazard", ax - hf_, ay - hf_, ax + hf_, ay + hf_, 0.003])
        place(ctx["coll"], "pull_red", sub, (ax, ay, zp), scale=0.75)
        CONTROLS.append(("pull", sub @ Vector((ax, ay, zp))))
        placard(ctx, sub, ax + hf_ + 0.024, ay, zp + 0.0002, "ALT GEAR", 0.0075)
        return
    for name, page, dq in mine:
        # the screen in this module's own frame, 3 mm proud of its plate and 4 mm under the bezel's face: the
        # blockout's quads come from a face that is not quite planar on the centre stack
        xs, ys = [p.x for p in dq], [p.y for p in dq]
        dx0, dx1, dy0, dy1 = min(xs), max(xs), min(ys), max(ys)
        mx_, my_ = (dx0 + dx1) / 2, (dy0 + dy1) / 2
        # the screen is the bezel's rectangle (the blockout's quad leans a few mm off square, which showed the plate
        # as a grey wedge inside the bezel)
        # (2.5 mm inside the bezel's opening, so the page's edge never sits under the bezel's lip from the eye)
        SCREENS[name] = (page, [fr @ Vector((dx0 + 0.0025 if p.x < mx_ else dx1 - 0.0025, dy0 + 0.0025 if p.y < my_ else dy1 - 0.0025, 0.010)) for p in dq])
        # a plain frame round the screen, as the stock aircraft's (the Darkreach's and the Medusa's displays carry no keys
        # round them: their soft keys are drawn on the screen, their push keys stand apart); the bottom band keeps the
        # display's name and its knob
        bx, bt, bb = 0.012, 0.012, 0.026
        BEZEL_TOPS.append((fr @ Vector((dx0 - bx, dy1 + bt, 0.012)), fr @ Vector((dx1 + bx, dy1 + bt, 0.012))))
        ox0, ox1, oy0, oy1 = dx0 - bx, dx1 + bx, dy0 - bb, dy1 + bt
        zb, zf = 0.007, 0.012  # 7 mm proud of the plate, its face 2 mm over the screen's

        def ring(f):
            return [(ox0 + f * bx, oy0 + f * bb), (ox1 - f * bx, oy0 + f * bb), (ox1 - f * bx, oy1 - f * bt), (ox0 + f * bx, oy1 - f * bt)]
        prof = [(0.0, zb, "side"), (0.0, zf - 0.0025, "edge"), (0.1, zf, "bezel"), (0.88, zf, "edge"), (1.0, zf - 0.003, "side"),
                (1.0, 0.0, None)]
        outer = ring(0.0)
        for (fa, za, kind), (fb, zb2, _) in zip(prof, prof[1:]):
            ra, rb = ring(fa), ring(fb)
            for i in range(4):
                j = (i + 1) % 4
                o0, o1 = Vector(outer[i]), Vector(outer[j])
                along = (o1 - o0).normalized()
                inward = Vector((-along.y, along.x))
                rect = t.strips[kind]
                spx = rect[3] - rect[1]

                def uvp(pt, z_, kind=kind, o0=o0, along=along, inward=inward, spx=spx):
                    d = Vector(pt) - o0
                    across = d.dot(inward) + (z_ if kind == "side" else 0.0)
                    return t.strip(kind, d.dot(along), min(0.98, max(0.02, 0.5 + (across - 0.011) * 1900 / spx)), 1900)
                if kind == "bezel" and i == 0:  # the lower band: its own card
                    bc = card_new(fr, ra[0][0], ra[0][1], ra[1][0] - ra[0][0], rb[0][1] - ra[0][1], za, "bezel")
                    bc["title"] = "display:" + name
                    bc["top"] = (fm, [tuple(q_) for q_ in (ra[i], ra[j], rb[j], rb[i])], za)
                    continue
                fm.face([(ra[i][0], ra[i][1], za), (ra[j][0], ra[j][1], za), (rb[j][0], rb[j][1], zb2), (rb[i][0], rb[i][1], zb2)],
                        [uvp(ra[i], za), uvp(ra[j], za), uvp(rb[j], zb2), uvp(rb[i], zb2)])
        placard(ctx, fr, dx0 + 0.035, oy0 + bb * 0.47, zf, {"pfd": "PFD", "gauges": "STATUS"}.get(page, page.upper()), 0.010, maxw=0.06)
        control(ctx, "knl", fr, dx1 - 0.02, oy0 + bb * 0.47, zf, knob_scale=0.6)
        NAMED.append(("display:" + name, "knl", "BEZEL", fr @ Vector((dx1 - 0.02, oy0 + bb * 0.47, zf)), fr))  # a small knob, so its scale stays on the bezel
        # the switch strip under the bezel (the centre stack's carries the caution lenses instead)
        sy1 = oy0 - 0.006
        if page in ("engines", "gauges"):
            continue
        if sy1 > 0.04:
            l0 = min(p.x for p in loc) + rail + 0.004
            l1 = max(p.x for p in loc) - rail - 0.004
            sub = fr @ Matrix.Translation((l0, 0.006, 0.007))
            rows = P2.STRIPS[page][:max(1, int((sy1 - 0.006) / 0.045))]  # a row under 45 mm hides its labels under its knobs
            panel(ctx, sub, l1 - l0, sy1 - 0.006, "", rows, thick=0.005)
        elif sy1 > 0.024:
            # too short for labelled rows: one row of legend keys, the strip's controls as push buttons
            sub = fr @ Matrix.Translation((min(p.x for p in loc) + rail + 0.004, 0.006, 0.007))
            wl = max(p.x for p in loc) - min(p.x for p in loc) - 2 * rail - 0.008
            panel(ctx, sub, wl, sy1 - 0.006, "", [], thick=0.005, blank=False)
            words = [lb for row in P2.STRIPS[page] for _, lb in row if lb]
            n_ = min(len(words), int((wl - 0.012) / 0.020))
            for k_, word in enumerate(words[:n_]):
                kx = wl / 2 + (k_ - (n_ - 1) / 2) * 0.020
                control(ctx, "key", sub, kx, (sy1 - 0.006) / 2, 0.005, word)


# ---------------------------------------------------------------- consoles, walls, pedestal
_occ = {"tree": None, "n": -1}


STICKS = [(1.0197, -16.1978), (-1.0197, -16.1978)]  # the stock sticks' pivots (x, y), measured


_stick_tree = {}


def stick_blocks(eye, p):
    """Whether the stock sticks (their own meshes as they stand in the scene, shroud included, which the boot
    replaces at about its size) stand between the eye and p."""
    if "t" not in _stick_tree:
        verts, polys = [], []
        for o in bpy.data.objects:
            if o.type == "MESH" and o.name.startswith("stockref_Multirole1_joystick"):
                base = len(verts)
                verts += [o.matrix_world @ v.co for v in o.data.vertices]
                polys += [[base + i for i in pl.vertices] for pl in o.data.polygons]
        _stick_tree["t"] = BVHTree.FromPolygons(verts, polys) if polys else None
    if _stick_tree["t"] is None:
        return False
    d = p - eye
    return _stick_tree["t"].ray_cast(eye, d.normalized(), d.length - 0.002)[0] is not None


def seen_from(ctx, eye, p, margin=0.03):
    """Whether point p is in plain sight of `eye` past everything built so far (the faces in ctx's accumulator)."""
    from mathutils.bvhtree import BVHTree as _B
    acc = ctx["acc"]
    if _occ["n"] != len(acc.faces):
        verts, polys = [], []
        for pts, _, _ in acc.faces:
            polys.append(list(range(len(verts), len(verts) + len(pts))))
            verts += pts
        _occ["tree"], _occ["n"] = _B.FromPolygons(verts, polys), len(acc.faces)
    if "seats" not in _occ:  # the stock seats, in the scene before anything is built: they hide what lies beside them
        verts, polys = [], []
        for o in bpy.data.objects:
            if o.type == "MESH" and o.name.startswith("stock_seat"):
                base = len(verts)
                verts += [o.matrix_world @ v.co for v in o.data.vertices]
                polys += [[base + i for i in pl.vertices] for pl in o.data.polygons]
        _occ["seats"] = _B.FromPolygons(verts, polys) if polys else None
    d = p - eye
    h = _occ["tree"].ray_cast(eye + d.normalized() * 0.03, d.normalized(), d.length - 0.03 - margin)
    if h[0] is None and _occ["seats"] is not None:
        h = _occ["seats"].ray_cast(eye + d.normalized() * 0.03, d.normalized(), d.length - 0.03 - margin)
    return h[0] is None


def boot(ctx, fm, centre, z0, z1, r0, r1, sides=24, folds=6, relief=0.001):
    """A rubber bellows boot from radius r0 at z0 to r1 at z1, its folds standing `relief` proud and sunk in turn (the
    cable strip's ribs run across U, so U goes up the boot and V round it)."""
    t = ctx["t"]
    cx, cy = centre
    rings = folds * 2
    for k in range(sides):
        a0, a1 = 2 * math.pi * k / sides, 2 * math.pi * (k + 1) / sides
        for j in range(rings):
            f0, f1 = j / rings, (j + 1) / rings
            ra = r0 + (r1 - r0) * f0 + (relief if j % 2 else -relief) * (0 < j)
            rb = r0 + (r1 - r0) * f1 + (relief if (j + 1) % 2 else -relief) * (j + 1 < rings)
            ra, rb = ra, rb
            za, zb = z0 + (z1 - z0) * f0, z0 + (z1 - z0) * f1
            pts = [(cx + ra * math.cos(a0), cy + ra * math.sin(a0), za), (cx + ra * math.cos(a1), cy + ra * math.sin(a1), za),
                   (cx + rb * math.cos(a1), cy + rb * math.sin(a1), zb), (cx + rb * math.cos(a0), cy + rb * math.sin(a0), zb)]
            fm.face(pts, [t.strip("cable", za, k / sides, 1500), t.strip("cable", za, (k + 1) / sides, 1500),
                          t.strip("cable", zb, (k + 1) / sides, 1500), t.strip("cable", zb, k / sides, 1500)])


def overhung(ctx, fr, w, h):
    """Whether anything built so far (a module's foot, a housing) stands within 0.3 m straight over the panel's edge."""
    from mathutils.bvhtree import BVHTree as _B
    acc = ctx["acc"]
    if _occ["n"] != len(acc.faces):
        verts, polys = [], []
        for pts, _, _ in acc.faces:
            polys.append(list(range(len(verts), len(verts) + len(pts))))
            verts += pts
        _occ["tree"], _occ["n"] = _B.FromPolygons(verts, polys), len(acc.faces)
    for fx_, fy_ in ((0, 0), (0.5, 0), (1, 0), (0, 0.5), (1, 0.5), (0, 1), (0.5, 1), (1, 1)):
        p_ = fr @ Vector((w * fx_, h * fy_, 0.012))
        if _occ["tree"].ray_cast(p_, Vector((0, 0, 1)), 0.30)[0] is not None:
            return True
    return False


def under_view(fr, w, h, height):
    """A panel on frame fr, w by h, with its tallest part `height` proud, stays under the pilot's lowest view today."""
    for x_, y_ in ((0, 0), (w, 0), (w, h), (0, h), (w / 2, h / 2)):
        p_ = fr @ Vector((x_, y_, height))
        if p_.z > bo.z_cap_at(p_):
            return False
    return True


FRAME_SLOT = 2  # s2_trim's third material: the side windows' frames in the forward screen frame's finish


def frame_metal():
    """The forward screen frame's grey metal: band_bezel's most used material and the median UV of its faces in it
    (the side windows' frames take both: in the trim sheet's frame finish the aft upright blended into the wall under
    night vision and the forward one was faint)."""
    import statistics
    bz = O["band_bezel"]
    top = Counter(p.material_index for p in bz.data.polygons).most_common(1)[0][0]
    uvl = bz.data.uv_layers.active.data
    loops = [li for p in bz.data.polygons if p.material_index == top for li in p.loop_indices]
    return bz.material_slots[top].material, (statistics.median(uvl[li].uv[0] for li in loops),
                                             statistics.median(uvl[li].uv[1] for li in loops))


def window_bezels(ctx):
    """A frame round each side window's opening on the cabin side of the inner glass, as the stock Darkreach frames its
    side glazing: a face flightdeck_window.FRAME_PROUD off the glass with returns to the glass on both edges (the inner one is the
    reveal), a dark gasket on the glass inside it, and a fastener every 14 cm along each member. Points sit on
    glass_int where a horizontal ray from the cabin meets it, so the frame follows the pane's curve."""
    gi = O["glass_int"]
    gw = gi.matrix_world
    tree = BVHTree.FromPolygons([gw @ v.co for v in gi.data.vertices], [tuple(p_.vertices) for p_ in gi.data.polygons])
    import flightdeck_window as win
    rings = {k: [Vector(c) for c in ring] for k, ring in win.rings().items()}
    base = [Vector(c) for c, _ in win.WINDOW_FRAME]  # the outline the outer edge reaches OUTER_TUCK past
    bu, bv = frame_metal()[1]
    corners = rings["outer"]
    n = len(corners)
    centre = sum(corners, Vector((0, 0))) / n
    n_q = n_f = 0
    for s in (1, -1):
        def on_glass(p2, proud):  # (station, z) to the glass, `proud` metres off it toward the cabin
            o_ = Vector((0.9 * s, bo.st(p2.x), p2.y))
            h = tree.ray_cast(o_, Vector((s, 0, 0)), 1.5)
            if h[0] is None:
                return None, None
            nrm = h[1] if h[1].x * s < 0 else -h[1]
            return h[0] + nrm * proud, nrm

        def quad(q, want, strip, run0, run1):  # its grain run on along the member, from run0 to run1 metres
            nonlocal n_q
            if any(v is None for v in q):
                return
            flip = (q[1] - q[0]).cross(q[3] - q[0]).dot(want) < 0
            if flip:
                q = [q[1], q[0], q[3], q[2]]
            if strip == "dark":
                banded(ctx, q, strip, 900, run0=-run1 if flip else run0)
            else:  # the face and its returns in the forward screen frame's grey metal (FRAME_SLOT)
                ctx["acc"].faces.append((q, [Vector((bu + du, bv + dv)) for du, dv in
                                             ((-0.002, -0.002), (0.002, -0.002), (0.002, 0.002), (-0.002, 0.002))], FRAME_SLOT))
            n_q += 1

        total = 0.0  # metres along the frame so far: the grain runs on round it
        for i in range(n):
            j = (i + 1) % n
            # each member in 4 cm runs along its edge, so the face follows the glass's curve
            run = (corners[j] - corners[i]).length
            k_n = max(1, math.ceil(run / 0.04))
            for k in range(k_n):
                f0, f1 = k / k_n, (k + 1) / k_n
                pts = {}
                for name, ring in list(rings.items()) + [("base", base)]:
                    a2, b2 = ring[i].lerp(ring[j], f0), ring[i].lerp(ring[j], f1)
                    pts[name] = (a2, b2)
                # the outer edge where the glass runs under it; past the glass's end it comes back toward the
                # outline in 5% steps of the frame's width (where it found none the segment was left out, a hole in
                # the frame; in quarter steps neighbouring points landed a quarter apart, and the face folded into a
                # tooth at the right window's top corner)
                for e_ in (0, 1):
                    for f in [1.0 - 0.05 * k for k in range(31)]:  # under 0: on toward the inner edge
                        q_ = (pts["base"][e_].lerp(pts["outer"][e_], f) if f >= 0
                              else pts["base"][e_].lerp(pts["inner"][e_], -f))
                        if on_glass(q_, 0.0)[0] is not None:
                            pts["outer"] = (q_, pts["outer"][1]) if e_ == 0 else (pts["outer"][0], q_)
                            break
                o0, nm0 = on_glass(pts["outer"][0], win.FRAME_PROUD)
                o1, nm1 = on_glass(pts["outer"][1], win.FRAME_PROUD)
                i0, nm_in = on_glass(pts["inner"][0], win.FRAME_PROUD)
                i1, _ = on_glass(pts["inner"][1], win.FRAME_PROUD)
                if nm0 is None:
                    continue
                # the face is wound to the glass under its inner edge: the outer edge can land on the fold where a side
                # pane turns into the windscreen's corner pane, whose normal turned the top member's last face at the
                # upper forward corner away from both seats, a crack of sky in the frame
                nm0 = nm_in if nm_in is not None else nm0
                inward = Vector((0.0, bo.st(centre.x), centre.y)) - Vector((0.0, bo.st(pts["inner"][0].x), pts["inner"][0].y))
                r0, r1 = total + f0 * run, total + f1 * run
                quad([o0, o1, i1, i0], nm0, "struct", r0, r1)  # the face
                ig0, _ = on_glass(pts["inner"][0], 0.003)
                ig1, _ = on_glass(pts["inner"][1], 0.003)
                quad([i0, i1, ig1, ig0], inward.normalized(), "edge", r0, r1)  # the reveal down to the glass
                og0, _ = on_glass(pts["outer"][0], 0.002)
                og1, _ = on_glass(pts["outer"][1], 0.002)
                quad([o0, o1, og1, og0], -inward.normalized(), "edge", r0, r1)  # its outer return
                g0, _ = on_glass(pts["gasket"][0], 0.003)
                g1, _ = on_glass(pts["gasket"][1], 0.003)
                quad([ig0, ig1, g1, g0], nm0, "dark", r0, r1)  # the gasket on the glass
            for k in range(max(1, int(run / 0.14))):
                f = (k + 0.5) / max(1, int(run / 0.14))
                mid = corners[i].lerp(corners[j], f).lerp(rings["inner"][i].lerp(rings["inner"][j], f), 0.5)
                p_, nm = on_glass(mid, win.FRAME_PROUD + 0.0002)
                if p_ is None:
                    continue
                along = (Vector((0.0, bo.st(corners[j].x), corners[j].y)) - Vector((0.0, bo.st(corners[i].x), corners[i].y))).normalized()
                along = (along - nm * along.dot(nm)).normalized()
                fastener(ctx, frame_of(p_, along, nm.cross(along)), 0.0, 0.0, 0.0)
                n_f += 1
            total += run
        # under each corner, 2 mm behind the frame's face, a dark patch over the frame's band from its outline
        # (WINDOW_FRAME) corner to the inner one: where one member's return meets the next member's face the mitre
        # left a crack, which showed the sky at the left window's upper forward corner
        inner = rings["inner"]
        for i in range(n):
            o_, in_ = base[i], inner[i]
            a2 = o_ + (base[i - 1] - o_).normalized() * 0.06
            b2 = o_ + (base[(i + 1) % n] - o_).normalized() * 0.06
            ia = in_ + (inner[i - 1] - in_).normalized() * 0.03
            ib = in_ + (inner[(i + 1) % n] - in_).normalized() * 0.03
            nm_ = on_glass(in_, 0.0)[1]
            for q2 in ((o_, b2, ib, in_), (o_, in_, ia, a2)):  # the band round the corner, 2 mm behind the face
                q3 = [on_glass(q_, win.FRAME_PROUD - 0.002)[0] for q_ in q2]
                if nm_ is not None and all(v is not None for v in q3):
                    quad(q3, nm_, "dark", 0.0, 0.06)
    print("WINDOW BEZELS", n_q, "faces,", n_f, "fasteners, both sides")


SILL_SLOPE = 22.0  # degrees the sill falls from the console's edge to the glass


def sill(ctx, s, x_out, top_z):
    """The console's outer edge to the side glass, from station 5.40 (from the forward console's edge at x 1.38 until
    5.72, where the outboard third starts) to 6.90: today's interior closed that strip and is hidden now, so the eye
    looked past the console's edge, down through the glass, at the ground. It falls SILL_SLOPE from the edge to the
    glass, shallower than the pilot's sightline over the edge (about 30 deg), so it reads as a bevel and the side pane
    shows below the console's height, where flat it hid the pane's lowest 9 deg (the owner: slope the side panels to
    open the window's view). Each 50 mm a ray runs out and down from the edge to the inner glass or the hull, whichever
    is nearer; the strip stops 3 mm short of it."""
    from mathutils.bvhtree import BVHTree as _B
    verts, polys = [], []
    for name in ("glass_int", "nose"):
        o = bpy.data.objects.get(name)
        if o is None or o.type != "MESH":
            continue
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        polys += [[base + i for i in pl.vertices] for pl in o.data.polygons]
    if not polys:
        return
    tree = _B.FromPolygons(verts, polys)
    # and forward of 5.72 from the forward console's edge (x 1.38), over today's console top that stayed there
    down = Vector((s * math.cos(math.radians(SILL_SLOPE)), 0.0, -math.sin(math.radians(SILL_SLOPE))))
    for x_e, s_a, s_b in ((1.382 * s, 5.40, 5.72), (x_out, 5.72, 6.90)):
        pts = []
        n_st = max(1, round((s_b - s_a) / 0.05))
        for k in range(n_st + 1):
            st = s_a + (s_b - s_a) * k / n_st
            o_ = Vector((x_e, bo.st(st), top_z + 0.001))
            h = tree.ray_cast(o_ + Vector((0, 0, 0.001)), down, 0.6)
            pts.append((st, o_ + down * ((h[3] - 0.003) if h[0] is not None else 0.25)))
        for (sa, pa), (sb, pb) in zip(pts, pts[1:]):  # the consoles' near-black, mapped evenly (the structure strip,
            # stretched 25 cm across its height, drew a pale slab of long streaks in game)
            # along the station, its grain run on from segment to segment (across it, each 5 cm segment drew the same
            # band of the strip and the sill read as a repeat of long marks in game)
            q = [Vector((x_e, bo.st(sa), top_z + 0.001)), Vector((x_e, bo.st(sb), top_z + 0.001)), pb, pa]
            flip = (q[1] - q[0]).cross(q[3] - q[0]).z < 0
            if flip:
                q = [q[1], q[0], q[3], q[2]]
            banded(ctx, q, "dark", 900, run0=-sb if flip else sa)
        # its ends closed: a plate under each end from the console's edge to the slope's foot on the glass (open, the
        # space under the slope shows as the rail's bare end)
        for st_, p_, out_y in ((pts[0][0], pts[0][1], -1.0), (pts[-1][0], pts[-1][1], 1.0)):
            lip_ = Vector((x_e, bo.st(st_), top_z + 0.001))
            q = [lip_, p_, Vector((x_e, bo.st(st_), p_.z)), Vector((x_e, bo.st(st_), p_.z))]
            if (q[1] - q[0]).cross(q[2] - q[0]).y * out_y < 0:
                q = [q[1], q[0], q[2], q[3]]
            banded(ctx, q, "dark", 900)
        print("SILL", s, "from x %.3f" % x_e, "to the glass at z", [round(p_.z, 3) for _, p_ in pts[::8]])


def console(ctx, side, panels):
    """A side console from the seat to the wall (x 0.86 to 1.62), its top at 4.352 so it covers today's console faces:
    three columns of Dzus panels filled front to aft, each column skipping the stock stick's well (pivot x 1.02,
    station 6.28) where the well crosses it; blank cover plates on the rail positions no system panel takes, as real
    consoles carry them; a stick base round the stock stick; a cable run along the inboard face. Each panel's
    lettering stands upright for its own seat (see `upright` below)."""
    s = side
    x_in, x_out = 0.86 * s, 1.62 * s
    top_z = 4.352
    # the outboard third starts at station 5.72: further forward its corner would rise into the side pane's lowest
    # view from the pilot's eye (az -43, el -23)
    x_mid = 1.38 * s
    # the housing in the cockpit's near-black structure finish (the light structure strip read as a pale slab in sun)
    box(ctx, (min(x_in, x_mid), bo.st(6.90), 3.75), (max(x_in, x_mid), bo.st(5.40), top_z), top="dark", side="dark")
    box(ctx, (min(x_mid, x_out), bo.st(6.90), 3.75), (max(x_mid, x_out), bo.st(5.72), top_z), top="dark", side="dark")
    # a lip along the console's outboard edge, as the stock consoles have, between the panels and the sill
    box(ctx, (s * 1.605, bo.st(6.90), top_z), (s * 1.622, bo.st(5.72), top_z + 0.016), top="dark", side="dark")
    box(ctx, (s * 1.365, bo.st(5.72), top_z), (s * 1.382, bo.st(5.40), top_z + 0.016), top="dark", side="dark")
    sill(ctx, s, x_out, top_z)
    ex, ey = Vector((-1, 0, 0)), Vector((0, -1, 0))
    x_start = max(0.875 * s, 1.605 * s)  # local x runs toward -X world from here
    gap_x = 0.010
    cols, x = [], 0.0
    for w in (0.237, 0.237, 0.236):
        cols.append((x, x + w))
        x += w + gap_x
    stick_local = x_start - 1.02 * s
    well_s, well_x = (6.20, 6.36), (stick_local - 0.075, stick_local + 0.075)
    pitch_row, title_h, gap = 0.042, 0.017, 0.004  # 42 mm a row of controls and their labels, 4 mm between panels
    # Each panel's "up" (its title's edge, the way its lettering stands) and the rails it fills along. UPRIGHT: up is
    # outboard, toward the console's window, so the lettering stands upright for the seat beside it, as the stock
    # Medusa's and Darkreach's side consoles read from theirs; the rails are six lanes across the console, one panel
    # width (0.237 m) of station each, filled from the inboard edge outward. Otherwise: up is forward, three
    # columns along the console filled from the front, the lettering a quarter turn from upright at the seat's side.
    upright = __import__("os").environ.get("CONSOLE_UPRIGHT", "1") == "1"
    if upright:
        lanes = [5.42 + 0.245 * k for k in range(6)]  # each lane's forward station, 0.237 m long
        n_lanes = len(lanes)
        well_u = (1.02 - 0.075 - 0.875, 1.02 + 0.075 - 0.875)  # the stick's well, metres outboard of the inboard rail

        def lane_w(c):
            return 0.237

        def limit(c):  # forward of station 5.72 the console stops at x 1.37, where the outboard third starts
            return (1.37 if lanes[c] < 5.72 else 1.605) - 0.875

        def pfr(c, f0, h_):  # the panel's frame: x along its lane (reading forward to aft from the seat), y outboard
            if s > 0:
                return frame_of(Vector((0.875 + f0, bo.st(lanes[c] + 0.237), top_z)), Vector((0, -1, 0)), Vector((1, 0, 0)))
            return frame_of(Vector((-(0.875 + f0), bo.st(lanes[c]), top_z)), Vector((0, 1, 0)), Vector((-1, 0, 0)))

        def blocked(c, f0, h_):
            return lanes[c] < well_s[1] and lanes[c] + 0.237 > well_s[0] and f0 < well_u[1] and f0 + h_ > well_u[0]
        fill = [0.0] * n_lanes
    else:
        n_lanes = 3

        def lane_w(c):
            return cols[c][1] - cols[c][0]

        def limit(c):
            return 6.89

        def pfr(c, f0, h_):
            return frame_of(Vector((x_start - cols[c][0], bo.st(f0 + h_), top_z)), ex, ey)

        def blocked(c, st0, h):
            return cols[c][0] < well_x[1] and cols[c][1] > well_x[0] and st0 < well_s[1] and st0 + h > well_s[0]
        fill = [5.42] * 3
        fill[0 if s > 0 else 2] = 5.74  # the outboard column, local 0 for the pilot's console and 2 for the commander's
    well_end = well_u[1] if upright else well_s[1]
    def height(rows):
        keypad = all(k_ == "key" for r_ in rows for k_, _ in r_)
        return title_h + (0.022 if keypad else pitch_row) * len(rows) + 0.006 + (GUARD_CLEAR if any(k_ == "gtog" for k_, _ in rows[0]) else 0.0)
    queue = list(panels)
    stick_blanks = [0]
    while queue:
        title, rows = queue.pop(0)
        h = height(rows)
        c = min(range(n_lanes), key=lambda k: fill[k])
        st0 = fill[c]
        if blocked(c, st0, h):
            # the rail forward of the stick's well goes to the first later panel short enough for it, not to waste
            short = None  # backfill off: the rail just forward of the well stands behind the stick from the seat
            if short is not None:
                print("CONSOLE %d backfill %s before the well, ahead of %s" % (s, queue[short][0], title))
                queue.insert(0, (title, rows))
                queue.insert(0, queue.pop(short + 1))
                continue
            st0 = well_end + gap
        if st0 + h > limit(c):
            fill[c] = 99
            if min(fill) > 98:
                print("CONSOLE %d dropped" % s, [title] + [q_[0] for q_ in queue])
                break
            queue.insert(0, (title, rows))
            continue
        w = lane_w(c)
        fr = pfr(c, st0, h)
        eye_s = bo.EYE[1] if s > 0 else bo.EYE[-1]
        pts_ = [fr @ Vector((w * fx_, h * fy_, 0.03)) for fx_, fy_ in ((0.5, 0.5), (0.2, 0.3), (0.8, 0.7))]
        title_pts = [fr @ Vector((x_, h - 0.0095, 0.004)) for x_ in (0.014, 0.035, 0.060)]
        if sum(seen_from(ctx, eye_s, q_) for q_ in pts_) < 2:
            print("CONSOLE %d hidden %s col %d st %.3f" % (s, title, c, st0))
            fill[c] = st0 + 0.02  # hidden from its seat (under the main panel, or by the seat itself): try 20 mm aft
            queue.insert(0, (title, rows))
            continue
        title_aft = False

        def clear(q_):
            return seen_from(ctx, eye_s, q_, 0.004)
        if sum(clear(q_) for q_ in title_pts) < 2:
            aft_pts = [fr @ Vector((x_, 0.0095, 0.004)) for x_ in (0.014, 0.035, 0.060)]
            if sum(clear(q_) for q_ in aft_pts) < 2:
                print("CONSOLE %d title hidden %s col %d st %.3f" % (s, title, c, st0))
                fill[c] = st0 + 0.02  # both edges behind what is built (a module, a screen): try 20 mm aft
                queue.insert(0, (title, rows))
                continue
            title_aft = True  # the top edge is behind a module or a screen: the title goes along the aft edge
        # its tallest part: a toggle or an open guard stands 31 mm, a pointer or big knob 25; keys and small knobs 20
        tallest = 0.035 if any(k_ in ("tog", "togw", "gtog", "big", "ptr", "pull", "stk", "skt") for r_ in rows for k_, _ in r_) else 0.022
        if not under_view(fr, w, h, tallest):
            print("CONSOLE %d out of view %s col %d st %.3f" % (s, title, c, st0))
            fill[c] = st0 + 0.09 + gap  # leave this slot to a blank plate and try further aft
            queue.insert(0, (title, rows))
            continue
        if overhung(ctx, fr, w, h):  # a module's foot stands over it: a blank on the overhung rail, the panel aft
            st1 = st0
            while st1 < limit(c) and overhung(ctx, pfr(c, st1, h), w, h):
                st1 += 0.005
            if st1 - st0 > 0.02:
                # plain: a grille here read as the modules standing on a vent (owner, build 33)
                panel(ctx, pfr(c, st0, st1 - gap - st0), w, st1 - gap - st0, "", [], blank=False)
            fill[c] = st1
            queue.insert(0, (title, rows))
            continue
        # the stock sticks stand after the consoles are built: a title the stick hides from its seat goes to the
        # edge's other end, or to the other edge, whichever end the stick leaves clear
        def title_end(fr_, h_, aft0):
            # a guard first in the top row stands open 27 mm tall under the title's left end: the title goes right
            r0 = rows[0][0][0] == "gtog" and rows[0][-1][0] != "gtog" and not aft0
            for aft_, right_ in ((aft0, r0), (aft0, not r0), (not aft0, False), (not aft0, True)):
                yy_ = 0.0095 if aft_ else h_ - 0.0095
                xs3 = (w - 0.060, w - 0.035, w - 0.014) if right_ else (0.014, 0.035, 0.060)
                if sum(not stick_blocks(eye_s, fr_ @ Vector((x_, yy_, 0.004))) for x_ in xs3) >= 2 and                         sum(clear(fr_ @ Vector((x_, yy_, 0.004))) for x_ in xs3) >= 2:
                    return aft_, right_
            return None
        def body_clear(fr_, h_):  # every control and label position the stick leaves in view from the seat
            return all(not stick_blocks(eye_s, fr_ @ Vector((w * (k + 0.5) / 5, h_ * fy, 0.012)))
                       for k in range(5) for fy in (0.25, 0.5, 0.75))
        end = title_end(fr, h, title_aft) if body_clear(fr, h) else None
        if end is None:  # behind the stick at every end: the slot goes to one of the next three panels if the
            # stick leaves one of its title ends clear there; this one takes the next slot
            for k, (t2, r2) in enumerate(queue[:3]):
                h2 = height(r2)
                if blocked(c, st0, h2) or st0 + h2 > limit(c):
                    continue
                fr2 = pfr(c, st0, h2)
                if body_clear(fr2, h2) and title_end(fr2, h2, False) is not None:
                    print("CONSOLE %d %s's slot (col %d st %.3f) to %s: the stick hides every end of its title" % (s, title, c, st0, t2))
                    queue.insert(0, queue.pop(k))
                    queue.insert(1, (title, rows))
                    break
            else:
                if True:  # none of them either: a blank plate in the stick's shadow, the panel aft
                    stick_blanks[0] += 1
                    hb = 0.050
                    print("CONSOLE %d blank in the stick's shadow col %d st %.3f..%.3f, %s aft of it" % (s, c, st0, st0 + hb, title))
                    panel(ctx, pfr(c, st0, hb), w, hb, "", [])
                    fill[c] = st0 + hb + gap
                    queue.insert(0, (title, rows))
                    continue
                print("CONSOLE %d title of %s behind the stick at every end" % (s, title))
                end = (title_aft, False)
            if end is None:
                continue
        if end != (title_aft, False):
            print("CONSOLE %d title of %s moved from the stick: aft %s right %s" % (s, title, end[0], end[1]))
        title_aft, title_right = end
        print("CONSOLE %d placed %s col %d st %.3f..%.3f aft %s" % (s, title, c, st0, st0 + h, title_aft))
        panel(ctx, fr, w, h, title, rows, title_aft=title_aft, title_right=title_right)
        GROUP_AXES["console_%s_%s" % ("left" if s > 0 else "right", title.lower().replace(" ", "_"))] = (
            fr.to_3x3().col[2].normalized(), fr.to_3x3().col[1].normalized())
        GROUPS.append(("console_%s_%s" % ("left" if s > 0 else "right", title.lower().replace(" ", "_")),
                       fr @ Vector((w / 2, h / 2, 0.01)), max(h, w) * 1.2, s))
        fill[c] = st0 + h + gap
    # blank cover plates on what is left of each column, in rail units of up to 0.09 m
    for c in range(n_lanes):
        st0 = min(fill[c], 99)
        w = lane_w(c)
        while st0 + 0.05 < limit(c):
            h = min(0.09, limit(c) - st0)
            if blocked(c, st0, h):
                st0 = well_end + gap
                continue
            fr = pfr(c, st0, h)
            if under_view(fr, w, h, 0.012):
                panel(ctx, fr, w, h, "", [])
            st0 += h + gap
    # the stick base: a plate, a raised collar and a ribbed boot round the stock stick's pivot
    fr = frame_of(Vector((x_start - well_x[0], bo.st(well_s[1]), top_z)), ex, ey)
    ww, wh = well_x[1] - well_x[0], well_s[1] - well_s[0]
    fm = FM(ctx["acc"], fr)
    card_prism(ctx, fr, 0, 0, ww, wh, 0, 0.006, 0.0015, "dark")  # a carded plate: grain, worn chamfer, four screws
    for fx_, fy_ in ((0.012, 0.012), (ww - 0.012, 0.012), (ww - 0.012, wh - 0.012), (0.012, wh - 0.012)):
        fastener(ctx, fr, fx_, fy_, 0.006)
    centre = (ww / 2, wh / 2)
    sp.cap(FM(ctx["round"], fr), ctx["t"], centre, 0.046, 0.006, 0.014, 48, ctx["t"].hw["cap"], "edge")
    # up to the stock grip's lower ring (32.5 mm across at z 4.415, measured): the stock lower shroud comes off
    boot(ctx, FM(ctx["round"], fr), centre, 0.014, 4.415 - top_z, 0.040, 0.0335, sides=20, folds=7)
    PANELS.append(("well", fr @ Vector((ww / 2, wh / 2, 0.006))))
    for fx in (0.01, ww - 0.01):
        for fy in (0.01, wh - 0.01):
            fastener(ctx, fr, fx, fy, 0.006)
    GROUPS.append(("console_%s_stick" % ("left" if s > 0 else "right"), fr @ Vector((ww / 2, wh / 2, 0.02)), 0.36, s))
    for k in range(3):
        z = 3.95 + 0.016 * k
        tube(ctx, [Vector((x_in - s * 0.008, bo.st(st), z + 0.01 * math.sin(st * 9))) for st in (5.45, 5.8, 6.2, 6.5, 6.85)], 0.006)


# forward to aft. EXT LIGHTS first: its five long toggle stems hang forward from the eye's view, and behind TRIM they
# crossed its legends and the overhead light laid their shadows on them (TRIM's night peak 14 on a ground of 9 against
# 45 for the rows aft); at the forward end they hang over the plate's edge
OVERHEAD = (("R", "EXT LIGHTS"), ("L", "TRIM"), ("L", "WARNING"), ("R", "SENSOR COOL"))


def overhead(ctx):
    """The overhead console's switch panels, under its plates between the hatches, from their forward end aft: 0.1.3
    had toggles and red lamps there, which the rebuild stripped with today's switch
    kit and left as a bare plate. They are panels the side consoles have no room for (OVERHEAD, taken off their
    queues), their lettering standing upright for a crew member looking up and forward (its top edge aft)."""
    # on 0.1.3's own overhead plates (cc_cockpit_console, kept in the shell): x +-0.148, from
    # (station 5.62, z 5.194) up to (6.83, 5.474), facing down and aft. The blockout's plate (bo_overhead) hangs above
    # their forward half, so panels there sit under 0.1.3's
    fwd, aft_ = Vector((0, -16.855, 5.194)), Vector((0, -15.645, 5.474))
    ey = (aft_ - fwd).normalized()
    ex = Vector((-1, 0, 0))
    n = ex.cross(ey).normalized()  # down and aft, toward the crew
    x_half = 0.140
    c, s0 = fwd, 0.0
    lists = {"L": dict(P2.LEFT_CONSOLE), "R": dict(P2.RIGHT_CONSOLE)}
    u, gap, placed = 0.02, 0.006, set()
    for side, title in OVERHEAD:
        rows = lists[side][title]
        h = 0.017 + 0.042 * len(rows) + 0.006
        origin = c + ey * (s0 + u) + Vector((x_half, 0, 0)) + n * 0.004  # 4 mm below the plate
        panel(ctx, frame_of(origin, ex, ey), 2 * x_half, h, title, rows)
        print("OVERHEAD placed %s at %.3f m from the forward end" % (title, u))
        placed.add(title)
        u += h + gap
    return placed


def wall_panel(ctx, side, title, rows, shell_tree):
    """Breakers on a sloped shelf along the foot of the wall, outboard of the console (x 1.38 to 1.45, up to z 4.44):
    under the side pane's lowest view from the pilot's eye (28 deg down there against 23 for the glass), so it hides
    nothing the pilot sees today."""
    ey = Vector((side * 0.65, 0, 0.76)).normalized()
    ez_want = Vector((-side * 0.76, 0, 0.65))
    ex = Vector((0, -1, 0)) if side > 0 else Vector((0, 1, 0))
    w, h = 0.66, 0.115
    s0 = 5.66
    origin = Vector((side * 1.375, bo.st(s0 + w) if side > 0 else bo.st(s0), 4.352))
    fr = frame_of(origin, ex, ey)
    if fr.to_3x3().col[2].dot(ez_want) < 0:
        ex = -ex
        origin = Vector((side * 1.375, bo.st(s0) if side > 0 else bo.st(s0 + w), 4.352))
        fr = frame_of(origin, ex, ey)
    panel(ctx, fr, w, h, title, rows)


def pilot_footwell(ctx):
    """The pilot's rudder pedals and footwell, worked to the stock Darkreach's level: each pedal a bevelled plate turned
    to the foot (tilted 20 deg back from upright), seven raised tread ribs and a toe lip on it, a round arm up to the
    cross shaft with a pivot boss there; on the floor three anti-slip rails
    and a fastened heel plate, on the side walls (the centre console's side and the side console's inboard face)
    vertical stiffeners and a seam. The stock footwell carries its relief in texture on plain walls; here it is a
    little geometry on the trim sheet's own finishes."""
    t = ctx["t"]
    n0 = {k: len(ctx[k].faces) for k in ("acc", "round")}
    n = Vector((0.0, math.cos(math.radians(20)), math.sin(math.radians(20))))  # toward the pilot's foot
    ex = Vector((1.0, 0.0, 0.0))
    shaft_z, shaft_st = 4.29, 5.41
    for dx in (-0.11, 0.11):
        c = Vector((0.55 + dx, bo.st(5.42), 3.96))
        fr = frame_of(c, ex, n.cross(ex))
        fm = FM(ctx["acc"], fr)
        w, h = 0.09, 0.22
        sp.plate(fm, t, [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)], -0.012, 0.0, 0.003, "dark")
        for k in range(7):  # the tread
            y = -h / 2 + 0.03 + k * (h - 0.06) / 6
            sp.plate(fm, t, [(-0.035, y - 0.003), (0.035, y - 0.003), (0.035, y + 0.003), (-0.035, y + 0.003)], 0.0, 0.003, 0.0008, "edge")
        sp.plate(fm, t, [(-w / 2, h / 2 - 0.018), (w / 2, h / 2 - 0.018), (w / 2, h / 2), (-w / 2, h / 2)], 0.0, 0.02, 0.002, "dark")  # toe lip
        # the arm from behind the pedal's top edge (the frame's y runs down the pedal) straight up to the shaft, in the
        # shaft's dark metal: from 3 cm over its foot, bowed 2 cm aft, on the cable strip, it climbed across the
        # pedal's face from the seat as a threaded rod, with a ribbed linkage bar between the two
        back = fr @ Vector((0.0, -h / 2 + 0.03, -0.012))
        top = Vector((0.55 + dx, bo.st(shaft_st), shaft_z))
        tube(ctx, [back, top], r=0.009, sides=8, strip="dark")
        tube(ctx, [top - Vector((0.018, 0, 0)), top + Vector((0.018, 0, 0))], r=0.018, sides=10, strip="dark")  # the pivot boss
    for x in (0.38, 0.55, 0.72):  # anti-slip rails on the floor
        box(ctx, (x - 0.012, bo.st(5.95), 3.75), (x + 0.012, bo.st(5.12), 3.758), top="edge", side="dark")
    hp = frame_of(Vector((0.55, bo.st(5.95), 3.7585)), ex, Vector((0, 1, 0)))  # facing up
    sp.plate(FM(ctx["acc"], hp), t, [(-0.16, -0.10), (0.16, -0.10), (0.16, 0.10), (-0.16, 0.10)], 0.0, 0.003, 0.0015, "struct")
    for fx, fy in ((-0.145, -0.085), (0.145, -0.085), (-0.145, 0.085), (0.145, 0.085)):
        fastener(ctx, hp, fx, fy, 0.003)
    # stiffeners and a seam on the footwell's walls, the centre console's side (stations 5.375 to 5.91) and the side
    # console's inboard face (from 5.40): forward of the walls a stiffener at 5.25 and the seam's front stood alone
    # in the footwell, as posts hanging under the radar's key row and a strip across to the floor
    for x_wall, sgn, st_a, st_b in ((0.24, 1.0, 5.375, 5.91), (0.86, -1.0, 5.40, 6.05)):
        x_wall += sgn * FLUSH_GAP
        for stn in (5.55, 5.85):
            box(ctx, (x_wall + sgn * 0.0 - (0.0 if sgn > 0 else 0.012), bo.st(stn + 0.015), 3.76),
                (x_wall + (0.012 if sgn > 0 else 0.0), bo.st(stn - 0.015), 4.20), top="dark", side="struct")
        box(ctx, (x_wall - (0.0 if sgn > 0 else 0.004), bo.st(st_b), 3.98), (x_wall + (0.004 if sgn > 0 else 0.0), bo.st(st_a), 3.986),
            top="dark", side="dark")
    print("PILOT FOOTWELL pedals, rails, heel plate, stiffeners:", sum(len(f[0]) - 2 for k in n0 for f in ctx[k].faces[n0[k]:]),
          "triangles before the cull")


AFT_ROWS = ((3.76, 4.90), (4.945, 5.80))  # the skin's bays up the aft bulkhead, a stiffener in the gap at rack height
AFT_FRAMES = (0.24, 0.92)  # each side of the centreline: a frame's middle, metres out


def aft_bulkhead(ctx, shell):
    """The aft bulkhead (station 6.95, y -15.525) finished as the stock Darkreach finishes the wall behind its seats:
    panelled, framed, with boxes and placarded panels on it. The shell's atlas paints the wall itself a plain grey, so
    it is skinned 4 mm proud in the structure strip, whose panel joints and Dzus columns run up a wall unbroken (the
    housings' finish), in two bays split at the racks' tops, fitted to the hull, to 0.1.3's racks outboard of the seats,
    to the stock hull frame (2 to 4 cm in front of the wall) and to the roof hatches' liners by casting against them at
    each part's front face, the nearer side for both. Vertical frames at AFT_FRAMES and a stiffener between them over
    the racks; between the seats an equipment rack with an access panel, and over it, behind each seat and in each
    upper outboard corner, placarded panels and boxes, cable runs between the boxes over the stiffener and a conduit
    down each outboard frame, mirrored for the commander. Everything stands within 17 cm of the wall behind and between
    the seats, none of it over a seat (|x| 0.25 to 0.85) more than 6 cm out, so nothing crosses the seats' path up
    through the roof hatches; the eye point is untouched."""
    y0 = -15.529  # the skin, 4 mm in front of the wall (at 2 mm it met a fitting on the wall); fittings stand on it
    yf = y0 - 0.001
    vs_, ps_ = [], []
    for o in (shell, O["hatch_liner_L"], O["hatch_liner_R"]):  # the roof hatches' liners are parts of their own
        ps_ += [[len(vs_) + i for i in p.vertices] for p in o.data.polygons]
        vs_ += [o.matrix_world @ v.co for v in o.data.vertices]
    hull = BVHTree.FromPolygons(vs_, ps_)

    def reach(x, z, d, depth=0.0):  # how far the shell stands from (x, z) along d, over a part `depth` deep from the skin
        r = 3.0
        for y_ in (y0, yf - depth):
            h = hull.ray_cast(Vector((x, y_, z)), Vector(d), 3.0)
            r = min(r, h[3] if h[0] is not None else 3.0)
        return r

    def out(zs, depth=0.0):  # half width clear of the shell at heights zs, the nearer side
        return min(reach(0.0, z_, (s, 0, 0), depth) for z_ in zs for s in (1, -1)) - 0.01

    def roof(x, z0, depth=0.0):
        return z0 + reach(x, z0, (0, 0, 1), depth) - 0.005
    for z0, z1 in AFT_ROWS:
        xo = out((z0 + 0.005, z0 + 0.15))
        print("AFT BULKHEAD bay z %.3f to %.3f out to x +-%.3f" % (z0, z1, xo))
        n_ = max(1, math.ceil(xo / 0.22))
        for s in (1, -1):
            xs = [s * xo * k / n_ for k in range(n_ + 1)]
            for xa, xb in zip(xs, xs[1:]):
                ta, tb = min(z1, roof(xa, z0)), min(z1, roof(xb, z0))
                if min(ta, tb) < z0 + 0.03:
                    continue
                # wound to face the crew (-y), U running across from the centreline so the joints line up bay to bay
                q = [Vector((xa, y0, z0)), Vector((xb, y0, z0)), Vector((xb, y0, tb)), Vector((xa, y0, ta))]
                if s < 0:
                    q = [q[1], q[0], q[3], q[2]]
                banded(ctx, q, "struct", 900, run0=min(xa, xb) + 2.0)
    for s in (1, -1):
        for xm in AFT_FRAMES:
            x = s * xm
            box(ctx, (x - 0.02, yf, 3.76), (x + 0.02, yf - 0.03, min(roof(x + d_, 4.0, 0.03) for d_ in (-0.02, 0.02)) - 0.002),
                top="dark", side="struct")
    f0, f1 = AFT_FRAMES
    z1, z2 = AFT_ROWS[0][1], AFT_ROWS[1][0]
    xs_ = out((z1 + 0.003, z2 - 0.003), 0.02)
    print("AFT BULKHEAD stiffener at z %.3f out to x +-%.3f" % (z1, xs_))
    for xa, xb in ((-xs_, -f1 - 0.02), (-f1 + 0.02, -f0 - 0.02), (-f0 + 0.02, f0 - 0.02), (f0 + 0.02, f1 - 0.02), (f1 + 0.02, xs_)):
        if xb - xa > 0.02:
            box(ctx, (xa, yf, z1), (xb, yf - 0.02, z2), top="dark", side="struct")
    fr = lambda x, z: frame_of(Vector((x, yf - 0.002, z)), Vector((1, 0, 0)), Vector((0, 0, 1)))  # facing the crew
    # between the seats: the rack (under the stiffener), its access panel, and an avionics panel over it
    box(ctx, (-0.20, yf, 3.76), (0.20, yf - 0.17, z1), top="dark", side="dark")
    def card_of(frame, w, h):  # the card panel() laid on frame, for marks in its own paint
        return card_at(frame, w / 2, h / 2, 0.003)[0]
    rf = frame_of(Vector((-0.17, yf - 0.17, 4.30)), Vector((1, 0, 0)), Vector((0, 0, 1)))
    panel(ctx, rf, 0.34, 0.50, "", [], blank=False)
    placard(ctx, rf, 0.17, 0.43, 0.0032, "AVIONICS BAY", 0.016)
    card_of(rf, 0.34, 0.50)["items"].append(["hazard", 0.02, 0.02, 0.32, 0.05, 0.03])  # a striped kick strip at its foot
    panel(ctx, fr(-0.18, 4.99), 0.36, 0.22, "", [], blank=False)
    placard(ctx, fr(-0.18, 4.99), 0.18, 0.185, 0.0032, "COOLING AIR", 0.016)
    for k in range(6):  # its outlet: slots across the panel
        card_of(fr(-0.18, 4.99), 0.36, 0.22)["items"].append(["slot", 0.05, 0.03 + 0.022 * k, 0.31, 0.04 + 0.022 * k])
    for s in (1, -1):
        # behind each seat over the headrest: an oxygen and rescue panel; in the upper outboard corner a junction box
        # (the dark strip's own joints and Dzus heads on its face: carded lids took every card from 1050 to 1000
        # px/m), outboard of the seat, kept clear of the hull frame
        x0 = 0.30 if s > 0 else -0.86
        panel(ctx, fr(x0, 4.99), 0.56, 0.18, "", [], blank=False)
        placard(ctx, fr(x0, 4.99), 0.28, 0.135, 0.0032, "OXYGEN" if s > 0 else "RESCUE", 0.016)
        if s < 0:  # the rescue panel ringed in hazard stripes, as the stock cockpits mark their emergency gear
            card_of(fr(x0, 4.99), 0.56, 0.18)["items"].append(["hazard", 0.012, 0.012, 0.548, 0.168, 0.012])
        xo = min(1.30, out((4.965, 5.06, 5.155), 0.08))
        top = min(roof(s * x_, 4.95, 0.08) for x_ in (0.98, xo)) - 0.01
        if xo > 1.15 and top > 5.10:
            box(ctx, (s * 0.98, yf, 4.96), (s * xo, yf - 0.08, min(top, 5.16)), top="dark", side="dark")
        # a conduit down the outboard frame's face into the side console's aft end (its top at 4.352), outboard of the
        # seat
        tube(ctx, [Vector((s * f1, yf - 0.045, 4.94)), Vector((s * f1, yf - 0.045, 4.36))], r=0.009, sides=6)
    # two cable runs over the stiffener, under the panels, from junction box to junction box, 4.5 cm off the wall
    for zc in (4.957, 4.975):
        tube(ctx, [Vector((-0.978, yf - 0.045, zc)), Vector((0.978, yf - 0.045, zc))], r=0.008, sides=6)


def pedestal(ctx):
    """The pedestal and its throttle quadrant. The quadrant is a raised housing round the stock throttles' pivots
    (station 6.05, x +-0.01, z 4.142; their grips sit at x +-0.075): a field-grey top with a slot per lever, detent
    ticks and IDLE and MAX marks along each slot, ENG 1 and ENG 2 beside them, fastened side cheeks, and a friction
    lock knob on its right cheek. The span lever stands in its own gate on the left, RET to EXT, the flap lever on the
    right, 0 15 30. Engine start, fuel and bays sit on panels aft of it."""
    t = ctx["t"]
    box(ctx, (-0.21, bo.st(6.55), 3.75), (0.21, bo.st(5.91), 4.38))
    ex, ey = Vector((-1, 0, 0)), Vector((0, -1, 0))
    # the stems, pivoted at 6.05 and 0.278 m under the top, cross it from 5.949 to 6.151 over the 40 deg throw: the
    # slots (2 cm in from the fore end, 4.5 from the aft) run 5.93 to 6.17, 7 mm past each stop; at 5.95 to 6.19 the
    # stem stood on the slot's forward end at full and never reached its aft 4 cm
    # the housing runs 2.5 cm further aft than its slots need, for the ENG captions on its top aft of them (on its steep aft face they read foreshortened from the seats)
    s0, s1 = 5.91, 6.215
    # the top at 4.42: the stock grips' bases ride at 4.44 over pivots 30 cm below them (stockref_Multirole1_throttle),
    # and at 26 mm high the housing left them hanging 3.4 cm over their slots in game
    hw_, hz = 0.115, 0.040
    box(ctx, (-hw_, bo.st(s1), 4.38), (hw_, bo.st(s0), 4.38 + hz - 0.008), top=None, side="struct", pxm=1200)
    fr = frame_of(Vector((hw_, bo.st(s1), 4.38 + hz - 0.008)), ex, ey)
    fm = FM(ctx["acc"], fr)
    L = s1 - s0
    # each cut round its lever's stalk as the game moves it (throttle_sweep): the stalk 1.15 cm outboard of its pivot
    # (the grip 7.4 cm out over the plate), from 10 deg aft at idle to 30 deg forward at full, 4 mm clear all round
    top_z = 4.38 + hz
    feet = [stalk_footprint(pts, top_z) for pts in throttle_sweep()]
    xs_ = tuple(hw_ - (f[0] + f[1]) / 2 for f in feet)  # local x of each lever's cut: world x +0.0215 and -0.0215
    sw = max(f[1] - f[0] for f in feet) / 2 + 0.004
    e0 = max(0.012, s1 - max(f[3] for f in feet) - 0.004)  # the cut's aft end (local y from the housing's aft end)
    e1 = min(L - 0.012, s1 - min(f[2] for f in feet) + 0.004)  # its forward end
    # the cut's black walls stand 1 mm inside the top's cut edges, which the lip covers: flush with them, the top's grey
    # edge and the wall shared one plane up the slot's sides and flickered along both slots in game
    bk = 0.001
    print("QUADRANT cuts at world x %+.4f and %+.4f, %.1f mm wide, stations %.3f to %.3f"
          % (hw_ - xs_[0], hw_ - xs_[1], 2000 * sw, s1 - e1, s1 - e0))
    print("LEVER SWEEP", lever_sweep_faults(top_z, [(hw_ - xl, sw - bk, s1 - e1 + bk, s1 - e0 - bk) for xl in xs_]),
          "faults over the throttles' travel (build 23's cuts and mounts:",
          lever_sweep_faults(top_z, [(x_, 0.011, 5.93, 6.17) for x_ in (0.075, -0.075)], rest=0.0), ")")
    assert lever_sweep_faults(top_z, [(hw_ - xl, sw - bk, s1 - e1 + bk, s1 - e0 - bk) for xl in xs_]) == 0
    cuts = [0.0, xs_[0] - sw, xs_[0] + sw, xs_[1] - sw, xs_[1] + sw, 2 * hw_]
    pieces = [card_prism(ctx, fr, cuts[i], 0, cuts[i + 1], L, 0, 0.008, 0.0015, "field") for i in range(0, 6, 2)]
    lip, lz, fz = 0.0022, 0.0105, -0.017  # the lip 2.2 mm wide and 1.5 mm proud; the floor 17 mm down, over the pedestal's top
    for k_, xl in enumerate(xs_):  # the cut's ends; a lip round the cut; black walls down to a black floor
        card_prism(ctx, fr, xl - sw, 0, xl + sw, e0, 0, 0.008, 0.0, "field")
        card_prism(ctx, fr, xl - sw, e1, xl + sw, L, 0, 0.008, 0.0, "field")
        inner = [(xl - sw + bk, e0 + bk), (xl + sw - bk, e0 + bk), (xl + sw - bk, e1 - bk), (xl - sw + bk, e1 - bk)]
        outer = [(xl - sw + bk - lip, e0 + bk - lip), (xl + sw - bk + lip, e0 + bk - lip), (xl + sw - bk + lip, e1 - bk + lip),
                 (xl - sw + bk - lip, e1 - bk + lip)]
        top_, side_, black = cellc(t, "keyedge"), cellc(t, "pin"), cellc(t, "pin")
        for i in range(4):
            j = (i + 1) % 4
            fm.face([outer[i] + (lz,), outer[j] + (lz,), inner[j] + (lz,), inner[i] + (lz,)], [top_] * 4)  # the lip's top
            fm.face([outer[i] + (0.008,), outer[j] + (0.008,), outer[j] + (lz,), outer[i] + (lz,)], [side_] * 4)  # its outer face
            fm.face([inner[j] + (fz,), inner[i] + (fz,), inner[i] + (lz,), inner[j] + (lz,)], [black] * 4)  # the cut's wall
        fm.face([q + (fz,) for q in inner], [black] * 4)
    PANELS.append(("quadrant", fr @ Vector((hw_, L / 2, 0.008))))
    for k, xl in enumerate(xs_):
        left, right = pieces[k], pieces[k + 1]
        for j in range(9):  # detent ticks beside the cut, long ones at the stops and mid travel
            yy = e0 + 0.01 + (e1 - e0 - 0.02) * j / 8  # along the slot
            right["items"].append(["line", lip + 0.0015, yy, lip + (0.0105 if j % 4 == 0 else 0.0065), yy, 0.0016, [238, 238, 232]])
        # the stops on the housing's end bands, on the slot's line, past the ends of the grip's travel: beside the slot
        # the grips swept over them from the seats
        placard(ctx, fr, xl, e0 - lip - 0.007, 0.008, "IDLE", 0.0085, maxw=2 * sw + 2 * lip)
        placard(ctx, fr, xl, 0.011, 0.008, "ENG %d" % (k + 1), 0.0085, maxw=0.05)
        placard(ctx, fr, xl, L - (0.02 - lip) / 2, 0.008, "MAX", 0.0085, maxw=2 * sw + 2 * lip)

        CONTROLS.append(("throttle", fr @ Vector((xl, L / 2, 0.008))))
    # the friction lock: a knob on the top's right front, clear of the right cut, its label under it
    fx_ = 2 * hw_ - 0.012
    place(ctx["coll"], "big", fr, (fx_, L - 0.030, 0.008), scale=0.75)
    knob_mark(ctx, "big", fr, fx_, L - 0.030, 0.008, 0.75)
    CONTROLS.append(("knob", fr @ Vector((fx_, L - 0.030, 0.008))))
    placard(ctx, fr, fx_ - 0.004, L - 0.058, 0.008, "FRICTION", 0.0085)
    # fastened cheeks, facing out
    for xw in (hw_ + 0.004, -hw_ - 0.004):
        if xw > 0:
            cheek = frame_of(Vector((xw, bo.st(s0), 4.38)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        else:
            cheek = frame_of(Vector((xw, bo.st(s1), 4.38)), Vector((0, -1, 0)), Vector((0, 0, 1)))
        cf = FM(ctx["acc"], cheek)
        sp.plate(cf, t, [(0.004, 0.004), (L - 0.004, 0.004), (L - 0.004, hz - 0.006), (0.004, hz - 0.006)], -0.004, 0.0, 0.001, "dark")
        for fx in (0.012, L / 2, L - 0.012):
            fastener(ctx, cheek, fx, hz / 2, 0.0)
    # span (left) and flap (right) levers in their own gates
    for xw, word, marks in ((0.165, "SPAN", ("RET", "EXT")), (-0.165, "FLAP", ("0", "15", "30"))):
        g = frame_of(Vector((xw + 0.030, bo.st(6.20), 4.38)), ex, ey)
        gm = FM(ctx["acc"], g)
        gl = card_prism(ctx, g, 0, 0, 0.024, 0.26, 0, 0.022, 0.003, "field")
        gr = card_prism(ctx, g, 0.036, 0, 0.060, 0.26, 0, 0.022, 0.003, "field")
        card_prism(ctx, g, 0.024, 0, 0.036, 0.03, 0, 0.022, 0.0, "field")
        card_prism(ctx, g, 0.024, 0.23, 0.036, 0.26, 0, 0.022, 0.0, "field")
        sa_, sb_ = 0.024 + FLUSH_GAP, 0.036 - FLUSH_GAP  # the slot's floor clear of each cheek
        gm.face([(sa_, 0.03, 0.010), (sb_, 0.03, 0.010), (sb_, 0.23, 0.010), (sa_, 0.23, 0.010)], [cellc(t, "glare")] * 4)
        for j, m_ in enumerate(marks):  # the scale on the gate's left cheek, the pilot's side of the lever: on its
            # right the lever and its grip stood over the marks from his seat
            yy = 0.05 + 0.16 * j / max(1, len(marks) - 1)
            placard(ctx, g, 0.012, yy, 0.022, m_, 0.007)
            gl["items"].append(["line", 0.018, yy, 0.023, yy, 0.0016, [238, 238, 232]])
        placard(ctx, g, 0.012, 0.016, 0.022, word, 0.0075)  # on the gate's aft end, clear of the centre stack
        for fx, fy in ((0.008, 0.008), (0.052, 0.008), (0.008, 0.252), (0.052, 0.252)):
            fastener(ctx, g, fx, fy, 0.022)
        # the lever slides its gate from the first mark (its rest: RET, flaps 0) to the last (EXT, flaps 30), a post
        # and a knob of its own (the kit grip, an instance, could not move with it)
        held = lever_begin(ctx)
        sp.plate(FM(ctx["acc"], g), t, [(0.027, 0.047), (0.033, 0.047), (0.033, 0.053), (0.027, 0.053)], 0.010, 0.085, 0, "edge")
        cylinder(FM(ctx["acc"], g), t, (0.030, 0.050, 0.095), "z", 0.009, 0.010, 20, "keyedge")
        lever_end(ctx, held, "lever_" + word.lower(), g @ Vector((0.030, 0.050, 0.010)), g @ Vector((0.030, 0.210, 0.010)),
                  (g, 0.024, 0.036, 0.03, 0.23, 0.022))
        CONTROLS.append(("lever", g @ Vector((0.03, 0.05, 0.022))))
        PANELS.append((word, g @ Vector((0.03, 0.13, 0.022))))
    GROUPS.append(("throttle_quadrant", Vector((0, bo.st(6.07), 4.44)), 0.42, 1))
    st0 = 6.225
    for title, rows in P2.PEDESTAL:
        h = 0.018 + 0.042 * len(rows) + 0.006 + (GUARD_CLEAR if any(k_ == "gtog" for k_, _ in rows[0]) else 0.0)
        fr = frame_of(Vector((0.20, bo.st(st0 + h), 4.38)), ex, ey)
        panel(ctx, fr, 0.40, h, title, rows)
        st0 += h + 0.004
    GROUPS.append(("pedestal_panels", Vector((0, bo.st(6.39), 4.40)), 0.44, 1))


def caution_panel(ctx, centre_quad):
    """The caution and warning lights: a grid of lenses with their legends on the centre stack's knee."""
    pass


# ---------------------------------------------------------------- materials, run
def trim2_material(tex, stem="trim2"):
    m = bpy.data.materials.new("s2_" + stem)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    def img(name, colour=True):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(str(tex / name))
        # Linear, as the game samples (bilinear, trilinear between mips); REVIEW_INTERP=Cubic gives the old review look
        n.interpolation = __import__("os").environ.get("REVIEW_INTERP", "Linear")
        if not colour:
            n.image.colorspace_settings.name = "Non-Color"
        return n
    b, ao, ms, nm = img(stem + "_b.png"), img(stem + "_ao.png", False), img(stem + "_m.png", False), img(stem + "_n.png", False)
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.inputs["Factor"].default_value = 0.5  # URP's occlusion map darkens indirect light only; Cycles shadows the rest
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
    # the paint's fine grain: the tiling detail, masked to the paint, as URP Lit draws it (albedo x2 in linear: the
    # sRGB 128 neutral is 0.2176 linear, times 4.5948; the detail normal emulated by a bump from its height)
    lay_ = json.loads((tex / "trim2_layout.json").read_text())
    det = lay_.get("detail")
    if det and (tex / "detail_b.png").exists():
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        tiling = det["trim_tiling"] if stem == "trim2" else det["ink_tiling"]
        mp.inputs["Scale"].default_value = (tiling, tiling, 1.0)
        nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])
        db, dh, dm = img("detail_b.png"), img("detail_h.png", False), img(stem + "_dmask.png", False)
        nt.links.new(mp.outputs["Vector"], db.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], dh.inputs["Vector"])
        x2 = nt.nodes.new("ShaderNodeVectorMath")
        x2.operation = "SCALE"
        x2.inputs["Scale"].default_value = 4.5948
        nt.links.new(db.outputs["Color"], x2.inputs[0])
        dmix = nt.nodes.new("ShaderNodeMix")
        dmix.data_type = "RGBA"
        dmix.inputs[6].default_value = (1, 1, 1, 1)
        nt.links.new(dm.outputs["Alpha"], dmix.inputs["Factor"])
        nt.links.new(x2.outputs["Vector"], dmix.inputs[7])
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        nt.links.new(mix.outputs[2], mul.inputs[6])
        nt.links.new(dmix.outputs[2], mul.inputs[7])
        nt.links.new(mul.outputs[2], bsdf.inputs["Base Color"])
        hmask = nt.nodes.new("ShaderNodeMath")
        hmask.operation = "MULTIPLY"
        nt.links.new(dh.outputs["Color"], hmask.inputs[0])
        nt.links.new(dm.outputs["Alpha"], hmask.inputs[1])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Distance"].default_value = det["relief_m_per_unit"] / (40 / 255)
        nt.links.new(hmask.outputs[0], bump.inputs["Height"])
        nt.links.new(nmap.outputs["Normal"], bump.inputs["Normal"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def unity_metal(m):
    """Render-side only: Unity lights a metal from its reflection probe (the sky), so the stock toggles read silver in
    the cockpit; Cycles reflects the dark cabin there instead. The kit's metallic is scaled to 0.35 so its albedo shows
    as the game shows it. The shipped mod binds the stock Switches1 material untouched."""
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    link = next((l for l in nt.links if l.to_socket == bsdf.inputs["Metallic"]), None)
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 0.35
    if link:
        nt.links.new(link.from_socket, mul.inputs[0])
    else:
        mul.inputs[0].default_value = bsdf.inputs["Metallic"].default_value
    nt.links.new(mul.outputs[0], bsdf.inputs["Metallic"])


def red_variant(base):
    """The stock Paintable shader's colour on a guard: Switches1's albedo times guard red."""
    m = base.copy()
    m.name = "s2_switches_red"
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    link = next((l for l in nt.links if l.to_socket == bsdf.inputs["Base Color"]), None)
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    mul.inputs[7].default_value = (0.9, 0.06, 0.04, 1)
    if link:
        nt.links.new(link.from_socket, mul.inputs[6])
    else:
        mul.inputs[6].default_value = (0.5, 0.5, 0.5, 1)
    nt.links.new(mul.outputs[2], bsdf.inputs["Base Color"])
    # the stock kit is dark: lift the paint toward the red the stock guards read at
    bright = nt.nodes.new("ShaderNodeMix")
    bright.data_type, bright.blend_type = "RGBA", "MIX"
    bright.inputs["Factor"].default_value = 0.6
    nt.links.new(mul.outputs[2], bright.inputs[6])
    bright.inputs[7].default_value = (0.45, 0.02, 0.015, 1)
    nt.links.new(bright.outputs[2], bsdf.inputs["Base Color"])
    return m


VIEWS = {"panel": ("pilot", 6, -28, 20), "left": ("pilot", -64, -26, 18), "right": ("pilot", 58, -24, 18),
         "shoulder": (bo.P(6.86, 0.05, 5.22), -16.0, -24.0, 20), "close_left": ("pilot", -78, -40, 38),
         "close_centre": (bo.P(6.70, 0.20, 5.15), 14.0, -42.0, 30)}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--flood", type=float, default=11.2)
    ap.add_argument("--exposure", type=float, default=0.16)
    ap.add_argument("--sun", type=float, default=3.0)
    ap.add_argument("--sky", type=float, default=0.6)
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--suffix", default="")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--crops", default="", help="a folder: render one 900 px close crop per panel group into it")
    ap.add_argument("--checker", action="store_true", help="the trim sheet's albedo swapped for a UV checker")
    ap.add_argument("--proofs", default="", help="a folder: render the phase A proof set into it and stop")
    ap.add_argument("--proof-set", default="all")
    ap.add_argument("--export", default="", help="a folder: save the interior as tools/export_blockout.py reads it (flightdeck.blend, textures/) and stop")
    ap.add_argument("--spec", default="", help="write every card's size and items to this json and stop (the texture pass reads it)")
    args = ap.parse_args(argv)
    # the commander's eye as the game puts it (Debug.CockpitSeat's log line: metres right, up and forward of the
    # pilot's eye in Unity, right being Blender -X, forward Blender -Y); unset, the game's as the prefab's rest pose puts
    # it (1.10 right, 0.12 down, 0.04 forward); "mirror" for the pilot's eye mirrored across the centreline
    import os as _os
    if _os.environ.get("COMMANDER_EYE", "") != "mirror":
        r_, u_, f_ = (float(v) for v in _os.environ.get("COMMANDER_EYE", "1.10,-0.12,0.04").split(","))
        bo.EYE[-1] = bo.EYE[1] + Vector((-r_, -f_, u_))
        print("COMMANDER EYE", tuple(round(c, 4) for c in bo.EYE[-1]))
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    tex = HERE.parents[2] / ".cache" / "art" / "cockpit" / "tex"
    layout_ = json.load(open(tex / "trim2_layout.json"))
    t = sp.Trim(layout_)
    t.cards = {} if args.spec else layout_.get("cards", {})
    t.ink = {} if args.spec else layout_.get("ink", {})
    t.ink_labels = t.ink.get("labels", {})
    relink_textures()
    coll = bpy.data.collections.new("Sample2")
    scene.collection.children.link(coll)
    trim = trim2_material(tex)
    _own.update(t=t, trim=trim)
    ctx = {"t": t, "acc": Acc(), "round": Acc(), "coll": coll, "red": None, "spec": bool(args.spec)}
    shell = O["bo_shell"]
    shell.data.materials.clear()  # today's shell textures back: its faces kept their slot indices
    for s in O["flightdeck_int"].material_slots:
        shell.data.materials.append(s.material)
    shell_materials(shell, O["flightdeck_int"])
    # today's pedestal and throttle housing survive in the kept shell above z 4.42 (blockout.kept_shell keeps faces that
    # high): the new pedestal replaces them
    import bmesh as _bm
    bm_ = _bm.new()
    bm_.from_mesh(shell.data)
    dead = []

    def under_new_console(f, c_):
        # outboard of 1.36 only wholly aft of station 5.72, where the new console's outboard third starts: today's top
        # forward of it (and across its front edge) stays, or the floor under the side pane shows through
        return abs(c_.x) < 1.36 or min((shell.matrix_world @ v.co).y for v in f.verts) + bo.Y0 > 5.72
    for f in bm_.faces:
        c_ = shell.matrix_world @ f.calc_center_median()
        on_pedestal = abs(c_.x) < 0.25 and 5.85 < c_.y + bo.Y0 < 6.60 and 4.20 < c_.z < 4.70
        on_console = 0.84 < abs(c_.x) < 1.60 and 5.38 < c_.y + bo.Y0 < 6.92 and 4.30 < c_.z < 4.62 and under_new_console(f, c_)
        # today's panel's leg, an 8 cm strip from the floor to z 4.40 beside each footwell (its middle under the 4.15
        # blockout.kept_shell keeps): edge-on to the eye in front of the console's inboard wall, it read as a pale blade
        panel_leg = shell.data.materials[f.material_index].name.endswith("cockpit_panel") and 0.40 < abs(c_.x) < 0.86 \
            and 5.40 < c_.y + bo.Y0 < 6.05 and c_.z < 4.42
        # today's rudder pedals (flightdeck.py build_pedals) where the new ones stand: their arms climbed aft from the
        # pedals' middles, in front of the new pedals from the seat, as pale rods
        old_pedal = 0.38 < abs(c_.x) < 0.72 and 5.30 < c_.y + bo.Y0 < 5.56 and 3.80 < c_.z < 4.40
        # today's map light on each side wall (flightdeck_detail.walls): a bare can in the shell's metal, the brightest
        # thing on the dark wall, with no mount and no light in the game
        map_light = shell.data.materials[f.material_index].name.endswith("cockpit_shell") and 1.17 < abs(c_.x) < 1.26 \
            and 6.02 < c_.y + bo.Y0 < 6.09 and 4.89 < c_.z < 4.98
        if on_pedestal or on_console or panel_leg or old_pedal or map_light:
            dead.append(f)
    # today's console furniture straddles the first box's edges (a bracket runs past x 1.60): every face connected to a
    # dead one whose centre stands in the console band out to x 1.70 goes too
    dead_set = set(dead)
    grew = True
    while grew:
        grew = False
        for f in bm_.faces:
            if f in dead_set:
                continue
            c_ = shell.matrix_world @ f.calc_center_median()
            if not (0.84 < abs(c_.x) < 1.70 and 5.38 < c_.y + bo.Y0 < 6.92 and 4.30 < c_.z < 4.62 and under_new_console(f, c_)):
                continue
            if any(g in dead_set for e in f.edges for g in e.link_faces):
                dead_set.add(f)
                grew = True
    dead = list(dead_set)
    _bm.ops.delete(bm_, geom=dead, context="FACES")
    bm_.to_mesh(shell.data)
    bm_.free()
    print("SHELL removed", len(dead), "faces of today's pedestal and console tops")
    # the camera band, BAND_K times today's arc on a BAND_RADIUS cylinder (flightdeck_screen.py; BAND_RADIUS=0 keeps today's), before
    # anything that is placed against it: the hoods run up to its crew face, and nothing may stand behind it
    import flightdeck_screen as band_shape
    band_r = float(_os.environ.get("BAND_RADIUS", "4.5"))
    band_shape.K = float(_os.environ.get("BAND_K", "1.3215"))
    if band_r > 0:
        half, end = band_shape.reshape({n: O.get(n) for n in ("band", "band_bezel", "band_marker", "warning_lenses")}, band_r,
                                       band_shape.K)
        bo.BAND_RADIUS = band_r
        print("BAND radius %.2f m, half arc %.3f m, ends at %.1f deg round its axis (station %.2f)" % (band_r, half, end, band_shape.axis_station(band_r)))
    shell["n_today"] = len(shell.data.polygons)  # the faces shell_close adds close openings: shell_cull keeps them
    shell_close(shell, O["flightdeck_int"])
    shell["n_close"] = len(shell.data.polygons)
    # today's caution, warning and annunciator lenses stood on today's panel and now float over the new bezels; only
    # the two missile warning lamps under the band stay
    wl = O["warning_lenses"]
    bm_ = _bm.new()
    bm_.from_mesh(wl.data)
    stray = [f for f in bm_.faces if (wl.matrix_world @ f.calc_center_median()).z < 4.765]
    _bm.ops.delete(bm_, geom=stray, context="FACES")
    bm_.to_mesh(wl.data)
    bm_.free()
    print("LENSES removed", len(stray))
    glass_fill(O["glass_int"], shell, O["nose"])
    sv = [shell.matrix_world @ v.co for v in shell.data.vertices]
    shell_tree = BVHTree.FromPolygons(sv, [tuple(p.vertices) for p in shell.data.polygons])
    for o in list(bpy.data.collections["Blockout"].objects):
        if o.name.startswith("bo_") and o.name != "bo_shell" and not o.name.startswith("bo_overhead"):
            bpy.data.objects.remove(o)
    displays = main_panel(ctx)
    panel_backing(ctx)
    for strip_args in CAUTION:
        caution_strip(ctx, *strip_args)
    up = overhead(ctx)
    console(ctx, 1, [p for p in P2.LEFT_CONSOLE if not (p[0] in up and ("L", p[0]) in OVERHEAD)])
    console(ctx, -1, [p for p in P2.RIGHT_CONSOLE if not (p[0] in up and ("R", p[0]) in OVERHEAD)])
    window_bezels(ctx)
    pedestal(ctx)
    aft_bulkhead(ctx, shell)
    # the pedals
    for side in (1, -1):
        # the pedals hang from a cross shaft at z 4.29 that runs from the centre console's side (x 0.24) to the side
        # console's inboard face (x 0.86), in a bracket at each end: alone, plates and posts read as tabs in the air
        x0, x1 = 0.24 + FLUSH_GAP, 0.86 - FLUSH_GAP  # the footwell's walls, the centre console's and the side console's
        box(ctx, (side * x0, bo.st(5.425), 4.275), (side * x1, bo.st(5.395), 4.305), top="dark", side="dark")
        for xb in (0.26, 0.84):
            box(ctx, (side * max(x0, xb - 0.02), bo.st(5.44), 4.25), (side * min(x1, xb + 0.02), bo.st(5.375), 4.33), top="dark", side="dark")
        if side == 1:
            pilot_footwell(ctx)
            continue
        for dx in (-0.11, 0.11):
            box(ctx, ((side * 0.55 + dx) - 0.04, bo.st(5.44), 3.85), ((side * 0.55 + dx) + 0.04, bo.st(5.40), 4.07), top="dark", side="dark")
            box(ctx, ((side * 0.55 + dx) - 0.011, bo.st(5.43), 4.07), ((side * 0.55 + dx) + 0.011, bo.st(5.39), 4.29), top="dark", side="dark")
    # the centre console runs on under the centre stack to the panel's backing (station 5.375), floor to 4.36: open,
    # the underside of the panel stood in plain view from the commander's lower eye
    box(ctx, (-0.24, bo.st(5.91), 3.75), (0.24, bo.st(5.375), 4.36), top="dark", side="dark")
    print("GROUPS", sorted({g[0] for g in GROUPS}))
    if args.spec:
        json.dump({"cards": [{"id": c["id"], "w": c["w"], "h": c["h"], "paint": c["paint"], "items": c["items"],
                              "title": c.get("title"), "x0": c["x0"], "y0": c["y0"], "z": c["z"],
                              "frame": [list(r) for r in c["frame"]],  # for legend sizes from the seat
                              "at": [round(v, 3) for v in c["frame"] @ Vector((c["x0"] + c["w"] / 2, c["y0"] + c["h"] / 2, c["z"]))]}
                             for c in CARDS],
                   "fallback_words": sorted(FALLBACK), "key_words": sorted(KEY_WORDS)}, open(args.spec, "w"))
        print("SPEC", len(CARDS), "cards,", sum(len(c["items"]) for c in CARDS), "items,", len(FALLBACK), "fallback words")
        return
    missing = [c["id"] for c in CARDS if c["id"] not in t.cards]
    assert not missing, "cards with no region on the sheet (rerun the spec and texture passes): %s" % missing[:5]
    n_bad = caption_mismatches(HERE.parents[2] / ".cache" / "art" / "cockpit" / "cards_spec.json")
    assert not n_bad, "%d controls whose nearest baked caption is not their own (rerun the spec and texture passes)" % n_bad
    build_card_tops(t)
    print("CARD ISLANDS", ISLANDS_TOUCHING[0], "lettering island pairs touching as baked,", ISLANDS_TOUCHING[1], "as built")
    assert ISLANDS_TOUCHING[1] == 0, "lettering islands touching on a card: their faces share its plane"
    ink_mat = trim2_material(tex, "ink2") if (tex / "ink2_b.png").exists() else trim
    for m_ in {trim, ink_mat}:  # the screws, toggles and lever tips read as Unity's reflection probe shows them
        unity_metal(m_)
    trim_obj = ctx["acc"].build("s2_trim", [trim, ink_mat, frame_metal()[0]], coll)
    tjunctions(trim_obj)
    round_obj = ctx["round"].build("s2_round", [trim], coll)
    lever_faults = lever_slot_faults()
    print("LEVER SLOTS", lever_faults, "vertices of the moving levers under their surface outside their slot over their travel")
    assert not sum(lever_faults.values()), "a moving lever meets the surface it slides on outside its slot"
    for name, (acc_, rest, far, _) in LEVERS.items():  # each its own object, its origin at its rest base
        lo = acc_.build(name, [trim, ink_mat, frame_metal()[0]], coll)
        lo.data.transform(Matrix.Translation(-rest) @ lo.matrix_world)
        lo.matrix_world = Matrix.Translation(rest)
        lo["slide_axis"] = [round(v, 5) for v in (far - rest).normalized()]  # as the wing stages: export_blockout.py
        lo["travel_m"] = round((far - rest).length, 5)  # writes slide_axis_unity, authoring reads both
    import bmesh as _bm2
    bm_ = _bm2.new()
    bm_.from_mesh(round_obj.data)
    _bm2.ops.remove_doubles(bm_, verts=bm_.verts, dist=1e-6)
    bm_.to_mesh(round_obj.data)
    bm_.free()
    round_obj.data.shade_smooth()
    round_obj.data.set_sharp_from_angle(angle=math.radians(50))  # 8-sided barrels and caps shade round; hex nuts stay hex
    # the throttles: the Darkreach's (BDF) stock lever pair by reference, standing in the quadrant's slots, in place of
    # the KR-67's, whose mesh carries its own flat quadrant base that read as a slab under the grips
    thr = []  # the KR-67 pair stays: the game places stock meshes by their own pivots, and the Darkreach pair's is unknown
    for o in thr:
        vs = [o.matrix_world @ v.co for v in o.data.vertices]
        lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
        hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
        target = Vector((0.0, bo.st(6.07), 4.398))
        o.data.transform(Matrix.Translation(target - Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))))
        grip_ends(o)
        for c_ in o.users_collection:
            c_.objects.unlink(o)
        coll.objects.link(o)
    for o in O:
        if o.name.startswith("stockref_Multirole1_throttle"):
            o.hide_render = False
        if o.name.startswith("stockref_Multirole1_joystick") and o.type == "MESH":
            # the stock stick stays whole: its lower shroud (41 mm across at the console top to 32.5 mm under the grip)
            # stands inside the boot (80 to 67 mm across), which hides it at every pixel (c6 boot crop with and without
            # it: max 1 luma apart), so the game uses the stock mesh as it is. STICK_SHROUD=cut takes it off.
            bmj = _bm.new()
            bmj.from_mesh(o.data)
            mw = o.matrix_world
            low = [f for f in bmj.faces if (mw @ f.calc_center_median()).z < 4.405] if __import__("os").environ.get("STICK_SHROUD") == "cut" else []
            _bm.ops.delete(bmj, geom=low, context="FACES")
            bmj.to_mesh(o.data)
            bmj.free()
            print("STICK shroud faces removed", len(low))
    keep = ("band", "band_bezel", "band_marker", "glass_int", "hatch_liner_L", "hatch_liner_R", "warning_lenses")
    for o in bpy.data.collections["Flightdeck"].objects:  # today's interior: only the locked pieces stay
        o.hide_render = o.name not in keep
    screen_mat = sp.screen_material(HERE.parents[2] / ".cache" / "art" / "cockpit" / "sample" / "tex", 1.6)
    # a matte screen face: at 0.08 the glass mirrored the band's housing across the pages, which the game's
    # emissive tac screen doesn't do
    screen_mat.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.45
    for n_ in screen_mat.node_tree.nodes:
        if n_.type == "TEX_IMAGE":
            n_.image = bpy.data.images.load(str(HERE.parents[2] / ".cache" / "art" / "cockpit" / "tex" / "canvas6.png"))
    screens_obj = screens(displays, screen_mat, coll)
    relink_textures()  # the stock throttle's maps, imported after the first relink
    if "bo_overhead" in O:
        O["bo_overhead"].data.materials.clear()
        O["bo_overhead"].data.materials.append(trim)
    # metrics
    eye = bo.EYE[1]

    def view(p):
        az, el = cm.angles_of(p - eye)
        if el > 15:
            return "overhead"
        return "panel" if -45 <= az <= 45 else "left" if az < -45 else "right"
    if __import__("os").environ.get("SHELL_CULL", "1") == "1":
        shell_cull(shell, coll)
    occluders = cm.tree([o for o in list(coll.objects) + [shell] if o.type == "MESH" and o.name != "s2_screens"])

    def visible(p):
        q = p + (eye - p).normalized() * 0.04  # above the tallest control, so a part never hides its own base
        d = q - eye
        return occluders.ray_cast(eye + d.normalized() * 0.03, d.normalized(), d.length - 0.03)[0] is None
    counts = defaultdict(Counter)
    hidden = Counter()
    hidden_at = []
    for kind, p in CONTROLS:
        if visible(p):
            counts[view(p)][kind] += 1
        else:
            hidden[kind] += 1
            az_, el_ = cm.angles_of(p - eye)
            hidden_at.append((kind, round(az_, 1), round(el_, 1), round(p.y + bo.Y0, 3), round(p.x, 3), round(p.z, 3)))
    for p in PLACARDS:
        if visible(p):
            counts[view(p)]["placard"] += 1
    for p in FASTENERS:
        if visible(p):
            counts[view(p)]["fastener"] += 1
    for _, p in PANELS:
        if visible(p):
            counts[view(p)]["panel"] += 1
    kit_tris = sum(len(o.data.polygons) for o in coll.objects if o.name.startswith("s2k_"))
    kit_tris = sum(sum(len(pl.vertices) - 2 for pl in o.data.polygons) for o in coll.objects if o.name.startswith("s2k_"))
    own_tris = sum(len(pl.vertices) - 2 for o_ in (trim_obj, round_obj) for pl in o_.data.polygons)
    uniq = sorted({o.data.name for o in coll.objects if o.name.startswith("s2k_")})
    print("STEM TITLES", sum(1 for s_ in STEM_TITLES if s_[1]), "titles had levers over them,",
          sum(1 for s_ in STEM_TITLES if s_[2]), "moved; still under a lever:", [s_[0] for s_ in STEM_TITLES if s_[3]])
    res = {"counts": {v: dict(c) for v, c in counts.items()}, "hidden_controls": dict(hidden), "hidden_at": hidden_at, "kit_instances": sum(1 for o in coll.objects if o.name.startswith("s2k_")),
           "kit_tris": kit_tris, "own_tris": own_tris, "unique_kit_meshes": uniq,
           "shell_tris": sum(len(pl.vertices) - 2 for pl in shell.data.polygons)}
    # the cap's whole count (COCKPIT.md section 6): kit by mesh, own by object, today's shell, the kept band pieces and
    # the stock sticks and throttles placed by reference
    def tris_of(o_):
        return sum(len(pl.vertices) - 2 for pl in o_.data.polygons)
    by_kit = {}
    for o_ in coll.objects:
        if o_.name.startswith("s2k_"):
            k_ = o_.name[4:].split(".")[0]
            n_, s_ = by_kit.get(k_, (0, 0))
            by_kit[k_] = (n_ + 1, s_ + tris_of(o_))
    kept = sum(tris_of(O[n]) for n in ("band", "band_bezel", "band_marker", "glass_int", "hatch_liner_L", "hatch_liner_R", "warning_lenses") if n in O and O[n].type == "MESH")
    stock_ref = sum(tris_of(o_) for o_ in bpy.data.objects if o_.type == "MESH" and not o_.hide_render and (o_.name.startswith("stock_thr") or o_.name.startswith("stockref_Multirole1_joystick")))
    res["tris"] = {"kit": by_kit, "own_trim": tris_of(trim_obj), "own_round": tris_of(round_obj), "shell": res["shell_tris"], "kept": kept,
                   "stock_ref": stock_ref}
    res["tris"]["total"] = kit_tris + own_tris + res["shell_tris"] + kept + stock_ref
    print("TRIS", json.dumps(res["tris"]))
    # what the pilot sees: today's eye grid against this one
    import numpy as np
    vis = [o for o in list(coll.objects) + [shell] + [ob for ob in O if ob.name.startswith("stock_seat") or ob.name.startswith("stockref_")]
           + [O[n] for n in ("band_bezel", "hatch_liner_L", "hatch_liner_R", "warning_lenses")] if o.type == "MESH" and o.name != "s2_screens"]
    cats = {"glass": cm.tree([O["glass_int"]]), "band": cm.tree([O["band"]]), "display": cm.tree([O["s2_screens"]]), "opaque": cm.tree(vis)}
    ext = cm.exterior_trees([O[n] for n in ("nose", "fuselage_F", "nose_hatch_L", "nose_hatch_R", "nose_door_visible")])
    azs, els, grid, covered = cm.eye_grid(eye, cats, *ext)
    today = np.load(HERE / "data" / "today_grid_pilot.npy")
    oa, ob = today[0] | today[1], (grid == "glass") | (grid == "band")
    res["view_cells_lost"] = [(int(j) - 90, int(i) - 45) for i, j in np.argwhere(oa & ~ob)]
    res["view_cells_gained"] = int((ob & ~oa).sum())
    def lifted(q, name):
        return tuple(SCREENS[name][1])
    res["displays_pilot"] = cm.display_rays(eye, [(d[0], d[1], lifted(d[2], d[0]), d[3]) for d in displays if d[0].endswith("pilot") or d[0] in ("engines", "gauges")],
                                            {k: v for k, v in cats.items() if k != "display"})
    json.dump(res, open(out / "s2_metrics.json", "w"), indent=1)
    print("VIEW lost", res["view_cells_lost"][:30], "gained", res["view_cells_gained"])
    for r in res["displays_pilot"]:
        print("DISP", r["name"], r["blocked_of_25"])
    print("S2", json.dumps({k: v for k, v in res.items() if k != "unique_kit_meshes"}), len(uniq))
    if not args.proofs:
        bpy.ops.wm.save_as_mainfile(filepath=str(out / "sample2.blend"), copy=True)
    if args.export:
        export_build(Path(args.export).resolve(), trim_obj, round_obj, coll, shell, screens_obj, tex)
        return
    if args.no_render:
        return
    sp_args = argparse.Namespace(samples=args.samples, exposure=args.exposure, sun=args.sun, sky=args.sky, flood=args.flood)
    sp.rig(sp_args)
    bpy.context.scene.cycles.use_denoising = __import__("os").environ.get("REVIEW_DENOISE", "1") == "1"
    ground_texture()
    if args.checker:
        checker_on(trim)
    if args.proofs:
        import proofs
        G_ = globals()
        G_["ink_islands"] = lambda cid: t.ink.get("islands", {}).get(cid, [])
        proofs.run(G_, Path(args.proofs), args.proof_set)
        return
    for v in [v for v in args.views.split(",") if v]:
        seat, az, el, lens = VIEWS[v]
        loc = bo.EYE[1] if seat == "pilot" else seat
        cam = bo.view_cam("s2_cam_" + v, loc, az, el, lens)
        sp.render(out / ("s2_%s%s.png" % (v, args.suffix)), cam)
    if args.crops:
        crops(Path(args.crops))


def tjunctions(obj):
    """No vertex of the trim mesh lies inside another face's edge: a card top cut round its lettering, a strip against
    the card's bevel, a key frame on a panel, each left a vertex part way along a neighbour's edge, and a rasteriser
    can open a hairline crack there (a dark edge under CODE, across the H of HATCH R). Each such edge is split at that
    vertex's own position; the faces become n-gons with collinear corners, triangulated on export."""
    import bmesh as _bt
    from mathutils.kdtree import KDTree
    bmt = _bt.new()
    bmt.from_mesh(obj.data)
    bmt.verts.ensure_lookup_table()
    bmt.verts.index_update()
    kd = KDTree(len(bmt.verts))
    for v in bmt.verts:
        kd.insert(v.co, v.index)
    kd.balance()
    todo = []
    for e in bmt.edges:
        a, b = e.verts[0].co.copy(), e.verts[1].co.copy()
        ab = b - a
        L2 = ab.length_squared
        if L2 < 1e-12:
            continue
        ends = {e.verts[0].index, e.verts[1].index}
        hits = {}
        for co, idx, _ in kd.find_range((a + b) / 2, L2 ** 0.5 / 2 + 1e-7):
            if idx in ends:
                continue
            f = (co - a).dot(ab) / L2
            if 1e-5 < f < 1 - 1e-5 and (a + ab * f - co).length < 2e-7:
                hits[round(f, 7)] = co.copy()
        if hits:
            todo.append((e, sorted(hits.items())))
    n = 0
    touched = set()
    for e, hits in todo:
        touched |= set(e.link_faces)
        v0, v1, cur, done = e.verts[0], e.verts[1], e, 0.0
        for f, co in hits:
            ne, nv = _bt.utils.edge_split(cur, v0, (f - done) / (1 - done))
            nv.co = co
            cur = next(ed for ed in nv.link_edges if v1 in ed.verts)
            v0, done = nv, f
            n += 1
    # each face that gained a corner part way along an edge is fanned from its middle: triangulated any other way,
    # three of its corners in a row make a triangle of no area, which Unity's importer drops (and counts against the slot)
    poked = [f for f in touched if f.is_valid and len(f.verts) > 3]
    _bt.ops.poke(bmt, faces=poked, center_mode="MEAN_WEIGHTED")
    bmt.to_mesh(obj.data)
    bmt.free()
    print("TJUNCTIONS split", n, "edges at", n, "vertices; fanned", len(poked), "faces from their middles")


def shell_materials(shell, today):
    """The kept shell's faces back on today's materials: the blockout kept them on one slot, so every face drew the
    kit atlas through its shell, panel or console UVs (the streaked roof and pillars). Each face takes the material of
    today's face at the same middle (within 1 mm), from today's flight deck mesh it was cut from."""
    from mathutils.kdtree import KDTree
    tm, sm = today.matrix_world, shell.matrix_world
    kd = KDTree(len(today.data.polygons))
    for pl in today.data.polygons:
        kd.insert(tm @ pl.center, pl.index)
    kd.balance()
    hit = 0
    for pl in shell.data.polygons:
        co, idx, d = kd.find(sm @ pl.center)
        if idx is not None and d < 0.001:
            pl.material_index = today.data.polygons[idx].material_index
            hit += 1
    print("SHELL materials from today's faces", hit, "of", len(shell.data.polygons))


def shell_close(shell, today):
    """Three openings to the outside in the kept shell, found by flightdeck_sightlines.py on the first export and closed here:
    - the aft bulkhead (station 6.95) never had its strip from z 4.681 to 4.815 (0.1.3 lacked it too; the seats'
      headrests hide it from the eye at rest, not from a head turned aft and leaned): filled between its neighbours;
    - the coaming's top over the band, today's cc_cockpit_panel faces aft of station 5.45, went with today's panel in
      blockout.kept_shell, leaving its underside alone, wound downward: the top comes back from today's mesh;
    - the coaming's outboard ends are walls wound toward the windscreen, seen from behind from both seats (the
      commander's eye, 12 cm lower than the pilot's mirrored, looks straight through his): each gets a crew-facing
      back."""
    import bmesh as _bc
    mw = shell.matrix_world
    tw = today.matrix_world
    names = [s.material.name if s.material else "" for s in today.material_slots]
    bo_ = _bc.new()
    bo_.from_mesh(today.data)
    keep = [f for f in bo_.faces if names[f.material_index] == "cc_cockpit_panel"
            and (lambda c, n: c.z > 4.88 and c.y + bo.Y0 > 5.45 and n.z > 0.85)(tw @ f.calc_center_median(), (tw.to_3x3() @ f.normal).normalized())]
    _bc.ops.delete(bo_, geom=[f for f in bo_.faces if f not in set(keep)], context="FACES")
    tmp = bpy.data.meshes.new("coaming_top")
    bo_.to_mesh(tmp)
    bo_.free()
    bm = _bc.new()
    bm.from_mesh(shell.data)
    n_before = len(bm.faces)
    bm.from_mesh(tmp)  # appends: the same local space, slots and UV layers as the shell (both are today's mesh)
    bpy.data.meshes.remove(tmp)
    print("SHELL CLOSE coaming top", len(bm.faces) - n_before, "faces from today's mesh")
    # its aft edge, cut round 0.1.3's tighter screen, ran past the new screen frame's top rail toward the crew over the
    # screen's outer thirds, up to 9 cm of pale panel seen edge-on under the rail: each corner inside the rail's crew
    # edge goes out round the screen's axis to just behind that edge
    import flightdeck_screen as _bs
    ax_y = bo.st(_bs.axis_station(bo.BAND_RADIUS or _bs.R0))
    bz = bpy.data.objects["band_bezel"]
    rail_in = min(math.hypot(w.x, ax_y - w.y) for w in (bz.matrix_world @ v.co for v in bz.data.vertices) if w.z > 4.94) + 0.005
    mw_inv = mw.inverted()
    pulled = 0
    for v in {v for f_ in list(bm.faces)[n_before:] for v in f_.verts}:
        w = mw @ v.co
        r = math.hypot(w.x, ax_y - w.y)
        if r < rail_in:
            v.co = mw_inv @ Vector((w.x * rail_in / r, ax_y - (ax_y - w.y) * rail_in / r, w.z))
            pulled += 1
    print("SHELL CLOSE coaming top corners pulled behind the screen frame's top rail", pulled, "to %.3f m round the axis" % rail_in)
    bm.verts.ensure_lookup_table()
    uv = bm.loops.layers.uv.active

    def wy(v):
        return (mw @ v.co).y

    def wz(v):
        return (mw @ v.co).z
    # the aft bulkhead's opening: its triangle under z 4.681 lacks its partner and the strip on to 4.815 is absent, so
    # the hole runs between the corners (-1.751, 4.681), (1.845, 4.540), (1.751, 4.681), (1.646, 4.815), (-1.646, 4.815)
    # (x, z), mapped on the wall's own UVs carried on from its neighbour under the hole
    wall = [f_ for f_ in bm.faces if all(abs(wy(v) + 15.525) < 0.002 for v in f_.verts)]
    under = next(f_ for f_ in wall if sorted(round(wz(v), 3) for v in f_.verts) == [4.54, 4.54, 4.681])
    (xa, za, ua), (xb, zb, ub), (xc, zc, uc) = [((mw @ l_.vert.co).x, wz(l_.vert), l_[uv].uv.copy()) for l_ in under.loops]
    det = (xb - xa) * (zc - za) - (xc - xa) * (zb - za)

    def uv_at(x, z):  # the neighbour's affine (x, z) -> uv, carried past its edges
        s_ = ((x - xa) * (zc - za) - (xc - xa) * (z - za)) / det
        t_ = ((xb - xa) * (z - za) - (x - xa) * (zb - za)) / det
        return ua + (ub - ua) * s_ + (uc - ua) * t_
    hole = [(-1.751, 4.681), (1.845, 4.540), (1.751, 4.681), (1.646, 4.815), (-1.646, 4.815)]
    inv = mw.inverted()
    f = bm.faces.new([bm.verts.new(inv @ Vector((x, -15.525, z))) for x, z in hole])
    if (mw.to_3x3() @ f.normal).y > 0:
        f.normal_flip()
    f.material_index = under.material_index
    for lp in f.loops:
        w_ = mw @ lp.vert.co
        lp[uv].uv = uv_at(w_.x, w_.z)
    print("SHELL CLOSE aft bulkhead opening", hole)
    # the coaming's outboard end walls facing the windscreen: a back for the crew
    mats = [m.name if m else "" for m in shell.data.materials]
    # (and the shelf they stand on over the outboard modules, which a head lowered and leaned forward sees from under)
    ends = [f_ for f_ in bm.faces if mats[f_.material_index] == "stockref_Matte_black"
            and (lambda c, n: 0.50 < abs(c.x) < 1.30 and -17.40 < c.y < -16.40 and 4.55 < c.z < 4.97 and n.z > -0.5)(
                mw @ f_.calc_center_median(), (mw.to_3x3() @ f_.normal).normalized())]
    backs = []
    for f_ in ends:
        # its own corners (bmesh holds one face per vertex set), 1 mm toward the crew so no depth test ties the two
        g = bm.faces.new([bm.verts.new(v.co - f_.normal * 0.001) for v in reversed(f_.verts)])
        g.material_index = f_.material_index
        for lp, lq in zip(g.loops, reversed(list(f_.loops))):
            lp[uv].uv = lq[uv].uv
        backs.append(g)
    # less what stands behind the band from either seat: the band shows the world there
    backs = carve_band(bm, mw, backs)
    print("SHELL CLOSE coaming end walls backed", len(ends), "->", len(backs), "faces outside the band")
    import flightdeck_screen as band_shape
    ax_y = bo.st(band_shape.axis_station(bo.BAND_RADIUS or band_shape.R0))
    r_b = bo.BAND_RADIUS or band_shape.R0
    # what of today's coaming stands just in front of the screen, inside its arc and under its top edge: its end walls,
    # at the narrower screen's ends, crossed the wider one's ends as a dark wedge from the commander's seat, and
    # down to the displays' tops, a dark blade over the commander's flight display
    half_s = band_shape.ARC0 / 2 * band_shape.K
    front = []
    for f_ in bm.faces:
        c = mw @ f_.calc_center_median()
        rr = math.hypot(c.x, ax_y - c.y)
        if 4.55 < c.z < 4.955 and r_b - 0.12 < rr < r_b - 0.002 and abs(math.atan2(c.x, ax_y - c.y)) * r_b < half_s + 0.02:
            front.append(f_)
    # and any sliver of lining beyond the screen reaching more than 1 cm in front of it by a corner: a long one poked its tip over the commander's flight display as a dark blade; its middle lies
    # beyond the screen, so the test by middles above missed it
    black_ = {i for i, m in enumerate(shell.data.materials) if m and m.name.endswith("Matte_black")}
    for f_ in bm.faces:
        if f_ in front or f_.material_index not in black_ or max(e_.calc_length() for e_ in f_.edges) < 0.4:
            continue
        c = mw @ f_.calc_center_median()
        if math.hypot(c.x, ax_y - c.y) <= r_b:
            continue
        for v_ in f_.verts:
            w = mw @ v_.co
            if (math.hypot(w.x, ax_y - w.y) < r_b - 0.01 and 4.55 < w.z < 4.955
                    and abs(math.atan2(w.x, ax_y - w.y)) * r_b < half_s + 0.02):
                front.append(f_)
                break
    _bc.ops.delete(bm, geom=front, context="FACES")
    print("SHELL CLOSE faces standing in front of the screen removed", len(front))
    # 0.1.3's lower wall bracket beside each side pane's aft end (x 1.42 to 1.52, station 6.67 to 6.70, z 4.69 to
    # 4.77): from the seat leaning in it stood over the aft console's NAV panel; the wall tumbles
    # in above it, so it goes rather than moves, and the grab handle over it stays
    bracket = [f_ for f_ in bm.faces if 1.40 < abs((mw @ f_.calc_center_median()).x) < 1.55
               and -15.84 < (mw @ f_.calc_center_median()).y < -15.74 and 4.66 < (mw @ f_.calc_center_median()).z < 4.80]
    _bc.ops.delete(bm, geom=bracket, context="FACES")
    print("SHELL CLOSE wall brackets over the aft consoles removed", len(bracket), "faces")
    bm.to_mesh(shell.data)
    bm.free()


def behind_band(p):
    """Whether p lies behind the camera band from either seat's eye: the band shows the world through the hidden nose,
    so nothing of ours may stand there (0.1.3's flightdeck.py drops its own frames there for the same reason)."""
    band = bpy.data.objects.get("band")
    if band is None:
        return False
    if "band_tree" not in _occ:
        _occ["band_tree"] = BVHTree.FromPolygons([band.matrix_world @ v.co for v in band.data.vertices],
                                                 [tuple(pl.vertices) for pl in band.data.polygons])
    # from both eyes: the pilot looks across the cockpit through the band's far end at the commander's front corner,
    # and anything put there to close it for the commander's own head blanks that third of the band for the pilot.
    # Its last 20 cm from the far seat give way: there the corner's coaming ends and sill close that seat's own view
    import flightdeck_screen as band_shape
    half = band_shape.ARC0 / 2 * (band_shape.K if bo.BAND_RADIUS else 1.0)
    for e in (bo.EYE[1],):
        # on the sightline through the band, behind it or in front of it: the wider band runs on behind 0.1.3's
        # coaming end walls, and their crew-facing backs stood in front of its ends
        d = p - e
        h = _occ["band_tree"].ray_cast(e, d.normalized(), d.length + 2.0)
        if h[0] is None:
            continue
        far = (p.x < 0) == (e.x > 0)
        r_ = bo.BAND_RADIUS or band_shape.R0
        s = r_ * math.atan2(h[0].x, bo.st(band_shape.axis_station(r_)) - h[0].y)
        if far and abs(s) > half - 0.20:
            continue
        return True
    return False


def carve_band(bm, mw, faces):
    """Cuts the given new faces (a bmesh's, mw its object's matrix, a translation) along each seat's sightlines past
    the band's two ends and deletes the pieces behind the band (behind_band): a closure that runs out past the band's
    end keeps its part outside the band, and the band its view. Returns the faces left."""
    import bmesh as _bk
    band = bpy.data.objects.get("band")
    if band is None or not faces:
        return faces
    bv = [band.matrix_world @ v.co for v in band.data.vertices]
    inv = mw.inverted()
    live = set(faces)
    for e in (bo.EYE[1],):
        for side in (1, -1):
            end = [v for v in bv if abs(v.x - (max if side > 0 else min)(w.x for w in bv)) < 0.003]
            b0, b1 = min(end, key=lambda v: v.z), max(end, key=lambda v: v.z)
            no = (b0 - e).cross(b1 - e).normalized()
            geom = [f for f in live if f.is_valid]
            geom = geom + list({ed for f in geom for ed in f.edges}) + list({v for f in geom for v in f.verts})
            before = set(bm.faces)
            _bk.ops.bisect_plane(bm, geom=geom, plane_co=inv @ e, plane_no=no, dist=1e-6)
            live = {f for f in live if f.is_valid} | (set(bm.faces) - before)
    dead = [f for f in live if f.is_valid and behind_band(mw @ f.calc_center_median())]
    _bk.ops.delete(bm, geom=dead, context="FACES")
    return [f for f in live if f.is_valid]


def glass_fill(glass, shell, nose):
    """The inner glass is the nose's own panes, whole: every cabin-facing face of the nose's glass (the nose itself is
    hidden in cockpit view) takes the place of today's inner panes, smooth shaded, one surface. Today's panes were cut
    to today's panel line, and filling the new, lower panel's bare corners from the nose laid a second, faceted layer
    over parts of the first: seen through the screen, the two read as pale triangles, and cutting them away behind the
    screen left a ragged edge over it from the pilot's seat. The underside of the nose's centre frame strip between the
    windscreen panes, which the shell lacks, joins the shell in its Matte_black slot, as do the frames' bare inner
    faces and a disc behind the aft bulkhead (below)."""
    import bmesh as _bg
    gt = BVHTree.FromPolygons([glass.matrix_world @ v.co for v in glass.data.vertices], [tuple(p.vertices) for p in glass.data.polygons])
    nw = nose.matrix_world
    nnames = [s.material.name if s.material else "" for s in nose.material_slots]
    nt = BVHTree.FromPolygons([nw @ v.co for v in nose.data.vertices], [tuple(p.vertices) for p in nose.data.polygons])
    cabin = Vector((0, -16.2, 4.7))
    panes, frame = [], []
    for p in nose.data.polygons:
        c = nw @ p.center
        n = (nw.to_3x3() @ p.normal).normalized()
        if nnames[p.material_index] == "glass" and n.dot(cabin - c) > 0:  # (glass may stand behind the band: it tints, it hides nothing)
            panes.append(p)
        elif abs(c.x) < 0.06 and c.z > 5.0 and -18.5 < c.y < -17.0 and n.z < -0.5:
            frame.append(p)

    def add(obj, polys, slot, flip=False, carve=False):
        bm = _bg.new()
        bm.from_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        inv = obj.matrix_world.inverted()
        uv0 = next(iter(bm.faces)).loops[0][uv].uv.copy() if uv is not None and len(bm.faces) else None
        new = []
        for p in polys:
            if flip:  # wound to the cabin, 2 mm in so it never ties with the skin in depth
                n = (nw.to_3x3() @ p.normal).normalized()
                ws = [nw @ nose.data.vertices[i].co - n * 0.002 for i in reversed(p.vertices)]
            else:
                ws = [nw @ nose.data.vertices[i].co for i in p.vertices]
            f = bm.faces.new([bm.verts.new(inv @ w) for w in ws])
            f.material_index = slot
            if uv0 is not None:
                for lp in f.loops:
                    lp[uv].uv = uv0
            new.append(f)
        if carve:  # less what stands behind the band from either seat: the band shows the world there
            new = carve_band(bm, obj.matrix_world, new)
        bm.to_mesh(obj.data)
        bm.free()
        return len(new)
    bm = _bg.new()  # today's panes out, the nose's in
    bm.from_mesh(glass.data)
    uvl = bm.loops.layers.uv.active
    keep_uv = next(iter(bm.faces)).loops[0][uvl].uv.copy() if uvl is not None and len(bm.faces) else None
    _bg.ops.delete(bm, geom=list(bm.faces), context="FACES")
    if keep_uv is not None:  # add() takes the new faces' UV from the first face: a seed, taken out after
        seed = bm.faces.new([bm.verts.new((0, 0, 0)), bm.verts.new((0.001, 0, 0)), bm.verts.new((0, 0.001, 0))])
        for lp in seed.loops:
            lp[uvl].uv = keep_uv
    bm.to_mesh(glass.data)
    bm.free()
    add(glass, panes, 0)
    bm = _bg.new()
    bm.from_mesh(glass.data)
    _bg.ops.delete(bm, geom=[f for f in bm.faces if f.calc_area() < 1e-6], context="FACES")
    _bg.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    _bg.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(glass.data)
    bm.free()
    gt = BVHTree.FromPolygons([glass.matrix_world @ v.co for v in glass.data.vertices], [tuple(p.vertices) for p in glass.data.polygons])
    mb = next(i for i, m in enumerate(shell.data.materials) if m and m.name == "stockref_Matte_black")
    add(shell, frame, mb)
    print("GLASS FILL", len(panes), "of the nose's pane faces into glass_int;", len(frame), "centre frame faces into the shell")
    # the window frames' inner faces, which the shell leaves bare round the panes' lower corners: every cabin-facing
    # face of the nose's skin above the consoles with no shell within 3 cm inboard of it joins the shell, dark
    # (the shell alone: a pane inboard of a frame is seen through, so it lines nothing)
    st = BVHTree.FromPolygons([shell.matrix_world @ v.co for v in shell.data.vertices], [tuple(p.vertices) for p in shell.data.polygons])
    # and where the skin is only its outer face (the sills under the side panes), that face turned to the cabin
    lining, backed = [], []
    import flightdeck_screen as band_shape
    ax_y_ = bo.st(band_shape.axis_station(bo.BAND_RADIUS or band_shape.R0))
    r_s = bo.BAND_RADIUS or band_shape.R0
    half_s = band_shape.ARC0 / 2 * (band_shape.K if bo.BAND_RADIUS else 1.0)

    def cabin_side(v):  # on the cabin's side of the screen's cylinder, inside its arc, at its height or under it
        return (math.hypot(v.x, ax_y_ - v.y) < r_s - 0.01 and abs(math.atan2(v.x, ax_y_ - v.y)) * r_s < half_s + 0.05
                and 4.5 < v.z < 4.96)
    # the nose's skin runs on under its own panes: turned in there, it stood as an opaque sheet behind both side panes.
    # A face with the
    # nose's glass within 2 cm either way and an inner pane over it toward the cabin is a pane's, not a sill's (by the
    # nose's glass alone, the frames beside the panes went too, and a moved head looked out past them).
    gi = [p.index for p in nose.data.polygons if nnames[p.material_index] == "glass"]
    ng = BVHTree.FromPolygons([nw @ v.co for v in nose.data.vertices], [tuple(nose.data.polygons[i].vertices) for i in gi])
    gt = BVHTree.FromPolygons([glass.matrix_world @ v.co for v in glass.data.vertices], [tuple(p.vertices) for p in glass.data.polygons])
    for p in nose.data.polygons:
        c = nw @ p.center
        n = (nw.to_3x3() @ p.normal).normalized()
        if nnames[p.material_index] == "glass" or not (-17.6 < c.y < -15.45 and c.z > 3.9) or p in frame:
            continue
        if any(cabin_side(nw @ nose.data.vertices[i].co) for i in p.vertices):
            continue  # a skin face reaching in front of the screen: a long sliver of one stood over the commander's
            # flight display as a dark blade
        inward = n if n.dot(cabin - c) > 0 else -n
        # all of it: at its middle alone, faces half under a pane went, and a moved head looked out past the pane's edge
        if all((ng.ray_cast(q, n, 0.02)[0] is not None or ng.ray_cast(q, -n, 0.02)[0] is not None)
               and gt.ray_cast(q, (cabin - q).normalized(), 0.15)[0] is not None
               for q in [c] + [c.lerp(nw @ nose.data.vertices[i].co, 0.9) for i in p.vertices]):
            continue
        # lined only where the shell stands within 3 cm: a sill set further in leaves a slot past its edge
        if st.ray_cast(c + inward * 0.002, inward, 0.03)[0] is not None:
            continue
        if inward is n:
            lining.append(p)
        else:
            backed.append(p)
    # whole, not carved along the screen's sightlines: carved, the forward corners' lining stood through the screen's
    # far end from the other seat as shards (flightdeck_cut.py cuts what lies behind the screen from the pilot's eye)
    n_l = add(shell, lining, mb)
    n_b = add(shell, backed, mb, flip=True)
    print("GLASS FILL", len(lining), "faces of the nose's skin line the frames,", len(backed), "outer faces turned in;",
          n_l + n_b, "faces")
    # the aft bulkhead's edge: its strips step round the hull's curve and leave slivers to the skin at the corners, so
    # a dark disc the shape of the hull's section stands 1 cm behind it (aft, y -15.515), facing the crew: 1 cm in front
    # it covered the wall, shell_cull took the wall away as unseen, and the game showed the untextured disc
    ring = []
    o_ = Vector((0, -15.515, 3.6))
    for k in range(72):
        a = 2 * math.pi * k / 72
        d = Vector((math.cos(a), 0, math.sin(a)))
        h = nt.ray_cast(o_, d, 5.0)
        if h[0] is not None:
            ring.append(h[0] - d * 0.005)
    bm = _bg.new()
    bm.from_mesh(shell.data)
    inv = shell.matrix_world.inverted()
    f = bm.faces.new([bm.verts.new(inv @ v) for v in ring])
    if (shell.matrix_world.to_3x3() @ f.normal).y > 0:
        f.normal_flip()
    f.material_index = mb
    bm.to_mesh(shell.data)
    bm.free()
    print("GLASS FILL aft disc", len(ring), "corners")


def shell_cull(shell, coll):
    """Today's shell less every face neither crew member can see: each face's middle, corners, edge midpoints and the
    points halfway in are sighted from each seat's eye moved through the whole range the game moves the head (the head
    tracker's box, decomp/CameraCockpitState.cs:227: 0.25 m either side, 0.15 up and down, 0.1 aft to 0.45 forward,
    which holds the keyboard's raise and lean at lines 150, 215 and 233; and the default G sway, 0.15 m at line 211 times
    PlayerSettings.cockpitCamInertia 0.5, on every axis) past everything built, the shell itself and the stock seats,
    as Unity draws them: a face seen from behind is culled, so a ray goes on through it (a sighting that counted it as
    a wall hid floor that the game shows through an inside-out console). A face no ray reaches goes; flightdeck_sightlines.py
    proves the export closed over the same range."""
    import bmesh as _bc
    blockers = [o for o in list(coll.objects) + [shell] + [ob for ob in bpy.data.objects if ob.name.startswith("stock_seat")]
                if o.type == "MESH" and o.name != "s2_screens"]
    # one tree, the shell's faces first so a hit's index under n_shell names the shell face
    dg = bpy.context.evaluated_depsgraph_get()
    tv, tp = [], []
    for o in [shell] + [b for b in blockers if b is not shell]:
        me = o.evaluated_get(dg).to_mesh()
        base = len(tv)
        tv += [o.matrix_world @ v.co for v in me.vertices]
        tp += [[base + i for i in p.vertices] for p in me.polygons]
        o.evaluated_get(dg).to_mesh_clear()
    n_shell = len(shell.data.polygons)
    tree = BVHTree.FromPolygons(tv, tp)
    sway = 0.075
    eyes = []
    # the head's range round the pilot's eye: the sweep casts only to 65 deg each way, and from the eye alone the floor
    # and corners the view's edge shows went unmet and were taken away
    for r in (bo.EYE[1],):
        for x in (-0.25 - sway, 0.0, 0.25 + sway):
            for u in (-0.15 - sway, 0.0, 0.15 + sway):
                for f in (-0.10 - sway, 0.175, 0.45 + sway):
                    off = Vector((-x, -f, u))
                    # a head moved through structure to get there (into the seat, through the roof) is not a seat's view
                    if tree.ray_cast(r, off.normalized(), off.length)[0] is None:
                        eyes.append(r + off)
    swept = set()  # every shell face some look across the game's range meets first from its front (2.5 deg steps)
    for e in eyes:
        for pan in range(-660, 661, 10):
            for tilt in range(-260, 261, 10):
                p_, t_ = math.radians(pan / 4), math.radians(tilt / 4)
                d = Vector((-math.sin(p_) * math.cos(t_), -math.cos(p_) * math.cos(t_), -math.sin(t_)))
                t0 = 0.0
                while True:
                    h = tree.ray_cast(e + d * t0, d, 40.0)
                    if h[0] is None:
                        break
                    if h[1].dot(d) < 0:
                        if h[2] < n_shell:
                            swept.add(h[2])
                        break
                    t0 += h[3] + 0.0005

    def reaches(e, q):
        """whether q is the first face the ray from e meets from its front"""
        d = q - e
        L = d.length
        d /= L
        t0 = 0.0
        while True:
            h = tree.ray_cast(e + d * t0, d, L + 0.01 - t0)
            if h[0] is None or t0 + h[3] >= L - 0.003:
                return True
            if h[1].dot(d) < 0:
                return False
            t0 += h[3] + 0.0005
    mw = shell.matrix_world
    bmc = _bc.new()
    bmc.from_mesh(shell.data)
    bmc.faces.ensure_lookup_table()
    seen = set()
    for f in bmc.faces:
        if f.index in swept:
            seen.add(f)
            continue
        c = mw @ f.calc_center_median()
        vs = [mw @ v.co for v in f.verts]
        # its middle, its corners drawn 2 % in, its edges' midpoints and the points halfway to the middle
        pts = [c] + [c + (v - c) * 0.98 for v in vs] + [c + ((vs[k] + vs[(k + 1) % len(vs)]) / 2 - c) * 0.98 for k in range(len(vs))]
        pts += [c + (v - c) * 0.5 for v in vs] + [c + ((vs[k] + vs[(k + 1) % len(vs)]) / 2 - c) * 0.5 for k in range(len(vs))]
        if any(reaches(e, q) for e in eyes for q in pts):
            seen.add(f)
    # and every face touching a seen one: a sighting by points and steps can miss the sliver of a face that shows past
    # an edge, and the outside would show through it
    ring = {g for f in seen for e_ in f.edges for g in e_.link_faces}
    # the faces shell_close added stay whatever the sighting says; the nose's faces glass_fill added go like today's
    n_close = shell.get("n_close", len(bmc.faces))
    dead = [f for f in bmc.faces if f not in seen and f not in ring and not (shell.get("n_today", 0) <= f.index < n_close)]
    n0 = sum(len(f.verts) - 2 for f in bmc.faces)
    _bc.ops.delete(bmc, geom=dead, context="FACES")
    # no merging of coplanar neighbours: on today's floor it joined faces into metre-wide ones whose corner UVs ran a
    # strip of the atlas one way and stood still the other, and the game drew the floor as long streaks
    bmc.to_mesh(shell.data)
    bmc.free()
    print("SHELL CULL", len(dead), "faces unseen from both seats;", n0, "to", sum(len(pl.vertices) - 2 for pl in shell.data.polygons), "triangles")


EXPORT_NAMES = {"s2_trim2": "Centurion_cockpit_trim", "s2_trim": "Centurion_cockpit_trim", "s2_ink2": "Centurion_cockpit_ink", "cc_cockpit_kit": "Centurion_cockpit_kit",
                "cc_cockpit_panel": "Centurion_cockpit_panel", "cc_cockpit_shell": "Centurion_cockpit_shell",
                "cc_cockpit_console": "Centurion_cockpit_console", "cc_band_review": "Centurion_band", "cc_marker_review": "Centurion_band_marker",
                "cc_glass_review": "canopy_int", "cc_display_review": "tacScreenDisplay"}
EXPORT_TEXTURES = {"trim2_b.png": "cockpit_trim_b.png", "trim2_m.png": "cockpit_trim_m.png", "trim2_n.png": "cockpit_trim_n.png",
                   "trim2_ao.png": "cockpit_trim_ao.png", "ink2_b.png": "cockpit_ink_b.png", "ink2_m.png": "cockpit_ink_m.png",
                   "ink2_n.png": "cockpit_ink_n.png", "ink2_ao.png": "cockpit_ink_ao.png", "detail_b.png": "cockpit_detail_b.png",
                   "detail_n.png": "cockpit_detail_n.png", "trim2_dmask.png": "cockpit_trim_dmask.png",
                   "band2.png": "cockpit_band.png", "marker2.png": "cockpit_marker.png", "glass2.png": "cockpit_glass.png"}
KEPT_TEXTURES = ("cockpit_panel_b.png",
                 "cockpit_panel_m.png", "cockpit_panel_n.png", "cockpit_panel_ao.png", "cockpit_console_b.png", "cockpit_console_m.png",
                 "cockpit_console_n.png", "cockpit_console_ao.png", "cockpit_shell_b.png", "cockpit_shell_m.png", "cockpit_shell_n.png",
                 "cockpit_shell_ao.png")


def export_material_name(m):
    if m is None:
        return None
    n = m.name.split(".")[0]
    if n in EXPORT_NAMES:
        return EXPORT_NAMES[n]
    return n[len("stockref_"):] if n.startswith("stockref_") else n


def close_backs(deck, kept, with_stock):
    """Every face of the deck that a seat's eye meets from behind, with an opaque face beyond it, gets a twin
    turned the other way: the game culls the back, so the eye saw into the part (the instrument housings' open
    undersides and braces over the footwells, the forward corners' end walls). The same
    rays as flightdeck_seeinto.py, the faults flightdeck_sightlines.py counts as 'into'."""
    import bmesh as _bk
    import flightdeck_seeinto as seeinto
    mw = deck.matrix_world
    vs = [mw @ v.co for v in deck.data.vertices]
    ps = [list(p.vertices) for p in deck.data.polygons]
    owner = ["flightdeck_int"] * len(ps)
    stock = [o for o in bpy.data.objects if with_stock and o.type == "MESH" and (o.name.startswith("stock_seat")
             or o.name.startswith("stockref_Multirole1_joystick") or o.name.startswith("stockref_Multirole1_throttle"))]
    for o in kept + stock:  # the game draws the stock seats, sticks and throttles too: a part seen past them counts
        b = len(vs)
        vs += [o.matrix_world @ v.co for v in o.data.vertices]
        ps += [[b + i for i in p.vertices] for p in o.data.polygons]
        owner += [o.name] * len(o.data.polygons)
    tree = BVHTree.FromPolygons(vs, ps)
    n_deck = len(deck.data.polygons)
    hit = set()
    for e in (bo.EYE[1],):
        for i in range(361):
            for j in range(141):
                d = seeinto.direction(-90 + 0.5 * i, -10 + 0.5 * j)
                o_, first = e, None
                while True:
                    h = tree.ray_cast(o_, d, 40.0)
                    if h[0] is None or (owner[h[2]] in seeinto.GLASS and first is None):
                        break  # out, or through glass (beyond it is outside the cabin)
                    if owner[h[2]] not in seeinto.GLASS and h[1].dot(d) < 0:
                        if first is not None and (h[0] - first_at).length > seeinto.CAVITY:
                            hit.add(first)
                        break
                    if first is None and owner[h[2]] not in seeinto.GLASS and not owner[h[2]].startswith("stock"):
                        first, first_at = h[2], h[0]
                    o_ = h[0] + d * 0.0005
    hit = sorted(i for i in hit if i < n_deck)
    bm = _bk.new()
    bm.from_mesh(deck.data)
    bm.normal_update()  # from_mesh leaves face normals unset: the twins sat on their faces
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.active
    for f in [bm.faces[i] for i in hit]:
        # 0.1 mm behind the face: coincident, a ray cast met either one first from either side; at 0.5 mm a ray grazing
        # a long sliver met the twin off its edge (the game culls one of the pair from each side, so they never fight)
        nf = bm.faces.new([bm.verts.new(v.co - f.normal * 0.0001) for v in reversed(f.verts)])
        # the face's own finish on its back: in flat black the housings' undersides read as bare plates
        nf.material_index = f.material_index
        if uv is not None:
            for lp, src in zip(nf.loops, reversed(f.loops)):
                lp[uv].uv = src[uv].uv
    bm.to_mesh(deck.data)
    bm.free()
    print("EXPORT backs closed", len(hit), "faces seen from behind with a part beyond them")


def export_build(dest, trim_obj, round_obj, coll, shell, screens_obj, tex):
    """The interior as tools/export_blockout.py reads a blend (flightdeck.py's save_export_blend contract): a
    "Centurion" collection holding flightdeck_int (the trim and round meshes, our knobs, the shell, all joined, its
    origin the deck's as today), the kept pieces (band, band_bezel, band_marker, glass_int, the hatch liners,
    warning_lenses), tacScreen (the displays less the wing display, which the plugin's canvas draws), the stock pivots
    (stick_L, stick_R, throttle_1, throttle_2) and wing_display (moved onto this panel's wing display, square to its
    glass); empty Colliders and LOD1 children; the maps named in the scene's m4_textures, copied to textures/."""
    import shutil
    import bmesh as _be
    repo = HERE.parents[2]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "textures").mkdir(exist_ok=True)
    old = O["flightdeck_int"]
    root_loc = old.matrix_world.translation.copy()
    kept = [O[n] for n in ("band", "band_bezel", "band_marker", "glass_int", "hatch_liner_L", "hatch_liner_R", "warning_lenses")]
    pivots = [O[n] for n in ("stick_L", "stick_R", "throttle_1", "throttle_2", "wing_display")]
    lamp_housings_out(O["band_bezel"])
    lamp_housings_out(O["warning_lenses"])  # their lenses, on the housings' faces, with them
    # the screen frame's top chamfer in the frame's own flat grey: on the 0.1.3 panel atlas it ran across a worn-edge
    # strip whose smoothness steps between 0.30 and 0.53 every centimetre or two, which direct sun broke into a sparkle
    bz = O["band_bezel"]
    metal, (fu, fv) = frame_metal()
    metal_i = [s_.material for s_ in bz.material_slots].index(metal)
    bzw, bz_uv = bz.matrix_world, bz.data.uv_layers.active.data
    chamfer = [p_ for p_ in bz.data.polygons if (bzw.to_3x3() @ p_.normal).normalized().z > 0.5 and (bzw @ p_.center).z > 4.965]
    for p_ in chamfer:
        p_.material_index = metal_i
        for k_, li in enumerate(p_.loop_indices):
            bz_uv[li].uv = (fu + (0.002 if k_ in (1, 2) else -0.002), fv + (0.002 if k_ >= 2 else -0.002))
    print("BEZEL TOP chamfer faces on the frame metal", len(chamfer), "z %.3f..%.3f" % (
        min((bzw @ p_.center).z for p_ in chamfer), max((bzw @ p_.center).z for p_ in chamfer)))
    levers = [O[n] for n in LEVERS]  # the moving levers: their own parts, out of the joined interior
    for o in levers:
        while len(o.data.uv_layers) > 1:
            o.data.uv_layers.remove(o.data.uv_layers[-1])
        if o.data.uv_layers:
            o.data.uv_layers[0].name = "UVMap"
    kept = kept + levers
    world = {o.name: o.matrix_world.copy() for o in kept + pivots}
    # the joined interior: every mesh that is ours, each in world space, one UV layer named UVMap
    parts = [trim_obj, round_obj, shell] + [o for o in coll.objects if o.name.startswith("s2k_")]
    copies = []
    for o in parts:
        c = o.copy()
        c.data = o.data.copy()
        c.data.transform(o.matrix_world)
        c.matrix_world = Matrix.Identity(4)
        while len(c.data.uv_layers) > 1:
            c.data.uv_layers.remove(c.data.uv_layers[-1])
        if c.data.uv_layers:
            c.data.uv_layers[0].name = "UVMap"
        for slot in c.material_slots:
            if slot.link == "OBJECT":
                m_ = slot.material
                slot.link = "DATA"
                slot.material = m_
        bpy.context.scene.collection.objects.link(c)
        copies.append(c)
        if o is shell:
            from collections import Counter as _C
            print("EXPORT shell slots", [m.name if m else None for m in c.data.materials], dict(_C(pl.material_index for pl in c.data.polygons)))
    with bpy.context.temp_override(active_object=copies[0], selected_editable_objects=copies, object=copies[0]):
        bpy.ops.object.join()
    deck = copies[0]
    old.name = "flightdeck_int_0_1_3"
    deck.name = "flightdeck_int"
    deck.data.name = "flightdeck_int"
    deck.data.transform(Matrix.Translation(-root_loc))
    deck.matrix_world = Matrix.Translation(root_loc)
    # faces of no area (a chamfer of zero width, a slot end's bevel) and the triangles of no area that fanning or
    # triangulation would leave: dissolved, so Unity's importer drops nothing and every slot keeps its count
    bmz = _be.new()
    bmz.from_mesh(deck.data)
    _be.ops.triangulate(bmz, faces=bmz.faces, quad_method="BEAUTY", ngon_method="BEAUTY")
    zero = [f for f in bmz.faces if f.calc_area() < 1e-10]
    _be.ops.delete(bmz, geom=zero, context="FACES_ONLY")
    bmz.to_mesh(deck.data)
    bmz.free()
    print("EXPORT removed", len(zero), "triangles of no area")
    for _ in range(2):  # again over the twins: a ray grazing a twin's edge, 0.1 mm off its face, met the next face in.
        # The stock seats, sticks and throttles stand differently in this scene than as the game (and flightdeck_sightlines.py)
        # places them: flightdeck_seeinto.py --close finishes on the exported blend with those.
        close_backs(deck, kept, False)
    # the displays: the wing display's face off tacScreen (its dark glass stays in the bezel under the plugin's canvas)
    scr = screens_obj.copy()
    scr.data = screens_obj.data.copy()
    bpy.context.scene.collection.objects.link(scr)
    bme = _be.new()
    bme.from_mesh(scr.data)
    wing_quad = [Vector(v) for v in SCREENS["wing_pilot"][1]]
    wc = sum(wing_quad, Vector()) / 4
    _be.ops.delete(bme, geom=[f for f in bme.faces if (f.calc_center_median() - wc).length < 0.03], context="FACES")
    bme.to_mesh(scr.data)
    bme.free()
    scr.data.transform(Matrix.Translation(-root_loc))
    O["tacScreen"].name = "tacScreen_0_1_3"
    scr.name = "tacScreen"
    scr.data.name = "tacScreen"
    # the export collection (the blockout's own "Centurion", the exterior, renamed out of the way first)
    for c_ in bpy.data.collections:
        if c_.name in ("Centurion", "Colliders", "LOD1"):
            c_.name = "blockout_" + c_.name
    ex = bpy.data.collections.new("Centurion")
    bpy.context.scene.collection.children.link(ex)
    for name in ("Colliders", "LOD1"):
        ex.children.link(bpy.data.collections.new(name))
    for o in [deck, scr] + kept + pivots:
        for c_ in list(o.users_collection):
            c_.objects.unlink(o)
        ex.objects.link(o)
    for o in kept + pivots:
        o.parent = deck
        o.matrix_parent_inverse.identity()
        o.matrix_world = world[o.name]
    scr.parent = deck
    scr.matrix_parent_inverse.identity()
    scr.matrix_world = Matrix.Translation(root_loc)
    # the wing display's pivot on this panel's wing display: x the crew's left (flightdeck.py's convention), z up its glass
    bl, br, tr, tl = wing_quad
    right = (br - bl).normalized()
    up = tl - bl
    up = (up - right * up.dot(right)).normalized()
    xa, za = -right, up
    m3 = Matrix((xa, za.cross(xa), za)).transposed()
    wd = O["wing_display"]
    wd.matrix_world = Matrix.Translation(wc + right.cross(up).normalized() * 0.0005) @ m3.to_4x4()
    # 7.5 mm in from the page quad all round: at 1.5 mm the plugin's readout along the canvas's foot ran under the
    # bezel's lip from the seat; the tac screen's pages keep about that margin in their glass
    wd["canvas_w"], wd["canvas_h"] = (br - bl).length - 0.015, (tl - bl).length - 0.015
    # the wing display's glass, black, on the page quad the bezel frames and a quarter millimetre in front of the
    # module's face (the canvas stands 0.5 mm out): without it the page drew on the module's painted face, which sun and
    # night vision lift to grey round the outline; a ground on the canvas, 7.5 mm inside the quad, left that face
    # showing round it. Matte_black, the stock displays' surrounds
    nrm_ = right.cross(up).normalized()
    slot_ = next((k for k, s_ in enumerate(deck.material_slots) if s_.material and s_.material.name.endswith("Matte_black")), None)
    assert slot_ is not None, "no Matte_black slot on the deck for the wing display's glass"
    bmw = _be.new()
    bmw.from_mesh(deck.data)
    fw = bmw.faces.new([bmw.verts.new(v + nrm_ * 0.00025 - root_loc) for v in (bl, br, tr, tl)])
    fw.material_index = slot_
    fw.normal_update()
    if fw.normal.dot(nrm_) < 0:
        fw.normal_flip()
    bmw.to_mesh(deck.data)
    bmw.free()
    # material names as authoring's slots know them
    for o in [deck] + kept:
        for slot in o.material_slots:
            if slot.link == "OBJECT":
                m_ = slot.material
                slot.link = "DATA"
                slot.material = m_
        for k, m in enumerate(o.data.materials):
            if m is not None:
                nm = export_material_name(m)
                if m.name != nm:
                    m2 = bpy.data.materials.get(nm) or m.copy()
                    m2.name = nm
                    o.data.materials[k] = m2
    scr.data.materials.clear()
    scr.data.materials.append(bpy.data.materials.get("tacScreenDisplay") or bpy.data.materials.new("tacScreenDisplay"))
    # everything else goes
    keep = {deck, scr} | set(kept) | set(pivots)
    for o in list(bpy.data.objects):
        if o not in keep:
            bpy.data.objects.remove(o)
    for c_ in list(bpy.data.collections):
        if c_.name not in ("Centurion", "Colliders", "LOD1"):
            bpy.data.collections.remove(c_)
    # the maps
    names = []
    for src, dst in EXPORT_TEXTURES.items():
        shutil.copyfile(tex / src, dest / "textures" / dst)
        names.append(dst)
    old_tex = repo / "art" / "export_cockpit" / "textures"
    for n in KEPT_TEXTURES:
        shutil.copyfile(old_tex / n, dest / "textures" / n)
        names.append(n)
    bpy.context.scene["m4_textures"] = sorted(names)
    # the paint's grain detail tiles this many times per UV unit of the trim sheet (flightdeck_textures.detail_maps)
    deck["detail_tiling"] = float(json.loads((tex / "trim2_layout.json").read_text())["detail"]["trim_tiling"])
    lay = json.loads((tex / "trim2_layout.json").read_text())
    (dest / "detail.json").write_text(json.dumps({"trim_tiling": lay["detail"]["trim_tiling"], "relief_m_per_unit": lay["detail"]["relief_m_per_unit"]}))
    # Unity's importer drops triangles of no area and then finds a slot short: count them as it will triangulate
    bmd = _be.new()
    bmd.from_mesh(deck.data)
    _be.ops.triangulate(bmd, faces=bmd.faces, quad_method="BEAUTY", ngon_method="BEAUTY")
    flat = sum(1 for f in bmd.faces if f.calc_area() < 1e-10)
    bmd.free()
    print("EXPORT triangles of no area in flightdeck_int:", flat)
    tris = sum(len(p.vertices) - 2 for o in [deck, scr] + kept for p in o.data.polygons)
    mats = sorted({m.name for o in [deck, scr] + kept for m in o.data.materials if m})
    bpy.ops.wm.save_as_mainfile(filepath=str(dest / "flightdeck.blend"), check_existing=False)
    print("EXPORT", dest / "flightdeck.blend", "triangles", tris, "materials", mats)


def grip_ends(o):
    """The stock throttle's grips: each knurled ring maps to the atlas strip at px 2026 to 2046 by 405 to 520, whose
    middle third (438 to 472) is half again as light as the rest (base 45 to 53 against 32 to 37), so the ring's front
    read as a pale band with hard edges, and its AO falls from 140 to 40 down the strip. The ring's faces keep their u
    and take v from the evenly shaded rows 486 to 496 only (AO 65 to 95); the grips are shaded round, edges over 65 deg kept sharp."""
    me = o.data
    uvl = me.uv_layers.active.data
    moved = 0
    for f in me.polygons:
        c = sum((uvl[li].uv for li in f.loop_indices), Vector((0, 0))) / f.loop_total
        x, y = (c.x % 1.0) * 2048, (1 - c.y) * 1024
        if False:  # the ring keeps its own UVs: the pale square was its loose facets
            for li in f.loop_indices:
                yy = (1 - uvl[li].uv.y) * 1024
                uvl[li].uv.y = 1 - (486 + (yy - 405) * 10 / 115) / 1024
            moved += 1
    if me.has_custom_normals:  # the OBJ's own normals are flat per facet; they would override the smoothing
        with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o]):
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
    import bmesh as _bm
    bmw = _bm.new()  # the export keeps every triangle loose: welded, so smoothing has neighbours to blend
    bmw.from_mesh(me)
    _bm.ops.remove_doubles(bmw, verts=bmw.verts, dist=1e-5)
    bmw.to_mesh(me)
    bmw.free()
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(65))  # the ring's facets meet at 45 deg: they shade round too
    print("GRIP ring faces onto the strip's dark part", o.name, moved)


def relink_textures():
    """Any image whose file is not where the blend says (a host without the source drive) relinks by file name to
    texcache/, which gather_textures.py fills."""
    cache = HERE.parents[2] / ".cache" / "art" / "cockpit" / "texcache"
    for im in bpy.data.images:
        if im.source == "FILE" and not Path(bpy.path.abspath(im.filepath)).exists():
            alt = cache / Path(im.filepath.replace("\\", "/")).name
            if alt.exists():
                im.filepath = str(alt)
                im.reload()


def ground_texture():
    """The ground the windows show: terrain from the in-game Medusa shot (mirrored to tile), so a gap
    beside a console reads as the outside it is."""
    m = bpy.data.materials.get("bo_ground")
    if m is None:
        return
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / 60.0, 1 / 33.0, 1)  # the near ground under the windows: 60 m a tile
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(str(HERE.parents[2] / ".cache" / "art" / "cockpit" / "tex" / "terrain.png"))
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], img.inputs["Vector"])
    nt.links.new(img.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95


def checker_on(trim):
    """A UV checker in place of the trim sheet's albedo: 16 px squares (1 cm at 1,600 px/m), every 128 px a red line
    across U and a green line across V, so stretch and density jumps show at a glance. Normal and AO off."""
    import numpy as np
    w, h = 2048, 1024
    yy, xx = np.mgrid[0:h, 0:w]
    sq = ((xx // 16 + yy // 16) % 2).astype(np.float32)
    rgb = np.stack([0.25 + 0.5 * sq] * 3, -1)
    rgb[(xx % 128) < 3] = (0.9, 0.1, 0.1)
    rgb[(yy % 128) < 3] = (0.1, 0.8, 0.1)
    img = bpy.data.images.new("uv_checker", w, h)
    img.pixels[:] = np.concatenate([rgb[::-1], np.ones((h, w, 1), np.float32)], -1).ravel()
    nt = trim.node_tree
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image and n.image.name.startswith("trim2_b"):
            n.image = img
        if n.type == "TEX_IMAGE" and n.image and (n.image.name.startswith("trim2_ao") or n.image.name.startswith("trim2_n")):
            n.mute = True
    nm = next(n for n in nt.nodes if n.type == "NORMAL_MAP")
    nm.inputs["Strength"].default_value = 0.0


def crops(folder):
    """One square 900 px render per panel group, from the eye of the seat that uses it, framed on the group."""
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    rx, ry = scene.render.resolution_x, scene.render.resolution_y
    scene.render.resolution_x = scene.render.resolution_y = 900
    seen = set()
    listing = []
    for name, centre, size, seat in GROUPS:
        if name in seen:
            continue
        seen.add(name)
        eye = bo.EYE[1] if seat >= 0 else bo.EYE[-1]
        n_, up = GROUP_AXES.get(name, (Vector((0, 0, 1)), Vector((0, -1, 0))))
        toward = (eye - centre).normalized()
        lean = {"stick": (0.25, 0.75, 0.0), "caution_panel": (0.2, 0.8, 0.0)}.get(name.split("console_left_")[-1].split(
            "console_right_")[-1], (0.45, 0.55, 0.0) if name.startswith("console") else (0.65, 0.35, 0.0))
        dirn = (n_ * lean[0] + toward * lean[1] + up * lean[2]).normalized()  # leaning toward the panel, square-on
        dist = size * 0.5 / 0.6 * 1.1  # the group's size across a 30 mm lens's 62 deg field, a margin round it
        pos = centre + dirn * dist
        zc = dirn  # the camera looks down its -Z
        yc = (up - zc * up.dot(zc)).normalized()
        cam = bo.view_cam("crop_cam", pos, 0, 0, 30)
        cam.rotation_euler = Matrix((yc.cross(zc), yc, zc)).transposed().to_euler()
        sp.render(folder / (name + ".png"), cam)
        listing.append({"file": str(folder / (name + ".png")), "group": name, "seat": "pilot" if seat >= 0 else "commander",
                        "centre": list(centre), "cam": list(pos)})
    json.dump(listing, open(folder / "groups.json", "w"), indent=1)
    scene.render.resolution_x, scene.render.resolution_y = rx, ry


def caution_strip(ctx, fr, loc, rail, mine):
    """Twenty-four caution lenses with their legends in an 8 by 3 grid, on a dark strip across the centre stack under
    its two pages, between the seats where both crew see them."""
    t = ctx["t"]
    ys = [p.y for _, _, dq in mine for p in dq]
    top = min(ys) - 0.026 - 0.006
    l0 = min(p.x for p in loc) + rail + 0.006
    l1 = max(p.x for p in loc) - rail - 0.006
    # the stores module's edge hides the strip's outboard end from the pilot's eye: start where both corners show
    while l0 < l1 - 0.2 and not all(seen_from(ctx, bo.EYE[1], fr @ Vector((l0 + 0.004, y, 0.0125)), 0.004)
                                    for y in (0.010, top - 0.004)):
        l0 += 0.004
    print("CAUTION strip from", round(l0 - (min(p.x for p in loc) + rail + 0.006), 3), "m in")
    fm = FM(ctx["acc"], fr)
    sp.plate(fm, t, [(l0, 0.006), (l1, 0.006), (l1, top), (l0, top)], 0.007, 0.012, 0.0015, "dark")
    PANELS.append(("caution", fr @ Vector(((l0 + l1) / 2, top / 2, 0.012))))
    cols, rows_ = 8, 3
    cw, ch = (l1 - l0 - 0.012) / cols, (top - 0.018) / rows_
    for i, word in enumerate(P2.ANNUNCIATORS):
        r, c = divmod(i, cols)
        x = l0 + 0.006 + cw * (c + 0.5)
        y = top - 0.006 - ch * (r + 0.5)
        rect = t.ink_labels.get("caution:" + word, (0, 0, 132, 44))
        asp = (rect[2] - rect[0]) / (rect[3] - rect[1])
        lw = min(cw * 0.88, ch * 0.78 * asp)
        keycap2(ctx, fr, (x, y), lw, lw / asp, 0.012, 0.0145, rect, 0.0008, 0.0005, mat=1)
        CONTROLS.append(("ann", fr @ Vector((x, y, 0.0125))))
    GROUP_AXES["caution_panel"] = (fr.to_3x3().col[2].normalized(), fr.to_3x3().col[1].normalized())
    GROUPS.append(("caution_panel", fr @ Vector(((l0 + l1) / 2, top / 2, 0.012)), (l1 - l0) * 1.3, 1))


def centre_caution(ctx):
    """Twenty-four caution lenses in a 6 x 4 grid with their legends, on the pedestal's front under the centre stack."""
    t = ctx["t"]
    w, h = 0.34, 0.12
    fr = frame_of(Vector((0.17, bo.st(5.905), 4.255)), Vector((-1, 0, 0)), Vector((0, -0.25, 1)))
    if fr.to_3x3().col[2].dot(bo.EYE[1] - fr.translation) < 0:
        fr = frame_of(Vector((0.17, bo.st(5.905), 4.255)), Vector((-1, 0, 0)), Vector((0, 0.25, 1)))
    panel(ctx, fr, w, h, "CAUTION", [])
    GROUPS.append(("caution_panel", fr @ Vector((w / 2, h / 2, 0.01)), 0.40, 1))
    fm = FM(ctx["acc"], fr)
    for i, word in enumerate(P2.ANNUNCIATORS):
        r, c = divmod(i, 6)
        x = 0.022 + c * 0.0505
        y = h - 0.03 - r * 0.022
        rect = t.labels["caution:" + word]
        fm.face([(x - 0.022, y - 0.009, 0.0085), (x + 0.022, y - 0.009, 0.0085), (x + 0.022, y + 0.009, 0.0085), (x - 0.022, y + 0.009, 0.0085)],
                [t.cell(rect, 0, 0), t.cell(rect, 1, 0), t.cell(rect, 1, 1), t.cell(rect, 0, 1)])
        CONTROLS.append(("ann", fr @ Vector((x, y, 0.0085))))
    box_lo = fr @ Vector((0, 0, 0))


if __name__ == "__main__":
    main()
