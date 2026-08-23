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


def read_json(path: Path) -> dict | None:
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
    return data.get("metrics", {})


def extract_step7(work_dir: Path) -> dict:
    data = read_json(work_dir / "visual-diff.json")
    if not data:
        return {"status": "not_run"}
    return {
        "visual_pass": data.get("visual_pass"),
        "visual_issues": data.get("visual_issues", []),
    }


def extract_step8(work_dir: Path) -> dict:
    data = read_json(work_dir / "attribution-ledger.json")
    if not data:
        return {"status": "no_fixes_needed"}
    entries = data if isinstance(data, list) else data.get("entries", [])
    breakdown = {}
    for e in entries:
        attr = e.get("attribution", "unknown")
        breakdown[attr] = breakdown.get(attr, 0) + 1
    return {
        "total_rounds": len(entries),
        "attributions": breakdown,
    }


def extract_step9(work_dir: Path) -> dict:
    data = read_json(work_dir / "behavior-result.json")
    if not data:
        return {"status": "not_run"}
    return {
        "behavior_total": data.get("behavior_total", 0),
        "behavior_passed": data.get("behavior_passed", 0),
        "behavior_failed": data.get("behavior_failed", []),
    }


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
    parser.add_argument("--platform", default="android", help="target platform")
    parser.add_argument("--output", required=True, help="output stage3-metrics.json path")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    metrics = build_metrics(work_dir, args.title, args.platform)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    steps_present = sum(
        1 for k, v in metrics.items()
        if k.startswith("step") and isinstance(v, dict) and v.get("status") not in ("missing", None)
    )
    print(json.dumps({"ok": True, "steps_with_data": steps_present}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
