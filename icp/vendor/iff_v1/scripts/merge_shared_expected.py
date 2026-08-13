#!/usr/bin/env python3
"""Merge shared-component expectations into a page's canvas expected.json so
check_render_fidelity verifies the mounted shared widget on EVERY consuming
page, not only at component birth.

The mounted widget's canvas keys are SOURCE-row node ids; the page's scene uses
its OWN node ids. detect_shared_components.py provides the positional bijection
(node_map) and the registry provides the component's own keyed expected nodes
(exactly what the widget renders — so no false 'missing' for unkeyed
containers). Each merged entry asserts bbox (page coordinates) + presence;
text/color stay unasserted here because labels/selected state are parameters —
icon shape is gated separately by check_render_fidelity --diff-report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import dump_json, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, help="page canvas *.expected.json")
    parser.add_argument("--local", required=True, help="spec_dir/shared_components.local.json")
    parser.add_argument("--scene", required=True, help="page scene.json (bbox source, page coords)")
    parser.add_argument("--out", required=True, help="merged expected.json")
    args = parser.parse_args()

    expected_doc = load_json(args.expected)
    nodes = dict(expected_doc.get("nodes") or {})
    try:
        local = load_json(args.local)
    except FileNotFoundError:
        local = {}  # no shared components on this page -> pass-through copy

    unresolved = [
        {
            "signature": comp.get("signature"),
            "group_node": comp.get("group_node"),
            "bbox": comp.get("bbox"),
        }
        for comp in (local.get("components") or [])
        if comp.get("status") == "missing"
    ]
    if unresolved:
        raise SystemExit(
            "ERROR: unresolved shared components cannot be omitted from merged expectations: "
            + json.dumps(unresolved, ensure_ascii=False)
        )
    scene = load_json(args.scene)
    by_id = {node["id"]: node for node in (scene.get("nodes") or [])}

    merged = 0
    skipped = 0
    for comp in local.get("components") or []:
        if comp.get("status") != "reuse":
            continue
        node_map = comp.get("node_map")
        expected_nodes = comp.get("expected_nodes")
        if not node_map or not isinstance(expected_nodes, dict):
            print(f"WARNING: shared component {comp.get('name') or comp.get('signature')} has no "
                  "node_map/expected_nodes — its region stays unverified on this page "
                  "(re-register with --from-batch/--component-expected)")
            continue
        source_to_page = {source: page for page, source in node_map.items()}
        for source_id in expected_nodes:
            page_node = source_to_page.get(source_id)
            page_bbox = (by_id.get(page_node) or {}).get("bbox") if page_node else None
            if page_node and page_node == comp.get("group_node") and comp.get("bbox"):
                page_bbox = comp["bbox"]
            if not page_bbox:
                skipped += 1
                continue
            if source_id in nodes:
                raise SystemExit(f"ERROR: shared expected key collides with page canvas key: {source_id}")
            nodes[source_id] = {"bbox": page_bbox, "impl": "shared_component",
                                "sharedComponent": comp.get("name"), "pageNode": page_node}
            merged += 1

    out_doc = dict(expected_doc)
    out_doc["nodes"] = nodes
    dump_json(out_doc, args.out)
    print(f"ok merged {merged} shared-component node expectation(s) into {args.out}"
          + (f" ({skipped} unmappable skipped)" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
