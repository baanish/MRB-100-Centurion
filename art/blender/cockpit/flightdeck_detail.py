"""The flight deck's small furniture and relief (cockpit/flightdeck.py builds the shell, panel, consoles and controls):
toggle switches, guarded switches, rotary knobs and push buttons on the overhead, the side consoles, the pedestal and the
panel's wings, each group on a modelled switch plate; the wings' eyeball vents, guarded arming switches and the hoses
along their tops; the aft wall's circuit breakers, extinguisher and mask stowage; gaspers, map lights and grab handles
on the walls; seat tracks and the floor hatch over the vestibule's ladder.

Every piece is a closed shell on the interior atlas slot, built in the composite's frame at a point with its own
"up" (the surface it stands on) and "ahead" (where its lever leans or its label reads up); the faces no head position
sees are culled afterwards (flightdeck_uv.cull_unseen), so a piece costs only its visible triangles. Each group
registers its switch plate, legends and hoses with the Labels collector beside it (cockpit/flightdeck_labels.py), so
they move together; build_plates models the plates once every group has registered."""

import math

import bmesh
from mathutils import Vector

import flightdeck_layout as fl
import flightdeck_labels as lb
from m4 import surface as sf

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
PLATE_T, PLATE_CHAMFER = lb.PLATE_T, 0.002  # a switch plate's thickness and the chamfer round its top edge


def frame(up, ahead):
    side, f, u = sf.basis(up, ahead)
    return side, f, u


def cbox(part, fd, centre, axes, size, cls, c=0.003):
    """A box with its edges chamfered c: the flats that catch the light along a stock cockpit's bevelled edges."""
    fs = sf.box(part, centre, axes, size, fd.ATLAS_SLOT, cls)
    verts = list({v for f in fs for v in f.verts})
    edges = list({e for f in fs for e in f.edges})
    r = bmesh.ops.bevel(part.bm, geom=verts + edges, offset=c, segments=1, affect="EDGES", profile=0.5, clamp_overlap=True)
    made = list({f for v in r["verts"] for f in v.link_faces})
    part.tag(made, fd.ATLAS_SLOT, cls)
    return made


# The switches are the kit's (flightdeck_kit): each call places a copy of the piece modelled and textured once.
def toggle(part, fd, base, up, ahead):
    part.kit.place(part, "toggle", base, up, ahead)


def guarded_toggle(part, fd, base, up, ahead, scale=1.0):
    """The kit's arming switch: a red flip cover on its hatched plate. MASTER_GUARD scales it to the KR-67's master
    arm for the switches that matter (master arm, jettison); engine fire's pair stands at ENGINE_GUARD."""
    part.kit.place(part, "guard", base, up, ahead, scale=scale)


MASTER_GUARD, ENGINE_GUARD = 1.7, 1.5


def knob(part, fd, base, up, ahead, r=0.014, h=0.020):
    """The kit's knob, scaled to radius r (its height scales with it)."""
    part.kit.place(part, "knob", base, up, ahead, scale=r / 0.014)


BUTTON_H = 0.006  # the kit's pushbutton cap stands this proud of its base: its legend sits on top


def button(part, fd, base, up, ahead):
    part.kit.place(part, "button", base, up, ahead)


def grid(fn, part, fd, origin, up, ahead, across, rows, cols, pitch, **kw):
    """fn at a rows x cols grid from origin: columns along across, rows along ahead, pitch apart. Returns the points
    row by row."""
    out = []
    for i in range(rows):
        row = []
        for j in range(cols):
            p = origin + ahead * (pitch[0] * i) + across * (pitch[1] * j)
            fn(part, fd, p, up, ahead, **kw)
            row.append(p)
        out.append(row)
    return out


def module(labels, a, b, up, top, cls, pad=0.0, **kw):
    """A switch plate over the rectangle with opposite corners a and b on a surface facing up, its top toward top;
    returns the projector onto the plate's top."""
    a, b = Vector(a), Vector(b)
    c = (a + b) / 2
    t = (top - up * top.dot(up)).normalized()
    right = t.cross(up)
    return labels.plate(c, up, t, abs((b - a).dot(right)) + 2 * pad, abs((b - a).dot(t)) + 2 * pad, cls=cls, **kw)


