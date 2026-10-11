# Russian Building Destruction v1 — embedded in the original INI BIG

Replace `!!ProjectXRe_INI.big` using the download in the repository README. Follow [the combined installation guide](../../updates/integrated-v1/INSTALL.md). No additional BIG or loose INI folder is needed.

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

Sixteen payloads inside the original 622-entry INI archive receive the destruction update: 14 building files change existing FX references, while FXList/ParticleSystem keep all original definitions and append 15/24 new templates. The earlier SVU/targeting/Ogre/Mishka/Kashtan repairs remain embedded. CI checks finite emitters, five reused sprites, sound references, budgets, keyframes and exact gameplay-byte preservation. Static validation only.

## Game and phone QA still required

- Destroy the power plant, barracks, command center, factories and all outposts; verify flashes, ground dust, rising smoke and debris clear fully.
- Test construction cancellation/destruction, missile-silo and deployed-building dummy deaths, capture, and damaged-building smoke before collapse.
- Test multiple simultaneous collapses with vehicles in view, close/far zoom, day/night and snow; record FPS and check for missing sprites or unexpectedly large flashes.
- Confirm existing wrecks, salvage/respawn behavior, superweapon effects, collapse timing and other factions are unchanged. Confirm the active mod directory contains the updated original INI archive.
