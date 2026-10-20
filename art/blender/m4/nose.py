"""Part group 1: the nose and forward fuselage, stations 0 to 17.

Parts: radar_F_fairing (the dielectric radome), nose (flight deck, windscreen, nose gear well), fuselage_F
(the refuelling receptacle and the forward bay with its interior), geardoor_FL/FR and baydoor_FL/FR (their
_visible meshes), and the flight deck's exits: the escape hatches nose_hatch_L/R and the crew door, nose_door_visible. The outer surface is the blockout's fus_point surface at 64 vertices a ring instead of 32; joints
stay at stations 3.625, 7 and 17. The nose leg that folds into the well is the gear group's (m4/gear.py), which
checks its fit against WELL_S, WELL_X and well_ceiling. The glass is the opaque tint over uncut skin; the flight
deck itself is the interior's (art/blender/cockpit/flightdeck.py). The hatch and door openings and their panels are
m4/nose_exits.py's.

Step 6 stretched step 5's nose 1.45 times along the body (the radome and the blockout's panes) on a 1.65 times longer
taper. The windscreen keeps the step 5 M4 panes' angles round the body, their stations mapped so the radome joint stays
at 3.625 and the side panes end at 6.92, inside the nose part; what stood behind the panes on step 5 (receptacle,
static ports) moved onto fuselage_F. The crew door is under the left side pane, ahead of the forward bay's
full-height front wall.

Positions are (station, angle) on the fuselage surface: angle in degrees from the top, positive toward +X (the left
wing), as the blockout's fus_point. Shapes listed for the +X side are mirrored to -X."""

import math

import numpy as np

from mathutils import Matrix, Vector

import flightdeck_layout as fl

from . import body_structure, nose_bay, nose_exits, render
from . import surface as sf
from .surface import DOOR, FITTING, FRAME, HULL, RADOME, N, KEEL, CHINE_K
from .paint import INTERIOR

GROUP = "nose"
PARTS = ("radar_F_fairing", "nose", "fuselage_F", "geardoor_FL_visible", "geardoor_FR_visible",
         "baydoor_FL_visible", "baydoor_FR_visible", "nose_hatch_L", "nose_hatch_R", "nose_door_visible")
BUDGET_TRIS = 19000  # damage stage 2: reclaim and leaner damage structure (was 16000)
# Bay doors share their twins' islands; gear doors keep unique islands for KEEP CLEAR on both sides.
MIRROR_PARTS = {"baydoor_FR_visible": "baydoor_FL_visible", "nose_hatch_R": "nose_hatch_L"}
# Close-ups (m4/render.py's view form); the first four make the contact sheet.
VIEWS = {
    "nose34": (50, (9.5, -10.5, 8.0), (0.0, 7.4, 3.9)),
    "nose_side": (("ortho", 21.0, render.SIDE), (30.0, 9.0, 3.9), None),
    "nose_low": (36, (-8.0, -5.5, 0.6), (0.0, 7.5, 2.0)),
    "nose_top": (40, (-5.5, 18.5, 10.8), (0.0, 7.0, 5.2)),
    "glazing": (45, (6.5, 0.5, 6.6), (0.9, 5.2, 4.5)),
    "exits": (32, (7.0, 2.0, 9.0), (0.6, 6.3, 4.4)),
    "evs_camera": (50, (1.6, 2.1, 5.7), (0.0, 3.9, 4.85)),
}

RADOME_STATIONS = (0.006, 0.015, 0.028, 0.044, 0.116, 0.218, 0.363, 0.551, 0.798, 1.088, 1.45, 1.885, 2.32, 2.755, 3.19, 3.625)
RADOME_TIP_RING = 1.088  # the radome is cut here into a tip and a band so neither island stretches
NOSE_RING_STEP = 0.2

WELL_S, WELL_X, WELL_CEILING = (3.95, 6.85), 0.72, 2.6  # nose gear well: the blockout's door stations and hinge x
WELL_K = (28, 36)  # ring vertices moved onto the well edges, x = +-WELL_X (the nearest columns that never cross)
# The well's roof rises between the roof frames, over the retracted wheels: the 1.1 m wheels need more than the 1.2 m
# from the belly to the 2.6 m roof once the doors' thickness and a margin come off.
WELL_DOME = (4.55, 4.85, 5.65, 5.95, 0.12)  # rise from, full from, full to, fall to, rise
DRAG_KNEE = (5.05, 1.58)  # the nose leg's folding drag brace meets its upper link here (station, z), inside the well
# Nose gear doors: thickness, the ribs' stations across the inner face and the beam's run along it (kept off station
# 6.0, where the trunnion's ends and bearing blocks sit just above the closed doors), the stiffeners' depth.
GEAR_DOOR_T = 0.04
GEAR_DOOR_RIBS = (4.1, 4.65, 5.65, 6.7)
GEAR_DOOR_BEAM_S, GEAR_DOOR_BEAM_X = (4.1, 6.7), 0.36
GEAR_DOOR_RIB_H = 0.05
# The gear and bay doors' outer skin: paint's DOOR colour without finish()'s edge wear (m4/paint.py), whose curvature
# mask spreads over the whole border quads of these coarse slabs as blotches.
DOOR_SKIN = 11
GEAR_DOOR_SKIN = 12
# Forward bay roof, the whole length of the bay: the stock bay mounts sit centred on the hardpoint (CenturionAuthor puts
# it 0.4 m under fuselage_M's pivot, z 3.55), the tallest, the ARAD-116 x4, reaching 0.60 m over it, and the longest,
# the 500 kg bombs x12, from station 7.73, so the roof's frames and rack beam stand BAY_ROOM over every store
# (check, bay_fit).
BAY_CEILING, BAY_ROOM = 4.40, 0.05
BAY_K = (25, 39)  # hull columns moved onto the bay doors' hinge lines (141 deg) inside the bay
BAY_FRAMES = (9.8, 11.0, 12.2, 13.4, 14.6, 15.8)  # the skin's frame lines (STATION_LINES)
DOOR_SEAM = 0.35  # degrees between the two bay doors' inner edges where they meet on the keel line (1.7 cm)
RECEPTACLE_S, RECEPTACLE_K = (7.3, 8.5), (-1, 1)  # dorsal, behind the flight deck
RECEPTACLE_DEPTH = (0.22, 0.04)  # slipway depth at its forward and aft ends
# The forward bay door (stations, angles), +X side: the blockout's, its free edge carried on to the keel line, where the
# doors close against each other. A keel strip between them crossed the open bay as a beam (owner, 2026-10-15).
BAY_DOOR = (7.4, 16.6, 141.0, 180.0 - DOOR_SEAM / 2)

