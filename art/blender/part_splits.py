"""The finer part tree (damage stage 2): the pieces the Centurion comes apart into besides its 39 step 6.1 parts, in
one table both passes read. The blockout (build_centurion.build) applies it after its colliders: a cut splits a part's
mesh and collider pieces along a plane (a convex piece cut by a plane stays convex) and fills the cut flat; a panel
lays a thin shell on the skin with its own collider pieces and leaves its core whole, so every core keeps the shape
the flight model is measured on (CenturionAuthor's PartMeshes.Shape) and a panel adds none. The art pass
(art/blender/m4/partition.py) cuts the detailed meshes along the same regions, panels included, with break faces.

A region is a list of half-spaces (point, normal), world space at rest (stages retracted): a point is in it when it
lies on the normal's side of every plane. An angle band ("band") is a wedge round the body's axis between two angles
from the top (positive toward +X, the left wing), within a section's stations; its pieces hold the skin, the lining
and the members within BAND_DEPTH of the skin, and everything deeper (bays, wells, tanks) stays on the core."""

import math

from mathutils import Vector

BAND_DEPTH = 0.3  # m from the skin: what a panel takes with it (skin, lining, frames, longerons, systems runs)
PANEL_SHELL = 0.05  # the blockout panel's thickness under the skin
PANEL_COLLIDER_ARC = 24.0  # degrees of girth per panel collider piece (a convex piece of a curved panel bows inward)
# A band's collider pieces start this far inside the body's true surface: inside the art's 64-sided skin, and short of
# the cores' pieces (inset COL_INSET from the blockout's 32-sided facets), so a hit on a panel's skin lands on it first.
PANEL_COL_INSET = 0.023
PANEL_COLLIDER_RUN = 2.0  # m of body per panel collider piece

