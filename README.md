# General Zero Hour — Project X Remastered Russian Mod

## Russian unit reference repairs and continuous validation (11 Oct 2026)

The current `!!ProjectXRe_INI.big` includes the Kashtan AI fix below and these repairs:

| Repair | Result |
| --- | --- |
| Missing `RussianInfantrySVUSniperCommandSet` | SVU gets Attack Move, Guard, Stop and its existing Grizon airdrop ability. |
| Missing `IskanderGroundAttack` | Its existing FIRE_WEAPON button has a 30-unit targeting preview matching the primary blast radius. |
| Missing `MigBomberGroundAttack` | The Su-34 carpet-bomb button has a 40-unit targeting preview matching bomb scatter; its four-shot command is preserved. |
| Missing `OCL_OgreTankDeathEffect` | Ogre's existing death behavior creates debris using its shipped `RVOgre_D1` wreck mesh. No repair/respawn ability is added. |
| Mishka damaged armor model typo | `RVMishka_U_D` now references the existing `RVMishka_UD.W3D`. |

The text sources in `repairs/` append definitions to three existing INI files. One model name is corrected in Mishka's existing file. The other **618 of 622 archived payloads** are byte-identical to the already merged Kashtan baseline. All eight other BIG archives are unchanged. Weapons, upgrades, locomotors, unit balance, faction identifiers, maps, audio and engine code are preserved.

- Baseline commit: `670b62f10f39ffe9016fa7f4e529816fa08ef460`
- Baseline INI SHA-256: `83c6616cbf7a45f0979edebd34d22a157d76751d03359bf62e62ca184d92bb25`
- Current INI SHA-256: `0b5797d866c3389f4528fdca99b06c22c29058670928c71441c4726179f0d060`
- CI: `.github/workflows/mod-ci.yml` runs on every pull request and main push. It tests malformed-archive rejection on Python 3.10/3.12, downloads all nine LFS archives, checks 22,736 indexed entries, resolves the repaired references against the shipped assets, and reproduces the current INI archive byte-for-byte. A successful run provides the installable INI archive and a JSON verification report.

**Install:** Download the current BIG through Git LFS or a successful CI artifact. Back up and replace your existing `!!ProjectXRe_INI.big` with it. Keep the other eight archives and the working load order. The `repairs/` directory is build input, not an additional loose INI installation.

**Reproduce locally:** Fetch the baseline commit and its INI LFS object, then run:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/patch_russian_references.py /path/to/baseline.big /path/to/repaired.big
python3 scripts/validate_mod.py --baseline /path/to/baseline.big
```

The validator expects all nine current BIG files in this checkout. Do not feed the repaired archive back into the patcher: it intentionally accepts only the pinned baseline.

**Remaining validation and source gaps:** CI verifies data and references; it does not launch Generals or run an Android/device test. In game, check SVU controls/airdrop, Iskander/Su-34 ground targeting, Ogre death debris, Mishka damaged armor and Russian Hard AI defense construction. Missing upgraded damaged helicopter meshes (`RVHellion_UD`, `RVHnchBck_UD`, `RVHind_UD`), Grizon's `RVBBMP_B` exit-bone model and Kodiak variant wreck meshes still need the correct authored assets. No replacement mesh is guessed. No `SkirmishScripts.scb` exists in these nine archives; a tactical AI overhaul requires the actual intended scripts. These repairs do not change Topol's upgrade prerequisite or artillery speed/reload values.

## Russian Skirmish AI — Kashtan defense fix (11 Oct 2026)

This repository contains **mod assets only**. This change does **not** update the Android or PC game engine, change units' damage/speed, modify saved-game/network formats, or alter AI scripts.

**Confirmed issue:** In `Data/INI/Default/AIData.ini`, the `SideInfo AmericaLaserGeneral` (Russia) declared:

```ini
BaseDefenseStructure1 Russia_RussiaKashtan
```

But the actual defense object is declared as `Object RussiaKashtan` in `Data/INI/Object/Russia/Defences/KashtanDefence.ini`. The skirmish-AI defense template reference is now:

```ini
BaseDefenseStructure1 RussiaKashtan
```

**Scope and validation:** Exactly 1 entry in the `!!ProjectXRe_INI.big` archive changed, out of 622. All other 621 archived file contents are byte-identical to the original. GitHub Actions generated and verified the new archive from the exact original Git LFS object; it did **not** rebuild the game engine or Android APK.

- Original LFS SHA-256: `214a17c3d501ec756d82f375353e329dfe0e7e074dc9f5f9e2d42d8fbe6f5fe4`
- Intermediate AI-only BIG SHA-256: `83c6616cbf7a45f0979edebd34d22a157d76751d03359bf62e62ca184d92bb25`
- QA: [mod-only repair CI run](https://github.com/koreazolfakar-droid/General-zero-hour-mod-ur/actions/runs/38096463915)
- Source/test implementation: `scripts/patch_russian_skirmish_defense.py`

**Installation:** Make a backup of your currently working mod archive, then replace its **`!!ProjectXRe_INI.big`** with this repository's updated file (via Git LFS or the attached successful Actions artifact). Keep all other mod BIG files and their working load order unchanged. Do not install both old and new INI archives simultaneously.

**Limitations:** This corrects a specific Russian defensive AI reference; it does not by itself overhaul Hard AI tactics. A physical-device Russian Skirmish (Hard) test is still needed to confirm Kashtan construction and check CPU/FPS, guard behavior, attacks, and other mod armies. A separate future tactical-script review is necessary to fix any missing or invalid `SkirmishScripts.scb` team conditions.
