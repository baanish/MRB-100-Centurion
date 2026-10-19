"""Procedural paint in numpy (art.md section 4, "Procedural texturing from Python").

A Canvas holds one value per atlas texel that some island covers, read from the baked buffers: world position,
world normal, paint class, AO and curvature. Everything painted is a function of where the texel sits on the
aircraft, never of where its island landed in the atlas, so a repack only needs a rebake.

Layouts address the hull by (station, arc): station in metres from the nose, arc the signed girth in metres from the
top centreline, positive toward +X (the left wing). Primitives draw lines, rounded panels, fastener rows, polygons
and stencils into the albedo, height, smoothness and metal layers."""

import math
import os
import sys
from pathlib import Path

import numpy as np

numpy = np
DEVICE = "CPU (NumPy)"


def to_host(value):
    return value.get() if hasattr(value, "get") else value


class GpuArrays:
    """CuPy with host constants accepted at the paint boundary, like NumPy."""

    def __init__(self, cupy):
        self.cupy = cupy

    # Layout loop bounds must match NumPy exactly: an ulp can change a rib's inclusion test.
    arange = staticmethod(numpy.arange)
    linspace = staticmethod(numpy.linspace)

    def asarray(self, value, dtype=None):
        if isinstance(value, (tuple, list)) and any(isinstance(v, self.cupy.ndarray) for v in value):
            stacked = self.cupy.stack([self.asarray(v) for v in value])
            return stacked.astype(dtype, copy=False) if dtype else stacked
        return self.cupy.asarray(value, dtype=dtype)

    array = asarray

    def interp(self, x, xp, fp):
        if numpy.isscalar(x):
            return numpy.interp(x, to_host(xp), to_host(fp))
        return self.cupy.interp(self.asarray(x), self.asarray(xp), self.asarray(fp))

    def isin(self, values, classes):
        return self.cupy.isin(values, self.asarray(classes))

    def digitize(self, values, bins):
        return self.cupy.digitize(values, self.asarray(bins))

    def min(self, values, **kwargs):
        return self.cupy.min(self.asarray(values), **kwargs)

    def concatenate(self, values, **kwargs):
        return self.cupy.concatenate([self.asarray(value) for value in values], **kwargs)

    def __getattr__(self, name):
        return getattr(self.cupy, name)


def select_backend():
    """The running game owns the GPU. CENTURION_PAINT_CPU=1 also forces the reference path."""
    global np, DEVICE
    from . import render
    np, DEVICE = numpy, "CPU (NumPy)"
    if os.environ.get("CENTURION_PAINT_CPU") == "1" or render.game_running():
        return DEVICE
    site = Path(__file__).resolve().parents[3] / ".cache" / "blender_site"
    if site.is_dir() and str(site) not in sys.path:
        sys.path.insert(0, str(site))
    try:
        import cupy
        if cupy.cuda.runtime.getDeviceCount():
            cupy.arange(1).sum().item()  # Compile before choosing the backend; a broken runtime falls back.
            np = GpuArrays(cupy)
            DEVICE = cupy.cuda.runtime.getDeviceProperties(cupy.cuda.Device().id)["name"].decode() + " (CuPy)"
    except (ImportError, RuntimeError, OSError) as exc:
        print(f"Paint uses NumPy: {exc}")
    print(f"Paint device: {DEVICE}")
    return DEVICE


def synchronize():
    if isinstance(np, GpuArrays):
        np.cupy.cuda.get_current_stream().synchronize()


def section_plane(coords, pos):
    x = np.abs(pos[:, 0]) if coords.axis is None else (pos - np.asarray(coords.origin)) @ np.asarray(coords.axis)
    le = np.stack([np.interp(x, coords.xs, coords.le[:, i]) for i in range(3)], axis=1)
    return (pos - le) @ np.asarray(coords.cdir), (pos - le) @ np.asarray(coords.tdir)


def locate_section(coords, pos, nrm):
    x = np.abs(pos[:, 0]) if coords.axis is None else (pos - np.asarray(coords.origin)) @ np.asarray(coords.axis)
    c = np.interp(x, coords.xs, coords.c)
    return x, section_plane(coords, pos)[0] / c, c, (nrm @ np.asarray(coords.tdir)) > 0