# Windscreen, +X side (787-style four panes, SPEC "flight deck"). Corners run c0 -> c1 along the fuselage and
# c0 -> c3 across it, as (station, angle).
PANES = (
    ((4.020, 1.3), (5.273, 1.3), (5.536, 43.7), (4.099, 60.2)),  # front
    ((5.606, 44.0), (6.591, 50.8), (6.920, 77.1), (4.169, 61.0)),  # side, one post width behind the front
)
GLASS_UP, FRAME_UP = 0.012, 0.022

BLADES = (  # station, angle, height, root chord, tip chord, sweep, part
    (9.65, 0.0, 0.38, 0.42, 0.16, 0.22, "fuselage_F"),  # UHF, dorsal
    (3.80, 180.0, 0.26, 0.24, 0.11, 0.13, "nose"),  # VHF, ventral, between the radome joint and the gear well
)
PITOT = (3.89, 76.0)
TEMP_PROBE = (5.01, 112.0)  # total air temperature probe, below the chine
SIDE_BLADE = (6.39, 148.0, 0.2)  # L-band blades on the lower nose, between the avionics doors and the well
GPS_DOME = (6.8, 0.0)
AOA_VANE = (4.68, 100.0)
SATCOM = (11.1, 0.0)  # ahead of the dorsal wing fairing, which leaves the crown at about 12.2
# Red anti-collision, bottom; the top one is on the wing fairing's crest (fuselage_aft), which covers the crown here.
BEACONS = ((7.18, 180.0, "fuselage_F"),)
FORMATION_SIZE = (0.6, 0.08)
# The forward screen's camera (owner): an enhanced-vision housing on the crown between the radome joint and the
# windscreen, its dark window looking ahead, where the flight deck screen's EXT CAM view is said to come from (the
# screen is a window on the pilot's eye in game; nothing renders from here). Station, the body's centre above the skin.
EVS_CAMERA = (3.85, 0.035)


def resolve(surf, corners, side=1):
    out = []
    for s, a in corners:
        a = surf.deg_for_z(s, a[1]) if isinstance(a, tuple) else a
        out.append((s, side * a))
    return out


def side_corners(corners, side):
    return [(s, side * a) for s, a in corners]


def build(bl, surf, slots):
    SKIN, STRUCT, GLASS, MECH, LIGHT = slots[:5]
    parts = {}

    def part(name):
        parts[name] = sf.Part(name, (SKIN,))
        return parts[name]

    # ---- radome ----
    p = part("radar_F_fairing")
    g = sf.hull(p, surf, RADOME_STATIONS, SKIN, RADOME, pole=Vector((0, bl.st(0.0), bl.NOSE_TIP_Z)), cap_slot=STRUCT)
    g.seam_column(0)
    g.seam_column(KEEL)
    g.seam_ring(sf.ring_index(g, RADOME_TIP_RING))
    sf.mirror_columns(p, g, KEEL, N)
    p.mirror_pairs += [(g.pole_faces[k], g.pole_faces[N - 1 - k]) for k in range(KEEL, N)]

    # ---- nose ----
    p = part("nose")
    joints = (RADOME_STATIONS[-1], 7.0)
    st = sf.merge_stations(sf.frange(*joints, NOSE_RING_STEP), joints + WELL_S)

    def well_angles(s, k):
        if k in WELL_K and WELL_S[0] - 1e-6 <= s <= WELL_S[1] + 1e-6:
            a = surf.deg_for_x(s, WELL_X)
            return a if k == WELL_K[0] else 360.0 - a
        return sf.ring_deg(k)

    g = sf.hull(p, surf, st, SKIN, HULL, angles=well_angles, cap_slot=STRUCT)
    for k in (CHINE_K[0], KEEL, CHINE_K[1]):
        g.seam_column(k)
    r0, r1 = sf.ring_index(g, WELL_S[0]), sf.ring_index(g, WELL_S[1])
    sf.recess(p, g, r0, r1, WELL_K[0], WELL_K[1], lambda q, r, k: Vector((q.x, q.y, well_ceiling(g.stations[r]))), SKIN, INTERIOR)
    sf.mirror_columns(p, g, KEEL, CHINE_K[1], rows=[r for r in range(len(g.stations) - 1)
                      if g.stations[r + 1] <= CREW_DOOR[0] or g.stations[r] >= CREW_DOOR[1]])
    nose_exits.build(bl, surf, p, g, {n: part(n) for n in ("nose_hatch_L", "nose_hatch_R", "nose_door_visible")}, slots)
    nose_details(bl, surf, p, slots)
    well_details(bl, surf, p, slots)

    # ---- fuselage_F ----
    p = part("fuselage_F")
    joints = (7.0, 17.0)
    st = sf.merge_stations(sf.frange(*joints, 1.0), joints + (BAY_DOOR[0], BAY_DOOR[1]) + RECEPTACLE_S)

    def bay_angles(s, k):
        if k in BAY_K and BAY_DOOR[0] - 1e-6 <= s <= BAY_DOOR[1] + 1e-6:
            return BAY_DOOR[2] if k == BAY_K[0] else 360.0 - BAY_DOOR[2]
        return sf.ring_deg(k)

    g = sf.hull(p, surf, st, SKIN, HULL, angles=bay_angles, cap_slot=STRUCT)
    for k in (CHINE_K[0], KEEL, CHINE_K[1]):
        g.seam_column(k)
    b0, b1 = sf.ring_index(g, BAY_DOOR[0]), sf.ring_index(g, BAY_DOOR[1])

    def bay_roof(q, r, k):
        """The bay's roof over each hull vertex of the opening: walls straight up from the hinge lines."""
        t = (k - BAY_K[0]) / (BAY_K[1] - BAY_K[0])
        xe = g.V[r][BAY_K[0]].co.x
        return Vector((xe * (1 - 2 * t), q.y, BAY_CEILING))

    sf.recess(p, g, b0, b1, BAY_K[0], BAY_K[1], bay_roof, SKIN, INTERIOR)
    q0, q1 = sf.ring_index(g, RECEPTACLE_S[0]), sf.ring_index(g, RECEPTACLE_S[1])

    def slipway(q, r, k):
        t = (g.stations[r] - RECEPTACLE_S[0]) / (RECEPTACLE_S[1] - RECEPTACLE_S[0])
        return q - surf.normal(g.stations[r], sf.ring_deg(k)) * (RECEPTACLE_DEPTH[0] + (RECEPTACLE_DEPTH[1] - RECEPTACLE_DEPTH[0]) * t)

    sf.recess(p, g, q0, q1, RECEPTACLE_K[0], RECEPTACLE_K[1], slipway, SKIN, INTERIOR)
    sf.mirror_columns(p, g, KEEL, CHINE_K[1])
    fwd_fuselage_details(bl, surf, p, slots)
    receptacle(bl, surf, p, slots)
    bay_interior(bl, surf, p, g, slots)
    body_structure.build_section(bl, surf, p, slots, 7.0, 17.0, bays=[BAY_DOOR[:2]])

    # ---- doors ----
    for sfx, side in (("L", 1), ("R", -1)):
        p = part(f"geardoor_F{sfx}_visible")
        gear_door(bl, surf, p, side, slots)
        p = part(f"baydoor_F{sfx}_visible")
        bay_door(surf, p, side, slots)
        bay_door_ribs(surf, p, side, STRUCT)
    return parts


