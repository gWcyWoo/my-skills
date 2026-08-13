#!/usr/bin/env python3
"""Recompute the feature-level data accuracy gate from current artifacts and source."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_one(root: Path, name: str) -> Path | None:
    direct = root / name
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(name))
    return matches[0] if len(matches) == 1 else None


def run_check(script: str, args: list[str]) -> str | None:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name(script)), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    return result.stdout.strip() or result.stderr.strip()


def validate_data_feature(
    spec_root: Path,
    project_root: Path,
    runtime_manifest: Path,
    live_api_report: Path | None = None,
    require_live_api: bool = False,
) -> tuple[list[str], dict[str, str], bool]:
    failures: list[str] = []
    inputs: dict[str, str] = {}
    oas = find_one(spec_root, "oas.json")
    contract_path = find_one(spec_root, "api_contract.json")
    if oas is None:
        failures.append("oas.json missing or not unique")
    else:
        inputs["oas.json"] = sha256(oas)
    if contract_path is None:
        failures.append("api_contract.json missing or not unique")
    else:
        inputs["api_contract.json"] = sha256(contract_path)
    if oas and contract_path:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if (contract.get("sourceFingerprint") or {}).get("sha256") != sha256(oas):
            failures.append("api_contract.json stale against oas.json")
        else:
            canonical_failure = run_check(
                "normalize_api_contract.py",
                ["--oas", str(oas), "--out", str(contract_path), "--check"],
            )
            if canonical_failure:
                failures.append(canonical_failure)
    component_manifest = find_one(spec_root, "component_manifest.json")
    bindings = find_one(spec_root, "data_slot_bindings.json")
    for name, path in (
        ("component_manifest.json", component_manifest),
        ("data_slot_bindings.json", bindings),
    ):
        if path is None:
            failures.append(f"{name} missing or not unique")
        else:
            inputs[name] = sha256(path)
    if component_manifest and bindings and contract_path:
        binding_failure = run_check(
            "check_data_bindings.py",
            [
                "--manifest",
                str(component_manifest),
                "--api-contract",
                str(contract_path),
                "--bindings",
                str(bindings),
            ],
        )
        if binding_failure:
            failures.append(binding_failure)
    if not runtime_manifest.is_file():
        failures.append("data_runtime_manifest.json missing")
    else:
        inputs["data_runtime_manifest.json"] = sha256(runtime_manifest)
    evidence = find_one(spec_root, "data_test_evidence.json")
    if evidence is None:
        failures.append("data_test_evidence.json missing or not unique")
    else:
        inputs["data_test_evidence.json"] = sha256(evidence)
    device_evidence = find_one(spec_root, "data_device_evidence.json")
    if device_evidence is None:
        failures.append("data_device_evidence.json missing or not unique")
    else:
        inputs["data_device_evidence.json"] = sha256(device_evidence)

    if runtime_manifest.is_file() and contract_path:
        runtime_args = [
            "--project-root",
            str(project_root),
            "--runtime-manifest",
            str(runtime_manifest),
            "--api-contract",
            str(contract_path),
        ]
        if bindings:
            runtime_args.extend(["--bindings", str(bindings)])
        runtime_failure = run_check(
            "check_data_runtime.py",
            runtime_args,
        )
        if runtime_failure:
            failures.append(runtime_failure)
        api_failure = run_check(
            "check_api_integration.py",
            [
                "--api-contract",
                str(contract_path),
                "--lib-root",
                str(project_root / "lib"),
                "--runtime-manifest",
                str(runtime_manifest),
            ],
        )
        if api_failure:
            failures.append(api_failure)
    fixture_failure = run_check(
        "check_fixture_source.py", ["--root", str(project_root)]
    )
    if fixture_failure:
        failures.append(fixture_failure)
    if bindings and runtime_manifest.is_file() and evidence:
        evidence_failure = run_check(
            "check_data_evidence.py",
            [
                "--bindings",
                str(bindings),
                "--runtime-manifest",
                str(runtime_manifest),
                "--test-root",
                str(project_root / "test"),
                "--evidence",
                str(evidence),
                "--app-root",
                str(project_root / "lib"),
                "--device-evidence",
                str(device_evidence or (spec_root / "data_device_evidence.json")),
            ],
        )
        if evidence_failure:
            failures.append(evidence_failure)
    if bindings and runtime_manifest.is_file():
        coverage_failure = run_check(
            "check_data_coverage.py",
            [
                "--bindings",
                str(bindings),
                "--runtime-manifest",
                str(runtime_manifest),
                "--test-root",
                str(project_root / "test"),
            ],
        )
        if coverage_failure:
            failures.append(coverage_failure)
    if bindings and runtime_manifest.is_file() and device_evidence:
        device_failure = run_check(
            "check_data_device_evidence.py",
            [
                "--bindings",
                str(bindings),
                "--runtime-manifest",
                str(runtime_manifest),
                "--test-root",
                str(project_root / "integration_test"),
                "--project-root",
                str(project_root),
                "--evidence",
                str(device_evidence),
            ],
        )
        if device_failure:
            failures.append(device_failure)
    for source in sorted((project_root / "lib").rglob("*.dart")):
        inputs[f"lib:{source.relative_to(project_root)}"] = sha256(source)
    for test_file in sorted((project_root / "test").rglob("*_test.dart")):
        inputs[f"test:{test_file.relative_to(project_root)}"] = sha256(test_file)
    live_verified = False
    if live_api_report:
        if not live_api_report.is_file():
            failures.append("live API report path does not exist")
        elif contract_path and runtime_manifest.is_file():
            inputs["live_api_report.json"] = sha256(live_api_report)
            live_failure = run_check(
                "check_live_api_evidence.py",
                [
                    "--api-contract",
                    str(contract_path),
                    "--runtime-manifest",
                    str(runtime_manifest),
                    "--report",
                    str(live_api_report),
                ],
            )
            if live_failure:
                failures.append(live_failure)
            else:
                live_verified = True
    if require_live_api and not live_verified:
        failures.append("live API verification required but missing")
    return failures, inputs, live_verified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--live-api-report")
    parser.add_argument("--require-live-api", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    spec_root = Path(args.spec_root).resolve()
    project_root = Path(args.project_root).resolve()
    runtime_manifest = Path(args.runtime_manifest).resolve()
    failures, inputs, live_verified = validate_data_feature(
        spec_root,
        project_root,
        runtime_manifest,
        Path(args.live_api_report).resolve() if args.live_api_report else None,
        args.require_live_api,
    )
    report = {
        "version": 1,
        "ok": not failures,
        "specRoot": str(spec_root),
        "projectRoot": str(project_root),
        "runtimeManifest": str(runtime_manifest),
        "liveApiReport": (
            str(Path(args.live_api_report).resolve()) if args.live_api_report else None
        ),
        "requireLiveApi": args.require_live_api,
        "liveApiVerified": live_verified,
        "inputs": inputs,
        "failures": failures,
    }
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SystemExit("ERROR: data feature gate failed:\n" + "\n".join(f"- {e}" for e in failures))
    print("ok data feature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
