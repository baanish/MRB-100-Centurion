# Flying the MRB-100 Centurion

The Centurion is a heavy bomber with two internal weapon bays. Fit the dorsal beam to fly AWACS instead. Its telescoping wing trades speed for lift and endurance. Plan your turns early and bring escorts into defended airspace.

For installation, see the [README](../../README.md). Check [known issues](KNOWN-ISSUES.md) before flying an interim build.

In stock Domination, Escalation, Terminal Control and their co-op variants, one BDF factory builds Centurions in turn with Darkreaches. BDF starts with none. Set `StockMissionSupply = false` under `[Missions]` in `BepInEx/config/baanish.centurion.cfg` to turn this off from the host's next mission load.

## Controls

Use your own bindings in Nuclear Option's control settings. The mod adds no separate keyboard shortcuts.

| Action | Control |
|---|---|
| Extend or retract the wing | Custom Axis 1; 0 is retracted, 1 is fully extended |
| Switch the radars and AWACS beam | Radar toggle |
| Raise or lower the gear and automatic flaps | Landing gear control |
| Release bay weapons | Select the weapon, designate a target when required, then use the weapon trigger |
| Aim the laser manually | Select the Laser C-RAM station, aim with your view or designate a target, then use the weapon trigger |
| Return the laser to automatic defence | Select another weapon station. With both bays empty, let go of the trigger |
| Flares and ECM | Countermeasure controls |
| Airbrakes | Bring throttle fully to idle |
| Eject or leave the aircraft | Ejection or aircraft exit control |

The span gauge shows the wing's actual extension and a marker for your command. Full travel takes 8 seconds. The wing is 43.56 m retracted and 87.14 m extended. Near a medium hangar on the ground, the wing stays retracted even if you command extension.

## Takeoff

1. Check fuel and stores before spawning. Normal maximum takeoff mass is 199 t. The full PAB-80LR pair needs reduced fuel, as described below.
2. Taxi with the wing retracted. From a medium hangar, wait until the doors are fully open, about 15 seconds, before you roll. The retracted wing clears the door by only about 3.6 ft (1.1 m) a side, so taxi straight out along the hangar's centreline until the wing is out of the doorway. Line up clear of the hangar, then extend for lift and the climb. Heavy takeoffs also work retracted, but you must extend before climbing to the higher ceiling.
3. The flaps automatically set 30 degrees for takeoff. Apply thrust and let the aircraft gain speed before rotating. In a measured extended takeoff near 199 t, it lifted off at about 154 kt after 920 m. Treat that as a reference, not a runway guarantee.
4. Rotate smoothly. Keep rotation within 8 or 9 degrees; the tail strikes at about 10.5 degrees. Avoid trying to force it off the runway.
5. Once climbing, raise the gear and keep gaining speed. The takeoff flaps stow over 20 seconds after gear up. Leave the wing extended while you establish the climb.

Leaving the gear down keeps the takeoff flap setting. Raise it during the climb so the flaps can stow and the next gear-down can use the landing setting.

## Cruise and ceiling

Use the extended wing for loiter, climb and slower cruise. It reduces the lift needed from angle of attack, burns less fuel at suitable speeds and rolls more slowly. Keep turns gentle and watch airspeed as you climb.

For fast transit near Mach 0.85, retract. The extended wing's drag rises steeply above Mach 0.76; retracting above about Mach 0.75 saves fuel. Extended full-throttle level flight settles near Mach 0.81. There is no automatic speed tear, but pulling hard at speed can exceed the load limit.

At mid weight, the extended aircraft can hold 17.5 km, about 57,500 ft. The retracted ceiling is about 14 km, about 46,000 ft. Weight and turns reduce your margin, so leave room below the ceiling rather than climbing until the speed decays. The official ceiling is 55,000 ft.

With the current 330 kN engines, AWACS loiter at 15 km and 200 m/s gives about 3.3 hours down to 20% fuel. This is extrapolated from four burns totalling 25 minutes, not a continuous endurance flight. It excludes the climb, manoeuvring and the return to base. There is no aerial refuelling.

With the stick centred, the stock fly-by-wire holds attitude, as on every aircraft. It cannot prevent a sink if you let the aircraft get too slow.

