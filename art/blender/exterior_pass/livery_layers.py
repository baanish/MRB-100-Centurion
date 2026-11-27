"""The livery kit's layers: each shipped livery (textures/centurion_livery_<key>.png, roundel-free) split into a clean
base colour, a markings layer and a panel line layer that stack back to it, from the paint's own record of which
texels are what (detail_centurion.texture_atlas writes textures/livery_layer_sources/: every livery repainted without
panel lines, and without lines or markings, and the markings' coverage).

Per livery <key>, in <out>:
- <key>_base.png: RGB, the livery with no panel lines, fasteners or markings. Shading baked into the albedo (AO grime,
  mottling, edge wear, soot) stays in it.
- <key>_markings.png: RGBA, the stencils, serials, placards and keep-clear lines (Canvas.paint's markings), alpha their
  coverage. No roundels: the liveries carry none (art/textures/faction_marks.py places them).
- <key>_panel_lines.png: RGBA, black, alpha the grooves' and fastener heads' darkening.
Base, then markings, then panel lines, composited normally (8-bit, sRGB as stored) give the livery within one step
per channel; layers.json records each livery's largest error, the texels over one step, and how far the base strays
from the clean paint where no marking covers it (what of the lines the base still carries).

python -I livery_layers.py <pass textures dir> <s4_uv.json> <out dir>"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

LINER_HALF = 12  # s6_bake.paint_block's primer block, texels either side of the liner point


def load(path, channels=3):
    return np.asarray(Image.open(path).convert("RGBA" if channels == 4 else "RGB"), dtype=np.float32) / 255.0


def lum(a):
    return a.mean(axis=-1)


def split(F, Fn, Fc, alpha, block):
    """(base, markings RGBA, lines RGBA) as uint8 and the composite's error in steps."""
    # panel lines: one black layer whose alpha takes the livery from its no-line paint down to the shipped one
    beta = np.where(np.abs(F - Fn).max(axis=-1) > 0.5 / 255, 1 - lum(F) / np.maximum(lum(Fn), 1e-4), 0.0)
    beta = np.clip(beta, 0.0, 0.98)
    beta[block] = 0.0
    under = np.clip(F / (1 - beta)[..., None], 0.0, 1.0)  # what the lines lie on
    a = np.where(block, 0.0, alpha)
    has = a > 0.5 / 255
    C = np.where(has[..., None], np.clip((under - (1 - a)[..., None] * Fc) / np.maximum(a, 1e-6)[..., None], 0, 1), 0.0)
    B = np.where(has[..., None], np.where((a < 0.999)[..., None], (under - a[..., None] * C) / np.maximum(1 - a, 1e-6)[..., None], Fc), under)
    B = np.clip(B, 0, 1)
    q = lambda x: np.clip(np.round(x * 255), 0, 255)  # noqa: E731
    B8, C8, a8, b8 = q(B), q(C), q(a), q(beta)
    target = q(F)
    for _ in range(3):  # fold the rounding back into the base where it carries enough weight
        comp = (1 - b8 / 255)[..., None] * ((a8 / 255)[..., None] * C8 + (1 - a8 / 255)[..., None] * B8)
        err = target - comp
        w = ((1 - b8 / 255) * (1 - a8 / 255))[..., None]
        B8 = np.clip(B8 + np.where(w > 0.25, np.round(err / np.maximum(w, 1e-6)), 0), 0, 255)
    comp = (1 - b8 / 255)[..., None] * ((a8 / 255)[..., None] * C8 + (1 - a8 / 255)[..., None] * B8)
    err = np.abs(target - comp)
    return (B8.astype(np.uint8), np.dstack([C8, a8]).astype(np.uint8),
            np.dstack([np.zeros_like(C8), b8]).astype(np.uint8), err, has, B)


def main():
    tex, s4, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    src = tex / "livery_layer_sources"
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads(s4.read_text())["report"]
    alpha = load(src / "marks_alpha.png")[..., 0]
    h, w = alpha.shape
    block = np.zeros((h, w), bool)
    for uv in [report["liner_uv"]] + ([report["loud_uv"]] if report.get("loud_uv") else []):
        cx, cy = int(uv[0] * w), int(uv[1] * h)
        row = h - 1 - cy  # the PNG's rows run top-down, Blender's pixels bottom-up
        block[row - LINER_HALF:row + LINER_HALF + 1, cx - LINER_HALF:cx + LINER_HALF] = True
    record = {"format": {"base": "RGB 8-bit sRGB", "markings": "RGBA 8-bit sRGB, straight alpha",
                         "panel_lines": "RGBA 8-bit, black, straight alpha",
                         "stack": "base, markings, panel_lines, normal blend"}, "liveries": {}}
    for f in sorted(tex.glob("centurion_livery_*.png")):
        key = f.stem[len("centurion_livery_"):]
        F, Fn, Fc = load(f), load(src / f"{key}_nolines.png"), load(src / f"{key}_clean.png")
        base, marks, lines, err, has, B = split(F, Fn, Fc, alpha, block)
        Image.fromarray(base, "RGB").save(out / f"{key}_base.png")
        Image.fromarray(marks, "RGBA").save(out / f"{key}_markings.png")
        Image.fromarray(lines, "RGBA").save(out / f"{key}_panel_lines.png")
        ghost = np.abs(B - Fc)[~has].max(axis=-1)
        record["liveries"][key] = {"map": f.name, "max_error_steps": round(float(err.max()), 2),
                                   "texels_over_one_step": int((err > 1.0001).any(axis=-1).sum()),
                                   "base_vs_clean_p99_steps": round(float(np.percentile(ghost, 99) * 255), 2),
                                   "marking_texels": int(has.sum())}
        print("LIVERY LAYERS", key, record["liveries"][key], flush=True)
    (out / "layers.json").write_text(json.dumps(record, indent=1))
    bad = {k: v for k, v in record["liveries"].items() if v["texels_over_one_step"]}
    if bad:
        raise SystemExit(f"livery_layers: the stack misses the livery by more than one step: {bad}")
    print("LIVERY LAYERS PASS", out, flush=True)


if __name__ == "__main__":
    main()
