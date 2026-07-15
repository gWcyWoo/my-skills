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

    def walk(node_id: str, depth: int, seen: set[str]) -> None:
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
                "text": node.get("text"),
                "solidFills": node.get("solidFills"),
                "gradientFills": node.get("gradientFills"),
                "border": node.get("border"),
                "radius": node.get("radius"),
                "shadow": node.get("shadow"),
                "opacity": node.get("opacity"),
                "asset": node.get("asset"),
                "componentProperties": node.get("componentProperties"),
                "variantProperties": node.get("variantProperties"),
            }
        )
        children = [by_id[c] for c in (node.get("children") or []) if c in by_id]
        for child in sorted(children, key=child_key):
            walk(child["id"], depth + 1, seen)

    walk(root_id, 0, set())
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


def loose_signature_of(records: list[dict]) -> str:
    """Candidate-only skeleton that ignores optional leaf multiplicity and geometry."""
    payload = sorted(
        {
            (int(record.get("depth") or 0), str(record.get("type") or ""), bool(record.get("is_text")))
            for record in records
        }
    )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "loose:" + hashlib.sha256(encoded).hexdigest()


def variation_matrix(rows: list[dict]) -> list[dict]:
    fields = (
        "text",
        "solidFills",
        "gradientFills",
        "border",
        "radius",
        "shadow",
        "opacity",
        "asset",
        "componentProperties",
        "variantProperties",
    )
    variations: list[dict] = []
    record_count = min(len(row["records"]) for row in rows)
    for index in range(record_count):
        changed: dict[str, list[object]] = {}
        for field in fields:
            values_by_json = {
                json.dumps(row["records"][index].get(field), ensure_ascii=False, sort_keys=True):
                row["records"][index].get(field)
                for row in rows
            }
            if len(values_by_json) > 1:
                changed[field] = [values_by_json[key] for key in sorted(values_by_json)]
        if changed:
            variations.append(
                {
                    "index": index,
                    "type": rows[0]["records"][index]["type"],
                    "fields": changed,
                }
            )
    return variations


