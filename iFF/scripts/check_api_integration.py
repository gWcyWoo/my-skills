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
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-contract", required=True)
    ap.add_argument("--lib-root", default="lib")
    ap.add_argument("--out")
    args = ap.parse_args()

    contract_path = Path(args.api_contract)
    if not contract_path.is_file():
        print(f"FAIL api integration: {contract_path} not found (run normalize_api_contract.py first)")
        return 1
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    endpoints = list((contract.get("endpoints") or {}).keys())
    if not endpoints:
        print("FAIL api integration: contract has no endpoints")
        return 1

    lib_root = Path(args.lib_root)
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in lib_root.rglob("*.dart"))

    missing = [ep for ep in endpoints if ep not in blob]
    integrated = [ep for ep in endpoints if ep in blob]

    report = {
        "endpointCount": len(endpoints),
        "integrated": integrated,
        "missing": missing,
        "ok": not missing,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if missing:
        print(f"FAIL api integration: {len(missing)}/{len(endpoints)} endpoint(s) have no repository "
              f"call site in {lib_root}/:")
        for ep in missing:
            print(f"  - {ep}")
        return 1
    print(f"ok api integration: all {len(endpoints)} endpoint(s) referenced in {lib_root}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
