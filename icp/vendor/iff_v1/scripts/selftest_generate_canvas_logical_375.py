#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from generate_canvas import emitted_uses_svg


SCRIPTS = Path(__file__).resolve().parent


def _node(node_id: str, bbox: list[float], parent: str = "root") -> dict:
    return {
        "name": node_id,
        "bbox": bbox,
        "implementation": "shape_container",
        "parent": parent,
        "children": [],
        "fills": ["#3366FF"],
        "rawFills": [],
        "border": [],
        "radius": 0,
        "shadow": [],
        "opacity": 1,
        "visible": True,
        "required": True,
    }


def main() -> int:
    if emitted_uses_svg([], {"hidden": []}) or not emitted_uses_svg(
            ["SvgPicture.asset('icon.svg')"], {"hidden": []}):
        raise AssertionError("SVG imports must follow emitted widgets, not source-only assets")
    with tempfile.TemporaryDirectory(prefix="iff-logical-375-") as raw_tmp:
        root = Path(raw_tmp)
        render_plan = root / "render_plan.json"
        classification = root / "design_classification.json"
        out = root / "canvas.dart"
        nodes = {
            "root": _node("root", [0, 0, 750, 1624], parent=None),
            "left": _node("left", [20, 40, 60, 80]),
            "right": _node("right", [650, 40, 60, 80]),
            "center": _node("center", [330, 200, 90, 40]),
            "stretch": _node("stretch", [24, 300, 702, 100]),
            "icon": _node("icon", [100, 500, 48, 48]),
            "photo": _node("photo", [100, 600, 200, 100]),
        }
        nodes["icon"]["implementation"] = "asset"
        nodes["icon"]["asset"] = "assets/icon.svg"
        nodes["photo"]["implementation"] = "asset"
        nodes["photo"]["asset"] = "assets/photo.png"
        nodes["root"]["children"] = ["left", "right", "center", "stretch", "icon", "photo"]
        render_plan.write_text(json.dumps({"rootNode": None, "nodes": nodes}), encoding="utf-8")
        classification.write_text(json.dumps({
            "artboard": {"width": 750, "height": 1624, "scale": 2},
            "viewport": {"width": 375, "height": 812},
        }), encoding="utf-8")
        generated = subprocess.run([
            sys.executable, str(SCRIPTS / "generate_canvas.py"),
            "--render-plan", str(render_plan), "--classification", str(classification),
            "--out", str(out), "--class-name", "Logical375Canvas",
        ], text=True, capture_output=True, check=False)
        if generated.returncode != 0:
            raise AssertionError(generated.stderr or generated.stdout)
        dart = out.read_text(encoding="utf-8")
        forbidden = ("constraints.maxWidth / designWidth", "width / logicalDesignWidth", "Transform.scale(")
        if any(token in dart for token in forbidden):
            raise AssertionError("generated canvas performs forbidden runtime viewport scaling")
        required = (
            "const double u = 1 / designPixelScale",
            "right: 40.00 * u, width: 60.00 * u",
            "left: (viewportWidth - 90.00 * u) / 2 + 0.00 * u",
            "left: 24.00 * u, right: 24.00 * u",
            "required this.viewportWidth",
            "final double viewportWidth = constraints.maxWidth",
            "viewportWidth: viewportWidth",
            "import 'package:flutter_svg/flutter_svg.dart'",
            "SvgPicture.asset('assets/images/icon.svg', fit: BoxFit.fill)",
            "cacheWidth: (200.00 * u * MediaQuery.devicePixelRatioOf(context)).ceil()",
            "cacheHeight: (100.00 * u * MediaQuery.devicePixelRatioOf(context)).ceil()",
        )
        missing = [token for token in required if token not in dart]
        if missing:
            rendered_assets = [line.strip() for line in dart.splitlines() if "Picture.asset" in line]
            raise AssertionError(
                f"generated canvas lacks logical-unit anchor constraints: {missing}; assets={rendered_assets}"
            )
        expected = json.loads(Path(str(out) + ".expected.json").read_text(encoding="utf-8"))
        if expected.get("designPixelScale") != 2 or expected.get("logicalDesignWidth") != 375:
            raise AssertionError(expected)
        if expected["nodes"]["right"]["logicalBbox"] != [325, 20, 30, 40]:
            raise AssertionError(expected["nodes"]["right"])
        modes = {node_id: expected["nodes"][node_id]["horizontalAnchor"]["mode"]
                 for node_id in ("left", "right", "center", "stretch")}
        if modes != {"left": "left", "right": "right", "center": "center", "stretch": "stretch"}:
            raise AssertionError(modes)
    print("ok generate_canvas logical 375 selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
