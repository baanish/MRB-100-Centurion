"""The AWACS mount's detail pass (docs/M4-ART-PLAN.md, group 8): finished meshes for the six parts of awacs_mount.py's
graybox, swapped in as mesh data after the graybox has made the colliders and LOD1 hulls, so names, pivots, parents,
colliders and LOD1 stay the graybox's; and the mount's own maps, baked and painted from Python as the airframe's are.

Detail: the beam's top-hat section with rounded corners and a fillet under the cap, its ends square with a seal ring
round the end sections' opening; the end sections' rounded noses; the upper blade on finer sections with a root fillet
into the beam; a seal ring on the lower blade's top, where it stands flush with the crown raised; the well liner's
ribs, the seal frame round its lip and the sleeve's top ring on the well floor. Every face is on the one skin slot,
which CenturionAuthor binds to the stock ColorableAttachment shader with these maps, so ColorableMount tints the paint
with the livery's colour: textures/awacs_{b,m,n,ao,paint}.png on one ATLAS canvas. _Paint is the livery mask: 1 on
every surface the livery colours (the painted skin, the dielectric array panels, the blades' satin leading edges and
every joint line on them), 0 on the seals and the dark well interior, and no value between. In game the stock shader
showed the near-white _BaseColor wherever the mask fell under 1: the dielectric panels at 0.94, the joint lines at
0.85 and the leading edges at 0 read pale grey under PALA Matte Black (owner, 2026-10-17). Panels and joints read
through the normal map, smoothness and _BaseColor shading instead.
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from m4 import paint, texture

BUDGET_TRIS = 4000  # docs/M4-ART-PLAN.md, group 8
ATLAS = 2048
TEXEL_MIN = 50.0  # px/m the pack must reach on the painted skin
PAINTED, DIELECTRIC, SEAL, INTERIOR = 1, 11, 12, paint.INTERIOR  # the bake's paint classes
ARC = 3  # segments a rounded corner
PAINT_SRGB = (0.38, 0.39, 0.405)  # m4/paint.py's hull grey: the albedo wherever the livery colour is off
# _BaseColor under the paint mask: near white, so the livery colour reads at its own value whether the shader lerps to
# it or multiplies it in; grooves and fasteners dark in both.
PAINT_BASE = (0.86, 0.865, 0.87)
SEAL_SRGB, INTERIOR_SRGB = (0.05, 0.05, 0.055), (0.10, 0.105, 0.11)


# ---------- sections ----------
def corner(cx, cz, r, a0, a1, arc=ARC):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / arc)), cz + r * math.sin(math.radians(a0 + (a1 - a0) * k / arc)))
            for k in range(arc + 1)]


def hat_section(M, d=0.0, arc=ARC):
    """The beam's top-hat outline (x across, z up from the fin's foot), every wall inset d, as a closed loop from the
    bottom centre: rounded foot corners, the fin, a fillet under the cap, rounded cap corners, the top."""
    fh, ch = M["fin_t"] / 2 - d, M["cap_w"] / 2 - d
    z0, z1, z2 = d, M["fin_h"] + d, M["fin_h"] + M["cap_t"] - d
    rf, rl, rc = max(0.05 - d, 0.02), 0.06, max(0.05 - d, 0.02)
    right = ([(0.0, z0)] + corner(fh - rf, z0 + rf, rf, -90, 0, arc) + corner(fh + rl, z1 - rl, rl, 180, 90, arc)
             + corner(ch - rc, z1 + rc, rc, -90, 0, arc) + corner(ch - rc, z2 - rc, rc, 0, 90, arc))
    right = right + [(0.0, z2)]
    return right + [(-x, z) for x, z in reversed(right[1:-1])]


def ring(section, y, sx=1.0, sz=1.0, zc=None):
    zs = [z for _, z in section]
    zc = (max(zs) + min(zs)) / 2 if zc is None else zc
    return [Vector((x * sx, y, zc + (z - zc) * sz)) for x, z in section]


def blade(z, front, back, thick, n=28):
    """awacs_mount.blade_ring on finer sections."""
    chord, tc, pts = back - front, thick / (back - front), []
    for k in range(n):
        t = 0.5 * (1 - math.cos(math.pi * k / (n - 1)))
        pts.append((t, 5 * tc * chord * (0.2969 * math.sqrt(t) - 0.126 * t - 0.3516 * t ** 2 + 0.2843 * t ** 3 - 0.1036 * t ** 4)))
    out = [(yt, front + t * chord) for t, yt in pts] + [(-yt, front + t * chord) for t, yt in reversed(pts[1:-1])]
    return [Vector((x, y, z)) for x, y in out]


# ---------- shells ----------
class Shells:
    """Closed shells into one bmesh, each face tagged with a paint class."""

    def __init__(self):
        self.bm = bmesh.new()
        self.cls = []

    def loft(self, rings, cls, cap_cls=None, side_cls=None):
        """Rings lofted and capped at both ends; side_cls(ring index, vertex index) overrides a side face's class."""
        vs = [[self.bm.verts.new(p) for p in r] for r in rings]
        n = len(rings[0])
        for i, (a, b) in enumerate(zip(vs, vs[1:])):
            for k in range(n):
                self.bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
                self.cls.append(side_cls(i, k) if side_cls else cls)
        for cap in (vs[0][::-1], vs[-1]):
            self.bm.faces.new(cap)
            self.cls.append(cap_cls or cls)

    def annulus(self, outer, inner, cls):
        """A flat ring between two loops of equal length, extruded by the offset between outer[0] and outer[1] rings:
        outer and inner are (near, far) loop pairs."""
        (o0, o1), (i0, i1) = outer, inner
        loops = [[self.bm.verts.new(p) for p in r] for r in (o0, o1, i1, i0)]
        n = len(o0)
        for a, b in zip(loops, loops[1:] + loops[:1]):
            for k in range(n):
                self.bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
                self.cls.append(cls)

    def box(self, lo, hi, cls):
        rings = [[Vector((lo[0], y, lo[2])), Vector((hi[0], y, lo[2])), Vector((hi[0], y, hi[2])), Vector((lo[0], y, hi[2]))]
                 for y in (lo[1], hi[1])]
        self.loft(rings, cls)

    def mesh(self, name, mat):
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        me = bpy.data.meshes.new(name + "_detail")
        self.bm.to_mesh(me)
        self.bm.free()
        me.materials.append(mat)
        me.attributes.new("cls", "INT", "FACE").data.foreach_set("value", np.array(self.cls, np.int32))
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(40))
        return me


