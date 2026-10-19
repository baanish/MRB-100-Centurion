"""Shell builders the detail groups share: the fuselage as a parametric surface, a hull lofted over it with
recesses cut into it, and closed detail shells (panels, frames, blades, domes, tubes) placed on any surface point.

Every builder adds faces to a Part's bmesh in world space and tags them with a material slot and a paint class;
the texturing reads the class (m4/paint.py), the export reads the slot. Every shell is closed, so a part stays a set
of closed shells however many details it carries. UV seams are marked where each shell is built."""

import math

import bmesh
from mathutils import Matrix, Vector

# Paint classes, written to the "cls" face attribute and baked into the class map.
HULL, RADOME, FRAME, DOOR, FITTING = 1, 2, 3, 4, 5

N = 64  # hull ring vertices: vertex 0 on top, angle grows toward +X (the left wing), as the blockout's fus_point
KEEL = N // 2
CHINE_DEG = 112.5  # the blockout's chine vertices (10 and 22 of 32); also the lower longeron line
CHINE_K = (round(N * CHINE_DEG / 360), N - round(N * CHINE_DEG / 360))  # 20 and 44


def ring_deg(k):
    return 360.0 * k / N


def merge_stations(base, must, near=0.08):
    """Base stations plus the feature stations, dropping base stations closer than near to a feature."""
    out = sorted(set(must))
    out += [s for s in base if all(abs(s - m) >= near for m in must)]
    return sorted(out)


def frange(a, b, step):
    n = max(1, round((b - a) / step))
    return [a + (b - a) * i / n for i in range(n + 1)]


class Fuselage:
    """The blockout's fuselage surface at any resolution: fus_point plus its chine, which the 32-vertex blockout
    applies at single vertices and is reproduced here as the same linear hat between them."""

    def __init__(self, bl):
        self.bl = bl
        self.P = bl.FUS_P

    def chine_offset(self, s, deg):
        d = deg % 360.0
        d = min(abs(d - CHINE_DEG), abs(d - (360.0 - CHINE_DEG)))
        return self.bl.CHINE_OUT * self.bl.chine(s) * max(0.0, 1.0 - d / (360.0 / 32))

    def point(self, s, deg, off=0.0):
        return self.bl.fus_point(s, deg, off + self.chine_offset(s, deg))

    def normal(self, s, deg):
        ds, da = 0.01, 0.25
        a = self.point(s + ds, deg) - self.point(s - ds, deg)
        b = self.point(s, deg + da) - self.point(s, deg - da)
        n = a.cross(b).normalized()
        w, top, bot = self.bl.fus_profile(s)
        c = Vector((0, self.bl.st(s), (top + bot) / 2))
        return n if n.dot(self.point(s, deg) - c) > 0 else -n

    def deg_for_z(self, s, z, side=1):
        """The upper-side angle (0..90) where the surface reaches height z at station s (chine ignored)."""
        w, top, bot = self.bl.fus_profile(s)
        zc, h = (top + bot) / 2, (top - bot) / 2
        c = max(-1.0, min(1.0, (z - zc) / h))
        c = math.copysign(abs(c) ** (self.P / 2), c)
        return side * math.degrees(math.acos(c))

    def deg_for_x(self, s, x, lower=True):
        """The angle where the surface reaches half-width |x|, on the lower side (90..180) by default."""
        w, _, _ = self.bl.fus_profile(s)
        a = math.degrees(math.asin(min(1.0, abs(x) / w) ** (self.P / 2)))
        a = 180.0 - a if lower else a
        return math.copysign(a, x)


