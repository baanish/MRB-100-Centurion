"""The flight deck's switch kit: a guarded arming switch (a red flip cover over a hatched plate, after the KR-67's
master arm), a bat toggle, a rotary knob, a pushbutton, a breaker button, and a display bezel with its row of keys for
each page shape, each modelled and textured once on the 2048 kit atlas (Centurion_cockpit_kit) and placed as copies
sharing those UVs wherever the deck has one (flightdeck_detail's toggle, guarded_toggle, knob and button;
flightdeck.build_displays' bezels).

A piece is modelled in its own frame: base at the origin, its surface's normal +Z, "ahead" (where a lever leans, a
knob's pointer, the cover's free end) +Y. Kit.place maps that frame onto a surface point's (side, ahead, up) basis; the
bezels are modelled centred straight ahead and turned about the panel's axis to their displays (Kit.place_turned)."""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import flightdeck_detail as fdd
from m4 import surface as sf
from m4 import texture

KIT_SLOT = "Centurion_cockpit_kit"
KIT_ATLAS = 2048
KIT_SPACING = 0.5  # the library lays the switches out this far apart for the bake
BEZEL_STACK = 0.6  # and stacks the bezels this far apart
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
CANON = sf.basis(Z, Y)  # (side, ahead, up) of a piece's own frame
KNOB_R, KNOB_H = 0.014, 0.020
SWITCH_WEIGHT = 2.0  # switches get twice the bezel's texels per metre: their detail is finer


# ---------------- the pieces, modelled once ----------------
def model_toggle(part, fd):
    """A bat toggle: a washer, a hex nut and a threaded bush, a tapered lever leaning 25 deg ahead, a ball end."""
    side, f, u = CANON
    o = Vector()
    sf.revolve_axis(part, ((0.0095, -0.0005), (0.0095, 0.0008), (0.0068, 0.0008), (0.0068, 0.0045), (0.0045, 0.0065)), o, u,
                    6, fd.ATLAS_SLOT, fd.METAL, ref=side)
    a = math.radians(25.0)
    d = (u * math.cos(a) + f * math.sin(a)).normalized()
    root = o + u * 0.0065
    sf.revolve_axis(part, ((0.003, 0.0), (0.0019, 0.022)), root, d, 6, fd.ATLAS_SLOT, fd.METAL, ref=side)
    sf.revolve_axis(part, ((0.0, -0.0035), (0.0037, 0.0), (0.0, 0.0035)), root + d * 0.022, d, 6, fd.ATLAS_SLOT, fd.METAL, ref=side)


def model_knob(part, fd):
    """A chunky rotary knob: a wide skirt, a knurled body stepped in from it, chamfered at its top, a pointer ridge."""
    side, f, u = CANON
    r, h = KNOB_R, KNOB_H
    sf.revolve_axis(part, ((r * 1.35, 0.0), (r * 1.35, h * 0.15), (r * 1.2, h * 0.22), (r, h * 0.26), (r, h * 0.84),
                           (r * 0.82, h), (0.0, h)), Vector(), u, 12, fd.ATLAS_SLOT, fd.KNOB, ref=side)
    sf.box(part, u * (h * 0.62) + f * (r * 0.98), (side, f, u), (0.003, 0.004, h * 0.66), fd.ATLAS_SLOT, fd.METAL)


def model_button(part, fd):
    """A pushbutton: a square bezel ring on the panel and a cap standing BUTTON_H proud, its top flat for a legend."""
    side, f, u = CANON
    sf.box(part, u * 0.001, (side, f, u), (0.018, 0.016, 0.002), fd.ATLAS_SLOT, fd.BEZEL)
    fdd.cbox(part, fd, u * (fdd.BUTTON_H / 2), (side, f, u), (0.0135, 0.0115, fdd.BUTTON_H), fd.KNOB, c=0.0009)