def bay_door(surf, p, side, slots):
    """The blockout's door band with the aft doors' bevelled rim."""
    s0, s1, a0, a1 = BAY_DOOR
    ss = [s0, s0 + 0.04] + sf.frange(s0 + 0.12, s1 - 0.12, 1.5) + [s1 - 0.04, s1]
    aa = [a0, a0 + 1.2] + sf.frange(a0 + 3.4, a1 - 3.4, 5.6) + [a1 - 1.2, a1]
    pts = [[surf.point(s, side * a) for a in aa] for s in ss]
    normals = [[surf.normal(s, side * a) for a in aa] for s in ss]

    def rise(i, j):
        return (0.005, 0.020, 0.044)[min(i, len(ss) - 1 - i, j, len(aa) - 1 - j, 2)]

    _, bottom, _ = sf.slab(p, pts, normals, rise, 0.001, slots[0], cls=DOOR_SKIN)
    p.tag(bottom, slots[1])


def bay_door_ribs(surf, p, side, STRUCT):
    """A forward bay door's inner structure, seen when it opens: curved ribs on the skin's frame lines and a beam along
    its middle, standing into the bay from the door's inner face."""
    s0, s1, a0, a1 = BAY_DOOR
    for s in (s0 + 0.12,) + BAY_FRAMES + (s1 - 0.12,):
        corners = side_corners(((s - 0.025, a0 + 2.5), (s + 0.025, a0 + 2.5), (s + 0.025, a1 - 1.0), (s - 0.025, a1 - 1.0)), side)
        sf.surface_patch(p, surf, corners, 1, 6, 0.008, -0.055, STRUCT)
    am = (a0 + a1) / 2
    corners = side_corners(((s0 + 0.15, am - 0.8), (s1 - 0.15, am - 0.8), (s1 - 0.15, am + 0.8), (s0 + 0.15, am + 0.8)), side)
    sf.surface_patch(p, surf, corners, 8, 1, 0.008, -0.07, STRUCT)
    for s in (8.0, 10.0, 12.0, 14.0, 16.0):
        corners = side_corners(((s - 0.06, a0 + 0.7), (s + 0.06, a0 + 0.7),
                               (s + 0.06, a0 + 3.5), (s - 0.06, a0 + 3.5)), side)
        sf.surface_patch(p, surf, corners, 1, 2, 0.008, -0.11, STRUCT)
    for s in (9.4, 14.8):
        corners = side_corners(((s - 0.075, am - 1.1), (s + 0.075, am - 1.1),
                               (s + 0.075, am + 1.1), (s - 0.075, am + 1.1)), side)
        sf.surface_patch(p, surf, corners, 1, 2, -0.055, -0.16, STRUCT)


def lift_light(p, surf, s, a, slots, colour_slot, r=0.11):
    """A beacon: a low skin-coloured base with a lens dome on it."""
    SKIN = slots[0]
    c, n = surf.point(s, a), surf.normal(s, a)
    sf.revolve_axis(p, ((r, -0.05), (r, 0.015), (r * 0.82, 0.032), (0, 0.032)), c, n, 16, SKIN, FITTING)
    sf.revolve_axis(p, ((r * 0.68, 0.02), (r * 0.67, 0.045), (r * 0.64, 0.07),
                       (r * 0.5, 0.092), (r * 0.38, 0.105), (0, 0.115)), c, n, 16, colour_slot)


def window_frame(surf, p, corners, slot):
    """One mitred perimeter around both panes; the shared post is a separate strip."""
    path = [surf.point(a[0] + (b[0] - a[0]) * t / 6, a[1] + (b[1] - a[1]) * t / 6)
            for a, b in zip(corners, corners[1:] + corners[:1]) for t in range(6)]
    normals = [surf.normal(a[0] + (b[0] - a[0]) * t / 6, a[1] + (b[1] - a[1]) * t / 6)
               for a, b in zip(corners, corners[1:] + corners[:1]) for t in range(6)]
    centre = sum(path, Vector()) / len(path)
    rings = []
    for i, (q, n) in enumerate(zip(path, normals)):
        b0 = n.cross((q - path[i - 1]).normalized()).normalized()
        b1 = n.cross((path[(i + 1) % len(path)] - q).normalized()).normalized()
        b = (b0 + b1).normalized()
        mitre = 1 / max(0.5, b.dot(b0))
        if b.dot(q - centre) < 0:
            b = -b
        rings.append([q + b * 0.045 * mitre - n * 0.012, q + b * 0.045 * mitre + n * FRAME_UP,
                      q - b * 0.014 * mitre + n * FRAME_UP, q - b * 0.014 * mitre - n * 0.012])
    grid = sf._loop_grid(p.bm, rings)
    for k in range(4):
        grid.seam_column(k)
    grid.seam_ring(0)
    p.tag(grid.faces(), slot, FRAME)


def nose_details(bl, surf, p, slots):
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    fwd = Vector((0, -1, 0))
    for side in (1, -1):
        for corners in PANES:
            c = resolve(surf, corners, side)
            sf.surface_patch(p, surf, c, 8, 6, GLASS_UP, -0.02, GLASS)
        front, rear = [resolve(surf, c, side) for c in PANES]
        window_frame(surf, p, front[:3] + rear + [front[3]], SKIN)
        sf.surface_patch(p, surf, (front[2], rear[0], rear[3], front[3]), 1, 8,
                         FRAME_UP, -0.012, SKIN, cls=FRAME)
        # pitot probe: a swept strut with the tube running forward
        s, a = PITOT
        base, n = surf.point(s, side * a), surf.normal(s, side * a)
        sf.blade(p, base, n, fwd, 0.13, 0.15, 0.07, 0.06, 0.16, SKIN)
        head = base + n * 0.12 + fwd * 0.0
        sf.tube(p, [head + Vector((0, 0.03, 0)), head + fwd * 0.18, head + fwd * 0.34], 0.013, 6, MECH)
        s, a = AOA_VANE
        sf.blade(p, surf.point(s, side * a), surf.normal(s, side * a), fwd, 0.10, 0.09, 0.06, 0.04, 0.12, MECH)
        s, a = TEMP_PROBE
        base, n = surf.point(s, side * a), surf.normal(s, side * a)
        sf.blade(p, base, n, fwd, 0.09, 0.12, 0.06, 0.05, 0.18, SKIN)
        sf.tube(p, [base + n * 0.075 + Vector((0, 0.02, 0)), base + n * 0.08 + fwd * 0.1], 0.016, 6, MECH)
        s, a, h = SIDE_BLADE
        sf.blade(p, surf.point(s, side * a), surf.normal(s, side * a), fwd, h, 0.24, 0.1, 0.12, 0.10, SKIN)
    for s, a, h, c0, c1, sw, owner in BLADES:
        if owner == "nose":
            sf.blade(p, surf.point(s, a), surf.normal(s, a), fwd, h, c0, c1, sw, 0.10, SKIN)
    for s, a, owner in BEACONS:
        if owner == "nose":
            lift_light(p, surf, s, a, slots, LIGHT)
    evs_camera(surf, p, slots)