## Landing and damaged wings

Extend before the approach, while you have room to slow down and settle. Lower the gear once configured; the flaps automatically use 15 degrees after they have stowed during the flight. Watch speed and sink rate rather than stretching the flare. At idle, the split ailerons and spoilers act as airbrakes. Avoid a high nose attitude near touchdown, and retract the wing before taxiing among buildings.

If you go around, add thrust and establish the climb before raising the gear. A go-around retains the landing flap preset until the aircraft is slow on the ground again.

Past 25% extension, more than +4 g or less than -1 g for half a second tears off the outer wing stages. Damage to one outer panel causes an automatic symmetric emergency jettison of the healthy outer panel to prevent asymmetric lift. Losing a whole wing at its root does not: the other wing keeps its panels. Extension then stays locked for the sortie. The damaged wing adds drag permanently. Slow down, use shallow turns and return to land with the remaining span.

## Fire in the bays

Lasers, guns, flak and missiles can all damage the Centurion. Fuel fires spread between tanks and threaten loaded bays.

If the fuel tank over a loaded bay catches fire, release everything in that bay within 20 seconds. If any conventional stores remain, one blast goes off at the bay. It can break up the aircraft and damage nearby escorts. The blast grows with what is left aboard, up to the equivalent of 5,000 kg of TNT. Empty bays and bays holding only nuclear weapons never cook off.

## AWACS beam and radar master

Fit the 6 t AWACS Beam on the dorsal station. It occupies the aft bay, which must stay empty. The forward bay keeps its bomber stores and ARAD-116 options; the AWACS preset uses 16 ARAD-116s.

Clear the hangar with the radar master on and the beam rises, then extends its ends. Deployment takes 12 seconds. The beam detects nothing until fully deployed. Switching the radar master off stows it and removes the extra deployed drag; switching on raises it again when clear of the hangar.

| Radar | Nominal range | Coverage |
|---|---|---|
| Nose | 60 km | Forward cone, 60 degree half-angle |
| Tail | 40 km | Aft cone, 60 degree half-angle |
| AWACS beam | 150 km | All directions |

All radars follow the same master switch and operate together when fitted and deployed. These are radar range settings, not guaranteed detection distances. Target radar cross-section, clutter and jamming affect the picture. The beam draws 15 kW and adds drag when deployed. Its emissions reveal you to enemy warning receivers and anti-radiation missiles.

## Laser C-RAM and capacitor

The tail laser is a separate, removable station. It fires at 120 kW within 80 degrees of straight aft, out to 8 km. Its 2,000 kJ capacitor also supplies the radars and ECM. Engine RPM controls charging: 20 kW at idle to 60 kW at full RPM with both engines healthy. Continuous fire drains charge even with the engines running.

Leave another weapon selected for automatic defence. The laser picks hostile missiles it can track, including missiles aimed at you, friendlies and missiles with no target. It does not automatically attack aircraft or vehicles. `Cram.CoverEscorts` defaults to true; turning it off leaves defence against missiles aimed at the Centurion and missiles with no target. Use the same setting throughout a multiplayer lobby.

Select the laser station to aim it yourself. It follows your view or a designated target and fires on the trigger, still within its range and aft cone. While selected, it stops automatic defence. Select another station to hand defence back. With both bays empty the laser is your only station. It still defends on its own, and holding the trigger aims and fires it as if selected. Let go and automatic defence resumes. The beam can hit friendlies, so check your line of fire.

ECM counts at twice its normal intensity against active and semi-active radar missile seekers when the seeker signal is strong enough for jamming to apply. Search radars and warning estimates keep the normal intensity. This is defensive self-protection; the aircraft has no offensive radar-jamming pod. Use flares for infrared threats and escorts for threats the rear laser cannot cover. A large salvo can exhaust the capacitor.

Leaving the laser station empty saves 300 kg and removes its defence. The tail dome remains. See [known issues](KNOWN-ISSUES.md) before using manual laser aim on a dedicated server.

## Bays and loadouts

