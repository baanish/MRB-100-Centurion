"""A carded face's paint as a function of position on the face, in metres, so any part of the face can be sampled at
any density with the same grain: the card itself on the trim sheet at the cards' density, and its lettering islands
(each label, each knob scale with the label under it, each group of white ticks) on the ink sheet at 3,750 px/m or
more. The islands are cut out of the same top face, coplanar and on the same paint, so only the lettering gains
resolution and the grain runs on across the cut.

PaintField(card, seed, card_pxm).sample(x0, y1, w_px, h_px, pxm) -> maps for a region whose top-left corner is
(x0, y1) in card metres (y up). islands(card, pxm) -> the island rectangles. ink(card, rect, w_px, h_px, pxm) -> the
lettering's coverage mask over a region. Used by flightdeck_textures.py."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# The paints at 18 % of the stock Darkreach's paint in linear light (field 63 to 24, bezel 39 to 12, dark 50 to 17): the
# stock's own value, lit by the game's sun through the side panes, read sRGB 114 to 142 on these consoles with the sun
# to the left, where the owner chose near-black; 18 % puts that sun at about sRGB 60 and the shade at about 8, under the
# white lettering (INK), which the flood light keeps readable in shade.
PAINT = {"field": ((24, 24, 25), 0.70), "bezel": ((12, 12, 13), 0.56), "dark": ((17, 18, 19), 0.66)}
INK = (228, 228, 224)  # off clip: at 248, flood-lit at night, the game's exposure and bloom haloed it
# the side-console panels whose small scales went too faint at night under the 0.6 flood (MAP,
# AUTOPILOT, COMMS and the far-right console): their ink alone back to near white, the halo-prone pedestal staying at 228
INK_BRIGHT = (246, 246, 242)
BRIGHT_INK_TITLES = {"MAP", "AUTOPILOT", "COMMS 2", "IFF", "DATA LINK", "INT LIGHTS"}
# the far ends of the flood: COMMS 1's knob scales and the commander's side console (TAIL RADAR, BOMB RELEASE and the
# scales aft) lost their ticks at night even at 246, so full white and strokes a third bolder; the pedestal and the
# overhead stand nearest the flood and in the eye's view of it, and their legends haloed at 228
INK_MAX, MAX_WEIGHT = (255, 255, 250), 1.35
MAX_INK_TITLES = {"COMMS 1"}
CONSOLE_TOP_Z = 4.39  # the side consoles' panels lie at z 4.36, the main panel's strips and labels from 4.40
INK_DIM = (205, 205, 201)
# the pedestal, the throttle quadrant's scales and the gear panels: their legends, track lines and the amber banks
# beside them haloed at night (the same GEAR crop: 677 to 691 pixels at luminance 120 or more in the night captures)
DIM_INK_TITLES = {"ENGINE START", "FUEL", "BAYS", "GEAR"}
QUADRANT = (0.25, 4.45)  # |x| under, z under: the untitled cards between the seats (the quadrant's scales)
# the overhead: 15 to 40 cm from the flood, the brightest-lit legends in the cabin, and the ones that smeared most
INK_OVERHEAD = (170, 170, 166)
OVERHEAD_Z = 5.1
# the strips under the main displays and the displays' own labels: their fine legends broke up from the seat
STRIP_Z = (4.39, 4.52)


def ink_level(card):
    """A card's ink colour and stroke weight, by where it stands from the flood."""
    title, at = card.get("title"), card.get("at")
    if at and at[2] > OVERHEAD_Z:
        return INK_OVERHEAD, 1.0
    if title in DIM_INK_TITLES or (at and not title and abs(at[0]) < QUADRANT[0] and at[2] < QUADRANT[1]):
        return INK_DIM, 1.0
    if title in MAX_INK_TITLES or (at and title and at[0] < -0.6 and at[2] < CONSOLE_TOP_Z):
        return INK_MAX, MAX_WEIGHT
    if at and STRIP_Z[0] < at[2] < STRIP_Z[1] and 0.2 < abs(at[0]) < 1.0 and (not title or title.startswith("display:")):
        return INK, MAX_WEIGHT
    return (INK_BRIGHT if title in BRIGHT_INK_TITLES else INK), 1.0


