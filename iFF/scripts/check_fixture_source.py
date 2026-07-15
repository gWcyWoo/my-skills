#!/usr/bin/env python3
"""Check the SAME-SOURCE fixture invariant (②⑦): the design-seeded visual fixture is shared by
BOTH the tests and the runtime/page — not a test-only mock and a separate runtime default.

Feature-agnostic: it auto-detects the fixture's exported symbol(s) from any `*visual_fixture.dart`
(class / top-level const / final), then verifies at least one symbol is referenced from a test file
AND from a non-test lib file. Pass --fixture-name to pin a specific symbol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

# 允许 class 前的修饰符(abstract/final/sealed/base/interface/mixin),否则
# `abstract final class XxxVisualFixture` 这种声明会被漏检(make_visual_fixture 正是这么发的)。
SYMBOL = re.compile(
    r"^\s*(?:(?:abstract|final|sealed|base|interface|mixin)\s+)*(?:class|mixin|enum|extension)\s+(\w+)"
    r"|^\s*(?:const|final)\s+(?:[\w<>, ]+\s+)?(\w+)\s*=",
    re.M)
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
IMPORT = re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]", re.M)


def is_skip(path: Path) -> bool:
    return ".dart_tool" in path.parts or "build" in path.parts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fixture-name", help="pin a specific fixture symbol (default: auto-detect)")
    args = parser.parse_args()

    root = Path(args.root)
    fixture_files = [p for p in root.rglob("*visual_fixture.dart") if not is_skip(p)]
    if not fixture_files:
        raise SystemExit("ERROR: no *visual_fixture.dart found (same-source fixture missing)")

    symbols: set[str] = set()
    if args.fixture_name:
        symbols.add(args.fixture_name)
    else:
        for fx in fixture_files:
            for m in SYMBOL.finditer(fx.read_text(encoding="utf-8")):
                symbols.add(m.group(1) or m.group(2))
    symbols = {s for s in symbols if s}
    if not symbols:
        raise SystemExit(f"ERROR: no exported symbol found in fixture file(s): "
                         f"{[str(f) for f in fixture_files]}")

    test_refs: set[str] = set()
    runtime_refs: set[str] = set()
    fixture_names = {path.name for path in fixture_files}
    for path in root.rglob("*.dart"):
        if is_skip(path) or path in fixture_files:
            continue
        try:
            text = COMMENTS.sub("", path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
        if not any(Path(uri).name in fixture_names for uri in IMPORT.findall(text)):
            continue
        hit = next((s for s in symbols if re.search(rf"\b{re.escape(s)}\b", text)), None)
        if not hit:
            continue
        if "test" in path.parts or path.name.endswith("_test.dart"):
            test_refs.add(hit)
        else:
            runtime_refs.add(hit)

    shared = test_refs & runtime_refs
    if not shared:
        raise SystemExit(
            "ERROR: fixture is NOT same-source. A fixture symbol must be referenced by BOTH a test "
            f"and a runtime/page file. symbols={sorted(symbols)} test_refs={sorted(test_refs)} "
            f"runtime_refs={sorted(runtime_refs)}. The widget test, preview and the page/repository "
            "must read the SAME design fixture (②⑦).")

    for fixture in fixture_files:
        source_path = Path(str(fixture) + ".source.json")
        if not source_path.is_file():
            raise SystemExit(f"ERROR: fixture source provenance missing: {source_path}")
        source = json.loads(source_path.read_text(encoding="utf-8"))
        for state, record in (source.get("states") or {}).items():
            seed_path = Path(str((record or {}).get("path") or ""))
            current_hash = (
                hashlib.sha256(seed_path.read_bytes()).hexdigest()
                if seed_path.is_file()
                else None
            )
            if current_hash != (record or {}).get("sha256"):
                raise SystemExit(f"ERROR: stale design slot seed: {state}")
        if hashlib.sha256(fixture.read_bytes()).hexdigest() != source.get("fixtureSha256"):
            raise SystemExit(f"ERROR: fixture differs from generated source: {fixture}")
    print(f"ok same-source fixture: shared symbol(s)={sorted(shared)} "
          f"(fixtureFiles={len(fixture_files)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
