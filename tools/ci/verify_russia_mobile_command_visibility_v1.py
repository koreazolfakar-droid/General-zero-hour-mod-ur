#!/usr/bin/env python3
"""Verify Russia mobile command visibility positions."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))

from baseline_audit import AuditError, parse_big

COMMANDSET_PATH="Data\\INI\\CommandSet.ini"

def read_entry(archive: Path, target: str) -> str:
    raw=archive.read_bytes()
    _meta,entries,_warnings=parse_big(archive)
    hits=[e for e in entries if e.name.replace("\\","/").lower()==target.replace("\\","/").lower()]
    if len(hits)!=1:
        raise AuditError(f"expected one {target}, found {len(hits)}")
    e=hits[0]
    return raw[e.offset:e.offset+e.size].decode("latin-1")

def block(text: str,name: str) -> str:
    m=re.search(
        rf"(?ms)^CommandSet\s+{re.escape(name)}\s*$.*?^End\s*$",
        text
    )
    if not m:
        raise AuditError(f"missing CommandSet {name}")
    return m.group(0)

def slots(text: str) -> dict[int,str]:
    out={}
    for line in text.splitlines():
        if line.lstrip().startswith(";"):
            continue
        m=re.match(r"^\s*(\d+)\s*(?:=\s*)?([A-Za-z_][A-Za-z0-9_]*)",line)
        if m:
            out[int(m.group(1))]=m.group(2)
    return out

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("archive",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()

    try:
        text=read_entry(args.archive,COMMANDSET_PATH)

        dozer=slots(block(text,"RussiaDozerCommandSet"))
        industrial=slots(block(text,"RussiaIndustrialPlantCommandSet"))

        expected_dozer={
            11:"Command_ConstructRussiaKashtan",
            12:"Command_ConstructRussiaComponentTower",
        }
        for slot,cmd in expected_dozer.items():
            if dozer.get(slot)!=cmd:
                raise AuditError(f"RussiaDozerCommandSet slot {slot}: expected {cmd}, got {dozer.get(slot)}")

        if dozer.get(17)=="Command_ConstructRussiaKashtan":
            raise AuditError("Kashtan still occupies high mobile-hidden slot 17")
        if dozer.get(18)=="Command_ConstructRussiaComponentTower":
            raise AuditError("Component Tower still occupies high mobile-hidden slot 18")

        if industrial.get(6)!="Command_UpgradeRussiaRocketSystem":
            raise AuditError(
                "RussiaIndustrialPlantCommandSet slot 6 does not expose Rocket System"
            )
        if industrial.get(12)=="Command_UpgradeRussiaRocketSystem":
            raise AuditError("Rocket System still occupies high slot 12")

        report={
            "status":"ok",
            "russia_dozer_slots":{
                "11":dozer[11],
                "12":dozer[12],
            },
            "industrial_plant_slot_6":industrial[6],
            "preserved_commands":[
                "Command_ConstructRussiaKashtan",
                "Command_ConstructRussiaComponentTower",
                "Command_UpgradeRussiaRocketSystem",
            ],
        }
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")

        print("OK: Russia mobile command visibility verified")
        print("VISIBLE: slot 11 Kashtan ground gun")
        print("VISIBLE: slot 12 Component Tower")
        print("VISIBLE: Industrial Plant slot 6 Rocket System protocol")
        return 0
    except (AuditError,OSError,ValueError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
