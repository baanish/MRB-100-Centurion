"""Part group 7: the landing gear. gear_F (the nose leg) with wheel_F (its two wheels), gear_LM/RM (each main leg, its
sleeve and its leg door) with wheel_LM/RM (the six-wheel bogie: beam, axles, piston, wheels and brakes). The right-hand
parts are the left's mirrored face for face.

The gear stands in its rest pose, down. Gear and wheels take the Centurion_gear slot, laid out on the group's own gear
trim (TRIM: tyre tread and sidewall, brake stack and hub unrolled round their axes, flat swatches for paint, satin
piston, steel and the rest); the leg doors' outer skin and edges and the legs' sleeves take Centurion_skin, the doors'
inner structure aircraft_structure; the nose leg's lamps take glass and its drag brace jet_mechanical, as the well's
upper brace link does (m4/nose.py).

Retraction, which check() models and the game folds the same way (CenturionAuthor.Gear.cs): the nose leg swings forward
and up about the blockout's hinge (gear_F's origin, a lateral axis) into the nose well; each main leg swings inboard and up
about gear_LM's origin (a longitudinal axis inside the sponson, under the bump its skin swells into: struts.HINGE_BUMP)
while its shrink link draws the shock strut closed, so the bogie lies in the sponson and the body beside the well. The
leg's sleeve fills the slot in the bump the leg hangs through, and the leg door closes the outboard part of the well
opening that the main door (struts group) leaves, up to the sleeve.

Positions are world (x, y, z) with y = bl.st(station); the left side is built and the right mirrored."""

import math
from contextlib import contextmanager

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import nose, struts
from . import surface as sf
from . import texture as tx
from .paint import PAINT, SMOOTH, poly_sdf, seg_dist, smoothstep
from .surface import DOOR

GROUP = "gear"
PARTS = ("gear_F", "wheel_F", "gear_LM", "wheel_LM", "gear_RM", "wheel_RM")
BUDGET_TRIS = 17500  # Lead's budget calls: 17,500 in round 2; round 4 adds 400 from the aircraft's spare for the nose
# tyres' rounded shoulders (384); 400 to the struts group for the hinge bump that replaced the legs' trunnion fairings.
MIRROR_PARTS = {"gear_RM": "gear_LM", "wheel_RM": "wheel_LM"}
GROUND_PARTS = ("wheel_F", "wheel_LM", "wheel_RM")  # on the runway on their tyres (the entry script's envelope)
# Close-ups (m4/render.py's view form); the first four make the contact sheet.
VIEWS = {  # on the right side, which the review sun (ahead, right, above) lights
    "main34": (35, (-8.2, 21.0, 1.0), (-3.5, 25.4, 1.3)),
    "nose_front": (45, (-1.3, -2.0, 0.75), (0.0, 6.0, 1.05)),  # between the open nose doors
    "main_front": (55, (-2.6, 13.5, 0.9), (-3.5, 25.5, 1.25)),
    "bogie": (30, (-6.0, 22.6, 0.5), (-3.7, 25.3, 0.8)),
    "nose34": (40, (-3.8, 1.2, 1.1), (0.0, 5.9, 1.0)),
    "main_side": (("ortho", 7.5, (90, 0, -90)), (-30.0, 25.5, 1.7), None),
    "nose_side": (("ortho", 4.5, (90, 0, -90)), (-30.0, 5.6, 1.4), None),
    "main_low": (30, (-6.0, 22.0, -1.2), (-3.2, 25.5, 1.6)),  # under the ground (hidden): the well and bogie from below
    "nose_low": (30, (-1.6, 3.2, -1.0), (0.0, 5.6, 1.7)),
}

# Paint classes (m4/paint.py: other groups from 11 up). The leg door's outer skin and the sleeve are painted on the
# group's canvas; the rest name what a gear face does when the leg retracts (check()), and the tyres.
GEAR_LEG, GEAR_FIXED, LEG_DOOR, DOOR_STRUCT, HOUSING, TYRE = 21, 23, 24, 25, 26, 27

# The blockout's gear (build_centurion.build_gear): the nose pair 0.8 m apart with 0.55 m tyres, the main bogie's six
# 1.2 m wheels in pairs 0.84 m apart on axles 1.4 m apart; CenturionAuthor gives the game the same wheel radii.
NOSE_WHEEL_X, MAIN_WHEEL_X = 0.40, 0.42
MAIN_AXLES = (-1.4, 0.0, 1.4)
WHEEL_SEG = 48
# Wheel profiles, (radius, height along the axle away from the leg), outer hub face, tyre, inner face, with the trim
# zone of each band. Tyre sections are aircraft radials: a flat ribbed crown, rounded shoulders, a bulged sidewall.
MAIN_WHEEL = ((0.0, 0.112), (0.29, 0.055), (0.375, 0.170),
              (0.51, 0.182), (0.60, 0.09), (0.60, -0.09), (0.51, -0.182),
              (0.375, -0.170), (0.0, -0.225))
MAIN_ZONES = ("hub", "hub", "sidewall", "tread", "tread", "tread", "sidewall", "brake")
NOSE_WHEEL = ((0.0, 0.095), (0.255, 0.045), (0.335, 0.142),
              (0.464, 0.152), (0.528, 0.130), (0.55, 0.075), (0.55, -0.075), (0.528, -0.130), (0.464, -0.152),
              (0.335, -0.142), (0.0, -0.115))
NOSE_ZONES = ("hub", "hub", "sidewall", "tread", "tread", "tread", "tread", "tread", "sidewall", "alloy")

# Main leg: the shock strut's axis runs from the hinge, inside the sponson, to its foot FOOT_OUT outboard of the
# bogie's centre on the bogie's pivot pin, between the middle wheels' brakes, so the strut rakes outboard as it goes
# down and the bogie and the wheels stay put; the bogie beam keeps the blockout's centre between the wheel rows.
FOOT_OUT = 0.03
MAIN_CYL_R, MAIN_PISTON_R = 0.165, 0.15
MAIN_GLAND_Z = 1.56  # the main cylinder's gland nut, the piston's top seal
# The leg's sleeve: a body of revolution about the hinge axis, SLEEVE_SINK under the hinge bump's round section, which
# shows in the leg's slot (struts.LEG_SLOT) and so looks the same at any angle of the leg; it runs SLEEVE_OVERLAP past
# the slot's ends under the bump, and closes in cones of SLEEVE_END. It takes the livery skin, painted as the leg door
# (a trim swatch read as a grey patch on a painted sponson). It turns with the leg, so the faces that show with the
# gear up lie in the well at rest: the slot's top wall runs round them (struts.SLOT_WALL), or the bury pass would seal
# them, and the composite bakes its AO with the legs stowed too (stowed, STOWED_AO_CLASSES), each face taking the pose
# it shows in.
SLEEVE_SINK, SLEEVE_OVERLAP, SLEEVE_END = 0.005, 0.04, 0.1
# Retraction (check()): angles about the hinges, and the shock strut's closure on the main legs.
NOSE_RETRACT_DEG = 128.0
MAIN_RETRACT_DEG = 120.0  # past level inboard, so the bogie rides up into the body clear of the aft bay
MAIN_SHRINK = 0.5  # no more than the piston shows below the gland (MAIN_GLAND_Z less the foot's 1.03 m)
FIT_MARGIN = 0.03  # retracted gear at least this far inside its well or the airframe

# ---------- gear trim ----------
# One 1024 sheet for the Centurion_gear slot. Polar zones run the full width and unroll round a wheel's axis (u round
# the axis, v across the profile: arc length for the tread and brake, radius for the sidewall and hub); the rest are
# 128 px swatches.
TRIM_PX = 1024
TRIM_UV = "UVGear"  # the trim's UVs while the entry script's UV pass runs; trim() moves them into UVMap
CELL = 0.125


def _cell(col, row):
    return (col * CELL, row * CELL, (col + 1) * CELL, (row + 1) * CELL)


ZONES = {"tread": (0.0, 0.0, 1.0, 0.125), "sidewall": (0.0, 0.125, 1.0, 0.25), "brake": (0.0, 0.25, 1.0, 0.3125),
         "hub": (0.0, 0.3125, 1.0, 0.4375), "lens": (0.0, 0.4375, 1.0, 0.5),
         "paint": _cell(0, 4), "piston": _cell(1, 4), "dark": _cell(2, 4), "steel": _cell(3, 4),
         "hydro": _cell(5, 4), "lamp": _cell(6, 4), "alloy": _cell(7, 4),
         "placard": (0.0, 0.625, 0.25, 0.6875)}
