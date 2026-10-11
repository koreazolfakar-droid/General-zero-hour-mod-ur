# Install the updated original mod archives

1. Close the game and back up your working `!ProjectXRe_Art.big` and `!!ProjectXRe_INI.big`.
2. Download the two updated original BIG files from the repository README. Replace the files with those exact names in the active Project X mod directory. Keep the other seven original mod archives.
3. If previously installed, remove `!!!ProjectXRe_RussianVisualsV1.big` and `!!!!ProjectXRe_RussianDestructionV1.big` from that mod directory. Their updates are now embedded in the original files; keeping old whole-file overrides can mask later INI changes.
4. Restart the game. If importing a ZIP through Mod Manager, rebuild/re-import your mod package with the two updated originals and the existing other seven archives. Updating an external downloaded file does not automatically update an already imported copy.

There are exactly nine shipped BIG files. No extra BIG, loose INI/DDS folder, engine update or APK is required. To roll back, restore your backed-up originals.

| Original file to replace | Contents | Size (decimal) |
| --- | --- | ---: |
| `!ProjectXRe_Art.big` | Seven 1024×1024 texture atlases for Russian buildings and Kodiak/shared surfaces | 1,253,328,669 bytes (1.25 GB) |
| `!!ProjectXRe_INI.big` | Existing repairs plus Russian building flashes, dust, smoke, sparks and debris | 27,195,960 bytes (27.2 MB) |

SHA-256 hashes are in [manifest.json](manifest.json). The Art download is the complete original graphics archive, explaining its larger size compared with the previous small add-on.

Validation preserves all index names/order, 10,664 of 10,671 Art payloads, 602 of 622 INI payloads relative to the earlier AI-fixed baseline, and all seven other original archives. Of the 20 changed INI payloads, four contain the already shipped unit-reference repairs and sixteen contain destruction effects; building gameplay/timing/OCL values remain unchanged. Texture codecs, UV/model data, alpha masks and all 11 mips are preserved/verified.

Game/device QA remains required: confirm the installed/imported originals are active, inspect building/Kodiak textures, destroy buildings individually and simultaneously, check construction/deployed dummies, compare day/night/snow and performance. See [visual scope](../../visuals/v1/INSTALL.md) and [destruction scope/budgets](../../effects/v1/INSTALL.md). CI does not launch the game or measure phone FPS.
