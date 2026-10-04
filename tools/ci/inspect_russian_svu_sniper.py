#!/usr/bin/env python3
"""Focused read-only audit of the Russian SVU sniper wiring."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError
from russia_dependency_map import (
    Definition,
    build_graph,
    parse_definitions,
    strip_comments,
    typed_reference_candidates,
)

TARGET_OBJECT = "RussiaInfantrySVUSniper"
TARGET_BUILD_BUTTON = "Command_ConstructRussiaInfantrySVUSniper"
TARGET_COMMANDSET = "RussianInfantrySVUSniperCommandSet"
TERMS = ("svu", "sniper")


def compact_body(body: str) -> str:
    return body.strip() + "\n"


def definition_record(defn: Definition) -> dict:
    return {
        "kind": defn.kind,
        "name": defn.name,
        "archive": defn.archive,
        "path": defn.path,
        "start_line": defn.start_line,
        "end_line": defn.end_line,
        "body": compact_body(defn.body),
        "typed_references": [
            {"relation": relation, "target": target}
            for relation, target in typed_reference_candidates(defn)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("ci-out/svu-sniper"))
    args = parser.parse_args()

    try:
        definitions: list[Definition] = []
        archive_info = []
        for archive in args.archives:
            defs, info = parse_definitions(archive)
            definitions.extend(defs)
            archive_info.append(info)

        by_name: dict[str, list[Definition]] = defaultdict(list)
        for d in definitions:
            by_name[d.name].append(d)

        _, edges, _ = build_graph(definitions)
        incoming: dict[str, list[dict]] = defaultdict(list)
        outgoing: dict[str, list[dict]] = defaultdict(list)
        for edge in edges:
            item = {"source": edge.source, "target": edge.target, "relation": edge.relation}
            outgoing[edge.source].append(item)
            incoming[edge.target].append(item)

        target_defs = by_name.get(TARGET_OBJECT, [])
        if not target_defs:
            raise AuditError(f"Missing target object: {TARGET_OBJECT}")
        if by_name.get(TARGET_COMMANDSET):
            raise AuditError(
                f"{TARGET_COMMANDSET} now exists; the original missing-reference assumption changed"
            )

        target = target_defs[0]

        infantry_rows = []
        for d in definitions:
            normalized = d.path.replace("\\", "/").lower()
            if d.kind != "Object" or "/object/russia/infantry/" not in normalized:
                continue
            commandsets = [
                ref_target
                for relation, ref_target in typed_reference_candidates(d)
                if relation == "command-set"
            ]
            infantry_rows.append(
                {
                    "object": d.name,
                    "path": d.path,
                    "line": d.start_line,
                    "commandsets": commandsets,
                }
            )

        candidate_commandset_names = set()
        for row in infantry_rows:
            candidate_commandset_names.update(row["commandsets"])
        for name, defs in by_name.items():
            if not defs or defs[0].kind != "CommandSet":
                continue
            lowered = name.lower()
            if "russianinfantry" in lowered or "sniper" in lowered or "svu" in lowered:
                candidate_commandset_names.add(name)

        candidate_commandsets = []
        for name in sorted(candidate_commandset_names):
            for d in by_name.get(name, []):
                if d.kind == "CommandSet":
                    candidate_commandsets.append(definition_record(d))

        related = []
        for d in definitions:
            hay = (d.name + "\n" + d.path + "\n" + d.body).lower()
            if any(term in hay for term in TERMS):
                related.append(definition_record(d))

        command_relevant_lines = []
        for line_no, line in enumerate(target.body.splitlines(), start=target.start_line):
            if re.search(
                r"(?i)(CommandSet|SpecialPower|Upgrade|Weapon|Stealth|Experience|Veterancy|Button|OCL|Behavior)",
                line,
            ):
                command_relevant_lines.append({"line": line_no, "text": line.rstrip()})

        result = {
            "status": "ok",
            "target_object": definition_record(target),
            "target_commandset": TARGET_COMMANDSET,
            "target_commandset_defined": False,
            "target_build_button": [
                definition_record(d) for d in by_name.get(TARGET_BUILD_BUTTON, [])
            ],
            "target_incoming_edges": sorted(
                incoming.get(TARGET_OBJECT, []),
                key=lambda x: (x["source"], x["relation"]),
            ),
            "target_outgoing_edges": sorted(
                outgoing.get(TARGET_OBJECT, []),
                key=lambda x: (x["target"], x["relation"]),
            ),
            "target_command_relevant_lines": command_relevant_lines,
            "russian_infantry_objects": sorted(infantry_rows, key=lambda x: x["object"]),
            "candidate_commandsets": candidate_commandsets,
            "svu_sniper_related_definitions": related,
            "archives": archive_info,
        }

        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "svu-sniper-audit.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

        lines = [
            "# Russian SVU Sniper Focused Audit",
            "",
            f"## Target object: {TARGET_OBJECT}",
            "",
            f"- Source: {target.path}:{target.start_line}",
            f"- Missing CommandSet: {TARGET_COMMANDSET}",
            f"- Incoming dependency edges: {len(result['target_incoming_edges'])}",
            f"- Outgoing dependency edges: {len(result['target_outgoing_edges'])}",
            "",
            "### Object definition",
            "",
            "~~~ini",
            compact_body(target.body).rstrip(),
            "~~~",
            "",
            "### Build button",
            "",
        ]
        for item in result["target_build_button"]:
            lines.extend(["~~~ini", item["body"].rstrip(), "~~~", ""])

        lines.extend(["### Incoming edges", ""])
        for edge in result["target_incoming_edges"]:
            lines.append(
                f"- {edge['source']} --{edge['relation']}--> {edge['target']}"
            )

        lines.extend(["", "### Command/ability-relevant object lines", ""])
        for item in command_relevant_lines:
            lines.append(f"- L{item['line']}: {item['text'].strip()}")

        lines.extend(
            [
                "",
                "## Russian infantry CommandSet usage",
                "",
                "| Object | CommandSet(s) | Source |",
                "|---|---|---|",
            ]
        )
        for row in result["russian_infantry_objects"]:
            cs = ", ".join(row["commandsets"]) or "—"
            lines.append(f"| {row['object']} | {cs} | {row['path']}:{row['line']} |")

        lines.extend(["", "## Candidate CommandSet definitions", ""])
        for item in candidate_commandsets:
            lines.extend(
                [
                    f"### {item['name']}",
                    "",
                    f"Source: {item['path']}:{item['start_line']}",
                    "",
                    "~~~ini",
                    item["body"].rstrip(),
                    "~~~",
                    "",
                ]
            )

        lines.extend(["## SVU/Sniper-related definitions", ""])
        for item in related:
            lines.extend(
                [
                    f"### {item['kind']} {item['name']}",
                    "",
                    f"Source: {item['path']}:{item['start_line']}",
                    "",
                    "~~~ini",
                    item["body"].rstrip(),
                    "~~~",
                    "",
                ]
            )

        (args.out / "svu-sniper-audit.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

        print(
            "OK: SVU sniper focused audit: "
            f"{len(infantry_rows)} Russian infantry objects, "
            f"{len(candidate_commandsets)} candidate command sets, "
            f"{len(related)} SVU/sniper-related definitions"
        )
        print(f"TARGET: {TARGET_OBJECT} @ {target.path}:{target.start_line}")
        print(f"MISSING: {TARGET_COMMANDSET}")
        return 0

    except (AuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
