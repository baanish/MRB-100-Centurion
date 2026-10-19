"""The four liveries (docs/SPEC.md, "Liveries"): BDF Matte Gray, BDF Forest Green, PALA Matte Black and PALA Desert
Camo, each a full albedo on the shared skin atlas's UVs, which the game sets as the skin's _Livery
(LiveryBehaviour.SetLivery; docs/M4-ART-PLAN.md, "How the game reads the skin").

Each is the composite's baked albedo repainted per texel: the base paint (the hull's neutral grey, by its colour,
and no cavity paint) takes the livery's colour times the texel's own brightness against the hull grey, so panel
lines, mottling, grime and edge wear carry over. The satin finish every group shares (wing.SATIN: leading-edge
strips, stage collars and end caps, inlet lips) is base paint too, a shade lighter than the hull, so it reads as a
livery-coloured satin; left at its baked grey it showed as pale edges under every livery (owner, 2026-10-17).
Markings, stencils, the engines' hot section (BARE), lights and interiors keep the baked colour. The camouflage is a
function of 3D position (with |x|, since the body's right side reuses the left side's islands outside its text
bands), so it runs across every UV seam. The faction insignia replace the aft body's
star and bar (painted out; the insignia sits in the same text band, unique on both sides, above it) and sit on the
upper and lower skin of the wing whose islands the other wing copies. The insignia are drawn here as vector shapes after the factions' marks:
BDF's shield between three stripes, PALA's ring round a triangle of triangles; the matte liveries take them in greys.

CenturionAuthor.AuthorLiveries reads the files as <stem>_livery_<key>.png and keeps the same names, factions and
colours (LIVERIES).
"""

import math

from . import engines, fuselage_aft, paint
from .paint import poly_sdf, smoothstep

L0 = 0.39  # the hull grey's brightness (paint.PAINT[HULL], sRGB), the ratio's reference
BASE_DIR = tuple(c / (sum(paint.PAINT[paint.HULL]) / 3) for c in paint.PAINT[paint.HULL])
SATIN_METAL = 0.2  # wing.SATIN's metal, the highest a texel may carry and still take the livery
# Satin surfaces that stay bare metal under every livery, by group: the core cowl round the hot exhaust and the
# pylon's heat shield under it.
BARE = {"engines": (engines.CORE_COWL, engines.HEAT_SHIELD)}

# key: (name, faction, sRGB paint or camo tones, insignia style). Camo tones: base, then the blotches in order.
LIVERIES = {
    "bdf_matte_gray": ("BDF Matte Gray", "Boscali", ((0.38, 0.39, 0.405),), "low"),
    "bdf_forest_green": ("BDF Forest Green", "Boscali", ((0.215, 0.275, 0.195),), "colour"),
    "pala_matte_black": ("PALA Matte Black", "Primeva", ((0.125, 0.128, 0.135),), "low"),
    "pala_desert_camo": ("PALA Desert Camo", "Primeva", ((0.66, 0.57, 0.42), (0.47, 0.36, 0.25), (0.78, 0.71, 0.58)), "colour"),
}
# Desert blotches: (feature size m, threshold, seed) for each tone after the base, about 30% and 20% of the skin.
CAMO = ((7.0, 0.56, 41), (5.0, 0.60, 43))

INSIGNIA_D = 1.6  # m across on the body: inside fuselage_aft's 2.14 m text band round its star and bar
INSIGNIA_DEG = 60.0  # its centre's angle from the crown: above the sponson's blend into the flank, which is the struts'
WING_STATION_X = 15.5  # m out on the wing: between the nacelle and the strut foot
WING_D_CHORD = 0.5  # the wing insignia's width as a fraction of the local chord

