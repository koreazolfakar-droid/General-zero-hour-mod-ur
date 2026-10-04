#!/usr/bin/env python3
"""Verify canonical faction identities while preserving Zero Hour legacy slots."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from baseline_audit import AuditError
from russia_dependency_map import parse_definitions, strip_comments, field_values

RANK_FIELDS = (
    "PurchaseScienceCommandSetRank1",
    "PurchaseScienceCommandSetRank3",
    "PurchaseScienceCommandSetRank8",
)

def one(body: str, field: str):
    vals = field_values(strip_comments(body), field)
    return vals[0] if vals else None

def starting_units(body: str) -> list[str]:
    clean = strip_comments(body)
    out = []
    for line in clean.splitlines():
        m = re.match(r"^\s*StartingUnit\d+\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            out.append(m.group(1))
    return out

def verify(archive: Path, manifest_path: Path) -> dict:
    defs, _ = parse_definitions(archive)
    players = {d.name: d for d in defs if d.kind == "PlayerTemplate"}
    all_names = {d.name for d in defs}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    factions = manifest["factions"]

    if len(factions) != 5:
        raise AuditError(f"expected 5 combat factions in manifest, got {len(factions)}")

    canonical_ids = [f["canonical_id"] for f in factions]
    if len(set(canonical_ids)) != len(canonical_ids):
        raise AuditError("duplicate canonical faction IDs in manifest")

    engine_ids = [f["engine_player_template"] for f in factions]
    if len(set(engine_ids)) != len(engine_ids):
        raise AuditError("duplicate engine PlayerTemplate IDs in manifest")

    results = []
    alias_count = 0

    for f in factions:
        engine_id = f["engine_player_template"]
        canonical_id = f["canonical_id"]

        if engine_id not in players:
            raise AuditError(f"missing engine PlayerTemplate {engine_id}")

        d = players[engine_id]
        body = d.body
        actual = {
            "engine_player_template": engine_id,
            "side": one(body, "Side"),
            "base_side": one(body, "BaseSide"),
            "playable_side": one(body, "PlayableSide"),
            "display_name": one(body, "DisplayName"),
            "intrinsic_science": one(body, "IntrinsicSciences"),
            "starting_building": one(body, "StartingBuilding"),
            "science_commandsets": [one(body, field) for field in RANK_FIELDS],
            "special_power_commandset": one(body, "SpecialPowerShortcutCommandSet"),
            "starting_units": starting_units(body),
            "path": d.path,
            "line": d.start_line,
        }

        expected_pairs = {
            "side": f["engine_side"],
            "base_side": f["base_side"],
            "playable_side": "Yes",
            "display_name": f["display_name"],
            "intrinsic_science": f["intrinsic_science"],
            "starting_building": f["starting_building"],
            "special_power_commandset": f["special_power_commandset"],
        }
        for key, expected in expected_pairs.items():
            if actual[key] != expected:
                raise AuditError(
                    f"{canonical_id}: {key} expected {expected}, got {actual[key]}"
                )

        if actual["science_commandsets"] != f["science_commandsets"]:
            raise AuditError(
                f"{canonical_id}: science CommandSets mismatch: "
                f"{actual['science_commandsets']}"
            )

        missing_identity_objects = [
            name for name in f["identity_objects"]
            if name not in actual["starting_units"]
        ]
        if missing_identity_objects:
            raise AuditError(
                f"{canonical_id}: identity objects not spawned at start: "
                f"{missing_identity_objects}"
            )

        if f["starting_building"] not in all_names:
            raise AuditError(
                f"{canonical_id}: starting building object is undefined: "
                f"{f['starting_building']}"
            )
        for name in f["identity_objects"]:
            if name not in all_names:
                raise AuditError(
                    f"{canonical_id}: identity object is undefined: {name}"
                )

        is_alias = engine_id != canonical_id
        if is_alias:
            alias_count += 1
            if "legacy_slot" not in f:
                raise AuditError(
                    f"{canonical_id}: legacy alias has no documented legacy_slot"
                )

        results.append({
            "canonical_id": canonical_id,
            "canonical_name": f["canonical_name"],
            "engine_player_template": engine_id,
            "engine_side": actual["side"],
            "base_side": actual["base_side"],
            "display_name": actual["display_name"],
            "intrinsic_science": actual["intrinsic_science"],
            "starting_building": actual["starting_building"],
            "identity_objects": f["identity_objects"],
            "legacy_slot": f.get("legacy_slot"),
            "uses_legacy_alias": is_alias,
            "source": f"{d.path}:{d.start_line}",
        })

    # Guard the two intentional compatibility aliases. Renaming these directly
    # would break the legacy ZH general slots that maps/skirmish compatibility
    # depend on.
    expected_aliases = {
        "FactionRussia": "FactionAmericaLaserGeneral",
        "FactionEurope": "FactionAmericaSuperWeaponGeneral",
    }
    actual_aliases = {
        r["canonical_id"]: r["engine_player_template"]
        for r in results if r["uses_legacy_alias"]
    }
    if actual_aliases != expected_aliases:
        raise AuditError(
            f"legacy compatibility aliases changed: {actual_aliases}"
        )

    return {
        "status": "ok",
        "policy": manifest["policy"],
        "combat_factions": len(results),
        "legacy_alias_count": alias_count,
        "canonical_factions": results,
        "canonical_lookup": {
            r["engine_player_template"]: r["canonical_id"]
            for r in results
        },
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archive", type=Path)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        report = verify(args.archive, args.manifest)
        args.out.mkdir(parents=True, exist_ok=True)

        (args.out / "faction-identity-audit.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        (args.out / "canonical-faction-lookup.json").write_text(
            json.dumps(report["canonical_lookup"], indent=2) + "\n",
            encoding="utf-8",
        )

        lines = [
            "# Canonical Faction Identity Audit",
            "",
            report["policy"],
            "",
            f"- Combat factions: **{report['combat_factions']}**",
            f"- Intentional legacy engine aliases: **{report['legacy_alias_count']}**",
            "",
            "| Canonical faction | Engine PlayerTemplate | Engine Side | Display | Starting building | Alias? |",
            "|---|---|---|---|---|---|",
        ]
        for f in report["canonical_factions"]:
            lines.append(
                f"| {f['canonical_id']} | {f['engine_player_template']} | "
                f"{f['engine_side']} | {f['display_name']} | "
                f"{f['starting_building']} | {'Yes' if f['uses_legacy_alias'] else 'No'} |"
            )

        lines.extend([
            "",
            "## Compatibility aliases",
            "",
            "- Russia: FactionAmericaLaserGeneral -> FactionRussia",
            "- Europe: FactionAmericaSuperWeaponGeneral -> FactionEurope",
            "",
            "These aliases are intentional compatibility slots. Canonical identity is used by",
            "tooling and future engine adapters; the engine-facing legacy IDs remain stable.",
            "",
        ])

        (args.out / "faction-identity-audit.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )

        print(
            "OK: canonical faction identity audit: "
            f"{report['combat_factions']} factions, "
            f"{report['legacy_alias_count']} intentional legacy aliases"
        )
        for f in report["canonical_factions"]:
            print(
                "FACTION_ID:",
                f["canonical_id"],
                "<-",
                f["engine_player_template"],
                f"side={f['engine_side']}",
                f"display={f['display_name']}",
            )
        return 0
    except (AuditError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
