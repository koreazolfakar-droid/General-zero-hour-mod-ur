#!/usr/bin/env python3
"""Build Russian Fix Pack V1 from the audited baseline INI BIG.

Integrated fixes:
- Mobility V1 + Heavy Launchers Speed V2
- Russian SVU sniper CommandSet
- Topol/ICBM activation flow
- Topol persistent map-darkening shadow fix

The script verifies the source SHA, applies only audited edits, rebuilds the BIG
once, and then performs entry-by-entry byte identity checks.
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

LOCOMOTOR_PATH = "Data\\INI\\Locomotor.ini"
COMMANDSET_PATH = "Data\\INI\\CommandSet.ini"
UPGRADE_PATH = "Data\\INI\\Upgrade.ini"
RUSSIA_SYSTEM_PATH = "Data\\INI\\Object\\Russia\\RussiaSystemObjects.ini"

SVU_NAME = "RussianInfantrySVUSniperCommandSet"
SVU_EXPECTED = {
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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(name: str) -> str:
    return name.replace("\\", "/").lower()


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


def find_rec(records: list[Rec], path: str) -> Rec:
    hits = [r for r in records if norm(r.name) == norm(path)]
    if len(hits) != 1:
        raise AuditError(f"expected one {path}, found {len(hits)}")
    return hits[0]


def entry(raw: bytes | bytearray, rec: Rec) -> bytes:
    return bytes(raw[rec.offset:rec.offset + rec.size])


def replace_entry_same_size(
    raw: bytearray, rec: Rec, before: bytes, after: bytes, label: str
) -> None:
    if len(before) != rec.size:
        raise AuditError(f"{label}: source entry size mismatch")
    if len(after) != len(before):
        raise AuditError(f"{label}: expected length-preserving entry edit")
    raw[rec.offset:rec.offset + rec.size] = after


def find_block(text: str, kind: str, name: str) -> tuple[int, int, str]:
    start_re = re.compile(
        rf"(?mi)^\s*{re.escape(kind)}\s+{re.escape(name)}(?:\s*;[^\r\n]*)?\s*$"
    )
    hits = list(start_re.finditer(text))
    if len(hits) != 1:
        raise AuditError(f"expected one {kind} {name}, found {len(hits)}")
    start = hits[0].start()
    tail = text[hits[0].end():]
    end_m = re.search(r"(?mi)^End\s*$", tail)
    if not end_m:
        raise AuditError(f"unterminated {kind} {name}")
    end = hits[0].end() + end_m.end()
    return start, end, text[start:end]


def replace_block(text: str, start: int, end: int, block: str) -> str:
    return text[:start] + block + text[end:]


def replace_numeric_field(
    block: str, field: str, old_value: str | int | float, new_value: str | int | float
) -> tuple[str, dict]:
    old = str(old_value)
    new = str(new_value)
    pattern = re.compile(
        rf"(?mi)^(?P<prefix>\s*{re.escape(field)}\s*=\s*)"
        rf"(?P<value>{re.escape(old)})(?P<suffix>\s*(?:;.*)?)$"
    )
    hits = list(pattern.finditer(block))
    if len(hits) != 1:
        raise AuditError(
            f"expected one {field}={old} in target block, found {len(hits)}"
        )
    if len(new) > len(old):
        raise AuditError(
            f"numeric edit would grow field width: {field} {old}->{new}"
        )
    rendered = new.ljust(len(old))
    m = hits[0]
    patched = block[:m.start("value")] + rendered + block[m.end("value"):]
    if len(patched) != len(block):
        raise AuditError(f"{field}: block length changed")
    return patched, {"field": field, "from": old, "to": new}


def parse_slots(text: str) -> dict[int, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def patch_mobility(text: str, changes: dict) -> tuple[str, list[dict]]:
    edits = []
    for locomotor, field_changes in changes.items():
        s, e, block = find_block(text, "Locomotor", locomotor)
        for field, spec in field_changes.items():
            block, edit = replace_numeric_field(
                block, field, spec["from"], spec["to"]
            )
            edit.update({"locomotor": locomotor, "kind": "mobility"})
            edits.append(edit)
        text = replace_block(text, s, e, block)
    return text, edits


def uncomment_button(block: str, button: str) -> tuple[str, dict]:
    lines = block.splitlines(keepends=True)
    matches = []
    for i, line in enumerate(lines):
        if button not in line:
            continue
        stripped = line.lstrip(" \t")
        if stripped.startswith(";"):
            pos = len(line) - len(stripped)
            matches.append((i, pos))
    if len(matches) != 1:
        raise AuditError(f"expected one commented {button}, found {len(matches)}")
    i, pos = matches[0]
    before = lines[i]
    chars = list(before)
    chars[pos] = " "
    after = "".join(chars)
    if len(after) != len(before):
        raise AuditError("uncomment changed line length")
    lines[i] = after
    return "".join(lines), {
        "kind": "activate-science-button",
        "button": button,
        "before": before.rstrip(),
        "after": after.rstrip(),
    }


def comment_active_button(block: str, button: str) -> tuple[str, dict]:
    lines = block.splitlines(keepends=True)
    hits = []
    for i, line in enumerate(lines):
        stripped = line.lstrip(" \t")
        if stripped.startswith(";"):
            continue
        if re.match(rf"^\d+\s*=\s*{re.escape(button)}\b", stripped):
            hits.append(i)
    if len(hits) != 1:
        raise AuditError(f"expected one active {button}, found {len(hits)}")
    i = hits[0]
    before = lines[i]
    if not before or before[0] not in " \t":
        raise AuditError(f"cannot length-preservingly comment {button}")
    after = ";" + before[1:]
    if len(after) != len(before):
        raise AuditError("comment changed line length")
    lines[i] = after
    return "".join(lines), {
        "kind": "hide-unarmed-fire-button",
        "button": button,
        "before": before.rstrip(),
        "after": after.rstrip(),
    }


def patch_topol_commandsets(text: str, spec: dict) -> tuple[str, list[dict]]:
    edits = []

    s, e, block = find_block(text, "CommandSet", spec["science_commandset"])
    block, edit = uncomment_button(block, spec["purchase_button"])
    edits.append(edit)
    text = replace_block(text, s, e, block)

    s, e, block = find_block(text, "CommandSet", spec["topol_base_commandset"])
    block, edit = comment_active_button(block, spec["fire_button"])
    edits.append(edit)
    text = replace_block(text, s, e, block)

    return text, edits


def append_svu(text: str, addition: str) -> tuple[str, dict]:
    if SVU_NAME in text:
        raise AuditError(f"{SVU_NAME} already exists before integration")
    if parse_slots(addition) != SVU_EXPECTED:
        raise AuditError("SVU addition slots do not match audited baseline")
    eol = "\r\n" if "\r\n" in text else "\n"
    base = text
    if not base.endswith(("\n", "\r")):
        base += eol
    if not base.endswith(eol + eol):
        base += eol
    appended = addition.strip().replace("\n", eol) + eol
    return base + appended, {
        "kind": "restore-svu-commandset",
        "commandset": SVU_NAME,
        "slots": {str(k): v for k, v in SVU_EXPECTED.items()},
        "delta": len((base + appended).encode("latin-1")) - len(text.encode("latin-1")),
    }


def patch_upgrade(text: str, spec: dict) -> tuple[str, list[dict]]:
    s, e, block = find_block(text, "Upgrade", spec["rearm_upgrade"])

    cost_re = re.compile(
        rf"(?mi)^\s*BuildCost\s*=\s*{re.escape(str(spec['rearm_build_cost']))}\s*$"
    )
    if len(cost_re.findall(block)) != 1:
        raise AuditError("Topol rearm BuildCost baseline mismatch")

    t = spec["rearm_build_time"]
    block, edit = replace_numeric_field(block, "BuildTime", t["from"], t["to"])
    edit.update({"kind": "reduce-topol-rearm-time", "upgrade": spec["rearm_upgrade"]})
    text = replace_block(text, s, e, block)
    return text, [edit]


def comment_shadow_in_object(block: str, object_name: str) -> tuple[str, dict]:
    lines = block.splitlines(keepends=True)
    hits = []
    for i, line in enumerate(lines):
        stripped = line.lstrip(" \t")
        if stripped.startswith(";"):
            continue
        if re.match(r"^Shadow\s*=\s*SHADOW_VOLUME\b", stripped, re.I):
            hits.append(i)
    if len(hits) != 1:
        raise AuditError(
            f"{object_name}: expected one active SHADOW_VOLUME, found {len(hits)}"
        )
    i = hits[0]
    before = lines[i]
    if not before or before[0] not in " \t":
        raise AuditError(f"{object_name}: no leading whitespace to replace with comment")
    after = ";" + before[1:]
    if len(after) != len(before):
        raise AuditError(f"{object_name}: shadow comment changed line length")
    lines[i] = after
    return "".join(lines), {
        "kind": "disable-giant-shadow-volume",
        "object": object_name,
        "before": before.rstrip(),
        "after": after.rstrip(),
    }


def patch_darkening(text: str, objects: list[str]) -> tuple[str, list[dict]]:
    edits = []
    for object_name in objects:
        s, e, block = find_block(text, "Object", object_name)

        # Guard against accidental edits to some similarly named helper.
        for field, expected in (
            ("GeometryMajorRadius", "800.0"),
            ("GeometryMinorRadius", "800.0"),
        ):
            if not re.search(
                rf"(?mi)^\s*{field}\s*=\s*{re.escape(expected)}\s*$", block
            ):
                raise AuditError(f"{object_name}: expected {field}={expected}")

        block, edit = comment_shadow_in_object(block, object_name)
        edits.append(edit)
        text = replace_block(text, s, e, block)
    return text, edits


def rebuild_with_resized_commandset(
    raw: bytes, records: list[Rec], patched_same_size: bytearray,
    command_rec: Rec, new_command_data: bytes
) -> bytes:
    old_end = command_rec.offset + command_rec.size
    delta = len(new_command_data) - command_rec.size
    if delta <= 0:
        raise AuditError("SVU integration did not grow CommandSet.ini")

    rebuilt = bytearray(
        patched_same_size[:command_rec.offset]
        + new_command_data
        + patched_same_size[old_end:]
    )
    rebuilt[4:8] = struct.pack("<I", len(rebuilt))

    for rec in records:
        off = rec.offset
        size = rec.size
        if rec is command_rec:
            size = len(new_command_data)
        elif rec.offset >= old_end:
            off += delta
        rebuilt[rec.pos:rec.pos + 4] = struct.pack(">I", off)
        rebuilt[rec.pos + 4:rec.pos + 8] = struct.pack(">I", size)

    return bytes(rebuilt)


def changed_entries(before: bytes, after: bytes) -> list[dict]:
    old_records = read_index(before)
    new_records = read_index(after)
    old_map = {norm(r.name): r for r in old_records}
    new_map = {norm(r.name): r for r in new_records}
    if set(old_map) != set(new_map):
        raise AuditError("archive path set changed")

    changed = []
    for key in sorted(old_map):
        b = entry(before, old_map[key])
        a = entry(after, new_map[key])
        if b != a:
            changed.append({
                "path": old_map[key].name,
                "old_size": len(b),
                "new_size": len(a),
                "old_sha256": sha(b),
                "new_sha256": sha(a),
            })
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--mobility-spec", type=Path, required=True)
    ap.add_argument("--svu-addition", type=Path, required=True)
    ap.add_argument("--topol-spec", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    try:
        raw = args.source.read_bytes()
        if sha(raw) != BASELINE_SHA256:
            raise AuditError("source !!ProjectXRe_INI.big does not match audited baseline")

        records = read_index(raw)
        patched = bytearray(raw)
        edits = []

        mobility_spec = json.loads(args.mobility_spec.read_text(encoding="utf-8"))
        topol_spec = json.loads(args.topol_spec.read_text(encoding="utf-8"))
        svu_addition = args.svu_addition.read_text(encoding="utf-8").strip()

        # 1) Mobility V1 + Heavy Launchers Speed V2
        loc_rec = find_rec(records, LOCOMOTOR_PATH)
        loc_old = entry(patched, loc_rec)
        loc_text = loc_old.decode("latin-1")
        loc_text, loc_edits = patch_mobility(loc_text, mobility_spec["changes"])
        loc_new = loc_text.encode("latin-1")
        replace_entry_same_size(patched, loc_rec, loc_old, loc_new, "Locomotor.ini")
        edits.extend(loc_edits)

        # 2) Topol activation changes inside CommandSet.ini (length preserving)
        cmd_rec = find_rec(records, COMMANDSET_PATH)
        cmd_old = entry(patched, cmd_rec)
        cmd_text = cmd_old.decode("latin-1")
        cmd_text, cmd_edits = patch_topol_commandsets(cmd_text, topol_spec)
        edits.extend(cmd_edits)

        # 3) Topol rearm time
        up_rec = find_rec(records, UPGRADE_PATH)
        up_old = entry(patched, up_rec)
        up_text = up_old.decode("latin-1")
        up_text, up_edits = patch_upgrade(up_text, topol_spec)
        up_new = up_text.encode("latin-1")
        replace_entry_same_size(patched, up_rec, up_old, up_new, "Upgrade.ini")
        edits.extend(up_edits)

        # 4) Remove the two giant shadow volumes that darken the map
        sys_rec = find_rec(records, RUSSIA_SYSTEM_PATH)
        sys_old = entry(patched, sys_rec)
        sys_text = sys_old.decode("latin-1")
        sys_text, shadow_edits = patch_darkening(
            sys_text, topol_spec["shadow_objects"]
        )
        sys_new = sys_text.encode("latin-1")
        replace_entry_same_size(
            patched, sys_rec, sys_old, sys_new, "RussiaSystemObjects.ini"
        )
        edits.extend(shadow_edits)

        # 5) Append the missing SVU CommandSet, then rebuild offsets once.
        cmd_text, svu_edit = append_svu(cmd_text, svu_addition)
        edits.append(svu_edit)
        cmd_new = cmd_text.encode("latin-1")

        rebuilt = rebuild_with_resized_commandset(
            raw, records, patched, cmd_rec, cmd_new
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(rebuilt)
        parse_big(args.output)

        changed = changed_entries(raw, rebuilt)
        expected_paths = {
            norm(LOCOMOTOR_PATH),
            norm(COMMANDSET_PATH),
            norm(UPGRADE_PATH),
            norm(RUSSIA_SYSTEM_PATH),
        }
        actual_paths = {norm(x["path"]) for x in changed}
        if actual_paths != expected_paths:
            raise AuditError(
                "unexpected changed BIG entries: "
                f"expected={sorted(expected_paths)} actual={sorted(actual_paths)}"
            )

        report = {
            "status": "ok",
            "baseline_sha256": sha(raw),
            "fixed_sha256": sha(rebuilt),
            "baseline_size": len(raw),
            "fixed_size": len(rebuilt),
            "size_delta": len(rebuilt) - len(raw),
            "entry_count": len(records),
            "changed_entries": changed,
            "unchanged_entries": len(records) - len(changed),
            "edit_count": len(edits),
            "edits": edits,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        print(
            "OK: Russian Fix Pack V1 built; "
            f"{report['unchanged_entries']} entries byte-identical; "
            f"{len(changed)} entries changed; delta={report['size_delta']} bytes"
        )
        print(f"FIXED_SHA256: {report['fixed_sha256']}")
        print(f"EDIT_COUNT: {report['edit_count']}")
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