WHITE_LINE = [238, 238, 232]
SUPER = 4
MARGIN = 0.0015  # metres of paint round the lettering inside an island
MIN_STEM = 0.00075  # metres: a legend's thinnest stroke; at 0.5 mm the median stroke was 0.62 screen px at the seat on its
# foreshortened axis and 920 of 1204 legends under a pixel, at 2 to 3 texels on the sheet
STEM_PER_EM = 0.12  # Bahnschrift Bold Condensed's stem width over its font size (measured 0.1225; 0.098 of the text height)


def bold(px):
    f = ImageFont.truetype("bahnschrift.ttf", max(4, int(round(px))))
    f.set_variation_by_name("Bold Condensed")
    return f


class Lattice:
    """Value noise on a lattice `cell` metres apart, smoothstep-interpolated: the same value at a point whatever the
    density it is sampled at."""
    def __init__(self, rng, w, h, cell):
        self.cell = cell
        self.g = rng.standard_normal((int(h / cell) + 4, int(w / cell) + 4)).astype(np.float32)

    def __call__(self, X, Y):
        u, v = X / self.cell + 1, Y / self.cell + 1
        i, j = np.floor(u).astype(int), np.floor(v).astype(int)
        fu, fv = u - i, v - j
        fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
        i = np.clip(i, 0, self.g.shape[1] - 2)
        j = np.clip(j, 0, self.g.shape[0] - 2)
        a, b = self.g[j, i], self.g[j, i + 1]
        c, d = self.g[j + 1, i], self.g[j + 1, i + 1]
        return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + d * fu) * fv


class Worley:
    """Hammered dimples: the distance to the nearest of one random point per `cell` square, 0 at a dimple's centre
    rising to about 1 at its rim."""
    def __init__(self, rng, w, h, cell):
        self.cell = cell
        self.p = rng.random((int(h / cell) + 4, int(w / cell) + 4, 2)).astype(np.float32)

    def __call__(self, X, Y):
        u, v = X / self.cell + 1, Y / self.cell + 1
        i, j = np.floor(u).astype(int), np.floor(v).astype(int)
        best = np.full(X.shape, 9.0, np.float32)
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                ii = np.clip(i + di, 0, self.p.shape[1] - 1)
                jj = np.clip(j + dj, 0, self.p.shape[0] - 1)
                px, py = ii + self.p[jj, ii, 0], jj + self.p[jj, ii, 1]
                best = np.minimum(best, np.hypot(u - px, v - py))
        return np.clip(best / 0.75, 0, 1)


