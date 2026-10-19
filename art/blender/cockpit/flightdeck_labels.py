"""The flight deck's legends, scales and placards: flat quads a hair in front of the surfaces they label, on their own
1024 RGBA atlas (Centurion_cockpit_labels: colour, coverage in alpha for a cutout) with an emission map for the
powered legends. Text is far denser here than any PBR atlas could carry it (at least LABEL_MIN_PX_PER_M), so a 6 mm
legend stays readable from the seat.

The builders that place a switch register its legend beside it (Labels.add), so a legend moves with its switch."""

import math

import numpy as np
from mathutils import Vector

from m4 import texture

LABEL_ATLAS = 1024
LABEL_MIN_PX_PER_M = 2048
LABEL_GUTTER = 8  # px between labels: mip levels down to 1/8 stay clean
LABEL_LIFT = 0.0007  # in front of the labelled surface
PLATE_T = 0.0025  # a modelled switch plate's thickness: what it carries stands on its top
LABEL_STRIP = 0.03  # a label wrapped round the panel's cylinder runs in strips this wide
MAX_LABELS = 96  # layout() still has to fit them all on the 1024 atlas at LABEL_MIN_PX_PER_M

WHITE = (0.86, 0.86, 0.82)
YELLOW = (0.86, 0.66, 0.10)
RED = (0.72, 0.08, 0.05)
BLACK = (0.03, 0.03, 0.03)
LIT_GREEN = (0.55, 1.0, 0.62)  # the soft keys' backlit legends
LIT_AMBER = (1.0, 0.62, 0.12)
LIT_DIM = (0.62, 0.64, 0.60)  # a powered legend's colour unlit


class Labels:
    """Collects label quads (text centred at a surface point, facing out along normal, its top toward top), the switch
    plates under them (flightdeck_detail.build_plates models them, flightdeck_paint paints them) and the hoses whose
    corrugations flightdeck_paint draws."""

    def __init__(self):
        self.items = []
        self.plates = []
        self.hoses = []

    def plate(self, centre, normal, top, w, h, kind="module", rgb=None, tol=0.012, cls=None, lift=0.0):
        """A plate w x h centred at a surface point: module (Dzus fasteners at its corners when large enough), round (w
        its diameter), hazard (yellow and black bands) or slot (a recessed lever slot, painted only). cls: the paint class
        of the modelled plate (None: painted only). lift: its base's stand-off from the surface (on a curved one). rgb:
        its paint instead of the plate grey. Returns the projector of a point on the surface onto the plate's top, where
        what it carries stands."""
        n = Vector(normal).normalized()
        t = (Vector(top) - n * Vector(top).dot(n)).normalized()
        self.plates.append({"c": tuple(centre), "n": tuple(n), "t": tuple(t), "w": w, "h": h, "kind": kind,
                            "rgb": None if rgb is None else np.asarray(rgb, float), "tol": tol, "cls": cls, "lift": lift})
        q0 = Vector(centre) + n * (lift + (PLATE_T if cls is not None and kind != "slot" else 0.0))
        return lambda p: Vector(p) + n * (q0 - Vector(p)).dot(n)

    def hose(self, pts, radius):
        self.hoses.append(([tuple(p) for p in pts], radius))

    def add(self, text, centre, normal, top, cap=0.006, rgb=WHITE, plate=None, lit=None, scale=None, width=None,
            lift=LABEL_LIFT, axis=None):
        """cap: cap height in metres. plate: a background colour (a placard) instead of a clear cutout. lit: the
        emission colour of a powered legend. scale: (count, length) for a rotary or linear scale's tick marks drawn
        round the text's centre instead of text. width: a fixed quad width (a row of legends spread over it). lift: how
        far in front of the surface (more on a surface curving toward the reader). axis: (x, y) of a vertical axis the
        quad wraps round at its centre's radius, in strips, for a label on the panel's cylinder."""
        n = Vector(normal).normalized()
        t = (Vector(top) - n * Vector(top).dot(n)).normalized()
        self.items.append({"text": text, "c": Vector(centre), "n": n, "t": t, "cap": cap, "rgb": rgb, "plate": plate,
                           "lit": lit, "scale": scale, "width": width, "lift": lift, "axis": axis})

    def row(self, texts, centres, normal, top, cap=0.005, **kw):
        """One quad over a row of legends, each centred at its own point (the switches they sit under)."""
        a, b = Vector(centres[0]), Vector(centres[-1])
        mid = (a + b) / 2
        axis = kw.get("axis")
        if axis is not None:  # on the cylinder: the row's centre at its points' mean radius, not on their chord
            ax = Vector((axis[0], axis[1], mid.z))
            rc = sum(math.hypot(c[0] - axis[0], c[1] - axis[1]) for c in centres) / len(centres)
            mid = ax + (mid - ax).normalized() * rc
        n = Vector(normal).normalized()
        right = Vector(top).cross(n).normalized()
        offsets = [(Vector(c) - mid).dot(right) for c in centres]
        pitch = min(abs(offsets[i + 1] - offsets[i]) for i in range(len(offsets) - 1)) if len(offsets) > 1 else 0.03
        self.add(list(zip(texts, offsets)), mid, normal, top, cap=cap, width=(max(offsets) - min(offsets)) + pitch, **kw)


