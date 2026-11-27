"""The forward screen is a camera feed: from the pilot's seat nothing of the aircraft may show through it. One solid,
the screen's sheet projected from the pilot's eye, from just behind the sheet to 6 m out; one operation, its boolean
difference from every cockpit mesh behind the screen (the deck and the inner glass). Nothing else is cut. The cut faces
lie inside the solid, behind the screen from the eye, so no cut edge shows from it.
The pilot's eye alone (--eyes nominal, the default): the union over the head tracker's range (--eyes tracker, 28
positions) holds eyes 45 cm forward and 15 cm low, close under the screen's top, whose view through it climbs through
the windscreen's frame and roof and drops behind the panel's modules, and from the eye it took the frame, the glass
and the panel's backing away (band/cut_compare.png). A head moved off the eye sees the cut's edge over the screen;
the inner glass's light tint (flightdeck_textures.GLASS_TINT) keeps glass against no glass quiet there.
  blender -b --factory-startup --python flightdeck_cut.py -- <export.blend> [--eyes nominal|tracker|sway] --apply
Imported by flightdeck_sightlines.py for its one number: through_screen(), rays from the pilot's eye through the
screen that meet any cockpit mesh, which must be zero (and, reported only, the same over the head tracker's range)."""
import math

from mathutils import Vector

SCREEN = "band"
TARGETS = ("flightdeck_int", "glass_int")
NEAR, FAR = 0.006, 6.0  # metres behind the sheet the solid starts; metres from the eye it runs out to
# chords along each of the sheet's edges: on the 4.5 m radius six sag 4 mm, inside NEAR, and the exact boolean cut a
# face of the deck along every face of the solid (with the sheet's own 24, 142,000 triangles)
SEGMENTS = 6
PILOT_EYE = Vector((0.55, 6.55 - 22.475, 5.0))


def head_offsets(sway=0.075):
    """The head tracker's range with the G sway, as flightdeck_sightlines.offsets: (Unity x, y, z) to Blender."""
    for x in (-0.25 - sway, 0.0, 0.25 + sway):
        for y in (-0.15 - sway, 0.0, 0.15 + sway):
            for z in (-0.10 - sway, 0.175, 0.45 + sway):
                yield Vector((-x, -z, y))


EYE_SET = "nominal"


def eye_positions(which=None):
    which = which or EYE_SET
    if which == "nominal":
        return [PILOT_EYE]
    return [PILOT_EYE] + [PILOT_EYE + off for off in head_offsets(0.075 if which == "sway" else 0.0)]


def sheet_rings(band, segments=None):
    """The sheet's top and bottom edges, each sorted along its arc, in world space; with `segments`, every few of its
    vertices, `segments` chords an edge (its ends always kept)."""
    bv = [band.matrix_world @ v.co for v in band.data.vertices]
    zt, zb = max(v.z for v in bv), min(v.z for v in bv)
    rings = [sorted((v for v in bv if abs(v.z - z) < 0.003), key=lambda v: v.x) for z in (zt, zb)]
    if segments:
        n = len(rings[0]) - 1
        keep = sorted({round(k * n / segments) for k in range(segments + 1)})
        rings = [[r[k] for k in keep] for r in rings]
    return rings


def frustum(bm, e, rings):
    """A closed solid into bmesh bm: the sheet's outline seen from eye e, from NEAR behind the sheet to FAR from e."""
    top, bot = rings
    near = [[v + (v - e).normalized() * NEAR for v in ring] for ring in (top, bot)]
    far = [[e + (v - e).normalized() * FAR for v in ring] for ring in (top, bot)]
    vn = [[bm.verts.new(p) for p in ring] for ring in near]
    vf = [[bm.verts.new(p) for p in ring] for ring in far]
    n = len(top)
    for k in range(n - 1):
        bm.faces.new((vn[0][k], vn[0][k + 1], vn[1][k + 1], vn[1][k]))  # the sheet's face
        bm.faces.new((vf[0][k + 1], vf[0][k], vf[1][k], vf[1][k + 1]))  # the far face
        bm.faces.new((vn[0][k + 1], vn[0][k], vf[0][k], vf[0][k + 1]))  # over the top edge
        bm.faces.new((vn[1][k], vn[1][k + 1], vf[1][k + 1], vf[1][k]))  # under the bottom edge
    for k in (0, n - 1):  # the two ends
        bm.faces.new((vn[0][k], vn[1][k], vf[1][k], vf[0][k]))


