#!/usr/bin/env python3
"""Regression: done gate honors the guard's explicit preexisting-GREEN adoption mode."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def run(checker: Path, root: Path, name: str) -> list[str]:
    report = root / f"{name}.json"
    result = subprocess.run(
        [sys.executable, str(checker), "--spec-root", str(root), "--out", str(report)],
        text=True,
        capture_output=True,
        check=False,
    )
    if not report.is_file():
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(report.read_text(encoding="utf-8"))["failures"]


def main() -> int:
    checker = Path(__file__).with_name("check_done_gate.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "home"
        root.mkdir()
        (root / "board").mkdir()
        evidence = root / "interaction_test_evidence.json"
        write_json(evidence, {"adoption": {"authorization": "preexisting-green"}})
        adopted = run(checker, root, "adopted")
        if any(failure.startswith("red evidence invalid") for failure in adopted):
            raise AssertionError(adopted)

        write_json(evidence, {"adoption": {"authorization": "not-authorized"}})
        invalid = run(checker, root, "invalid")
        red_failures = [failure for failure in invalid if failure.startswith("red evidence invalid")]
        if len(red_failures) != 2:
            raise AssertionError(invalid)

    print("ok done gate adoption selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