def load_registry(path: Path) -> dict:
    try:
        registry = load_json(path)
    except FileNotFoundError:
        return {"version": 1, "components": {}}
    if not isinstance(registry, dict) or not isinstance(registry.get("components"), dict):
        raise SystemExit(f"ERROR: registry has invalid schema: {path}")
    return registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dirs", nargs="+", required=True,
                        help="spec_dir paths of the current batch rows (each needs scene.json + groups.json)")
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
    registered_aliases: dict[str, dict] = {}
    for registered_entry in registered.values():
        for alias in registered_entry.get("source_aliases") or []:
            existing_alias = registered_aliases.get(alias)
            if existing_alias and existing_alias.get("family_id") != registered_entry.get("family_id"):
                raise SystemExit(f"ERROR: source alias belongs to multiple component families: {alias}")
            registered_aliases[alias] = registered_entry

    # occurrences[signature] -> list of {spec_dir, group..., records}
    occurrences: dict[str, list[dict]] = {}
    kind_by_signature: dict[str, str] = {}
    errors: list[str] = []

    for spec_dir in args.spec_dirs:
        spec = Path(spec_dir).expanduser().resolve()
        try:
            scene = load_json(spec / "scene.json")
            groups_doc = load_json(spec / "groups.json")
        except FileNotFoundError as exc:
            errors.append(f"{spec}: missing artifact ({exc})")
            continue
        by_id = {node["id"]: node for node in (scene.get("nodes") or [])}
        for group in groups_doc.get("groups") or []:
            root_id = str(group.get("node") or "")
            if not root_id or root_id not in by_id:
                continue
            signature, records = signature_of(root_id, by_id)
            exportable = [r for r in records if r["exportable"]]
            occurrences.setdefault(signature, []).append(
                {
                    "spec_dir": str(spec),
                    "group_id": group.get("id"),
                    "group_node": root_id,
                    "group_name": (by_id.get(root_id) or {}).get("name"),
                    "kind": group.get("kind"),
                    "bbox": group.get("bbox"),
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
        is_candidate = kind in kinds or len(row_dirs) >= 2 or signature in registered or signature in registered_aliases
        if not is_candidate:
            continue

        # Positional asset pooling: identical structure => same canonical index
        # across rows; take each exportable position's asset from the first row
        # that has one.
        pooled_assets: dict[str, dict] = {}
        missing_positions: list[int] = []
        record_count = min(len(row["records"]) for row in rows)
        for index in range(record_count):
            if not any(row["records"][index]["exportable"] or row["records"][index]["has_asset"] for row in rows):
                continue
            source = next((row for row in rows if row["records"][index]["has_asset"]), None)
            if source is None:
                missing_positions.append(index)
            else:
                pooled_assets[str(index)] = {
                    "spec_dir": source["spec_dir"],
                    "node": source["records"][index]["node"],
                }
        best = max(rows, key=lambda row: row["asset_nodes"])
        entry = registered.get(signature) or registered_aliases.get(signature)
        status = "reuse" if entry else ("candidate" if signature.startswith("struct:") else "missing")
        model_decision = None
        if status == "candidate":
            model_decision = {"required": True, "reason": "structural_match_only"}
        # canonical order gives a positional bijection page-node <-> source-node,
        # so consuming pages can verify the mounted shared widget (whose canvas
        # keys are SOURCE node ids) against their OWN scene geometry.
        node_maps: dict[str, dict[str, str]] = {}
        source_nodes = (entry or {}).get("canonical_nodes") or []
        node_role_nodes = (entry or {}).get("node_role_nodes") or {}
        alias_role_indices = ((entry or {}).get("alias_role_indices") or {}).get(signature)
        if alias_role_indices:
            for row in rows:
                mapped: dict[str, str] = {}
                for role, index in alias_role_indices.items():
                    source_node = node_role_nodes.get(role)
                    if source_node is None:
                        raise SystemExit(
                            f"ERROR: role {role} has no canonical node for {signature}"
                        )
                    if not isinstance(index, int) or not 0 <= index < len(row["records"]):
                        raise SystemExit(
                            f"ERROR: role {role} has invalid canonical index {index} "
                            f"for {signature} in {row['spec_dir']}"
                        )
                    mapped[row["records"][index]["node"]] = source_node
                node_maps[row["spec_dir"]] = mapped
        elif source_nodes:
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
                "status": status,
                "model_decision": model_decision,
                "loose_signature": loose_signature_of(rows[0]["records"]),
                "variations": variation_matrix(rows),
                "widget": entry,
                "rows": [
                    {
                        **{k: row[k] for k in ("spec_dir", "group_id", "group_node", "group_name", "kind", "bbox",
                                               "exportable_nodes", "asset_nodes")},
                        "canonical_nodes": [r["node"] for r in row["records"]],
                        "node_map": node_maps.get(row["spec_dir"]),
                    }
                    for row in rows
                ],
                "best_asset_source": best["spec_dir"],
                "pooled_assets": pooled_assets,
                "assets_incomplete": bool(missing_positions),
                "assets_missing_positions": missing_positions,
            }
        )

    by_loose: dict[str, list[str]] = {}
    for component in components:
        by_loose.setdefault(component["loose_signature"], []).append(component["signature"])
    for component in components:
        component["related_signatures"] = sorted(
            signature
            for signature in by_loose[component["loose_signature"]]
            if signature != component["signature"]
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
                        "model_decision": comp.get("model_decision"),
                        "name": (comp["widget"] or {}).get("name"),
                        "widget_path": (comp["widget"] or {}).get("widget_path"),
                        "group_node": row["group_node"],
                        "bbox": row["bbox"],
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
    candidates = sum(1 for c in components if c["status"] == "candidate")
    incomplete = [c["signature"] for c in components if c["assets_incomplete"]]
    print(
        f"ok shared components: {len(components)} total, {reuse} reuse, "
        f"{missing} missing, {candidates} semantic candidate(s)"
    )
    if incomplete:
        print("WARNING assets_incomplete (no row has a slice export for some icon positions): "
              + ", ".join(incomplete))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
