#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
SCRIPT = SCRIPT_ROOT / "platforms" / "android_region_diff_v1.py"
VENDORED = SCRIPT_ROOT.parent / "vendor" / "iff_v1" / "scripts" / "visual_diff.py"


def _visual_diff_module():
    specification = importlib.util.spec_from_file_location("icp_test_visual_diff", VENDORED)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.path.insert(0, str(VENDORED.parent))
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_region_ratio_comes_from_vendored_visual_diff_report() -> None:
    visual_diff = _visual_diff_module()
    with tempfile.TemporaryDirectory(prefix="icp-android-region-diff-") as directory:
        root = Path(directory)
        reference = root / "reference.png"
        actual = root / "actual.png"
        visual_diff.write_png_rgba(reference, 12, 12, [(255, 255, 255, 255)] * 144)
        pixels = [(255, 255, 255, 255)] * 144
        for y in range(2, 10):
            for x in range(2, 10):
                pixels[y * 12 + x] = (0, 0, 0, 255)
        visual_diff.write_png_rgba(actual, 12, 12, pixels)
        contract = {
            "design_contracts": [
                {
                    "states": [
                        {
                            "state_id": "state-default",
                            "regions": [
                                {
                                    "name": "asset_icon",
                                    "bbox": [2, 2, 8, 8],
                                    "max_mismatch_ratio": 0.05,
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        contract_path = root / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        output = root / "region-measurements.json"

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--reference",
                str(reference),
                "--actual",
                str(actual),
                "--contract",
                str(contract_path),
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
        assert report["kind"] == "icp.android-region-measurements.v1"
        measurement = report["measurements"][0]
        assert measurement["name"] == "asset_icon"
        assert measurement["mismatch_ratio"] == 1.0
        diff_path = Path(measurement["vendored_diff_report_path"])
        assert hashlib.sha256(diff_path.read_bytes()).hexdigest() == measurement[
            "vendored_diff_report_sha256"
        ]
        vendored_report = json.loads(diff_path.read_text(encoding="utf-8"))
        assert measurement["mismatch_ratio"] == vendored_report[
            "pixelMismatchRealDefect"
        ]
        assert len(report["report_sha256"]) == 64
        assert report["status"] == "pass"


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
