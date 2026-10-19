"""Blender side of the texturing: a bake proxy for a part group, the geometry buffers baked from it, image IO, and
stencil text rasterised from Blender's bundled font.

The proxy is one world-space mesh of the group's faces. Its skin faces with their own islands take the bake
material (the atlas is the active image); every other face (trims, glass, and mirrored faces whose islands are
copies) takes a dummy material whose target is a tiny throwaway image, so it occludes the AO bake without writing
into the atlas."""

import bmesh
import bpy
import numpy as np

BAKE_MARGIN = 16


def make_proxy(objs, skin_name, mirrored, group_of=None, moving=()):
    """mirrored: {object name: set of face indices whose UVs are copies}; group_of: {object name: group number from
    1} and moving (the names of parts that slide with the stages), baked beside the paint class so each texel knows
    which group paints it and whether it slides. Copies of the objects in world space,
    joined (a bmesh merge would drop later meshes' UVs)."""
    copies = []
    for o in objs:
        me = o.data.copy()
        me.transform(o.matrix_world)
        skin = [i for i, m in enumerate(me.materials) if m.name == skin_name]
        own = mirrored.get(o.name, ())
        slots = [0 if (p.material_index in skin and p.index not in own) else 1 for p in me.polygons]
        cls = np.zeros(len(me.polygons), np.int32)
        if "cls" in me.attributes:  # a blockout part standing in as an occluder has no paint class
            me.attributes["cls"].data.foreach_get("value", cls)
        me.materials.clear()
        me.attributes.new("bake_slot", "INT", "FACE").data.foreach_set("value", np.array(slots, np.int32))
        # Cycles reads the class from a colour attribute on face corners (a face-domain float bakes as 0)
        loop_cls = np.repeat(cls, [p.loop_total for p in me.polygons]).astype(np.float32)
        col = np.zeros((len(loop_cls), 4), np.float32)
        col[:, 0], col[:, 1], col[:, 2], col[:, 3] = loop_cls, (group_of or {}).get(o.name, 1), o.name in moving, 1.0
        me.color_attributes.new("clsf", "FLOAT_COLOR", "CORNER").data.foreach_set("color", col.ravel())
        c = bpy.data.objects.new("bake_proxy", me)
        bpy.context.scene.collection.objects.link(c)
        copies.append(c)
    with bpy.context.temp_override(active_object=copies[0], selected_editable_objects=copies, selected_objects=copies):
        bpy.ops.object.join()
    me = copies[0].data
    for name in ("bake_main", "bake_dummy"):  # slots must exist before indices are set, or they clamp to 0
        me.materials.append(bpy.data.materials.get(name) or bpy.data.materials.new(name))
    slots = np.zeros(len(me.polygons), np.int32)
    me.attributes["bake_slot"].data.foreach_get("value", slots)
    me.polygons.foreach_set("material_index", slots)
    return copies[0]


def bake_material(name, target):
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = target
    nt.nodes.active = tex
    return mat, emit, tex


def new_image(name, size, float_buffer=True):
    img = bpy.data.images.get(name)
    if img is not None:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, size, size, alpha=True, float_buffer=float_buffer)
    img.colorspace_settings.name = "Non-Color"
    return img


def pixels(img):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)


