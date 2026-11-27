"""The cockpit's knobs, pulls and lever grips as our own geometry on the trim sheet, in place of the shapes lifted from
the VT-7's Switches1 kit: COCKPIT-DESIGN.md allows stock meshes by placeholder only, and those shapes are pieces of a
stock cockpit mesh, so they could not ship. Each is a lathe (a profile turned about z) or a lathe and a bar, its base
at z 0, sized as the kit shape it replaces at scale 1, every face on one solid cell of the sheet; shaded round with
edges over 50 deg kept sharp. mesh(role, t) builds a role's mesh once."""
import math

import bmesh
import bpy

MM = 0.001
_cache = {}


def _lathe(bm, uvl, profile, sides, uv, cap=True, rot=0.0):
    """Rings at each (r, z) of `profile` (bottom to top), joined by quads, the last ring capped if `cap`."""
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new((r * math.cos(rot + 2 * math.pi * k / sides), r * math.sin(rot + 2 * math.pi * k / sides), z))
                      for k in range(sides)])
    for a, b in zip(rings, rings[1:]):
        for k in range(sides):
            j = (k + 1) % sides
            f = bm.faces.new((a[k], a[j], b[j], b[k]))
            for lp in f.loops:
                lp[uvl].uv = uv
    if cap:
        f = bm.faces.new(rings[-1])
        for lp in f.loops:
            lp[uvl].uv = uv
    return rings


def _prism(bm, uvl, prof_yz, half_x, uv, skip_bottom=True):
    """A bar: the profile (y, z) anticlockwise seen from +x, extruded from -half_x to +half_x; its bottom edge left
    open when it stands on the knob."""
    left = [bm.verts.new((-half_x, y, z)) for y, z in prof_yz]
    right = [bm.verts.new((half_x, y, z)) for y, z in prof_yz]
    faces = [bm.faces.new(list(reversed(left))), bm.faces.new(right)]
    n = len(prof_yz)
    for k in range(n):
        j = (k + 1) % n
        if skip_bottom and k == n - 1:
            continue
        faces.append(bm.faces.new((left[k], left[j], right[j], right[k])))
    for f in faces:
        for lp in f.loops:
            lp[uvl].uv = uv


def mesh(role, t):
    """The role's mesh (base at z 0, metres), UVs on the trim sheet's cells."""
    if role in _cache:
        return _cache[role]
    hw = t.hw

    def cell(name):
        x0, y0, x1, y1 = hw[name]
        return t.uv((x0 + x1) / 2, (y0 + y1) / 2)
    black, red = cell("keyframe"), cell("guard_red")
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    if role == "knl":  # a 14.4 mm knob 6 mm tall, its top edge chamfered (58 triangles)
        _lathe(bm, uvl, [(7.2 * MM, 0), (7.2 * MM, 5.2 * MM), (6.0 * MM, 6.0 * MM)], 12, black)
    elif role == "big":  # a 25 mm knob on a skirt (110 triangles)
        _lathe(bm, uvl, [(12.5 * MM, 0), (12.5 * MM, 1.5 * MM), (11.2 * MM, 2.2 * MM), (11.2 * MM, 9.6 * MM), (10.0 * MM, 11 * MM)], 16, black)
    elif role == "ptr":  # a 25 mm disc and a moulded pointer bar along +y, its end ramping down (92 triangles)
        _lathe(bm, uvl, [(12.5 * MM, 0), (12.5 * MM, 3.0 * MM), (11.5 * MM, 3.5 * MM)], 16, black)
        # its crown highest toward the tip, so the index finds the pointer's direction (knob_profile: the farthest high vertex)
        _prism(bm, uvl, [(-5 * MM, 3.5 * MM), (12 * MM, 3.5 * MM), (12 * MM, 6 * MM), (6 * MM, 11 * MM), (-5 * MM, 9.5 * MM)], 3.5 * MM, black)
    elif role == "stk":  # a stacked pair: a 20 mm outer knob with a top land, a 13 mm inner one (108 triangles)
        _lathe(bm, uvl, [(10 * MM, 0), (10 * MM, 5 * MM), (6.5 * MM, 5 * MM), (6.5 * MM, 11 * MM)], 16, black)
    elif role in ("pull", "pull_red"):  # a T-handle on its stem and collar (54 triangles)
        uv = red if role == "pull_red" else black
        _lathe(bm, uvl, [(6 * MM, 0), (6 * MM, 2 * MM), (2.2 * MM, 2 * MM), (2.2 * MM, 18 * MM)], 8, uv, cap=False)
        _prism(bm, uvl, [(-12 * MM, 18 * MM), (12 * MM, 18 * MM), (12 * MM, 23 * MM), (-12 * MM, 23 * MM)], 3 * MM, uv, skip_bottom=False)
    elif role == "grip":  # a lever's grip: a rounded 10 mm knob 19 mm tall (56 triangles)
        _lathe(bm, uvl, [(3 * MM, 0), (5 * MM, 4 * MM), (5 * MM, 14 * MM), (3.5 * MM, 18 * MM), (1.2 * MM, 19 * MM)], 8, black)
    else:
        raise KeyError(role)
    me = bpy.data.meshes.new("own_" + role)
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(50))
    _cache[role] = me
    return me
