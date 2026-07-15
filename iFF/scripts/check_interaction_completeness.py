#!/usr/bin/env python3
"""Gate: the interaction CONTRACT must be complete before coverage can mean anything.

100% interaction coverage is worthless if `parse_interactions` silently dropped real behavioral
rules into `ignoredItems` — you'd have 100% of an *incomplete* list. This audit scans the ignored
items for sentences that look like behavioral rules (a trigger/condition + an effect) yet were not
turned into `INT-xxx` rules, and fails so the gap is resolved explicitly — either by extracting the
rule (improve the contract) or by acknowledging it as a non-rule.

It does NOT invent rules; it only flags ignored prose carrying rule signals so a human/model
decides. Acknowledge a genuinely-non-rule item by adding its exact text (or a unique substring) to
`acknowledgedNonRules` in the contract JSON; acknowledged items are not flagged.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from parse_interactions import is_ignorable_item, split_items

# Signals that a sentence encodes behaviour (a trigger/condition AND/OR an effect), not just
# structure/prose. Bilingual (the specs mix Chinese + English identifiers).
TRIGGER = re.compile(
    r"apply_status\s*=|auth_stage\s*=|点击|长按|tap\b|click|进入|打开|页面离开|离开|返回|下拉|刷新|"
    r"超时|失败时|成功后|为空|非空|拒绝|同意|授权|轮询|poll|on\s?(tap|press|leave|back)", re.I)
EFFECT = re.compile(
    r"跳转|进入.{0,6}页|push|pop|路由|route|展示|显示|show|隐藏|请求|调用|上传|刷新|拉起|打开|"
    r"禁止|埋点|/[a-z][a-z0-9/_-]+|EasyLoading|弹窗|dialog|toast", re.I)
# Pure structure / file-layout / data-model prose — not interaction rules even if they match above.
STRUCTURE = re.compile(
    r"^\s*#|实现结构|目录|文件按|入口[::]|`lib/|\.dart\b|Domain model|数据结构|静态配置|"
    r"DTO|model[::]|字段[::]|^\s*-?\s*`?[A-Z]\w+`?[::]\s*(贷款|客服|底部|标题)", re.I)


def looks_like_rule(text: str) -> bool:
    t = text.strip()
    if len(t) < 18:                      # headers / fragments
        return False
    if STRUCTURE.search(t):
        return False
    return bool(TRIGGER.search(t)) and bool(EFFECT.search(t))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True, help="interaction_contract.json")
    ap.add_argument("--out")
    a = ap.parse_args()

    c = json.loads(Path(a.contract).read_text(encoding="utf-8"))
    ignored = c.get("ignoredItems") or []
    ack = c.get("acknowledgedNonRules") or []
    ack_sources = [
        str(x.get("source") or "") if isinstance(x, dict) else str(x)
        for x in ack
    ]
    invalid_acknowledgements = []
    for source, item in zip(ack_sources, ack):
        if not isinstance(item, dict) or not str(item.get("reason") or "").strip():
            invalid_acknowledgements.append(f"{source}: missing reason")
        elif not is_ignorable_item(source) and item.get("confirmedByModel") is not True:
            invalid_acknowledgements.append(
                f"{source}: semantic non-rule not confirmed by model"
            )
    ack_norm = [re.sub(r"\s+", "", x) for x in ack_sources]
    rules = [rule for rule in c.get("rules") or [] if isinstance(rule, dict)]
    rule_sources = {str(rule.get("source") or "") for rule in rules}
    compound_decisions = {
        str(item.get("source") or ""): item
        for item in c.get("compoundDecisions") or []
        if isinstance(item, dict)
    }
    invalid_compounds = []
    resolved_compound_sources = set()
    for candidate in c.get("compoundCandidates") or []:
        source = str((candidate or {}).get("source") or "")
        decision = compound_decisions.get(source)
        if not decision:
            invalid_compounds.append(f"{source}: unresolved compound candidate")
            continue
        if decision.get("confirmedByModel") is not True:
            invalid_compounds.append(f"{source}: compound decision not confirmed by model")
            continue
        kind = decision.get("decision")
        if kind == "single":
            if source not in rule_sources:
                invalid_compounds.append(f"{source}: single decision missing matching rule")
                continue
        elif kind == "split":
            atomic_sources = decision.get("atomicSources") or []
            if (
                not atomic_sources
                or any(not isinstance(item, str) or item not in source for item in atomic_sources)
                or any(item not in rule_sources for item in atomic_sources)
            ):
                invalid_compounds.append(f"{source}: split decision has invalid atomicSources")
                continue
        else:
            invalid_compounds.append(f"{source}: invalid compound decision {kind!r}")
            continue
        resolved_compound_sources.add(source)

    def acknowledged(text: str) -> bool:
        tn = re.sub(r"\s+", "", text)
        return any(a_ and (a_ in tn or tn in a_) for a_ in ack_norm)

    flagged = []
    for item in ignored:
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        if looks_like_rule(text) and not acknowledged(text):
            flagged.append(text.strip()[:200])

    source_items = split_items(str(c.get("source") or ""))
    accounted = {
        re.sub(r"\s+", "", str(rule.get("source") or ""))
        for rule in c.get("rules") or []
        if isinstance(rule, dict)
    }
    accounted.update(re.sub(r"\s+", "", source) for source in ack_sources)
    accounted.update(re.sub(r"\s+", "", source) for source in resolved_compound_sources)
    unaccounted = [
        item for item in source_items if re.sub(r"\s+", "", item) not in accounted
    ]

    report = {
        "ruleCount": len(c.get("rules") or []),
        "ignoredCount": len(ignored),
        "acknowledgedNonRules": len(ack),
        "suspectedMissedRules": flagged,
        "unaccountedSourceItems": unaccounted,
        "invalidAcknowledgements": invalid_acknowledgements,
        "invalidCompoundDecisions": invalid_compounds,
        "ok": not flagged and not unaccounted and not invalid_acknowledgements and not invalid_compounds,
    }
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if flagged or unaccounted or invalid_acknowledgements or invalid_compounds:
        print(
            f"FAIL interaction completeness: {len(flagged)} suspected missed rule(s), "
            f"{len(unaccounted)} unaccounted source item(s), "
            f"{len(invalid_acknowledgements)} invalid acknowledgement(s), "
            f"{len(invalid_compounds)} invalid compound decision(s) "
            f"(rules={report['ruleCount']}):"
        )
        for f in flagged:
            print("  - " + f)
        for item in unaccounted:
            print("  - " + item)
        for item in invalid_acknowledgements:
            print("  - " + item)
        for item in invalid_compounds:
            print("  - " + item)
        return 1
    print(f"ok interaction completeness: {report['ruleCount']} rules, no rule-like text left in "
          f"{len(ignored)} ignored items ({len(ack)} acknowledged non-rules).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
