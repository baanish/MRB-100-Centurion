"""The Centurion's line art for the cockpit and the HUD, drawn from the step 6.1 blockout seen from above, light grey on
transparent as the stock sprites are (the game tints them). CenturionAuthor.Cockpit.cs imports each and lays it out from
the JSON written beside it:
- centurion_status_top.png (+ .json): every render part's outline with the bay doors under the belly dashed through the
  body; the tac screen's weapon panel, and the frame of the HUD's damage diagram;
- centurion_span_root/_stage1/_stage2.png and centurion_span.json: the span gauge, the right half in plan with the
  root wing fixed and each telescoping stage on its own sprite, with where each stage's outboard end sits retracted and
  extended (read from both spans' blends), so the plugin slides the stages (src/Centurion/SpanGauge.cs);
- Damage/centurion_part_<part>.png and centurion_damage.json: each part the game damages (a mesh carrying its own
  mass_kg, or a control surface's mesh under a hinge empty that does) filled, cropped from the status frame, for the
  damage diagram, which colours a part's sprite as it loses hit points.

blender --background --factory-startup --python art/blender/status_silhouette.py -- [--blend PATH] [--out DIR]

--blend defaults to .cache/art/blockout_s61/centurion_s61_retracted.blend (the retracted span: the extended wing would
leave the body a sliver; the span gauge also opens the _extended blend beside it); --out to the mod's Cockpit folder.
Coordinates in the JSON are metres: x outboard along the right wing (Blender -X), s the station."""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part_splits  # noqa: E402
from m4 import render, texture  # noqa: E402
from m4.blockout import load_blockout  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SUPERSAMPLE = 4  # lines are drawn at 4x and box-filtered down
GREY = 0.81  # the stock sprites' line colour (206 of 255)
BAY_DOORS = ("baydoor_FL_visible", "baydoor_FR_visible", "baydoor_AL_visible", "baydoor_AR_visible")
DASH_PX = 24  # at 4x: the bay doors' dashes
# The status frame: the square it covers (the 45 m length and 43.6 m span with a margin), 512 px as the stock silhouettes.
STATUS = "centurion_status_top"
STATUS_SIZE_M, STATUS_CENTRE_STATION, STATUS_PX = 48.0, 22.5, 512
STATUS_LINES = {"outline": (3, 1.0), "parts": (2, 0.8), "bays": (2, 0.55)}  # radius at 4x, alpha
# The span gauge: 16 px a metre, as wide on the HUD as the stock gauge's art; lines about 4 px wide.
SPAN, SPAN_PX_PER_M, SPAN_PAD_M = "centurion_span", 16, 0.4
SPAN_LINES = {"outline": (9, 1.0), "parts": (6, 0.8)}
# Outboard in order, each with the pieces that ride it (the part tree, art/blender/part_splits.py: stage 2 carries the
# wingtip); each nests in the one before, the first in the inner wing, whose outboard end is ROOT_WING's
STAGES = (("wing_tele1_R",), ("wing_tele2_R", "wing_tip_R"))
ROOT_WING = "wing_outer_R"
DAMAGE = "centurion_damage"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"blend": REPO / ".cache/art/blockout_s61/centurion_s61_retracted.blend",
            "out": REPO / "unity/Assets/Blueprinter/Mods/centurion/Cockpit"}
    for key, value in zip(argv[::2], argv[1::2]):
        if key not in ("--blend", "--out"):
            raise SystemExit(f"unknown argument {key}")
        opts[key[2:]] = Path(value)
    return opts


