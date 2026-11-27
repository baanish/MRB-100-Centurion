"""The camera band reshaped (docs/DECISIONS.md: flatter and wider): the screen K times 0.1.3's length along its arc, at
0.1.3's height, on a cylinder of a larger radius with
its middle where today's is (station 5.70, 1.60 m ahead of today's axis at 7.30). The kept 0.1.3 parts are moved
point by point, by arc length and distance from the cylinder: the sheet stretches along its arc (its scan lines run
along it); the bezel stretches with it and its end caps move out unstretched; the camera marker stays 12 mm in from
the +X end; the missile warning lamps' housings and lenses keep their place along the arc (over the same displays)
and their shape, bent onto the new curve.

Used by flightdeck_build.py."""
import math

from mathutils import Vector

AXIS_ST0, R0 = 7.30, 1.60  # today's cylinder (art/blender/cockpit/flightdeck.py:89)
MID_ST = AXIS_ST0 - R0  # the band's middle, kept: station 5.70
ARC0 = 2 * R0 * math.radians(29.3)  # today's arc, 1.635 m
# the arc over 0.1.3's (flightdeck_build.py sets it from BAND_K, 1.3215 on a 4.5 m radius: 2.16 m): the widest that
# fits, since the side wall tumbles in to x 1.08 to 1.16 at the screen's top edge (z 4.97, stations 5.75 to 5.95), the
# sheet's ends at x 1.07 and its bezel caps 2 cm beyond
K = 1.2
Y0 = 22.475


def st(s):
    return s - Y0


def old_coords(p):
    """Today's (arc length from the middle, distance outward from the sheet's cylinder) of a world point."""
    ax = st(AXIS_ST0)
    phi = math.atan2(p.x, ax - p.y)
    return R0 * phi, math.hypot(p.x, ax - p.y) - R0


def new_point(s, d, z, radius):
    ax = st(MID_ST) + radius
    phi = s / radius
    r = radius + d
    return Vector((r * math.sin(phi), ax - r * math.cos(phi), z))


def axis_station(radius):
    return MID_ST + radius


def lamp_pieces(bezel):
    """The vertices of band_bezel's missile warning lamp housings (flightdeck.py build_warning_lamps): every connected
    piece lying wholly under the screen's foot (z 4.80) between 16.5 and 23.5 deg off the middle. Picked by height
    alone (under z 4.772) only the housings' bottom edges kept their place and the rest stretched 18 cm outboard: a
    sheared box with its bottom edge drawn out as a line over the radar, the dark lens off the lit face."""
    mw = bezel.matrix_world
    root = list(range(len(bezel.data.vertices)))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i
    for e in bezel.data.edges:
        root[find(e.vertices[0])] = find(e.vertices[1])
    ok = {}
    for v in bezel.data.vertices:
        p = mw @ v.co
        r = find(v.index)
        ok[r] = ok.get(r, True) and p.z < 4.8005 and 16.5 < abs(math.degrees(old_coords(p)[0] / R0)) < 23.5
    return {v.index for v in bezel.data.vertices if ok[find(v.index)]}


def reshape(objs, radius, k):
    """Moves band, band_bezel, band_marker and warning_lenses (a dict of objects) onto the new cylinder. Returns the
    new half-arc and end angle."""
    s_end = ARC0 / 2
    grow = s_end * (k - 1)
    for name, o in objs.items():
        if o is None:
            continue
        mw, inv = o.matrix_world, o.matrix_world.inverted()
        housing = lamp_pieces(o) if name == "band_bezel" else set()
        for v in o.data.vertices:
            p = mw @ v.co
            s, d = old_coords(p)
            lamp = name == "warning_lenses" or v.index in housing
            if lamp:
                s1 = s  # the lamps keep their place along the arc
            elif name == "band_marker":
                s1 = s + grow  # 12 mm in from the +X end, as today
            elif abs(s) <= s_end + 1e-6:
                s1 = s * k
            elif name == "band_bezel" and p.z > 4.955:  # the top rail stops 3 mm past the upright: carried out unstretched
                # it overhung the upright by 2 cm, a blunt tip from the pilot's seat
                s1 = math.copysign(s_end * k + min(abs(s) - s_end, 0.003), s)
            else:
                s1 = s + math.copysign(grow, s)  # the bezel's end caps: out with the ends, unstretched
            v.co = inv @ new_point(s1, d, p.z, radius)
        o.data.update()
    half = s_end * k
    return half, math.degrees(half / radius)


def crew_face(p, radius, gap=0.01):
    """The point at p's height on the new band's cylinder plus the panel's gap, along the line from p toward its axis
    (blockout.band_crew_face for the new band)."""
    ax = Vector((0.0, st(axis_station(radius)), p.z))
    dv = p - ax
    dv.z = 0
    return ax + dv.normalized() * (radius + gap)
