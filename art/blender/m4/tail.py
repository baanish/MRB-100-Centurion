"""Part group 6: the V-tail.

Parts: vtail_L/R (the fixed panels: root fillets onto the tail cone, the cut-out along the whole moving trailing edge with
its dark cove, hinge fittings, the dielectric tip cap over the blockout's elliptic tip with its white tail light,
formation strips and a static discharger) and ruddervator_L1/L2/R1/R2_visible (the split tail's moving surfaces, 1
inboard and 2 outboard and into the rounded tip: a nose round the one hinge line, static dischargers). The actuators sit
inside the panel, as on a transport's tail of this size: the owner read the external actuator fairings as pods ("tail
fin detailing looks weird"). Right-hand parts come from the same code with side -1, face for face. The right surfaces
reuse the left's UV islands (MIRROR_PARTS); the right panel keeps its own, because the tail code on its upper face must
read the right way round.

Sections and planform are the blockout's (build_centurion: vtail_planform, vtail_section_s6, build_vtail_s6) at
finished resolution: the last VTAIL_TIP_ROUND[0] metres close elliptically on a point, so the tip ends rounded. Positions are
(d, chord fraction): d the distance along the panel's span direction from the root leading edge (the blockout's
vtail_section argument), the chord fraction 0 at the leading edge and 1 at the trailing edge.

The root: the panel meets the tail cone on an oblique line, about 1.4 m up the panel at the leading edge and nearly at
the root aft, and the cone's narrowing tail passes just above the panel's root trailing edge. A fillet runs along that
junction on both faces, drawn forward on the body ahead of the leading edge into a long, narrow strake; where the
panel misses the cone (the last fifth of the chord on the lower face, the trailing edge) the root lands a few degrees
into the cone instead of hanging in the air. The tail cone itself stays the plain hull.

The hinge: each surface's nose is a circle about the hinge line inside a concave cove of the fixed panel, so it turns
its full throw (pitch plus yaw, build_centurion S61_SPLIT_TAIL) without closing the gap; the cove is skin painted dark, so the gap reads as one dark line (the
stock aircraft_structure, a bright sheet, showed as a light strip along it in game). The cut-out's outer end opens
toward the trailing edge: a surface turning about a swept hinge moves its trailing edge outboard.

Text (the tail code, NO STEP) sits only on the panels' upper faces, which are unique; the ruddervators, mirrored,
carry symbols and lines that read either way."""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import airfoil as af
from . import fuselage_aft as aft_body
from . import render
from . import surface as sf
from .tail_join import conform_fillet_boundary, join_fillet_nose, land_panel_root

GROUP = "tail"
# The split tail's moving surfaces (build_centurion S61_SPLIT_TAIL): 1 inboard, biased to yaw; 2 outboard, biased to pitch.
SURFACES = ("1", "2")
PARTS = ("vtail_L", "vtail_R") + tuple(f"ruddervator_{s}{n}_visible" for s in "LR" for n in SURFACES)
# Round 2 Lead's call on budgets, 2026-10-14: spend on visible silhouettes. Round 4 lead's call, 2026-10-15: 164 of the
# composite's spare for the tip ring at u 0.12 (TIP_U), so the leading edge seen from above leaves the panel under 12 deg.
BUDGET_TRIS = 7664
# vtail_R stays unique for its tail code. The shared atlas can mirror all of it but TAIL_CODE's region on the upper
# face (about d 3.8 to 5.4 m, chord fractions 0.2 to 0.47) and the NO STEP stencils, once the entry script can mirror
# part of a part across x = 0.
MIRROR_PARTS = {f"ruddervator_R{n}_visible": f"ruddervator_L{n}_visible" for n in SURFACES}
# Close-ups (m4/render.py's view form); the first four make the contact sheet.
VIEWS = {
    "tail34": (38, (-9.0, 57.0, 19.0), (1.0, 39.5, 5.0)),
    "tail_root": (35, (8.5, 30.5, 8.0), (2.3, 36.2, 4.3)),
    "tail_low": (32, (11.5, 47.5, 1.1), (4.0, 39.5, 4.4)),
    "tail_tip": (45, (11.5, 48.5, 10.5), (7.4, 43.0, 7.0)),
    "tail_side": (("ortho", 17.0, render.SIDE), (60.0, 38.5, 4.6), None),
    "tail_rear": (40, (0.0, 72.0, 5.6), (0.0, 40.0, 4.9)),
    "tail_top": (("ortho", 22.0, render.TOP), (0.0, 38.5, 60.0), None),
    "tail_root_aft": (50, (6.5, 46.0, 1.8), (1.9, 39.6, 3.7)),
    "tail_below34": (30, (9.0, 52.0, -2.0), (3.2, 40.0, 5.0)),  # the owner's in-game angle: below, rear three-quarter
}

# Paint classes past the shared ones (m4/surface.py, 1 to 5) and the other groups' (wing 11 to 23).
PANEL, ROOT, TIP, FILLET, RUDDER, RUDDER_END, COVE, BRACKET = range(60, 68)
SKIN_CLASSES = (PANEL, ROOT, TIP, FILLET, RUDDER, RUDDER_END, COVE, BRACKET)

CDIR = Vector((0, 1, 0))  # the V-tail's chord runs along the body
PANEL_N = 20  # airfoil points a side, cosine spaced (the blockout's 10)
ROOT_D = -0.3  # the blockout's buried root section (S6_VTAIL root_buried)
# The panel's second ring where no fillet runs (elsewhere it follows the fillet's panel edge): far enough out that the
# face from the root ring, ROOT_SINK under the cone, lands into it at a few degrees (the lower face aft, which runs
# nearly tangent past the cone's lower flank, and the trailing edge)
PANEL_EDGE_D, ROOT_SINK = 0.3, 0.025
SEAM_D = 4.5  # a spanwise UV cut on a skin splice, so each face packs as two islands
# Rings over the blockout's rounded tip, as fractions u of its closing run (VTAIL_TIP_ROUND[0] metres to the point):
# u = sin(a) for a stepped evenly in the ellipse's angle from the full section at c1 + OUTER_RAMP (u 0.067) to the
# point, so each bay turns the leading edge seen from above by the same few degrees (a first bay to u 0.38 left it
# at 32 deg), with u 0.12 added in the first step. tip_ds drops u 0.0; the loft closes on the point itself.
TIP_U = (0.0, 0.12, 0.21, 0.36, 0.5, 0.62, 0.73, 0.82, 0.9, 0.955, 0.99)
TE_THICK = 0.002  # the sections' trailing-edge thickness term, a fraction of the chord (the blockout's 0.006)
# Radial gap between a surface's nose and the cove round it. Its skin aft of the nose stays inside the cove's radius for
# a length that grows with the gap, and that length is what clears the cove's lip at the full throw: at 1.2 cm the skin
# reached the lip at 40 deg (the inboard surface's pitch plus yaw).
COVE_GAP = 0.025
OUTER_RAMP = 0.12  # spanwise width of the cove-to-tip section transition
# Span gaps at the moving trailing edge's ends, against the blockout's 3 cm: a surface turning about a hinge line swept 29
# deg moves the faces of its nose along the span by up to r tan(sweep) sin(throw / 2) / cos(sweep) twice over, r the
# nose's radius (0.2 m at the root, where the inboard surface turns 40 deg; 0.1 m by the tip cap); its trailing edge
# moves 11 cm outboard at 25 deg.
END_GAP_IN, END_GAP_OUT = 0.09, 0.06
RUDDER_N, NOSE_M = 6, 11  # ruddervator: points a face from the hinge to the trailing edge; nose arc points
RUDDER_BEVEL = (0.006, 0.012)  # inset and width of the soft bevel round the ruddervator's inboard end
RUDDER_OUTER_BEVEL = (0.02, 0.045)  # the outer end, by the tip: a deeper bevel closes it as a tapered cap
HINGE_BRACKETS = (0.06, 0.5, 0.94)  # hinge fittings on the upper face, fractions of each surface's span
BRACKET_LEN = 0.5  # flush hinge doublers ahead of the cove lip
# The outer surface runs into the rounded tip: rings at these fractions u of its closing run (TIP_U's) carry its curving
# trailing edge, and the cove's
ROUND_U = (0.14, 0.52)
# span fractions of each surface; metres short of the tip (on the fixed tip cap's trailing edge)
DISCHARGERS = {"1": (0.55,), "2": (0.35, 0.82), "tip": (0.3,)}
TIP_LIGHT_U = 0.85  # the white tail light on the tip cap's trailing edge, at this fraction of its closing run
TIP_LIGHT_SEG = 16
FORMATION = (0.45, 0.08, 0.12, 0.6)  # strip on each face of the tip cap: metres short of the tip, width, from chord
# fraction, length in metres (the shared 0.6 x 0.08 m strip)
# Root fillet: chord fractions of its sections (each face, from the leading edge aft)
FILLET_NOSE_T = 0.5 * (1 - math.cos(2 * math.pi / PANEL_N))
FILLET_T_UP = (0.0, 0.00025, 0.001, 0.002, 0.004, 0.5 * (1 - math.cos(math.pi / PANEL_N)),
               0.009, 0.016, FILLET_NOSE_T,
               0.036, 0.05, 0.075, 0.11, 0.16, 0.22, 0.3, 0.38, 0.46, 0.53,
               0.56, 0.59, 0.62, 0.65, 0.685, 0.72, 0.75, 0.78, 0.81, 0.84, 0.865, 0.89, 0.91, 0.93)
