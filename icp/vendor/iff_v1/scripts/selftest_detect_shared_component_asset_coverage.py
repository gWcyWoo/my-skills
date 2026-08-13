#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args()
    detector = args.skill_dir.resolve() / "scripts" / "detect_shared_components.py"

    with tempfile.TemporaryDirectory(prefix="iff-shared-asset-coverage-") as raw_tmp:
        tmp = Path(raw_tmp)
        spec_dirs = [tmp / "first", tmp / "second"]
        nodes = [
            {"id": "artboard", "type": "artboard", "bbox": [0, 0, 390, 844],
             "children": ["enclosing-region", "normal-group", "unpainted-group"]},
            {"id": "enclosing-region", "type": "frame", "bbox": [0, 0, 200, 200],
             "parent": "artboard", "children": ["atomic-asset"],
             "componentId": "enclosing-region"},
            {"id": "atomic-asset", "type": "image", "bbox": [10, 10, 180, 180],
             "parent": "enclosing-region", "children": ["nested-covered"],
             "componentId": "atomic-asset", "asset": "assets/atomic.png", "exportable": True},
            {"id": "nested-covered", "type": "frame", "bbox": [20, 20, 160, 160],
             "parent": "atomic-asset", "children": ["nested-visible"],
             "componentId": "nested-covered"},
            {"id": "nested-visible", "type": "shapeLayer", "bbox": [30, 30, 100, 20],
             "parent": "nested-covered", "children": [], "fills": [], "border": []},
            {"id": "normal-group", "type": "frame", "bbox": [0, 220, 200, 100],
             "parent": "artboard", "children": ["normal-visible"],
             "componentId": "normal-group"},
            {"id": "normal-visible", "type": "text", "bbox": [10, 230, 100, 20],
             "parent": "normal-group", "children": [], "text": "visible"},
            {"id": "unpainted-group", "type": "groupLayer", "bbox": [220, 0, 74, 74],
             "parent": "artboard", "children": ["unpainted-leaf"],
             "componentId": "unpainted-shared"},
            {"id": "unpainted-leaf", "type": "shapeLayer", "figmaType": "shapeLayer",
             "bbox": [220, 0, 74, 74], "parent": "unpainted-group", "children": [],
             "visible": True, "fills": [], "border": [], "shadow": []},
        ]
        groups = [
            {"id": "enclosing", "node": "enclosing-region", "kind": "region", "bbox": [0, 0, 200, 200]},
            {"id": "atomic", "node": "atomic-asset", "kind": "region", "bbox": [10, 10, 180, 180]},
            {"id": "nested", "node": "nested-covered", "kind": "region", "bbox": [20, 20, 160, 160]},
            {"id": "normal", "node": "normal-group", "kind": "region", "bbox": [0, 220, 200, 100]},
            {"id": "unpainted", "node": "unpainted-group", "kind": "header", "bbox": [220, 0, 74, 74]},
        ]
        for spec_dir in spec_dirs:
            write_json(spec_dir / "scene.json", {"nodes": nodes})
            write_json(spec_dir / "groups.json", {"groups": groups})
            write_json(spec_dir / "assets_manifest.json", {"atomic-asset": {"path": "assets/atomic.png"}})

        registry = tmp / "registry.json"
        output = tmp / "batch.json"
        write_json(registry, {"components": {
            "componentId:unpainted-shared": {
                "name": "StaleTransparentWidget",
                "canonical_nodes": ["unpainted-group", "unpainted-leaf"],
            }
        }})
        completed = subprocess.run(
            [
                sys.executable,
                str(detector),
                "--spec-dirs",
                *(str(path) for path in spec_dirs),
                "--registry",
                str(registry),
                "--out",
                str(output),
                "--no-local",
            ],
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)

        components = json.loads(output.read_text(encoding="utf-8"))["components"]
        signatures = {component["signature"] for component in components}
        assert "componentId:nested-covered" not in signatures, signatures
        assert {
            "componentId:atomic-asset",
            "componentId:enclosing-region",
            "componentId:normal-group",
            "componentId:unpainted-shared",
        } <= signatures, signatures
        unpainted = next(
            component for component in components
            if component["signature"] == "componentId:unpainted-shared"
        )
        assert unpainted["assets_incomplete"] is True, unpainted
        assert unpainted["paint_missing_positions"] == [1], unpainted
        assert unpainted["status"] == "missing", unpainted
        assert unpainted["widget"] is None, unpainted
        atomic = next(
            component for component in components
            if component["signature"] == "componentId:atomic-asset"
        )
        assert atomic["paint_missing_positions"] == [], atomic

        covered_output = tmp / "covered-batch.json"
        covered_entry = {
            "name": "LocalizedFallbackWidget",
            "source_spec_dir": str(spec_dirs[0]),
            "canonical_nodes": ["unpainted-group", "unpainted-leaf"],
            "expected_nodes": {
                "unpainted-leaf": {"impl": "image_png", "bbox": [0, 0, 74, 74]},
            },
        }
        write_json(registry, {"components": {
            "componentId:unpainted-shared": covered_entry,
        }})
        covered_run = subprocess.run(
            [
                sys.executable, str(detector),
                "--spec-dirs", *(str(path) for path in spec_dirs),
                "--registry", str(registry),
                "--out", str(covered_output),
            ],
            text=True, capture_output=True, check=False,
        )
        assert covered_run.returncode == 0, covered_run.stderr or covered_run.stdout
        covered_doc = json.loads(covered_output.read_text(encoding="utf-8"))
        covered = next(
            component for component in covered_doc["components"]
            if component["signature"] == "componentId:unpainted-shared"
        )
        assert covered["status"] == "reuse", covered
        assert covered["paint_missing_positions"] == [], covered
        assert covered["assets_incomplete"] is False, covered

        legacy_output = tmp / "legacy-batch.json"
        write_json(registry, {"components": {"legacy-signature": covered_entry}})
        legacy_run = subprocess.run(
            [
                sys.executable, str(detector),
                "--spec-dirs", *(str(path) for path in spec_dirs),
                "--registry", str(registry),
                "--out", str(legacy_output),
            ],
            text=True, capture_output=True, check=False,
        )
        assert legacy_run.returncode == 0, legacy_run.stderr or legacy_run.stdout
        legacy_doc = json.loads(legacy_output.read_text(encoding="utf-8"))
        rebound = next(
            component for component in legacy_doc["components"]
            if component["signature"] == "componentId:unpainted-shared"
        )
        assert rebound["status"] == "reuse", rebound
        assert rebound["paint_missing_positions"] == [], rebound
        assert rebound["assets_incomplete"] is False, rebound
        assert "rebound verified shared component" in legacy_run.stdout, legacy_run.stdout

    print("ok detect shared component atomic asset coverage selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
