"""The exported Centurion as world-space triangles, read from art/export without Blender: the binary FBX meshes that
tools/export_blockout.py writes, posed by blockout.json at any wing extension, rasterized into the skin atlas, with
the ray casts and physical edges faction_marks.py checks its roundels against. Frame: x left, y aft, z up, metres."""
import json
import struct
import zlib

import numpy as np

SKIN = "Centurion_skin"
ARRAY = {"d": "<f8", "f": "<f4", "i": "<i4", "l": "<i8", "b": "u1", "c": "u1"}
SCALAR = {"D": "<d", "F": "<f", "I": "<i", "L": "<q", "Y": "<h", "C": "<B", "B": "<B"}


def fbx_nodes(data):
    """The node tree of a binary FBX: (name, properties, children), arrays decoded to numpy."""
    if data[:23] != b"Kaydara FBX Binary  \x00\x1a\x00":
        raise ValueError("expected a binary FBX")
    wide = struct.unpack_from("<I", data, 23)[0] >= 7500
    header, size = ("<QQQB", 25) if wide else ("<IIIB", 13)

    def node(start):
        end, count, _, name_size = struct.unpack_from(header, data, start)
        if end == 0:
            return None, start + size
        pos = start + size
        name = data[pos:pos + name_size].decode()
        pos += name_size
        props = []
        for _ in range(count):
            kind = chr(data[pos])
            pos += 1
            if kind in SCALAR:
                props.append(struct.unpack_from(SCALAR[kind], data, pos)[0])
                pos += struct.calcsize(SCALAR[kind])
            elif kind in "SR":
                n = struct.unpack_from("<I", data, pos)[0]
                raw = data[pos + 4:pos + 4 + n]
                props.append(raw.split(b"\x00\x01")[0].decode("utf-8", "replace") if kind == "S" else raw)
                pos += 4 + n
            else:
                length, encoding, n = struct.unpack_from("<III", data, pos)
                raw = data[pos + 12:pos + 12 + n]
                props.append(np.frombuffer(zlib.decompress(raw) if encoding else raw, ARRAY[kind], length))
                pos += 12 + n
        children = []
        while pos < end:
            child, pos = node(pos)
            if child is None:
                break
            children.append(child)
        return (name, props, children), end

    pos, tree = 27, []
    while pos < len(data):
        item, pos = node(pos)
        if item is None:
            break
        tree.append(item)
    return tree


def child(node, name):
    return next((c for c in node[2] if c[0] == name), None)


def fbx_triangles(path, model_name):
    """(corners [n,3,3], uvs [n,3,2], material names [n]) of the model named `model_name`, in the FBX's own axes,
    polygons fanned into triangles, UVs from the first layer."""
    tree = fbx_nodes(path.read_bytes())
    objects = next(n for n in tree if n[0] == "Objects")
    links = [c[1] for c in next(n for n in tree if n[0] == "Connections")[2]]
    kinds = {o[1][0]: (o[0], o[1][1]) for o in objects[2]}
    model = next(i for i, (kind, n) in kinds.items() if kind == "Model" and n == model_name)
    attached = [a for _, a, b, *_ in links if b == model]
    geometry = next(o for o in objects[2] if o[0] == "Geometry" and o[1][0] in attached)
    materials = [kinds[a][1] for a in attached if kinds.get(a, ("",))[0] == "Material"]
    vertices = child(geometry, "Vertices")[1][0].reshape(-1, 3)
    index = child(geometry, "PolygonVertexIndex")[1][0]
    uv_layer = child(geometry, "LayerElementUV")
    uv = child(uv_layer, "UV")[1][0].reshape(-1, 2)
    uv_index = child(uv_layer, "UVIndex")[1][0]
    slots = child(child(geometry, "LayerElementMaterial"), "Materials")[1][0]
    ends = np.flatnonzero(index < 0)
    starts = np.r_[0, ends[:-1] + 1]
    corner = np.where(index < 0, ~index, index)
    fans = [(s, k, k + 1, p) for p, (s, e) in enumerate(zip(starts, ends)) for k in range(s + 1, e)]
    fans = np.array(fans)
    slot = slots[fans[:, 3]] if len(slots) == len(starts) else np.full(len(fans), slots[0])
    return vertices[corner[fans[:, :3]]], uv[uv_index[fans[:, :3]]], np.array(materials)[slot]


def moving_parts(parts):
    """Parts that move against the airframe: a hinged surface, a telescoping stage, and everything they carry."""
    def moves(n):
        p = parts.get(n)
        return p is not None and ("hinge_axis" in p["props"] or "travel_m" in p["props"] or moves(p["blender_parent"]))
    return {n for n in parts if moves(n)}


