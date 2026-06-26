#!/usr/bin/env python3
"""Convert visual diff output into an ordered iFF repair plan."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import dump_json, load_json


def score(issue: dict[str, Any]) -> float:
    return float(issue.get("area") or 0) * float(issue.get("pixelMismatch") or 0)


def priority(issue: dict[str, Any], category: str) -> str:
    if category == "viewport":
        return "P0"
    mismatch = float(issue.get("pixelMismatch") or 0)
    weighted = score(issue)
    if category in {"layout_region", "asset_region"} and (mismatch > 0.10 or weighted > 50000):
        return "P0"
    if category == "text_region" and (mismatch > 0.05 or weighted > 12000):
        return "P0"
    if category == "shape_region" and float(issue.get("avgColorDelta") or 0) > 3:
        return "P1"
    if mismatch > 0.01 or weighted > 5000:
        return "P1"
    return "P2"


def issue_action(category: str) -> str:
    return {
        "viewport": "fix runtime viewport, crop, status/nav bars, density, or screenshot timing before editing widgets",
        "layout_region": "inspect the component against layout_contract; use actual_layout_trace before claiming a bbox offset",
        "asset_region": "use the exact exported asset and match bbox, fit, clipping, opacity, and z order",
        "text_region": "match text content, fontSize, weight, lineHeight, color, bbox, and runtime fixture state",
        "shape_region": "match fill, border, radius, shadow, opacity, clipping, and edge geometry",
    }.get(category, "inspect the referenced node and patch only this mismatch class")


def index_layout(layout: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    components: dict[str, dict[str, Any]] = {}
    widgets_by_node: dict[str, dict[str, Any]] = {}
    for component_name, component in layout.items():
        if not isinstance(component, dict):
            continue
        components[component_name] = component
        for role, widget in (component.get("widgets") or {}).items():
            if not isinstance(widget, dict):
                continue
            node = str(widget.get("node") or "")
            if node:
                widgets_by_node[node] = {
                    "component": component_name,
                    "role": role,
                    "widget": widget,
                }
    return components, widgets_by_node


def render_info(render_plan: dict[str, Any], node: str | None) -> dict[str, Any]:
    if not node:
        return {}
    item = (render_plan.get("nodes") or {}).get(node)
    if not isinstance(item, dict):
        return {}
    return {
        "name": item.get("name"),
        "implementation": item.get("implementation"),
        "asset": item.get("asset"),
        "widgetTraceRequired": item.get("widgetTraceRequired"),
    }


def implementation_hints(implementation_map: dict[str, Any], node: str | None, component: str | None) -> list[Any]:
    if not implementation_map:
        return []
    hints = []
    for key in (node, component):
        if key and key in implementation_map:
            value = implementation_map[key]
            if isinstance(value, list):
                hints.extend(value)
            else:
                hints.append(value)
    return hints


def actual_trace_index(actual_trace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if not actual_trace:
        return indexed
    entries = actual_trace.get("widgets") if isinstance(actual_trace, dict) else None
    if isinstance(entries, dict):
        iterable = entries.values()
    elif isinstance(entries, list):
        iterable = entries
    else:
        iterable = []
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        for key in ("node", "designNode", "key", "role"):
            value = entry.get(key)
            if value:
                indexed[str(value)] = entry
    return indexed


def bbox_delta(expected: Any, actual: Any) -> dict[str, float] | None:
    if not (isinstance(expected, list) and isinstance(actual, list) and len(expected) == 4 and len(actual) == 4):
        return None
    labels = ("dx", "dy", "dw", "dh")
    return {label: round(float(a) - float(e), 3) for label, e, a in zip(labels, expected, actual)}


def structural_delta(widget: dict[str, Any] | None, trace: dict[str, Any] | None) -> dict[str, Any]:
    if not widget or not trace:
        return {}
    delta: dict[str, Any] = {}
    box = bbox_delta(widget.get("bbox"), trace.get("bbox") or trace.get("rect"))
    if box:
        delta["bboxDelta"] = box
    for key in ("text", "fontSize", "fontWeight", "lineHeight", "color", "radius", "asset"):
        if key in widget or key in trace:
            expected = widget.get(key)
            actual = trace.get(key)
            if expected != actual:
                delta[key] = {"expected": expected, "actual": actual}
    return delta


def diagnostic_hint(action: dict[str, Any]) -> dict[str, str]:
    category = str(action.get("category") or "")
    has_trace = bool(action.get("actualTrace"))
    has_delta = bool(action.get("structuralDelta"))
    if category == "viewport":
        return {
            "kind": "viewport_mismatch",
            "confidence": "high",
            "note": "Screenshot dimensions or capture setup must be fixed before widget changes.",
        }
    if category == "layout_region" and not has_trace:
        return {
            "kind": "component_region_pixels",
            "confidence": "medium",
            "note": "The component region differs by pixels, but runtime widget rects are missing; this is not proof of bbox offset.",
        }
    if category == "layout_region" and has_delta:
        return {
            "kind": "component_layout_delta",
            "confidence": "high",
            "note": "Runtime trace reports structural deltas for this component or node.",
        }
    if category == "text_region" and not has_trace:
        return {
            "kind": "text_region_pixels",
            "confidence": "medium",
            "note": "Text pixels differ; actual font metrics are unavailable without actual_layout_trace.",
        }
    if category == "shape_region":
        return {
            "kind": "shape_or_antialias_pixels",
            "confidence": "medium",
            "note": "Shape pixels differ; inspect fill, radius, border, shadow, clipping, and antialias-sensitive edges.",
        }
    if category == "asset_region":
        return {
            "kind": "asset_region_pixels",
            "confidence": "high" if has_trace else "medium",
            "note": "Asset region differs; verify exact exported asset, fit, clip, opacity, and z order.",
        }
    return {
        "kind": "pixel_region",
        "confidence": "low",
        "note": "Use the observed region and design contract to narrow the mismatch.",
    }


def alias_entry(action: dict[str, Any]) -> dict[str, Any]:
    render = ((action.get("expected") or {}).get("render") or {})
    return {
        "node": action.get("node"),
        "role": action.get("role"),
        "renderName": render.get("name"),
        "implementation": render.get("implementation"),
    }


def canonical_rank(action: dict[str, Any]) -> tuple[int, int, int]:
    node = str(action.get("node") or "")
    role = str(action.get("role") or "")
    render = ((action.get("expected") or {}).get("render") or {})
    return (
        1 if node.startswith("figma_json.") else 0,
        1 if role.startswith("figma_json_") else 0,
        0 if render.get("name") else 1,
    )


def rounded_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not (isinstance(value, list) and len(value) == 4):
        return None
    try:
        return tuple(round(float(item), 3) for item in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def dedupe_key(action: dict[str, Any]) -> tuple[Any, ...]:
    expected = action.get("expected") if isinstance(action.get("expected"), dict) else {}
    widget = expected.get("widget") if isinstance(expected.get("widget"), dict) else {}
    bbox = rounded_bbox(widget.get("bbox")) or rounded_bbox(expected.get("componentBbox"))
    observed = action.get("observed") if isinstance(action.get("observed"), dict) else {}
    return (
        action.get("priority"),
        action.get("category"),
        action.get("component"),
        widget.get("widget"),
        bbox,
        round(float(observed.get("area") or 0), 3),
        round(float(observed.get("pixelMismatch") or 0), 6),
        round(float(action.get("score") or 0), 3),
    )


def dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for action in actions:
        grouped.setdefault(dedupe_key(action), []).append(action)

    deduped: list[dict[str, Any]] = []
    for items in grouped.values():
        canonical = sorted(items, key=canonical_rank)[0].copy()
        aliases = [alias_entry(item) for item in items]
        canonical["sourceNodes"] = aliases
        canonical["aliasCount"] = len(aliases)
        canonical["diagnostic"] = diagnostic_hint(canonical)
        deduped.append(canonical)

    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(deduped, key=lambda item: (priority_rank.get(item["priority"], 9), -float(item.get("score") or 0)))


def category_counts(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for action in actions:
        key = (str(action.get("priority")), str(action.get("category")))
        counts[key] = counts.get(key, 0) + 1
    return [
        {"priority": priority, "category": category, "count": count}
        for (priority, category), count in sorted(counts.items())
    ]


def make_action(
    issue: dict[str, Any],
    category: str,
    components: dict[str, dict[str, Any]],
    widgets_by_node: dict[str, dict[str, Any]],
    render_plan: dict[str, Any],
    implementation_map: dict[str, Any],
    trace_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    node = issue.get("node")
    role = issue.get("role")
    component_name = node if node in components else None
    widget = None
    if not component_name and node:
        match = widgets_by_node.get(str(node))
        if match:
            component_name = match["component"]
            widget = match["widget"]
            role = role or match["role"]
    component = components.get(str(component_name)) if component_name else None
    design_node = str(widget.get("node")) if isinstance(widget, dict) and widget.get("node") else str(node or "")
    trace = trace_by_key.get(design_node) or trace_by_key.get(str(role or "")) or trace_by_key.get(str(component_name or ""))
    action = {
        "priority": priority(issue, category),
        "category": category,
        "component": component_name,
        "node": node,
        "role": role,
        "score": round(score(issue), 3),
        "observed": {
            "pixelMismatch": issue.get("pixelMismatch"),
            "avgColorDelta": issue.get("avgColorDelta"),
            "maxColorDelta": issue.get("maxColorDelta"),
            "area": issue.get("area"),
        },
        "expected": {
            "componentKind": component.get("kind") if component else None,
            "componentBbox": component.get("bbox") if component else None,
            "widget": widget,
            "render": render_info(render_plan, design_node),
        },
        "actualTrace": trace or None,
        "structuralDelta": structural_delta(widget, trace),
        "implementationHints": implementation_hints(implementation_map, design_node, str(component_name) if component_name else None),
        "repairAction": issue_action(category),
    }
    return action


def build_actions(
    diff: dict[str, Any],
    layout: dict[str, Any],
    render_plan: dict[str, Any],
    implementation_map: dict[str, Any],
    actual_trace: dict[str, Any],
) -> list[dict[str, Any]]:
    components, widgets_by_node = index_layout(layout)
    trace_by_key = actual_trace_index(actual_trace)
    actions: list[dict[str, Any]] = []
    for issue in diff.get("viewportIssues") or []:
        actions.append(
            {
                "priority": "P0",
                "category": "viewport",
                "component": None,
                "node": None,
                "role": None,
                "score": 10**12,
                "observed": issue,
                "expected": None,
                "actualTrace": None,
                "structuralDelta": {},
                "implementationHints": [],
                "repairAction": issue_action("viewport"),
            }
        )
    for category, key in (
        ("layout_region", "bboxIssues"),
        ("asset_region", "assetIssues"),
        ("text_region", "textIssues"),
        ("shape_region", "shapeIssues"),
    ):
        for issue in diff.get(key) or []:
            if isinstance(issue, dict):
                actions.append(make_action(issue, category, components, widgets_by_node, render_plan, implementation_map, trace_by_key))
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(actions, key=lambda item: (priority_rank.get(item["priority"], 9), -float(item.get("score") or 0)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--render-plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--implementation-map")
    parser.add_argument("--actual-trace")
    args = parser.parse_args()

    diff = load_json(args.diff)
    layout = load_json(args.layout)
    render_plan = load_json(args.render_plan)
    implementation_map = load_json(args.implementation_map) if args.implementation_map and Path(args.implementation_map).is_file() else {}
    actual_trace = load_json(args.actual_trace) if args.actual_trace and Path(args.actual_trace).is_file() else {}
    raw_actions = build_actions(diff, layout, render_plan, implementation_map, actual_trace)
    actions = dedupe_actions(raw_actions)
    top = actions[0] if actions else None
    raw_p0_count = sum(1 for item in raw_actions if item.get("priority") == "P0")
    raw_p1_count = sum(1 for item in raw_actions if item.get("priority") == "P1")
    duplicate_alias_count = sum(max(0, int(item.get("aliasCount") or 1) - 1) for item in actions)
    report = {
        "repairPlanVersion": 2,
        "inputs": {
            "diff": args.diff,
            "layout": args.layout,
            "renderPlan": args.render_plan,
            "implementationMap": args.implementation_map,
            "actualTrace": args.actual_trace,
        },
        "summary": {
            "pass": diff.get("pass"),
            "ssim": diff.get("ssim"),
            "pixelMismatch": diff.get("pixelMismatch"),
            "rawActionCount": len(raw_actions),
            "actionCount": len(actions),
            "rawP0Count": raw_p0_count,
            "p0Count": sum(1 for item in actions if item.get("priority") == "P0"),
            "rawP1Count": raw_p1_count,
            "p1Count": sum(1 for item in actions if item.get("priority") == "P1"),
            "duplicateAliasCount": duplicate_alias_count,
            "hasActualTrace": bool(actual_trace),
            "hasImplementationMap": bool(implementation_map),
        },
        "diagnosticWarnings": [
            *([] if actual_trace else ["actual_layout_trace missing: component_region pixels cannot prove real widget bbox/font deltas"]),
            *([] if implementation_map else ["implementation_map missing: repair plan cannot point to source files or widget keys"]),
            *([] if not duplicate_alias_count else [f"collapsed {duplicate_alias_count} duplicate design-node aliases"]),
        ],
        "categoryCounts": category_counts(actions),
        "repairOrder": [
            "viewport",
            "layout_region",
            "asset_region",
            "text_region",
            "shape_region",
            "fine_pixels",
        ],
        "stopGate": "Patch only the first unresolved P0 category, then rerun capture_runtime_screenshot, visual_diff, and make_repair_plan.",
        "topAction": top,
        "actions": actions,
    }
    dump_json(report, args.out)
    p0_count = report["summary"]["p0Count"]
    print(f"repair_plan raw_actions={len(raw_actions)} actions={len(actions)} p0={p0_count} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
