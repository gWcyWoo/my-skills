#!/usr/bin/env python3
"""Public-CLI regression for explicit assembly runtime fixture wiring."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message: str) -> int:
    print(f"FAIL {message}", file=sys.stderr)
    return 1


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent

    with tempfile.TemporaryDirectory(prefix="iff-assembly-runtime-fixture-") as tmp_raw:
        tmp = Path(tmp_raw)
        project = (tmp / "project").resolve()
        spec = project / "lanhu" / "specs" / "home"
        for board in ("首页-首贷", "首页-等待中", "首页-审核拒绝"):
            (spec / board).mkdir(parents=True)

        row = tmp / "row.json"
        prompt = tmp / "assembly_prompt.txt"
        row.write_text(json.dumps({"title": "首页"}, ensure_ascii=False), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "assembly",
                "--row-json",
                str(row),
                "--spec-dir",
                str(spec),
                "--project-root",
                str(project),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            return fail(f"make_worker_prompt exited {result.returncode}: {result.stderr.strip()}")

        generated = prompt.read_text(encoding="utf-8")
        runtime_target = project / "lib" / "home" / "presentation" / "home_page.dart"
        target_marker = f"`RUNTIME_FIXTURE_TARGET={runtime_target}`"
        symbol_marker = "`FIXTURE_SYMBOL=HomeVisualFixture`"
        exact_reference = (
            "must contain the exact generated fixture symbol `HomeVisualFixture` "
            "in executable Dart runtime/page code"
        )
        indirect_forbidden = (
            "Indirect value copies, test-only references, or only a repository abstraction do NOT satisfy"
        )
        pre_gate = (
            "rg -n -w -F -e HomeVisualFixture "
            f"{shlex.quote(str(runtime_target))}"
        )
        green_marker = "Only after packaging evidence exists and the runtime pre-gate exits 0, run the single required GREEN test command"
        strict_marker = (
            f"check_fixture_source.py --root {project} --fixture-name HomeVisualFixture"
        )

        required = (
            target_marker,
            symbol_marker,
            exact_reference,
            indirect_forbidden,
            pre_gate,
            "pre-gate exit is nonzero, STOP before GREEN",
            green_marker,
            strict_marker,
        )
        missing = [item for item in required if item not in generated]
        if missing:
            return fail(f"assembly prompt lacks runtime fixture target contract: {missing}")

        positions = [
            generated.index(target_marker),
            generated.index(pre_gate),
            generated.index(green_marker),
            generated.index(strict_marker),
        ]
        if positions != sorted(positions) or len(set(positions)) != len(positions):
            return fail(f"runtime fixture contract is out of order: {positions}")

    print("PASS assembly wires an exact runtime fixture target before GREEN and strict gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
