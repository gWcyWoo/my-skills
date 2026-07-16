#!/usr/bin/env python3
"""Deterministically exclude device/system chrome from design scene nodes."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
from typing import Any


TIME_RE = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)")
STATUS_CONTAINER_RE = re.compile(r"status[\s_-]*bar|system[\s_-]*bar|状态栏|系统栏")
STATUS_INDICATOR_RES = (
    re.compile(r"cellular|mobile[\s_-]*signal|蜂窝|信号"),
    re.compile(r"wi[\s_-]*fi|无线网络"),
    re.compile(r"battery|电量"),
)
CAMERA_RE = re.compile(
    r"dynamic[\s_-]*island|camera[\s_-]*(?:cutout|hole|island)?|display[\s_-]*cutout|notch|sensor[\s_-]*housing|"
    r"灵动岛|摄像头|挖孔|刘海"
)


def _bbox(node: dict[str, Any]) -> tuple[float, float, float, float] | None:
    value = node.get("bbox")
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x, y, width, height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _asset_path(node: dict[str, Any], asset_base: Path | None) -> Path | None:
    asset = node.get("asset")
    variants = node.get("assetVariants")
    value: Any = variants.get("svg_path") if isinstance(variants, dict) else None
    if value is None:
        value = asset
    if isinstance(asset, dict):
        # SVG retains semantic ids/text even when the render-preferred path is PNG/WebP.
        value = asset.get("svg_path") or asset.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute() and asset_base is not None:
        path = asset_base / path
    return path


def _svg_fingerprint(node: dict[str, Any], asset_base: Path | None) -> str:
    path = _asset_path(node, asset_base)
    if path is None or path.suffix.lower() != ".svg" or not path.is_file():
        return ""
    try:
        if path.stat().st_size > 2_000_000:
            return ""
        return html.unescape(path.read_text(encoding="utf-8", errors="ignore")).lower()
    except OSError:
        return ""


def _fingerprint(node: dict[str, Any], asset_base: Path | None) -> str:
    fields = (node.get("name"), node.get("path"), node.get("text"))
    return " ".join(str(value) for value in fields if value is not None).lower() + " " + _svg_fingerprint(node, asset_base)


def _contains_dark(value: Any) -> bool:
    if isinstance(value, str):
        compact = value.lower().replace(" ", "")
        return any(token in compact for token in ("#000", "black", "0x000000"))
    if isinstance(value, list):
        return any(_contains_dark(item) for item in value)
    if not isinstance(value, dict):
        return False
    color = value.get("color") if isinstance(value.get("color"), dict) else value
    if all(channel in color for channel in ("r", "g", "b")):
        try:
            channels = [float(color[channel]) for channel in ("r", "g", "b")]
            limit = 0.18 if max(channels) <= 1 else 46
            if max(channels) <= limit:
                return True
        except (TypeError, ValueError):
            pass
    return any(_contains_dark(item) for item in value.values())


def _is_dark(node: dict[str, Any], asset_base: Path | None) -> bool:
    if _contains_dark(node.get("solidFills")) or _contains_dark(node.get("fills")):
        return True
    svg = _svg_fingerprint(node, asset_base).replace(" ", "")
    return any(token in svg for token in ('fill="black"', "fill='#000", 'fill="#000'))


def exclude_system_ui(
    nodes: list[dict[str, Any]],
    artboard_bbox: list[Any] | tuple[Any, ...],
    *,
    asset_base: Path | None = None,
    explicit_node_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Mark system chrome non-visible while preserving the source graph for audits."""
    try:
        art_x, art_y, art_width, art_height = (float(item) for item in artboard_bbox)
    except (TypeError, ValueError):
        return []
    if art_width <= 0 or art_height <= 0:
        return []

    by_id = {str(node.get("id")): node for node in nodes if node.get("id") is not None}
    root_id = str(nodes[0].get("id")) if nodes else ""
    child_boxes = [box for node_id, node in by_id.items() if node_id != root_id if (box := _bbox(node)) is not None]
    margin_x = art_width * 0.25
    margin_y = art_height * 0.25
    relative_score = sum(
        1
        for x, y, width, height in child_boxes
        if -margin_x <= x <= art_width + margin_x
        and -margin_y <= y <= art_height + margin_y
        and x + width >= -margin_x
        and y + height >= -margin_y
    )
    absolute_score = sum(
        1
        for x, y, width, height in child_boxes
        if art_x - margin_x <= x <= art_x + art_width + margin_x
        and art_y - margin_y <= y <= art_y + art_height + margin_y
        and x + width >= art_x - margin_x
        and y + height >= art_y - margin_y
    )
    coordinate_x, coordinate_y = (0.0, 0.0) if relative_score > absolute_score else (art_x, art_y)
    children: dict[str, list[str]] = {}
    for node_id, node in by_id.items():
        children[node_id] = [str(item) for item in node.get("children") or [] if str(item) in by_id]

    descendants_cache: dict[str, list[str]] = {}

    def descendants(node_id: str) -> list[str]:
        if node_id in descendants_cache:
            return descendants_cache[node_id]
        result: list[str] = []
        stack = list(reversed(children.get(node_id, [])))
        seen: set[str] = set()
        while stack:
            child_id = stack.pop()
            if child_id in seen:
                continue
            seen.add(child_id)
            result.append(child_id)
            stack.extend(reversed(children.get(child_id, [])))
        descendants_cache[node_id] = result
        return result

    fingerprints = {node_id: _fingerprint(node, asset_base) for node_id, node in by_id.items()}
    top_band_bottom = coordinate_y + min(art_height * 0.10, art_width * 0.18)

    status_candidates: list[str] = []
    for node_id, node in by_id.items():
        if node_id == root_id:
            continue
        box = _bbox(node)
        if box is None:
            continue
        x, y, width, height = box
        in_top_band = y >= coordinate_y - 1 and y + height <= top_band_bottom + 1
        if not in_top_band:
            continue
        subtree_ids = [node_id, *descendants(node_id)]
        evidence = " ".join(fingerprints[item] for item in subtree_ids)
        explicit_container = bool(STATUS_CONTAINER_RE.search(evidence))
        indicator_count = sum(1 for pattern in STATUS_INDICATOR_RES if pattern.search(evidence))
        time_signal = bool(TIME_RE.search(evidence))
        wide_and_shallow = width >= art_width * 0.40 and height <= art_height * 0.12
        compact_companions = 0
        for child_id in descendants(node_id):
            child_box = _bbox(by_id[child_id])
            if child_box is None or TIME_RE.search(fingerprints[child_id]):
                continue
            _, _, child_width, child_height = child_box
            if child_width <= art_width * 0.15 and child_height <= art_height * 0.05:
                compact_companions += 1
        combined_status_signal = (
            (time_signal and indicator_count >= 1)
            or indicator_count >= 3
            or (time_signal and compact_companions >= 2)
        )
        if explicit_container or (wide_and_shallow and combined_status_signal):
            status_candidates.append(node_id)

    status_set = set(status_candidates)
    status_roots = [
        node_id
        for node_id in status_candidates
        if str(by_id[node_id].get("parent") or "") not in status_set
    ]
    exclusions: list[dict[str, Any]] = []
    excluded_ids: set[str] = set()

    def mark(node_id: str, role: str, reason: str) -> None:
        for target_id in [node_id, *descendants(node_id)]:
            if target_id in excluded_ids:
                continue
            target = by_id[target_id]
            target["visible"] = False
            target["effectiveVisible"] = False
            target["systemUi"] = {"excluded": True, "role": role, "reason": reason}
            excluded_ids.add(target_id)
            exclusions.append({"node": target_id, "role": role, "reason": reason})

    for node_id in sorted(set(explicit_node_ids or [])):
        if node_id not in by_id:
            raise ValueError(f"unknown explicit exclusion node: {node_id}")
        if node_id == root_id:
            raise ValueError("artboard root cannot be explicitly excluded")
        mark(
            node_id,
            "confirmed_device_artifact",
            "explicit node confirmed as non-app device or capture artifact",
        )

    for node_id in sorted(status_roots, key=lambda item: (int(by_id[item].get("depth") or 0), item)):
        mark(node_id, "status_bar", "top-band status indicators or time fingerprint")

    for node_id, node in by_id.items():
        if node_id == root_id or node_id in excluded_ids:
            continue
        box = _bbox(node)
        if box is None:
            continue
        x, y, width, height = box
        center_x = x + width / 2
        centered = abs(center_x - (coordinate_x + art_width / 2)) <= art_width * 0.12
        compact = 4 <= width <= art_width * 0.36 and 4 <= height <= art_height * 0.08
        in_top_band = y >= coordinate_y - 1 and y + height <= top_band_bottom + 1
        aspect = width / height
        explicit = bool(CAMERA_RE.search(fingerprints[node_id]))
        geometry_signal = bool(status_roots) and centered and compact and 0.45 <= aspect <= 6 and _is_dark(node, asset_base)
        if in_top_band and centered and compact and (explicit or geometry_signal):
            mark(node_id, "camera_cutout", "top-center cutout geometry or semantic fingerprint")

    return exclusions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--asset-base", type=Path)
    parser.add_argument("--exclude-node", action="append", default=[])
    args = parser.parse_args()
    scene = json.loads(args.scene.read_text(encoding="utf-8"))
    nodes = scene.get("nodes") or []
    artboard = scene.get("artboard") or {}
    artboard_bbox = artboard.get("bbox") or (nodes[0].get("bbox") if nodes else None)
    exclusions = exclude_system_ui(
        nodes,
        artboard_bbox or [],
        asset_base=args.asset_base or args.scene.parent,
        explicit_node_ids=args.exclude_node,
    )
    scene["systemUiExclusions"] = exclusions
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "excludedCount": len(exclusions), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
