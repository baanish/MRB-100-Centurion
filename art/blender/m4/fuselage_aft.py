"""Part group 2: the mid and aft fuselage and the tail systems, stations 17 to 44.95.

Parts: fuselage_M (the wing box section, under the dorsal fairing and between the sponsons), wingfairing (the
wing-to-body fairing), fuselage_R (the aft bay section, where the belly ramp starts at the blockout's UPSWEEP_START),
tailcone (the V-tail roots' section, to where the laser lens begins), spine_cover (the lid over the AWACS beam
well), radar_R_fairing (the tail radar's dielectric panel), laser_turret and laser_barrel (the back end's lens and its
emitter), baydoor_AL/AR (their _visible meshes). Hull parts are the blockout's fus_point surface at 64 vertices a ring,
joints at stations 17, 25 and 33; the wing fairing is step 6.1's teardrop (build_wingfairing_s61) at finished
resolution, a panel ending in a lap edge on the body, swelling out over the wing root's upper skin into which it tucks
along one line (Fairing), and filleted onto the root's lower skin and the body under it (RootFillet). The belly's
blend into the ramp follows the blockout's rings; the tail cone's skin ends at its last hull ring, where the laser lens
carries its section on to a pole (fuselage_aft_laser). The AWACS well's slot runs through
the crown of fuselage_M, fuselage_R and tailcone as the blockout cuts it (fuselage_aft_well), under the spine cover;
the aft bay's cavity through the belly of fuselage_M and fuselage_R, across their joint (fuselage_aft_bay).

Ground clearance: the belly ramp runs parallel to the 10.5 deg strike line, about 4 cm inside it, so nothing on the
ramp stands prouder than the blockout's bay doors (0.045) and radar panel (0.035); check() reruns the strike.

Boundaries: the V-tail roots on the tail cone, the sponsons and the strut roots on fuselage_M and fuselage_R stay plain
hull (their groups own the fillets); the fairing's skin inside the wing roots and the hull's inside the sponsons and
V-tails go to aircraft_structure.

UV islands: the -X half of each hull part reuses the +X half's islands, except on the station bands that carry text
(TEXT_BANDS), where both halves are unique so stencils read the right way round; the fairing does the same with its own
bands; the right bay door reuses the left's.

Positions are (station, angle) on the fuselage, as in nose.py: angle in degrees from the top, positive toward +X (the
left wing). Shapes listed for the +X side are mirrored to -X."""

import math

import bpy
import numpy as np
from mathutils import Vector

from . import fuselage_aft_bay as bay
from . import body_structure
from . import fuselage_aft_laser as laser
from . import nose_bay, render
from . import surface as sf
from .fuselage_aft_well import cut_well
from .surface import CHINE_K, DOOR, FITTING, HULL, KEEL, N, RADOME

GROUP = "fuselage_aft"
PARTS = ("fuselage_M", "wingfairing", "fuselage_R", "tailcone", "spine_cover", "radar_R_fairing", "laser_turret",
         "laser_barrel", "baydoor_AL_visible", "baydoor_AR_visible")
BUDGET_TRIS = 26400  # 23,400 before the damage structure and the tail cone's curve rings (curve_rings)
MIRROR_PARTS = {"baydoor_AR_visible": "baydoor_AL_visible"}
STOCK_SLOTS = (laser.LENS,)

# Paint classes past the shared ones (surface.py 1 to 5, the wing's 11 to 23). They stay off HULL and RADOME, whose
# faces take the fuselage surface's own normals (detail_centurion.hull_normals): wrong on the blister and the lids'
# bevels.
FAIRING, DIELECTRIC, SPINE, FILLET, WELL = 31, 32, 34, 36, 37

# Close-ups (m4/render.py's view form); the first four make the contact sheet.
VIEWS = {
    "aft34": (40, (13.5, 55.0, 11.0), (0.0, 34.0, 4.6)),
    "aft_side": (("ortho", 30.0, render.SIDE), (30.0, 31.0, 4.4), None),
    "tail_close": (50, (4.6, 48.8, 6.9), (0.0, 42.6, 4.9)),
    "fairing34": (38, (11.5, 7.5, 13.5), (0.0, 20.5, 6.4)),
    "aft_belly": (("ortho", 30.0, (180, 0, 90)), (0.0, 31.0, -30.0), None),
    "aft_top": (("ortho", 30.0, render.TOP), (0.0, 31.0, 60.0), None),
    "aft_low": (34, (-9.0, 47.0, 1.0), (0.0, 31.0, 2.9)),
    "root_fillet": (32, (4.3, 11.0, 4.5), (2.2, 19.0, 5.6)),
    "front_lip": (40, (5.0, 6.5, 9.2), (0.8, 13.0, 6.6)),
    "le_root": (40, (6.5, 9.5, 7.6), (1.6, 15.2, 6.3)),
    "laser_side": (("ortho", 4.4, render.SIDE), (30.0, 43.7, 4.6), None),
    "laser_rear34": (45, (4.6, 49.6, 6.4), (0.0, 43.9, 4.6)),
}

# ---------- layout ----------
JOINTS = (17.0, 25.0, 33.0)
# The aft bay door (stations, angles), +X side: the blockout's, its free edge carried on to the keel line, where the
# doors close against each other, as the forward bay's (nose.BAY_DOOR).
BAY_DOOR = (23.6, 32.6, 141.0, 180.0 - bay.DOOR_SEAM / 2)
# The bay frame's outboard fastener row: between the door's hinge edge and the sponson's lower fillet, which lands on
# the hull at 139.2 deg at most beside the door (struts group)
BAY_FRAME = 140.1
RAMP_S = 30.86  # the blockout's UPSWEEP_START, the middle of the belly's blend into the ramp
# Ring vertices moved onto the doors' hinge lines and the blockout's door edges over the bay (all of fuselage_R's rings):
# the bay's walls rise from the hinge columns (fuselage_aft_bay)
DOOR_COLUMNS = {25: 141.0, 39: 219.0, 31: 178.6, 33: 181.4}
# Station bands whose hull rows keep unique islands on both sides: the text and the insignia sit inside them
TEXT_BANDS = ((25.6, 27.8), (28.75, 30.45), (30.86, 33.0), (35.4, 37.6), (40.4, 41.6))
# Hull rings. The barrel (to 37) and the belly ramp are ruled, so rings sit only where a feature, a band or the
# curving tail needs one: the door ends and the crease, the radar panel's ends (40.9, 43.5), and the spine cover's
# ends, where the AWACS well's lip starts (well_rings, from the blockout).
FUS_M_ST = (17.0, BAY_DOOR[0], 25.0)
FUS_R_ST = (25.0, RAMP_S, 31.9, BAY_DOOR[1], 33.0)
TAIL_UV_CUT = 38.3  # the tail cone's island is cut here, so no island runs past 8 m
# The skin ends at the last ring, LENS_S, and the laser lens carries the cone on from there (fuselage_aft_laser): the
# tail cone's end section, 3 cm aft of where the tail radar's panel ends (RADAR), so the panel's proud rim stays on skin
LENS_S = 43.53
TAIL_ST = (33.0, 37.0, 37.6, TAIL_UV_CUT, 38.9, 39.5, 40.0, 40.4, 40.9, 41.6, 42.1, 42.6, 43.1, 43.5, LENS_S)
# m: the tail cone's rings are added (curve_rings) until the skin's straight runs stay this close to the boat-tail's
# curve: the lining (body_structure) lies af.WALL inside the true surface, and showed through runs that sagged more
CURVE_TOL = 0.005

RADAR = (40.9, 43.5, 140.0, 220.0)  # the blockout's tail radar panel
RADAR_RISE = (0.004, 0.006, 0.008)  # keep the render rim above the cone's facets, inside the collider band
RADAR_DOWN = -0.01

BALL_S = 44.3  # the turret's pivot station (the blockout's ball centre)

FAIRING_UV_CUTS = (15.4, 20.0)
FAIRING_TEXT_BANDS = ((12.8, 13.6),)
SPINE_RISE = (0.012, 0.03, 0.04)  # spine cover height on its rim, the bevel row and inside; the blockout's is 0.045
SPINE_DOWN = 0.004
SPINE_SEGMENTS = 5  # the cover in five lids, each a pair of clamshell halves hinged on the outer edges

BLADES = (  # station, angle, height, root chord, tip chord, sweep, part
    (18.4, 180.0, 0.34, 0.38, 0.15, 0.2, "fuselage_M"),  # UHF, ventral, between the sponsons
    (22.75, 180.0, 0.24, 0.30, 0.12, 0.13, "fuselage_M"),  # VHF, ventral, ahead of the aft bay's spoiler
    (32.1, 26.0, 0.16, 0.24, 0.10, 0.08, "fuselage_R"),  # ESM, either side of the spine cover's aft end
    (32.1, -26.0, 0.16, 0.24, 0.10, 0.08, "fuselage_R"),
    (35.7, 0.0, 0.34, 0.40, 0.15, 0.21, "tailcone"),  # data link, dorsal, behind the spine cover
)
DRAIN_MAST = (22.2, 180.0)
GPS_DOME = (39.3, 0.0)
BEACON = (37.8, 0.0)  # red anti-collision light on the cone's crown, above the V-tail roots
TAIL_LIGHT = (43.42, 0.0)  # white tail position light at the lens's edge, looking aft
# Formation strips, both sides: (station, angle) of the lower end, the station the upper end leans back to, part. Each
# is the shared size (docs/M4-ART-PLAN.md rule 5): 0.6 m along the girth, 0.08 m wide.
FORMATION_STRIPS = ((22.18, 82.0, 22.38, "fuselage_M"), (40.14, 66.0, 40.3, "tailcone"))
FORMATION_SIZE = (0.6, 0.08)
MAWS = ((42.55, 50.0), (42.55, 112.0))  # missile warning sensors looking aft, both sides
COOLANT_VENT = (41.95, 92.0)  # the laser's coolant exhaust, both sides
# On the fairing, as (station, x): the IFF blade on the crest behind the hump, the upper anti-collision beacon on the
# crest where it leaves the crown, the wing ice inspection lights on the forward shoulders looking outboard.
FAIRING_BLADE = (20.9, 0.0, 0.30, 0.38, 0.15, 0.2)
FAIRING_BEACON = (12.9, 0.0)
INSPECTION_LIGHT = (13.9, 1.2)


# ---------- the wing fairing ----------
FAIRING_COLS = 21  # columns a side from the crest to where the fairing lands on the body, spaced along its arc
# The section reaches the body this many degrees into it (step 6.1 lands tangent), so it crosses the 64-vertex hull
# along one clean line instead of grazing the facets (a saw-tooth), then runs on into the body at the second angle
# for the third's length. Under the skin the crest sinks FAIRING_SINK times as fast as the blockout's ramp.
FAIRING_LAND = (2.0, 60.0, 0.03)
FAIRING_SINK = 4.0
# The fairing is a panel laid on the skin: where it would feather out it stands FAIRING_LIP[0] proud of the body (a
# smooth maximum of radius [1]) and ends in a lap edge, the steep run-in above (aircraft_structure, which reads as the
# joint's shadow line). Ahead of and behind the stations where its crest leaves the crown (lap_stations), the sunk
# rings drop a further [2], so the front and aft edges are one ring-aligned line across the crown, not a feather
# wandering over the hull's facets.
FAIRING_LIP = (0.012, 0.012, 0.012)
# Over the wing root the fairing is the root's upper skin with a swell on it (Fairing.section): as high as the
# teardrop's crest at the centreline, falling to nothing FAIRING_FILLET[0] metres out (Fairing.reach: nearer where the
# landing or the root's leading edge is nearer), where it meets the analytic skin [1] degrees into it along a ring
# column; then diving inside the root at [2] m per m squared to rejoin its own curve; [3] the smooth maximum with the
# teardrop. Under the root the flank meets the root's lower skin; RootFillet turns one into the other.
FAIRING_FILLET = (1.6, 4.0, 4.0, 0.04)
# The swell lands FAIRING_TUCK[4] over that skin, then drops [0] under it within [1] (the next column), steeper than
# the 50 deg hard-edge angle: a lap edge along the column. The detailed root's facets sag under its analytic skin,
# never over it, and the landing's straight run between two rings sags under the curved skin by less than [4], so the
# fairing goes in along the column whatever either tessellation, and is deeper than the smoothness report's 4 cm
# reach before it turns back (rule 9). [2]: how far behind the leading edge (as a chord fraction) the swell may land,
# so it never wraps the nose; [3]: from where that allows FAIRING_SPLIT[2], the landing runs out at most this many
# metres a metre of station, against the leading edge's own 2.9, so the ring columns along it lean over gently.
FAIRING_TUCK = (0.05, 0.03, 0.03, 0.7, 0.008)
# The section's columns: this many intervals from the crest to the swell's landing, one down the tuck, the rest to
# the lap edge; [1] keeps the landing that far inside the lap edge, so the outer flank keeps its columns. Near the
# leading edge, where the swell lands inside the teardrop (hidden), the split stays [2] out, so the columns ahead of
# the wing never crowd onto the crest.
FAIRING_SPLIT = (5, 0.35, 1.2)
FAIRING_INNER = 0  # the buried underside closes directly between the two run-in points
FAIRING_STEP = 0.65
FAIRING_FINE = (11.4, 13.6, 0.22)  # closer rings where the crest leaves the crown at a grazing angle
FAIRING_NOSE = (14.7, 17.0, 0.1)  # and where the root's leading edge comes through the flank


