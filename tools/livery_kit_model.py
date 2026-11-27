"""Make a Blender and FBX paint model from the kit's staged exterior triangles."""

import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrub_fbx import scrub_file  # noqa: E402

MODEL = "centurion_paint_model"


def paint_texture(nodes, relative, colour_space):
    image = bpy.data.images.new(Path(relative).name, 8, 8)
    image.source = "FILE"
    image.filepath = "//" + relative
    image.colorspace_settings.name = colour_space
    node = nodes.new("ShaderNodeTexImage")
    node.image = image
    return node


def paint_material(example):
    material = bpy.data.materials.new("Centurion livery")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shader = nodes.get("Principled BSDF")
    base = paint_texture(nodes, f"../examples/{example}", "sRGB")
    metal = paint_texture(nodes, "../maps/centurion_m.png", "Non-Color")
    normal = paint_texture(nodes, "../maps/centurion_n.png", "Non-Color")
    links.new(base.outputs["Color"], shader.inputs["Base Color"])
    # The bake stores the same metal value in R, G and B and smoothness in alpha.
    links.new(metal.outputs["Color"], shader.inputs["Metallic"])
    roughness = nodes.new("ShaderNodeMath")
    roughness.operation = "SUBTRACT"
    roughness.inputs[0].default_value = 1
    links.new(metal.outputs["Alpha"], roughness.inputs[1])
    links.new(roughness.outputs["Value"], shader.inputs["Roughness"])
    normals = nodes.new("ShaderNodeNormalMap")
    links.new(normal.outputs["Color"], normals.inputs["Color"])
    links.new(normals.outputs["Normal"], shader.inputs["Normal"])
    for node in nodes:
        node.select = node == base
    nodes.active = base
    return material


def paint_object(source, scene):
    with np.load(source) as data:
        vertices, faces, uv, normals = (data[key] for key in ("vertices", "faces", "uv", "normals"))
    mesh = bpy.data.meshes.new(MODEL)
    mesh.from_pydata(vertices.tolist(), [], faces.tolist(), shade_flat=False)
    mesh.update()
    # Some exported triangles use the same vertices. Mesh validation would remove those faces.
    layer = mesh.uv_layers.new(name="UVMap", do_init=False)
    layer.uv.foreach_set("vector", np.ascontiguousarray(uv).ravel())
    mesh.normals_split_custom_set(normals.reshape(-1, 3).tolist())
    actual_uv = np.empty(uv.size, np.float32)
    layer.uv.foreach_get("vector", actual_uv)
    actual_indices = np.empty(faces.size, np.int32)
    mesh.loops.foreach_get("vertex_index", actual_indices)
    actual_vertices = np.empty(vertices.size, np.float32)
    mesh.vertices.foreach_get("co", actual_vertices)
    if not (np.array_equal(actual_uv, uv.ravel()) and np.array_equal(actual_indices, faces.ravel())
            and np.array_equal(actual_vertices, vertices.ravel())):
        raise ValueError("Blender changed the exterior triangles or their UVs")
    mesh.update()
    obj = bpy.data.objects.new(MODEL, mesh)
    scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def main():
    mesh_path, kit = (Path(arg).resolve() for arg in sys.argv[sys.argv.index("--") + 1:])
    scene = bpy.context.scene
    scene.name = MODEL
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    source = json.loads((kit / "atlas.json").read_text(encoding="utf-8"))
    directory = kit / "model"
    model = paint_object(mesh_path, scene)
    material = paint_material(source["examples"]["bdf_matte_gray"])
    model.data.materials.append(material)
    bpy.context.view_layer.update()
    base_image = material.node_tree.nodes.active.image
    for index, image in enumerate(material.texture_paint_images):
        if image == base_image:
            material.paint_active_slot = index
            break

    blend = directory / (MODEL + ".blend")
    scene.render.filepath = ""
    # Save only the scene to avoid local file-browser paths. Preserve the image paths relative to the kit.
    bpy.data.libraries.write(str(blend), {scene}, path_remap="NONE", compress=False)
    data = blend.read_bytes()
    for saved_path in {str(blend), blend.as_posix()}:
        encoded = saved_path.encode()
        data = data.replace(encoded, bytes(len(encoded)))
    blend.write_bytes(data)

    # The FBX exporter resolves // against the open scene. The Blender file above is a saved copy.
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE":
            node.image.filepath = str((directory / node.image.filepath[2:]).resolve())
    fbx = directory / (MODEL + ".fbx")
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={"MESH"},
                             path_mode="RELATIVE", embed_textures=False, mesh_smooth_type="FACE",
                             add_leaf_bones=False, bake_anim=False)
    scrub_file(fbx)
    print(f"LIVERY KIT MODEL PASS: {len(model.data.polygons):,} skin triangles, {fbx.name} and {blend.name}", flush=True)


if __name__ == "__main__":
    main()
