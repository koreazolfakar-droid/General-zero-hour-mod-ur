# Russian Visuals v1 — optional diffuse texture update

Download **`!!!ProjectXRe_RussianVisualsV1.big`** (6,292,735 bytes) through Git LFS, the direct download in the repository README, or a successful `projectx-russian-mod-verified` CI artifact. Put this one additional BIG in the same mod directory as the existing nine Project X archives. Keep its exact filename and load it ahead of `!ProjectXRe_Art.big`; the engine's alphabetically-first archive precedence makes the three leading `!` characters significant. Restart the game after installation.

Do not install the `visuals/v1/Art/Textures` source folder as loose files. Do not replace the original Art BIG. To roll back, remove only `!!!ProjectXRe_RussianVisualsV1.big` and restart.

SHA-256: `9b99add57f84b9351e4db73e534fbf990e168cb93e751d6bae6f709ac94942e5`

| Main target | Updated atlases | Resolution |
| --- | --- | --- |
| Coal power plant | `RBCPwrPlnt1` | 512 → 1024 |
| Barracks | `RBBarr_1`, `RBBarr_2` | 256 → 1024 |
| Command center | `RBCmdBnkr1`, `RBCmdBnkr2` | 512 → 1024 |
| Kodiak hull and standard turret | `RVKodiakC`, `RVKodiakT` | 256 → 1024 |

The seven diffuse atlases add material detail to concrete, brick, painted armor, panels and vents. UV coordinates, geometry, animation, exit bones, INI definitions and faction-color textures stay in the original archives. Every new DDS has 11 mip levels through 1×1, keeps the original DXT1/DXT3 format, and preserves the original alpha via exact nearest sampling at each mip. These are diffuse textures, not PBR maps or new 3D parts. Full mip chains improve texture minification but do not guarantee unchanged FPS.

Some atlases are shared: the industrial plant and war factory use `RBBarr_2`; the Russian waypoint base uses `RBCmdBnkr2`; BMD and some Kodiak MG/damaged variants use `RVKodiakT`. These areas also receive the new texture. See `affected-models.json` for the complete W3D reference inventory. Separate night, snow, damaged and variant turret atlases are preserved; this is a first pass, not a complete replacement of all visual states or Russian vehicles. Explosions/particles are unchanged.

## Verification and remaining game checks

CI checks archive indexes, original archive preservation, the seven DDS hashes, compression headers, mip extents, alpha masks at all levels, and deterministic reconstruction of the overlay. The comparison JPGs are offline renders of the actual W3D models with simplified lighting, not screenshots. The renderer does not execute game animations or particles.

Game/device testing is still required: inspect the three buildings and Kodiak at normal/close zoom, test blue/red player colors, building doors and infantry exits, Kodiak turret movement and upgrades, damage/rubble, snow/night transitions, Russian waypoint markers and the shared factory/BMD areas. Compare FPS and memory with and without the overlay in the same scene. If the new visuals do not appear, verify archive precedence in the active engine build. No APK or engine update is included.

## Rebuild

The committed DDS files are the canonical shipping artwork; AI generation is not deterministic. `generation-prompts.json` records the prompts and `manifest.json` records original/generated/output hashes. The original generated PNG hashes are provenance metadata; those PNGs are not required to reproduce the shipped BIG from the DDS sources.

```sh
python3 scripts/build_russian_visuals.py
python3 scripts/validate_russian_visuals.py
MOD_ARCHIVE_TESTS=1 python3 -m unittest discover -s tests -v
```

The checks require downloaded original BIGs. To regenerate offline comparisons, install Pillow and NumPy, then run `python3 scripts/preview_russian_visuals.py` and `python3 scripts/preview_russian_visuals.py --shared`. This preview uses original hierarchy base poses and diffuse UVs; it skips light/muzzle/glow/lens-flare effect meshes and follows the listed default hidden subobjects.
