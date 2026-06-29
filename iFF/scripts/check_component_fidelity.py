#!/usr/bin/env python3
"""DEPRECATED — golden-vs-golden component fidelity is forbidden (Invariant ⑥).

This check used to diff the component page screenshot against the generate_canvas golden
screenshot. That is a self-vs-self comparison: the golden and the geometry-pinned component
page are both rendered from render_plan, so it could never catch the failures that matter
(static/Offstage layers, data overflowing the design, mis-bound fields) and it tied the gate
to the cross-engine pixel ceiling.

It is replaced by a STRUCTURED, design-anchored gate that compares the REAL render of the
on-line page against the design's render_plan, per component:

  python3 gen_layout_trace_test.py --expected <canvas>.dart.expected.json \
      --page-import <pkg path> --page-type <Widget> --trace-out <abs>/actual_layout_trace.json \
      --out test/<feature>_layout_trace_test.dart
  flutter test test/<feature>_layout_trace_test.dart
  python3 check_render_fidelity.py --trace <abs>/actual_layout_trace.json \
      --expected <canvas>.dart.expected.json --tokens <spec_dir>/tokens.json --out <report>

This shim fails loudly so no pipeline can silently fall back to golden-vs-golden.
"""
import sys

if __name__ == "__main__":
    sys.stderr.write(
        "check_component_fidelity.py is DEPRECATED (golden-vs-golden violates Invariant ⑥).\n"
        "Use gen_layout_trace_test.py + check_render_fidelity.py "
        "(real on-line render vs render_plan). See this file's docstring.\n")
    raise SystemExit(2)
