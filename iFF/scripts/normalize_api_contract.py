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
import hashlib
import json
from pathlib import Path


HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}


def resolve_local_reference(value: dict, document: dict, depth: int = 0) -> dict:
    if depth > 20:
        raise ValueError("unresolved $ref: reference depth exceeded 20")
    if not isinstance(value, dict) or "$ref" not in value:
        return value
    ref = str(value["$ref"])
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported external $ref: {ref}")
    current: object = document
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise ValueError(f"unresolved $ref: {ref}")
        current = current[token]
    if not isinstance(current, dict):
        raise ValueError(f"unresolved $ref: {ref} is not an object")
    return resolve_local_reference(current, document, depth + 1)


def json_media_type(content: dict) -> str | None:
    if "application/json" in content:
        return "application/json"
    candidates = sorted(
        media_type
        for media_type in content
        if media_type.split(";", 1)[0].strip().lower().endswith("+json")
    )
    if len(candidates) > 1:
        raise ValueError(f"ambiguous JSON media types: {candidates}")
    return candidates[0] if candidates else None


def normalized_type(spec: dict) -> tuple[str, bool]:
    raw_type = spec.get("type")
    nullable = bool(spec.get("nullable", False))
    if isinstance(raw_type, list):
        non_null = [value for value in raw_type if value != "null"]
        if len(non_null) != 1:
            raise ValueError(f"ambiguous schema type union: {raw_type}")
        return str(non_null[0]), True
    if raw_type:
        return str(raw_type), nullable
    return ("object" if spec.get("properties") else "unknown"), nullable


def resolve_schema(schema: dict, defs: dict, depth: int = 0) -> dict:
    if depth > 20:
        raise ValueError("unresolved $ref: reference depth exceeded 20")
    if not isinstance(schema, dict):
        return {}
    ref = schema.get("$ref")
    if not ref:
        return schema
    name = str(ref).split("/")[-1]
    if name not in defs:
        raise ValueError(f"unresolved $ref: {ref}")
    return resolve_schema(defs[name], defs, depth + 1)


def schema_field_paths(
    schema: dict, defs: dict, path: str = "$", path_required: bool = True
) -> dict:
    """Return traceable scalar response fields keyed by their JSON path."""
    resolved = resolve_schema(schema, defs)
    if resolved.get("allOf"):
        fields = {}
        for member in resolved["allOf"]:
            fields.update(schema_field_paths(member, defs, path, path_required))
        return fields
    required = set(resolved.get("required") or [])
    fields = {}
    for name, raw_spec in (resolved.get("properties") or {}).items():
        if not isinstance(raw_spec, dict):
            continue
        spec = resolve_schema(raw_spec, defs)
        field_path = f"{path}.{name}"
        field_type, nullable = normalized_type(spec)
        field_required = path_required and name in required
        if field_type == "array":
            fields.update(
                schema_field_paths(
                    spec.get("items") or {}, defs, field_path + "[]", field_required
                )
            )
        elif field_type == "object" or spec.get("properties"):
            fields.update(schema_field_paths(spec, defs, field_path, field_required))
        else:
            fields[field_path] = {
                "type": field_type,
                "format": spec.get("format"),
                "required": field_required,
                "nullable": nullable,
                "enum": spec.get("enum"),
            }
    return fields


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
    ap.add_argument("--check", action="store_true")
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
        methods = resolve_local_reference(methods, oas)
        path_parameters = methods.get("parameters") or []
        for method, op in methods.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            normalized_responses = {}
            primary_schema = {}
            for status, resp in (op.get("responses") or {}).items():
                if not isinstance(resp, dict):
                    continue
                resp = resolve_local_reference(resp, oas)
                content = resp.get("content") or {}
                media_type = json_media_type(content)
                media = content.get(media_type) if media_type else {}
                schema = (media or {}).get("schema") or resp.get("schema") or {}
                normalized_response = {
                    "mediaType": media_type,
                    "fields": schema_field_paths(schema, defs),
                }
                for variant_kind in ("oneOf", "anyOf"):
                    if schema.get(variant_kind):
                        normalized_response["schemaKind"] = variant_kind
                        normalized_response["variants"] = [
                            {
                                "index": index,
                                "fields": schema_field_paths(variant, defs),
                            }
                            for index, variant in enumerate(schema[variant_kind])
                        ]
                        break
                normalized_responses[str(status)] = normalized_response
                if not primary_schema and str(status).startswith("2"):
                    primary_schema = schema
            parameters = []
            for parameter in [*path_parameters, *(op.get("parameters") or [])]:
                if not isinstance(parameter, dict):
                    continue
                parameter = resolve_local_reference(parameter, oas)
                parameter_schema = parameter.get("schema") or {}
                parameter_type, _ = normalized_type(parameter_schema)
                parameters.append(
                    {
                        "name": parameter.get("name"),
                        "in": parameter.get("in"),
                        "required": bool(parameter.get("required", False)),
                        "type": parameter_type,
                        "format": parameter_schema.get("format"),
                    }
                )
            request_body = resolve_local_reference(op.get("requestBody") or {}, oas)
            request_content = request_body.get("content") or {}
            request_media_type = json_media_type(request_content)
            request_media = request_content.get(request_media_type) if request_media_type else {}
            endpoints.setdefault(path, {})[method.upper()] = {
                "summary": op.get("summary") or op.get("operationId"),
                "parameters": parameters,
                "requestBody": {
                    "required": bool(request_body.get("required", False)),
                    "mediaType": request_media_type,
                    "fields": schema_field_paths((request_media or {}).get("schema") or {}, defs),
                }
                if request_body
                else None,
                "responseFields": schema_fields(primary_schema, defs),
                "responses": normalized_responses,
            }

    contract = {
        "source": "normalize_api_contract.py (real Apifox OAS)",
        "sourceFingerprint": {
            "sha256": hashlib.sha256(oas_path.read_bytes()).hexdigest(),
            "openapi": oas.get("openapi") or oas.get("swagger"),
        },
        "endpointCount": len(endpoints),
        "endpoints": endpoints,
    }
    if args.check:
        out_path = Path(args.out)
        if not out_path.is_file() or json.loads(
            out_path.read_text(encoding="utf-8")
        ) != contract:
            print(f"FAIL api contract is not canonical for current OAS: {args.out}")
            return 1
        print(f"ok canonical api_contract endpoints={len(endpoints)}: {args.out}")
        return 0
    Path(args.out).write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok api_contract endpoints={len(endpoints)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
