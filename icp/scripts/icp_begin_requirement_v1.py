#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import icp_entry_v1
import icp_common
import orchestrate_client_project_v1 as orchestrator


class BeginRequirementError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BeginRequirementError("JSON contains duplicate keys")
        result[key] = value
    return result


def _load_json(path: Path, role: str) -> Any:
    resolved = path.expanduser().resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file():
        raise BeginRequirementError(f"{role} must be a regular file")
    try:
        return json.loads(resolved.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except BeginRequirementError:
        raise
    except Exception as exc:
        raise BeginRequirementError(f"{role} is invalid") from exc


def begin(
    *,
    config_path: Path,
    feature_positions_path: Path,
    verified_operation_plan_digest: str,
    batch_id: str | None = None,
) -> dict[str, Any]:
    if len(verified_operation_plan_digest) != 64 or any(
        character not in "0123456789abcdef" for character in verified_operation_plan_digest
    ):
        raise BeginRequirementError("verified operation plan digest must be SHA-256 hex")
    feature_positions = _load_json(feature_positions_path, "feature positions")
    if not isinstance(feature_positions, list) or not feature_positions:
        raise BeginRequirementError("feature positions must be a non-empty array")
    entry = icp_entry_v1.preflight(config_path)
    if entry["status"] != "ready" or entry["unattended_ready"] is not True:
        return {
            "kind": "icp.begin-requirement-result.v1",
            "schema_version": 1,
            "status": entry["status"],
            "prepared": None,
            "entry": entry,
        }
    registries = icp_common.load_registries()
    prepared = orchestrator.prepare_single_requirement_with_entry_gate(
        resolved_config=entry["resolved_config"],
        registries=registries,
        readiness_report=entry["readiness_report"],
        entry_gate_decision=entry["entry_gate_decision"],
        package_resolution=entry["package_resolution"],
        package_verification_digest=entry["package_verification_digest"],
        verified_operation_plan_digest=verified_operation_plan_digest,
        feature_positions=feature_positions,
        batch_id=batch_id,
    )
    return {
        "kind": "icp.begin-requirement-result.v1",
        "schema_version": 1,
        "status": "prepared",
        "prepared": prepared,
        "entry": entry,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Begin one ICP requirement after the entry gate")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--feature-positions", required=True, type=Path)
    parser.add_argument("--verified-operation-plan-digest", required=True)
    parser.add_argument("--batch-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = begin(
            config_path=args.config,
            feature_positions_path=args.feature_positions,
            verified_operation_plan_digest=args.verified_operation_plan_digest,
            batch_id=args.batch_id,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] == "prepared" else 2
    except Exception as exc:
        message = str(exc) if isinstance(exc, BeginRequirementError) else "requirement activation failed"
        print(
            json.dumps(
                {
                    "kind": "icp.begin-requirement-error.v1",
                    "schema_version": 1,
                    "status": "error",
                    "error": type(exc).__name__,
                    "message": message,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
