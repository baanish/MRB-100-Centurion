"""MRB-100 Centurion proportion study: the step-5 blockout (build_centurion.py, loaded as a library and never edited)
rebuilt with a variant's proportions, measured and rendered with identical cameras in the M4 review look.

Render and measure (Blender):
  blender --background --factory-startup --python art/blender/proportion_study.py -- --variants current,D [--samples 48] [--out DIR]
Compose the comparison sheets from the renders (plain Python with Pillow):
  python -I art/blender/proportion_study.py --compose [--out DIR]

DIR defaults to <repo>/.cache/art/proportion_study. Blender writes <variant>_<view>_<span>.png at 1600 x 1000 and
metrics_<variant>.json; compose writes the sheets (sheet_*.png, D_sheet_*.png). docs/PROPORTION-STUDY.md reads them.

Round 2 (directions E, F and G and the D+A airframe, each with a straight strut on the T1 V-tail, then tail options T1
to T4 on the D+A airframe) runs the same way with "--round 2" on both commands; DIR defaults to
<repo>/.cache/art/proportion_study_r2 and the sheets are sheet_r2_*.png.

Round 3 (tails T5a, T5b, T2, T2 folded and T3 on direction E, T4 measured only, then E's wing group 2 m and 4 m aft on
T5a) runs with "--round 3"; DIR defaults to <repo>/.cache/art/proportion_study_r3 and the sheets are sheet_r3_*.png.
"--table --round 3" prints its tables. --views none measures without rendering.

Round 4 (the owner's picks on E: the 6.19 m body, the M4 nose scaled to it, a twin of 4.75 m late-UltraFans hung
close-coupled, the strut node at 19.4 m, the wing 2 m aft, a 10.5 deg strike; the strut-echo V-tail against T5a) runs
with "--round 4"; DIR defaults to <repo>/.cache/art/proportion_study_r4, the sheets are sheet_r4_*.png and
"--table --round 4" prints its tables.

Every variant keeps the hard constraints: retracted span 43.6 and extended 68.2 with the telescoping nesting, height
under 8 m with tail tips under 7.6 m, tail clearance of at least 12 deg, main gear at station 21, four engines under
the inner wing inboard of the strut node, the forward sweep and the truss strut. The owner's notes on volume (a fuller,
rounder fuselage and aft body) and on a bigger tail apply to every variant except "current", the blockout as built.
"""

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / ".cache" / "art" / "proportion_study"

# ---------- variants ----------
# Keys left out keep the blockout's value. Lengths in metres, angles in degrees, stations from the nose.
VOLUME = {"fus_half_w": 2.4, "fus_top": 6.4, "aft": "full"}  # owner: more girth, a fuller aft body; still round
VARIANTS = {
    "current": {"label": "Current blockout (step 5)"},
    "D": {"label": "D: owner sketch, H-tail", **VOLUME,
          # Fins run from just above the 12 deg clearance line to the 7.5 m cap; their lower half leans forward with
          # the 30 deg sweep, which is what lets it reach that low. fin_le is the fin's leading edge at the stabiliser.
          "htail": {"root_z": 5.6, "root_le": 33.6, "root_chord": 6.8, "tip_chord": 4.4, "x_fin": 6.6, "sweep": 25.0,
                    "elevator_hinge": 0.62, "fin_bottom": 3.8, "fin_top": 7.5, "fin_le": 35.45, "fin_bottom_chord": 3.2,
                    "fin_mid_chord": 4.8, "fin_top_chord": 3.2, "fin_sweep": 30.0, "rudder_hinge": 0.6}},
    "A": {"label": "A: minimal fix", **VOLUME,
          "chord": ((0.0, 7.2), (13.0, 4.3), (21.8, 3.3)), "thick": ((0.0, 0.86), (13.0, 0.47), (21.8, 0.36)),
          "tele_chords": (3.10, 2.90), "tip_rake": 38.0,
          "nacelle": {"kr": 1.0, "kl": 1.12, "core": 1.25, "under": 0.45},
          "vtail": {"dihedral": 32.0, "root_chord": 9.0, "tip_chord": 4.0, "sweep": 33.0, "root_station": 30.8, "hinge": 0.5}},
    "B": {"label": "B: Nuclear Option stylised", **VOLUME,
          "chord": ((0.0, 7.4), (13.0, 4.5), (21.8, 3.7)), "thick": ((0.0, 0.82), (13.0, 0.45), (21.8, 0.37)),
          "tele_chords": (3.48, 3.27), "tip_rake": 24.0, "tip_upsweep": 22.0, "strut_scale": 1.3,
          "nacelle": {"kr": 1.06, "kl": 1.04, "core": 1.1, "under": 0.45},
          "vtail": {"dihedral": 32.0, "root_chord": 9.6, "tip_chord": 5.2, "sweep": 28.0, "root_station": 30.4, "hinge": 0.5}},
    "C": {"label": "C: real-world TTBW", **VOLUME,
          "chord": ((0.0, 7.2), (14.0, 3.9), (21.8, 2.9)), "thick": ((0.0, 0.79), (14.0, 0.39), (21.8, 0.29)),
          "tele_chords": (2.72, 2.52), "tip_rake": 35.0, "tip_upsweep": 10.0, "strut_x": 14.0,
          "strut_ctrl": ((6.4, 20.3, 2.95), (12.6, 20.0, 4.1)),
          "engines_x": (6.6, 11.4), "nacelle": {"kr": 0.906, "kl": 1.19, "core": 1.3, "under": 0.42},
          "vtail": {"dihedral": 24.0, "root_chord": 7.6, "tip_chord": 3.2, "sweep": 38.0, "root_station": 31.4, "hinge": 0.5}},
}
# The recommendation: D's H-tail and volume on A's wing and nacelles.
VARIANTS["DA"] = {**{k: v for k, v in VARIANTS["A"].items() if k != "vtail"}, "htail": VARIANTS["D"]["htail"],
                  "label": "D+A: recommended, H-tail on the A wing"}
ORDER = ("current", "D", "A", "B", "C", "DA")

# ---------- round 2: three whole-aircraft directions, and D+A again, all with a straight strut ----------
# A straight strut from the lower fuselage to the node crosses the inner nacelle's disc in the rear view at any root
# height, so it passes behind the nozzle exits: the nacelles hang further forward ("under" 0.2: 80% of the cowl ahead
# of the wing leading edge, as on the 787), and the strut root moves aft into a gear sponson ("pod"). "strut" gives the
# root (off centreline, station, height), the node's semi-span and chord fraction, and the strut section. "plugs" are
# (from, to, added length) station ranges of constant barrel stretched after the build, so stations elsewhere in the
# table are the build's own. "aft" tunes the heavy-lifter aft body: crown held to "crown" then drooping "droop", sides
# held to "side" then closing by "close" over "close_len".
ROUND2_FULL_AFT = {"crown": 35.0, "droop": 0.5, "side": 34.0, "close": 0.55, "close_len": 8.0}
VARIANTS.update({
    "DA2": {**{k: v for k, v in VARIANTS["DA"].items() if k != "htail"}, "label": "D+A airframe, straight strut",
            "nacelle": {**VARIANTS["DA"]["nacelle"], "under": 0.2},
            "strut": {"root": (3.0, 21.0, 2.6), "node_x": 13.0, "node_chord": 0.68},
            "pod": {"station": 20.0, "half_len": 3.95, "half_w": 0.75, "half_h": 1.2, "cz": 2.4}},
    # C-17 / A400M heft: a 5.5 m round body on a lowered belly, long gear sponsons, anhedral, a strongly tapered wing,
    # 2 m more forward fuselage and nacelles 15% longer.
    "E": {"label": "E: heavy lifter", "fus_half_w": 2.75, "fus_top": 6.7, "fus_bottom": 1.2, "fus_p": 2.0,
          "upsweep_start": 26.0, "aft": {"crown": 36.0, "droop": 0.7, "side": 34.5, "close": 0.5, "close_len": 8.0},
          "plugs": ((9.0, 12.5, 2.0),), "dihedral": -2.5, "root_le": 15.25,
          "chord": ((0.0, 7.8), (13.0, 4.3), (21.8, 2.9)), "thick": ((0.0, 0.94), (13.0, 0.51), (21.8, 0.32)),
          "tele_chords": (2.72, 2.52), "tip_rake": 32.0, "tip_upsweep": 8.0,
          "nacelle": {"kr": 1.0, "kl": 1.15, "core": 1.25, "under": 0.22}, "nacelle_z": 3.8, "engines_x": (6.8, 11.2),
          "strut": {"root": (3.45, 22.6, 3.0), "node_x": 14.0, "node_chord": 0.68, "chord": 0.95, "thick": 0.29},
          "pod": {"station": 21.0, "half_len": 5.6, "half_w": 1.0, "half_h": 1.5, "cz": 2.6, "inset": 0.15},
          "main_gear": 21.5, "main_track": 7.0},
    # X-66 truss-braced wing as a bomber: slender wing with the node out at 15.5 m, slim long nacelles spread along
    # the span, 1 m more forward fuselage and 1 m more tail arm.
    "F": {"label": "F: slender truss-braced", **VOLUME, "fus_p": 2.0, "aft": ROUND2_FULL_AFT,
          "plugs": ((9.0, 12.5, 1.0), (24.6, 27.0, 1.0)), "root_le": 15.5,
          "chord": ((0.0, 6.8), (16.5, 3.1), (21.8, 2.5)), "thick": ((0.0, 0.74), (16.5, 0.33), (21.8, 0.25)),
          "tele_chords": (2.35, 2.2), "tip_rake": 36.0, "tip_upsweep": 10.0,
          "nacelle": {"kr": 0.9, "kl": 1.3, "core": 1.35, "under": 0.2}, "nacelle_z": 3.7, "engines_x": (6.0, 10.7),
          "strut": {"root": (2.95, 22.6, 2.3), "node_x": 15.5, "node_chord": 0.66, "chord": 0.8, "thick": 0.24},
          "pod": {"station": 21.0, "half_len": 3.8, "half_w": 0.75, "half_h": 1.2, "cz": 2.4},
          "main_gear": 21.5, "main_track": 6.0},
    # Nuclear Option's stylisation: 2.8 m shorter, a fatter body, Medusa's 0.43 taper on a broad wing with a cropped
    # tip, oversized nacelles and a chunky strut.
    "G": {"label": "G: game-stylised", "fus_half_w": 2.6, "fus_top": 6.8, "fus_p": 2.0,
          "aft": {"crown": 35.0, "droop": 0.4, "side": 34.0, "close": 0.5, "close_len": 8.0},
          "plugs": ((9.0, 12.5, -0.8), (24.8, 27.0, -2.0)), "root_le": 15.1,
          "chord": ((0.0, 8.4), (13.0, 5.0), (21.8, 3.6)), "thick": ((0.0, 0.92), (13.0, 0.53), (21.8, 0.37)),
          "tele_chords": (3.38, 3.17), "tip_rake": 18.0, "tip_upsweep": 6.0,
          "nacelle": {"kr": 1.12, "kl": 1.05, "core": 1.2, "under": 0.2}, "nacelle_z": 3.85, "engines_x": (6.4, 11.0),
          "strut": {"root": (3.2, 21.5, 2.5), "node_x": 13.0, "node_chord": 0.68, "chord": 1.05, "thick": 0.32},
          "pod": {"station": 20.3, "half_len": 4.1, "half_w": 0.85, "half_h": 1.3, "cz": 2.5},
          "main_gear": 21.0, "main_track": 6.5},
})
# Tail options, compared on the D+A airframe; T1 is also the provisional tail on every direction. Each keeps its tips
# (T2: folded) under 7.6 m, its span inside the 45.78 m door and 12 deg of tail clearance, and splits the V-tail
# group's 4,000 kg ("tail_mass", by part name without its side).
TAILS = {
    # T1: the biggest V-tail under the cap: a steeper 40 deg and the broadest chord.
    "T1": {"tail_label": "T1: bigger V-tail",
           "vtail": {"dihedral": 40.0, "root_z": 4.6, "root_chord": 10.0, "tip_chord": 5.6, "sweep": 30.0,
                     "root_station": 29.9, "hinge": 0.5}},
    # T2: a tall centreline fin whose upper 4.5 m folds onto the left for the hangar door, as the B-52's did, and a
    # low stabiliser. "fold" 90 is the hangar and taxi state.
    "T2": {"tail_label": "T2: folding fin, raised",
           "fintail": {"stab": {"root_z": 4.9, "root_le": 34.0, "root_chord": 6.4, "tip_chord": 3.2, "x_fin": 7.2,
                                "sweep": 30.0, "elevator_hinge": 0.62},
                       "fin": {"le": 32.4, "root_z": 5.6, "root_chord": 9.0, "hinge_z": 6.8, "hinge_chord": 7.6,
                               "top": 11.3, "tip_chord": 3.8, "sweep": 38.0, "rudder_hinge": 0.64, "rudder_from": 6.5,
                               "fold": 0}},
           "tail_mass": {"hstab": 1000, "elevator": 200, "fin": 700, "fin_fold": 600, "rudder_lower": 100, "rudder_upper": 200}},
    # T3: two fins canted 20 deg out from low on the aft-body sides, ahead of a separate low stabiliser (F/A-18). Rooted
    # on the shoulders they would stand 1.1 m under the cap.
    "T3": {"tail_label": "T3: twin canted fins",
           "canted": {"fins": {"dihedral": 70.0, "root_z": 4.6, "root_chord": 7.0, "tip_chord": 4.2, "sweep": 35.0,
                               "root_station": 28.6, "hinge": 0.65},
                      "stab": {"root_z": 4.9, "root_le": 35.6, "root_chord": 5.6, "tip_chord": 2.8, "x_fin": 6.6,
                               "sweep": 30.0, "elevator_hinge": 0.62}},
           "tail_mass": {"hstab": 800, "elevator": 150, "vtail": 900, "ruddervator": 150}},
    "T4": {"tail_label": "T4: H-tail (round 1 D)", "htail": VARIANTS["D"]["htail"]},
}
TAILS["T2f"] = {**TAILS["T2"], "tail_label": "T2: folding fin, folded",
                "fintail": {**TAILS["T2"]["fintail"], "fin": {**TAILS["T2"]["fintail"]["fin"], "fold": 90}}}
TAIL_ORDER = ("T1", "T2", "T2f", "T3", "T4")
for _d in ("E", "F", "G"):
    VARIANTS[_d].update({k: v for k, v in TAILS["T1"].items() if k != "tail_label"})
VARIANTS["F"]["vtail"] = {**TAILS["T1"]["vtail"], "root_station": 29.1}  # F's 1 m aft plug puts the tail further from the gear
for _t in TAIL_ORDER:
    VARIANTS[f"DA2_{_t}"] = {**VARIANTS["DA2"], **{k: v for k, v in TAILS[_t].items() if k != "tail_label"},
                             "label": TAILS[_t]["tail_label"]}
VARIANTS["DA2_T1"]["label"] = "D+A airframe (T1 V-tail)"
ORDER_R2 = ("DA2_T1", "E", "F", "G") + tuple(f"DA2_{t}" for t in TAIL_ORDER[1:])
OUT_R2 = REPO / ".cache" / "art" / "proportion_study_r2"
TAIL_TIP_MAX = 7.5  # top of the tail tip, 0.1 m under SPEC's 7.6
AERO_TAIL_M2 = 16.0  # CenturionAuthor: wingArea of each vtail and each ruddervator

# ---------- round 3: direction E with its tail, wing station, body and engines picked separately ----------
# Owner: tail strike "should be a real risk": rotation to 8 or 9 deg clears and more strikes, so every round 3 layout
# strikes at 9.5 to 10 deg (round 2: at least 12). The belly ramp runs at 9.75 deg and starts as late as that allows
# ("upsweep_start", tuned per wing station with --tune_strike 9.8), and the aft body keeps more of its section, the
# fuller heavy-lifter tail cone the owner asked for. The wing is rigged at 1.5 deg ("the wings should be really low
# incidence as they are huge"; the blockout's mesh rig is 2, the lift normal's 4.83 with the camber term).
R3_E = {**{k: v for k, v in VARIANTS["E"].items() if k != "vtail"}, "strike": 9.75, "incidence": 1.5,
        "aft": {"crown": 37.5, "droop": 0.5, "side": 36.0, "close": 0.35, "close_len": 7.0}}
R3_UPSWEEP = {0.0: 27.24, 2.0: 29.25, 4.0: 31.25}  # by wing_aft, from --tune_strike 9.8 (the big body's is 29.24)
# T5 (owner: "why not put the fins from T3 at the end of the horizontal stab"): T3's fins, canted 20 deg outward, as
# endplates on the tips of a flat stabiliser. "cant" leans each fin's top outboard about the stabiliser tip; the fin is
# one straight panel, so T5b's lower half leans inboard. Both are sized to the limits: fin tops at the 7.5 m cap, the
# stabiliser and fin feet over the strike line with the body touching first, every trailing edge ahead of the tail
# cone's end. The lower strike angle lets the stabiliser drop, so the fins grow. T5a's fin_bottom only buries the fin's
# root in the stabiliser; T5b's fins reach 1.6 m below it, so its stabiliser sits higher. T2, T3 and T4 are round 2's.
T5_STAB = {"root_le": 34.2, "root_chord": 6.6, "tip_chord": 4.6, "x_fin": 6.8, "sweep": 30.0, "elevator_hinge": 0.62}
TAILS_R3 = {
    "T5a": {"tail_label": "T5a: canted endplate fins, above the stabiliser",
            "htail": {**T5_STAB, "root_z": 4.2, "cant": 20.0, "fin_bottom": 4.05, "fin_top": 7.43, "fin_le": 35.6,
                      "fin_bottom_chord": 6.2, "fin_mid_chord": 6.8, "fin_top_chord": 4.2, "fin_sweep": 38.0,
                      "rudder_hinge": 0.62},
            "tail_mass": {"hstab": 1100, "elevator": 200, "fin": 550, "rudder_upper": 150}},
    "T5b": {"tail_label": "T5b: canted endplate fins, above and below",
            "htail": {**T5_STAB, "root_z": 5.0, "cant": 20.0, "fin_bottom": 3.4, "fin_top": 7.43, "fin_le": 36.0,
                      "fin_bottom_chord": 4.5, "fin_mid_chord": 6.0, "fin_top_chord": 4.2, "fin_sweep": 35.0,
                      "rudder_hinge": 0.62},
            "tail_mass": {"hstab": 1050, "elevator": 200, "fin": 550, "rudder_upper": 100, "rudder_lower": 100}},
}
for _t, _spec in {**{t: TAILS[t] for t in ("T2", "T2f", "T3", "T4")}, **TAILS_R3}.items():
    VARIANTS[f"E_{_t}"] = {**R3_E, **{k: v for k, v in _spec.items() if k != "tail_label"}, "upsweep_start": R3_UPSWEEP[0.0],
                           "label": _spec["tail_label"]}
# Owner: "the wing root needs to move further back". "wing_aft" moves the whole wing group (wing, strut node, engines and
# pylons, the strut root, its sponson and the main gear) aft by that many metres; the tail and fuselage stay.
for _d in (2, 4):
    VARIANTS[f"E{_d}_T5a"] = {**VARIANTS["E_T5a"], "wing_aft": float(_d), "upsweep_start": R3_UPSWEEP[float(_d)],
                              "label": f"E, wing group {_d} m aft (T5a)"}
# Body and engines, on the wing 2 m aft with T5a. Owner: "it's a bomber meant to lift a ton", so the body should read
# big against the engines (C-17 and An-124 nacelle over fuselage diameter about 0.4 to 0.45; E's 3.2 over 5.5 is 0.58).
# BIG_BODY is the largest round section whose wing fairing stays 5 cm under the 8 m door with the belly kept at E's
# 1.2 m. The strut root, sponson, gear track and nacelle height follow the body. "twin" is the owner's two-engine
# option: one GE9X-class nacelle a side (4.1 m outer, 3.65 m fan, 270 kN), the four engine groups' 22,500 kg split
# between two.
BIG_BODY = {"fus_half_w": 3.095, "fus_top": 7.39}


def r3_body(v, fus_half_w, fus_top):
    dz = fus_top - VARIANTS["E"]["fus_top"]
    r = v["strut"]["root"]
    return {**v, "fus_half_w": fus_half_w, "fus_top": fus_top, "strut": {**v["strut"], "root": (fus_half_w + 0.7, *r[1:])},
            "main_track": 2 * fus_half_w + 1.5, "nacelle_z": v["nacelle_z"] + dz}