POLAR = {"tread": "arc", "sidewall": "radius", "brake": "arc", "hub": "radius", "lens": "radius"}
# Swatches: sRGB albedo, metal, smoothness. Gear legs in a light grey over the airframe's mid grey; every bare fitting
# (piston, pins, lines) the wing's one satin metal (rule 2: no chrome); hubs a painted mid grey, which the hub zone
# shares, so at game distance they stay under the legs' value; actuators dark.
SATIN_SWATCH = (struts.SATIN[0], struts.SATIN[2], struts.SATIN[1])
SWATCH = {"paint": ((0.56, 0.57, 0.58), 0.05, 0.46), "piston": SATIN_SWATCH,
          "dark": ((0.17, 0.175, 0.18), 0.30, 0.38), "steel": SATIN_SWATCH, "hydro": SATIN_SWATCH,
          "lamp": ((0.82, 0.82, 0.80), 0.05, 0.60), "alloy": ((0.47, 0.47, 0.48), 0.05, 0.50)}
SIDEWALL_TEXT = "MRB AERO   52 x 21.0 R22   36 PLY   TUBELESS   RIB"
PLACARD_TEXT = ("SHOCK STRUT", "N2 1450 PSI", "MIL-PRF-5606")


class GearPart(sf.Part):
    """A part with a UVMap (first, which the entry's unwrap and box projection fill) and the trim's own UV layer."""

    def __init__(self, name, slots, bm=None):
        super().__init__(name, slots)
        if bm is not None:  # a mirrored copy
            self.bm.free()
            self.bm = bm
            self.cls = bm.faces.layers.int["cls"]
        else:
            self.bm.loops.layers.uv.new("UVMap")
            self.bm.loops.layers.uv.new(TRIM_UV)
        self.uv = self.bm.loops.layers.uv[TRIM_UV]
        self.gear = slots[0]

    def flat(self, faces, zone, slot=None, cls=GEAR_LEG):
        """Faces onto one swatch: each face's own box projection fitted inside the swatch (the placard stretched
        over it)."""
        self.tag(faces, slot or self.gear, cls)
        u0, v0, u1, v1 = ZONES[zone]
        for f in faces:
            f.normal_update()
            ax = max(range(3), key=lambda i: abs(f.normal[i]))
            a, b = (i for i in range(3) if i != ax)
            pts = [(l.vert.co[a], l.vert.co[b]) for l in f.loops]
            lo = (min(p[0] for p in pts), min(p[1] for p in pts))
            ext = (max(max(p[0] for p in pts) - lo[0], 1e-6), max(max(p[1] for p in pts) - lo[1], 1e-6))
            for l, (pa, pb) in zip(f.loops, pts):
                if zone == "placard":
                    l[self.uv].uv = (u0 + (u1 - u0) * (pa - lo[0]) / ext[0], v0 + (v1 - v0) * (pb - lo[1]) / ext[1])
                else:
                    k = 0.8 * (u1 - u0) / max(ext)
                    l[self.uv].uv = (u0 + 0.1 * (u1 - u0) + (pa - lo[0]) * k, v0 + 0.1 * (v1 - v0) + (pb - lo[1]) * k)
        return faces


def mirror_part(src, name):
    """The right-hand twin: the left part's mesh mirrored across x = 0, face for face. Unrolled zones flip their u, so
    sidewall text still reads from outside."""
    bm = src.bm.copy()
    bmesh.ops.transform(bm, matrix=Matrix.Scale(-1, 4, (1, 0, 0)), verts=bm.verts)
    for f in bm.faces:
        f.normal_flip()
    p = GearPart(name, src.slots, bm)
    for f in bm.faces:
        for l in f.loops:
            u, v = l[p.uv].uv
            if v < ZONES["hub"][3]:
                l[p.uv].uv = (-u, v)
    return p


def lathe(p, profile, centre, axis, ref, seg, zones, cls=GEAR_LEG, slot=None, flip_u=False, zone_cls=None):
    """surface.revolve_axis with trim UVs: (radius, height) points spun about axis through centre, a zero radius at
    either end a pole, otherwise a flat cap; zones[b] is the trim zone of the band from point b to b + 1, zone_cls a
    paint class per zone over cls."""
    zone_cls = zone_cls or {}
    slot = slot or p.gear
    ax = axis.normalized()
    e1 = (ref - ax * ref.dot(ax)).normalized()
    e2 = ax.cross(e1)
    bm = p.bm
    V = []
    for r, h in profile:
        c = centre + ax * h
        count = seg(r) if callable(seg) else seg
        ring = [(math.cos(2 * math.pi * i / count), math.sin(2 * math.pi * i / count)) for i in range(count)]
        V.append(bm.verts.new(c) if r == 0 else [bm.verts.new(c + (e1 * cs + e2 * sn) * r) for cs, sn in ring])
    # each band's parameter at its two ends, per zone run (consecutive bands of one zone)
    tb, b = [None] * (len(profile) - 1), 0
    while b < len(tb):
        e = b
        while e + 1 < len(tb) and zones[e + 1] == zones[b]:
            e += 1
        pts = profile[b:e + 2]
        if POLAR.get(zones[b]) == "radius":
            rs = [q[0] for q in pts]
            lo, hi = min(rs), max(rs)
            ts = [(q[0] - lo) / max(hi - lo, 1e-6) for q in pts]
        else:
            d = [0.0]
            for q0, q1 in zip(pts, pts[1:]):
                d.append(d[-1] + math.hypot(q1[0] - q0[0], q1[1] - q0[1]))
            ts = [x / max(d[-1], 1e-6) for x in d]
        for k in range(b, e + 1):
            tb[k] = (ts[k - b], ts[k - b + 1])
        b = e + 1
    flat = {}
    for b, z in enumerate(zones):
        A, B = V[b], V[b + 1]
        na, nb = len(A) if isinstance(A, list) else 1, len(B) if isinstance(B, list) else 1
        count = max(na, nb)
        t0, t1 = tb[b]
        u0, v0, u1, v1 = ZONES[z]
        side = profile[b][1] + profile[b + 1][1]
        flip = -1.0 if (flip_u != (z == "sidewall" and side > 0)) else 1.0

        def uv(i, t):
            return (flip * i / count, v0 + (v1 - v0) * t)
        for i in range(count):
            ia, ja = i * na // count, (i + 1) * na // count
            ib, jb = i * nb // count, (i + 1) * nb // count
            if isinstance(A, list) and isinstance(B, list):
                corners = [(A[ia % na], uv(ia * count / na, t0))]
                if ia != ja:
                    corners.append((A[ja % na], uv(ja * count / na, t0)))
                corners.append((B[jb % nb], uv(jb * count / nb, t1)))
                if ib != jb:
                    corners.append((B[ib % nb], uv(ib * count / nb, t1)))
                f = bm.faces.new([v for v, _ in corners])
                coords = [c for _, c in corners]
            elif isinstance(B, list):
                f = bm.faces.new((B[jb % nb], B[ib], A))
                coords = (uv(i + 1, t1), uv(i, t1), uv(i + 0.5, t0))
            else:
                f = bm.faces.new((A[ia], A[ja % na], B))
                coords = (uv(i, t0), uv(i + 1, t0), uv(i + 0.5, t1))
            if z in POLAR:
                p.tag([f], slot, zone_cls.get(z, cls))
                for l, c in zip(f.loops, coords):
                    l[p.uv].uv = c
            else:
                flat.setdefault(z, []).append(f)
    for end, z in ((V[0], zones[0]), (V[-1], zones[-1])):
        if isinstance(end, list):
            faces = sf.cap(bm, end[::-1] if end is V[0] else end)
            flat.setdefault(z if z not in POLAR else "dark", []).extend(faces)
    for z, faces in flat.items():
        p.flat(faces, z, slot, zone_cls.get(z, cls))


def rod(p, a, b, r, zone, seg=8, cls=GEAR_LEG, slot=None):
    """A capped round bar from a to b on a swatch."""
    return p.flat(sf.tube(p, [a, b], r, seg, slot or p.gear), zone, slot, cls)


def block(p, centre, axes, size, zone, cls=GEAR_LEG, slot=None):
    return p.flat(sf.box(p, centre, axes, size, slot or p.gear), zone, slot, cls)


