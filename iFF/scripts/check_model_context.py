#!/usr/bin/env python3
"""Validate current bounded model inputs and their cumulative generation ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from complete_worker import build_receipt, load_object
from model_context_contract import expected_workers, validate_packet


MAX_BYTES = 8192


ACTION_KINDS = {
    "component": {"resolve_component_semantics", "none"},
    "visual": {
        "resolve_component_semantics",
        "fill_plan_judgment",
        "run_visual_verification",
        "fix_hard_failure",
        "apply_one_repair",
        "none",
    },
    "interaction": {
        "classify_compound_rule",
        "classify_interaction_item",
        "complete_rule_semantics",
        "choose_action_target_board",
        "confirm_anchor",
        "choose_initial_state",
        "define_state_meaning",
        "define_transition",
        "implement_interaction_case",
        "run_interaction_gate",
        "none",
    },
    "data": {
        "confirm_field_binding",
        "choose_field_group",
        "choose_operation",
        "choose_field",
        "run_deterministic_repair",
        "none",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def requires_full_rule_read(text: str) -> bool:
    for line in text.splitlines():
        lowered = line.lower()
        names_rule = any(
            name in lowered
            for name in ("skill.md", "test_rules.md", "implementation_rules.md")
        )
        requires_full = any(
            marker in lowered for marker in ("completely", "entire", "全文", "完整")
        )
        negated = any(marker in lowered for marker in ("do not", "never", "禁止"))
        if names_rule and requires_full and not negated:
            return True
    return False


def packet_expectations(
    spec_root: Path, project_root: Path, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    feature = str(manifest.get("featureId") or spec_root.name)
    expectations = [
        {
            "kind": "component",
            "path": project_root / ".iff" / "component_model_packet.json",
            "scope": {"feature": feature},
        }
    ]
    for value in (manifest.get("states") or {}).values():
        board = str((value or {}).get("board") or "")
        expectations.append(
            {
                "kind": "visual",
                "path": spec_root / board / "visual_model_packet.json",
                "scope": {"feature": feature, "board": board},
            }
        )
    expectations.extend(
        [
            {
                "kind": "interaction",
                "path": spec_root / "interaction_model_packet.json",
                "scope": {"feature": feature},
            },
            {
                "kind": "data",
                "path": spec_root / "data_model_packet.json",
                "scope": {"feature": feature},
            },
        ]
    )
    return expectations


def validate_ledger(ledger: Path) -> tuple[list[str], list[dict[str, Any]]]:
    if not ledger.is_file():
        return [f"model input ledger missing: {ledger}"], []
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    for index, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"model input ledger line {index} invalid: {error}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"model input ledger line {index} is not an object")
            continue
        blob = ledger.parent / "model_context_blobs" / f"{entry.get('sha256')}.bin"
        if not blob.is_file():
            errors.append(f"model input blob missing at line {index}")
        elif sha256(blob) != entry.get("sha256") or blob.stat().st_size != entry.get(
            "bytes"
        ):
            errors.append(f"model input blob stale at line {index}")
        entries.append(entry)
    return errors, entries


def validate_context(
    spec_root: Path,
    project_root: Path,
    skill_dir: Path,
    feature_manifest_path: Path,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[str] = []
    model_files: list[dict[str, Any]] = []
    manifest = load_object(feature_manifest_path)
    try:
        workers = expected_workers(manifest)
    except ValueError as error:
        return [str(error)], [], []
    workers_dir = spec_root / ".iff" / "workers"
    expected_receipts = {
        (workers_dir / f"{worker['id']}.receipt.json").resolve(): worker
        for worker in workers
    }
    actual_receipts = {path.resolve() for path in workers_dir.glob("*.receipt.json")}
    for missing in sorted(set(expected_receipts) - actual_receipts):
        errors.append(f"worker receipt missing: {missing.name}")
    for extra in sorted(actual_receipts - set(expected_receipts)):
        errors.append(f"unexpected worker receipt: {extra.name}")
    for receipt_path, worker in expected_receipts.items():
        if not receipt_path.is_file():
            continue
        try:
            stored = load_object(receipt_path)
            expected = build_receipt(
                skill_dir,
                feature_manifest_path,
                Path(str(stored.get("contractInputPath") or "")).resolve(),
                Path(str(stored.get("resultPath") or "")).resolve(),
                receipt_path,
            )
            if stored != expected or stored.get("worker") != worker:
                raise ValueError("receipt differs from current canonical receipt")
            prompt = Path(str(stored["contractPath"])).resolve()
            if requires_full_rule_read(prompt.read_text(encoding="utf-8")):
                errors.append(f"{prompt}: forbidden full rule read")
            model_files.append(
                {
                    "kind": "worker_prompt",
                    "owner": worker["id"],
                    "path": str(prompt),
                    "bytes": prompt.stat().st_size,
                    "sha256": sha256(prompt),
                }
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"{receipt_path}: {error}")

    expectations = packet_expectations(spec_root, project_root, manifest)
    expected_packet_paths = {item["path"].resolve() for item in expectations}
    discovered = {
        path.resolve()
        for path in [
            *spec_root.rglob("*_model_packet.json"),
            project_root / ".iff" / "component_model_packet.json",
        ]
        if path.is_file()
    }
    for extra in sorted(discovered - expected_packet_paths):
        errors.append(f"unexpected model packet: {extra}")
    for expectation in expectations:
        path = expectation["path"].resolve()
        if not path.is_file():
            errors.append(f"{path.name} missing: {path}")
            continue
        try:
            packet = load_object(path)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            errors.append(f"{path}: {error}")
            continue
        packet_errors = validate_packet(
            packet,
            {
                "kind": expectation["kind"],
                "scope": expectation["scope"],
                "requiredSources": [],
                "allowedActions": sorted(ACTION_KINDS[expectation["kind"]]),
            },
            project_root,
        )
        errors.extend(f"{path}: {error}" for error in packet_errors)
        model_files.append(
            {
                "kind": f"{expectation['kind']}_model_packet",
                "owner": expectation["scope"].get("board") or expectation["scope"]["feature"],
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "action": (packet.get("action") or {}).get("kind"),
            }
        )

    ledger_errors, ledger_entries = validate_ledger(spec_root / ".iff/model_context.jsonl")
    errors.extend(ledger_errors)
    ledger_hashes = {entry.get("sha256") for entry in ledger_entries}
    for item in model_files:
        if item["sha256"] not in ledger_hashes:
            errors.append(f"model input missing from cumulative ledger: {item['path']}")
        if item["bytes"] > MAX_BYTES:
            errors.append(f"{item['path']}: exceeds {MAX_BYTES} bytes")
    return errors, sorted(model_files, key=lambda item: (item["kind"], item["path"])), ledger_entries


def build_report(
    spec_root: Path,
    project_root: Path,
    skill_dir: Path,
    feature_manifest_path: Path,
) -> dict[str, Any]:
    errors, model_files, ledger = validate_context(
        spec_root, project_root, skill_dir, feature_manifest_path
    )
    current_bytes = sum(item["bytes"] for item in model_files)
    generated_bytes = sum(int(entry.get("bytes") or 0) for entry in ledger)
    generated_prompt_count = sum(
        1 for entry in ledger if entry.get("kind") == "worker_prompt"
    )
    rule_bytes = sum(
        (skill_dir / name).stat().st_size
        for name in ("SKILL.md", "test_rules.md", "implementation_rules.md")
    )
    avoided_rule_bytes = generated_prompt_count * rule_bytes
    baseline = generated_bytes + avoided_rule_bytes
    return {
        "version": 2,
        "specRoot": str(spec_root),
        "projectRoot": str(project_root),
        "featureManifest": str(feature_manifest_path),
        "maxBytesPerFile": MAX_BYTES,
        "currentRetainedInputBytes": current_bytes,
        "generatedInputBytes": generated_bytes,
        "generatedInputCount": len(ledger),
        "controlledBaselineBytes": baseline,
        "controlledInputReductionPercent": (
            round(avoided_rule_bytes * 100 / baseline, 1) if baseline else 0.0
        ),
        "unmeasuredChannels": [
            "provider system prompt",
            "Agent framework envelope",
            "tool stdout/stderr not embedded in a packet",
            "provider tokenizer overhead",
        ],
        # Compatibility aliases remain explicit snapshot/baseline fields.
        "totalBytes": current_bytes,
        "avoidedRepeatedRuleBytes": avoided_rule_bytes,
        "legacyEquivalentBytes": baseline,
        "reductionPercent": (
            round(avoided_rule_bytes * 100 / baseline, 1) if baseline else 0.0
        ),
        "modelFiles": model_files,
        "ok": not errors,
        "failures": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_report(
        Path(args.spec_root).expanduser().resolve(),
        Path(args.project_root).expanduser().resolve(),
        Path(args.skill_dir).expanduser().resolve(),
        Path(args.feature_manifest).expanduser().resolve(),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["failures"]:
        raise SystemExit("ERROR: model context invalid:\n" + "\n".join(report["failures"]))
    print(
        f"ok model context: files={len(report['modelFiles'])} "
        f"current_bytes={report['currentRetainedInputBytes']} "
        f"generated_bytes={report['generatedInputBytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
