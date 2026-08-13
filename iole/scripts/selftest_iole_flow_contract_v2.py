#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("iole_flow_contract_v2.py")
ICP_FLOW_SCRIPT = Path(__file__).parents[2] / "icp" / "scripts" / "icp_flow_job_v1.py"
MAPPING = Path(__file__).parents[1] / "references" / "role-mapping-v2.json"


def run_plan(document: dict[str, object]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        input_path = Path(temporary_directory) / "flow-input.json"
        input_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
            check=False,
            capture_output=True,
            text=True,
        )


def base_input() -> dict[str, object]:
    return {
        "kind": "iole.flow-plan-input.v2",
        "schema_version": 2,
        "source_id": "google-sheets:" + "a" * 64,
        "role": "client",
        "root_title": "申请首页",
        "rows": [
            {
                "title": "申请首页",
                "status": "ready",
                "pr_url": "",
                "design_ref": "https://design.example/application",
                "route": "/apply",
                "interaction": "点击“继续” →「职业信息页」",
                "change_scope": "modify",
                "requirement": "实现申请入口并导航到职业信息页。",
                "acceptance_criteria": [],
                "design_source": "lanhu-figma",
                "mode": "implement",
                "review": None,
                "allowed_paths": ["app/src/main/ApplicationScreen.kt"],
            },
            {
                "title": "职业信息页",
                "status": "ready",
                "pr_url": "",
                "design_ref": "https://design.example/occupation",
                "route": "/apply/job",
                "interaction": "点击“提交” →「申请结果页」",
                "change_scope": "modify",
                "requirement": "实现职业信息表单。",
                "acceptance_criteria": [],
                "design_source": "lanhu-figma",
                "mode": "implement",
                "review": None,
                "allowed_paths": ["app/src/main/OccupationScreen.kt"],
            },
            {
                "title": "申请结果页",
                "status": "ready",
                "pr_url": "",
                "design_ref": "https://design.example/result",
                "route": "/apply/result",
                "interaction": "",
                "change_scope": "modify",
                "requirement": "实现申请结果页。",
                "acceptance_criteria": [],
                "design_source": "lanhu-figma",
                "mode": "implement",
                "review": None,
                "allowed_paths": ["app/src/main/ResultScreen.kt"],
            },
        ],
        "component_analysis": {
            "inventory_source": "project-scan",
            "searched_paths": ["app/src/main"],
            "summary": "Inspected existing shared and feature-local components.",
        },
        "component_plan": [],
    }
def internal_page_id(title: str) -> str:
    return "page-" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:20]


def page_node(title: str) -> str:
    return "page:" + internal_page_id(title)


