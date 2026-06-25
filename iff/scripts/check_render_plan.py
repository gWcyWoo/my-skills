#!/usr/bin/env python3
"""Fail if render_plan allows design-screenshot masquerading."""

from __future__ import annotations

import argparse

from common import load_json


FORBIDDEN = {"full_artboard_background", "reference_background", "generated_from_reference"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("render_plan")
    args = parser.parse_args()

    plan = load_json(args.render_plan)
    errors = []
    for node_id, item in (plan.get("nodes") or {}).items():
        impl = item.get("implementation")
        if impl in FORBIDDEN:
            errors.append(f"{node_id}: forbidden implementation {impl}")
        if item.get("asset") and "reference" in str(item["asset"]).lower():
            errors.append(f"{node_id}: asset path looks like reference image")
        if not item.get("widgetTraceRequired"):
            errors.append(f"{node_id}: widget trace is not required")
    if errors:
        raise SystemExit("ERROR: render plan invalid:\n" + "\n".join(errors))
    print("ok render plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
