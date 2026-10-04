#!/usr/bin/env python3
"""Read-only audit of the Russian Topol/ICBM activation chain."""

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

TOPOL = "RussiaVehicleTopol"
TOPOL_BASE_CS = "RussiaVehicleTopolCommandSet"
TOPOL_ARMED_CS = "RussiaVehicleTopolUpgradedCommandSet"
FIRE_BUTTON = "Command_TacticalNuclearStrike"
REARM_BUTTON = "Command_UpgradeRussiaRearmICBM"
ICBM_SCIENCE = "SCIENCE_ICBMClearance"
ICBM_PURCHASE = "Command_PurchaseScienceICBMClearance"
REARM_UPGRADE = "Upgrade_RussiaTopolMIRVMissileUpgrade"
TOPOL_WEAPON = "TopolMissileWeapon"
TOPOL_PROJECTILE = "TopolMissile"
TOPOL_REARM_OCL = "OCL_TopolMirvWareheadUpgrade"


def fields(body: str) -> dict[str, list[str]]:
    clean = strip_comments(body)
    out: dict[str, list[str]] = defaultdict(list)
    for key, value in re.findall(
        r"(?mi)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\r\n;]+)",
        clean,
    ):
        out[key].append(value.strip())
    return dict(out)


def one(field_map: dict[str, list[str]], key: str):
    vals = field_map.get(key, [])
    return vals[0] if vals else None


