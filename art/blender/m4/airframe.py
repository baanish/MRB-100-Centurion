"""The damage structure the groups build inside their parts: what a broken-off part or a burned-through skin shows,
as the stock aircraft carry it (extra submeshes inside the ordinary part meshes, skin kept in slot 0). Hidden while
the aircraft is whole; nothing here is ever seen from outside an intact part.

A part with structure is thin-walled: its closed hull is kept as the part's envelope (Part.envelope, which the bury
pass tests containment against, as it tested the closed hull), then each joint's flat cap is opened onto a lining that
runs WALL inside the skin round the part's air space, and the cap becomes a break face of that thickness: the skin's
torn edge (break_face). Inside the lining stand the frames, longerons and systems runs (sweep, tube), torn skin tongues
and broken member ends just past each break (teeth, the members' path past the joint), and the part's real bulkheads.

Everything here is on SLOT, the airframe trim: an original 512 sheet of eight horizontal strips (STRIPS, the last a fuel
tank's sealed wall), each tiling
along U, so a member's length runs along U (UV_PER_M) and its section across its strip's V. The builders write those
UVs into the part's "airframe_uv" layer; detail_centurion's trim pass moves them onto UVMap and writes the sheet
(write_sheet). The structure is exempt from the closed-shell rule (it is never tested for containment and never
baked): members are open where they sit against the lining or a wall, which would hide the faces anyway."""

import math

import bmesh
import numpy as np
from mathutils import Vector, geometry

SLOT = "Centurion_airframe"
WALL = 0.02  # the skin's thickness at a break face, and the lining's depth inside the skin
UV_PER_M = 0.5  # the sheet is 2 m long along U
SHEET_PX, STRIP_PX = 512, 64
STRIPS = {"web": 0, "flange": 1, "lining": 2, "torn": 3, "cable": 4, "pipe": 5, "plate": 6, "wet": 7}
PAD = 3 / STRIP_PX  # V stays this far inside a strip, so no filter reaches the next one


def strip_v(role, t):
    """V at fraction t (0..1) across a strip."""
    lo = STRIPS[role] * STRIP_PX / SHEET_PX
    h = STRIP_PX / SHEET_PX
    return lo + h * (PAD + (1 - 2 * PAD) * min(max(t, 0.0), 1.0))


def uv_layer(part):
    """The part's airframe UV layer, made after UVMap so UVMap stays the mesh's first (active) map."""
    uv = part.bm.loops.layers.uv
    if uv.get("UVMap") is None:
        uv.new("UVMap")
    return uv.get("airframe_uv") or uv.new("airframe_uv")


def face(part, verts, uvs, role_out=None):
    """A face on SLOT from vertices (duplicates dropped) with a UV per vertex; None if fewer than three remain."""
    keep, kuv = [], []
    for v, t in zip(verts, uvs):
        if v not in keep:
            keep.append(v)
            kuv.append(t)
    if len(keep) < 3:
        return None
    f = part.bm.faces.get(keep) or part.bm.faces.new(keep)
    layer = uv_layer(part)
    for loop in f.loops:
        loop[layer].uv = kuv[keep.index(loop.vert)]
    part.tag([f], SLOT)
    return f


def orient(f, outward):
    """Flip f so its normal points along outward."""
    f.normal_update()
    if f.normal.dot(outward) < 0:
        f.normal_flip()
    return f


def path_length(pts):
    out = [0.0]
    for a, b in zip(pts, pts[1:]):
        out.append(out[-1] + (b - a).length)
    return out