def fin_side(M, n):
    """Side faces of a hat loft that lie on the fin's flanks (the dielectric array), by vertex index in the section."""
    sec = hat_section(M)
    flank = {k for k in range(n) if abs(abs(sec[k][0]) - M["fin_t"] / 2) < 1e-6 and abs(abs(sec[(k + 1) % n][0]) - M["fin_t"] / 2) < 1e-6}
    return lambda i, k: DIELECTRIC if k in flank else PAINTED


def build_meshes(M, geo, mats):
    """{part: mesh} in each part's local frame, as awacs_mount.build_mount places the graybox. geo: the graybox's
    numbers (foot0, rise1, rise2, length, spans, slot_x, slot_y)."""
    skin = mats["Centurion_skin"]
    L, d, n_ext = M["fin_len"] / 2, M["ext_inset"], M["ext_len"]
    out = {}

    # beam: square ends, a seal ring round the end sections' opening proud of each end face
    s = Shells()
    sec = hat_section(M)
    ys = [-L, -L + 0.15, L - 0.15, L]
    s.loft([ring(sec, y) for y in ys], PAINTED, side_cls=fin_side(M, len(sec)))
    for sgn in (1, -1):
        y0, y1 = sgn * L, sgn * (L + 0.012)
        outer, inner = hat_section(M, 0.004, 2), hat_section(M, d - 0.006, 2)
        s.annulus((ring(outer, y0 - sgn * 0.003, zc=M["fin_h"] / 2 + M["cap_t"] / 2), ring(outer, y1, zc=M["fin_h"] / 2 + M["cap_t"] / 2)),
                  (ring(inner, y0 - sgn * 0.003, zc=M["fin_h"] / 2 + M["cap_t"] / 2), ring(inner, y1, zc=M["fin_h"] / 2 + M["cap_t"] / 2)), SEAL)
    out["awacs_beam"] = s.mesh("awacs_beam", skin)

    # end sections: origin at the outer end, a rounded nose onto the inset section
    sec = hat_section(M, d)
    zc = (M["fin_h"] + M["cap_t"]) / 2
    nose = ((0.0, 0.30, 0.50), (0.05, 0.53, 0.71), (0.16, 0.73, 0.86), (0.33, 0.90, 0.95), (0.55, 1.0, 1.0))
    for tag, sgn in (("F", -1), ("R", 1)):
        s = Shells()
        rings = [ring(sec, -sgn * y, sx, sz, zc) for y, sx, sz in nose] + [ring(sec, -sgn * y, zc=zc) for y in (1.55, n_ext)]
        s.loft(rings[::-1] if sgn > 0 else rings, PAINTED, side_cls=lambda i, k, f=fin_side(dict(M, fin_t=M["fin_t"] - 2 * d), len(sec)): f(i, k))
        out[f"awacs_beam_ext_{tag}"] = s.mesh(f"awacs_beam_ext_{tag}", skin)

    # upper blade: finer sections, a root fillet into the beam's fin
    spans, length, rise2 = geo["spans"], geo["length"], geo["rise2"]
    thick = M["mast_t"] - 2 * M["stage_inset"]
    (cf, cb), (bf, bb) = spans["upper_crown"], spans["upper_beam"]
    zs = [-length, -rise2, -rise2 / 2, -0.12, -0.05, 0.0, 0.15]

    def at(z):
        t = min(max((z + rise2) / rise2, 0.0), 1.0)
        f, b = cf + (bf - cf) * t, cb + (bb - cb) * t
        flare = max(0.0, (z + 0.12) / 0.12) ** 2 if z <= 0.0 else 1.0  # the fillet: 0 at 12 cm under the beam, 1 at it
        return f - 0.10 * flare, b + 0.10 * flare, thick * (1 + 0.25 * flare)

    s = Shells()
    s.loft([blade(z, *at(z), n=22) for z in zs], PAINTED)
    out["awacs_mast_2"] = s.mesh("awacs_mast_2", skin)

    # lower blade: the graybox's span on finer sections, a seal ring round the upper blade on its top
    lf, lb = spans["lower"]
    s = Shells()
    s.loft([blade(z, lf, lb, M["mast_t"], n=20) for z in (-length, 0.0)], PAINTED)
    s.annulus((blade(-0.004, lf + 0.012, lb - 0.012, M["mast_t"] - 0.024, n=20), blade(0.010, lf + 0.012, lb - 0.012, M["mast_t"] - 0.024, n=20)),
              (blade(-0.004, cf - 0.012, cb + 0.012, thick + 0.016, n=20), blade(0.010, cf - 0.012, cb + 0.012, thick + 0.016, n=20)), SEAL)
    out["awacs_mast_1"] = s.mesh("awacs_mast_1", skin)

    # base: the liner (floor plate, four walls), ribs on the long walls, the lip's seal frame, the sleeve and its top ring
    foot0, sx_, sy_ = geo["foot0"], geo["slot_x"], geo["slot_y"]
    floor, deck, top = foot0 - 0.06, foot0 - 0.01, -0.04
    xi, xo, yi, yo = sx_ - 0.02, sx_ - 0.01, sy_ - 0.02, sy_ - 0.01
    s = Shells()
    for lo, hi in (((-xo, -yo, floor), (xo, yo, deck)), ((xi, -yo, deck), (xo, yo, top)), ((-xo, -yo, deck), (-xi, yo, top)),
                   ((-xi, yi, deck), (xi, yo, top)), ((-xi, -yo, deck), (xi, -yi, top))):
        s.box(lo, hi, INTERIOR)
    for k in range(7):
        y = -yi + 0.25 + k * (2 * yi - 0.5) / 6
        for sgn in (1, -1):
            x0, x1 = sorted((sgn * xi, sgn * (xi - 0.05)))
            s.box((x0, y - 0.02, deck), (x1, y + 0.02, top - 0.01), INTERIOR)
    for lo, hi in (((xi - 0.03, -yi, top - 0.012), (xi, yi, top)), ((-xi, -yi, top - 0.012), (-xi + 0.03, yi, top)),
                   ((-xi + 0.03, yi - 0.03, top - 0.012), (xi - 0.03, yi, top)), ((-xi + 0.03, -yi, top - 0.012), (xi - 0.03, -yi + 0.03, top))):
        s.box(lo, hi, SEAL)
    sf, sb = spans["sleeve"]
    st = M["mast_t"] + 2 * M["stage_inset"]
    s.loft([blade(z, sf, sb, st, n=20) for z in (foot0 - length - 0.05, foot0 - 0.05)], INTERIOR)
    s.annulus((blade(deck - 0.002, sf - 0.05, sb + 0.05, st + 0.10, n=14), blade(deck + 0.04, sf - 0.05, sb + 0.05, st + 0.10, n=14)),
              (blade(deck - 0.002, sf + 0.005, sb - 0.005, st - 0.01, n=14), blade(deck + 0.04, sf + 0.005, sb - 0.005, st - 0.01, n=14)), INTERIOR)
    out["awacs_base"] = s.mesh("awacs_base", skin)
    return out