class Part:
    """One render part under construction: a world-space bmesh, its material slot names, a paint class per face
    and the mirrored face pairs whose UVs are copied (the lower hull and the radome)."""

    def __init__(self, name, slots):
        self.name, self.slots = name, list(slots)
        self.bm = bmesh.new()
        self.cls = self.bm.faces.layers.int.new("cls")
        self.mirror_pairs = []  # (face whose UVs are copied, its +X source)
        # A thin-walled part's closed hull, kept before its joints open onto the damage structure (m4/airframe.py):
        # what other parts' hidden skin is tested inside
        self.envelope = None

    def tag(self, faces, slot, cls=0):
        if slot not in self.slots:
            self.slots.append(slot)
        k = self.slots.index(slot)
        for f in faces:
            f.material_index = k
            f[self.cls] = cls
        return faces


def seam(bm, a, b):
    e = bm.edges.get((a, b))
    if e is not None:
        e.seam = True


def cap(bm, ring):
    """Zip a closed ring shut from both ends inward (as the blockout's loft caps), seaming its boundary."""
    i, j, faces = 0, len(ring) - 1, []
    while j - i > 1:
        faces.append(bm.faces.new((ring[i], ring[i + 1], ring[j])))
        i += 1
        if j - i > 1:
            faces.append(bm.faces.new((ring[i], ring[j - 1], ring[j])))
            j -= 1
    for k in range(len(ring)):
        seam(bm, ring[k], ring[(k + 1) % len(ring)])
    return faces


class Grid:
    """Rings of equal size lofted into quads: V[r][k] vertices, F[(r, k)] the face from ring r to r + 1 between
    columns k and k + 1. loop: the rings close on themselves (a hull); otherwise they are open rows."""

    def __init__(self, bm, rings, loop=True):
        self.bm, self.loop = bm, loop
        self.V = [[bm.verts.new(p) for p in ring] for ring in rings]
        self.n = len(rings[0])
        self.F = {}
        cols = self.n if loop else self.n - 1
        for r in range(len(rings) - 1):
            for k in range(cols):
                k1 = (k + 1) % self.n
                self.F[r, k] = bm.faces.new((self.V[r][k], self.V[r][k1], self.V[r + 1][k1], self.V[r + 1][k]))

    def faces(self):
        return list(self.F.values())

    def seam_column(self, k):
        for r in range(len(self.V) - 1):
            seam(self.bm, self.V[r][k], self.V[r + 1][k])

    def seam_ring(self, r):
        for k in range(self.n if self.loop else self.n - 1):
            seam(self.bm, self.V[r][k], self.V[r][(k + 1) % self.n])


def hull(part, surf, stations, slot, cls, pole=None, angles=None, cap_slot=None):
    """The fuselage skin between two stations: N-vertex rings on the surface, a pole at the start (the radome tip)
    or a flat cap, and a flat cap at the end. Caps are station joints, hidden while the part is attached, so they
    take cap_slot. angles(s, k) may move a ring vertex (to put a column on a door edge); it must stay symmetric."""
    rings = [[surf.point(s, angles(s, k) if angles else ring_deg(k)) for k in range(N)] for s in stations]
    g = Grid(part.bm, rings)
    part.tag(g.faces(), slot, cls)
    bm = part.bm
    if pole is not None:
        p = bm.verts.new(pole)
        fan = [bm.faces.new((g.V[0][(k + 1) % N], g.V[0][k], p)) for k in range(N)]
        part.tag(fan, slot, cls)
        g.pole_faces = fan
    else:
        part.tag(cap(bm, g.V[0][::-1]), cap_slot or slot)
        g.pole_faces = []
    part.tag(cap(bm, g.V[-1]), cap_slot or slot)
    g.stations = list(stations)
    return g


def ring_index(g, s):
    return min(range(len(g.stations)), key=lambda r: abs(g.stations[r] - s))


def mirror_columns(part, g, k0, k1, rows=None):
    """Faces between columns k0 and k1 (on the -X side, KEEL <= k0) copy the UVs of their +X mirror: face (r, k)
    mirrors (r, N - 1 - k). Records the pairs on the part; faces cut away by a recess are skipped."""
    for r in rows or range(len(g.V) - 1):
        for k in range(k0, k1):
            src, dst = g.F.get((r, N - 1 - k)), g.F.get((r, k))
            if src is not None and dst is not None and src.is_valid and dst.is_valid:
                part.mirror_pairs.append((dst, src))


