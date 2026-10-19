"""MRB-100 Centurion M4 detail pass: rebuild part groups at finished-aircraft detail on top of the step 6.1 blockout,
texture them from Python and render them for review. docs/M4-ART-PLAN.md is the plan this script carries out.

blender --background --factory-startup --python art/blender/detail_centurion.py -- [--group nose] [--span retracted]
    [--out DIR] [--samples 64] [--no-render]

--group takes one group (a module in m4/ that declares GROUP), a comma list, or all. One group writes into DIR
(default .cache/art/m4_<group>): centurion_m4_<group>_<span>.blend, metrics_<group>.json, the group's textures on its
own 2048 canvas, its close-ups (the module's VIEWS) and the whole aircraft. Several groups (a list, or all) build into
one scene, the composite: DIR (default .cache/art/m4) gets centurion_m4_<span>.blend, metrics_m4_<span>.json, the
shared 4096 skin atlas (textures/centurion_*.png) and the whole aircraft. The .blend is saved before the review look
restyles the materials, so it is an export source for tools/export_blockout.py as it stands.

It opens the blockout's saved step 6.1 .blend (.cache/art/blockout_s61/centurion_s61_<span>.blend) and swaps the mesh
data of each group's render parts in place, so every part keeps its name, origin, hinge empty, parent and children
(colliders and LOD1 hulls stay the blockout's). Every group is swapped first; then, once over all of them, so each
pass sees the final neighbours:
- skin hidden inside a touching part (blockout or detailed) moved to aircraft_structure (bury_hidden_skin);
- material slots in the blockout's slot order, plus the light materials;
- skin UVs: angle-based along the seams the builders mark, mirrored faces (the lower hull below the chine line, the
  radome's -X half, the right-hand twins) reusing their +X twin's islands, packed together on one canvas; trim faces
  box-projected as in the blockout, then each group's trim(bl, objs) hook if it has one;
- smoothing from the blockout's bake_normals (hard edges past 50 degrees, Weighted Normal), hull faces on the
  fuselage surface's own normals;
- checks per group (triangles against the group budget, closed shells, outward normals, texel density, envelope, and
  the module's own check(bl, objs) if it has one) into the metrics;
- textures: geometry buffers baked from one proxy of every group, each group's paint composed in numpy (m4/paint.py
  and the group's layout) over the texels its parts own, written as albedo, metal-smooth (RGB metal, A smoothness),
  tangent normal and AO PNGs, and the damaged skin's colour and normal.

A group module declares GROUP, PARTS, BUDGET_TRIS, VIEWS (its close-ups, as render.AIRCRAFT_VIEWS; the first four
make the contact sheet), build(bl, surf, slots) and paint(canvas, text_mask), and optionally MIRROR_PARTS
(right-hand part: its left twin), GROUND_PARTS (parts that stand on the runway: the envelope asks their lowest point
within 1 cm of the ground instead of over the 0.3 m floor), STOCK_SLOTS (material slots of its own that Unity binds to
a stock material), trim(bl, objs, folder) (its own trim UVs, and maps written into folder, after the UV pass; returns
a check) and check(bl, objs).
Adding a group never edits this script.
"""

import importlib
import json
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m4 import airframe, livery, paint, render, surface, texture  # noqa: E402
from m4.blockout import load_blockout  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BLOCKOUT = REPO / ".cache" / "art" / "blockout_s61"


def discover_groups():
    """Every module in m4/ that declares GROUP is a part group, so a new group is one new file and never an edit here."""
    groups = {}
    for path in sorted((Path(__file__).resolve().parent / "m4").glob("*.py")):
        module = importlib.import_module(f"m4.{path.stem}")
        if hasattr(module, "GROUP"):
            groups[module.GROUP] = module
    return groups


GROUPS = discover_groups()
# A group alone paints on its own 2048 review canvas at TEXEL_TARGET; the composite packs every group into the one
# 4096 skin atlas (G4.1: 60 px/m or more) at the highest density that fits. See docs/M4-ART-PLAN.md "Texel plan".
ATLAS, COMPOSITE_ATLAS, TEXEL_TARGET = 2048, 4096, 61.0
LOD0_CEILING = 146000  # G4.1: 130,000 for the exterior, plus 16,000 of damage structure (owner, 2026-10-18)
UV_MARGIN = 4 / 2048  # island gap as a fraction of the sheet: 4 px on a group canvas, 8 on the atlas
# The stock jet_mechanical sheet is an atlas (pipes, cables, a painted fan disc), 40% of it cut out by alpha, not a
# tiling trim: box-projected faces land on holes and fragments. So every face on that slot takes one flat swatch of the
# mod's own sheet, by what it is, and Unity puts the sheet on an opaque copy of the stock material (CenturionAuthor
# MechMaps). Only tiling trims (aircraft_structure) keep the box projection. The engines' aircraft_structure faces (the
# duct, splitter and core cowl, which m4/engines.py means dark) join them on the duct swatch: that stock sheet is a
# bright, fully glossy panel greeble that reads as chrome on a cowl. Swatch: sRGB albedo, metal, smoothness.
MECH_SWATCHES = {"fitting": ((122, 124, 128), 0.6, 0.45),  # probes, wipers, actuators, knuckles, dischargers
                 "fan": ((150, 152, 156), 0.7, 0.5),  # fan blades, satin titanium
                 "spinner": ((92, 94, 98), 0.5, 0.55),
                 "duct": ((58, 60, 64), 0.3, 0.3),
                 "nozzle": ((176, 178, 180), 0.2, 0.54),  # the core nozzle's bright lip
                 "plug": ((48, 46, 44), 0.15, 0.22)}  # the exhaust plug, sooty matte