# The factions' colours, sRGB; the low-visibility set maps each to a grey.
BLACK, WHITE = (0.05, 0.05, 0.055), (0.86, 0.86, 0.84)
BDF_BLUE, BDF_GREEN, PALA_RED = (0.03, 0.22, 0.46), (0.22, 0.42, 0.04), (0.55, 0.04, 0.04)
LOW = {BLACK: (0.10, 0.10, 0.105), WHITE: (0.58, 0.59, 0.60), BDF_BLUE: (0.24, 0.245, 0.25), BDF_GREEN: (0.31, 0.315, 0.32),
       PALA_RED: (0.27, 0.275, 0.28)}


def paint_weight(albedo, metal, cls):
    """How much of each texel is base paint: neutral like the hull grey, between the darkest panel line and the
    lightest worn edge, no more metal than the satin finish (the radome's diverter buttons, 0.25, stay bare) and not
    cavity paint."""
    np = paint.np
    lum = albedo.mean(axis=1)
    chroma = np.abs(albedo - lum[:, None] * np.asarray(BASE_DIR)).max(axis=1) / np.maximum(lum, 1e-3)
    w = smoothstep(0.12, 0.06, chroma) * smoothstep(0.185, 0.215, lum) * smoothstep(0.55, 0.48, lum)
    return w * smoothstep(SATIN_METAL + 0.03, SATIN_METAL + 0.01, metal) * (cls != paint.INTERIOR), lum


def camo_tone(tones, pos):
    np = paint.np
    p = pos.copy()
    p[:, 0] = np.abs(p[:, 0])
    rgb = np.ones((len(pos), 3)) * np.asarray(tones[0])
    for tone, (size, edge, seed) in zip(tones[1:], CAMO):
        cov = smoothstep(edge - 0.006, edge + 0.006, paint.fbm(p, size, 3, seed=seed))
        rgb += (np.asarray(tone) - rgb) * cov[:, None]
    return rgb


# ---------- insignia, in a frame of half-width 1 (x right, y up as seen from outside) ----------
def _layers_bdf(x, y):
    """(sdf, colour) from the bottom up: three stripes each side, the shield outlined in black, split blue and green
    on a diagonal, a white flash in its upper corner."""
    np = paint.np
    out = []
    for k, colour in enumerate((WHITE, BDF_GREEN, BDF_BLUE)):
        y0 = 0.30 - 0.19 * k
        for s in (1, -1):
            pts = [(s * 0.35, y0 + 0.07), (s * 0.98, y0 + 0.07), (s * 0.90, y0 - 0.07), (s * 0.35, y0 - 0.07)]
            d = poly_sdf(x, y, pts)
            out += [(d - 0.035, BLACK), (d, colour)]
    shield = [(-0.48, 0.60), (0.0, 0.48), (0.48, 0.64), (0.42, 0.02), (0.0, -0.66), (-0.42, 0.02)]
    d = poly_sdf(x, y, shield)
    out += [(d - 0.06, BLACK), (d, BDF_GREEN)]
    blue = poly_sdf(x, y, [(-0.6, 0.30), (0.25, -0.75), (-0.6, -0.75)])
    out.append((np.maximum(d, blue), BDF_BLUE))
    flash = poly_sdf(x, y, [(0.06, 0.40), (0.38, 0.52), (0.33, 0.30)])
    out.append((np.maximum(d + 0.02, flash), WHITE))
    return out


