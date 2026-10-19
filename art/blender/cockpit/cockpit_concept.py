"""Concept blockout of the Centurion's own flight deck (docs/COCKPIT-DESIGN.md), built inside a copy of the detailed
retracted composite and rendered for the owner's review. Nothing here ships; the game-side build comes later.

blender -b --factory-startup <copy of centurion_m4_retracted.blend> --python art/blender/cockpit/cockpit_concept.py --
    --out <absolute folder> --tag 08 [--variants a,b,c,d,w,o,e,x] [--samples 24] [--pitch 6]

Views: a, b, c, d are the pilot's eye on short final (3 deg path, 2,000 m out) with the panes only, per-seat forward
displays, today's eye with the nose hidden, and the panoramic screen; w the flight deck from its aft wall; o the
outside through the windscreen (glass made clear for this view only); e the escape hatches on the seats' rails; x the
crew door open. Pass an absolute --out: Blender resolves a relative one against its own working directory.

It refuses to run on a blend under art/ or .cache/art/: work on a copy (e.g. .cache/cockpit/base_retracted.blend), and
it never saves the scene. Coordinates are the composite's: Blender X positive is the aircraft's left, the nose points
to -Y, world Y = station - Y0, Z is height above the ground.

The cockpit view is mimicked as the game draws it: the nose and radome hide (they are Aircraft.exteriorRenderers), the
interior shows, so the world shows wherever the interior has an opening. The interior lining follows the outer skin
8 cm in, found by ray casts on the composite's own nose and forward fuselage, and opens wherever the skin is glass."""

import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

Y0 = 22.475
WALL = 0.08  # lining depth under the skin
EYE_S, EYE_X, EYE_Z = 6.55, 0.55, 5.00  # design eye, left seat (x outboard); the right seat mirrors
FLOOR_Z = 3.75  # raised flight deck floor, 1.25 m under the eye
DECK_S = (5.45, 6.95)  # floor and aft wall stations: the cabin ends at the nose part's joint (7.0), where fuselage_F's cap closes it
PANEL_S = 5.75  # instrument panel face, 0.75 m ahead of the eye
LINING_S = (3.95, 6.95, 0.05)  # lining rings: from, to, step
LINING_DEG = (-150.0, 150.0, 1.5)  # lining columns, angle from the top, positive to +X
AXIS_Z = 3.45  # the nose's approximate section centre, the lining's ray origin
FVD_AZ, FVD_LOW = 25.0, -22.0  # forward vision display: half width in azimuth, lowest elevation (deg)


def st(s):
    return s - Y0


# ---------------- the composite's exterior, for ray casts ----------------
class Skin:
    def __init__(self, names):
        dg = bpy.context.evaluated_depsgraph_get()
        self.trees = []
        for n in names:
            o = bpy.data.objects[n]
            me = o.evaluated_get(dg).to_mesh()
            vs = [o.matrix_world @ v.co for v in me.vertices]
            mats = [o.data.materials[p.material_index].name if p.material_index < len(o.data.materials) else "" for p in me.polygons]
            self.trees.append((BVHTree.FromPolygons(vs, [tuple(p.vertices) for p in me.polygons]), mats))

    def cast(self, origin, d):
        best = None
        for tree, mats in self.trees:
            h = tree.ray_cast(origin, d)
            if h[0] is not None and (best is None or h[3] < best[3]):
                best = (h[0], h[1], mats[h[2]], h[3])
        return best

    def radial(self, s, deg):
        """Outer skin point, outward normal and material at a station and an angle round the axis."""
        a = math.radians(deg)
        out = Vector((math.sin(a), 0, math.cos(a)))
        h = self.cast(Vector((0, st(s), AXIS_Z)) + out * 10, -out)
        if h is None:
            return None
        n = h[1] if h[1].dot(out) > 0 else -h[1]
        return h[0], n, h[2]

    def exits_glass(self, eye, d):
        """True when a ray from inside leaves the skin through glass (cast back from far along it)."""
        h = self.cast(eye + d * 40, -d)
        return h is None or h[2] == "glass" or h[3] > 39.95


