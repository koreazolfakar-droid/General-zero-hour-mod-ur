#!/usr/bin/env python3
"""Read-only audit for Russian ground-vehicle mobility, formation and armor-upgrade wiring."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError
from russia_dependency_map import Definition, parse_definitions, strip_comments

RUSSIA_VEHICLE_PATH = "/object/russia/vehicles/"
RUSSIA_DEFENCE_PATH = "/object/russia/defences/"
LOC_FIELDS = (
    "Speed",
    "SpeedDamaged",
    "MinSpeed",
    "TurnRate",
    "TurnRateDamaged",
    "Acceleration",
    "AccelerationDamaged",
    "Braking",
    "MinTurnSpeed",
    "TurnPivotOffset",
    "WanderWidthFactor",
    "WanderLengthFactor",
    "CloseEnoughDist",
    "CloseEnoughDist3D",
)
GEOMETRY_FIELDS = (
    "Geometry",
    "GeometryMajorRadius",
    "GeometryMinorRadius",
    "GeometryHeight",
    "GeometryIsSmall",
    "ShadowSizeX",
    "ShadowSizeY",
)
OBJECT_FIELDS = (
    "CrusherLevel",
    "CrushableLevel",
    "BuildCost",
    "BuildTime",
    "VisionRange",
    "ShroudClearingRange",
)

ASSIGN_RE = re.compile(
    r"(?mi)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;\r\n]+)"
)
LOCOMOTOR_USE_RE = re.compile(
    r"(?mi)^\s*Locomotor\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
ARMORSET_RE = re.compile(
    r"(?mis)^\s*ArmorSet\b(?P<body>.*?)(?=^\s*End\s*$)"
)
BEHAVIOR_RE = re.compile(
    r"(?mis)^\s*Behavior\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)(?P<body>.*?)(?=^\s*End\s*$)"
)
KINDOF_RE = re.compile(r"(?mi)^\s*KindOf\s*=\s*([^;\r\n]+)")


@dataclass
class MobilityRow:
    object_name: str
    path: str
    line: int
    kindof: list[str]
    locomotors: list[dict]
    geometry: dict
    object_fields: dict
    armor_sets: list[dict]
    upgrade_behaviors: list[dict]
    suspicious_lines: list[dict]


def scalar(value: str):
    v = value.strip()
    if not v:
        return ""
    low = v.lower()
    if low in {"yes", "true"}:
        return True
    if low in {"no", "false"}:
        return False
    try:
        if re.fullmatch(r"[-+]?\d+", v):
            return int(v)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", v):
            return float(v)
    except ValueError:
        pass
    return v


def assignments(body: str) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for key, value in ASSIGN_RE.findall(strip_comments(body)):
        out[key].append(scalar(value.strip()))
    return dict(out)


def first(assigns: dict[str, list], key: str):
    vals = assigns.get(key, [])
    return vals[0] if vals else None


def parse_kindof(body: str) -> list[str]:
    m = KINDOF_RE.search(strip_comments(body))
    if not m:
        return []
    return [x for x in re.split(r"\s+", m.group(1).strip()) if x]


def parse_locomotor_uses(body: str) -> list[dict]:
    result = []
    for state, name in LOCOMOTOR_USE_RE.findall(strip_comments(body)):
        result.append({"state": state, "name": name})
    return result


def parse_armor_sets(body: str) -> list[dict]:
    out = []
    clean = strip_comments(body)
    for match in ARMORSET_RE.finditer(clean):
        block = match.group(0)
        a = assignments(block)
        out.append(
            {
                "conditions": first(a, "Conditions"),
                "armor": first(a, "Armor"),
                "damage_fx": first(a, "DamageFX"),
            }
        )
    return out


def parse_upgrade_behaviors(body: str) -> list[dict]:
    out = []
    clean = strip_comments(body)
    for match in BEHAVIOR_RE.finditer(clean):
        behavior_type = match.group(1)
        tag = match.group(2)
        block = match.group(0)
        if "Upgrade" not in behavior_type and not re.search(r"(?i)upgrade|armor|replaceobject", block):
            continue
        a = assignments(block)
        interesting = {}
        for key in (
            "TriggeredBy",
            "ConflictsWith",
            "RequiresAllTriggers",
            "Upgrade",
            "Science",
            "ReplaceObject",
            "ReplacementObject",
            "ReplacementObjectName",
            "Armor",
            "ArmorSetFlag",
            "ModelCondition",
            "WeaponSetFlags",
        ):
            vals = a.get(key)
            if vals:
                interesting[key] = vals
        out.append(
            {
                "type": behavior_type,
                "tag": tag,
                "fields": interesting,
                "text": block.strip(),
            }
        )
    return out


def numeric_fields(defn: Definition) -> dict:
    a = assignments(defn.body)
    out = {}
    for key in LOC_FIELDS:
        value = first(a, key)
        if isinstance(value, (int, float)):
            out[key] = float(value)
        elif value is not None:
            out[key] = value
    out["Surfaces"] = first(a, "Surfaces")
    out["Appearance"] = first(a, "Appearance")
    out["StickToGround"] = first(a, "StickToGround")
    return out


def median(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.median(values)


def ratio_flag(value: float | None, reference: float | None, low: float, high: float) -> bool:
    if value is None or reference in (None, 0):
        return False
    ratio = value / reference
    return ratio < low or ratio > high


def build_report(definitions: list[Definition]) -> dict:
    by_name: dict[str, list[Definition]] = defaultdict(list)
    for d in definitions:
        by_name[d.name].append(d)

    locomotors = {
        d.name: d
        for d in definitions
        if d.kind == "Locomotor"
    }

    rows: list[MobilityRow] = []
    for d in definitions:
        normalized = d.path.replace("\\", "/").lower()
        if d.kind != "Object":
            continue
        if RUSSIA_VEHICLE_PATH not in normalized and RUSSIA_DEFENCE_PATH not in normalized:
            continue

        kindof = parse_kindof(d.body)
        uses = parse_locomotor_uses(d.body)
        # Keep mobile ground objects and movable vehicle-like objects.
        if not uses and not any(k in kindof for k in ("VEHICLE", "CAN_ATTACK", "TRANSPORT")):
            continue

        a = assignments(d.body)
        geometry = {k: first(a, k) for k in GEOMETRY_FIELDS if first(a, k) is not None}
        object_fields = {k: first(a, k) for k in OBJECT_FIELDS if first(a, k) is not None}

        suspicious_lines = []
        for idx, line in enumerate(d.body.splitlines(), start=d.start_line):
            if re.search(r"(?i)(armor|upgrade|replaceobject|locomotor|geometry|crusher|formation|pathfind)", line):
                suspicious_lines.append({"line": idx, "text": line.rstrip()})

        row = MobilityRow(
            object_name=d.name,
            path=d.path,
            line=d.start_line,
            kindof=kindof,
            locomotors=uses,
            geometry=geometry,
            object_fields=object_fields,
            armor_sets=parse_armor_sets(d.body),
            upgrade_behaviors=parse_upgrade_behaviors(d.body),
            suspicious_lines=suspicious_lines,
        )
        rows.append(row)

    used_locomotor_names = sorted(
        {use["name"] for row in rows for use in row.locomotors}
    )

    loc_rows = []
    for name in used_locomotor_names:
        defs = by_name.get(name, [])
        loc_def = next((d for d in defs if d.kind == "Locomotor"), None)
        if not loc_def:
            loc_rows.append(
                {
                    "name": name,
                    "defined": False,
                    "path": None,
                    "line": None,
                    "fields": {},
                }
            )
            continue
        loc_rows.append(
            {
                "name": name,
                "defined": True,
                "path": loc_def.path,
                "line": loc_def.start_line,
                "fields": numeric_fields(loc_def),
            }
        )

    # Compute fleet medians from normal locomotors.
    normal_loc_names = []
    for row in rows:
        for use in row.locomotors:
            if use["state"].upper() == "SET_NORMAL":
                normal_loc_names.append(use["name"])
    normal_loc_names = sorted(set(normal_loc_names))
    normal_defs = [
        next((d for d in by_name.get(name, []) if d.kind == "Locomotor"), None)
        for name in normal_loc_names
    ]
    normal_defs = [d for d in normal_defs if d is not None]
    numeric_by_name = {d.name: numeric_fields(d) for d in normal_defs}

    speed_med = median([
        v["Speed"] for v in numeric_by_name.values()
        if isinstance(v.get("Speed"), (int, float))
    ])
    turn_med = median([
        v["TurnRate"] for v in numeric_by_name.values()
        if isinstance(v.get("TurnRate"), (int, float))
    ])
    accel_med = median([
        v["Acceleration"] for v in numeric_by_name.values()
        if isinstance(v.get("Acceleration"), (int, float))
    ])
    brake_med = median([
        v["Braking"] for v in numeric_by_name.values()
        if isinstance(v.get("Braking"), (int, float))
    ])

    findings = []
    for row in rows:
        normal = next(
            (u for u in row.locomotors if u["state"].upper() == "SET_NORMAL"),
            None,
        )
        if normal:
            fields = numeric_by_name.get(normal["name"], {})
            speed = fields.get("Speed")
            turn = fields.get("TurnRate")
            accel = fields.get("Acceleration")
            brake = fields.get("Braking")

            if ratio_flag(speed, speed_med, 0.60, 1.80):
                findings.append({
                    "severity": "medium",
                    "category": "speed-outlier",
                    "object": row.object_name,
                    "locomotor": normal["name"],
                    "value": speed,
                    "fleet_median": speed_med,
                })
            if ratio_flag(turn, turn_med, 0.55, 1.80):
                findings.append({
                    "severity": "high" if isinstance(turn, (int, float)) and turn < (turn_med or 0) * 0.55 else "medium",
                    "category": "turn-rate-outlier",
                    "object": row.object_name,
                    "locomotor": normal["name"],
                    "value": turn,
                    "fleet_median": turn_med,
                })
            if ratio_flag(accel, accel_med, 0.40, 2.50):
                findings.append({
                    "severity": "medium",
                    "category": "acceleration-outlier",
                    "object": row.object_name,
                    "locomotor": normal["name"],
                    "value": accel,
                    "fleet_median": accel_med,
                })
            if ratio_flag(brake, brake_med, 0.40, 2.50):
                findings.append({
                    "severity": "medium",
                    "category": "braking-outlier",
                    "object": row.object_name,
                    "locomotor": normal["name"],
                    "value": brake,
                    "fleet_median": brake_med,
                })

            if isinstance(speed, (int, float)) and isinstance(turn, (int, float)) and speed > 0:
                turn_per_speed = turn / speed
                if turn_per_speed < 1.20:
                    findings.append({
                        "severity": "high",
                        "category": "low-turn-authority",
                        "object": row.object_name,
                        "locomotor": normal["name"],
                        "turn_per_speed": round(turn_per_speed, 3),
                        "speed": speed,
                        "turn_rate": turn,
                    })

        major = row.geometry.get("GeometryMajorRadius")
        minor = row.geometry.get("GeometryMinorRadius")
        if isinstance(major, (int, float)) and isinstance(minor, (int, float)):
            if max(major, minor) >= 30:
                findings.append({
                    "severity": "medium",
                    "category": "large-collision-footprint",
                    "object": row.object_name,
                    "major_radius": major,
                    "minor_radius": minor,
                })

        for behavior in row.upgrade_behaviors:
            if behavior["type"] == "ReplaceObjectUpgrade" or "ReplaceObject" in behavior["text"]:
                findings.append({
                    "severity": "high",
                    "category": "replace-object-upgrade",
                    "object": row.object_name,
                    "behavior": behavior["type"],
                    "fields": behavior["fields"],
                })

        if len(row.armor_sets) > 1:
            findings.append({
                "severity": "info",
                "category": "multiple-armor-sets",
                "object": row.object_name,
                "armor_sets": row.armor_sets,
            })

    missing_locomotors = [x for x in loc_rows if not x["defined"]]
    for item in missing_locomotors:
        findings.append({
            "severity": "critical",
            "category": "missing-locomotor",
            "locomotor": item["name"],
        })

    replace_edges = []
    for row in rows:
        for behavior in row.upgrade_behaviors:
            fields = behavior["fields"]
            replacements = []
            for key in ("ReplaceObject", "ReplacementObject", "ReplacementObjectName"):
                for value in fields.get(key, []):
                    if isinstance(value, str):
                        replacements.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", value))
            for target in replacements:
                replace_edges.append({
                    "source": row.object_name,
                    "target": target,
                    "behavior": behavior["type"],
                    "target_defined": target in by_name,
                })

    report = {
        "status": "ok",
        "summary": {
            "russian_ground_objects": len(rows),
            "used_locomotors": len(used_locomotor_names),
            "missing_locomotors": len(missing_locomotors),
            "upgrade_replacement_edges": len(replace_edges),
            "findings": len(findings),
        },
        "fleet_medians": {
            "Speed": speed_med,
            "TurnRate": turn_med,
            "Acceleration": accel_med,
            "Braking": brake_med,
        },
        "objects": [
            {
                "object": r.object_name,
                "path": r.path,
                "line": r.line,
                "kindof": r.kindof,
                "locomotors": r.locomotors,
                "geometry": r.geometry,
                "object_fields": r.object_fields,
                "armor_sets": r.armor_sets,
                "upgrade_behaviors": r.upgrade_behaviors,
                "suspicious_lines": r.suspicious_lines,
            }
            for r in sorted(rows, key=lambda x: x.object_name)
        ],
        "locomotors": loc_rows,
        "replacement_edges": replace_edges,
        "findings": sorted(
            findings,
            key=lambda x: (
                {"critical": 0, "high": 1, "medium": 2, "info": 3}.get(x["severity"], 9),
                x.get("object", ""),
                x["category"],
            ),
        ),
    }
    return report


def write_reports(report: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "russian-mobility-audit.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    s = report["summary"]
    lines = [
        "# Russian Mobility / Pathfinding Audit",
        "",
        "Read-only static audit of Project X Re Russian ground vehicles.",
        "",
        "## Summary",
        "",
        f"- Russian ground objects audited: **{s['russian_ground_objects']}**",
        f"- Locomotors used: **{s['used_locomotors']}**",
        f"- Missing locomotors: **{s['missing_locomotors']}**",
        f"- Replace-object upgrade edges: **{s['upgrade_replacement_edges']}**",
        f"- Findings: **{s['findings']}**",
        "",
        "## Fleet medians",
        "",
        "| Field | Median |",
        "|---|---:|",
    ]
    for key, value in report["fleet_medians"].items():
        lines.append(f"| {key} | {value if value is not None else '—'} |")

    lines.extend([
        "",
        "## High-priority findings",
        "",
        "| Severity | Category | Object / Locomotor | Details |",
        "|---|---|---|---|",
    ])
    for f in report["findings"]:
        if f["severity"] not in {"critical", "high"}:
            continue
        name = f.get("object") or f.get("locomotor") or "—"
        details = ", ".join(
            f"{k}={v}"
            for k, v in f.items()
            if k not in {"severity", "category", "object", "locomotor"}
        )
        lines.append(
            f"| {f['severity']} | {f['category']} | {name} | {details} |"
        )

    lines.extend([
        "",
        "## Vehicle mobility table",
        "",
        "| Object | Normal Locomotor | Geometry | Armor sets | Upgrade behaviors |",
        "|---|---|---|---:|---:|",
    ])
    for obj in report["objects"]:
        normal = next(
            (u["name"] for u in obj["locomotors"] if u["state"].upper() == "SET_NORMAL"),
            "—",
        )
        geom = ", ".join(f"{k}={v}" for k, v in obj["geometry"].items()) or "—"
        lines.append(
            f"| {obj['object']} | {normal} | {geom} | "
            f"{len(obj['armor_sets'])} | {len(obj['upgrade_behaviors'])} |"
        )

    lines.extend(["", "## Locomotor definitions", ""])
    for loc in report["locomotors"]:
        lines.append(f"### {loc['name']}")
        lines.append("")
        if not loc["defined"]:
            lines.append("**MISSING DEFINITION**")
            lines.append("")
            continue
        lines.append(f"Source: {loc['path']}:{loc['line']}")
        lines.append("")
        lines.append("~~~text")
        for key, value in loc["fields"].items():
            lines.append(f"{key} = {value}")
        lines.append("~~~")
        lines.append("")

    (out / "russian-mobility-audit.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archives", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("ci-out/mobility"))
    args = ap.parse_args()

    try:
        definitions: list[Definition] = []
        for archive in args.archives:
            defs, _ = parse_definitions(archive)
            definitions.extend(defs)

        report = build_report(definitions)
        write_reports(report, args.out)

        s = report["summary"]
        print(
            "OK: Russian mobility audit: "
            f"{s['russian_ground_objects']} objects, "
            f"{s['used_locomotors']} locomotors, "
            f"{s['findings']} findings"
        )
        for f in report["findings"]:
            if f["severity"] in {"critical", "high"}:
                print(
                    "HIGH:",
                    f["category"],
                    f.get("object") or f.get("locomotor") or "",
                    json.dumps(f, ensure_ascii=False),
                )
        return 0
    except (AuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
