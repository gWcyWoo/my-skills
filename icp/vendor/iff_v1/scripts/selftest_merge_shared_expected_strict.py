#!/usr/bin/env python3
"""Regression: unresolved shared components must never disappear from fidelity input."""

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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-merge-shared-strict-") as raw_tmp:
        root = Path(raw_tmp)
        expected = root / "canvas.expected.json"
        local = root / "shared_components.local.json"
        scene = root / "scene.json"
        out = root / "merged_expected.json"
        _write(expected, {"nodes": {"base": {"bbox": [0, 0, 10, 10], "impl": "shape"}}})
        _write(scene, {"nodes": [{"id": "shared-root", "bbox": [10, 10, 20, 20]}]})
        _write(local, {"components": [{
            "status": "missing",
            "signature": "struct:unresolved",
            "group_node": "shared-root",
            "bbox": [10, 10, 20, 20],
        }]})
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "merge_shared_expected.py"),
                "--expected", str(expected),
                "--local", str(local),
                "--scene", str(scene),
                "--out", str(out),
            ],
            text=True, capture_output=True, check=False,
        )
        if completed.returncode == 0:
            raise AssertionError("unresolved shared component was silently omitted")
        message = completed.stderr or completed.stdout
        if "unresolved shared components cannot be omitted" not in message:
            raise AssertionError(message)
        if out.exists():
            raise AssertionError("failed merge wrote a misleading output artifact")

    print("ok strict unresolved shared-component merge selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