def recess(part, g, r0, r1, k0, k1, floor, slot, cls=0):
    """Cut the hull faces between rings r0..r1 and columns k0..k1 (k may run past N) and close the hole with walls
    down to a floor: floor(p, r, k) gives the floor point under hull vertex p. The part stays one closed shell."""
    bm = part.bm
    ks = list(range(k0, k1 + 1))
    under = {(r, k): floor(g.V[r][k % N].co.copy(), r, k) for r in range(r0, r1 + 1) for k in ks}
    for r in range(r0, r1):
        for k in ks[:-1]:
            bm.faces.remove(g.F.pop((r, k % N)))
    for r in range(r0 + 1, r1):
        for k in ks[1:-1]:
            bm.verts.remove(g.V[r][k % N])
    W = {key: bm.verts.new(p) for key, p in under.items()}
    faces = []
    for r in range(r0, r1):
        for k in ks[:-1]:
            faces.append(bm.faces.new((W[r, k], W[r + 1, k], W[r + 1, k + 1], W[r, k + 1])))
    walls = []
    for k in ks[:-1]:
        for r in (r0, r1):
            walls.append(bm.faces.new((g.V[r][k % N], g.V[r][(k + 1) % N], W[r, k + 1], W[r, k])))
    for r in range(r0, r1):
        for k in (k0, k1):
            walls.append(bm.faces.new((g.V[r][k % N], g.V[r + 1][k % N], W[r + 1, k], W[r, k])))
    for e in {e for f in walls for e in f.edges}:
        e.seam = True
    part.tag(faces + walls, slot, cls)
    return faces, walls


# ---------- closed detail shells ----------
def slab(part, grid_pts, normals, outer, inner, slot_top, slot_rest=None, cls=0, cls_rest=None):
    """A thin closed shell over a rows x cols grid of surface points: the top face lifted by outer (a number or a
    function (i, j) -> offset), the bottom by inner, side walls round the boundary. Returns (top, bottom, sides)."""
    bm = part.bm
    rows, cols = len(grid_pts), len(grid_pts[0])
    off = outer if callable(outer) else (lambda i, j: outer)
    T = Grid(bm, [[grid_pts[i][j] + normals[i][j] * off(i, j) for j in range(cols)] for i in range(rows)], loop=False)
    B = Grid(bm, [[grid_pts[i][j] + normals[i][j] * inner for j in range(cols)] for i in range(rows)], loop=False)
    for f in B.faces():
        f.normal_flip()
    ring = ([(0, j) for j in range(cols)] + [(i, cols - 1) for i in range(1, rows)]
            + [(rows - 1, j) for j in range(cols - 2, -1, -1)] + [(i, 0) for i in range(rows - 2, 0, -1)])
    sides = []
    for (i, j), (i1, j1) in zip(ring, ring[1:] + ring[:1]):
        sides.append(bm.faces.new((T.V[i][j], T.V[i1][j1], B.V[i1][j1], B.V[i][j])))
        seam(bm, T.V[i][j], T.V[i1][j1])
        seam(bm, B.V[i][j], B.V[i1][j1])
    seam(bm, T.V[0][0], B.V[0][0])
    part.tag(T.faces(), slot_top, cls)
    part.tag(B.faces() + sides, slot_rest or slot_top, cls if cls_rest is None else cls_rest)
    return T.faces(), B.faces(), sides


def bilinear(c, u, v):
    """Corner c0..c3 (u from c0 to c1, v from c0 to c3) interpolated, each corner an (s, deg) pair."""
    (s0, a0), (s1, a1), (s2, a2), (s3, a3) = c
    return ((1 - u) * (1 - v) * s0 + u * (1 - v) * s1 + u * v * s2 + (1 - u) * v * s3,
            (1 - u) * (1 - v) * a0 + u * (1 - v) * a1 + u * v * a2 + (1 - u) * v * a3)


