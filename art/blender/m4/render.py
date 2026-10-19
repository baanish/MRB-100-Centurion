"""Review renders: Cycles on the GPU with a sun, a sky-coloured world and a ground plane, the detailed group in its
baked maps and the rest of the blockout in flat paint of the same grey."""

import math
import subprocess
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

from . import texture as tx

# A view is (lens, camera location, look-at target) with positions as (x, station, z), or for an orthographic view
# (("ortho", scale, camera rotation in degrees), camera location, None). A group module's VIEWS take the same form.
SIDE, TOP = (90, 0, 90), (0, 0, 180)  # from +X, nose to the left; from above, nose up as the three-view
AIRCRAFT_VIEWS = {
    "hero": (50, (42.0, -31.0, 33.0), (0.0, 22.5, 3.0)),
    "side": (("ortho", 50.0, SIDE), (120.0, 22.5, 3.8), None),
    "top": (("ortho", 76.0, TOP), (0.0, 22.5, 80.0), None),
}
# The extended wing spans bl.SPAN_EXTENDED (87 m): the hero on a wider lens and the top view framed wider.
AIRCRAFT_VIEWS_EXTENDED = {**AIRCRAFT_VIEWS, "hero": (44, (62.0, -46.0, 48.0), (6.0, 24.5, 3.0)),
                           "top": (("ortho", 96.0, TOP), (0.0, 22.5, 80.0), None)}
# The composite adds the junctions the owner's flow rule is about: the wing fairing over the root, the sponson and the
# strut root, seen from ahead, left and above.
COMPOSITE_VIEWS = {"junctions": (30, (16.0, 4.0, 12.5), (1.5, 20.0, 5.0))}


def game_running():
    """NuclearOption.exe is up: bakes stay on the CPU and renders go to Workbench, so the game's frame rate holds."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NuclearOption.exe", "/NH"], capture_output=True, text=True).stdout
    return "NuclearOption.exe" in out


def use_gpu(scene):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            scene.cycles.device = "GPU"
            return kind
    scene.cycles.device = "CPU"
    return "CPU"


def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def principled(mat, base=None, rough=None, metal=None, emit=None, strength=0.0):
    p = mat.node_tree.nodes.get("Principled BSDF")
    if base is not None:
        p.inputs["Base Color"].default_value = (*base, 1.0)
        mat.diffuse_color = (*base, 1.0)
    if rough is not None:
        p.inputs["Roughness"].default_value = rough
    if metal is not None:
        p.inputs["Metallic"].default_value = metal
    if emit is not None:
        p.inputs["Emission Color"].default_value = (*emit, 1.0)
        p.inputs["Emission Strength"].default_value = strength


def style_shared(slot_names, paint_srgb):
    """Flat looks for the blockout skin and the stand-ins for the shared stock trims."""
    m = bpy.data.materials
    principled(m[slot_names["skin"]], tuple(srgb_to_linear(paint_srgb)), 0.6, 0.0)
    principled(m[slot_names["struct"]], (0.11, 0.115, 0.11), 0.7, 0.2)
    principled(m[slot_names["mech"]], (0.06, 0.06, 0.065), 0.45, 0.8)
    principled(m[slot_names["glass"]], (0.008, 0.011, 0.010), 0.04, 0.0)
    if slot_names.get("gear") in m:
        principled(m[slot_names["gear"]], (0.16, 0.16, 0.165), 0.55, 0.3)
    for name, col, k in (("light_red", (1.0, 0.05, 0.03), 6.0), ("light_white", (1.0, 0.95, 0.85), 4.0),
                         ("light_formation", (0.55, 1.0, 0.45), 0.25)):
        principled(m[name], {"light_red": (0.2, 0.05, 0.05), "light_white": (0.6, 0.6, 0.6)}.get(name, (0.32, 0.4, 0.3)), 0.15, 0.0, col, k)
    if "light_green" in m:  # the wing's starboard nav light, bound to a stock material of its own
        principled(m["light_green"], (0.02, 0.20, 0.025), 0.15, 0.0, (0.03, 1.0, 0.06), 6.0)


def preview_material(name, maps):
    """The baked maps as a Principled material: base x AO, metal from R, roughness 1 - A, tangent normal map."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"

    def tex(key, data=True):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = tx.load_image(maps[key], data=data)
        t.interpolation = "Linear"
        nt.links.new(uv.outputs["UV"], t.inputs["Vector"])
        return t

    alb, ms, nrm = tex("albedo", data=False), tex("metal_smooth"), tex("normal")
    nt.nodes.active = alb  # Workbench's texture colour
    if "ao" in maps:  # a trim sheet has none
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        nt.links.new(alb.outputs["Color"], mul.inputs["A"])
        nt.links.new(tex("ao").outputs["Color"], mul.inputs["B"])
        nt.links.new(mul.outputs["Result"], bsdf.inputs["Base Color"])
    else:
        nt.links.new(alb.outputs["Color"], bsdf.inputs["Base Color"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(ms.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(ms.outputs["Alpha"], inv.inputs[1])
    nt.links.new(inv.outputs["Value"], bsdf.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.uv_map = "UVMap"
    nt.links.new(nrm.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def build_rig(bl):
    scene = bpy.context.scene
    coll = bpy.data.collections.get("M4_render") or bpy.data.collections.new("M4_render")
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    for o in list(coll.objects):
        bpy.data.objects.remove(o)
    old = bpy.data.collections.get("Centurion_render")
    if old is not None:
        for o in old.objects:
            o.hide_render = True
    sun = bpy.data.objects.new("m4_sun", bpy.data.lights.new("m4_sun", "SUN"))
    sun.data.energy, sun.data.angle = 3.2, math.radians(2.5)
    sun.rotation_euler = (math.radians(42), math.radians(12), math.radians(-35))
    coll.objects.link(sun)
    me = bpy.data.meshes.new("m4_ground")
    me.from_pydata([(-200, -200, 0), (200, -200, 0), (200, 200, 0), (-200, 200, 0)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new("m4_ground", me)
    gm = bpy.data.materials.get("m4_ground") or bpy.data.materials.new("m4_ground")
    principled(gm, (0.16, 0.16, 0.155), 0.85, 0.0)
    me.materials.append(gm)
    coll.objects.link(ground)
    cam = bpy.data.objects.new("m4_cam", bpy.data.cameras.new("m4_cam"))
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
    scene.render.use_stamp = False  # the blockout's saved scenes carry its caption stamp
    scene.render.film_transparent = False
    return cam, ground


def shoot(bl, cam, view, path, samples, res=(1600, 1000)):
    """Render one view (see AIRCRAFT_VIEWS) to path. A camera under the ground renders with the ground hidden. While
    the game runs, Workbench (the albedo, studio light) stands in for Cycles."""
    scene = bpy.context.scene
    lens, loc, target = view
    st = bl.st
    cam.location = Vector((loc[0], st(loc[1]), loc[2]))
    ground = bpy.data.objects.get("m4_ground")
    if ground is not None:
        ground.hide_render = loc[2] < 0
    if isinstance(lens, tuple):
        cam.data.type, cam.data.ortho_scale = "ORTHO", lens[1]
        cam.rotation_euler = tuple(math.radians(a) for a in lens[2])
    else:
        cam.data.type, cam.data.lens = "PERSP", lens
        t = Vector((target[0], st(target[1]), target[2]))
        cam.rotation_euler = (t - cam.location).to_track_quat("-Z", "Y").to_euler()
    if game_running():
        scene.render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.light, shading.color_type, shading.show_cavity = "STUDIO", "TEXTURE", True
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = *res, 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return Path(path)
