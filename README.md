# General Zero Hour — Project X Remastered Russian Mod

## Updated original archives — Russian graphics and destruction

The Russian texture and building-destruction updates are now embedded in the original mod files. Install the same nine BIG files; no additional visual/destruction BIG is shipped.

| Original mod file | Direct download | Size | Update |
| --- | --- | ---: | --- |
| `!ProjectXRe_Art.big` | [Download full Art BIG](https://media.githubusercontent.com/media/koreazolfakar-droid/General-zero-hour-mod-ur/main/%21ProjectXRe_Art.big) | 1.25 GB | Seven 1024×1024 building/Kodiak diffuse atlases |
| `!!ProjectXRe_INI.big` | [Download full INI BIG](https://media.githubusercontent.com/media/koreazolfakar-droid/General-zero-hour-mod-ur/main/%21%21ProjectXRe_INI.big) | 27.2 MB | Russian building destruction plus existing unit/AI repairs |

Replace those two files in the active mod directory and keep the other seven original archives. If you installed the earlier `!!!ProjectXRe_RussianVisualsV1.big` or `!!!!ProjectXRe_RussianDestructionV1.big`, remove those add-ons. Restart the game; an already imported Mod Manager copy must also be replaced/re-imported. See [installation and hashes](updates/integrated-v1/INSTALL.md).

The Art file is the full original graphics archive. Its seven updated atlases cover the coal power plant, barracks, command center and Kodiak hull/standard turret, plus shared Russian factory/BMD/waypoint surfaces. Original W3D models, UVs, codecs and alpha masks are preserved; separate snow/night/damage atlases are unchanged. [Visual scope](visuals/v1/INSTALL.md).

Russian building collapse gains brief warm flashes/fireballs, outward dust, rising fading smoke, sparks and small debris, using small/medium/large sizes across fourteen building files. Each new emitter fires once and fades within 0.3–7 seconds. Existing collapse timing, 3D debris OCLs, sounds and all gameplay fields are preserved. Weapon, vehicle and other faction explosions are unchanged. [Effect stages/budgets and game QA](effects/v1/INSTALL.md).

[Before/after front](docs/visuals/comparison-front.jpg) · [Before/after rear](docs/visuals/comparison-rear.jpg) · [Shared surfaces](docs/visuals/comparison-shared.jpg). These are offline texture/model previews with simplified lighting, not game screenshots.

## Preservation and CI

CI runs unit checks on Python 3.10/3.12 and downloaded-archive checks against immutable Git LFS originals. It verifies exactly nine BIGs and 22,736 entries, original index names/order/padding, all seven DDS codecs/mips/alpha masks, finite destruction emitters and all sprite/audio references. Exactly seven Art payloads change; 10,664 other Art payloads are identical. Exactly twenty INI payloads differ from the earlier AI-fixed baseline: four existing reference repairs and sixteen destruction payloads; 602 remain identical. All seven other BIG archives are unchanged.

The verified CI artifact contains the updated INI, installation notes, texture previews, hashes and validation report. Download the full Art archive through the direct Git LFS link above. CI does not run the game or measure phone FPS. No engine/APK update is included.

## Existing unit and AI repairs retained

| Repair | Result |
| --- | --- |
| Missing `RussianInfantrySVUSniperCommandSet` | SVU gets Attack Move, Guard, Stop and its existing Grizon airdrop ability. |
| Missing `IskanderGroundAttack` | Its existing FIRE_WEAPON button has a 30-unit targeting preview matching the primary blast radius. |
| Missing `MigBomberGroundAttack` | The Su-34 carpet-bomb button has a 40-unit targeting preview matching bomb scatter; its four-shot command is preserved. |
| Missing `OCL_OgreTankDeathEffect` | Ogre's existing death behavior creates debris using its shipped `RVOgre_D1` wreck mesh. No repair/respawn ability is added. |
| Mishka damaged armor model typo | `RVMishka_U_D` now references the existing `RVMishka_UD.W3D`. |

The repair sources remain in `repairs/`. The Kashtan AI defense reference uses the existing `RussiaKashtan` object, retaining the fix from baseline commit `670b62f10f39ffe9016fa7f4e529816fa08ef460`. Weapons, upgrades, locomotors, faction IDs, maps, audio, engine code, save/network formats and AI scripts are preserved.

## Reproduce locally

Download the shipped originals and immutable source objects:

```sh
git lfs pull --include='*.big' --exclude=''
git fetch --depth=1 origin 670b62f10f39ffe9016fa7f4e529816fa08ef460
git lfs fetch origin 670b62f10f39ffe9016fa7f4e529816fa08ef460 --include='!!ProjectXRe_INI.big' --exclude=''
git fetch --depth=1 origin afc5b1e802b8481db9857f2c6c2e2bda2eb73009
git lfs fetch origin afc5b1e802b8481db9857f2c6c2e2bda2eb73009 --include='!ProjectXRe_Art.big' --exclude=''
python3 scripts/integrate_russian_updates.py --output-dir /tmp/reproduced-projectx
MOD_ARCHIVE_TESTS=1 python3 -m unittest discover -s tests -v
python3 scripts/validate_mod.py --baseline .git/lfs/objects/83/c6/83c6616cbf7a45f0979edebd34d22a157d76751d03359bf62e62ca184d92bb25
```

The builder pins the original Art SHA-256 and AI-fixed INI SHA-256, reproduces the existing repairs, then embeds the reviewed texture/effect sources. Source folders are build inputs; install only the two replacement original BIGs.

Remaining game/device checks include SVU controls/airdrop, Iskander/Su-34 targeting, Ogre debris, Mishka armor, Kashtan AI construction, building destruction and visual/performance QA. Missing upgraded damaged helicopter meshes, Grizon's exit-bone mesh and Kodiak variant wreck meshes still need correct authored assets. No `SkirmishScripts.scb` exists in these archives; a tactical AI overhaul needs the intended scripts.
