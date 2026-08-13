#!/usr/bin/env python3
"""Build and verify bounded assembly references to shared-component contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "iff.assembly_shared_components.index"
VERSION = 1
LOCAL_FILENAME = "shared_components.local.json"


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: invalid shared-component contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: shared-component contract must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _merge_records(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for group in groups:
        for record in group:
            key = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            records[key] = record
    return [records[key] for key in sorted(records)]


def _required_string(value: Any, *, field: str, source: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"ERROR: {source} requires non-empty {field}")
    return value


def _string_paths(value: Any, *, field: str, source: Path) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit(f"ERROR: {source} field {field} must be a list")
    paths: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and item:
            paths.append(item)
            continue
        if isinstance(item, dict):
            path = next(
                (item.get(key) for key in ("path", "file", "asset") if item.get(key)),
                None,
            )
            if isinstance(path, str):
                paths.append(path)
                continue
        raise SystemExit(f"ERROR: {source} field {field}[{index}] has no path contract")
    return sorted(set(paths))


def _contract_path(raw_path: str, *, source: Path) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = source.parent / path
    return path.resolve()


def _expected_contracts(
    registration: dict[str, Any],
    local_component: dict[str, Any],
    *,
    registry_path: Path,
    local_path: Path,
    registry_pointer: str,
    local_pointer: str,
) -> list[dict[str, str]]:
    contracts: list[dict[str, str]] = []
    for owner, value in (("registry", registration), ("local", local_component)):
        source = registry_path if owner == "registry" else local_path
        source_sha256 = _sha256(source)
        for key in ("expected_path", "component_expected", "component_expected_path"):
            path = value.get(key)
            if path is None:
                continue
            if not isinstance(path, str) or not path:
                raise SystemExit(f"ERROR: {source} field {key} must be a non-empty path")
            path_contract = {
                "kind": "path",
                "owner": owner,
                "path": path,
                "sourceContract": str(source),
                "sourceSha256": source_sha256,
            }
            resolved = _contract_path(path, source=source)
            if resolved.is_file():
                path_contract["contentSha256"] = _sha256(resolved)
                try:
                    expected_value = json.loads(resolved.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise SystemExit(f"ERROR: invalid expected JSON contract {resolved}: {error}")
                path_contract["semanticSha256"] = _semantic_sha256(expected_value)
            contracts.append(path_contract)
    if isinstance(registration.get("expected_nodes"), dict) and registration["expected_nodes"]:
        contracts.append(
            {
                "kind": "json_pointer",
                "owner": "registry",
                "path": str(registry_path),
                "pointer": f"{registry_pointer}/expected_nodes",
                "sourceSha256": _sha256(registry_path),
                "semanticSha256": _semantic_sha256(registration["expected_nodes"]),
            }
        )
    if isinstance(local_component.get("expected_nodes"), dict) and local_component["expected_nodes"]:
        contracts.append(
            {
                "kind": "json_pointer",
                "owner": "local",
                "path": str(local_path),
                "pointer": f"{local_pointer}/expected_nodes",
                "sourceSha256": _sha256(local_path),
                "semanticSha256": _semantic_sha256(local_component["expected_nodes"]),
            }
        )
    if not contracts:
        raise SystemExit(
            f"ERROR: reuse mapping {local_pointer} has no expected path or expected-node contract"
        )
    return contracts


def build_index(spec_root: Path) -> dict[str, Any]:
    spec_root = spec_root.expanduser().resolve()
    if not spec_root.is_dir():
        raise SystemExit(f"ERROR: assembly spec root not found: {spec_root}")
    board_dirs = sorted(path for path in spec_root.iterdir() if path.is_dir())
    if not board_dirs:
        raise SystemExit(f"ERROR: assembly spec root has no child board directories: {spec_root}")

    boards: list[dict[str, Any]] = []
    registrations: dict[str, dict[str, Any]] = {}
    reuse_mappings: list[dict[str, Any]] = []
    registry_hashes: dict[str, str] = {}

    for board in board_dirs:
        local_path = board / LOCAL_FILENAME
        if not local_path.is_file():
            boards.append(
                {
                    "board": board.name,
                    "specDir": str(board),
                    "localContract": None,
                    "componentCount": 0,
                }
            )
            continue
        local = _load_object(local_path)
        registry_raw = _required_string(
            local.get("registry"),
            field="registry",
            source=local_path,
        )
        registry_path = _contract_path(registry_raw, source=local_path)
        if not registry_path.is_file():
            raise SystemExit(f"ERROR: shared-component registry not found: {registry_path}")
        registry = _load_object(registry_path)
        registry_components = registry.get("components")
        if not isinstance(registry_components, dict):
            raise SystemExit(f"ERROR: registry components must be an object: {registry_path}")
        components = local.get("components")
        if not isinstance(components, list):
            raise SystemExit(f"ERROR: local components must be a list: {local_path}")
        local_hash = _sha256(local_path)
        registry_hash = registry_hashes.setdefault(str(registry_path), _sha256(registry_path))
        boards.append(
            {
                "board": board.name,
                "specDir": str(board),
                "localContract": str(local_path),
                "localSha256": local_hash,
                "registryContract": str(registry_path),
                "registrySha256": registry_hash,
                "componentCount": len(components),
            }
        )

        for component_index, component in enumerate(components):
            if not isinstance(component, dict):
                raise SystemExit(
                    f"ERROR: {local_path} components[{component_index}] must be an object"
                )
            local_pointer = f"#/components/{component_index}"
            signature = _required_string(
                component.get("signature"),
                field=f"components[{component_index}].signature",
                source=local_path,
            )
            status = _required_string(
                component.get("status"),
                field=f"components[{component_index}].status",
                source=local_path,
            )
            if status != "reuse":
                raise SystemExit(
                    f"ERROR: assembly shared component must be resolved to reuse: "
                    f"{signature} status={status}"
                )
            registration = registry_components.get(signature)
            if not isinstance(registration, dict):
                raise SystemExit(
                    f"ERROR: reuse mapping {signature} has no registry registration in {registry_path}"
                )
            if registration.get("verified") is not True:
                raise SystemExit(f"ERROR: shared-component registration is not verified: {signature}")
            registry_pointer = f"#/components/{signature.replace('~', '~0').replace('/', '~1')}"
            registration_name = _required_string(
                registration.get("name"),
                field=f"components[{signature}].name",
                source=registry_path,
            )
            widget_path = _required_string(
                registration.get("widget_path"),
                field=f"components[{signature}].widget_path",
                source=registry_path,
            )
            if component.get("name") not in (None, registration_name):
                raise SystemExit(f"ERROR: local/registry name mismatch for {signature}")
            if component.get("widget_path") not in (None, widget_path):
                raise SystemExit(f"ERROR: local/registry widget_path mismatch for {signature}")
            expected_contracts = _expected_contracts(
                registration,
                component,
                registry_path=registry_path,
                local_path=local_path,
                registry_pointer=registry_pointer,
                local_pointer=local_pointer,
            )
            expected_semantic_hashes = sorted(
                {
                    contract["semanticSha256"]
                    for contract in expected_contracts
                    if contract.get("semanticSha256")
                }
            )
            if len(expected_semantic_hashes) > 1:
                raise SystemExit(
                    f"ERROR: conflicting shared-component expected contract: {signature}"
                )
            assets_incomplete = registration.get("assets_incomplete", False)
            if not isinstance(assets_incomplete, bool):
                raise SystemExit(
                    f"ERROR: registry assets_incomplete must be boolean: {signature}"
                )
            semantic_contract = {
                "signature": signature,
                "name": registration_name,
                "widgetPath": widget_path,
                "assetsIncomplete": assets_incomplete,
            }
            previous = registrations.get(signature)
            if previous is None:
                previous = {
                    **semantic_contract,
                    "registryContracts": [],
                    "assetPaths": [],
                    "fontPaths": [],
                    "expectedContracts": [],
                    "expectedSemanticSha256": None,
                }
            else:
                previous_semantic = {
                    key: previous[key]
                    for key in ("signature", "name", "widgetPath", "assetsIncomplete")
                }
                if previous_semantic != semantic_contract:
                    raise SystemExit(
                        f"ERROR: conflicting shared-component registration: {signature}"
                    )
            expected_semantic_sha256 = (
                expected_semantic_hashes[0] if expected_semantic_hashes else None
            )
            previous_expected_sha256 = previous.get("expectedSemanticSha256")
            if (
                previous_expected_sha256
                and expected_semantic_sha256
                and previous_expected_sha256 != expected_semantic_sha256
            ):
                raise SystemExit(
                    f"ERROR: conflicting shared-component expected contract: {signature}"
                )
            previous["expectedSemanticSha256"] = (
                previous_expected_sha256 or expected_semantic_sha256
            )
            previous["registryContracts"] = _merge_records(
                previous["registryContracts"],
                [
                    {
                        "path": str(registry_path),
                        "sha256": registry_hash,
                        "pointer": registry_pointer,
                    }
                ],
            )
            previous["assetPaths"] = sorted(
                set(previous["assetPaths"])
                | set(
                    _string_paths(
                        registration.get("assets"),
                        field=f"components[{signature}].assets",
                        source=registry_path,
                    )
                )
            )
            previous["fontPaths"] = sorted(
                set(previous["fontPaths"])
                | set(
                    _string_paths(
                        registration.get("fonts"),
                        field=f"components[{signature}].fonts",
                        source=registry_path,
                    )
                )
            )
            previous["expectedContracts"] = _merge_records(
                previous["expectedContracts"], expected_contracts
            )
            registrations[signature] = previous

            node_map_contract = None
            if component.get("node_map") is not None:
                if not isinstance(component["node_map"], dict):
                    raise SystemExit(f"ERROR: node_map must be an object for {signature}")
                node_map_contract = {
                    "path": str(local_path),
                    "pointer": f"{local_pointer}/node_map",
                }
            reuse_mappings.append(
                {
                    "board": board.name,
                    "signature": signature,
                    "localContract": str(local_path),
                    "localSha256": local_hash,
                    "componentPointer": local_pointer,
                    "groupNode": component.get("group_node"),
                    "bbox": component.get("bbox"),
                    "nodeMapContract": node_map_contract,
                    "expectedContracts": expected_contracts,
                }
            )

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "specRoot": str(spec_root),
        "counts": {
            "boards": len(boards),
            "localContracts": sum(1 for board in boards if board["localContract"]),
            "uniqueRegistrations": len(registrations),
            "reuseMappings": len(reuse_mappings),
        },
        "boards": boards,
        "registrations": [registrations[key] for key in sorted(registrations)],
        "reuseMappings": sorted(
            reuse_mappings,
            key=lambda value: (value["board"], value["signature"]),
        ),
    }


def write_index(index: dict[str, Any], out: Path) -> None:
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def check_index(index_path: Path) -> dict[str, Any]:
    index_path = index_path.expanduser().resolve()
    recorded = _load_object(index_path)
    if recorded.get("schema") != SCHEMA or recorded.get("version") != VERSION:
        raise SystemExit(f"ERROR: unsupported assembly shared index: {index_path}")
    spec_root = _required_string(recorded.get("specRoot"), field="specRoot", source=index_path)
    current = build_index(Path(spec_root))
    if recorded != current:
        raise SystemExit(
            "ERROR: assembly shared-component index is stale or contract files drifted; "
            "regenerate the worker prompt"
        )
    return current


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--spec-root", required=True)
    prepare.add_argument("--out", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--index", required=True)
    args = parser.parse_args()

    if args.command == "prepare":
        index = build_index(Path(args.spec_root))
        write_index(index, Path(args.out))
    else:
        index = check_index(Path(args.index))
    print(json.dumps(index["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
