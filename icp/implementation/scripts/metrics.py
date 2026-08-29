#!/usr/bin/env python3
"""汇总 Stage 3 全流程指标 → stage3-metrics.json

读取各步骤产出文件,合并为一份结构化指标,供跨页面对比。

用法:
    python3 metrics.py --work-dir <page-work-dir> --title <page-title> --platform <platform> --output <path>

各步骤产出文件 (在 --work-dir 下查找):
    layout-blueprint.json   Step 1
    api-contract.json       Step 2
    probe-result.json       Step 5
    struct-diff.json        Step 6
    visual-diff.json        Step 7 (可选,模型产出)
    attribution-ledger.json Step 8 (可选)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def extract_step1(work_dir: Path) -> dict:
    data = read_json(work_dir / "layout-blueprint.json")
    if not data:
        return {"status": "missing"}
    return data.get("metrics", {})


def extract_step2(work_dir: Path) -> dict:
    data = read_json(work_dir / "api-contract.json")
    if not data:
        return {"status": "missing"}
    return data.get("metrics", {})


def extract_step5(work_dir: Path) -> dict:
    data = read_json(work_dir / "probe-result.json")
    if not data:
        return {"status": "missing"}
    return {
        "render_ok": data.get("render_ok"),
        "render_time_ms": data.get("render_time_ms"),
        "render_view_nodes": data.get("render_view_nodes"),
        "timings": data.get("timings", {}),
    }


def extract_step6(work_dir: Path) -> dict:
    data = read_json(work_dir / "struct-diff.json")
    if not data:
        return {"status": "missing"}
    result = data.get("metrics", {})
    gate = data.get("gate")
    if gate:
        result["gate"] = gate
    return result


def extract_step7(work_dir: Path) -> dict:
    data = read_json(work_dir / "visual-diff.json")
    if not data:
        return {"status": "not_run"}
    return {
        "visual_pass": data.get("pass"),
        "visual_issues": data.get("issues_remaining", []),
    }


def extract_step8(work_dir: Path) -> dict:
    data = read_json(work_dir / "attribution-ledger.json")
    if data is None:
        return {"status": "not_run"}
    if not data:
        return {"status": "no_fixes_needed"}
    breakdown = {}
    for e in data:
        attr = e.get("attribution", "unknown")
        breakdown[attr] = breakdown.get(attr, 0) + 1
    unique_rounds = len(set(e.get("round", 0) for e in data))
    return {
        "total_rounds": unique_rounds,
        "attributions": breakdown,
    }


def extract_step9(work_dir: Path) -> dict:
    data = read_json(work_dir / "behavior-result.json")
    if not data:
        return {"status": "not_run"}
    pos = data.get("positive") or {}
    neg = data.get("negative") or {}
    qc = data.get("quality_check") or {}
    behavior_total = data.get("behavior_total", 0)
    positive_total = pos.get("total", 0)
    contract = read_json(work_dir / "api-contract.json")
    contract_interactions = contract.get("metrics", {}).get("contract_interactions", 0) if contract else 0
    mock_violations = data.get("mock_violations") or []
    result = {
        "behavior_total": behavior_total,
        "positive_total": positive_total,
        "positive_passed": pos.get("passed", 0),
        "negative_total": neg.get("total", 0),
        "negative_passed": neg.get("passed", 0),
        "mock_violations": len(mock_violations),
        "quality_rewrites": qc.get("rewrites", 0),
    }
    result["interaction_gap"] = max(0, contract_interactions - positive_total) if contract_interactions > 0 else 0
    return result


def build_metrics(work_dir: Path, title: str, platform: str) -> dict:
    return {
        "title": title,
        "platform": platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step1_blueprint": extract_step1(work_dir),
        "step2_contract": extract_step2(work_dir),
        "step5_probe": extract_step5(work_dir),
        "step6_struct_diff": extract_step6(work_dir),
        "step7_visual_diff": extract_step7(work_dir),
        "step8_attribution": extract_step8(work_dir),
        "step9_behavior": extract_step9(work_dir),
    }


def main():
    parser = argparse.ArgumentParser(description="Stage 3 指标汇总")
    parser.add_argument("--work-dir", required=True, help="page work directory")
    parser.add_argument("--title", required=True, help="page title")
    parser.add_argument("--platform", required=True, help="target platform")
    parser.add_argument("--output", required=True, help="output stage3-metrics.json path")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    metrics = build_metrics(work_dir, args.title, args.platform)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    steps_present = sum(
        1 for k, v in metrics.items()
        if k.startswith("step") and isinstance(v, dict) and v
        and v.get("status") not in ("missing", "not_run")
    )
    print(json.dumps({"ok": True, "steps_with_data": steps_present}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
