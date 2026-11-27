"""The walk-around's game side: walkaround_plan.py's views (its first tier by default) as NO-Agentic scenarios, one run a
pose, each view a free-camera screenshot from the plan's eye toward its target, named as walkaround_render.py names
the render, so the blind check pairs them. Writes <out>/walk_<pose>.scenario.jsonc and <out>/manifest.json
({run, scenario, frame, part, group, pose, view, set, note}).

The aircraft is the runway mission's (tests/agentic/centurion_agrapol_runway.mission.json): parked at x -406.01,
z -27684.76, heading 323.5, the root 4.50 m above the runway (CenturionAuthor's report). A Blender point maps into its
frame as Unity (-x, z - ROOT_Z, -y - ROOT_Y) (the authoring's report of the main gear hinge: Blender (3.49, 3.025, 2.1)
is Unity (-3.49, -1.85, -4.50)), then the parking's heading and place. Free-camera points are fixed on the ground, so
the aircraft must sit where the mission parks it: the parked runs hold the engines off (Debug.Ignition), since idle
thrust alone taxied the unbraked aircraft 870 m down the runway in build 41's walk_04, and every parked frame first
requires the aircraft within PARK_TOL of its parking.

Each free-camera frame's manifest row carries on_screen: the share of the part's exported box (blockout.json bounds,
at rest) that projects inside the frame through the camera the step asks for (FOV_V, the runner's external field of
view, on its 16:9 screen); a frame under ON_SCREEN_MIN is listed by the generator as off screen.

A view whose pose the game cannot set, or (with --frames) whose camera another part blocks, is left out of the runs and
listed in the manifest's left_out with why: the renders carry it. Views from under the belly fly at dawn (DAWN_HOUR, a
copy of the mission), where a low sun reaches the underside. How each pose is set:
- gear down: parked. gear up: airborne at 1,500 m with the gear up; the camera then rides with the aircraft
  ("attached"), aimed at its root from the plan's direction and distance, not at the part.
- wing: Debug.SpanCommand 0 or 1. roll: Debug.RollCommand -1 or 1 (left, right). pitch: Debug.PitchCommand -1 (nose
  up); nose down cannot be set on the ground (the fly-by-wire holds the nose wheel down), noted.
- split: the clamshell opens at idle (exterior_pass README): Debug.ThrottleCommand 0 for open, 0.3 for shut.
- flaps: no scenario control; the runway spawn selects take-off flaps. bay: no scenario control. Both noted.
- faction: the mission's Primeva aircraft wears its faction's livery (PALA); BDF views are noted as not set.

python -I walkaround_scenarios.py [--plan .cache/art/walkaround/plan.json] [--tier 1] [--out .cache/refresh/art2/walkaround]
    [--build <repo with build/>] [--frames <walkaround_render's frames.json>, its eyes cleared of geometry]
python -I walkaround_scenarios.py --out <the same folder> --check <the flown runs' folder>: each frame's mean luminance"""
import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PARK = {"x": -406.01, "z": -27684.76, "hdg": 323.5, "alt": 142.23}
ROOT_Z, ROOT_Y = 3.95, 1.475  # Blender z and y of the Unity root's origin (see the docstring)
AIR_ALT = 1500.0
PARK_TOL = 0.5
# The game's free camera stays 1.7 m over the statics under it (CameraFreeState.cs:102); the runway under the parked
# aircraft is at 138.28 m (build 41's walk_05: a camera asked for 139.34 m was taken at 139.98)
CAMERA_FLOOR_ALT = 138.28 + 1.7
HULL_CLEAR = 1.5
PARTS = {}  # blockout.json's parts, read by main
FOV_V, ASPECT, ON_SCREEN_MIN = 90.0, 16 / 9, 0.25  # the runner's prefs: DefaultExternalFoV 90.4, screen 2560x1440


def frame_name(v):
    p = "_".join(f"{k}-{v['pose'][k]}" for k in sorted(v["pose"])) or "rest"
    return f"{v['group']}__{v['part']}__{p}__{v['view']}"


def to_world(b):
    """A Blender point at rest to the parked aircraft's game world (x, y up, z)."""
    u = (-b[0], b[2] - ROOT_Z, -b[1] - ROOT_Y)
    h = math.radians(PARK["hdg"])
    x = u[0] * math.cos(h) + u[2] * math.sin(h)
    z = -u[0] * math.sin(h) + u[2] * math.cos(h)
    return PARK["x"] + x, PARK["alt"] + u[1], PARK["z"] + z


