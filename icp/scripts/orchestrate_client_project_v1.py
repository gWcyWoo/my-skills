#!/usr/bin/env python3
"""P3d durable, task-source-neutral requirement state orchestration."""
from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import json
import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Iterator

import requirement_claim_intent_v1 as claim_contract
import requirement_progress_v1 as progress_contract
import csv_task_source
import entry_readiness_v1
import freeze_platform_package_selection_v1
import freeze_selection_manifest
import platform_package_resolver_v1
import prepare_selection
import verify_platform_package_selection_v1


class OrchestratorError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _canonical_bytes(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise OrchestratorError("invalid_state_document", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _ordered(document: dict) -> dict:
    kind = document.get("kind")
    orders = {
        claim_contract.KIND_CLAIM_INTENT: claim_contract.CLAIM_INTENT_KEY_ORDER,
        progress_contract.KIND_ACTIVE_REQUIREMENT: progress_contract.ACTIVE_REQUIREMENT_KEY_ORDER,
        progress_contract.KIND_PROGRESS: progress_contract.PROGRESS_KEY_ORDER,
        progress_contract.KIND_CHECKPOINT_RECEIPT: progress_contract.CHECKPOINT_RECEIPT_KEY_ORDER,
        progress_contract.KIND_CLEANUP_PLAN: progress_contract.CLEANUP_PLAN_KEY_ORDER,
        progress_contract.KIND_CLEANUP_REPORT: progress_contract.CLEANUP_REPORT_KEY_ORDER,
        "icp.pending-checkpoint.v1": ("kind", "expected_revision", "receipt", "next_progress"),
    }
    order = orders.get(kind)
    if order is None or set(document) != set(order):
        return document
    result = {key: document[key] for key in order}
    if kind == progress_contract.KIND_PROGRESS:
        result["feature_positions"] = [
            {key: feature[key] for key in progress_contract.FEATURE_POSITION_KEY_ORDER}
            if isinstance(feature, dict) and set(feature) == set(progress_contract.FEATURE_POSITION_KEY_ORDER)
            else feature
            for feature in result["feature_positions"]
        ]
    if kind == progress_contract.KIND_CHECKPOINT_RECEIPT:
        for field in ("input_artifact_digests", "output_artifact_digests"):
            result[field] = [
                {key: artifact[key] for key in progress_contract.ARTIFACT_DIGEST_KEY_ORDER}
                if isinstance(artifact, dict) and set(artifact) == set(progress_contract.ARTIFACT_DIGEST_KEY_ORDER)
                else artifact
                for artifact in result[field]
            ]
    if kind == "icp.pending-checkpoint.v1":
        if isinstance(result["receipt"], dict):
            result["receipt"] = _ordered(result["receipt"])
        if isinstance(result["next_progress"], dict):
            result["next_progress"] = _ordered(result["next_progress"])
    return result


class RequirementStateStore:
    """Persist one active requirement under an exclusive state-root lock."""

    def __init__(self, state_root: Path | str):
        raw = Path(state_root).expanduser()
        raw.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = raw.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OrchestratorError("unsafe_state_root", "state root must be a real directory")
        self.state_root = raw.resolve(strict=True)
        os.chmod(self.state_root, 0o700)
        self._lock_fd: int | None = None

    @property
    def _active_path(self) -> Path:
        return self.state_root / "active.json"

    @property
    def _pending_path(self) -> Path:
        return self.state_root / "pending-checkpoint.json"

    @contextlib.contextmanager
    def exclusive_lock(self) -> Iterator[None]:
        if self._lock_fd is not None:
            raise OrchestratorError("lock_already_held", "state-root lock is already held")
        lock_path = self.state_root / ".state.lock"
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock_path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._lock_fd = fd
            yield
        finally:
            self._lock_fd = None
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _require_lock(self) -> None:
        if self._lock_fd is None:
            raise OrchestratorError("lock_not_acquired", "exclusive state-root lock is required")

    def _directory(self, name: str) -> Path:
        path = self.state_root / name
        path.mkdir(mode=0o700, exist_ok=True)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OrchestratorError("unsafe_state_path", f"unsafe state directory: {name}")
        os.chmod(path, 0o700)
        return path

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise OrchestratorError("state_missing", f"state document is missing: {path.name}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OrchestratorError("unsafe_state_path", f"state document is not a regular file: {path.name}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OrchestratorError("invalid_state_document", f"invalid state document: {path.name}") from exc
        if not isinstance(value, dict):
            raise OrchestratorError("invalid_state_document", f"state document must be an object: {path.name}")
        return _ordered(value)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _publish_no_clobber(self, path: Path, document: dict, *, exists_code: str) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise OrchestratorError(exists_code, f"state document already exists: {path.name}") from exc
        try:
            data = _canonical_bytes(document)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.fchmod(fd, 0o600)
        except Exception:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            raise
        finally:
            os.close(fd)
        self._fsync_directory(path.parent)

    def _replace(self, path: Path, document: dict) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        self._publish_no_clobber(temporary, document, exists_code="temporary_state_collision")
        try:
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def publish_claim_intent(self, intent: dict) -> Path:
        self._require_lock()
        claim_contract.verify_claim_intent(intent)
        path = self._directory("claim-intents") / f"{intent['requirement_id']}.json"
        self._publish_no_clobber(path, intent, exists_code="claim_intent_exists")
        return path

    @staticmethod
    def _verify_scope(scope: dict) -> None:
        order = (
            "kind",
            "schema_version",
            "requirement_id",
            "task_ref",
            "row_identity",
            "selection_manifest_path",
            "selection_manifest_digest",
            "entry_readiness_path",
            "entry_readiness_digest",
            "platform_package_selection_path",
            "platform_package_selection_digest",
            "verified_operation_plan_digest",
            "feature_positions",
        )
        if not isinstance(scope, dict) or tuple(scope) != order:
            raise OrchestratorError("invalid_execution_scope", "execution scope shape is invalid")
        if scope["kind"] != "icp.requirement-execution-scope.v1" or scope["schema_version"] != 1:
            raise OrchestratorError("invalid_execution_scope", "execution scope identity is invalid")
        digest_fields = (
            "requirement_id",
            "selection_manifest_digest",
            "entry_readiness_digest",
            "platform_package_selection_digest",
            "verified_operation_plan_digest",
        )
        for field in digest_fields:
            value = scope[field]
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise OrchestratorError("invalid_execution_scope", f"invalid digest field: {field}")
        if not isinstance(scope["row_identity"], str) or not scope["row_identity"].strip():
            raise OrchestratorError("invalid_execution_scope", "row identity must be non-empty")
        for field in (
            "task_ref",
            "selection_manifest_path",
            "entry_readiness_path",
            "platform_package_selection_path",
        ):
            value = scope[field]
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise OrchestratorError("invalid_execution_scope", f"scope path must be absolute: {field}")
        if not isinstance(scope["feature_positions"], list) or not scope["feature_positions"]:
            raise OrchestratorError("invalid_execution_scope", "feature positions must be non-empty")

    def publish_execution_scope(self, scope: dict) -> Path:
        self._require_lock()
        self._verify_scope(scope)
        path = self._directory("execution-scopes") / f"{scope['requirement_id']}.json"
        self._publish_no_clobber(path, scope, exists_code="execution_scope_exists")
        return path

    def load_execution_scope(self, requirement_id: str) -> dict:
        self._require_lock()
        path = self._directory("execution-scopes") / f"{requirement_id}.json"
        scope = self._read_json(path)
        expected_order = (
            "kind",
            "schema_version",
            "requirement_id",
            "task_ref",
            "row_identity",
            "selection_manifest_path",
            "selection_manifest_digest",
            "entry_readiness_path",
            "entry_readiness_digest",
            "platform_package_selection_path",
            "platform_package_selection_digest",
            "verified_operation_plan_digest",
            "feature_positions",
        )
        if set(scope) == set(expected_order):
            scope = {key: scope[key] for key in expected_order}
            scope["feature_positions"] = [
                {key: feature[key] for key in progress_contract.FEATURE_POSITION_KEY_ORDER}
                if isinstance(feature, dict) and set(feature) == set(progress_contract.FEATURE_POSITION_KEY_ORDER)
                else feature
                for feature in scope["feature_positions"]
            ]
        self._verify_scope(scope)
        return scope

    def unactivated_execution_scopes(self) -> list[dict]:
        self._require_lock()
        active_requirement_id = None
        if self._active_path.exists():
            active_requirement_id = self._read_json(self._active_path).get("requirement_id")
        scopes = []
        for path in sorted(self._directory("execution-scopes").glob("*.json")):
            scope = self.load_execution_scope(path.stem)
            if scope["requirement_id"] != active_requirement_id:
                intent_path = self._directory("claim-intents") / f"{scope['requirement_id']}.json"
                completed_path = self._directory("completion-reports") / f"{scope['requirement_id']}.json"
                if intent_path.exists() and not completed_path.exists():
                    scopes.append(scope)
        return scopes

    @staticmethod
    def _order_claim_ack(ack: dict) -> dict:
        order = (
            "kind",
            "schema_version",
            "ok",
            "task_ref",
            "row_identity",
            "row_index",
            "previous_status",
            "status",
            "sha256_before",
            "sha256_after",
        )
        return {key: ack[key] for key in order} if isinstance(ack, dict) and set(ack) == set(order) else ack

    @staticmethod
    def _order_writeback_intent(intent: dict) -> dict:
        order = (
            "kind",
            "schema_version",
            "claim_ack_digest",
            "task_ref",
            "row_identity",
            "row_index",
            "expected_status_before",
            "outcome",
            "source_sha256_before",
            "expected_source_sha256_after",
        )
        return (
            {key: intent[key] for key in order}
            if isinstance(intent, dict) and set(intent) == set(order)
            else intent
        )

    def publish_terminal_transaction(self, transaction: dict) -> Path:
        self._require_lock()
        order = ("kind", "schema_version", "requirement_id", "claim_ack", "writeback_intent")
        if not isinstance(transaction, dict) or tuple(transaction) != order:
            raise OrchestratorError("invalid_terminal_transaction", "terminal transaction shape is invalid")
        if transaction["kind"] != "icp.terminal-writeback-transaction.v1" or transaction["schema_version"] != 1:
            raise OrchestratorError("invalid_terminal_transaction", "terminal transaction identity is invalid")
        claim_ack = transaction["claim_ack"]
        intent = transaction["writeback_intent"]
        if hashlib.sha256(csv_task_source.ack_to_json_bytes(claim_ack)).hexdigest() != intent.get("claim_ack_digest"):
            raise OrchestratorError("invalid_terminal_transaction", "terminal transaction ack digest mismatch")
        path = self._directory("terminal-transactions") / f"{transaction['requirement_id']}.json"
        self._publish_no_clobber(path, transaction, exists_code="terminal_transaction_exists")
        return path

    def load_terminal_transaction(self, requirement_id: str) -> dict | None:
        self._require_lock()
        path = self._directory("terminal-transactions") / f"{requirement_id}.json"
        if not path.exists():
            return None
        raw = self._read_json(path)
        order = ("kind", "schema_version", "requirement_id", "claim_ack", "writeback_intent")
        if set(raw) == set(order):
            raw = {key: raw[key] for key in order}
            raw["claim_ack"] = self._order_claim_ack(raw["claim_ack"])
            raw["writeback_intent"] = self._order_writeback_intent(raw["writeback_intent"])
        if raw.get("requirement_id") != requirement_id:
            raise OrchestratorError("invalid_terminal_transaction", "terminal transaction requirement mismatch")
        if hashlib.sha256(csv_task_source.ack_to_json_bytes(raw["claim_ack"])).hexdigest() != raw[
            "writeback_intent"
        ].get("claim_ack_digest"):
            raise OrchestratorError("invalid_terminal_transaction", "terminal transaction ack digest mismatch")
        return raw

    def activate(self, active: dict, progress: dict) -> None:
        self._require_lock()
        progress_contract.verify_active_requirement(active)
        progress_contract.verify_progress(progress)
        if self._active_path.exists():
            raise OrchestratorError("active_requirement_exists", "one requirement is already active")
        if active["requirement_id"] != progress["requirement_id"] or active["progress_id"] != progress["progress_id"]:
            raise OrchestratorError("identity_mismatch", "active pointer and progress identities differ")
        intent_path = self._directory("claim-intents") / f"{active['requirement_id']}.json"
        intent = self._read_json(intent_path)
        claim_contract.verify_claim_intent(intent)
        if claim_contract.document_digest(intent) != active["claim_intent_digest"]:
            raise OrchestratorError("identity_mismatch", "active pointer does not bind the persisted claim intent")
        progress_path = self._directory("progress") / f"{active['progress_id']}.json"
        self._publish_no_clobber(progress_path, progress, exists_code="progress_exists")
        try:
            self._publish_no_clobber(self._active_path, active, exists_code="active_requirement_exists")
        except Exception:
            with contextlib.suppress(FileNotFoundError):
                progress_path.unlink()
            raise

    def _receipt_paths(self, progress_id: str) -> list[Path]:
        directory = self._directory("checkpoint-receipts") / progress_id
        if not directory.exists():
            return []
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OrchestratorError("unsafe_state_path", "checkpoint receipt path is unsafe")
        return sorted(directory.glob("*.json"))

    def _load_snapshot_raw(self) -> dict:
        if not self._active_path.exists():
            return {"active": None, "progress": None, "receipts": []}
        active = self._read_json(self._active_path)
        progress_contract.verify_active_requirement(active)
        progress_path = self._directory("progress") / f"{active['progress_id']}.json"
        progress = self._read_json(progress_path)
        progress_contract.verify_progress(progress)
        receipts = [self._read_json(path) for path in self._receipt_paths(active["progress_id"])]
        return {"active": active, "progress": progress, "receipts": receipts}

    def _recover_pending_checkpoint(self) -> None:
        if not self._pending_path.exists():
            return
        pending = self._read_json(self._pending_path)
        if list(pending) != ["kind", "expected_revision", "receipt", "next_progress"]:
            raise OrchestratorError("invalid_pending_checkpoint", "pending checkpoint shape is invalid")
        if pending["kind"] != "icp.pending-checkpoint.v1" or not isinstance(pending["expected_revision"], int):
            raise OrchestratorError("invalid_pending_checkpoint", "pending checkpoint identity is invalid")
        receipt = pending["receipt"]
        next_progress = pending["next_progress"]
        progress_contract.verify_checkpoint_receipt(receipt)
        progress_contract.verify_progress(next_progress)
        snapshot = self._load_snapshot_raw()
        active = snapshot["active"]
        current = snapshot["progress"]
        if active is None or current is None:
            raise OrchestratorError("invalid_pending_checkpoint", "pending checkpoint has no active requirement")
        receipt_digest = progress_contract.document_digest(receipt)
        receipt_path = self._directory("checkpoint-receipts") / active["progress_id"] / (
            f"{receipt['sequence']:08d}-{receipt_digest}.json"
        )
        if receipt_path.exists() and self._read_json(receipt_path) != receipt:
            raise OrchestratorError("checkpoint_tamper", "persisted checkpoint bytes differ")
        if current == next_progress:
            self._pending_path.unlink()
            self._fsync_directory(self.state_root)
            return
        if current["revision"] != pending["expected_revision"]:
            raise OrchestratorError("stale_progress_revision", "pending checkpoint revision is stale")
        receipts = list(snapshot["receipts"])
        if not receipt_path.exists():
            self._publish_no_clobber(receipt_path, receipt, exists_code="checkpoint_exists")
            receipts.append(receipt)
        progress_contract.verify_checkpoint_chain(receipts, active=active, progress=next_progress)
        progress_path = self._directory("progress") / f"{active['progress_id']}.json"
        self._replace(progress_path, next_progress)
        self._pending_path.unlink()
        self._fsync_directory(self.state_root)

    def load_snapshot(self) -> dict:
        self._require_lock()
        self._recover_pending_checkpoint()
        snapshot = self._load_snapshot_raw()
        if snapshot["active"] is not None:
            progress_contract.verify_checkpoint_chain(
                snapshot["receipts"], active=snapshot["active"], progress=snapshot["progress"]
            )
        return snapshot

    def commit_checkpoint(self, receipt: dict, next_progress: dict, *, expected_revision: int) -> None:
        self._require_lock()
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise OrchestratorError("invalid_expected_revision", "expected revision must be a non-negative integer")
        progress_contract.verify_checkpoint_receipt(receipt)
        progress_contract.verify_progress(next_progress)
        snapshot = self.load_snapshot()
        active = snapshot["active"]
        current = snapshot["progress"]
        if active is None or current is None:
            raise OrchestratorError("no_active_requirement", "checkpoint requires an active requirement")
        if current["revision"] != expected_revision or next_progress["revision"] != expected_revision + 1:
            raise OrchestratorError("stale_progress_revision", "progress revision compare-and-swap failed")
        receipts = list(snapshot["receipts"])
        receipts.append(receipt)
        progress_contract.verify_checkpoint_chain(receipts, active=active, progress=next_progress)
        pending = {
            "kind": "icp.pending-checkpoint.v1",
            "expected_revision": expected_revision,
            "receipt": receipt,
            "next_progress": next_progress,
        }
        self._publish_no_clobber(self._pending_path, pending, exists_code="pending_checkpoint_exists")
        self._recover_pending_checkpoint()

    def replace_progress(self, next_progress: dict, *, expected_revision: int) -> None:
        """CAS-replace mutable progress without changing the receipt chain."""
        self._require_lock()
        progress_contract.verify_progress(next_progress)
        snapshot = self.load_snapshot()
        active = snapshot["active"]
        current = snapshot["progress"]
        if active is None or current is None:
            raise OrchestratorError("no_active_requirement", "progress replacement requires an active requirement")
        if current["revision"] != expected_revision or next_progress["revision"] != expected_revision + 1:
            raise OrchestratorError("stale_progress_revision", "progress revision compare-and-swap failed")
        if (
            next_progress["requirement_id"] != active["requirement_id"]
            or next_progress["progress_id"] != active["progress_id"]
            or next_progress["claim_ack_digest"] != active["claim_ack_digest"]
        ):
            raise OrchestratorError("identity_mismatch", "replacement progress changes active identities")
        progress_contract.verify_checkpoint_chain(
            snapshot["receipts"], active=active, progress=next_progress
        )
        progress_path = self._directory("progress") / f"{active['progress_id']}.json"
        self._replace(progress_path, next_progress)

    def scratch_directory(self, requirement_id: str) -> Path:
        self._require_lock()
        snapshot = self.load_snapshot()
        active = snapshot["active"]
        if active is None or active["requirement_id"] != requirement_id:
            raise OrchestratorError("identity_mismatch", "scratch scope must match the active requirement")
        directory = self._directory("scratch") / requirement_id
        directory.mkdir(mode=0o700, exist_ok=True)
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OrchestratorError("unsafe_state_path", "scratch path is unsafe")
        os.chmod(directory, 0o700)
        return directory

    def seal_evidence(self, requirement_id: str, evidence: dict) -> str:
        self._require_lock()
        snapshot = self.load_snapshot()
        active = snapshot["active"]
        if active is None or active["requirement_id"] != requirement_id:
            raise OrchestratorError("identity_mismatch", "sealed evidence must match the active requirement")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("kind"), str):
            raise OrchestratorError("invalid_sealed_evidence", "sealed evidence must be a typed object")
        digest = progress_contract.document_digest(evidence)
        path = self._directory("sealed-evidence") / f"{requirement_id}-{digest}.json"
        if path.exists():
            if self._read_json(path) != evidence:
                raise OrchestratorError("sealed_evidence_tamper", "sealed evidence bytes differ")
            return digest
        self._publish_no_clobber(path, evidence, exists_code="sealed_evidence_exists")
        return digest

    @staticmethod
    def _checkpoint_chain_digest(receipts: list[dict]) -> str:
        return hashlib.sha256(_canonical_bytes({"receipts": receipts})).hexdigest()

    def complete_terminal_cleanup(self, cleanup_plan: dict) -> dict:
        transaction = self.stage_terminal_cleanup(cleanup_plan)
        return self._finish_terminal_cleanup(transaction)

    def stage_terminal_cleanup(self, cleanup_plan: dict) -> dict:
        """Persist enough immutable state to finish cleanup after any process exit."""
        self._require_lock()
        snapshot = self.load_snapshot()
        active = snapshot["active"]
        progress = snapshot["progress"]
        if active is None or progress is None:
            raise OrchestratorError("no_active_requirement", "terminal cleanup requires active state")
        expected_plan = progress_contract.plan_terminal_cleanup(
            active,
            progress,
            terminal_status=cleanup_plan.get("terminal_status"),
            writeback_ack_digest=cleanup_plan.get("writeback_ack_digest"),
            expected_writeback_ack_digest=cleanup_plan.get("writeback_ack_digest"),
            sealed_evidence_digest=cleanup_plan.get("sealed_evidence_digest"),
        )
        if cleanup_plan != expected_plan:
            raise OrchestratorError("invalid_cleanup_plan", "terminal cleanup plan is not canonical")
        requirement_id = active["requirement_id"]
        sealed_path = self._directory("sealed-evidence") / (
            f"{requirement_id}-{cleanup_plan['sealed_evidence_digest']}.json"
        )
        sealed = self._read_json(sealed_path)
        if progress_contract.document_digest(sealed) != cleanup_plan["sealed_evidence_digest"]:
            raise OrchestratorError("sealed_evidence_tamper", "sealed evidence digest mismatch")
        transaction = {
            "kind": "icp.terminal-cleanup-transaction.v1",
            "schema_version": 1,
            "requirement_id": requirement_id,
            "progress_id": active["progress_id"],
            "cleanup_plan": cleanup_plan,
            "checkpoint_chain_digest_before": self._checkpoint_chain_digest(snapshot["receipts"]),
        }
        path = self._directory("terminal-cleanups") / f"{requirement_id}.json"
        if path.exists():
            existing = self._load_cleanup_transaction(path)
            if existing != transaction:
                raise OrchestratorError("cleanup_transaction_tamper", "cleanup transaction bytes differ")
            return existing
        self._publish_no_clobber(path, transaction, exists_code="cleanup_transaction_exists")
        return transaction

    def _load_cleanup_transaction(self, path: Path) -> dict:
        raw = self._read_json(path)
        order = (
            "kind",
            "schema_version",
            "requirement_id",
            "progress_id",
            "cleanup_plan",
            "checkpoint_chain_digest_before",
        )
        if set(raw) == set(order):
            raw = {key: raw[key] for key in order}
            if isinstance(raw["cleanup_plan"], dict):
                raw["cleanup_plan"] = _ordered(raw["cleanup_plan"])
        if tuple(raw) != order or raw.get("kind") != "icp.terminal-cleanup-transaction.v1":
            raise OrchestratorError("invalid_cleanup_transaction", "cleanup transaction shape is invalid")
        for field in ("requirement_id", "progress_id", "checkpoint_chain_digest_before"):
            value = raw[field]
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise OrchestratorError("invalid_cleanup_transaction", f"invalid cleanup field: {field}")
        return raw

    def _finish_terminal_cleanup(self, transaction: dict) -> dict:
        cleanup_plan = transaction["cleanup_plan"]
        requirement_id = transaction["requirement_id"]
        progress_id = transaction["progress_id"]
        report_path = self._directory("completion-reports") / f"{requirement_id}.json"
        if report_path.exists():
            return _ordered(self._read_json(report_path))
        sealed_path = self._directory("sealed-evidence") / (
            f"{requirement_id}-{cleanup_plan['sealed_evidence_digest']}.json"
        )
        sealed_digest_after = progress_contract.document_digest(self._read_json(sealed_path))
        if self._active_path.exists():
            active = self._read_json(self._active_path)
            if active.get("requirement_id") != requirement_id or active.get("progress_id") != progress_id:
                raise OrchestratorError("identity_mismatch", "cleanup transaction targets another active requirement")
            self._active_path.unlink()
            self._fsync_directory(self.state_root)
        progress_path = self._directory("progress") / f"{progress_id}.json"
        if progress_path.exists():
            progress_path.unlink()
            self._fsync_directory(progress_path.parent)
        scratch = self._directory("scratch") / requirement_id
        if scratch.exists():
            metadata = scratch.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                scratch.unlink()
            elif stat.S_ISDIR(metadata.st_mode):
                shutil.rmtree(scratch)
            else:
                raise OrchestratorError("unsafe_state_path", "scratch path is not a directory")
            self._fsync_directory(scratch.parent)
        retained_receipts = [self._read_json(path) for path in self._receipt_paths(progress_id)]
        chain_after = self._checkpoint_chain_digest(retained_receipts)
        report = progress_contract.verify_terminal_cleanup(
            cleanup_plan,
            active_present=self._active_path.exists(),
            progress_present=progress_path.exists(),
            scratch_present=scratch.exists(),
            checkpoint_chain_digest_before=transaction["checkpoint_chain_digest_before"],
            checkpoint_chain_digest_after=chain_after,
            sealed_evidence_digest_after=sealed_digest_after,
        )
        self._publish_no_clobber(report_path, report, exists_code="completion_report_exists")
        return report

    def recover_terminal_cleanup(self) -> dict | None:
        self._require_lock()
        pending = []
        for path in sorted(self._directory("terminal-cleanups").glob("*.json")):
            transaction = self._load_cleanup_transaction(path)
            report_path = self._directory("completion-reports") / f"{transaction['requirement_id']}.json"
            if not report_path.exists():
                pending.append(transaction)
        if len(pending) > 1:
            raise OrchestratorError("multiple_pending_cleanups", "only one terminal cleanup may be pending")
        return self._finish_terminal_cleanup(pending[0]) if pending else None


def _file_sha256(path: Path) -> str:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OrchestratorError("unsafe_scope_artifact", f"scope artifact is not a regular file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _publish_bytes_no_clobber(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise OrchestratorError("adjacent_artifact_exists", f"adjacent artifact already exists: {path.name}") from exc
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchmod(fd, 0o600)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        raise
    finally:
        os.close(fd)
    RequirementStateStore._fsync_directory(path.parent)


def _producer_script_bytes() -> dict[str, bytes]:
    scripts = Path(__file__).resolve().parent
    return {
        "entry-readiness-v1": (scripts / "entry_readiness_v1.py").read_bytes(),
        "platform-package-resolver-v1": (scripts / "platform_package_resolver_v1.py").read_bytes(),
        "freeze-platform-package-selection-v1": (
            scripts / "freeze_platform_package_selection_v1.py"
        ).read_bytes(),
        "verify-platform-package-selection-v1": (
            scripts / "verify_platform_package_selection_v1.py"
        ).read_bytes(),
    }


def _verify_scope_artifacts(scope: dict) -> None:
    pairs = (
        ("selection_manifest_path", "selection_manifest_digest"),
        ("entry_readiness_path", "entry_readiness_digest"),
        ("platform_package_selection_path", "platform_package_selection_digest"),
    )
    for path_field, digest_field in pairs:
        path = Path(scope[path_field])
        if _file_sha256(path) != scope[digest_field]:
            raise OrchestratorError("scope_artifact_drift", f"scope artifact digest mismatch: {path_field}")


def recover_pending_csv_claim(store: RequirementStateStore) -> dict:
    """Recover the sole persisted pre/post-CAS claim window, then activate it."""
    store._require_lock()
    store.recover_terminal_cleanup()
    if store.load_snapshot()["active"] is not None:
        return {"decision": "active-present", "active": store.load_snapshot()["active"]}
    scopes = store.unactivated_execution_scopes()
    if not scopes:
        return {"decision": "no-pending-claim", "active": None}
    if len(scopes) != 1:
        raise OrchestratorError("multiple_pending_claims", "exactly one pending claim is allowed")
    scope = scopes[0]
    _verify_scope_artifacts(scope)
    intent_path = store._directory("claim-intents") / f"{scope['requirement_id']}.json"
    intent = store._read_json(intent_path)
    claim_contract.verify_claim_intent(intent)
    if claim_contract.document_digest(intent) != scope.get("claim_intent_digest", claim_contract.document_digest(intent)):
        raise OrchestratorError("identity_mismatch", "execution scope claim intent drift")
    recovery = csv_task_source.recover_claim_with_intent(
        scope["task_ref"], scope["row_identity"], intent
    )
    ack = recovery["claim_ack"]
    if ack is None:
        return {"decision": "claim-blocked", "recovery_report": recovery["recovery_report"], "active": None}
    claim_ack_digest = hashlib.sha256(csv_task_source.ack_to_json_bytes(ack)).hexdigest()
    progress_id = progress_contract.derive_progress_id(scope["requirement_id"], claim_ack_digest)
    active = {
        "kind": progress_contract.KIND_ACTIVE_REQUIREMENT,
        "schema_version": 1,
        "requirement_id": scope["requirement_id"],
        "selection_manifest_digest": intent["selection_manifest_digest"],
        "row_identity_digest": intent["row_identity_digest"],
        "claim_intent_digest": claim_contract.document_digest(intent),
        "claim_ack_digest": claim_ack_digest,
        "progress_id": progress_id,
    }
    progress = {
        "kind": progress_contract.KIND_PROGRESS,
        "schema_version": 1,
        "requirement_id": scope["requirement_id"],
        "progress_id": progress_id,
        "claim_ack_digest": claim_ack_digest,
        "verified_operation_plan_digest": scope["verified_operation_plan_digest"],
        "revision": 0,
        "phase": "claimed",
        "latest_checkpoint_receipt_digest": None,
        "checkpoint_count": 0,
        "feature_positions": copy.deepcopy(scope["feature_positions"]),
    }
    progress_contract.verify_active_requirement(active)
    progress_contract.verify_progress(progress)
    store.activate(active, progress)
    return {
        "decision": "claim-activated",
        "recovery_report": recovery["recovery_report"],
        "claim_ack": ack,
        "active": active,
        "progress": progress,
    }


def prepare_single_requirement_with_entry_gate(
    *,
    resolved_config: dict,
    registries: dict,
    readiness_report: dict,
    entry_gate_decision: dict,
    package_resolution: dict,
    package_verification_digest: str,
    verified_operation_plan_digest: str,
    feature_positions: list[dict],
    batch_id: str | None = None,
) -> dict:
    """Freeze adjacent artifacts, persist intent, then claim exactly one row."""
    if not isinstance(verified_operation_plan_digest, str) or len(
        verified_operation_plan_digest
    ) != 64 or any(
        character not in "0123456789abcdef"
        for character in verified_operation_plan_digest
    ):
        raise OrchestratorError(
            "invalid_operation_plan_digest",
            "operation plan digest must be lowercase SHA-256 hex",
        )
    entry_readiness_v1.verify_readiness_report(readiness_report)
    entry_readiness_v1.verify_entry_gate_decision(entry_gate_decision)
    platform_package_resolver_v1.verify_resolution(package_resolution)
    if readiness_report["status"] != "ready":
        return {
            "kind": "icp.requirement-entry-result.v1",
            "schema_version": 1,
            "decision": "needs-user-input",
            "readiness_report": readiness_report,
        }
    if entry_gate_decision["decision"] != "select-new":
        return {
            "kind": "icp.requirement-entry-result.v1",
            "schema_version": 1,
            "decision": entry_gate_decision["decision"],
            "entry_gate_decision": entry_gate_decision,
        }
    if package_resolution["platform_id"] != resolved_config.get("platform"):
        raise OrchestratorError("identity_mismatch", "package resolution platform differs from run config")
    if resolved_config.get("profile") not in (None, package_resolution["profile_id"]):
        raise OrchestratorError("identity_mismatch", "package resolution profile differs from run config")
    if not isinstance(feature_positions, list) or not feature_positions:
        raise OrchestratorError("invalid_feature_positions", "one or more feature positions are required")

    state_root, _ = freeze_selection_manifest.derive_roots(
        resolved_config["platform"], resolved_config["project_root"], "state-check"
    )
    durable_store = RequirementStateStore(state_root / "icp-requirements-v1")
    with durable_store.exclusive_lock():
        recovered = recover_pending_csv_claim(durable_store)
        if recovered["decision"] != "no-pending-claim":
            return {
                "kind": "icp.requirement-entry-result.v1",
                "schema_version": 1,
                "decision": "resume-required",
                "recovery": recovered,
            }

    published: dict[str, object] = {}
    producer_bytes = _producer_script_bytes()

    def on_manifest_frozen(manifest_ack: dict, candidate: dict) -> bool:
        run_root = Path(manifest_ack["run_root"])
        manifest_path = Path(manifest_ack["manifest_path"])
        if _file_sha256(manifest_path) != manifest_ack["manifest_sha256"]:
            raise OrchestratorError("selection_manifest_drift", "selection manifest digest mismatch")
        readiness_path = run_root / "entry-readiness.json"
        readiness_bytes = _canonical_bytes(readiness_report)
        readiness_digest = hashlib.sha256(readiness_bytes).hexdigest()
        if readiness_digest != entry_readiness_v1.document_digest(readiness_report):
            raise OrchestratorError("readiness_digest_mismatch", "readiness canonical digest mismatch")
        _publish_bytes_no_clobber(readiness_path, readiness_bytes)
        package_selection = freeze_platform_package_selection_v1.build_selection(
            resolution=package_resolution,
            entry_readiness_report_digest=readiness_digest,
            selection_manifest_digest=manifest_ack["manifest_sha256"],
            package_verification_digest=package_verification_digest,
            producer_script_bytes=producer_bytes,
        )
        verify_platform_package_selection_v1.verify_selection(
            package_selection,
            resolution=package_resolution,
            expected_entry_readiness_report_digest=readiness_digest,
            expected_selection_manifest_digest=manifest_ack["manifest_sha256"],
            expected_package_verification_digest=package_verification_digest,
            producer_script_bytes=producer_bytes,
        )
        package_path = run_root / "platform-package-selection.json"
        package_bytes = freeze_platform_package_selection_v1.canonical_bytes(package_selection)
        package_digest = hashlib.sha256(package_bytes).hexdigest()
        _publish_bytes_no_clobber(package_path, package_bytes)
        row_identity_digest = readiness_report["candidate_identity_digest"]
        requirement_id = progress_contract.derive_requirement_id(
            manifest_ack["manifest_sha256"], row_identity_digest
        )
        intent = csv_task_source.prepare_claim_intent(
            resolved_config["task_ref"],
            candidate["title"],
            requirement_id=requirement_id,
            selection_manifest_digest=manifest_ack["manifest_sha256"],
            row_identity_digest=row_identity_digest,
            task_source_snapshot_digest=readiness_report["task_source_snapshot_digest"],
            candidate_identity_digest=readiness_report["candidate_identity_digest"],
        )
        scope = {
            "kind": "icp.requirement-execution-scope.v1",
            "schema_version": 1,
            "requirement_id": requirement_id,
            "task_ref": str(Path(resolved_config["task_ref"])),
            "row_identity": candidate["title"],
            "selection_manifest_path": str(manifest_path),
            "selection_manifest_digest": manifest_ack["manifest_sha256"],
            "entry_readiness_path": str(readiness_path),
            "entry_readiness_digest": readiness_digest,
            "platform_package_selection_path": str(package_path),
            "platform_package_selection_digest": package_digest,
            "verified_operation_plan_digest": verified_operation_plan_digest,
            "feature_positions": copy.deepcopy(feature_positions),
        }
        callback_store = RequirementStateStore(Path(manifest_ack["state_root"]) / "icp-requirements-v1")
        with callback_store.exclusive_lock():
            callback_store.publish_claim_intent(intent)
            callback_store.publish_execution_scope(scope)
        published.update(
            {
                "requirement_id": requirement_id,
                "readiness_path": str(readiness_path),
                "readiness_digest": readiness_digest,
                "package_path": str(package_path),
                "package_digest": package_digest,
            }
        )
        return True

    preparation = prepare_selection.prepare_selection_with_entry_gate(
        resolved_config=resolved_config,
        limit=1,
        readiness_report=readiness_report,
        entry_gate_decision=entry_gate_decision,
        package_resolution=package_resolution,
        registries=registries,
        batch_id=batch_id,
        on_manifest_frozen=on_manifest_frozen,
    )
    preparation_ack = preparation.get("preparation_ack")
    if (
        not isinstance(preparation_ack, dict)
        or not preparation_ack.get("ok")
        or preparation_ack.get("successful_count") != 1
    ):
        return {
            "kind": "icp.requirement-entry-result.v1",
            "schema_version": 1,
            "decision": "claim-failed",
            "preparation": preparation,
            "published": published,
        }
    with durable_store.exclusive_lock():
        activation = recover_pending_csv_claim(durable_store)
    if activation["decision"] != "claim-activated":
        raise OrchestratorError("claim_activation_failed", "claimed requirement was not activated")
    return {
        "kind": "icp.requirement-entry-result.v1",
        "schema_version": 1,
        "decision": "requirement-activated",
        "requirement_id": activation["active"]["requirement_id"],
        "preparation": preparation,
        "published": published,
        "activation": activation,
    }


def decide_stored_resume(
    store: RequirementStateStore,
    *,
    prerequisites_status: str,
    observed_row_status: str,
) -> dict:
    """Return the exact next checkpoint action for the persisted active requirement."""
    store._require_lock()
    snapshot = store.load_snapshot()
    active = snapshot["active"]
    progress = snapshot["progress"]
    if active is None:
        empty_identities = {
            "requirement_id": "0" * 64,
            "selection_manifest_digest": "0" * 64,
            "row_identity_digest": "0" * 64,
            "claim_intent_digest": "0" * 64,
            "claim_ack_digest": "0" * 64,
            "progress_id": "0" * 64,
            "verified_operation_plan_digest": "0" * 64,
        }
        return progress_contract.decide_resume(
            [],
            progress=None,
            receipts=[],
            expected_identities=empty_identities,
            exclusive_lock_acquired=True,
            prerequisites_status=prerequisites_status,
            observed_row_status=observed_row_status,
        )
    scope = store.load_execution_scope(active["requirement_id"])
    _verify_scope_artifacts(scope)
    intent_path = store._directory("claim-intents") / f"{active['requirement_id']}.json"
    intent = store._read_json(intent_path)
    claim_contract.verify_claim_intent(intent)
    expected_identities = {
        "requirement_id": scope["requirement_id"],
        "selection_manifest_digest": scope["selection_manifest_digest"],
        "row_identity_digest": intent["row_identity_digest"],
        "claim_intent_digest": claim_contract.document_digest(intent),
        "claim_ack_digest": active["claim_ack_digest"],
        "progress_id": active["progress_id"],
        "verified_operation_plan_digest": scope["verified_operation_plan_digest"],
    }
    return progress_contract.decide_resume(
        [active],
        progress=progress,
        receipts=snapshot["receipts"],
        expected_identities=expected_identities,
        exclusive_lock_acquired=True,
        prerequisites_status=prerequisites_status,
        observed_row_status=observed_row_status,
    )


def build_execution_checkpoint_receipt(
    *,
    progress: dict,
    platform_id: str,
    feature_id: str | None,
    step_id: str,
    execution_mode: str,
    input_artifact_digests: dict[str, str],
    output_artifact_digests: dict[str, str],
    producer_digest: str,
    verifier_digest: str,
) -> dict:
    """Build the common checkpoint receipt for any selected platform package."""
    progress_contract.verify_progress(progress)
    if not isinstance(platform_id, str) or not platform_id or len(platform_id) > 64:
        raise OrchestratorError("invalid_platform_id", "platform id is invalid")
    if not isinstance(input_artifact_digests, dict) or not isinstance(output_artifact_digests, dict):
        raise OrchestratorError("invalid_artifact_digests", "artifact digests must be objects")
    artifacts = {
        "input": [{"id": key, "digest": input_artifact_digests[key]} for key in sorted(input_artifact_digests)],
        "output": [{"id": key, "digest": output_artifact_digests[key]} for key in sorted(output_artifact_digests)],
    }
    receipt_seed = {
        "platform_id": platform_id,
        "progress_id": progress["progress_id"],
        "sequence": progress["checkpoint_count"],
        "feature_id": feature_id,
        "step_id": step_id,
        "execution_mode": execution_mode,
        "artifacts": artifacts,
        "producer_digest": producer_digest,
        "verifier_digest": verifier_digest,
    }
    receipt = {
        "kind": progress_contract.KIND_CHECKPOINT_RECEIPT,
        "schema_version": 1,
        "receipt_id": hashlib.sha256(
            b"icp.execution-checkpoint.v1\x00" + _canonical_bytes(receipt_seed)
        ).hexdigest(),
        "requirement_id": progress["requirement_id"],
        "progress_id": progress["progress_id"],
        "claim_ack_digest": progress["claim_ack_digest"],
        "sequence": progress["checkpoint_count"],
        "previous_receipt_digest": progress["latest_checkpoint_receipt_digest"]
        or progress_contract.GENESIS_RECEIPT_DIGEST,
        "feature_id": feature_id,
        "step_id": step_id,
        "execution_mode": execution_mode,
        "input_artifact_digests": artifacts["input"],
        "output_artifact_digests": artifacts["output"],
        "producer_digest": producer_digest,
        "verifier_digest": verifier_digest,
    }
    progress_contract.verify_checkpoint_receipt(receipt)
    return receipt


def finalize_active_csv_requirement(
    store: RequirementStateStore,
    *,
    outcome: str,
    evidence: dict,
) -> dict:
    """Durably write back one terminal result, seal evidence, and clear mutable state."""
    store._require_lock()
    if outcome not in csv_task_source.WRITEBACK_OUTCOMES:
        raise OrchestratorError("invalid_terminal_status", "terminal status must be done or error")
    snapshot = store.load_snapshot()
    active = snapshot["active"]
    progress = snapshot["progress"]
    if active is None or progress is None:
        raise OrchestratorError("no_active_requirement", "terminal writeback requires active state")
    scope = store.load_execution_scope(active["requirement_id"])
    _verify_scope_artifacts(scope)
    if progress["phase"] != "terminal-pending":
        if outcome == "done" and any(item["state"] != "done" for item in progress["feature_positions"]):
            raise OrchestratorError("features_not_done", "done writeback requires every feature to be done")
        terminal_progress = copy.deepcopy(progress)
        terminal_progress["revision"] += 1
        terminal_progress["phase"] = "terminal-pending"
        store.replace_progress(terminal_progress, expected_revision=progress["revision"])
        progress = terminal_progress
    transaction = store.load_terminal_transaction(active["requirement_id"])
    if transaction is None:
        intent_path = store._directory("claim-intents") / f"{active['requirement_id']}.json"
        claim_intent = store._read_json(intent_path)
        claim_contract.verify_claim_intent(claim_intent)
        recovery = csv_task_source.recover_claim_with_intent(
            scope["task_ref"], scope["row_identity"], claim_intent
        )
        claim_ack = recovery["claim_ack"]
        if claim_ack is None:
            raise OrchestratorError("claim_ack_unavailable", "cannot reconstruct claim ack before writeback")
        writeback_intent = csv_task_source.prepare_writeback_intent(
            scope["task_ref"], claim_ack, outcome=outcome
        )
        transaction = {
            "kind": "icp.terminal-writeback-transaction.v1",
            "schema_version": 1,
            "requirement_id": active["requirement_id"],
            "claim_ack": claim_ack,
            "writeback_intent": writeback_intent,
        }
        store.publish_terminal_transaction(transaction)
    if transaction["writeback_intent"]["outcome"] != outcome:
        raise OrchestratorError("terminal_status_drift", "persisted terminal outcome differs")
    writeback = csv_task_source.recover_writeback_with_intent(
        scope["task_ref"], transaction["claim_ack"], transaction["writeback_intent"]
    )
    writeback_ack = writeback["writeback_ack"]
    if writeback_ack is None:
        raise OrchestratorError("writeback_blocked", "terminal writeback intent is not recoverable")
    writeback_ack_digest = hashlib.sha256(_canonical_bytes(writeback_ack)).hexdigest()
    sealed_document = {
        "kind": "icp.sealed-requirement-evidence.v1",
        "schema_version": 1,
        "requirement_id": active["requirement_id"],
        "terminal_status": outcome,
        "writeback_ack_digest": writeback_ack_digest,
        "checkpoint_chain_digest": store._checkpoint_chain_digest(snapshot["receipts"]),
        "evidence": copy.deepcopy(evidence),
    }
    sealed_digest = store.seal_evidence(active["requirement_id"], sealed_document)
    cleanup_plan = progress_contract.plan_terminal_cleanup(
        active,
        progress,
        terminal_status=outcome,
        writeback_ack_digest=writeback_ack_digest,
        expected_writeback_ack_digest=writeback_ack_digest,
        sealed_evidence_digest=sealed_digest,
    )
    cleanup_report = store.complete_terminal_cleanup(cleanup_plan)
    return {
        "kind": "icp.terminal-requirement-result.v1",
        "schema_version": 1,
        "requirement_id": active["requirement_id"],
        "terminal_status": outcome,
        "writeback_decision": writeback["decision"],
        "writeback_ack_digest": writeback_ack_digest,
        "sealed_evidence_digest": sealed_digest,
        "cleanup_report": cleanup_report,
    }


__all__ = [
    "OrchestratorError",
    "RequirementStateStore",
    "decide_stored_resume",
    "build_execution_checkpoint_receipt",
    "finalize_active_csv_requirement",
    "prepare_single_requirement_with_entry_gate",
    "recover_pending_csv_claim",
]
