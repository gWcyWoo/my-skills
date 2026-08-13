#!/usr/bin/env python3
"""Validate deterministic DTO/mapper/repository runtime wiring from a project manifest."""
from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from pathlib import Path

from check_interaction_wiring import imports_of, pkg_name


def reachable(start: Path, lib_root: Path, package: str | None) -> set[Path]:
    seen: set[Path] = set()
    queue = deque([start.resolve()])
    while queue:
        current = queue.popleft()
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        queue.extend(imports_of(current, lib_root, package) - seen)
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--runtime-manifest", required=True)
    parser.add_argument("--api-contract")
    parser.add_argument("--bindings")
    parser.add_argument("--out")
    args = parser.parse_args()

    project = Path(args.project_root).resolve()
    manifest_path = Path(args.runtime_manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lib_root = project / "lib"
    package = pkg_name(project / "pubspec.yaml")
    entry = (project / str(manifest.get("entry") or "lib/main.dart")).resolve()
    entry_reachable = reachable(entry, lib_root, package)
    errors = []
    operation_id_counts = Counter(
        str(operation.get("id"))
        for operation in manifest.get("operations") or []
        if operation.get("id")
    )
    for operation_id, count in sorted(operation_id_counts.items()):
        if count > 1:
            errors.append(f"duplicate runtime operation id: {operation_id}")
    contract_endpoints = None
    bound_operations: set[tuple[str, str]] | None = None
    if args.api_contract:
        contract = json.loads(Path(args.api_contract).read_text(encoding="utf-8"))
        contract_endpoints = contract.get("endpoints") or {}
        if args.bindings:
            bindings = json.loads(Path(args.bindings).read_text(encoding="utf-8"))
            expected_operations = {
                (
                    str(field.get("method") or "").upper(),
                    str(field.get("endpoint") or ""),
                )
                for entry in bindings.get("bindings") or []
                for field in [(entry.get("binding") or {}).get("field")]
                if isinstance(field, dict)
            }
            bound_operations = expected_operations
        else:
            expected_operations = {
                (str(method).upper(), str(endpoint))
                for endpoint, methods in contract_endpoints.items()
                for method, value in (methods or {}).items()
                if isinstance(value, dict)
            }
        runtime_counts = Counter(
            (
                str(operation.get("method") or "").upper(),
                str(operation.get("endpoint") or ""),
            )
            for operation in manifest.get("operations") or []
        )
        for method, endpoint in sorted(expected_operations):
            if runtime_counts[(method, endpoint)] == 0:
                errors.append(f"missing runtime operation: {method} {endpoint}")
            elif runtime_counts[(method, endpoint)] > 1:
                errors.append(f"duplicate runtime operation: {method} {endpoint}")
    for operation in manifest.get("operations") or []:
        operation_id = operation.get("id") or "<missing-id>"
        if bound_operations is not None:
            if not isinstance(operation.get("id"), str) or not operation["id"].strip():
                errors.append("missing runtime operation id")
            if not isinstance(operation.get("publicMethod"), str) or not operation[
                "publicMethod"
            ].strip():
                errors.append(f"{operation_id}: missing runtime publicMethod")
        operation_key = (
            str(operation.get("method") or "").upper(),
            str(operation.get("endpoint") or ""),
        )
        if (
            bound_operations is not None
            and operation_key not in bound_operations
            and operation.get("confirmedByModel") is not True
        ):
            errors.append(
                f"{operation_id}: non-slot operation requires model confirmation"
            )
        missing_states = {"loading", "success", "error"} - set(
            operation.get("requiredStates") or []
        )
        if missing_states:
            errors.append(
                f"{operation_id}: missing required states: {', '.join(sorted(missing_states))}"
            )
        endpoint = str(operation.get("endpoint") or "")
        method = str(operation.get("method") or "").upper()
        if contract_endpoints is not None and method not in (
            contract_endpoints.get(endpoint) or {}
        ):
            errors.append(
                f"{operation_id}: {method} {endpoint} absent from current API contract"
            )
        elif contract_endpoints is not None:
            contract_operation = contract_endpoints[endpoint][method]
            field_paths = {
                path
                for response in (contract_operation.get("responses") or {}).values()
                for path in ((response or {}).get("fields") or {})
            }
            if any("[]" in path for path in field_paths) and "empty" not in set(
                operation.get("requiredStates") or []
            ):
                errors.append(f"{operation_id}: array response requires empty state")
        mapper = (project / str(operation.get("mapper") or "")).resolve()
        interface = (project / str(operation.get("interface") or "")).resolve()
        dto = (project / str(operation.get("dto") or "")).resolve()
        for role in ("real", "mock"):
            repository = (project / str(operation.get(role) or "")).resolve()
            repository_reachable = reachable(repository, lib_root, package)
            if mapper not in repository_reachable:
                errors.append(f"{operation_id}: {role} does not use shared mapper")
            if interface not in repository_reachable:
                errors.append(
                    f"{operation_id}: {role} does not use shared repository interface"
                )
            if dto not in repository_reachable:
                errors.append(f"{operation_id}: {role} does not use shared DTO")
        consumer = (project / str(operation.get("consumer") or "")).resolve()
        real = (project / str(operation.get("real") or "")).resolve()
        if consumer not in entry_reachable:
            errors.append(f"{operation_id}: consumer unreachable from entry")
        if real not in entry_reachable:
            errors.append(f"{operation_id}: real repository unreachable from entry")

    report = {"ok": not errors, "failures": errors}
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if errors:
        raise SystemExit("ERROR: invalid data runtime:\n" + "\n".join(f"- {e}" for e in errors))
    print(f"ok data runtime: {len(manifest.get('operations') or [])} operation(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
