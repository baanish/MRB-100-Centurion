"""The second sample's trim sheet: one 2048 x 1024 four-map set in the stock contract, near-black. Surfaces separate by
value, roughness and edge wear as the Darkreach's and Medusa's dark panels do (their atlases: p5 24, p25 54 to 65):
panel plates sRGB 46, title strips and sub-panels 32, bezels 24, structure 56, chamfers worn to 120, white stencils.
Every placard word of flightdeck_panels.py and the caution legends get a cell.

python -I flightdeck_textures.py <out folder>   writes trim2_{b,n,m,ao}.png and trim2_layout.json"""

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flightdeck_panels as panels2  # noqa: E402
from flightdeck_texture_noise import border_mask, noise, scratches  # noqa: E402

W, H = 2048, 2048
STRIPS = {"field": (0, 0, 2048, 288), "dark": (0, 288, 2048, 352), "bezel": (0, 352, 2048, 400),
          "edge": (0, 400, 2048, 424), "side": (0, 424, 2048, 448), "struct": (0, 448, 2048, 512),
          "cable": (0, 512, 2048, 536), "rail": (0, 536, 2048, 560)}
# decals: every label, caution legend, key legend and knob dial, packed in the sheet's lower half and the band under
# the strips. A label is drawn 40 px tall for a placard 8.5 mm tall (4,706 px/m), so it holds its edge at the crops' distance as well as the pilot's
# (1440p at 0.7 m: about 17 screen px); labels and dials sit on a copy of the panel field at its own scale, so they
# carry the panel's grain, value and roughness and show no patch.
DECAL_RECTS = [(0, 1024, 2048, 2048), (0, 560, 2048, 958), (1336, 960, 2048, 1024)]
LABEL_PX, LABEL_M = 40, 0.0085
DIAL_PX, DIAL_M = 128, 0.030
PAD = 8  # px of padding round every decal region, filled from the region's own edge
SPEC = None  # flightdeck_build.py's card spec (json), from the command line
HW = {"fastener": (0, 960, 64, 1024), "cb": (64, 960, 128, 1024), "osb": (1024, 960, 1088, 1024),
      "mark": (1088, 960, 1104, 1024), "cap": (1104, 960, 1168, 1024), "hazard": (128, 960, 384, 992),
      "guard_red": (384, 960, 448, 1024), "lens_amber": (448, 960, 496, 1008), "lens_green": (496, 960, 544, 1008),
      "lens_red": (544, 960, 592, 1008), "lens_white": (592, 960, 640, 1008), "glare": (640, 960, 1024, 1024),
      "keyframe": (1168, 960, 1200, 992), "keyside": (1200, 960, 1232, 992), "keyedge": (1232, 960, 1264, 992),
      "guard_dark": (1264, 960, 1296, 992), "white": (1296, 960, 1328, 992), "guard_cap": (1168, 992, 1232, 1024),
      "pin": (1232, 992, 1264, 1024), "tmetal": (1264, 992, 1296, 1024)}


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    alb = np.zeros((H, W, 3), np.float32)
    height = np.zeros((H, W), np.float32)
    metal = np.zeros((H, W), np.float32)
    smooth = np.full((H, W), 0.3, np.float32)
    ao = np.ones((H, W), np.float32)

    def paint(rect, base, mottle, wear_px, wear_amt, grime, sm, seed, scuffs=0, wear_rgb=(118, 120, 122)):
        x0, y0, x1, y1 = rect
        h, w = y1 - y0, x1 - x0
        n1, n2 = noise(h, w, 96, 5, seed), noise(h, w, 10, 3, seed + 1)
        col = np.array(base, np.float32)[None, None] / 255 * (1 + mottle * n1[..., None] + 0.03 * n2[..., None])
        bm = border_mask(h, w, wear_px)
        chip = (noise(h, w, 5, 2, seed + 2) > 0.45).astype(np.float32)
        wear = np.clip(bm * (0.5 + 0.9 * noise(h, w, 20, 3, seed + 3)), 0, 1) * chip * wear_amt
        gr = np.clip(0.5 + 0.5 * noise(h, w, 160, 4, seed + 4), 0, 1) * grime
        col = col * (1 - 0.3 * gr[..., None])
        col = col * (1 - wear[..., None]) + np.array(wear_rgb, np.float32) / 255 * wear[..., None]
        if scuffs:
            sc = scratches(h, w, scuffs, 70, seed + 5)
            col = col + 0.04 * sc[..., None]  # as faint on the near-black paints as 0.10 was on the stock's
            height[y0:y1, x0:x1] -= 0.12 * sc
        alb[y0:y1, x0:x1] = np.clip(col, 0, 1)
        height[y0:y1, x0:x1] += 0.035 * n2
        metal[y0:y1, x0:x1] = wear * 0.7
        smooth[y0:y1, x0:x1] = np.clip(sm + 0.25 * wear - 0.1 * gr + 0.04 * n1, 0, 1)
        ao[y0:y1, x0:x1] = 1 - 0.4 * bm ** 2 * (wear_amt > 0)

    # flat strips carry no worn border: faces map isotropically and centred, and edge wear lives on the chamfers; the
    # near-black paints at 18 % of the stock's in linear light (flightdeck_cards.PAINT says why)
    paint(STRIPS["field"], (24, 25, 26), 0.03, 10, 0.0, 0.10, 0.30, 11, scuffs=90)
    paint(STRIPS["dark"], (17, 18, 19), 0.03, 8, 0.0, 0.10, 0.25, 21, scuffs=40)
    paint(STRIPS["bezel"], (12, 13, 14), 0.03, 5, 0.0, 0.08, 0.45, 31, scuffs=12)
    paint(STRIPS["side"], (14, 15, 16), 0.03, 4, 0.0, 0.15, 0.22, 41)
    paint(STRIPS["struct"], (74, 74, 72), 0.04, 12, 0.0, 0.2, 0.20, 51, scuffs=60)

    def panel_lines(rect, seam_px, seed):
        """Access-panel joints across a strip every seam_px along U (0.43 m at the 900 px/m the housings map at): a
        2 px groove with a lit lip, and a fastener each side of it at the strip's middle. Faces map the strip's height
        over and over up a wall, so the joints run unbroken up it and the fasteners stand in a column 71 mm apart, as the
        Darkreach's housings carry them (broad surfaces bare, 67 shots)."""
        x0, y0, x1, y1 = rect
        rng = np.random.default_rng(seed)
        yc = (y0 + y1) // 2
        for xs in range(x0 + seam_px // 2, x1, seam_px):
            xs += int(rng.integers(-24, 25))
            alb[y0:y1, xs:xs + 2] *= 0.45
            alb[y0:y1, xs + 2:xs + 3] = np.clip(alb[y0:y1, xs + 2:xs + 3] * 1.35, 0, 1)
            height[y0:y1, xs:xs + 2] -= 0.6
            ao[y0:y1, xs - 2:xs + 4] *= 0.8
            for xf in (xs - 14, xs + 16):  # a Dzus head 6 px (7 mm) across, its slot across it
                yy, xx = np.mgrid[y0:y1, max(x0, xf - 6):min(x1, xf + 7)]
                r = np.hypot(xx - xf, yy - yc)
                head = r <= 3.2
                ring = (r > 3.2) & (r <= 4.4)
                sl = alb[y0:y1, max(x0, xf - 6):min(x1, xf + 7)]
                sl[ring] *= 0.5
                sl[head] = np.array((70, 70, 72)) / 255
                sl[head & (np.abs(yy - yc) < 0.8)] = np.array((30, 30, 31)) / 255
                height[y0:y1, max(x0, xf - 6):min(x1, xf + 7)] += np.where(head, 0.5 * (1 - r / 3.2), 0)
                smooth[y0:y1, max(x0, xf - 6):min(x1, xf + 7)][head] = 0.5
    panel_lines(STRIPS["dark"], 384, 71)
    panel_lines(STRIPS["struct"], 384, 72)
    # structure: a rivet row along each long edge and ribs, in the height
    x0, y0, x1, y1 = STRIPS["struct"]
    pass
    # chamfer: worn through
    x0, y0, x1, y1 = STRIPS["edge"]
    t = 1 - np.abs(np.linspace(-1, 1, y1 - y0, dtype=np.float32))
    chips = (noise(y1 - y0, x1 - x0, 3, 1, 61) > 0.95).astype(np.float32)
    chips = (noise(y1 - y0, x1 - x0, 3, 1, 61) > 0.85).astype(np.float32)
    crest = np.clip((t[:, None] - 0.62) / 0.2, 0, 1) * np.ones((1, x1 - x0), np.float32) * 0.7  # the worn crest
    wear = np.maximum(chips * (t[:, None] > 0.45), crest)
    # the worn crest dull: bright and a pixel wide, it drew jagged pale seams in game
    alb[y0:y1, x0:x1] = (np.array((41, 41, 42)) / 255)[None, None] * (1 - wear[..., None]) + (np.array((90, 91, 93)) / 255) * wear[..., None]
    metal[y0:y1, x0:x1] = 0.8 * wear
    smooth[y0:y1, x0:x1] = 0.3 + 0.35 * wear
    # cable: black rubber, ribs every 6 px
    x0, y0, x1, y1 = STRIPS["cable"]
    alb[y0:y1, x0:x1] = 18 / 255
    for x in range(x0, x1, 6):
        alb[y0:y1, x:x + 2] = 30 / 255
        height[y0:y1, x:x + 2] = 0.5
    smooth[y0:y1, x0:x1] = 0.45
    # Dzus rail: dark grey strip with a slotted fastener every 48 px
    x0, y0, x1, y1 = STRIPS["rail"]
    alb[y0:y1, x0:x1] = 40 / 255
    for x in range(x0 + 24, x1, 48):
        alb[y0 + 6:y1 - 6, x - 6:x + 6] = 70 / 255
        alb[(y0 + y1) // 2 - 1:(y0 + y1) // 2 + 1, x - 5:x + 5] = 12 / 255
        height[y0 + 6:y1 - 6, x - 6:x + 6] = 0.6

    # decals on the trim sheet: every carded face's paint (flightdeck_cards.PaintField, generated in the face's own metres),
    # and label cells for words placed where no card is. The lettering, keys and caution lenses go to the ink sheet.
    rng = np.random.default_rng(7)
    spec = json.load(open(SPEC)) if SPEC else {"cards": [], "fallback_words": []}
    import flightdeck_cards as cardbake2
    grown = cardbake2.grow_legends(spec)
    print("LEGENDS %d from the pilot's eye, under %.0f px: %d before growing, %d after" % (
        grown[0], cardbake2.LEGEND_FLOOR_PX, grown[1], grown[2]))
    json.dump(spec, open(out / "cards_grown.json", "w"))  # the sizes as drawn, for measuring them

    def field_copy(x, y, w, h, pxm):
        k = 1500.0 / pxm
        fx0, fy0, fx1, fy1 = STRIPS["field"]
        sw, sh = max(2, int(round(w * k))), max(2, int(round(h * k)))
        sx, sy = int(rng.integers(fx0, fx1 - sw)), int(rng.integers(fy0 + 16, fy1 - 16 - sh))

        def rs(a):
            return np.asarray(Image.fromarray(np.ascontiguousarray(a[sy:sy + sh, sx:sx + sw], np.float32)).resize((w, h), Image.BILINEAR))
        for c in range(3):
            alb[y:y + h, x:x + w, c] = rs(alb[..., c])
        height[y:y + h, x:x + w] = rs(height)
        smooth[y:y + h, x:x + w] = rs(smooth)
        metal[y:y + h, x:x + w] = rs(metal)
        ao[y:y + h, x:x + w] = 1.0

    def bold(px):
        f = ImageFont.truetype("bahnschrift.ttf", px)
        f.set_variation_by_name("Bold Condensed")
        return f

    measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    small = [("label:" + w_, int(measure.textlength(w_, font=bold(33))) + 20, LABEL_PX, "label", w_)
             for w_ in sorted(set(spec["fallback_words"]) | {"SPARE"})]

    def density(c):  # a blank or an air outlet carries no lettering: half the density
        return 0.5 if not any(it[0] in ("text", "dial", "screwseat") for it in c["items"]) else 1.0

    def pack(entries, rects, pad):
        """Skyline bottom-left packing over `rects`, tallest first: [(entry, x, y)] or None."""
        entries = sorted(entries, key=lambda e: (-e[2], -e[1]))
        skylines = [[[r[0], r[1], r[2] - r[0]]] for r in rects]
        placed = []
        for e in entries:
            ww, hh = e[1] + 2 * pad, e[2] + 2 * pad
            best = None
            for ri, sky in enumerate(skylines):
                for i in range(len(sky)):
                    x = sky[i][0]
                    if x + ww > rects[ri][2]:
                        break
                    y, span, j = sky[i][1], 0, i
                    while span < ww:
                        y = max(y, sky[j][1])
                        span += sky[j][2]
                        j += 1
                        if span < ww and j >= len(sky):
                            y = None
                            break
                    if y is None or y + hh > rects[ri][3]:
                        continue
                    if best is None or (y + hh, x) < (best[0] + best[1], best[2]):
                        best = (y, hh, x, ri)
            if best is None:
                return None
            y, hh, x, ri = best
            out_ = []
            done = False
            for s in skylines[ri]:
                s0, s1 = s[0], s[0] + s[2]
                if s1 <= x or s0 >= x + ww:
                    out_.append(s)
                    continue
                if s0 < x:
                    out_.append([s0, s[1], x - s0])
                if not done:
                    out_.append([x, y + hh, ww])
                    done = True
                if s1 > x + ww:
                    out_.append([x + ww, s[1], s1 - x - ww])
            skylines[ri] = sorted(out_)
            placed.append((e, x + pad, y + pad))
        return placed

    def card_entries(pxm):
        return [("card:" + c["id"], max(4, int(round(c["w"] * pxm * density(c)))), max(4, int(round(c["h"] * pxm * density(c)))), "card", c)
                for c in spec["cards"]]
    card_pxm = 2200
    placed = pack(small + card_entries(card_pxm), DECAL_RECTS, PAD)
    while placed is None:
        card_pxm -= 25
        assert card_pxm >= 600, "the cards do not fit the sheet"
        placed = pack(small + card_entries(card_pxm), DECAL_RECTS, PAD)
    cells, text_jobs, card_rects, fields = {}, [], {}, {}
    for (key, w_, h_, kind, obj), x, y in placed:
        if kind == "card":
            dens = card_pxm * density(obj)
            f_ = cardbake2.PaintField(obj, int(obj["id"][1:]) + 11, dens)
            fields[obj["id"]] = f_
            # the card's texels per metre across and up as its UVs place them (its content is computed at the first
            # in both directions; the rect's rounding makes the second differ by up to 0.4 %)
            f_.grid = (w_ / obj["w"], h_ / obj["h"])
            f_.rect = (x, y)
            mp = f_.sample(0.0, obj["h"], w_, h_, w_ / obj["w"])
            alb[y:y + h_, x:x + w_] = mp["alb"]
            height[y:y + h_, x:x + w_] = mp["height"]
            smooth[y:y + h_, x:x + w_] = mp["smooth"]
            metal[y:y + h_, x:x + w_] = mp["metal"]
            ao[y:y + h_, x:x + w_] = mp["ao"]
            card_rects[obj["id"]] = (x, y, x + w_, y + h_)
            continue
        field_copy(x, y, w_, h_, LABEL_PX / LABEL_M)
        cells[key] = (x, y, x + w_, y + h_)
        text_jobs.append((key, x, y, w_, h_, kind, obj))
    print("cards", len(card_rects), "at", card_pxm, "px/m")
    img = Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    def centred(word, box, fill, px, lines=1):
        x0_, y0_, x1_, y1_ = box
        parts = [word]
        f = bold(px)
        while px > 10 and max(d.textlength(q, font=f) for q in parts) > (x1_ - x0_) - 10:
            px -= 1
            f = bold(px)
        asc, desc = f.getmetrics()
        ty = (y0_ + y1_) / 2 - asc / 2 - 1
        d.text(((x0_ + x1_) / 2 - d.textlength(word, font=f) / 2, ty), word, fill=fill, font=f)

    for key, x, y, w_, h_, kind, word in text_jobs:
        centred(word, (x, y, x + w_, y + h_), (238, 238, 232), 33)
    # hardware cells
    x0, y0, x1, y1 = HW["fastener"]  # the shared Dzus head: plated, a 0.4 mm crown, a dark slot
    yy_, xx_ = np.mgrid[0:y1 - y0, 0:x1 - x0]
    # the head's circle inside the octagon that carries it (radius cos 22.5 deg of the cell's half width); outside
    # it, panel dark, no metal
    rr_ = np.hypot(xx_ - (x1 - x0 - 1) / 2, yy_ - (y1 - y0 - 1) / 2) / ((x1 - x0) / 2) / 0.9239
    dome = np.sqrt(np.clip(1 - rr_ ** 2, 0, 1))
    shade = np.clip(150 + 70 * dome, 0, 255)
    d.rectangle((x0, y0, x1, y1), fill=(150, 151, 153))
    for yv in range(y1 - y0):
        for xv in range(x1 - x0):
            r_ = rr_[yv, xv]
            if r_ > 1.0:
                d.point((x0 + xv, y0 + yv), fill=(62, 62, 64))
                continue
            v = int(shade[yv, xv] * (1 - 0.25 * min(1.0, max(0.0, (r_ - 0.86) / 0.14))))
            d.point((x0 + xv, y0 + yv), fill=(v, v, v + 2))
    d.line((x0 + 10, (y0 + y1) // 2, x1 - 10, (y0 + y1) // 2), fill=(22, 22, 22), width=9)
    # 0.4 mm over a 4.6 mm head across 64 px: slope units are metres x px/m / 2, the cell is 13,900 px/m
    height[y0:y1, x0:x1] = dome * 0.0004 * 13900 / 2
    height[(y0 + y1) // 2 - 4:(y0 + y1) // 2 + 5, x0 + 10:x1 - 10] -= 0.0003 * 13900 / 2
    metal[y0:y1, x0:x1], smooth[y0:y1, x0:x1] = np.where(rr_ <= 1.0, 0.85, 0.0), np.where(rr_ <= 1.0, 0.65, 0.3)
    d.rectangle(HW["tmetal"], fill=(150, 150, 148))  # a toggle's nut and barrel: plated
    tx0, ty0, tx1, ty1 = HW["tmetal"]
    metal[ty0:ty1, tx0:tx1], smooth[ty0:ty1, tx0:tx1] = 0.85, 0.5
    # the keys' frames, edges and sides, the white lever and the lenses toned down: brighter, under the game's sun
    # and the night flood they bloomed past the stock cockpit's keys and lamps
    x0, y0, x1, y1 = HW["osb"]  # a display key's face: dark grey in a light frame, as the stock MFD keys, domed
    d.rectangle((x0, y0, x1, y1), fill=(104, 104, 101))
    for k in range(7, (y1 - y0) - 7):
        v = int(92 - 34 * (k - 7) / ((y1 - y0) - 14))  # lit along its top edge, darker toward its foot
        d.line((x0 + 7, y0 + k, x1 - 8, y0 + k), fill=(v, v + 1, v + 3))
    d.rectangle(HW["keyframe"], fill=(20, 20, 21))
    d.rectangle(HW["keyside"], fill=(88, 88, 85))
    d.rectangle(HW["keyedge"], fill=(140, 140, 137))
    x0, y0, x1, y1 = HW["keyedge"]
    metal[y0:y1, x0:x1], smooth[y0:y1, x0:x1] = 0.6, 0.6
    d.rectangle(HW["guard_dark"], fill=(110, 18, 16))
    x0, y0, x1, y1 = HW["guard_cap"]  # the guard's red cap: paint darker toward its corners, worn bright at its edges
    gw, gh = x1 - x0, y1 - y0
    yy_, xx_ = np.mgrid[0:gh, 0:gw]
    edge_ = np.minimum(np.minimum(xx_, gw - 1 - xx_), np.minimum(yy_, gh - 1 - yy_)).astype(np.float32)
    corner = np.hypot(np.minimum(xx_, gw - 1 - xx_), np.minimum(yy_, gh - 1 - yy_)) / (gw / 2)
    rng_g = np.random.default_rng(5)
    for yv in range(gh):
        for xv in range(gw):
            k_ = (0.78 + 0.22 * min(1.0, corner[yv, xv] * 1.6)) * (1 + 0.07 * rng_g.standard_normal())
            worn = edge_[yv, xv] < 2 and rng_g.random() < 0.45
            c_ = (150, 132, 128) if worn else (int(172 * k_), int(28 * k_), int(22 * k_))
            d.point((x0 + xv, y0 + yv), fill=c_)
    smooth[y0:y1, x0:x1] = 0.55
    d.rectangle(HW["pin"], fill=(58, 58, 60))
    x0, y0, x1, y1 = HW["pin"]
    metal[y0:y1, x0:x1], smooth[y0:y1, x0:x1] = 0.9, 0.5
    d.rectangle(HW["white"], fill=(176, 176, 171))
    d.rectangle(HW["mark"], fill=(240, 240, 235))
    d.rectangle(HW["cap"], fill=(92, 93, 96))
    x0, y0, x1, y1 = HW["cb"]  # breaker cap: black, white collar band
    d.rectangle((x0, y0, x1, y1), fill=(20, 20, 21))
    d.ellipse((x0 + 8, y0 + 8, x1 - 8, y1 - 8), outline=(205, 205, 200), width=5)
    x0, y0, x1, y1 = HW["hazard"]
    d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(20, 20, 20))
    for k in range(-(y1 - y0), x1 - x0, 32):
        d.polygon([(x0 + k, y1), (x0 + k + 16, y1), (x0 + k + 16 + (y1 - y0), y0), (x0 + k + (y1 - y0), y0)], fill=(205, 158, 36))
    d.rectangle((x1, y0, x1 + 40, y1), fill=(0, 0, 0))
    d.rectangle(HW["guard_red"], fill=(168, 26, 22))
    for name, c in (("lens_amber", (170, 118, 34)), ("lens_green", (58, 160, 76)), ("lens_red", (165, 42, 34)), ("lens_white", (168, 168, 164))):
        x0, y0, x1, y1 = HW[name]
        d.rectangle((x0, y0, x1, y1), fill=(30, 30, 30))
        d.ellipse((x0 + 4, y0 + 4, x1 - 4, y1 - 4), fill=c)
    d.rectangle(HW["glare"], fill=(14, 14, 15))
    alb = np.asarray(img, np.float32) / 255
    for (x0_, y0_, x1_, y1_) in list(cells.values()) + list(card_rects.values()):
        for arr in (alb, height, smooth, metal, ao):
            arr[y0_ - PAD:y0_, x0_:x1_] = arr[y0_:y0_ + 1, x0_:x1_]
            arr[y1_:y1_ + PAD, x0_:x1_] = arr[y1_ - 1:y1_, x0_:x1_]
            arr[y0_ - PAD:y1_ + PAD, x0_ - PAD:x0_] = arr[y0_ - PAD:y1_ + PAD, x0_:x0_ + 1]
            arr[y0_ - PAD:y1_ + PAD, x1_:x1_ + PAD] = arr[y0_ - PAD:y1_ + PAD, x1_ - 1:x1_]
    for name in ("lens_amber", "lens_green", "lens_red", "lens_white"):
        x0, y0, x1, y1 = HW[name]
        smooth[y0:y1, x0:x1] = 0.65
    x0, y0, x1, y1 = HW["glare"]
    smooth[y0:y1, x0:x1] = 0.05
    hp = np.pad(height, 1, mode="wrap")
    dx, dy = (hp[1:-1, 2:] - hp[1:-1, :-2]), (hp[2:, 1:-1] - hp[:-2, 1:-1])
    nrm = np.stack([-dx, dy, np.ones_like(dx)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8)).save(out / "trim2_b.png")
    Image.fromarray(((nrm * 0.5 + 0.5) * 255).astype(np.uint8)).save(out / "trim2_n.png")
    ms = np.zeros((H, W, 4), np.uint8)
    ms[..., 0] = ms[..., 1] = ms[..., 2] = (np.clip(metal, 0, 1) * 255).astype(np.uint8)
    ms[..., 3] = (np.clip(smooth, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(ms).save(out / "trim2_m.png")
    Image.fromarray((np.clip(ao, 0, 1) * 255).astype(np.uint8)).save(out / "trim2_ao.png")
    ink_layout = ink_sheet(spec, fields, out, pack, card_pxm)
    detail = detail_maps(out, card_rects, ink_layout)
    band_lines(out)
    marker_keyline(out)
    glass_tint(out)
    json.dump({"size": [W, H], "strips": STRIPS, "labels": cells, "hardware": HW, "cards": card_rects, "card_pxm": card_pxm,
               "ink": ink_layout, "detail": dict(detail, trim_tiling=detail["pxm"] / detail["size"] / (card_pxm / W),
                                                  ink_tiling=detail["pxm"] / detail["size"] / (ink_layout["pxm"] / 2048))},
              open(out / "trim2_layout.json", "w"), indent=1)
    print("cells", len(cells))


INK_PAD = 6


def slopes(height):
    hp = np.pad(height, 1, mode="edge")
    return (hp[1:-1, 2:] - hp[1:-1, :-2]), (hp[2:, 1:-1] - hp[:-2, 1:-1])


DETAIL_PX, DETAIL_PXM = 512, 3000  # the paint's fine grain: one 512 px tile at 3,000 px/m (170 mm), tiled over the paint
DETAIL_WAVE = 0.0011  # its dimples about 1.1 mm across: 2 px at the stock crop's 2.7 px/mm, as the stock paint's


def detail_arrays():
    """The detail tile: its height h (unit std), albedo (sRGB, 128 neutral) and slopes (m/m, as save_maps' slope units)."""
    n = DETAIL_PX
    rng = np.random.default_rng(23)
    f = np.fft.fftfreq(n) * DETAIL_PXM
    fr = np.hypot(*np.meshgrid(f, f))
    band = np.exp(-0.5 * (np.log(np.maximum(fr, 1.0) * DETAIL_WAVE) / 0.45) ** 2)
    h = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * band))
    h = (h - h.mean()) / h.std()
    alb = np.clip(128 + DETAIL_ALB * h, 0, 255).astype(np.uint8)  # dimples (negative h) darker
    hm = h * DETAIL_RELIEF * DETAIL_PXM / 2
    hp = np.pad(hm, 1, mode="wrap")
    dx, dy = hp[1:-1, 2:] - hp[1:-1, :-2], hp[2:, 1:-1] - hp[:-2, 1:-1]
    return h, alb, dx, dy


# albedo steps per unit (sRGB), relief per unit (m); 6 steps, not 15: on the near-black paint in sun the grain read
# as speckle in game
DETAIL_ALB, DETAIL_RELIEF = 6.0, 0.000020


def detail_sample(a, col, row):
    """Bilinear, wrapping, at texel-space positions (texel k's centre at k + 0.5)."""
    n = a.shape[0]
    x, y = col - 0.5, row - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    x0, y0 = x0 % n, y0 % n
    x1, y1 = (x0 + 1) % n, (y0 + 1) % n
    return (a[y0, x0] * (1 - fx) + a[y0, x1] * fx) * (1 - fy) + (a[y1, x0] * (1 - fx) + a[y1, x1] * fx) * fy


def band_lines(out):
    """The camera screen's scan lines (0.1.3's tile, 64 px, a line every 8 rows): clear between the lines, half as
    opaque as the line, and the lines black. 0.1.3's map was near-white with lines a shade darker, which under the
    screen's pale tint made the whole pane a lit veil that the game's night vision blew up into a blank band; the screen's material (CenturionAuthor.FlightDeck.cs ScreenTint) sets the overall opacity."""
    m = np.zeros((64, 64, 4), np.uint8)
    m[..., :3] = 255
    m[..., 3] = 128
    for r in range(0, 64, 8):
        m[r + 1:r + 3, :, :3] = 0
        m[r + 1:r + 3, :, 3] = 255
    Image.fromarray(m, "RGBA").save(out / "band2.png")


GLASS_TINT = (43, 36, 27, 13)  # the inner panes' tint: 0.1.3's colour at alpha 13 (it was 117)


def glass_tint(out):
    """The inner panes' uniform tint (cockpit_glass.png, 4 x 4): seen through the forward screen, a pane at 0.1.3's
    alpha of 117 with its grazing reflection read as a pale dome on the screen (in game, 193 against 121 outside it
    from the pilot's seat), and over the screen as a dark field (57); at 13 the screen with a pane behind it and the
    screen alone differ by about 5%, and the pane over it still reads as a faint glass."""
    Image.fromarray(np.full((4, 4, 4), GLASS_TINT, np.uint8), "RGBA").save(out / "glass2.png")


def marker_keyline(out, px=2, alpha=0.85, pad=10, plate=0.65):
    """The EXT CAM mark (0.1.3's: a red dot and near-white letters on clear, kept as marker_013.png beside this script)
    on a dark rounded plate at `plate` opacity, `pad` px round it, with a dark keyline px wide at `alpha` round its
    letters: on the clear screen the mark alone faded over pale sky, and a keyline alone over dark pavement."""
    from PIL import ImageDraw, ImageFilter
    im = Image.open(Path(__file__).parent / "data" / "marker_013.png").convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    grown = np.asarray(im.getchannel("A").filter(ImageFilter.MaxFilter(2 * px + 1))).astype(np.float32)
    ys, xs = np.nonzero(a[..., 3] > 8)
    back = Image.new("L", im.size, 0)
    ImageDraw.Draw(back).rounded_rectangle([xs.min() - pad, ys.min() - pad, xs.max() + pad, ys.max() + pad],
                                           radius=pad, fill=int(255 * plate))
    k = a[..., 3:4] / 255
    out_a = np.maximum(np.maximum(a[..., 3], grown * alpha), np.asarray(back).astype(np.float32))
    rgb = a[..., :3] * k / np.maximum(out_a[..., None] / 255, 1e-6)  # the mark over black, unpremultiplied
    m = np.concatenate([np.clip(rgb, 0, 255), out_a[..., None]], -1).astype(np.uint8)
    Image.fromarray(m, "RGBA").save(out / "marker2.png")


def detail_maps(out, card_rects, ink_layout):
    """The paint's fine hammered grain as a tiling detail (URP Lit's detail albedo x2 and detail normal, masked to the
    paint), so its size no longer follows the atlas's 1,150 px/m: band-passed noise round DETAIL_WAVE, periodic by
    construction (FFT), dimples darker; detail_b (sRGB, 128 neutral), detail_n, detail_h (for the review render's bump),
    and each sheet's mask in the alpha of {trim2,ink2}_dmask.png (paint 255, hardware cells and keys 0)."""
    n = DETAIL_PX
    h, alb, dx, dy = detail_arrays()
    Image.fromarray(np.stack([alb] * 3, -1)).save(out / "detail_b.png")
    nrm = np.stack([-dx, dy, np.ones_like(dx)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    Image.fromarray(((nrm * 0.5 + 0.5) * 255).astype(np.uint8)).save(out / "detail_n.png")
    Image.fromarray(np.clip(128 + 40 * h, 0, 255).astype(np.uint8)).save(out / "detail_h.png")
    # the ink sheet's islands carry the detail baked in at the card's own phase (ink_sheet), so its mask is empty
    for stem, rects in (("trim2", list(card_rects.values())), ("ink2", [])):
        m = np.zeros((2048, 2048, 4), np.uint8)
        m[..., :3] = 255
        for x0, y0, x1, y1 in rects:
            m[y0:y1, x0:x1, 3] = 255
        Image.fromarray(m).save(out / (stem + "_dmask.png"))
    return {"size": n, "pxm": DETAIL_PXM, "relief_m_per_unit": DETAIL_RELIEF, "albedo_per_unit": DETAIL_ALB}


def save_maps(out, stem, alb, height, smooth, metal, ao, slope_set=None):
    """The maps from the albedo and the height (slope units); `slope_set` (dx, dy, NaN where unset) gives the normal
    directly where the height cannot (the ink islands: their card's normals, interpolated)."""
    dx, dy = slopes(height)
    if slope_set is not None:
        dx, dy = np.where(np.isnan(slope_set[0]), dx, slope_set[0]), np.where(np.isnan(slope_set[1]), dy, slope_set[1])
    nrm = np.stack([-dx, dy, np.ones_like(dx)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8)).save(out / (stem + "_b.png"))
    Image.fromarray(((nrm * 0.5 + 0.5) * 255).astype(np.uint8)).save(out / (stem + "_n.png"))
    ms = np.zeros(height.shape + (4,), np.uint8)
    ms[..., 0] = ms[..., 1] = ms[..., 2] = (np.clip(metal, 0, 1) * 255).astype(np.uint8)
    ms[..., 3] = (np.clip(smooth, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(ms).save(out / (stem + "_m.png"))
    Image.fromarray((np.clip(ao, 0, 1) * 255).astype(np.uint8)).save(out / (stem + "_ao.png"))


def ink_sheet(spec, fields, out, pack, card_pxm):
    """The ink sheet: every card's lettering islands at the highest density from 4,400 px/m down that fits (3,750 at
    least), each sampled from its card's paint field with the lettering on it; then the key faces and caution lenses."""
    import flightdeck_cards as cardbake2
    DET = detail_arrays()
    N = 2048
    alb = np.zeros((N, N, 3), np.float32)
    height = np.zeros((N, N), np.float32)
    smooth = np.full((N, N), 0.3, np.float32)
    metal = np.zeros((N, N), np.float32)
    ao = np.ones((N, N), np.float32)
    slope_set = (np.full((N, N), np.nan, np.float32), np.full((N, N), np.nan, np.float32))
    isl = {c["id"]: cardbake2.islands(c) for c in spec["cards"]}
    fixed = [("caution:" + w_, 132, 44, "caution", w_) for w_ in panels2.ANNUNCIATORS]
    fixed += [("key:" + w_, 64, 56, "key", w_) for w_ in (spec.get("key_words") or panels2.key_words())]

    def entries(pxm):
        es = []
        for cid, rs in isl.items():
            for k, r in enumerate(rs):
                es.append(("isl:%s:%d" % (cid, k), max(2, int(np.ceil((r[2] - r[0]) * pxm))), max(2, int(np.ceil((r[3] - r[1]) * pxm))), "island", (cid, r)))
        return es
    ink_pxm = 4400
    placed = pack(fixed + entries(ink_pxm), [(0, 0, N, N)], INK_PAD)
    while placed is None:
        ink_pxm -= 50
        # 3,500 px/m holds the thinnest stroke (MIN_STEM) at 2.6 texels; the legends grown to the floor
        # (flightdeck_cards.grow_legends) need the room, and their own strokes are thicker
        assert ink_pxm >= 3500, "the lettering does not fit the ink sheet at 3,500 px/m"
        placed = pack(fixed + entries(ink_pxm), [(0, 0, N, N)], INK_PAD)
    lay = {"pxm": ink_pxm, "islands": {}, "labels": {}}
    cards = {c["id"]: c for c in spec["cards"]}
    jobs = []
    for (key, w_, h_, kind, obj), x, y in placed:
        if kind == "island":
            cid, r = obj
            c = cards[cid]
            f_ = fields[cid]
            # the paint under the lettering as the card's own texels show it, sampled on the card's grid and
            # interpolated up as the GPU filters the card, so the island's grain meets the card's across the cut
            (g_, gy), H_ = f_.grid, c["h"]
            kx0, ky0 = int(np.floor(r[0] * g_)) - 2, int(np.floor((H_ - r[3]) * gy)) - 2
            kx1, ky1 = int(np.ceil((r[0] + w_ / ink_pxm) * g_)) + 2, int(np.ceil((H_ - r[3] + h_ / ink_pxm) * gy)) + 2
            lo = f_.sample(kx0 / g_, H_ - ky0 / g_, kx1 - kx0, ky1 - ky0, g_)  # texel rows as the card computed them
            bx, by = r[0] * g_ - kx0, (H_ - r[3]) * gy - ky0  # placed where the card's UVs put them
            box = (bx, by, bx + w_ / ink_pxm * g_, by + h_ / ink_pxm * gy)

            def up(a):
                if a.ndim == 3:
                    return np.stack([up(a[..., k]) for k in range(a.shape[2])], -1)
                return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((w_, h_), Image.BILINEAR, box=box), np.float32).copy()
            mp = {k: up(v) for k, v in lo.items()}
            # the normal as the card's map has it (central differences on the card's grid), interpolated
            sx, sy = slopes(lo["height"])
            sx, sy = up(sx), up(sy)
            # the tiling detail where the trim material draws it on the card: each ink texel's card metres, to the
            # card's trim texel, to the detail tile's texel (the shader's tiling DETAIL_PXM / card_pxm per trim px)
            jj, ii = np.mgrid[0:h_, 0:w_]
            mx, my = r[0] + (ii + 0.5) / ink_pxm, r[3] - (jj + 0.5) / ink_pxm
            xt, yt = f_.rect[0] + mx * g_, f_.rect[1] + (H_ - my) * gy
            s_ = DETAIL_PXM / card_pxm
            col, row = xt * s_, -(2048 - yt) * s_
            dalb = detail_sample(DET[1].astype(np.float32), col, row) / 255
            dlin = np.where(dalb <= 0.04045, dalb / 12.92, ((dalb + 0.055) / 1.055) ** 2.4) * 4.5948
            lin = np.where(mp["alb"] <= 0.04045, mp["alb"] / 12.92, ((mp["alb"] + 0.055) / 1.055) ** 2.4) * dlin[..., None]
            mp["alb"] = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.maximum(lin, 0), 1 / 2.4) - 0.055)
            mp["ao"] = mp["ao"].copy()
            sx, sy = sx + detail_sample(DET[2], col, row), sy + detail_sample(DET[3], col, row)
            slope_set[0][y:y + h_, x:x + w_], slope_set[1][y:y + h_, x:x + w_] = sx, sy
            colour, weight = cardbake2.ink_level(c)
            mask = cardbake2.ink(c, r[0], r[3], w_, h_, ink_pxm, weight)
            col = np.array(colour, np.float32) / 255
            alb[y:y + h_, x:x + w_] = mp["alb"] * (1 - mask[..., None]) + col * mask[..., None]
            height[y:y + h_, x:x + w_] = mp["height"]
            smooth[y:y + h_, x:x + w_] = mp["smooth"] * (1 - mask) + 0.30 * mask  # the stencil as matte as the paint
            metal[y:y + h_, x:x + w_] = mp["metal"] * (1 - mask)
            ao[y:y + h_, x:x + w_] = mp["ao"] * (1 - mask) + mask  # the stencil not darkened by the contact AO round its control
            # the island's exact extent in card metres, so the cut on the face meets its texels exactly
            lay["islands"].setdefault(cid, []).append({"m": [r[0], r[3] - h_ / ink_pxm, r[0] + w_ / ink_pxm, r[3]], "px": [x, y, x + w_, y + h_]})
        else:
            lay["labels"][key] = (x, y, x + w_, y + h_)
            jobs.append((key, x, y, w_, h_, kind, obj))
    img = Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    def bold_(px, variant="Bold Condensed"):
        f = ImageFont.truetype("bahnschrift.ttf", int(px))
        f.set_variation_by_name(variant)
        return f
    for key, x, y, w_, h_, kind, word in jobs:
        if kind == "caution":  # an unlit caution lens: smoked glass in a dark rim, the legend in amber
            d.rectangle((x, y, x + w_ - 1, y + h_ - 1), fill=(64, 58, 50))
            d.rectangle((x + 3, y + 3, x + w_ - 4, y + h_ - 4), fill=(34, 26, 14))
            smooth[y:y + h_, x:x + w_] = 0.85
            px = 30
            f = bold_(px)
            while px > 10 and d.textlength(word, font=f) > w_ - 10:
                px -= 1
                f = bold_(px)
            bb = f.getbbox(word)
            d.text((x + (w_ - d.textlength(word, font=f)) / 2, y + h_ / 2 - (bb[1] + bb[3]) / 2), word, fill=(246, 176, 56), font=f)
        else:  # a push key's face: light grey, its legend in black at 4.5 mm cap height or more
            d.rectangle((x, y, x + w_ - 1, y + h_ - 1), fill=(120, 120, 116))
            d.rectangle((x + 4, y + 4, x + w_ - 5, y + h_ - 5), fill=(178, 178, 172))
            smooth[y:y + h_, x:x + w_] = 0.45
            cap_px = 0.006 * 64 / 0.014
            for variant in ("Bold", "Bold Condensed"):
                f = bold_(10, variant)
                bb = f.getbbox("H")
                f = bold_(round(10 * cap_px / (bb[3] - bb[1])), variant)
                if d.textlength(word, font=f) <= w_ - 10:
                    break
            bb = f.getbbox(word)
            d.text((x + (w_ - d.textlength(word, font=f)) / 2, y + h_ / 2 - (bb[1] + bb[3]) / 2), word, fill=(22, 22, 22), font=f)
    alb = np.asarray(img, np.float32) / 255
    for (_, w_, h_, kind, obj), x, y in placed:
        for arr in (alb, height, smooth, metal, ao):
            arr[y - INK_PAD:y, x:x + w_] = arr[y:y + 1, x:x + w_]
            arr[y + h_:y + h_ + INK_PAD, x:x + w_] = arr[y + h_ - 1:y + h_, x:x + w_]
            arr[y - INK_PAD:y + h_ + INK_PAD, x - INK_PAD:x] = arr[y - INK_PAD:y + h_ + INK_PAD, x:x + 1]
            arr[y - INK_PAD:y + h_ + INK_PAD, x + w_:x + w_ + INK_PAD] = arr[y - INK_PAD:y + h_ + INK_PAD, x + w_ - 1:x + w_]
    save_maps(out, "ink2", alb, height, smooth, metal, ao, slope_set)
    n_isl = sum(len(v) for v in lay["islands"].values())
    area = sum((i["m"][2] - i["m"][0]) * (i["m"][3] - i["m"][1]) for v in lay["islands"].values() for i in v)
    lay["island_count"], lay["island_area_m2"] = n_isl, area
    print("ink sheet:", n_isl, "islands,", round(area, 4), "m2, at", ink_pxm, "px/m")
    return lay


if __name__ == "__main__":
    SPEC = sys.argv[2] if len(sys.argv) > 2 else None
    main(Path(sys.argv[1]))