def _layers_pala(x, y):
    """(sdf, colour) from the bottom up: a red ring outlined in black with three black nubs carrying white points,
    round an inverted red triangle outlined in black holding six white triangles in rows of 3, 2 and 1."""
    np = paint.np
    r = np.hypot(x, y)
    ring = np.abs(r - 0.70) - 0.08
    out = [(ring - 0.035, BLACK), (ring, PALA_RED)]
    for a in (90.0, 210.0, 330.0):
        t = math.radians(a)
        ux, uy = math.cos(t), math.sin(t)
        nub = [(0.62 * ux + 0.12 * -uy, 0.62 * uy + 0.12 * ux), (0.86 * ux + 0.12 * -uy, 0.86 * uy + 0.12 * ux),
               (0.86 * ux - 0.12 * -uy, 0.86 * uy - 0.12 * ux), (0.62 * ux - 0.12 * -uy, 0.62 * uy - 0.12 * ux)]
        out.append((poly_sdf(x, y, nub), BLACK))
        tip = [(0.84 * ux + 0.09 * -uy, 0.84 * uy + 0.09 * ux), (0.99 * ux, 0.99 * uy), (0.84 * ux - 0.09 * -uy, 0.84 * uy - 0.09 * ux)]
        out.append((poly_sdf(x, y, tip), WHITE))
    tri = [(-0.52, 0.30), (0.52, 0.30), (0.0, -0.60)]
    d = poly_sdf(x, y, tri)
    out += [(d - 0.05, BLACK), (d, PALA_RED)]
    h = 0.27  # each small triangle's height: three rows fill the big one less its margin
    for row, count in enumerate((3, 2, 1)):
        top = 0.25 - row * h
        for k in range(count):
            cx = (k - (count - 1) / 2) * 0.30
            out.append((poly_sdf(x, y, [(cx - 0.12, top - h + 0.05), (cx + 0.12, top - h + 0.05), (cx, top - 0.02)]), WHITE))
    return out


def insignia(faction, style, x, y, px):
    """Coverage-weighted colour of the faction's insignia at frame points (x, y): (rgb (n, 3), alpha (n,)); px is a
    texel in frame units, the anti-aliasing width."""
    np = paint.np
    rgb, alpha = np.zeros((len(x), 3)), np.zeros(len(x))
    for d, colour in (_layers_bdf if faction == "Boscali" else _layers_pala)(x, y):
        cov = np.clip(0.5 - d / px, 0.0, 1.0)
        c = np.asarray(LOW[colour] if style == "low" else colour)
        rgb += (c - rgb) * cov[:, None]
        alpha = alpha + (1 - alpha) * cov
    return rgb, alpha


def body_frames(coords, s, arc, deg):
    """The body's insignia frames: (selection, x, y) per side in fuselage_aft's insignia band, x aft on the +X side
    and forward on the -X side, y toward the crown, in units of half the insignia's width."""
    np = paint.np
    cs = fuselage_aft.INSIGNIA[0]
    half = INSIGNIA_D / 2
    for side in (1, -1):
        v = float(coords.arc_at(cs, side * INSIGNIA_DEG))
        x, y = side * (s - cs) / half, -side * (arc - v) / half
        yield (np.abs(x) < 1.05) & (np.abs(y) < 1.05) & (np.sign(deg) == side), x, y


def old_marking(coords, s, arc):
    """The signed distance to fuselage_aft's star and bar (its disc and bar, as it paints them), both sides."""
    np = paint.np
    cs, ca, R = fuselage_aft.INSIGNIA
    sym = np.full(len(s), 1e9)
    for side in (1, -1):
        v = float(coords.arc_at(cs, side * ca))
        up = -side
        circle = np.hypot(s - cs, arc - v) - R
        bar = paint.rrect_sdf(s, arc, cs - 2.0 * R, cs + 2.0 * R, v + up * 0.35 * R, v - up * 0.31 * R, 0.0)
        sym = np.minimum(sym, np.minimum(circle, bar))
    return sym