def fairing_locate(coords, pos):
    """Interpolate batches sharing a station row, rather than calling interp for every texel."""
    s = pos[:, 1] + coords.Y0
    i, t = coords.index(s)
    if isinstance(np, GpuArrays):
        lengths = numpy.array([len(row) for row in coords.x])
        width = int(lengths.max())
        xs, arcs = (numpy.zeros((len(lengths), width)) for _ in range(2))
        for row, length in enumerate(lengths):
            xs[row, :length], arcs[row, :length] = coords.x[row], coords.arc[row]
        xs, arcs, lengths = np.asarray(xs), np.asarray(arcs), np.asarray(lengths)
        x = np.abs(pos[:, 0]).astype(float)

        def interpolate(rows):
            low, high = np.zeros(len(i), int), lengths[rows] - 1
            for _ in range(width.bit_length()):
                mid = (low + high) // 2
                right = x >= xs[rows, mid]
                low = np.where(right, mid, low)
                high = np.where(right, high, mid)
            high = np.minimum(low + 1, lengths[rows] - 1)
            low = np.maximum(high - 1, 0)
            x0, x1 = xs[rows, low], xs[rows, high]
            y0, y1 = arcs[rows, low], arcs[rows, high]
            y = y0 + ((y1 - y0) / (x1 - x0)) * (x - x0)
            return np.where(x <= xs[rows, 0], arcs[rows, 0], np.where(x >= xs[rows, lengths[rows] - 1], arcs[rows, lengths[rows] - 1], y))

        arc = interpolate(i) * (1 - t) + interpolate(i + 1) * t
        return s, np.sign(pos[:, 0] + 1e-12) * arc
    order = numpy.argsort(i, kind="stable")
    cuts = numpy.r_[0, numpy.flatnonzero(numpy.diff(i[order])) + 1, len(i)]
    a, b = numpy.empty(len(i)), numpy.empty(len(i))
    for start, end in zip(cuts[:-1], cuts[1:]):
        selected = order[start:end]
        row = i[selected[0]]
        x = numpy.abs(pos[selected, 0])
        a[selected] = numpy.interp(x, coords.x[row], coords.arc[row])
        b[selected] = numpy.interp(x, coords.x[row + 1], coords.arc[row + 1])
    arc = numpy.sign(pos[:, 0] + 1e-12) * (a * (1 - t) + b * t)
    return np.asarray(s), np.asarray(arc)

from .surface import DOOR, FITTING, FRAME, HULL, RADOME

# Well and bay cavities read as shadow through closed-door gaps, without edge wear.
INTERIOR = 6

# Paint, sRGB 0..1: a matte mid grey close to the stock default skin (art.md: means 91 to 106 of 255).
PAINT = {HULL: (0.38, 0.39, 0.405), RADOME: (0.33, 0.335, 0.34), FRAME: (0.10, 0.105, 0.11),
         DOOR: (0.38, 0.39, 0.405), FITTING: (0.37, 0.38, 0.39), INTERIOR: (0.10, 0.105, 0.11)}
SMOOTH = {HULL: 0.42, RADOME: 0.5, FRAME: 0.3, DOOR: 0.42, FITTING: 0.4, INTERIOR: 0.3}


