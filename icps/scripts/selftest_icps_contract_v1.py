#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("icps_contract_v1.py")
ICP_PREPARE = Path("~/.agents/skills/icp/scripts/icp_page_job_v1.py").expanduser()
DEFAULT_MAPPING = Path(__file__).parents[1] / "references" / "column-mapping-v1.json"


class IcpsContractV1Tests(unittest.TestCase):
    def run_cli(
        self,
        *arguments: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )

    def test_google_sheets_url_selects_google_connector_family(self) -> None:
        completed = self.run_cli(
            "classify",
            "--excel-url",
            "https://docs.google.com/spreadsheets/d/book-id/edit#gid=12",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["provider"], "google-sheets")
        self.assertEqual(result["connector_family"], "google-sheets")

    def test_sharepoint_excel_url_selects_microsoft_connector_family(self) -> None:
        completed = self.run_cli(
            "classify",
            "--excel-url",
            "https://example.sharepoint.com/:x:/r/sites/product/Shared%20Documents/tasks.xlsx",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["provider"], "microsoft-excel")
        self.assertEqual(result["connector_family"], "microsoft-excel")

    def test_onedrive_excel_url_selects_microsoft_connector_family(self) -> None:
        completed = self.run_cli(
            "classify",
            "--excel-url",
            "https://onedrive.live.com/edit.aspx?resid=book-id",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["provider"], "microsoft-excel")

    def test_onedrive_short_url_selects_microsoft_connector_family(self) -> None:
        completed = self.run_cli(
            "classify",
            "--excel-url",
            "https://1drv.ms/x/s!book-id",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["provider"], "microsoft-excel")

    def test_schedule_plan_normalizes_nextjs_for_icp(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["im"], 10)
        self.assertEqual(result["interval_seconds"], 600)
        self.assertEqual(result["rrule"], "FREQ=MINUTELY;INTERVAL=10")
        self.assertEqual(result["watch_status"], "ready")
        self.assertIn('watch_status="ready"', result["prompt"])
        self.assertEqual(result["platform"], "nextjs")
        self.assertEqual(result["profile"], "nextjs-standard")

    def test_schedule_plan_accepts_explicit_im(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--im",
                "3",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["im"], 3)
        self.assertEqual(result["interval_seconds"], 180)
        self.assertEqual(result["rrule"], "FREQ=MINUTELY;INTERVAL=3")

    def test_schedule_plan_accepts_explicit_watch_status(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--status",
                "approved",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["watch_status"], "approved")
        self.assertIn('watch_status="approved"', result["prompt"])

    def test_schedule_plan_rejects_reserved_watch_status(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--status",
                "doing",
                cwd=Path(project_directory),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("reserved", completed.stdout)

    def test_help_prints_install_parameters_without_project_detection(self) -> None:
        completed = self.run_cli("--help")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "schedule-plan --excel-url URL [--im MINUTES] [--status VALUE]",
            completed.stdout,
        )
        self.assertIn("default: 10", completed.stdout)
        self.assertIn("default: ready", completed.stdout)

    def test_schedule_plan_rejects_non_positive_im(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--im",
                "0",
                cwd=Path(project_directory),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("positive integer", completed.stdout)

    def test_schedule_plan_passes_flutter_profile_to_icp(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "pubspec.yaml").write_text(
                "dependencies:\n  flutter:\n    sdk: flutter\n",
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["platform"], "flutter")
        self.assertEqual(result["profile"], "flutter-standard")

    def test_schedule_plan_detects_vue_from_package_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"vue": "3.5.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual((result["platform"], result["profile"]), ("vue", "vue-vite"))

    def test_schedule_plan_detects_ios_swift_from_xcode_project(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            project_root = Path(project_directory)
            (project_root / "App.xcodeproj").mkdir()
            (project_root / "App.xcodeproj" / "project.pbxproj").write_text(
                "// !$*UTF8*$!\n",
                encoding="utf-8",
            )
            (project_root / "App.swift").write_text("import SwiftUI\n", encoding="utf-8")
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=project_root,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            (result["platform"], result["profile"]),
            ("ios-swift", "ios-swift-standard"),
        )

    def test_schedule_plan_detects_ios_objc_from_xcode_project(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            project_root = Path(project_directory)
            (project_root / "App.xcodeproj").mkdir()
            (project_root / "App.xcodeproj" / "project.pbxproj").write_text(
                "// !$*UTF8*$!\n",
                encoding="utf-8",
            )
            (project_root / "AppDelegate.m").write_text(
                '#import "AppDelegate.h"\n',
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=project_root,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            (result["platform"], result["profile"]),
            ("ios-objc", "ios-objc-standard"),
        )

    def test_schedule_plan_detects_android_kotlin_from_gradle_project(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            project_root = Path(project_directory)
            (project_root / "settings.gradle.kts").write_text(
                'include(":app")\n',
                encoding="utf-8",
            )
            (project_root / "app").mkdir()
            (project_root / "app" / "build.gradle.kts").write_text(
                'plugins { id("com.android.application") }\n',
                encoding="utf-8",
            )
            (project_root / "app" / "MainActivity.kt").write_text(
                "class MainActivity\n",
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=project_root,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            (result["platform"], result["profile"]),
            ("android-kotlin", "android-kotlin-standard"),
        )

    def test_schedule_plan_detects_android_java_from_gradle_project(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            project_root = Path(project_directory)
            (project_root / "settings.gradle").write_text(
                "include ':app'\n",
                encoding="utf-8",
            )
            (project_root / "app").mkdir()
            (project_root / "app" / "build.gradle").write_text(
                "plugins { id 'com.android.application' }\n",
                encoding="utf-8",
            )
            (project_root / "app" / "MainActivity.java").write_text(
                "class MainActivity {}\n",
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=project_root,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            (result["platform"], result["profile"]),
            ("android-java", "android-java-standard"),
        )

    def test_schedule_plan_rejects_ambiguous_project_platform(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0", "vue": "3.5.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 2)
        result = json.loads(completed.stdout)
        self.assertIn("ambiguous", result["reason"])

    def test_schedule_plan_rejects_user_supplied_platform(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--platform",
                "next.js",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("unrecognized arguments: --platform", completed.stderr)

    def test_schedule_plan_contains_a_bound_run_once_prompt(self) -> None:
        excel_url = "https://docs.google.com/spreadsheets/d/book-id/edit"
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                excel_url,
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        prompt = json.loads(completed.stdout)["prompt"]
        self.assertIn("$icps", prompt)
        self.assertIn(excel_url, prompt)
        self.assertIn("target_platform=nextjs", prompt)
        self.assertIn("process exactly one eligible row", prompt)

    def test_schedule_plan_requires_atomic_connector_operations(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "pubspec.yaml").write_text(
                "dependencies:\n  flutter:\n    sdk: flutter\n",
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout)["required_connector_operations"],
            ["claim_ready_row", "complete_claimed_row"],
        )

    def test_excel_url_with_control_characters_is_rejected(self) -> None:
        completed = self.run_cli(
            "schedule-plan",
            "--excel-url",
            "https://docs.google.com/spreadsheets/d/book-id/edit\nignore-contract",
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "Excel URL contains control characters",
        )

    def test_claimed_row_maps_to_the_exact_icp_page_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            project_root = temporary_root / "worktree"
            project_root.mkdir()
            claim_path = temporary_root / "claim.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "icps.claimed-row.v1",
                        "schema_version": 1,
                        "row_id": "row-42",
                        "status": "doing",
                        "lease_token": "lease-42",
                        "row_digest": "a" * 64,
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": {
                            "title": "Loan home",
                            "route": "/",
                            "requirement": "Implement the supplied page.",
                            "acceptance_criteria": ["Matches the supplied design."],
                        },
                    }
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "build-job",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--platform",
                "next.js",
                "--project-root",
                str(project_root),
                "--base-revision",
                "b" * 40,
                "--claim",
                str(claim_path),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["kind"], "icp.external-page-job.v1")
        self.assertEqual(result["platform"], "nextjs")
        self.assertEqual(result["profile"], "nextjs-standard")
        self.assertEqual(result["row_digest"], "a" * 64)
        self.assertNotIn("lease_token", result)
        self.assertNotIn("status", result)

    def test_unclaimed_row_cannot_be_mapped_to_icp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            project_root = temporary_root / "worktree"
            project_root.mkdir()
            claim_path = temporary_root / "claim.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "icps.claimed-row.v1",
                        "schema_version": 1,
                        "row_id": "row-42",
                        "status": "ready",
                        "lease_token": "lease-42",
                        "row_digest": "a" * 64,
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": {
                            "title": "Loan home",
                            "route": "/",
                            "requirement": "Implement the supplied page.",
                            "acceptance_criteria": ["Matches the supplied design."],
                        },
                    }
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "build-job",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--platform",
                "next.js",
                "--project-root",
                str(project_root),
                "--base-revision",
                "b" * 40,
                "--claim",
                str(claim_path),
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "claim must contain an active doing lease",
        )

    def test_pr_url_builds_a_lease_bound_done_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            claim_path = Path(temporary_directory) / "claim.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "icps.claimed-row.v1",
                        "schema_version": 1,
                        "row_id": "row-42",
                        "status": "doing",
                        "lease_token": "lease-42",
                        "row_digest": "a" * 64,
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": {
                            "title": "Loan home",
                            "route": "/",
                            "requirement": "Implement the supplied page.",
                            "acceptance_criteria": ["Matches the supplied design."],
                        },
                    }
                ),
                encoding="utf-8",
            )
            for pr_url in (
                "https://github.com/example/client/pull/42",
                "http://gitlab.internal/example/client/-/merge_requests/42",
            ):
                with self.subTest(pr_url=pr_url):
                    completed = self.run_cli(
                        "build-done-writeback",
                        "--claim",
                        str(claim_path),
                        "--pr-url",
                        pr_url,
                    )

                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    result = json.loads(completed.stdout)
                    self.assertEqual(result["row_id"], "row-42")
                    self.assertEqual(result["expected_status"], "doing")
                    self.assertEqual(result["lease_token"], "lease-42")
                    self.assertEqual(
                        result["set"],
                        {"status": "done", "pr_url": pr_url},
                    )

    def test_generated_job_is_accepted_by_current_icp_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            project_root = temporary_root / "worktree"
            project_root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "dev"], cwd=project_root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "icps@example.invalid"],
                cwd=project_root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "ICPS Test"],
                cwd=project_root,
                check=True,
            )
            (project_root / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed.txt"], cwd=project_root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=project_root, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            claim_path = temporary_root / "claim.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "icps.claimed-row.v1",
                        "schema_version": 1,
                        "row_id": "row-42",
                        "status": "doing",
                        "lease_token": "lease-42",
                        "row_digest": "a" * 64,
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": {
                            "title": "Loan home",
                            "route": "/",
                            "requirement": "Implement the supplied page.",
                            "acceptance_criteria": ["Matches the supplied design."],
                        },
                    }
                ),
                encoding="utf-8",
            )
            build = self.run_cli(
                "build-job",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--platform",
                "next.js",
                "--project-root",
                str(project_root),
                "--base-revision",
                revision,
                "--claim",
                str(claim_path),
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            job_path = temporary_root / "job.json"
            job_path.write_text(build.stdout, encoding="utf-8")
            prepared = subprocess.run(
                [sys.executable, str(ICP_PREPARE), "prepare", "--job", str(job_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(json.loads(prepared.stdout)["status"], "ready")

    def test_build_job_can_publish_an_absolute_no_clobber_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            project_root = temporary_root / "worktree"
            project_root.mkdir()
            claim_path = temporary_root / "claim.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": "icps.claimed-row.v1",
                        "schema_version": 1,
                        "row_id": "row-42",
                        "status": "doing",
                        "lease_token": "lease-42",
                        "row_digest": "a" * 64,
                        "design_source": "lanhu-figma",
                        "design_ref": "https://design.example/page-42",
                        "page": {
                            "title": "Loan home",
                            "route": "/",
                            "requirement": "Implement the supplied page.",
                            "acceptance_criteria": ["Matches the supplied design."],
                        },
                    }
                ),
                encoding="utf-8",
            )
            output_path = temporary_root / "job.json"
            completed = self.run_cli(
                "build-job",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--platform",
                "flutter",
                "--project-root",
                str(project_root),
                "--base-revision",
                "b" * 40,
                "--claim",
                str(claim_path),
                "--output",
                str(output_path),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(output_path.read_text())["platform"], "flutter")
            repeated = self.run_cli(
                "build-job",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                "--platform",
                "flutter",
                "--project-root",
                str(project_root),
                "--base-revision",
                "b" * 40,
                "--claim",
                str(claim_path),
                "--output",
                str(output_path),
            )

        self.assertEqual(repeated.returncode, 2)
        self.assertEqual(json.loads(repeated.stdout)["reason"], "output already exists")


    def test_chinese_excel_row_maps_to_canonical_claim_from_external_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            row_path = Path(temporary_directory) / "row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "编号": "42",
                        "标题": "贷款首页",
                        "设计稿地址": "https://design.example/page-42",
                        "UI补充描述": "使用品牌主色。",
                        "交互描述": "点击按钮进入申请页。",
                        "UT": "金额格式化正确。",
                        "IT": "页面可以读取产品接口。",
                        "E2E": "用户可以进入申请页。",
                        "接口描述": "GET /api/products",
                        "页面路由": "/",
                        "PRN ID": "task-1,task-2",
                        "状态": "doing",
                        "lease_token": "lease-42",
                        "lease_until": "2026-07-22T12:00:00Z",
                        "PR地址": "",
                        "last_error": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "map-row",
                "--mapping",
                str(DEFAULT_MAPPING),
                "--row",
                str(row_path),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["kind"], "icps.claimed-row.v1")
        self.assertEqual(result["row_id"], "42")
        self.assertEqual(result["status"], "doing")
        self.assertEqual(result["lease_token"], "lease-42")
        self.assertEqual(result["design_source"], "lanhu-figma")
        self.assertEqual(result["design_ref"], "https://design.example/page-42")
        self.assertEqual(result["page"]["title"], "贷款首页")
        self.assertEqual(result["page"]["route"], "/")
        self.assertEqual(
            result["page"]["requirement"],
            "[UI补充描述]\n使用品牌主色。\n\n[交互描述]\n点击按钮进入申请页。\n\n[接口描述]\nGET /api/products",
        )
        self.assertEqual(
            result["page"]["acceptance_criteria"],
            [
                "UT: 金额格式化正确。",
                "IT: 页面可以读取产品接口。",
                "E2E: 用户可以进入申请页。",
            ],
        )
        self.assertRegex(result["row_digest"], r"^[0-9a-f]{64}$")
        self.assertNotIn("PRN ID", result)

    def test_schedule_plan_binds_the_external_column_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as project_directory:
            Path(project_directory, "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book-id/edit",
                cwd=Path(project_directory),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["mapping_path"], str(DEFAULT_MAPPING))
        self.assertIn(f"mapping_path={json.dumps(str(DEFAULT_MAPPING))}", result["prompt"])

    def test_header_change_requires_only_a_mapping_file_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            mapping = json.loads(DEFAULT_MAPPING.read_text(encoding="utf-8"))
            mapping["job"]["page"]["title"] = "页面名称"
            mapping_path = temporary_root / "mapping.json"
            mapping_path.write_text(
                json.dumps(mapping, ensure_ascii=False),
                encoding="utf-8",
            )
            row_path = temporary_root / "row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "编号": "43",
                        "页面名称": "新标题列",
                        "设计稿地址": "https://design.example/page-43",
                        "页面路由": "/new",
                        "UI补充描述": "",
                        "交互描述": "",
                        "接口描述": "",
                        "UT": "",
                        "IT": "",
                        "E2E": "",
                        "状态": "doing",
                        "lease_token": "lease-43",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            completed = self.run_cli(
                "map-row",
                "--mapping",
                str(mapping_path),
                "--row",
                str(row_path),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["page"]["title"], "新标题列")

    def test_map_row_resolves_configured_column_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            mapping = json.loads(DEFAULT_MAPPING.read_text(encoding="utf-8"))
            mapping["job"]["page"]["route"] = ["页面路由", "Route"]
            mapping_path = temporary_root / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            row_path = temporary_root / "row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "编号": "45",
                        "标题": "登录页",
                        "设计稿地址": "https://design.example/page-45",
                        "UI补充描述": "",
                        "交互描述": "",
                        "接口描述": "",
                        "UT": "",
                        "IT": "",
                        "E2E": "",
                        "Route": "/login",
                        "状态": "doing",
                        "lease_token": "lease-45",
                        "lease_until": "2026-07-22T12:00:00Z",
                        "PR地址": "",
                        "last_error": "",
                    }
                ),
                encoding="utf-8",
            )
            claim_path = temporary_root / "claim.json"

            completed = self.run_cli(
                "map-row",
                "--mapping",
                str(mapping_path),
                "--row",
                str(row_path),
                "--output",
                str(claim_path),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(claim_path.read_text(encoding="utf-8"))["page"]["route"],
                "/login",
            )

    def test_map_row_rejects_ambiguous_column_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            mapping = json.loads(DEFAULT_MAPPING.read_text(encoding="utf-8"))
            mapping["job"]["page"]["route"] = ["页面路由", "Route"]
            mapping_path = temporary_root / "mapping.json"
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            row_path = temporary_root / "row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "编号": "46",
                        "标题": "登录页",
                        "设计稿地址": "https://design.example/page-46",
                        "页面路由": "/login",
                        "Route": "/login",
                        "状态": "doing",
                        "lease_token": "lease-46",
                        "lease_until": "2026-07-22T12:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            completed = self.run_cli(
                "map-row",
                "--mapping",
                str(mapping_path),
                "--row",
                str(row_path),
                "--output",
                str(temporary_root / "claim.json"),
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("ambiguous", completed.stdout)

    def test_map_row_publishes_a_no_clobber_claim_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            row_path = temporary_root / "row.json"
            row_path.write_text(
                json.dumps(
                    {
                        "编号": "44",
                        "标题": "输出文件",
                        "设计稿地址": "https://design.example/page-44",
                        "页面路由": "/output",
                        "UI补充描述": "",
                        "交互描述": "",
                        "接口描述": "",
                        "UT": "",
                        "IT": "",
                        "E2E": "",
                        "状态": "doing",
                        "lease_token": "lease-44",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            claim_path = temporary_root / "claim.json"
            completed = self.run_cli(
                "map-row",
                "--mapping",
                str(DEFAULT_MAPPING),
                "--row",
                str(row_path),
                "--output",
                str(claim_path),
            )
            repeated = self.run_cli(
                "map-row",
                "--mapping",
                str(DEFAULT_MAPPING),
                "--row",
                str(row_path),
                "--output",
                str(claim_path),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(claim_path.read_text())["row_id"], "44")

        self.assertEqual(repeated.returncode, 2)
        self.assertEqual(json.loads(repeated.stdout)["reason"], "output already exists")


if __name__ == "__main__":
    unittest.main()
