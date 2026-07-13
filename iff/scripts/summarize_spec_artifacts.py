#!/usr/bin/env python3
"""Deterministic digest of every spec_dir artifact — the worker model READS THIS
instead of the raw multi-hundred-KB JSONs.

Measured on real runs: scene.json 72-260KB, render_plan.json 67-227KB,
layout_contract.json 40-100KB, oas.json ~92KB, repair_plan.json up to 177KB —
mandating full reads of those burned 100-250k tokens per page while the model
only ever needed counts, ids and schema shape (the visible layer is generated
by generate_canvas.py, not hand-drawn from node data). Big JSONs stay
script-consumed; the model windows into them by node id only when a specific
node's data is required.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import dump_json, load_json


def _safe(path: Path):
    try:
        return load_json(path)
    except FileNotFoundError:
        return None


def _meta(path: Path, doc) -> dict:
    return {
        "exists": doc is not None,
        "bytes": path.stat().st_size if path.is_file() else 0,
        "topLevelKeys": sorted(doc.keys()) if isinstance(doc, dict) else None,
    }


def build_digest(spec_dir: Path) -> dict:
    digest: dict = {"specDir": str(spec_dir), "artifacts": {}}

    def track(name: str):
        path = spec_dir / name
        doc = _safe(path)
        digest["artifacts"][name] = _meta(path, doc)
        return doc

    classification = track("design_classification.json")
    if classification:
        digest["classification"] = classification  # tiny — embed whole

    scene = track("scene.json")
    if scene:
        nodes = scene.get("nodes") or []
        digest["scene"] = {
            "sourceSchema": scene.get("sourceSchema"),
            "artboard": scene.get("artboard"),
            "nodeCount": len(nodes),
            "textNodes": sum(1 for n in nodes if n.get("text")),
            "assetNodes": sum(1 for n in nodes if n.get("asset")),
            "exportableNodes": sum(1 for n in nodes if n.get("exportable")),
            "hiddenNodes": sum(1 for n in nodes if n.get("effectiveVisible") is False),
        }

    groups = track("groups.json")
    if groups:
        by_kind: dict[str, int] = {}
        for g in groups.get("groups") or []:
            by_kind[g.get("kind") or "region"] = by_kind.get(g.get("kind") or "region", 0) + 1
        digest["groups"] = {"count": sum(by_kind.values()), "byKind": by_kind}

    tokens = track("tokens.json")
    if isinstance(tokens, dict):
        digest["tokens"] = {"count": sum(len(v) if isinstance(v, (list, dict)) else 1 for v in tokens.values())}

    assets = track("assets_manifest.json")
    if isinstance(assets, dict):
        digest["assets"] = {"count": len(assets)}

    layout = track("layout_contract.json")
    if isinstance(layout, dict):
        digest["layout"] = {
            "components": len(layout),
            "widgets": sum(len(c.get("widgets") or {}) for c in layout.values() if isinstance(c, dict)),
        }

    plan = track("render_plan.json")
    if isinstance(plan, dict):
        by_impl: dict[str, int] = {}
        required = 0
        for item in (plan.get("nodes") or {}).values():
            impl = item.get("implementation") or "unknown"
            by_impl[impl] = by_impl.get(impl, 0) + 1
            if item.get("required"):
                required += 1
        digest["renderPlan"] = {
            "nodeCount": len(plan.get("nodes") or {}),
            "requiredVisibleNodeCount": required,
            "byImplementation": dict(sorted(by_impl.items())),
            "sharedComponents": plan.get("sharedComponents") or [],
        }

    contract = track("interaction_contract.json")
    if isinstance(contract, dict):
        rules = contract.get("rules") or contract.get("interactions") or []
        digest["interaction"] = {"ruleCount": len(rules) if isinstance(rules, list) else None}

    test_plan = track("interaction_test_plan.json")
    if isinstance(test_plan, dict):
        cases = test_plan.get("cases") or test_plan.get("tests") or []
        digest["interactionTestPlan"] = {
            "caseCount": len(cases) if isinstance(cases, list) else None,
            "caseIds": sorted({c.get("id") for c in cases if isinstance(c, dict) and c.get("id")})
            if isinstance(cases, list) else None,
        }

    api = track("api_contract.json")
    if isinstance(api, dict):
        endpoints = api.get("endpoints") or []
        digest["api"] = {
            "endpointCount": len(endpoints) if isinstance(endpoints, list) else None,
            "endpoints": [e.get("path") or e.get("name") for e in endpoints if isinstance(e, dict)]
            if isinstance(endpoints, list) else None,
        }

    shared = track("shared_components.local.json")
    if isinstance(shared, dict):
        digest["sharedComponents"] = [
            {k: c.get(k) for k in ("name", "kind", "status", "widget_path", "group_node", "bbox")}
            for c in shared.get("components") or []
        ]

    for name in ("design_artifacts_report.json", "component_manifest.json", "data_slot_bindings.json"):
        track(name)
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec-dir", required=True)
    parser.add_argument("--out", help="default <spec-dir>/artifact_digest.json")
    args = parser.parse_args()

    spec_dir = Path(args.spec_dir).expanduser().resolve()
    digest = build_digest(spec_dir)
    out = args.out or str(spec_dir / "artifact_digest.json")
    dump_json(digest, out)
    print(f"ok artifact digest -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
