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
# Corpus-driven: each accumulated failure becomes a permanent regression fixture (a dir under
# evolution/regression/ with render_plan.json + classification.json [+ meta.json]). Run ALL of them.
# This is the load-bearing mechanism of the self-improving skill: a fix's failing case is added here
# (red-before / green-after), and it can never silently regress because the whole corpus is re-run.
# A fix can be masked by ANOTHER path in the SAME fixture (R11: a fixture with both '<' and 'v'
# chevrons hid the back-'<'-only unused_element_parameter), so corpus entries must be MINIMAL +
# single-concern, and analyze fails on warnings (not just errors).
CORPUS_DIR = SCRIPTS.parent / "evolution" / "regression"


def discover_corpus():
    """Each subdir of evolution/regression/ with render_plan.json + classification.json is a case."""
    entries = []
    for d in sorted(p for p in CORPUS_DIR.iterdir() if p.is_dir()) if CORPUS_DIR.is_dir() else []:
        rp, cls = d / "render_plan.json", d / "classification.json"
        if rp.is_file() and cls.is_file():
            entries.append((d.name, rp, cls))
    return entries


def run(cmd, cwd=None, capture=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)


def fail(stage: str, detail: str) -> int:
    print(f"SELFTEST FAIL [{stage}]: {detail}")
    return 1


def _check_ref(proj: Path, pkg: str, tag: str, ref_plan: Path, ref_cls: Path, keep: bool):
    """Run the full chain for one corpus case. Returns (ok: bool, present: int, fail_detail: str)."""
    cls_name = "Selftest" + "".join(ch for ch in tag.title() if ch.isalnum()) + "Canvas"
    work = proj / "lib" / f"_iff_selftest_{tag}"
    testdir = proj / "test" / f"_iff_selftest_{tag}"
    trace_out = proj / ".dart_tool" / f"iff_selftest_trace_{tag}.json"
    for d in (work, testdir):
        if d.exists():
            shutil.rmtree(d)
    work.mkdir(parents=True)
    testdir.mkdir(parents=True)
    try:
        canvas = work / "selftest_canvas.dart"
        colors = work / "app_colors.dart"
        r = run([sys.executable, str(SCRIPTS / "generate_canvas.py"),
                 "--render-plan", str(ref_plan), "--classification", str(ref_cls),
                 "--class-name", cls_name, "--out", str(canvas),
                 "--colors-out", str(colors), "--colors-import", "app_colors.dart"])
        if r.returncode != 0:
            return False, 0, f"generate_canvas: {r.stderr.strip() or r.stdout.strip()}"
        expected = Path(str(canvas) + ".expected.json")
        if not expected.is_file():
            return False, 0, "generate_canvas: expected.json sidecar not emitted"

        trace_test = testdir / "selftest_layout_trace_test.dart"
        r = run([sys.executable, str(SCRIPTS / "gen_layout_trace_test.py"),
                 "--expected", str(expected),
                 "--page-import", f"package:{pkg}/_iff_selftest_{tag}/selftest_canvas.dart",
                 "--page-type", cls_name,
                 "--trace-out", str(trace_out), "--out", str(trace_test)])
        if r.returncode != 0:
            return False, 0, f"gen_layout_trace_test: {r.stderr.strip() or r.stdout.strip()}"

        # flutter analyze — catches COMPILE/lint regressions (R7 EditableText null-safety;
        # the chevron unused_element_parameter, which only shows on a back-only design).
        r = run(["flutter", "analyze", str(work), str(testdir)], cwd=str(proj))
        bad = [ln for ln in (r.stdout + r.stderr).splitlines()
               if re.search(r"(\berror\b|\bwarning\b)\s+•", ln)]
        if bad:
            return False, 0, "flutter analyze NOT clean:\n  " + "\n  ".join(bad[:8])

        r = run(["flutter", "test", str(trace_test)], cwd=str(proj))
        if r.returncode != 0:
            tail = "\n  ".join((r.stdout + r.stderr).splitlines()[-8:])
            return False, 0, f"flutter test (trace) failed:\n  {tail}"
        if not trace_out.is_file():
            return False, 0, "trace JSON not written — page may not have rendered"

        rep = proj / ".dart_tool" / f"iff_selftest_fidelity_{tag}.json"
        r = run([sys.executable, str(SCRIPTS / "check_render_fidelity.py"),
                 "--trace", str(trace_out), "--expected", str(expected), "--out", str(rep)])
        if r.returncode != 0:
            return False, 0, f"check_render_fidelity: {r.stdout.strip() or r.stderr.strip()}"

        present = sum(1 for v in json.loads(trace_out.read_text(encoding="utf-8")).get("nodes", {}).values()
                      if v.get("present"))
        return True, present, ""
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(testdir, ignore_errors=True)
            trace_out.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".", help="target flutter project root")
    ap.add_argument("--keep", action="store_true", help="keep the temp dirs for inspection")
    a = ap.parse_args()

    proj = Path(a.project).resolve()
    pubspec = proj / "pubspec.yaml"
    if not pubspec.is_file():
        return fail("setup", f"no flutter project at {proj}")
    m = re.search(r"^name:\s*(\w+)", pubspec.read_text(encoding="utf-8"), re.M)
    if not m:
        return fail("setup", "could not read package name from pubspec.yaml")
    pkg = m.group(1)

    corpus = discover_corpus()
    if not corpus:
        return fail("setup", f"no regression cases under {CORPUS_DIR}")
    for tag, ref_plan, ref_cls in corpus:
        ok, present, detail = _check_ref(proj, pkg, tag, ref_plan, ref_cls, a.keep)
        if not ok:
            return fail(f"corpus case '{tag}'", detail)
        print(f"  [{tag}] ok — {present} nodes rendered, analyze clean, fidelity pass")
    print(f"SELFTEST OK: visible-layer toolchain green on all {len(corpus)} regression corpus "
          f"case(s). Safe to commit visible-layer changes. (Add a fixture under evolution/regression/ "
          f"for every new failure — red-before/green-after — so it can never silently regress.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
