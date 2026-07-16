#!/usr/bin/env python3
"""Regression tests for canonical merged expectations in runtime layout traces."""

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


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-layout-contract-") as raw_tmp:
        root = Path(raw_tmp)
        board = root / "board"
        raw_expected = root / "canvas.dart.expected.json"
        merged_expected = board / "merged_expected.json"
        trace_out = board / "actual_layout_trace.json"
        dart_out = root / "layout_trace_test.dart"

        _write(raw_expected, {
            "artboardWidth": 750,
            "artboardHeight": 1624,
            "nodes": {"base": {"bbox": [1, 2, 3, 4], "impl": "shape"}},
        })
        _write(merged_expected, {
            "artboardWidth": 750,
            "artboardHeight": 1624,
            "nodes": {
                "base": {"bbox": [9, 9, 9, 9], "impl": "shape"},
                "shared": {"bbox": [5, 6, 7, 8], "impl": "shared_component"},
            },
        })

        generated = _run(
            sys.executable, str(SCRIPTS / "gen_layout_trace_test.py"),
            "--expected", str(raw_expected),
            "--page-import", "package:demo/page.dart",
            "--page-type", "DemoPage",
            "--trace-out", str(trace_out),
            "--out", str(dart_out),
        )
        if generated.returncode != 0:
            raise AssertionError(generated.stderr or generated.stdout)
        dart = dart_out.read_text(encoding="utf-8")
        if "'base'" not in dart or "'shared'" not in dart:
            raise AssertionError("generator did not adopt merged shared-component nodes")
        if "'expectedNodeIds': ids" not in dart:
            raise AssertionError("generated trace does not bind its expected node ids")
        if "adopted canonical merged expectation" not in generated.stdout:
            raise AssertionError("raw-sidecar adaptation was not reported")

        _write(trace_out, {
            "pageType": "DemoPage",
            "expectedNodeIds": ["base"],
            "nodes": {"base": {"present": True, "bbox": [1, 2, 3, 4]}},
        })
        checked = _run(
            sys.executable, str(SCRIPTS / "check_render_fidelity.py"),
            "--trace", str(trace_out),
            "--expected", str(merged_expected),
        )
        if checked.returncode == 0:
            raise AssertionError("mismatched trace/expected node contracts were accepted")
        if "trace/expected node contract mismatch" not in checked.stderr:
            raise AssertionError(checked.stderr or checked.stdout)

    print("ok layout trace canonical expected contract selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
