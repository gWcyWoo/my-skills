#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args()
    exporter = args.skill_dir.resolve() / "scripts" / "export_figma_scene.py"
    render_planner = args.skill_dir.resolve() / "scripts" / "make_render_plan.py"
    render_checker = args.skill_dir.resolve() / "scripts" / "check_render_plan.py"

    with tempfile.TemporaryDirectory(prefix="iff-system-ui-") as raw_tmp:
        tmp = Path(raw_tmp)
        status_svg = tmp / "misnamed_header.svg"
        status_png = tmp / "misnamed_header.png"
        status_svg.write_text(
            '<svg width="335" height="24" xmlns="http://www.w3.org/2000/svg">'
            '<g id="9:41"/><g id="Cellular Connection"/><g id="Wifi"/><g id="Battery"/>'
            "</svg>",
            encoding="utf-8",
        )
        status_png.write_bytes(b"\x89PNG\r\n\x1a\n")
        raw = tmp / "raw.json"
        assets = tmp / "assets.json"
        scene = tmp / "scene.json"
        render_assets = tmp / "render_assets.json"
        layout = tmp / "layout.json"
        shared = tmp / "shared.json"
        render_plan = tmp / "render_plan.json"
        write_json(
            raw,
            {
                "figma_json": {
                    "artboard": {
                        "id": "root",
                        "name": "Home",
                        "type": "FRAME",
                        "frame": {"left": -5064, "top": -21504, "width": 375, "height": 812},
                        "layers": [
                            {
                                "id": "status-asset",
                                "name": "Header Decoration",
                                "type": "VECTOR",
                                "frame": {"left": 20, "top": 12, "width": 335, "height": 24},
                            },
                            {
                                "id": "camera-dot",
                                "name": "Ellipse 22",
                                "type": "ELLIPSE",
                                "frame": {"left": 177, "top": 7, "width": 21, "height": 21},
                                "style": {
                                    "fills": [
                                        {"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}
                                    ]
                                },
                            },
                            {
                                "id": "offer-clock",
                                "name": "Offer clock",
                                "type": "TEXT",
                                "frame": {"left": 16, "top": 72, "width": 52, "height": 20},
                                "text": {"style": {"content": "09:41"}},
                            },
                            {
                                "id": "battery-health-header",
                                "name": "Battery Health",
                                "type": "FRAME",
                                "frame": {"left": 20, "top": 40, "width": 335, "height": 24},
                            },
                            {
                                "id": "app-logo-dot",
                                "name": "Brand mark",
                                "type": "ELLIPSE",
                                "frame": {"left": 177, "top": 84, "width": 21, "height": 21},
                                "style": {
                                    "fills": [
                                        {"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}
                                    ]
                                },
                            },
                        ],
                    }
                }
            },
        )
        write_json(
            assets,
            [
                {
                    "layer_id": "status-asset",
                    "png_path": str(status_png),
                    "svg_path": str(status_svg),
                }
            ],
        )

        completed = subprocess.run(
            [sys.executable, str(exporter), "--raw", str(raw), "--assets", str(assets), "--out", str(scene)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        nodes = {node["id"]: node for node in json.loads(scene.read_text(encoding="utf-8"))["nodes"]}

        assert nodes["status-asset"]["effectiveVisible"] is False, nodes["status-asset"]
        assert nodes["status-asset"]["systemUi"]["role"] == "status_bar"
        assert nodes["camera-dot"]["effectiveVisible"] is False
        assert nodes["camera-dot"]["systemUi"]["role"] == "camera_cutout"
        assert nodes["offer-clock"]["effectiveVisible"] is True
        assert "systemUi" not in nodes["offer-clock"]
        assert nodes["battery-health-header"]["effectiveVisible"] is True
        assert "systemUi" not in nodes["battery-health-header"]
        assert nodes["app-logo-dot"]["effectiveVisible"] is True
        assert "systemUi" not in nodes["app-logo-dot"]

        write_json(render_assets, {"status-asset": {"path": str(status_svg), "format": "svg"}})
        write_json(
            layout,
            {
                "component": {
                    "widgets": {node_id: {"node": node_id} for node_id in nodes}
                }
            },
        )
        write_json(
            shared,
            {
                "components": [
                    {
                        "status": "reuse",
                        "name": "FakeStatusBarComponent",
                        "group_node": "status-asset",
                        "bbox": [20, 12, 335, 24],
                    }
                ]
            },
        )
        planned = subprocess.run(
            [
                sys.executable,
                str(render_planner),
                "--scene",
                str(scene),
                "--assets",
                str(render_assets),
                "--layout",
                str(layout),
                "--shared",
                str(shared),
                "--out",
                str(render_plan),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert planned.returncode == 0, planned.stderr
        planned_payload = json.loads(render_plan.read_text(encoding="utf-8"))
        planned_nodes = planned_payload["nodes"]
        assert planned_payload["sharedComponents"] == []
        assert planned_nodes["status-asset"]["implementation"] == "hidden", planned_nodes["status-asset"]
        assert planned_nodes["status-asset"]["systemUi"]["role"] == "status_bar"
        assert planned_nodes["camera-dot"]["implementation"] == "hidden"
        assert planned_nodes["camera-dot"]["systemUi"]["role"] == "camera_cutout"

        invalid_plan = json.loads(render_plan.read_text(encoding="utf-8"))
        invalid_plan["nodes"]["status-asset"]["implementation"] = "svg"
        invalid_plan["nodes"]["status-asset"]["required"] = True
        invalid_path = tmp / "invalid_render_plan.json"
        write_json(invalid_path, invalid_plan)
        rejected = subprocess.run(
            [sys.executable, str(render_checker), str(invalid_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode != 0, "render-plan gate accepted system UI as a visible asset"
        assert "system UI must be hidden" in rejected.stdout + rejected.stderr

    print("OK: system chrome is excluded while nearby app content remains visible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
