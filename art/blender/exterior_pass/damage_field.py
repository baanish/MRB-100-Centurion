"""The damage field, by world position: which skin opens and at what health. One source for the bake (s6_bake.torn_damage
paints it into the damage map) and for the faces that need an inward copy (s2 tags them, s3 copies them).

The owner's decision (docs/DECISIONS.md 2026-11-23, G4.1): the damage looks like the stock Darkreach's, matched by its
statistics, never by its texture: a few heavily torn patches per part with very ragged edges and fine speckle round
them, about 17% of the skin open at 0 HP, 4.8 holes per m2, a typical hole of 51 cm2, outlines about 6 times a disc's
(measured on the stock sfb_skin_dmg_b.png). Round 3's panel squares and the Icarus-method
shards both spread evenly and read as camouflage at full damage.

The owner, 2026-11-23 afternoon: the tears straight-sided with sawtooth ends, as the stock's (long straight flanks, a
comb of teeth), not rounded clouds. A tear potential per point: a low-frequency zone mask (ZONE_M across; only its
highest ZONE share tears heavily, the rest stays whole at every health) read at the centre of a CELL_M cell, plus the
cell's own random share, so whole cells open and a tear's sides are the cells' straight shared sides; a comb of
tapering teeth reaches from some open cells into their closed neighbours; fine speckle breaks out round the zones. The higher the potential, the
earlier a point opens: T_AT pins the potential at which it opens at 0, 30, 60 and 100 HP, calibrated by field_tune.py
so the open share follows the stock's (17.4%, 14.5%, 9.4% at 0, 30, 60 HP).

The game opens a texel where D * (alpha - 0.52) + 0.02 < 0, D = 1 - saturate(_HitPoints / 100) (UnitPart.ApplyDamage
sets _HitPoints from the part's raw hit points): 0 HP is the most a part ever opens.

panel_index keeps the old box grid of structural bays, for s2's grouping of members by bay."""
import numpy

ZONE_M, ZONE_EDGE = 3.0, 0.06  # the tearing zones: noise features this many metres across; the zone mask's soft edge
ZONE_AT = 0.56  # zone noise over this tears heavily (the noise sits about 0.5 +- 0.1)
CELL_M = 0.45  # the tears' cells: whole cells open, so a tear's sides are the cells' straight shared sides
W_ZONE, W_CELL = 0.55, 0.45
COMB_SHARE = 0.6  # the share of cell sides that carry a comb of teeth
TOOTH_SPACING_M, TOOTH_TAPER = 0.07, 1.0  # the teeth's pitch along the side; how fast a tooth narrows (1: to a point at its reach)
TOOTH_M, TOOTH_DROP = 0.25, 0.08  # a tooth's typical reach into the closed cell, and the potential it loses over it
W_EDGE_JAG = 0.01  # a little centimetre noise on the tears' sides: a cut edge, not a ruled one
SPECK_M, NEAR_FROM = 0.065, 0.42  # the speckle's spot size; zone noise over NEAR_FROM carries speckle (round the zones)
SPECK_STRETCH = 3.0  # speckle drawn out along x (the span) by this factor: streaks, as the stock's run
# pinned by field_tune.py with the settings below and TEAR60=0.72 TEAR30=0.72 TEAR0=0.7 (the tears' share of the open
# area at 60, 30 and 0 HP; the speckle tops it up to the stock's): on a flat 20 m sheet every one of the four numbers
# within a quarter of the stock's at each health, the big holes as solid as the stock's (0.98 to 0.99; stock 0.97), and
# their outlines as straight (edge_measure.py: 0.27 / 0.28 / 0.25 at 60 / 30 / 0 HP; stock 0.30 / 0.30 / 0.29; the
# rounded field before it 0.13 at 0 HP)
T_TEAR = (0.79506, 0.81833, 0.86984, 0.99701)  # tear potential opening at 0, 30, 60 and 100 HP
T_SPECK = (0.68432, 0.70629, 0.73963, 0.9862)  # speckle potential opening at 0, 30, 60 and 100 HP
TEAR_SHARE = 0.6  # field_tune's default tear share where no TEAR<hp> is given
JAG_M, W_JAG = 0.04, 0.05  # centimetre-scale noise: the edge warp's scale, and a little added to the potential
EDGE_WARP_M = 0.06  # how far the centimetre-scale warp moves an edge: torn teeth, solid insides
SCORCH = 0.03  # tear potential under the 0 HP line that still scorches: the standing rim round each tear
CLOSED_ALPHA = 1.0
PANEL = numpy.array([0.9, 1.1, 0.7])  # the structural bays (s2): x across the span, y along, z up
WARP = 0.06
# the barycentric points (s, t) on each skin triangle where check_damage_area looks through an opened texel, and s2
# casts the same sight lines when it tags the faces that need an inward copy
SIGHT_BARY = [(s, t) for s in numpy.linspace(0.05, 0.95, 6) for t in numpy.linspace(0.05, 0.95, 6) if s + t < 0.98][:16:4]


