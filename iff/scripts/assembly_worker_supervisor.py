#!/usr/bin/env python3
"""Fail-closed assembly worker handoff.

The worker process is untrusted completion evidence.  This supervisor removes any
stale certificate before launch and accepts the handoff only after a fresh
certificate passes assembly_completion.py verify.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time


SCHEMA_VERSION = 2
CONTRACT_KIND = "iff_assembly_invocation"
STATE_KIND = "iff_assembly_supervisor_state"
FAILURE_KIND = "iff_assembly_worker_failure"
EXTERNAL_PERMISSION_MARKERS = (
    "could not create PATH aliases: Operation not permitted",
    "failed to initialize in-process app-server client: Operation not permitted",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def dump_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def failure_path(paths: dict[str, Path]) -> Path:
    return paths["state"].with_suffix(".failure.json")


def remove_artifact(path: Path, *, label: str) -> None:
    if not (path.exists() or path.is_symlink()):
        return
    if path.is_dir() and not path.is_symlink():
        raise ValueError(f"{label} path is a directory: {path}")
    path.unlink()


def contract_paths(contract_path: Path) -> tuple[dict, dict[str, Path]]:
    contract = load_json(contract_path)
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported assembly invocation schemaVersion")
    if contract.get("kind") != CONTRACT_KIND:
        raise ValueError("invalid assembly invocation kind")
    if contract.get("sessionMode") != "fresh_only" or contract.get("resumeAllowed") is not False:
        raise ValueError("assembly invocation must require a fresh worker session")
    if contract.get("recoveryMode") not in {"strict-tdd", "preexisting-green"}:
        raise ValueError("assembly invocation recoveryMode is invalid")
    paths = {
        key: Path(str(contract.get(key) or "")).expanduser().resolve()
        for key in (
            "prompt",
            "specRoot",
            "projectRoot",
            "evidence",
            "state",
            "completionVerifier",
            "supervisor",
        )
    }
    if paths["supervisor"] != Path(__file__).resolve():
        raise ValueError("assembly invocation supervisor path mismatch")
    if not paths["specRoot"].is_dir():
        raise ValueError(f"assembly spec root missing: {paths['specRoot']}")
    if not paths["projectRoot"].is_dir():
        raise ValueError(f"assembly project root missing: {paths['projectRoot']}")
    if not paths["prompt"].is_file():
        raise ValueError(f"assembly prompt missing: {paths['prompt']}")
    if sha256(paths["prompt"]) != contract.get("promptSha256"):
        raise ValueError("assembly prompt changed after invocation contract generation")
    if not paths["completionVerifier"].is_file():
        raise ValueError(f"completion verifier missing: {paths['completionVerifier']}")
    if paths["completionVerifier"] != Path(__file__).resolve().parent / "assembly_completion.py":
        raise ValueError("assembly completion verifier path mismatch")
    if paths["evidence"] != paths["specRoot"] / "assembly_completion.json":
        raise ValueError("completion evidence must be assembly_completion.json in spec root")
    if paths["state"] != paths["specRoot"] / "assembly_supervisor_state.json":
        raise ValueError("assembly supervisor state path mismatch")
    return contract, paths


def prepare(contract_path: Path) -> int:
    _, paths = contract_paths(contract_path)
    evidence = paths["evidence"]
    remove_artifact(evidence, label="completion evidence")
    remove_artifact(failure_path(paths), label="assembly failure")
    started_ns = time.time_ns()
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": STATE_KIND,
        "contract": str(contract_path),
        "contractSha256": sha256(contract_path),
        "runId": secrets.token_hex(16),
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "startedAtNs": started_ns,
        "status": "prepared",
    }
    dump_json(paths["state"], state)
    print(json.dumps({"ok": True, "runId": state["runId"], "state": str(paths["state"])}))
    return 0


def parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include timezone")
    return parsed.astimezone(timezone.utc)


def verify(contract_path: Path) -> int:
    _, paths = contract_paths(contract_path)
    state = load_json(paths["state"])
    if state.get("schemaVersion") != SCHEMA_VERSION or state.get("kind") != STATE_KIND:
        raise ValueError("invalid assembly supervisor state")
    if state.get("contract") != str(contract_path):
        raise ValueError("assembly supervisor state contract mismatch")
    if state.get("contractSha256") != sha256(contract_path):
        raise ValueError("assembly invocation contract changed after prepare")
    if state.get("status") not in {"prepared", "accepted"}:
        raise ValueError("assembly supervisor state is not verifiable")
    evidence = paths["evidence"]
    if not evidence.is_file():
        print(
            f"ERROR: worker returned without fresh completion evidence: {evidence}",
            file=sys.stderr,
        )
        return 1
    started_ns = state.get("startedAtNs")
    if not isinstance(started_ns, int) or evidence.stat().st_mtime_ns < started_ns:
        print("ERROR: completion evidence predates supervised worker start", file=sys.stderr)
        return 1
    document = load_json(evidence)
    if parse_utc(document.get("issuedAt"), "completion issuedAt") < parse_utc(
        state.get("startedAt"), "supervisor startedAt"
    ):
        print("ERROR: completion evidence is stale for this supervised run", file=sys.stderr)
        return 1
    result = subprocess.run(
        [
            sys.executable,
            str(paths["completionVerifier"]),
            "verify",
            "--spec-root",
            str(paths["specRoot"]),
            "--evidence",
            str(evidence),
        ],
        text=True,
    )
    if result.returncode != 0:
        return result.returncode
    state.update(
        {
            "status": "accepted",
            "acceptedAt": datetime.now(timezone.utc).isoformat(),
            "evidenceSha256": sha256(evidence),
        }
    )
    dump_json(paths["state"], state)
    print(json.dumps({"ok": True, "runId": state["runId"], "evidence": str(evidence)}))
    return 0


def record_worker_failure(
    contract_path: Path,
    command: list[str],
    *,
    exit_code: int,
    stderr: str,
) -> int:
    _, paths = contract_paths(contract_path)
    matched_markers = [
        marker for marker in EXTERNAL_PERMISSION_MARKERS if marker in stderr
    ]
    external_blocker = bool(matched_markers)
    classification = (
        "external_sandbox_permission_startup"
        if external_blocker
        else "worker_failure"
    )
    retry_argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "run",
        "--contract",
        str(contract_path),
        "--",
        *command,
    ]
    retry_contract = {
        "action": (
            "request_main_approval_then_retry_supervised"
            if external_blocker
            else "fix_worker_failure_then_retry_supervised"
        ),
        "argv": retry_argv,
        "workingDirectory": str(paths["projectRoot"]),
        "requiresEscalation": external_blocker,
        "autoEscalationAllowed": False,
        "supervisorBypassAllowed": False,
    }
    if external_blocker:
        retry_contract["approvalJustification"] = (
            "allow the iFF assembly supervisor to start the generated worker command "
            "outside the restricted sandbox"
        )
    failure = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": FAILURE_KIND,
        "classification": classification,
        "owner": "main_session" if external_blocker else "worker",
        "requiresEscalation": external_blocker,
        "contract": str(contract_path),
        "contractSha256": sha256(contract_path),
        "attemptedCommand": command,
        "workerExitCode": exit_code,
        "matchedDiagnostics": matched_markers,
        "stderr": stderr,
        "stderrSha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        "retryContract": retry_contract,
    }
    failure_file = failure_path(paths)
    dump_json(failure_file, failure)
    state = load_json(paths["state"])
    state.update(
        {
            "status": "external_blocker" if external_blocker else "worker_failed",
            "workerExitCode": exit_code,
            "failure": str(failure_file),
            "failureClassification": classification,
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "completedAtNs": time.time_ns(),
        }
    )
    dump_json(paths["state"], state)
    print(
        json.dumps(
            {
                "ok": False,
                "classification": classification,
                "failure": str(failure_file),
                "retryContract": retry_contract,
            },
            sort_keys=True,
        )
    )
    print(f"ERROR: assembly worker exited {exit_code} ({classification})", file=sys.stderr)
    return exit_code


def run(contract_path: Path, command: list[str]) -> int:
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("supervised worker command is required after --")
    if "resume" in command:
        raise ValueError("assembly workers require a fresh session; resume is forbidden")
    prepared = prepare(contract_path)
    if prepared != 0:
        return prepared
    _, paths = contract_paths(contract_path)
    prompt = paths["prompt"].read_text(encoding="utf-8")
    worker = subprocess.run(
        command,
        cwd=paths["projectRoot"],
        input=prompt,
        text=True,
        stderr=subprocess.PIPE,
    )
    if worker.stderr:
        print(worker.stderr, end="", file=sys.stderr)
    if worker.returncode != 0:
        return record_worker_failure(
            contract_path,
            command,
            exit_code=worker.returncode,
            stderr=worker.stderr or "",
        )
    return verify(contract_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("prepare", "verify"):
        child = subparsers.add_parser(action)
        child.add_argument("--contract", required=True)
    runner = subparsers.add_parser("run")
    runner.add_argument("--contract", required=True)
    runner.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    contract_path = Path(args.contract).expanduser().resolve()
    try:
        if args.action == "prepare":
            return prepare(contract_path)
        if args.action == "verify":
            return verify(contract_path)
        return run(contract_path, args.command)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
