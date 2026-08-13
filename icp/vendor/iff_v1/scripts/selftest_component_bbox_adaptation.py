#!/usr/bin/env python3
"""Regression for malformed header bbox adaptation and merged fidelity geometry."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from detect_shared_components import normalize_component_bbox  # noqa: E402


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    normalized, evidence = normalize_component_bbox([700, 123, 72, 72], 750, "header")
    if normalized != [628.0, 123.0, 72.0, 72.0]:
        raise AssertionError((normalized, evidence))
    if not evidence or evidence.get("reason") != "right_edge_encoded_as_x":
        raise AssertionError(evidence)
    unchanged, unchanged_evidence = normalize_component_bbox([700, 123, 72, 72], 750, "region")
    if unchanged != [700, 123, 72, 72] or unchanged_evidence is not None:
        raise AssertionError((unchanged, unchanged_evidence))

    with tempfile.TemporaryDirectory(prefix="iff-bbox-adaptation-") as raw_tmp:
        root = Path(raw_tmp)
        spec = root / "spec"
        registry = root / "registry.json"
        batch = root / "batch.json"
        _write(spec / "scene.json", {
            "artboard": {"width": 750, "height": 1704},
            "nodes": [
                {"id": "artboard", "type": "artboard", "bbox": [0, 0, 750, 1704],
                 "children": ["page-header"]},
                {"id": "page-header", "type": "image", "bbox": [700, 123, 72, 72],
                 "parent": "artboard", "children": [], "componentId": "chat",
                 "asset": "assets/chat.png", "exportable": True},
            ],
        })
        _write(spec / "groups.json", {"groups": [{
            "id": "header", "node": "page-header", "kind": "header",
            "bbox": [700, 123, 72, 72],
        }]})
        _write(spec / "assets_manifest.json", {"page-header": {"path": "assets/chat.png"}})
        _write(registry, {"components": {"componentId:chat": {
            "name": "Header", "widget_path": "lib/header.dart",
            "source_spec_dir": str(spec), "canonical_nodes": ["page-header"],
            "expected_nodes": {"page-header": {"bbox": [0, 0, 72, 72], "impl": "image_png"}},
        }}})
        detected = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "detect_shared_components.py"),
                "--spec-dirs", str(spec), "--registry", str(registry),
                "--out", str(batch),
            ],
            text=True, capture_output=True, check=False,
        )
        if detected.returncode != 0:
            raise AssertionError(detected.stderr or detected.stdout)
        local = json.loads((spec / "shared_components.local.json").read_text(encoding="utf-8"))
        component = local["components"][0]
        if component["bbox"] != normalized:
            raise AssertionError(component)
        if (component.get("bbox_adaptation") or {}).get("reason") != "right_edge_encoded_as_x":
            raise AssertionError(component)

        expected = root / "canvas.expected.json"
        local = root / "shared_components.local.json"
        scene = root / "scene.json"
        out = root / "merged_expected.json"
        _write(expected, {"nodes": {}})
        _write(scene, {"nodes": [{"id": "page-header", "bbox": [700, 123, 72, 72]}]})
        _write(local, {"components": [{
            "status": "reuse", "name": "Header", "group_node": "page-header",
            "bbox": normalized, "node_map": {"page-header": "source-header"},
            "expected_nodes": {"source-header": {"bbox": [0, 0, 72, 72]}},
        }]})
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "merge_shared_expected.py"),
                "--expected", str(expected), "--local", str(local),
                "--scene", str(scene), "--out", str(out),
            ],
            text=True, capture_output=True, check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        merged = json.loads(out.read_text(encoding="utf-8"))
        if merged["nodes"]["source-header"]["bbox"] != normalized:
            raise AssertionError(merged)

    print("ok component bbox adaptation selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
