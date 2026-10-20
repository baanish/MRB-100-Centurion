"""Part group 3: the wing.

Parts: wing_root_L/R (the fixed inner wing: flap and aileron cut-outs with their cove lips, the fixed halves of three
flap-track fairings, a landing light, the fuel jettison pipe, the end cap the stages slide through), wing_tele1_L/R and
wing_tele2_L/R (the telescoping stages; the raked, upswept tip with its glass nav blister, strobe, tail light, formation
strip and static dischargers is part of wing_tele2, as in the blockout), and the wing's control
surfaces' _visible meshes: flap_*, aileron_*, spoiler_* (each flap carries its fairings' moving halves). Right-hand
parts come from the same code with side -1, face for face, and reuse the left twin's UV islands (MIRROR_PARTS), except
the TEXT_PARTS, which keep islands of their own so their stencil text reads the right way round.

Sections and stations are the blockout's (build_centurion: build_wing, tip_rings, build_surfaces) at finished
resolution. Positions are (x, chord fraction): x the semi-span in metres, the chord fraction 0 at the leading edge and
1 at the trailing edge. The stages are built retracted and
moved by their current extension, so meshes swapped into an extended scene sit where the blockout's did.

Nesting (SPEC "Wing"): retracted, every stage vertex stays inside its parent (build_centurion.outside_count), so the
stages carry nothing proud of their skin inboard of the tip. The parent's wiper sits outside the child's section,
with its back buried in the closing rib and its front under the tip neck clearance.

Stencils: a right-hand part in MIRROR_PARTS shows its left twin's texels mirrored, so text there would read backwards.
Real text sits only on the TEXT_PARTS (flap 1, behind the walkway); every other servicing note is a plain ruled
placard, which reads either way. The placard sites (PLACARDS, the stages') are the rows a shared atlas must keep
unique to carry real text."""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import surface as sf
from . import airfoil as af
from . import render

GROUP = "wing"
PARTS = ("wing_root_L", "wing_root_R", "wing_tele1_L", "wing_tele1_R", "wing_tele2_L", "wing_tele2_R",
         "flap_L1_visible", "flap_L2_visible", "flap_R1_visible", "flap_R2_visible",
         "aileron_L_visible", "aileron_R_visible", "spoiler_L_visible", "spoiler_R_visible")
BUDGET_TRIS = 21000  # damage stage 2: reclaim and leaner damage structure (was 20000)
# Right-hand parts with islands of their own, for the NO STEP text outside the walkway (about 20 m2 more unique skin).
TEXT_PARTS = ("flap_R1_visible",)
MIRROR_PARTS = {n: n.replace("_R", "_L", 1) for n in PARTS if "_R" in n and n not in TEXT_PARTS}
GREEN = "light_green"
STOCK_SLOTS = (GREEN,)
# Close-ups (m4/render.py's view form); the first four make the contact sheet. TIP_VIEW looks at the retracted tip;
# build() sets VIEWS["wing_tip"] from it, moved with stage 2 when the scene is open extended (VIEWS is read after
# build). The joint view looks at the root's end, which never moves: the cuff retracted, stage 1 coming out extended.
TIP_VIEW = (50, (27.0, 16.5, 9.5), (20.6, 23.0, 5.6))
VIEWS = {
    "wing34": (35, (30.0, 2.0, 16.0), (11.0, 18.0, 5.4)),
    "wing_aft": (38, (18.0, 40.0, 12.0), (10.0, 21.0, 5.5)),
    "wing_low": (28, (21.0, 31.0, 1.2), (9.0, 20.5, 5.6)),  # under the root from behind: manholes, fairings, coves
    "wing_tip": TIP_VIEW,
    "wing_top": (("ortho", 24.0, render.TOP), (11.0, 20.0, 60.0), None),
    "wing_joint": (60, (23.5, 16.0, 8.8), (19.8, 22.6, 5.5)),
    "wing_tracks": (35, (14.0, 34.0, 3.2), (8.0, 23.5, 5.2)),
    "wing_canoe": (32, (18.0, 25.5, 5.0), (7.0, 23.6, 5.6)),  # the fairing tails at the trailing edge, from outboard
}

# Paint classes past the shared ones (m4/surface.py, 1 to 5): one per section family and end cap, so the layout knows
# which surface a texel lies on. HULL and RADOME stay unused here: the entry script gives those fuselage normals.
WING, STAGE1, STAGE2, TIP, FLAP, AILERON, SPOILER, FAIRING = range(11, 19)
COVE = 19  # a cut-out's cove walls and lip underside: skin-toned structure, seen round a deflected surface
CAP_ROOT, CAP_STAGE1, CAP_STAGE2, CAP_CUFF = range(20, 24)
WIPER = 24
REFLECTOR = 25
ON_STAGE1, ON_STAGE2 = (STAGE1, CAP_STAGE1, WIPER), (STAGE2, CAP_STAGE2, TIP, CAP_CUFF)

ROOT_N, STAGE_N, TIP_N = 22, 22, 16  # airfoil points per surface, cosine spaced (the blockout's 10)
# Root rings, plus bl.WING_UV_CUTS (the spanwise UV cuts at the pylon and the 13 m kink, so the 20 m skin packs),
# the cut-out edges, the aileron's middle ring and the end bevel. Flap sections between planform breaks are affine,
# so their middle rings add no curvature; the aileron's swept nose needs its extra samples.
ROOT_STATIONS = (0.0, 13.0, 16.5)
BEVEL = (0.006, 0.040)  # the roll stays inside the original end perimeter
# Most spacing between a stage's spanwise rings: the in-game wing flex (src/Centurion/WingFlex.cs) bends the render
# meshes vertex by vertex, so a stage needs rings along its run to bend as a curve, nested in its parent (a straight
# 11 m run would cut through the parent's bent skin; at 1.5 m the chord sags about 5 mm at the 1 g bend).
STAGE_RING = 1.5
# Tip reach fractions, close over the blockout's rounded end (bl.TIP_ROUND: chord and thickness closing elliptically on
# a point), which the loft closes on its pole at reach 1.
TIP_F = (0.0, 0.1, 0.22, 0.35, 0.55, 0.72, 0.79, 0.85, 0.9, 0.94, 0.97, 0.99)
LIGHT_F = 0.93  # the tail light sits on the tip section here
STROBE_F = 0.8  # the strobe, on the upper skin where the rounded end is still thick enough to hold it
TIP_CAP_F = 0.66  # the dielectric tip cap carrying the lights starts at this reach fraction
NAV_LENS = (0.81, 0.15, 0.05)  # reach fraction, oval half length and height in metres
LIGHT_SEG = 12  # segments round the strobe and tail light
# Formation strip on the tip's upper skin: inboard end (reach fraction), chord fraction of its front edge, length and
# width in metres (one size on every group).
FORMATION = (0.2, 0.25, 0.6, 0.08)
LANDING_LIGHT = (3.975, 4.425)  # bay span in true metres
# Cove lips: aft_ring's nose for the flaps (build_flap; the aileron's is aileron_ring's), and each kind's deflection
# range in degrees, trailing edge up positive (CenturionAuthor's Surfaces: flaps 30 down, ailerons 25 either way). The
# lip on the fixed skin reaches over the nose until it would come within LIP_CLEAR of it anywhere in that range, or
# thins to LIP_MIN.
NOSE_K = {"flap": 0.6}
DEFLECT = {"flap": (-30.0, 0.0), "aileron": (-25.0, 25.0)}
LIP_CLEAR, LIP_MIN = 0.01, 0.008
# The aileron hinges on the camber line 2 cm aft of its cut-out (the blockout's hinge empty), and a nose ending on the
# hinge swings into any lip over its 25 deg either way, which left a 17 cm trench across the wing from above. Its nose
# is instead an arc about the hinge as deep as its skin, out to AIL_ARC deg from the vertical either side, then falling
# to AIL_NOTCH by AIL_DROP deg, clear of stage 1's trailing edge 8 cm ahead of the hinge; the root's cove follows the
# nose's swept envelope LIP_CLEAR outside it, and the root's skin runs aft as a lip until it is LIP_MIN thick.
AIL_ARC, AIL_DROP, AIL_NOTCH, AIL_N = 35.0, 60.0, 0.035, 5
STAGE_CLEAR, STAGE_ANGLE = 0.012, 8  # the aileron's cove off stage 1's section: metres, and degrees round it
# The lower lip is a flexible seal strip, thinner and closer to the aileron's swept nose than the upper lip, so from
# below the cove reads as a seal line rather than a slot (painted cove grey over SEAL_STRIP). Clearance and least
# thickness in metres; at 6 mm clearance the lofts (rings 3.4 m apart) met from 23 deg trailing edge down.
SEAL_CLEAR, SEAL_MIN, SEAL_STRIP = 0.008, 0.003, 0.025
AIL_SWING = max(-DEFLECT["aileron"][0], DEFLECT["aileron"][1]) + 1.0  # degrees the nose swings either way, 1 spare
# Flap-track fairings (semi-span, flap): off the nacelle (x 5.12 to 9.38), whose pylon's aft fairing carries flap 1's
# outer end and flap 2's inner end, and inboard of the stage run (x 11.3), where the nesting check needs plain skin.
CANOES = ((4.3, 1), (9.8, 2), (11.05, 2))
# Metres along the chord from the flap hinge: the nose, the deepest section (where the halves split), the tail point
# past the trailing edge; and the gap between the halves.
CANOE_NOSE, CANOE_MID, CANOE_TAIL, CANOE_GAP = -2.4, -0.6, 0.55, 0.008
# The deepest section: depth below the lower skin, half width, top buried above the skin. About 0.8 as wide as deep:
# at half as wide, flat sided, the fairings read as fins and blades from the side.
CANOE_DEPTH, CANOE_HALF_W, CANOE_TOP = 0.5, 0.2, 0.04
CANOE_DROP = 0.06  # the tail point's depth below the trailing edge's lower corner, on the fairing's centre line
CANOE_M = 32  # points round a fairing section
# The split runs on a cylinder about the hinge line; its bottom lands this far ahead of straight below the hinge, so
# the fixed half ends in a steep cut. Landing under the hinge, the cut grazed the bottom line and the fixed half ended
# in a long sliver, a pale blade from the side with its flap hidden.
CANOE_SPLIT_ANGLE = 35.0
JETTISON = 12.6  # fuel jettison pipe out of the fixed trailing edge between flap 2 and the aileron
DISCHARGERS = {"aileron": (14.6, 16.4, 18.2, 19.45), "tip": (0.3, 0.62, 0.9)}


def canoe_section(off, te):
    """A flap-track fairing's section at off metres aft of the flap hinge, on a wing whose trailing edge is te aft of
    it: (half width, top, bottom, widest), heights over the lower skin (past the trailing edge, over the chord line
    through its lower corner), widest the share of the height from the top down to the widest line. Ahead of the
    deepest section depth and width round off onto the nose, a blunt bow out of the skin (a nose leaving the skin
    tangent read as a sliver from the side); behind it the section closes on the tail point much as an ellipse
    closes on its end, a small rounded point with no inflection on the way (a slender tail after a steep rise read as
    an upturned claw). The top stays buried in the skin until the trailing edge, then closes on the point."""
    if off <= CANOE_MID:
        t = math.sin(0.5 * math.pi * (off - CANOE_NOSE) / (CANOE_MID - CANOE_NOSE))
        return CANOE_HALF_W * t ** 0.5, CANOE_TOP, -CANOE_DEPTH * t ** 0.9, 0.35
    s = (off - CANOE_MID) / (te + CANOE_TAIL - CANOE_MID)
    zc = (CANOE_TOP - CANOE_DEPTH) / 2 * (1 - s ** 1.5) - CANOE_DROP * s ** 1.5
    hh = (CANOE_TOP + CANOE_DEPTH) / 2 * (1 - s ** 1.6) ** 0.6
    past = min(1.0, max(0.0, (off - te) / CANOE_TAIL))
    return CANOE_HALF_W * (1 - s ** 2.2) ** 0.6, zc + hh, zc - hh, 0.35 + 0.15 * past * past * (3 - 2 * past)