def cut_solid():
    """One closed solid: the union of a frustum per eye position, its normals out."""
    import bmesh
    import bpy
    band = bpy.data.objects[SCREEN]
    rings = sheet_rings(band, SEGMENTS)
    if len(rings[0]) != len(rings[1]):
        raise ValueError("the sheet's top and bottom edges have %d and %d vertices" % (len(rings[0]), len(rings[1])))
    solid = None
    for e in eye_positions():
        bm = bmesh.new()
        frustum(bm, e, rings)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new("screen_cut")
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new("screen_cut", me)
        bpy.context.scene.collection.objects.link(ob)
        if solid is None:
            solid = ob
            continue
        mod = solid.modifiers.new("union", "BOOLEAN")
        mod.operation, mod.solver, mod.object = "UNION", "EXACT", ob
        dg = bpy.context.evaluated_depsgraph_get()
        merged = bpy.data.meshes.new_from_object(solid.evaluated_get(dg))
        solid.modifiers.remove(mod)
        old, solid.data = solid.data, merged
        bpy.data.meshes.remove(old)
        bpy.data.objects.remove(ob)
    print("CUT solid", len(solid.data.polygons), "faces from", len(eye_positions()), "eye positions")
    return solid


NEAR_GLASS = 0.0005  # metres beyond the inner glass the panes' solid starts (at 2 mm the windscreen's centre post,
# its side wall 1 mm behind the pane that overlaps it, kept a sliver in the opening)


def glass_solid():
    """The panes' solid: the inner glass's surface carried out along the pilot's sightlines, from NEAR_GLASS beyond it
    to FAR from his eye. What stands in it is outside the cabin (the nose the game hides) yet seen through a pane: the
    frames' lining past the side panes' edges read as opaque tabs in the side glazing, and the upper windscreen's trim
    as steps into the opening."""
    import bmesh
    import bpy
    g = bpy.data.objects["glass_int"]
    e = PILOT_EYE
    src = bmesh.new()
    src.from_mesh(g.data)
    src.transform(g.matrix_world)
    bm = bmesh.new()
    near = {v: bm.verts.new(v.co + (v.co - e).normalized() * NEAR_GLASS) for v in src.verts}
    far = {v: bm.verts.new(e + (v.co - e).normalized() * FAR) for v in src.verts}
    for f in src.faces:
        bm.faces.new([near[v] for v in f.verts])
        bm.faces.new([far[v] for v in reversed(f.verts)])
    for ed in src.edges:
        if len(ed.link_faces) == 1:  # the surface's edge: a wall along the sightlines
            a, b = ed.verts
            bm.faces.new((near[a], near[b], far[b], far[a]))
    src.free()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("glass_cut")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("glass_cut", me)
    bpy.context.scene.collection.objects.link(ob)
    print("CUT glass solid", len(me.polygons), "faces")
    return ob


def inside_test(solid):
    """A test: whether a point lies inside the closed solid (rays up and down both meet it an odd number of times)."""
    from mathutils.bvhtree import BVHTree
    tree = BVHTree.FromPolygons([solid.matrix_world @ v.co for v in solid.data.vertices], [tuple(p.vertices) for p in solid.data.polygons])

    def crossings(p, d):
        n, o = 0, p
        while True:
            h = tree.ray_cast(o, d, 100.0)
            if h[0] is None:
                return n
            n += 1
            o = h[0] + d * 1e-5
    return tree, lambda p: crossings(p, Vector((0, 0, 1))) % 2 == 1 and crossings(p, Vector((0, 0, -1))) % 2 == 1


def cut_by(ob, solid):
    """The boolean difference of solid from ob, on the faces that touch or lie in it alone: they are split off, cut,
    cleaned and merged back, and every other face stays as it was. Run on the whole mesh, the cut's clean-up of slivers
    and polygons also reached faces nowhere near it, and drew dark streaks across printed console panels."""
    import bmesh
    import bpy
    from mathutils.bvhtree import BVHTree
    stree, inside = inside_test(solid)
    mw = ob.matrix_world
    otree = BVHTree.FromPolygons([mw @ v.co for v in ob.data.vertices], [tuple(p.vertices) for p in ob.data.polygons])
    touch = {i for i, _ in otree.overlap(stree)}
    touch |= {p.index for p in ob.data.polygons if inside(mw @ p.center)}
    if not touch:
        return 0, len(ob.data.polygons)
    before = len(ob.data.polygons)
    part = ob.copy()
    part.data = ob.data.copy()
    bpy.context.scene.collection.objects.link(part)
    bm = bmesh.new()
    bm.from_mesh(part.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in touch], context="FACES")
    bm.to_mesh(part.data)
    bm.free()
    mod = part.modifiers.new("cut", "BOOLEAN")
    mod.operation, mod.solver, mod.object = "DIFFERENCE", "EXACT", solid
    # not use_self: resolving the deck's own intersections (its parts overlap everywhere) split it to 141,000 triangles
    mod.use_hole_tolerant = True  # the deck is open surfaces, not a closed solid
    mod.material_mode = "INDEX"  # the deck keeps its own slots and indices
    with bpy.context.temp_override(object=part, active_object=part, selected_objects=[part]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    bm = bmesh.new()
    bm.from_mesh(part.data)
    # the cut leaves polygons along its edge, some with slivers of no area: triangulated, and the slivers gone, since
    # Unity's import drops a degenerate triangle and its submesh then no longer matches the export's count
    bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4], quad_method="BEAUTY", ngon_method="BEAUTY")
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.calc_area() < 1e-9], context="FACES")
    bm.to_mesh(part.data)
    bm.free()
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in touch], context="FACES")
    kept = len(bm.faces)
    bm.from_mesh(part.data)  # appended: the cut part back beside the untouched faces
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    pme = part.data
    bpy.data.objects.remove(part)
    bpy.data.meshes.remove(pme)
    if kept != before - len(touch):
        raise RuntimeError("the cut changed faces outside its solid in %s" % ob.name)
    return len(touch), len(ob.data.polygons)


