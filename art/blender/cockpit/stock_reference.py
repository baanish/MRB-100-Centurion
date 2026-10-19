"""Stock cockpit parts and materials in the flight deck's review renders, by reference: decodes the Blueprinter
placeholder mesh assets under unity/Assets/Blueprinter/_donotship (Unity YAML, never shipped) into the review scene and
dresses them in the stock textures, so a render shows what the game will draw where authoring references them. Nothing
from here reaches flightdeck.blend or the export: the review scene is saved separately, and the export blend keeps only
the interior's own parts.

Unity's frame is (x right, y up, z forward); the composite's is (x left, y aft, z up): (x, y, z)_unity -> (-x, -z, y).

Run outside Blender for the measurements: python -I art/blender/cockpit/stock_reference.py"""

import math
import re
import struct
from pathlib import Path

DONOTSHIP = Path(__file__).resolve().parents[3] / "unity" / "Assets" / "Blueprinter" / "_donotship"
FORMAT_SIZE = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}
FORMAT_CODE = {0: "f", 1: "e", 2: "B", 3: "b", 4: "H", 5: "h", 6: "B", 7: "b", 8: "H", 9: "h", 10: "I", 11: "i"}


def read_mesh(name):
    """{"pos", "nrm", "uv": per vertex lists in Unity's frame, "subs": [(triangles as index triples)]} of a placeholder."""
    text = (DONOTSHIP / "Mesh" / f"{name}_PLACEHOLDER.asset").read_text(errors="ignore")
    head = text.split("m_Shapes:")[0]
    subs = [(int(a), int(b), int(c)) for a, b, c in re.findall(
        r"firstByte: (\d+)\s*\n\s*indexCount: (\d+)\s*\n\s*topology: \d+\s*\n\s*baseVertex: (\d+)", head)]
    wide = re.search(r"m_IndexFormat: (\d+)", text).group(1) == "1"
    ib = bytes.fromhex(re.search(r"m_IndexBuffer: ([0-9a-f]*)", text).group(1))
    count = int(re.search(r"m_VertexCount: (\d+)", text).group(1))
    chans = [tuple(int(v) for v in m) for m in re.findall(
        r"- stream: (\d+)\s*\n\s*offset: (\d+)\s*\n\s*format: (\d+)\s*\n\s*dimension: (\d+)", text.split("m_VertexData:")[1])]
    data = bytes.fromhex(re.search(r"_typelessdata: ([0-9a-f]*)", text).group(1))
    strides, starts, at = {}, {}, 0
    for s in sorted({c[0] for c in chans if c[3]}):
        strides[s] = max(o + FORMAT_SIZE[f] * (d & 0xF) for st, o, f, d in chans if st == s and d)
        starts[s] = at
        at += strides[s] * count
        at = (at + 15) // 16 * 16

    def channel(i):
        if i >= len(chans) or not chans[i][3]:
            return None
        s, o, f, d = chans[i]
        d &= 0xF
        fmt = "<" + FORMAT_CODE[f] * d
        return [struct.unpack_from(fmt, data, starts[s] + strides[s] * v + o) for v in range(count)]

    isz = 4 if wide else 2
    out = []
    for first, n, base in subs:
        idx = struct.unpack_from("<" + ("I" if wide else "H") * n, ib, first)
        out.append([(idx[k] + base, idx[k + 1] + base, idx[k + 2] + base) for k in range(0, n - n % 3, 3)])
    del isz
    return {"pos": channel(0), "nrm": channel(1), "uv": channel(4), "subs": out}


def to_composite(p):
    return (-p[0], -p[2], p[1])


def uv_density(name, sub, texture_px):
    """Texels per metre a stock mesh's submesh gives a texture texture_px wide: how densely the stock tiles it."""
    m = read_mesh(name)
    world = uvs = 0.0
    for a, b, c in m["subs"][sub]:
        pa, pb, pc = (m["pos"][i] for i in (a, b, c))
        ua, ub, uc = (m["uv"][i] for i in (a, b, c))
        e1 = [pb[k] - pa[k] for k in range(3)]
        e2 = [pc[k] - pa[k] for k in range(3)]
        cr = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        world += math.sqrt(sum(v * v for v in cr)) / 2
        uvs += abs((ub[0] - ua[0]) * (uc[1] - ua[1]) - (ub[1] - ua[1]) * (uc[0] - ua[0])) / 2
    return texture_px * math.sqrt(uvs / world) if world else 0.0


# ---------------- Blender side: the review scene only ----------------
def blender_mesh(name):
    import bpy
    me = bpy.data.meshes.get("stock_" + name)
    if me:
        return me
    m = read_mesh(name)
    tris = [t for sub in m["subs"] for t in sub]
    me = bpy.data.meshes.new("stock_" + name)
    me.from_pydata([to_composite(p) for p in m["pos"]], [], [(a, c, b) for a, b, c in tris])  # the mirror flips winding
    if m["uv"]:
        layer = me.uv_layers.new(name="UVMap")
        for poly, (a, b, c) in zip(me.polygons, tris):
            for li, v in zip(poly.loop_indices, (a, c, b)):
                layer.data[li].uv = m["uv"][v][:2]
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    return me


