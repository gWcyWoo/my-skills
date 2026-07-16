#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    scripts = Path(__file__).resolve().parent
    checker = scripts / "check_done_gate.py"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "home"
        (root / "board").mkdir(parents=True)
        asset_issue = {"node": "asset-node", "pixelMismatch": 0.75}
        text_issue = {"node": "text-node", "pixelMismatch": 0.80}
        (root / "diff_report.json").write_text(
            json.dumps(
                {
                    "assetIssues": [asset_issue, asset_issue],
                    "textIssues": [text_issue, text_issue],
                }
            ),
            encoding="utf-8",
        )
        report_path = root / "done_gate_report.json"
        result = subprocess.run(
            [
                sys.executable,
                str(checker),
                "--spec-root",
                str(root),
                "--out",
                str(report_path),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1, result.stdout + result.stderr
        failures = json.loads(report_path.read_text(encoding="utf-8"))["failures"]
        asset_failure = "asset region real defect: asset-node mismatch=0.750 > 0.1"
        text_failure = (
            "text region real defect (clipped/wrong glyphs): "
            "text-node mismatch=0.800 > 0.3"
        )
        assert failures.count(asset_failure) == 1, failures
        assert failures.count(text_failure) == 1, failures
        assert failures.count("capture_readiness.json missing") == 1, failures
        assert result.stdout.count(asset_failure) == 1, result.stdout
        assert result.stdout.count(text_failure) == 1, result.stdout

    print("PASS: done gate reports each distinct failure once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
