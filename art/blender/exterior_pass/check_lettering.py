"""The lettering check: every lettered stencil the body groups paint (nose.lettering, fuselage_aft.lettering) reads
left to right in world space on the finished UVs. The paint lays a stencil on the texels of the faces at its place,
written to read from outside its own side; a face elsewhere that maps the same texels shows it too, and one on the
other side of the aircraft shows it mirrored. So each stencil, at its middle and both ends, is found on the skin by a
ray, and every skin face whose UVs hold the texel hit there must lie on the stencil's side (markings only on unmirrored
islands, as the Icarus's). Fails by name. Read-only.
blender --background <s4_uv or s6_bake blend> --python check_lettering.py -- [<out.json>]"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.geometry import barycentric_transform

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT.parent))
from m4 import fuselage_aft, nose, paint  # noqa: E402
from m4.blockout import load_blockout  # noqa: E402

SKIN = "Centurion_skin"
ATLAS = 4096
LEGIBLE_PX_M = 10.0  # a face mapping its texels thinner than this (the control surfaces' trim on one skin texel) shows
# no lettering, mirrored or not
SAME_SIDE_X = 0.02  # a stencil this near the centreline has no other side
MIRROR_M = 0.3  # a face using the texel within this of the hit's mirror image is its mirrored copy (other users, the
# control surfaces' trim strips that borrow skin texels, are listed, not failed: no lettering reads on them)

bl = load_blockout()
bl.BOAT_TAIL = bl.S61_BOAT_TAIL_VISUAL  # the paint's coordinates (detail_centurion)
c = paint.FuselageCoords(bl)


def ray(s, where):
    """(origin, direction) of a ray onto the stencil at station s from outside."""
    y = s - bl.Y0
    if where[0] == "z":
        return Vector((where[2] * 3.0, y, where[1])), Vector((-where[2], 0.0, 0.0))
    if where[0] == "door":
        p, n = nose.gear_door_open(bl, s, where[1], where[2])
        return p + n * 1.0, -n
    p = c.point(s, where[1])
    ds = c.point(s + 0.01, where[1]) - c.point(s - 0.01, where[1])
    da = c.point(s, where[1] + 0.5) - c.point(s, where[1] - 0.5)
    n = np.cross(ds, da)
    n /= np.linalg.norm(n)
    if n @ np.array([p[0], 0.0, 0.0]) < 0 or (abs(p[0]) < 0.05 and n[2] < 0):
        n = -n  # outward
    return Vector(p + n * 0.3), Vector(-n)  # from just outside: a nacelle or strut stands off the flank


# every skin loop triangle's UVs and world corners, for the texel's users
tris = []
for o in bpy.data.objects:
    if o.type != "MESH" or "_lod1" in o.name or "_colmesh" in o.name or not o.data.uv_layers or o.hide_render:
        continue
    me = o.data
    sk = [i for i, m in enumerate(me.materials) if m and m.name == SKIN]
    if not sk:
        continue
    me.calc_loop_triangles()
    uv = np.zeros(2 * len(me.loops))
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    co = np.zeros(3 * len(me.vertices))
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(o.matrix_world)
    co = co @ mw[:3, :3].T + mw[:3, 3]
    lt = me.loop_triangles
    loops = np.zeros(3 * len(lt), int)
    verts = np.zeros(3 * len(lt), int)
    mat = np.zeros(len(lt), int)
    lt.foreach_get("loops", loops)
    lt.foreach_get("vertices", verts)
    lt.foreach_get("material_index", mat)
    U, W = uv[loops.reshape(-1, 3)], co[verts.reshape(-1, 3)]
    ua = np.abs(np.cross(U[:, 1] - U[:, 0], U[:, 2] - U[:, 0])) / 2 * ATLAS ** 2
    wa = np.linalg.norm(np.cross(W[:, 1] - W[:, 0], W[:, 2] - W[:, 0]), axis=1) / 2
    keep = np.isin(mat, sk) & (ua > (LEGIBLE_PX_M ** 2) * wa)  # a texel smeared across a face is no lettering
    tris.append((o.name, U[keep], W[keep]))


def users(t):
    """World points of every skin triangle whose UVs hold texel t."""
    out = []
    for name, U, W in tris:
        a, b, cc = U[:, 0], U[:, 1], U[:, 2]
        v0, v1, v2 = b - a, cc - a, t - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        ok = np.abs(den) > 1e-14
        den = np.where(ok, den, 1.0)
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        u = 1 - v - w
        hit = ok & (u >= -1e-6) & (v >= -1e-6) & (w >= -1e-6)
        for i in np.nonzero(hit)[0]:
            out.append((name, W[i, 0] * u[i] + W[i, 1] * v[i] + W[i, 2] * w[i]))
    return out


for o in bpy.data.objects:  # the rays see the rendered model only
    if "_colmesh" in o.name or "_lod1" in o.name or o.hide_render:
        o.hide_viewport = True
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
sc = bpy.context.scene
report, fails = [], []
for text, s, where, half in nose.lettering(c) + fuselage_aft.lettering(c):
    for ds in (-0.8 * half, 0.0, 0.8 * half):
        org, d = ray(s + ds, where)
        hit, loc, nrm, fi, ob, _ = sc.ray_cast(dg, org, d)
        if not hit:
            fails.append(f"{text} at station {round(s + ds, 2)} {where}: no skin under it")
            continue
        me = ob.data
        p = me.polygons[fi]
        m = me.materials[p.material_index] if me.materials else None
        if not m or m.name != SKIN:
            fails.append(f"{text} at station {round(s + ds, 2)} {where}: {ob.name} ({m.name if m else None}) over it")
            continue
        # the texel under the hit, by the hit triangle's barycentrics
        me.calc_loop_triangles()
        inv = ob.matrix_world.inverted()
        lp = inv @ loc
        best = None
        for t in me.loop_triangles:
            if t.polygon_index != fi:
                continue
            A, B, C = (me.vertices[v].co for v in t.vertices)
            uvs = [me.uv_layers.active.data[li].uv for li in t.loops]
            q = barycentric_transform(lp, A, B, C, Vector((*uvs[0], 0)), Vector((*uvs[1], 0)), Vector((*uvs[2], 0)))
            r = barycentric_transform(q, Vector((*uvs[0], 0)), Vector((*uvs[1], 0)), Vector((*uvs[2], 0)), A, B, C)
            err = (r - lp).length
            if best is None or err < best[0]:
                best = (err, np.array([q.x, q.y]))
        side = np.sign(loc.x) if abs(loc.x) > SAME_SIDE_X else 0
        mirror = np.array([-loc.x, loc.y, loc.z])
        us = users(best[1])
        others = [(n_, w) for n_, w in us if side and np.linalg.norm(w - mirror) < MIRROR_M]
        elsewhere = sorted({n_ for n_, w in us if np.linalg.norm(w - np.array(loc)) > MIRROR_M
                            and np.linalg.norm(w - mirror) >= MIRROR_M})
        report.append({"text": text, "station": round(s + ds, 2), "object": ob.name, "side": int(side),
                       "mirrored_users": len(others), "other_users": elsewhere})
        if others:
            n_, w = others[0]
            fails.append(f"{text} at station {round(s + ds, 2)} on {ob.name}: its texels also skin {n_} at "
                         f"{[round(float(v), 2) for v in w]}, the other side, where it reads mirrored")
out = Path(sys.argv[sys.argv.index("--") + 1]).resolve() if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 1 else None
if out:
    out.write_text(json.dumps({"points": report, "fails": fails}, indent=1))
print("LETTERING", len(report), "points,", len(fails), "fails", json.dumps(fails[:12]), flush=True)
if fails:
    sys.exit(1)
