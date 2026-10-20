# Centurion sound credits

The locked engine loops use the sources below. The v1 prototype set is built by `audio/build_v1.py`; its source inventory and processing notes follow the locked set.

DVIDS material: The appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.

## Locked engine loops

| Loop | Source | Author or uploader | License | Changes |
|---|---|---|---|---|
| `centurion_fan_loop.wav` | [B-52 Take Off, DVIDS 752134](https://www.dvidshub.net/video/752134/b-52-take-off) | USAF, MSgt Theodore Daigle, VIRIN 180915-F-YH293-1001 | Public domain, US government work | V1 turbine processing plus circular broad-band stabilization and looping |
| `centurion_thrust_loop.wav` | [B-52 Take Off, DVIDS 752134](https://www.dvidshub.net/video/752134/b-52-take-off) | USAF, MSgt Theodore Daigle, VIRIN 180915-F-YH293-1001 | Public domain, US government work | V1 filtered and looped nozzle roar |
| `centurion_cabin_loop.wav` | [Airbus A350 Flaps Extending In Flight](https://freesound.org/people/Marschal/sounds/787790/), original upload: AAC-LC in M4A, 48 kHz mono, SHA-256 `3e74adfca472ec3e7171a0ff0e70a09a2d43f2997a9e7d6a3ccf952283d87f0a` | Marschal | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | 12 to 26 s excerpt at original speed, resampled to 44.1 kHz mono; 35 Hz high-pass and 2200 Hz low-pass, shelf and 450 Hz EQ; slow level stabilization capped at +/-2 dB; 0.8 s pre-roll, 12 s loop with +/-0.2 s seam search and 0.7 s crossfade; circular limiting to -12 LUFS with -1.3 dBTP ceiling; PCM24 output |

[earshot](https://github.com/Leonxlnx/earshot), by Leon Lin, is an analysis and comparison tool used for these loops. Its code is licensed under [MIT](https://github.com/Leonxlnx/earshot/blob/main/LICENSE). Recording licenses are separate. Stock game audio is reference material and is not included in these loops.

## Flap motion loop

`centurion_flap_loop.wav` is an original procedural geared drive, dedicated to CC0 1.0: a 205 Hz harmonic motor with 820 Hz gear-mesh pulses (3 harmonics), 6.2 Hz load and 11.3 Hz screw modulation, and quiet seeded periodic flow at -20 dB (seed 404). It replaces an earlier loop whose filtered pressure noise made up about 74% of its power and read as static. No recording, stock game sample or earshot ingredient is included. The 20 s mono loop is loudness-matched to -10.59 LUFS, then halved in amplitude (-6 dB, -16.61 LUFS). Output SHA-256 `4a97356661ceab6e5c11ca5735e3773afe82655198e453b4465fd5d70e2833fd`. Runtime volume follows mean engine RPM, normalized from each engine's idle to maximum RPM: 0.45 at idle and 1 at full power, multiplied by actual flap movement rate.

The telescoping drive references the installed game's `ShelterMovingSound` through a Blueprinter placeholder. No stock audio file is copied into the mod.

## V1 prototype sources

| Source | License | Author | Original file | Used in |
|---|---|---|---|---|
| [DVIDS 752134, B-52 Take Off (RAF Fairford, 2018)](https://www.dvidshub.net/video/752134/b-52-take-off) | Public domain (US government work) | USAF, MSgt Theodore Daigle, VIRIN 180915-F-YH293-1001 | [file](https://d34w7g4gy10iej.cloudfront.net/video/2005/DOD_107809281/DOD_107809281-1024x576-1769k.mp4) | `centurion_turbine`, `centurion_thrust` |
| [File:Springlocked cellar door.ogg](https://commons.wikimedia.org/wiki/File:Springlocked_cellar_door.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/9/9b/Springlocked_cellar_door.ogg) | `centurion_laser_start`, `centurion_laser_end`, `centurion_bay_open`, `centurion_bay_close`, `centurion_gear_latch`, `centurion_panel_tear` |
| [File:Clickick switch.ogg](https://commons.wikimedia.org/wiki/File:Clickick_switch.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/8/8e/Clickick_switch.ogg) | `centurion_laser_start`, `centurion_laser_end` |
| [File:Can of compressed air.ogg](https://commons.wikimedia.org/wiki/File:Can_of_compressed_air.ogg) | Public domain | stilgar (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/0/02/Can_of_compressed_air.ogg) | `centurion_panel_tear` |
| [File:Sound inside the Copa Airlines flight during landing.flac](https://commons.wikimedia.org/wiki/File:Sound_inside_the_Copa_Airlines_flight_during_landing.flac) | CC0 | Wilfredor | [file](https://upload.wikimedia.org/wikipedia/commons/2/21/Sound_inside_the_Copa_Airlines_flight_during_landing.flac) | `centurion_cockpit_drone` |
| [File:Dreadful jarring of dis.ogg](https://commons.wikimedia.org/wiki/File:Dreadful_jarring_of_dis.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/0/0a/Dreadful_jarring_of_dis.ogg) | `centurion_panel_tear` |
| [File:Aggressive electric buzzing.ogg](https://commons.wikimedia.org/wiki/File:Aggressive_electric_buzzing.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/2/23/Aggressive_electric_buzzing.ogg) | `centurion_laser_start`, `centurion_laser_sustained`, `centurion_laser_end` |
| [File:Garage door closing.ogg](https://commons.wikimedia.org/wiki/File:Garage_door_closing.ogg) | Public domain | ezwa (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/c/c2/Garage_door_closing.ogg) | `centurion_bay_open`, `centurion_bay_close` |
| [File:Garage door opening.ogg](https://commons.wikimedia.org/wiki/File:Garage_door_opening.ogg) | Public domain | ezwa (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/4/4e/Garage_door_opening.ogg) | `centurion_bay_open` |
| [File:Hydraulic lift down.ogg](https://commons.wikimedia.org/wiki/File:Hydraulic_lift_down.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/1/13/Hydraulic_lift_down.ogg) | `centurion_bay_open`, `centurion_bay_close`, `centurion_gear_latch` |
| [File:Hydraulic lift pushing up.ogg](https://commons.wikimedia.org/wiki/File:Hydraulic_lift_pushing_up.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/d/d2/Hydraulic_lift_pushing_up.ogg) | `centurion_wing_actuator`, `centurion_gear_fold` |
| [File:MainsBrum50Hz.ogg](https://commons.wikimedia.org/wiki/File:MainsBrum50Hz.ogg) | Public domain | No machine-readable author provided. Julo assumed (based on copyright claims). | [file](https://upload.wikimedia.org/wikipedia/commons/c/ce/MainsBrum50Hz.ogg) | `centurion_capacitor` |
| [File:Metal cabinet door jarring.ogg](https://commons.wikimedia.org/wiki/File:Metal_cabinet_door_jarring.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/2/23/Metal_cabinet_door_jarring.ogg) | `centurion_panel_tear` |
| [File:Electric roof window opening.ogg](https://commons.wikimedia.org/wiki/File:Electric_roof_window_opening.ogg) | Public domain | ezwa (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/a/a9/Electric_roof_window_opening.ogg) | `centurion_wing_actuator` |
| [File:Rusty metal door clasp.ogg](https://commons.wikimedia.org/wiki/File:Rusty_metal_door_clasp.ogg) | Public domain | stephan (via pdsounds.org) | [file](https://upload.wikimedia.org/wikipedia/commons/0/04/Rusty_metal_door_clasp.ogg) | `centurion_panel_tear` |
| [File:STS-132 — Shuttle Gear Drop.mp3](https://commons.wikimedia.org/wiki/File:STS-132_%E2%80%94_Shuttle_Gear_Drop.mp3) | Public domain | NASA | [file](https://upload.wikimedia.org/wikipedia/commons/1/1a/STS-132_%E2%80%94_Shuttle_Gear_Drop.mp3) | `centurion_gear_fold`, `centurion_gear_latch` |
| [File:Killiney Hill Storm Floris 20250804 1537.ogg](https://commons.wikimedia.org/wiki/File:Killiney_Hill_Storm_Floris_20250804_1537.ogg) | CC0 | Karlunun | [file](https://upload.wikimedia.org/wikipedia/commons/6/63/Killiney_Hill_Storm_Floris_20250804_1537.ogg) | `centurion_panel_tear` |

## What was changed, per cue

- `centurion_turbine.wav` (Fan and gearbox whine): 96 s on, varispeed 0.84, TF33 tones notched twice (-38 dB), 1-6 kHz cut 10 dB, high shelf -6 dB at 6 kHz, fan tones 480 and 960 Hz and gearbox whine 3,150 Hz resonated from the recording's own noise, 0.5 s loop crossfade at a calm cut, normalized.
- `centurion_thrust.wav` (Broadband roar): 12 s on (before the camera change), varispeed 0.9, TF33 tones notched, 6th-order low-pass 1.7 kHz, low shelf +2 dB, 0.6 s loop crossfade at a calm cut, normalized.
- `centurion_cockpit_drone.wav` (Cockpit drone): 193 s on (the steadiest cabin stretch: 10 ms crest 2.0 against 4.9 at 150 s), varispeed 0.92, fan tones 480 and 960 Hz resonated, low shelf +3 dB, low-pass 2 kHz, 0.5 s loop crossfade at a calm cut, normalized.
- `centurion_capacitor.wav` (Capacitor whine): varispeed x3.92 (50 Hz hum to 196 Hz), high-pass 120 Hz, +5 dB at 784 Hz, low-pass 7 kHz, loop point matched to the hum's phase, normalized.
- `centurion_laser_start.wav` (Laser start): switch click varispeed 0.6 and door thump varispeed 0.8, each gated to the hit with a 40 and 100 ms decay; buzz swelling in from 0.06 s; low shelf +3 dB; normalized.
- `centurion_laser_sustained.wav` (Laser sustain): 0.3 s on, high-pass 120 Hz, +4 dB at 1.1 kHz, high shelf -4 dB at 8 kHz, loop point matched to the buzz, normalized (about +25 dB of gain).
- `centurion_laser_end.wav` (Laser end): buzz with a pitch glide 1.0 to 0.45 held 0.45 s then decaying; switch click varispeed 0.55 and door thump varispeed 0.7, each gated to the hit; low shelf +3 dB; normalized.
- `centurion_bay_open.wav` (Bay doors, open): garage door motor's steady run (2.85 s on) varispeed 0.7 for 3.3 s of travel, hydraulic lift flow 8 dB under it, low shelf +4 dB, high shelf -6 dB; end clunk from the opening door's latch varispeed 0.6 with a cellar-door thump varispeed 0.6, low shelf +6 dB; normalized.
- `centurion_bay_close.wav` (Bay doors, close): garage door motor's steady run (2.85 s on) varispeed 0.62 for 3.3 s of travel, hydraulic lift flow 8 dB under it, low shelf +4 dB, high shelf -6 dB; end clunk from the closing door's impact varispeed 0.6 with a cellar-door thump varispeed 0.6, low shelf +6 dB; normalized.
- `centurion_wing_actuator.wav` (Telescoping actuator): roof-window screw actuator 3 s on varispeed 0.7, hydraulic lift 4 s on varispeed 0.55 10 dB under it, low shelf +4 dB, high shelf -6 dB, 0.5 s loop crossfade at a calm cut, normalized (about +37 dB of gain on the actuator).
- `centurion_gear_fold.wav` (Gear fold): hydraulic lift from its start varispeed 0.75, Shuttle gear drop varispeed 0.85 6 dB under it, low shelf +3 dB, high shelf -4 dB, 0.4 s fade out, normalized.
- `centurion_gear_latch.wav` (Gear latch): hydraulic lift end-stop clunk varispeed 0.8 gated to the hit, Shuttle gear lock (both clunks) varispeed 0.9, cellar-door thump varispeed 0.7 gated to the hit, the end-stop 20 ms after the lock, low shelf +4 dB, normalized.
- `centurion_panel_tear.wav` (Panel tear): crack from a rusty metal clasp varispeed 0.6 and a door thump varispeed 0.5, gated to the hit; metal cabinet scrape varispeed 0.55 decaying over 0.7 s and dishwasher-door squeal varispeed 0.6 as the shear; storm gust high-passed at 250 Hz plus a compressed-air burst varispeed 0.45 as the wind rush, swelling to 0.5 s then decaying; low shelf +3 dB; normalized.

## Notes

- Files marked "via pdsounds.org" were released to the public domain on pdsounds.org and uploaded to Commons as Ogg; the Commons upload is the original download used here.
- `MainsBrum50Hz.ogg`: Commons gives no machine-readable author; the uploader, User:Julo, is assumed to be the author under the file's public-domain release.
- `STS-132 — Shuttle Gear Drop.mp3`: NASA's own published MP3 (nasa.gov sounds page), so MP3 is the original format.
- Not shipped: `audio/sources.py` also fetches a public-domain speech recording (`File:Joni Ernst on Federal Regualtions.ogg`) used only as the positive control for the voice-activity check.

## Earshot license notice

```text
MIT License

Copyright (c) 2026 Leon Lin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
