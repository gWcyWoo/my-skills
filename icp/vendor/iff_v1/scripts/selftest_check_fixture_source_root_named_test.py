#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff-fixture-source-") as raw_tmp:
        project = Path(raw_tmp) / "test"
        fixture = project / "lib" / "home_visual_fixture.dart"
        runtime = project / "lib" / "home_page.dart"
        widget_test = project / "test" / "home_page_test.dart"
        fixture.parent.mkdir(parents=True)
        widget_test.parent.mkdir(parents=True)

        fixture.write_text(
            "abstract final class HomeVisualFixture {\n"
            "  static const items = <String>['design'];\n"
            "}\n",
            encoding="utf-8",
        )
        runtime.write_text(
            "final runtimeItems = HomeVisualFixture.items;\n",
            encoding="utf-8",
        )
        widget_test.write_text(
            "final testedItems = HomeVisualFixture.items;\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "check_fixture_source.py"),
                "--root",
                str(project),
                "--fixture-name",
                "HomeVisualFixture",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode

    print("PASS: a root named test keeps lib runtime refs separate from root-relative test refs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