def aim(eye, target):
    dx, dy, dz = (t - e for t, e in zip(target, eye))
    return (math.degrees(math.atan2(dx, dz)) % 360, math.degrees(math.atan2(dy, math.hypot(dx, dz))))


def part_corners(part, n=5):
    """An n x n x n grid through a part's exported box (blockout.json, at rest) in the parked aircraft's game world."""
    u0, u1 = part["bounds_unity"]
    ax = part["axes_unity"]
    out = []
    steps = [k / (n - 1) for k in range(n)]
    for c in ((u0[0] + a * (u1[0] - u0[0]), u0[1] + b * (u1[1] - u0[1]), u0[2] + d * (u1[2] - u0[2])) for a in steps for b in steps for d in steps):
        u = [part["pivot_unity"][i] + c[0] * ax["right"][i] + c[1] * ax["up"][i] + c[2] * ax["forward"][i] for i in range(3)]
        out.append(to_world((-u[0], -u[2], u[1])))  # Unity (-x, z, -y) of Blender, back to Blender
    return out


def hull_clearance(p):
    """How far a point in the Unity root's frame stands from the nearest exported part box (each box made axis-aligned
    round its corners; 0 inside one). The gear's boxes are its rest pose, down; the runs that use this fly gear up."""
    near = 1e9
    for name, part in PARTS.items():
        if "bounds_unity" not in part or name.startswith(("gear_", "wheel_", "geardoor_")):
            continue
        u0, u1 = part["bounds_unity"]
        ax = part["axes_unity"]
        pts = [[part["pivot_unity"][i] + c[0] * ax["right"][i] + c[1] * ax["up"][i] + c[2] * ax["forward"][i] for i in range(3)]
               for c in ((x, y, z) for x in (u0[0], u1[0]) for y in (u0[1], u1[1]) for z in (u0[2], u1[2]))]
        # pivot_unity is Unity (-x, z, -y) of the Blender point, so the root, Blender (0, -ROOT_Y, ROOT_Z), is (0, ROOT_Z, ROOT_Y)
        root = (0, ROOT_Z, ROOT_Y)
        gap = [max(min(q[i] for q in pts) - root[i] - p[i], p[i] - (max(q[i] for q in pts) - root[i]), 0.0) for i in range(3)]
        near = min(near, math.sqrt(sum(g * g for g in gap)))
    return near


def on_screen(eye, hdg, pitch, points):
    """The share of the box's grid points in front of the camera and inside the frame."""
    h, p = math.radians(hdg), math.radians(pitch)
    fwd = (math.sin(h) * math.cos(p), math.sin(p), math.cos(h) * math.cos(p))
    right = (math.cos(h), 0.0, -math.sin(h))
    up = (fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2], fwd[0] * right[1] - fwd[1] * right[0])
    ty = math.tan(math.radians(FOV_V) / 2)
    tx = ty * ASPECT
    seen = 0
    for c in points:
        d = [c[i] - eye[i] for i in range(3)]
        z = sum(a * b for a, b in zip(d, fwd))
        if z > 0.05 and abs(sum(a * b for a, b in zip(d, right)) / z) <= tx and abs(sum(a * b for a, b in zip(d, up)) / z) <= ty:
            seen += 1
    return seen / len(points)


def setup(pose):
    """The steps that set a pose, whether the game can set it, and a note when it cannot."""
    steps, notes = [], []

    def cmd(key, value, label):
        steps.append({"config": {"guid": "baanish.centurion", "section": "Debug", "key": key, "value": str(value)}})
        steps.append({"wait": {"path": "own.alive", "eq": True}, "timeout": 8, "hold": 4, "label": label})
    if pose.get("wing"):
        span = 1 if pose["wing"] == "extended" else 0
        cmd("SpanCommand", span, f"wing {pose['wing']}")
        # the stages take about 9 s end to end: build 45's left wing was shot at 0.86, its markings still in the root
        steps.append({"wait": {"path": "mods.baanish.centurion.span_frac", "near": span, "tol": 0.01}, "timeout": 30,
                      "label": f"wing {pose['wing']} fully"})
    if pose.get("roll") in ("left", "right"):
        cmd("RollCommand", -1 if pose["roll"] == "left" else 1, f"roll {pose['roll']}")
    if pose.get("pitch") == "up":
        cmd("PitchCommand", -1, "nose-up pitch")
    elif pose.get("pitch") == "down":
        notes.append("nose-down pitch cannot be set on the ground")
    if pose.get("split"):
        cmd("ThrottleCommand", 0 if pose["split"] == "open" else 0.3, f"split {pose['split']} by throttle")
    if pose.get("flaps") not in (None,):
        notes.append(f"flaps {pose['flaps']}: no scenario control, the runway spawn's take-off flaps")
    if pose.get("bay"):
        notes.append(f"bay {pose['bay']}: no scenario control")
    if pose.get("faction") == "BDF":
        notes.append("BDF livery: the mission's aircraft is Primeva's (PALA)")
    return steps, notes