def smax(a, b, k):
    """Smooth maximum of radius k (scalars or arrays)."""
    h = np.clip(k - np.abs(a - b), 0.0, None) / k
    return np.maximum(a, b) + h * h * k / 4


def smin(a, b, k):
    h = np.clip(k - np.abs(a - b), 0.0, None) / k
    return np.minimum(a, b) - h * h * k / 4


def wing_station_point(bl, x, s, upper):
    """Intersect the pitched airfoil with the station plane, including thickness's longitudinal offset."""
    le, chord, thick = bl.wing_le(1, float(x))
    target = bl.st(s)
    def point(f):
        return bl.airfoil_point(le, chord, thick, bl.CDIR, bl.TDIR, bl.WING_CAMBER, f, upper)
    a, b = 0.0, 1.0
    qa, qb = point(a), point(b)
    if target <= qa.y:
        return qa
    if target >= qb.y:
        return qb
    ya, yb = qa.y - target, qb.y - target
    f = min(max((target - le.y) / (chord * bl.CDIR.y), a), b)
    for _ in range(16):
        f = min(max(f, a), b)
        q = point(f)
        error = q.y - target
        if abs(error) < 1e-6:
            return q
        if error < 0:
            a, ya = f, error
        else:
            b, yb = f, error
        f = (a * yb - b * ya) / (yb - ya)
    return q


class Fairing:
    """Step 6.1's wing fairing (build_centurion.build_wingfairing_s61) at finished resolution: a smoothstep teardrop
    along the body, each section a level crest curving down to the body (a Hermite curve). Finishing changes: the
    curve lands FAIRING_LAND degrees into the body and ends in a lap edge FAIRING_LIP proud of it; where the wing
    root's upper skin comes through the flank the section turns onto it along a fillet (FAIRING_FILLET) instead of
    being pierced; under the root RootFillet turns the root's lower skin into the flank. Sections are heights over the
    half width x; point(s, x) on the +x side, negative x mirrored."""

    def __init__(self, bl):
        self.bl, p = bl, bl.S61_FAIRING
        self.s0 = bl.WING_ROOT_LE_STATION + p["start"]
        self.peak = bl.WING_ROOT_LE_STATION + p["peak"] * bl.CHORD[0][1]
        self.s1 = bl.S6_WELL_START - 0.1
        self.cache = {}
        self.lap = self.lap_stations()

    def k(self, s):
        sm = self.bl.smooth
        return sm((s - self.s0) / (self.peak - self.s0)) if s < self.peak else sm((self.s1 - s) / (self.s1 - self.peak))

    def lap_stations(self):
        """The stations where the crest leaves the crown (front) and sinks back into it (aft): the lap edge's ends."""
        p = self.bl.S61_FAIRING
        target = p["bury"] / (p["rise"] + p["bury"])

        def solve(a, b, rising):
            for _ in range(50):
                m = (a + b) / 2
                a, b = (m, b) if (self.k(m) < target) == rising else (a, m)
            return (a + b) / 2
        return solve(self.s0, self.peak, True), solve(self.peak, self.s1, False)

    def body_z(self, s, x):
        w, tb, bb = self.bl.fus_profile(s)
        return (tb + bb) / 2 + (tb - bb) / 2 * np.sqrt(np.clip(1 - (np.asarray(x) / w) ** 2, 0.0, None))

    def wing_top(self, x, s):
        """The left root's upper skin over (x, s); off its chord it falls away steeply, so the fillet fades out within
        a few centimetres of the leading and trailing edges instead of stopping at a ring."""
        bl = self.bl
        le, c, t = bl.wing_le(1, x)
        frac = (bl.st(s) - le.y) / (c * bl.CDIR.y)
        z = wing_station_point(bl, x, s, True).z
        return z - c * (0.6 * max(-frac, 0.0) + 2.0 * max(frac - 1, 0.0))

    def reach(self, s, land):
        """Where the swell over the root meets its analytic upper skin: FAIRING_FILLET[0] out, inside the lap edge
        (land) and FAIRING_TUCK[2] of the chord behind the swept leading edge."""
        bl = self.bl

        def behind(x):  # the leading edge sweeps back outboard, so this falls as x rises
            le, c, _ = bl.wing_le(1, x)
            return bl.st(s) - le.y - FAIRING_TUCK[2] * c * bl.CDIR.y

        x = FAIRING_FILLET[0]
        if behind(x) < 0:
            a, b = 0.0, x
            for _ in range(30):
                m = (a + b) / 2
                a, b = (m, b) if behind(m) >= 0 else (a, m)
            x = a
        x0 = FAIRING_SPLIT[2]
        ramp = x0 + behind(x0) * FAIRING_TUCK[3]  # behind(x0): how far s is past the station that first allows x0
        return max(min(x, ramp, land - FAIRING_SPLIT[1]), 0.0)

    @staticmethod
    def split(reach, land, s):
        """The x of the column where the section's inner columns end (the swell's landing, see FAIRING_SPLIT)."""
        t = min(max((21.5 - s) / 1.5, 0.0), 1.0)
        floor = FAIRING_SPLIT[2] * t * t * (3 - 2 * t)
        return min(max(reach, floor), land - FAIRING_SPLIT[1])

    def section(self, s):
        """The +x half from the crest to the landing (dense, x rising), then the run-in point under the skin: (xs, zs,
        the landing's x, the x where the fairing goes under the wing's upper skin or None, the swell's reach)."""
        if s in self.cache:
            return self.cache[s]
        bl, p = self.bl, self.bl.S61_FAIRING
        k = self.k(s)
        crown = bl.fus_profile(s)[1]
        rise = (p["rise"] + p["bury"]) * k - p["bury"]
        top = crown + (rise if rise >= 0 else rise * FAIRING_SINK)
        phi = math.radians(p["phi_end"] + (p["phi_mid"] - p["phi_end"]) * k)
        skin, tan = bl.body_point(s, phi)
        w, tb, bb = bl.fus_profile(s)
        n_out = Vector((math.sin(phi) / w, 0, math.cos(phi) / ((tb - bb) / 2))).normalized()
        a, b, run = math.radians(FAIRING_LAND[0]), math.radians(FAIRING_LAND[1]), FAIRING_LAND[2]
        t_in = tan * math.cos(a) - n_out * math.sin(a)
        crest = Vector((0, skin.y, top))
        span = (skin - crest).length
        pts = bl.hermite(crest, Vector((span, 0, 0)), skin, t_in * span, 60) + [skin + (tan * math.cos(b) - n_out * math.sin(b)) * run]
        xs, zs = np.array([q.x for q in pts]), np.array([q.z for q in pts])
        lip, lip_k, drop = FAIRING_LIP
        if rise >= 0:  # a plate at least lip over the body up to the landing, which becomes the lap edge
            hb = zs[:-1] - self.body_z(s, xs[:-1])
            zs[:-1] += smax(hb, lip, lip_k) - hb
        else:
            zs -= drop
        _, land_deg, dive, k_b = FAIRING_FILLET
        depth, foot, _, _, rim = FAIRING_TUCK
        reach = max(float(self.reach(s, skin.x)), 0.1)
        aft_reach = smin(reach, FAIRING_FILLET[0] * bl.smooth((self.s1 - 0.25 - s) / 3.5), 0.15)
        reach = max(float(reach + (aft_reach - reach) * bl.smooth((s - 19.8) / 1.0)), 0.1)
        # Aft, where the root's skin at the landing sinks toward the body (its tuck would cut into the hull), the
        # landing moves in to where the teardrop itself goes under that skin, and there the swell sinks away.
        wt = np.array([self.wing_top(float(x), s) for x in xs])
        crossing = next((i for i in range(len(xs) - 1) if wt[i] > zs[i]), None)
        td = None
        if crossing is not None:
            i = crossing
            td = float(xs[0]) if i == 0 else float(np.interp(0.0, [wt[i - 1] - zs[i - 1], wt[i] - zs[i]], xs[i - 1:i + 1]))
        fade = bl.smooth((self.wing_top(reach, s) - float(self.body_z(s, reach)) - 0.05) / 0.06)
        if td is not None and td < reach:
            reach = td + (reach - td) * fade
        # the swell's landing and the foot of its tuck are samples of the section, so the columns there are exact
        split = self.split(reach, skin.x, s)
        xv = np.union1d(xs[:-1], [reach, reach + foot, split, split + foot])
        zs = np.append(np.interp(xv, xs[:-1], zs[:-1]), zs[-1])
        xs = np.append(xv, xs[-1])
        wt = np.array([self.wing_top(float(x), s) for x in xs])
        le, te = (bl.wing_le(1, 0.0)[0].y + bl.Y0 + d for d in (0.0, bl.wing_le(1, 0.0)[1] * bl.CDIR.y))
        present = bl.smooth((s - le) / 0.3) * bl.smooth((te - s) / 0.3)  # the root under the crest
        present *= bl.smooth(fade / 0.25)
        # crest height over the skin at the centreline, falling as a Hermite curve that leaves the crest level and
        # lands land_deg into the skin (at most the slope that keeps the curve from rising first)
        A = max(zs[0] - wt[0] - rim, 1e-4)
        k = min(math.tan(math.radians(land_deg)) * reach / A, 3.0)
        u = xs / reach
        uc = np.minimum(u, 1.0)
        swell = rim + A * (1 - 3 * uc ** 2 + 2 * uc ** 3 + k * (uc ** 2 - uc ** 3))
        swell -= (rim + depth) * np.clip((xs - reach) / foot, 0.0, 1.0)
        over = wt + swell - dive * np.maximum(0.0, u - 1) ** 2 - (1 - present)
        zs = smax(zs, over, k_b + 0.08 * (1 - bl.smooth((s - le - 0.3) / 0.3)))
        # Above the root, the crest ends on the same landing column instead of letting the teardrop pierce it again.
        cap_weight = np.clip((wt - self.body_z(s, xs)) / 0.02, 0.0, 1.0) * bl.smooth((s - 19.8) / 1.0)
        capped = np.minimum(zs, np.maximum(wt + swell - dive * np.maximum(0.0, u - 1) ** 2,
                                           self.body_z(s, xs) - 0.02))
        zs = zs + (capped - zs) * cap_weight * (xs >= reach)
        cross = next((i for i in range(len(xs) - 1) if wt[i] > zs[i]), None)
        out = (xs, zs, skin.x, None if cross is None else float(xs[cross]), reach)
        self.cache[s] = out
        return out

    def z(self, s, x):
        xs, zs = self.section(s)[:2]
        return float(np.interp(abs(x), xs[:-1], zs[:-1]))

    def columns(self, s):
        """FAIRING_COLS + 1 x positions from the crest to the landing: FAIRING_SPLIT[0] intervals evenly spaced along
        the section's arc to the swell's landing on the root, one down its tuck, the rest evenly to the lap edge."""
        xs, zs, land, _, reach = self.section(s)
        split = self.split(reach, land, s)
        xv, zv = xs[:-1], zs[:-1]
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xv), np.diff(zv)))])
        a, b = (float(np.interp(x, xv, cum)) for x in (split, split + FAIRING_TUCK[1]))
        n_in, n_out = FAIRING_SPLIT[0], FAIRING_COLS - FAIRING_SPLIT[0] - 1
        arcs = [a * j / n_in for j in range(n_in + 1)] + [b + (cum[-1] - b) * j / n_out for j in range(n_out + 1)]
        return [float(np.interp(c, cum, xv)) for c in arcs]

    def point(self, s, x):
        return Vector((x, self.bl.st(s), self.z(s, x)))

    def normal(self, s, x):
        u = self.point(s + 0.02, x) - self.point(s - 0.02, x)
        v = self.point(s, x + 0.01) - self.point(s, x - 0.01)
        return v.cross(u).normalized()

    def ring(self, s):
        """+x half and -x half over the crest, then back under inside the body: the -x run-in point is column 0, the
        -x landing column 1, the crest column FAIRING_COLS + 1."""
        bl = self.bl
        xs, zs = self.section(s)[:2]
        original = [self.point(s, x) for x in self.columns(s)] + [Vector((xs[-1], bl.st(s), zs[-1]))]
        half = []
        weight, radius = bl.smooth((14.2 - s) / 2.0), 0.6
        for i, base in enumerate(original):
            station = s
            for _ in range(8):
                edge = self.section(station)[0][-1]
                x = edge if i == len(original) - 1 else self.columns(station)[i]
                corner = max(0.0, x - (edge - radius))
                next_station = s + (radius - math.sqrt(max(radius * radius - corner * corner, 0.0))) * weight
                if abs(next_station - station) < 1e-7:
                    break
                station = next_station
            edge_x, edge_z = (v[-1] for v in self.section(station)[:2])
            q = Vector((edge_x, bl.st(station), edge_z)) if i == len(original) - 1 else self.point(station, self.columns(station)[i])
            if s < self.lap[0]:
                q.z = float(self.body_z(station, q.x)) + base.z - float(self.body_z(s, base.x))
            half.append(q)
        upper = [Vector((-q.x, q.y, q.z)) for q in reversed(half)] + half[1:]
        w, tb, bb = bl.fus_profile(s)
        zc, h = (tb + bb) / 2, (tb - bb) / 2
        phi = math.atan2(half[-1].x / w, (half[-1].z - zc) / h)
        inner = [bl.body_point(s, phi - 2 * phi * j / (FAIRING_INNER + 1), 0.9)[0] for j in range(1, FAIRING_INNER + 1)]
        return upper + inner