def model_breaker(part, fd):
    """A circuit breaker's button: a short black cap with a shoulder, standing from a breaker field's plate."""
    side, f, u = CANON
    sf.revolve_axis(part, ((0.0058, 0.0), (0.0058, 0.0045), (0.0044, 0.0078), (0.0, 0.0088)), Vector(), u, 6, fd.ATLAS_SLOT,
                    fd.KNOB, ref=side)


def model_guard(part, fd):
    """The arming switch: a hatched plate, a hinge barrel across its aft end on two brackets, and a red flip cover
    over the toggle, its sides rounded into its top, a lip at its free end to lift it by."""
    side, f, u = CANON
    fdd.cbox(part, fd, f * 0.004 + u * 0.0015, (side, f, u), (0.040, 0.058, 0.003), fd.HAZARD, c=0.001)
    sec = [(-0.0130, 0.0030), (-0.0130, 0.0120), (-0.0112, 0.0155), (-0.0070, 0.0170), (0.0070, 0.0170), (0.0112, 0.0155),
           (0.0130, 0.0120), (0.0130, 0.0030)]
    rows = [[side * x + f * y + u * z for x, z in sec] for y in (-0.016, 0.006, 0.020)]
    g = sf.Grid(part.bm, rows, loop=False)
    ends = [part.bm.faces.new(g.V[0][::-1]), part.bm.faces.new(g.V[-1])]
    fs = g.faces() + ends
    centre = f * 0.002 + u * 0.008
    for face in fs:
        face.normal_update()
        if face.normal.dot(face.calc_center_median() - centre) < 0:
            face.normal_flip()
    part.tag(fs, fd.ATLAS_SLOT, fd.HANDLE)
    fdd.cbox(part, fd, f * 0.0215 + u * 0.0135, (side, f, u), (0.026, 0.004, 0.008), fd.HANDLE, c=0.0008)
    sf.revolve_axis(part, ((0.0036, -0.015), (0.0036, 0.015)), f * -0.0185 + u * 0.0065, side, 10, fd.ATLAS_SLOT, fd.METAL)
    for k in (-1, 1):
        fdd.cbox(part, fd, side * (k * 0.0165) + f * -0.0185 + u * 0.0045, (side, f, u), (0.004, 0.009, 0.006), fd.METAL, c=0.0008)


def model_bezel(part, fd, key):
    """A display's bezel, centred straight ahead on the panel: its opening the page key's shape (fd.display_opening), a
    housing fd.BEZEL_HOUSING deep with fd.BEZEL_SIDE frames at its sides, 3 cm under the opening for its keys and 2 cm
    over it, its outer edges chamfered, an inner chamfer down to short walls round the glass (fd.DISPLAY_GLASS_R); a
    screw at each corner and six keys along its bottom frame."""
    w = fd.display_opening(key)
    dw = math.degrees(w / fd.PANEL_R)
    z0, z1 = fd.DISPLAY_Z
    R, D, c = fd.PANEL_R, fd.BEZEL_HOUSING, 0.005
    half = math.degrees((w / 2 + fd.BEZEL_SIDE) / R)
    outer, inner = (-half, half, z0 - 0.03, z1 + 0.02), (-dw / 2, dw / 2, z0, z1)

    def rect(rc, d, r):
        p0, p1, q0, q1 = rc
        dm, dp = math.degrees(d[0] / R), math.degrees(d[1] / R)
        return [fd.cyl(p1 + dp, q0 - d[2], r), fd.cyl(p0 - dm, q0 - d[2], r), fd.cyl(p0 - dm, q1 + d[3], r),
                fd.cyl(p1 + dp, q1 + d[3], r)]

    prof = [rect(outer, (0, 0, 0, 0), R), rect(outer, (0, 0, 0, 0), R - D + c), rect(outer, (-c, -c, -c, -c), R - D),
            rect(inner, (0.003,) * 4, R - D), rect(inner, (0.0,) * 4, R - D + 0.003), rect(inner, (0.0,) * 4, fd.DISPLAY_GLASS_R)]
    bm = part.bm
    housing = []
    for k in range(len(prof) - 1):
        for i in range(4):
            j = (i + 1) % 4
            housing.append(bm.faces.new([bm.verts.new(q) for q in (prof[k][i], prof[k][j], prof[k + 1][j], prof[k + 1][i])]))
    front = housing[8]
    front.normal_update()
    if front.normal.dot(fd.toward_point(front.calc_center_median())) < 0:
        for face in housing:
            face.normal_flip()
    part.tag(housing, fd.ATLAS_SLOT, fd.BEZEL)
    rr = R - D
    for sa in (-1, 1):
        for zz in (z0 - 0.017, z1 + 0.0095):
            p = fd.cyl(sa * math.degrees((w / 2 + fd.BEZEL_SIDE / 2) / R), zz, rr)
            sf.revolve_axis(part, ((0.0026, 0.0), (0.0024, 0.0011), (0.0, 0.0018)), p, fd.toward_point(p), 6, fd.ATLAS_SLOT, fd.METAL)
    for k in range(6):
        a = dw / 2 - dw * (k + 0.5) / 6
        r = math.radians(a)
        along, inward = Vector((math.cos(r), math.sin(r), 0)), Vector((-math.sin(r), math.cos(r), 0))
        fdd.cbox(part, fd, fd.cyl(a, z0 - 0.017, rr - 0.004), (along, inward, Z), (min(0.022, w / 6 - 0.003), 0.008, 0.011), fd.KNOB,
                 c=0.0012)


