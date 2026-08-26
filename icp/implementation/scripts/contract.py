#!/usr/bin/env python3
"""Step 2: 接口契约提取 — component-binding.json → api-contract.json

从 Stage 2 产物提取 API 端点、组件参数、交互原子列表。

用法:
    python3 contract.py --binding <path> --output <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def extract_interactions(binding: dict) -> list[dict]:
    interactions = []
    for api in binding.get("apis", []):
        interactions.append({
            "type": "api_call",
            "trigger": api.get("trigger", ""),
            "endpoint": api.get("endpoint", ""),
        })
    for comp in binding.get("components", []):
        params = comp.get("params", [])
        if "navController" in params:
            interactions.append({
                "type": "navigation",
                "component": comp["component_name"],
                "trigger": "screen_entry",
            })
        for p in params:
            if p.startswith("on") and p[2:3].isupper():
                interactions.append({
                    "type": "callback",
                    "component": comp["component_name"],
                    "param": p,
                    "trigger": p,
                })
    return interactions


def build_contract(binding: dict) -> dict:
    platform = binding.get("platform", {})
    apis = binding.get("apis", [])
    components = binding.get("components", [])

    type_dist = {}
    for c in components:
        ct = c.get("component_type", "unknown")
        type_dist[ct] = type_dist.get(ct, 0) + 1

    component_specs = []
    for c in components:
        component_specs.append({
            "name": c["component_name"],
            "group": c.get("group_name", ""),
            "type": c.get("component_type", "new"),
            "source_path": c.get("source_path"),
            "params": c.get("params", []),
            "affected": c.get("affected"),
        })

    raw_interactions = binding.get("interactions")
    if isinstance(raw_interactions, list) and raw_interactions:
        interactions = raw_interactions
    else:
        interactions = extract_interactions(binding)

    contract = {
        "platform": platform,
        "apis": apis,
        "components": component_specs,
        "interactions": interactions,
        "metrics": {
            "contract_apis": len(apis),
            "contract_interactions": len(interactions),
            "contract_components": len(components),
            "contract_component_types": type_dist,
        },
    }
    return contract


def main():
    parser = argparse.ArgumentParser(description="Step 2: 接口契约提取")
    parser.add_argument("--binding", required=True, help="component-binding.json path")
    parser.add_argument("--output", required=True, help="output api-contract.json path")
    args = parser.parse_args()

    with open(args.binding) as f:
        binding = json.load(f)

    comps = binding.get("components")
    if not isinstance(comps, list) or len(comps) == 0:
        print(json.dumps({"ok": False, "error": "stage2_incomplete",
              "detail": "component-binding.json has no components[] — Stage 2 未完成"}, ensure_ascii=False))
        sys.exit(1)

    contract = build_contract(binding)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(contract, f, indent=2, ensure_ascii=False)

    m = contract["metrics"]
    print(json.dumps({"ok": True, **m}, ensure_ascii=False))


if __name__ == "__main__":
    main()