def commandset_buttons(body: str) -> list[str]:
    clean = strip_comments(body)
    result = []
    for line in clean.splitlines():
        m = re.match(r"^\s*\d+\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            result.append(m.group(1))
    return result


def weapon_for_rider(body: str, rider: str, slot: str) -> str | None:
    clean = strip_comments(body)
    blocks = re.split(r"(?mi)^\s*WeaponSet\s*$", clean)
    for block in blocks[1:]:
        # block ends at top-level End but the useful lines occur before it.
        cond = re.search(r"(?mi)^\s*Conditions\s*=\s*([^\r\n]+)", block)
        if not cond or rider.upper() not in cond.group(1).upper():
            continue
        for line in block.splitlines():
            m = re.match(
                rf"^\s*Weapon\s*=\s*{re.escape(slot)}\s+([A-Za-z_][A-Za-z0-9_]*)",
                line,
                re.I,
            )
            if m:
                return m.group(1)
    return None


def collect_by_name(definitions):
    by_name = defaultdict(list)
    for d in definitions:
        by_name[d.name].append(d)
    return by_name


def unique(by_name, name: str, kind: str):
    defs = [d for d in by_name.get(name, []) if d.kind == kind]
    if len(defs) != 1:
        raise AuditError(f"Expected one {kind} {name}, found {len(defs)}")
    return defs[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("ci-out/topol"))
    args = ap.parse_args()

    try:
        definitions = []
        for archive in args.archives:
            defs, _ = parse_definitions(archive)
            definitions.extend(defs)
        by_name = collect_by_name(definitions)

        topol = unique(by_name, TOPOL, "Object")
        base_cs = unique(by_name, TOPOL_BASE_CS, "CommandSet")
        armed_cs = unique(by_name, TOPOL_ARMED_CS, "CommandSet")
        fire_btn = unique(by_name, FIRE_BUTTON, "CommandButton")
        rearm_btn = unique(by_name, REARM_BUTTON, "CommandButton")
        science = unique(by_name, ICBM_SCIENCE, "Science")
        purchase = unique(by_name, ICBM_PURCHASE, "CommandButton")
        rearm_upgrade = unique(by_name, REARM_UPGRADE, "Upgrade")
        weapon = unique(by_name, TOPOL_WEAPON, "Weapon")
        projectile = unique(by_name, TOPOL_PROJECTILE, "Object")
        rearm_ocl = unique(by_name, TOPOL_REARM_OCL, "ObjectCreationList")

        topol_clean = strip_comments(topol.body)
        topol_fields = fields(topol.body)
        fire_fields = fields(fire_btn.body)
        rearm_fields = fields(rearm_btn.body)
        upgrade_fields = fields(rearm_upgrade.body)
        science_fields = fields(science.body)

        prerequisite_sciences = re.findall(
            r"(?mi)^\s*Science\s*=\s*([A-Za-z_][A-Za-z0-9_]*)",
            topol_clean,
        )
        prerequisite_objects = re.findall(
            r"(?mi)^\s*Object\s*=\s*([A-Za-z_][A-Za-z0-9_]*)",
            topol_clean,
        )

        base_buttons = commandset_buttons(base_cs.body)
        armed_buttons = commandset_buttons(armed_cs.body)

        active_commandset_refs = []
        for d in definitions:
            if d.kind != "CommandSet":
                continue
            buttons = commandset_buttons(d.body)
            if ICBM_PURCHASE in buttons:
                active_commandset_refs.append(
                    {"commandset": d.name, "path": d.path, "line": d.start_line}
                )

        raw_purchase_mentions = []
        for d in definitions:
            if d.kind == "CommandSet" and ICBM_PURCHASE in d.body:
                raw_purchase_mentions.append(
                    {
                        "commandset": d.name,
                        "path": d.path,
                        "line": d.start_line,
                        "active": ICBM_PURCHASE in commandset_buttons(d.body),
                    }
                )

        rider_lines = [
            line.strip()
            for line in topol_clean.splitlines()
            if re.match(r"^\s*Rider[12]\s*=", line, re.I)
        ]

        object_upgrade_blocks = []
        clean_lines = topol_clean.splitlines()
        for idx, line in enumerate(clean_lines):
            if re.match(r"^\s*Behavior\s*=\s*ObjectCreationUpgrade\b", line):
                block = [line]
                for following in clean_lines[idx + 1:]:
                    block.append(following)
                    if re.match(r"^\s*End\s*$", following):
                        break
                text = "\n".join(block)
                if REARM_UPGRADE in text or TOPOL_REARM_OCL in text:
                    object_upgrade_blocks.append(text)

        findings = []

        if ICBM_SCIENCE in prerequisite_sciences and not active_commandset_refs:
            findings.append(
                {
                    "severity": "critical",
                    "code": "ICBM_CLEARANCE_UNPURCHASABLE",
                    "detail": (
                        f"{TOPOL} requires {ICBM_SCIENCE}, but "
                        f"{ICBM_PURCHASE} is not active in any CommandSet."
                    ),
                }
            )

        if raw_purchase_mentions and not active_commandset_refs:
            findings.append(
                {
                    "severity": "high",
                    "code": "ICBM_PURCHASE_BUTTON_COMMENTED_OUT",
                    "detail": (
                        f"{ICBM_PURCHASE} is present textually in a science CommandSet "
                        "but only inside comments."
                    ),
                    "mentions": raw_purchase_mentions,
                }
            )

        rider1_weapon = weapon_for_rider(topol.body, "WEAPON_RIDER1", "SECONDARY")
        rider2_weapon = weapon_for_rider(topol.body, "WEAPON_RIDER2", "SECONDARY")

        if FIRE_BUTTON in base_buttons and (rider1_weapon is None or rider1_weapon.upper() == "NONE"):
            findings.append(
                {
                    "severity": "high",
                    "code": "FIRE_BUTTON_VISIBLE_WHILE_TOPOL_UNARMED",
                    "detail": (
                        f"{TOPOL_BASE_CS} exposes {FIRE_BUTTON}, while the initial "
                        "WEAPON_RIDER1 SECONDARY slot is NONE."
                    ),
                }
            )

        build_time = one(upgrade_fields, "BuildTime")
        build_cost = one(upgrade_fields, "BuildCost")
        try:
            build_time_seconds = float(build_time) if build_time is not None else None
        except ValueError:
            build_time_seconds = None
        if build_time_seconds is not None and build_time_seconds >= 300:
            findings.append(
                {
                    "severity": "medium",
                    "code": "TOPOL_REARM_EXTREMELY_LONG",
                    "detail": (
                        f"{REARM_UPGRADE} takes {build_time_seconds:g} seconds "
                        f"and costs {build_cost}; this can look like activation is stuck."
                    ),
                }
            )

        dependency_checks = {
            "topol_object": True,
            "base_commandset": True,
            "armed_commandset": True,
            "fire_button": True,
            "rearm_button": True,
            "icbm_science": True,
            "icbm_purchase_button": True,
            "rearm_upgrade": True,
            "missile_weapon": True,
            "missile_projectile": True,
            "rearm_ocl": True,
            "base_has_fire_button": FIRE_BUTTON in base_buttons,
            "base_has_rearm_button": REARM_BUTTON in base_buttons,
            "armed_has_fire_button": FIRE_BUTTON in armed_buttons,
            "rearm_button_targets_upgrade": one(rearm_fields, "Upgrade") == REARM_UPGRADE,
            "fire_button_uses_secondary": one(fire_fields, "WeaponSlot") == "SECONDARY",
            "topol_requires_icbm_science": ICBM_SCIENCE in prerequisite_sciences,
            "icbm_purchase_is_active_somewhere": bool(active_commandset_refs),
            "rider1_secondary": rider1_weapon,
            "rider2_secondary": rider2_weapon,
            "rider2_weapon_correct": rider2_weapon == TOPOL_WEAPON,
            "rearm_object_upgrade_block_found": bool(object_upgrade_blocks),
        }

        report = {
            "status": "ok",
            "topol": {
                "path": topol.path,
                "line": topol.start_line,
                "prerequisite_sciences": prerequisite_sciences,
                "prerequisite_objects": prerequisite_objects,
                "rider_lines": rider_lines,
                "rider1_secondary_weapon": rider1_weapon,
                "rider2_secondary_weapon": rider2_weapon,
            },
            "commandsets": {
                "base": {"name": TOPOL_BASE_CS, "buttons": base_buttons},
                "armed": {"name": TOPOL_ARMED_CS, "buttons": armed_buttons},
            },
            "science": {
                "name": ICBM_SCIENCE,
                "path": science.path,
                "line": science.start_line,
                "fields": science_fields,
                "purchase_button": ICBM_PURCHASE,
                "active_commandset_refs": active_commandset_refs,
                "raw_commandset_mentions": raw_purchase_mentions,
            },
            "rearm": {
                "button": REARM_BUTTON,
                "upgrade": REARM_UPGRADE,
                "build_time": build_time,
                "build_cost": build_cost,
                "object_upgrade_blocks": object_upgrade_blocks,
            },
            "weapon_chain": {
                "weapon": TOPOL_WEAPON,
                "projectile": TOPOL_PROJECTILE,
                "rearm_ocl": TOPOL_REARM_OCL,
                "weapon_path": weapon.path,
                "projectile_path": projectile.path,
                "ocl_path": rearm_ocl.path,
            },
            "dependency_checks": dependency_checks,
            "findings": findings,
        }

        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "topol-activation-audit.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        lines = [
            "# Russian Topol / ICBM Activation Audit",
            "",
            f"Topol source: {topol.path}:{topol.start_line}",
            "",
            "## Activation chain",
            "",
            f"1. Build prerequisite science: {ICBM_SCIENCE}",
            f"2. Purchase button: {ICBM_PURCHASE}",
            f"3. Initial command set: {TOPOL_BASE_CS}",
            f"4. Rearm button: {REARM_BUTTON}",
            f"5. Rearm upgrade: {REARM_UPGRADE}",
            f"6. Armed command set: {TOPOL_ARMED_CS}",
            f"7. Fire button: {FIRE_BUTTON}",
            f"8. Weapon: {TOPOL_WEAPON}",
            f"9. Projectile: {TOPOL_PROJECTILE}",
            "",
            "## Findings",
            "",
        ]
        for f in findings:
            lines.append(f"- **{f['severity'].upper()} — {f['code']}**: {f['detail']}")

        lines.extend(
            [
                "",
                "## Key facts",
                "",
                f"- Initial SECONDARY weapon: {rider1_weapon}",
                f"- Armed SECONDARY weapon: {rider2_weapon}",
                f"- Rearm BuildTime: {build_time} seconds",
                f"- Rearm BuildCost: {build_cost}",
                f"- ICBM purchase button active in any CommandSet: {bool(active_commandset_refs)}",
                "",
                "## Raw science CommandSet mentions",
                "",
            ]
        )
        if raw_purchase_mentions:
            for item in raw_purchase_mentions:
                lines.append(
                    f"- {item['commandset']} at {item['path']}:{item['line']} "
                    f"(active={item['active']})"
                )
        else:
            lines.append("- None")

        (args.out / "topol-activation-audit.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

        print(
            "OK: Topol activation audit: "
            f"{len(findings)} findings; "
            f"active ICBM purchase refs={len(active_commandset_refs)}"
        )
        for f in findings:
            print(f"{f['severity'].upper()}: {f['code']}: {f['detail']}")
        return 0

    except (AuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
