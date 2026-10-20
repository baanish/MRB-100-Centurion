# Releasing MRB-100 Centurion

Releases come from [baanish/MRB-100-Centurion](https://github.com/baanish/MRB-100-Centurion). Build locally with Unity and the purchased game's assemblies, following [BUILD.md](../BUILD.md). GitHub Actions verifies uploaded assets after publication. It does not build the mod or publish to NOMNOM.

## Prepare and package locally

1. Set the same version in `src/Centurion/CenturionPlugin.cs`, `src/Centurion/Centurion.csproj` and `unity/Assets/Blueprinter/Mods/centurion/modinfo.json`. The scenarios and their generators name the bundle by version (`build/centurion_<version>.nobp`): replace the old name across `tests/agentic` and `tools` byte for byte (Python `read_bytes`/`write_bytes`; `sed -i` on Windows strips the CRLF files), or the playtests keep loading the previous build.
2. After intentional exports, run `python tools/scrub_fbx.py` and `python tools/export_manifest.py --write`. The scrubber blanks native scene and absolute texture path metadata, preserves relative texture references, and verifies every other FBX node value. Commit `art/export-manifest.json` with the release source. The private checkout ignores the exports; the public checkout commits every export named by that manifest. Builds check those hashes and never re-export from a cached AWACS scene. Close the Unity editor for `unity/`.
3. Run this single command from the repository root:

   ```powershell
   pwsh -NoProfile -File tools/Package-Release.ps1
   ```

   Optionally pass `-NotesFile <markdown-file>` to include release-specific changes. `-CheckOnly` checks the pinned exports, committed inputs, versions and licence without Unity. The command builds the plugin from HEAD and the bundle, checks their versions and hashes, rejects tracked changes caused by the build except prefab fileIDs, and runs the Unity identity check. That check rejects game meshes and textures in the bundle and checks aircraft structure. The command then packages and verifies both archives, the manifest and their metadata. It publishes nothing.

4. Require a final `RELEASE PASS` line. Outputs are in `.cache/release/v<version>-<UTC time>/`:

   | File | Purpose |
   | --- | --- |
   | `Centurion-v<version>-nomm.zip` | Flat payload for NOMM. Its name sorts first among release assets. |
   | `Centurion-v<version>-plugin-only.zip` | Manual game-root installation, including `BepInEx/plugins/baanish.centurion/`. |
   | `Centurion-v<version>-nomnom.json` | Initial catalog listing, with the NOMM ZIP hash and public download URL. |
   | `RELEASE-NOTES.md` | Release body with absolute links at the version tag. |
   | `SHA256SUMS.txt` | SHA-256 of both archives, the manifest and notes. |

   GitHub returns release assets sorted by name, ignoring case. `Centurion-v<version>-nomm.zip` sorts before `Centurion-v<version>-nomnom.json`, the manual ZIP, `RELEASE-NOTES.md` and `SHA256SUMS.txt`. Keep these names so NOMNOM imports the NOMM ZIP. Upload order does not control the API order.

   Staging `meta.json` and `README.md` also remain in the output directory. They are already inside both archives; do not upload them separately. Both archives carry the same DLL, bundle, metadata, README and licence, plus `audio/CREDITS.md` when sounds are present. Packaged README links point to the public source at `v<version>`. The DLL and bundle share one mod folder so NOMM toggles them together.

`-AllowDirty` is for local rehearsals. Warnings about dirty source, changed assets, version disagreements or the placeholder licence mark outputs `-LOCAL`. Never publish those files. Release verification rejects rehearsal tags.

## Validate the install before publication

On a clean game profile with BepInEx 5 and Blueprinter 2.0.1+, extract the manual archive beside `NuclearOption.exe`. Check the installed DLL against the hash in its `meta.json`. Read `BepInEx/LogOutput.log` for the correct mod version and errors, spawn from a medium hangar and fly a circuit. Static packaging and CI verification do not establish gameplay or multiplayer compatibility. Keep releases as prereleases until two-PC multiplayer validation passes.

## Publish on GitHub

For the first release, create the public `baanish/MRB-100-Centurion` GitHub repository and push the public source. It must include the unobfuscated source matching the plugin DLL. Enable GitHub Actions. For every release:

1. Push the source commit used by the local package. Tag that exact public commit `v<version>` and push the tag. A tag alone does not run the asset verifier.
2. Run `pwsh -NoProfile -File tools/Publish-Release.ps1 -Directory <package-directory> -Tag v<version>`. It refuses missing or invalid assets and requires the tag to exist remotely. It creates a draft prerelease and uploads exactly the five documented assets. Before publishing, it checks their sizes, digests and case-insensitive name order with the NOMM ZIP first. It then publishes and verifies the prerelease. It never creates tags or pushes. If an upload or draft check fails, the draft stays unpublished; inspect it before retrying.
3. Require a green **Verify release assets** workflow. It downloads those five assets and checks hashes, manifest version and URLs, Blueprinter dependency, archive layout, paired payloads, embedded `meta.json`, GitHub asset metadata and NOMM-first order before submitting the catalog listing.

The workflow runs on `release.published`, including prereleases published from drafts. If assets are corrected later, rerun it from Actions with the published tag as its input. Edits to an existing release do not trigger a new published event. A failed check reports a published release problem; it cannot prevent NOMNOM from discovering that release. Verify locally before publishing:

```powershell
pwsh -NoProfile -File tools/Verify-Release.ps1 -Directory <package-directory> -Tag v<version>
```

The manifest template currently emits `preRelease`. When promoting to stable releases, change that template category to `release` and update the release notes' multiplayer status before packaging. The verifier rejects a category that disagrees with GitHub's prerelease flag.

## Register in NOMM once

Fork [KopterBuzz/NOMNOM](https://github.com/KopterBuzz/NOMNOM) and submit the generated `Centurion-v<version>-nomnom.json` as `modManifests/baanish.centurion.json` in a pull request to `main`. Do not edit the compiled catalog. After acceptance, refresh NOMM and install Centurion from its catalog to check dependency installation and toggling.

The listing sets `autoUpdateArtifacts` to the string `"True"`. NOMNOM's hourly updater discovers subsequent GitHub releases from this repository and imports the first asset. No recurring registration PR, publishing token or upstream-dispatch workflow is needed. The updater copies dependencies and game version from the previous artifact, so a later change to those requirements needs a catalog correction as well as a template change.

## Dependency contract and upstream evidence

The release manifest and packaged `meta.json` both declare:

```json
"dependencies": [
  { "id": "com.nikkorap.blueprinter", "version": "2.0.1" }
]
```

- [NOMNOM's schema](https://github.com/KopterBuzz/NOMNOM/blob/main/SCHEMA.md#dependencies) defines dependency versions as minimum compatible versions. [ValidationSchema.json](https://github.com/KopterBuzz/NOMNOM/blob/main/ValidationSchema.json) requires an `id` and `version` for each dependency. A description or tag alone creates no dependency relationship.
- [Blueprinter's catalog entry](https://github.com/KopterBuzz/NOMNOM/blob/main/modManifests/com.nikkorap.blueprinter.json) uses exactly `com.nikkorap.blueprinter` and provides 2.0.1 for game 0.34.2. Existing plugin entries [AGR31Tenpin](https://github.com/KopterBuzz/NOMNOM/blob/main/modManifests/AGR31Tenpin.json) and [Apex-6](https://github.com/KopterBuzz/NOMNOM/blob/main/modManifests/Apex-6.json) also declare Blueprinter 2.0.1 in `dependencies`. Centurion remains `type: plugin`, without `extends`, because its DLL and bundle belong together in their own folder.
- NOMM's [RepoMods.kt](https://github.com/Combat787/NOMM/blob/a251c6f55591659e5f0a77770006d2fe9dbfc445/composeApp/src/jvmMain/kotlin/com/combat/nomm/RepoMods.kt#L141-L178) recursively installs each dependency's latest catalog version during installation. It does not pass the declared minimum version to that resolver or wait for dependencies to succeed before installing Centurion.
- Its [LocalMods.kt](https://github.com/Combat787/NOMM/blob/a251c6f55591659e5f0a77770006d2fe9dbfc445/composeApp/src/jvmMain/kotlin/com/combat/nomm/LocalMods.kt#L539-L585) reports missing or disabled dependencies. The resolve action installs missing dependencies and enables disabled ones. These checks do not compare versions, and ordinary `dependencies` do not block enabling Centurion. Users must confirm Blueprinter is enabled and at least 2.0.1. This is a manager limitation, not a guarantee of strict version enforcement.
- BepInEx 5 is a loader prerequisite managed separately by NOMM's [downloadBepInEx and installation path](https://github.com/Combat787/NOMM/blob/a251c6f55591659e5f0a77770006d2fe9dbfc445/composeApp/src/jvmMain/kotlin/com/combat/nomm/RepoMods.kt#L95-L138). When absent, NOMM starts installation of BepInEx 5.4.23.4 and returns from the mod install attempt. Retry the mod installation after the loader finishes if necessary. There is no BepInEx loader catalog entry to reference. `BepInEx.ConfigurationManager` is a different, optional mod.
- [NOMNOM's acceptance policy](https://github.com/KopterBuzz/NOMNOM#mod-submission-acceptance-policy) requires matching public source, BepInEx 5 compatibility, parseable version tags and the intended package first. [Update-ModArtifact.ps1](https://github.com/KopterBuzz/NOMNOM/blob/main/Update-ModArtifact.ps1) reads the first GitHub asset and carries forward dependency metadata. [hourly_update.yml](https://github.com/KopterBuzz/NOMNOM/blob/main/.github/workflows/hourly_update.yml) schedules discovery. The manifest is a separate submission asset; the updater does not ingest it from each release.
