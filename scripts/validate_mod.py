#!/usr/bin/env python3
"""Validate the shipped archives, repair references and preservation of the baseline."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import re

from big_archive import payloads, read_index
from patch_russian_references import APPENDS, CHANGED_PATHS, MISHKA, SOURCE_SHA256, patch
from build_russian_visuals import ARCHIVE as VISUAL_ARCHIVE
from validate_russian_visuals import validate as validate_visuals
from build_russian_destruction import ARCHIVE as DESTRUCTION_ARCHIVE
from validate_russian_destruction import validate as validate_destruction


def require(condition, message):
    if not condition:
        raise ValueError(message)


def definition(files, kind, name):
    pattern = re.compile(rb"(?m)^" + kind.encode() + rb"[ \t]+" +
                         re.escape(name.encode()) + rb"[ \t]*\r?$")
    found = []
    for path, data in files.items():
        if not path.endswith(".ini"):
            continue
        for match in pattern.finditer(data):
            depth = 1
            lines = []
            for raw in data[match.end():].splitlines():
                line = raw.split(b";", 1)[0].strip()
                if line in (b"CreateDebris", b"CreateObject", b"CreateParticleSystem"):
                    depth += 1
                if line.lower() == b"end":
                    depth -= 1
                    if depth == 0:
                        found.append(b"\n".join(lines))
                        break
                lines.append(line)
            else:
                raise ValueError("unterminated definition: " + name)
    require(len(found) == 1, "definition must resolve exactly once: " + name)
    return found[0]


def field(block, name):
    pattern = rb"(?mi)^[ \t]*" + re.escape(name.encode()) + rb"[ \t]+(?:=[ \t]*)?([^\r\n;]+)"
    values = re.findall(pattern, block)
    require(len(values) == 1, "field must resolve exactly once: " + name)
    return values[0].strip().decode("ascii")


def check_references(files, assets):
    svu = files["data/ini/object/russia/infantry/svusniper.ini"]
    commandset = re.search(rb"CommandSet[ \t]*=[ \t]*([^\s;]+)", svu).group(1).decode()
    commands = definition(files, "CommandSet", commandset)
    slots = {int(n): command.decode() for n, command in
             re.findall(rb"(?m)^([0-9]+)[ \t]*=[ \t]*([^\s;]+)$", commands)}
    require(slots == {7: "Command_RussiaCallinGrizonAirdrop", 15: "Command_AttackMove",
                      17: "Command_Guard", 18: "Command_Stop"}, "SVU controls incomplete")
    for name in slots.values():
        definition(files, "CommandButton", name)
    airdrop = definition(files, "CommandButton", slots[7])
    ability = field(airdrop, "SpecialPower")
    definition(files, "SpecialPower", ability)
    require(re.search(rb"SpecialPowerTemplate[ \t]*=[ \t]*" + ability.encode() + rb"\b", svu),
            "SVU airdrop button has no matching behavior")
    for command, template, radius in (
        ("Command_IskanderGroundAttack", "IskanderGroundAttack", "30"),
        ("Command_MigBomberCarpetBomb", "MigBomberGroundAttack", "40"),
    ):
        button = definition(files, "CommandButton", command)
        require(field(button, "Command") == "FIRE_WEAPON", "ground attack must fire the weapon")
        require(field(button, "SpecialPower") == template, "targeting template mismatch")
        require(field(button, "WeaponSlot") == "PRIMARY", "weapon slot changed")
        power = definition(files, "SpecialPower", template)
        require(field(power, "Enum") == "SPECIAL_INVALID", "cursor-only template became an ability")
        require(field(power, "RadiusCursorRadius") == radius, "incorrect targeting radius")
        require(field(power, "ReloadTime") == "0" and field(power, "PublicTimer") == "No",
                "cursor-only template must not introduce a cooldown")
    bomber = definition(files, "CommandButton", "Command_MigBomberCarpetBomb")
    require(field(bomber, "MaxShotsToFire") == "4", "bomber firing behavior changed")
    ogre = files["data/ini/object/russia/vehicles/ogre.ini"]
    require(re.search(rb"OCL\s+FINAL\s+OCL_OgreTankDeathEffect\b", ogre), "Ogre death effect unconnected")
    wreck = definition(files, "ObjectCreationList", "OCL_OgreTankDeathEffect")
    require(field(wreck, "ModelNames") == "RVOgre_D1", "wrong Ogre wreck mesh")
    require(b"CreateDebris" in wreck and b"CreateObject" not in wreck, "unexpected Ogre gameplay object")
    require("art/w3d/rvogre_d1.w3d" in assets, "Ogre wreck mesh absent")
    require(b"RVMishka_U_D" not in files[MISHKA] and b"RVMishka_UD" in files[MISHKA],
            "Mishka damaged-armor typo remains")
    require("art/w3d/rvmishka_ud.w3d" in assets, "Mishka repaired mesh absent")
    ai = files["data/ini/default/aidata.ini"]
    side = ai.split(b"SideInfo AmericaLaserGeneral ; Russia", 1)[1].split(b"SideInfo AmericaSuperWeaponGeneral", 1)[0]
    require(re.search(rb"BaseDefenseStructure1\s+RussiaKashtan\b", side), "Kashtan AI regression")
    require(b"Object RussiaKashtan" in files["data/ini/object/russia/defences/kashtandefence.ini"],
            "Kashtan AI object missing")


def validate(root, baseline, report=None):
    source = baseline.read_bytes()
    require(hashlib.sha256(source).hexdigest() == SOURCE_SHA256, "baseline hash mismatch")
    before = payloads(source)
    shipped = (root / "!!ProjectXRe_INI.big").read_bytes()
    after = payloads(shipped)
    require([e.name for e in read_index(source)] == [e.name for e in read_index(shipped)],
            "archive entry names or ordering changed")
    require(set(before) == set(after) and len(after) == 622, "archive entry set changed")
    require({p for p in before if before[p] != after[p]} == CHANGED_PATHS,
            "unexpected payload changes")
    for target in APPENDS:
        require(after[target].startswith(before[target]), "existing definitions were edited/deleted")
    require(before[MISHKA].replace(b"RVMishka_U_D", b"RVMishka_UD") == after[MISHKA],
            "unexpected Mishka change")
    require(patch(source) == shipped, "shipped BIG differs from reproducible repair sources")
    manifest = json.loads((root / "tests/baseline_manifest.json").read_text())
    has_visuals = (root / 'visuals/v1/manifest.json').exists()
    has_destruction = (root / 'effects/v1/manifest.json').exists()
    expected_archives = set(manifest) | ({VISUAL_ARCHIVE} if has_visuals else set()) | ({DESTRUCTION_ARCHIVE} if has_destruction else set())
    require({f.name for f in root.glob("*.big")} == expected_archives, "missing or unexpected mod archive")
    archives, assets = [], set()
    for name, expected in manifest.items():
        with (root / name).open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            entries = read_index(data)
            digest = hashlib.sha256(data).hexdigest()
            require(len(entries) == expected["entries"], "entry count changed: " + name)
            if name != "!!ProjectXRe_INI.big":
                require(digest == expected["sha256"], "unrelated archive changed: " + name)
            if name == "!ProjectXRe_Art.big":
                assets = {e.key for e in entries}
            archives.append({"archive": name, "entries": len(entries), "sha256": digest})
    check_references(after, assets)
    visuals = validate_visuals(root) if has_visuals else None
    destruction = validate_destruction(root) if has_destruction else None
    result = {"archives": archives, "total_entries": sum(a["entries"] for a in archives),
              "changed_ini_entries": sorted(CHANGED_PATHS), "unchanged_ini_entries": 618,
              "baseline_sha256": SOURCE_SHA256,
              "validation": "static archive integrity, references and byte preservation; no game/device execution"}
    if visuals:
        result['visuals'] = visuals
        result['total_entries'] += len(visuals['textures'])
    if destruction:
        result['destruction'] = destruction
        result['total_entries'] += destruction['entries']
    if report:
        report.write_text(json.dumps(result, indent=2) + "\n")
    print("PASS: 9 base archives" + (" + visual overlay" if visuals else "") + (" + destruction overlay" if destruction else ""), "/", result["total_entries"], "entries; 618 INI payloads and 8 other BIGs unchanged")
    print("PASS: SVU controls/ability, both targeting templates, Ogre wreck, Mishka asset and Kashtan AI")
    print("PASS: shipped INI archive reproduced byte-for-byte from reviewed repair sources")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    validate(args.root, args.baseline, args.report)
