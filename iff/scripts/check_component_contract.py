#!/usr/bin/env python3
"""Validate the public contract of one shared visual component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


RAW_VISUAL_INPUT_SUFFIXES = {
    "alignment",
    "border",
    "color",
    "decoration",
    "font",
    "fontsize",
    "fontstyle",
    "fontweight",
    "gap",
    "gradient",
    "height",
    "lineheight",
    "margin",
    "opacity",
    "padding",
    "radius",
    "shadow",
    "spacing",
    "style",
    "textstyle",
    "width",
}

RAW_VISUAL_DART_TYPES = (
    "Alignment",
    "AlignmentGeometry",
    "Border",
    "BorderRadius",
    "BoxDecoration",
    "BoxShadow",
    "Color",
    "Decoration",
    "EdgeInsets",
    "EdgeInsetsGeometry",
    "Gradient",
    "Shadow",
    "TextStyle",
)


def input_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return ""


def is_raw_visual_input(name: str) -> bool:
    normalized = "".join(char.lower() for char in name if char.isalnum())
    return any(normalized.endswith(suffix) for suffix in RAW_VISUAL_INPUT_SUFFIXES)


def validate_contract(contract: dict, source_text: str | None = None) -> list[str]:
    failures: list[str] = []
    if not isinstance(contract.get("familyId"), str) or not contract.get("familyId"):
        failures.append("familyId must be a non-empty string")
    if not isinstance(contract.get("invariants"), dict) or not contract.get("invariants"):
        failures.append("invariants must be a non-empty object")
    if not isinstance(contract.get("variants"), list) or not contract.get("variants"):
        failures.append("variants must be a non-empty list")
    for field in ("businessInputs", "uiStateInputs", "events", "controlledSlots"):
        if not isinstance(contract.get(field), list):
            failures.append(f"{field} must be a list")

    for value in contract.get("businessInputs") or []:
        name = input_name(value)
        if is_raw_visual_input(name):
            failures.append(f"raw visual override is forbidden: {name}")

    for slot in contract.get("controlledSlots") or []:
        if not isinstance(slot, dict):
            failures.append(f"controlled slot must be an object: {slot}")
            continue
        name = str(slot.get("name") or "<unnamed>")
        if not isinstance(slot.get("allowedRoles"), list) or not slot.get("allowedRoles"):
            failures.append(f"controlled slot {name} must declare allowedRoles")

    if source_text is not None:
        source = source_text.lower()
        for dependency in contract.get("forbiddenDependencies") or []:
            if str(dependency).lower() in source:
                failures.append(f"forbidden dependency in source: {dependency}")
        type_pattern = "|".join(re.escape(value) for value in RAW_VISUAL_DART_TYPES)
        for match in re.finditer(
            rf"\b({type_pattern})\??\s+([A-Za-z]\w*)\s*(?:[;=,)])",
            source_text,
        ):
            dart_type, name = match.groups()
            if not name.startswith("_"):
                failures.append(f"raw visual override type is forbidden: {dart_type} {name}")
        source_without_comments = re.sub(
            r"//[^\n]*|/\*.*?\*/",
            " ",
            source_text,
            flags=re.DOTALL,
        )
        identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", source_without_comments))
        declared_inputs = {
            "businessInputs": [input_name(value) for value in contract.get("businessInputs") or []],
            "uiStateInputs": [input_name(value) for value in contract.get("uiStateInputs") or []],
            "events": [input_name(value) for value in contract.get("events") or []],
            "controlledSlots": [
                input_name(value) for value in contract.get("controlledSlots") or []
            ],
        }
        for field, names in declared_inputs.items():
            missing = sorted(name for name in names if name and name not in identifiers)
            if missing:
                failures.append(f"declared {field} missing from source: {', '.join(missing)}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--source")
    args = parser.parse_args()

    contract_path = Path(args.contract)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    source_text = Path(args.source).read_text(encoding="utf-8") if args.source else None
    failures = validate_contract(contract, source_text)

    if failures:
        print(f"FAIL component contract {contract.get('familyId') or contract_path.stem}:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"ok component contract: {contract.get('familyId') or contract_path.stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
