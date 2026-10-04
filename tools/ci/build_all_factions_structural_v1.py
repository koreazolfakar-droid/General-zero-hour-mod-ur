#!/usr/bin/env python3
"""Build additive America/China/GLA structural fixes on top of Russian Fix Pack V1."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, parse_big

INPUT_SHA256 = "4c719bbb869c16b1007991e8862168ba34c3bde684316dfe63ef616a1258d6dc"
COMMANDSET_PATH = "Data\\INI\\CommandSet.ini"
OCL_PATH = "Data\\INI\\ObjectCreationList.ini"

EXPECTED_COMMANDSETS = {
    "ChinaBarracksChinaProtocolCommandSet",
    "ChinaWarFactoryChinaProtocolCommandSet",
    "ChinaTankNukeOverlordCommandSet_Speaker",
    "ChinaTankNukeOverlordCommandSet_Upgraded",
    "GLAVehicleKraitCommandSet",
}

EXPECTED_OCLS = {
    "OCL_LibraTankDeathEffectSimple",
    "OCL_ToxicInfantryGamma",
    "OCL_ChinaQuadFangDebris",
    "OCL_ChinaTankEmperorDeathEffectSimple",
    "OCL_ChinaTankEmperorDebris",
    "OCL_ChinaTankSuperOverlordDebris",
    "OCL_ChinaTankWarMasterDebris",
    "OCL_SiegeCannonDeathEffect",
    "OCL_FinalSTroopCrawlerDeathEffectSimple",
    "OCL_FinalSTroopCrawlerDebris",
    "OCL_GLABasiliskExplode",
    "OCL_CombatBuggyDeath_Rebel",
    "OCL_CombatBuggyDeath_FlashTrooper",
    "OCL_CombatBuggyDeath_Jarmen",
    "OCL_CombatBuggyDeath_Grenadier",
    "OCL_ToxinTractorPoisonField",
    "OCL_NukebombTruckDebris",
}

@dataclass
class Rec:
    name: str
    offset: int
    size: int
    pos: int

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def norm(name: str) -> str:
    return name.replace("\\", "/").lower()

def read_index(raw: bytes) -> tuple[list[Rec], int]:
    if raw[:4] not in (b"BIGF", b"BIG4"):
        raise AuditError("invalid BIG magic")
    total = struct.unpack("<I", raw[4:8])[0]
    count = struct.unpack(">I", raw[8:12])[0]
    data_start = struct.unpack(">I", raw[12:16])[0]
    if total != len(raw):
        raise AuditError("BIG header size mismatch")

    pos = 16
    records = []
    for _ in range(count):
        rec_pos = pos
        off, size = struct.unpack(">II", raw[pos:pos + 8])
        pos += 8
        end = raw.index(b"\0", pos)
        name = raw[pos:end].decode("latin-1")
        pos = end + 1
        records.append(Rec(name, off, size, rec_pos))
    if pos > data_start:
        raise AuditError("BIG index overlaps data")
    return records, data_start

def find(records: list[Rec], path: str) -> Rec:
    hits = [r for r in records if norm(r.name) == norm(path)]
    if len(hits) != 1:
        raise AuditError(f"expected one {path}, found {len(hits)}")
    return hits[0]

def entry(raw: bytes, rec: Rec) -> bytes:
    return raw[rec.offset:rec.offset + rec.size]

def names_from_addition(text: str, kind: str) -> set[str]:
    import re
    return set(re.findall(
        rf"(?m)^\s*{kind}\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
        text
    ))

def append_text(old: bytes, addition: str, forbidden_names: set[str]) -> bytes:
    old_text = old.decode("latin-1")
    for name in forbidden_names:
        if name in old_text:
            raise AuditError(f"definition already exists before patch: {name}")

    eol = "\r\n" if b"\r\n" in old else "\n"
    base = old_text
    if not base.endswith(("\n", "\r")):
        base += eol
    if not base.endswith(eol + eol):
        base += eol
    return (base + addition.strip().replace("\n", eol) + eol).encode("latin-1")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--commandsets", type=Path, required=True)
    ap.add_argument("--ocls", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    try:
        raw = args.source.read_bytes()
        if sha(raw) != INPUT_SHA256:
            raise AuditError(
                "source does not match validated Russian Fix Pack V1 integration"
            )

        records, _data_start = read_index(raw)
        cmd_rec = find(records, COMMANDSET_PATH)
        ocl_rec = find(records, OCL_PATH)

        cmd_add = args.commandsets.read_text(encoding="utf-8")
        ocl_add = args.ocls.read_text(encoding="utf-8")

        cmd_names = names_from_addition(cmd_add, "CommandSet")
        ocl_names = names_from_addition(ocl_add, "ObjectCreationList")
        if cmd_names != EXPECTED_COMMANDSETS:
            raise AuditError(
                f"CommandSet addition mismatch: {sorted(cmd_names)}"
            )
        if ocl_names != EXPECTED_OCLS:
            raise AuditError(
                f"OCL addition mismatch: {sorted(ocl_names)}"
            )

        cmd_new = append_text(entry(raw, cmd_rec), cmd_add, EXPECTED_COMMANDSETS)
        ocl_new = append_text(entry(raw, ocl_rec), ocl_add, EXPECTED_OCLS)

        replacements = {
            norm(COMMANDSET_PATH): cmd_new,
            norm(OCL_PATH): ocl_new,
        }

        # Replace data in descending offset order so original offsets stay valid
        # during splicing. Then rewrite every BIG record offset/size once.
        patched = bytearray(raw)
        target_records = sorted(
            [cmd_rec, ocl_rec], key=lambda r: r.offset, reverse=True
        )
        for rec in target_records:
            new_data = replacements[norm(rec.name)]
            patched[rec.offset:rec.offset + rec.size] = new_data

        deltas = {
            norm(cmd_rec.name): len(cmd_new) - cmd_rec.size,
            norm(ocl_rec.name): len(ocl_new) - ocl_rec.size,
        }

        patched[4:8] = struct.pack("<I", len(patched))

        for rec in records:
            delta_before = sum(
                delta
                for target, delta in ((cmd_rec, deltas[norm(cmd_rec.name)]),
                                      (ocl_rec, deltas[norm(ocl_rec.name)]))
                if target.offset < rec.offset
            )
            new_off = rec.offset + delta_before
            new_size = replacements[norm(rec.name)].__len__() if norm(rec.name) in replacements else rec.size
            patched[rec.pos:rec.pos + 4] = struct.pack(">I", new_off)
            patched[rec.pos + 4:rec.pos + 8] = struct.pack(">I", new_size)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(patched)
        parse_big(args.output)

        new_raw = args.output.read_bytes()
        new_records, _ = read_index(new_raw)
        old_map = {norm(r.name): r for r in records}
        new_map = {norm(r.name): r for r in new_records}
        if set(old_map) != set(new_map):
            raise AuditError("archive path set changed")

        changed = []
        for key in sorted(old_map):
            before = entry(raw, old_map[key])
            after = entry(new_raw, new_map[key])
            if before != after:
                changed.append({
                    "path": old_map[key].name,
                    "old_size": len(before),
                    "new_size": len(after),
                    "old_sha256": sha(before),
                    "new_sha256": sha(after),
                })

        expected_changed = {norm(COMMANDSET_PATH), norm(OCL_PATH)}
        actual_changed = {norm(x["path"]) for x in changed}
        if actual_changed != expected_changed:
            raise AuditError(
                f"unexpected changed entries: {sorted(actual_changed)}"
            )

        report = {
            "status": "ok",
            "input_sha256": sha(raw),
            "fixed_sha256": sha(new_raw),
            "input_size": len(raw),
            "fixed_size": len(new_raw),
            "size_delta": len(new_raw) - len(raw),
            "entry_count": len(records),
            "unchanged_entries": len(records) - len(changed),
            "changed_entries": changed,
            "added_commandsets": sorted(cmd_names),
            "added_ocls": sorted(ocl_names),
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        print(
            "OK: All Factions Structural V1 built; "
            f"{report['unchanged_entries']} entries byte-identical; "
            f"{len(changed)} entries changed; delta={report['size_delta']} bytes"
        )
        print(f"FIXED_SHA256: {report['fixed_sha256']}")
        for item in changed:
            print(
                "CHANGED_ENTRY:",
                item["path"],
                f"{item['old_size']}->{item['new_size']}",
            )
        return 0

    except (AuditError, OSError, ValueError, KeyError, struct.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