def direction(az, el, side):
    """Unit vector from the eye: az outboard positive (side +1 is the left seat, +X), el up positive."""
    a, e = math.radians(az), math.radians(el)
    return Vector((side * math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def glass_floor(skin, eye, side, az):
    """Lowest elevation at this azimuth whose ray leaves through the real glass (60 if none below 60)."""
    for el10 in range(-350, 600, 5):
        if skin.exits_glass(eye, direction(az, el10 / 10, side)):
            return el10 / 10
    return 60.0


# ---------------- mesh helpers ----------------
def collection():
    coll = bpy.data.collections.get("cockpit_concept") or bpy.data.collections.new("cockpit_concept")
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    return coll


def new_object(name, bm, mat):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    collection().objects.link(o)
    return o


def material(name, rgb, rough=0.6, metal=0.0, emit=None, strength=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*rgb, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emit is not None:
        p.inputs["Emission Color"].default_value = (*emit, 1)
        p.inputs["Emission Strength"].default_value = strength
    return m


def box(bm, centre, size):
    r = bmesh.ops.create_cube(bm, size=1.0)
    for v in r["verts"]:
        v.co = Vector((centre[0] + v.co.x * size[0], centre[1] + v.co.y * size[1], centre[2] + v.co.z * size[2]))


# ---------------- the flight deck ----------------
def in_fvd(c, edges):
    """A point ahead of the panel inside either seat's forward vision display frustum."""
    if c.y > st(PANEL_S):
        return False
    for side in (1, -1):
        v = c - Vector((side * EYE_X, st(EYE_S), EYE_Z))
        az = math.degrees(math.atan2(side * v.x, -v.y))
        el = math.degrees(math.atan2(v.z, math.hypot(v.x, v.y)))
        if abs(az) <= FVD_AZ + 2 and FVD_LOW - 2 <= el <= interp_edge(edges[side], az) + 2:
            return True
    return False


def build_lining(skin, hide=None):
    """The lining 8 cm inside the skin from LINING_S, open wherever the skin is glass and below the deck floor, and,
    given the glass edges, inside the forward vision displays' frusta."""
    bm = bmesh.new()
    s0, s1, ds = LINING_S
    a0, a1, da = LINING_DEG
    rings = [s0 + ds * i for i in range(int(round((s1 - s0) / ds)) + 1)]
    cols = [a0 + da * j for j in range(int(round((a1 - a0) / da)) + 1)]
    grid = {}
    for i, s in enumerate(rings):
        for j, a in enumerate(cols):
            r = skin.radial(s, a)
            if r is not None:
                p, n, m = r
                grid[i, j] = (bm.verts.new(p - n * WALL), m == "glass")
    for i in range(len(rings) - 1):
        for j in range(len(cols) - 1):
            q = [grid.get(k) for k in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))]
            if any(c is None for c in q) or sum(c[1] for c in q) >= 2:
                continue
            zc = sum(c[0].co.z for c in q) / 4
            if zc < FLOOR_Z and rings[i] >= DECK_S[0] - 0.05:
                continue
            if zc < 3.3:
                continue
            if hide is not None and hide(sum((c[0].co for c in q), Vector()) / 4):
                continue
            bm.faces.new([c[0] for c in q])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def lining_half_width(skin, s, z):
    h = skin.cast(Vector((10, st(s), z)), Vector((-1, 0, 0)))
    return (h[0].x if h else 1.0) - WALL


def build_deck(skin):
    """The deck floor as a slab to the lining, and the aft wall as a cap on the lining's ring at the aft station."""
    bm = bmesh.new()
    w = lining_half_width(skin, 6.3, FLOOR_Z + 0.02)
    box(bm, (0, st((DECK_S[0] + DECK_S[1]) / 2), FLOOR_Z - 0.02), (2 * w, DECK_S[1] - DECK_S[0], 0.04))
    ring = []
    for k in range(73):
        r = skin.radial(DECK_S[1], -180 + 5 * k)
        if r is not None:
            p, n, _ = r
            q = p - n * WALL
            ring.append(Vector((q.x, st(DECK_S[1]), max(q.z, FLOOR_Z))))
    bm.faces.new([bm.verts.new(v) for v in ring])
    return bm


def panel_top(edges, x):
    """Height of the panel's top edge at x on the panel face: the glass's lower edge as the nearer eye sees it."""
    side = 1 if x >= 0 else -1
    dx = abs(x) - EYE_X
    d = EYE_S - PANEL_S
    az = math.degrees(math.atan2(dx, d))
    el = interp_edge(edges[side], az)
    return min(EYE_Z - 0.03, EYE_Z + math.hypot(dx, d) * math.tan(math.radians(el))), az


def interp_edge(edge, az):
    pts = sorted(edge.items())
    if az <= pts[0][0]:
        return pts[0][1]
    for (a0, e0), (a1, e1) in zip(pts, pts[1:]):
        if az <= a1:
            return e0 + (e1 - e0) * (az - a0) / (a1 - a0)
    return pts[-1][1]


def build_panel(skin, edges, mode):
    """The panel face at PANEL_S from just over the floor to the glass's lower edge ("a"), or cut for the per-seat FVD
    apertures ("b"). The panoramic band's panel is build_panel_curved."""
    bm = bmesh.new()
    y, bottom = st(PANEL_S), 3.85
    w = lining_half_width(skin, PANEL_S, 4.4)

    def top(x):
        zt, az = panel_top(edges, x)
        if mode == "b" and abs(az) <= FVD_AZ:
            return min(zt, EYE_Z + math.hypot(abs(x) - EYE_X, EYE_S - PANEL_S) * math.tan(math.radians(FVD_LOW)))
        return zt

    n = 160  # columns, each a quad from the bottom to the top edge at its own two sides
    xs = [-w + 2 * w * k / n for k in range(n + 1)]
    for x0, x1 in zip(xs, xs[1:]):
        t0, t1 = top(x0), top(x1)
        bm.faces.new([bm.verts.new(Vector(p)) for p in ((x0, y, bottom), (x1, y, bottom), (x1, y, t1), (x0, y, t0))])
    return bm


# The panoramic band (owner, locked): a rectangle with straight top and bottom edges, curved only in depth, a section
# of a vertical cylinder concave toward the crew, like a curved monitor across the flight deck. Its size comes from the
# owner's markup on 02_short_final_a_panes_only.png (90 deg across, from the eye at station 6.30): from 19.8 deg
# outboard of the pilot's forward line to the frame's far edge, which by symmetry spans both seats; the top at the
# windscreen's base by the centre post (1.8 deg under the eye at the band's centre); the bottom 16.3 deg under the
# pilot's eye straight ahead, below the runway on short final (9 deg).
BAND_AXIS_S, BAND_R = 7.30, 1.60  # the cylinder's vertical axis (centreline, station) and radius: its centre at 5.70
BAND_EDGE_AZ, BAND_TOP_EL, BAND_BOTTOM_EL = 19.8, -1.8, -16.3
BAND_DEPTH = 0.01  # the sheet sits this far toward the crew from the panel cylinder
# Owner, round 4: a bit shorter, lowered a little (the view through it need not line up with the panes above). Bottom
# 15 deg and top 3.9 deg under the pilot's eye straight ahead; the runway on short final (9 deg) stays inside.
BAND_Z = (4.80, 4.95)
BEZEL_W, BEZEL_DEPTH = 0.018, 0.06  # owner, round 4: a bit thinner (was 0.03)


def cyl(phi, z, r=BAND_R):
    """A point on a cylinder about the band's axis: phi in degrees, positive toward +X (the left), 0 straight ahead."""
    a = math.radians(phi)
    return Vector((r * math.sin(a), st(BAND_AXIS_S) - r * math.cos(a), z))


def cyl_hit(eye, d, r=BAND_R):
    """Where a ray from inside the cylinder meets it, in plan (the ray's z follows along)."""
    ox, oy = eye.x, eye.y - st(BAND_AXIS_S)
    a = d.x ** 2 + d.y ** 2
    b = 2 * (ox * d.x + oy * d.y)
    c = ox ** 2 + oy ** 2 - r ** 2
    t = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)
    return eye + d * t, t


