"""Procedural paint in numpy (art.md section 4, "Procedural texturing from Python").

A Canvas holds one value per atlas texel that some island covers, read from the baked buffers: world position,
world normal, paint class, AO and curvature. Everything painted is a function of where the texel sits on the
aircraft, never of where its island landed in the atlas, so a repack only needs a rebake. The exception: a groove's
weight follows its angle to the texel grid (Canvas.line_cover).

Layouts address the hull by (station, arc): station in metres from the nose, arc the signed girth in metres from the
top centreline, positive toward +X (the left wing). Primitives draw lines, rounded panels, fastener rows, polygons
and stencils into the albedo, height, smoothness and metal layers."""

import inspect
import math
import os
import sys
from pathlib import Path

import numpy as np

numpy = np
DEVICE = "CPU (NumPy)"
# every Canvas.decal stamped since import: where it was called, its ink's full area and the area printed on the canvas's
# own texels (less where the stencil runs off them: onto another group's faces, past a mask, off the part)
DECALS = []


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

    def point(self, s, deg):
        """World position of (station, angle) on the section, as locate inverts it."""
        w, top, bot = (to_host(v) for v in self._profile(np.asarray(s, float)))
        a = numpy.radians(deg)
        P = self.bl.FUS_P
        x = w * numpy.sign(numpy.sin(a)) * numpy.abs(numpy.sin(a)) ** (2 / P)
        z = (top + bot) / 2 + (top - bot) / 2 * numpy.sign(numpy.cos(a)) * numpy.abs(numpy.cos(a)) ** (2 / P)
        return numpy.stack([x, numpy.asarray(s, float) - self.bl.Y0 + 0 * x, z], axis=-1)

    def deg_at(self, s, arc):
        """The angle at station s whose girth from the crown is arc (arc >= 0), inverting arc_at."""
        i = min(max(s / self.ds, 0), len(self.s) - 1.001)
        i0, t = int(i), i - int(i)
        row = to_host(self.arc[i0]) * (1 - t) + to_host(self.arc[i0 + 1]) * t
        return float(numpy.interp(arc, row, to_host(self.deg)))

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


def check_seams(seams, outlines, edges, tol=0.005, ends=(0.0, 180.0), across=2.0, fittings=(), fit_across=0.5):
    """A skin layout on one side, in stations and a coordinate round the part (the F-240's panel_checks.py, on the
    layout's data; for the body, degrees from the crown): seams (name, station from, to, round from, to), each a ring
    at one station or a lap at one round value; outlines (access panels, fittings, text) and edges (openings, and where
    another layout carries the seams on) as (name, station from, to, round from, to). Every seam end lies on another
    seam, on an edge or at the round coordinate's ends (for the body the centreline above and below, where the other
    side's seams carry on), so the seams close into panels; every outline clears every seam by 5 cm and `across`,
    inside one sheet. fittings (raised parts on the skin, as the formation light strips) by their footprint's box: none
    crosses a seam (fit_across, round the part: they carry no fastener rows) and each lies either clear of each outline
    or inside it, never across its edge. Raises naming each fault."""
    def on(name, s, a, boxes):
        return any(other != name and s0 - tol <= s <= s1 + tol and a0 - tol <= a <= a1 + tol
                   for other, s0, s1, a0, a1 in boxes)
    faults = [f"{name} stops at station {s}, {a} on no seam or edge" for name, s0, s1, a0, a1 in seams
              for s, a in ((s0, a0), (s1, a1))
              if not (a <= ends[0] + tol or a >= ends[1] - tol or on(name, s, a, seams) or on(name, s, a, edges))]
    faults += [f"{what} ({round(s0, 2)} to {round(s1, 2)}, {round(a0, 1)} to {round(a1, 1)}) crosses {name}"
               for boxes, gap in ((outlines, across), (fittings, fit_across)) for what, s0, s1, a0, a1 in boxes
               for name, l0, l1, b0, b1 in seams if l0 < s1 + 0.05 and l1 > s0 - 0.05 and b0 < a1 + gap and b1 > a0 - gap]
    faults += [f"{what} ({round(s0, 2)} to {round(s1, 2)}, {round(a0, 1)} to {round(a1, 1)}) lies across {name}'s edge"
               for what, s0, s1, a0, a1 in fittings for name, l0, l1, b0, b1 in outlines
               if l0 < s1 + 0.05 and l1 > s0 - 0.05 and b0 < a1 + across and b1 > a0 - across
               and not (l0 + 0.05 <= s0 and s1 <= l1 - 0.05 and b0 + across <= a0 and a1 <= b1 - across)]
    if faults:
        raise ValueError("skin seams: " + "; ".join(faults))


