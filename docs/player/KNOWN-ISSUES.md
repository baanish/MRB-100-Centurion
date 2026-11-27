# Known issues

Interim builds are work in progress. Check your release's notes and the [changelog](../../CHANGELOG.md) for changes. The [pilot's guide](FLYING.md) covers controls and normal operation.

## Unfinished

- The look of battle damage is not final: the openings, the structure behind them and a broken aircraft.
- A small gap shows in the skin where the left V-tail root meets the tail cone.
- The AWACS radar mount takes no damage of its own. It is lost only with the fuselage section that carries it.
- Up close, thin coloured lines on the skin step along their length, and on the green, desert and black liveries they carry a pale edge.
- The NO STEP lettering on the inboard flaps reads mirrored.
- A thin line of bare metal shows along the slanted joint of the outer flap fairings, seen from below.
- From some head positions in the pilot's seat, a few faint gaps show past the display modules. Under night vision, the wing display has a halo around it.

## Multiplayer

- Every player needs the mod and Blueprinter enabled. Keep the Centurion version the same across the lobby.
- Two-PC sessions over Steam passed for the wing, radars, the AWACS beam, a bay cook-off and late joins. The laser has been tested only with host and client on one PC.
- On a dedicated server, a laser fired at a selected target damages it as in single player (tested with one client). Free aim with no target selected may disagree with the server's aim, so damage may go in a different direction. Free aim and the automatic defence are untested on a dedicated server. Select a target before firing.
- Joining while an AWACS beam is moving can show it at its destination until the animation catches up, for up to 12 seconds.
- Keep `Cram.CoverEscorts` the same on every peer.

## Flight and AI

- Avoid the camera tool's 4x time acceleration during manoeuvring flight. It can cause load spikes and wing loss. Use normal speed for takeoff, turns and landing.
- An AI bomber climbing out from Vigil Cay can move toward its target before reaching strike altitude. Threats near the base can catch it during the climb.
- The rear laser cannot cover head-on threats. Its capacitor is finite and it can be overwhelmed by salvos. Bring escorts.
- The AWACS orbit can lie inside long-range SAM coverage. Its standoff is chosen for detection, so clear threatening sites or protect it.
- The current AWACS endurance figure is extrapolated from a short loiter burn. It is not a guaranteed sortie duration and excludes climb, manoeuvring and the return to base.

Version 0.2.0 was tested on Nuclear Option 0.34.6 with Blueprinter 2.1.1.

## Report a problem

Open a [GitHub issue](https://github.com/baanish/MRB-100-Centurion/issues/new?template=bug_report.md). Include:

- Nuclear Option version and Centurion release version or interim build tag.
- Blueprinter version and other enabled mods.
- Whether you were in single-player, hosting, a joining client or on a dedicated server.
- Map, base, loadout and the steps that caused the problem.
- What you expected and what happened. Add screenshots or video if useful.
- `BepInEx/LogOutput.log` from that session as an attachment.

Check the log for personal details before attaching it. Keep the original available if more information is needed.
