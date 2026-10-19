"""The flight deck's UV layout over its three PBR atlases (cockpit/flightdeck.py builds the parts):

- Centurion_cockpit_panel: the main panel, its displays' bezels and keys, the screen's bezel.
- Centurion_cockpit_console: the side consoles, the pedestal and the overhead with their switches and knobs.
- Centurion_cockpit_shell: the lining, window and hatch trims, floor, aft wall and racks, the screen's shroud.

Only faces the pilot can see get texels: a face no sample of the pilot's head positions sees (its back, the
undersides, whatever the furniture hides) shares one dead texel in its atlas's reserved right-hand stripe. A face on the
commander's side whose mirror image on the pilot's side exists reuses that image's UVs, so each atlas holds one side's
detail at twice the density; text lives on the label quads (flightdeck_labels.py), so nothing reads backwards.
Each slot's islands are scaled to the density targets of their paint classes (TARGET_PX_PER_M) and packed onto the
atlas at the largest scale that fits; the achieved densities are measured per class."""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import flightdeck_layout as fl

ATLAS = 2048
SHELL_SLOT, PANEL_SLOT, CONSOLE_SLOT = "Centurion_cockpit_shell", "Centurion_cockpit_panel", "Centurion_cockpit_console"
PBR_SLOTS = (PANEL_SLOT, CONSOLE_SLOT, SHELL_SLOT)
# Stock shared materials on our own faces, referenced by name in authoring: the walls and frames on the tiling
# aircraft_structure, the screen's frame, shroud and glareshield on Matte_black, the grips on a plain rubber patch of
# hotas. The kit's faces (flightdeck_kit.KIT_SLOT) and the warning lenses keep their own.
STRUCTURE_SLOT, MATTE_SLOT, HOTAS_SLOT = "aircraft_structure", "Matte_black", "hotas"
STRUCTURE_PX_PER_M = 600  # the stock cockpits tile aircraft_structure's 1024 x 512 at 518 to 689 px/m (stock_reference.py)
STRUCTURE_PX = (1024, 512)
HOTAS_RUBBER = (0.125, 0.4531, 0.375, 0.5156)  # u0, v0, u1, v1: a plain dark rubber patch of hotas_b
DEAD_STRIPE = 12  # px at each atlas's right edge kept clear of islands for the invisible faces' shared texel
PACK_MARGIN = 4  # px between islands


def targets(fd):
    """px per metre by slot and paint class: the art spec's floors (panel 1,536, consoles 768, shell 256 to 512)."""
    return {PANEL_SLOT: {fd.PANEL: 1536, fd.BEZEL: 1536, fd.KNOB: 1536, fd.METAL: 1536},
            CONSOLE_SLOT: {fd.CONSOLE: 768, fd.OVERHEAD: 768, fd.KNOB: 768, fd.METAL: 768, fd.HANDLE: 768, fd.GRIP: 768,
                           fd.RACK: 768},
            SHELL_SLOT: {fd.LINING: 320, fd.FLOOR: 288, fd.RACK: 384, fd.FRAME: 512, fd.HANDLE: 512, fd.PANEL: 256,
                         fd.KNOB: 384, fd.METAL: 384, fd.GRIP: 384, fd.HATCH: 384, fd.STRUCT: 448}}


