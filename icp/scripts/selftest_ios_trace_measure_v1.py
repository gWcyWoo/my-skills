#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "platforms" / "ios_trace_measure_v1.py"


def test_measures_explicit_anchor_in_points() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-ios-trace-measure-") as directory:
        root = Path(directory)
        trace = root / "trace.json"
        trace.write_text(
            json.dumps(
                {
                    "kind": "icp.ios-native-view-trace.v1",
                    "schema_version": 1,
                    "elements": [
                        {
                            "identifier": "icp:action",
                            "label": "Continue",
                            "frame": {"x": 20.0, "y": 100.0, "width": 160.0, "height": 48.0},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        contract = root / "contract.json"
        contract.write_text(
            json.dumps(
                {
                    "design_contracts": [
                        {
                            "states": [
                                {
                                    "state_id": "state-default",
                                    "anchors": [
                                        {
                                            "name": "action_top",
                                            "node_id": "action",
                                            "attribute": "top",
                                            "expected": 100.0,
                                            "tolerance": 1.0,
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        output = root / "anchor-measurements.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--trace",
                str(trace),
                "--contract",
                str(contract),
                "--state-id",
                "state-default",
                "--out",
                str(output),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["kind"] == "icp.ios-anchor-measurements.v1"
        measurement = report["measurements"][0]
        assert measurement["name"] == "action_top"
        assert measurement["actual_pt"] == 100.0
        assert measurement["matched_element"]["identifier"] == "icp:action"
        assert report["status"] == "pass"
        assert len(report["report_sha256"]) == 64


def test_missing_identifier_writes_failure_without_estimate() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-ios-trace-missing-") as directory:
        root = Path(directory)
        trace = root / "trace.json"
        trace.write_text(
            json.dumps(
                {
                    "kind": "icp.ios-native-view-trace.v1",
                    "schema_version": 1,
                    "elements": [],
                }
            ),
            encoding="utf-8",
        )
        contract = root / "contract.json"
        contract.write_text(
            json.dumps(
                {
                    "design_contracts": [
                        {
                            "states": [
                                {
                                    "state_id": "state-default",
                                    "anchors": [
                                        {
                                            "name": "action_top",
                                            "node_id": "action",
                                            "attribute": "top",
                                            "expected": 100.0,
                                            "tolerance": 1.0,
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        output = root / "anchor-measurements.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--trace",
                str(trace),
                "--contract",
                str(contract),
                "--state-id",
                "state-default",
                "--out",
                str(output),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        assert result.returncode == 2
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["status"] == "failed"
        assert report["measurements"] == []
        assert report["errors"] == ["anchor element action is missing or ambiguous"]
        assert "actual" not in json.dumps(report)


def main() -> int:
    tests = sorted(name for name in globals() if name.startswith("test_"))
    failures = 0
    for name in tests:
        try:
            globals()[name]()
            print(f"ok {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"not ok {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    if failures:
        print(f"failed {failures}/{len(tests)} selftest cases")
        return 1
    print(f"ok {len(tests)} selftest cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
