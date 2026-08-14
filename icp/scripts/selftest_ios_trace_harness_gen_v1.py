#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "platforms" / "ios_trace_harness_gen_v1.py"


def test_generates_xctest_that_publishes_identifier_label_and_frame() -> None:
    with tempfile.TemporaryDirectory(prefix="icp-ios-trace-harness-") as directory:
        output = Path(directory) / "ICPVisualTraceTests.swift"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--out", str(output)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        source = output.read_text(encoding="utf-8")
        assert "app.descendants(matching: .any)" in source
        assert ".allElementsBoundByIndex" in source
        assert 'environment["ICP_TRACE_OUTPUT"]' in source
        assert '"identifier": element.identifier' in source
        assert '"label": element.label' in source
        assert '"frame": [' in source
        assert '"kind": "icp.ios-native-view-trace.v1"' in source


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
