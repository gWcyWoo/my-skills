#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(checker: Path, root: Path, expected: int) -> dict:
    report = root / "capture_readiness.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(checker),
            "--project-root",
            str(root),
            "--entry",
            str(root / "lib" / "main.dart"),
            "--out",
            str(report),
        ],
        text=True,
        capture_output=True,
    )
    assert completed.returncode == expected, completed.stdout + completed.stderr
    return json.loads(report.read_text(encoding="utf-8"))


def write_project(root: Path, app_source: str, unrelated_source: str = "") -> None:
    (root / "lib").mkdir(parents=True)
    (root / "pubspec.yaml").write_text("name: capture_fixture\n", encoding="utf-8")
    (root / "lib" / "main.dart").write_text(
        "import 'app.dart';\nvoid main() => runApp(const App());\n",
        encoding="utf-8",
    )
    (root / "lib" / "app.dart").write_text(app_source, encoding="utf-8")
    if unrelated_source:
        (root / "lib" / "unrelated.dart").write_text(unrelated_source, encoding="utf-8")


def main() -> int:
    checker = Path(__file__).with_name("check_capture_readiness.py")
    with tempfile.TemporaryDirectory(prefix="iff-capture-readiness-") as tmp:
        root = Path(tmp)
        passing = root / "passing"
        write_project(
            passing,
            "class App { const App(); Widget build(context) => MaterialApp("
            "debugShowCheckedModeBanner: false); }\n",
        )
        report = run(checker, passing, 0)
        assert report["ok"] is True, report
        assert report["appShellFiles"] == [str((passing / "lib" / "app.dart").resolve())], report

        failing = root / "failing"
        write_project(
            failing,
            "class App { const App(); Widget build(context) => MaterialApp(); }\n",
            "final ignored = MaterialApp(debugShowCheckedModeBanner: false);\n",
        )
        report = run(checker, failing, 1)
        assert report["ok"] is False, report
        assert report["reason"] == "debug_banner_not_disabled", report
        assert str((failing / "lib" / "unrelated.dart").resolve()) not in report["reachableFiles"], report

    print("PASS: capture readiness rejects debug banners through the real entry graph")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