class PaintField:
    def __init__(self, card, seed, card_pxm):
        self.c = card
        rng = np.random.default_rng(seed)
        w, h = card["w"], card["h"]
        self.base, self.rough = PAINT[card["paint"]]
        # the grain's finest features span 1.2 of the card's texels (1 mm at 1,200 px/m), the stock hammered paint's
        # 2 px at 2.7 px/mm (grain.py)
        g = max(0.0010, 1.2 / card_pxm)
        self.mottle = Lattice(rng, w, h, 0.030)
        self.hammer = Worley(rng, w, h, g * 1.25)
        self.speck = Lattice(rng, w, h, g)
        self.relief = Lattice(rng, w, h, 0.004)
        self.chip = Lattice(rng, w, h, 0.0009)
        self.scuffs = []
        for _ in range(int(w * h * 25) + 1):
            x0, y0 = rng.uniform(0, w), rng.uniform(0, h)
            a, ln = rng.uniform(0, math.pi), rng.uniform(0.004, 0.022)
            self.scuffs.append((x0, y0, x0 + ln * math.cos(a), y0 + ln * math.sin(a), rng.uniform(0.2, 0.45)))
        # the relief's height scale, fixed once at the card's density: the normal's X and Y then span 118 to 137
        # (5th to 95th percentile) wherever the face is sampled
        self.k = 1.0
        ys, xs = np.mgrid[0:max(8, int(h * card_pxm)), 0:max(8, int(w * card_pxm))]
        X, Y = (xs + 0.5) / card_pxm, h - (ys + 0.5) / card_pxm
        hm = self._height(X, Y)
        dx = (hm[:, 2:] - hm[:, :-2]) * card_pxm / 2  # slope, m/m
        dy = (hm[2:, :] - hm[:-2, :]) * card_pxm / 2
        self.k = 0.12 / (np.percentile(np.concatenate([np.abs(dx).ravel(), np.abs(dy).ravel()]), 95) + 1e-9)

    def _height(self, X, Y):  # metres x k
        return self.k * (0.00012 * (1 - self.hammer(X, Y)) + 0.00003 * self.speck(X, Y) + 0.00003 * self.relief(X, Y))

    def sample(self, x0, y1, w_px, h_px, pxm):
        """Maps over a region w_px by h_px at pxm whose top-left corner is (x0, y1) in card metres."""
        ys, xs = np.mgrid[0:h_px, 0:w_px]
        X, Y = x0 + (xs + 0.5) / pxm, y1 - (ys + 0.5) / pxm
        c = self.c
        ham = self.hammer(X, Y)
        col = np.empty((h_px, w_px, 3), np.float32)
        col[:] = np.array(self.base, np.float32) / 255
        # the fine grain is the tiling detail's now (flightdeck_textures.detail_maps); the card keeps a little of its own
        # hammer and a low mottle, so the paint has no broad cloud

        shade = 1 + 0.012 * self.mottle(X, Y) + 0.06 * (ham - 0.5) + 0.03 * self.speck(X, Y)
        col *= shade[..., None]
        height = self._height(X, Y) * pxm / 2  # slope units: central difference = slope
        smooth = np.full((h_px, w_px), 1 - self.rough, np.float32) + 0.04 * (ham - 0.5)
        metal = np.zeros((h_px, w_px), np.float32)
        ao = np.ones((h_px, w_px), np.float32)
        edge = np.minimum(np.minimum(X, c["w"] - X), np.minimum(Y, c["h"] - Y))
        chips = (self.chip(X, Y) > 1.55) & (edge < 0.0025)
        col[chips] = np.array((128, 130, 133), np.float32) / 255
        metal[chips] = 0.6
        ao *= 1 - 0.28 * np.clip(1 - edge / 0.004, 0, 1) ** 2
        # scuffs, faint and fine, drawn in metres
        sc = self._mask(x0, y1, w_px, h_px, pxm, lambda d, P: [d.line(P(s[0], s[1]) + P(s[2], s[3]), fill=int(255 * s[4]),
                                                                     width=max(1, int(0.00025 * pxm * SUPER))) for s in self.scuffs])
        col += 0.015 * sc[..., None]  # as faint on the darker paint as 0.04 was on the stock's
        smooth += 0.06 * sc
        m = {"alb": col, "height": height, "smooth": smooth, "metal": metal, "ao": ao}
        for it in c["items"]:
            self._item(m, it, X, Y, x0, y1, w_px, h_px, pxm)
        return m

    def _mask(self, x0, y1, w_px, h_px, pxm, fn):
        im = Image.new("L", (w_px * SUPER, h_px * SUPER), 0)

        def P(x, y):
            return ((x - x0) * pxm * SUPER, (y1 - y) * pxm * SUPER)
        fn(ImageDraw.Draw(im), P)
        return np.asarray(im.resize((w_px, h_px), Image.LANCZOS), np.float32) / 255

    def _item(self, m, it, X, Y, x0, y1, w_px, h_px, pxm):
        kind = it[0]
        if kind == "ao":  # a control's contact shadow
            d = np.hypot(X - it[1], Y - it[2])
            k = np.where(d < it[3], 1.0, np.clip(1 - (d - it[3]) / 0.0045, 0, 1) ** 1.5)
            m["ao"] *= 1 - 0.38 * k
        elif kind == "aorect":
            dx = np.maximum(np.maximum(it[1] - X, X - it[3]), 0)
            dy = np.maximum(np.maximum(it[2] - Y, Y - it[4]), 0)
            m["ao"] *= 1 - 0.32 * np.clip(1 - np.hypot(dx, dy) / 0.003, 0, 1) ** 1.5
        elif kind == "screwseat":  # the shared head stands on it: a soft seat shadow just round its rim
            d = np.hypot(X - it[1], Y - it[2])
            m["ao"] *= 1 - 0.20 * np.where(d < it[3], 1.0, np.clip(1 - (d - it[3]) / 0.0012, 0, 1) ** 2)
        elif kind == "slot":
            inside = (X >= it[1]) & (X <= it[3]) & (Y >= it[2]) & (Y <= it[4])
            m["alb"][inside] = 0.05
            m["height"][inside] -= 0.001 * pxm / 2
            m["smooth"][inside] = 0.2
            dx = np.maximum(np.maximum(it[1] - X, X - it[3]), 0)
            dy = np.maximum(np.maximum(it[2] - Y, Y - it[4]), 0)
            m["ao"] *= 1 - 0.35 * np.clip(1 - np.hypot(dx, dy) / 0.002, 0, 1)
        elif kind == "hazard":
            bw = it[5]
            band = (X >= it[1]) & (X <= it[3]) & (Y >= it[2]) & (Y <= it[4]) & ~(
                (X > it[1] + bw) & (X < it[3] - bw) & (Y > it[2] + bw) & (Y < it[4] - bw))
            stripe = (np.floor((X + Y) / 0.004).astype(int) % 2) == 0
            m["alb"][band & stripe] = np.array((205, 158, 36), np.float32) / 255
            m["alb"][band & ~stripe] = np.array((22, 22, 22), np.float32) / 255
        elif kind == "line" and list(it[6]) != WHITE_LINE:  # a coloured line (a cut's worn lip): paint, not lettering
            lm = self._mask(x0, y1, w_px, h_px, pxm, lambda d, P: d.line(P(it[1], it[2]) + P(it[3], it[4]), fill=255,
                                                                       width=max(1, int(round(it[5] * pxm * SUPER)))))
            col = np.array(it[6], np.float32) / 255
            m["alb"] = m["alb"] * (1 - lm[..., None]) + col * lm[..., None]
            m["metal"] = np.maximum(m["metal"], 0.6 * lm)


