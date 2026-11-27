"""The finished sample's textures, generated: one 2048 x 1024 cockpit trim sheet in the stock four-map contract
(albedo, tangent normal, metallic R + smoothness A, AO; digest-cockpit rule 9) and a stand-in 1024 x 512 tac screen
canvas for the review renders (the game draws the real pages; this only lights the glass).

python -I flightdeck_texture_noise.py <out folder>   writes trim_{b,n,m,ao}.png, trim_layout.json, canvas.png

The trim sheet is laid out as strips that tile along U (rule 11: repeated regions, UVs reused across copies), in the
Darkreach's design language (BDF): light grey panel field, dark grey sub-panels, near-black bezels, worn chamfers, white
condensed stencils on dark label strips, yellow and black hazard, red guards. Wear and grime sit on each strip's long
borders, so a face mapped edge to edge picks them up on its own edges."""

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 2048, 1024
rng = np.random.default_rng(7)

# Regions, pixel rects (x0, y0, x1, y1) with y down; the Blender side converts to UV.
STRIPS = {
    "field": (0, 0, 2048, 448),       # light grey panel faces, 0.30 m tall at 1,500 px/m
    "dark": (0, 448, 2048, 640),      # dark grey sub-panels and the switch strip
    "bezel": (0, 640, 2048, 704),     # display bezels
    "edge": (0, 704, 2048, 736),      # chamfers: worn paint to bare metal
    "side": (0, 736, 2048, 768),      # hidden returns and module sides
}
LABELS = ["RADAR", "NAV", "RESET", "VIEW", "CNTR", "GAIN", "CONT", "BRT", "MASTER ARM", "BAY DOORS", "JETT",
          "RANGE", "MODE", "WING SPAN", "TEST", "MFD 2", "ARM", "SAFE", "OPEN", "CLOSE", "AUTO", "OFF", "ON", "DAY",
          "NIGHT", "HUD", "STBY", "MAP"]
LABEL_CELL = (192, 40)
LABEL_RECT = (0, 768, 1536, 1024)  # 8 x 6 cells
HW = {  # hardware cells in (1536..2048, 768..1024)
    "fastener": (1536, 768, 1600, 832), "knob": (1600, 768, 1696, 864), "osb": (1696, 768, 1760, 832),
    "button_amber": (1760, 768, 1824, 832), "button_green": (1824, 768, 1888, 832), "guard_red": (1888, 768, 1952, 832),
    "hazard": (1536, 864, 1792, 896), "knob_side": (1696, 832, 1824, 864), "lamp_lens": (1952, 768, 2048, 832),
    "toggle": (1824, 832, 1888, 864), "warning_tri": (1888, 832, 1952, 896),
}


def srgb(c):
    return np.array(c, dtype=np.float32) / 255.0


def noise(h, w, scale, octaves=4, seed=0):
    r = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        s = max(1, int(scale / (2 ** o)))
        small = r.standard_normal((h // s + 2, w // s + 2)).astype(np.float32)
        img = Image.fromarray(small).resize((w + 2 * s, h + 2 * s), Image.BICUBIC)
        a = np.asarray(img)[s:s + h, s:s + w]
        a = a[:, :w]
        # tile in U: blend the right edge into the left
        out += amp * a
        tot += amp
        amp *= 0.5
    out /= tot
    # make it tile horizontally by cross-fading the ends
    f = 64
    ramp = np.linspace(0, 1, f, dtype=np.float32)
    out[:, :f] = out[:, :f] * ramp + out[:, -f:] * (1 - ramp)
    return out


def scratches(h, w, count, length, seed):
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    r = np.random.default_rng(seed)
    for _ in range(count):
        x, y = r.uniform(0, w), r.uniform(0, h)
        a = r.uniform(-0.5, 0.5) + (0 if r.random() < 0.7 else math.pi / 2)
        L = r.uniform(0.3, 1.0) * length
        d.line((x, y, x + L * math.cos(a), y + L * math.sin(a)), fill=int(r.uniform(90, 200)), width=1)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(0.6)), np.float32) / 255


