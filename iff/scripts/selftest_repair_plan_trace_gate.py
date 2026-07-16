#!/usr/bin/env python3
"""Regression checks for fail-closed repair-plan trace readiness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def command(script: Path, root: Path, trace: Path, stem: str) -> list[str]:
    return [
        sys.executable,
        str(script),
        "--diff",
        str(root / "diff.json"),
        "--layout",
        str(root / "layout.json"),
        "--render-plan",
        str(root / "render.json"),
        "--actual-trace",
        str(trace),
        "--require-actual-trace",
        "--out",
        str(root / f"{stem}.json"),
        "--top-out",
        str(root / f"{stem}_top.json"),
    ]


def main() -> int:
    script = Path(__file__).resolve().parent / "make_repair_plan.py"
    with tempfile.TemporaryDirectory(prefix="iff-repair-trace-gate-") as raw_tmp:
        root = Path(raw_tmp)
        for name in ("diff.json", "layout.json", "render.json"):
            write_json(root / name, {})

        empty_trace = root / "empty_trace.json"
        write_json(empty_trace, {"pageType": "RuntimePage", "nodes": {}})
        rejected = subprocess.run(command(script, root, empty_trace, "rejected"), text=True, capture_output=True)
        assert rejected.returncode != 0, rejected.stdout
        assert "non-empty top-level nodes object" in rejected.stderr, rejected.stderr
        assert not (root / "rejected.json").exists()
        assert not (root / "rejected_top.json").exists()

        legacy_trace = root / "legacy_trace.json"
        write_json(legacy_trace, {"pageType": "RuntimePage", "widgets": [{"node": "node-1"}]})
        legacy = subprocess.run(command(script, root, legacy_trace, "legacy"), text=True, capture_output=True)
        assert legacy.returncode != 0, legacy.stdout

        valid_trace = root / "valid_trace.json"
        write_json(
            valid_trace,
            {"pageType": "RuntimePage", "nodes": {"node-1": {"bbox": [0, 0, 10, 10]}}},
        )
        accepted = subprocess.run(command(script, root, valid_trace, "accepted"), text=True, capture_output=True)
        if accepted.returncode != 0:
            raise AssertionError(accepted.stdout + accepted.stderr)
        top = json.loads((root / "accepted_top.json").read_text(encoding="utf-8"))
        assert top["summary"]["hasActualTrace"] is True, top
        assert not any("actual_layout_trace missing" in item for item in top["diagnosticWarnings"]), top
        full = json.loads((root / "accepted.json").read_text(encoding="utf-8"))
        assert full["provenance"]["board"] == root.name, full
        assert full["provenance"]["diffSha256"] == hashlib.sha256(
            (root / "diff.json").read_bytes()
        ).hexdigest(), full

    print("PASS: repair plan rejects empty trace before writing and accepts an indexed runtime trace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
