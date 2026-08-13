#!/usr/bin/env python3
"""Detect shared UI components (nav headers, bottom tab bars, cross-row repeats)
across the spec_dirs of one iFF batch, resolve them against the project's
shared-component registry, and write per-spec_dir exclusion files consumed by
make_render_plan.py --shared.

Identity of a component is deterministic:
  1. the group root's Figma componentId when present (strongest signal), else
  2. a sha256 over the group's canonical subtree structure — per node
     (depth, type, relative bbox rounded to 1px, is_text), children sorted by
     (rel_y, rel_x, type). Names, text strings, fills, asset paths, and
     has_asset/exportable flags are excluded from the hash so the same
     component matches across pages that differ only in labels, selected
     state, or which page the designer marked slices on (the pooling case).

Asset pooling: identical structure gives a positional bijection between rows,
so an icon that has no slice export in row A can take its asset from row B.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from common import dump_json, load_json


DEFAULT_KINDS = ("header", "bottom_tabs")
LOCAL_FILENAME = "shared_components.local.json"


def canonical_subtree(root_id: str, by_id: dict[str, dict]) -> list[dict]:
    """Flatten the group subtree into a canonical, name/text/path-free record list."""
    root = by_id.get(root_id) or {}
    root_bbox = root.get("bbox") or [0, 0, 0, 0]
    origin_x, origin_y = float(root_bbox[0] or 0), float(root_bbox[1] or 0)
    records: list[dict] = []

    def rel_bbox(node: dict) -> list[int]:
        bbox = node.get("bbox") or [0, 0, 0, 0]
        return [
            int(round(float(bbox[0] or 0) - origin_x)),
            int(round(float(bbox[1] or 0) - origin_y)),
            int(round(float(bbox[2] or 0))),
            int(round(float(bbox[3] or 0))),
        ]

    def child_key(node: dict) -> tuple:
        bbox = rel_bbox(node)
        return (bbox[1], bbox[0], str(node.get("type") or ""))

    def has_paint_source(node: dict) -> bool:
        if node.get("asset") or node.get("text"):
            return True
        return any(
            bool(node.get(field))
            for field in (
                "fills", "rawFills", "solidFills", "gradientFills", "imageFills",
                "border", "shadow", "effects",
            )
        )

    def walk(node_id: str, depth: int, seen: set[str], covered_by_asset: bool) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        node = by_id.get(node_id)
        if not isinstance(node, dict):
            return
        records.append(
            {
                "node": node_id,
                "depth": depth,
                "type": str(node.get("type") or ""),
                "bbox": rel_bbox(node),
                "has_asset": bool(node.get("asset")),
                "is_text": bool(node.get("text")),
                "exportable": bool(node.get("exportable")),
                "has_paint_source": has_paint_source(node),
                "covered_by_asset": covered_by_asset,
                "is_leaf": not bool(node.get("children")),
                "visible": node.get("effectiveVisible", node.get("visible", True)) is not False,
            }
        )
        children = [by_id[c] for c in (node.get("children") or []) if c in by_id]
        descendants_covered = covered_by_asset or bool(node.get("asset"))
        for child in sorted(children, key=child_key):
            walk(child["id"], depth + 1, seen, descendants_covered)

    walk(root_id, 0, set(), False)
    return records


def signature_of(root_id: str, by_id: dict[str, dict]) -> tuple[str, list[dict]]:
    records = canonical_subtree(root_id, by_id)
    root = by_id.get(root_id) or {}
    component_id = root.get("componentId")
    if component_id:
        return f"componentId:{component_id}", records
    payload = json.dumps(
        [{k: r[k] for k in ("depth", "type", "bbox", "is_text")} for r in records],
        ensure_ascii=False,
        sort_keys=True,
    )
    return "struct:" + hashlib.sha256(payload.encode("utf-8")).hexdigest(), records


def load_registry(path: Path) -> dict:
    try:
        registry = load_json(path)
    except FileNotFoundError:
        return {"version": 1, "components": {}}
    if not isinstance(registry, dict) or not isinstance(registry.get("components"), dict):
        raise SystemExit(f"ERROR: registry has invalid schema: {path}")
    return registry


def _legacy_registry_entry(
    registered: dict[str, dict], rows: list[dict]
) -> tuple[str, dict] | None:
    """Bind a registry entry after signature-algorithm evolution.

    Source spec + canonical node order is a deterministic identity for the
    component that originally produced the registry entry.  It lets detector
    upgrades reuse verified components without trusting fuzzy names or bboxes.
    """
    matches: list[tuple[str, dict]] = []
    for old_signature, candidate in registered.items():
        source = candidate.get("source_spec_dir")
        canonical = candidate.get("canonical_nodes")
        if not source or not isinstance(canonical, list) or not canonical:
            continue
        for row in rows:
            row_nodes = [record["node"] for record in row["records"]]
            if Path(source).resolve() == Path(row["spec_dir"]).resolve() and row_nodes == canonical:
                matches.append((old_signature, candidate))
                break
    return matches[0] if len(matches) == 1 else None


def _registered_entry_covers_paint(entry: dict | None, positions: list[int]) -> bool:
    if not entry:
        return False
    canonical = entry.get("canonical_nodes") or []
    expected = entry.get("expected_nodes") or {}
    paint_markers = ("image", "asset", "svg", "png", "reference_region")
    for position in positions:
        if position >= len(canonical):
            return False
        implementation = str((expected.get(canonical[position]) or {}).get("impl") or "").lower()
        if not any(marker in implementation for marker in paint_markers):
            return False
    return True


def normalize_component_bbox(
    bbox: object, artboard_width: object, kind: str
) -> tuple[object, dict | None]:
    """Adapt a common malformed right-edge-as-x export for header components."""
    if not isinstance(bbox, list) or len(bbox) != 4 or kind != "header":
        return bbox, None
    try:
        x, y, width, height = (float(value) for value in bbox)
        boundary = float(artboard_width)
    except (TypeError, ValueError):
        return bbox, None
    if not (0 <= x <= boundary and width > 0 and x + width > boundary and x - width >= 0):
        return bbox, None
    normalized = [x - width, y, width, height]
    return normalized, {
        "reason": "right_edge_encoded_as_x",
        "originalBbox": bbox,
        "normalizedBbox": normalized,
        "artboardWidth": boundary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dirs", nargs="+", required=True,
                        help="spec_dir paths of the current batch rows "
                             "(each needs scene.json + groups.json + assets_manifest.json)")
    parser.add_argument("--registry", required=True,
                        help="project shared-component registry, e.g. <project>/.iff/shared_components.json")
    parser.add_argument("--kinds", default=",".join(DEFAULT_KINDS),
                        help="group kinds that are shared-chrome candidates even in a single row")
    parser.add_argument("--out", required=True, help="batch resolution JSON")
    parser.add_argument("--no-local", action="store_true",
                        help=f"skip writing <spec_dir>/{LOCAL_FILENAME}")
    args = parser.parse_args()

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    registry_path = Path(args.registry).expanduser()
    registry = load_registry(registry_path)
    registered = registry["components"]

    # occurrences[signature] -> list of {spec_dir, group..., records}
    occurrences: dict[str, list[dict]] = {}
    kind_by_signature: dict[str, str] = {}
    errors: list[str] = []

    for spec_dir in args.spec_dirs:
        spec = Path(spec_dir).expanduser().resolve()
        try:
            scene = load_json(spec / "scene.json")
            groups_doc = load_json(spec / "groups.json")
            assets = load_json(spec / "assets_manifest.json")
        except FileNotFoundError as exc:
            errors.append(f"{spec}: missing artifact ({exc})")
            continue
        by_id = {node["id"]: node for node in (scene.get("nodes") or [])}
        asset_ids = set(assets.keys()) if isinstance(assets, dict) else set()
        covered_by_asset = {
            record["node"]
            for asset_id in asset_ids
            for record in canonical_subtree(asset_id, by_id)
            if record["node"] != asset_id
        }
        for group in groups_doc.get("groups") or []:
            root_id = str(group.get("node") or "")
            if not root_id or root_id not in by_id:
                continue
            if root_id in covered_by_asset:
                continue
            signature, records = signature_of(root_id, by_id)
            component_bbox, bbox_adaptation = normalize_component_bbox(
                group.get("bbox"),
                (scene.get("artboard") or {}).get("width"),
                str(group.get("kind") or "region"),
            )
            exportable = [r for r in records if r["exportable"]]
            occurrences.setdefault(signature, []).append(
                {
                    "spec_dir": str(spec),
                    "group_id": group.get("id"),
                    "group_node": root_id,
                    "group_name": (by_id.get(root_id) or {}).get("name"),
                    "kind": group.get("kind"),
                    "bbox": component_bbox,
                    "bbox_adaptation": bbox_adaptation,
                    "records": records,
                    "exportable_nodes": len(exportable),
                    "asset_nodes": sum(1 for r in records if r["has_asset"]),
                }
            )
            kind_by_signature.setdefault(signature, str(group.get("kind") or "region"))

    if errors:
        raise SystemExit("ERROR: detect_shared_components inputs invalid:\n" + "\n".join(errors))

    components = []
    for signature, rows in sorted(occurrences.items()):
        row_dirs = {row["spec_dir"] for row in rows}
        kind = kind_by_signature[signature]
        is_candidate = kind in kinds or len(row_dirs) >= 2 or signature in registered
        if not is_candidate:
            continue

        # Positional asset pooling: identical structure => same canonical index
        # across rows; take each exportable position's asset from the first row
        # that has one.
        pooled_assets: dict[str, dict] = {}
        missing_positions: list[int] = []
        paint_missing_positions: list[int] = []
        record_count = min(len(row["records"]) for row in rows)
        for index in range(record_count):
            records_at_position = [row["records"][index] for row in rows]
            if any(record["exportable"] or record["has_asset"] for record in records_at_position):
                source = next((row for row in rows if row["records"][index]["has_asset"]), None)
                if source is None:
                    missing_positions.append(index)
                else:
                    pooled_assets[str(index)] = {
                        "spec_dir": source["spec_dir"],
                        "node": source["records"][index]["node"],
                    }
            visible_leaf = any(record["visible"] and record["is_leaf"] for record in records_at_position)
            if visible_leaf and not any(
                record["has_paint_source"] or record["covered_by_asset"]
                for record in records_at_position
            ):
                paint_missing_positions.append(index)
        best = max(rows, key=lambda row: row["asset_nodes"])
        entry = registered.get(signature)
        if entry is None:
            legacy = _legacy_registry_entry(registered, rows)
            if legacy is not None:
                old_signature, entry = legacy
                print(f"INFO: rebound verified shared component {old_signature} -> {signature} "
                      "by source spec + canonical node identity")
        registered_paint_covered = _registered_entry_covers_paint(
            entry, paint_missing_positions
        ) if paint_missing_positions else False
        unresolved_paint_positions = (
            [] if registered_paint_covered else paint_missing_positions
        )
        reusable_entry = entry if entry and not unresolved_paint_positions else None
        # canonical order gives a positional bijection page-node <-> source-node,
        # so consuming pages can verify the mounted shared widget (whose canvas
        # keys are SOURCE node ids) against their OWN scene geometry.
        node_maps: dict[str, dict[str, str]] = {}
        source_nodes = (reusable_entry or {}).get("canonical_nodes") or []
        if source_nodes:
            for row in rows:
                row_nodes = [r["node"] for r in row["records"]]
                if len(row_nodes) != len(source_nodes):
                    print(f"WARNING: canonical length mismatch for {signature} in {row['spec_dir']} "
                          f"({len(row_nodes)} != {len(source_nodes)}); per-page fidelity mapping skipped")
                    continue
                node_maps[row["spec_dir"]] = dict(zip(row_nodes, source_nodes))
        components.append(
            {
                "signature": signature,
                "kind": kind,
                "status": "reuse" if reusable_entry else "missing",
                "widget": reusable_entry,
                "rows": [
                    {
                        **{k: row[k] for k in ("spec_dir", "group_id", "group_node", "group_name", "kind", "bbox",
                                               "bbox_adaptation", "exportable_nodes", "asset_nodes")},
                        "canonical_nodes": [r["node"] for r in row["records"]],
                        "node_map": node_maps.get(row["spec_dir"]),
                    }
                    for row in rows
                ],
                "best_asset_source": best["spec_dir"],
                "pooled_assets": pooled_assets,
                "assets_incomplete": bool(missing_positions or unresolved_paint_positions),
                "assets_missing_positions": missing_positions,
                "paint_missing_positions": unresolved_paint_positions,
                "source_paint_missing_positions": paint_missing_positions,
            }
        )

    resolution = {
        "registry": str(registry_path),
        "kinds": sorted(kinds),
        "spec_dirs": [str(Path(d).expanduser().resolve()) for d in args.spec_dirs],
        "components": components,
    }
    dump_json(resolution, args.out)

    if not args.no_local:
        for spec_dir in resolution["spec_dirs"]:
            local = {
                "registry": str(registry_path),
                "components": [
                    {
                        "signature": comp["signature"],
                        "kind": comp["kind"],
                        "status": comp["status"],
                        "name": (comp["widget"] or {}).get("name"),
                        "widget_path": (comp["widget"] or {}).get("widget_path"),
                        "group_node": row["group_node"],
                        "bbox": row["bbox"],
                        "bbox_adaptation": row.get("bbox_adaptation"),
                        "node_map": row.get("node_map"),
                        "expected_nodes": (comp["widget"] or {}).get("expected_nodes"),
                    }
                    for comp in components
                    for row in comp["rows"]
                    if row["spec_dir"] == spec_dir
                ],
            }
            dump_json(local, Path(spec_dir) / LOCAL_FILENAME)

    reuse = sum(1 for c in components if c["status"] == "reuse")
    missing = sum(1 for c in components if c["status"] == "missing")
    incomplete = [c["signature"] for c in components if c["assets_incomplete"]]
    print(f"ok shared components: {len(components)} candidates, {reuse} reuse, {missing} missing")
    if incomplete:
        print("WARNING assets_incomplete (missing slice asset or visible leaf paint source): "
              + ", ".join(incomplete))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
