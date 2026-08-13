#!/usr/bin/env python3
"""Fail-closed liveness and evidence supervisor for iFF shared workers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def contained_path(job_root: Path, raw: object, field: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"contract field {field} must be a non-empty path")
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(job_root)
    except ValueError as exc:
        raise ValueError(f"contract field {field} escapes jobRoot: {path}") from exc
    return path


def load_contract(contract_path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    contract_path = contract_path.expanduser().resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("kind") != "iff_shared_component_invocation":
        raise ValueError("contract kind must be iff_shared_component_invocation")
    if contract.get("schemaVersion") != 1:
        raise ValueError("unsupported shared invocation schemaVersion")
    invocation_id = contract.get("invocationId")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("contract invocationId is required")

    job_root = Path(contract["jobRoot"]).expanduser().resolve()
    project_root = Path(contract["projectRoot"]).expanduser().resolve()
    skill_dir = Path(contract["skillDir"]).expanduser().resolve()
    if not job_root.is_dir() or not project_root.is_dir() or not skill_dir.is_dir():
        raise ValueError("contract jobRoot, projectRoot, and skillDir must exist")

    paths = {
        "contract": contract_path,
        "jobRoot": job_root,
        "projectRoot": project_root,
        "skillDir": skill_dir,
        "prompt": contained_path(job_root, contract.get("prompt"), "prompt"),
        "result": contained_path(job_root, contract.get("result"), "result"),
        "compliance": contained_path(job_root, contract.get("compliance"), "compliance"),
        "state": contained_path(job_root, contract.get("state"), "state"),
        "outputLog": contained_path(job_root, contract.get("outputLog"), "outputLog"),
        "failure": contained_path(job_root, contract.get("failure"), "failure"),
        "complianceChecker": Path(contract["complianceChecker"]).expanduser().resolve(),
    }
    prompt_hash = sha256_file(paths["prompt"])
    if prompt_hash != contract.get("promptSha256"):
        raise ValueError("prompt hash drifted after invocation contract generation")
    required_hashes = contract.get("requiredFileSha256")
    if not isinstance(required_hashes, dict) or not required_hashes:
        raise ValueError("contract requiredFileSha256 is required")
    for raw_path, expected in required_hashes.items():
        source = Path(raw_path).expanduser().resolve()
        if not source.is_file() or sha256_file(source) != expected:
            raise ValueError(f"compliance source drifted: {source}")
    if str(paths["complianceChecker"]) not in required_hashes:
        raise ValueError("complianceChecker is not pinned by requiredFileSha256")
    return contract, paths


def emit(payload: dict[str, Any], failure_path: Path | None = None) -> None:
    if failure_path is not None and payload.get("success") is False:
        atomic_json(failure_path, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def failure_payload(
    contract_path: Path,
    reason: str,
    *,
    contract: dict[str, Any] | None = None,
    paths: dict[str, Path] | None = None,
    detail: str | None = None,
    worker_exit_code: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "iff_shared_worker_failure",
        "success": False,
        "reason": reason,
        "contract": str(contract_path.expanduser().resolve()),
    }
    if contract is not None:
        payload["invocationId"] = contract.get("invocationId")
    if paths is not None:
        payload["outputLog"] = str(paths["outputLog"])
    if detail:
        payload["detail"] = detail
    if worker_exit_code is not None:
        payload["workerExitCode"] = worker_exit_code
    return payload


def terminate_group(worker: subprocess.Popen[bytes], grace_seconds: float) -> None:
    signaled = False
    try:
        os.killpg(worker.pid, signal.SIGTERM)
        signaled = True
    except ProcessLookupError:
        pass
    try:
        worker.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    if signaled:
        time.sleep(min(grace_seconds, 0.2))
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    worker.wait()


def stream_worker(
    worker: subprocess.Popen[bytes],
    log_path: Path,
    total_timeout: float,
    idle_timeout: float,
    grace_seconds: float,
) -> tuple[int, str | None]:
    selector = selectors.DefaultSelector()
    assert worker.stdout is not None
    assert worker.stderr is not None
    selector.register(worker.stdout, selectors.EVENT_READ, "stdout")
    selector.register(worker.stderr, selectors.EVENT_READ, "stderr")
    started = time.monotonic()
    last_output = started
    timeout_reason: str | None = None

    with log_path.open("wb") as log:
        while worker.poll() is None or selector.get_map():
            events = selector.select(timeout=0.1)
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                last_output = time.monotonic()
                prefix = f"[{key.data}] ".encode("utf-8")
                log.write(prefix + chunk)
                log.flush()
                sys.stderr.buffer.write(prefix + chunk)
                sys.stderr.buffer.flush()

            now = time.monotonic()
            if timeout_reason is None and total_timeout > 0 and now - started >= total_timeout:
                timeout_reason = "total_timeout"
                terminate_group(worker, grace_seconds)
            elif timeout_reason is None and idle_timeout > 0 and now - last_output >= idle_timeout:
                timeout_reason = "idle_timeout"
                terminate_group(worker, grace_seconds)

        selector.close()
    if timeout_reason is None:
        terminate_group(worker, grace_seconds)
    return worker.wait(), timeout_reason


def verify_evidence(
    contract: dict[str, Any], paths: dict[str, Path], started_at_ns: int
) -> tuple[str | None, str | None]:
    result_path = paths["result"]
    compliance_path = paths["compliance"]
    if not result_path.is_file():
        return "missing_result", "worker exit 0 did not produce shared_result.json"
    if result_path.stat().st_mtime_ns < started_at_ns:
        return "stale_result", "shared_result.json predates this invocation"
    if not compliance_path.is_file():
        return "missing_compliance", "worker did not produce worker_compliance.json"
    if compliance_path.stat().st_mtime_ns < started_at_ns:
        return "stale_compliance", "worker_compliance.json predates this invocation"
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "invalid_result", str(exc)
    if result.get("success") is not True:
        return "result_not_success", "shared_result.json success must be true"
    if result.get("invocation_id") != contract["invocationId"]:
        return "result_invocation_mismatch", "shared result invocation_id mismatch"
    if result.get("prompt_sha256") != contract["promptSha256"]:
        return "result_prompt_mismatch", "shared result prompt_sha256 mismatch"
    if Path(str(result.get("result_path", ""))).expanduser().resolve() != result_path:
        return "result_path_mismatch", "shared result_path does not match invocation contract"
    if Path(str(result.get("compliance_path", ""))).expanduser().resolve() != compliance_path:
        return "compliance_path_mismatch", "shared compliance_path does not match invocation contract"
    if result.get("compliance_sha256") != sha256_file(compliance_path):
        return "compliance_hash_mismatch", "shared result does not bind current compliance bytes"

    checked = subprocess.run(
        [
            sys.executable,
            str(paths["complianceChecker"]),
            "--manifest",
            str(compliance_path),
            "--skill-dir",
            str(paths["skillDir"]),
        ],
        text=True,
        capture_output=True,
    )
    if checked.returncode != 0:
        return "compliance_rejected", (checked.stderr or checked.stdout).strip()
    render_plan = paths["jobRoot"] / "component_render_plan.json"
    if not render_plan.is_file():
        return "missing_render_plan", "worker did not produce component_render_plan.json"
    render_checked = subprocess.run(
        [
            sys.executable,
            str(paths["skillDir"] / "scripts" / "check_render_plan.py"),
            str(render_plan),
        ],
        text=True,
        capture_output=True,
    )
    if render_checked.returncode != 0:
        detail = (render_checked.stderr or render_checked.stdout).strip()
        code = "paintless_render_plan" if "required visible shape has no paint source" in detail else "render_plan_rejected"
        return code, detail
    return None, None


def run_supervised(
    contract_path: Path,
    command: list[str],
    total_override: float | None,
    idle_override: float | None,
    grace_override: float | None,
) -> int:
    contract, paths = load_contract(contract_path)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        payload = failure_payload(
            contract_path, "missing_command", contract=contract, paths=paths
        )
        emit(payload, paths["failure"])
        return 2

    total_timeout = (
        float(contract["defaultTotalTimeoutSeconds"])
        if total_override is None
        else total_override
    )
    idle_timeout = (
        float(contract["defaultIdleTimeoutSeconds"])
        if idle_override is None
        else idle_override
    )
    grace_seconds = (
        float(contract["terminationGraceSeconds"])
        if grace_override is None
        else grace_override
    )
    if total_timeout < 0 or idle_timeout < 0 or grace_seconds <= 0:
        raise ValueError("timeouts must be non-negative and termination grace must be positive")
    if total_timeout == 0 and idle_timeout == 0:
        raise ValueError("at least one shared-worker timeout must be enabled")

    for key in ("result", "compliance", "state", "outputLog", "failure"):
        paths[key].unlink(missing_ok=True)
    started_at_ns = time.time_ns()
    state = {
        "schemaVersion": 1,
        "kind": "iff_shared_supervisor_state",
        "invocationId": contract["invocationId"],
        "promptSha256": contract["promptSha256"],
        "startedAtNs": started_at_ns,
        "totalTimeoutSeconds": total_timeout,
        "idleTimeoutSeconds": idle_timeout,
    }
    atomic_json(paths["state"], state)

    environment = os.environ.copy()
    environment.update(
        {
            "IFF_SHARED_INVOCATION_ID": contract["invocationId"],
            "IFF_SHARED_PROMPT_SHA256": contract["promptSha256"],
            "IFF_SHARED_RESULT_PATH": str(paths["result"]),
            "IFF_SHARED_COMPLIANCE_PATH": str(paths["compliance"]),
        }
    )
    try:
        with paths["prompt"].open("rb") as prompt_input:
            worker = subprocess.Popen(
                command,
                cwd=paths["projectRoot"],
                stdin=prompt_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=environment,
            )
    except OSError as exc:
        payload = failure_payload(
            contract_path,
            "launch_failed",
            contract=contract,
            paths=paths,
            detail=str(exc),
        )
        emit(payload, paths["failure"])
        return 2

    state["workerPid"] = worker.pid
    atomic_json(paths["state"], state)

    worker_exit, timeout_reason = stream_worker(
        worker, paths["outputLog"], total_timeout, idle_timeout, grace_seconds
    )
    if timeout_reason is not None:
        payload = failure_payload(
            contract_path,
            timeout_reason,
            contract=contract,
            paths=paths,
            detail=(
                f"shared worker exceeded {idle_timeout}s idle timeout"
                if timeout_reason == "idle_timeout"
                else f"shared worker exceeded {total_timeout}s total timeout"
            ),
            worker_exit_code=worker_exit,
        )
        emit(payload, paths["failure"])
        return 124
    if worker_exit != 0:
        payload = failure_payload(
            contract_path,
            "worker_exit_nonzero",
            contract=contract,
            paths=paths,
            worker_exit_code=worker_exit,
        )
        emit(payload, paths["failure"])
        return 1

    reason, detail = verify_evidence(contract, paths, started_at_ns)
    if reason is not None:
        payload = failure_payload(
            contract_path,
            reason,
            contract=contract,
            paths=paths,
            detail=detail,
            worker_exit_code=worker_exit,
        )
        emit(payload, paths["failure"])
        return 1

    success = {
        "schemaVersion": 1,
        "kind": "iff_shared_worker_success",
        "success": True,
        "invocationId": contract["invocationId"],
        "result": str(paths["result"]),
        "compliance": str(paths["compliance"]),
        "outputLog": str(paths["outputLog"]),
    }
    emit(success)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--contract", required=True)
    run_parser.add_argument("--total-timeout", type=float)
    run_parser.add_argument("--idle-timeout", type=float)
    run_parser.add_argument("--termination-grace", type=float)
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    contract_path = Path(args.contract)
    try:
        return run_supervised(
            contract_path,
            args.command,
            args.total_timeout,
            args.idle_timeout,
            args.termination_grace,
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        emit(
            failure_payload(
                contract_path,
                "invalid_contract",
                detail=f"{exc} at {frame.name}:{frame.lineno}",
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