FILLET_T_LO = (0.00025, 0.001, 0.002, 0.004, 0.5 * (1 - math.cos(math.pi / PANEL_N)),
               0.009, 0.016, FILLET_NOSE_T,
               0.036, 0.05, 0.075, 0.11, 0.16, 0.22, 0.27, 0.32, 0.38, 0.43, 0.48,
               0.53, 0.57, 0.61, 0.65, 0.69, 0.73, 0.76, 0.78)
# lower_footprint: the chord fractions it relaxes between (to the last section ahead of build_fillet's end blend onto
# the root), relaxation passes
LOWER_FOOTPRINT_SMOOTH = (0.38, 0.73, 6)
FILLET_ARC = (0.0, 0.035, 0.7, 0.9, 1.0)  # Bezier parameters of the arc, panel edge to body edge
FILLET_R = 0.54  # nominal radius along each surface
STRAKE_LEN, STRAKE_SIGMA = 1.6, 0.23  # the strake's run forward on the cone, and its width as sqrt(chord fraction)
STRAKE_NARROW = 0.35  # retain the leading-edge radius as it turns onto the cone
FILLET_RUN = 0.16
FILLET_LIP = 0.001  # a sealant film above the facets keeps the tangent landing from z-fighting
FILLET_SINK = 0.035  # the closing points run this far inside the panel and the cone
FILLET_EDGE_SINK = 0.03  # the arc's panel end sits under the panel's facets

# Built geometry the paint reads (left side): the fillet's panel and body edges, the ruddervator's span.
EDGES = {}


# ---------- section family ----------
def span_dir(bl, side):
    return Vector((side * math.cos(bl.VTAIL_DIHEDRAL), 0, math.sin(bl.VTAIL_DIHEDRAL)))


def thick_dir(bl, side):
    """The panel's thickness direction: its upper face (toward the other panel) is +."""
    return Vector((-side * math.sin(bl.VTAIL_DIHEDRAL), 0, math.cos(bl.VTAIL_DIHEDRAL)))


def root_le(bl, side):
    return Vector((side * bl.VTAIL_ROOT_X, bl.st(bl.VTAIL_ROOT_STATION), bl.VTAIL_ROOT_Z))


def section(bl, side):
    """The panel at distance d along its span (build_centurion.vtail_planform, vtail_section_s6): (leading edge,
    chord, thickness, chord dir, thickness dir, camber)."""
    sd, td, r0 = span_dir(bl, side), thick_dir(bl, side), root_le(bl, side)

    def sec(d):
        f = d / bl.VTAIL_SPAN
        le_station, chord = bl.vtail_planform(min(d, bl.VTAIL_SPAN))
        le = r0 + sd * d + Vector((0, le_station - bl.VTAIL_ROOT_STATION, 0))
        return le, chord, chord * (0.10 - 0.03 * max(f, 0.0)), CDIR, td, 0.0
    return sec


def hinge_t(bl, d):
    """The hinge line's chord fraction at d, the blockout's (build_vtail_s6's t0): one straight line, so further back in
    the local chord where the rounded tip draws both edges in."""
    return bl.vtail_hinge_fraction(d, bl.RUDDERVATOR_HINGE + 0.02 / bl.VTAIL_TIP_CHORD)


def airfoil_point(bl, *args):
    """The blockout's section point (build_centurion.airfoil_point) with a trailing edge TE_THICK of the chord thick
    instead of its 0.006, which read as a blunt edge from behind; it only moves skin inward."""
    return bl.airfoil_point(*args, te=TE_THICK)


def point(bl, sec, d, t, upper):
    le, c, th, cd, td, cam = sec(d)
    return airfoil_point(bl, le, c, th, cd, td, cam, t, upper)


def facet_point(bl, sec, d, t, upper):
    """The panel mesh's point at (d, chord fraction t): on the straight edge between the two PANEL_N columns either
    side of t, where point() is on the analytic section. Round the leading edge the two differ by up to a centimetre."""
    ts = cosine_ts(PANEL_N)
    i = min(max(int(np.searchsorted(ts, t)) - 1, 0), PANEL_N - 1)
    w = (t - ts[i]) / (ts[i + 1] - ts[i])
    return point(bl, sec, d, ts[i], upper).lerp(point(bl, sec, d, ts[i + 1], upper), w)


def cosine_ts(n):
    return [0.5 * (1 - math.cos(math.pi * k / n)) for k in range(n + 1)]


def columns(n):
    """(chord fraction, upper) of each ring index: upper trailing edge (0), leading edge (n), lower trailing edge."""
    ts = cosine_ts(n)
    return [(ts[n - i], True) for i in range(n)] + [(0.0, True)] + [(ts[i], False) for i in range(1, n + 1)]


def hinge_circle(bl, sec, d):
    """The hinge point at d, the nose radius (the half thickness at the hinge) and the cove radius."""
    th_ = hinge_t(bl, d)
    le, c, th, cd, td, cam = sec(d)
    hc = le + cd * (th_ * c)
    rn = (airfoil_point(bl, le, c, th, cd, td, cam, th_, True) - hc).dot(td)
    return hc, rn, rn + COVE_GAP


def axis_frame(bl, sec, d):
    """(hinge point, hinge axis, ahead) at d: ahead is the direction straight forward square to the swept axis."""
    side = 1 if sec(0.0)[0].x > 0 else -1
    A = hinge_axis(bl, side)
    hc = hinge_circle(bl, sec, d)[0]
    f = -(CDIR - A * A.dot(CDIR)).normalized()
    return hc, A, f


def axis_point(bl, sec, d, r, phi):
    """A point r from the hinge line, phi degrees from straight ahead toward the upper face, in the ring plane at d.
    The nose and the cove are true cylinders about the swept hinge line, so the nose turns inside the cove."""
    hc, A, f = axis_frame(bl, sec, d)
    td = sec(d)[4]
    a = math.radians(phi)
    q = hc + (f * math.cos(a) + td * math.sin(a)) * r
    sd = span_dir(bl, 1 if hc.x > 0 else -1)
    return q + A * (-(q - hc).dot(sd) / A.dot(sd))


def axis_dist(bl, sec, d, p):
    hc, A, f = axis_frame(bl, sec, d)
    v = p - hc
    return (v - A * v.dot(A)).length


def skin_end_t(bl, sec, d):
    """Chord fraction where the fixed skin meets the cove cylinder (ahead of the hinge)."""
    hc, rn, rc = hinge_circle(bl, sec, d)
    lo, hi = hinge_t(bl, d) - 0.2, hinge_t(bl, d)
    for _ in range(40):
        m = (lo + hi) / 2
        if axis_dist(bl, sec, d, point(bl, sec, d, m, True)) > rc:
            lo = m
        else:
            hi = m
    return lo


def panel_ring(bl, sec, d, n, cut=False, thick_k=1.0):
    """A closed panel section. cut: the points behind the skin end fold onto the cove, a concave arc about the hinge
    line. Returns the points and the folded indices."""
    cols = columns(n)
    pts = []
    le, c, th, cd, td, cam = sec(d)
    for t, up in cols:
        pts.append(airfoil_point(bl, le, c, th * thick_k, cd, td, cam, t, up))
    if not cut:
        return pts, set()
    hc, rn, rc = hinge_circle(bl, sec, d)
    _, A, f = axis_frame(bl, sec, d)
    t_se = skin_end_t(bl, sec, d)
    p = airfoil_point(bl, le, c, th, cd, td, cam, t_se, True) - hc
    p -= A * p.dot(A)
    phi_se = math.degrees(math.atan2(p.dot(td), p.dot(f)))
    up_idx = [i for i in range(n) if cols[i][0] > t_se]
    lo_idx = [i for i in range(n + 1, 2 * n + 1) if cols[i][0] > t_se]
    j = len(up_idx)
    for k, i in enumerate(up_idx):  # i = 0 (the deepest, by the cove's front) .. j - 1 (the skin end)
        pts[i] = axis_point(bl, sec, d, rc, 2.0 + (phi_se - 2.0) * k / (j - 1))
    for k, i in enumerate(reversed(lo_idx)):  # i = 2n (deepest) .. the skin end
        pts[i] = axis_point(bl, sec, d, rc, -(2.0 + (phi_se - 2.0) * k / (j - 1)))
    return pts, set(up_idx) | set(lo_idx)


