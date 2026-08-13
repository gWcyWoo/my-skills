#!/usr/bin/env python3
"""Normalize Apifox OpenAPI root+ref resources into the compact iFF API contract.

The worker saves read_project_oas as oas.json and read_project_oas_ref_resources as
oas_ref_resources.json. This script resolves those machine-consumed documents, then flattens the OAS
into the endpoint/field/type/enum shape
that make_visual_fixture / make_interaction_tests_plan / bind_data_slots / check_api_integration
read. Replacing the previously DERIVED contract with the real one is what makes the node->field
binding rest on the actual schema instead of inference.

If oas.json is absent, or an external ref lacks a resource-map entry, this fails loudly. (The
downstream scripts still degrade gracefully on a missing contract, but a real run must not silently
ship a guessed contract.)
"""
from __future__ import annotations

import argparse
import json
import posixpath
import sys
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse


class OasRefError(ValueError):
    """An OAS reference cannot be resolved deterministically."""


def load_json_value(path: Path, label: str) -> object:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, str):
            value = json.loads(value)
        return value
    except (OSError, json.JSONDecodeError) as exc:
        raise OasRefError(f"invalid {label} JSON at {path}: {exc}") from exc


class RefResolver:
    ROOT = "<root>"

    def __init__(self, root: dict, resources: dict) -> None:
        self.documents: dict[str, object] = {self.ROOT: root}
        self.cache: dict[str, object] = {}
        for raw_key, value in resources.items():
            if not isinstance(raw_key, str):
                raise OasRefError("ref resource keys must be strings")
            document_ref, fragment = urldefrag(raw_key)
            if fragment:
                raise OasRefError(f"ref resource key must not contain a fragment: {raw_key}")
            key = self._document_key(document_ref, self.ROOT)
            if key in self.documents:
                raise OasRefError(f"duplicate ref resource: {key}")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise OasRefError(f"invalid ref resource JSON: {raw_key}: {exc}") from exc
            if not isinstance(value, (dict, list)):
                raise OasRefError(f"ref resource must be a JSON object or array: {raw_key}")
            self.documents[key] = value
        self.bundle_root = self._make_bundle_root(root)

    def _make_bundle_root(self, root: dict) -> dict:
        bundle_root = dict(root)
        for key, document in self.documents.items():
            if key == self.ROOT or not key.startswith("/"):
                continue
            parts = key.strip("/").split("/")
            if len(parts) < 2 or parts[-1] != "index.json":
                continue
            cursor = bundle_root
            for segment in parts[:-2]:
                existing = cursor.get(segment)
                branch = dict(existing) if isinstance(existing, dict) else {}
                cursor[segment] = branch
                cursor = branch
            cursor[parts[-2]] = document
        return bundle_root

    def resolve(self, value: object, current_document: str = ROOT) -> object:
        return self._resolve_node(value, current_document, ())

    def _resolve_node(self, value: object, current_document: str, stack: tuple[str, ...]) -> object:
        if isinstance(value, list):
            return [self._resolve_node(item, current_document, stack) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" not in value:
            return {
                key: self._resolve_node(item, current_document, stack)
                for key, item in value.items()
            }

        resolved = self._resolve_ref(value["$ref"], current_document, stack)
        siblings = {key: item for key, item in value.items() if key != "$ref"}
        if not siblings:
            return resolved
        if not isinstance(resolved, dict):
            raise OasRefError(f"$ref siblings require an object target: {value['$ref']}")
        return {
            **resolved,
            **{
                key: self._resolve_node(item, current_document, stack)
                for key, item in siblings.items()
            },
        }

    def _resolve_ref(self, ref: object, current_document: str, stack: tuple[str, ...]) -> object:
        if not isinstance(ref, str) or not ref:
            raise OasRefError("$ref must be a non-empty string")
        document_ref, fragment = urldefrag(ref)
        try:
            fragment = unquote(fragment, encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise OasRefError(f"invalid UTF-8 in URI fragment: {ref}") from exc
        target_document = (
            self._document_key(document_ref, current_document) if document_ref else current_document
        )
        if target_document not in self.documents:
            raise OasRefError(f"missing external ref resource: {target_document}")
        pointer_document = (
            self.bundle_root if target_document == self.ROOT else self.documents[target_document]
        )
        try:
            target = self._json_pointer(pointer_document, fragment, target_document)
        except OasRefError:
            if document_ref or not fragment or target_document == self.ROOT:
                raise
            target_document = self.ROOT
            target = self._json_pointer(self.bundle_root, fragment, target_document)
        identity = self._identity(target_document, fragment)
        if identity in stack:
            cycle = stack[stack.index(identity) :] + (identity,)
            raise OasRefError(f"reference cycle: {' -> '.join(cycle)}")
        if identity in self.cache:
            return self.cache[identity]
        resolved = self._resolve_node(target, target_document, stack + (identity,))
        self.cache[identity] = resolved
        return resolved

    @classmethod
    def _document_key(cls, document_ref: str, current_document: str) -> str:
        if not document_ref:
            return current_document
        if urlparse(document_ref).scheme:
            return document_ref
        if current_document != cls.ROOT and urlparse(current_document).scheme:
            return urljoin(current_document, document_ref)
        if document_ref.startswith("/"):
            return posixpath.normpath(document_ref)
        base = "/" if current_document == cls.ROOT else posixpath.dirname(current_document)
        return posixpath.normpath(posixpath.join(base, document_ref))

    @classmethod
    def _identity(cls, document: str, fragment: str) -> str:
        if document == cls.ROOT:
            return f"#{fragment}" if fragment else cls.ROOT
        return f"{document}#{fragment}" if fragment else document

    @staticmethod
    def _json_pointer(document: object, fragment: str, document_key: str) -> object:
        if not fragment:
            return document
        if not fragment.startswith("/"):
            raise OasRefError(f"unsupported JSON pointer in {document_key}: #{fragment}")
        current = document
        for raw_token in fragment[1:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            try:
                if isinstance(current, list):
                    current = current[int(token)]
                elif isinstance(current, dict):
                    current = current[token]
                else:
                    raise KeyError(token)
            except (KeyError, IndexError, ValueError) as exc:
                raise OasRefError(
                    f"missing JSON pointer #{fragment} in ref resource: {document_key}"
                ) from exc
        return current


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
    ap.add_argument(
        "--ref-resources",
        help="JSON map saved from Apifox MCP read_project_oas_ref_resources",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    oas_path = Path(args.oas)
    if not oas_path.is_file():
        print(f"FAIL: {oas_path} not found. Call the Apifox MCP tool "
              "mcp__apifox-new-mcp__read_project_oas and save its result to oas.json first.")
        return 1

    try:
        oas = load_json_value(oas_path, "OAS root")
        if not isinstance(oas, dict):
            raise OasRefError("OAS root must be a JSON object")
        resources: object = {}
        if args.ref_resources:
            resources = load_json_value(Path(args.ref_resources), "OAS ref resources")
        if not isinstance(resources, dict):
            raise OasRefError("OAS ref resources must be a JSON object mapping refs to documents")
        resolver = RefResolver(oas, resources)
    except OasRefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    defs = (oas.get("components") or {}).get("schemas") or oas.get("definitions") or {}
    endpoints = {}
    try:
        for path, methods in (oas.get("paths") or {}).items():
            methods = resolver.resolve(methods)
            if not isinstance(methods, dict):
                raise OasRefError(f"resolved path item must be a JSON object: {path}")
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
    except OasRefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    contract = {
        "source": "normalize_api_contract.py (real Apifox OAS)",
        "contractScope": "project",
        "endpointCount": len(endpoints),
        "operationCount": sum(len(methods) for methods in endpoints.values()),
        "endpoints": endpoints,
    }
    Path(args.out).write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok api_contract endpoints={len(endpoints)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