def text_box(it, pxm_ref=10000):
    """A text item's ink box in card metres: (x0, y0, x1, y1)."""
    _, lx, ly, ph, word, maxw = it[:6]
    align = it[6] if len(it) > 6 else "c"
    f = bold(ph * 0.80 * pxm_ref)
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    tw = d.textlength(word, font=f) / pxm_ref
    scale = min(1.0, maxw / tw) if maxw else 1.0
    tw *= scale
    bb = f.getbbox(word)
    th = (bb[3] - bb[1]) / pxm_ref * scale
    x0 = lx - tw / 2 if align == "c" else (lx - tw) if align == "r" else lx
    return (x0, ly - th / 2, x0 + tw, ly + th / 2)


# The legend floor: from the pilot's normal eye at the game's view (2560 x 1440, 50 deg vertical, 1544 px a radian at
# the centre) a legend's letters stand at least LEGEND_FLOOR_PX tall: the stock Darkreach's smallest readable captions
# (ANTI SKID, DE-ICE, EOTS, CHANNEL on its left console, from its seat) measure 9 to 11 px in the same view. Each
# legend under it grows toward it, at most LEGEND_GROW_MAX, as far as it stays on its card's face clear of every other
# item (CLEAR round a control's footprint, where its stem stands over the letters from the seat). The commander's side
# (x under -0.3) is read from his seat and keeps its size.
LEGEND_FLOOR_PX, LEGEND_GROW_MAX, CLEAR, LEGEND_GAP = 9.0, 2.5, 0.002, 0.003
PILOT_EYE = (0.55, -15.925, 5.0)
FOCAL_PX = 720 / math.tan(math.radians(25))