# kind: cut (split along the region), panel (a band: overlay at the blockout, split in the art), promote (an existing
# mesh becomes a part), canoe (a flap-track fairing). source: the part (or mesh) it comes from; parent: the part it
# joins; moves: parts and surfaces that re-join it; braces: extra joints (CenturionAuthor) and the parts it may touch.
# mass_kg is taken from the source's (build_centurion S6_MASS); fuselage cores keep the section's name, systems and tank.
# visual: a piece the game draws but does not damage (CenturionAuthor keeps it a mesh on its parent, with the mass): the
# spine cover's lids, which the AWACS beam hides and whose colliders would stand in its envelope.
SPLITS = (
    {"name": "fuselage_F2", "kind": "cut", "source": "fuselage_F", "parent": "fuselage_M", "region": ("station_gt", 12.0),
     "moves": {"fuselage_F": "fuselage_F2"}, "braces": ("wingfairing",), "mass_kg": 4250},
    {"name": "tail_end", "kind": "cut", "source": "tailcone", "parent": "tailcone", "region": ("station_gt", 38.3),
     "moves": {"laser_turret": "tail_end", "radar_R_fairing": "tail_end"}, "braces": (), "mass_kg": 2180},
    *({"name": f"sponson_tail_{s}", "kind": "cut", "source": f"sponson_{s}", "parent": f"sponson_{s}",
       "region": ("station_gt", 28.6), "moves": {}, "braces": ("fuselage_R", "tailcone"), "mass_kg": 1120} for s in "LR"),
    *({"name": f"wing_outer_{s}", "kind": "cut", "source": f"wing_root_{s}", "parent": f"wing_root_{s}",
       "region": ("x_out", 10.7, 1 if s == "L" else -1),
       "moves": {f"wing_tele1_{s}": f"wing_outer_{s}", f"aileron_{s}": f"wing_outer_{s}",
                 f"spoiler_{s}": f"wing_outer_{s}", f"strut_outer_{s}": f"wing_outer_{s}"},
       "braces": (f"strut_outer_{s}",), "mass_kg": 5625} for s in "LR"),
    *({"name": f"wing_tip_{s}", "kind": "cut", "source": f"wing_tele2_{s}", "parent": f"wing_tele2_{s}",
       "region": ("tip", 0.05, 1 if s == "L" else -1), "moves": {}, "braces": (), "mass_kg": 240} for s in "LR"),
    *({"name": f"vtail_tip_{s}", "kind": "cut", "source": f"vtail_{s}", "parent": f"vtail_{s}",
       "region": ("vtail_split", 1 if s == "L" else -1), "moves": {f"ruddervator_{s}2": f"vtail_tip_{s}"},
       "braces": (), "mass_kg": 990} for s in "LR"),
    {"name": "wingfairing", "kind": "promote", "source": "wingfairing", "parent": "fuselage_M", "region": None,
     "moves": {}, "braces": ("fuselage_F2", "wing_root_L", "wing_root_R"), "mass_kg": 600, "from": "fuselage_M"},
    {"name": "spine_cover", "kind": "promote", "source": "spine_cover", "parent": "fuselage_R", "region": None,
     "moves": {}, "braces": ("spine_cover_A",), "mass_kg": 150, "from": "fuselage_R", "visual": True},
    {"name": "spine_cover_A", "kind": "cut", "source": "spine_cover", "parent": "fuselage_R", "region": ("station_gt", 29.8),
     "moves": {}, "braces": ("spine_cover",), "mass_kg": 150, "from": "fuselage_R", "visual": True},
    # round the circumference (angles from the top, +X positive); stations bound the band within its section
    # fuselage_F in halves, not quarters: a crown seam would run through the refuelling slipway and the crown's fittings
    {"name": "fuselage_F_upper", "kind": "panel", "source": "fuselage_F", "parent": "fuselage_F",
     "region": ("band", -112.5, 112.5, 7.0, 12.0), "moves": {}, "braces": ("fuselage_F2_upper", "nose"), "mass_kg": 1700},
    # the cheeks: skin panels on the upper half (a skin piece, no lining: a torn lip round the hole and the panel)
    {"name": "cheek_L", "kind": "panel", "source": "fuselage_F_upper", "parent": "fuselage_F_upper",
     "region": ("band", 62.0, 100.0, 7.7, 11.6), "moves": {}, "braces": ("fuselage_F",), "mass_kg": 150, "skin_only": True},
    {"name": "cheek_R", "kind": "panel", "source": "fuselage_F_upper", "parent": "fuselage_F_upper",
     "region": ("band", -100.0, -62.0, 7.7, 11.6), "moves": {}, "braces": ("fuselage_F",), "mass_kg": 150, "skin_only": True},
    {"name": "fuselage_F2_upper", "kind": "panel", "source": "fuselage_F2", "parent": "fuselage_F2",
     "region": ("band", -112.5, 112.5, 12.0, 17.0), "moves": {},
     "braces": ("fuselage_F_upper", "fuselage_M_flank_L", "fuselage_M_flank_R", "wingfairing"),
     "mass_kg": 1300},
    *({"name": f"fuselage_M_flank_{s}", "kind": "panel", "source": "fuselage_M", "parent": "fuselage_M",
       "region": ("band", 45.0, 112.5, 17.0, 25.0) if s == "L" else ("band", -112.5, -45.0, 17.0, 25.0), "moves": {},
       "braces": (f"wing_root_{s}", f"sponson_{s}", "fuselage_F2_upper"), "mass_kg": 1000} for s in "LR"),
    *({"name": f"fuselage_R_upper_{s}", "kind": "panel", "source": "fuselage_R", "parent": "fuselage_R",
       "region": ("band", 22.5, 112.5, 25.0, 33.0) if s == "L" else ("band", -112.5, -22.5, 25.0, 33.0), "moves": {},
       "braces": (f"fuselage_M_flank_{s}", "tailcone_upper", f"sponson_{s}"), "mass_kg": 1400} for s in "LR"),
    {"name": "tailcone_upper", "kind": "panel", "source": "tailcone", "parent": "tailcone",
     "region": ("band", -112.5, 112.5, 33.0, 38.3), "moves": {"vtail_L": "tailcone_upper", "vtail_R": "tailcone_upper"},
     "braces": ("fuselage_R_upper_L", "fuselage_R_upper_R"), "mass_kg": 900},
    {"name": "tail_end_upper", "kind": "panel", "source": "tail_end", "parent": "tail_end",
     "region": ("band", -112.5, 112.5, 38.3, 43.53), "moves": {}, "braces": ("tailcone_upper",), "mass_kg": 700},
    *({"name": f"flap_track_{s}{k}", "kind": "canoe", "source": f"wing_root_{s}", "parent": f"wing_root_{s}",
       "region": ("canoe", x, 1 if s == "L" else -1), "moves": {}, "braces": (f"flap_{s}{k}",), "mass_kg": 120}
      for s in "LR" for k, x in ((1, 4.3), (2, 9.8))),
)
BY_NAME = {s["name"]: s for s in SPLITS}
VISUAL = tuple(s["name"] for s in SPLITS if s.get("visual"))  # meshes only: no collider pieces
CANOE_HALF_W, CANOE_DEPTH = 0.2, 0.5  # the art's flap-track fairing (m4/wing.py CANOE_HALF_W, CANOE_DEPTH)


def axis_at(bl, s):
    """The body's axis at station s: the centre of its section."""
    w, top, bot = bl.fus_profile(min(max(s, 0.01), bl.LENGTH))
    return Vector((0.0, bl.st(s), (top + bot) / 2))


def radial(deg):
    a = math.radians(deg)
    return Vector((math.sin(a), 0.0, math.cos(a)))