class FlowPlanContractTests(unittest.TestCase):
    def test_extracts_title_only_references_without_document_page_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            row_path = Path(temporary_directory) / "root-row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "title": "申请首页",
                        "interaction": (
                            "点击继续 →「职业信息页」；点击帮助 →「帮助页」"
                        ),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "extract-refs",
                    "--row",
                    str(row_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["title"], "申请首页")
        self.assertEqual(
            result["references"],
            [{"title": "职业信息页"}, {"title": "帮助页"}],
        )
        self.assertNotIn("page_id", result)

    def test_extracts_only_titles_after_navigation_arrows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            row_path = Path(temporary_directory) / "root-row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "title": "申请首页",
                        "interaction": (
                            "点击「继续」 →「职业信息页」；"
                            "失败时显示「请重试」，点击帮助 →「帮助页」"
                        ),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "extract-refs",
                    "--row",
                    str(row_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout)["references"],
            [{"title": "职业信息页"}, {"title": "帮助页"}],
        )

    def test_builds_the_same_flow_from_titles_when_document_numbers_are_absent_or_change(self) -> None:
        without_numbers = base_input()
        changed_numbers = base_input()
        changed_numbers["root_page_id"] = "IGNORED-ROOT"
        changed_rows = changed_numbers["rows"]
        assert isinstance(changed_rows, list)
        for index, row in enumerate(changed_rows, start=900):
            assert isinstance(row, dict)
            row["编号"] = f"IGNORED-{index}"
            row["page_id"] = f"IGNORED-PAGE-{index}"

        first = run_plan(without_numbers)
        second = run_plan(changed_numbers)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_result = json.loads(first.stdout)
        second_result = json.loads(second.stdout)
        self.assertEqual(first_result["flow_id"], second_result["flow_id"])
        self.assertEqual(first_result["root_page_title"], "申请首页")
        self.assertEqual(
            first_result["claim_page_titles"],
            ["申请首页", "职业信息页", "申请结果页"],
        )
        self.assertEqual(
            first_result["interaction_title_edges"],
            [
                {"from": "申请首页", "to": "职业信息页"},
                {"from": "职业信息页", "to": "申请结果页"},
            ],
        )
        self.assertEqual(
            [member["title"] for member in first_result["members"]],
            ["申请首页", "职业信息页", "申请结果页"],
        )

    def test_new_schedule_requires_the_flow_connector_and_v2_mapping(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book/edit",
                "--role",
                "client",
                "--im",
                "10",
                "--project-root",
                str(Path.cwd()),
                "--mapping",
                str(MAPPING),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["kind"], "iole.flow-schedule-plan.v2")
        self.assertEqual(result["mapping_path"], str(MAPPING))
        self.assertEqual(
            result["required_connector_operations"],
            [
                "inspect_ready_flow_root",
                "inspect_flow_rows",
                "claim_flow_rows",
                "expand_flow_claim",
                "complete_flow_rows",
                "record_flow_error",
            ],
        )
        self.assertEqual(result["connector_queue"]["status"], "frontend status")
        self.assertEqual(result["connector_queue"]["row_id"], "标题")
        self.assertNotIn("编号", MAPPING.read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads(MAPPING.read_text(encoding="utf-8"))["flow"]["reference_syntax"],
            "→「页面标题」",
        )
        self.assertIn("flow_contract_version", result["prompt"])

    def test_rejects_a_new_flow_mapping_that_uses_a_number_instead_of_title(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            mapping_path = Path(temporary_directory) / "mapping.json"
            mapping_document = json.loads(MAPPING.read_text(encoding="utf-8"))
            mapping_document["common"]["row_id"] = "编号"
            mapping_path.write_text(
                json.dumps(mapping_document, ensure_ascii=False),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "schedule-plan",
                    "--excel-url",
                    "https://docs.google.com/spreadsheets/d/book/edit",
                    "--role",
                    "client",
                    "--project-root",
                    str(Path.cwd()),
                    "--mapping",
                    str(mapping_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "flow title mapping is invalid",
        )

    def test_rejects_missing_duplicate_and_cyclic_page_titles(self) -> None:
        cases: list[tuple[dict[str, object], str]] = []

        missing = base_input()
        missing_rows = missing["rows"]
        assert isinstance(missing_rows, list)
        missing["rows"] = missing_rows[:1]
        cases.append((missing, "referenced page is missing: 职业信息页"))

        duplicated = base_input()
        duplicated_rows = duplicated["rows"]
        assert isinstance(duplicated_rows, list)
        duplicated_rows[1]["title"] = "申请首页"
        cases.append((duplicated, "duplicate page title: 申请首页"))

        cyclic = base_input()
        cyclic_rows = cyclic["rows"]
        assert isinstance(cyclic_rows, list)
        cyclic_rows[2]["interaction"] = "返回 →「申请首页」"
        cases.append((cyclic, "page interaction cycle"))

        for document, reason in cases:
            with self.subTest(reason=reason):
                completed = run_plan(document)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(json.loads(completed.stdout)["reason"], reason)

    def test_extracts_declared_child_titles_before_reading_child_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            row_path = Path(temporary_directory) / "root-row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "title": "申请首页",
                        "interaction": (
                            "点击继续 →「职业信息页」；点击帮助 →「帮助页」"
                        ),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "extract-refs",
                    "--row",
                    str(row_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout)["references"],
            [{"title": "职业信息页"}, {"title": "帮助页"}],
        )

    def test_rejects_a_flow_that_skips_component_inventory_reasoning(self) -> None:
        document = base_input()
        del document["component_analysis"]

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "component analysis is required",
        )

    def test_builds_leaf_first_plan_from_title_references(self) -> None:
        completed = run_plan(base_input())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["kind"], "iole.flow-plan.v2")
        self.assertEqual(result["decision"], "ready")
        self.assertEqual(result["root_page_title"], "申请首页")
        self.assertEqual(
            result["claim_page_titles"],
            ["申请首页", "职业信息页", "申请结果页"],
        )
        self.assertEqual(
            result["interaction_title_edges"],
            [
                {"from": "申请首页", "to": "职业信息页"},
                {"from": "职业信息页", "to": "申请结果页"},
            ],
        )
        self.assertEqual(
            result["execution_order"],
            [page_node("申请结果页"), page_node("职业信息页"), page_node("申请首页")],
        )

    def test_excludes_navigation_only_pages_from_claim_and_status_changes(self) -> None:
        document = base_input()
        rows = document["rows"]
        assert isinstance(rows, list)
        rows[1]["change_scope"] = "navigate-only"
        rows[2]["change_scope"] = "navigate-only"

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["claim_page_titles"], ["申请首页"])
        self.assertEqual(result["execution_order"], [page_node("申请首页")])
        self.assertEqual(
            [page["title"] for page in result["excluded_pages"]],
            ["职业信息页", "申请结果页"],
        )

    def test_places_shared_component_changes_before_every_page_consumer(self) -> None:
        document = base_input()
        document["component_plan"] = [
            {
                "component_id": "shared-form-card",
                "name": "FormCard",
                "decision": "extend",
                "code_path": "app/src/main/java/ui/components/FormCard.kt",
                "allowed_paths": [
                    "app/src/main/java/ui/components/FormCard.kt",
                    "app/src/test/java/ui/components/",
                ],
                "consumers": ["申请首页", "职业信息页"],
                "evidence": "Existing shared card is the closest semantic match.",
            }
        ]

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["execution_order"],
            [
                "component:shared-form-card",
                page_node("申请结果页"),
                page_node("职业信息页"),
                page_node("申请首页"),
            ],
        )
        nodes = {node["node_id"]: node for node in result["execution_dag"]}
        self.assertEqual(nodes["component:shared-form-card"]["type"], "shared-component")
        self.assertEqual(
            nodes["component:shared-form-card"]["allowed_paths"],
            [
                "app/src/main/java/ui/components/FormCard.kt",
                "app/src/test/java/ui/components/",
            ],
        )
        self.assertIn(
            "component:shared-form-card",
            nodes[page_node("申请首页")]["depends_on"],
        )
        self.assertIn(
            "component:shared-form-card",
            nodes[page_node("职业信息页")]["depends_on"],
        )

    def test_rejects_overlapping_execution_node_path_ownership_before_claim(self) -> None:
        document = base_input()
        rows = document["rows"]
        assert isinstance(rows, list)
        rows[0]["allowed_paths"] = ["app/src/main/java/ui/"]
        document["component_plan"] = [
            {
                "component_id": "shared-form-card",
                "name": "FormCard",
                "decision": "extend",
                "code_path": "app/src/main/java/ui/components/FormCard.kt",
                "allowed_paths": ["app/src/main/java/ui/components/FormCard.kt"],
                "consumers": ["申请首页"],
                "evidence": "Existing shared card needs one compatible extension.",
            }
        ]

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            (
                "execution node path ownership overlaps: "
                f"component:shared-form-card and {page_node('申请首页')}"
            ),
        )

    def test_requires_a_local_component_to_be_owned_by_its_consumer_page(self) -> None:
        document = base_input()
        document["component_plan"] = [
            {
                "component_id": "occupation-hint",
                "name": "OccupationHint",
                "decision": "create-local",
                "code_path": "app/src/main/OccupationHint.kt",
                "allowed_paths": ["app/src/main/OccupationHint.kt"],
                "consumers": ["职业信息页"],
                "evidence": "The behavior is specific to the occupation page.",
            }
        ]

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "local component path is not owned by its consumer page: occupation-hint",
        )

    def test_requires_explicit_reopen_before_claiming_a_done_page_that_will_change(self) -> None:
        document = base_input()
        rows = document["rows"]
        assert isinstance(rows, list)
        rows[1]["status"] = "done"
        rows[1]["pr_url"] = "https://git.example/team/app/pull/7"

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["decision"], "needs-reopen")
        self.assertEqual(result["reopen_page_titles"], ["职业信息页"])
        self.assertEqual(
            result["claim_page_titles"],
            ["申请首页", "职业信息页", "申请结果页"],
        )
        self.assertEqual(result["existing_pr_url"], "https://git.example/team/app/pull/7")

    def test_blocks_before_claim_when_members_reference_different_prs(self) -> None:
        document = base_input()
        rows = document["rows"]
        assert isinstance(rows, list)
        rows[0]["pr_url"] = "https://git.example/team/app/pull/7"
        rows[1]["pr_url"] = "https://git.example/team/app/pull/8"

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["decision"], "blocked")
        self.assertEqual(result["reason"], "pr-conflict")
        self.assertNotIn("execution_order", result)

    def test_blocks_before_claim_when_a_member_is_already_doing(self) -> None:
        document = base_input()
        rows = document["rows"]
        assert isinstance(rows, list)
        rows[2]["status"] = "doing"

        completed = run_plan(document)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["decision"], "blocked")
        self.assertEqual(result["reason"], "active-member-claim")
        self.assertEqual(result["blocked_page_titles"], ["申请结果页"])
        self.assertNotIn("execution_order", result)

    def test_builds_one_external_icp_flow_job_from_the_verified_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "flow-input.json"
            input_path.write_text(
                json.dumps(base_input(), ensure_ascii=False), encoding="utf-8"
            )
            planned = subprocess.run(
                [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            plan_path = root / "flow-plan.json"
            plan_path.write_text(planned.stdout, encoding="utf-8")
            worktree = root / "worktree"
            worktree.mkdir()
            built = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-job",
                    "--plan",
                    str(plan_path),
                    "--worktree",
                    str(worktree),
                    "--base-revision",
                    "c" * 40,
                    "--platform",
                    "android-kotlin",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(built.returncode, 0, built.stderr)
        job = json.loads(built.stdout)
        self.assertEqual(job["kind"], "icp.external-flow-job.v3")
        self.assertEqual(job["flow_id"], json.loads(planned.stdout)["flow_id"])
        self.assertEqual(
            [member["title"] for member in job["members"]],
            ["申请首页", "职业信息页", "申请结果页"],
        )
        nodes = {node["node_id"]: node for node in job["execution_dag"]}
        self.assertEqual(
            nodes[page_node("申请结果页")]["allowed_paths"],
            ["app/src/main/ResultScreen.kt"],
        )
        self.assertEqual(job["execution_order"][-1], page_node("申请首页"))

    def test_built_job_is_accepted_by_the_real_icp_flow_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worktree = root / "worktree"
            worktree.mkdir()
            (worktree / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
            subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=IOLE Flow Selftest",
                    "-c",
                    "user.email=iole-flow@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=worktree,
                check=True,
            )
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            worktree = worktree.resolve()
            input_path = root / "flow-input.json"
            input_path.write_text(json.dumps(base_input()), encoding="utf-8")
            planned = subprocess.run(
                [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            plan_path = root / "flow-plan.json"
            plan_path.write_text(planned.stdout, encoding="utf-8")
            built = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-job",
                    "--plan",
                    str(plan_path),
                    "--worktree",
                    str(worktree),
                    "--base-revision",
                    revision,
                    "--platform",
                    "android-kotlin",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            job_path = root / "job.json"
            job_path.write_text(built.stdout, encoding="utf-8")
            prepared = subprocess.run(
                [sys.executable, str(ICP_FLOW_SCRIPT), "prepare", "--job", str(job_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        self.assertEqual(json.loads(prepared.stdout)["status"], "ready")

    def test_derives_one_stable_branch_for_every_member_and_review_round(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "flow-input.json"
            input_path.write_text(json.dumps(base_input()), encoding="utf-8")
            planned = subprocess.run(
                [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            plan_path = root / "flow-plan.json"
            plan_path.write_text(planned.stdout, encoding="utf-8")
            first = subprocess.run(
                [sys.executable, str(SCRIPT), "branch-name", "--plan", str(plan_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            second = subprocess.run(
                [sys.executable, str(SCRIPT), "branch-name", "--plan", str(plan_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        branch = json.loads(first.stdout)["branch_name"]
        self.assertRegex(branch, r"^codex/iole-flow-[0-9a-f]{12}-client-[0-9a-f]{12}$")

    def test_recovers_a_closed_flow_pr_from_current_dev_without_splitting_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "flow-input.json"
            input_path.write_text(json.dumps(base_input()), encoding="utf-8")
            planned = subprocess.run(
                [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            plan_path = root / "flow-plan.json"
            plan_path.write_text(planned.stdout, encoding="utf-8")
            recovered = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "pr-recovery-plan",
                    "--plan",
                    str(plan_path),
                    "--pr-url",
                    "https://git.example/team/app/pull/9",
                    "--mr-state",
                    "closed",
                    "--source-branch",
                    "missing",
                    "--dev-revision",
                    "d" * 40,
                    "--review-number",
                    "2",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        result = json.loads(recovered.stdout)
        self.assertEqual(result["action"], "inspect-from-dev")
        self.assertEqual(result["base_revision"], "d" * 40)
        self.assertEqual(
            result["member_titles"],
            ["申请首页", "职业信息页", "申请结果页"],
        )
        self.assertRegex(result["branch_name"], r"-recovery-[0-9a-f]{8}-r2$")

    def test_builds_one_terminal_intent_for_all_members_and_one_pr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "flow-input.json"
            input_path.write_text(json.dumps(base_input()), encoding="utf-8")
            planned = subprocess.run(
                [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            plan_path = root / "flow-plan.json"
            plan_path.write_text(planned.stdout, encoding="utf-8")
            intent_process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-review-writeback",
                    "--plan",
                    str(plan_path),
                    "--lease-token",
                    "flow-lease-1",
                    "--pr-url",
                    "https://git.example/team/app/pull/9",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(intent_process.returncode, 0, intent_process.stderr)
        intent = json.loads(intent_process.stdout)
        self.assertEqual(intent["connector_operation"], "complete_flow_rows")
        self.assertEqual(
            intent["member_titles"],
            ["申请首页", "职业信息页", "申请结果页"],
        )
        self.assertEqual(intent["set"]["status"], "review")
        self.assertEqual(intent["set"]["pr_url"], "https://git.example/team/app/pull/9")

    def test_builds_one_error_intent_that_keeps_every_member_doing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "flow-input.json"
            input_path.write_text(json.dumps(base_input()), encoding="utf-8")
            planned = subprocess.run(
                [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            plan_path = root / "flow-plan.json"
            plan_path.write_text(planned.stdout, encoding="utf-8")
            intent_process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-error-writeback",
                    "--plan",
                    str(plan_path),
                    "--lease-token",
                    "flow-lease-1",
                    "--error-code",
                    "worker/node-failed",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(intent_process.returncode, 0, intent_process.stderr)
        intent = json.loads(intent_process.stdout)
        self.assertEqual(intent["connector_operation"], "record_flow_error")
        self.assertEqual(intent["expected_status"], "doing")
        self.assertEqual(
            intent["member_titles"],
            ["申请首页", "职业信息页", "申请结果页"],
        )
        self.assertEqual(intent["set"]["last_error"], "worker/node-failed")
        self.assertEqual(
            intent["orchestrator_action"],
            {
                "notify_user_immediately": True,
                "stop_current_run": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
