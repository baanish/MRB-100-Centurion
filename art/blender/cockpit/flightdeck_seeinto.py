"""Seeing into or between parts, from each real eye: rays every 0.5 deg over the forward
half (pan -90 to 90, tilt 60 down to 10 up), Unity's rules (back faces pass, glass passes). Two faults are counted:
  into  - the first face met is a part's back face (culled in game), so the eye sees inside the part or past it: an
          open box, a panel's open underside, a bare brace's hollow (more than CAVITY behind the culled face);
  slit  - the ray gets out (through glass or not) while its neighbours 1 deg either side, across or up and down, both
          stop on an opaque face within 1.5 m: a thin opening between parts, as at the forward corners.
Regions: 'corner' (outboard of 0.75 m, z 4.55 to 5.15, forward of the eye), 'under' (the panel's underside and the
footwells, z under 4.55, forward of station 6.2), 'other'. Imported by flightdeck_sightlines.py, or run alone:
blender -b --factory-startup --python flightdeck_seeinto.py -- <export flightdeck.blend> <blockout.blend> [--close]
  --close: a twin behind every face of flightdeck_int seen into, round after round until none, saved into the
  export (the build step after flightdeck_build.py's export, which closes most of them in its own scene)."""
import math
from collections import Counter

from mathutils import Vector

GLASS = {"glass_int", "band", "band_marker"}
CAVITY = 0.01  # metres past a culled face to the next front face: under it, a ray clipping a thin plate's edge


def behind_screen(tree, ref, e, p):
    """Whether the sightline from e to p passes the screen first."""
    d = p - e
    L = d.length
    d.normalize()
    o, t = e, 0.0
    while True:
        h = tree.ray_cast(o, d, L - t - 0.001)
        if h[0] is None:
            return False
        if ref[h[2]][0] == "band":
            return True
        t += h[3] + 0.0002
        o = h[0] + d * 0.0002


def region(p):
    if abs(p.x) > 0.75 and 4.55 < p.z < 5.15 and p.y < -16.2:
        return "corner"
    if p.z < 4.55 and p.y < -15.75:
        return "under"
    return "other"


def direction(pan, tilt):
    p, t = math.radians(pan), math.radians(tilt)
    return Vector((-math.sin(p) * math.cos(t), -math.cos(p) * math.cos(t), -math.sin(t))).normalized()


def trace(tree, owner, e, d):
    """('solid', distance, point) at the first opaque front face; ('into', ., point of the culled face, owner) when the
    first opaque face met is a back face and the ray then stops on a front face behind it (the inside of a part); ('out',
    ., point of the last face passed or None) when the ray gets out (a view through glass, or an escape)"""
    o, last, back, glass = e, None, None, False
    while True:
        h = tree.ray_cast(o, d, 40.0)
        if h[0] is None:
            return "out", None, last
        glass |= owner[h[2]] in GLASS
        if owner[h[2]] not in GLASS and h[1].dot(d) < 0:
            # a cavity behind the culled face, not the same plate's top a few mm past its side wall's edge
            if back is not None and (h[0] - back[0]).length > CAVITY:
                return ("into", (back[0] - e).length) + back
            return "solid", (h[0] - e).length, h[0]
        if owner[h[2]] not in GLASS and back is None and not glass and not owner[h[2]].startswith("stock"):
            back = (h[0], owner[h[2]], h[2])  # (the game's stick, throttle and seat are not ours to close; past glass is outside)
        o, last = h[0] + d * 0.0005, h[0]


