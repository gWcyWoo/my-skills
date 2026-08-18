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
MAPPING = Path(__file__).parents[1] / "references" / "role-mapping-v2.json"

OPERATIONAL_COLUMNS = {
    "标题",
    "PRN ID",
    "frontend status",
    "frontend pr",
    "frontend reviews",
    "frontend lease_token",
    "frontend lease_until",
    "frontend last_error",
    "backend status",
    "backend pr",
    "backend reviews",
    "backend lease_token",
    "backend lease_until",
    "backend last_error",
}


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def title_catalog(*titles: str) -> dict[str, object]:
    payload = {
        "spreadsheet_id": "book",
        "sheet_name": "Sheet1",
        "row_id_column": "标题",
        "titles": list(titles),
    }
    return {
        "kind": "icps.flow-title-catalog.v1",
        "schema_version": 1,
        **payload,
        "catalog_digest": canonical_digest(payload),
    }


def source_analysis_v2(
    raw_rows: dict[str, dict[str, str]],
    *,
    root_title: str,
    scopes: dict[str, str],
    references: dict[tuple[str, str], list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    references = references or {}
    return {
        "kind": "iole.source-analysis-input.v2",
        "schema_version": 2,
        "source_id": "google-sheets:"
        + canonical_digest({"sheet_name": "Sheet1", "spreadsheet_id": "book"}),
        "role": "client",
        "root_title": root_title,
        "rows": [
            {
                "title": title,
                "change_scope": scopes[title],
                "fields": [
                    {
                        "column": column,
                        "source_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                        "references": references.get((title, column), []),
                        "dismissals": [],
                    }
                    for column, value in row.items()
                    if column not in OPERATIONAL_COLUMNS
                ],
            }
            for title, row in raw_rows.items()
        ],
    }


def passing_closure_review(analysis: dict[str, object], catalog: dict[str, object]) -> dict[str, object]:
    field_reviews = [
        {
            "title": row["title"],
            "column": field["column"],
            "source_sha256": field["source_sha256"],
            "all_dependencies_identified": True,
            "reference_targets_correct": True,
            "dismissals_correct": True,
            "evidence": ["Compared the complete source field with the title catalog."],
            "issues": [],
        }
        for row in analysis["rows"]
        for field in row["fields"]
    ]
    return {
        "kind": "iole.source-closure-review.v1",
        "schema_version": 1,
        "analysis_sha256": canonical_digest(analysis),
        "title_catalog_digest": catalog["catalog_digest"],
        "decision": "pass",
        "field_reviews": field_reviews,
        "cross_review": {
            "every_business_field_reviewed": True,
            "no_unresolved_reference": True,
            "no_ambiguous_target": True,
            "evidence": ["Every relation and dismissal was checked against exact source spans."],
            "issues": [],
        },
    }


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
    def test_source_bundle_v2_compiles_directly_to_execution_plan(self) -> None:
        bundle = {
            "kind": "iole.flow-source-bundle.v2",
            "schema_version": 2,
            "source_id": "google-sheets:" + "a" * 64,
            "role": "client",
            "root_title": "登录",
            "row_data_columns": ["标题"],
            "members": [
                {
                    "title": "登录",
                    "change_scope": "modify",
                    "row_data": {"标题": "登录"},
                }
            ],
            "relations": [],
            "mapping_digest": "b" * 64,
            "source_closure": {"closure_digest": "c" * 64},
        }
        bundle["bundle_digest"] = canonical_digest(bundle)
        page_key = "page-login"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bundle_path = root / "source-bundle.json"
            bundle_path.write_text(
                json.dumps(bundle, ensure_ascii=False), encoding="utf-8"
            )
            component_lock = {
                "schema": "icp.component-design.lock.v6",
                "source_hashes": {
                    "iole_source_bundle_sha256": hashlib.sha256(
                        bundle_path.read_bytes()
                    ).hexdigest()
                },
                "source_context": {
                    "members": [
                        {
                            "title": "登录",
                            "page_key": page_key,
                            "change_scope": "modify",
                        }
                    ]
                },
            }
            lock_path = root / "component-lock.json"
            lock_path.write_text(
                json.dumps(component_lock, ensure_ascii=False), encoding="utf-8"
            )
            implementation_plan = {
                "schema": "icp.implementation.plan.v1",
                "component_lock_sha256": hashlib.sha256(
                    lock_path.read_bytes()
                ).hexdigest(),
                "page_keys": [page_key],
                "pages": [{"page_key": page_key, "member_title": "登录"}],
                "execution_nodes": [
                    {
                        "node_id": "foundation",
                        "kind": "foundation",
                        "page_keys": [],
                        "depends_on": [],
                        "case_ids": [],
                    },
                    {
                        "node_id": f"page:{page_key}",
                        "kind": "page",
                        "page_keys": [page_key],
                        "depends_on": ["foundation"],
                        "case_ids": ["case-login"],
                    },
                    {
                        "node_id": "flow-integration",
                        "kind": "flow-integration",
                        "page_keys": [page_key],
                        "depends_on": [f"page:{page_key}"],
                        "case_ids": [],
                    },
                ],
                "file_owners": {
                    "app/src/main/AndroidManifest.xml": "foundation",
                    "app/src/main/LoginScreen.kt": f"page:{page_key}",
                    "app/src/main/MainActivity.kt": "flow-integration",
                },
            }
            implementation_path = root / "implementation-plan.json"
            implementation_path.write_text(
                json.dumps(implementation_plan, ensure_ascii=False), encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "compile-execution-plan",
                    "--source-bundle",
                    str(bundle_path),
                    "--component-lock",
                    str(lock_path),
                    "--implementation-plan",
                    str(implementation_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            execution_path = root / "execution-plan.json"
            execution_path.write_text(completed.stdout, encoding="utf-8")
            branch = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "branch-name",
                    "--plan",
                    str(execution_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            error_writeback = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-error-writeback",
                    "--plan",
                    str(execution_path),
                    "--lease-token",
                    "lease-1",
                    "--error-code",
                    "node-failed",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["kind"], "iole.flow-execution-plan.v4")
        self.assertEqual(result["claim_page_titles"], ["登录"])
        self.assertEqual(result["page_keys"], [page_key])
        self.assertEqual(result["source_bundle_digest"], bundle["bundle_digest"])
        self.assertEqual(
            [node["node_id"] for node in result["execution_nodes"]],
            ["foundation", f"page:{page_key}", "flow-integration"],
        )
        self.assertEqual(
            result["file_owners"]["app/src/main/AndroidManifest.xml"], "foundation"
        )
        self.assertEqual(result["decision"], "ready")
        self.assertEqual(result["root_page_id"], page_key)
        self.assertEqual(set(result["member_digests"]), {page_key})
        self.assertEqual(branch.returncode, 0, branch.stdout + branch.stderr)
        self.assertEqual(
            error_writeback.returncode,
            0,
            error_writeback.stdout + error_writeback.stderr,
        )

    def test_source_bundle_rejects_legacy_analysis_without_closure_evidence(self) -> None:
        raw_rows = {
            "登录": {
                "标题": "登录",
                "Route": "signin",
                "设计稿地址": "无",
                "UI补充描述": "",
                "交互描述": "",
                "接口描述": "",
                "UT": "",
                "IT": "",
                "E2E": "",
                "frontend status": "ready",
                "frontend pr": "",
                "frontend reviews": "",
            }
        }
        analysis = {
            "kind": "iole.source-analysis-input.v1",
            "schema_version": 1,
            "source_id": "google-sheets:" + "0" * 64,
            "role": "client",
            "root_title": "登录",
            "rows": [
                {
                    "title": "登录",
                    "normalized_interaction": "",
                    "change_scope": "modify",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw.json"
            analysis_path = root / "analysis.json"
            raw_path.write_text(json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8")
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(raw_path),
                    "--analysis",
                    str(analysis_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("source closure", completed.stdout)

    def test_source_bundle_rejects_an_unresolved_ui_component_row_reference(self) -> None:
        def row(title: str, ui: str, interaction: str, status: str) -> dict[str, str]:
            return {
                "标题": title,
                "Route": "",
                "设计稿地址": "无",
                "UI补充描述": ui,
                "交互描述": interaction,
                "接口描述": "",
                "UT": "",
                "IT": "",
                "E2E": "",
                "frontend status": status,
                "frontend pr": "",
                "frontend reviews": "",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend last_error": "",
            }

        raw_rows = {
            "如何支付-visa": row(
                "如何支付-visa",
                "1.复用”公共组件--Bottom Drawer“组件",
                "",
                "ready",
            ),
            "公共组件--Bottom Drawer": row(
                "公共组件--Bottom Drawer",
                "padding: 16pt, radius: 24pt, background-color:#FFFFFF",
                "触发后，从底部向上弹起",
                "",
            ),
        }
        catalog = title_catalog(*raw_rows)
        analysis = source_analysis_v2(
            raw_rows,
            root_title="如何支付-visa",
            scopes={
                "如何支付-visa": "modify",
                "公共组件--Bottom Drawer": "context",
            },
        )
        review = passing_closure_review(analysis, catalog)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw-rows.json"
            catalog_path = root / "title-catalog.json"
            analysis_path = root / "analysis.json"
            review_path = root / "closure-review.json"
            raw_path.write_text(json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8")
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(raw_path),
                    "--title-catalog",
                    str(catalog_path),
                    "--analysis",
                    str(analysis_path),
                    "--closure-review",
                    str(review_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("unresolved title mention", completed.stdout)

    def test_source_bundle_includes_a_component_row_referenced_from_ui(self) -> None:
        def row(title: str, ui: str, interaction: str, status: str) -> dict[str, str]:
            return {
                "标题": title,
                "Route": "",
                "设计稿地址": "无",
                "UI补充描述": ui,
                "交互描述": interaction,
                "接口描述": "",
                "UT": "",
                "IT": "",
                "E2E": "",
                "frontend status": status,
                "frontend pr": "",
                "frontend reviews": "",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend last_error": "",
            }

        component_title = "公共组件--Bottom Drawer"
        ui = f"1.复用”{component_title}“组件"
        raw_rows = {
            "如何支付-visa": row("如何支付-visa", ui, "", "ready"),
            component_title: row(
                component_title,
                "padding: 16pt, radius: 24pt, background-color:#FFFFFF",
                "触发后，从底部向上弹起",
                "",
            ),
        }
        catalog = title_catalog(*raw_rows)
        start = ui.index(component_title)
        analysis = source_analysis_v2(
            raw_rows,
            root_title="如何支付-visa",
            scopes={"如何支付-visa": "modify", component_title: "context"},
            references={
                ("如何支付-visa", "UI补充描述"): [
                    {
                        "reference_id": "visa-ui-bottom-drawer",
                        "start": start,
                        "end": start + len(component_title),
                        "quote": component_title,
                        "target_title": component_title,
                        "relation_kind": "component",
                    }
                ]
            },
        )
        review = passing_closure_review(analysis, catalog)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw-rows.json"
            catalog_path = root / "title-catalog.json"
            analysis_path = root / "analysis.json"
            review_path = root / "closure-review.json"
            raw_path.write_text(json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8")
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(raw_path),
                    "--title-catalog",
                    str(catalog_path),
                    "--analysis",
                    str(analysis_path),
                    "--closure-review",
                    str(review_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        bundle = json.loads(completed.stdout)
        self.assertEqual(
            [(member["title"], member["change_scope"]) for member in bundle["members"]],
            [("如何支付-visa", "modify"), (component_title, "context")],
        )
        self.assertEqual(
            bundle["relations"],
            [{"from_title": "如何支付-visa", "to_title": component_title}],
        )
        self.assertEqual(bundle["members"][1]["design_refs"], [])
        self.assertIn("source_closure", bundle)

    def test_source_bundle_declares_owned_columns_and_ignores_extra_sheet_columns(self) -> None:
        raw_rows = {
            "登录": {
                "标题": "登录",
                "Route": "/login",
                "设计稿地址": "https://design.example/login",
                "UI补充描述": "显示手机号输入框",
                "交互描述": "",
                "接口描述": "",
                "UT": "只能输入数字",
                "IT": "",
                "E2E": "",
                "frontend status": "ready",
                "frontend pr": "",
                "frontend reviews": "",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend last_error": "",
            }
        }
        catalog = title_catalog("登录")
        analysis = source_analysis_v2(
            raw_rows,
            root_title="登录",
            scopes={"登录": "modify"},
        )
        review = passing_closure_review(analysis, catalog)
        raw_rows["登录"]["编号"] = "1001"
        raw_rows["登录"]["未声明备注"] = "must not enter ICP"

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw-rows.json"
            catalog_path = root / "title-catalog.json"
            analysis_path = root / "analysis.json"
            review_path = root / "closure-review.json"
            raw_path.write_text(json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8")
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(raw_path),
                    "--title-catalog",
                    str(catalog_path),
                    "--analysis",
                    str(analysis_path),
                    "--closure-review",
                    str(review_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        bundle = json.loads(completed.stdout)
        expected_columns = [
            "标题",
            "Route",
            "设计稿地址",
            "UI补充描述",
            "交互描述",
            "接口描述",
            "UT",
            "IT",
            "E2E",
        ]
        self.assertEqual(bundle["row_data_columns"], expected_columns)
        row_data = bundle["members"][0]["row_data"]
        self.assertEqual(list(row_data), expected_columns)
        self.assertEqual(row_data["UT"], "只能输入数字")
        self.assertIsNone(row_data["IT"])
        self.assertNotIn("编号", row_data)
        self.assertNotIn("未声明备注", row_data)

    def test_source_bundle_rejects_a_stale_business_field_hash(self) -> None:
        raw_rows = {
            "登录": {
                "标题": "登录",
                "Route": "signin",
                "设计稿地址": "无",
                "UI补充描述": "显示登录表单",
                "交互描述": "",
                "接口描述": "",
                "UT": "",
                "IT": "",
                "E2E": "",
                "frontend status": "ready",
                "frontend pr": "",
                "frontend reviews": "",
                "frontend lease_token": "",
                "frontend lease_until": "",
                "frontend last_error": "",
            }
        }
        catalog = title_catalog("登录")
        analysis = source_analysis_v2(
            raw_rows,
            root_title="登录",
            scopes={"登录": "modify"},
        )
        analysis["rows"][0]["fields"][0]["source_sha256"] = "0" * 64
        review = passing_closure_review(analysis, catalog)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paths = {
                "raw": root / "raw.json",
                "catalog": root / "catalog.json",
                "analysis": root / "analysis.json",
                "review": root / "review.json",
            }
            paths["raw"].write_text(json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8")
            paths["catalog"].write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            paths["analysis"].write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            paths["review"].write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(paths["raw"]),
                    "--title-catalog",
                    str(paths["catalog"]),
                    "--analysis",
                    str(paths["analysis"]),
                    "--closure-review",
                    str(paths["review"]),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("field hash mismatch", completed.stdout)

    def test_builds_source_bundle_with_empty_non_modify_queue_status(self) -> None:
        root_interaction = "点击支付说明 →「如何支付-visa」"
        raw_rows = {
            "登录相关": {
                "标题": "登录相关",
                "Route": "signin",
                "设计稿地址": (
                    "初始状态：https://design.example/signin-initial\n"
                    "手机号状态：https://design.example/signin-phone"
                ),
                "UI补充描述": "",
                "交互描述": root_interaction,
                "接口描述": "",
                "UT": "",
                "IT": "",
                "E2E": "",
                "frontend status": "ready",
                "frontend pr": "",
                "frontend reviews": "",
            },
            "如何支付-visa": {
                "标题": "如何支付-visa",
                "Route": "",
                "设计稿地址": "https://design.example/pay-visa",
                "UI补充描述": "",
                "交互描述": "",
                "接口描述": "",
                "UT": "",
                "IT": "",
                "E2E": "",
                "frontend status": "",
                "frontend pr": "",
                "frontend reviews": "",
            },
        }
        target = "如何支付-visa"
        start = root_interaction.index(target)
        catalog = title_catalog(*raw_rows)
        analysis = source_analysis_v2(
            raw_rows,
            root_title="登录相关",
            scopes={"登录相关": "modify", target: "navigate-only"},
            references={
                ("登录相关", "交互描述"): [
                    {
                        "reference_id": "login-payment-visa",
                        "start": start,
                        "end": start + len(target),
                        "quote": target,
                        "target_title": target,
                        "relation_kind": "navigation",
                    }
                ]
            },
        )
        review = passing_closure_review(analysis, catalog)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw-rows.json"
            catalog_path = root / "catalog.json"
            analysis_path = root / "analysis.json"
            review_path = root / "review.json"
            raw_path.write_text(
                json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8"
            )
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(raw_path),
                    "--title-catalog",
                    str(catalog_path),
                    "--analysis",
                    str(analysis_path),
                    "--closure-review",
                    str(review_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        bundle = json.loads(completed.stdout)
        self.assertEqual(bundle["kind"], "iole.flow-source-bundle.v2")
        self.assertEqual(bundle["root_title"], "登录相关")
        self.assertEqual(
            [(member["title"], member["change_scope"]) for member in bundle["members"]],
            [("登录相关", "modify"), ("如何支付-visa", "navigate-only")],
        )
        self.assertEqual(
            bundle["relations"],
            [{"from_title": "登录相关", "to_title": "如何支付-visa"}],
        )
        self.assertEqual(
            bundle["members"][0]["design_refs"],
            [
                {
                    "ordinal": 1,
                    "label": "初始状态",
                    "url": "https://design.example/signin-initial",
                },
                {
                    "ordinal": 2,
                    "label": "手机号状态",
                    "url": "https://design.example/signin-phone",
                },
            ],
        )
        self.assertIsNone(bundle["members"][1]["queue_status"])
        self.assertEqual(
            bundle["members"][1]["source_contract"]["design_ref"],
            raw_rows["如何支付-visa"]["设计稿地址"],
        )
        self.assertNotIn("allowed_paths", completed.stdout)
        self.assertNotIn("component_plan", completed.stdout)

    def test_source_bundle_allows_a_closed_cycle_through_read_only_context(self) -> None:
        def raw_row(title: str, interaction: str, status: str) -> dict[str, str]:
            return {
                "标题": title,
                "Route": "",
                "设计稿地址": f"https://design.example/{title}",
                "UI补充描述": "",
                "交互描述": interaction,
                "接口描述": "",
                "UT": "",
                "IT": "",
                "E2E": "",
                "frontend status": status,
                "frontend pr": "",
                "frontend reviews": "",
            }

        raw_rows = {
            "登录相关": raw_row("登录相关", "打开 Visa 说明", "ready"),
            "如何支付-visa": raw_row("如何支付-visa", "切换 Mastercard", ""),
            "如何支付-mastercard": raw_row(
                "如何支付-mastercard", "切换 Visa", ""
            ),
        }
        catalog = title_catalog(*raw_rows)
        references: dict[tuple[str, str], list[dict[str, object]]] = {}
        edges = [
            ("登录相关", "如何支付-visa"),
            ("如何支付-visa", "如何支付-mastercard"),
            ("如何支付-mastercard", "如何支付-visa"),
        ]
        for source, target in edges:
            source_text = raw_rows[source]["交互描述"]
            references[(source, "交互描述")] = [
                {
                    "reference_id": f"{source}-{target}",
                    "start": 0,
                    "end": len(source_text),
                    "quote": source_text,
                    "target_title": target,
                    "relation_kind": "navigation",
                }
            ]
        analysis = source_analysis_v2(
            raw_rows,
            root_title="登录相关",
            scopes={
                "登录相关": "modify",
                "如何支付-visa": "context",
                "如何支付-mastercard": "navigate-only",
            },
            references=references,
        )
        review = passing_closure_review(analysis, catalog)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw-rows.json"
            catalog_path = root / "catalog.json"
            analysis_path = root / "analysis.json"
            review_path = root / "review.json"
            raw_path.write_text(
                json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8"
            )
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(raw_path),
                    "--title-catalog",
                    str(catalog_path),
                    "--analysis",
                    str(analysis_path),
                    "--closure-review",
                    str(review_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        bundle = json.loads(completed.stdout)
        self.assertEqual(
            bundle["relations"],
            [
                {"from_title": "登录相关", "to_title": "如何支付-visa"},
                {
                    "from_title": "如何支付-visa",
                    "to_title": "如何支付-mastercard",
                },
                {
                    "from_title": "如何支付-mastercard",
                    "to_title": "如何支付-visa",
                },
            ],
        )

    def test_source_bundle_rejects_a_non_ready_modify_member(self) -> None:
        raw_row = {
            "标题": "登录相关",
            "Route": "signin",
            "设计稿地址": "https://design.example/signin",
            "UI补充描述": "",
            "交互描述": "",
            "接口描述": "",
            "UT": "",
            "IT": "",
            "E2E": "",
            "frontend status": "",
            "frontend pr": "",
            "frontend reviews": "",
        }
        raw_rows = {"登录相关": raw_row}
        catalog = title_catalog("登录相关")
        analysis = source_analysis_v2(
            raw_rows,
            root_title="登录相关",
            scopes={"登录相关": "modify"},
        )
        review = passing_closure_review(analysis, catalog)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw-rows.json"
            catalog_path = root / "catalog.json"
            analysis_path = root / "analysis.json"
            review_path = root / "review.json"
            raw_path.write_text(
                json.dumps(raw_rows, ensure_ascii=False),
                encoding="utf-8",
            )
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-source-bundle",
                    "--raw-rows",
                    str(raw_path),
                    "--title-catalog",
                    str(catalog_path),
                    "--analysis",
                    str(analysis_path),
                    "--closure-review",
                    str(review_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "modify page is not ready: 登录相关",
        )

    def test_lossless_review_writeback_accepts_a_complete_icp_v2_result(self) -> None:
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
            plan = json.loads(planned.stdout)
            plan["kind"] = "iole.flow-plan.v3"
            plan["schema_version"] = 3
            plan_path = root / "flow-plan-v3.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            changed_path = root / "app/src/main/Screen.kt"
            changed_path.parent.mkdir(parents=True, exist_ok=True)
            changed_path.write_text("// complete\n", encoding="utf-8")
            manifest_path = root / "manifest.json"
            manifest_path.write_text("{}\n", encoding="utf-8")
            result_path = root / "icp-result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-handoff-result.v2",
                        "schema_version": 2,
                        "job_id": "fixture-job",
                        "job_digest": "1" * 64,
                        "flow_id": plan["flow_id"],
                        "member_digests": plan["member_digests"],
                        "base_revision": "2" * 40,
                        "project_root": str(root.resolve()),
                        "status": "ready-for-pr",
                        "changed_files": ["app/src/main/Screen.kt"],
                        "verification": {
                            "node_tests": "passed",
                            "runtime_capture": "passed",
                            "visual": "passed",
                            "e2e": "passed",
                        },
                        "evidence_manifest": str(manifest_path.resolve()),
                        "evidence_manifest_digest": hashlib.sha256(
                            manifest_path.read_bytes()
                        ).hexdigest(),
                        "implementation_contract_sha256": "4" * 64,
                        "coverage": {
                            "status": "passed",
                            "required_clause_ids": ["clause-1"],
                            "covered_clause_ids": ["clause-1"],
                            "worker_evidence_digests": [
                                {"node_id": node_id, "sha256": "5" * 64}
                                for node_id in plan["execution_order"]
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            intent_process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-review-writeback",
                    "--plan",
                    str(plan_path),
                    "--lease-token",
                    "flow-lease-1",
                    "--mr",
                    "2",
                    "--pr-url",
                    "https://git.example/team/app/pull/9",
                    "--icp-result",
                    str(result_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            plan["kind"] = "iole.flow-execution-plan.v4"
            plan["schema_version"] = 4
            execution_plan_path = root / "flow-execution-plan-v4.json"
            execution_plan_path.write_text(json.dumps(plan), encoding="utf-8")
            execution_intent_process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-review-writeback",
                    "--plan",
                    str(execution_plan_path),
                    "--lease-token",
                    "flow-lease-1",
                    "--mr",
                    "2",
                    "--pr-url",
                    "https://git.example/team/app/pull/9",
                    "--icp-result",
                    str(result_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(intent_process.returncode, 0, intent_process.stdout + intent_process.stderr)
        self.assertEqual(
            execution_intent_process.returncode,
            0,
            execution_intent_process.stdout + execution_intent_process.stderr,
        )
        self.assertEqual(
            json.loads(intent_process.stdout)["connector_operation"],
            "complete_flow_rows",
        )

    def test_lossless_review_writeback_rejects_incomplete_icp_clause_coverage(self) -> None:
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
            plan = json.loads(planned.stdout)
            plan["kind"] = "iole.flow-plan.v3"
            plan["schema_version"] = 3
            plan_path = root / "flow-plan-v3.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            result_path = root / "icp-result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "kind": "icp.flow-handoff-result.v2",
                        "schema_version": 2,
                        "job_id": "fixture-job",
                        "job_digest": "1" * 64,
                        "flow_id": plan["flow_id"],
                        "member_digests": plan["member_digests"],
                        "base_revision": "2" * 40,
                        "project_root": str(root.resolve()),
                        "status": "ready-for-pr",
                        "changed_files": ["app/src/main/Screen.kt"],
                        "verification": {
                            "node_tests": "passed",
                            "runtime_capture": "passed",
                            "visual": "passed",
                            "e2e": "passed",
                        },
                        "evidence_manifest": str((root / "manifest.json").resolve()),
                        "evidence_manifest_digest": "3" * 64,
                        "implementation_contract_sha256": "4" * 64,
                        "coverage": {
                            "status": "passed",
                            "required_clause_ids": ["clause-1"],
                            "covered_clause_ids": [],
                            "worker_evidence_digests": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            intent_process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-review-writeback",
                    "--plan",
                    str(plan_path),
                    "--lease-token",
                    "flow-lease-1",
                    "--mr",
                    "2",
                    "--pr-url",
                    "https://git.example/team/app/pull/9",
                    "--icp-result",
                    str(result_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(intent_process.returncode, 2)
        self.assertEqual(
            json.loads(intent_process.stdout)["reason"],
            "ICP result acceptance coverage is incomplete",
        )

    def test_lossless_review_writeback_requires_a_verified_icp_v2_result(self) -> None:
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
            plan = json.loads(planned.stdout)
            plan["kind"] = "iole.flow-plan.v3"
            plan["schema_version"] = 3
            plan_path = root / "flow-plan-v3.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            intent_process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-review-writeback",
                    "--plan",
                    str(plan_path),
                    "--lease-token",
                    "flow-lease-1",
                    "--mr",
                    "2",
                    "--pr-url",
                    "https://git.example/team/app/pull/9",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(intent_process.returncode, 2)
        self.assertEqual(
            json.loads(intent_process.stdout)["reason"],
            "lossless review writeback requires a verified ICP v2 result",
        )

    def test_lossless_build_plan_rejects_an_input_without_raw_sheet_rows(self) -> None:
        ui_notes = "原始 UI 合同"
        raw_row = {
            "标题": "反馈",
            "Route": "feedback",
            "设计稿地址": "https://design.example/feedback",
            "UI补充描述": ui_notes,
            "交互描述": "原始交互合同",
            "接口描述": "",
            "UT": "",
            "IT": "",
            "E2E": "",
            "frontend status": "ready",
            "frontend pr": "",
            "frontend reviews": "",
        }
        analysis = {
            "kind": "iole.flow-analysis-input.v1",
            "schema_version": 1,
            "source_id": "google-sheets:" + "e" * 64,
            "role": "client",
            "root_title": "反馈",
            "rows": [
                {
                    "title": "反馈",
                    "normalized_interaction": "",
                    "change_scope": "modify",
                    "allowed_paths": ["app/src/main/FeedbackScreen.kt"],
                }
            ],
            "component_analysis": {
                "inventory_source": "project-scan",
                "searched_paths": ["app/src/main"],
                "summary": "Inspected feedback ownership.",
            },
            "component_plan": [],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw.json"
            analysis_path = root / "analysis.json"
            input_path = root / "input.json"
            raw_path.write_text(
                json.dumps({"反馈": raw_row}, ensure_ascii=False), encoding="utf-8"
            )
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )
            mapped = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-input",
                    "--raw-rows",
                    str(raw_path),
                    "--analysis",
                    str(analysis_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            input_path.write_text(mapped.stdout, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "build-plan", "--input", str(input_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(
            json.loads(completed.stdout)["reason"],
            "lossless build-plan requires raw Sheet rows and mapping",
        )

    def test_maps_raw_sheet_contract_losslessly_into_real_icp_node_job(self) -> None:
        ui_notes = (
            "俄语：Проблема с входом\n"
            "Ошибка при оплате / выводе средств\n"
            "Вопрос по договору или условиям займа\n"
            "Не получил(а) уведомление или код\n"
            "Другое\n"
            "哈语：Кіру кезінде мәселе\n"
            "Төлем немесе қаражатты шығару кезінде қате\n"
            "Келісімшарт немесе қарыз шарттары бойынша сұрақ\n"
            "Хабарлама немесе растау кодын алмадым\n"
            "Басқа"
        )
        interaction = (
            "提交成功：Спасибо за ваш отзыв!\n\n返回到上一页\n"
            "检验：\n请选择问题类型：Пожалуйста, выберите категорию проблемы\n"
            "请输入反馈内容：Пожалуйста, введите содержание отзыва\n"
            "反馈内容不能超过500个字符："
            "Содержание отзыва не должно превышать 500 символов"
        )
        raw_row = {
            "标题": "反馈",
            "Route": "\nfeedback",
            "设计稿地址": "https://design.example/feedback\n",
            "UI补充描述": ui_notes,
            "交互描述": interaction,
            "接口描述": "",
            "UT": "",
            "IT": "",
            "E2E": "",
            "frontend status": "ready",
            "frontend pr": "",
            "frontend reviews": "",
            "frontend lease_token": "must-not-reach-icp",
            "frontend lease_until": "2099-01-01T00:00:00Z",
            "frontend last_error": "must-not-reach-icp",
        }
        analysis = {
            "kind": "iole.flow-analysis-input.v1",
            "schema_version": 1,
            "source_id": "google-sheets:" + "f" * 64,
            "role": "client",
            "root_title": "反馈",
            "rows": [
                {
                    "title": "反馈",
                    "normalized_interaction": "",
                    "change_scope": "modify",
                    "allowed_paths": ["app/src/main/FeedbackScreen.kt"],
                }
            ],
            "component_analysis": {
                "inventory_source": "project-scan",
                "searched_paths": ["app/src/main"],
                "summary": "Inspected the feedback feature boundary.",
            },
            "component_plan": [],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_path = root / "raw-rows.json"
            analysis_path = root / "analysis.json"
            input_path = root / "flow-input.json"
            plan_path = root / "flow-plan.json"
            job_path = root / "flow-job.json"
            raw_path.write_text(
                json.dumps({"反馈": raw_row}, ensure_ascii=False), encoding="utf-8"
            )
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )
            mapped = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-input",
                    "--raw-rows",
                    str(raw_path),
                    "--analysis",
                    str(analysis_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(mapped.returncode, 0, mapped.stdout + mapped.stderr)
            input_path.write_text(mapped.stdout, encoding="utf-8")
            planned = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-plan",
                    "--input",
                    str(input_path),
                    "--raw-rows",
                    str(raw_path),
                    "--mapping",
                    str(MAPPING),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
            plan_path.write_text(planned.stdout, encoding="utf-8")

            worktree = root / "worktree"
            worktree.mkdir()
            (worktree / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
            subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=IOLE Lossless Selftest",
                    "-c",
                    "user.email=iole-lossless@example.invalid",
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
            built = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-job",
                    "--plan",
                    str(plan_path),
                    "--worktree",
                    str(worktree.resolve()),
                    "--base-revision",
                    revision,
                    "--platform",
                    "android-kotlin",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            job_path.write_text(built.stdout, encoding="utf-8")
            job = json.loads(built.stdout)
            self.assertEqual(job["kind"], "icp.external-flow-job.v5")
            self.assertEqual(job["schema_version"], 5)
            member = job["members"][0]
            source_contract = member["source_contract"]
            self.assertEqual(source_contract["title"], raw_row["标题"])
            self.assertEqual(source_contract["route"], raw_row["Route"])
            self.assertEqual(source_contract["design_ref"], raw_row["设计稿地址"])
            self.assertEqual(source_contract["interaction"], interaction)
            self.assertEqual(
                source_contract["requirement_sections"],
                [
                    {"label": "UI补充描述", "value": ui_notes},
                    {"label": "交互描述", "value": interaction},
                    {"label": "接口描述", "value": ""},
                ],
            )
            self.assertEqual(
                source_contract["acceptance_sections"],
                [
                    {"prefix": "UT", "value": ""},
                    {"prefix": "IT", "value": ""},
                    {"prefix": "E2E", "value": ""},
                ],
            )
            self.assertEqual(member["interaction"], interaction)
            self.assertIn(ui_notes, member["requirement"])
            self.assertNotIn("must-not-reach-icp", built.stdout)

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
        self.assertEqual(result["mr"], 0)
        self.assertEqual(result["mapping_path"], str(MAPPING))
        self.assertEqual(
            result["required_connector_operations"],
            [
                "inspect_ready_flow_root",
                "inspect_title_catalog",
                "inspect_flow_rows",
                "claim_flow_rows",
                "release_flow_claim",
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

    def test_schedule_binds_each_delivery_mode_and_rejects_unknown_mode(self) -> None:
        for mr in (1, 2):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "schedule-plan",
                    "--excel-url",
                    "https://docs.google.com/spreadsheets/d/book/edit",
                    "--role",
                    "client",
                    "--mr",
                    str(mr),
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
            self.assertEqual(result["mr"], mr)
            self.assertEqual(
                json.loads(result["prompt"].split(" with ", 1)[1])["mr"], mr
            )

        rejected = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "schedule-plan",
                "--excel-url",
                "https://docs.google.com/spreadsheets/d/book/edit",
                "--role",
                "client",
                "--mr",
                "3",
                "--project-root",
                str(Path.cwd()),
                "--mapping",
                str(MAPPING),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(json.loads(rejected.stdout)["reason"], "mr must be 0, 1, or 2")

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
                    "--mr",
                    "2",
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

    def test_default_delivery_builds_review_intent_without_pr(self) -> None:
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
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            direct_process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-review-writeback",
                    "--plan",
                    str(plan_path),
                    "--lease-token",
                    "flow-lease-1",
                    "--mr",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(intent_process.returncode, 0, intent_process.stderr)
        intent = json.loads(intent_process.stdout)
        self.assertEqual(intent["mr"], 0)
        self.assertEqual(intent["set"]["status"], "review")
        self.assertIsNone(intent["set"]["pr_url"])

        self.assertEqual(direct_process.returncode, 0, direct_process.stderr)
        direct = json.loads(direct_process.stdout)
        self.assertEqual(direct["mr"], 1)
        self.assertIsNone(direct["set"]["pr_url"])

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
