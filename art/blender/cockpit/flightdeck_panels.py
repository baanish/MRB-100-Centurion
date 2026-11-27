"""The second sample's panels: every control belongs to a system of the Centurion (docs/SPEC.md, src/Centurion/),
grouped the way a flight engineer would find it, each with its placard. Pure data, shared by flightdeck_textures.py (the
label cells) and flightdeck_build.py (the geometry).

A panel is (title, rows); a row is a list of controls; a control is (kind, label). Kinds and what draws them:
  tog   toggle: stock Switches1 bushing (kit_04) and bat lever (kit_07)
  togw  toggle with the white-tipped lever (kit_34)
  gtog  guarded toggle: tog under the stock box guard (kit_36), painted red
  ptr   pointer knob (kit_08)      skt  skirted knob (kit_33)    knl  knurled knob (kit_40)
  big   large slotted knob (kit_22)   stk  stacked dual knob (kit_20)   pull  pull handle (kit_28)
  key   square legend key (kit_12)   lamp  indicator lamp (kit_23)
  cb    circuit breaker (new: 22 triangles on the trim sheet)
  ann   annunciator tile (new: a 2-triangle lens with its legend on the trim sheet)
  gap   an empty cell
Labels use the placards' standard abbreviations, the same for a word everywhere (MSTR master, DRS doors, LT light),
where the full word left no room for letters the seat can read (flightdeck_cards.LEGEND_FLOOR_PX).
"""

