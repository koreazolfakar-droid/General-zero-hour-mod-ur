#!/usr/bin/env python3
"""Read-only CI audit for the Project X Re baseline.

The script has two modes:
  pointers  - verify that the original BIG archives are represented by valid
              Git LFS pointers and still match the imported baseline sizes.
  big       - validate selected materialized EA BIGF/BIG4 archives and produce
              a machine-readable + Markdown inventory without modifying them.

No archive is repacked or changed by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

BASELINE = {
    "!!ProjectXRe_INI.big": 27_160_453,
    "!ProjectXRe_Art.big": 1_247_954_717,
    "!ProjectXRe_Audio.big": 906_503_106,
    "!ProjectXRe_CloseINI.big": 3_924,
    "!ProjectXRe_Eng.big": 795_953,
    "!ProjectXRe_Maps.big": 72_493_744,
    "!ProjectXRe_Music.big": 393_978_629,
    "!ProjectXRe_Voice.big": 77_145_052,
    "!ProjectXRe_Window.big": 8_307_913,
}

LFS_RE = re.compile(
    r"\Aversion https://git-lfs\.github\.com/spec/v1\n"
    r"oid sha256:([0-9a-f]{64})\n"
    r"size ([0-9]+)\n?\Z"
)

TEXT_EXTENSIONS = {
    ".ini", ".inc", ".txt", ".str", ".wnd", ".csf", ".map", ".cfg", ".xml"
}
RUSSIA_RE = re.compile(rb"(?i)\b(russia|russian|soviet)\b")


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class BigEntry:
    offset: int
    size: int
    name: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def human_size(size: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def read_c_string(handle, *, max_len: int = 260) -> str:
    buf = bytearray()
    while len(buf) <= max_len:
        byte = handle.read(1)
        if not byte:
            raise AuditError("Unexpected EOF while reading BIG entry name")
        if byte == b"\x00":
            try:
                return buf.decode("utf-8")
            except UnicodeDecodeError:
                return buf.decode("latin-1")
        buf.extend(byte)
    raise AuditError(f"BIG entry name exceeds {max_len} bytes")


def normalize_archive_name(name: str) -> str:
    return name.replace("\\", "/").lstrip("./").lower()


def parse_big(path: Path) -> tuple[dict, list[BigEntry], list[str]]:
    actual_size = path.stat().st_size
    warnings: list[str] = []

    with path.open("rb") as handle:
        header = handle.read(16)
        if len(header) != 16:
            raise AuditError(f"{path.name}: file is too short for a BIG header")

        magic = header[0:4]
        if magic not in (b"BIGF", b"BIG4"):
            raise AuditError(
                f"{path.name}: invalid BIG magic {magic!r}; expected BIGF or BIG4"
            )

        archive_size = struct.unpack("<I", header[4:8])[0]
        entry_count = struct.unpack(">I", header[8:12])[0]
        data_start = struct.unpack(">I", header[12:16])[0]

        if archive_size != actual_size:
            raise AuditError(
                f"{path.name}: header size {archive_size} != actual size {actual_size}"
            )
        if entry_count > 1_000_000:
            raise AuditError(f"{path.name}: unreasonable entry count {entry_count}")
        if not 16 <= data_start <= actual_size:
            raise AuditError(
                f"{path.name}: invalid data_start {data_start} for size {actual_size}"
            )

        entries: list[BigEntry] = []
        for index in range(entry_count):
            fixed = handle.read(8)
            if len(fixed) != 8:
                raise AuditError(
                    f"{path.name}: truncated index at entry {index}/{entry_count}"
                )
            offset, size = struct.unpack(">II", fixed)
            name = read_c_string(handle)

            if not name:
                raise AuditError(f"{path.name}: empty entry name at index {index}")
            if name.startswith(("/", "\\")) or "../" in name.replace("\\", "/"):
                raise AuditError(f"{path.name}: unsafe archive path {name!r}")
            if offset > actual_size or size > actual_size - offset:
                raise AuditError(
                    f"{path.name}: entry {name!r} is out of bounds "
                    f"(offset={offset}, size={size}, archive={actual_size})"
                )
            entries.append(BigEntry(offset=offset, size=size, name=name))

        index_end = handle.tell()
        if index_end > data_start:
            raise AuditError(
                f"{path.name}: parsed index ends at {index_end}, "
                f"after data_start {data_start}"
            )
        if index_end < data_start:
            warnings.append(
                f"Index has {data_start - index_end} padding byte(s) before data"
            )

    normalized = [normalize_archive_name(e.name) for e in entries]
    duplicates = sorted(
        name for name, count in Counter(normalized).items() if count > 1
    )
    if duplicates:
        raise AuditError(
            f"{path.name}: duplicate case-insensitive archive paths: "
            + ", ".join(duplicates[:20])
        )

    ranges = sorted(
        (e.offset, e.offset + e.size, e.name)
        for e in entries
        if e.size > 0
    )
    overlaps = []
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            overlaps.append((previous[2], current[2]))
    if overlaps:
        warnings.append(
            f"{len(overlaps)} overlapping data range(s) detected; first pair: "
            f"{overlaps[0][0]!r} / {overlaps[0][1]!r}"
        )

    metadata = {
        "archive": path.name,
        "magic": magic.decode("ascii"),
        "size_bytes": actual_size,
        "size_human": human_size(actual_size),
        "sha256": sha256_file(path),
        "entry_count": entry_count,
        "data_start": data_start,
        "index_end": index_end,
    }
    return metadata, entries, warnings


def scan_russia_references(path: Path, entries: Iterable[BigEntry]) -> list[dict]:
    hits: list[dict] = []
    with path.open("rb") as handle:
        for entry in entries:
            ext = Path(entry.name).suffix.lower()
            path_hit = bool(RUSSIA_RE.search(entry.name.encode("utf-8", "ignore")))
            content_hits: list[dict] = []

            # Avoid treating large binary assets as text.
            if ext in TEXT_EXTENSIONS and entry.size <= 4 * 1024 * 1024:
                handle.seek(entry.offset)
                raw = handle.read(entry.size)
                for match_index, match in enumerate(RUSSIA_RE.finditer(raw)):
                    if match_index >= 20:
                        break
                    line = raw.count(b"\n", 0, match.start()) + 1
                    snippet_start = max(0, match.start() - 70)
                    snippet_end = min(len(raw), match.end() + 110)
                    snippet = raw[snippet_start:snippet_end]
                    snippet = snippet.replace(b"\r", b" ").replace(b"\n", b" ")
                    content_hits.append(
                        {
                            "line": line,
                            "term": match.group(0).decode("ascii", "ignore"),
                            "snippet": snippet.decode("utf-8", "replace"),
                        }
                    )

            if path_hit or content_hits:
                hits.append(
                    {
                        "path": entry.name,
                        "path_match": path_hit,
                        "content_matches": content_hits,
                    }
                )
    return hits


def pointer_audit(root: Path, out_dir: Path) -> None:
    attributes = root / ".gitattributes"
    if not attributes.exists():
        raise AuditError(".gitattributes is missing")
    attr_text = attributes.read_text(encoding="utf-8", errors="strict")
    expected_rule = "*.big filter=lfs diff=lfs merge=lfs -text"
    if expected_rule not in [line.strip() for line in attr_text.splitlines()]:
        raise AuditError(f".gitattributes is missing required rule: {expected_rule}")

    records = []
    for name, expected_size in BASELINE.items():
        path = root / name
        if not path.exists():
            raise AuditError(f"Baseline archive is missing: {name}")

        raw = path.read_bytes()
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise AuditError(
                f"{name}: expected a Git LFS pointer before targeted LFS pull"
            ) from exc

        match = LFS_RE.fullmatch(text)
        if not match:
            raise AuditError(f"{name}: invalid Git LFS pointer")

        oid, size_text = match.groups()
        pointer_size = int(size_text)
        if pointer_size != expected_size:
            raise AuditError(
                f"{name}: baseline size changed from {expected_size} to {pointer_size}"
            )

        records.append(
            {
                "archive": name,
                "oid_sha256": oid,
                "size_bytes": pointer_size,
                "size_human": human_size(pointer_size),
            }
        )

    total = sum(item["size_bytes"] for item in records)
    report = {
        "status": "ok",
        "archive_count": len(records),
        "total_size_bytes": total,
        "total_size_human": human_size(total),
        "archives": records,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "lfs-baseline.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Project X Re Git LFS Baseline",
        "",
        f"- Status: OK",
        f"- Archives: {len(records)}",
        f"- Total logical size: {human_size(total)}",
        "",
        "| Archive | Logical size | LFS SHA-256 |",
        "|---|---:|---|",
    ]
    for item in records:
        lines.append(
            f"| `{item['archive']}` | {item['size_human']} | "
            f"`{item['oid_sha256']}` |"
        )
    (out_dir / "lfs-baseline.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"OK: verified {len(records)} LFS pointers ({human_size(total)} logical)")


def big_audit(paths: list[Path], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    archives = []

    for path in paths:
        if not path.exists():
            raise AuditError(f"Archive not found: {path}")
        metadata, entries, warnings = parse_big(path)
        suffix_counts = Counter(Path(e.name).suffix.lower() or "<none>" for e in entries)
        russia_hits = scan_russia_references(path, entries)

        archive_report = {
            **metadata,
            "warnings": warnings,
            "extension_counts": dict(sorted(suffix_counts.items())),
            "russia_candidate_count": len(russia_hits),
            "russia_candidates": russia_hits,
            "entries": [
                {"path": e.name, "offset": e.offset, "size": e.size}
                for e in entries
            ],
        }
        archives.append(archive_report)
        print(
            f"OK: {path.name}: {metadata['entry_count']} entries, "
            f"{len(russia_hits)} Russia-related candidate file(s)"
        )

    report = {"status": "ok", "archives": archives}
    (out_dir / "big-audit.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = ["# Project X Re BIG Audit", ""]
    for archive in archives:
        lines.extend(
            [
                f"## {archive['archive']}",
                "",
                f"- Format: `{archive['magic']}`",
                f"- Size: {archive['size_human']}",
                f"- SHA-256: `{archive['sha256']}`",
                f"- Entries: {archive['entry_count']}",
                f"- Russia-related candidate files: {archive['russia_candidate_count']}",
            ]
        )
        if archive["warnings"]:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in archive["warnings"])
        lines.append("")
        if archive["russia_candidates"]:
            lines.append("### Russia-related candidates")
            lines.append("")
            for candidate in archive["russia_candidates"][:200]:
                lines.append(f"- `{candidate['path']}`")
            lines.append("")

    (out_dir / "big-audit.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.big"
        name = b"Data/INI/RussiaUnit.ini\x00"
        payload = b"Object RussiaUnit\nEnd\n"
        data_start = 16 + 8 + len(name)
        total_size = data_start + len(payload)
        header = (
            b"BIGF"
            + struct.pack("<I", total_size)
            + struct.pack(">I", 1)
            + struct.pack(">I", data_start)
        )
        index = struct.pack(">II", data_start, len(payload)) + name
        path.write_bytes(header + index + payload)

        metadata, entries, warnings = parse_big(path)
        assert metadata["magic"] == "BIGF"
        assert metadata["entry_count"] == 1
        assert entries[0].name == "Data/INI/RussiaUnit.ini"
        assert entries[0].size == len(payload)
        assert not warnings
        hits = scan_russia_references(path, entries)
        assert len(hits) == 1
        assert hits[0]["path_match"] is True
    print("OK: BIG parser self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    pointer_parser = sub.add_parser("pointers")
    pointer_parser.add_argument("--root", type=Path, default=Path("."))
    pointer_parser.add_argument("--out", type=Path, default=Path("ci-out"))

    big_parser = sub.add_parser("big")
    big_parser.add_argument("archives", nargs="+", type=Path)
    big_parser.add_argument("--out", type=Path, default=Path("ci-out"))

    sub.add_parser("self-test")

    args = parser.parse_args()
    try:
        if args.command == "pointers":
            pointer_audit(args.root.resolve(), args.out)
        elif args.command == "big":
            big_audit(args.archives, args.out)
        elif args.command == "self-test":
            self_test()
        else:
            raise AssertionError(args.command)
    except (AuditError, OSError, ValueError, struct.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
