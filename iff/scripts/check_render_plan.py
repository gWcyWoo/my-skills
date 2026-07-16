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
PAINT_REQUIRED_IMPLEMENTATIONS = {
    "gradient_shape",
    "oval_shape",
    "shape",
    "shape_container",
    "vector_shape",
}


def has_paint_source(item: dict) -> bool:
    if item.get("asset"):
        return True
    return any(item.get(key) for key in ("fills", "solidFills", "gradientFills", "imageFills", "border", "shadow", "effects"))
COORDINATE_RENDER_MODES = {"absolute_positioned", "absolute_bbox", "render_plan_bbox", "coordinate_canvas"}


def valid_local_reference_fallback(node_id: str, item: dict) -> bool:
    provenance = item.get("assetProvenance")
    if not isinstance(provenance, dict) or provenance.get("kind") != "localized_reference_region":
        return False
    if provenance.get("asset") != item.get("asset") or provenance.get("node") != node_id:
        return False
    digest = provenance.get("reference_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return False
    reference_size = provenance.get("reference_size")
    pixel_bbox = provenance.get("pixel_bbox")
    if not isinstance(reference_size, list) or len(reference_size) != 2:
        return False
    if not isinstance(pixel_bbox, list) or len(pixel_bbox) != 4:
        return False
    try:
        reference_width, reference_height = (float(value) for value in reference_size)
        left, top, width, height = (float(value) for value in pixel_bbox)
    except (TypeError, ValueError):
        return False
    if reference_width <= 0 or reference_height <= 0 or width <= 0 or height <= 0:
        return False
    if left + width <= 0 or top + height <= 0 or left >= reference_width or top >= reference_height:
        return False
    return not (left <= 0 and top <= 0 and left + width >= reference_width and top + height >= reference_height)


def valid_exported_design_asset(node_id: str, item: dict) -> bool:
    provenance = item.get("assetProvenance")
    if not isinstance(provenance, dict) or provenance.get("kind") != "exported_design_asset":
        return False
    if provenance.get("asset") != item.get("asset") or provenance.get("node") != node_id:
        return False
    if not str(provenance.get("source_node") or "").strip() or not str(provenance.get("source") or "").strip():
        return False
    digest = provenance.get("source_sha256")
    return isinstance(digest, str) and len(digest) == 64 and not any(
        char not in "0123456789abcdef" for char in digest
    )


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
        system_ui = item.get("systemUi")
        if isinstance(system_ui, dict) and system_ui.get("excluded") is True:
            if impl != "hidden" or item.get("required") is True:
                errors.append(f"{node_id}: system UI must be hidden and non-required")
        local_reference_fallback = valid_local_reference_fallback(node_id, item)
        component_root = plan.get("componentRoot")
        exported_component_root = bool(
            valid_exported_design_asset(node_id, item)
            and plan.get("rootNode") == node_id
            and isinstance(component_root, dict)
            and component_root.get("node") == node_id
        )
        if impl in FORBIDDEN:
            errors.append(f"{node_id}: forbidden implementation {impl}")
        if item.get("asset") and "reference" in str(item["asset"]).lower() and not local_reference_fallback:
            errors.append(f"{node_id}: asset path looks like reference image")
        bbox = item.get("bbox")
        if item.get("asset") and isinstance(bbox, list) and len(bbox) == 4 and max_area and bbox[2] * bbox[3] >= max_area * 0.98 and not local_reference_fallback and not exported_component_root:
            errors.append(f"{node_id}: asset covers full artboard")
        if item.get("required") is True or impl in VISIBLE_IMPLEMENTATIONS:
            if item.get("renderMode") not in COORDINATE_RENDER_MODES:
                errors.append(f"{node_id}: visible node missing coordinate renderMode")
            if not (isinstance(bbox, list) and len(bbox) == 4 and bbox[2] > 0 and bbox[3] > 0):
                errors.append(f"{node_id}: visible node missing positive bbox")
            if impl in PAINT_REQUIRED_IMPLEMENTATIONS and not has_paint_source(item):
                errors.append(f"{node_id}: required visible shape has no paint source")
        if not item.get("widgetTraceRequired"):
            errors.append(f"{node_id}: widget trace is not required")
    if errors:
        raise SystemExit("ERROR: render plan invalid:\n" + "\n".join(errors))
    print("ok render plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