def seeinto(tree, owner, eyes, step=0.5):
    res = {}
    for seat, e in eyes.items():
        pans = [-90 + step * i for i in range(int(180 / step) + 1)]
        tilts = [-10 + step * i for i in range(int(70 / step) + 1)]
        grid = {(p, t): trace(tree, owner, e, direction(p, t)) for p in pans for t in tilts}
        counts, places, faces = Counter(), Counter(), set()
        k = int(round(1.0 / step))
        for (p, t), g in grid.items():
            kind, dist, pt = g[:3]
            if kind == "into":
                reg = region(pt)
                counts[("into", reg)] += 1
                places[("into", reg, g[3], tuple(round(c, 1) for c in pt))] += 1
                faces.add(g[4])
            elif kind == "out":
                def shut(a, b):
                    g = grid.get((a, b))
                    return g is not None and g[0] == "solid" and g[1] < 1.5
                if (shut(p - k * step, t) and shut(p + k * step, t)) or (shut(p, t - k * step) and shut(p, t + k * step)):
                    # where it slips through: the nearer neighbour's face
                    near = min((grid[q] for q in ((p - k * step, t), (p + k * step, t), (p, t - k * step), (p, t + k * step))
                                if q in grid and grid[q][0] == "solid"), key=lambda g: g[1])
                    reg = region(near[2])
                    counts[("slit", reg)] += 1
                    places[("slit", reg, tuple(round(c, 1) for c in near[2]))] += 1
        res[seat] = {"rays": len(grid), "counts": {"%s %s" % k_: n for k_, n in sorted(counts.items())},
                     "places": [[list(k_), n] for k_, n in places.most_common(12)], "faces": sorted(faces)}
        print("SEE", seat, res[seat]["counts"])
    return res


def build(objs):
    """The scene's meshes in one tree: (tree, owner per face, (object, polygon index) per face)."""
    import bpy
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    vs, ps, owner, ref = [], [], [], []
    for o in objs:
        me = o.evaluated_get(dg).to_mesh()
        b = len(vs)
        vs += [o.matrix_world @ v.co for v in me.vertices]
        for p in me.polygons:
            ps.append([b + i for i in p.vertices])
            owner.append(o.name)
            ref.append((o.name, p.index))
    return BVHTree.FromPolygons(vs, ps), owner, ref


