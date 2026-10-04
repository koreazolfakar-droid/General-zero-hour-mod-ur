#!/usr/bin/env python3
"""Build a read-only dependency map for the Project X Re Russian faction.

This script reads materialized BIG archives, never modifies or repacks them,
and emits JSON/Markdown/DOT reports suitable for GitHub Actions artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from baseline_audit import AuditError, BigEntry, parse_big  # noqa: E402

BLOCK_TYPES = (
    "PlayerTemplate",
    "Object",
    "CommandButton",
    "CommandSet",
    "Science",
    "Upgrade",
    "Weapon",
    "Armor",
    "Locomotor",
    "SpecialPower",
    "ObjectCreationList",
    "FXList",
    "ParticleSystem",
)

BLOCK_RE = re.compile(
    r"(?m)^(" + "|".join(BLOCK_TYPES) + r")\\s+([A-Za-z_][A-Za-z0-9_]*)"
)
TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

RUSSIAN_NAME_RE = re.compile(r"(?i)(russia|russian|soviet)")
RUSSIAN_NAMESPACE_RE = re.compile(
    r"(?i)(^Russia|_Russia|Russian|Soviet|SCIENCE_Russia|Upgrade_Russia|Command_Russia)"
)


@dataclass(frozen=True)
class Definition:
    kind: str
    name: str
    archive: str
    path: str
    start_line: int
    end_line: int
    body: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str


def read_entry_text(archive: Path, entry: BigEntry) -> str:
    with archive.open("rb") as handle:
        handle.seek(entry.offset)
        raw = handle.read(entry.size)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(line.split(";", 1)[0])
    return "\n".join(lines)


def parse_definitions(archive: Path) -> tuple[list[Definition], dict]:
    metadata, entries, warnings = parse_big(archive)
    definitions: list[Definition] = []

    for entry in entries:
        if Path(entry.name).suffix.lower() not in {".ini", ".inc"}:
            continue

        text = read_entry_text(archive, entry).replace("\r\n", "\n").replace("\r", "\n")
        matches = list(BLOCK_RE.finditer(text))
        if not matches:
            continue

        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            start_line = text.count("\n", 0, start) + 1
            end_line = text.count("\n", 0, end) + 1
            definitions.append(
                Definition(
                    kind=match.group(1),
                    name=match.group(2),
                    archive=archive.name,
                    path=entry.name,
                    start_line=start_line,
                    end_line=end_line,
                    body=text[start:end],
                )
            )

    return definitions, {"metadata": metadata, "warnings": warnings}


def field_values(body: str, field: str) -> list[str]:
    clean = strip_comments(body)
    pattern = re.compile(
        rf"(?mi)^\s*{re.escape(field)}\s*=\s*([^\n]+)$"
    )
    values = []
    for match in pattern.finditer(clean):
        value = match.group(1).strip()
        if value:
            values.append(value)
    return values


def typed_reference_candidates(defn: Definition) -> list[tuple[str, str]]:
    """Return (relation, token) references extracted from well-known fields."""
    clean = strip_comments(defn.body)
    refs: list[tuple[str, str]] = []

    def one(field: str, relation: str, *, last_token: bool = False) -> None:
        for value in field_values(clean, field):
            tokens = TOKEN_RE.findall(value)
            if not tokens:
                continue
            refs.append((relation, tokens[-1] if last_token else tokens[0]))

    def many(field: str, relation: str) -> None:
        for value in field_values(clean, field):
            for token in TOKEN_RE.findall(value):
                refs.append((relation, token))

    if defn.kind == "PlayerTemplate":
        one("StartingBuilding", "starting-building")
        for line in clean.splitlines():
            m = re.match(r"^\s*StartingUnit\d+\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", line)
            if m:
                refs.append(("starting-unit", m.group(1)))
        many("IntrinsicSciences", "intrinsic-science")
        for field in (
            "PurchaseScienceCommandSetRank1",
            "PurchaseScienceCommandSetRank3",
            "PurchaseScienceCommandSetRank8",
            "SpecialPowerShortcutCommandSet",
        ):
            one(field, "command-set")

    elif defn.kind == "CommandSet":
        for line in clean.splitlines():
            m = re.match(r"^\s*\d+\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", line)
            if m:
                refs.append(("command-button", m.group(1)))

    elif defn.kind == "CommandButton":
        for field, relation in (
            ("Object", "build-object"),
            ("Upgrade", "upgrade"),
            ("Science", "science"),
            ("SpecialPower", "special-power"),
        ):
            one(field, relation)

    elif defn.kind == "Object":
        one("CommandSet", "command-set")
        many("TriggeredBy", "triggered-by")
        many("ConflictsWith", "conflicts-with")
        many("RequiresAllTriggers", "requires-trigger")
        one("SpecialPowerTemplate", "special-power")
        one("OCL", "ocl")
        one("Weapon", "weapon")
        one("Armor", "armor")
        one("Locomotor", "locomotor", last_token=True)
        one("Upgrade", "upgrade")
        one("Science", "science")

        # Prerequisite blocks commonly use Object = / Science =.
        for line in clean.splitlines():
            m = re.match(r"^\s*(Object|Science)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", line)
            if m:
                refs.append((f"prerequisite-{m.group(1).lower()}", m.group(2)))

    elif defn.kind == "Weapon":
        for field, relation in (
            ("ProjectileObject", "projectile-object"),
            ("FireFX", "fx"),
            ("ProjectileDetonationFX", "fx"),
            ("OCL", "ocl"),
        ):
            one(field, relation)

    elif defn.kind == "Science":
        many("PrerequisiteSciences", "prerequisite-science")

    elif defn.kind == "SpecialPower":
        one("OCL", "ocl")

    # Preserve deterministic order while removing duplicates.
    seen = set()
    result = []
    for relation, token in refs:
        key = (relation, token)
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def build_graph(definitions: list[Definition]) -> tuple[dict, list[Edge], list[dict]]:
    by_name: dict[str, list[Definition]] = defaultdict(list)
    for defn in definitions:
        by_name[defn.name].append(defn)

    known = set(by_name)
    edges: set[tuple[str, str, str]] = set()
    unresolved: list[dict] = []

    for defn in definitions:
        clean = strip_comments(defn.body)

        # Generic symbol references provide broad coverage beyond field-specific rules.
        for token in TOKEN_RE.findall(clean):
            if token != defn.name and token in known:
                edges.add((defn.name, token, "symbol"))

        for relation, token in typed_reference_candidates(defn):
            if token in known:
                edges.add((defn.name, token, relation))
            else:
                unresolved.append(
                    {
                        "source": defn.name,
                        "source_kind": defn.kind,
                        "source_path": defn.path,
                        "relation": relation,
                        "target": token,
                        "russian_namespace": bool(RUSSIAN_NAMESPACE_RE.search(token)),
                    }
                )

    return by_name, [Edge(*edge) for edge in sorted(edges)], unresolved


def find_russian_roots(definitions: list[Definition]) -> list[Definition]:
    roots = []
    for defn in definitions:
        if defn.kind != "PlayerTemplate":
            continue
        clean = strip_comments(defn.body)
        score = 0
        score += 5 if re.search(r"(?mi)^\s*Side\s*=\s*Russia\b", clean) else 0
        score += 4 if "INI:FactionRussia" in clean else 0
        score += 4 if "RussiaCommandCenter" in clean else 0
        score += 3 if "SCIENCE_Russia" in clean else 0
        score += 2 if "SpecialPowerShortcutRussia" in clean else 0
        if score >= 5:
            roots.append(defn)
    return roots


def reachable_from(seeds: set[str], edges: list[Edge]) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].add(edge.target)

    seen = set(seeds)
    queue = deque(sorted(seeds))
    while queue:
        source = queue.popleft()
        for target in sorted(adjacency.get(source, ())):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def classify_object_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    marker = "/Object/Russia/"
    if marker.lower() not in normalized.lower():
        return "Other"
    after = normalized.lower().split(marker.lower(), 1)[1]
    first = after.split("/", 1)[0]
    mapping = {
        "aircraft": "Aircraft",
        "buildings": "Buildings",
        "defences": "Defences",
        "infantry": "Infantry",
        "vehicles": "Vehicles",
    }
    return mapping.get(first, "Core")


def generate_reports(
    definitions: list[Definition],
    archive_info: list[dict],
    out_dir: Path,
) -> dict:
    by_name, edges, unresolved = build_graph(definitions)
    roots = find_russian_roots(definitions)
    if not roots:
        raise AuditError("No Russian PlayerTemplate root could be identified")

    root_names = {root.name for root in roots}
    reachable = reachable_from(root_names, edges)

    explicit_russian = {
        d.name
        for d in definitions
        if "/Object/Russia/" in d.path.replace("\\", "/")
        or RUSSIAN_NAME_RE.search(d.name)
    }
    russian_scope = reachable | explicit_russian

    duplicates = {
        name: [
            {
                "kind": d.kind,
                "archive": d.archive,
                "path": d.path,
                "line": d.start_line,
            }
            for d in defs
        ]
        for name, defs in by_name.items()
        if len(defs) > 1
    }

    nodes = []
    for name in sorted(russian_scope):
        defs = by_name.get(name, [])
        if not defs:
            continue
        primary = defs[0]
        nodes.append(
            {
                "name": name,
                "kind": primary.kind,
                "archive": primary.archive,
                "path": primary.path,
                "line": primary.start_line,
                "object_category": (
                    classify_object_path(primary.path)
                    if primary.kind == "Object"
                    else None
                ),
                "reachable_from_player_template": name in reachable,
                "explicit_russian": name in explicit_russian,
            }
        )

    scoped_edges = [
        asdict(edge)
        for edge in edges
        if edge.source in russian_scope and edge.target in russian_scope
    ]

    unresolved_russian = [
        item
        for item in unresolved
        if item["source"] in russian_scope and item["russian_namespace"]
    ]

    type_counts = Counter(node["kind"] for node in nodes)
    object_counts = Counter(
        node["object_category"]
        for node in nodes
        if node["kind"] == "Object" and node["object_category"]
    )

    report = {
        "status": "ok",
        "russian_player_templates": [
            {
                "name": r.name,
                "archive": r.archive,
                "path": r.path,
                "line": r.start_line,
            }
            for r in roots
        ],
        "summary": {
            "all_definitions": len(definitions),
            "unique_symbols": len(by_name),
            "all_edges": len(edges),
            "russian_scope_nodes": len(nodes),
            "russian_scope_edges": len(scoped_edges),
            "reachable_nodes": len(reachable),
            "explicit_russian_nodes": len(explicit_russian),
            "potential_unresolved_russian_refs": len(unresolved_russian),
            "duplicate_symbol_names": len(duplicates),
        },
        "type_counts": dict(sorted(type_counts.items())),
        "object_category_counts": dict(sorted(object_counts.items())),
        "nodes": nodes,
        "edges": scoped_edges,
        "potential_unresolved_russian_refs": unresolved_russian,
        "duplicates": duplicates,
        "archives": archive_info,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "russia-dependency-map.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Project X Re — Russian Faction Dependency Map",
        "",
        "This report is generated read-only from the materialized BIG archives.",
        "",
        "## Russian PlayerTemplate root",
        "",
    ]
    for root in report["russian_player_templates"]:
        lines.append(
            f"- `{root['name']}` — `{root['path']}:{root['line']}`"
        )

    s = report["summary"]
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Parsed definitions: **{s['all_definitions']}**",
            f"- Unique symbols: **{s['unique_symbols']}**",
            f"- Russian-scope nodes: **{s['russian_scope_nodes']}**",
            f"- Russian-scope dependency edges: **{s['russian_scope_edges']}**",
            f"- Reachable from Russian PlayerTemplate: **{s['reachable_nodes']}**",
            f"- Potential unresolved Russian references: **{s['potential_unresolved_russian_refs']}**",
            f"- Duplicate symbol names across audited archives: **{s['duplicate_symbol_names']}**",
            "",
            "## Nodes by type",
            "",
            "| Type | Count |",
            "|---|---:|",
        ]
    )
    for kind, count in sorted(type_counts.items()):
        lines.append(f"| {kind} | {count} |")

    lines.extend(["", "## Russian objects by category", "", "| Category | Count |", "|---|---:|"])
    for category, count in sorted(object_counts.items()):
        lines.append(f"| {category} | {count} |")

    lines.extend(["", "## Potential unresolved Russian references", ""])
    if unresolved_russian:
        lines.append("| Source | Relation | Missing target | Source file |")
        lines.append("|---|---|---|---|")
        for item in unresolved_russian[:250]:
            lines.append(
                f"| `{item['source']}` | {item['relation']} | "
                f"`{item['target']}` | `{item['source_path']}` |"
            )
    else:
        lines.append("None detected by the typed-reference checks.")

    lines.extend(["", "## Duplicate symbol names", ""])
    if duplicates:
        for name, places in sorted(duplicates.items())[:250]:
            lines.append(f"- `{name}`")
            for place in places:
                lines.append(
                    f"  - {place['archive']} — `{place['path']}:{place['line']}` "
                    f"({place['kind']})"
                )
    else:
        lines.append("None detected.")

    (out_dir / "russia-dependency-map.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    dot = [
        "digraph RussiaFaction {",
        '  rankdir="LR";',
        '  graph [overlap=false, splines=true];',
        '  node [shape=box];',
    ]
    for node in nodes:
        safe = node["name"].replace('"', '\\"')
        label = f"{node['kind']}\\n{safe}".replace('"', '\\"')
        dot.append(f'  "{safe}" [label="{label}"];')
    for edge in scoped_edges:
        sname = edge["source"].replace('"', '\\"')
        tname = edge["target"].replace('"', '\\"')
        relation = edge["relation"].replace('"', '\\"')
        dot.append(f'  "{sname}" -> "{tname}" [label="{relation}"];')
    dot.append("}")
    (out_dir / "russia-dependency-map.dot").write_text(
        "\n".join(dot) + "\n", encoding="utf-8"
    )

    return report


def self_test() -> None:
    sample = """