def sweep(part, path, inward, along, section, roles, closed=False, caps=None, u0=0.0):
    """A member swept along path: at each point i the section's (a, b) points sit at path[i] + along[i] * a +
    inward[i] * b. Section edge j (from point j to j + 1, the last back to the first) takes roles[j] (a STRIPS name)
    or None, which leaves that side open. caps: (role at the first end, role at the last) for an open path, or None
    for open ends. Faces face away from the section's centre. Returns the faces."""
    bm = part.bm
    rings = [[bm.verts.new(p + al * a + n * b) for a, b in section] for p, n, al in zip(path, inward, along)]
    u = [u0 + d * UV_PER_M for d in path_length(path + ([path[0]] if closed else []))]
    m = len(section)
    ca = sum(a for a, _ in section) / m
    cb = sum(b for _, b in section) / m
    faces = []
    count = len(rings) if closed else len(rings) - 1
    for i in range(count):
        i1 = (i + 1) % len(rings)
        for j in range(m):
            role = roles[j % len(roles)]
            if role is None:
                continue
            j1 = (j + 1) % m
            (a0, b0), (a1, b1) = section[j], section[j1]
            mid = path[i].lerp(path[i1], 0.5)
            n_mid = (inward[i] + inward[i1]).normalized()
            al_mid = (along[i] + along[i1]).normalized()
            out = al_mid * ((a0 + a1) / 2 - ca) + n_mid * ((b0 + b1) / 2 - cb)
            f = face(part, (rings[i][j], rings[i1][j], rings[i1][j1], rings[i][j1]),
                     ((u[i], strip_v(role, 0)), (u[i + 1], strip_v(role, 0)), (u[i + 1], strip_v(role, 1)),
                      (u[i], strip_v(role, 1))))
            if f is not None:
                faces.append(orient(f, out if out.length > 1e-9 else mid))
    if caps and not closed:
        for end, role, sign in ((0, caps[0], -1), (len(rings) - 1, caps[1], 1)):
            if role is None:
                continue
            k = min(end + 1, len(path) - 1) if end == 0 else end - 1
            axis = (path[end] - path[k]).normalized()
            ring = rings[end]
            span = max(abs(a) for a, _ in section) or 1.0
            depth = max(abs(b) for _, b in section) or 1.0
            uvs = [(u[end] + a * UV_PER_M, strip_v(role, 0.5 + 0.5 * b / depth)) for a, b in section]
            f = face(part, ring, uvs)
            if f is not None:
                faces.append(orient(f, axis))
    return faces


def tube(part, pts, radius, role, seg=6, caps=("plate", "plate")):
    """A closed run along pts (a pipe or a cable bundle), its circumference across the strip."""
    ref = None
    inward, along = [], []
    for i in range(len(pts)):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        ref = ref or t.orthogonal()
        e1 = (ref - t * ref.dot(t)).normalized()
        inward.append(e1)
        along.append(t.cross(e1))
        ref = e1
    section = [(radius * math.cos(2 * math.pi * k / seg), radius * math.sin(2 * math.pi * k / seg)) for k in range(seg)]
    bm = part.bm
    rings = [[bm.verts.new(p + al * a + n * b) for a, b in section] for p, n, al in zip(pts, inward, along)]
    u = [d * UV_PER_M for d in path_length(pts)]
    faces = []
    for i in range(len(pts) - 1):
        for k in range(seg):
            k1 = (k + 1) % seg
            f = face(part, (rings[i][k], rings[i + 1][k], rings[i + 1][k1], rings[i][k1]),
                     ((u[i], strip_v(role, k / seg)), (u[i + 1], strip_v(role, k / seg)),
                      (u[i + 1], strip_v(role, (k + 1) / seg)), (u[i], strip_v(role, (k + 1) / seg))))
            mid = (pts[i] + pts[i + 1]) / 2
            faces.append(orient(f, rings[i][k].co.lerp(rings[i + 1][k1].co, 0.5) - mid))
    for end, role_c, axis in ((0, caps[0], pts[0] - pts[1]), (-1, caps[1], pts[-1] - pts[-2])):
        if role_c:
            ring = rings[end]
            f = face(part, ring, [(u[end] + 0.5 * radius * math.cos(2 * math.pi * k / seg) * UV_PER_M,
                                   strip_v(role_c, 0.5 + 0.5 * math.sin(2 * math.pi * k / seg))) for k in range(seg)])
            faces.append(orient(f, axis))
    return faces


