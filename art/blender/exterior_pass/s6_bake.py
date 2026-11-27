"""Pass stage 6, the one bake: albedo, metal and smoothness, normal, AO, the new damage map and its normal, and the four
liveries, all on the repacked atlas, from detail_centurion.texture_atlas. UNTESTED (written while Blender was
unavailable).

texture_atlas paints each texel with the group module (m4/*.py) that owns its object. The parts mix groups inside one
object, so each part is split here into temporary per-group copies by the face attribute paint_group (s1_cut), each
parented to its part (the stages' AO is baked extended, which moves only what slides). Faces whose texels belong to
another face (uv_copy: mirrored copies and twins, s4_uv) go to the proxy's dummy slot, as texture_atlas's `mirrored`.
The damage map is replaced by torn_damage() below: pieces about CELL across opening in the Darkreach's curve, a ragged
standing border scorched dark, alpha written so the game's rule D*(alpha-0.52)+0.02 < 0 opens each piece at its level.

blender --background --python s6_bake.py -- [--force]"""
import json
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

ctx = P.begin("s6_bake", __file__)
import detail_centurion as DC  # noqa: E402
from m4 import paint  # noqa: E402
from m4.blockout import load_blockout  # noqa: E402

from damage_field import CLOSED_ALPHA, SCORCH, open_alpha, open_hp  # noqa: E402


def torn_damage(pos, ao, structured):
    """Per texel from world position: (rgba, dent) as detail_centurion.damage returns them. RGB multiplies the albedo as
    health falls (soot, and a scorched ring just outside each tear); A opens each texel at its own health (the Icarus's
    method: damage_field.open_hp)."""
    np = paint.np
    hp = open_hp(pos, paint)
    opens = hp > 0
    alpha = np.where(opens, open_alpha(np.where(opens, hp, 1.0), np), CLOSED_ALPHA)
    rag = paint.fbm(pos, 0.03, 4, seed=59)
    soot = paint.smoothstep(0.45, 0.8, paint.fbm(pos, 1.6, 3, seed=21))
    tone = np.clip(0.92 - 0.45 * soot - 0.1 * (1 - ao), 0.15, 1.0)
    near = ~opens & (hp > -400 * SCORCH)  # the standing rim round a tear: scorched
    speck = paint.smoothstep(0.62, 0.7, paint.fbm(pos, 0.08, 3, seed=61))  # irregular black scorch, as the stock map has
    tone = tone * np.where(near, 0.3 + 0.25 * rag, 1.0) * (1 - 0.7 * speck * (opens | near))
    rgb = np.stack([tone, tone * 0.97, tone * 0.93], axis=1)
    dent = -0.006 * paint.smoothstep(0.5, 0.9, paint.fbm(pos, 0.45, 3, seed=31))
    return np.concatenate([rgb, alpha[:, None]], axis=1), dent


DC.damage = torn_damage  # texture_atlas calls DC.damage

# ---- liveries without roundels, and where the roundels go (as F-240-Icarus-II does: art/textures/faction_marks.py) ----
# The repository never holds the game's roundels, not even inside a livery map. The liveries are written complete but
# for them; pass/faction_marks.json records the liveries and their maps, and `faction_marks.py place` adds where each
# roundel goes once the bake is exported (its PLACEMENTS, in aircraft terms).
import numpy as host  # noqa: E402

from m4 import livery  # noqa: E402
from m4 import texture as _texture  # noqa: E402

FACTION = {"Boscali": "BDF", "Primeva": "PALA"}
STASH = {}
_bake_buffers = _texture.bake_buffers


def _bake_buffers_kept(proxy, size, *a, **k):
    """texture.bake_buffers, keeping the first bake's valid mask: the livery texels are its texels in this order."""
    buf = _bake_buffers(proxy, size, *a, **k)
    if "valid" not in STASH:
        STASH["valid"], STASH["size"] = host.asarray(paint.to_host(buf["valid"])), size
        STASH["buf"] = buf  # texture_atlas lightens its AO in place (extension, stowed gear): read once it returns
    return buf


_texture.bake_buffers = _bake_buffers_kept

