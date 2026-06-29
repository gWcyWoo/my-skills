#!/usr/bin/env python3
"""Normalize a real Apifox/OpenAPI export into the iFF api_contract.json the pipeline consumes.

The worker first pulls the spec via the Apifox MCP tool (mcp__apifox-new-mcp__read_project_oas)
and saves it as oas.json. This script flattens that OAS into the endpoint/field/type/enum shape
that make_visual_fixture / make_interaction_tests_plan / bind_data_slots / check_api_integration
read. Replacing the previously DERIVED contract with the real one is what makes the node->field
binding rest on the actual schema instead of inference.

If oas.json is absent, this fails loudly: the worker must call the Apifox MCP tool first. (The
downstream scripts still degrade gracefully on a missing contract, but a real run must not silently
ship a guessed contract.)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def schema_fields(schema: dict, defs: dict, depth: int = 0) -> dict:
    """Flatten an OpenAPI schema's properties into {field: {type, nullable, enum}}."""
    if depth > 6 or not isinstance(schema, dict):
        return {}
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return schema_fields(defs.get(ref, {}), defs, depth + 1)
    props = schema.get("properties") or {}
    out = {}
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        out[name] = {
            "type": spec.get("type") or ("object" if "properties" in spec or "$ref" in spec else "unknown"),
            "nullable": bool(spec.get("nullable", False)),
            "enum": spec.get("enum"),
        }
        if spec.get("type") == "object" or "properties" in spec or "$ref" in spec:
            nested = schema_fields(spec, defs, depth + 1)
            if nested:
                out[name]["fields"] = nested
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oas", required=True, help="oas.json saved from Apifox MCP read_project_oas")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    oas_path = Path(args.oas)
    if not oas_path.is_file():
        print(f"FAIL: {oas_path} not found. Call the Apifox MCP tool "
              "mcp__apifox-new-mcp__read_project_oas and save its result to oas.json first.")
        return 1

    oas = json.loads(oas_path.read_text(encoding="utf-8"))
    defs = (oas.get("components") or {}).get("schemas") or oas.get("definitions") or {}
    endpoints = {}
    for path, methods in (oas.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            resp = (op.get("responses") or {}).get("200") or {}
            content = (resp.get("content") or {}).get("application/json") or {}
            schema = content.get("schema") or resp.get("schema") or {}
            endpoints.setdefault(path, {})[method.upper()] = {
                "summary": op.get("summary") or op.get("operationId"),
                "responseFields": schema_fields(schema, defs),
            }

    contract = {
        "source": "normalize_api_contract.py (real Apifox OAS)",
        "endpointCount": len(endpoints),
        "endpoints": endpoints,
    }
    Path(args.out).write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok api_contract endpoints={len(endpoints)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
