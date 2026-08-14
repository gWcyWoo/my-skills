#!/usr/bin/env python3
"""Measure frozen ICP anchors from one generated iOS XCTest trace."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ATTRIBUTES = {"left", "top", "right", "bottom", "center_x", "center_y", "width", "height"}


class IOSTraceMeasurementError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IOSTraceMeasurementError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise IOSTraceMeasurementError(f"{label} must be an object")
    return value


def _state(contract: dict[str, Any], state_id: str) -> dict[str, Any]:
    designs = contract.get("design_contracts")
    if not isinstance(designs, list):
        raise IOSTraceMeasurementError("implementation contract design_contracts are invalid")
    matches = [
        state
        for design in designs
        if isinstance(design, dict)
        for state in design.get("states", [])
        if isinstance(state, dict) and state.get("state_id") == state_id
    ]
    if len(matches) != 1:
        raise IOSTraceMeasurementError("design state identity is missing or ambiguous")
    return matches[0]


def _coordinate(frame: dict[str, Any], attribute: str) -> float:
    if set(frame) != {"x", "y", "width", "height"} or any(
        isinstance(frame[field], bool) or not isinstance(frame[field], (int, float))
        for field in frame
    ):
        raise IOSTraceMeasurementError("iOS trace frame is invalid")
    left = float(frame["x"])
    top = float(frame["y"])
    width = float(frame["width"])
    height = float(frame["height"])
    values = {
        "left": left,
        "top": top,
        "right": left + width,
        "bottom": top + height,
        "center_x": left + width / 2,
        "center_y": top + height / 2,
        "width": width,
        "height": height,
    }
    return values[attribute]


def build_report(
    *,
    trace_path: Path,
    contract_path: Path,
    state_id: str,
) -> dict[str, object]:
    trace = _object(trace_path, "iOS trace")
    if (
        trace.get("kind") != "icp.ios-native-view-trace.v1"
        or trace.get("schema_version") != 1
        or not isinstance(trace.get("elements"), list)
    ):
        raise IOSTraceMeasurementError("iOS trace identity is invalid")
    contract = _object(contract_path, "implementation contract")
    state = _state(contract, state_id)
    anchors = state.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise IOSTraceMeasurementError("design state anchors are invalid")
    measurements: list[dict[str, object]] = []
    for anchor in anchors:
        if (
            not isinstance(anchor, dict)
            or set(anchor) != {"name", "node_id", "attribute", "expected", "tolerance"}
            or not isinstance(anchor["name"], str)
            or not anchor["name"]
            or not isinstance(anchor["node_id"], str)
            or not anchor["node_id"]
            or anchor["attribute"] not in ATTRIBUTES
        ):
            raise IOSTraceMeasurementError("native design anchor is invalid")
        marker = f"icp:{anchor['node_id']}"
        matches = [
            element
            for element in trace["elements"]
            if isinstance(element, dict) and element.get("identifier") == marker
        ]
        if len(matches) != 1:
            raise IOSTraceMeasurementError(
                f"anchor element {anchor['node_id']} is missing or ambiguous"
            )
        element = matches[0]
        frame = element.get("frame")
        if not isinstance(frame, dict):
            raise IOSTraceMeasurementError("iOS trace frame is invalid")
        measurements.append(
            {
                "name": anchor["name"],
                "node_id": anchor["node_id"],
                "attribute": anchor["attribute"],
                "expected": float(anchor["expected"]),
                "tolerance": float(anchor["tolerance"]),
                "actual_pt": _coordinate(frame, anchor["attribute"]),
                "matched_element": {
                    "identifier": element.get("identifier", ""),
                    "label": element.get("label", ""),
                    "frame_pt": frame,
                },
            }
        )
    payload: dict[str, object] = {
        "kind": "icp.ios-anchor-measurements.v1",
        "schema_version": 1,
        "state_id": state_id,
        "trace_path": str(trace_path.resolve()),
        "trace_sha256": _sha(trace_path),
        "implementation_contract_path": str(contract_path.resolve()),
        "implementation_contract_sha256": _sha(contract_path),
        "measurements": measurements,
        "errors": [],
        "status": "pass",
    }
    payload["report_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def _failure_report(
    *,
    trace_path: Path,
    contract_path: Path,
    state_id: str,
    error: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "icp.ios-anchor-measurements.v1",
        "schema_version": 1,
        "state_id": state_id,
        "trace_path": str(trace_path.resolve()),
        "implementation_contract_path": str(contract_path.resolve()),
        "measurements": [],
        "errors": [error],
        "status": "failed",
    }
    payload["report_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--state-id", required=True)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()
    output = Path(arguments.out)
    trace_path = Path(arguments.trace)
    contract_path = Path(arguments.contract)
    try:
        report = build_report(
            trace_path=trace_path,
            contract_path=contract_path,
            state_id=arguments.state_id,
        )
    except IOSTraceMeasurementError as exc:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                _failure_report(
                    trace_path=trace_path,
                    contract_path=contract_path,
                    state_id=arguments.state_id,
                    error=str(exc),
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"ERROR: {exc}")
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok iOS anchor measurements: {len(report['measurements'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
