"""The side windows' frame outline, shared by the build (flightdeck_build.window_bezels, corner_cheeks) and the gate
(flightdeck_sightlines.py): where the frame stands on the inner glass and where the pilot may see glass through it.

Outlines are (station, z) on the inner glass, the same on both sides (the commander's mirrored in x). The outer edge
tucks under the panels round the opening (the coaming over it, the cheek by the display stack forward, the sloped sill
under it); each member runs inward from it by its width to the glass. Measured from the pilot's eye with the cheek open
and the sill sloped: the glass shows from station 5.25 to 6.66, z 4.26 to 4.67, its forward top edge falling to the
display stack. The aft member's outer edge stands at 6.74, under the aft wall (at 6.69 the glass showed past it
in the lower aft corner from the eye)."""
import math

# The forward lower corner reaches to station 5.08 and down to z 4.17 under the cheek's lowest foot (which the wing
# display's sight cone holds up): a corner piece, its inner edge where the jamb's was (5.245); with the corner at
# (5.21, 4.24) the pane showed forward of the jamb, between it, the cheek and the sill (build 16 in game).
WINDOW_FRAME = [((5.08, 4.17), 0.14), ((6.74, 4.17), 0.035), ((6.74, 4.71), 0.035), ((5.47, 4.71), 0.035),
                ((5.08, 4.245), 0.165)]  # each corner, and the width of the member from it to the next corner
FRAME_PROUD, GASKET_W = 0.022, 0.008  # the frame face stands 22 mm off the glass; a dark gasket 8 mm wide inside it
# The frame's outer edge reaches OUTER_TUCK past the outline under the panels round it, and the cheek stands over the
# outline by CHEEK_LAP: in flight the camera sways up to SWAY from the eye in any direction (the game clamps its
# length at 0.15 m, times the default cockpitCamInertia 0.5), and from 7.5 cm aft or outboard the glass showed between
# the frame's slanted forward member and the cheek when they lapped by 1 cm; from the camera a wide look slides 14 to
# 20 cm toward the window, 6 cm of tuck left the glass showing 15 to 20 mm outside that member. The cheek's edge stays
# where it was (CHEEK_LAP - OUTER_TUCK) and a centimetre lower, over the upper forward corner where the glass ends
# under the frame's outer edge
OUTER_TUCK, CHEEK_LAP, SWAY = 0.12, 0.14, 0.075


def _area(poly):
    n = len(poly)
    return sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))


def inset(poly, dist):
    """poly moved inward by dist(i) along each edge i, corners where neighbouring edges meet."""
    n = len(poly)
    sign = 1.0 if _area(poly) > 0 else -1.0
    lines = []
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        L = math.hypot(bx - ax, by - ay)
        tx, ty = (bx - ax) / L, (by - ay) / L
        nx, ny = -ty * sign, tx * sign  # inward
        d = dist(i)
        lines.append(((ax + nx * d, ay + ny * d), (tx, ty)))
    out = []
    for i in range(n):
        (p1, t1), (p2, t2) = lines[i - 1], lines[i]
        den = t1[0] * t2[1] - t1[1] * t2[0]
        k = ((p2[0] - p1[0]) * t2[1] - (p2[1] - p1[1]) * t2[0]) / den
        out.append((p1[0] + t1[0] * k, p1[1] + t1[1] * k))
    return out


def rings():
    """The frame's outlines: outer (on the glass, OUTER_TUCK past the outline under the panels), inner (the glass's
    edge the pilot sees), gasket."""
    corners = [c for c, _ in WINDOW_FRAME]
    widths = [w for _, w in WINDOW_FRAME]
    return {"outer": inset(corners, lambda i: -OUTER_TUCK), "inner": inset(corners, lambda i: widths[i]),
            "gasket": inset(corners, lambda i: widths[i] + GASKET_W)}