MECH_DUCT_PARTS = ("nacelle_", "nozzle_")
MECH_SWATCH_PX = 32  # a 4 x 2 sheet (power of two); the UVs sit on swatch centres, so no filter or mip reaches a neighbour
SPINNER_R = 0.63  # m: a fan face centred this close to the spin axis (the part's Y) is the spinner's (m4/engines.SPINNER)
LIGHTS = ("light_red", "light_white", "light_formation")
# Slots a group binds to a stock material of its own, after the lights (CenturionAuthor SlotMaterials maps them by name)
STOCK_SLOTS = tuple(s for g in GROUPS.values() for s in getattr(g, "STOCK_SLOTS", ()))
DEGENERATE = 1e-5  # metres: an edge this short is a collapsed one
# The stationary joints along the body, where the skin must run on as one surface: (part ahead, part behind, station).
# joint_continuity holds each to JOINT_GAP and JOINT_TURN.
JOINT_PAIRS = (("radar_F_fairing", "nose", 3.625), ("nose", "fuselage_F", 7.0), ("fuselage_F", "fuselage_M", 17.0),
               ("fuselage_M", "fuselage_R", 25.0), ("fuselage_R", "tailcone", 33.0))
JOINT_GAP, JOINT_TURN = 1e-4, 1.0  # metres between matching skin vertices, degrees between their normals
# Each group's right-hand parts whose skin islands are their left twin's.
MIRROR_PARTS = {k: v for g in GROUPS.values() for k, v in getattr(g, "MIRROR_PARTS", {}).items()}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"group": "nose", "span": "retracted", "out": None, "samples": 64, "render": True}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--group", "--span", "--out", "--samples"):
            opts[a[2:]] = argv[i + 1]
            i += 1
        elif a == "--no-render":
            opts["render"] = False
        else:
            raise SystemExit(f"unknown argument {a}")
        i += 1
    names = list(GROUPS) if opts["group"] == "all" else opts["group"].split(",")
    unknown = [n for n in names if n not in GROUPS]
    if unknown:
        raise SystemExit(f"unknown group {', '.join(unknown)}; groups: {', '.join(GROUPS)}")
    if opts["span"] not in ("retracted", "extended"):
        raise SystemExit("--span takes retracted or extended")
    opts["groups"] = [GROUPS[n] for n in names]
    opts["composite"] = opts["group"] == "all" or len(names) > 1
    default = "m4" if opts["composite"] else f"m4_{names[0]}"
    opts["out"] = Path(opts["out"]) if opts["out"] else REPO / ".cache" / "art" / default
    opts["samples"] = int(opts["samples"])
    if not opts["out"].is_absolute():
        raise SystemExit("Pass an absolute --out: Blender resolves relative paths against its own cwd.")
    return opts


