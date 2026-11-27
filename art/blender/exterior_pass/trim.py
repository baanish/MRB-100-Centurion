"""Structure members mapped onto strips of the stock jet_mechanical sheet, in the game's own UV0 (no shader tricks).
UNTESTED. The review sample's trim_material repeated a strip in the shader (fract); the game samples UV0 directly, so
here a member is cut where each pass of its strip ends and each piece maps onto the strip once.

Strips and rates are the Darkreach's own: rect (u0, u1, v0, v1) on the 2048 sheet, texels per metre,
alpha cut-out wanted (the stock material cuts at 0.394 on perforated parts backed by a cavity)."""
import math

import bmesh

ATLAS_PX = 2048
TRIMS = {
    "wing_web": ((0.377, 0.667, 0.867, 0.940), 154, True),  # wing1b_L's break web: hex openings
    "body_web": ((0.280, 0.560, 0.936, 0.998), 187, False),  # gearbay_L's break wall: corrugated
    "flange": ((0.280, 0.660, 0.940, 1.000), 371, False),  # caps, stringers, flanges: the top trim
    "rail": ((0.000, 0.188, 0.763, 0.790), 430, False),  # the split airbrake's rail: spoiler frames, cove edges
    # a dark metal patch whose stock occlusion is 0 (no ambient, no reflections; metal takes no diffuse light): a thin
    # bay's backdrop reads near black through the holes, as the Darkreach's insides do. The game's Centurion_trim_cut is
    # a copy of jet_mechanical, which binds the occlusion map (_OCCLUSIONMAP, strength 1)
    "dark": ((0.909, 0.919, 0.465, 0.480), 154, False),  # (inside the 0.906 to 0.922 by 0.462 to 0.484 patch: mips stay on it)
}


def strip_metres(name):
    (u0, u1, _, _), tpm, _ = TRIMS[name]
    return (u1 - u0) * ATLAS_PX / tpm


def apply(bm, faces, along, name, uv_name="UVMap"):
    """Cut `faces` at each strip length along `along` and give them UV0 on the strip `name`. Returns the faces after the
    cuts (the originals and their new pieces)."""
    (u0, u1, v0, v1), _, _ = TRIMS[name]
    along = along.normalized()
    L = strip_metres(name)
    faces = set(faces)
    ds = [v.co.dot(along) for f in faces for v in f.verts]
    if not ds:
        return []
    lo, hi = min(ds), max(ds)
    for k in range(math.floor(lo / L) + 1, math.ceil(hi / L)):
        geom = list(faces) + list(dict.fromkeys(e for f in faces for e in f.edges)) + list(dict.fromkeys(v for f in faces for v in f.verts))
        res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=along * (k * L), plane_no=along)
        faces |= {g for g in res["geom"] if isinstance(g, bmesh.types.BMFace)}
    faces = {f for f in faces if f.is_valid}
    uv = bm.loops.layers.uv.get(uv_name) or bm.loops.layers.uv.new(uv_name)
    bm.normal_update()
    for f in faces:
        n = f.normal
        across = n.cross(along)
        if across.length < 1e-6:
            across = n.orthogonal()
        across.normalize()
        k = math.floor(f.calc_center_median().dot(along) / L)
        ws = [l.vert.co.dot(across) for l in f.loops]
        w0, span = min(ws), max(max(ws) - min(ws), 1e-6)
        for l in f.loops:
            t = (l.vert.co.dot(along) - k * L) / L
            l[uv].uv = (u0 + min(max(t, 0.0), 1.0) * (u1 - u0), v0 + (l.vert.co.dot(across) - w0) / span * (v1 - v0))
    return list(faces)