def check_square(coords, boxes, limit=1.0, girth=False):
    """Each outline (name, station from, to, angle from, to; angles from the crown) measured on the body's surface as
    Canvas.square draws it: the angle between each end edge and its station plane, and between each long edge and the
    longeron (the constant angle) at its middle. Raises naming every outline over limit degrees; returns {name: worst}.
    girth: measure them as drawn before Canvas.square, the long edges at the girth of their mid-station."""
    worst, faults = {}, []
    for name, s0, s1, a0, a1 in boxes:
        sm, ang = (s0 + s1) / 2, []
        for a in (a0, a1):
            g = float(coords.arc_at(sm, a))
            d0, d1 = (coords.deg_at(s0, g), coords.deg_at(s1, g)) if girth else (a, a)
            edge = coords.point(s1, d1) - coords.point(s0, d0)
            lon = coords.point(sm + 0.01, a) - coords.point(sm - 0.01, a)
            cosang = float(edge @ lon) / (numpy.linalg.norm(edge) * numpy.linalg.norm(lon))
            ang.append(math.degrees(math.acos(min(1.0, abs(cosang)))))
        for s in (s0, s1):
            e = coords.point(s, a1) - coords.point(s, a0)
            ang.append(math.degrees(math.asin(min(1.0, abs(float(e[1])) / float(numpy.linalg.norm(e))))))
        worst[name] = round(max(ang), 2)
        if worst[name] > limit:
            faults.append(f"{name} leans {worst[name]} deg off the station plane or longeron")
    if faults:
        raise ValueError("skin outlines: " + "; ".join(faults))
    return worst


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


MIN_LINE_TEXELS = 2.0
# Canvas.line_cover's anti-aliased line darkens by up to this much more the further it runs off the texel grid (half
# again at 45 degrees): a diagonal spreads its darkening over two texels a column and read fainter than a line on the
# grid (the tail underside, builds 46 and 47). The gain is the same all along a straight line, so its weight is even.
# Lines drawn in whole texels read crisper but broke into runs a few degrees off the grid (build 47's three trials).
DIAGONAL_GAIN = 0.5
# Functions whose paint() calls are markings, for the livery kit's markings layer: the groups' stencils and placards
# (engines, wing, tail: stamp; struts, wing: placard) and Canvas.decal, the serials' and lettering's.
MARKING_CALLERS = frozenset(("stamp", "placard", "decal"))