def actuator(p, a, b, r_body, r_rod, split=0.58, cls=GEAR_LEG):
    """A hydraulic actuator from a (its body's end) to b (its rod's eye): dark body, satin rod, steel end eyes."""
    m = a + (b - a) * split
    rod(p, a, m + (b - a) * 0.03, r_body, "dark", 12, cls)
    rod(p, m - (b - a) * 0.05, b, r_rod, "piston", 10, cls)
    for q in (a, b):
        rod(p, q - Vector((r_body * 0.8, 0, 0)), q + Vector((r_body * 0.8, 0, 0)), r_rod * 1.15, "steel", 8, cls)


X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))


def wheel(p, centre, out, profile, zones, flip_u=False):
    """One wheel and tyre about an axle along x; out points away from the leg (the hub's outer face). The tyre's
    faces are TYRE, which the envelope stands on the runway."""
    first = set(p.bm.faces)
    lathe(p, profile, centre, out, Z, WHEEL_SEG,
          zones, flip_u=flip_u, zone_cls={"tread": TYRE, "sidewall": TYRE})
    faces = [f for f in p.bm.faces if f not in first]
    # A stem must share the wheel shell or Unity leaves it on the stationary bogie.
    face = next(f for f in faces if len(f.verts) == 4 and all(
        profile[1][0] - 1e-5 < (v.co - centre - out * (v.co - centre).dot(out)).length < profile[2][0] + 1e-5
        and (v.co - centre).dot(Z) > 0.2 and (v.co - centre).dot(out) > 0 for v in f.verts))
    ring = list(face.verts)
    base = sum((v.co for v in ring), Vector()) / len(ring)
    p.bm.faces.remove(face)
    foot = [p.bm.verts.new(base + (v.co - base) * 0.12) for v in ring]
    tip = [p.bm.verts.new(v.co + out * 0.025) for v in foot]
    for i in range(len(ring)):
        j = (i + 1) % len(ring)
        p.flat([p.bm.faces.new((ring[i], ring[j], foot[j], foot[i]))], "alloy")
        p.flat([p.bm.faces.new((foot[i], foot[j], tip[j], tip[i]))], "steel")
    p.flat([p.bm.faces.new(tip)], "dark")
    soft = p.bm.edges.layers.int.get("soft") or p.bm.edges.layers.int.new("soft")
    for f in faces:
        if f.is_valid and f[p.cls] == TYRE:
            for edge in f.edges:
                edge[soft] = 1


# ---------- nose gear ----------
def build_nose(bl, leg, wheels, slots):
    SKIN, STRUCT, GLASS, MECH = slots[:4]
    P = bpy.data.objects["gear_F"].matrix_world.translation.copy()
    A = bpy.data.objects["wheel_F"].matrix_world.translation.copy()
    zt = P.z  # the trunnion
    # trunnion pin across the well, its ends in the well's bearing blocks (m4/nose.py); turns about its own axis
    rod(leg, P - X * 0.62, P + X * 0.62, 0.05, "steel", 12, GEAR_FIXED)
    block(leg, P + Vector((0, 0, -0.035)), (X, Y, Z), (0.30, 0.17, 0.13), "paint")
    # shock strut: cylinder with the steering collar at its foot, the satin piston, the axle's foot block
    lathe(leg, ((0.0, zt - 0.05), (0.095, zt - 0.05), (0.10, zt - 0.09), (0.10, 1.14), (0.13, 1.13), (0.13, 1.04),
                (0.085, 1.03), (0.0, 1.03)), Vector((0, P.y, 0)), Z, X, 16,
          ("paint", "paint", "paint", "dark", "dark", "dark", "dark"))
    lathe(leg, ((0.0, 1.06), (0.068, 1.06), (0.068, 0.75), (0.0, 0.75)), Vector((0, P.y, 0)), Z, X, 16,
          ("piston", "piston", "piston"))
    lathe(leg, ((0.0, A.z + 0.22), (0.085, A.z + 0.22), (0.105, A.z + 0.15),
                (0.105, A.z), (0.065, A.z - 0.02), (0.0, A.z - 0.02)),
          Vector((0, A.y, 0)), Z, X, 24, ("paint", "paint", "paint", "paint", "paint"))
    rod(leg, A - X * 0.30, A + X * 0.30, 0.06, "steel", 12)
    # torque links ahead of the strut, steering actuators on its front quarters
    knee = Vector((0, P.y - 0.27, 0.90))
    for a, b in ((Vector((0, P.y - 0.11, 1.05)), knee), (knee, Vector((0, P.y - 0.08, 0.73)))):
        d = (b - a).normalized()
        block(leg, (a + b) / 2, (X, d, X.cross(d)), (0.07, (b - a).length + 0.04, 0.035), "paint")
    rod(leg, knee - X * 0.05, knee + X * 0.05, 0.022, "steel", 8)
    for sx in (1, -1):
        actuator(leg, Vector((sx * 0.105, P.y - 0.08, 1.36)), Vector((sx * 0.105, P.y - 0.07, 1.10)), 0.028, 0.016)
    # taxi light over two landing lights on a bar across the strut's front, aimed a little down
    block(leg, Vector((0, P.y - 0.15, 1.22)), (X, Y, Z), (0.44, 0.05, 0.05), "dark")
    aim = Vector((0, -1, -0.07)).normalized()
    for x, z, r in ((0.0, 1.31, 0.055), (0.17, 1.22, 0.065), (-0.17, 1.22, 0.065)):
        c = Vector((x, P.y - 0.17, z))
        lathe(leg, ((0.0, -0.02), (r, -0.02), (r * 1.06, 0.06), (r * 0.9, 0.075), (0.0, 0.065)), c, aim, Z, 32,
              ("dark", "dark", "steel", "lens"))
        lathe(leg, ((0.0, 0.064), (r * 0.14, 0.064), (r * 0.16, 0.088), (0.0, 0.094)),
              c, aim, Z, 12, ("lamp", "lamp", "lamp"))
        up = (Z - aim * Z.dot(aim)).normalized()
        across = aim.cross(up)
        rings = [[c + aim * h + (up * math.cos(2 * math.pi * i / 32)
                  + across * math.sin(2 * math.pi * i / 32)) * rr for i in range(32)]
                 for rr, h in ((r * 0.9, 0.074), (r * 0.86, 0.080), (r * 0.84, 0.074))]
        lens = sf.Grid(leg.bm, rings)
        glass = lens.faces() + [leg.bm.faces.new((lens.V[-1][i], lens.V[-1][(i + 1) % 32],
                                                lens.V[0][(i + 1) % 32], lens.V[0][i])) for i in range(32)]
        leg.tag(glass, GLASS, GEAR_LEG)
    # servicing placard on the cylinder's left side
    faces = block(leg, Vector((0.104, P.y + 0.01, 1.30)), (X, Y, Z), (0.008, 0.11, 0.06), "dark")
    leg.flat([f for f in faces if f.calc_center_median().x > 0.107], "placard")
    # drag brace: the lower link rides the leg to the knee in the well, where the upper link (the well's) takes it
    knee_d = nose.DRAG_KNEE
    kd = Vector((0, bl.st(knee_d[0]), knee_d[1]))
    lug = Vector((0, P.y - 0.10, 1.30))
    leg.tag(sf.tube(leg, [lug, kd], 0.045, 10, MECH), MECH, GEAR_LEG)
    leg.tag(sf.tube(leg, [kd - X * 0.09, kd + X * 0.09], 0.05, 10, MECH), MECH, GEAR_LEG)
    leg.tag(sf.box(leg, lug + Vector((0, 0.02, 0)), (X, Y, Z), (0.08, 0.1, 0.09), MECH), MECH, GEAR_LEG)
    for q in (lug, kd):
        for dx in (-0.065, 0.065):
            block(leg, q + X * dx, (X, Y, Z), (0.04, 0.11, 0.10), "paint")
    lock = kd.lerp(lug, 0.24) + Z * 0.055
    rod(leg, kd, lock, 0.03, "paint", 10)
    rod(leg, lock, kd.lerp(lug, 0.42), 0.03, "paint", 10)
    actuator(leg, P + Vector((0.10, -0.10, -0.10)), lock + X * 0.10, 0.027, 0.015)
    actuator(leg, P + Vector((-0.15, -0.08, -0.08)), lug + Vector((-0.15, 0.08, 0.08)), 0.035, 0.018)
    # hydraulic lines down the strut's right side to the steering collar
    for dx in (0.0, 0.035):
        rod(leg, Vector((-0.115 - dx, P.y + 0.03, zt - 0.06)), Vector((-0.115 - dx, P.y + 0.03, 1.15)), 0.012, "hydro", 6)

    for sx in (1, -1):
        wheel(wheels, A + X * (sx * NOSE_WHEEL_X), X * sx, NOSE_WHEEL, NOSE_ZONES, flip_u=sx < 0)