def band_shape():
    """The band's half angle on the cylinder and its top and bottom heights, from the owner's markup."""
    eye = Vector((EYE_X, st(EYE_S), EYE_Z))
    edge, _ = cyl_hit(eye, direction(BAND_EDGE_AZ, 0.0, 1))
    phi = math.degrees(math.atan2(edge.x, st(BAND_AXIS_S) - edge.y))
    if BAND_Z is not None:
        return phi, BAND_Z[1], BAND_Z[0]
    centre = cyl(0.0, EYE_Z)
    top = EYE_Z + (centre - eye).length * math.tan(math.radians(BAND_TOP_EL))
    _, t = cyl_hit(eye, direction(0.0, 0.0, 1))
    bottom = EYE_Z + t * math.tan(math.radians(BAND_BOTTOM_EL))
    return phi, top, bottom


def in_band(c, edges):
    """A point ahead of the band seen by either eye through it."""
    phi, top, bottom = band_shape()
    for side in (1, -1):
        eye = Vector((side * EYE_X, st(EYE_S), EYE_Z))
        d = (c - eye).normalized()
        if d.y >= 0:
            continue
        p, t = cyl_hit(eye, d)
        if (c - eye).length <= t:  # the point is nearer than the band
            continue
        a = math.degrees(math.atan2(p.x, st(BAND_AXIS_S) - p.y))
        if abs(a) <= phi + 1 and bottom - 0.02 <= p.z <= top + 0.02:
            return True
    return False


def build_panel_curved(skin, edges):
    """The panel on the band's cylinder, just behind it: under the band from the floor to the band's bottom, and beyond
    the band's ends up to the glass's lower edge as the nearer eye sees it."""
    phi, top, bottom = band_shape()
    bm = bmesh.new()
    floor = 3.85
    cols = [-70 + 0.5 * k for k in range(281)]
    pts = []
    for a in cols:
        p = cyl(a, 0.0, BAND_R + BAND_DEPTH)
        if abs(p.x) > lining_half_width(skin, p.y + Y0, 4.4):
            pts.append(None)
            continue
        if abs(a) <= phi:
            z = bottom
        else:
            side = 1 if p.x >= 0 else -1
            eye = Vector((side * EYE_X, st(EYE_S), EYE_Z))
            v = p - eye
            az = math.degrees(math.atan2(side * v.x, -v.y))
            z = min(EYE_Z - 0.03, EYE_Z + math.hypot(v.x, v.y) * math.tan(math.radians(interp_edge(edges[side], az))))
        pts.append((p, z))
    for q0, q1 in zip(pts, pts[1:]):
        if q0 is None or q1 is None:
            continue
        (p0, z0), (p1, z1) = q0, q1
        bm.faces.new([bm.verts.new(v) for v in (Vector((p0.x, p0.y, floor)), Vector((p1.x, p1.y, floor)),
                                                  Vector((p1.x, p1.y, z1)), Vector((p0.x, p0.y, z0)))])
    return bm


MARKER_AT = []  # where build_band put the camera marker, for the close-up view