def open_alpha(hp, np=numpy):
    """The highest alpha that the shader has discarded once the part is down to hp (Icarus damage.open_alpha)."""
    d = np.clip(1 - np.asarray(hp, np.float64) / 100, 1e-6, 1)
    threshold = np.clip(255 * (0.52 - 0.02 / d), 0, 255)
    return np.maximum(np.ceil(threshold) - 1, 0) / 255


def _hash(c, k, np):
    """A repeatable value in [0, 1) per row of c (cell indices, or any floats) for the key k."""
    x = np.sin(c @ np.asarray(k, np.float64)) * 43758.5453
    return x - np.floor(x)


_JIT = ((127.1, 311.7, 74.7), (269.5, 183.3, 246.1), (113.5, 271.9, 124.6))


def _cells(pos, np):
    """The nearest and second nearest of a jittered grid of CELL_M points: (c1, c2, id1, id2, edge distance), the edge
    distance being to the plane halfway between c1 and c2 (the cells' straight shared side)."""
    g = pos / CELL_M
    base = np.floor(g)
    n = len(pos)
    d1 = np.full(n, np.inf)
    d2 = np.full(n, np.inf)
    c1, c2, i1, i2 = (np.zeros((n, 3)) for _ in range(4))
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            for oz in (-1, 0, 1):
                cell = base + np.asarray((ox, oy, oz), np.float64)
                cp = (cell + np.stack([_hash(cell, k, np) for k in _JIT], axis=1)) * CELL_M
                d = ((pos - cp) ** 2).sum(axis=1)
                a = d < d1
                b = ~a & (d < d2)
                d2 = np.where(a, d1, np.where(b, d, d2))
                c2 = np.where(a[:, None], c1, np.where(b[:, None], cp, c2))
                i2 = np.where(a[:, None], i1, np.where(b[:, None], cell, i2))
                d1 = np.where(a, d, d1)
                c1 = np.where(a[:, None], cp, c1)
                i1 = np.where(a[:, None], cell, i1)
    span = np.sqrt(((c2 - c1) ** 2).sum(axis=1))
    return c1, c2, i1, i2, (d2 - d1) / (2 * np.maximum(span, 1e-9))


def _cell_tear(c, cid, paint):
    """A whole cell's tear potential: its zone (read at its centre, so the zone edge follows the cells' straight sides)
    and its own random share."""
    zone = paint.smoothstep(ZONE_AT - ZONE_EDGE, ZONE_AT + ZONE_EDGE, paint.fbm(c, ZONE_M, 3, seed=71))
    return W_ZONE * zone + W_CELL * _hash(cid, (41.3, 289.1, 97.7), paint.np)