def evs_camera(surf, p, slots):
    """The EVS camera at EVS_CAMERA: a streamlined body 0.30 m long and 0.14 m across in the nose's paint, half sunk in
    the crown, its blunt front a flat face carrying a 76 mm window of glass, facing straight ahead."""
    SKIN, GLASS = slots[0], slots[2]
    s, lift = EVS_CAMERA
    centre = surf.point(s, 0.0) + surf.normal(s, 0.0) * lift
    fwd = Vector((0, -1, 0))
    fs = sf.revolve_axis(p, ((0, -0.20), (0.05, -0.12), (0.07, -0.02), (0.068, 0.07), (0.05, 0.10), (0.038, 0.10), (0, 0.1004)),
                         centre, fwd, 10, SKIN, FITTING)
    p.tag([f for f in fs if (f.calc_center_median() - centre).dot(fwd) > 0.0999 and all(
        (v.co - centre - fwd * (v.co - centre).dot(fwd)).length < 0.039 for v in f.verts)], GLASS)


def well_ceiling(s):
    """The nose gear well's roof height at station s: WELL_CEILING, raised by the dome over the retracted wheels."""
    a, b, c, d, rise = WELL_DOME
    up = min(max((s - a) / (b - a), 0.0), 1.0)
    down = min(max((d - s) / (d - c), 0.0), 1.0)
    return WELL_CEILING + rise * (up * up * (3 - 2 * up)) * (down * down * (3 - 2 * down))


def well_details(bl, surf, p, slots):
    """The well's dark structural fittings and mechanical trims: two frames either side of the dome,
    wall-top longerons, the trunnion's bearing blocks, the drag brace's upper link from the knee to the forward roof, the retraction
    actuator from the aft roof to the knee, and hydraulic lines down the left wall. Everything stays clear of the
    retracted leg and wheels (gear.check)."""
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    for s in (4.6, 6.0):
        sf.box(p, Vector((0, bl.st(s), well_ceiling(s) - 0.09)), (X, Y, Z), (2 * WELL_X - 0.04, 0.08, 0.18), SKIN, INTERIOR)
    s0, s1 = WELL_S[0] + 0.05, WELL_S[1] - 0.05
    for side in (1, -1):
        sf.box(p, Vector((side * (WELL_X - 0.05), bl.st((s0 + s1) / 2), WELL_CEILING - 0.07)), (X, Y, Z),
               (0.08, s1 - s0, 0.1), SKIN, INTERIOR)
        sf.box(p, Vector((side * (WELL_X - 0.055), bl.st(6.0), 1.52)), (X, Y, Z), (0.09, 0.22, 0.2), SKIN, INTERIOR)
    knee = Vector((0, bl.st(DRAG_KNEE[0]), DRAG_KNEE[1]))
    top = Vector((0, bl.st(4.2), WELL_CEILING - 0.12))
    sf.tube(p, [knee, top], 0.045, 10, MECH)
    sf.box(p, top + Vector((0, 0, 0.06)), (X, Y, Z), (0.14, 0.12, 0.1), MECH)
    a, b = Vector((0.15, bl.st(6.55), WELL_CEILING - 0.12)), Vector((0.15, knee.y, knee.z))
    sf.tube(p, [a, a + (b - a) * 0.6], 0.045, 10, MECH)
    sf.tube(p, [a + (b - a) * 0.55, b], 0.026, 8, MECH)
    sf.box(p, a + Vector((0, 0, 0.06)), (X, Y, Z), (0.1, 0.12, 0.1), MECH)
    for dz in (0.0, 0.05):
        sf.tube(p, [Vector((WELL_X - 0.03, bl.st(s0), 2.2 + dz)), Vector((WELL_X - 0.03, bl.st(s1), 2.2 + dz))], 0.014, 6, MECH)


def bay_interior(bl, surf, p, g, slots):
    """The forward bay with dark structural fittings and mechanical trims: ring frames on the skin's frame lines
    (wall posts and a roof beam), wall longerons, the weapons rack beam on the roof over the hardpoint, the door
    actuators by the hinge lines and stiffeners on the end bulkheads. Nothing spans the opening: the doors close
    against each other on the keel line."""
    SKIN, STRUCT, GLASS, MECH = slots[:4]
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    s0, s1, a0, _ = BAY_DOOR

    def edge(s):  # the left hinge line's x and z
        q = surf.point(s, a0)
        return q.x, q.z
    zc = BAY_CEILING
    for s in BAY_FRAMES:
        xe, ze = edge(s)
        for side in (1, -1):
            sf.box(p, Vector((side * (xe - 0.035), bl.st(s), (ze + zc) / 2)), (X, Y, Z), (0.07, 0.08, zc - ze), SKIN, INTERIOR)
        sf.box(p, Vector((0, bl.st(s), zc - 0.07)), (X, Y, Z), (2 * xe - 0.02, 0.08, 0.14), SKIN, INTERIOR)
    rings = [s for s in g.stations if s0 <= s <= s1]
    for side in (1, -1):
        for z in (2.55, zc - 0.05):
            sf.tube(p, [Vector((side * (edge(s)[0] - 0.03), bl.st(s), z)) for s in rings], 0.035, 6, SKIN, INTERIOR)
        for s in (9.4, 14.8):
            xe, ze = edge(s)
            a, b = Vector((side * (xe - 0.05), bl.st(s), 2.35)), Vector((side * (xe - 0.02), bl.st(s), ze + 0.05))
            sf.tube(p, [a, a + (b - a) * 0.6], 0.04, 8, MECH)
            sf.tube(p, [a + (b - a) * 0.55, b], 0.022, 8, MECH)
    sf.box(p, Vector((0, bl.st(12.0), BAY_CEILING - 0.085)), (X, Y, Z), (0.2, 4.8, 0.17), MECH)
    for s in (10.0, 11.3, 12.7, 14.0):  # ejector blocks a value step off the darker beam, so each reads on its own
        sf.box(p, Vector((0, bl.st(s), BAY_CEILING - 0.085)), (X, Y, Z), (0.36, 0.1, 0.16), SKIN, INTERIOR)
    for s, d in ((s0, 1), (s1, -1)):
        for x in (0.0, 0.75, -0.75):
            zb = bl.fus_bottom_z(s, abs(x)) + 0.02
            sf.box(p, Vector((x, bl.st(s) + d * 0.03, (zb + zc) / 2)), (X, Y, Z), (0.07, 0.06, zc - zb), SKIN, INTERIOR)


