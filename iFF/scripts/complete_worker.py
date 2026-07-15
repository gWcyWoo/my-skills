#!/usr/bin/env python3
"""Validate one worker's current contract and outputs, then write its receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from model_context_contract import expected_workers, render_contract
from verify_pipeline_scripts import build_report as build_preflight_report


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_current_contract(
    skill_dir: Path,
    feature_manifest_path: Path,
    contract_input_path: Path,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    contract_input = load_object(contract_input_path)
    if contract_input.get("version") != "IFF_WORKER_CONTRACT v3":
        raise ValueError("worker contract version must be IFF_WORKER_CONTRACT v3")
    manifest = load_object(feature_manifest_path)
    worker = contract_input.get("worker") or {}
    if worker not in expected_workers(manifest):
        raise ValueError("worker is not in current feature manifest")
    paths = contract_input.get("paths") or {}
    feature_root = Path(str(paths.get("featureRoot") or "")).resolve()
    expected_contract = feature_root / ".iff" / "workers" / f"{worker['id']}.contract.json"
    if contract_input_path.resolve() != expected_contract:
        raise ValueError("contract input path is not canonical")
    generation = contract_input.get("generation") or {}
    prompt = Path(str(generation.get("promptPath") or "")).resolve()
    expected_prompt = feature_root / ".iff" / "workers" / f"{worker['id']}.prompt.md"
    if prompt != expected_prompt or not prompt.is_file():
        raise ValueError("canonical contract prompt is missing or at the wrong path")
    if prompt.read_bytes() != render_contract(contract_input):
        raise ValueError("canonical contract does not match current prompt")

    fingerprints = contract_input.get("fingerprints") or {}
    sources: dict[str, Path | None] = {
        "skill_md_sha256": skill_dir / "SKILL.md",
        "test_rules_sha256": skill_dir / "test_rules.md",
        "implementation_rules_sha256": skill_dir / "implementation_rules.md",
        "verify_pipeline_scripts_sha256": skill_dir / "scripts/verify_pipeline_scripts.py",
        "feature_manifest_sha256": feature_manifest_path,
        "preflight_report_sha256": Path(str(generation.get("preflightReport") or "")),
        "renderer_sha256": skill_dir / "scripts/make_worker_prompt.py",
        "contract_library_sha256": skill_dir / "scripts/model_context_contract.py",
        "row_json_sha256": (
            Path(str(generation["rowJson"])) if generation.get("rowJson") else None
        ),
    }
    for key, path in sources.items():
        expected = sha256(path) if path is not None and path.is_file() else None
        if fingerprints.get(key) != expected:
            raise ValueError(f"contract source fingerprint mismatch: {key}")
    preflight_path = sources["preflight_report_sha256"]
    if preflight_path is None or not preflight_path.is_file():
        raise ValueError("preflight report missing")
    if load_object(preflight_path) != build_preflight_report(skill_dir):
        raise ValueError("preflight report is stale")
    return contract_input, prompt, worker


def build_receipt(
    skill_dir: Path,
    feature_manifest_path: Path,
    contract_input_path: Path,
    result_path: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    contract_input, prompt, worker = require_current_contract(
        skill_dir, feature_manifest_path, contract_input_path
    )
    expected_receipt = Path(str((contract_input.get("paths") or {}).get("receipt") or "")).resolve()
    if receipt_path.resolve() != expected_receipt:
        raise ValueError("receipt path is not canonical")
    expected_result = Path(str((contract_input.get("paths") or {}).get("result") or "")).resolve()
    if result_path.resolve() != expected_result or not result_path.is_file():
        raise ValueError("worker result path is not canonical or is missing")
    result = load_object(result_path)
    outputs = result.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("worker result outputs must be a non-empty list")
    project_root = Path(str((contract_input.get("generation") or {}).get("projectRoot") or "")).resolve()
    output_entries = []
    for raw_path in outputs:
        path = Path(str(raw_path)).expanduser().resolve()
        try:
            path.relative_to(project_root)
        except ValueError as error:
            raise ValueError(f"worker output is outside project: {path}") from error
        if not path.is_file():
            raise ValueError(f"worker output missing: {path}")
        output_entries.append({"path": str(path), "sha256": sha256(path)})
    return {
        "version": 3,
        "generator": "complete_worker.py",
        "workerContractVersion": "IFF_WORKER_CONTRACT v3",
        "worker": worker,
        "contractInputPath": str(contract_input_path.resolve()),
        "contractInputSha256": sha256(contract_input_path),
        "contractPath": str(prompt),
        "contractSha256": sha256(prompt),
        "resultPath": str(result_path.resolve()),
        "resultSha256": sha256(result_path),
        "outputs": output_entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--contract-input", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).expanduser().resolve()
    try:
        receipt = build_receipt(
            Path(args.skill_dir).expanduser().resolve(),
            Path(args.feature_manifest).expanduser().resolve(),
            Path(args.contract_input).expanduser().resolve(),
            Path(args.result).expanduser().resolve(),
            out,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: worker completion failed: {error}") from error
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, out)
    print(f"ok worker completion: {receipt['worker']['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
