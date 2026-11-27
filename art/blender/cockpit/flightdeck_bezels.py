"""Every display's bezel in plain sight from both seats (the skirt and housing edges stood across the
tops of the commander's radar and flight display): for each display page a seat uses (its own and the centre stack's;
the other seat's own, across the cabin, stand behind the centre stack), points 8 mm outside its
edge, 10 along each side, on the page's plane; from each seat's eye, the sightline to each point must meet nothing
drawn more than NEAR from it (glass and faces seen from behind pass; the game's stock seats, sticks and throttles
are counted apart, since they move). Imported by flightdeck_sightlines.py, or alone:
blender -b --factory-startup --python flightdeck_bezels.py -- <export.blend> <blockout.blend>"""
from collections import Counter

from mathutils import Vector

GLASS = {"glass_int", "band", "band_marker"}
NEAR = 0.03  # metres: what a sightline meets this close to the bezel point is the bezel
FRAME_NEAR = 0.08  # the same for a page turned to the other seat: its housing's frame stands this far proud


def outline(o, p, grow=0.008, n=10):
    mw = o.matrix_world
    vs = [mw @ o.data.vertices[i].co for i in p.vertices]
    c = sum(vs, Vector()) / len(vs)
    pts = []
    for k in range(len(vs)):
        a, b = vs[k], vs[(k + 1) % len(vs)]
        for j in range(n):
            q = a.lerp(b, (j + 0.5) / n)
            m = (q - c)
            pts.append(q + m.normalized() * grow)
    return c, pts


def bezels(tree, ref, eyes, screens):
    """screens: the display object (tacScreen). Returns per seat the blocked sightlines and what blocked them."""
    res = {}
    for seat, e in eyes.items():
        n, blocked, stock, who = 0, 0, 0, Counter()
        for p in screens.data.polygons:
            c, pts = outline(screens, p)
            if (screens.matrix_world.to_3x3() @ p.normal).dot(e - c) <= 0:
                continue  # a page turned away from this seat (none is)
            if c.x * e.x < 0 and abs(c.x) > 0.35:
                continue  # the other seat's own displays: across the cabin the centre stack stands in front of them
            n_ = (screens.matrix_world.to_3x3() @ p.normal).normalized()
            # the centre stack's pages turned to the other seat (the owner's call: they face the pilot): from this seat
            # their far edge stands behind their own frame, which is not a fault
            own_frame = abs(c.x) < 0.35 and n_.x * e.x < 0 and abs(n_.x) > 0.5
            for q in pts:
                d = q - e
                L = d.length
                d.normalize()
                o, t = e, 0.0
                n += 1
                while True:
                    h = tree.ray_cast(o, d, L - t - 0.008)
                    if h[0] is None:
                        break
                    ob, pi = ref[h[2]]
                    if ob in GLASS or h[1].dot(d) >= 0:
                        t += h[3] + 0.0002
                        o = h[0] + d * 0.0002
                        continue
                    if (h[0] - q).length < (FRAME_NEAR if own_frame else NEAR):
                        break  # the bezel itself (its raised lip, met first by a grazing sightline)
                    if ob.startswith("stock"):
                        stock += 1
                    else:
                        blocked += 1
                        who[(ob, pi, tuple(round(x, 2) for x in h[0]))] += 1
                    break
        res[seat] = {"sightlines": n, "blocked": blocked, "by_stock_parts": stock,
                     "blockers": [[list(k), v] for k, v in who.most_common(12)]}
        print("BEZEL", seat, "sightlines", n, "blocked", blocked, "by the stock parts", stock, who.most_common(5))
    return res


if __name__ == "__main__":
    import sys

    import bpy
    sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
    import flightdeck_seeinto as seeinto
    argv = sys.argv[sys.argv.index("--") + 1:]
    bpy.ops.wm.open_mainfile(filepath=argv[0])
    with bpy.data.libraries.load(argv[1]) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith("stock_seat") or n.startswith("stockref_Multirole1_joystick")
                       or n.startswith("stockref_Multirole1_throttle")]
    for o in dst.objects:
        if o is not None:
            bpy.context.scene.collection.objects.link(o)
    tree, owner, ref = seeinto.build([o for o in bpy.context.scene.objects if o.type == "MESH"])
    EYES = {"pilot": Vector((0.55, 6.55 - 22.475, 5.0))}
    EYES["commander"] = EYES["pilot"] + Vector((-1.10, -0.04, -0.12))
    bezels(tree, ref, EYES, bpy.data.objects["tacScreen"])