# ---------- main gear ----------
def main_frame(bl):
    """The left main gear's hinge (gear_LM's origin) and bogie centre (wheel_LM's), world."""
    return (bpy.data.objects["gear_LM"].matrix_world.translation.copy(),
            bpy.data.objects["wheel_LM"].matrix_world.translation.copy())


def strut_axis(P, B, side=1):
    """A main shock strut's axis: the unit vector from its foot (FOOT_OUT outboard of the bogie's centre B, on the
    bogie's pivot pin) up to the hinge P."""
    return (P - Vector((B.x + side * FOOT_OUT, B.y, B.z + 0.27))).normalized()


def retract_main(points, P, side, angle=MAIN_RETRACT_DEG, lift=Vector()):
    """Points of a main gear in its rest pose, carried to the retracted pose: moved by lift (the shock strut closing,
    along its axis), then swung inboard and up about the hinge axis."""
    m = Matrix.Translation(P) @ Matrix.Rotation(side * math.radians(angle), 4, "Y") @ Matrix.Translation(-P)
    return [m @ (q + lift) for q in points]


def leg_door_ribs():
    """Stations of the leg door's three ribs."""
    s0, s1 = struts.WELL_S[0] + 0.03, struts.WELL_S[1] - 0.03
    return [s0 + (s1 - s0) * k / 10 for k in (1, 5, 9)]


def gap_phi(SP, s, phi, gap):
    """The ray angle gap metres along the skin from phi (toward larger phi for a positive gap) at station s."""
    step = (Vector(SP.local(s, phi + 0.5)) - Vector(SP.local(s, phi))).length / 0.5  # metres of skin per degree
    return phi + gap / step


def leg_door_rows():
    """The leg door's stations: its ends and chamfers, the ribs and the bracket feet."""
    s0, s1 = struts.WELL_S[0] + 0.03, struts.WELL_S[1] - 0.03
    cl = struts.LEG_DOOR_CHAMFER[0]
    return sorted({s0 + (s1 - s0) * i / 10 for i in (0, 1, 4, 5, 6, 9, 10)} | {s0 + cl, s1 - cl})


def leg_door_edges(SP, s):
    """The leg door's inboard and outboard edges at station s, as the sponson's ray angles: DOOR_GAP inside the main
    door's free edge (out over its tabs at the door's ends) and inside the well's outboard edge."""
    s0, s1 = struts.WELL_S[0] + 0.03, struts.WELL_S[1] - 0.03
    cl, cx = struts.LEG_DOOR_CHAMFER
    x_in = struts.DOOR_X[1] + struts.DOOR_GAP + cx * max(0.0, 1 - (s - s0) / cl, 1 - (s1 - s) / cl)
    return SP.phi_for_x(s, x_in, 140.0, 215.0), gap_phi(SP, s, SP.well_edges(s)[0], struts.DOOR_GAP)


# The leg door's tab over the leg's slot runs this far down under the door (its skin TAB_UNDER under the door's) and
# up to the leg's sleeve, DOOR_GAP inside the slot's ends; its own closed shell, so its ends are square slab sides.
TAB_OVERLAP, TAB_UNDER = 0.03, 0.0005


def leg_tab_rows(SP):
    """The tab's stations: its ends, DOOR_GAP inside the slot's, and the hinge's."""
    h, half = SP.hinge[2], struts.LEG_SLOT["half_len"] - struts.DOOR_GAP
    return [h - half, h, h + half]


def leg_tab_edges(SP, s):
    """The tab's lower and upper edges at station s, as ray angles: TAB_OVERLAP under the leg door's outboard edge,
    and DOOR_GAP short of the sleeve's lower line (the band's, struts.LEG_SLOT)."""
    return (gap_phi(SP, s, leg_door_edges(SP, s)[1], TAB_OVERLAP),
            gap_phi(SP, s, SP.hinge_phi(s, struts.LEG_SLOT["band_deg"][0]), struts.DOOR_GAP))


def door_slab(SP, leg, rows, edges, nv, outer, slots):
    """A door panel over the sponson's skin between edges(s) (ray angles, larger first) on each of rows: columns spread
    by arc length and turning (struts.spread_columns), its skin outer metres off the sponson's. Returns the faces, the
    points and the normals."""
    SKIN, STRUCT = slots[0], slots[1]
    pts, nrm = [], []
    for s in rows:
        a, b = edges(SP, s)
        phis = struts.spread_columns(SP, s, [a + (b - a) * j / nv for j in range(nv + 1)], 0, nv, 96)
        row_p = [SP.point(s, ph) for ph in phis]
        if not all(q1.x > q0.x for q0, q1 in zip(row_p, row_p[1:])):
            raise ValueError(f"leg door row at {s} folds across its chamfer")
        pts.append(row_p)
        nrm.append([SP.normal(s, ph) for ph in phis])
    top, bottom, sides = sf.slab(leg, pts, nrm, outer, outer - struts.DOOR_T, SKIN, STRUCT, cls=LEG_DOOR,
                                 cls_rest=DOOR_STRUCT)
    leg.tag(sides, SKIN, LEG_DOOR)  # the edges show in the gaps round the closed door, as struts.build_door's
    return top + bottom + sides, pts, nrm


def leg_door(bl, leg, P, slots):
    """The leg door: built closed over the outboard part of the well opening (from the main door's free edge to the
    well's outboard edge, flush with the sponson) with its tab over the leg's slot up to the sleeve, then carried down
    with the leg into the rest pose. Outer skin on Centurion_skin with its edges, inner face and stiffeners on
    aircraft_structure; two brackets tie it to the strut."""
    STRUCT = slots[1]
    SP = struts.Sponson(bl, 1)
    s0, s1 = struts.WELL_S[0] + 0.03, struts.WELL_S[1] - 0.03
    rows = leg_door_rows()
    ribs = [rows.index(s) for s in leg_door_ribs()]
    nv = 8
    faces, pts, nrm = door_slab(SP, leg, rows, leg_door_edges, nv, 0.0, slots)
    faces += door_slab(SP, leg, leg_tab_rows(SP), leg_tab_edges, 6, -TAB_UNDER, slots)[0]
    for i in ribs:
        faces += struts.door_stiffener(leg, pts, nrm, 0, i, 0.05, 0.06, STRUCT, DOOR_STRUCT)
    beam = nv // 3
    faces += struts.door_stiffener(leg, pts, nrm, 1, beam, 0.06, 0.06, STRUCT, DOOR_STRUCT)
    sf.rotate_about(leg, faces, P, Y, -math.radians(MAIN_RETRACT_DEG))
    # bracket feet on the door's inner beam, carried down with it
    feet = [rows.index(s0 + (s1 - s0) * k / 10) for k in (4, 6)]
    feet = retract_main([pts[i][beam] - nrm[i][beam] * (struts.DOOR_T + 0.06) for i in feet], P, 1, -MAIN_RETRACT_DEG)
    return feet


