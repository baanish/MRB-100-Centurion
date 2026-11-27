"""The Centurion's damage part tree: 45 parts, the old meshes each one takes, its cut planes, parent, braces and donor.

Pure Python, read by art/blender/damage_parts.py (in Blender) and art/blender/damage_finalize.py. The tree is the owner's
choice of 2026-11-22 (docs/DECISIONS.md), designed in the part map blockout (variant A).

Blender axes: nose toward -Y, +X is the pilot's left (_L), +Z up from the ground. Station = Y + 22.475 (docs/SPEC.md
"Origin"). Section cuts sit on the bay walls (forward bay 7.4 to 16.6, aft bay 23.6 to 32.6) and the bay roof (4.40 m),
so each bay is the belly slab under its roof, its own part carrying its hardpoint and doors, and the tank section above
it is one convex block.

A source is (old object, clip) where clip is a list of half-spaces: ('st'|'z', sign, value) keeps
sign * (coord - value) >= 0; ('ax', +1, v) keeps |X| >= v on the source's own side and ('ax', -1, v) keeps |X| <= v;
('x', sign, v) keeps sign * (X - v) >= 0; ('hinge', surface, d) keeps the side of a control surface's hinge line away
from the surface (d >= 0 moves it toward the surface) and ('hinge_own', surface, d) the surface's side plus d;
('stage_aft', 1, d) keeps a surface aft of the telescoping stages' trailing-edge line plus d; ('stage_fwd', 1, d) keeps
a shape forward of it. The clips of one old object over every part that takes it partition space, so each of its faces
lands on exactly one part.

A part's mesh is the skin inside its collision shape's region: where a shape stops short of a mesh (a strut end inside
the body or nacelle, the pylon root inside the wing, the sponson's inboard skin under the belly), that skin goes to the
neighbour whose shape covers it (spills). A `visual` object is drawn with the part but left out of its shape; `rigs`
are objects that stay separate (doors, gear, hatches, fans), re-parented onto the part. `hull_only` sources (the bay
doors, the control surfaces) shape the part's collider and mass but keep their own objects.
"""

ST0 = 22.475
CUT_COCKPIT, CUT_FWD, CUT_MID, CUT_AFT, CUT_TAIL = 7.4, 16.6, 23.6, 32.6, 38.3
BAY_ROOF = 4.40
CUT_WING = 12.6  # inner wing to outer wing, outboard of flap 2 (7.85 to 12.4) so each flap sits behind one wing part
BODY_HALF = 2.76  # body side: wing roots and sponsons meet the body sections on this plane
NOZZLE_SEAM = 21.95  # the nacelle cowl's aft lip (the nacelle mesh ends here); the nozzle is what shows aft of it
# The struts meet the nacelles on planes clear of the cowl and of the 11 cm collar fillet on it (cowl |X| 5.12 to 9.38):
# at 5.25 and 9.30 the planes shaved a strip of cowl skin into each strut, which moves with the wing, and its edge
# showed on the cowl as a hairline ending mid-panel (build 45, nacelle 1 outboard at 4 m from the intake)
STRUT_IN = (2.75, 4.98)  # inner strut between the body skin and the nacelle skin, |X| m
STRUT_OUT = (9.50, 5.30)  # outer strut outboard of the nacelle (|X| m) and under the wing's lower skin (m up)
PYLON = (5.30, 5.55)  # pylon between the nacelle crest and the wing's lower skin, m up
VTAIL_ROOT = 2.70  # V-tail fin outboard of the tail cone's skin, |X| m
# The cockpit's shape stops at the flight deck's notch (CenturionAuthor.FlightDeck's NotchHeight), so the escape hatches
# jettison and the seats ride their rails clear of it, as 0.1.3's notched nose shape let them; the canopy above is skin.
COCKPIT_NOTCH = 5.10
SURFACE_INSET = 0.015
# Parts that touch without a joint between them, whose shapes keep this gap (twice Unity's 10 mm contact offset, so no
# contact forms): a brace there would hold the piece that comes off on its own (the nozzle, the tail end) after its own
# joint broke, since a brace owned by its neighbour weakens with the neighbour's hit points, not the piece's. The first
# part of each pair is the one trimmed.
CLEAR_PAIRS = [("pylon_1", "nozzle_1"), ("pylon_2", "nozzle_2"), ("vtail_L", "tail_end"), ("vtail_R", "tail_end")]
CLEAR_GAP = 0.02
# Each fin root and tip share their skin-share mass so the root carries 70%: at 6 solver iterations a 1.1 t tip and its
# 0.3 t ruddervator hung on a 0.2 t root fin flexed up to 7 degrees on its joint and broke it at 1 g in level flight
# (runs 20261122-011947-dmg_circuit, -012959-dmg_wing_cycles); a fin's root spar is its heaviest structure.
MASS_SPLITS = {("vtail_L", "vtail_tip_L"): 0.7, ("vtail_R", "vtail_tip_R"): 0.7}  # control-surface shapes stand this far inside their skin (half their thickness where thinner)