RELEASE = [{"config": {"guid": "baanish.centurion", "section": "Debug", "key": k, "value": v}}
           for k, v in (("RollCommand", "-999"), ("PitchCommand", "-999"), ("ThrottleCommand", "-999"), ("SpanCommand", "0"))]
PER_RUN = 13  # parked views a run: its poses set one after another


DAWN_HOUR = 7.0  # the belly views' runs: at noon the parked aircraft's underside sits in its own shadow (build 39's runs)
DARK = 0.08  # a frame whose mean luminance is under this is flagged by --check


# Views that stay in shadow in the game whatever the hour the runs fly (mean luminance under DARK in build 41's runs:
# the inner struts under the wing at noon; the main legs and their doors in the wing roots' shadow at dawn): the
# renders carry them.
SHADED = {"wings__strut_inner_L__wing-retracted__above", "wings__strut_inner_R__wing-retracted__above",
          "gear__gear_LM__gear-down__below", "gear__gear_RM__gear-down__below",
          "gear__geardoor_LM_visible__gear-down__front", "gear__geardoor_RM_visible__gear-down__front"}


def is_belly(v):
    return v["eye"][2] < 2.0  # an eye under the fuselage's lowest skin, parked


def scenario(run, blocks, build, mission):
    """One run: blocks of (pose, views), each pose set after the last one's commands are released."""
    up = blocks[0][0].get("gear") == "up"
    steps = [
        {"require": {"all": [{"path": "own.alive", "eq": True}, {"path": "own.type", "eq": "baanish_centurion"}]}, "label": "in the Centurion"},
        {"wait": {"path": "own.alive", "eq": True}, "timeout": 45, "hold": 40, "label": "the player-joined notice clears"},
    ]
    if up:
        # the takeoff mode raises the gear itself (an act gear=up after it was refused: "already up"): wait for it
        steps += [{"fly": {"mode": "takeoff", "alt_msl_m": AIR_ALT, "hdg_deg": PARK["hdg"], "throttle": 1}},
                  {"wait": {"path": "own.alt_agl_m", "gt": 300}, "timeout": 240, "label": "airborne"},
                  {"wait": {"path": "own.gear", "eq": "up"}, "timeout": 90, "label": "gear up"},
                  {"fly": {"mode": "hold", "alt_msl_m": AIR_ALT, "hdg_deg": PARK["hdg"], "throttle": 0.8}},
                  {"wait": {"path": "fly.alt_err_m", "between": [-30, 30]}, "timeout": 180, "hold": 5, "label": "level"}]
    rows = []
    for pose, views in blocks:
        pre, notes = setup(pose)
        steps += RELEASE + [{"wait": {"path": "own.alive", "eq": True}, "timeout": 8, "hold": 3, "label": "commands released"}] + pre
        rows += shots(run, views, notes, up, steps)
    steps.append({"camera": {"mode": "game"}})
    steps.append({"record": {"path": "own.hp_frac"}, "label": "undamaged through the run"})
    doc = {
        "mission": str(Path(mission).as_posix()),
        "mods": "clean",
        "measure": True,
        "plugins": ["installed:com.nikkorap.blueprinter", str((build / "build" / "dotnet").as_posix()),
                    f"content:{(build / 'build' / 'centurion_0.2.0.nobp').as_posix()} host=com.nikkorap.blueprinter keys=baanish_centurion"],
        "config": {"baanish.centurion": {"Diagnostics": {"Enabled": True},
                                         "Debug": {"SpanCommand": 0} if up else {"SpanCommand": 0, "Ignition": "off"}}},
        "timeout": 900 if up else 600,
        "steps": steps,
    }
    return doc, rows