Forward and aft stores of the same munition pool into one weapon selection. For bombs, a single release alternates bays. Holding the trigger, or selecting two or more targets, releases bombs from both bays together. Doors stay open for four seconds and lower layers release first. Keep the aircraft steady while stores clear the bays.

The table gives the standard pairs in 0.2.0 and the three forward ARAD racks. Counts are rounds.

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

Smaller racks also appear in the selector. Each rack fits its intended bay. The higher 0.1.3 counts are labelled `LEGACY` and appear in missions that allow event content.

| Munition, smaller rack | Forward | Aft | Total with that rack in both bays |
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

Normal payload is up to 50 t. The 412-round LEGACY PAB-80LR pair weighs 51.5 t. With full fuel and the laser fitted, it reaches 200.5 t. Set fuel to 93% or less to stay under 199 t. Check mass before departure with any custom load.

With the AWACS beam fitted, read every aft count as zero. The beam takes precedence over aft stores, including saved loadouts. ARAD-116s are forward-only with either role. There are no air-to-air missiles or external pods.

## Weapon pack racks

With the Aryx Weaponry Pack or Meridian Works installed, the bays also offer Centurion-sized racks of their weapons. The racks appear only when the pack is installed; nothing changes without it. A mission saved with a pack rack loads that bay empty on a game without the pack.

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

The Hailstorm rack, "EVENT: HSM-160M Hailstorm (20kt) x9", appears only in missions that allow event content. The nuclear racks follow the mission's nuclear settings and the airbase's warheads like the stock ones. Nemesis and Kalibr pairs, and the forward-only ARAD-120, load the aircraft nose-heavy; the ARAD-120 rack holds 12 rather than 16 so its takeoff keeps back stick in hand at rotation. In multiplayer everyone needs the same packs; a Steam lobby turns away a player whose packs differ from the host's.

## Crew and ejection

The pilot sits on the left and the mission commander on the right. Use the normal ejection control in flight. The overhead escape hatches jettison and both crew leave in separate seats with parachutes; the cockpit stays with the aircraft. This does not add a separate player-controlled commander station. On the ground, leaving the aircraft uses the side crew door.

## What the AI does

The AI draws one of eight presets: GPO-500 x66, PAB-250 x120, PAB-250LR x120, GBM-500LR x54, Tusko-B x42, AShM-300 x36, GPO-500 x16 and AWACS. These presets use the standard racks. While the enemy has a long-range SAM site alive anywhere in the mission, a bomb or glide bomb draw becomes a Tusko-B or AShM-300 loadout instead, so bombers carry missiles until those sites are gone. The AWACS draw is unaffected.

Bombers extend for takeoff and climb on a racetrack before heading toward the target. Cruise height depends on weight, about 51,000 to 57,000 ft, with gentle 20 degree banks. Against a target near their base they attack lower. With bombs they come in at 15,000 ft for a target 10 nautical miles from base, rising evenly to 50,000 ft at 30 nautical miles and beyond. Missile bombers come in at 20,000 ft for a target within about 22 nautical miles (40 km). Each keeps its assigned target until it is destroyed. Missiles launch from height and speed, except while an enemy long-range SAM covers the home base: then a missile bomber fires during the climb, often within a minute of takeoff. A missile bomber extends away from a target too close to line up on, then turns back. With rounds left, it waits for its missiles in flight before deciding to land. Empty aircraft return to rearm.

The AI leaves the laser in automatic defence. It holds its attack against missiles the laser can cover. For an uncovered radar missile, it dodges while holding height rather than diving to the ground. Escort it against head-on attacks.

AWACS aircraft climb toward 15 km and orbit near 200 m/s, with radars on. Their racetrack follows the front at a distance set by detecting stealthy fighters, about 25 km from the nearest enemy base under normal conditions. This can put them inside long-range SAM coverage. They use countermeasures and the automatic laser, and return at 20% fuel. They fire their ARAD-116s in pairs at emitting hostile SAM and AA radars, only from beyond the site's own reach plus 10 km and never closing in to make a shot, so a StratoLance R9 site is never a target.

AI Centurions need a qualifying runway at least 1,907 m long. Players can spawn at any base whose medium hangar fits the aircraft. The AI manages span itself, including extension for landing and retraction for taxi.
