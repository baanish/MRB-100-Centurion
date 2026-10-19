"""The stores the bays carry, against either bay: each stock bay mount's stores as boxes about its hardpoint
(bay_mounts.json), and the room each box has to the bay's meshes (fit, which nose.check and fuselage_aft.check run as
bay_fit for the forward and aft bays).

bay_mounts.json comes from an export of the game's assets (prefabs under GameObject/, meshes under Mesh/):

    python -I art/blender/m4/nose_bay.py <export>/Assets

It writes one box per store of each mount in MOUNTS: the bounds of every mesh under the store's transform, its
vertices decoded from the mesh asset and placed as the prefab places them (the root's own offset included, as
Hardpoint.SpawnMount instantiates it under the hardpoint), in Blender axes about the hardpoint.

CenturionAuthor.BuildBays puts each bay's hardpoint on the centreline at its doors' hinge station, HARDPOINT_DROP under
fuselage_M's pivot (the prefab root), with the mount's axes the airframe's."""

import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOUNTS_JSON = HERE / "bay_mounts.json"
# CenturionAuthor.BayWeapons, and the AWACS loadout's ARAD-116 x4 in the forward bay (docs/DECISIONS.md, 2026-10-13).
MOUNTS = ("ARM1_internalx4", "bomb_500_internalx8", "bomb_500_internalx12", "bomb_250_internalx18",
          "bomb_250_glide_internalx8", "AAM2_triple_internal")
HARDPOINT_DROP = 0.4  # CenturionAuthor.BuildBays: each bay's hardpoint 0.4 m under the root
STEP = 0.02  # metres between the rays fit casts off a box's faces


# ---------- the table, from the game's assets ----------
def read_mesh(path):
    """A Unity mesh asset's vertices (mesh space) and triangles (vertex indices), from its YAML text."""
    txt = Path(path).read_text(encoding="utf-8")
    count = int(re.search(r"m_VertexCount: (\d+)", txt).group(1))
    channels = re.findall(r"- stream: (\d+)\n\s+offset: (\d+)\n\s+format: (\d+)\n\s+dimension: (\d+)", txt)
    stream, offset, fmt, dim = (int(v) for v in channels[0])  # channel 0 is the position
    if fmt != 0 or dim != 3 or {int(c[0]) for c in channels if int(c[3])} != {0}:
        raise SystemExit(f"{path}: positions not float3 in one interleaved stream")
    data = bytes.fromhex(re.search(r"_typelessdata: ([0-9a-f]*)", txt).group(1))
    stride = len(data) // count
    verts = [struct.unpack_from("<3f", data, i * stride + offset) for i in range(count)]
    wide = re.search(r"m_IndexFormat: (\d+)", txt).group(1) == "1"
    raw = bytes.fromhex(re.search(r"m_IndexBuffer: ([0-9a-f]*)", txt).group(1))
    idx = struct.unpack(f"<{len(raw) // (4 if wide else 2)}{'I' if wide else 'H'}", raw)
    return verts, [idx[i:i + 3] for i in range(0, len(idx) - 2, 3)]


def mesh_index(assets):
    """Mesh asset path by GUID, from the .meta files beside the meshes."""
    out = {}
    for meta in (assets / "Mesh").glob("*.meta"):
        m = re.search(r"^guid: ([0-9a-f]+)", meta.read_text(encoding="utf-8"), re.M)
        if m:
            out[m.group(1)] = meta.with_suffix("")
    return out


def unity_to_blender(p):
    """Unity (x right, y up, z forward) to Blender (x left, y aft, z up): Unity is (-x, z, -y) of Blender."""
    return (-p[0], -p[2], p[1])


def mount_stores(assets, name, meshes):
    """[(store name, [Blender points about the hardpoint])] for one mount prefab: every mesh under each of the root's
    children, placed by the prefab's transforms."""
    sys.path.insert(0, str(HERE.parents[2] / "tools" / "fm"))
    from unity_prefab import Prefab, qrot
    pf = Prefab(assets / "GameObject" / f"{name}.prefab")
    root = next(t for t, v in pf.tf.items() if v["father"] in ("0", None))
    stores = {t: (pf.name_of_tf(t), []) for t, v in pf.tf.items() if v["father"] == root}
    for fid, (cid, body) in pf.docs.items():
        if cid != "33":
            continue
        guid = re.search(r"m_Mesh: \{fileID: \d+, guid: ([0-9a-f]+)", body).group(1)
        t = pf.go_tf[pf.ref(body, "m_GameObject")]
        pos, rot = pf.world(t)
        scale = pf.world_scale(t)
        owner = t
        while pf.tf[owner]["father"] != root:
            owner = pf.tf[owner]["father"]
        verts, _ = read_mesh(meshes[guid])
        stores[owner][1].extend(unity_to_blender([a + b for a, b in zip(pos, qrot(rot, [s * c for s, c in zip(scale, v)]))])
                                for v in verts)
    return [s for s in stores.values() if s[1]]


def write_table(assets):
    assets = Path(assets)
    meshes = mesh_index(assets)
    table = {"source": "the game's mount prefabs and meshes, exported (art/blender/m4/nose_bay.py)",
             "frame": "Blender axes about the hardpoint, metres: x toward the left wing, y aft, z up",
             "mounts": {}}
    for name in MOUNTS:
        boxes = []
        for store, pts in mount_stores(assets, name, meshes):
            lo = [round(min(p[i] for p in pts), 4) for i in range(3)]
            hi = [round(max(p[i] for p in pts), 4) for i in range(3)]
            boxes.append({"store": store, "lo": lo, "hi": hi})
        table["mounts"][name] = boxes
    MOUNTS_JSON.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")
    return table


