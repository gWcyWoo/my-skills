#!/usr/bin/env python3
"""Compile the sheet interaction column into deterministic rules."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import dump_json


TRIGGER_WORDS = (
    "点击",
    "点按",
    "输入",
    "选择",
    "切换",
    "滑动",
    "下拉",
    "提交",
    "返回",
    "tap",
    "click",
    "input",
    "select",
    "switch",
    "swipe",
    "submit",
    "back",
)
EXPECT_WORDS = (
    "跳转",
    "进入",
    "显示",
    "弹出",
    "提示",
    "请求",
    "刷新",
    "更新",
    "关闭",
    "navigate",
    "show",
    "display",
    "toast",
    "request",
    "refresh",
    "update",
    "close",
)


def read_interaction(args: argparse.Namespace) -> str:
    if args.input:
        return Path(args.input).read_text(encoding="utf-8")
    return args.interaction or ""


def split_items(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_parts: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[-*•]\s+", line) or re.match(r"^\d+[.)、]\s*", line):
            raw_parts.append(line)
            continue
        raw_parts.extend(part.strip() for part in re.split(r"[；;]\s*", line) if part.strip())
    items = []
    for part in raw_parts:
        cleaned = re.sub(r"^[-*•]\s+", "", part)
        cleaned = re.sub(r"^\d+[.)、]\s*", "", cleaned).strip()
        if cleaned:
            items.append(cleaned)
    return items


def split_trigger_expectation(text: str) -> tuple[str | None, str | None]:
    for sep in ("->", "=>", "→", "后", "则", "时"):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip() or None, right.strip() or None
    trigger = None
    expectation = None
    for word in TRIGGER_WORDS:
        if word.lower() in text.lower():
            trigger = text
            break
    for word in EXPECT_WORDS:
        if word.lower() in text.lower():
            expectation = text
            break
    return trigger, expectation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interaction", help="Raw interaction column value.")
    parser.add_argument("--input", help="File containing the raw interaction column value.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    raw = read_interaction(args)
    items = split_items(raw)
    rules = []
    errors = []
    for index, item in enumerate(items, start=1):
        trigger, expectation = split_trigger_expectation(item)
        rule_id = f"INT-{index:03d}"
        missing = []
        if not trigger:
            missing.append("trigger")
        if not expectation:
            missing.append("expectation")
        if missing:
            errors.append(f"{rule_id}: cannot parse {', '.join(missing)} from: {item}")
        rules.append(
            {
                "id": rule_id,
                "source": item,
                "trigger": trigger,
                "expectation": expectation,
                "coverageRequired": ["happy", "boundary", "failure"],
                "testCaseIdsRequired": [
                    f"{rule_id}-HAPPY",
                    f"{rule_id}-BOUNDARY",
                    f"{rule_id}-FAILURE",
                ],
            }
        )
    if errors:
        raise SystemExit("ERROR: interaction column is not machine-parseable:\n" + "\n".join(errors))
    dump_json({"source": raw, "rules": rules}, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
