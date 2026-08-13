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
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from common import dump_json, load_json
from check_component_contract import validate_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--source-alias", action="append", default=[])
    parser.add_argument("--role-map", help="JSON with nodeRoleNodes and aliasRoleIndices")
    parser.add_argument("--name", required=True, help="widget class name, e.g. AppBottomTabs")
    parser.add_argument("--widget-path", required=True, help="project-relative dart file, e.g. lib/shared/widgets/app_bottom_tabs.dart")
    parser.add_argument("--project-root")
    parser.add_argument("--consumer-id")
    parser.add_argument("--consumer-visual-gate")
    parser.add_argument("--asset", action="append", default=[], help="registered asset path (repeatable)")
    parser.add_argument("--source-spec-dir", required=True)
    parser.add_argument("--from-batch", help="batch_shared_components.json from detect_shared_components.py — "
                                             "stores the source row's canonical node order so consuming pages "
                                             "can map their own node ids onto the widget's keys")
    parser.add_argument("--component-expected", help="the shared component's own canvas *.expected.json — "
                                                     "its keyed nodes become the per-page fidelity expectation "
                                                     "(only keyed/rendered nodes, so no false 'missing')")
    parser.add_argument("--component-contract")
    parser.add_argument("--assets-incomplete", action="store_true",
                        help="record that some icon positions had no slice export in any batch row")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.component_contract:
        print("ERROR: --component-contract is required")
        return 1
    contract_path = Path(args.component_contract).expanduser().resolve()
    if not contract_path.is_file():
        print(f"ERROR: component contract not found: {contract_path}")
        return 1
    contract = load_json(contract_path)
    family_id = contract.get("familyId")
    if not family_id:
        print(f"ERROR: component contract has no familyId: {contract_path}")
        return 1
    contract_sha256 = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    contract_failures = validate_contract(contract)
    if contract_failures:
        print(f"ERROR: invalid component contract {contract_path}:")
        for failure in contract_failures:
            print(f"  - {failure}")
        return 1

    if bool(args.consumer_id) != bool(args.consumer_visual_gate):
        print("ERROR: --consumer-id and --consumer-visual-gate must be provided together")
        return 1

    registry_path = Path(args.registry).expanduser()
    try:
        registry = load_json(registry_path)
    except FileNotFoundError:
        registry = {"version": 2, "components": {}}
    if not isinstance(registry, dict) or not isinstance(registry.get("components"), dict):
        raise SystemExit(f"ERROR: registry has invalid schema: {registry_path}")

    existing = registry["components"].get(args.signature)
    if existing and existing.get("widget_path") != args.widget_path and not args.force:
        raise SystemExit(
            "ERROR: signature already registered to a different widget "
            f"({existing.get('widget_path')} != {args.widget_path}); pass --force only after "
            "confirming the old implementation is superseded"
        )

    widget_source_sha256 = (existing or {}).get("widget_source_sha256")
    if args.project_root:
        widget_source = Path(args.project_root).expanduser().resolve() / args.widget_path
        if not widget_source.is_file():
            print(f"ERROR: shared component widget not found: {widget_source}")
            return 1
        source_failures = validate_contract(
            contract, widget_source.read_text(encoding="utf-8")
        )
        if source_failures:
            print(f"ERROR: invalid component source {widget_source}:")
            for failure in source_failures:
                print(f"  - {failure}")
            return 1
        widget_source_sha256 = hashlib.sha256(widget_source.read_bytes()).hexdigest()

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

    registry["version"] = 2
    source_aliases = sorted(set((existing or {}).get("source_aliases") or []) | set(args.source_alias))
    node_role_nodes = dict((existing or {}).get("node_role_nodes") or {})
    alias_role_indices = dict((existing or {}).get("alias_role_indices") or {})
    if args.role_map:
        role_map = load_json(Path(args.role_map).expanduser())
        proposed_nodes = role_map.get("nodeRoleNodes")
        proposed_aliases = role_map.get("aliasRoleIndices")
        if not isinstance(proposed_nodes, dict) or not proposed_nodes:
            print("ERROR: role map nodeRoleNodes must be a non-empty object")
            return 1
        if not isinstance(proposed_aliases, dict) or not proposed_aliases:
            print("ERROR: role map aliasRoleIndices must be a non-empty object")
            return 1
        for alias, roles in proposed_aliases.items():
            if alias not in source_aliases:
                print(f"ERROR: role map alias is not registered: {alias}")
                return 1
            if not isinstance(roles, dict) or not roles:
                print(f"ERROR: role map for {alias} must be a non-empty object")
                return 1
            for role, index in roles.items():
                if role not in proposed_nodes:
                    print(f"ERROR: role {role} has no canonical node")
                    return 1
                if not isinstance(index, int) or index < 0:
                    print(f"ERROR: role {role} has invalid canonical index: {index}")
                    return 1
        node_role_nodes = proposed_nodes
        alias_role_indices.update(proposed_aliases)
    consumers = list((existing or {}).get("consumers") or [])
    if args.consumer_id:
        consumers = [item for item in consumers if item.get("id") != args.consumer_id]
        consumers.append({"id": args.consumer_id, "visual_gate": args.consumer_visual_gate})
        consumers.sort(key=lambda item: str(item.get("id") or ""))
    registry["components"][args.signature] = {
        "family_id": family_id,
        "contract_path": str(contract_path),
        "contract_sha256": contract_sha256,
        "source_aliases": source_aliases,
        "node_role_nodes": node_role_nodes,
        "alias_role_indices": alias_role_indices,
        "widget_source_sha256": widget_source_sha256,
        "consumers": consumers,
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