def check(bl, objs):
    """Every stock bay mount (m4/nose_bay.py) on the forward bay's hardpoint with the doors closed: no store touches a
    mesh or sits inside the hull, and the bay's structure stands BAY_ROOM or more above and below the stores."""
    fit, parts = nose_bay.fit(bl, nose_bay.hardpoint("F"), ("fuselage_F", "baydoor_FL_visible", "baydoor_FR_visible"))
    failing = sorted(m for m, f in fit.items() if f["touches"] or f["in_solid"] or min(f["up"], f["down"]) < BAY_ROOM)
    return {"bay_fit": {"value": {"mounts": fit, "parts": parts, "failing": failing},
                        "limit": f"no store touching a mesh or inside the hull; {BAY_ROOM} m or more above and below",
                        "pass": not failing}}


def receptacle(bl, surf, p, slots):
    """The refuelling receptacle at the forward end of its slipway, with the slipway floodlight behind."""
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    s = RECEPTACLE_S[0] + 0.16
    n = surf.normal(s, 0.0)
    floor = surf.point(s, 0.0) - n * (RECEPTACLE_DEPTH[0] - 0.03)
    axis = (n * 0.8 + Vector((0, 1, 0)) * 0.6).normalized()  # facing up and aft, toward a tanker's boom
    sf.revolve_axis(p, ((0.075, -0.05), (0.075, 0.06), (0.11, 0.1), (0.1, 0.12), (0, 0.06)), floor, axis, 12, MECH)
    lift_light(p, surf, RECEPTACLE_S[1] + 0.25, 0.0, slots, WHITE, r=0.06)


def fwd_fuselage_details(bl, surf, p, slots):
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    fwd = Vector((0, -1, 0))
    for s, a, h, c0, c1, sw, owner in BLADES:
        if owner == "fuselage_F":
            sf.blade(p, surf.point(s, a), surf.normal(s, a), fwd, h, c0, c1, sw, 0.10, SKIN)
    for s, a, owner in BEACONS:
        if owner == "fuselage_F":
            lift_light(p, surf, s, a, slots, LIGHT)
    # SATCOM radome: a low dome stretched along the fuselage
    s, a = SATCOM
    c, n = surf.point(s, a), surf.normal(s, a)
    faces = sf.revolve_axis(p, ((0.5, -0.07), (0.5, 0.0), (0.42, 0.09), (0.26, 0.16), (0, 0.19)), c, n, 20, SKIN, FITTING)
    verts = list({v for f in faces for v in f.verts})
    m = Matrix.Translation(c) @ Matrix.Diagonal((1.0, 1.7, 1.0, 1.0)) @ Matrix.Translation(-c)
    for v in verts:
        v.co = m @ v.co
    length, width = FORMATION_SIZE
    a0 = 93.0
    a1 = a0 - math.degrees(length / bl.fus_profile(8.86)[0])
    corners = ((8.96 - width / 2, a0), (8.96 + width / 2, a0),
               (8.76 + width / 2, a1), (8.76 - width / 2, a1))
    for side in (1, -1):
        sf.surface_patch(p, surf, side_corners(corners, side), 1, 6, 0.008, -0.012, FORMATION)
    s, a = GPS_DOME
    sf.revolve_axis(p, ((0.16, -0.05), (0.16, 0.01), (0.145, 0.026), (0.12, 0.04), (0, 0.05)),
                    surf.point(s, a), surf.normal(s, a), 16, SKIN, FITTING)


def gear_door(bl, surf, p, side, slots):
    """A nose gear door built closed (its outer face flush with the belly, x from the hinge to the keel) with ribs
    and a beam on its inner face, as the bay doors', and swung 90 degrees down about its hinge, the blockout's rest
    pose (gear down)."""
    SKIN, STRUCT = slots[0], slots[1]
    s0, s1 = WELL_S[0] + 0.03, WELL_S[1] - 0.03

    def grid(stations, xs):
        pts, nrm = [], []
        for s in stations:
            a = [surf.deg_for_x(s, side * x) for x in xs]
            pts.append([surf.point(s, d) for d in a])
            nrm.append([surf.normal(s, d) for d in a])
        return pts, nrm

    xs = [WELL_X - 0.003 - (WELL_X - 0.015) * j / 5 for j in range(6)]
    top, bottom, sides = sf.slab(p, *grid([s0 + (s1 - s0) * i / 6 for i in range(7)], xs), 0.0, -GEAR_DOOR_T,
                                 SKIN, cls=GEAR_DOOR_SKIN)
    p.tag(bottom, STRUCT)
    faces = top + bottom + sides
    inner = -GEAR_DOOR_T + 0.008  # the stiffeners start inside the skin, so they never show a seam
    r0, r1 = xs[0] - 0.03, xs[-1] + 0.03
    for s in GEAR_DOOR_RIBS:
        faces += sum(sf.slab(p, *grid((s - 0.025, s + 0.025), [r0 + (r1 - r0) * j / 5 for j in range(6)]),
                             inner, -GEAR_DOOR_T - GEAR_DOOR_RIB_H, STRUCT), [])
    b0, b1 = GEAR_DOOR_BEAM_S
    xb = GEAR_DOOR_BEAM_X
    faces += sum(sf.slab(p, *grid([b0 + (b1 - b0) * i / 6 for i in range(7)], (xb + 0.025, xb - 0.025)),
                         inner, -GEAR_DOOR_T - GEAR_DOOR_RIB_H, STRUCT), [])
    hinge = Vector((side * WELL_X, bl.st(s0), bl.fus_bottom_z(s0, WELL_X)))
    end = Vector((side * WELL_X, bl.st(s1), bl.fus_bottom_z(s1, WELL_X)))
    sf.rotate_about(p, faces, hinge, (end - hinge).normalized(), -side * math.pi / 2)


def gear_door_floor(s, x):
    """Height of the closed nose gear doors' inner structure over the belly at station s, |x| (metres): the door's
    thickness, plus its ribs' and beam's depth over their footprints widened by 4 cm, which the retracted nose gear
    must clear (gear.check)."""
    pad = 0.025 + 0.04
    over = (any(abs(s - r) < pad for r in GEAR_DOOR_RIBS)
            or (abs(x - GEAR_DOOR_BEAM_X) < pad and GEAR_DOOR_BEAM_S[0] - 0.04 < s < GEAR_DOOR_BEAM_S[1] + 0.04))
    return GEAR_DOOR_T + (GEAR_DOOR_RIB_H if over else 0.0)


