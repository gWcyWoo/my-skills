#!/usr/bin/env python3
"""Regression: asset gate uses AA-filtered real defects, with legacy fallback."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def run(script: Path, root: Path, diff: Path, name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3", str(script),
            "--trace", str(root / "trace.json"),
            "--expected", str(root / "expected.json"),
            "--diff-report", str(diff),
            "--out", str(root / f"{name}.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    script = Path(__file__).with_name("check_render_fidelity.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "expected.json", {"nodes": {"asset": {"bbox": [0, 0, 20, 20], "impl": "asset"}}})
        write_json(root / "trace.json", {
            "pageType": "RuntimePage", "expectedNodeIds": ["asset"],
            "nodes": {"asset": {"present": True, "bbox": [0, 0, 20, 20]}},
        })

        aa_only = root / "aa_only.json"
        write_json(aa_only, {"assetIssues": [{
            "node": "asset", "board": root.name, "bbox": [0, 0, 20, 20],
            "widget": "Image/SVG", "pixelMismatch": 0.30, "pixelMismatchRealDefect": 0.0,
        }]})
        accepted = run(script, root, aa_only, "accepted")
        if accepted.returncode != 0:
            raise AssertionError(accepted.stdout + accepted.stderr)

        real = root / "real.json"
        write_json(real, {"assetIssues": [{
            "node": "asset", "board": root.name, "bbox": [0, 0, 20, 20],
            "widget": "Image/SVG", "pixelMismatch": 0.30, "pixelMismatchRealDefect": 0.20,
        }]})
        rejected = run(script, root, real, "rejected")
        if rejected.returncode == 0:
            raise AssertionError("real asset defect must fail")

        legacy = root / "legacy.json"
        write_json(legacy, {"assetIssues": [{
            "node": "asset", "board": root.name, "bbox": [0, 0, 20, 20],
            "widget": "Image/SVG", "pixelMismatch": 0.20,
        }]})
        if run(script, root, legacy, "legacy").returncode == 0:
            raise AssertionError("legacy reports must retain raw mismatch fallback")

    print("ok render fidelity asset real-defect selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