NACELLE_28 = {"kr": 0.875, "kl": 1.3, "core": 1.35, "under": 0.22}  # 2.8 m outer, longer so the thrust still reads
TWIN = {"nacelle": {"kr": 1.281, "kl": 1.4, "core": 1.45, "under": 0.22}, "engine_mass": {"nacelle": 8200, "nozzle": 1600, "pylon": 1450}}


def r3_twin(v, x, dz=-0.45):
    return {**v, **TWIN, "engines_x": (x,), "nacelle_z": v["nacelle_z"] + dz}


# The twin hangs at 6.5 m: of 6.5, 7.5 and 8.5 m it leaves the most room to its nearest neighbour (1.74 m to the
# sponson, 1.96 m from the strut and 1.75 m from the jury strut to the nozzle; at 7.5 the jury strut closes to 1.24).
TWIN_X = 6.5
VARIANTS["E2_T5a_twin"] = {**r3_twin(VARIANTS["E2_T5a"], TWIN_X), "label": "E body, two 4.1 m nacelles"}
VARIANTS["EB2_T5a"] = {**r3_body(VARIANTS["E2_T5a"], **BIG_BODY), "label": "Big body, four 3.2 m nacelles"}
VARIANTS["EB2_T5a_n28"] = {**VARIANTS["EB2_T5a"], "nacelle": NACELLE_28, "label": "Big body, four 2.8 m nacelles"}
VARIANTS["EB2_T5a_twin"] = {**r3_twin(VARIANTS["EB2_T5a"], TWIN_X), "label": "Big body, two 4.1 m nacelles"}
ORDER_R3 = ("E_T5a", "E_T5b", "E_T2", "E_T2f", "E_T3", "E_T4", "E2_T5a", "E4_T5a", "E2_T5a_twin", "EB2_T5a",
            "EB2_T5a_n28", "EB2_T5a_twin")
BODY_TITLES = {"E2_T5a": "E body, four", "E2_T5a_twin": "E body, twin", "EB2_T5a": "Big body, four",
               "EB2_T5a_n28": "Big body, four slim", "EB2_T5a_twin": "Big body, twin"}
THRUST_KN = {4: 135.0, 2: 270.0}  # per engine: CenturionAuthor's staticThrust, and the owner's GE9X-class twin
OUT_R3 = REPO / ".cache" / "art" / "proportion_study_r3"
TAIL_PARTS = ("vtail", "ruddervator", "hstab", "fin_", "fin_fold", "elevator", "rudder_")

# AeroPart masses (kg) from unity/Assets/Centurion/Editor/CenturionAuthor.cs; each acts at its hull bounds' centre,
# as ConfigurePart places CoM. The cockpit (a donor mesh) is booked on the nose. Surfaces are 500 kg each.
MASS = {"fuselage_M": 15100, "fuselage_F": 8500, "nose": 5958.56 + 2000, "radar_F_fairing": 500, "fuselage_R": 11000,
        "tailcone": 7041.44, "vtail_L": 1500, "vtail_R": 1500, "strutfairing_L": 3500, "strutfairing_R": 3500,
        "wing_root_L": 12500, "wing_root_R": 12500, "strut_L": 1200, "strut_R": 1200, "jury_strut_L": 500,
        "jury_strut_R": 500, "wing_tele1_L": 2200, "wing_tele1_R": 2200, "wing_tele2_L": 2300, "wing_tele2_R": 2300,
        **{f"pylon_{n}": 725 for n in range(1, 5)}, **{f"nacelle_{n}": 4100 for n in range(1, 5)},
        **{f"nozzle_{n}": 800 for n in range(1, 5)}}
SURFACE_MASS = 500
CONTROL_SURFACES = ("flap_", "aileron_", "spoiler_", "ruddervator_", "elevator_", "rudder_")
# The H-tail keeps the V-tail group's 4,000 kg (2 x 1,500 panels + 2 x 500 ruddervators).
HTAIL_MASS = {"hstab": 1150, "fin": 400, "elevator": 250, "rudder_upper": 100, "rudder_lower": 100}

# ---------- round 4: the owner's picks after round 3 ----------
# E's 6.19 m round body, the wing group 2 m aft at 1.5 deg incidence, a 10.5 deg tail strike (the stock takeoff AI aims
# about 9.5 deg and its landing rollout about 10, so both clear) and a twin of late-UltraFan engines. Owner: "make
# nacelle bigger, and move engine higher, it still overlaps the truss"; "the truss should go almost to the end of the
# retracted wing"; the round 2 and 3 nose "looks goofy", keep the M4 detailed nose's shape; and a low-rooted V-tail
# "following the truss but slightly offset" (docs/concepts/owner/2026-10-12_rear_view_strut_echo_vtail_sketch.png),
# compared against T5a.
#
# A straight strut seen from the front is a line from its root to the node, and a nacelle hung under the wing is a disc
# spanning about 2.5 to 7.3 m, so the line misses the disc only if it passes under it. Three moves make that so: the
# strut roots at the bottom of the gear sponson (as on the X-66), the engine hangs as far inboard as the fuselage
# allows, and the nacelle is close-coupled, its fan nozzle ending at the wing leading edge with its crown level with
# the leading edge (as the 787 and 777X hang theirs), so the pylon is a short fairing.
R4_STRIKE = 10.5
NOSE_SCALE = 6.19 / 4.4  # the blockout nose (4.4 m tall, the M4 detailed nose's base) scaled to the 6.19 m body
# "x": semi-span; "crown_above_le": nacelle crown over the wing leading edge at that semi-span; "exit_behind_le": the
# fan nozzle petals' trailing edge against the leading edge. Lengths are along the engine axis from the intake plane.
ULTRAFAN = {"od": 4.75, "cowl": 7.4, "x": 6.0, "crown_above_le": 0.45, "exit_behind_le": -0.2, "petals": 16,
            "petal_len": 0.7, "core_len": 1.4, "plug_len": 0.9, "fan_blades": 22}
R4_STRUT = {"root": (3.35, 23.8, 1.45), "node_x": 19.4, "node_chord": 0.68, "chord": 0.95, "thick": 0.29,
            "jury": (0.58, 0.6)}  # jury strut from 58% of the strut up to 60% chord, outboard of the engine
# The UltraFan nacelle wall, (radius over the outer radius, distance aft of the intake plane over the cowl length):
# outer skin from the highlight to the trailing edge, where the petals take over, then the bypass duct and fan case
# forward to the inner lip.
UF_OUTER = ((0.915, -0.004), (0.95, 0.0), (0.975, 0.012), (0.993, 0.04), (1.0, 0.09), (1.0, 0.5), (0.985, 0.66),
            (0.955, 0.8), (0.915, 0.92), (0.89, 1.0))
UF_INNER = ((0.855, 1.0), (0.87, 0.75), (0.885, 0.45), (0.89, 0.2), (0.885, 0.1), (0.875, 0.035), (0.885, 0.01),
            (0.9, -0.003))


def uf_r(u):
    """The UltraFan cowl's outer radius over its maximum, u of the cowl length aft of the intake plane."""
    table = [(a, f) for f, a in UF_OUTER[1:]]
    u = min(max(u, 0.0), 1.0)
    for (a0, f0), (a1, f1) in zip(table, table[1:]):
        if u <= a1:
            return f0 + (f1 - f0) * (u - a0) / (a1 - a0)
    return table[-1][1]


R4_BASE = {**{k: v for k, v in VARIANTS["EB2_T5a"].items() if k not in ("nacelle", "nacelle_z", "htail", "tail_mass")},
           "strike": R4_STRIKE - 0.05, "nose_scale": NOSE_SCALE, "ultrafan": ULTRAFAN, "strut": R4_STRUT,
           "engine_mass": TWIN["engine_mass"]}
R4_UPSWEEP = 28.86  # from --tune_strike 10.5 (either tail), built station; the 2 m forward plug adds 2 to it
# The strut-echo V-tail: two panels rooted low on the aft body's sides, rising outboard at the owner's sketch angle (40
# deg; the strut itself rises at about 17, where a V-tail keeps 9% of its area in yaw). Sized so its yaw-effective area
# nearly matches T5a's with the roots clear of the 10.5 deg strike; swept 48 deg so the tips carry area aft for arm.
R4_VEE = {"dihedral": 40.0, "root_z": 3.2, "root_x": 1.78, "root_chord": 9.0, "tip_chord": 5.8, "sweep": 48.0,
          "root_station": 29.0, "hinge": 0.62}
VARIANTS["E4_vee"] = {**R4_BASE, "vtail": R4_VEE, "upsweep_start": R4_UPSWEEP,
                      "label": "Strut-echo V-tail (owner's sketch)"}
VARIANTS["E4_T5a"] = {**R4_BASE, **{k: v for k, v in TAILS_R3["T5a"].items() if k != "tail_label"},
                      "upsweep_start": R4_UPSWEEP, "label": "T5a: canted endplate fins"}
ORDER_R4 = ("E4_vee", "E4_T5a")
OUT_R4 = REPO / ".cache" / "art" / "proportion_study_r4"
THRUST_R4_KN = (270.0, 300.0)  # the owner's range for each late-UltraFan

# ---------- cameras (world: nose -Y, up +Z, left wing +X, Y = station - 21.5) ----------
VIEWS = {  # name: ("persp", lens) or ("ortho", scale), location, look-at target or euler degrees
    "hero": (("persp", 50), (56.0, -72.0, 44.0), (0.0, 0.0, 3.0)),
    "side": (("ortho", 50), (120.0, 0.0, 3.8), (90, 0, 90)),
    "top": (("ortho", 76), (0.0, 0.0, 80.0), (0, 0, 180)),
    "front": (("ortho", 76), (0.0, -120.0, 3.8), (90, 0, 0)),
    "rear": (("ortho", 30), (0.0, 120.0, 4.6), (90, 0, 180)),
    "rear_full": (("ortho", 76), (0.0, 120.0, 3.8), (90, 0, 180)),
    "side_pitch12": (("ortho", 50), (120.0, 0.0, 3.8), (90, 0, 90)),
    "front_close": (("ortho", 30), (0.0, -120.0, 4.6), (90, 0, 0)),
    "strut": (("persp", 40), (19.0, 17.0, 1.4), (7.5, -3.0, 3.8)),  # low behind the left wing, onto the strut
    # Round 4: front and rear framed on the retracted span, so the strut, nacelle and tail lines read; close-ups.
    "front_span": (("ortho", 48), (0.0, -120.0, 4.4), (90, 0, 0)),
    "rear_span": (("ortho", 48), (0.0, 120.0, 4.4), (90, 0, 180)),
    "nose34": (("persp", 50), (13.0, -38.0, 8.0), (0.0, -16.0, 4.3)),
    "nose_side": (("ortho", 17), (120.0, -14.5, 4.6), (90, 0, 90)),
    "engine34": (("persp", 40), (1.6, -27.0, 1.5), (6.0, -9.0, 4.0)),  # low ahead, inboard: intake and generator
    "engine_rear": (("persp", 38), (15.0, 8.0, 2.4), (6.0, -2.5, 4.8)),  # low behind, outboard: petals and core
    "strut_r4": (("persp", 38), (24.0, 20.0, 1.2), (9.0, -1.0, 3.6)),  # low behind the left wing, onto the strut
}
# Retracted frames zoom in; every variant still shares each state's cameras.
STATE_CAMERA = {"retracted": {"hero": ("persp", 62), "front": ("ortho", 50)}}
STATE_VIEWS = {"retracted": ("hero", "side", "top", "front", "rear", "rear_full", "side_pitch12"),
               "extended": ("hero", "side", "top", "front", "rear", "rear_full")}
STATE_CAMERA_R2 = {"retracted": {"hero": ("persp", 62), "front": ("ortho", 50), "rear_full": ("ortho", 50)}}
STATE_VIEWS_R2 = {"retracted": ("hero", "side", "top", "front", "rear_full", "rear", "front_close", "strut", "side_pitch12"),
                  "extended": ("hero", "side", "top", "front", "rear_full")}
STATE_VIEWS_R3 = {"retracted": ("hero", "side", "top", "front", "rear", "side_strike"),
                  "extended": ("hero", "side", "top", "front", "rear_full")}
STATE_VIEWS_R4 = {"retracted": ("hero", "side", "top", "front_span", "rear_span", "rear", "side_strike", "nose34",
                                "nose_side", "engine34", "engine_rear", "strut_r4"),
                  "extended": ("hero", "side", "top", "front", "rear_full")}
STRIKE_LINES = {"3": (9.5, 12.0), "4": (R4_STRIKE, 9.5)}  # red, amber (deg)
PAINT_SRGB = (0.38, 0.39, 0.405)  # m4/paint.py PAINT[HULL], the M4 renders' skin grey
RADOME_SRGB = (0.33, 0.335, 0.34)  # m4/paint.py PAINT[RADOME]