# ---------- paint layout ----------
# Panel and marking data in (station, angle) like the geometry above; angles become girth with coords.arc_at.
STATION_LINES = ((5.6, 118.0, 180.0),)  # nose frame, station and angles
# One continuous skin over the part joints at 7 and 17 (as in fuselage_aft.py's layout): per band a fastened splice
# (SPLICES) and laps (LAPS) at frames, no station shared by neighbouring bands, so no joint runs right round but the
# radome's edge.
BANDS = ((0.0, 48.0), (48.0, 112.5), (112.5, 180.0))
SPLICES = ((9.8, 13.4), (11.6,), (13.0,))
LAPS = ((7.2, 8.6, 11.0, 14.6), (7.6, 9.0, 12.2, 15.8), (8.6, 11.0, 14.6, 16.4))
assert not any(set(LAPS[i] + SPLICES[i]) & set(LAPS[i + 1] + SPLICES[i + 1]) for i in range(len(BANDS) - 1)),     "neighbouring bands share a joint station: it would run on as one line"
RADOME_JOINT = 3.625  # the dielectric radome's edge: a heavier line with fastener rows either side
LONG_LINES = ((112.5, 1.75, 7.0), (135.0, 3.625, 7.4))  # nose stringers
STRINGERS = ((48.0, 7.0, 17.0), (112.5, 7.0, 17.0))
# Crew entry door, left side, clear of the glazing surround and ahead of the forward bay. Its lower skin rows
# keep unique islands so the hatch and rescue marking can extend below the chine without appearing on the right.
CREW_DOOR = fl.CREW_DOOR  # stations, level bottom and top heights below the glazing surround
PANELS = (  # station from, to, angle from, to, corner radius, sides (+1, -1 or 0 for both)
    (13.6, 14.7, 55.0, 82.0, 0.05, 0),
    (15.0, 15.5, 100.0, 112.0, 0.03, -1),  # external power
    (7.6, 8.1, 30.0, 44.0, 0.03, 0),
    (3.78, 4.15, 96.0, 108.0, 0.03, 0),  # pitot heater access
    (10.6, 11.3, 52.0, 66.0, 0.04, 0),
    (14.2, 14.8, 120.0, 136.0, 0.04, 0),
)
LEVEL_PANELS = ((4.35, 5.40, 120.0, 152.0, 0.06),  # avionics bay doors
                (9.6, 10.5, 92.0, 118.0, 0.05), (11.9, 12.5, 96.0, 110.0, 0.04))
DOOR_HANDLE = (6.78, 2.85)  # station, height on the free edge of the crew door
RESCUE_ARROW = (6.78, 2.45)
STATIC_PORTS = ((9.15, 101.0), (9.4, 101.0))
NACA_INLET = (9.0, 9.7, 128.0)
LOUVRES = (5.42, 5.80, 128.0, 6)  # ahead of the crew door
# Flare dispensers, one plate a side below the cheeks (CenturionAuthor.FlarePlates; the other pair is fuselage_aft.py's
# FLARES): station from, to, angle from, to. On fuselage_F's core, under the upper half's seam at 112.5 deg, between
# the NACA inlet (to 9.7) and the lap at 11.0, the avionics door above (to 118 deg) and the bay door's hinge (141) below.
FLARES = ((9.95, 10.85, 121.0, 135.0),)
WALKWAY = (9.7, 12.6, 0.55)  # stations, girth from the centreline
NO_STEP = (9.2, 0.85)  # station, girth from the centreline
MODEL_STENCIL = (5.3, 88.0)
EXT_PWR_STENCIL = (15.25, -94.0)
DIVERTERS = 8

DARK = (0.10, 0.105, 0.11)
STENCIL = (0.80, 0.80, 0.78)
WALK = (0.58, 0.59, 0.59)
RESCUE = (0.78, 0.62, 0.16)
RED = (0.55, 0.10, 0.08)


