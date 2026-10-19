"""MRB-100 Centurion AWACS beam mount, graybox: the meshes, colliders, LOD1 hulls and pose markers of M3's mount prefab
(docs/M3-DESIGN.md "Mount prefab"), built in hardpoint_dorsal's frame (origin on the crown at the spine cover's
station) from the direction E study's numbers, which art/blender/awacs_beam_blockout.py keeps (MOUNT, rise_geometry).
The beam rides a dorsal blade nearly its length, as the E-7 Wedgetail's does: two nested blades (awacs_mast_1 and 2)
rising out of a sleeve under the well's floor, the upper one swept like a fin (blade_spans). Then the mount is posed on
the step 6.1 airframe at deploy 0, 0.5 and 1 to measure the least gap to every collider but fuselage_R's, whose pair
with the mount's joint never collides, and rendered for review. CenturionAuthor's AwacsEnvelopeCheck, on the authored
colliders, stays the gate.

  blender --background --factory-startup --python art/blender/awacs_mount.py -- [--airframe BLEND] [--out DIR] [--no-render]

--airframe defaults to <repo>/.cache/art/blockout_s61/centurion_s61_retracted.blend and --out to
<repo>/.cache/art/awacs_mount. DIR gets awacs_mount.blend, which tools/export_blockout.py exports for Unity as it does
the airframe (--blend DIR/awacs_mount.blend --out art/export_awacs), metrics_awacs_mount.json and the review
renders in m4/render.py's look (Workbench while the game runs).

The blend follows build_centurion.py's export conventions: the six meshes and the empties in a "Centurion" collection,
parented as the prefab's tree; convex collider pieces, inset COL_INSET, in "Colliders" and one LOD1 hull per mesh in
"LOD1", each parented to its part at an identity transform; mass_kg on awacs_base. Every moving part is built stowed,
and its raised or extended pose is the "_raised" or "_extended" empty beside it under the same parent.
"""

import json
import math
import sys
import types
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import awacs_mount_detail as detail  # noqa: E402
import convex  # noqa: E402  (beside this script, which Blender runs without a package)
from awacs_beam_blockout import MOUNT, rise_geometry  # noqa: E402
from m4 import render as m4r  # noqa: E402

REPO = HERE.parents[1]
SKIN, STRUCT, LOD = "Centurion_skin", "aircraft_structure", "LOD"  # build_centurion.py's slot names
COL_INSET = 0.028  # build_centurion.py's: every hull face 2.8 cm inside the skin
LOD1_VERTS, LOD1_GREY = 10, 0.14  # a hull of V vertices has 2V - 4 triangles; the stock LOD material reads 0.14 grey
BASE_MASS_KG = 1500.0  # the mount AeroPart's own mass; the WeaponMount's 4,500 kg emptyMass rides fuselage_R
POSES = (0.0, 0.5, 1.0)
GAP_MIN, STOW_LIMIT = 0.10, 7.45  # AwacsEnvelopeCheck's collider gap and stowed top (m above wheel contact)
MOVING = (("awacs_mast_1", "awacs_mast_1_raised", "mast"), ("awacs_mast_2", "awacs_mast_2_raised", "mast"),
          ("awacs_beam_ext_F", "awacs_beam_ext_F_extended", "ends"), ("awacs_beam_ext_R", "awacs_beam_ext_R_extended", "ends"))
PAINT_SRGB = (0.38, 0.39, 0.405)  # m4/paint.py's hull grey
# name: m4/render.py view, (lens, camera (x, station, z), target (x, station, z)), or (("ortho", scale, camera euler deg),
# camera, None); the spine well spans stations 24.7 to 34.8.
VIEWS = {"well": (35, (9.0, 41.5, 13.5), (0.0, 29.8, 6.3)),
         "side": (("ortho", 26.0, (90, 0, 90)), (60.0, 29.8, 6.5), None),
         "three_quarter": (35, (24.0, 50.0, 19.0), (0.0, 29.5, 7.5)),
         "close": (35, (9.0, 22.0, 12.0), (0.0, 29.5, 9.0)), "end": (40, (3.5, 42.5, 11.5), (0.0, 37.0, 9.6))}


