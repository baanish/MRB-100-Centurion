"""Place the game's faction roundels on the Centurion, check them, and paint them onto its roundel-free livery maps, as
F-240-Icarus-II does.

The repository never holds the game's roundels, not even inside a livery map. The art pass bakes the four liveries
complete except for the roundels (art/export/textures/centurion_livery_*.png). `place` puts each roundel where
PLACEMENTS says, in aircraft terms, and records it in art/textures/faction_marks.json: per footprint and UV island, the
texel runs, a cubic from texel to the roundel's ink box, and the paint's own shade under it. The record follows the
UVs of the export it was placed on, so a new UV layout needs `place` again, never a hand edit.

`check` holds every recorded roundel to how stock aircraft carry theirs, measured on the export (airframe.py): wholly on
one fixed part, clear of its physical edges (hinge lines, joints, the root), on texels no other surface shares, upright,
read the right way round from outside, left and right mirror images, and whole and unhidden from above or below with the
wing retracted and extended. It fails naming the roundel.

`paint` paints the game's own PALA_roundel.png and BDF_roundel.png, read from the builder's asset export (`game_export`
in tools/local-paths.json, or --game-export), into:
- unity/Assets/Blueprinter/Mods/centurion/Liveries/centurion_livery_<key>.png (gitignored), which
  CenturionAuthor.AuthorLiveries builds the liveries from;
- .cache/faction-marks/marks.json, the input and output hashes Unity's import checks before it builds a livery.

  python art/textures/faction_marks.py place [--export DIR] [--maps DIR]   record where every roundel goes
  python art/textures/faction_marks.py check [--export DIR]                the recorded roundels against the export
  python art/textures/faction_marks.py [--maps DIR] [--out DIR] [--game-export DIR]   paint (Build-Centurion.ps1 runs it)
  python art/textures/faction_marks.py verify-marked       every painted livery carries its roundels
  python art/textures/faction_marks.py check-clean [--require-references] FILE...   no file is game art or shows a roundel
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves the script's folder off the path
import airframe as A  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "art/textures/faction_marks.json"
EXPORT = ROOT / "art/export"
MAPS = ROOT / "art/export/textures"
UNITY = ROOT / "unity/Assets/Blueprinter/Mods/centurion/Liveries"
HASHES = ROOT / ".cache/faction-marks/marks.json"
SUBSAMPLES = 4  # per texel axis: 16 samples a texel box-filter the roundel's edges
PAD = 6  # transparent pixels round the cropped roundel so samples past its edge read clear
MARK_SCALE = 64.0  # texel offsets over this in the cubic's basis keep it well scaled
MARKED_MIN, CLEAN_MAX, MIN_INK_TEXELS = .9, .5, 50  # the Icarus's thresholds
LUMINANCE = np.array((.2126, .7152, .0722))

# Where the roundels go: a deliberate decision, not a measurement. The stock SFB-81 Darkreach, the BDF bomber the
# Centurion shares a factory with, wears its roundel on all four wing faces for both factions, upright with its top
# toward the nose on the upper and lower faces alike, the same way round on both wings, about 0.38 of the local chord
# across, on the fixed outer panel ahead of the aileron; the EW-25 Medusa's are 0.36 to 0.38 of the chord on wing and
# fins, upright along the fin. The owner's choice (docs/DECISIONS.md, 2026-11-22) is "V-tail and wings"; nothing goes
# on the fuselage unless he asks for it (a "side" entry places one). So: both factions on all four wing faces and both
# faces of each V-tail panel, every mark the mirror image of its other side in position and size. The V-tail's panels
# sit 30 degrees off level, so they take the wing's rule: a face within 60 degrees of level reads with its top toward
# the nose; a steeper one, a fin or the fuselage side, with its top up.
# Each entry: label, the part it lies wholly on ({side} is L or R), the face (upper, lower, or side), the centre on the
# left side ((span x, station y) on an upper or lower face, (station y, height z) on a side; the right side mirrors x),
# and the ink width in metres. Frame: x left, y aft, z up, the wing retracted. Sizes are the owner's (2026-11-24,
# "Bigger on top"): larger than the Darkreach's 0.38 of the chord, as large as each face's fixed skin allows. Each box,
# with room to spare, is that part's skin as seen from above (below) with the wing retracted and extended: on top of the
# inner wing at 2 m, between the flap cove, the fuel filler outboard and the walkway inboard (2.75 m would fit; 2 m is
# his size); under the outer wing at 0.9 m, the most that fits between the strut's fitting, the aileron and an access
# panel, since the inner wing's underside is taken by the nacelle, strut and gear; on each V-tail tip panel's upper face
# at 1.2 m, outboard and aft of the tail code ("MR 1043") and the antenna window, ahead of the ruddervator's hinge
# corner; on its lower face at 1.85 m, between the leading edge, the ruddervator and the joint with the inboard panel.
PLACEMENTS = (
    ("wing_upper", "wing_root_{side}", "upper", (8.0, -2.05), 2.0),
    ("wing_lower", "wing_outer_{side}", "lower", (18.6, -.85), .9),
    ("tail_upper", "vtail_tip_{side}", "upper", (7.42, 18.3), 1.2),
    ("tail_lower", "vtail_tip_{side}", "lower", (5.7, 16.72), 1.85),
)
FACTION_MARKS = {"BDF": ("wing_upper", "wing_lower", "tail_upper", "tail_lower"),
                 "PALA": ("wing_upper", "wing_lower", "tail_upper", "tail_lower")}
INK_BOX = {"PALA": (482, 490), "BDF": (500, 293)}  # the stock roundels' ink, px: each mark keeps its own aspect
SHADE_LIVERY = "bdf_matte_gray"  # the plain livery whose brightness under a roundel is the paint's own wear
SHEET_M = .08  # a footprint takes the skin within this of the mark's plane: one face, never the far one
MARGIN_M = .02  # a texel's supersamples reach half a texel (8 mm at 60 px/m) past the ink box
GUTTER_TEXELS = 2  # how far a footprint runs into its island's empty padding (bilinear filtering reads one)
RESIDUAL_TEXELS = .5  # the cubic's worst miss of the true projection; a footprint splits until each piece meets it
# check's thresholds
EDGE_CLEAR_M = .05  # ink from the sheet's open edges: three texels, past the hinge gap and the joint's seam
UP_TOLERANCE_DEG = 3.0
WHOLE_MIN = .97  # printed (and then unhidden) ink area against the roundel's full ink area
SYMMETRY_M, SYMMETRY_SIZE = .03, .02  # left against mirrored right: centre, and relative width, height and area
SMEAR_FACTOR = 4.0  # a face with texels this many times denser than the atlas is a UV smear, not a surface
FACING = .5


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def game_export(arg):
    if arg:
        return Path(arg)
    paths = ROOT / "tools/local-paths.json"
    export = json.loads(paths.read_text()).get("game_export") if paths.is_file() else None
    return Path(export) / "Texture2D" if export else None


def roundel_paths(record, export):
    return {} if export is None else {f: export / (name + ".png") for f, name in record["roundels"].items()}


def faction_roundel(path):
    """The stock roundel, cropped to its ink and premultiplied."""
    if not path or not path.is_file():
        raise SystemExit(f"FACTION MARKS FAIL: {path} not found; pass --game-export or set `game_export` in tools/local-paths.json")
    rgba = np.asarray(Image.open(path).convert("RGBA"), np.float32) / 255
    yy, xx = np.where(rgba[..., 3] > 0)
    rgba = rgba[yy.min():yy.max() + 1, xx.min():xx.max() + 1]
    rgba[..., :3] *= rgba[..., 3:]
    return np.pad(rgba, ((PAD, PAD), (PAD, PAD), (0, 0)))


def ink_to_uv(s, t, decal):
    ph, pw = decal.shape[:2]
    return .5 + (s - .5) * (pw - 2 * PAD) / pw, .5 + (t - .5) * (ph - 2 * PAD) / ph


def sample(image, u, v):
    h, w = image.shape[:2]
    x, y = np.clip(u, 0, 1) * (w - 1), np.clip(v, 0, 1) * (h - 1)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - ix)[..., None], (y - iy)[..., None]
    jx, jy = np.minimum(ix + 1, w - 1), np.minimum(iy + 1, h - 1)
    return ((1 - fx) * (1 - fy) * image[iy, ix] + fx * (1 - fy) * image[iy, jx] + (1 - fx) * fy * image[jy, ix] + fx * fy * image[jy, jx])


def mark_basis(col, row, terms):
    x, y = np.asarray(col, np.float64) / MARK_SCALE, np.asarray(row, np.float64) / MARK_SCALE
    return np.stack([x ** (d - j) * y ** j for d in range(4) for j in range(d + 1)][:terms], -1)


def mark_texels(mark):
    runs = np.array(mark["runs"])
    lengths = runs[:, 2] - runs[:, 1]
    return np.repeat(runs[:, 0], lengths), np.concatenate([np.arange(c0, c1) for _, c0, c1 in runs])


def mark_st(mark, cols, rows):
    coefficients = np.array(mark["coefficients"])
    basis = mark_basis(cols - mark["origin"][0], rows - mark["origin"][1], coefficients.shape[1])
    return (basis @ coefficients.T).T


def coverage(mark, decal, size):
    """Premultiplied roundel RGBA over the mark's footprint texels, and their flat indices into a size-square atlas."""
    rows, cols = mark_texels(mark)
    offsets = (np.arange(SUBSAMPLES) + .5) / SUBSAMPLES - .5
    ink = np.zeros((len(rows), 4), np.float32)
    for oy in offsets:
        for ox in offsets:
            s, t = mark_st(mark, cols + ox, rows + oy)
            u, v = ink_to_uv(s, t, decal)
            inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
            ink[inside] += sample(decal, u[inside], v[inside])
    return rows * size + cols, ink / SUBSAMPLES ** 2