def band_planes(bl, lo, hi, s0, s1):
    """Half-spaces of the wedge between angles lo and hi about the axis through stations s0 and s1."""
    a0, a1 = axis_at(bl, s0), axis_at(bl, s1)
    ax = (a1 - a0).normalized()
    out = []
    for edge, inward in ((lo, lo + 90.0), (hi, hi - 90.0)):
        d = radial(edge)
        d = (d - ax * d.dot(ax)).normalized()
        n = ax.cross(d).normalized()
        if n.dot(radial(inward)) < 0:
            n = -n
        out.append((a0.copy(), n))
    return out


def region(bl, spec, objs=None):
    """The half-spaces of a split's region. objs: the scene's parts (the tip's cut is measured on its stage)."""
    kind = spec[0]
    if kind == "station_gt":
        return [(Vector((0, bl.st(spec[1]), 0)), Vector((0, 1, 0)))]
    if kind == "x_out":
        _, x, side = spec
        return [(Vector((side * x, 0, 0)), Vector((side, 0, 0)))]
    if kind == "tip":  # the last stage's end outside the fixed wing when retracted, outboard of its cuff
        _, margin, side = spec
        cuff = abs(bl.qc_at(side, bl.XI_ROOT_TIP - bl.TELE[1][3] + bl.TIP_NECK).x)
        return [(Vector((side * (cuff + margin), 0, 0)), Vector((side, 0, 0)))]
    if kind == "vtail_split":
        side = spec[1]
        span_dir = Vector((side * math.cos(bl.VTAIL_DIHEDRAL), 0, math.sin(bl.VTAIL_DIHEDRAL)))
        root_le = bl.vtail_section(side, 0.0)[1]
        return [(root_le + span_dir * bl.SPLIT_TAIL["split"], span_dir)]
    if kind == "band":
        _, lo, hi, s0, s1 = spec
        return band_planes(bl, lo, hi, s0, s1) + [(Vector((0, bl.st(s0), 0)), Vector((0, 1, 0))),
                                                  (Vector((0, bl.st(s1), 0)), Vector((0, -1, 0)))]
    if kind == "canoe":
        _, x, side = spec
        return [(Vector((side * (x - CANOE_HALF_W - 0.05), 0, 0)), Vector((side, 0, 0))),
                (Vector((side * (x + CANOE_HALF_W + 0.05), 0, 0)), Vector((-side, 0, 0)))]
    raise ValueError(f"unknown region {spec}")


def param_deg(bl, p):
    """p's angle round the body as fus_point's parameter (the hull's columns), from the top, +X positive."""
    s = p.y + bl.Y0
    w, top, bot = bl.fus_profile(min(max(s, 0.01), bl.LENGTH))
    zc, h = (top + bot) / 2, (top - bot) / 2
    return math.degrees(math.atan2(p.x / w, (p.z - zc) / h))


def in_band(bl, region_spec, p):
    """Whether p lies in a band region: between its stations and, round the body, between its angles."""
    _, lo, hi, s0, s1 = region_spec
    s = p.y + bl.Y0
    return s0 - 1e-6 <= s <= s1 + 1e-6 and lo - 1e-6 <= param_deg(bl, p) <= hi + 1e-6


def inside(p, halfspaces, eps=1e-6):
    return all((p - q).dot(n) >= -eps for q, n in halfspaces)


def band_depth_ok(bl, p, depth=BAND_DEPTH):
    """Whether p lies within depth of the body's skin (a band piece's own depth)."""
    s = p.y + bl.Y0
    w, top, bot = bl.fus_profile(min(max(s, 0.01), bl.LENGTH))
    zc, h = (top + bot) / 2, (top - bot) / 2
    r = math.hypot(p.x / w, (p.z - zc) / h)
    scale = math.hypot(p.x, p.z - zc) / max(r, 1e-6)  # the skin's distance from the axis in p's direction
    return r > 1e-6 and math.hypot(p.x, p.z - zc) > scale - depth


def pieces_in_order():
    """Splits ordered so a source exists before its pieces are cut from it (a cheek from its upper quarter)."""
    done, out = set(), []
    names = {s["name"] for s in SPLITS if s["kind"] != "promote"}
    pending = list(SPLITS)
    while pending:
        for s in list(pending):
            if s["source"] not in names or s["source"] in done or s["source"] == s["name"]:
                out.append(s)
                done.add(s["name"])
                pending.remove(s)
    return out


def mass_moves():
    """{part: kg change}: each piece's mass and what its source (or "from") gives up."""
    out = {}
    for s in SPLITS:
        out[s["name"]] = out.get(s["name"], 0.0) + s["mass_kg"]
        giver = s.get("from", s["source"])
        if giver != s["name"]:
            out[giver] = out.get(giver, 0.0) - s["mass_kg"]
    return out


