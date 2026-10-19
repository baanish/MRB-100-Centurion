"""MRB-100 Centurion AWACS beam blockout: the dorsal mount, stowed down in a well in the spine with its cap flush with
the crown, raised straight up on a two-stage telescoping mast, then its end sections telescoped fore and aft. Built on
a proportion_study.py airframe (direction E, the heavy lifter), measured through the rise, and rendered in the M4
review look. docs/M3-DESIGN.md, "Blockout measurements", reads the numbers.

Freeze the study first (another worker edits the live script), then measure and render (Blender):
  git show cb7da2a:art/blender/proportion_study.py > .cache/art/awacs_beam/proportion_study_cb7da2a.py
  blender --background --factory-startup --python art/blender/awacs_beam_blockout.py -- \
      --study .cache/art/awacs_beam/proportion_study_cb7da2a.py [--airframe E]
      [--places aft,fwd] [--render aft] [--views none] [--samples 48] [--out DIR]
Compose the sheets (plain Python with Pillow):
  python -I art/blender/awacs_beam_blockout.py --compose [--out DIR]

--airframe is a proportion_study.py variant, built by running that script with no renders. Every place in --places
is measured; --render picks the one rendered. DIR defaults to <repo>/.cache/art/awacs_beam. Blender writes
<airframe>_<place>_<state>_<view>.png at 1600 x 1000 and metrics_<airframe>.json; compose writes sheet.png (2560
wide), door.png and sequence.png.

World frame as the blockout: nose -Y, up +Z, left wing +X, Y = station - 21.5, ground at z 0.
"""

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / ".cache" / "art" / "awacs_beam"
STUDY = REPO / "art" / "blender" / "proportion_study.py"
Y0 = 21.5
TRAVEL_WING = 6.3  # SPEC: each wing stage's travel; the study slides stages by slide_axis x this
STOW_LIMIT, SPEC_HEIGHT, DOOR = 7.45, 7.6, 8.0
GAP_MIN = 0.10  # M3 AwacsEnvelopeCheck: no mount collider within 0.10 m of another part's collider

# The mount, in metres. The beam (fin, cap and end sections) is M3-DESIGN's; the mast is a fixed sleeve in the well
# and two nested streamlined stages that rise together, each stage_inset thinner than the one around it, keeping
# "overlap" inside its parent when raised. Raised, mast_exposed of mast shows above the crown, as M3's 2.2 m mast.
# M3's mount on step 6.1 (art/blender/awacs_mount.py) holds the beam on a full-length dorsal blade instead of the mast,
# as the E-7 Wedgetail does (owner, docs/DECISIONS.md 2026-10-13): two nested blades in a sleeve under the well's floor.
# Stowed there, they fit between fuselage_M's collider (ending at station 25.0) and the tail cone's (from 33.0) with the
# envelope check's 0.10 m, so the sleeve reaches blade_ahead ahead of the beam's centre (station 29.79) and blade_behind
# behind it. From the crown up to the beam, the blade's leading and trailing edges sweep aft by blade_le_sweep and
# blade_te_sweep, as a fin's do.
MOUNT = {"fin_len": 10.0, "fin_h": 1.4, "fin_t": 0.55, "cap_w": 0.8, "cap_t": 0.25, "ext_len": 3.0, "travel": 2.5,
         "ext_inset": 0.03, "mast_chord": 1.6, "mast_t": 0.45, "mast_exposed": 2.2, "overlap": 0.4,
         "stage_inset": 0.04, "slot_gap": 0.03, "cap_above_crown": 0.0,
         "blade_ahead": 4.72, "blade_behind": 3.14, "blade_le_sweep": 0.7, "blade_te_sweep": 0.4}
# Beam centre station on the airframe. aft: from just behind the wing root's trailing edge (25.05 on E) over the aft
# bay, which the AWACS loadout leaves empty (SPEC "Hardpoint sets"); fwd: over the forward bay, ahead of the wing.
PLACES = {"aft": 30.4, "fwd": 12.0}
# Assumed split of the 6,000 kg loadout (SPEC "Mass and fuel") over the mount's pieces, for the CG.
MASS_SPLIT = {"awacs_beam": 2800, "awacs_beam_ext_F": 500, "awacs_beam_ext_R": 500, "awacs_mast_2": 500,
              "awacs_mast_1": 700, "awacs_base": 1000}
CARRIER_MASS = 4500  # M3: emptyMass, applied at the hardpoint part's centre of mass; the mount part carries 1,500
# Airframe skin parts the well may cut; any other part near the well is a clash.
SKINS = ("nose", "fuselage_F", "fuselage_M", "fuselage_R", "tailcone", "wingfairing", "radar_F_fairing", "radar_R_fairing")
CARRIER = {"aft": "fuselage_R", "fwd": "fuselage_F"}  # the fuselage part holding most of the well


