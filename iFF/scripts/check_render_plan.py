#!/usr/bin/env python3
"""Fail if render_plan allows design-screenshot masquerading."""

from __future__ import annotations

import argparse

from common import load_json


FORBIDDEN = {"full_artboard_background", "reference_background", "generated_from_reference"}
VISIBLE_IMPLEMENTATIONS = {
    "asset",
    "gradient_shape",
    "image",
    "image_fill",
    "image_png",
    "image_webp",
    "oval_shape",
    "shape",
    "shape_container",
    "svg",
    "text",
    "vector_shape",
}
COORDINATE_RENDER_MODES = {"absolute_positioned", "absolute_bbox", "render_plan_bbox", "coordinate_canvas"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("render_plan")
    args = parser.parse_args()

    plan = load_json(args.render_plan)
    errors = []
    nodes = plan.get("nodes") or {}
    max_area = 0
    for item in nodes.values():
        bbox = item.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            max_area = max(max_area, bbox[2] * bbox[3])
    for node_id, item in nodes.items():
        impl = item.get("implementation")
        if impl in FORBIDDEN:
            errors.append(f"{node_id}: forbidden implementation {impl}")
        if item.get("asset") and "reference" in str(item["asset"]).lower():
            errors.append(f"{node_id}: asset path looks like reference image")
        bbox = item.get("bbox")
        if item.get("asset") and isinstance(bbox, list) and len(bbox) == 4 and max_area and bbox[2] * bbox[3] >= max_area * 0.98:
            errors.append(f"{node_id}: asset covers full artboard")
        if item.get("required") is True or impl in VISIBLE_IMPLEMENTATIONS:
            if item.get("renderMode") not in COORDINATE_RENDER_MODES:
                errors.append(f"{node_id}: visible node missing coordinate renderMode")
            if not (isinstance(bbox, list) and len(bbox) == 4 and bbox[2] > 0 and bbox[3] > 0):
                errors.append(f"{node_id}: visible node missing positive bbox")
        if not item.get("widgetTraceRequired"):
            errors.append(f"{node_id}: widget trace is not required")
    if errors:
        raise SystemExit("ERROR: render plan invalid:\n" + "\n".join(errors))
    print("ok render plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
