# Changelog

## 0.2.0 (pre-release), 2026-11-26

### Cockpit

- Rebuilt the flight deck with a new layout: radar straight ahead, flight display on the left, stores on the right, and engine and fuel panels on the centre stack.
- Throttles, landing gear, span and flap levers now animate, and the panels carry more switches.
- Widened and flattened the forward camera screen. From the pilot's seat nothing shows through behind it, and at night it stays see-through instead of glowing as a bright band.
- Added a frame and sill to the pilot's side window and angled the surrounding panels to open the view.
- Cleared the footwell below the control strips so the rudder pedals are visible and within reach.
- Added a live wing display left of the flight display showing extension and span percentage.

### Exterior

- Redrew panel lines, seams and fittings from the airframe structure, with fittings seated square to the skin.
- Replaced the earlier insignia with faction roundels on the wings and V-tail, placed like the Darkreach's.
- Articulated the under-wing flap fairings so the rear half swings aft and down with the flap.
- Recessed the spoilers into wells with visible actuators, and split the ailerons into two halves with internal structure between them.
- Sharpened skin textures up close. Download size is now about 95 MB, up from 70 MB.
- Mounted the wingtip navigation lights on the tips so they travel with the telescoping wing.
- Removed the two missile-warning domes and coolant vent from the tail cone.
- Main wheels now stow clear of the aft bay, and gear doors close cleanly in flight.

### Fuel and damage

- Rebuilt the damage model into 45 sections (down from 64) following the Darkreach's layout, with section armour and joints sized for their loads.
- Fixed parts detaching on the ground or during full-health pulls.
- Lighter construction than the Darkreach means the Centurion breaks up sooner under missile, cannon and blast damage.
- Fuel fires now use the game's standard fire propagation between neighbouring tanks and burn bays off normally.
- Lasers can now damage the Centurion and start fuel fires, as on stock aircraft.
- A bay whose fuel tank burns for 20 seconds cooks off in one blast scaled to its remaining conventional ordnance (up to 5,000 kg of TNT), breaking the aircraft apart. Dropping stores within 20 seconds prevents cook-off, and nuclear stores never cook off.
- Hard landings above about 3,000 ft/min at maximum weight, or about 4,200 ft/min light, can break a main gear leg.
- Losing an entire wing at its root no longer triggers symmetric jettison on the opposite wing. Losing a single outer stage still jettisons the other side.

### Weapons and defence

- Rebalanced bay racks to match Darkreach payload density, roughly 1.7 times its round counts (for example, 60 PAB-250s per bay, and 120 forward and 144 aft PAB-80LRs).
- Fixed bomb racks fitting into either bay and allowing loads past the takeoff limit. Each rack now fits only its own bay.
- Kept the 0.1.3 counts as `LEGACY: <weapon> x<rounds>` racks, available only in missions that allow event content (no stock mission does, and AI never carries them). Missions saved in 0.1.3 load the new balanced racks under the same names. Saved LEGACY racks in missions without event content leave that bay empty.
- The LEGACY PAB-80LR pair exceeds the takeoff limit at full fuel. Use 93% fuel or less.
- With both bays empty, the tail laser still defends automatically. Hold the trigger to aim and fire it manually, and let go to hand defence back.
- Added 45 Centurion-sized bay racks for the Aryx Weaponry Pack and Meridian Works (including PGM-400LR x32, Atlatl x60, Black Arrow x60, Kalibr x16 and PAB-125HD x60 per bay). They appear only when the corresponding pack is installed. Nothing from either pack ships with this mod. Event-content pack weapons such as Meridian Works' Hailstorm fill the bay and appear only in missions that allow event content.

### Flight

- Stiffened the tail to match stock aircraft so it no longer flutters at high speed or bends under normal pitch and yaw. Only the telescoping wing flexes.
- Landing gear on grass and soft ground now breaks about as easily as a Darkreach's.

### AI

- Bombers now attack targets near their base from altitude on the first pass, scaling ingress height from 15,000 ft at 10 nautical miles out up to 50,000 ft at 30 nautical miles.
- Bombers stay committed to their assigned target through transit until it is destroyed.
- AI Centurions switch to missile loadouts while an enemy long-range SAM is alive, returning to bombs once it is gone.
- When an enemy long-range SAM covers their home base, AI missile bombers launch during the climb instead of waiting for cruise altitude.
- AI Centurions keep their wings extended at cruise altitude so they no longer retract and sink.
- AI Centurions now wait for medium hangar doors to open completely, hold the hangar centreline on exit, and taxi out at 12 knots or less.
- Updated AI presets to the balanced rack counts (Bombs 500 x66, Bombs 250 x120, Glide Bombs 250 x120, Glide Bombs 500 x54, Tusko-B x42).
- In stock Domination, Escalation, Terminal Control and their co-op variants, one BDF factory alternates producing Centurions and Darkreaches (BDF starts with none). Hosts can disable this from the next mission load with `StockMissionSupply = false` under `[Missions]`.