class RootFillet:
    """One fairing shell owns the skirt and the lower root blend. Its upper skin ends inside the wing; a buried
    bridge reaches the lower skin, and a concave cubic turns onto a body-following landing ramp. Both landings
    enter their neighbour at three degrees. The lower wing edge starts 15 mm inside its actual facets, rather than
    forming a lap that could hang below the leading edge. The aft taper and closing cap stay inside the hull."""

    def __init__(self, bl, fairing):
        self.bl, self.f = bl, fairing
        self.wing_lands = {}
        from .wing import ROOT_N, ROOT_STATIONS, LANDING_LIGHT
        # The fillet stays in the first root bay. Interpolate its two rings, as the wing loft does, rather than
        # resampling the airfoil at x: thickness varies nonlinearly between those rings.
        end = min(x for x in (*ROOT_STATIONS, *bl.WING_UV_CUTS, *LANDING_LIGHT,
                              *(x0 - 0.048 for _, x0, _, kind in bl.SURFACES if kind != 'spoiler')) if x > 0)
        self.wing_rings = [bl.airfoil(*bl.wing_le(1, x), bl.CDIR, bl.TDIR, bl.WING_CAMBER, n=ROOT_N)
                           for x in (0.0, end)]
        self.wing_bay = end

    def wing_skin(self, x, s, upper):
        """The detailed root's faceted skin; using its ideal airfoil leaves a lip between the two tessellations."""
        from .wing import ROOT_N
        bl = self.bl
        ring = [a.lerp(b, x / self.wing_bay) for a, b in zip(*self.wing_rings)]
        points = ring[:ROOT_N + 1][::-1] if upper else ring[ROOT_N:]
        z = float(np.interp(bl.st(s), [q.y for q in points], [q.z for q in points]))
        return Vector((x, bl.st(s), z))

    def wing_poly(self, s):
        """The root's section in the station plane, x from 0 outboard: (closed polygon, its lower skin x rising)."""
        bl = self.bl

        def frac(x):
            le, c, t = bl.wing_le(1, float(x))
            return (bl.st(s) - le.y) / (c * bl.CDIR.y)

        def at(x, upper):
            x = float(x)
            q = wing_station_point(bl, x, s, upper)
            return (x, q.z)

        def crossing(x0, x1, target):
            f0 = frac(x0) - target
            for _ in range(30):
                m = (x0 + x1) / 2
                x0, x1 = (m, x1) if (frac(m) - target > 0) == (f0 > 0) else (x0, m)
            return (x0 + x1) / 2

        grid = [x * 0.05 for x in range(91)]
        ok = [0.0 <= frac(x) <= 1.0 for x in grid]
        if not any(ok):
            return None, None
        i0, i1 = ok.index(True), len(ok) - 1 - ok[::-1].index(True)
        xl = grid[i0:i1 + 1]
        if i0 > 0:  # behind the trailing edge inboard (it sweeps a little)
            xl = [crossing(grid[i0 - 1], grid[i0], 1.0)] + xl
        tip = crossing(grid[i1], grid[i1 + 1], 0.0) if i1 < len(grid) - 1 else None
        top = [at(x, True) for x in xl]
        bot = [at(x, False) for x in xl]
        if tip is not None:
            top.append(at(tip, True))
        return np.array(top + bot[::-1]), np.array(bot + top[-1:] if tip is not None else bot)

    def ring(self, s):
        original = self.f.ring(s)
        if s > self.f.lap[1]:
            weight = self.bl.smooth((s - self.f.lap[1]) / 0.15)
            for q in original:
                q.z += weight * (min(q.z, float(self.f.body_z(s, q.x)) - 0.06) - q.z)
        self.wing_lands[s] = False
        wing, bottom = self.wing_poly(s)
        if wing is None:
            return original
        bl = self.bl
        w, top, bot = bl.fus_profile(s)
        zc, h = (top + bot) / 2, (top - bot) / 2

        def body(q):
            return math.hypot(q[0] / w, (q[1] - zc) / h) - 1

        distances = [body(q) for q in bottom]
        crossing = next((i for i in range(1, len(bottom)) if distances[i] > 0 >= distances[i - 1]), None)
        if crossing is None:
            return original
        a, b = bottom[crossing - 1].copy(), bottom[crossing].copy()
        for _ in range(24):
            q = (a + b) / 2
            a, b = (q, b) if body(q) < 0 else (a, q)
        joint = (a + b) / 2
        fade = bl.smooth((23.8 - s) / 0.7)
        room = float(bottom[-1, 0] - joint[0])
        reach = min(0.55 * fade, room * 0.72)
        x = float(joint[0] + reach)
        z = self.wing_skin(x, s, False).z
        eps = min(0.015, max(room * 0.1, 0.001))
        slope = (self.wing_skin(x + eps, s, False).z - self.wing_skin(x - eps, s, False).z) / (2 * eps)
        tangent = np.array([1., slope])
        tangent /= np.linalg.norm(tangent)
        normal = np.array([tangent[1], -tangent[0]])
        A = np.array([x, z]) - normal * (0.015 * fade + 0.035 * (1 - fade))
        A[0] -= 0.10 * (1 - fade)  # close inside the hull while the root still covers the connector
        angle = math.radians(3.)
        ta = -tangent * math.cos(angle) + normal * math.sin(angle)

        xs, zs = self.f.section(s)[:2]
        phi_joint = math.atan2(joint[0] / w, (joint[1] - zc) / h)
        phi_edge = math.atan2(xs[-2] / w, (zs[-2] - zc) / h)
        height = 0.045 * fade - 0.04 * (1 - fade)
        end_height = 0.004 * fade - 0.02 * (1 - fade)
        run = max((height - end_height) / math.tan(angle), 0.)
        radius = math.hypot(w * math.cos(phi_joint), h * math.sin(phi_joint))
        phi = max(phi_edge - run / radius, phi_joint + 0.04 * fade)
        nb = np.array([math.sin(phi) / w, math.cos(phi) / h])
        nb /= np.linalg.norm(nb)
        tb = np.array([w * math.cos(phi), -h * math.sin(phi)])
        tb /= np.linalg.norm(tb)
        B = np.array([w * math.sin(phi), zc + h * math.cos(phi)]) + nb * height
        tb = tb * math.cos(angle) - nb * math.sin(angle)
        lengths = np.linalg.solve(np.stack([ta, tb], axis=1), B - A)
        lengths = np.clip(lengths, 0., 2 * np.linalg.norm(B - A))
        C, D = A + ta * lengths[0] * 0.56, B - tb * lengths[1] * 0.56
        half = original[FAIRING_COLS + 1:]
        keep = half[:FAIRING_SPLIT[0] + 2]
        q = keep[-1]
        lo, hi = (self.wing_skin(q.x, s, upper).z for upper in (False, True))
        q.z = min(max(q.z, lo + (hi - lo) * 0.35), lo + (hi - lo) * 0.85)
        # The upper-to-lower connector stays inside the wing; the next row crosses its lower skin at three degrees.
        xt = x + min(0.12, (room - reach) * 0.5) * fade - 0.08 * (1 - fade)
        lo = self.wing_skin(xt, s, False).z
        hi = self.wing_skin(xt, s, True).z
        tuck = np.array([xt, lo + min(0.035, (hi - lo) * 0.4)])
        keep.append(Vector((tuck[0], bl.st(s), tuck[1])))
        keep.append(Vector((A[0], bl.st(s), A[1])))
        count = FAIRING_COLS + 1 - len(keep)
        curve = []
        bend = 6
        def cubic(t):
            return (1 - t) ** 3 * A + 3 * (1 - t) ** 2 * t * C + 3 * (1 - t) * t * t * D + t ** 3 * B

        lo, hi = 0.0, 1.0
        for _ in range(24):
            t = (lo + hi) / 2
            q = cubic(t)
            if q[1] > self.wing_skin(q[0], s, False).z:
                lo = t
            else:
                hi = t
        emerge = (lo + hi) / 2
        for t in np.linspace(emerge, 1.0, bend):
            q = cubic(t)
            curve.append(Vector((q[0], bl.st(s), q[1])))
        radius = math.hypot(w * math.cos(phi), h * math.sin(phi))
        for t in np.linspace(0., 1., count - bend + 1)[1:]:
            a = phi + run * t / radius
            nb = np.array([math.sin(a) / w, math.cos(a) / h])
            nb /= np.linalg.norm(nb)
            q = np.array([w * math.sin(a), zc + h * math.cos(a)]) + nb * (height + (end_height - height) * t)
            curve.append(Vector((q[0], bl.st(s), q[1])))
        dive = q + np.array([math.cos(a), -math.sin(a)]) * 0.015 - nb * 0.025
        curve.append(Vector((dive[0], bl.st(s), dive[1])))
        half = keep + curve
        self.wing_lands[s] = True
        return [Vector((-q.x, q.y, q.z)) for q in reversed(half)] + half[1:]


class FairingCoords:
    """Station and signed girth from the crest of points on the fairing (paint coordinates, as
    paint.FuselageCoords gives the hull's): a girth table over x per station, read at the texel's |x|. Also, per
    station, the girth of the lap edge (the landing) and of the line where the wing's upper skin comes through."""

    def __init__(self, fairing, ds=0.05):
        self.f, self.Y0, self.ds = fairing, fairing.bl.Y0, ds
        self.s = np.arange(fairing.s0, fairing.s1 + ds, ds)
        self.x, self.arc, self.edge, self.wing = [], [], [], []
        for s in self.s:
            xs, zs, _, xc, *_ = fairing.section(s)
            xs, zs = xs[:-1], zs[:-1]
            arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(zs)))])
            self.x.append(xs)
            self.arc.append(arc)
            self.edge.append(arc[-1])
            if xc is not None:
                le, chord, _ = fairing.bl.wing_le(1, xc)
                fraction = (fairing.bl.st(s) - le.y) / (chord * fairing.bl.CDIR.y)
                if not 0.0 <= fraction <= 1.0:
                    xc = None
            self.wing.append(np.interp(xc, xs, arc) if xc is not None else 99.0)
        self.edge, self.wing = np.array(self.edge), np.array(self.wing)

    def index(self, s):
        row = np.clip((s - self.s[0]) / self.ds, 0, len(self.s) - 1)
        i = np.minimum(row.astype(int), len(self.s) - 2)
        return i, row - i

    def interpolate(self, values, s):
        i, t = self.index(s)
        return values[i] * (1 - t) + values[i + 1] * t

    def locate(self, pos):
        s = pos[:, 1] + self.Y0
        i, t = self.index(s)
        a = np.array([np.interp(abs(x), self.x[k], self.arc[k]) for x, k in zip(pos[:, 0], i)])
        b = np.array([np.interp(abs(x), self.x[k + 1], self.arc[k + 1]) for x, k in zip(pos[:, 0], i)])
        arc = a * (1 - t) + b * t
        return s, np.sign(pos[:, 0] + 1e-12) * arc


# ---------- builders ----------
def side_corners(corners, side):
    return [(s, side * a) for s, a in corners]


def light(p, c, n, skin, colour_slot, r=0.11, struct=None, sink=0.05):
    """A light: a low skin-coloured base with a lens dome on it (as nose.py's beacons). With struct, the base's
    buried faces are structure."""
    seg = 16 if r < 0.1 else 20
    base = sf.revolve_axis(p, ((r, -sink), (r * 0.82, 0.032), (0, 0.032)), c, n, seg, skin, FITTING)
    profile = ((r * 0.68, 0.02), (r * 0.64, 0.07), (r * 0.38, 0.105), (0, 0.115)) if r < 0.1 else (
        (r * 0.68, 0.02), (r * 0.68, 0.044), (r * 0.64, 0.07), (r * 0.53, 0.09), (r * 0.38, 0.105), (0, 0.115))
    sf.revolve_axis(p, profile, c, n, seg, colour_slot)
    if struct is not None:
        buried(p, base, c, n, struct)