# ---------- mesh swap ----------
def swap_mesh(obj, part, mats):
    """Replace obj's mesh with the part's world-space bmesh, keeping the object (name, transform, parent,
    children). The blockout's mesh stays on the object as _blockout_mesh, the shape the game's physics and aero are
    measured on (tools/export_blockout.py writes it as <part>_shape). Edges shorter than DEGENERATE collapse first: Unity drops the zero-area triangles they leave, and its
    submesh counts must match the export's. Returns the face indices whose UVs are copies, and their sources."""
    bm = part.bm
    bmesh.ops.dissolve_degenerate(bm, dist=DEGENERATE, edges=bm.edges[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.faces.index_update()
    pairs = [(d.index, s.index) for d, s in part.mirror_pairs if d.is_valid and s.is_valid]
    bmesh.ops.transform(bm, matrix=obj.matrix_world.inverted(), verts=bm.verts)
    if part.envelope is not None:  # a thin-walled part's closed hull, which the bury pass tests containment against
        env = bpy.data.meshes.new(obj.name + "_envelope")
        bmesh.ops.dissolve_degenerate(part.envelope, dist=DEGENERATE, edges=part.envelope.edges[:])
        bmesh.ops.recalc_face_normals(part.envelope, faces=part.envelope.faces)  # the bury test reads them
        bmesh.ops.transform(part.envelope, matrix=obj.matrix_world.inverted(), verts=part.envelope.verts)
        part.envelope.to_mesh(env)
        part.envelope.free()
        obj["_envelope_mesh"] = env
    me = bpy.data.meshes.new(obj.name + "_m4")
    bm.to_mesh(me)
    bm.free()
    for slot in part.slots:
        me.materials.append(mats[slot])
    old = obj.data
    if "_blockout_mesh" not in obj:
        old.name = obj.name + "_blockout"
        obj["_blockout_mesh"] = old
    obj.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    me.name = obj.name
    return dict(pairs)


def swap_group(bl, group, surf, mats):
    """Build the group and swap its meshes into the scene. Returns its objects and their mirrored face pairs."""
    parts = group.build(bl, surf, (bl.SKIN, bl.STRUCT, bl.GLASS, bl.MECH) + LIGHTS)
    missing = set(group.PARTS) ^ set(parts)
    if missing:
        raise SystemExit(f"{group.GROUP}: PARTS and build() disagree on {sorted(missing)}")
    objs, mirrored = {}, {}
    for name, part in parts.items():
        obj = bpy.data.objects[name]
        mirrored[name] = swap_mesh(obj, part, mats)
        objs[name] = obj
    return objs, mirrored


def split_buried_pairs(objs, mirrored):
    """Mirrored face pairs the bury pass left on different slots are split, so each keeps its own islands and a visible
    face never copies a buried twin's UVs. Burial is decided here, once every group is in: a group judging its own
    faces against the blockout neighbours it was built among buried hull the detailed sponsons no longer cover."""
    for name, pairs in mirrored.items():
        polys = objs[name].data.polygons
        for d in [d for d, s in pairs.items() if polys[d].material_index != polys[s].material_index]:
            del pairs[d]


def order_slots(obj, order):
    me = obj.data
    names = [m.name for m in me.materials]
    by_name = {m.name: m for m in me.materials}
    used = sorted({names[p.material_index] for p in me.polygons}, key=order.index)
    index = [used.index(names[p.material_index]) for p in me.polygons]
    me.materials.clear()
    for n in used:
        me.materials.append(by_name[n])
    me.polygons.foreach_set("material_index", index)


def render_parts():
    """The aircraft's render meshes: the Centurion collection without its colliders and LOD1 hulls."""
    return {o.name: o for o in bpy.data.collections["Centurion"].all_objects
            if o.type == "MESH" and o.users_collection[0].name not in ("Colliders", "LOD1")}


def world_box(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def touching(objs, margin=0.05):
    """Render parts outside objs whose bounds touch one of objs': the parts a detailed face can sit inside."""
    boxes = [world_box(o) for o in objs.values()]
    out = {}
    for name, o in render_parts().items():
        if name in objs:
            continue
        lo, hi = world_box(o)
        if any(all(lo[i] - margin <= b[1][i] and b[0][i] <= hi[i] + margin for i in range(3)) for b in boxes):
            out[name] = o
    return out


# ---------- UVs ----------
def copy_mirrored_uvs(dst, dst_faces, src, src_faces):
    """Each dst face takes its src face's UVs, loops matched by mirroring world positions across x = 0."""
    duv, suv = dst.data.uv_layers["UVMap"].data, src.data.uv_layers["UVMap"].data
    dm, sm = dst.matrix_world, src.matrix_world
    bad = 0
    for fd, fs in zip(dst_faces, src_faces):
        pd, ps = dst.data.polygons[fd], src.data.polygons[fs]
        spts = [(sm @ src.data.vertices[src.data.loops[li].vertex_index].co, li) for li in ps.loop_indices]
        for li in pd.loop_indices:
            p = dm @ dst.data.vertices[dst.data.loops[li].vertex_index].co
            p.x = -p.x
            dist, sl = min(((p - q).length, sl) for q, sl in spts)
            bad += dist > 1e-3
            duv[li].uv = suv[sl].uv
    return bad


def mech_role(name, centre, duct):
    if duct:
        return "duct"
    if name.startswith("fan_"):
        return "spinner" if math.hypot(centre.x, centre.z) < SPINNER_R else "fan"
    if name.startswith("nozzle_"):
        return "plug" if math.hypot(centre.x, centre.z) < 0.7 else "nozzle"
    return "fitting"


def mech_trim(bl, objs, folder, slot_order):
    """The engines' aircraft_structure faces moved to jet_mechanical, then every jet_mechanical face onto its
    MECH_SWATCHES swatch (all its loops on the swatch centre); the sheet's albedo and metal-smoothness PNGs written into
    folder. Returns the check: faces per role, and none left off a swatch."""
    names, cols, rows = list(MECH_SWATCHES), 4, 2
    centre = {r: ((i % cols + 0.5) / cols, (i // cols + 0.5) / rows) for i, r in enumerate(names)}
    counts, stray = {r: 0 for r in names}, 0
    for name, o in objs.items():
        me = o.data
        duct = set()
        if name.startswith(MECH_DUCT_PARTS):
            if bl.MECH not in me.materials:
                me.materials.append(bpy.data.materials[bl.MECH])
            mi = [m.name for m in me.materials].index(bl.MECH)
            for p in me.polygons:
                if me.materials[p.material_index].name == bl.STRUCT:
                    p.material_index = mi
                    duct.add(p.index)
            order_slots(o, slot_order)
        mech = {i for i, m in enumerate(me.materials) if m and m.name == bl.MECH}
        uv = me.uv_layers["UVMap"].data
        for p in me.polygons:
            if p.material_index in mech:
                role = mech_role(name, p.center, p.index in duct)
                for li in p.loop_indices:
                    uv[li].uv = centre[role]
                counts[role] += 1
        stray += sum(1 for p in me.polygons if p.material_index in mech
                     and any((uv[li].uv - Vector(centre[mech_role(name, p.center, p.index in duct)])).length > 1e-6 for li in p.loop_indices))
    S = MECH_SWATCH_PX
    alb, ms = np.zeros((rows * S, cols * S, 3)), np.zeros((rows * S, cols * S, 4))
    for i, (rgb, metal, smooth) in enumerate(MECH_SWATCHES.values()):
        rows_, cols_ = slice((i // cols) * S, (i // cols + 1) * S), slice((i % cols) * S, (i % cols + 1) * S)
        alb[rows_, cols_] = np.array(rgb) / 255
        ms[rows_, cols_] = (metal, metal, metal, smooth)
    folder.mkdir(parents=True, exist_ok=True)
    texture.save_image(alb, folder / "mech_trim_b.png", srgb=True)
    texture.save_image(ms, folder / "mech_trim_m.png")
    return {"value": counts, "limit": "every jet_mechanical face on a swatch centre", "pass": stray == 0}


def airframe_trim(objs, folder):
    """The damage structure's UVs, which its builders wrote into the airframe_uv layer, moved onto UVMap and the layer
    dropped; the airframe trim sheet written into folder. Returns the check: structure faces per part, and every
    one on the sheet's strips."""
    counts, stray = {}, 0
    for name, o in objs.items():
        me = o.data
        layer = me.uv_layers.get("airframe_uv")
        frame = {i for i, m in enumerate(me.materials) if m and m.name == airframe.SLOT}
        if layer is None:
            stray += sum(1 for p in me.polygons if p.material_index in frame)
            continue
        uv, src = me.uv_layers["UVMap"].data, layer.data
        n = 0
        for p in me.polygons:
            if p.material_index in frame:
                for li in p.loop_indices:
                    uv[li].uv = src[li].uv
                n += 1
        me.uv_layers.remove(layer)
        counts[name] = n
    airframe.write_sheet(folder, texture.save_image, paint.normal_from_height)
    return {"value": counts, "limit": "every structure face with its builder's UVs", "pass": stray == 0}


BURN_DEPTH = 0.1  # metres: a hull texel burns through only if the damage structure lies this close behind it


def over_structure(objs, pos, nrm, cls):
    """Which hull texels (world positions and normals) have a part's damage structure right behind them: the first
    face a ray straight in meets within BURN_DEPTH is on the airframe slot and met from behind (the lining, facing the
    air space; not a cavity's wall, nor the lining's face where the skin closes on a cavity wall with no air between),
    so a burn-through there opens onto frames and lining; and rays 45 deg off it round the body and along it (the hole
    seen at a slant) meet structure too, not a cavity's wall."""
    verts, polys, frame = [], [], []
    for o in objs.values():
        me, mw = o.data, o.matrix_world
        slots = {i for i, m in enumerate(me.materials) if m and m.name == airframe.SLOT}
        if not slots:
            continue
        base = len(verts)
        verts += [mw @ v.co for v in me.vertices]
        for p in me.polygons:
            polys.append([base + v for v in p.vertices])
            frame.append(p.material_index in slots)
    out = np.zeros(len(pos), bool)
    if not polys:
        return out
    tree = BVHTree.FromPolygons(verts, polys)
    lo = np.min(np.array(verts), axis=0) - BURN_DEPTH
    hi = np.max(np.array(verts), axis=0) + BURN_DEPTH
    near = (cls == surface.HULL) & np.all((pos > lo) & (pos < hi), axis=1)
    for i in np.flatnonzero(near):
        n = Vector(nrm[i]).normalized()
        g = n.cross(Vector((0, 1, 0))).normalized()  # round the body
        p = Vector(pos[i]) - n * 0.003
        out[i] = structure_behind(tree, frame, p, -n, n, True) and all(
            structure_behind(tree, frame, p, (-n + t).normalized(), n, False)
            for t in (g, -g, Vector((0, 0.8, 0)), Vector((0, -0.8, 0))))
    return out


def structure_behind(tree, frame, p, d, n, lining):
    """Whether a ray from p along d first meets a damage structure face within BURN_DEPTH of the skin; with lining,
    met from behind (the lining, facing the air space)."""
    hit = tree.ray_cast(p, d, BURN_DEPTH / max(-d.dot(n), 0.3))
    return hit[2] is not None and frame[hit[2]] and (not lining or hit[1].dot(n) < 0)


def joint_continuity(bl, objs):
    """Each JOINT_PAIRS joint: the hull vertices of the two parts on the joint's plane, matched nearest to nearest, the
    largest gap between a match and the largest turn between their shading normals."""
    out = {}
    for a, b, s in JOINT_PAIRS:
        if a not in objs or b not in objs:
            continue
        y = bl.st(s)
        rings = []
        for name in (a, b):
            o = objs[name]
            me, mw = o.data, o.matrix_world
            rot = mw.to_3x3()
            cls = np.zeros(len(me.polygons), np.int32)
            me.attributes["cls"].data.foreach_get("value", cls)
            normals = me.corner_normals
            pts = {}
            for p in me.polygons:  # hull faces, buried ones too (under a fairing they are still the same skin)
                if cls[p.index] not in (surface.HULL, surface.RADOME):
                    continue
                for li in p.loop_indices:
                    vi = me.loops[li].vertex_index
                    w = mw @ me.vertices[vi].co
                    if abs(w.y - y) < 1e-4:
                        pts.setdefault(vi, [w, Vector()])[1] += rot @ normals[li].vector
            rings.append([(w, n.normalized()) for w, n in pts.values()])
        gap = turn = 0.0
        for w, n in rings[0]:
            q, m = min(rings[1], key=lambda t: (t[0] - w).length)
            gap = max(gap, (q - w).length)
            turn = max(turn, math.degrees(n.angle(m, 0.0)))
        counts = [len(r) for r in rings]
        out[f"{a}~{b}"] = {"station": s, "vertices": counts, "gap_mm": round(gap * 1000, 4), "normal_deg": round(turn, 3),
                           "pass": counts[0] == counts[1] > 0 and gap <= JOINT_GAP and turn <= JOINT_TURN}
    return out


def unwrap(bl, objs, mirrored, atlas, fill):
    """Skin islands for objs packed onto one atlas-sized canvas: scaled down to TEXEL_TARGET, or with fill (the
    composite's shared atlas) left at the density the pack reaches. Returns the UV report."""
    scene = bpy.context.scene
    meshes = list(objs.values())
    for o in meshes:
        bl.box_project(o)
    unique = {}
    for o in meshes:
        skip = set(mirrored.get(o.name, {})) | (set(range(len(o.data.polygons))) if o.name in MIRROR_PARTS else set())
        unique[o.name] = [i for i in bl.slot_faces(o, bl.SKIN) if i not in skip]
    owners = [o for o in meshes if unique[o.name]]
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in owners:
        bl.select_faces(o, unique[o.name])
        o.select_set(True)
    bpy.context.view_layer.objects.active = owners[0]
    tools = scene.tool_settings
    tools.mesh_select_mode = (False, False, True)
    tools.use_uv_select_sync = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.0)
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, shape_method="CONCAVE", margin_method="FRACTION", margin=UV_MARGIN)
    bpy.ops.object.mode_set(mode="OBJECT")
    areas = [bl.skin_areas(o, unique[o.name]) for o in owners]
    world_a, uv_a = map(sum, zip(*areas))
    packed = atlas * math.sqrt(uv_a / world_a)
    if packed < TEXEL_TARGET:
        raise SystemExit(f"the skin does not fit the {atlas} canvas at {TEXEL_TARGET} px/m (packs at {packed:.1f})")
    k = 1.0 if fill else TEXEL_TARGET / packed
    for o in owners:
        uv = o.data.uv_layers["UVMap"].data
        for i in unique[o.name]:
            for li in o.data.polygons[i].loop_indices:
                uv[li].uv *= k
    bad = {}
    for o in meshes:
        pairs = mirrored.get(o.name, {})
        if pairs:
            bad[o.name] = copy_mirrored_uvs(o, list(pairs), o, list(pairs.values()))
        if o.name in MIRROR_PARTS:
            src = objs[MIRROR_PARTS[o.name]]
            faces = bl.slot_faces(o, bl.SKIN)
            bad[o.name] = copy_mirrored_uvs(o, faces, src, faces)
    per_part = {}
    for o in meshes:
        faces = bl.slot_faces(o, bl.SKIN)
        if faces:
            wa, ua = bl.skin_areas(o, faces)
            per_part[o.name] = {"skin_m2": round(wa, 2), "px_per_m": round(atlas * math.sqrt(ua / wa), 1)}
    return {"atlas": atlas, "target_px_per_m": TEXEL_TARGET, "packed_px_per_m": round(packed, 1), "scaled_by": round(k, 4),
            "px_per_m": round(packed * k, 2), "unique_skin_m2": round(world_a, 1), "unique_atlas_fraction": round(uv_a * k * k, 4),
            "mirrored_faces": {n: len(p) for n, p in mirrored.items() if p}, "mirror_mismatches": {n: b for n, b in bad.items() if b},
            "parts": per_part}


# ---------- smoothing ----------
def hull_normals(objs, surf, coords):
    """Hull faces take the surface's own normal at each vertex, so shading runs on unbroken across the part joints
    (each part alone would bend its rim normals toward its cap). Returns loops set per part."""
    done = {}
    for o in objs.values():
        me = o.data
        cls = np.zeros(len(me.polygons), np.int32)
        me.attributes["cls"].data.foreach_get("value", cls)
        hull = np.isin(cls, (surface.HULL, surface.RADOME))
        if not hull.any():
            continue
        loops = [tuple(n.vector) for n in me.corner_normals]
        mw = o.matrix_world
        inv = mw.to_3x3().inverted()
        vco = np.array([tuple(mw @ v.co) for v in me.vertices])
        s, deg, _ = coords.locate(vco)
        cache, n = {}, 0
        for p in me.polygons:
            if not hull[p.index]:
                continue
            for li in p.loop_indices:
                vi = me.loops[li].vertex_index
                if vi not in cache:
                    # Only the radome's pole takes the axis normal: at 0.02 the rings round 1 added at s 0.006 and 0.015
                    # took it too and shaded a flat 12 cm disc on the tip (art review round 2).
                    w = surf.normal(s[vi], deg[vi]) if s[vi] > 0.001 else Vector((0, -1, 0))
                    cache[vi] = tuple((inv @ w).normalized())
                loops[li] = cache[vi]
                n += 1
        me.normals_split_custom_set(loops)
        done[o.name] = n
    return done


# ---------- checks ----------
def shell_report(obj):
    """Triangles, shells, open edges, inward shells and world bounds. The damage structure (m4/airframe.py) is open
    where it sits against the lining: its edges count as open only where they meet a face of another slot (a break face
    on the skin's edge), and a shell of structure alone is not tested for its normals."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bm.normal_update()  # transform moves the vertices only: a part on a turned hinge kept its local normals
    frame = {i for i, m in enumerate(obj.data.materials) if m and m.name == airframe.SLOT}
    open_edges = sum(1 for e in bm.edges if not e.is_manifold and any(f.material_index not in frame for f in e.link_faces))
    shells, seen = 0, set()
    inward = 0
    for f in bm.faces:
        if f.index in seen:
            continue
        shells += 1
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        if all(g.material_index in frame for g in comp):
            continue
        vol = sum(g.calc_center_median().dot(g.normal) * g.calc_area() for g in comp) / 3
        inward += vol < 0
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    structure = sum(len(f.verts) - 2 for f in bm.faces if f.material_index in frame)
    lo = [min(v.co[i] for v in bm.verts) for i in range(3)]
    hi = [max(v.co[i] for v in bm.verts) for i in range(3)]
    bm.free()
    return {"tris": tris, "structure_tris": structure, "shells": shells, "open_edges": open_edges, "inward_shells": inward,
            "bounds": [[round(x, 3) for x in lo], [round(x, 3) for x in hi]]}


def checks(bl, group, objs, uv, extension):
    ground = set(getattr(group, "GROUND_PARTS", ()))
    parts = {n: shell_report(o) for n, o in objs.items()}
    tris = sum(p["tris"] for p in parts.values())
    lo = [min(p["bounds"][0][i] for p in parts.values()) for i in range(2)]
    lo.append(min((p["bounds"][0][2] for n, p in parts.items() if n not in ground), default=0.31))
    hi = [max(p["bounds"][1][i] for p in parts.values()) for i in range(3)]
    grounded = {n: parts[n]["bounds"][0][2] for n in sorted(ground)}
    half_span = max(abs(lo[0]), abs(hi[0]))
    span_limit = bl.RETRACTED_SEMISPAN + extension * 0.5 * (bl.SPAN_EXTENDED + 0.25 - 2 * bl.RETRACTED_SEMISPAN)
    # the hangar's 45 m with the spawn at the aircraft's middle (world y = 0 at station Y0)
    fore, aft = lo[1] + bl.Y0, hi[1] + bl.Y0
    margin = (bl.LENGTH_LIMIT - bl.LENGTH) / 2
    skin = {n: v for n, v in uv["parts"].items() if n in objs}
    envelope = {"lowest_z": round(lo[2], 3), "highest_z": round(hi[2], 3), "half_width": round(half_span, 3),
                "stations": [round(fore, 3), round(aft, 3)]}
    if ground:
        envelope["on_runway_z"] = grounded
    res = {
        "tris": {"value": tris, "limit": group.BUDGET_TRIS, "pass": tris <= group.BUDGET_TRIS},
        "closed_shells": {"value": sum(p["open_edges"] for p in parts.values()), "pass": all(p["open_edges"] == 0 for p in parts.values())},
        "outward_normals": {"value": sum(p["inward_shells"] for p in parts.values()), "pass": all(p["inward_shells"] == 0 for p in parts.values())},
        "texel_density": {"value": skin, "limit": "60 px/m or more", "pass": all(v["px_per_m"] >= 60 for v in skin.values() if v["skin_m2"] > 1)},
        "envelope": {"value": envelope,
                     "limit": f"above 0.3 m ({', '.join(sorted(ground)) or 'nothing'} on the runway within 1 cm), under {bl.TAIL_TOP_LIMIT} m, "
                              f"half width inside {span_limit:.2f} m, stations {-margin:.3f} to {bl.LENGTH + margin:.3f} "
                              f"(the {bl.LENGTH_LIMIT} m hangar)",
                     "pass": lo[2] > 0.3 and hi[2] < bl.TAIL_TOP_LIMIT and half_span < span_limit
                             and fore >= -margin - 1e-4 and aft <= bl.LENGTH + margin + 1e-4
                             and all(abs(z) <= 0.01 for z in grounded.values())},
    }
    if hasattr(group, "check"):
        res.update(group.check(bl, objs))
    return parts, res


# ---------- textures ----------
def moves_with_stages(obj):
    while obj is not None:
        if "slide_axis" in obj:
            return True
        obj = obj.parent
    return False


def texture_atlas(bl, built, atlas, density, extension, out, stem):
    """Bake one proxy of every built group onto the atlas and run each group's paint over the texels its parts own.
    The touching blockout parts occlude the AO without taking texels, and the parts that slide with the stages take
    their AO at full extension (retracted, every ray from a stage's skin hits the root's inside).
    built: [(group module, objs, mirrored)]. Writes textures/<stem>_*.png; returns the maps, the sheet and timings."""
    t0 = time.time()
    objs = {n: o for _, g_objs, _ in built for n, o in g_objs.items()}
    occluders = touching(objs)
    mirrored = {n: set(p) for _, _, g_mir in built for n, p in g_mir.items()}
    mirrored.update({n: set(range(len(o.data.polygons))) for n, o in occluders.items()})
    group_of = {n: k + 1 for k, (_, g_objs, _) in enumerate(built) for n in g_objs}
    every = [*objs.values(), *occluders.values()]
    moving = {n for n, o in objs.items() if moves_with_stages(o)}

    def proxy():
        for o in every:
            o.hide_render = True
        return texture.make_proxy(every, bl.SKIN, mirrored, group_of, moving)

    p = proxy()
    buf = texture.bake_buffers(p, atlas)
    bpy.data.objects.remove(p)
    if moving and extension < 1.0:
        scene = render_parts()
        bl.set_extension(scene, 1.0)
        p = proxy()
        ao_ext = texture.bake_ao(p, atlas)
        bpy.data.objects.remove(p)
        bl.set_extension(scene, extension)
        # The root's end caps stay put but sit against the tip cuff when retracted, so they bake near black there too.
        extended_ao = buf["moving"].copy()
        for k, (group, _, _) in enumerate(built):
            if group.GROUP == "wing":
                extended_ao |= (buf["group"] == k + 1) & (buf["cls"] == group.CAP_ROOT)
        buf["ao"] = np.where(extended_ao, ao_ext, buf["ao"])
    # A group whose parts swing into another pose (its stowed(objs) context) bakes the AO of STOWED_AO_CLASSES there
    # too, and each of those texels takes the pose it shows in, the lighter: the main legs' sleeves turn in the leg's
    # slot, so one sector shows gear down and another gear up, each sealed against the sponson's bump in the other.
    for k, (group, g_objs, _) in enumerate(built):
        if hasattr(group, "stowed"):
            with group.stowed(g_objs):
                p = proxy()
                ao_stowed = texture.bake_ao(p, atlas)
                bpy.data.objects.remove(p)
            sel = (buf["group"] == k + 1) & np.isin(buf["cls"], group.STOWED_AO_CLASSES)
            buf["ao"] = np.where(sel, np.maximum(buf["ao"], ao_stowed), buf["ao"])
    t_bake = time.time() - t0
    for o in every:
        o.hide_render = False
    paint_device = paint.select_backend()
    xp = paint.np
    buf = {key: xp.asarray(value) for key, value in buf.items()}
    valid = buf["valid"]
    coords = paint.FuselageCoords(bl)
    surf = surface.Fuselage(bl)
    H = W = atlas
    albedo, height = xp.zeros((H, W, 3)), xp.zeros((H, W))
    ms = xp.zeros((H, W, 4))
    masks, texels = {}, {}

    def text_mask(body):
        if body not in masks:
            masks[body] = xp.asarray(texture.text_mask(body))
        return masks[body]

    for k, (group, _, _) in enumerate(built):
        sel = valid & (buf["group"] == k + 1)
        texels[group.GROUP] = int(sel.sum())
        if not sel.any():
            continue
        flat = {key: buf[key][sel] for key in ("pos", "nrm", "cls", "ao", "curv")}
        cv = paint.Canvas(flat, coords, 1.0 / density)
        cv.surf = surf
        group.paint(cv, text_mask)
        cv.finish(flat["ao"], flat["curv"])
        albedo[sel] = cv.albedo
        ms[sel, 0:3] = cv.metal[:, None]
        ms[sel, 3] = cv.smooth
        height[sel] = cv.height
    normal = paint.normal_from_height(height, valid, density)
    ao = xp.ones((H, W, 3))
    ao[valid] = xp.clip(0.15 + 0.85 * buf["ao"][valid], 0, 1)[:, None]
    structured = xp.asarray(over_structure(objs, paint.to_host(buf["pos"][valid]), paint.to_host(buf["nrm"][valid]),
                                           paint.to_host(buf["cls"][valid])))
    dmg_b, dmg_h = damage(buf["pos"][valid], buf["ao"][valid], structured)
    damaged, dented = xp.ones((H, W, 4)), height.copy()
    damaged[valid] = dmg_b
    dented[valid] += dmg_h
    tex = out / "textures"
    tex.mkdir(parents=True, exist_ok=True)
    maps = {"albedo": texture.save_image(albedo, tex / f"{stem}_b.png", srgb=True),
            "metal_smooth": texture.save_image(ms, tex / f"{stem}_m.png"),
            "normal": texture.save_image(normal, tex / f"{stem}_n.png"),
            "ao": texture.save_image(ao, tex / f"{stem}_ao.png"),
            "damage": texture.save_image(damaged, tex / f"{stem}_dmg_b.png", srgb=True),
            "damage_normal": texture.save_image(paint.normal_from_height(dented, valid, density), tex / f"{stem}_dmg_n.png")}
    if atlas == COMPOSITE_ATLAS:  # the liveries are albedos on the shared atlas the export carries
        flat = {key: buf[key][valid] for key in ("pos", "nrm", "cls", "group", "moving")}
        repainted = albedo.copy()
        for key, rgb in livery.paint_liveries(coords, flat, albedo[valid], ms[valid, 0], [g.GROUP for g, _, _ in built], 1.0 / density).items():
            repainted[valid] = rgb
            texture.save_image(repainted, tex / f"{stem}_livery_{key}.png", srgb=True)
    shrink = atlas // ATLAS
    sheet = texture_sheet(bl, paint.to_host(buf["island"]), [paint.to_host(layer) for layer in
                          [albedo, normal, ao, xp.repeat(ms[..., 3:4], 3, axis=2)]], tex / f"{stem}_sheet.png", shrink)
    paint.synchronize()
    island_fraction = round(float(buf["island"].mean()), 4)
    paint.np = np
    return maps, sheet, {"bake_s": round(t_bake, 1), "paint_s": round(time.time() - t0 - t_bake, 1),
                         "device": paint_device, "island_fraction": island_fraction, "texels": texels}


def damage(pos, ao, structured):
    """The damaged skin the game's AircraftSkin fades in as a part loses hit points: RGB multiplies the albedo, metal
    and smoothness (soot and scorch, near white where the paint survives), A below 0.5 burns through (holes open
    where A is lowest first, so they grow with the damage), and a dent height added to the paint's. Per texel from
    the world position, like the paint. Burn-through opens only where structured: the hull over a part's modelled
    damage structure (over_structure), so a hole shows frames and lining, never an empty shell."""
    np = paint.np
    soot = paint.smoothstep(0.45, 0.8, paint.fbm(pos, 1.6, 3, seed=21))
    scorch = paint.smoothstep(0.55, 0.85, paint.fbm(pos * np.array([1.0, 0.5, 1.0]), 0.9, 3, seed=23))
    burn = paint.fbm(pos, 0.7, 3, seed=29)
    tone = np.clip(0.92 - 0.45 * soot - 0.3 * scorch - 0.1 * (1 - ao), 0.15, 1.0)
    tone = tone * (1 - 0.8 * structured * paint.smoothstep(0.58, 0.68, burn))  # charred round a burn-through's edge
    rgb = np.stack([tone, tone * 0.97, tone * 0.93], axis=1)
    alpha = np.where(structured, np.clip(1.0 - 1.4 * paint.smoothstep(0.62, 0.82, burn), 0.0, 1.0), 1.0)
    dent = -0.006 * paint.smoothstep(0.5, 0.9, paint.fbm(pos, 0.45, 3, seed=31)) - 0.002 * (paint.value_noise(pos, 0.12, seed=37) - 0.5)
    return np.concatenate([rgb, alpha[:, None]], axis=1), dent


def texture_sheet(bl, island, layers, path, shrink=1):
    """The used corner of each map, side by side: albedo, normal, AO, smoothness; box-filtered down by shrink."""
    ys, xs = np.nonzero(island)
    y1, x1 = ys.max() + 8, xs.max() + 8
    y1, x1 = -(-y1 // shrink) * shrink, -(-x1 // shrink) * shrink
    tiles = []
    for layer in layers:
        t = np.zeros((y1, x1, 3))
        h, w = min(y1, layer.shape[0]), min(x1, layer.shape[1])
        t[:h, :w] = np.clip(layer[:h, :w], 0, 1)
        tiles.append(t.reshape(y1 // shrink, shrink, x1 // shrink, shrink, 3).mean(axis=(1, 3)))
    gap = np.full((y1 // shrink, 6, 3), 0.08)
    row = np.hstack(sum(([t, gap] for t in tiles), [])[:-1])
    return bl.save_png(row, path)


# ---------- review ----------
def review_look(bl, detailed, textures):
    """The review look: shared slots in flat paint, the detailed skin in its baked maps (linked per object, so the
    mesh data keeps Centurion_skin), the damage structure in the airframe trim (textures: the folder holding its
    sheet). detailed: {name: (objs, maps)}. Returns the camera."""
    render.style_shared({"skin": bl.SKIN, "struct": bl.STRUCT, "mech": bl.MECH, "glass": bl.GLASS, "gear": bl.GEAR},
                        paint.PAINT[surface.HULL])
    sheet = {k: textures / f"airframe_{c}.png" for k, c in (("albedo", "b"), ("metal_smooth", "m"), ("normal", "n"))}
    if airframe.SLOT in bpy.data.materials and sheet["albedo"].exists():
        render.preview_material(airframe.SLOT, sheet)
    for name, (objs, maps) in detailed.items():
        skin_preview = render.preview_material(f"M4_{name}_preview", maps)
        for o in objs.values():
            for slot in o.material_slots:
                if slot.material and slot.material.name == bl.SKIN:
                    slot.link = "OBJECT"
                    slot.material = skin_preview
    cam, _ = render.build_rig(bl)
    for name in ("Colliders", "LOD1"):
        for o in bpy.data.collections[name].objects:
            o.hide_render = True
    return cam


# ---------- main ----------
def main():
    opts = parse_args()
    out = opts["out"]
    out.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.open_mainfile(filepath=str(BLOCKOUT / f"centurion_s61_{opts['span']}.blend"))
    bl = load_blockout()
    device = "CPU" if render.game_running() else render.use_gpu(bpy.context.scene)
    extension = 1.0 if opts["span"] == "extended" else 0.0
    surf = surface.Fuselage(bl)
    mats = {m.name: m for m in bpy.data.materials}
    for name in LIGHTS + STOCK_SLOTS + (airframe.SLOT,):
        mats[name] = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    composite = opts["composite"]
    atlas = COMPOSITE_ATLAS if composite else ATLAS

    built, t_build = [], {}
    for group in opts["groups"]:
        t0 = time.time()
        objs, mirrored = swap_group(bl, group, surf, mats)
        built.append((group, objs, mirrored))
        t_build[group.GROUP] = round(time.time() - t0, 1)
    bpy.context.view_layer.update()
    objs = {n: o for _, g_objs, _ in built for n, o in g_objs.items()}
    mirrored = {n: p for _, _, g_mir in built for n, p in g_mir.items()}
    scene = {**objs, **touching(objs)}
    bl.set_extension(scene, 0.0)  # bury_hidden_skin measures at rest, then at full extension, and leaves them at rest
    buried = bl.bury_hidden_skin(scene, mats[bl.STRUCT])
    split_buried_pairs(objs, mirrored)
    bl.set_extension(scene, extension)
    slot_order = list(bl.SLOT_ORDER) + list(LIGHTS) + list(STOCK_SLOTS) + [airframe.SLOT]
    for o in objs.values():
        order_slots(o, slot_order)
    uv = unwrap(bl, objs, mirrored, atlas, fill=composite)
    trims = {g.GROUP: g.trim(bl, g_objs, out / "textures") for g, g_objs, _ in built if hasattr(g, "trim")}
    mech = mech_trim(bl, objs, out / "textures", slot_order)
    frames = airframe_trim(objs, out / "textures")
    hard = bl.bake_normals(objs)
    hull_normals(objs, surf, paint.FuselageCoords(bl))
    density = uv["px_per_m"]
    # Each span packs its own atlas, but both write into the same textures/ folder: the extended maps get their own stem,
    # or whichever span builds second repaints the other's blend (round 2's extended sheets showed retracted paint). The
    # retracted composite keeps "centurion", the names the export and CenturionAuthor read.
    stem = "centurion" if composite else opts["groups"][0].GROUP
    if opts["span"] == "extended":
        stem += "_extended"
    joints = joint_continuity(bl, objs) if composite else None
    maps, sheet, tex_t = texture_atlas(bl, built, atlas, density, extension, out, stem)

    metrics = {}
    for group, g_objs, g_mir in built:
        part_stats, result = checks(bl, group, g_objs, uv, extension)
        if group.GROUP in trims:
            result["trim"] = trims[group.GROUP]
        m = {"group": group.GROUP, "parts": part_stats, "checks": result, "all_pass": all(c["pass"] for c in result.values()),
             "buried_skin_faces": {n: v for n, v in buried.items() if n in g_objs},
             "hard_edges": {n: v for n, v in hard.items() if n in g_objs},
             "texels": tex_t["texels"].get(group.GROUP), "timings_s": {"build": t_build[group.GROUP]}}
        metrics[group.GROUP] = m
        print(f"M4 {group.GROUP}: tris={result['tris']['value']}/{group.BUDGET_TRIS} all_pass={m['all_pass']} "
              + json.dumps({k: v['pass'] for k, v in result.items()}))
    smoothness = bl.smoothness_report(render_parts()) if composite else None  # the owner's flow rule
    label = f"m4_{opts['span']}" if composite else f"m4_{opts['groups'][0].GROUP}_{opts['span']}"
    blend = out / f"centurion_{label}.blend"
    # the maps this run wrote (the skin's and any trim's), which tools/export_blockout.py carries to Unity
    bpy.context.scene["m4_textures"] = sorted(p.name for p in (out / "textures").glob("*.png")
                                              if p.stat().st_mtime >= t_start and not p.stem.endswith("_sheet"))
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False)

    renders, render_s = [], 0.0
    if opts["render"]:
        cam = review_look(bl, {stem: (objs, maps)}, out / "textures")
        t0 = time.time()
        if not composite:
            group = opts["groups"][0]
            for view, spec in group.VIEWS.items():
                renders.append(str(render.shoot(bl, cam, spec, out / f"{group.GROUP}_{view}.png", opts["samples"])))
            renders.append(bl.contact_sheet(renders[:4], out / f"{group.GROUP}_sheet.png"))
        views = render.AIRCRAFT_VIEWS_EXTENDED if extension else render.AIRCRAFT_VIEWS
        if composite:
            views = {**views, **render.COMPOSITE_VIEWS}
        for view, spec in views.items():
            renders.append(str(render.shoot(bl, cam, spec, out / f"aircraft_{view}_{opts['span']}.png", opts["samples"])))
        render_s = round(time.time() - t0, 1)

    tris = sum(m["checks"]["tris"]["value"] for m in metrics.values())
    texture_report = {"maps": {k: str(v) for k, v in maps.items()}, "sheet": str(sheet), "atlas": atlas,
                      "device": tex_t["device"],
                      "px_per_m": density, "island_fraction": tex_t["island_fraction"],
                      "timings_s": {"bake": tex_t["bake_s"], "paint": tex_t["paint_s"]}}
    summary = {"span": opts["span"], "device": device, "blend": str(blend), "renders": renders, "uv": uv,
               "textures": texture_report, "mech_trim": mech, "airframe_trim": frames,
               "neighbours": sorted(n for n in scene if n not in objs),
               "timings_s": {"render": render_s, "total": round(time.time() - t_start, 1)}}
    if composite:
        structure = sum(sum(1 for p in o.data.polygons if o.data.materials[p.material_index].name == airframe.SLOT
                            for _ in range(len(p.vertices) - 2)) for o in objs.values())
        summary.update({"smoothness": smoothness, "groups": metrics, "joints": joints,
                        "lod0_tris": {"value": tris, "limit": LOD0_CEILING, "pass": tris <= LOD0_CEILING,
                                      "exterior": tris - structure, "structure": structure},
                        "all_pass": tris <= LOD0_CEILING and mech["pass"] and frames["pass"]
                        and all(j["pass"] for j in joints.values()) and all(m["all_pass"] for m in metrics.values())})
        (out / f"metrics_{label}.json").write_text(json.dumps(summary, indent=1))
    else:
        group = opts["groups"][0]
        summary.update({**metrics[group.GROUP], "timings_s": {**metrics[group.GROUP]["timings_s"], **summary["timings_s"]}})
        (out / f"metrics_{group.GROUP}.json").write_text(json.dumps(summary, indent=1))
    print(f"M4 {label}: groups={','.join(metrics)} tris={tris} all_pass={all(m['all_pass'] for m in metrics.values())} "
          f"atlas={atlas} px_per_m={density} islands={tex_t['island_fraction']} "
          f"timings={json.dumps(summary['timings_s'])} blend={blend}")


main()
