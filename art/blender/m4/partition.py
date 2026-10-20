"""The finer part tree in the art: each group's built parts cut along part_splits' regions (art/blender/part_splits.py),
the blockout's table, into the pieces the blockout made objects for. A cut runs through everything in the region's
planes (skin, lining, frames, members); the faces inside go to the piece, and every closed loop the cut leaves on a
plane is filled as a break face on the airframe trim (m4/airframe.py), bright at the skin's torn edge. A band piece (a
panel round the circumference) takes only what lies within part_splits.BAND_DEPTH of the skin, so bays, wells and
tanks stay on the core; it keeps no envelope of its own, the core's whole hull standing for both in the bury pass.
Face pairs whose UVs are mirrored survive a cut where both faces land on one part (matched again by position). A
right part built as the left's mirror image (struts' sponson) gets its pieces as mirror images of the left's, since a
cut's fills on mirrored loops need not mirror."""

import math

import bmesh
from mathutils import Matrix, Vector, geometry
from mathutils.kdtree import KDTree

import part_splits as ps

from . import airframe as af
from . import surface as sf

ON_PLANE = 1e-5


def apply(bl, parts):
    """Cut every split whose source is among parts (one group's {name: surface.Part}) into its pieces, in order."""
    flagged, twins = set(), {}
    for spec in ps.pieces_in_order():
        if spec["kind"] == "promote" or spec["source"] not in parts:
            continue
        name, source = spec["name"], spec["source"]
        if name.endswith("_L") and source.endswith("_L") and parts.get(source[:-2] + "_R") and mirrored(parts[source], parts[source[:-2] + "_R"]):
            twins[name[:-2] + "_R"] = (name, source)
        if name in twins:
            left, left_src = twins[name]
            parts[source] = mirror_copy(parts[left_src], source)
            parts[name] = mirror_copy(parts[left], name)
            flagged |= {source, name}
            continue
        src = parts[source]
        if src.name not in flagged:
            flag_mirrors(src)
            flagged.add(src.name)
        hs = ps.region(bl, spec["region"])
        if spec["kind"] == "canoe":
            piece = take_shells(src, spec["name"], hs)
        elif spec["kind"] == "panel":
            piece = cut_band(bl, src, spec)
        else:
            piece = cut(bl, src, spec["name"], hs)
        parts[spec["name"]] = piece
        flagged.add(piece.name)
    for name in flagged:
        rematch_mirrors(parts[name])
    return parts


def mirrored(left, right):
    """Whether right is left's mirror image across x = 0, vertex for vertex and with the same UVs (built as a copy)."""
    lb, rb = left.bm, right.bm
    if (len(lb.verts), len(lb.faces)) != (len(rb.verts), len(rb.faces)) or left.slots != right.slots:
        return False
    if any((a.co - Vector((-b.co.x, b.co.y, b.co.z))).length > 1e-6 for a, b in zip(lb.verts, rb.verts)):
        return False
    luv, ruv = lb.loops.layers.uv.active, rb.loops.layers.uv.active
    if (luv is None) != (ruv is None):
        return False
    if luv is None:
        return True
    lb.verts.index_update()
    rb.verts.index_update()

    def corners(f, layer):  # a mirrored face runs its loops the other way round: compare by vertex
        return sorted((c.vert.index, round(c[layer].uv.x, 6), round(c[layer].uv.y, 6)) for c in f.loops)
    return all(corners(fa, luv) == corners(fb, ruv) for fa, fb in zip(lb.faces, rb.faces))


def mirror_copy(part, name):
    """part mirrored across x = 0 as a new Part called name (its faces turned to face out again)."""
    flip = Matrix.Scale(-1, 4, (1, 0, 0))
    twin = new_part(name, part.slots, part.bm.copy())
    bmesh.ops.transform(twin.bm, matrix=flip, verts=twin.bm.verts)
    for f in twin.bm.faces:
        f.normal_flip()
    if part.envelope is not None:
        twin.envelope = part.envelope.copy()
        bmesh.ops.transform(twin.envelope, matrix=flip, verts=twin.envelope.verts)
        for f in twin.envelope.faces:
            f.normal_flip()
    return twin


def flag_mirrors(part):
    """Mark the faces of part's mirrored pairs (1: takes its twin's UVs, 2: lends them), so a cut can pair them again."""
    layer = part.bm.faces.layers.int.get("mirror") or part.bm.faces.layers.int.new("mirror")
    for dst, src in part.mirror_pairs:
        if dst.is_valid and src.is_valid:
            dst[layer], src[layer] = 1, 2
    part.mirror_pairs = []


