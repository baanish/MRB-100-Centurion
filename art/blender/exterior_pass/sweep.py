"""The control surfaces' swept envelopes, for the stages that must keep out of them (s2 keeps its members out; s1's
lip trim, switched off) and for check_travel's poses. A surface's envelope is its own meshes posed about its hinge every
STEP degrees over its travel as the game drives it (CenturionAuthor.cs Surfaces: flaps 30 trailing edge down; the
ailerons 25 either way in roll, and the clamshell split adds 50 more, the upper half up only and the lower half down
only, s1 having made them real halves; ruddervators 40 both ways)."""
import math

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

STEP = 2
FLAP, ROLL, SPLIT, RUDDERVATOR = 30, 25, 50, 40
RAYS = (Vector((0.0, 0.0, 1.0)), Vector((0.31, 0.53, -0.79)).normalized(), Vector((-0.67, 0.41, 0.62)).normalized())


def helper(o):
    return ("_colmesh" in o.name or "_lod1" in o.name or o.name.endswith(("_blockout_mesh", "_shape"))
            or any(c.name in ("Colliders", "LOD1") for c in o.users_collection))


def turn(hinge, deg):
    ax = hinge.matrix_world.col[0].xyz.normalized()
    piv = hinge.matrix_world.translation.copy()
    return Matrix.Translation(piv) @ Matrix.Rotation(math.radians(deg), 4, ax) @ Matrix.Translation(-piv)


def world(objs, m=Matrix.Identity(4)):
    vs, ps = [], []
    for o in objs:
        b = len(vs)
        mw = m @ o.matrix_world
        vs += [mw @ v.co for v in o.data.vertices]
        ps += [[b + i for i in p.vertices] for p in o.data.polygons]
    return vs, ps


def te_sign(hinge, moving):
    """+1 when a positive turn raises the trailing edge, -1 when it lowers it."""
    vs, _ = world(moving)
    ax = hinge.matrix_world.col[0].xyz.normalized()
    piv = hinge.matrix_world.translation.copy()
    fwd = ax.cross(Vector((0, 0, 1)))
    fwd = fwd if fwd.y < 0 else -fwd
    te = min(vs, key=lambda p: (p - piv).dot(fwd))
    return 1 if (turn(hinge, 10) @ te).z > te.z else -1


def surfaces():
    """[(hinge, meshes, degrees, label)] for every flap, aileron half and ruddervator in the blend."""
    out = []
    for o in sorted((o for o in bpy.data.objects if o.type != "MESH" and bpy.data.objects.get(o.name + "_visible")), key=lambda o: o.name):
        vis = bpy.data.objects[o.name + "_visible"]
        lower = bpy.data.objects.get(o.name + "_visible_lower")
        moving = [c for c in [vis, *vis.children_recursive] if c.type == "MESH" and not helper(c) and c is not lower]
        up = te_sign(o, moving)
        if o.name.startswith("flap_"):  # trailing edge down only
            out.append((o, moving, [-up * d for d in range(STEP, FLAP + 1, STEP)], o.name))
        elif o.name.startswith("aileron_"):  # roll either way; the split adds up for the upper half, down for the lower
            out.append((o, moving, [up * d for d in range(-ROLL, ROLL + SPLIT + 1, STEP) if d], o.name + " upper"))
            if lower is not None:
                out.append((o, [lower], [up * d for d in range(-ROLL - SPLIT, ROLL + 1, STEP) if d], o.name + " lower"))
        elif o.name.startswith("ruddervator_"):
            out.append((o, moving, [d for d in range(-RUDDERVATOR, RUDDERVATOR + 1, STEP) if d], o.name))
    return out


def envelope(hinge, moving, degs):
    """One BVH per pose of the surface's meshes."""
    return [BVHTree.FromPolygons(*world(moving, turn(hinge, d))) for d in degs]


def inside(p, trees, reach=8.0):
    """True when p lies inside the surface at any pose: an odd count of crossings along at least two of three rays."""
    for t in trees:
        odd = 0
        for d in RAYS:
            n, q = 0, p.copy()
            for _ in range(32):
                h = t.ray_cast(q, d, reach)
                if h[0] is None:
                    break
                n += 1
                q = h[0] + d * 1e-5
            odd += n % 2
        if odd >= 2:
            return True
    return False