# ---------------- slots ----------------
def slot_for(fd, cls, c):
    """The atlas a face of class cls centred at world point c belongs to."""
    s = c.y + fd.Y0
    phi, r = fd.cyl_coords(c)
    on_panel = (abs(phi) <= fd.PANEL_PHI + 0.5 and fd.PANEL_R - 0.035 <= r <= fd.PANEL_R + fd.PANEL_DEPTH + 0.004
                and (c.z >= fd.KNEE_Z - 0.012 or abs(phi) >= fd.band_phi() - 0.1) and c.z <= fl.EYE_Z)
    if cls in (fd.LINING, fd.STRUCT):
        return STRUCTURE_SLOT
    if cls == fd.GRIP:
        return HOTAS_SLOT
    if cls in (fd.PANEL, fd.BEZEL) or (on_panel and cls in (fd.KNOB, fd.METAL)):
        return PANEL_SLOT if on_panel else MATTE_SLOT
    if cls in (fd.CONSOLE, fd.OVERHEAD):
        return CONSOLE_SLOT
    if cls in (fd.FLOOR, fd.FRAME, fd.HATCH):
        return SHELL_SLOT
    console = (abs(c.x) >= fd.CONSOLE_X - 0.012 and fd.CONSOLE_TOP - 0.02 <= c.z <= fd.CONSOLE_TOP + 0.16
               and fd.CONSOLE_S[0] - 0.02 <= s <= fd.CONSOLE_S[1] + 0.02)
    pedestal = (abs(c.x) <= fd.PEDESTAL_X + 0.03 and fd.PEDESTAL_TOP - 0.012 <= c.z <= fd.PEDESTAL_TOP + 0.26
                and s <= fd.PEDESTAL_AFT + 0.02)
    overhead = (abs(c.x) <= fd.OVERHEAD_X + 0.02 and fd.OVERHEAD_S[0] - 0.02 <= s <= fd.OVERHEAD_S[1] + 0.02 and c.z > 5.1)
    return CONSOLE_SLOT if (console or pedestal or overhead) else SHELL_SLOT


def assign_slots(part, fd, slot_of_part=None):
    """Retag part's atlas faces into the three PBR slots (slot_of_part: one slot for the whole part)."""
    old = part.slots.index(fd.ATLAS_SLOT) if fd.ATLAS_SLOT in part.slots else None
    groups = {}
    for f in part.bm.faces:
        if f.material_index != old:
            continue
        slot = slot_of_part or slot_for(fd, f[part.cls], f.calc_center_median())
        groups.setdefault(slot, []).append(f)
    for slot, fs in groups.items():
        for f in fs:
            cls = f[part.cls]
            part.tag([f], slot, cls)


# ---------------- visibility ----------------
def head_positions(fd, side=1):
    """A seat's eye (side 1 the pilot's) and where the head moves round it in game: leaning, raised, forward."""
    e = fd.eye(side)
    offs = [(0, 0, 0), (0.12, 0, 0), (-0.12, 0, 0), (0, 0, 0.10), (0, 0, -0.08), (0, -0.12, 0), (0, 0.10, 0.05),
            (-0.10, -0.08, 0.06)]
    return [e + Vector((side * x, y, z)) for x, y, z in offs]


def visible_faces(objs, eyes, occluders=()):
    """{object name: bool per polygon} for objs: a face is visible when a ray from some eye reaches its centre or a
    point toward one of its corners before anything in objs or occluders."""
    verts, polys, owner = [], [], []
    for o in list(objs) + list(occluders):
        mw = o.matrix_world
        base = len(verts)
        verts += [mw @ v.co for v in o.data.vertices]
        for p in o.data.polygons:
            polys.append([base + i for i in p.vertices])
            owner.append((o.name, p.index))
    tree = BVHTree.FromPolygons(verts, polys)
    index = {key: i for i, key in enumerate(owner)}
    out = {}
    for o in objs:
        mw = o.matrix_world
        nm = mw.to_3x3().inverted().transposed()
        vis = np.zeros(len(o.data.polygons), bool)
        for p in o.data.polygons:
            me_i = index[(o.name, p.index)]
            c = mw @ p.center
            n = (nm @ p.normal).normalized()
            pts = [c] + [c + ((mw @ o.data.vertices[i].co) - c) * 0.8 for i in p.vertices]
            pts = [q + n * 1e-4 for q in pts]
            vis[p.index] = any(_sees(tree, e, q, n, me_i) for e in eyes for q in pts)
        out[o.name] = vis
    return out


CULL_SLOTS = PBR_SLOTS + ("Centurion_cockpit_kit", STRUCTURE_SLOT, MATTE_SLOT, HOTAS_SLOT)