# ---------- the blockout ----------
def apply_blockout(bl, objs, world, coll_colliders, mats, col_report):
    """Apply SPLITS to the blockout scene (after build_colliders): new part objects with their meshes, collider
    pieces and joints, their world matrices added to world; col_report (build_colliders') re-read for every piece the
    splits made or moved. Returns a report per piece."""
    import bpy
    bpy.context.view_layer.update()  # the collider pieces were just made: their world matrices are stale until now
    related = relations(bl, objs)
    inherited = {}  # collider piece name: the report entry of the piece it was cut from
    report = {}
    for spec in pieces_in_order():
        name, kind = spec["name"], spec["kind"]
        if kind == "promote":
            obj = objs[name]
            got = colliders_of(obj, coll_colliders)
            if spec.get("visual"):
                for c in got:
                    bpy.data.objects.remove(c)
            elif not got:
                if name == "wingfairing":
                    fairing_colliders(bl, obj, coll_colliders)
                else:
                    hull_collider(obj, coll_colliders, bl)
            obj["bonded_to"] = ",".join(sorted(set(braces_of(spec)) | bonds_of(obj)))
            report[name] = {"kind": kind, "colliders": len(colliders_of(obj, coll_colliders))}
            continue
        src = objs[spec["source"]]
        if kind == "cut":
            hs = region(bl, spec["region"], objs)
            obj = split_mesh(bl, src, name, hs, mats)
            moved = split_colliders(src, obj, hs, coll_colliders, col_report, inherited)
        elif kind == "panel":
            obj = panel_mesh(bl, spec, src, mats)
            moved = panel_colliders(bl, spec, obj, coll_colliders)
        else:
            obj = canoe_mesh(bl, spec, src, mats)
            moved = hull_collider(obj, coll_colliders, bl)
        if spec.get("visual"):  # a mesh only, as its source
            for c in colliders_of(src, coll_colliders) + colliders_of(obj, coll_colliders):
                bpy.data.objects.remove(c)
            moved = None
        elif not moved and kind == "cut":  # a piece no collider reached (a tip): the inset hull of its own mesh
            moved = hull_collider(obj, coll_colliders, bl)
        objs[name] = obj
        world[name] = obj.matrix_world.copy()
        parent = objs[spec["parent"]]
        reparent(obj, parent)
        for child, new_parent in spec["moves"].items():
            if child in objs:  # it may still touch the part it left
                c = objs[child]
                c["bonded_to"] = ",".join(sorted(bonds_of(c) | {spec["source"]}))
                reparent(c, objs[new_parent] if new_parent in objs else obj)
        obj["bonded_to"] = ",".join(braces_of(spec))
        report[name] = {"kind": kind, "tris": sum(len(p.vertices) - 2 for p in obj.data.polygons), "colliders": moved}
    bpy.context.view_layer.update()
    bond_pieces(objs, related)
    collider_report(bl, objs, coll_colliders, col_report, inherited)
    return report


def braces_of(spec):
    """A piece's declared bonds, a hinged surface named by its empty also by its mesh."""
    out = []
    for b in spec["braces"]:
        out += [b, b + "_visible"] if b.startswith(("flap_", "aileron_", "spoiler_", "ruddervator_")) else [b]
    return out


def bonds_of(obj):
    return {b for b in obj.get("bonded_to", "").split(",") if b}


def root_source(name):
    while name in BY_NAME and BY_NAME[name]["source"] != name:
        name = BY_NAME[name]["source"]
    return name


BODY = ("fuselage_F", "fuselage_M", "fuselage_R", "tailcone")  # sources whose pieces are one skin, all touching


def relations(bl, objs):
    """Before any split: each part's neighbours it may touch (parent, children, declared bonds either way)."""
    out = {n: set() for n in objs}
    for n, o in objs.items():
        p = bl.joint_parent(o)
        if p is not None:
            out[n].add(p.name)
            out.setdefault(p.name, set()).add(n)
        for b in bonds_of(o):
            out[n].add(b)
            out.setdefault(b, set()).add(n)
    return out


def bond_pieces(objs, related):
    """A piece may touch whatever its source could (the source itself, its other pieces, and the pieces of every part
    its source touched), and the body's pieces all touch one another; the bonds go on the pieces, which jointed()
    reads either way."""
    pieces = [s["name"] for s in SPLITS if s["name"] in objs]
    body = [n for n in objs if n in BODY or (n in BY_NAME and root_source(n) in BODY)]
    body += [n for n in ("wingfairing", "spine_cover", "spine_cover_A") if n in objs]
    for piece in pieces:
        src = root_source(piece)
        near = related.get(src, set()) | {src}
        others = {n for n in objs if n != piece and (root_source(n) in near or n in near)}
        o = objs[piece]
        o["bonded_to"] = ",".join(sorted(bonds_of(o) | others))
    for a in body:
        o = objs[a]
        o["bonded_to"] = ",".join(sorted(bonds_of(o) | {b for b in body if b != a}))


