"""Checks the displays' tac screen UVs against the canvas's pages (flightdeck.PAGES, flightdeck.DISPLAY_ORDER): each
display face shows exactly its one page, whole (its UVs span the page's rectangle less PAGE_INSET, within half a
pixel), upright (up the face runs up the page), unstretched (the face's width over its height on the glass matches the
page's aspect within 1%), inset PAGE_MARGIN in its opening (the face as wide and tall as flightdeck.display_page within
a millimetre), and nothing samples outside it; and no bezel, key or screw hides any of a page's edge, the wing
display's canvas (flightdeck.wing_canvas) included, from either seat's head positions (flightdeck_uv.head_positions).

Inside the flight deck build: check(tac_screen_object, flightdeck module, occluders) -> (passed, report lines), the
occluders the interior's opaque parts. On a built blend:
blender -b .cache/cockpit/build/flightdeck.blend --python art/blender/cockpit/check_display_uvs.py"""

import math
import sys
from pathlib import Path

from mathutils import Vector
from mathutils.bvhtree import BVHTree

EDGE_SAMPLES = 12  # points along each of a page's edges, a millimetre inside it, that every head position must see


def islands(me, slot_index):
    parent = {}

    def find(i):
        parent.setdefault(i, i)
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    polys = [p for p in me.polygons if p.material_index == slot_index]
    for p in polys:
        vs = list(p.vertices)
        for v in vs[1:]:
            parent[find(vs[0])] = find(v)
    groups = {}
    for p in polys:
        groups.setdefault(find(p.vertices[0]), []).append(p)
    return list(groups.values())


def canvas_edge_points(centre, right, hw, hh):
    """Points a millimetre inside a flat canvas's edges, EDGE_SAMPLES along each."""
    out = []
    for k in range(EDGE_SAMPLES):
        t = -1 + 2 * k / (EDGE_SAMPLES - 1)
        for u, v in ((t * (hw - 0.001), hh - 0.001), (t * (hw - 0.001), 0.001 - hh), (hw - 0.001, t * (hh - 0.001)),
                     (0.001 - hw, t * (hh - 0.001))):
            out.append(centre + right * u + Vector((0.0, 0.0, v)))
    return out


def edge_points(loops, fd):
    """Points a millimetre inside a display face's edges, EDGE_SAMPLES along each, on its cylinder."""
    phis = [fd.cyl_coords(p)[0] for p, _ in loops]
    r = fd.cyl_coords(loops[0][0])[1]
    a0, a1 = min(phis), max(phis)
    z0, z1 = min(p.z for p, _ in loops), max(p.z for p, _ in loops)
    da, dz = math.degrees(0.001 / r), 0.001
    out = []
    for k in range(EDGE_SAMPLES):
        t = k / (EDGE_SAMPLES - 1)
        a, z = a0 + da + (a1 - a0 - 2 * da) * t, z0 + dz + (z1 - z0 - 2 * dz) * t
        out += [fd.cyl(a, z0 + dz, r), fd.cyl(a, z1 - dz, r), fd.cyl(a0 + da, z, r), fd.cyl(a1 - da, z, r)]
    return out


def occluder_tree(occluders):
    verts, polys = [], []
    for o in occluders:
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        polys += [tuple(base + i for i in p.vertices) for p in o.data.polygons]
    return BVHTree.FromPolygons(verts, polys)


def hidden_edges(points, tree, eyes):
    """The (eye, point) pairs where something in the tree lies between the eye and the page's edge point."""
    out = []
    for e in eyes:
        for p in points:
            d = p - e
            hit = tree.ray_cast(e, d.normalized(), d.length - 0.0005)
            if hit[0] is not None:
                out.append((e, p))
    return out