def part_offsets(parts, extension):
    """World offset of every part with the wing's telescoping stages slid out by `extension` (0 retracted, 1 extended):
    a stage moves its travel along its slide axis and carries its children."""
    own = {n: np.asarray(p["props"]["slide_axis"]) * p["props"]["travel_m"] * extension if "travel_m" in p["props"]
           else np.zeros(3) for n, p in parts.items()}

    def offset(n):
        return own[n] + (offset(parts[n]["blender_parent"]) if parts[n]["blender_parent"] in parts else 0)
    return {n: offset(n) for n in parts}


def load_airframe(export, extension=0.0):
    """Every exported render mesh: triangle corners, UVs, owning part (index into names) and whether it is skin.
    Part-local FBX axes are (x, z, -y) of Blender's; blockout.json gives each part's world pivot and its axes in
    Unity's frame, Unity = (-x, z, -y) of Blender."""
    parts = json.loads((export / "blockout.json").read_text())["parts"]
    offsets = part_offsets(parts, extension)
    names, corners, uvs, owner, skin = [], [], [], [], []
    for name, p in sorted(parts.items()):
        if not p.get("fbx"):
            continue
        local, uv, material = fbx_triangles(export / p["fbx"], name)
        b = np.stack([local[..., 0], -local[..., 2], local[..., 1]], -1)
        u = np.stack([-b[..., 0], b[..., 2], -b[..., 1]], -1)
        a = p["axes_unity"]
        w = u[..., :1] * a["right"] + u[..., 1:2] * a["up"] + u[..., 2:] * a["forward"] + p["pivot_unity"]
        names.append(name)
        corners.append(np.stack([-w[..., 0], -w[..., 2], w[..., 1]], -1) + offsets[name])
        uvs.append(uv)
        owner.append(np.full(len(local), len(names) - 1))
        skin.append(material == SKIN)
    return {"names": names, "corners": np.concatenate(corners), "uv": np.concatenate(uvs), "part": np.concatenate(owner),
            "skin": np.concatenate(skin), "moving": moving_parts(parts), "sha256": {n: parts[n]["sha256"] for n in names}}


def barycentric(t, x, y):
    """Barycentric weights of points (x, y) in the 2D triangle t (3, 2); None when it is degenerate."""
    a, b, c = t
    d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(d) < 1e-14:
        return None
    l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
    l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
    return np.stack([l1, l2, 1 - l1 - l2], -1)


def atlas_px(frame, size, k):
    """Triangle k's corners in atlas texel coordinates (column, row; PNG rows top down; texel centres at +.5)."""
    uv = frame["uv"][k]
    return np.stack([uv[..., 0] * size - .5, (1 - uv[..., 1]) * size - .5], -1)


def texel_cover(frame, size, rows, cols, triangles):
    """For each texel (rows, cols): every triangle among `triangles` whose UV covers its centre, as (texel, triangle)
    index pairs, and the world position of the texel on that triangle."""
    lo_c, hi_c, lo_r, hi_r = cols.min(), cols.max(), rows.min(), rows.max()
    at = -np.ones((hi_r - lo_r + 1, hi_c - lo_c + 1), int)
    at[rows - lo_r, cols - lo_c] = np.arange(len(rows))
    texel, tri, pos = [], [], []
    for k in triangles:
        t = atlas_px(frame, size, k)
        x0, y0 = np.maximum(np.floor(t.min(0)).astype(int), (lo_c, lo_r))
        x1, y1 = np.minimum(np.ceil(t.max(0)).astype(int), (hi_c, hi_r))
        if x1 < x0 or y1 < y0:
            continue
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        i = at[yy - lo_r, xx - lo_c]
        listed = i >= 0
        if not listed.any():
            continue
        w = barycentric(t, xx[listed], yy[listed])
        if w is None:
            continue
        inside = (w > -1e-9).all(-1)
        texel.append(i[listed][inside])
        tri.append(np.full(inside.sum(), k))
        pos.append(w[inside] @ frame["corners"][k])
    if not texel:
        return np.zeros(0, int), np.zeros(0, int), np.zeros((0, 3))
    return np.concatenate(texel), np.concatenate(tri), np.concatenate(pos)


def uv_bbox_overlaps(frame, size, cols, rows, pad=1):
    """Triangles whose atlas box overlaps the box of these texels."""
    t = np.stack([frame["uv"][..., 0] * size - .5, (1 - frame["uv"][..., 1]) * size - .5], -1)
    lo, hi = t.min(1), t.max(1)
    return np.flatnonzero((hi[:, 0] >= cols.min() - pad) & (lo[:, 0] <= cols.max() + pad)
                          & (hi[:, 1] >= rows.min() - pad) & (lo[:, 1] <= rows.max() + pad))