def rematch_mirrors(part):
    """Pair each flagged face with the flagged face at its mirror image across x = 0 within the same part."""
    layer = part.bm.faces.layers.int.get("mirror")
    if layer is None:
        return
    srcs = [f for f in part.bm.faces if f[layer] == 2]
    if not srcs:
        return
    tree = KDTree(len(srcs))
    for i, f in enumerate(srcs):
        tree.insert(f.calc_center_median(), i)
    tree.balance()
    for f in part.bm.faces:
        if f[layer] == 1:
            c = f.calc_center_median()
            co, i, d = tree.find(Vector((-c.x, c.y, c.z)))
            if co is not None and d < 1e-4:
                part.mirror_pairs.append((f, srcs[i]))


def take_shells(src, name, hs):
    """A piece made of src's whole closed shells lying inside the region (a flap-track fairing): no cut."""
    bm = src.bm
    bm.faces.index_update()
    tag = bm.faces.layers.int.new("piece")
    seen = set()
    for f in bm.faces:
        if f.index in seen:
            continue
        comp, stack = [], [f]
        seen.add(f.index)
        while stack:
            g = stack.pop()
            comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        if all(ps.inside(g.calc_center_median(), hs) for g in comp):
            for g in comp:
                g[tag] = 1
    piece_bm = split_off(bm)
    return new_part(name, src.slots, piece_bm)


def split_off(bm):
    """The faces bm's "piece" layer tags, moved into a new bmesh. A "FACES" delete leaves the vertices and edges only the
    deleted faces used: each side drops them, since an export's bounds read every vertex and Unity imports only the
    faces' (CenturionAuthor's import bounds check)."""
    piece_bm = bm.copy()
    for b, keep in ((piece_bm, 1), (bm, 0)):
        tag = b.faces.layers.int.get("piece")
        bmesh.ops.delete(b, geom=[f for f in b.faces if f[tag] != keep], context="FACES")
        bmesh.ops.delete(b, geom=[e for e in b.edges if not e.link_faces], context="EDGES")
        bmesh.ops.delete(b, geom=[v for v in b.verts if not v.link_faces], context="VERTS")
        b.faces.layers.int.remove(tag)
    return piece_bm


def new_part(name, slots, bm):
    p = sf.Part(name, slots)
    p.bm.free()
    p.bm = bm
    p.cls = bm.faces.layers.int.get("cls") or bm.faces.layers.int.new("cls")
    return p


SMALL_SHELL = 600  # faces: a detail (an antenna, a light, a dome) goes with whichever piece holds its middle


def shells(bm):
    """bm's connected face sets."""
    bm.faces.index_update()
    seen, out = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        comp, stack = [], [f]
        seen.add(f.index)
        while stack:
            g = stack.pop()
            comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        out.append(comp)
    return out


def cut_band(bl, src, spec):
    """A panel round the circumference: every face assigned whole (hull faces by their middle's angle on the hull's
    own columns, so the seam runs exactly along a column; the lining and members within BAND_DEPTH by theirs; a
    detail's shell by its middle), then each side's opening closed: the wall between skin and lining filled as a strip
    (the loop the skin, the lining and the end rims leave), or for a skin-only piece (a cheek) a torn lip WALL deep."""
    bm = src.bm
    slot_frame = src.slots.index(af.SLOT) if af.SLOT in src.slots else -1
    cls = src.cls
    region = spec["region"]
    skin_only = spec.get("skin_only", False)
    tag = bm.faces.layers.int.new("piece")
    for comp in shells(bm):
        hull = any(f[cls] in (sf.HULL, sf.RADOME) for f in comp)
        frame = all(f.material_index == slot_frame for f in comp)
        if not hull and not frame and len(comp) < SMALL_SHELL:
            c = sum((f.calc_center_median() for f in comp), Vector()) / len(comp)
            if ps.in_band(bl, region, c) and ps.band_depth_ok(bl, c, 0.15):
                for f in comp:
                    f[tag] = 1
            continue
        for f in comp:
            c = f.calc_center_median()
            if skin_only and f.material_index != 0:
                continue
            if ps.in_band(bl, region, c) and ps.band_depth_ok(bl, c):
                f[tag] = 1
    edge_tag = bm.edges.layers.int.new("cut")
    for e in bm.edges:
        fs = e.link_faces
        if len(fs) == 2 and fs[0][tag] != fs[1][tag]:
            e[edge_tag] = 1
    piece_bm = split_off(bm)
    piece = new_part(spec["name"], src.slots, piece_bm)
    for part in (piece, src):
        b = part.bm
        et = b.edges.layers.int.get("cut")
        edges = [e for e in b.edges if e[et] and len(e.link_faces) == 1]
        if skin_only:
            lip(bl, part, edges)
        elif edges:
            close_strip(part, edges)
            left = [e for e in b.edges if e.is_valid and e[et] and len(e.link_faces) == 1]
            lip(bl, part, left)  # what no closed loop took: a torn lip turned in, never an open skin edge
        b.edges.layers.int.remove(et)
    return piece


