#!/usr/bin/env python3
"""Gate: interaction/behavior logic must be WIRED at runtime, not only exercised by tests.

The failure this catches (observed on the first iFF home run): domain logic (e.g. the
permission/risk chain, the apply_status router) was fully implemented and unit-tested, but no
runtime code path invoked it — the shipped page rendered a static canvas and never reached the
behavior. Tests were green; the feature was dead.

Mechanism (deterministic):
  1. Build the import graph over lib/ (package: and relative imports).
  2. BFS the set REACHABLE from the entry point (lib/main.dart).
  3. Collect lib files that TEST files import (the tested behavior units).
  4. Any tested unit NOT reachable from the entry is tested-but-unwired -> FAIL.

This does not prove every interaction RULE is correct (that is the test suite's job); it proves
the implemented behavior is actually on a runtime path from the app entry. Run it in the step-12
audit. A unit that is legitimately entry-unreachable (pure dev tool) must be justified, not left
imported only by tests.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import deque
from pathlib import Path

_IMPORT = re.compile(r"""^\s*(?:import|export)\s+['"]([^'"]+)['"]""", re.MULTILINE)


def pkg_name(pubspec: Path) -> str | None:
    if not pubspec.is_file():
        return None
    for line in pubspec.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^name:\s*([A-Za-z0-9_]+)\s*$", line)
        if m:
            return m.group(1)
    return None


def resolve(import_uri: str, from_file: Path, lib_root: Path, pkg: str | None) -> Path | None:
    """Resolve a Dart import URI to a concrete lib/ file path, or None if external."""
    if import_uri.startswith("dart:"):
        return None
    if import_uri.startswith("package:"):
        body = import_uri[len("package:"):]
        parts = body.split("/", 1)
        if len(parts) != 2 or (pkg and parts[0] != pkg):
            return None  # third-party package
        if pkg is None:
            return None
        return (lib_root / parts[1]).resolve()
    if import_uri.endswith(".dart"):  # relative
        return (from_file.parent / import_uri).resolve()
    return None


def imports_of(path: Path, lib_root: Path, pkg: str | None) -> set:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    out = set()
    for uri in _IMPORT.findall(text):
        r = resolve(uri, path, lib_root, pkg)
        if r is not None and r.is_file():
            out.add(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib-root", default="lib")
    ap.add_argument("--test-root", default="test")
    ap.add_argument("--entry", default="lib/main.dart")
    ap.add_argument("--pubspec", default="pubspec.yaml")
    ap.add_argument("--contract", help="interaction_contract.json (for INT-rule context only)")
    ap.add_argument("--out", help="optional wiring_report.json path")
    args = ap.parse_args()

    lib_root = Path(args.lib_root).resolve()
    test_root = Path(args.test_root).resolve()
    entry = Path(args.entry).resolve()
    pkg = pkg_name(Path(args.pubspec))

    if not entry.is_file():
        print(f"FAIL interaction wiring: entry not found {entry}")
        return 1

    # 1-2) reachable set from entry.
    reachable = set()
    q = deque([entry])
    while q:
        cur = q.popleft()
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt in imports_of(cur, lib_root, pkg):
            if nxt not in reachable:
                q.append(nxt)

    # 3) lib files imported by tests.
    tested = set()
    for t in test_root.rglob("*_test.dart"):
        for r in imports_of(t, lib_root, pkg):
            if lib_root in r.parents:
                tested.add(r)

    # 4) tested but unreachable from entry.
    unwired = sorted(p for p in tested if p not in reachable)

    rel = lambda p: str(p.relative_to(lib_root.parent)) if lib_root.parent in p.parents else str(p)
    int_rules = 0
    if args.contract and Path(args.contract).is_file():
        try:
            int_rules = len(json.loads(Path(args.contract).read_text(encoding="utf-8")).get("rules", []))
        except (OSError, ValueError):
            int_rules = 0

    report = {
        "entry": rel(entry),
        "package": pkg,
        "reachableCount": len(reachable),
        "testedUnitCount": len(tested),
        "interactionRuleCount": int_rules,
        "unwired": [rel(p) for p in unwired],
        "ok": not unwired,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if unwired:
        print(f"FAIL interaction wiring: {len(unwired)} tested unit(s) unreachable from {rel(entry)} "
              f"(implemented + tested but never invoked at runtime):")
        for p in unwired:
            print(f"  - {rel(p)}")
        print("Wire each into a runtime path from the entry (component event / page orchestration / "
              "repository), or justify why it is entry-unreachable.")
        return 1

    print(f"ok interaction wiring: {len(tested)} tested unit(s) all reachable from {rel(entry)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