# ---- pilot's side console (left), front to aft
LEFT_CONSOLE = [
    ("WING SPAN", [[("gtog", "EXTEND"), ("tog", "STG 1 LOCK"), ("tog", "STG 2 LOCK"), ("lamp", "LOCKED"), ("lamp", "UNLOCK")],
                   [("gtog", "TEAR ARM"), ("ptr", "SPAN"), ("tog", "STG 1 L"), ("tog", "STG 1 R"), ("lamp", "TEAR")]]),
    ("FLIGHT CONTROLS", [[("ptr", "FLAP"), ("tog", "SPOILER"), ("tog", "DRAG RUD"), ("tog", "FBW 1"), ("tog", "FBW 2")],
                         [("knl", "PITCH TRIM"), ("knl", "YAW TRIM"), ("key", "ALPHA LIM"), ("key", "AP ENGAGE"), ("lamp", "AP")]]),
    ("HYDRAULICS", [[("tog", "SYS A PUMP"), ("tog", "SYS B PUMP"), ("tog", "ELEC PUMP"), ("gtog", "PTU"), ("lamp", "A PRESS"), ("lamp", "B PRESS")],
                    [("ptr", "GEAR ALT"), ("tog", "BRAKE"), ("tog", "ANTI SKID"), ("tog", "NWS"), ("lamp", "LO QTY"), ("gap", "")]]),
    ("CAMERA BAND", [[("tog", "CAM PWR"), ("knl", "GAIN"), ("knl", "CONT"), ("tog", "MARKER"), ("key", "TEST")]]),
    ("COMMS 1", [[("stk", "VHF 1"), ("stk", "UHF"), ("knl", "VOL"), ("knl", "SQL"), ("key", "XFR")],
                 [("key", "1"), ("key", "2"), ("key", "3"), ("key", "4"), ("key", "PRE")]]),
    ("ESCAPE", [[("gtog", "HATCH L"), ("gtog", "HATCH R"), ("ptr", "EJECT MODE"), ("tog", "SEAT ARM"), ("lamp", "ARMED")]]),
    ("EXT LIGHTS", [[("tog", "NAV"), ("tog", "STROBE"), ("tog", "BEACON"), ("tog", "LAND"), ("tog", "TAXI"), ("tog", "FORM")]]),
    ("INT LIGHTS", [[("knl", "FLOOD"), ("knl", "PANEL"), ("knl", "CONSOLE"), ("knl", "MFD"), ("tog", "DAY NIGHT"), ("key", "LT TEST")]]),
]
LEFT_CONSOLE += [
    ("ANTI ICE", [[("tog", "PROBE"), ("tog", "WING"), ("tog", "ENG 1"), ("tog", "ENG 2"), ("lamp", "ICE")]]),
    ("NAV", [[("ptr", "NAV MODE"), ("knl", "CRS"), ("knl", "HDG"), ("key", "INS"), ("key", "GPS")],
             [("key", "WPT"), ("key", "FIX"), ("key", "MARK"), ("key", "HOLD"), ("lamp", "ALIGN")]]),
    ("IFF", [[("ptr", "MSTR"), ("tog", "MODE 2"), ("tog", "MODE 4"), ("knl", "CODE"), ("lamp", "REPLY")]]),
    ("OXYGEN", [[("tog", "O2 SUPPLY"), ("tog", "DILUTER"), ("tog", "EMER"), ("lamp", "FLOW")]]),
    ("DATA ENTRY", [[("key", "1"), ("key", "2"), ("key", "3"), ("key", "CLR")],
                    [("key", "4"), ("key", "5"), ("key", "6"), ("key", "ENT")],
                    [("key", "7"), ("key", "8"), ("key", "9"), ("key", "0")]]),
]
LEFT_CONSOLE += [
    ("AUTOPILOT", [[("key", "ALT HOLD"), ("key", "HDG HOLD"), ("key", "COMBAT HT"), ("key", "AP ENGAGE"), ("lamp", "AP")],
                   [("knl", "ALT"), ("knl", "HDG"), ("knl", "VS"), ("tog", "AP"), ("lamp", "ALT")]]),
    ("FIRE", [[("pull", "FIRE 1"), ("pull", "FIRE 2"), ("gtog", "BOTTLE 1"), ("gtog", "BOTTLE 2"), ("lamp", "FIRE")],
              [("tog", "TANK EXT"), ("tog", "BAY EXT"), ("key", "TEST"), ("lamp", "OVHT"), ("lamp", "BAY")]]),
    ("GEAR BRAKES", [[("tog", "PARK"), ("tog", "NWS"), ("knl", "AUTOBRAKE"), ("lamp", "PARK"), ("lamp", "SKID")]]),
    ("HUD", [[("knl", "HUD"), ("tog", "DECLUTTER"), ("tog", "SPAN"), ("knl", "SYM"), ("key", "DAY NIGHT")]]),
    ("POWER", [[("gtog", "BATT"), ("tog", "EXT PWR"), ("tog", "GEN 1"), ("tog", "GEN 2"), ("lamp", "EXT")],
               [("tog", "BUS TIE"), ("tog", "ESS"), ("knl", "VOLT"), ("key", "TEST"), ("lamp", "BATT")]]),
    ("MAP", [[("knl", "ZOOM"), ("knl", "RANGE"), ("key", "MAP"), ("key", "CNTR"), ("key", "VIEW")]]),
    ("ENGINE 1", [[("tog", "EEC 1"), ("tog", "FAN 1"), ("tog", "IGN"), ("lamp", "START"), ("lamp", "FIRE 1")]]),
    ("ENGINE 2", [[("tog", "EEC 2"), ("tog", "FAN 2"), ("tog", "IGN"), ("lamp", "START"), ("lamp", "FIRE 2")]]),
    ("TRIM", [[("knl", "PITCH"), ("knl", "ROLL"), ("knl", "YAW"), ("key", "RESET"), ("lamp", "TRIM")]]),
    ("WARNING", [[("key", "MSTR CAUT"), ("key", "MSTR WARN"), ("knl", "TONE VOL"), ("tog", "VOICE"), ("lamp", "CAUT")]]),
    ("CLOCK", [[("key", "START"), ("key", "STOP"), ("key", "RESET"), ("knl", "SET"), ("lamp", "TIMER")]]),
    ("SEAT", [[("tog", "HEIGHT"), ("tog", "HARNESS"), ("knl", "PEDALS"), ("lamp", "LOCK")]]),
]
# the left wall over the console: circuit breakers, by bus
LEFT_WALL = [("CB  BUS 1", [[("cb", "")] * 16] * 3)]

