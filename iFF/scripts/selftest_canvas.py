#!/usr/bin/env python3
"""Regression self-test for the visible-layer toolchain — run it after ANY change to
generate_canvas.py / gen_layout_trace_test.py / check_render_fidelity.py.

Root cause of several training rounds (R5/R7) was a regression cycle: a fix to generate_canvas or
the trace harness compiled/ran fine on the design that motivated it but broke a DIFFERENT path
(e.g. the EditableText branch null-safety, a chevron, a gradient) only discovered when the next
round's worker hit it. This self-test exercises the bug-prone node types from a bundled synthetic
reference (text, ₦ amount, rounded shape, gradient, tall-narrow Vector→'<' chevron, wide-short
Vector→'v' chevron, an input-value text) and asserts the whole chain still works:

  generate_canvas  →  flutter analyze (clean)  →  gen_layout_trace_test  →  flutter test
  →  check_render_fidelity (per-node pass)

Usage (run inside the target flutter project, or pass --project):
  python3 selftest_canvas.py --project /path/to/flutter/app
Exit 0 = green; non-zero = a regression (prints the failing stage).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SELFTEST = SCRIPTS.parent / "selftest"
REF_PLAN = SELFTEST / "ref_render_plan.json"
REF_CLS = SELFTEST / "ref_classification.json"


def run(cmd, cwd=None, capture=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)


def fail(stage: str, detail: str) -> int:
    print(f"SELFTEST FAIL [{stage}]: {detail}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".", help="target flutter project root")
    ap.add_argument("--keep", action="store_true", help="keep the temp dir for inspection")
    a = ap.parse_args()

    proj = Path(a.project).resolve()
    pubspec = proj / "pubspec.yaml"
    if not pubspec.is_file():
        return fail("setup", f"no flutter project at {proj}")
    m = re.search(r"^name:\s*(\w+)", pubspec.read_text(encoding="utf-8"), re.M)
    if not m:
        return fail("setup", "could not read package name from pubspec.yaml")
    pkg = m.group(1)

    work = proj / "lib" / "_iff_selftest"
    testdir = proj / "test" / "_iff_selftest"
    trace_out = proj / ".dart_tool" / "iff_selftest_trace.json"
    if work.exists():
        shutil.rmtree(work)
    if testdir.exists():
        shutil.rmtree(testdir)
    work.mkdir(parents=True)
    testdir.mkdir(parents=True)
    try:
        canvas = work / "selftest_canvas.dart"
        colors = work / "app_colors.dart"
        # 1) generate the canvas (exercises text/shape/gradient/chevron emission + expected.json)
        r = run([sys.executable, str(SCRIPTS / "generate_canvas.py"),
                 "--render-plan", str(REF_PLAN), "--classification", str(REF_CLS),
                 "--class-name", "SelftestCanvas", "--out", str(canvas),
                 "--colors-out", str(colors), "--colors-import", "app_colors.dart"])
        if r.returncode != 0:
            return fail("generate_canvas", r.stderr.strip() or r.stdout.strip())
        expected = Path(str(canvas) + ".expected.json")
        if not expected.is_file():
            return fail("generate_canvas", "expected.json sidecar not emitted")

        # 2) generate the trace test (its template carries the Text + EditableText branches)
        trace_test = testdir / "selftest_layout_trace_test.dart"
        r = run([sys.executable, str(SCRIPTS / "gen_layout_trace_test.py"),
                 "--expected", str(expected),
                 "--page-import", f"package:{pkg}/_iff_selftest/selftest_canvas.dart",
                 "--page-type", "SelftestCanvas",
                 "--trace-out", str(trace_out), "--out", str(trace_test)])
        if r.returncode != 0:
            return fail("gen_layout_trace_test", r.stderr.strip() or r.stdout.strip())

        # 3) flutter analyze — catches COMPILE regressions (the R7 EditableText null-safety class)
        r = run(["flutter", "analyze", str(work), str(testdir)], cwd=str(proj))
        errors = [ln for ln in (r.stdout + r.stderr).splitlines() if re.search(r"\berror\b\s+•", ln)]
        if errors:
            return fail("flutter analyze", "generated dart has errors:\n  " + "\n  ".join(errors[:8]))

        # 4) flutter test the trace test — catches RUNTIME regressions (0x0 collapse, asset crashes)
        r = run(["flutter", "test", str(trace_test)], cwd=str(proj))
        if r.returncode != 0:
            tail = "\n  ".join((r.stdout + r.stderr).splitlines()[-8:])
            return fail("flutter test (trace)", f"trace test failed:\n  {tail}")
        if not trace_out.is_file():
            return fail("flutter test (trace)", "trace JSON not written — page may not have rendered")

        # 5) check_render_fidelity — the structured per-node gate must pass on a faithful render
        rep = proj / ".dart_tool" / "iff_selftest_fidelity.json"
        r = run([sys.executable, str(SCRIPTS / "check_render_fidelity.py"),
                 "--trace", str(trace_out), "--expected", str(expected), "--out", str(rep)])
        if r.returncode != 0:
            return fail("check_render_fidelity", r.stdout.strip() or r.stderr.strip())

        ntr = json.loads(trace_out.read_text(encoding="utf-8")).get("nodes", {})
        present = sum(1 for v in ntr.values() if v.get("present"))
        print(f"SELFTEST OK: canvas+trace+fidelity green ({present} nodes rendered, "
              f"flutter analyze clean, check_render_fidelity pass).")
        return 0
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(testdir, ignore_errors=True)
            trace_out.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