def torn_uv(part, faces):
    """Faces moved onto the airframe trim's torn strip: U along their longest extent, V bright at the skin's edge."""
    layer = af.uv_layer(part)
    for f in faces:
        part.tag([f], af.SLOT)
        for loop in f.loops:
            v = loop.vert
            on_skin = any(g.material_index == 0 for g in v.link_faces if g is not f)
            loop[layer].uv = ((v.co.y + v.co.x * 0.3) * af.UV_PER_M, af.strip_v("torn", 1.0 if on_skin else 0.0))


def close_strip(part, edges):
    """Fill the closed loops among a band cut's opened edges (the wall between the skin and the lining), then turn
    the shell they close outward as a whole (the fill's winding follows no neighbour)."""
    faces = bmesh.ops.holes_fill(part.bm, edges=edges, sides=0)["faces"]
    if faces:
        faces = bmesh.ops.triangulate(part.bm, faces=faces, quad_method="BEAUTY", ngon_method="BEAUTY")["faces"]
        torn_uv(part, faces)
        outward_shell(part.bm, faces)


def outward_shell(bm, seeds):
    """Make the closed shell holding seeds face outward (its signed volume positive), consistently."""
    shell, stack = set(), list(seeds)
    while stack:
        f = stack.pop()
        if f in shell or not f.is_valid:
            continue
        shell.add(f)
        for e in f.edges:
            stack += [g for g in e.link_faces if g not in shell]
    if any(not e.is_manifold for f in shell for e in f.edges):
        return
    faces = list(shell)
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    vol = sum(f.calc_center_median().dot(f.normal) * f.calc_area() for f in faces)
    if vol < 0:
        bmesh.ops.reverse_faces(bm, faces=faces)


def lip(bl, part, edges):
    """A skin-only cut's edge turned in WALL as a torn lip, toward the body's axis."""
    if not edges:
        return
    new = bmesh.ops.extrude_edge_only(part.bm, edges=edges)["geom"]
    verts = [g for g in new if isinstance(g, bmesh.types.BMVert)]
    for v in verts:
        a = ps.axis_at(bl, v.co.y + bl.Y0)
        d = Vector((a.x - v.co.x, 0.0, a.z - v.co.z)).normalized()
        v.co += d * af.WALL
    torn_uv(part, [g for g in new if isinstance(g, bmesh.types.BMFace)])


def cut(bl, src, name, hs, keep=None, envelope=True):
    """Split src (a surface.Part) along the region hs: a new Part with the faces inside (and, with keep, only those
    whose centre keep accepts), both sides' cut loops filled as break faces."""
    bm = src.bm
    for q, n in hs:
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=q, plane_no=n, dist=ON_PLANE)
    tag = bm.faces.layers.int.new("piece")
    for f in bm.faces:
        c = f.calc_center_median()
        if ps.inside(c, hs) and (keep is None or keep(c)):
            f[tag] = 1
    piece_bm = split_off(bm)
    piece = new_part(name, src.slots, piece_bm)
    for part, outward in ((piece, -1), (src, 1)):
        fill_cuts(part, hs, outward)
        leftovers(part, hs)
        for q, n in hs:  # still open on the plane: a lip turned in
            on = lambda v: abs((v.co - q).dot(n)) < 4 * ON_PLANE
            left = [e for e in part.bm.edges if len(e.link_faces) == 1 and on(e.verts[0]) and on(e.verts[1])
                    and e.link_faces[0].material_index != (part.slots.index(af.SLOT) if af.SLOT in part.slots else -1)]
            lip(bl, part, left)
    if envelope and src.envelope is not None:
        env_piece = src.envelope.copy()
        for q, n in hs:
            for b in (src.envelope, env_piece):
                bmesh.ops.bisect_plane(b, geom=b.verts[:] + b.edges[:] + b.faces[:], plane_co=q, plane_no=n,
                                       dist=ON_PLANE)
        bmesh.ops.delete(env_piece, geom=[f for f in env_piece.faces if not ps.inside(f.calc_center_median(), hs)],
                         context="FACES")
        bmesh.ops.delete(src.envelope, geom=[f for f in src.envelope.faces if ps.inside(f.calc_center_median(), hs)],
                         context="FACES")
        for b in (src.envelope, env_piece):
            edges = [e for e in b.edges if len(e.link_faces) == 1]
            if edges:
                faces = bmesh.ops.holes_fill(b, edges=edges, sides=0)["faces"]
                bmesh.ops.triangulate(b, faces=faces)
        piece.envelope = env_piece
    return piece


