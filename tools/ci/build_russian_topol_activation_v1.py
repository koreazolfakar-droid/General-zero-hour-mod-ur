#!/usr/bin/env python3
"""Build a byte-minimal Topol/ICBM activation fix inside !!ProjectXRe_INI.big.

Edits are length-preserving so BIG offsets and archive size stay unchanged.
Only the INI entries containing the affected CommandSets/Upgrade may differ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, parse_big

BASELINE_SHA256 = "214a17c3d501ec756d82f375353e329dfe0e7e074dc9f5f9e2d42d8fbe6f5fe4"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(name: str) -> str:
    return name.replace("\\", "/").lower()


def decode_1to1(data: bytes) -> str:
    return data.decode("latin-1")


def encode_1to1(text: str) -> bytes:
    return text.encode("latin-1")


def find_block(text: str, kind: str, name: str) -> tuple[int, int, str]:
    start_re = re.compile(
        rf"(?mi)^(?P<indent>\s*){re.escape(kind)}\s+{re.escape(name)}\s*$"
    )
    hits = list(start_re.finditer(text))
    if len(hits) != 1:
        raise AuditError(f"Expected one {kind} {name}, found {len(hits)}")
    start = hits[0].start()
    tail = text[hits[0].end():]
    end_match = re.search(r"(?mi)^\s*End\s*$", tail)
    if not end_match:
        raise AuditError(f"Unterminated {kind} {name}")
    end = hits[0].end() + end_match.end()
    return start, end, text[start:end]


def replace_block(text: str, old_block: str, new_block: str) -> str:
    if len(old_block) != len(new_block):
        raise AuditError(
            f"Length-preserving patch violated: {len(old_block)} -> {len(new_block)}"
        )
    count = text.count(old_block)
    if count != 1:
        raise AuditError(f"Expected one exact block occurrence, found {count}")
    return text.replace(old_block, new_block, 1)


def activate_commented_button(block: str, button: str) -> tuple[str, dict]:
    lines = block.splitlines(keepends=True)
    matches = []
    for i, line in enumerate(lines):
        if button not in line:
            continue
        nonspace = len(line) - len(line.lstrip(" \t"))
        if nonspace < len(line) and line[nonspace] == ";":
            matches.append((i, nonspace))
    if len(matches) != 1:
        raise AuditError(
            f"Expected one commented {button} line, found {len(matches)}"
        )
    i, pos = matches[0]
    before = lines[i]
    chars = list(before)
    chars[pos] = " "
    after = "".join(chars)
    if len(before) != len(after):
        raise AuditError("Uncomment changed line length")
    lines[i] = after
    return "".join(lines), {"button": button, "before": before.rstrip(), "after": after.rstrip()}


def disable_active_button(block: str, button: str) -> tuple[str, dict]:
    lines = block.splitlines(keepends=True)
    matches = []
    for i, line in enumerate(lines):
        if button not in line:
            continue
        stripped = line.lstrip(" \t")
        if stripped.startswith(";"):
            continue
        if re.match(rf"^\d+\s*=\s*{re.escape(button)}\b", stripped):
            matches.append(i)
    if len(matches) != 1:
        raise AuditError(f"Expected one active {button} line, found {len(matches)}")
    i = matches[0]
    before = lines[i]
    leading = len(before) - len(before.lstrip(" \t"))
    if leading == 0:
        raise AuditError(
            f"Cannot length-preservingly comment {button}: no leading whitespace"
        )
    chars = list(before)
    chars[0] = ";"
    after = "".join(chars)
    if len(before) != len(after):
        raise AuditError("Commenting changed line length")
    lines[i] = after
    return "".join(lines), {"button": button, "before": before.rstrip(), "after": after.rstrip()}


def replace_numeric_field(
    block: str, field: str, expected: int | float, new_value: int | float
) -> tuple[str, dict]:
    pattern = re.compile(
        rf"(?mi)^(?P<prefix>\s*{re.escape(field)}\s*=\s*)"
        rf"(?P<value>{re.escape(str(expected))})(?P<suffix>\s*(?:;.*)?)$"
    )
    matches = list(pattern.finditer(block))
    if len(matches) != 1:
        raise AuditError(
            f"Expected one {field}={expected} field, found {len(matches)}"
        )
    rendered = str(new_value)
    if len(rendered) != len(str(expected)):
        raise AuditError(
            f"{field} replacement must preserve width: {expected} -> {new_value}"
        )
    m = matches[0]
    new_block = block[:m.start("value")] + rendered + block[m.end("value"):]
    if len(new_block) != len(block):
        raise AuditError(f"{field} replacement changed block length")
    return new_block, {
        "field": field,
        "before": str(expected),
        "after": rendered,
    }


def find_entry_containing(raw: bytes, entries, marker: str):
    hits = []
    marker_b = marker.encode("latin-1")
    for e in entries:
        if Path(e.name).suffix.lower() not in {".ini", ".inc"}:
            continue
        data = raw[e.offset:e.offset + e.size]
        if marker_b in data:
            hits.append(e)
    if len(hits) != 1:
        raise AuditError(f"Expected one entry containing {marker!r}, found {len(hits)}")
    return hits[0]


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
            raise AuditError("Source INI BIG does not match audited baseline")

        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        meta, entries, _ = parse_big(args.source)
        patched = bytearray(raw)
        changed_paths = set()
        edits = []

        science_name = spec["science_commandset"]
        purchase_button = spec["purchase_button"]
        marker = f"CommandSet {science_name}"
        e = find_entry_containing(raw, entries, marker)
        data = bytes(patched[e.offset:e.offset + e.size])
        text = decode_1to1(data)
        s, t, block = find_block(text, "CommandSet", science_name)
        new_block, edit = activate_commented_button(block, purchase_button)
        new_text = text[:s] + new_block + text[t:]
        new_data = encode_1to1(new_text)
        if len(new_data) != len(data):
            raise AuditError("Science CommandSet entry size changed")
        patched[e.offset:e.offset + e.size] = new_data
        changed_paths.add(norm(e.name))
        edit.update({"entry": e.name, "kind": "activate-science-button"})
        edits.append(edit)

        base_cs = spec["topol_base_commandset"]
        fire_button = spec["fire_button"]
        marker = f"CommandSet {base_cs}"
        e2 = find_entry_containing(bytes(patched), entries, marker)
        data = bytes(patched[e2.offset:e2.offset + e2.size])
        text = decode_1to1(data)
        s, t, block = find_block(text, "CommandSet", base_cs)
        new_block, edit = disable_active_button(block, fire_button)
        new_text = text[:s] + new_block + text[t:]
        new_data = encode_1to1(new_text)
        if len(new_data) != len(data):
            raise AuditError("Topol base CommandSet entry size changed")
        patched[e2.offset:e2.offset + e2.size] = new_data
        changed_paths.add(norm(e2.name))
        edit.update({"entry": e2.name, "kind": "hide-unarmed-fire-button"})
        edits.append(edit)

        upgrade = spec["rearm_upgrade"]
        marker = f"Upgrade {upgrade}"
        e3 = find_entry_containing(bytes(patched), entries, marker)
        data = bytes(patched[e3.offset:e3.offset + e3.size])
        text = decode_1to1(data)
        s, t, block = find_block(text, "Upgrade", upgrade)
        cost_expected = spec["rearm_build_cost"]["expected"]
        cost_re = re.compile(
            rf"(?mi)^\s*BuildCost\s*=\s*{re.escape(str(cost_expected))}\s*$"
        )
        if len(cost_re.findall(block)) != 1:
            raise AuditError(
                f"Expected BuildCost={cost_expected} exactly once in {upgrade}"
            )
        time_spec = spec["rearm_build_time"]
        new_block, edit = replace_numeric_field(
            block, "BuildTime", time_spec["from"], time_spec["to"]
        )
        new_text = text[:s] + new_block + text[t:]
        new_data = encode_1to1(new_text)
        if len(new_data) != len(data):
            raise AuditError("Upgrade entry size changed")
        patched[e3.offset:e3.offset + e3.size] = new_data
        changed_paths.add(norm(e3.name))
        edit.update({"entry": e3.name, "kind": "reduce-rearm-time"})
        edits.append(edit)

        if len(patched) != len(raw):
            raise AuditError("Whole BIG size changed")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(patched)
        parse_big(args.output)

        # Entry-by-entry byte identity check.
        changed = []
        unchanged = 0
        for ent in entries:
            before = raw[ent.offset:ent.offset + ent.size]
            after = bytes(patched[ent.offset:ent.offset + ent.size])
            if before == after:
                unchanged += 1
            else:
                changed.append(
                    {
                        "path": ent.name,
                        "old_sha256": sha(before),
                        "new_sha256": sha(after),
                        "size": ent.size,
                    }
                )

        actual_changed = {norm(x["path"]) for x in changed}
        if actual_changed != changed_paths:
            raise AuditError(
                f"Changed entry set mismatch. expected={sorted(changed_paths)}, "
                f"actual={sorted(actual_changed)}"
            )

        report = {
            "status": "ok",
            "baseline_sha256": sha(raw),
            "fixed_sha256": sha(bytes(patched)),
            "archive_size": len(raw),
            "entry_count": meta["entry_count"],
            "unchanged_entries": unchanged,
            "changed_entries": changed,
            "edits": edits,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        print(
            f"OK: Topol V1 built; {unchanged} entries byte-identical; "
            f"{len(changed)} entries changed; archive size unchanged"
        )
        print(f"FIXED_SHA256: {report['fixed_sha256']}")
        for item in edits:
            print("EDIT:", json.dumps(item, ensure_ascii=False))
        return 0

    except (AuditError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
