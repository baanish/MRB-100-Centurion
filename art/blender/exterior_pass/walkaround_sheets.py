"""The walk-around renders on one sheet a group: walkaround_render.py's frames tiled in plan order, each labelled with
part, pose and view. python -I walkaround_sheets.py <render dir> [--cols 6] [--tile 480]"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("dir")
ap.add_argument("--cols", type=int, default=6)
ap.add_argument("--tile", type=int, default=480)
a = ap.parse_args()
d = Path(a.dir)
frames = json.loads((d / "frames.json").read_text())
groups = defaultdict(list)
for f in frames:
    groups[f["group"]].append(f)
w, h = a.tile, a.tile * 3 // 4
for g, fs in sorted(groups.items()):
    fs.sort(key=lambda f: f["frame"])
    rows = (len(fs) + a.cols - 1) // a.cols
    sheet = Image.new("RGB", (w * a.cols, (h + 18) * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for i, f in enumerate(fs):
        x, y = (i % a.cols) * w, (i // a.cols) * (h + 18)
        sheet.paste(Image.open(d / f"{f['frame']}.png").convert("RGB").resize((w, h)), (x, y + 18))
        pose = " ".join(f"{k} {v}" for k, v in sorted(f["pose"].items())) or "rest"
        draw.text((x + 4, y + 3), f"{i + 1}. {f['part']}  {pose}  {f['view']}", fill="black")
    sheet.save(d / f"sheet_{g}.png")
    print("WALKAROUND sheet", g, len(fs), "frames", flush=True)
