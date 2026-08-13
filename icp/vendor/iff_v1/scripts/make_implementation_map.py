#!/usr/bin/env python3
"""Build a board implementation map from the authoritative render plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from check_implementation_map import VISIBLE_IMPLEMENTATIONS


def fail(message: str) -> int:
    print(f"ERROR {message}", file=sys.stderr)
    return 1


def load_render_plan(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"render plan is missing or not a file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read render plan {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("render plan must be an object")
    if not isinstance(value.get("nodes"), dict):
        raise ValueError("render plan nodes must be an object")
    return value


def valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-plan", required=True)
    parser.add_argument("--canvas", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    render_plan_path = Path(args.render_plan).resolve()
    canvas_path = Path(args.canvas).resolve()
    out_path = Path(args.out).resolve()
    if not canvas_path.is_file():
        return fail(f"canvas is missing or not a file: {canvas_path}")

    try:
        render_plan = load_render_plan(render_plan_path)
    except ValueError as exc:
        return fail(str(exc))

    mappings: list[dict[str, Any]] = []
    for node_id, node in sorted(render_plan["nodes"].items()):
        if not isinstance(node, dict):
            return fail(f"render node {node_id!r} must be an object")
        implementation = node.get("implementation")
        if node.get("required") is not True and implementation not in VISIBLE_IMPLEMENTATIONS:
            continue
        if not isinstance(implementation, str) or not implementation:
            return fail(f"visible render node {node_id!r} has no implementation")
        bbox = node.get("bbox")
        if not valid_bbox(bbox):
            return fail(f"visible render node {node_id!r} has invalid bbox; expected four numbers")
        mappings.append(
            {
                "node": node_id,
                "bbox": bbox,
                "implementation": implementation,
                "widget": str(canvas_path),
                "renderMode": "absolute_positioned",
            }
        )

    output = {
        "schemaVersion": 1,
        "source": {
            "renderPlan": str(render_plan_path),
            "canvas": str(canvas_path),
        },
        "nodeMappings": mappings,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok implementation_map nodes={len(mappings)} out={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
