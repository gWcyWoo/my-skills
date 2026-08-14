#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "platforms" / "android_trace_measure_v1.py"


def _write(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def test_measures_explicit_anchor_from_real_density_output() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-android-trace-measure-") as directory:
        root = Path(directory)
        hierarchy = _write(
            root / "window.xml",
            '<hierarchy rotation="0"><node resource-id="" '
            'content-desc="icp:action" bounds="[84,210][420,378]" /></hierarchy>',
        )
        contract = {
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
        contract_path = _write(root / "contract.json", json.dumps(contract))
        density = _write(
            root / "density.txt",
            "Physical density: 420\nOverride density: 336\n",
        )
        output = root / "anchor-measurements.json"

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--hierarchy",
                str(hierarchy),
                "--contract",
                str(contract_path),
                "--state-id",
                "state-default",
                "--density-output",
                str(density),
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
        assert report["kind"] == "icp.android-anchor-measurements.v1"
        assert report["density"]["effective_dpi"] == 336
        assert report["density"]["source"] == "override"
        measurement = report["measurements"][0]
        assert measurement["name"] == "action_top"
        assert measurement["actual_px"] == 210.0
        assert measurement["actual_dp"] == 100.0
        assert measurement["matched_node"]["content_desc"] == "icp:action"
        assert len(report["report_sha256"]) == 64
        assert report["status"] == "pass"


def test_missing_anchor_node_writes_failure_without_estimate() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-android-trace-missing-") as directory:
        root = Path(directory)
        hierarchy = _write(
            root / "window.xml",
            '<hierarchy rotation="0"><node content-desc="icp:other" '
            'bounds="[0,0][100,100]" /></hierarchy>',
        )
        contract = {
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
        contract_path = _write(root / "contract.json", json.dumps(contract))
        density = _write(root / "density.txt", "Physical density: 420\n")
        output = root / "anchor-measurements.json"

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--hierarchy",
                str(hierarchy),
                "--contract",
                str(contract_path),
                "--state-id",
                "state-default",
                "--density-output",
                str(density),
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
        assert report["errors"] == ["anchor node action is missing or ambiguous"]
        assert "actual" not in json.dumps(report)
        assert len(report["report_sha256"]) == 64


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