def tile_uvs(objs, fd):
    """UVs for the faces on stock shared materials: aircraft_structure unrolled round the hull (girth across, station
    along; a frame's sides girth and depth) at STRUCTURE_PX_PER_M, repeating; each hotas face squeezed into
    HOTAS_RUBBER."""
    su, sv = STRUCTURE_PX_PER_M / STRUCTURE_PX[0], STRUCTURE_PX_PER_M / STRUCTURE_PX[1]
    hu0, hv0, hu1, hv1 = HOTAS_RUBBER
    for o in objs:
        me = o.data
        names = [m.name for m in me.materials]
        mw = o.matrix_world
        uv = me.uv_layers["UVMap"].data
        for p in me.polygons:
            slot = names[p.material_index]
            if slot not in (STRUCTURE_SLOT, HOTAS_SLOT):
                continue
            pts = [mw @ me.vertices[me.loops[li].vertex_index].co for li in p.loop_indices]
            n = (mw.to_3x3() @ p.normal).normalized()
            if slot == STRUCTURE_SLOT:
                for li, q in zip(p.loop_indices, pts):
                    girth = math.atan2(q.x, q.z - 3.45) * 1.9
                    v = math.hypot(q.x, q.z - 3.45) if abs(n.y) > 0.7 else q.y + fd.Y0
                    uv[li].uv = (girth * su, v * sv)
            else:
                k = max(range(3), key=lambda i: abs(n[i]))
                a, b = [(1, 2), (0, 2), (0, 1)][k]
                us, vs = [q[a] for q in pts], [q[b] for q in pts]
                span = max(max(us) - min(us), max(vs) - min(vs), 1e-6)
                for li, q in zip(p.loop_indices, pts):
                    uv[li].uv = (hu0 + (hu1 - hu0) * (q[a] - min(us)) / span, hv0 + (hv1 - hv0) * (q[b] - min(vs)) / span)


STRUCTURE_TINT = (0.12, 0.12, 0.13)  # vertex colour on aircraft_structure faces: its shader multiplies the near-white base
# colour by it (the Darkreach's structure carries 0.22, the Alkyon's 0.14); this matches the panels' grey


def structure_tint(objs):
    """A corner colour on every face: STRUCTURE_TINT on the aircraft_structure faces, white on the rest (whose materials
    ignore it). The export carries it to the FBX."""
    for o in objs:
        me = o.data
        names = [m.name for m in me.materials]
        col = me.color_attributes.new("Col", "FLOAT_COLOR", "CORNER")
        values = np.ones((len(me.loops), 4), np.float32)
        for p in me.polygons:
            if names[p.material_index] == STRUCTURE_SLOT:
                values[p.loop_start:p.loop_start + p.loop_total, :3] = STRUCTURE_TINT
        col.data.foreach_set("color", values.ravel())
        me.color_attributes.active_color = col
        me.color_attributes.render_color_index = me.color_attributes.find("Col")


def wide_head_positions(fd):
    """Every head position the pilot's camera reaches, generously: leaning 0.2 m either way, 0.15 m fore and aft,
    0.1 m down and 0.15 m up from the eye."""
    e = fd.eye(1)
    return [e + Vector((x, y, z)) for x in (-0.2, 0.0, 0.2) for y in (-0.15, 0.0, 0.15) for z in (-0.1, 0.0, 0.15)]


def cull_unseen(objs, fd, occluders=()):
    """Delete the faces of the small and stand-off parts (knobs, levers, handles, grips, trims, bezels, boxes, frames)
    that no wide head position sees: their backs, undersides and the sides against the surfaces they stand on. The
    lining, floor, panel and console shells stay whole, as they keep the sun out where the hidden exterior would.
    Returns the triangles removed per object."""
    keep_cls = {fd.LINING, fd.FLOOR, fd.PANEL, fd.CONSOLE, fd.OVERHEAD, fd.HATCH}
    vis = visible_faces(objs, wide_head_positions(fd), occluders)
    removed = {}
    for o in objs:
        me = o.data
        cls = np.zeros(len(me.polygons), np.int32)
        me.attributes["cls"].data.foreach_get("value", cls)
        names = [m.name for m in me.materials]
        doomed = {p.index for p in me.polygons if not vis[o.name][p.index] and int(cls[p.index]) not in keep_cls
                  and names[p.material_index] in CULL_SLOTS}
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        faces = [bm.faces[i] for i in sorted(doomed)]
        removed[o.name] = sum(len(f.verts) - 2 for f in faces)
        bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
        bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context="VERTS")
        bm.to_mesh(me)
        bm.free()
    return removed


