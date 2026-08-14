#!/usr/bin/env python3
"""Measure frozen ICP anchors from one Android UIAutomator hierarchy."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ANDROID_BASE_DENSITY_DPI = 160.0
BOUNDS = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")
DENSITY = re.compile(r"^(Physical|Override) density: ([1-9]\d*)$", re.MULTILINE)
ATTRIBUTES = {"left", "top", "right", "bottom", "center_x", "center_y", "width", "height"}


class AndroidTraceMeasurementError(ValueError):
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


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AndroidTraceMeasurementError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise AndroidTraceMeasurementError(f"{label} must be an object")
    return value


def _density(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AndroidTraceMeasurementError("Android density output is invalid") from exc
    values = {name.lower(): int(number) for name, number in DENSITY.findall(raw)}
    if not values:
        raise AndroidTraceMeasurementError("Android density output has no measured density")
    source = "override" if "override" in values else "physical"
    effective = values[source]
    return {
        "source": source,
        "effective_dpi": effective,
        "dp_per_px": ANDROID_BASE_DENSITY_DPI / effective,
        "raw_sha256": _sha(path),
    }


def _state(contract: dict[str, Any], state_id: str) -> dict[str, Any]:
    designs = contract.get("design_contracts")
    if not isinstance(designs, list):
        raise AndroidTraceMeasurementError("implementation contract design_contracts are invalid")
    matches = [
        state
        for design in designs
        if isinstance(design, dict)
        for state in design.get("states", [])
        if isinstance(state, dict) and state.get("state_id") == state_id
    ]
    if len(matches) != 1:
        raise AndroidTraceMeasurementError("design state identity is missing or ambiguous")
    return matches[0]


def _coordinate(bounds: tuple[int, int, int, int], attribute: str) -> float:
    left, top, right, bottom = bounds
    values = {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "center_x": (left + right) / 2,
        "center_y": (top + bottom) / 2,
        "width": right - left,
        "height": bottom - top,
    }
    return float(values[attribute])


def _matching_node(root: ET.Element, node_id: str) -> tuple[ET.Element, tuple[int, int, int, int]]:
    marker = f"icp:{node_id}"
    matches: list[tuple[ET.Element, tuple[int, int, int, int]]] = []
    for node in root.iter("node"):
        resource_id = node.attrib.get("resource-id", "")
        content_desc = node.attrib.get("content-desc", "")
        if marker not in {resource_id, content_desc}:
            continue
        bound_match = BOUNDS.fullmatch(node.attrib.get("bounds", ""))
        if bound_match is None:
            raise AndroidTraceMeasurementError(f"anchor node {node_id} has invalid bounds")
        matches.append((node, tuple(int(value) for value in bound_match.groups())))
    if len(matches) != 1:
        raise AndroidTraceMeasurementError(f"anchor node {node_id} is missing or ambiguous")
    return matches[0]


def build_report(
    *,
    hierarchy_path: Path,
    contract_path: Path,
    state_id: str,
    density_output_path: Path,
) -> dict[str, object]:
    contract = _read_object(contract_path, "implementation contract")
    density = _density(density_output_path)
    try:
        hierarchy = ET.parse(hierarchy_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise AndroidTraceMeasurementError("UIAutomator hierarchy is invalid") from exc
    if hierarchy.tag != "hierarchy":
        raise AndroidTraceMeasurementError("UIAutomator hierarchy root is invalid")
    state = _state(contract, state_id)
    anchors = state.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise AndroidTraceMeasurementError("design state anchors are invalid")
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
            raise AndroidTraceMeasurementError("native design anchor is invalid")
        node, bounds = _matching_node(hierarchy, anchor["node_id"])
        actual_px = _coordinate(bounds, anchor["attribute"])
        actual_dp = actual_px * float(density["dp_per_px"])
        measurements.append(
            {
                "name": anchor["name"],
                "node_id": anchor["node_id"],
                "attribute": anchor["attribute"],
                "expected": float(anchor["expected"]),
                "tolerance": float(anchor["tolerance"]),
                "actual_px": actual_px,
                "actual_dp": actual_dp,
                "matched_node": {
                    "resource_id": node.attrib.get("resource-id", ""),
                    "content_desc": node.attrib.get("content-desc", ""),
                    "bounds_px": list(bounds),
                },
            }
        )
    payload: dict[str, object] = {
        "kind": "icp.android-anchor-measurements.v1",
        "schema_version": 1,
        "state_id": state_id,
        "hierarchy_path": str(hierarchy_path.resolve()),
        "hierarchy_sha256": _sha(hierarchy_path),
        "implementation_contract_path": str(contract_path.resolve()),
        "implementation_contract_sha256": _sha(contract_path),
        "density_output_path": str(density_output_path.resolve()),
        "density": density,
        "measurements": measurements,
        "errors": [],
        "status": "pass",
    }
    payload["report_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _failure_report(
    *,
    hierarchy_path: Path,
    contract_path: Path,
    state_id: str,
    density_output_path: Path,
    error: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "icp.android-anchor-measurements.v1",
        "schema_version": 1,
        "state_id": state_id,
        "hierarchy_path": str(hierarchy_path.resolve()),
        "implementation_contract_path": str(contract_path.resolve()),
        "density_output_path": str(density_output_path.resolve()),
        "measurements": [],
        "errors": [error],
        "status": "failed",
    }
    payload["report_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hierarchy", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--state-id", required=True)
    parser.add_argument("--density-output", required=True)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()
    hierarchy_path = Path(arguments.hierarchy)
    contract_path = Path(arguments.contract)
    density_output_path = Path(arguments.density_output)
    output_path = Path(arguments.out)
    try:
        report = build_report(
            hierarchy_path=hierarchy_path,
            contract_path=contract_path,
            state_id=arguments.state_id,
            density_output_path=density_output_path,
        )
    except AndroidTraceMeasurementError as exc:
        _write(
            output_path,
            _failure_report(
                hierarchy_path=hierarchy_path,
                contract_path=contract_path,
                state_id=arguments.state_id,
                density_output_path=density_output_path,
                error=str(exc),
            ),
        )
        print(f"ERROR: {exc}")
        return 2
    _write(output_path, report)
    print(f"ok Android anchor measurements: {len(report['measurements'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