def loft(part, rings, role, facing):
    """The lining: rings of vertices (BMVerts, one list per station, equal counts, a vertex may repeat between
    neighbouring rings where the section does not change) lofted into faces facing the air space: facing(r, j) is
    the direction into it from the face between rings r and r + 1 and points j and j + 1. U runs round the section, V
    across the strip per row of faces."""
    faces = []
    for r in range(len(rings) - 1):
        A, B = rings[r], rings[r + 1]
        ua = [d * UV_PER_M for d in path_length([v.co for v in A])]
        ub = [d * UV_PER_M for d in path_length([v.co for v in B])]
        for j in range(len(A)):
            j1 = (j + 1) % len(A)
            if j1 == 0:
                ua1, ub1 = ua[-1] + (A[0].co - A[-1].co).length * UV_PER_M, ub[-1] + (B[0].co - B[-1].co).length * UV_PER_M
            else:
                ua1, ub1 = ua[j1], ub[j1]
            f = face(part, (A[j], A[j1], B[j1], B[j]),
                     ((ua[j], strip_v(role, 0)), (ua1, strip_v(role, 0)), (ub1, strip_v(role, 1)), (ub[j], strip_v(role, 1))))
            if f is not None:
                faces.append(orient(f, facing(r, j)))
    return faces


def fill(part, outer, inner, normal, role, centre):
    """A planar break face between a closed outer loop (the skin's and the cavities' edge at a joint) and a closed
    inner loop (the lining's section there), facing along normal. inner may be None (a bulkhead: the loop filled).
    UVs: U round the body (angle about centre), V from the inner loop (0) to the outer (1), so the torn strip's bright
    edge runs along the skin."""
    loops = [outer] + ([inner] if inner else [])
    pts = [[v.co for v in loop] for loop in loops]
    flat = [v for loop in loops for v in loop]
    is_outer = [True] * len(outer) + [False] * (len(inner) if inner else 0)
    faces = []
    span = max((v.co - centre).length for v in outer) or 1.0
    for tri in geometry.tessellate_polygon(pts):
        vs = [flat[i] for i in tri]
        c = sum((v.co for v in vs), Vector()) / 3
        if inner and inside_loop(c, [v.co for v in inner], normal):
            continue
        ang = [math.atan2((v.co - centre).x, (v.co - centre).z) for v in vs]
        if max(ang) - min(ang) > math.pi:
            ang = [a + 2 * math.pi if a < 0 else a for a in ang]
        if inner:
            vv = [1.0 if is_outer[i] else 0.0 for i in tri]
        else:
            vv = [(v.co - centre).length / span for v in vs]
        f = face(part, vs, [(a * span * UV_PER_M, strip_v(role, t)) for a, t in zip(ang, vv)])
        if f is not None:
            faces.append(orient(f, normal))
    return faces


def inside_loop(p, loop, normal):
    """Whether p lies inside the planar loop (seen along normal)."""
    n = normal.normalized()
    e1 = n.orthogonal().normalized()
    e2 = n.cross(e1)
    q = [((v - p).dot(e1), (v - p).dot(e2)) for v in loop]
    inside = False
    for (x0, y0), (x1, y1) in zip(q, q[1:] + q[:1]):
        if (y0 > 0) != (y1 > 0) and x0 + (x1 - x0) * (0 - y0) / (y1 - y0) > 0:
            inside = not inside
    return inside


def teeth(part, edge, inward, out_dir, lengths, thick=(0.008, 0.022), bend=0.03):
    """Torn skin tongues along a break: edge points on the lining at the joint plane, each tongue from edge[i] to
    edge[i + 1] reaching lengths[i] (0 skips) past the joint along out_dir, into the neighbour's hidden inside,
    bent bend inward at its tip. Closed slabs on the torn strip, bright at the tip."""
    bm = part.bm
    faces = []
    for i, L in enumerate(lengths):
        if L <= 0 or i + 1 >= len(edge):
            continue
        a, b = edge[i], edge[i + 1]
        n = (inward[i] + inward[i + 1]).normalized()
        tip = a.lerp(b, 0.35 + 0.3 * ((i * 7) % 5) / 4) + out_dir * L + n * bend
        top = [bm.verts.new(p + n * thick[0]) for p in (a, b, tip)]
        bot = [bm.verts.new(p + n * thick[1]) for p in (a, b, tip)]
        w = (b - a).length * UV_PER_M
        uv = ((0.0, strip_v("torn", 0)), (w, strip_v("torn", 0)), (w / 2, strip_v("torn", 1)))
        faces.append(orient(face(part, top, uv), -n))
        faces.append(orient(face(part, bot, uv), n))
        for k in range(3):
            k1 = (k + 1) % 3
            f = face(part, (top[k], top[k1], bot[k1], bot[k]),
                     ((0.0, uv[k][1]), (w, uv[k1][1]), (w, uv[k1][1]), (0.0, uv[k][1])))
            if f is not None:
                c = (top[k].co + top[k1].co) / 2
                ctr = (top[0].co + top[1].co + top[2].co) / 3
                faces.append(orient(f, c - ctr))
    return faces


