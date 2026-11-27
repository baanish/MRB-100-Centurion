"""Teeth hanging into the windscreen opening (small roof and brace edges, 0.1.3's, left by the
trimming, silhouetted against the opening): from each seat's eye, rays every 0.5 deg over the windscreen (pan -70 to
70, tilt 40 up to 5 down); a flight deck face met first, over z 4.95 and forward of station 6.2, whose neighbours 1 deg
either side (across, or up and down) both see out through glass or into the open, is a tooth (narrower than 2 deg; the
brace and pillars are 3 deg and wider). --apply takes them away and saves; the build step after flightdeck_seeinto.py's.
blender -b --factory-startup --python flightdeck_teeth.py -- <export.blend> <blockout.blend> [--apply]"""
import sys
from collections import Counter

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import flightdeck_seeinto as seeinto  # noqa: E402

GLASS = seeinto.GLASS


def first(tree, owner, ref, e, d):
    """('open', None) out or through glass to the open; ('face', (object, polygon, point)) at the first drawn face."""
    o = e
    while True:
        h = tree.ray_cast(o, d, 40.0)
        if h[0] is None:
            return "open", None
        if owner[h[2]] not in GLASS and h[1].dot(d) < 0:
            return "face", (ref[h[2]][0], ref[h[2]][1], h[0])
        o = h[0] + d * 0.0002


def teeth(tree, owner, ref, eyes):
    found = Counter()
    for e in eyes:
        grid = {}
        for i in range(281):
            for j in range(91):
                pan, tilt = -70 + 0.5 * i, -40 + 0.5 * j
                grid[(pan, tilt)] = first(tree, owner, ref, e, seeinto.direction(pan, tilt))
        for (pan, tilt), (kind, hit) in grid.items():
            if kind != "face" or hit[0] != "flightdeck_int" or hit[2].z < 4.95 or hit[2].y > 6.2 - 22.475:
                continue

            def open_(a, b):
                g = grid.get((a, b))
                return g is not None and g[0] == "open"
            if (open_(pan - 1, tilt) and open_(pan + 1, tilt)) or (open_(pan, tilt - 1) and open_(pan, tilt + 1)):
                found[hit[1]] += 1
    return found


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:]
    bpy.ops.wm.open_mainfile(filepath=argv[0])
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    EYE_P = Vector((0.55, 6.55 - 22.475, 5.0))
    eyes = [EYE_P]  # the pilot's: only the player's view counts
    for rnd in range(3 if "--apply" in argv else 1):
        tree, owner, ref = seeinto.build(meshes)
        t = teeth(tree, owner, ref, eyes)
        deck = bpy.data.objects["flightdeck_int"]
        print("TEETH round", rnd, "faces", len(t), "rays", sum(t.values()),
              [(i, deck.material_slots[deck.data.polygons[i].material_index].material.name,
                tuple(round(c, 2) for c in deck.matrix_world @ deck.data.polygons[i].center)) for i, _ in t.most_common(6)])
        if "--apply" not in argv or not t:
            break
        bm = bmesh.new()
        bm.from_mesh(deck.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in t], context="FACES")
        bm.to_mesh(deck.data)
        bm.free()
        deck.data.update()
    if "--apply" in argv:
        bpy.ops.wm.save_mainfile(filepath=argv[0])
