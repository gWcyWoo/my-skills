#!/usr/bin/env python3
"""Convert visual diff output into an ordered iFF repair plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import dump_json, load_json
from layout_trace_contract import LayoutTraceContractError, actual_layout_trace_nodes


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
        "text": item.get("text"),
        "fontSize": item.get("fontSize"),
        "fontWeight": item.get("weight"),
        "lineHeight": item.get("lineHeight"),
        "letterSpacing": item.get("letterSpacing"),
        "textRuns": item.get("textRuns"),
        "fills": item.get("fills"),
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
    for mapping in implementation_map.get("nodeMappings") or []:
        if not isinstance(mapping, dict) or not node or str(mapping.get("node") or "") != str(node):
            continue
        bbox = mapping.get("bbox")
        render_mode = mapping.get("renderMode") or mapping.get("positioning") or mapping.get("layoutMode")
        if (
            not isinstance(mapping.get("implementation"), str)
            or not mapping.get("implementation")
            or not isinstance(mapping.get("widget"), str)
            or not mapping.get("widget")
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or render_mode not in {"absolute_positioned", "absolute_bbox", "render_plan_bbox", "coordinate_canvas"}
        ):
            continue
        hint = mapping.copy()
        hint["generatedValueKey"] = f"iff:{node}"
        hint["sourceBindingKind"] = "implementation_map.nodeMappings"
        hints.append(hint)
    return hints


def actual_trace_index(actual_trace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if not actual_trace:
        return indexed
    try:
        entries = actual_layout_trace_nodes(actual_trace)
    except LayoutTraceContractError:
        return indexed
    for node_id, entry in entries.items():
        if not isinstance(node_id, str) or not node_id or not isinstance(entry, dict):
            continue
        indexed[node_id] = entry
        for key in ("node", "designNode", "key", "role"):
            value = entry.get(key)
            if value:
                indexed[str(value)] = entry
    return indexed


def bbox_delta(expected: Any, actual: Any) -> dict[str, float] | None:
    if not (isinstance(expected, list) and isinstance(actual, list) and len(expected) == 4 and len(actual) == 4):
        return None
    labels = ("dx", "dy", "dw", "dh")
    delta = {label: round(float(a) - float(e), 3) for label, e, a in zip(labels, expected, actual)}
    return delta if any(value != 0 for value in delta.values()) else None


def structural_delta(widget: dict[str, Any] | None, trace: dict[str, Any] | None) -> dict[str, Any]:
    if not widget or not trace:
        return {}
    delta: dict[str, Any] = {}
    box = bbox_delta(widget.get("bbox"), trace.get("bbox") or trace.get("rect"))
    if box:
        delta["bboxDelta"] = box
    for key in ("text", "fontSize", "fontWeight", "lineHeight", "color", "radius", "asset"):
        if key in widget and key in trace:
            expected = widget.get(key)
            actual = trace.get(key)
            if expected is None or actual is None:
                continue
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


def deterministic_source_binding(action: dict[str, Any]) -> bool:
    hints = action.get("implementationHints")
    return isinstance(hints, (list, dict)) and bool(hints)


def source_binding_fingerprint(action: dict[str, Any] | None) -> str | None:
    if action is None or not deterministic_source_binding(action):
        return None
    encoded = json.dumps(
        action.get("implementationHints"),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bbox_intersection_area(left: Any, right: Any) -> float:
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != 4 or len(right) != 4:
        return 0.0
    lx, ly, lw, lh = (float(value) for value in left)
    rx, ry, rw, rh = (float(value) for value in right)
    width = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
    height = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
    return width * height


def route_composite_asset_action(
    action: dict[str, Any], overlapping_nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    routed = action.copy()
    source_backed = [item for item in overlapping_nodes if deterministic_source_binding(item)]
    explicit_isolation = any(
        isinstance(item, dict) and item.get("isolatedAsset") is True
        for item in (routed.get("implementationHints") or [])
    )
    routed["assetIsolation"] = {
        "isolated": not overlapping_nodes,
        "explicitIsolationEvidence": explicit_isolation,
        "overlappingNodeCount": len(overlapping_nodes),
        "sourceBackedOverlapCount": len(source_backed),
    }
    if not overlapping_nodes or explicit_isolation:
        routed["assetClassification"] = "isolated_source_bound"
        return routed
    if not source_backed:
        routed["assetClassification"] = "composite_without_source_bound_child"
        return routed
    selected = sorted(
        source_backed,
        key=lambda item: (
            0 if item.get("actualTrace") else 1,
            float(item.get("area") or 0),
            str(item.get("node") or ""),
        ),
    )[0]
    routed["sourceIssueNode"] = routed.get("node")
    routed["node"] = selected.get("node")
    routed["designNode"] = selected.get("node")
    routed["role"] = selected.get("role")
    routed["component"] = selected.get("component")
    routed["actualTrace"] = selected.get("actualTrace")
    routed["implementationHints"] = selected.get("implementationHints")
    routed["expected"] = {**(routed.get("expected") or {}), "widget": selected.get("widget")}
    routed["assetClassification"] = "overlap_routed_source_child"
    routed["repairAction"] = "repair the routed source-bound overlapping child, not the composite asset region"
    return routed


def repair_eligibility(action: dict[str, Any]) -> dict[str, Any]:
    category = str(action.get("category") or "")
    has_trace = bool(action.get("actualTrace"))
    has_implementation = deterministic_source_binding(action)
    diagnostic = action.get("diagnostic") if isinstance(action.get("diagnostic"), dict) else {}
    diagnostic_note = str(diagnostic.get("note") or "")
    disclaims_bbox_offset = "not proof of bbox offset" in diagnostic_note.lower()
    reasons: list[str] = []
    if disclaims_bbox_offset:
        reasons.append("diagnostic_disclaims_bbox_offset")
    if (
        category == "text_region"
        and diagnostic.get("kind") == "pixel_region"
        and diagnostic.get("confidence") == "low"
        and not action.get("structuralDelta")
    ):
        reasons.append("text_pixel_residual_has_no_structural_delta")
    if category in {"asset_region", "text_region", "layout_region", "shape_region"} and not has_implementation:
        reasons.append("missing_deterministic_source_binding")
    isolation = action.get("assetIsolation") if isinstance(action.get("assetIsolation"), dict) else {}
    observed = action.get("observed") if isinstance(action.get("observed"), dict) else {}
    expected = action.get("expected") if isinstance(action.get("expected"), dict) else {}
    expected_widget = expected.get("widget") if isinstance(expected.get("widget"), dict) else {}
    if (
        action.get("assetClassification") == "overlap_routed_source_child"
        and observed.get("bbox") != expected_widget.get("bbox")
    ):
        reasons.append("composite_parent_metrics_are_not_child_local_evidence")
    if (
        category == "asset_region"
        and isolation.get("isolated") is False
        and isolation.get("explicitIsolationEvidence") is not True
        and action.get("assetClassification") != "overlap_routed_source_child"
    ):
        reasons.append("composite_asset_lacks_isolation_or_source_evidence")
    if category == "layout_region" and not has_trace:
        reasons.append("missing_runtime_trace")
    elif not has_trace and not has_implementation:
        reasons.append("missing_runtime_or_implementation_evidence")
    return {
        "schemaVersion": 2,
        "eligible": not reasons,
        "reasons": reasons,
        "evidence": {
            "hasActualTrace": has_trace,
            "hasImplementationHints": has_implementation,
            "sourceBindingFingerprint": source_binding_fingerprint(action),
            "diagnosticConfidence": diagnostic.get("confidence"),
            "diagnosticDisclaimsBboxOffset": disclaims_bbox_offset,
        },
    }


def annotate_actionability(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for action in actions:
        item = action.copy()
        item["repairEligibility"] = repair_eligibility(item)
        annotated.append(item)
    return annotated


def consumed_action_fingerprints(state_path: str | None) -> set[str]:
    if not state_path or not Path(state_path).is_file():
        return set()
    state = load_json(state_path)
    attempts = [*(state.get("attemptHistory") or []), state.get("validAttempt")]
    fingerprints = [
        str(proof["topActionFingerprint"])
        for attempt in attempts
        if isinstance(attempt, dict)
        for proof in [attempt.get("actionabilityProof")]
        if isinstance(proof, dict) and proof.get("topActionFingerprint")
    ]
    return {
        fingerprint
        for fingerprint in set(fingerprints)
        if fingerprints.count(fingerprint) >= 3
    }


def select_top_action(
    actions: list[dict[str, Any]], excluded_fingerprints: set[str] | None = None
) -> dict[str, Any] | None:
    excluded = excluded_fingerprints or set()
    return next(
        (
            action
            for action in actions
            if isinstance(action.get("repairEligibility"), dict)
            and action["repairEligibility"].get("schemaVersion") == 2
            and action["repairEligibility"].get("eligible") is True
            and actionability_fingerprint(action) not in excluded
        ),
        None,
    )


def actionability_fingerprint(action: dict[str, Any] | None) -> str | None:
    if action is None:
        return None
    payload = {
        "category": action.get("category"),
        "node": action.get("node"),
        "sourceIssueNode": action.get("sourceIssueNode"),
        "component": action.get("component"),
        "role": action.get("role"),
        "assetClassification": action.get("assetClassification"),
        "repairAction": action.get("repairAction"),
        "sourceBindingFingerprint": source_binding_fingerprint(action),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_actionability_proof(
    actions: list[dict[str, Any]], top_action: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "eligible": top_action is not None,
        "eligibleActionCount": sum(
            1
            for action in actions
            if isinstance(action.get("repairEligibility"), dict)
            and action["repairEligibility"].get("eligible") is True
        ),
        "topActionFingerprint": actionability_fingerprint(top_action),
        "sourceBacked": deterministic_source_binding(top_action or {}),
        "sourceBindingFingerprint": source_binding_fingerprint(top_action),
        "topActionNode": (top_action or {}).get("node"),
        "sourceIssueNode": (top_action or {}).get("sourceIssueNode"),
    }


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
    render = render_info(render_plan, design_node)
    expected_node = {**(widget or {}), **render}
    action = {
        "priority": priority(issue, category),
        "category": category,
        "component": component_name,
        "node": node,
        "role": role,
        "score": round(score(issue), 3),
        "observed": {
            "bbox": issue.get("bbox"),
            "pixelMismatch": issue.get("pixelMismatch"),
            "avgColorDelta": issue.get("avgColorDelta"),
            "maxColorDelta": issue.get("maxColorDelta"),
            "area": issue.get("area"),
        },
        "expected": {
            "componentKind": component.get("kind") if component else None,
            "componentBbox": component.get("bbox") if component else None,
            "widget": widget,
            "render": render,
        },
        "actualTrace": trace or None,
        "structuralDelta": structural_delta(expected_node, trace),
        "implementationHints": implementation_hints(implementation_map, design_node, str(component_name) if component_name else None),
        "repairAction": issue_action(category),
    }
    if category == "asset_region":
        issue_bbox = issue.get("bbox")
        overlapping_nodes: list[dict[str, Any]] = []
        for candidate_node, match in widgets_by_node.items():
            if str(candidate_node) == design_node:
                continue
            candidate_widget = match.get("widget") if isinstance(match, dict) else None
            candidate_bbox = candidate_widget.get("bbox") if isinstance(candidate_widget, dict) else None
            overlap_area = bbox_intersection_area(issue_bbox, candidate_bbox)
            if overlap_area <= 0:
                continue
            candidate_component = str(match.get("component") or "")
            overlapping_nodes.append(
                {
                    "node": str(candidate_node),
                    "role": match.get("role"),
                    "component": candidate_component or None,
                    "widget": candidate_widget,
                    "actualTrace": trace_by_key.get(str(candidate_node))
                    or trace_by_key.get(str(match.get("role") or "")),
                    "implementationHints": implementation_hints(
                        implementation_map,
                        str(candidate_node),
                        candidate_component or None,
                    ),
                    "area": float(candidate_bbox[2]) * float(candidate_bbox[3]),
                }
            )
        overlapping_node_ids = {str(item.get("node") or "") for item in overlapping_nodes}
        for mapping in implementation_map.get("nodeMappings") or []:
            if not isinstance(mapping, dict):
                continue
            candidate_node = str(mapping.get("node") or "")
            candidate_bbox = mapping.get("bbox")
            if not candidate_node or candidate_node == design_node or candidate_node in overlapping_node_ids:
                continue
            overlap_area = bbox_intersection_area(issue_bbox, candidate_bbox)
            if overlap_area <= 0:
                continue
            try:
                candidate_area = float(candidate_bbox[2]) * float(candidate_bbox[3])
            except (IndexError, TypeError, ValueError):
                continue
            match = widgets_by_node.get(candidate_node) or {}
            candidate_widget = match.get("widget") or {"node": candidate_node, "bbox": candidate_bbox}
            candidate_component = str(match.get("component") or "")
            overlapping_nodes.append(
                {
                    "node": candidate_node,
                    "role": match.get("role"),
                    "component": candidate_component or None,
                    "widget": candidate_widget,
                    "actualTrace": trace_by_key.get(candidate_node),
                    "implementationHints": implementation_hints(
                        implementation_map,
                        candidate_node,
                        candidate_component or None,
                    ),
                    "area": candidate_area,
                }
            )
        action = route_composite_asset_action(action, overlapping_nodes)
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
    parser.add_argument("--top-out", help="small model-facing digest (summary + topAction + first actions of the "
                                          "top P0 category); the full plan can reach 177KB and must stay "
                                          "script-consumed")
    parser.add_argument("--top-actions", type=int, default=8, help="how many actions the digest carries")
    parser.add_argument("--implementation-map")
    parser.add_argument("--actual-trace")
    parser.add_argument("--repair-budget-state")
    parser.add_argument(
        "--require-actual-trace",
        action="store_true",
        help="fail before writing a repair plan unless actual-trace contains at least one indexed widget",
    )
    args = parser.parse_args()

    diff = load_json(args.diff)
    layout = load_json(args.layout)
    render_plan = load_json(args.render_plan)
    implementation_map = load_json(args.implementation_map) if args.implementation_map and Path(args.implementation_map).is_file() else {}
    actual_trace = load_json(args.actual_trace) if args.actual_trace and Path(args.actual_trace).is_file() else {}
    has_actual_trace = bool(actual_trace_index(actual_trace))
    if args.require_actual_trace and not has_actual_trace:
        raise SystemExit(
            "ERROR: --require-actual-trace needs an existing actual_layout_trace.json "
            "matching the canonical shape: non-empty pageType and non-empty top-level nodes object"
        )
    raw_actions = build_actions(diff, layout, render_plan, implementation_map, actual_trace)
    actions = annotate_actionability(dedupe_actions(raw_actions))
    excluded_fingerprints = consumed_action_fingerprints(args.repair_budget_state)
    top = select_top_action(actions, excluded_fingerprints)
    actionability = build_actionability_proof(actions, top)
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
        "provenance": {
            "board": Path(args.layout).resolve().parent.name,
            "diffSha256": file_sha256(args.diff),
            "assetIssueScope": diff.get("assetIssueScope"),
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
            "hasActualTrace": has_actual_trace,
            "hasImplementationMap": bool(implementation_map),
            "eligibleActionCount": actionability["eligibleActionCount"],
            "repairEligible": actionability["eligible"],
        },
        "diagnosticWarnings": [
            *([] if has_actual_trace else ["actual_layout_trace missing: component_region pixels cannot prove real widget bbox/font deltas"]),
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
        "actionability": actionability,
        "topAction": top,
        "actions": actions,
    }
    dump_json(report, args.out)
    if args.top_out:
        top_category = (top or {}).get("category")
        same_category = [a for a in actions if a.get("category") == top_category][: args.top_actions]
        dump_json(
            {
                "summary": report["summary"],
                "diagnosticWarnings": report["diagnosticWarnings"],
                "categoryCounts": report["categoryCounts"],
                "stopGate": report["stopGate"],
                "actionability": actionability,
                "topAction": top,
                "topCategoryActions": same_category,
                "fullPlan": str(Path(args.out).resolve()),
            },
            args.top_out,
        )
    p0_count = report["summary"]["p0Count"]
    print(f"repair_plan raw_actions={len(raw_actions)} actions={len(actions)} p0={p0_count} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