def build_main(bl, leg, bogie, slots):
    SKIN, STRUCT = slots[0], slots[1]
    P, B = main_frame(bl)
    u = strut_axis(P, B)  # up the strut, raking inboard to the hinge
    c0 = Vector((P.x - u.x * P.z / u.z, P.y, 0.0))  # the axis at ground height
    at = lambda z: c0 + u * (z / u.z)  # the axis at height z
    ax = lambda prof: [(r, z / u.z) for r, z in prof]  # a lathe profile's heights as lengths along the axis
    n = Vector((u.z, 0.0, -u.x))  # square to the axis, outboard
    # the sleeve round the trunnion, under the hinge bump, coaxial with the hinge so it never moves
    r = struts.HINGE_BUMP["r"] - SLEEVE_SINK
    half = struts.LEG_SLOT["half_len"] + SLEEVE_OVERLAP
    leg.tag(sf.revolve_axis(leg, [(0.0, -half - SLEEVE_END), (r, -half), (r, half), (0.0, half + SLEEVE_END)],
                            P, Y, 32, SKIN, ref=X), SKIN, HOUSING)
    # shock strut cylinder from the hinge (its top turns on the trunnion there, inside the sleeve), gland nut at its foot
    nut = MAIN_CYL_R + 0.012
    lathe(leg, ax(((0.0, P.z), (0.12, P.z), (MAIN_CYL_R, P.z - 0.04),
                   (MAIN_CYL_R, MAIN_GLAND_Z + 0.07), (nut, MAIN_GLAND_Z + 0.06), (nut, MAIN_GLAND_Z),
                   (MAIN_PISTON_R + 0.005, MAIN_GLAND_Z - 0.01), (0.0, MAIN_GLAND_Z - 0.01))), c0, u, n, 24,
          ("paint", "paint", "paint", "steel", "steel", "steel", "steel"))
    z_drag, z_act = 1.72, 1.84  # the existing brace and actuator eye heights
    for dz in (z_drag,):
        lathe(leg, ax(((MAIN_CYL_R - 0.01, dz - 0.04), (MAIN_CYL_R + 0.012, dz - 0.03), (MAIN_CYL_R + 0.012, dz + 0.03),
                       (MAIN_CYL_R - 0.01, dz + 0.04))), c0, u, n, 24, ("paint", "paint", "paint"))
    # drag strut forward and retraction actuator aft, from the trunnion's ends on the hinge axis to the strut
    fwd_top, aft_top = P + Y * -0.74 + Z * -0.02, P + Y * 0.74 + Z * -0.02
    eye = at(z_drag) + Y * (-MAIN_CYL_R - 0.01)
    rod(leg, fwd_top, eye, 0.055, "paint", 12)
    rod(leg, eye - n * 0.06, eye + n * 0.06, 0.035, "steel", 8)
    actuator(leg, aft_top, at(z_act) + Y * (MAIN_CYL_R + 0.02), 0.07, 0.04)
    # upper torque link
    knee = at(1.3) + Y * -0.38
    a = at(MAIN_GLAND_Z + 0.02) + Y * -0.13
    d = (knee - a).normalized()
    block(leg, (a + knee) / 2, (n, d, n.cross(d)), (0.12, (knee - a).length + 0.05, 0.06), "paint")
    for q in (a, knee):
        rod(leg, q - n * 0.08, q + n * 0.08, 0.035, "steel", 16)
    # hydraulic lines down the strut's aft face
    for dx in (-0.04, 0.0):
        side = Y * (MAIN_CYL_R + 0.015) + n * dx
        rod(leg, at(P.z - 0.12) + side, at(1.50) + side, 0.014, "hydro", 6)
    # placard on the strut's outboard face
    c = at(1.80)
    faces = block(leg, c + n * (MAIN_CYL_R + 0.004), (n, Y, u), (0.008, 0.13, 0.07), "dark")
    leg.flat([f for f in faces if (f.calc_center_median() - c).dot(n) > MAIN_CYL_R + 0.007], "placard")
    # the leg door, and its brackets from the strut
    for foot, dy in zip(leg_door(bl, leg, P, slots), (-0.09, 0.09)):  # a V of two short arms from a collar lug
        root = at(1.9) + n * (MAIN_CYL_R + 0.01) + Y * dy
        rod(leg, root, foot, 0.04, "paint", 10)
        block(leg, root, (n, Y, u), (0.07, 0.06, 0.09), "paint")

    # ---- bogie (wheel_LM): beam, pivot boss, axles, piston, lower torque link, brake rods, pitch trimmer
    bx = B.x
    ring = [(-1, -0.6), (-0.6, -1), (0.6, -1), (1, -0.6), (1, 0.6), (0.6, 1), (-0.6, 1), (-1, 0.6)]
    sections = ((-1.66, 0.075, 0.09, 0.10), (-1.4, 0.095, 0.12, 0.13), (-0.6, 0.11, 0.12, 0.14), (0.0, 0.12, 0.12, 0.28),
                (0.6, 0.11, 0.12, 0.14), (1.4, 0.095, 0.12, 0.13), (1.66, 0.075, 0.09, 0.10))
    rings = []
    for dy, w, lo, hi in sections:
        rings.append([Vector((bx + w * u, B.y + dy, B.z + (hi if v > 0 else lo) * v)) for u, v in ring])
    g = sf.Grid(bogie.bm, rings)
    faces = g.faces() + sf.cap(bogie.bm, g.V[0][::-1]) + sf.cap(bogie.bm, g.V[-1])
    bogie.flat(faces, "paint")
    for dy in MAIN_AXLES:
        c = Vector((bx, B.y + dy, B.z))
        rod(bogie, c - X * MAIN_WHEEL_X, c + X * MAIN_WHEEL_X, 0.075, "steel", 10)
        rod(bogie, c - X * 0.16, c + X * 0.16, 0.12, "paint", 12)
    pin = Vector((bx, B.y, B.z + 0.27))
    rod(bogie, pin - X * 0.15, pin + X * 0.15, 0.055, "steel", 10)
    lathe(bogie, ax(((0.0, 1.03), (0.115, 1.03), (0.13, 1.0), (0.13, 0.86), (0.0, 0.86))), c0, u, n, 18,
          ("paint", "paint", "paint", "paint"))
    lathe(bogie, ax(((0.0, MAIN_GLAND_Z + 0.12), (MAIN_PISTON_R, MAIN_GLAND_Z + 0.12), (MAIN_PISTON_R, 1.02), (0.0, 1.02))),
          c0, u, n, 24, ("piston", "piston", "piston"))
    a = at(1.02) + Y * -0.12
    d = (knee - a).normalized()
    block(bogie, (a + knee) / 2, (X, d, X.cross(d)), (0.12, (knee - a).length + 0.05, 0.06), "paint")
    for dy in MAIN_AXLES:
        for sx in (-1, 1):
            hub = Vector((bx + sx * (MAIN_WHEEL_X - 0.27), B.y + dy, B.z + 0.25))
            rod(bogie, hub, Vector((bx + sx * 0.11, B.y + dy + 0.22, B.z + 0.2)), 0.02, "steel", 5)
    actuator(bogie, at(0.98) + Y * -0.14, Vector((bx, B.y - 1.05, B.z + 0.1)), 0.045, 0.025)
    for dy in MAIN_AXLES:
        for sx in (-1, 1):
            wheel(bogie, Vector((bx + sx * MAIN_WHEEL_X, B.y + dy, B.z)), X * sx, MAIN_WHEEL, MAIN_ZONES, flip_u=sx < 0)


def build(bl, surf, slots):
    gear = bl.GEAR
    parts = {n: GearPart(n, (gear,)) for n in ("gear_F", "wheel_F", "gear_LM", "wheel_LM")}
    build_nose(bl, parts["gear_F"], parts["wheel_F"], slots)
    build_main(bl, parts["gear_LM"], parts["wheel_LM"], slots)
    for name in ("gear_F", "gear_LM"):
        p = parts[name]
        p.bm.normal_update()
        for edge in p.bm.edges:
            if len(edge.link_faces) != 2 or edge.link_faces[0][p.cls] != edge.link_faces[1][p.cls]:
                edge.seam = True
        bmesh.ops.dissolve_limit(p.bm, angle_limit=math.radians(2.0), verts=p.bm.verts[:], edges=p.bm.edges[:],
                                delimit={"SEAM", "MATERIAL"})
    parts["gear_RM"] = mirror_part(parts["gear_LM"], "gear_RM")
    parts["wheel_RM"] = mirror_part(parts["wheel_LM"], "wheel_RM")
    return parts


# ---------- trim sheet ----------
def _text_strip(mask, width, height):
    """The text raster resampled to height rows (bottom-up) and its own width scaled to match, padded to width."""
    h, w = mask.shape
    k = height / h
    cols = max(1, int(w * k))
    ys = np.clip((np.arange(height) + 0.5) / k, 0, h - 1).astype(int)
    xs = np.clip((np.arange(cols) + 0.5) / k, 0, w - 1).astype(int)
    out = np.zeros((height, width))
    out[:, :min(cols, width)] = mask[ys][:, xs][:, :width]
    return out