def kit_models(fd):
    """The kit's pieces by name: the switches, and a bezel for each page shape the displays carry (bezel_<page>)."""
    out = {"toggle": model_toggle, "knob": model_knob, "button": model_button, "guard": model_guard, "breaker": model_breaker}
    for key in dict.fromkeys(fd.DISPLAY_ORDER):
        out["bezel_" + key] = lambda part, fd, key=key: model_bezel(part, fd, key)
    return out


class Kit:
    """The pieces' geometry and UVs once laid out on the kit atlas; place copies them onto a part under construction."""

    def __init__(self, fd):
        self.fd = fd
        self.pieces = {}
        self.library = None
        self.offsets = {}
        self.models = kit_models(fd)
        lib = bmesh.new()
        cls_layer = lib.faces.layers.int.new("cls")
        ranges = {}
        bezels = 0
        for i, (name, model) in enumerate(self.models.items()):
            part = sf.Part("kit_" + name, (fd.ATLAS_SLOT,))
            model(part, fd)
            bm = part.bm
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
            bm.verts.index_update()
            verts = [v.co.copy() for v in bm.verts]
            faces = [[v.index for v in f.verts] for f in bm.faces]
            cls = [f[part.cls] for f in bm.faces]
            bm.free()
            if name.startswith("bezel"):  # the bezels where they are modelled, stacked apart for the bake
                off = Vector((0.0, 0.0, BEZEL_STACK * bezels))
                bezels += 1
            else:
                off = Vector((KIT_SPACING * (i + 1), 0.0, 0.0))
            self.offsets[name] = off
            vs = [lib.verts.new(v + off) for v in verts]
            start = len(lib.faces)
            for fi, idx in enumerate(faces):
                face = lib.faces.new([vs[k] for k in idx])
                face[cls_layer] = cls[fi]
            ranges[name] = (start, len(lib.faces))
            self.pieces[name] = {"verts": verts, "faces": faces, "cls": cls,
                                 "bounds": ([min(v[k] for v in verts) + off[k] for k in range(3)],
                                            [max(v[k] for v in verts) + off[k] for k in range(3)])}
        me = bpy.data.meshes.new("kit_library")
        lib.to_mesh(me)
        lib.free()
        me.materials.append(bpy.data.materials.get(KIT_SLOT) or bpy.data.materials.new(KIT_SLOT))
        obj = bpy.data.objects.new("kit_library", me)
        bpy.context.scene.collection.objects.link(obj)
        self.library = obj
        self.density = self._unwrap(obj, ranges)
        uv = me.uv_layers["UVMap"].data
        for name, (a, b) in ranges.items():
            self.pieces[name]["uvs"] = [[tuple(uv[li].uv) for li in me.polygons[i].loop_indices] for i in range(a, b)]

    def _unwrap(self, obj, ranges):
        """Smart-project the library, grow the switches' islands SWITCH_WEIGHT times, pack onto the atlas; returns
        {piece: px per metre}."""
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        me = obj.data
        me.uv_layers.new(name="UVMap")
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(50), island_margin=0.0, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        uv = bm.loops.layers.uv["UVMap"]
        import flightdeck_uv as fuv
        bezel_ranges = [r for n, r in ranges.items() if n.startswith("bezel")]
        for island in fuv._islands(bm, uv, list(bm.faces)):
            k = 1.0 if any(a <= island[0].index < b for a, b in bezel_ranges) else SWITCH_WEIGHT
            w = sum(f.calc_area() for f in island)
            a = sum(fuv._uv_area([l[uv].uv for l in f.loops]) for f in island)
            s = math.sqrt(w / a) * k if a > 1e-12 else 1.0
            loops = [l for f in island for l in f.loops]
            c = sum((l[uv].uv for l in loops), Vector((0, 0))) / len(loops)
            for l in loops:
                l[uv].uv = c + (l[uv].uv - c) * s
        bm.to_mesh(me)
        bm.free()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.context.scene.tool_settings.use_uv_select_sync = True
        bpy.ops.uv.pack_islands(rotate=True, rotate_method="ANY", scale=True, shape_method="CONCAVE", margin_method="FRACTION",
                                margin=4 / KIT_ATLAS)
        bpy.ops.object.mode_set(mode="OBJECT")
        out = {}
        uvd = me.uv_layers["UVMap"].data
        for name, (a, b) in ranges.items():
            w = sum(me.polygons[i].area for i in range(a, b))
            u = sum(fuv._uv_area([uvd[li].uv for li in me.polygons[i].loop_indices]) for i in range(a, b))
            out[name] = round(KIT_ATLAS * math.sqrt(u / w), 1)
        obj.select_set(False)
        return out

    def _add(self, part, name, xf):
        p = self.pieces[name]
        bm = part.bm
        uv = bm.loops.layers.uv.verify()
        vs = [bm.verts.new(xf @ v) for v in p["verts"]]
        made = []
        for idx, uvs, cls in zip(p["faces"], p["uvs"], p["cls"]):
            f = bm.faces.new([vs[k] for k in idx])
            for loop, t in zip(f.loops, uvs):
                loop[uv].uv = t
            part.tag([f], KIT_SLOT, cls)
            made.append(f)
        return made

    def place(self, part, name, base, up, ahead, scale=1.0):
        """A copy of a piece standing on a surface point base, its +Z along up and +Y toward ahead."""
        side, f, u = sf.basis(up, ahead)
        cs, cf, cu = CANON
        rot = Matrix((side, f, u)).transposed() @ Matrix((cs, cf, cu))
        return self._add(part, name, Matrix.Translation(base) @ rot.to_4x4() @ Matrix.Scale(scale, 4))

    def place_turned(self, part, name, angle_deg):
        """A copy of a piece modelled in the deck's frame, turned angle_deg about the panel's axis."""
        ax, ay = self.fd.band_axis()
        pivot = Vector((ax, ay, 0.0))
        xf = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(angle_deg), 4, "Z") @ Matrix.Translation(-pivot)
        return self._add(part, name, xf)

    def paint(self, folder):
        """Bake the library and paint the kit atlas: cockpit_kit_{b,m,n,ao}.png. The library leaves the scene after."""
        import flightdeck_paint as fp
        obj = self.library
        proxy = texture.make_proxy([obj], KIT_SLOT, {})
        buf = texture.bake_buffers(proxy, KIT_ATLAS, ao_samples=64, ao_distance=0.05)
        bpy.data.objects.remove(proxy)
        piece = np.full(buf["cls"].shape, -1)
        pos = buf["pos"]
        names = list(self.models)
        for i, name in enumerate(names):
            lo, hi = self.pieces[name]["bounds"]
            on = np.all((pos >= np.asarray(lo) - 0.005) & (pos <= np.asarray(hi) + 0.005), axis=-1)
            piece[on] = i
        dens = np.full(buf["cls"].shape, min(self.density.values()), float)
        for i, name in enumerate(names):
            dens[piece == i] = self.density[name]
        cv = fp.Atlas(buf, dens, self.fd.Y0)
        cv.piece = piece[buf["valid"]]
        paint_kit(cv, self, names)
        fp.finish(cv, KIT_SLOT)
        maps = fp.save_maps(cv, buf, dens, folder, "cockpit_kit", KIT_ATLAS)
        bpy.data.objects.remove(obj)
        self.library = None
        return maps


