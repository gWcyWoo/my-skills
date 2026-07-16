#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IMPORT_RE = re.compile(r"\b(?:import|export|part)\s+['\"]([^'\"]+)['\"]")
APP_RE = re.compile(r"\b(?:MaterialApp|CupertinoApp)\s*\(")
BANNER_FALSE_RE = re.compile(r"\bdebugShowCheckedModeBanner\s*:\s*false\b")


def package_name(project_root: Path) -> str:
    pubspec = project_root / "pubspec.yaml"
    if not pubspec.is_file():
        return ""
    match = re.search(r"(?m)^name:\s*([A-Za-z0-9_]+)\s*$", pubspec.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def resolve_import(source: Path, uri: str, project_root: Path, package: str) -> Path | None:
    if uri.startswith("dart:"):
        return None
    if uri.startswith("package:"):
        prefix = f"package:{package}/"
        if not package or not uri.startswith(prefix):
            return None
        candidate = project_root / "lib" / uri[len(prefix):]
    else:
        candidate = source.parent / uri
    resolved = candidate.resolve()
    lib_root = (project_root / "lib").resolve()
    if resolved.suffix != ".dart" or not resolved.is_relative_to(lib_root) or not resolved.is_file():
        return None
    return resolved


def reachable_sources(entry: Path, project_root: Path) -> list[Path]:
    package = package_name(project_root)
    pending = [entry.resolve()]
    seen: set[Path] = set()
    while pending:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        text = source.read_text(encoding="utf-8")
        imports = [resolve_import(source, uri, project_root, package) for uri in IMPORT_RE.findall(text)]
        pending.extend(sorted((path for path in imports if path is not None), reverse=True))
    return sorted(seen)


def constructor_body(text: str, start: int) -> str:
    open_index = text.find("(", start)
    depth = 0
    quote = ""
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_index:index + 1]
    return text[open_index:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the real Flutter app entry disables the debug banner before capture")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    entry = Path(args.entry).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not entry.is_file() or not entry.is_relative_to(project_root / "lib"):
        report = {"ok": False, "reason": "invalid_entry", "entry": str(entry)}
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"ERROR: invalid Flutter entry: {entry}")
        return 2

    reachable = reachable_sources(entry, project_root)
    app_shell_files: list[str] = []
    safe_files: list[str] = []
    for source in reachable:
        text = source.read_text(encoding="utf-8")
        matches = list(APP_RE.finditer(text))
        if not matches:
            continue
        app_shell_files.append(str(source))
        if all(BANNER_FALSE_RE.search(constructor_body(text, match.start())) for match in matches):
            safe_files.append(str(source))

    if not app_shell_files:
        ok = False
        reason = "app_shell_not_found"
    elif sorted(app_shell_files) != sorted(safe_files):
        ok = False
        reason = "debug_banner_not_disabled"
    else:
        ok = True
        reason = None
    report = {
        "ok": ok,
        "reason": reason,
        "entry": str(entry),
        "reachableFiles": [str(path) for path in reachable],
        "appShellFiles": app_shell_files,
        "bannerSafeFiles": safe_files,
    }
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if ok:
        print(f"ok capture readiness: {len(app_shell_files)} reachable app shell file(s)")
        return 0
    print(f"ERROR: capture readiness failed: {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