def trim_sheet():
    """The gear trim as arrays, rows bottom-up: albedo (sRGB), metal, smoothness and height (metres), and the texel
    densities along u and v that turn height into the normal map."""
    S = TRIM_PX
    alb = np.zeros((S, S, 3))
    metal = np.zeros((S, S))
    smooth = np.full((S, S), 0.4)
    height = np.zeros((S, S))
    du, dv = np.full((S, S), 300.0), np.full((S, S), 300.0)
    rng = np.random.default_rng(7)

    def rows(zone):
        u0, v0, u1, v1 = ZONES[zone]
        return slice(int(v0 * S), int(v1 * S)), slice(int(u0 * S), int(u1 * S))

    def along_u(n, scale):
        x = rng.normal(size=n)
        k = np.exp(-0.5 * (np.arange(-3 * scale, 3 * scale + 1) / scale) ** 2)
        return np.convolve(np.concatenate([x[-3 * scale:], x, x[:3 * scale]]), k / k.sum(), "same")[3 * scale:-3 * scale]

    # tread: four circumferential grooves on the crown, worn crown lighter than the shoulders
    rs, cs = rows("tread")
    n = rs.stop - rs.start
    t = (np.arange(n) + 0.5) / n
    crown = smoothstep(0.20, 0.26, t) * smoothstep(0.80, 0.74, t)
    groove = sum(np.clip(1.5 - np.abs(t - c) / 0.016, 0, 1) for c in (0.339, 0.446, 0.554, 0.661))
    wear = along_u(S, 24) * 0.012
    alb[rs, cs] = (0.10 + 0.025 * crown[:, None] - 0.045 * groove[:, None] + wear[None, :] * crown[:, None])[..., None]
    smooth[rs, cs] = (0.26 - 0.1 * crown)[:, None]
    height[rs, cs] = (-0.008 * groove)[:, None]
    du[rs, cs], dv[rs, cs] = S / (2 * math.pi * 0.6), n / 0.335
    # sidewall: rim line, shoulder line, moulded lettering
    rs, cs = rows("sidewall")
    n = rs.stop - rs.start
    t = (np.arange(n) + 0.5) / n
    rings = np.clip(1.5 - np.abs(t - 0.07) / 0.012, 0, 1) - np.clip(1.5 - np.abs(t - 0.9) / 0.01, 0, 1)
    text = _text_strip(tx.text_mask(SIDEWALL_TEXT), S // 2, int(n * 0.24))
    band = np.zeros((n, S))
    r0 = int(n * 0.40)
    band[r0:r0 + text.shape[0]] = np.tile(text, (1, 2))[:, :S]
    alb[rs, cs] = (0.09 + 0.014 * band + 0.01 * rings[:, None])[..., None]
    smooth[rs, cs] = 0.32 - 0.06 * band
    height[rs, cs] = 0.0015 * rings[:, None] + 0.0008 * band
    du[rs, cs], dv[rs, cs] = S / (2 * math.pi * 0.47), n / 0.185
    # brake stack: rotor and stator discs, heat tint toward the hot end
    rs, cs = rows("brake")
    n = rs.stop - rs.start
    t = (np.arange(n) + 0.5) / n
    discs = 0.5 + 0.5 * np.cos(2 * math.pi * t * 7)
    tint = np.stack([0.32 - 0.04 * t, 0.28 - 0.06 * t, 0.25 - 0.02 * t], axis=-1)
    alb[rs, cs] = (tint * (0.8 + 0.2 * discs[:, None]))[:, None, :]
    metal[rs, cs], smooth[rs, cs] = struts.SATIN[2], 0.32
    height[rs, cs] = (0.0025 * discs)[:, None]
    du[rs, cs], dv[rs, cs] = S / (2 * math.pi * 0.28), n / 0.086
    # hub: painted mid grey with a satin cap and lip, the nut, bolt circle, tie bolts near the rim
    rs, cs = rows("hub")
    n = rs.stop - rs.start
    t = ((np.arange(n) + 0.5) / n)[:, None]
    u = ((np.arange(S) + 0.5) / S)[None, :]
    cap = smoothstep(0.27, 0.24, t)
    lip = smoothstep(0.92, 0.95, t)
    pr = 0.375  # the main hub's rim radius; the nose's is close enough
    bolts = np.zeros((n, S))
    for tc, count, rad in ((0.38, 12, 0.012), (0.85, 16, 0.009)):
        circ = 2 * math.pi * tc * pr
        du_m = (np.abs(((u * count) % 1.0) - 0.5) / count) * circ  # metres along the circle to the nearest bolt
        dt_m = np.abs(t - tc) * pr
        bolts = np.maximum(bolts, np.clip(1.5 - np.hypot(du_m, dt_m) / rad, 0, 1))
    groove = np.clip(1.5 - np.abs(t - 0.62) / 0.012, 0, 1)
    (base, base_m, base_s), (bare, bare_m, bare_s) = SWATCH["alloy"], SATIN_SWATCH
    col = np.array(base) * (1 - cap - lip)[..., None] + np.array(bare) * (cap + lip)[..., None]
    col = col * (1 - 0.25 * groove)[..., None] * (1 - 0.15 * bolts)[..., None]
    nut = smoothstep(0.09, 0.07, t)
    col = col * (1 - 0.6 * nut)[..., None]
    alb[rs, cs] = col
    metal[rs, cs] = (base_m + (bare_m - base_m) * (cap + lip)) * np.ones((1, S))
    smooth[rs, cs] = (base_s + (bare_s - base_s) * (cap + lip)) * np.ones((1, S))
    height[rs, cs] = 0.004 * bolts - 0.003 * groove + 0.01 * nut
    du[rs, cs] = S / (2 * math.pi * np.maximum(t * pr, 0.03)) * np.ones((1, S))
    dv[rs, cs] = n / pr
    # lamp lens: the reflector seen through a clear cover, its faint concentric prism rings catching the light and a
    # darker seat where the cover meets the bezel, so the lamp reads as glass over a mirror rather than a flat plate
    rs, cs = rows("lens")
    n = rs.stop - rs.start
    t = (np.arange(n) + 0.5) / n
    prism = 0.5 + 0.5 * np.cos(2 * math.pi * t * 5)
    seat = np.clip(1.5 - np.abs(t - 0.94) / 0.025, 0, 1)
    alb[rs, cs] = (0.80 - 0.10 * t - 0.015 * prism - 0.45 * seat)[:, None, None]
    metal[rs, cs], smooth[rs, cs] = 0.4, (0.92 - 0.3 * seat)[:, None]
    height[rs, cs] = (0.00008 * prism)[:, None]
    du[rs, cs], dv[rs, cs] = S / (2 * math.pi * 0.03), n / 0.06
    # swatches
    for zone, (rgb, m, sm) in SWATCH.items():
        rs, cs = rows(zone)
        alb[rs, cs], metal[rs, cs], smooth[rs, cs] = rgb, m, sm
    # placard: a dark plate, a light rule and three lines of service text
    rs, cs = rows("placard")
    h, w = rs.stop - rs.start, cs.stop - cs.start
    plate = np.full((h, w), 0.0)
    plate[2:4, 2:-2] = plate[-4:-2, 2:-2] = 1.0
    plate[2:-2, 2:4] = plate[2:-2, -4:-2] = 1.0
    for k, line in enumerate(PLACARD_TEXT):
        strip = _text_strip(tx.text_mask(line), w - 16, 14)
        r = h - 8 - 16 * (k + 1)
        plate[r:r + 14, 8:w - 8] = np.maximum(plate[r:r + 14, 8:w - 8], strip)
    alb[rs, cs] = (0.13 + 0.65 * plate)[..., None]
    smooth[rs, cs] = 0.35
    du[rs, cs], dv[rs, cs] = w / 0.13, h / 0.07
    return alb, metal, smooth, height, du, dv


def write_trim(folder):
    """The trim's albedo, metal-smoothness and normal PNGs. Returns their paths."""
    alb, metal, smooth, height, du, dv = trim_sheet()
    gy, gx = np.gradient(height)
    nx, ny = -gx * du, -gy * dv
    L = np.sqrt(nx * nx + ny * ny + 1)
    nrm = np.stack([nx / L, ny / L, 1 / L], axis=-1) * 0.5 + 0.5
    ms = np.concatenate([np.repeat(metal[..., None], 3, axis=2), smooth[..., None]], axis=2)
    folder.mkdir(parents=True, exist_ok=True)
    return {"albedo": tx.save_image(alb, folder / "gear_trim_b.png", srgb=True),
            "metal_smooth": tx.save_image(ms, folder / "gear_trim_m.png"),
            "normal": tx.save_image(nrm, folder / "gear_trim_n.png")}


def wire_trim(mat, maps):
    """The trim's maps into the Centurion_gear material's Principled BSDF (links override the flat look the review
    sets on it); the albedo node active, which Workbench shows."""
    nt = mat.node_tree
    for n in [n for n in nt.nodes if n.name.startswith("gear_trim")]:
        nt.nodes.remove(n)
    bsdf = nt.nodes["Principled BSDF"]
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.name, uv.uv_map = "gear_trim_uv", "UVMap"

    def tex(key, data=True):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.name = f"gear_trim_{key}"
        t.image = tx.load_image(maps[key], data=data)
        nt.links.new(uv.outputs["UV"], t.inputs["Vector"])
        return t
    alb, ms, nrm = tex("albedo", data=False), tex("metal_smooth"), tex("normal")
    nt.links.new(alb.outputs["Color"], bsdf.inputs["Base Color"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.name = "gear_trim_sep"
    nt.links.new(ms.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.name, inv.operation = "gear_trim_rough", "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(ms.outputs["Alpha"], inv.inputs[1])
    nt.links.new(inv.outputs["Value"], bsdf.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.name, nm.uv_map = "gear_trim_nm", "UVMap"
    nt.links.new(nrm.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    nt.nodes.active = alb


def trim(bl, objs, folder):
    """The entry script's trim hook, after its UV pass box-projects the trims: the gear trim's UVs into UVMap on every
    Centurion_gear face, its maps written into folder and wired into the material. Returns the check."""
    laid = {}
    for name, o in objs.items():
        me = o.data
        if TRIM_UV not in me.uv_layers:
            continue
        src, dst = me.uv_layers[TRIM_UV].data, me.uv_layers["UVMap"].data
        gear = [i for i, m in enumerate(me.materials) if m.name == bl.GEAR]
        n = 0
        for p in me.polygons:
            if p.material_index in gear:
                for li in p.loop_indices:
                    dst[li].uv = src[li].uv
                n += 1
        me.uv_layers.remove(me.uv_layers[TRIM_UV])
        laid[name] = n
    wire_trim(bpy.data.materials[bl.GEAR], write_trim(folder))
    gear_faces = {n: sum(1 for p in o.data.polygons if o.data.materials[p.material_index].name == bl.GEAR)
                  for n, o in objs.items()}
    return {"value": laid, "limit": "every Centurion_gear face on the gear trim",
            "pass": all(laid.get(n, 0) == c for n, c in gear_faces.items())}


# ---------- checks ----------
def world_faces(o):
    """World vertices, polygons and each polygon's paint class."""
    me = o.data
    mw = o.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    cls = np.zeros(len(me.polygons), np.int32)
    me.attributes["cls"].data.foreach_get("value", cls)
    return verts, [tuple(p.vertices) for p in me.polygons], cls


def nose_fit(bl, objs):
    """The nose leg and wheels swung forward about gear_F's hinge into the well: every vertex inside the well's walls,
    ends and ceiling and above the closed doors' inner faces and stiffeners (nose.gear_door_floor), by FIT_MARGIN;
    no face through the well's own structure (the trunnion pin, which turns in its bearings, aside)."""
    P = objs["gear_F"].matrix_world.translation.copy()
    m = Matrix.Translation(P) @ Matrix.Rotation(-math.radians(NOSE_RETRACT_DEG), 4, "X") @ Matrix.Translation(-P)
    worst, where, verts, polys = 1e9, None, [], []
    for name in ("gear_F", "wheel_F"):
        v, f, cls = world_faces(objs[name])
        base = len(verts)
        moved = [m @ q for q in v]
        verts += moved
        polys += [tuple(base + i for i in poly) for poly, c in zip(f, cls) if c != GEAR_FIXED]
        for q in moved:
            s = q.y + bl.Y0
            room = min(nose.WELL_X - abs(q.x), s - nose.WELL_S[0], nose.WELL_S[1] - s,
                       q.z - (bl.fus_bottom_z(s, abs(q.x)) + nose.gear_door_floor(s, abs(q.x))),
                       nose.well_ceiling(s) - q.z)
            if room < worst:
                worst, where = room, (round(q.x, 2), round(s, 2), round(q.z, 2), name)
    tree = BVHTree.FromPolygons(verts, polys)
    nv, nf = bl.world_mesh(bpy.data.objects["nose"])
    clash = len(tree.overlap(BVHTree.FromPolygons(nv, nf)))
    return {"value": {"least_room_m": round(worst, 3), "at": where, "faces_through_well_structure": clash,
                      "retract_deg": NOSE_RETRACT_DEG},
            "limit": f"{FIT_MARGIN} m inside the well (doors closed), nothing through its structure",
            "pass": worst >= FIT_MARGIN and clash == 0}


def main_fit(bl, objs, sfx, side):
    """A main leg swung inboard about gear_LM's hinge with its strut closed by MAIN_SHRINK: every moving vertex but the
    sleeve's (the strut's top inside it included) inside the sponson or the body by FIT_MARGIN and clear of the aft
    bay's door line; the leg door's outer skin within 2 cm of the sponson's skin over the opening."""
    P = objs[f"gear_{sfx}"].matrix_world.translation.copy()
    lift = strut_axis(P, objs[f"wheel_{sfx}"].matrix_world.translation, side) * MAIN_SHRINK
    SP = struts.Sponson(bl, 1)
    bay = bl.BAYS[-1]
    depth, door_gap, bay_room = {}, 0.0, 1e9
    for name, shift in ((f"gear_{sfx}", Vector()), (f"wheel_{sfx}", lift)):
        v, f, cls = world_faces(objs[name])
        role = {}
        for poly, c in zip(f, cls):
            for i in poly:
                role.setdefault(i, set()).add(int(c))
        moved = retract_main(v, P, side, lift=shift)
        worst = (1e9, None)
        for i, (q0, q) in enumerate(zip(v, moved)):
            r = role.get(i, set())
            if r & {GEAR_FIXED, HOUSING}:
                continue
            s, x = q.y + bl.Y0, abs(q.x)
            d = SP.sdf(s, x, q.z)
            if LEG_DOOR in r and DOOR_STRUCT not in r:  # the outer skin; its edges' inner corners join the inner face
                door_gap = max(door_gap, abs(d))
                continue
            if -d < worst[0]:
                worst = (-d, [round(q.x, 2), round(s, 2), round(q.z, 2)])
            if bay[1] <= s <= bay[2]:
                bay_room = min(bay_room, x - abs(bl.fus_point(s, 141.0).x))
        depth[name] = {"least_depth_m": round(worst[0], 3), "at": worst[1]}
    least = min(d["least_depth_m"] for d in depth.values())
    return {"value": {**depth, "door_skin_gap_m": round(door_gap, 3), "aft_bay_clearance_m": round(bay_room, 3),
                      "retract_deg": MAIN_RETRACT_DEG, "shrink_m": MAIN_SHRINK},
            "limit": f"{FIT_MARGIN} m inside the sponson or body, door skin within 0.02 m, clear of the aft bay",
            "pass": least >= FIT_MARGIN and door_gap <= 0.02 and bay_room >= 0.05}


def rest_clear(bl, objs):
    """Gear down: no gear face through any other render part, except where a part is built into its mount (the main
    sleeves and strut tops through the well's structure round the hinge, though never through the sponson's skin; the
    nose trunnion in its bearings, the drag brace's knee)."""
    scene = {o.name: o for o in bpy.data.collections["Centurion"].all_objects
             if o.type == "MESH" and o.users_collection[0].name not in ("Colliders", "LOD1") and o.name not in objs}
    knee = Vector((0, bl.st(nose.DRAG_KNEE[0]), nose.DRAG_KNEE[1]))
    allowed = {"gear_LM": ("sponson_L",), "gear_RM": ("sponson_R",), "gear_F": ("nose",)}
    hits = {}
    for name, o in objs.items():
        v, f = bl.world_mesh(o)
        tree = BVHTree.FromPolygons(v, f)
        lo, hi = bl.bounds(v)
        P = o.matrix_world.translation
        for other, oo in scene.items():
            ov, of = bl.world_mesh(oo)
            olo, ohi = bl.bounds(ov)
            if not bl.boxes_touch((lo, hi), (olo, ohi), 0.01):
                continue
            skin = world_faces(oo)[2] == struts.SPONSON if "cls" in oo.data.attributes else np.zeros(len(of), bool)
            n, at = 0, None
            for i, j in tree.overlap(BVHTree.FromPolygons(ov, of)):
                c = sum((v[k] for k in f[i]), Vector()) / len(f[i])
                if other in allowed.get(name, ()):
                    near_hinge = (math.hypot(c.x - P.x, c.z - P.z) < struts.HINGE_BUMP["r"] + 0.12 and not skin[j]
                                  if name != "gear_F" else (c - P).length < 0.7 or (c - knee).length < 0.12)
                    if near_hinge:
                        continue
                n += 1
                at = [round(c.x, 2), round(c.y + bl.Y0, 2), round(c.z, 2)]
            if n:
                hits[f"{name}/{other}"] = {"faces": n, "at": at}
    return {"value": hits, "limit": "no gear face through another part away from its mounts", "pass": not hits}


def hinge_inside(bl, objs):
    """Each main leg's hinge axis inside the sponson's line without the bump over it (owner: "the hinge should be inside
    the plane") by FIT_MARGIN, along the trunnion from the drag strut's end to the actuator's."""
    SP = struts.Sponson(bl, 1)
    depth = {}
    for sfx in ("LM", "RM"):
        P = objs[f"gear_{sfx}"].matrix_world.translation
        s = P.y + bl.Y0
        depth[sfx] = round(min(-SP.sdf_plain(s + dy, abs(P.x), P.z) for dy in (-0.74, 0.0, 0.74)), 3)
    return {"value": {"depth_m": depth}, "limit": f"{FIT_MARGIN} m inside the sponson without its bump",
            "pass": all(d >= FIT_MARGIN for d in depth.values())}


STOWED_AO_CLASSES = (HOUSING,)  # the texels whose AO the composite also bakes with the main legs stowed


@contextmanager
def stowed(objs):
    """The main legs swung up as MAIN_RETRACT_DEG about their hinges (the bogies, their children, with them) while the
    composite bakes the AO of STOWED_AO_CLASSES; back down after."""
    rest = {sfx: objs[f"gear_{sfx}"].matrix_world.copy() for sfx in ("LM", "RM")}
    for (sfx, m), side in zip(rest.items(), (1, -1)):
        P = m.translation
        objs[f"gear_{sfx}"].matrix_world = (Matrix.Translation(P) @ Matrix.Rotation(side * math.radians(MAIN_RETRACT_DEG), 4, "Y")
                                           @ Matrix.Translation(-P) @ m)
    bpy.context.view_layer.update()
    try:
        yield
    finally:
        for sfx, m in rest.items():
            objs[f"gear_{sfx}"].matrix_world = m
        bpy.context.view_layer.update()


def check(bl, objs):
    return {"nose_gear_retracted": nose_fit(bl, objs),
            "main_hinge_inside": hinge_inside(bl, objs),
            "main_gear_L_retracted": main_fit(bl, objs, "LM", 1),
            "main_gear_R_retracted": main_fit(bl, objs, "RM", -1),
            "gear_down_clear": rest_clear(bl, objs),
            "doors_clear_spinning_tyres": door_tyre_clearance(bl, objs),
            "leg_doors_closed": leg_door_shells(objs)}


def leg_door_shells(objs):
    """The door skins, corner caps and stiffeners each remain closed after triangulation."""
    values = {}
    for name in ("gear_LM", "gear_RM"):
        bm = bmesh.new()
        bm.from_mesh(objs[name].data)
        cls = bm.faces.layers.int["cls"]
        faces = [f for f in bm.faces if f[cls] in (LEG_DOOR, DOOR_STRUCT)]
        bmesh.ops.triangulate(bm, faces=faces)
        edges = {e for f in bm.faces if f[cls] in (LEG_DOOR, DOOR_STRUCT) for e in f.edges}
        values[name] = sum(not e.is_manifold for e in edges)
        bm.free()
    return {"value": values, "limit": "zero open edges on each leg door", "pass": not any(values.values())}


def door_tyre_clearance(bl, objs):
    """Both door skins and ribs stay at least 5 cm outside the rotating tyre envelope."""
    values = {}
    for sfx, side in (("LM", "L"), ("RM", "R")):
        verts, faces, cls = world_faces(objs[f"gear_{sfx}"])
        door_faces = [f for f, c in zip(faces, cls) if c in (LEG_DOOR, DOOR_STRUCT)]
        door_vertices = {i for face in door_faces for i in face}
        door = BVHTree.FromPolygons(verts, door_faces)
        wv, wf, wc = world_faces(objs[f"wheel_{sfx}"])
        tyre_faces = [f for f, c in zip(wf, wc) if c == TYRE]
        tyre_vertices = {i for face in tyre_faces for i in face}
        tyres = BVHTree.FromPolygons(wv, tyre_faces)
        gap = min([tyres.find_nearest(verts[i])[3] for i in door_vertices]
                  + [door.find_nearest(wv[i])[3] for i in tyre_vertices])
        main = bpy.data.objects[f"geardoor_{sfx}_visible"]
        values[sfx] = {"leg_door_gap_m": round(gap, 3), "intersections": len(door.overlap(tyres)),
                       "main_door_gap_m": round(bl.min_distance(main, objs[f"wheel_{sfx}"]), 3)}
    return {"value": values, "limit": "at least 0.05 m from each spinning tyre, no intersections",
            "pass": all(v["leg_door_gap_m"] >= 0.05 and v["main_door_gap_m"] >= 0.05
                        and v["intersections"] == 0 for v in values.values())}


# ---------- paint (the leg doors' skin) ----------
RED = (0.55, 0.10, 0.08)
DARK = (0.10, 0.105, 0.11)


def paint(cv, text_mask):
    """In the left gear's frame: the bake writes whichever twin's texels it reaches last into their shared islands."""
    np = cv.xp
    bl = cv.coords.bl
    D = cv.on(LEG_DOOR, HOUSING).astype(float)
    cv.paint(D, rgb=PAINT[DOOR], smooth=SMOOTH[DOOR])
    P, _ = main_frame(bl)
    pos = np.column_stack([np.abs(cv.pos[:, 0]), cv.pos[:, 1], cv.pos[:, 2]])
    # the door in its closed frame: station along it, x across it (DOOR_X's)
    m = (Matrix.Translation(P) @ Matrix.Rotation(math.radians(MAIN_RETRACT_DEG), 4, "Y") @ Matrix.Translation(-P))
    R, t = np.array(m.to_3x3()), np.array(m.translation)
    q = pos @ R.T + t
    s, x = q[:, 1] + bl.Y0, q[:, 0]
    s0, s1 = struts.WELL_S[0] + 0.03, struts.WELL_S[1] - 0.03
    x0 = struts.DOOR_X[1] + struts.DOOR_GAP
    SP = struts.Sponson(bl, 1)
    door_x = lambda r, edges: SP.local(r, edges(SP, r)[1])[0]
    tab = leg_tab_rows(SP)
    outer = ([(r, door_x(r, leg_door_edges)) for r in reversed(leg_door_rows()) if r > tab[-1]]
             + [(tab[-1], door_x(tab[-1], leg_door_edges))] + [(r, door_x(r, leg_tab_edges)) for r in reversed(tab)]
             + [(tab[0], door_x(tab[0], leg_door_edges))]
             + [(r, door_x(r, leg_door_edges)) for r in reversed(leg_door_rows()) if r < tab[0]])  # up the tab
    cl, cx = struts.LEG_DOOR_CHAMFER
    free = [(s0, x0 + cx), (s0 + cl, x0), (s1 - cl, x0), (s1, x0 + cx)]
    edge = -poly_sdf(s, x, free + outer)
    # the sponson's skin carried across the closed door: its band tones and the laps on the pod's own (station, psi)
    ss, rows = struts.sponson_frame_table(bl)
    px, pz, a, b = (np.interp(s, ss, rows[:, i]) for i in range(4))
    psi = np.degrees(np.arctan2((x - px) / a, (pz - q[:, 2]) / b))
    r_eff = np.sqrt((a * a + b * b) / 2)
    cell = np.zeros(len(s), np.int64)
    for i, (p0, p1, splits) in enumerate(struts.SPONSON_BANDS):
        band = (psi >= p0) & (psi < p1)
        cell[band] = (i + 1) * 64 + np.searchsorted(np.array(sorted(struts.SPONSON_RINGS + splits)), s[band])
        cv.groove(np.abs(np.radians(psi - p1) * r_eff), mask=D * (edge > 0.02))
        for si in splits:
            cv.groove(np.abs(s - si), mask=D * band)
    cv.albedo *= (1 + 0.04 * (((cell * 2654435761) % 1000) / 1000.0 - 0.5) * D)[:, None]
    # the door's own: a red keep-clear line on its free edge only (the lowest, with the gear down), a fastener row round
    # the edge and on the ribs, a ruled placard (the right door's islands are this one's: no text)
    d_free = np.min([seg_dist(s, x, p, p1)[0] for p, p1 in zip(free, free[1:])], axis=0)
    cv.paint(D * (edge > 0) * cv.coverage(np.abs(d_free - 0.025), struts.RED_LINE), rgb=RED)
    cv.fasteners(np.abs(edge - 0.07), s + x, 0.0, mask=D * (np.abs(edge - 0.07) < 0.03))
    for si in leg_door_ribs():
        cv.fasteners(np.abs(s - si), x, 0.0, mask=D * (np.abs(s - si) < 0.03) * (edge > 0.1))
    struts.placard(cv, s, x, (s0 + 0.6, x0 + 0.42), (0.18, 0.1), D)