def faint_material(name, rgb, opacity):
    """An emissive mark drawn at the given opacity over what lies behind it."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*rgb, 1)
    em.inputs["Strength"].default_value = 4.0
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = opacity
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def build_band(skin, edges):
    """The band: the translucent sheet on the cylinder, its black bezel all round (3 cm wide, 6 cm deep), a small
    camera marker in its top left corner, and the panel's five displays under it. Returns its objects."""
    phi, top, bottom = band_shape()
    n = 96
    angles = [-phi + 2 * phi * k / n for k in range(n + 1)]
    bm = bmesh.new()
    for a0, a1 in zip(angles, angles[1:]):
        bm.faces.new([bm.verts.new(v) for v in (cyl(a0, bottom), cyl(a1, bottom), cyl(a1, top), cyl(a0, top))])
    sheet = new_object("cc_band", bm, band_material())

    black = material("cc_bezel", (0.004, 0.004, 0.005), 0.7)
    bm = bmesh.new()
    w, deep = BEZEL_W, BEZEL_DEPTH
    r_in = BAND_R - deep  # the frame stands toward the crew

    def frame_quad(a0, a1, z0, z1):
        """The bezel's face toward the crew."""
        bm.faces.new([bm.verts.new(v) for v in (cyl(a0, z0, r_in), cyl(a1, z0, r_in), cyl(a1, z1, r_in), cyl(a0, z1, r_in))])

    da = math.degrees(w / BAND_R)
    for a0, a1 in zip(angles, angles[1:]):
        frame_quad(a0, a1, top, top + w)  # top
        frame_quad(a0, a1, bottom - w, bottom)  # bottom
    frame_quad(-phi - da, -phi, bottom - w, top + w)  # ends
    frame_quad(phi, phi + da, bottom - w, top + w)
    for zz in (top, bottom):  # the depth: lips from the frame back to the sheet along top, bottom and ends
        for a0, a1 in zip(angles, angles[1:]):
            bm.faces.new([bm.verts.new(v) for v in (cyl(a0, zz, r_in), cyl(a1, zz, r_in), cyl(a1, zz), cyl(a0, zz))])
    for a in (-phi, phi):
        bm.faces.new([bm.verts.new(v) for v in (cyl(a, bottom, r_in), cyl(a, top, r_in), cyl(a, top), cyl(a, bottom))])
    bezel = new_object("cc_band_bezel", bm, black)

    # the camera marker (owner, round 4): a red circle and EXT CAM in the bottom left corner as the pilot sees it
    # (the +X end), inside the bezel, at 25% opacity
    red = faint_material("cc_rec", (1.0, 0.05, 0.03), 0.25)
    white = faint_material("cc_cam_text", (0.9, 0.92, 0.95), 0.25)
    a_mark = phi - math.degrees(0.045 / BAND_R)
    facing = (math.radians(90), 0, math.radians(180 + a_mark))
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=True, segments=24, radius=0.007)
    marker = new_object("cc_band_rec", bm, red)
    marker.location = cyl(a_mark, bottom + 0.022, BAND_R - 0.004)
    marker.rotation_euler = facing
    cu = bpy.data.curves.new("cc_cam_label", "FONT")
    cu.body, cu.size, cu.align_x = "EXT CAM", 0.014, "LEFT"
    label = bpy.data.objects.new("cc_band_cam_label", cu)
    label.location = cyl(a_mark - math.degrees(0.014 / BAND_R), bottom + 0.017, BAND_R - 0.004)
    label.rotation_euler = facing
    label.data.materials.append(white)
    collection().objects.link(label)
    MARKER_AT[:] = [marker.location.copy()]

    # the panel's displays under the band: per seat an outboard flight display and an inboard navigation display,
    # one engine and stores display in the middle
    glow = material("cc_display", (0.0, 0.0, 0.0), 0.3, emit=(0.10, 0.35, 0.22), strength=1.5)
    bm = bmesh.new()
    dw = math.degrees(0.28 / BAND_R)
    for ac in (-2.1 * dw, -1.05 * dw, 0.0, 1.05 * dw, 2.1 * dw):
        a0, a1 = ac - dw / 2, ac + dw / 2
        z0, z1 = bottom - 0.29, bottom - 0.05
        bm.faces.new([bm.verts.new(v) for v in (cyl(a0, z0, BAND_R - 0.002), cyl(a1, z0, BAND_R - 0.002),
                                                  cyl(a1, z1, BAND_R - 0.002), cyl(a0, z1, BAND_R - 0.002))])
    displays = new_object("cc_displays", bm, glow)
    left = cyl(phi, top)
    print(f"BAND cylinder r {BAND_R} about station {BAND_AXIS_S}: +-{phi:.1f} deg, x +-{left.x:.2f} m, stations "
          f"{left.y + Y0:.2f} (ends) to {BAND_AXIS_S - BAND_R:.2f} (centre), z {bottom:.2f} to {top:.2f}")
    return [sheet, bezel, marker, label, displays]