# ---- the commander's side console (right), front to aft
RIGHT_CONSOLE = [
    ("RADAR SUITE", [[("gtog", "MSTR"), ("tog", "NOSE"), ("tog", "TAIL"), ("tog", "AWACS"), ("lamp", "XMIT")],
                     [("ptr", "MODE"), ("big", "RANGE"), ("knl", "TILT"), ("key", "IFF"), ("key", "TEST")]]),
    ("AWACS BEAM", [[("gtog", "DEPLOY"), ("tog", "STOW"), ("tog", "ROTATE"), ("lamp", "UP"), ("lamp", "STOWED")],
                    [("ptr", "SECTOR"), ("knl", "RATE"), ("key", "TRACK"), ("key", "DATA"), ("lamp", "LINK")]]),
    ("C-RAM LASER", [[("gtog", "LASER ARM"), ("tog", "CAP CHG"), ("ptr", "AUTO MAN"), ("lamp", "READY"), ("lamp", "CAP LO")],
                     [("knl", "PRIORITY"), ("key", "SLEW"), ("key", "TEST"), ("gtog", "SAFE"), ("lamp", "FIRE")]]),
    ("JAMMER", [[("tog", "ECM PWR"), ("ptr", "ECM MODE"), ("knl", "POWER"), ("key", "BURN"), ("lamp", "ECM")]]),
    ("COUNTERMEASURES", [[("tog", "DISP 1"), ("tog", "DISP 2"), ("tog", "DISP 3"), ("tog", "DISP 4"), ("lamp", "EMPTY")],
                         [("ptr", "PROGRAM"), ("knl", "SALVO"), ("key", "AUTO"), ("gtog", "CM JETT"), ("lamp", "CM ARM")]]),
    ("COMMS 2", [[("stk", "VHF 2"), ("stk", "SATCOM"), ("knl", "VOL"), ("key", "ICS"), ("key", "XFR")]]),
    ("ENVIRONMENT", [[("tog", "PACK 1"), ("tog", "PACK 2"), ("knl", "TEMP"), ("tog", "DEFOG"), ("tog", "O2")],
                     [("tog", "PRESS"), ("knl", "CABIN ALT"), ("key", "DUMP"), ("lamp", "O2 LO"), ("lamp", "PRESS")]]),
]
RIGHT_CONSOLE += [
    ("DATA LINK", [[("tog", "LINK PWR"), ("ptr", "NET"), ("key", "TX"), ("key", "RX"), ("lamp", "SYNC")],
                   [("key", "TGT"), ("key", "TRK"), ("key", "PASS"), ("key", "DROP"), ("lamp", "DATA")]]),
    ("RECORDER", [[("tog", "REC"), ("tog", "CAM"), ("key", "MARK"), ("lamp", "REC")]]),
    ("MISSION COMP", [[("tog", "MC 1"), ("tog", "MC 2"), ("ptr", "MC MODE"), ("key", "RESET"), ("lamp", "FAIL")]]),
    ("DISPLAYS", [[("knl", "MFD 1"), ("knl", "MFD 2"), ("knl", "MFD 3"), ("tog", "DAY NIGHT"), ("key", "SWAP")]]),
    ("DATA ENTRY", [[("key", "1"), ("key", "2"), ("key", "3"), ("key", "CLR")],
                    [("key", "4"), ("key", "5"), ("key", "6"), ("key", "ENT")],
                    [("key", "7"), ("key", "8"), ("key", "9"), ("key", "0")]]),
]
RIGHT_CONSOLE += [
    ("NOSE RADAR", [[("tog", "NOSE"), ("ptr", "MODE"), ("knl", "GAIN"), ("knl", "TILT"), ("lamp", "XMIT")]]),
    ("TAIL RADAR", [[("tog", "TAIL"), ("ptr", "MODE"), ("knl", "GAIN"), ("key", "TEST"), ("lamp", "XMIT")]]),
    ("ARAD", [[("gtog", "ARM"), ("ptr", "MODE"), ("key", "TGT"), ("key", "AUTO"), ("lamp", "LOCK")]]),
    ("BOMB RELEASE", [[("ptr", "RELEASE"), ("knl", "INTERVAL"), ("knl", "RIPPLE"), ("tog", "PAIRED"), ("lamp", "ARM")],
                      [("key", "BAY 1"), ("key", "BAY 2"), ("key", "LEGACY"), ("gtog", "MSTR ARM"), ("lamp", "READY")]]),
    ("TARGETING", [[("tog", "CAM"), ("ptr", "FWD AFT"), ("knl", "ZOOM"), ("key", "TRACK"), ("lamp", "TRK")],
                   [("key", "WPT"), ("key", "MARK"), ("key", "TGT"), ("key", "DATA"), ("lamp", "LOCK")]]),
    ("COOK OFF", [[("gtog", "BAY 1"), ("gtog", "BAY 2"), ("key", "TEST"), ("lamp", "BAY"), ("lamp", "FIRE")]]),
    # CAPACITOR before the commander's copy of INT LIGHTS: the pilot's INT LIGHTS works the same lights
    ("CAPACITOR", [[("tog", "CHARGE"), ("knl", "RATE"), ("key", "DUMP"), ("lamp", "FULL"), ("lamp", "LO")]]),
    ("INT LIGHTS", [[("knl", "FLOOD"), ("knl", "PANEL"), ("knl", "CONSOLE"), ("knl", "MFD"), ("key", "LT TEST")]]),
    # the commander's copy of the pilot's EXT LIGHTS: after INT LIGHTS and CAPACITOR, which only this console carries room for
    ("EXT LIGHTS", [[("tog", "NAV"), ("tog", "STROBE"), ("tog", "BEACON"), ("tog", "LAND"), ("tog", "TAXI")]]),
    ("WARNING", [[("key", "MSTR CAUT"), ("key", "MSTR WARN"), ("knl", "TONE VOL"), ("tog", "VOICE"), ("lamp", "CAUT")]]),
    ("SENSOR COOL", [[("tog", "COOL 1"), ("tog", "COOL 2"), ("knl", "TEMP"), ("key", "TEST"), ("lamp", "HOT")]]),
    ("CLOCK", [[("key", "START"), ("key", "STOP"), ("key", "RESET"), ("knl", "SET"), ("lamp", "TIMER")]]),
]
RIGHT_WALL = [("CB  BUS 2", [[("cb", "")] * 16] * 3)]

