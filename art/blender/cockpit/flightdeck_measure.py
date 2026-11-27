"""Eye-grid and display-ray measurements for a Centurion flight deck in Blender, the same code for today's interior and
the blockout, so the two tables compare like for like.

Frame: the composite's (Blender X is the aircraft's left, the nose to -Y, Z up); stations s = y + Y0. Angles from an
eye: az positive to the pilot's RIGHT (toward the commander), el positive up, 0 along the nose line.

- eye_grid: one ray per degree, az -90..+90, el -45..+45, from the eye; each ray's first hit over 3 cm is classed
  glass (an inner pane: the world through real glass), band (the camera-feed sheet), display (a lit page), opaque
  (anything else in the interior) or leak (nothing: should never happen). Where the first hit is opaque, the ray is
  also cast against the exterior alone, to tell glass the interior covers from skin.
- glass_edges: per az, the elevations at which rays leave through the exterior glass with no interior present (the
  locked nose and panes alone), lowest and highest.
- display_rays: per display quad, a 5 x 5 grid of rays from the eye to points 3% to 97% across it; a ray is blocked
  when anything else in the interior is hit first. Also distance, centre az and el, angular size, metres, px/m."""

import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

Y0 = 22.475
PILOT_EYE = (0.55, 6.55, 5.00)  # x (left +), station, z
COMMANDER_EYE = (-0.55, 6.55, 5.00)


def P(s, x, z):
    return Vector((x, s - Y0, z))


def eye_vec(eye):
    return P(eye[1], eye[0], eye[2])


