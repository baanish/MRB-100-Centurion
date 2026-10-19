# Changelog

## 0.1.3 (in progress)

### Done

- The wing status display is drawn with the HUD span gauge's line art, one wing hanging down, with the extension percentage and amber warnings.
- A burning weapon bay now cooks off after 20 seconds instead of 5, giving the crew time to react.

### Planned

- A finer damage model: the aircraft breaks into 66 pieces instead of 39, including split fuselage skin panels and outer wing sections.
- Internal structure and fuel compartments visible through damage, with armour and joint strength set for each part.
- A slimmer, more streamlined tail (appearance only; flight is unchanged).
- A small external camera on the nose where the forward screen's view comes from, and subtler scan lines on that screen.
- The missile warning strips move from the windows onto the cockpit panel, and the Alkyon's old missile warning on the tactical screen is removed.

## 0.1.2 (pre-release), 2026-10-19

### Cockpit

- Added a dedicated wing status display left of the pilot's flight display. A telescoping column shows extension, with a percentage below and amber warnings for lost stages.
- Added padding around display pages so their edges stay clear of the bezels from both seats.
- Removed the blocks at the ends of the forward camera screen and closed the gaps beneath them.
- Closed the gaps where sky showed past the forward camera screen's ends.

### AI

- The AWACS preset carries 16 ARAD-116s. AI AWACS fire them in pairs at emitting hostile radars, prioritising SAM and AA sites while staying beyond their anti-aircraft range plus 10 km.

### Fuel and damage

- Moved all fuel out of the wings into four fuselage tanks: centre box, forward, aft and a new tail tank. Neighbouring tanks can spread fire to one another.
- A weapon bay whose fuel tank burns for 5 seconds cooks off: its conventional stores explode once, sized by what is left in the bay (up to 5,000 kg), and its section breaks off. Nuclear weapons never cook off.
- Lasers can no longer damage the Centurion or start its fires. Guns, flak and missiles still can.

## 0.1.1 (pre-release), 2026-10-19

### Cockpit and crew

- Added the Centurion's own flight deck, with a forward camera screen, KR-67 sticks and throttles, a side crew door and five displays: two flight displays, radar, engines and stores. Interior art is still in progress.
- Added a mission commander beside the pilot. Both crew eject through overhead hatches in separate seats with parachutes.

### Sound

- Added the Centurion's engine fan and thrust sounds, plus cabin engine audio heard only in its cockpit.
- The telescoping wing stages play a lower, layered version of the Alkyon's wing sound. The flaps have their own motion sound, audible over the engines.

### Weapons and defence

- Added bay loads of 21 ALM-C450s, 10 ALND-4s or 110 AGM-99s across both bays. The ALM-C450 load carries 12 forward and 9 aft.
- Increased the capacitor to 2,000 kJ at the original charge rate. Doubled defensive jamming intensity against active and semi-active radar missile seekers, without changing search radar returns.
- Restricted laser fire to its 80 degree aft cone and 8 km range.
- Selecting the laser station now allows manual aiming and firing at designated targets. Selecting another weapon restores automatic missile defence.
- Increased demolition bombs to 2 per bay, 4 total.
- Added PAB-80LRs in both bays: 196 forward and 216 aft, 412 total. This load weighs 51.5 t. With the laser fitted, use 93% fuel or less to stay under maximum takeoff mass.

### Flight

- Increased engine thrust to 330 kN each, with fuel burn scaled to match. The retracted ceiling is about 14 km. Extended flight holds 17.5 km at mid weight.
- Added permanent drag after outer wing loss, with a notification for symmetric emergency jettison after one outer panel is lost.
- Takeoff flaps now retract over 20 seconds after gear up, reducing the sudden loss of lift during the climb.
- Increased radar cross-section to 1.5 retracted and 2.0 extended on the game's scale.
- Moved the landing camera behind the aft bay.

### Damage

- Added fragment debris when aircraft parts break apart.
- Wing fuel tank hits now leak and burn at the tank's location.
- Moved both target cameras clear of the nose and tail to prevent views clipping into the aircraft.

### AI

- Missile bombers line up with targets horizontally and fly away to make another pass when too close to turn onto a target.
- With rounds remaining, missile bombers wait for their own missiles in flight before deciding to return to land.
- Missile bombers now climb and launch from altitude, as bombers do with bombs and glide bombs.

### Installation and help

- Added build and installation instructions, release packages and download checksums.
- Added a pilot's guide, known issues and a bug report template for interim builds.

## 0.1.0, 2026-10-17

Initial release for Nuclear Option 0.34.2.

### Aircraft

- Heavy bomber and optional AWACS, available to both factions from medium hangars.
- A telescoping wing with a span of 43.56 m retracted and 87.14 m extended, trading speed for lift and endurance.
- Two geared turbofan engines producing 270 kN each, without afterburners.
- BDF Matte Gray and Forest Green liveries, plus PALA Matte Black and Desert Camo.

### Weapons and sensors

- Two internal weapon bays with up to 50 t of bombs, glide bombs, cruise missiles, anti-ship missiles and nuclear weapons. Forward bay ARAD-116 racks carry 4, 8 or 16 missiles.
- Nose and tail radars with maximum ranges of 60 km and 40 km. An optional retractable dorsal AWACS beam adds 150 km coverage in all directions and occupies the aft bay.
- Automatic tail laser C-RAM for missile defence, powered by a 1,500 kJ capacitor, plus built-in ECM and flares.

### AI

- Eight AI loadout presets, with bombers attacking from altitude and AWACS flying patrol orbits before returning to land for fuel.
