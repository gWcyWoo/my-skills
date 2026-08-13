"""Replay-safe supervisor shell for controlled ICP platform handlers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


class ControlledExecutionError(RuntimeError):
    pass


def _bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _receipt_root(run_root: Path) -> Path:
    path = run_root / ".icp-execution-receipts"
    if path.is_symlink():
        raise ControlledExecutionError("receipt root must not be a symlink")
    path.mkdir(mode=0o700, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode)
    if not path.is_dir() or mode & 0o077:
        raise ControlledExecutionError("receipt root permissions are unsafe")
    return path


def _publish_no_clobber(path: Path, value: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        data = _bytes(value)
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ControlledExecutionError("execution receipt is not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlledExecutionError("execution receipt is invalid") from exc
    if not isinstance(value, dict):
        raise ControlledExecutionError("execution receipt shape is invalid")
    return value


def execute_authorization(
    authorization: dict[str, Any],
    *,
    execution_nonce: str,
    expected_binding_digest: str,
    expected_authorization_digest: str,
    platform_id: str,
    profile_id: str,
    authorization_module: ModuleType,
    handler: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_binding_digest or ""):
        raise ControlledExecutionError("expected binding digest is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_authorization_digest or ""):
        raise ControlledExecutionError("expected authorization digest is invalid")
    verified = authorization_module.verify_authorization(
        authorization,
        execution_nonce=execution_nonce,
    )
    if verified["binding_digest"] != expected_binding_digest:
        raise ControlledExecutionError("binding digest differs from expectation")
    if verified["authorization_digest"] != expected_authorization_digest:
        raise ControlledExecutionError("authorization digest differs from expectation")
    binding = verified["verified_binding"]
    plan = binding["operation_plan"]
    context = plan["execution_context"]
    run_root = Path(context["run_root"])
    receipts = _receipt_root(run_root)
    receipt_id = verified["authorization_digest"]
    claim_path = receipts / f"{receipt_id}.claim.json"
    result_path = receipts / f"{receipt_id}.result.json"
    if result_path.exists():
        return _load_receipt(result_path)
    claim = {
        "kind": "icp.controlled-execution-claim.v1",
        "schema_version": 1,
        "platform_id": platform_id,
        "profile_id": profile_id,
        "authorization_digest": receipt_id,
    }
    try:
        _publish_no_clobber(claim_path, claim)
    except FileExistsError as exc:
        if result_path.exists():
            return _load_receipt(result_path)
        raise ControlledExecutionError(
            "execution claim exists without terminal receipt; recovery verification is required"
        ) from exc
    verified = authorization_module.verify_authorization(
        authorization,
        execution_nonce=execution_nonce,
    )
    step = verified["verified_binding"]["operation_plan"]["steps"][0]
    try:
        artifacts = handler(
            verified["verified_binding"]["operation_id"],
            step,
            context,
        )
        if not isinstance(artifacts, dict):
            raise ControlledExecutionError("platform handler returned an invalid result")
        report = {
            "kind": "icp.controlled-execution-report.v1",
            "schema_version": 1,
            "status": "succeeded",
            "replayed": False,
            "platform_id": platform_id,
            "profile_id": profile_id,
            "operation_id": verified["verified_binding"]["operation_id"],
            "authorization_digest": receipt_id,
            "artifacts": artifacts,
        }
    except Exception as exc:  # noqa: BLE001
        report = {
            "kind": "icp.controlled-execution-report.v1",
            "schema_version": 1,
            "status": "failed",
            "replayed": False,
            "platform_id": platform_id,
            "profile_id": profile_id,
            "operation_id": verified["verified_binding"]["operation_id"],
            "authorization_digest": receipt_id,
            "error": f"platform handler failed: {type(exc).__name__}",
        }
        _publish_no_clobber(result_path, report)
        raise ControlledExecutionError(report["error"]) from exc
    _publish_no_clobber(result_path, report)
    return report


__all__ = ["ControlledExecutionError", "execute_authorization"]
