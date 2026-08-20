#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


STAGES = {"extract", "component-design", "implementation", "orchestration"}


class IncidentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IncidentError("missing_input", f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise IncidentError("invalid_json", f"{label} is invalid JSON: {path}") from exc


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(json_bytes(value))
    os.replace(temporary, path)


def require_project_path(project_root: Path, value: str, label: str) -> Path:
    candidate = (project_root / value).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise IncidentError("invalid_path", f"{label} must stay inside the project") from exc
    return candidate


def hash_path(path: Path) -> str:
    if path.is_symlink():
        return sha256_bytes(os.readlink(path).encode("utf-8"))
    if not path.is_file():
        raise IncidentError("invalid_path", f"evidence path is not a regular file: {path}")
    return sha256_bytes(path.read_bytes())


def tree_manifest(root: Path, excluded: tuple[Path, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.exists():
        return result
    resolved_excluded = tuple(path.resolve() for path in excluded)
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if any(resolved == base or base in resolved.parents for base in resolved_excluded):
            continue
        if path.is_symlink() or path.is_file():
            result[path.relative_to(root).as_posix()] = hash_path(path)
    return result


def icp_manifest(project_root: Path, incident_id: str | None = None) -> dict[str, str]:
    icp_root = project_root / ".icp"
    excluded: tuple[Path, ...] = ()
    if incident_id is not None:
        excluded = (icp_root / "incidents" / incident_id,)
    return tree_manifest(icp_root, excluded)


def outside_icp_manifest(project_root: Path) -> dict[str, str]:
    return tree_manifest(project_root, (project_root / ".git", project_root / ".icp"))


def require_string_list(value: object, label: str, *, non_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (non_empty and not value):
        raise IncidentError("invalid_input", f"{label} must be a {'non-empty ' if non_empty else ''}array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise IncidentError("invalid_input", f"{label}[{index}] must be a non-empty string")
        result.append(item)
    return result


def record_incident(args: argparse.Namespace) -> dict[str, object]:
    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        raise IncidentError("invalid_project", "project root does not exist")
    if args.stage not in STAGES:
        raise IncidentError("invalid_stage", f"stage must be one of {sorted(STAGES)}")
    command = require_string_list(
        read_json(Path(args.failed_command).resolve(), "failed command"),
        "failed command",
    )
    if args.exit_code == 0:
        raise IncidentError("invalid_exit_code", "an incident requires a non-zero exit code")
    error_path = Path(args.error_output).resolve()
    try:
        error_bytes = error_path.read_bytes()
    except OSError as exc:
        raise IncidentError("missing_input", "error output cannot be read") from exc
    if len(error_bytes) > 1024 * 1024:
        raise IncidentError("invalid_input", "error output exceeds the 1 MiB incident limit")
    error_text = error_bytes.decode("utf-8", errors="replace")
    checkpoint_path = require_project_path(
        project_root, args.last_checkpoint, "last checkpoint"
    )
    if not checkpoint_path.exists():
        raise IncidentError("missing_input", "last checkpoint does not exist")
    state_files: list[dict[str, str]] = []
    for value in args.state_file:
        path = require_project_path(project_root, value, "state file")
        state_files.append(
            {"path": path.relative_to(project_root).as_posix(), "sha256": hash_path(path)}
        )
    artifacts: list[dict[str, str]] = []
    for value in args.artifact:
        path = Path(value)
        if not path.is_absolute():
            path = require_project_path(project_root, value, "artifact")
            display = path.relative_to(project_root).as_posix()
        else:
            path = path.resolve()
            display = str(path)
        artifacts.append({"path": display, "sha256": hash_path(path)})
    core = {
        "stage": args.stage,
        "failed_command": command,
        "exit_code": args.exit_code,
        "error_output_sha256": sha256_bytes(error_bytes),
        "last_successful_checkpoint": checkpoint_path.relative_to(project_root).as_posix(),
        "state_files": state_files,
        "involved_artifacts": artifacts,
    }
    incident_id = "incident-" + sha256_bytes(canonical_bytes(core))[:16]
    incident_dir = project_root / ".icp" / "incidents" / incident_id
    incident_path = incident_dir / "incident.json"
    incident = {
        "schema": "icp.incident.v1",
        "incident_id": incident_id,
        "status": "open",
        "root_cause": None,
        **core,
        "error_output": error_text,
        "frozen_icp_manifest": icp_manifest(project_root),
        "outside_icp_workspace_manifest": outside_icp_manifest(project_root),
        "subagent_contract": {
            "purpose": "record the failure and prepare an append-only run-local recovery",
            "may_analyze_root_cause": False,
            "may_modify_skill_or_production": False,
            "allowed_write_root": f".icp/incidents/{incident_id}/recovery-data",
            "must_return_to_main_session": True,
        },
    }
    if incident_path.exists():
        existing = read_json(incident_path, "incident")
        if existing != incident:
            raise IncidentError("incident_collision", "incident identity already has different evidence")
    else:
        atomic_write_json(incident_path, incident)
    return {
        "ok": True,
        "incident_id": incident_id,
        "incident_file": incident_path.relative_to(project_root).as_posix(),
        "next_action": "dispatch one recovery subagent with this incident file; do not ask it for root-cause analysis",
    }


def record_recovery(args: argparse.Namespace) -> dict[str, object]:
    project_root = Path(args.project_root).resolve()
    incident_dir = project_root / ".icp" / "incidents" / args.incident_id
    incident_path = incident_dir / "incident.json"
    incident = read_json(incident_path, "incident")
    if (
        not isinstance(incident, dict)
        or incident.get("schema") != "icp.incident.v1"
        or incident.get("incident_id") != args.incident_id
        or incident.get("root_cause") is not None
    ):
        raise IncidentError("invalid_incident", "incident record is invalid")
    if outside_icp_manifest(project_root) != incident.get("outside_icp_workspace_manifest"):
        raise IncidentError(
            "outside_icp_workspace_changed",
            "temporary recovery changed files outside .icp",
        )
    if icp_manifest(project_root, args.incident_id) != incident.get("frozen_icp_manifest"):
        raise IncidentError(
            "frozen_icp_evidence_changed",
            "temporary recovery changed frozen .icp evidence",
        )
    recovery = read_json(Path(args.recovery).resolve(), "temporary recovery")
    expected_fields = {
        "schema",
        "incident_id",
        "strategy",
        "recovery_data_paths",
        "resume_command",
        "invariant_checks",
        "limitations",
    }
    if not isinstance(recovery, dict) or set(recovery) != expected_fields:
        raise IncidentError("invalid_recovery", "temporary recovery fields are invalid")
    if (
        recovery.get("schema") != "icp.incident.temporary-recovery.v1"
        or recovery.get("incident_id") != args.incident_id
    ):
        raise IncidentError("invalid_recovery", "temporary recovery targets another incident")
    strategy = recovery.get("strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        raise IncidentError("invalid_recovery", "temporary recovery strategy is required")
    resume_command = require_string_list(recovery.get("resume_command"), "resume_command")
    limitations = require_string_list(recovery.get("limitations"), "limitations")
    data_paths = require_string_list(recovery.get("recovery_data_paths"), "recovery_data_paths")
    recovery_root = (incident_dir / "recovery-data").resolve()
    recovery_artifacts: list[dict[str, str]] = []
    for value in data_paths:
        path = require_project_path(project_root, value, "recovery data")
        try:
            path.relative_to(recovery_root)
        except ValueError as exc:
            raise IncidentError(
                "invalid_recovery_scope",
                "temporary recovery data must stay under this incident's recovery-data directory",
            ) from exc
        recovery_artifacts.append(
            {"path": path.relative_to(project_root).as_posix(), "sha256": hash_path(path)}
        )
    checks = recovery.get("invariant_checks")
    if not isinstance(checks, list) or not checks:
        raise IncidentError("invalid_recovery", "invariant_checks must be non-empty")
    normalized_checks: list[dict[str, object]] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or set(check) != {"name", "passed", "evidence"}:
            raise IncidentError("invalid_recovery", f"invariant_checks[{index}] is invalid")
        if (
            not isinstance(check["name"], str)
            or not check["name"]
            or check["passed"] is not True
            or not isinstance(check["evidence"], str)
            or not check["evidence"]
        ):
            raise IncidentError("invalid_recovery", f"invariant_checks[{index}] did not pass")
        normalized_checks.append(check)
    actual_files = {
        path.relative_to(project_root).as_posix()
        for path in incident_dir.rglob("*")
        if path.is_file() and path.name not in {"incident.json", "recovery.json"}
    }
    if actual_files != set(data_paths):
        raise IncidentError(
            "undeclared_recovery_data",
            "incident directory contains undeclared temporary recovery data",
        )
    recorded = {
        **recovery,
        "status": "temporarily_recovered",
        "root_cause": None,
        "recovery_artifacts": recovery_artifacts,
        "resume_command": resume_command,
        "invariant_checks": normalized_checks,
        "limitations": limitations,
        "main_session_action": "reload the live ICP instructions and resume from the recorded checkpoint",
    }
    recovery_path = incident_dir / "recovery.json"
    if recovery_path.exists():
        if read_json(recovery_path, "recorded recovery") != recorded:
            raise IncidentError("recovery_drift", "recorded temporary recovery changed")
    else:
        atomic_write_json(recovery_path, recorded)
    return {
        "ok": True,
        "incident_id": args.incident_id,
        "status": "temporarily_recovered",
        "recovery_file": recovery_path.relative_to(project_root).as_posix(),
        "resume_command": resume_command,
    }


def pending_incidents(args: argparse.Namespace) -> dict[str, object]:
    project_root = Path(args.project_root).resolve()
    incidents_root = project_root / ".icp" / "incidents"
    incidents: list[dict[str, object]] = []
    if incidents_root.exists():
        for incident_dir in sorted(path for path in incidents_root.iterdir() if path.is_dir()):
            incident = read_json(incident_dir / "incident.json", "incident")
            recovery_path = incident_dir / "recovery.json"
            status = "temporarily_recovered" if recovery_path.exists() else "open"
            incidents.append(
                {
                    "incident_id": incident.get("incident_id"),
                    "stage": incident.get("stage"),
                    "status": status,
                    "incident_file": (incident_dir / "incident.json").relative_to(project_root).as_posix(),
                    "recovery_file": (
                        recovery_path.relative_to(project_root).as_posix()
                        if recovery_path.exists()
                        else None
                    ),
                    "reminder": "The underlying ICP defect is not fixed by temporary recovery.",
                }
            )
    return {"ok": True, "incidents": incidents}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="incident_recovery.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--project-root", required=True, type=Path)
    record.add_argument("--stage", required=True)
    record.add_argument("--failed-command", required=True, type=Path)
    record.add_argument("--exit-code", required=True, type=int)
    record.add_argument("--error-output", required=True, type=Path)
    record.add_argument("--last-checkpoint", required=True)
    record.add_argument("--state-file", action="append", default=[])
    record.add_argument("--artifact", action="append", default=[])
    recovery = subparsers.add_parser("record-recovery")
    recovery.add_argument("--project-root", required=True, type=Path)
    recovery.add_argument("--incident-id", required=True)
    recovery.add_argument("--recovery", required=True, type=Path)
    pending = subparsers.add_parser("pending")
    pending.add_argument("--project-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            result = record_incident(args)
        elif args.command == "record-recovery":
            result = record_recovery(args)
        else:
            result = pending_incidents(args)
    except IncidentError as exc:
        print(
            json.dumps(
                {"ok": False, "error": exc.code, "message": exc.message},
                ensure_ascii=False,
            ),
            file=os.sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
