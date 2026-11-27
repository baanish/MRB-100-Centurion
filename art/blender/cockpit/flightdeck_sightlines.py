"""Openings to the outside, as the game draws the cockpit: from each seat's eye, moved through the head's whole range
and turned through the view's whole range (CameraCockpitState, decomp/CameraCockpitState.cs:195-199 and 227: pan
-165 to 165 deg, tilt -65 to 65; the head tracker's offset x -0.25 to 0.25 m, y -0.15 to 0.15, z -0.1 to 0.45 in
the camera's frame, which holds the keyboard's 0.15 m raise and 0.2 m lean too), rays cast against the exported
interior with Unity's rules: a face seen from behind is culled (the ray goes on through it), glass and the band's
screen count as glass (the view through them is meant), the nose skin is hidden in cockpit view and every other skin
is seen from inside, so culled. A ray that leaves without meeting a front face or glass is an opening.

blender -b --factory-startup --python-exit-code 1 --python flightdeck_sightlines.py -- <export flightdeck.blend> <blockout.blend> <out.json>
           [--commander right,up,forward]   (the commander's eye from the pilot's, metres; default 1.10,-0.12,0.04)
           [--max-escaped=0,1] [--min-band=0.97,0.97] [--max-into=10]   (pilot, commander: the limits; the pilot's are the verdict's)
Also counts the rays through the camera band that reach the outside, and the rays from the pilot's eye through it that
meet any cockpit mesh (flightdeck_cut.through_screen). Exits 1 (Blender's --python-exit-code) and prints VIS VERDICT FAIL
when a pilot limit is broken; the commander's numbers are reported only."""
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
export_blend, blockout_blend, out_json = argv[:3]
cmd = [1.10, -0.12, 0.04]
if "--commander" in argv:
    cmd = [float(v) for v in argv[argv.index("--commander") + 1].split(",")]
bpy.ops.wm.open_mainfile(filepath=export_blend)
# the stock seats, sticks and throttles the game also draws (from the review scene, placed as the game places them)
with bpy.data.libraries.load(blockout_blend) as (src, dst):
    dst.objects = [n for n in src.objects if n.startswith("stock_seat") or n.startswith("stockref_Multirole1_joystick")
                   or n.startswith("stockref_Multirole1_throttle")]
for o in dst.objects:
    if o is not None:
        bpy.context.scene.collection.objects.link(o)
GLASS = {"glass_int", "band", "band_marker"}
# the pilot's pane openings: rays from his eye (every degree) whose first drawn face is a pane, by side. Build 14
# opened the left pane's forward part to a cheek's cut edge with no frame and passed every other check; build 15
# walled it again (left 449, right 235); build 16 opens it on purpose inside a frame, with the sill sloped (left 524,
# right 234); build 17 closes the frame's corners with a corner piece and the cheek held to the frame, and the
# commander's outboard module edges with flanges (left 527, right 232). An opening that grows or shrinks fails here; changing one is a decision, made by re-pinning.
PANE_OPENINGS = {"left": 527, "windscreen": 292, "right": 232}
PANE_TOLERANCE = 0.01


