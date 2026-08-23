#!/usr/bin/env python3
"""ICP Stage 2 — check: 验证 checklist.md 完成度。

用法:
  check.py <checklist>              检查全部步骤
  check.py <checklist> --step N     只检查 Step N
"""

import argparse
import json
import re
import sys
from pathlib import Path

STEP_RE = re.compile(r"^##\s+Step\s+(\d+)")
ITEM_RE = re.compile(r"^-\s+\[([ xX])\]\s+(\w+):\s*(.*)")


def parse_checklist(text):
    """Parse checklist.md → {step_num: [{key, checked, value}, ...]}."""
    steps = {}
    current_step = None
    for line in text.splitlines():
        m = STEP_RE.match(line)
        if m:
            current_step = int(m.group(1))
            steps[current_step] = []
            continue
        if current_step is None:
            continue
        m = ITEM_RE.match(line)
        if m:
            steps[current_step].append({
                "key": m.group(2),
                "checked": m.group(1).lower() == "x",
                "value": m.group(3).strip(),
            })
    return steps


def check(checklist_path, step=None, required=None):
    text = Path(checklist_path).read_text(encoding="utf-8")
    steps = parse_checklist(text)

    if not steps:
        return {"ok": False, "errors": [{"type": "empty_checklist"}]}

    if step is not None and step not in steps:
        return {"ok": False, "errors": [{"type": "unknown_step", "step": step}]}

    targets = {step: steps[step]} if step is not None else steps
    errors = []
    for s, items in sorted(targets.items()):
        found_keys = set()
        for item in items:
            found_keys.add(item["key"])
            if not item["checked"]:
                errors.append({"type": "unchecked", "step": s, "key": item["key"]})
            elif not item["value"]:
                errors.append({"type": "empty_value", "step": s, "key": item["key"]})
        if required:
            for rk in required:
                if rk not in found_keys:
                    errors.append({"type": "missing_key", "step": s, "key": rk})

    ok = len(errors) == 0
    result = {"ok": ok}
    if errors:
        result["errors"] = errors
    return result


def main():
    parser = argparse.ArgumentParser(description="ICP checklist 验证")
    parser.add_argument("checklist", help="checklist.md 路径")
    parser.add_argument("--step", type=int, help="只检查指定步骤")
    parser.add_argument("--require", help="逗号分隔的必填 key（缺失即报 missing_key）")
    args = parser.parse_args()

    required = [k.strip() for k in args.require.split(",") if k.strip()] if args.require else None
    result = check(args.checklist, args.step, required)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