def paint_liveries_pass(coords, flat, albedo, metal, groups, px):
    """livery.paint_liveries without its insignia: the paint is livery.py's."""
    np = paint.np
    pos, nrm, cls = flat["pos"], flat["nrm"], flat["cls"]
    w, lum = livery.paint_weight(albedo, metal, cls)
    for name, classes in livery.BARE.items():
        if name in groups:
            w = w * ~((flat["group"] == groups.index(name) + 1) & np.isin(cls, classes))
    ratio = lum / livery.L0
    out = {}
    for key, (_, faction, tones, style) in livery.LIVERIES.items():
        target = livery.camo_tone(tones, pos) if len(tones) > 1 else np.ones((len(cls), 3)) * np.asarray(tones[0])
        out[key] = np.clip(albedo + (target * ratio[:, None] - albedo) * w[:, None], 0.0, 1.0)
    return out


livery.paint_liveries = paint_liveries_pass

# gear.stowed swings the main legs by name; here the group's objects are the bake's temporary copies, parented to the
# real legs, so the real legs swing and the copies follow
from contextlib import contextmanager  # noqa: E402

from m4 import gear as _gear  # noqa: E402

_stowed = _gear.stowed


@contextmanager
def _stowed_pass(objs):
    with _stowed({n: bpy.data.objects[n] for n in ("gear_LM", "gear_RM")}):
        yield


_gear.stowed = _stowed_pass

import fairing  # noqa: E402

if fairing.variant_on():  # the flaps and their fairings down: the faces that touch at rest (the rear half's top, the flap
    # underside it covered) baked black in each other's occlusion; the FLAP and FAIRING texels take the lighter of the
    # two poses, as the main legs' housings do theirs (detail_centurion.texture_atlas)
    import math as _math

    import sweep as _SW
    from mathutils import Matrix
    from m4 import wing as _wing

    @contextmanager
    def _flaps_down(objs):
        flaps = [e for e in _SW.surfaces() if e[0].name.startswith("flap_")]
        fairs = [o for o in bpy.data.objects if o.get("fairing_of")]
        was_ = {o: o.matrix_world.copy() for o in [e[0] for e in flaps] + fairs}
        sign_ = {e[0].name: (-1 if e[2][-1] < 0 else 1) for e in flaps}
        for h, _, _, _ in flaps:
            h.matrix_world = _SW.turn(h, sign_[h.name] * 30) @ h.matrix_world
        for f in fairs:
            ax_ = f.matrix_world.col[0].xyz.normalized()
            p_ = f.matrix_world.translation.copy()
            f.matrix_world = (Matrix.Translation(p_) @ Matrix.Rotation(_math.radians(sign_[f["fairing_of"]] * 30), 4, ax_)
                              @ Matrix.Translation(-p_) @ f.matrix_world)
        bpy.context.view_layer.update()
        try:
            yield
        finally:
            for o, m in was_.items():
                o.matrix_world = m
            bpy.context.view_layer.update()

    _wing.stowed = _flaps_down
    _wing.STOWED_AO_CLASSES = (_wing.FLAP, _wing.FAIRING)

bl = load_blockout()
objs, _ = P.part_objects()
HIDDEN0 = {o.name for o in bpy.data.objects if o.hide_render}  # hidden by design before the bake hides the originals
groups = list(DC.GROUPS.values())
built = [(g, {}, {}) for g in groups]
temps = []
for o in objs.values():
    me = o.data
    if not any(m and m.name == P.SKIN for m in me.materials):
        continue
    pg = [0] * len(me.polygons)
    if "paint_group" in me.attributes:
        me.attributes["paint_group"].data.foreach_get("value", pg)
    cp = [0] * len(me.polygons)
    if "uv_copy" in me.attributes:
        me.attributes["uv_copy"].data.foreach_get("value", cp)
    for gi in sorted(set(pg)):
        g = gi - 1 if gi > 0 else next(i for i, m in enumerate(groups) if m.GROUP == "wing")  # untagged: new pass faces
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        # the two-sided skin's inward copies (s3) leave the bake: they lie on the skin, so every AO ray met them at once and
        # the AO baked black; they read their originals' texels anyway
        tw = [0] * len(me.polygons)
        if "twin_src" in me.attributes:
            me.attributes["twin_src"].data.foreach_get("value", tw)
        keep = {i for i, x in enumerate(pg) if x == gi and not tw[i]}
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in keep], context="FACES")
        bm.faces.index_update()
        copies = {f.index for f, src in zip(bm.faces, sorted(keep)) if cp[src]}
        tm = bpy.data.meshes.new(f"bake_{o.name}_{gi}")
        bm.to_mesh(tm)
        bm.free()
        for m in me.materials:  # a mesh made through bmesh has no slots: without them no face is skin and nothing bakes
            tm.materials.append(m)
        t = bpy.data.objects.new(tm.name, tm)
        bpy.context.scene.collection.objects.link(t)
        t.parent = o
        temps.append(t)
        built[g][1][t.name] = t
        built[g][2][t.name] = copies
    o.hide_render = True