class TopView:
    """An orthographic camera looking down, nose up, the right wing on the right, rendering flat object colours that
    encode each part's index."""

    def __init__(self, bl, parts):
        self.bl, self.parts = bl, parts
        scene = self.scene = bpy.context.scene
        self.cam = bpy.data.objects.new("status_cam", bpy.data.cameras.new("status_cam"))
        scene.collection.objects.link(self.cam)
        self.cam.data.type, self.cam.data.clip_end = "ORTHO", 500
        self.cam.rotation_euler = (0.0, 0.0, np.pi)
        scene.camera = self.cam
        scene.render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.light, shading.color_type = "FLAT", "OBJECT"
        shading.show_cavity = shading.show_shadows = shading.show_object_outline = shading.show_specular_highlight = False
        scene.display.render_aa = "OFF"
        scene.view_settings.view_transform, scene.view_settings.look = "Standard", "None"
        scene.render.dither_intensity = 0.0
        scene.render.film_transparent = True
        scene.render.use_stamp = False
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format, scene.render.image_settings.color_mode = "PNG", "RGBA"
        for i, o in enumerate(parts):  # scene-linear colours the Standard view writes back as these 8-bit codes
            o.color = (*render.srgb_to_linear([(8 * (i % 32) + 4) / 255, (8 * (i // 32) + 4) / 255, 0.0]), 1.0)

    def frame(self, rect, px_per_m):
        """Look at rect (x0, x1, s0, s1); returns it snapped to whole pixels."""
        x0, x1, s0, s1 = rect
        w, h = max(1, round((x1 - x0) * px_per_m)), max(1, round((s1 - s0) * px_per_m))
        x1, s1 = x0 + w / px_per_m, s0 + h / px_per_m
        self.cam.data.ortho_scale = max(w, h) / px_per_m
        self.cam.location = (-(x0 + x1) / 2, self.bl.st((s0 + s1) / 2), 100.0)
        self.scene.render.resolution_x, self.scene.render.resolution_y = w * SUPERSAMPLE, h * SUPERSAMPLE
        return x0, x1, s0, s1

    def ids(self, shown):
        """The index of the part seen at each pixel (row 0 at the bottom), -1 where nothing is; only shown render."""
        for o in self.scene.objects:
            if o.type == "MESH":
                o.hide_render = o not in shown
        path = Path(bpy.app.tempdir) / "status_ids.png"
        self.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        img = texture.load_image(path)
        px = np.array(img.pixels[:], np.float32).reshape(self.scene.render.resolution_y, self.scene.render.resolution_x, 4)
        bpy.data.images.remove(img)
        rgb = np.rint(px[..., :3] * 255)
        code = np.rint((rgb[..., :2] - 4) / 8)
        hit = px[..., 3] > 0.5
        if np.abs(rgb[..., :2] - (8 * code + 4))[hit].max(initial=0) > 2 or (code[..., 0] + 32 * code[..., 1])[hit].max(initial=0) >= len(self.parts):
            raise SystemExit("the render's colours don't decode to part indices (view transform, dither or lighting changed)")
        return np.where(hit, code[..., 0] + 32 * code[..., 1], -1).astype(int)


def edges(ids):
    """Pixels where the part index changes to the right or above: (silhouette edge, edge between two parts)."""
    a, right, up = ids[:-1, :-1], ids[:-1, 1:], ids[1:, :-1]
    out, inner = np.zeros(ids.shape, bool), np.zeros(ids.shape, bool)
    for b in (right, up):
        change = a != b
        out[:-1, :-1] |= change & ((a < 0) | (b < 0))
        inner[:-1, :-1] |= change & (a >= 0) & (b >= 0)
    return out, inner


def thicken(mask, r):
    """mask grown by a disc of radius r, without wrapping round the edges."""
    h, w = mask.shape
    padded = np.pad(mask, r)
    out = np.zeros_like(mask)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                out |= padded[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def line_art(layers):
    """[(mask at 4x, (radius at 4x, alpha))] drawn over each other into a grey sprite at 1x."""
    h, w = layers[0][0].shape
    alpha = np.zeros((h, w))
    for mask, (r, a) in layers:
        alpha = np.maximum(alpha, thicken(mask, r) * a)
    return sprite(alpha)


def sprite(coverage_4x):
    h, w = coverage_4x.shape
    alpha = coverage_4x.reshape(h // SUPERSAMPLE, SUPERSAMPLE, w // SUPERSAMPLE, SUPERSAMPLE).mean(axis=(1, 3))
    return np.dstack([np.full(alpha.shape + (3,), GREY), alpha])


def save(arr, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    texture.save_image(arr, path, srgb=True)
    return path


def render_parts():
    return sorted((o for o in bpy.data.collections["Centurion"].all_objects
                   if o.type == "MESH" and o.users_collection[0].name not in ("Colliders", "LOD1")), key=lambda o: o.name)


def outboard_end(bl, objs):
    """Right-wing parts' outboard end: their largest x and the mean station of the vertices within 1 cm of it."""
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    x = max(-p.x for p in pts)
    tip = [p.y + bl.Y0 for p in pts if -p.x > x - 0.01]
    return [round(x, 4), round(sum(tip) / len(tip), 4)]


def footprint(bl, objs, pad):
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    return (min(-p.x for p in pts) - pad, max(-p.x for p in pts) + pad,
            min(p.y + bl.Y0 for p in pts) - pad, max(p.y + bl.Y0 for p in pts) + pad)


def status_top(view, parts, out):
    view.frame((-STATUS_SIZE_M / 2, STATUS_SIZE_M / 2, STATUS_CENTRE_STATION - STATUS_SIZE_M / 2,
                STATUS_CENTRE_STATION + STATUS_SIZE_M / 2), STATUS_PX / STATUS_SIZE_M)
    outline, inner = edges(view.ids(parts))
    doors = [o for o in parts if o.name in BAY_DOORS]
    if len(doors) != len(BAY_DOORS):
        raise SystemExit(f"the blend lacks {sorted(set(BAY_DOORS) - {o.name for o in doors})}")
    bays = np.logical_or(*edges(view.ids(doors)))
    y, x = np.mgrid[0:bays.shape[0], 0:bays.shape[1]]
    bays &= ((x + y) // DASH_PX) % 2 == 0
    save(line_art([(bays, STATUS_LINES["bays"]), (inner, STATUS_LINES["parts"]), (outline, STATUS_LINES["outline"])]), out / f"{STATUS}.png")
    (out / f"{STATUS}.json").write_text(json.dumps({"size_m": STATUS_SIZE_M, "centre_station": STATUS_CENTRE_STATION}, indent=1) + "\n")


def span_gauge(view, bl, parts, extended_ends, out):
    """The root sprite: every part but the stages, cropped to the right half from the centreline; each stage alone."""
    by_name = {o.name: o for o in parts}
    riding = {n for names in STAGES for n in names} | {n[:-1] + "L" for names in STAGES for n in names}
    fixed = [o for o in parts if o.name not in riding]
    x0, x1, s0, s1 = footprint(bl, fixed, SPAN_PAD_M)
    sprites = {}
    rect = view.frame((0.0, x1, s0, s1), SPAN_PX_PER_M)
    outline, inner = edges(view.ids(fixed))
    save(line_art([(inner, SPAN_LINES["parts"]), (outline, SPAN_LINES["outline"])]), out / f"{SPAN}_root.png")
    sprites[f"{SPAN}_root"] = {"rect_m": [round(v, 4) for v in rect], "end_m": outboard_end(bl, [by_name[ROOT_WING]])}
    for k, names in enumerate(STAGES, 1):
        stage = [by_name[n] for n in names]
        rect = view.frame(footprint(bl, stage, SPAN_PAD_M), SPAN_PX_PER_M)
        outline, _ = edges(view.ids(stage))
        save(line_art([(outline, SPAN_LINES["outline"])]), out / f"{SPAN}_stage{k}.png")
        sprites[f"{SPAN}_stage{k}"] = {"rect_m": [round(v, 4) for v in rect], "end_m": outboard_end(bl, stage),
                                       "extended_end_m": extended_ends[names]}
    (out / f"{SPAN}.json").write_text(json.dumps({"px_per_m": SPAN_PX_PER_M, "sprites": sprites}, indent=1) + "\n")


def damaged_parts(parts):
    """The parts the game damages, by the name its UnitPart carries: meshes with their own mass, and control surfaces'
    meshes, whose mass is on the hinge empty they hang from; not the part tree's visual pieces (part_splits)."""
    out = {}
    for o in parts:
        if part_splits.BY_NAME.get(o.name, {}).get("visual"):
            continue
        if "mass_kg" in o:
            out[o.name] = o
        elif o.name.endswith("_visible") and o.parent is not None and "mass_kg" in o.parent:
            out[o.parent.name] = o
    return out


def damage_diagram(view, parts, out):
    """Each damageable part alone, filled, cropped from the status frame; its place as fractions of that frame."""
    folder = out / "Damage"
    view.frame((-STATUS_SIZE_M / 2, STATUS_SIZE_M / 2, STATUS_CENTRE_STATION - STATUS_SIZE_M / 2,
                STATUS_CENTRE_STATION + STATUS_SIZE_M / 2), STATUS_PX / STATUS_SIZE_M)
    layout = {}
    for name, obj in sorted(damaged_parts(parts).items()):
        cover = sprite((view.ids([obj]) >= 0).astype(float))
        rows, cols = np.nonzero(cover[..., 3] > 0)
        r0, r1, c0, c1 = max(rows.min() - 1, 0), rows.max() + 2, max(cols.min() - 1, 0), cols.max() + 2
        file = f"centurion_part_{name}"
        save(cover[r0:r1, c0:c1], folder / f"{file}.png")
        layout[name] = {"sprite": file, "rect": [round(c0 / STATUS_PX, 5), round(r0 / STATUS_PX, 5), round(c1 / STATUS_PX, 5), round(r1 / STATUS_PX, 5)]}
    for stale in folder.glob("centurion_part_*.png"):
        if stale.stem not in {v["sprite"] for v in layout.values()}:
            stale.unlink()
            stale.with_suffix(".png.meta").unlink(missing_ok=True)
    (out / f"{DAMAGE}.json").write_text(json.dumps({"frame": STATUS, "parts": layout}, indent=1) + "\n")
    return layout


def main():
    opts = parse_args()
    extended = opts["blend"].with_name(opts["blend"].name.replace("_retracted", "_extended"))
    bpy.ops.wm.open_mainfile(filepath=str(extended))
    bl = load_blockout()
    extended_ends = {names: outboard_end(bl, [bpy.data.objects[n] for n in names]) for names in STAGES}
    bpy.ops.wm.open_mainfile(filepath=str(opts["blend"]))
    bl = load_blockout()
    parts = render_parts()
    view = TopView(bl, parts)
    out = opts["out"]
    status_top(view, parts, out)
    span_gauge(view, bl, parts, extended_ends, out)
    layout = damage_diagram(view, parts, out)
    print(f"status line art: {len(parts)} parts, the span gauge's root and {len(STAGES)} stages, {len(layout)} damage parts -> {out}")


main()
