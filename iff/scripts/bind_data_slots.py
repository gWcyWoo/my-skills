#!/usr/bin/env python3
"""Join component dynamic slots to real API fields + transform rules (the node<->field table).

Input: component_manifest.json (dynamic_text_slot candidates) + api_contract.json (real OAS fields).
Output: data_slot_bindings.json — for each dynamic slot, a binding: {field, transform, confidence}.

Deterministic part (this script): propose candidate bindings by content pattern (₦/amount, date,
N-days, percent) matched against field names/types in the contract, with a confidence score.
Semantic part (model, per the agreed hybrid): the worker must CONFIRM or correct each binding using
the interaction spec — e.g. that the withdraw card amount is level_money-with-max_money-fallback
(INT-010), not a plain field. Unresolved/low-confidence slots are listed for the model under
`needsModelBinding`; a slot must end up with a confirmed field+transform before the api gate passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


PATTERNS = [
    ("amount", re.compile(r"₦|\$|\bmoney\b|\bamount\b", re.I),
     re.compile(r"money|amount|repayable|level", re.I), "formatNaira"),
    ("date", re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}|\bdate\b", re.I),
     re.compile(r"date|repay", re.I), "formatDate"),
    ("days", re.compile(r"\d+\s*days?\b", re.I),
     re.compile(r"day|overdue|reapply", re.I), "asDays"),
    ("percent", re.compile(r"\d+(\.\d+)?\s*%", re.I),
     re.compile(r"rate|interest", re.I), "asPercent"),
]

TRANSFORM_TYPES = {
    "asText": {"string", "integer", "number", "boolean"},
    "formatNaira": {"integer", "number"},
    "formatDate": {"string"},
    "asDays": {"integer", "number"},
    "asPercent": {"integer", "number"},
}


def flatten_fields(contract: dict) -> list:
    """Collect response fields without losing their operation and JSON-path identity."""
    fields = []

    def walk_legacy(values, endpoint, method, status="200", prefix=""):
        if not isinstance(values, dict):
            return
        for name, spec in values.items():
            path = prefix + name
            fields.append({
                "endpoint": endpoint,
                "method": method,
                "status": status,
                "jsonPath": "$." + path,
                "type": spec.get("type", "unknown") if isinstance(spec, dict) else "unknown",
                "format": spec.get("format") if isinstance(spec, dict) else None,
                "required": spec.get("required", False) if isinstance(spec, dict) else False,
                "nullable": spec.get("nullable", False) if isinstance(spec, dict) else False,
                "enum": spec.get("enum") if isinstance(spec, dict) else None,
            })
            if isinstance(spec, dict) and isinstance(spec.get("fields"), dict):
                walk_legacy(spec["fields"], endpoint, method, status, path + ".")

    for endpoint, methods in (contract.get("endpoints") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            responses = op.get("responses") or {}
            for status, response in responses.items():
                response = response or {}

                def append_fields(values, variant_kind=None, variant_index=None):
                    for json_path, spec in (values or {}).items():
                        if not isinstance(spec, dict):
                            continue
                        field = {
                            "endpoint": endpoint,
                            "method": method,
                            "status": str(status),
                            "jsonPath": json_path,
                            "type": spec.get("type", "unknown"),
                            "format": spec.get("format"),
                            "required": bool(spec.get("required", False)),
                            "nullable": bool(spec.get("nullable", False)),
                            "enum": spec.get("enum"),
                        }
                        if variant_kind is not None:
                            field["variantKind"] = variant_kind
                            field["variantIndex"] = variant_index
                        fields.append(field)

                append_fields(response.get("fields"))
                for variant in response.get("variants") or []:
                    append_fields(
                        variant.get("fields"),
                        response.get("schemaKind"),
                        variant.get("index"),
                    )
            if not responses and "responseFields" in op:
                walk_legacy(op.get("responseFields"), endpoint, method)
        if isinstance(methods.get("fields"), dict):  # derived shape
            walk_legacy(methods["fields"], endpoint, "UNKNOWN")
    unique = {json.dumps(field, ensure_ascii=False, sort_keys=True): field for field in fields}
    return sorted(
        unique.values(),
        key=lambda field: (
            field["endpoint"], field["method"], field["status"], field["jsonPath"]
        ),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--api-contract", required=True)
    ap.add_argument("--interaction-contract")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if not Path(args.api_contract).is_file():
        raise SystemExit(f"ERROR: api contract not found: {args.api_contract}")
    contract = {}
    try:
        contract = json.loads(Path(args.api_contract).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"ERROR: invalid api contract: {exc}") from exc
    fields = flatten_fields(contract)

    bindings = []
    needs_model = []
    for comp in manifest.get("components", []):
        for slot in comp.get("dynamicSlots", []):
            text = (slot.get("text") or "").strip()
            match = None
            for kind, text_re, field_re, transform in PATTERNS:
                if text_re.search(text):
                    candidates = [f for f in fields if field_re.search(f["jsonPath"])]
                    compatible = [
                        field for field in candidates
                        if field["type"] in TRANSFORM_TYPES[transform]
                    ]
                    match = {
                        "slotKind": kind,
                        "transform": transform,
                        "candidateFields": candidates,
                        "compatibleCandidateFields": compatible,
                        "field": compatible[0] if len(compatible) == 1 else None,
                        "confidence": "high" if len(compatible) == 1 else (
                            "medium" if compatible else "low"
                        ),
                    }
                    break
            if match is None:
                candidates = [
                    field for field in fields if field["type"] in TRANSFORM_TYPES["asText"]
                ]
                match = {
                    "slotKind": "text",
                    "transform": "asText",
                    "candidateFields": candidates,
                    "compatibleCandidateFields": candidates,
                    "field": None,
                    "confidence": "low",
                }
            entry = {
                "component": comp.get("name"),
                "variantIndex": comp.get("variantIndex"),
                "node": slot.get("node"),
                "designText": text,
                "binding": match,
                "confirmedByModel": False,
            }
            bindings.append(entry)
            if not match or match.get("confidence") != "high":
                needs_model.append({"node": slot.get("node"), "designText": text,
                                    "reason": "no contract" if not fields else "ambiguous/no field match"})

    inputs = {
        "component_manifest.json": hashlib.sha256(
            Path(args.manifest).read_bytes()
        ).hexdigest(),
        "api_contract.json": hashlib.sha256(
            Path(args.api_contract).read_bytes()
        ).hexdigest(),
    }
    if args.interaction_contract:
        interaction_path = Path(args.interaction_contract)
        if not interaction_path.is_file():
            raise SystemExit(f"ERROR: interaction contract not found: {interaction_path}")
        inputs["interaction_contract.json"] = hashlib.sha256(
            interaction_path.read_bytes()
        ).hexdigest()

    out = {
        "source": "bind_data_slots.py",
        "inputs": inputs,
        "hasRealContract": bool(fields),
        "slotCount": len(bindings),
        "highConfidence": sum(1 for b in bindings if b["binding"] and b["binding"]["confidence"] == "high"),
        "bindings": bindings,
        "needsModelBinding": needs_model,
        "note": "Model must confirm every binding against the interaction spec (e.g. INT-010 "
                "level_money->max_money fallback) and set confirmedByModel=true before the api gate.",
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ok data slot bindings slots={len(bindings)} high_conf={out['highConfidence']} "
          f"needs_model={len(needs_model)} real_contract={bool(fields)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
