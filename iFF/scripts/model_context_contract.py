#!/usr/bin/env python3
"""Pure contracts shared by iFF prompt, packet, and context tooling."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def expected_workers(feature_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    states = feature_manifest.get("states")
    if not isinstance(states, dict) or not states:
        raise ValueError("feature manifest states must be a non-empty object")
    workers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for state, value in sorted(states.items()):
        if not isinstance(value, dict):
            raise ValueError(f"feature state must be an object: {state}")
        board = value.get("board")
        if not isinstance(board, str) or not board.strip():
            raise ValueError(f"feature state has no board: {state}")
        board = board.strip()
        if board in seen:
            raise ValueError(f"feature states share board: {board}")
        seen.add(board)
        workers.append(
            {"id": f"board--{board}", "role": "board", "board": board}
        )
    workers.append({"id": "assembly", "role": "assembly", "board": None})
    return workers


def render_contract(contract_input: dict[str, Any]) -> bytes:
    worker = contract_input.get("worker") or {}
    worker_id = str(worker.get("id") or "")
    role = str(worker.get("role") or "")
    if not worker_id or role not in {"board", "assembly"}:
        raise ValueError("contract input has invalid worker")
    body = contract_input.get("body")
    if body is not None and not isinstance(body, str):
        raise ValueError("contract body must be text")
    canonical = json.dumps(
        {key: value for key, value in contract_input.items() if key != "body"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    text = (
        f"IFF_WORKER_CONTRACT v3\n"
        f"worker={worker_id} role={role}\n"
        f"contract-input={canonical}\n"
        f"{body or ''}"
    )
    return text.encode("utf-8")


def validate_packet(
    packet: dict[str, Any], expected: dict[str, Any], project_root: Path
) -> list[str]:
    errors: list[str] = []
    if packet.get("version") != 2:
        errors.append("packet version must be 2")
    if packet.get("kind") != expected.get("kind"):
        errors.append("packet kind mismatch")
    if packet.get("scope") != expected.get("scope"):
        errors.append("packet scope mismatch")

    sources = packet.get("sources")
    if not isinstance(sources, dict) or not sources:
        errors.append("packet sources must be a non-empty object")
        sources = {}
    required = set(expected.get("requiredSources") or [])
    missing = sorted(required - set(sources))
    if missing:
        errors.append("packet sources missing: " + ", ".join(missing))
    project_root = project_root.resolve()
    for label, source in sorted(sources.items()):
        if not isinstance(source, dict):
            errors.append(f"packet source must be an object: {label}")
            continue
        path = Path(str(source.get("path") or "")).expanduser().resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            errors.append(f"packet source outside project: {label}")
            continue
        if not path.is_file():
            errors.append(f"packet source missing: {label}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if source.get("sha256") != actual:
            errors.append(f"packet source stale: {label}")

    action = packet.get("action")
    if "actions" in packet:
        errors.append("exactly one action object is required")
    if not isinstance(action, dict) or not action.get("kind"):
        errors.append("packet action.kind is required")
        return errors
    allowed = set(expected.get("allowedActions") or [])
    if action.get("kind") not in allowed:
        errors.append(f"packet action is not allowed: {action.get('kind')}")
    if action.get("kind") == "none":
        if not str(action.get("reason") or "").strip():
            errors.append("packet none action requires reason")
    elif not isinstance(action.get("allowedDecisions"), list) or not action.get(
        "allowedDecisions"
    ):
        errors.append("model action requires allowedDecisions")
    allowed_write_paths = action.get("allowedWritePaths")
    required_by_decision = action.get("requiredWritePathsByDecision")
    if allowed_write_paths is not None or required_by_decision is not None:
        if not isinstance(allowed_write_paths, list) or not allowed_write_paths:
            errors.append("write contract requires allowedWritePaths")
        if not isinstance(required_by_decision, dict) or not required_by_decision:
            errors.append("write contract requires requiredWritePathsByDecision")
        if isinstance(allowed_write_paths, list) and isinstance(
            required_by_decision, dict
        ):
            declared_sources = set(sources)
            allowed_paths = set(allowed_write_paths)
            required_paths = {
                path
                for paths in required_by_decision.values()
                if isinstance(paths, list)
                for path in paths
            }
            if allowed_paths != required_paths:
                errors.append("write contract allowed and required paths differ")
            if set(required_by_decision) != set(action.get("allowedDecisions") or []):
                errors.append("write contract decisions differ from allowedDecisions")
            for target in sorted(allowed_paths):
                label, separator, dotted = str(target).partition(":")
                if not separator or not dotted or label not in declared_sources:
                    errors.append(f"write contract source is not declared: {target}")
    return errors


def persist_model_input(
    payload: bytes, *, kind: str, owner: str, ledger: Path
) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    ledger = ledger.expanduser().resolve()
    blob_dir = ledger.parent / "model_context_blobs"
    blob_dir.mkdir(parents=True, exist_ok=True)
    blob = blob_dir / f"{digest}.bin"
    if not blob.is_file():
        temporary = blob.with_name(f".{blob.name}.{os.getpid()}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, blob)
    elif blob.read_bytes() != payload:
        raise ValueError(f"model input digest collision: {digest}")
    entry = {
        "kind": kind,
        "owner": owner,
        "bytes": len(payload),
        "sha256": digest,
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
    return entry


def packet_source(path: Path) -> dict[str, str]:
    path = path.expanduser().resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def attach_write_contract(
    action: dict[str, Any], paths_by_decision: dict[str, list[str]]
) -> None:
    normalized = {
        decision: sorted(set(paths))
        for decision, paths in paths_by_decision.items()
        if paths
    }
    if not normalized:
        return
    action["requiredWritePathsByDecision"] = normalized
    action["allowedWritePaths"] = sorted(
        {path for paths in normalized.values() for path in paths}
    )


def write_model_packet(
    packet: dict[str, Any],
    out: Path,
    *,
    max_bytes: int,
    ledger: Path | None,
    owner: str,
) -> int:
    encoded = (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError(f"model packet is {len(encoded)} bytes > {max_bytes}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded)
    if ledger is not None:
        persist_model_input(
            encoded,
            kind=f"{packet.get('kind')}_model_packet",
            owner=owner,
            ledger=ledger,
        )
    return len(encoded)