def _sees(tree, e, q, n, face):
    d = q - e
    dist = d.length
    if dist < 1e-6 or d.dot(n) >= 0:
        return False
    hit = tree.ray_cast(e, d / dist, dist + 0.002)
    return hit[0] is None or hit[2] == face or hit[3] >= dist - 0.0015


# ---------------- mirroring ----------------
def mirror_twins(o, slots_ok):
    """{face on the commander's side (-X): its mirror image on the pilot's side}, faces in the same slot and class
    with the same corners mirrored."""
    me = o.data
    mw = o.matrix_world
    cls = np.zeros(len(me.polygons), np.int32)
    if "cls" in me.attributes:
        me.attributes["cls"].data.foreach_get("value", cls)
    names = [m.name for m in me.materials]

    def key(c):
        return (round(c.x * 500), round(c.y * 500), round(c.z * 500))

    plus = {}
    for p in me.polygons:
        c = mw @ p.center
        if c.x > 0.003 and names[p.material_index] in slots_ok:
            plus.setdefault(key(c), []).append(p.index)
    out = {}
    for p in me.polygons:
        c = mw @ p.center
        if c.x >= -0.003 or names[p.material_index] not in slots_ok:
            continue
        m = Vector((-c.x, c.y, c.z))
        for j in plus.get(key(m), []):
            q = me.polygons[j]
            if (q.material_index == p.material_index and cls[j] == cls[p.index] and len(q.vertices) == len(p.vertices)
                    and ((mw @ q.center) - m).length < 0.003):
                out[p.index] = j
                break
    return out


def copy_mirrored(o, twins):
    """Each twin's UVs onto its mirror image, corner by corner (matched by mirrored position)."""
    me = o.data
    uv = me.uv_layers["UVMap"].data
    for dst, src in twins.items():
        pd, ps = me.polygons[dst], me.polygons[src]
        src_loops = [(Vector((-me.vertices[me.loops[li].vertex_index].co.x, *me.vertices[me.loops[li].vertex_index].co[1:])), li)
                     for li in ps.loop_indices]
        for li in pd.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            best = min(src_loops, key=lambda s: (s[0] - co).length)
            uv[li].uv = uv[best[1]].uv


# ---------------- unwrap and pack ----------------
def _select(objs, chosen):
    """Select exactly the polygons in chosen ({name: bool array}) in object mode, with their edges and vertices."""
    for o in objs:
        me = o.data
        sel = chosen[o.name]
        me.polygons.foreach_set("select", sel)
        vsel = np.zeros(len(me.vertices), bool)
        esel = np.zeros(len(me.edges), bool)
        for p in me.polygons:
            if sel[p.index]:
                vsel[list(p.vertices)] = True
        ev = np.zeros(len(me.edges) * 2, np.int32)
        me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(-1, 2)
        esel = vsel[ev[:, 0]] & vsel[ev[:, 1]]
        me.vertices.foreach_set("select", vsel)
        me.edges.foreach_set("select", esel)


def _islands(bm, uv, faces):
    parent = {f.index: f.index for f in faces}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for f in faces:
        for e in f.edges:
            for g in e.link_faces:
                if g is f or g.index not in parent:
                    continue
                ok = True
                for v in e.verts:
                    a = next(l for l in f.loops if l.vert is v)[uv].uv
                    b = next(l for l in g.loops if l.vert is v)[uv].uv
                    if (a - b).length > 1e-6:
                        ok = False
                if ok:
                    parent[find(f.index)] = find(g.index)
    groups = {}
    for f in faces:
        groups.setdefault(find(f.index), []).append(f)
    return list(groups.values())