built = [b for b in built if b[1]]
bpy.context.view_layer.update()  # the copies' world matrices, which make_proxy reads
print("S6 groups", [(g.GROUP, len(o), sum(len(x.data.polygons) for x in o.values())) for g, o, _ in built], flush=True)
density = json.loads((P.PASS / "atlas_record.json").read_text())["px_per_m"]
# the collision hulls and LOD hulls enclose the skin and render: every AO ray met them and the AO baked black. The
# shipped pipeline bakes before damage_parts makes them; here they leave the bake and come back after
helpers = [c for c in (bpy.data.collections.get("Colliders"), bpy.data.collections.get("LOD1")) if c]
was = [(c, c.hide_render) for c in helpers] + [(o, o.hide_render) for c in helpers for o in c.all_objects]
for x, _ in was:
    x.hide_render = True
# the occluders, named: detail_centurion.touching takes every render part the baked meshes' bounds touch, and the
# temps live outside the Centurion collection, so it brought back every hidden original whole, twins included
# (27,414 inward faces on the skin, the AO at its minimum). Here an occluder is a render mesh no
# temp stands for, not hidden by design, and no collider, distant hull or blockout
represented = {t.parent.name for t in temps}
HELPER_TAIL = ("_blockout_mesh", "_shape")


def explicit_occluders(objs_, margin=0.05):
    boxes = [DC.world_box(o) for o in objs_.values()]
    out = {}
    for name, o in DC.render_parts().items():
        if name in objs_ or name in represented or name in HIDDEN0 or name.endswith(HELPER_TAIL) or "_colmesh" in name or "_lod1" in name:
            continue
        lo, hi = DC.world_box(o)
        if any(all(lo[i] - margin <= b[1][i] and b[0][i] <= hi[i] + margin for i in range(3)) for b in boxes):
            out[name] = o
    return out


OCC = explicit_occluders({t.name: t for t in temps})


def twin_faces(o):
    a = o.data.attributes.get("twin_src")
    if a is None:
        return 0
    v = [0] * len(o.data.polygons)
    a.data.foreach_get("value", v)
    return sum(1 for x in v if x)


bad_occ = {n: twin_faces(o) for n, o in OCC.items() if twin_faces(o)}
print("S6 occluders", len(OCC), sorted(OCC), "with twins", bad_occ, flush=True)
if bad_occ or any(n.endswith(HELPER_TAIL) or "_colmesh" in n or "_lod1" in n for n in OCC):
    raise SystemExit(f"s6_bake: an occluder carries twins or is a helper: {bad_occ}")
DC.touching = explicit_occluders
maps, sheet, timings = DC.texture_atlas(bl, built, DC.COMPOSITE_ATLAS, density, 0.0, P.PASS, "centurion")
for x, h in was:
    x.hide_render = h
# stencils printed whole: each decal's ink on its painter's own texels against the stencil's full ink (a stencil running
# onto faces another group paints loses its glyphs there: the aft flank's serial read "043")
from m4 import paint as PT  # noqa: E402
short = [d for d in PT.DECALS if d["printed_cells"] < d["ink_cells"]]
(P.PASS / "stencils_s6.json").write_text(json.dumps(PT.DECALS, indent=1))
for d in short:
    print("S6 stencil printed short", d["at"], "at station", d["centre_s"], "arc", d["centre_arc"],
          f"{d['printed_cells']} of its {d['ink_cells']} inked cells", flush=True)