def buried(p, faces, c, n, struct, depth=0.006):
    """A fitting's faces that lie under the skin it stands on (point c, normal n) are structure: nobody sees them,
    and they would read as creases in the smoothness report's samples near the skin."""
    p.tag([f for f in faces if (f.calc_center_median() - c).dot(n) < -depth], struct)


def in_bands(s0, s1, bands):
    return any(b0 - 1e-6 <= s0 and s1 <= b1 + 1e-6 for b0, b1 in bands)


def mirror_rows(p, g, bands, rows=None):
    """The -X half of every row outside the text bands reuses the +X half's islands."""
    rows = [r for r in (rows if rows is not None else range(len(g.stations) - 1))
            if not any(b0 < g.stations[r + 1] and g.stations[r] < b1 for b0, b1 in bands)]
    if rows:
        sf.mirror_columns(p, g, KEEL, N, rows)


def hull_seams(g):
    for k in (0, CHINE_K[0], KEEL, CHINE_K[1]):
        g.seam_column(k)


def well_rings(bl, stations):
    """A hull's ring stations with the spine cover's ends added where they fall inside it: the AWACS well's lip
    starts on them."""
    s0, s1, _ = spine_extent(bl)
    return sf.merge_stations(stations, [s for s in (s0, s1) if stations[0] < s < stations[-1]], near=0.1)


def hull_angles(bl, moved=None, moved_from=-math.inf, moved_to=math.inf):
    """Ring vertex angles (k: deg moved off the even spacing, on the rings from station moved_from to moved_to), with
    columns 1 and N - 1 on the spine cover's sides on the rings over it, where the AWACS well's lip starts."""
    s0, s1, a = spine_extent(bl)
    edge = {1: a, N - 1: 360.0 - a}

    def angle(s, k):
        if k in edge and s0 - 1e-6 <= s <= s1 + 1e-6:
            return edge[k]
        moving = moved_from - 1e-6 <= s <= moved_to + 1e-6
        return (moved or {}).get(k, sf.ring_deg(k)) if moving else sf.ring_deg(k)
    return angle


def well(bl, p, g, skin, struct):
    """The AWACS well's slot through the hull's crown (fuselage_aft_well) under the spine cover, which hides it, its
    lip's -X half on the +X islands outside the text bands."""
    s0, s1, _ = spine_extent(bl)
    for r, pairs in cut_well(bl, p, g, (s0, s1), skin, struct, WELL).items():
        if not in_bands(g.stations[r], g.stations[r + 1], TEXT_BANDS):
            p.mirror_pairs += pairs


def spine_extent(bl):
    """The blockout's spine cover (build_spine_cover): stations and half angle."""
    s0 = bl.S6_WELL_START - 0.03
    s1 = bl.S6_WELL_START + bl.S6_WELL["length"] + 0.03
    return s0, s1, math.degrees(math.asin((bl.S6_WELL["width"] / 2 + 0.03) / bl.FUS_HALF_W))


def ball_centre(bl):
    """The turret's centre, as the blockout's build_tail_systems_s6 places it (the object origin)."""
    _, top, bot = bl.fus_profile(bl.TAIL_END[-1][0])
    return Vector((0, bl.st(BALL_S), (top + bot) / 2))


def curve_rings(surf, stations, tol=CURVE_TOL):
    """stations with rings added between two wherever the skin's straight run would stand off the curved surface by
    more than tol, at the crown, the sides or the belly."""
    def run(a, b):
        m = (a + b) / 2
        sag = max((surf.point(m, d) - (surf.point(a, d) + surf.point(b, d)) / 2).length for d in (0.0, 45.0, 90.0, 135.0, 180.0))
        return [b] if sag <= tol or b - a < 0.2 else run(a, m) + run(m, b)
    return [stations[0]] + [s for a, b in zip(stations, stations[1:]) for s in run(a, b)]


def tail_hull(p, surf, bl, skin, struct):
    """The tail cone: N-vertex rings on the surface to its last ring, where the laser lens takes over; both caps are
    joint faces."""
    stations, angle = curve_rings(surf, well_rings(bl, TAIL_ST)), hull_angles(bl)
    g = sf.Grid(p.bm, [[surf.point(s, angle(s, k)) for k in range(N)] for s in stations])
    p.tag(g.faces(), skin, HULL)
    p.tag(sf.cap(p.bm, g.V[0][::-1]), struct)
    p.tag(sf.cap(p.bm, g.V[-1]), struct)
    g.stations = stations
    return g


def ramp_rings(bl):
    """The blockout's fuselage_R rings over the belly's parabolic blend into the ramp."""
    rs = next(rs for n, rs, _, _ in bl.FUSELAGE if n == "fuselage_R")
    return [s for s in rs if abs(s - bl.UPSWEEP_START) <= bl.RAMP_BLEND + 1e-6]