BODY = ["nose", "fuselage_F", "fuselage_F_upper", "cheek_L", "cheek_R", "fuselage_F2", "fuselage_F2_upper",
        "fuselage_M", "fuselage_M_flank_L", "fuselage_M_flank_R", "wingfairing", "fuselage_R", "fuselage_R_upper_L",
        "fuselage_R_upper_R", "tailcone", "tailcone_upper", "tail_end", "tail_end_upper", "radar_R_fairing"]
WING_CENTRE = ["wing_root_L", "wing_root_R"]  # their |X| < BODY_HALF strip folds into the body sections
ABOVE, BELOW = ("z", 1, BAY_ROOF), ("z", -1, BAY_ROOF)

# The old (0.1.3) part each new part stands in for, where it keeps one: the author measures the aero, fittings and lights
# on that part's blockout shape, which the export carries as <part>_shape, so the 45-part tree flies as 0.1.3 did.
SHAPE_OF = {"radome": ["radar_F_fairing"], "cockpit": ["nose"], "Centurion": ["fuselage_M"],
            "wing_tele2_L": ["wing_tele2_L", "wing_tip_L"], "wing_tele2_R": ["wing_tele2_R", "wing_tip_R"]}

# Each part's origin (its transform, its tank's fire origin and the point its parent joint holds it by), Blender world
# metres, from the part map design's part table: the first moment of the 0.1.3 masses each part took over, moved at least
# 0.10 m inside its main shape, and the rear tank moved to station 28.70 so its fire reaches the tail section. The
# cockpit's is the flight deck's floor under the eyes (CenturionAuthor.FlightDeck's EyeStation and FloorHeight), where the
# flight deck stands its Cockpit. The root's is 0.1.3's root pivot (station 21.0, 3.95 m up), so every position the build
# and the plugin keep in the prefab's frame stays put; its tank's fire still reaches both neighbours and both bays. A
# part's mass acts at its shape's centroid, not here (damage_finalize.py).
ORIGINS = {
    "radome": (0.0, -18.9500, 3.9500), "cockpit": (0.0, -15.9250, 3.7500),
    "fuselage_F": (0.0, -9.6769, 4.8962), "bay_F": (0.0, -11.2624, 4.0565),
    "Centurion": (0.0, -1.475, 3.95), "fuselage_R": (0.0014, 6.2240, 4.4990),
    "bay_A": (-0.0013, 4.8510, 3.5244), "tailcone": (0.0006, 10.7956, 4.2570), "tail_end": (0.0, 16.4952, 4.6709),
    "wing_root_L": (3.3986, -3.9972, 6.1912), "wing_outer_L": (12.6990, -1.2288, 5.9286),
    "wing_tele1_L": (5.9916, -3.7700, 6.1227), "wing_tele2_L": (7.6995, -3.1702, 6.0416),
    "strut_inner_L": (2.8490, -5.2983, 2.4611), "strut_outer_L": (19.2864, 1.1889, 5.1990),
    "pylon_1": (7.2500, -3.4149, 5.4490), "nacelle_1": (7.4821, -6.9729, 3.4277),
    "nozzle_1": (7.2500, -0.4260, 3.8130), "sponson_L": (2.8590, 4.2860, 2.2842), "vtail_L": (2.7990, 13.9234, 3.8084),
    "vtail_tip_L": (4.7143, 16.6533, 5.1500), "flap_L1": (3.6150, -0.2250, 6.1960),
    "ruddervator_L1": (2.9606, 17.0067, 4.1375), "flap_L2": (7.9650, 0.2511, 5.9949),
    "ruddervator_L2": (4.7619, 18.0722, 5.1775), "aileron_L": (12.9150, 1.2368, 5.8016),
    "spoiler_L": (13.7666, 0.3862, 6.0189), "wing_root_R": (-3.3986, -3.9972, 6.1912),
    "wing_outer_R": (-12.6990, -1.2288, 5.9286), "wing_tele1_R": (-5.9916, -3.7700, 6.1227),
    "wing_tele2_R": (-7.6995, -3.1702, 6.0416), "strut_inner_R": (-2.8490, -5.2983, 2.4611),
    "strut_outer_R": (-19.2864, 1.1889, 5.1990), "pylon_2": (-7.2500, -3.4149, 5.4490),
    "nacelle_2": (-7.4821, -6.9729, 3.4277), "nozzle_2": (-7.2500, -0.4260, 3.8130),
    "sponson_R": (-2.8590, 4.2860, 2.2842), "vtail_R": (-2.7990, 13.9246, 3.8076),
    "vtail_tip_R": (-4.7143, 16.6533, 5.1500), "flap_R1": (-3.6150, -0.2250, 6.1960),
    "ruddervator_R1": (-2.9606, 17.0067, 4.1375), "flap_R2": (-7.9650, 0.2511, 5.9949),
    "ruddervator_R2": (-4.7619, 18.0722, 5.1775), "aileron_R": (-12.9150, 1.2368, 5.8016),
    "spoiler_R": (-13.7666, 0.3862, 6.0189),
}


