"""The split ailerons' halves through their travel as the game drives them (ControlSurfaceJob_Math.cs:74-82): the hinge
turns by the roll deflection, then the half on the split's upper transform turns +splitAmount about the hinge line and
the half on its lower transform -splitAmount, splitAmount 0 to maxSplit (50) as the throttle leaves or reaches idle.
CenturionAuthor puts aileron_X_visible on the upper transform and aileron_X_visible_lower on the lower one. The spoiler
on the same side rises with it (SplitKind.Rise, 50, the same 40 deg/s servo) and turns 15 deg in roll on the side whose
aileron goes up (SurfaceRules). penetration() measures the deepest crossings at every sampled pose; gate() stops the
stage when the two halves pass through each other by more than fairing.PEN_M anywhere.
blender --background <stage blend> --python split_gate.py -- [out.json] [--gate]"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fairing as F  # noqa: E402
import sweep as SW  # noqa: E402

ROLLS = (-25, -15, 0, 15, 25)  # aileron trailing edge, degrees up
SPLITS = (0, 5, 10, 20, 30, 40, 50)  # each half, degrees apart from the shut pose
SPOILER_ROLL = 15


def _meshes(prefix):
    return [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(prefix) and not SW.helper(o)]


def halves(side, swap=False):
    """The meshes on the split's upper and lower transforms (swap: the other way round, to measure that assignment)."""
    O = bpy.data.objects
    pair = O[f"aileron_{side}_visible"], O[f"aileron_{side}_visible_lower"]
    return pair[::-1] if swap else pair


def poses(side, swap=False):
    """[(label, {object: matrix})] over the sampled roll and split angles for one side's aileron halves and spoiler."""
    O = bpy.data.objects
    hinge, sp = O[f"aileron_{side}"], O[f"spoiler_{side}"]
    upper, lower = halves(side, swap)
    up = SW.te_sign(hinge, [upper])
    sp_up = SW.te_sign(sp, [O[f"spoiler_{side}_visible"]])
    spoiler = _meshes(f"spoiler_{side}")
    out = []
    for r in ROLLS:
        for s in SPLITS:
            m = {upper.name: SW.turn(hinge, up * (r + s)), lower.name: SW.turn(hinge, up * (r - s))}
            t = SW.turn(sp, sp_up * ((SPOILER_ROLL * r / 25 if r > 0 else 0) + s))
            m.update({o.name: t for o in spoiler})
            out.append((f"roll {r:+d} split {s}", m))
    return out


def _pair(a, b, m):
    av, at, _ = F._tris(a, lambda o: m.get(o.name, Matrix.Identity(4)))
    bv, bt, _ = F._tris(b, lambda o: m.get(o.name, Matrix.Identity(4)))
    hits = F._crossings(av, at, bv, bt)
    if not hits:
        return None
    i, j, depth, _n = max(hits, key=lambda h: h[2])
    c = sum((av[x] for x in at[i]), Vector()) / 3
    return round(depth, 4), [round(x, 3) for x in c], len(hits)


def penetration(sides=("L", "R"), halves_only=False, swap=False):
    """{side: {pair: {pose: (depth m, a crossing point, crossing pairs)}}} for the pairs that cross."""
    O = bpy.data.objects
    out = {}
    for side in sides:
        upper, lower = ([h] for h in halves(side, swap))
        pairs = {"halves": (upper, lower)}
        if not halves_only:
            fixed = [O[n + side] for n in ("wing_outer_", "wing_tele1_") if n + side in O]
            pairs.update({"upper transform half / spoiler": (upper, _meshes(f"spoiler_{side}")),
                          "lower transform half / spoiler": (lower, _meshes(f"spoiler_{side}")),
                          "upper transform half / fixed wing": (upper, fixed),
                          "lower transform half / fixed wing": (lower, fixed)})
        res = {}
        for label, m in poses(side, swap):
            for k, (a, b) in pairs.items():
                hit = _pair(a, b, m)
                if hit:
                    res.setdefault(k, {})[label] = hit
        out[side] = res
    return out


def gate():
    """penetration() of the halves alone, stopping the stage when they cross by more than fairing.PEN_M."""
    res = penetration(halves_only=True)
    bad = {s: {p: v[0] for p, v in r.get("halves", {}).items()} for s, r in res.items() if r.get("halves")}
    if bad:
        raise SystemExit(f"split_gate: the aileron halves pass through each other (m): {bad}")
    return {"poses_per_side": len(ROLLS) * len(SPLITS), "limit_m": F.PEN_M, "crossing": 0}


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--gate" in args:  # Run-Pass, on the last geometry stage: the halves with the structure stage 2 joined into them
        print("SPLIT halves clear", gate(), flush=True)
        sys.exit(0)
    if "--extended" in args:
        import render_rig as L
        L.set_extension(1.0)
    swap = "--swap" in args
    res = penetration(swap=swap)
    for side, r in res.items():
        for k, v in r.items():
            worst = max(v.items(), key=lambda kv: kv[1][0])
            print(f"SPLIT{' swapped' if swap else ''} {side} {k}: {len(v)} of {len(ROLLS) * len(SPLITS)} poses cross, deepest {worst[1][0]} m "
                  f"at {worst[0]} near {worst[1][1]}", flush=True)
        if not r:
            print(f"SPLIT{' swapped' if swap else ''} {side}: nothing crosses", flush=True)
    outs = [a for a in args if a.endswith(".json")]
    if outs:
        Path(outs[0]).write_text(json.dumps(res, indent=1))
