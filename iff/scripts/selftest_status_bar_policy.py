#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(generator: Path, scene: Path, class_name: str, out: Path, expected: int) -> str:
    completed = subprocess.run(
        [
            sys.executable,
            str(generator),
            "--scene",
            str(scene),
            "--class-name",
            class_name,
            "--out",
            str(out),
        ],
        text=True,
        capture_output=True,
    )
    assert completed.returncode == expected, completed.stdout + completed.stderr
    return out.read_text(encoding="utf-8") if out.is_file() else ""


def main() -> int:
    generator = Path(__file__).with_name("make_status_bar_policy.py")
    with tempfile.TemporaryDirectory(prefix="iff-status-bar-policy-") as temp:
        root = Path(temp)
        with_status = root / "with_status.json"
        with_status.write_text(
            json.dumps({"systemUiExclusions": [{"node": "status", "role": "status_bar"}]}),
            encoding="utf-8",
        )
        overlay = run(generator, with_status, "WaitingStatusBarPolicy", root / "waiting.dart", 0)
        assert "static const String mode = 'overlay';" in overlay, overlay
        assert "static const bool designStatusBarDetected = true;" in overlay, overlay
        assert "static const bool reserveTopInset = false;" in overlay, overlay

        without_status = root / "without_status.json"
        without_status.write_text(json.dumps({"systemUiExclusions": []}), encoding="utf-8")
        hidden = run(generator, without_status, "ApplyStatusBarPolicy", root / "apply.dart", 0)
        assert "static const String mode = 'hidden';" in hidden, hidden
        assert "static const bool designStatusBarDetected = false;" in hidden, hidden
        assert "static const bool reserveTopInset = false;" in hidden, hidden

        run(generator, without_status, "invalid-name", root / "invalid.dart", 2)

    print("PASS: status-bar policy generation follows scene evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