def _mask(item, px_per_m):
    """The label's raster (rows bottom-up, 1 = ink) at px_per_m."""
    cap_px = item["cap"] * px_per_m
    unit = cap_px * 1.4  # text_mask's pixels per font unit: about 1.4 cap heights
    if item["scale"]:
        count, length = item["scale"]
        r = length * px_per_m
        size = int(math.ceil(2 * r + 4))
        yy, xx = np.mgrid[0:size, 0:size] + 0.5 - size / 2
        rad, ang = np.hypot(xx, yy), np.degrees(np.arctan2(yy, xx))
        img = np.zeros((size, size))
        for k in range(count):  # a 270 deg dial from lower left round over the top to lower right
            a = 225.0 - 270.0 * k / (count - 1)
            major = k % 2 == 0
            d = np.abs(((ang - a + 180) % 360) - 180) * np.pi / 180 * rad
            inner = r * (0.70 if major else 0.82)
            img = np.maximum(img, np.clip(1.2 - d / max(1.0, 0.035 * r), 0, 1) * (rad > inner) * (rad < r))
        return img
    if isinstance(item["text"], list):  # a row: each legend at its offset
        parts = [(texture.text_mask(t, px_height=unit), off) for t, off in item["text"]]
        w = int(math.ceil(item["width"] * px_per_m))
        h = max(m.shape[0] for m, _ in parts)
        img = np.zeros((h, w))
        for m, off in parts:
            x0 = int(round(w / 2 + off * px_per_m - m.shape[1] / 2))
            y0 = (h - m.shape[0]) // 2
            xs, xe = max(0, x0), min(w, x0 + m.shape[1])
            if xe > xs:
                img[y0:y0 + m.shape[0], xs:xe] = np.maximum(img[y0:y0 + m.shape[0], xs:xe], m[:, xs - x0:xe - x0])
        return img
    img = texture.text_mask(item["text"], px_height=unit)
    if item["plate"] is not None:  # a placard: a border round the text
        pad = int(math.ceil(cap_px * 0.6))
        h, w = img.shape[0] + 2 * pad, img.shape[1] + 2 * pad
        out = np.zeros((h, w))
        out[pad:pad + img.shape[0], pad:pad + img.shape[1]] = img
        b = max(1, int(round(cap_px * 0.12)))
        out[:b], out[-b:], out[:, :b], out[:, -b:] = 1, 1, 1, 1
        img = out
    if item["width"]:
        w = int(math.ceil(item["width"] * px_per_m))
        if w > img.shape[1]:
            pad = np.zeros((img.shape[0], w))
            x0 = (w - img.shape[1]) // 2
            pad[:, x0:x0 + img.shape[1]] = img
            img = pad
    return img


def _shelf_pack(sizes, side, gutter):
    """Place (w, h) rectangles in rows on a side x side canvas, tallest first: their (x, y) or None if they overflow."""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    pos = [None] * len(sizes)
    x = y = row_h = gutter
    for i in order:
        w, h = sizes[i]
        if x + w + gutter > side:
            x, y, row_h = gutter, y + row_h + gutter, gutter
        if w + 2 * gutter > side or y + h + gutter > side:
            return None
        pos[i] = (x, y)
        x += w + gutter
        row_h = max(row_h, h)
    return pos