def swap_detail(objs, M, geo, mats):
    """Swap each part's mesh data for its detailed mesh, keeping the graybox's as _blockout_mesh (the export's
    <part>_shape). Returns triangles per part."""
    tris = {}
    for name, me in build_meshes(M, geo, mats).items():
        o = objs[name]
        o["_blockout_mesh"] = o.data
        o.data = me
        tris[name] = sum(len(p.vertices) - 2 for p in me.polygons)
    return tris


# ---------- checks ----------
def shell_report(o):
    """Open edges and inward shells (signed volume below 0) of one mesh."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    open_edges = sum(1 for e in bm.edges if not e.is_manifold)
    bm.faces.ensure_lookup_table()
    seen, inward = set(), 0
    for f in bm.faces:
        if f.index in seen:
            continue
        shell, stack = [], [f]
        seen.add(f.index)
        while stack:
            g = stack.pop()
            shell.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        vol = sum(vs[0].dot(vs[i].cross(vs[i + 1])) for g in shell for vs in [[v.co for v in g.verts]] for i in range(1, len(vs) - 1))
        inward += vol < 0
    bm.free()
    return open_edges, inward


def checks(objs, tris):
    parts = {}
    for name in tris:
        open_edges, inward = shell_report(objs[name])
        parts[name] = {"tris": tris[name], "open_edges": open_edges, "inward_shells": inward}
    total = sum(tris.values())
    return parts, {"tris": {"value": total, "limit": BUDGET_TRIS, "pass": total <= BUDGET_TRIS},
                   "closed_shells": {"value": sum(p["open_edges"] for p in parts.values()), "pass": all(p["open_edges"] == 0 for p in parts.values())},
                   "outward_normals": {"value": sum(p["inward_shells"] for p in parts.values()), "pass": all(p["inward_shells"] == 0 for p in parts.values())}}


# ---------- UVs and maps ----------
def unwrap(meshes):
    """Smart-projected islands of every part packed onto one canvas. Returns px per metre on the painted skin."""
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in meshes:
        o.data.uv_layers.new(name="UVMap") if "UVMap" not in o.data.uv_layers else None
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(50), island_margin=0.004, scale_to_bounds=False)
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, shape_method="CONCAVE", margin_method="FRACTION", margin=4 / ATLAS)
    bpy.ops.object.mode_set(mode="OBJECT")
    world_a = uv_a = 0.0
    for o in meshes:
        me = o.data
        uv = me.uv_layers["UVMap"].data
        cls = np.zeros(len(me.polygons), np.int32)
        me.attributes["cls"].data.foreach_get("value", cls)
        mw = o.matrix_world
        for p in me.polygons:
            if cls[p.index] not in (PAINTED, DIELECTRIC):
                continue
            world_a += p.area * mw.to_scale().x ** 2
            pts = [uv[li].uv for li in p.loop_indices]
            uv_a += abs(sum(pts[i].x * pts[(i + 1) % len(pts)].y - pts[(i + 1) % len(pts)].x * pts[i].y for i in range(len(pts)))) / 2
    return round(ATLAS * math.sqrt(uv_a / world_a), 1), round(world_a, 2)


def bake_and_paint(meshes, M, folder, density):
    """Bake the mount (posed as the caller left it: deployed, so no end section bakes inside the beam) and paint it in
    each part's own frame. Writes the five maps into folder; returns their names."""
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    names = [o.name for o in meshes]
    group_of = {n: k + 1 for k, n in enumerate(names)}
    proxy = texture.make_proxy(meshes, "Centurion_skin", {}, group_of, ())
    for o in meshes:
        o.hide_render = True
    buf = texture.bake_buffers(proxy, ATLAS)
    bpy.data.objects.remove(proxy)
    for o in meshes:
        o.hide_render = False
    valid = buf["valid"]
    pos, cls, part, ao = buf["pos"][valid], buf["cls"][valid], buf["group"][valid], buf["ao"][valid]
    local = np.zeros_like(pos)
    for name, k in group_of.items():
        sel = part == k
        inv = np.array(bpy.data.objects[name].matrix_world.inverted())
        local[sel] = pos[sel] @ inv[:3, :3].T + inv[:3, 3]
    px = 1.0 / density  # a texel, the anti-aliasing width
    albedo, mask, height, smooth = paint_mount(M, names, local, cls, part, px)
    H = W = ATLAS
    out = {"b": np.zeros((H, W, 3)), "paint": np.zeros((H, W, 3)), "m": np.zeros((H, W, 4)), "ao": np.ones((H, W, 3))}
    h = np.zeros((H, W))
    grime = smoothstep_np(0.95, 0.6, ao)
    out["b"][valid] = albedo * (1 - 0.12 * grime)[:, None]
    out["paint"][valid] = mask[:, None]
    out["m"][valid, 0:3] = 0.03
    out["m"][valid, 3] = smooth
    out["ao"][valid] = np.clip(0.15 + 0.85 * ao, 0, 1)[:, None]
    h[valid] = height
    out["n"] = paint.normal_from_height(h, valid, density)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for key, srgb in (("b", True), ("paint", False), ("m", False), ("ao", False), ("n", False)):
        written.append(texture.save_image(out[key], folder / f"awacs_{key}.png", srgb=srgb).name)
    # The review renders' albedo, the paint at the hull grey under the mask (not exported: the game tints it)
    tint = 1 + (np.array(PAINT_SRGB) / np.array(PAINT_BASE) - 1) * out["paint"]
    texture.save_image(out["b"] * tint, folder / "awacs_preview_b.png", srgb=True)
    return written, int(valid.sum())