def potentials(pos, paint):
    """(tear, speck) potential per point: the tears, whole cells of a jittered CELL_M grid opening in a few zones (merged
    cells: angular holes with long straight sides, as the stock's), with a comb of teeth cut into the skin beyond some of
    their sides; the speckle, small streaks round the zones (spot noise, only where the zone noise is over NEAR_FROM).
    Mirror symmetric (|x|): the two sides' mirrored parts share texels, and the bake paints a shared texel from one side's
    position while s2 tags each side at its own (check_damage_area caught a hole seen from the left strut)."""
    np = paint.np
    pos = np.asarray(pos, np.float64).copy()
    pos[:, 0] = abs(pos[:, 0])
    zn = paint.fbm(pos, ZONE_M, 3, seed=71)
    c1, c2, i1, i2, edge = _cells(pos, np)
    v1, v2 = _cell_tear(c1, i1, paint), _cell_tear(c2, i2, paint)
    # the teeth: on COMB_SHARE of the sides, slits square to the side reach into the closed cell from its open
    # neighbour, opening with it and lengthening as health falls. The slits run along the side's normal as seen on a
    # surface facing up (the wings); elsewhere they cross the side at an angle.
    pair = _hash(i1 + 0.37 * i2, (12.9898, 78.233, 37.719), np)
    nrm = (c2 - c1) / np.maximum(np.sqrt(((c2 - c1) ** 2).sum(axis=1)), 1e-9)[:, None]
    up = np.where((np.abs(nrm[:, 2]) > 0.7)[:, None], np.asarray((1.0, 0.0, 0.0)), np.asarray((0.0, 0.0, 1.0)))
    t = np.cross(nrm, up)
    t = t / np.maximum(np.sqrt((t ** 2).sum(axis=1)), 1e-9)[:, None]
    s = (pos * t).sum(axis=1) / TOOTH_SPACING_M + 10 * pair
    k = np.floor(s)
    reach = TOOTH_M * (0.4 + 0.8 * _hash(np.stack([k, pair, k * pair], axis=1), (7.1, 3.3, 5.9), np))
    tri = np.abs(s - k - 0.5) * 2  # 0 mid-pitch, 1 between teeth: each tooth narrows to a point (sawtooth)
    tooth = np.where(pair < COMB_SHARE, v2 - TOOTH_DROP * (edge / reach + TOOTH_TAPER * tri), -1.0)
    tear = np.maximum(v1, tooth)
    near = paint.smoothstep(NEAR_FROM, NEAR_FROM + 0.08, zn)
    # the speckle's edges torn: its sample position warped by EDGE_WARP_M at centimetre scale (the stock's small holes
    # are ragged streaks; a warp moves an edge but leaves the inside solid)
    pos = pos + EDGE_WARP_M * 2 * (np.stack([paint.fbm(pos, JAG_M, 3, seed=s) for s in (91, 93, 97)], axis=1) - 0.5)
    sp = pos * paint.np.asarray([1.0 / SPECK_STRETCH, 1.0, 1.0])  # streaks along the span, as the stock's specks run
    speck = (0.75 * paint.value_noise(sp, SPECK_M, seed=79) + 0.25 * paint.value_noise(sp, SPECK_M / 3, seed=83)) * near
    jag = W_JAG * (paint.fbm(pos, JAG_M, 2, seed=89) - 0.5)  # a little fine noise on top: specks of rim
    return tear + W_EDGE_JAG * (paint.fbm(pos, JAG_M, 2, seed=89) - 0.5), speck + jag


def _hp(t, at, np):
    t0, t30, t60, t100 = at
    hp = np.interp(t, np.asarray([t0, t30, t60, t100]), np.asarray([0.0, 30.0, 60.0, 100.0]))
    return np.where(t > t0, np.maximum(hp, 0.01), (t - t0) * 400.0)


def hp_of_potentials(tear, speck, np=numpy):
    """The health at or under which a point is open; under 0 where it never opens (down to -SCORCH x 400 on a tear's
    standing rim)."""
    return np.maximum(_hp(tear, T_TEAR, np), _hp(speck, T_SPECK, np))


def open_hp(pos, paint, chunk=1_000_000):
    """Per point: the health at or under which its skin is open; at or under 0 where it never opens. A point opens by 0
    HP where this is over 0."""
    np = paint.np
    pos = np.asarray(pos, np.float64)
    out = np.empty(len(pos))
    for a in range(0, len(pos), chunk):
        out[a:a + chunk] = hp_of_potentials(*potentials(pos[a:a + chunk], paint), np)
    return out


def opens_by_0hp(pos, paint):
    """True where the skin is open at 0 HP, the most the game ever opens."""
    return open_hp(pos, paint) > 0


def panel_index(pos, paint):
    """Each point's structural bay, as integer (i, j, k) rows (s2 groups members by these)."""
    np = paint.np
    warp = np.stack([paint.fbm(pos, 0.6, 3, seed=s) for s in (51, 53, 57)], axis=1) - 0.5
    return np.floor((pos + 2 * WARP * warp) / np.asarray(PANEL)).astype(int)
