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
  - asset_shape: (when --diff-report given) an icon/asset REGION whose AA-filtered real-defect mismatch
                 exceeds --asset-mismatch-tol failed to render the actual glyph (bbox/color
                 checks are blind to shape; the flat-region pixel channel is not).

Exit non-zero if any node fails any applicable check. The report lists every failing node with the
expected vs observed values and the category, so repair is mechanical and design-anchored.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from layout_trace_contract import LayoutTraceContractError, actual_layout_trace_nodes
from dynamic_content_contract import DynamicContentContractError, load_api_dynamic_nodes

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


def bbox_key(value) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        return tuple(round(float(part), 6) for part in value)
    except (TypeError, ValueError):
        return None


def asset_pixel_mismatch(issue: dict) -> float:
    value = issue.get("pixelMismatchRealDefect")
    if value is None:
        value = issue.get("pixelMismatch")
    return float(value or 0)


def scoped_asset_regions(
    issues: list,
    expected: dict,
    trace: dict,
    board: str,
    tolerance: float,
) -> tuple[list[dict], list[str]]:
    expected_regions = {
        str(node): bbox_key(record.get("bbox"))
        for node, record in expected.items()
        if isinstance(record, dict) and str(node) in trace
    }
    matched: dict[tuple[str, tuple[float, float, float, float]], dict] = {}
    ambiguous: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        node = str(issue.get("node") or "")
        if node not in expected_regions or expected_regions[node] is None:
            continue
        mismatch = asset_pixel_mismatch(issue)
        if mismatch <= tolerance:
            continue
        issue_board = issue.get("board")
        if issue_board and issue_board != board:
            continue
        region = bbox_key(issue.get("bbox"))
        if not issue_board or region is None:
            ambiguous.add(node)
            continue
        if region != expected_regions[node]:
            continue
        key = (node, region)
        alias = {
            "state": issue.get("state"),
            "component": issue.get("component"),
            "role": issue.get("role"),
            "widget": issue.get("widget"),
        }
        current = matched.get(key)
        if current is None:
            current = {"issue": dict(issue), "aliases": []}
            matched[key] = current
        if alias not in current["aliases"]:
            current["aliases"].append(alias)
        if mismatch > asset_pixel_mismatch(current["issue"]):
            current["issue"] = dict(issue)
    scoped = []
    for key in sorted(matched):
        record = dict(matched[key]["issue"])
        record["aliases"] = matched[key]["aliases"]
        record["aliasCount"] = len(record["aliases"])
        scoped.append(record)
    return scoped, sorted(ambiguous)


