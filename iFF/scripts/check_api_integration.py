#!/usr/bin/env python3
"""Gate: every contract endpoint must have a real repository call site in lib/ (not just a mock).

Deterministic check: for each endpoint path in api_contract.json, require that some lib/ Dart file
references the path string (the repository that hits it). A contract endpoint with zero lib
references means the API was declared but never integrated — the page cannot actually drive it.

This does not prove the request/response handling is correct (tests do that); it proves each
declared endpoint is wired into the data layer. Pair with check_interaction_wiring (behavior on a
runtime path) and check_fixture_source (mock/real same-source).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def has_call(text: str, method: str, endpoint: str) -> bool:
    endpoint_pattern = re.escape(endpoint)
    endpoint_pattern = re.sub(r"\\\{[^}]+\\\}", r"[^'\"]+", endpoint_pattern)
    return bool(
        re.search(
            rf"\b{re.escape(method.lower())}\s*\([^)]{{0,200}}['\"]{endpoint_pattern}['\"]",
            text,
            re.I | re.S,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-contract", required=True)
    ap.add_argument("--lib-root", default="lib")
    ap.add_argument("--runtime-manifest")
    ap.add_argument("--out")
    args = ap.parse_args()

    contract_path = Path(args.api_contract)
    if not contract_path.is_file():
        print(f"FAIL api integration: {contract_path} not found (run normalize_api_contract.py first)")
        return 1
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    operations = [
        (path, method)
        for path, methods in (contract.get("endpoints") or {}).items()
        for method, operation in (methods or {}).items()
        if isinstance(operation, dict)
    ]
    if not operations:
        print("FAIL api integration: contract has no endpoints")
        return 1

    lib_root = Path(args.lib_root)
    sources = []
    for path in lib_root.rglob("*.dart"):
        lower_name = path.name.lower()
        if "mock" in lower_name or "fixture" in lower_name or path.name.endswith("_test.dart"):
            continue
        sources.append(COMMENTS.sub("", path.read_text(encoding="utf-8", errors="ignore")))
    blob = "\n".join(sources)

    operation_sources = None
    if args.runtime_manifest:
        runtime = json.loads(Path(args.runtime_manifest).read_text(encoding="utf-8"))
        operation_sources = {}
        operations = []
        for operation in runtime.get("operations") or []:
            key = (
                str(operation.get("endpoint") or ""),
                str(operation.get("method") or "").upper(),
            )
            operations.append(key)
            real_path = lib_root.parent / str(operation.get("real") or "")
            operation_sources[key] = (
                COMMENTS.sub("", real_path.read_text(encoding="utf-8", errors="ignore"))
                if real_path.is_file()
                else ""
            )

    def source_for(path: str, method: str) -> str:
        if operation_sources is None:
            return blob
        return operation_sources.get((path, method.upper()), "")

    missing = [
        f"{method} {path}"
        for path, method in operations
        if not has_call(source_for(path, method), method, path)
    ]
    integrated = [
        f"{method} {path}"
        for path, method in operations
        if has_call(source_for(path, method), method, path)
    ]

    report = {
        "operationCount": len(operations),
        "integrated": integrated,
        "missing": missing,
        "ok": not missing,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if missing:
        print(f"FAIL api integration: {len(missing)}/{len(operations)} operation(s) have no repository "
              f"call site in {lib_root}/:")
        for ep in missing:
            print(f"  - {ep}")
        return 1
    print(f"ok api integration: all {len(operations)} operation(s) called in {lib_root}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
