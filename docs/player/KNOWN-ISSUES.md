# Known issues

Version 0.2.0 is a pre-release tested on Nuclear Option 0.34.6 with Blueprinter 2.1.1 (requires BepInEx 5 and Blueprinter 2.0.1 or later). It has not been tested on Nuclear Option 0.35 or later. For controls and normal flight, see the [pilot's guide](FLYING.md). For recent changes, see the [changelog](../../CHANGELOG.md).

## Damage and combat

- **Battle damage art is not final.** Damage openings, internal structure and broken-up sections are still work in progress.
- **Missile and cannon durability is still being tuned.** A single Scythe or Scimitar hit does not yet reliably destroy the Centurion, and cannon fire takes a sustained burst.
- **Bay cook-offs do not always award a kill.** A cook-off breaks the aircraft apart, but the game does not consistently credit it as a kill.

## Multiplayer

- **Everyone needs the same setup.** Every player in a lobby needs the same Centurion version, Blueprinter enabled, and the same weapon packs (Aryx Weaponry Pack or Meridian Works) as the host.
- **Match `Cram.CoverEscorts` across the lobby.** Keep this setting the same on every player so escort missile defence stays in sync.
- **Dedicated server manual laser aim.** Select a target before firing the laser manually on a dedicated server. Free aim with no target selected may not match where the server applies damage.

## Flight and AI

- **Avoid 4x time acceleration while manoeuvring.** High time compression can cause load spikes that tear off the outer wing stages. Use normal speed for takeoff, turns and landing.
- **AI bombers in heavy SAM environments.** In end-game Escalation, AI bombers can still be shot down by long-range SAM sites before reaching release. An AI bomber climbing out from Vigil Cay can also head toward its target before reaching strike altitude, exposing it to threats near the base.

## Report a problem

Open a [GitHub issue](https://github.com/baanish/MRB-100-Centurion/issues/new?template=bug_report.md) and include:

- Your Nuclear Option version, Centurion version, Blueprinter version and any other enabled mods.
- Whether you were in single-player, hosting, joining as a client or on a dedicated server.
- Map, base, loadout and the steps that caused the problem.
- What happened versus what you expected, with screenshots or video if helpful.
- `BepInEx/LogOutput.log` from that session (check it for personal details before attaching).
