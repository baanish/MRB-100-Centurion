"""Takes away the deck faces the pilot cannot see, so the flight deck stays under the 65,000 triangle cap: from his
eye (only the player's view at the normal eye counts), a face is seen when it faces the eye and the sightline to
its middle or to one of six points near its corners and edges meets it first. By default only the faces turned away
from every position go (the game culls them from every seat); with --hidden, the ones no sightline meets too. The
build step after flightdeck_cut.py and flightdeck_seeinto.py, saved into the export.
blender -b --factory-startup --python flightdeck_cull.py -- <export.blend> <blockout.blend>"""
import sys

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import flightdeck_seeinto as seeinto  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.open_mainfile(filepath=argv[0])
with bpy.data.libraries.load(argv[1]) as (src, dst):
    dst.objects = [n for n in src.objects if n.startswith("stock_seat") or n.startswith("stockref_Multirole1_joystick")
                   or n.startswith("stockref_Multirole1_throttle")]
stock = [o for o in dst.objects if o is not None]
for o in stock:
    bpy.context.scene.collection.objects.link(o)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
tree, owner, ref = seeinto.build(meshes)
deck = bpy.data.objects["flightdeck_int"]
base = next(i for i, r in enumerate(ref) if r[0] == deck.name)  # the deck's faces in the tree, in order
EYE_P = Vector((0.55, 6.55 - 22.475, 5.0))
eyes = [EYE_P]
mw = deck.matrix_world
n3 = mw.to_3x3()
GLASS = seeinto.GLASS


def seen(fi, p):
    c = mw @ p.center
    n = (n3 @ p.normal).normalized()
    vs = [mw @ deck.data.vertices[i].co for i in p.vertices]
    pts = [c] + [c.lerp(v, 0.8) for v in vs] + [c.lerp((vs[k] + vs[(k + 1) % len(vs)]) / 2, 0.8) for k in range(len(vs))]
    for e in eyes:
        if n.dot(e - c) <= 0:
            continue
        for q in pts:
            d = q - e
            L = d.length
            d.normalize()
            o, t = e, 0.0
            while True:  # glass and faces seen from behind let the sightline through
                h = tree.ray_cast(o, d, L - t + 0.002)
                if h[0] is None:
                    break
                if h[2] == base + fi:
                    return True
                if owner[h[2]] not in GLASS and h[1].dot(d) < 0:
                    break
                t += h[3] + 0.0002
                o = h[0] + d * 0.0002
    return False


def facing_any(p):
    c = mw @ p.center
    n = (n3 @ p.normal).normalized()
    return any(n.dot(e - c) > 0 for e in eyes)


# faces turned away from every head position (the box's corners among them, so from anywhere in it): the game culls
# them from every seat; the sightline test (seen) also takes faces seen only through a gap, which its seven points
# miss, and opens holes: --hidden adds it, off by default
gone = [p.index for p in deck.data.polygons if not facing_any(p) or ("--hidden" in argv and not seen(p.index, p))]


# and the lining's slivers: a face under 6 mm across and over 20 cm long, with any speck under 1 cm2 joined to it, seen
# edge-on as a hairline (build 15 and 16 in game: a strip of the left lining at station 6.72, 4 mm by half a metre,
# its end lit as a bright point); what lies behind it closes the view
def thin(p):
    vs = [mw @ deck.data.vertices[i].co for i in p.vertices]
    longest = max((vs[k] - vs[k - 1]).length for k in range(len(vs)))
    area = sum((vs[k] - vs[0]).cross(vs[k + 1] - vs[0]).length / 2 for k in range(1, len(vs) - 1))
    return longest > 0.20 and 2 * area / longest < 0.006


shell_slots = {k for k, sl in enumerate(deck.material_slots) if sl.material and sl.material.name.startswith("Centurion_cockpit_shell")}
strips = {p.index for p in deck.data.polygons if p.material_index in shell_slots and thin(p)}  # the lining's: the deck's
# own 4 mm seams and lips are drawn that thin on purpose
edge_faces = {}
for p in deck.data.polygons:
    for ek in p.edge_keys:
        edge_faces.setdefault(ek, []).append(p.index)
specks = {j for i in strips for ek in deck.data.polygons[i].edge_keys for j in edge_faces[ek]
          if deck.data.polygons[j].area < 1e-4}
gone = sorted(set(gone) | strips | specks)
print("CULL slivers", len(strips), "strips and", len(specks - strips), "specks joined to them")
bm = bmesh.new()
bm.from_mesh(deck.data)
bm.faces.ensure_lookup_table()
n_tris = sum(len(bm.faces[i].verts) - 2 for i in gone)
bmesh.ops.delete(bm, geom=[bm.faces[i] for i in gone], context="FACES")
bm.to_mesh(deck.data)
bm.free()
for o in stock:
    bpy.data.objects.remove(o)
bpy.ops.wm.save_mainfile(filepath=argv[0])
print("CULL head positions", len(eyes), "faces turned from every seat" + (" or hidden" if "--hidden" in argv else ""), len(gone), "triangles", n_tris, "deck now", len(deck.data.polygons))