# ---------- the mount ----------
def naca_ring(chord, thick, z, n=20):
    """A symmetric streamlined section at height z, chord along Y centred on 0, leading edge forward (-Y)."""
    tc, pts = thick / chord, []
    for k in range(n):
        t = 0.5 * (1 - math.cos(math.pi * k / (n - 1)))
        pts.append((t, 5 * tc * chord * (0.2969 * math.sqrt(t) - 0.126 * t - 0.3516 * t ** 2 + 0.2843 * t ** 3 - 0.1036 * t ** 4)))
    return ([Vector((yt, -chord / 2 + t * chord, z)) for t, yt in pts]
            + [Vector((-yt, -chord / 2 + t * chord, z)) for t, yt in reversed(pts[1:-1])])


def t_ring(M, y, d=0.0, sx=1.0, sz=1.0):
    """The beam's top-hat section at y, x across and z up from the fin's foot, every wall inset by d (the end sections
    nest at d = ext_inset), scaled about its middle for the end chamfers."""
    fh, ch = M["fin_t"] / 2 - d, M["cap_w"] / 2 - d
    z0, z1, z2, c = d, M["fin_h"] + d, M["fin_h"] + M["cap_t"] - d, 0.04
    right = [(fh, z0), (fh, z1), (ch - c, z1), (ch, z1 + c), (ch, z2 - c), (ch - c, z2)]
    zc = (M["fin_h"] + M["cap_t"]) / 2
    return [Vector((x * sx, y, zc + (z - zc) * sz)) for x, z in right + [(-x, z) for x, z in reversed(right)]]


def blade_ring(z, front, back, thick):
    """The blade's streamlined section at height z from y = front to y = back (leading edge forward, -Y)."""
    return [p + Vector((0.0, (front + back) / 2, 0.0)) for p in naca_ring(back - front, thick, z)]


def blade_geometry(M):
    """The two nested blades' rises and length: the lower blade rises until its top is flush with the crown, so only the
    upper one shows under the beam, and each keeps M["overlap"] inside its parent when raised."""
    beam_h, travel, _, _ = rise_geometry(M)
    rise1 = beam_h - M["cap_above_crown"]
    rise2 = travel - rise1
    return rise1, rise2, max(rise1, rise2) + M["overlap"] + 0.01


def blade_spans(M):
    """Each blade's span along the beam (y from the beam's centre, forward negative), each M["stage_inset"] inside the one
    around it: the sleeve, the lower blade, and the upper blade at the crown and at the beam, its leading and trailing
    edges swept aft by M["blade_le_sweep"] and M["blade_te_sweep"] from the crown up (a negative sweep leans that edge
    forward). Every section of the upper blade stays inside the lower blade's span, so it nests at any height."""
    ins, le, te = M["stage_inset"], M["blade_le_sweep"], M["blade_te_sweep"]
    front, back = -M["blade_ahead"], M["blade_behind"]
    f2, b2 = front + 2 * ins, back - 2 * ins
    crown = (f2 + max(0.0, -le), b2 - max(0.0, te))
    return {"sleeve": (front, back), "lower": (front + ins, back - ins), "upper_crown": crown,
            "upper_beam": (crown[0] + le, crown[1] + te)}


def slab_rings(lo, hi):
    return [[Vector((lo[0], y, lo[2])), Vector((hi[0], y, lo[2])), Vector((hi[0], y, hi[2])), Vector((lo[0], y, hi[2]))]
            for y in (lo[1], hi[1])]