def cylinder_unwrap(objs, chosen, axis):
    """UVs in metres for the chosen faces about a vertical axis (x, y): faces toward the axis unrolled as (arc, height),
    faces up or down as (arc, radius), faces along the arc as (radius, height); an island per edge-connected run of one
    kind, unrolled at its mean radius. The panel's and the screen bezel's curved strips come out straight and pack
    tightly, where a planar projection bends them into arcs."""
    ax, ay = axis
    up = Vector((0, 0, 1))
    for o in objs:
        sel = [int(i) for i in np.flatnonzero(chosen[o.name])]
        if not sel:
            continue
        me = o.data
        mw = o.matrix_world
        rot = mw.to_3x3()
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        uv = bm.loops.layers.uv["UVMap"]
        wco = {v.index: mw @ v.co for v in bm.verts}
        kind = {}
        for i in sel:
            f = bm.faces[i]
            c = mw @ f.calc_center_median()
            n = (rot @ f.normal).normalized()
            rad = Vector((c.x - ax, c.y - ay, 0)).normalized()
            a = (abs(n.dot(rad)), abs(n.z), abs(n.dot(up.cross(rad))))
            kind[i] = a.index(max(a))
        parent = {i: i for i in sel}

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in sel:
            for e in bm.faces[i].edges:
                for g in e.link_faces:
                    if g.index != i and g.index in parent and kind[g.index] == kind[i]:
                        parent[find(i)] = find(g.index)
        groups = {}
        for i in sel:
            groups.setdefault(find(i), []).append(i)
        for faces in groups.values():
            k = kind[faces[0]]
            vs = {v.index for i in faces for v in bm.faces[i].verts}
            rm = sum(math.hypot(wco[v].x - ax, wco[v].y - ay) for v in vs) / len(vs)
            for i in faces:
                for loop in bm.faces[i].loops:
                    p = wco[loop.vert.index]
                    phi = math.atan2(p.x - ax, ay - p.y)
                    r = math.hypot(p.x - ax, p.y - ay)
                    loop[uv].uv = ((phi * rm, p.z), (phi * rm, r), (r, p.z))[k]
        bm.to_mesh(me)
        bm.free()


