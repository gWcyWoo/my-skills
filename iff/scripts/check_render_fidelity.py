#!/usr/bin/env python3
"""Structured per-component fidelity gate (Invariant ③ / ⑥).

Compares the REAL render trace of the on-line page (`actual_layout_trace.json`, produced by the
generated widget test) against the design-derived expectation (`*.expected.json`, emitted by
generate_canvas straight from render_plan). This is NOT golden-vs-golden and NOT raw-pixel SSIM:
every value compared is a structured quantity sourced from the design (render_plan/tokens), so a
divergence means the real component render does not honor the design — fix the generator/binding,
never eyeball the app.

Per node (tolerances from the goal):
  - present:   the keyed node must actually render (catches Offstage / 0x0 collapse / wrong page).
  - bbox:      |actual - expected| <= bbox_tol px on x,y,w,h.
  - text:      whitespace-normalized string equality (OCR/text 100%).
  - fontSize:  |actual - expected| <= size_tol px.
  - color:     per-channel |actual - expected| <= color_tol (RGB).
  - radius:    |actual - expected| <= size_tol px.
  - token:     (when --tokens given) the rendered color must be one of the design tokens (100% hit).
  - asset_shape: (when --diff-report given) an icon/asset REGION whose raw pixel mismatch
                 exceeds --asset-mismatch-tol failed to render the actual glyph (bbox/color
                 checks are blind to shape; the flat-region pixel channel is not).

Exit non-zero if any node fails any applicable check. The report lists every failing node with the
expected vs observed values and the category, so repair is mechanical and design-anchored.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WS = re.compile(r"\s+")


def norm_text(s) -> str:
    return WS.sub(" ", str(s or "")).strip()


def hex_rgb(h):
    if not h:
        return None
    h = str(h).lstrip("#")
    if len(h) == 8:  # AARRGGBB
        h = h[2:]
    if len(h) != 6:
        return None
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def argb_rgb(v):
    if v is None:
        return None
    v = int(v) & 0xFFFFFFFF
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


def chan_max_diff(a, b):
    return max(abs(a[i] - b[i]) for i in range(3))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="actual_layout_trace.json (real render)")
    ap.add_argument("--expected", required=True, help="generate_canvas *.expected.json (design truth)")
    ap.add_argument("--tokens", help="tokens.json — gate that rendered colors are design tokens")
    ap.add_argument("--diff-report", help="visual_diff diff_report.json — gate icon/asset REGION shape: "
                                          "an asset region whose raw pixelMismatch exceeds --asset-mismatch-tol "
                                          "is a real flat-region defect (wrong glyph/icon), far above the "
                                          "cross-engine anti-aliasing floor, and fails the gate")
    ap.add_argument("--asset-mismatch-tol", type=float, default=0.10)
    ap.add_argument("--bbox-tol", type=float, default=2.0)
    ap.add_argument("--color-tol", type=float, default=3.0)
    ap.add_argument("--size-tol", type=float, default=1.0)
    ap.add_argument("--typography-tol", type=float, default=0.01)
    ap.add_argument("--out")
    a = ap.parse_args()

    expected = json.loads(Path(a.expected).read_text(encoding="utf-8")).get("nodes", {})
    trace = json.loads(Path(a.trace).read_text(encoding="utf-8")).get("nodes", {})

    token_rgb = set()
    if a.tokens and Path(a.tokens).is_file():
        tok = json.loads(Path(a.tokens).read_text(encoding="utf-8"))
        for v in _walk_hex(tok):
            rgb = hex_rgb(v)
            if rgb:
                token_rgb.add(rgb)

    failures = []
    checked = 0
    for nid, exp in expected.items():
        act = trace.get(nid)
        if not act or not act.get("present"):
            failures.append({"node": nid, "category": "missing", "impl": exp.get("impl"),
                             "detail": "keyed node did not render (Offstage / collapse / not mounted)"})
            continue
        checked += 1
        # geometry
        eb, ab = exp.get("bbox"), act.get("bbox")
        if eb and ab and len(eb) == 4 and len(ab) == 4:
            for i, axis in enumerate(("x", "y", "w", "h")):
                d = abs(float(ab[i]) - float(eb[i]))
                if d > a.bbox_tol:
                    failures.append({"node": nid, "category": "bbox", "impl": exp.get("impl"),
                                     "axis": axis, "expected": round(float(eb[i]), 2),
                                     "observed": round(float(ab[i]), 2), "delta": round(d, 2),
                                     "tol": a.bbox_tol})
        # text
        if exp.get("text") is not None:
            if norm_text(act.get("text")) != norm_text(exp.get("text")):
                failures.append({"node": nid, "category": "text", "impl": exp.get("impl"),
                                 "expected": norm_text(exp.get("text")),
                                 "observed": norm_text(act.get("text"))})
            if exp.get("fontSize") is not None:
                if act.get("fontSize") is None:
                    failures.append({"node": nid, "category": "fontSize", "impl": exp.get("impl"),
                                     "expected": exp["fontSize"], "observed": None})
                else:
                    d = abs(float(act["fontSize"]) - float(exp["fontSize"]))
                    if d > a.size_tol:
                        failures.append({"node": nid, "category": "fontSize", "impl": exp.get("impl"),
                                         "expected": exp["fontSize"], "observed": act["fontSize"],
                                         "delta": round(d, 2), "tol": a.size_tol})
            for expected_key, actual_key in (
                ("fontFamily", "fontFamily"),
                ("fontStyle", "fontStyle"),
                ("weight", "fontWeight"),
            ):
                expected_value = exp.get(expected_key)
                if expected_value is not None and act.get(actual_key) != expected_value:
                    failures.append(
                        {
                            "node": nid,
                            "category": "fontWeight" if expected_key == "weight" else expected_key,
                            "impl": exp.get("impl"),
                            "expected": expected_value,
                            "observed": act.get(actual_key),
                        }
                    )
            for key in ("letterSpacing", "lineHeight"):
                expected_value = exp.get(key)
                actual_value = act.get(key)
                if expected_value is None:
                    continue
                if actual_value is None:
                    failures.append(
                        {
                            "node": nid,
                            "category": key,
                            "impl": exp.get("impl"),
                            "expected": expected_value,
                            "observed": None,
                        }
                    )
                    continue
                delta = abs(float(actual_value) - float(expected_value))
                if delta > a.typography_tol:
                    failures.append(
                        {
                            "node": nid,
                            "category": key,
                            "impl": exp.get("impl"),
                            "expected": expected_value,
                            "observed": actual_value,
                            "delta": round(delta, 4),
                            "tol": a.typography_tol,
                        }
                    )
        # color (text color or shape fill)
        erg = hex_rgb(exp.get("colorHex"))
        arg = argb_rgb(act.get("colorArgb"))
        if erg:
            if not arg:
                failures.append({"node": nid, "category": "color", "impl": exp.get("impl"),
                                 "expected": exp.get("colorHex"), "observed": None})
            else:
                d = chan_max_diff(arg, erg)
                if d > a.color_tol:
                    failures.append({"node": nid, "category": "color", "impl": exp.get("impl"),
                                     "expected": exp.get("colorHex"), "observed": list(arg),
                                     "delta": d, "tol": a.color_tol})
                if token_rgb and not any(chan_max_diff(arg, t) <= a.color_tol for t in token_rgb):
                    failures.append({"node": nid, "category": "token", "impl": exp.get("impl"),
                                     "observed": list(arg), "detail": "rendered color is not a design token"})
        # radius
        if exp.get("radius") is not None:
            if act.get("radius") is None:
                if float(exp["radius"]) != 0:
                    failures.append({"node": nid, "category": "radius", "impl": exp.get("impl"),
                                     "expected": exp["radius"], "observed": None})
            else:
                d = abs(float(act["radius"]) - float(exp["radius"]))
                if d > a.size_tol:
                    failures.append({"node": nid, "category": "radius", "impl": exp.get("impl"),
                                     "expected": exp["radius"], "observed": act["radius"],
                                     "delta": round(d, 2), "tol": a.size_tol})

    # icon/asset region shape gate: bbox+color cannot see a wrong glyph drawn at the
    # right place in the right dominant color — the pixel diff's per-asset-region
    # mismatch can. AA-only residue stays ~<5%; a wrong icon is typically >30%.
    if a.diff_report and Path(a.diff_report).is_file():
        diff = json.loads(Path(a.diff_report).read_text(encoding="utf-8"))
        for issue in diff.get("assetIssues") or []:
            mismatch = float(issue.get("pixelMismatch") or 0)
            if mismatch > a.asset_mismatch_tol:
                failures.append({"node": issue.get("node"), "category": "asset_shape",
                                 "impl": issue.get("widget"), "role": issue.get("role"),
                                 "observed": round(mismatch, 4), "tol": a.asset_mismatch_tol,
                                 "detail": "asset region pixel mismatch beyond AA floor — "
                                           "wrong/missing icon glyph or unregistered asset"})

    by_cat = {}
    for f in failures:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    ok = len(failures) == 0
    report = {
        "ok": ok,
        "assetShapeChecked": bool(a.diff_report and Path(a.diff_report).is_file()),
        "expectedNodes": len(expected),
        "checkedNodes": checked,
        "failureCount": len(failures),
        "byCategory": by_cat,
        "tolerances": {
            "bbox": a.bbox_tol,
            "color": a.color_tol,
            "size": a.size_tol,
            "typography": a.typography_tol,
        },
        "failures": failures,
    }
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not ok:
        head = failures[:12]
        print(f"FAIL render fidelity: {len(failures)} failure(s) across {by_cat} "
              f"(expected {len(expected)} nodes, {checked} rendered).")
        for f in head:
            print("  - " + json.dumps(f, ensure_ascii=False))
        if len(failures) > len(head):
            print(f"  ... +{len(failures) - len(head)} more (see {a.out})")
        return 1
    print(f"ok render fidelity: {checked}/{len(expected)} nodes within tol "
          f"(bbox<={a.bbox_tol} color<={a.color_tol} size<={a.size_tol}).")
    return 0


def _walk_hex(obj):
    """Yield every '#RRGGBB'-ish string anywhere in tokens.json."""
    if isinstance(obj, str):
        if re.fullmatch(r"#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", obj):
            yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_hex(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_hex(v)


if __name__ == "__main__":
    raise SystemExit(main())
