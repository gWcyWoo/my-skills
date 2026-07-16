#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from common import dump_json


TEMPLATE_MARKERS = (
    "Counter increments smoke test",
    "pumpWidget(const MyApp())",
    "expect(find.text('0'), findsOneWidget)",
    "expect(find.text('1'), findsNothing)",
    "find.byIcon(Icons.add)",
    "expect(find.text('0'), findsNothing)",
    "expect(find.text('1'), findsOneWidget)",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    entry = project_root / "lib" / "main.dart"
    test_path = project_root / "test" / "widget_test.dart"
    report = {
        "schemaVersion": 1,
        "entry": str(entry),
        "test": str(test_path),
        "action": "absent",
    }
    if not test_path.is_file():
        dump_json(report, args.out)
        print("ok stale Flutter template test: absent")
        return 0
    if not entry.is_file():
        raise SystemExit(f"ERROR: missing Flutter entry {entry}")

    source = test_path.read_text(encoding="utf-8")
    entry_source = entry.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    report["sha256"] = digest
    is_template = source.count("testWidgets(") == 1 and all(marker in source for marker in TEMPLATE_MARKERS)
    if not is_template:
        report["action"] = "kept_custom_test"
        dump_json(report, args.out)
        print("ok stale Flutter template test: kept custom test")
        return 0

    home_match = re.search(r"\bhome\s*:\s*(?:const\s+)?([A-Za-z_]\w*)\s*\(", entry_source)
    home_widget = home_match.group(1) if home_match else None
    report["homeWidget"] = home_widget
    if home_widget == "MyHomePage":
        report["action"] = "kept_active_template"
        dump_json(report, args.out)
        print("ok stale Flutter template test: kept active counter template")
        return 0
    if home_widget is None:
        raise SystemExit("ERROR: cannot determine MaterialApp/CupertinoApp home widget; refusing to retire template test")

    archive_dir = project_root / ".iff" / "retired_template_tests"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"widget_test.{digest[:16]}.dart"
    if archive.exists() and archive.read_bytes() != test_path.read_bytes():
        raise SystemExit(f"ERROR: stale-test archive collision {archive}")
    if archive.exists():
        test_path.unlink()
    else:
        test_path.replace(archive)
    report["action"] = "archived"
    report["archive"] = str(archive)
    report["reason"] = "Flutter counter template test no longer targets the configured home widget"
    dump_json(report, args.out)
    print(f"ok stale Flutter template test: archived {test_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