def bake_ao(proxy, size, ao_samples=128, ao_distance=3.0):
    """AO alone into a float image of the proxy's islands (as bake_buffers' "ao"): a second pose of the same faces."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    bake = scene.render.bake
    bake.margin, bake.margin_type, bake.use_clear = BAKE_MARGIN, "EXTEND", True
    target = new_image("bake_target", size)
    dummy = new_image("bake_dummy", 8)
    mat, _, _ = bake_material("bake_main_nodes", target)
    dmat, _, _ = bake_material("bake_dummy_nodes", dummy)
    me = proxy.data
    placeholders = list(me.materials)
    me.materials[0], me.materials[1] = mat, dmat
    for m in placeholders:
        if m.users == 0:
            bpy.data.materials.remove(m)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    proxy.select_set(True)
    bpy.context.view_layer.objects.active = proxy
    scene.cycles.samples = ao_samples
    scene.world.light_settings.distance = ao_distance
    bpy.ops.object.bake(type="AO")
    ao = pixels(target)[..., 0].copy()
    for m in (mat, dmat):
        bpy.data.materials.remove(m)
    bpy.data.images.remove(dummy)
    bpy.data.images.remove(target)
    return ao


def bake_buffers(proxy, size, ao_samples=128, ao_distance=3.0):
    """Bake world position, world normal, paint class, pointiness and AO into float images; returns arrays of
    shape (size, size, ...) with row 0 at the bottom (Blender's pixel order) and the valid mask."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    bake = scene.render.bake
    bake.margin, bake.margin_type, bake.use_clear = BAKE_MARGIN, "EXTEND", True
    target = new_image("bake_target", size)
    dummy = new_image("bake_dummy", 8)
    mat, emit, tex = bake_material("bake_main_nodes", target)
    dmat, demit, _ = bake_material("bake_dummy_nodes", dummy)
    me = proxy.data
    placeholders = list(me.materials)
    me.materials[0], me.materials[1] = mat, dmat
    for m in placeholders:
        if m.users == 0:
            bpy.data.materials.remove(m)
    nt = mat.node_tree
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "clsf"
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    proxy.select_set(True)
    bpy.context.view_layer.objects.active = proxy

    out = {}
    for key, socket in (("pos", geo.outputs["Position"]), ("nrm", geo.outputs["Normal"]),
                        ("cls", attr.outputs["Color"]), ("curv", geo.outputs["Pointiness"])):
        link = nt.links.new(socket, emit.inputs["Color"])
        scene.cycles.samples = 1
        bpy.ops.object.bake(type="EMIT")
        out[key] = pixels(target).copy()
        nt.links.remove(link)
    # the valid texels: covered by an island or its margin (cls is at least 1 on every painted class)
    scene.cycles.samples = ao_samples
    scene.world.light_settings.distance = ao_distance
    bpy.ops.object.bake(type="AO")
    out["ao"] = pixels(target).copy()
    bake.margin = 0
    link = nt.links.new(attr.outputs["Color"], emit.inputs["Color"])
    scene.cycles.samples = 1
    bpy.ops.object.bake(type="EMIT")
    island = pixels(target)[..., 0] > 0.5
    nt.links.remove(link)
    bake.margin = BAKE_MARGIN
    for m in (mat, dmat):
        bpy.data.materials.remove(m)
    bpy.data.images.remove(dummy)
    bpy.data.images.remove(target)
    valid = np.rint(out["cls"][..., 0]) > 0
    return {"pos": out["pos"][..., :3], "nrm": out["nrm"][..., :3], "cls": np.rint(out["cls"][..., 0]).astype(int),
            "group": np.rint(out["cls"][..., 1]).astype(int), "moving": out["cls"][..., 2] > 0.5, "curv": out["curv"][..., 0], "ao": out["ao"][..., 0], "valid": valid, "island": island}


def save_image(arr, path, srgb=False):
    """Write an (h, w, 3 or 4) float array, row 0 at the bottom, to an 8-bit PNG. srgb: the values are already
    sRGB-encoded (albedo); otherwise they are data. Returns the path."""
    from .paint import to_host
    arr = to_host(arr)
    h, w = arr.shape[:2]
    ch = arr.shape[2]
    img = bpy.data.images.new(path.stem, w, h, alpha=(ch == 4), float_buffer=False)
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    px = np.ones((h, w, 4), np.float32)
    px[..., :ch] = arr
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw, img.file_format = str(path), "PNG"
    img.save()
    bpy.data.images.remove(img)
    return path


def load_image(path, data=True):
    img = bpy.data.images.load(str(path), check_existing=False)
    img.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return img


def text_mask(body, px_height=48, font_path=None):
    """Rasterise text with Blender's bundled font (OFL) to a mask whose rows run bottom-up: px_height pixels per
    unit of font size, about 1.4 times the cap height."""
    cu = bpy.data.curves.new("stencil", "FONT")
    cu.body = body
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    if font_path:
        cu.font = bpy.data.fonts.load(font_path, check_existing=True)
    obj = bpy.data.objects.new("stencil", cu)
    bpy.context.scene.collection.objects.link(obj)
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    co = np.array([v.co[:2] for v in me.vertices])
    tris = np.array([lt.vertices[:] for lt in me.loop_triangles])
    ev.to_mesh_clear()
    bpy.data.objects.remove(obj)
    bpy.data.curves.remove(cu)
    return raster_triangles(co, tris, px_height, pad=0.15)


def raster_triangles(co, tris, px_per_unit, pad=0.1, ss=3):
    """Fill 2D triangles into a coverage mask (supersampled ss x ss), the drawing centred with pad units round it."""
    lo, hi = co.min(axis=0) - pad, co.max(axis=0) + pad
    W = int(np.ceil((hi[0] - lo[0]) * px_per_unit * ss))
    H = int(np.ceil((hi[1] - lo[1]) * px_per_unit * ss))
    # centre the box on the origin so a decal's centre is the drawing's centre
    c = (lo + hi) / 2
    half = np.array([W, H]) / (2 * px_per_unit * ss)
    pts = (co - (c - half)) * px_per_unit * ss
    mask = np.zeros((H, W), bool)
    for t in tris:
        a, b, d = pts[t]
        x0, y0 = np.floor(np.minimum(np.minimum(a, b), d)).astype(int)
        x1, y1 = np.ceil(np.maximum(np.maximum(a, b), d)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W - 1), min(y1, H - 1)
        if x1 < x0 or y1 < y0:
            continue
        x, y = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        e = [(q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]) for p, q in ((b, d), (d, a), (a, b))]
        hit = ((e[0] >= 0) & (e[1] >= 0) & (e[2] >= 0)) | ((e[0] <= 0) & (e[1] <= 0) & (e[2] <= 0))
        mask[y0:y1 + 1, x0:x1 + 1] |= hit
    H2, W2 = H // ss, W // ss
    return mask[:H2 * ss, :W2 * ss].reshape(H2, ss, W2, ss).mean(axis=(1, 3))