def legend_px(card, it):
    """The legend's letter height in pixels from the pilot's eye, or None where the card is turned from it."""
    F = card.get("frame")
    if not F:
        return None
    x0, y0, x1, y1 = text_box(it)
    lx, ly = card["x0"] + (x0 + x1) / 2, card["y0"] + (y0 + y1) / 2
    p = [F[i][0] * lx + F[i][1] * ly + F[i][2] * card["z"] + F[i][3] for i in range(3)]
    d = [p[i] - PILOT_EYE[i] for i in range(3)]
    L = math.sqrt(sum(v * v for v in d))
    dn = [v / L for v in d]
    up, nrm = [F[i][1] for i in range(3)], [F[i][2] for i in range(3)]
    if -sum(a * b for a, b in zip(nrm, dn)) <= 0.05:
        return None
    k = sum(a * b for a, b in zip(up, dn))
    sq = math.sqrt(sum((up[i] - k * dn[i]) ** 2 for i in range(3)))
    return FOCAL_PX * (y1 - y0) * sq / L


def _item_box(it):
    k = it[0]
    if k == "text":  # LEGEND_GAP clear of another legend, so two never run together as one word
        x0, y0, x1, y1 = text_box(it)
        return (x0 - LEGEND_GAP, y0 - LEGEND_GAP, x1 + LEGEND_GAP, y1 + LEGEND_GAP)
    if k in ("ao", "screwseat"):
        r = it[3] + (CLEAR if k == "ao" else 0.0)
        return (it[1] - r, it[2] - r, it[1] + r, it[2] + r)
    if k == "dial":
        return (it[1] - it[4], it[2] - it[4], it[1] + it[4], it[2] + it[4])
    if k in ("aorect", "slot", "hazard"):
        return (min(it[1], it[3]), min(it[2], it[4]), max(it[1], it[3]), max(it[2], it[4]))
    if k == "line":
        hw = it[5] / 2
        return (min(it[1], it[3]) - hw, min(it[2], it[4]) - hw, max(it[1], it[3]) + hw, max(it[2], it[4]) + hw)
    return None


def grow_legends(spec):
    """Each pilot-side legend under LEGEND_FLOOR_PX grown toward it in place (its size, it[3]); returns (legends
    measured, under the floor before, under it after)."""
    b = 0.0016
    n = before = after = 0
    for card in spec["cards"]:
        at = card.get("at")
        if not card.get("frame") or (at and at[0] < -0.3):
            continue
        items = card["items"]
        for i, it in enumerate(items):
            if it[0] != "text":
                continue
            px = legend_px(card, it)
            if px is None:
                continue
            n += 1
            if px >= LEGEND_FLOOR_PX:
                continue
            before += 1
            others = [bx for j, o in enumerate(items) if j != i for bx in [_item_box(o)] if bx]
            f = min(LEGEND_GROW_MAX, LEGEND_FLOOR_PX * 1.04 / px)  # a little over: the font's whole sizes land under
            while f > 1.0:
                trial = it[:3] + [it[3] * f, it[4], it[5] * f] + it[6:]  # its width allowance grows with it
                x0, y0, x1, y1 = text_box(trial)
                m = b + MARGIN  # its island's margin inside the card too: clipped at the card's edge, a baseline was cut
                if (x0 >= m and y0 >= m and x1 <= card["w"] - m and y1 <= card["h"] - m
                        and not any(x0 < o[2] and o[0] < x1 and y0 < o[3] and o[1] < y1 for o in others)):
                    it[3] *= f
                    it[5] *= f
                    break
                f -= 0.05
            if legend_px(card, it) < LEGEND_FLOOR_PX:
                after += 1
    return n, before, after


