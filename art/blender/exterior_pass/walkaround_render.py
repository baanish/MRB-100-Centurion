"""The walk-around's renders: every view of walkaround_plan.py's plan (or its first tier) rendered from the baked
blend, posed and drawn as near the game as the review rig gets: back faces culled (render_rig's camera cull), the
pass's maps and painted liveries on the skin, the stock jet_mechanical sheet on the trim, sun and sky, the twins 2 mm in
(Cycles shadows a coincident twin black). Writes <out>/<frame>.png and <out>/frames.json ({frame, part, group, pose,
view, eye_used, seen, in_the_way, blocked}); a sheet per group is cut from them by walkaround_sheets.py.

Each eye is scored by the share of the part's eye-facing surface it sees first (seen_share). The plan's eye stands
when it is outside every body and sees SEEN_MIN of the part; otherwise it is cleared of geometry (clear_eye) and
swung round the part, the best of those taken (best_eye), and one that still sees under SEEN_MIN is marked blocked,
which the game runs leave out. The eye taken then backs off along its view until it stands EYE_CLEAR off every
surface, so the game camera's near plane does not cut the hull.

Poses, as the game moves the parts:
- gear up: main struts closed 0.5 m, then the legs 120 degrees inboard about their hinges, nose leg 128 forward (gear.py, CenturionAuthor), every gear
  door its quarter turn shut (CenturionAuthor.CloseGearDoor: the turn that points its skin's summed normal down);
  gear down: the blend's rest.
- flaps 15/30: each flap and its fairings' rear halves trailing edge down that many degrees about their hinges.
- roll left/right: ailerons 25 degrees, the left one trailing edge up for roll left; split open: each aileron's halves
  apart by 50 degrees (sweep.py's travel); the spoiler on the side whose aileron goes up 15 degrees up, its actuators
  following.
- pitch up/down: the ruddervators 25 degrees trailing edge up/down.
- wing extended: the telescoping stages slid out (render_rig.set_extension).
- bay open: each bay door a quarter turn out and down about its hinge (an approximation of the authoring's RigDoor).
- faction: BDF on the matte grey livery, PALA on the desert camouflage, both with their roundels painted.

blender --background <s6_bake.blend> --python walkaround_render.py -- <plan.json> <out dir> [--tier 1] [--res W]
[--samples N] [--only text,text (frames whose name holds one)]"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
import pass_common as P  # noqa: E402
import render_rig as L  # noqa: E402
import sweep as SW  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
plan, OUT = json.loads(Path(args[0]).read_text()), Path(args[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
TIER = int(args[args.index("--tier") + 1]) if "--tier" in args else None
W = int(args[args.index("--res") + 1]) if "--res" in args else 1200
SAMPLES = int(args[args.index("--samples") + 1]) if "--samples" in args else 32
ONLY = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
LIVERY = {"BDF": "bdf_matte_gray", "PALA": "pala_desert_camo"}
ROLL, SPLIT, PITCH, MAIN_FOLD, NOSE_FOLD = 25.0, 50.0, 25.0, 120.0, 128.0
SPOILER_ROLL, MAIN_SHRINK = 15.0, 0.5  # CenturionAuthor Surfaces' spoiler roll range; gear.py MAIN_SHRINK

views = [v for v in plan if TIER is None or v["tier"] <= TIER]

L.hide_helpers(lod_too=True)
cam = L.rig(ground=True)
scene = bpy.context.scene
# the game's ambient lights the underside, which the rig's one sun leaves near black: a soft fill from below
fill = bpy.data.objects.new("wa_fill", bpy.data.lights.new("wa_fill", "SUN"))
fill.data.energy, fill.data.angle, fill.rotation_euler = 1.2, math.radians(30), (math.radians(180), 0, 0)
fill.data.use_shadow = False
scene.collection.objects.link(fill)
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
maps = {k: tex / f"centurion_{k}.png" for k in ("b", "m", "n", "ao") if not (k == "n" and "--no-normal" in args)}


def livery(faction):
    marked = P.PASS / "textures_marked" / f"centurion_livery_{LIVERY[faction]}.png"
    return marked if marked.exists() else tex / f"centurion_livery_{LIVERY[faction]}.png"


skins = {f: L.skin_material(f"wa_skin_{f}", maps, livery=livery(f)) for f in LIVERY}
trim = L.skin_material("wa_trim", {"b": P.game_texture("jet_mechanical_AlbedoTransparency.png"),
                                   "m": P.game_texture("jet_mechanical_MetallicSmoothness.png"),
                                   "ao": P.game_texture("jet_mechanical_Occlusion.png")}, cull=True)
skin_slots = []
for me in bpy.data.meshes:
    for i, m in enumerate(me.materials):
        if m is not None and m.name == P.SKIN:
            skin_slots.append((me, i))
            me.materials[i] = skins["BDF"]
        elif m is not None and m.name == "Centurion_trim_cut":
            me.materials[i] = trim
scene.render.resolution_x, scene.render.resolution_y = W, W * 3 // 4
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.cycles.samples, scene.cycles.use_denoising = SAMPLES, True

O = bpy.data.objects
BASIS = {o.name: o.matrix_basis.copy() for o in O}
SURF = SW.surfaces()  # (hinge, meshes, degrees, label), signs from the rest pose
TE_UP = {}
for hinge, moving, degs, label in SURF:
    TE_UP[label] = SW.te_sign(hinge, moving)
GEAR_DOORS = [n for n in ("geardoor_FL", "geardoor_FR", "geardoor_LM", "geardoor_RM") if n in O]
BAY_DOORS = [o.name for o in O if o.name.startswith("baydoor_") and not o.name.endswith("_visible") and o.type != "MESH"]


def summed_normal(vis):
    me = vis.data
    me.calc_loop_triangles()
    n = Vector()
    for t in me.loop_triangles:
        if t.material_index == 0:
            p = [vis.matrix_world @ me.vertices[i].co for i in t.vertices]
            n += (p[1] - p[0]).cross(p[2] - p[0])
    return n


SHUT = {}
for d in GEAR_DOORS:
    n = summed_normal(O[d + "_visible"])
    ax = (O[d].matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()
    SHUT[d] = 90 if (Matrix.Rotation(math.radians(90), 3, ax) @ n).z < (Matrix.Rotation(math.radians(-90), 3, ax) @ n).z else -90
BAY_OPEN = {}
for d in BAY_DOORS:
    vis = O.get(d + "_visible")
    if vis is None:
        continue
    c = sum((vis.matrix_world @ Vector(b) for b in vis.bound_box), Vector()) / 8
    ax = (O[d].matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()
    piv = O[d].matrix_world.translation
    BAY_OPEN[d] = max((90, -90), key=lambda s: -(Matrix.Rotation(math.radians(s), 3, ax) @ (c - piv)).z)


UPPER_DEG = {}  # each aileron's upper turn in the pose being set: the lower half rides it when parented to the hinge


def about(o, pivot, axis, deg):
    o.matrix_world = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-pivot) @ o.matrix_world


def pose(p):
    for o in O:
        if o.name in BASIS:
            o.matrix_basis = BASIS[o.name]
    bpy.context.view_layer.update()
    L.set_extension(1.0 if p.get("wing") == "extended" else 0.0)
    for me, i in skin_slots:
        me.materials[i] = skins[p.get("faction", "BDF")]
    if p.get("gear", "up") == "up":
        for sfx, side in (("LM", 1), ("RM", -1)):
            g = O[f"gear_{sfx}"]
            hinge_at, wheel = g.matrix_world.translation.copy(), O[f"wheel_{sfx}"]
            # the strut closes MAIN_SHRINK along its axis first (gear.py strut_axis; CenturionAuthor.ShrinkMainStrutAsArt)
            b_ = wheel.matrix_world.translation
            lift = (hinge_at - Vector((b_.x + side * 0.03, b_.y, b_.z + 0.27))).normalized() * MAIN_SHRINK
            wheel.matrix_world = Matrix.Translation(lift) @ wheel.matrix_world
            bpy.context.view_layer.update()
            about(g, hinge_at, Vector((0, 1, 0)), side * MAIN_FOLD)
        g = O["gear_F"]
        about(g, g.matrix_world.translation.copy(), Vector((1, 0, 0)), -NOSE_FOLD)
        for d in GEAR_DOORS:
            o = O[d]
            about(o, o.matrix_world.translation.copy(), (o.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized(), SHUT[d])
    if p.get("bay") == "open":
        for d, s in BAY_OPEN.items():
            o = O[d]
            about(o, o.matrix_world.translation.copy(), (o.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized(), s)
    bpy.context.view_layer.update()
    flap = float(p.get("flaps", 0))
    roll = {"neutral": 0.0, "left": 1.0, "right": -1.0}[p.get("roll", "neutral")]
    split = SPLIT / 2 if p.get("split") == "open" else 0.0
    pitch = {"neutral": 0.0, "up": 1.0, "down": -1.0}[p.get("pitch", "neutral")]
    UPPER_DEG.clear()
    for hinge, moving, degs, label in SURF:
        up = TE_UP[label]
        name = hinge.name
        if name.startswith("flap_"):
            deg = -up * flap  # trailing edge down
        elif name.startswith("aileron_"):
            # roll left: the left aileron's trailing edge up, the right one's down; the split opens the halves apart
            side = 1.0 if name.startswith("aileron_L") else -1.0
            te = ROLL * roll * side + (split if label.endswith("upper") else -split)
            deg = up * te
        elif name.startswith("ruddervator_"):
            deg = up * PITCH * pitch
        else:
            continue
        target = hinge
        if label.endswith("lower"):
            target = O[name + "_visible_lower"]
            if target.parent is not None and (target.parent == hinge or target.parent in hinge.children_recursive):
                deg -= UPPER_DEG.get(name, 0.0)  # it rode the hinge's turn already
        elif name.startswith("aileron_"):
            UPPER_DEG[name] = deg
        if abs(deg) < 1e-6:
            continue
        target.matrix_world = SW.turn(hinge, deg) @ target.matrix_world
        bpy.context.view_layer.update()
    # roll: the spoiler on the side whose aileron goes up rises, the other stays down (src/Centurion/SurfaceRules.cs);
    # its rods ride the panel and each cylinder turns about its eye to stay aimed at its rod's (CenturionAuthor.RigActuators)
    for side, name in ((1.0, "spoiler_L"), (-1.0, "spoiler_R")):
        if roll * side <= 0 or name not in O:
            continue
        hinge = O[name]
        rods = [O[f"{name}_rod_{k}"] for k in range(1, 9) if f"{name}_rod_{k}" in O]
        turn = SW.turn(hinge, SW.te_sign(hinge, [O[name + "_visible"]]) * SPOILER_ROLL)
        eyes = {rod.name: rod.matrix_world.translation.copy() for rod in rods}
        for o in [O[name + "_visible"], *rods]:
            if o.parent not in (hinge, O[name + "_visible"]):
                o.matrix_world = turn @ o.matrix_world
        bpy.context.view_layer.update()
        for k, rod in enumerate(rods, 1):
            cyl = O.get(f"{name}_cylinder_{k}")
            if cyl is None:
                continue
            eye = cyl.matrix_world.translation.copy()
            spin = (eyes[rod.name] - eye).rotation_difference(rod.matrix_world.translation - eye).to_matrix().to_4x4()
            cyl.matrix_world = Matrix.Translation(eye) @ spin @ Matrix.Translation(-eye) @ cyl.matrix_world
        bpy.context.view_layer.update()


def frame_name(v):
    p = "_".join(f"{k}-{v['pose'][k]}" for k in sorted(v["pose"])) or "rest"
    return f"{v['group']}__{v['part']}__{p}__{v['view']}"


PROBE = (int(args[args.index("--probe") + 1]), int(args[args.index("--probe") + 2])) if "--probe" in args else None


def probe(name):
    """What the camera sees, cell by cell, in the posed scene: the first front face (back faces skipped, as culled) by
    object, material and twin, an ASCII map and its legend, instead of a render."""
    import string
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    fr = [cam.matrix_world @ c for c in cam.data.view_frame(scene=scene)]  # tr, br, bl, tl
    o = cam.matrix_world.translation.copy()
    keys, letters = {}, string.ascii_lowercase + string.ascii_uppercase + string.digits
    for r in range(PROBE[1]):
        line = ""
        for c in range(PROBE[0]):
            u, w = (c + 0.5) / PROBE[0], (r + 0.5) / PROBE[1]
            d = (fr[3].lerp(fr[0], u).lerp(fr[2].lerp(fr[1], u), w) - o).normalized()
            q, ch = o, " "
            for _ in range(16):
                ok, loc, nrm, idx, ob, _m = scene.ray_cast(dg, q, d)
                if not ok:
                    break
                if nrm.dot(d) > 0 or ob.hide_render or any(c.hide_render for c in ob.users_collection):
                    q = loc + d * 1e-4
                    continue
                me = ob.data
                mat = me.materials[me.polygons[idx].material_index].name if me.materials else "-"
                tw = me.attributes.get("twin_src")
                key = (ob.name, mat, "twin" if tw is not None and tw.data[idx].value else "")
                keys.setdefault(key, letters[len(keys) % len(letters)])
                ch = keys[key]
                break
            line += ch
        print("PROBE |" + line + "|", flush=True)
    for key, ch in keys.items():
        print("PROBE LEGEND", ch, key, flush=True)


CLEAR = 0.15  # an eye pulled in this far short of the surface that stood between it and its part


def clear_eye(v, eye=None):
    """The plan's eye (or `eye`), or nearer: cast from the part's centre out toward the eye, and stop CLEAR short of
    the first other surface past the part's own outermost skin (a wing over a fairing, the body round a hatch), so no
    view starts inside geometry or behind something. What the part encloses (a retracted wing stage stowed in the
    wing) and the helpers are passed through. Returns the eye and the object that stopped it, or None."""
    target, eye = Vector(v["target"]), Vector(eye if eye is not None else v["eye"])
    if v.get("keep_eye"):  # a hand-placed view compared with an earlier render of it
        return eye, None
    d = (eye - target).normalized()
    reach = (eye - target).length
    own = v["part"].replace("_visible", "")
    dg = bpy.context.evaluated_depsgraph_get()
    q, hits = target.copy(), []
    for _ in range(64):
        ok, loc, nrm, idx, ob, _m = scene.ray_cast(dg, q, d, distance=reach - (q - target).length)
        if not ok:
            break
        if not (ob.hide_render or any(c.hide_render for c in ob.users_collection)):
            hits.append(((loc - target).length, ob.name.replace("_visible", "").replace("_lower", "").startswith(own), ob.name))
        q = loc + d * 1e-4
    skin = max((t for t, mine, _n in hits if mine), default=0.0)
    for t, mine, name in hits:
        if t > skin and not mine:
            return target + d * max(t - CLEAR, 0.5), name
    return eye, None


SEEN_MIN = 0.25  # a view that shows less of its part's eye-facing surface than this is blocked


def first_front(dg, eye, p):
    """The object of the first front face on the line from eye to p (helpers passed), or None when nothing stands in it."""
    d, reach = (p - eye).normalized(), (p - eye).length
    q = eye.copy()
    for _ in range(64):
        ok, loc, nrm, idx, ob, _m = scene.ray_cast(dg, q, d, distance=reach + 1e-3 - (q - eye).length)
        if not ok:
            return None
        if nrm.dot(d) > 0 or ob.hide_render or any(c.hide_render for c in ob.users_collection):
            q = loc + d * 1e-4
            continue
        return ob
    return None


def seen_share(v, eye, samples=200):
    """The share of the part's eye-facing faces (area weighted, up to `samples` face centres) that the eye sees first,
    and the object most often in the way: a ray to the part's centre alone misses a part whose centre is inside it or
    under an overhang."""
    import random
    own = v["part"].replace("_visible", "")
    dg = bpy.context.evaluated_depsgraph_get()
    faces = []
    for ob in O:
        if ob.type != "MESH" or ob.hide_render or not ob.name.replace("_visible", "").replace("_lower", "").startswith(own):
            continue
        ev = ob.evaluated_get(dg)
        me, mw, m3 = ev.data, ev.matrix_world, ev.matrix_world.to_3x3()
        for p in me.polygons:
            c = mw @ p.center
            if (m3 @ p.normal).dot(eye - c) > 0:
                faces.append((p.area, c + (m3 @ p.normal).normalized() * 1e-3, ob.name))
    if not faces:
        return 0.0, None
    pick = random.Random(7).choices(faces, weights=[f[0] for f in faces], k=min(samples, len(faces)))
    seen, others = 0, {}
    for _a, c, name in pick:
        ob = first_front(dg, eye, c)
        if ob is None or ob.name == name or ob.name.replace("_visible", "").replace("_lower", "").startswith(own):
            seen += 1
        else:
            others[ob.name] = others.get(ob.name, 0) + 1
    return seen / len(pick), max(others, key=others.get) if others else None


SWING_DEG = (25, -25, 50, -50)  # the angles a poor view's eye is swung through, about the vertical and the side axis
PUSH_M = 0.25  # an eye inside the hull is tried this much further out along its view, twelve times
NEAR_MIN = 0.5  # an eye cleared to under this share of the plan's distance is a close-up of whatever stopped it


# The game's free camera stays 1.7 m over the ground under it (CameraFreeState.cs:102): an eye planned lower is lifted,
# and under the radome that put it inside the nose (build 41). Parked on the runway that floor is Blender z 1.80
# (runway 138.28 m, the root parked 3.83 m above it, ROOT_Z 3.95: walkaround_scenarios). Airborne views ride the
# aircraft and have no floor.
PARKED_EYE_FLOOR = 1.8


def eye_floor(v, plan):
    return PARKED_EYE_FLOOR if v["pose"].get("gear", "down") == "down" else min(plan.z, 0.3)


def best_eye(v):
    """The cleared eye, or, when it sees too little of the part or had to come in close (a flap's fairing behind the
    flap outboard of it, an aileron under the spoiler's overhang), the cleared eye swung round the part that scores
    best: the share it sees, scaled down for an eye pulled in under NEAR_MIN of the plan's distance."""
    target = Vector(v["target"])
    off = Vector(v["eye"]) - target

    def score(e):
        s, w = seen_share(v, e)
        return s * min(1.0, (e - target).length / (off.length * NEAR_MIN)), s, w

    plan = Vector(v["eye"])
    if v.get("keep_eye"):
        return plan, *seen_share(v, plan)
    best = (-1.0, 0.0, None, plan)
    if not inside(plan) and plan.z >= eye_floor(v, plan):  # the plan's eye stands when it is in the open and sees the part
        best = (*score(plan), plan)
        if best[1] >= SEEN_MIN:
            return plan, best[1], best[2]
    eye, v["eye_stop"] = clear_eye(v)
    cands = [eye] + [target + off * (1 + k * PUSH_M / off.length) for k in range(1, 13)]  # pushed out along the view
    a = off.cross(Vector((0, 0, 1)) if abs(off.normalized().z) < 0.9 else Vector((1, 0, 0))).normalized()
    for ax in (a, off.cross(a).normalized()):  # two axes square to the view: a view from straight above swings too
        for deg in SWING_DEG:
            swung = target + Matrix.Rotation(math.radians(deg), 3, ax) @ off
            cands += [swung, clear_eye(v, swung)[0]]
    for e in cands:
        if e.z < eye_floor(v, plan) or inside(e):  # never under the floor (the ground, or the game's camera floor), nor inside
            continue
        cand = (*score(e), e)
        if cand[0] > best[0]:
            best = cand
    return best[3], best[1], best[2]


def inside(p):
    """Whether p is inside a body or a cavity (helpers passed): along some axis both rays leave through a back face
    first (one axis is enough, so a point inside a thin wing open at its ends counts), or no ray of the six axes and
    eight diagonals escapes to the sky (a spoiler's well, every face of it facing in)."""
    dg = bpy.context.evaluated_depsgraph_get()

    def first(d):
        q = p.copy()
        for _ in range(64):
            ok, loc, nrm, idx, ob, _m = scene.ray_cast(dg, q, d)
            if not ok:
                return None
            if ob.hide_render or any(c.hide_render for c in ob.users_collection):
                q = loc + d * 1e-4
                continue
            return (loc - p).length, nrm.dot(d) > 0
        return None
    axes = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
    hits = [(first(ax), first(-ax)) for ax in axes]
    if any(a and b and a[1] and b[1] for a, b in hits):
        return True
    if any(h is None for pair in hits for h in pair):
        return False
    return all(first(Vector((x, y, z)).normalized()) is not None for x in (-1, 1) for y in (-1, 1) for z in (-1, 1))


EYE_CLEAR = 0.6  # the game camera's near plane cut the nose open from eyes a few cm off the radome (build 41)


def surface_gap(p):
    """How far p stands from the nearest rendered surface."""
    dg = bpy.context.evaluated_depsgraph_get()
    gap = 1e9
    for ob in O:
        if ob.type != "MESH" or ob.name == "art2_ground" or ob.hide_render or any(c.hide_render for c in ob.users_collection):
            continue
        ev = ob.evaluated_get(dg)
        ok, loc, _n, _i = ev.closest_point_on_mesh(ev.matrix_world.inverted() @ p)
        if ok:
            gap = min(gap, (ev.matrix_world @ loc - p).length)
    return gap


def backed_off(v, eye):
    """The eye, or moved back along its view (away from the part) until it stands EYE_CLEAR off every surface."""
    target = Vector(v["target"])
    d = (eye - target).normalized()
    for k in range(33):
        e = eye + d * (0.25 * k)
        if e.z >= eye_floor(v, eye) and surface_gap(e) >= EYE_CLEAR and not inside(e):
            return e
    return eye


def shoot(v, path):
    target = Vector(v["target"])
    eye, share, v["in_the_way"] = best_eye(v)
    if not v.get("keep_eye"):
        moved = backed_off(v, eye)
        if moved != eye:
            eye, (share, v["in_the_way"]) = moved, seen_share(v, moved)
    v["eye_used"] = [round(c, 3) for c in eye]
    v["seen"] = round(share, 3)
    v["blocked"] = share < SEEN_MIN  # the game runs leave such a view out
    cam.location = eye
    d = (target - eye).normalized()
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()  # the camera's own up is +Y ("Z" laid every view on its side)
    cam.data.type, cam.data.lens = "PERSP", 30
    if PROBE:
        probe(path.stem)
        return
    ground = O.get("art2_ground")
    if ground is not None:  # a view from under the belly has its eye below the ground plane
        ground.hide_render = eye.z < 0.3
    scene.render.filepath = str(path)
    L.assert_clean(lod_too=True)
    bpy.ops.render.render(write_still=True)


record = []
views.sort(key=lambda v: json.dumps(v["pose"], sort_keys=True))  # one pose set up once for its views
last = None
for v in views:
    name = frame_name(v)
    if ONLY and not any(s in name for s in ONLY):
        continue
    key = json.dumps(v["pose"], sort_keys=True)
    if key != last:
        pose(v["pose"])
        last = key
    shoot(v, OUT / f"{name}.png")
    record.append({"frame": name, **{k: v[k] for k in ("part", "group", "pose", "view", "eye", "target")},
                   "eye_used": v.get("eye_used", v["eye"]), "seen": v.get("seen"), "eye_stop": v.get("eye_stop"), "in_the_way": v.get("in_the_way"), "blocked": v.get("blocked", False)})
    print("WALKAROUND frame", len(record), name, flush=True)
(OUT / "frames.json").write_text(json.dumps(record, indent=1))
print("WALKAROUND rendered", len(record), "frames to", OUT, flush=True)