def build_tree(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys, info = [], [], []
    for o in objs:
        me = o.evaluated_get(dg).to_mesh()
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        for p in me.polygons:
            polys.append([base + i for i in p.vertices])
            m = o.material_slots[p.material_index].material if p.material_index < len(o.material_slots) else None
            uv_v = (sum(me.uv_layers.active.data[li].uv.y for li in p.loop_indices) / len(p.loop_indices)
                    if me.uv_layers.active else None)
            info.append((o.name, p.index, m.name if m else None, tuple(round(c, 3) for c in o.matrix_world @ p.center),
                         tuple(round(c, 2) for c in (o.matrix_world.to_3x3() @ p.normal).normalized()), round(p.area * 1e4, 1),
                         uv_v))
    return BVHTree.FromPolygons(verts, polys), info


tree, info = build_tree([o for o in bpy.context.scene.objects if o.type == "MESH"])
owner = [i[0] for i in info]
print("VIS objects", dict(Counter(owner)))
# references for the cause: the untrimmed shell and the flight deck as the blockout built it (before this rebuild)
with bpy.data.libraries.load(blockout_blend) as (src, dst):
    dst.meshes = []
    dst.objects = ["bo_shell", "flightdeck_int", "fuselage_F", "nose"]
ref_objs = dst.objects
for o in ref_objs:
    bpy.context.scene.collection.objects.link(o)
ref = {}
ref_info = {}
for o, key in zip(ref_objs[:2], ("untrimmed_shell", "blockout_flightdeck")):
    ref[key], ref_info[key] = build_tree([o])
hull = build_tree(ref_objs[2:])[0]  # where an escaping ray leaves the airframe


def first_front(tr, o_, d, limit=40.0):
    """distance to the first face the ray meets from its front, or None"""
    t0 = 0.0
    while True:
        h = tr.ray_cast(o_ + d * t0, d, limit - t0)
        if h[0] is None:
            return None
        if h[1].dot(d) < 0:
            return t0 + h[3], h[2]
        t0 += h[3] + 0.0005
EYE_P = Vector((0.55, 6.55 - 22.475, 5.0))  # blockout.EYE[1]: station 6.55, 0.55 m left, 5.0 m up
eyes = {"pilot": EYE_P, "commander": EYE_P + Vector((-cmd[0], -cmd[2], cmd[1]))}  # Unity right is Blender -X, forward -Y


SWAY = 0.075  # the G sway, 0.15 m (line 211) times PlayerSettings.cockpitCamInertia's default 0.5, on top of the tracker's box


def offsets():
    yield (0.0, 0.0, 0.0), Vector()  # the eye itself, the one position the verdict is on
    for x in (-0.25 - SWAY, 0.0, 0.25 + SWAY):
        for y in (-0.15 - SWAY, 0.0, 0.15 + SWAY):
            for z in (-0.10 - SWAY, 0.175, 0.45 + SWAY):
                yield (x, y, z), Vector((-x, -z, y))


def direction(pan, tilt):
    p, t = math.radians(pan), math.radians(tilt)
    # forward Blender -Y; pan right toward -X; tilt down toward -Z
    return Vector((-math.sin(p) * math.cos(t), -math.cos(p) * math.cos(t), -math.sin(t))).normalized()


# The camera screen's cylinder, from its own sheet: a ray out through the strip over its top edge (up to 0.30 m over it:
# the coaming, and from a raised head the windscreen's foot) and within its arc looks at the world the hidden nose
# shows there, as the screen does.
_band = bpy.data.objects.get("band")
_bv = [_band.matrix_world @ v.co for v in _band.data.vertices] if _band else []


def _circle(a, b, c):
    ax, ay, bx, by, cx, cy = a.x, a.y, b.x, b.y, c.x, c.y
    d_ = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d_
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d_
    return Vector((ux, uy, 0.0)), math.hypot(ax - ux, ay - uy)


if _bv:
    _lo = min(v.z for v in _bv)
    _ring = [v for v in _bv if abs(v.z - _lo) < 0.005]
    _c, _r = _circle(min(_ring, key=lambda v: v.x), min(_ring, key=lambda v: abs(v.x)), max(_ring, key=lambda v: v.x))
    _half = max(abs(math.atan2(v.x - _c.x, _c.y - v.y)) for v in _bv)
    _ztop = max(v.z for v in _bv)


def over_screen(o, d):
    if not _bv:
        return False
    # where the ray crosses the screen's cylinder going forward
    px, py, dx, dy = o.x - _c.x, o.y - _c.y, d.x, d.y
    A, B, C = dx * dx + dy * dy, 2 * (px * dx + py * dy), px * px + py * py - _r * _r
    disc = B * B - 4 * A * C
    if A < 1e-12 or disc < 0:
        return False
    t = (-B + math.sqrt(disc)) / (2 * A)
    q = o + d * t
    return abs(math.atan2(q.x - _c.x, _c.y - q.y)) <= _half and _ztop <= q.z <= _ztop + 0.30


res = {"limits": {"pan_deg": [-165, 165], "tilt_deg": [-65, 65], "head_m": {"x": [-0.25, 0.25], "y": [-0.15, 0.15], "z": [-0.1, 0.45]},
                  "sway_m": SWAY},
       "commander_eye_from_pilot_m": cmd, "seats": {}}
for seat, eye in eyes.items():
    escaped, rays, culled_by, holes, over = 0, 0, Counter(), defaultdict(int), 0
    escaped_eye = 0
    causes, back_faces, examples = Counter(), Counter(), []
    through = []
    for off_u, off in offsets():
        o0 = eye + off
        # a head moved there would pass through a face on the way (the roof, the seat, a module): the game does not stop
        # it, but past structure any cockpit shows the outside, so that head position is reported, not cast from
        h = tree.ray_cast(eye, off.normalized(), off.length) if off.length > 0 else (None,)
        if h[0] is not None:
            through.append({"head": off_u, "face": info[h[2]]})
            continue
        for pan in range(-165, 166, 5):
            for tilt in range(-65, 66, 5):
                d = direction(pan, tilt)
                rays += 1
                o_, passed = o0, []
                while True:
                    h = tree.ray_cast(o_, d, 40.0)
                    if h[0] is None:
                        break
                    name = owner[h[2]]
                    if name in GLASS:
                        passed = None
                        break
                    if h[1].dot(d) < 0:  # a front face: the view stops here
                        passed = None
                        break
                    passed.append((name, h[2], tuple(round(c, 2) for c in h[0])))
                    o_ = h[0] + d * 0.0005
                if passed is None:
                    continue
                if over_screen(o0, d):  # out over the screen's top, under the coaming: the forward view, by design
                    over += 1
                    continue
                escaped += 1
                escaped_eye += off.length == 0
                t_trim = first_front(ref["untrimmed_shell"], o0, d)
                t_old = first_front(ref["blockout_flightdeck"], o0, d)
                h = hull.ray_cast(o0, d, 40.0)
                exit_ = tuple(round(c, 2) for c in h[0]) if h[0] is not None else None
                ref_face = None
                if t_trim is not None:
                    cause = "trimmed"
                    at = tuple(round(c, 2) for c in o0 + d * t_trim[0])
                    ref_face = ref_info["untrimmed_shell"][t_trim[1]]
                elif t_old is not None:
                    cause = "lost_in_rebuild"
                    at = tuple(round(c, 2) for c in o0 + d * t_old[0])
                    ref_face = ref_info["blockout_flightdeck"][t_old[1]]
                elif passed:
                    cause = "seen_from_behind"
                    at = passed[0][2]
                else:
                    cause = "never_built"
                    at = exit_
                causes[cause] += 1
                if passed:
                    culled_by[passed[0][0]] += 1
                    back_faces[passed[0][1]] += 1
                cell = tuple(round(c / 0.05) * 0.05 for c in at) if at else None
                holes[(cause, tuple(round(c, 2) for c in cell) if cell else None)] += 1
                examples.append({"head": off_u, "pan": pan, "tilt": tilt, "cause": cause, "at": at, "hull_exit": exit_,
                                 "ref_face": ref_face, "behind": [info[p[1]] for p in passed[:3]]})
    top = sorted(holes.items(), key=lambda kv: -kv[1])[:80]
    res["seats"][seat] = {"eye_blender": tuple(round(c, 4) for c in eye), "rays": rays, "escaped": escaped, "escaped_eye": escaped_eye,
                          "over_screen": over,
                          "causes": dict(causes), "first_culled_object": dict(culled_by), "head_through_structure": through,
                          "back_faces": [{"face": info[i], "rays": n} for i, n in back_faces.most_common(60)],
                          "places": [{"cause": k[0], "cell_5cm": k[1], "rays": n} for k, n in top],
                          "examples": examples}
    print("VIS", seat, "rays", rays, "escaped from the eye", escaped_eye, "from the head's range (reported only)", escaped, dict(causes), "out over the screen", over, "head positions through structure",
          [(t["head"], t["face"][0], t["face"][3]) for t in through])
# The camera band: it shows the world through the hidden nose, so from each seat's eye every ray through it must
# leave the airframe past nothing opaque (glass is fine). 0.1.3 lets 356 of 369 of the pilot's through and 135 of the
# commander's (whose lower eye sees the coaming's underside past the band's top, 0.1.3's own); builds 4 and 5 let
# none (a wall behind it). Rays on a 41 x 9 grid over the sheet.
band = bpy.data.objects.get("band")
bands = {}
if band is not None:
    bt = BVHTree.FromPolygons([band.matrix_world @ v.co for v in band.data.vertices], [tuple(p.vertices) for p in band.data.polygons])
    bv = [band.matrix_world @ v.co for v in band.data.vertices]
    bz0, bz1 = min(v.z for v in bv), max(v.z for v in bv)
    bxs = sorted(bv, key=lambda v: v.x)
    for seat, eye in eyes.items():
        clear = n = 0
        blockers = Counter()
        for i in range(41):
            # points across the sheet: march along its lower edge's x span, find the sheet by casting from the eye
            x = bxs[0].x + (bxs[-1].x - bxs[0].x) * (i + 0.5) / 41
            for j in range(9):
                z = bz0 + (bz1 - bz0) * (j + 0.5) / 9
                guess = Vector((x, sum(v.y for v in bv) / len(bv), z))
                d = (guess - eye).normalized()
                hb = bt.ray_cast(eye, d, 5.0)
                if hb[0] is None:
                    continue
                n += 1
                o_, ok = hb[0] + d * 0.002, True
                while True:
                    h = tree.ray_cast(o_, d, 30.0)
                    if h[0] is None:
                        break
                    if owner[h[2]] in GLASS or h[1].dot(d) >= 0:
                        o_ = h[0] + d * 0.0005
                        continue
                    ok = False
                    blockers[(owner[h[2]], info[h[2]][2], round(h[0].y + 22.475, 2), round(h[0].z, 2))] += 1
                    break
                clear += ok
        bands[seat] = {"rays": n, "clear": clear, "share": round(clear / max(n, 1), 3), "blocked_by": [[list(k), c] for k, c in blockers.most_common(8)]}
        print("BAND", seat, "clear %d of %d" % (clear, n), blockers.most_common(4))
res["band"] = bands
# seeing into parts from each seat's eye: faces culled from behind with a part beyond them, under the panel and at the
# forward corners (flightdeck_seeinto.py).
sys.path.insert(0, str(Path(__file__).parent))
import flightdeck_seeinto as seeinto  # noqa: E402
see = seeinto.seeinto(tree, owner, eyes)
res["seeinto"] = see
# the screen is a camera feed: from the pilot's eye nothing of the aircraft shows through it (flightdeck_cut.py)
import flightdeck_cut as cut  # noqa: E402
ts_rays, ts_met, ts_what = cut.through_screen(tree, [(i[0], i[1]) for i in info])
res["through_screen"] = {"rays": ts_rays, "met": ts_met, "what": [[list(k), n] for k, n in ts_what.most_common(12)]}
print("THROUGH SCREEN", ts_rays, "rays", ts_met, "met a cockpit mesh", ts_what.most_common(5))
hb_rays, hb_met, _ = cut.through_screen(tree, [(i[0], i[1]) for i in info], step=2.0, which="tracker")  # reported only
res["through_screen"]["head_box"] = {"rays": hb_rays, "met": hb_met}
print("THROUGH SCREEN head box (reported only)", hb_rays, "rays", hb_met, "met a cockpit mesh")
tp_rays, tp_met, tp_side, tp_seen = cut.through_panes(tree, [(i[0], i[1]) for i in info])
res["through_panes"] = {"rays": tp_rays, "met": tp_met, "by_side": tp_side, "openings": tp_seen}
print("PANE OPENINGS", tp_seen, "pinned", PANE_OPENINGS)
print("THROUGH PANES", tp_rays, "rays", tp_met, "met an opaque cockpit face", tp_side)
import flightdeck_window as win  # noqa: E402
# the side windows: no glass shows just outside a frame, sighted from the camera where the game puts it for the look
# (it slides sideways past 33 deg); over the head's range from fixed positions, reported only
refs = [(i[0], i[1]) for i in info]
gi_ = bpy.data.objects["glass_int"]
glass_tree = BVHTree.FromPolygons([gi_.matrix_world @ v.co for v in gi_.data.vertices], [tuple(p.vertices) for p in gi_.data.polygons])
ow_rays, ow_bad, ow_by, ow_ex, ow_screen = win.outline_gaps(tree, refs, EYE_P, glass_tree)
sw_n, sw_tot, sw_worst, sw_at, sw_screen = win.sway_gaps(tree, refs, EYE_P, glass_tree)
hb_bad = [win.outline_gaps(tree, refs, EYE_P + off, glass_tree, shift=False)[1] for _, off in offsets()]
# the slide belongs to the look, not to each sightline: a point near the edge of a wide look is seen from the camera
# slid by the look's angle (0.14 m at 80 deg, up to 0.2 m), so the frame is checked from fixed slides to each side too.
# Gated to 0.17 (a 90 deg look): at the game's 60.09 deg vertical field of view (91.6 across) a look that slides 0.2
# (100 deg and more) no longer holds the windows' forward members (about 40 deg off the nose); 0.20 is reported
SLIDES, SLIDES_GATED = (0.10, 0.14, 0.17, 0.20), 0.17
sl_bad = {"%+.2f" % (sg * s_): win.outline_gaps(tree, refs, EYE_P + Vector((sg * s_, 0.0, 0.0)), glass_tree, shift=False)[1]
          for s_ in SLIDES for sg in (1, -1)}
print("SLIDES pilot glass just outside the window frames from the camera slid by a look (x, gaps):", sl_bad)
res["outside_frame"] = {"sights": ow_rays, "gaps": ow_bad, "by_side": ow_by, "examples": ow_ex,
                        "sway": {"positions": sw_n, "gaps": sw_tot, "worst": sw_worst, "at": sw_at},
                        "past_the_screen_edge": {"eye": len(ow_screen), "sway": sw_screen},
                        "head_box": {"positions": len(hb_bad), "gaps": sum(hb_bad), "worst": max(hb_bad)},
                        "slides": sl_bad}
print("OUTSIDE FRAME", ow_rays, "sights just outside the frames from the eye as the look moves it,", ow_bad,
      "on glass", ow_by, ow_ex, "| over the sway:", sw_tot, "at", sw_n, "positions, worst", sw_worst, sw_at,
      "| past the screen's edge instead (reported only):", len(ow_screen), sw_screen,
      "| head box (reported only):", sum(hb_bad), "over", len(hb_bad), "positions, worst",
      max(hb_bad))
# every display's bezel in plain sight from both seats (flightdeck_bezels.py).
import flightdeck_bezels as bezels  # noqa: E402
bez = bezels.bezels(tree, [(i[0], i[1]) for i in info], eyes, bpy.data.objects["tacScreen"])
res["bezels"] = bez
# the screen foot's skirt (on the screen's cylinder, 5 mm behind the sheet) seen from the pilot's eye under the glare
# plate's height, which happens only through the wedge between two modules set at different angles (Stores and Engine
# 1; filling the wedge would hide Engine 1's left bezel): reported, and a sight of the trim sheet's light finish there
# (the struct strip's rows) fails, as in game the sun lights it to pale triangles (Workbench renders, with no sun and
# no sky reflection, drew it dark)
STRUCT_V = (1 - 512 / 2048, 1 - 448 / 2048)
import flightdeck_layout as bo_  # noqa: E402
import flightdeck_screen as band_shape  # noqa: E402
SKIRT_BELOW = 4.76  # the glare plate stands at 4.765
radius = bo_.BAND_RADIUS or band_shape.R0
half = band_shape.ARC0 / 2 * (band_shape.K if bo_.BAND_RADIUS else 1.0)
skirt_rays, skirt_seen = 0, []
for k in range(int(2 * half / 0.005) + 1):
    s_ = -half + 0.005 * k
    for j in range(40):
        z = 4.56 + 0.005 * j
        if z >= SKIRT_BELOW:
            break
        p = band_shape.new_point(s_, 0.005, z, radius)
        d = p - EYE_P
        L = d.length
        d.normalize()
        h = first_front(tree, EYE_P, d, L + 0.01)
        skirt_rays += 1
        if h is not None and abs(h[0] - L) < 0.004 and (info[h[1]][2] or "").endswith("cockpit_trim"):
            v = info[h[1]][6]
            skirt_seen.append((tuple(round(c, 3) for c in p), v is not None and STRUCT_V[0] <= v <= STRUCT_V[1]))
skirt_by_x = dict(sorted(Counter(round(p[0], 1) for p, _ in skirt_seen).items()))
skirt_light = sum(1 for _, lt in skirt_seen if lt)
res["skirt_seen_below_plate"] = {"rays": skirt_rays, "seen": len(skirt_seen), "light": skirt_light, "by_x": skirt_by_x,
                                 "points": [p for p, _ in skirt_seen[:40]]}
print("SKIRT pilot %d of %d points on the screen foot's skirt under the glare plate seen (%d in the light finish), by x:"
      % (len(skirt_seen), skirt_rays, skirt_light), skirt_by_x)
# the verdict, on the pilot's numbers alone (only the player's view counts; the commander's stay in the report): no
# escapes, the band clear, nothing of the aircraft through the screen, every bezel in sight, no more than a few rays
# into a part under the panel or at a corner (fail the build step otherwise)
lim_esc = {"pilot": 0, "commander": 1}
lim_band = {"pilot": 0.97, "commander": 0.97}  # a clean screen: about 98% clear, the rest grazing its frame
lim_into = 10
for a in argv:
    if a.startswith("--max-into="):
        lim_into = int(a.split("=")[1])
    if a.startswith("--max-escaped="):
        lim_esc.update(zip(("pilot", "commander"), (int(v) for v in a.split("=")[1].split(","))))
    if a.startswith("--min-band="):
        lim_band.update(zip(("pilot", "commander"), (float(v) for v in a.split("=")[1].split(","))))
GATED = ("pilot",)
# on the pilot's normal eye (the owner: moved heads are ignored); the head's range is reported only
fails = [("%s escaped %d > %d" % (s, res["seats"][s]["escaped_eye"], lim_esc[s])) for s in GATED if res["seats"][s]["escaped_eye"] > lim_esc[s]]
fails += [("%s band clear %.3f < %.2f" % (s, bands[s]["share"], lim_band[s])) for s in GATED if s in bands and bands[s]["share"] < lim_band[s]]
if ts_met:
    fails.append("pilot through the screen %d of %d rays meet a cockpit mesh" % (ts_met, ts_rays))
for k, n in sorted(PANE_OPENINGS.items()):
    if abs(tp_seen.get(k, 0) - n) > max(3, PANE_TOLERANCE * n):
        fails.append("pilot's %s pane opening %d rays, pinned %d: an opening grew or shrank" % (k, tp_seen.get(k, 0), n))
sl_gated = {k: v for k, v in sl_bad.items() if abs(float(k)) <= SLIDES_GATED + 1e-6}
if sum(sl_gated.values()):
    fails.append("pilot sees the glass just outside the window frames from a look's slid camera: %s" % sl_gated)
if ow_bad or sw_tot:
    fails.append("pilot sees the glass just outside the window frames: %d points from the eye, %d over the camera's sway" % (ow_bad, sw_tot))
if tp_met:
    fails.append("pilot through the panes %d of %d rays meet an opaque cockpit face %s" % (tp_met, tp_rays, tp_side))
for s in GATED:
    if bez[s]["blocked"] > 0:
        fails.append("%s display bezel sightlines blocked %d of %d" % (s, bez[s]["blocked"], bez[s]["sightlines"]))
for s, v in see.items():
    if s not in GATED:
        continue
    n_into = sum(n for k, n in v["counts"].items() if k in ("into under", "into corner"))
    if n_into > lim_into:
        fails.append("%s sees into parts under the panel or at a corner %d > %d" % (s, n_into, lim_into))
# the pilot's rudder pedals and his legs (docs/DECISIONS.md: nothing hangs below the control strips into the footwell).
# Pedals: points on each pedal's face (flightdeck_build.py pilot_footwell: 9 x 22 cm plates at x 0.55 -+ 0.11, station
# 5.42, z 3.96, turned 20 deg back), each seen when nothing stands between it and the camera: the share seen from the
# eye, and the least share over the look's slides and the sway. Legs: for each leg a capsule from the seat pan's front
# edge (station 6.25, z 4.15) up to a seated knee (station 5.95, z 4.25), 16 cm round, then down to the sole 10 cm off
# the pedal (its arm rises beside it to the cross shaft), 10 cm round; a cockpit face inside one (the stock seat, which the hip rests on, aside) is a fault.
PEDAL_SEEN_MIN, LEG_RADII = 0.60, (0.16, 0.10)
pedal_n = Vector((0.0, math.cos(math.radians(20)), math.sin(math.radians(20))))
pedal_y = pedal_n.cross(Vector((1.0, 0.0, 0.0)))
pedal_pts = [Vector((0.55 + dx, 5.42 - 22.475, 3.96)) + Vector((u, 0, 0)) + pedal_y * v + pedal_n * 0.006
             for dx in (-0.11, 0.11) for u in (-0.035, 0.0, 0.035) for v in (-0.09, -0.045, 0.0, 0.045, 0.09)]


def pedal_share(cam):
    seen = 0
    for q in pedal_pts:
        d = q - cam
        seen += tree.ray_cast(cam, d.normalized(), d.length - 0.004)[0] is None
    return seen / len(pedal_pts)


ped_eye = pedal_share(EYE_P)
ped_least = min(pedal_share(EYE_P + Vector((s_ * d_, 0.0, 0.0))) for d_ in (0.10, 0.14, 0.17) for s_ in (1, -1))
leg_faults = defaultdict(int)
for dx in (-0.11, 0.11):
    x_ = 0.55 + dx
    hip, knee = Vector((x_, 6.25 - 22.475, 4.15)), Vector((x_, 5.95 - 22.475, 4.25))
    foot = Vector((x_, 5.42 - 22.475, 3.96)) + pedal_n * 0.10  # the sole 10 cm off the pedal: its arm rises beside it
    for a_, b_, r_ in ((hip, knee, LEG_RADII[0]), (knee, foot, LEG_RADII[1])):
        for k in range(21):
            c_ = a_.lerp(b_, k / 20)
            hit = tree.find_nearest(c_, r_)
            pedal_c = Vector((x_, 5.42 - 22.475, 3.96))
            if hit[0] is not None and not info[hit[2]][0].startswith("stock_seat") and (hit[0] - pedal_c).length > 0.14:
                leg_faults[(info[hit[2]][0], info[hit[2]][2], tuple(round(v, 2) for v in hit[0]))] += 1
res["pedals"] = {"seen_from_eye": round(ped_eye, 3), "least_over_slides": round(ped_least, 3),
                 "leg_faults": len(leg_faults), "leg_hits": [list(k) for k in list(leg_faults)[:12]]}
print("PEDALS seen from the eye %.0f%% of their faces, at least %.0f%% from a look's slid camera; legs: %d faces inside"
      " the clearance" % (100 * ped_eye, 100 * ped_least, len(leg_faults)), list(leg_faults)[:6])
if ped_eye < PEDAL_SEEN_MIN:
    fails.append("the pedals' faces %.0f%% in sight from the eye, under %.0f%%" % (100 * ped_eye, 100 * PEDAL_SEEN_MIN))
if leg_faults:
    fails.append("%d cockpit faces inside the legs' clearance to the pedals" % len(leg_faults))
# the display modules' tops: rays from each seat's eye, a look's slid cameras and a raised head through every point
# (3 mm apart) of the band where the modules stand (station 5.775, inboard of 1 m, z 4.45 to 4.80); one that meets
# window glass or leaves the airframe saw out between or over the modules (the commander's flight display's outboard
# end showed the side window to the pilot's wide look, past every other check here). Fails when a camera's count rises
# over TOPS_PINNED (slides to SLIDES_GATED; the 0.20 m slides are reported, as for the window frames): single rays at
# the outboard ends where the plate behind the displays meets the screen's foot (z 4.795 to 4.798), and low beside the
# commander's outboard module from the pilot's camera slid 0.17 m, all there since before this check; lowering one is a
# decision, made by re-pinning.
TOPS_Y, TOPS_X, TOPS_Z, TOPS_STEP = 5.775 - 22.475, 1.0, (4.45, 4.80), 0.003
TOPS_PINNED = {"pilot eye": 1, "pilot slid +0.17": 3, "pilot slid -0.17": 1,
               "commander slid -0.10": 1, "commander slid +0.14": 1, "commander raised 0.075": 2}
tops_pts = [Vector((-TOPS_X + TOPS_STEP * i, TOPS_Y, TOPS_Z[0] + TOPS_STEP * j))
            for i in range(int(2 * TOPS_X / TOPS_STEP) + 1) for j in range(int((TOPS_Z[1] - TOPS_Z[0]) / TOPS_STEP) + 1)]
tops = {}
for seat, e_ in eyes.items():
    cams = [("eye", e_)] + [("slid %+.2f" % (sg * s_), e_ + Vector((sg * s_, 0.0, 0.0))) for s_ in SLIDES for sg in (1, -1)]
    cams += [("raised %.3f" % z_, e_ + Vector((0.0, 0.0, z_))) for z_ in (0.05, SWAY)]
    for name, c_ in cams:
        out_ = []
        for q in tops_pts:
            d = (q - c_).normalized()
            h = first_front(tree, c_, d)
            if (h is None and not over_screen(c_, d)) or (h is not None and info[h[1]][0] == "glass_int"):
                out_.append(tuple(round(v, 3) for v in q))
        tops["%s %s" % (seat, name)] = out_
tops_bad = {k: len(v) for k, v in tops.items() if v}
res["module_tops"] = {"rays_per_camera": len(tops_pts), "out": tops_bad,
                      "points": {k: v[:12] for k, v in tops.items() if v}}
print("TOPS rays through the display modules' tops that meet window glass or leave, per camera (%d rays each):"
      % len(tops_pts), tops_bad or "none", {k: v[:3] for k, v in tops.items() if v})
tops_over = {k: n for k, n in tops_bad.items() if n > TOPS_PINNED.get(k, 0)
             and not ("slid" in k and abs(float(k.split()[-1])) > SLIDES_GATED + 1e-6)}
if tops_over:
    fails.append("rays between or over the display modules meet window glass or the outside: %s (pinned %s)"
                 % (tops_over, {k: TOPS_PINNED.get(k, 0) for k in tops_over}))
if band is None:
    fails.append("no band object")
if skirt_light:
    fails.append("pilot sees the skirt's light finish under the glare plate at %d points" % skirt_light)
res["verdict"] = "FAIL: " + "; ".join(fails) if fails else "PASS"
Path(out_json).write_text(json.dumps(res, indent=1))
print("VIS VERDICT", res["verdict"])
if fails:
    sys.exit(1)