def smoothstep_np(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def paint_mount(M, names, local, cls, part, px):
    """Per texel in part-local metres: albedo (sRGB), livery mask, height and smoothness. Panel joints on the beam
    every 2 m and round the dielectric array on each flank, fastener rows on them; the end sections' and blades' joints
    and a livery-coloured satin leading edge on the blade."""
    n = len(cls)
    albedo = np.tile(np.array(PAINT_BASE), (n, 1))
    mask = np.ones(n)
    height = np.zeros(n)
    smooth = np.full(n, 0.42)
    x, y, z = local[:, 0], local[:, 1], local[:, 2]

    def groove(dist, sel, width=0.014, depth=-0.003):
        cov = np.clip(0.5 + (width / 2 - dist) / px, 0, 1) * sel
        albedo[:] = albedo * (1 - 0.7 * cov)[:, None]
        height[:] = height + depth * cov
        return cov

    def fasteners(dist, along, sel, offset=0.03, pitch=0.12):
        k = np.round(along / pitch) * pitch
        r = np.hypot(np.abs(dist) - offset, along - k)
        cov = np.clip(0.5 + (0.007 - r) / px, 0, 1) * sel
        height[:] = height + 0.001 * cov
        albedo[:] = albedo * (1 - 0.2 * cov)[:, None]

    def on(name):
        return part == names.index(name) + 1

    L = M["fin_len"] / 2
    zc = M["fin_h"] / 2
    dielectric = cls == DIELECTRIC
    albedo[dielectric] = (0.80, 0.81, 0.80)
    smooth[dielectric] = 0.36
    beam = on("awacs_beam")
    skin = (cls == PAINTED) | dielectric
    # beam: full-girth joints every 2 m, the array panel's outline, a lap joint along each cap edge
    for yj in (-4.0, -2.0, 0.0, 2.0, 4.0):
        groove(np.abs(y - yj), beam & skin)
        fasteners(y - yj, z + np.abs(x), beam & (cls == PAINTED))
    panel = np.maximum(np.abs(y) - (L - 0.35), np.abs(z - zc) - (zc - 0.18))
    groove(np.abs(panel), beam & dielectric)
    fasteners(panel, y, beam & dielectric & (np.abs(panel) < 0.06), offset=0.035, pitch=0.15)
    groove(np.abs(z - (M["fin_h"] + 0.04)), beam & (cls == PAINTED) & (np.abs(x) > M["fin_t"] / 2 + 0.07))
    # end sections: a joint where the nose meets the straight run, the array's outline on each flank
    for tag in ("F", "R"):
        e = on(f"awacs_beam_ext_{tag}")
        ay = np.abs(y)
        groove(np.abs(ay - 0.55), e & skin)
        panel = np.maximum(np.abs(ay - 1.75) - 1.05, np.abs(z - zc) - (zc - 0.2))
        groove(np.abs(panel), e & dielectric)
    # blades: a joint every 0.6 m up the span, the satin leading edge
    for name in ("awacs_mast_1", "awacs_mast_2"):
        b = on(name) & (cls == PAINTED)
        for zj in np.arange(-3.0, 0.0, 0.6):
            groove(np.abs(z - zj), b)
        le = b & (y < np.interp(z, [-3.0, 0.2], [-M["blade_ahead"] + 0.2, -M["blade_ahead"] + 1.0]))
        smooth[le] = 0.54
    seal, interior = cls == SEAL, cls == INTERIOR
    albedo[seal], mask[seal], smooth[seal] = SEAL_SRGB, 0.0, 0.25
    albedo[interior], mask[interior], smooth[interior] = INTERIOR_SRGB, 0.0, 0.3
    return np.clip(albedo, 0, 1), np.clip(mask, 0, 1), height, np.clip(smooth, 0.05, 0.95)
