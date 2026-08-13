#!/usr/bin/env python3
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("iole_contract_v1.py")
MAPPING = Path(__file__).parents[1] / "references" / "role-mapping-v1.json"
SOURCE_ID = "google-sheets:" + hashlib.sha256(
    json.dumps(
        {"sheet_name": "Sheet1", "spreadsheet_id": "book-a"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


def claim_digest(latest_review: dict[str, object] | None) -> str:
    immutable = {
        "source_id": SOURCE_ID,
        "row_id": "42",
        "role": "client",
        "design_source": "lanhu-figma",
        "design_ref": "https://design.example/page-42",
        "latest_review": latest_review,
        "page": {
            "title": "Loan home",
            "route": "/loan",
            "requirement": "实现贷款首页",
            "acceptance_criteria": ["UT: 组件测试通过"],
        },
    }
    return hashlib.sha256(
        json.dumps(
            immutable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class IoleContractV1Tests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_source_id_is_deterministic_for_one_provider_document_and_sheet(self) -> None:
        completed = self.run_cli(
            "source-id",
            "--provider",
            "google-sheets",
            "--spreadsheet-id",
            "book-a",
            "--sheet-name",
            "Sheet1",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["source_id"], SOURCE_ID)

    def test_branch_name_is_stable_across_review_rounds(self) -> None:
        arguments = (
            "branch-name",
            "--source-id",
            SOURCE_ID,
            "--role",
            "client",
            "--row-id",
            "42",
        )
        first = self.run_cli(*arguments)
        second = self.run_cli(*arguments)
        other_row = self.run_cli(*arguments[:-1], "43")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(other_row.returncode, 0, other_row.stderr)
        first_name = json.loads(first.stdout)["branch_name"]
        self.assertEqual(first_name, json.loads(second.stdout)["branch_name"])
        self.assertNotEqual(first_name, json.loads(other_row.stdout)["branch_name"])
        self.assertRegex(
            first_name,
            r"^codex/iole-[0-9a-f]{12}-client-[0-9a-f]{12}$",
        )

    def test_deleted_mr_branch_is_recovered_from_latest_dev(self) -> None:
        completed = self.run_cli(
            "pr-recovery-plan",
            "--source-id",
            SOURCE_ID,
            "--role",
            "client",
            "--row-id",
            "42",
            "--pr-url",
            "http://gitlab.example/client/merge_requests/1",
            "--mr-state",
            "merged",
            "--source-branch",
            "missing",
            "--dev-revision",
            "a" * 40,
            "--review-number",
            "1",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["action"], "inspect-from-dev")
        self.assertEqual(result["base_revision"], "a" * 40)
        self.assertEqual(result["changed_action"], "create-new-pr")
        self.assertEqual(result["unchanged_action"], "return-to-review")
        self.assertRegex(
            result["branch_name"],
            r"^codex/iole-[0-9a-f]{12}-client-[0-9a-f]{12}-recovery-[0-9a-f]{8}-r1$",
        )

    def test_existing_mr_branch_reuses_the_current_pr(self) -> None:
        completed = self.run_cli(
            "pr-recovery-plan",
            "--source-id",
            SOURCE_ID,
            "--role",
            "client",
            "--row-id",
            "42",
            "--pr-url",
            "http://gitlab.example/client/merge_requests/1",
            "--mr-state",
            "open",
            "--source-branch",
            "present",
            "--dev-revision",
            "a" * 40,
            "--review-number",
            "1",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["action"], "reuse-existing-pr")
        self.assertIsNone(result["base_revision"])
        self.assertIsNone(result["branch_name"])
        self.assertEqual(result["changed_action"], "update-existing-pr")
        self.assertEqual(result["unchanged_action"], "return-to-review")

    def test_terminal_mr_is_recovered_even_when_its_branch_still_exists(self) -> None:
        completed = self.run_cli(
            "pr-recovery-plan",
            "--source-id",
            SOURCE_ID,
            "--role",
            "client",
            "--row-id",
            "42",
            "--pr-url",
            "http://gitlab.example/client/merge_requests/1",
            "--mr-state",
            "closed",
            "--source-branch",
            "present",
            "--dev-revision",
            "b" * 40,
            "--review-number",
            "2",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["action"], "inspect-from-dev")
        self.assertEqual(result["base_revision"], "b" * 40)
        self.assertEqual(result["changed_action"], "create-new-pr")

    def test_role_mapping_rejects_unknown_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            mapping_path = Path(temporary_directory) / "mapping.json"
            mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
            mapping["unexpected"] = True
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            completed = self.run_cli(
                "role-config",
                "--mapping",
                str(mapping_path),
                "--role",
                "client",
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "invalid-input")

    def test_role_mapping_rejects_unknown_nested_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            mapping_path = Path(temporary_directory) / "mapping.json"
            mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
            mapping["job"]["page"]["unexpected"] = True
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            completed = self.run_cli(
                "role-config",
                "--mapping",
                str(mapping_path),
                "--role",
                "client",
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "invalid-input")

    def test_schedule_plan_binds_client_role_instead_of_raw_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            (project_root / "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-a/edit",
                "--role",
                "client",
                "--im",
                "5",
                "--project-root",
                str(project_root),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["role"], "client")
        self.assertEqual(result["worker_skill_name"], "icp")
        self.assertEqual(result["worker_skill"], "~/.agents/skills/icp/SKILL.md")
        self.assertEqual(result["rrule"], "FREQ=MINUTELY;INTERVAL=5")
        self.assertEqual(result["role_queue"]["status"], "frontend status")
        self.assertEqual(result["role_queue"]["pr_url"], "frontend pr")
        self.assertNotIn("watch_status", result)

    def test_backend_role_uses_only_backend_columns(self) -> None:
        completed = self.run_cli(
            "role-config", "--mapping", str(MAPPING), "--role", "backend"
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["queue"]["status"], "backend status")
        self.assertEqual(result["queue"]["pr_url"], "backend pr")
        self.assertEqual(result["queue"]["reviews"], "backend reviews")
        self.assertEqual(result["queue"]["lease_token"], "backend lease_token")

    def test_schedule_plan_rejects_a_role_without_a_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-a/edit",
                "--role",
                "backend",
                "--project-root",
                temporary_directory,
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["reason"], "role-worker-unavailable")

    def test_client_role_cannot_be_redirected_away_from_icp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project_root = root / "project"
            project_root.mkdir()
            (project_root / "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            worker_path = root / "other-skill.md"
            worker_path.write_text("# Other Skill\n", encoding="utf-8")
            mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
            mapping["roles"]["client"]["worker_skill_name"] = "other-skill"
            mapping["roles"]["client"]["worker_skill"] = str(worker_path)
            mapping_path = root / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-a/edit",
                "--role",
                "client",
                "--project-root",
                str(project_root),
                "--mapping",
                str(mapping_path),
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "client-worker-must-be-icp",
        )

    def test_non_client_role_dispatches_to_its_configured_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker_path = root / "api-worker.md"
            worker_path.write_text("# API Worker\n", encoding="utf-8")
            mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
            mapping["roles"]["backend"]["worker_skill_name"] = "api-worker"
            mapping["roles"]["backend"]["worker_skill"] = str(worker_path)
            mapping_path = root / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-a/edit",
                "--role",
                "backend",
                "--project-root",
                str(root),
                "--mapping",
                str(mapping_path),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["worker_skill_name"], "api-worker")
        self.assertEqual(result["worker_skill"], str(worker_path))
        self.assertIsNone(result["platform"])
        self.assertEqual(result["role_queue"]["status"], "backend status")

    def test_schedule_plan_reports_a_malformed_package_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            (project_root / "package.json").write_text(
                json.dumps({"dependencies": None, "devDependencies": {}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-a/edit",
                "--role",
                "client",
                "--project-root",
                str(project_root),
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "invalid-input")
        self.assertNotIn("Traceback", completed.stderr)

    def test_map_row_selects_latest_numbered_client_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            row_path = root / "row.json"
            output_path = root / "claim.json"
            row_path.write_text(
                json.dumps(
                    {
                        "编号": "42",
                        "frontend status": "doing",
                        "frontend lease_token": "lease-client-42",
                        "frontend lease_until": "2026-07-23T12:00:00Z",
                        "frontend pr": "http://gitlab.example/client/merge_requests/7",
                        "frontend last_error": "",
                        "frontend reviews": "1. 卡片间距错误\n2. 点击按钮没有跳转",
                        "设计稿地址": "https://design.example/page-42",
                        "标题": "Loan home",
                        "Route": "/loan",
                        "UI补充描述": "实现贷款首页",
                        "交互描述": "点击进入详情",
                        "接口描述": "读取贷款列表",
                        "UT": "",
                        "IT": "",
                        "E2E": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "map-row",
                "--mapping",
                str(MAPPING),
                "--role",
                "client",
                "--source-id",
                SOURCE_ID,
                "--row",
                str(row_path),
                "--output",
                str(output_path),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            inconsistent_row = json.loads(row_path.read_text(encoding="utf-8"))
            inconsistent_row["frontend pr"] = ""
            inconsistent_path = root / "inconsistent-row.json"
            inconsistent_path.write_text(
                json.dumps(inconsistent_row, ensure_ascii=False),
                encoding="utf-8",
            )
            inconsistent = self.run_cli(
                "map-row",
                "--mapping",
                str(MAPPING),
                "--role",
                "client",
                "--source-id",
                SOURCE_ID,
                "--row",
                str(inconsistent_path),
                "--output",
                str(root / "inconsistent-claim.json"),
            )
            self.assertEqual(inconsistent.returncode, 2, inconsistent.stderr)

        self.assertEqual(result["kind"], "iole.claimed-row.v1")
        self.assertEqual(result["role"], "client")
        self.assertEqual(result["source_id"], SOURCE_ID)
        self.assertEqual(result["page"]["acceptance_criteria"], [])
        self.assertEqual(result["latest_review"], {"number": 2, "text": "点击按钮没有跳转"})
        self.assertEqual(
            result["existing_pr_url"],
            "http://gitlab.example/client/merge_requests/7",
        )

    def test_map_row_reports_detailed_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            row_path = root / "row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "编号": "42",
                        "frontend status": "doing",
                        "frontend lease_token": "lease-client-42",
                        "frontend lease_until": "2026-07-23T12:00:00Z",
                        "frontend pr": "",
                        "frontend last_error": "",
                        "frontend reviews": "",
                        "设计稿地址": "https://design.example/page-42",
                        "标题": "",
                        "Route": "/loan",
                        "UI补充描述": "实现贷款首页",
                        "交互描述": "",
                        "接口描述": "",
                        "UT": "",
                        "IT": "",
                        "E2E": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "map-row",
                "--mapping",
                str(MAPPING),
                "--role",
                "client",
                "--source-id",
                SOURCE_ID,
                "--row",
                str(row_path),
                "--output",
                str(root / "claim.json"),
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["reason"], "invalid-row-data")
        self.assertEqual(result["detail"], "missing required fields: 标题")

    def test_build_job_emits_revise_client_job_for_icp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            claim_path = root / "claim.json"
            output_path = root / "job.json"
            worktree = root / "worktree"
            worktree.mkdir()
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "iole.claimed-row.v1",
                        "schema_version": 1,
                        "source_id": SOURCE_ID,
                        "role": "client",
                        "row_id": "42",
                        "status": "doing",
                        "lease_token": "lease-client-42",
                        "row_digest": claim_digest(
                            {"number": 2, "text": "点击按钮没有跳转"}
                        ),
                        "existing_pr_url": "http://gitlab.example/client/merge_requests/7",
                        "latest_review": {"number": 2, "text": "点击按钮没有跳转"},
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": {
                            "title": "Loan home",
                            "route": "/loan",
                            "requirement": "实现贷款首页",
                            "acceptance_criteria": ["UT: 组件测试通过"],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "build-job",
                "--claim",
                str(claim_path),
                "--worktree",
                str(worktree),
                "--base-revision",
                "b" * 40,
                "--platform",
                "nextjs",
                "--output",
                str(output_path),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            inconsistent_claim = json.loads(claim_path.read_text(encoding="utf-8"))
            inconsistent_claim["existing_pr_url"] = None
            inconsistent_path = root / "inconsistent-claim.json"
            inconsistent_path.write_text(
                json.dumps(inconsistent_claim, ensure_ascii=False),
                encoding="utf-8",
            )
            inconsistent = self.run_cli(
                "build-job",
                "--claim",
                str(inconsistent_path),
                "--worktree",
                str(worktree),
                "--base-revision",
                "a" * 40,
                "--platform",
                "nextjs",
                "--output",
                str(root / "inconsistent-job.json"),
            )
            self.assertEqual(inconsistent.returncode, 2, inconsistent.stderr)

        self.assertEqual(result["kind"], "icp.external-page-job.v2")
        self.assertEqual(result["role"], "client")
        self.assertEqual(result["mode"], "revise")
        self.assertEqual(result["review"], {"number": 2, "text": "点击按钮没有跳转"})
        source_digest = hashlib.sha256(SOURCE_ID.encode("utf-8")).hexdigest()[:12]
        self.assertIn(f":source-{source_digest}:", result["job_id"])
        self.assertIn(":review-2:", result["job_id"])

    def test_build_job_rejects_claim_content_that_does_not_match_its_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            claim_path = root / "claim.json"
            output_path = root / "job.json"
            worktree = root / "worktree"
            worktree.mkdir()
            page = {
                "title": "Loan home",
                "route": "/loan",
                "requirement": "原始需求",
                "acceptance_criteria": ["UT: 组件测试通过"],
            }
            immutable = {
                "source_id": SOURCE_ID,
                "row_id": "42",
                "role": "client",
                "design_source": "lanhu-figma",
                "design_ref": "https://design.example/page-42",
                "page": page,
                "latest_review": None,
            }
            digest = hashlib.sha256(
                json.dumps(
                    immutable,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            page["requirement"] = "被篡改的需求"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "iole.claimed-row.v1",
                        "schema_version": 1,
                        "source_id": SOURCE_ID,
                        "role": "client",
                        "row_id": "42",
                        "status": "doing",
                        "lease_token": "lease-client-42",
                        "row_digest": digest,
                        "existing_pr_url": None,
                        "latest_review": None,
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": page,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "build-job",
                "--claim",
                str(claim_path),
                "--worktree",
                str(worktree),
                "--base-revision",
                "b" * 40,
                "--platform",
                "nextjs",
                "--output",
                str(output_path),
            )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["reason"], "claim digest mismatch")

    def test_review_writeback_targets_only_the_client_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            claim_path = Path(temporary_directory) / "claim.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "iole.claimed-row.v1",
                        "schema_version": 1,
                        "source_id": SOURCE_ID,
                        "role": "client",
                        "row_id": "42",
                        "status": "doing",
                        "lease_token": "lease-client-42",
                        "row_digest": claim_digest(None),
                        "existing_pr_url": None,
                        "latest_review": None,
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": {
                            "title": "Loan home",
                            "route": "/loan",
                            "requirement": "实现贷款首页",
                            "acceptance_criteria": ["UT: 组件测试通过"],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "build-review-writeback",
                "--mapping",
                str(MAPPING),
                "--claim",
                str(claim_path),
                "--pr-url",
                "https://gitlab.example/client/merge_requests/8",
            )
            invalid_url = self.run_cli(
                "build-review-writeback",
                "--mapping",
                str(MAPPING),
                "--claim",
                str(claim_path),
                "--pr-url",
                "http://gitlab.example/client/merge_requests/8\ninjected",
            )
            error_writeback = self.run_cli(
                "build-error-writeback",
                "--mapping",
                str(MAPPING),
                "--claim",
                str(claim_path),
                "--error-code",
                "invalid-row-data",
                "--error-detail",
                "missing required fields: 标题, 设计稿地址",
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(invalid_url.returncode, 2, invalid_url.stderr)
        self.assertEqual(error_writeback.returncode, 0, error_writeback.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["columns"]["status"], "frontend status")
        self.assertEqual(result["columns"]["pr_url"], "frontend pr")
        self.assertEqual(result["set"]["status"], "review")
        self.assertEqual(
            result["set"]["pr_url"],
            "https://gitlab.example/client/merge_requests/8",
        )
        self.assertEqual(result["expected_row_digest"], claim_digest(None))
        self.assertIn("frontend reviews", result["guard_columns"])
        self.assertIn("frontend pr", result["guard_columns"])
        self.assertIn("UI补充描述", result["guard_columns"])
        self.assertNotIn("frontend status", result["guard_columns"])
        self.assertNotIn("frontend lease_token", result["guard_columns"])
        self.assertEqual(result["columns"]["last_error"], "frontend last_error")
        self.assertEqual(result["set"]["lease_token"], "")
        self.assertEqual(result["set"]["lease_until"], "")
        self.assertEqual(result["set"]["last_error"], "")
        error_result = json.loads(error_writeback.stdout)
        self.assertEqual(error_result["expected_status"], "doing")
        self.assertEqual(error_result["columns"]["last_error"], "frontend last_error")
        self.assertEqual(
            error_result["set"]["last_error"],
            "invalid-row-data: missing required fields: 标题, 设计稿地址",
        )
        self.assertEqual(
            error_result["orchestrator_action"],
            {
                "notify_user_immediately": True,
                "stop_current_run": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