def surface_patch(part, surf, corners, nu, nv, outer, inner, slot_top, slot_rest=None, cls=0, cls_rest=None):
    """A slab conforming to the fuselage over a quad of (station, angle) corners."""
    pts, nrm = [], []
    for i in range(nu + 1):
        row_p, row_n = [], []
        for j in range(nv + 1):
            s, a = bilinear(corners, i / nu, j / nv)
            row_p.append(surf.point(s, a))
            row_n.append(surf.normal(s, a))
        pts.append(row_p)
        nrm.append(row_n)
    return slab(part, pts, nrm, outer, inner, slot_top, slot_rest, cls, cls_rest)


def outline_frame(part, surf, corners, per_edge, w_out, w_in, top, bottom, slot, cls=0):
    """A closed frame of rectangular section following a quad outline of (station, angle) corners: w_out past the
    outline, w_in over it, from bottom to top above the surface. Corners are mitred to keep the width."""
    path = []
    for e in range(4):
        c0, c1 = corners[e], corners[(e + 1) % 4]
        path += [(c0[0] + (c1[0] - c0[0]) * t / per_edge, c0[1] + (c1[1] - c0[1]) * t / per_edge) for t in range(per_edge)]
    pts = [surf.point(s, a) for s, a in path]
    nrm = [surf.normal(s, a) for s, a in path]
    centre = sum(pts, Vector()) / len(pts)
    rings = []
    m = len(pts)
    for i in range(m):
        t0 = (pts[i] - pts[i - 1]).normalized()
        t1 = (pts[(i + 1) % m] - pts[i]).normalized()
        n = nrm[i]
        b0, b1 = n.cross(t0).normalized(), n.cross(t1).normalized()
        b = (b0 + b1).normalized()
        mitre = 1.0 / max(0.5, b.dot(b0))
        if b.dot(pts[i] - centre) < 0:
            b = -b
        p = pts[i]
        rings.append([p + b * w_out * mitre + n * bottom, p + b * w_out * mitre + n * top,
                      p - b * w_in * mitre + n * top, p - b * w_in * mitre + n * bottom])
    g = _loop_grid(part.bm, rings)
    for k in range(4):
        g.seam_column(k)
    g.seam_ring(0)
    part.tag(g.faces(), slot, cls)
    return g


def _loop_grid(bm, rings):
    """Rings swept round a closed path: the last ring joins the first."""
    g = Grid(bm, rings, loop=True)
    n = len(rings[0])
    last = len(rings) - 1
    for k in range(n):
        k1 = (k + 1) % n
        g.F[last, k] = bm.faces.new((g.V[last][k], g.V[last][k1], g.V[0][k1], g.V[0][k]))
    return g


def basis(n, fwd):
    """Orthonormal (side, fwd, up) with up = n and fwd projected off it."""
    up = n.normalized()
    f = (fwd - up * fwd.dot(up)).normalized()
    return up.cross(f).normalized(), f, up


def blade(part, base, n, fwd, height, c_root, c_tip, sweep, thick, slot, cls=FITTING, bury=0.04, npts=6):
    """A swept blade antenna or vane: symmetric sections from bury below the base to the tip, which is capped."""
    side, f, up = basis(n, fwd)
    rings = []
    for z in (-bury, 0.0, height * 0.5, height):
        t = max(0.0, z) / height
        c = c_root + (c_tip - c_root) * t
        le = base + up * z + f * (c_root * 0.5 - sweep * t)  # leading edge forward, swept back with height
        ring = []
        for i in range(npts):  # upper side from trailing to leading edge, then lower side back
            x = 0.5 * (1 - math.cos(math.pi * (npts - 1 - i) / (npts - 1)))
            y = 5 * thick * c * (0.2969 * math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1036 * x ** 4)
            ring.append(le - f * (c * x) + side * max(y, 0.004))
        for i in range(1, npts - 1):
            x = 0.5 * (1 - math.cos(math.pi * i / (npts - 1)))
            y = 5 * thick * c * (0.2969 * math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1036 * x ** 4)
            ring.append(le - f * (c * x) - side * max(y, 0.004))
        rings.append(ring)
    g = Grid(part.bm, rings, loop=True)
    g.seam_column(0)
    g.seam_column(npts - 1)
    faces = g.faces() + cap(part.bm, g.V[0][::-1]) + cap(part.bm, g.V[-1])
    part.tag(faces, slot, cls)
    return faces


