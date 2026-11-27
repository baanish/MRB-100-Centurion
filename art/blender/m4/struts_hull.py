"""The detailed fuselage triangles used by the strut's body landing."""
import bpy
from types import SimpleNamespace
from mathutils.bvhtree import BVHTree

from . import fuselage_aft, nose
from .tail_join import conform_fillet_boundary


def hull_triangles(bl, surf, slots):
    # Group-only builds still have blockout neighbours. Use the same detailed builders as the composite.
    vertices, triangles = [], []
    for group, owner in ((nose, 'fuselage_F'), (fuselage_aft, 'fuselage_M')):
        parts = group.build(bl, surf, slots)
        mesh = bpy.data.meshes.new('strut_landing')
        parts[owner].bm.to_mesh(mesh)
        mesh.calc_loop_triangles()
        offset = len(vertices)
        vertices.extend(v.co.copy() for v in mesh.vertices)
        triangles.extend(tuple(offset + i for i in t.vertices) for t in mesh.loop_triangles)
        bpy.data.meshes.remove(mesh)
        for part in parts.values():
            part.bm.free()
    return LandingHull(BVHTree.FromPolygons(vertices, triangles, all_triangles=True))


class LandingHull:
    """The hull's BVH with find_nearest's ties broken by position: a point nearest an edge or corner the triangles
    share is as near all of them, and BVHTree returns whichever its build order puts first, so any change elsewhere
    in fuselage_F (a paint panel's face order, the refuelling slipway) moved the strut root and its collider hull up
    to 105 mm. The normal is the mean of every triangle at the nearest distance."""
    TIE_M = 1e-6

    def __init__(self, tree):
        self.tree = tree

    def find_nearest(self, point, distance=1.0e30):
        hit, normal, index, d = self.tree.find_nearest(point, distance)
        if hit is None:
            return hit, normal, index, d
        tied = self.tree.find_nearest_range(point, d + self.TIE_M)
        if len(tied) > 1:
            n = sum((t[1] for t in tied if t[3] <= d + self.TIE_M), normal * 0.0)
            if n.length > 1e-9:
                normal = n.normalized()
            index = min(t[2] for t in tied if t[3] <= d + self.TIE_M)
        return hit, normal, index, d

    def __getattr__(self, name):
        return getattr(self.tree, name)


def hull_distance(hull, point):
    """Signed normal distance to the detailed skin, negative inside it."""
    hit, normal, _, _ = hull.find_nearest(point)
    return (point - hit).dot(normal)


def land_root_column(points, hull, field, clearance):
    """Keep the smooth fillet's height profile above the tessellated body, with its cap buried."""
    result = [points[0]]
    end = len(points) - 1
    for i, point in enumerate(points[1:], 1):
        hit, normal, _, _ = hull.find_nearest(point)
        landed = hit + normal * (field(point) - clearance)
        u = min(1.0, (end - i) / 3.0)
        result.append(point.lerp(landed, u * u * (3 - 2 * u)))
    return result


def conform_root_boundary(part, grid, hull, clearance):
    rows = [[grid.V[2][j], grid.V[1][j]] for j in range(grid.n)]
    rows.append(rows[0])
    return conform_fillet_boundary(part, SimpleNamespace(V=rows), 1, hull, -clearance)
