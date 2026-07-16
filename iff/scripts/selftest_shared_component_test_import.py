#!/usr/bin/env python3
"""Public-CLI regression: shared tests use the project's package import."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff_shared_test_import_") as td:
        project = Path(td) / "project"
        widget = project / "lib" / "shared" / "widgets" / "iff_shared_header.dart"
        test_out = project / "test" / "shared" / "widgets" / "iff_shared_header_test.dart"
        widget.parent.mkdir(parents=True)
        widget.write_text("class IffSharedHeader {}\n", encoding="utf-8")
        (project / "pubspec.yaml").write_text("name: synthetic_app\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "generate_shared_component_test.py"),
                "--project-root",
                str(project),
                "--widget-path",
                "lib/shared/widgets/iff_shared_header.dart",
                "--class-name",
                "IffSharedHeader",
                "--out",
                "test/shared/widgets/iff_shared_header_test.dart",
            ],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        generated = test_out.read_text(encoding="utf-8")
        assert (
            "import 'package:synthetic_app/shared/widgets/iff_shared_header.dart';"
            in generated
        ), generated
        assert "../../../lib/" not in generated, generated

    print("PASS: shared component test uses a deterministic package import")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
