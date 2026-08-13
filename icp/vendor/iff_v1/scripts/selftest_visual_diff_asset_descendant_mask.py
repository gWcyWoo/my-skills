#!/usr/bin/env python3
"""Regression: asset shape metrics exclude independently rendered descendants."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from visual_diff import write_png_rgba


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def run(script: Path, root: Path, actual: Path, name: str) -> dict:
    report = root / f"{name}.json"
    subprocess.run(
        [
            "python3", str(script),
            "--reference", str(root / "reference.png"),
            "--actual", str(actual),
            "--layout", str(root / "layout.json"),
            "--out", str(report),
            "--heatmap", str(root / f"{name}.png"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return json.loads(report.read_text(encoding="utf-8"))


def main() -> int:
    script = Path(__file__).with_name("visual_diff.py")
    width = height = 20
    reference = [(255, 255, 255, 255)] * (width * height)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_png_rgba(root / "reference.png", width, height, reference)
        write_json(root / "layout.json", {"card": {
            "bbox": [0, 0, 20, 20],
            "widgets": {
                "background": {"node": "card-bg", "bbox": [0, 0, 20, 20], "widget": "Image/SVG"},
                "title": {"node": "card-title", "bbox": [5, 5, 10, 5], "widget": "Text"},
            },
        }})

        text_only = list(reference)
        for y in range(5, 10):
            for x in range(5, 15):
                text_only[y * width + x] = (0, 0, 0, 255)
        write_png_rgba(root / "text_only.png", width, height, text_only)
        masked = run(script, root, root / "text_only.png", "masked")
        if any(issue.get("node") == "card-bg" for issue in masked.get("assetIssues", [])):
            raise AssertionError(masked.get("assetIssues"))

        asset_defect = list(text_only)
        for y in range(0, 5):
            for x in range(0, 5):
                asset_defect[y * width + x] = (0, 0, 0, 255)
        write_png_rgba(root / "asset_defect.png", width, height, asset_defect)
        detected = run(script, root, root / "asset_defect.png", "detected")
        asset_issue = next(
            (issue for issue in detected.get("assetIssues", []) if issue.get("node") == "card-bg"),
            None,
        )
        if not asset_issue or asset_issue.get("pixelMismatchRealDefect", 0) <= 0.01:
            raise AssertionError(detected.get("assetIssues"))
        if asset_issue.get("excludedDescendantRegions") != 1:
            raise AssertionError(asset_issue)

    print("ok visual diff asset descendant mask selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
