#!/usr/bin/env python3
"""Validate current Android/iOS interaction evidence for every planned case."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from check_interaction_coverage import observable_assertion_pattern


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_hashes(root: Path, paths: list[Path]) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(paths)
        if path.is_file()
    }


def app_hashes(project_root: Path) -> dict[str, str]:
    return file_hashes(project_root, list((project_root / "lib").rglob("*.dart")))


def test_hashes(test_root: Path) -> dict[str, str]:
    return file_hashes(test_root, list(test_root.rglob("*.dart")))


def runtime_input_hashes(project_root: Path) -> dict[str, str]:
    paths = [project_root / "pubspec.yaml", project_root / "pubspec.lock"]
    assets = project_root / "assets"
    if assets.is_dir():
        paths.extend(path for path in assets.rglob("*") if path.is_file())
    return file_hashes(project_root, paths)


def device_case_source_failures(plan: dict, test_root: Path) -> list[str]:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(test_root.rglob("*.dart"))
    )
    failures = []
    for case in plan.get("cases") or []:
        case_id = str(case.get("id") or "")
        declaration = re.search(
            r"testWidgets\s*\(\s*['\"][^'\"]*" + re.escape(case_id),
            sources,
        )
        if not declaration:
            failures.append(f"{case_id}: device case missing public action source")
            continue
        next_test = re.search(r"\btestWidgets\s*\(", sources[declaration.end():])
        end = declaration.end() + next_test.start() if next_test else len(sources)
        body = sources[declaration.start():end]
        if not re.search(r"\b(?:\w+\.)?main\s*\(", body):
            failures.append(f"{case_id}: device case does not start the app entry")
            continue
        target = case.get("actionTarget") or {}
        if target.get("kind") == "node":
            key = str(target.get("key") or "")
            action = re.compile(
                r"\btester\.(?:tap|enterText|drag|dragFrom|fling|flingFrom|longPress)\s*\(\s*"
                r"find\.byKey\s*\(\s*(?:const\s+)?ValueKey(?:<[^>]+>)?\s*\(\s*['\"]"
                + re.escape(key)
                + r"['\"]"
            )
            if not action.search(body):
                failures.append(f"{case_id}: device case missing public action on {key}")
                continue
        elif target.get("kind") == "system" and target.get("gesture") == "back":
            if not re.search(r"\btester\.pageBack\s*\(", body):
                failures.append(f"{case_id}: device case missing public action back")
                continue
        observable = case.get("expectedObservableTarget") or {}
        assertion = observable_assertion_pattern(observable)
        if assertion is None or not assertion.search(body):
            failures.append(f"{case_id}: device case missing planned observable assertion")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--test-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    test_root = Path(args.test_root).resolve()
    project_root = Path(args.project_root).resolve()
    evidence_path = Path(args.evidence).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    failures = []

    platforms = {str(value).lower() for value in evidence.get("actualPlatforms") or []}
    if not platforms.intersection({"android", "ios"}):
        failures.append("target client platform must be android or ios")
    command = evidence.get("command") or []
    device_id = str(evidence.get("deviceId") or "")
    if not (
        isinstance(command, list)
        and len(command) >= 6
        and Path(str(command[0])).name == "flutter"
        and command[1] == "test"
        and "--machine" in command
        and ("-d" in command or "--device-id" in command)
        and device_id
        and device_id in command
    ):
        failures.append("device evidence command must be flutter test --machine on deviceId")
    if evidence.get("exitCode") != 0:
        failures.append("device interaction test exitCode must be 0")
    if evidence.get("planHash") != sha256(plan_path):
        failures.append("stale device planHash")
    if evidence.get("testHashes") != test_hashes(test_root):
        failures.append("stale device testHashes")
    if evidence.get("appHashes") != app_hashes(project_root):
        failures.append("stale device appHashes")
    if evidence.get("runtimeInputHashes") != runtime_input_hashes(project_root):
        failures.append("stale device runtimeInputHashes")
    cases = evidence.get("cases") or {}
    failures.extend(device_case_source_failures(plan, test_root))
    for case in plan.get("cases") or []:
        case_id = str(case.get("id") or "")
        result = cases.get(case_id) or {}
        if result.get("result") != "success" or result.get("skipped"):
            failures.append(f"{case_id}: missing successful target-client evidence")

    if failures:
        raise SystemExit("ERROR: interaction device evidence failed:\n" + "\n".join(failures))
    print(f"ok interaction device evidence cases={len(plan.get('cases') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