STENCILS = {"decals": len(PT.DECALS), "printed_short": len(short)}
if short:  # build 37's bake: the serial's flanks 34 and 30 of 42 cells; every stencil whole once the groups came from the cut
    raise SystemExit(f"s6_bake: {len(short)} stencils printed short (stencils_s6.json)")
# ---- the liners' primer: the atlas point s4 gave the inward liners (an empty cell, 32 px) painted primer grey in the
# albedo and every livery, opaque and unscorched in the damage map, AO 1, flat normal. Black there made every hole and
# break look onto a black cap (round 2's review) ----
# At 0.55 the liners read as a bright sliver in the gap between a flap fairing's halves (build 43, flaps 15): a darker
# primer still keeps every hole off black
PRIMER_SRGB = (0.33, 0.34, 0.32)
LINER_UV = json.loads((P.PASS / "s4_uv.json").read_text())["report"]["liner_uv"]
# The recess tones. The open split's gaps are shaded live by the game (its screen-space occlusion and the raised parts'
# shadows; the baked AO there is 1), so no albedo lifts them to the open skin's shade: the tones keep a dark gap reading
# as shade and not as a light grid on black. Builds 49 and 50, on screen from behind and above (.cache/refresh/art2/b50).
# Sunlit (s4_uv RECESS_UV, facing up at rest: a lower half's inner face, the wells' floors): at 0.17 106 to 116 from
# above against the wing skin's 148 to 163, and 12 to 20 from behind in the roll-right pose, where the same face is in
# the gap's shade. At 0.25 (build 51) 130 from above, 0.84 of the skin, paler than the tilted halves' outer skin beside
# it: the opening read as a light plate; 0.20 is about 0.72.
RECESS_SRGB = (0.20, 0.203, 0.206)
RECESS_UV = json.loads((P.PASS / "s4_uv.json").read_text())["report"]["recess_uv"]
# Shaded (s4_uv RECESS_SHADE_UV: facing down, a spoiler's underside panels, an upper half's inner face): at 0.36 a
# spoiler's panels read 21 to 23 from behind; 0.55 is about 32.
RECESS_SHADE_SRGB = (0.55, 0.555, 0.56)
RECESS_SHADE_UV = json.loads((P.PASS / "s4_uv.json").read_text())["report"]["recess_shade_uv"]
# A spoiler's ribs (s4_uv RECESS_RIB_UV): their sides catch the sun in the open gap, 163 to 174 at 0.36 against the
# panels' 23 (build 50); 0.06 puts them near 1.3 times the panels at 0.55, low relief on one dark surface.
RECESS_RIB_SRGB = (0.06, 0.061, 0.062)
RECESS_RIB_UV = json.loads((P.PASS / "s4_uv.json").read_text())["report"]["recess_rib_uv"]


def paint_block(path, rgba, at=None, r=12):
    im = bpy.data.images.load(str(path))
    w, h = im.size
    px = host.empty(w * h * 4, dtype=host.float32)
    im.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    at = at or LINER_UV
    cx, cy = int(at[0] * w), int(at[1] * h)
    for k, val in enumerate(rgba):
        if val is not None:
            px[cy - r:cy + r, cx - r:cx + r, k] = val
    im.pixels.foreach_set(px.ravel())
    im.save()
    bpy.data.images.remove(im)


MAPS_DIR = P.PASS / "textures"
for at, rgb in ((LINER_UV, PRIMER_SRGB), (RECESS_UV, RECESS_SRGB), (RECESS_SHADE_UV, RECESS_SHADE_SRGB),
                (RECESS_RIB_UV, RECESS_RIB_SRGB)):
    for path in [MAPS_DIR / "centurion_b.png", *sorted(MAPS_DIR.glob("centurion_livery_*.png"))]:
        paint_block(path, (*rgb, None), at)  # an 8-bit PNG's pixels read and write as stored (sRGB)
    paint_block(MAPS_DIR / "centurion_dmg_b.png", (1.0, 1.0, 1.0, 1.0), at)
    paint_block(MAPS_DIR / "centurion_m.png", (0.0, 0.0, 0.0, 0.3), at)  # matte paint, not whatever bled into the block
    paint_block(MAPS_DIR / "centurion_ao.png", (1.0, 1.0, 1.0, None), at)
    paint_block(MAPS_DIR / "centurion_n.png", (0.5, 0.5, 1.0, None), at)
