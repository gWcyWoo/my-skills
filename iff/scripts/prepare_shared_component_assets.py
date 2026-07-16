#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import math
import shutil
from pathlib import Path

from PIL import Image

from common import dump_json, load_json


def _asset_path(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("path", "asset", "file"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


def _manifest_asset(spec_dir: Path, node_id: str) -> Path | None:
    manifest_path = spec_dir / "assets_manifest.json"
    manifest = load_json(manifest_path)
    rel = _asset_path(manifest.get(node_id)) if isinstance(manifest, dict) else None
    if not rel:
        return None
    source = Path(rel)
    if not source.is_absolute():
        source = manifest_path.parent / source
    return source


def _bbox(value: object, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise SystemExit(f"ERROR: {label} must be a four-number bbox")
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"ERROR: {label} must be a four-number bbox") from exc
    if not all(math.isfinite(item) for item in result) or result[2] <= 0 or result[3] <= 0:
        raise SystemExit(f"ERROR: {label} must have finite coordinates and positive size")
    return result


def _reference_region_fallback(
    *,
    target_node: str,
    node: dict,
    component_bbox: object,
    source_spec: Path,
    target: Path,
    project_root: Path,
) -> tuple[str, dict]:
    if node.get("children"):
        raise SystemExit(f"ERROR: reference fallback target must be a leaf node: {target_node}")
    if node.get("visible") is False:
        raise SystemExit(f"ERROR: reference fallback target is hidden: {target_node}")
    paint_fields = (
        "asset",
        "text",
        "fills",
        "rawFills",
        "solidFills",
        "gradientFills",
        "imageFills",
        "border",
        "shadow",
        "effects",
    )
    if any(node.get(field) for field in paint_fields):
        raise SystemExit(f"ERROR: reference fallback target already has a paint source: {target_node}")

    group_x, group_y, _, _ = _bbox(component_bbox, "component bbox")
    node_x, node_y, width, height = _bbox(node.get("bbox"), f"node bbox {target_node}")
    source_bbox = [group_x + node_x, group_y + node_y, width, height]
    left = math.floor(source_bbox[0])
    top = math.floor(source_bbox[1])
    right = math.ceil(source_bbox[0] + source_bbox[2])
    bottom = math.ceil(source_bbox[1] + source_bbox[3])

    reference = source_spec / "reference.png"
    if not reference.is_file():
        raise SystemExit(f"ERROR: reference fallback requires {reference}")
    with Image.open(reference) as opened:
        image = opened.convert("RGBA")
        reference_width, reference_height = image.size
        if right <= 0 or bottom <= 0 or left >= reference_width or top >= reference_height:
            raise SystemExit(f"ERROR: reference fallback bbox is outside the reference: {target_node}")
        if left <= 0 and top <= 0 and right >= reference_width and bottom >= reference_height:
            raise SystemExit(f"ERROR: full-reference fallback is forbidden: {target_node}")
        cropped = image.crop((left, top, right, bottom))

    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    safe_node = target_node.replace(":", "_").replace("/", "_")
    destination = target / f"reference_region_{safe_node}_{digest[:12]}_{left}_{top}_{right}_{bottom}.png"
    cropped.save(destination, format="PNG")
    relative = destination.relative_to(project_root).as_posix()
    provenance = {
        "kind": "localized_reference_region",
        "node": target_node,
        "asset": relative,
        "reason": "missing_visible_paint_source",
        "reference": str(reference),
        "reference_sha256": digest,
        "reference_size": [reference_width, reference_height],
        "source_bbox": source_bbox,
        "pixel_bbox": [left, top, right - left, bottom - top],
    }
    return relative, provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--render-plan", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest-out", required=True)
    args = parser.parse_args()

    job = load_json(args.job)
    plan = load_json(args.render_plan)
    project_root = Path(job["project_root"]).expanduser().resolve()
    target_arg = Path(args.target).expanduser()
    target = target_arg.resolve() if target_arg.is_absolute() else (project_root / target_arg).resolve()
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise SystemExit(f"ERROR: shared asset target must be inside project root: {target}") from exc
    target.mkdir(parents=True, exist_ok=True)
    source_spec = Path(job["source_spec_dir"]).expanduser().resolve()
    nodes = plan.get("nodes") or {}
    canonical_nodes = job.get("canonical_nodes") or []
    copied = {}
    reference_fallbacks = []
    exported_assets = []

    def copy_for(target_node: str, spec_dir: Path, source_node: str) -> bool:
        source = _manifest_asset(spec_dir, source_node)
        if source is None:
            return False
        if not source.is_file():
            raise SystemExit(f"ERROR: missing shared asset {source}")
        safe_node = target_node.replace(":", "_").replace("/", "_")
        destination = target / f"{safe_node}_{source.name}"
        shutil.copy2(source, destination)
        relative = destination.relative_to(project_root).as_posix()
        if target_node in nodes:
            nodes[target_node]["asset"] = relative
            provenance = {
                "kind": "exported_design_asset",
                "node": target_node,
                "asset": relative,
                "source_node": source_node,
                "source": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            nodes[target_node]["assetProvenance"] = provenance
            exported_assets.append(provenance)
        copied[target_node] = relative
        return True

    for target_node, node in nodes.items():
        if node.get("asset") and copy_for(target_node, source_spec, target_node):
            continue

    for position, pooled in (job.get("pooled_assets") or {}).items():
        index = int(position)
        if index >= len(canonical_nodes):
            raise SystemExit(f"ERROR: pooled asset position {position} is outside canonical_nodes")
        target_node = str(canonical_nodes[index])
        if target_node in copied:
            continue
        pooled_spec = Path(pooled["spec_dir"]).expanduser().resolve()
        copy_for(target_node, pooled_spec, str(pooled["node"]))

    for position in job.get("paint_missing_positions") or []:
        index = int(position)
        if index >= len(canonical_nodes):
            raise SystemExit(f"ERROR: paint-missing position {position} is outside canonical_nodes")
        target_node = str(canonical_nodes[index])
        node = nodes.get(target_node)
        if not isinstance(node, dict):
            raise SystemExit(f"ERROR: paint-missing node is absent from render plan: {target_node}")
        if target_node in copied or node.get("asset"):
            continue
        relative, provenance = _reference_region_fallback(
            target_node=target_node,
            node=node,
            component_bbox=job.get("bbox"),
            source_spec=source_spec,
            target=target,
            project_root=project_root,
        )
        node["asset"] = relative
        node["implementation"] = "image_png"
        node["required"] = True
        node["renderMode"] = node.get("renderMode") or "absolute_positioned"
        node["reason"] = "localized reference fallback for missing visible paint source"
        node["assetProvenance"] = provenance
        copied[target_node] = relative
        reference_fallbacks.append(provenance)

    plan["nodes"] = nodes
    dump_json(plan, args.out)
    dump_json(
        {
            "assets": copied,
            "assets_incomplete": bool(job.get("assets_incomplete")),
            "exported_assets": exported_assets,
            "reference_fallbacks": reference_fallbacks,
        },
        args.manifest_out,
    )
    print(f"ok shared assets: {len(copied)} copied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
