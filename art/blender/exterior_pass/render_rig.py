"""Render pieces the pass's luma gate and its distant model share: the Centurion's baked skin as a game-like material
with the damage rule and back faces culled, flat stand-ins, the collision and LOD helpers kept out of renders, a camera
and sun rig, and the stages slid to an extension."""
import math
from pathlib import Path

import bpy
from mathutils import Vector

REPO = Path(__file__).resolve().parents[3]
# The parts blend carries the shipped UVs (the maps in the Unity project); the detailed blend under .cache/art/m4 was
# rebaked on its own UVs on 2026-10-18 and matches only its own textures folder.
TEX = (REPO / "unity" / "Assets" / "Blueprinter" / "Mods" / "centurion" / "Skin" if "m4_parts" in bpy.data.filepath
       else REPO / ".cache" / "art" / "m4" / "textures")


def img(path, data):
    i = bpy.data.images.load(str(path), check_existing=True)
    i.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return i


def _node(nt, kind, **kw):
    n = nt.nodes.new(kind)
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def skin_material(name, maps, hp=100.0, cull=True, procedural=None, livery=None, clip=None):
    """A Principled skin from baked maps (keys b, m, n, ao, dmg_b), albedo x lerp(1, dmg RGB, D), cut where the game's rule
    D*(alpha-0.52)+0.02 < 0 opens it (D = 1 - hp/100), back faces see-through as the game culls them. procedural: a
    shader-side stand-in for a new damage alpha (a callable(nt, D) returning an alpha socket)."""
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    nt.nodes.clear()
    out = _node(nt, "ShaderNodeOutputMaterial")
    bsdf = _node(nt, "ShaderNodeBsdfPrincipled")
    uv = _node(nt, "ShaderNodeUVMap", uv_map="UVMap")
    D = max(0.0, 1.0 - hp / 100.0)

    def tex(path, data=True):
        t = _node(nt, "ShaderNodeTexImage", image=img(path, data))
        nt.links.new(uv.outputs["UV"], t.inputs["Vector"])
        return t

    alb = tex(livery or maps["b"], False)
    col = alb.outputs["Color"]
    if "ao" in maps:
        m = _node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        m.inputs["Factor"].default_value = 1.0
        nt.links.new(col, m.inputs["A"])
        nt.links.new(tex(maps["ao"]).outputs["Color"], m.inputs["B"])
        col = m.outputs["Result"]
    alpha = None
    if "dmg_b" in maps:
        dm = tex(maps["dmg_b"], False)
        tint = _node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MIX")
        tint.inputs["Factor"].default_value = D
        tint.inputs["A"].default_value = (1, 1, 1, 1)
        nt.links.new(dm.outputs["Color"], tint.inputs["B"])
        mul = _node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        mul.inputs["Factor"].default_value = 1.0
        nt.links.new(col, mul.inputs["A"])
        nt.links.new(tint.outputs["Result"], mul.inputs["B"])
        col = mul.outputs["Result"]
        alpha = dm.outputs["Alpha"]
    if procedural is not None:
        alpha = procedural(nt, D)
        if isinstance(alpha, tuple):  # (alpha, char): char 0..1 darkens the paint round a tear, as a burn would
            alpha, char = alpha
            k = _node(nt, "ShaderNodeMath", operation="MULTIPLY_ADD")
            k.inputs[1].default_value, k.inputs[2].default_value = -0.5, 1.0  # scorched, still lighter than the cavity
            nt.links.new(char, k.inputs[0])
            burn = _node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            burn.inputs["Factor"].default_value = 1.0
            nt.links.new(col, burn.inputs["A"])
            cv = _node(nt, "ShaderNodeCombineColor")
            for ch in ("Red", "Green", "Blue"):
                nt.links.new(k.outputs[0], cv.inputs[ch])
            nt.links.new(cv.outputs[0], burn.inputs["B"])
            col = burn.outputs["Result"]
    nt.links.new(col, bsdf.inputs["Base Color"])
    if "m" in maps:
        ms = tex(maps["m"])
        sep = _node(nt, "ShaderNodeSeparateColor")
        nt.links.new(ms.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
        inv = _node(nt, "ShaderNodeMath", operation="SUBTRACT")
        inv.inputs[0].default_value = 1.0
        nt.links.new(ms.outputs["Alpha"], inv.inputs[1])
        nt.links.new(inv.outputs["Value"], bsdf.inputs["Roughness"])
    if "n" in maps:
        nm = _node(nt, "ShaderNodeNormalMap", uv_map="UVMap")
        nt.links.new(tex(maps["n"]).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    shader = bsdf.outputs["BSDF"]
    transparent = _node(nt, "ShaderNodeBsdfTransparent")
    if alpha is not None and D > 0:
        # open = D*(a-0.52)+0.02 < 0  ->  keep = D*a - 0.52*D + 0.02 >= 0
        f1 = _node(nt, "ShaderNodeMath", operation="MULTIPLY_ADD")
        f1.inputs[1].default_value = D
        f1.inputs[2].default_value = 0.02 - 0.52 * D
        nt.links.new(alpha, f1.inputs[0])
        keep = _node(nt, "ShaderNodeMath", operation="GREATER_THAN")
        keep.inputs[1].default_value = 0.0
        nt.links.new(f1.outputs[0], keep.inputs[0])
        mix = _node(nt, "ShaderNodeMixShader")
        nt.links.new(keep.outputs[0], mix.inputs["Fac"])
        nt.links.new(transparent.outputs[0], mix.inputs[1])
        nt.links.new(shader, mix.inputs[2])
        shader = mix.outputs[0]
    if clip is not None:  # the stock jet_mechanical cuts its perforations at alpha 0.394
        keep = _node(nt, "ShaderNodeMath", operation="GREATER_THAN")
        keep.inputs[1].default_value = clip
        nt.links.new(alb.outputs["Alpha"], keep.inputs[0])
        mixc = _node(nt, "ShaderNodeMixShader")
        nt.links.new(keep.outputs[0], mixc.inputs["Fac"])
        nt.links.new(transparent.outputs[0], mixc.inputs[1])
        nt.links.new(shader, mixc.inputs[2])
        shader = mixc.outputs[0]
    if cull:
        shader = camera_cull(nt, shader)
    nt.links.new(shader, out.inputs["Surface"])
    return mat


def camera_cull(nt, shader):
    """Back faces invisible to the camera, as the game culls them; to light, only the faces the game's shadow pass draws:
    those turned toward the sun. A shadow ray runs toward the light, so it meets such a face from behind; a face it meets
    from the front (an inward copy under a hole) lets the light through, or every hole's structure rendered black."""
    geo = _node(nt, "ShaderNodeNewGeometry")
    lp = _node(nt, "ShaderNodeLightPath")
    cam_back = _node(nt, "ShaderNodeMath", operation="MULTIPLY")
    nt.links.new(geo.outputs["Backfacing"], cam_back.inputs[0])
    nt.links.new(lp.outputs["Is Camera Ray"], cam_back.inputs[1])
    front = _node(nt, "ShaderNodeMath", operation="SUBTRACT")
    front.inputs[0].default_value = 1.0
    nt.links.new(geo.outputs["Backfacing"], front.inputs[1])
    shadow_front = _node(nt, "ShaderNodeMath", operation="MULTIPLY")
    nt.links.new(front.outputs[0], shadow_front.inputs[0])
    nt.links.new(lp.outputs["Is Shadow Ray"], shadow_front.inputs[1])
    both = _node(nt, "ShaderNodeMath", operation="MAXIMUM")
    nt.links.new(cam_back.outputs[0], both.inputs[0])
    nt.links.new(shadow_front.outputs[0], both.inputs[1])
    tr = _node(nt, "ShaderNodeBsdfTransparent")
    mix = _node(nt, "ShaderNodeMixShader")
    nt.links.new(both.outputs[0], mix.inputs["Fac"])
    nt.links.new(shader, mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    return mix.outputs[0]


def flat(name, rgb, rough=0.6, metal=0.0, cull=False):
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    p = nt.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*rgb, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if cull:
        out = nt.nodes.get("Material Output")
        nt.links.new(camera_cull(nt, p.outputs["BSDF"]), out.inputs["Surface"])
    return mat
HELPER_COLLECTIONS = ("Colliders", "LOD1", "M4_render", "Centurion_render")


def is_helper(o, lod_too=True):
    names = {c.name for c in o.users_collection}
    return (("_colmesh" in o.name or "Colliders" in names) or (lod_too and ("_lod1" in o.name or "LOD1" in names))
            or o.name.endswith(("_blockout_mesh", "_shape")))


def hide_helpers(lod_too=True):
    """Collision meshes, LOD1 hulls and blockout stand-ins out of every render. The collections themselves are excluded
    and each object is hidden from a snapshot list: setting hide_render while iterating the live all_objects skipped
    most of them (round 2 hid 6 to 24 of 47 colliders)."""
    for name in HELPER_COLLECTIONS:
        if name == "LOD1" and not lod_too:
            continue
        c = bpy.data.collections.get(name)
        if c:
            c.hide_render = True
    for o in list(bpy.data.objects):
        if is_helper(o, lod_too):
            o.hide_render = True
    assert_clean(lod_too)


def assert_clean(lod_too=True):
    """Fail the run if any collision mesh (or, with lod_too, any LOD1 hull) would render."""
    shown = [o.name for o in bpy.data.objects if o.type == "MESH" and is_helper(o, lod_too) and not o.hide_render
             and not any(c.hide_render for c in o.users_collection)]
    if shown:
        raise SystemExit(f"helpers would render: {shown[:10]} ({len(shown)})")


def rig(sun_rot=(42, 12, -35), ground=True):
    scene = bpy.context.scene
    coll = bpy.data.collections.new("art2_rig")
    scene.collection.children.link(coll)
    sun = bpy.data.objects.new("art2_sun", bpy.data.lights.new("art2_sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.4, math.radians(2.5)
    sun.rotation_euler = tuple(math.radians(a) for a in sun_rot)
    coll.objects.link(sun)
    if ground:
        me = bpy.data.meshes.new("art2_ground")
        me.from_pydata([(-400, -400, 0), (400, -400, 0), (400, 400, 0), (-400, 400, 0)], [], [(0, 1, 2, 3)])
        me.materials.append(flat("art2_ground", (0.16, 0.16, 0.155), 0.85))
        coll.objects.link(bpy.data.objects.new("art2_ground", me))
    cam = bpy.data.objects.new("art2_cam", bpy.data.cameras.new("art2_cam"))
    cam.data.clip_start, cam.data.clip_end = 0.02, 2000
    coll.objects.link(cam)
    scene.camera = cam
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.55, 0.6, 0.68, 1)
    bg.inputs["Strength"].default_value = 0.9
    scene.view_settings.view_transform = "AgX"  # Standard clips a sunlit light-grey face to white
    scene.render.use_stamp = False
    scene.render.film_transparent = False
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        if any(d.type == kind for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == kind
            scene.cycles.device = "GPU"
            break
    scene.cycles.transparent_max_bounces = 32
    return cam


def set_extension(ext):
    """Slide the stages as build_centurion.set_extension does, where the parts blend keeps slide_axis."""
    import sys
    sys.path.insert(0, str(REPO / "art" / "blender"))
    from m4.blockout import load_blockout
    bl = load_blockout()
    n = 0
    for o in bpy.data.objects:
        if "slide_axis" in o and "rest_location" in o:
            o.location = Vector(o["rest_location"]) + Vector(o["slide_axis"]) * (bl.TRAVEL * ext)
            n += 1
    bpy.context.view_layer.update()
    return n