# ---- pedestal, between the seats: aft of the throttles (front to aft)
PEDESTAL = [
    ("ENGINE START", [[("gtog", "START 1"), ("gtog", "START 2"), ("tog", "IGN"), ("tog", "FAN 1"), ("tog", "FAN 2")],
                      [("pull", "CUTOFF 1"), ("pull", "CUTOFF 2"), ("lamp", "START"), ("lamp", "VALVE")]]),
    ("FUEL", [[("tog", "FWD"), ("tog", "CTR 1"), ("tog", "CTR 2"), ("tog", "AFT"), ("tog", "TAIL")],
              [("ptr", "XFEED"), ("gtog", "DUMP"), ("lamp", "LO PRESS"), ("lamp", "IMBAL"), ("knl", "QTY TEST")]]),
    ("BAYS", [[("gtog", "MSTR ARM"), ("tog", "BAY 1"), ("tog", "BAY 2"), ("ptr", "RACK"), ("gtog", "BAY JETT")],
              [("lamp", "1 OPEN"), ("lamp", "2 OPEN"), ("key", "LEGACY"), ("knl", "RIPPLE"), ("key", "SAFE")]]),
]

# ---- main panel strips under each display (the pilot's and the commander's) and the centre stack
STRIPS = {
    "wing": [[("tog", "BAND"), ("key", "STG"), ("lamp", "LOCKED")], [("key", "SPAN"), ("key", "TEST"), ("lamp", "TEAR")]],
    "pfd": [[("knl", "BARO"), ("knl", "HDG"), ("key", "STD"), ("key", "ALT")], [("key", "HUD"), ("key", "MAP"), ("knl", "CRS"), ("lamp", "AP")]],
    "radar": [[("gtog", "XMIT"), ("ptr", "RANGE"), ("knl", "GAIN"), ("knl", "TILT"), ("key", "MAP"), ("key", "TGT"), ("lamp", "LOCK")],
              [("key", "NOSE"), ("key", "TAIL"), ("key", "AWACS"), ("key", "IFF"), ("key", "TEST"), ("key", "MARK"), ("lamp", "XMIT")]],
    "stores": [[("gtog", "MSTR ARM"), ("tog", "BAY DRS"), ("key", "JETT"), ("knl", "RACK"), ("lamp", "ARM")],
               [("key", "BAY 1"), ("key", "BAY 2"), ("key", "LEGACY"), ("ptr", "RELEASE"), ("lamp", "READY")]],
    "engines": [[("tog", "EEC 1"), ("tog", "EEC 2"), ("key", "N1"), ("key", "EGT"), ("lamp", "FIRE 1"), ("lamp", "FIRE 2")]],
    "gauges": [[("tog", "BATT"), ("tog", "GEN 1"), ("tog", "GEN 2"), ("tog", "BUS TIE"), ("lamp", "GEN")]],
}
# the centre stack's caution panel under its two pages
ANNUNCIATORS = ["FUEL LO", "HYD A", "HYD B", "GEN 1", "GEN 2", "BUS",
                "BAY 1", "BAY 2", "WING LK", "TEAR", "SPAN", "FLAP",
                "CAP LO", "LASER", "ECM", "CM LO", "RADAR", "BEAM",
                "HATCH", "CABIN", "O2", "FIRE 1", "FIRE 2", "OVHT"]