def shots(run, views, notes, up, steps):
    rows = []
    for v in views:
        name = frame_name(v)
        if up:
            eye_u = (-v["eye"][0], v["eye"][2] - ROOT_Z, -v["eye"][1] - ROOT_Y)
            dist = math.dist(eye_u, (0, 0, 0))
            # attached: where the camera sits, clockwise from the nose and above the wing plane (WRITING-SCENARIOS.md).
            # It aims at the root, not the part, so it backs out along the plan's direction until half the part is in
            # frame (checked on the parked aircraft, a rigid move of the flying one).
            a_hdg = math.degrees(math.atan2(eye_u[0], eye_u[2])) % 360
            a_pitch = math.degrees(math.asin(eye_u[1] / dist)) if dist else 0.0
            # and it stands HULL_CLEAR off every part box, or the near plane cuts the hull (build 41: the nose sliced
            # open from 0.03 m ahead of the cockpit's box and 0.25 m under the radome's)
            for reach in [max(dist, 4.0) + 0.5 * k for k in range(80)]:
                s = reach / max(dist, 1e-6)
                if hull_clearance([c * s for c in eye_u]) < HULL_CLEAR:
                    continue
                eye = to_world((-eye_u[0] * s, -eye_u[2] * s - ROOT_Y, eye_u[1] * s + ROOT_Z))
                hdg, pitch = aim(eye, to_world((0.0, -ROOT_Y, ROOT_Z)))
                if v["part"] not in PARTS or on_screen(eye, hdg, pitch, part_corners(PARTS[v["part"]])) >= 0.5:
                    break
            steps.append({"camera": {"mode": "attached", "target": "own", "distance_m": round(reach, 2),
                                     "hdg_deg": round(a_hdg, 1), "pitch_deg": round(a_pitch, 1)}})
        else:
            eye, tgt = to_world(v["eye"]), to_world(v["target"])
            hdg, pitch = aim(eye, tgt)
            steps.append({"camera": {"mode": "free", "x": round(eye[0], 2), "z": round(eye[2], 2), "alt_msl_m": round(eye[1], 2),
                                     "hdg_deg": round(hdg, 1), "pitch_deg": round(pitch, 1)}})
        steps.append({"wait": {"path": "own.alive", "eq": True}, "timeout": 6, "hold": 2, "label": name})
        if not up and eye[1] < CAMERA_FLOOR_ALT:
            raise SystemExit(f"{name}: the eye stands at {eye[1]:.2f} m, under the game's free camera floor {CAMERA_FLOOR_ALT} m "
                             "(CameraFreeState.cs:102), which would lift it; render with walkaround_render.py's floor")
        if not up:
            steps.append({"require": {"all": [{"path": "own.pos.x", "near": PARK["x"], "tol": PARK_TOL},
                                              {"path": "own.pos.z", "near": PARK["z"], "tol": PARK_TOL}]},
                          "label": f"parked where the cameras stand: {name}"})
        steps.append({"screenshot": {"name": name}})
        row = {"run": run, "frame": name, "part": v["part"], "group": v["group"], "pose": v["pose"], "view": v["view"],
               "set": not notes, "note": "; ".join(notes + (["gear up: camera rides the aircraft, aimed at its root"] if up else []))}
        if v["part"] in PARTS:
            row["on_screen"] = round(on_screen(eye, hdg, pitch, part_corners(PARTS[v["part"]])), 3)
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=str(REPO / ".cache" / "art" / "walkaround" / "plan.json"))
    ap.add_argument("--tier", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--build", default=str(REPO))
    ap.add_argument("--frames", help="walkaround_render.py's frames.json: its eyes, cleared of geometry, replace the plan's")
    ap.add_argument("--check", help="a folder of flown runs: each manifest frame's screenshot's mean luminance, dark ones flagged")
    a = ap.parse_args()
    out = Path(a.out)
    if a.check:
        return check(out, Path(a.check))
    PARTS.update(json.loads((REPO / "art" / "export" / "blockout.json").read_text())["parts"])
    views = [v for v in json.loads(Path(a.plan).read_text()) if v["tier"] <= a.tier]
    left_out = []
    if a.frames:  # the renderer's eyes, cleared of geometry; a view that sees too little of its part stays out
        frames = {f["frame"]: f for f in json.loads(Path(a.frames).read_text())}
        kept = []
        for v in views:
            f = frames.get(frame_name(v), {})
            if f.get("blocked"):
                left_out.append({"frame": frame_name(v), "why": f"the camera sees {f.get('seen', 0):.0%} of the part"
                                 + (f", {f['in_the_way']} in the way" if f.get("in_the_way") else ", none of it facing the camera")})
                continue
            kept.append(dict(v, eye=f.get("eye_used", v["eye"])))
        views = kept
    settable = []
    for v in views:  # a pose the game cannot set would fly a copy of another frame: the renders alone carry it
        notes = setup(v["pose"])[1] + (["in shadow in the game at noon and at dawn (build 41's runs)"] if frame_name(v) in SHADED else [])
        (settable.append(v) if not notes else left_out.append({"frame": frame_name(v), "why": "; ".join(notes)}))
    views = settable
    out.mkdir(parents=True, exist_ok=True)
    mission = json.loads((REPO / "tests" / "agentic" / "centurion_agrapol_runway.mission.json").read_text())
    mission["environment"]["timeOfDay"] = DAWN_HOUR
    dawn = out / "centurion_agrapol_runway_dawn.mission.json"
    dawn.write_text(json.dumps(mission, indent=2))
    noon = REPO / "tests" / "agentic" / "centurion_agrapol_runway.mission.json"
    runs = {}
    for v in views:  # parked or airborne by the gear axis, belly views at dawn; the rest set on the same run
        light = "air" if v["pose"].get("gear") == "up" else ("dawn" if is_belly(v) else "noon")
        runs.setdefault((light, json.dumps(v["pose"], sort_keys=True)), []).append(v)
    groups, cur = [], {}
    for (light, key), vs in sorted(runs.items()):
        pose = json.loads(key)
        if light == "air":
            groups.append(("air", [(pose, vs)]))
            continue
        cur.setdefault(light, []).append((pose, vs))
        if sum(len(b[1]) for b in cur[light]) >= PER_RUN:
            groups.append((light, cur.pop(light)))
    groups += [(light, blocks) for light, blocks in sorted(cur.items())]
    manifest = []
    for i, (light, blocks) in enumerate(groups, 1):
        run = f"walk_{i:02d}" + {"air": "_gear_up", "dawn": "_dawn", "noon": ""}[light]
        doc, rows = scenario(run, blocks, Path(a.build), dawn if light == "dawn" else noon)
        path = out / f"{run}.scenario.jsonc"
        path.write_text("// The walk-around's first tier in the game: written by exterior_pass/walkaround_scenarios.py\n" + json.dumps(doc, indent=1))
        for r in rows:
            r["scenario"] = path.name
        manifest += rows
    off = [r["frame"] for r in manifest if r.get("on_screen", 1.0) < ON_SCREEN_MIN]
    (out / "manifest.json").write_text(json.dumps({"frames": manifest, "left_out": left_out, "off_screen": off}, indent=1))
    print("WALKAROUND scenarios", len(groups), "runs,", len(manifest), "frames flown,", len(left_out), "left to the renders, to", out)
    print("WALKAROUND", len(off), "frames with under", ON_SCREEN_MIN, "of their part on screen")
    for r in manifest:
        if r["frame"] in off:
            print("  ", r["frame"], r["on_screen"])


def check(out, runs_dir):
    """Each manifest frame's screenshot under runs_dir (the runs' folders), its mean luminance; dark ones flagged."""
    from PIL import Image
    import numpy as np
    man = json.loads((out / "manifest.json").read_text())
    shots = {p.stem: p for p in runs_dir.rglob("*.png")}
    dark, missing = [], []
    for r in man["frames"]:
        p = next((shots[k] for k in shots if k.endswith(r["frame"]) or k.startswith(r["frame"])), None)
        if p is None:
            missing.append(r["frame"])
            continue
        lum = float((np.asarray(Image.open(p).convert("L"), np.float32) / 255).mean())
        r["luminance"] = round(lum, 3)
        r["dark"] = lum < DARK
        dark += [r["frame"]] if r["dark"] else []
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    print("WALKAROUND check", len(man["frames"]), "frames,", len(dark), "dark (under", DARK, "),", len(missing), "missing", flush=True)
    for f in dark + missing:
        print("WALKAROUND   ", "dark" if f in dark else "missing", f, flush=True)


if __name__ == "__main__":
    main()
