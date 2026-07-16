#!/usr/bin/env python3
"""Validate iFF multi-viewport uniform fit-width runtime evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def responsive_failures(contract_path: Path, report_path: Path, bbox_tol: float = 2.0) -> list[str]:
    failures: list[str] = []
    if not contract_path.is_file():
        return [f"responsive contract missing: {contract_path}"]
    if not report_path.is_file():
        return [f"responsive report missing: {report_path}"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if contract.get("policy") != "logical_375_constraints":
        failures.append(f"unsupported responsive policy: {contract.get('policy')!r}")
    if contract.get("runtimeScaleAllowed") is not False:
        failures.append("runtimeScaleAllowed must be false")
    if float(contract.get("logicalDesignWidth", 0)) != 375.0:
        failures.append("logicalDesignWidth must be 375")
    if contract.get("safeAreaPolicy") not in {"edge_to_edge", "inset_content"}:
        failures.append("safeAreaPolicy must be explicit")
    expected = {
        (float(item["width"]), float(item["height"]))
        for item in (contract.get("viewports") or [])
        if isinstance(item, dict) and "width" in item and "height" in item
    }
    cases = report.get("cases") or []
    observed = {
        (float(item["width"]), float(item["height"]))
        for item in cases
        if isinstance(item, dict) and "width" in item and "height" in item
    }
    if len(expected) < 3:
        failures.append("responsive contract must contain at least 3 target viewports")
    if observed != expected:
        failures.append(f"responsive viewport evidence mismatch: expected={sorted(expected)} observed={sorted(observed)}")
    for item in cases:
        viewport = f"{item.get('width')}x{item.get('height')}"
        if float(item.get("runtimeScale", 0)) != 1.0:
            failures.append(f"{viewport}: runtimeScale must remain 1")
        if item.get("missing"):
            failures.append(f"{viewport}: missing nodes {item.get('missing')}")
        if item.get("layoutErrors"):
            failures.append(f"{viewport}: layout errors {item.get('layoutErrors')}")
        delta = float(item.get("maxLogicalBboxDelta", float("inf")))
        if delta > bbox_tol:
            failures.append(
                f"{viewport}: node={item.get('worstNode')} axis={item.get('worstAxis')} "
                f"expected={item.get('worstExpected')} observed={item.get('worstObserved')} "
                f"logical bbox delta {delta} > {bbox_tol}"
            )
        if item.get("pass") is not True:
            failures.append(f"{viewport}: pass is not true")
    if report.get("pass") is not True:
        failures.append("responsive report pass is not true")
    return list(dict.fromkeys(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--bbox-tol", type=float, default=2.0)
    args = parser.parse_args()
    failures = responsive_failures(args.contract, args.report, args.bbox_tol)
    if failures:
        print(f"FAIL responsive layout ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("ok responsive layout: all target viewports satisfy 375 logical constraint geometry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
