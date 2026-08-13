#!/usr/bin/env python3
"""Strict high-assurance visual verification over two clean runtime captures."""
from __future__ import annotations

import hashlib
import json
import math
import stat
from pathlib import Path
from typing import Any

from shared_core import visual_evidence_v1


class VisualVerificationError(ValueError):
    pass


KIND = "icp.visual-verification.v1"
CLASSIFICATIONS = (
    "capture-normalization",
    "layout",
    "typography",
    "color",
    "asset",
    "state",
)
CALIBRATION_KEYS = (
    "reference_width",
    "reference_height",
    "runtime_width",
    "runtime_height",
    "density",
    "font_scale",
    "locale",
    "theme",
    "system_bars",
    "animations_disabled",
)


def _regular_absolute(path_value: Path | str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise VisualVerificationError(f"{label} path must be absolute")
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise VisualVerificationError(f"{label} must be a regular non-symlink file")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise VisualVerificationError(f"duplicate evidence key: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise VisualVerificationError("visual evidence manifest must be an object")
    return value


def _number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < minimum
    ):
        raise VisualVerificationError(f"{label} is invalid")
    return float(value)


def _name(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise VisualVerificationError(f"{label} is invalid")
    return value


def _calibration(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or tuple(value) != CALIBRATION_KEYS:
        raise VisualVerificationError("visual calibration shape is invalid")
    result: dict[str, object] = {}
    for field in (
        "reference_width",
        "reference_height",
        "runtime_width",
        "runtime_height",
    ):
        dimension = value[field]
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise VisualVerificationError(f"visual calibration {field} is invalid")
        result[field] = dimension
    if (result["reference_width"], result["reference_height"]) != (
        result["runtime_width"],
        result["runtime_height"],
    ):
        raise VisualVerificationError("reference and runtime viewports must match before repair")
    result["density"] = _number(value["density"], "visual calibration density", minimum=0.000001)
    result["font_scale"] = _number(
        value["font_scale"], "visual calibration font_scale", minimum=0.000001
    )
    for field in ("locale", "theme", "system_bars"):
        result[field] = _name(value[field], f"visual calibration {field}")
    if value["animations_disabled"] is not True:
        raise VisualVerificationError("animations must be disabled for deterministic capture")
    result["animations_disabled"] = True
    return result


def _evidence_run(path_value: object) -> tuple[dict[str, str], dict[str, Any]]:
    path = _regular_absolute(str(path_value), "visual evidence")
    manifest = _strict_json(path)
    try:
        visual_evidence_v1.verify_evidence(manifest)
    except (OSError, ValueError) as exc:
        raise VisualVerificationError("nested visual evidence is invalid") from exc
    if manifest["status"] != "pass":
        raise VisualVerificationError("both final visual evidence runs must pass")
    provenance = _strict_json(Path(manifest["actual"]["provenance_path"]))
    capture_id = _name(provenance.get("capture_id"), "visual capture_id")
    state_reset_id = _name(provenance.get("state_reset_id"), "visual state_reset_id")
    return (
        {
            "evidence_path": str(path),
            "evidence_sha256": _sha(path),
            "actual_sha256": str(manifest["actual"]["sha256"]),
            "capture_id": capture_id,
            "state_reset_id": state_reset_id,
        },
        manifest,
    )


def _anchor(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or tuple(value) != (
        "name",
        "expected",
        "actual",
        "tolerance",
    ):
        raise VisualVerificationError("visual anchor input shape is invalid")
    expected = _number(value["expected"], "visual anchor expected")
    actual = _number(value["actual"], "visual anchor actual")
    tolerance = _number(value["tolerance"], "visual anchor tolerance")
    delta = abs(actual - expected)
    status = "pass" if delta <= tolerance else "fail"
    if status != "pass":
        raise VisualVerificationError(f"visual anchor {value.get('name')} did not pass")
    return {
        "name": _name(value["name"], "visual anchor name"),
        "expected": expected,
        "actual": actual,
        "tolerance": tolerance,
        "delta": delta,
        "status": status,
    }


def _region(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or tuple(value) != (
        "name",
        "mismatch_ratio",
        "max_mismatch_ratio",
    ):
        raise VisualVerificationError("visual region input shape is invalid")
    mismatch = _number(value["mismatch_ratio"], "visual region mismatch_ratio")
    maximum = _number(value["max_mismatch_ratio"], "visual region max_mismatch_ratio")
    if mismatch > 1 or maximum > 1:
        raise VisualVerificationError("visual region mismatch ratios must be in [0,1]")
    status = "pass" if mismatch <= maximum else "fail"
    if status != "pass":
        raise VisualVerificationError(f"visual region {value.get('name')} did not pass")
    return {
        "name": _name(value["name"], "visual region name"),
        "mismatch_ratio": mismatch,
        "max_mismatch_ratio": maximum,
        "status": status,
    }


def _state(value: object, calibration: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, dict) or tuple(value) != (
        "name",
        "contract",
        "final_runs",
        "anchors",
        "regions",
    ):
        raise VisualVerificationError("visual state input shape is invalid")
    name = _name(value["name"], "visual state name")
    contract = _name(value["contract"], "visual state contract")
    final_paths = value["final_runs"]
    if not isinstance(final_paths, list) or len(final_paths) != 2:
        raise VisualVerificationError("visual state requires exactly two clean final runs")
    run_values: list[dict[str, str]] = []
    manifests: list[dict[str, Any]] = []
    for path_value in final_paths:
        run, manifest = _evidence_run(path_value)
        run_values.append(run)
        manifests.append(manifest)
    if (
        len({run["evidence_path"] for run in run_values}) != 2
        or len({run["capture_id"] for run in run_values}) != 2
        or len({run["state_reset_id"] for run in run_values}) != 2
    ):
        raise VisualVerificationError("visual state requires two distinct runtime captures")
    if len({manifest["reference"]["sha256"] for manifest in manifests}) != 1:
        raise VisualVerificationError("final visual runs must use the same design reference")
    expected_dimensions = (
        calibration["reference_width"],
        calibration["reference_height"],
    )
    if any(
        (manifest["reference"]["width"], manifest["reference"]["height"])
        != expected_dimensions
        for manifest in manifests
    ):
        raise VisualVerificationError("visual evidence dimensions do not match calibration")
    anchor_inputs = value["anchors"]
    region_inputs = value["regions"]
    if not isinstance(anchor_inputs, list) or not anchor_inputs:
        raise VisualVerificationError("visual state requires geometry anchors")
    if not isinstance(region_inputs, list) or not region_inputs:
        raise VisualVerificationError("visual state requires regional pixel metrics")
    anchors = [_anchor(anchor) for anchor in anchor_inputs]
    regions = [_region(region) for region in region_inputs]
    if len({anchor["name"] for anchor in anchors}) != len(anchors):
        raise VisualVerificationError("visual anchor names must be unique per state")
    if len({region["name"] for region in regions}) != len(regions):
        raise VisualVerificationError("visual region names must be unique per state")
    return {
        "name": name,
        "contract": contract,
        "final_runs": run_values,
        "anchors": anchors,
        "regions": regions,
    }


def _history(values: object, state_names: set[str]) -> list[dict[str, object]]:
    if not isinstance(values, list):
        raise VisualVerificationError("visual repair history must be a list")
    result: list[dict[str, object]] = []
    stalled: dict[tuple[str, str, str], int] = {}
    for expected_iteration, value in enumerate(values, start=1):
        if not isinstance(value, dict) or tuple(value) != (
            "iteration",
            "state",
            "classification",
            "target",
            "before_score",
            "after_score",
        ):
            raise VisualVerificationError("visual repair history shape is invalid")
        if value["iteration"] != expected_iteration:
            raise VisualVerificationError("visual repair iterations must be consecutive")
        state = _name(value["state"], "visual repair state")
        if state not in state_names:
            raise VisualVerificationError("visual repair state is not declared")
        classification = value["classification"]
        if classification not in CLASSIFICATIONS:
            raise VisualVerificationError("visual repair classification is invalid")
        target = _name(value["target"], "visual repair target")
        before = _number(value["before_score"], "visual repair before_score")
        after = _number(value["after_score"], "visual repair after_score")
        if before > 1 or after > 1:
            raise VisualVerificationError("visual repair scores must be in [0,1]")
        outcome = "improved" if after < before else "no-progress"
        key = (state, str(classification), target)
        stalled[key] = 0 if outcome == "improved" else stalled.get(key, 0) + 1
        if stalled[key] >= 2:
            raise VisualVerificationError(
                "two consecutive no-progress repairs require controlled failure"
            )
        result.append(
            {
                "iteration": expected_iteration,
                "state": state,
                "classification": classification,
                "target": target,
                "before_score": before,
                "after_score": after,
                "outcome": outcome,
            }
        )
    return result


def build_verification(
    *,
    calibration: dict[str, object],
    states: list[dict[str, object]],
    repair_history: list[dict[str, object]],
) -> dict[str, object]:
    normalized_calibration = _calibration(calibration)
    if not isinstance(states, list) or not states:
        raise VisualVerificationError("visual verification requires at least one state")
    normalized_states = [_state(state, normalized_calibration) for state in states]
    state_names = {str(state["name"]) for state in normalized_states}
    if len(state_names) != len(normalized_states):
        raise VisualVerificationError("visual state names must be unique")
    document: dict[str, object] = {
        "kind": KIND,
        "schema_version": 1,
        "calibration": normalized_calibration,
        "states": normalized_states,
        "repair_history": _history(repair_history, state_names),
        "status": "pass",
    }
    verify_verification(document)
    return document


def _verify_run(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or tuple(value) != (
        "evidence_path",
        "evidence_sha256",
        "actual_sha256",
        "capture_id",
        "state_reset_id",
    ):
        raise VisualVerificationError("visual final run shape is invalid")
    path = _regular_absolute(value["evidence_path"], "visual evidence")
    if value["evidence_sha256"] != _sha(path):
        raise VisualVerificationError("visual evidence manifest digest drift")
    manifest = _strict_json(path)
    try:
        visual_evidence_v1.verify_evidence(manifest)
    except (OSError, ValueError) as exc:
        raise VisualVerificationError("nested visual evidence is invalid") from exc
    if manifest["status"] != "pass" or value["actual_sha256"] != manifest["actual"]["sha256"]:
        raise VisualVerificationError("visual final run did not pass")
    provenance = _strict_json(Path(manifest["actual"]["provenance_path"]))
    if (
        value["capture_id"] != _name(provenance.get("capture_id"), "visual capture_id")
        or value["state_reset_id"]
        != _name(provenance.get("state_reset_id"), "visual state_reset_id")
    ):
        raise VisualVerificationError("visual final run provenance drift")
    return manifest


def verify_verification(document: dict[str, object]) -> None:
    if not isinstance(document, dict) or tuple(document) != (
        "kind",
        "schema_version",
        "calibration",
        "states",
        "repair_history",
        "status",
    ):
        raise VisualVerificationError("visual verification shape is invalid")
    if document["kind"] != KIND or document["schema_version"] != 1:
        raise VisualVerificationError("visual verification identity is invalid")
    calibration = _calibration(document["calibration"])
    states = document["states"]
    if not isinstance(states, list) or not states:
        raise VisualVerificationError("visual verification requires at least one state")
    state_names: set[str] = set()
    for state in states:
        if not isinstance(state, dict) or tuple(state) != (
            "name",
            "contract",
            "final_runs",
            "anchors",
            "regions",
        ):
            raise VisualVerificationError("visual state shape is invalid")
        name = _name(state["name"], "visual state name")
        _name(state["contract"], "visual state contract")
        if name in state_names:
            raise VisualVerificationError("visual state names must be unique")
        state_names.add(name)
        runs = state["final_runs"]
        if not isinstance(runs, list) or len(runs) != 2:
            raise VisualVerificationError("visual state requires exactly two clean final runs")
        manifests = [_verify_run(run) for run in runs]
        if (
            len({run["evidence_path"] for run in runs}) != 2
            or len({run["capture_id"] for run in runs}) != 2
            or len({run["state_reset_id"] for run in runs}) != 2
        ):
            raise VisualVerificationError("visual state requires two distinct runtime captures")
        if len({manifest["reference"]["sha256"] for manifest in manifests}) != 1:
            raise VisualVerificationError("final visual runs must use the same design reference")
        expected_dimensions = (
            calibration["reference_width"],
            calibration["reference_height"],
        )
        if any(
            (manifest["reference"]["width"], manifest["reference"]["height"])
            != expected_dimensions
            for manifest in manifests
        ):
            raise VisualVerificationError("visual evidence dimensions do not match calibration")
        anchors = state["anchors"]
        regions = state["regions"]
        if not isinstance(anchors, list) or not anchors:
            raise VisualVerificationError("visual state requires geometry anchors")
        if not isinstance(regions, list) or not regions:
            raise VisualVerificationError("visual state requires regional pixel metrics")
        anchor_names: set[str] = set()
        for anchor in anchors:
            if not isinstance(anchor, dict) or tuple(anchor) != (
                "name",
                "expected",
                "actual",
                "tolerance",
                "delta",
                "status",
            ):
                raise VisualVerificationError("visual anchor shape is invalid")
            anchor_name = _name(anchor["name"], "visual anchor name")
            expected = _number(anchor["expected"], "visual anchor expected")
            actual = _number(anchor["actual"], "visual anchor actual")
            tolerance = _number(anchor["tolerance"], "visual anchor tolerance")
            if (
                anchor_name in anchor_names
                or anchor["delta"] != abs(actual - expected)
                or anchor["status"] != "pass"
                or abs(actual - expected) > tolerance
            ):
                raise VisualVerificationError("visual anchor did not pass")
            anchor_names.add(anchor_name)
        region_names: set[str] = set()
        for region in regions:
            if not isinstance(region, dict) or tuple(region) != (
                "name",
                "mismatch_ratio",
                "max_mismatch_ratio",
                "status",
            ):
                raise VisualVerificationError("visual region shape is invalid")
            region_name = _name(region["name"], "visual region name")
            mismatch = _number(region["mismatch_ratio"], "visual region mismatch_ratio")
            maximum = _number(
                region["max_mismatch_ratio"], "visual region max_mismatch_ratio"
            )
            if (
                region_name in region_names
                or mismatch > 1
                or maximum > 1
                or region["status"] != "pass"
                or mismatch > maximum
            ):
                raise VisualVerificationError("visual region did not pass")
            region_names.add(region_name)
    history = document["repair_history"]
    if not isinstance(history, list):
        raise VisualVerificationError("visual repair history must be a list")
    raw_history: list[dict[str, object]] = []
    for entry in history:
        if not isinstance(entry, dict) or tuple(entry) != (
            "iteration",
            "state",
            "classification",
            "target",
            "before_score",
            "after_score",
            "outcome",
        ):
            raise VisualVerificationError("visual repair history shape is invalid")
        raw_history.append({key: entry[key] for key in tuple(entry)[:-1]})
    if _history(raw_history, state_names) != history:
        raise VisualVerificationError("visual repair history drift")
    if document["status"] != "pass":
        raise VisualVerificationError("visual verification status drift")


__all__ = [
    "CLASSIFICATIONS",
    "KIND",
    "VisualVerificationError",
    "build_verification",
    "verify_verification",
]
