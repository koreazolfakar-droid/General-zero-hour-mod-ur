#!/usr/bin/env python3
"""Focused repair analysis for remaining America/China/GLA structural refs."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError
from all_factions_audit import (
    RELATION_TARGET_KIND,
    build_typed_graph,
    parse_extended,
    player_identity,
    reachable_from,
)

TARGET_FAMILIES = {"America", "China", "GLA"}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        definitions = []
        for archive in args.archives:
            defs, _ = parse_extended(archive)
            definitions.extend(defs)

        by_name, edges, unresolved = build_typed_graph(definitions)
        roots = [d for d in definitions if d.kind == "PlayerTemplate"]

        names_by_kind = defaultdict(list)
        for name, defs in by_name.items():
            for kind in {d.kind for d in defs}:
                names_by_kind[kind].append(name)

        issues = []
        for root in roots:
            ident = player_identity(root)
            if ident["family"] not in TARGET_FAMILIES:
                continue

            reachable = reachable_from(root.name, edges)
            for u in unresolved:
                if u["source"] not in reachable:
                    continue

                expected_kind = RELATION_TARGET_KIND.get(u["relation"])
                if expected_kind is None:
                    continue

                source_defs = by_name.get(u["source"], [])
                source_rows = []
                for d in source_defs:
                    source_rows.append({
                        "kind": d.kind,
                        "path": d.path,
                        "line": d.start_line,
                        "body": d.body.strip(),
                    })

                pool = sorted(set(names_by_kind.get(expected_kind, [])))
                candidates = difflib.get_close_matches(
                    u["target"], pool, n=12, cutoff=0.28
                )

                target_tokens = u["target"].lower().replace("commandset", "").replace("ocl_", "")
                token_candidates = []
                for name in pool:
                    low = name.lower()
                    score = 0
                    for token in (
                        "china", "gla", "america", "tank", "vehicle", "infantry",
                        "barracks", "warfactory", "overlord", "krait", "libra",
                        "debris", "death", "toxic", "poison", "heroic"
                    ):
                        if token in target_tokens and token in low:
                            score += 1
                    if score:
                        token_candidates.append((score, name))
                token_candidates.sort(key=lambda x: (-x[0], x[1]))

                issues.append({
                    "family": ident["family"],
                    "player_template": root.name,
                    **u,
                    "expected_kind": expected_kind,
                    "source_definitions": source_rows,
                    "close_candidates": candidates,
                    "token_candidates": [name for _score, name in token_candidates[:20]],
                })

        seen = set()
        unique = []
        for x in issues:
            key = (x["family"], x["source"], x["relation"], x["target"], x["source_path"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(x)

        unique.sort(key=lambda x:(x["family"], x["source"], x["relation"], x["target"]))

        args.out.mkdir(parents=True, exist_ok=True)
        (args.out/"all-factions-repair-audit.json").write_text(
            json.dumps({"status":"ok","issues":unique}, indent=2)+"\n",
            encoding="utf-8"
        )

        lines=[
            "# All Factions Repair Audit","",
            f"Focused unresolved refs: **{len(unique)}**","",
        ]
        current=None
        for i,x in enumerate(unique,1):
            if current != x["family"]:
                current=x["family"]
                lines += [f"## {current}",""]
            lines += [
                f"### {i}. {x['source']} -> {x['target']}",
                f"- Relation: {x['relation']}",
                f"- Expected kind: {x['expected_kind']}",
                f"- Source: {x['source_path']}",
                f"- Close candidates: {', '.join(x['close_candidates']) or 'none'}",
                f"- Token candidates: {', '.join(x['token_candidates']) or 'none'}",
                "",
            ]
            for d in x["source_definitions"][:3]:
                lines += [
                    f"Source definition {d['kind']} {x['source']} @ {d['path']}:{d['line']}",
                    "~~~ini",
                    d["body"],
                    "~~~",
                    "",
                ]

        (args.out/"all-factions-repair-audit.md").write_text(
            "\n".join(lines)+"\n", encoding="utf-8"
        )

        print(f"OK: repair audit: {len(unique)} focused unresolved refs")
        for x in unique:
            print(
                "ISSUE:",
                x["family"],
                x["relation"],
                x["source"],
                "->",
                x["target"],
                "CANDIDATES=" + ",".join(x["close_candidates"][:6]),
            )
        return 0
    except (AuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
