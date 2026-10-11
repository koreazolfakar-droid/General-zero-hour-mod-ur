# Russian Visuals v1 — embedded in the original Art BIG

The seven updated textures are now inside `!ProjectXRe_Art.big`. Replace that original mod file using the download in the repository README. Follow [the combined installation guide](../../updates/integrated-v1/INSTALL.md); remove any previously installed standalone visual/destruction BIGs. No additional BIG or loose DDS folder is needed.

| Main target | Updated atlases | Resolution |
| --- | --- | --- |
| Coal power plant | `RBCPwrPlnt1` | 512 → 1024 |
| Barracks | `RBBarr_1`, `RBBarr_2` | 256 → 1024 |
| Command center | `RBCmdBnkr1`, `RBCmdBnkr2` | 512 → 1024 |
| Kodiak hull and standard turret | `RVKodiakC`, `RVKodiakT` | 256 → 1024 |

The seven diffuse atlases add material detail to concrete, brick, painted armor, panels and vents. UV coordinates, geometry, animation, exit bones, INI definitions and faction-color textures stay in the original archives. Every new DDS has 11 mip levels through 1×1, keeps the original DXT1/DXT3 format, and preserves the original alpha via exact nearest sampling at each mip. These are diffuse textures, not PBR maps or new 3D parts. Full mip chains improve texture minification but do not guarantee unchanged FPS.

Some atlases are shared: the industrial plant and war factory use `RBBarr_2`; the Russian waypoint base uses `RBCmdBnkr2`; BMD and some Kodiak MG/damaged variants use `RVKodiakT`. These areas also receive the new texture. See `affected-models.json` for the complete W3D reference inventory. Separate night, snow, damaged and variant turret atlases are preserved; this is a first pass, not a complete replacement of all visual states or Russian vehicles. Explosions/particles are unchanged.

## Verification and remaining game checks

CI checks archive indexes, original archive preservation, the seven DDS hashes, compression headers, mip extents, alpha masks at all levels, and exact preservation of all other Art payloads and index bytes. The comparison JPGs are offline renders of the actual W3D models with simplified lighting, not screenshots. The renderer does not execute game animations or particles.

Game/device testing is still required: inspect the three buildings and Kodiak at normal/close zoom, test blue/red player colors, building doors and infantry exits, Kodiak turret movement and upgrades, damage/rubble, snow/night transitions, Russian waypoint markers and the shared factory/BMD areas. Compare FPS and memory before and after replacing the original Art archive in the same scene. If the new visuals do not appear, confirm that the active mod directory contains the downloaded original Art archive. No APK or engine update is included.

## Rebuild

The committed DDS files are the canonical shipping artwork; AI generation is not deterministic. `generation-prompts.json` records the prompts and `manifest.json` records original/generated/output hashes. The original generated PNG hashes are provenance metadata; those PNGs are not required to reproduce the shipped BIG from the DDS sources.

```sh
python3 scripts/build_russian_visuals.py
python3 scripts/validate_russian_visuals.py
MOD_ARCHIVE_TESTS=1 python3 -m unittest discover -s tests -v
```

The checks require downloaded original BIGs. To regenerate offline comparisons, install Pillow and NumPy, then run `python3 scripts/preview_russian_visuals.py` and `python3 scripts/preview_russian_visuals.py --shared`. This preview uses original hierarchy base poses and diffuse UVs; it skips light/muzzle/glow/lens-flare effect meshes and follows the listed default hidden subobjects.