def collider_report(bl, objs, coll, col_report, inherited):
    """build_colliders' report entries for the collider pieces as they stand: kept where a piece is untouched, re-read
    (size and depth inside its part's skin, or for a panel inside its section's) where the splits made it."""
    from mathutils.bvhtree import BVHTree
    trees = {}

    def tree(name):
        if name not in trees:
            body = BY_NAME[name]["source"] if name in BY_NAME and BY_NAME[name]["kind"] == "panel" else name
            while body in BY_NAME and BY_NAME[body]["kind"] == "panel":
                body = BY_NAME[body]["source"]
            o = objs[body]
            v, p = bl.world_mesh(o)
            trees[name] = BVHTree.FromPolygons(v, p)
        return trees[name]

    live = {o.name: o for o in coll.objects if o.parent is not None}
    for n in [n for n in col_report if n not in live]:
        del col_report[n]
    for n, o in live.items():
        owner = o.parent.name
        if (owner in BY_NAME and BY_NAME[owner]["kind"] == "panel") or owner.startswith("spine_cover"):
            pts = [o.matrix_world @ v.co for v in o.data.vertices] + [o.matrix_world @ q.center for q in o.data.polygons]
            d = [analytic_depth(bl, q) for q in pts]
            col_report[n] = {"owner": owner, "verts": len(o.data.vertices), "tris": len(o.data.polygons),
                             "min_depth_m": round(min(d), 4), "vertex_depth_m": [round(min(d), 4), round(max(d), 4)],
                             "sliver_rings_skipped": 0, "measured_on": "the body's true surface (a skin band)"}
            continue
        if n in inherited:
            col_report[n] = dict(inherited[n], owner=o.parent.name, verts=len(o.data.vertices), tris=len(o.data.polygons))
            continue
        if n in col_report and col_report[n]["owner"] == o.parent.name:
            continue
        verts = [o.matrix_world @ v.co for v in o.data.vertices]
        centres = [o.matrix_world @ p.center for p in o.data.polygons]
        t = tree(o.parent.name)
        vd = [bl.signed_depth(t, v) for v in verts]
        cd = [bl.signed_depth(t, c) for c in centres]
        col_report[n] = {"owner": o.parent.name, "verts": len(verts), "tris": len(o.data.polygons),
                         "min_depth_m": round(min(vd + cd), 4), "vertex_depth_m": [round(min(vd), 4), round(max(vd), 4)],
                         "sliver_rings_skipped": 0}


def analytic_depth(bl, p):
    """How far inside the body's true surface (fus_profile's section, chine ignored) p lies, along its radius."""
    s = p.y + bl.Y0
    w, top, bot = bl.fus_profile(min(max(s, 0.01), bl.LENGTH))
    zc, h = (top + bot) / 2, (top - bot) / 2
    r = math.hypot(p.x, p.z - zc)
    rn = math.hypot(p.x / w, (p.z - zc) / h)
    return r / max(rn, 1e-9) - r if rn > 1e-9 else min(w, h)


def reparent(obj, parent):
    """Re-join obj to parent keeping its place; a stage's rest location (build_centurion.set_extension) is re-read in
    its new parent's frame, since this runs at rest."""
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse.identity()
    obj.matrix_basis = parent.matrix_world.inverted() @ world
    if "rest_location" in obj:
        obj["rest_location"] = list(obj.location)


def new_object(name, me, origin, like):
    import bpy
    from mathutils import Matrix
    obj = bpy.data.objects.new(name, me)
    for c in like.users_collection:
        c.objects.link(obj)
    obj.matrix_world = Matrix.Translation(origin)
    return obj


def cut_bmesh(bm, hs):
    """Bisect bm by every plane of hs (cuts only) and return its faces inside the region."""
    import bmesh
    for q, n in hs:
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=q, plane_no=n, dist=1e-6)
    return [f for f in bm.faces if inside(f.calc_center_median(), hs)]


def close_holes(bm, mat_index):
    """Fill every open boundary loop flat (a blockout cut), on mat_index."""
    import bmesh
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    if not edges:
        return []
    faces = bmesh.ops.holes_fill(bm, edges=edges, sides=0)["faces"]
    tris = bmesh.ops.triangulate(bm, faces=faces)["faces"] if faces else []
    for f in tris:
        f.material_index = mat_index
    return tris


