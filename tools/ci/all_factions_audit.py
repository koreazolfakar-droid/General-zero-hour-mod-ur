#!/usr/bin/env python3
"""Audit every playable faction/general in Project X Re.

This is a read-only structural audit. It parses Object, ChildObject and
ObjectReskin definitions so inherited/reskinned units are counted as real
object targets instead of being reported as false missing-object defects.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, parse_big
from russia_dependency_map import (
    BLOCK_TYPES,
    Definition,
    Edge,
    build_graph,
    field_values,
    read_entry_text,
    strip_comments,
    typed_reference_candidates,
)

EXTENDED_BLOCK_TYPES = tuple(BLOCK_TYPES) + ("ChildObject", "ObjectReskin")
EXTENDED_BLOCK_RE = re.compile(
    r"(?m)^(" + "|".join(EXTENDED_BLOCK_TYPES) + r")\s+([A-Za-z_][A-Za-z0-9_]*)"
)
TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

RELATION_TARGET_KIND = {
    "starting-building": "Object",
    "starting-unit": "Object",
    "build-object": "Object",
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
    "requires-trigger": "Upgrade",
    "special-power": "SpecialPower",
    "weapon": "Weapon",
    "locomotor": "Locomotor",
    "armor": "Armor",
    "ocl": "ObjectCreationList",
    "fx": "FXList",
}


def parse_extended(archive: Path) -> tuple[list[Definition], dict]:
    metadata, entries, warnings = parse_big(archive)
    definitions: list[Definition] = []

    for entry in entries:
        if Path(entry.name).suffix.lower() not in {".ini", ".inc"}:
            continue
        text = read_entry_text(archive, entry).replace("\r\n", "\n").replace("\r", "\n")
        matches = list(EXTENDED_BLOCK_RE.finditer(text))
        if not matches:
            continue

        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            raw_kind = match.group(1)
            kind = "Object" if raw_kind in {"ChildObject", "ObjectReskin"} else raw_kind
            definitions.append(
                Definition(
                    kind=kind,
                    name=match.group(2),
                    archive=archive.name,
                    path=entry.name,
                    start_line=text.count("\n", 0, start) + 1,
                    end_line=text.count("\n", 0, end) + 1,
                    body=text[start:end],
                )
            )
    return definitions, {"metadata": metadata, "warnings": warnings}


def reachable_from(root: str, edges: list[Edge]) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].add(edge.target)

    seen: set[str] = set()
    q = deque([root])
    while q:
        current = q.popleft()
        if current in seen:
            continue
        seen.add(current)
        for nxt in adjacency.get(current, ()):
            if nxt not in seen:
                q.append(nxt)
    return seen


def player_identity(defn: Definition) -> dict:
    body = strip_comments(defn.body)
    side = (field_values(body, "Side") or [None])[0]
    intrinsic = []
    for value in field_values(body, "IntrinsicSciences"):
        intrinsic.extend(TOKEN_RE.findall(value))
    starting_building = (field_values(body, "StartingBuilding") or [None])[0]

    is_russia = (
        any(x == "SCIENCE_Russia" for x in intrinsic)
        or (starting_building or "").startswith("Russia")
        or re.search(r"(?i)russia|russian", body) is not None
    )

    if is_russia:
        family = "Russia"
    elif (starting_building or "").startswith("Europe") or re.search(r"(?i)SCIENCE_Europe|\bEurope", body):
        family = "Europe"
    elif side:
        family = side
    elif defn.name.startswith("FactionAmerica"):
        family = "America"
    elif defn.name.startswith("FactionChina"):
        family = "China"
    elif defn.name.startswith("FactionGLA"):
        family = "GLA"
    else:
        family = "Other"

    return {
        "name": defn.name,
        "family": family,
        "side": side,
        "intrinsic_sciences": intrinsic,
        "starting_building": starting_building,
        "path": defn.path,
        "line": defn.start_line,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        definitions: list[Definition] = []
        archives = []
        for archive in args.archives:
            defs, info = parse_extended(archive)
            definitions.extend(defs)
            archives.append({"name": archive.name, **info})

        by_name, edges, unresolved = build_graph(definitions)
        roots = [d for d in definitions if d.kind == "PlayerTemplate"]
        if not roots:
            raise AuditError("No PlayerTemplate definitions found")

        duplicate_names = {
            name: defs for name, defs in by_name.items() if len(defs) > 1
        }

        factions = []
        for root in roots:
            identity = player_identity(root)
            reachable = reachable_from(root.name, edges)

            scoped_defs = [
                d for name in reachable for d in by_name.get(name, [])
            ]
            scoped_kinds = Counter(d.kind for d in scoped_defs)

            scoped_unresolved = [
                u for u in unresolved if u["source"] in reachable
            ]

            typed_unresolved = []
            sentinels = {"none", "yes", "no", "true", "false", "null", "0"}
            for u in scoped_unresolved:
                expected = RELATION_TARGET_KIND.get(u["relation"])
                if expected is None:
                    continue

                target = u["target"]
                relation = u["relation"]
                low = target.lower()

                # Ignore engine sentinel/boolean values that are intentionally
                # not symbol references.
                if low in sentinels:
                    continue

                # RequiresAllTriggers is a boolean, not an Upgrade reference.
                if relation == "requires-trigger":
                    continue

                # Tighten typed fields to their normal namespaces. This avoids
                # false positives from unrelated fields inside large blocks.
                if "science" in relation and not target.startswith("SCIENCE_"):
                    continue
                if relation in {"upgrade", "triggered-by", "conflicts-with"} and not target.startswith("Upgrade_"):
                    continue
                if relation == "command-set" and "CommandSet" not in target:
                    continue
                if relation == "command-button" and not target.startswith("Command_"):
                    continue
                if relation == "ocl" and not target.startswith("OCL_"):
                    continue

                typed_unresolved.append({
                    **u,
                    "expected_kind": expected,
                })

            active_build_buttons = []
            for d in scoped_defs:
                if d.kind != "CommandButton":
                    continue
                refs = [
                    (rel, tok) for rel, tok in typed_reference_candidates(d)
                    if rel == "build-object"
                ]
                for _rel, target in refs:
                    active_build_buttons.append({
                        "button": d.name,
                        "target": target,
                        "target_defined": target in by_name,
                        "path": d.path,
                        "line": d.start_line,
                    })

            missing_commandsets = [
                x for x in typed_unresolved if x["relation"] == "command-set"
            ]
            missing_build_objects = [
                x for x in typed_unresolved if x["relation"] in {
                    "build-object", "starting-building", "starting-unit"
                }
            ]
            missing_weapons = [
                x for x in typed_unresolved if x["relation"] == "weapon"
            ]
            missing_upgrades = [
                x for x in typed_unresolved if x["relation"] in {
                    "upgrade", "triggered-by", "conflicts-with", "requires-trigger"
                }
            ]
            missing_sciences = [
                x for x in typed_unresolved if "science" in x["relation"]
            ]

            severity = "clean"
            if missing_commandsets or missing_build_objects:
                severity = "critical"
            elif missing_weapons or missing_upgrades or missing_sciences:
                severity = "warning"
            elif typed_unresolved:
                severity = "review"

            factions.append({
                **identity,
                "reachable_symbols": len(reachable),
                "definition_kinds": dict(sorted(scoped_kinds.items())),
                "typed_unresolved_count": len(typed_unresolved),
                "severity": severity,
                "missing_commandsets": missing_commandsets,
                "missing_build_objects": missing_build_objects,
                "missing_weapons": missing_weapons,
                "missing_upgrades": missing_upgrades,
                "missing_sciences": missing_sciences,
                "typed_unresolved": typed_unresolved,
                "active_build_buttons": active_build_buttons,
            })

        unresolved_impact = defaultdict(set)
        unresolved_example = {}
        for faction in factions:
            for u in faction["typed_unresolved"]:
                key = (
                    u["source"], u["relation"], u["target"], u["source_path"]
                )
                unresolved_impact[key].add(faction["name"])
                unresolved_example[key] = u

        cross_faction = []
        for key, affected in unresolved_impact.items():
            item = unresolved_example[key]
            cross_faction.append({
                **item,
                "affected_factions": sorted(affected),
                "affected_count": len(affected),
            })
        cross_faction.sort(
            key=lambda x: (-x["affected_count"], x["source"], x["relation"], x["target"])
        )

        combat_factions = [
            f for f in factions if f["family"] not in {"Civilian", "Observer"}
        ]

        summary = {
            "player_templates": len(factions),
            "combat_factions": len(combat_factions),
            "families": dict(Counter(f["family"] for f in factions)),
            "critical_factions": sum(f["severity"] == "critical" for f in combat_factions),
            "warning_factions": sum(f["severity"] == "warning" for f in combat_factions),
            "review_factions": sum(f["severity"] == "review" for f in combat_factions),
            "clean_factions": sum(f["severity"] == "clean" for f in combat_factions),
            "all_definitions": len(definitions),
            "unique_symbols": len(by_name),
            "duplicate_symbol_names": len(duplicate_names),
            "typed_unresolved_total_occurrences": sum(
                f["typed_unresolved_count"] for f in factions
            ),
            "unique_typed_unresolved": len(cross_faction),
        }

        report = {
            "status": "ok",
            "summary": summary,
            "factions": sorted(
                factions, key=lambda f: (f["family"], f["name"])
            ),
            "cross_faction_unresolved": cross_faction,
            "archives": archives,
        }

        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "all-factions-audit.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        lines = [
            "# Project X Re — All Factions Structural Audit",
            "",
            "This audit includes ChildObject and ObjectReskin as valid object definitions",
            "to avoid false missing-unit reports from inherited/reskinned units.",
            "",
            "## Summary",
            "",
            f"- PlayerTemplates: **{summary['player_templates']}**",
            f"- Combat factions: **{summary['combat_factions']}**",
            f"- Families: **{summary['families']}**",
            f"- Critical factions: **{summary['critical_factions']}**",
            f"- Warning factions: **{summary['warning_factions']}**",
            f"- Review-only factions: **{summary['review_factions']}**",
            f"- Structurally clean factions: **{summary['clean_factions']}**",
            f"- Unique typed unresolved references: **{summary['unique_typed_unresolved']}**",
            f"- Duplicate symbol names: **{summary['duplicate_symbol_names']}**",
            "",
            "## Faction overview",
            "",
            "| Family | PlayerTemplate | Reachable | Unresolved | Status | Starting building |",
            "|---|---|---:|---:|---|---|",
        ]
        for f in report["factions"]:
            lines.append(
                f"| {f['family']} | {f['name']} | {f['reachable_symbols']} | "
                f"{f['typed_unresolved_count']} | **{f['severity']}** | "
                f"{f['starting_building'] or '—'} |"
            )

        lines.extend([
            "",
            "## Actionable unresolved references by faction",
            "",
        ])
        for f in report["factions"]:
            if not f["typed_unresolved"]:
                continue
            lines.append(f"### {f['family']} — {f['name']}")
            lines.append("")
            lines.append("| Relation | Source | Missing target | Source file |")
            lines.append("|---|---|---|---|")
            for u in f["typed_unresolved"]:
                lines.append(
                    f"| {u['relation']} | {u['source']} | {u['target']} | "
                    f"{u['source_path']} |"
                )
            lines.append("")

        lines.extend([
            "## Cross-faction impact",
            "",
            "| Affected | Relation | Source | Missing target | Factions |",
            "|---:|---|---|---|---|",
        ])
        for u in cross_faction:
            lines.append(
                f"| {u['affected_count']} | {u['relation']} | {u['source']} | "
                f"{u['target']} | {', '.join(u['affected_factions'])} |"
            )

        (args.out / "all-factions-audit.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

        print(
            "OK: all-factions audit: "
            f"{summary['player_templates']} PlayerTemplates, "
            f"{summary['critical_factions']} critical, "
            f"{summary['warning_factions']} warning, "
            f"{summary['clean_factions']} clean, "
            f"{summary['unique_typed_unresolved']} unique unresolved refs"
        )
        for f in report["factions"]:
            print(
                "FACTION:",
                f["family"],
                f["name"],
                f"reachable={f['reachable_symbols']}",
                f"unresolved={f['typed_unresolved_count']}",
                f"status={f['severity']}",
            )
        for u in cross_faction[:100]:
            print(
                "UNRESOLVED:",
                u["affected_count"],
                u["relation"],
                u["source"],
                "->",
                u["target"],
                "factions=" + ",".join(u["affected_factions"]),
            )
        return 0

    except (AuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