def canoe_ring(centre, across, up, half_w, top, bottom, widest):
    """A fairing section, point 0 on top: a full superellipse above the widest line, so the sides rise near upright
    into the skin, and a rounder one below it."""
    zw = top - widest * (top - bottom)
    pts = []
    for k in range(CANOE_M):
        a = 2 * math.pi * k / CANOE_M
        s, c = math.sin(a), math.cos(a)
        e = 2 / 3.0 if c > 0 else 2 / 2.2
        h = (top - zw) if c > 0 else (zw - bottom)
        pts.append(centre + across * (half_w * math.copysign(abs(s) ** e, s))
                   + up * (zw + h * math.copysign(abs(c) ** e, c)))
    return pts


# ---------- checks ----------
def check(bl, objs):
    """build_centurion's checks that the wing sets, rerun on the detailed meshes in the whole scene: the stages nested
    retracted, the retracted tip step, the span and hangar door, the tips behind the roots (15 deg aft sweep), the
    tail strike, no overlap between unjointed parts at extension 0, 0.5 and 1, and the flaps and ailerons deflected
    clear of the engines (surface_clashes). Leaves the stages and surfaces as found."""
    scene = {o.name: o for o in bpy.data.collections["Centurion"].objects}
    stages = {n: o for n, o in scene.items() if "slide_axis" in o}
    saved = {n: o.location.copy() for n, o in stages.items()}
    bl.set_extension(stages, 0.0)
    allv = [v for o in scene.values() if o.type == "MESH" for v in bl.world_mesh(o)[0]]
    span = max(v.x for v in allv) - min(v.x for v in allv)
    height = max(v.z for v in allv)
    nested = {f"{c}{s}_outside_{p}{s}": bl.outside_count(scene[c + s], bl.fixed_wing(scene, s) if p == "wing_root" else scene[p + s])
              for s in ("_L", "_R") for c, p in (("wing_tele1", "wing_root"), ("wing_tele2", "wing_tele1"))}
    res = {
        "stages_nested_retracted": {"value": nested, "pass": not any(nested.values())},
        "hangar_door_fit": {"value": f"{span:.2f} x {height:.2f}", "limit": f"{bl.HANGAR_DOOR_W} x {bl.HANGAR_DOOR_H}",
                            "pass": span < bl.HANGAR_DOOR_W and height < bl.HANGAR_DOOR_H},
    }
    for side, s in ((1, "_L"), (-1, "_R")):
        step = bl.tip_step(scene, side)
        res[f"retracted_tip_step{s}"] = {"value": step, "pass": step["pass"]}
        tele = scene["wing_tele2" + s]
        root_y, tip_y = scene["wing_root" + s].matrix_world.translation.y, (tele.matrix_world @ Vector(tele["tip_qc"])).y
        res[f"wingtip{s}_behind_root"] = {"value": round(tip_y - root_y, 3), "pass": tip_y > root_y}
    strike = bl.tail_strike(scene)
    res[bl.TAIL_STRIKE_KEY] = {"value": strike["value"], "limit": strike.get("limit"), "pass": strike["pass"]}
    by_ext = {}
    for e in (0.0, 0.5, 1.0):
        bl.set_extension(stages, e)
        by_ext[f"{e:.1f}"] = bl.overlaps(scene)
    res["no_overlap_unjointed_parts"] = {"value": by_ext, "pass": not any(by_ext.values())}
    for n, o in stages.items():
        o.location = saved[n]
    bpy.context.view_layer.update()
    clashes = surface_clashes(bl, scene)
    res["surfaces_deflected_clear"] = {"value": clashes, "pass": not clashes}
    return res


def surface_clashes(bl, scene):
    """Each flap and aileron swung through its range (DEFLECT; local X is the hinge, minus is trailing edge down)
    against the engine under it: the pylon (with the engines group's aft canoe between flaps 1 and 2, when built),
    nacelle and nozzle as the scene has them. Returns {surface@deg~part: intersecting face pairs}."""
    found = {}
    for num, side, _, _ in bl.NACELLES:
        sfx = "L" if side > 0 else "R"
        under = [scene[n] for n in (f"pylon_{num}", f"nacelle_{num}", f"nozzle_{num}") if n in scene]
        for pattern, _, _, kind in bl.SURFACES:
            if kind not in DEFLECT:
                continue
            hinge = scene[pattern.format(s=sfx)]
            rest = hinge.matrix_basis.copy()
            lo, hi = DEFLECT[kind]
            for deg in sorted({lo, hi, (lo + hi) / 2, lo / 3, 2 * lo / 3} - {0.0}):
                hinge.matrix_basis = rest @ Matrix.Rotation(math.radians(deg), 4, "X")
                bpy.context.view_layer.update()
                for o in under:
                    n = bl.clash_faces(scene[hinge.name + "_visible"], o)
                    if n:
                        found[f"{hinge.name}@{deg:+.0f}~{o.name}"] = n
            hinge.matrix_basis = rest
    bpy.context.view_layer.update()
    return found


# ---------- section families ----------
def root_section(bl, side):
    """The fixed inner wing: (leading edge, chord, thickness, chord dir, thickness dir, camber) at semi-span x."""
    def sec(x):
        le, c, t = bl.wing_le(side, x)
        return le, c, t, bl.CDIR, bl.TDIR, bl.WING_CAMBER
    return sec


def stage_section(bl, side, chord, thick):
    """A telescoping stage at rest: a constant section on the swept quarter-chord line."""
    def sec(x):
        le = bl.qc_at(side, x * bl.XI_PER_X) - 0.25 * chord * bl.CDIR
        return le, chord, thick, bl.CDIR, bl.TDIR, bl.WING_CAMBER
    return sec


# ---------- build ----------
def build(bl, surf, slots):
    parts = {}

    def part(name):
        parts[name] = sf.Part(name, (slots[0],))
        return parts[name]

    for sfx, side in (("L", 1), ("R", -1)):
        hinges = {}
        for pattern, x0, x1, kind in bl.SURFACES:
            if kind == "flap":
                hinges[pattern.format(s=sfx)] = (flap_hinge(bl, side, x0), flap_hinge(bl, side, x1))
        build_root(bl, part(f"wing_root_{sfx}"), side, hinges, sfx, slots)
        for k in (0, 1):
            name = f"{bl.TELE[k][0]}_{sfx}"
            p = part(name)
            build_stage(bl, p, side, k, slots)
            if k == 1:
                build_tip(bl, p, side, slots)
            bmesh.ops.translate(p.bm, vec=stage_shift(bl, name, side, k), verts=p.bm.verts[:])
        for pattern, x0, x1, kind in bl.SURFACES:
            name = pattern.format(s=sfx)
            p = part(name + "_visible")
            if kind == "flap":
                build_flap(bl, p, side, x0, x1, hinges[name], [x for x, f in CANOES if name.endswith(str(f))], slots)
            elif kind == "aileron":
                build_aileron(bl, p, side, x0, x1, slots)
            else:
                build_spoiler(bl, p, side, x0, x1, slots)
    for p in parts.values():
        bmesh.ops.delete(p.bm, geom=[e for e in p.bm.edges if not e.link_faces], context="EDGES")
    lens, cam, target = TIP_VIEW
    d = tuple(stage_shift(bl, "wing_tele2_L", 1, 1))
    VIEWS["wing_tip"] = (lens, tuple(c + o for c, o in zip(cam, d)), tuple(c + o for c, o in zip(target, d)))
    return parts


def stage_shift(bl, name, side, k):
    """How far the stage sits from its retracted rest (the scene may be open extended)."""
    _, chord, length, inset = bl.TELE[k]
    rest = bl.qc_at(side, bl.XI_ROOT_TIP - inset - length)
    return bpy.data.objects[name].matrix_world.translation - rest


def stage_thickness(bl, k):
    return bl.interp(bl.THICK, bl.X_ROOT_TIP) * bl.TELE_THICK_RATIO ** (k + 1)


def flap_hinge(bl, side, x):
    """A flap hinge point, as build_centurion.build_surfaces puts the hinge empty (2 cm aft of the cut-out)."""
    le, c, t = bl.wing_le(side, x)
    return bl.camber_point(le, c, bl.CDIR, bl.TDIR, bl.WING_CAMBER, bl.FLAP_HINGE + 0.02 / c)


def nose_envelope(bl, sec, x, kind, cut):
    """The control surface behind a cut at chord fraction cut, as build_flap and build_aileron make it (aft_ring, its
    hinge on the camber line 2 cm aft of the cut): returns (hinge point, env), env(a) being the highest the surface's
    upper side reaches over its deflection range at a metres aft of the hinge (None where it never passes)."""
    le, c, th, cd, td, cam = sec(x)
    t0 = cut + 0.02 / c
    P = lambda t: bl.airfoil_point(le, c, th, cd, td, cam, t, True)
    C = lambda t: bl.camber_point(le, c, cd, td, cam, t)
    nose = min(NOSE_K[kind] * (P(t0) - C(t0)).dot(td), 0.3 * c * (1 - t0))
    tc = t0 + nose / c
    ctr = C(tc)
    hu = (P(tc) - ctr).dot(td)
    pts = [ctr - cd * (nose * math.cos(phi) ** 0.8) + td * (hu * math.sin(phi))
           for phi in (0.5 * math.pi * i / 24 for i in range(25))]
    pts += [P(tc + (1 - tc) * i / 12) for i in range(1, 13)]
    H = C(t0)
    prof = [((q - H).dot(cd), (q - H).dot(td)) for q in pts]
    lo, hi = DEFLECT[kind]
    poses = []
    for deg in np.linspace(lo, hi, 21):
        cs, sn = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        poses.append([(a * cs - h * sn, a * sn + h * cs) for a, h in prof])

    def env(a):
        best = None
        for r in poses:
            for (a0, h0), (a1, h1) in zip(r, r[1:]):
                if a0 != a1 and min(a0, a1) <= a <= max(a0, a1):
                    h = h0 + (h1 - h0) * (a - a0) / (a1 - a0)
                    best = h if best is None else max(best, h)
        return best

    return H, env


def cove_lip(bl, sec, x, kind, cut, m):
    """The upper side of a cut-out behind the skin's last surface point: m points from the skin at the cut, aft over
    the control surface's nose as a lip (a fixed shroud that leaves only a narrow slot), back under it and down the cove
    wall toward the camber line. Returns the points and how many of them lie on the upper skin (the lip's top)."""
    le, c, th, cd, td, cam = sec(x)
    H, env = nose_envelope(bl, sec, x, kind, cut)
    top = lambda d: bl.airfoil_point(le, c, th, cd, td, cam, cut + d / c, True)
    top_h = lambda d: (top(d) - H).dot(td)

    def under(d):  # the lip's underside: LIP_CLEAR over the surface's envelope, the hinge 2 cm aft of the cut
        e = env(d - 0.02)
        return None if e is None else e + LIP_CLEAR

    d_end, d = 0.0, 0.0
    while d < 0.4:
        u = under(d)
        if u is not None and top_h(d) - u < LIP_MIN:
            break
        d_end, d = d, d + 0.002
    mid = bl.camber_point(le, c, cd, td, cam, cut)
    if d_end < 0.02:  # no room for a lip: the plain cut face
        face = top(0.0)
        return [face.lerp(mid, 0.95 * j / (m - 1)) for j in range(m)], 1
    pts = [top(0.0), top(d_end / 2), top(d_end)]
    ds = (d_end, 2 * d_end / 3, d_end / 3, 0.0)
    floor, lip = top_h(d_end) - LIP_MIN, []
    for i, d in enumerate(ds):
        # each point clears the envelope over both its segments, so the straight underside between points does too
        near = [under(q) for q in np.linspace(ds[min(i + 1, 3)], ds[max(i - 1, 0)], 9)]
        near = [u for u in near if u is not None]
        floor = min(max(near) if near else floor, top_h(d) - LIP_MIN)
        lip.append(H + cd * (d - 0.02) + td * floor)
    pts += lip
    wall = m - len(pts)
    pts += [lip[-1].lerp(mid, 0.95 * (j + 1) / wall) for j in range(wall)]
    return pts, 3