# =====================================================================================================================
# Blender side
# =====================================================================================================================
def blender_main():
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m4 import render as m4r
    from m4.blockout import load_blockout

    scene = bpy.context.scene

    # ---------- variant geometry on a fresh copy of the blockout ----------
    def configure(v):
        bc = load_blockout()
        w0 = bc.FUS_HALF_W
        bc.FUS_P = v.get("fus_p", bc.FUS_P)
        bc.FUS_BOTTOM = v.get("fus_bottom", bc.FUS_BOTTOM)
        if "upsweep_start" in v:  # the ramp's crease needs a ring at its station, in whichever part holds it
            bc.UPSWEEP_START = v["upsweep_start"]
            bc.FUSELAGE = tuple((n, tuple(sorted({*sts, bc.UPSWEEP_START})) if sts[0] < bc.UPSWEEP_START < sts[-1] else sts, o, p)
                                for n, sts, o, p in bc.FUSELAGE)
        if "strike" in v:  # round 3: the tail-strike angle, which the belly ramp runs parallel to
            bc.TAIL_STRIKE_MIN_DEG = v["strike"]
            bc.UPSWEEP_SLOPE = math.tan(math.radians(v["strike"]))
        if "incidence" in v:  # round 3: the wing's rig on the fuselage
            bc.INCIDENCE = math.radians(v["incidence"])
            bc.CDIR = Vector((0, math.cos(bc.INCIDENCE), -math.sin(bc.INCIDENCE)))
            bc.TDIR = Vector((0, math.sin(bc.INCIDENCE), math.cos(bc.INCIDENCE)))
        if "dihedral" in v:
            bc.DIHEDRAL = math.radians(v["dihedral"])
            bc.COS_G = math.cos(bc.DIHEDRAL)
            bc.XI_PER_X = 1 / (bc.COS_G * math.cos(bc.SWEEP))
            bc.XI_ROOT_TIP = bc.X_ROOT_TIP * bc.XI_PER_X
        aft = v.get("wing_aft", 0.0)
        bc.WING_ROOT_LE_STATION = v.get("root_le", bc.WING_ROOT_LE_STATION) + aft
        bc.NACELLE_Z = v.get("nacelle_z", bc.NACELLE_Z)
        if "fus_half_w" in v:
            bc.FUS_HALF_W, bc.FUS_TOP = v["fus_half_w"], v["fus_top"]
            bc.WING_ROOT_TOP = bc.FUS_TOP + 0.4
            bc.FUS_CENTER_Z = (bc.FUS_TOP + bc.FUS_BOTTOM) / 2
            dw = bc.FUS_HALF_W - w0
            bc.STRUT_ROOT = (bc.STRUT_ROOT[0] + dw, *bc.STRUT_ROOT[1:])
            bc.MAIN_TRACK += 2 * dw
        nose = {}
        if "nose_scale" in v:
            nose = configure_nose(bc, v)
        if v.get("aft") == "full":
            bc.fus_profile = full_profile(bc)
        elif isinstance(v.get("aft"), dict):
            bc.fus_profile = full_profile(bc, **v["aft"], **nose)
        if "chord" in v:
            bc.CHORD, bc.THICK = v["chord"], v["thick"]
            c1, c2 = v["tele_chords"]
            bc.TELE = ((bc.TELE[0][0], c1, *bc.TELE[0][2:]), (bc.TELE[1][0], c2, *bc.TELE[1][2:]))
        bc.TIP_RAKE = math.radians(v.get("tip_rake", 30.0))
        bc.TIP_UPSWEEP = math.radians(v.get("tip_upsweep", 12.0))
        bc.STRUT_WING_X = v.get("strut_x", bc.STRUT_WING_X)
        bc.STRUT_CTRL = v.get("strut_ctrl", bc.STRUT_CTRL)
        if "strut" in v:
            r = v["strut"]["root"]
            bc.STRUT_ROOT, bc.STRUT_WING_X = (r[0], r[1] + aft, r[2]), v["strut"]["node_x"]
            bc.STRUT_NODE_CHORD = v["strut"]["node_chord"]
            bc.JURY_T, bc.JURY_TOP_CHORD = v["strut"].get("jury", (bc.JURY_T, bc.JURY_TOP_CHORD))
            bc.build_struts = straight_strut_builder(bc, v["strut"], {**v["pod"], "station": v["pod"]["station"] + aft})
            build_doors = bc.build_geardoors

            def nose_doors_only(parts):  # the main doors are cut to the blockout pod at station 19 (adapt drops them)
                root, bc.STRUT_ROOT = bc.STRUT_ROOT, (2.6, 19.0, 2.6)
                build_doors(parts)
                bc.STRUT_ROOT = root
            bc.build_geardoors = nose_doors_only
        bc.MAIN_GEAR_STATION = v.get("main_gear", bc.MAIN_GEAR_STATION) + aft
        bc.MAIN_TRACK = v.get("main_track", bc.MAIN_TRACK)
        bc.ROOT_QC = bc._root_qc()
        bc.AILERON_HINGE_BEHIND_QC = 0.75 * bc.TELE[0][1] + 0.06
        if "nacelle" in v:
            configure_engines(bc, v)
        if "ultrafan" in v:
            configure_ultrafan(bc, v["ultrafan"])
        if "vtail" in v:
            configure_vtail(bc, v["vtail"])
        if "htail" in v:
            bc.build_vtail = htail_builder(bc, v["htail"])
        configure_tail(bc, v)
        return bc

    def full_profile(bc, crown=35.0, droop=0.5, side=34.0, close=0.55, close_len=8.0, nose_k=1.0, nose_kw=1.0,
                     nose_map=None):
        """The blockout's profile with a heavy-lifter aft body: by default the crown holds to station 35 and droops
        0.5 m, the sides hold to 34 and close to 45% of the half width instead of 15%. The belly keeps the 12 deg ramp
        from UPSWEEP_START (27 on the blockout). Round 4: nose_k and nose_kw stretch the blockout's nose profile lengths
        in side view and in plan, and the nose is shaped at its final station (nose_map, through the plugs), so a plug
        inside the nose doesn't stretch it."""
        W, TOP = bc.FUS_HALF_W, bc.FUS_TOP

        def fus_profile(s):
            n = nose_map(s) if nose_map else s
            w = W * bc.ell(n / (7.0 * nose_kw), 1.6)
            top = bc.NOSE_TIP_Z + (TOP - bc.NOSE_TIP_Z) * bc.ell(n / (9.0 * nose_k), 1.5)
            bot = bc.NOSE_TIP_Z - (bc.NOSE_TIP_Z - bc.FUS_BOTTOM) * bc.ell(n / (4.5 * nose_k), 1.7)
            if s > bc.UPSWEEP_START:
                bot = bc.FUS_BOTTOM + bc.UPSWEEP_SLOPE * (s - bc.UPSWEEP_START)
            if s > crown:
                top = TOP - droop * ((s - crown) / (42.0 - crown)) ** 2
            if s > side:
                w = W * (1 - close * (min(s - side, close_len) / close_len) ** 1.8)
            return w, top, bot
        return fus_profile

    def side_x(bc, s, z):
        """Half width of the fuselage skin at a station and height."""
        w, top, bot = bc.fus_profile(s)
        zc, h = (top + bot) / 2, (top - bot) / 2
        u = min(abs(z - zc) / h, 1.0)
        return w * (1 - u ** bc.FUS_P) ** (1 / bc.FUS_P)

    def configure_nose(bc, v):
        """Round 4: the blockout's nose (the M4 detailed nose's base surface) scaled by nose_scale to the body: the
        radome tip keeps its share of the body height, the side-view profile lengths, the radome joint and the four
        windscreen panes scale with it, and the plan-view lengths scale with the width (the body is round, the
        blockout's 4.0 m wide), so the nose keeps the M4's point in plan as well. Returns full_profile's arguments."""
        k = v["nose_scale"]
        bc.NOSE_TIP_Z = bc.FUS_BOTTOM + (3.0 - 1.6) / 4.4 * (bc.FUS_TOP - bc.FUS_BOTTOM)
        bc.PANES = tuple((s0 * k, s1 * k, a0, a1) for s0, s1, a0, a1 in bc.PANES)
        radome = tuple(round(s * k, 3) for s in (0.15, 0.4, 0.8, 1.3, 1.9, 2.5))
        stations = {"radar_F_fairing": (radome, radome[-1], "nose"),
                    "nose": ((radome[-1], 4.0, 4.45, 4.85, 5.25, 5.7, 6.1, 6.55, 7.0), 7.0, "fuselage_F"),
                    "fuselage_F": ((7.0, 8.5, 9.75, 11.0, 13.0, 15.0), 15.0, "fuselage_M")}
        bc.FUSELAGE = tuple((n, *stations[n]) if n in stations else (n, sts, o, p) for n, sts, o, p in bc.FUSELAGE)
        bc.R4_NOSE = {"k": k, "radome_joint": radome[-1]}
        return {"nose_k": k, "nose_kw": bc.FUS_HALF_W / 2.0, "nose_map": station_map(v.get("plugs", ()))}

    def nose_details(bc, v, parts):
        """Round 4: block the M4 nose's dark windscreen surround, a frame round each of the four panes and the centre
        post between the front pair (beside the glass, never under it: the blockout's panes are coarse facets that
        sink below a finer panel), and a dark joint band where the radome meets the nose."""
        if "nose_scale" not in v:
            return
        k = v["nose_scale"]
        bm = next(p for p in parts if p["name"] == "nose")["bm"]
        w, da = 0.12 * k, 4.0  # frame width along the fuselage (m) and round it (deg)
        strips = [((bc.PANES[0][0], bc.PANES[0][1]), -bc.PANES[0][2], bc.PANES[0][2])]  # the centre post
        for s0, s1, a0, a1 in bc.PANES:
            for sg in (1, -1):
                lo, hi = sorted((sg * a0, sg * a1))
                strips += [((s0 - w, s0), lo - da, hi + da), ((s1, s1 + w), lo - da, hi + da),
                           ((s0, s1), lo - da, lo), ((s0, s1), hi, hi + da)]
        for (s0, s1), a0, a1 in strips:
            for f in bc.skin_panel(bm, [s0 + (s1 - s0) * i / 4 for i in range(5)], a0, a1, -0.01, 0.016, n_a=3):
                f.material_index = 1
        j = bc.R4_NOSE["radome_joint"]
        for f in bc.skin_panel(bm, (j, j + 0.035 * k, j + 0.07 * k), -179.0, 179.0, -0.01, 0.012, n_a=36):
            f.material_index = 1

    def configure_ultrafan(bc, e):
        """Round 4: one late-UltraFan a side (docs/DECISIONS.md, 2026-10-12), hung close-coupled: its crown at the
        wing leading edge's height and its fan nozzle petals ending at the leading edge. Sets the blockout's engine
        table and surfaces; ultrafan_builder replaces build_engines."""
        r, x = e["od"] / 2, e["x"]
        le = bc.wing_le(1, x)[0]
        exit_st = le.y + bc.Y0 + e["exit_behind_le"]
        front = exit_st - e["petal_len"] - e["cowl"]
        bc.NACELLE_Z = le.z + e["crown_above_le"] - r
        bc.NACELLES = ((1, 1, x, round(front, 3)), (2, -1, x, round(front, 3)))
        bc.NACELLE_LEN = e["cowl"]
        bc.NACELLE_OUTER = tuple((r * f, e["cowl"] * a) for f, a in UF_OUTER)
        bc.CORE_PROFILE = ((0, e["petal_len"] + e["core_len"] + e["plug_len"]),)  # for the metrics' overall length
        # The node near the retracted tip leaves no span outboard of it, so the ailerons run inboard of it: the node
        # fitting sits on the lower skin at 68% chord, ahead of their hinge line.
        bc.SURFACES = (("flap_{s}1", bc.FUS_HALF_W + 0.35, x - 0.6, "flap"), ("flap_{s}2", x + 0.6, 12.4, "flap"),
                       ("aileron_{s}", 12.8, 19.6, "aileron"), ("spoiler_{s}", 12.8, 19.4, "spoiler"))
        bc.build_engines = ultrafan_builder(bc, e)

    def ultrafan_builder(bc, e):
        """A blockout late-UltraFan: a huge fan in a long nacelle, a generator fairing with cooling scoops on the
        cowl's lower inboard side, variable-area fan nozzle petals, a third-stream exit ring stepping down the core
        cowl, and a stout core nozzle round a short plug. Parts and parents as the blockout's engines."""
        r, L, seg = e["od"] / 2, e["cowl"], 48
        Y = Vector((0, 1, 0))
        outer = [(r * f, L * a) for f, a in UF_OUTER]
        inner = [(r * f, L * a) for f, a in UF_INNER]
        pl, cl = e["petal_len"], e["core_len"]

        def oriented_box(bm, base, axes, size):
            pts = [base + axes[0] * (sx * size[0] / 2) + axes[1] * (sy * size[1] / 2)
                   for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            return bc.loft(bm, [pts, [p + axes[2] * size[2] for p in pts]])

        def build(parts):
            for num, side, x, front in bc.NACELLES:
                sfx = "_L" if side > 0 else "_R"
                c = Vector((side * x, bc.st(front), bc.NACELLE_Z))
                rad = lambda th: Vector((side * math.sin(math.radians(th)), 0, math.cos(math.radians(th))))
                bm = bmesh.new()
                n_out = len(outer)
                faces = bc.revolve(bm, outer + inner, c, seg=seg, loop=True, seams=(0, seg // 2),
                                   ring_seams=(0, n_out - 1, n_out, len(outer + inner) - 1))
                for f in faces[(n_out + 0) * seg:(n_out + 2) * seg]:  # the bypass duct behind the fan
                    f.material_index = 1
                # Generator fairing on the lower inboard cowl: a long blister with two cooling scoops at its nose
                # and an exhaust slot at its tail (the geared fan drives a multi-megawatt generator).
                th, w, h = -135.0, 1.4, 0.34
                n_r = rad(th)
                t_r = Y.cross(n_r).normalized()
                bulge = lambda u: math.sin(math.pi * (u - 0.22) / 0.58) ** 0.6 if 0.22 < u < 0.8 else 0.0
                rings = []
                for u in (0.22, 0.27, 0.36, 0.5, 0.64, 0.74, 0.8):
                    base = c + Y * (L * u) + n_r * (r * uf_r(u) - 0.12)
                    rings.append([base + t_r * (0.5 * w * max(bulge(u), 0.05) * math.cos(math.pi * i / 10))
                                  + n_r * ((0.12 + h * bulge(u)) * math.sin(math.pi * i / 10)) for i in range(11)])
                bc.loft(bm, rings)
                for dt in (-0.3, 0.3):  # two cooling scoops standing on the blister's forward crown
                    p = c + Y * (L * 0.31) + n_r * (r * uf_r(0.31) + h * bulge(0.31) - 0.05) + t_r * dt
                    for f in oriented_box(bm, p, (t_r, Y, n_r), (0.34, 0.55, 0.15)):
                        f.material_index = 1
                add = bc.add_part
                add(parts, f"nacelle_{num}", bm, c, f"pylon_{num}", mats=(bc.SKIN, bc.MECH),
                    col=bc.airframe([[c + Y * a + rad(360 * i / 32) * rr for i in range(32)] for rr, a in outer]))

                # Fan: a big spinner and wide-chord blades out to the fan case, 1.1 m behind the intake plane.
                fc = c + Y * (0.15 * L)
                bm = bmesh.new()
                bc.revolve(bm, [(0, -0.9 * r * 0.4), (0.18 * r, -0.62 * r * 0.4), (0.26 * r, -0.2 * r * 0.4),
                                (0.29 * r, 0.1), (0.29 * r, 0.4), (0, 0.45)], fc, seg=24)
                nb = e["fan_blades"]
                for i in range(nb):
                    phi = 2 * math.pi * (i + 0.5) / nb
                    er, et = Vector((math.sin(phi), 0, math.cos(phi))), Vector((math.cos(phi), 0, -math.sin(phi)))
                    rings = []
                    for rr, beta, chord, tk in ((0.27, 58, 0.52, 0.08), (0.55, 42, 0.62, 0.06), (0.85, 28, 0.66, 0.04)):
                        b = math.radians(beta)
                        cd = et * math.cos(b) + Y * math.sin(b)
                        nd = er.cross(cd).normalized()
                        p = fc + er * (rr * r)
                        rings.append([p + cd * (u * chord / 2) + nd * (q * tk / 2) for u, q in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
                    bc.loft(bm, rings)
                add(parts, f"fan_{num}", bm, fc, f"nacelle_{num}", mats=(bc.MECH,), spin_axis=[0.0, 1.0, 0.0])

                # Nozzle: variable-area petals off the cowl's trailing edge (notched between petals), the core cowl
                # with the third-stream exit ring stepping it down, the core nozzle and the plug.
                rear = c + Y * L
                rt, rti = r * UF_OUTER[-1][0], r * UF_INNER[0][0]
                petals = [(rt - 0.025, 0.0), (rt - 0.11, pl), (rti - 0.07, pl), (rti - 0.01, 0.0)]
                np_ = e["petals"]

                def notch(pi, i, rr, a):  # a narrow V-notch between petals
                    return (rr, a - 0.3) if pi in (1, 2) and i % 6 == 0 else (rr, a)
                bm = bmesh.new()
                bc.revolve(bm, petals, rear, seg=6 * np_, loop=True, shape=notch)
                core = [(0.0, -0.6 * L), (0.5 * r, -0.6 * L), (0.53 * r, 0.0), (0.54 * r, pl + 0.55), (0.555 * r, pl + 0.62),
                        (0.49 * r, pl + 0.64), (0.47 * r, pl + cl), (0.4 * r, pl + cl + 0.02), (0.0, pl + cl + 0.02)]
                faces = bc.revolve(bm, core, rear, seg=seg)
                for f in faces[3 * seg:4 * seg] + faces[5 * seg:]:  # the third-stream exit face and the core nozzle
                    f.material_index = 1
                plug = [(0.0, pl + cl - 0.4), (0.3 * r, pl + cl - 0.4), (0.3 * r, pl + cl + 0.1),
                        (0.2 * r, pl + cl + 0.6 * e["plug_len"]), (0.0, pl + cl + e["plug_len"])]
                for f in bc.revolve(bm, plug, rear, seg=seg // 2):
                    f.material_index = 1
                add(parts, f"nozzle_{num}", bm, rear, f"nacelle_{num}", mats=(bc.SKIN, bc.MECH))

                # Pylon: a short fairing from the nacelle's aft crown into the wing leading edge and underside,
                # closing over the core under the wing.
                le, ch, _ = bc.wing_le(side, x)
                le_st = le.y + bc.Y0
                crown = lambda s: bc.NACELLE_Z + r * uf_r((s - front) / L) - 0.12 if s < front + L else bc.NACELLE_Z + 0.55 * r - 0.1
                under = lambda s: bc.wing_lower(side, x, s).z + 0.15

                def ring(s, bot, top, half):
                    mid = bot + 0.4 * (top - bot)
                    return [Vector((side * x + dx * half, bc.st(s), z)) for dx, z in
                            ((-0.7, bot), (0.7, bot), (1.0, mid), (0.75, top), (-0.75, top), (-1.0, mid))]
                s0 = front + 0.45 * L
                rings = [ring(s0, crown(s0), crown(s0) + 0.12, 0.12),
                         ring(le_st - 1.6, crown(le_st - 1.6), max(le.z - 0.25, crown(le_st - 1.6) + 0.3), 0.32),
                         ring(le_st + 0.4, crown(le_st + 0.4), under(le_st + 0.4), 0.36),
                         ring(le_st + 2.2, crown(le_st + 2.2), under(le_st + 2.2), 0.34),
                         ring(le_st + 3.4, under(le_st + 3.4) - 0.3, under(le_st + 3.4), 0.12)]
                bm = bmesh.new()
                bc.loft(bm, rings, seams=(0, 1, 3, 4))
                attach = bc.wing_lower(side, x, le_st + 0.25 * ch)
                add(parts, f"pylon_{num}", bm, Vector((side * x, attach.y, attach.z)), "wing_root" + sfx,
                    col=bc.airframe(rings))
        return build

    def configure_engines(bc, v):
        n = v["nacelle"]
        kr, kl, kc = n["kr"], n["kl"], n["core"]
        sc = lambda prof: tuple((r * kr, a * kl) for r, a in prof)
        bc.NACELLE_OUTER, bc.NACELLE_INNER = sc(bc.NACELLE_OUTER), sc(bc.NACELLE_INNER)
        bc.NACELLE_LEN, bc.FAN_STATION_OFFSET = bc.NACELLE_LEN * kl, bc.FAN_STATION_OFFSET * kl
        bc.SLEEVE_PROFILE = sc(bc.SLEEVE_PROFILE)
        bc.CORE_PROFILE = tuple((r * kr, a * kc) for r, a in bc.CORE_PROFILE)
        xs, node = v.get("engines_x", (6.0, 10.4)), bc.STRUT_WING_X
        if len(xs) == 1:  # round 3 twin: nacelle_1 left, nacelle_2 right; the outer flap runs to the strut node
            engines, flaps = ((1, 1, xs[0]), (2, -1, xs[0])), ((bc.FUS_HALF_W + 0.35, xs[0] - 0.35), (xs[0] + 0.35, node - 0.5))
        else:
            xi, xo = xs
            engines = ((1, 1, xo), (2, 1, xi), (3, -1, xi), (4, -1, xo))
            flaps = ((bc.FUS_HALF_W + 0.35, xi - 0.35), (xi + 0.35, xo - 0.35))
        nac = []
        for num, side, x in engines:
            le = bc.wing_le(side, x)[0].y + bc.Y0
            nac.append((num, side, x, round(le - (1 - n["under"]) * bc.NACELLE_LEN, 3)))
        bc.NACELLES = tuple(nac)
        bc.SURFACES = (("flap_{s}1", *flaps[0], "flap"), ("flap_{s}2", *flaps[1], "flap"),
                       ("aileron_{s}", node + 0.5, 19.6, "aileron"), ("spoiler_{s}", node + 0.5, 19.4, "spoiler"))

    def configure_vtail(bc, t):
        dih = math.radians(t["dihedral"])
        bc.VTAIL_DIHEDRAL, bc.VTAIL_SWEEP = dih, math.radians(t["sweep"])
        bc.VTAIL_ROOT_CHORD, bc.VTAIL_TIP_CHORD = t["root_chord"], t["tip_chord"]
        bc.VTAIL_ROOT_STATION = t["root_station"]
        bc.VTAIL_ROOT_Z = t.get("root_z", 4.6)
        tip_half_thick = 0.5 * 0.07 * t["tip_chord"] * math.cos(dih)
        bc.VTAIL_SPAN = (TAIL_TIP_MAX - bc.VTAIL_ROOT_Z - tip_half_thick) / math.sin(dih)
        bc.RUDDERVATOR_HINGE = t["hinge"]
        bc.RUDDERVATOR_SPAN = (0.55, bc.VTAIL_SPAN - 0.35)
        # The root line runs where the skin is narrowest along the root chord, so no part of it stands proud.
        s0 = t["root_station"]
        # Round 4 sets it: a root low on the aft body would reach the belly at the root's trailing edge.
        root_x = t.get("root_x", min(side_x(bc, s0 + k * t["root_chord"] / 6, bc.VTAIL_ROOT_Z) for k in range(7)) - 0.1)
        bc.VTAIL_ROOT_X = root_x

        def vtail_section(side, d, cut=None, t0=None):
            span_dir = Vector((side * math.cos(dih), 0, math.sin(dih)))
            normal = Vector((-side * math.sin(dih), 0, math.cos(dih)))
            root_le = Vector((side * root_x, bc.st(s0), bc.VTAIL_ROOT_Z))
            f = d / bc.VTAIL_SPAN
            chord = t["root_chord"] + (t["tip_chord"] - t["root_chord"]) * f
            le = root_le + span_dir * d + Vector((0, d * math.tan(bc.VTAIL_SWEEP), 0))
            thick = chord * (0.10 - 0.03 * max(f, 0))
            if t0 is not None:
                return (bc.airfoil_aft(le, chord, thick, Vector((0, 1, 0)), normal, 0.0, t0),
                        bc.camber_point(le, chord, Vector((0, 1, 0)), normal, 0.0, t0))
            return bc.airfoil(le, chord, thick, Vector((0, 1, 0)), normal, cut=cut), root_le
        bc.vtail_section = vtail_section

    def htail_builder(bc, h):
        """H-tail: a flat stabiliser out of the fuselage sides with elevators, twin fins on its tips reaching above
        and below it, each fin with an upper and a lower rudder split at the stabiliser."""
        Y = Vector((0, 1, 0))
        sweep, fin_sweep = math.tan(math.radians(h["sweep"])), math.tan(math.radians(h.get("fin_sweep", 0.0)))
        z0, xf = h["root_z"], h["x_fin"]
        x_body = side_x(bc, h["root_le"] + 0.5 * h["root_chord"], z0)
        with_fins = h.get("fins", True)  # round 2's T2 and T3 use the stabiliser alone

        def stab_le(x):
            f = max(x - x_body, 0.0) / (xf - x_body)
            chord = h["root_chord"] + (h["tip_chord"] - h["root_chord"]) * f
            return h["root_le"] + max(x - x_body, 0.0) * sweep, chord

        def stab_section(side, x, cut=None, t0=None):
            s, c = stab_le(x)
            le = Vector((side * x, bc.st(s), z0))
            th = c * 0.10
            up = Vector((0, 0, 1))
            if t0 is not None:
                return bc.airfoil_aft(le, c, th, Y, up, 0.0, t0), bc.camber_point(le, c, Y, up, 0.0, t0)
            return bc.airfoil(le, c, th, Y, up, cut=cut)

        def fin_le(z):
            chord = bc.interp(((h["fin_bottom"], h["fin_bottom_chord"]), (z0, h["fin_mid_chord"]),
                               (h["fin_top"], h["fin_top_chord"])), z)
            return h["fin_le"] + (z - z0) * fin_sweep, chord

        # Round 3's T5 leans each fin's top outboard by "cant" about the stabiliser tip; sections stay horizontal.
        cant = math.radians(h.get("cant", 0.0))

        def fin_section(side, z, cut=None, t0=None):
            s, c = fin_le(z)
            le = Vector((side * (xf + (z - z0) * math.tan(cant)), bc.st(s), z))
            n = Vector((side * math.cos(cant), 0, -math.sin(cant)))
            th = c * 0.09
            if t0 is not None:
                return bc.airfoil_aft(le, c, th, Y, n, 0.0, t0), bc.camber_point(le, c, Y, n, 0.0, t0)
            return bc.airfoil(le, c, th, Y, n, cut=cut)

        gap = bc.SURF_GAP

        def build(parts, side):
            sfx = "_L" if side > 0 else "_R"
            e0, e1 = x_body + 0.3, xf - 0.35
            xs = sorted({0.6, x_body, (x_body + xf) / 2, xf, e0 - gap - 0.01, e0 - gap, e1 + gap, e1 + gap + 0.01})
            rings = [stab_section(side, x, h["elevator_hinge"] if e0 - gap - 1e-6 <= x <= e1 + gap + 1e-6 else None) for x in xs]
            bm = bmesh.new()
            bc.loft(bm, rings, seams=bc.AF_SEAMS, soft=(bc.AF_N,), cap_mat=(1, None))
            s_root, c_root = stab_le(x_body)
            origin = Vector((side * x_body, bc.st(s_root + 0.25 * c_root), z0))
            bc.add_part(parts, "hstab" + sfx, bm, origin, "tailcone", mats=(bc.SKIN, bc.STRUCT))
            t0 = h["elevator_hinge"] + 0.02 / h["tip_chord"]
            secs = [stab_section(side, x, t0=t0) for x in (e0, (e0 + e1) / 2, e1)]
            bm = bmesh.new()
            bc.loft(bm, [r for r, _ in secs], seams=bc.AFT_SEAMS)
            bc.add_hinged(parts, "elevator" + sfx, bm, secs[0][1], "hstab" + sfx, secs[-1][1] - secs[0][1])
            if not with_fins:
                return

            zb, zt = h["fin_bottom"], h["fin_top"]
            th0 = 0.5 * 0.10 * stab_le(xf)[1] + 0.12  # rudders stop clear of the stabiliser's thickness
            spans = {"rudder_lower": (zb + 0.2, z0 - th0), "rudder_upper": (z0 + th0, zt - 0.25)}
            if z0 - zb < 1.0:  # T5a: the fin's foot only buries its root in the stabiliser, so no lower rudder
                del spans["rudder_lower"]
            zs = {zb, zt, z0, (zb + z0) / 2, (z0 + zt) / 2}
            for a, b in spans.values():
                zs |= {a - gap - 0.01, a - gap, b + gap, b + gap + 0.01}
            zs = sorted(zs)
            hinge = h["rudder_hinge"]
            in_rudder = lambda z: any(a - gap - 1e-6 <= z <= b + gap + 1e-6 for a, b in spans.values())
            rings = [fin_section(side, z, hinge if in_rudder(z) else None) for z in zs]
            bm = bmesh.new()
            bc.loft(bm, rings, seams=bc.AF_SEAMS, soft=(bc.AF_N,))
            s_mid, c_mid = fin_le(z0)
            bc.add_part(parts, "fin" + sfx, bm, Vector((side * xf, bc.st(s_mid + 0.25 * c_mid), z0)), "hstab" + sfx,
                        mats=(bc.SKIN, bc.STRUCT))
            for name, (a, b) in spans.items():
                t0 = hinge + 0.02 / h["fin_top_chord"]
                secs = [fin_section(side, z, t0=t0) for z in (a, (a + b) / 2, b)]
                bm = bmesh.new()
                bc.loft(bm, [r for r, _ in secs], seams=bc.AFT_SEAMS)
                bc.add_hinged(parts, f"{name}{sfx}", bm, secs[0][1], "fin" + sfx, secs[-1][1] - secs[0][1],
                              up=Vector((side * math.cos(cant), 0, -math.sin(cant))) if cant else Vector((side, 0, 0)))

        build.stab_le, build.fin_le, build.x_body = stab_le, fin_le, x_body
        return build

    def fin_builder(bc, f):
        """A tall centreline fin, its upper part a separate panel on a longitudinal fold hinge (round 2's T2). Both
        parts carry a rudder; the panel and its rudder are built raised and folded afterwards (fold_fin)."""
        Y, X = Vector((0, 1, 0)), Vector((1, 0, 0))
        sweep, gap, hinge = math.tan(math.radians(f["sweep"])), bc.SURF_GAP, f["rudder_hinge"]

        def fin_le(z):
            chord = bc.interp(((f["root_z"], f["root_chord"]), (f["hinge_z"], f["hinge_chord"]), (f["top"], f["tip_chord"])), z)
            return f["le"] + (z - f["root_z"]) * sweep, chord

        def section(z, cut=None, t0=None):
            s, c = fin_le(z)
            le = Vector((0, bc.st(s), z))
            if t0 is not None:
                return bc.airfoil_aft(le, c, c * 0.09, Y, X, 0.0, t0), bc.camber_point(le, c, Y, X, 0.0, t0)
            return bc.airfoil(le, c, c * 0.09, Y, X, cut=cut)

        def panel(parts, name, rudder, z0, z1, parent, r0, r1):
            zs = sorted({z0, z1, (z0 + z1) / 2, r0 - gap - 0.01, r0 - gap, r1 + gap, r1 + gap + 0.01})
            rings = [section(z, hinge if r0 - gap - 1e-6 <= z <= r1 + gap + 1e-6 else None) for z in zs]
            bm = bmesh.new()
            bc.loft(bm, rings, seams=bc.AF_SEAMS, soft=(bc.AF_N,))
            s, c = fin_le(z0)
            bc.add_part(parts, name, bm, Vector((0, bc.st(s + 0.25 * c), z0)), parent, mats=(bc.SKIN, bc.STRUCT))
            t0 = hinge + 0.02 / f["tip_chord"]
            secs = [section(z, t0=t0) for z in (r0, (r0 + r1) / 2, r1)]
            bm = bmesh.new()
            bc.loft(bm, [r for r, _ in secs], seams=bc.AFT_SEAMS)
            bc.add_hinged(parts, rudder, bm, secs[0][1], name, secs[-1][1] - secs[0][1], up=X)

        def build(parts):
            hz = f["hinge_z"]
            panel(parts, "fin_C", "rudder_lower_C", f["root_z"], hz - 0.02, "tailcone", f["rudder_from"], hz - 0.1)
            panel(parts, "fin_fold_C", "rudder_upper_C", hz + 0.02, f["top"], "fin_C", hz + 0.1, f["top"] - 0.3)
        build.fin_le = fin_le
        return build

    def fold_fin(bc, v, parts):
        """Fold T2's upper fin and its rudder sideways onto the left about the hinge line on the panel's left skin."""
        f = v.get("fintail", {}).get("fin", {})
        if not f.get("fold"):
            return
        R = Matrix.Rotation(math.radians(f["fold"]), 3, "Y")
        P = Vector((0.045 * bc.TAIL["fin"].fin_le(f["hinge_z"])[1], 0.0, f["hinge_z"]))
        for p in parts:
            if p["name"] in ("fin_fold_C", "rudder_upper_C", "rudder_upper_C_visible"):
                p["origin"] = P + R @ (p["origin"] - P)
                p["basis"] = R @ (p["basis"] or Matrix.Identity(3))
                if p["bm"] is not None:
                    for vert in p["bm"].verts:
                        vert.co = P + R @ (vert.co - P)

    def vtail_panels(bc):
        """The blockout's build_vtail with its span stations scaled to VTAIL_SPAN: it hard-codes rings at 2.0 and
        4.2 m, which stretch a shorter panel past its tip."""
        def build(parts, side):
            sfx, (d0, d1), span, gap = ("_L" if side > 0 else "_R"), bc.RUDDERVATOR_SPAN, bc.VTAIL_SPAN, bc.SURF_GAP
            ds = sorted({-0.45, 0.0, 0.45 * span, 0.8 * span, span, d0 - gap - 0.01, d0 - gap, d1 + gap, d1 + gap + 0.01})
            rings = [bc.vtail_section(side, d, bc.RUDDERVATOR_HINGE if d0 - gap - 1e-6 <= d <= d1 + gap + 1e-6 else None)[0]
                     for d in ds]
            root_le = bc.vtail_section(side, 0.0)[1]
            bm = bmesh.new()
            bc.loft(bm, rings, seams=bc.AF_SEAMS, soft=(bc.AF_N,), cap_mat=(1, None))
            bc.add_part(parts, "vtail" + sfx, bm, root_le + Vector((0, 0.25 * bc.VTAIL_ROOT_CHORD, 0)), "tailcone",
                        mats=(bc.SKIN, bc.STRUCT))
            t0 = bc.RUDDERVATOR_HINGE + 0.02 / bc.VTAIL_TIP_CHORD
            secs = [bc.vtail_section(side, d, t0=t0) for d in (d0, (d0 + d1) / 2, d1)]
            bm = bmesh.new()
            bc.loft(bm, [r for r, _ in secs], seams=bc.AFT_SEAMS)
            dih = bc.VTAIL_DIHEDRAL
            bc.add_hinged(parts, "ruddervator" + sfx, bm, secs[0][1], "vtail" + sfx, secs[-1][1] - secs[0][1],
                          up=Vector((-side * math.sin(dih), 0, math.cos(dih))))
        return build

    def configure_tail(bc, v):
        """Round 2's tail options. T1 is "vtail"; T4 is "htail"; T2 "fintail" is a stabiliser and a folding fin; T3
        "canted" is a stabiliser and two canted fins, built by the V-tail code at a steep dihedral."""
        if "vtail" in v and "strut" in v:
            bc.build_vtail = vtail_panels(bc)
        if "fintail" in v:
            stab, fin = htail_builder(bc, {**v["fintail"]["stab"], "fins": False}), fin_builder(bc, v["fintail"]["fin"])
            bc.TAIL = {"stab": stab, "fin": fin}
            bc.build_vtail = lambda parts, side: (stab(parts, side), fin(parts) if side > 0 else None)
        elif "canted" in v:
            configure_vtail(bc, v["canted"]["fins"])
            stab, fins = htail_builder(bc, {**v["canted"]["stab"], "fins": False}), vtail_panels(bc)
            bc.TAIL = {"stab": stab}
            bc.build_vtail = lambda parts, side: (fins(parts, side), stab(parts, side))

    def straight_strut_builder(bc, s, pod):
        """A straight strut from the sponson to the node on the rear spar, flared into the sponson and pressed onto
        the wing skin as the blockout's, a straight jury strut from its midpoint up to 62% chord, and the sponson:
        the blockout's strut-root pod resized to hold the main bogie under the strut root."""
        ch, th = s.get("chord", 0.85), s.get("thick", 0.26)

        def build_struts(parts, side):
            sfx = "_L" if side > 0 else "_R"
            le, c, _ = bc.wing_le(side, bc.STRUT_WING_X)
            node = bc.wing_lower(side, bc.STRUT_WING_X, le.y + bc.Y0 + bc.STRUT_NODE_CHORD * c)
            root = Vector((side * bc.STRUT_ROOT[0], bc.st(bc.STRUT_ROOT[1]), bc.STRUT_ROOT[2]))
            axis, length = (node - root).normalized(), (node - root).length

            def section(p, ax, chord, thick):
                cd = (Vector((0, 1, 0)) - ax * ax.y).normalized()
                td = ax.cross(cd).normalized()
                return bc.airfoil(p - 0.4 * chord * cd, chord, thick, cd, td, n=bc.STRUT_AF_N, te=0.01)

            flare = lambda d: 1 + 0.45 * max(0.0, 1 - d / 1.8) ** 2  # the blockout's flare over the first 1.8 m
            rings = [section(root - axis * 0.5, axis, ch * 1.45, th * 1.45)]
            for t in (0.0, 0.06, 0.14, 0.3, 0.5, 0.7, 0.85, 0.92):
                rings.append(section(root + axis * (t * length), axis, ch * flare(t * length), th * flare(t * length)))
            foot = section(node, axis, ch, th)
            rings.append([Vector((p.x, p.y, bc.wing_lower(side, abs(p.x), p.y + bc.Y0, inset=0.02).z)) for p in foot])
            bm = bmesh.new()
            seams = (0, bc.STRUT_AF_N, 2 * bc.STRUT_AF_N)
            bc.loft(bm, rings, seams=seams, soft=(bc.STRUT_AF_N,), cap_mat=(1, 1))
            bc.add_part(parts, "strut" + sfx, bm, root, "wing_root" + sfx, mats=(bc.SKIN, bc.STRUCT),
                        col=bc.airframe(rings[:-1]), bonded_to="strutfairing" + sfx,
                        line_root=list(root), line_node=list(node))

            m = root + (node - root) * bc.JURY_T
            jle, jc, _ = bc.wing_le(side, abs(m.x))
            top = bc.wing_lower(side, abs(m.x), jle.y + bc.Y0 + bc.JURY_TOP_CHORD * jc, inset=0.1)
            ax = (top - m).normalized()
            rings = [section(m - ax * 0.12, ax, 0.45, 0.14), section(top, ax, 0.45, 0.14)]
            bm = bmesh.new()
            bc.loft(bm, rings, seams=seams, soft=(bc.STRUT_AF_N,), cap_mat=(1, 1))
            bc.add_part(parts, "jury_strut" + sfx, bm, m, "strut" + sfx, mats=(bc.SKIN, bc.STRUCT),
                        col=bc.airframe(rings), bonded_to="wing_root" + sfx)

            cx, cz, s0, half = side * (bc.FUS_HALF_W - pod.get("inset", 0.1)), pod["cz"], pod["station"], pod["half_len"]
            rings = []
            for u in (-0.96, -0.85, -0.6, -0.25, 0.1, 0.45, 0.75, 0.92):
                f = (1 - abs(u) ** 2.5) ** 0.5
                rings.append([Vector((cx + pod["half_w"] * f * math.sin(2 * math.pi * k / 16), bc.st(s0 + u * half),
                                      cz + pod["half_h"] * f * math.cos(2 * math.pi * k / 16))) for k in range(16)])
            poles = Vector((cx, bc.st(s0 - half), cz)), Vector((cx, bc.st(s0 + half), cz))
            bm = bmesh.new()
            bc.loft(bm, rings, *poles, seams=(8,))
            bc.add_part(parts, "strutfairing" + sfx, bm, Vector((side * bc.FUS_HALF_W, bc.st(s0), cz)), "fuselage_M",
                        col=bc.airframe(rings, *poles))
        return build_struts

    # ---------- post-processing the part list ----------
    def move_part(parts, name, fn):
        for p in parts:
            if p["name"] in (name, name + "_visible"):
                p["origin"] = fn(p["origin"].copy())
                if p["bm"] is not None:
                    for vert in p["bm"].verts:
                        vert.co = fn(vert.co.copy())

    def adapt(bc, v, parts):
        """Parts whose blockout builders hard-code the 4.0 m fuselage: the dorsal wing fairing scales with the width and
        rides up with the crown; the strut-root pods and their gear doors move out with the side."""
        if "fus_half_w" not in v:
            return
        k, dz, dw = bc.FUS_HALF_W / 2.0, bc.FUS_TOP - 6.0, bc.FUS_HALF_W - 2.0
        move_part(parts, "wingfairing", lambda p: Vector((p.x * k, p.y + v.get("wing_aft", 0.0), p.z + dz)))
        if "pod" in v:  # the sponson is built in place; the blockout's pod-shaped main doors don't fit it
            parts[:] = [p for p in parts if not p["name"].startswith(("geardoor_LM", "geardoor_RM"))]
        else:
            for sfx, side in (("L", 1), ("R", -1)):
                for name in (f"strutfairing_{sfx}", f"geardoor_{sfx}M"):
                    move_part(parts, name, lambda p, s=side: Vector((p.x + s * dw, p.y, p.z)))
        if "nacelle" in v:
            kr = v["nacelle"]["kr"]
            for num, *_ in bc.NACELLES:
                origin = next(p["origin"] for p in parts if p["name"] == f"fan_{num}").copy()
                move_part(parts, f"fan_{num}", lambda p, o=origin: Vector((o.x + (p.x - o.x) * kr, p.y, o.z + (p.z - o.z) * kr)))
        if "strut_scale" in v:
            k2 = v["strut_scale"]
            for sfx in ("_L", "_R"):
                pts = [p for p in parts if p["name"] == "strut" + sfx][0]
                # Thicken about the strut's own centreline: each ring scales about its centroid.
                bm = pts["bm"]
                bm.verts.ensure_lookup_table()
                ring = 2 * bc.STRUT_AF_N + 1
                verts = list(bm.verts)
                for r in range(len(verts) // ring):
                    vs = verts[r * ring:(r + 1) * ring]
                    c = sum((x.co for x in vs), Vector()) / len(vs)
                    for x in vs:
                        x.co = c + (x.co - c) * k2

    STRETCHED = ("radar_F_fairing", "nose", "fuselage_", "tailcone", "baydoor_", "wingfairing", "radar_R_fairing")
    WING_GROUP = ("wing_", "flap_", "aileron_", "spoiler_", "strut_", "jury_strut", "pylon_", "nacelle_", "fan_", "nozzle_")

    def station_map(plugs):
        return lambda s: s + sum(d * min(max((s - s0) / (s1 - s0), 0.0), 1.0) for s0, s1, d in plugs)

    def remap(bc, v, parts):
        """Apply the plugs: fuselage skin parts stretch vertex by vertex; every other part moves whole, the wing and
        everything hung on it by the root quarter chord's shift, the rest by its own origin's."""
        m = bc.MAP = station_map(v.get("plugs", ()))
        if not v.get("plugs"):
            return
        s_wing = bc.ROOT_QC.y + bc.Y0
        for p in parts:
            if p["name"].startswith(STRETCHED):
                f = lambda q: Vector((q.x, m(q.y + bc.Y0) - bc.Y0, q.z))
            else:
                s0 = s_wing if p["name"].startswith(WING_GROUP) else p["origin"].y + bc.Y0
                f = lambda q, d=m(s0) - s0: Vector((q.x, q.y + d, q.z))
            p["origin"] = f(p["origin"].copy())
            if p["bm"] is not None:
                for vert in p["bm"].verts:
                    vert.co = f(vert.co.copy())
            for key in ("line_root", "line_node"):
                if key in p["props"]:
                    p["props"][key] = list(f(Vector(p["props"][key])))

    def build(bc, v, extension):
        coll = bc.reset_collection("Centurion")
        mats = {k: bc.material(k, c) for k, c in bc.MATERIALS.items()}
        parts = []
        bc.build_fuselage(parts)
        bc.build_wingfairing(parts)
        for side in (1, -1):
            # build_wing cuts a UV seam at STRUT_WING_X from a fixed station list that holds 13.0; a moved node only
            # moves the strut, so the seam stays at 13.0.
            node, bc.STRUT_WING_X = bc.STRUT_WING_X, 13.0
            bc.build_wing(parts, side)
            bc.STRUT_WING_X = node
            bc.build_surfaces(parts, side)
            bc.build_struts(parts, side)
            bc.build_vtail(parts, side)
        bc.build_engines(parts)
        bc.build_tail_systems(parts)
        bc.build_baydoors(parts)
        bc.build_geardoors(parts)
        bc.build_gear(parts)
        adapt(bc, v, parts)
        nose_details(bc, v, parts)
        fold_fin(bc, v, parts)
        remap(bc, v, parts)
        objs, world = {}, {}
        for p in parts:
            m = Matrix.Translation(p["origin"]) @ (p["basis"] or Matrix.Identity(3)).to_4x4()
            world[p["name"]] = m
            if p["bm"] is None:
                obj = bpy.data.objects.new(p["name"], None)
            else:
                bm = p["bm"]
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
                bmesh.ops.transform(bm, matrix=m.inverted(), verts=bm.verts)
                me = bpy.data.meshes.new(p["name"])
                bm.to_mesh(me)
                bm.free()
                for k in p["mats"]:
                    me.materials.append(mats[k])
                obj = bpy.data.objects.new(p["name"], me)
            coll.objects.link(obj)
            for k, val in p["props"].items():
                obj[k] = val
            objs[p["name"]] = obj
        for p in parts:
            obj = objs[p["name"]]
            if p["parent"]:
                obj.parent = objs[p["parent"]]
                obj.matrix_parent_inverse.identity()
                obj.matrix_basis = world[p["parent"]].inverted() @ world[p["name"]]
            else:
                obj.matrix_basis = world[p["name"]]
        for obj in objs.values():
            if "slide_axis" in obj:
                obj["rest_location"] = list(obj.location)
        bpy.context.view_layer.update()
        bc.bake_normals(objs)
        bc.set_extension(objs, extension)
        return objs

    # ---------- measurements ----------
    def verts_of(objs, names=None):
        return [p for n, o in objs.items() if o.type == "MESH" and (names is None or n.startswith(names))
                for p in bc_world(o)]

    def bc_world(o):
        mw = o.matrix_world
        return [mw @ x.co for x in o.data.vertices]

    def planform(objs, prefixes, step=0.1):
        """Projected area seen from above (rays down through a grid), split at the fuselage side."""
        verts, tris = [], []
        for n, o in objs.items():
            if o.type != "MESH" or not n.startswith(prefixes):
                continue
            base = len(verts)
            verts += bc_world(o)
            tris += [tuple(base + i for i in p.vertices) for p in o.data.polygons]
        tree = BVHTree.FromPolygons(verts, tris)
        xs = [p.x for p in verts]
        ys = [p.y for p in verts]
        hits = []
        y = min(ys)
        while y <= max(ys):
            x = min(xs)
            while x <= max(xs):
                if tree.ray_cast(Vector((x, y, 30.0)), Vector((0, 0, -1)))[0] is not None:
                    hits.append(x)
                x += step
            y += step
        return hits, step * step

    def tail_area_vtail(bc):
        """One V-tail panel outboard of the skin, in its own plane, and its ruddervator, as built."""
        c = lambda d: bc.VTAIL_ROOT_CHORD + (bc.VTAIL_TIP_CHORD - bc.VTAIL_ROOT_CHORD) * d / bc.VTAIL_SPAN
        d_skin = 0.0
        if hasattr(bc, "VTAIL_ROOT_X"):
            mid = bc.VTAIL_ROOT_STATION + 0.5 * bc.VTAIL_ROOT_CHORD
            d_skin = max(side_x(bc, mid, bc.VTAIL_ROOT_Z) - bc.VTAIL_ROOT_X, 0.0) / math.cos(bc.VTAIL_DIHEDRAL)
        else:  # the blockout's root line at x = 1.45 sits inside the 2.0 m skin
            mid = bc.VTAIL_ROOT_STATION + 0.5 * bc.VTAIL_ROOT_CHORD
            d_skin = max(bc.fus_profile(mid)[0] * 0.95 - 1.45, 0.0) / math.cos(bc.VTAIL_DIHEDRAL)
        n = 200
        panel = sum(c(d_skin + (bc.VTAIL_SPAN - d_skin) * (k + 0.5) / n) for k in range(n)) * (bc.VTAIL_SPAN - d_skin) / n
        d0, d1 = bc.RUDDERVATOR_SPAN
        rv = sum(c(d0 + (d1 - d0) * (k + 0.5) / n) * (1 - bc.RUDDERVATOR_HINGE) for k in range(n)) * (d1 - d0) / n
        dih = bc.VTAIL_DIHEDRAL
        return {"panel_m2_each": round(panel, 1), "fixed_part_m2_each": round(panel - rv, 1),
                "ruddervator_m2_each": round(rv, 1), "aero_data_m2_each": f"{AERO_TAIL_M2:.0f} panel + {AERO_TAIL_M2:.0f} ruddervator",
                "dihedral_deg": round(math.degrees(dih), 1), "span_along_panel_m": round(bc.VTAIL_SPAN, 2),
                "panel_aspect_ratio": round((bc.VTAIL_SPAN - d_skin) ** 2 / panel, 2),
                "pitch_effective_m2_total": round(2 * panel * math.cos(dih) ** 2, 1),
                "yaw_effective_m2_total": round(2 * panel * math.sin(dih) ** 2, 1),
                "aero_pitch_effective_m2": round(4 * AERO_TAIL_M2 * math.cos(dih) ** 2, 1) if not hasattr(bc, "VTAIL_ROOT_X") else None,
                "ruddervator_chord_share": round(1 - bc.RUDDERVATOR_HINGE, 2)}

    def tail_area_htail(bc, h):
        b = bc.build_vtail
        n = 200
        x0, xf = b.x_body, h["x_fin"]
        stab = sum(b.stab_le(x0 + (xf - x0) * (k + 0.5) / n)[1] for k in range(n)) * (xf - x0) / n
        elev = stab * (1 - h["elevator_hinge"]) * (xf - x0 - 0.65) / (xf - x0)
        zb, zt = h["fin_bottom"], h["fin_top"]
        fin = sum(b.fin_le(zb + (zt - zb) * (k + 0.5) / n)[1] for k in range(n)) * (zt - zb) / n
        return {"stabiliser_m2_each_side": round(stab, 1), "elevator_m2_each": round(elev, 1),
                "fin_m2_each": round(fin, 1), "rudder_m2_each_fin": round(fin * (1 - h["rudder_hinge"]) * 0.82, 1),
                "fin_above_stab_m": round(zt - h["root_z"], 2), "fin_below_stab_m": round(h["root_z"] - zb, 2),
                "tail_span_m": round(2 * xf, 2), "pitch_effective_m2_total": round(2 * stab, 1),
                "yaw_effective_m2_total": round(2 * fin, 1)}

    def weighted(rows):
        """rows of (leading-edge station, chord, step): area and area-weighted quarter-chord station."""
        area = sum(c * d for _, c, d in rows)
        return area, sum(c * d * (s + 0.25 * c) for s, c, d in rows) / area

    def tail_summary(bc, v):
        """Round 2: geometric areas of any tail option, its pitch- and yaw-effective totals (a canted panel projects
        by cos2 and sin2 of its dihedral), and the area-weighted quarter-chord stations of the pitch and yaw surfaces,
        as built (before the plugs)."""
        n, out = 200, {}

        def stab(b, h):
            x0, xf = b.x_body, h["x_fin"]
            rows = [(*b.stab_le(x0 + (xf - x0) * (k + 0.5) / n), (xf - x0) / n) for k in range(n)]
            a, qc = weighted(rows)
            out.update({"stabiliser_m2_each_side": round(a, 1), "elevator_m2_each": round(a * (1 - h["elevator_hinge"]) * (xf - x0 - 0.65) / (xf - x0), 1),
                        "stabiliser_span_m": round(2 * xf, 2), "stabiliser_height_m": h["root_z"]})
            return 2 * a, qc

        def vee():
            t = tail_area_vtail(bc)
            span = bc.VTAIL_SPAN
            c = lambda d: bc.VTAIL_ROOT_CHORD + (bc.VTAIL_TIP_CHORD - bc.VTAIL_ROOT_CHORD) * d / span
            rows = [(bc.VTAIL_ROOT_STATION + d * math.tan(bc.VTAIL_SWEEP), c(d), span / n) for d in
                    (span * (k + 0.5) / n for k in range(n))]
            out.update({"panel_m2_each": t["panel_m2_each"], "moving_surface_m2_each": t["ruddervator_m2_each"],
                        "tail_span_m": round(2 * (bc.VTAIL_ROOT_X + span * math.cos(bc.VTAIL_DIHEDRAL)), 2),
                        "dihedral_deg": t["dihedral_deg"], "cant_from_vertical_deg": round(90 - t["dihedral_deg"], 1)})
            return t["pitch_effective_m2_total"], t["yaw_effective_m2_total"], weighted(rows)[1]

        if "htail" in v:
            h, b = v["htail"], bc.build_vtail
            pitch, pqc = stab(b, h)
            zt = h["fin_top"]
            zb = h["fin_bottom"] if h["root_z"] - h["fin_bottom"] >= 1.0 else h["root_z"]  # T5a: exposed above the stabiliser
            yaw, yqc = weighted([(*b.fin_le(zb + (zt - zb) * (k + 0.5) / n), (zt - zb) / n) for k in range(n)])
            # A canted fin's panel is 1/cos longer than its height; it projects by cos2 into yaw and sin2 into pitch.
            cant = math.radians(h.get("cant", 0.0))
            panel = yaw / math.cos(cant)
            yaw, pitch = 2 * panel * math.cos(cant) ** 2, pitch + 2 * panel * math.sin(cant) ** 2
            out.update({"kind": "H-tail" if not cant else "canted endplate fins", "fin_m2_each": round(panel, 1),
                        "cant_deg": h.get("cant", 0.0), "fin_above_stab_m": round(zt - h["root_z"], 2),
                        "fin_below_stab_m": round(max(h["root_z"] - h["fin_bottom"], 0.0) if zb < h["root_z"] else 0.0, 2),
                        "fin_top_semi_span_m": round(h["x_fin"] + (zt - h["root_z"]) * math.tan(cant), 2),
                        "tail_span_m": round(2 * (h["x_fin"] + (zt - h["root_z"]) * math.tan(cant)), 2)})
        elif "fintail" in v:
            f, fb = v["fintail"]["fin"], bc.TAIL["fin"]
            pitch, pqc = stab(bc.TAIL["stab"], v["fintail"]["stab"])
            s_mid = fb.fin_le(f["hinge_z"])[0] + 0.5 * fb.fin_le(f["hinge_z"])[1]
            crown = bc.fus_profile(s_mid)[1]
            fin = lambda z0, z1: weighted([(*fb.fin_le(z0 + (z1 - z0) * (k + 0.5) / n), (z1 - z0) / n) for k in range(n)])
            yaw, yqc = fin(crown, f["top"])
            stub = fin(crown, f["hinge_z"])[0]
            out.update({"kind": "folding fin", "fin_exposed_m2": round(yaw, 1), "fin_stub_m2": round(stub, 1),
                        "fold_panel_m2": round(yaw - stub, 1), "crown_at_fin_m": round(crown, 2),
                        "fin_top_raised_m": f["top"], "hinge_height_m": f["hinge_z"], "folded": bool(f.get("fold")),
                        "yaw_effective_m2_folded": round(stub, 1)})
        elif "canted" in v:
            pitch, pqc = stab(bc.TAIL["stab"], v["canted"]["stab"])
            p2, yaw, yqc = vee()
            out["stabiliser_only_pitch_m2"] = round(pitch, 1)
            pitch += p2
            out["kind"] = "twin canted fins"
        else:
            pitch, yaw, pqc = vee()
            yqc = pqc
            out["kind"] = "V-tail"
        out.update({"pitch_effective_m2_total": round(pitch, 1), "yaw_effective_m2_total": round(yaw, 1),
                    "pitch_quarter_chord_station_built": round(pqc, 2), "yaw_quarter_chord_station_built": round(yqc, 2),
                    "aero_data_now": f"V-tail {AERO_TAIL_M2:.0f} + {AERO_TAIL_M2:.0f} m2 a side at 32 deg: "
                                     f"{4 * AERO_TAIL_M2 * math.cos(math.radians(32)) ** 2:.1f} pitch / "
                                     f"{4 * AERO_TAIL_M2 * math.sin(math.radians(32)) ** 2:.1f} yaw effective"})
        return out

    def point_masses(objs, v):
        """(name, kg, bounds centre) for every massed part, as ConfigurePart places CoM."""
        out = []
        for n, o in objs.items():
            if o.type != "MESH":
                continue
            base = n[:-len("_visible")] if n.endswith("_visible") else n
            # Round 2 tails split the same 4,000 kg; round 3's twin splits the four engine groups' 22,500 kg.
            override = {**v.get("tail_mass", {}), **v.get("engine_mass", {})}
            m = override.get(base.rsplit("_", 1)[0], MASS.get(n))
            if m is None and n.endswith("_visible") and base.startswith(CONTROL_SURFACES):
                m = HTAIL_MASS.get(base.rsplit("_", 1)[0], SURFACE_MASS)
            if m is None and base.startswith(("hstab", "fin_")):
                m = HTAIL_MASS["hstab" if base.startswith("hstab") else "fin"]
            if m is None:
                continue
            vs = bc_world(o)
            lo = Vector((min(p.x for p in vs), min(p.y for p in vs), min(p.z for p in vs)))
            hi = Vector((max(p.x for p in vs), max(p.y for p in vs), max(p.z for p in vs)))
            out.append((base, m, (lo + hi) / 2))
        return out

    def cg(objs, v):
        pm = point_masses(objs, v)
        m_sum = sum(m for _, m, _ in pm)
        c = sum((m * p for _, m, p in pm), Vector()) / m_sum
        return {"mass_kg": round(m_sum), "station": round(c.y + 21.5, 3), "height_m": round(c.z, 3)}

    def roll_inertia(objs, v):
        """Round 3: roll inertia about the empty CG's fore-and-aft axis, every part a point mass at its bounds centre
        (the wing's own spread is missed, so read the tail rows as differences), and the mass on each tail tip."""
        pm = point_masses(objs, v)
        m_sum = sum(m for _, m, _ in pm)
        zc = sum(m * p.z for _, m, p in pm) / m_sum
        ixx = lambda rows: sum(m * (p.x ** 2 + (p.z - zc) ** 2) for _, m, p in rows)
        tail = [r for r in pm if r[0].startswith(TAIL_PARTS)]
        tip = sum(m for n, m, p in tail if n.startswith(("fin_", "rudder_")) and n.endswith("_L"))
        return {"total_kg_m2": round(ixx(pm)), "tail_group_kg_m2": round(ixx(tail)), "tip_mass_kg_each_side": tip,
                "tail_mass_kg": sum(m for _, m, _ in tail)}

    def fuselage_stats(objs):
        vol, aft = 0.0, 0.0
        for n in ("radar_F_fairing", "nose", "fuselage_F", "fuselage_M", "fuselage_R", "tailcone"):
            o = objs[n]
            vs = bc_world(o)
            vv = 0.0
            for p in o.data.polygons:
                ids = p.vertices
                for i in range(1, len(ids) - 1):
                    vv += vs[ids[0]].dot(vs[ids[i]].cross(vs[ids[i + 1]])) / 6
            vol += vv
            if n in ("fuselage_R", "tailcone"):
                aft += vv
        return {"volume_m3": round(vol, 1), "aft_body_volume_m3": round(aft, 1)}

    def station_of(p):
        return round(p.y + 21.5, 3)

    def box_centre(o):
        vs = bc_world(o)
        return Vector([(min(p[i] for p in vs) + max(p[i] for p in vs)) / 2 for i in range(3)])

    def wing_mac(bc):
        """Fixed wing, root to the retracted tip: mean aerodynamic chord and the area-weighted quarter-chord station."""
        n, X = 200, bc.X_ROOT_TIP
        xs = [X * (k + 0.5) / n for k in range(n)]
        cs = [bc.interp(bc.CHORD, x) for x in xs]
        qcs = [bc.qc_at(1, x * bc.XI_PER_X).y + bc.Y0 for x in xs]
        s_root = bc.ROOT_QC.y + bc.Y0
        return sum(c * c for c in cs) / sum(cs), sum(c * q for c, q in zip(cs, qcs)) / sum(cs) + bc.MAP(s_root) - s_root

    def round2_metrics(bc, v, objs, cgm, wing_gross, span):
        """Flight-model inputs that move with the layout: strut line and clearances, gear, CG against the MAC, tail
        arms and volumes, engine stations."""
        out = {}
        o = objs["strut_L"]
        r, nd = Vector(o["line_root"]), Vector(o["line_node"])
        d = nd - r
        out["strut"] = {"root": [round(r.x, 2), station_of(r), round(r.z, 2)],
                        "node": [round(nd.x, 2), station_of(nd), round(nd.z, 2)], "length_m": round(d.length, 2),
                        "rise_in_rear_view_deg": round(math.degrees(math.atan2(d.z, d.x)), 1),
                        "forward_lean_in_plan_deg": round(math.degrees(math.atan2(-d.y, d.x)), 1), "clearance": {}}
        for num, side, x, _ in bc.NACELLES:
            if side < 0:
                continue
            t = (x - r.x) / d.x
            exit_st = max(p.y for p in bc_world(objs[f"nozzle_{num}"])) + 21.5
            row = {"engine_semi_span": x, "nozzle_exit_station": round(exit_st, 2),
                   "strut_line_station_at_engine": round(r.y + t * d.y + 21.5, 2),
                   "strut_line_behind_exit_m": round(r.y + t * d.y + 21.5 - exit_st, 2),
                   "strut_height_at_engine": round(r.z + t * d.z, 2), "jet_axis_height": bc.NACELLE_Z}
            for part in (f"nacelle_{num}", f"nozzle_{num}", f"pylon_{num}"):
                for s in ("strut_L", "jury_strut_L"):
                    row[f"{s[:-2]}_to_{part}_m"] = round(min(bc.min_distance(objs[s], objs[part]),
                                                             bc.min_distance(objs[part], objs[s])), 3)
            out["strut"]["clearance"][f"engine_{num}"] = row
        main, nose = objs["wheel_LM"].matrix_world.translation, objs["wheel_F"].matrix_world.translation
        out["gear"] = {"nose_station": station_of(nose), "main_station": station_of(main),
                       "track_m": round(2 * abs(main.x), 2), "main_behind_cg_m": round(station_of(main) - cgm["station"], 2),
                       "nose_gear_load_share": round((station_of(main) - cgm["station"]) / (station_of(main) - station_of(nose)), 3)}
        mac, qbar = wing_mac(bc)
        out["wing_mac"] = {"mac_m": round(mac, 2), "quarter_chord_station": round(qbar, 2),
                           "root_le_station": round(bc.MAP(bc.WING_ROOT_LE_STATION), 2),
                           "cg_percent_mac": round(100 * (cgm["station"] - (qbar - 0.25 * mac)) / mac, 1)}
        ta = tail_summary(bc, v)
        pqc, yqc = bc.MAP(ta["pitch_quarter_chord_station_built"]), bc.MAP(ta["yaw_quarter_chord_station_built"])
        lh, lv = pqc - cgm["station"], yqc - cgm["station"]
        out["tail_arms"] = {"pitch_quarter_chord_station": round(pqc, 2), "yaw_quarter_chord_station": round(yqc, 2),
                            "pitch_arm_m": round(lh, 2), "yaw_arm_m": round(lv, 2),
                            "horizontal_volume": round(ta["pitch_effective_m2_total"] * lh / (wing_gross * mac), 3),
                            "vertical_volume": round(ta["yaw_effective_m2_total"] * lv / (wing_gross * span), 4)}
        out["engines"] = {f"nacelle_{num}": {"semi_span": x, "intake_station": round(min(p.y for p in bc_world(objs[f"nacelle_{num}"])) + 21.5, 2),
                                             "ground_clearance_m": round(min(p.z for p in bc_world(objs[f"nacelle_{num}"])), 2),
                                             "to_sponson_m": round(bc.min_distance(objs[f"nacelle_{num}"], objs["strutfairing_L"]), 2)}
                          for num, side, x, _ in bc.NACELLES if side > 0}
        # Round 3: the ground line through the nose wheel and the sagged main contact sets the static attitude (nose
        # down when negative); the tail strike is the body attitude at first tail contact, pivoting on the main gear.
        nose_z = min(p.z for p in bc_world(objs["wheel_F"]))
        c = bc.main_contact(objs)
        static = math.degrees(math.atan2(c.z - nose_z, c.y - nose.y))
        strike = bc.tail_strike(objs)["value"]
        out["ground"] = {"static_attitude_deg": round(static, 2), "strike_attitude_deg": strike,
                         "rotation_from_static_deg": round(strike - static, 2),
                         "belly_clearance_m": round(min(p.z for p in bc_world(objs["fuselage_M"])), 2)}
        return out

    def silhouette_gap(objs, a_names, b_names, axes, cell=0.02):
        """Round 4: two part sets' silhouettes in an orthographic view (axes: the two world coordinates kept, 0 x, 1 y,
        2 z), rasterised at `cell`: the gap between them, or the overlapping area when they cross."""
        import numpy as np
        from mathutils.kdtree import KDTree

        def tris(names):
            out = []
            for n in names:
                o = objs[n]
                pts = np.array([(p[axes[0]], p[axes[1]]) for p in bc_world(o)])
                for poly in o.data.polygons:
                    ids = poly.vertices
                    out += [(pts[ids[0]], pts[ids[i]], pts[ids[i + 1]]) for i in range(1, len(ids) - 1)]
            return np.array(out)
        ta, tb = tris(a_names), tris(b_names)
        lo = np.minimum(ta.reshape(-1, 2).min(0), tb.reshape(-1, 2).min(0)) - 0.1
        hi = np.maximum(ta.reshape(-1, 2).max(0), tb.reshape(-1, 2).max(0)) + 0.1
        shape = tuple(np.ceil((hi - lo) / cell).astype(int) + 1)

        def raster(T):
            mask = np.zeros(shape, bool)
            for a, b, c in T:
                i0 = np.floor((np.minimum(np.minimum(a, b), c) - lo) / cell).astype(int)
                i1 = np.ceil((np.maximum(np.maximum(a, b), c) - lo) / cell).astype(int)
                gx, gy = np.meshgrid(np.arange(i0[0], i1[0] + 1), np.arange(i0[1], i1[1] + 1), indexing="ij")
                px, py = lo[0] + gx * cell, lo[1] + gy * cell
                d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
                if abs(d) < 1e-12:
                    continue
                l1 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
                l2 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
                mask[gx, gy] |= (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
            return mask
        ma, mb = raster(ta), raster(tb)
        both = ma & mb
        if both.any():
            return {"overlap_m2": round(float(both.sum()) * cell * cell, 3), "gap_m": 0.0}
        edge = lambda m: np.argwhere(m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1)))
        ea, eb = edge(ma), edge(mb)
        tree = KDTree(len(eb))
        for i, (x, y) in enumerate(eb):
            tree.insert((float(x), float(y), 0.0), i)
        tree.balance()
        gap = min(tree.find((float(x), float(y), 0.0))[2] for x, y in ea) * cell
        return {"overlap_m2": 0.0, "gap_m": round(gap, 2)}

    def round4_metrics(bc, v, objs, cgm):
        """The owner's round 4 checks: the strut against the nacelle in the front, rear and side views; the tail roots
        against the strike; the AWACS beam's spine well aft of the wing box (docs/M3-DESIGN.md "Blockout
        measurements": a 10.10 x 0.86 m slot 1.71 m deep, 0.30 m behind the wing box)."""
        out = {}
        nacelle, strut = ("nacelle_1", "nozzle_1", "fan_1"), ("strut_L",)
        for view, axes in (("front_or_rear", (0, 2)), ("side", (1, 2)), ("top", (0, 1))):
            out[f"strut_vs_nacelle_{view}"] = silhouette_gap(objs, strut, nacelle, axes)
            out[f"strut_vs_pylon_{view}"] = silhouette_gap(objs, strut, ("pylon_1",), axes)
            out[f"jury_vs_nacelle_{view}"] = silhouette_gap(objs, ("jury_strut_L",), nacelle, axes)
        out["strut_to_nacelle_3d_m"] = round(min(bc.min_distance(objs[a], objs[b]) for a in ("strut_L", "jury_strut_L")
                                                 for b in nacelle + ("pylon_1",)), 2)
        o = objs["jury_strut_L"]
        vs = bc_world(o)
        lo, hi = min(vs, key=lambda p: p.z), max(vs, key=lambda p: p.z)
        out["jury_strut"] = {"length_m": round((hi - lo).length, 2), "foot": [round(lo.x, 2), station_of(lo), round(lo.z, 2)],
                             "top": [round(hi.x, 2), station_of(hi), round(hi.z, 2)]}
        # Tail roots against the strike: the lowest body angle at which each tail part's vertices meet the runway.
        c = bc.main_contact(objs)
        ang = lambda names: min(math.degrees(math.atan2(p.z - c.z, p.y - c.y)) for n, o2 in objs.items()
                                if o2.type == "MESH" and n.startswith(names) for p in bc_world(o2) if p.y > c.y + 0.5)
        out["tail_strike_by_tail_parts_deg"] = round(ang(TAIL_PARTS), 2)
        tv = verts_of(objs, TAIL_PARTS)
        out["tail_lowest_point"] = (lambda p: [round(p.x, 2), station_of(p), round(p.z, 2)])(min(tv, key=lambda p: p.z))
        # AWACS spine well: starts 0.30 m behind the wing root's trailing edge on the crown.
        wing = [p for p in bc_world(objs["wing_root_L"]) if abs(p.x) < 0.5]
        te = max(station_of(p) for p in wing)
        s0, s1 = te + 0.30, te + 0.30 + 10.10
        built = lambda s: s - sum(d for a, b, d in v.get("plugs", ()) if s > b + d)  # the plugs all lie forward
        crown = [bc.fus_profile(built(s))[1] for s in (s0, (s0 + s1) / 2, s1)]
        floor = min(crown) - 1.71
        box_lo, box_hi = Vector((-0.43, s0 - 21.5, floor)), Vector((0.43, s1 - 21.5, max(crown)))
        dist = lambda p: Vector([max(box_lo[i] - p[i], 0.0, p[i] - box_hi[i]) for i in range(3)]).length
        out["awacs_well"] = {"stations": [round(s0, 2), round(s1, 2)], "crown_m": [round(z, 2) for z in crown],
                             "floor_m": round(floor, 2), "wing_root_te_station": te,
                             "tail_parts_to_well_m": round(min(dist(p) for p in tv), 2),
                             "tail_cone_end_station": round(max(station_of(p) for p in verts_of(objs, ("tailcone",))), 2),
                             "belly_at_mast_m": round(bc.fus_profile(built((s0 + s1) / 2))[2], 2)}
        x = bc.NACELLES[0][2]
        out["engine_out_yaw_kN_m"] = {f"{t:.0f} kN": round(t * x) for t in THRUST_R4_KN}
        return out

    def measure(bc, v, objs_by_state):
        out = {"label": v["label"], "params": {k: val for k, val in v.items() if k != "label"}}
        for state, objs in objs_by_state.items():
            allv = verts_of(objs)
            lo = (min(p.x for p in allv), min(p.y for p in allv), min(p.z for p in allv))
            hi = (max(p.x for p in allv), max(p.y for p in allv), max(p.z for p in allv))
            tail_names = ("vtail", "ruddervator", "hstab", "fin_", "elevator", "rudder_")
            tail_top = max(p.z for p in verts_of(objs, tail_names))
            body_top = max(p.z for n, o in objs.items() if o.type == "MESH" and not n.startswith(TAIL_PARTS) for p in bc_world(o))
            hits, cell = planform(objs, ("wing_root", "wing_tele"))
            w = bc.FUS_HALF_W
            exposed = sum(1 for x in hits if abs(x) > w) * cell
            gross = exposed + 2 * w * bc.CHORD[0][1]
            span = hi[0] - lo[0]
            out[state] = {"length_m": round(hi[1] - lo[1], 3), "span_m": round(span, 3), "height_m": round(hi[2], 3),
                          "tail_top_m": round(tail_top, 3), "height_without_tail_m": round(body_top, 3), "wing_exposed_m2": round(exposed, 1),
                          "wing_gross_m2": round(gross, 1), "aspect_ratio": round(span ** 2 / gross, 2),
                          "hangar_door_fit": state != "retracted" or (span < 45.78 and hi[2] < 8.0)}
            if state == "retracted":
                out[state]["tail_strike"] = bc.tail_strike(objs)
                nested = {f"{c}{s}": bc.outside_count(objs[c + s], objs[p + s]) for s in ("_L", "_R")
                          for c, p in (("wing_tele1", "wing_root"), ("wing_tele2", "wing_tele1"))}
                out[state]["stage_vertices_outside_parent"] = nested
                out[state]["engine_clashes"] = bc.engine_clashes(objs)
                out[state]["cg_empty"] = cg(objs, v)
                out[state]["fuselage"] = fuselage_stats(objs)
                if "strut" in v:
                    out[state].update(round2_metrics(bc, v, objs, out[state]["cg_empty"], gross, span))
                    out[state]["roll_inertia"] = roll_inertia(objs, v)
                if "ultrafan" in v:
                    out[state]["round4"] = round4_metrics(bc, v, objs, out[state]["cg_empty"])
            if "strut" in v:  # stage 1's lift acts 6 m aft of its hull centre (CenturionAuthor Stage(..., 6f))
                c1, c2 = box_centre(objs["wing_tele1_L"]), box_centre(objs["wing_tele2_L"])
                out[state]["stages"] = {"tele1_centre": [round(c1.x, 2), station_of(c1)], "tele1_lift_station": round(station_of(c1) + 6.0, 2),
                                        "tele2_centre": [round(c2.x, 2), station_of(c2)]}
                out[state]["fuselage_length_m"] = round(hi[1] - lo[1], 2)
        c = bc.CHORD
        out["wing"] = {"root_chord": c[0][1], "node_chord": c[1][1], "tip_chord_fixed": c[2][1],
                       "taper_fixed": round(c[2][1] / c[0][1], 3),
                       "t_over_c": [round(t / ch, 3) for (_, t), (_, ch) in zip(bc.THICK, c)],
                       "stage_chords": [bc.TELE[0][1], bc.TELE[1][1]], "tip_rake_deg": round(math.degrees(bc.TIP_RAKE), 1),
                       "tip_upsweep_deg": round(math.degrees(bc.TIP_UPSWEEP), 1), "strut_node_x": bc.STRUT_WING_X}
        r_max = max(r for r, _ in bc.NACELLE_OUTER)
        core = max(a for _, a in bc.CORE_PROFILE)
        out["nacelle"] = {"outer_diameter": round(2 * r_max, 2), "cowl_length": round(bc.NACELLE_LEN, 2),
                          "overall_length": round(bc.NACELLE_LEN + core, 2),
                          "cowl_L_over_D": round(bc.NACELLE_LEN / (2 * r_max), 2),
                          "overall_L_over_D": round((bc.NACELLE_LEN + core) / (2 * r_max), 2),
                          "positions": [list(n) for n in bc.NACELLES],
                          "od_over_fuselage_width": round(2 * r_max / (2 * bc.FUS_HALF_W), 2)}
        if "strut" in v:
            out["tail"] = tail_summary(bc, v)
        else:
            out["tail"] = tail_area_htail(bc, v["htail"]) if "htail" in v else tail_area_vtail(bc)
        out["fuselage_section"] = {"width": round(2 * bc.FUS_HALF_W, 2), "height": round(bc.FUS_TOP - bc.FUS_BOTTOM, 2),
                                   "fineness": round(43.0 / (bc.FUS_HALF_W + (bc.FUS_TOP - bc.FUS_BOTTOM) / 2), 2)}
        if "strut" in v:  # round 2 lengths move, so fineness uses the measured length
            out["fuselage_section"]["fineness"] = round((hi[1] - lo[1]) / (bc.FUS_HALF_W + (bc.FUS_TOP - bc.FUS_BOTTOM) / 2), 2)
        return out

    # ---------- render rig (the M4 review look) ----------
    def rig():
        for c in [c for c in bpy.data.collections if c.name.startswith("study_")]:
            bc_remove(c)
        coll = bpy.data.collections.new("study_rig")
        scene.collection.children.link(coll)
        sun = bpy.data.objects.new("study_sun", bpy.data.lights.new("study_sun", "SUN"))
        sun.data.energy, sun.data.angle = 3.2, math.radians(2.5)
        sun.rotation_euler = (math.radians(42), math.radians(12), math.radians(-35))
        coll.objects.link(sun)
        me = bpy.data.meshes.new("study_ground")
        me.from_pydata([(-300, -300, 0), (300, -300, 0), (300, 300, 0), (-300, 300, 0)], [], [(0, 1, 2, 3)])
        ground = bpy.data.objects.new("study_ground", me)
        gm = bpy.data.materials.new("study_ground")
        m4r.principled(gm, (0.16, 0.16, 0.155), 0.85, 0.0)
        me.materials.append(gm)
        coll.objects.link(ground)
        red = bpy.data.materials.new("study_red")
        m4r.principled(red, (0.6, 0.03, 0.02), 0.6, 0.0, (0.9, 0.05, 0.03), 1.5)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(0.6, 90.0, 0.12), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0, -0.06), verts=bm.verts)
        lm = bpy.data.meshes.new("study_groundline")
        bm.to_mesh(lm)
        bm.free()
        lm.materials.append(red)
        line = bpy.data.objects.new("study_groundline", lm)
        coll.objects.link(line)
        line.hide_render = True
        # Round 3's side_strike view: ground lines from the main contact, rising aft at 9.5 deg (red, the low end of
        # the owner's strike band) and at round 2's 12 deg (amber); anything above a line clears that body attitude.
        amber = bpy.data.materials.new("study_amber")
        m4r.principled(amber, (0.8, 0.45, 0.02), 0.6, 0.0, (0.95, 0.55, 0.05), 1.5)
        strike_lines = []
        for name, mat in (("study_strike_line", red), ("study_12deg_line", amber)):
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(0.6, 40.0, 0.1), verts=bm.verts)
            bmesh.ops.translate(bm, vec=(0, 20.0, 0), verts=bm.verts)
            sm = bpy.data.meshes.new(name)
            bm.to_mesh(sm)
            bm.free()
            sm.materials.append(mat)
            ob = bpy.data.objects.new(name, sm)
            coll.objects.link(ob)
            ob.hide_render = True
            strike_lines.append(ob)
        cam = bpy.data.objects.new("study_cam", bpy.data.cameras.new("study_cam"))
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
        return cam, line, strike_lines

    def bc_remove(coll):
        for o in list(coll.all_objects):
            bpy.data.objects.remove(o)
        bpy.data.collections.remove(coll)

    def style(bc, objs=None):
        m = bpy.data.materials
        m4r.principled(m[bc.SKIN], tuple(m4r.srgb_to_linear(PAINT_SRGB)), 0.6, 0.0)
        if objs is not None and hasattr(bc, "R4_NOSE"):  # round 4: the radome in the M4 radome grey
            radome = m.get("study_radome") or m.new("study_radome")
            m4r.principled(radome, tuple(m4r.srgb_to_linear(RADOME_SRGB)), 0.5, 0.0)
            objs["radar_F_fairing"].data.materials[0] = radome
            # The blockout's faceted panes mirror the ground in patches; slightly rough glass reads as one dark pane.
            m4r.principled(m[bc.GLASS], (0.008, 0.011, 0.010), 0.3, 0.0)
        m4r.principled(m[bc.STRUCT], (0.11, 0.115, 0.11), 0.7, 0.2)
        m4r.principled(m[bc.MECH], (0.06, 0.06, 0.065), 0.45, 0.8)
        m4r.principled(m[bc.GLASS], (0.008, 0.011, 0.010), 0.04, 0.0)
        m4r.principled(m[bc.GEAR], (0.16, 0.16, 0.165), 0.55, 0.3)

    def shoot(cam, view, path, samples, state, state_camera=STATE_CAMERA):
        (kind, k), loc, aim = VIEWS[view]
        kind, k = state_camera.get(state, {}).get(view, (kind, k))
        cam.location = Vector(loc)
        if kind == "ortho":
            cam.data.type, cam.data.ortho_scale = "ORTHO", k
            cam.rotation_euler = tuple(math.radians(a) for a in aim)
        else:
            cam.data.type, cam.data.lens = "PERSP", k
            cam.rotation_euler = (Vector(aim) - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.cycles.samples = samples
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1600, 1000, 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        return str(path)

    def pitched(bc, objs):
        """Pitch the airframe TAIL_STRIKE_MIN_DEG nose up about the main contact with the struts sagged (as the blockout's
        tail-strike render), yielding while pitched."""
        c = bc.main_contact(objs)
        roots = [o for o in objs.values() if o.parent is None]
        rest = {o: o.matrix_world.copy() for o in roots}
        pitch = (Matrix.Translation((0, c.y, 0)) @ Matrix.Rotation(-math.radians(bc.TAIL_STRIKE_MIN_DEG), 4, "X")
                 @ Matrix.Translation(-c))
        for o in roots:
            o.matrix_world = pitch @ rest[o]
        bpy.context.view_layer.update()
        return lambda: [setattr(o, "matrix_world", rest[o]) for o in roots]

    def tune_strike(v, target):
        """Round 3: the belly ramp's start station that puts the first tail contact at `target` deg, by secant
        iteration on retracted builds. A later start leaves a fuller aft body and a lower strike angle."""
        def strike(s0):
            vv = {**v, "upsweep_start": s0}
            b = configure(vv)
            ts = b.tail_strike(build(b, vv, 0.0))
            return ts["value"] - target, ts["first_contact"]["part"]
        a, b = v["upsweep_start"], v["upsweep_start"] + 1.0
        (fa, _), (fb, part) = strike(a), strike(b)
        for _ in range(8):
            if abs(fb) < 0.02 or fb == fa:
                break
            a, b, fa = b, b - fb * (b - a) / (fb - fa), fb
            fb, part = strike(b)
        return round(b, 2), round(fb + target, 2), part

    # ---------- main ----------
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"variants": "", "samples": "48", "out": "", "views": "", "round": "1", "tune_strike": ""}
    i = 0
    while i < len(argv):
        key = argv[i].lstrip("-")
        if key not in opts:
            raise SystemExit(f"unknown argument {argv[i]}")
        opts[key], i = argv[i + 1], i + 2
    order, state_views, state_camera, out = {
        "1": (ORDER, STATE_VIEWS, STATE_CAMERA, OUT), "2": (ORDER_R2, STATE_VIEWS_R2, STATE_CAMERA_R2, OUT_R2),
        "3": (ORDER_R3, STATE_VIEWS_R3, STATE_CAMERA_R2, OUT_R3),
        "4": (ORDER_R4, STATE_VIEWS_R4, STATE_CAMERA_R2, OUT_R4)}[opts["round"]]
    opts["variants"] = opts["variants"] or ",".join(order)
    out = Path(opts["out"] or out)
    if not out.is_absolute():
        raise SystemExit("Pass an absolute --out: Blender resolves relative paths against its own cwd.")
    out.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, opts["views"].split(",")))
    default = bpy.data.collections.get("Collection")
    if default is not None:
        bc_remove(default)
    cam, line, strike_lines = rig()
    if opts["tune_strike"]:
        for name in opts["variants"].split(","):
            s0, got, part = tune_strike(VARIANTS[name], float(opts["tune_strike"]))
            print(f"TUNE {name}: upsweep_start {s0} gives a tail strike of {got} deg at {part}")
        return
    for name in opts["variants"].split(","):
        v = VARIANTS[name]
        bc = configure(v)
        written = []
        for state, ext in (("retracted", 0.0), ("extended", 1.0)):
            objs = build(bc, v, ext)
            style(bc, objs)
            if state == "retracted":
                metrics_ret = measure(bc, v, {"retracted": objs})
            else:
                metrics_ext = measure(bc, v, {"extended": objs})
            for view in state_views[state]:
                if only and view not in only:
                    continue
                path = out / f"{name}_{view}_{state}.png"
                if view == "side_pitch12":
                    restore = pitched(bc, objs)
                    line.hide_render = False
                    written.append(shoot(cam, "side", path, int(opts["samples"]), state, state_camera))
                    line.hide_render = True
                    restore()
                elif view == "side_strike":
                    c = bc.main_contact(objs)
                    for ob, deg in zip(strike_lines, STRIKE_LINES[opts["round"]]):
                        ob.location, ob.rotation_euler, ob.hide_render = c, (math.radians(deg), 0, 0), False
                    written.append(shoot(cam, "side", path, int(opts["samples"]), state, state_camera))
                    for ob in strike_lines:
                        ob.hide_render = True
                else:
                    written.append(shoot(cam, view, path, int(opts["samples"]), state, state_camera))
        metrics = {**metrics_ret, "extended": metrics_ext["extended"], "renders": written}
        (out / f"metrics_{name}.json").write_text(json.dumps(metrics, indent=1, default=str))
        r = metrics["retracted"]
        if "ground" in r:
            print(f"STUDY {name}: ground {r['ground']} body top {r['height_without_tail_m']} roll {r['roll_inertia']}")
        print(f"STUDY {name}: retracted span {r['span_m']} height {r['height_m']} tail top {r['tail_top_m']} "
              f"tail strike {r['tail_strike']['value']} ({r['tail_strike']['first_contact']['part']}) "
              f"extended span {metrics['extended']['span_m']} AR {r['aspect_ratio']}/{metrics['extended']['aspect_ratio']} "
              f"CG {r['cg_empty']} nested {r['stage_vertices_outside_parent']} clashes {r['engine_clashes']}")
        if "strut" in r:
            print(f"STUDY {name}: length {r['length_m']} strut {r['strut']} gear {r['gear']} mac {r['wing_mac']} "
                  f"tail {r.get('tail_arms')} engines {r['engines']}")
        if "round4" in r:
            print(f"STUDY {name}: round4 {json.dumps(r['round4'])} tail {json.dumps(metrics['tail'])} "
                  f"nacelle {json.dumps(metrics['nacelle'])} fuselage {r['fuselage']}")
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "proportion_study_last.blend"), check_existing=False)


