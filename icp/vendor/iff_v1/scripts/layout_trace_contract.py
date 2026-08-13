#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LayoutTraceContractError(ValueError):
    pass


def actual_layout_trace_nodes(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise LayoutTraceContractError("actual layout trace must be a JSON object")
    page_type = payload.get("pageType")
    if not isinstance(page_type, str) or not page_type.strip():
        raise LayoutTraceContractError("actual layout trace requires a non-empty pageType")
    nodes = payload.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise LayoutTraceContractError("actual layout trace requires a non-empty top-level nodes object")
    for node_id, record in nodes.items():
        if not isinstance(node_id, str) or not node_id or not isinstance(record, dict):
            raise LayoutTraceContractError("actual layout trace nodes must map non-empty string ids to objects")
    return nodes


def load_actual_layout_trace(
    path: Path,
    *,
    min_mtime_ns: int | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        raise LayoutTraceContractError(f"actual layout trace missing: {path}")
    if min_mtime_ns is not None and path.stat().st_mtime_ns < min_mtime_ns:
        raise LayoutTraceContractError(
            "actual layout trace is stale: "
            f"mtime_ns={path.stat().st_mtime_ns} < required={min_mtime_ns}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LayoutTraceContractError(f"actual layout trace is invalid JSON: {path}: {exc}") from exc
    actual_layout_trace_nodes(payload)
    return payload