def cut_ring(bl, sec, x, n, cut, cut_min, kind):
    """A section cut at chord fraction cut for a control surface: its surface points spread over [0, cut] as the
    blockout's airfoil(cut=cut_min) spreads them over [0, cut_min]; behind them the upper side's cove lip (cove_lip)
    and the lower side's cut face. Every ring along a cut-out then uses the same columns: the aileron's hinge fraction
    grows outboard (0.73 to 0.89), and a column that folds at one ring and not the next made a skewed facet in the skin
    ahead of it. Returns the ring and its columns on the outer skin (the rest are cove)."""
    le, c, t, cd, td, cam = sec(x)
    ts = [0.5 * (1 - math.cos(math.pi * k / n)) for k in range(1, n + 1)]
    stretch = cut / cut_min
    samples = [u for u in ts if u <= cut_min]
    m = max(10, n - len(samples))
    samples = [samples[int(i)] for i in np.linspace(0, len(samples) - 1, n - m)]
    surface = lambda upper: [bl.airfoil_point(le, c, t, cd, td, cam, u * stretch, upper) for u in samples]
    up, lo = surface(True), surface(False)
    upper_fold, on_skin = cove_lip(bl, sec, x, kind, cut, m)
    face, mid = bl.airfoil_point(le, c, t, cd, td, cam, cut, False), bl.camber_point(le, c, cd, td, cam, cut)
    lower_fold = [face.lerp(mid, 0.95 * j / (m - 1)) for j in range(m)]
    ring = list(reversed(up + upper_fold)) + [le.copy()] + lo + lower_fold
    cove = set(range(m - on_skin)) | set(range(2 * n - m + 2, 2 * n + 1))
    return ring, set(range(len(ring))) - cove


def hinge_frame(bl, sec, x):
    """The aileron's section at x about its hinge: (le, c, th, cd, td, cam, hinge chord fraction, hinge point)."""
    le, c, th, cd, td, cam = sec(x)
    t0 = bl.surface_hinge_fraction("aileron", x) + 0.02 / c
    return le, c, th, cd, td, cam, t0, bl.camber_point(le, c, cd, td, cam, t0)


def hinge_cd(bl, cd):
    """The chord direction scaled to measure across the aileron's hinge: the hinge is swept against the sections
    (planes of constant x), so a circle about it cuts a section as an ellipse, longer along the chord. Polar angles
    and radii about the hinge measured with this vector are the hinge's own, so a swing about it maps the nose and
    cove onto themselves; measured along the plain chord, the sweep put up to 7 mm of error into a 1 cm cove."""
    a, b = next((a, b) for _, a, b, kind in bl.SURFACES if kind == "aileron")
    sec = root_section(bl, 1)
    axis = (hinge_frame(bl, sec, b)[-1] - hinge_frame(bl, sec, a)[-1]).normalized()
    return cd * math.sqrt(1 - cd.dot(axis) ** 2)


def polar(H, ck, td, q):
    """(degrees from the thickness direction toward the leading edge, radius) of q about the hinge H, in -90 to 270;
    ck the chord direction as hinge_cd scales it."""
    a, h = (q - H).dot(ck), (q - H).dot(td)
    deg = math.degrees(math.atan2(-a, h))
    return (deg + 360 if deg < -90 else deg), math.hypot(a, h)


def from_polar(H, ck, td, deg, r):
    return H - ck / ck.length_squared * (r * math.sin(math.radians(deg))) + td * (r * math.cos(math.radians(deg)))


def stage_section_2d(bl, side, x, H, cd, td):
    """Stage 1's section at semi-span x at rest, as (chordwise, thicknesswise) metres about the hinge H (cd as
    hinge_cd scales it)."""
    _, chord, _, _ = bl.TELE[0]
    ring = af.ring(bl, stage_section(bl, side, chord, stage_thickness(bl, 0)), x, STAGE_N)
    return [((q - H).dot(cd), (q - H).dot(td)) for q in ring]


def ray_hit(poly, deg):
    """How far from the origin a ray at polar angle deg (as polar()) meets the closed polygon; inf if it misses."""
    dx, dy = -math.sin(math.radians(deg)), math.cos(math.radians(deg))
    best = math.inf
    for (px, py), (qx, qy) in zip(poly, poly[1:] + poly[:1]):
        ex, ey = qx - px, qy - py
        den = dx * ey - dy * ex
        if abs(den) > 1e-12:
            t, s = (px * ey - py * ex) / den, (px * dy - py * dx) / den
            if t > 0 and 0 <= s <= 1:
                best = min(best, t)
    return best


def aileron_ring(bl, side, x):
    """The aileron's section: the upper skin from the trailing edge to the hinge station, the nose (an arc about the
    hinge either side, falling to the notch in front of it, and held so its cove clears stage 1 by STAGE_CLEAR at any
    deflection), the lower skin back. 2 (AIL_N + 1) + 15 points."""
    le, c, th, cd, td, cam, t0, H = hinge_frame(bl, root_section(bl, side), x)
    P = lambda t, up: bl.airfoil_point(le, c, th, cd, td, cam, t, up)
    ck = hinge_cd(bl, cd)
    ts = [t0 + (1 - t0) * k / AIL_N for k in range(AIL_N + 1)]
    (a_u, rho_u), (a_l, rho_l) = polar(H, ck, td, P(t0, True)), polar(H, ck, td, P(t0, False))
    notch = min(AIL_NOTCH, 0.45 * min(rho_u, rho_l))
    stage = stage_section_2d(bl, side, x, H, ck, td)

    def r(deg):
        rho, d = (rho_u, deg) if deg <= 90 else (rho_l, 180 - deg)
        f = min(1.0, max(0.0, (d - AIL_ARC) / (AIL_DROP - AIL_ARC)))
        want = notch + (rho - notch) * 0.5 * (1 + math.cos(math.pi * f))
        reach = int(AIL_SWING) + STAGE_ANGLE  # the stage's corners widened, so the cove's chords pass clear of them
        room = min(ray_hit(stage, deg + k) for k in range(-reach, reach + 1)) - STAGE_CLEAR - LIP_CLEAR
        return max(0.01, min(want, room))

    degs = [a_u + (AIL_ARC - a_u) * k / 4 for k in range(1, 5)] + [43.0, 51.0, AIL_DROP, 90.0, 180 - AIL_DROP, 129.0,
                                                                  137.0]
    degs += [180 - AIL_ARC + (a_l - 180 + AIL_ARC) * k / 4 for k in range(4)]
    nose = [from_polar(H, ck, td, d, r(d)) for d in degs]
    return [P(t, True) for t in reversed(ts)] + nose + [P(t, False) for t in ts]


def aileron_cove(bl, side, x, m):
    """The root's side of the aileron's cove at x, m points a side: the lip's edge on the skin, then the cove round the
    aileron's envelope over its deflection (LIP_CLEAR outside it) to the camber line. Returns, for the upper and the
    lower side, (points, the skin's chord fraction at the lip's edge)."""
    le, c, th, cd, td, cam, t0, H = hinge_frame(bl, root_section(bl, side), x)
    ck = hinge_cd(bl, cd)
    ring = aileron_ring(bl, side, x)
    pts = [polar(H, ck, td, a.lerp(b, k / 8)) for a, b in zip(ring, ring[1:]) for k in range(8)]

    def cove_r(deg, clear):
        return max(r for d, r in pts if abs(d - deg) <= AIL_SWING) + clear

    sides = []
    for upper, s, clear, thick in ((True, 1, LIP_CLEAR, LIP_MIN), (False, -1, SEAL_CLEAR, SEAL_MIN)):
        start = 0.0 if upper else 180.0
        deg = start
        while True:  # the lip runs aft until the skin over the cove is thick enough
            q = from_polar(H, ck, td, deg, cove_r(deg, clear))
            t = t0 + (q - H).dot(cd) / c
            skin = bl.airfoil_point(le, c, th, cd, td, cam, t, upper)
            if s * (skin - q).dot(td) >= thick or abs(deg - start) > 60:
                break
            deg += 0.5 * s
        degs = [deg + (90 - 2 * s - deg) * k / (m - 2) for k in range(m - 1)]
        # only the lip's own edge sits at its clearance; the cove wall behind it keeps LIP_CLEAR
        cove = [from_polar(H, ck, td, d, cove_r(d, clear if k == 0 else LIP_CLEAR)) for k, d in enumerate(degs)]
        sides.append(([skin] + cove, t))
    return sides


def aileron_cut_ring(bl, side, x, n, cut_min):
    """A root section across the aileron's cut-out: as cut_ring, the skin's points spread over each side's run to the
    lip's edge (so every ring along the cut-out keeps the same columns), then the cove (aileron_cove)."""
    le, c, t, cd, td, cam = root_section(bl, side)(x)
    ts = [0.5 * (1 - math.cos(math.pi * k / n)) for k in range(1, n + 1)]
    samples = [u for u in ts if u <= cut_min]
    m = max(12, n - len(samples))
    samples = [samples[int(i)] for i in np.linspace(0, len(samples) - 1, n - m)]
    (upper_fold, t_up), (lower_fold, t_lo) = aileron_cove(bl, side, x, m)
    surface = lambda upper, end: [bl.airfoil_point(le, c, t, cd, td, cam, u * end / cut_min, upper)
                                  for u in samples]
    ring = list(reversed(surface(True, t_up) + upper_fold)) + [le.copy()] + surface(False, t_lo) + lower_fold
    cove = set(range(m - 1)) | set(range(2 * n - m + 2, 2 * n + 1))
    return ring, set(range(len(ring))) - cove


_LIP = {}


def lip_edge(bl, x, upper=True):
    """Chord fraction of the root's lip edge over the aileron's cut-out at semi-span x (an array), upper or lower: the
    spoiler and the paint end ahead of the upper one, the seal strip's paint ends on the lower one."""
    if "xs" not in _LIP:
        a, b = next((a, b) for _, a, b, kind in bl.SURFACES if kind == "aileron")
        sec = root_section(bl, 1)
        _LIP["xs"] = [float(v) for v in np.linspace(a - bl.SURF_GAP, b + bl.SURF_GAP, 9)]
        coves = [aileron_cove(bl, 1, xx, 11) for xx in _LIP["xs"]]
        _LIP["setback"] = [[sec(xx)[1] * (bl.surface_hinge_fraction("aileron", xx) - cv[k][1])
                            for xx, cv in zip(_LIP["xs"], coves)] for k in (0, 1)]
        _LIP["chord"] = [sec(xx)[1] for xx in _LIP["xs"]]
    c = np.interp(x, _LIP["xs"], _LIP["chord"])
    cut = (0.25 * c + bl.AILERON_HINGE_BEHIND_QC) / c
    return cut - np.interp(x, _LIP["xs"], _LIP["setback"][0 if upper else 1]) / c