def build_furniture(dark, grey):
    """Blockout seats, centre pedestal with two throttles, outboard consoles with sidesticks, rudder pedals: the
    shapes the wide and outside views need for scale. Seats sit under each eye on the deck floor."""
    bm = bmesh.new()
    for side in (1, -1):
        x = side * EYE_X
        root = rail_start(side)
        box(bm, (x, root.y + 0.05, FLOOR_Z + 0.22), (0.50, 0.50, 0.44))  # seat bucket
        box(bm, (x, st(EYE_S) + 0.22, FLOOR_Z + 0.85), (0.50, 0.12, 0.90))  # back
        box(bm, (x, st(EYE_S) + 0.18, EYE_Z + 0.05), (0.30, 0.10, 0.30))  # headrest behind the head
        box(bm, (side * 1.05, st(EYE_S) + 0.05, FLOOR_Z + 0.33), (0.30, 1.10, 0.66))  # outboard console
        for px in (-0.12, 0.12):
            box(bm, (x + px, st(PANEL_S) + 0.15, FLOOR_Z + 0.12), (0.10, 0.04, 0.20))  # pedals
    box(bm, (0, st((PANEL_S + EYE_S) / 2) + 0.05, FLOOR_Z + 0.33), (0.42, EYE_S - PANEL_S, 0.66))  # pedestal
    seats = new_object("cc_furniture", bm, grey)
    bm = bmesh.new()
    for side in (1, -1):
        box(bm, (side * 1.02, st(EYE_S) + 0.25, FLOOR_Z + 0.78), (0.035, 0.035, 0.24))  # sidestick
    for x in (-0.06, 0.06):
        box(bm, (x, st(PANEL_S + 0.35), FLOOR_Z + 0.78), (0.03, 0.05, 0.22))  # throttles
    sticks = new_object("cc_controls", bm, dark)
    return [seats, sticks]


def band_material():
    """A camera feed seen on a screen: mostly see-through, graded slightly cool, with faint horizontal scanlines
    (a 4 mm period, about 4 px at the eye in a 1600 px, 90 degree render) and a faint reflection."""
    m = bpy.data.materials.new("cc_band_feed")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation, mul.inputs[1].default_value = "MULTIPLY", 2 * math.pi / 0.004
    nt.links.new(sep.outputs["Z"], mul.inputs[0])
    sin = nt.nodes.new("ShaderNodeMath")
    sin.operation = "SINE"
    nt.links.new(mul.outputs[0], sin.inputs[0])
    lines = nt.nodes.new("ShaderNodeMapRange")  # sine -1..1 to a dark-line weight 0.03..0.13
    lines.inputs["From Min"].default_value, lines.inputs["From Max"].default_value = -1.0, 1.0
    lines.inputs["To Min"].default_value, lines.inputs["To Max"].default_value = 0.03, 0.13
    nt.links.new(sin.outputs[0], lines.inputs["Value"])
    feed = nt.nodes.new("ShaderNodeBsdfTransparent")
    feed.inputs["Color"].default_value = (0.80, 0.92, 0.95, 1)  # the grade: a touch cool and green
    dark = nt.nodes.new("ShaderNodeEmission")
    dark.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lines.outputs[0], mix.inputs["Fac"])
    nt.links.new(feed.outputs[0], mix.inputs[1])
    nt.links.new(dark.outputs[0], mix.inputs[2])
    gl = nt.nodes.new("ShaderNodeBsdfGlossy")
    gl.inputs["Roughness"].default_value = 0.45  # smoothness about 0.5 at most, as the game material (no mirror finish)
    top = nt.nodes.new("ShaderNodeMixShader")
    top.inputs["Fac"].default_value = 0.03
    nt.links.new(mix.outputs[0], top.inputs[1])
    nt.links.new(gl.outputs[0], top.inputs[2])
    nt.links.new(top.outputs[0], out.inputs["Surface"])
    return m


# The escape path: the Pilot transform sits 0.73 m under and 0.17 m ahead of the helmet eye (the Darkreach rig's
# armature is scaled 100), and the stock seat rails 1.5 m along the PilotDismounted nozzle's up, which in the cockpit
# frame is 0.024 left, 0.230 forward and 0.973 up (pilotDismounted_PLACEHOLDER.prefab).
ROOT_BELOW_EYE, ROOT_AHEAD_OF_EYE = 0.73, 0.17
RAIL = Vector((0.024, -0.230, 0.973))
HATCH_S, HATCH_X = (5.58, 6.85), (0.20, 0.90)  # escape hatch opening: stations, and x outboard of the centreline
HATCH_CORNER = 0.15  # corner radius (owner: rounded corners)


def hatch_outline(side, step=0.02):
    """The hatch's rounded rectangle in plan, as (x, world y) points round it."""
    (s0, s1), (x0, x1), r = HATCH_S, HATCH_X, HATCH_CORNER
    pts = []
    for cx, cs, a0 in ((x1 - r, s0 + r, -90), (x1 - r, s1 - r, 0), (x0 + r, s1 - r, 90), (x0 + r, s0 + r, 180)):
        for k in range(10):
            a = math.radians(a0 + 9 * k)
            pts.append((cx + r * math.cos(a), cs + r * math.sin(a)))
    out = []
    for (xa, sa), (xb, sb) in zip(pts, pts[1:] + pts[:1]):
        n = max(1, int(math.hypot(xb - xa, sb - sa) / step))
        out += [(side * (xa + (xb - xa) * k / n), st(sa + (sb - sa) * k / n)) for k in range(n)]
    return out


def glass_points():
    """A BVH of the composite's glass faces, for measuring skin gaps to the windscreen (find_nearest)."""
    o = bpy.data.objects["nose"]
    gi = [i for i, m in enumerate(o.data.materials) if m.name == "glass"][0]
    vs = [o.matrix_world @ v.co for v in o.data.vertices]
    return BVHTree.FromPolygons(vs, [tuple(p.vertices) for p in o.data.polygons if p.material_index == gi])


