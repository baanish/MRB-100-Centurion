"""Brings stock_cockpits.py's OBJ exports into a Blender scene with their stock textures, for review renders only.

import_stock(folder, keep, offset, mirror) -> [objects]: keep(part) decides which parts come in (part is scene.json's
entry: name, list, layer, materials); offset is added to every vertex after an optional mirror across x = 0."""

import json
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def _material(name, info, cache):
    if name in cache:
        return cache[name]
    m = bpy.data.materials.new("stock_" + name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    maps = (info or {}).get("maps", {})

    def tex(key, colour=True):
        path = maps[key]
        if not Path(path).exists():  # a host without the source drive: gather_textures.py copied the file here
            path = str(Path(__file__).resolve().parents[3] / ".cache" / "art" / "cockpit" / "texcache" / Path(path.replace("\\", "/")).name)
        img = bpy.data.images.load(path, check_existing=True)
        if not colour:
            img.colorspace_settings.name = "Non-Color"
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        return n
    low = name.lower()
    if "b" in maps:
        b = tex("b")
        if "ao" in maps:
            ao = tex("ao", False)
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            nt.links.new(b.outputs["Color"], mix.inputs[6])
            nt.links.new(ao.outputs["Color"], mix.inputs[7])
            nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
        else:
            nt.links.new(b.outputs["Color"], bsdf.inputs["Base Color"])
    if "m" in maps:  # Unity metallic (R) and smoothness (A)
        mm = tex("m", False)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(mm.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
        inv = nt.nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        nt.links.new(mm.outputs["Alpha"], inv.inputs[1])
        nt.links.new(inv.outputs[0], bsdf.inputs["Roughness"])
    if "n" in maps:
        n = tex("n", False)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(n.outputs["Color"], nm.inputs["Color"])
        # Unity normal maps are OpenGL-style (+Y), as Blender's
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if low == "matte_black":
        bsdf.inputs["Base Color"].default_value = (0.01, 0.01, 0.01, 1)
        bsdf.inputs["Roughness"].default_value = 0.9
    if "glass" in low:
        bsdf.inputs["Base Color"].default_value = (0.8, 0.85, 0.9, 1)
        bsdf.inputs["Alpha"].default_value = 0.08
        bsdf.inputs["Roughness"].default_value = 0.05
    if low == "tacscreendisplay":
        bsdf.inputs["Base Color"].default_value = (0.0, 0.02, 0.0, 1)
        bsdf.inputs["Emission Color"].default_value = (0.05, 0.45, 0.08, 1)
        bsdf.inputs["Emission Strength"].default_value = 1.0
    cache[name] = m
    return m


def import_stock(folder, keep, offset=Vector(), mirror=False, tag=""):
    folder = Path(folder)
    scene = json.load(open(folder / "scene.json"))
    cache = {}
    out = []
    for part in scene["parts"]:
        if not keep(part):
            continue
        before = set(bpy.data.objects)
        bpy.ops.wm.obj_import(filepath=str(folder / part["file"]), forward_axis="Y", up_axis="Z")
        new = [o for o in bpy.data.objects if o not in before]
        for o in new:
            o.name = "stock%s_%s" % (tag, part["name"])
            if mirror:
                o.data.transform(Matrix.Scale(-1, 4, Vector((1, 0, 0))))
                o.data.flip_normals()
            o.data.transform(Matrix.Translation(offset))
            for slot in o.material_slots:
                base = slot.material.name.split(".")[0] if slot.material else "missing"
                slot.material = _material(base, scene["materials"].get(base), cache)
            o["stock_list"] = part["list"]
            out.append(o)
    return out, Vector(scene["eye"])
