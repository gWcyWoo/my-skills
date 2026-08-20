#!/usr/bin/env python3
"""Deterministic, append-only execution checklists for ICP stages."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


class ChecklistError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(_json_bytes(value))
    os.replace(temporary, path)


def node(
    node_id: str,
    action: str,
    depends_on: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "action": action,
        "depends_on": list(depends_on),
    }


def _definition(stage: str, input_sha256: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stage": stage,
        "input_sha256": input_sha256,
        "nodes": [
            {
                "node_id": item["node_id"],
                "action": item["action"],
                "depends_on": list(item.get("depends_on", [])),
            }
            for item in nodes
        ],
    }


def _validate_specs(nodes: list[dict[str, Any]]) -> None:
    ids = [item.get("node_id") for item in nodes]
    if (
        not nodes
        or any(not isinstance(item, str) or not item for item in ids)
        or len(ids) != len(set(ids))
    ):
        raise ChecklistError("invalid_checklist_definition", "checklist node IDs must be unique strings")
    known: set[str] = set()
    for item in nodes:
        if not isinstance(item.get("action"), str) or not item["action"]:
            raise ChecklistError(
                "invalid_checklist_definition",
                f"checklist action is missing for {item.get('node_id')}",
            )
        dependencies = item.get("depends_on", [])
        if (
            not isinstance(dependencies, list)
            or len(dependencies) != len(set(dependencies))
            or any(dependency not in known for dependency in dependencies)
        ):
            raise ChecklistError(
                "invalid_checklist_definition",
                f"checklist dependencies must reference earlier nodes: {item['node_id']}",
            )
        known.add(item["node_id"])


def create(
    path: Path,
    *,
    stage: str,
    input_sha256: str,
    nodes: list[dict[str, Any]],
    initially_completed: Iterable[str] = (),
) -> dict[str, Any]:
    _validate_specs(nodes)
    definition = _definition(stage, input_sha256, nodes)
    definition_sha256 = _digest(definition)
    if path.is_file():
        checklist = load(path, stage=stage, input_sha256=input_sha256, nodes=nodes)
        return checklist
    completed = set(initially_completed)
    known = {item["node_id"] for item in nodes}
    if not completed.issubset(known):
        raise ChecklistError("invalid_checklist_definition", "initial checklist completion is unknown")
    runtime_nodes: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for item in nodes:
        is_complete = item["node_id"] in completed
        runtime_nodes.append(
            {
                **item,
                "status": "completed" if is_complete else "pending",
                "evidence_sha256": input_sha256 if is_complete else None,
                "invalidated_by": None,
            }
        )
        if is_complete:
            events.append(
                {
                    "sequence": len(events) + 1,
                    "node_id": item["node_id"],
                    "event": "completed",
                    "evidence_sha256": input_sha256,
                }
            )
    checklist = {
        "schema": "icp.stage-checklist",
        "stage": stage,
        "input_sha256": input_sha256,
        "definition_sha256": definition_sha256,
        "nodes": runtime_nodes,
        "events": events,
    }
    _atomic_write(path, checklist)
    return checklist


def load(
    path: Path,
    *,
    stage: str,
    input_sha256: str,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    _validate_specs(nodes)
    try:
        checklist = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChecklistError("checklist_missing", f"stage checklist does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ChecklistError("checklist_drift", f"stage checklist is invalid JSON: {path}") from exc
    definition = _definition(stage, input_sha256, nodes)
    expected_definition_sha256 = _digest(definition)
    if (
        not isinstance(checklist, dict)
        or checklist.get("schema") != "icp.stage-checklist"
        or checklist.get("stage") != stage
        or checklist.get("input_sha256") != input_sha256
        or checklist.get("definition_sha256") != expected_definition_sha256
    ):
        raise ChecklistError("checklist_drift", "stage checklist targets another input or flow")
    runtime_nodes = checklist.get("nodes")
    events = checklist.get("events")
    if not isinstance(runtime_nodes, list) or not isinstance(events, list):
        raise ChecklistError("checklist_drift", "stage checklist runtime data is invalid")
    if len(runtime_nodes) != len(nodes):
        raise ChecklistError("checklist_drift", "stage checklist node count changed")
    for expected, actual in zip(nodes, runtime_nodes, strict=True):
        if (
            not isinstance(actual, dict)
            or {key: actual.get(key) for key in ("node_id", "action", "depends_on")}
            != expected
            or actual.get("status") not in {"pending", "completed"}
            or actual.get("evidence_sha256") is not None
            and not isinstance(actual.get("evidence_sha256"), str)
            or actual.get("invalidated_by") is not None
            and not isinstance(actual.get("invalidated_by"), str)
        ):
            raise ChecklistError("checklist_drift", f"stage checklist node changed: {expected['node_id']}")
    for sequence, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != sequence:
            raise ChecklistError("checklist_drift", "stage checklist event sequence changed")
    replay = {
        item["node_id"]: {
            "status": "pending",
            "evidence_sha256": None,
            "invalidated_by": None,
        }
        for item in nodes
    }
    spec_by_id = {item["node_id"]: item for item in nodes}
    for event in events:
        node_id = event.get("node_id")
        event_kind = event.get("event")
        if node_id not in replay:
            raise ChecklistError("checklist_drift", "stage checklist event targets an unknown node")
        if event_kind == "completed":
            if set(event) != {"sequence", "node_id", "event", "evidence_sha256"}:
                raise ChecklistError("checklist_drift", "stage checklist completion event changed")
            evidence_sha256 = event.get("evidence_sha256")
            if not isinstance(evidence_sha256, str) or not evidence_sha256:
                raise ChecklistError("checklist_drift", "stage checklist completion evidence is invalid")
            if any(
                replay[dependency]["status"] != "completed"
                for dependency in spec_by_id[node_id]["depends_on"]
            ):
                raise ChecklistError("checklist_drift", "stage checklist event skipped a dependency")
            replay[node_id] = {
                "status": "completed",
                "evidence_sha256": evidence_sha256,
                "invalidated_by": None,
            }
        elif event_kind == "invalidated":
            if set(event) != {"sequence", "node_id", "event", "invalidated_by"}:
                raise ChecklistError("checklist_drift", "stage checklist invalidation event changed")
            invalidated_by = event.get("invalidated_by")
            if invalidated_by not in replay:
                raise ChecklistError("checklist_drift", "stage checklist invalidation source is unknown")
            replay[node_id] = {
                "status": "pending",
                "evidence_sha256": None,
                "invalidated_by": invalidated_by,
            }
        else:
            raise ChecklistError("checklist_drift", "stage checklist event kind is invalid")
    for actual in runtime_nodes:
        expected_runtime = replay[actual["node_id"]]
        if any(actual.get(field) != expected_runtime[field] for field in expected_runtime):
            raise ChecklistError(
                "checklist_drift",
                f"stage checklist status is not replayable: {actual['node_id']}",
            )
    return checklist


def _descendants(checklist: dict[str, Any], root_id: str) -> set[str]:
    result = {root_id}
    changed = True
    while changed:
        changed = False
        for item in checklist["nodes"]:
            if item["node_id"] not in result and any(
                dependency in result for dependency in item["depends_on"]
            ):
                result.add(item["node_id"])
                changed = True
    return result


def invalidate(
    path: Path,
    *,
    stage: str,
    input_sha256: str,
    nodes: list[dict[str, Any]],
    node_id: str,
) -> dict[str, Any]:
    checklist = load(path, stage=stage, input_sha256=input_sha256, nodes=nodes)
    by_id = {item["node_id"]: item for item in checklist["nodes"]}
    if node_id not in by_id:
        raise ChecklistError("unknown_checklist_node", f"unknown checklist node: {node_id}")
    affected = _descendants(checklist, node_id)
    for item in checklist["nodes"]:
        if item["node_id"] in affected and item["status"] == "completed":
            item["status"] = "pending"
            item["evidence_sha256"] = None
            item["invalidated_by"] = node_id
            checklist["events"].append(
                {
                    "sequence": len(checklist["events"]) + 1,
                    "node_id": item["node_id"],
                    "event": "invalidated",
                    "invalidated_by": node_id,
                }
            )
    _atomic_write(path, checklist)
    return checklist


def complete(
    path: Path,
    *,
    stage: str,
    input_sha256: str,
    nodes: list[dict[str, Any]],
    node_id: str,
    evidence_sha256: str,
) -> dict[str, Any]:
    checklist = load(path, stage=stage, input_sha256=input_sha256, nodes=nodes)
    by_id = {item["node_id"]: item for item in checklist["nodes"]}
    target = by_id.get(node_id)
    if target is None:
        raise ChecklistError("unknown_checklist_node", f"unknown checklist node: {node_id}")
    missing_dependencies = [
        dependency
        for dependency in target["depends_on"]
        if by_id[dependency]["status"] != "completed"
    ]
    if missing_dependencies:
        missing = missing_dependencies[0]
        action = by_id[missing]["action"]
        raise ChecklistError(
            "checklist_incomplete",
            f"resume_from_node={missing}; required_action={action}; blocked_node={node_id}",
        )
    if target["status"] == "completed" and target["evidence_sha256"] == evidence_sha256:
        return checklist
    if target["status"] == "completed":
        checklist = invalidate(
            path,
            stage=stage,
            input_sha256=input_sha256,
            nodes=nodes,
            node_id=node_id,
        )
        by_id = {item["node_id"]: item for item in checklist["nodes"]}
        target = by_id[node_id]
    target["status"] = "completed"
    target["evidence_sha256"] = evidence_sha256
    target["invalidated_by"] = None
    checklist["events"].append(
        {
            "sequence": len(checklist["events"]) + 1,
            "node_id": node_id,
            "event": "completed",
            "evidence_sha256": evidence_sha256,
        }
    )
    _atomic_write(path, checklist)
    return checklist


def require_ready(
    path: Path,
    *,
    stage: str,
    input_sha256: str,
    nodes: list[dict[str, Any]],
    node_id: str,
) -> dict[str, Any]:
    checklist = load(path, stage=stage, input_sha256=input_sha256, nodes=nodes)
    by_id = {item["node_id"]: item for item in checklist["nodes"]}
    target = by_id.get(node_id)
    if target is None:
        raise ChecklistError("unknown_checklist_node", f"unknown checklist node: {node_id}")
    missing = next(
        (
            by_id[dependency]
            for dependency in target["depends_on"]
            if by_id[dependency]["status"] != "completed"
        ),
        None,
    )
    if missing is not None:
        raise ChecklistError(
            "checklist_incomplete",
            f"resume_from_node={missing['node_id']}; required_action={missing['action']}; blocked_node={node_id}",
        )
    return checklist


def require_complete(
    path: Path,
    *,
    stage: str,
    input_sha256: str,
    nodes: list[dict[str, Any]],
    exclude: Iterable[str] = (),
) -> dict[str, Any]:
    checklist = load(path, stage=stage, input_sha256=input_sha256, nodes=nodes)
    excluded = set(exclude)
    missing = next(
        (
            item
            for item in checklist["nodes"]
            if item["node_id"] not in excluded and item["status"] != "completed"
        ),
        None,
    )
    if missing is not None:
        descendants = [
            item["node_id"]
            for item in checklist["nodes"]
            if item["node_id"] in _descendants(checklist, missing["node_id"])
        ]
        raise ChecklistError(
            "checklist_incomplete",
            "resume_from_node="
            + missing["node_id"]
            + "; required_action="
            + missing["action"]
            + "; revalidate_nodes="
            + ",".join(descendants),
        )
    return checklist