def islands(card):
    """The card's lettering islands: each label, each knob scale (merged with any label it touches), each group of
    white ticks, with MARGIN of paint round the ink, clipped to the card's top face, overlaps merged."""
    b = 0.0016  # the plate's bevel: the top face starts there
    rects = []
    for it in card["items"]:
        if it[0] == "text":
            x0, y0, x1, y1 = text_box(it)
        elif it[0] == "dial":
            x0, y0, x1, y1 = it[1] - it[4], it[2] - it[4], it[1] + it[4], it[2] + it[4]
        elif it[0] == "line" and list(it[6]) == WHITE_LINE:
            hw = it[5] / 2
            x0, y0, x1, y1 = min(it[1], it[3]) - hw, min(it[2], it[4]) - hw, max(it[1], it[3]) + hw, max(it[2], it[4]) + hw
        else:
            continue
        r = [max(b, x0 - MARGIN), max(b, y0 - MARGIN), min(card["w"] - b, x1 + MARGIN), min(card["h"] - b, y1 + MARGIN)]
        if r[2] > r[0] and r[3] > r[1]:
            rects.append(r)
    merged = True
    while merged:
        merged = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, c = rects[i], rects[j]
                if a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]:
                    rects[i] = [min(a[0], c[0]), min(a[1], c[1]), max(a[2], c[2]), max(a[3], c[3])]
                    del rects[j]
                    merged = True
                    break
            if merged:
                break
    return rects


def ink(card, x0, y1, w_px, h_px, pxm, weight=1.0):
    """The lettering's coverage over a region (text, knob scales, white ticks), drawn at 4x and filtered down; weight
    scales the ticks' widths and the legends' least stem."""
    im = Image.new("L", (w_px * SUPER, h_px * SUPER), 0)
    d = ImageDraw.Draw(im)

    def P(x, y):
        return ((x - x0) * pxm * SUPER, (y1 - y) * pxm * SUPER)
    for it in card["items"]:
        if it[0] == "dial":
            for i in range(9):
                a = math.radians(225 - 270 * i / 8)
                r0 = it[3] - (0.0006 if i in (0, 8) else 0)
                wd = (0.0009 if i in (0, 8) else 0.0008) * weight * pxm * SUPER
                d.line(P(it[1] + r0 * math.cos(a), it[2] + r0 * math.sin(a)) + P(it[1] + it[4] * math.cos(a), it[2] + it[4] * math.sin(a)),
                       fill=255, width=max(1, int(round(wd))))
        elif it[0] == "line" and list(it[6]) == WHITE_LINE:
            d.line(P(it[1], it[2]) + P(it[3], it[4]), fill=255, width=max(1, int(round(it[5] * weight * pxm * SUPER))))
        elif it[0] == "text":
            bx0, by0, bx1, by1 = text_box(it)
            _, lx, ly, ph, word, maxw = it[:6]
            px = ph * 0.80 * pxm * SUPER
            f = bold(px)
            tw = d.textlength(word, font=f)
            want = (bx1 - bx0) * pxm * SUPER
            if tw > want * 1.001:
                f = bold(px * want / tw)
            # stems at least MIN_STEM, the letters' size kept: Bahnschrift Bold Condensed's stem is about 0.098 of the
            # text height, so a 3 mm legend's was 0.29 mm, 1.2 texels on the ink sheet and under a screen pixel from
            # the seat, and its strokes broke up; the glyphs are stroked out to it instead
            stem = STEM_PER_EM * f.size / (pxm * SUPER)
            sw = int(round(max(0.0, MIN_STEM * weight - stem) / 2 * pxm * SUPER))
            bb = f.getbbox(word, stroke_width=sw)
            X, Y = P(bx0, (by0 + by1) / 2)
            d.text((X - bb[0], Y - (bb[1] + bb[3]) / 2), word, fill=255, font=f, stroke_width=sw, stroke_fill=255)
    return np.asarray(im.resize((w_px, h_px), Image.LANCZOS), np.float32) / 255
