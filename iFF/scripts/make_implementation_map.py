#!/usr/bin/env python3
"""Generate implementation-map coverage from render and canvas metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from check_implementation_map import VISIBLE_IMPLEMENTATIONS


def build_implementation_map(
    render_plan: dict[str, Any], canvas_expected: dict[str, Any]
) -> dict[str, Any]:
    render_nodes = render_plan.get("nodes") or {}
    expected_nodes = canvas_expected.get("nodes") or {}
    mappings: list[dict[str, Any]] = []
    for node_id, node in sorted(render_nodes.items()):
        implementation = node.get("implementation")
        if node.get("required") is not True and implementation not in VISIBLE_IMPLEMENTATIONS:
            continue
        bbox = node.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"visible node has invalid bbox: {node_id}")
        expected = expected_nodes.get(node_id) or {}
        widget = expected.get("widget") or expected.get("widgetType")
        if not widget:
            raise ValueError(f"canvas metadata has no widget for visible node: {node_id}")
        mappings.append(
            {
                "node": node_id,
                "implementation": implementation,
                "widget": widget,
                "bbox": bbox,
                "renderMode": "absolute_positioned",
            }
        )
    return {"version": 1, "nodes": mappings}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-plan", required=True)
    parser.add_argument("--canvas-expected", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    render_plan = json.loads(Path(args.render_plan).read_text(encoding="utf-8"))
    canvas_expected = json.loads(
        Path(args.canvas_expected).read_text(encoding="utf-8")
    )
    try:
        result = build_implementation_map(render_plan, canvas_expected)
    except ValueError as error:
        raise SystemExit(f"ERROR: {error}") from error
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok implementation map: {len(result['nodes'])} node(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