def all_words():
    words = set()
    for group in (LEFT_CONSOLE, RIGHT_CONSOLE, PEDESTAL, LEFT_WALL, RIGHT_WALL):
        for title, rows in group:
            words.add(title)
            for row in rows:
                for kind, label in row:
                    if label:
                        words.add(label)
    for rows in STRIPS.values():
        for row in rows:
            for kind, label in row:
                words.add(label)
    words |= {"RADAR", "PFD", "STORES", "ENGINES", "STATUS", "WING", "CAUTION"}
    words |= {"IDLE", "MAX", "ENG 1", "ENG 2", "FRICTION", "RET", "EXT", "0", "15", "30", "SPAN", "FLAP", "UP", "DOWN"}
    return sorted(words)


# one convention for keys: a console key's cap is blank light grey and its name is stencilled in white under it, as
# every other control's is; only a keypad's keys (digits, CLR, ENT) carry their black legend on the cap
KEYPAD = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "CLR", "ENT"}


def legend(label):
    return label if label in KEYPAD else ""


def key_words():
    """Every legend a push key carries on its face: the consoles' and pedestal's keys, every control of a display's
    strip (a strip too short for labelled rows becomes a row of legend keys), and the displays' brightness keys."""
    words = {"BRT", "CON"}
    for group in (LEFT_CONSOLE, RIGHT_CONSOLE, PEDESTAL):
        for title, rows in group:
            for row in rows:
                words |= {label for kind, label in row if kind == "key" and label}
    for rows in STRIPS.values():
        for row in rows:
            words |= {label for kind, label in row if label}
    return sorted(words)
