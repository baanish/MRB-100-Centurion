"""The spoiler wells (stage 1). build(side) cuts the spoiler's hole in wing_outer_<side>, builds its well, panel, frame, fittings and two actuators,
proves the 3 mm seam over 0 to 65 degrees, and returns the sweep report. The panel replaces spoiler_<side>_visible's
mesh (the authoring keeps finding it by name); the well and fittings join wing_outer_<side>'s own mesh in a pass_*
slot that s4_uv maps onto production slots; the actuator pieces are objects spoiler_<side>_cylinder_<n> (on the wing)
and spoiler_<side>_rod_<n> (on the hinge), which the authoring aims at each other (CenturionAuthor change)."""
import json
import math
from collections import defaultdict

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

import trim

FULL = 65.0
SEAM = 0.003
THICK = 0.010
NOSE = THICK / 2
DEPTH_CLEAR = 0.025
DEPTH_MAX = 0.16
ACT_X = (13.6, 15.9)
BARREL_R, ROD_R = 0.026, 0.011


def _mat(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def build(side):
    SGN = 1 if side == "L" else -1
    skin_mat = _mat("Centurion_skin")
    rail, lining, painted, chrome, steel = (_mat(n) for n in ("pass_trim_rail", "pass_lining", "pass_paint", "pass_chrome", "pass_steel"))
    dark = _mat("pass_trim_cut")
    (du0, du1, dv0, dv1), _, _ = trim.TRIMS["dark"]
    DARK_UV = ((du0 + du1) / 2, (dv0 + dv1) / 2)
    vis_world0 = bpy.data.objects[f"spoiler_{side}_visible"].matrix_world.copy()  # it and its collider stay put
    wing = bpy.data.objects[f"wing_outer_{side}"]
    stage = bpy.data.objects[f"wing_tele1_{side}"]
    vis = bpy.data.objects[f"spoiler_{side}_visible"]
    hinge = vis.parent
    while hinge.type != "EMPTY":
        hinge = hinge.parent
    H0 = hinge.matrix_world.copy()
    axis = H0.col[0].xyz.normalized()
    if axis.x < 0:
        axis = -axis
    pivot = H0.translation.copy()
    pts = [vis.matrix_world @ v.co for v in vis.data.vertices]
    cen = sum(pts, Vector()) / len(pts)
    chord = (cen - pivot)
    chord = (chord - axis * chord.dot(axis)).normalized()
    normal = axis.cross(chord)
    if normal.z < 0:
        normal = -normal


    def local(p):
        d = p - pivot
        return d.dot(axis), d.dot(chord), d.dot(normal)


    def world(s, u, w):
        return pivot + axis * s + chord * u + normal * w


    def bvh_of(o):
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        t = BVHTree.FromBMesh(bm)
        bm.free()
        return t


    # ---- the spoiler's planform from its own rings (constant-x stations), front and trailing edges as polylines ----
    rings = defaultdict(list)
    for p in pts:
        rings[round(p.x, 2)].append(p)
    front_line, back_line = [], []
    for x in sorted(rings):
        q = [local(p) for p in rings[x]]
        f = min(q, key=lambda v: v[1])
        b = max(q, key=lambda v: v[1])
        front_line.append((f[0], f[1] + 0.010))  # the old feathered lip stood 10 mm ahead of the top's front point
        back_line.append((b[0], b[1]))
    front_line.sort()
    back_line.sort()
    s0 = max(front_line[0][0], back_line[0][0]) + 0.01  # ends square to the hinge, inside the old raked tips
    s1 = min(front_line[-1][0], back_line[-1][0]) - 0.01
    SG = 1 if s0 + s1 > 0 else -1  # +1 where s grows outboard (the left wing), -1 on the right (its axis also points +x)
    S_IN, S_OUT = (s0, s1) if SG > 0 else (s1, s0)


    def along(line, s):
        for (sa, ua), (sb, ub) in zip(line, line[1:]):
            if sa <= s <= sb:
                return ua + (ub - ua) * (s - sa) / max(sb - sa, 1e-9)
        return line[0][1] if s < line[0][0] else line[-1][1]


    UF = along(front_line, (s0 + s1) / 2)  # the hinge line is straight: the front edge at mid span
    uf_at = lambda s: UF + (along(front_line, s) - along(front_line, (s0 + s1) / 2)) * 0.0  # noqa: E731 (straight)
    ub_at = lambda s: along(back_line, s)  # noqa: E731

    # the wing's top skin and its UVs, sampled before the hole is cut
    wbm = bmesh.new()
    wbm.from_mesh(wing.data)
    wbm.transform(wing.matrix_world)
    wbm.faces.ensure_lookup_table()
    wuv = wbm.loops.layers.uv["UVMap"]
    wing_t = BVHTree.FromBMesh(wbm)
    stage_t = bvh_of(stage)


    def uv_on(bm_, layer, face, p):
        """The UV at point p on a face: from the fan triangle that holds p (the nearest one if none does)."""
        from mathutils.geometry import closest_point_on_tri
        best, best_d = None, 1e9
        for k in range(1, len(face.loops) - 1):
            a, b, c = face.loops[0], face.loops[k], face.loops[k + 1]
            q = closest_point_on_tri(p, a.vert.co, b.vert.co, c.vert.co)
            d = (q - p).length
            if d < best_d:
                best_d = d
                best = barycentric_transform(q, a.vert.co, b.vert.co, c.vert.co, a[layer].uv.to_3d(), b[layer].uv.to_3d(), c[layer].uv.to_3d())
        return best.to_2d()


    def skin_at(s, u):
        """The wing's top skin over (s, u): (point, its UV)."""
        h = wing_t.ray_cast(world(s, u, 1.0), -normal, 2.0)
        if h[0] is None:
            return world(s, u, 0.0), Vector((0, 0))
        return h[0], uv_on(wbm, wuv, wbm.faces[h[2]], h[0])


    # the old spoiler's top keeps the texels baked for a visible panel (the skin under it baked in its shadow)
    vbm = bmesh.new()
    vbm.from_mesh(vis.data)
    vbm.transform(vis.matrix_world)
    vbm.faces.ensure_lookup_table()
    vuv = vbm.loops.layers.uv["UVMap"]
    vis_t = BVHTree.FromBMesh(vbm)


    def panel_uv(s, u):
        h = vis_t.ray_cast(world(s, u, 1.0), -normal, 2.0)
        if h[0] is not None and vbm.faces[h[2]].normal.dot(normal) > 0.5:
            return uv_on(vbm, vuv, vbm.faces[h[2]], h[0])
        return skin_at(s, u)[1]


    def floor_w(s, u):
        top = local(skin_at(s, u)[0])[2]
        h = stage_t.ray_cast(world(s, u, top - 0.002), -normal, 1.0)
        below = local(h[0])[2] if h[0] is not None else top - 1.0
        return max(top - DEPTH_MAX, below + DEPTH_CLEAR)


    coll = bpy.data.collections.new(f"pass_spoiler_{side}")
    bpy.context.scene.collection.children.link(coll)


    def mesh_obj(name, bm, mats, parent=None):
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for m in mats:
            me.materials.append(m)
        o = bpy.data.objects.new(name, me)
        coll.objects.link(o)
        if parent is not None:
            o.parent = parent
            o.matrix_parent_inverse = parent.matrix_world.inverted()
        return o


    # ---- the panel ----
    NS, NU = 30, 10
    ss = [s0 + (s1 - s0) * i / NS for i in range(NS + 1)]
    AX_U = UF + NOSE  # the hinge axis: NOSE aft of the front edge, at mid thickness
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    top, bot, uvs = [], [], []
    for s in ss:
        ub = ub_at(s)
        row_t, row_b, row_uv = [], [], []
        us = [AX_U + (ub - AX_U) * k / NU for k in range(NU + 1)]
        for u in us:
            p, uv = skin_at(s, u)[0], panel_uv(s, u)
            row_t.append(bm.verts.new(p))
            row_b.append(bm.verts.new(p - normal * THICK))
            row_uv.append(uv)
        top.append(row_t)
        bot.append(row_b)
        uvs.append(row_uv)
    # the nose: a half circle round the axis line, from the top's first point down to the bottom's
    nose = []
    for i, s in enumerate(ss):
        tw = local(top[i][0].co)[2]
        c = world(s, AX_U, tw - NOSE)
        arc = []
        for k in range(1, 8):
            a = math.pi / 2 + math.pi * k / 8
            arc.append(bm.verts.new(c + chord * (NOSE * math.cos(a)) + normal * (NOSE * math.sin(a))))
        nose.append(arc)
    tfaces, others = [], []
    for i in range(NS):
        for k in range(NU):
            f = bm.faces.new((top[i][k], top[i][k + 1], top[i + 1][k + 1], top[i + 1][k]))
            for l, uv in zip(f.loops, (uvs[i][k], uvs[i][k + 1], uvs[i + 1][k + 1], uvs[i + 1][k])):
                l[uvl].uv = uv
            tfaces.append(f)
            others.append(bm.faces.new((bot[i][k], bot[i + 1][k], bot[i + 1][k + 1], bot[i][k + 1])))
        chain_a = [top[i][0]] + nose[i] + [bot[i][0]]
        chain_b = [top[i + 1][0]] + nose[i + 1] + [bot[i + 1][0]]
        for k in range(len(chain_a) - 1):
            others.append(bm.faces.new((chain_a[k], chain_b[k], chain_b[k + 1], chain_a[k + 1])))
        others.append(bm.faces.new((top[i][NU], bot[i][NU], bot[i + 1][NU], top[i + 1][NU])))  # trailing edge
    for i, sign in ((0, 1), (NS, -1)):  # square ends
        ring = [top[i][k] for k in range(NU, -1, -1)] + nose[i] + [bot[i][k] for k in range(NU + 1)]
        f = bm.faces.new(ring if sign > 0 else ring[::-1])
        others.append(f)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in others:
        f.material_index = 1
    # a dark sheet facing up 1.5 mm over the underside: through the top skin's damage holes the painted underside read as
    # brown tiles (the owner, 2026-11-23: "make thin bays dark"); from below the underside hides it
    lift = [[bm.verts.new(v.co + normal * 0.0015) for v in row] for row in bot]
    for i in range(NS):
        for k in range(NU):
            f = bm.faces.new((lift[i][k], lift[i][k + 1], lift[i + 1][k + 1], lift[i + 1][k]))
            f.normal_update()
            if f.normal.dot(normal) < 0:
                f.normal_flip()
            f.material_index = 2
            for l in f.loops:
                l[uvl].uv = DARK_UV
    top_w = [local(r[0].co)[2] for r in top]  # read before the bmesh is freed
    panel = mesh_obj(f"pass_panel_{side}", bm, [skin_mat, painted, dark])  # underside and edges painted metal, not the dark lining (read black when raised)
    vis.hide_render = True

    # ---- the hole: bisect the wing skin along the outline offset SEAM, then drop the skin inside it ----
    back = [(s0 - SEAM, ub_at(s0) + SEAM)] + [(s, ub_at(s) + SEAM) for s in ss[1:-1]] + [(s1 + SEAM, ub_at(s1) + SEAM)]
    poly = [(s0 - SEAM, UF - SEAM), (s1 + SEAM, UF - SEAM)] + back[::-1]


    def inside(s, u):
        n, c = len(poly), False
        for i in range(n):
            (sa, ua), (sb, ub) = poly[i], poly[(i + 1) % n]
            if (ua > u) != (ub > u) and s < sa + (u - ua) * (sb - sa) / (ub - ua):
                c = not c
        return c


    cut = bmesh.new()
    cut.from_mesh(wing.data)
    cut.transform(wing.matrix_world)
    segs = list(zip(poly, poly[1:] + poly[:1]))
    for (sa, ua), (sb, ub) in segs:
        pa, pb = world(sa, ua, 0), world(sb, ub, 0)
        no = (pb - pa).cross(normal).normalized()
        lo_s, hi_s = min(sa, sb) - 0.05, max(sa, sb) + 0.05
        near = []
        for f in cut.faces:  # any face reaching the segment's span band near the top (big faces have far centres)
            q = [local(v.co) for v in f.verts]
            if min(v[0] for v in q) <= hi_s and max(v[0] for v in q) >= lo_s and max(v[2] for v in q) > -0.3:
                near.append(f)
        if near:
            es = list(dict.fromkeys(e for f in near for e in f.edges))
            vs = list(dict.fromkeys(v for f in near for v in f.verts))
            bmesh.ops.bisect_plane(cut, geom=vs + es + near, plane_co=pa, plane_no=no)
    # anything else of the wing inside the well's volume (cove faces, the old slot) is cut on the same outline and goes
    for (sa, ua), (sb, ub) in segs:
        pa, pb = world(sa, ua, 0), world(sb, ub, 0)
        no = (pb - pa).cross(normal).normalized()
        near = [f for f in cut.faces if min(sa, sb) - 0.6 <= local(f.calc_center_median())[0] <= max(sa, sb) + 0.6
                and local(f.calc_center_median())[2] > -0.3 and f.normal.dot(normal) <= 0.3]
        if near:
            es = list(dict.fromkeys(e for f in near for e in f.edges))
            vs = list(dict.fromkeys(v for f in near for v in f.verts))
            bmesh.ops.bisect_plane(cut, geom=vs + es + near, plane_co=pa, plane_no=no)
    doomed = []
    for f in cut.faces:
        s, u, w = local(f.calc_center_median())
        if not inside(s, u):
            continue
        if (f.normal.dot(normal) > 0.3 and w > -0.25) or w > floor_w(s, u) - 0.005:
            doomed.append(f)
    bmesh.ops.delete(cut, geom=doomed, context="FACES")
    cut.transform(wing.matrix_world.inverted())
    cut.to_mesh(wing.data)
    cut.free()
    print("SPOILER3 hole: removed", len(doomed), "faces; panel s", round(s0, 3), round(s1, 3), flush=True)

    # ---- the well: walls from the hole edge to the floor, sharing their edges with it ----
    rim = []  # hole outline, closed, densified
    for (sa, ua), (sb, ub) in segs:
        n = max(1, int(math.hypot(sb - sa, ub - ua) / 0.12))
        for k in range(n):
            rim.append((sa + (sb - sa) * k / n, ua + (ub - ua) * k / n))
    bm = bmesh.new()
    rt = [bm.verts.new(world(s, u, local(skin_at(s, u)[0])[2] + 0.0005)) for s, u in rim]
    rf = [bm.verts.new(world(s, u, floor_w(s, u))) for s, u in rim]
    n = len(rim)
    walls = [bm.faces.new((rt[k], rt[(k + 1) % n], rf[(k + 1) % n], rf[k])) for k in range(n)]


    def floor_probe(bm_):
        """Rays straight down through the hole at 10 mm steps: the (s, u) points where nothing of the well stops them, which
        show as daylight or the lit stage through the well (round 3: a bright sliver in the outboard corner)."""
        t = BVHTree.FromBMesh(bm_)
        miss = []
        for i in range(int((s1 - s0) / 0.01) + 1):
            s = s0 + 0.01 * i
            for j in range(1, int((ub_at(s) - UF) / 0.01)):
                u = UF + 0.01 * j
                o = world(s, u, local(skin_at(s, u)[0])[2] - 0.001)
                if t.ray_cast(o, -normal, 0.4)[0] is None:
                    miss.append((round(s, 2), round(u, 2)))
        return miss


    # floor: on the wall foot's own vertices, so floor and walls share every edge. A 3D ngon triangulation (round 3) let
    # triangles cross the concave outline; the floor is tessellated in the hole's own (s, u) plane instead
    from mathutils.geometry import tessellate_polygon  # noqa: E402
    probe = bm.copy()
    probe.verts.ensure_lookup_table()
    fl = probe.faces.new([probe.verts[n + k] for k in range(n)])
    bmesh.ops.triangulate(probe, faces=[fl], quad_method="BEAUTY", ngon_method="BEAUTY")
    miss_3d = floor_probe(probe)
    probe.free()
    floor_faces = [bm.faces.new([rf[i] for i in tri]) for tri in tessellate_polygon([[Vector((s, u, 0.0)) for s, u in rim]])]
    miss_2d = floor_probe(bm)
    print("SPOILER3 floor probe: rays through the well", len(miss_3d), "with the 3D triangulation, e.g.", miss_3d[:6],
          "; with the planar one", len(miss_2d), miss_2d[:6], flush=True)
    # every face looks into the well: the floor up the hole's normal, each wall toward the well's mid-depth inside it. Aiming
    # all of them at a point 30 mm over the floor flipped floor triangles at random on the tilted floor, and the culled
    # back faces showed the stage through the well (1,043 of 1,096 lining hits were back faces at the outboard end).
    # Walls face the outline's inside, from the rim polygon's own winding in (s, u): aiming them at a point in the well
    # misjudged the inboard trailing-edge corner (57 back faces there after the floor was fixed).
    for f in floor_faces:
        if f.normal.dot(normal) < 0:
            f.normal_flip()
    area2 = sum(rim[k][0] * rim[(k + 1) % n][1] - rim[(k + 1) % n][0] * rim[k][1] for k in range(n))
    for k, f in enumerate(walls):
        (sa, ua), (sb, ub) = rim[k], rim[(k + 1) % n]
        ins, inu = -(ub - ua), sb - sa  # left of the segment, the inside when the outline winds counter-clockwise
        if area2 < 0:
            ins, inu = -ins, -inu
        if f.normal.dot(axis * ins + chord * inu) < 0:
            f.normal_flip()
    for f in floor_faces:  # the floor on the stock sheet's corrugated web, not plain lining (round 3: flat and uniformly dark)
        f.material_index = 1
    trim.apply(bm, floor_faces, axis, "body_web")
    well = mesh_obj(f"pass_well_{side}", bm, [painted, rail])  # walls painted metal, as real wells are; on the dark lining the raised panel's well read black

    # ---- floor fittings, ribs and lines (rail strip) ----
    bm = bmesh.new()


    def box(bm, centre, ax, ay, az, sx, sy, sz):
        vs = [bm.verts.new(centre + ax * (i * sx / 2) + ay * (j * sy / 2) + az * (k * sz / 2))
              for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)]
        fs = [bm.faces.new([vs[i] for i in f]) for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))]
        return fs


    def tube(bm, a, b, r, n=10):
        d = (b - a).normalized()
        x = d.orthogonal().normalized()
        y = d.cross(x)
        ring = lambda c: [bm.verts.new(c + (x * math.cos(2 * math.pi * k / n) + y * math.sin(2 * math.pi * k / n)) * r) for k in range(n)]  # noqa: E731
        ra, rb = ring(a), ring(b)
        fs = [bm.faces.new((ra[k], ra[(k + 1) % n], rb[(k + 1) % n], rb[k])) for k in range(n)]
        fs += [bm.faces.new(list(reversed(ra))), bm.faces.new(rb)]
        return fs


    ribs = []
    for sr in [s0 + 0.25 + 0.5 * k for k in range(int((s1 - s0 - 0.5) / 0.5) + 1)]:
        a = world(sr, UF + 0.02, floor_w(sr, UF + 0.02) + 0.005)
        b = world(sr, ub_at(sr) - 0.02, floor_w(sr, ub_at(sr) - 0.02) + 0.005)
        d = (b - a).normalized()
        up_ = d.cross(axis).normalized()
        up_ = up_ if up_.dot(normal) > 0 else -up_
        ribs += box(bm, (a + b) / 2, d, axis, up_, (b - a).length, 0.02, 0.01)
    acts = []
    fit_faces = []
    for ax_ in ACT_X:
        s = local(Vector((SGN * ax_, pivot.y, pivot.z)))[0]
        fw = floor_w(s, UF + 0.08)
        anchor = world(s, UF + 0.07, fw + 0.035)
        fit_faces += box(bm, world(s, UF + 0.07, fw + 0.015), chord, axis, normal, 0.07, 0.10, 0.03)
        fit_faces += box(bm, world(s, UF + 0.07, fw + 0.002), chord, axis, normal, 0.13, 0.17, 0.004)  # doubler plate under it
        for ds in (-0.03, 0.03):
            fit_faces += box(bm, anchor + axis * ds - normal * 0.008, chord, axis, normal, 0.05, 0.008, 0.05)  # lugs
        eye_u = AX_U + min(0.36, 0.33 * (ub_at(s) - AX_U))
        eye = world(s, eye_u, local(skin_at(s, eye_u)[0])[2] - 0.05)
        acts.append((s, anchor, eye))
    bm.normal_update()
    trim.apply(bm, ribs, chord, "rail")
    trim.apply(bm, fit_faces, axis, "rail")
    fixed_fit = mesh_obj(f"pass_well_fittings_{side}", bm, [rail])
    bm = bmesh.new()
    for s, anchor, eye in acts:
        tube(bm, anchor - axis * 0.045, anchor + axis * 0.045, 0.009, 10)  # anchor pin
        for ds in (-0.047, 0.047):
            tube(bm, anchor + axis * ds - axis * 0.004, anchor + axis * ds + axis * 0.004, 0.014, 10)
    for dz in (0.012, 0.03):  # hydraulic lines along the floor to the inboard fitting
        a = world(S_IN + 0.1 * SG, UF + 0.03, floor_w(S_IN + 0.1 * SG, UF + 0.03) + dz)
        b = acts[0][1] + normal * (dz - 0.02) - axis * 0.06
        tube(bm, a, b, 0.006, 8)
    pins_fixed = mesh_obj(f"pass_pins_fixed_{side}", bm, [steel])

    # ---- the panel's frame (rails and ribs under its underside, on the hinge), clevis and pin ----
    hinge_axis_pt = world(0.0, AX_U, top_w[NS // 2] - NOSE)
    new_rest = Matrix.Translation(hinge_axis_pt - pivot) @ H0
    hinge.matrix_world = new_rest
    bpy.context.view_layer.update()
    panel.parent = hinge
    panel.matrix_parent_inverse = hinge.matrix_world.inverted()


    def under(s, u, depth):
        """A point depth below the panel's underside at (s, u)."""
        return world(s, u, local(skin_at(s, u)[0])[2] - THICK - depth)


    def depth_at(s):
        """The well's least depth across the chord at span s."""
        return min(local(skin_at(s, u)[0])[2] - floor_w(s, u) for u in (UF + 0.02, (UF + ub_at(s)) / 2, ub_at(s) - 0.02))


    # the frame stands 25 mm under the panel's 10 mm skin: it stops where the well is shallower than 45 mm (outboard, where
    # the retracted stage comes within 54 mm of the skin), and the panel runs on as a plain plate
    def outboard_until(depth, s_from):
        """From s_from, step outboard while the well is at least `depth` deep."""
        s = s_from
        while SG * (S_OUT - s) > 0.05 and depth_at(s + 0.05 * SG) >= depth:
            s += 0.05 * SG
        return s


    # full-depth members (16 mm) where the well is 45 mm deep, then 8 mm members on to where it is 30 mm deep, so the frame
    # tapers out instead of stopping (round 3: a flat black patch at the panel's outboard end)
    s_lim = outboard_until(0.045, S_IN + 0.05 * SG)
    s_end = outboard_until(0.030, s_lim)
    print("SPOILER3 frame to s", round(s_lim, 2), "tapering to", round(s_end, 2), "of", round(S_OUT, 2), flush=True)


    def member_h(s):
        return 0.016 if SG * (s_lim - s) >= 0 else 0.008


    def strip(bm, pts, ups, w):
        """A closed member swept through pts (its top edge on them), one section per point sharing the joints (round 3's
        separate boxes stepped at every joint), w wide and member_h deep."""
        secs = []
        for k, (p, up_) in enumerate(zip(pts, ups)):
            d = (pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]).normalized()
            side = d.cross(up_).normalized() * (w / 2)
            h = member_h(local(p)[0])
            secs.append([bm.verts.new(p + side), bm.verts.new(p - side), bm.verts.new(p - side - up_ * h), bm.verts.new(p + side - up_ * h)])
        fs = []
        for a, b in zip(secs, secs[1:]):
            fs += [bm.faces.new((a[i], a[(i + 1) % 4], b[(i + 1) % 4], b[i])) for i in range(4)]
        fs += [bm.faces.new(secs[0][::-1]), bm.faces.new(secs[-1])]
        bmesh.ops.recalc_face_normals(bm, faces=fs)
        return fs


    bm = bmesh.new()
    rails, cross = [], []
    for f in (0.08, 0.36, 0.64, 0.92):
        st = [S_IN + 0.05 * SG + (s_end - S_IN - 0.05 * SG) * k / 12 for k in range(13)]
        pts = [under(s, AX_U + (ub_at(s) - AX_U) * f, 0.0015) for s in st]
        ups = []
        for k in range(len(pts)):
            d = (pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]).normalized()
            up_ = chord.cross(d).normalized()
            ups.append(up_ if up_.dot(normal) > 0 else -up_)
        rails += strip(bm, pts, ups, 0.022)
    for sr in [S_IN + SG * (0.3 + 0.5 * k) for k in range(int((abs(s_end - S_IN) - 0.3) / 0.5) + 1)]:
        # swept along the panel's underside like the rails (a straight box under the curved underside rose 1.8 mm into it)
        us = [AX_U + 0.03 + (ub_at(sr) - 0.03 - AX_U - 0.03) * k / 8 for k in range(9)]
        pts = [under(sr, uu, 0.0015) for uu in us]
        ups = []
        for k in range(len(pts)):
            d = (pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]).normalized()
            up_ = d.cross(axis).normalized()
            ups.append(up_ if up_.dot(normal) > 0 else -up_)
        cross += strip(bm, pts, ups, 0.012)
    # (round 1 put hinge knuckles round the axis here; they stood through the panel and above its top, 282 frame-panel
    # crossings and a 3.16 mm crown. The pass gates the frame against the panel at zero.)
    knuckles = []
    clev = []
    for s, anchor, eye in acts:
        for ds in (-0.03, 0.03):
            clev += box(bm, eye + axis * ds + normal * 0.0115, chord, axis, normal, 0.09, 0.008, 0.05)  # top 3.5 mm under the underside at the eye: 90 mm long, it rose into the curved panel flush (28 crossings)
    bm.normal_update()
    trim.apply(bm, rails, axis, "rail")
    trim.apply(bm, cross, chord, "rail")
    trim.apply(bm, clev, chord, "rail")
    trim.apply(bm, knuckles, axis, "flange")
    frame = mesh_obj(f"pass_frame_{side}", bm, [rail], parent=hinge)
    bm = bmesh.new()
    for s, anchor, eye in acts:
        tube(bm, eye - axis * 0.045, eye + axis * 0.045, 0.008, 10)
        for ds in (-0.047, 0.047):
            tube(bm, eye + axis * ds - axis * 0.004, eye + axis * ds + axis * 0.004, 0.013, 10)
    pins_moving = mesh_obj(f"pass_pins_moving_{side}", bm, [steel], parent=hinge)

    # ---- actuators: cylinder and rod with their origins at their eyes ----
    cyls, rods = [], []
    for s, anchor, eye in acts:
        bm = bmesh.new()
        tube(bm, Vector((0, 0.035, 0)), Vector((0, 0.26, 0)), BARREL_R, 14)
        tube(bm, Vector((0, 0.24, 0)), Vector((0, 0.27, 0)), BARREL_R + 0.004, 14)  # gland
        tube(bm, Vector((-0.02, 0, 0)), Vector((0.02, 0, 0)), 0.02, 12)  # eye boss across the pin
        tube(bm, Vector((0, 0.0, 0)), Vector((0, 0.04, 0)), 0.012, 10)
        c = mesh_obj(f"spoiler_{side}_cylinder_{len(cyls) + 1}", bm, [painted])
        bm = bmesh.new()
        tube(bm, Vector((0, 0.03, 0)), Vector((0, 0.26, 0)), ROD_R, 12)
        tube(bm, Vector((-0.018, 0, 0)), Vector((0.018, 0, 0)), 0.017, 12)  # rod-end eye
        tube(bm, Vector((0, 0.0, 0)), Vector((0, 0.035, 0)), 0.01, 10)
        r = mesh_obj(f"spoiler_{side}_rod_{len(rods) + 1}", bm, [chrome])
        r["eye_local"] = list(hinge.matrix_world.inverted() @ eye)
        cyls.append((c, anchor))
        rods.append(r)
    H_AXIS = H0.col[0].xyz.normalized()


    def frame_at(at, toward):
        y = toward - at
        y = (y - axis * y.dot(axis)).normalized()
        z = axis.cross(y)
        m = Matrix((axis, y, z)).transposed().to_4x4()
        m.translation = at
        return m


    rest_pts = [panel.matrix_world @ v.co for v in panel.data.vertices]
    hinge.matrix_world = Matrix.Translation(hinge_axis_pt) @ Matrix.Rotation(math.radians(10), 4, H_AXIS) @ Matrix.Translation(-hinge_axis_pt) @ new_rest
    bpy.context.view_layer.update()
    moved = [panel.matrix_world @ v.co for v in panel.data.vertices]
    up = 1 if sum((b - a).dot(normal) for a, b in zip(rest_pts, moved)) > 0 else -1  # +deg lifts the trailing edge


    def pose(deg):
        hinge.matrix_world = Matrix.Translation(hinge_axis_pt) @ Matrix.Rotation(math.radians(up * deg), 4, H_AXIS) @ \
            Matrix.Translation(-hinge_axis_pt) @ new_rest
        bpy.context.view_layer.update()
        for (c, anchor), r in zip(cyls, rods):
            eye = hinge.matrix_world @ Vector(r["eye_local"])
            c.matrix_world = frame_at(anchor, eye)
            r.matrix_world = frame_at(eye, anchor)
        bpy.context.view_layer.update()


    # ---- the seam sweep ----
    def tree(o):
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        t = BVHTree.FromBMesh(bm)
        bm.free()
        return t


    fixed = {"wing": tree(wing), "well": tree(well), "stage": stage_t, "fittings": tree(fixed_fit)}
    fixed_objs = {"wing": wing, "well": well, "stage": stage, "fittings": fixed_fit}


    def where(o, idx):
        """Where face idx of o lies (its centre in hinge-frame s, u, w) and its material."""
        p = o.data.polygons[idx]
        c = o.matrix_world @ p.center
        m = o.data.materials[p.material_index].name if o.data.materials else "-"
        return [round(v, 3) for v in local(c)] + [m]
    sweep, worst = [], 0
    for deg in range(0, int(FULL) + 1):
        pose(deg)
        moving = {"panel": tree(panel), "frame": tree(frame)}
        hits = {f"{m}x{k}": len(tm.overlap(tf)) for m, tm in moving.items() for k, tf in fixed.items()}
        hits = {k: v for k, v in hits.items() if v}
        if deg in (0, 5, 30) and hits:
            for m, tm in moving.items():
                for k, tf in fixed.items():
                    pairs = tm.overlap(tf)
                    if pairs and k != "stage":
                        print("SPOILER3 clash", deg, m, k, [where(fixed_objs[k], j) for _, j in pairs[:4]], flush=True)
        sweep.append((deg, hits))
        worst = max(worst, sum(hits.values()))
    pose(0)
    frame_through_panel = len(tree(frame).overlap(tree(panel)))
    # what matters to the eye: how far any frame vertex stands above the panel's underside and its top (negative: below)
    fv = [local(frame.matrix_world @ v.co) for v in frame.data.vertices]
    rel = [w - local(skin_at(s, u)[0])[2] for s, u, w in fv]
    frame_crown = {"above_top_mm": round(1000 * max(rel), 2), "above_underside_mm": round(1000 * (max(rel) + THICK), 2)}
    print("SPOILER3 frame crown", frame_crown, "overlap pairs", frame_through_panel, flush=True)
    gaps = []
    pt = tree(panel)
    for s, u in rim:
        p = world(s, u, local(skin_at(s, u)[0])[2])
        loc, _, _, d = pt.find_nearest(p, 0.05)
        if loc is not None:
            gaps.append(d)
    report = {"panel_span_s": [s0, s1], "seam_m": SEAM, "frame_through_panel_pairs": frame_through_panel, "frame_crown": frame_crown, "sweep_intersections": [(d, h) for d, h in sweep if h],
              "max_pairs": worst, "seam_measured_mm": {"min": round(1000 * min(gaps), 2), "median": round(1000 * sorted(gaps)[len(gaps) // 2], 2),
                                                       "max": round(1000 * max(gaps), 2)} if gaps else None}
    print("SPOILER3 report", json.dumps(report), flush=True)


    for c, _ in cyls:  # the cylinders ride the wing, the rods the hinge, where they stand at rest
        mw = c.matrix_world.copy()
        c.parent = wing
        c.matrix_world = mw
    for r in rods:
        mw = r.matrix_world.copy()
        r.parent = hinge
        r.matrix_world = mw
    # the panel's mesh becomes spoiler_<side>_visible's own, in its frame (the authoring finds the surface by that name)
    # the panel is a new mesh: it takes the paint class and group of the spoiler skin it replaces, or the bake paints
    # it nothing (it rendered black)
    old_me = vis.data
    sk_old = {i for i, m in enumerate(old_me.materials) if m and m.name == "Centurion_skin"}
    for attr in ("cls", "paint_group"):
        if attr not in old_me.attributes:
            continue
        vals = [0] * len(old_me.polygons)
        old_me.attributes[attr].data.foreach_get("value", vals)
        common = defaultdict(int)
        for val, p in zip(vals, old_me.polygons):
            if p.material_index in sk_old:
                common[val] += 1
        top = max(common, key=common.get) if common else 0
        a = panel.data.attributes.get(attr) or panel.data.attributes.new(attr, "INT", "FACE")
        a.data.foreach_set("value", [top] * len(panel.data.polygons))
    vis.matrix_world = vis_world0  # the hinge moved onto the bull nose; the visible mesh's frame and its collider did not
    bpy.context.view_layer.update()
    panel.data.transform(vis.matrix_world.inverted() @ panel.matrix_world)
    vis.data = panel.data
    # merged faces keep stale custom normals, which shaded the panel black; the panel is flat: plain flat normals
    if vis.data.has_custom_normals:
        vis.data.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(vis.data.loops))
    vis.data.shade_flat()
    vis.hide_render = False
    bpy.data.objects.remove(panel)
    return report
