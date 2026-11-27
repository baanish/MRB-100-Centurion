# Changelog

## 0.2.0 (pre-release), 2026-11-26

### Cockpit

- The cockpit is rebuilt with a new layout: radar straight ahead, flight display on the left, stores on the right, and engine and fuel panels on the centre stack.
- Throttles, gear, span and flap levers move, and the panels carry more switches.
- The forward camera screen is wider and flatter. From the pilot's seat nothing behind it shows through, and at night it is see-through rather than a bright band.
- The pilot's side window has a frame and sill, and the panels around it are angled to open the view.
- Nothing hangs below the control strips into the footwell, so the rudder pedals are in sight and a seated pilot's legs can reach them.
- A wing display left of the flight display shows the telescoping wing live, with the span in percent.

### Exterior

- Panel lines, seams and fittings are redrawn from the airframe's structure, and fittings sit square to the skin.
- Faction roundels replace the earlier insignia, on the wings and the V-tail, placed as on the Darkreach.
- The flap fairings under the wing move with their flaps: the rear half swings aft and down as the flap lowers, and nothing is left behind.
- Spoilers rise out of recessed wells with a visible actuator.
- The split ailerons open as two halves with structure between them.
- Skin textures are sharper up close. The download is about 95 MB, up from 70 MB.
- The wingtip navigation lights sit on the wingtips and move with the span.
- The tail cone's two missile-warning domes and its coolant vent are removed.
- The main wheels stow clear of the aft bay, and the gear doors close in flight.

### Fuel and damage

- The aircraft breaks into 45 sections instead of 64 parts. The layout follows the Darkreach's, and each section has its own armour and joints sized for the load it carries.
- Parts no longer come off on the ground or in a full pull at full health.
- The Centurion is built lighter than the Darkreach, so it breaks up sooner under missile, cannon and blast damage.
- Fire is the game's own: a burning tank spreads to its neighbours as on a stock bomber, and the bays burn off.
- Lasers can damage the Centurion and start its fires, as they do on stock aircraft.
- A bay whose fuel tank burns for 20 seconds cooks off. Its stores explode once at the bay, sized by what is still loaded (up to 5,000 kg of TNT), which can break the aircraft apart. Release the bay's stores within those 20 seconds to prevent it. Nuclear stores never cook off.
- A landing above about 3,000 ft/min at maximum weight, or about 4,200 ft/min at light weight, can break a main gear leg.
- Losing a whole wing at its root no longer makes the other wing jettison its outer stages. Losing a single outer section still jettisons the other side.

### Weapons and defence

- Bay racks are balanced to the Darkreach's density, about 1.7 times its rounds of each munition. For example, PAB-250 is 60 a bay, and PAB-80LR is 120 forward and 144 aft.
- Fixed: some bomb racks could be fitted to either bay, which allowed loads over the take-off limit. Each rack now fits its own bay only.
- The 0.1.3 loads remain as LEGACY racks, labelled "LEGACY: <weapon> x<rounds>". They appear only in missions that allow event content, which no stock mission does. AI Centurions never carry them.
- A mission saved in 0.1.3 loads its balanced rack under the same name. A saved LEGACY rack in a mission without event content leaves that bay empty.
- The LEGACY PAB-80LR pair is over the take-off limit at full fuel, so use 93% fuel or less.
- With both bays empty the laser still defends on its own. Hold the trigger to aim and fire it yourself, and let go to hand defence back.
- With the Aryx Weaponry Pack or Meridian Works installed, the bays offer 45 Centurion-sized racks of their weapons, such as PGM-400LR x32, Atlatl x60, Black Arrow x60, Kalibr x16 and PAB-125HD x60 a bay. They appear only when the pack is installed. Nothing of either pack ships with the Centurion.
- Event-content pack weapons, such as the Meridian Works Hailstorm, get racks filled to the bay's maximum. They appear only in missions that allow event content.

### Flight

- The tail is as rigid as a stock aircraft's tail. It no longer flutters at high speed or bends under normal pitch and yaw. Only the telescoping wing flexes.
- Wheels on grass and soft ground break about as easily as a Darkreach's.

