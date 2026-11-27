# Flying the MRB-100 Centurion

The Centurion is a heavy high-altitude bomber with two internal bays, or an AWACS once you fit the dorsal radar beam. Its telescoping wing trades speed for lift and endurance. Think ahead on turns, manage your energy on climbs, and bring escorts when pushing into defended airspace.

For installation, see the [README](../../README.md). Check [known issues](KNOWN-ISSUES.md) for current caveats.

## Controls

The mod adds no custom hotkeys. Everything runs on Nuclear Option's own bindings.

| Action | Control |
|---|---|
| Extend or retract the wing | Custom Axis 1 (0 is retracted, 1 is fully extended) |
| Switch radars and AWACS beam | Radar toggle |
| Raise or lower gear and automatic flaps | Landing gear control |
| Release bay weapons | Select weapon, designate target when required, press weapon trigger |
| Aim the laser manually | Select the Laser C-RAM station, aim with your view or designate a target, press weapon trigger |
| Return laser to automatic defence | Select another weapon station, or let go of the trigger if both bays are empty |
| Flares and ECM | Countermeasure controls |
| Airbrakes | Throttle fully to idle |
| Eject or exit aircraft | Ejection or aircraft exit control |

The HUD span gauge and the cockpit wing display both show current extension (143 ft retracted to 286 ft extended) along with your commanded position. Full travel takes 8 seconds. On the ground near a medium hangar, the span stays locked retracted even if you command extension.

## Takeoff