def paint(cv, text_mask):
    """The group's paint over a Canvas (m4/paint.py)."""
    np = cv.xp
    from .paint import PAINT, SMOOTH, panel_joint_mask, poly_sdf, rrect_sdf, seg_dist, smoothstep
    c = cv.coords
    cv.paint(cv.on(DOOR_SKIN, GEAR_DOOR_SKIN).astype(float), rgb=PAINT[DOOR], smooth=SMOOTH[DOOR])
    s, arc, deg = cv.s, cv.arc, cv.deg
    H, R = cv.on(HULL).astype(float), cv.on(RADOME).astype(float)
    HR = np.clip(H + R, 0, 1)
    ua, ad = np.abs(arc), np.abs(deg)
    joints = panel_joint_mask(cv, PANELS)
    level_panels = []
    for s0, s1, a0, a1, r in LEVEL_PANELS:
        sm = (s0 + s1) / 2
        z0, z1 = sorted((cv.surf.point(sm, a0).z, cv.surf.point(sm, a1).z))
        sdf = rrect_sdf(s, cv.pos[:, 2], s0, s1, z0, z1, r)
        level_panels.append(sdf)
        joints *= 1 - cv.fill_coverage(sdf - 0.05)
    crew_sdf = rrect_sdf(s, cv.pos[:, 2], *CREW_DOOR, fl.DOOR_CORNER)
    joints *= 1 - cv.fill_coverage(crew_sdf - 0.05) * (cv.pos[:, 0] > 0)
    hatch_sdf = rrect_sdf(s, np.abs(cv.pos[:, 0]), *fl.HATCH_S, *fl.HATCH_X, fl.HATCH_CORNER)
    joints *= 1 - cv.fill_coverage(hatch_sdf - 0.05)

    # radome: lightning diverter strips on eight meridians, metal on the dielectric
    for k in range(DIVERTERS):
        d0 = -180.0 + 22.5 + 45.0 * k
        d = np.abs(arc - c.arc_at(s, d0))
        run = smoothstep(0.43, 0.65, s) * smoothstep(3.51, 3.33, s) * R
        cv.paint(cv.coverage(d, 0.025) * run, rgb=DARK, smooth=0.35)
        pitch = np.abs((s - 0.65 + 0.0125) % 0.025 - 0.0125)
        cv.paint(cv.fill_coverage(np.hypot(d, pitch) - 0.005) * run,
                 rgb=(0.47, 0.47, 0.47), smooth=0.55, metal=0.25, height=0.0015)
    cv.paint(smoothstep(0.42, 0.36, s) * R, smooth=0.6)
    cv.groove(ua, 0.012, mask=R * (s > 3.25) * (s < 3.58))
    for side in (1, -1):
        latch_arc = side * float(c.arc_at(3.54, 130.0))
        latch = rrect_sdf(s, arc, 3.46, 3.61, latch_arc - 0.055, latch_arc + 0.055, 0.012)
        cv.paint(cv.fill_coverage(latch) * R, rgb=(0.37, 0.38, 0.39), smooth=0.55, metal=0.15, height=0.001)
        cv.groove(np.abs(latch), 0.01, mask=R)

    # skin panels differ a little in tone, Darkreach-like: a panel is a cell between the lines
    band = np.digitize(ad, [b for _, b in BANDS[:-1]])
    cell = np.zeros(cv.n, int)
    for i, (laps, splices) in enumerate(zip(LAPS, SPLICES)):
        cell = np.where(band == i, np.searchsorted(np.array(sorted(set(laps) | set(splices) | {RADOME_JOINT})), s), cell)
    for a, s0, s1 in STRINGERS + LONG_LINES:
        cell = cell * 2 + ((ad > a) & (s > s0) & (s < s1))
    cell = (cell * 4 + band) * 2 + (arc > 0)
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    cv.albedo *= (1 + 0.05 * tone * HR)[:, None]

    # window mask and anti-glare panel
    for side in (1, -1):
        sdfs = []
        for corners in PANES:
            q = [(si, float(c.arc_at(si, a))) for si, a in resolve(cv.surf, corners, side)]
            sdfs.append(poly_sdf(s, arc, q))
        tip = [(3.70, 0.0), (4.07, 0.0), (4.07, side * 0.84), (3.83, side * 0.43)]
        sdfs.append(poly_sdf(s, arc, tip))
        m = np.min(sdfs, axis=0)
        cv.paint(cv.fill_coverage(m - 0.16) * H, rgb=DARK, smooth=0.2)

    # joints and skin lines
    d = np.abs(s - RADOME_JOINT)
    cv.groove(d, 0.02, mask=HR * joints)
    cv.fasteners(d, ua, 0.035, mask=HR * joints)
    for st_, a0, a1 in STATION_LINES:
        m = H * joints * (ad >= a0) * (ad <= a1)
        cv.groove(np.abs(s - st_), mask=m)
        cv.fasteners(np.abs(s - st_), ua, 0.03, mask=m)
    for (a0, a1), laps, splices in zip(BANDS, LAPS, SPLICES):
        m = H * joints * smoothstep(a0 - 0.6, a0, ad) * smoothstep(a1 + 0.6, a1, ad)
        for j in splices:
            cv.groove(np.abs(s - j), 0.016, mask=m)
            cv.fasteners(np.abs(s - j), ua, 0.035, mask=m)
        for st_ in laps:
            cv.groove(np.abs(s - st_), mask=m)
    for a, s0, s1 in STRINGERS:
        d = np.abs(ua - np.abs(c.arc_at(s, a)))
        cv.groove(d, mask=H * joints * (s > s0) * (s < s1))
    for a, s0, s1 in LONG_LINES:
        d = np.abs(ua - np.abs(c.arc_at(s, a)))
        m = H * joints * smoothstep(s0 - 0.01, s0, s) * smoothstep(s1 + 0.01, s1, s)
        cv.groove(d, mask=m)
        cv.fasteners(d, s, 0.03, mask=m)

    # access panels
    for s0, s1, a0, a1, r, sides in PANELS:
        for side in ((1, -1) if sides == 0 else (sides,)):
            sm = (s0 + s1) / 2
            v0, v1 = sorted((float(c.arc_at(sm, side * a0)), float(c.arc_at(sm, side * a1))))
            sdf = rrect_sdf(s, arc, s0, s1, v0, v1, r)
            cv.groove(np.abs(sdf), mask=H)
            cv.fasteners(np.abs(sdf), s + arc, 0.03, mask=H * (np.abs(sdf) < 0.06))

    for sdf in level_panels:
        cv.groove(np.abs(sdf), mask=H)
        cv.fasteners(np.abs(sdf), s + cv.pos[:, 2], 0.03, mask=H * (np.abs(sdf) < 0.06))

    s0, s1, z0, z1 = CREW_DOOR
    left = H * (cv.pos[:, 0] > 0)
    z = cv.pos[:, 2]
    cv.groove(np.abs(crew_sdf), 0.01, -0.004, mask=left)
    cv.groove(np.abs(hatch_sdf), 0.01, -0.004, mask=H)
    for h in np.linspace(z0 + 0.12, z1 - 0.12, 3):
        mark = rrect_sdf(s, z, s0 - 0.025, s0 + 0.035, h - 0.055, h + 0.055, 0.012)
        cv.paint(cv.fill_coverage(mark) * left, rgb=DARK, height=0.002)

    # crew door handle and rescue marking
    hs, ha = DOOR_HANDLE[0], float(c.arc_at(DOOR_HANDLE[0], cv.surf.deg_for_z(*DOOR_HANDLE)))
    cv.paint(cv.fill_coverage(rrect_sdf(s, arc, hs - 0.06, hs + 0.06, ha - 0.1, ha + 0.1, 0.02)) * H, rgb=DARK, height=-0.008)
    rs, ra = RESCUE_ARROW[0], float(c.arc_at(RESCUE_ARROW[0], cv.surf.deg_for_z(*RESCUE_ARROW)))
    arrow = [(rs, ra - 0.17), (rs - 0.08, ra - 0.08), (rs - 0.03, ra - 0.08), (rs - 0.03, ra + 0.02), (rs + 0.03, ra + 0.02),
             (rs + 0.03, ra - 0.08), (rs + 0.08, ra - 0.08)]
    cv.paint(cv.fill_coverage(poly_sdf(s, arc, arrow)) * H, rgb=RESCUE)
    cv.decal(text_mask("RESCUE"), (rs, ra + 0.08), 48 / 0.075, (1, 0), mask=H, rgb=RESCUE)

    # static ports: a red keep-clean ring round a dark port
    for ps, pa in STATIC_PORTS:
        for side in (1, -1):
            pv = float(c.arc_at(ps, side * pa))
            r = np.hypot(s - ps, arc - pv)
            cv.paint(cv.coverage(np.abs(r - 0.055), 0.014) * H, rgb=RED)
            cv.paint(cv.fill_coverage(r - 0.018) * H, rgb=DARK, height=-0.002)

    # NACA inlet and louvres
    s0, s1, a = NACA_INLET
    from .fuselage_aft import flare_plates, naca
    naca(cv, s0, s1, float(c.arc_at((s0 + s1) / 2, a)), H)
    flare_plates(cv, FLARES, H)
    s0, s1, a, n = LOUVRES
    z = cv.surf.point((s0 + s1) / 2, a).z  # the slots stand at one height, beside the level avionics door
    for side in (1, -1):
        for i in range(n):
            si = s0 + (s1 - s0) * i / (n - 1)
            v = side * float(c.arc_at(si, cv.surf.deg_for_z(si, z)))
            d, _ = seg_dist(s, arc, (si, v - 0.11), (si, v + 0.11))
            cv.groove(d, 0.024, -0.006, 0.55, mask=H)

    # walkway lines on the crown, and the refuelling receptacle's slipway outline and guide stripe
    s0, s1, g = WALKWAY
    dash = ((s - s0) % 0.32) < 0.2
    cv.paint(cv.coverage(np.abs(ua - g), 0.025) * H * dash * (s > s0) * (s < s1), rgb=WALK)
    # receptacle: a dark slipway surround and white lead-in lines opening aft, toward the tanker's boom
    v = float(c.arc_at(RECEPTACLE_S[0], sf.ring_deg(1))) + 0.1
    sdf = rrect_sdf(s, arc, RECEPTACLE_S[0] - 0.1, RECEPTACLE_S[1] + 0.1, -v, v, 0.08)
    cv.paint(cv.fill_coverage(sdf) * H, rgb=DARK, smooth=0.2)
    for side in (1, -1):
        d, _ = seg_dist(s, arc, (RECEPTACLE_S[1] + 0.15, side * (v - 0.04)), (RECEPTACLE_S[1] + 1.05, side * (v + 0.42)))
        cv.paint(cv.coverage(d, 0.04) * H, rgb=STENCIL)
    cv.paint(cv.coverage(ua, 0.04) * H * (s > RECEPTACLE_S[1] + 0.45) * (s < RECEPTACLE_S[1] + 1.05), rgb=STENCIL)
    for side in (1, -1):
        cv.decal(text_mask("NO STEP"), (NO_STEP[0], side * NO_STEP[1]), 48 / 0.06, (side, 0), mask=H, rgb=STENCIL)

    # stencils
    for side in (1, -1):
        cv.decal(text_mask("PITOT HOT"), (PITOT[0] + 0.05, side * float(c.arc_at(PITOT[0], 84.0))), 48 / 0.045,
                 (side, 0), mask=H, rgb=STENCIL)
        ms, ma = MODEL_STENCIL
        z = cv.surf.point(ms, ma).z
        a0 = float(c.arc_at(ms - 0.3, cv.surf.deg_for_z(ms - 0.3, z)))
        a1 = float(c.arc_at(ms + 0.3, cv.surf.deg_for_z(ms + 0.3, z)))
        u = np.array([0.6, a1 - a0])
        u /= np.linalg.norm(u)
        cv.decal(text_mask("MRB-100"), (ms, side * float(c.arc_at(ms, ma))), 48 / 0.2,
                 (side * u[0], u[1]), mask=H, rgb=STENCIL, axis_v=(0.0, -side))
    es, ea = EXT_PWR_STENCIL
    cv.decal(text_mask("EXT PWR"), (es, float(c.arc_at(es, ea))), 48 / 0.045, (-1, 0), mask=H, rgb=STENCIL)
    paint_bay_doors(cv)
    paint_gear_doors(cv, text_mask)
    paint_well_roof(cv)


