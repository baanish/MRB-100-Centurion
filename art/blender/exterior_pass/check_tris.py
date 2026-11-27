"""The pass's triangle check: exterior triangles per part (the part's own mesh and every mesh under it, LOD hulls,
colliders and blockout shapes left out) against baselines/budget.json's `after`, and the total against the owner's 260,000.
Fails past 3% over on the total. Read-only.
blender --background <blend> --python check_tris.py -- [<out.json>]"""
import json
import sys
from pathlib import Path

import bpy

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT.parent))
import damage_tree as T  # noqa: E402

TARGET, SLACK = 260_000, 0.03  # the owner, 2026-11-23 (docs/DECISIONS.md): two-sided skin as the stock, room behind the holes
budget = {r["part"]: r for r in json.loads((KIT / "baselines" / "budget.json").read_text())["parts"]}
parts = set(T.tree())


def helper(o):
    return ("_lod1" in o.name or "_colmesh" in o.name or o.name.endswith(("_blockout_mesh", "_shape"))
            or any(c.name in ("Colliders", "LOD1") for c in o.users_collection))


def owner(o):
    """The nearest part up the parent chain (a control surface's visible mesh hangs on its hinge, named like it)."""
    p = o
    while p is not None:
        base = p.name.replace("_visible", "")
        if base in parts:
            return base
        p = p.parent
    return None


per, loose = {}, {}
for o in bpy.data.objects:
    if o.type != "MESH" or helper(o) or o.hide_render:
        continue
    n = sum(len(p.vertices) - 2 for p in o.data.polygons)
    k = owner(o)
    if k is None:
        loose[o.name] = n
    else:
        per[k] = per.get(k, 0) + n
total = sum(per.values()) + sum(loose.values())
rows = {k: {"tris": per.get(k, 0), "budget_after": budget.get(k, {}).get("after")} for k in sorted(parts)}
report = {"blend": bpy.data.filepath, "total": total, "target": TARGET, "over_by": round(total / TARGET - 1, 4),
          "parts": rows, "not_under_a_part": loose}
print("TRIS total", total, "target", TARGET, "over by", f"{100 * (total / TARGET - 1):.1f}%", "loose", sum(loose.values()), flush=True)
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if args:
    Path(args[0]).resolve().write_text(json.dumps(report, indent=1))
if total > TARGET * (1 + SLACK):
    raise SystemExit(f"check_tris: {total} exterior triangles, over {TARGET:,} by more than 3%")
