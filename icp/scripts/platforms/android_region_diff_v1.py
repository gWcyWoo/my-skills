#!/usr/bin/env python3
"""Measure frozen Android image regions through vendored iFF visual_diff."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


VENDORED_DIR = Path(__file__).resolve().parents[2] / "vendor" / "iff_v1" / "scripts"
VISUAL_DIFF = VENDORED_DIR / "visual_diff.py"
SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class AndroidRegionDiffError(ValueError):
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
        raise AndroidRegionDiffError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise AndroidRegionDiffError(f"{label} must be an object")
    return value


def _state(contract: dict[str, Any], state_id: str) -> dict[str, Any]:
    designs = contract.get("design_contracts")
    if not isinstance(designs, list):
        raise AndroidRegionDiffError("implementation contract design_contracts are invalid")
    matches = [
        state
        for design in designs
        if isinstance(design, dict)
        for state in design.get("states", [])
        if isinstance(state, dict) and state.get("state_id") == state_id
    ]
    if len(matches) != 1:
        raise AndroidRegionDiffError("design state identity is missing or ambiguous")
    return matches[0]


def _visual_diff_module():
    specification = importlib.util.spec_from_file_location(
        "icp_vendored_visual_diff", VISUAL_DIFF
    )
    if specification is None or specification.loader is None:
        raise AndroidRegionDiffError("vendored visual_diff cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    sys.path.insert(0, str(VENDORED_DIR))
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _crop(
    module: Any,
    source: Path,
    target: Path,
    bbox: list[object],
) -> None:
    width, height, pixels = module.read_png_rgba(source)
    if (
        len(bbox) != 4
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox)
    ):
        raise AndroidRegionDiffError("native design region bbox is invalid")
    x, y, crop_width, crop_height = [int(round(float(value))) for value in bbox]
    if (
        x < 0
        or y < 0
        or crop_width <= 0
        or crop_height <= 0
        or x + crop_width > width
        or y + crop_height > height
    ):
        raise AndroidRegionDiffError("native design region bbox escapes the image")
    cropped = [
        pixels[row * width + column]
        for row in range(y, y + crop_height)
        for column in range(x, x + crop_width)
    ]
    module.write_png_rgba(target, crop_width, crop_height, cropped)


def _measure_region(
    *,
    module: Any,
    reference: Path,
    actual: Path,
    region: dict[str, Any],
    artifacts: Path,
) -> dict[str, object]:
    if (
        set(region) != {"name", "bbox", "max_mismatch_ratio"}
        or not isinstance(region["name"], str)
        or not region["name"]
        or not isinstance(region["bbox"], list)
    ):
        raise AndroidRegionDiffError("native design region is invalid")
    slug = SAFE.sub("-", region["name"]).strip("-") or "region"
    region_root = artifacts / slug
    region_root.mkdir(parents=True, exist_ok=True)
    reference_crop = region_root / "reference.png"
    actual_crop = region_root / "actual.png"
    layout = region_root / "layout.json"
    diff_report = region_root / "visual-diff.json"
    heatmap = region_root / "heatmap.png"
    _crop(module, reference, reference_crop, region["bbox"])
    _crop(module, actual, actual_crop, region["bbox"])
    layout.write_text("{}\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(VENDORED_DIR)
    result = subprocess.run(
        [
            sys.executable,
            str(VISUAL_DIFF),
            "--reference",
            str(reference_crop),
            "--actual",
            str(actual_crop),
            "--layout",
            str(layout),
            "--out",
            str(diff_report),
            "--heatmap",
            str(heatmap),
            "--ssim-threshold",
            "0",
            "--pixel-threshold",
            "1",
        ],
        cwd=VENDORED_DIR,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not diff_report.is_file():
        raise AndroidRegionDiffError("vendored visual_diff did not produce a report")
    vendored = _object(diff_report, "vendored visual_diff report")
    mismatch = vendored.get("pixelMismatchRealDefect")
    if isinstance(mismatch, bool) or not isinstance(mismatch, (int, float)):
        raise AndroidRegionDiffError("vendored visual_diff mismatch ratio is invalid")
    return {
        "name": region["name"],
        "bbox": [float(value) for value in region["bbox"]],
        "mismatch_ratio": float(mismatch),
        "max_mismatch_ratio": float(region["max_mismatch_ratio"]),
        "reference_crop_path": str(reference_crop.resolve()),
        "reference_crop_sha256": _sha(reference_crop),
        "actual_crop_path": str(actual_crop.resolve()),
        "actual_crop_sha256": _sha(actual_crop),
        "vendored_diff_report_path": str(diff_report.resolve()),
        "vendored_diff_report_sha256": _sha(diff_report),
    }


def build_report(
    *,
    reference_path: Path,
    actual_path: Path,
    contract_path: Path,
    state_id: str,
    output_path: Path,
) -> dict[str, object]:
    contract = _object(contract_path, "implementation contract")
    state = _state(contract, state_id)
    regions = state.get("regions")
    if not isinstance(regions, list) or not regions:
        raise AndroidRegionDiffError("design state regions are invalid")
    artifacts = output_path.parent / f"{output_path.stem}.artifacts"
    module = _visual_diff_module()
    measurements = [
        _measure_region(
            module=module,
            reference=reference_path,
            actual=actual_path,
            region=region,
            artifacts=artifacts,
        )
        for region in regions
    ]
    payload: dict[str, object] = {
        "kind": "icp.android-region-measurements.v1",
        "schema_version": 1,
        "state_id": state_id,
        "reference_path": str(reference_path.resolve()),
        "reference_sha256": _sha(reference_path),
        "actual_path": str(actual_path.resolve()),
        "actual_sha256": _sha(actual_path),
        "implementation_contract_path": str(contract_path.resolve()),
        "implementation_contract_sha256": _sha(contract_path),
        "measurements": measurements,
        "errors": [],
        "status": "pass",
    }
    payload["report_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--state-id", required=True)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()
    output = Path(arguments.out)
    try:
        report = build_report(
            reference_path=Path(arguments.reference),
            actual_path=Path(arguments.actual),
            contract_path=Path(arguments.contract),
            state_id=arguments.state_id,
            output_path=output,
        )
    except (AndroidRegionDiffError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok Android region measurements: {len(report['measurements'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