def layout_uvs(objs, fd, eyes, occluders=()):
    """Unwrap and pack each PBR slot of objs (occluders only hide faces); returns {"density": {slot: {class: px/m}}, "live": {slot: m2}, "dead": {name:
    set of faces}, "mirrored": {name: set of faces}} for the bake (dead and mirrored faces only occlude)."""
    want = targets(fd)
    for o in objs:
        if "UVMap" not in o.data.uv_layers:
            o.data.uv_layers.new(name="UVMap")
    vis = visible_faces(objs, eyes, occluders)
    twins = {o.name: mirror_twins(o, PBR_SLOTS) for o in objs}
    live, dead, mirrored = {}, {}, {}
    for o in objs:
        names = [m.name for m in o.data.materials]
        pbr = np.array([names[p.material_index] in PBR_SLOTS for p in o.data.polygons], bool)
        v = vis[o.name].copy()
        for dst, src in twins[o.name].items():  # a pair lives if either half is seen; the pilot's half carries it
            if v[dst]:
                v[src] = True
        t = twins[o.name]
        live[o.name] = np.array([v[i] and i not in t for i in range(len(v))], bool) & pbr
        mirrored[o.name] = {i for i in t if v[t[i]]}
        dead[o.name] = {i for i in np.flatnonzero(pbr) if not v[i] and not (i in t and v[t[i]])}
    slot_names = {o.name: [m.name for m in o.data.materials] for o in objs}
    report = {"density": {}, "live_m2": {}}
    scene = bpy.context.scene
    scene.tool_settings.use_uv_select_sync = True
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    for slot in PBR_SLOTS:
        chosen = {}
        for o in objs:
            idx = np.array([slot_names[o.name][p.material_index] == slot for p in o.data.polygons], bool)
            chosen[o.name] = idx & live[o.name]
        if not any(c.any() for c in chosen.values()):
            continue
        if slot == PANEL_SLOT:
            cylinder_unwrap(objs, chosen, fd.band_axis())
        else:
            _select(objs, chosen)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.uv.smart_project(angle_limit=math.radians(50), island_margin=0.0, scale_to_bounds=False)
            bpy.ops.object.mode_set(mode="OBJECT")
        weights = want[slot]
        for o in objs:  # islands grown to their class's target relative to the slot's others
            me = o.data
            cls = np.zeros(len(me.polygons), np.int32)
            me.attributes["cls"].data.foreach_get("value", cls)
            bm = bmesh.new()
            bm.from_mesh(me)
            bm.faces.ensure_lookup_table()
            uv = bm.loops.layers.uv["UVMap"]
            faces = [bm.faces[i] for i in np.flatnonzero(chosen[o.name])]
            for island in _islands(bm, uv, faces):
                areas_w = sum(f.calc_area() for f in island)
                areas_uv = sum(_uv_area([l[uv].uv for l in f.loops]) for f in island)
                k = max(weights.get(int(cls[f.index]), min(weights.values())) for f in island)
                s = math.sqrt(areas_w / areas_uv) * k / 1000.0 if areas_uv > 1e-12 else 1.0
                loops = [l for f in island for l in f.loops]
                c = sum((l[uv].uv for l in loops), Vector((0, 0))) / len(loops)
                for l in loops:
                    l[uv].uv = c + (l[uv].uv - c) * s
            bm.to_mesh(me)
            bm.free()
        _select(objs, chosen)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.uv.pack_islands(rotate=True, rotate_method="ANY", scale=True, shape_method="CONCAVE",
                                margin_method="FRACTION", margin=PACK_MARGIN / ATLAS)
        bpy.ops.object.mode_set(mode="OBJECT")
        squeeze = 1.0 - DEAD_STRIPE / ATLAS
        world_by_cls, uv_by_cls = {}, {}
        for o in objs:
            me = o.data
            uvd = me.uv_layers["UVMap"].data
            cls = np.zeros(len(me.polygons), np.int32)
            me.attributes["cls"].data.foreach_get("value", cls)
            for i in np.flatnonzero(chosen[o.name]):
                p = me.polygons[i]
                for li in p.loop_indices:
                    uvd[li].uv = (uvd[li].uv[0] * squeeze, uvd[li].uv[1])
                k = int(cls[i])
                world_by_cls[k] = world_by_cls.get(k, 0.0) + p.area
                uv_by_cls[k] = uv_by_cls.get(k, 0.0) + _uv_area([uvd[li].uv for li in p.loop_indices])
        report["density"][slot] = {fd_class_name(fd, k): round(ATLAS * math.sqrt(uv_by_cls[k] / world_by_cls[k]), 1)
                                   for k in sorted(world_by_cls) if uv_by_cls[k] > 0}
        report["live_m2"][slot] = round(sum(world_by_cls.values()), 3)
        report.setdefault("uv_fill", {})[slot] = round(sum(uv_by_cls.values()) / squeeze, 3)
    for o in objs:
        copy_mirrored(o, {i: twins[o.name][i] for i in mirrored[o.name]})
        uvd = o.data.uv_layers["UVMap"].data
        for i in dead[o.name]:
            for li in o.data.polygons[i].loop_indices:
                uvd[li].uv = (1.0 - DEAD_STRIPE / 2 / ATLAS, 0.5)
    for o in objs:
        o.select_set(False)
    report["faces"] = {o.name: {"live": int(live[o.name].sum()), "mirrored": len(mirrored[o.name]), "dead": len(dead[o.name])}
                       for o in objs}
    report["dead"] = dead
    report["mirrored"] = mirrored
    return report


def fd_class_name(fd, k):
    names = {fd.LINING: "lining", fd.FLOOR: "floor", fd.PANEL: "panel", fd.CONSOLE: "console", fd.FRAME: "frame",
             fd.BEZEL: "bezel", fd.RACK: "rack", fd.KNOB: "knob", fd.METAL: "metal", fd.HANDLE: "handle", fd.GRIP: "grip",
             fd.OVERHEAD: "overhead", fd.HATCH: "hatch", fd.STRUCT: "struct", fd.HAZARD: "hazard"}
    return names.get(k, str(k))


def _uv_area(q):
    return sum(abs((q[i] - q[0]).cross(q[i + 1] - q[0])) / 2 for i in range(1, len(q) - 1))