def close(deck, faces):
    """A twin 0.1 mm behind each of the deck's faces, turned the other way (flightdeck_build.close_backs' recipe)."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(deck.data)
    bm.normal_update()  # from_mesh leaves face normals unset: the twins sat on their faces
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.active
    for f in [bm.faces[i] for i in faces]:
        nf = bm.faces.new([bm.verts.new(v.co - f.normal * 0.0001) for v in reversed(f.verts)])
        # the face's own finish on its back: in flat black the housings' undersides read as bare plates
        nf.material_index = f.material_index
        if uv is not None:
            for lp, src in zip(nf.loops, reversed(f.loops)):
                lp[uv].uv = src[uv].uv
    bm.to_mesh(deck.data)
    bm.free()
    deck.data.update()  # so the next round's evaluated mesh has the twins


def screen_cylinder():
    """The camera screen's cylinder, fitted to the band's sheet: (axis x, axis y, radius), or None."""
    import bpy
    band = bpy.data.objects.get("band")
    if band is None:
        return None
    bv = [band.matrix_world @ v.co for v in band.data.vertices]
    lo = min(v.z for v in bv)
    ring = [v for v in bv if abs(v.z - lo) < 0.005]
    a, b, c = min(ring, key=lambda v: v.x), min(ring, key=lambda v: abs(v.x)), max(ring, key=lambda v: v.x)
    d_ = 2 * (a.x * (b.y - c.y) + b.x * (c.y - a.y) + c.x * (a.y - b.y))
    ux = ((a.x ** 2 + a.y ** 2) * (b.y - c.y) + (b.x ** 2 + b.y ** 2) * (c.y - a.y) + (c.x ** 2 + c.y ** 2) * (a.y - b.y)) / d_
    uy = ((a.x ** 2 + a.y ** 2) * (c.x - b.x) + (b.x ** 2 + b.y ** 2) * (a.x - c.x) + (c.x ** 2 + c.y ** 2) * (b.x - a.x)) / d_
    return ux, uy, math.hypot(a.x - ux, a.y - uy)


def split_on_screen(deck, faces):
    """Splits each face along the camera screen's cylinder (fitted to the band's sheet), by the vertical plane tangent
    to it where the face lies."""
    import math
    import bmesh
    import bpy
    cyl = screen_cylinder()
    if cyl is None or not faces:
        return
    ux, uy, r = cyl
    mw = deck.matrix_world
    inv = mw.inverted()
    bm = bmesh.new()
    bm.from_mesh(deck.data)
    bm.faces.ensure_lookup_table()
    ahead = []
    for f in [bm.faces[i] for i in faces]:
        if not f.is_valid:
            continue
        cw = mw @ f.calc_center_median()
        rad = Vector((cw.x - ux, cw.y - uy, 0.0)).normalized()
        co = Vector((ux, uy, cw.z)) + rad * r
        out = bmesh.ops.bisect_plane(bm, geom=list(f.verts) + list(f.edges) + [f], dist=1e-5, plane_co=inv @ co,
                                     plane_no=(inv.to_3x3() @ rad).normalized())
        # the half beyond the screen goes now (behind it, as flightdeck_cut.py would take it): left, it stood in the
        # screen after the last cleanup
        for g in {lf for e in out["geom_cut"] if isinstance(e, bmesh.types.BMEdge) for lf in e.link_faces}:
            cg = mw @ g.calc_center_median()
            if math.hypot(cg.x - ux, cg.y - uy) > r + 0.001:
                ahead.append(g)
    bmesh.ops.delete(bm, geom=list(set(ahead)), context="FACES")
    bm.to_mesh(deck.data)
    bm.free()
    deck.data.update()


if __name__ == "__main__":
    import sys

    import bpy
    sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
    argv = sys.argv[sys.argv.index("--") + 1:]
    bpy.ops.wm.open_mainfile(filepath=argv[0])
    with bpy.data.libraries.load(argv[1]) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith("stock_seat") or n.startswith("stockref_Multirole1_joystick")
                       or n.startswith("stockref_Multirole1_throttle")]
    stock = [o for o in dst.objects if o is not None]
    for o in stock:
        bpy.context.scene.collection.objects.link(o)
    EYES = {"pilot": Vector((0.55, 6.55 - 22.475, 5.0))}  # only the player's view at the normal eye counts
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if "--close" in argv:
        # closes, as the game and flightdeck_sightlines.py stand the stock parts, every face of the deck seen into, until none
        deck = bpy.data.objects["flightdeck_int"]
        for rnd in range(4):
            tree, owner, ref = build(meshes)
            r = seeinto(tree, owner, EYES)
            mw_ = deck.matrix_world
            def twin_behind_screen(pi):  # only the eyes on the face's back see its twin
                p_ = deck.data.polygons[pi]
                c_, n_ = mw_ @ p_.center, (mw_.to_3x3() @ p_.normal).normalized()
                return any(n_.dot(e_ - c_) < 0 and behind_screen(tree, ref, e_, c_) for e_ in EYES.values())
            seen_into = {ref[i][1] for v in r.values() for i in v["faces"] if ref[i][0] == deck.name}
            cyl = screen_cylinder()

            def crosses(pi):  # a face across the screen's cylinder
                if cyl is None:
                    return False
                ux_, uy_, r_ = cyl
                rs = [math.hypot((mw_ @ deck.data.vertices[k].co).x - ux_, (mw_ @ deck.data.vertices[k].co).y - uy_)
                      for k in deck.data.polygons[pi].vertices]
                # (3 mm either way: a piece split along the tangent at its middle still crosses the curve by a mm at its
                # ends, and was split again every round, never closed)
                return min(rs) < r_ - 0.003 and max(rs) > r_ + 0.003
            todo = sorted(pi for pi in seen_into if not twin_behind_screen(pi) and not crosses(pi))
            # a face across the screen's cylinder (the coaming over its top edge): split along it, and the next round
            # twins the piece on the cabin's side
            split_on_screen(deck, sorted(seen_into - set(todo)))
            print("SEE close round", rnd, "faces", len(todo))
            if not todo:
                break
            close(deck, todo)
        for o in stock:
            bpy.data.objects.remove(o)
        bpy.ops.wm.save_mainfile(filepath=argv[0])
    else:
        tree, owner, ref = build(meshes)
        for seat, v in seeinto(tree, owner, EYES).items():
            for pl in v["places"]:
                print("SEE place", seat, pl)
