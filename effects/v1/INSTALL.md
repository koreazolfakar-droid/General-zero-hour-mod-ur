# Russian Building Destruction v1

Put `!!!!ProjectXRe_RussianDestructionV1.big` alongside the existing nine Project X BIG files. Keep the four leading `!` characters: this overlay must take precedence over `!!ProjectXRe_INI.big`. It works with the optional `!!!ProjectXRe_RussianVisualsV1.big` texture overlay. Restart the game. Install the BIG only; the two source INI files are build inputs, not loose-file replacements. Remove this one destruction overlay and restart to roll back.

This update adds a brief warm flash and fireball, an outward dust cloud, rising fading smoke, sparks and small debris at the existing collapse stages. Three explicit sizes keep outpost effects smaller than factory/command-center effects. Original sound events, existing 3D debris OCLs, collapse delays, damaged-building effects and all gameplay parameters remain unchanged. Weapons, vehicle explosions, other factions, superweapon blast effects, models, audio archives and the engine/APK are preserved.

| Effect size | Building files |
| --- | --- |
| Small | Air-raid, observation and radar outposts |
| Medium | Barracks, coal power plant, helipad, missile silo, supply warehouse, weapon bunker |
| Large | Airfield, command bunker, industrial plant, Tremor, war factory |

| Existing stage | New particles per FX invocation |
| --- | ---: |
| Initial | 16 |
| Delay | 10 |
| Burst | 14 |
| Final | 30 |
| Instant death (including existing construction/dummy death effects) | 42 |

Each emitter produces a single batch and ends. Particles fade within 0.3–7 seconds at the engine's legacy 30-tick particle clock. Burst/delay stages can run repeatedly during the unchanged collapse sequence. These are per-invocation counts, not a limit on an entire battle; existing damage smoke, 3D debris and other units still contribute to rendering cost. No phone FPS improvement is claimed.

The 16-entry overlay contains full copies of the original FXList/ParticleSystem files with 15/24 new definitions appended, plus 14 building files whose existing destruction FX references alone are changed. The builder requires the repaired INI archive SHA-256 `0b5797d866c3389f4528fdca99b06c22c29058670928c71441c4726179f0d060`. Use this repository's current base INI: older/newer independent INI edits cannot be combined automatically with a whole-file overlay.

Archive size: 4,243,944 bytes. SHA-256: `59adcdbaefe3caeee808c53f9b198faf7fb2b19ecab8cd310273678b62d8a7d9`.

CI reproduces the BIG, rejects perpetual emitters and unsupported FX fields, resolves all five reused sprites and existing audio events, checks particle budgets and keyframes, restores building FX references to prove every other byte is unchanged, and verifies the original archives plus the texture overlay. This is static validation, not game execution.

## Game and phone QA still required

- Destroy the power plant, barracks, command center, factories and all outposts; verify flashes, ground dust, rising smoke and debris clear fully.
- Test construction cancellation/destruction, missile-silo and deployed-building dummy deaths, capture, and damaged-building smoke before collapse.
- Test multiple simultaneous collapses with vehicles in view, close/far zoom, day/night and snow; record FPS and check for missing sprites or unexpectedly large flashes.
- Confirm existing wrecks, salvage/respawn behavior, superweapon effects, collapse timing and other factions are unchanged. If the phone's mod loader uses a custom load order, place the destruction BIG first among INI-containing archives.
