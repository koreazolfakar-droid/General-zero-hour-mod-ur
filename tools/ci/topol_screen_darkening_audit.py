#!/usr/bin/env python3
"""Read-only audit for persistent screen/map darkening after Russian Topol launch."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, parse_big
from russia_dependency_map import build_graph, parse_definitions, strip_comments

SEEDS = (
    "Command_TacticalNuclearStrike",
    "TopolMissileWeapon",
    "TopolMissile",
    "OCL_TopolMirvWareheadUpgrade",
)

VISUAL_RE = re.compile(
    r"(?i)(terrainlight|lightpulse|screen|tint|fade|dark|night|camera|viewshake|"
    r"shroud|weather|color|flash|postprocess|shadow|black|brightness|contrast)"
)
TOPOL_RE = re.compile(r"(?i)(topol|icbm|mirv|nuclear)")
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def reachable_from_seeds(definitions):
    nodes, edges, _ = build_graph(definitions)
    adjacency = defaultdict(list)
    for e in edges:
        adjacency[e.source].append((e.target, e.relation))

    seen=set()
    q=deque((seed,0) for seed in SEEDS)
    hops={}
    while q:
        name,depth=q.popleft()
        if name in seen or depth>5:
            continue
        seen.add(name)
        hops[name]=depth
        for target,_rel in adjacency.get(name,[]):
            if target not in seen:
                q.append((target,depth+1))
    return seen,hops,edges


def scan_reachable(definitions, reachable, hops):
    by_name=defaultdict(list)
    for d in definitions:
        by_name[d.name].append(d)

    hits=[]
    for name in sorted(reachable, key=lambda n:(hops.get(n,99),n)):
        for d in by_name.get(name,[]):
            body=strip_comments(d.body)
            matching=[]
            for lineno,line in enumerate(body.splitlines(),start=d.start_line):
                if VISUAL_RE.search(line):
                    matching.append({"line":lineno,"text":line.strip()})
            if matching:
                hits.append({
                    "name":name,
                    "kind":d.kind,
                    "path":d.path,
                    "start_line":d.start_line,
                    "hop":hops.get(name),
                    "matching_lines":matching,
                    "body":d.body.strip(),
                })
    return hits


def scan_raw_archive(archive: Path):
    raw=archive.read_bytes()
    _meta,entries,_warnings=parse_big(archive)
    hits=[]
    for e in entries:
        if not e.name.lower().endswith((".ini",".inc")):
            continue
        data=raw[e.offset:e.offset+e.size]
        try:
            text=data.decode("utf-8")
        except UnicodeDecodeError:
            text=data.decode("latin-1")

        if not TOPOL_RE.search(text):
            continue

        lines=text.splitlines()
        for i,line in enumerate(lines):
            if TOPOL_RE.search(line) and VISUAL_RE.search(line):
                lo=max(0,i-4)
                hi=min(len(lines),i+5)
                hits.append({
                    "path":e.name,
                    "line":i+1,
                    "context":lines[lo:hi],
                })
            elif TOPOL_RE.search(line):
                # Nearby visual-control lines often sit a few lines below a Topol symbol.
                lo=max(0,i-10)
                hi=min(len(lines),i+30)
                nearby=lines[lo:hi]
                if any(VISUAL_RE.search(x) for x in nearby):
                    hits.append({
                        "path":e.name,
                        "line":i+1,
                        "context":nearby,
                    })
    return hits


def exact_topol_definitions(definitions):
    out=[]
    for d in definitions:
        hay=(d.name+"\n"+d.path+"\n"+d.body)
        if TOPOL_RE.search(hay):
            out.append({
                "kind":d.kind,
                "name":d.name,
                "path":d.path,
                "line":d.start_line,
                "body":d.body.strip(),
            })
    return out


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("archives",nargs="+",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()

    try:
        definitions=[]
        for archive in args.archives:
            defs,_=parse_definitions(archive)
            definitions.extend(defs)

        reachable,hops,edges=reachable_from_seeds(definitions)
        reachable_visual=scan_reachable(definitions,reachable,hops)

        raw_hits=[]
        for archive in args.archives:
            raw_hits.extend(scan_raw_archive(archive))

        exact=exact_topol_definitions(definitions)

        # Flag the most suspicious reachable definitions first.
        suspicious=[]
        for item in reachable_visual:
            score=0
            joined="\n".join(x["text"] for x in item["matching_lines"]).lower()
            for term,weight in (
                ("terrainlight",5),
                ("lightpulse",5),
                ("fade",4),
                ("tint",4),
                ("dark",4),
                ("screen",3),
                ("color",2),
                ("flash",2),
                ("camera",1),
                ("viewshake",1),
            ):
                if term in joined:
                    score+=weight
            suspicious.append({**item,"score":score})
        suspicious.sort(key=lambda x:(-x["score"],x["hop"],x["name"]))

        report={
            "status":"ok",
            "seeds":list(SEEDS),
            "reachable_symbol_count":len(reachable),
            "reachable_visual_hits":suspicious,
            "raw_topol_visual_contexts":raw_hits,
            "topol_related_definitions":exact,
        }

        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/"topol-screen-darkening-audit.json").write_text(
            json.dumps(report,indent=2)+"\n",encoding="utf-8"
        )

        lines=[
            "# Topol Persistent Screen Darkening Audit","",
            f"- Reachable symbols from launch chain: **{len(reachable)}**",
            f"- Reachable definitions with visual/light keywords: **{len(suspicious)}**",
            f"- Raw Topol visual contexts: **{len(raw_hits)}**",
            "",
            "## Highest-suspicion reachable definitions","",
        ]
        for item in suspicious[:30]:
            lines.extend([
                f"### {item['kind']} {item['name']} (score {item['score']}, hop {item['hop']})",
                f"Source: {item['path']}:{item['start_line']}",
                "",
            ])
            for hit in item["matching_lines"]:
                lines.append(f"- L{hit['line']}: {hit['text']}")
            lines.extend(["","~~~ini",item["body"],"~~~",""])

        lines.extend(["## Raw Topol visual contexts",""])
        for hit in raw_hits[:50]:
            lines.extend([
                f"### {hit['path']}:{hit['line']}",
                "~~~text",
                *hit["context"],
                "~~~",
                "",
            ])

        (args.out/"topol-screen-darkening-audit.md").write_text(
            "\n".join(lines)+"\n",encoding="utf-8"
        )

        print(
            "OK: Topol screen-darkening audit: "
            f"{len(reachable)} reachable symbols, "
            f"{len(suspicious)} reachable visual hits, "
            f"{len(raw_hits)} raw contexts"
        )
        for item in suspicious[:20]:
            print(
                "SUSPECT:",
                item["score"],
                item["kind"],
                item["name"],
                item["path"],
                json.dumps(item["matching_lines"],ensure_ascii=False),
            )
        return 0

    except (AuditError,OSError,ValueError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