def direction(az, el):
    a, e = math.radians(az), math.radians(el)
    return Vector((-math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def angles_of(v):
    v = v.normalized()
    return math.degrees(math.atan2(-v.x, -v.y)), math.degrees(math.asin(max(-1, min(1, v.z))))


def tree(objs, face_filter=None):
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        for p in me.polygons:
            if face_filter is None or face_filter(o, p):
                polys.append([base + i for i in p.vertices])
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys, epsilon=0.0) if polys else None


def first(trees, origin, d, start=0.03, far=6.0):
    best = None
    o = origin + d * start
    for name, t in trees.items():
        if t is None:
            continue
        h = t.ray_cast(o, d, far - start)
        if h[0] is not None and (best is None or h[3] < best[1]):
            best = (name, h[3] + start)
    return best


def exterior_trees(exterior_objs):
    """The nose shell and its glass, split by material: (glass tree, skin tree)."""
    glass = tree(exterior_objs, lambda o, p: o.material_slots and "glass" in o.material_slots[p.material_index].name.lower()
                 and "int" not in o.material_slots[p.material_index].name.lower())
    skin = tree(exterior_objs, lambda o, p: not (o.material_slots and "glass" in o.material_slots[p.material_index].name.lower()))
    return glass, skin


def glass_edges(eye, ext_glass, ext_skin, az_range=range(-90, 91, 2)):
    out = {}
    trees = {"glass": ext_glass, "skin": ext_skin}
    for az in az_range:
        els = [el / 2 for el in range(-90, 121) if (first(trees, eye, direction(az, el / 2), 0.03, 8.0) or ("glass",))[0] == "glass"]
        out[az] = (min(els), max(els)) if els else None
    return out


def eye_grid(eye, cats, ext_glass, ext_skin, az=(-90, 90), el=(-45, 45)):
    """cats: {class: tree}. Returns the class grid (el rows, az cols) and, for opaque cells, whether glass lies behind."""
    azs, els = np.arange(az[0], az[1] + 1), np.arange(el[0], el[1] + 1)
    grid = np.empty((len(els), len(azs)), dtype=object)
    covered = np.zeros(grid.shape, dtype=bool)
    ext = {"glass": ext_glass, "skin": ext_skin}
    for i, e in enumerate(els):
        for j, a in enumerate(azs):
            d = direction(a, e)
            h = first(cats, eye, d)
            grid[i, j] = h[0] if h else "leak"
            if grid[i, j] == "opaque":
                x = first(ext, eye, d, 0.03, 8.0)
                covered[i, j] = x is not None and x[0] == "glass"
    return azs, els, grid, covered


def outside(grid):
    return (grid == "glass") | (grid == "band")


def grid_summary(azs, els, grid, covered, box=((-45, 45), (-20, 30))):
    sel = np.ix_((els >= box[1][0]) & (els <= box[1][1]), (azs >= box[0][0]) & (azs <= box[0][1]))
    g, c = grid[sel], covered[sel]
    n = g.size
    share = {k: round(100.0 * float((g == k).sum()) / n, 1) for k in ("glass", "band", "display", "opaque", "leak")}
    share["opaque_over_glass"] = round(100.0 * float(c.sum()) / n, 1)

    def runs(col):
        out, start, prev = [], None, None
        for e, k in zip(els, col):
            if start is None or k != prev:
                if start is not None:
                    out.append("%s %d..%d" % (prev, start, e - 1))
                start, prev = e, k
        out.append("%s %d..%d" % (prev, start, els[-1]))
        return [r for r in out if not r.startswith("opaque") or True]
    columns = {}
    for a in (-30, -15, 0, 15, 30, 45, 60):
        j = int(np.where(azs == a)[0][0])
        columns[a] = runs(grid[:, j])
    return {"box_az_el": box, "share_pct": share, "columns": columns}


def display_rays(eye, displays, blockers):
    """displays: [(name, page, (a, b, c, d) corners in order round the quad, page px (w, h))]; blockers: {name: tree}
    of everything else. Returns one row per display."""
    rows = []
    for name, page, quad, px in displays:
        if callable(quad):  # a sampler (fu, fv) -> point, for curved faces
            at = quad
            quad = (at(0, 0), at(1, 0), at(1, 1), at(0, 1))
        else:
            qa, qb, qc, qd = quad

            def at(fu, fv, qa=qa, qb=qb, qc=qc, qd=qd):
                return qa.lerp(qb, fu).lerp(qd.lerp(qc, fu), fv)
        a, b, c, d = quad
        blocked = 0
        for fu in np.linspace(0.03, 0.97, 5):
            for fv in np.linspace(0.03, 0.97, 5):
                ray = at(fu, fv) - eye
                h = first(blockers, eye, ray.normalized(), 0.03, ray.length - 0.004)
                blocked += h is not None
        centre = at(0.5, 0.5)
        w, h_ = (b - a).length, (d - a).length
        az, el = angles_of(centre - eye)
        corner_angles = [angles_of(p - eye) for p in quad]
        span_az = max(x[0] for x in corner_angles) - min(x[0] for x in corner_angles)
        span_el = max(x[1] for x in corner_angles) - min(x[1] for x in corner_angles)
        n = (b - a).cross(d - a).normalized()
        incidence = math.degrees(math.acos(min(1.0, abs(n.dot((eye - centre).normalized())))))
        rows.append({"name": name, "page": page, "dist_m": round((centre - eye).length, 3), "az": round(az, 1),
                     "el": round(el, 1), "span_deg": [round(span_az, 1), round(span_el, 1)],
                     "size_m": [round(w, 3), round(h_, 3)],
                     "px_per_m": round(px[0] / w) if px else None, "incidence_deg": round(incidence, 1),
                     "blocked_of_25": blocked})
    return rows


def grid_image(azs, els, grid, covered, path, scale=4):
    """The eye grid as a picture: glass sky blue, band teal, display green, opaque grey (dark red where it covers
    glass), leak magenta; az left to right, el bottom to top. Blender's Python has no PIL: the pixels go to path.npy and
    grids_to_png.py writes the PNGs outside Blender."""
    colours = {"glass": (120, 170, 220), "band": (60, 160, 150), "display": (40, 200, 60), "opaque": (90, 90, 90),
               "leak": (255, 0, 255)}
    img = np.zeros((len(els), len(azs), 3), dtype=np.uint8)
    for i in range(len(els)):
        for j in range(len(azs)):
            img[len(els) - 1 - i, j] = (150, 60, 60) if covered[i, j] else colours[grid[i, j]]
    for a in range(-90, 91, 15):  # az ticks
        j = int(np.where(azs == a)[0][0])
        img[:, j] = img[:, j] // 2 + 60
    i0 = len(els) - 1 - int(np.where(els == 0)[0][0])
    img[i0, :] = (255, 255, 255)
    np.save(str(path) + ".npy", img)


def leak_sphere(eye, cats, step=3):
    """Directions over the whole sphere (step degrees) whose ray from the eye meets nothing in the interior: in cockpit
    view the nose is hidden, so each is the world seen past the cockpit with no glass in the way."""
    found = []
    for el in range(-87, 88, step):
        for az in range(-180, 180, step):
            if first(cats, eye, direction(az, el)) is None:
                found.append((az, el))
    return found
