# Known issues

Interim builds are work in progress for Nuclear Option 0.34.2. Check your release's notes and the [changelog](../../CHANGELOG.md) for changes. The [pilot's guide](FLYING.md) covers controls and normal operation.

## Unfinished

- The flight deck interior art and displays are still being finished. The Centurion has its own cockpit, but its presentation is not final.
- The damage model and exposed structure are still in progress.
- Gear and wing sounds are still being finished. Engine and cabin audio are present.

## Multiplayer

- Every player needs the mod and Blueprinter enabled. Keep the Centurion version the same across the lobby.
- Testing has used a host and client on one PC, including simulated lag and late joins. Two-PC multiplayer validation is still pending.
- On a dedicated server, manual laser aim may disagree with the server's aim, so damage may go in a different direction from the player's aim. Dedicated-server laser behaviour remains unverified. Leave another weapon selected to use automatic defence instead of relying on manual aim.
- Joining while an AWACS beam is moving can show it at its destination until the animation catches up, for up to 12 seconds.
- Keep `Cram.CoverEscorts` the same on every peer.

## Flight and AI

- Avoid the camera tool's 4x time acceleration during manoeuvring flight. It can cause load spikes and wing loss. Use normal speed for takeoff, turns and landing.
- An AI bomber climbing out from Vigil Cay can move toward its target before reaching strike altitude. Threats near the base can catch it during the climb.
- The rear laser cannot cover head-on threats. Its capacitor is finite and it can be overwhelmed by salvos. Bring escorts.
- The AWACS orbit can lie inside long-range SAM coverage. Its standoff is chosen for detection, so clear threatening sites or protect it.
- The current AWACS endurance figure is extrapolated from a short loiter burn. It is not a guaranteed sortie duration and excludes climb, manoeuvring and the return to base.

The mod targets Nuclear Option 0.34.2. Compatibility with later game versions is not established.

## Report a problem

Open a [GitHub issue](https://github.com/baanish/MRB-100-Centurion/issues/new?template=bug_report.md). Include:

- Nuclear Option version and Centurion release version or interim build tag.
- Blueprinter version and other enabled mods.
- Whether you were in single-player, hosting, a joining client or on a dedicated server.
- Map, base, loadout and the steps that caused the problem.
- What you expected and what happened. Add screenshots or video if useful.
- `BepInEx/LogOutput.log` from that session as an attachment.

Check the log for personal details before attaching it. Keep the original available if more information is needed.