print("S6 liner primer at", LINER_UV, "sunlit recesses at", RECESS_UV, "shaded recesses at", RECESS_SHADE_UV, "spoiler ribs at", RECESS_RIB_UV, flush=True)
ao_all = host.asarray(paint.to_host(STASH["buf"]["ao"])).astype(float).ravel()
ao_ = ao_all[host.asarray(STASH["valid"]).ravel().astype(bool)] if ao_all.size == STASH["valid"].size else ao_all
ao_ = ao_ / 255.0 if ao_.max() > 1.5 else ao_
AO = {"texels": int(ao_.size), "p1": round(float(host.percentile(ao_, 1)), 3), "p5": round(float(host.percentile(ao_, 5)), 3),
      "median": round(float(host.median(ao_)), 3), "share_under_0_15": round(float((ao_ < 0.15).mean()), 4)}
print("S6 AO over the baked texels", AO, flush=True)
for t in temps:
    bpy.data.objects.remove(t)
for o in objs.values():
    o.hide_render = False
import hashlib  # noqa: E402

TEXD = P.PASS / "textures"
# the maps tools/export_blockout.py copies (the scene's m4_textures, from textures/ beside the blend): the ones baked here,
# the gear's, carried over unchanged (the gear keeps its own slot, Centurion_gear), and the engines' swatch sheet (s4
# keeps the fan, nacelles and nozzles on jet_mechanical; CenturionAuthor.AuthorMech binds it as Centurion_mech). No part
# is on the airframe slot any more (s4 folds it onto Centurion_trim_cut), so its maps are not listed
GEAR_MAPS = [f"gear_trim_{k}.png" for k in ("b", "m", "n")]
MECH_MAPS = ["mech_trim_b.png", "mech_trim_m.png"]
DC.mech_sheet(TEXD)
for name in GEAR_MAPS:
    (TEXD / name).write_bytes((P.REPO / ".cache" / "art" / "m4_parts" / "textures" / name).read_bytes())
# the gear's material reads its maps from wherever the detail build left them (an absolute path under .cache/wipers on
# this desktop): pointed at these copies, relative to the blend, they travel with it (Invoke-PassScript -ShipBlend),
# where the review on the second machine had drawn the gear untextured
for im in bpy.data.images:
    if Path(bpy.path.abspath(im.filepath)).name in GEAR_MAPS:
        im.filepath = "//textures/" + Path(bpy.path.abspath(im.filepath)).name
        im.reload()
bpy.context.scene["m4_textures"] = sorted([p.name for p in TEXD.glob("centurion_*.png") if p.name != "centurion_sheet.png"] + GEAR_MAPS + MECH_MAPS)
record = {
    "atlas_size": STASH["size"],
    "skin_uv_sha256": json.loads((P.PASS / "atlas_record.json").read_text())["uv_sha256"],
    "roundels": {"PALA": "PALA_roundel", "BDF": "BDF_roundel"},
    "liveries": {key: {"name": name, "faction": FACTION[faction], "map": f"centurion_livery_{key}.png",
                       "map_sha256": hashlib.sha256((TEXD / f"centurion_livery_{key}.png").read_bytes()).hexdigest()}
                 for key, (name, faction, _, _) in livery.LIVERIES.items()},
    "marks": [],
}
(P.PASS / "faction_marks.json").write_text(json.dumps(record))
import export_parts  # noqa: E402
P.finish(ctx, {"exported_actuators": export_parts.actuators_into_export(), "degenerate_dropped": export_parts.drop_degenerate(),
               "export_hard_edges": sum(export_parts.export_normals().values()), "maps": {k: str(v) for k, v in maps.items()}, "sheet": str(sheet), "timings": timings,
               "occluders": sorted(OCC), "ao": AO, "stencils": STENCILS})
