#!/usr/bin/env python3
"""Execute and attest the assembly RED -> packaging -> GREEN test sequence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

from layout_trace_contract import LayoutTraceContractError, load_actual_layout_trace
from prepare_assembly_packaging import (
    pre_green_evidence_snapshot,
    red_evidence_snapshot,
    sha256,
    validate_evidence,
)


RUNNER = "assembly_tdd_guard.py"
TOOLING_FAILURE_SIGNALS = (
    "operation not permitted",
    "permission denied",
    "engine.stamp",
    "no space left on device",
    "failed host lookup",
    "socketexception",
    "unable to locate a development device",
    "flutter pub get failed",
)
SCHEMA_VERSION = 1


class GuardError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GuardError(f"evidence missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GuardError(f"evidence is invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardError(f"evidence must be a JSON object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def normalize_test_target(project_root: Path, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute():
        raise GuardError("test target must be project-relative")
    resolved = (project_root / candidate).resolve()
    try:
        relative = resolved.relative_to(project_root)
    except ValueError as exc:
        raise GuardError("test target escapes the project root") from exc
    if not relative.parts or relative.parts[0] != "test":
        raise GuardError("test target must be under project test/")
    if not resolved.exists():
        raise GuardError(f"test target does not exist: {resolved}")
    return relative.as_posix()


def run_test(project_root: Path, flutter: str, test_target: str) -> tuple[subprocess.CompletedProcess[str], int, int, str, str]:
    argv = [flutter, "test", test_target]
    command = shlex.join(argv)
    started_at_ns = time.time_ns()
    try:
        result = subprocess.run(
            argv,
            cwd=project_root,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        raise GuardError(f"unable to execute guarded test command: {exc}") from exc
    completed_at_ns = time.time_ns()
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    output_sha256 = hashlib.sha256(
        (result.stdout + "\n---stderr---\n" + result.stderr).encode("utf-8")
    ).hexdigest()
    return result, started_at_ns, completed_at_ns, command, output_sha256


def is_tooling_failure(result: subprocess.CompletedProcess[str]) -> bool:
    combined = f"{result.stdout}\n{result.stderr}".casefold()
    return any(signal in combined for signal in TOOLING_FAILURE_SIGNALS)


def build_case_evidence(
    spec_root: Path,
    project_root: Path,
    test_target: str,
    *,
    red_run_id: object,
    green_run_id: object,
) -> dict[str, object]:
    plan_path = spec_root / "interaction_test_plan.json"
    if not plan_path.is_file():
        return {}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    cases = plan.get("cases") if isinstance(plan, dict) else None
    if not isinstance(cases, list):
        raise GuardError("interaction_test_plan.json cases must be an array")

    target = Path(test_target)
    target = target if target.is_absolute() else project_root / target
    target = target.resolve()
    project = project_root.resolve()
    if not target.is_relative_to(project):
        raise GuardError("test target must stay within project root")
    files = [target] if target.is_file() else sorted(target.rglob("*.dart"))
    source = {path: path.read_text(encoding="utf-8") for path in files if path.is_file()}

    mappings: dict[str, object] = {}
    for case in cases:
        case_id = case.get("id") if isinstance(case, dict) else None
        if not isinstance(case_id, str) or not case_id:
            raise GuardError("interaction test case id must be a non-empty string")
        if case_id in mappings:
            raise GuardError(f"duplicate interaction test case id: {case_id}")
        matches = [path for path, text in source.items() if case_id in text]
        if not matches:
            raise GuardError(f"interaction test case id is not present in test source: {case_id}")
        digest = hashlib.sha256()
        relative_files: list[str] = []
        for path in matches:
            relative_files.append(path.relative_to(project).as_posix())
            digest.update(path.read_bytes())
        mappings[case_id] = {
            "redRunId": red_run_id,
            "greenRunId": green_run_id,
            "testTarget": test_target,
            "testFiles": relative_files,
            "testSourceSha256": digest.hexdigest(),
        }
    return mappings


def file_manifest(root: Path, targets: list[Path], label: str) -> dict[str, str]:
    files: list[Path] = []
    for target in targets:
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(path for path in target.rglob("*.dart") if path.is_file())
        else:
            raise GuardError(f"{label} adoption target missing: {target}")
    if not files:
        raise GuardError(f"{label} adoption manifest is empty")
    return {
        path.resolve().relative_to(root).as_posix(): sha256(path)
        for path in sorted(set(files))
    }


def adopt(args: argparse.Namespace) -> int:
    if args.authorization != "preexisting-green":
        raise GuardError("preexisting GREEN adoption requires explicit authorization")
    spec_root = Path(args.spec_root).expanduser().resolve()
    project_root = Path(args.project_root).expanduser().resolve()
    test_target = normalize_test_target(project_root, args.test_target)
    feature_key = spec_root.name
    source_targets = [project_root / "lib" / feature_key]
    if (project_root / "lib" / "main.dart").is_file():
        source_targets.append(project_root / "lib" / "main.dart")
    contract_targets = [
        spec_root / name
        for name in (
            "row.json",
            "interaction_contract.json",
            "interaction_test_plan.json",
            "api_contract.json",
        )
    ]
    (spec_root / "assembly_packaging.json").unlink(missing_ok=True)
    run_id = uuid.uuid4().hex
    result, started_at_ns, completed_at_ns, command, output_sha256 = run_test(
        project_root, args.flutter, test_target
    )
    if result.returncode != 0:
        raise GuardError("preexisting GREEN adoption requires the scoped tests to pass")
    record = {
        "runner": RUNNER,
        "run_id": run_id,
        "authorization": args.authorization,
        "command": command,
        "exit_code": result.returncode,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
        "output_sha256": output_sha256,
        "source_files": file_manifest(project_root, source_targets, "source"),
        "test_files": file_manifest(project_root, [project_root / test_target], "test"),
        "contract_files": file_manifest(spec_root, contract_targets, "contract"),
    }
    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "guard": {
            "runner": RUNNER,
            "mode": "preexisting_green_adoption",
            "phase": "adoption_verified",
            "runId": run_id,
            "projectRoot": str(project_root),
            "specRoot": str(spec_root),
            "testTarget": test_target,
        },
        "adoption": record,
    }
    evidence_path = spec_root / "interaction_test_evidence.json"
    write_json(evidence_path, evidence)
    pre_green_evidence_snapshot(spec_root, require_pre_green=True)
    print(f"PASS: preexisting GREEN adopted run_id={run_id}")
    return 0


def validate_tdd_chronology(spec_root: Path) -> list[str]:
    spec_root = spec_root.expanduser().resolve()
    evidence_path = spec_root / "interaction_test_evidence.json"
    packaging_path = spec_root / "assembly_packaging.json"
    failures = [
        f"packaging: {failure}" for failure in validate_evidence(packaging_path)
    ]
    try:
        evidence = load_json(evidence_path)
        pre_green_snapshot = pre_green_evidence_snapshot(
            spec_root, require_pre_green=False
        )
        packaging = load_json(packaging_path)
    except (GuardError, RuntimeError) as exc:
        failures.append(str(exc))
        return failures

    guard = evidence.get("guard") or {}
    green = evidence.get("green") or {}
    run_id = pre_green_snapshot.get("runId")
    if evidence.get("schemaVersion") != SCHEMA_VERSION:
        failures.append("guarded TDD evidence schema invalid")
    mode = pre_green_snapshot.get("mode")
    if guard.get("mode", "strict_tdd") != mode:
        failures.append("guarded TDD provenance mode changed")
    if packaging.get("testProvenanceMode") != mode:
        failures.append("packaging test provenance mode mismatch")
    if guard.get("runner") != RUNNER or guard.get("phase") != "green_verified":
        failures.append("guarded TDD phase must be green_verified")
    if guard.get("runId") != run_id:
        failures.append("guarded TDD run id changed after pre-GREEN evidence")
    if green.get("runner") != RUNNER or green.get("run_id") != run_id:
        failures.append("GREEN evidence was not issued by the guarded runner")
    if green.get("exit_code", green.get("exitCode")) != 0:
        failures.append("GREEN evidence exit code must be 0")

    prepared_at_ns = packaging.get("preparedAtNs")
    green_started_at_ns = green.get("started_at_ns", green.get("startedAtNs"))
    green_completed_at_ns = green.get("completed_at_ns", green.get("completedAtNs"))
    if not isinstance(prepared_at_ns, int):
        failures.append("packaging preparedAtNs missing")
    elif not isinstance(green_started_at_ns, int) or green_started_at_ns <= prepared_at_ns:
        failures.append("GREEN invocation is not newer than packaging evidence")
    if (
        not isinstance(green_completed_at_ns, int)
        or not isinstance(green_started_at_ns, int)
        or green_completed_at_ns < green_started_at_ns
    ):
        failures.append("GREEN completion chronology invalid")
    if packaging.get("tddRunId") != run_id:
        failures.append("packaging evidence is not tied to the guarded pre-GREEN run")
    if green.get("pre_green_record_sha256") != pre_green_snapshot.get("recordSha256"):
        failures.append("GREEN evidence is not tied to the current pre-GREEN record")
    if green.get("packaging_sha256") != sha256(packaging_path):
        failures.append("GREEN evidence packaging hash mismatch")
    if green.get("packaging_prepared_at_ns") != prepared_at_ns:
        failures.append("GREEN evidence packaging timestamp mismatch")
    if guard.get("testTarget") != pre_green_snapshot.get("testTarget"):
        failures.append("guarded test target changed after pre-GREEN evidence")
    return failures


def validate_fresh_layout_traces(spec_root: Path, started_at_ns: int) -> list[str]:
    boards = [path for path in sorted(spec_root.iterdir()) if path.is_dir()]
    if not boards:
        return [f"no board dirs under {spec_root}"]
    failures: list[str] = []
    for board in boards:
        try:
            load_actual_layout_trace(
                board / "actual_layout_trace.json",
                min_mtime_ns=started_at_ns,
            )
        except LayoutTraceContractError as exc:
            failures.append(f"{board.name}: {exc}")
    return failures


def red(args: argparse.Namespace) -> int:
    spec_root = Path(args.spec_root).expanduser().resolve()
    project_root = Path(args.project_root).expanduser().resolve()
    if not spec_root.is_dir() or not project_root.is_dir():
        raise GuardError("spec root and project root must exist")
    test_target = normalize_test_target(project_root, args.test_target)
    (spec_root / "assembly_packaging.json").unlink(missing_ok=True)
    run_id = uuid.uuid4().hex
    result, started_at_ns, completed_at_ns, command, output_sha256 = run_test(
        project_root,
        args.flutter,
        test_target,
    )
    red_record = {
        "runner": RUNNER,
        "run_id": run_id,
        "command": command,
        "exit_code": result.returncode,
        "failure_kind": args.failure_kind,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
        "output_sha256": output_sha256,
    }
    tooling_failure = is_tooling_failure(result)
    red_record["failure_classification"] = (
        "tooling_environment" if tooling_failure else "feature_behavior"
    )
    valid = (
        result.returncode != 0
        and args.failure_kind == "missing_feature_behavior"
        and not tooling_failure
    )
    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "guard": {
            "runner": RUNNER,
            "mode": "strict_tdd",
            "phase": "red_verified" if valid else "red_rejected",
            "runId": run_id,
            "projectRoot": str(project_root),
            "specRoot": str(spec_root),
            "testTarget": test_target,
        },
        "red": red_record,
    }
    write_json(spec_root / "interaction_test_evidence.json", evidence)
    if not valid:
        if tooling_failure:
            raise GuardError("RED invocation failed because of tooling/environment, not feature behavior")
        raise GuardError(
            "RED invocation must fail with failure_kind=missing_feature_behavior"
        )
    red_evidence_snapshot(spec_root, require_pre_green=True)
    print(f"PASS: guarded RED recorded run_id={run_id}")
    return 0


def green(args: argparse.Namespace) -> int:
    spec_root = Path(args.spec_root).expanduser().resolve()
    project_root = Path(args.project_root).expanduser().resolve()
    test_target = normalize_test_target(project_root, args.test_target)
    evidence_path = spec_root / "interaction_test_evidence.json"
    packaging_path = spec_root / "assembly_packaging.json"
    evidence = load_json(evidence_path)
    pre_green_snapshot = pre_green_evidence_snapshot(spec_root, require_pre_green=True)
    guard = evidence.get("guard") or {}
    if guard.get("projectRoot") != str(project_root):
        raise GuardError("GREEN project root differs from guarded pre-GREEN evidence")
    if guard.get("testTarget") != test_target:
        raise GuardError("GREEN test target differs from guarded pre-GREEN evidence")
    packaging_failures = validate_evidence(packaging_path)
    if packaging_failures:
        raise GuardError("; ".join(packaging_failures))
    packaging = load_json(packaging_path)
    prepared_at_ns = packaging.get("preparedAtNs")
    if (
        not isinstance(prepared_at_ns, int)
        or prepared_at_ns <= pre_green_snapshot["completedAtNs"]
    ):
        raise GuardError("packaging evidence must be newer than guarded pre-GREEN evidence")

    result, started_at_ns, completed_at_ns, command, output_sha256 = run_test(
        project_root,
        args.flutter,
        test_target,
    )
    if started_at_ns <= prepared_at_ns:
        raise GuardError("GREEN invocation must start after packaging evidence")
    if result.returncode == 0:
        trace_failures = validate_fresh_layout_traces(spec_root, started_at_ns)
        if trace_failures:
            raise GuardError("; ".join(trace_failures))
    evidence["guard"]["phase"] = (
        "green_verified" if result.returncode == 0 else "green_failed"
    )
    evidence["green"] = {
        "runner": RUNNER,
        "run_id": pre_green_snapshot["runId"],
        "command": command,
        "exit_code": result.returncode,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
        "output_sha256": output_sha256,
        "pre_green_record_sha256": pre_green_snapshot["recordSha256"],
        "packaging_sha256": sha256(packaging_path),
        "packaging_prepared_at_ns": prepared_at_ns,
    }
    if pre_green_snapshot["mode"] == "strict_tdd":
        evidence["green"]["red_record_sha256"] = pre_green_snapshot["recordSha256"]
    evidence["cases"] = build_case_evidence(
        spec_root,
        project_root,
        test_target,
        red_run_id=(evidence.get("red") or {}).get("run_id"),
        green_run_id=evidence["green"]["run_id"],
    )
    write_json(evidence_path, evidence)
    if result.returncode != 0:
        return result.returncode
    failures = validate_tdd_chronology(spec_root)
    if failures:
        raise GuardError("; ".join(failures))
    print(f"PASS: guarded GREEN recorded run_id={pre_green_snapshot['runId']}")
    return 0


def verify(args: argparse.Namespace) -> int:
    failures = validate_tdd_chronology(Path(args.spec_root))
    if failures:
        print("ERROR: guarded assembly TDD chronology failed", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("PASS: guarded RED -> packaging -> GREEN chronology verified")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("red", "green", "adopt"):
        command = subparsers.add_parser(name)
        command.add_argument("--spec-root", required=True)
        command.add_argument("--project-root", required=True)
        command.add_argument("--test-target", required=True)
        command.add_argument("--flutter", default="flutter")
    red_parser = subparsers.choices["red"]
    red_parser.add_argument(
        "--failure-kind",
        choices=["missing_feature_behavior"],
        required=True,
    )
    adopt_parser = subparsers.choices["adopt"]
    adopt_parser.add_argument(
        "--authorization",
        choices=["preexisting-green"],
        required=True,
    )
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--spec-root", required=True)
    args = parser.parse_args()
    try:
        return {"red": red, "green": green, "adopt": adopt, "verify": verify}[
            args.command
        ](args)
    except GuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
