#!/usr/bin/env python3
"""Regression: visual diff masks only proven API text content regions."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path


def load_visual_diff(path: Path):
    spec = importlib.util.spec_from_file_location("iff_visual_diff", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def run(script: Path, root: Path, bindings: Path | None, name: str) -> subprocess.CompletedProcess[str]:
    command = [
        "python3", str(script),
        "--reference", str(root / "reference.png"),
        "--actual", str(root / "actual.png"),
        "--layout", str(root / "layout.json"),
        "--out", str(root / f"{name}.json"),
        "--heatmap", str(root / f"{name}.png"),
    ]
    if bindings is not None:
        command.extend(["--data-slot-bindings", str(bindings)])
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> int:
    script = Path(__file__).with_name("visual_diff.py")
    visual_diff = load_visual_diff(script)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        width = height = 10
        reference = [(255, 255, 255, 255)] * (width * height)
        actual = list(reference)
        for y in range(2, 6):
            for x in range(2, 6):
                actual[y * width + x] = (0, 0, 0, 255)
        visual_diff.write_png_rgba(root / "reference.png", width, height, reference)
        visual_diff.write_png_rgba(root / "actual.png", width, height, actual)
        write_json(root / "layout.json", {"plan": {
            "bbox": [0, 0, 10, 10],
            "widgets": {"title": {"node": "plan-title", "bbox": [2, 2, 4, 4], "widget": "Text"}},
        }})

        if run(script, root, None, "baseline").returncode == 0:
            raise AssertionError("unproven content mismatch must fail visual diff")

        bindings = root / "bindings.json"
        write_json(bindings, {"bindings": [{
            "node": "plan-title",
            "binding": {"field": "plan.title"},
            "contentSource": {"kind": "api", "evidence": "GET /plans response.plan.title"},
            "confirmedByModel": True,
        }]})
        accepted = run(script, root, bindings, "accepted")
        if accepted.returncode != 0:
            raise AssertionError(accepted.stdout + accepted.stderr)
        report = json.loads((root / "accepted.json").read_text(encoding="utf-8"))
        if report.get("dynamicContentExclusions") != ["plan-title"]:
            raise AssertionError(report)
        if report.get("pixelMismatch") != 0.0:
            raise AssertionError(report)

    print("ok visual diff API dynamic-content contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
