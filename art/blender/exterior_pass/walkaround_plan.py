"""The walk-around gate's camera list: every exported part, in every pose that moves or repaints it, seen from four
sides at its own height, from above and from below, 3 to 6 m off. Built from the export's own part list
(art/export/blockout.json), so a part added later is in the sweep without anyone listing it. Writes the plan the
Blender renders and the game scenario are both made from, and prints how many images it makes.

A view: {part, pose, view, eye, target} in Blender world metres with the aircraft at rest (pose names say what to set).
python -I walkaround_plan.py [--export art/export] [--out .cache/art/walkaround/plan.json]"""
import argparse
import itertools
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# Pose axes, and the parts each one moves or repaints (by name prefix). A part's poses are the product of its axes.
AXES = {
    "gear": (("up", "down"), ("gear_", "wheel_", "geardoor_", "nose_door", "nose_hatch", "sponson_", "fuselage_F", "cockpit")),
    "flaps": (("0", "15", "30"), ("flap_", "wing_root_")),
    "roll": (("neutral", "left", "right"), ("aileron_", "spoiler_", "wing_outer_")),
    "split": (("shut", "open"), ("aileron_",)),
    "pitch": (("neutral", "up", "down"), ("ruddervator_", "vtail_", "tail_end", "tailcone")),
    "wing": (("retracted", "extended"), ("wing_tele", "wing_outer_", "wing_root_", "aileron_", "spoiler_", "strut_")),
    "bay": (("shut", "open"), ("baydoor_", "bay_")),
    # paint that differs by faction: the roundels' surfaces (faction_marks: wings and V-tail)
    "faction": (("BDF", "PALA"), ("wing_", "vtail_")),
}
VIEWS = ("front", "back", "left", "right", "above", "below")
DIST_MIN, DIST_MAX = 3.0, 6.0
# The first tier, for a person in one sitting: each part, both sides' twins (the owner's clipped right wing roundel was
# a one-side fault), once per pose of its own (OWN), from its most revealing side; one sheet per group.
GROUPS = (("engines", ("fan_", "nacelle_", "nozzle_", "pylon_")), ("gear", ("gear_", "wheel_", "geardoor_", "nose_door", "nose_hatch")),
          ("wings", ("wing_", "strut_", "sponson_")), ("surfaces", ("aileron_", "spoiler_", "flap_")),
          ("tail", ("vtail_", "ruddervator_", "tail_end", "tailcone")), ("bays", ("bay_", "baydoor_")))
BELOW_FIRST = ("gear_", "wheel_", "geardoor_", "nose_door", "nose_hatch", "bay_", "baydoor_", "sponson_")
# The axes that move or repaint a part itself; in the first tier a neighbour's axis stays at its first value
OWN = {"gear": ("gear_", "wheel_", "geardoor_", "nose_door", "nose_hatch"), "flaps": ("flap_",), "roll": ("aileron_", "spoiler_"),
       "split": ("aileron_",), "pitch": ("ruddervator_",), "wing": ("wing_tele", "wing_outer_"), "bay": ("baydoor_",),
       "faction": ("wing_", "vtail_")}


# Every moving surface from above and from below at each step of its own travel (the owner's eye found a fairing passing
# up through its flap at 30 degrees, between the poses above): degrees a step, and the parts each travel moves.
TRAVEL = {"flap_deg": (range(0, 31, 5), ("flap_",)), "roll_deg": (range(-25, 26, 5), ("aileron_", "spoiler_")),
          "split_deg": (range(0, 51, 10), ("aileron_",)), "pitch_deg": (range(-40, 41, 10), ("ruddervator_",))}
# Every fitting square on (the camera on its normal: the owner's skewed panel read as a rhombus only face on): the
# renderer adds, per part, one view along each of its skin's normal clusters (area-weighted, 15 degrees apart) at 3 m;
# the part list here carries no normals, so those views are counted where they are made, not in this plan.


def travel_views(name, centre, size):
    out = []
    for key, (steps, prefixes) in TRAVEL.items():
        if name.startswith(prefixes):
            v = views(centre, size)
            for deg in steps:
                for side in ("above", "below"):
                    out.append(({key: deg}, side, v[side]))
    return out