def check(obj, fd, occluders=()):
    import flightdeck_uv as fuv
    me = obj.data
    mw = obj.matrix_world
    names = [m.name for m in me.materials]
    if fd.DISPLAY_SLOT not in names:
        return False, ["no display faces"]
    if len(names) != 1:
        return False, [f"FAIL the tac screen carries {names}: only the pages may fill the openings"]
    uv = me.uv_layers["UVMap"].data
    groups = islands(me, names.index(fd.DISPLAY_SLOT))
    # order the displays from the +X end, as DISPLAY_ORDER runs
    groups.sort(key=lambda g: -sum((mw @ me.vertices[p.vertices[0]].co).x for p in g) / len(g))
    pages = [k for k in fd.DISPLAY_ORDER if k in fd.PAGES]
    lines, ok = [], len(groups) == len(pages)
    if not ok:
        lines.append(f"FAIL {len(groups)} display faces, {len(pages)} expected")
    tree = occluder_tree(occluders) if occluders else None
    eyes = fuv.head_positions(fd, 1) + fuv.head_positions(fd, -1)
    if tree:
        hidden = hidden_edges(canvas_edge_points(*fd.wing_canvas()), tree, eyes)
        ok &= not hidden
        lines.append(f"{'PASS' if not hidden else 'FAIL'} {fd.WING_PAGE:8} canvas edge hidden from {len(hidden)} of "
                     f"{len(eyes) * EDGE_SAMPLES * 4} sightlines")
    for g, key in zip(groups, pages):
        (x0, y0, x1, y1), turned = fd.PAGES[key]
        i = fd.PAGE_INSET
        want = (x0 + i, y0 + i, x1 - i, y1 - i)
        loops = [(mw @ me.vertices[me.loops[li].vertex_index].co, uv[li].uv) for p in g for li in p.loop_indices]
        px = [(t[0] * fd.CANVAS[0], t[1] * fd.CANVAS[1]) for _, t in loops]
        got = (min(q[0] for q in px), min(q[1] for q in px), max(q[0] for q in px), max(q[1] for q in px))
        whole = all(abs(a - b) <= 0.5 for a, b in zip(got, want))
        # upright: the highest point of the face has the page's top
        top = max(loops, key=lambda t: t[0].z)
        bottom = min(loops, key=lambda t: t[0].z)
        if turned:
            upright = top[1][0] * fd.CANVAS[0] < bottom[1][0] * fd.CANVAS[0]
        else:
            upright = top[1][1] > bottom[1][1]
        zs = [p.z for p, _ in loops]
        phis = [fd.cyl_coords(p)[0] for p, _ in loops]
        width = math.radians(max(phis) - min(phis)) * fd.cyl_coords(loops[0][0])[1]  # on the glass
        height = max(zs) - min(zs)
        aspect = width / height
        stretch = abs(aspect / fd.page_aspect(key) - 1)
        inset = (abs(width - fd.display_page(key)) < 0.001
                 and abs(height - (fd.DISPLAY_Z[1] - fd.DISPLAY_Z[0] - 2 * fd.PAGE_MARGIN)) < 0.001)
        hidden = hidden_edges(edge_points(loops, fd), tree, eyes) if tree else []
        fine = whole and upright and stretch < 0.01 and inset and not hidden
        ok &= fine
        lines.append(f"{'PASS' if fine else 'FAIL'} {key:8} canvas {tuple(round(v, 1) for v in got)} want "
                     f"{tuple(round(v, 1) for v in want)} upright {upright} face {width:.3f} x {height:.3f} m inset "
                     f"{fd.PAGE_MARGIN * 1000:.0f} mm, aspect {aspect:.3f} vs page {fd.page_aspect(key):.3f}, edge hidden from "
                     f"{len(hidden)} of {len(eyes) * EDGE_SAMPLES * 4} sightlines")
    return ok, lines


if __name__ == "__main__":
    import bpy
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import flightdeck as fd  # noqa: E402
    ok, lines = check(bpy.data.objects["tacScreen"], fd, [bpy.data.objects[n] for n in ("flightdeck_int", "band_bezel", "labels")])
    print("\n".join(lines))
    print("DISPLAY UVS", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