def chord_lift(c, n, pts):
    """How far a flat plate at c facing n must stand off so its edge points pts on a curved surface stay under it."""
    return max(0.0, max((Vector(p) - Vector(c)).dot(n) for p in pts))


def build_plates(part, fd, labels):
    """The registered switch plates (all but the painted lever slots) as PLATE_T thick plates on the surfaces, their top
    edges chamfered PLATE_CHAMFER: open underneath, so the surface under each stays as it is."""
    bm = part.bm
    for p in labels.plates:
        if p["cls"] is None or p["kind"] == "slot":
            continue
        n, t = Vector(p["n"]), Vector(p["t"])
        r = t.cross(n)
        base = Vector(p["c"]) + n * p["lift"]
        w, h, ch = p["w"], p["h"], PLATE_CHAMFER
        if p["kind"] == "round":
            ring = lambda rad: [base + (r * math.cos(2 * math.pi * k / 16) + t * math.sin(2 * math.pi * k / 16)) * rad
                                for k in range(16)]
            lo, hi = ring(w / 2), [q + n * PLATE_T for q in ring(w / 2 - ch)]
        else:
            rect = lambda hw, hh: [base + r * su * hw + t * sv * hh for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            lo, hi = rect(w / 2, h / 2), [q + n * PLATE_T for q in rect(w / 2 - ch, h / 2 - ch)]
        vlo, vhi = [bm.verts.new(q) for q in lo], [bm.verts.new(q) for q in hi]
        m = len(vlo)
        fs = [bm.faces.new((vlo[i], vlo[(i + 1) % m], vhi[(i + 1) % m], vhi[i])) for i in range(m)] + [bm.faces.new(vhi)]
        fd.facing(fs, n)
        part.tag(fs, fd.ATLAS_SLOT, p["cls"])


WARNING_SLOT = "CockpitWarningLight"  # the stock lamp material: the game lights it on a warning


def warning_lens(part, fd, centre, n):
    """A caution or warning key's lens on the stock warning-lamp material, just over the key's cap, on part.lenses (its
    own renderer, which the stock CockpitWarningLights shows only while it flashes) when the part has one."""
    side, f, u = frame(n, Z)
    pts = [centre + side * sx * 0.0062 + f * sy * 0.0052 for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    into = getattr(part, "lenses", part)
    face = into.bm.faces.new([into.bm.verts.new(p) for p in pts])
    fd.facing([face], n)
    into.tag([face], WARNING_SLOT, fd.KNOB)


def hose(part, fd, labels, pts, radius=0.011, cls=None):
    """A flexible hose along pts, its corrugations painted from the path labels registers."""
    sf.tube(part, pts, radius, 8, fd.ATLAS_SLOT, cls or fd.GRIP)
    labels.hose(pts, radius)


def eyeball_vent(part, fd, base, n, up):
    """A cockpit air outlet: a bezel ring on the panel and a ball with its nozzle, aimed a little up and inboard."""
    side, f, u = frame(n, up)
    sf.revolve_axis(part, ((0.045, -0.001), (0.045, 0.008), (0.036, 0.016), (0.027, 0.014)), base, u, 12, fd.ATLAS_SLOT,
                    fd.PANEL, ref=side)
    aim = (u + f * 0.25 - side * 0.15).normalized()
    ball = base + u * 0.010
    sf.revolve_axis(part, ((0.0, -0.012), (0.019, -0.006), (0.024, 0.006), (0.019, 0.016), (0.012, 0.020)), ball, aim, 12,
                    fd.ATLAS_SLOT, fd.KNOB, ref=side)
    sf.revolve_axis(part, ((0.012, 0.020), (0.012, 0.030), (0.008, 0.030), (0.008, 0.022)), ball, aim, 12, fd.ATLAS_SLOT,
                    fd.METAL, ref=side)


# ---------------- placements ----------------
OVERHEAD_PANELS = (
    ("ELEC", ("BATT", "GEN 1", "GEN 2", "APU"), ("BUS TIE", "EXT PWR", "INV", "STBY")),
    ("HYD", ("PUMP 1", "PUMP 2", "XFEED", "ACCUM"), ("ELEC PMP", "RAT", "BRAKE", "NWS")),
    ("ANTI ICE", ("PITOT", "AOA", "WSHLD", "PROBE"), ("ENG 1", "ENG 2", "WING", "TEST")),
    ("OXY", ("SUPPLY", "DILUTER", "EMERG", "MASK"), ("CREW", "PRESS", "DUMP", "TEST")),
)


def overhead(part, fd, surf, labels):
    """Four panels down the overhead console: two rows of toggles, a guarded pair and a knob each; legends read from
    the seat looking up, their tops aft."""
    o0, o1 = fd.OVERHEAD_S
    fwd, aft = -Y, Y

    def at(x, s):
        return Vector((x, fd.st(s), fd.lining_point(surf, s, 0.0).z - fd.OVERHEAD_DROP))

    def down(s):  # the overhead's face follows the crown: its normal leans with the crown's slope
        dz = (fd.lining_point(surf, s + 0.01, 0.0).z - fd.lining_point(surf, s - 0.01, 0.0).z) / 0.02
        return Vector((0, dz, -1)).normalized()

    n = 4
    for k, (title, row0, row2) in enumerate(OVERHEAD_PANELS):
        a = o0 + 0.04 + k * (o1 - o0 - 0.08) / n
        sc = a + 0.1475
        c, nn = at(0.0, sc), down(sc)
        on = labels.plate(c, nn, aft, 0.30, 0.285, tol=0.03, cls=fd.OVERHEAD,
                          lift=chord_lift(c, nn, [at(x, s) for x in (-0.15, 0.15) for s in (a + 0.005, a + 0.29)]))
        for i in range(4):
            s = a + 0.05 + 0.055 * i
            for x in (-0.11, -0.06, 0.06, 0.11):
                (guarded_toggle if (i == 3 and abs(x) > 0.1) else toggle)(part, fd, on(at(x, s)), nn, fwd)
        knob(part, fd, on(at(0.0, a + 0.10)), nn, fwd, r=0.012, h=0.017)
        labels.add(title, on(at(0.0, a + 0.268)), nn, aft, cap=0.0075)
        for i, texts in ((0, row0), (2, row2)):
            s = a + 0.05 + 0.055 * i + 0.022
            labels.row(texts, [on(at(x, s)) for x in (-0.11, -0.06, 0.06, 0.11)], nn, aft, cap=0.0048)


CONSOLE_SEAM = 0.004  # between neighbouring console panels: the console top shows in it as a dark seam
WING_END_X = 1.045  # the panel's wings stand on the consoles inboard of here, hiding the console top ahead of them


def consoles(part, fd, surf, labels):
    """Each side console tiled with panels from its inboard rail to the wall, CONSOLE_SEAM apart, aft of where the
    panel's wing hides it: the NAV panel's knobs; the source buttons and the jettison guard; a blanking plate where the
    wing ends; the stick's panel; the COMM knobs; a circuit-breaker field; a plate under the armrest; the ENG FIRE
    guards and discharge buttons; a cup recess; the LIGHTS toggles and dimmers. An oxygen mask stowage box at the aft
    end. Legends read from the seat, their tops forward."""
    fwd = -Y
    for side in (1, -1):
        sx = Vector((side, 0, 0))
        top = fd.CONSOLE_TOP
        P = lambda x, s, dz=0.0: Vector((side * x, fd.st(s), top + dz))
        s0, s1 = fd.CONSOLE_S
        cbox(part, fd, P(fd.CONSOLE_X + 0.03, (s0 + s1) / 2, 0.0025), (X, Y, Z), (0.024, s1 - s0 - 0.04, 0.005), fd.CONSOLE, c=0.0015)
        x_in = fd.CONSOLE_X + 0.045

        def edge(a, b):
            return min(fd.lining_x(surf, s, top) for s in (a, (a + b) / 2, b)) - 0.012

        def panel(xa, sa, xb, sb):
            h = CONSOLE_SEAM / 2
            return module(labels, P(xa + h, sa + h), P(xb - h, sb - h), Z, fwd, fd.CONSOLE)

        on = panel(WING_END_X, 5.42, edge(5.42, 5.72), 5.72)
        nav = grid(knob, part, fd, on(P(1.20, 5.62)), Z, fwd, sx, 2, 3, (0.09, 0.09))
        labels.add("NAV", on(P(1.29, 5.49)), Z, fwd, cap=0.0075)
        for row, texts in zip(nav, (("CRS 1", "HDG", "CRS 2"), ("RNG", "MODE", "BRT"))):
            labels.row(texts, [p + Y * 0.032 for p in row], Z, fwd, cap=0.005)
        on = panel(WING_END_X, 5.72, edge(5.72, 5.96), 5.96)
        src = grid(button, part, fd, on(P(1.075, 5.85)), Z, fwd, sx, 1, 4, (0.0, 0.05))
        labels.row(("TCN", "ILS", "GPS", "INS"), [p + Z * BUTTON_H for p in src[0]], Z, fwd, cap=0.0034, rgb=lb.LIT_DIM,
                   lit=lb.LIT_GREEN)
        guarded_toggle(part, fd, on(P(1.33, 5.86)), Z, fwd, scale=MASTER_GUARD)
        labels.add("JETT", on(P(1.33, 5.768)), Z, fwd, cap=0.0065, rgb=lb.RED)
        panel(WING_END_X, 5.96, 1.21, 6.08)
        on = panel(x_in, 6.08, 1.21, 6.38)
        labels.plate(on(P(1.02, fd.STICK_AT[1])), Z, fwd, 0.15, 0.15, kind="round", cls=fd.CONSOLE)
        on = panel(1.21, 5.96, edge(5.96, 6.20), 6.20)
        comm = grid(knob, part, fd, on(P(1.32, 6.15)), Z, fwd, sx, 3, 2, (0.065, 0.075))
        labels.add("COMM", on(P(1.3575, 5.997)), Z, fwd, cap=0.0055)
        for row, texts in zip(comm, (("VHF 1", "VHF 2"), ("UHF", "GRD"), ("VOL", "SQL"))):
            labels.row(texts, [p + Y * 0.029 for p in row], Z, fwd, cap=0.005)
        xb = edge(6.20, 6.38)
        on = panel(1.21, 6.20, xb, 6.38)
        n = int((xb - 1.25) / 0.03)
        for s in (6.26, 6.32):
            for j in range(n):
                part.kit.place(part, "breaker", on(P(1.245 + 0.03 * j, s)), Z, fwd)
        panel(x_in, 6.38, 1.125, 6.895)
        on = panel(1.125, 6.38, 1.335, 6.60)
        for x in (1.17, 1.27):
            guarded_toggle(part, fd, on(P(x, 6.50)), Z, fwd, scale=ENGINE_GUARD)
        fire = grid(button, part, fd, on(P(1.17, 6.405)), Z, fwd, sx, 1, 2, (0.0, 0.10))
        labels.add("ENG FIRE", on(P(1.22, 6.583)), Z, fwd, cap=0.0065, rgb=lb.RED)
        labels.row(("DISCH", "DISCH"), [p + Z * BUTTON_H for p in fire[0]], Z, fwd, cap=0.0032, rgb=lb.LIT_DIM, lit=lb.LIT_AMBER)
        xb = edge(6.38, 6.60)
        on = panel(1.335, 6.38, xb, 6.60)
        cup = on(P((1.335 + xb) / 2, 6.49))
        r = min(0.036, (xb - 1.335) / 2 - 0.012)
        sf.revolve_axis(part, ((r, -0.001), (r, 0.012), (r - 0.004, 0.012), (r - 0.004, 0.001)), cup, Z, 12, fd.ATLAS_SLOT, fd.CONSOLE)
        on = panel(1.125, 6.60, edge(6.60, 6.895), 6.895)
        lights = grid(toggle, part, fd, on(P(1.17, 6.68)), Z, fwd, sx, 2, 4, (0.06, 0.035))
        labels.add("LIGHTS", on(P(1.22, 6.85)), Z, fwd, cap=0.0065)
        for row, texts in zip(lights, (("NAV", "STROBE", "BCN", "LDG"), ("PANEL", "FLOOD", "DOME", "STBY"))):
            labels.row(texts, [p + Y * 0.024 for p in row], Z, fwd, cap=0.0045)
        for s, text in ((6.70, "PNL"), (6.80, "FLOOD")):
            knob(part, fd, on(P(1.36, s)), Z, fwd, r=0.011, h=0.017)
            labels.add(text, on(P(1.36, s + 0.029)), Z, fwd, cap=0.005)
        cbox(part, fd, P(0.98, 6.84) + Z * 0.05, (X, Y, Z), (0.14, 0.10, 0.10), fd.RACK, c=0.004)
        on = labels.plate(P(0.98, 6.84, 0.10), Z, fwd, 0.12, 0.08, cls=fd.RACK)
        labels.add("O2 MASK", on(P(0.98, 6.84, 0.10)), Z, fwd, cap=0.007)


def pedestal(part, fd, labels):
    """The pedestal's radio panel aft of the levers, the quadrant's go-around and disconnect buttons, the trim wheels
    on the quadrant's sides, the gear lever's panel ahead of the quadrant, and the lever slots and legends."""
    top = fd.PEDESTAL_TOP
    fwd = -Y
    P = lambda x, s, dz=0.0: Vector((x, fd.st(s), top + dz))
    on = module(labels, P(-0.135, 6.35), P(0.135, 6.50), Z, fwd, fd.CONSOLE)
    radio = grid(knob, part, fd, on(P(-0.12, 6.44)), Z, fwd, X, 2, 4, (0.06, 0.08), r=0.011, h=0.017)
    labels.add("RADIO", on(P(0.0, 6.488)), Z, fwd, cap=0.006)
    for row, texts in zip(radio, (("TACAN", "ICS", "VHF", "UHF"), ("CHAN", "MODE", "SQL", "VOL"))):
        labels.row(texts, [p + Y * 0.026 for p in row], Z, fwd, cap=0.0046)
    for x, text in ((-0.15, "FLAP"), (0.15, "SPAN")):
        labels.add(text, P(x, 6.478), Z, fwd, cap=0.006)
    for x in (-0.115, 0.115):
        for s in (5.95, 6.05):
            cbox(part, fd, Vector((x * 1.02, fd.st(s), top + 0.03)), (X, Y, Z), (0.012, 0.016, 0.010), fd.KNOB, c=0.0015)
        sf.revolve_axis(part, ((0.045, -0.008), (0.047, -0.004), (0.047, 0.004), (0.045, 0.008)),
                        Vector((math.copysign(0.118, x), fd.st(6.12), top + 0.02)), X, 16, fd.ATLAS_SLOT, fd.KNOB)
    for x in (-fd.THROTTLE_GRIP_X, fd.THROTTLE_GRIP_X):
        labels.plate(P(x, 6.05, 0.05), Z, fwd, 0.012, 0.24, kind="slot")
    labels.add("MAX", P(0.0, 5.935, 0.05), Z, fwd, cap=0.006)
    labels.add("IDLE", P(0.0, 6.165, 0.05), Z, fwd, cap=0.006)
    module(labels, P(-0.20, 6.235), P(0.20, 6.345), Z, fwd, fd.CONSOLE)  # under the flap and span levers
    on = module(labels, P(-0.135, 5.72), P(0.135, 5.87), Z, fwd, fd.CONSOLE)
    keys = grid(button, part, fd, on(P(-0.09, 5.76)), Z, fwd, X, 1, 4, (0.0, 0.06))
    labels.row(("TRIM", "DISC", "TOGA", "A/THR"), [p + Z * BUTTON_H for p in keys[0]], Z, fwd, cap=0.0034, rgb=lb.LIT_DIM,
               lit=lb.LIT_GREEN)
    labels.add("GEAR", on(P(0.058, 5.82)), Z, fwd, cap=0.006)


def wings(part, fd, edges, phi_b, labels):
    """On each panel wing's face beyond the screen: a plate with two columns of knobs and a master caution and warning
    pair; outboard of it an eyeball vent high up and a guarded arming switch on a hazard plate below; a hose along the
    wing's top."""
    R = fd.PANEL_R
    for sgn in (1, -1):
        cols = [sgn * (phi_b + 2.5), sgn * (phi_b + 6.0)]
        lo = fd.KNEE_Z
        tops = [fd.panel_top(edges, p, phi_b) for p in cols]
        mid = sgn * (phi_b + 4.25)
        inward = lambda p: Vector((-math.sin(math.radians(p)), math.cos(math.radians(p)), 0))
        rows = [z for z in (lo + 0.07, lo + 0.13) if all(z < t - 0.04 for t in tops)]
        caution = all(t - lo > 0.22 for t in tops)
        if not rows:
            continue
        z0, z1 = lo + 0.035, (lo + 0.19 if caution else max(rows)) + 0.035
        c = fd.cyl(mid, (z0 + z1) / 2, R)
        half = 2.8
        on = labels.plate(c, inward(mid), Z, math.radians(2 * half) * R, z1 - z0, tol=0.02, cls=fd.PANEL,
                          lift=chord_lift(c, inward(mid), [fd.cyl(mid + d, c.z, R) for d in (-half, half)]))
        for z, texts in zip(rows, (("BRT", "CONT"), ("HUD", "SYM"))):
            for p in cols:
                knob(part, fd, on(fd.cyl(p, z, R)), inward(p), Z, r=0.012, h=0.018)
            labels.row(texts, [on(fd.cyl(p, z + 0.027, R)) for p in cols], inward(mid), Z, cap=0.0048, axis=fd.band_axis())
        if caution:
            pts = []
            for p in cols:
                b = on(fd.cyl(p, lo + 0.19, R))
                button(part, fd, b, inward(p), Z)
                warning_lens(part, fd, b + inward(p) * (BUTTON_H + 0.0003), inward(p))
                pts.append(b + inward(p) * BUTTON_H)
            labels.row(("CAUT", "WARN"), pts, inward(mid), Z, cap=0.0032, rgb=lb.LIT_DIM, lit=lb.LIT_AMBER, axis=fd.band_axis())
        out = sgn * (fd.PANEL_PHI - 1.9)  # outboard of the knob plate, inside the wing's end
        top_out = fd.panel_top(edges, out, phi_b)
        lo_out = fd.CONSOLE_TOP if abs(fd.cyl(out, 0, R).x) > fd.CONSOLE_X else fd.KNEE_Z
        if top_out - lo_out > 0.26:
            eyeball_vent(part, fd, fd.cyl(out, top_out - 0.095, R - 0.001), inward(out), Z)
            guarded_toggle(part, fd, fd.cyl(out, lo_out + 0.09, R), inward(out), Z, scale=MASTER_GUARD)
        path = [fd.cyl(sgn * a, fd.panel_top(edges, sgn * a, phi_b) - 0.020, R - 0.013)
                for a in [phi_b + 0.8 + (fd.PANEL_PHI - 1.5 - phi_b - 0.8) * k / 14 for k in range(15)]]
        hose(part, fd, labels, path)


BREAKERS = {1: (("FUEL", "HYD", "AVNX", "RDR", "NAV", "COMM"), ("LTS", "OXY", "EWS", "DISP", "FCS 1", "FCS 2")),
            -1: (("BUS 1", "BUS 2", "DEICE", "WPN", "IFF", "DL"), ("ECS", "PUMP", "GEAR", "FLAP", "SPAN", "BRK"))}


def aft_wall(part, fd, surf, labels):
    """Circuit breaker panels between the racks and the seats, the extinguisher on its bracket, and cable runs along
    the wall's foot. Legends read facing aft."""
    y = fd.st(fd.AFT_S)
    for side in (1, -1):
        c = Vector((side * 0.62, y - 0.02, 4.80))
        cbox(part, fd, c, (X, Y, Z), (0.40, 0.04, 0.34), fd.RACK, c=0.004)
        face = c - Y * 0.02
        on = labels.plate(face, -Y, Z, 0.37, 0.31, cls=fd.RACK)
        rows = []
        for i in range(4):
            row = []
            for j in range(6):
                b = on(c + Vector((side * (-0.15 + 0.06 * j), -0.02, -0.12 + 0.08 * i)))
                sf.revolve_axis(part, ((0.0065, 0.0), (0.0065, 0.004), (0.005, 0.009), (0.0, 0.010)), b, -Y, 6, fd.ATLAS_SLOT, fd.KNOB)
                row.append(b)
            rows.append(row)
        labels.add("CIRCUIT BREAKERS", on(face + Z * 0.143), -Y, Z, cap=0.006)
        for i, texts in zip((1, 3), BREAKERS[side]):
            labels.row(texts, [b - Z * 0.021 for b in rows[i]], -Y, Z, cap=0.0044)
    e = Vector((-0.70, y - 0.10, fl.FLOOR_Z + 0.06))
    sf.revolve_axis(part, ((0.0, 0.0), (0.055, 0.0), (0.06, 0.03), (0.06, 0.30), (0.04, 0.34), (0.015, 0.36), (0.015, 0.40)),
                    e, Z, 14, fd.ATLAS_SLOT, fd.HANDLE)
    labels.add("FIRE EXT\nHALON", e + Z * 0.20 - Y * 0.0605, -Y, Z, cap=0.007, lift=0.0025)
    sf.tube(part, [e + Z * 0.38 + Y * 0.0, e + Z * 0.42 + Y * 0.03, e + Z * 0.38 + Y * 0.06], 0.006, 6, fd.ATLAS_SLOT, fd.METAL)
    for z in (0.12, 0.28):
        cbox(part, fd, e + Z * z + Y * 0.07, (X, Y, Z), (0.13, 0.02, 0.025), fd.METAL, c=0.002)
    for side in (1, -1):
        hose(part, fd, labels, [Vector((side * 0.3, y - 0.03, fl.FLOOR_Z + 0.05)), Vector((side * 0.6, y - 0.03, fl.FLOOR_Z + 0.05)),
                                Vector((side * 0.9, y - 0.03, fl.FLOOR_Z + 0.05))], radius=0.018, cls=fd.KNOB)


def walls(part, fd, surf):
    """A gasper and a map light over each console, and an assist handle on each wall aft of the side pane."""
    for side in (1, -1):
        for s, z, kind in ((6.55, 4.80, "gasper"), (6.05, 4.95, "light")):
            a = _angle_at(fd, surf, s, z, side)
            p, n = fd.lining_point(surf, s, a), surf.normal(s, a)
            if kind == "gasper":
                sf.revolve_axis(part, ((0.035, 0.0), (0.035, 0.008), (0.025, 0.02), (0.018, 0.03), (0.0, 0.03)), p, -n, 12,
                                fd.ATLAS_SLOT, fd.KNOB)
            else:
                sf.revolve_axis(part, ((0.022, 0.0), (0.022, 0.012), (0.015, 0.05), (0.0, 0.05)), p, -n, 10, fd.ATLAS_SLOT, fd.METAL)
        a = _angle_at(fd, surf, 6.75, 4.95, side)
        p, n = fd.lining_point(surf, 6.75, a), surf.normal(6.75, a)
        sf.tube(part, [p + Y * 0.12, p - n * 0.05 + Y * 0.12, p - n * 0.05 - Y * 0.12, p - Y * 0.12], 0.011, 8, fd.ATLAS_SLOT, fd.GRIP)


def _angle_at(fd, surf, s, z, side):
    lo, hi = 0.0, 179.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fd.lining_point(surf, s, mid).z > z else (lo, mid)
    return side * (lo + hi) / 2


def floor(part, fd):
    """Seat tracks under each seat, and the floor hatch over the vestibule's ladder (fl.FLOOR_HATCH): its frame, hinges
    on the forward edge and a flush handle."""
    for side in (1, -1):
        for dx in (-0.2, 0.2):
            x = side * fl.EYE_X + dx
            cbox(part, fd, Vector((x, fd.st(6.50), fl.FLOOR_Z + 0.008)), (X, Y, Z), (0.035, 0.80, 0.016), fd.METAL, c=0.002)
    s0, s1, w = fl.FLOOR_HATCH
    z = fl.FLOOR_Z + 0.004
    for x, s, lx, ls in ((0.0, s0 - 0.01, 2 * w + 0.04, 0.02), (0.0, s1 + 0.01, 2 * w + 0.04, 0.02),
                         (-w - 0.01, (s0 + s1) / 2, 0.02, s1 - s0), (w + 0.01, (s0 + s1) / 2, 0.02, s1 - s0)):
        sf.box(part, Vector((x, fd.st(s), z)), (X, Y, Z), (lx, ls, 0.008), fd.ATLAS_SLOT, fd.METAL)
    for x in (-0.12, 0.12):
        sf.tube(part, [Vector((x - 0.04, fd.st(s0 + 0.01), z + 0.008)), Vector((x + 0.04, fd.st(s0 + 0.01), z + 0.008))],
                0.008, 8, fd.ATLAS_SLOT, fd.METAL)
    sf.box(part, Vector((0.0, fd.st(s1 - 0.06), z + 0.002)), (X, Y, Z), (0.12, 0.04, 0.008), fd.ATLAS_SLOT, fd.HANDLE)


def build_details(part, fd, surf, edges, phi_b, labels):
    overhead(part, fd, surf, labels)
    consoles(part, fd, surf, labels)
    pedestal(part, fd, labels)
    wings(part, fd, edges, phi_b, labels)
    aft_wall(part, fd, surf, labels)
    walls(part, fd, surf)
    floor(part, fd)