def own_pose(name, pose):
    return all(v == AXES[k][0][0] or name.startswith(OWN[k]) for k, v in pose.items())


def group_of(name):
    return next((g for g, prefixes in GROUPS if name.startswith(prefixes)), "fuselage")


def best_view(name, centre, size):
    """Along the part's thinnest axis, from the side a person looks at it from."""
    if name.startswith("fan_"):
        return "front"
    if name.startswith("nozzle_"):
        return "back"
    axis = min(range(3), key=lambda i: size[i])
    if axis == 0:
        return "left" if centre[0] >= 0 else "right"  # outboard: Blender +x is the left side
    if axis == 1:
        return "front"
    return "below" if name.startswith(BELOW_FIRST) else "above"


def parts(export):
    """Every exported mesh part (an FBX of its own): name -> (world centre, size), from blockout.json."""
    b = json.loads((export / "blockout.json").read_text())["parts"]
    out = {}
    for name, p in b.items():
        if not p.get("fbx"):
            continue
        piv = json.loads(p["pivot_blender"]) if isinstance(p["pivot_blender"], str) else p["pivot_blender"]
        lo, hi = json.loads(p["bounds_blender"]) if isinstance(p["bounds_blender"], str) else p["bounds_blender"]
        centre = [piv[i] + (lo[i] + hi[i]) / 2 for i in range(3)]
        out[name] = (centre, [hi[i] - lo[i] for i in range(3)])
    return out


def poses(name):
    axes = [(k, vals) for k, (vals, prefixes) in AXES.items() if name.startswith(prefixes)]
    if not axes:
        return [{}]
    return [dict(zip((k for k, _ in axes), combo)) for combo in itertools.product(*(v for _, v in axes))]


def views(centre, size):
    """Blender world: x left, y aft, z up (the aircraft faces -y)."""
    d = min(DIST_MAX, max(DIST_MIN, 0.6 * max(size)))
    c = centre
    eye = {"front": (c[0], c[1] - d, c[2]), "back": (c[0], c[1] + d, c[2]), "left": (c[0] + d, c[1], c[2]),
           "right": (c[0] - d, c[1], c[2]), "above": (c[0], c[1] + 0.3 * d, c[2] + d), "below": (c[0], c[1] + 0.3 * d, c[2] - d)}
    return {v: (eye[v], tuple(c)) for v in VIEWS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", type=Path, default=REPO / "art" / "export")
    ap.add_argument("--out", type=Path, default=REPO / ".cache" / "art" / "walkaround" / "plan.json")
    a = ap.parse_args()
    plan, per_part = [], {}
    all_parts = parts(a.export)
    for name, (centre, size) in sorted(all_parts.items()):
        ps = poses(name)
        first = best_view(name, centre, size)
        for pose in ps:
            for view, (eye, target) in views(centre, size).items():
                plan.append({"part": name, "group": group_of(name), "pose": pose, "view": view, "tier": 1 if view == first and own_pose(name, pose) else 2,
                             "eye": [round(x, 3) for x in eye], "target": [round(x, 3) for x in target]})
        for pose, view, (eye, target) in travel_views(name, centre, size):
            plan.append({"part": name, "group": group_of(name), "pose": pose, "view": view, "tier": 2,
                         "eye": [round(x, 3) for x in eye], "target": [round(x, 3) for x in target]})
        per_part[name] = len(ps) * len(VIEWS) + len(travel_views(name, centre, size))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(plan, indent=0))
    distinct = {json.dumps(v["pose"], sort_keys=True) for v in plan}
    print(f"WALKAROUND {len(per_part)} parts, {len(distinct)} distinct poses, {len(plan)} views "
          f"({len(plan)} renders and {len(plan)} game captures); most for one part: "
          f"{max(per_part, key=per_part.get)} {max(per_part.values())}")
    tier1 = [v for v in plan if v["tier"] == 1]
    sheets = {}
    for v in tier1:
        sheets[v["group"]] = sheets.get(v["group"], 0) + 1
    print(f"WALKAROUND first tier: {len(tier1)} views on {len(sheets)} sheets {dict(sorted(sheets.items()))}")
    print(f"WALKAROUND plan written to {a.out}")


if __name__ == "__main__":
    main()
