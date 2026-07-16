#!/usr/bin/env python3
"""Regression: done gate uses board-scoped AA-filtered real-defect metrics."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def main() -> int:
    checker = Path(__file__).with_name("check_done_gate.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "home"
        board = root / "board"
        board.mkdir(parents=True)
        write_json(root / "diff_report.json", {
            "assetIssues": [{"node": "stale-root", "pixelMismatch": 1.0}],
            "textIssues": [{"node": "stale-root-text", "pixelMismatch": 1.0}],
        })
        write_json(board / "diff_report.json", {
            "assetIssues": [
                {"node": "aa-only-asset", "pixelMismatch": 0.8, "pixelMismatchRealDefect": 0.0},
                {"node": "real-asset", "pixelMismatch": 0.8, "pixelMismatchRealDefect": 0.2},
            ],
            "textIssues": [
                {"node": "aa-only-text", "pixelMismatch": 0.8, "pixelMismatchRealDefect": 0.0},
                {"node": "real-text", "pixelMismatch": 0.8, "pixelMismatchRealDefect": 0.4},
            ],
        })
        report = root / "done_gate_report.json"
        result = subprocess.run(
            [sys.executable, str(checker), "--spec-root", str(root), "--out", str(report)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 1:
            raise AssertionError(result.stdout + result.stderr)
        if not report.is_file():
            raise AssertionError(result.stdout + result.stderr)
        failures = json.loads(report.read_text(encoding="utf-8"))["failures"]
        rendered = "\n".join(failures)
        if "stale-root" in rendered or "aa-only" in rendered:
            raise AssertionError(failures)
        if "asset region real defect: real-asset mismatch=0.200 > 0.1" not in failures:
            raise AssertionError(failures)
        if "text region real defect (clipped/wrong glyphs): real-text mismatch=0.400 > 0.3" not in failures:
            raise AssertionError(failures)

    print("ok done gate real-defect scope selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