def mesh_part(name, shells, mat, parent, location, coll):
    """A closed mesh from shells of rings (each lofted and capped at both ends), box-projected UVs at 1 per 2 m."""
    bm = bmesh.new()
    for rings in shells:
        vs = [[bm.verts.new(p) for p in ring] for ring in rings]
        n = len(rings[0])
        for a, b in zip(vs, vs[1:]):
            for k in range(n):
                bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
        bm.faces.new(vs[0][::-1])
        bm.faces.new(vs[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    uv = me.uv_layers.new(name="UVMap").data
    for p in me.polygons:
        axis = max(range(3), key=lambda i: abs(p.normal[i]))
        a, b = (i for i in range(3) if i != axis)
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv[li].uv = (co[a] * 0.5, co[b] * 0.5)
    return place(bpy.data.objects.new(name, me), parent, location, coll)


def empty(name, parent, location, coll):
    o = bpy.data.objects.new(name, None)
    o.empty_display_type, o.empty_display_size = "ARROWS", 0.4
    return place(o, parent, location, coll)


def place(o, parent, location, coll):
    coll.objects.link(o)
    o.parent = parent
    o.location = location
    return o


def hull_child(name, verts, tris, part, coll, mat=None):
    """A hull mesh parented to its part at an identity transform (verts in the part's local frame)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(int(i) for i in t) for t in tris])
    me.update()
    if mat is not None:
        me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    o.parent = part
    o.hide_render = True
    return o


def collider_hull(points):
    """The convex hull of points inset COL_INSET, thinned until it is under Unity's 255-triangle convex limit (a blade
    lofted from four sections has about 300)."""
    pts = np.array([p[:] for p in points])
    for budget in (120, 90, 64):
        verts, tris = convex.inset_hull(convex.simplify_hull(pts, budget), COL_INSET, True)
        if len(verts) < 255 and len(tris) < 255:
            return verts, tris
    raise SystemExit(f"no collider hull under 255 triangles for {len(pts)} points")


def build_mount(coll, colliders, lods, mats):
    """The mount at deploy 0 in the hardpoint's frame: z 0 is the crown. Returns the objects by name, each moving
    part's stowed location and the numbers the detail pass builds on."""
    M = MOUNT
    beam_h = rise_geometry(M)[0]
    rise1, rise2, length = blade_geometry(M)
    spans = blade_spans(M)
    foot0 = M["cap_above_crown"] - beam_h  # the beam's foot under the crown, stowed
    L, ins = M["fin_len"] / 2, M["stage_inset"]
    slot_x, slot_y = M["cap_w"] / 2 + M["slot_gap"], L + 0.05  # half the airframe's slot (build_centurion.py's S6_WELL)
    # The root: the well's liner (a floor plate on the well's floor and four walls 1 cm thick, 1 cm inside the slot, up
    # to just under the skin at the slot's edge) and, below it, the fixed sleeve of the blades, hanging into the aft bay.
    floor, deck, top, xi, xo, yi, yo = foot0 - 0.06, foot0 - 0.01, -0.04, slot_x - 0.02, slot_x - 0.01, slot_y - 0.02, slot_y - 0.01
    liner = [slab_rings((-xo, -yo, floor), (xo, yo, deck)),
             slab_rings((xi, -yo, deck), (xo, yo, top)), slab_rings((-xo, -yo, deck), (-xi, yo, top)),
             slab_rings((-xi, yi, deck), (xi, yo, top)), slab_rings((-xi, -yo, deck), (xi, -yi, top))]
    sleeve = [blade_ring(z, *spans["sleeve"], M["mast_t"] + 2 * ins) for z in (foot0 - length - 0.05, foot0 - 0.05)]
    base = mesh_part("awacs_base", liner + [sleeve], mats[STRUCT], None, (0.0, 0.0, 0.0), coll)
    base["mass_kg"] = BASE_MASS_KG
    pieces = {"awacs_base": [[p for shell in liner for ring in shell for p in ring], [p for ring in sleeve for p in ring]]}
    # The lower blade never shows: in the sleeve stowed, its top flush with the crown raised.
    lower = mesh_part("awacs_mast_1", [[blade_ring(z, *spans["lower"], M["mast_t"]) for z in (-length, 0.0)]], mats[SKIN],
                      base, (0.0, 0.0, foot0), coll)
    empty("awacs_mast_1_raised", base, (0.0, 0.0, foot0 + rise1), coll)
    # The upper blade is the support: straight below the crown, swept from the crown (rise2 under its top) to the beam's
    # foot, and running 0.15 m up into the beam's fin.
    thick = M["mast_t"] - 2 * ins
    upper = mesh_part("awacs_mast_2", [[blade_ring(z, *spans[at], thick) for z, at in
                                         ((-length, "upper_crown"), (-rise2, "upper_crown"), (0.0, "upper_beam"), (0.15, "upper_beam"))]],
                      mats[SKIN], lower, (0.0, 0.0, 0.0), coll)
    empty("awacs_mast_2_raised", lower, (0.0, 0.0, rise2), coll)
    beam = mesh_part("awacs_beam", [[t_ring(M, -L, sx=0.82, sz=0.9), t_ring(M, -L + 0.15), t_ring(M, L - 0.15),
                                      t_ring(M, L, sx=0.82, sz=0.9)]], mats[SKIN], upper, (0.0, 0.0, 0.0), coll)
    d, n = M["ext_inset"], M["ext_len"]
    for tag, s in (("F", -1), ("R", 1)):
        # Origin at the outer end; retracted it sits 2 cm inside the beam's end.
        rings = [t_ring(M, 0.0, d, sx=0.35, sz=0.55), t_ring(M, -s * 0.22, d, sx=0.75, sz=0.88), t_ring(M, -s * 0.55, d), t_ring(M, -s * n, d)]
        mesh_part(f"awacs_beam_ext_{tag}", [rings[::-1] if s > 0 else rings], mats[SKIN], beam, (0.0, s * (L - 0.02), 0.0), coll)
        empty(f"awacs_beam_ext_{tag}_extended", beam, (0.0, s * (L - 0.02 + M["travel"]), 0.0), coll)
    empty("awacs_scanner", beam, (0.0, 0.0, beam_h / 2), coll)

    objs = {o.name: o for o in coll.objects}
    for name, o in objs.items():
        if o.type != "MESH":
            continue
        local = [v.co.copy() for v in o.data.vertices]
        for k, pts in enumerate(pieces.get(name, [local])):
            verts, tris = collider_hull(pts)
            hull_child(f"{name}_colmesh" + (f".{k:03d}" if k else ""), verts, tris, o, colliders)
        verts, tris = convex.hull_mesh(convex.simplify_hull(np.array([p[:] for p in local]), LOD1_VERTS))
        lod = hull_child(f"{name}_lod1", verts, tris, o, lods, mats[LOD]).data
        col = lod.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        col.data.foreach_set("color", [LOD1_GREY, LOD1_GREY, LOD1_GREY, 1.0] * len(lod.vertices))
        lod.color_attributes.active_color = col
        lod.color_attributes.render_color_index = lod.color_attributes.active_color_index
    bpy.context.view_layer.update()
    geo = {"foot0": foot0, "rise2": rise2, "length": length, "spans": spans, "slot_x": slot_x, "slot_y": slot_y}
    return objs, {name: objs[name].location.copy() for name, _, _ in MOVING}, geo


def pose(objs, rest, deploy):
    """The mount at a deployment fraction, as AwacsBeam moves it: the mast over the first two thirds, then the end
    sections, each eased (Mathf.SmoothStep) from its stowed pose to its marker's."""
    f = {"mast": min(max(1.5 * deploy, 0.0), 1.0), "ends": min(max(3.0 * deploy - 2.0, 0.0), 1.0)}
    for name, marker, stage in MOVING:
        u = f[stage]
        objs[name].location = rest[name].lerp(objs[marker].location, u * u * (3 - 2 * u))
    bpy.context.view_layer.update()


# ---------- on the airframe ----------
def world_hull(o):
    mw = o.matrix_world
    v = np.array([(mw @ p.co)[:] for p in o.data.vertices])
    return v, np.array([tuple(p.vertices) for p in o.data.polygons])


def measure(objs, rest, airframe_colliders, y0):
    """At each of POSES, and over every 0.05 between, the least gap from any mount collider to any airframe collider
    but fuselage_R's, and the mount's top above wheel contact."""
    mount_cols = [o for o in bpy.data.objects if o.parent in objs.values() and "_colmesh" in o.name]
    meshes = [o for o in objs.values() if o.type == "MESH"]
    others = [(o.parent.name, o.name, *world_hull(o)) for o in airframe_colliders if o.parent.name != "fuselage_R"]
    boxes = [(v.min(0), v.max(0)) for _, _, v, _ in others]
    out, sweep = {}, []
    for k in range(21):
        deploy = k / 20
        pose(objs, rest, deploy)
        best = moving = (math.inf, None, None)  # any mount piece; the mast, beam and end sections alone
        for c in mount_cols:
            v, t = world_hull(c)
            lo, hi = v.min(0), v.max(0)
            for (part, name, ov, ot), (blo, bhi) in zip(others, boxes):
                if max(np.max(blo - hi), np.max(lo - bhi)) > 5.0:  # boxes this far apart can't set the least gap
                    continue
                g = convex.hull_gap((v, t), (ov, ot))
                best = min(best, (g, part, c.name), key=lambda r: r[0])
                if c.parent.name != "awacs_base":
                    moving = min(moving, (g, part, c.name), key=lambda r: r[0])
        top = max((o.matrix_world @ p.co).z for o in meshes for p in o.data.vertices)
        row = {"deploy": deploy, "least_gap_m": round(best[0], 3), "to": best[1], "mount_piece": best[2], "top_m": round(top, 3),
               "moving_least_gap_m": round(moving[0], 3) if moving[1] else None, "moving_to": moving[1], "moving_piece": moving[2]}
        sweep.append(row)
        if deploy in POSES:
            out[f"{deploy:.1f}"] = row
    worst = min(sweep, key=lambda r: r["least_gap_m"])
    pose(objs, rest, 1.0)
    beam = [objs[n].matrix_world @ p.co for n in ("awacs_beam", "awacs_beam_ext_F", "awacs_beam_ext_R") for p in objs[n].data.vertices]
    raised = objs["awacs_mast_2"].matrix_world.translation.copy()
    ext = (objs["awacs_beam_ext_R"].location - rest["awacs_beam_ext_R"]).length
    pose(objs, rest, 0.0)
    return {"poses": out, "least_gap_over_0.05_steps": {**worst, "limit_m": GAP_MIN, "pass": worst["least_gap_m"] >= GAP_MIN},
            "stowed_top_m": out["0.0"]["top_m"], "stowed_limit_m": STOW_LIMIT, "stowed_pass": out["0.0"]["top_m"] <= STOW_LIMIT,
            "deployed_top_m": out["1.0"]["top_m"],
            "mast_rise_m": round((raised - objs["awacs_mast_2"].matrix_world.translation).length, 3), "end_travel_m": round(ext, 3),
            "deployed_beam_m": round(max(p.y for p in beam) - min(p.y for p in beam), 3),
            "deployed_beam_stations": [round(min(p.y for p in beam) + y0, 2), round(max(p.y for p in beam) + y0, 2)]}


def render(out, objs, rest, y0):
    """The open well (bomber lid and mount hidden), the mount stowed in it, and deployed from the side and three-quarters
    behind, in the M4 review look."""
    looks = {SKIN: (tuple(m4r.srgb_to_linear(PAINT_SRGB)), 0.6, 0.0), STRUCT: ((0.11, 0.115, 0.11), 0.7, 0.2),
             "jet_mechanical": ((0.06, 0.06, 0.065), 0.45, 0.8), "glass": ((0.008, 0.011, 0.010), 0.04, 0.0),
             "Centurion_gear": ((0.16, 0.16, 0.165), 0.55, 0.3)}
    for mat in bpy.data.materials:
        look = looks.get(mat.name.split(".")[0])  # the mount's own slots came in beside the airframe's as ".001"
        if look is not None:
            m4r.principled(mat, *look)
    for coll in bpy.data.collections:
        if coll.name.startswith(("Colliders", "LOD1")):
            for o in coll.objects:
                o.hide_render = True
    bl = types.SimpleNamespace(st=lambda s: s - y0)
    cam, _ = m4r.build_rig(bl)
    mount = [o for o in objs.values() if o.type == "MESH"]
    tex = out / "textures"
    baked = m4r.preview_material("awacs_preview", {"albedo": tex / "awacs_preview_b.png", "ao": tex / "awacs_ao.png",
                                                   "metal_smooth": tex / "awacs_m.png", "normal": tex / "awacs_n.png"})
    for o in mount:
        for slot in o.material_slots:
            slot.link, slot.material = "OBJECT", baked
    cover = bpy.data.objects["spine_cover"]
    written = []
    for label, deploy, show, view in (("well_open", 0.0, False, "well"), ("stowed", 0.0, True, "well"),
                                      ("deployed_side", 1.0, True, "side"), ("deployed_three_quarter", 1.0, True, "three_quarter"),
                                      ("deployed_close", 1.0, True, "close"), ("deployed_end", 1.0, True, "end")):
        for o in mount:
            o.hide_render = not show
        cover.hide_render = True
        pose(objs, rest, deploy)
        written.append(str(m4r.shoot(bl, cam, VIEWS[view], out / f"awacs_mount_{label}.png", 64)))
    pose(objs, rest, 0.0)
    return written


# ---------- main ----------
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = {"airframe": REPO / ".cache" / "art" / "blockout_s61" / "centurion_s61_retracted.blend",
            "out": REPO / ".cache" / "art" / "awacs_mount", "render": True}
    it = iter(argv)
    for flag in it:
        if flag == "--no-render":
            args["render"] = False
        elif flag in ("--airframe", "--out"):
            args[flag[2:]] = Path(next(it))
        else:
            raise SystemExit(f"unknown argument {flag}")
    if not all(args[k].is_absolute() for k in ("airframe", "out")):
        raise SystemExit("Pass absolute paths: Blender resolves relative paths against its own cwd.")
    return args


def main():
    args = parse_args()
    out = args["out"]
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version = 0  # no .blend1 backup beside it
    coll = bpy.data.collections.new("Centurion")
    bpy.context.scene.collection.children.link(coll)
    subs = {name: bpy.data.collections.new(name) for name in ("Colliders", "LOD1")}
    for sub in subs.values():
        coll.children.link(sub)
    mats = {}
    for name, rgba in ((SKIN, (0.62, 0.62, 0.62, 1.0)), (STRUCT, (0.42, 0.43, 0.42, 1.0)), (LOD, (0.14, 0.14, 0.14, 1.0))):
        mats[name] = bpy.data.materials.new(name)
        mats[name].diffuse_color = rgba
    objs, rest, geo = build_mount(coll, subs["Colliders"], subs["LOD1"], mats)
    for o in subs["Colliders"].objects:
        o.display_type = "WIRE"
    # The detail pass (group 8): the colliders and LOD1 hulls above came from the graybox meshes, which each part keeps
    # as its _blockout_mesh. Baked deployed, so no end section bakes inside the beam.
    tris = detail.swap_detail(objs, MOUNT, geo, mats)
    meshes = [o for o in objs.values() if o.type == "MESH"]
    px_per_m, skin_m2 = detail.unwrap(meshes)
    pose(objs, rest, 1.0)
    maps, texels = detail.bake_and_paint(meshes, MOUNT, out / "textures", px_per_m)
    pose(objs, rest, 0.0)
    detail_parts, detail_checks = detail.checks(objs, tris)
    detail_checks["texel_density"] = {"value": px_per_m, "limit": detail.TEXEL_MIN, "pass": px_per_m >= detail.TEXEL_MIN}
    bpy.context.scene["m4_textures"] = maps
    blend = out / "awacs_mount.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False)
    report = {"blend": str(blend), "mount": MOUNT, "parts": {},
              "detail": {"parts": detail_parts, "checks": detail_checks, "all_pass": all(c["pass"] for c in detail_checks.values()),
                         "atlas": detail.ATLAS, "px_per_m": px_per_m, "painted_skin_m2": skin_m2, "texels": texels, "maps": maps}}
    for o in sorted(objs.values(), key=lambda o: o.name):
        entry = {"parent": o.parent.name if o.parent else None, "location": [round(c, 4) for c in o.location]}
        if o.type == "MESH":
            cols = [c for c in subs["Colliders"].objects if c.parent == o]
            entry.update(tris=sum(len(p.vertices) - 2 for p in o.data.polygons),
                         colliders=[{"verts": len(c.data.vertices), "tris": len(c.data.polygons)} for c in cols],
                         lod1_tris=len(bpy.data.objects[o.name + "_lod1"].data.polygons))
        report["parts"][o.name] = entry

    # On the airframe: the mount's root on the spine cover's pivot, hardpoint_dorsal (CenturionAuthor.BuildBays).
    bpy.ops.wm.open_mainfile(filepath=str(args["airframe"]))
    airframe_colliders = list(bpy.data.collections["Colliders"].objects)
    with bpy.data.libraries.load(str(blend), link=False) as (_, dst):
        dst.collections = ["Centurion"]
    bpy.context.scene.collection.children.link(dst.collections[0])
    objs = {o.name: o for o in dst.collections[0].objects}
    hardpoint = bpy.data.objects["spine_cover"].matrix_world.translation.copy()
    objs["awacs_base"].location = hardpoint
    bpy.context.view_layer.update()
    rest = {name: objs[name].location.copy() for name, _, _ in MOVING}
    y0 = -min((o.matrix_world @ p.co).y for o in bpy.data.collections["Centurion"].objects if o.type == "MESH" for p in o.data.vertices)
    report["airframe"] = str(args["airframe"])
    report["hardpoint_dorsal"] = {"x": round(hardpoint.x, 3), "station": round(hardpoint.y + y0, 3), "z": round(hardpoint.z, 3)}
    rise1, rise2, length = blade_geometry(MOUNT)
    report["blade"] = {"rise_m": {"lower": round(rise1, 3), "upper": round(rise2, 3)}, "length_m": round(length, 3),
                       "thickness_m": {"sleeve": MOUNT["mast_t"] + 2 * MOUNT["stage_inset"], "lower": MOUNT["mast_t"],
                                       "upper": round(MOUNT["mast_t"] - 2 * MOUNT["stage_inset"], 3)},
                       **{name: {"stations": [round(hardpoint.y + y0 + y, 2) for y in span], "chord_m": round(span[1] - span[0], 3)}
                          for name, span in blade_spans(MOUNT).items()}}
    report["on_airframe"] = measure(objs, rest, airframe_colliders, y0)
    if args["render"]:
        report["renders"] = render(out, objs, rest, y0)
    (out / "metrics_awacs_mount.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    r = report["on_airframe"]
    print("AWACS blade: " + json.dumps(report["blade"]))
    print("AWACS mount: " + json.dumps({k: r[k] for k in r if k != "poses"}))
    d = report["detail"]
    print("AWACS detail: " + json.dumps({"all_pass": d["all_pass"], "px_per_m": d["px_per_m"], **{k: v["value"] for k, v in d["checks"].items()},
                                         "tris": {n: p["tris"] for n, p in d["parts"].items()}}))
    for key, row in r["poses"].items():
        print(f"AWACS mount deploy {key}: " + json.dumps(row))


main()