def build_root(bl, p, side, hinges, sfx, slots):
    SKIN, STRUCT = slots[:2]
    n, M = ROOT_N, 2 * ROOT_N + 1
    sec = root_section(bl, side)
    cuts = [(x0 - 0.008, x1 + 0.008, kind) for _, x0, x1, kind in bl.SURFACES if kind != "spoiler"]
    xs = set(ROOT_STATIONS) | set(bl.WING_UV_CUTS) | {(a + b) / 2 for a, b, kind in cuts if kind == "aileron"}
    xs |= set(LANDING_LIGHT)
    for a, b, _ in cuts:
        xs |= {a - 0.04, a, b, b + 0.04}
    xs = sorted(xs) + [bl.X_ROOT_TIP - BEVEL[1], bl.X_ROOT_TIP]
    kinds = [next((k for a, b, k in cuts if a - 1e-6 <= x <= b + 1e-6), None) for x in xs]
    cut_min = {k: min(bl.surface_hinge_fraction(k, x) for x, kk in zip(xs, kinds) if kk == k) for k in set(kinds) - {None}}
    rings, skin_cols = [], []
    for x, kind in zip(xs, kinds):
        if kind == "aileron":
            ring, cols = aileron_cut_ring(bl, side, x, n, cut_min[kind])
        elif kind:
            ring, cols = cut_ring(bl, sec, x, n, bl.surface_hinge_fraction(kind, x), cut_min[kind], kind)
        else:
            ring, cols = af.ring(bl, sec, x, n), set(range(M))
        rings.append(ring)
        skin_cols.append(cols)
    rings[-1] = af.inset_ring(rings[-1], bl.CDIR, bl.TDIR, BEVEL[0])
    # Round the exposed closing rib aft of the child's section without narrowing the stage opening.
    for i, q in enumerate(rings[-1]):
        u = (q - sec(xs[-1])[0]).dot(bl.CDIR) / sec(xs[-1])[1]
        if u > 0.96:
            rings[-1][i] = q - bl.CDIR * (0.055 * ((u - 0.96) / 0.04) ** 2)

    def cove(r, k):  # a face with a corner off the outer skin is cove: the lip's underside, the cove and end walls
        if not {k, (k + 1) % M} <= skin_cols[r] & skin_cols[r + 1]:
            return SKIN, COVE

    g = af.loft(p, rings, SKIN, WING, seams=(0, n, 2 * n), soft=(n,),
                ring_seams=[xs.index(x) for x in bl.WING_UV_CUTS], cap_slot=(STRUCT, None), cap_cls=(0, CAP_ROOT),
                face_tag=cove)
    for f in g.faces():  # the cove unwraps on its own islands, folded off the skin's
        for e in f.edges:
            if len(e.link_faces) == 2 and e.link_faces[0][p.cls] != e.link_faces[1][p.cls]:
                e.seam = True
    landing_light(bl, p, g, xs, side, slots)
    joint_wiper(bl, p, g, side, bl.X_ROOT_TIP, 0, slots)
    control_end_seals(bl, p, side, slots)
    for x, flap in CANOES:
        canoe(bl, p, side, x, hinges[f"flap_{sfx}{flap}"], "fixed", slots)
    jettison_pipe(bl, p, side, slots)
    corners = []
    for a, b, _ in cuts:
        for x in (a - 0.04, b + 0.04):
            r = xs.index(x)
            edge = p.bm.edges.get((g.V[r][0], g.V[r][-1]))
            if edge is not None:
                corners.append(edge)
    bmesh.ops.bevel(p.bm, geom=corners, offset=0.035, segments=3, affect="EDGES", clamp_overlap=True)


def control_end_seals(bl, p, side, slots):
    """Thin internal end seals close the sight line through the slots, below both skin lips."""
    sec = root_section(bl, side)
    for _, x0, x1, kind in bl.SURFACES:
        if kind == "spoiler":
            continue
        for x, sign in ((x0, -1), (x1, 1)):
            rings = []
            for xx in (x + sign * 0.018 - 0.032, x + sign * 0.018 + 0.032):
                le, c, _, cd, td, cam = sec(xx)
                cut = bl.surface_hinge_fraction(kind, xx) + 0.03 / c
                if kind == "aileron":
                    wall = min((fold[-1] for fold, _ in aileron_cove(bl, side, xx, 11)), key=lambda q: q.dot(cd))
                    cut = (wall - le).dot(cd) / c
                front = bl.camber_point(le, c, cd, td, cam, cut)
                aft = bl.camber_point(le, c, cd, td, cam, 1.0)
                rings.append([front + td * 0.0015, aft + td * 0.0015,
                              aft - td * 0.0015, front - td * 0.0015])
            af.loft(p, rings, slots[0], COVE, seams=(0,))


def landing_light(bl, p, g, xs, side, slots):
    """An oval lens in a closed leading-edge bay, with a bowl and lamp behind it."""
    skin, _, _, mech, _, white, _ = slots
    a, b = (xs.index(x) for x in LANDING_LIGHT)
    n = ROOT_N
    for r in range(a, b):
        for k in (n - 1, n):
            p.bm.faces.remove(g.F.pop((r, k)))
    border = [g.V[a][n - 1], g.V[b][n - 1], g.V[b][n], g.V[b][n + 1], g.V[a][n + 1], g.V[a][n]]
    sec = root_section(bl, side)
    centre = sec(sum(LANDING_LIGHT) / 2)[0]
    across = (sec(LANDING_LIGHT[1])[0] - sec(LANDING_LIGHT[0])[0]).normalized()
    axis = across.cross(bl.TDIR).normalized()
    if axis.dot(-bl.CDIR) < 0:
        axis = -axis
    # Six boundary edges meet a 24-point oval, so the bay stays part of the closed wing shell.
    angles = (math.pi * 0.75, math.pi * 0.25, 0.0, -math.pi * 0.25, -math.pi * 0.75, -math.pi)
    oval = []
    for i, angle in enumerate(angles):
        end = angles[(i + 1) % 6] if i < 5 else angles[0] - 2 * math.pi
        for j in range(4):
            t = angle + (end - angle) * j / 4
            q = centre + across * (0.205 * math.cos(t)) + bl.TDIR * (0.075 * math.sin(t))
            le, c, th, cd, td, cam = sec(abs(q.x))
            height = (q - le).dot(td)
            upper = height >= 0
            low, high = 0.0, 0.05
            for _ in range(22):
                u = (low + high) / 2
                point = bl.airfoil_point(le, c, th, cd, td, cam, u, upper)
                if abs((point - le).dot(td)) < abs(height):
                    low = u
                else:
                    high = u
            oval.append(p.bm.verts.new(point))
    faces = []
    for i, v in enumerate(border):
        vv = border[(i + 1) % 6]
        for j in range(4):
            faces.append(p.bm.faces.new((v, oval[(4 * i + j + 1) % 24], oval[4 * i + j])))
        faces.append(p.bm.faces.new((v, vv, oval[(4 * i + 4) % 24])))
    p.tag(faces, skin, WING)
    back = p.bm.verts.new(centre - axis * 0.09)
    p.tag([p.bm.faces.new((oval[i], oval[(i + 1) % 24], back)) for i in range(24)], skin, REFLECTOR)
    lamp_unit(p, centre - axis * 0.005, axis, across, 0.199, 0.071, white, skin, white,
              dome=0.006, bowl=0.055)


def lamp_unit(p, centre, axis, across, half_w, half_h, lens, reflector, lamp, dome=0.025, bowl=0.025):
    """An oval lens over a satin reflector and an 8 cm emitter, dimensions in metres."""
    axis, across = axis.normalized(), across.normalized()
    up = axis.cross(across).normalized()
    rings = [[centre + axis * h + across * (half_w * scale * math.cos(2 * math.pi * i / 16))
              + up * (half_h * scale * math.sin(2 * math.pi * i / 16)) for i in range(16)]
             for scale, h in ((1.03, -0.009), (1.0, 0.001), (0.83, dome * 0.72), (0.42, dome))]
    af.loft(p, rings, lens, 0, seams=(0,), soft=tuple(range(16)), end=centre + axis * (dome * 1.1))
    sf.revolve_axis(p, ((0, -bowl - 0.005), (0.025, -bowl - 0.005), (0.05, -0.002),
                       (0.047, -0.002), (0.022, -bowl + 0.003), (0, -bowl + 0.003)), centre, axis, 16, reflector,
                    REFLECTOR, ref=across)
    sf.revolve_axis(p, ((0.04, -bowl + 0.002), (0.04, -bowl + 0.008), (0, -bowl + 0.01)),
                    centre, axis, 16, lamp, ref=across)


def joint_wiper(bl, p, cap_grid, side, x, child, slots):
    """Seal rolled into the parent's cap, outside the sliding section, below its perimeter plane."""
    sec = stage_section(bl, side, bl.TELE[child][1], stage_thickness(bl, child))
    pts = af.ring(bl, sec, x, STAGE_N)
    inner = af.inset_ring(pts, bl.CDIR, bl.TDIR, -0.005)
    outer = af.inset_ring(pts, bl.CDIR, bl.TDIR, -0.010)
    for f in cap_grid.caps[-1]:
        p.bm.faces.remove(f)
    # Zip contours of different resolutions by their chord fraction along each side.
    ax = Vector((side, 0, 0))
    rim = cap_grid.V[-1]
    raised = [p.bm.verts.new(q - ax * 0.001) for q in outer]
    recessed = [p.bm.verts.new(q - ax * 0.012) for q in inner]
    for first, second, cls in ((rim, raised, (CAP_ROOT, CAP_STAGE1)[child]), (raised, recessed, WIPER)):
        m, n = len(first), len(second)
        i = j = 0
        faces = []
        while i < m or j < n:
            if i < m and (j == n or (i + 1) / m <= (j + 1) / n):
                faces.append(p.bm.faces.new((first[i % m], first[(i + 1) % m], second[j % n])))
                i += 1
            else:
                faces.append(p.bm.faces.new((first[i % m], second[(j + 1) % n], second[j % n])))
                j += 1
        p.tag(faces, slots[0], cls)
    p.tag(sf.cap(p.bm, recessed), slots[0], (CAP_ROOT, CAP_STAGE1)[child])


def jettison_pipe(bl, p, side, slots):
    """The fuel jettison pipe: a short tube out of the blunt trailing edge, angled a little down, its inner end buried
    in the edge (1.6 m behind the stage's trailing edge, so it never nears a stage vertex)."""
    MECH = slots[3]
    le, c, t, cd, td, cam = root_section(bl, side)(JETTISON)
    up, lo = (bl.airfoil_point(le, c, t, cd, td, cam, 1.0, u) for u in (True, False))
    mid = (up + lo) / 2
    out = (cd - td * 0.12).normalized()
    sf.tube(p, [mid - cd * 0.08, mid + out * 0.12, mid + out * 0.3], 0.028, 12, MECH, sf.FITTING)


def build_stage(bl, p, side, k, slots):
    """A stage: its constant section from the inner end to the outer end, the run that stays inside the chain at full
    extension on aircraft_structure, a soft bevel round the outer end."""
    SKIN, STRUCT = slots[0], slots[1]
    _, chord, length, inset = bl.TELE[k]
    outer = bl.XI_ROOT_TIP - inset
    sec = stage_section(bl, side, chord, stage_thickness(bl, k))
    hidden = outer - bl.TRAVEL - 0.1  # inboard of this the stage stays inside the chain at full extension
    bevel = outer - BEVEL[1] * bl.XI_PER_X
    xis = [outer - length] + sf.frange(hidden, bevel, STAGE_RING)
    xis = sorted(set(sf.frange(xis[0], hidden, STAGE_RING) + xis[1:] + [outer]))
    rings = [af.ring(bl, sec, xi / bl.XI_PER_X, STAGE_N) for xi in xis]
    rings[-1] = af.inset_ring(rings[-1], bl.CDIR, bl.TDIR, BEVEL[0])
    g = af.loft(p, rings, SKIN, (STAGE1, STAGE2)[k], seams=(0, STAGE_N, 2 * STAGE_N), soft=(STAGE_N,),
            cap_slot=(STRUCT, None), cap_cls=(0, (CAP_STAGE1, CAP_STAGE2)[k]),
            face_tag=lambda r, c: (STRUCT, 0) if xis[r + 1] <= hidden + 1e-6 else None)
    if k == 0:
        joint_wiper(bl, p, g, side, outer / bl.XI_PER_X, 1, slots)


def tip_table(bl, side):
    """The raked, upswept tip (build_centurion.tip_rings) as (x, leading edge, chord, thickness) rows at TIP_F, and the
    point its rounded end (bl.TIP_ROUND) closes on."""
    tip_xi = bl.XI_ROOT_TIP - bl.TELE[1][3]
    base = bl.qc_at(side, tip_xi + bl.TIP_NECK)
    end_chord, end_thick = bl.interp(bl.CHORD, bl.X_ROOT_TIP), bl.interp(bl.THICK, bl.X_ROOT_TIP)
    w = bl.span_axis(side, bl.TIP_UPSWEEP)
    reach = (bl.RETRACTED_SEMISPAN - 0.02 - abs(base.x)) / abs(w.x)
    f0, back = bl.TIP_ROUND
    rows = []
    for f in TIP_F + (1.0,):
        d = f * reach
        te = base + w * d + 0.75 * end_chord * bl.CDIR
        chord = end_chord - d * abs(w.x) * math.tan(bl.TIP_RAKE) - 0.35 * f ** 3 * end_chord
        le, thick = te - chord * bl.CDIR, end_thick * (1 - 0.55 * f)
        if f > f0:
            g = (f - f0) / (1 - f0)
            e = math.sqrt(max(0.0, 1 - g * g))
            le, chord, thick = le + (1 - e) * back * chord * bl.CDIR, chord * e, thick * e
        rows.append((abs(te.x), le, chord, thick))
    *rows, (_, le, _, _) = rows
    return rows, le


