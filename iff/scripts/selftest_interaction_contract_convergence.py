#!/usr/bin/env python3
"""Public-CLI regression for contract-worker interaction convergence."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
PARSE = SCRIPTS / "parse_interactions.py"
CHECK = SCRIPTS / "check_interaction_completeness.py"
PLAN = SCRIPTS / "make_interaction_tests_plan.py"
PROMPT = SCRIPTS / "make_worker_prompt.py"
PROMOTE = SCRIPTS / "promote_interaction_rules.py"
SKILL_DIR = SCRIPTS.parent


def run_cli(tool: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tool), *args],
        text=True,
        capture_output=True,
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def assert_live_like_five_misses_converge() -> None:
    missed = [
        "apply_status=5 时页面展示可操作卡片并允许点击按钮",
        "额度字段非空时页面展示等级额度，字段为空时展示默认额度",
        "Usage Access 权限已授权时记录应用使用时长上传计划，未授权时页面不弹窗",
        "Usage Access 权限已授权时记录应用使用时长上传计划",
        "产品数据数组为空时贷款卡片区域页面展示预设的空列表占位内容",
    ]
    rules = []
    for number in range(1, 35):
        rule_id = f"INT-{number:03d}"
        rules.append(
            {
                "id": rule_id,
                "source": f"点击操作{number}，跳转结果页{number}",
                "trigger": f"点击操作{number}",
                "expectation": f"跳转结果页{number}",
                "coverageRequired": ["happy", "boundary", "failure"],
                "testCaseIdsRequired": [
                    f"{rule_id}-HAPPY",
                    f"{rule_id}-BOUNDARY",
                    f"{rule_id}-FAILURE",
                ],
            }
        )

    with tempfile.TemporaryDirectory(prefix="iff-interaction-live-like-") as raw_tmp:
        root = Path(raw_tmp)
        contract = root / "interaction_contract.json"
        completeness = root / "interaction_completeness.json"
        promotion_report = root / "interaction_promotion_report.json"
        plan = root / "interaction_test_plan.json"
        write_json(
            contract,
            {
                "schemaVersion": 1,
                "rules": rules,
                "ignoredItems": [*[f"说明片段{index}" for index in range(22)], *missed],
                "acknowledgedNonRules": [],
            },
        )

        promoted = run_cli(
            PROMOTE,
            "--contract",
            str(contract),
            "--completeness-report",
            str(completeness),
            "--out",
            str(promotion_report),
        )
        assert promoted.returncode == 0, promoted.stdout + promoted.stderr
        promotion = json.loads(promotion_report.read_text(encoding="utf-8"))
        assert promotion["initialRuleCount"] == 34
        assert promotion["reportedOccurrenceCount"] == 5, promotion
        assert promotion["promotedRuleIds"] == ["INT-035", "INT-036", "INT-037", "INT-038"]
        assert promotion["deduplicatedOccurrenceCount"] == 1

        regenerated = run_cli(
            PLAN,
            "--contract",
            str(contract),
            "--out",
            str(plan),
        )
        assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
        final_check = run_cli(
            CHECK,
            "--contract",
            str(contract),
            "--out",
            str(completeness),
        )
        assert final_check.returncode == 0, final_check.stdout + final_check.stderr
        final_report = json.loads(completeness.read_text(encoding="utf-8"))
        assert final_report["ruleCount"] == 38
        assert final_report["suspectedMissedRules"] == []


def main() -> int:
    existing = "点击保存按钮，跳转结果页"
    shorter = "列表为空这一条件会控制页面展示预设的空状态占位内容"
    longer = shorter + "以及帮助说明"
    raw = "；".join((existing, shorter, longer, shorter))

    with tempfile.TemporaryDirectory(prefix="iff-interaction-convergence-") as raw_tmp:
        root = Path(raw_tmp)
        contract = root / "interaction_contract.json"
        report = root / "interaction_completeness_report.json"
        promotion_report = root / "interaction_promotion_report.json"
        prompt_path = root / "contract_worker_prompt.txt"
        plan_path = root / "interaction_test_plan.json"

        parsed = run_cli(PARSE, "--interaction", raw, "--out", str(contract))
        assert parsed.returncode == 0, parsed.stderr or parsed.stdout
        parsed_contract = json.loads(contract.read_text(encoding="utf-8"))
        assert [rule["id"] for rule in parsed_contract["rules"]] == ["INT-001"]
        assert parsed_contract["ignoredItems"] == [shorter, longer, shorter]

        failed = run_cli(
            CHECK,
            "--contract",
            str(contract),
            "--out",
            str(report),
        )
        assert failed.returncode == 1, failed.stdout
        failed_report = json.loads(report.read_text(encoding="utf-8"))
        assert failed_report["suspectedMissedRules"] == [shorter, longer, shorter]

        generated = run_cli(
            PROMPT,
            "--mode",
            "contract",
            "--skill-dir",
            str(SKILL_DIR),
            "--spec-dir",
            str(root),
            "--project-root",
            str(root),
            "--out",
            str(prompt_path),
        )
        assert generated.returncode == 0, generated.stderr or generated.stdout
        prompt = prompt_path.read_text(encoding="utf-8")
        expected_check = (
            f"python3 {CHECK} --contract {contract.resolve()} --row {(root / 'row.json').resolve()} "
            f"--out {report.resolve()}"
        )
        assert expected_check in prompt
        assert "exactly ONE bounded promotion pass" in prompt
        assert "promote_interaction_rules.py" in prompt
        assert "remove exactly one matching ignoredItems occurrence" in prompt
        assert "Do not renumber or reorder existing rules" in prompt
        assert "rerun the completeness command exactly once" in prompt
        assert prompt.count("check_interaction_completeness.py") == 1
        assert f"--row {(root / 'row.json').resolve()}" in prompt
        assert prompt.index("promote_interaction_rules.py") < prompt.index("make_interaction_tests_plan.py")
        assert prompt.index("make_interaction_tests_plan.py") < prompt.index("check_interaction_completeness.py")

        parsed_contract["acknowledgedNonRules"] = [shorter]
        write_json(contract, parsed_contract)
        overlap = run_cli(
            CHECK,
            "--contract",
            str(contract),
            "--out",
            str(report),
        )
        assert overlap.returncode == 1, overlap.stdout
        overlap_report = json.loads(report.read_text(encoding="utf-8"))
        assert overlap_report["suspectedMissedRules"] == [longer, shorter]

        promoted = run_cli(
            PROMOTE,
            "--contract",
            str(contract),
            "--completeness-report",
            str(report),
            "--out",
            str(promotion_report),
        )
        assert promoted.returncode == 0, promoted.stdout + promoted.stderr
        promotion = json.loads(promotion_report.read_text(encoding="utf-8"))
        assert promotion["reportedOccurrenceCount"] == 2
        assert promotion["promotedRuleIds"] == ["INT-002"]
        assert promotion["deduplicatedOccurrenceCount"] == 1
        assert promotion["initialCompletenessRuns"] == 1
        assert [action["action"] for action in promotion["actions"]] == [
            "promoted",
            "deduplicated_overlap",
        ]
        promoted_contract = json.loads(contract.read_text(encoding="utf-8"))
        assert promoted_contract["acknowledgedNonRules"] == [shorter]
        assert promoted_contract["ignoredItems"] == [shorter]

        converged = run_cli(
            CHECK,
            "--contract",
            str(contract),
            "--out",
            str(report),
        )
        assert converged.returncode == 0, converged.stdout
        planned = run_cli(
            PLAN,
            "--contract",
            str(contract),
            "--out",
            str(plan_path),
        )
        assert planned.returncode == 0, planned.stderr or planned.stdout
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assert [case["id"] for case in plan["cases"]] == [
            "INT-001-HAPPY",
            "INT-001-BOUNDARY",
            "INT-001-FAILURE",
            "INT-002-HAPPY",
            "INT-002-BOUNDARY",
            "INT-002-FAILURE",
        ]

    assert_live_like_five_misses_converge()
    print("ok interaction contract convergence selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
