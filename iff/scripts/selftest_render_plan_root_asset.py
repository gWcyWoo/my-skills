#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_render_plan(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args()
    script = args.skill_dir.resolve() / "scripts" / "make_render_plan.py"

    with tempfile.TemporaryDirectory(prefix="iff-render-plan-root-asset-") as raw_tmp:
        tmp = Path(raw_tmp)
        assets = tmp / "assets_manifest.json"
        write_json(assets, {
            "265:198": {"path": "assets/component.svg", "format": "svg"},
        })

        component_scene = tmp / "component_scene.json"
        component_layout = tmp / "component_layout.json"
        component_plan = tmp / "component_render_plan.json"
        write_json(
            component_scene,
            {
                "sourceSchema": "selftest",
                "nodes": [
                    {
                        "id": "265:198",
                        "type": "image",
                        "bbox": [320, 480, 80, 40],
                        "children": [],
                        "asset": "assets/component.png",
                    }
                ],
            },
        )
        write_json(
            component_layout,
            {"component": {"widgets": {"root": {"node": "265:198"}}}},
        )
        component_result = run_render_plan(
            script,
            "--scene",
            str(component_scene),
            "--assets",
            str(assets),
            "--layout",
            str(component_layout),
            "--root-node",
            "265:198",
            "--out",
            str(component_plan),
        )
        assert component_result.returncode == 0, component_result.stderr
        component_payload = json.loads(component_plan.read_text(encoding="utf-8"))
        assert component_payload["componentRoot"]["bbox"] == [0, 0, 80, 40]
        assert component_payload["nodes"]["265:198"]["bbox"] == [0, 0, 80, 40]
        assert component_payload["nodes"]["265:198"]["implementation"] == "svg"
        assert component_payload["nodes"]["265:198"]["asset"] == "assets/component.svg"

        page_scene = tmp / "page_scene.json"
        page_layout = tmp / "page_layout.json"
        page_plan = tmp / "page_render_plan.json"
        write_json(
            page_scene,
            {
                "sourceSchema": "selftest",
                "nodes": [
                    {
                        "id": "page-artboard",
                        "type": "artboard",
                        "bbox": [0, 0, 390, 844],
                        "children": ["page-asset"],
                    },
                    {
                        "id": "page-asset",
                        "type": "image",
                        "bbox": [0, 0, 390, 844],
                        "parent": "page-artboard",
                        "children": [],
                        "asset": "assets/reference.png",
                    },
                ],
            },
        )
        write_json(
            page_layout,
            {"page": {"widgets": {"background": {"node": "page-asset"}}}},
        )
        page_result = run_render_plan(
            script,
            "--scene",
            str(page_scene),
            "--assets",
            str(assets),
            "--layout",
            str(page_layout),
            "--out",
            str(page_plan),
        )
        assert page_result.returncode != 0, "page-level full-artboard asset unexpectedly succeeded"
        assert "full-artboard asset is forbidden: page-asset" in (
            page_result.stdout + page_result.stderr
        )

    print("ok render plan component-root atomic asset guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