def _require_expected_node_contract(trace_payload: dict, expected: dict) -> None:
    declared = trace_payload.get("expectedNodeIds")
    if (not isinstance(declared, list)
            or not all(isinstance(item, str) and item for item in declared)):
        raise LayoutTraceContractError(
            "actual_layout_trace.json lacks expectedNodeIds; regenerate it with "
            "gen_layout_trace_test.py so the trace and expected artifact are bound"
        )
    declared_ids = set(declared)
    expected_ids = set(expected)
    if declared_ids != expected_ids:
        missing = sorted(expected_ids - declared_ids)
        extra = sorted(declared_ids - expected_ids)
        raise LayoutTraceContractError(
            "trace/expected node contract mismatch: "
            f"missing_from_trace_contract={missing[:8]} extra_in_trace_contract={extra[:8]}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="actual_layout_trace.json (real render)")
    ap.add_argument("--expected", required=True, help="generate_canvas *.expected.json (design truth)")
    ap.add_argument("--tokens", help="tokens.json — gate that rendered colors are design tokens")
    ap.add_argument("--diff-report", help="visual_diff diff_report.json — gate icon/asset REGION shape after "
                                          "excluding independently rendered descendants and cross-engine AA; "
                                          "pixelMismatchRealDefect above --asset-mismatch-tol fails")
    ap.add_argument("--asset-mismatch-tol", type=float, default=0.10)
    ap.add_argument("--bbox-tol", type=float, default=2.0)
    ap.add_argument("--color-tol", type=float, default=3.0)
    ap.add_argument("--size-tol", type=float, default=1.0)
    ap.add_argument("--data-slot-bindings", help="validated dynamic-slot provenance; confirmed API text values may differ from the design fixture")
    ap.add_argument("--out")
    a = ap.parse_args()

    expected_document = json.loads(Path(a.expected).read_text(encoding="utf-8"))
    design_pixel_scale = float(expected_document.get("designPixelScale") or 1.0)
    if design_pixel_scale <= 0:
        raise SystemExit("ERROR: expected designPixelScale must be > 0")
    expected = expected_document.get("nodes", {})
    try:
        api_dynamic_nodes = load_api_dynamic_nodes(a.data_slot_bindings)
    except DynamicContentContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        trace_payload = json.loads(Path(a.trace).read_text(encoding="utf-8"))
        _require_expected_node_contract(trace_payload, expected)
        trace = actual_layout_trace_nodes(trace_payload)
    except (OSError, json.JSONDecodeError, LayoutTraceContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    token_rgb = set()
    if a.tokens and Path(a.tokens).is_file():
        tok = json.loads(Path(a.tokens).read_text(encoding="utf-8"))
        for v in _walk_hex(tok):
            rgb = hex_rgb(v)
            if rgb:
                token_rgb.add(rgb)

    failures = []
    asset_scope_summary = None
    checked = 0
    for nid, exp in expected.items():
        act = trace.get(nid)
        if not act or not act.get("present"):
            failures.append({"node": nid, "category": "missing", "impl": exp.get("impl"),
                             "detail": "keyed node did not render (Offstage / collapse / not mounted)"})
            continue
        checked += 1
        # geometry
        eb, ab = exp.get("logicalBbox"), act.get("bbox")
        if not (isinstance(eb, list) and len(eb) == 4):
            raw_bbox = exp.get("bbox")
            eb = ([float(value) / design_pixel_scale for value in raw_bbox]
                  if isinstance(raw_bbox, list) and len(raw_bbox) == 4 else raw_bbox)
        if eb and ab and len(eb) == 4 and len(ab) == 4:
            for i, axis in enumerate(("x", "y", "w", "h")):
                d = abs(float(ab[i]) - float(eb[i]))
                if d > a.bbox_tol:
                    failures.append({"node": nid, "category": "bbox", "impl": exp.get("impl"),
                                     "axis": axis, "expected": round(float(eb[i]), 2),
                                     "observed": round(float(ab[i]), 2), "delta": round(d, 2),
                                     "tol": a.bbox_tol})
        # text
        if exp.get("text") is not None and nid not in api_dynamic_nodes:
            if norm_text(act.get("text")) != norm_text(exp.get("text")):
                failures.append({"node": nid, "category": "text", "impl": exp.get("impl"),
                                 "expected": norm_text(exp.get("text")),
                                 "observed": norm_text(act.get("text"))})
            if exp.get("fontSize") is not None and act.get("fontSize") is not None:
                expected_font_size = float(exp["fontSize"]) / design_pixel_scale
                d = abs(float(act["fontSize"]) - expected_font_size)
                if d > a.size_tol:
                    failures.append({"node": nid, "category": "fontSize", "impl": exp.get("impl"),
                                     "expected": expected_font_size, "observed": act["fontSize"],
                                     "delta": round(d, 2), "tol": a.size_tol})
        # color (text color or shape fill)
        erg = hex_rgb(exp.get("colorHex"))
        arg = argb_rgb(act.get("colorArgb"))
        if erg and arg:
            d = chan_max_diff(arg, erg)
            if d > a.color_tol:
                failures.append({"node": nid, "category": "color", "impl": exp.get("impl"),
                                 "expected": exp.get("colorHex"), "observed": list(arg),
                                 "delta": d, "tol": a.color_tol})
            if token_rgb and not any(chan_max_diff(arg, t) <= a.color_tol for t in token_rgb):
                failures.append({"node": nid, "category": "token", "impl": exp.get("impl"),
                                 "observed": list(arg), "detail": "rendered color is not a design token"})
        # radius
        if exp.get("radius") is not None and act.get("radius") is not None:
            expected_radius = float(exp["radius"]) / design_pixel_scale
            d = abs(float(act["radius"]) - expected_radius)
            if d > a.size_tol:
                failures.append({"node": nid, "category": "radius", "impl": exp.get("impl"),
                                 "expected": expected_radius, "observed": act["radius"],
                                 "delta": round(d, 2), "tol": a.size_tol})

    # icon/asset region shape gate: bbox+color cannot see a wrong glyph drawn at the
    # right place in the right dominant color — the pixel diff's per-asset-region
    # mismatch can. AA-only residue stays ~<5%; a wrong icon is typically >30%.
    if a.diff_report and Path(a.diff_report).is_file():
        diff = json.loads(Path(a.diff_report).read_text(encoding="utf-8"))
        board_scope = Path(a.expected).resolve().parent.name
        trace_scope = Path(a.trace).resolve().parent.name
        if trace_scope != board_scope:
            print(
                f"ERROR: trace board {trace_scope!r} does not match expected board {board_scope!r}",
                file=sys.stderr,
            )
            return 2
        raw_asset_issues = diff.get("assetIssues") or []
        scoped_issues, ambiguous_nodes = scoped_asset_regions(
            raw_asset_issues, expected, trace, board_scope, a.asset_mismatch_tol
        )
        asset_scope_summary = {
            "board": board_scope,
            "inputIssueCount": len(raw_asset_issues),
            "matchedRegionCount": len(scoped_issues),
            "ambiguousNodes": ambiguous_nodes,
        }
        for issue in scoped_issues:
            mismatch = asset_pixel_mismatch(issue)
            failures.append({"node": issue.get("node"), "category": "asset_shape",
                             "board": issue.get("board"), "state": issue.get("state"),
                             "bbox": issue.get("bbox"), "impl": issue.get("widget"),
                             "role": issue.get("role"), "aliasCount": issue.get("aliasCount"),
                             "aliases": issue.get("aliases"), "observed": round(mismatch, 4),
                             "tol": a.asset_mismatch_tol,
                             "detail": "asset region pixel mismatch beyond AA floor — "
                                       "wrong/missing icon glyph or unregistered asset"})
        for node in ambiguous_nodes:
            failures.append({
                "node": node,
                "category": "asset_shape_scope",
                "tol": a.asset_mismatch_tol,
                "detail": "asset issue lacks deterministic board/bbox identity; regenerate the diff report",
            })

    by_cat = {}
    for f in failures:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    ok = len(failures) == 0
    report = {
        "ok": ok,
        "assetShapeChecked": bool(a.diff_report and Path(a.diff_report).is_file()),
        "expectedNodes": len(expected),
        "checkedNodes": checked,
        "assetIssueScope": asset_scope_summary,
        "dynamicContentExclusions": sorted(api_dynamic_nodes.intersection(expected)),
        "failureCount": len(failures),
        "byCategory": by_cat,
        "tolerances": {"bbox": a.bbox_tol, "color": a.color_tol, "size": a.size_tol},
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
