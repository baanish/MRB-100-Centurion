"""The flight deck's fixed measurements (docs/COCKPIT-DESIGN.md), shared by the blockout (build_centurion.py: the escape
hatches, the crew door and the nose collider's notch), the M4 nose (m4/nose_exits.py: their openings and panels) and
the interior (cockpit/flightdeck.py). Stations are metres from the radome tip, x is metres outboard of the centreline
(positive to the left, Blender +X), z is height above the ground."""

import math

# The pilot's eye (left seat; the mission commander's mirrors to -x) and the flight deck floor under it.
EYE_S, EYE_X, EYE_Z = 6.55, 0.55, 5.00
FLOOR_Z = 3.75

# Escape hatch opening, one over each seat: stations, x outboard of the centreline, corner radius (owner: rounded
# corners, 15 cm of skin to the windscreen everywhere). It covers the ejection seat swept along its rail, the pilot's
# capsule and the dismounted pilot's helmeted head (docs/COCKPIT-DESIGN.md "Escape").
HATCH_S, HATCH_X, HATCH_CORNER = (5.58, 6.85), (0.20, 0.90), 0.15
HATCH_GAP = 0.004  # the panel stands this far in from the opening all round: the seam that reads as a hatch
HATCH_DEPTH = 0.08  # the opening's walls run this deep under the skin, to the panel's inner face (the lining's depth)

# Crew door, left side (owner: a tall walk-in door, about 1.0 m by 1.8 to 1.9 m, corners rounded as the hatches'):
# stations, the level sill and head heights, corner radius. As large as the nose's side allows: its head 16 cm or more
# under the side pane's frame, its sill 0.6 m over the belly and 0.7 m outboard of the nose gear well, ahead of the
# part's joint at 7.0. It hinges on its forward edge (build_centurion.build_flightdeck_exits).
CREW_DOOR, DOOR_CORNER = (5.92, 6.92, 1.85, 3.72), 0.15
DOOR_GAP, DOOR_THICK = 0.004, 0.05  # seam, panel thickness
# The vestibule the door opens into, under the flight deck floor (FLOOR_Z): a room straight in from the door to
# VESTIBULE_X outboard of the centreline, two steps up its inboard wall to a passage over the gear well's roof (2.6),
# which runs in under the floor hatch between the seats, and a ladder on the passage's aft wall up through that hatch.
VESTIBULE_X = 0.85
PASSAGE_S, PASSAGE_Z, PASSAGE_X = (6.45, 6.88), (2.65, 3.55), -0.25  # stations, floor and roof, inboard end
STEPS = ((2.12, 0.40), (2.39, 0.20))  # each step's top and its depth out from the inboard wall
FLOOR_HATCH = (6.55, 6.88, 0.21)  # in the flight deck floor over the passage: stations, half width

# The nose's collider opens over each hatch above NOTCH_Z, between NOTCH_S, from NOTCH_X[0] to NOTCH_X[1] outboard:
# the seats and capsules turn collidable at the rail's last step with their bottoms over it.
NOTCH_Z, NOTCH_S, NOTCH_X = 5.10, (5.50, 6.95), (0.15, 0.95)


def rounded_rect(u0, u1, v0, v1, r, edge_step, arc_segments):
    """A rounded rectangle's outline in (u, v), counter-clockwise from the (u0, v0) side's corner: each corner an arc
    of arc_segments pieces, each straight edge cut into pieces of about edge_step."""
    corners = ((u1 - r, v0 + r, -90.0), (u1 - r, v1 - r, 0.0), (u0 + r, v1 - r, 90.0), (u0 + r, v0 + r, 180.0))
    pts = []
    for k, (cu, cv, a0) in enumerate(corners):
        for i in range(arc_segments):
            a = math.radians(a0 + 90.0 * i / arc_segments)
            pts.append((cu + r * math.cos(a), cv + r * math.sin(a)))
        # the straight edge from this arc's end to the next arc's start, both at a0 + 90 round their own centres
        a = math.radians(a0 + 90.0)
        nu, nv, _ = corners[(k + 1) % 4]
        end, nxt = (cu + r * math.cos(a), cv + r * math.sin(a)), (nu + r * math.cos(a), nv + r * math.sin(a))
        n = max(1, math.ceil(math.hypot(nxt[0] - end[0], nxt[1] - end[1]) / edge_step))
        pts += [(end[0] + (nxt[0] - end[0]) * t / n, end[1] + (nxt[1] - end[1]) * t / n) for t in range(n)]
    return pts


def hatch_outline(inset=0.0, edge_step=0.30, arc_segments=3):
    """The left hatch's outline in plan as (station, x outboard) points, shrunk by inset all round."""
    (s0, s1), (x0, x1) = HATCH_S, HATCH_X
    return rounded_rect(s0 + inset, s1 - inset, x0 + inset, x1 - inset, HATCH_CORNER - inset, edge_step, arc_segments)


def door_outline(inset=0.0, edge_step=0.30, arc_segments=3):
    """The crew door's outline on the left side as (station, z) points, shrunk by inset all round."""
    s0, s1, z0, z1 = CREW_DOOR
    return rounded_rect(s0 + inset, s1 - inset, z0 + inset, z1 - inset, DOOR_CORNER - inset, edge_step, arc_segments)