### Multiplayer

- Removed the late-joiner bay cook-off replay. Players joining after a cook-off see the aircraft whole until it crashes.
- Every player in a lobby needs the same weapon packs as the host.
- On a dedicated server, firing the laser manually at a designated target now applies damage just as in single player.

### Liveries

- Added a separate player livery kit (`centurion_livery_kit_<version>.zip`) containing a 3D paint model, flat templates, the four stock liveries as examples and a Unity livery builder (see the livery kit guide).
- Wing sections, nacelles and outboard flaps paint separately on left and right, while flap track fairings share one paint area across both sides. Distant LOD models carry custom paint, and Steam Workshop liveries use the tag `MRB-100 Centurion`.

### Compatibility

- Tested on Nuclear Option 0.34.6 with Blueprinter 2.1.1. Requires BepInEx 5 and Blueprinter 2.0.1 or later. Not tested on Nuclear Option 0.35 or later.
- Updated the NO-Autopilot 6.x Centurion profile so track hold flies steadily without wing rock.
- Stripped test hooks, recorders and debug settings from release builds. On first launch, 0.2.0 removes old `Diagnostics`, `Debug` and `Capture` config sections while keeping your WingFlex and C-RAM settings.
- Configuration Manager now shows three top-level switches (wing flex, escort cover and stock mission supply) and hides the seven wing flex tuning values under Advanced settings.

### Not final yet

- Battle damage openings, internal structure and broken-up sections are still work in progress.
- Missile and cannon durability is still being tuned. A single Scythe or Scimitar hit does not yet reliably destroy the aircraft, and cannon fire takes a sustained burst.
- A bay cook-off breaks the aircraft apart, but the game does not always credit it as a kill.
- AI bombers can still be shot down by long-range SAM sites before releasing in end-game Escalation.
- On a dedicated server, select a target before firing the laser manually. Free aim with no target selected may not match where the server applies damage.

## 0.1.3 (pre-release), 2026-10-20

### Cockpit

- The wing status display is drawn with the HUD span gauge's line art, one wing hanging down, with the extension percentage and amber warnings.
- Clearer, less reflective cockpit glass, and no dark bar above the forward camera screen.
- Subtler scan lines on the forward camera screen.
- Missile warning lamps in housings under the forward camera screen, in each seat's view, replacing the strips in the windows.
- The Alkyon's old missile warning on the tactical screen is removed.

### Exterior

- A slimmer, gently curved tail whose top curves down all the way to the end (appearance only; flight is unchanged).
- A small external camera housing on the nose, where the forward screen's view comes from.
- Removed the windscreen wipers.

### Fuel and damage

- A finer damage model: the aircraft breaks into 64 parts instead of 39, including split fuselage skin panels, outer wing sections, wingtips, the tail end and V-tail tips.
- Internal structure and fuel compartments show through damage, and each part has its own armour and joint strength: skin panels and tips come off first, the main structure last.
- A burning weapon bay now cooks off after 20 seconds instead of 5, giving the crew time to react.
- Fuel fires no longer strip the skin in seconds: panels burn slowly and stay on past a bay's 20 s cook-off, and a burning section holds for about 25 s before it burns through. Skin still comes off quickly from weapons, blasts and crashes. A fire spreads to the neighbouring tank after 40 s of burning.
- Fixed an error logged whenever a breakup took the target camera's part: the cockpit displays now black out instead, as on the Alkyon.

### Weapons and defence

- Flares raised to 400, released four at a time from four dispensers.
- Radar cross-section raised to 13 retracted and 26 extended, sized against other large aircraft: the Centurion is harder to hide over terrain and its jamming against radar-guided missiles is weaker.

### Flight

- Stronger landing gear on runways (all three legs survive about 25% harder touchdowns); grass and rough ground still break it.
- NO-Autopilot flies the Centurion without oscillating: with NO-Autopilot installed, the mod adds a Centurion-only NO-Autopilot profile (never replacing one you already have).
- Removed the custom flight-path hold. A centred stick now uses the stock fly-by-wire attitude hold, including with NO-Autopilot installed.

### Sound

- A more mechanical, quieter flap motion sound in place of the hiss-heavy one.

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