# ---- place ----

def part_texels(frame, size, part):
    """Every atlas texel of a part's skin: rows, columns, the triangle under it, world position and winding normal.
    A texel under two coincident triangles (the two-sided skin's inward copy) is listed once."""
    rows, cols, tris, pos = [], [], [], []
    for k in np.flatnonzero(frame["skin"] & (frame["part"] == frame["names"].index(part))):
        t = A.atlas_px(frame, size, k)
        x0, y0 = np.maximum(np.floor(t.min(0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(t.max(0)).astype(int), size - 1)
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        w = A.barycentric(t, xx, yy)
        if w is None:
            continue
        inside = (w > -1e-9).all(-1)
        rows.append(yy[inside])
        cols.append(xx[inside])
        tris.append(np.full(inside.sum(), k))
        pos.append(w[inside] @ frame["corners"][k])
    rows, cols, tris, pos = (np.concatenate(a) for a in (rows, cols, tris, pos))
    _, first = np.unique(rows * size + cols, return_index=True)
    c = frame["corners"][tris[first]]
    n = np.cross(c[:, 1] - c[:, 0], c[:, 2] - c[:, 0])
    return rows[first], cols[first], tris[first], pos[first], n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def face_axis(face, side):
    return np.array({"upper": (0., 0., 1.), "lower": (0., 0., -1.), "side": (float(side), 0., 0.)}[face])


def reference_up(normal):
    """Stock's upright: top toward the nose on a face within 60 degrees of level, top up on a steeper one."""
    ref = np.array((0., -1., 0.)) if abs(normal[2]) >= .5 else np.array((0., 0., 1.))
    up = ref - (ref @ normal) * normal
    return up / np.linalg.norm(up)


def mark_frame(frame, texels, placement, side, faction):
    """The roundel's plane on the skin: centre, outward normal, up and right (seen from outside), ink width and height."""
    _, _, _, pos, nrm = texels
    label, part, face, (a, b), width = placement
    axis = face_axis(face, side)
    flat, centre = (pos[:, :2], (a * side, b)) if face != "side" else (pos[:, 1:], (a, b))
    facing = np.abs(nrm @ axis) > FACING
    near = facing & (np.linalg.norm(flat - centre, axis=1) < .1)
    if not near.any():
        raise SystemExit(f"FACTION MARKS FAIL: {label} has no {face} skin of {part} at {centre}")
    outer = near & (pos @ axis > (pos[near] @ axis).max() - SHEET_M)
    height_fit, *_ = np.linalg.lstsq(np.c_[flat[outer], np.ones(outer.sum())], pos[outer] @ axis, rcond=None)
    first, second = (np.eye(3)[0], np.eye(3)[1]) if face != "side" else (np.eye(3)[1], np.eye(3)[2])
    c = first * centre[0] + second * centre[1] + axis * (height_fit @ (*centre, 1.))  # the skin at exactly the station
    if A.first_hit(frame, c + axis * 1e-3, axis) < .3:
        raise SystemExit(f"FACTION MARKS FAIL: {label}: {part} is not the {face} skin at {centre}; another surface covers it")
    local = facing & (np.linalg.norm(pos - c, axis=1) < width / 2) & ((pos - c) @ axis > -SHEET_M)
    n = (nrm[local] * np.sign(nrm[local] @ axis)[:, None]).mean(0)
    n /= np.linalg.norm(n)
    up = reference_up(n)
    ink_w, ink_h = INK_BOX[faction]
    return c, n, up, np.cross(up, n), width, width * ink_h / ink_w


def islands(rows, cols):
    """Connected texel groups (4-neighbour): a footprint split by a UV seam is one mark per island."""
    at = {(int(r), int(c)): k for k, (r, c) in enumerate(zip(rows, cols))}
    label = -np.ones(len(rows), int)
    n = 0
    for k in range(len(rows)):
        if label[k] >= 0:
            continue
        stack, label[k] = [k], n
        while stack:
            j = stack.pop()
            r, c = int(rows[j]), int(cols[j])
            for q in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                m = at.get(q)
                if m is not None and label[m] < 0:
                    label[m] = n
                    stack.append(m)
        n += 1
    return [np.nonzero(label == i)[0] for i in range(n)]


def gutter(frame, size, rows, cols, st):
    """Texels within GUTTER_TEXELS of an island that no skin triangle covers, with the island's own ink coordinates
    carried out to them: the GPU's filtering reads them at the island's rim, so a roundel crossing a UV seam would
    otherwise show a thin line of bare paint along it."""
    have = set(zip(rows.tolist(), cols.tolist()))
    ring = {(r + dr, c + dc) for r, c in have for dr in range(-GUTTER_TEXELS, GUTTER_TEXELS + 1)
            for dc in range(-GUTTER_TEXELS, GUTTER_TEXELS + 1)} - have
    if not ring:
        return np.zeros(0, int), np.zeros(0, int), np.zeros((0, 2))
    gr, gc = (np.array(a) for a in zip(*sorted(ring)))
    inside = (gr >= 0) & (gr < size) & (gc >= 0) & (gc < size)
    gr, gc = gr[inside], gc[inside]
    candidates = A.uv_bbox_overlaps(frame, size, gc, gr)
    used, _, _ = A.texel_cover(frame, size, gr, gc, candidates[frame["skin"][candidates]])
    free = np.ones(len(gr), bool)
    free[used] = False
    gr, gc = gr[free], gc[free]
    basis = mark_basis(cols - cols.min(), rows - rows.min(), 10)
    coef, *_ = np.linalg.lstsq(basis, st, rcond=None)
    return gr, gc, mark_basis(gc - cols.min(), gr - rows.min(), 10) @ coef


def make_mark(faction, label, rows, cols, st, shade):
    """One footprint: runs (row, first col, end col), the cubic from texel offsets to the ink box s, t (s right, t down
    the roundel image), and the paint's shade where it is not 1."""
    origin = [float(cols.min()), float(rows.min())]
    basis = mark_basis(cols - origin[0], rows - origin[1], 10)
    coef, *_ = np.linalg.lstsq(basis, st, rcond=None)
    err = np.abs(basis @ coef - st).max() * max(float(cols.max() - cols.min()), float(rows.max() - rows.min()), 1.0)
    runs = []
    for r in np.unique(rows):
        cs = np.sort(cols[rows == r])
        breaks = np.flatnonzero(np.diff(cs) > 1)
        for a, b in zip(np.r_[0, breaks + 1], np.r_[breaks, len(cs) - 1]):
            runs.append([int(r), int(cs[a]), int(cs[b]) + 1])
    off = np.abs(shade - 1) > .01
    return {"faction": faction, "label": label, "origin": origin, "coefficients": coef.T.tolist(),
            "max_residual_texels": round(float(err), 3), "runs": runs,
            "shade": [[int(r), int(c), round(float(s), 3)] for r, c, s in zip(rows[off], cols[off], shade[off])]}


def fitted_marks(faction, label, rows, cols, st, shade):
    """make_mark, split into halves along the longer side until each piece's cubic stays within RESIDUAL_TEXELS."""
    m = make_mark(faction, label, rows, cols, st, shade)
    if m["max_residual_texels"] <= RESIDUAL_TEXELS or len(rows) < 64:
        return [m]
    half = cols <= np.median(cols) if np.ptp(cols) >= np.ptp(rows) else rows <= np.median(rows)
    if half.all() or not half.any():
        return [m]
    return [p for h in (half, ~half) for p in fitted_marks(faction, label, rows[h], cols[h], st[h], shade[h])]


def place(record, export, maps):
    """Every roundel of PLACEMENTS on the export's skin, as record marks; the liveries' map hashes from `maps`."""
    size = record["atlas_size"]
    frame = A.load_airframe(export)
    shade_map = np.asarray(Image.open(maps / record["liveries"][SHADE_LIVERY]["map"]).convert("RGB"), np.float64) / 255
    lum = shade_map @ LUMINANCE
    marks, placed, cache = [], [], {}
    for faction, labels in FACTION_MARKS.items():
        for placement in (p for p in PLACEMENTS if p[0] in labels):
            for side, letter in ((1, "L"), (-1, "R")):
                part = placement[1].format(side=letter)
                if part not in cache:
                    cache[part] = part_texels(frame, size, part)
                texels = cache[part]
                rows, cols, _, pos, nrm = texels
                c, n, up, right, width, height = mark_frame(frame, texels, placement, side, faction)
                s = .5 + (pos - c) @ right / width
                t = .5 - (pos - c) @ up / height
                ms, mt = MARGIN_M / width, MARGIN_M / height
                sel = ((np.abs(nrm @ n) > FACING) & (np.abs((pos - c) @ n) < SHEET_M)
                       & (s >= -ms) & (s <= 1 + ms) & (t >= -mt) & (t <= 1 + mt))
                label = f"{placement[0]}_{letter}"
                r, cl, st = rows[sel], cols[sel], np.stack([s[sel], t[sel]], -1)
                under = lum[r, cl]
                shade = np.clip(under / np.median(under), .6, 1.4)
                for ix in islands(r, cl):
                    if len(ix) >= 20:
                        gr, gc, gst = gutter(frame, size, r[ix], cl[ix], st[ix])
                        marks.extend(fitted_marks(faction, label, np.r_[r[ix], gr], np.r_[cl[ix], gc], np.r_[st[ix], gst],
                                                  np.r_[shade[ix], np.ones(len(gr))]))
                placed.append({"faction": faction, "label": label, "part": part, "face": placement[2],
                               "centre": np.round(c, 4).tolist(), "normal": np.round(n, 4).tolist(),
                               "up": np.round(up, 4).tolist(), "size_m": [round(width, 4), round(height, 4)],
                               "part_sha256": frame["sha256"][part]})
                print(f"FACTION MARKS PLACE {faction} {label}: {part} {placement[2]}, {width:.2f} x {height:.2f} m at "
                      f"{np.round(c, 2).tolist()}, {int(sel.sum())} texels", flush=True)
    for livery in record["liveries"].values():
        livery["map_sha256"] = sha256(maps / livery["map"])
    return {**record, "placements": placed, "marks": marks}


# ---- check ----

def mark_groups(record):
    groups = {}
    for mark in record["marks"]:
        groups.setdefault((mark["faction"], mark["label"]), []).append(mark)
    return groups


def mirror_key(label):
    return "_".join("?" if w in ("L", "R") else w for w in label.split("_"))


def measure_mark(frames, marks, decal, size, density, atlas_density):
    """One roundel (all its footprint pieces) measured on the export. Returns a dict of measurements and a list of
    problems."""
    frame = frames[0]
    rows, cols, alpha, st = [], [], [], []
    for mark in marks:
        index, ink = coverage(mark, decal, size)
        r, c = index // size, index % size
        rows.append(r)
        cols.append(c)
        alpha.append(ink[:, 3])
        st.append(np.stack(mark_st(mark, c.astype(float), r.astype(float)), -1))
    rows, cols, alpha, st = (np.concatenate(a) for a in (rows, cols, alpha, st))
    inked = alpha > .01
    rows, cols, alpha, st = rows[inked], cols[inked], alpha[inked], st[inked]
    problems = []
    candidates = A.uv_bbox_overlaps(frame, size, cols, rows)
    texel, tri, pos = A.texel_cover(frame, size, rows, cols, candidates[frame["skin"][candidates]])
    smear = density[tri] > SMEAR_FACTOR * atlas_density
    smear_parts = Counter(frame["names"][p] for p in frame["part"][tri[smear]])
    texel, tri, pos = texel[~smear], tri[~smear], pos[~smear]
    if not len(tri):
        return {"part": None}, ["prints on no skin"]
    part_ids = frame["part"][tri]
    own_part = Counter(part_ids.tolist()).most_common(1)[0][0]
    part = frame["names"][own_part]
    mine = part_ids == own_part
    # the mark's own surface at each texel; anything else under the same texel is somewhere else on the airframe
    own_pos = np.full((len(rows), 3), np.nan)
    own_pos[texel[mine]] = pos[mine]
    own_area = np.full(len(rows), np.nan)
    own_area[texel[mine]] = 1 / density[tri[mine]] ** 2  # each texel's world area, from its own triangle
    elsewhere = ~mine | (np.linalg.norm(pos - own_pos[texel], axis=1) > .02)
    shared = Counter(frame["names"][p] for p in frame["part"][tri[elsewhere]])
    shared_texels = len(np.unique(texel[elsewhere]))
    on = ~np.isnan(own_pos[:, 0])
    if part in frame["moving"]:
        problems.append(f"lies on {part}, which moves")
    if shared_texels:
        problems.append(f"shares {shared_texels} inked texels with " + ", ".join(f"{n} ({k})" for n, k in shared.most_common()))
    p, a_, s_ = own_pos[on], alpha[on], st[on]
    # the roundel's plane from the cubic: world ~ origin + s * right * width - t * up * height
    fit, *_ = np.linalg.lstsq(np.c_[s_, np.ones(len(s_))], p, rcond=None)
    right_w, down_h, origin = fit
    width, height = float(np.linalg.norm(right_w)), float(np.linalg.norm(down_h))
    right, up = right_w / width, -down_h / height
    ink_fraction = float(decal[PAD:-PAD, PAD:-PAD, 3].mean())
    full = ink_fraction * width * height
    printed = float((a_ * own_area[on]).sum())
    centre = (p * a_[:, None]).sum(0) / a_.sum()
    c = frame["corners"][tri[mine]]
    n = np.cross(c[:, 1] - c[:, 0], c[:, 2] - c[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    n = (n * np.sign(n @ n[0])[:, None]).mean(0)
    n /= np.linalg.norm(n)
    surface = p[np.argmin(np.linalg.norm(p - centre, axis=1))]  # the centroid of a curved skin lies inside it
    if A.first_hit(frame, surface + n * 1e-3, n) < A.first_hit(frame, surface - n * 1e-3, -n):
        n = -n  # outward is the side with more room: the far skin of a wing or a fin is the nearer hit inward
    ref = reference_up(n)
    tilt = float(np.degrees(np.arccos(np.clip(up @ ref, -1, 1))))
    mirrored = float(np.cross(right, up) @ n) < 0
    if tilt > UP_TOLERANCE_DEG:
        problems.append(f"top points {tilt:.0f} deg off " + ("the nose" if abs(n[2]) >= .5 else "up"))
    if mirrored:
        problems.append("reads mirrored from outside")
    sheet = A.physical_edges(frame, np.flatnonzero(frame["skin"] & (frame["part"] == own_part)))
    solid = a_ > .5
    edge = float(A.segment_distance(p[solid][::max(1, solid.sum() // 4000)], sheet).min()) if solid.any() else 0.
    if edge < EDGE_CLEAR_M:
        problems.append(f"ink {edge * 1000:.0f} mm from an open edge of {part} (min {EDGE_CLEAR_M * 1000:.0f}): a hinge line, joint or root")
    whole = printed / full
    if whole < WHOLE_MIN:
        problems.append(f"prints {whole:.0%} of its ink area (clipped off its skin)")
    axis, sign = (2, np.sign(n[2])) if abs(n[2]) >= .5 else (0, np.sign(n[0]))
    view = ("from above" if sign > 0 else "from below") if axis == 2 else "from the side"
    seen = {}
    step = max(1, len(p) // 4000)
    for extension, posed in frames.items():
        shift = posed["corners"][tri[mine][0]].mean(0) - frame["corners"][tri[mine][0]].mean(0)
        hidden = A.occluded(posed, p[::step] + shift, axis, sign, ())
        seen[extension] = float((a_[::step] * ~hidden).sum() / a_[::step].sum()) * whole
        if seen[extension] < WHOLE_MIN:
            problems.append(f"shows {seen[extension]:.0%} of its ink {view} with the wing "
                            + ("extended" if extension else "retracted"))
    return {"part": part, "centre": centre, "normal": n, "up": up, "size": (width, height), "area": printed,
            "tilt": tilt, "edge": edge, "whole": whole, "seen": seen, "view": view, "smear": smear_parts}, problems


def check(record, export, decals):
    """Every recorded roundel measured on the export; prints one line a roundel and returns the problems."""
    size = record["atlas_size"]
    frames = {e: A.load_airframe(export, e) for e in (0.0, 1.0)}
    density, atlas_density = A.texel_density(frames[0.0], size)
    problems, measured = [], {}
    for placed in record.get("placements", ()):
        if frames[0.0]["sha256"].get(placed["part"]) != placed["part_sha256"]:
            problems.append(f"{placed['faction']} {placed['label']}: placed on another export of {placed['part']}; run `place`")
    for (faction, label), marks in sorted(mark_groups(record).items()):
        m, found = measure_mark(frames, marks, decals[faction], size, density, atlas_density)
        measured[faction, label] = m
        problems += [f"{faction} {label}: {p}" for p in found]
        if m["part"] is None:
            continue
        print(f"FACTION MARKS CHECK {faction} {label}: {m['part']}, {m['size'][0]:.2f} x {m['size'][1]:.2f} m at "
              f"{np.round(m['centre'], 2).tolist()}, top {m['tilt']:.1f} deg off, {m['edge'] * 1000:.0f} mm from an edge, "
              f"whole {m['whole']:.0%}, seen {m['view']} {m['seen'][0.0]:.0%} retracted {m['seen'][1.0]:.0%} extended"
              + (f"; NOTE under UV-smeared faces of {', '.join(sorted(m['smear']))} (not a placement fault)" if m["smear"] else ""))
    for (faction, label), m in measured.items():
        if m["part"] is None or label.split("_")[-1] != "L" and "_L_" not in label:
            continue
        other = next((k for k in measured if k[0] == faction and k[1] != label and mirror_key(k[1]) == mirror_key(label)), None)
        if other is None:
            problems.append(f"{faction} {label}: no right-side copy")
            continue
        o = measured[other]
        if o["part"] is None:
            continue
        gap = float(np.linalg.norm(m["centre"] * (-1, 1, 1) - o["centre"]))
        size_gap = max(abs(a / b - 1) for a, b in zip((*m["size"], m["area"]), (*o["size"], o["area"])))
        if gap > SYMMETRY_M or size_gap > SYMMETRY_SIZE:
            problems.append(f"{faction} {label} and {other[1]}: not mirror images ({gap * 1000:.0f} mm apart mirrored, "
                            f"size or area {size_gap:.0%} apart)")
    return problems


# ---- paint and the clean checks ----

def paint(record, maps, out, export):
    """Each livery map with its faction's roundels. The record carries the hash of every roundel-free map it was made
    for, so a map from another bake (other UVs, other footprints) stops here."""
    size = record["atlas_size"]
    paths = roundel_paths(record, export)
    decals = {f: faction_roundel(paths.get(f)) for f in record["roundels"]}
    inputs = {f: sha256(p) for f, p in paths.items()}
    outputs = {}
    out.mkdir(parents=True, exist_ok=True)
    for livery in record["liveries"].values():
        base = maps / livery["map"]
        if sha256(base) != livery["map_sha256"]:
            raise SystemExit(f"FACTION MARKS FAIL: {base} is not the map art/textures/faction_marks.json was recorded for; export the bake that wrote both")
        colour = np.asarray(Image.open(base).convert("RGB"), np.float64).reshape(-1, 3) / 255
        for mark in record["marks"]:
            if mark["faction"] != livery["faction"]:
                continue
            index, ink = coverage(mark, decals[mark["faction"]], size)
            shade = np.ones(len(index))
            lookup = {int(i): k for k, i in enumerate(index)}
            for r, c, s in mark.get("shade", []):
                k = lookup.get(r * size + c)
                if k is not None:
                    shade[k] = s
            alpha = ink[:, 3:4]
            colour[index] = colour[index] * (1 - alpha) + ink[:, :3] * shade[:, None]
        target = out / livery["map"]
        Image.fromarray(np.uint8(np.clip(colour, 0, 1) * 255 + .5).reshape(size, size, 3)).save(target)
        outputs[livery["map"]] = sha256(target)
        print("FACTION MARKS", livery["map"], livery["faction"], flush=True)
    return inputs, outputs


def correlations(rgb, record, faction, decal):
    """Per roundel (all the marks of one label: a footprint is tiled until each tile's cubic fits, and a tile inside
    one colour of the roundel says nothing alone), the correlation of rgb with the roundel at its inked texels."""
    groups = {}
    for mark in record["marks"]:
        if mark["faction"] != faction:
            continue
        index, ink = coverage(mark, decal, record["atlas_size"])
        inked = ink[:, 3] > .5
        g = groups.setdefault(mark["label"], ([], []))
        g[0].append(index[inked])
        g[1].append(ink[inked])
    found = []
    for idx, ink in groups.values():
        idx, ink = np.concatenate(idx), np.concatenate(ink)
        if len(idx) < MIN_INK_TEXELS:
            continue
        logo = (ink[:, :3] / ink[:, 3:]) @ LUMINANCE
        texture = rgb[idx] @ LUMINANCE
        found.append(float(np.corrcoef(texture, logo)[0, 1]) if texture.std() > 1e-9 and logo.std() > 1e-9 else 0.)
    return found


def read_rgb(path, size):
    image = Image.open(path).convert("RGB")
    return None if image.size != (size, size) else np.asarray(image, np.float64).reshape(-1, 3) / 255


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", nargs="?", default="paint", choices=("place", "check", "paint", "verify-marked", "check-clean"))
    ap.add_argument("files", nargs="*")
    ap.add_argument("--record", type=Path, default=RECORD)
    ap.add_argument("--export", type=Path, default=EXPORT)
    ap.add_argument("--maps", type=Path, default=MAPS)
    ap.add_argument("--out", type=Path, default=UNITY)
    ap.add_argument("--hashes", type=Path, default=HASHES)
    ap.add_argument("--game-export", default=None, help="the asset export's Texture2D folder")
    ap.add_argument("--require-references", action="store_true")
    a = ap.parse_intermixed_args()
    record = json.loads(a.record.read_text())
    export = game_export(a.game_export)
    if a.command == "place":
        record = place(record, a.export.resolve(), a.maps.resolve())
        a.record.write_text(json.dumps(record))
        print(f"FACTION MARKS PLACE PASS: {len(record['placements'])} roundels in {len(record['marks'])} footprints, {a.record}")
        return 0
    if a.command == "check":
        decals = {f: faction_roundel(p) for f, p in roundel_paths(record, export).items()}
        problems = check(record, a.export.resolve(), decals)
        for p in problems:
            print("FACTION MARKS FAIL:", p)
        print("FACTION MARKS CHECK " + ("FAIL" if problems else "PASS: every roundel whole, upright, symmetric and seen, on fixed skin"))
        return 1 if problems else 0
    if a.command == "paint":
        inputs, outputs = paint(record, a.maps.resolve(), a.out.resolve(), export)
        inputs["record"] = sha256(a.record)
        a.hashes.parent.mkdir(parents=True, exist_ok=True)
        a.hashes.write_text(json.dumps({"inputs": inputs, "outputs": outputs}, indent=2) + "\n")
        print(f"FACTION MARKS PASS: {len(outputs)} liveries with roundels in {a.out}")
        return 0
    paths = roundel_paths(record, export)
    if a.command == "verify-marked":
        outputs = json.loads(a.hashes.read_text())["outputs"] if a.hashes.is_file() else {}
        problems = []
        for livery in record["liveries"].values():
            path = a.out / livery["map"]
            if not path.is_file() or outputs.get(livery["map"]) != sha256(path):
                problems.append(f"{livery['map']} is not the painted output")
                continue
            scores = correlations(read_rgb(path, record["atlas_size"]), record, livery["faction"], faction_roundel(paths.get(livery["faction"])))
            if not scores or min(scores) < MARKED_MIN:
                problems.append(f"{livery['map']} lacks its {livery['faction']} roundels (correlation {min(scores, default=0):.2f}, needs {MARKED_MIN})")
        for p in problems:
            print("FACTION MARKS FAIL:", p)
        print("FACTION MARKS VERIFY " + ("FAIL" if problems else "PASS: every painted livery carries its roundels"))
        return 1 if problems else 0
    forbidden = {}
    if a.hashes.is_file():
        forbidden.update({sha: f"the painted {n}" for n, sha in json.loads(a.hashes.read_text())["outputs"].items()})
    present = {f: p for f, p in paths.items() if p.is_file()}
    forbidden.update({sha256(p): f"the stock {p.name}" for p in present.values()})
    if not forbidden and a.require_references:
        print("ROUNDEL FAIL: no stock roundels or painted-output hashes to check against")
        return 1
    by_map = {l["map"]: l["faction"] for l in record["liveries"].values()}
    problems = []
    for path in map(Path, a.files):
        digest = sha256(path)
        if digest in forbidden:
            problems.append(f"{path}: is {forbidden[digest]}")
            continue
        faction = by_map.get(path.name.split("__")[-1])
        rgb = read_rgb(path, record["atlas_size"]) if faction in present else None
        if rgb is None:
            continue
        scores = correlations(rgb, record, faction, faction_roundel(present[faction]))
        if scores and max(scores) > CLEAN_MAX:
            problems.append(f"{path}: shows the {faction} roundel (correlation {max(scores):.2f}, limit {CLEAN_MAX})")
    for p in problems:
        print("ROUNDEL FAIL:", p)
    print(f"ROUNDEL CHECK {'FAIL' if problems else 'PASS'}: {len(a.files)} files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