def rail_start(side):
    return Vector((side * EYE_X, st(EYE_S - ROOT_AHEAD_OF_EYE), EYE_Z - ROOT_BELOW_EYE))


def skin_top(skin, x, y):
    h = skin.cast(Vector((x, y, 20)), Vector((0, 0, -1)))
    return h[0], (h[1] if h[1].z > 0 else -h[1])


def build_escape(skin):
    """Exterior escape and entry concept: a hatch outline where each seat's rail crosses the roof, the rails drawn as
    orange lines, and the left crew door swung open about its forward edge over a dark doorway."""
    seam = material("cc_hatch_seam", (0.01, 0.01, 0.01), 0.5)
    rail_mat = material("cc_rail", (0.0, 0.0, 0.0), 0.5, emit=(1.0, 0.35, 0.02), strength=8.0)
    bm_seam, bm_rail = bmesh.new(), bmesh.new()
    crossings, gaps = {}, []
    glass_kd = glass_points()
    for side in (1, -1):
        p0 = rail_start(side)
        t = 0.0
        while t < 3.0:  # first point outside the skin: where the rail crosses the roof
            p = p0 + RAIL * t
            top, _ = skin_top(skin, p.x, p.y)
            if p.z > top.z:
                break
            t += 0.01
        c = p0 + RAIL * t
        crossings[side] = (round(c.y + Y0, 3), round(c.z, 3), round(t, 3))
        for k in range(30):  # the rail as a dotted line, 3 m
            a = p0 + RAIL * (k * 0.1)
            box(bm_rail, (a.x, a.y, a.z), (0.03, 0.03, 0.05))
        # hatch outline: four strips on the skin round the opening, which covers the capsule swept along the rail and
        # the dismounted pilot's head path (docs/COCKPIT-DESIGN.md)
        outline = hatch_outline(side)
        gaps.append(min(glass_kd.find_nearest(skin_top(skin, x, y)[0])[3] for x, y in outline))
        for (xa, ya), (xb, yb) in zip(outline, outline[1:] + outline[:1]):
            top, n = skin_top(skin, (xa + xb) / 2, (ya + yb) / 2)
            q = top + n * 0.006
            box(bm_seam, (q.x, q.y, q.z), (abs(xb - xa) + 0.025, abs(yb - ya) + 0.025, 0.01))
    print("HATCH CROSSINGS (station, z, rail metres):", crossings)
    print(f"HATCH nearest glass from the outline: {min(gaps):.3f} m")

    # the crew door: left side, stations 5.95 to 6.85, z 2.80 to 3.70 (nose.CREW_DOOR), open 100 deg about its
    # forward edge, over a dark doorway
    door = material("cc_door", (0.25, 0.26, 0.24), 0.6)
    dark = material("cc_doorway", (0.005, 0.005, 0.005), 0.9)
    bm_door, bm_way = bmesh.new(), bmesh.new()
    s0, s1, z0, z1 = 5.95, 6.85, 2.80, 3.70
    rows = []
    for zi in range(5):
        z = z0 + (z1 - z0) * zi / 4
        row = []
        for si in range(5):
            s = s0 + (s1 - s0) * si / 4
            h = skin.cast(Vector((10, st(s), z)), Vector((-1, 0, 0)))
            row.append(h[0])
        rows.append(row)
    hinge = (rows[0][0] + rows[-1][0]) / 2
    from mathutils import Matrix
    pin = (rows[-1][0] - rows[0][0]).normalized()  # the door's forward edge, bottom to top
    turn = Matrix.Translation(hinge) @ Matrix.Rotation(math.radians(-100), 4, pin) @ Matrix.Translation(-hinge)
    for zi in range(4):
        for si in range(4):
            q = [rows[zi][si], rows[zi][si + 1], rows[zi + 1][si + 1], rows[zi + 1][si]]
            bm_way.faces.new([bm_way.verts.new(v + Vector((0.004, 0, 0))) for v in q])
            bm_door.faces.new([bm_door.verts.new(turn @ (v + Vector((0.01, 0, 0)))) for v in q])
    objs = [new_object("cc_hatch_seams", bm_seam, seam), new_object("cc_rails", bm_rail, rail_mat),
            new_object("cc_doorway", bm_way, dark), new_object("cc_door", bm_door, door)]
    bpy.data.objects["cc_door"].modifiers.new("thick", "SOLIDIFY").thickness = 0.04
    return objs