PlayerTemplate FactionRussiaAlias
  Side = Russia
  IntrinsicSciences = SCIENCE_Russia
  StartingBuilding = RussiaCommandCenter
  PurchaseScienceCommandSetRank1 = SCIENCE_Russia_CommandSetRank1
End

Science SCIENCE_Russia
End

CommandSet SCIENCE_Russia_CommandSetRank1
  1 = Command_PurchaseRussiaThing
End

CommandButton Command_PurchaseRussiaThing
  Command = UNIT_BUILD
  Object = RussiaTank
End

Object RussiaCommandCenter
  CommandSet = RussiaCommandCenterCommandSet
End

CommandSet RussiaCommandCenterCommandSet
  1 = Command_ConstructRussiaTank
End

CommandButton Command_ConstructRussiaTank
  Command = UNIT_BUILD
  Object = RussiaTank
End

Object RussiaTank
  WeaponSet
    Weapon = PRIMARY RussiaTankGun
  End
End

Weapon RussiaTankGun
End
""".strip()

    matches = list(BLOCK_RE.finditer(sample))
    defs = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(sample)
        defs.append(
            Definition(
                kind=match.group(1),
                name=match.group(2),
                archive="test.big",
                path="Data\\INI\\test.ini",
                start_line=sample.count("\n", 0, start) + 1,
                end_line=sample.count("\n", 0, end) + 1,
                body=sample[start:end],
            )
        )
    roots = find_russian_roots(defs)
    assert [r.name for r in roots] == ["FactionRussiaAlias"]
    _, edges, unresolved = build_graph(defs)
    reach = reachable_from({"FactionRussiaAlias"}, edges)
    assert "RussiaTank" in reach
    assert "RussiaTankGun" in reach
    assert not [u for u in unresolved if u["russian_namespace"]]
    print("OK: Russian dependency-map self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=Path("ci-out/russia-map"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.self_test:
            self_test()
            return 0
        if not args.archives:
            raise AuditError("At least one BIG archive is required")

        all_definitions: list[Definition] = []
        archive_info = []
        for archive in args.archives:
            definitions, info = parse_definitions(archive)
            all_definitions.extend(definitions)
            archive_info.append(info)

        report = generate_reports(all_definitions, archive_info, args.out)
        s = report["summary"]
        print(
            "OK: Russian dependency map: "
            f"{s['russian_scope_nodes']} nodes, "
            f"{s['russian_scope_edges']} edges, "
            f"{s['potential_unresolved_russian_refs']} potential unresolved Russian refs"
        )
        for root in report["russian_player_templates"]:
            print(
                f"ROOT: {root['name']} @ {root['path']}:{root['line']}"
            )
        return 0
    except (AuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
