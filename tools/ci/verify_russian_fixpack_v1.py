#!/usr/bin/env python3
"""Static integration verifier for Russian Fix Pack V1."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError, parse_big
from russia_dependency_map import build_graph, parse_definitions

COMMANDSET_PATH = "Data\\INI\\CommandSet.ini"
UPGRADE_PATH = "Data\\INI\\Upgrade.ini"
LOCOMOTOR_PATH = "Data\\INI\\Locomotor.ini"
SYSTEM_PATH = "Data\\INI\\Object\\Russia\\RussiaSystemObjects.ini"

SVU = "RussianInfantrySVUSniperCommandSet"
SVU_OBJECT = "RussiaInfantrySVUSniper"
SVU_EXPECTED = {
    7: "Command_RussiaCallinGrizonAirdrop",
    15: "Command_AttackMove",
    17: "Command_Guard",
    18: "Command_Stop",
}

TOPOL_SCIENCE_CS = "SCIENCE_Russia_CommandSetRank8"
TOPOL_BASE_CS = "RussiaVehicleTopolCommandSet"
TOPOL_ARMED_CS = "RussiaVehicleTopolUpgradedCommandSet"
ICBM_BUTTON = "Command_PurchaseScienceICBMClearance"
FIRE_BUTTON = "Command_TacticalNuclearStrike"
REARM_UPGRADE = "Upgrade_RussiaTopolMIRVMissileUpgrade"
SHADOW_OBJECTS = (
    "TopolWarheadReentryObject",
    "RussianTacticalNukeStrikeWarningDecal",
)

EXPECTED_LOCOMOTORS = {
    "SentinelTankLocomotor": {
        "TurnRate": "40",
        "TurnRateDamaged": "35",
        "Acceleration": "35",
        "AccelerationDamaged": "30",
        "Braking": "65",
    },
    "GolemLocomotor": {
        "TurnRate": "45",
        "TurnRateDamaged": "40",
        "Acceleration": "40",
        "AccelerationDamaged": "35",
        "Braking": "65",
    },
    "KodiakTankLocomotor": {
        "TurnRate": "50",
        "TurnRateDamaged": "45",
    },
    "BuratinoLocomotor": {
        "Speed": "43",
        "SpeedDamaged": "27",
        "TurnRate": "52",
        "TurnRateDamaged": "48",
    },
    "ScudLauncherLocomotor": {
        "Speed": "23",
        "SpeedDamaged": "17",
        "TurnRate": "35",
        "TurnRateDamaged": "30",
        "Braking": "65",
        "MinTurnSpeed": "0",
    },
    "TopolLocomotor": {
        "Speed": "28",
        "SpeedDamaged": "22",
        "TurnRate": "35",
        "TurnRateDamaged": "30",
        "Acceleration": "65",
        "AccelerationDamaged": "55",
        "Braking": "65",
        "MinTurnSpeed": "0",
    },
    "MSTALocomotor": {
        "Speed": "35",
        "SpeedDamaged": "32",
        "TurnRate": "45",
    },
}


def norm(s: str) -> str:
    return s.replace("\\", "/").lower()


def read_entry(path: Path, target: str) -> str:
    raw = path.read_bytes()
    _meta, entries, _warnings = parse_big(path)
    hits = [e for e in entries if norm(e.name) == norm(target)]
    if len(hits) != 1:
        raise AuditError(f"expected one {target}, found {len(hits)}")
    e = hits[0]
    return raw[e.offset:e.offset + e.size].decode("latin-1")


def find_block(text: str, kind: str, name: str) -> str:
    start_re = re.compile(
        rf"(?mi)^\s*{re.escape(kind)}\s+{re.escape(name)}(?:\s*;[^\r\n]*)?\s*$"
    )
    hits = list(start_re.finditer(text))
    if len(hits) != 1:
        raise AuditError(f"expected one {kind} {name}, found {len(hits)}")
    tail = text[hits[0].end():]
    end_m = re.search(r"(?mi)^\s*End\s*$", tail)
    if not end_m:
        raise AuditError(f"unterminated {kind} {name}")
    return text[hits[0].start(): hits[0].end() + end_m.end()]


def active_buttons(block: str) -> dict[int, str]:
    out = {}
    for line in block.splitlines():
        stripped = line.lstrip(" \t")
        if stripped.startswith(";"):
            continue
        m = re.match(r"^(\d+)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if m:
            out[int(m.group(1))] = m.group(2)
    return out


def field(block: str, name: str) -> str | None:
    m = re.search(
        rf"(?mi)^\s*{re.escape(name)}\s*=\s*([^;\r\n]+)", block
    )
    return m.group(1).strip() if m else None


def verify(archive: Path) -> dict:
    commandsets = read_entry(archive, COMMANDSET_PATH)
    upgrades = read_entry(archive, UPGRADE_PATH)
    locomotors = read_entry(archive, LOCOMOTOR_PATH)
    systems = read_entry(archive, SYSTEM_PATH)

    checks = []

    # SVU command set.
    svu_block = find_block(commandsets, "CommandSet", SVU)
    svu_slots = active_buttons(svu_block)
    if svu_slots != SVU_EXPECTED:
        raise AuditError(f"SVU CommandSet slots mismatch: {svu_slots}")
    checks.append("SVU CommandSet restored with audited four-slot baseline")

    defs, _ = parse_definitions(archive)
    _nodes, edges, unresolved = build_graph(defs)
    if not any(
        e.source == SVU_OBJECT and e.target == SVU and e.relation == "command-set"
        for e in edges
    ):
        raise AuditError("SVU object does not resolve to restored CommandSet")
    if any(
        x["source"] == SVU_OBJECT and x["target"] == SVU
        for x in unresolved
    ):
        raise AuditError("SVU CommandSet is still unresolved")
    checks.append("SVU object -> CommandSet dependency resolves")

    # Topol science + armed/unarmed command flow.
    science = active_buttons(find_block(commandsets, "CommandSet", TOPOL_SCIENCE_CS))
    if ICBM_BUTTON not in science.values():
        raise AuditError("ICBM Clearance purchase button is not active")
    checks.append("ICBM Clearance purchase button is active")

    base = active_buttons(find_block(commandsets, "CommandSet", TOPOL_BASE_CS))
    armed = active_buttons(find_block(commandsets, "CommandSet", TOPOL_ARMED_CS))
    if FIRE_BUTTON in base.values():
        raise AuditError("unarmed Topol still exposes nuclear fire command")
    if FIRE_BUTTON not in armed.values():
        raise AuditError("armed Topol lost nuclear fire command")
    checks.append("Topol fire button only appears in armed CommandSet")

    rearm = find_block(upgrades, "Upgrade", REARM_UPGRADE)
    if field(rearm, "BuildTime") != "180.0":
        raise AuditError(f"Topol rearm BuildTime={field(rearm, 'BuildTime')}")
    if field(rearm, "BuildCost") != "5000":
        raise AuditError(f"Topol rearm BuildCost={field(rearm, 'BuildCost')}")
    checks.append("Topol rearm is 180s and cost remains 5000")

    # Mobility V1 + Heavy Launchers V2.
    for loco, expected_fields in EXPECTED_LOCOMOTORS.items():
        block = find_block(locomotors, "Locomotor", loco)
        for key, expected in expected_fields.items():
            actual = field(block, key)
            if actual != expected:
                raise AuditError(f"{loco}.{key}: expected {expected}, got {actual}")
    checks.append("Mobility V1 + Heavy Launchers Speed V2 values verified")

    # Darkening fix: preserve timing/geometry but remove active giant shadows.
    for obj in SHADOW_OBJECTS:
        block = find_block(systems, "Object", obj)
        if field(block, "GeometryMajorRadius") != "800.0":
            raise AuditError(f"{obj}: GeometryMajorRadius changed")
        if field(block, "GeometryMinorRadius") != "800.0":
            raise AuditError(f"{obj}: GeometryMinorRadius changed")
        active_shadow = re.search(
            r"(?mi)^\s*Shadow\s*=\s*SHADOW_VOLUME\s*$", block
        )
        if active_shadow:
            raise AuditError(f"{obj}: giant SHADOW_VOLUME still active")

    reentry = find_block(systems, "Object", "TopolWarheadReentryObject")
    warning = find_block(systems, "Object", "RussianTacticalNukeStrikeWarningDecal")
    if field(reentry, "MinLifetime") != "15000" or field(reentry, "MaxLifetime") != "15000":
        raise AuditError("Topol reentry lifetime changed")
    if field(warning, "MinLifetime") != "12500" or field(warning, "MaxLifetime") != "12500":
        raise AuditError("Topol warning decal lifetime changed")
    checks.append("Giant Topol shadow volumes disabled; geometry/timing preserved")

    return {
        "status": "ok",
        "checks": checks,
        "svu_slots": {str(k): v for k, v in svu_slots.items()},
        "topol": {
            "icbm_clearance_active": True,
            "unarmed_fire_button": False,
            "armed_fire_button": True,
            "rearm_time": "180.0",
            "rearm_cost": "5000",
        },
        "darkening": {
            "objects": list(SHADOW_OBJECTS),
            "shadow_volume_active": False,
            "geometry_preserved": "800x800",
            "lifetimes_preserved_ms": {
                "TopolWarheadReentryObject": 15000,
                "RussianTacticalNukeStrikeWarningDecal": 12500,
            },
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        report = verify(args.archive)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"OK: Russian Fix Pack V1 integration verification passed ({len(report['checks'])} checks)")
        for item in report["checks"]:
            print("CHECK:", item)
        return 0
    except (AuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