def loops_on(bm, q, n):
    """Closed boundary loops of bm whose edges all lie on the plane (q, n), as vertex lists."""
    on = lambda v: abs((v.co - q).dot(n)) < 4 * ON_PLANE
    edges = [e for e in bm.edges if len(e.link_faces) == 1 and on(e.verts[0]) and on(e.verts[1])]
    link = {}
    for e in edges:
        a, b = e.verts
        link.setdefault(a, []).append(b)
        link.setdefault(b, []).append(a)
    seen, loops = set(), []
    for start in link:
        if start in seen or len(link[start]) != 2:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [v for v in link[cur] if v is not prev]
            if not nxt or len(link[cur]) != 2:
                loop = None
                break
            prev, cur = cur, nxt[0]
            if cur is start:
                break
            if cur in seen:
                loop = None
                break
            loop.append(cur)
            seen.add(cur)
        if loop and len(loop) >= 3:
            loops.append(loop)
    return loops


def fill_cuts(part, hs, outward):
    """Fill the closed loops each region plane left open in part: an even-odd fill of all the loops on a plane (so a
    wall between the skin and the lining fills as a ring), facing out of the part (outward times the plane's normal).
    U runs along the loop, V is bright (1) at the skin's edge."""
    bm = part.bm
    skin = part.slots.index(part.slots[0])
    for q, n in hs:
        loops = loops_on(bm, q, n)
        if not loops:
            continue
        e1 = n.orthogonal().normalized()
        e2 = n.cross(e1)
        flat = [[((v.co - q).dot(e1), (v.co - q).dot(e2)) for v in loop] for loop in loops]
        verts = [v for loop in loops for v in loop]
        on_skin = {v for v in verts if any(f.material_index == skin for f in v.link_faces)}
        tris = geometry.tessellate_polygon([[Vector((x, y, 0)) for x, y in lp] for lp in flat])
        pts2 = [p for lp in flat for p in lp]
        for tri in tris:
            c = tuple(sum(pts2[i][k] for i in tri) / 3 for k in (0, 1))
            if sum(point_in(c, lp) for lp in flat) % 2 == 0:
                continue
            vs = [verts[i] for i in tri]
            if len(set(vs)) < 3:
                continue
            uv = [((v.co - q).dot(e1) * af.UV_PER_M, af.strip_v("torn", 1.0 if v in on_skin else 0.0)) for v in vs]
            f = af.face(part, vs, uv)
            if f is not None:
                af.orient(f, n * outward)


def leftovers(part, hs):
    """Close what the even-odd fill left open on the cut's planes (a loop touching another at a vertex)."""
    skin_side = [i for i, s in enumerate(part.slots) if s != af.SLOT]
    for q, n in hs:
        on = lambda v: abs((v.co - q).dot(n)) < 4 * ON_PLANE
        edges = [e for e in part.bm.edges if len(e.link_faces) == 1 and on(e.verts[0]) and on(e.verts[1])
                 and e.link_faces[0].material_index in skin_side]
        if edges:
            close_strip(part, edges)


def point_in(p, loop):
    x, y = p
    inside = False
    for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (x1 - x0) * (y - y0) / (y1 - y0):
            inside = not inside
    return inside


def hull_outward(bl, part):
    """Turn every shell of part whose body skin (surface.HULL and RADOME faces) mostly faces the body's axis. A band cut
    can leave a thin strip of skin and lining that a torn lip keeps open (fuselage_R's crown beside the AWACS well),
    and an open shell's volume says nothing about which way it faces; the skin's side of the axis does."""
    bm = part.bm
    bm.normal_update()
    for comp in shells(bm):
        if hull_facing(bl, comp, part.cls) < 0:
            bmesh.ops.reverse_faces(bm, faces=comp)


def hull_facing(bl, faces, cls):
    """How much of faces' body skin faces away from the body's axis, area-weighted (negative: it faces in; 0: none)."""
    score = 0.0
    for f in faces:
        if f[cls] in (sf.HULL, sf.RADOME):
            c = f.calc_center_median()
            score += (c - ps.axis_at(bl, c.y + bl.Y0)).dot(f.normal) * f.calc_area()
    return score


def piece_names(group_parts):
    """The pieces part_splits cuts from a group's parts (the art builds them), in order."""
    names, have = [], set(group_parts)
    for spec in ps.pieces_in_order():
        if spec["kind"] != "promote" and spec["source"] in have:
            names.append(spec["name"])
            have.add(spec["name"])
    return names
