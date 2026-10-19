"""fuselage_aft's laser C-RAM: laser_turret is the tail cone's back end in the lens material, and laser_barrel the
emitter's transform inside it. A helper of fuselage_aft.py; it declares no GROUP, so detail_centurion's group discovery
passes over it.

The owner wants the whole back end in the lens material, not a dome on it (docs/DECISIONS.md, 2026-10-13), on the
boat-tail's small tip (build_centurion S61_BOAT_TAIL). The skin ends at the cone's last hull ring; from that ring the
lens carries the cone's own tapering section on and rounds it over LENS_LENGTH onto a pole, so the lens and the skin
share the ring and its tangent. The stock Medusa lens showed the structure behind it in game (owner: "too
transparent, make it opaque"), so laser_lens takes the mod's own opaque amber metal (CenturionAuthor.Cram.cs
AuthorLens) and nothing inside it shows: the emitter is a token head that keeps laser_barrel a mesh.

The stock turret aims by turning laser_turret about the vertical through its pivot and laser_barrel about the
turret's cross axis (Turret.cs:715-716), so the lens, which follows the cone, cannot turn with the turret unseen. The
C-RAM mount carries it on its fixed yaw frame instead (CenturionAuthor.Cram.cs) and only the emitter turns, inside the
lens at any aim. The pivots, colliders and LOD1 hulls stay the blockout's, so the laser's fire point and the
authoring's 80 deg cone check do not move."""

import math

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import render
from . import surface as sf

LENS = "laser_lens"  # the lens's slot, which CenturionAuthor binds to its opaque Centurion_lens
# The lens scales the cone's section about its centre by round_off over LENS_LENGTH past the last hull ring: it follows
# the boat-tail's taper, then rounds it onto a pole, tangent to the skin at the ring. Its rings sit
# LENS_LENGTH * sin(phi) past the ring at these phi (degrees), closer toward the pole.
LENS_LENGTH, LENS_ROUND = 1.3, 3.0
LENS_PHI = (0.0, 4.0, 10.0, 18.0, 28.0, 39.0, 51.0, 63.0, 67.0, 71.0, 75.0, 79.0, 82.0, 85.0, 86.5, 88.0, 89.5)
# The emitter's token head on the pivot, (radius, height along the aft axis), and how far inside the lens its reach
# stays at any aim
EMITTER = ((0.0, -0.05), (0.05, -0.02), (0.05, 0.02), (0.0, 0.05))
EMITTER_CLEAR = 0.05
# The review renders' stand-in for Centurion_lens: sRGB colour, metallic and smoothness (CenturionAuthor's LensTint)
LENS_LOOK = {"rgb": (239, 152, 104), "metal": 1.0, "smooth": 0.95}


def section(bl, surf, s, scale):
    """The cone's ring at station s (the fuselage surface at N angles) scaled by scale about its section's centre."""
    _, top, bot = bl.fus_profile(s)
    c = Vector((0, bl.st(s), (top + bot) / 2))
    return [c + (surf.point(s, sf.ring_deg(k)) - c) * scale for k in range(sf.N)]


def round_off(d, length):
    """The lens's scale on the cone's section d past the last hull ring: 1 with no slope at the ring, 0 at length."""
    return max(0.0, 1 - (d / length) ** LENS_ROUND) ** (1 / LENS_ROUND)


def lens(bl, surf, p, s0, struct):
    """laser_turret: the lens from the last hull ring s0 to its pole, closed by a flat base across the ring (a joint
    face inside the cone)."""
    ds = [LENS_LENGTH * math.sin(math.radians(a)) for a in LENS_PHI]
    g = sf.Grid(p.bm, [section(bl, surf, s0 + d, round_off(d, LENS_LENGTH)) for d in ds])
    _, top, bot = bl.fus_profile(s0 + LENS_LENGTH)
    pole = p.bm.verts.new(Vector((0, bl.st(s0 + LENS_LENGTH), (top + bot) / 2)))
    fan = [p.bm.faces.new((g.V[-1][k], g.V[-1][(k + 1) % sf.N], pole)) for k in range(sf.N)]
    g.seam_column(0)
    p.tag(g.faces() + fan, LENS)
    p.tag(sf.cap(p.bm, g.V[0][::-1]), struct)


def emitter(p, centre, mech):
    """laser_barrel: the emitter's token head on the pivot, hidden in the lens."""
    sf.revolve_axis(p, EMITTER, centre, Vector((0, 1, 0)), 8, mech, ref=Vector((0, 0, 1)))


def lens_look(mat):
    """mat (the lens slot's material) as the review renders' stand-in for Centurion_lens: opaque amber metal."""
    rgb = tuple(render.srgb_to_linear(np.array(LENS_LOOK["rgb"]) / 255.0))
    render.principled(mat, rgb, 1.0 - LENS_LOOK["smooth"], LENS_LOOK["metal"])


def checks(bl, lens_obj, emitter_obj, cone):
    """The emitter inside the lens at any aim (its farthest point from the pivot against the lens's nearest), and the
    crease where the skin turns to lens: for points on the lens outside the cone and within 4 cm of its skin
    (smoothness_report's reach), the angle to that skin, against the report's kink limit."""
    c = lens_obj.matrix_world.translation
    dv, dp = bl.world_mesh(lens_obj)
    reach = max((v - c).length for v in bl.world_mesh(emitter_obj)[0])
    near = BVHTree.FromPolygons(dv, dp).find_nearest(c)[3]
    res = {"emitter_clear": {"value": {"reach_m": round(reach, 3), "lens_m": round(near, 3)},
                             "limit": f"the emitter's reach {EMITTER_CLEAR} m inside the lens",
                             "pass": reach + EMITTER_CLEAR <= near}}
    cv, cp = bl.world_mesh(cone)
    whole = BVHTree.FromPolygons(cv, cp)
    skin_tree = BVHTree.FromPolygons(cv, [cp[i] for i in bl.slot_faces(cone, bl.SKIN)])
    lens_faces = set(bl.slot_faces(lens_obj, LENS))
    angles = []
    for f, poly in enumerate(dp):
        if f not in lens_faces:
            continue
        for i in range(1, len(poly) - 1):
            p0, p1, p2 = dv[poly[0]], dv[poly[i]], dv[poly[i + 1]]
            na = (p1 - p0).cross(p2 - p0)
            if na.length < 1e-12:
                continue
            na.normalize()
            n = min(40, max(1, math.ceil(max((p1 - p0).length, (p2 - p0).length) / 0.01)))
            for a in range(n + 1):
                for b in range(n + 1 - a):
                    q = p0 + (p1 - p0) * (a / n) + (p2 - p0) * (b / n)
                    loc, nb, _, _ = skin_tree.find_nearest(q, 0.04)
                    if loc is None:
                        continue
                    at, nw, _, _ = whole.find_nearest(q)  # in front of the cone's nearest face: outside it, in sight
                    if (q - at).dot(nw) >= 0:
                        angles.append(math.degrees(na.angle(nb)))
    angles.sort()
    value = {"samples": len(angles)}
    if angles:
        value.update({"median_deg": round(angles[len(angles) // 2], 1),
                      "p90_deg": round(angles[int(0.9 * (len(angles) - 1))], 1), "max_deg": round(angles[-1], 1)})
    res["lens_junction"] = {"value": value, "limit": f"worst tenth under {bl.SMOOTH_KINK_DEG} deg",
                            "pass": bool(angles) and value["p90_deg"] < bl.SMOOTH_KINK_DEG}
    return res