def split_mesh(bl, src, name, hs, mats):
    """Cut src's mesh by the region hs: the faces inside become a new object, both sides closed flat."""
    import bmesh
    import bpy
    from mathutils import Matrix
    mw = src.matrix_world
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.transform(mw)
    tag = bm.faces.layers.int.new("piece")
    for f in cut_bmesh(bm, hs):
        f[tag] = 1
    piece = bm.copy()
    ptag = piece.faces.layers.int.get("piece")
    bmesh.ops.delete(piece, geom=[f for f in piece.faces if not f[ptag]], context="FACES")
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[tag]], context="FACES")
    for b in (bm, piece):
        b.faces.layers.int.remove(b.faces.layers.int.get("piece"))
    struct = material_index(src.data, bl.STRUCT)
    q, n = hs[0]
    on_cut = [v.co.copy() for v in piece.verts if abs((v.co - q).dot(n)) < 1e-4]
    for b in (bm, piece):
        close_holes(b, struct)
        bmesh.ops.recalc_face_normals(b, faces=b.faces)
    centre = sum((v.co for v in piece.verts), Vector()) / max(len(piece.verts), 1)
    origin = sum(on_cut, Vector()) / len(on_cut) if on_cut else centre  # the joint: the middle of the cut
    me = bpy.data.meshes.new(name)
    piece.transform(Matrix.Translation(-origin))
    piece.to_mesh(me)
    piece.free()
    for m in src.data.materials:
        me.materials.append(m)
    bm.transform(mw.inverted())
    bm.to_mesh(src.data)
    bm.free()
    return new_object(name, me, origin, src)


def material_index(me, name):
    names = [m.name for m in me.materials]
    if name not in names:
        import bpy
        me.materials.append(bpy.data.materials[name])
        names.append(name)
    return names.index(name)


def colliders_of(part, coll):
    return [o for o in coll.objects if o.parent is part]


def collider_name(owner, coll):
    taken = {o.name for o in coll.objects}
    k = 0
    while (f"{owner}_colmesh" + (f".{k:03d}" if k else "")) in taken:
        k += 1
    return f"{owner}_colmesh" + (f".{k:03d}" if k else "")


def split_colliders(src, obj, hs, coll, col_report, inherited):
    """Each of src's convex collider pieces cut by the region's planes: the part inside goes to obj (still convex,
    closed flat, re-hulled to the vertex budget), the rest stays; a cut or moved piece keeps the depth inside the skin
    its whole piece was measured at (inherited). Returns how many pieces obj received."""
    import bmesh
    import bpy
    bpy.context.view_layer.update()
    moved = 0
    for col in colliders_of(src, coll):
        bm = bmesh.new()
        bm.from_mesh(col.data)
        bm.transform(col.matrix_world)
        verts = [v.co.copy() for v in bm.verts]
        entry = inherited.get(col.name) or col_report.get(col.name)
        if all(inside(v, hs) for v in verts):
            bm.free()
            world = col.matrix_world.copy()
            col.parent = obj
            col.matrix_parent_inverse.identity()
            col.matrix_basis = __import__("mathutils").Matrix.Identity(4)
            col.data.transform(obj.matrix_world.inverted() @ world)
            old = col.name
            col.name = collider_name(obj.name, coll)
            inherited.pop(old, None)
            if entry:
                inherited[col.name] = entry
            moved += 1
            continue
        if not any(inside(v, hs, -1e-4) for v in verts):
            bm.free()
            continue
        halves = []
        for keep_inside in (True, False):
            b = bm.copy()
            for q, n in hs:
                geom = b.verts[:] + b.edges[:] + b.faces[:]
                bmesh.ops.bisect_plane(b, geom=geom, plane_co=q, plane_no=n, dist=1e-6,
                                       clear_inner=keep_inside, clear_outer=not keep_inside)
                if not keep_inside:
                    break  # the outside of a one-plane region; several planes leave the source whole there
            close_holes(b, 0)
            bmesh.ops.triangulate(b, faces=b.faces[:])
            halves.append(b)
        old_name = col.name
        bpy.data.objects.remove(col)
        inherited.pop(old_name, None)
        for b, owner in ((halves[0], obj), (halves[1], src)):
            if len(b.faces) < 4:
                b.free()
                continue
            pts = [v.co.copy() for v in b.verts]
            b.free()
            piece = convex_piece(pts, collider_name(owner.name, coll), owner, coll, budget=120)
            if entry:
                inherited[piece.name] = entry
            moved += owner is obj
        bm.free()
    return moved


def band_rings(bl, spec, offset, steps=0.5, dd=5.625):
    """Skin points (offset along the outward normal) over a band's stations and angles."""
    _, lo, hi, s0, s1 = spec["region"]
    n_s = max(1, round((s1 - s0) / steps))
    n_a = max(2, round((hi - lo) / dd))
    rings = []
    for i in range(n_s + 1):
        s = s0 + (s1 - s0) * i / n_s
        rings.append([bl.fus_point(s, lo + (hi - lo) * j / n_a, offset) for j in range(n_a + 1)])
    return rings