1. **Check your weight before spawning.** Normal maximum takeoff mass is 199 t. Only the event-content 412-round LEGACY PAB-80LR load exceeds this at full fuel (see [Bays and loadouts](#bays-and-loadouts) below).
2. **Wait for the hangar doors.** Keep the wing retracted while taxiing. From a medium hangar, wait until the doors finish opening (about 15 seconds) before rolling. The retracted wingtips clear the doorway by only 3.6 ft (1.1 m) a side, so track straight down the centreline until the wings are completely outside.
3. **Choose your span.** Heavy takeoffs work retracted or extended, though extending once clear of the hangar gives better lift in the climb. At 199 t with the wing extended, expect liftoff around 154 kt after roughly 3,020 ft (920 m) of runway.
4. **Rotate gently.** Flaps set themselves to 30 degrees for takeoff. Let speed build, then pull smoothly to 8 or 9 degrees nose-up. The tail strikes at 10.5 degrees, so do not force it off the ground.
5. **Clean up in the climb.** Raise the gear once established climbing. Takeoff flaps stow slowly over 20 seconds after gear up so you keep your lift while accelerating. Leave the wing extended until you want speed down low.

Always raise the gear after takeoff. If you leave it down, the flaps stay on the 30-degree takeoff setting for your landing, which makes the aircraft float and bounce.

## Cruise and ceiling

- **Extended wing** is for climbs, loiter and long-range cruise. It lowers fuel burn, climbs higher and rolls more slowly. Keep turns smooth and watch airspeed as the air thins out.
- **Retracted wing** is for fast transit near Mach 0.85. Extended drag climbs sharply past Mach 0.76, capping level flight around Mach 0.81, so pull the wing in once you pass Mach 0.75. There is no automatic overspeed tear, though a hard pull at high speed will still over-g the outer stages.
- **Ceiling.** Official ceiling is 55,000 ft. At mid weight, the aircraft holds about 57,500 ft extended and about 46,000 ft retracted. Heavy loads and turns eat into that margin, so cruise a little below maximum altitude rather than riding the edge of a stall.
- **Endurance.** At 49,000 ft and around 390 kt extended, AWACS loiter runs roughly 3.3 hours down to 20% internal fuel, not counting the climb, manoeuvring or recovery. There is no aerial refuelling.
- **Fly-by-wire.** With the stick centred, stock fly-by-wire holds pitch attitude as on other aircraft. It will not save you from sinking if you let airspeed bleed away.

## Landing and damaged wings

Extend the wing before starting your approach so you have lift and room to slow down. Once the flaps have stowed earlier in the flight, lowering the gear sets 15-degree landing flaps automatically. Fly speed and sink rate onto the runway instead of stretching the flare, keep the nose down to avoid a tail strike, and bring throttle to idle if you need the split ailerons and spoilers as airbrakes. Retract the wing before taxiing back near buildings.

If you go around, add power and establish a positive climb before raising the gear. A go-around keeps the 15-degree landing flap preset until you are slow on the ground again.

Hard touchdowns can snap a main gear leg above about 3,000 ft/min at maximum weight, or about 4,200 ft/min light. Grass and soft ground break the gear about as easily as on a Darkreach.

### Wing tear and symmetric jettison

Past 25% extension, holding more than +4 g or less than -1 g for half a second tears both outer wing stages off. If enemy fire knocks off one outer panel, the aircraft automatically jettisons the healthy opposite outer panel so you are not rolled upside down by asymmetric lift. Losing an entire wing at the root does not trigger jettison on the intact side.

After any outer stage loss, wing extension locks for the rest of the sortie and the damaged wing adds permanent drag. Slow down, make shallow turns and fly home on the inner span.

## Fire in the bays

Lasers, cannon fire, flak and missiles can all damage the Centurion and start fuel fires, which spread between neighbouring tanks just like on stock bombers.

Each weapon bay sits under a fuselage fuel tank. If the tank over a loaded bay catches fire, you have **20 seconds** to jettison or drop everything in that bay. If any conventional ordnance remains when the timer runs out, the bay cooks off in a single explosion scaled to what is left aboard (up to 5,000 kg of TNT). The blast can break the aircraft in half and damage nearby escorts. Empty bays and bays holding only nuclear weapons never cook off.

## AWACS beam and radars

Mounting the 6 t AWACS beam on the dorsal station turns the Centurion into an AWACS. The beam uses the aft bay's space, so the aft bay stays empty regardless of saved loadouts. The forward bay keeps normal bomber stores and ARAD-116 racks (the AWACS preset loads 16 ARAD-116s).

Once you clear the hangar with radar master on, the beam rises on its mast and extends its end sections over 12 seconds. It produces no detections until fully deployed. Toggling radar master off stows the beam back into the spine and drops its deployed drag.

| Radar | Nominal range | Coverage |
|---|---|---|
| Nose | 60 km | Forward 60-degree half-cone |
| Tail | 40 km | Aft 60-degree half-cone |
| AWACS beam | 150 km | All directions |

All three radars share the stock radar toggle and run simultaneously when fitted and deployed. Actual detection distances depend on target radar cross-section, terrain clutter and jamming. Deployed, the beam draws 15 kW, adds noticeable drag and broadcasts your position to enemy RWRs and anti-radiation missiles.

## Laser C-RAM and capacitor

The tail cone carries a removable 120 kW laser effective out to 8 km within 80 degrees of straight aft. It shares a 2,000 kJ capacitor with the radars and built-in ECM. Both healthy engines recharge the capacitor from 20 kW at idle up to 60 kW at full RPM, so continuous firing drains it faster than the engines can refill it.

- **Automatic defence.** Leave any other weapon selected and the laser defends automatically, engaging tracked hostile missiles aimed at you, aimed at friendlies, or flying without a target. It never shoots at aircraft or ground units on its own. Setting `Cram.CoverEscorts = false` limits it to missiles aimed at you and untargeted missiles (keep this setting identical across a multiplayer lobby).
- **Manual aim.** Select the laser station to aim with your view or lock a designated target of any kind within the aft cone, then hold the trigger. Automatic defence pauses while the station is selected. Pick another weapon to hand it back. If both bays are empty, the laser stays automatic until you hold the trigger to aim it manually, and returns to automatic defence when you release. Watch your line of fire, because the beam hits friendlies too.
- **ECM and flares.** Built-in ECM applies at double its normal strength against active and semi-active radar missile seekers while leaving search radar returns and RWR estimates unchanged. It is defensive self-protection only, not an offensive radar jammer. Use flares for IR missiles, and rely on escorts for head-on shots and salvos that can drain the capacitor.
- **Removing the laser.** Leaving the tail station empty saves 300 kg and removes point defence. The tail dome stays.

Check [known issues](KNOWN-ISSUES.md) before using manual laser aim on a dedicated server.

## Bays and loadouts

Matching munitions in the forward and aft bays combine into one weapon selection. Single bomb presses alternate between bays. Holding the trigger, or selecting two or more targets, drops from both bays together at that bomb's normal interval. Bay doors stay open for four seconds and lower layers drop first, so hold the aircraft steady while stores clear.

Standard 0.2.0 racks and forward-only ARAD-116 options (counts in rounds):

| Munition | Forward | Aft | Total |
|---|---:|---:|---:|
| PAB-250 | 60 | 60 | 120 |
| PAB-250LR | 60 | 60 | 120 |
| PAB-80LR | 120 | 144 | 264 |
| GPO-500 | 30 | 36 | 66 |
| GPO-N (1.5 kt) | 12 | 16 | 28 |
| GPO-N (250 kt) | 12 | 16 | 28 |
| GBM-500LR | 24 | 30 | 54 |
| Tusko-B (HE) | 18 | 24 | 42 |
| AShM-300 | 18 | 18 | 36 |
| AGM-99 | 24 | 32 | 56 |
| ALM-C450 | 12 | 9 | 21 |
| ALND-4 (20 kt) | 4 | 6 | 10 |
| GPO-2P Auger | 9 | 9 | 18 |
| Piledriver TBM | 6 | 6 | 12 |
| Piledriver TBM (20 kt) | 6 | 6 | 12 |
| Demolition Bomb | 2 | 2 | 4 |
| ARAD-116, small rack | 4 | 0 | 4 |
| ARAD-116, medium rack | 8 | 0 | 8 |
| ARAD-116, packed rack (AWACS preset) | 16 | 0 | 16 |

Smaller racks are also available in the loadout menu:

| Munition, smaller rack | Forward | Aft | Total with both bays |
|---|---:|---:|---:|
| GPO-500 | 8 | 8 | 16 |
| GPO-500 | 12 | 12 | 24 |
| PAB-250 | 18 | 18 | 36 |
| PAB-250LR | 8 | 8 | 16 |
| PAB-80LR | 4 | 4 | 8 |
| GBM-500LR | 6 | 6 | 12 |
| GPO-2P Auger | 4 | 4 | 8 |
| GPO-N (1.5 kt) | 2 | 2 | 4 |
| GPO-N (250 kt) | 2 | 2 | 4 |
| ALND-4 (20 kt) | 2 | 2 | 4 |

Each rack fits only its intended bay. In missions that allow event content, the larger 0.1.3 counts appear under `LEGACY` labels. Normal maximum payload is 50 t, but the 412-round LEGACY PAB-80LR pair weighs 51.5 t and pushes takeoff mass to 200.5 t with full fuel and the laser fitted. Cut fuel to 93% or less to stay under 199 t.

With the AWACS beam mounted, aft bay counts are always zero, and ARAD-116s mount in the forward bay only. There are no air-to-air missiles or external pods.

## Weapon pack racks

If you have the Aryx Weaponry Pack or Meridian Works installed, the Centurion adds 45 bay racks for their weapons automatically. Without those packs installed, nothing changes. Missions saved with a pack rack load that bay empty if the pack is absent.

| Pack | Weapon | Forward | Aft |
|---|---|---:|---:|
| Aryx | AGM-111 Nemesis | 8 | 8 |
| Aryx | AGM-76 Atlatl | 60 | 60 |
| Aryx | CBO-400 | 32 | 32 |
| Aryx | PAB-3000LR | 4 | 4 |
| Aryx | PGM-400LR | 32 | 32 |
| Aryx | Tusko-N (1.5 kt) | 12 | 12 |
| Meridian Works | AGM-102 Kalibr, AGM-102E Kalibr | 16 | 16 |
| Meridian Works | AGM-190A Black Arrow | 60 | 60 |
| Meridian Works | AGM-33L | 24 | 24 |
| Meridian Works | AGM-57L | 20 | 22 |
| Meridian Works | AGM-84 | 14 | 15 |
| Meridian Works | AGM-92, GBO-900, GBP-500 Bodkin | 8 | 8 |
| Meridian Works | ARAD-120 | 12 | 0 |
| Meridian Works | AShM-140 Exocet, HSM-160 Kickback, HSM-160C Scatter, HSM-160N Longshot (300 kt) | 6 | 6 |
| Meridian Works | AShM-500 Yashma | 12 | 12 |
| Meridian Works | HSM-160M Hailstorm (20 kt), event content | 9 | 9 |
| Meridian Works | PAB-125HD | 60 | 60 |

`"EVENT: HSM-160M Hailstorm (20kt) x9"` appears only in missions that allow event content. Nuclear pack racks obey the mission's nuclear rules and airbase warhead stock just like stock nukes. Nemesis pairs, Kalibr pairs and the forward-only ARAD-120 shift weight forward, so expect a nose-heavy rotation on takeoff. In multiplayer, every player needs the same weapon packs as the host.

## Crew and ejection

The pilot sits on the left and the mission commander on the right. Ejecting in flight blows the overhead escape hatches and launches both seats on parachutes while the cockpit stays with the airframe. On the ground, exiting the aircraft uses the side crew door.

## AI and stock missions

In stock Domination, Escalation, Terminal Control and their co-op variants, one BDF factory builds Centurions in turn with Darkreaches (BDF starts with none). Hosts can turn this off from the next mission load by setting `StockMissionSupply = false` under `[Missions]` in `BepInEx/config/baanish.centurion.cfg`.

AI Centurions only take off from runways at least 6,257 ft (1,907 m) long, while players can spawn at any base with a medium hangar. The AI handles its own wing extension, waiting for hangar doors and taxiing out at 12 kt or less.

- **Loadouts.** AI Centurions draw from eight standard presets: GPO-500 x66, PAB-250 x120, PAB-250LR x120, GBM-500LR x54, Tusko-B x42, AShM-300 x36, GPO-500 x16 and AWACS. Whenever an enemy long-range SAM site is alive anywhere on the map, bomb and glide-bomb draws swap to Tusko-B or AShM-300 missiles until those sites are gone. AWACS draws are unchanged.
- **Bomber doctrine.** Bombers climb extended on a racetrack before heading in at 51,000 to 57,000 ft by weight, using gentle 20-degree banks. Against nearby targets they ingress lower, from 15,000 ft at 10 nautical miles out up to 50,000 ft at 30 nautical miles for bombs, and 20,000 ft within about 22 nautical miles (40 km) for missiles. If an enemy long-range SAM covers their home base, missile bombers fire during the climb instead of waiting for cruise altitude. They stay on their assigned target until it is destroyed, extend away and turn back if a missile target is too close to align on, and wait for missiles in flight before heading home to rearm.
- **Defence.** AI leaves the tail laser on automatic and flies through attacks the laser can intercept. Against an uncovered radar missile, it dodges laterally while holding altitude rather than diving to the deck. Escort friendly bombers against head-on threats.
- **AWACS doctrine.** AWACS climbs to about 49,000 ft and orbits near 390 kt with radars on, standing off roughly 25 km from the nearest enemy base to detect stealth fighters. That standoff can sit inside long-range SAM reach, so clear threatening sites or cover it. It defends with countermeasures and the automatic laser, returns to base at 20% fuel, and fires pairs of ARAD-116s at emitting SAM and AA radars from outside their weapon reach plus 10 km without closing in (so a StratoLance R9 site stays out of its target list).
