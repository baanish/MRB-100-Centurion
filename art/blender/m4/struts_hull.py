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
    return BVHTree.FromPolygons(vertices, triangles, all_triangles=True)


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