def station(lo, hi):
    return ([("st", 1, lo)] if lo is not None else []) + ([("st", -1, hi)] if hi is not None else [])


def regions():
    """Body section name -> its clip."""
    return {"cockpit": station(None, CUT_COCKPIT), "fuselage_F": station(CUT_COCKPIT, CUT_FWD) + [ABOVE],
            "bay_F": station(CUT_COCKPIT, CUT_FWD) + [BELOW], "Centurion": station(CUT_FWD, CUT_MID),
            "fuselage_R": station(CUT_MID, CUT_AFT) + [ABOVE], "bay_A": station(CUT_MID, CUT_AFT) + [BELOW],
            "tailcone": station(CUT_AFT, CUT_TAIL), "tail_end": station(CUT_TAIL, None)}


def body(clip):
    return [(n, list(clip)) for n in BODY] + [(n, list(clip) + [("ax", -1, BODY_HALF)]) for n in WING_CENTRE]


def tree():
    """name -> dict(sources, hull_clip, parent, braces, donor, kind, hull_groups, visual, rigs, hull_only)."""
    t = {}
    reg = regions()

    def add(name, sources, parent, donor, braces=(), hull_clip=(), visual=(), rigs=(), hull_only=(), kind="section",
            hull_groups=()):
        t[name] = dict(sources=list(sources), parent=parent, donor=donor, braces=list(braces), hull_clip=list(hull_clip),
                       visual=list(visual), rigs=list(rigs), hull_only=list(hull_only), kind=kind,
                       hull_groups=[list(g) for g in hull_groups])

    def spill_to_body(src, clip):
        for part, rc in reg.items():
            t[part]["sources"].append((src, list(clip) + rc))

    add("radome", [("radar_F_fairing", [])], "cockpit", "nose")
    add("cockpit", body(reg["cockpit"]), "fuselage_F", "cockpit", braces=["Centurion"], hull_clip=[("z", -1, COCKPIT_NOTCH)],
        rigs=["nose_hatch_L", "nose_hatch_R", "nose_door", "gear_F", "geardoor_FL", "geardoor_FR"])
    add("fuselage_F", body(reg["fuselage_F"]), "Centurion", "fuselage_F")
    # The bay doors are closed at rest, so they are bay skin and inside the bay's shape.
    add("bay_F", body(reg["bay_F"]) + [("baydoor_FL_visible", []), ("baydoor_FR_visible", [])],
        "fuselage_F", "gearbay_L", braces=["Centurion", "cockpit"], kind="bay",
        hull_only=["baydoor_FL_visible", "baydoor_FR_visible"], rigs=["baydoor_FL", "baydoor_FR"])
    add("Centurion", body(reg["Centurion"]), None, "Darkreach")
    add("fuselage_R", body(reg["fuselage_R"]), "Centurion", "fuselage_R", rigs=["spine_cover", "spine_cover_A"])
    add("bay_A", body(reg["bay_A"]) + [("baydoor_AL_visible", []), ("baydoor_AR_visible", [])],
        "fuselage_R", "gearbay_L", braces=["Centurion"], kind="bay",
        hull_only=["baydoor_AL_visible", "baydoor_AR_visible"], rigs=["baydoor_AL", "baydoor_AR"])
    add("tailcone", body(reg["tailcone"]), "fuselage_R", "tail", braces=["bay_A"])
    add("tail_end", body(reg["tail_end"]), "tailcone", "tail", rigs=["laser_turret"])

    for s in "LR":
        n = "1" if s == "L" else "2"
        sx = 1 if s == "L" else -1
        out_x = ("x", sx, sx * BODY_HALF)
        add(f"wing_root_{s}", [(f"wing_root_{s}", [("ax", 1, BODY_HALF)]), (f"wing_outer_{s}", [("ax", -1, CUT_WING)]),
                               (f"pylon_{n}", [("z", 1, PYLON[1])])],
            "Centurion", "wing1b_L", braces=["fuselage_F", "fuselage_R"], visual=[f"flap_track_{s}1", f"flap_track_{s}2"],
            hull_clip=[("hinge", f"flap_{s}1", 0.0)], kind="wing", rigs=[f"flap_{s}1", f"flap_{s}2"])
        add(f"wing_outer_{s}", [(f"wing_outer_{s}", [("ax", 1, CUT_WING)]),
                                (f"strut_outer_{s}", [("ax", 1, STRUT_OUT[0]), ("z", 1, STRUT_OUT[1])])],
            f"wing_root_{s}", "wing2_L", hull_clip=[("stage_fwd", 1, -0.05)], kind="wing",
            rigs=[f"aileron_{s}", f"spoiler_{s}"])
        add(f"wing_tele1_{s}", [(f"wing_tele1_{s}", [])], f"wing_outer_{s}", "wing2_L", braces=[f"wing_root_{s}"], kind="stage")
        # two shapes: one hull over the straight stage and the raked, upswept tip, stood up to 0.5 m over the outer
        # wing's top skin when retracted
        add(f"wing_tele2_{s}", [(f"wing_tele2_{s}", []), (f"wing_tip_{s}", [])], f"wing_tele1_{s}", "wingtip_L",
            braces=[f"wing_outer_{s}", f"wing_root_{s}"], kind="stage", hull_groups=[[f"wing_tele2_{s}"], [f"wing_tip_{s}"]])
        add(f"strut_inner_{s}", [(f"strut_inner_{s}", [("ax", 1, STRUT_IN[0]), ("ax", -1, STRUT_IN[1])])], "Centurion",
            "wing1a_L", braces=[f"nacelle_{n}", f"strut_outer_{s}", "bay_F"], kind="strut")
        add(f"strut_outer_{s}", [(f"strut_outer_{s}", [("ax", 1, STRUT_OUT[0]), ("z", -1, STRUT_OUT[1])])],
            f"wing_outer_{s}", "wing1a_L", braces=[f"nacelle_{n}"], kind="strut")
        add(f"pylon_{n}", [(f"pylon_{n}", [("z", 1, PYLON[0]), ("z", -1, PYLON[1])])], f"wing_root_{s}", "nacelle_L",
            kind="engine")
        add(f"nacelle_{n}", [(f"nacelle_{n}", []), (f"nozzle_{n}", [("st", -1, NOZZLE_SEAM)]),
                             (f"strut_inner_{s}", [("ax", 1, STRUT_IN[1])]), (f"strut_outer_{s}", [("ax", -1, STRUT_OUT[0])]),
                             (f"pylon_{n}", [("z", -1, PYLON[0]), ("st", -1, NOZZLE_SEAM)])],
            f"pylon_{n}", "engine_L", braces=[f"wing_root_{s}"], rigs=[f"fan_{n}"], kind="engine")
        add(f"nozzle_{n}", [(f"nozzle_{n}", [("st", 1, NOZZLE_SEAM)]), (f"pylon_{n}", [("z", -1, PYLON[0]), ("st", 1, NOZZLE_SEAM)])],
            f"nacelle_{n}", "nozzle_L", kind="engine")
        sponson_own = [out_x, BELOW, ("st", -1, CUT_AFT)]
        add(f"sponson_{s}", [(f"sponson_{s}", sponson_own), (f"sponson_tail_{s}", sponson_own)], "Centurion", "gearbay_L",
            braces=["bay_A", "fuselage_R", "tailcone"], rigs=[f"gear_{s}M", f"geardoor_{s}M"], kind="gear")
        for src in (f"sponson_{s}", f"sponson_tail_{s}"):
            spill_to_body(src, [("ax", -1, BODY_HALF)])
            spill_to_body(src, [out_x, ABOVE])
            spill_to_body(src, [out_x, BELOW, ("st", 1, CUT_AFT)])
        spill_to_body(f"strut_inner_{s}", [("ax", -1, STRUT_IN[0])])
        add(f"vtail_{s}", [(f"vtail_{s}", [("ax", 1, VTAIL_ROOT)])], "tailcone", "vstab1_L",
            hull_clip=[("hinge", f"ruddervator_{s}1", 0.0)], kind="tail", rigs=[f"ruddervator_{s}1"])
        spill_to_body(f"vtail_{s}", [("ax", -1, VTAIL_ROOT)])
        add(f"vtail_tip_{s}", [(f"vtail_tip_{s}", [])], f"vtail_{s}", "vstab2_L",
            hull_clip=[("hinge", f"ruddervator_{s}2", 0.0)], kind="tail", rigs=[f"ruddervator_{s}2"])
        for f in ("1", "2"):
            surf = f"flap_{s}{f}"
            add(surf, [(f"{surf}_visible", [])], f"wing_root_{s}", "flap_L", kind="surface", hull_only=[f"{surf}_visible"],
                hull_clip=[("hinge_own", surf, 0.01)] + ([("stage_aft", 1, 0.05)] if f == "2" else []))
            rud = f"ruddervator_{s}{f}"
            add(rud, [(f"{rud}_visible", [])], f"vtail_{s}" if f == "1" else f"vtail_tip_{s}",
                "rudder_L", kind="surface", hull_only=[f"{rud}_visible"], hull_clip=[("hinge_own", rud, 0.01)])
        add(f"aileron_{s}", [(f"aileron_{s}_visible", [])], f"wing_outer_{s}", "aileron_L", kind="surface",
            hull_only=[f"aileron_{s}_visible"], hull_clip=[("stage_aft", 1, 0.06)])
        add(f"spoiler_{s}", [(f"spoiler_{s}_visible", [])], f"wing_outer_{s}", "aileron_L", kind="surface",
            hull_only=[f"spoiler_{s}_visible"])
    return t