def tip_ds(bl):
    """The rings over the rounded tip, as d, and the point it closes on (left side)."""
    L, span = bl.VTAIL_TIP_ROUND[0], bl.VTAIL_SPAN
    lo = cutout_span(bl)[1] + 0.01 + OUTER_RAMP
    return [span - L * (1 - u) for u in TIP_U if span - L * (1 - u) > lo + 0.05]


def tip_point(bl, side):
    return root_le(bl, side) + span_dir(bl, side) * bl.VTAIL_SPAN + Vector((0, bl.vtail_planform(bl.VTAIL_SPAN)[0]
                                                                          - bl.VTAIL_ROOT_STATION, 0))


def body_frame(bl, p):
    """(station, angle) of the fuselage surface point nearest in angle to p (the round step 6 body, P = 2)."""
    s = p.y + bl.Y0
    w, top, bot = bl.fus_profile(s)
    zc, h = (top + bot) / 2, (top - bot) / 2
    return s, math.degrees(math.atan2(p.x / w, (p.z - zc) / h))


def hull_triangles(bl, surf, skin, structure):
    """Use the cone builder's tessellated hull, including in tail-only builds with a blockout neighbour."""
    part = sf.Part('tail_landing', (skin,))
    aft_body.tail_hull(part, surf, bl, skin, structure)
    mesh = bpy.data.meshes.new('tail_landing')
    part.bm.to_mesh(mesh)
    part.bm.free()
    mesh.calc_loop_triangles()
    tree = BVHTree.FromPolygons([v.co for v in mesh.vertices], [t.vertices for t in mesh.loop_triangles],
                               all_triangles=True)
    bpy.data.meshes.remove(mesh)
    return tree


def hull_point(bl, surf, tree, s, deg):
    """Project onto a hull triangle instead of interpolating across a non-planar quad."""
    point, normal = surf.point(s, deg), surf.normal(s, deg)
    hit, facet, index, distance = tree.ray_cast(point + normal * 0.2, -normal, 0.5)
    if hit is None:
        raise SystemExit(f'tail: cone projection missed station {s:.6f}, angle {deg:.6f}')
    return hit, facet if facet.dot(normal) > 0 else -facet


def body_inside(bl, p):
    s = p.y + bl.Y0
    w, top, bot = bl.fus_profile(s)
    zc, h = (top + bot) / 2, (top - bot) / 2
    return (p.x / w) ** 2 + ((p.z - zc) / h) ** 2 < 1.0


def junction(bl, sec, t, upper):
    """Where the panel face at chord fraction t enters the tail cone: d, or None where the face misses it."""
    lo, hi = ROOT_D, 3.0
    if not body_inside(bl, point(bl, sec, lo, t, upper)):
        return None
    for _ in range(40):
        m = (lo + hi) / 2
        if body_inside(bl, point(bl, sec, m, t, upper)):
            lo = m
        else:
            hi = m
    return hi


def root_point(bl, surf, sec, t, upper, bare):
    """The root ring point. Under a fillet, the blockout's buried section. Where the root runs bare (bare), the cone's
    skin at the face's own junction, sunk ROOT_SINK, so the face lands into the cone a few degrees along the junction
    line instead of crossing the hull's facets steeply from 0.3 m inside; past the junction's end, the cone's skin
    nearest the buried section, sunk the same, so the root lands instead of hanging in the air."""
    p = point(bl, sec, ROOT_D, t, upper)
    if body_inside(bl, p):
        if not bare:
            return p
        p = point(bl, sec, junction(bl, sec, t, upper), t, upper)
    s, deg = body_frame(bl, p)
    return surf.point(s, deg) - surf.normal(s, deg) * ROOT_SINK


def bare_edge_d(bl, sec, t, upper):
    """d of the second ring where the root runs bare: PANEL_EDGE_D out from the junction (or from d 0 past its end)."""
    return max(junction(bl, sec, t, upper) or 0.0, 0.0) + PANEL_EDGE_D


# ---------- build ----------
def build(bl, surf, slots):
    parts = {}
    for sfx, side in (("L", 1), ("R", -1)):
        p = sf.Part(f"vtail_{sfx}", (slots[0],))
        p.bm.verts.layers.float.new('tail_fillet_chord')
        build_panel(bl, surf, p, side, slots)
        build_fillet(bl, surf, p, side, slots)
        build_tip(bl, p, side, slots)
        parts[p.name] = p
        for n in SURFACES:
            r = sf.Part(f"ruddervator_{sfx}{n}_visible", (slots[0],))
            build_ruddervator(bl, r, side, slots, n)
            parts[r.name] = r
    return parts


def ruddervator_span(bl):
    """The moving trailing edge's span on the panel (the blockout's), both surfaces."""
    return bl.RUDDERVATOR_SPAN


def surface_span(bl, n):
    """Surface n's span on the panel, the blockout's (ruddervator_spans: its hinge empty sits at the inboard end)."""
    return dict(bl.ruddervator_spans("_L"))[f"ruddervator_L{n}"]


def cutout_span(bl):
    """The cut-out's end walls, the blockout's."""
    d0, d1 = bl.RUDDERVATOR_SPAN
    return d0 - bl.SURF_GAP, d1 + bl.SURF_GAP


def mesh_span(bl, n):
    """Surface n's mesh ends: inside the cut-out by what the end gaps take, and the blockout's own ends at the split.
    Both surfaces turn about one hinge line, which keeps every point's place along it, so the split's gap holds at any
    mix of their deflections."""
    c0, c1 = cutout_span(bl)
    a, b = surface_span(bl, n)
    return (c0 + END_GAP_IN if n == SURFACES[0] else a), (c1 - END_GAP_OUT if n == SURFACES[-1] else b)


def ruddervator_mesh_span(bl):
    """The moving trailing edge's mesh ends, inboard and outboard."""
    return mesh_span(bl, SURFACES[0])[0], mesh_span(bl, SURFACES[-1])[1]


def bevels(n):
    """(inboard, outboard) bevels of surface n: (inset, width), the deeper tapered cap only at the tip."""
    return RUDDER_BEVEL, RUDDER_OUTER_BEVEL if n == SURFACES[-1] else RUDDER_BEVEL


def round_ds(bl):
    """The rounded tip's sections inside the cut-out (ROUND_U), d of each."""
    L, span = bl.VTAIL_TIP_ROUND[0], bl.VTAIL_SPAN
    return [span - L * (1 - u) for u in ROUND_U]


def hinge_plate_station(bl, n):
    """Surface n's outboard plate's inboard edge, where both cylinder lofts need the same section."""
    d0, d1 = surface_span(bl, n)
    return d0 + (d1 - d0) * HINGE_BRACKETS[-1] - 0.16


def surface_ds(bl, n):
    """Surface n's ring stations: its ends and their bevels, then inside them its hinge plate and the rounded tip's
    sections, so its trailing edge follows the rounding."""
    d0, d1 = mesh_span(bl, n)
    (_, w_in), (_, w_out) = bevels(n)
    # a short surface lofts in one bay, nose and cove alike: over 2 m their facets part by under a millimetre
    inside = set(round_ds(bl)) | ({hinge_plate_station(bl, n)} if d1 - d0 > 3.0 else set())
    return [d0, d0 + w_in] + sorted(d for d in inside if d0 + w_in + 0.05 < d < d1 - w_out - 0.05) + [d1 - w_out, d1]


def panel_cut_ds(bl):
    """The cut rings of the panel between its cut-out's walls: each surface's inner stations, so the cove is lofted on
    the noses' sections, the outer bevels, one ring at the split and the skin splice."""
    first, last = surface_ds(bl, SURFACES[0]), surface_ds(bl, SURFACES[-1])
    split = (mesh_span(bl, SURFACES[0])[1] + mesh_span(bl, SURFACES[-1])[0]) / 2
    return sorted({first[1], *first[2:-2], split, SEAM_D, *last[2:-2], last[-2]})


