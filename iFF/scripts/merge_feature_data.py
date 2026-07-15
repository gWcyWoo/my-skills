#!/usr/bin/env python3
"""Merge per-board data artifacts into one state-qualified feature contract."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, label: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {label}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--feature-manifest", required=True)
    parser.add_argument("--api-contract", required=True)
    parser.add_argument("--out-manifest", required=True)
    parser.add_argument("--out-bindings", required=True)
    args = parser.parse_args()

    spec_root = Path(args.spec_root).resolve()
    feature_path = Path(args.feature_manifest).resolve()
    contract_path = Path(args.api_contract).resolve()
    out_manifest = Path(args.out_manifest).resolve()
    out_bindings = Path(args.out_bindings).resolve()
    feature = load(feature_path, "feature manifest")
    load(contract_path, "API contract")
    states = feature.get("states") or {}
    if not states:
        raise SystemExit("ERROR: feature manifest has no states")

    components = []
    bindings = []
    needs_model = []
    board_inputs = {}
    board_names = []
    contract_hash = sha256(contract_path)
    for state, value in sorted(states.items()):
        board_name = value.get("board") if isinstance(value, dict) else None
        if not board_name:
            raise SystemExit(f"ERROR: state has no board: {state}")
        board_names.append(str(board_name))
        board = (spec_root / str(board_name)).resolve()
        if spec_root not in board.parents:
            raise SystemExit(f"ERROR: board escapes spec root: {board_name}")
        manifest_path = board / "component_manifest.json"
        bindings_path = board / "data_slot_bindings.json"
        manifest = load(manifest_path, f"{state} component manifest")
        binding_doc = load(bindings_path, f"{state} data bindings")
        recorded = binding_doc.get("inputs") or {}
        if (
            recorded.get("component_manifest.json") != sha256(manifest_path)
            or recorded.get("api_contract.json") != contract_hash
        ):
            raise SystemExit(f"ERROR: stale board binding: {state}")

        expected = [
            slot.get("node")
            for component in manifest.get("components") or []
            for slot in component.get("dynamicSlots") or []
            if slot.get("node")
        ]
        actual = [
            entry.get("node")
            for entry in binding_doc.get("bindings") or []
            if entry.get("node")
        ]
        if Counter(expected) != Counter(actual) or any(
            count != 1 for count in Counter(expected).values()
        ):
            raise SystemExit(f"ERROR: board slot/binding mismatch: {state}")

        components.extend(
            {**component, "state": str(state), "board": str(board_name)}
            for component in manifest.get("components") or []
        )
        bindings.extend(
            {**entry, "state": str(state), "board": str(board_name)}
            for entry in binding_doc.get("bindings") or []
        )
        needs_model.extend(
            {**entry, "state": str(state), "board": str(board_name)}
            for entry in binding_doc.get("needsModelBinding") or []
        )
        board_inputs[str(state)] = {
            "board": str(board_name),
            "componentManifestPath": str(manifest_path),
            "componentManifestHash": sha256(manifest_path),
            "dataBindingsPath": str(bindings_path),
            "dataBindingsHash": sha256(bindings_path),
        }

    duplicates = [name for name, count in Counter(board_names).items() if count > 1]
    if duplicates:
        raise SystemExit(f"ERROR: states share data board: {', '.join(sorted(duplicates))}")

    merged_manifest = {
        "source": "merge_feature_data.py",
        "featureId": feature.get("featureId"),
        "featureManifestHash": sha256(feature_path),
        "stateCount": len(states),
        "components": components,
    }
    out_manifest.write_text(
        json.dumps(merged_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    merged_bindings = {
        "source": "merge_feature_data.py",
        "inputs": {
            "component_manifest.json": sha256(out_manifest),
            "api_contract.json": contract_hash,
            "feature_manifest.json": {
                "path": str(feature_path),
                "sha256": sha256(feature_path),
            },
            "boards": board_inputs,
        },
        "slotCount": len(bindings),
        "bindings": bindings,
        "needsModelBinding": needs_model,
    }
    out_bindings.write_text(
        json.dumps(merged_bindings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"ok feature data merge: states={len(states)} slots={len(bindings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