def paint_kit(cv, kit, names):
    """The pieces' own paint over the class colours: the cover's gloss red and ribbed top, the plate's white and black
    hatching, the knob's knurled body and white pointer, the toggle's brushed lever and darker nut, the keys' dark caps,
    the bezel's satin black."""
    import flightdeck_paint as fp
    fd = kit.fd
    idx = {n: i for i, n in enumerate(names)}

    def local(name):
        on = cv.piece == idx[name]
        return on, cv.pos - np.asarray(kit.offsets[name])

    on, p = local("guard")
    red = on & cv.on(fd.HANDLE)
    cv.paint(red.astype(float), rgb=fp.srgb(176, 22, 18), smooth=0.62)
    ribs = red & (cv.nrm[:, 2] > 0.8) & (np.abs(((p[:, 0] / 0.004) % 1.0) - 0.5) < 0.18)
    cv.height += 0.00025 * ribs
    hz = on & cv.on(fd.HAZARD) & (cv.nrm[:, 2] > 0.8)
    band = (((p[:, 0] + p[:, 1]) / 0.008) % 1.0) < 0.5
    border = (np.abs(p[:, 0]) > 0.017) | (np.abs(p[:, 1] - 0.004) > 0.026)
    cv.paint((hz & border & band).astype(float), rgb=fp.srgb(16, 16, 16), smooth=0.3)
    cv.paint((hz & border & ~band).astype(float), rgb=fp.srgb(214, 212, 204), smooth=0.3)
    cv.paint((hz & ~border).astype(float), rgb=fp.srgb(20, 20, 21), smooth=0.35)
    on, p = local("knob")
    k = on & cv.on(fd.KNOB)
    ang = np.arctan2(p[:, 1], p[:, 0])
    side = k & (np.abs(cv.nrm[:, 2]) < 0.5) & (p[:, 2] > KNOB_H * 0.27)
    knurl = side & (np.abs(((ang * 30 / math.pi) % 1.0) - 0.5) < 0.22)
    cv.height += 0.0003 * knurl
    cv.albedo *= (1 - 0.35 * knurl)[:, None]
    top = k & (cv.nrm[:, 2] > 0.8)
    pointer = top & (np.abs(p[:, 0]) < 0.0009) & (p[:, 1] > 0.002)
    cv.paint(pointer.astype(float), rgb=fp.srgb(220, 218, 210), smooth=0.4)
    on, p = local("toggle")
    nut = on & (p[:, 2] < 0.0068)
    cv.paint(nut * 0.6, rgb=fp.srgb(110, 112, 116), smooth=0.5)
    on, p = local("button")
    cv.paint((on & cv.on(fd.KNOB)) * 0.7, rgb=fp.srgb(40, 41, 43), smooth=0.45)
    on, p = local("breaker")
    cv.paint((on & (np.abs(p[:, 2] - 0.0035) < 0.0009)).astype(float), rgb=fp.srgb(206, 204, 196), smooth=0.4)
    for name in names:
        if name.startswith("bezel"):
            on, p = local(name)
            cv.paint((on & cv.on(fd.BEZEL)) * 1.0, rgb=fp.srgb(26, 27, 29), smooth=0.48)
            cv.paint((on & cv.on(fd.KNOB)) * 1.0, rgb=fp.srgb(38, 39, 41), smooth=0.45)