def layout(labels):
    """The densest px per metre (at least LABEL_MIN_PX_PER_M) at which every label's raster fits the atlas: (density,
    rasters, positions)."""
    if len(labels.items) > MAX_LABELS:
        raise SystemExit(f"{len(labels.items)} label quads, more than MAX_LABELS {MAX_LABELS}")
    best = None
    for density in (2048, 2560, 3072, 3584, 4096, 5120, 6144):
        rasters = [_mask(it, density) for it in labels.items]
        pos = _shelf_pack([(r.shape[1], r.shape[0]) for r in rasters], LABEL_ATLAS, LABEL_GUTTER)
        if pos is None:
            break
        best = (density, rasters, pos)
    if best is None:
        raise SystemExit(f"the labels do not fit a {LABEL_ATLAS} atlas at {LABEL_MIN_PX_PER_M} px/m")
    return best


def build(labels, part, slot, lit_slot):
    """The quads on part (a sf.Part), UV-mapped to their rasters; returns (density, rasters, positions)."""
    density, rasters, pos = layout(labels)
    bm = part.bm
    uv = bm.loops.layers.uv.verify()
    for it, img, (x, y) in zip(labels.items, rasters, pos):
        h, w = img.shape
        right = it["t"].cross(it["n"]).normalized()
        hw, hh = w / density / 2, h / density / 2
        c = it["c"] + it["n"] * it["lift"]
        strips = 1 if it["axis"] is None else max(1, math.ceil(2 * hw / LABEL_STRIP))
        cols = []
        for k in range(strips + 1):
            along = -hw + 2 * hw * k / strips
            col = []
            for up in (-hh, hh):
                p = c + right * along + it["t"] * up
                if it["axis"] is not None:  # back onto the cylinder through the label's centre
                    ax, ay = it["axis"]
                    rc = math.hypot(c.x - ax, c.y - ay)
                    d = Vector((p.x - ax, p.y - ay)).normalized() * rc
                    p = Vector((ax + d.x, ay + d.y, p.z))
                col.append((bm.verts.new(p), (x + w / 2 + along * density) / LABEL_ATLAS, (y + h / 2 + up * density) / LABEL_ATLAS))
            cols.append(col)
        for k in range(strips):
            quad = [cols[k][0], cols[k + 1][0], cols[k + 1][1], cols[k][1]]
            f = bm.faces.new([q[0] for q in quad])
            for loop, q in zip(f.loops, quad):
                loop[uv].uv = (q[1], q[2])
            f.normal_update()
            if f.normal.dot(it["n"]) < 0:
                f.normal_flip()
            part.tag([f], slot if it["lit"] is None else lit_slot, 0)
    part.uv_done = True
    return density, rasters, pos


def paint(labels, rasters, pos, folder):
    """cockpit_labels_b.png (sRGB colour, alpha the cutout) and cockpit_labels_e.png (the powered legends' glow)."""
    S = LABEL_ATLAS
    rgba, emit = np.zeros((S, S, 4)), np.zeros((S, S, 3))
    rgba[..., 0:3] = 0.5
    for it, img, (x, y) in zip(labels.items, rasters, pos):
        h, w = img.shape
        g = LABEL_GUTTER // 2  # the cutout's colour bleeds into the gutter, its alpha stays clear
        ink = np.asarray(it["rgb"], float)
        if it["plate"] is not None:
            block = np.empty((h, w, 3))
            block[:] = it["plate"]
            block = block * (1 - img[..., None]) + ink * img[..., None]
            rgba[y:y + h, x:x + w, 0:3] = block
            rgba[y:y + h, x:x + w, 3] = 1.0
        else:
            rgba[y - g:y + h + g, x - g:x + w + g, 0:3] = ink
            rgba[y:y + h, x:x + w, 3] = img
        if it["lit"] is not None:
            emit[y:y + h, x:x + w] = np.asarray(it["lit"], float) * img[..., None]
    return {"labels": texture.save_image(rgba, folder / "cockpit_labels_b.png", srgb=True),
            "labels_emission": texture.save_image(emit, folder / "cockpit_labels_e.png", srgb=True)}