# =====================================================================================================================
# Compose side (plain Python, Pillow)
# =====================================================================================================================
def compose_helpers(out):
    """The sheet builder, the metrics reader and the render path for a renders directory."""
    from PIL import Image, ImageDraw, ImageFont

    def font(size):
        for f in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def tile(path, w, h):
        return Image.open(path).convert("RGB").resize((w, h), Image.LANCZOS)

    def sheet(rows, cols, path, title, tile_w=640, row_label_w=0, col_titles=None, row_titles=None, note=""):
        """rows x cols grid of (variant, view, state) render paths; missing renders are skipped as blank tiles."""
        tile_h = tile_w * 10 // 16
        head = 70 + (34 if col_titles else 0)
        foot = 40 if note else 0
        W, H = row_label_w + cols * tile_w, head + len(rows) * tile_h + foot
        img = Image.new("RGB", (W, H), (226, 228, 232))
        d = ImageDraw.Draw(img)
        d.text((16, 14), title, fill=(20, 20, 24), font=font(34))
        if col_titles:
            for c, t in enumerate(col_titles):
                d.text((row_label_w + c * tile_w + 12, 72), t, fill=(40, 40, 46), font=font(24))
        for r, row in enumerate(rows):
            for c, p in enumerate(row):
                if p and Path(p).exists():
                    img.paste(tile(p, tile_w, tile_h), (row_label_w + c * tile_w, head + r * tile_h))
            if row_titles:
                d.text((row_label_w + 12, head + r * tile_h + 8), row_titles[r], fill=(250, 250, 250), font=font(26),
                       stroke_width=2, stroke_fill=(30, 30, 30))
        if note:
            d.text((16, H - 34), note, fill=(60, 60, 66), font=font(20))
        img.save(path)
        return path

    def metrics(v):
        p = out / f"metrics_{v}.json"
        return json.loads(p.read_text()) if p.exists() else None

    return sheet, metrics, lambda v, view, state: out / f"{v}_{view}_{state}.png"


