"""The painted skin's dark tail, seen whole: the intact aircraft in
one livery from six directions, orthographic, under the review's sun and sky, with no ground; per view, the luma of
every pixel the painted skin covers (a flat white-on-black mask render finds them), and the share under DARK.
Run on the parts blend with the shipped maps once, writing the baseline; on the pass's baked blend with its maps (and
roundels), held to it: each view's dark share at most the shipped view's plus SLACK.
blender --background <blend> --python check_luma.py -- <out.json> [--against <baseline.json>]
Renders land in pass/luma/<shipped|pass>_<view>.png beside their masks."""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
import render_rig as L  # noqa: E402
import pass_common as P  # noqa: E402

DARK = 0.08  # in display luma (AgX): the diagnosis's black patches, albedo ~92/255 under AO ~40/255, rendered under it
SLACK = 0.01
LIVERY = "bdf_matte_gray"  # the lightest livery: a dark patch shows most on it
RES = 900
VIEWS = {"front": Vector((0, -1, 0)), "rear": Vector((0, 1, 0)), "left": Vector((1, 0, 0)), "right": Vector((-1, 0, 0)),
         "top": Vector((0, 0, 1)), "bottom": Vector((0, 0, -1))}
args = sys.argv[sys.argv.index("--") + 1:]
out = Path(args[0]).resolve()
against = Path(args[args.index("--against") + 1]).resolve() if "--against" in args else None
shipped = "m4_parts" in bpy.data.filepath
tag = "shipped" if shipped else "pass"
DIR = P.PASS / "luma"
DIR.mkdir(exist_ok=True)

L.hide_helpers(lod_too=True)
cam = L.rig(ground=False)
scene = bpy.context.scene
if not shipped:  # the pass's inward twins sit on the skin: 2 mm in, as the review renders them (Cycles shadows a coincident twin)
    import bmesh
    for me in dict.fromkeys(o.data for o in bpy.data.objects if o.type == "MESH" and "twin_src" in o.data.attributes):
        bm = bmesh.new()
        bm.from_mesh(me)
        tw = bm.faces.layers.int.get("twin_src")
        bm.normal_update()
        push = {v: f.normal for f in bm.faces if f[tw] for v in f.verts}
        for v, n in push.items():
            v.co += n * 0.002
        bm.to_mesh(me)
        bm.free()
    tex = P.PASS / "textures"
    marked = P.PASS / "textures_marked" / f"centurion_livery_{LIVERY}.png"
    maps = {k: tex / f"centurion_{k}.png" for k in ("b", "m", "n", "ao")}
    livery = marked if marked.exists() else tex / f"centurion_livery_{LIVERY}.png"
else:
    maps = {k: L.TEX / f"centurion_{k}.png" for k in ("b", "m", "n", "ao")}
    livery = L.TEX / f"centurion_livery_{LIVERY}.png"
skin = L.skin_material("lu_skin", maps, livery=livery)
other = L.flat("lu_other", (0.20, 0.205, 0.215), 0.5, 0.5)
glass = L.flat("lu_glass", (0.01, 0.012, 0.012), 0.05)
for me in bpy.data.meshes:
    for i, m in enumerate(me.materials):
        if m is not None:
            me.materials[i] = skin if (m.name == P.SKIN or m.name.startswith("rv_skin")) else glass if m.name.startswith("glass") else other
shown = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and not L.is_helper(o, True)]
cs = [o.matrix_world @ Vector(c) for o in shown for c in o.bound_box]
lo = Vector([min(c[i] for c in cs) for i in range(3)])
hi = Vector([max(c[i] for c in cs) for i in range(3)])
mid, size = (lo + hi) / 2, (hi - lo).length
cam.data.type, cam.data.ortho_scale = "ORTHO", size * 1.02
cam.data.clip_end = size * 4
scene.render.resolution_x = scene.render.resolution_y = RES
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"


def render(path):
    scene.render.filepath = str(path)
    L.assert_clean(lod_too=True)
    bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(str(path))
    px = np.array(im.pixels[:], dtype=np.float32).reshape(RES, RES, im.channels)
    bpy.data.images.remove(im)
    return px


def mask_pass():
    """Workbench, flat, each slot its viewport colour: the skin white, the rest black, on black."""
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light, sh.color_type, sh.background_type = "FLAT", "MATERIAL", "VIEWPORT"
    sh.background_color = (0, 0, 0)
    scene.view_settings.view_transform = "Standard"
    for m, c in ((skin, (1, 1, 1, 1)), (other, (0, 0, 0, 1)), (glass, (0, 0, 0, 1))):
        m.diffuse_color = c


def look_pass():
    scene.render.engine = "CYCLES"
    scene.view_settings.view_transform = "AgX"
    scene.cycles.samples, scene.cycles.use_denoising = 32, True


report = {"livery": LIVERY, "dark": DARK, "views": {}}
for name, d in VIEWS.items():
    cam.location = mid + d * size * 1.5
    cam.rotation_euler = (-d).to_track_quat("-Z", "Z" if abs(d.z) < 0.9 else "Y").to_euler()
    mask_pass()
    m = render(DIR / f"{tag}_{name}_mask.png")[..., 0] > 0.5
    look_pass()
    px = render(DIR / f"{tag}_{name}.png")
    luma = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    sel = luma[m]
    report["views"][name] = {"skin_px": int(m.sum()), "dark_share": round(float((sel < DARK).mean()), 4) if sel.size else 0.0,
                             "p1": round(float(np.percentile(sel, 1)), 3) if sel.size else 0.0, "median": round(float(np.median(sel)), 3) if sel.size else 0.0}
    print("LUMA", tag, name, report["views"][name], flush=True)
fails = []
if against is not None:
    base = json.loads(against.read_text())["views"]
    for name, r in report["views"].items():
        if r["dark_share"] > base[name]["dark_share"] + SLACK:
            fails.append(f"{name}: {r['dark_share']} of the skin under luma {DARK}, shipped {base[name]['dark_share']} + {SLACK}")
    report["fails"] = fails
out.write_text(json.dumps(report, indent=1))
print("LUMA", tag, len(fails), "fails", fails, flush=True)
if fails:
    raise SystemExit("check_luma: " + "; ".join(fails))