def wing_frames(pos, nrm, sel_wing, px):
    """The insignia frames on the wing that owns the islands, upper and lower: a planar projection about the skin
    point over (under) the upper skin's mid chord at WING_STATION_X, x right and y forward as seen from outside, in
    units of half the width. Yields (selection, x, y, frame px)."""
    np = paint.np
    xw = WING_STATION_X * (1.0 if float(np.median(pos[sel_wing, 0])) > 0 else -1.0)
    top = sel_wing & (nrm[:, 2] > 0.7) & (np.abs(pos[:, 0] - xw) < 0.05)
    if not bool(top.any()):
        return
    ys = pos[top, 1]
    y_mid = float((ys.min() + ys.max()) / 2)
    half = WING_D_CHORD * float(ys.max() - ys.min()) / 2
    for up in (1.0, -1.0):
        facing = sel_wing & (nrm[:, 2] * up > 0.7)
        near = facing & (np.abs(pos[:, 0] - xw) < 0.05) & (np.abs(pos[:, 1] - y_mid) < 0.05)
        if not bool(near.any()):
            continue
        z_c = float(pos[near, 2].max() if up > 0 else pos[near, 2].min())
        dx, dy = pos[:, 0] - xw, pos[:, 1] - y_mid
        x = (-dx if up > 0 else dx) / half
        y = -dy / half
        sel = facing & (np.abs(x) < 1.05) & (np.abs(y) < 1.05) & (np.abs(pos[:, 2] - z_c) < 0.25)
        yield sel, x, y, px / half


def paint_liveries(coords, flat, albedo, metal, groups, px):
    """coords: the composite's paint.FuselageCoords; flat: the valid texels' pos, nrm, cls, group (1-based into groups)
    and moving; albedo (n, 3) sRGB and metal (n,) the composite's; px the texel size in metres. Returns
    {key: (n, 3) sRGB albedo}."""
    np = paint.np
    pos, nrm, cls = flat["pos"], flat["nrm"], flat["cls"]
    w, lum = paint_weight(albedo, metal, cls)
    for name, classes in BARE.items():
        if name in groups:
            w = w * ~((flat["group"] == groups.index(name) + 1) & np.isin(cls, classes))
    ratio = lum / L0
    aft = flat["group"] == groups.index("fuselage_aft") + 1 if "fuselage_aft" in groups else np.zeros(len(cls), bool)
    body = aft & np.isin(cls, (paint.HULL,))
    s, deg, arc = np.zeros(len(cls)), np.zeros(len(cls)), np.zeros(len(cls))
    if bool(body.any()):
        s_b, deg_b, arc_b = coords.locate(pos[body])
        s[body], deg[body], arc[body] = s_b, deg_b, arc_b
        # Under the old star and bar the paint takes the livery at the marking's own brightness variation: the dark
        # disc and bar (fuselage_aft.MARKING), or the star and its inner outline in the paint's grey.
        sym = old_marking(coords, s[body], arc[body])
        under = np.clip(0.5 - (sym - 0.015) / px, 0.0, 1.0)
        own = np.where(lum[body] > 0.27, 0.372, 0.175)
        idx = np.nonzero(body)[0]
        ratio[idx] = ratio[idx] * (1 - under) + (lum[idx] / own) * under
        w[idx] = np.maximum(w[idx], under)
    wing = (flat["group"] == groups.index("wing") + 1) & ~flat["moving"] if "wing" in groups else np.zeros(len(cls), bool)
    frames = []
    if bool(body.any()):
        for sel, x, y in body_frames(coords, s, arc, deg):
            frames.append((sel & body, x, y, px / (INSIGNIA_D / 2)))
    if bool(wing.any()):
        frames += list(wing_frames(pos, nrm, wing, px))

    out = {}
    for key, (_, faction, tones, style) in LIVERIES.items():
        target = camo_tone(tones, pos) if len(tones) > 1 else np.ones((len(cls), 3)) * np.asarray(tones[0])
        rgb = albedo + (target * ratio[:, None] - albedo) * w[:, None]
        for sel, x, y, fpx in frames:
            idx = np.nonzero(sel)[0]
            if not len(idx):
                continue
            ink, alpha = insignia(faction, style, x[idx], y[idx], fpx)
            shade = np.clip(ratio[idx], 0.6, 1.4)[:, None]  # the paint's own wear and grime over the insignia
            rgb[idx] = rgb[idx] + (ink * shade - rgb[idx]) * alpha[:, None]
        out[key] = np.clip(rgb, 0.0, 1.0)
    return out
