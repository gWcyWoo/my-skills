#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT_ID = "component-root"
ASSET_ID = "component-icon"
ROOT_BBOX = [137, 211, 72, 72]
ASSET_BBOX = [145, 220, 24, 24]


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def run(script: Path, *args: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {script.name}\n{completed.stderr}"
        )


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff-shared-root-coordinates-") as raw_tmp:
        tmp = Path(raw_tmp)
        source = tmp / "source"
        source_assets = source / "assets"
        source_assets.mkdir(parents=True)
        (source_assets / "icon.png").write_bytes(b"synthetic png")

        scene = source / "scene.json"
        groups = source / "groups.json"
        source_manifest = source / "assets_manifest.json"
        classification = source / "design_classification.json"
        write_json(
            scene,
            {
                "sourceSchema": "lanhu_figma_json",
                "artboard": {"width": 1024, "height": 768},
                "nodes": [
                    {
                        "id": ROOT_ID,
                        "name": "Shared header",
                        "path": "Synthetic board/Shared header",
                        "parent": "source-page-root",
                        "type": "frame",
                        "figmaType": "FRAME",
                        "bbox": ROOT_BBOX,
                        "children": [ASSET_ID],
                        "effectiveVisible": True,
                        "fills": ["#FFFFFF"],
                        "solidFills": ["#FFFFFF"],
                        # Lanhu may expose bbox and absoluteTransform in different
                        # source coordinate spaces. Component normalization must
                        # still make the bbox authoritative for canvas placement.
                        "absoluteTransform": [[-1, 0, -7085], [0, 1, -21381]],
                    },
                    {
                        "id": ASSET_ID,
                        "name": "Battery",
                        "path": "Synthetic board/Shared header/Battery",
                        "parent": ROOT_ID,
                        "type": "image",
                        "figmaType": "RECTANGLE",
                        "bbox": ASSET_BBOX,
                        "children": [],
                        "effectiveVisible": True,
                        "asset": "assets/icon.png",
                    },
                ],
            },
        )
        write_json(
            groups,
            {
                "groups": [
                    {
                        "id": "shared-component",
                        "node": ROOT_ID,
                        "path": "Shared/Component",
                        "kind": "region",
                        "bbox": ROOT_BBOX,
                    }
                ]
            },
        )
        write_json(source_manifest, {ASSET_ID: "assets/icon.png"})
        write_json(
            classification,
            {
                "type": "component_sheet",
                "artboard": {"width": ROOT_BBOX[2], "height": 768},
                "states": [],
            },
        )

        layout = tmp / "layout_contract.json"
        raw_plan = tmp / "component_render_plan.raw.json"
        prepared_plan = tmp / "component_render_plan.json"
        copied_assets = tmp / "copied_assets"
        shared_assets = tmp / "shared_assets.json"
        component_manifest = tmp / "component_manifest.json"
        canvas = tmp / "shared_component.dart"
        job = tmp / "component.json"
        write_json(
            job,
            {
                "project_root": str(tmp),
                "source_spec_dir": str(source),
                "canonical_nodes": [ROOT_ID, ASSET_ID],
                "pooled_assets": {},
                "assets_incomplete": False,
            },
        )

        run(
            scripts / "make_figma_layout_contract.py",
            "--scene",
            str(scene),
            "--groups",
            str(groups),
            "--out",
            str(layout),
        )
        run(
            scripts / "make_render_plan.py",
            "--scene",
            str(scene),
            "--assets",
            str(source_manifest),
            "--layout",
            str(layout),
            "--root-node",
            ROOT_ID,
            "--out",
            str(raw_plan),
        )
        run(
            scripts / "prepare_shared_component_assets.py",
            "--job",
            str(job),
            "--render-plan",
            str(raw_plan),
            "--target",
            str(copied_assets),
            "--out",
            str(prepared_plan),
            "--manifest-out",
            str(shared_assets),
        )
        run(
            scripts / "make_component_manifest.py",
            "--render-plan",
            str(prepared_plan),
            "--classification",
            str(classification),
            "--out",
            str(component_manifest),
        )
        run(
            scripts / "generate_canvas.py",
            "--render-plan",
            str(prepared_plan),
            "--classification",
            str(classification),
            "--component-manifest",
            str(component_manifest),
            "--class-name",
            "SyntheticSharedComponent",
            "--artboard-width",
            str(ROOT_BBOX[2]),
            "--artboard-height",
            str(ROOT_BBOX[3]),
            "--asset-prefix",
            "assets/shared/",
            "--out",
            str(canvas),
        )

        plan_payload = json.loads(prepared_plan.read_text())
        expected_payload = json.loads(Path(f"{canvas}.expected.json").read_text())
        copied_asset = Path(plan_payload["nodes"][ASSET_ID]["asset"])
        canvas_nodes = expected_payload["nodes"]
        observed = {
            "rootNode": plan_payload.get("rootNode"),
            "canvasArtboard": [expected_payload["artboardWidth"], expected_payload["artboardHeight"]],
            "planBboxes": {
                ROOT_ID: plan_payload["nodes"][ROOT_ID]["bbox"],
                ASSET_ID: plan_payload["nodes"][ASSET_ID]["bbox"],
            },
            "canvasBboxes": {
                ROOT_ID: canvas_nodes.get(ROOT_ID, {}).get("bbox"),
                ASSET_ID: canvas_nodes.get(ASSET_ID, {}).get("bbox"),
            },
            "assetCopied": (tmp / copied_asset).is_file(),
        }
        expected = {
            "rootNode": ROOT_ID,
            "canvasArtboard": [72, 72],
            "planBboxes": {ROOT_ID: [0, 0, 72, 72], ASSET_ID: [8, 9, 24, 24]},
            "canvasBboxes": {ROOT_ID: [0, 0, 72, 72], ASSET_ID: [8, 9, 24, 24]},
            "assetCopied": True,
        }
        diagnostics = {
            "observed": observed,
            "implementations": {
                node_id: node["implementation"]
                for node_id, node in plan_payload["nodes"].items()
            },
            "rootMetadata": {
                key: plan_payload["nodes"][ROOT_ID].get(key)
                for key in ("parent", "absoluteTransform", "effectiveVisible")
            },
            "canvasNodeIds": list(canvas_nodes),
        }
        assert observed == expected, json.dumps(diagnostics, indent=2)

    print("PASS: shared-component public pipeline keeps rooted descendants on-canvas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