def border_mask(h, w, px):
    """1 at a strip's top and bottom rows fading to 0 over px: where faces mapped edge to edge get their edge wear."""
    y = np.arange(h, dtype=np.float32)
    m = np.clip(1 - np.minimum(y, h - 1 - y) / px, 0, 1)
    return np.repeat(m[:, None], w, axis=1)


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    alb = np.zeros((H, W, 3), np.float32)
    height = np.zeros((H, W), np.float32)
    metal = np.zeros((H, W), np.float32)
    smooth = np.full((H, W), 0.35, np.float32)
    ao = np.ones((H, W), np.float32)

    def paint(rect, base, mottle, wear_px, wear_amt, grime_amt, smooth_v, seed, scuffs=0):
        x0, y0, x1, y1 = rect
        h, w = y1 - y0, x1 - x0
        n1 = noise(h, w, 96, 5, seed)
        n2 = noise(h, w, 12, 3, seed + 1)
        col = srgb(base)[None, None, :] * (1 + mottle * n1[..., None] + 0.015 * n2[..., None])
        bm = border_mask(h, w, wear_px)
        chip = (noise(h, w, 6, 2, seed + 2) > 0.55).astype(np.float32)
        wear = np.clip(bm * (0.6 + 0.8 * noise(h, w, 24, 3, seed + 3)), 0, 1) * chip * wear_amt
        grime = np.clip(bm * 0.8 + 0.25 * noise(h, w, 128, 4, seed + 4), 0, 1) * grime_amt
        col = col * (1 - grime[..., None] * 0.35)
        bare = srgb((150, 152, 155))[None, None, :]
        col = col * (1 - wear[..., None]) + bare * wear[..., None]
        if scuffs:
            sc = scratches(h, w, scuffs, 90, seed + 5)
            col = col * (1 - 0.25 * sc[..., None]) + srgb((175, 176, 178)) * 0.25 * sc[..., None]
            height[y0:y1, x0:x1] -= 0.15 * sc
        alb[y0:y1, x0:x1] = np.clip(col, 0, 1)
        height[y0:y1, x0:x1] += 0.08 * n2 + 0.3 * noise(h, w, 4, 1, seed + 6) * 0.05
        metal[y0:y1, x0:x1] = wear * 0.8
        smooth[y0:y1, x0:x1] = smooth_v + 0.15 * wear - 0.08 * grime
        ao[y0:y1, x0:x1] = 1 - 0.35 * bm ** 2

    # BDF greys: the Darkreach's sfb_cockpit_b sits at p50 74 and p95 145 (sRGB); its light panels 125 to 140
    paint(STRIPS["field"], (128, 130, 131), 0.03, 14, 0.9, 0.5, 0.32, 11, scuffs=260)
    paint(STRIPS["dark"], (58, 60, 62), 0.06, 10, 0.8, 0.4, 0.30, 21, scuffs=120)
    paint(STRIPS["bezel"], (33, 34, 36), 0.05, 6, 0.7, 0.2, 0.40, 31, scuffs=40)
    paint(STRIPS["side"], (40, 41, 43), 0.05, 4, 0.1, 0.5, 0.25, 41)
    # chamfer: paint worn through to metal toward the strip's middle line (the edge itself)
    x0, y0, x1, y1 = STRIPS["edge"]
    h = y1 - y0
    t = 1 - np.abs(np.linspace(-1, 1, h, dtype=np.float32))
    wear = np.clip(t[:, None] * 1.3 * (0.6 + 0.6 * noise(h, x1 - x0, 8, 2, 51)), 0, 1)
    base = srgb((128, 130, 131))[None, None, :] * (1 - wear[..., None]) + srgb((165, 167, 170)) * wear[..., None]
    alb[y0:y1, x0:x1] = base
    metal[y0:y1, x0:x1] = wear * 0.9
    smooth[y0:y1, x0:x1] = 0.35 + 0.3 * wear
    height[y0:y1, x0:x1] = t[:, None] * 0.6

    # labels: white condensed stencil on a dark strip with a fine light keyline
    font = ImageFont.truetype("bahnschrift.ttf", 26)
    font.set_variation_by_name("Bold Condensed")
    lab = Image.new("RGB", (LABEL_RECT[2] - LABEL_RECT[0], LABEL_RECT[3] - LABEL_RECT[1]), (44, 45, 47))
    d = ImageDraw.Draw(lab)
    cells = {}
    cw, ch = LABEL_CELL
    per_row = lab.width // cw
    for i, word in enumerate(LABELS):
        cx, cy = (i % per_row) * cw, (i // per_row) * ch
        d.rectangle((cx + 1, cy + 1, cx + cw - 2, cy + ch - 2), fill=(42, 43, 45), outline=(70, 71, 73))
        tw = d.textlength(word, font=font)
        d.text((cx + (cw - tw) / 2, cy + 6), word, fill=(226, 226, 220), font=font)
        cells[word] = (LABEL_RECT[0] + cx + 2, LABEL_RECT[1] + cy + 2, LABEL_RECT[0] + cx + cw - 2, LABEL_RECT[1] + cy + ch - 2)
    la = np.asarray(lab, np.float32) / 255
    la = la * (1 + 0.04 * noise(la.shape[0], la.shape[1], 16, 3, 61)[..., None])
    alb[LABEL_RECT[1]:LABEL_RECT[3], LABEL_RECT[0]:LABEL_RECT[2]] = np.clip(la, 0, 1)
    smooth[LABEL_RECT[1]:LABEL_RECT[3], LABEL_RECT[0]:LABEL_RECT[2]] = 0.3

    # hardware cells
    hw = Image.fromarray((alb * 255).astype(np.uint8))
    hd = ImageDraw.Draw(hw)
    hgt = Image.fromarray((np.clip(height, -1, 1) * 127 + 128).astype(np.uint8))
    gd = ImageDraw.Draw(hgt)

    def cell(name):
        return HW[name]
    x0, y0, x1, y1 = cell("fastener")  # Dzus head: dark grey dome with a slot
    hd.ellipse((x0 + 4, y0 + 4, x1 - 4, y1 - 4), fill=(70, 72, 74), outline=(40, 40, 42), width=3)
    hd.line((x0 + 14, (y0 + y1) // 2, x1 - 14, (y0 + y1) // 2), fill=(25, 25, 25), width=6)
    gd.ellipse((x0 + 4, y0 + 4, x1 - 4, y1 - 4), fill=190)
    gd.line((x0 + 14, (y0 + y1) // 2, x1 - 14, (y0 + y1) // 2), fill=90, width=6)
    x0, y0, x1, y1 = cell("knob")  # knob top: black with a white index line, knurled rim
    hd.ellipse((x0 + 2, y0 + 2, x1 - 2, y1 - 2), fill=(22, 22, 23))
    for k in range(48):
        a = 2 * math.pi * k / 48
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 - 3
        gd.line((cx + r * 0.86 * math.cos(a), cy + r * 0.86 * math.sin(a), cx + r * math.cos(a), cy + r * math.sin(a)), fill=200, width=2)
    hd.rectangle(((x0 + x1) / 2 - 3, y0 + 8, (x0 + x1) / 2 + 3, (y0 + y1) / 2), fill=(230, 230, 225))
    x0, y0, x1, y1 = cell("knob_side")  # knurl band for the knob's side, tiles in U
    for k in range(0, x1 - x0, 6):
        hd.rectangle((x0 + k, y0, x0 + k + 2, y1), fill=(38, 38, 40))
        gd.rectangle((x0 + k, y0, x0 + k + 2, y1), fill=200)
    x0, y0, x1, y1 = cell("osb")  # bezel key cap: dark rubber, light bar
    hd.rectangle((x0 + 3, y0 + 3, x1 - 3, y1 - 3), fill=(30, 31, 33), outline=(55, 56, 58), width=2)
    hd.rectangle((x0 + 14, y0 + 28, x1 - 14, y0 + 34), fill=(200, 200, 195))
    for name, fill in (("button_amber", (200, 140, 30)), ("button_green", (60, 150, 70))):
        x0, y0, x1, y1 = cell(name)
        hd.rectangle((x0 + 3, y0 + 3, x1 - 3, y1 - 3), fill=(26, 26, 27))
        hd.rectangle((x0 + 9, y0 + 9, x1 - 9, y1 - 9), fill=tuple(int(c * 0.55) for c in fill))
        f2 = ImageFont.truetype("bahnschrift.ttf", 13)
        f2.set_variation_by_name("Bold Condensed")
        hd.text((x0 + 12, y0 + 24), "ARM" if name == "button_amber" else "RDY", fill=tuple(int(c * 0.9) for c in fill), font=f2)
    x0, y0, x1, y1 = cell("guard_red")
    hd.rectangle((x0, y0, x1, y1), fill=(178, 28, 24))
    x0, y0, x1, y1 = cell("hazard")  # yellow and black at 45 deg, tiles in U (period 32 px)
    hd.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(22, 22, 22))
    for k in range(-(y1 - y0), x1 - x0, 32):
        hd.polygon([(x0 + k, y1), (x0 + k + 16, y1), (x0 + k + 16 + (y1 - y0), y0), (x0 + k + (y1 - y0), y0)],
                   fill=(214, 164, 38))
    hd.rectangle((x1, y0, x1 + 40, y1), fill=(0, 0, 0))
    x0, y0, x1, y1 = cell("toggle")  # toggle lever: brushed steel
    hd.rectangle((x0, y0, x1, y1), fill=(150, 152, 156))
    x0, y0, x1, y1 = cell("lamp_lens")
    hd.rectangle((x0, y0, x1, y1), fill=(18, 12, 12))
    x0, y0, x1, y1 = cell("warning_tri")
    hd.polygon([((x0 + x1) / 2, y0 + 6), (x1 - 6, y1 - 8), (x0 + 6, y1 - 8)], outline=(214, 164, 38), width=4)
    alb = np.asarray(hw, np.float32) / 255
    height = (np.asarray(hgt, np.float32) - 128) / 127
    for name in ("toggle", "fastener", "knob", "knob_side"):
        x0, y0, x1, y1 = cell(name)
        metal[y0:y1, x0:x1] = 0.85 if name == "toggle" else 0.0
        smooth[y0:y1, x0:x1] = 0.55 if name == "toggle" else 0.4

    # normal from height (OpenGL +Y, as Unity), strength per pixel
    hpad = np.pad(height, 1, mode="wrap")
    dx = (hpad[1:-1, 2:] - hpad[1:-1, :-2]) * 2.0
    dy = (hpad[2:, 1:-1] - hpad[:-2, 1:-1]) * 2.0
    nrm = np.stack([-dx, dy, np.ones_like(dx)], axis=-1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    Image.fromarray((np.clip(alb, 0, 1) * 255).astype(np.uint8)).save(out / "trim_b.png")
    Image.fromarray(((nrm * 0.5 + 0.5) * 255).astype(np.uint8)).save(out / "trim_n.png")
    ms = np.zeros((H, W, 4), np.uint8)
    ms[..., 0] = (np.clip(metal, 0, 1) * 255).astype(np.uint8)
    ms[..., 1] = ms[..., 0]
    ms[..., 2] = ms[..., 0]
    ms[..., 3] = (np.clip(smooth, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(ms).save(out / "trim_m.png")
    Image.fromarray((np.clip(ao, 0, 1) * 255).astype(np.uint8)).save(out / "trim_ao.png")
    json.dump({"size": [W, H], "strips": STRIPS, "labels": cells, "hardware": HW}, open(out / "trim_layout.json", "w"), indent=1)
    canvas(out)


def canvas(out):
    """A stand-in tac screen canvas (1024 x 512, y up in canvas pixels as flightdeck.PAGES): green on black pages in
    the stock MFD style at the existing Centurion_TacScreen rects, the wing page in the vacant engine-2 rect."""
    img = Image.new("RGB", (1024, 512), (0, 0, 0))
    d = ImageDraw.Draw(img)
    g, gd = (40, 255, 60), (10, 90, 20)
    f = ImageFont.truetype("consolab.ttf", 16)

    def rect(x0, y0, x1, y1):  # canvas (y up) -> image (y down)
        return x0, 512 - y1, x1, 512 - y0
    # radar
    x0, y0, x1, y1 = rect(2.8, 146.1, 585.7, 488.5)
    d.rectangle((x0, y0, x1, y1), outline=gd, width=2)
    cx, cy = (x0 + x1) / 2 + 30, y1 - 20
    for r in (80, 160, 240, 320):
        d.arc((cx - r, cy - r, cx + r, cy + r), 200, 340, fill=gd, width=2)
    d.polygon([(cx, cy), (cx - 120, cy - 300), (cx + 40, cy - 310)], fill=(6, 60, 12))
    d.line((cx, cy, cx - 40, cy - 305), fill=g, width=2)
    for px, py in ((cx - 70, cy - 190), (cx + 10, cy - 250), (cx - 150, cy - 120)):
        d.polygon([(px, py - 7), (px + 7, py), (px, py + 7), (px - 7, py)], outline=g, width=2)
    for i, t in enumerate(("NAV", "RESET", "VIEW", "CNTR")):
        d.rectangle((x0 + 8, y0 + 40 + 44 * i, x0 + 70, y0 + 66 + 44 * i), outline=g, width=2)
        d.text((x0 + 14, y0 + 44 + 44 * i), t, fill=g, font=f)
    d.text((x0 + 230, y0 + 8), "12:04:31", fill=g, font=f)
    # flight instrument, turned (its up toward canvas -x)
    pfd = Image.new("RGB", (141, 231), (0, 0, 0))
    pd = ImageDraw.Draw(pfd)
    pd.pieslice((20, 70, 121, 171), 180, 360, fill=(30, 90, 200))
    pd.pieslice((20, 70, 121, 171), 0, 180, fill=(150, 80, 30))
    pd.line((40, 121, 101, 121), fill=(255, 255, 255), width=2)
    pd.text((50, 20), "360", fill=g, font=f)
    pd.text((35, 190), "390kt", fill=g, font=f)
    img.paste(pfd.rotate(90, expand=True), (int(289.8), int(512 - 143.8)))
    # engines
    x0, y0, x1, y1 = rect(595.7, 257.0, 810.6, 509.4)
    d.text((x0 + 40, y0 + 10), "ENGINE  NOMINAL", fill=g, font=f)
    for k in range(2):
        ex = x0 + 55 + 105 * k
        d.arc((ex - 40, y0 + 60, ex + 40, y0 + 140), 135, 405, fill=g, width=3)
        d.line((ex, y0 + 100, ex + 25, y0 + 80), fill=g, width=3)
        d.rectangle((ex - 12, y0 + 160, ex + 12, y1 - 20), outline=g, width=2)
        d.rectangle((ex - 10, y0 + 200, ex + 10, y1 - 22), fill=g)
    # stores
    x0, y0, x1, y1 = rect(811.8, 191.8, 1012.2, 504.9)
    mx = (x0 + x1) / 2
    d.polygon([(mx, y0 + 30), (mx + 12, y0 + 120), (mx + 90, y0 + 170), (mx + 12, y0 + 190), (mx + 8, y1 - 40),
               (mx - 8, y1 - 40), (mx - 12, y0 + 190), (mx - 90, y0 + 170), (mx - 12, y0 + 120)], outline=g, width=2)
    for k, t in enumerate(("1  PAB-250 x60", "2  PAB-250 x60", "3  -", "4  -")):
        d.text((x0 + 10, y1 - 30 - 18 * (3 - k) - 40), t, fill=g, font=f)
    # status gauges, turned
    gg = Image.new("RGB", (141, 248), (0, 0, 0))
    gdd = ImageDraw.Draw(gg)
    for k, (t, v) in enumerate((("FUEL", 0.7), ("THR", 0.55))):
        bx = 25 + 55 * k
        gdd.rectangle((bx, 30, bx + 30, 200), outline=g, width=2)
        gdd.rectangle((bx + 3, 200 - int(167 * v), bx + 27, 197), fill=g)
        gdd.text((bx, 210), t, fill=g, font=f)
    img.paste(gg.rotate(90, expand=True), (int(16.1), int(512 - 143.4)))
    # the wing page in the vacant rect (595.7..803.4 x 1.6..253.9)
    x0, y0, x1, y1 = rect(595.7, 1.6, 803.4, 253.9)
    cx = (x0 + x1) / 2
    d.polygon([(cx - 20, y0 + 10), (cx + 20, y0 + 10), (cx + 14, y0 + 120), (cx + 8, y0 + 175), (cx - 8, y0 + 175),
               (cx - 14, y0 + 120)], outline=g, width=2)
    d.line((cx - 18, y0 + 75, cx + 18, y0 + 75), fill=g, width=1)
    d.line((cx - 14, y0 + 125, cx + 14, y0 + 125), fill=g, width=1)
    d.text((cx - 22, y1 - 40), "100%", fill=g, font=f)
    img.save(out / "canvas.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