class Canvas:
    """Paint layers over the covered texels. px: texel size in metres (1 / density), the anti-aliasing width. With
    buffers["yx"], each texel's atlas row and column, grooves darken with their angle to the texel grid (line_cover):
    the one place paint depends on where an island landed, so that their strength does not."""

    def __init__(self, buffers, coords, px):
        self.xp = np
        buffers = {key: np.asarray(value) for key, value in buffers.items()}
        self.b = buffers
        self.px = px
        self.yx = buffers.get("yx")
        self._nb = None
        self.pos, self.nrm, self.cls = buffers["pos"], buffers["nrm"], buffers["cls"]
        self.n = len(self.cls)
        self.s, self.deg, self.arc = coords.locate(self.pos)
        self.coords = coords
        self.albedo = np.zeros((self.n, 3))
        self.smooth = np.zeros(self.n)
        self.metal = np.full(self.n, 0.03)
        self.height = np.zeros(self.n)
        # the livery kit's layers (detail_centurion.texture_atlas paints a group again without them): "lines" skips the
        # grooves and fastener heads, "marks" the markings; mark_alpha is how much marking ink covers each texel
        self.skip = set()
        self.mark_alpha = np.zeros(self.n)
        self._mark_next = False
        for c, rgb in PAINT.items():
            m = self.cls == c
            self.albedo[m] = rgb
            self.smooth[m] = SMOOTH[c]

    def square(self, sm, am):
        """(u, v, k) for an outline centred at station sm and angle am (degrees from the crown, either side): u the
        station less sm, v the angle less am times k, the girth per degree there, so metres, toward the keel. A station
        plane is u constant and a longeron (an angle) v constant, so a box drawn in (u, v) has its ends in station planes
        and its long edges on the longerons, a slight trapezoid where the body tapers. Drawn in (station, girth) the long
        edges leave the longerons wherever the body tapers and the box shears into a parallelogram."""
        c = self.coords
        k = float(c.arc_at(sm, am + 0.5) - c.arc_at(sm, am - 0.5))
        return self.s - sm, (np.abs(self.deg) - am) * k, k

    def box(self, s0, s1, a0, a1, r, sides=0):
        """Signed distance to an outline from station s0 to s1 and angle a0 to a1, drawn in square()'s coordinates, on
        both sides (sides 0) or one (+1 the left, -1 the right; 9 m away on the other)."""
        u, v, k = self.square((s0 + s1) / 2, (a0 + a1) / 2)
        hs, ha = (s1 - s0) / 2, abs(a1 - a0) / 2 * k
        sdf = rrect_sdf(u, v, -hs, hs, -ha, ha, r)
        return np.where(np.sign(self.arc) == sides, sdf, 9.0) if sides else sdf

    def on(self, *classes):
        return np.isin(self.cls, classes)

    def coverage(self, d, width):
        """Anti-aliased coverage of a line of width centred at distance d."""
        return np.clip(0.5 + (width / 2 - d) / self.px, 0.0, 1.0)

    def colour_line(self, d, width):
        """coverage() for a coloured line (red, yellow), at least MIN_LINE_TEXELS wide: narrower, a diagonal line's
        texels took it at full strength or barely by turns, and it beaded into steps from 3 m (the red keep-clear lines,
        1.3 texels wide). Not for the grooves, rivets and dark lines: widened, they read softer and fainter in the game
        than their crisp one-texel draw (build 44). A marking: the paint() call it feeds goes on the markings layer."""
        self._mark_next = True
        return self.coverage(d, max(width, MIN_LINE_TEXELS * self.px))

    def fill_coverage(self, sdf):
        return np.clip(0.5 - sdf / self.px, 0.0, 1.0)

    def neighbours(self):
        """Canvas index of the texel beside each texel in the atlas (+x, -x, +y, -y), -1 where this canvas has none
        there or it is across an island border (more than 3 texels away on the aircraft)."""
        if self._nb is None:
            y, x = self.yx[:, 0].astype(np.int64) + 1, self.yx[:, 1].astype(np.int64) + 1
            idx = np.full((int(y.max()) + 2, int(x.max()) + 2), -1, dtype=np.int64)
            idx[y, x] = np.arange(self.n)
            self._nb = []
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                j = idx[y + dy, x + dx]
                far = np.linalg.norm(self.pos[np.maximum(j, 0)] - self.pos, axis=1) > 3 * self.px
                self._nb.append(np.where((j >= 0) & ~far, j, -1))
        return self._nb

    def _beside(self, f, j, empty):
        return np.where(j >= 0, f[np.maximum(j, 0)], empty)

    def line_cover(self, d, width):
        """coverage() of a panel line, darkened by DIAGONAL_GAIN times how far it runs off the texel grid (the
        tangent of its angle to the nearer atlas axis, from how fast d changes along each); without atlas positions,
        coverage()."""
        if self.yx is None:
            return self.coverage(d, width)
        nb = self.neighbours()
        sx = np.maximum(np.abs(self._beside(d, nb[0], d) - d), np.abs(self._beside(d, nb[1], d) - d))
        sy = np.maximum(np.abs(self._beside(d, nb[2], d) - d), np.abs(self._beside(d, nb[3], d) - d))
        step = np.maximum(sx, sy)
        slope = np.where(step > 0, np.minimum(sx, sy) / np.where(step > 0, step, 1.0), 0.0)
        return np.clip(self.coverage(d, width) * (1 + DIAGONAL_GAIN * slope), 0.0, 1.0)

    def paint(self, cov, rgb=None, smooth=None, metal=None, height=None, mask=None):
        """Lerp the layers toward the given values by cov. Markings: a colour_line() coverage, or paint from a stencil,
        placard or decal (the caller's name, MARKING_CALLERS: every group's lettering goes through one)."""
        mark = self._mark_next or sys._getframe(1).f_code.co_name in MARKING_CALLERS
        self._mark_next = False
        if mark and "marks" in self.skip:
            return
        if mask is not None:
            cov = cov * mask
        if mark and rgb is not None:
            self.mark_alpha = 1 - (1 - self.mark_alpha) * (1 - np.clip(cov, 0, 1))
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
        if "lines" in self.skip:
            return
        cov = self.line_cover(d, width)
        if mask is not None:
            cov = cov * mask
        self.albedo *= (1 - darken * cov)[:, None]
        self.smooth -= 0.08 * cov
        self.height += depth * cov

    def fasteners(self, d, along, offset=0.03, pitch=0.09, radius=0.007, mask=None):
        """Rows of fastener heads either side of a line: d its distance field, along the position along it."""
        if "lines" in self.skip:
            return
        k = np.round(along / pitch) * pitch
        for o in (-offset, offset) if offset else (0.0,):
            r = np.hypot(d - abs(o), along - k) if o else np.hypot(d, along - k)
            # anti-aliased, as build 43: a head on a single full texel, with its relief in the normal map, drew as a
            # cross-shaped tick either side of the seam, like stitching (build 47)
            cov = np.clip(0.5 + (radius - r) / self.px, 0, 1)
            if mask is not None:
                cov = cov * mask
            self.height += 0.0012 * cov
            self.albedo *= (1 - 0.12 * cov)[:, None]

    def decal_at(self, mask_img, s, a, side, px_per_m, mask=None, rgb=(0.85, 0.85, 0.82), dv=0.0):
        """decal centred at station s and angle a (dv metres toward the keel from it) on one side, its text along the
        longerons and upright in station planes (Canvas.square)."""
        u, v, _ = self.square(s, abs(a))
        on_side = (np.sign(self.arc) == side).astype(float) * (1.0 if mask is None else mask)
        return self.decal(mask_img, (0.0, side * 1e-6), px_per_m, (side, 0), mask=on_side, rgb=rgb, uv=(u, side * (v - dv)))

    def decal(self, mask_img, centre, px_per_m, axis_u, mask=None, rgb=(0.85, 0.85, 0.82), smooth=None, axis_v=None,
              uv=None):
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
        du, dv = (self.s - centre[0], self.arc - centre[1]) if uv is None else uv  # uv: offsets from the centre, metres
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
        # the stencil's box in a grid of cells at least two texels across (8 by 8 at most): the cells holding ink, and of
        # them those a texel of this canvas lands in, whatever the texel size, which varies across the atlas
        gx = max(1, min(8, int(w / px_per_m / (2 * self.px))))
        gy = max(1, min(8, int(h / px_per_m / (2 * self.px))))
        ink_cells = {(i, j) for i in range(gx) for j in range(gy)
                     if mask_img[j * h // gy:(j + 1) * h // gy, i * w // gx:(i + 1) * w // gx].max(initial=0) > 0.5}
        hit = {(int(a * gx // w), int(b * gy // h)) for a, b in zip(x, y)}
        caller = next(f for f in inspect.stack(0)[1:4] if f.function not in ("decal", "decal_at", "stamp"))
        DECALS.append({"at": f"{Path(caller.filename).name}:{caller.lineno} {caller.function}",
                       "centre_s": round(float(np.mean(self.s[cov > 0.5])) if (cov > 0.5).any() else -1.0, 2),
                       "centre_arc": round(float(np.mean(self.arc[cov > 0.5])) if (cov > 0.5).any() else 0.0, 2),
                       "ink_cells": len(ink_cells), "printed_cells": len(ink_cells & hit)})
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
