#!/usr/bin/env python3
"""Reject worker changes outside one feature state's declared file ownership."""

from __future__ import annotations

import argparse
import json
from pathlib import PurePosixPath, Path


def normalize_project_path(value: object) -> str | None:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def validate_state_change_scope(
    manifest: dict, state_key: str, changed: list[str]
) -> list[str]:
    state = (manifest.get("states") or {}).get(state_key)
    if not isinstance(state, dict):
        return [f"unknown feature state: {state_key}"]
    declared = [state.get("canvasPath"), *(state.get("generatedFiles") or [])]
    allowed = {
        path
        for value in declared
        if value
        for path in [normalize_project_path(value)]
        if path
    }
    return [
        f"out-of-scope change: {value}"
        for value in changed
        if normalize_project_path(value) not in allowed
    ]


def validate_state_changes(manifest: dict, document: object) -> list[str]:
    if not isinstance(document, dict):
        return ["state changes document must be an object"]
    failures: list[str] = []
    if document.get("version") != 1:
        failures.append("state changes version must be 1")
    changes = document.get("states")
    if not isinstance(changes, dict):
        return [*failures, "state changes states must be an object"]
    declared = manifest.get("states") or {}
    if not isinstance(declared, dict) or not declared:
        return [*failures, "feature manifest has no states"]
    for state in sorted(set(declared) - set(changes)):
        failures.append(f"state changes missing declared state: {state}")
    for state in sorted(set(changes) - set(declared)):
        failures.append(f"state changes contains unknown state: {state}")

    owners: dict[str, str] = {}
    for state in sorted(set(declared) & set(changes)):
        files = changes[state]
        if not isinstance(files, list) or not files:
            failures.append(f"state changes files must be a non-empty list: {state}")
            continue
        normalized_files: list[str] = []
        for value in files:
            normalized = normalize_project_path(value)
            if not normalized:
                failures.append(f"invalid project path for state {state}: {value}")
                continue
            previous = owners.get(normalized)
            if previous is not None:
                failures.append(
                    f"changed file listed for multiple states: {normalized} "
                    f"({previous}, {state})"
                )
                continue
            owners[normalized] = state
            normalized_files.append(normalized)
        failures.extend(validate_state_change_scope(manifest, state, normalized_files))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--state")
    mode.add_argument("--state-changes")
    parser.add_argument("--changed-files")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.state_changes:
        if args.changed_files:
            parser.error("--changed-files cannot be combined with --state-changes")
        document = json.loads(Path(args.state_changes).read_text(encoding="utf-8"))
        failures = validate_state_changes(manifest, document)
        label = "all-states"
        count = sum(
            len(files) for files in (document.get("states") or {}).values()
            if isinstance(files, list)
        ) if isinstance(document, dict) else 0
    else:
        if not args.changed_files:
            parser.error("--changed-files is required with --state")
        changed = [
            line.strip()
            for line in Path(args.changed_files).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        failures = validate_state_change_scope(manifest, args.state, changed)
        label = args.state
        count = len(changed)
    if failures:
        print(f"FAIL state change scope {manifest.get('featureId') or 'unknown'}/{label}:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"ok state change scope: {label} ({count} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