def compose_main(out):
    sheet, metrics, f = compose_helpers(out)
    labels = {k: VARIANTS[k]["label"] for k in ORDER}
    made = []
    # D against the blockout, straight from behind as the owner's sketch, both states.
    made.append(sheet([[f("current", "rear", "retracted"), f("D", "rear", "retracted")],
                       [f("current", "rear_full", "extended"), f("D", "rear_full", "extended")]], 2,
                      out / "D_sheet_rear.png", "Rear view: current blockout (left) and D, the owner's H-tail (right)",
                      tile_w=1280, row_titles=["retracted, tail close-up", "extended, full span"] * 1,
                      note="Orthographic, camera behind the aircraft looking forward. D: round fuselage 4.8 x 4.8 m, fuller aft body, "
                           "flat stabiliser with twin fins above and below."))
    for state in ("retracted", "extended"):
        views = ["hero", "side", "top", "front"]
        made.append(sheet([[f(v, view, state) for view in views] for v in ("current", "D")], 4,
                          out / f"D_sheet_{state}.png", f"Current blockout and D, {state}", col_titles=views,
                          row_titles=[labels["current"], labels["D"]]))
    mc, md = metrics("current"), metrics("D")
    ts = lambda m: f"{m['retracted']['tail_strike']['value']} deg, first contact {m['retracted']['tail_strike']['first_contact']['part']}" if m else "n/a"
    made.append(sheet([[f("current", "side_pitch12", "retracted"), f("D", "side_pitch12", "retracted")]], 2,
                      out / "D_sheet_tail_clearance.png", "Pitched 12 deg nose up about the main wheels (struts sagged), red runway line",
                      tile_w=1280, row_titles=None,
                      note=f"Clearance angle: current {ts(mc)}; D {ts(md)}. Pass is 12 deg or more."))
    # The main comparison: every variant, identical cameras.
    present = [v for v in ORDER if f(v, "hero", "retracted").exists()]
    for state in ("retracted", "extended"):
        views = ["hero", "side", "top", "front"]
        made.append(sheet([[f(v, view, state) for view in views] for v in present], 4, out / f"sheet_{state}.png",
                          f"MRB-100 Centurion proportion study, {state}", col_titles=views,
                          row_titles=[labels[v] for v in present]))
    rear = [[f(v, "rear", "retracted") for v in present]]
    made.append(sheet(rear, len(present), out / "sheet_rear.png", "Rear view, retracted, all variants",
                      tile_w=2560 // len(present), col_titles=[labels[v] for v in present]))
    made.append(sheet([[f(v, "side_pitch12", "retracted") for v in present]], len(present), out / "sheet_tail_clearance.png",
                      "Pitched 12 deg about the main wheels, all variants", tile_w=2560 // len(present),
                      col_titles=[f"{v}: {metrics(v)['retracted']['tail_strike']['value']} deg" if metrics(v) else v for v in present]))
    for p in made:
        print(p)


def compose_r2(out):
    """Round 2 sheets: the directions (each on the T1 V-tail), the strut close-ups, and the tail options on the D+A
    airframe. Main sheets are 2560 px wide."""
    sheet, metrics, f = compose_helpers(out)
    dirs, tails = ORDER_R2[:4], ("DA2_T1",) + ORDER_R2[4:]

    def dir_title(v):
        m = metrics(v)
        if not m:
            return VARIANTS[v]["label"]
        r, fs = m["retracted"], m["fuselage_section"]
        return f"{VARIANTS[v]['label']}: {r['length_m']:.1f} m long, {fs['width']:.1f} m body, AR {r['aspect_ratio']}/{m['extended']['aspect_ratio']}"

    def tail_title(v):
        m = metrics(v)
        label = TAILS["T1"]["tail_label"] if v == "DA2_T1" else VARIANTS[v]["label"]
        if not m:
            return label
        t = m["tail"]
        yaw = f"{t['yaw_effective_m2_folded']} folded" if t.get("folded") else t["yaw_effective_m2_total"]
        return f"{label}: yaw {yaw}, pitch {t['pitch_effective_m2_total']} m2, top {m['retracted']['tail_top_m']:.2f} m"

    made = []
    for state in ("retracted", "extended"):
        views = ["hero", "side", "top", "front", "rear_full"]
        made.append(sheet([[f(v, view, state) for view in views] for v in dirs], 5, out / f"sheet_r2_directions_{state}.png",
                          f"MRB-100 Centurion proportion study round 2: directions, {state} (all on the T1 V-tail)",
                          tile_w=512, col_titles=views, row_titles=[dir_title(v) for v in dirs]))
    views = ["rear", "front_close", "strut"]
    made.append(sheet([[f(v, view, "retracted") for view in views] for v in dirs], 3, out / "sheet_r2_strut.png",
                      "Straight strut: rear and front close-ups, and from low behind the left wing", tile_w=2560 // 3,
                      col_titles=["rear (orthographic)", "front (orthographic)", "low rear quarter"],
                      row_titles=[VARIANTS[v]["label"] for v in dirs]))
    made.append(sheet([[f(v, "side_pitch12", "retracted") for v in dirs]], 4, out / "sheet_r2_directions_clearance.png",
                      "Directions pitched 12 deg about the main wheels (struts sagged), red runway line", tile_w=640,
                      col_titles=[f"{v}: {metrics(v)['retracted']['tail_strike']['value']} deg" if metrics(v) else v for v in dirs]))
    views = ["hero", "side", "top", "rear", "side_pitch12"]
    made.append(sheet([[f(v, view, "retracted") for view in views] for v in tails], 5, out / "sheet_r2_tails_retracted.png",
                      "Tail options on the D+A airframe, retracted (side_pitch12: pitched 12 deg about the main wheels)",
                      tile_w=512, col_titles=views, row_titles=[tail_title(v) for v in tails],
                      note="Current aero data: V-tail 16 + 16 m2 a side at 32 deg, 46.0 m2 pitch-effective and 18.0 m2 yaw-effective."))
    views = ["hero", "side", "top", "front", "rear_full"]
    made.append(sheet([[f(v, view, "extended") for view in views] for v in tails], 5, out / "sheet_r2_tails_extended.png",
                      "Tail options on the D+A airframe, extended", tile_w=512, col_titles=views,
                      row_titles=[tail_title(v) for v in tails]))
    made.append(sheet([[f("DA2_T2", "rear", "retracted"), f("DA2_T2f", "rear", "retracted")],
                       [f("DA2_T2", "hero", "retracted"), f("DA2_T2f", "hero", "retracted")]], 2, out / "sheet_r2_T2_fold.png",
                      "T2 folding fin: raised for flight (left), folded for the hangar door and taxi (right)", tile_w=1280))
    for p in made:
        print(p)


def tables_r2(out):
    """Print docs/PROPORTION-STUDY.md's round 2 tables (Markdown) from the metrics."""
    sys.stdout.reconfigure(encoding="utf-8")
    load = lambda v: json.loads((out / f"metrics_{v}.json").read_text())
    rows = lambda ms, spec: "\n".join(f"| {name} | " + " | ".join(str(fn(m)) for m in ms) + " |" for name, fn in spec)
    dirs = ORDER_R2[:4]
    ms = [load(v) for v in dirs]
    R = lambda m: m["retracted"]
    clr = lambda m, e: R(m)["strut"]["clearance"][f"engine_{e}"]
    spec = [
        ("Length (m)", lambda m: R(m)["length_m"]),
        ("Fuselage width x height (m), fineness", lambda m: f"{m['fuselage_section']['width']} x {m['fuselage_section']['height']}, {m['fuselage_section']['fineness']}"),
        ("Fuselage volume / aft body (m³)", lambda m: f"{R(m)['fuselage']['volume_m3']:.0f} / {R(m)['fuselage']['aft_body_volume_m3']:.0f}"),
        ("Fixed wing root / node / tip chord (m), taper", lambda m: f"{m['wing']['root_chord']} / {m['wing']['node_chord']} / {m['wing']['tip_chord_fixed']}, {m['wing']['taper_fixed']}"),
        ("Stage chords (m)", lambda m: " / ".join(str(c) for c in m["wing"]["stage_chords"])),
        ("Wing gross area retracted / extended (m²)", lambda m: f"{R(m)['wing_gross_m2']:.0f} / {m['extended']['wing_gross_m2']:.0f}"),
        ("Gross AR retracted / extended", lambda m: f"{R(m)['aspect_ratio']} / {m['extended']['aspect_ratio']}"),
        ("Span retracted / extended (m)", lambda m: f"{R(m)['span_m']:.2f} / {m['extended']['span_m']:.2f}"),
        ("Height, tail top (m)", lambda m: f"{R(m)['height_m']:.2f}, {R(m)['tail_top_m']:.2f}"),
        ("Nacelle OD, cowl L/D, OD over body width", lambda m: f"{m['nacelle']['outer_diameter']}, {m['nacelle']['cowl_L_over_D']}, {m['nacelle']['od_over_fuselage_width']}"),
        ("Nacelle semi-span; intake stations", lambda m: f"{m['nacelle']['positions'][1][2]}, {m['nacelle']['positions'][0][2]}; {R(m)['engines']['nacelle_2']['intake_station']}, {R(m)['engines']['nacelle_1']['intake_station']}"),
        ("Strut root (x, station, z) to node", lambda m: f"({', '.join(str(c) for c in R(m)['strut']['root'])}) to ({', '.join(str(c) for c in R(m)['strut']['node'])})"),
        ("Strut length, rise in rear view", lambda m: f"{R(m)['strut']['length_m']} m, {R(m)['strut']['rise_in_rear_view_deg']} deg"),
        ("Strut to inner / outer nozzle (m)", lambda m: f"{clr(m, 2)['strut_to_nozzle_2_m']:.2f} / {clr(m, 1)['strut_to_nozzle_1_m']:.2f}"),
        ("Strut line behind inner / outer nozzle exit (m)", lambda m: f"{clr(m, 2)['strut_line_behind_exit_m']} / {clr(m, 1)['strut_line_behind_exit_m']}"),
        ("Strut to nacelles, pylons, nearest (m)", lambda m: f"{min(clr(m, e)[f'strut_to_{p}_{e}_m'] for e in (1, 2) for p in ('nacelle', 'pylon')):.2f}"),
        ("Main gear station, track (m)", lambda m: f"{R(m)['gear']['main_station']}, {R(m)['gear']['track_m']}"),
        ("Main gear behind CG (m), nose-gear share", lambda m: f"{R(m)['gear']['main_behind_cg_m']}, {R(m)['gear']['nose_gear_load_share']}"),
        ("Empty CG station / height (m)", lambda m: f"{R(m)['cg_empty']['station']} / {R(m)['cg_empty']['height_m']}"),
        ("Fixed-wing MAC (m), CG at % MAC", lambda m: f"{R(m)['wing_mac']['mac_m']}, {R(m)['wing_mac']['cg_percent_mac']}"),
        ("Stage 1 hull centre / lift station, retracted", lambda m: f"{R(m)['stages']['tele1_centre'][1]} / {R(m)['stages']['tele1_lift_station']}"),
        ("Stage 1 hull centre / lift station, extended", lambda m: f"{m['extended']['stages']['tele1_centre'][1]} / {m['extended']['stages']['tele1_lift_station']}"),
        ("Stage 2 hull centre, retracted / extended", lambda m: f"{R(m)['stages']['tele2_centre'][1]} / {m['extended']['stages']['tele2_centre'][1]}"),
        ("T1 yaw / pitch effective (m²)", lambda m: f"{m['tail']['yaw_effective_m2_total']} / {m['tail']['pitch_effective_m2_total']}"),
        ("Tail arms yaw / pitch (m)", lambda m: f"{R(m)['tail_arms']['yaw_arm_m']} / {R(m)['tail_arms']['pitch_arm_m']}"),
        ("Tail volumes vertical / horizontal", lambda m: f"{R(m)['tail_arms']['vertical_volume']} / {R(m)['tail_arms']['horizontal_volume']}"),
        ("Tail clearance, first contact", lambda m: f"{R(m)['tail_strike']['value']}, {R(m)['tail_strike']['first_contact']['part']}"),
        ("Stages nested, engine clashes", lambda m: f"{sum(R(m)['stage_vertices_outside_parent'].values())} outside, {len(R(m)['engine_clashes'])}"),
    ]
    print("| | " + " | ".join(VARIANTS[v]["label"] for v in dirs) + " |\n|---|" + "---|" * len(dirs))
    print(rows(ms, spec))
    tails = ("DA2_T1",) + ORDER_R2[4:]
    ms = [load(v) for v in tails]
    T = lambda m: m["tail"]
    spec = [
        ("Kind", lambda m: T(m)["kind"]),
        ("Yaw-effective area (m²)", lambda m: T(m)["yaw_effective_m2_total"] if not T(m).get("folded") else f"{T(m)['yaw_effective_m2_folded']} folded"),
        ("Pitch-effective area (m²)", lambda m: T(m)["pitch_effective_m2_total"]),
        ("Surfaces (m²)", lambda m: "; ".join(text for key, text in (
            ("panel_m2_each", "panel {} a side"), ("stabiliser_m2_each_side", "stabiliser {} a side"),
            ("fin_m2_each", "fin {} each"), ("fin_exposed_m2", "fin {}")) if key in T(m) for text in [text.format(T(m)[key])])
         + (f" (stub {T(m)['fin_stub_m2']})" if "fin_stub_m2" in T(m) else "")),
        ("Tail top (m)", lambda m: f"{R(m)['tail_top_m']:.2f}"),
        ("Tail span (m)", lambda m: max(T(m).get("stabiliser_span_m", 0), T(m).get("tail_span_m", 0))),
        ("Arms yaw / pitch (m)", lambda m: f"{R(m)['tail_arms']['yaw_arm_m']} / {R(m)['tail_arms']['pitch_arm_m']}"),
        ("Volumes vertical / horizontal", lambda m: f"{R(m)['tail_arms']['vertical_volume']} / {R(m)['tail_arms']['horizontal_volume']}"),
        ("Tail clearance, first contact", lambda m: f"{R(m)['tail_strike']['value']}, {R(m)['tail_strike']['first_contact']['part']}"),
        ("Empty CG station", lambda m: R(m)["cg_empty"]["station"]),
    ]
    print("\n| | " + " | ".join(TAILS["T1"]["tail_label"] if v == "DA2_T1" else VARIANTS[v]["label"] for v in tails)
          + " |\n|---|" + "---|" * len(tails))
    print(rows(ms, spec))


def compose_r3(out):
    """Round 3 sheets, 2560 px wide: the tails on E, the T5 close-ups, E's wing group at three stations, and the body
    and engine options."""
    sheet, metrics, f = compose_helpers(out)
    tails, wings = ORDER_R3[:5], ("E_T5a", "E2_T5a", "E4_T5a")

    def tail_title(v):
        m = metrics(v)
        if not m:
            return VARIANTS[v]["label"]
        t = m["tail"]
        yaw = f"{t['yaw_effective_m2_folded']} folded" if t.get("folded") else t["yaw_effective_m2_total"]
        return f"{VARIANTS[v]['label']}: yaw {yaw}, pitch {t['pitch_effective_m2_total']} m2, top {m['retracted']['tail_top_m']:.2f} m"

    def wing_title(v):
        m = metrics(v)
        label = "E as is (T5a)" if v == "E_T5a" else VARIANTS[v]["label"]
        if not m:
            return label
        r = m["retracted"]
        return (f"{label}: wing root LE {r['wing_mac']['root_le_station']}, CG {r['wing_mac']['cg_percent_mac']}% MAC, "
                f"nose gear {100 * r['gear']['nose_gear_load_share']:.0f}%, strike {r['tail_strike']['value']} deg")

    def body_title(v):
        m = metrics(v)
        label = BODY_TITLES[v]
        if not m:
            return label
        n = len(m["nacelle"]["positions"])
        return (f"{label}: {m['fuselage_section']['width']} m body, {n} x {m['nacelle']['outer_diameter']} m nacelles, "
                f"ratio {m['nacelle']['od_over_fuselage_width']}, top {m['retracted']['height_without_tail_m']:.2f} m")

    note = "Current aero data: V-tail 16 + 16 m2 a side at 32 deg, 46.0 m2 pitch-effective and 18.0 m2 yaw-effective."
    lines = "Strike view: ground lines from the main wheels at 9.5 deg (red) and 12 deg (amber); a part under a line strikes at that attitude."
    made = []
    views = ["hero", "side", "top", "rear", "side_strike"]
    made.append(sheet([[f(v, view, "retracted") for view in views] for v in tails], 5, out / "sheet_r3_tails_retracted.png",
                      "Round 3: tails on E, retracted (rear close-up; side_strike: ground lines at 9.5 and 12 deg)",
                      tile_w=512, col_titles=views, row_titles=[tail_title(v) for v in tails], note=note + " " + lines))
    views = ["hero", "side", "top", "front", "rear_full"]
    made.append(sheet([[f(v, view, "extended") for view in views] for v in tails], 5, out / "sheet_r3_tails_extended.png",
                      "Round 3: tails on E, extended", tile_w=512, col_titles=views,
                      row_titles=[tail_title(v) for v in tails], note=note))
    made.append(sheet([[f("E_T5a", "rear", "retracted"), f("E_T5b", "rear", "retracted")],
                       [f("E_T5a", "hero", "retracted"), f("E_T5b", "hero", "retracted")]], 2, out / "sheet_r3_T5_close.png",
                      "T5: T3's fins canted 20 deg out on the stabiliser tips. T5a above only (left), T5b above and below (right)",
                      tile_w=1280))
    views = [("hero", "retracted"), ("side", "retracted"), ("top", "retracted"), ("side_strike", "retracted"), ("hero", "extended")]
    made.append(sheet([[f(v, view, state) for view, state in views] for v in wings], 5, out / "sheet_r3_wing_station.png",
                      "Round 3: E's wing group as is, 2 m aft and 4 m aft (T5a tail, same cameras)", tile_w=512,
                      col_titles=["hero", "side", "top", "strike lines 9.5 / 12 deg", "hero, extended"],
                      row_titles=[wing_title(v) for v in wings], note=lines))
    views = [("hero", "retracted"), ("side", "retracted"), ("front", "retracted"), ("top", "retracted"), ("hero", "extended")]
    made.append(sheet([[f(v, view, state) for view, state in views] for v in BODY_TITLES], 5, out / "sheet_r3_body_engines.png",
                      "Round 3: body and engines, wing group 2 m aft, T5a (C-17 and An-124 nacelle over body diameter about 0.4 to 0.45)",
                      tile_w=512, col_titles=["hero", "side", "front", "top", "hero, extended"],
                      row_titles=[body_title(v) for v in BODY_TITLES]))
    for p in made:
        print(p)


def tables_r3(out):
    """Print docs/PROPORTION-STUDY.md's round 3 tables (Markdown) from the metrics."""
    sys.stdout.reconfigure(encoding="utf-8")
    load = lambda v: json.loads((out / f"metrics_{v}.json").read_text())
    rows = lambda ms, spec: "\n".join(f"| {name} | " + " | ".join(str(fn(m)) for m in ms) + " |" for name, fn in spec)
    R, T = (lambda m: m["retracted"]), (lambda m: m["tail"])
    tails = ORDER_R3[:6]
    ms = [load(v) for v in tails]
    aero_yaw, aero_pitch = 4 * AERO_TAIL_M2 * math.sin(math.radians(32)) ** 2, 4 * AERO_TAIL_M2 * math.cos(math.radians(32)) ** 2
    yaw = lambda m: T(m)["yaw_effective_m2_folded"] if T(m).get("folded") else T(m)["yaw_effective_m2_total"]
    spec = [
        ("Yaw-effective area (m²), against 18.0", lambda m: f"{yaw(m)}{' folded' if T(m).get('folded') else ''}, {yaw(m) / aero_yaw:.2f}x"),
        ("Pitch-effective area (m²), against 46.0", lambda m: f"{T(m)['pitch_effective_m2_total']}, {T(m)['pitch_effective_m2_total'] / aero_pitch:.2f}x"),
        ("Surfaces (m²)", lambda m: "; ".join(text.format(T(m)[key]) for key, text in (
            ("stabiliser_m2_each_side", "stabiliser {} a side"), ("panel_m2_each", "canted fin {} each"),
            ("fin_m2_each", "fin {} each"), ("fin_exposed_m2", "fin {}")) if key in T(m))),
        ("Tail top (m)", lambda m: f"{R(m)['tail_top_m']:.2f}"),
        ("Tail span (m)", lambda m: max(T(m).get("stabiliser_span_m", 0), T(m).get("tail_span_m", 0))),
        ("Tail strike (deg), first contact", lambda m: f"{R(m)['tail_strike']['value']}, {R(m)['tail_strike']['first_contact']['part']}"),
        ("Length (m)", lambda m: R(m)["length_m"]),
        ("Arms yaw / pitch (m)", lambda m: f"{R(m)['tail_arms']['yaw_arm_m']} / {R(m)['tail_arms']['pitch_arm_m']}"),
        ("Volumes vertical / horizontal", lambda m: f"{R(m)['tail_arms']['vertical_volume']} / {R(m)['tail_arms']['horizontal_volume']}"),
        ("Mass on each tail tip (kg)", lambda m: R(m)["roll_inertia"]["tip_mass_kg_each_side"]),
        ("Tail group roll inertia (kg m²)", lambda m: f"{R(m)['roll_inertia']['tail_group_kg_m2']:,}"),
        ("Empty CG station", lambda m: R(m)["cg_empty"]["station"]),
    ]
    print("| | " + " | ".join(VARIANTS[v]["label"] for v in tails) + " |\n|---|" + "---|" * len(tails))
    print(rows(ms, spec))
    wings = ("E_T5a", "E2_T5a", "E4_T5a")
    ms = [load(v) for v in wings]
    base = ms[0]
    spec = [
        ("Wing root LE / fixed-wing quarter-MAC station", lambda m: f"{R(m)['wing_mac']['root_le_station']} / {R(m)['wing_mac']['quarter_chord_station']}"),
        ("Strut root station, node station", lambda m: f"{R(m)['strut']['root'][1]}, {R(m)['strut']['node'][1]}"),
        ("Intake stations inner / outer", lambda m: f"{R(m)['engines']['nacelle_2']['intake_station']} / {R(m)['engines']['nacelle_1']['intake_station']}"),
        ("Main gear station", lambda m: R(m)["gear"]["main_station"]),
        ("Empty CG station (moved)", lambda m: f"{R(m)['cg_empty']['station']} ({R(m)['cg_empty']['station'] - R(base)['cg_empty']['station']:+.2f})"),
        ("CG at % MAC (moved)", lambda m: f"{R(m)['wing_mac']['cg_percent_mac']} ({R(m)['wing_mac']['cg_percent_mac'] - R(base)['wing_mac']['cg_percent_mac']:+.1f})"),
        ("Main gear behind CG (m), nose-gear share", lambda m: f"{R(m)['gear']['main_behind_cg_m']}, {100 * R(m)['gear']['nose_gear_load_share']:.1f}%"),
        ("Belly ramp starts at station", lambda m: round(m["params"]["upsweep_start"] + sum(p[2] for p in m["params"]["plugs"]), 2)),
        ("Static attitude / strike attitude / rotation allowed (deg)", lambda m: f"{R(m)['ground']['static_attitude_deg']} / {R(m)['ground']['strike_attitude_deg']} / {R(m)['ground']['rotation_from_static_deg']}"),
        ("Strike first contact", lambda m: f"{R(m)['tail_strike']['first_contact']['part']} at {R(m)['tail_strike']['first_contact']['station']}"),
        ("Tail arms yaw / pitch (m)", lambda m: f"{R(m)['tail_arms']['yaw_arm_m']} / {R(m)['tail_arms']['pitch_arm_m']}"),
        ("Tail volumes vertical / horizontal", lambda m: f"{R(m)['tail_arms']['vertical_volume']} / {R(m)['tail_arms']['horizontal_volume']}"),
        ("Length (m), stages nested, engine clashes", lambda m: f"{R(m)['length_m']}, {sum(R(m)['stage_vertices_outside_parent'].values())} outside, {len(R(m)['engine_clashes'])}"),
    ]
    print("\n| | E as is (T5a) | " + " | ".join(VARIANTS[v]["label"] for v in wings[1:]) + " |\n|---|" + "---|" * len(wings))
    print(rows(ms, spec))

    # Body and engines, on the wing 2 m aft with T5a.
    bodies = tuple(BODY_TITLES)
    ms = [load(v) for v in bodies]
    base = ms[0]
    E = lambda m: R(m)["engines"]["nacelle_1"]
    n_eng = lambda m: len(m["nacelle"]["positions"])
    clr = lambda m: min(val for d in R(m)["strut"]["clearance"].values() for key, val in d.items() if key.endswith("_m") and ("nozzle" in key or "nacelle" in key or "pylon" in key))
    spec = [
        ("Body width x height (m), fineness", lambda m: f"{m['fuselage_section']['width']} x {m['fuselage_section']['height']}, {m['fuselage_section']['fineness']}"),
        ("Top of wing fairing / tail (m), door 8.0", lambda m: f"{R(m)['height_without_tail_m']:.2f} / {R(m)['tail_top_m']:.2f}"),
        ("Belly ground clearance (m)", lambda m: R(m)["ground"]["belly_clearance_m"]),
        ("Engines x thrust (kN)", lambda m: f"{n_eng(m)} x {THRUST_KN[n_eng(m)]:.0f}"),
        ("Nacelle OD, cowl length (m), OD over body", lambda m: f"{m['nacelle']['outer_diameter']}, {m['nacelle']['cowl_length']}, {m['nacelle']['od_over_fuselage_width']}"),
        ("Nacelle semi-span (m), ground clearance (m)", lambda m: f"{', '.join(str(p[2]) for p in m['nacelle']['positions'] if p[1] > 0)}; {E(m)['ground_clearance_m']}"),
        ("Nearest strut or jury strut to a nacelle, nozzle or pylon (m)", lambda m: f"{clr(m):.2f}"),
        ("Inner nacelle to sponson (m)", lambda m: min(e["to_sponson_m"] for e in R(m)["engines"].values())),
        ("Empty CG station / height (m), moved", lambda m: f"{R(m)['cg_empty']['station']} / {R(m)['cg_empty']['height_m']} ({R(m)['cg_empty']['station'] - R(base)['cg_empty']['station']:+.2f} / {R(m)['cg_empty']['height_m'] - R(base)['cg_empty']['height_m']:+.2f})"),
        ("CG at % MAC, nose-gear share", lambda m: f"{R(m)['wing_mac']['cg_percent_mac']}, {100 * R(m)['gear']['nose_gear_load_share']:.1f}%"),
        ("Roll inertia, point masses (kg m²), against E body four", lambda m: f"{R(m)['roll_inertia']['total_kg_m2']:,} ({R(m)['roll_inertia']['total_kg_m2'] / R(base)['roll_inertia']['total_kg_m2'] - 1:+.0%})"),
        ("One engine out: yaw moment (kN m)", lambda m: f"{THRUST_KN[n_eng(m)] * max(p[2] for p in m['nacelle']['positions']):,.0f}"),
        ("T5a yaw / pitch effective (m²)", lambda m: f"{T(m)['yaw_effective_m2_total']} / {T(m)['pitch_effective_m2_total']}"),
        ("Tail strike (deg), first contact", lambda m: f"{R(m)['tail_strike']['value']}, {R(m)['tail_strike']['first_contact']['part']}"),
        ("Stages nested, engine clashes", lambda m: f"{sum(R(m)['stage_vertices_outside_parent'].values())} outside, {len(R(m)['engine_clashes'])}"),
    ]
    print("\n| | " + " | ".join(VARIANTS[v]["label"] for v in bodies) + " |\n|---|" + "---|" * len(bodies))
    print(rows(ms, spec))

    # One engine out against each tail: the dynamic pressure at which full rudder holds the yaw, from the tail's
    # yaw-effective area and arm on E with an assumed side-force coefficient, as a speed at sea level.
    cy, rho = 0.6, 1.225
    layouts = {"four, outer engine out (135 kN at 11.2 m)": 135.0 * 11.2, f"twin (270 kN at {TWIN_X} m)": 270.0 * TWIN_X}
    tails = [v for v in ORDER_R3[:6] if v != "E_T2f"]
    print(f"\n| One engine out, speed where full rudder holds it (m/s, side-force coefficient {cy}) | " + " | ".join(layouts) + " |\n|---|---|---|")
    for v in tails:
        m = load(v)
        cap = T(m)["yaw_effective_m2_total"] * R(m)["tail_arms"]["yaw_arm_m"] * cy
        print(f"| {VARIANTS[v]['label']} | " + " | ".join(f"{math.sqrt(2 * n * 1000 / (rho * cap)):.0f}" for n in layouts.values()) + " |")


def compose_r4(out):
    """Round 4 sheets, 2560 px wide: the strut-echo V-tail and T5a on the same airframe, retracted and extended, the
    front and rear views at span scale, the strike lines, and the nose, engine and strut close-ups."""
    sheet, metrics, f = compose_helpers(out)
    rows = ORDER_R4

    def title(v):
        m = metrics(v)
        if not m:
            return VARIANTS[v]["label"]
        t, r = m["tail"], m["retracted"]
        return (f"{VARIANTS[v]['label']}: yaw {t['yaw_effective_m2_total']}, pitch {t['pitch_effective_m2_total']} m2, "
                f"top {r['tail_top_m']:.2f} m, strike {r['tail_strike']['value']} deg")
    lines = f"Strike view: ground lines from the main wheels at {R4_STRIKE} deg (red, the strike) and 9.5 deg (amber, the takeoff AI's pitch target)."
    made = []
    views = ["hero", "side", "top", "side_strike"]
    made.append(sheet([[f(v, view, "retracted") for view in views] for v in rows], 4, out / "sheet_r4_retracted.png",
                      "Round 4: E, 6.19 m body, twin 4.75 m late-UltraFans, node at 19.4 m, M4 nose; retracted",
                      tile_w=640, col_titles=views, row_titles=[title(v) for v in rows], note=lines))
    views = ["hero", "side", "top", "front", "rear_full"]
    made.append(sheet([[f(v, view, "extended") for view in views] for v in rows], 5, out / "sheet_r4_extended.png",
                      "Round 4: extended (68.2 m)", tile_w=512, col_titles=views, row_titles=[title(v) for v in rows]))
    made.append(sheet([[f("E4_vee", "front_span", "retracted"), f("E4_vee", "rear_span", "retracted")],
                       [f("E4_T5a", "front_span", "retracted"), f("E4_T5a", "rear_span", "retracted")]], 2,
                      out / "sheet_r4_front_rear.png",
                      "Front (left) and rear (right), orthographic: the strut passes under both nacelles; strut-echo V-tail (top), T5a (bottom)",
                      tile_w=1280))
    made.append(sheet([[f("E4_vee", "side_strike", "retracted"), f("E4_T5a", "side_strike", "retracted")],
                       [f("E4_vee", "rear", "retracted"), f("E4_T5a", "rear", "retracted")]], 2,
                      out / "sheet_r4_strike_tail.png",
                      f"Tail strike at {R4_STRIKE} deg and the tails from behind: strut-echo V-tail (left), T5a (right)",
                      tile_w=1280, note=lines))
    m4_nose = REPO / "docs" / "progress" / "img" / "40_m4_nose_34.jpg"
    made.append(sheet([[f("E4_vee", "nose34", "retracted"), f("E4_vee", "nose_side", "retracted"), m4_nose],
                       [f("E4_vee", "engine34", "retracted"), f("E4_vee", "engine_rear", "retracted"),
                        f("E4_vee", "strut_r4", "retracted")]], 3, out / "sheet_r4_details.png",
                      "Close-ups: the M4 nose scaled to the 6.19 m body (M4 reference top right); the late-UltraFan and the strut",
                      tile_w=2560 // 3,
                      row_titles=["nose 3/4, nose side, M4 detailed nose (reference)",
                                  "engine from low ahead, engine from low behind, strut from low behind"]))
    for p in made:
        print(p)


def tables_r4(out):
    """Print docs/PROPORTION-STUDY.md's round 4 tables (Markdown) from the metrics."""
    sys.stdout.reconfigure(encoding="utf-8")
    load = lambda v: json.loads((out / f"metrics_{v}.json").read_text())
    rows = lambda ms, spec: "\n".join(f"| {name} | " + " | ".join(str(fn(m)) for m in ms) + " |" for name, fn in spec)
    R, T, Q = (lambda m: m["retracted"]), (lambda m: m["tail"]), (lambda m: m["retracted"]["round4"])
    sil = lambda d: f"gap {d['gap_m']}" if not d["overlap_m2"] else f"overlap {d['overlap_m2']} m²"
    ms = [load(v) for v in ORDER_R4]
    aero_yaw, aero_pitch = 4 * AERO_TAIL_M2 * math.sin(math.radians(32)) ** 2, 4 * AERO_TAIL_M2 * math.cos(math.radians(32)) ** 2
    spec = [
        ("Length / height, wing fairing top / tail top (m)", lambda m: f"{R(m)['length_m']:.2f} / {R(m)['height_without_tail_m']:.2f} / {R(m)['tail_top_m']:.2f}"),
        ("Span retracted / extended, tail span (m)", lambda m: f"{R(m)['span_m']:.2f} / {m['extended']['span_m']:.2f}, {max(T(m).get('stabiliser_span_m', 0), T(m).get('tail_span_m', 0))}"),
        ("Fuselage / aft-body volume (m³)", lambda m: f"{R(m)['fuselage']['volume_m3']:.0f} / {R(m)['fuselage']['aft_body_volume_m3']:.0f}"),
        ("Strike (deg), first contact", lambda m: f"{R(m)['tail_strike']['value']}, {R(m)['tail_strike']['first_contact']['part']} at {R(m)['tail_strike']['first_contact']['station']}"),
        ("Tail parts first touch at (deg); lowest tail point (x, station, z)", lambda m: f"{Q(m)['tail_strike_by_tail_parts_deg']}; {tuple(Q(m)['tail_lowest_point'])}"),
        ("Static attitude / rotation allowed (deg)", lambda m: f"{R(m)['ground']['static_attitude_deg']} / {R(m)['ground']['rotation_from_static_deg']}"),
        ("Yaw-effective (m²), against T5a on round 3's E 33.4 and the data's 18.0", lambda m: f"{T(m)['yaw_effective_m2_total']}, {T(m)['yaw_effective_m2_total'] / 33.4:.2f}x / {T(m)['yaw_effective_m2_total'] / aero_yaw:.2f}x"),
        ("Pitch-effective (m²), against 52.2 and 46.0", lambda m: f"{T(m)['pitch_effective_m2_total']}, {T(m)['pitch_effective_m2_total'] / 52.2:.2f}x / {T(m)['pitch_effective_m2_total'] / aero_pitch:.2f}x"),
        ("Surfaces (m²)", lambda m: "; ".join(text.format(T(m)[key]) for key, text in (
            ("panel_m2_each", "panel {} a side"), ("moving_surface_m2_each", "ruddervator {} each"),
            ("stabiliser_m2_each_side", "stabiliser {} a side"), ("elevator_m2_each", "elevator {} each"), ("fin_m2_each", "fin {} each")) if key in T(m))),
        ("Arms yaw / pitch (m)", lambda m: f"{R(m)['tail_arms']['yaw_arm_m']} / {R(m)['tail_arms']['pitch_arm_m']}"),
        ("Volumes vertical / horizontal", lambda m: f"{R(m)['tail_arms']['vertical_volume']} / {R(m)['tail_arms']['horizontal_volume']}"),
        ("Tail group roll inertia (kg m²), mass on each tip (kg)", lambda m: f"{R(m)['roll_inertia']['tail_group_kg_m2']:,}, {R(m)['roll_inertia']['tip_mass_kg_each_side']}"),
        ("Empty CG station / height (m), % MAC", lambda m: f"{R(m)['cg_empty']['station']} / {R(m)['cg_empty']['height_m']}, {R(m)['wing_mac']['cg_percent_mac']}"),
        ("Main gear behind CG (m), nose-gear share", lambda m: f"{R(m)['gear']['main_behind_cg_m']}, {100 * R(m)['gear']['nose_gear_load_share']:.1f}%"),
        ("AWACS well stations, tail parts to the well (m)", lambda m: f"{Q(m)['awacs_well']['stations'][0]} to {Q(m)['awacs_well']['stations'][1]}, {Q(m)['awacs_well']['tail_parts_to_well_m']}"),
        ("Stages nested, engine clashes", lambda m: f"{sum(R(m)['stage_vertices_outside_parent'].values())} outside, {len(R(m)['engine_clashes'])}"),
    ]
    print("| | " + " | ".join(VARIANTS[v]["label"] for v in ORDER_R4) + " |\n|---|" + "---|" * len(ORDER_R4))
    print(rows(ms, spec))

    m = ms[0]
    r, q, n, s = R(m), Q(m), m["nacelle"], R(m)["strut"]
    e = r["engines"]["nacelle_1"]
    print("\n| Airframe (both tails) | |\n|---|---|")
    for k, val in (
            ("Nacelle OD, cowl length, overall with nozzle (m), cowl L/D", f"{n['outer_diameter']}, {n['cowl_length']}, {n['overall_length']}, {n['cowl_L_over_D']}"),
            ("Nacelle over body diameter", n["od_over_fuselage_width"]),
            ("Engine semi-span (m), axis height (m), intake station", f"{e['semi_span']}, {s['clearance']['engine_1']['jet_axis_height']:.2f}, {e['intake_station']}"),
            ("Nacelle ground clearance, to the sponson (m)", f"{e['ground_clearance_m']}, {e['to_sponson_m']}"),
            ("Strut root (x, station, z) to node", f"({', '.join(str(c) for c in s['root'])}) to ({', '.join(str(c) for c in s['node'])})"),
            ("Strut length, rise in front view, forward lean in plan", f"{s['length_m']} m, {s['rise_in_rear_view_deg']} deg, {s['forward_lean_in_plan_deg']} deg"),
            ("Jury strut: length, foot to top", f"{q['jury_strut']['length_m']} m, {tuple(q['jury_strut']['foot'])} to {tuple(q['jury_strut']['top'])}"),
            ("Strut against the nacelle, front and rear views", sil(q["strut_vs_nacelle_front_or_rear"])),
            ("Strut against the nacelle / pylon, side view", f"{sil(q['strut_vs_nacelle_side'])} / {sil(q['strut_vs_pylon_side'])}"),
            ("Jury strut against the nacelle, front / side view", f"{sil(q['jury_vs_nacelle_front_or_rear'])} / {sil(q['jury_vs_nacelle_side'])}"),
            ("Strut or jury strut to the nacelle or pylon, 3D (m)", q["strut_to_nacelle_3d_m"]),
            ("One engine out, yaw moment (kN m)", ", ".join(f"{k2}: {v2:,}" for k2, v2 in q["engine_out_yaw_kN_m"].items())),
            ("AWACS well: stations, crown, floor, belly under the mast (m)", f"{q['awacs_well']['stations']}, {q['awacs_well']['crown_m'][0]}, {q['awacs_well']['floor_m']}, {q['awacs_well']['belly_at_mast_m']}"),
            ("Wing root trailing edge on the crown (station)", q["awacs_well"]["wing_root_te_station"])):
        print(f"| {k} | {val} |")

    cy, rho = 0.6, 1.225
    print(f"\n| One engine out, speed where full rudder holds it (m/s, side-force coefficient {cy}) | "
          + " | ".join(f"{t:.0f} kN at {R(ms[0])['engines']['nacelle_1']['semi_span']} m" for t in THRUST_R4_KN) + " |\n|---|---|---|")
    for v, m in zip(ORDER_R4, ms):
        cap = T(m)["yaw_effective_m2_total"] * R(m)["tail_arms"]["yaw_arm_m"] * cy
        print(f"| {VARIANTS[v]['label']} | " + " | ".join(
            f"{math.sqrt(2 * t * R(m)['engines']['nacelle_1']['semi_span'] * 1000 / (rho * cap)):.0f}" for t in THRUST_R4_KN) + " |")


def round_arg(args):
    return args[args.index("--round") + 1] if "--round" in args else "1"


if __name__ == "__main__" and "--table" in sys.argv:
    tables, out_dir = {"1": (tables_r2, OUT_R2), "2": (tables_r2, OUT_R2), "3": (tables_r3, OUT_R3),
                       "4": (tables_r4, OUT_R4)}[round_arg(sys.argv)]
    tables(out_dir)
elif __name__ == "__main__" and "--compose" in sys.argv:
    args = sys.argv[1:]
    out_dir = Path(args[args.index("--out") + 1]) if "--out" in args else None
    if round_arg(args) == "4":
        compose_r4(out_dir or OUT_R4)
    elif round_arg(args) == "3":
        compose_r3(out_dir or OUT_R3)
    elif round_arg(args) == "2":
        compose_r2(out_dir or OUT_R2)
    else:
        compose_main(out_dir or OUT)
else:
    blender_main()