def texel_density(frame, size):
    """Texels per metre of every triangle (UV area over world area), and the skin's median: the atlas density."""
    c, uv = frame["corners"], frame["uv"] * size
    world = np.linalg.norm(np.cross(c[:, 1] - c[:, 0], c[:, 2] - c[:, 0]), axis=1) / 2
    d1, d2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    texels = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / 2
    density = np.sqrt(texels / np.maximum(world, 1e-12))
    return density, float(np.median(density[frame["skin"] & (world > 1e-4)]))


def first_hit(frame, origin, direction, skip=()):
    """Distance along the ray to the nearest triangle (Moller-Trumbore), inf when none; triangles in `skip` ignored."""
    c = frame["corners"]
    e1, e2 = c[:, 1] - c[:, 0], c[:, 2] - c[:, 0]
    p = np.cross(direction, e2)
    det = (e1 * p).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
    s = origin - c[:, 0]
    u = (s * p).sum(1) * inv
    q = np.cross(s, e1)
    v = (q @ direction) * inv
    t = (q * e2).sum(1) * inv
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-4)
    hit[list(skip)] = False
    return float(t[hit].min()) if hit.any() else np.inf


def occluded(frame, points, axis, sign, own, eps=.01):
    """Which points something hides from an orthographic view looking along -sign*axis (axis 2 with sign 1: from
    above): any triangle crossing the ray from the point toward the viewer more than eps from it. Triangles of the
    point's own surface (`own`, the triangles carrying it and their two-sided copies) are not counted."""
    a, b = [i for i in range(3) if i != axis]
    c = frame["corners"]
    lo, hi = points.min(0), points.max(0)
    near = np.flatnonzero((c[:, :, a].max(1) >= lo[a]) & (c[:, :, a].min(1) <= hi[a]) & (c[:, :, b].max(1) >= lo[b])
                          & (c[:, :, b].min(1) <= hi[b]) & ((c[:, :, axis].max(1) - lo[axis]) * sign > -eps))
    near = np.setdiff1d(near, own)
    hidden = np.zeros(len(points), bool)
    px, py, pz = points[:, a], points[:, b], points[:, axis]
    for chunk in np.array_split(near, max(1, len(near) // 1500)):
        t = c[chunk]
        ax, ay, bx, by, cx, cy = t[:, 0, a], t[:, 0, b], t[:, 1, a], t[:, 1, b], t[:, 2, a], t[:, 2, b]
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        good = np.abs(d) > 1e-12
        d = np.where(good, d, 1)
        l1 = ((by - cy)[:, None] * (px - cx[:, None]) + (cx - bx)[:, None] * (py - cy[:, None])) / d[:, None]
        l2 = ((cy - ay)[:, None] * (px - cx[:, None]) + (ax - cx)[:, None] * (py - cy[:, None])) / d[:, None]
        l3 = 1 - l1 - l2
        inside = good[:, None] & (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        depth = l1 * t[:, 0, axis][:, None] + l2 * t[:, 1, axis][:, None] + l3 * t[:, 2, axis][:, None]
        hidden |= (inside & ((depth - pz) * sign > eps)).any(0)
    return hidden


def physical_edges(frame, triangles):
    """The open edges of a skin sheet (segments [n, 2, 3]): edges one triangle uses, after welding corners to the
    millimetre and dropping two-sided copies. A control-surface cut-out, a part joint or a root ends the sheet there."""
    key = np.round(frame["corners"][triangles] * 1000).astype(np.int64)
    flat = key.reshape(len(triangles), 3, 3)
    order = np.sort(flat[:, :, 0] * 10 ** 12 + flat[:, :, 1] * 10 ** 6 + flat[:, :, 2], axis=1)
    _, unique = np.unique(order, axis=0, return_index=True)
    tris = flat[np.sort(unique)]
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    ids = edges[:, :, 0] * 10 ** 12 + edges[:, :, 1] * 10 ** 6 + edges[:, :, 2]
    swap = ids[:, 0] > ids[:, 1]
    ids[swap] = ids[swap][:, ::-1]
    edges[swap] = edges[swap][:, ::-1]
    _, first, count = np.unique(ids, axis=0, return_index=True, return_counts=True)
    return edges[first[count == 1]] / 1000.0


def segment_distance(points, segments):
    """Distance from each point to the nearest segment."""
    best = np.full(len(points), np.inf)
    for chunk in np.array_split(segments, max(1, len(segments) // 2000)):
        a, ab = chunk[:, 0], chunk[:, 1] - chunk[:, 0]
        ap = points[:, None] - a[None]
        t = np.clip((ap * ab[None]).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-12)[None], 0, 1)
        best = np.minimum(best, np.linalg.norm(ap - t[..., None] * ab[None], axis=-1).min(1))
    return best