class FuselageCoords:
    """Station, angle and arc of any point near the fuselage surface (the blockout's superellipse sections, chine
    ignored): a table of girth against angle per station, inverted per texel."""

    def __init__(self, bl, ds=0.02, dd=0.5):
        self.bl = bl
        stations = numpy.arange(0.0, bl.LENGTH + ds, ds)
        self.s = np.asarray(stations)
        prof = np.array([bl.fus_profile(max(s, 1e-4)) for s in stations])
        self.w, self.top, self.bot = prof[:, 0], prof[:, 1], prof[:, 2]
        self.deg = np.asarray(numpy.arange(0.0, 180.0 + dd, dd))
        a = np.radians(self.deg)
        P = bl.FUS_P
        sx, cz = np.sin(a) ** (2 / P), np.sign(np.cos(a)) * np.abs(np.cos(a)) ** (2 / P)
        h = (self.top - self.bot) / 2
        x = self.w[:, None] * sx[None, :]
        z = h[:, None] * cz[None, :]
        seg = np.hypot(np.diff(x, axis=1), np.diff(z, axis=1))
        self.arc = np.concatenate([np.zeros((len(self.s), 1)), np.cumsum(seg, axis=1)], axis=1)
        self.ds, self.dd = ds, dd

    def _profile(self, s):
        i = np.clip(s / self.ds, 0, len(self.s) - 1.001)
        i0 = i.astype(int)
        t = i - i0
        lerp = lambda arr: arr[i0] * (1 - t) + arr[i0 + 1] * t
        return lerp(self.w), lerp(self.top), lerp(self.bot)

    def arc_at(self, s, deg):
        """Arc of (station, angle) pairs, arrays or scalars; the sign follows the angle (-180..180)."""
        s, deg = np.asarray(s, float), np.asarray(deg, float)
        d = np.abs(((deg + 180.0) % 360.0) - 180.0)
        i = np.clip(s / self.ds, 0, len(self.s) - 1.001)
        j = np.clip(d / self.dd, 0, len(self.deg) - 1.001)
        i0, j0 = i.astype(int), j.astype(int)
        ti, tj = i - i0, j - j0
        A = self.arc
        v = (A[i0, j0] * (1 - ti) * (1 - tj) + A[i0 + 1, j0] * ti * (1 - tj)
             + A[i0, j0 + 1] * (1 - ti) * tj + A[i0 + 1, j0 + 1] * ti * tj)
        return np.sign(((deg + 180.0) % 360.0) - 180.0 + 1e-12) * v

    def locate(self, pos):
        """(station, angle, arc) of world positions."""
        s = pos[:, 1] + self.bl.Y0
        w, top, bot = self._profile(s)
        zc, h = (top + bot) / 2, np.maximum((top - bot) / 2, 1e-3)
        P = self.bl.FUS_P
        u = np.clip(pos[:, 0] / np.maximum(w, 1e-3), -1.5, 1.5)
        v = np.clip((pos[:, 2] - zc) / h, -1.5, 1.5)
        deg = np.degrees(np.arctan2(np.sign(u) * np.abs(u) ** (P / 2), np.sign(v) * np.abs(v) ** (P / 2)))
        return s, deg, self.arc_at(s, deg)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def value_noise(p, scale, seed=0):
    """Smooth 3D value noise in 0..1 at points p (n, 3), features about scale metres across."""
    q = p / scale + seed * 17.13
    i = np.floor(q).astype(np.int64)
    f = q - i
    f = f * f * (3 - 2 * f)

    def h(ix, iy, iz):
        n = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
        n = (n ^ (n >> 13)) * 1274126177
        return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                wgt = ((f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2]))
                out = out + wgt * h(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz)
    return out


def fbm(p, scale, octaves=3, seed=0):
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total = total + amp * value_noise(p, scale / 2 ** o, seed + o)
        norm += amp
        amp *= 0.5
    return total / norm


def seg_dist(u, v, p0, p1):
    """Distance from points (u, v) to the segment p0-p1, and the position along it in metres."""
    (u0, v0), (u1, v1) = p0, p1
    du, dv = u1 - u0, v1 - v0
    L2 = du * du + dv * dv
    t = np.clip(((u - u0) * du + (v - v0) * dv) / L2, 0.0, 1.0)
    return np.hypot(u - (u0 + t * du), v - (v0 + t * dv)), t * math.sqrt(L2)


def rrect_sdf(u, v, s0, s1, a0, a1, r):
    cu, cv = (s0 + s1) / 2, (a0 + a1) / 2
    hu, hv = abs(s1 - s0) / 2 - r, abs(a1 - a0) / 2 - r
    qu, qv = np.abs(u - cu) - hu, np.abs(v - cv) - hv
    return np.hypot(np.maximum(qu, 0), np.maximum(qv, 0)) + np.minimum(np.maximum(qu, qv), 0) - r


