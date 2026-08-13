#!/usr/bin/env python3
"""Validate that one board's visual gate is passing and bound to current inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from make_visual_gate_report import classify_hard_failures


REQUIRED_INPUTS = {
    "reference.png",
    "actual.png",
    "render_fidelity_report.json",
    "diff_report.json",
    "visual_manifest.json",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_board(spec_dir: Path, report_name: str = "visual_gate_report.json") -> list[str]:
    report_path = spec_dir / report_name
    if not report_path.is_file():
        return [f"report missing: {report_path.name}"]

    report = json.loads(report_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if report.get("ok") is not True:
        failures.append("visual gate report is not ok")
    for issue in report.get("hardFailures") or []:
        failures.append(
            f"{issue.get('category') or 'unknown'} hard failure at "
            f"{issue.get('node') or '(unscoped)'}: {issue.get('reason') or 'visual mismatch'}"
        )

    inputs = report.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        failures.append("visual gate report has no input fingerprints")
    else:
        for relative in sorted(REQUIRED_INPUTS - set(inputs)):
            failures.append(f"input fingerprint missing: {relative}")
        for relative, expected in sorted(inputs.items()):
            path = (spec_dir / relative).resolve()
            if spec_dir not in path.parents:
                failures.append(f"input escapes spec dir: {relative}")
            elif not path.is_file():
                failures.append(f"input missing: {relative}")
            elif sha256(path) != expected:
                failures.append(f"stale input {relative}")
    if (
        isinstance(inputs, dict)
        and REQUIRED_INPUTS <= set(inputs)
        and all((spec_dir / name).is_file() for name in REQUIRED_INPUTS)
    ):
        diff = json.loads((spec_dir / "diff_report.json").read_text(encoding="utf-8"))
        fidelity = json.loads(
            (spec_dir / "render_fidelity_report.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (spec_dir / "visual_manifest.json").read_text(encoding="utf-8")
        )
        for issue in classify_hard_failures(spec_dir, diff, fidelity, manifest):
            failures.append(
                f"current evidence has {issue.get('category') or 'unknown'} hard failure: "
                f"{issue.get('reason') or 'visual mismatch'}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--report", default="visual_gate_report.json")
    args = parser.parse_args()

    spec_dir = Path(args.spec_dir).expanduser().resolve()
    failures = validate_board(spec_dir, args.report)

    if failures:
        print(f"FAIL visual board {spec_dir.name} ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"ok visual board: {spec_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
