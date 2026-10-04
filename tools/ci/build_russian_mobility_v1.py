#!/usr/bin/env python3
"""Build a minimal Russian mobility V1 patch inside !!ProjectXRe_INI.big.

Only Data\INI\Locomotor.ini is modified. All other BIG entries are verified
byte-identical against the audited baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, parse_big

BASELINE_SHA256 = "214a17c3d501ec756d82f375353e329dfe0e7e074dc9f5f9e2d42d8fbe6f5fe4"


@dataclass
class Rec:
    name: str
    offset: int
    size: int
    pos: int


def norm(name: str) -> str:
    return name.replace("\\", "/").lower()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_index(raw: bytes) -> list[Rec]:
    if raw[:4] not in (b"BIGF", b"BIG4"):
        raise AuditError("invalid BIG magic")
    total = struct.unpack("<I", raw[4:8])[0]
    count = struct.unpack(">I", raw[8:12])[0]
    data_start = struct.unpack(">I", raw[12:16])[0]
    if total != len(raw):
        raise AuditError("BIG header size mismatch")

    pos = 16
    records = []
    for i in range(count):
        if pos + 8 > len(raw):
            raise AuditError(f"truncated BIG index at record {i}")
        rec_pos = pos
        off, size = struct.unpack(">II", raw[pos:pos + 8])
        pos += 8
        end = raw.find(b"\0", pos)
        if end < 0:
            raise AuditError(f"missing path terminator at record {i}")
        name = raw[pos:end].decode("latin-1")
        pos = end + 1
        records.append(Rec(name, off, size, rec_pos))

    if pos > data_start:
        raise AuditError("BIG index overlaps data")
    return records


def get_entry(raw: bytes, rec: Rec) -> bytes:
    end = rec.offset + rec.size
    if rec.offset < 0 or end > len(raw):
        raise AuditError(f"entry out of bounds: {rec.name}")
    return raw[rec.offset:end]


def find_record(records: list[Rec], name: str) -> Rec:
    hits = [r for r in records if norm(r.name) == norm(name)]
    if len(hits) != 1:
        raise AuditError(f"expected exactly one {name}, found {len(hits)}")
    return hits[0]


def find_locomotor_block(lines: list[str], name: str) -> tuple[int, int]:
    start_re = re.compile(rf"^Locomotor\s+{re.escape(name)}\s*$", re.I)
    starts = [i for i, line in enumerate(lines) if start_re.match(line.strip("\r\n"))]
    if len(starts) != 1:
        raise AuditError(f"expected exactly one Locomotor {name}, found {len(starts)}")
    start = starts[0]
    for i in range(start + 1, len(lines)):
        if re.match(r"^End\s*$", lines[i].strip("\r\n"), re.I):
            return start, i
    raise AuditError(f"unterminated Locomotor {name}")


def replace_numeric_field(
    lines: list[str],
    block_start: int,
    block_end: int,
    field: str,
    old_value: float,
    new_value: float,
) -> dict:
    pattern = re.compile(
        rf"^(?P<prefix>\s*{re.escape(field)}\s*=\s*)"
        r"(?P<value>[-+]?\d+(?:\.\d+)?)"
        r"(?P<suffix>\s*(?:;.*)?)(?P<eol>\r?\n?)$",
        re.I,
    )
    hits = []
    for i in range(block_start + 1, block_end):
        m = pattern.match(lines[i])
        if m:
            hits.append((i, m))
    if len(hits) != 1:
        raise AuditError(
            f"expected exactly one {field} in locomotor block, found {len(hits)}"
        )

    index, match = hits[0]
    actual = float(match.group("value"))
    if actual != float(old_value):
        raise AuditError(
            f"{field}: baseline changed; expected {old_value}, found {actual}"
        )

    if isinstance(new_value, int) or float(new_value).is_integer():
        rendered = str(int(new_value))
    else:
        rendered = str(new_value)

    lines[index] = (
        match.group("prefix")
        + rendered
        + match.group("suffix")
        + match.group("eol")
    )
    return {
        "field": field,
        "from": actual,
        "to": float(new_value),
        "line_index": index + 1,
    }


def patch_locomotors(text: str, changes: dict) -> tuple[str, list[dict]]:
    lines = text.splitlines(keepends=True)
    applied = []

    for locomotor, field_changes in changes.items():
        start, end = find_locomotor_block(lines, locomotor)
        for field, spec in field_changes.items():
            item = replace_numeric_field(
                lines,
                start,
                end,
                field,
                spec["from"],
                spec["to"],
            )
            item["locomotor"] = locomotor
            applied.append(item)

    return "".join(lines), applied


def rebuild_big(raw: bytes, records: list[Rec], target: Rec, replacement: bytes) -> bytes:
    old_end = target.offset + target.size
    delta = len(replacement) - target.size

    for rec in records:
        if rec is target:
            continue
        if rec.offset < old_end and rec.offset + rec.size > target.offset:
            raise AuditError(f"target overlaps another entry: {rec.name}")

    patched = bytearray(raw[:target.offset] + replacement + raw[old_end:])
    patched[4:8] = struct.pack("<I", len(patched))

    for rec in records:
        off = rec.offset
        size = rec.size
        if rec is target:
            size = len(replacement)
        elif rec.offset >= old_end:
            off += delta

        patched[rec.pos:rec.pos + 4] = struct.pack(">I", off)
        patched[rec.pos + 4:rec.pos + 8] = struct.pack(">I", size)

    return bytes(patched)


def validate_only_target_changed(
    before: bytes,
    after: bytes,
    before_records: list[Rec],
    after_records: list[Rec],
    target_path: str,
) -> list[dict]:
    old_map = {norm(r.name): r for r in before_records}
    new_map = {norm(r.name): r for r in after_records}
    if set(old_map) != set(new_map):
        raise AuditError("BIG path set changed after rebuild")

    changed = []
    for key in sorted(old_map):
        old = get_entry(before, old_map[key])
        new = get_entry(after, new_map[key])
        if old != new:
            changed.append(
                {
                    "path": old_map[key].name,
                    "old_size": len(old),
                    "new_size": len(new),
                    "old_sha256": sha(old),
                    "new_sha256": sha(new),
                }
            )

    if [norm(x["path"]) for x in changed] != [norm(target_path)]:
        raise AuditError(
            "unexpected BIG entries changed: "
            + ", ".join(x["path"] for x in changed)
        )
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    try:
        raw = args.source.read_bytes()
        if sha(raw) != BASELINE_SHA256:
            raise AuditError(
                "source !!ProjectXRe_INI.big does not match audited baseline"
            )

        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        target_path = spec["target_entry"]
        changes = spec["changes"]

        records = read_index(raw)
        target = find_record(records, target_path)
        old_entry = get_entry(raw, target)

        try:
            old_text = old_entry.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            old_text = old_entry.decode("latin-1")
            encoding = "latin-1"

        new_text, applied = patch_locomotors(old_text, changes)
        new_entry = new_text.encode(encoding)

        patched = rebuild_big(raw, records, target, new_entry)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(patched)

        parse_big(args.output)
        new_records = read_index(patched)
        changed_entries = validate_only_target_changed(
            raw, patched, records, new_records, target_path
        )

        # Verify every requested field ended at the requested value by re-parsing text.
        target_after = get_entry(patched, find_record(new_records, target_path))
        after_text = target_after.decode(encoding)
        after_lines = after_text.splitlines(keepends=True)
        verified = []
        for locomotor, field_changes in changes.items():
            start, end = find_locomotor_block(after_lines, locomotor)
            for field, spec_item in field_changes.items():
                pattern = re.compile(
                    rf"^\s*{re.escape(field)}\s*=\s*([-+]?\d+(?:\.\d+)?)",
                    re.I,
                )
                values = []
                for line in after_lines[start + 1:end]:
                    m = pattern.match(line)
                    if m:
                        values.append(float(m.group(1)))
                if values != [float(spec_item["to"])]:
                    raise AuditError(
                        f"verification failed for {locomotor}.{field}: {values}"
                    )
                verified.append(
                    {
                        "locomotor": locomotor,
                        "field": field,
                        "value": values[0],
                    }
                )

        report = {
            "status": "ok",
            "baseline_sha256": sha(raw),
            "fixed_sha256": sha(patched),
            "baseline_size": len(raw),
            "fixed_size": len(patched),
            "size_delta": len(patched) - len(raw),
            "entry_count": len(records),
            "changed_entries": changed_entries,
            "unchanged_entries": len(records) - len(changed_entries),
            "applied_changes": applied,
            "verified_values": verified,
        }

        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )

        print(
            f"OK: mobility V1 built; {report['unchanged_entries']} BIG entries "
            f"byte-identical; only {target_path} changed"
        )
        print(f"APPLIED_CHANGES: {len(applied)}")
        print(f"FIXED_SHA256: {report['fixed_sha256']}")
        return 0

    except (AuditError, OSError, ValueError, KeyError, struct.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