def build(bl, surf, slots):
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    parts = {}

    def part(name):
        parts[name] = sf.Part(name, (SKIN,))
        return parts[name]

    # ---- fuselage_M ----
    p = part("fuselage_M")
    g = sf.hull(p, surf, well_rings(bl, FUS_M_ST), SKIN, HULL, angles=hull_angles(bl, DOOR_COLUMNS, BAY_DOOR[0]),
                cap_slot=STRUCT)
    hull_seams(g)
    well(bl, p, g, SKIN, STRUCT)
    bay.cut(bl, p, g, BAY_DOOR[0], JOINTS[1], STRUCT)
    mirror_rows(p, g, TEXT_BANDS)
    hull_details(bl, surf, p, "fuselage_M", slots)
    s, a = DRAIN_MAST
    sf.blade(p, surf.point(s, a), surf.normal(s, a), Vector((0, -1, 0)), 0.12, 0.10, 0.05, 0.06, 0.16, SKIN)

    # ---- wingfairing ----
    build_fairing(bl, part("wingfairing"), slots)

    # ---- fuselage_R ----
    p = part("fuselage_R")
    # The door columns stop at the bay's end, so the ring at 33 is the tail cone's own, vertex for vertex
    g = sf.hull(p, surf, sf.merge_stations(ramp_rings(bl), FUS_R_ST, near=0.2), SKIN, HULL,
                angles=hull_angles(bl, DOOR_COLUMNS, moved_to=BAY_DOOR[1]), cap_slot=STRUCT)
    hull_seams(g)
    well(bl, p, g, SKIN, STRUCT)
    bay.cut(bl, p, g, JOINTS[1], BAY_DOOR[1], STRUCT)
    mirror_rows(p, g, TEXT_BANDS)
    hull_details(bl, surf, p, "fuselage_R", slots)
    bay.interior(bl, surf, {n: parts[n] for n in bay.PARTS}, BAY_DOOR, JOINTS[1], slots)
    lo, hi = bl.well_box()
    well_span = (lo.y + bl.Y0, hi.y + bl.Y0)
    for name, (s0, s1) in (("fuselage_M", JOINTS[:2]), ("fuselage_R", JOINTS[1:])):
        body_structure.build_section(bl, surf, parts[name], slots, s0, s1, bays=[BAY_DOOR[:2]], well=well_span)

    # ---- tailcone ----
    p = part("tailcone")
    g = tail_hull(p, surf, bl, SKIN, STRUCT)
    hull_seams(g)
    g.seam_ring(sf.ring_index(g, TAIL_UV_CUT))
    g.seam_ring(sf.ring_index(g, TAIL_ST[-1]))
    well(bl, p, g, SKIN, STRUCT)
    mirror_rows(p, g, TEXT_BANDS)
    hull_details(bl, surf, p, "tailcone", slots)
    tail_details(bl, surf, p, slots)
    lo, hi = bl.well_box()
    body_structure.build_section(bl, surf, p, slots, JOINTS[2], LENS_S, well=(lo.y + bl.Y0, hi.y + bl.Y0))

    # ---- spine_cover ----
    spine_cover(bl, surf, part("spine_cover"), slots)

    # ---- radar_R_fairing: the dielectric lid, its -X half on the +X islands ----
    p = part("radar_R_fairing")
    s0, s1, a0, a1 = RADAR
    ss = [s0, s0 + 0.03, s0 + 0.08] + sf.frange(s0 + 0.08, s1 - 0.08, 0.42)[1:-1] + [s1 - 0.08, s1 - 0.03, s1]
    half = [a0, a0 + 1.5, a0 + 3.5] + sf.frange(a0 + 3.5, 180.0, 6.0)[1:]
    aa = half + [360.0 - a for a in reversed(half[:-1])]

    def radar_up(i, j):
        return RADAR_RISE[min(i, len(ss) - 1 - i, j, len(aa) - 1 - j, 2)]

    T = lid(p, surf, ss, aa, radar_up, RADAR_DOWN, SKIN, DIELECTRIC, STRUCT)
    m = len(aa) - 1
    for r in range(len(ss) - 1):
        for k in range(m // 2, m):
            p.mirror_pairs.append((T.F[r, k], T.F[r, m - 1 - k]))
    T.seam_column(m // 2)

    # ---- laser_turret and laser_barrel: the lens on from the tail cone's last ring, the emitter in its core ----
    laser.lens(bl, surf, part("laser_turret"), TAIL_ST[-1], STRUCT)
    laser.emitter(part("laser_barrel"), ball_centre(bl), MECH)

    # ---- bay doors ----
    for sfx, side in (("L", 1), ("R", -1)):
        bay_door(bl, surf, part(f"baydoor_A{sfx}_visible"), side, slots)
    return parts


def lid(part, surf, ss, aa, outer, inner, slot_top, cls_top, slot_rest):
    """A thin panel conforming to the fuselage over a station x angle grid: the top lifted by outer(i, j), walls down
    to inner round its rim, and a bottom zipped across the rim inside the hull. Returns the top Grid."""
    bm = part.bm
    rows, cols = len(ss), len(aa)
    pts = [[surf.point(s, a) for a in aa] for s in ss]
    nrm = [[surf.normal(s, a) for a in aa] for s in ss]
    T = sf.Grid(bm, [[pts[i][j] + nrm[i][j] * outer(i, j) for j in range(cols)] for i in range(rows)], loop=False)
    rim = ([(0, j) for j in range(cols)] + [(i, cols - 1) for i in range(1, rows)]
           + [(rows - 1, j) for j in range(cols - 2, -1, -1)] + [(i, 0) for i in range(rows - 2, 0, -1)])
    B = [bm.verts.new(pts[i][j] + nrm[i][j] * inner) for i, j in rim]
    walls = []
    for k, (i, j) in enumerate(rim):
        i1, j1 = rim[(k + 1) % len(rim)]
        walls.append(bm.faces.new((T.V[i][j], T.V[i1][j1], B[(k + 1) % len(rim)], B[k])))
        sf.seam(bm, T.V[i][j], T.V[i1][j1])
    part.tag(T.faces(), slot_top, cls_top)
    part.tag(walls + sf.cap(bm, B), slot_rest)
    return T


def build_fairing(bl, p, slots):
    """Step 6.1's teardrop at finished resolution (Fairing): rings along the root's chord facets and closer where the
    crest leaves the crown, FAIRING_COLS columns a side, closed inside the body; its ends are under the skin and capped, its front
    and aft lap edges each a pair of rings a few millimetres apart. RootFillet replaces the outer flank under
    each root with its concave lower blend in the same shell. The -X half reuses the +X islands outside
    FAIRING_TEXT_BANDS."""
    SKIN, STRUCT = slots[0], slots[1]
    fs = Fairing(bl)
    lap0, lap1 = fs.lap
    walls = ((lap0 - 0.006, lap0 + 0.002), (lap1 - 0.002, lap1 + 0.006))
    start, end = lap0 - 0.06, fs.s1  # close before the AWACS well
    must = [start, end, *FAIRING_UV_CUTS, *walls[0], *walls[1]] + [b for band in FAIRING_TEXT_BANDS for b in band]
    a, b, step = FAIRING_FINE
    c, d, nose = FAIRING_NOSE
    rf = RootFillet(bl, fs)
    wing_stations = []
    n = (len(rf.wing_rings[0]) - 1) // 2
    for index in range(n + 1, 2 * n + 1):
        s = rf.wing_rings[0][index].y + bl.Y0
        for _ in range(8):
            half = rf.ring(s)[FAIRING_COLS + 1:]
            x = half[FAIRING_SPLIT[0] + 4].x
            s = rf.wing_rings[0][index].lerp(rf.wing_rings[1][index], x / rf.wing_bay).y + bl.Y0
        wing_stations.append(s)
    fine = [s for s in sf.frange(c, d, nose) if min(abs(s - t) for t in wing_stations) > 0.08]
    base = sorted(set(sf.frange(start, b, step) + sf.frange(b, c, FAIRING_STEP)[1:-1]
                      + fine + [s for s in wing_stations if c < s < end] + [end]))
    ss = sf.merge_stations(base, must, near=0.02)
    g = sf.Grid(p.bm, [rf.ring(s) for s in ss])
    m, crest = len(g.V[0]), FAIRING_COLS + 1
    upper = 2 * crest  # faces 0 .. upper - 1 are the visible section, the rest close it inside the body
    wall_rows = {r for r in range(len(ss) - 1) if (ss[r], ss[r + 1]) in walls}
    sunk = {r for r in range(len(ss) - 1) if ss[r + 1] <= walls[0][0] or ss[r] >= walls[1][1]}  # under the crown
    bridges = {crest + FAIRING_SPLIT[0] + i for i in (1, 2)}
    bridges |= {upper - 1 - k for k in bridges}
    for (r, k), f in g.F.items():
        bridge = k in bridges and rf.wing_lands[ss[r]] and rf.wing_lands[ss[r + 1]]
        if 0 < k < upper - 1 and (r not in wall_rows | sunk or ss[r] > 22.5) and not bridge:  # faces 0 and upper - 1 run into the body
            lower = abs(k + 0.5 - crest) > FAIRING_SPLIT[0] + 3
            root = rf.wing_lands[ss[r]] or rf.wing_lands[ss[r + 1]]
            p.tag([f], SKIN, FILLET if root and lower else FAIRING)
        else:
            p.tag([f], STRUCT)
    p.tag(sf.cap(p.bm, g.V[0][::-1]), STRUCT)
    p.tag(sf.cap(p.bm, g.V[-1]), STRUCT)
    g.seam_column(crest)
    g.seam_column(upper + (m - upper) // 2)
    for c in FAIRING_UV_CUTS:
        g.seam_ring(min(range(len(ss)), key=lambda r: abs(ss[r] - c)))
    for r in range(len(ss) - 1):
        if in_bands(ss[r], ss[r + 1], FAIRING_TEXT_BANDS):
            continue
        for k in range(1, crest):
            p.mirror_pairs.append((g.F[r, k], g.F[r, upper - 1 - k]))
    fairing_details(bl, fs, p, slots)


def fairing_details(bl, fs, p, slots):
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    s, x, h, c0, c1, sw = FAIRING_BLADE
    c, n = fs.point(s, x), fs.normal(s, x)
    buried(p, sf.blade(p, c, n, Vector((0, -1, 0)), h, c0, c1, sw, 0.10, SKIN, bury=0.02), c, n, STRUCT)
    s, x = FAIRING_BEACON
    light(p, fs.point(s, x), fs.normal(s, x), SKIN, LIGHT, struct=STRUCT, sink=0.02)
    s, x = INSPECTION_LIGHT
    for side in (1, -1):
        c, n = fs.point(s, side * x), fs.normal(s, side * x)
        look = (n + Vector((side * 0.6, 0.5, 0.0))).normalized()  # outboard and aft, along the wing's leading edge
        base = sf.revolve_axis(p, ((0.075, -0.02), (0.06, 0.024), (0.0, 0.024)), c, n, 20, SKIN, FITTING)
        buried(p, base, c, n, STRUCT)
        sf.revolve_axis(p, ((0.045, 0.0), (0.045, 0.02), (0.042, 0.028), (0.032, 0.032), (0.0, 0.034)),
                        c, look, 20, WHITE)


def bevel_rows(a, b, inner_step, bevel=(0.02, 0.06)):
    """Grid lines from a to b: two bevel lines in from each end, evenly spaced lines between."""
    mid = sf.frange(a + bevel[1], b - bevel[1], inner_step)
    return [a, a + bevel[0]] + mid + [b - bevel[0], b]


def bay_door(bl, surf, p, side, slots):
    """An aft bay door at rest (closed), hinged on its outboard edge: the blockout's slab (0.006 to 0.045 off the
    skin) with a soft bevel round its rim and rows on the hull's rings over the belly's blend into the ramp, and the
    forward doors' ribs and beam on its inner face (fuselage_aft_bay.door_ribs)."""
    SKIN, STRUCT = slots[0], slots[1]
    s0, s1, a0, a1 = BAY_DOOR
    ss = sf.merge_stations(bevel_rows(s0, s1, 0.9), [s for s in ramp_rings(bl) if s0 < s < s1], near=0.15)
    aa = bevel_rows(a0, a1, (a1 - a0 - 4.0) / 6, (0.6, 1.7))
    pts = [[surf.point(s, side * a) for a in aa] for s in ss]
    nrm = [[surf.normal(s, side * a) for a in aa] for s in ss]
    rise = (0.022, 0.038, 0.044)

    def up(i, j):
        return rise[min(i, len(ss) - 1 - i, j, len(aa) - 1 - j, 2)]

    top, bottom, sides = sf.slab(p, pts, nrm, up, 0.006, SKIN, cls=DOOR)
    p.tag(bottom, STRUCT)
    bay.door_ribs(bl, surf, p, BAY_DOOR, side, STRUCT)


def spine_cover(bl, surf, p, slots):
    """The AWACS lid's clamshell pairs, recessed segment joints and slim hinge beads inside the blockout band."""
    SKIN, STRUCT = slots[0], slots[1]
    s0, s1, a = spine_extent(bl)
    joints = [s0 + (s1 - s0) * i / SPINE_SEGMENTS for i in range(1, SPINE_SEGMENTS)]
    ss = sorted({s0, s0 + 0.02, s0 + 0.06, JOINTS[1], JOINTS[2], s1 - 0.06, s1 - 0.02, s1}
                | {s + d for s in joints for d in (-0.02, -0.005, 0.005, 0.02)})
    aa = bevel_rows(-a, a, 2.4, (0.5, 1.4))

    def up(i, j):
        rise = SPINE_RISE[min(i, len(ss) - 1 - i, j, len(aa) - 1 - j, 2)]
        return rise - 0.01 if min(abs(ss[i] - s) for s in joints) < 0.006 and 1 < j < len(aa) - 2 else rise

    bm = p.bm
    rows, cols = len(ss), len(aa)
    pts = [[surf.point(s, x) for x in aa] for s in ss]
    nrm = [[surf.normal(s, x) for x in aa] for s in ss]
    T = sf.Grid(bm, [[pts[i][j] + nrm[i][j] * up(i, j) for j in range(cols)] for i in range(rows)], loop=False)
    # The underside: over fuselage_R (its parent, which it may sink into) one face across the width per row, sagging
    # inside the hull; over fuselage_M and the tail cone, which it must not cut, the full grid just off the skin.
    strip = [JOINTS[1] <= ss[i] and ss[i + 1] <= JOINTS[2] for i in range(rows - 1)]
    needed = [i in (0, rows - 1) or not (strip[i - 1] and strip[i]) for i in range(rows)]
    B = [[bm.verts.new(pts[i][j] + nrm[i][j] * SPINE_DOWN) if needed[i] or j in (0, cols - 1) else None
          for j in range(cols)] for i in range(rows)]
    bottom = []
    for i in range(rows - 1):
        if strip[i]:  # one face from row i (its whole row where the full grid ends there) to row i + 1
            ring = [v for v in B[i] if v] + [v for v in B[i + 1] if v][::-1]
            bottom.append(bm.faces.new(ring[::-1]))
        else:
            bottom += [bm.faces.new((B[i][j], B[i + 1][j], B[i + 1][j + 1], B[i][j + 1])) for j in range(cols - 1)]
    rim = ([(0, j) for j in range(cols)] + [(i, cols - 1) for i in range(1, rows)]
           + [(rows - 1, j) for j in range(cols - 2, -1, -1)] + [(i, 0) for i in range(rows - 2, 0, -1)])
    sides = []
    for (i, j), (i1, j1) in zip(rim, rim[1:] + rim[:1]):
        sides.append(bm.faces.new((T.V[i][j], T.V[i1][j1], B[i1][j1], B[i][j])))
        sf.seam(bm, T.V[i][j], T.V[i1][j1])
        sf.seam(bm, B[i][j], B[i1][j1])
    sf.seam(bm, T.V[0][0], B[0][0])
    p.tag(T.faces(), SKIN, SPINE)
    p.tag(bottom + sides, STRUCT)
    seg = (s1 - s0) / SPINE_SEGMENTS
    for i in range(SPINE_SEGMENTS):
        for side in (1, -1):
            pts = [surf.point(s, side * (a - 1.1), 0.035)
                   for s in sf.frange(s0 + i * seg + 0.25, s0 + (i + 1) * seg - 0.25, seg)]
            sf.tube(p, pts, 0.01, 6, SKIN, SPINE)


def hull_details(bl, surf, p, owner, slots):
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    fwd = Vector((0, -1, 0))
    for s, a, h, c0, c1, sw, o in BLADES:
        if o == owner:
            sf.blade(p, surf.point(s, a), surf.normal(s, a), fwd, h, c0, c1, sw, 0.10, SKIN)
    length, width = FORMATION_SIZE
    for s0, a0, s1, o in FORMATION_STRIPS:
        if o == owner:
            a1 = a0 - math.degrees(length / bl.fus_profile((s0 + s1) / 2)[0])  # up the girth from the lower end
            corners = ((s0 - width / 2, a0), (s0 + width / 2, a0), (s1 + width / 2, a1), (s1 - width / 2, a1))
            for side in (1, -1):
                # one segment across the strip's width, six along its girth: a single span would sag under the skin
                # and leave only the strip's ends showing
                sf.surface_patch(p, surf, side_corners(corners, side), 1, 6, 0.008, -0.012, FORMATION)


def tail_details(bl, surf, p, slots):
    SKIN, STRUCT, GLASS, MECH, LIGHT, WHITE, FORMATION = slots
    s, a = BEACON
    light(p, surf.point(s, a), surf.normal(s, a), SKIN, LIGHT, struct=STRUCT)
    s, a = GPS_DOME
    c, n = surf.point(s, a), surf.normal(s, a)
    buried(p, sf.revolve_axis(p, ((0.17, -0.05), (0.17, 0.01), (0.158, 0.027), (0.13, 0.04),
                                (0.08, 0.049), (0, 0.052)), c, n, 20, SKIN, FITTING), c, n,
           STRUCT)
    s, a = TAIL_LIGHT
    n = (surf.normal(s, a) + Vector((0, 1.4, 0))).normalized()  # looking aft and a little up
    light(p, surf.point(s, a, -0.02), n, SKIN, WHITE, r=0.07)
    aft = Vector((0, 1, 0))
    for side in (1, -1):
        for s, a in MAWS:
            n = surf.normal(s, side * a)
            axis = (n + aft * 0.7).normalized()
            c = surf.point(s, side * a)
            buried(p, sf.revolve_axis(p, ((0.075, -0.07), (0.075, 0.014), (0.06, 0.03), (0.0, 0.03)), c, axis, 14, SKIN,
                                      FITTING), c, n, STRUCT)
            sf.revolve_axis(p, ((0.046, 0.02), (0.045, 0.04), (0.026, 0.056), (0.0, 0.06)), c, axis, 14, GLASS)
        # the coolant exhaust: a half-buried cowl along the skin with a dark pipe mouth looking aft
        s, a = COOLANT_VENT
        a *= side
        n = surf.normal(s, a)
        t = (surf.point(s + 0.05, a) - surf.point(s - 0.05, a)).normalized()
        c = surf.point(s, a) - n * 0.04
        sf.revolve_axis(p, ((0.0, -0.36), (0.055, -0.28), (0.095, -0.13), (0.11, 0.02), (0.11, 0.16)), c, t, 16,
                        SKIN, FITTING, ref=n)
        sf.revolve_axis(p, ((0.084, 0.06), (0.084, 0.192), (0.068, 0.192), (0.068, 0.17), (0.0, 0.17)), c, t, 16, MECH,
                        ref=n)


def trim(bl, objs, folder):
    """The laser lens's review stand-in (fuselage_aft_laser.lens_look); its opaque material needs no UVs. The check:
    the lens part's outer faces all on laser_lens."""
    laser.lens_look(bpy.data.materials[laser.LENS])
    lens = len(bl.slot_faces(objs["laser_turret"], laser.LENS))
    return {"value": {"lens_faces": lens}, "limit": "the lens part on laser_lens", "pass": lens > 0}


# ---------- checks ----------
def check(bl, objs):
    """build_centurion's checks this group sets, rerun on the whole scene with the detailed meshes: the hangar door
    (span and height), the hangar depth (stations, the spawn at the middle), the 10.5 deg tail strike, no overlap
    between this group's parts and any part they are not jointed to, and the AWACS well open down to its floor; then
    the laser's emitter clear of its lens and the crease where the skin turns to lens (fuselage_aft_laser.checks)."""
    scene = {o.name: o for o in bpy.data.collections["Centurion"].objects}
    stages = {n: o for n, o in scene.items() if "slide_axis" in o}
    saved = {n: o.location.copy() for n, o in stages.items()}
    bl.set_extension(stages, 0.0)  # the hangar and the strike are measured retracted, as the blockout measures them
    meshes = [o for o in scene.values() if o.type == "MESH"]
    allv = [v for o in meshes for v in bl.world_mesh(o)[0]]
    span = max(v.x for v in allv) - min(v.x for v in allv)
    height = max(v.z for v in allv)
    fore, aft = min(v.y for v in allv) + bl.Y0, max(v.y for v in allv) + bl.Y0
    margin = (bl.LENGTH_LIMIT - bl.LENGTH) / 2
    res = {
        "hangar_door_fit": {"value": f"{span:.2f} x {height:.2f}", "limit": f"{bl.HANGAR_DOOR_W} x {bl.HANGAR_DOOR_H}",
                            "pass": span < bl.HANGAR_DOOR_W and height < bl.HANGAR_DOOR_H},
        "hangar_depth_fit": {"value": [round(fore, 3), round(aft, 3)], "limit": f"{-margin:.3f} to {bl.LENGTH + margin:.3f}",
                             "pass": fore >= -margin - 1e-4 and aft <= bl.LENGTH + margin + 1e-4},
    }
    strike = bl.tail_strike(scene)
    res[bl.TAIL_STRIKE_KEY] = {"value": strike["value"], "limit": strike["limit"], "pass": strike["pass"],
                               "first_contact": strike["first_contact"]}
    mine = set(objs)
    found = {k: v for k, v in bl.overlaps({n: o for n, o in scene.items()}).items() if set(k.split("~")) & mine}
    res["no_overlap_unjointed_parts"] = {"value": found, "pass": not found}
    # The blockout's slot_open (build_centurion awacs_well_clear): rays down the AWACS well's centreline from 8 m meet
    # nothing above its floor but the lid, which AwacsBeam hides.
    lo, hi = bl.well_box()
    tree, _ = bl.smooth_tree(scene, [o.name for o in meshes if not o.name.startswith("spine_cover")])
    hits = [tree.ray_cast(Vector((0.0, lo.y + 0.05 + (hi.y - lo.y - 0.1) * k / 100, 8.0)), Vector((0, 0, -1)))[0]
            for k in range(101)]
    top = max((h.z for h in hits if h is not None), default=-math.inf)
    res["awacs_well_open"] = {"value": round(top, 3), "limit": f"highest first hit at the floor, {lo.z:.2f} m",
                              "pass": top <= lo.z + 1e-3}
    # Every stock bay mount on the aft hardpoint, doors closed, as nose.check's bay_fit does for the forward bay
    fit, parts = nose_bay.fit(bl, nose_bay.hardpoint("A"), bay.PARTS + ("baydoor_AL_visible", "baydoor_AR_visible"))
    failing = sorted(m for m, f in fit.items() if f["touches"] or f["in_solid"] or min(f["up"], f["down"]) < bay.ROOM)
    res["bay_fit"] = {"value": {"mounts": fit, "parts": parts, "failing": failing},
                      "limit": f"no store touching a mesh or inside the hull; {bay.ROOM} m or more above and below",
                      "pass": not failing}
    res.update(laser.checks(bl, objs["laser_turret"], objs["laser_barrel"], objs.get("tail_end", objs["tailcone"])))
    res["crown_curves_down"] = crown_profile(bl)
    for n, o in stages.items():
        o.location = saved[n]
    bpy.context.view_layer.update()
    return res


def crown_profile(bl, step=0.05):
    """The side view's centreline from the crown's start (build_centurion S61_BOAT_TAIL_VISUAL) to the lens's pole,
    every step metres: the top falls ever more steeply and the bottom rises ever more steeply (owner, 2026-10-20: "The
    top should curve down, the bottom should curve up"), so neither line flattens or turns back up into the end."""
    s0 = bl.BOAT_TAIL["crown"]
    tops, bots = [], []
    for i in range(int(round((LENS_S + laser.LENS_LENGTH - s0) / step)) + 1):
        s = s0 + i * step
        _, top, bot = bl.fus_profile(s)
        k = laser.round_off(s - LENS_S, laser.LENS_LENGTH) if s > LENS_S else 1.0
        c = (top + bot) / 2
        tops.append(c + (top - c) * k)
        bots.append(c + (bot - c) * k)
    dt = [b - a for a, b in zip(tops, tops[1:])]
    db = [b - a for a, b in zip(bots, bots[1:])]
    bad = [round(s0 + i * step, 2) for i in range(len(dt)) if dt[i] > 1e-6 or db[i] < -1e-6
           or (i and (dt[i] > dt[i - 1] + 1e-6 or db[i] < db[i - 1] - 1e-6))]
    return {"value": {"stations": [round(s0, 2), round(s0 + (len(tops) - 1) * step, 2)], "bad": bad[:20]},
            "limit": f"every {step} m: top falling and steepening, bottom rising and steepening", "pass": not bad}


# ---------- paint layout ----------
# (station, angle) like the geometry; angles become girth with coords.arc_at, the fairing's with FairingCoords.
# Skin joints laid on structure (docs/M4-ART-PLAN.md rule 1), one continuous skin over the part joints (17, 25 and 33
# carry no line: the parts are partitions of one form, as in nose.py's layout): per band a fastened splice every six
# or seven frames (SPLICES) and panels lapping at frames (LAPS), no station shared by neighbouring bands, so no joint
# runs right round; and along stringer lines (STRINGERS), where each band's joints end. The tail cone's skin
# ends at the laser lens along LENS_JOINT, the one full-girth line.
LENS_JOINT = TAIL_ST[-1]
BANDS = ((0.0, 48.0), (48.0, 112.5), (112.5, 180.0))  # crown, upper flank, lower flank and belly: angles
SPLICES = ((21.0, 29.0, 37.4, 40.9),  # per band: stations
           (20.6, 27.8, 36.8, 40.4),
           (21.6, 29.5, 38.0, 41.4))
FASTENED_TO = 33.0  # splices aft of this (on the tail cone) are laps
LAPS = ((18.8, 23.0, 27.0, 31.2, 35.2, 39.2, 42.2),
        (19.6, 22.6, 24.7, 31.6, 34.6, 39.0, 42.9),
        (18.4, 23.6, 26.6, 30.4, 35.6, 39.6))
assert not any(set(LAPS[i] + SPLICES[i]) & set(LAPS[i + 1] + SPLICES[i + 1]) for i in range(len(BANDS) - 1)),     "neighbouring bands share a joint station: it would run on as one line"
STRINGERS = ((48.0, 17.0, 43.5), (112.5, 17.0, 43.5), (82.0, 17.0, 29.0), (82.0, 33.0, 40.9), (135.0, 17.0, 25.0),
             (135.0, 33.0, 40.9), (160.0, 33.0, 40.9), (22.0, 34.9, 40.9))  # angle, stations
PANELS = (  # station from, to, angle from, to, corner radius, sides (+1, -1 or 0 for both)
    (17.6, 18.5, 60.0, 78.0, 0.05, 0),
    (20.9, 21.8, 62.0, 80.0, 0.05, 0),
    (23.4, 24.4, 56.0, 72.0, 0.05, 0),
    (18.7, 19.9, 158.0, 174.0, 0.04, 0),  # keel access between the sponsons
    (21.4, 22.6, 150.0, 166.0, 0.04, 0),
    (25.7, 26.7, 58.0, 80.0, 0.06, 0),  # aft avionics bay doors
    (27.9, 28.7, 64.0, 82.0, 0.04, 0),
    (31.25, 31.85, 98.0, 110.0, 0.04, 1),  # single-point refuel, left side
    (33.6, 34.6, 52.0, 72.0, 0.05, 0),
    (35.0, 35.9, 92.0, 108.0, 0.04, 0),
    (38.0, 39.0, 58.0, 78.0, 0.04, 0),
    (39.4, 40.2, 26.0, 42.0, 0.03, 0),  # laser power access
    (42.0, 42.9, 120.0, 136.0, 0.04, 0),  # turret access, lower flank
    (36.8, 38.0, 152.0, 172.0, 0.04, 0),  # belly ramp, between the V-tail roots
)
# flare dispensers above the sponsons' tapering tails, one plate a side (CenturionAuthor.FlarePlates; the other pair is
# nose.py's FLARES, owner: "not side by side, in different locations"): station from, to, angle from, to
FLARES = ((32.0, 32.9, 80.0, 94.0),)
WALKWAY = (24.9, 37.2, 0.66)  # stations, girth from the centreline: either side of the spine cover
NOSTEP = ((26.7, 0.98), (36.4, 0.98))  # station, girth (inside TEXT_BANDS)
SERIAL = ("1043", 29.6, 74.0, 0.56)  # text, station, angle, font size: ahead of the V-tail, so it shows from the side
INSIGNIA = (31.95, 70.0, 0.34)  # star and bar: station, angle, circle radius (inside a text band)
LASER_SIGN = (41.0, 62.0)  # the laser hazard triangle on both cone flanks (inside a text band)
SPR_STENCIL = (31.55, 92.0)
RADALT = ((19.95, 20.35), (20.5, 20.9))  # radar altimeter antennas, flush on the keel: stations (0.32 m wide)
JACK_POINTS = ((22.9, 150.0), (32.85, 126.0))  # jacking points, both sides: a red ring round a dark socket
# Service panels on the belly with the wing's thin red keep-clear border (rule 6), two a side: station from, to,
# girth from the keel from, to. Square to the keel, so they stay rectangles where the ramp narrows.
SERVICE_PANELS = ((33.4, 34.3, 0.45, 1.25), (38.5, 39.3, 0.14, 0.6))
RED_LINE = 0.022  # the wing's keep-clear line weight
BELLY_STENCIL = (("HYD SVC", "3000 PSI"), 36.0, 163.0)  # a small block of text in a text band, both sides
# The doubler round the AWACS well: its edge this far outside the spine cover (girth and station), corner radius. Its
# fastener row runs halfway in; the crown's laps and splices stop at it.
WELL_DOUBLER = (0.10, 0.08)

# The fairing's layout, girths from its crest. It shows ahead of the wing root (from its front lap edge at about 12.2,
# where the crest leaves the crown) and, over the root, as a swell about 1.5 m a side before it tucks under the root's
# upper skin; its aft lap edge is at about 23.1.
FAIRING_FRAMES = (12.6, 13.9, 15.2, 16.7, 18.2, 19.7, 21.2)
FAIRING_SPLICES = (13.9, 16.7, 19.7)  # the frames whose joints carry fasteners
FAIRING_LONG = ((0.6, 12.4, 22.6),)  # girth, stations
FAIRING_PANELS = ((13.05, 13.75, 0.8, 1.2, 0.05), (19.6, 20.4, -0.38, 0.38, 0.08), (21.6, 22.2, 0.2, 0.45, 0.04))
FAIRING_NACA = (14.0, 14.6, 1.05)  # ram-air inlets for the environmental control system: stations, girth
FAIRING_LOUVRES = (20.8, 21.3, 0.45, 4)
FAIRING_WALK = (12.6, 20.6, 0.4)
NOSTEP_FAIRING = ((13.2, 0.75),)  # inside FAIRING_TEXT_BANDS

DARK = (0.10, 0.105, 0.11)
MARKING = (0.17, 0.175, 0.185)  # low-visibility insignia and serial grey
STENCIL = (0.80, 0.80, 0.78)
WALK = (0.58, 0.59, 0.59)
RED = (0.55, 0.10, 0.08)
YELLOW = (0.80, 0.62, 0.12)
DIVERTER = (0.47, 0.47, 0.47)
# Bare metal (docs/M4-ART-PLAN.md rule 2): the wing's SATIN, the one satin finish for lips and bare fittings
BARE, BARE_SMOOTH, BARE_METAL = (0.46, 0.47, 0.48), 0.54, 0.2
SEAL = (0.22, 0.225, 0.23)


def paint(cv, text_mask):
    """The group's paint over a Canvas (m4/paint.py)."""
    np = cv.xp
    from .paint import PAINT, SMOOTH
    bl = cv.coords.bl
    for cls, like in ((FAIRING, HULL), (FILLET, HULL), (SPINE, HULL), (WELL, HULL), (DIELECTRIC, RADOME)):
        m = cv.cls == cls
        cv.albedo[m], cv.smooth[m] = PAINT[like], SMOOTH[like]
    # fairing texels: the fairing's own girth from its crest, so its layout reads like the hull's, and their girth
    # distances to its lap edge and to the line where it goes under the wing's upper skin (both from the analytic
    # fairing, never from whatever wing is in the scene)
    fm = cv.cls == FAIRING
    edge, wing = np.full(cv.n, 9.0), np.full(cv.n, 9.0)
    if fm.any():
        fs = Fairing(bl)
        fc = FairingCoords(fs)
        from .paint import fairing_locate
        _, cv.arc[fm] = fairing_locate(fc, cv.pos[fm])
        s, ua = cv.s[fm], np.abs(cv.arc[fm])
        i, t = fc.index(s)
        interp = lambda values: np.asarray(values)[i] * (1 - t) + np.asarray(values)[i + 1] * t
        edge[fm] = np.minimum(np.minimum(interp(fc.edge) - ua, s - fs.lap[0]), fs.lap[1] - s)
        wing[fm] = interp(fc.wing) - ua
    paint_hull(cv, text_mask)
    paint_well(cv)
    paint_fairing(cv, text_mask, edge, wing)
    tone_cells(cv, cv.on(FILLET).astype(float), (21.0,), [])
    paint_spine(cv, text_mask)
    paint_doors(cv)
    paint_radar(cv)


def tone_cells(cv, mask, breaks, girths):
    """Panels differ a little in tone, Darkreach-like: a cell between the station breaks and the girth lines."""
    np = cv.xp
    ua = np.abs(cv.arc)
    cell = np.searchsorted(np.array(sorted(breaks)), cv.s) * 16 + sum((ua > g).astype(int) for g in girths)
    cell = cell * 2 + (cv.arc > 0)
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    cv.albedo *= (1 + 0.05 * tone * mask)[:, None]


def panel(cv, s0, s1, v0, v1, r, mask, arc=None):
    np = cv.xp
    from .paint import rrect_sdf
    a = cv.arc if arc is None else arc
    sdf = rrect_sdf(cv.s, a, s0, s1, v0, v1, r)
    cv.groove(np.abs(sdf), mask=mask)
    cv.fasteners(np.abs(sdf), cv.s + a, 0.03, mask=mask * (np.abs(sdf) < 0.06))
    return sdf


def star_sdf(s, v, cs, cv_, R, up):
    """A five-point star of outer radius R centred at (cs, cv_), one point toward up (+1 or -1 in girth)."""
    from .paint import poly_sdf
    pts = []
    for i in range(10):
        r = R if i % 2 == 0 else R * 0.382
        t = math.pi * i / 5
        pts.append((cs + r * math.sin(t), cv_ + up * r * math.cos(t)))
    return poly_sdf(s, v, pts)


def paint_hull(cv, text_mask):
    np = cv.xp
    from .paint import panel_joint_mask, poly_sdf, rrect_sdf, seg_dist, smoothstep
    c = cv.coords
    s, arc = cv.s, cv.arc
    H = cv.on(HULL).astype(float)
    ua = np.abs(arc)
    ad = np.abs(cv.deg)

    # panel tones: a panel is a cell between its band's laps and splices and the stringer lines
    band = np.digitize(ad, [b for _, b in BANDS[:-1]])
    cell = np.zeros(cv.n, int)
    for i, (laps, splices) in enumerate(zip(LAPS, SPLICES)):
        cell = np.where(band == i, np.searchsorted(np.array(sorted(set(laps) | set(splices) | {LENS_JOINT})), s), cell)
    for a, s0, s1 in STRINGERS:
        cell = cell * 2 + ((ad > a) & (s > s0) & (s < s1))
    cell = (cell * 4 + band) * 2 + (arc > 0)
    tone = ((cell * 2654435761) % 1000) / 1000.0 - 0.5
    cv.albedo *= (1 + 0.05 * tone * H)[:, None]

    # splices (fastened), laps and stringer lines (not), each band's ending on its stringer lines and the crown's at
    # the well's doubler; the lens joint right round
    joints = panel_joint_mask(cv, PANELS)
    off = (well_doubler(cv) > 0).astype(float) * joints
    cv.groove(np.abs(s - LENS_JOINT), 0.02, mask=H * off)
    for (a0, a1), laps, splices in zip(BANDS, LAPS, SPLICES):
        m = H * off * smoothstep(a0 - 0.6, a0, ad) * smoothstep(a1 + 0.6, a1, ad)
        for j in splices:
            d = np.abs(s - j)
            cv.groove(d, 0.016, mask=m)
            if j <= FASTENED_TO:
                cv.fasteners(d, ua, 0.035, mask=m)
        for st_ in laps:
            cv.groove(np.abs(s - st_), mask=m)
    for a, s0, s1 in STRINGERS:
        d = np.abs(ua - np.abs(c.arc_at(s, a)))
        cv.groove(d, mask=H * joints * smoothstep(s0 - 0.01, s0, s) * smoothstep(s1 + 0.01, s1, s))

    # access panels
    for s0, s1, a0, a1, r, sides in PANELS:
        for side in ((1, -1) if sides == 0 else (sides,)):
            sm = (s0 + s1) / 2
            v0, v1 = sorted((float(c.arc_at(sm, side * a0)), float(c.arc_at(sm, side * a1))))
            panel(cv, s0, s1, v0, v1, r, H)

    # the bay opening's frame: a fastener row round the doors, and the acoustic spoiler's lip ahead of them
    e = np.abs(c.arc_at(s, BAY_FRAME))
    inside = (s > BAY_DOOR[0] - 0.12) * (s < BAY_DOOR[1] + 0.12)
    cv.fasteners(np.abs(ua - e), s, 0.0, 0.07, mask=H * inside)
    for sx in (BAY_DOOR[0] - 0.12, BAY_DOOR[1] + 0.12):
        cv.fasteners(np.abs(s - sx), ua, 0.0, 0.07, mask=H * (ua > e))
    spoiler = rrect_sdf(s, ua, BAY_DOOR[0] - 0.5, BAY_DOOR[0] - 0.2, np.abs(c.arc_at(s, 146.0)),
                        np.abs(c.arc_at(s, 180.0)) + 0.1, 0.04)
    cv.groove(np.abs(spoiler), 0.014, mask=H)
    cv.fasteners(np.abs(spoiler + 0.03), s + ua, 0.0, 0.07, mask=H * (np.abs(spoiler) < 0.05))

    flare_plates(cv, FLARES, H)

    # antenna doublers: a fastener ring round each blade's footprint
    for bs, ba, _, c0, *_ in BLADES:
        v = float(c.arc_at(bs, ba))
        sdf = rrect_sdf(s, arc, bs - c0 * 0.5 - 0.12, bs + c0 * 0.6 + 0.12, v - 0.13, v + 0.13, 0.06)
        cv.groove(np.abs(sdf), 0.012, mask=H)
        cv.fasteners(np.abs(sdf + 0.035), s + arc, 0.0, 0.06, mask=H * (np.abs(sdf) < 0.06))

    # radar altimeter antennas on the keel and the jacking points
    for s0, s1 in RADALT:
        sdf = rrect_sdf(s, arc, s0, s1, -0.16, 0.16, 0.03)
        cv.paint(cv.fill_coverage(sdf) * H, rgb=(0.24, 0.245, 0.25), smooth=0.5)
        cv.groove(np.abs(sdf), 0.012, mask=H)
    for js, ja in JACK_POINTS:
        for side in (1, -1):
            r = np.hypot(s - js, arc - float(c.arc_at(js, side * ja)))
            cv.paint(cv.coverage(np.abs(r - 0.07), 0.018) * H, rgb=RED)
            cv.paint(cv.fill_coverage(r - 0.03) * H, rgb=DARK, height=-0.003)

    # Service covers use ordinary panel grooves; red is reserved for keep-clear markings.
    keel = np.abs(c.arc_at(s, 180.0)) - ua
    for s0, s1, k0, k1 in SERVICE_PANELS:
        panel(cv, s0, s1, k0, k1, 0.0, H, arc=keel)
        latch = np.maximum(np.abs(s - (s0 + s1) / 2) - 0.045, np.abs(keel - (k0 + 0.09)) - 0.025)
        cv.paint(cv.fill_coverage(latch) * H, rgb=DARK, height=-0.004)
    lines, bs, ba = BELLY_STENCIL
    for side in (1, -1):
        v = float(c.arc_at(bs, side * ba))
        for i, body in enumerate(lines):
            cv.decal(text_mask(body), (bs, v - side * 0.07 * i), 48 / 0.05, (side, 0), mask=H, rgb=STENCIL)

    # walkway either side of the spine cover, NO STEP outside it
    s0, s1, g = WALKWAY
    dash = ((s - s0) % 0.32) < 0.2
    cv.paint(cv.coverage(np.abs(ua - g), 0.025) * H * dash * (s > s0) * (s < s1), rgb=WALK)
    for side in (1, -1):
        for st_, gi in NOSTEP:
            cv.decal(text_mask("NO STEP"), (st_, side * gi), 48 / 0.06, (side, 0), mask=H, rgb=STENCIL)

    # national insignia, low visibility: a star and bar in a darker grey, the star in the paint
    cs, ca, R = INSIGNIA
    for side in (1, -1):
        v = float(c.arc_at(cs, side * ca))
        up = -side  # toward the crown
        circle = np.hypot(s - cs, arc - v) - R
        bar = rrect_sdf(s, arc, cs - 2.0 * R, cs + 2.0 * R, v + up * 0.35 * R, v - up * 0.31 * R, 0.0)
        sym = np.minimum(circle, bar)
        star = star_sdf(s, arc, cs, v, R * 0.92, up)
        cv.paint(cv.fill_coverage(sym) * H, rgb=MARKING, smooth=0.38)
        cv.paint(cv.fill_coverage(star) * H, rgb=(0.36, 0.37, 0.385), smooth=0.42)
        cv.paint(cv.coverage(np.abs(sym + 0.03), 0.012) * H * (star > 0.02), rgb=(0.36, 0.37, 0.385))

    # serial number on both cone flanks, refuel and bay stencils
    body, ss_, sa, size = SERIAL
    for side in (1, -1):
        cv.decal(text_mask(body), (ss_, side * float(c.arc_at(ss_, sa))), 48 / size, (side, 0), mask=H, rgb=MARKING)
    s_, a_ = SPR_STENCIL
    cv.decal(text_mask("SPR"), (s_, float(c.arc_at(s_, a_))), 48 / 0.07, (1, 0), mask=H, rgb=STENCIL)

    # laser hazard: a yellow triangle with a dark rim, a dark source and its beam, above LASER
    ls, la = LASER_SIGN
    v = float(c.arc_at(ls, la))
    tri = [(ls, v - 0.1), (ls + 0.115, v + 0.1), (ls - 0.115, v + 0.1)]
    sdf = poly_sdf(s, ua, tri)
    cv.paint(cv.fill_coverage(sdf) * H, rgb=YELLOW)
    cv.paint(cv.coverage(np.abs(sdf + 0.012), 0.014) * H, rgb=DARK)
    d, _ = seg_dist(s, ua, (ls, v + 0.045), (ls + 0.075, v + 0.045))
    cv.paint(cv.coverage(d, 0.012) * H * (sdf < -0.02), rgb=DARK)
    cv.paint(cv.fill_coverage(np.hypot(s - ls, ua - (v + 0.045)) - 0.02) * H, rgb=DARK)
    for side in (1, -1):
        cv.decal(text_mask("LASER"), (ls, side * (v - 0.2)), 48 / 0.07, (side, 0), mask=H, rgb=STENCIL)


def well_doubler(cv):
    """Each texel's signed distance (station, girth) to the edge of the doubler round the AWACS well, negative inside."""
    from .paint import rrect_sdf
    s0, s1, a = spine_extent(cv.coords.bl)
    g = float(cv.coords.arc_at((s0 + s1) / 2, a))
    d, r = WELL_DOUBLER
    return rrect_sdf(cv.s, cv.arc, s0 - d, s1 + d, -g - d, g + d, r)


def paint_well(cv):
    """The AWACS well's opening: its lip in the seal's grey, where the spine cover's seal lands, and round it, outside
    the cover, the doubler's edge as a panel line with a fastener row inside it."""
    np = cv.xp
    cv.paint(cv.on(WELL).astype(float), rgb=SEAL, smooth=0.3)
    H = cv.on(HULL).astype(float)
    sdf = well_doubler(cv)
    s0, s1, _ = spine_extent(cv.coords.bl)
    cv.groove(np.abs(sdf), mask=H)
    row = np.abs(sdf + WELL_DOUBLER[0] / 2)
    cv.fasteners(row, np.where((cv.s > s0) & (cv.s < s1), cv.s, np.abs(cv.arc)), 0.0, 0.08, mask=H * (row < 0.03))


def paint_fairing(cv, text_mask, edge, wing):
    """edge, wing: each fairing texel's girth distance to the lap edge and to where the fairing goes under the wing's
    upper skin, metres (negative past them)."""
    np = cv.xp
    from .paint import poly_sdf, seg_dist, smoothstep
    s, arc = cv.s, cv.arc
    F = cv.on(FAIRING).astype(float)
    if not F.any():
        return
    ua = np.abs(arc)
    tone_cells(cv, F, FAIRING_FRAMES, [g for g, _, _ in FAIRING_LONG])
    # the lap edge: a sealant bead along it and a fastener row just inside; the same where the wing's skin laps over.
    # Girth comes from |x| alone, so the swell's tuck, dropping steeply under the root, reads as on the wing's line;
    # where that line turns over the leading edge the tuck faces fore and the bead would fill it as a dark beak.
    along = smoothstep(0.5, 0.3, np.abs(cv.nrm[:, 1]))
    for d, m in ((edge, F), (wing, F * along)):
        cv.paint(cv.coverage(d - 0.008, 0.014) * m, rgb=SEAL, smooth=0.3)
        cv.fasteners(np.abs(d - 0.05), s + ua, 0.0, 0.08, mask=m * (d > 0.02))
    clear = F * (edge > 0.1) * (wing > 0.1)
    for st_ in FAIRING_FRAMES:
        d = np.abs(s - st_)
        cv.groove(d, mask=clear)
        if st_ in FAIRING_SPLICES:
            cv.fasteners(d, ua, 0.03, mask=clear)
    for g, s0, s1 in FAIRING_LONG:
        d = np.abs(ua - g)
        cv.groove(d, mask=clear * (s > s0) * (s < s1))
    for s0, s1, v0, v1, r in FAIRING_PANELS:
        panel(cv, s0, s1, v0, v1, r, clear, arc=ua if v0 >= 0 else arc)
    # escape hatch on the crown: a yellow-rimmed panel with its handle
    s0, s1, v0, v1, _ = FAIRING_PANELS[1]
    sdf = poly_sdf(s, arc, [(s0 + 0.08, v0 + 0.08), (s1 - 0.08, v0 + 0.08), (s1 - 0.08, v1 - 0.08), (s0 + 0.08, v1 - 0.08)])
    cv.paint(cv.coverage(np.abs(sdf), 0.025) * F, rgb=YELLOW)
    cv.paint(cv.fill_coverage(np.maximum(np.abs(s - (s0 + s1) / 2) - 0.1, np.abs(arc) - 0.03)) * F, rgb=DARK, height=-0.004)
    # NACA inlets on the forward shoulders and exhaust louvres on the aft flanks
    s0, s1, g = FAIRING_NACA
    naca(cv, s0, s1, g, F)
    s0, s1, g, n = FAIRING_LOUVRES
    for i in range(n):
        si = s0 + (s1 - s0) * i / (n - 1)
        d, _ = seg_dist(s, ua, (si, g - 0.13), (si, g + 0.13))
        cv.groove(d, 0.024, -0.006, 0.55, mask=F)
    # walkway along the crown, NO STEP on the slopes
    s0, s1, g = FAIRING_WALK
    hs = FAIRING_PANELS[1]
    dash = ((s - s0) % 0.32) < 0.2
    keep = (s < hs[0] - 0.1) | (s > hs[1] + 0.1)
    cv.paint(cv.coverage(np.abs(ua - g), 0.025) * F * dash * (s > s0) * (s < s1) * keep, rgb=WALK)
    for side in (1, -1):
        for st_, gi in NOSTEP_FAIRING:
            cv.decal(text_mask("NO STEP"), (st_, side * gi), 48 / 0.06, (side, 0), mask=F, rgb=STENCIL)



def flare_plates(cv, plates, mask):
    """Flare dispensers on both sides, each (station from, to, angle from, to): a dark plate of cartridge caps."""
    np = cv.xp
    from .paint import rrect_sdf
    s, ua, c = cv.s, np.abs(cv.arc), cv.coords
    for s0, s1, a0, a1 in plates:
        sm = (s0 + s1) / 2
        v0, v1 = float(c.arc_at(sm, a0)), float(c.arc_at(sm, a1))
        sdf = rrect_sdf(s, ua, s0, s1, v0, v1, 0.02)
        cv.paint(cv.fill_coverage(sdf) * mask, rgb=(0.15, 0.155, 0.16), smooth=0.3, height=-0.005)
        cv.paint(cv.coverage(np.abs(sdf + 0.012), 0.024) * mask, rgb=(0.33, 0.34, 0.35), height=0.003)
        cv.groove(np.abs(sdf), 0.014, mask=mask)
        nu, nv = 9, 3
        gu = s0 + (s1 - s0) * (np.clip(np.floor((s - s0) / (s1 - s0) * nu), 0, nu - 1) + 0.5) / nu
        gv = v0 + (v1 - v0) * (np.clip(np.floor((ua - v0) / (v1 - v0) * nv), 0, nv - 1) + 0.5) / nv
        cv.paint(cv.fill_coverage(np.hypot(s - gu, ua - gv) - 0.036) * mask * (sdf < -0.01), rgb=(0.06, 0.06, 0.065),
                 height=-0.003)


def naca(cv, s0, s1, g, mask):
    """A NACA submerged inlet on both sides at girth g: its walls curving out from a narrow nose to the mouth, the
    ramp floor sinking and darkening toward the mouth, a bright lip across the mouth's aft edge."""
    from .paint import poly_sdf, seg_dist
    ts = np.linspace(0.0, 1.0, 9)
    half = 0.025 + 0.085 * ts ** 1.6
    st_ = s0 + (s1 - s0) * ts
    for side in (1, -1):
        v = side * g
        pts = [(a, v - h) for a, h in zip(st_, half)] + [(a, v + h) for a, h in zip(st_[::-1], half[::-1])]
        sdf = poly_sdf(cv.s, cv.arc, pts)
        t = np.clip((cv.s - s0) / (s1 - s0), 0, 1)
        fill = cv.fill_coverage(sdf) * mask
        cv.paint(fill, rgb=(0.27, 0.275, 0.28))
        cv.paint(fill * t ** 2, rgb=(0.08, 0.08, 0.085), smooth=0.25)
        cv.height += -0.014 * t * fill
        cv.groove(np.abs(sdf), 0.012, mask=mask * (cv.s < s1 - 0.01))
        d, _ = seg_dist(cv.s, cv.arc, (s1 + 0.012, v - half[-1]), (s1 + 0.012, v + half[-1]))
        cv.paint(cv.coverage(d, 0.016) * mask, rgb=BARE, smooth=BARE_SMOOTH, metal=BARE_METAL, height=0.002)


def paint_spine(cv, text_mask):
    """The spine cover: the clamshell split down the middle, the hinge lines along the outer edges, the cross seams
    between the lids, latch marks on the split, fastener rows, NO STEP on each half."""
    np = cv.xp
    S = cv.on(SPINE).astype(float)
    if not S.any():
        return
    bl = cv.coords.bl
    s, arc = cv.s, cv.arc
    ua = np.abs(arc)
    s0, s1, a = spine_extent(bl)
    edge = float(cv.coords.arc_at((s0 + s1) / 2, a))
    tone_cells(cv, S, [s0 + (s1 - s0) * i / SPINE_SEGMENTS for i in range(1, SPINE_SEGMENTS)], [0.0])
    inner = S * (ua < edge - 0.06) * (s > s0 + 0.06) * (s < s1 - 0.06)
    cv.groove(ua, 0.01, -0.004, 0.45, mask=inner)
    for i in range(1, SPINE_SEGMENTS):
        cv.groove(np.abs(s - (s0 + (s1 - s0) * i / SPINE_SEGMENTS)), 0.01, -0.01, 0.45, mask=inner)
    cv.groove(np.abs(ua - (edge - 0.09)), 0.012, mask=S)
    cv.fasteners(np.abs(ua - (edge - 0.045)), s, 0.0, 0.08, mask=S)
    # piano hinges down the outer edges of each lid: a raised bead broken into knuckles
    hinge = float(cv.coords.arc_at((s0 + s1) / 2, a - 1.1))
    seg = (s1 - s0) / SPINE_SEGMENTS
    on = S * ((s - s0) % seg > 0.25) * ((s - s0) % seg < seg - 0.25)
    bead = cv.coverage(np.abs(ua - hinge), 0.024) * on
    cv.paint(bead, rgb=(0.33, 0.34, 0.35), smooth=0.45, height=0.004)
    cv.groove(np.abs(((s - s0) % 0.1) - 0.05), 0.006, -0.002, 0.3, mask=bead)
    for sx in (s0 + 0.045, s1 - 0.045):
        cv.fasteners(np.abs(s - sx), ua, 0.0, 0.08, mask=S * (ua < edge - 0.06))
    seg = (s1 - s0) / SPINE_SEGMENTS
    for i in range(SPINE_SEGMENTS):
        for f in (0.3, 0.7):
            ls = s0 + seg * (i + f)
            latch = np.maximum(np.abs(s - ls) - 0.09, ua - 0.05)
            cv.paint(cv.fill_coverage(latch) * S, rgb=(0.33, 0.34, 0.35), smooth=0.45, height=0.003)
            cv.groove(np.abs(latch), 0.01, -0.002, 0.3, mask=S)
            cv.paint(cv.fill_coverage(np.maximum(np.abs(s - ls) - 0.035, ua - 0.012)) * S, rgb=DARK, height=-0.002)
        cv.decal(text_mask("NO STEP"), (s0 + seg * (i + 0.5), 0.22), 48 / 0.05, (1, 0), mask=S * (arc > 0), rgb=STENCIL)
        cv.decal(text_mask("NO STEP"), (s0 + seg * (i + 0.5), -0.22), 48 / 0.05, (-1, 0), mask=S * (arc < 0), rgb=STENCIL)


def paint_doors(cv):
    """Bay doors: an inset border with fasteners, stiffeners across at the ramp crease and either side, and the
    hinge line along the outboard edge. The right door's islands are the left's, so this paints by |girth|."""
    np = cv.xp
    D = cv.on(DOOR).astype(float)
    if not D.any():
        return
    c = cv.coords
    s, ua = cv.s, np.abs(cv.arc)
    s0, s1, a0, a1 = BAY_DOOR
    g0, g1 = np.abs(c.arc_at(s, a0)), np.abs(c.arc_at(s, a1))
    edge_s, edge_g = np.minimum(s - s0, s1 - s), np.minimum(ua - g0, g1 - ua)
    sdf = -np.minimum(edge_s, edge_g)
    along = np.where(edge_s < edge_g, ua, s)
    cv.paint(cv.coverage(np.abs(sdf + 0.006), 0.012) * D, rgb=SEAL, smooth=0.3)  # the seal round the door's edge
    cv.groove(np.abs(sdf + 0.12), 0.012, mask=D)
    cv.fasteners(np.abs(sdf + 0.085), along, 0.0, 0.08, mask=D)
    hinge = np.abs(ua - (g0 + 0.05))  # the hinge line along the outboard edge: its bolts at the hinge knuckles
    cv.fasteners(hinge, s, 0.0, 0.06, 0.009, mask=D * (np.abs(s - (s0 + s1) / 2) < (s1 - s0) / 2 - 0.05))
    for st_ in (27.2, 29.0, RAMP_S):
        d = np.abs(s - st_)
        cv.groove(d, 0.012, mask=D * (sdf < -0.12))
        cv.fasteners(d, ua, 0.0, 0.08, mask=D * (sdf < -0.12))
    cv.groove(np.abs(ua - (g0 + 0.17)), 0.012, mask=D * (np.abs(s - (s0 + s1) / 2) < (s1 - s0) / 2 - 0.12))


def paint_radar(cv):
    """The dielectric lid: radome paint, lightning diverter strips along it and a fastener rim."""
    np = cv.xp
    from .paint import smoothstep
    R = cv.on(DIELECTRIC).astype(float)
    if not R.any():
        return
    c = cv.coords
    s, ua = cv.s, np.abs(cv.arc)
    s0, s1, a0, _ = RADAR
    seal = np.minimum(np.minimum(s - s0, s1 - s), ua - np.abs(c.arc_at(s, a0)))
    cv.paint(cv.coverage(np.abs(seal - 0.006), 0.012) * R, rgb=SEAL, height=-0.002)
    for a in (156.0, 180.0):
        d = np.abs(ua - np.abs(c.arc_at(s, a)))
        cov = cv.coverage(d, 0.022) * R * smoothstep(s0 + 0.12, s0 + 0.2, s) * smoothstep(s1 - 0.12, s1 - 0.2, s)
        cv.paint(cov, rgb=DIVERTER, smooth=0.62, metal=0.85, height=0.0015)
    sdf = np.maximum(np.maximum(s0 - s, s - s1), np.abs(c.arc_at(s, a0)) - ua)
    along = np.where(np.minimum(s - s0, s1 - s) < ua - np.abs(c.arc_at(s, a0)), ua, s)
    cv.fasteners(np.abs(sdf + 0.06), along, 0.0, 0.08, mask=R)
