"""Measure fuselage_aft's junctions against the detailed neighbours without rebuilding the composite.

blender --background --factory-startup --python art/blender/m4/fuselage_aft_junctions.py -- [--blend FILE]
    [--out FILE] [--shots DIR] [--module FILE]

Opens a composite scene (default .cache/art/m4/centurion_m4_retracted.blend: every group's detailed meshes), swaps in
this module's fresh build the way detail_centurion.py does (swap, bury, slot order), and writes
build_centurion.smoothness_report to --out (default .cache/art/m4_fuselage_aft/smoothness_retracted.json) for
tools/compare_smoothness.py. --module builds another copy of the module (say HEAD's) instead. --shots renders
flat-shaded close-ups of the fairing's junctions into DIR (buried faces in red). A scene with "extended" in its name
is measured and shot extended. For the group in its maps against its detailed neighbours, run the composite
(detail_centurion.py --group all). Every top-level statement is a definition, so detail_centurion's group discovery
can import this module."""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VIEWS = {  # flat-shaded geometry checks: (lens, camera (x, station, z), target)
    "under_root": (30, (3.7, 12.0, 4.7), (2.0, 19.0, 5.7)),
    "under_aft": (30, (3.9, 27.5, 4.9), (2.0, 21.0, 5.8)),
    "le_root": (40, (6.5, 9.5, 7.6), (1.6, 15.2, 6.3)),
    "top_seal": (34, (4.5, 26.0, 11.0), (0.8, 19.0, 6.9)),
    "front_lip": (40, (4.5, 7.0, 8.6), (0.6, 12.0, 6.6)),
    "swell_edge": (35, (6.0, 12.0, 10.5), (1.2, 19.5, 6.9)),
    "te_root": (34, (6.0, 30.0, 6.0), (1.5, 23.5, 6.2)),
    "le_low": (30, (5.5, 11.0, 5.2), (2.0, 15.6, 6.0)),
    "lap_corner": (35, (4.5, 10.5, 7.5), (1.3, 12.6, 6.3)),
    "le_top": (35, (3.2, 13.6, 8.6), (1.6, 15.4, 6.4)),
    "le_front": (30, (2.6, 12.2, 6.3), (1.7, 15.4, 6.3)),
}


