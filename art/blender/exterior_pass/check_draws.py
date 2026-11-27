"""The pass's draw check (FRAMES.md section 9): per LOD, draw calls per pass (a renderer's used material slots, one draw
each), material slots on the parts, triangles, for the built exterior plus the prefab's other renderers this blend does
not hold (the cockpit's interior, the pilots and the like, from the prefab's audit, baselines/draw_centurion.json).
Fails when the aircraft at full detail draws more than the Darkreach's 123 calls a pass, or a damage part draws more
than two slots besides glass and lights. Read-only.
blender --background <blend> --python check_draws.py -- [<out.json>]"""
import json
import sys
from pathlib import Path

import bpy

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT.parent))
import damage_tree as T  # noqa: E402

DARKREACH = {"draws": 123, "lod1_tris": 7862}
TODAY = 214  # today's prefab at full detail (draw_centurion.json); FRAMES.md section 10: the Darkreach's count is a ceiling to
# stay under where it costs nothing, not a goal to atlas toward (equal cost on screen); the gate is today's count
APART = ("glass", "light_", "laser_lens")  # the laser's lens is glazing too, its own opaque slot as Unity authors it
parts = set(T.tree())


def helper(o):
    return "_colmesh" in o.name or o.name.endswith(("_blockout_mesh", "_shape")) or any(c.name == "Colliders" for c in o.users_collection)


def used_slots(o):
    return sorted({o.data.materials[p.material_index].name if o.data.materials and o.data.materials[p.material_index] else "" for p in o.data.polygons})


lod0, lod1 = {}, {}
for o in bpy.data.objects:
    if o.type != "MESH" or helper(o) or not o.data.polygons:
        continue
    row = {"slots": used_slots(o), "tris": sum(len(p.vertices) - 2 for p in o.data.polygons)}
    if "_lod1" in o.name or any(c.name == "LOD1" for c in o.users_collection):
        lod1[o.name] = row
    elif not o.hide_render:
        lod0[o.name] = row
names = set(bpy.data.objects.keys())
audit = json.loads((KIT / "baselines" / "draw_centurion.json").read_text())
others = [r for r in audit if r.get("lod") == 0 and r.get("drawn") and r["kind"] in ("MeshRenderer", "SkinnedMeshRenderer")
          and not ({r["name"], r["name"].replace("_visible", ""), r["name"].removesuffix("_mesh"), r["name"].removesuffix("_mesh") + "_visible"} & names)]
other_draws = sum(len(r["materials"]) for r in others)
other_tris = sum(r.get("tris") or 0 for r in others)
draws0 = sum(len(r["slots"]) for r in lod0.values())
part_slots = {n: [s for s in r["slots"] if not s.startswith(APART)] for n, r in lod0.items() if n.replace("_visible", "") in parts}
over = {n: s for n, s in part_slots.items() if len(s) > 2}
report = {
    "lod0": {"draws_exterior": draws0, "draws_other_prefab": other_draws, "draws_total": draws0 + other_draws, "budget": TODAY, "darkreach": DARKREACH["draws"],
             "draws_without_glass_and_lights": draws0 + other_draws - sum(1 for r in lod0.values() for s in r["slots"] if s.startswith(APART)),
             "renderers": len(lod0), "max_slots_on_a_part": max((len(s) for s in part_slots.values()), default=0),
             "parts_over_two_slots": over, "materials": sorted({s for r in lod0.values() for s in r["slots"]}),
             "tris_exterior": sum(r["tris"] for r in lod0.values()), "tris_other_prefab": other_tris},
    "lod1": {"draws": sum(len(r["slots"]) for r in lod1.values()), "renderers": len(lod1), "tris": sum(r["tris"] for r in lod1.values()),
             "materials": sorted({s for r in lod1.values() for s in r["slots"]}), "darkreach_tris": DARKREACH["lod1_tris"]},
    "other_prefab_renderers": sorted({r["name"] for r in others}),
    "heaviest_lod0": sorted(((len(r["slots"]), n, r["slots"]) for n, r in lod0.items()), reverse=True)[:12],
}
l0 = report["lod0"]
print("DRAWS lod0", l0["draws_total"], f"({l0['draws_exterior']} exterior + {l0['draws_other_prefab']} other) of", DARKREACH["draws"],
      "| max slots on a part", l0["max_slots_on_a_part"], "| lod1", report["lod1"]["draws"], "draws,", report["lod1"]["tris"], "tris", flush=True)
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args:
    Path(args[0]).resolve().write_text(json.dumps(report, indent=1))
fails = []
if l0["draws_total"] > TODAY:
    fails.append(f"{l0['draws_total']} draw calls a pass at full detail, over today's {TODAY}")
if over:
    fails.append(f"parts over two slots: {over}")
if l0["draws_total"] > DARKREACH["draws"]:
    print(f"DRAWS WARN: {l0['draws_total']} calls a pass at full detail, over the Darkreach's {DARKREACH['draws']} (a ceiling to aim at, not a gate)", flush=True)
if fails:
    raise SystemExit("check_draws: " + "; ".join(fails))