def revolve_axis(part, profile, centre, axis, seg, slot, cls=0, ref=None):
    """Spin (radius, height) points about axis through centre; a zero radius at either end makes a pole, otherwise
    the end is capped flat. Returns the faces."""
    ax = axis.normalized()
    e1 = (ref or ax.orthogonal()).normalized()
    e1 = (e1 - ax * e1.dot(ax)).normalized()
    e2 = ax.cross(e1)
    pts = list(profile)
    bm = part.bm
    poles = [None, None]
    if pts[0][0] == 0:
        poles[0] = centre + ax * pts.pop(0)[1]
    if pts[-1][0] == 0:
        poles[1] = centre + ax * pts.pop()[1]
    rings = [[centre + ax * h + (e1 * math.cos(2 * math.pi * i / seg) + e2 * math.sin(2 * math.pi * i / seg)) * r
              for i in range(seg)] for r, h in pts]
    g = Grid(bm, rings, loop=True) if len(rings) > 1 else None
    faces = g.faces() if g else []
    V = g.V if g else [[bm.verts.new(p) for p in rings[0]]]
    if g:
        g.seam_column(0)
    for end, ring, flip in ((poles[0], V[0], True), (poles[1], V[-1], False)):
        if end is None:
            faces += cap(bm, ring[::-1] if flip else ring)
        else:
            p = bm.verts.new(end)
            for i in range(seg):
                a, b = ring[i], ring[(i + 1) % seg]
                faces.append(bm.faces.new((b, a, p) if flip else (a, b, p)))
            seam(bm, ring[0], p)
    part.tag(faces, slot, cls)
    return faces


def tube(part, pts, radius, seg, slot, cls=0):
    """A capped tube along a polyline."""
    bm = part.bm
    rings = []
    ref = None
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        ref = (ref or t.orthogonal())
        e1 = (ref - t * ref.dot(t)).normalized()
        e2 = t.cross(e1)
        rings.append([p + (e1 * math.cos(2 * math.pi * k / seg) + e2 * math.sin(2 * math.pi * k / seg)) * radius
                      for k in range(seg)])
        ref = e1
    g = Grid(bm, rings, loop=True)
    g.seam_column(0)
    faces = g.faces() + cap(bm, g.V[0][::-1]) + cap(bm, g.V[-1])
    part.tag(faces, slot, cls)
    return faces


def box(part, centre, axes, size, slot, cls=0):
    """An oriented box: axes (x, y, z) unit vectors, size along each."""
    x, y, z = (a * (s / 2) for a, s in zip(axes, size))
    rings = [[centre + y * sy + x * sx + z * sz for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))] for sy in (-1, 1)]
    g = Grid(part.bm, rings, loop=True)
    for k in range(4):
        g.seam_column(k)
    faces = g.faces() + cap(part.bm, g.V[0][::-1]) + cap(part.bm, g.V[-1])
    part.tag(faces, slot, cls)
    return faces


def rotate_about(part, faces, origin, axis, angle):
    """Rotate the vertices of faces about a line (used to swing a door built closed into its rest pose)."""
    verts = list({v for f in faces for v in f.verts})
    m = Matrix.Translation(origin) @ Matrix.Rotation(angle, 4, axis) @ Matrix.Translation(-origin)
    bmesh.ops.transform(part.bm, matrix=m, verts=verts)