def build_panel(bl, surf, p, side, slots):
    SKIN, STRUCT = slots[0], slots[1]
    n, M = PANEL_N, 2 * PANEL_N + 1
    sec = section(bl, side)
    hull = hull_triangles(bl, surf, SKIN, STRUCT)
    c0, c1 = cutout_span(bl)
    span = bl.VTAIL_SPAN
    rings, fold, ds = [], [], []

    def add(d, **kw):
        pts, f = panel_ring(bl, sec, d, n, **kw)
        # The leading-edge fillet passes the first cove stations; its uncut columns must keep moving outboard.
        if rings:
            origin, axis = root_le(bl, side), span_dir(bl, side)
            for k, (t, up) in enumerate(columns(n)):
                previous = (rings[-1][k] - origin).dot(axis)
                if k not in f and (pts[k] - origin).dot(axis) < previous + 0.01:
                    pts[k] = point(bl, sec, previous + 0.01, t, up)
        rings.append(pts)
        fold.append(f)
        ds.append(d)

    cols = columns(n)
    # The joining ring follows the fillet at each chord column; the root faces behind it are buried.
    edge = [fillet_edge(bl, sec, t, up) for t, up in cols]
    filleted = {k for k, e in enumerate(edge) if e is not None}
    # a column lands on the cone where its root, or the face beside it, runs bare
    bare = [not {(k - 1) % M, k, (k + 1) % M} <= filleted for k in range(M)]
    rings.append([root_point(bl, surf, sec, t, up, b) for (t, up), b in zip(cols, bare)])
    fold.append(set())
    ds.append(ROOT_D)
    rings.append([point(bl, sec, bare_edge_d(bl, sec, t, up) if e is None else e, t, up)
                  for (t, up), e in zip(cols, edge)])
    fold.append(set())
    ds.append(PANEL_EDGE_D)
    # forward of the cut-out the fillet's edge runs past the cut-out's inboard wall: the next two rings step past it
    for d, step in ((c0 - 0.01, 0.06), (c0, 0.12)):
        add(d, cut=d == c0)
        for k, e in enumerate(edge):
            if e is not None and k not in fold[-1] and e + step > d:
                rings[-1][k] = point(bl, sec, e + step, *cols[k])
    for d in panel_cut_ds(bl):
        add(d, cut=True)
    add(c1, cut=True)
    for fraction in (0.5,):
        d = c1 + OUTER_RAMP * fraction
        add(d)
        cut, folded = panel_ring(bl, sec, d, n, cut=True)
        weight = fraction * fraction * (3 - 2 * fraction)
        for k in folded:
            rings[-1][k] = cut[k].lerp(rings[-1][k], weight)
    add(c1 + OUTER_RAMP)
    tip_r = len(rings) - 1
    for d in tip_ds(bl):
        add(d)
    for m in SURFACES:
        hc0, _, _ = hinge_circle(bl, sec, surface_span(bl, m)[0])
        want = bpy.data.objects[f"ruddervator_{'L' if side > 0 else 'R'}{m}"].matrix_world.translation
        if (hc0 - want).length > 2e-3:
            raise SystemExit(f"tail: hinge line {tuple(hc0)} misses the blockout's hinge empty {tuple(want)} of surface {m}")

    def tag(r, k):
        k1 = (k + 1) % M
        cove = [k in f and k1 in f for f in (fold[r], fold[r + 1])]
        if all(cove):
            return SKIN, COVE  # the cut-out's cove, painted dark: the hinge gap reads as one line
        if any(cove):
            return SKIN, RUDDER_END  # its end walls, in view through the end gaps: end ribs in the skin's paint
        if r == 0:
            return SKIN, ROOT
        if r >= tip_r:
            return SKIN, TIP
        return None

    # The unequal root strips collapse the inboard UV island unless unwrapped separately.
    p.tail_panel_grid = af.loft(p, rings, SKIN, PANEL, seams=(0, n, 2 * n), soft=(n,),
                               ring_seams=(1, 2, 3, 4, ds.index(SEAM_D), tip_r), end=tip_point(bl, side),
                               cap_slot=(STRUCT, None), cap_cls=(0, TIP), face_tag=tag)
    land_panel_root(p, p.tail_panel_grid, bare, hull, FILLET_LIP, SKIN, STRUCT, ROOT)
    build_cove_ends(bl, p, sec, SKIN)
    bmesh.ops.recalc_face_normals(p.bm, faces=p.bm.faces)
    p.bm.verts.index_update()
    p.tail_root_surface = BVHTree.FromPolygons([v.co for v in p.bm.verts],
                                              [[v.index for v in f.verts] for f in p.bm.faces if f[p.cls] == ROOT])


def build_cove_ends(bl, p, sec, skin):
    """End ribs close the circular cove up to the moving nose's swept envelope."""
    c0, c1 = cutout_span(bl)
    d0, d1 = ruddervator_mesh_span(bl)
    for wall, end, sign in ((c0, d0, 1), (c1, d1, -1)):
        axis = axis_frame(bl, sec, end)[1]
        rc = hinge_circle(bl, sec, end)[2]
        nose = [q for q in ruddervator_ring(bl, sec, end) if axis_dist(bl, sec, end, q) <= rc + COVE_GAP]
        limit = (min if sign > 0 else max)(q.dot(axis) for q in nose) - sign * COVE_GAP
        d = wall - sign * 0.005
        rc = hinge_circle(bl, sec, d)[2]
        ring = [axis_point(bl, sec, d, rc, 90 - 180 * k / 12) for k in range(13)]
        back = (min if sign > 0 else max)([q.dot(axis) for q in ring] + [limit - sign * 0.01])
        rings = [[q + axis * (plane - q.dot(axis)) for q in ring] for plane in (back, limit)]
        af.loft(p, rings, skin, RUDDER_END, seams=(0, 12))


def fillet_size(t, upper, room):
    """(along the panel, along the cone, strake weight) for the fillet section at chord fraction t: full size forward,
    a long, narrow strake running forward on the cone at the leading edge, narrowing where the ruddervator's root
    leaves no room (room: metres of fixed panel between the junction and the cut-out) and at the trailing edge."""
    from .paint import smoothstep
    le = math.exp(-t / 0.05)
    strake = math.exp(-((math.sqrt(t) / STRAKE_SIGMA) ** 2))
    if upper:
        k = 1 - 0.97 * smoothstep(0.38, 0.93, t)
    else:
        k = 1 - 0.985 * smoothstep(0.5, 0.78, t)  # to a few millimetres, so it ends on the bare root's landing line
    ra = FILLET_R * k + 0.06 * le
    # Cutout clearance narrows the panel side without pinching the body's lap curve.
    rb = (1.15 * ra + 0.1 * le) * (1 - STRAKE_NARROW * strake)
    if room is not None:
        ra = min(ra, max(0.012, room - 0.06))
    return ra, rb, strake


def fillet_reach(bl, sec, t, upper):
    """(junction d, panel metres per d, along the panel, along the cone, strake weight) of the fillet section at chord
    fraction t, or None where the face misses the cone."""
    dj = junction(bl, sec, t, upper)
    if dj is None:
        return None
    per_m = (point(bl, sec, dj + 0.01, t, upper) - point(bl, sec, dj - 0.01, t, upper)).length / 0.02
    room = (cutout_span(bl)[0] - dj) * per_m if t > hinge_t(bl, dj) - 0.08 else None
    return (dj, per_m, *fillet_size(t, upper, room))


def fillet_edge(bl, sec, t, upper):
    """d of the panel ring just under the fillet's panel edge at chord fraction t, or None where no fillet runs."""
    if t > (FILLET_T_UP if upper else FILLET_T_LO)[-1]:
        return None
    f = fillet_reach(bl, sec, t, upper)
    if f is None:
        return None
    dj, per_m, ra = f[:3]
    return dj + ra / per_m


def lower_footprint(cols, rbs):
    """The fillet's widths along the cone (fillet_size's rb, one a section), the lower face's taper relaxed: it turns
    within a few sections at both ends, which put a V corner (t 0.53) and an aft corner (t 0.73) in the lap line on the
    cone. The panel side keeps fillet_size's widths; the sections at both ends of the run stay where they are."""
    t0, t1, passes = LOWER_FOOTPRINT_SMOOTH
    idx = [i for i, (t, up) in enumerate(cols) if not up and t0 <= t <= t1]
    out = list(rbs)
    for _ in range(passes):
        prev = out[:]
        for a, b, c in zip(idx, idx[1:], idx[2:]):
            w = (cols[b][0] - cols[a][0]) / (cols[c][0] - cols[a][0])
            out[b] = 0.5 * prev[b] + 0.5 * (prev[a] * (1 - w) + prev[c] * w)
    return out


