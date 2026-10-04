#!/usr/bin/env python3
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
from russia_dependency_map import build_graph, parse_definitions

BASELINE_SHA = "214a17c3d501ec756d82f375353e329dfe0e7e074dc9f5f9e2d42d8fbe6f5fe4"
TARGET = "Data\\INI\\CommandSet.ini"
NEW_NAME = "RussianInfantrySVUSniperCommandSet"
OBJECT = "RussiaInfantrySVUSniper"
EXPECTED = {
    7: "Command_RussiaCallinGrizonAirdrop",
    15: "Command_AttackMove",
    17: "Command_Guard",
    18: "Command_Stop",
}


@dataclass
class Rec:
    name: str
    offset: int
    size: int
    pos: int


def norm(s: str) -> str:
    return s.replace("\\", "/").lower()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_index(raw: bytes):
    if raw[:4] not in (b"BIGF", b"BIG4"):
        raise AuditError("invalid BIG magic")
    total = struct.unpack("<I", raw[4:8])[0]
    count = struct.unpack(">I", raw[8:12])[0]
    data_start = struct.unpack(">I", raw[12:16])[0]
    if total != len(raw):
        raise AuditError("BIG header size mismatch")
    out = []
    pos = 16
    for _ in range(count):
        rec_pos = pos
        off, size = struct.unpack(">II", raw[pos:pos + 8])
        pos += 8
        end = raw.index(b"\0", pos)
        name = raw[pos:end].decode("latin-1")
        pos = end + 1
        out.append(Rec(name, off, size, rec_pos))
    if pos > data_start:
        raise AuditError("BIG index overlaps data")
    return out, data_start


def entry(raw: bytes, rec: Rec) -> bytes:
    return raw[rec.offset:rec.offset + rec.size]


def find(records, name: str) -> Rec:
    hits = [r for r in records if norm(r.name) == norm(name)]
    if len(hits) != 1:
        raise AuditError(f"expected one {name}, found {len(hits)}")
    return hits[0]


def parse_slots(text: str) -> dict[int, str]:
    import re
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--addition", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()

    try:
        raw = a.source.read_bytes()
        if sha(raw) != BASELINE_SHA:
            raise AuditError("source INI BIG does not match audited baseline")

        records, _ = read_index(raw)
        target = find(records, TARGET)
        old = entry(raw, target)
        old_text = old.decode("latin-1")
        if NEW_NAME in old_text:
            raise AuditError("target CommandSet already exists")

        addition = a.addition.read_text(encoding="utf-8").strip()
        if parse_slots(addition) != EXPECTED:
            raise AuditError("patch CommandSet does not match audited slot baseline")

        eol = "\r\n" if b"\r\n" in old else "\n"
        base = old_text
        if not base.endswith(("\n", "\r")):
            base += eol
        if not base.endswith(eol + eol):
            base += eol
        new = (base + addition.replace("\n", eol) + eol).encode("latin-1")
        delta = len(new) - len(old)
        old_end = target.offset + target.size

        for r in records:
            if r is target:
                continue
            if r.offset < old_end and r.offset + r.size > target.offset:
                raise AuditError("target entry overlaps another entry")

        patched = bytearray(raw[:target.offset] + new + raw[old_end:])
        patched[4:8] = struct.pack("<I", len(patched))

        for r in records:
            off, size = r.offset, r.size
            if r is target:
                size = len(new)
            elif r.offset >= old_end:
                off += delta
            patched[r.pos:r.pos + 4] = struct.pack(">I", off)
            patched[r.pos + 4:r.pos + 8] = struct.pack(">I", size)

        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_bytes(patched)
        parse_big(a.output)

        new_raw = a.output.read_bytes()
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
        if [norm(x["path"]) for x in changed] != [norm(TARGET)]:
            raise AuditError("more than CommandSet.ini changed")

        defs, _ = parse_definitions(a.output)
        by_name = {}
        for d in defs:
            by_name.setdefault(d.name, []).append(d)
        if len(by_name.get(NEW_NAME, [])) != 1:
            raise AuditError("new CommandSet is not defined exactly once")
        if parse_slots(by_name[NEW_NAME][0].body) != EXPECTED:
            raise AuditError("new CommandSet parsed with wrong slots")

        _, edges, unresolved = build_graph(defs)
        if not any(
            e.source == OBJECT and e.target == NEW_NAME and e.relation == "command-set"
            for e in edges
        ):
            raise AuditError("SVU CommandSet reference still does not resolve")
        if any(
            x["source"] == OBJECT and x["target"] == NEW_NAME
            for x in unresolved
        ):
            raise AuditError("SVU CommandSet remains unresolved")

        report = {
            "status": "ok",
            "baseline_sha256": sha(raw),
            "fixed_sha256": sha(new_raw),
            "baseline_size": len(raw),
            "fixed_size": len(new_raw),
            "size_delta": delta,
            "entry_count": len(records),
            "changed_entries": changed,
            "unchanged_entries": len(records) - len(changed),
            "commandset": NEW_NAME,
            "slots": {str(k): v for k, v in EXPECTED.items()},
        }
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        print(
            f"OK: {report['unchanged_entries']} entries byte-identical; "
            f"only {TARGET} changed; delta={delta} bytes"
        )
        print(f"FIXED_SHA256: {report['fixed_sha256']}")
        return 0
    except (AuditError, OSError, ValueError, struct.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