def inside(poly, st, z):
    """(st, z) inside poly, by crossings."""
    n, c = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > z) != (y2 > z) and st < x1 + (z - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def cheek_may_open(st, z):
    """Whether a cheek column may stand clear of the glass at (st, z): only inside the outline less CHEEK_LAP (so
    CHEEK_LAP + OUTER_TUCK over the frame's outer edge), so the cheek always laps the frame and the glass shows nowhere
    but inside it."""
    return inside(inset([c for c, _ in WINDOW_FRAME], lambda i: CHEEK_LAP - OUTER_TUCK), st, z)


def look_eye(eye, d):
    """The camera's position when the pilot looks along d: past 33 deg either way the game slides the camera sideways
    toward the look, 0.2 m at 100 deg (CameraCockpitState: num2 = Lerp(0, 0.2, |pan| 0.015 - 0.5) along the
    cockpit's right). Blender x is the crew's left; the pan is negative to the left."""
    from mathutils import Vector
    pan = math.degrees(math.atan2(-d.x, -d.y))
    t = min(1.0, max(0.0, abs(pan) * 0.015 - 0.5))
    return eye + Vector((-(0.2 * t) * math.copysign(1.0, pan), 0.0, 0.0))


OUTLINE_STEP, OUTLINE_OUT = 0.005, (0.002, 0.005, 0.01, 0.015, 0.02)


def outline_gaps(tree, ref, eye, glass_tree, shift=True, glass="glass_int"):
    """Glass the pilot sees just outside a side window's frame, between it and the panels it tucks under, or through a
    hole in it: points on the glass 2 to 20 mm outside each frame's outer outline and across its band (a quarter, a
    half and three quarters of the way to the inner edge), every OUTLINE_STEP along it on both sides, sighted from
    the camera where the game puts it for that look (look_eye; shift False: from eye itself); a sight whose first drawn
    face is the glass there is a gap. Fine enough for a strip a centimetre wide, which a one-degree grid of rays
    misses. Returns (sights, gaps, by side, first examples (side, station, z, mm out), sights past the screen's edge
    instead, reported apart)."""
    from mathutils import Vector
    outer, inner = rings()["outer"], rings()["inner"]
    n = len(outer)
    sign = 1.0 if _area(outer) > 0 else -1.0
    head = max(z for _, z in outer) + 0.05
    sights = gaps = 0
    by, ex, screen_edge = {}, [], []
    for s in (1, -1):
        for i in range(n):
            (ax, ay), (bx, by_) = outer[i], outer[(i + 1) % n]
            L = math.hypot(bx - ax, by_ - ay)
            tx, ty = (bx - ax) / L, (by_ - ay) / L
            ox, oy = ty * sign, -tx * sign  # outward
            (ix, iy), (jx, jy) = inner[i], inner[(i + 1) % n]
            for k in range(int(L / OUTLINE_STEP) + 1):
                f_ = k * OUTLINE_STEP / L
                st0, z0 = ax + tx * k * OUTLINE_STEP, ay + ty * k * OUTLINE_STEP
                sti, zi = ix + (jx - ix) * f_, iy + (jy - iy) * f_  # the inner edge at the same place
                hit = None
                # just outside the outer edge, and across the frame's band (a hole in the frame shows the glass too)
                spots = [(st0 + ox * off, z0 + oy * off, off) for off in OUTLINE_OUT]
                spots += [(st0 + (sti - st0) * b, z0 + (zi - z0) * b, -b) for b in (0.25, 0.5, 0.75)]
                for st, z, off in spots:
                    if z > head:
                        continue
                    g = glass_tree.ray_cast(Vector((0.9 * s, st - 22.475, z)), Vector((s, 0, 0)), 1.5)
                    if g[0] is None:
                        continue
                    e = look_eye(eye, (g[0] - eye).normalized()) if shift else eye
                    d = (g[0] - e).normalized()
                    sights += 1
                    o = e
                    for _ in range(20):
                        h = tree.ray_cast(o, d, 40.0)
                        if h[0] is None:
                            break
                        if h[1].dot(d) < 0:
                            if ref[h[2]][0] == glass and (h[0] - g[0]).length < 0.01:
                                hit = (round(st, 3), round(z, 3), round(off * 1000) if off > 0 else "band %.2f" % -off)
                            break
                        o = h[0] + d * 0.0002
                    if hit:
                        # past the screen's edge (2 mm either way the sight meets the screen or its housing): a crack
                        # at the screen's end, not the window frame's; reported apart
                        side_d = d.cross(Vector((0, 0, 1))).normalized()
                        up_d = side_d.cross(d).normalized()
                        for w in (side_d, -side_d, up_d, -up_d):
                            h2 = tree.ray_cast(e, (g[0] + w * 0.002 - e).normalized(), 40.0)
                            if h2[0] is not None and ref[h2[2]][0] in SCREEN_PARTS:
                                screen_edge.append((("left" if s > 0 else "right"),) + hit)
                                hit = None
                                break
                        break
                if hit:
                    gaps += 1
                    side = "left" if s > 0 else "right"
                    by[side] = by.get(side, 0) + 1
                    if len(ex) < 8:
                        ex.append((side,) + hit)
    return sights, gaps, by, ex, screen_edge


SCREEN_PARTS = ("band", "band_bezel", "band_marker")


def sway_gaps(tree, ref, eye, glass_tree):
    """outline_gaps from the eye and from SWAY away from it in 26 directions (the axes, the edges and the corners of a
    cube, each at SWAY: the game clamps the camera's sway to a length, Vector3.ClampMagnitude), each with the look's
    slide: (positions, total gaps, the worst position's gaps, its offset, sights past the screen's edge instead)."""
    from mathutils import Vector
    worst, at, tot, n, screen = 0, None, 0, 0, 0
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                off = Vector((dx, dy, dz))
                off = off.normalized() * SWAY if off.length else off
                r = outline_gaps(tree, ref, eye + off, glass_tree)
                g, screen = r[1], screen + len(r[4])
                tot += g
                n += 1
                if g > worst:
                    worst, at = g, tuple(round(c, 3) for c in off)
    return n, tot, worst, at, screen
