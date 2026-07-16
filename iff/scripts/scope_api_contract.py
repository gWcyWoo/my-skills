#!/usr/bin/env python3
"""Validate a model-selected feature endpoint subset against the full normalized OAS contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


class ApiScopeError(ValueError):
    pass


def load_object(path: Path, label: str) -> dict:
    if not path.is_file():
        raise ApiScopeError(f"{label} missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiScopeError(f"invalid {label} JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ApiScopeError(f"{label} must be a JSON object: {path}")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_operations(contract: dict) -> dict[tuple[str, str], dict]:
    if contract.get("contractScope") != "project":
        raise ApiScopeError("project API contract must declare contractScope=project")
    endpoints = contract.get("endpoints")
    if not isinstance(endpoints, dict):
        raise ApiScopeError("project API contract endpoints must be an object")
    operations: dict[tuple[str, str], dict] = {}
    for path, methods in endpoints.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(methods, dict):
            raise ApiScopeError(f"invalid normalized endpoint path: {path!r}")
        for method, operation in methods.items():
            if not isinstance(method, str) or not method or not isinstance(operation, dict):
                raise ApiScopeError(f"invalid normalized operation: {method!r} {path}")
            operations[(path, method.upper())] = operation
    return operations


def interaction_rule_ids(contract: dict) -> set[str]:
    rules = contract.get("rules") or []
    if not isinstance(rules, list):
        raise ApiScopeError("interaction contract rules must be an array")
    return {
        rule["id"]
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str) and rule["id"]
    }


def build_feature_contract(
    project_contract: dict,
    row: dict,
    interaction_contract: dict,
    selection: dict,
    *,
    project_sha256: str,
    row_sha256: str,
    interaction_sha256: str,
    selection_sha256: str,
) -> dict:
    operations = project_operations(project_contract)
    row_api = row.get("api", "")
    if row_api is None:
        row_api = ""
    if not isinstance(row_api, str):
        raise ApiScopeError("row api must be a string")
    if selection.get("contractScope") != "feature-selection":
        raise ApiScopeError("selection must declare contractScope=feature-selection")
    api_required = selection.get("apiRequired")
    if not isinstance(api_required, bool):
        raise ApiScopeError("selection apiRequired must be a boolean")

    basis = selection.get("basis")
    if not isinstance(basis, dict) or basis.get("rowApi") != row_api:
        raise ApiScopeError("selection basis.rowApi must exactly match the claimed row api")
    selected_rule_ids = basis.get("interactionRuleIds")
    if not isinstance(selected_rule_ids, list) or any(
        not isinstance(rule_id, str) or not rule_id for rule_id in selected_rule_ids
    ):
        raise ApiScopeError("selection basis.interactionRuleIds must be an array of rule ids")
    if len(selected_rule_ids) != len(set(selected_rule_ids)):
        raise ApiScopeError("selection basis.interactionRuleIds contains duplicates")
    unknown_rules = sorted(set(selected_rule_ids) - interaction_rule_ids(interaction_contract))
    if unknown_rules:
        raise ApiScopeError(f"selection references unknown interaction rule ids: {unknown_rules}")

    selected = selection.get("selectedEndpoints")
    if not isinstance(selected, list):
        raise ApiScopeError("selection selectedEndpoints must be an array")
    selected_keys: list[tuple[str, str]] = []
    for item in selected:
        if not isinstance(item, dict) or set(item) != {"path", "method"}:
            raise ApiScopeError("each selected endpoint must contain exactly path and method")
        path = item.get("path")
        method = item.get("method")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ApiScopeError(f"invalid selected endpoint path: {path!r}")
        if not isinstance(method, str) or not method:
            raise ApiScopeError(f"invalid selected endpoint method for {path}")
        selected_keys.append((path, method.upper()))
    if len(selected_keys) != len(set(selected_keys)):
        raise ApiScopeError("selectedEndpoints contains duplicate operations")
    unknown = sorted(key for key in selected_keys if key not in operations)
    if unknown:
        raise ApiScopeError(
            "selection contains unknown OAS operations: "
            + ", ".join(f"{method} {path}" for path, method in unknown)
        )

    row_requires_api = bool(row_api.strip())
    if row_requires_api and not api_required:
        raise ApiScopeError("row api is non-empty but selection apiRequired is false")
    if api_required and not selected_keys:
        raise ApiScopeError("API is required but selectedEndpoints is empty")
    if selected_keys and not api_required:
        raise ApiScopeError("selectedEndpoints is non-empty but apiRequired is false")
    if api_required and not row_requires_api and not selected_rule_ids:
        raise ApiScopeError("API selection lacks a row api or interaction-rule basis")

    selected_keys.sort()
    endpoints: dict[str, dict[str, dict]] = {}
    for path, method in selected_keys:
        endpoints.setdefault(path, {})[method] = operations[(path, method)]
    selected_endpoints = [{"path": path, "method": method} for path, method in selected_keys]
    return {
        "source": "scope_api_contract.py (validated feature subset)",
        "contractScope": "feature",
        "apiRequired": api_required,
        "endpointCount": len(endpoints),
        "operationCount": len(selected_keys),
        "projectEndpointCount": len(project_contract.get("endpoints") or {}),
        "projectOperationCount": len(operations),
        "selectedEndpoints": selected_endpoints,
        "endpoints": endpoints,
        "selectionBasis": {
            "rowApi": row_api,
            "interactionRuleIds": sorted(selected_rule_ids),
        },
        "provenance": {
            "projectContractSha256": project_sha256,
            "rowSha256": row_sha256,
            "interactionContractSha256": interaction_sha256,
            "selectionSha256": selection_sha256,
        },
    }


def feature_operations(contract: dict) -> list[tuple[str, str]]:
    if contract.get("contractScope") != "feature":
        raise ApiScopeError("API integration requires contractScope=feature")
    api_required = contract.get("apiRequired")
    if not isinstance(api_required, bool):
        raise ApiScopeError("feature API contract apiRequired must be a boolean")
    endpoints = contract.get("endpoints")
    if not isinstance(endpoints, dict):
        raise ApiScopeError("feature API contract endpoints must be an object")
    operations: list[tuple[str, str]] = []
    for path, methods in endpoints.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(methods, dict):
            raise ApiScopeError(f"invalid feature endpoint path: {path!r}")
        for method, operation in methods.items():
            if not isinstance(method, str) or not method or not isinstance(operation, dict):
                raise ApiScopeError(f"invalid feature operation: {method!r} {path}")
            operations.append((path, method.upper()))
    operations.sort()
    selected = contract.get("selectedEndpoints")
    expected_selected = [{"path": path, "method": method} for path, method in operations]
    if selected != expected_selected:
        raise ApiScopeError("selectedEndpoints does not exactly match scoped endpoint operations")
    if contract.get("endpointCount") != len(endpoints):
        raise ApiScopeError("feature API contract endpointCount is inconsistent")
    if contract.get("operationCount") != len(operations):
        raise ApiScopeError("feature API contract operationCount is inconsistent")
    if api_required and not operations:
        raise ApiScopeError("API is required but the feature contract has no selected endpoints")
    if not api_required and operations:
        raise ApiScopeError("API is not required but the feature contract selects endpoints")
    provenance = contract.get("provenance")
    required_hashes = {
        "projectContractSha256",
        "rowSha256",
        "interactionContractSha256",
        "selectionSha256",
    }
    if not isinstance(provenance, dict) or any(
        not isinstance(provenance.get(name), str) or len(provenance[name]) != 64
        for name in required_hashes
    ):
        raise ApiScopeError("feature API contract lacks complete source-hash provenance")
    return operations


def build_from_files(project: Path, row: Path, interaction: Path, selection: Path) -> dict:
    return build_feature_contract(
        load_object(project, "project API contract"),
        load_object(row, "row"),
        load_object(interaction, "interaction contract"),
        load_object(selection, "endpoint selection"),
        project_sha256=file_sha256(project),
        row_sha256=file_sha256(row),
        interaction_sha256=file_sha256(interaction),
        selection_sha256=file_sha256(selection),
    )


def validate_feature_contract_files(
    project: Path,
    row: Path,
    interaction: Path,
    selection: Path,
    feature: Path,
) -> dict:
    expected = build_from_files(project, row, interaction, selection)
    actual = load_object(feature, "feature API contract")
    if actual != expected:
        raise ApiScopeError("feature API contract is stale, unscoped, or differs from validated inputs")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-contract", required=True)
    parser.add_argument("--row-json", required=True)
    parser.add_argument("--interaction-contract", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    project = Path(args.project_contract)
    row = Path(args.row_json)
    interaction = Path(args.interaction_contract)
    selection = Path(args.selection)
    out = Path(args.out)
    try:
        contract = build_from_files(project, row, interaction, selection)
    except (ApiScopeError, OSError) as exc:
        print(f"ERROR: feature API contract scope invalid: {exc}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "apiRequired": contract["apiRequired"],
                "projectOperationCount": contract["projectOperationCount"],
                "selectedOperationCount": contract["operationCount"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