def build_fillet(bl, surf, p, side, slots):
    """The root fillet: one closed shell along the junction, both faces round the leading edge, drawn forward at the
    leading edge into a long, narrow strake on the cone. Each section is a concave arc from the panel to the cone, laid
    out in (along the cone, along the panel) from the junction and mapped onto both surfaces, so it follows the cone's
    curvature. The body boundary follows the cone's triangles, with a tangent rise into the arc. The closure stays buried."""
    SKIN, STRUCT = slots[0], slots[1]
    sec = section(bl, side)
    asurf = af.AirfoilSurface(bl, sec)
    hull = hull_triangles(bl, surf, SKIN, STRUCT)
    cols = [(t, True) for t in reversed(FILLET_T_UP)] + [(t, False) for t in FILLET_T_LO]

    def frame(t, up):
        """(junction d, junction point, panel normal, panel metres per d, cone normal, the cone's direction away
        from the junction square to it, the section's sizes)."""
        f = fillet_reach(bl, sec, t, up)
        if f is None:
            raise SystemExit(f"tail: no root junction at chord {t} ({'upper' if up else 'lower'})")
        dj, per_m = f[:2]
        J = point(bl, sec, dj, t, up)
        n_p = asurf.normal(dj, math.sqrt(t) * (1 if up else -1))
        n_b = surf.normal(*body_frame(bl, J))
        return dj, J, n_p, per_m, n_b, (n_p - n_b * n_b.dot(n_p)).normalized(), f[2:]

    ahead = frame(0.0, True)[5]  # the strake runs this way: forward along the cone from the leading edge
    frames = [frame(t, up) for t, up in cols]
    widths = lower_footprint(cols, [f[6][1] for f in frames])
    rings, p1s, p2s = [], [], []
    for (t, up), (dj, J, n_p, per_m, n_b, b, (ra, _, strake)), rb in zip(cols, frames, widths):
        reach = STRAKE_LEN * strake / rb
        ts = cosine_ts(PANEL_N)
        i = min(max(int(np.searchsorted(ts, t)) - 1, 0), PANEL_N - 1)
        join = []
        for tt in ts[i:i + 2]:
            d = fillet_edge(bl, sec, tt, up)
            join.append(point(bl, sec, bare_edge_d(bl, sec, tt, up) if d is None else d, tt, up))
        panel_join = join[0].lerp(join[1], (t - ts[i]) / (ts[i + 1] - ts[i]))
        join_offset = panel_join - facet_point(bl, sec, dj + ra / per_m, t, up)

        def on_body(x):
            """The cone point x out from the junction, carried forward by the strake in proportion."""
            s2, deg2 = body_frame(bl, J + b * x + ahead * (reach * x))
            return hull_point(bl, surf, hull, s2, deg2)

        def at(x, y):
            """The fillet point x along the cone and y along the panel from the junction. The panel side lies on the
            panel's facets, so the arc comes out of them along one line instead of crossing them where they sag."""
            body = on_body(x)[0].lerp(J, (y / ra) ** 2)
            weight = (y / ra) ** 2
            root_offset = facet_point(bl, sec, dj, t, up) - J
            return body + facet_point(bl, sec, dj + y / per_m, t, up) - J + join_offset * weight - root_offset * (1 - weight)

        # the arc in (x, y): a cubic from (0, ra) on the panel to (rb, 0) on the cone, tangent to both, so the strake
        # leaves the leading edge along it on one radius (2/3 is the quadratic arc about the junction corner)
        h = 2 / 3
        c1, c2 = (0.0, ra * (1 - h)), (rb * (1 - h), 0.0)
        sink = FILLET_EDGE_SINK * ra * max(0.0, min(1.0, (t - FILLET_NOSE_T) / 0.025))
        g = (b + ahead * reach).length  # metres on the cone per unit of x: the landing angle and run are in metres
        arc = []
        for u in FILLET_ARC:
            w = ((1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u * u, u ** 3)
            x = w[1] * c1[0] + w[2] * c2[0] + w[3] * rb
            y = w[0] * ra + w[1] * c1[1] + w[2] * c2[1]
            q = at(x, y) - n_p * (sink * (1 - u) ** 2) + on_body(x)[1] * (FILLET_LIP * u * u)
            arc.append(q)
        P1, P2 = arc[0], arc[-1]
        e = FILLET_SINK
        under, n2 = on_body(rb + FILLET_RUN / g)
        inner = [under - n2 * e, J - (n_p + n_b).normalized() * e * 1.4, P1 - n_p * e]
        rings.append(arc + inner)
        p1s.append(P1)
        p2s.append(P2)
    m = len(FILLET_ARC) - 1  # the arc's faces are skin; the lap edge's face into the cone and the closing ones structure
    le_col = len(FILLET_T_UP) - 1
    g = af.loft(p, rings, SKIN, FILLET, ring_seams=(le_col,), cap_slot=(STRUCT, STRUCT), cap_cls=(0, 0),
                face_tag=lambda r, k: (STRUCT, 0) if k >= m else None)
    chord_layer = p.bm.verts.layers.float['tail_fillet_chord']
    for (t, up), row in zip(cols, g.V):
        for vertex in row:
            vertex[chord_layer] = t * (1 if up else -1)
    g.seam_column(0)
    g.seam_column(m)
    body_boundary = conform_fillet_boundary(p, g, m, hull, FILLET_LIP)
    p2s = [tuple(vertex.co) for vertex in body_boundary]
    join_fillet_nose(p, p.tail_panel_grid, g, columns(PANEL_N), cols, FILLET_NOSE_T, STRUCT)
    edges = [edge for edge in p.bm.edges if len(edge.link_faces) == 2
             and all(face[p.cls] == FILLET for face in edge.link_faces)]
    midpoints = np.array([tuple((edge.verts[0].co + edge.verts[1].co) / 2) for edge in edges])
    body_distance = polyline_dist(midpoints, p2s)[0]
    panel_distance = polyline_dist(midpoints, p1s)[0]
    for edge, midpoint, db, dp in zip(edges, midpoints, body_distance, panel_distance):
        if db >= 0.18 or db >= dp:
            continue
        q = Vector(midpoint)
        hit, normal, _, _ = hull.find_nearest(q)
        if (q - hit).dot(normal) < -0.0001:
            _, vertex = bmesh.utils.edge_split(edge, edge.verts[0], 0.5)
            vertex.co = hit + normal * FILLET_LIP
    from .paint import smoothstep
    for vertex in {v for f in p.bm.faces if f[p.cls] == FILLET for v in f.verts}:
        t = vertex[chord_layer]
        weight = float(smoothstep(0.865, 0.93, t) if t > 0 else smoothstep(0.727, 0.78, -t))
        if weight > 0:
            hit, normal, _, _ = p.tail_root_surface.find_nearest(vertex.co)
            vertex.co = vertex.co.lerp(hit - normal * FILLET_LIP, weight)
    if side > 0:
        EDGES["fillet_panel"] = [tuple(v) for v in p1s]
        EDGES["fillet_body"] = [tuple(vertex.co) for vertex in body_boundary]


def ruddervator_ring(bl, sec, d):
    """The ruddervator's section: upper face from the trailing edge to the hinge, a half circle about the hinge line
    round the front, the lower face back. 2 (RUDDER_N + 1) + NOSE_M points; the nose's front is RUDDER_N + 1 +
    NOSE_M // 2."""
    th_ = hinge_t(bl, d)
    le, c, th, cd, td, cam = sec(d)
    hc, rn, rc = hinge_circle(bl, sec, d)
    ts = [th_ + (1 - th_) * (1 - math.cos(math.pi / 2 * k / RUDDER_N)) for k in range(RUDDER_N + 1)]
    upper = [airfoil_point(bl, le, c, th, cd, td, cam, t, True) for t in reversed(ts)]
    nose = [axis_point(bl, sec, d, rn, 90.0 - 180.0 * k / (NOSE_M + 1)) for k in range(1, NOSE_M + 1)]
    lower = [airfoil_point(bl, le, c, th, cd, td, cam, t, False) for t in ts]
    return upper + nose + lower


def build_ruddervator(bl, p, side, slots, n):
    SKIN, STRUCT, GLASS, MECH = slots[:4]
    sec = section(bl, side)
    d0, d1 = mesh_span(bl, n)
    (inset, _), (inset_out, _) = bevels(n)
    ds = surface_ds(bl, n)
    rings = [ruddervator_ring(bl, sec, d) for d in ds]
    td = thick_dir(bl, side)
    rings[0] = bevel_ring(rings[0], td, inset)
    rings[-1] = bevel_ring(rings[-1], td, inset_out)
    front = RUDDER_N + 1 + NOSE_M // 2
    last = 2 * (RUDDER_N + 1) + NOSE_M - 1
    # a long surface's skin packs as two islands, cut at a middle ring. The caps facing the split take the cove's dark
    # paint: in the end rib's light grey the two lit faces read as a bright slot from below, not a hinge gap.
    af.loft(p, rings, SKIN, RUDDER, seams=(0, front, last), soft=(front,), ring_seams=(len(ds) // 2,) if len(ds) > 5 else (),
            cap_cls=(RUDDER_END if n == SURFACES[0] else COVE, RUDDER_END if n == SURFACES[-1] else COVE))
    for f in DISCHARGERS[n]:
        le, c, t, cd, td_, cam = sec(d0 + (d1 - d0) * f)
        af.discharger(p, le + cd * (c - 0.01), cd, td_, MECH)


def bevel_ring(pts, td, d):
    """af.inset_ring on a ruddervator_ring, the skin points' inset held to a third of the section's local thickness, so
    the thin trailing edge never crosses itself (a folded end cap turns the whole shell inside out in the entry
    script's normal recalc). The nose points take the full inset."""
    inset = af.inset_ring(pts, CDIR, td, d)
    n = len(pts)
    out = []
    for i, (p, q) in enumerate(zip(pts, inset)):
        skin = i <= RUDDER_N or i >= n - 1 - RUDDER_N  # point i faces point n - 1 - i across the section
        k = min(1.0, (p - pts[n - 1 - i]).length / (3 * d)) if skin else 1.0
        out.append(p + (q - p) * k)
    return out


def hinge_axis(bl, side):
    sec = section(bl, side)
    d0, d1 = ruddervator_span(bl)
    return (hinge_circle(bl, sec, d1)[0] - hinge_circle(bl, sec, d0)[0]).normalized()


def build_tip(bl, p, side, slots):
    """The tip cap's white tail light, its formation strips and a static discharger."""
    SKIN, STRUCT, GLASS, MECH, RED, WHITE, GREEN = slots
    sec = section(bl, side)
    span = bl.VTAIL_SPAN
    sd = span_dir(bl, side)

    def edge(u):
        le, c, th, cd, td, cam = sec(span - bl.VTAIL_TIP_ROUND[0] * (1 - u))
        return bl.camber_point(le, c, cd, td, cam, 0.995)

    # on the rounded tip's trailing edge, facing out along its plan-view normal (outboard and aft)
    q = edge(TIP_LIGHT_U)
    tang = (edge(TIP_LIGHT_U + 0.01) - edge(TIP_LIGHT_U - 0.01)).normalized()
    out = (sd - tang * tang.dot(sd)).normalized()
    tip_light(p, q - out * 0.02, out, WHITE, MECH, 0.04)
    asurf = af.AirfoilSurface(bl, sec)
    back, width, t0, length = FORMATION
    t1 = t0 + length / sec(span - back)[1]
    for sgn in (1, -1):
        corners = [(span - back - width, sgn * math.sqrt(t0)), (span - back, sgn * math.sqrt(t0)),
                   (span - back, sgn * math.sqrt(t1)), (span - back - width, sgn * math.sqrt(t1))]
        faces = sf.surface_patch(p, asurf, corners, 1, 8, 0.006, -0.012, GREEN)
        underside = [asurf.point(*sf.bilinear(corners, i, j / 8)) - asurf.normal(*sf.bilinear(corners, i, j / 8)) * 0.012
                     for i in (0, 1) for j in (2, 4, 6)]
        buried = [vertex for vertex in {v for group in faces for face in group for v in face.verts}
                  if any((vertex.co - point).length < 1e-6 for point in underside)]
        bmesh.ops.dissolve_verts(p.bm, verts=buried, use_face_split=False)
    for back in DISCHARGERS["tip"]:
        le, c, t, cd, td_, cam = sec(span - back)
        af.discharger(p, le + cd * (c - 0.01), cd, td_, MECH, length=0.17)  # inside the 45 m hangar


def tip_light(p, centre, axis, lens, bezel, r):
    """A light: a dark bezel sunk into the surface with a lens dome on it (off the skin atlas, as the wing's)."""
    sf.revolve_axis(p, ((r, 0.004), (r * 0.82, 0.018), (0, 0.018)), centre, axis, TIP_LIGHT_SEG, bezel)
    sf.revolve_axis(p, ((r * 0.7, 0.01), (r * 0.66, 0.045), (r * 0.4, 0.07), (0, 0.078)), centre, axis, TIP_LIGHT_SEG,
                    lens)


# ---------- checks ----------
def check(bl, objs):
    """The blockout's checks the tail sets, rerun on the detailed meshes in the whole scene: the tip height under the
    7.5 m cap, the hangar door and depth (span at the stages' rest), the tail strike; and the moving surfaces at the four
    full pitch and yaw stick corners clear of their panel, the tail cone and each other."""
    scene = {o.name: o for o in bpy.data.collections["Centurion"].objects}
    stages = {n: o for n, o in scene.items() if "slide_axis" in o}
    saved = {n: o.location.copy() for n, o in stages.items()}
    bl.set_extension(stages, 0.0)
    allv = [v for o in scene.values() if o.type == "MESH" for v in bl.world_mesh(o)[0]]
    span = max(v.x for v in allv) - min(v.x for v in allv)
    height = max(v.z for v in allv)
    lo_y, hi_y = min(v.y for v in allv), max(v.y for v in allv)
    for n, o in stages.items():
        o.location = saved[n]
    bpy.context.view_layer.update()
    top = max(v.z for n in PARTS for v in bl.world_mesh(objs[n])[0])
    cap = bl.S6_TAIL_TIP_MAX + 0.015
    res = {
        "vtail_tip_height": {"value": round(top, 3), "limit": f"<= {cap:.3f} m (the {bl.S6_TAIL_TIP_MAX} m cap; "
                                                             f"blockout 7.511) and < {bl.TAIL_TOP_LIMIT}",
                             "pass": top <= cap and top < bl.TAIL_TOP_LIMIT},
        "hangar_door_fit": {"value": f"{span:.2f} x {height:.2f}", "limit": f"{bl.HANGAR_DOOR_W} x {bl.HANGAR_DOOR_H}",
                            "pass": span < bl.HANGAR_DOOR_W and height < bl.HANGAR_DOOR_H},
        "hangar_depth_centred": {"value": {"nose_m": round(-bl.HANGAR_DEPTH / 2 - lo_y, 3),
                                           "tail_m": round(bl.HANGAR_DEPTH / 2 - hi_y, 3)},
                                 "limit": f"inside the {bl.HANGAR_DEPTH} m hangar with the spawn at its centre",
                                 "pass": lo_y > -bl.HANGAR_DEPTH / 2 and hi_y < bl.HANGAR_DEPTH / 2},
    }
    strike = bl.tail_strike(scene)
    res[bl.TAIL_STRIKE_KEY] = {"value": strike["value"], "limit": strike.get("limit"), "pass": strike["pass"],
                               "first_contact": strike["first_contact"]}
    clear = {}
    ranges = dict(zip(SURFACES, bl.SPLIT_TAIL["ranges"]))

    def turned(name, deg):
        hinge = scene[name]
        origin = hinge.matrix_world.translation
        axis = (hinge.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()
        verts, polys = bl.world_mesh(scene[name + "_visible"])
        rm = Matrix.Translation(origin) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-origin)
        return BVHTree.FromPolygons([rm @ v for v in verts], polys)

    # Full pitch and full yaw each way: every surface at its pitch plus yaw range, and the two as far apart as the game's
    # mixing ever turns them (the sign of a side's yaw doesn't change how far apart its surfaces stand).
    for s in ("_L", "_R"):
        fixed = {n: BVHTree.FromPolygons(*bl.world_mesh(scene[n])) for n in ("vtail" + s, "tailcone")}
        for pitch, yaw in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            trees = {n: turned(f"ruddervator{s}{n}", pitch * ranges[n][0] + yaw * ranges[n][1]) for n in SURFACES}
            for n, tree in trees.items():
                others = {**fixed, **{f"ruddervator{s}{m}": trees[m] for m in SURFACES if m > n}}
                for name, other in others.items():
                    hits = len(tree.overlap(other))
                    if hits:
                        clear[f"ruddervator{s}{n}@pitch{pitch:+d},yaw{yaw:+d}~{name}"] = hits
    res["ruddervators_clear_at_full_throw"] = {"value": clear or "clear", "limit": f"(pitch, yaw) ranges {ranges} deg, summed",
                                               "pass": not clear}
    found = {k: v for k, v in bl.overlaps(scene).items() if any(n in k for n in PARTS)}
    res["no_overlap_unjointed_parts"] = {"value": found or "none", "pass": not found}
    return res


# ---------- paint layout ----------
# The fixed panel's skin follows its structure (docs/concepts/details/detail_tail_laser.png): long spanwise skins
# between a leading-edge joint, the front spar, a stringer lap and the rear spar, each strip spliced at its own
# stations so no chordwise joint runs the full chord; fastener rows only on the spars, the leading-edge joint, the
# splices and the hinge fittings, and a single rivet row (no joint) on each rib. Positions are (d, chord fraction).
LE_JOINT, FRONT_SPAR, REAR_SPAR = 0.075, 0.16, 0.52
LAPS = ((0.34, 1), (0.30, -1))  # stringer lap joints between the spars: chord fraction, face (+1 upper, -1 lower)
# Chordwise splices per strip: (chord fraction from, to, face (0 both), stations)
SPLICES = ((LE_JOINT, FRONT_SPAR, 0, (2.3, 3.9, 5.5, 7.0)),
           (FRONT_SPAR, REAR_SPAR, 1, (3.0, SEAM_D, 6.1)),
           (FRONT_SPAR, REAR_SPAR, -1, (2.7, SEAM_D, 6.3)),
           (REAR_SPAR, 1.01, 0, (3.4, 5.8)))
RIB_PITCH, RIB_FROM = 0.6, 0.6  # rib rivet rows on the fixed panel, metres along the span, from this d out
# (the ruddervator has none: below a texel at 61 px/m its rows read as speckle in Cycles)
# The dielectric tip cap starts this far outboard of the cut-out's outer wall (tip_joint): on the rounded tip's ring at
# u 0.82 (TIP_U), clear of the cut-out's end and OUTER_RAMP, which beside a joint read as one lid edge from the side
TIP_CAP_GAP = 0.26
DIELECTRIC = (5.9, 0.3, 0.7, 0.4, 0.1, 1)  # a flush antenna window on the upper face near the tip
# Access panels only where there is something to reach, each inside one rib bay of the lower torque box (d, chord
# fraction, width along d, width along the chord, corner radius, face): the inboard actuator's attachment (bay 2.7 to
# 4.2) and the outer hinge fitting with the outboard actuator (bay 6.3 to 6.6)
ACCESS = ((3.65, 0.45, 0.35, 0.24, 0.05, -1), (6.45, 0.44, 0.22, 0.22, 0.05, -1))
# Each surface's actuator access panels, d of each: by each actuator's horn, one on the short inboard surface
RUDDER_ACCESS = {"1": (2.55,), "2": (4.9, 6.6)}
LAP_CONTRAST = 0.5  # lap joints' groove darkening and depth, as a fraction of the full-span joints'
# The tail code on both upper faces, the side the game's chase camera sees: (text, d, chord fraction, font size in
# metres). It reads from behind, glyphs upright toward the nose, so the right panel keeps its own islands.
TAIL_CODE = (("MR", 4.6, 0.265, 0.71), ("1043", 4.6, 0.43, 0.27))
PAINT_RGB = (0.38, 0.39, 0.405)  # paint.PAINT[HULL]
WINDOW_RGB = (0.33, 0.335, 0.34)  # the dielectric antenna window
BRACKET_RGB = (0.35, 0.36, 0.37)
DARK = (0.10, 0.105, 0.11)
LE_METAL = ((0.46, 0.47, 0.48), 0.54, 0.2)  # the shared satin metal (wing.SATIN): rgb, smoothness, metal
MARKING = (0.17, 0.175, 0.185)  # fuselage_aft's low-visibility serial grey
RED = (0.55, 0.10, 0.08)


def coords(bl):
    """Paint coordinates of the left panel's section family: (d, chord fraction, chord, upper face)."""
    span = bl.VTAIL_SPAN
    return af.SectionCoords(section(bl, 1), np.linspace(ROOT_D - 0.2, span + 0.1, 80), origin=root_le(bl, 1),
                            axis=span_dir(bl, 1))


def polyline_dist(pos, pts):
    """Distance from points to a 3D polyline, and the arc length along it of the nearest point."""
    from .paint import np
    pts = np.asarray(pts)
    a, b = pts[:-1], pts[1:]
    ab = b - a
    L = np.linalg.norm(ab, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(L)])
    best = np.full(len(pos), np.inf)
    along = np.zeros(len(pos))
    for i in range(len(a)):
        t = np.clip(((pos - a[i]) @ ab[i]) / max(L[i] ** 2, 1e-12), 0, 1)
        dist = np.linalg.norm(pos - (a[i] + t[:, None] * ab[i]), axis=1)
        m = dist < best
        best[m] = dist[m]
        along[m] = cum[i] + t[m] * L[i]
    return best, along




def paint(cv, text_mask):
    """The group's paint over a Canvas (m4/paint.py)."""
    np = cv.xp
    from .paint import poly_sdf, rrect_sdf, smoothstep
    bl = cv.surf.bl
    cls = cv.cls
    pos, nrm = cv.pos.copy(), cv.nrm.copy()
    right = pos[:, 0] < 0  # the right-hand parts paint as the left; only the text reads per side
    pos[right, 0] *= -1
    nrm[right, 0] *= -1
    from .paint import locate_section
    X, U, C, UP = locate_section(coords(bl), pos, nrm)
    C = np.maximum(C, 1e-3)
    S = U * C
    up, lo = UP.astype(float), (~UP).astype(float)
    on = lambda *cs: np.isin(cls, cs).astype(float)
    P, RT, TP, FL, RD, RE, CV, BR = (on(c) for c in SKIN_CLASSES)
    PANELS = np.clip(P + RT + TP, 0, 1)
    d0, d1 = ruddervator_span(bl)
    sec = section(bl, 1)
    dd = np.linspace(d0, d1, 24)
    th_ = np.interp(X, dd, [hinge_t(bl, d) for d in dd])  # the hinge line's chord fraction, which grows in the rounding
    t_se = np.interp(X, dd, [skin_end_t(bl, sec, d) for d in dd])
    S_se = t_se * C  # the fixed skin's end at the cove lip, metres from the leading edge
    spans = [surface_span(bl, n) for n in SURFACES]
    brackets = [a + (b - a) * f for a, b in spans for f in HINGE_BRACKETS]
    tip_joint = cutout_span(bl)[1] + TIP_CAP_GAP  # the dielectric tip cap over the rounded tip starts here

    for c in SKIN_CLASSES:
        m = cls == c
        cv.albedo[m] = PAINT_RGB
        cv.smooth[m] = 0.42

    def side_mask(s):
        return up if s > 0 else lo if s < 0 else 1.0

    def spanwise(mask, u0, s, rows, x0, x1):
        """A joint along the span at chord fraction u0: rows 2 a fastener row either side, 1 a single row, 0 none (a
        lap joint, at LAP_CONTRAST)."""
        d = np.abs(U - u0) * C
        m = mask * side_mask(s) * (X >= x0) * (X <= x1)
        k = 1.0 if rows else LAP_CONTRAST
        cv.groove(d, depth=-0.0035 * k, darken=0.35 * k, mask=m)
        if rows:
            cv.fasteners(d, X, 0.03 if rows == 2 else 0.0, mask=m * (d < 0.08))

    def splice(mask, x0, rows=True):
        d = np.abs(X - x0)
        cv.groove(d, mask=mask)
        if rows:
            cv.fasteners(d, S, 0.025, mask=mask * (d < 0.06))

    def panel(mask, x, s0, s1, wx, r, s):
        """An access panel, x the centre along d, s0 to s1 metres from the leading edge."""
        sdf = rrect_sdf(X, S, x - wx / 2, x + wx / 2, s0, s1, r)
        m = mask * side_mask(s)
        cv.groove(np.abs(sdf), mask=m)
        cv.fasteners(np.abs(sdf), X + S, 0.028, mask=m * (np.abs(sdf) < 0.06))
        return sdf

    def stamp(body, x, s, size, mask, rgb):
        """Text in (d, chord metres) on the upper faces: it reads from behind with its glyphs upright toward the
        nose, so it runs inboard on the left panel and outboard on the right."""
        img = text_mask(body)
        ppm = 48 / size
        f = int(ppm * cv.px / 1.5)  # box-filter to about 1.5 raster pixels a texel, as Canvas.decal
        if f >= 2:
            hh, ww = (img.shape[0] // f) * f, (img.shape[1] // f) * f
            img = img[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
            ppm /= f
        h, w = img.shape
        lu = (X - x) * np.where(right, 1.0, -1.0) * ppm + w / 2
        lv = -(S - s) * ppm + h / 2
        inside = (lu >= 0) & (lu < w - 1) & (lv >= 0) & (lv < h - 1) & (mask > 0)
        x_, y_ = lu[inside], lv[inside]
        x0, y0 = x_.astype(int), y_.astype(int)
        tx, ty = x_ - x0, y_ - y0
        cov = np.zeros(cv.n)
        cov[inside] = (img[y0, x0] * (1 - tx) * (1 - ty) + img[y0, x0 + 1] * tx * (1 - ty)
                       + img[y0 + 1, x0] * (1 - tx) * ty + img[y0 + 1, x0 + 1] * tx * ty)
        cv.paint(cov * mask, rgb=rgb)

    # panel tones: each skin between joints differs a little
    strip = np.searchsorted(np.array((LE_JOINT, FRONT_SPAR, 0.32, REAR_SPAR)), U)
    bay = np.zeros(cv.n, int)
    for u0, u1, s, xs in SPLICES:
        m = (U >= u0) & (U < u1) & ((UP if s > 0 else ~UP) if s else True)
        bay[m] = np.searchsorted(np.array(xs), X[m])
    # the panel's root and tip faces are the same skins as the rest of it: the tone changes only on joints
    kind = np.where(PANELS > 0, PANEL, cls)
    cell = ((strip * 16 + bay) * 2 + UP) * 16 + np.clip(kind - 59, 0, 15)
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    tone[(PANELS > 0) & (X > tip_joint)] = 0.0  # the tip cap in the panel's mean tone, so it reads as one with it
    cv.albedo *= (1 + 0.045 * tone * on(*SKIN_CLASSES))[:, None]

    # ---- fixed panel ----
    rgb, smooth, metal = LE_METAL
    cv.paint(PANELS * smoothstep(LE_JOINT, LE_JOINT - 0.01, U) * smoothstep(tip_joint, tip_joint - 0.1, X),
             rgb=rgb, smooth=smooth, metal=metal)
    span_end = tip_joint
    spanwise(PANELS, LE_JOINT, 0, 1, ROOT_D, span_end)
    spanwise(PANELS, FRONT_SPAR, 0, 2, ROOT_D, span_end)
    spanwise(PANELS, REAR_SPAR, 0, 2, ROOT_D, span_end)
    for u0, s in LAPS:
        spanwise(PANELS, u0, s, 0, ROOT_D, span_end)
    for u0, u1, s, xs in SPLICES:
        m = PANELS * side_mask(s) * (U >= u0) * (U <= u1)
        for x in xs:
            splice(m, x)
    splice_x = [x for *_, xs in SPLICES for x in xs]
    for x in np.arange(RIB_FROM, tip_joint - 0.25, RIB_PITCH):
        if min(abs(x - sx) for sx in splice_x) > 0.2:
            d = np.abs(X - x)
            cv.fasteners(d, S, 0.0, mask=PANELS * (U > LE_JOINT + 0.012) * (U < REAR_SPAR - 0.012) * (d < 0.03))
    chord = lambda x: float(sec(x)[1])
    for x, u, wx, ws, r, s in ACCESS:
        panel(PANELS, x, u * chord(x) - ws / 2, u * chord(x) + ws / 2, wx, r, s)
    x, u, wx, ws, r, s = DIELECTRIC
    sdf = panel(PANELS, x, u * chord(x) - ws / 2, u * chord(x) + ws / 2, wx, r, s)
    cv.paint(cv.fill_coverage(sdf + 0.03) * PANELS * up, rgb=WINDOW_RGB, smooth=0.5)
    # a thin red keep-clear line ahead of the hinge, broken at the flush fittings
    near_cut = PANELS * (X > d0 - 0.02) * (X < d1 + 0.02)
    clear_of_fittings = np.min([np.abs(X - x) for x in brackets], axis=0) > 0.22
    cv.paint(cv.coverage(np.abs(S - (S_se - 0.09)), 0.022) * near_cut * clear_of_fittings, rgb=RED)
    # crush hazard symbols by the ruddervator's inboard end: thin red triangles
    for s in (1, -1):
        sx, su = d0 + 0.35, hinge_t(bl, d0) * chord(d0) - 0.45
        tri = [(sx - 0.1, su - 0.08), (sx + 0.1, su - 0.08), (sx, su + 0.1)]
        cv.paint(cv.coverage(np.abs(poly_sdf(X, S, tri)), 0.018) * PANELS * side_mask(s), rgb=RED)
    # hinge fittings: a fastened doubler under each, the fitting itself a shade darker
    for x in brackets:
        sdf = rrect_sdf(X, S, x - 0.16, x + 0.16, S_se - BRACKET_LEN - 0.1, S_se - 0.012, 0.03)
        cv.groove(np.abs(sdf), mask=PANELS * up)
        cv.fasteners(np.abs(sdf), X + S, 0.03, mask=PANELS * up * (np.abs(sdf) < 0.06))
    cv.paint(BR, rgb=BRACKET_RGB, smooth=0.4)
    # the trailing edge root strip and the tip cap's trailing edge: a darker wedge
    cv.paint(PANELS * smoothstep(0.965, 0.975, U), rgb=(0.30, 0.305, 0.31))
    # tip cap: painted as the panel (a darker cap read as a separate part at game distance), on a lap-contrast joint
    # fastened aft of the satin strip (a full-depth joint wrapped the leading edge as a dark curve)
    dj = np.abs(X - tip_joint)
    cv.groove(dj, 0.02, depth=-0.0035 * LAP_CONTRAST, darken=0.35 * LAP_CONTRAST, mask=PANELS)
    cv.fasteners(dj, S, 0.03, mask=PANELS * (dj < 0.06) * (U > LE_JOINT))
    # the tail code
    for body, x, u, size in TAIL_CODE:
        stamp(body, x, u * chord(x), size, PANELS * up * (X < tip_joint), MARKING)

    # ---- root fillet: a fastened panel joint and a painted, feathered body landing ----
    if EDGES:
        fm = FL > 0
        d_pan, a_pan = polyline_dist(pos[fm], EDGES["fillet_panel"])
        full = lambda v: _scatter(fm, v, cv.n)
        dp, ap = full(d_pan), full(a_pan)
        joint = FL * (U > LE_JOINT)
        cv.groove(dp, 0.018, mask=joint * (dp < 0.03))
        cv.fasteners(np.abs(dp - 0.04), ap, 0.0, mask=joint * (dp < 0.07))
        rgb, smooth, metal = LE_METAL
        cv.paint(FL * smoothstep(LE_JOINT, LE_JOINT - 0.01, U) * smoothstep(0.16, 0.1, dp),
                 rgb=rgb, smooth=smooth, metal=metal)
        leading_join = Vector(EDGES['fillet_panel'][len(FILLET_T_UP) - 1])
        leading_d = (leading_join - root_le(bl, 1)).dot(span_dir(bl, 1))
        root_finish = (PANELS + FL) * smoothstep(LE_JOINT, LE_JOINT - 0.01, U)
        root_finish *= smoothstep(leading_d + 0.2, leading_d + 0.04, X)
        cv.paint(root_finish, rgb=PAINT_RGB, smooth=0.42, metal=0.0)

    # ---- moving surfaces: long spanwise skins, a splice mid-span on each, end ribs, the hinge-fitting rows ----
    spanwise(RD, th_ + 0.035, 0, 1, d0, d1)
    spanwise(RD, 0.80, 0, 0, d0, d1)
    for n in SURFACES:
        a, b = mesh_span(bl, n)
        for x in ((a + b) / 2, a + 0.07, b - 0.12 if n == SURFACES[-1] else b - 0.07):
            splice(RD * (U > th_) * (X > a - 0.01) * (X < b + 0.01), x)
    cv.paint(RD * smoothstep(0.965, 0.975, U), rgb=(0.30, 0.305, 0.31))
    for x in brackets:  # the moving half of each hinge fitting: a fastened plate on the nose skin
        sdf = rrect_sdf(X, S, x - 0.11, x + 0.11, th_ * C - 0.05, th_ * C + 0.3, 0.03)
        cv.groove(np.abs(sdf), mask=RD * up)
        cv.fasteners(np.abs(sdf), X + S, 0.028, mask=RD * up * (np.abs(sdf) < 0.06))
    for x in (x for n in SURFACES for x in RUDDER_ACCESS[n]):  # on the lower face
        panel(RD, x, 0.72 * chord(x) - 0.12, 0.72 * chord(x) + 0.12, 0.3, 0.04, -1)
    cv.paint(RE, rgb=(0.34, 0.345, 0.355), smooth=0.38)
    c0, c1 = cutout_span(bl)
    ends = 1 - smoothstep(c0, c0 + 0.14, X) * smoothstep(c1, c1 - 0.14, X)
    cv.paint(CV * (1 - ends), rgb=DARK, smooth=0.2)
    cv.paint(CV * ends, rgb=(0.34, 0.345, 0.355), smooth=0.38)


def _scatter(mask, values, n):
    from .paint import np
    out = np.zeros(n)
    out[mask] = values
    return out
