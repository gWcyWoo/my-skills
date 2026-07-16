#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


TEMPLATE_TEST = """import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:demo/main.dart';

void main() {
  testWidgets('Counter increments smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const MyApp());
    expect(find.text('0'), findsOneWidget);
    expect(find.text('1'), findsNothing);
    await tester.tap(find.byIcon(Icons.add));
    await tester.pump();
    expect(find.text('0'), findsNothing);
    expect(find.text('1'), findsOneWidget);
  });
}
"""


def run(script: Path, project: Path, evidence: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), "--project-root", str(project), "--out", str(evidence)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(evidence.read_text(encoding="utf-8"))


def write_project(project: Path, *, home: str, test_source: str) -> None:
    (project / "lib").mkdir(parents=True, exist_ok=True)
    (project / "test").mkdir(parents=True, exist_ok=True)
    (project / "lib" / "main.dart").write_text(
        "class MyApp { Object build() => MaterialApp(home: const " + home + "()); }\n",
        encoding="utf-8",
    )
    (project / "test" / "widget_test.dart").write_text(test_source, encoding="utf-8")


def main() -> int:
    skill_dir = Path(__file__).resolve().parent.parent
    script = skill_dir / "scripts" / "retire_stale_flutter_template_tests.py"
    with tempfile.TemporaryDirectory(prefix="iff-retire-template-tests-") as raw_tmp:
        tmp = Path(raw_tmp)

        stale = tmp / "stale"
        write_project(stale, home="HomePage", test_source=TEMPLATE_TEST)
        stale_report = run(script, stale, stale / ".iff" / "report.json")
        assert stale_report["action"] == "archived", stale_report
        assert not (stale / "test" / "widget_test.dart").exists()
        archived = Path(stale_report["archive"])
        assert archived.is_file()
        assert archived.read_text(encoding="utf-8") == TEMPLATE_TEST

        active = tmp / "active"
        write_project(active, home="MyHomePage", test_source=TEMPLATE_TEST)
        active_report = run(script, active, active / ".iff" / "report.json")
        assert active_report["action"] == "kept_active_template", active_report
        assert (active / "test" / "widget_test.dart").is_file()

        custom = tmp / "custom"
        write_project(
            custom,
            home="HomePage",
            test_source=TEMPLATE_TEST.replace("}\n", "  testWidgets('custom behavior', (_) async {});\n}\n", 1),
        )
        custom_report = run(script, custom, custom / ".iff" / "report.json")
        assert custom_report["action"] == "kept_custom_test", custom_report
        assert (custom / "test" / "widget_test.dart").is_file()

    print("retire stale Flutter template tests self-test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
