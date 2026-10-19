"""Join the leading-edge fillet to the panel instead of shading two overlapping rims."""
import bmesh
from types import SimpleNamespace

LANDING_SMOOTH_PASSES = 2  # past the first: one alone left straight runs with corners along the bare root's landing


def land_panel_root(part, panel, bare, hull, clearance, skin, structure, root_class):
    """Give the bare strip a surface boundary and keep its root cap buried."""
    count = len(bare)
    start = next(i for i in range(count) if bare[i] and not bare[(i - 1) % count])
    indices = [start]
    while bare[(indices[-1] + 1) % count]:
        indices.append((indices[-1] + 1) % count)
    points = []
    for i in indices:
        a, b = panel.V[0][i].co, panel.V[1][i].co
        direction = a - b
        hit, normal, _, _ = hull.ray_cast(b, direction.normalized(), direction.length + 0.1)
        if hit is None:
            raise SystemExit(f'tail: bare root ray missed column {i}')
        points.append(hit + normal * clearance)
    smooth = [points[0]] + [points[i - 1] * 0.25 + points[i] * 0.5 + points[i + 1] * 0.25
                            for i in range(1, len(points) - 1)] + [points[-1]]
    # Further passes hold the trailing edge's two columns, where the line turns round the edge, and the point next to
    # the first, by the fillet's end, which build_fillet lands on these faces.
    pinned = {0, 1, len(points) - 1} | {j for j, i in enumerate(indices) if i in (0, count - 1)}
    for _ in range(LANDING_SMOOTH_PASSES):
        smooth = [p if j in pinned else smooth[j - 1] * 0.25 + p * 0.5 + smooth[j + 1] * 0.25
                  for j, p in enumerate(smooth)]
    landing = []
    for point in smooth:
        hit, normal, _, _ = hull.find_nearest(point)
        landing.append(part.bm.verts.new(hit + normal * clearance))
    rows = [[panel.V[1][i], vertex, panel.V[0][i]] for i, vertex in zip(indices, landing)]
    for j, (i, k) in enumerate(zip(indices, indices[1:])):
        part.bm.faces.remove(panel.F[0, i])
        a, b = rows[j], rows[j + 1]
        part.tag([part.bm.faces.new((a[0], b[0], b[1], a[1]))], skin, root_class)
        part.tag([part.bm.faces.new((a[1], b[1], b[2], a[2]))], structure)
    for row in (rows[0], rows[-1]):
        part.tag([part.bm.faces.new(tuple(row))], skin, root_class)
    conform_fillet_boundary(part, SimpleNamespace(V=rows), 1, hull, clearance, preserve_companion=True)
    hidden = [row[2] for row in rows[1:-1]
              if all(face.material_index == part.slots.index(structure) for face in row[2].link_faces)]
    bmesh.ops.dissolve_verts(part.bm, verts=hidden, use_face_split=False)