def joint_cap(part, y, slot_names):
    """The faces of the flat cap at a joint plane (world y), on any slot but the skin's, and its outer boundary loop in
    order. The cap may be notched by cavities; the loop then runs round their walls."""
    bm = part.bm
    skin = part.slots.index(slot_names[0]) if slot_names[0] in part.slots else -1
    cap = [f for f in bm.faces if f.material_index != skin and all(abs(v.co.y - y) < 1e-6 for v in f.verts)]
    count = {}
    for f in cap:
        for e in f.edges:
            count[e] = count.get(e, 0) + 1
    link = {}
    for e, n in count.items():
        if n == 1:
            a, b = e.verts
            link.setdefault(a, []).append(b)
            link.setdefault(b, []).append(a)
    start = next(iter(link))
    loop, prev = [start], None
    while True:
        nxt = next(v for v in link[loop[-1]] if v is not prev)
        if nxt is start:
            break
        prev = loop[-1]
        loop.append(nxt)
    if len(loop) != len(link):
        raise SystemExit(f"{part.name}: the cap at y {y:.3f} has {len(link)} boundary vertices, one loop of {len(loop)}")
    return cap, loop


def open_joint(part, y, slot_names, inner, outward, role="torn"):
    """Replace the flat cap at joint plane y with a break face round the lining's section inner (BMVerts in the plane),
    facing outward (away from the part). Returns the break face's faces."""
    cap, loop = joint_cap(part, y, slot_names)
    centre = sum((v.co for v in loop), Vector()) / len(loop)
    bmesh.ops.delete(part.bm, geom=cap, context="FACES_ONLY")
    return fill(part, loop, inner, outward, role, centre)


