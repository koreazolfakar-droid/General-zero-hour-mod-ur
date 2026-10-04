#!/usr/bin/env python3
"""Focused verifier for All Factions Structural Fix V1 additions."""

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
from all_factions_audit import parse_extended
from russia_dependency_map import typed_reference_candidates

EXPECTED_COMMANDSETS = {
    "ChinaBarracksChinaProtocolCommandSet",
    "ChinaWarFactoryChinaProtocolCommandSet",
    "ChinaTankNukeOverlordCommandSet_Speaker",
    "ChinaTankNukeOverlordCommandSet_Upgraded",
    "GLAVehicleKraitCommandSet",
}

EXPECTED_OCLS = {
    "OCL_LibraTankDeathEffectSimple",
    "OCL_ToxicInfantryGamma",
    "OCL_ChinaQuadFangDebris",
    "OCL_ChinaTankEmperorDeathEffectSimple",
    "OCL_ChinaTankEmperorDebris",
    "OCL_ChinaTankSuperOverlordDebris",
    "OCL_ChinaTankWarMasterDebris",
    "OCL_SiegeCannonDeathEffect",
    "OCL_FinalSTroopCrawlerDeathEffectSimple",
    "OCL_FinalSTroopCrawlerDebris",
    "OCL_GLABasiliskExplode",
    "OCL_CombatBuggyDeath_Rebel",
    "OCL_CombatBuggyDeath_FlashTrooper",
    "OCL_CombatBuggyDeath_Jarmen",
    "OCL_CombatBuggyDeath_Grenadier",
    "OCL_ToxinTractorPoisonField",
    "OCL_NukebombTruckDebris",
}

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("archive", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args=ap.parse_args()

    try:
        defs,_=parse_extended(args.archive)
        by_name=defaultdict(list)
        for d in defs:
            by_name[d.name].append(d)

        for name in EXPECTED_COMMANDSETS | EXPECTED_OCLS:
            if len(by_name.get(name,[])) != 1:
                raise AuditError(
                    f"expected exactly one added definition {name}, "
                    f"found {len(by_name.get(name,[]))}"
                )

        command_buttons={d.name for d in defs if d.kind=="CommandButton"}
        objects={d.name for d in defs if d.kind=="Object"}

        commandset_checks=[]
        for name in sorted(EXPECTED_COMMANDSETS):
            d=by_name[name][0]
            refs=[
                target for relation,target in typed_reference_candidates(d)
                if relation=="command-button"
            ]
            missing=[x for x in refs if x not in command_buttons]
            if missing:
                raise AuditError(f"{name}: missing CommandButtons {missing}")
            commandset_checks.append({
                "name":name,
                "buttons":refs,
            })

        ocl_checks=[]
        for name in sorted(EXPECTED_OCLS):
            d=by_name[name][0]
            object_names=[]
            for line in d.body.splitlines():
                m=re.match(
                    r"^\s*ObjectNames\s*=\s*([A-Za-z_][A-Za-z0-9_]*)",
                    line
                )
                if m:
                    object_names.append(m.group(1))
            missing=[x for x in object_names if x not in objects]
            if missing:
                raise AuditError(f"{name}: missing created objects {missing}")
            ocl_checks.append({
                "name":name,
                "object_names":object_names,
            })

        report={
            "status":"ok",
            "commandsets":commandset_checks,
            "ocls":ocl_checks,
            "added_commandset_count":len(commandset_checks),
            "added_ocl_count":len(ocl_checks),
        }
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        print(
            "OK: all-factions structural additions verified; "
            f"{len(commandset_checks)} CommandSets, {len(ocl_checks)} OCLs"
        )
        return 0
    except (AuditError,OSError,ValueError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
