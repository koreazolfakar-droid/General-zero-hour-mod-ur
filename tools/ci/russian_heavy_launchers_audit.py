#!/usr/bin/env python3
"""Read-only audit of Russian heavy artillery/launcher mobility."""

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
from russia_dependency_map import parse_definitions, strip_comments

TERMS = ("topol", "grumble", "buratino", "msta", "tornado", "iskander")
LOCO_RE = re.compile(
    r"(?mi)^\s*Locomotor\s*=\s*SET_NORMAL\s+([A-Za-z_][A-Za-z0-9_]*)"
)
FIELD_RE = re.compile(
    r"(?mi)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;\r\n]+)"
)
FIELDS = (
    "Speed", "SpeedDamaged", "TurnRate", "TurnRateDamaged",
    "Acceleration", "AccelerationDamaged", "Braking",
    "MinTurnSpeed", "TurnPivotOffset", "Appearance", "Surfaces"
)


def assigns(body: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for k, v in FIELD_RE.findall(strip_comments(body)):
        out[k].append(v.strip())
    return dict(out)


def first(a, key):
    vals=a.get(key, [])
    return vals[0] if vals else None


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("archives", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args=ap.parse_args()

    try:
        definitions=[]
        for archive in args.archives:
            defs,_=parse_definitions(archive)
            definitions.extend(defs)

        by_name=defaultdict(list)
        for d in definitions:
            by_name[d.name].append(d)

        objects=[]
        loco_names=set()
        for d in definitions:
            if d.kind != "Object":
                continue
            hay=(d.name+"\n"+d.path+"\n"+d.body).lower()
            if not any(t in hay for t in TERMS):
                continue
            if "/object/russia/vehicles/" not in d.path.replace("\\","/").lower():
                continue

            m=LOCO_RE.search(strip_comments(d.body))
            loco=m.group(1) if m else None
            if loco:
                loco_names.add(loco)
            a=assigns(d.body)
            objects.append({
                "name":d.name,
                "path":d.path,
                "line":d.start_line,
                "locomotor":loco,
                "build_cost":first(a,"BuildCost"),
                "build_time":first(a,"BuildTime"),
                "geometry":{
                    k:first(a,k) for k in (
                        "Geometry","GeometryMajorRadius","GeometryMinorRadius",
                        "GeometryHeight","GeometryIsSmall"
                    ) if first(a,k) is not None
                },
            })

        locomotors=[]
        for name in sorted(loco_names):
            defs=[d for d in by_name.get(name,[]) if d.kind=="Locomotor"]
            if len(defs)!=1:
                locomotors.append({"name":name,"defined":False,"count":len(defs)})
                continue
            d=defs[0]
            a=assigns(d.body)
            locomotors.append({
                "name":name,
                "defined":True,
                "path":d.path,
                "line":d.start_line,
                "fields":{k:first(a,k) for k in FIELDS if first(a,k) is not None},
            })

        result={
            "status":"ok",
            "objects":sorted(objects,key=lambda x:x["name"]),
            "locomotors":locomotors,
        }
        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/"heavy-launchers-audit.json").write_text(
            json.dumps(result,indent=2)+"\n",encoding="utf-8"
        )

        lines=[
            "# Russian Heavy Launchers Mobility Audit","",
            "| Object | Locomotor | Cost | BuildTime | Source |",
            "|---|---|---:|---:|---|",
        ]
        for o in result["objects"]:
            lines.append(
                f"| {o['name']} | {o['locomotor'] or '—'} | "
                f"{o['build_cost'] or '—'} | {o['build_time'] or '—'} | "
                f"{o['path']}:{o['line']} |"
            )
        lines.extend(["","## Locomotors",""])
        for l in locomotors:
            lines.append(f"### {l['name']}")
            lines.append("")
            if not l["defined"]:
                lines.append(f"Definition count: {l['count']}")
                lines.append("")
                continue
            lines.append(f"Source: {l['path']}:{l['line']}")
            lines.append("")
            lines.append("~~~text")
            for k,v in l["fields"].items():
                lines.append(f"{k} = {v}")
            lines.append("~~~")
            lines.append("")

        (args.out/"heavy-launchers-audit.md").write_text(
            "\n".join(lines)+"\n",encoding="utf-8"
        )

        print(
            f"OK: heavy launchers audit: {len(objects)} objects, "
            f"{len(locomotors)} locomotors"
        )
        for o in result["objects"]:
            print(f"OBJECT: {o['name']} -> {o['locomotor']}")
        for l in locomotors:
            if l["defined"]:
                print(f"LOCO: {l['name']} {json.dumps(l['fields'])}")
        return 0

    except (AuditError,OSError,ValueError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