### AI

- Bombers attack a target near their base from altitude on their first run. Their release height scales with distance from base: 15,000 ft for a target 10 nautical miles out, rising to 50,000 ft at 30 nautical miles.
- Bombers keep their assigned target through the transit until it is destroyed.
- AI Centurions carry missile loadouts while an enemy long-range SAM is alive, and bombs once it is gone.
- While an enemy long-range SAM covers their home base, AI missile bombers fire during the climb instead of waiting for cruise height.
- AI Centurions keep their wings extended at cruise height, so they no longer retract them and sink.
- AI Centurions wait for a hangar's doors to finish opening, so a wingtip no longer strikes a moving door, hold the shelter's centreline, and taxi at 12 knots or less.
- AI presets use the balanced counts: Bombs 500 x66, Bombs 250 x120, Glide Bombs 250 x120, Glide Bombs 500 x54, Tusko-B x42.
- In stock Domination, Escalation and Terminal Control, and their co-op variants, one BDF factory builds Centurions in turn with Darkreaches. BDF starts with none. The host can turn this off with `StockMissionSupply = false` under `[Missions]` in the Centurion config, from the next mission load.

### Multiplayer

- A player who joins after a cook-off sees the aircraft whole until it crashes. The late-joiner replay of a cook-off is removed.
- Every player in a lobby needs the same weapon packs as the host.
- Tested on two PCs over Steam: span, wing loss, radars, the AWACS beam, a bay cook-off and players who join late agree on both PCs.
- On a dedicated server, a laser a client fires at a selected target damages it as in single player.

### Liveries

- A player livery kit ships as a separate download, `centurion_livery_kit_<version>.zip`: a 3D paint model, flat templates, the four liveries as examples and a livery builder for Unity. See the livery kit guide.
- Each wing section, nacelle and outboard flap paints separately on the left and right. The flap track fairings share one paint area for both sides. Distant models carry the paint.
- A livery installed locally was tested in the game. Steam Workshop sharing, with the tag `MRB-100 Centurion`, has not been tested.

### Compatibility

- Tested on Nuclear Option 0.34.6 with Blueprinter 2.1.1. Requires BepInEx 5 and Blueprinter 2.0.1 or later.
- Not tested on Nuclear Option 0.35 or later.
- With NO-Autopilot 6.x, the Centurion's profile holds track without rocking the wings.
- The plugin no longer carries test hooks, recorders or debug settings. On first run it removes the Diagnostics, Debug and Capture sections from its config. Its WingFlex and C-RAM settings are kept.
- Configuration Manager shows three switches for the Centurion: wing flex, escort cover and stock mission supply. The seven wing flex tuning values appear with Advanced settings ticked.

### Not final yet

- Battle damage openings, the braced structure behind them, and the look of a broken aircraft are not final.
- A small gap shows in the skin where the left V-tail root meets the tail cone.
- The AWACS radar mount takes no damage of its own. It is lost only with the fuselage section that carries it.
- Up close, thin coloured lines on the skin step along their length, and on the green, desert and black liveries they carry a pale edge.
- The NO STEP lettering on the inboard flaps reads mirrored.
- A thin line of bare metal shows along the slanted joint of the outer flap fairings, seen from below.
- A bay cook-off breaks the aircraft apart, but the game does not always count it as a kill. In testing it credited about half of the runs.
- Missile kills are still being tuned. A Scythe or Scimitar hit does not yet reliably destroy the aircraft, and cannon hits need a sustained burst.
- AI bombers still die to long-range SAM sites before release in the end-game Escalation mission.
- On a dedicated server, free laser aim with no target selected and the automatic laser defence have not been tested. A Steam lobby refusing a player with different packs comes from reading the code and has not been run.
- From some head positions in the pilot's seat, a few faint gaps show past the display modules. Under night vision, the wing display has a halo around it.
- The NO-Autopilot step that adds track gains to an earlier profile has not been run in game.
- Balance numbers are set by hand and will follow player feedback. The bombing and AWACS balance checks have not been rerun at the shipping radar size and rack counts.

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