# 0.1.3's prefab AeroPart masses (they sum to 124,700 kg, the empty mass less the C-RAM's 300 kg); the cockpit is the
# Unity-only box part inside the nose. Each new part starts at its skin-area share of the old parts it takes.
PREFAB_KG = {
    "fuselage_M": 12500, "nose": 9142.06, "fuselage_R": 8200, "nacelle_1": 8200, "nacelle_2": 8200,
    "wing_root_L": 6635, "wing_root_R": 6635, "wing_outer_L": 5625, "wing_outer_R": 5625, "fuselage_F2": 2950,
    "fuselage_F": 2550, "sponson_L": 2380, "sponson_R": 2380, "wing_tele1_L": 2200, "wing_tele1_R": 2200,
    "wing_tele2_L": 2060, "wing_tele2_R": 2060, "cockpit": 2000, "nozzle_1": 1600, "nozzle_2": 1600, "pylon_1": 1450,
    "pylon_2": 1450, "fuselage_R_upper_L": 1400, "fuselage_R_upper_R": 1400, "fuselage_F_upper": 1400,
    "fuselage_F2_upper": 1300, "strut_outer_L": 1290, "strut_outer_R": 1290, "tail_end": 1180, "sponson_tail_L": 1120,
    "sponson_tail_R": 1120, "fuselage_M_flank_L": 1000, "fuselage_M_flank_R": 1000, "vtail_tip_L": 990,
    "vtail_tip_R": 990, "tailcone_upper": 900, "tailcone": 777.94, "tail_end_upper": 700, "wingfairing": 600,
    "vtail_L": 510, "vtail_R": 510, "flap_L1": 500, "flap_L2": 500, "flap_R1": 500, "flap_R2": 500, "aileron_L": 500,
    "aileron_R": 500, "spoiler_L": 500, "spoiler_R": 500, "radar_F_fairing": 500, "strut_inner_L": 410,
    "strut_inner_R": 410, "ruddervator_L2": 334.53, "ruddervator_R2": 334.53, "wing_tip_L": 240, "wing_tip_R": 240,
    "ruddervator_L1": 165.47, "ruddervator_R1": 165.47, "cheek_L": 150, "cheek_R": 150, "flap_track_L1": 120,
    "flap_track_L2": 120, "flap_track_R1": 120, "flap_track_R2": 120,
}
TOTAL_KG = 124700.0
assert abs(sum(PREFAB_KG.values()) - TOTAL_KG) < 1, sum(PREFAB_KG.values())


if __name__ == "__main__":
    t = tree()
    print(len(t), "parts", sum(len(p["sources"]) for p in t.values()), "sources")