def build_tip(bl, p, side, slots):
    """The tip on wing_tele2: a neck through the stage's end cap out to a cuff cut to the fixed wing's end section
    (bevelled to match the root's end), then the raked, upswept tip, its nav light, strobe and static dischargers."""
    SKIN, STRUCT, GLASS, MECH, RED, WHITE, FORMATION_SLOT = slots
    n = TIP_N
    _, chord, _, inset = bl.TELE[1]
    thick = stage_thickness(bl, 1)
    tip_xi = bl.XI_ROOT_TIP - inset

    def neck(xi, k):
        return bl.airfoil(bl.qc_at(side, xi) - 0.25 * chord * k * bl.CDIR, chord * k, thick * k, bl.CDIR, bl.TDIR,
                          bl.WING_CAMBER, n=n)

    rows, point = tip_table(bl, side)
    rings = [neck(tip_xi - 0.05, 0.985), neck(tip_xi + bl.TIP_NECK, 1.0)]
    rings += [bl.airfoil(le, c, t, bl.CDIR, bl.TDIR, bl.WING_CAMBER, n=n) for _, le, c, t in rows]
    rings[2] = af.inset_ring(rings[2], bl.CDIR, bl.TDIR, BEVEL[0])
    # Keep the cuff's matching perimeter while chamfering its exposed closing rib aft of stage 2.
    child_te = (neck(tip_xi + bl.TIP_NECK, 1.0)[0]).dot(bl.CDIR)
    for i, q in enumerate(rings[2]):
        le, c, *_ = root_section(bl, side)(bl.X_ROOT_TIP)
        u = (q - le).dot(bl.CDIR) / c
        if u > 0.96:
            rings[2][i] = q - bl.CDIR * (0.055 * ((u - 0.96) / 0.04) ** 2)
    chamfer = [a.lerp(b, 0.45) for a, b in zip(rings[1], rings[2])]
    for i, q in enumerate(chamfer):
        excess = max(0.0, q.dot(bl.CDIR) - child_te)
        chamfer[i] = q + Vector((side, 0, 0)) * min(0.15, excess * 0.7)
    rings.insert(2, chamfer)
    af.loft(p, rings, SKIN, TIP, seams=(0, n, 2 * n), soft=(n,), ring_seams=(1, 3), end=point, cap_slot=(STRUCT, None),
            cap_cls=(0, TIP), face_tag=lambda r, k: (SKIN, CAP_CUFF) if r < 3 else None)
    sec = af.table_section(bl, rows)
    reach = lambda f: rows[0][0] + (rows[-1][0] - rows[0][0]) * f
    tsurf = af.AirfoilSurface(bl, sec)
    f, half_w, half_h = NAV_LENS
    centre = tsurf.point(reach(f), 0.0)
    axis = (Vector((side, 0, 0)) * 0.7 - bl.CDIR).normalized()
    across = bl.TDIR.cross(axis).normalized()
    nav = RED if side > 0 else GREEN
    lamp_unit(p, centre + axis * 0.040, axis, across, half_w, half_h, nav, SKIN, nav)
    le, c, t, cd, td, cam = sec(reach(LIGHT_F))
    out = Vector((side, 0, 0))
    tip_light(p, le + cd * (c - 0.03), (out * 0.3 + cd).normalized(), WHITE, MECH, 0.055)
    # strobe on the upper skin of the rounded end, looking up and outboard
    le, c, t, cd, td, cam = sec(reach(STROBE_F))
    tip_light(p, bl.airfoil_point(le, c, t, cd, td, cam, 0.45, True), (td + out * 0.5).normalized(), WHITE, MECH, 0.06)
    xa, xb = formation_span([r[0] for r in rows])
    _, u0, _, width = FORMATION
    ca, cb = sec(xa)[1], sec(xb)[1]
    s0 = math.sqrt(u0)
    corners = [(xa, s0), (xb, s0), (xb, math.sqrt(u0 + width / cb)), (xa, math.sqrt(u0 + width / ca))]
    sf.surface_patch(p, tsurf, corners, 4, 1, 0.006, -0.012, FORMATION_SLOT)
    for f in DISCHARGERS["tip"]:
        le, c, t, cd, td, cam = sec(rows[0][0] + (rows[-1][0] - rows[0][0]) * f)
        af.discharger(p, le + cd * (c - 0.01), cd, td, MECH)


def formation_span(xs):
    """The formation strip's inboard and outboard x on the tip, whose rows sit at xs (FORMATION: its inboard end as
    a reach fraction, and its length)."""
    f0, _, length, _ = FORMATION
    xa = xs[0] + (xs[-1] - xs[0]) * f0
    return xa, xa + length


def tip_light(p, centre, axis, lens, bezel, r):
    """A light on the tip: a dark bezel sunk into the surface with a low lens on it (a tall dome read as a gumdrop stuck
    on). The bezel stays off the skin atlas: a revolve is not mirrored vertex for vertex, so its UVs could not be
    copied to the right-hand tip."""
    prof = ((r, -0.05), (r, 0.003), (r * 0.86, 0.008), (0, 0.008))
    sf.revolve_axis(p, prof, centre, axis, LIGHT_SEG, bezel)
    prof = ((r * 0.74, 0.004), (r * 0.72, 0.014), (r * 0.46, 0.025), (0, 0.029))
    sf.revolve_axis(p, prof, centre, axis, LIGHT_SEG, lens)


def canoe(bl, p, side, x, hinge, half, slots):
    """One flap-track fairing half under the wing at semi-span x. The halves meet on a cylinder about the flap hinge
    line, so the moving half (on the flap) turns with the flap without entering the fixed half (on the root); the
    tops stay buried in the skin, on aircraft_structure, until the trailing edge."""
    SKIN, STRUCT = slots[0], slots[1]
    le, c, th, cd, td, cam = root_section(bl, side)(x)
    h0, h1 = hinge
    axis = (h1 - h0).normalized()
    H = h0.lerp(h1, (x - abs(h0.x)) / (abs(h1.x) - abs(h0.x)))
    u_h = (H - le).dot(cd) / c
    te = (1 - u_h) * c
    across = Vector((side, 0, 0))

    def base(off):
        u = u_h + off / c
        if u <= 1:
            return bl.airfoil_point(le, c, th, cd, td, cam, u, False)
        return bl.airfoil_point(le, c, th, cd, td, cam, 1.0, False) + cd * ((u - 1) * c)

    def section(off):
        return canoe_ring(base(off), across, td, *canoe_section(off, te))

    # the split: the deepest section's points slid along the chord onto a cylinder about the hinge line
    pts = section(CANOE_MID)
    a = 1 - cd.dot(axis) ** 2
    quad = []
    for q in pts:
        d = q - H
        b = 2 * (d.dot(cd) - d.dot(axis) * cd.dot(axis))
        c0 = d.length_squared - d.dot(axis) ** 2
        quad.append((b, c0))
    R2 = max(c0 - b * b / (4 * a) for b, c0 in quad) / math.cos(math.radians(CANOE_SPLIT_ANGLE)) ** 2
    slide = [(-b - math.sqrt(b * b - 4 * a * (c0 - R2))) / (2 * a) for b, c0 in quad]
    top_hidden = lambda r, k: (STRUCT, 0) if k in (CANOE_M - 1, 0) else None
    if half == "fixed":
        rings = [section(off) for off in (-2.25, -1.95, -1.6, -1.2)]
        rings.append([q + cd * (s - CANOE_GAP / 2) for q, s in zip(pts, slide)])
        af.loft(p, rings, SKIN, FAIRING, seams=(0,), start=base(CANOE_NOSE) - td * 0.012, cap_slot=(None, STRUCT),
                cap_cls=(None, 0), face_tag=top_hidden)
    else:
        # rings closer where the bottom line bends, toward the tail point
        aft = (-0.3, 0.33 * te, 0.7 * te, te) + tuple(te + f * CANOE_TAIL for f in (0.45, 0.76, 0.92))
        rings = [[q + cd * (s + CANOE_GAP / 2) for q, s in zip(pts, slide)]]
        rings += [section(off) for off in aft]
        exposed = 1 + aft.index(te)  # from the trailing edge the top shows
        end = base(te + CANOE_TAIL) - td * CANOE_DROP
        af.loft(p, rings, SKIN, FAIRING, seams=(0,), end=end, cap_slot=(STRUCT, None), cap_cls=(0, None),
                face_tag=lambda r, k: top_hidden(r, k) if r < exposed else None)