def panel_mesh(bl, spec, src, mats):
    """A band's blockout piece: a closed shell PANEL_SHELL thick under the skin over its region."""
    import bmesh
    import bpy
    outer, inner = band_rings(bl, spec, 0.0), band_rings(bl, spec, -PANEL_SHELL)
    bm = bmesh.new()
    O = [[bm.verts.new(p) for p in r] for r in outer]
    I = [[bm.verts.new(p) for p in r] for r in inner]
    rows, cols = len(O), len(O[0])
    for i in range(rows - 1):
        for j in range(cols - 1):
            bm.faces.new((O[i][j], O[i + 1][j], O[i + 1][j + 1], O[i][j + 1]))
            bm.faces.new((I[i][j], I[i][j + 1], I[i + 1][j + 1], I[i + 1][j]))
    rim = [(0, j) for j in range(cols)] + [(i, cols - 1) for i in range(1, rows)] + \
          [(rows - 1, j) for j in range(cols - 2, -1, -1)] + [(i, 0) for i in range(rows - 2, 0, -1)]
    for (i, j), (i1, j1) in zip(rim, rim[1:] + rim[:1]):
        bm.faces.new((O[i][j], I[i][j], I[i1][j1], O[i1][j1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    centre = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    bm.transform(__import__("mathutils").Matrix.Translation(-centre))
    me = bpy.data.meshes.new(spec["name"])
    bm.to_mesh(me)
    bm.free()
    me.materials.append(bpy.data.materials[bl.STRUCT])  # a stand-in on the skin: the art pass makes the panel's skin
    obj = new_object(spec["name"], me, centre, src)
    _, lo, hi, s0, s1 = spec["region"]
    w_lo, w_hi = bl.well_box()
    if lo < 0.0 < hi and s0 < w_hi.y + bl.Y0 and w_lo.y + bl.Y0 < s1:  # over the AWACS well: its slot, as the crown's
        bpy.context.view_layer.update()
        bl.cut_box({obj.name: obj}, [obj.name], w_lo, w_hi, bpy.data.materials[bl.STRUCT], "well")
    return obj


def convex_piece(points, name, owner, coll, budget=28):
    """A convex hull collider piece of world points (thinned to budget vertices), parented to owner."""
    import bpy
    import convex
    import numpy as np
    v, t = convex.hull_mesh(convex.simplify_hull(np.array([p[:] for p in points]), budget))
    me = bpy.data.meshes.new("col")
    inv = owner.matrix_world.inverted()
    me.from_pydata([inv @ Vector(p) for p in v], [], [tuple(int(i) for i in tri) for tri in t])
    piece = bpy.data.objects.new(name, me)
    coll.objects.link(piece)
    piece.parent = owner
    piece.matrix_parent_inverse.identity()
    piece.hide_render = True
    bpy.context.view_layer.update()
    return piece


def panel_colliders(bl, spec, obj, coll):
    """A panel's collider pieces: a shell PANEL_SHELL thick from the colliders' inset (COL_INSET) inward, in runs of
    PANEL_COLLIDER_ARC degrees, each convex, so a hit on the panel's skin can land on the panel."""
    _, lo, hi, s0, s1 = spec["region"]
    return band_colliders(bl, obj, coll, lo, hi, s0, s1)


def band_colliders(bl, obj, coll, lo, hi, s0, s1):
    """Collider pieces for a skin band (stations s0 to s1, angles lo to hi): a shell PANEL_SHELL thick from the
    colliders' inset inward, its ends and sides inset as much, in runs of PANEL_COLLIDER_ARC degrees, none over the
    AWACS well's slot."""
    r = bl.FUS_HALF_W
    d_a = math.degrees(PANEL_COL_INSET / r)
    lo, hi, s0, s1 = lo + d_a, hi - d_a, s0 + PANEL_COL_INSET, s1 - PANEL_COL_INSET
    n = max(1, math.ceil((hi - lo) / PANEL_COLLIDER_ARC))
    m = max(1, math.ceil((s1 - s0) / PANEL_COLLIDER_RUN))  # runs along the body, where its section changes (the ramp)
    # the AWACS well stays open as the cores leave it (build_centurion.clear_of_well, for the stowed beam that lies in
    # it): no piece within WELL_CLEAR of its clearance box, well_box(WELL_CLEAR)
    import convex
    import numpy as np
    box = bl.well_box(bl.WELL_CLEAR)
    box_hull = convex.hull_mesh(bl.box_corners(*box))
    wa = math.degrees(math.asin(min(1.0, (box[1].x + bl.WELL_CLEAR) / r))) + d_a
    w0, w1 = box[0].y + bl.Y0 - bl.WELL_CLEAR, box[1].y + bl.Y0 + bl.WELL_CLEAR
    angles = sorted({lo + (hi - lo) * k / n for k in range(n + 1)} | {a for a in (-wa, wa) if lo < a < hi})
    stations = sorted({s0 + (s1 - s0) * i / m for i in range(m + 1)} | {s for s in (w0, w1) if s0 < s < s1})
    count = 0
    for a0, a1 in zip(angles, angles[1:]):
        for b0, b1 in zip(stations, stations[1:]):
            if -wa <= (a0 + a1) / 2 <= wa and w0 <= (b0 + b1) / 2 <= w1:
                continue
            sub = {"region": ("band", a0, a1, b0, b1)}
            pts = [p for r in band_rings(bl, sub, -PANEL_COL_INSET, steps=0.4) for p in r]
            pts += [p for r in band_rings(bl, sub, -PANEL_COL_INSET - PANEL_SHELL, steps=0.4) for p in r]
            piece = convex_piece(pts, collider_name(obj.name, coll), obj, coll)
            v = np.array([(piece.matrix_world @ c.co)[:] for c in piece.data.vertices])
            gap = convex.hull_gap(convex.hull_mesh(v), box_hull)
            if gap < bl.WELL_CLEAR - 1e-4:
                raise SystemExit(f"{piece.name} stands {gap:.3f} m from the AWACS well's clearance box, under WELL_CLEAR")
            count += 1
    return count


def canoe_mesh(bl, spec, src, mats):
    """A flap-track fairing's blockout piece: a box under the root's lower skin round the art's fairing."""
    import bmesh
    import bpy
    _, x, side = spec["region"]
    le, chord, _ = bl.wing_le(side, x)
    te = le + bl.CDIR * chord
    y0, y1 = te.y - 2.4 - 0.4, te.y + 0.55
    z_top = bl.wing_lower(side, x, (y0 + y1) / 2 + bl.Y0).z if hasattr(bl, "wing_lower") else te.z
    pts = [Vector((side * x + dx, y, z)) for dx in (-CANOE_HALF_W, CANOE_HALF_W) for y in (y0, y1)
           for z in (z_top + 0.02, z_top - CANOE_DEPTH)]
    import convex
    import numpy as np
    v, t = convex.hull_mesh(np.array([p[:] for p in pts]))
    centre = sum(pts, Vector()) / len(pts)
    me = bpy.data.meshes.new(spec["name"])
    me.from_pydata([Vector(p) - centre for p in v], [], [tuple(int(i) for i in tri) for tri in t])
    me.materials.append(bpy.data.materials[bl.STRUCT])  # a stand-in: the art pass makes the fairing
    return new_object(spec["name"], me, centre, src)


def inset_piece(bl, points, name, owner, coll, tree):
    """A collider piece build_centurion's way (collider_piece: the inset hull, its depth checked against tree), or
    None where the inset leaves nothing."""
    import bpy
    piece = bl.collider_piece(points, tree)
    if piece is None:
        return None
    me = bpy.data.meshes.new("col")
    inv = owner.matrix_world.inverted()
    me.from_pydata([inv @ Vector(p) for p in piece["verts"]], [], [tuple(int(i) for i in t) for t in piece["tris"]])
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
    obj.parent = owner
    obj.matrix_parent_inverse.identity()
    obj.hide_render = True
    bpy.context.view_layer.update()
    return obj


def mesh_tree(bl, obj):
    from mathutils.bvhtree import BVHTree
    v, p = bl.world_mesh(obj)
    return BVHTree.FromPolygons(v, p)


def fairing_colliders(bl, obj, coll, chunks=3):
    """The wing fairing's pieces: its hump over the crown only (vertices above it), in runs along the body, so they
    stay clear of the stages, which never reach over the crown."""
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    pts = [p for p in pts if p.z > bl.FUS_TOP + 0.05 and abs(p.x) < 2.0]
    if len(pts) < 8:
        return 0
    y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
    n = 0
    for k in range(chunks):
        a, b = y0 + (y1 - y0) * k / chunks, y0 + (y1 - y0) * (k + 1) / chunks
        run = [p for p in pts if a - 0.05 <= p.y <= b + 0.05]
        if len(run) >= 8:
            base = [Vector((p.x, p.y, bl.FUS_TOP - 0.1)) for p in run]
            tree = mesh_tree(bl, [obj, bl.bpy.data.objects["fuselage_M"]] if hasattr(bl, "bpy") else obj)
            n += inset_piece(bl, run + base, collider_name(obj.name, coll), obj, coll, tree) is not None
    return n


def hull_collider(obj, coll, bl=None):
    """A piece no collider reached: the inset hull of its own mesh (build_centurion's collider_piece)."""
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if bl is not None:
        return int(inset_piece(bl, pts, collider_name(obj.name, coll), obj, coll, mesh_tree(bl, obj)) is not None)
    centre = sum(pts, Vector()) / len(pts)
    convex_piece([centre + (p - centre) * 0.96 for p in pts], collider_name(obj.name, coll), obj, coll)
    return 1