def views(c):
    """name: (kind, lens or ortho scale, camera (x, station, z), look-at (x, station, z) or euler degrees); c is the
    beam's centre station."""
    rear, side = (90, 0, 180), (90, 0, 90)
    return {
        "hero": ("persp", 62, (56.0, -50.5, 44.0), (0.0, 22.5, 3.0)),
        "hero_ext": ("persp", 50, (56.0, -50.5, 44.0), (0.0, 22.5, 3.0)),
        "beam34": ("persp", 40, (17.0, c + 22.0, 15.0), (0.8, c, 7.4)),
        "side": ("ortho", 52, (120.0, 22.5, 4.6), side),
        "cut_side": ("ortho", 18, (120.0, c, 6.0), side),
        "rear": ("ortho", 30, (0.0, 140.0, 5.4), rear),
        "rear_ext": ("ortho", 76, (0.0, 140.0, 4.0), rear),
        "top": ("ortho", 76, (0.0, 22.5, 80.0), (0, 0, 180)),
        "door": ("ortho", 52, (0.0, 140.0, 4.0), rear),
        "door_close": ("ortho", 12, (0.0, 140.0, 6.6), rear),
    }


RES = (1600, 1000)
# state: (mast fraction, end fraction, wing extension, flight attitude)
STATES = {"stowed": (0.0, 0.0, 0.0, False), "mid": (0.5, 0.0, 0.0, False), "mastup": (1.0, 0.0, 0.0, False),
          "deployed": (1.0, 1.0, 1.0, True)}
SHOTS = {"stowed": ("hero", "side", "rear", "beam34", "cut_side", "door", "door_close"), "mid": ("beam34", "hero", "cut_side"),
         "mastup": ("beam34", "hero", "cut_side"), "deployed": ("hero_ext", "side", "rear_ext", "top", "beam34")}
CUTAWAY = "cut_side"  # rendered with the skins hidden, so the stowed beam and the nested mast show
FLIGHT_PITCH_DEG, FLIGHT_GROUND_Z = 3.0, -40.0
PAINT_SRGB = (0.38, 0.39, 0.405)  # m4/paint.py PAINT[HULL]
BEAM_SRGB = (0.33, 0.335, 0.34)  # m4/paint.py PAINT[RADOME]: the dielectric array


def st(station):
    return station - Y0


def rise_geometry(M):
    """The beam's height, its rise, and each mast stage's travel and length."""
    beam_h = M["fin_h"] + M["cap_t"]
    travel = beam_h - M["cap_above_crown"] + M["mast_exposed"]
    stage_travel = travel / 2
    return beam_h, travel, stage_travel, stage_travel + M["overlap"] + 0.01