def build_flap(bl, p, side, x0, x1, hinge, canoe_xs, slots):
    SKIN, STRUCT = slots[0], slots[1]
    n, nose = 6, 5
    sec = root_section(bl, side)
    rings = []
    for x in (x0, (x0 + x1) / 2, x1):
        c = sec(x)[1]
        rings.append(af.aft_ring(bl, sec, x, bl.FLAP_HINGE + 0.02 / c, n, nose, NOSE_K["flap"]))
    af.loft(p, rings, SKIN, FLAP, seams=(0, n + 1 + nose // 2, 2 * n + 1 + nose), cap_slot=(SKIN, SKIN),
            cap_cls=(COVE, COVE))
    for x in canoe_xs:
        canoe(bl, p, side, x, hinge, "moving", slots)


def build_aileron(bl, p, side, x0, x1, slots):
    SKIN, STRUCT, GLASS, MECH = slots[:4]
    sec = root_section(bl, side)
    rings = [aileron_ring(bl, side, x) for x in (x0, (x0 + x1) / 2, x1)]
    g = af.loft(p, rings, SKIN, AILERON, seams=(0, AIL_N + 8, 2 * AIL_N + 16), start=None, end=None)
    _, _, _, cd, td, _ = sec(x0)
    for ring, verts in ((rings[0][::-1], g.V[0][::-1]), (rings[-1], g.V[-1])):
        p.tag(ear_cap(p.bm, verts, [(q.dot(cd), q.dot(td)) for q in ring]), SKIN, COVE)
    for x in DISCHARGERS["aileron"]:
        le, c, t, cd, td, cam = sec(x)
        af.discharger(p, le + cd * (c - 0.01), cd, td, MECH)


def ear_cap(bm, verts, pts):
    """Close a ring that need not be convex (the aileron's notched nose) by ear clipping on its section points pts,
    faces wound as the ring. A zipped cap bridged the notch, outside the section and into the root's cove. Ears go
    by index, so a mirrored twin gets the same faces."""
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    cross = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    idx, faces = list(range(n)), []
    while len(idx) > 3:
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if cross(a, b, c) * area <= 1e-12:
                continue
            sg = math.copysign(1, area)
            if any(min(sg * cross(a, b, q), sg * cross(b, c, q), sg * cross(c, a, q)) > 1e-12
                   for q in (pts[j] for j in idx if j not in (i0, i1, i2))):
                continue
            faces.append(bm.faces.new((verts[i0], verts[i1], verts[i2])))
            del idx[k]
            break
        else:
            raise SystemExit("ear_cap: no ear left")
    faces.append(bm.faces.new([verts[i] for i in idx]))
    for k in range(n):
        sf.seam(bm, verts[k], verts[(k + 1) % n])
    return faces


def spoiler_te(bl, x, c):
    """The spoiler's trailing edge (chord fraction) at semi-span x, chord c (an array in the paint): the blockout's,
    held 1.5 cm ahead of the root's lip over the aileron's cove where that runs further forward (inboard), so the
    spoiler never overhangs the cove."""
    a, b = next((a, b) for _, a, b, kind in bl.SURFACES if kind == "aileron")
    t1 = bl.SPOILER_CHORD[1]
    over_cove = (x >= a - bl.SURF_GAP) & (x <= b + bl.SURF_GAP)
    return np.where(over_cove, np.minimum(t1, lip_edge(bl, x) - 0.015 / c), t1)


def build_spoiler(bl, p, side, x0, x1, slots):
    """An 8 mm panel with its top 4 mm above the skin and a feathered hinge lip."""
    SKIN, STRUCT, GLASS, MECH = slots[:4]
    t0 = bl.SPOILER_CHORD[0]
    sec = root_section(bl, side)
    rings = []
    for x in sf.frange(x0, x1, 0.5):
        le, c, t, cd, td, cam = sec(x)
        t1 = float(spoiler_te(bl, x, c))
        up = lambda u: bl.airfoil_point(le, c, t, cd, td, cam, u, True)
        ts = [t0 + (t1 - t0) * k / 3 for k in range(4)]
        top = [up(u) + td * 0.004 for u in reversed(ts)]
        front = [up(t0) - cd * 0.010]
        bottom = [up(u) - td * 0.004 for u in ts]
        rings.append(top + front + bottom)
    af.loft(p, rings, SKIN, SPOILER, seams=(0, 4), cap_cls=(SPOILER, SPOILER))


def trim(bl, objs, folder):
    """Resolve Blender's ambiguous winding on the shallow closing-rib annuli before baking normals."""
    for obj in objs.values():
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        seen = set()
        for face in bm.faces:
            if face in seen:
                continue
            shell, stack = [], [face]
            seen.add(face)
            while stack:
                f = stack.pop()
                shell.append(f)
                for e in f.edges:
                    for neighbour in e.link_faces:
                        if neighbour not in seen:
                            seen.add(neighbour)
                            stack.append(neighbour)
            # A shell-local origin avoids cancellation on a centimetre lamp far down an extended wing.
            origin = shell[0].verts[0].co.copy()
            volume = sum(q[0].dot(q[i].cross(q[i + 1])) for f in shell
                         for q in [[v.co - origin for v in f.verts]] for i in range(1, len(q) - 1))
            if volume < 0:
                bmesh.ops.reverse_faces(bm, faces=shell)
        bm.normal_update()
        bm.to_mesh(obj.data)
        bm.free()
    return {"pass": True}


# ---------- paint layout ----------
# Inner wing (WING), step 6: the wing-body fairing covers the root to about x 3.4; the pylon sits on the lower skin over
# x 6.89 to 7.61 and its fillets over 6.67 to 7.83 (left plain, PYLON_FILLET); the stages fill the root from x 11.3
# outboard, so the fuel tank and its manholes stop there and the sleeve outboard carries the stages' roller inspection
# panels; the
# strut meets the lower skin at x 19.4, 62% chord, under the struts group's node pod, which covers that skin, so it
# carries no paint of its own.
# Panel lines follow the structure: spanwise lap joints on the spar and stringer lines (chord fraction, side +1 upper /
# -1 lower / 0 both, fastener rows: rows only on the spars and the leading-edge skin joint), full-chord splices (x,
# from the leading edge to the trailing edge) every three or four ribs with fastener rows, the trailing-edge panels
# aft of the rear spar split on every other rib, access panels (x, chord fraction, size along x and chord in metres,
# corner radius, side).
ROOT_LINES = ((0.055, 0, 1), (0.12, 0, 2), (0.27, 1, 0), (0.25, -1, 0), (0.40, 1, 0), (0.43, -1, 0), (0.53, 1, 0),
              (0.56, -1, 0), (0.65, 0, 2), (0.84, 0, 0))
ROOT_SPLICES = (3.5, 6.0, 8.5, 11.3, 13.0, 15.4, 17.7)  # flap 1's inner end, either side of the pylon, the stage
# box's closing rib, the 13 m kink, then even bays to the end collar
TE_JOINT = 1.2  # trailing-edge panel joints aft of the rear spar (every other 0.6 m rib)
# Inner tank manholes on the lower skin, one in each rib bay between the splices, off the pylon's fillets
FUEL_PANELS = tuple((x, 0.36, 0.5, 0.3, 0.11, -1) for x in (3.95, 4.75, 5.55, 6.35, 8.15, 9.45, 10.45))
SLEEVE_PANELS = tuple((x, 0.3, 0.36, 0.22, 0.04, -1) for x in (14.2, 16.5, 18.5))
# Upper skin: few, square-cornered access panels in rib bays by the spars and actuators (rule 1; a staggered grid of
# small rounded ones read as wallpaper from above): the flap drives over tracks 1 and 2 by the rear spar, the
# aileron actuator, a fuel probe and a stage-rail panel by the front spar.
UPPER_PANELS = ((4.3, 0.67, 0.4, 0.2, 0.015, 1), (9.8, 0.67, 0.4, 0.2, 0.015, 1), (14.2, 0.47, 0.42, 0.18, 0.015, 1),
                (7.25, 0.2, 0.4, 0.2, 0.015, 1), (16.5, 0.2, 0.4, 0.2, 0.015, 1))
# The pylon's wing fillets land on the lower skin over x 6.67 to 7.83 from the leading edge to station 21.3 (the
# engines group's); that skin carries no paint of the wing's.
PYLON_FILLET = (6.67, 7.83, 21.3)
LAP_CONTRAST = 0.5  # stringer laps (lines without fastener rows) at this share of a primary joint's groove
# Lower skin behind the rear spar: flap and aileron actuator and hydraulic access, clear of the fairings and the pylon
LOWER_PANELS = tuple((x, u, 0.3, 0.2, 0.04, -1) for x, u in ((5.15, 0.6), (8.35, 0.6), (12.1, 0.6), (13.9, 0.5),
                                                            (15.0, 0.6), (16.6, 0.5)))
WALKWAY = (3.6, 6.3, 0.18, 0.58)  # x from, to; chord fractions: outboard of the fairing, bordered by dashed lines
NO_STEP = (3.95, 5.1, 6.25)  # x of the NO STEP stencils on flap 1, behind the walkway (TEXT_PARTS)
NO_STEP_H = 0.14  # their raster's height in metres: 6 cm letters were 4 texels at 61 px/m, a blur
FUEL_FILLER = (10.0, 0.33)  # gravity filler on the upper skin, at the inner tank's outer end
FUEL_VENT = (10.9, 0.28)  # NACA vent on the lower skin
JACK_POINT = (8.9, 0.3)  # outboard of the pylon, lower skin
# Placards (x, chord fraction, size along x and chord in metres, side): servicing notes as plain ruled plates, which
# read either way round on the mirrored islands.
PLACARDS = ((10.15, 0.4, 0.34, 0.1, 1), (10.9, 0.36, 0.3, 0.08, -1), (8.75, 0.36, 0.3, 0.08, -1),
            (12.6, 0.9, 0.26, 0.08, 1), (17.9, 0.3, 0.3, 0.08, -1), (5.0, 0.62, 0.3, 0.08, -1))
END_COLLAR = 0.16  # the satin metal band each end a stage slides through
SEAL_BAND = 0.03  # the black rubber seal band at the outer edge of a parent's end collar
SEAL = 0.012  # the cap's rubber band covers the wiper's 5 to 10 mm clearance round the child
# Stages: the root's spar and stringer lines and a splice at each quarter of the run that shows at full extension, a red
# witness line just outboard of the seal
STAGE_LINES = ((0.055, 0, 1), (0.15, 0, 2), (0.27, 1, 0), (0.25, -1, 0), (0.40, 1, 0), (0.53, 1, 0), (0.56, -1, 0),
               (0.65, 0, 2))
# Access panels on a stage's exposed run: (metres outboard of the parent's end at full extension, chord fraction, size
# along x and chord, corner radius, side), between the splices at its quarters
STAGE_PANELS = (
    ((2.0, 0.4, 0.46, 0.28, 0.08, -1), (4.7, 0.42, 0.58, 0.3, 0.09, -1),
     (7.0, 0.38, 0.4, 0.26, 0.07, -1), (9.7, 0.4, 0.52, 0.32, 0.10, -1),
     (6.4, 0.2, 0.4, 0.2, 0.015, 1), (3.3, 0.47, 0.34, 0.18, 0.015, 1), (9.0, 0.47, 0.46, 0.22, 0.015, 1)),
    ((1.7, 0.38, 0.40, 0.24, 0.07, -1), (4.5, 0.43, 0.48, 0.28, 0.08, -1),
     (7.9, 0.36, 0.54, 0.30, 0.09, -1), (10.2, 0.41, 0.38, 0.22, 0.06, -1),
     (2.1, 0.2, 0.32, 0.16, 0.015, 1), (4.8, 0.46, 0.42, 0.20, 0.015, 1), (7.6, 0.22, 0.36, 0.18, 0.015, 1)),
)

PAINT_RGB = (0.38, 0.39, 0.405)  # paint.PAINT[HULL]
COVE_RGB = (0.32, 0.33, 0.345)  # cove structure: the skin's grey a shade down
DARK = (0.10, 0.105, 0.11)
RUBBER = (0.05, 0.05, 0.055)
# One satin metal for every bare-metal surface (leading-edge strips, collars, end caps): smoothness 0.12 over the
# skin's 0.42, low metal, so it never reads as chrome.
SATIN = {"rgb": (0.46, 0.47, 0.48), "smooth": 0.54, "metal": 0.2}
STENCIL = (0.80, 0.80, 0.78)
PLACARD = ((0.50, 0.51, 0.52), (0.30, 0.305, 0.31))  # plate, rules
RED = (0.55, 0.10, 0.08)
RED_LINE = 0.022  # every red marking's line weight
WITNESS_TINT = 0.5  # the stage witness line's share of RED over the skin: full red there read as the loudest mark
WALK = (0.58, 0.59, 0.59)  # the walkway's dashed border, as the nose's and the fairing's
SKIN_CLASSES = (WING, STAGE1, STAGE2, TIP, FLAP, AILERON, SPOILER, FAIRING,
                CAP_ROOT, CAP_STAGE1, CAP_STAGE2, CAP_CUFF)


def paint(cv, text_mask):
    """The group's paint over a Canvas (m4/paint.py)."""
    np = cv.xp
    lip_edge(cv.surf.bl, 0.0)  # Build the geometry's small lip table once, with host scalars.
    def paint_lip_edge(x, upper=True):
        c = np.interp(x, _LIP["xs"], _LIP["chord"])
        cut = (0.25 * c + bl.AILERON_HINGE_BEHIND_QC) / c
        return cut - np.interp(x, _LIP["xs"], _LIP["setback"][0 if upper else 1]) / c

    def paint_spoiler_te(x, c):
        a, b = next((a, b) for _, a, b, kind in bl.SURFACES if kind == "aileron")
        over_cove = (x >= a - bl.SURF_GAP) & (x <= b + bl.SURF_GAP)
        return np.where(over_cove, np.minimum(bl.SPOILER_CHORD[1], paint_lip_edge(x) - 0.015 / c), bl.SPOILER_CHORD[1])
    from .paint import poly_sdf, rrect_sdf, smoothstep
    bl = cv.surf.bl
    cls = cv.cls
    pos, nrm = cv.pos.copy(), cv.nrm.copy()
    # Texels of the right-hand TEXT_PARTS (the rest of the right wing shares the left's islands): the layout reads
    # them on the left, the text turns to read the right way round on them.
    neg = pos[:, 0] < 0
    pos[neg, 0] *= -1
    nrm[neg, 0] *= -1
    for classes, k in ((ON_STAGE1, 0), (ON_STAGE2, 1)):
        name = f"{bl.TELE[k][0]}_L"
        on = np.isin(cls, classes)
        pos[on] -= np.array(tuple(stage_shift(bl, name, 1, k)))

    fam = families(bl)
    # Texels on no family (caps, fittings) keep chord 1: a NaN from dividing by a zero chord would survive the
    # zero masks below (NaN times 0 is NaN) and black out their normal map.
    X, U, C = np.zeros(cv.n), np.zeros(cv.n), np.ones(cv.n)
    UP = np.zeros(cv.n, bool)
    groups = {"root": (WING, FLAP, AILERON, SPOILER, FAIRING), "t1": (STAGE1,), "t2": (STAGE2,), "tip": (TIP,)}
    for key, classes in groups.items():
        m = np.isin(cls, classes)
        from .paint import locate_section, section_plane
        X[m], U[m], C[m], UP[m] = locate_section(fam[key], pos[m], nrm[m])
    S = U * C  # metres from the leading edge along the chord
    up, lo = UP.astype(float), (~UP).astype(float)

    for c in SKIN_CLASSES:
        m = cls == c
        cv.albedo[m] = PAINT_RGB
        cv.smooth[m] = 0.42
    on = lambda *cs: np.isin(cls, cs).astype(float)
    W, T1, T2, TP = on(WING), on(STAGE1), on(STAGE2), on(TIP)
    WS = W + T1 + T2 + TP
    cv.paint(on(REFLECTOR), **SATIN)

    def side_mask(s):
        return up if s > 0 else lo if s < 0 else 1.0

    def chord_line(mask, u0, s, rows, x0=-1.0, x1=99.0):
        d = np.abs(U - u0) * C
        m = mask * side_mask(s) * (X >= x0) * (X <= x1)
        cv.groove(d, mask=m * (1.0 if rows else LAP_CONTRAST))  # a groove's darkening and depth scale with its mask
        if rows == 2:
            cv.fasteners(d, X, 0.03, mask=m * (d < 0.08))
        elif rows == 1:  # one row, on the aft side of the joint
            cv.fasteners(np.abs((U - u0) * C - 0.025), X, 0.0, mask=m * (d < 0.08))

    def rib(mask, x0, u0=0.055, u1=1.01, rows=True):
        d = np.abs(X - x0)
        m = mask * (U >= u0) * (U <= u1)
        cv.groove(d, mask=m)
        if rows:
            cv.fasteners(d, S, 0.025, mask=m * (d < 0.06))

    def te_joints(mask, x_from, x_to):  # secondary joints: no fastener rows
        for x in np.arange(x_from, x_to, TE_JOINT):
            rib(mask, x, 0.65, 1.01, rows=False)

    def panel(mask, x, u, wx, ws_, r, s, fasten=True):
        sdf = rrect_sdf(X, (U - u) * C, x - wx / 2, x + wx / 2, -ws_ / 2, ws_ / 2, r)
        m = mask * side_mask(s)
        cv.groove(np.abs(sdf), mask=m)
        if fasten:
            cv.fasteners(np.abs(sdf), X + S, 0.028, mask=m * (np.abs(sdf) < 0.06))
        return sdf

    x_root = bl.X_ROOT_TIP
    # panel tones, Darkreach-like: each skin panel between joints differs a little
    breaks = np.array(sorted(set(ROOT_SPLICES) | {0.0, x_root}))
    cell = (np.searchsorted(breaks, X) * 8 + np.searchsorted(np.array([0.055, 0.15, 0.4, 0.65, 0.84]), U)) * 2 + UP
    cell = cell * 16 + np.clip(cls - 10, 0, 15)
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    cv.albedo *= (1 + 0.045 * tone * on(*SKIN_CLASSES))[:, None]

    # leading-edge erosion strips on the wing, stages and tip
    cv.paint(WS * smoothstep(0.06, 0.045, U), **SATIN)

    # ---- inner wing ----
    x_in = x_root - END_COLLAR
    fx0, fx1, f_station = PYLON_FILLET
    WP = W * (1 - lo * (X > fx0) * (X < fx1) * (pos[:, 1] + bl.Y0 < f_station))  # the inner wing off the fillets
    for i, (u0, s, rows) in enumerate(ROOT_LINES):
        if rows:
            chord_line(WP, u0, s, rows, 3.0, x_in)
        else:
            for j, (a, b) in enumerate(zip(ROOT_SPLICES, ROOT_SPLICES[1:] + (x_in,))):
                if (i + j) % 3 != 0:
                    chord_line(WP, u0, s, rows, a + 0.035, b - 0.035)
    for x in ROOT_SPLICES:
        rib(WP, x, 0.0)
    te_joints(WP, ROOT_SPLICES[0] + TE_JOINT, x_in - 0.2)
    for x, u, wx, ws_, r, s in FUEL_PANELS + SLEEVE_PANELS + UPPER_PANELS + LOWER_PANELS:
        panel(WP, x, u, wx, ws_, r, s)
    for i, x in enumerate(np.arange(3.8, x_in - 0.3, 0.6)):
        if (min(abs(x - splice) for splice in ROOT_SPLICES) < 0.24
                or any(abs(x - px) < 0.45 for px, pu, *_ in UPPER_PANELS if pu == 0.67)):
            continue
        wx, ws_ = ((0.22, 0.13), (0.32, 0.18), (0.25, 0.15))[i % 3]
        panel(WP, x, 0.67, wx, ws_, 0.015, 1)
    for x, u, wx, ws_, r, s in FUEL_PANELS:
        panel(WP, x, u, wx + 0.13, ws_ + 0.13, r + 0.04, s)
    for x in np.arange(3.6, x_in - 0.3, 1.2):
        rib(WP, x, 0.0, 0.12)
    for x in (3.8, 4.7, 5.6, 6.4):
        panel(WP, x, 0.075, 0.7 if x < 6 else 0.35, 0.34, 0.025, -1)
        panel(WP, x, 0.10, 0.18, 0.10, 0.015, -1)
    # walkway: dashed light border lines ahead, behind and outboard (the fairing closes it inboard); NO STEP outside it,
    # on flap 1 below
    x0, x1, u0, u1 = WALKWAY
    dash_x, dash_s = ((X - x0) % 0.32) < 0.2, ((S - u0 * C) % 0.32) < 0.2
    edge = cv.coverage(np.abs(S - u0 * C), 0.025) + cv.coverage(np.abs(S - u1 * C), 0.025)
    edge = np.clip(edge, 0, 1) * dash_x * (X > x0) * (X < x1)
    edge = np.maximum(edge, cv.coverage(np.abs(X - x1), 0.025) * dash_s * (S > u0 * C) * (S < u1 * C))
    cv.paint(edge * W * up, rgb=WALK)
    # red keep-clear lines ahead of the moving surfaces, and round the spoilers
    for pattern, xa, xb, kind in bl.SURFACES:
        if kind == "spoiler":
            t0, t1 = bl.SPOILER_CHORD[0], paint_spoiler_te(X, C)
            # front and ends only: aft of the spoilers lies the aileron's lip, too close for a line (the aileron hinge
            # runs from 0.73 to 0.89 chord)
            sdf = rrect_sdf(X, S, xa - 0.06, xb + 0.06, t0 * C - 0.06, t1 * C + 0.06, 0.04)
            cv.paint(cv.coverage(np.abs(sdf), RED_LINE) * W * up * (S < t1 * C), rgb=RED)
            continue
        if kind == "aileron":  # the spoilers span it, so their outline is its line: the skin between them and the
            continue  # lip narrows to nothing partway along, and a line there stopped in mid-air
        cove = bl.FLAP_HINGE * C
        cv.paint(cv.coverage(np.abs(S - (cove - 0.07)), RED_LINE) * W * up * (X > xa) * (X < xb), rgb=RED)
    # fuel filler with its marker, fuel vent, jacking point: shapes in (x, metres aft of a chord fraction)
    fx, fu = FUEL_FILLER
    V = S - fu * C
    r = np.hypot(X - fx, V)
    cv.paint(cv.fill_coverage(r - 0.06) * W * up, rgb=DARK, height=-0.002)
    cv.groove(np.abs(r - 0.075), 0.012, mask=W * up)
    cv.paint(cv.fill_coverage(poly_sdf(X, V, [(fx + 0.16, 0.0), (fx + 0.26, -0.06), (fx + 0.26, 0.06)])) * W * up,
             rgb=RED)
    vx, vu = FUEL_VENT
    sdf = poly_sdf(X, S - vu * C, [(vx - 0.06, -0.12), (vx + 0.06, -0.12), (vx, 0.16)])
    cv.paint(cv.fill_coverage(sdf) * W * lo, rgb=(0.16, 0.16, 0.17), height=-0.01)
    cv.groove(np.abs(sdf), 0.012, mask=W * lo)
    jx, ju = JACK_POINT
    sdf = poly_sdf(X, S - ju * C, [(jx - 0.1, -0.08), (jx + 0.1, -0.08), (jx, 0.1)])
    cv.paint(cv.coverage(np.abs(sdf), 0.02) * W * lo, rgb=STENCIL)
    # fuel jettison pipe: a red keep-clear ring on the trailing edge round it
    cv.paint(cv.coverage(np.abs(np.hypot(X - JETTISON, (1 - U) * C * 4) - 0.12), RED_LINE) * W, rgb=RED)
    for x, u, wx, ws_, s in PLACARDS:
        placard(cv, W * side_mask(s), X, S - u * C, x, wx, ws_)
    for x, u in ((9.7, 0.33), (10.3, 0.33)):
        placard(cv, W * up, X, S - u * C, x, 0.22, 0.10)
    # the end collar the first stage slides through, and its seal band
    collar(cv, W, X, S, x_in, x_root, seal=True)
    # cove: the walls and the lip's underside in the skin's grey a shade down, and the aileron's lower seal strip
    cv.paint(on(COVE), rgb=COVE_RGB, smooth=0.36)
    xa, xb = next((a, b) for _, a, b, kind in bl.SURFACES if kind == "aileron")
    seal_edge = paint_lip_edge(X, upper=False) * C
    run = W * lo * (X > xa - bl.SURF_GAP) * (X < xb + bl.SURF_GAP)
    cv.paint(run * (S > seal_edge - SEAL_STRIP), rgb=COVE_RGB, smooth=0.36)
    cv.groove(np.abs(S - (seal_edge - SEAL_STRIP)), mask=run)
    cv.paint(on(WIPER), rgb=RUBBER, smooth=0.3, metal=0.0)

    # ---- stages ----
    for k, mask in ((0, T1), (1, T2)):
        _, chord, length, inset = bl.TELE[k]
        x_end = (bl.XI_ROOT_TIP - inset) / bl.XI_PER_X
        x_seal = x_end - bl.TRAVEL / bl.XI_PER_X  # the parent's end, at full extension, in the stage's rest frame
        splices = (0.22, 0.53, 0.79) if k == 0 else (0.28, 0.57, 0.82)
        for i, (u0, s, rows) in enumerate(STAGE_LINES):
            if rows:
                chord_line(mask, u0, s, rows, x_seal, x_end - END_COLLAR)
            else:
                ends = (x_seal,) + tuple(x_seal + (x_end - x_seal) * f for f in splices) + (x_end - END_COLLAR,)
                for j, (a, b) in enumerate(zip(ends, ends[1:])):
                    if (i + j + k) % 3 != 0:
                        chord_line(mask, u0, s, rows, a + 0.035, b - 0.035)
        for f in splices:
            rib(mask, x_seal + (x_end - x_seal) * f)
        for dx in ((1.1, 2.7, 4.0, 6.2, 7.6, 9.5) if k == 0 else (1.5, 3.3, 4.6, 6.6, 8.4, 10.0)):
            rib(mask, x_seal + dx, 0.65, 1.01, rows=False)
        # the witness line, low-vis
        cv.paint(cv.coverage(np.abs(X - (x_seal + 0.1)), RED_LINE) * mask * WITNESS_TINT, rgb=RED)
        for uu in (0.3, 0.5):  # index arrows pointing outboard, read against the seal when fully extended
            arrow = [(x_seal + 0.2, uu * chord - 0.07), (x_seal + 0.2, uu * chord + 0.07), (x_seal + 0.34, uu * chord)]
            cv.paint(cv.fill_coverage(poly_sdf(X, S, arrow)) * mask * up, rgb=STENCIL)
        for dx, u, wx, ws_, r, s in STAGE_PANELS[k]:
            panel(mask, x_seal + dx, u, wx, ws_, r, s)
        for dx, u in ((0.55, 0.16), (1.15, 0.16), (0.7, 0.65), (1.4, 0.65)):
            panel(mask, x_seal + dx + 0.12 * k, u, 0.28 if u < 0.3 else 0.34, 0.14, 0.015, 1)
        placard(cv, mask * up, X, S - 0.62 * chord, x_seal + 0.7, 0.3, 0.08)
        placard(cv, mask * up, X, S - 0.40 * chord, x_seal + 0.55, 0.25, 0.10)
        # stage 2's outer end is the tip's neck, under the cuff: only stage 1's end shows a seal band, extended
        collar(cv, mask, X, S, x_end - END_COLLAR, x_end, seal=k == 0)

    # ---- tip: two skin bays, then the dielectric cap carrying the lights ----
    x_cuff, x_far = fam["tip"].xs[0], fam["tip"].xs[-1]
    x_cap = x_cuff + TIP_CAP_F * (x_far - x_cuff)
    chord_line(TP, 0.15, 0, 1, x_cuff + END_COLLAR, x_cap)
    chord_line(TP, 0.65, 0, 1, x_cuff + END_COLLAR, x_cap)
    rib(TP, (x_cuff + END_COLLAR + x_cap) / 2, rows=True)
    cv.groove(np.abs(X - x_cap), 0.02, mask=TP)
    cv.fasteners(np.abs(X - x_cap), S, 0.03, mask=TP * (np.abs(X - x_cap) < 0.06))
    cv.paint(TP * smoothstep(x_cap, x_cap + 0.01, X), rgb=(0.33, 0.335, 0.34), smooth=0.5)
    xa, xb = formation_span(fam["tip"].xs)  # a thin dark mounting rim round the formation strip
    _, u0, _, width = FORMATION
    sdf = rrect_sdf(X, S, xa - 0.025, xb + 0.025, u0 * C - 0.025, u0 * C + width + 0.025, 0.015)
    cv.paint(cv.fill_coverage(sdf) * TP * up, rgb=DARK, smooth=0.3)
    collar(cv, TP, X, S, x_cuff, x_cuff + END_COLLAR - 0.04)

    # ---- end caps: a rubber seal round the stage passing through, satin metal outside it ----
    for cap, child in ((CAP_ROOT, 0), (CAP_STAGE1, 1), (CAP_STAGE2, 1), (CAP_CUFF, 1)):
        m = cls == cap
        if not m.any():
            continue
        coords = fam[("t1", "t2")[child]]
        a, b = section_plane(coords, pos[m])
        seal = np.zeros(cv.n)
        seal[m] = np.clip(0.5 - (np.abs(poly_sdf(a, b, stage_outline(bl, child))) - SEAL) / cv.px, 0, 1)
        cv.paint(m.astype(float), **SATIN)
        cv.paint(seal, rgb=RUBBER, smooth=0.3, metal=0.0)
        aa, bb = np.zeros(cv.n), np.zeros(cv.n)
        aa[m], bb[m] = a, b
        edge = np.zeros(cv.n)
        edge[m] = np.abs(poly_sdf(a, b, stage_outline(bl, child)) - 0.025)
        cv.fasteners(edge, aa + bb, 0.0, mask=m * (edge < 0.025))
        chord = bl.TELE[child][1]
        drain = np.hypot(aa - chord - 0.10, bb + 0.018)
        cv.paint(cv.fill_coverage(drain - 0.012) * m, rgb=DARK, height=-0.003)
        placard(cv, m, aa, bb - 0.04, chord + 0.16, 0.12, 0.065)

    # ---- control surfaces ----
    F, A, SP, FR = on(FLAP), on(AILERON), on(SPOILER), on(FAIRING)
    for pattern, xa, xb, kind in bl.SURFACES:
        mask = (F if kind == "flap" else A if kind == "aileron" else SP) * (X > xa - 0.05) * (X < xb + 0.05)
        pitch = {"flap": 0.55, "aileron": 0.5, "spoiler": 0.6}[kind]
        # a skin splice with its fastener rows on every third rib (a joint on every rib read as a barcode from above)
        for i, x in enumerate(np.arange(xa + pitch, xb - 0.2, pitch)):
            if i % 3 == 2:
                rib(mask, x, 0.0, 1.01, rows=True)
            else:  # an intermediate rib shows as its rivet row, not a joint: joints both ways read as a square grid
                cv.fasteners(np.abs(X - x), S, 0.025, mask=mask * (np.abs(X - x) < 0.06))
        if kind == "spoiler":
            t0, t1 = bl.SPOILER_CHORD[0], paint_spoiler_te(X, C)
            sdf = rrect_sdf(X, S, xa + 0.03, xb - 0.03, t0 * C + 0.03, t1 * C - 0.03, 0.03)
            cv.groove(np.abs(sdf), mask=mask)
            cv.groove(np.abs(X - (xa + xb) / 2), 0.02, mask=mask)
            for x in (xa + 0.55, (xa + xb) / 2, xb - 0.55):
                panel(mask, x, t0 + 0.1 / C, 0.14, 0.14, 0.015, 1)
        else:
            hinge = bl.FLAP_HINGE if kind == "flap" else None
            u_nose = (hinge + 0.06) if hinge else (0.25 * C + bl.AILERON_HINGE_BEHIND_QC + 0.05) / np.maximum(C, 1e-3)
            chord_line(mask, u_nose, 0, 1)
            chord_line(mask, u_nose + 0.4 * (1 - u_nose), 0, 0)  # a light lap, no rivets, so ribs cross no joint
            chord_line(mask, 0.955, 0, 1)
            rub = mask * up * ((X < xa + 0.055) | (X > xb - 0.055))
            cv.paint(rub, **SATIN)
            cv.paint(mask * smoothstep(0.965, 0.975, U), rgb=(0.30, 0.305, 0.31))
    for x, flap in CANOES:  # actuator access panels on the flaps' undersides, by each fairing
        panel(F * lo, x + 0.4, 0.88, 0.35, 0.25, 0.05, -1)
        panel(F, x, 0.82, 0.26, 0.16, 0.015, 1)
    xa, xb = next((a, b) for _, a, b, kind in bl.SURFACES if kind == "aileron")
    for x in np.linspace(xa + 0.6, xb - 0.6, 4):
        u = float(paint_lip_edge(x, upper=False)) + 0.06
        panel(A, x, u, 0.22, 0.13, 0.015, -1)
    # fairings: a joint ring round each with its fasteners, the attach flange along the wing skin, the drain hole at
    # the bottom
    coords = fam["root"]
    th = np.interp(np.abs(pos[:, 0]), coords.xs, [root_section(bl, 1)(float(x))[2] for x in coords.xs])
    t = np.clip(U, 0.0, 1.0)
    yt = 5 * th * (0.2969 * np.sqrt(t) - 0.1260 * t - 0.3516 * t ** 2 + 0.2843 * t ** 3 - 0.1036 * t ** 4)
    yt = yt + 0.006 * C * t
    yc = bl.WING_CAMBER * C * 4 * t * (1 - t)
    rise = section_plane(coords, pos)[1] - (yc - yt)
    for x, flap in CANOES:
        near = FR * (np.abs(X - x) < 0.3)
        for off in (-1.8, -1.35):  # the nose cap's joint and a frame ahead of the split
            le_u = bl.FLAP_HINGE + off / np.maximum(C, 1e-3)
            cv.groove(np.abs(S - le_u * C), mask=near)
            cv.fasteners(np.abs(S - le_u * C), X + pos[:, 2], 0.025, mask=near * (np.abs(S - le_u * C) < 0.06))
        flange = near * (U < 0.99)
        cv.groove(np.abs(rise + 0.03), mask=flange)
        cv.fasteners(np.abs(rise + 0.015), S, 0.0, mask=flange * (np.abs(rise + 0.015) < 0.02))
        cv.groove(np.abs(X - x), 0.012, mask=near * lo * (np.abs(X - x) < 0.03))

    # NO STEP on flap 1 behind the walkway, reading from the walkway on either wing (flap_R1 keeps its own islands)
    img = text_mask("NO STEP")
    flap1 = next((a, b) for pattern, a, b, kind in bl.SURFACES if pattern.endswith("1"))
    across = np.where(neg, -1.0, 1.0)
    for x in NO_STEP:
        stamp(cv, img, across * (X - x), S - 0.79 * C, 48 / NO_STEP_H, F * up * (X > flap1[0]) * (X < flap1[1]), STENCIL)


def collar(cv, mask, X, S, x0, x1, seal=False):
    """A satin metal band round a stage end, bordered by joints with fastener rows; seal: a parent's end, whose outer
    edge carries the black rubber band the stage slides through (detail_telescope_joint.png), which reads beside the
    tip's cuff when retracted. Edges anti-aliased: a hard step stair-stepped across the texels on the swept end."""
    np = cv.xp
    edge = lambda a, b: np.clip(0.5 + (X - a) / cv.px, 0, 1) * np.clip(0.5 + (b - X) / cv.px, 0, 1)
    band = mask * edge(x0, x1)
    cv.paint(band, **SATIN)
    for x in (x0, x1 - 0.03):
        cv.groove(np.abs(X - x), mask=mask)
    if seal:
        x1 -= SEAL_BAND
        # no outer edge: the band ends with the part, and anti-aliasing there half-covered the last texels of the swept
        # end, a row of satin flecks in the seal
        cv.paint(mask * np.clip(0.5 + (X - x1) / cv.px, 0, 1), rgb=RUBBER, smooth=0.3, metal=0.0)
        cv.groove(np.abs(X - x1), mask=mask)
    cv.fasteners(np.abs(X - (x0 + x1) / 2), S, 0.035, mask=band)


def placard(cv, mask, X, V, x, wx, wv):
    """A plain ruled placard centred at (x, V = 0): a low-vis plate with rules for its lines of print, which read the
    same either way round (V in metres along the chord)."""
    np = cv.xp
    from .paint import rrect_sdf
    sdf = rrect_sdf(X, V, x - wx / 2, x + wx / 2, -wv / 2, wv / 2, 0.006)
    plate = cv.fill_coverage(sdf) * mask
    cv.paint(plate, rgb=PLACARD[0], smooth=0.36)
    rows = cv.coverage(np.abs(((V + wv / 2) % 0.03) - 0.015), 0.01) * (np.abs(V) < wv / 2 - 0.015)
    cv.paint(plate * rows * (np.abs(X - x) < wx / 2 - 0.03), rgb=PLACARD[1])


def stamp(cv, img, U, V, px_per_m, mask, rgb):
    """Stamp a raster (rows bottom-up, 1 = ink) centred at U = V = 0, U along the text and V up, in metres: the
    engines group's stamp (Canvas.decal works in the fuselage's station and girth)."""
    np = cv.xp
    img = np.asarray(img)
    f = int(px_per_m * cv.px / 1.5)  # box-filter the raster down to about 1.5 pixels a texel
    if f >= 2:
        hh, ww = (img.shape[0] // f) * f, (img.shape[1] // f) * f
        img = img[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
        px_per_m /= f
    h, w = img.shape
    lu, lv = U * px_per_m + w / 2, V * px_per_m + h / 2
    inside = (lu >= 0) & (lu < w - 1) & (lv >= 0) & (lv < h - 1) & (mask > 0)
    cov = np.zeros(cv.n)
    x, y = lu[inside], lv[inside]
    x0, y0 = x.astype(int), y.astype(int)
    tx, ty = x - x0, y - y0
    cov[inside] = (img[y0, x0] * (1 - tx) * (1 - ty) + img[y0, x0 + 1] * tx * (1 - ty)
                   + img[y0 + 1, x0] * (1 - tx) * ty + img[y0 + 1, x0 + 1] * tx * ty)
    cv.paint(cov * mask, rgb=rgb)


def stage_outline(bl, k, scale=1.0):
    """The stage's section outline in its own plane: (chordwise, thickness-wise) metres from its leading edge."""
    _, chord, _, _ = bl.TELE[k]
    thick = stage_thickness(bl, k)
    pts = bl.airfoil(Vector(), chord * scale, thick * scale, bl.CDIR, bl.TDIR, bl.WING_CAMBER, n=STAGE_N)
    return [(p.dot(bl.CDIR), p.dot(bl.TDIR)) for p in pts]


def families(bl):
    """Paint coordinates of each section family, left side, stages retracted."""
    rows = tip_table(bl, 1)[0]
    return {
        "root": af.SectionCoords(root_section(bl, 1), np.linspace(0.0, bl.X_ROOT_TIP + 0.5, 90)),
        "t1": af.SectionCoords(stage_section(bl, 1, bl.TELE[0][1], stage_thickness(bl, 0)), (8.0, 22.0)),
        "t2": af.SectionCoords(stage_section(bl, 1, bl.TELE[1][1], stage_thickness(bl, 1)), (8.0, 22.0)),
        "tip": af.SectionCoords(af.table_section(bl, rows), [r[0] for r in rows]),
    }
