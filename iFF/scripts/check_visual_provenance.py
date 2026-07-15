#!/usr/bin/env python3
"""Recompute canonical visual reports from current board inputs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent


def load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return value


def run_script(name: str, arguments: list[object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *(str(value) for value in arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


def validate_visual_provenance(spec_dir: Path) -> list[str]:
    required = (
        "reference.png",
        "actual.png",
        "layout_contract.json",
        "actual_layout_trace.json",
        "merged_expected.json",
        "tokens.json",
        "diff_report.json",
        "render_fidelity_report.json",
    )
    missing = [name for name in required if not (spec_dir / name).is_file()]
    if missing:
        return [f"visual recomputation input missing: {name}" for name in missing]

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp)
        recomputed_diff = temporary / "diff_report.json"
        diff_result = run_script(
            "visual_diff.py",
            [
                "--reference",
                spec_dir / "reference.png",
                "--actual",
                spec_dir / "actual.png",
                "--layout",
                spec_dir / "layout_contract.json",
                "--out",
                recomputed_diff,
                "--heatmap",
                temporary / "diff_heatmap.png",
            ],
        )
        if not recomputed_diff.is_file():
            failures.append(
                "visual_diff.py did not produce a recomputed report: "
                + (diff_result.stderr.strip() or diff_result.stdout.strip())
            )
            return failures
        try:
            if load_object(spec_dir / "diff_report.json") != load_object(recomputed_diff):
                failures.append(
                    "diff_report.json differs from deterministic recomputation"
                )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"diff report unreadable: {error}")
        if diff_result.returncode != 0:
            failures.append("visual_diff.py deterministic recomputation is not passing")

        recomputed_fidelity = temporary / "render_fidelity_report.json"
        fidelity_result = run_script(
            "check_render_fidelity.py",
            [
                "--trace",
                spec_dir / "actual_layout_trace.json",
                "--expected",
                spec_dir / "merged_expected.json",
                "--tokens",
                spec_dir / "tokens.json",
                "--diff-report",
                recomputed_diff,
                "--out",
                recomputed_fidelity,
            ],
        )
        if not recomputed_fidelity.is_file():
            failures.append(
                "check_render_fidelity.py did not produce a recomputed report: "
                + (fidelity_result.stderr.strip() or fidelity_result.stdout.strip())
            )
            return failures
        try:
            if load_object(spec_dir / "render_fidelity_report.json") != load_object(
                recomputed_fidelity
            ):
                failures.append(
                    "render_fidelity_report.json differs from deterministic recomputation"
                )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"render fidelity report unreadable: {error}")
        if fidelity_result.returncode != 0:
            failures.append(
                "check_render_fidelity.py deterministic recomputation is not passing"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True)
    args = parser.parse_args()
    spec_dir = Path(args.spec_dir).expanduser().resolve()
    failures = validate_visual_provenance(spec_dir)
    if failures:
        print(f"FAIL visual provenance {spec_dir.name} ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"ok visual provenance: {spec_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
