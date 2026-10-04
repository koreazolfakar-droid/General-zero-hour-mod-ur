#!/usr/bin/env python3
"""Global integrity audit for Project X Re INI + English string archive.

This intentionally audits *all* definitions, including dormant/unreachable content,
so it complements the focused playable-faction dependency audits.

It does not modify gameplay data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, BigEntry, parse_big
from all_factions_audit import parse_extended
from russia_dependency_map import (
    Definition,
    field_values,
    read_entry_text,
    strip_comments,
    typed_reference_candidates,
)

SENTINELS = {
    "none", "null", "yes", "no", "true", "false", "0",
    "buttonimage", "not_applicable",
}

EXPECTED_KIND = {
    "build-object": "Object",
    "starting-building": "Object",
    "starting-unit": "Object",
    "projectile-object": "Object",
    "prerequisite-object": "Object",
    "command-set": "CommandSet",
    "command-button": "CommandButton",
    "science": "Science",
    "intrinsic-science": "Science",
    "prerequisite-science": "Science",
    "upgrade": "Upgrade",
    "triggered-by": "Upgrade",
    "conflicts-with": "Upgrade",
    "special-power": "SpecialPower",
    "weapon": "Weapon",
    "locomotor": "Locomotor",
    "armor": "Armor",
    "ocl": "ObjectCreationList",
    "fx": "FXList",
}

CONTROLBAR_RE = re.compile(r"\bCONTROLBAR:[A-Za-z0-9_]+\b")
MAPPED_IMAGE_DEF_RE = re.compile(
    r"(?m)^\s*MappedImage\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
)
BUTTON_IMAGE_FIELD_RE = re.compile(
    r"(?mi)^\s*ButtonImage\s*(?:=\s*)?([^\s;]+)"
)
STRING_KEY_LINE_RE = re.compile(
    r"(?m)^\s*([A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+)\s*$"
)
DUP_BLOCK_KINDS = {
    "CommandButton", "Locomotor", "FXList", "ObjectCreationList",
    "Weapon", "Armor", "Upgrade", "CommandSet", "SpecialPower",
    "ParticleSystem", "Science", "PlayerTemplate", "Object",
}

def normalize_body(body: str) -> str:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    # Preserve comments because duplicate blocks may intentionally differ there,
    # but remove trailing whitespace / blank tail noise.
    return "\n".join(line.rstrip() for line in text.strip().splitlines())

def read_all_text_entries(archive: Path) -> list[tuple[str, str]]:
    _meta, entries, _warnings = parse_big(archive)
    out = []
    for e in entries:
        suffix = Path(e.name).suffix.lower()
        if suffix not in {".ini", ".inc", ".str", ".txt"}:
            continue
        raw = archive.read_bytes()[e.offset:e.offset + e.size]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
        out.append((e.name, text))
    return out

def meaningful_ref(relation: str, target: str) -> bool:
    low = target.lower()
    if low in SENTINELS:
        return False
    if relation == "requires-trigger":
        return False
    if target.startswith("Upgrade_Veterancy_"):
        return False
    if "science" in relation and not target.startswith("SCIENCE_"):
        return False
    if relation in {"upgrade", "triggered-by", "conflicts-with"} and not target.startswith("Upgrade_"):
        return False
    if relation == "command-set" and "CommandSet" not in target:
        return False
    if relation == "command-button" and not target.startswith("Command_"):
        return False
    if relation == "ocl" and not target.startswith("OCL_"):
        return False
    return True

def build_expected_kind_symbols(ini_archives: list[Path]) -> dict[str, set[str]]:
    symbols: dict[str, set[str]] = defaultdict(set)

    patterns = {
        "Object": re.compile(
            r"(?m)^(?:Object|ChildObject|ObjectReskin)\s+"
            r"([A-Za-z_][A-Za-z0-9_]*)"
            r"(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*(?:;[^\r\n]*)?$"
        ),
        "CommandButton": re.compile(
            r"(?m)^CommandButton\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "CommandSet": re.compile(
            r"(?m)^CommandSet\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "Science": re.compile(
            r"(?m)^Science\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "Upgrade": re.compile(
            r"(?m)^Upgrade\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "Weapon": re.compile(
            r"(?m)^Weapon\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "Armor": re.compile(
            r"(?m)^Armor\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "Locomotor": re.compile(
            r"(?m)^Locomotor\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "SpecialPower": re.compile(
            r"(?m)^SpecialPower\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "ObjectCreationList": re.compile(
            r"(?m)^ObjectCreationList\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
        "FXList": re.compile(
            r"(?m)^FXList\s+([A-Za-z_][A-Za-z0-9_]*)\s*$"
        ),
    }

    for archive in ini_archives:
        for _path, text in read_all_text_entries(archive):
            for kind, pattern in patterns.items():
                symbols[kind].update(pattern.findall(text))
    return symbols


def all_global_unresolved(
    definitions: list[Definition],
    symbols_by_kind: dict[str, set[str]],
) -> list[dict]:

    rows = []
    seen = set()
    for d in definitions:
        for relation, target in typed_reference_candidates(d):
            if not meaningful_ref(relation, target):
                continue
            expected = EXPECTED_KIND.get(relation)
            if expected is None:
                continue
            if target in symbols_by_kind.get(expected, set()):
                continue
            key = (d.name, d.kind, d.path, relation, target)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "source": d.name,
                "source_kind": d.kind,
                "source_path": d.path,
                "source_line": d.start_line,
                "relation": relation,
                "target": target,
                "expected_kind": expected,
            })
    rows.sort(key=lambda x:(x["source_path"], x["source_line"], x["source"], x["relation"], x["target"]))
    return rows

def duplicate_groups(ini_archives: list[Path]) -> list[dict]:
    kinds = (
        "CommandButton", "Locomotor", "FXList", "ObjectCreationList",
        "CommandSet", "Weapon", "Armor", "Upgrade", "SpecialPower",
        "ParticleSystem",
    )
    groups = []

    for archive in ini_archives:
        for path, text in read_all_text_entries(archive):
            for kind in kinds:
                pattern = re.compile(
                    rf"(?m)^{re.escape(kind)}\s+"
                    r"([A-Za-z_][A-Za-z0-9_]*)\s*$"
                )
                rows: dict[str, list[tuple[int,str]]] = defaultdict(list)
                matches = list(pattern.finditer(text))
                for idx, m in enumerate(matches):
                    start = m.start()
                    end = matches[idx+1].start() if idx+1 < len(matches) else len(text)
                    # This body slice is used only to tell exact duplicates from
                    # differing same-file definitions; locations are authoritative.
                    body = normalize_body(text[start:end])
                    rows[m.group(1)].append(
                        (text.count("\n",0,start)+1, body)
                    )
                for name, defs in rows.items():
                    if len(defs) < 2:
                        continue
                    bodies=[b for _line,b in defs]
                    groups.append({
                        "kind":kind,
                        "name":name,
                        "count":len(defs),
                        "identical":len(set(bodies))==1,
                        "locations":[
                            {
                                "archive":archive.name,
                                "path":path,
                                "line":line,
                                "body_sha256":hashlib.sha256(
                                    body.encode("latin-1",errors="replace")
                                ).hexdigest(),
                            }
                            for line,body in defs
                        ],
                    })
    groups.sort(key=lambda x:(x["kind"],x["name"],x["locations"][0]["path"]))
    return groups

def mapped_image_audit(ini_archives: list[Path]) -> dict:
    definitions: dict[str, list[dict]] = defaultdict(list)
    refs: list[dict] = []

    for archive in ini_archives:
        for path, text in read_all_text_entries(archive):
            for m in MAPPED_IMAGE_DEF_RE.finditer(text):
                definitions[m.group(1)].append({
                    "archive": archive.name,
                    "path": path,
                    "line": text.count("\n", 0, m.start()) + 1,
                })
            for m in BUTTON_IMAGE_FIELD_RE.finditer(strip_comments(text)):
                value = m.group(1).strip()
                if value and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
                    refs.append({
                        "name": value,
                        "archive": archive.name,
                        "path": path,
                        "line": text.count("\n", 0, m.start()) + 1,
                    })

    missing = []
    for ref in refs:
        if ref["name"] not in definitions:
            missing.append(ref)

    dedup = {}
    for x in missing:
        dedup[(x["name"], x["path"], x["line"])] = x

    return {
        "mapped_image_definition_count": len(definitions),
        "button_image_ref_count": len(refs),
        "missing_button_image_refs": sorted(
            dedup.values(), key=lambda x:(x["name"], x["path"], x["line"])
        ),
        "duplicate_mapped_image_names": {
            k:v for k,v in definitions.items() if len(v)>1
        },
    }

def controlbar_audit(ini_archives: list[Path], eng_archive: Path) -> dict:
    refs: dict[str, list[dict]] = defaultdict(list)
    for archive in ini_archives:
        for path, text in read_all_text_entries(archive):
            clean = strip_comments(text)
            for m in CONTROLBAR_RE.finditer(clean):
                key = m.group(0)
                refs[key].append({
                    "archive": archive.name,
                    "path": path,
                    "line": clean.count("\n", 0, m.start()) + 1,
                })

    keys = set()
    eng_files = []

    string_archives = [*ini_archives, eng_archive]
    for string_archive in string_archives:
        for path, text in read_all_text_entries(string_archive):
            if Path(path).suffix.lower() != ".str":
                continue
            found = set(STRING_KEY_LINE_RE.findall(text))
            keys.update(found)
            eng_files.append({
                "archive": string_archive.name,
                "path": path,
                "keys": len(found),
            })

    missing = []
    for key in sorted(refs):
        if key not in keys:
            missing.append({
                "key": key,
                "references": refs[key],
            })

    return {
        "string_files": eng_files,
        "defined_string_key_count": len(keys),
        "controlbar_ref_key_count": len(refs),
        "missing_controlbar_keys": missing,
    }

def line_ending_audit(ini_archives: list[Path]) -> dict:
    stats = Counter()
    empty_files = []
    no_final_newline = []

    for archive in ini_archives:
        _meta, entries, _warnings = parse_big(archive)
        raw_all = archive.read_bytes()
        for e in entries:
            if Path(e.name).suffix.lower() not in {".ini", ".inc", ".str"}:
                continue
            raw = raw_all[e.offset:e.offset+e.size]
            if len(raw) == 0:
                empty_files.append({"archive":archive.name,"path":e.name})
                continue
            if b"\r\n" in raw:
                stats["CRLF_files"] += 1
            elif b"\n" in raw:
                stats["LF_files"] += 1
            else:
                stats["single_line_or_no_newline_files"] += 1
            if not raw.endswith((b"\n", b"\r")):
                no_final_newline.append({"archive":archive.name,"path":e.name})

    return {
        "line_ending_stats": dict(stats),
        "empty_files": empty_files,
        "no_final_newline_count": len(no_final_newline),
        "no_final_newline_sample": no_final_newline[:50],
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ini", nargs="+", type=Path, required=True)
    ap.add_argument("--eng", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        definitions = []
        archive_meta = []
        for archive in args.ini:
            defs, info = parse_extended(archive)
            definitions.extend(defs)
            archive_meta.append({
                "archive": archive.name,
                "definitions": len(defs),
                "warnings": info["warnings"],
            })

        symbols_by_kind = build_expected_kind_symbols(args.ini)
        unresolved = all_global_unresolved(definitions, symbols_by_kind)
        duplicates = duplicate_groups(args.ini)
        mapped = mapped_image_audit(args.ini)
        strings = controlbar_audit(args.ini, args.eng)
        endings = line_ending_audit(args.ini)

        summary = {
            "definitions": len(definitions),
            "unique_definition_names": len({d.name for d in definitions}),
            "global_typed_unresolved": len(unresolved),
            "duplicate_groups": len(duplicates),
            "conflicting_duplicate_groups": sum(not x["identical"] for x in duplicates),
            "identical_duplicate_groups": sum(x["identical"] for x in duplicates),
            "missing_controlbar_keys": len(strings["missing_controlbar_keys"]),
            "missing_button_image_refs": len(mapped["missing_button_image_refs"]),
            "empty_ini_files": len(endings["empty_files"]),
            "no_final_newline_count": endings["no_final_newline_count"],
        }

        report = {
            "status": "ok",
            "summary": summary,
            "global_typed_unresolved": unresolved,
            "duplicate_groups": duplicates,
            "controlbar": strings,
            "mapped_images": mapped,
            "line_endings": endings,
            "archives": archive_meta,
        }

        args.out.mkdir(parents=True, exist_ok=True)
        (args.out/"global-ini-integrity.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        lines = [
            "# Project X Re — Global INI Integrity Audit",
            "",
            "This audit checks dormant and active definitions globally, not only playable reachable paths.",
            "",
            "## Summary",
            "",
            f"- Definitions: **{summary['definitions']}**",
            f"- Global typed unresolved refs: **{summary['global_typed_unresolved']}**",
            f"- Duplicate definition groups: **{summary['duplicate_groups']}**",
            f"- Conflicting duplicate groups: **{summary['conflicting_duplicate_groups']}**",
            f"- Identical duplicate groups: **{summary['identical_duplicate_groups']}**",
            f"- Missing CONTROLBAR keys in Eng BIG: **{summary['missing_controlbar_keys']}**",
            f"- Missing mapped button-image refs in INI mapped-image definitions: **{summary['missing_button_image_refs']}**",
            f"- Empty INI/INC/STR files: **{summary['empty_ini_files']}**",
            f"- Files without final newline: **{summary['no_final_newline_count']}**",
            "",
            "## Global typed unresolved references",
            "",
            "| Relation | Source | Missing target | Source |",
            "|---|---|---|---|",
        ]
        for x in unresolved:
            lines.append(
                f"| {x['relation']} | {x['source']} | {x['target']} | "
                f"{x['source_path']}:{x['source_line']} |"
            )

        lines += ["", "## Duplicate definitions", ""]
        for x in duplicates:
            label = "IDENTICAL" if x["identical"] else "CONFLICTING"
            locs = ", ".join(
                f"{p['path']}:{p['line']}" for p in x["locations"]
            )
            lines.append(
                f"- **{label}** {x['kind']} {x['name']} x{x['count']} — {locs}"
            )

        lines += ["", "## Missing CONTROLBAR keys", ""]
        for x in strings["missing_controlbar_keys"]:
            first = x["references"][0]
            lines.append(
                f"- {x['key']} — first ref {first['path']}:{first['line']}"
            )

        lines += ["", "## Missing button images", ""]
        for x in mapped["missing_button_image_refs"]:
            lines.append(
                f"- {x['name']} — {x['path']}:{x['line']}"
            )

        lines += ["", "## Empty files", ""]
        for x in endings["empty_files"]:
            lines.append(f"- {x['archive']} :: {x['path']}")

        (args.out/"global-ini-integrity.md").write_text(
            "\n".join(lines)+"\n", encoding="utf-8"
        )

        print(
            "OK: global INI integrity audit: "
            f"{summary['global_typed_unresolved']} unresolved, "
            f"{summary['duplicate_groups']} duplicate groups "
            f"({summary['conflicting_duplicate_groups']} conflicting), "
            f"{summary['missing_controlbar_keys']} missing CONTROLBAR keys, "
            f"{summary['missing_button_image_refs']} missing button-image refs"
        )
        for x in unresolved:
            print(
                "UNRESOLVED:",
                x["relation"], x["source"], "->", x["target"],
                f"@{x['source_path']}:{x['source_line']}"
            )
        for x in duplicates:
            print(
                "DUPLICATE:",
                "CONFLICTING" if not x["identical"] else "IDENTICAL",
                x["kind"], x["name"], f"x{x['count']}"
            )
        for x in strings["missing_controlbar_keys"][:250]:
            print("MISSING_CONTROLBAR:", x["key"])
        for x in mapped["missing_button_image_refs"][:100]:
            print(
                "MISSING_BUTTON_IMAGE:",
                x["name"], f"@{x['path']}:{x['line']}"
            )
        return 0

    except (AuditError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