def conform_fillet_boundary(part, grid, column, hull, clearance, preserve_companion=False):
    """Split the landing at triangle crossings so its chords cannot cut through the cone."""
    boundary = []
    if not preserve_companion:
        for row in grid.V:
            vertex = row[column - 1]
            hit, normal, _, _ = hull.find_nearest(vertex.co)
            height = max(0.012, (vertex.co - hit).dot(normal))
            vertex.co = hit + normal * height
    for row in range(len(grid.V) - 1):
        a, b = grid.V[row][column], grid.V[row + 1][column]
        pa, pb = a.co.copy(), b.co.copy()
        ca, cb = grid.V[row][column - 1], grid.V[row + 1][column - 1]
        pca, pcb = ca.co.copy(), cb.co.copy()
        heights = [max(0.012, (point - hit).dot(normal)) for point in (pca, pcb)
                   for hit, normal, _, _ in [hull.find_nearest(point)]]

        def project(t):
            hit, normal, index, distance = hull.find_nearest(pa.lerp(pb, t))
            return hit, index

        samples = [(i / 32, project(i / 32)[1]) for i in range(33)]
        crossings = []
        for (lo, left), (hi, right) in zip(samples, samples[1:]):
            if left == right:
                continue
            for _ in range(24):
                mid = (lo + hi) / 2
                if project(mid)[1] == left:
                    lo = mid
                else:
                    hi = mid
            t = (lo + hi) / 2
            if 1e-5 < t < 1 - 1e-5 and (not crossings or t - crossings[-1] > 1e-4):
                crossings.append(t)
        boundary.append(a)
        previous, vertex, companion = 0.0, a, ca
        for t in crossings:
            edge = part.bm.edges.get((vertex, b))
            _, vertex = bmesh.utils.edge_split(edge, vertex, (t - previous) / (1 - previous))
            hit, _ = project(t)
            normal = (pa.lerp(pb, t) - hit).normalized()
            if normal.length < 0.5:
                normal = hull.find_nearest(hit)[1]
            # Offset outward even when the unsplit chord is below the hull.
            facet = hull.find_nearest(hit)[1]
            if normal.dot(facet) < 0:
                normal = -normal
            vertex.co = hit + normal * clearance
            edge = part.bm.edges.get((companion, cb))
            _, companion = bmesh.utils.edge_split(edge, companion, (t - previous) / (1 - previous))
            if preserve_companion:
                companion.co = pca.lerp(pcb, t)
            else:
                hit, normal, _, _ = hull.find_nearest(pca.lerp(pcb, t))
                companion.co = hit + normal * (heights[0] * (1 - t) + heights[1] * t)
            face = next(face for face in vertex.link_faces if companion in face.verts)
            bmesh.utils.face_split(face, companion, vertex)
            boundary.append(vertex)
            previous = t
    boundary.append(grid.V[-1][column])
    return boundary


def join_fillet_nose(part, panel, fillet, panel_columns, fillet_columns, chord_limit, structure):
    bm = part.bm
    signed = lambda column: column[0] * (1 if column[1] else -1)
    nose = [i for i, column in enumerate(fillet_columns) if column[0] <= chord_limit]
    coordinates = [signed(fillet_columns[i]) for i in nose]
    intervals = [k for k in range(len(panel_columns) - 1)
                 if chord_limit >= signed(panel_columns[k]) > signed(panel_columns[k + 1]) >= -chord_limit]

    def split_row(row):
        vertices = {}
        for k in intervals:
            start, end = signed(panel_columns[k]), signed(panel_columns[k + 1])
            a, b = panel.V[row][k:k + 2]
            vertices[start], vertices[end] = a, b
            previous = start
            for coordinate in coordinates:
                if not end < coordinate < start:
                    continue
                edge = bm.edges.get((a, b))
                fraction = (previous - coordinate) / (previous - end)
                _, a = bmesh.utils.edge_split(edge, a, fraction)
                vertices[coordinate] = a
                previous = coordinate
        return vertices

    root, join = split_row(0), split_row(1)
    closing_column = fillet.n - 1
    faces = [panel.F[0, k] for k in intervals]
    faces += [fillet.F[i, closing_column] for i in nose[:-1]]
    bmesh.ops.delete(bm, geom=faces, context='FACES_ONLY')
    bridges = []
    for i, j in zip(nose, nose[1:]):
        a, b = signed(fillet_columns[i]), signed(fillet_columns[j])
        bridges.append(bm.faces.new((root[a], root[b], fillet.V[j][-1], fillet.V[i][-1])))
    for i in (nose[0], nose[-1]):
        coordinate = signed(fillet_columns[i])
        bridges.append(bm.faces.new((join[coordinate], root[coordinate], fillet.V[i][-1])))
    part.tag(bridges, structure, 0)
    bmesh.ops.weld_verts(bm, targetmap={fillet.V[i][0]: join[signed(fillet_columns[i])] for i in nose})
    bmesh.ops.delete(bm, geom=[edge for edge in bm.edges if not edge.link_faces], context='EDGES')