def texture_material(name, maps, uv_scale=(1.0, 1.0), tint=None, alpha_clip=False):
    """A review material from stock texture names (keys albedo, metal_smooth, normal, ao), tiled by uv_scale; tint
    multiplies the albedo (the vertex colour the stock structure shader applies)."""
    import bpy
    mat = bpy.data.materials.get("stockref_" + name)
    if mat:
        return mat
    mat = bpy.data.materials.new("stockref_" + name)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (uv_scale[0], uv_scale[1], 1.0)
    nt.links.new(uv.outputs["UV"], mapping.inputs["Vector"])

    def tex(key, srgb=False):
        t = nt.nodes.new("ShaderNodeTexImage")
        img = bpy.data.images.load(str(DONOTSHIP / "Texture2D" / f"{maps[key]}_PLACEHOLDER.png"), check_existing=True)
        img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
        t.image = img
        nt.links.new(mapping.outputs["Vector"], t.inputs["Vector"])
        return t

    alb = tex("albedo", srgb=True)
    col = alb.outputs["Color"]
    for key, value in (("ao", None), ("tint", tint)):
        if key == "ao" and "ao" not in maps:
            continue
        if key == "tint" and tint is None:
            continue
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        nt.links.new(col, mul.inputs["A"])
        if key == "ao":
            nt.links.new(tex("ao").outputs["Color"], mul.inputs["B"])
        else:
            mul.inputs["B"].default_value = (*value, 1.0)
        col = mul.outputs["Result"]
    nt.links.new(col, bsdf.inputs["Base Color"])
    if "metal_smooth" in maps:
        ms = tex("metal_smooth")
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(ms.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
        inv = nt.nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        nt.links.new(ms.outputs["Alpha"], inv.inputs[1])
        nt.links.new(inv.outputs["Value"], bsdf.inputs["Roughness"])
    if "normal" in maps:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = "UVMap"
        nt.links.new(tex("normal").outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def flat_material(name, rgb, rough, emit=None, alpha=1.0):
    import bpy
    mat = bpy.data.materials.get("stockref_" + name) or bpy.data.materials.new("stockref_" + name)
    p = mat.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*rgb, 1.0)
    p.inputs["Roughness"].default_value = rough
    if emit:
        p.inputs["Emission Color"].default_value = (*emit[0], 1.0)
        p.inputs["Emission Strength"].default_value = emit[1]
    p.inputs["Alpha"].default_value = alpha
    return mat


def stock_materials():
    """The shared stock materials as the review draws them: Matte_black and Touchscreen_off flat black at their
    smoothness, CockpitWarningLight its dark translucent red unlit (it glows only on a warning), hotas and
    aircraft_structure in their textures (the structure tinted by STRUCTURE_TINT, standing in for the vertex colour
    the stock structure shader multiplies in)."""
    from flightdeck_uv import STRUCTURE_TINT  # the vertex colour the export carries (Blender only)
    return {
        "Matte_black": flat_material("Matte_black", (0.0, 0.0, 0.0), 0.5),
        "Touchscreen_off": flat_material("Touchscreen_off", (0.0, 0.0, 0.0), 0.4),
        "CockpitWarningLight": flat_material("CockpitWarningLight", (0.05, 0.0, 0.0), 1.0, emit=((1.0, 0.05, 0.02), 0.0), alpha=0.6),
        "hotas": texture_material("hotas", {"albedo": "hotas_b", "metal_smooth": "hotas_m", "normal": "hotas_n", "ao": "hotas_ao"}),
        "aircraft_structure": texture_material("aircraft_structure", {"albedo": "aircraft_structure_b", "metal_smooth": "aircraft_structure_m",
                                                                      "normal": "aircraft_structure_n", "ao": "aircraft_structure_ao"},
                                               tint=STRUCTURE_TINT),
    }




def place(name, location, rotation_z=0.0, mirror=False, material=None, collection=None):
    """A stock mesh in the review scene with its origin at location (composite frame), turned rotation_z radians about
    Z, mirrored left for right when mirror (a right-hand stick in a left hand)."""
    import bpy
    o = bpy.data.objects.new("stockref_" + name, blender_mesh(name))
    o.location = location
    o.rotation_euler = (0.0, 0.0, rotation_z)
    if mirror:
        o.scale = (-1.0, 1.0, 1.0)
    if material is not None:
        o.data.materials.clear()
        o.data.materials.append(material)
    (collection or bpy.context.scene.collection).objects.link(o)
    return o


if __name__ == "__main__":
    for name, sub, px in (("sfb_cockpit_int", 0, 1024), ("CAS1_cockpit_int", 0, 1024), ("fastBomber1_cockpit_int", 1, 1024)):
        print(f"{name} submesh {sub}: aircraft_structure at {uv_density(name, sub, px):.0f} px/m")
    for name in ("Multirole1_joystick", "Multirole1_throttle", "multirole1_warningLights"):
        m = read_mesh(name)
        xs = [p for p in m["pos"]]
        lo = [min(p[k] for p in xs) for k in range(3)]
        hi = [max(p[k] for p in xs) for k in range(3)]
        print(name, len(m["pos"]), "verts", sum(len(s) for s in m["subs"]), "tris", "bounds", [round(v, 3) for v in lo], [round(v, 3) for v in hi])
