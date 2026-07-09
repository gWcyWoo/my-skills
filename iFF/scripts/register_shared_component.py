#!/usr/bin/env python3
"""Register (or update) one verified shared component in the project registry.

The registry maps a deterministic component signature (from
detect_shared_components.py) to the widget that renders it. Registration is
append-or-exact-update: re-registering the same signature with a DIFFERENT
widget_path fails loudly unless --force, so two divergent implementations of
the same component can never coexist silently.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from common import dump_json, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--name", required=True, help="widget class name, e.g. AppBottomTabs")
    parser.add_argument("--widget-path", required=True, help="project-relative dart file, e.g. lib/shared/widgets/app_bottom_tabs.dart")
    parser.add_argument("--asset", action="append", default=[], help="registered asset path (repeatable)")
    parser.add_argument("--source-spec-dir", required=True)
    parser.add_argument("--from-batch", help="batch_shared_components.json from detect_shared_components.py — "
                                             "stores the source row's canonical node order so consuming pages "
                                             "can map their own node ids onto the widget's keys")
    parser.add_argument("--component-expected", help="the shared component's own canvas *.expected.json — "
                                                     "its keyed nodes become the per-page fidelity expectation "
                                                     "(only keyed/rendered nodes, so no false 'missing')")
    parser.add_argument("--assets-incomplete", action="store_true",
                        help="record that some icon positions had no slice export in any batch row")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    registry_path = Path(args.registry).expanduser()
    try:
        registry = load_json(registry_path)
    except FileNotFoundError:
        registry = {"version": 1, "components": {}}
    if not isinstance(registry, dict) or not isinstance(registry.get("components"), dict):
        raise SystemExit(f"ERROR: registry has invalid schema: {registry_path}")

    existing = registry["components"].get(args.signature)
    if existing and existing.get("widget_path") != args.widget_path and not args.force:
        raise SystemExit(
            "ERROR: signature already registered to a different widget "
            f"({existing.get('widget_path')} != {args.widget_path}); pass --force only after "
            "confirming the old implementation is superseded"
        )

    source_spec_dir = str(Path(args.source_spec_dir).expanduser().resolve())

    canonical_nodes = None
    if args.from_batch:
        batch = load_json(Path(args.from_batch).expanduser())
        for comp in batch.get("components") or []:
            if comp.get("signature") != args.signature:
                continue
            for row in comp.get("rows") or []:
                if str(Path(row["spec_dir"]).expanduser().resolve()) == source_spec_dir:
                    canonical_nodes = row.get("canonical_nodes")
        if not canonical_nodes:
            raise SystemExit(f"ERROR: --from-batch has no canonical_nodes for {args.signature} "
                             f"at source spec dir {source_spec_dir}")

    expected_nodes = None
    if args.component_expected:
        expected_doc = load_json(Path(args.component_expected).expanduser())
        expected_nodes = expected_doc.get("nodes")
        if not isinstance(expected_nodes, dict) or not expected_nodes:
            raise SystemExit(f"ERROR: --component-expected has no nodes: {args.component_expected}")

    registry["components"][args.signature] = {
        "name": args.name,
        "widget_path": args.widget_path,
        "assets": sorted(set(args.asset)),
        "source_spec_dir": source_spec_dir,
        "canonical_nodes": canonical_nodes,
        "expected_nodes": expected_nodes,
        "assets_incomplete": bool(args.assets_incomplete),
        "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verified": True,
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    dump_json(registry, registry_path)
    print(f"ok registered {args.signature} -> {args.widget_path} ({len(registry['components'])} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
