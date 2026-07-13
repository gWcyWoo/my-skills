#!/usr/bin/env python3
"""Compile the sheet interaction column into deterministic rules."""

from __future__ import annotations

import argparse
import hashlib
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
REQUIRE_WORDS = (
    "必须",
    "不得",
    "不能",
    "禁止",
    "只",
    "优先",
    "读取",
    "上传",
    "调用",
    "轮询",
    "打开",
    "保留",
    "展示",
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


def is_ignorable_item(text: str) -> bool:
    if text.startswith("#"):
        return True
    if text.endswith("如下：") or text.endswith("如下:"):
        return True
    if (text.endswith("：") or text.endswith(":")) and not any(word in text for word in TRIGGER_WORDS):
        return True
    if "例如" in text and not any(word in text for word in TRIGGER_WORDS + EXPECT_WORDS + REQUIRE_WORDS):
        return True
    return False


def split_colon_rule(text: str) -> tuple[str | None, str | None]:
    match = re.match(r"^`?(\d{2}:\d{2}[-–]\d{2}:\d{2})`?[：:](.+)$", text)
    if match:
        return f"local_time={match.group(1)}", match.group(2).strip() or None

    match = re.match(r"^`?(\d{1,2})`?[：:](.+)$", text)
    if match:
        code = match.group(1)
        rest = match.group(2).strip()
        trigger = f"auth_stage={code}" if "AppRoutes." in rest else f"apply_status={code}"
        return trigger, rest or None

    if "：" in text:
        left, right = text.split("：", 1)
    elif ":" in text and not re.match(r"^\w+://", text):
        left, right = text.split(":", 1)
    else:
        return None, None
    left = left.strip("` ").strip()
    right = right.strip()
    if not left or not right:
        return None, None
    if any(word in right for word in TRIGGER_WORDS):
        after_match = re.search(r"(?<!最)后(?!续|置)", right)
        if after_match:
            return (
                right[: after_match.start()].strip() or None,
                right[after_match.end() :].strip() or None,
            )
    if any(word in right for word in EXPECT_WORDS) or any(word in left for word in TRIGGER_WORDS):
        return left, right
    return None, None


def split_trigger_expectation(text: str) -> tuple[str | None, str | None]:
    trigger, expectation = split_colon_rule(text)
    if trigger or expectation:
        return trigger, expectation
    for sep in ("->", "=>", "→"):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip() or None, right.strip() or None
    after_match = re.search(r"(?<!最)后(?!续|置)", text)
    if after_match:
        left = text[: after_match.start()]
        right = text[after_match.end() :]
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
    if not expectation and any(word in text for word in REQUIRE_WORDS) and any(
        word in text for word in TRIGGER_WORDS + EXPECT_WORDS
    ):
        expectation = text
    if not trigger and expectation and any(word in text for word in EXPECT_WORDS):
        trigger = "contract requirement"
    return trigger, expectation


def stable_rule_id(source: str) -> str:
    normalized = re.sub(r"\s+", " ", source).strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10].upper()
    return f"INT-{digest}"


def compound_clauses(text: str) -> list[str]:
    trigger_pattern = "|".join(re.escape(word) for word in TRIGGER_WORDS)
    clauses = [
        part.strip()
        for part in re.split(rf"[，,]\s*(?=(?:{trigger_pattern}))", text, flags=re.I)
        if part.strip()
    ]
    if len(clauses) < 2:
        return []
    return clauses if all(all(split_trigger_expectation(part)) for part in clauses) else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interaction", help="Raw interaction column value.")
    parser.add_argument("--input", help="File containing the raw interaction column value.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    raw = read_interaction(args)
    items = split_items(raw)
    rules = []
    ignored_items = []
    acknowledged_non_rules = []
    compound_candidates = []
    for item in items:
        if is_ignorable_item(item):
            acknowledged_non_rules.append(
                {"source": item, "reason": "structure_or_heading"}
            )
            continue
        clauses = compound_clauses(item)
        if clauses:
            compound_candidates.append({"source": item, "suggestedClauses": clauses})
            continue
        trigger, expectation = split_trigger_expectation(item)
        if not trigger or not expectation:
            ignored_items.append(item)
            continue
        rule_id = stable_rule_id(item)
        rules.append(
            {
                "id": rule_id,
                "source": item,
                "trigger": trigger,
                "expectation": expectation,
                "action": trigger,
                "actionTarget": {"kind": "__MODEL__"},
                "observableOutcome": expectation,
                "boundaryOutcome": "__MODEL__",
                "failureOutcome": "__MODEL__",
                "observableTargets": {
                    "happy": {"kind": "__MODEL__"},
                    "boundary": {"kind": "__MODEL__"},
                    "failure": {"kind": "__MODEL__"},
                },
                "coverageRequired": ["happy", "boundary", "failure"],
                "testCaseIdsRequired": [
                    f"{rule_id}-HAPPY",
                    f"{rule_id}-BOUNDARY",
                    f"{rule_id}-FAILURE",
                ],
            }
        )
    if raw.strip() and not rules and not compound_candidates:
        raise SystemExit("ERROR: interaction column is not machine-parseable: no actionable rules found")
    dump_json(
        {
            "source": raw,
            "rules": rules,
            "ignoredItems": ignored_items,
            "acknowledgedNonRules": acknowledged_non_rules,
            "compoundCandidates": compound_candidates,
            "compoundDecisions": [],
        },
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