# ---------- the trim sheet ----------
def write_sheet(folder, save_image, normal_from_height):
    """The airframe trim's albedo (sRGB), metal-smoothness (RGB metal, A smoothness) and normal (OpenGL) PNGs, 512
    square, row 0 at the bottom. Returns their paths."""
    W, H = SHEET_PX, SHEET_PX
    u = (np.arange(W) + 0.5) / W / UV_PER_M  # metres along U
    alb = np.zeros((H, W, 3))
    metal, smooth, height = np.zeros((H, W)), np.zeros((H, W)), np.zeros((H, W))
    rng = np.random.default_rng(7)
    noise = rng.random((H, W)) - 0.5

    def rivets(mm, vv, rows, pitch, r=0.004, k=0.18):
        """Rivet heads along U at the strip fractions rows (v in metres across a nominal 0.12 m strip)."""
        out = np.zeros_like(mm)
        for row in rows:
            d = np.hypot((mm % pitch) - pitch / 2, (vv - row) * 0.12)
            out = np.maximum(out, np.clip(1 - d / r, 0, 1))
        return out

    for role, s in STRIPS.items():
        rows = slice(s * STRIP_PX, (s + 1) * STRIP_PX)
        v = ((np.arange(STRIP_PX) + 0.5) / STRIP_PX)[:, None] * np.ones((1, W))
        mm = np.ones((STRIP_PX, 1)) * u[None, :]
        a = np.zeros((STRIP_PX, W, 3))
        me, sm, hh = np.full((STRIP_PX, W), 0.1), np.full((STRIP_PX, W), 0.35), np.zeros((STRIP_PX, W))
        if role == "web":
            a[:] = (0.34, 0.37, 0.31)
            hole = np.hypot(((mm % 0.5) - 0.25) / 0.11, (v - 0.5) / 0.26)
            rim = np.clip(1 - np.abs(hole - 1.08) / 0.12, 0, 1)
            a = np.where((hole < 1)[..., None], (0.05, 0.05, 0.05), a)
            a += 0.08 * rim[..., None]
            hh += -0.004 * (hole < 1) + 0.0015 * rim
            r = rivets(mm, v, (0.1, 0.9), 0.05)
            a *= (1 - 0.15 * r)[..., None]
            hh += 0.0008 * r
        elif role == "flange":
            a[:] = (0.42, 0.45, 0.38)
            r = rivets(mm, v, (0.5,), 0.04)
            a *= (1 - 0.18 * r)[..., None]
            hh += 0.0008 * r
            a *= (0.85 + 0.15 * np.clip(np.minimum(v, 1 - v) / 0.15, 0, 1))[..., None]
        elif role == "lining":
            a[:] = (0.36, 0.39, 0.25)
            sd = np.abs((mm % 0.25) - 0.125)
            band = np.clip(1 - sd / 0.025, 0, 1)
            a *= (1 - 0.35 * band)[..., None]
            hh += 0.002 * band
            r = rivets(mm % 0.25 + 0.0, v, (0.25, 0.75), 0.25, 0.006)
            a *= (1 - 0.1 * r)[..., None]
        elif role == "torn":
            edge = np.clip((v - 0.55 + 0.12 * noise[rows]) / 0.3, 0, 1)
            a[:] = (0.07, 0.065, 0.06)
            a = a * (1 - edge[..., None]) + np.array((0.62, 0.62, 0.6)) * edge[..., None]
            me, sm = 0.1 + 0.7 * edge, 0.25 + 0.25 * edge
            hh += 0.002 * noise[rows]
        elif role == "cable":
            a[:] = (0.11, 0.11, 0.115)
            strand = np.abs(np.sin(v * math.pi * 10))
            a *= (0.8 + 0.2 * strand)[..., None]
            hh += 0.0015 * strand
            tie = np.abs((mm % 0.3) - 0.15) < 0.008
            a = np.where(tie[..., None], (0.62, 0.62, 0.6), a)
            hh += 0.002 * tie
            tag = np.abs((mm % 1.0) - 0.5) < 0.03
            a = np.where(tag[..., None], (0.55, 0.14, 0.1), a)
        elif role == "pipe":
            a[:] = (0.52, 0.53, 0.54)
            me, sm = np.full_like(me, 0.75), np.full_like(sm, 0.55)
            for c, at in (((0.13, 0.27, 0.62), 0.3), ((0.75, 0.6, 0.12), 0.38)):
                tape = np.abs((mm % 1.0) - at) < 0.03
                a = np.where(tape[..., None], c, a)
                me = np.where(tape, 0.0, me)
            a *= (0.85 + 0.15 * np.cos((v - 0.3) * 2 * math.pi))[..., None]
        elif role == "plate":
            a[:] = (0.31, 0.33, 0.31)
            r = rivets(mm, v, (0.2, 0.8), 0.1)
            a *= (1 - 0.15 * r)[..., None]
            hh += 0.0008 * r
        elif role == "wet":  # a fuel tank's sealed wall: dark sealant, glossy, with fillet beads along its seams
            a[:] = (0.13, 0.16, 0.15)
            me, sm = np.full_like(me, 0.05), np.full_like(sm, 0.62)
            bead = np.clip(1 - np.abs((mm % 0.6) - 0.3) / 0.015, 0, 1)
            a = a * (1 + 0.6 * bead[..., None])
            hh += 0.0015 * bead
            r = rivets(mm, v, (0.15, 0.85), 0.06)
            a *= (1 - 0.2 * r)[..., None]
        a *= (1 + 0.06 * noise[rows])[..., None]
        alb[rows], metal[rows], smooth[rows], height[rows] = a, me, sm, hh
    folder.mkdir(parents=True, exist_ok=True)
    ms = np.zeros((H, W, 4))
    ms[..., 0:3] = metal[..., None]
    ms[..., 3] = smooth
    density = SHEET_PX * UV_PER_M
    normal = normal_from_height(height, np.ones((H, W), bool), density)
    return {"albedo": save_image(np.clip(alb, 0, 1), folder / "airframe_b.png", srgb=True),
            "metal_smooth": save_image(ms, folder / "airframe_m.png"),
            "normal": save_image(normal, folder / "airframe_n.png")}
