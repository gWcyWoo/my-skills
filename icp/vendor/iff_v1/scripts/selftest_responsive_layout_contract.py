#!/usr/bin/env python3
"""Regression tests for generated multi-viewport responsive contracts and gates."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPTS = Path(__file__).resolve().parent


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-responsive-contract-") as raw_tmp:
        root = Path(raw_tmp)
        board = root / "board"
        expected = board / "merged_expected.json"
        trace = board / "actual_layout_trace.json"
        test_file = root / "responsive_test.dart"
        _write(expected, {
            "artboardWidth": 750,
            "artboardHeight": 1624,
            "designPixelScale": 2,
            "logicalDesignWidth": 375,
            "nodes": {
                "left": {
                    "bbox": [20, 40, 60, 80], "logicalBbox": [10, 20, 30, 40],
                    "horizontalAnchor": {"mode": "left", "left": 10}, "impl": "shape",
                },
                "right": {
                    "bbox": [650, 40, 60, 80], "logicalBbox": [325, 20, 30, 40],
                    "horizontalAnchor": {"mode": "right", "right": 20}, "impl": "shape",
                },
            },
        })
        generated = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "gen_layout_trace_test.py"),
                "--expected", str(expected),
                "--page-import", "package:demo/page.dart",
                "--page-type", "DemoPage",
                "--trace-out", str(trace),
                "--out", str(test_file),
                "--viewports", "320x568,375x812,430x932",
            ],
            text=True, capture_output=True, check=False,
        )
        if generated.returncode != 0:
            raise AssertionError(generated.stderr or generated.stdout)
        contract_path = board / "responsive_layout_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if len(contract["viewports"]) != 3 or contract["policy"] != "logical_375_constraints":
            raise AssertionError(contract)
        if contract.get("runtimeScaleAllowed") is not False or contract.get("logicalDesignWidth") != 375:
            raise AssertionError(contract)
        dart = test_file.read_text(encoding="utf-8")
        if ("iff responsive layout contract" not in dart
                or "<double>[320.0, 568.0]" not in dart
                or "'worstNode': worstNode" not in dart
                or "const double dw = 375.0" not in dart
                or "width / dw" in dart
                or "rect.width / scale" in dart):
            raise AssertionError("generated Dart lacks responsive target tests")

        report_path = board / "responsive_layout_report.json"
        cases = [
            {
                "width": item["width"], "height": item["height"],
                "runtimeScale": 1,
                "missing": [], "layoutErrors": [],
                "maxLogicalBboxDelta": 0.25,
                "worstNode": "left", "worstAxis": "x",
                "worstExpected": 10, "worstObserved": 10.25,
                "pass": True,
            }
            for item in contract["viewports"]
        ]
        _write(report_path, {"schemaVersion": 1, "policy": contract["policy"],
                             "cases": cases, "pass": True})
        passed = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_responsive_layout.py"),
             "--contract", str(contract_path), "--report", str(report_path)],
            text=True, capture_output=True, check=False,
        )
        if passed.returncode != 0 or "375 logical constraint geometry" not in passed.stdout:
            raise AssertionError(passed.stdout or passed.stderr)
        legacy_contract = dict(contract)
        legacy_contract["policy"] = "fit_width_uniform_scroll"
        _write(contract_path, legacy_contract)
        rejected_legacy = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_responsive_layout.py"),
             "--contract", str(contract_path), "--report", str(report_path)],
            text=True, capture_output=True, check=False,
        )
        if rejected_legacy.returncode == 0 or "unsupported responsive policy" not in rejected_legacy.stdout:
            raise AssertionError(rejected_legacy.stdout or rejected_legacy.stderr)
        _write(contract_path, contract)
        cases[0]["maxLogicalBboxDelta"] = 3.0
        cases[0]["pass"] = False
        _write(report_path, {"schemaVersion": 1, "policy": contract["policy"],
                             "cases": cases, "pass": False})
        failed = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_responsive_layout.py"),
             "--contract", str(contract_path), "--report", str(report_path)],
            text=True, capture_output=True, check=False,
        )
        if failed.returncode == 0 or "logical bbox delta" not in failed.stdout:
            raise AssertionError(failed.stdout or failed.stderr)

    print("ok responsive layout contract selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
