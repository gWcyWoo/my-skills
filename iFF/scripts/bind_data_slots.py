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


def flatten_fields(contract: dict) -> list:
    """Collect field names from either the normalized OAS shape (endpoint->method->responseFields)
    or the derived shape (endpoint->{fields}); tolerant of string leaves."""
    names = []

    def walk(fields, prefix=""):
        if not isinstance(fields, dict):
            return
        for n, spec in fields.items():
            names.append(prefix + n)
            if isinstance(spec, dict) and isinstance(spec.get("fields"), dict):
                walk(spec["fields"], prefix + n + ".")

    for _path, methods in (contract.get("endpoints") or {}).items():
        if not isinstance(methods, dict):
            continue
        for _m, op in methods.items():
            if isinstance(op, dict) and "responseFields" in op:
                walk(op.get("responseFields"))
        if isinstance(methods.get("fields"), dict):  # derived shape
            walk(methods["fields"])
    return sorted(set(names))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--api-contract", required=True)
    ap.add_argument("--interaction-contract")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    contract = {}
    if Path(args.api_contract).is_file():
        try:
            contract = json.loads(Path(args.api_contract).read_text(encoding="utf-8"))
        except ValueError:
            contract = {}
    fields = flatten_fields(contract)

    bindings = []
    needs_model = []
    for comp in manifest.get("components", []):
        for slot in comp.get("dynamicSlots", []):
            text = (slot.get("text") or "").strip()
            match = None
            for kind, text_re, field_re, transform in PATTERNS:
                if text_re.search(text):
                    candidates = [f for f in fields if field_re.search(f)]
                    match = {
                        "slotKind": kind,
                        "transform": transform,
                        "candidateFields": candidates,
                        "field": candidates[0] if len(candidates) == 1 else None,
                        "confidence": "high" if len(candidates) == 1 else ("medium" if candidates else "low"),
                    }
                    break
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

    out = {
        "source": "bind_data_slots.py",
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
