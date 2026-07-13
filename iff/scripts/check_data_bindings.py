#!/usr/bin/env python3
"""Validate that data-slot bindings describe the current deterministic inputs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from bind_data_slots import TRANSFORM_TYPES, flatten_fields


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--api-contract", required=True)
    parser.add_argument("--bindings", required=True)
    args = parser.parse_args()

    paths = {
        "component_manifest.json": Path(args.manifest),
        "api_contract.json": Path(args.api_contract),
    }
    bindings_path = Path(args.bindings)
    for label, path in {**paths, "data_slot_bindings.json": bindings_path}.items():
        if not path.is_file():
            raise SystemExit(f"ERROR: missing {label}: {path}")

    manifest = json.loads(paths["component_manifest.json"].read_text(encoding="utf-8"))
    contract = json.loads(paths["api_contract.json"].read_text(encoding="utf-8"))
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    recorded = bindings.get("inputs") or {}
    errors = []
    for label, path in paths.items():
        if recorded.get(label) != sha256(path):
            errors.append(f"stale {label}")
    feature_record = recorded.get("feature_manifest.json")
    if isinstance(feature_record, dict):
        feature_path = Path(str(feature_record.get("path") or ""))
        if not feature_path.is_file() or feature_record.get("sha256") != sha256(
            feature_path
        ):
            errors.append("stale merged feature manifest")
    for state, board_record in sorted((recorded.get("boards") or {}).items()):
        component_path = Path(str((board_record or {}).get("componentManifestPath") or ""))
        board_bindings_path = Path(str((board_record or {}).get("dataBindingsPath") or ""))
        if (
            not component_path.is_file()
            or not board_bindings_path.is_file()
            or (board_record or {}).get("componentManifestHash") != sha256(component_path)
            or (board_record or {}).get("dataBindingsHash") != sha256(board_bindings_path)
        ):
            errors.append(f"stale merged board: {state}")

    expected_keys = {
        (component.get("state"), slot.get("node"))
        for component in manifest.get("components") or []
        for slot in component.get("dynamicSlots") or []
        if slot.get("node")
    }
    key_counts = Counter(
        (entry.get("state"), entry.get("node"))
        for entry in bindings.get("bindings") or []
        if entry.get("node")
    )
    actual_keys = set(key_counts)

    def key_label(key: tuple[object, object]) -> str:
        state, node = key
        return f"{state}:{node}" if state is not None else str(node)

    for key in sorted(expected_keys - actual_keys, key=lambda value: str(value)):
        errors.append(f"missing binding: {key_label(key)}")
    for key in sorted(expected_keys, key=lambda value: str(value)):
        if key_counts[key] > 1:
            errors.append(f"duplicate binding: {key_label(key)}")
    for entry in bindings.get("bindings") or []:
        node = entry.get("node")
        key = (entry.get("state"), node)
        if key not in expected_keys or key_counts[key] != 1:
            continue
        field = (entry.get("binding") or {}).get("field")
        static_reason = entry.get("staticReason")
        if field and isinstance(static_reason, str) and static_reason.strip():
            errors.append(f"conflicting dynamic/static resolution: {node}")
        if not field and not (isinstance(static_reason, str) and static_reason.strip()):
            errors.append(f"unresolved binding: {node}")
        if (
            isinstance(static_reason, str)
            and static_reason.strip()
            and entry.get("confirmedByModel") is not True
        ):
            errors.append(f"static reason requires model confirmation: {node}")
    contract_fields = {
        json.dumps(field, ensure_ascii=False, sort_keys=True)
        for field in flatten_fields(contract)
    }
    for entry in bindings.get("bindings") or []:
        node = entry.get("node")
        binding = entry.get("binding") or {}
        field = binding.get("field")
        if field and json.dumps(field, ensure_ascii=False, sort_keys=True) not in contract_fields:
            errors.append(f"field absent from current contract: {node}")
        if (
            field
            and entry.get("confirmedByModel") is not True
        ):
            errors.append(f"model confirmation required: {node}")
        allowed_types = TRANSFORM_TYPES.get(binding.get("transform"))
        if field and binding.get("transform") not in TRANSFORM_TYPES:
            errors.append(f"unknown transform: {node}")
        if field and allowed_types and field.get("type") not in allowed_types:
            errors.append(f"transform/type mismatch: {node}")

    if errors:
        raise SystemExit("ERROR: invalid data bindings:\n" + "\n".join(f"- {e}" for e in errors))
    print(f"ok data bindings: {bindings_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