def apply_cut():
    import bpy
    solid = cut_solid()
    for name in TARGETS:
        ob = bpy.data.objects[name]
        before = len(ob.data.polygons)
        n, after = cut_by(ob, solid)
        print("CUT screen", name, before, "->", after, "faces;", n, "touched the solid,", before - n, "untouched")
    bpy.data.objects.remove(solid)
    panes = glass_solid()
    deck = bpy.data.objects["flightdeck_int"]
    before = len(deck.data.polygons)
    n, after = cut_by(deck, panes)
    print("CUT panes flightdeck_int", before, "->", after, "faces;", n, "touched the solid,", before - n, "untouched")
    bpy.data.objects.remove(panes)


def through_panes(tree, ref, step=1.0):
    """Rays from the pilot's eye over the view's range (every `step` deg) whose first drawn face is the inner glass and
    which then meet a drawn opaque cockpit face more than 2 x NEAR_GLASS past the pane (nearer is the pane's own seam
    with the frame that holds it): (rays through a pane, rays that met something, by side: the left pane, the
    windscreen, the right pane, by the ray's bearing; and the openings: the rays through a pane, by side)."""
    from collections import Counter
    e = PILOT_EYE
    rays = met = 0
    side, seen = Counter(), Counter()
    pan = -165.0
    while pan <= 165:
        tilt = -65.0
        while tilt <= 65:
            p, t = math.radians(pan), math.radians(tilt)
            d = Vector((-math.sin(p) * math.cos(t), -math.cos(p) * math.cos(t), -math.sin(t)))
            o, through, g = e, False, None
            for _ in range(40):
                h = tree.ray_cast(o, d, 40.0)
                if h[0] is None:
                    break
                ob = ref[h[2]][0]
                if h[1].dot(d) < 0:
                    if not through:
                        if ob != "glass_int":
                            break  # the first thing drawn is not a pane
                        through, g = True, h[0]
                        rays += 1
                        seen["left" if pan < -35 else ("right" if pan > 35 else "windscreen")] += 1
                    elif ob not in ("glass_int", SCREEN, "band_marker"):
                        if (h[0] - g).length > 2 * NEAR_GLASS:
                            met += 1
                            side["left" if pan < -35 else ("right" if pan > 35 else "windscreen")] += 1
                        break
                o = h[0] + d * 0.0002
            tilt += step
        pan += step
    return rays, met, dict(side), dict(seen)


def through_screen(tree, ref, step=1.0, which=None):
    """Rays from each of the pilot's eye positions through the screen (every `step` deg over it) that meet a drawn
    face of any cockpit mesh past the sheet: (rays through the screen, rays that met something, what they met)."""
    from collections import Counter
    import bpy
    band = bpy.data.objects[SCREEN]
    rings = sheet_rings(band)
    rays = met = 0
    what = Counter()
    for e in eye_positions(which):
        vs = rings[0] + rings[1]
        az = [math.degrees(math.atan2(v.x - e.x, -(v.y - e.y))) for v in vs]
        el = [math.degrees(math.atan2(v.z - e.z, math.hypot(v.x - e.x, v.y - e.y))) for v in vs]
        a = min(az)
        while a <= max(az):
            t = min(el) - 1
            while t <= max(el) + 1:
                p, tl = math.radians(a), math.radians(t)
                t += step / 2
                d = Vector((math.sin(p) * math.cos(tl), -math.cos(p) * math.cos(tl), math.sin(tl)))
                o, through = e, False
                for _ in range(40):
                    h = tree.ray_cast(o, d, 8.0)
                    if h[0] is None:
                        break
                    ob = ref[h[2]][0]
                    if not through:
                        if ob != SCREEN:
                            if h[1].dot(d) < 0:
                                break  # something drawn before the screen: not a ray through it
                        else:
                            through = True
                            rays += 1
                    elif h[1].dot(d) < 0 and ob not in (SCREEN, "band_marker"):
                        met += 1
                        what[(ob, ref[h[2]][1])] += 1
                        break
                    o = h[0] + d * 0.0002
            a += step
    return rays, met, what


if __name__ == "__main__":
    import sys

    import bpy
    argv = sys.argv[sys.argv.index("--") + 1:]
    bpy.ops.wm.open_mainfile(filepath=argv[0])
    if "--eyes" in argv:
        EYE_SET = argv[argv.index("--eyes") + 1]
    if "--apply" in argv:
        apply_cut()
        bpy.ops.wm.save_mainfile(filepath=argv[0])