# ---------- the fit, in Blender ----------
def hardpoint(bay):
    """A bay's hardpoint in world space, as CenturionAuthor.BuildBays places it: bay "F" or "A"."""
    import bpy
    from mathutils import Vector
    door = bpy.data.objects[f"baydoor_{bay}L"].matrix_world.translation
    return Vector((0.0, door.y, bpy.data.objects["fuselage_M"].matrix_world.translation.z - HARDPOINT_DROP))


FACES = (("up", 2, 1), ("down", 2, -1), ("side", 0, 1), ("side", 0, -1), ("ends", 1, 1), ("ends", 1, -1))


def fit(bl, at, parts):
    """Each mount at hardpoint `at` against the render meshes: parts (the bay's part and its closed doors) and every
    other part whose bounds reach a store. Per mount: whether a store box touches a mesh (a face through it, or a
    vertex inside it) or sits inside one (in the solid hull, not a cavity); the room in metres up, down, across and
    along (the least _face_room off its boxes' faces looking that way, a clearance where nothing touches); and the
    stores' lowest and highest z. Returns (that per mount, the parts measured)."""
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    table = json.loads(MOUNTS_JSON.read_text(encoding="utf-8"))["mounts"]
    boxes = {m: [(at + Vector(s["lo"]), at + Vector(s["hi"])) for s in stores] for m, stores in table.items()}
    reach = bl.bounds([c for b in boxes.values() for box in b for c in box])
    verts, polys, used = [], [], []
    for o in bpy.data.collections["Centurion"].all_objects:
        if o.type != "MESH" or o.users_collection[0].name in ("Colliders", "LOD1"):
            continue
        v, f = bl.world_mesh(o)
        if o.name in parts or bl.boxes_touch(reach, bl.bounds(v), 0.0):
            polys += [tuple(i + len(verts) for i in p) for p in f]
            verts += v
            used.append(o.name)
    tree = BVHTree.FromPolygons(verts, polys)
    points = np.array([tuple(v) for v in verts])
    out = {}
    for name, stores in boxes.items():
        room = dict.fromkeys(("up", "down", "side", "ends"), 9.0)
        touches = inside = False
        for lo, hi in stores:
            for key, axis, sign in FACES:
                room[key] = min(room[key], _face_room(tree, lo, hi, axis, sign))
            touches = touches or _box_touches(tree, points, lo, hi)
            inside = inside or _in_solid(tree, (lo + hi) / 2)
        out[name] = {**{k: round(v, 3) for k, v in room.items()}, "touches": touches, "in_solid": inside,
                     "z": [round(min(lo.z for lo, _ in stores), 3), round(max(hi.z for _, hi in stores), 3)]}
    return out, sorted(used)


def _face_room(tree, lo, hi, axis, sign):
    """The least distance a ray travels off the box face that looks along axis * sign before it meets a mesh, cast
    every STEP across the face."""
    from mathutils import Vector
    u, v = [i for i in range(3) if i != axis]
    d = Vector((0, 0, 0))
    d[axis] = sign
    best = 9.0
    nu = max(1, round((hi[u] - lo[u]) / STEP))
    nv = max(1, round((hi[v] - lo[v]) / STEP))
    for i in range(nu + 1):
        for j in range(nv + 1):
            p = Vector((0, 0, 0))
            p[u] = lo[u] + (hi[u] - lo[u]) * i / nu
            p[v] = lo[v] + (hi[v] - lo[v]) * j / nv
            p[axis] = hi[axis] if sign > 0 else lo[axis]
            hit = tree.ray_cast(p, d, best)
            if hit[0] is not None:
                best = hit[3]
    return best


def _in_solid(tree, p):
    """Whether p is inside the meshes (closed shells, outward normals): the first face a ray from p meets, straight
    down, is one it leaves through. Down, because the roof's frames lie flush with the roof, where a ray up would meet
    two faces at once."""
    from mathutils import Vector
    loc, normal, _, _ = tree.ray_cast(p, Vector((0.0, 0.0, -1.0)))
    return loc is not None and normal.z < 0


def _box_touches(tree, points, lo, hi):
    """Whether any face of the meshes passes through the box, or any of their vertices sits inside it."""
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    if ((points >= tuple(lo)) & (points <= tuple(hi))).all(axis=1).any():
        return True
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for vert in bm.verts:
        vert.co = Vector(tuple(lo[i] + (hi[i] - lo[i]) * (vert.co[i] + 0.5) for i in range(3)))
    box = BVHTree.FromBMesh(bm)
    bm.free()
    return bool(tree.overlap(box))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -I art/blender/m4/nose_bay.py <export>/Assets")
    for mount, boxes in write_table(sys.argv[1])["mounts"].items():
        lo = [min(b["lo"][i] for b in boxes) for i in range(3)]
        hi = [max(b["hi"][i] for b in boxes) for i in range(3)]
        print(f"{mount}: {len(boxes)} stores, x {lo[0]:.3f} to {hi[0]:.3f}, y {lo[1]:.3f} to {hi[1]:.3f}, "
              f"z {lo[2]:.3f} to {hi[2]:.3f}")