# =====================================================================================================================
# Blender side
# =====================================================================================================================
def blender_main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"airframe": "E", "places": "aft,fwd", "render": "aft", "views": "", "samples": "48", "out": str(OUT),
            "study": str(STUDY)}
    i = 0
    while i < len(argv):
        key = argv[i].lstrip("-")
        if key not in opts:
            raise SystemExit(f"unknown argument {argv[i]}")
        opts[key], i = argv[i + 1], i + 2
    out = Path(opts["out"])
    if not out.is_absolute():
        raise SystemExit("Pass an absolute --out: Blender resolves relative paths against its own cwd.")
    out.mkdir(parents=True, exist_ok=True)
    airframe = opts["airframe"]
    study_out = out / f"study_{airframe}"
    build_study(airframe, Path(opts["study"]), study_out)
    study = json.loads((study_out / f"metrics_{airframe}.json").read_text())

    import bmesh
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m4 import render as m4r

    scene = bpy.context.scene
    parts = [o for o in bpy.data.collections["Centurion"].objects if o.type == "MESH"]
    slides = {o: (Vector(o["rest_location"]), Vector(o["slide_axis"])) for o in parts if "slide_axis" in o}
    skins = [o for o in parts if o.name in SKINS]

    def set_wing(ext):
        for o, (rest, axis) in slides.items():
            o.location = rest + axis * (TRAVEL_WING * ext)
        bpy.context.view_layer.update()

    # ---------- geometry helpers ----------
    def world_mesh(objs):
        verts, polys, owner = [], [], []
        for o in objs:
            mw, base = o.matrix_world, len(verts)
            verts += [mw @ v.co for v in o.data.vertices]
            for p in o.data.polygons:
                polys.append([base + k for k in p.vertices])
                owner.append(o.name)
        return verts, polys, owner

    def tree_of(objs):
        v, p, _ = world_mesh(objs)
        return BVHTree.FromPolygons(v, p)

    def surface_samples(objs, h):
        """Points over every face of objs at most h apart, so a coarse face's interior counts in a distance."""
        pts = []
        verts, polys, _ = world_mesh(objs)
        for poly in polys:
            for k in range(1, len(poly) - 1):
                a, b, c = verts[poly[0]], verts[poly[k]], verts[poly[k + 1]]
                n = max(1, math.ceil(max((b - a).length, (c - a).length, (c - b).length) / h))
                for u in range(n + 1):
                    for w in range(n + 1 - u):
                        pts.append(a + (b - a) * (u / n) + (c - a) * (w / n))
        return pts

    def add_shell(bm, rings, cap_start=True, cap_end=True):
        vs = [[bm.verts.new(p) for p in ring] for ring in rings]
        n = len(rings[0])
        for a, b in zip(vs, vs[1:]):
            for k in range(n):
                bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
        if cap_start:
            bm.faces.new(vs[0][::-1])
        if cap_end:
            bm.faces.new(vs[-1])

    def mesh_obj(name, shells, mats, parent, location, coll):
        bm = bmesh.new()
        for rings, caps in shells:
            add_shell(bm, rings, *caps)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for m in mats:
            me.materials.append(m)
        return obj(name, me, parent, location, coll)

    def obj(name, data, parent, location, coll):
        o = bpy.data.objects.new(name, data)
        coll.objects.link(o)
        o.parent = parent
        o.location = location
        if data is None:
            o.empty_display_size = 0.4
        return o

    # ---------- the mount ----------
    def t_ring(M, y, d=0.0, sx=1.0, sz=1.0):
        """Top-hat section at y, x across and z up from the fin's foot, every wall inset by d (the end sections nest
        at d = ext_inset), scaled about its middle for the end chamfers."""
        fh, ch = M["fin_t"] / 2 - d, M["cap_w"] / 2 - d
        z0, z1, z2, c = d, M["fin_h"] + d, M["fin_h"] + M["cap_t"] - d, 0.04
        right = [(fh, z0), (fh, z1), (ch - c, z1), (ch, z1 + c), (ch, z2 - c), (ch - c, z2)]
        zc = (M["fin_h"] + M["cap_t"]) / 2
        return [Vector((x * sx, y, zc + (z - zc) * sz)) for x, z in right + [(-x, z) for x, z in reversed(right)]]

    def naca_ring(chord, thick, z, n=20):
        """Symmetric streamlined section, chord along Y centred on 0, leading edge forward (-Y)."""
        tc, pts = thick / chord, []
        for k in range(n):
            t = 0.5 * (1 - math.cos(math.pi * k / (n - 1)))
            pts.append((t, 5 * tc * chord * (0.2969 * math.sqrt(t) - 0.126 * t - 0.3516 * t ** 2 + 0.2843 * t ** 3 - 0.1036 * t ** 4)))
        return ([Vector((yt, -chord / 2 + t * chord, z)) for t, yt in pts]
                + [Vector((-yt, -chord / 2 + t * chord, z)) for t, yt in reversed(pts[1:-1])])

    def box_ring(hx, hy, z):
        return [Vector((hx, -hy, z)), Vector((hx, hy, z)), Vector((-hx, hy, z)), Vector((-hx, -hy, z))]

    def build_mount(M, centre, crown, mats, coll):
        beam_h, travel, s_travel, s_len = rise_geometry(M)
        foot0 = M["cap_above_crown"] - beam_h  # the beam's foot below the crown, stowed
        L, ins = M["fin_len"] / 2, M["stage_inset"]
        slot_x, slot_y = M["cap_w"] / 2 + M["slot_gap"], L + 0.05
        # The root: the well's floor plate and below it the fixed sleeve of the mast. The well's walls are the
        # airframe's slot (the cut skins), and the cap closes it.
        floor = [box_ring(slot_x - 0.01, slot_y - 0.01, z) for z in (foot0 - 0.06, foot0 - 0.01)]
        sleeve = [naca_ring(M["mast_chord"] + 2 * ins, M["mast_t"] + 2 * ins, z) for z in (foot0 - s_len - 0.05, foot0 - 0.05)]
        base = mesh_obj("awacs_base", [(floor, (True, True)), (sleeve, (True, True))], (mats["struct"],), None,
                        (0.0, st(centre), crown), coll)
        col = obj("awacs_base_colmesh", base.data.copy(), base, (0, 0, 0), coll)
        col.hide_render = col.hide_viewport = True
        stages = []
        parent, loc = base, (0, 0, foot0)
        for k in (1, 2):
            t, c = M["mast_t"] - 2 * ins * (k - 1), M["mast_chord"] - 2 * ins * (k - 1)
            top = 0.15 if k == 2 else 0.0  # the top stage runs into the fin's foot
            stage = mesh_obj(f"awacs_mast_{k}", [([naca_ring(c, t, z) for z in (-s_len, top)], (True, True))],
                             (mats["skin"],), parent, loc, coll)
            obj(f"awacs_mast_{k}_raised", None, parent, (loc[0], loc[1], loc[2] + s_travel), coll)
            stages.append(stage)
            parent, loc = stage, (0, 0, 0)
        beam = mesh_obj("awacs_beam", [([t_ring(M, -L, sx=0.82, sz=0.9), t_ring(M, -L + 0.15), t_ring(M, L - 0.15),
                                         t_ring(M, L, sx=0.82, sz=0.9)], (True, True))], (mats["beam"],), stages[1], (0, 0, 0), coll)
        exts, d, n = {}, M["ext_inset"], M["ext_len"]
        for tag, s in (("F", -1), ("R", 1)):
            # Origin at the outer end; retracted it sits 2 cm inside the beam's end.
            rings = [t_ring(M, 0.0, d, sx=0.35, sz=0.55), t_ring(M, -s * 0.22, d, sx=0.75, sz=0.88),
                     t_ring(M, -s * 0.55, d), t_ring(M, -s * n, d)]
            exts[tag] = mesh_obj(f"awacs_beam_ext_{tag}", [(rings[::-1] if s > 0 else rings, (True, True))],
                                 (mats["beam"],), beam, (0, s * (L - 0.02), 0), coll)
            obj(f"awacs_beam_ext_{tag}_extended", None, beam, (0, s * (L - 0.02 + M["travel"]), 0), coll)
        obj("awacs_scanner", None, beam, (0, 0, beam_h / 2), coll)
        # Not part of the mount: the slot the airframe needs, cut from the skins for the renders.
        cutter = mesh_obj("awacs_slot_cutter", [([box_ring(slot_x, slot_y, z) for z in (foot0 - 0.06, 1.2)], (True, True))],
                          (mats["struct"],), base, (0, 0, 0), coll)
        cutter.hide_render = True
        bpy.context.view_layer.update()
        rest = [s.location.copy() for s in stages], {t: e.location.copy() for t, e in exts.items()}

        def pose(mast_f, ends_f):
            for s, r in zip(stages, rest[0]):
                s.location = r + Vector((0, 0, s_travel * mast_f))
            for t, e in exts.items():
                e.location = rest[1][t] + Vector((0, (-1 if t == "F" else 1) * M["travel"] * ends_f, 0))
            bpy.context.view_layer.update()

        return {"base": base, "stages": stages, "beam": beam, "exts": list(exts.values()), "cutter": cutter, "pose": pose,
                "moving": [*stages, beam, *exts.values()]}

    # ---------- measurements ----------
    af_verts, af_polys, af_owner = world_mesh(parts)
    af_tree = BVHTree.FromPolygons(af_verts, af_polys)
    af_vert_owner = [o.name for o in parts for _ in o.data.vertices]
    skin_tree = tree_of(skins)

    def distances(mount_objs, h):
        """Least distance from the mount objects to each airframe part, both ways (mount surface samples to the
        airframe, airframe vertices near the mount to the mount), 0 where they intersect."""
        mv, mp, _ = world_mesh(mount_objs)
        mtree = BVHTree.FromPolygons(mv, mp)
        best = {}
        for p in surface_samples(mount_objs, h):
            loc, _, idx, d = af_tree.find_nearest(p)
            if idx is not None and d < best.get(af_owner[idx], (9e9,))[0]:
                best[af_owner[idx]] = (d, p.copy())
        lo = [min(v[k] for v in mv) - 1 for k in range(3)]
        hi = [max(v[k] for v in mv) + 1 for k in range(3)]
        for v, name in zip(af_verts, af_vert_owner):
            if all(lo[k] <= v[k] <= hi[k] for k in range(3)):
                loc, _, idx, d = mtree.find_nearest(v)
                if idx is not None and d < best.get(name, (9e9,))[0]:
                    best[name] = (d, loc.copy())
        for _, ai in mtree.overlap(af_tree):
            best[af_owner[ai]] = (0.0, best.get(af_owner[ai], (0, Vector()))[1])
        return best

    def not_skin(d):
        return {k: v for k, v in d.items() if k not in SKINS}

    def zmax(objs):
        return max(v.z for v in world_mesh(objs)[0])

    def where(p):
        return {"x": round(p.x, 2), "station": round(p.y + Y0, 2), "z": round(p.z, 2)}

    def crown_at(station):
        return skin_tree.ray_cast(Vector((0.0, st(station), 30.0)), Vector((0, 0, -1)))[0].z

    def belly_at(station):
        return skin_tree.ray_cast(Vector((0.0, st(station), -5.0)), Vector((0, 0, 1)))[0].z

    def bounds_centre(o):
        vs = world_mesh([o])[0]
        return Vector([(min(v[k] for v in vs) + max(v[k] for v in vs)) / 2 for k in range(3)])

    def cg(m, place):
        cg0 = study["retracted"]["cg_empty"]
        m0, s0, z0 = cg0["mass_kg"], cg0["station"], cg0["height_m"]
        main = study["retracted"]["gear"]["main_station"]
        objs = {o.name.split(".")[0]: o for o in [m["base"], *m["moving"]]}  # a second place's copies get ".001"
        mt = sum(MASS_SPLIT.values())
        res = {"empty": {"mass_kg": m0, "station": s0, "height_m": z0, "main_gear_station": main}}
        for state, (mf, ef) in (("stowed", (0.0, 0.0)), ("deployed", (1.0, 1.0))):
            m["pose"](mf, ef)
            c = sum((bounds_centre(objs[n]) * w for n, w in MASS_SPLIT.items()), Vector()) / mt
            s, z = (m0 * s0 + mt * (c.y + Y0)) / (m0 + mt), (m0 * z0 + mt * c.z) / (m0 + mt)
            res[state] = {"mount_station": round(c.y + Y0, 2), "mount_height": round(c.z, 2), "station": round(s, 3),
                          "height_m": round(z, 3), "shift_m": round(s - s0, 3), "rise_m": round(z - z0, 3),
                          "ahead_of_main_gear_m": round(main - s, 2)}
        # In game: emptyMass sits at the carrier part's centre of mass (its hull bounds' centre), the mount part's
        # 1,500 kg at its own.
        carrier = bpy.data.objects[CARRIER[place]]
        cc = bounds_centre(carrier).y + Y0
        m["pose"](0.0, 0.0)
        s = (m0 * s0 + CARRIER_MASS * cc + (mt - CARRIER_MASS) * res["stowed"]["mount_station"]) / (m0 + mt)
        res["in_game"] = {"carrier": carrier.name, "carrier_com_station": round(cc, 2), "station": round(s, 3),
                          "shift_m": round(s - s0, 3)}
        return res

    def measure(M, m, place, centre, crown):
        beam_h, travel, s_travel, s_len = rise_geometry(M)
        out = {"centre_station": centre, "beam_stations": [centre - M["fin_len"] / 2, centre + M["fin_len"] / 2],
               "crown_z": round(crown, 3), "rise_m": round(travel, 3), "stage_travel_m": round(s_travel, 3),
               "stage_length_m": round(s_len, 3), "mount": M}
        crowns = [crown_at(centre - 5.05 + 10.1 * k / 40) for k in range(41)]
        out["crown_along_slot"] = [round(min(crowns), 3), round(max(crowns), 3)]
        set_wing(0.0)
        m["pose"](0.0, 0.0)
        d = distances([m["base"], m["cutter"], *m["moving"]], 0.05)
        others = sorted(not_skin(d).items(), key=lambda kv: kv[1][0])[:6]
        out["stowed"] = {"top_z": round(zmax(m["moving"]), 3), "under_limit_m": round(STOW_LIMIT - zmax(m["moving"]), 3),
                         "skins_cut": sorted(k for k, v in d.items() if k in SKINS and v[0] == 0.0),
                         "nearest_other_parts": {k: {"gap": round(v[0], 3), "at": where(v[1])} for k, v in others},
                         "wing_box_gap_m": round(min(d.get(n, (9e9,))[0] for n in ("wing_root_L", "wing_root_R")), 3),
                         "well_floor_z": round(min(v.z for v in world_mesh([m["cutter"]])[0]), 3),
                         "sleeve_bottom_z": round(min(v.z for v in world_mesh([m["base"]])[0]), 3),
                         "belly_at_centre_z": round(belly_at(centre), 3)}
        sweep, worst = [], (9e9, None, None)
        for mf, ef in [(k / 16, 0.0) for k in range(17)] + [(1.0, k / 10) for k in range(1, 11)]:
            m["pose"](mf, ef)
            o = not_skin(distances(m["moving"], 0.08))
            k_min = min(o, key=lambda k: o[k][0])
            sweep.append({"mast": round(mf, 3), "ends": ef, "min_gap": round(o[k_min][0], 3), "part": k_min})
            if o[k_min][0] < worst[0]:
                worst = (o[k_min][0], k_min, (round(mf, 3), ef))
        out["sweep"] = {"min_gap_to_non_skin_parts": round(worst[0], 3), "part": worst[1], "at_mast_ends": worst[2],
                        "passes_0.10": worst[0] >= GAP_MIN, "poses": sweep}
        m["pose"](1.0, 0.0)
        out["mast_up"] = {"top_z": round(zmax(m["moving"]), 3), "beam_foot_z": round(min(v.z for v in world_mesh([m["beam"]])[0]), 3)}
        m["pose"](1.0, 1.0)
        bv = world_mesh([m["beam"], *m["exts"]])[0]
        out["deployed"] = {"top_z": round(zmax(m["moving"]), 3), "beam_length_m": round(max(v.y for v in bv) - min(v.y for v in bv), 3),
                           "beam_stations": [round(min(v.y for v in bv) + Y0, 2), round(max(v.y for v in bv) + Y0, 2)],
                           "tail_top_z": study["retracted"]["tail_top_m"]}
        out["cg"] = cg(m, place)
        m["pose"](0.0, 0.0)
        return out

    # ---------- render rig (the M4 review look, as proportion_study.py) ----------
    def rig():
        for c in [c for c in bpy.data.collections if c.name.startswith("study_")]:
            for o in list(c.all_objects):
                bpy.data.objects.remove(o)
            bpy.data.collections.remove(c)
        coll = bpy.data.collections.new("awacs_rig")
        scene.collection.children.link(coll)
        sun = bpy.data.objects.new("awacs_sun", bpy.data.lights.new("awacs_sun", "SUN"))
        sun.data.energy, sun.data.angle = 3.2, math.radians(2.5)
        sun.rotation_euler = (math.radians(42), math.radians(12), math.radians(-35))
        coll.objects.link(sun)
        me = bpy.data.meshes.new("awacs_ground")
        me.from_pydata([(-300, -300, 0), (300, -300, 0), (300, 300, 0), (-300, 300, 0)], [], [(0, 1, 2, 3)])
        ground = bpy.data.objects.new("awacs_ground", me)
        gm = bpy.data.materials.new("awacs_ground")
        m4r.principled(gm, (0.16, 0.16, 0.155), 0.85, 0.0)
        me.materials.append(gm)
        coll.objects.link(ground)
        cam = bpy.data.objects.new("awacs_cam", bpy.data.cameras.new("awacs_cam"))
        cam.data.clip_end = 1000
        coll.objects.link(cam)
        scene.camera = cam
        world = scene.world or bpy.data.worlds.new("World")
        scene.world = world
        if world.node_tree is None:
            world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        bg.inputs["Color"].default_value = (0.55, 0.6, 0.68, 1)
        bg.inputs["Strength"].default_value = 0.9
        scene.view_settings.view_transform = "Standard"
        scene.render.engine = "CYCLES"
        m4r.use_gpu(scene)
        scene.cycles.use_denoising = True
        return coll, cam, ground

    def style():
        m = bpy.data.materials
        m4r.principled(m["Centurion_skin"], tuple(m4r.srgb_to_linear(PAINT_SRGB)), 0.6, 0.0)
        m4r.principled(m["aircraft_structure"], (0.11, 0.115, 0.11), 0.7, 0.2)
        m4r.principled(m["jet_mechanical"], (0.06, 0.06, 0.065), 0.45, 0.8)
        m4r.principled(m["glass"], (0.008, 0.011, 0.010), 0.04, 0.0)
        m4r.principled(m["Centurion_gear"], (0.16, 0.16, 0.165), 0.55, 0.3)
        beam = m.get("awacs_dielectric") or m.new("awacs_dielectric")
        m4r.principled(beam, tuple(m4r.srgb_to_linear(BEAM_SRGB)), 0.5, 0.0)
        return {"skin": m["Centurion_skin"], "beam": beam, "struct": m["aircraft_structure"]}

    def shoot(cam, view, vdefs, path, samples):
        kind, k, loc, aim = vdefs[view]
        cam.location = Vector((loc[0], st(loc[1]), loc[2]))
        if kind == "ortho":
            cam.data.type, cam.data.ortho_scale = "ORTHO", k
            cam.rotation_euler = tuple(math.radians(a) for a in aim)
        else:
            cam.data.type, cam.data.lens = "PERSP", k
            cam.rotation_euler = (Vector((aim[0], st(aim[1]), aim[2])) - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.cycles.samples = samples
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = *RES, 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        return str(path)

    def flight(on, roots, rest, ground, centre):
        """Flight attitude: gear, wheels and gear doors hidden, FLIGHT_PITCH_DEG nose up about the beam's station,
        the ground dropped out of the way."""
        for o in parts:
            if o.name.startswith(("gear_", "wheel_", "geardoor_")):
                o.hide_render = on
        pivot = Vector((0, st(centre), 4.0))
        pitch = (Matrix.Translation(pivot) @ Matrix.Rotation(-math.radians(FLIGHT_PITCH_DEG) if on else 0.0, 4, "X")
                 @ Matrix.Translation(-pivot))
        for o in roots:
            o.matrix_world = pitch @ rest[o]
        ground.location.z = FLIGHT_GROUND_Z if on else 0.0
        bpy.context.view_layer.update()

    def cut_slot(cutter):
        """Boolean the slot out of every skin it crosses (left unapplied, so measurements read the uncut meshes)."""
        ct = tree_of([cutter])
        for o in skins:
            if ct.overlap(tree_of([o])):
                mod = o.modifiers.new("awacs_slot", "BOOLEAN")
                mod.operation, mod.object, mod.solver = "DIFFERENCE", cutter, "EXACT"
                mod.material_mode = "TRANSFER"

    # ---------- main ----------
    rig_coll, cam, ground = rig()
    mats = style()
    only = set(filter(None, opts["views"].split(",")))
    metrics = {"airframe": airframe, "study": str(opts["study"]), "places": {}, "renders": []}
    mounts = {}
    for place in opts["places"].split(","):
        centre = PLACES[place]
        crown = crown_at(centre)
        coll = bpy.data.collections.new(f"AWACS_{place}")
        scene.collection.children.link(coll)
        m = build_mount(MOUNT, centre, crown, mats, coll)
        res = measure(MOUNT, m, place, centre, crown)
        metrics["places"][place] = res
        mounts[place] = (m, coll)
        s = res["stowed"]
        print(f"AWACS {airframe}/{place}: beam stations {res['beam_stations']} crown {res['crown_along_slot']} stowed top "
              f"{s['top_z']} skins cut {s['skins_cut']} nearest {json.dumps(s['nearest_other_parts'])} wing box gap "
              f"{s['wing_box_gap_m']} sleeve bottom {s['sleeve_bottom_z']} belly {s['belly_at_centre_z']} rise {res['rise_m']} "
              f"stage {res['stage_travel_m']}/{res['stage_length_m']} sweep {res['sweep']['min_gap_to_non_skin_parts']} "
              f"({res['sweep']['part']} at {res['sweep']['at_mast_ends']}) mast up {res['mast_up']} deployed {res['deployed']} "
              f"CG {json.dumps(res['cg'])}")
        for o in coll.objects:
            o.hide_render = True
    place = opts["render"]
    metrics["render_place"] = place
    if place in mounts and only != {"none"}:
        m, coll = mounts[place]
        centre = PLACES[place]
        vdefs = views(centre)
        cut_slot(m["cutter"])
        keep = set(parts)
        mount_objs = {o for o in coll.objects if o.type == "MESH" and not o.name.endswith(("_colmesh", "_cutter"))}
        for o in scene.objects:
            o.hide_render = not (o in keep or o in mount_objs or o.name in rig_coll.objects)
        roots = [o for o in keep | mount_objs if o.parent is None]
        rest = {o: o.matrix_world.copy() for o in roots}
        for state, vs in SHOTS.items():
            vs = [v for v in vs if not only or v in only]
            if not vs:
                continue
            mast_f, ends_f, wing, fly = STATES[state]
            set_wing(wing)
            m["pose"](mast_f, ends_f)
            flight(fly, roots, rest, ground, centre)
            for view in vs:
                for o in skins:
                    o.hide_render = view == CUTAWAY
                path = out / f"{airframe}_{place}_{state}_{view}.png"
                metrics["renders"].append(shoot(cam, view, vdefs, path, int(opts["samples"])))
            for o in skins:
                o.hide_render = False
            flight(False, roots, rest, ground, centre)
        set_wing(0.0)
        m["pose"](0.0, 0.0)
    (out / f"metrics_{airframe}.json").write_text(json.dumps(metrics, indent=1))
    bpy.ops.wm.save_as_mainfile(filepath=str(out / f"awacs_{airframe}.blend"), check_existing=False)


def build_study(variant, src, out):
    """Build a proportion_study.py variant into the scene by running that script with no renders. It loads its
    libraries from art/blender, so it runs under its repo path whatever copy of the source is given."""
    argv = sys.argv
    sys.argv = ["blender", "--", "--variants", variant, "--views", "none", "--out", str(out)]
    try:
        exec(compile(Path(src).read_text(encoding="utf-8"), str(STUDY), "exec"),
             {"__name__": "proportion_study", "__file__": str(STUDY)})
    finally:
        sys.argv = argv


# =====================================================================================================================
# Compose side (plain Python, Pillow)
# =====================================================================================================================
def compose_main(out, airframe="E"):
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        for f in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
        return ImageFont.load_default()

    metrics = json.loads((out / f"metrics_{airframe}.json").read_text())
    place = metrics["render_place"]
    pm = metrics["places"][place]
    vdefs = views(pm["centre_station"])
    f = lambda s, v: out / f"{airframe}_{place}_{s}_{v}.png"

    def with_lines(path, view, rows):
        """An ortho render with horizontal lines drawn at their heights (labels alternate sides)."""
        img = Image.open(path).convert("RGB")
        kind, scale, loc, _ = vdefs[view]
        W, H = img.size
        ppm = W / scale
        zpx = lambda z: H / 2 - (z - loc[2]) * ppm
        d = ImageDraw.Draw(img)
        for k, (z, col, label) in enumerate(sorted(rows, reverse=True)):
            y = zpx(z)
            d.line([(0, y), (W, y)], fill=col, width=3)
            d.text((W - 12, y - 4) if k % 2 == 0 else (12, y - 4), label, fill=col, font=font(34),
                   anchor="rb" if k % 2 == 0 else "lb", stroke_width=3, stroke_fill=(20, 20, 20))
        if view == "door":
            xpx = lambda x: W / 2 + (x - loc[0]) * ppm
            for x in (-45.78 / 2, 45.78 / 2):
                d.line([(xpx(x), zpx(0)), (xpx(x), zpx(DOOR))], fill=(220, 30, 30), width=3)
        lined = path.with_name(path.stem + "_lines.png")
        img.save(lined)
        return lined

    s = pm["stowed"]
    door = (DOOR, (220, 30, 30), "hangar door 8.00 m")
    limit = (STOW_LIMIT, (235, 200, 20), "stowed limit 7.45 m")
    top = (s["top_z"], (20, 200, 230), f"stowed top {s['top_z']:.2f} m")
    tail = (pm["deployed"]["tail_top_z"], (180, 120, 230), f"tail top {pm['deployed']['tail_top_z']:.2f} m")
    raised = (pm["mast_up"]["top_z"], (20, 200, 230), f"top {pm['mast_up']['top_z']:.2f} m")
    lined = {}
    for state, view, rows in (("stowed", "door", [door]), ("stowed", "door_close", [door, limit, top, tail]),
                              ("stowed", "cut_side", [door, top]), ("mid", "cut_side", [door]), ("mastup", "cut_side", [door, raised])):
        if f(state, view).exists():
            lined[(state, view)] = with_lines(f(state, view), view, rows)

    def sheet(rows, path, title, tile_w, row_titles=None, notes=()):
        tile_h = tile_w * RES[1] // RES[0]
        cols = max(len(r) for r in rows)
        head, foot = 64, 16 + 30 * len(notes)
        W, H = cols * tile_w, head + len(rows) * tile_h + foot
        img = Image.new("RGB", (W, H), (226, 228, 232))
        d = ImageDraw.Draw(img)
        d.text((16, 12), title, fill=(20, 20, 24), font=font(34))
        for r, row in enumerate(rows):
            for c, (p, label) in enumerate(row):
                x0, y0 = c * tile_w, head + r * tile_h
                if p and Path(p).exists():
                    img.paste(Image.open(p).convert("RGB").resize((tile_w, tile_h), Image.LANCZOS), (x0, y0))
                if label:
                    d.text((x0 + 10, y0 + 8), label, fill=(250, 250, 250), font=font(22), stroke_width=2, stroke_fill=(30, 30, 30))
            if row_titles:
                d.text((12, head + r * tile_h + tile_h - 36), row_titles[r], fill=(255, 235, 120), font=font(24),
                       stroke_width=2, stroke_fill=(20, 20, 20))
        for k, n in enumerate(notes):
            d.text((16, head + len(rows) * tile_h + 10 + 30 * k), n, fill=(40, 40, 46), font=font(21))
        img.save(path)
        print(path)
        return path

    cg = pm["cg"]
    b0, b1 = pm["beam_stations"]
    notes = [f"Beam over stations {b0:.1f} to {b1:.1f}, behind the wing box; stowed top {s['top_z']:.2f} m, flush with the "
             f"{pm['crown_z']:.2f} m crown; rise {pm['rise_m']:.2f} m on two {pm['stage_length_m']:.2f} m mast stages, then the ends "
             f"{MOUNT['travel']} m each; raised top {pm['deployed']['top_z']:.2f} m, beam {pm['deployed']['beam_length_m']:.2f} m",
             f"Least gap through the rise to parts other than the cut skins {pm['sweep']['min_gap_to_non_skin_parts']:.2f} m "
             f"({pm['sweep']['part']}); well to wing box {s['wing_box_gap_m']:.2f} m; sleeve bottom {s['sleeve_bottom_z']:.2f} m",
             f"CG with the 6 t loadout: station {cg['stowed']['station']:.2f} ({cg['stowed']['shift_m']:+.2f} m from the empty "
             f"{cg['empty']['station']:.2f}), {cg['stowed']['ahead_of_main_gear_m']:.2f} m ahead of the main gear; raising adds "
             f"{cg['deployed']['rise_m'] - cg['stowed']['rise_m']:.2f} m of CG height"]
    rows = [
        [(f("stowed", "hero"), "stowed, hero"), (f("stowed", "side"), "stowed, side"), (f("stowed", "rear"), "stowed, rear"),
         (lined.get(("stowed", "door_close")), "stowed, rear, door line")],
        [(f("stowed", "beam34"), "stowed, cap flush in the spine"), (f("mid", "beam34"), "mid-rise"),
         (f("mastup", "beam34"), "mast up, ends retracted"), (f("deployed", "beam34"), "deployed, ends out 2.5 m")],
        [(lined.get(("stowed", "cut_side")), "skins hidden: stowed"), (lined.get(("mid", "cut_side")), "skins hidden: mid-rise"),
         (lined.get(("mastup", "cut_side")), "skins hidden: mast up"), (lined.get(("stowed", "door")), "stowed, against the door")],
        [(f("deployed", "hero_ext"), "deployed, flight, hero"), (f("deployed", "side"), "deployed, flight, side"),
         (f("deployed", "rear_ext"), "deployed, flight, rear"), (f("deployed", "top"), "deployed, flight, top")],
    ]
    sheet(rows, out / "sheet.png", "MRB-100 Centurion, direction E: AWACS beam rising out of the spine", 640,
          row_titles=["stowed", "the rise: 8 s mast, then 4 s ends", "the well and the nested mast",
                      "deployed, extended wing, 3 deg nose up"], notes=notes)
    sheet([[(lined.get(("stowed", "door")), "stowed, rear, against the medium-hangar door"),
            (lined.get(("stowed", "door_close")), "stowed, rear, close")]], out / "door.png",
          "Stowed beam from behind against the 8 m door (direction E)", 1280, notes=notes[:1])
    sheet([[(f(k, "beam34"), lab) for k, lab in (("stowed", "stowed"), ("mid", "mid-rise"), ("mastup", "mast up"),
                                                 ("deployed", "deployed"))],
           [(lined.get((k, "cut_side")), lab) for k, lab in (("stowed", "skins hidden: stowed"), ("mid", "skins hidden: mid-rise"),
                                                            ("mastup", "skins hidden: mast up"))] + [(None, None)]],
          out / "sequence.png", "AWACS beam deploy sequence (direction E)", 640)


if __name__ == "__main__" and "--compose" in sys.argv:
    args = sys.argv[1:]
    compose_main(Path(args[args.index("--out") + 1]) if "--out" in args else OUT)
elif __name__ == "__main__":
    blender_main()