def build_windscreen(name, hide=None):
    """The real windscreen from the composite's nose: its glass faces and the small frame and surround faces within
    10 cm of them, as a separate object, so it shows while the rest of the nose hides as in the cockpit view. Given the
    glass edges, faces inside the forward vision displays' frusta go, as the interior's do."""
    from mathutils.kdtree import KDTree
    src = bpy.data.objects["nose"]
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.transform(src.matrix_world)
    gi = [i for i, m in enumerate(src.data.materials) if m.name == "glass"][0]
    glass = [f for f in bm.faces if f.material_index == gi]
    gverts = [v.co.copy() for f in glass for v in f.verts]
    kd = KDTree(len(gverts))
    for k, co in enumerate(gverts):
        kd.insert(co, k)
    kd.balance()
    keep = set(glass)
    for f in bm.faces:
        if f.material_index != gi and f.calc_area() < 0.05 and kd.find(f.calc_center_median())[2] < 0.10:
            keep.add(f)
    if hide is not None:
        keep = {f for f in keep if not hide(f.calc_center_median())}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context="FACES")
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in src.data.materials:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    collection().objects.link(o)
    # the glass clear with a faint reflection; the frames keep their composite materials
    clear = bpy.data.materials.new("cc_glass_clear")
    clear.use_nodes = True
    nt = clear.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    gl = nt.nodes.new("ShaderNodeBsdfGlossy")
    gl.inputs["Roughness"].default_value = 0.05
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.06
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(gl.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    me.materials[gi] = clear
    return o


def short_final(pitch_deg, glide_deg, dist_m, threshold_m):
    """Green ground and a black 3,000 x 45 m runway placed as the eye sees them on final: dist_m short of the aim
    point on a glide_deg path, the aircraft pitched pitch_deg nose up. The aircraft stays put; an 'earth' empty at the
    design eye carries the ground, turned by the pitch."""
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.52, 0.64, 0.82, 1)
    bg.inputs["Strength"].default_value = 1.0
    sun = bpy.data.objects.new("cc_sun", bpy.data.lights.new("cc_sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.5, math.radians(2)
    sun.rotation_euler = (math.radians(40), math.radians(-20), math.radians(150))
    collection().objects.link(sun)
    earth = bpy.data.objects.new("cc_earth", None)
    earth.location = Vector((EYE_X, st(EYE_S), EYE_Z))
    earth.rotation_euler = (math.radians(pitch_deg), 0, 0)
    collection().objects.link(earth)
    h = dist_m * math.tan(math.radians(glide_deg))
    bm = bmesh.new()
    box(bm, (0, -dist_m, -h - 0.05), (30000, 30000, 0.02))
    grass = new_object("cc_grass", bm, material("cc_grass", (0.12, 0.30, 0.08), 0.95))
    bm = bmesh.new()
    box(bm, (0, -(dist_m - threshold_m) - 1500, -h), (45, 3000, 0.02))
    rwy = new_object("cc_runway", bm, material("cc_runway", (0.01, 0.01, 0.01), 0.9))
    for o in (grass, rwy):
        o.parent = earth
    for o in bpy.data.objects:
        if o.name == "m4_ground":
            o.hide_render = True
    return h


def camera(name, loc, rot, lens):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    cam.data.lens, cam.data.clip_start, cam.data.clip_end = lens, 0.05, 40000
    cam.location, cam.rotation_euler = Vector(loc), rot
    collection().objects.link(cam)
    return cam


def shoot(cam, path, samples, res=(1600, 900)):
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = *res, 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)
    scene.view_settings.view_transform = "AgX"
    ahead = cam.rotation_euler.to_quaternion() @ Vector((0, 0, -1))
    hit = scene.ray_cast(bpy.context.evaluated_depsgraph_get(), cam.location, ahead)
    print(f"VIEW {cam.name} at station {cam.location.y + Y0:.2f}, z {cam.location.z:.2f}: first hit along the axis "
          f"{hit[4].name if hit[0] else 'none'} at {(hit[1] - cam.location).length if hit[0] else 0:.2f} m")
    bpy.ops.render.render(write_still=True)
    print("RENDER", path)


# The cockpit camera looks along the cockpit's forward axis (CameraCockpitState); the field of view is the player's
# setting, so the renders use 90 degrees across.
FORWARD = (math.radians(90), 0, math.radians(180))
LENS_90 = 18.0
TODAY_EYE = (0.42, 4.60, 4.37)  # the Alkyon clone's eye: x outboard, station, z


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".cache/cockpit/renders")
    ap.add_argument("--tag", default="02")
    ap.add_argument("--variants", default="a,b,c")
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--pitch", type=float, default=6.0)
    a = ap.parse_args(argv)
    blend = Path(bpy.data.filepath).resolve()
    if "art" in blend.parts:
        raise SystemExit(f"refusing to work on {blend}: copy it under .cache/cockpit first")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    for o in bpy.data.objects:  # colliders and LOD1 hulls never render
        if o.name.endswith(("_colmesh", "_lod1")) or "_colmesh." in o.name:
            o.hide_render = True
    skin = Skin(("radar_F_fairing", "nose", "fuselage_F"))
    edges = {}
    for side in (1, -1):
        eye = Vector((side * EYE_X, st(EYE_S), EYE_Z))
        edges[side] = {az: glass_floor(skin, eye, side, az) for az in range(-70, 91, 5)}
    print("GLASS_EDGE left eye (az outboard: lowest el):", edges[1])

    grey = material("cc_interior", (0.017, 0.018, 0.018), 0.6)  # the stock cockpits: frames about sRGB 35
    dark = material("cc_panel", (0.005, 0.005, 0.006), 0.5)  # panels and glareshield near black
    h = short_final(a.pitch, 3.0, 2000.0, 300.0)
    print(f"FINAL: {a.pitch} deg nose up, 3 deg path, 2,000 m short of the aim point, eye {h:.0f} m up")
    deck = new_object("cc_deck", build_deck(skin), grey)
    want = set(a.variants.split(","))
    if want & {"w", "o", "m"}:  # the wide interior, the outside view and the marker close-up show the (d) flight deck
        want.add("d")
    if "x" in want:  # the crew door close-up shows the escape and entry set
        want.add("e")
    hides = {"a": None, "b": lambda c: in_fvd(c, edges), "d": lambda c: in_band(c, edges)}
    sets = {}
    for k, hide in hides.items():
        if k in want or (k == "a" and "c" in want):
            sets[k] = [new_object("cc_lining_" + k, build_lining(skin, hide), grey),
                       new_object("cc_panel_" + k, build_panel_curved(skin, edges) if k == "d" else build_panel(skin, edges, k), dark),
                       build_windscreen("cc_windscreen_" + k, hide)]
    if "d" in sets:
        sets["d"] += build_band(skin, edges) + build_furniture(dark, grey)
    if "e" in want:
        sets["e"] = build_escape(skin)
    for o in [deck] + [o for objs in sets.values() for o in objs]:
        if o.type == "MESH":
            print("TRIS", o.name, sum(len(p.vertices) - 2 for p in o.data.polygons))
    fill = bpy.data.objects.new("cc_fill", bpy.data.lights.new("cc_fill", "AREA"))
    fill.data.energy, fill.data.size = 40, 1.2
    fill.location = Vector((0, st(6.8), 5.30))
    fill.visible_camera = False
    collection().objects.link(fill)

    names = {"a": "panes_only", "b": "panes_plus_fvd", "c": "todays_eye_nose_hidden", "d": "panes_plus_panoramic_feed",
             "e": "escape_hatches_and_crew_door", "w": "wide_interior", "o": "outside_through_windscreen",
             "x": "crew_door_open", "m": "screen_and_camera_marker"}
    nose = bpy.data.objects["nose"]
    glass_slot = [i for i, m in enumerate(nose.data.materials) if m.name == "glass"][0]
    if "o" in want:  # the design removes nose_cabin.py's cabin (lining, floor, bulkheads); it would show through clear glass
        struct = [i for i, m in enumerate(nose.data.materials) if m.name == "aircraft_structure"][0]
        bm = bmesh.new()
        bm.from_mesh(nose.data)
        mw = nose.matrix_world
        cabin = [f for f in bm.faces if f.material_index == struct
                 and 3.80 < (mw @ f.calc_center_median()).y + Y0 < 7.0 and (mw @ f.calc_center_median()).z > 3.0]
        tris_removed = sum(len(f.verts) - 2 for f in cabin)
        bmesh.ops.delete(bm, geom=cabin, context="FACES")
        bm.to_mesh(nose.data)
        bm.free()
        print("NOSE_CABIN removed triangles:", tris_removed)
    opaque_glass = nose.data.materials[glass_slot]
    for v in a.variants.split(","):
        shown = {"w": "d", "o": "d", "x": "e", "m": "d"}.get(v, v)
        for k, objs in sets.items():
            for o in objs:
                o.hide_render = k != shown and not (v == "c" and k == "a" and o.name.startswith("cc_windscreen"))
        exterior = v in ("e", "o", "x")
        deck.hide_render = v in ("c", "e", "x")
        # cockpit view: the nose and radome hide, as Aircraft.exteriorRenderers do in game; the exterior views show them
        for n in ("nose", "radar_F_fairing"):
            bpy.data.objects[n].hide_render = not exterior
        for n in ("cc_grass", "cc_runway"):
            bpy.data.objects[n].hide_render = exterior
        # outside through the windscreen: the composite's opaque tint swapped for clear glass, for this view only
        nose.data.materials[glass_slot] = bpy.data.materials["cc_glass_clear"] if v == "o" else opaque_glass
        for o in sets.get("d", []):
            if o.name.startswith("cc_windscreen"):
                o.hide_render = o.hide_render or v == "o"
        views = {
            "e": ((7.0, 2.0, 9.0), (0.4, 6.2, 4.6), 40),
            "x": ((5.5, 2.6, 3.4), (1.6, 6.4, 3.2), 32),
            "o": ((3.2, 1.2, 6.3), (0.1, 6.2, 4.7), 30),
            "w": ((0.0, 6.90, 5.15), (0.0, 4.9, 4.75), 11),
        }
        if v == "m":  # from the pilot's eye, a long lens on the screen's outboard end and the marker
            eye = Vector((EYE_X, st(EYE_S), EYE_Z))
            target = MARKER_AT[0] + Vector((-0.25, 0, 0.06))
            cam = camera("cc_cam_m", eye, (target - eye).to_track_quat("-Z", "Y").to_euler(), 30)
            shoot(cam, out / f"{a.tag}_{v}_{names[v]}.png", a.samples)
            continue
        if v in views:
            (lx, ls, lz), (tx, ts, tz), lens = views[v]
            loc, target = Vector((lx, st(ls), lz)), Vector((tx, st(ts), tz))
            cam = camera("cc_cam_" + v, loc, (target - loc).to_track_quat("-Z", "Y").to_euler(), lens)
            shoot(cam, out / f"{a.tag}_{v}_{names[v]}.png", a.samples)
            continue
        x, s_, z = TODAY_EYE if v == "c" else (EYE_X, EYE_S, EYE_Z)
        cam = camera("cc_cam_" + v, (x, st(s_), z), FORWARD, LENS_90)
        shoot(cam, out / f"{a.tag}_short_final_{v}_{names[v]}.png", a.samples)


main()