def panel_joint_mask(cv, panels):
    """Keep structural joints and their fasteners outside access-panel outlines and rims."""
    distance = np.full(cv.n, np.inf)
    for s0, s1, a0, a1, radius, sides in panels:
        for side in ((1, -1) if sides == 0 else (sides,)):
            v0, v1 = sorted(float(cv.coords.arc_at((s0 + s1) / 2, side * a)) for a in (a0, a1))
            distance = np.minimum(distance, rrect_sdf(cv.s, cv.arc, s0, s1, v0, v1, radius))
    return 1 - cv.fill_coverage(distance - 0.05)


def poly_sdf(u, v, pts):
    """Signed distance to a closed polygon (negative inside)."""
    d = np.full(u.shape, np.inf)
    inside = np.zeros(u.shape, bool)
    n = len(pts)
    for i in range(n):
        (u0, v0), (u1, v1) = pts[i], pts[(i + 1) % n]
        d = np.minimum(d, seg_dist(u, v, (u0, v0), (u1, v1))[0])
        cross = ((v0 > v) != (v1 > v)) & (u < (u1 - u0) * (v - v0) / (v1 - v0 + 1e-12) + u0)
        inside ^= cross
    return np.where(inside, -d, d)


class Canvas:
    """Paint layers over the covered texels. px: texel size in metres (1 / density), the anti-aliasing width."""

    def __init__(self, buffers, coords, px):
        self.xp = np
        buffers = {key: np.asarray(value) for key, value in buffers.items()}
        self.b = buffers
        self.px = px
        self.pos, self.nrm, self.cls = buffers["pos"], buffers["nrm"], buffers["cls"]
        self.n = len(self.cls)
        self.s, self.deg, self.arc = coords.locate(self.pos)
        self.coords = coords
        self.albedo = np.zeros((self.n, 3))
        self.smooth = np.zeros(self.n)
        self.metal = np.full(self.n, 0.03)
        self.height = np.zeros(self.n)
        for c, rgb in PAINT.items():
            m = self.cls == c
            self.albedo[m] = rgb
            self.smooth[m] = SMOOTH[c]

    def on(self, *classes):
        return np.isin(self.cls, classes)

    def coverage(self, d, width):
        """Anti-aliased coverage of a line of width centred at distance d."""
        return np.clip(0.5 + (width / 2 - d) / self.px, 0.0, 1.0)

    def fill_coverage(self, sdf):
        return np.clip(0.5 - sdf / self.px, 0.0, 1.0)

    def paint(self, cov, rgb=None, smooth=None, metal=None, height=None, mask=None):
        if mask is not None:
            cov = cov * mask
        if rgb is not None:
            self.albedo += (np.asarray(rgb) - self.albedo) * cov[:, None]
        if smooth is not None:
            self.smooth += (smooth - self.smooth) * cov
        if metal is not None:
            self.metal += (metal - self.metal) * cov
        if height is not None:
            self.height += height * cov

    def groove(self, d, width=0.016, depth=-0.0035, darken=0.35, mask=None):
        """A panel line: a dark hairline with a groove in the height."""
        cov = self.coverage(d, width)
        if mask is not None:
            cov = cov * mask
        self.albedo *= (1 - darken * cov)[:, None]
        self.smooth -= 0.08 * cov
        self.height += depth * cov

    def fasteners(self, d, along, offset=0.03, pitch=0.09, radius=0.007, mask=None):
        """Rows of fastener heads either side of a line: d its distance field, along the position along it."""
        k = np.round(along / pitch) * pitch
        for o in (-offset, offset) if offset else (0.0,):
            r = np.hypot(d - abs(o), along - k) if o else np.hypot(d, along - k)
            cov = np.clip(0.5 + (radius - r) / self.px, 0, 1)
            if mask is not None:
                cov = cov * mask
            self.height += 0.0012 * cov
            self.albedo *= (1 - 0.12 * cov)[:, None]

    def decal(self, mask_img, centre, px_per_m, axis_u, mask=None, rgb=(0.85, 0.85, 0.82), smooth=None, axis_v=None):
        """Stamp a raster (rows bottom-up, 1 = ink) centred at (station, arc), px_per_m raster pixels to the metre;
        axis_u is the (dstation, darc) unit direction text runs in, and up is axis_u turned toward the top
        centreline, so text reads upright from outside on either side. axis_v overrides up: text whose baseline
        leans in arc (a constant-height run) still wants its glyphs at constant station, not perpendicular."""
        mask_img = np.asarray(mask_img)
        f = int(px_per_m * self.px / 1.5)  # box-filter the raster down to about 1.5 pixels a texel
        if f >= 2:
            hh, ww = (mask_img.shape[0] // f) * f, (mask_img.shape[1] // f) * f
            mask_img = mask_img[:hh, :ww].reshape(hh // f, f, ww // f, f).mean(axis=(1, 3))
            px_per_m /= f
        h, w = mask_img.shape
        au = np.asarray(axis_u, float)
        if axis_v is None:
            av = np.array([-au[1], au[0]])
            if av[1] * np.sign(centre[1] or 1) > 0:
                av = -av
            basis = np.stack([au, av])  # orthonormal: its inverse is its transpose
        else:
            basis = np.linalg.inv(np.column_stack([au, np.asarray(axis_v, float)]))  # (dstation, darc) -> (along, up)
        du, dv = self.s - centre[0], self.arc - centre[1]
        lu = (du * basis[0, 0] + dv * basis[0, 1]) * px_per_m + w / 2
        lv = (du * basis[1, 0] + dv * basis[1, 1]) * px_per_m + h / 2
        inside = (lu >= 0) & (lu < w - 1) & (lv >= 0) & (lv < h - 1)
        if mask is not None:
            inside &= mask.astype(bool)
        cov = np.zeros(self.n)
        x, y = lu[inside], lv[inside]
        x0, y0 = x.astype(int), y.astype(int)
        tx, ty = x - x0, y - y0
        cov[inside] = (mask_img[y0, x0] * (1 - tx) * (1 - ty) + mask_img[y0, x0 + 1] * tx * (1 - ty)
                       + mask_img[y0 + 1, x0] * (1 - tx) * ty + mask_img[y0 + 1, x0 + 1] * tx * ty)
        self.paint(cov, rgb=rgb, smooth=smooth)
        return cov

    def finish(self, ao, curv):
        """Mottling, edge wear and cavity grime over the layout, then clamp."""
        p = self.pos
        mott = fbm(p, 2.5, 3, seed=3) - 0.5
        fine = value_noise(p, 0.35, seed=9) - 0.5
        self.albedo *= (1 + 0.07 * mott + 0.025 * fine)[:, None]
        edges = self.on(DOOR, FITTING)
        convex = smoothstep(0.53, 0.62, curv) * (value_noise(p, 0.08, seed=5) > 0.55) * edges
        self.albedo += 0.07 * convex[:, None]
        grime = smoothstep(0.9, 0.6, ao) * (0.5 + 0.5 * fbm(p, 0.6, 2, seed=11))
        self.albedo = self.albedo * (1 - 0.15 * grime[:, None]) + np.array([0.20, 0.17, 0.13]) * 0.15 * grime[:, None]
        self.smooth -= 0.1 * grime
        under = smoothstep(-0.2, -0.8, self.nrm[:, 2]) * fbm(p * np.array([3.0, 0.4, 3.0]), 1.2, 2, seed=13)
        self.albedo *= (1 - 0.08 * under)[:, None]
        self.albedo = np.clip(self.albedo, 0, 1)
        self.smooth = np.clip(self.smooth, 0.05, 0.95)
        self.metal = np.clip(self.metal, 0, 1)


def normal_from_height(height_img, valid, density):
    """Tangent-space normal map (OpenGL, +V up) from a height image in metres: the UV pixel axes are the tangent
    and bitangent, so the gradient in pixels times the density is the slope."""
    gy, gx = np.gradient(height_img)
    nx, ny = -gx * density, -gy * density
    nz = np.ones_like(nx)
    L = np.sqrt(nx * nx + ny * ny + 1)
    n = np.stack([nx / L, ny / L, nz / L], axis=-1) * 0.5 + 0.5
    n[~valid] = (0.5, 0.5, 1.0)
    return n
