#!/usr/bin/env python3
"""Move three Russian controls into mobile-visible command slots.

This is a byte-length-preserving CommandSet.ini edit on top of the validated
All Factions Structural Fix V1 artifact. No command definition is deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, parse_big

INPUT_SHA256 = "33a9bcd9ca413acd77a0a6f0bde98d1fdb5abc3a8ec7964865587c1a53416916"
COMMANDSET_PATH = "Data\\INI\\CommandSet.ini"

EDITS = (
    {
        "label": "Kashtan ground gun visibility",
        "before": "  17   Command_ConstructRussiaKashtan",
        "after":  "  11   Command_ConstructRussiaKashtan",
    },
    {
        "label": "Component Tower visibility",
        "before": "  18   Command_ConstructRussiaComponentTower",
        "after":  "  12   Command_ConstructRussiaComponentTower",
    },
    {
        "label": "Rocket System protocol visibility",
        "before": "  12 = Command_UpgradeRussiaRocketSystem",
        "after":  "   6 = Command_UpgradeRussiaRocketSystem",
    },
)

@dataclass
class Rec:
    name: str
    offset: int
    size: int
    pos: int

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def norm(s: str) -> str:
    return s.replace("\\", "/").lower()

def read_index(raw: bytes) -> list[Rec]:
    if raw[:4] not in (b"BIGF", b"BIG4"):
        raise AuditError("invalid BIG magic")
    total=struct.unpack("<I",raw[4:8])[0]
    count=struct.unpack(">I",raw[8:12])[0]
    if total != len(raw):
        raise AuditError("BIG size mismatch")
    pos=16
    out=[]
    for _ in range(count):
        rec_pos=pos
        off,size=struct.unpack(">II",raw[pos:pos+8]); pos+=8
        end=raw.index(b"\0",pos)
        name=raw[pos:end].decode("latin-1"); pos=end+1
        out.append(Rec(name,off,size,rec_pos))
    return out

def get_rec(records: list[Rec], path: str) -> Rec:
    hits=[r for r in records if norm(r.name)==norm(path)]
    if len(hits)!=1:
        raise AuditError(f"expected one {path}, found {len(hits)}")
    return hits[0]

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args()

    try:
        raw=args.source.read_bytes()
        if sha(raw)!=INPUT_SHA256:
            raise AuditError("source does not match validated All Factions Structural Fix V1")

        records=read_index(raw)
        rec=get_rec(records,COMMANDSET_PATH)
        old=raw[rec.offset:rec.offset+rec.size]
        text=old.decode("latin-1")

        applied=[]
        for edit in EDITS:
            before=edit["before"]
            after=edit["after"]
            if len(before)!=len(after):
                raise AuditError(f"{edit['label']}: edit is not length preserving")
            count=text.count(before)
            if count!=1:
                raise AuditError(
                    f"{edit['label']}: expected one exact source line, found {count}"
                )
            text=text.replace(before,after,1)
            applied.append(edit)

        new=text.encode("latin-1")
        if len(new)!=len(old):
            raise AuditError("CommandSet.ini size changed")

        patched=bytearray(raw)
        patched[rec.offset:rec.offset+rec.size]=new
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_bytes(patched)
        parse_big(args.output)

        new_raw=args.output.read_bytes()
        new_records=read_index(new_raw)
        old_map={norm(r.name):r for r in records}
        new_map={norm(r.name):r for r in new_records}
        changed=[]
        for key in sorted(old_map):
            a=raw[old_map[key].offset:old_map[key].offset+old_map[key].size]
            b=new_raw[new_map[key].offset:new_map[key].offset+new_map[key].size]
            if a!=b:
                changed.append(old_map[key].name)

        if changed != [COMMANDSET_PATH]:
            raise AuditError(f"unexpected changed BIG entries: {changed}")

        report={
            "status":"ok",
            "input_sha256":sha(raw),
            "fixed_sha256":sha(new_raw),
            "entry_count":len(records),
            "unchanged_entries":len(records)-1,
            "changed_entries":changed,
            "commandset_size":len(new),
            "edits":applied,
        }
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")

        print(
            "OK: Russia Mobile Command Visibility V1 built; "
            f"{report['unchanged_entries']} entries byte-identical; "
            "only CommandSet.ini changed"
        )
        print("FIXED_SHA256:",report["fixed_sha256"])
        for edit in applied:
            print("MOVED:",edit["label"],"|",edit["before"],"->",edit["after"])
        return 0
    except (AuditError,OSError,ValueError,struct.error) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
