#!/usr/bin/env python3
"""Regression test for model-confirmed non-app design artifact exclusion."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("system_ui_filter.py")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def fixture() -> dict[str, object]:
    return {
        "artboard": {"bbox": [0, 0, 375, 812]},
        "nodes": [
            {
                "id": "root",
                "name": "Home",
                "bbox": [0, 0, 375, 812],
                "children": ["confirmed-black-spot", "business-sparkle"],
                "depth": 0,
                "visible": True,
                "effectiveVisible": True,
            },
            {
                "id": "confirmed-black-spot",
                "name": "Star 4",
                "bbox": [261.44, 144.44, 17.15, 17.15],
                "parent": "root",
                "children": [],
                "depth": 1,
                "visible": True,
                "effectiveVisible": True,
                "solidFills": [{"color": "#000000", "opacity": 1}],
            },
            {
                "id": "business-sparkle",
                "name": "Reward sparkle",
                "bbox": [40, 400, 16, 16],
                "parent": "root",
                "children": [],
                "depth": 1,
                "visible": True,
                "effectiveVisible": True,
                "solidFills": [{"color": "#000000", "opacity": 1}],
            },
        ],
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        scene = root / "scene.json"
        untouched = root / "untouched.json"
        filtered = root / "filtered.json"
        scene.write_text(json.dumps(fixture()), encoding="utf-8")

        baseline = run("--scene", str(scene), "--out", str(untouched))
        assert baseline.returncode == 0, baseline.stderr
        baseline_nodes = {
            node["id"]: node for node in json.loads(untouched.read_text(encoding="utf-8"))["nodes"]
        }
        assert baseline_nodes["confirmed-black-spot"]["effectiveVisible"] is True
        assert baseline_nodes["business-sparkle"]["effectiveVisible"] is True

        result = run(
            "--scene",
            str(scene),
            "--out",
            str(filtered),
            "--exclude-node",
            "confirmed-black-spot",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(filtered.read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in payload["nodes"]}
        excluded = {item["node"]: item for item in payload["systemUiExclusions"]}
        assert nodes["confirmed-black-spot"]["effectiveVisible"] is False
        assert nodes["confirmed-black-spot"]["systemUi"]["role"] == "confirmed_device_artifact"
        assert excluded["confirmed-black-spot"]["role"] == "confirmed_device_artifact"
        assert nodes["business-sparkle"]["effectiveVisible"] is True

        unknown = run(
            "--scene",
            str(scene),
            "--out",
            str(filtered),
            "--exclude-node",
            "missing-node",
        )
        assert unknown.returncode != 0
        assert "unknown explicit exclusion node" in unknown.stderr

    print("ok confirmed design exclusion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