def paint_well_roof(cv):
    np = cv.xp
    from .paint import rrect_sdf, seg_dist
    s, x = cv.s, cv.pos[:, 0]
    roof = cv.on(INTERIOR) * (cv.nrm[:, 2] < -0.8) * (cv.pos[:, 2] > WELL_CEILING - 0.02)
    roof *= (s > WELL_S[0] + 0.1) * (s < WELL_S[1] - 0.1) * (np.abs(x) < WELL_X - 0.1)
    for side in (1, -1):
        sdf = rrect_sdf(s, x, 4.75, 5.5, side * 0.38 - 0.16, side * 0.38 + 0.16, 0.035)
        cv.paint(cv.fill_coverage(sdf) * roof, rgb=(0.23, 0.24, 0.25), smooth=0.4, height=0.002)
        cv.groove(np.abs(sdf), 0.018, mask=roof)
        cv.fasteners(np.abs(sdf), s + x, 0.035, 0.16, 0.012, mask=roof * (np.abs(sdf) < 0.06))
        d, _ = seg_dist(s, x, (4.2, side * 0.57), (6.6, side * 0.57))
        cv.paint(cv.coverage(d, 0.035) * roof, rgb=(0.37, 0.38, 0.39), metal=0.4, height=0.008)


def paint_bay_doors(cv):
    np = cv.xp
    s, ua, c = cv.s, np.abs(cv.arc), cv.coords
    D = cv.on(DOOR_SKIN).astype(float)
    s0, s1, a0, a1 = BAY_DOOR
    g0, g1 = np.abs(c.arc_at(s, a0)), np.abs(c.arc_at(s, a1))
    edge_s, edge_g = np.minimum(s - s0, s1 - s), np.minimum(ua - g0, g1 - ua)
    inset = np.minimum(edge_s, edge_g)
    along = np.where(edge_s < edge_g, ua, s)
    cv.paint(cv.coverage(np.abs(inset - 0.006), 0.012) * D, rgb=DARK, smooth=0.3)
    cv.groove(np.abs(inset - 0.12), 0.012, mask=D)
    cv.fasteners(np.abs(inset - 0.085), along, 0.0, 0.08, mask=D)
    cv.fasteners(np.abs(ua - g0 - 0.05), s, 0.0, 0.06, 0.009, mask=D * (edge_s > 0.05))
    cv.groove(np.abs(ua - g0 - 0.17), 0.012, mask=D * (edge_s > 0.12))
    for st_ in BAY_FRAMES[::2]:
        cv.groove(np.abs(s - st_), 0.012, mask=D * (inset > 0.12))
        cv.fasteners(np.abs(s - st_), ua, 0.0, 0.08, mask=D * (inset > 0.12))


def paint_gear_doors(cv, text_mask):
    """Paint in the closed door's coordinates, then keep those texels through the hinge rotation."""
    np = cv.xp
    from .paint import Canvas
    bl = cv.coords.bl
    s0, s1 = WELL_S[0] + 0.03, WELL_S[1] - 0.03
    for side in (1, -1):
        mask = cv.on(GEAR_DOOR_SKIN) & (cv.pos[:, 0] * side > 0)
        if not mask.any():
            continue
        hinge = Vector((side * WELL_X, bl.st(s0), bl.fus_bottom_z(s0, WELL_X)))
        end = Vector((side * WELL_X, bl.st(s1), bl.fus_bottom_z(s1, WELL_X)))
        rotation = np.array(Matrix.Rotation(side * math.pi / 2, 3, (end - hinge).normalized()))
        pos = (cv.pos[mask] - np.array(hinge)) @ rotation.T + np.array(hinge)
        door = Canvas({"pos": pos, "nrm": cv.nrm[mask], "cls": np.full(int(mask.sum()), DOOR)}, cv.coords, cv.px)
        s, x = door.s, np.abs(pos[:, 0])
        edge_s = np.minimum(s - s0, s1 - s)
        edge_x = np.minimum(WELL_X - 0.003 - x, x - 0.012)
        rim = np.minimum(edge_s, edge_x)
        door.fasteners(np.abs(rim - 0.06), np.where(edge_s < edge_x, x, s), 0.0, 0.08)
        door.groove(np.abs(x - (WELL_X - 0.045)), 0.012, mask=(edge_s > 0.06))
        door.arc = side * (WELL_X - x)
        door.decal(text_mask("KEEP CLEAR"), (5.4, side * (WELL_X - 0.36)), 48 / 0.12, (side, 0), rgb=STENCIL)
        cv.albedo[mask] = door.albedo
        cv.smooth[mask] = door.smooth
        cv.height[mask] += door.height
