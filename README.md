# General Zero Hour — Project X Remastered Russian Mod

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
- Corrected BIG SHA-256: `83c6616cbf7a45f0979edebd34d22a157d76751d03359bf62e62ca184d92bb25`
- QA: [mod-only repair CI run](https://github.com/koreazolfakar-droid/General-zero-hour-mod-ur/actions/runs/38096463915)
- Source/test implementation: `scripts/patch_russian_skirmish_defense.py`

**Installation:** Make a backup of your currently working mod archive, then replace its **`!!ProjectXRe_INI.big`** with this repository's updated file (via Git LFS or the attached successful Actions artifact). Keep all other mod BIG files and their working load order unchanged. Do not install both old and new INI archives simultaneously.

**Limitations:** This corrects a specific Russian defensive AI reference; it does not by itself overhaul Hard AI tactics. A physical-device Russian Skirmish (Hard) test is still needed to confirm Kashtan construction and check CPU/FPS, guard behavior, attacks, and other mod armies. A separate future tactical-script review is necessary to fix any missing or invalid `SkirmishScripts.scb` team conditions.