def load_detail(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("detail_centurion", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def measure_junctions():
    import bpy
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"blend": str(REPO / ".cache/art/m4/centurion_m4_retracted.blend"),
            "out": str(REPO / ".cache/art/m4_fuselage_aft/smoothness_retracted.json"), "shots": None, "module": None}
    for flag, value in zip(argv[::2], argv[1::2]):
        opts[flag.lstrip("-")] = value
    sys.path.insert(0, str(REPO / "art/blender"))
    dc = load_detail(REPO / "art/blender/detail_centurion.py")
    bpy.ops.wm.open_mainfile(filepath=opts["blend"])
    bl = dc.load_blockout()
    surf = dc.surface.Fuselage(bl)
    mats = {m.name: m for m in bpy.data.materials}
    for name in dc.LIGHTS:
        mats[name] = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    group = dc.GROUPS["fuselage_aft"]
    if opts.get("module"):  # another version of the module (a file), to compare against
        import importlib.util
        spec = importlib.util.spec_from_file_location("m4.fuselage_aft_other", opts["module"])
        group = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(group)
    extension = 1.0 if "extended" in Path(opts["blend"]).name else 0.0
    objs, _ = dc.swap_group(bl, group, surf, mats)
    bpy.context.view_layer.update()
    scene = {**objs, **dc.touching(objs)}
    bl.set_extension(scene, 0.0)
    bl.bury_hidden_skin(scene, mats[bl.STRUCT])
    bl.set_extension(scene, extension)
    for o in objs.values():
        dc.order_slots(o, list(bl.SLOT_ORDER) + list(dc.LIGHTS))
    for name in ("wingfairing",):
        print("SHELLS", name, dc.shell_report(bl, objs[name]))
    report = bl.smoothness_report(dc.render_parts())
    Path(opts["out"]).write_text(json.dumps({"blend": opts["blend"], "smoothness": report}, indent=1))
    for k, v in report["junction_creases"].items():
        if any(n in k for n in ("wingfairing", "laser_turret")):
            print("JUNCTION", k, v.get("median_deg"), v.get("p90_deg"), v.get("at"))
            where_worst(bl, dc.render_parts(), *k.split("~"))
    if opts["shots"]:
        out = Path(opts["shots"])
        out.mkdir(parents=True, exist_ok=True)
        dc.render.style_shared({"skin": bl.SKIN, "struct": bl.STRUCT, "mech": bl.MECH, "glass": bl.GLASS,
                                "gear": bl.GEAR}, dc.paint.PAINT[dc.surface.HULL])
        bpy.data.materials[bl.STRUCT].diffuse_color = (0.6, 0.12, 0.08, 1)  # buried faces in red where they show
        cam, _ = dc.render.build_rig(bl)
        for name in ("Colliders", "LOD1"):
            for o in bpy.data.collections[name].objects:
                o.hide_render = True
        flat_shots(bl, cam, out)


def where_worst(bl, objs, a, b, step=0.05):
    """smoothness_report's crease samples for one pair, binned by station and height: where the worst tenth lies."""
    import math
    from collections import Counter
    from mathutils.bvhtree import BVHTree
    bv, bp = bl.world_mesh(objs[b])
    btree = BVHTree.FromPolygons(bv, bp)
    blo, bhi = bl.bounds(bv)
    av, ap = bl.world_mesh(objs[a])
    skin = set(bl.slot_faces(objs[a], bl.SKIN))
    rows = []
    for f, poly in enumerate(ap):
        if f not in skin:
            continue
        for t in range(1, len(poly) - 1):
            p0, p1, p2 = av[poly[0]], av[poly[t]], av[poly[t + 1]]
            if not bl.boxes_touch(bl.bounds([p0, p1, p2]), (blo, bhi), 0.05):
                continue
            na = (p1 - p0).cross(p2 - p0)
            if na.length < 1e-12:
                continue
            na.normalize()
            n = min(40, max(1, math.ceil(max((p1 - p0).length, (p2 - p0).length) / step)))
            for i in range(n + 1):
                for j in range(n + 1 - i):
                    q = p0 + (p1 - p0) * (i / n) + (p2 - p0) * (j / n)
                    loc, nb, _, _ = btree.find_nearest(q, 0.04)
                    if loc is not None and (q - loc).dot(nb) >= 0:
                        rows.append((math.degrees(na.angle(nb)), q, na, loc, nb))
    if not rows:
        return
    rows.sort(key=lambda r: r[0])
    p90 = rows[int(0.9 * (len(rows) - 1))][0]
    bins = Counter((round(q.y + bl.Y0), round(q.x, 1), round(q.z, 1)) for d, q, *_ in rows if d >= p90)
    print(f"  WORST {a}~{b}: {len(rows)} samples, p90 {p90:.1f}; worst tenth by (station, x, z):",
          ", ".join(f"{k}x{v}" for k, v in bins.most_common(12)))
    by = {}
    for d, q, *_ in rows:
        by.setdefault((round(q.y + bl.Y0), "hi" if q.z >= 6.2 else "lo"), []).append(d)
    for d, q, na, loc, nb in rows[-1::-max(1, len(rows) // 400)][:8]:
        print(f"    sample {d:.0f} deg at ({q.x:.2f}, {q.y + bl.Y0:.2f}, {q.z:.3f}) n {tuple(round(c, 2) for c in na)}"
              f" nearest ({loc.x:.2f}, {loc.y + bl.Y0:.2f}, {loc.z:.3f}) n {tuple(round(c, 2) for c in nb)}")
    for lo, hi in ((5.0, 6.3), (6.3, 8.0)):
        sel = sorted(d for d, q, *_ in rows if lo <= q.z < hi and 17 <= q.y + bl.Y0 <= 23)
        if sel:
            print(f"  BAND z {lo}-{hi} (17-23): {len(sel)} samples, median {sel[len(sel) // 2]:.1f}, p90 {sel[int(0.9 * (len(sel) - 1))]:.1f}")
    lo_, hi_ = (float(v) for v in os.environ.get('JWIN', '17.5,20.5').split(','))
    mid = sorted((r for r in rows if lo_ < r[1].y + bl.Y0 < hi_), key=lambda r: r[0])
    for d, q, na, loc, nb in mid[int(0.85 * len(mid))::max(1, len(mid) // 60)][:8]:
        print(f"    mid {d:.0f} deg at ({q.x:.2f}, {q.y + bl.Y0:.2f}, {q.z:.3f}) n {tuple(round(c, 2) for c in na)}"
              f" nearest ({loc.x:.2f}, {loc.y + bl.Y0:.2f}, {loc.z:.3f}) n {tuple(round(c, 2) for c in nb)}")
    print("  BYSTATION", " ".join(f"{k[0]}{k[1]}:{len(v)}/{sorted(v)[len(v) // 2]:.0f}/{sorted(v)[int(0.9 * (len(v) - 1))]:.0f}"
                                  for k, v in sorted(by.items())))


def flat_shots(bl, cam, out):
    """Workbench in material colours (geometry only, never the GPU): each VIEWS close-up."""
    import bpy
    from mathutils import Vector
    scene = bpy.context.scene
    scene.view_settings.exposure = 1.3
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light, shading.color_type, shading.show_cavity = "STUDIO", "MATERIAL", True
    shading.show_shadows = False
    if os.environ.get("JPARTS"):  # colour by part instead: the fairing orange, the wing roots blue
        shading.color_type = "OBJECT"
        for o in bpy.data.objects:
            o.color = ((0.9, 0.55, 0.2, 1) if o.name == "wingfairing" else
                       (0.3, 0.5, 0.9, 1) if o.name.startswith("wing_root") else (0.6, 0.6, 0.6, 1))
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1600, 1000, 100
    for view, (lens, loc, target) in VIEWS.items():
        cam.data.type, cam.data.lens = "PERSP", lens
        cam.location = Vector((loc[0], bl.st(loc[1]), loc[2]))
        t = Vector((target[0], bl.st(target[1]), target[2]))
        cam.rotation_euler = (t - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out / f"junction_{view}.png")
        bpy.ops.render.render(write_still=True)
    print("SHOTS", out)


if __name__ == "__main__":
    measure_junctions()
