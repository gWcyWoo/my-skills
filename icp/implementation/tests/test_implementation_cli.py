from __future__ import annotations

import hashlib
import importlib
import json
import argparse
import copy
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

STAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = STAGE_ROOT / "scripts" / "implementation.py"
IOLE_SCRIPT = STAGE_ROOT.parents[1] / "iole" / "scripts" / "iole_flow_contract_v2.py"
COMPONENT_TESTS = importlib.import_module(
    "icp.component-design.tests.test_component_design_v4_cli"
)
IMPLEMENTATION = importlib.import_module(
    "icp.implementation.scripts.implementation"
)
COMPONENT_DESIGN = COMPONENT_TESTS.COMPONENT_DESIGN
EXTRACT_FIXTURE = importlib.import_module("icp.component-design.tests.extract_fixture")
read_json = COMPONENT_TESTS.read_json
write_json = COMPONENT_TESTS.write_json
canonical_digest = COMPONENT_TESTS.canonical_digest
page_key_for = COMPONENT_DESIGN.page_key_for

EIGHT_PAGE_TOPOLOGY = read_json(
    STAGE_ROOT / "tests" / "fixtures" / "eight-page-navigation-topology.json"
)
EIGHT_PAGE_ROUTE_CHAINS = {
    "登录": [],
    "客服弹窗": [("登录", "客服弹窗")],
    "反馈": [("登录", "反馈")],
    "登录文件-弹窗": [("登录", "登录文件-弹窗")],
    "登录-验证码": [("登录", "登录-验证码")],
    "反馈上传弹窗": [("登录", "反馈"), ("反馈", "反馈上传弹窗")],
    "权限-相机": [
        ("登录", "反馈"),
        ("反馈", "反馈上传弹窗"),
        ("反馈上传弹窗", "权限-相机"),
    ],
    "权限-相册": [
        ("登录", "反馈"),
        ("反馈", "反馈上传弹窗"),
        ("反馈上传弹窗", "权限-相册"),
    ],
}


class ImplementationTestModuleIsolationTest(unittest.TestCase):
    def test_module_does_not_reexport_the_stage_two_test_case(self) -> None:
        self.assertNotIn("ComponentDesignV4CliTest", globals())


def case_for_interaction(
    universe: dict, plan: dict, page_key: str, interaction_id: str
) -> dict:
    """The integration case frozen for one exact graph interaction."""

    interaction_by_obligation = {
        item["obligation_id"]: item.get("interaction_id")
        for item in universe["integration_obligations"]
    }
    return next(
        case
        for case in plan["integration_test_cases"]
        if case["page_key"] == page_key
        and interaction_by_obligation.get(case["obligation_id"]) == interaction_id
    )


def eight_page_design_url(index: int) -> str:
    return (
        "https://lanhuapp.com/web/#/item/project/detailDetach?"
        f"pid=project-1&image_id=image-eight{index}&fromEditor=true"
    )


def authored_layout_decisions(universe: dict) -> list[dict]:
    result: list[dict] = []
    for selection in universe["layout_selection_inputs"]:
        decisions = []
        for obligation in selection["decision_obligations"]:
            vertical = obligation["scope"] == "slots" or len(obligation["member_ids"]) > 1
            decisions.append(
                {
                    "decision_id": obligation["decision_id"],
                    "scope": obligation["scope"],
                    "parent_instance_id": obligation["parent_instance_id"],
                    "slot": obligation["slot"],
                    "ordered_member_ids": obligation["member_ids"],
                    "layout_kind": "flow",
                    "main_axis": "vertical" if vertical else "none",
                    "sizing_policy": {"width": "constraint", "height": "content"},
                    "alignment_policy": "source_evidence",
                    "constraints": [],
                    "overflow_policy": "reachable",
                    "evidence_ids": obligation["evidence_ids"],
                    "rationale": "Use component topology and frozen source evidence.",
                }
            )
        result.append(
            {
                "design_state_id": selection["design_state_id"],
                "decisions": decisions,
            }
        )
    return result


def create_eight_page_extract(root: Path) -> Path:
    members = EIGHT_PAGE_TOPOLOGY["members"]
    project = root / "project"
    project.mkdir(parents=True)
    urls_path = root / "urls.json"
    reference_path = root / "reference.png"
    reference_path.write_bytes(EXTRACT_FIXTURE.PNG_1X1)
    assets_path = root / "assets"
    assets_path.mkdir()
    (assets_path / "fixture.png").write_bytes(EXTRACT_FIXTURE.PNG_1X1)
    write_json(
        urls_path,
        {
            "schema": "icp.extract.run-input.v2",
            "designs": [
                {
                    "design_url": eight_page_design_url(index),
                    "ui_supplement": member["ui"],
                }
                for index, member in enumerate(members, start=1)
            ],
        },
    )
    result = EXTRACT_FIXTURE.run_command(
        EXTRACT_FIXTURE.EXTRACT_SCRIPT,
        "begin-run",
        "--project-root",
        str(project),
        "--urls-file",
        str(urls_path),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    for index, member in enumerate(members, start=1):
        suffix = f"eight{index}"
        source_path = root / f"source-{suffix}.json"
        write_json(
            source_path,
            EXTRACT_FIXTURE.source_for(
                member["title"], suffix, eight_page_design_url(index)
            ),
        )
        result = EXTRACT_FIXTURE.run_command(
            EXTRACT_FIXTURE.EXTRACT_SCRIPT,
            "prepare",
            "--project-root",
            str(project),
            "--source-json",
            str(source_path),
            "--reference-image",
            str(reference_path),
            "--assets-dir",
            str(assets_path),
            "--allow-loose-input",
            "--design-url",
            eight_page_design_url(index),
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        EXTRACT_FIXTURE.complete_extract_design(project, member["title"], suffix)
    result = EXTRACT_FIXTURE.run_command(
        EXTRACT_FIXTURE.EXTRACT_SCRIPT, "verify-run", "--project-root", str(project)
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return project


def run_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class ImplementationCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        COMPONENT_TESTS.ComponentDesignV4CliTest.setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        COMPONENT_TESTS.ComponentDesignV4CliTest.tearDownClass()

    def setUp(self) -> None:
        self.fixture = COMPONENT_TESTS.ComponentDesignV4CliTest(
            methodName="test_designless_context_with_business_data_gets_a_source_only_work_item"
        )
        self.fixture.setUp()
        self.project = self.fixture.project
        self.common_rules_text = (
            "# Common rules\n\n"
            "When no language is selected, use Russian or Kazakh from the system locale; "
            "otherwise default to Russian.\n"
        )
        (self.project / "common-rules.md").write_text(
            self.common_rules_text, encoding="utf-8"
        )
        self.fixture.seal_all_pages()
        recorded = self.fixture.record_abstraction(self.fixture.valid_abstraction_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        verified = self.fixture.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.stage_dir = self.project / ".icp" / "implementation"

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def begin(self) -> subprocess.CompletedProcess[str]:
        return run_command(
            "begin",
            "--project-root",
            str(self.project),
            "--platform",
            "android-kotlin",
        )

    def test_begin_recovers_uncommitted_artifacts_and_is_idempotent_after_commit(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        expected_state = read_json(self.stage_dir / "state.json")
        (self.stage_dir / "state.json").unlink()

        recovered = self.begin()
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual(read_json(self.stage_dir / "state.json"), expected_state)

        repeated = self.begin()
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertTrue(json.loads(repeated.stdout)["resumed"])

    def test_stage_writer_lock_times_out_without_publishing_implementation_state(self) -> None:
        lock_fd = os.open(self.project, os.O_RDONLY)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            result = run_command(
                "begin",
                "--project-root",
                str(self.project),
                "--platform",
                "android-kotlin",
                "--lock-timeout-seconds",
                "0.05",
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

        self.assertEqual(result.returncode, 2)
        self.assertIn('"error": "stage_busy"', result.stderr)
        self.assertFalse(self.stage_dir.exists())

    def test_current_icp_artifacts_compile_directly_into_iole(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        compiled = subprocess.run(
            [
                sys.executable,
                str(IOLE_SCRIPT),
                "compile-execution-plan",
                "--source-bundle",
                str(
                    self.project
                    / ".icp"
                    / "source"
                    / "source-bundle.json"
                ),
                "--component-lock",
                str(
                    self.project
                    / ".icp"
                    / "component-design"
                    / "component-lock.json"
                ),
                "--implementation-plan",
                str(self.stage_dir / "implementation-plan.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        execution_plan = json.loads(compiled.stdout)
        self.assertEqual(execution_plan["page_keys"], read_json(
            self.stage_dir / "implementation-plan.json"
        )["page_keys"])
        self.assertEqual(
            execution_plan["implementation_plan_sha256"],
            hashlib.sha256(
                (self.stage_dir / "implementation-plan.json").read_bytes()
            ).hexdigest(),
        )

    def test_verified_icp_stage_result_unlocks_current_iole_review_writeback(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _, evidence = self.prepare_verifiable_implementation(plan)
        verified = self.verify_implementation(evidence)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        compiled = subprocess.run(
            [
                sys.executable,
                str(IOLE_SCRIPT),
                "compile-execution-plan",
                "--source-bundle",
                str(self.project / ".icp" / "source" / "source-bundle.json"),
                "--component-lock",
                str(self.project / ".icp" / "component-design" / "component-lock.json"),
                "--implementation-plan",
                str(self.stage_dir / "implementation-plan.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        execution_path = self.project / "execution-plan.json"
        execution_path.write_text(compiled.stdout, encoding="utf-8")

        writeback = subprocess.run(
            [
                sys.executable,
                str(IOLE_SCRIPT),
                "build-review-writeback",
                "--plan",
                str(execution_path),
                "--lease-token",
                "lease-1",
                "--icp-result",
                str(self.stage_dir / "stage-result.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(writeback.returncode, 0, writeback.stdout + writeback.stderr)
        self.assertEqual(
            json.loads(writeback.stdout)["connector_operation"],
            "complete_flow_rows",
        )

    def test_iole_compiles_original_cli_bundle_after_icp_snapshot_normalization(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        for source_bundle in (
            self.fixture.bundle_path,
            self.fixture.root / "reformatted-bundle.json",
        ):
            if source_bundle != self.fixture.bundle_path:
                bundle = read_json(self.fixture.bundle_path)
                source_bundle.write_text(
                    json.dumps(
                        dict(reversed(list(bundle.items()))),
                        ensure_ascii=False,
                        indent=4,
                    ),
                    encoding="utf-8",
                )
            compiled = subprocess.run(
                [
                    sys.executable,
                    str(IOLE_SCRIPT),
                    "compile-execution-plan",
                    "--source-bundle",
                    str(source_bundle),
                    "--component-lock",
                    str(
                        self.project
                        / ".icp"
                        / "component-design"
                        / "component-lock.json"
                    ),
                    "--implementation-plan",
                    str(self.stage_dir / "implementation-plan.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

    def test_iole_rejects_semantically_changed_bundle_after_rehash(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        bundle = read_json(self.fixture.bundle_path)
        bundle["members"][0]["row_data"]["Route"] = "/changed"
        bundle["bundle_digest"] = canonical_digest(
            {key: value for key, value in bundle.items() if key != "bundle_digest"}
        )
        changed_path = self.fixture.root / "semantically-changed-bundle.json"
        write_json(changed_path, bundle)
        compiled = subprocess.run(
            [
                sys.executable,
                str(IOLE_SCRIPT),
                "compile-execution-plan",
                "--source-bundle",
                str(changed_path),
                "--component-lock",
                str(
                    self.project
                    / ".icp"
                    / "component-design"
                    / "component-lock.json"
                ),
                "--implementation-plan",
                str(self.stage_dir / "implementation-plan.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(compiled.returncode, 2, compiled.stdout + compiled.stderr)
        self.assertIn("component lock targets another source bundle", compiled.stdout)

    def test_stage3_consumes_only_the_closed_component_contract_not_raw_source(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)

        universe = read_json(self.stage_dir / "coverage-universe.json")
        plan_input = read_json(self.stage_dir / "implementation-plan.input.json")
        forbidden_keys = {
            "source_authority",
            "source_coverage",
            "source_refs",
            "source_ref",
            "source_text",
            "quote",
            "row_data",
            "source_contract",
        }

        def collect_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(collect_keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(collect_keys(item) for item in value)) if value else set()
            return set()

        self.assertFalse(forbidden_keys & collect_keys(universe))
        self.assertFalse(forbidden_keys & collect_keys(plan_input))
        self.assertEqual(
            universe["source_identity"],
            read_json(
                self.project / ".icp" / "component-design" / "component-lock.json"
            )["implementation_contract"]["source_identity"],
        )

    def test_begin_freezes_the_complete_input_derived_implementation_checklist(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")

        checklist = read_json(self.stage_dir / "checklist.json")
        expected = ["stage.begin", "plan.record", "build.clean"]
        for obligation in universe["integration_obligations"]:
            obligation_id = obligation["obligation_id"]
            expected.extend(
                [
                    f"case:{obligation_id}.red",
                    f"case:{obligation_id}.green",
                ]
            )
        expected.extend(
            f"implementation.code-coverage:{page_key}"
            for page_key in universe["page_keys"]
        )
        expected.append("implementation.code-coverage")
        for page_key in universe["page_keys"]:
            expected.extend(
                [
                    f"responsive:{page_key}.compact",
                    f"responsive:{page_key}.expanded",
                ]
            )
        for item in universe["visual_references"]:
            expected.extend(
                [
                    f"visual:{item['design_name']}.capture",
                    f"visual:{item['design_name']}.verify",
                ]
            )
        expected.extend(["verification.commands", "stage.verify"])

        self.assertEqual(checklist["stage"], "implementation")
        self.assertEqual(
            [item["node_id"] for item in checklist["nodes"]], expected
        )
        self.assertEqual(checklist["nodes"][0]["status"], "completed")
        self.assertTrue(
            all(item["status"] == "pending" for item in checklist["nodes"][1:])
        )

    def test_stage3_starts_and_continues_after_stage2_source_is_unavailable(self) -> None:
        shutil.rmtree(self.project / ".icp" / "source")

        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def begin_component_stage(
        self,
        *,
        bundle_kwargs: dict | None = None,
        page_facts_transform=None,
        plan_transform=None,
    ) -> None:
        """Re-run Stage-2 with a custom bundle/page facts/plan, then begin Stage-3 on it."""

        fixture = COMPONENT_TESTS.ComponentDesignV4CliTest(
            methodName="test_designless_context_with_business_data_gets_a_source_only_work_item"
        )
        fixture.setUp()
        try:
            if bundle_kwargs:
                fixture.bundle_path = fixture.build_source_bundle(**bundle_kwargs)
            (fixture.project / "common-rules.md").write_text(
                self.common_rules_text, encoding="utf-8"
            )
            begun = fixture.begin()
            self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
            for page in reversed(json.loads(begun.stdout)["pages"]):
                facts = fixture.valid_page_facts(page)
                if page_facts_transform is not None:
                    facts = page_facts_transform(page, facts)
                recorded = fixture.record_page(page, facts)
                self.assertEqual(
                    recorded.returncode, 0, recorded.stdout + recorded.stderr
                )
            plan = fixture.valid_abstraction_plan()
            if plan_transform is not None:
                plan = plan_transform(plan)
            recorded = fixture.record_abstraction(plan)
            self.assertEqual(
                recorded.returncode, 0, recorded.stdout + recorded.stderr
            )
            verified = fixture.verify()
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        except BaseException:
            fixture.tearDown()
            raise
        old_fixture = self.fixture
        self.fixture = fixture
        self.project = fixture.project
        self.stage_dir = fixture.project / ".icp" / "implementation"
        old_fixture.tearDown()
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)

    def valid_plan(self) -> dict:
        plan = read_json(self.stage_dir / "implementation-plan.input.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        instances_by_page: dict[str, list[dict]] = {}
        for instance in universe["component_instances"]:
            instances_by_page.setdefault(instance["page_key"], []).append(instance)
        blocks_by_instance: dict[str, list[str]] = {}
        for block in universe["blocks"]:
            blocks_by_instance.setdefault(block["component_instance_id"], []).append(
                block["obligation_id"]
            )
        pages_by_key = {page["page_key"]: page for page in universe["pages"]}
        plan["pages"] = []
        for index, page_key in enumerate(universe["page_keys"], start=1):
            page = pages_by_key[page_key]
            route = page["route"]
            page_has_api = any(
                contract["page_key"] == page_key
                for contract in universe["api_contracts"]
            )
            plan["pages"].append(
                {
                    "page_key": page_key,
                    "member_title": page["member_title"],
                    "route": route,
                    "source_file": f"app/src/main/java/test/Page{index}.kt",
                    "root_symbol": f"Page{index}Screen",
                    "dto_file": f"app/src/main/java/test/Page{index}Dto.kt",
                    "dto_symbol": f"Page{index}Dto",
                    "ui_state_symbol": f"Page{index}UiState",
                    "mock_fixture_path": f"app/src/test/resources/page-{index}.json",
                    "api_adapter_file": (
                        f"app/src/main/java/test/Page{index}ApiAdapter.kt"
                        if page_has_api
                        else None
                    ),
                    "api_adapter_symbol": (
                        f"Page{index}ApiAdapter" if page_has_api else None
                    ),
                    "responsive_strategy": "Constraint-driven vertical flow with inset-aware scrolling.",
                    "component_instance_ids": [
                        item["component_instance_id"]
                        for item in instances_by_page[page_key]
                    ],
                }
            )
        plan["runtime_entries"] = [
            {
                "entry_id": f"entry-{page['page_key']}",
                "source_file": page["source_file"],
                "symbol": page["root_symbol"],
                "page_key": page["page_key"],
                "design_name": pages_by_key[page["page_key"]]["design_names"][0],
            }
            for page in plan["pages"]
        ]
        plan["runtime_probe_provider"] = {
            "source_file": "app/src/main/java/test/IcpRuntimeProbePublisher.kt",
            "symbol": "IcpRuntimeProbePublisher",
            "publish_method_symbol": "publishRuntimeProbes",
            "output_path": "files/icp-runtime-probes.json",
        }
        plan["component_mappings"] = [
            {
                "component_instance_id": item["component_instance_id"],
                "component_id": item["component_id"],
                "page_key": item["page_key"],
                "source_file": next(
                    page["source_file"] for page in plan["pages"] if page["page_key"] == item["page_key"]
                ),
                "symbol": "Component" + hashlib.sha256(item["component_instance_id"].encode()).hexdigest()[:8],
                "platform_primitive": "Composable",
                "responsive_strategy": "Use parent constraints and wrap content without clipping.",
                "block_obligation_ids": blocks_by_instance.get(item["component_instance_id"], []),
            }
            for item in universe["component_instances"]
        ]
        component_pages: dict[str, set[str]] = {}
        for mapping in plan["component_mappings"]:
            component_pages.setdefault(mapping["component_id"], set()).add(
                mapping["page_key"]
            )
        for mapping in plan["component_mappings"]:
            if len(component_pages[mapping["component_id"]]) > 1:
                token = hashlib.sha256(mapping["component_id"].encode()).hexdigest()[:8]
                mapping["source_file"] = f"app/src/main/java/test/Shared{token}.kt"
                mapping["symbol"] = f"SharedComponent{token}"
        component_by_id = {
            item["component_instance_id"]: item for item in plan["component_mappings"]
        }
        plan["interaction_mappings"] = []
        for graph in universe["interaction_graphs"]:
            for interaction in graph["interactions"]:
                interaction_instance_ids = []
                for bound_ids in interaction["component_bindings"].values():
                    for instance_id in bound_ids:
                        if instance_id not in interaction_instance_ids:
                            interaction_instance_ids.append(instance_id)
                owner = component_by_id[interaction_instance_ids[0]]
                plan["interaction_mappings"].append(
                    {
                        "interaction_id": interaction["interaction_id"],
                        "page_key": graph["page_key"],
                        "component_instance_ids": interaction_instance_ids,
                        "source_file": owner["source_file"],
                        "symbol": owner["symbol"],
                        "implementation_anchor": (
                            "ICP:interaction:" + interaction["interaction_id"]
                        ),
                    }
                )
        page_plan_by_key = {page["page_key"]: page for page in plan["pages"]}
        plan["api_contract_mappings"] = [
            {
                "api_contract_id": contract["api_contract_id"],
                "page_key": contract["page_key"],
                "source_file": page_plan_by_key[contract["page_key"]]["api_adapter_file"],
                "adapter_symbol": page_plan_by_key[contract["page_key"]][
                    "api_adapter_symbol"
                ],
                "method_symbol": (
                    "apiMethod"
                    + hashlib.sha256(contract["api_contract_id"].encode()).hexdigest()[:8]
                ),
                "implementation_anchor": (
                    "ICP:api:" + contract["api_contract_id"]
                ),
            }
            for contract in universe["api_contracts"]
        ]
        plan["design_element_mappings"] = [
            {
                "obligation_id": item["obligation_id"],
                "source_file": component_by_id[item["component_instance_id"]]["source_file"],
                "symbol": component_by_id[item["component_instance_id"]]["symbol"],
                "implementation_anchor": "ICP:" + item["obligation_id"],
                "runtime_probe_tag": next(
                    (
                        assertion["probe_tag"]
                        for assertion in universe["reference_viewport_assertions"]
                        if assertion["obligation_id"] == item["obligation_id"]
                    ),
                    None,
                ),
                "asset_mappings": [
                    {
                        "source_asset_id": asset["asset_id"],
                        "source_asset_sha256": asset["sha256"],
                        "target_resource_path": (
                            "app/src/main/res/raw/icp_"
                            + asset["sha256"][:16]
                            + "."
                            + asset["format"]
                        ),
                    }
                    for asset in item["assets"][:1]
                ],
            }
            for item in universe["design_elements"]
        ]
        instance_by_fact = {
            binding["fact_id"]: instance
            for instance in universe["component_instances"]
            for binding in instance["fact_bindings"]
        }
        plan["semantic_fact_mappings"] = [
            {
                "obligation_id": item["obligation_id"],
                "fact_id": item["fact_id"],
                "source_file": component_by_id[
                    instance_by_fact[item["fact_id"]]["component_instance_id"]
                ]["source_file"],
                "symbol": component_by_id[
                    instance_by_fact[item["fact_id"]]["component_instance_id"]
                ]["symbol"],
                "implementation_anchor": "ICP:" + item["obligation_id"],
            }
            for item in universe["semantic_facts"]
        ]
        plan["integration_test_cases"] = [
            {
                "case_id": "case-" + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:20],
                "obligation_id": item["obligation_id"],
                "source_kind": item["source_kind"],
                "fact_id": item["fact_id"],
                "basis_fact_ids": item["basis_fact_ids"],
                "component_instance_id": item["component_instance_id"],
                "page_key": item["page_key"],
                "test_file": (
                    "app/src/androidTest/java/test/Interaction_"
                    + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8]
                    + ".kt"
                ),
                "test_name": "integration_" + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8],
                "runtime_test": self.runtime_test_contract(item, universe),
                "command": [
                    "./gradlew",
                    "connectedDebugAndroidTest",
                    (
                        "-Pandroid.testInstrumentationRunnerArguments.class="
                        "test.Interaction_"
                        + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8]
                        + "#integration_"
                        + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8]
                    ),
                ],
            }
            for item in universe["integration_obligations"]
        ]
        plan["presentation_mappings"] = [
            {
                "usage_id": item["usage_id"],
                "source_file": next(
                    page["source_file"]
                    for page in plan["pages"]
                    if page["page_key"] == item["source_page_key"]
                ),
                "symbol": "Presentation" + hashlib.sha256(item["usage_id"].encode()).hexdigest()[:8],
                "implementation_anchor": "ICP:presentation:" + item["usage_id"],
            }
            for item in universe["presentation_usages"]
        ]
        seen_visual_pages: set[str] = set()
        plan["visual_capture_cases"] = []
        for item in universe["visual_references"]:
            page_key = item["page_key"]
            component = next(
                mapping
                for mapping in plan["component_mappings"]
                if mapping["page_key"] == page_key
            )
            entry = next(
                entry
                for entry in plan["runtime_entries"]
                if entry["page_key"] == page_key
            )
            graph = next(
                graph
                for graph in universe["interaction_graphs"]
                if graph["page_key"] == page_key
            )
            interaction_trace = []
            if item["design_name"] != entry["design_name"]:
                continuation = next(
                    edge
                    for edge in graph["edges"]
                    if edge["target"]["kind"] == "interaction"
                )
                interaction_trace = [
                    {
                        "source_page_key": page_key,
                        "case_id": case_for_interaction(
                            universe,
                            plan,
                            page_key,
                            continuation["from_interaction_id"],
                        )["case_id"],
                        "interaction_id": continuation["from_interaction_id"],
                        "outcome": continuation["outcome"],
                        "action": "click",
                        "target_tag": "trigger-" + item["visual_state_id"],
                    }
                ]
            seen_visual_pages.add(page_key)
            plan["visual_capture_cases"].append(
                {
                    "design_name": item["design_name"],
                    "visual_state_id": item["visual_state_id"],
                    "page_key": page_key,
                    "entry_id": entry["entry_id"],
                    "package_name": "test.app",
                    "locale": "ru-RU",
                    "precondition_commands": [],
                    "interaction_trace": interaction_trace,
                    "production_render": {
                        "component_instance_id": component["component_instance_id"],
                        "source_file": component["source_file"],
                        "symbol": component["symbol"],
                        "root_tag": "root-" + item["visual_state_id"],
                    },
                }
            )
        plan["verification_commands"] = {
            "lint": [["./gradlew", "lintDebug"]],
            "build": [["./gradlew", "assembleDebug"]],
            "integration": [["./gradlew", "connectedDebugAndroidTest"]],
        }
        page_node_ids = {
            page_key: f"page:{page_key}" for page_key in universe["page_keys"]
        }
        plan["execution_nodes"] = [
            {
                "node_id": "foundation",
                "kind": "foundation",
                "page_keys": [],
                "depends_on": [],
                "case_ids": [],
            },
            *[
                {
                    "node_id": page_node_ids[page_key],
                    "kind": "page",
                    "page_keys": [page_key],
                    "depends_on": ["foundation"],
                    "case_ids": [
                        case["case_id"]
                        for case in plan["integration_test_cases"]
                        if case["page_key"] == page_key
                    ],
                }
                for page_key in universe["page_keys"]
            ],
            {
                "node_id": "flow-integration",
                "kind": "flow-integration",
                "page_keys": list(universe["page_keys"]),
                "depends_on": [page_node_ids[key] for key in universe["page_keys"]],
                "case_ids": [],
            },
        ]
        file_owners: dict[str, str] = {
            "app/src/main/AndroidManifest.xml": "foundation",
            "app/src/main/MainActivity.kt": "flow-integration",
        }
        for page in plan["pages"]:
            owner = page_node_ids[page["page_key"]]
            for field in (
                "source_file",
                "dto_file",
                "mock_fixture_path",
                "api_adapter_file",
            ):
                if page[field] is not None:
                    file_owners[page[field]] = owner
        for case in plan["integration_test_cases"]:
            file_owners[case["test_file"]] = page_node_ids[case["page_key"]]
        for mapping in plan["component_mappings"]:
            file_owners[mapping["source_file"]] = (
                "foundation"
                if len(component_pages[mapping["component_id"]]) > 1
                else page_node_ids[mapping["page_key"]]
            )
        file_owners[plan["runtime_probe_provider"]["source_file"]] = "foundation"
        for field in (
            "design_element_mappings",
            "semantic_fact_mappings",
            "presentation_mappings",
        ):
            for mapping in plan[field]:
                owner = file_owners.get(mapping["source_file"])
                if owner is None:
                    page = next(
                        page
                        for page in plan["pages"]
                        if page["source_file"] == mapping["source_file"]
                    )
                    owner = page_node_ids[page["page_key"]]
                    file_owners[mapping["source_file"]] = owner
                for asset in mapping.get("asset_mappings", []):
                    file_owners[asset["target_resource_path"]] = owner
        plan["file_owners"] = file_owners
        plan["layout_decisions"] = authored_layout_decisions(universe)
        plan["layout_contracts"] = []
        return plan

    def runtime_test_contract(self, obligation: dict, universe: dict) -> dict:
        precondition_fact_ids: list[str] = []
        trigger_fact_ids: list[str] = []
        network_expectation = None
        mock_expectation = None
        forced_action_target = None
        if obligation["source_kind"] == "interaction_description":
            graph = next(
                item
                for item in universe["interaction_graphs"]
                if item["page_key"] == obligation["page_key"]
            )
            interaction = next(
                item
                for item in graph["interactions"]
                if item["interaction_id"] == obligation["item_id"]
            )
            for field in ("condition", "state"):
                if interaction[field] is not None:
                    precondition_fact_ids.extend(interaction[field]["fact_ids"])
            if interaction["trigger"] is not None:
                trigger_fact_ids = list(interaction["trigger"]["fact_ids"])
            behavior = interaction.get("behavior")
            if behavior is not None and behavior.get("kind") == "api_call":
                api_contract = next(
                    item
                    for item in universe["api_contracts"]
                    if item["page_key"] == obligation["page_key"]
                    and item["api_contract_id"] == behavior["api_contract_id"]
                )
                normalized_api = api_contract["normalized"]
                response_status = int(normalized_api["responses"][0]["status"])
                network_expectation = {
                    "api_contract_id": behavior["api_contract_id"],
                    "mode": "response",
                    "method": normalized_api["method"],
                    "path": normalized_api["path"],
                    "request_headers": {},
                    "request_body": None,
                    "response_status": response_status,
                    "response_headers": {"Content-Type": "application/json"},
                    "response_body": {
                        "icp_runtime_value": "__ICP_RUNTIME_CANARY__"
                    },
                    "response_probe": {
                        "target_tag": "icp-result-"
                        + hashlib.sha256(
                            obligation["obligation_id"].encode()
                        ).hexdigest()[:12],
                        "operator": "text_contains",
                    },
                }
            if network_expectation is None:
                incoming_api = next(
                    (
                        (edge, source)
                        for edge in graph["edges"]
                        if edge["target"].get("kind") == "interaction"
                        and edge["target"].get("to_interaction_id")
                        == interaction["interaction_id"]
                        for source in graph["interactions"]
                        if source["interaction_id"] == edge["from_interaction_id"]
                        and source.get("behavior") is not None
                        and source["behavior"].get("kind") == "api_call"
                    ),
                    None,
                )
                if incoming_api is not None:
                    edge, source = incoming_api
                    api_contract = next(
                        item
                        for item in universe["api_contracts"]
                        if item["page_key"] == obligation["page_key"]
                        and item["api_contract_id"]
                        == source["behavior"]["api_contract_id"]
                    )
                    normalized_api = api_contract["normalized"]
                    forced_action_target = "icp-action-" + hashlib.sha256(
                        source["interaction_id"].encode()
                    ).hexdigest()[:12]
                    if edge["outcome"] == "failure":
                        network_expectation = {
                            "api_contract_id": source["behavior"]["api_contract_id"],
                            "mode": "disconnect",
                            "method": normalized_api["method"],
                            "path": normalized_api["path"],
                            "request_headers": {},
                            "request_body": None,
                            "response_status": None,
                            "response_headers": {},
                            "response_body": None,
                            "response_probe": None,
                        }
                    else:
                        network_expectation = {
                            "api_contract_id": source["behavior"]["api_contract_id"],
                            "mode": "response",
                            "method": normalized_api["method"],
                            "path": normalized_api["path"],
                            "request_headers": {},
                            "request_body": None,
                            "response_status": int(
                                normalized_api["responses"][0]["status"]
                            ),
                            "response_headers": {
                                "Content-Type": "application/json"
                            },
                            "response_body": {
                                "icp_runtime_value": "__ICP_RUNTIME_CANARY__"
                            },
                            "response_probe": {
                                "target_tag": "icp-result-"
                                + hashlib.sha256(
                                    obligation["obligation_id"].encode()
                                ).hexdigest()[:12],
                                "operator": "text_contains",
                            },
                        }
        if obligation["source_kind"] == "model_inference":
            first_page_model_obligation = next(
                item
                for item in universe["integration_obligations"]
                if item["page_key"] == obligation["page_key"]
                and item["source_kind"] == "model_inference"
            )
            if first_page_model_obligation["obligation_id"] == obligation[
                "obligation_id"
            ]:
                mock_expectation = {
                    "body": {"icp_runtime_value": "__ICP_RUNTIME_CANARY__"},
                    "response_probe": {
                        "target_tag": "icp-result-"
                        + hashlib.sha256(
                            obligation["obligation_id"].encode()
                        ).hexdigest()[:12],
                        "operator": "text_contains",
                    },
                }
        remaining_fact_ids = [
            fact_id
            for fact_id in obligation["basis_fact_ids"]
            if fact_id not in precondition_fact_ids
            and fact_id not in trigger_fact_ids
        ]
        token = hashlib.sha256(obligation["obligation_id"].encode()).hexdigest()[:12]
        return {
            "entry_tag": "icp-entry-" + obligation["page_key"],
            "preconditions": (
                [
                    {
                        "operator": "visible",
                        "target_tag": "icp-entry-" + obligation["page_key"],
                        "value": None,
                        "fact_ids": precondition_fact_ids,
                    }
                ]
                if precondition_fact_ids
                else []
            ),
            "actions": (
                [
                    {
                        "operator": "click",
                        "target_tag": forced_action_target or "icp-action-" + token,
                        "value": None,
                        "fact_ids": trigger_fact_ids,
                    }
                ]
                if trigger_fact_ids or forced_action_target is not None
                else []
            ),
            "assertions": [
                {
                    "operator": "visible",
                    "target_tag": "icp-result-" + token,
                    "value": None,
                    "fact_ids": remaining_fact_ids or obligation["basis_fact_ids"],
                }
            ],
            "network_expectation": network_expectation,
            "mock_expectation": mock_expectation,
        }

    def record_plan(self, plan: dict) -> subprocess.CompletedProcess[str]:
        path = self.project / "implementation-plan.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = run_command(
            "record-plan",
            "--project-root",
            str(self.project),
            "--plan",
            str(path),
        )
        return result

    def materialize_android_tests(self, plan: dict) -> None:
        IMPLEMENTATION.materialize_android_test_files(
            self.project.resolve(), plan, recovering=False
        )

    def test_plan_requires_a_production_runtime_probe_provider(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        plan["runtime_probe_provider"] = {
            "source_file": "app/src/main/java/test/IcpRuntimeProbePublisher.kt",
            "symbol": "IcpRuntimeProbePublisher",
            "publish_method_symbol": "publishRuntimeProbes",
            "output_path": "files/icp-runtime-probes.json",
        }
        plan["file_owners"][plan["runtime_probe_provider"]["source_file"]] = "foundation"

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        self.assertEqual(frozen["runtime_probe_provider"], plan["runtime_probe_provider"])

    def test_record_plan_recovers_an_identical_plan_written_before_its_receipts(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        state = read_json(self.stage_dir / "state.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        normalized = IMPLEMENTATION.validate_plan(plan, state, universe)
        IMPLEMENTATION.materialize_android_test_files(
            self.project.resolve(), normalized, recovering=False
        )
        write_json(self.stage_dir / "implementation-plan.json", normalized)

        recovered = self.record_plan(plan)

        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        repaired_state = read_json(self.stage_dir / "state.json")
        self.assertEqual(repaired_state["state"], "awaiting_red")
        self.assertTrue((self.stage_dir / "tdd-evidence.json").is_file())
        checklist = read_json(self.stage_dir / "checklist.json")
        node = next(item for item in checklist["nodes"] if item["node_id"] == "plan.record")
        self.assertEqual(node["status"], "completed")

    def test_record_plan_recovery_rejects_fabricated_existing_tdd_results(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        evidence_path = self.stage_dir / "tdd-evidence.json"
        evidence = read_json(evidence_path)
        evidence["cases"][0]["red"] = {
            "exit_code": 0,
            "test_file_sha256": "fabricated",
            "device_test_result": {
                "class_name": "fabricated",
                "test_name": "fabricated",
                "status": "failed",
            },
        }
        write_json(evidence_path, evidence)

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("tdd_evidence_invalid", rejected.stderr)

    def test_record_plan_recovery_rejects_well_formed_tdd_results_without_transaction(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.materialize_android_tests(plan)
        self.write_fake_gradle("app_behavior")
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        planned_case = plan["integration_test_cases"][0]
        contract = IMPLEMENTATION.exact_android_test_contract(
            self.project.resolve(), planned_case
        )
        evidence_path = self.stage_dir / "tdd-evidence.json"
        evidence = read_json(evidence_path)
        evidence["cases"][0]["red"] = {
            "exit_code": 1,
            "stdout_sha256": "0" * 64,
            "stderr_sha256": "0" * 64,
            "stdout_tail": "",
            "stderr_tail": "",
            "test_file_sha256": contract["test_file_sha256"],
            "test_runner_sha256": contract["test_runner_sha256"],
            "device_task_path": contract["device_task_path"],
            "device_test_result": {
                "report_path": "app/build/outputs/androidTest-results/fake.xml",
                "report_sha256": "0" * 64,
                "class_name": contract["class_name"],
                "test_name": contract["method_name"],
                "device": "fabricated-device",
                "status": "failed",
            },
            "build_baseline": {
                "command": ["./gradlew", "clean"],
                "exit_code": 0,
                "stdout_sha256": "0" * 64,
                "stderr_sha256": "0" * 64,
                "stale_apk_paths": [],
                "stale_apks_absent_after_clean": True,
            },
        }
        write_json(evidence_path, evidence)

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("stage_drift", rejected.stderr)

    def test_code_coverage_requires_the_production_renderer_to_publish_runtime_probes(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        universe, _ = self.prepare_verifiable_implementation(
            plan, record_runtime_capture=False
        )
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        provider = frozen["runtime_probe_provider"]
        page_path = self.project / frozen["pages"][0]["source_file"]
        page_path.write_text(
            page_path.read_text(encoding="utf-8").replace(
                provider["publish_method_symbol"] + "()", ""
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError,
            "production renderer never calls",
        ):
            IMPLEMENTATION.verify_code_coverage(
                self.project.resolve(),
                frozen,
                universe,
                frozen["pages"][0]["page_key"],
            )

    def test_capture_visual_rejects_a_caller_supplied_driver(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        driver = self.project / "caller-driver.py"
        driver.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        driver.chmod(0o755)

        rejected = self.capture_visual(
            plan["visual_capture_cases"][0]["design_name"], driver
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("untrusted_runtime_driver", rejected.stderr)

    def test_capture_visual_requires_a_fresh_agp_production_install(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        self.write_fake_gradle("app_behavior", attest_task=False)

        reset = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(self.clean_package_reset()), stderr=""
        )
        with patch.object(IMPLEMENTATION, "run_driver", return_value=reset):
            with self.assertRaises(IMPLEMENTATION.ContractError) as failure:
                IMPLEMENTATION.capture_visual(
                    argparse.Namespace(
                        project_root=str(self.project),
                        design_name=plan["visual_capture_cases"][0]["design_name"],
                        driver=str(IMPLEMENTATION.ANDROID_VISUAL_DRIVER),
                    )
                )

        self.assertEqual(failure.exception.code, "android_device_task_unproven")

    def test_implementation_driver_forwards_an_explicit_validated_device_serial(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(
            IMPLEMENTATION.subprocess, "run", return_value=completed
        ) as run:
            IMPLEMENTATION.run_driver(
                str(IMPLEMENTATION.ANDROID_VISUAL_DRIVER),
                "snapshot",
                "test.app",
                device_serial="device-2",
            )

        self.assertEqual(
            run.call_args.args[0],
            [
                str(IMPLEMENTATION.ANDROID_VISUAL_DRIVER),
                "snapshot",
                "--package",
                "test.app",
                "--serial",
                "device-2",
            ],
        )

    def test_capture_responsive_rejects_a_caller_supplied_driver(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        driver = self.project / "caller-responsive-driver.py"
        driver.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        driver.chmod(0o755)

        rejected = self.capture_responsive(
            plan["page_keys"][0], "compact", driver
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("untrusted_runtime_driver", rejected.stderr)

    def test_visual_capture_depends_on_completed_production_code_coverage(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        checklist = read_json(self.stage_dir / "checklist.json")
        capture_nodes = [
            item for item in checklist["nodes"]
            if item["node_id"].startswith("visual:")
            and item["node_id"].endswith(".capture")
        ]

        self.assertTrue(capture_nodes)
        references = {
            item["design_name"]: item["page_key"]
            for item in read_json(self.stage_dir / "coverage-universe.json")[
                "visual_references"
            ]
        }
        for item in capture_nodes:
            design_name = item["node_id"][len("visual:") : -len(".capture")]
            self.assertEqual(
                item["depends_on"],
                [f"implementation.code-coverage:{references[design_name]}"],
            )

    def test_capture_responsive_records_live_layout_and_screenshot_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        universe, _evidence = self.prepare_verifiable_implementation(
            plan, record_runtime_capture=False
        )
        plan = read_json(self.stage_dir / "implementation-plan.json")
        page_key = plan["page_keys"][0]
        viewport = "compact"
        width, height = 360, 800
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        current = copy.deepcopy(initial)
        snapshot_count = 0
        visual_operations: list[str] = []

        def completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

        def fake_driver(
            _driver: str, operation: str, _package: str, **paths: Path
        ) -> subprocess.CompletedProcess[str]:
            nonlocal current, snapshot_count
            if operation in {"capture", "read-layout"}:
                visual_operations.append(operation)
            if operation == "snapshot":
                snapshot_count += 1
                return completed(json.dumps(current))
            if operation == "reset-package":
                return completed(json.dumps(self.clean_package_reset()))
            if operation == "package-identity":
                return completed(json.dumps(self.installed_package_identity()))
            if operation in {"apply", "restore"}:
                current = read_json(paths["config"])
                return completed()
            if operation in {"cold-start", "health"}:
                return completed(json.dumps({
                    "activity_resumed": True,
                    "process_alive": True,
                    "no_fatal_exception": True,
                    "fatal_log_tail": "",
                }))
            if operation == "interact":
                trace = read_json(paths["trace"])
                return completed(json.dumps({
                    "schema": "icp.visual-interaction.v1",
                    "steps": trace["steps"],
                    "initial_state_absent": bool(trace["steps"]),
                    "terminal_state_present": True,
                }))
            if operation == "attest":
                return completed(json.dumps({
                    "visual_state_id": str(paths["state_id"]),
                    "root_tag": str(paths["root_tag"]),
                    "state_attested": True,
                    "root_attested": True,
                }))
            if operation == "read-layout":
                contract_input = read_json(paths["contract"])
                contract = next(
                    item
                    for item in plan["layout_contracts"]
                    if item["design_state_id"] == contract_input["design_state_id"]
                )
                components = []
                for instance_id, node in contract["component_tree"]["nodes_by_instance_id"].items():
                    bounds = copy.deepcopy(
                        contract["component_geometry_by_instance_id"][instance_id][
                            "artboard_envelope"
                        ]
                    )
                    if instance_id == contract["root_instance_id"]:
                        bounds = {"left": 0, "top": 0, "width": width, "height": height}
                    components.append({
                        "instance_id": instance_id,
                        "occurrence_id": instance_id,
                        "presence": "present",
                        "parent_instance_id": node["parent_instance_id"],
                        "slot": node["slot"],
                        "order": node["order"],
                        "bounds": bounds,
                    })
                scroll_metrics = []
                for assertion in contract["responsive_assertions"]:
                    if assertion["kind"] == "scroll_reachability":
                        extent = width if assertion["axis"] == "horizontal" else height
                        scroll_metrics.append({
                            "decision_id": assertion["decision_id"],
                            "container_instance_id": assertion["container_instance_id"],
                            "axis": assertion["axis"],
                            "viewport_extent": extent,
                            "content_extent": extent,
                            "observed_offsets": [0],
                        })
                return completed(json.dumps({
                    "visual_state_id": contract_input["visual_state_id"],
                    "root_tag": contract_input["root_tag"],
                    "coordinate_space": {"unit": "dp", "origin": "viewport"},
                    "viewport_bounds": {"left": 0, "top": 0, "width": width, "height": height},
                    "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
                    "system_bars": {
                        "status": {"visible": False, "bounds": None},
                        "navigation": {"visible": False, "bounds": None},
                    },
                    "scroll_metrics": scroll_metrics,
                    "driver_observations": {
                        "observed_instance_ids": [
                            item["occurrence_id"] for item in components
                        ],
                        "scroll_actions": [],
                        "scroll_results": [
                            {
                                "decision_id": assertion["decision_id"],
                                "container_instance_id": assertion[
                                    "container_instance_id"
                                ],
                                "axis": assertion["axis"],
                                "end_reached": True,
                                "restored_to_start": True,
                                "observed_instance_ids": list(
                                    contract["component_tree"][
                                        "nodes_by_instance_id"
                                    ]
                                ),
                            }
                            for assertion in contract["responsive_assertions"]
                            if assertion["kind"] == "scroll_reachability"
                        ],
                    },
                    "components": components,
                }))
            if operation == "capture":
                IMPLEMENTATION.write_png_rgba(
                    paths["output"], width, height, [(255, 255, 255, 255)] * (width * height)
                )
                return completed()
            raise AssertionError(operation)

        with patch.object(IMPLEMENTATION, "run_driver", side_effect=fake_driver):
            result = IMPLEMENTATION.capture_responsive(argparse.Namespace(
                project_root=str(self.project),
                page_key=page_key,
                viewport=viewport,
                driver=str(IMPLEMENTATION.ANDROID_VISUAL_DRIVER),
            ))

        run = read_json(self.project / result["responsive_evidence"])
        self.assertEqual((run["page_key"], run["viewport"]), (page_key, viewport))
        self.assertEqual(len(run["snapshots"]), len([
            item for item in plan["layout_contracts"] if item["page_key"] == page_key
        ]))
        self.assertEqual(snapshot_count, 2 * len(run["snapshots"]) + 2)
        self.assertEqual(
            visual_operations,
            [operation for _ in run["snapshots"] for operation in ("capture", "read-layout")],
        )
        self.assertEqual(current, initial)
        checklist = read_json(self.stage_dir / "checklist.json")
        node = next(
            item for item in checklist["nodes"]
            if item["node_id"] == f"responsive:{page_key}.{viewport}"
        )
        self.assertEqual(node["status"], "completed")
        self.assertEqual(node["evidence_sha256"], IMPLEMENTATION.digest(run))

    def run_case(
        self, case_id: str, phase: str, *, device_serial: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            "run-case",
            "--project-root",
            str(self.project),
            "--case-id",
            case_id,
            "--phase",
            phase,
        ]
        if device_serial is not None:
            arguments.extend(["--device-serial", device_serial])
        return run_command(*arguments)

    def write_fake_gradle(
        self, module: str, *, delay: bool = False, attest_task: bool = True
    ) -> None:
        path = self.project / "gradlew"
        path.write_text(
            "#!/usr/bin/env python3\n"
            + ("import time; time.sleep(0.3)\n" if delay else "")
            + "import os, pathlib, shutil, sys\n"
            + "if sys.argv[1:] == ['clean']:\n"
            + "    shutil.rmtree('app/build', ignore_errors=True)\n"
            + "    raise SystemExit(0)\n"
            + "if '--serial' in sys.argv: raise SystemExit(97)\n"
            + "device = os.environ.get('ANDROID_SERIAL', 'test-device')\n"
            + "apk = pathlib.Path('app/build/outputs/apk/debug/app-debug.apk')\n"
            + "apk.parent.mkdir(parents=True, exist_ok=True)\n"
            + "apk.write_bytes(b'production-base-apk')\n"
            + (
                "print('Path\\n     :app:connectedDebugAndroidTest\\n\\nType\\n     DeviceProviderInstrumentTestTask (com.android.build.gradle.internal.tasks.DeviceProviderInstrumentTestTask)')\n"
                "print('Starting 1 tests on ' + device)\n"
                if attest_task
                else ""
            )
            + f"from {module} import IMPLEMENTED\n"
            + "prefix = '-Pandroid.testInstrumentationRunnerArguments.class='\n"
            + "selector = next(arg[len(prefix):] for arg in sys.argv[1:] if arg.startswith(prefix))\n"
            + "class_name, test_name = selector.split('#', 1)\n"
            + "result = pathlib.Path('app/build/outputs/androidTest-results/connected/debug')\n"
            + "result.mkdir(parents=True, exist_ok=True)\n"
            + "body = '<failure message=\"assertion failed\" />' if not IMPLEMENTED else ''\n"
            + "xml = f'<testsuite timestamp=\"2026-01-01T00:00:00\"><properties><property name=\"device\" value=\"{device}\" /></properties><testcase classname=\"{class_name}\" name=\"{test_name}\">{body}</testcase></testsuite>'\n"
            + "(result / ('TEST-' + class_name + '.xml')).write_text(xml, encoding='utf-8')\n"
            + "raise SystemExit(0 if IMPLEMENTED else 1)\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def verify_implementation(self, evidence: dict) -> subprocess.CompletedProcess[str]:
        path = self.project / "runtime-evidence.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_command(
            "verify",
            "--project-root",
            str(self.project),
            "--evidence",
            str(path),
        )

    def capture_visual(
        self, design_name: str, driver: Path
    ) -> subprocess.CompletedProcess[str]:
        return run_command(
            "capture-visual",
            "--project-root",
            str(self.project),
            "--design-name",
            design_name,
            "--driver",
            str(driver),
        )

    def capture_visual_with_test_driver(
        self, design_name: str, driver: Path
    ) -> subprocess.CompletedProcess[str]:
        try:
            with patch.object(IMPLEMENTATION, "ANDROID_VISUAL_DRIVER", driver):
                result = IMPLEMENTATION.capture_visual(argparse.Namespace(
                    project_root=str(self.project),
                    design_name=design_name,
                    driver=str(driver),
                ))
        except IMPLEMENTATION.ContractError as exc:
            return subprocess.CompletedProcess(
                [],
                2,
                stdout="",
                stderr=json.dumps({
                    "ok": False,
                    "error": exc.code,
                    "message": exc.message,
                }) + "\n",
            )
        return subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(result) + "\n", stderr=""
        )

    def reference_layout_snapshot(
        self, plan: dict, design_name: str, visual_state_id: str, root_tag: str
    ) -> dict:
        contract = next(
            item
            for item in plan["layout_contracts"]
            if item["design_state_id"] == design_name
        )
        components = []
        for instance_id, node in contract["component_tree"]["nodes_by_instance_id"].items():
            components.append(
                {
                    "instance_id": instance_id,
                    "occurrence_id": instance_id,
                    "presence": "present",
                    "parent_instance_id": node["parent_instance_id"],
                    "slot": node["slot"],
                    "order": node["order"],
                    "bounds": copy.deepcopy(
                        contract["component_geometry_by_instance_id"][instance_id][
                            "artboard_envelope"
                        ]
                    ),
                }
            )
        root_bounds = next(
            item["bounds"]
            for item in components
            if item["instance_id"] == contract["root_instance_id"]
        )
        return {
            "visual_state_id": visual_state_id,
            "root_tag": root_tag,
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": copy.deepcopy(root_bounds),
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [],
            "driver_observations": {
                "observed_instance_ids": [
                    item["occurrence_id"] for item in components
                ],
                "scroll_actions": [],
                "scroll_results": [
                    {
                        "decision_id": assertion["decision_id"],
                        "container_instance_id": assertion[
                            "container_instance_id"
                        ],
                        "axis": assertion["axis"],
                        "end_reached": True,
                        "restored_to_start": True,
                        "observed_instance_ids": list(
                            contract["component_tree"]["nodes_by_instance_id"]
                        ),
                    }
                    for assertion in contract["responsive_assertions"]
                    if assertion["kind"] == "scroll_reachability"
                ],
            },
            "components": components,
        }

    def installed_package_identity(self, package_name: str = "test.app") -> dict:
        apks = [
            {
                "name": "base.apk",
                "size": 19,
                "sha256": hashlib.sha256(b"production-base-apk").hexdigest(),
            }
        ]
        return {
            "package_name": package_name,
            "apks": apks,
            "sha256": IMPLEMENTATION.digest(apks),
        }

    def clean_package_reset(self, package_name: str = "test.app") -> dict:
        return {
            "package_name": package_name,
            "was_installed": True,
            "absent_after_reset": True,
        }

    def capture_responsive(
        self, page_key: str, viewport: str, driver: Path
    ) -> subprocess.CompletedProcess[str]:
        return run_command(
            "capture-responsive",
            "--project-root",
            str(self.project),
            "--page-key",
            page_key,
            "--viewport",
            viewport,
            "--driver",
            str(driver),
        )

    def prepare_verifiable_implementation(
        self, plan: dict, *, record_runtime_capture: bool = True
    ) -> tuple[dict, dict]:
        behavior_path = self.project / "app_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("app_behavior")
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"visual_interaction_case_{index}.py"
            test_path.write_text(
                "from app_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
            case["command"] = [
                "./gradlew",
                "connectedDebugAndroidTest",
                (
                    "-Pandroid.testInstrumentationRunnerArguments.class=test.Interaction#"
                    + case["test_name"]
                ),
            ]
        verify_command = self.project / "visual_verify_command.py"
        verify_command.write_text("raise SystemExit(0)\n", encoding="utf-8")
        command = [sys.executable, verify_command.name]
        plan["verification_commands"] = {
            "lint": [command],
            "build": [command],
            "integration": [command],
        }
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        for case in plan["integration_test_cases"]:
            red = self.run_case(case["case_id"], "red")
            self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        behavior_path.write_text("IMPLEMENTED = True\n", encoding="utf-8")
        for case in plan["integration_test_cases"]:
            green = self.run_case(case["case_id"], "green")
            self.assertEqual(green.returncode, 0, green.stdout + green.stderr)

        universe_for_calls = read_json(self.stage_dir / "coverage-universe.json")
        graph_interaction_by_key = {
            (graph["page_key"], interaction["interaction_id"]): interaction
            for graph in universe_for_calls["interaction_graphs"]
            for interaction in graph["interactions"]
        }
        api_mapping_by_key = {
            (mapping["page_key"], mapping["api_contract_id"]): mapping
            for mapping in plan["api_contract_mappings"]
        }
        file_lines: dict[str, list[str]] = {}
        for page in plan["pages"]:
            file_lines.setdefault(page["source_file"], []).append(
                f"fun {page['root_symbol']}() = Unit"
            )
            file_lines.setdefault(page["dto_file"], []).extend(
                [
                    f"data class {page['dto_symbol']}(val value: String)",
                    f"data class {page['ui_state_symbol']}(val value: String)",
                ]
            )
            file_lines.setdefault(page["api_adapter_file"], []).append(
                f"class {page['api_adapter_symbol']}"
            )
            mock = self.project / page["mock_fixture_path"]
            mock.parent.mkdir(parents=True, exist_ok=True)
            mock_body = next(
                case["runtime_test"]["mock_expectation"]["body"]
                for case in plan["integration_test_cases"]
                if case["page_key"] == page["page_key"]
                and case["runtime_test"]["mock_expectation"] is not None
            )
            mock.write_text(
                json.dumps(mock_body, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        for mapping in plan["component_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).append(
                f"fun {mapping['symbol']}() = Unit"
            )
        for mapping in plan["interaction_mappings"]:
            interaction = graph_interaction_by_key[
                (mapping["page_key"], mapping["interaction_id"])
            ]
            behavior = interaction.get("behavior")
            call_lines = []
            if behavior is not None and behavior["kind"] == "api_call":
                api_mapping = api_mapping_by_key[
                    (mapping["page_key"], behavior["api_contract_id"])
                ]
                call_lines = [api_mapping["method_symbol"] + "()"]
            file_lines.setdefault(mapping["source_file"], []).extend(
                [
                    f"fun {mapping['symbol']}() = Unit",
                    "// " + mapping["implementation_anchor"],
                    *call_lines,
                ]
            )
        for mapping in plan["api_contract_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).extend(
                [
                    f"class {mapping['adapter_symbol']}",
                    f"fun {mapping['method_symbol']}() = Unit",
                    "// " + mapping["implementation_anchor"],
                ]
            )
        for visual in plan["visual_capture_cases"]:
            file_lines.setdefault(
                visual["production_render"]["source_file"], []
            ).append("// " + visual["production_render"]["root_tag"])
        provider = plan["runtime_probe_provider"]
        file_lines.setdefault(provider["source_file"], []).extend(
            [
                f"object {provider['symbol']}",
                f"fun {provider['publish_method_symbol']}() = Unit",
                f'const val outputPath = "{provider["output_path"]}"',
            ]
        )
        for page in plan["pages"]:
            file_lines.setdefault(page["source_file"], []).append(
                provider["publish_method_symbol"] + "()"
            )
        for field in (
            "design_element_mappings",
            "semantic_fact_mappings",
            "presentation_mappings",
        ):
            for mapping in plan[field]:
                typography_resources = (
                    [
                        assertion["apk_resource_name"]
                        for assertion in universe_for_calls[
                            "reference_viewport_assertions"
                        ]
                        if assertion["obligation_id"] == mapping["obligation_id"]
                        and assertion["kind"] in {"font_size", "line_height"}
                    ]
                    if field == "design_element_mappings"
                    else []
                )
                element_binding = []
                if field == "design_element_mappings":
                    element = next(
                        item
                        for item in universe_for_calls["design_elements"]
                        if item["obligation_id"] == mapping["obligation_id"]
                    )
                    resources_by_kind = {
                        assertion["kind"]: assertion["apk_resource_name"]
                        for assertion in universe_for_calls[
                            "reference_viewport_assertions"
                        ]
                        if assertion["obligation_id"] == mapping["obligation_id"]
                        and assertion["kind"] in {"font_size", "line_height"}
                    }
                    asset_resource_refs = [
                        IMPLEMENTATION.android_resource_reference(
                            item["target_resource_path"]
                        )
                        for item in mapping["asset_mappings"]
                    ]
                    self.assertNotIn(None, asset_resource_refs)
                    element_binding = [
                        "IcpBoundElement("
                        + f'obligationId = {json.dumps(mapping["obligation_id"])}, '
                        + f'componentInstanceId = {json.dumps(element["component_instance_id"])}, '
                        + f'ownerSymbol = {json.dumps(mapping["symbol"])}, '
                        + "probeTag = "
                        + (
                            json.dumps(mapping["runtime_probe_tag"])
                            if mapping["runtime_probe_tag"] is not None
                            else "null"
                        )
                        + ", "
                        + "fontSizeRes = "
                        + (
                            "R.dimen." + resources_by_kind["font_size"]
                            if "font_size" in resources_by_kind
                            else "null"
                        )
                        + ", lineHeightRes = "
                        + (
                            "R.dimen." + resources_by_kind["line_height"]
                            if "line_height" in resources_by_kind
                            else "null"
                        )
                        + ", assetRefs = "
                        + (
                            "listOf(" + ", ".join(asset_resource_refs) + ")"
                            if asset_resource_refs
                            else "emptyList()"
                        )
                        + ")"
                    ]
                file_lines.setdefault(mapping["source_file"], []).extend(
                    [
                        f"fun {mapping['symbol']}() = Unit",
                        "// " + mapping["implementation_anchor"],
                        *["val typography = R.dimen." + name for name in typography_resources],
                        *element_binding,
                        *(
                            ["// " + mapping["runtime_probe_tag"]]
                            if field == "design_element_mappings"
                            and mapping["runtime_probe_tag"] is not None
                            else []
                        ),
                    ]
                )
        for relative, lines in file_lines.items():
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        universe = read_json(self.stage_dir / "coverage-universe.json")
        elements = {item["obligation_id"]: item for item in universe["design_elements"]}
        for mapping in plan["design_element_mappings"]:
            source_assets = {
                item["asset_id"]: item
                for item in elements[mapping["obligation_id"]]["assets"]
            }
            for asset_mapping in mapping["asset_mappings"]:
                source = self.project / source_assets[asset_mapping["source_asset_id"]][
                    "source_project_path"
                ]
                target = self.project / asset_mapping["target_resource_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())

        plan_sha = read_json(self.stage_dir / "state.json")["implementation_plan_sha256"]
        references_by_page = {
            page_key: next(
                item
                for item in universe["visual_references"]
                if item["page_key"] == page_key
            )
            for page_key in universe["page_keys"]
        }
        runtime_installations = {
            page_key: IMPLEMENTATION.attest_android_runtime_installation(
                self.project.resolve(), plan, page_key, device_serial=None
            )
            for page_key in universe["page_keys"]
        }
        responsive_runs = []
        for page_key in universe["page_keys"]:
            page_contracts = [
                item for item in plan["layout_contracts"] if item["page_key"] == page_key
            ]
            for viewport, width, height in (
                ("compact", 360, 800),
                ("expanded", 840, 1200),
            ):
                reference = references_by_page[page_key]
                screenshot = self.stage_dir / "runtime" / f"responsive-{page_key}-{viewport}.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes((self.project / reference["path"]).read_bytes())
                snapshots = []
                for contract in page_contracts:
                    components = []
                    for instance_id, node in contract["component_tree"]["nodes_by_instance_id"].items():
                        bounds = copy.deepcopy(
                            contract["component_geometry_by_instance_id"][instance_id][
                                "artboard_envelope"
                            ]
                        )
                        if instance_id == contract["root_instance_id"]:
                            bounds = {"left": 0, "top": 0, "width": width, "height": height}
                        components.append(
                            {
                                "instance_id": instance_id,
                                "occurrence_id": instance_id,
                                "presence": "present",
                                "parent_instance_id": node["parent_instance_id"],
                                "slot": node["slot"],
                                "order": node["order"],
                                "bounds": bounds,
                            }
                        )
                    scroll_metrics = []
                    for assertion in contract["responsive_assertions"]:
                        if assertion["kind"] != "scroll_reachability":
                            continue
                        extent = width if assertion["axis"] == "horizontal" else height
                        scroll_metrics.append(
                            {
                                "decision_id": assertion["decision_id"],
                                "container_instance_id": assertion["container_instance_id"],
                                "axis": assertion["axis"],
                                "viewport_extent": extent,
                                "content_extent": extent,
                                "observed_offsets": [0],
                            }
                        )
                    snapshots.append(
                        {
                            "design_state_id": contract["design_state_id"],
                            "coordinate_space": {"unit": "dp", "origin": "viewport"},
                            "viewport_bounds": {
                                "left": 0,
                                "top": 0,
                                "width": width,
                                "height": height,
                            },
                            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
                            "system_bars": {
                                "status": {"visible": False, "bounds": None},
                                "navigation": {"visible": False, "bounds": None},
                            },
                            "scroll_metrics": scroll_metrics,
                            "driver_observations": {
                                "observed_instance_ids": [
                                    item["occurrence_id"] for item in components
                                ],
                                "scroll_actions": [],
                                "scroll_results": [
                                    {
                                        "decision_id": assertion["decision_id"],
                                        "container_instance_id": assertion[
                                            "container_instance_id"
                                        ],
                                        "axis": assertion["axis"],
                                        "end_reached": True,
                                        "restored_to_start": True,
                                        "observed_instance_ids": list(
                                            contract["component_tree"][
                                                "nodes_by_instance_id"
                                            ]
                                        ),
                                    }
                                    for assertion in contract[
                                        "responsive_assertions"
                                    ]
                                    if assertion["kind"]
                                    == "scroll_reachability"
                                ],
                            },
                            "components": components,
                            "capture": {
                                "screenshot_path": str(screenshot.relative_to(self.project)),
                                "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                                "device_configuration": {
                                    "width": width,
                                    "height": height,
                                    "density": 320,
                                    "locale": "ru-RU",
                                    "font_scale": "1.0",
                                    "navigation_mode": "gesture",
                                },
                            },
                        }
                    )
                responsive_run = {
                    "page_key": page_key,
                    "viewport": viewport,
                    "package_reset": self.clean_package_reset(),
                    "runtime_installation": runtime_installations[page_key],
                    "package_identity": self.installed_package_identity(),
                    "snapshots": snapshots,
                }
                responsive_path = (
                    self.stage_dir
                    / "runtime"
                    / "responsive"
                    / f"{page_key}-{viewport}.capture.json"
                )
                responsive_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(responsive_path, responsive_run)
                responsive_runs.append(
                    {
                        "page_key": page_key,
                        "viewport": viewport,
                        "capture_evidence": str(
                            responsive_path.relative_to(self.project)
                        ),
                    }
                )
        evidence = {
            "schema": "icp.implementation.runtime-evidence.v1",
            "implementation_plan_sha256": plan_sha,
            "responsive_runs": responsive_runs,
            "visual_runs": [],
        }
        for reference in universe["visual_references"]:
            actual = self.stage_dir / "runtime" / (
                hashlib.sha256(reference["design_name"].encode()).hexdigest()[:16]
                + ".actual.png"
            )
            actual.parent.mkdir(parents=True, exist_ok=True)
            actual.write_bytes((self.project / reference["path"]).read_bytes())
            config = {
                "size": {"width": 1080, "height": 1920},
                "size_override": False,
                "density": 420,
                "density_override": False,
                "locale": "en-US",
                "font_scale": "1.0",
                "navigation_mode": "2",
            }
            applied = {
                **config,
                "size": reference["pixel_size"],
                "size_override": True,
                "density": round(160 * float(reference["logical_scale"])),
                "density_override": True,
                "locale": "ru-RU",
            }
            capture = {
                "schema": "icp.implementation.visual-capture-evidence.v3",
                "evaluation_scope": "reference_viewport_visual_fidelity",
                "implementation_plan_sha256": plan_sha,
                "design_name": reference["design_name"],
                "reference_sha256": reference["sha256"],
                "logical_artboard_size": reference["logical_artboard_size"],
                "reference_pixel_size": reference["pixel_size"],
                "logical_scale": reference["logical_scale"],
                "capture_strategy": "extended-viewport-full-page",
                "visual_state_id": reference["visual_state_id"],
                "package_reset": self.clean_package_reset(),
                "runtime_installation": runtime_installations[
                    reference["page_key"]
                ],
                "package_identity": self.installed_package_identity(),
                "cold_start": {
                    "activity_resumed": True,
                    "process_alive": True,
                    "no_fatal_exception": True,
                    "fatal_log_tail": "",
                },
                "interaction": {
                    "schema": "icp.visual-interaction.v1",
                    "steps": next(
                        item["interaction_trace"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == reference["design_name"]
                    ),
                    "initial_state_absent": bool(next(
                        item["interaction_trace"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == reference["design_name"]
                    )),
                    "terminal_state_present": True,
                },
                "production_state": {
                    "visual_state_id": reference["visual_state_id"],
                    "root_tag": next(
                        item["production_render"]["root_tag"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == reference["design_name"]
                    ),
                    "state_attested": True,
                    "root_attested": True,
                },
                "measurements": {
                    "schema": "icp.visual-measurements.v1",
                    "visual_state_id": reference["visual_state_id"],
                    "root_tag": next(
                        item["production_render"]["root_tag"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == reference["design_name"]
                    ),
                    "measurements": [
                        {
                            "assertion_id": item["assertion_id"],
                            "probe_tag": item["probe_tag"],
                            "kind": item["kind"],
                            "actual": item["expected"],
                            **(
                                {
                                    "source": "clean_build_apk",
                                    "apk_sha256": runtime_installations[
                                        reference["page_key"]
                                    ]["built_apks"][0]["sha256"],
                                }
                                if item["kind"] in {"font_size", "line_height"}
                                else {}
                            ),
                        }
                        for item in universe["reference_viewport_assertions"]
                        if item["design_name"] == reference["design_name"]
                    ],
                },
                "layout": {
                    key: value
                    for key, value in self.reference_layout_snapshot(
                        plan,
                        reference["design_name"],
                        reference["visual_state_id"],
                        next(
                            item["production_render"]["root_tag"]
                            for item in plan["visual_capture_cases"]
                            if item["design_name"] == reference["design_name"]
                        ),
                    ).items()
                    if key not in {"visual_state_id", "root_tag"}
                },
                "before": config,
                "applied": applied,
                "raw_pixel_size": [
                    reference["pixel_size"]["width"],
                    reference["pixel_size"]["height"],
                ],
                "actual_screenshot": str(actual.relative_to(self.project)),
                "actual_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
                "restored": config,
                "restore_exact": True,
            }
            capture_path = actual.with_suffix(".capture.json")
            capture_path.write_text(
                json.dumps(capture, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            evidence["visual_runs"].append(
                {
                    "design_name": reference["design_name"],
                    "actual_screenshot": str(actual.relative_to(self.project)),
                    "capture_evidence": str(capture_path.relative_to(self.project)),
                }
            )
        if record_runtime_capture:
            state = read_json(self.stage_dir / "state.json")
            for page_key in universe["page_keys"]:
                page_manifest = IMPLEMENTATION.verify_code_coverage(
                    self.project.resolve(), plan, universe, page_key
                )
                IMPLEMENTATION.implementation_checklist_call(
                    self.stage_dir,
                    state,
                    universe,
                    "complete",
                    node_id=f"implementation.code-coverage:{page_key}",
                    evidence_sha256=IMPLEMENTATION.digest(page_manifest),
                )
            manifest = IMPLEMENTATION.verify_code_coverage(
                self.project.resolve(), plan, universe
            )
            IMPLEMENTATION.implementation_checklist_call(
                self.stage_dir,
                state,
                universe,
                "complete",
                node_id="implementation.code-coverage",
                evidence_sha256=IMPLEMENTATION.digest(manifest),
            )
            for responsive_run in evidence["responsive_runs"]:
                captured_run = read_json(
                    self.project / responsive_run["capture_evidence"]
                )
                IMPLEMENTATION.implementation_checklist_call(
                    self.stage_dir,
                    state,
                    universe,
                    "complete",
                    node_id=(
                        f"responsive:{responsive_run['page_key']}."
                        f"{responsive_run['viewport']}"
                    ),
                    evidence_sha256=IMPLEMENTATION.digest(captured_run),
                )
            for visual_run in evidence["visual_runs"]:
                capture_path = self.project / visual_run["capture_evidence"]
                IMPLEMENTATION.implementation_checklist_call(
                    self.stage_dir,
                    state,
                    universe,
                    "complete",
                    node_id=f"visual:{visual_run['design_name']}.capture",
                    evidence_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest(),
                )
        return universe, evidence

    def test_begin_freezes_the_complete_stage1_and_stage2_implementation_universe(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        result = json.loads(begun.stdout)
        self.assertEqual(result["state"], "awaiting_plan")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        state = read_json(self.stage_dir / "state.json")
        plan_input = read_json(self.stage_dir / "implementation-plan.input.json")
        lock = read_json(
            self.project / ".icp" / "component-design" / "component-lock.json"
        )
        bindings = read_json(
            self.project
            / ".icp"
            / "component-design"
            / "block-component-bindings.json"
        )

        self.assertEqual(universe["schema"], "icp.implementation.coverage-universe.v3")
        self.assertEqual(plan_input["schema"], "icp.implementation.plan.v3")
        self.assertEqual(
            universe["page_keys"],
            [
                member["page_key"]
                for member in lock["source_context"]["members"]
                if member["change_scope"] == "modify"
            ],
        )
        self.assertEqual(
            {item["component_instance_id"] for item in universe["component_instances"]},
            {
                item["instance_id"]
                for item in lock["component_instances"]
                if item["page_key"] in set(universe["page_keys"])
            },
        )
        expected_nodes = {
            (binding["design_name"], node["source_node_id"])
            for binding in bindings["bindings"]
            if binding["page_key"] in set(universe["page_keys"])
            for node in binding["block"]["source_nodes"]
        }
        self.assertEqual(
            {
                (item["design_name"], item["source_node_id"])
                for item in universe["design_elements"]
            },
            expected_nodes,
        )
        self.assertTrue(universe["design_elements"])
        self.assertTrue(
            all(item["content_role"] for item in universe["design_elements"])
        )
        expected_parents = {
            (binding["design_name"], node["source_node_id"]): node["source_fact"].get(
                "parent_id"
            )
            for binding in bindings["bindings"]
            if binding["page_key"] in set(universe["page_keys"])
            for node in binding["block"]["source_nodes"]
        }
        self.assertEqual(
            {
                (item["design_name"], item["source_node_id"]): item[
                    "source_parent_node_id"
                ]
                for item in universe["design_elements"]
            },
            expected_parents,
        )

        expected_interaction_facts = {
            value["fact_id"]
            for page in lock["pages"]
            if page["page_key"] in set(universe["page_keys"])
            for item in page["interaction_items"]
            for field in ("condition", "state", "trigger", "behavior", "result")
            for value in [item[field]]
            if value is not None
        }
        self.assertEqual(
            {
                fact_id
                for item in universe["integration_obligations"]
                if item["source_kind"]
                in {"interaction_graph", "interaction_description", "it_description"}
                for fact_id in item["basis_fact_ids"]
            },
            expected_interaction_facts,
        )
        self.assertEqual(
            universe["presentation_usages"], lock["presentation_usages"]
        )
        self.assertEqual(
            state["component_lock_sha256"],
            hashlib.sha256(
                (
                    self.project
                    / ".icp"
                    / "component-design"
                    / "component-lock.json"
                ).read_bytes()
            ).hexdigest(),
        )
        self.assertRegex(state["platform_rules_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            state["common_rules_sha256"],
            hashlib.sha256(self.common_rules_text.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            (self.stage_dir / "common-rules.md").read_text(encoding="utf-8"),
            self.common_rules_text,
        )
        plan_input = read_json(self.stage_dir / "implementation-plan.input.json")
        self.assertEqual(plan_input["coverage_universe_sha256"], state["coverage_universe_sha256"])
        self.assertEqual(plan_input["platform"], "android-kotlin")
        self.assertEqual(
            plan_input["common_rules"],
            {
                "project_path": "common-rules.md",
                "sha256": state["common_rules_sha256"],
                "content": self.common_rules_text,
            },
        )
        self.assertEqual(plan_input["pages"], [])
        self.assertEqual(plan_input["component_mappings"], [])
        self.assertEqual(plan_input["design_element_mappings"], [])
        self.assertEqual(plan_input["integration_test_cases"], [])
        self.assertEqual(plan_input["visual_capture_cases"], [])

    def test_begin_projects_only_modify_page_owned_data_from_a_mixed_scope_lock(self) -> None:
        self.begin_component_stage(
            bundle_kwargs={
                "include_designless_context": True,
                "design_b_scope": "navigate-only",
            }
        )

        universe = read_json(self.stage_dir / "coverage-universe.json")
        source_members = universe["source_identity"]["members"]
        expected_page_keys = [
            member["page_key"]
            for member in source_members
            if member["change_scope"] == "modify"
        ]
        expected_page_key_set = set(expected_page_keys)

        self.assertEqual(universe["page_keys"], expected_page_keys)
        self.assertEqual(
            {member["change_scope"] for member in source_members},
            {"modify", "context", "navigate-only"},
        )
        for collection in (
            "pages",
            "component_instances",
            "interaction_graphs",
            "api_contracts",
            "blocks",
            "design_elements",
            "semantic_facts",
            "integration_obligations",
            "component_layout_inputs",
            "layout_selection_inputs",
        ):
            self.assertTrue(
                all(
                    item["page_key"] in expected_page_key_set
                    for item in universe[collection]
                ),
                collection,
            )
        self.assertTrue(
            all(
                item["source_page_key"] in expected_page_key_set
                for item in universe["presentation_usages"]
            )
        )

    def test_begin_rejects_a_sealed_contract_whose_targets_disagree_with_scope(self) -> None:
        component_dir = self.project / ".icp" / "component-design"
        lock_path = component_dir / "component-lock.json"
        lock = read_json(lock_path)
        lock["implementation_contract"]["source_identity"]["members"][0][
            "change_scope"
        ] = "context"
        write_json(lock_path, lock)
        lock_sha256 = hashlib.sha256(lock_path.read_bytes()).hexdigest()

        result_path = component_dir / "stage-result.json"
        result = read_json(result_path)
        result["component_lock_sha256"] = lock_sha256
        result["artifacts"]["component_lock"]["sha256"] = lock_sha256
        write_json(result_path, result)

        state_path = component_dir / "state.json"
        state = read_json(state_path)
        state["component_lock_sha256"] = lock_sha256
        state["stage_result_sha256"] = hashlib.sha256(
            result_path.read_bytes()
        ).hexdigest()
        write_json(state_path, state)

        begun = self.begin()

        self.assertNotEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        self.assertIn("implementation_scope_mismatch", begun.stderr)

    def test_begin_derives_reference_viewport_assertions_from_stage1_facts(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        assertions = universe["reference_viewport_assertions"]
        self.assertTrue(assertions)
        bounds = next(item for item in assertions if item["kind"] == "bounds")
        source = next(
            item
            for item in universe["design_elements"]
            if item["obligation_id"] == bounds["obligation_id"]
        )
        frame = source["design_facts"]["geometry"]
        self.assertEqual(
            bounds["expected"],
            {
                "left": frame.get("left", frame.get("x")),
                "top": frame.get("top", frame.get("y")),
                "width": frame["width"],
                "height": frame["height"],
            },
        )
        self.assertEqual(bounds["source_node_id"], source["source_node_id"])
        self.assertEqual(bounds["mode"], "exact_at_reference")
        self.assertEqual(bounds["probe_tag"], "icp-probe-" + bounds["obligation_id"])

    def test_reference_assertions_use_resolved_artboard_coordinates(self) -> None:
        design_elements = [
            {
                "obligation_id": "element-root",
                "design_name": "screen",
                "source_node_id": "root-node",
                "component_instance_id": "instance-screen",
                "content_role": "static_visual",
                "design_facts": {
                    "geometry": {
                        "left": 687,
                        "top": 2050,
                        "width": 390,
                        "height": 844,
                    }
                },
            },
            {
                "obligation_id": "element-child",
                "design_name": "screen",
                "source_node_id": "child-node",
                "component_instance_id": "instance-screen",
                "content_role": "static_visual",
                "design_facts": {
                    "geometry": {
                        "left": 703,
                        "top": 2098,
                        "width": 100,
                        "height": 40,
                    }
                },
            },
        ]
        layout_inputs = [
            {
                "design_state_id": "screen",
                "artboard_frames_by_source_node_id": {
                    "root-node": {
                        "left": 0,
                        "top": 0,
                        "width": 390,
                        "height": 844,
                    },
                    "child-node": {
                        "left": 16,
                        "top": 48,
                        "width": 100,
                        "height": 40,
                    },
                },
            }
        ]

        assertions = IMPLEMENTATION.build_reference_viewport_assertions(
            design_elements,
            layout_inputs,
            IMPLEMENTATION.build_design_element_evidence_channels(design_elements),
        )
        bounds = {
            item["obligation_id"]: item["expected"]
            for item in assertions
            if item["kind"] == "bounds"
        }

        self.assertEqual(
            bounds,
            {
                "element-root": {
                    "left": 0,
                    "top": 0,
                    "width": 390,
                    "height": 844,
                },
                "element-child": {
                    "left": 16,
                    "top": 48,
                    "width": 100,
                    "height": 40,
                },
            },
        )

    def test_reference_bounds_are_compared_on_the_frozen_physical_pixel_grid(self) -> None:
        assertion = {
            "assertion_id": "assertion-bounds",
            "probe_tag": "probe-bounds",
            "kind": "bounds",
            "mode": "exact_at_reference",
            "evaluation": {
                "operator": "equals",
                "expected": {
                    "left": 70.9224853515625,
                    "top": 16,
                    "width": 100,
                    "height": 40,
                },
            },
        }
        evidence = {
            "schema": "icp.visual-measurements.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-a",
            "measurements": [
                {
                    "assertion_id": "assertion-bounds",
                    "probe_tag": "probe-bounds",
                    "kind": "bounds",
                    "actual": {
                        "left": 71,
                        "top": 16,
                        "width": 100,
                        "height": 40,
                    },
                }
            ],
        }

        accepted = IMPLEMENTATION.validate_measurement_evidence(
            evidence, "state-a", "root-a", [assertion], "2"
        )
        self.assertEqual(accepted["measurements"][0]["actual"]["left"], 71)

        evidence["measurements"][0]["actual"]["left"] = 72
        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "reference viewport assertion failed"
        ):
            IMPLEMENTATION.validate_measurement_evidence(
                evidence, "state-a", "root-a", [assertion], "2"
            )

    def test_typography_can_pass_only_from_the_current_clean_build_apk(self) -> None:
        apk_sha = "a" * 64
        assertion = {
            "assertion_id": "font",
            "probe_tag": "copy",
            "kind": "font_size",
            "expected": 14,
            "evaluation": {"operator": "equals", "expected": 14},
        }
        evidence = {
            "schema": "icp.visual-measurements.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-a",
            "measurements": [
                {
                    "assertion_id": "font",
                    "probe_tag": "copy",
                    "kind": "font_size",
                    "actual": 18,
                    "source": "clean_build_apk",
                    "apk_sha256": apk_sha,
                }
            ],
        }

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "reference viewport assertion failed"
        ):
            IMPLEMENTATION.validate_measurement_evidence(
                evidence, "state-a", "root-a", [assertion], "1", apk_sha
            )

        evidence["measurements"][0]["actual"] = 14
        accepted = IMPLEMENTATION.validate_measurement_evidence(
            evidence, "state-a", "root-a", [assertion], "1", apk_sha
        )
        self.assertEqual(accepted["measurements"][0]["source"], "clean_build_apk")

        evidence["measurements"][0]["apk_sha256"] = "b" * 64
        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "reference viewport assertion failed"
        ):
            IMPLEMENTATION.validate_measurement_evidence(
                evidence, "state-a", "root-a", [assertion], "1", apk_sha
            )

    def test_opaque_color_measurement_must_exist_in_the_real_captured_pixels(self) -> None:
        reference = self.project / "color-reference.png"
        screenshot = self.project / "color-proof.png"
        IMPLEMENTATION.write_png_rgba(
            reference,
            4,
            4,
            [(255, 0, 0, 255)] * 16,
        )
        IMPLEMENTATION.write_png_rgba(
            screenshot,
            4,
            4,
            [(255, 255, 255, 255)] * 16,
        )
        assertions = [
            {
                "assertion_id": "bounds",
                "probe_tag": "probe",
                "kind": "bounds",
                "mode": "exact_at_reference",
                "expected": {"left": 0, "top": 0, "width": 4, "height": 4},
            },
            {
                "assertion_id": "color",
                "probe_tag": "probe",
                "kind": "color",
                "expected": {"r": 255, "g": 0, "b": 0, "a": 255},
            },
        ]
        measurements = {
            "measurements": [
                {
                    "assertion_id": "bounds",
                    "probe_tag": "probe",
                    "kind": "bounds",
                    "actual": {"left": 0, "top": 0, "width": 4, "height": 4},
                },
                {
                    "assertion_id": "color",
                    "probe_tag": "probe",
                    "kind": "color",
                    "actual": {"r": 255, "g": 0, "b": 0, "a": 255},
                },
            ]
        }

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "captured production pixels"
        ):
            IMPLEMENTATION.validate_color_pixel_evidence(
                reference, screenshot, assertions, measurements, "1"
            )

        pixels = [(255, 255, 255, 255)] * 16
        pixels[5] = (253, 2, 1, 255)
        IMPLEMENTATION.write_png_rgba(screenshot, 4, 4, pixels)
        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "reference color footprint"
        ):
            IMPLEMENTATION.validate_color_pixel_evidence(
                reference, screenshot, assertions, measurements, "1"
            )

        IMPLEMENTATION.write_png_rgba(
            screenshot,
            4,
            4,
            [(253, 2, 1, 255)] * 16,
        )
        observations = IMPLEMENTATION.validate_color_pixel_evidence(
            reference, screenshot, assertions, measurements, "1"
        )
        self.assertEqual(
            observations,
            [
                {
                    "assertion_id": "color",
                    "probe_tag": "probe",
                    "source": "captured_production_pixels",
                    "pixel": {"x": 0, "y": 0, "r": 253, "g": 2, "b": 1, "a": 255},
                    "reference_pixel_count": 16,
                    "actual_pixel_count": 16,
                }
            ],
        )

    def test_color_passes_only_from_captured_pixels_not_the_app_claim(self) -> None:
        assertion = {
            "assertion_id": "color",
            "obligation_id": "element",
            "design_name": "screen",
            "probe_tag": "probe",
            "kind": "color",
            "mode": "exact_at_reference",
            "expected": {"r": 255, "g": 0, "b": 0, "a": 255},
            "evaluation": {
                "operator": "equals_normalized_color",
                "expected": {"r": 255, "g": 0, "b": 0, "a": 255},
            },
        }
        evidence = {
            "schema": "icp.visual-measurements.v1",
            "visual_state_id": "screen",
            "root_tag": "root",
            "measurements": [
                {
                    "assertion_id": "color",
                    "probe_tag": "probe",
                    "kind": "color",
                    "actual": {"r": 0, "g": 255, "b": 0, "a": 255},
                }
            ],
        }

        accepted = IMPLEMENTATION.validate_measurement_evidence(
            evidence, "screen", "root", [assertion], "1"
        )

        self.assertEqual(
            accepted["measurements"][0]["actual"],
            {"r": 0, "g": 255, "b": 0, "a": 255},
        )

        translucent = copy.deepcopy(assertion)
        translucent["expected"]["a"] = 128
        translucent["evaluation"]["expected"]["a"] = 128
        evidence["measurements"][0]["actual"]["a"] = 128
        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "reference viewport assertion failed"
        ):
            IMPLEMENTATION.validate_measurement_evidence(
                evidence, "screen", "root", [translucent], "1"
            )

    def test_visual_interaction_evidence_requires_a_real_state_transition(self) -> None:
        step = {"action": "click", "target_tag": "open-target"}
        evidence = {
            "schema": "icp.visual-interaction.v1",
            "steps": [step],
            "initial_state_absent": False,
            "terminal_state_present": True,
        }

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "frozen production interaction trace"
        ):
            IMPLEMENTATION.validate_interaction_evidence(evidence, [step])

        evidence["initial_state_absent"] = True
        accepted = IMPLEMENTATION.validate_interaction_evidence(evidence, [step])
        self.assertTrue(accepted["initial_state_absent"])

    def test_every_framed_design_element_gets_a_reference_bounds_assertion(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        framed = {
            item["obligation_id"]
            for item in universe["design_elements"]
            if item["design_facts"]["geometry"]
        }
        bounded = {
            item["obligation_id"]
            for item in universe["reference_viewport_assertions"]
            if item["kind"] == "bounds"
        }

        self.assertEqual(bounded, framed)
        adaptive_text_bounds = [
            item
            for item in universe["reference_viewport_assertions"]
            if item["kind"] == "bounds"
            and next(
                element["content_role"]
                for element in universe["design_elements"]
                if element["obligation_id"] == item["obligation_id"]
            )
            in {"static_copy", "dynamic_content"}
        ]
        self.assertTrue(adaptive_text_bounds)
        self.assertTrue(
            all(item["mode"] == "adaptive_at_reference" for item in adaptive_text_bounds)
        )

    def test_begin_derives_typography_assertions_from_stage1_text_style(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        assertions = read_json(self.stage_dir / "coverage-universe.json")[
            "reference_viewport_assertions"
        ]
        font_size = next(item for item in assertions if item["kind"] == "font_size")
        line_height = next(item for item in assertions if item["kind"] == "line_height")
        self.assertEqual(font_size["expected"], 14)
        self.assertEqual(line_height["expected"], 22)
        self.assertEqual(font_size["obligation_id"], line_height["obligation_id"])
        self.assertEqual(font_size["mode"], "exact_at_reference")
        self.assertRegex(font_size["apk_resource_name"], r"^icp_[0-9a-f]{20}_font_size$")
        self.assertEqual(
            line_height["apk_resource_name"],
            font_size["apk_resource_name"].removesuffix("font_size") + "line_height",
        )

    def test_code_coverage_requires_production_ui_to_consume_frozen_typography_resources(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        assertion = next(
            item
            for item in universe["reference_viewport_assertions"]
            if item["kind"] == "font_size"
        )
        mapping = next(
            item
            for item in plan["design_element_mappings"]
            if item["obligation_id"] == assertion["obligation_id"]
        )
        element = next(
            item
            for item in universe["design_elements"]
            if item["obligation_id"] == mapping["obligation_id"]
        )
        page_key = next(
            item["page_key"]
            for item in plan["component_mappings"]
            if item["component_instance_id"] == element["component_instance_id"]
        )
        source_path = self.project / mapping["source_file"]
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace(
                "R.dimen." + assertion["apk_resource_name"],
                "14.sp",
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError,
            "does not consume its frozen APK typography resources",
        ):
            IMPLEMENTATION.verify_code_coverage(
                self.project.resolve(),
                plan,
                universe,
                page_key,
            )

    def test_code_coverage_rejects_disconnected_element_identity_and_typography_tokens(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        assertion = next(
            item
            for item in universe["reference_viewport_assertions"]
            if item["kind"] == "font_size"
        )
        mapping = next(
            item
            for item in plan["design_element_mappings"]
            if item["obligation_id"] == assertion["obligation_id"]
        )
        element = next(
            item
            for item in universe["design_elements"]
            if item["obligation_id"] == mapping["obligation_id"]
        )
        page_key = next(
            item["page_key"]
            for item in plan["component_mappings"]
            if item["component_instance_id"] == element["component_instance_id"]
        )
        source_path = self.project / mapping["source_file"]
        obligation_literal = json.dumps(mapping["obligation_id"])
        source_path.write_text(
            "\n".join(
                line
                for line in source_path.read_text(encoding="utf-8").splitlines()
                if not (
                    "IcpBoundElement(" in line
                    and f"obligationId = {obligation_literal}" in line
                )
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError,
            "one production element binding",
        ):
            IMPLEMENTATION.verify_code_coverage(
                self.project.resolve(), plan, universe, page_key
            )

    def test_code_coverage_rejects_copied_but_unconsumed_target_asset(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        mapping = next(
            item for item in plan["design_element_mappings"] if item["asset_mappings"]
        )
        element = next(
            item
            for item in universe["design_elements"]
            if item["obligation_id"] == mapping["obligation_id"]
        )
        page_key = next(
            item["page_key"]
            for item in plan["component_mappings"]
            if item["component_instance_id"] == element["component_instance_id"]
        )
        target_reference = IMPLEMENTATION.android_resource_reference(
            mapping["asset_mappings"][0]["target_resource_path"]
        )
        self.assertIsNotNone(target_reference)
        source_path = self.project / mapping["source_file"]
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace(
                target_reference,
                "R.raw.unrelated_decoy_asset",
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError,
            "production element binding does not consume",
        ):
            IMPLEMENTATION.verify_code_coverage(
                self.project.resolve(), plan, universe, page_key
            )

    def test_begin_derives_color_assertions_from_stage1_style(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        text_element = next(
            item
            for item in universe["design_elements"]
            if item["content_role"] == "static_copy"
        )
        color = next(
            item
            for item in universe["reference_viewport_assertions"]
            if item["obligation_id"] == text_element["obligation_id"]
            and item["kind"] == "color"
        )

        self.assertEqual(
            color["expected"], {"r": 91, "g": 92, "b": 226, "a": 255}
        )
        self.assertEqual(color["mode"], "exact_at_reference")
        visual_element = next(
            item
            for item in universe["design_elements"]
            if item["content_role"] == "static_visual"
        )
        visual_color = next(
            item
            for item in universe["reference_viewport_assertions"]
            if item["obligation_id"] == visual_element["obligation_id"]
            and item["kind"] == "color"
        )
        self.assertEqual(
            visual_color["expected"], {"r": 91, "g": 92, "b": 226, "a": 255}
        )

    def test_begin_projects_complete_component_bound_visual_facts_once(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        text_element = next(
            item
            for item in universe["design_elements"]
            if item["content_role"] == "static_copy"
        )
        visual_element = next(
            item
            for item in universe["design_elements"]
            if item["content_role"] == "static_visual"
        )

        self.assertEqual(
            text_element["design_facts"],
            {
                "geometry": {"x": 0, "y": 0, "width": 1, "height": 1},
                "backgrounds": [],
                "borders": [],
                "radii": [],
                "typography": {
                    "content": text_element["design_name"],
                    "fills": [
                        {
                            "enabled": True,
                            "color": {
                                "r": 0.3568627450980392,
                                "g": 0.3607843137254902,
                                "b": 0.8862745098039215,
                                "a": 1,
                            },
                        }
                    ],
                    "font": {
                        "size": 14,
                        "lineHeight": {"unit": "PIXELS", "value": 22},
                    },
                },
                "assets": text_element["assets"],
            },
        )
        self.assertEqual(
            visual_element["design_facts"]["backgrounds"],
            [{"enabled": True, "color": "#5B5CE2"}],
        )
        self.assertEqual(visual_element["design_facts"]["geometry"], {"x": 0, "y": 0, "width": 1, "height": 1})
        self.assertEqual(visual_element["design_facts"]["assets"], [])
        self.assertEqual(
            universe["reference_viewport_assertions"],
            IMPLEMENTATION.build_reference_viewport_assertions(
                universe["design_elements"],
                universe["layout_selection_inputs"],
                universe["design_element_evidence_channels"],
            ),
        )

    def test_design_fact_projection_preserves_border_radius_and_typography_payloads(self) -> None:
        facts = IMPLEMENTATION.project_design_facts(
            {
                "payload": {
                    "frame": {"x": 4, "y": 8, "width": 100, "height": 40},
                    "style": {
                        "fills": [{"color": "#FFFFFF"}],
                        "strokes": [{"color": "#222222", "weight": 1}],
                        "cornerRadius": 12,
                    },
                    "text": {
                        "style": {
                            "font": {"family": "Inter", "size": 14},
                            "letterSpacing": 0.2,
                        }
                    },
                }
            },
            [{"asset_id": "icon", "sha256": "a" * 64}],
        )

        self.assertEqual(facts["backgrounds"], [{"color": "#FFFFFF"}])
        self.assertEqual(
            facts["borders"], [{"color": "#222222", "weight": 1}]
        )
        self.assertEqual(facts["radii"], [12])
        self.assertEqual(
            facts["typography"],
            {
                "font": {"family": "Inter", "size": 14},
                "letterSpacing": 0.2,
            },
        )
        self.assertEqual(facts["assets"][0]["asset_id"], "icon")

    def test_begin_exposes_layout_selection_only_from_stage_two_bound_inputs(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        plan_input = read_json(self.stage_dir / "implementation-plan.input.json")
        bindings = read_json(
            self.project / ".icp" / "component-design" / "block-component-bindings.json"
        )
        self.assertEqual(
            {item["design_state_id"] for item in universe["layout_selection_inputs"]},
            {item["design_state_id"] for item in bindings["layout_inputs"]},
        )
        self.assertTrue(universe["layout_selection_inputs"])
        self.assertTrue(
            all(item["decision_obligations"] for item in universe["layout_selection_inputs"])
        )
        self.assertEqual(plan_input["layout_decisions"], [])
        self.assertEqual(plan_input["layout_contracts"], [])
        serialized = json.dumps(universe["layout_selection_inputs"], ensure_ascii=False)
        self.assertNotIn("source_bundle", serialized)
        self.assertNotIn("interaction_description", serialized)

    def test_begin_never_rejoins_extract_after_stage_two_is_sealed(self) -> None:
        extract_dir = self.project / ".icp" / "extract"
        detached_extract = self.project / ".icp" / "extract.detached-for-test"
        extract_dir.rename(detached_extract)

        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        self.assertTrue(universe["visual_references"])
        self.assertTrue(
            any(item["assets"] for item in universe["design_elements"])
        )

    def test_record_plan_freezes_executable_layout_contracts_for_codegen(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)

        accepted = self.record_plan(self.valid_plan())

        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        self.assertEqual(
            {item["design_state_id"] for item in plan["layout_contracts"]},
            {item["design_state_id"] for item in universe["layout_selection_inputs"]},
        )
        for contract in plan["layout_contracts"]:
            self.assertTrue(contract["authored_layout_decisions"])
            self.assertTrue(contract["reference_assertions"])
            self.assertTrue(contract["responsive_assertions"])
        for page_key in universe["page_keys"]:
            packet = read_json(self.stage_dir / "codegen-packets" / f"{page_key}.json")
            self.assertEqual(
                packet["layout_contracts"],
                [
                    item
                    for item in plan["layout_contracts"]
                    if item["page_key"] == page_key
                ],
            )

    def test_record_plan_collects_all_layout_problems_and_bounds_whole_page_retries(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        invalid = self.valid_plan()
        for item in invalid["layout_decisions"]:
            item["decisions"] = []

        failures = [self.record_plan(invalid) for _ in range(4)]

        for failed in failures[:3]:
            self.assertNotEqual(failed.returncode, 0)
            payload = json.loads(failed.stderr)
            self.assertEqual(payload["error"], "component_layout_decision_invalid")
            self.assertEqual(
                {item["design_state_id"] for item in payload["details"]["problems"]},
                {
                    item["design_state_id"]
                    for item in read_json(self.stage_dir / "coverage-universe.json")[
                        "layout_selection_inputs"
                    ]
                },
            )
        exhausted = json.loads(failures[3].stderr)
        self.assertEqual(exhausted["error"], "component_layout_retry_exhausted")
        history = read_json(self.stage_dir / "layout-decision-attempts.json")
        self.assertEqual(history["max_attempts"], 3)
        self.assertEqual(len(history["attempts"]), 3)
        self.assertTrue(all(item["problems"] for item in history["attempts"]))
        self.assertFalse((self.stage_dir / "implementation-plan.json").exists())

    def test_plan_binds_each_reference_assertion_to_a_runtime_probe_tag(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        universe = read_json(self.stage_dir / "coverage-universe.json")
        assertions_by_obligation = {
            item["obligation_id"]: item
            for item in universe["reference_viewport_assertions"]
        }
        self.assertTrue(assertions_by_obligation)
        for mapping in plan["design_element_mappings"]:
            assertion = assertions_by_obligation.get(mapping["obligation_id"])
            mapping["runtime_probe_tag"] = (
                assertion["probe_tag"] if assertion is not None else None
            )

        accepted = self.record_plan(plan)

        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        frozen_by_obligation = {
            item["obligation_id"]: item
            for item in frozen["design_element_mappings"]
        }
        for obligation_id, assertion in assertions_by_obligation.items():
            self.assertEqual(
                frozen_by_obligation[obligation_id]["runtime_probe_tag"],
                assertion["probe_tag"],
            )

    def test_begin_freezes_one_executable_evaluation_for_each_visual_assertion(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        assertions = read_json(self.stage_dir / "coverage-universe.json")[
            "reference_viewport_assertions"
        ]
        self.assertTrue(assertions)
        for assertion in assertions:
            expected_evaluation = (
                {
                    "operator": "finite_nonnegative_rect",
                    "expected": None,
                }
                if assertion["mode"] == "adaptive_at_reference"
                else {
                    "operator": "equals",
                    "expected": assertion["expected"],
                }
            )
            self.assertEqual(assertion["evaluation"], expected_evaluation)
            self.assertTrue(
                IMPLEMENTATION.evaluate_reference_assertion(
                    assertion,
                    assertion["expected"],
                    "1",
                )
            )

    def test_asset_internal_design_nodes_use_the_owner_asset_evidence_channel(self) -> None:
        elements = [
            {
                "obligation_id": "owner",
                "design_name": "screen",
                "source_node_id": "asset-owner-without-encoded-path",
                "source_parent_node_id": None,
                "assets": [{"asset_id": "asset-a"}],
            },
            {
                "obligation_id": "child",
                "design_name": "screen",
                "source_node_id": "deceptive;unrelated-id",
                "source_parent_node_id": "asset-owner-without-encoded-path",
                "assets": [],
            },
            {
                "obligation_id": "grandchild",
                "design_name": "screen",
                "source_node_id": "flat-grandchild-id",
                "source_parent_node_id": "deceptive;unrelated-id",
                "assets": [],
            },
            {
                "obligation_id": "ordinary",
                "design_name": "screen",
                "source_node_id": "asset-owner-without-encoded-path;fake-child",
                "source_parent_node_id": None,
                "assets": [],
            },
        ]

        channels = IMPLEMENTATION.build_design_element_evidence_channels(elements)

        self.assertEqual(
            channels,
            [
                {"obligation_id": "owner", "kind": "live_node", "owner_obligation_id": None},
                {"obligation_id": "child", "kind": "asset_internal", "owner_obligation_id": "owner"},
                {"obligation_id": "grandchild", "kind": "asset_internal", "owner_obligation_id": "owner"},
                {"obligation_id": "ordinary", "kind": "live_node", "owner_obligation_id": None},
            ],
        )

    def test_reference_assertions_reject_a_live_node_without_observable_design_data(self) -> None:
        elements = [
            {
                "obligation_id": "element-without-evidence",
                "design_name": "screen",
                "source_node_id": "10:20",
                "component_instance_id": "instance-a",
                "content_role": "dynamic_content",
                "design_facts": {},
            }
        ]
        layout_inputs = [
            {
                "design_state_id": "screen",
                "artboard_frames_by_source_node_id": {},
            }
        ]
        channels = [
            {
                "obligation_id": "element-without-evidence",
                "kind": "live_node",
                "owner_obligation_id": None,
            }
        ]

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError,
            "live design elements have no executable reference assertion",
        ):
            IMPLEMENTATION.build_reference_viewport_assertions(
                elements, layout_inputs, channels
            )

    def test_begin_never_requires_asset_internals_to_be_live_probe_nodes(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        assertions_by_obligation: dict[str, list[dict]] = {}
        for assertion in universe["reference_viewport_assertions"]:
            assertions_by_obligation.setdefault(assertion["obligation_id"], []).append(
                assertion
            )
        elements = {
            item["obligation_id"]: item for item in universe["design_elements"]
        }

        for channel in universe["design_element_evidence_channels"]:
            if channel["kind"] == "live_node":
                self.assertTrue(assertions_by_obligation[channel["obligation_id"]])
                continue
            self.assertEqual(channel["kind"], "asset_internal")
            self.assertNotIn(channel["obligation_id"], assertions_by_obligation)
            owner = elements[channel["owner_obligation_id"]]
            self.assertTrue(owner["assets"])
            self.assertEqual(
                owner["design_name"], elements[channel["obligation_id"]]["design_name"]
            )

    def test_begin_freezes_component_bound_interaction_graphs_and_api_contracts(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")

        self.assertEqual(len(universe["interaction_graphs"]), 2)
        self.assertEqual(len(universe["api_contracts"]), 2)
        api_contract_ids = {
            contract["api_contract_id"] for contract in universe["api_contracts"]
        }
        graph_api_contract_ids = {
            interaction["behavior"]["api_contract_id"]
            for graph in universe["interaction_graphs"]
            for interaction in graph["interactions"]
            if interaction["behavior"] is not None
            and interaction["behavior"]["kind"] == "api_call"
        }
        self.assertEqual(graph_api_contract_ids, api_contract_ids)
        for graph in universe["interaction_graphs"]:
            for interaction in graph["interactions"]:
                for binding_ids in interaction["component_bindings"].values():
                    self.assertTrue(
                        set(binding_ids).issubset(
                            {
                                instance["component_instance_id"]
                                for instance in universe["component_instances"]
                            }
                        )
                    )
        expected_interaction_ids = {
            interaction["interaction_id"]
            for graph in universe["interaction_graphs"]
            for interaction in graph["interactions"]
        }
        graph_obligations = {
            obligation["interaction_id"]
            for obligation in universe["integration_obligations"]
            if obligation["source_kind"] == "interaction_description"
        }
        self.assertEqual(graph_obligations, expected_interaction_ids)

    def test_graph_obligation_preserves_explicit_terminal_api_outcomes(self) -> None:
        graph = {
            "schema": "icp.component-design.locked-interaction-graph.v2",
            "page_key": "page-a",
            "member_title": "Page A",
            "interactions": [
                {
                    "interaction_id": "load-data",
                    "condition": None,
                    "state": None,
                    "trigger": {
                        "fact_ids": [],
                        "inference_basis": ["page load"],
                    },
                    "behavior": {
                        "fact_ids": [],
                        "inference_basis": ["load contract"],
                        "kind": "api_call",
                        "api_contract_id": "load-data-api",
                    },
                    "result": {
                        "fact_ids": [],
                        "inference_basis": ["load contract"],
                        "outcomes": ["success", "failure"],
                    },
                    "component_bindings": {
                        "condition_component_instance_ids": [],
                        "state_component_instance_ids": [],
                        "trigger_component_instance_ids": ["instance-a"],
                        "behavior_component_instance_ids": ["instance-a"],
                        "result_component_instance_ids": ["instance-a"],
                    },
                }
            ],
            "edges": [],
            "terminal_outcomes": [
                {
                    "interaction_id": "load-data",
                    "outcome": "success",
                    "inference_basis": ["fire-and-forget success"],
                },
                {
                    "interaction_id": "load-data",
                    "outcome": "failure",
                    "inference_basis": ["fire-and-forget failure"],
                },
            ],
        }

        obligations = IMPLEMENTATION.build_graph_interaction_obligations([graph])

        self.assertEqual(
            obligations[0]["terminal_outcomes"], graph["terminal_outcomes"]
        )

    def test_codegen_packet_binds_interactions_and_api_methods_to_production_components(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        plan = self.valid_plan()
        component_mapping_by_instance = {
            item["component_instance_id"]: item
            for item in plan["component_mappings"]
        }
        plan["interaction_mappings"] = []
        for graph in universe["interaction_graphs"]:
            for interaction in graph["interactions"]:
                instance_ids = []
                for bound_ids in interaction["component_bindings"].values():
                    for instance_id in bound_ids:
                        if instance_id not in instance_ids:
                            instance_ids.append(instance_id)
                owner = component_mapping_by_instance[instance_ids[0]]
                plan["interaction_mappings"].append(
                    {
                        "interaction_id": interaction["interaction_id"],
                        "page_key": graph["page_key"],
                        "component_instance_ids": instance_ids,
                        "source_file": owner["source_file"],
                        "symbol": owner["symbol"],
                        "implementation_anchor": (
                            "ICP:interaction:" + interaction["interaction_id"]
                        ),
                    }
                )
        page_by_key = {page["page_key"]: page for page in plan["pages"]}
        plan["api_contract_mappings"] = [
            {
                "api_contract_id": contract["api_contract_id"],
                "page_key": contract["page_key"],
                "source_file": page_by_key[contract["page_key"]]["api_adapter_file"],
                "adapter_symbol": page_by_key[contract["page_key"]][
                    "api_adapter_symbol"
                ],
                "method_symbol": (
                    "apiMethod"
                    + hashlib.sha256(contract["api_contract_id"].encode()).hexdigest()[:8]
                ),
                "implementation_anchor": (
                    "ICP:api:" + contract["api_contract_id"]
                ),
            }
            for contract in universe["api_contracts"]
        ]

        accepted = self.record_plan(plan)

        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        first_page = universe["page_keys"][0]
        packet = read_json(self.stage_dir / "codegen-packets" / f"{first_page}.json")
        self.assertTrue(packet["interaction_graph"]["interactions"])
        self.assertTrue(packet["interaction_mappings"])
        self.assertTrue(packet["api_contracts"])
        self.assertTrue(packet["api_contract_mappings"])
        self.assertEqual(packet["schema"], "icp.implementation.codegen-packet.v3")

    def test_plan_accepts_a_page_adapter_file_separate_from_the_dto(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        pages_by_key = {page["page_key"]: page for page in plan["pages"]}
        for index, page in enumerate(plan["pages"], start=1):
            page["api_adapter_file"] = (
                f"app/src/main/java/test/Page{index}ApiAdapter.kt"
            )
        for mapping in plan["api_contract_mappings"]:
            mapping["source_file"] = pages_by_key[mapping["page_key"]][
                "api_adapter_file"
            ]

        accepted = self.record_plan(plan)

        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

    def test_plan_rejects_one_missing_interaction_mapping(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        plan["interaction_mappings"].pop()

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_implementation_coverage", rejected.stderr)

    def test_plan_rejects_an_interaction_bound_to_the_wrong_components(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        plan["interaction_mappings"][0]["component_instance_ids"] = [
            "wrong-component-instance"
        ]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("interaction_implementation_coverage", rejected.stderr)

    def test_plan_rejects_one_missing_api_adapter_mapping(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        plan["api_contract_mappings"].pop()

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_implementation_coverage", rejected.stderr)

    def test_plan_rejects_an_api_adapter_colocated_with_its_interaction(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        api_mapping = plan["api_contract_mappings"][0]
        graph = next(
            item
            for item in read_json(self.stage_dir / "coverage-universe.json")[
                "interaction_graphs"
            ]
            if item["page_key"] == api_mapping["page_key"]
        )
        api_interaction = next(
            interaction
            for interaction in graph["interactions"]
            if interaction["behavior"] is not None
            and interaction["behavior"]["api_contract_id"]
            == api_mapping["api_contract_id"]
        )
        interaction_mapping = next(
            mapping
            for mapping in plan["interaction_mappings"]
            if mapping["page_key"] == graph["page_key"]
            and mapping["interaction_id"] == api_interaction["interaction_id"]
        )
        page = next(
            page
            for page in plan["pages"]
            if page["page_key"] == api_mapping["page_key"]
        )
        page["api_adapter_file"] = interaction_mapping["source_file"]
        api_mapping["source_file"] = interaction_mapping["source_file"]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_implementation_boundary", rejected.stderr)

    def test_plan_rejects_an_api_adapter_colocated_with_the_dto(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        page = plan["pages"][0]
        page["api_adapter_file"] = page["dto_file"]
        for mapping in plan["api_contract_mappings"]:
            if mapping["page_key"] == page["page_key"]:
                mapping["source_file"] = page["dto_file"]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_implementation_boundary", rejected.stderr)

    def test_verify_rejects_an_api_method_mentioned_only_in_a_comment(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        universe, evidence = self.prepare_verifiable_implementation(plan)
        api_mapping = plan["api_contract_mappings"][0]
        graph = next(
            item
            for item in universe["interaction_graphs"]
            if item["page_key"] == api_mapping["page_key"]
        )
        api_interaction = next(
            item
            for item in graph["interactions"]
            if item["behavior"] is not None
            and item["behavior"]["api_contract_id"] == api_mapping["api_contract_id"]
        )
        interaction_mapping = next(
            item
            for item in plan["interaction_mappings"]
            if item["interaction_id"] == api_interaction["interaction_id"]
            and item["page_key"] == graph["page_key"]
        )
        source_path = self.project / interaction_mapping["source_file"]
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace(
                f"{api_mapping['method_symbol']}()",
                f"// call {api_mapping['method_symbol']}()",
            ),
            encoding="utf-8",
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_interaction_not_implemented", rejected.stderr)

    def test_verify_rejects_an_api_method_that_is_only_declared(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        universe, evidence = self.prepare_verifiable_implementation(plan)
        api_mapping = plan["api_contract_mappings"][0]
        graph = next(
            item
            for item in universe["interaction_graphs"]
            if item["page_key"] == api_mapping["page_key"]
        )
        api_interaction = next(
            item
            for item in graph["interactions"]
            if item["behavior"] is not None
            and item["behavior"]["api_contract_id"]
            == api_mapping["api_contract_id"]
        )
        interaction_mapping = next(
            item
            for item in plan["interaction_mappings"]
            if item["interaction_id"] == api_interaction["interaction_id"]
            and item["page_key"] == graph["page_key"]
        )
        source_path = self.project / interaction_mapping["source_file"]
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace(
                f"{api_mapping['method_symbol']}()",
                f"fun {api_mapping['method_symbol']}() = Unit",
            ),
            encoding="utf-8",
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_interaction_not_implemented", rejected.stderr)

    def test_codegen_prompt_and_complete_block_join_are_frozen_inputs(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        state = read_json(self.stage_dir / "state.json")
        prompt_path = self.stage_dir / "implementation-prompt.md"
        self.assertTrue(prompt_path.is_file())
        prompt_text = prompt_path.read_text(encoding="utf-8")
        wrapped_prompt_text = " ".join(prompt_text.split())
        for required_instruction in (
            "Read the entire packet before editing",
            "Query the live codebase for every `component_id`",
            "`platform_best_practices` fills only",
            "Work one strict vertical case at a time",
            "only the current page node",
            "`file_owners`",
            "`visual_state_id`",
            "cold start",
            "Never inject a terminal `icp_state`",
            "production interaction trace",
            "`runtime_probe_tag`",
            "Do not create a debug-only duplicate renderer",
            "Human-authored fidelity booleans are forbidden",
            "Implement every bound `design_element.design_facts`",
            "`layout_contracts`",
            "Do not publish `no_clip`",
            "affected design-element obligation",
            "fix the implementation",
            "`interaction_graph`",
            "`api_call`",
            "mapped adapter method",
            "IcpBoundElement(",
            "exactly one production element binding",
            "assetRefs",
            "reference color footprint",
            "one obligation probe",
            "production UI tag is not unique",
        ):
            self.assertIn(required_instruction, wrapped_prompt_text)
        self.assertEqual(state["implementation_prompt_sha256"], hashlib.sha256(prompt_path.read_bytes()).hexdigest())
        plan_input = read_json(self.stage_dir / "implementation-plan.input.json")
        self.assertEqual(plan_input["implementation_prompt"]["content"], prompt_text)
        self.assertEqual(
            plan_input["platform_best_practices"]["content"],
            (self.stage_dir / "platform-best-practices.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(plan_input["component_definitions"], read_json(self.stage_dir / "coverage-universe.json")["component_definitions"])
        self.assertNotIn("codebase_index", plan_input)
        self.assertNotIn("component_implementation_origins", plan_input)

        plan = self.valid_plan()
        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        packet = read_json(next((self.stage_dir / "codegen-packets").glob("*.json")))
        self.assertEqual(packet["implementation_prompt"], plan_input["implementation_prompt"])
        self.assertEqual(packet["platform_best_practices"], plan_input["platform_best_practices"])
        self.assertNotIn("codebase_index", packet)
        self.assertNotIn("component_implementation_origins", packet)
        self.assertTrue(packet["reference_viewport_assertions"])
        self.assertEqual(
            {
                item["runtime_probe_tag"]
                for item in packet["design_element_mappings"]
                if item["runtime_probe_tag"] is not None
            },
            {item["probe_tag"] for item in packet["reference_viewport_assertions"]},
        )
        packet_component_ids = {item["component_id"] for item in packet["component_instances"]}
        self.assertEqual(
            {item["component_id"] for item in packet["component_definitions"]},
            packet_component_ids,
        )
        self.assertTrue(
            all(
                {
                    "candidate_id",
                    "member_title",
                    "parent_design_instance_id",
                    "slot",
                }.issubset(block)
                for block in packet["blocks"]
            )
        )

    def test_visual_difference_cannot_override_failed_real_color_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        universe, evidence = self.prepare_verifiable_implementation(plan)
        for visual_run in evidence["visual_runs"]:
            actual = self.project / visual_run["actual_screenshot"]
            width, height, pixels = IMPLEMENTATION.read_png_rgba(actual)
            IMPLEMENTATION.write_png_rgba(
                actual,
                width,
                height,
                [
                    (255 - red, 255 - green, 255 - blue, alpha)
                    for red, green, blue, alpha in pixels
                ],
            )
            capture_path = self.project / visual_run["capture_evidence"]
            capture = read_json(capture_path)
            capture["actual_sha256"] = hashlib.sha256(actual.read_bytes()).hexdigest()
            capture_path.write_text(
                json.dumps(capture, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            IMPLEMENTATION.implementation_checklist_call(
                self.stage_dir,
                read_json(self.stage_dir / "state.json"),
                universe,
                "complete",
                node_id=f"visual:{visual_run['design_name']}.capture",
                evidence_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest(),
            )

        verified = self.verify_implementation(evidence)

        self.assertNotEqual(verified.returncode, 0)
        self.assertIn("reference_viewport_measurement_failed", verified.stderr)
        self.assertIn("captured production pixels", verified.stderr)

    def test_responsive_evidence_requires_raw_measurements_not_authored_booleans(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(plan)
        responsive_path = self.project / evidence["responsive_runs"][0]["capture_evidence"]
        responsive = read_json(responsive_path)
        responsive["snapshots"][0]["no_clip"] = True
        write_json(responsive_path, responsive)

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("responsive_evidence_invalid", rejected.stderr)

    def test_verify_rejects_runtime_evidence_not_recorded_by_capture_commands(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(
            plan, record_runtime_capture=False
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("runtime_evidence_not_captured", rejected.stderr)

    def test_code_change_invalidates_only_its_page_runtime_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(plan)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        changed_page = frozen["pages"][0]
        source = self.project / changed_page["dto_file"]
        source.write_text(
            source.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("runtime_evidence_not_captured", rejected.stderr)
        checklist = read_json(self.stage_dir / "checklist.json")
        by_id = {item["node_id"]: item for item in checklist["nodes"]}
        self.assertEqual(
            by_id[f"responsive:{changed_page['page_key']}.compact"]["status"],
            "pending",
        )
        other_pages = [
            page for page in frozen["pages"] if page["page_key"] != changed_page["page_key"]
        ]
        if other_pages:
            self.assertEqual(
                by_id[f"responsive:{other_pages[0]['page_key']}.compact"]["status"],
                "completed",
            )

    def test_every_component_must_have_one_measured_runtime_occurrence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(plan)
        responsive_path = self.project / evidence["responsive_runs"][0]["capture_evidence"]
        responsive = read_json(responsive_path)
        responsive["snapshots"][0]["components"].pop()
        write_json(responsive_path, responsive)

        rejected_component = self.verify_implementation(evidence)

        self.assertNotEqual(rejected_component.returncode, 0)
        self.assertIn("responsive_evidence_invalid", rejected_component.stderr)

    def test_project_common_rules_are_a_frozen_codegen_input_and_drift_fails_closed(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()

        (self.project / "common-rules.md").write_text(
            self.common_rules_text + "Changed after begin.\n", encoding="utf-8"
        )
        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("stage_drift", rejected.stderr)

    def test_record_plan_rejects_one_missing_design_element_then_freezes_codegen_packets(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        missing = plan["design_element_mappings"].pop()

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("coverage_incomplete", rejected.stderr)

        plan["design_element_mappings"].append(missing)
        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        result = json.loads(recorded.stdout)
        self.assertEqual(result["state"], "awaiting_red")
        state = read_json(self.stage_dir / "state.json")
        self.assertRegex(state["implementation_plan_sha256"], r"^[0-9a-f]{64}$")
        for page_key in read_json(self.stage_dir / "coverage-universe.json")["page_keys"]:
            packet = read_json(self.stage_dir / "codegen-packets" / f"{page_key}.json")
            self.assertEqual(packet["page"]["page_key"], page_key)
            self.assertTrue(packet["component_mappings"])
            self.assertTrue(packet["design_elements"])

    def test_component_coverage_is_order_independent(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        page = next(
            item for item in plan["pages"] if len(item["component_instance_ids"]) > 1
        )
        page["component_instance_ids"].reverse()

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_component_lock_storage_order_does_not_change_page_coverage(self) -> None:
        def interleave_global_instance_storage(plan: dict) -> dict:
            by_page: dict[str, list[dict]] = {}
            for instance in plan["component_instances"]:
                by_page.setdefault(instance["page_key"], []).append(instance)
            interleaved: list[dict] = []
            while any(by_page.values()):
                for page_key in sorted(by_page):
                    if by_page[page_key]:
                        interleaved.append(by_page[page_key].pop(0))
            plan["component_instances"] = interleaved
            return plan

        self.begin_component_stage(plan_transform=interleave_global_instance_storage)

        universe = read_json(self.stage_dir / "coverage-universe.json")
        stored_order = [item["page_key"] for item in universe["component_instances"]]
        self.assertNotEqual(
            stored_order,
            sorted(stored_order),
            "fixture must interleave component instances across pages",
        )
        plan = self.valid_plan()

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        self.assertEqual(frozen["page_keys"], universe["page_keys"])
        for page in frozen["pages"]:
            expected = [
                item["component_instance_id"]
                for item in universe["component_instances"]
                if item["page_key"] == page["page_key"]
            ]
            self.assertEqual(set(page["component_instance_ids"]), set(expected))
            self.assertEqual(len(page["component_instance_ids"]), len(expected))

    @staticmethod
    def merge_page_into_single_candidate(page: dict, facts: dict) -> dict:
        """One candidate owns the whole design so its instance carries two Block obligations."""

        design_name = facts["design_names"][0]
        content = facts["candidates"][1]
        facts["candidates"] = [
            {
                "candidate_id": content["candidate_id"],
                "name": content["name"],
                "kind": "component",
                "responsibility": (
                    f"Own {facts['member_title']}'s root boundary and business content."
                ),
                "owns": ["The page root boundary and the page-specific content."],
                "excludes": ["Any other page's semantics."],
                "source_block_refs": [
                    {"design_name": design_name, "block_id": "page"},
                    {"design_name": design_name, "block_id": "content"},
                ],
                "facts": content["facts"],
            }
        ]
        facts["design_compositions"] = [
            {
                "design_name": design_name,
                "root_instance_id": f"{facts['page_key']}-root-instance",
                "instances": [
                    {
                        "instance_id": f"{facts['page_key']}-root-instance",
                        "candidate_id": content["candidate_id"],
                        "parent_instance_id": None,
                        "slot": "root",
                        "source_block_ids": ["page", "content"],
                    }
                ],
            }
        ]
        return facts

    def test_block_obligation_coverage_is_order_independent(self) -> None:
        def merge_design_a(page: dict, facts: dict) -> dict:
            if page["member_title"] != "Design A":
                return facts
            return self.merge_page_into_single_candidate(page, facts)

        def keep_page_shell_local(plan: dict) -> dict:
            decision = next(
                item
                for item in plan["decisions"]
                if item["decision_id"] == "extract-shared-page-shell"
            )
            decision.update(
                {
                    "decision_id": "keep-page-shell-separate",
                    "kind": "keep-separate",
                    "rationale": "The remaining page shell stays page-local.",
                    "alternatives_rejected": ["Sharing one page's shell with another page."],
                }
            )
            definition = next(
                item
                for item in plan["component_definitions"]
                if item["component_id"] == "shared-page-shell"
            )
            definition["scope"] = "local"
            definition["reuse_mode"] = "local"
            return plan

        self.begin_component_stage(
            page_facts_transform=merge_design_a,
            plan_transform=keep_page_shell_local,
        )
        plan = self.valid_plan()
        mapping = next(
            item
            for item in plan["component_mappings"]
            if len(item["block_obligation_ids"]) > 1
        )
        expected = list(mapping["block_obligation_ids"])
        mapping["block_obligation_ids"].reverse()

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        frozen_mapping = next(
            item
            for item in frozen["component_mappings"]
            if item["component_instance_id"] == mapping["component_instance_id"]
        )
        self.assertEqual(frozen_mapping["block_obligation_ids"], expected)

        self.begin_component_stage(
            page_facts_transform=merge_design_a,
            plan_transform=keep_page_shell_local,
        )
        plan = self.valid_plan()
        mapping = next(
            item
            for item in plan["component_mappings"]
            if len(item["block_obligation_ids"]) > 1
        )
        expected = list(mapping["block_obligation_ids"])

        duplicate = list(expected)
        duplicate[0] = duplicate[1]
        mapping["block_obligation_ids"] = duplicate
        rejected = self.record_plan(plan)
        self.assertNotEqual(rejected.returncode, 0)
        error = json.loads(rejected.stderr)
        self.assertEqual(error["error"], "coverage_incomplete")
        self.assertEqual(
            error["details"]["component_instance_id"],
            mapping["component_instance_id"],
        )
        self.assertEqual(error["details"]["duplicates"], [duplicate[1]])
        self.assertEqual(error["details"]["missing"], [expected[0]])

        mapping["block_obligation_ids"] = ["unexpected-block", *expected[1:]]
        rejected = self.record_plan(plan)
        self.assertNotEqual(rejected.returncode, 0)
        error = json.loads(rejected.stderr)
        self.assertEqual(error["error"], "coverage_incomplete")
        self.assertEqual(error["details"]["unexpected"], ["unexpected-block"])
        self.assertEqual(error["details"]["missing"], [expected[0]])

    def test_component_coverage_error_reports_exact_missing_and_unexpected_ids(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        page = plan["pages"][0]
        missing = page["component_instance_ids"][0]
        page["component_instance_ids"][0] = "unexpected-instance"

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        error = json.loads(rejected.stderr)
        self.assertEqual(error["error"], "component_coverage_mismatch")
        self.assertEqual(error["details"]["page_key"], page["page_key"])
        self.assertEqual(error["details"]["missing"], [missing])
        self.assertEqual(error["details"]["unexpected"], ["unexpected-instance"])

    @staticmethod
    def share_one_interaction_with_the_page_shell(page: dict, facts: dict) -> dict:
        """Bind one interaction to two distinct instances (page shell + content)."""

        shell = facts["candidates"][0]
        interaction = next(
            item
            for item in facts["source_coverage"]
            if item["clause_id"] == "page:interaction"
        )
        segment = interaction["segments"][0]
        source_ref = {
            "member_title": facts["member_title"],
            "clause_id": interaction["clause_id"],
            "source_sha256": interaction["source_sha256"],
            "start": segment["start"],
            "end": segment["end"],
            "quote": segment["quote"],
        }
        fact_id = f"{facts['page_key']}-shell-trigger"
        meaning = f"User interaction starts the {facts['member_title']} page flow."
        shell["facts"].append(
            {
                "fact_id": fact_id,
                "evidence_class": "business_source",
                "kind": "trigger",
                "meaning": meaning,
                "source_refs": [source_ref],
                "block_refs": [
                    {"design_name": facts["design_names"][0], "block_id": "page"}
                ],
            }
        )
        segment["fact_ids"].append(fact_id)
        facts["interaction_items"].append(
            {
                "item_id": fact_id,
                "source_ref": source_ref,
                "condition": None,
                "state": None,
                "trigger": {"fact_id": fact_id, "meaning": meaning},
                "behavior": None,
                "result": None,
            }
        )
        graph_interaction = next(
            item
            for item in facts["interaction_graph"]["interactions"]
            if item["interaction_id"] == f"{facts['page_key']}-interaction"
        )
        graph_interaction["trigger"] = {"fact_ids": [fact_id], "inference_basis": []}
        graph_interaction["component_bindings"]["trigger_candidate_ids"] = [
            shell["candidate_id"]
        ]
        return facts

    def test_interaction_component_coverage_is_order_independent(self) -> None:
        def share_with_shell(page: dict, facts: dict) -> dict:
            if page["member_title"] != "Design B":
                return facts
            return self.share_one_interaction_with_the_page_shell(page, facts)

        self.begin_component_stage(page_facts_transform=share_with_shell)
        plan = self.valid_plan()
        mapping = next(
            item
            for item in plan["interaction_mappings"]
            if len(item["component_instance_ids"]) > 1
        )
        expected = list(mapping["component_instance_ids"])
        mapping["component_instance_ids"].reverse()

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        frozen_mapping = next(
            item
            for item in frozen["interaction_mappings"]
            if item["interaction_id"] == mapping["interaction_id"]
        )
        self.assertEqual(frozen_mapping["component_instance_ids"], expected)

        self.begin_component_stage(page_facts_transform=share_with_shell)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        plan = self.valid_plan()
        mapping = next(
            item
            for item in plan["interaction_mappings"]
            if len(item["component_instance_ids"]) > 1
        )
        expected = list(mapping["component_instance_ids"])

        duplicate = list(expected)
        duplicate[0] = duplicate[1]
        mapping["component_instance_ids"] = duplicate
        rejected = self.record_plan(plan)
        self.assertNotEqual(rejected.returncode, 0)
        error = json.loads(rejected.stderr)
        self.assertEqual(error["error"], "interaction_implementation_coverage")
        self.assertEqual(error["details"]["duplicates"], [duplicate[1]])
        self.assertEqual(error["details"]["missing"], [expected[0]])

        wrong_page_instance = next(
            item["component_instance_id"]
            for item in universe["component_instances"]
            if item["page_key"] != mapping["page_key"]
        )
        mapping["component_instance_ids"] = [wrong_page_instance, *expected[1:]]
        rejected = self.record_plan(plan)
        self.assertNotEqual(rejected.returncode, 0)
        error = json.loads(rejected.stderr)
        self.assertEqual(error["error"], "interaction_implementation_coverage")
        self.assertEqual(error["details"]["unexpected"], [wrong_page_instance])
        self.assertEqual(error["details"]["missing"], [expected[0]])

    def test_integration_basis_fact_coverage_is_order_independent(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        case = next(
            item
            for item in plan["integration_test_cases"]
            if len(item["basis_fact_ids"]) > 1
        )
        expected = list(case["basis_fact_ids"])
        case["basis_fact_ids"].reverse()

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        frozen_case = next(
            item
            for item in frozen["integration_test_cases"]
            if item["case_id"] == case["case_id"]
        )
        self.assertEqual(frozen_case["basis_fact_ids"], expected)

        self.begin_component_stage()
        plan = self.valid_plan()
        case = next(
            item
            for item in plan["integration_test_cases"]
            if len(item["basis_fact_ids"]) > 1
        )
        expected = list(case["basis_fact_ids"])

        duplicate = list(expected)
        duplicate[0] = duplicate[1]
        case["basis_fact_ids"] = duplicate
        rejected = self.record_plan(plan)
        self.assertNotEqual(rejected.returncode, 0)
        error = json.loads(rejected.stderr)
        self.assertEqual(error["error"], "coverage_incomplete")
        self.assertEqual(error["details"]["case_id"], case["case_id"])
        self.assertEqual(error["details"]["duplicates"], [duplicate[1]])
        self.assertEqual(error["details"]["missing"], [expected[0]])

        case["basis_fact_ids"] = ["unexpected-fact", *expected[1:]]
        rejected = self.record_plan(plan)
        self.assertNotEqual(rejected.returncode, 0)
        error = json.loads(rejected.stderr)
        self.assertEqual(error["error"], "coverage_incomplete")
        self.assertEqual(error["details"]["unexpected"], ["unexpected-fact"])
        self.assertEqual(error["details"]["missing"], [expected[0]])

    def test_android_integration_cases_must_run_the_real_device_test_surface(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        case = plan["integration_test_cases"][0]
        case["command"] = ["./gradlew", "testDebugUnitTest"]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("integration_runtime_unproven", rejected.stderr)

    def test_android_integration_case_selector_must_match_the_exact_test_method(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        case = plan["integration_test_cases"][0]
        case["command"] = [
            "./gradlew",
            "connectedDebugAndroidTest",
            "-Pnote=" + case["test_name"],
        ]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("integration_runtime_unproven", rejected.stderr)

    def test_android_integration_rejects_a_device_test_that_bypasses_the_ui_surface(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        case = next(
            item
            for item in plan["integration_test_cases"]
            if item["source_kind"] == "interaction_description"
        )
        (self.project / case["test_file"]).write_text(
            (
                "package test\n"
                "import kotlin.test.assertEquals\n"
                "class Bypass {{\n"
                f"    fun {case['test_name']}() = assertEquals(Expected.Done, Rules.finish())\n"
                "}\n"
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "ICP-generated real UI contract"
        ):
            IMPLEMENTATION.exact_android_test_contract(
                self.project.resolve(), case
            )

    def test_record_plan_materializes_an_immutable_real_ui_test(self) -> None:
        self.begin_component_stage()
        self.write_fake_gradle("app_behavior")
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        case = plan["integration_test_cases"][0]
        source = (self.project / case["test_file"]).read_text(encoding="utf-8")

        self.assertIn("instrumentation.startActivitySync(intent)", source)
        self.assertIn("production UI tag is not reachable", source)
        self.assertNotIn("Rules.", source)
        IMPLEMENTATION.exact_android_test_contract(self.project.resolve(), case)

    def test_record_plan_generates_unique_production_node_lookup(self) -> None:
        self.begin_component_stage()
        self.write_fake_gradle("app_behavior")
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        case = plan["integration_test_cases"][0]
        source = (self.project / case["test_file"]).read_text(encoding="utf-8")

        self.assertIn("private fun matchingNodes", source)
        self.assertIn("production UI tag is not unique: $tag", source)
        self.assertIn("node.packageName?.toString() == productionPackage", source)
        self.assertNotIn("if (matches(node, tag)) return node", source)

    def test_record_plan_generates_pre_and_post_trigger_result_observations(self) -> None:
        self.begin_component_stage()
        self.write_fake_gradle("app_behavior")
        authored_plan = self.valid_plan()
        authored_plan["integration_test_cases"][0]["runtime_test"]["actions"] = [
            {
                "operator": "click",
                "target_tag": "icp-action-transition",
                "value": None,
                "fact_ids": [],
            }
        ]
        recorded = self.record_plan(authored_plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        case = next(
            item
            for item in plan["integration_test_cases"]
            if item["runtime_test"]["actions"]
        )
        source = (self.project / case["test_file"]).read_text(encoding="utf-8")

        self.assertIn("beforeResultObservations", source)
        self.assertIn("afterResultObservations", source)
        self.assertIn("production result already satisfied before trigger", source)
        self.assertIn("production result was not satisfied after trigger", source)

    def test_record_plan_rejects_api_call_without_runtime_network_observation(self) -> None:
        self.begin_component_stage()
        authored_plan = self.valid_plan()
        universe = read_json(self.stage_dir / "coverage-universe.json")
        api_interaction_ids = {
            interaction["interaction_id"]
            for graph in universe["interaction_graphs"]
            for interaction in graph["interactions"]
            if interaction.get("behavior") is not None
            and interaction["behavior"]["kind"] == "api_call"
        }
        api_case = next(
            case
            for case in authored_plan["integration_test_cases"]
            if case["obligation_id"] in {
                obligation["obligation_id"]
                for obligation in universe["integration_obligations"]
                if obligation.get("interaction_id") in api_interaction_ids
                or obligation.get("item_id") in api_interaction_ids
            }
        )
        api_case["runtime_test"].pop("network_expectation")

        rejected = self.record_plan(authored_plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_call requires runtime network observation", rejected.stderr)

    def test_record_plan_rejects_api_call_without_response_value_probe(self) -> None:
        self.begin_component_stage()
        authored_plan = self.valid_plan()
        api_case = next(
            case
            for case in authored_plan["integration_test_cases"]
            if case["runtime_test"]["network_expectation"] is not None
        )
        api_case["runtime_test"]["network_expectation"].pop("response_probe")

        rejected = self.record_plan(authored_plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("api_call requires a response-derived UI probe", rejected.stderr)

    def test_record_plan_rejects_page_without_runtime_mock_dto_probe(self) -> None:
        self.begin_component_stage()
        authored_plan = self.valid_plan()
        for case in authored_plan["integration_test_cases"]:
            case["runtime_test"].pop("mock_expectation", None)

        rejected = self.record_plan(authored_plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("every page requires one runtime mock DTO probe", rejected.stderr)

    def test_record_plan_generates_device_side_network_observer_for_api_call(self) -> None:
        self.begin_component_stage()
        self.write_fake_gradle("app_behavior")
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        case = next(
            item
            for item in plan["integration_test_cases"]
            if item["runtime_test"]["network_expectation"] is not None
        )
        expectation = case["runtime_test"]["network_expectation"]
        source = (self.project / case["test_file"]).read_text(encoding="utf-8")

        self.assertIn("ServerSocket(0)", source)
        self.assertIn(
            'intent.putExtra("icp_api_base_url", networkRecorder.baseUrl)', source
        )
        self.assertIn("val observedRequest = networkRecorder.awaitRequest()", source)
        self.assertIn("production result appeared before API response", source)
        self.assertIn("networkRecorder.releaseResponse()", source)
        self.assertIn("UUID.randomUUID().toString()", source)
        self.assertIn(
            '.replace("__ICP_RUNTIME_CANARY__", responseCanary)', source
        )
        self.assertIn("production UI did not render the API response value", source)
        self.assertIn(
            f'assertEquals("{expectation["method"]}", observedRequest.method)',
            source,
        )
        self.assertIn(
            f'assertEquals("{expectation["path"]}", observedRequest.path)',
            source,
        )
        result_assertion = case["runtime_test"]["assertions"][0]["target_tag"]
        self.assertLess(
            source.index("val observedRequest = networkRecorder.awaitRequest()"),
            source.index("networkRecorder.releaseResponse()"),
        )
        self.assertLess(
            source.index("networkRecorder.releaseResponse()"),
            source.rindex(result_assertion),
        )

    def test_record_plan_generates_runtime_mock_dto_probe(self) -> None:
        self.begin_component_stage()
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        case = next(
            item
            for item in plan["integration_test_cases"]
            if item["runtime_test"]["mock_expectation"] is not None
        )
        source = (self.project / case["test_file"]).read_text(encoding="utf-8")

        self.assertIn('intent.putExtra("icp_mock_payload", mockPayload)', source)
        self.assertIn("UUID.randomUUID().toString()", source)
        self.assertIn("production UI did not render the mock DTO value", source)

    def test_record_plan_rejects_api_failure_continuation_without_network_error_observation(self) -> None:
        self.begin_component_stage()
        universe = read_json(self.stage_dir / "coverage-universe.json")
        graph = next(
            item
            for item in universe["interaction_graphs"]
            if any(
                interaction.get("behavior") is not None
                and interaction["behavior"].get("kind") == "api_call"
                for interaction in item["interactions"]
            )
        )
        api_interaction = next(
            interaction
            for interaction in graph["interactions"]
            if interaction.get("behavior") is not None
            and interaction["behavior"].get("kind") == "api_call"
        )
        failure_target = next(
            edge["target"]["to_interaction_id"]
            for edge in graph["edges"]
            if edge["from_interaction_id"] == api_interaction["interaction_id"]
            and edge["outcome"] == "failure"
            and edge["target"]["kind"] == "interaction"
        )
        plan = self.valid_plan()
        failure_case = next(
            case
            for case in plan["integration_test_cases"]
            if next(
                obligation
                for obligation in universe["integration_obligations"]
                if obligation["obligation_id"] == case["obligation_id"]
            )["item_id"]
            == failure_target
        )
        failure_case["runtime_test"]["network_expectation"] = None

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("API failure result requires runtime disconnect observation", rejected.stderr)

    def test_record_plan_generates_runtime_disconnect_for_api_failure_result(self) -> None:
        self.begin_component_stage()
        recorded = self.record_plan(self.valid_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        case = next(
            item
            for item in plan["integration_test_cases"]
            if item["runtime_test"]["network_expectation"] is not None
            and item["runtime_test"]["network_expectation"]["mode"] == "disconnect"
        )
        source = (self.project / case["test_file"]).read_text(encoding="utf-8")

        self.assertIn("disconnectAfterRequest = true", source)
        self.assertIn("if (disconnectAfterRequest) return@use", source)
        self.assertIn("val observedRequest = networkRecorder.awaitRequest()", source)
        self.assertIn("production result appeared before API failure", source)
        self.assertIn("networkRecorder.releaseResponse()", source)
        self.assertNotIn("production UI did not render the API response value", source)
        result_assertion = case["runtime_test"]["assertions"][0]["target_tag"]
        self.assertLess(
            source.index("networkRecorder.releaseResponse()"),
            source.rindex(result_assertion),
        )

    def test_verify_rejects_valid_json_that_differs_from_runtime_mock_dto_input(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(plan)
        frozen_plan = read_json(self.stage_dir / "implementation-plan.json")
        mock_page_key = next(
            case["page_key"]
            for case in frozen_plan["integration_test_cases"]
            if case["runtime_test"]["mock_expectation"] is not None
        )
        page = next(
            item for item in frozen_plan["pages"] if item["page_key"] == mock_page_key
        )
        (self.project / page["mock_fixture_path"]).write_text(
            '{"different":"but-valid-json"}\n', encoding="utf-8"
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("mock fixture differs from its runtime DTO input", rejected.stderr)

    def test_runtime_ui_contract_preserves_trigger_to_result_causality(self) -> None:
        obligation = {
            "source_kind": "interaction_description",
            "page_key": "page-a",
            "item_id": "submit",
            "basis_fact_ids": ["trigger-submit", "result-done"],
        }
        universe = {
            "interaction_graphs": [
                {
                    "page_key": "page-a",
                    "interactions": [
                        {
                            "interaction_id": "submit",
                            "condition": None,
                            "state": None,
                            "trigger": {"fact_ids": ["trigger-submit"]},
                            "behavior": None,
                            "result": {"fact_ids": ["result-done"]},
                        }
                    ],
                }
            ]
        }
        contract = {
            "entry_tag": "entry",
            "preconditions": [],
            "actions": [],
            "assertions": [
                {
                    "operator": "visible",
                    "target_tag": "done",
                    "value": None,
                    "fact_ids": ["trigger-submit", "result-done"],
                }
            ],
        }

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "frozen interaction causality"
        ):
            IMPLEMENTATION.validate_runtime_ui_test_contract(
                contract, obligation, universe
            )

    def test_runtime_ui_contract_requires_condition_and_state_before_the_trigger(self) -> None:
        obligation = {
            "source_kind": "interaction_description",
            "page_key": "page-a",
            "item_id": "submit",
            "basis_fact_ids": [
                "condition-online",
                "state-ready",
                "trigger-submit",
                "behavior-send",
                "result-done",
            ],
        }
        universe = {
            "interaction_graphs": [
                {
                    "page_key": "page-a",
                    "interactions": [
                        {
                            "interaction_id": "submit",
                            "condition": {"fact_ids": ["condition-online"]},
                            "state": {"fact_ids": ["state-ready"]},
                            "trigger": {"fact_ids": ["trigger-submit"]},
                            "behavior": {"fact_ids": ["behavior-send"]},
                            "result": {"fact_ids": ["result-done"]},
                        }
                    ],
                }
            ]
        }
        contract = {
            "entry_tag": "entry",
            "preconditions": [],
            "actions": [
                {
                    "operator": "click",
                    "target_tag": "submit",
                    "value": None,
                    "fact_ids": ["trigger-submit"],
                }
            ],
            "assertions": [
                {
                    "operator": "visible",
                    "target_tag": "done",
                    "value": None,
                    "fact_ids": [
                        "condition-online",
                        "state-ready",
                        "behavior-send",
                        "result-done",
                    ],
                }
            ],
        }

        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "frozen interaction causality"
        ):
            IMPLEMENTATION.validate_runtime_ui_test_contract(
                contract, obligation, universe
            )

    def test_android_integration_rejects_a_non_device_task_with_androidtest_in_a_flag(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        case = plan["integration_test_cases"][0]
        selector = next(
            value
            for value in case["command"]
            if value.startswith("-Pandroid.testInstrumentationRunnerArguments.class=")
        )
        case["command"] = [
            "./gradlew",
            "help",
            "--init-script",
            "fake-androidtest.gradle",
            selector,
        ]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("integration_runtime_unproven", rejected.stderr)

    def test_android_integration_rejects_an_arbitrary_androidtest_named_task(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        case = plan["integration_test_cases"][0]
        selector = next(
            value
            for value in case["command"]
            if value.startswith("-Pandroid.testInstrumentationRunnerArguments.class=")
        )
        case["command"] = ["./gradlew", "fakeAndroidTest", selector]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("integration_runtime_unproven", rejected.stderr)

    def test_each_integration_obligation_requires_a_distinct_device_test(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        first = plan["integration_test_cases"][0]
        second = next(
            item
            for item in plan["integration_test_cases"][1:]
            if item["test_file"] != first["test_file"]
        )
        second["test_name"] = first["test_name"]
        second["command"] = list(first["command"])

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("integration_runtime_unproven", rejected.stderr)

    def test_final_verify_rejects_an_android_test_changed_after_green(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _, evidence = self.prepare_verifiable_implementation(plan)
        frozen_plan = read_json(self.stage_dir / "implementation-plan.json")
        test_path = self.project / frozen_plan["integration_test_cases"][0]["test_file"]
        test_path.write_text(
            test_path.read_text(encoding="utf-8") + "// changed after GREEN\n",
            encoding="utf-8",
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("test_contract_changed", rejected.stderr)

    def test_red_rejects_a_nonzero_command_without_the_exact_failed_device_test(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        self.write_fake_gradle("app_behavior")
        (self.project / "app_behavior.py").write_text(
            "raise RuntimeError('compile failed')\n", encoding="utf-8"
        )

        rejected = self.run_case(case["case_id"], "red")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("red_result_unproven", rejected.stderr)

    def test_android_test_method_must_belong_to_the_selected_test_class(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        selector = next(
            value.split("=", 1)[1]
            for value in case["command"]
            if value.startswith("-Pandroid.testInstrumentationRunnerArguments.class=")
        )
        class_name, method_name = selector.split("#", 1)
        package_name, simple_class = class_name.rsplit(".", 1)
        test_path = self.project / case["test_file"]
        test_path.write_text(
            f"package {package_name}\n"
            f"class {simple_class} {{}}\n"
            f"class UnrelatedTest {{ fun {method_name}() = Unit }}\n",
            encoding="utf-8",
        )
        (self.project / "app_behavior.py").write_text(
            "IMPLEMENTED = False\n", encoding="utf-8"
        )
        self.write_fake_gradle("app_behavior")

        rejected = self.run_case(case["case_id"], "red")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("test_contract_changed", rejected.stderr)

    def test_identical_duplicate_gradle_reports_are_deduplicated_but_conflicts_fail(self) -> None:
        contract = {"class_name": "test.ExactTest", "method_name": "exactCase"}
        roots = [
            self.project / "app/build/outputs/androidTest-results/connected/debug/a",
            self.project / "app/build/outputs/androidTest-results/connected/debug/b",
        ]
        passed = (
            '<testsuite timestamp="2026-01-01T00:00:00"><properties>'
            '<property name="device" value="device-1" /></properties>'
            '<testcase classname="test.ExactTest" name="exactCase" /></testsuite>'
        )
        for index, root in enumerate(roots):
            root.mkdir(parents=True, exist_ok=True)
            (root / f"TEST-{index}.xml").write_text(passed, encoding="utf-8")

        accepted = IMPLEMENTATION.exact_android_test_result(
            self.project, contract, 0
        )
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["status"], "passed")

        conflicting = passed.replace(
            " /></testsuite>", "><failure /></testcase></testsuite>"
        )
        (roots[1] / "TEST-1.xml").write_text(conflicting, encoding="utf-8")

        self.assertIsNone(
            IMPLEMENTATION.exact_android_test_result(self.project, contract, 0)
        )

    def test_android_test_result_uses_agp_report_device_name_when_property_is_absent(self) -> None:
        contract = {"class_name": "test.ExactTest", "method_name": "exactCase"}
        root = self.project / "app/build/outputs/androidTest-results/connected/debug"
        root.mkdir(parents=True, exist_ok=True)
        report = root / "TEST-Pixel_9_Pro(AVD) - 15-_app-.xml"
        report.write_text(
            '<testsuites timestamp="2026-01-01T00:00:00">'
            '<testsuite><testcase classname="test.ExactTest" name="exactCase" />'
            '</testsuite></testsuites>',
            encoding="utf-8",
        )

        accepted = IMPLEMENTATION.exact_android_test_result(
            self.project, contract, 0
        )

        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["device"], "Pixel_9_Pro(AVD) - 15")

    def test_android_test_result_accepts_legacy_agp_suite_device_metadata(self) -> None:
        contract = {"class_name": "test.ExactTest", "method_name": "exactCase"}
        root = self.project / "app/build/outputs/androidTest-results/connected/debug"
        root.mkdir(parents=True, exist_ok=True)
        (root / "TEST-legacy.xml").write_text(
            '<testsuite timestamp="2026-01-01T00:00:00" device="legacy-device">'
            '<testcase classname="test.ExactTest" name="exactCase" />'
            '</testsuite>',
            encoding="utf-8",
        )

        accepted = IMPLEMENTATION.exact_android_test_result(
            self.project, contract, 0
        )

        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["device"], "legacy-device")

    def test_android_test_result_rejects_conflicting_device_metadata(self) -> None:
        contract = {"class_name": "test.ExactTest", "method_name": "exactCase"}
        root = self.project / "app/build/outputs/androidTest-results/connected/debug"
        root.mkdir(parents=True, exist_ok=True)
        (root / "TEST-conflict.xml").write_text(
            '<testsuite timestamp="2026-01-01T00:00:00" device="attribute-device">'
            '<properties><property name="device" value="property-device" /></properties>'
            '<testcase classname="test.ExactTest" name="exactCase" />'
            '</testsuite>',
            encoding="utf-8",
        )

        self.assertIsNone(
            IMPLEMENTATION.exact_android_test_result(self.project, contract, 0)
        )

    def test_red_requires_the_device_command_and_exact_result_to_both_fail(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        selector = next(
            value.split("=", 1)[1]
            for value in case["command"]
            if value.startswith("-Pandroid.testInstrumentationRunnerArguments.class=")
        )
        class_name, test_name = selector.split("#", 1)
        gradle = self.project / "gradlew"
        gradle.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, shutil, sys\n"
            "if sys.argv[1:] == ['clean']:\n"
            "    for build in sorted(pathlib.Path('.').rglob('build'), reverse=True):\n"
            "        if build.is_dir(): shutil.rmtree(build, ignore_errors=True)\n"
            "    raise SystemExit(0)\n"
            "print('Path\\n     :app:connectedDebugAndroidTest\\n\\nType\\n     DeviceProviderInstrumentTestTask (com.android.build.gradle.internal.tasks.DeviceProviderInstrumentTestTask)')\n"
            "print('Starting 1 tests on test-device')\n"
            "path = pathlib.Path('app/build/outputs/androidTest-results/connected/debug')\n"
            "path.mkdir(parents=True, exist_ok=True)\n"
            f"xml = '<testsuite timestamp=\"2026-01-01T00:00:00\"><properties><property name=\"device\" value=\"test-device\" /></properties><testcase classname=\"{class_name}\" name=\"{test_name}\"><failure /></testcase></testsuite>'\n"
            f"(path / 'TEST-{class_name}.xml').write_text(xml, encoding='utf-8')\n"
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        gradle.chmod(0o755)

        rejected = self.run_case(case["case_id"], "red")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("red_not_observed", rejected.stderr)

    def test_run_case_requires_the_real_agp_device_provider_task(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        self.materialize_android_tests(plan)
        (self.project / "app_behavior.py").write_text(
            "IMPLEMENTED = False\n", encoding="utf-8"
        )
        self.write_fake_gradle("app_behavior", attest_task=False)

        rejected = self.run_case(
            plan["integration_test_cases"][0]["case_id"], "red"
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("android_device_task_unproven", rejected.stderr)

    def test_first_red_cleans_old_gradle_outputs_before_device_execution(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        self.materialize_android_tests(plan)
        case = plan["integration_test_cases"][0]
        selector = next(
            value.split("=", 1)[1]
            for value in case["command"]
            if value.startswith(
                "-Pandroid.testInstrumentationRunnerArguments.class="
            )
        )
        class_name, test_name = selector.split("#", 1)
        stale = self.project / "app/build/outputs/apk/debug/stale.apk"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"stale-build")
        gradle = self.project / "gradlew"
        gradle.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, shutil, sys\n"
            "log = pathlib.Path('gradle-order.log')\n"
            "if sys.argv[1:] == ['clean']:\n"
            "    shutil.rmtree('app/build', ignore_errors=True)\n"
            "    log.write_text('clean\\n', encoding='utf-8')\n"
            "    raise SystemExit(0)\n"
            "if pathlib.Path('app/build/outputs/apk/debug/stale.apk').exists():\n"
            "    raise SystemExit(91)\n"
            "with log.open('a', encoding='utf-8') as stream: stream.write('device\\n')\n"
            "print('Path\\n     :app:connectedDebugAndroidTest\\n\\nType\\n     DeviceProviderInstrumentTestTask (com.android.build.gradle.internal.tasks.DeviceProviderInstrumentTestTask)')\n"
            "print('Starting 1 tests on test-device')\n"
            "result = pathlib.Path('app/build/outputs/androidTest-results/connected/debug')\n"
            "result.mkdir(parents=True, exist_ok=True)\n"
            f"xml = '<testsuite timestamp=\"2026-01-01T00:00:00\"><properties><property name=\"device\" value=\"test-device\" /></properties><testcase classname=\"{class_name}\" name=\"{test_name}\"><failure /></testcase></testsuite>'\n"
            f"(result / 'TEST-{class_name}.xml').write_text(xml, encoding='utf-8')\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        gradle.chmod(0o755)

        red = self.run_case(case["case_id"], "red")

        self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        self.assertFalse(stale.exists())
        self.assertEqual(
            (self.project / "gradle-order.log").read_text(encoding="utf-8"),
            "clean\ndevice\n",
        )
        evidence = read_json(self.stage_dir / "tdd-evidence.json")
        baseline = evidence["cases"][0]["red"]["build_baseline"]
        checklist = read_json(self.stage_dir / "checklist.json")
        clean_node = next(
            item for item in checklist["nodes"] if item["node_id"] == "build.clean"
        )
        self.assertEqual(clean_node["status"], "completed")
        self.assertEqual(clean_node["evidence_sha256"], IMPLEMENTATION.digest(baseline))

    def test_run_case_binds_the_selected_android_device_through_the_environment(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        (self.project / "app_behavior.py").write_text(
            "IMPLEMENTED = False\n", encoding="utf-8"
        )
        self.write_fake_gradle("app_behavior")

        observed = self.run_case(
            plan["integration_test_cases"][0]["case_id"],
            "red",
            device_serial="emulator-5554",
        )

        self.assertEqual(observed.returncode, 0, observed.stdout + observed.stderr)
        evidence = read_json(self.stage_dir / "tdd-evidence.json")
        self.assertEqual(
            evidence["cases"][0]["red"]["device_test_result"]["device"],
            "emulator-5554",
        )

    def test_runtime_installation_binds_the_selected_device_without_a_gradle_flag(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen_plan = read_json(self.stage_dir / "implementation-plan.json")
        (self.project / "app_behavior.py").write_text(
            "IMPLEMENTED = True\n", encoding="utf-8"
        )
        self.write_fake_gradle("app_behavior")
        stale = self.project / "app/build/outputs/apk/debug/stale.apk"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"stale-apk")

        receipt = IMPLEMENTATION.attest_android_runtime_installation(
            self.project.resolve(),
            frozen_plan,
            frozen_plan["pages"][0]["page_key"],
            device_serial="emulator-5554",
        )

        self.assertEqual(
            receipt["device_test_result"]["device"], "emulator-5554"
        )
        self.assertFalse(stale.exists())
        self.assertEqual(receipt["build_clean"]["command"], ["./gradlew", "clean"])
        self.assertTrue(receipt["build_clean"]["stale_apks_absent_after_clean"])
        self.assertEqual(
            receipt["built_apks"],
            [
                {
                    "path": "app/build/outputs/apk/debug/app-debug.apk",
                    "size": len(b"production-base-apk"),
                    "sha256": hashlib.sha256(b"production-base-apk").hexdigest(),
                }
            ],
        )
        transaction = IMPLEMENTATION.validate_android_execution_transaction(
            receipt,
            self.installed_package_identity(),
            self.project.resolve(),
            frozen_plan,
            frozen_plan["pages"][0]["page_key"],
        )
        self.assertEqual(
            transaction["installed_apk_matches"],
            [
                {
                    "installed_name": "base.apk",
                    "built_path": "app/build/outputs/apk/debug/app-debug.apk",
                    "sha256": hashlib.sha256(b"production-base-apk").hexdigest(),
                }
            ],
        )
        replaced = self.installed_package_identity()
        replaced["apks"][0]["sha256"] = hashlib.sha256(
            b"another-installed-apk"
        ).hexdigest()
        replaced["sha256"] = IMPLEMENTATION.digest(replaced["apks"])
        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError,
            "do not uniquely match this clean build",
        ):
            IMPLEMENTATION.validate_android_execution_transaction(
                receipt,
                replaced,
                self.project.resolve(),
                frozen_plan,
                frozen_plan["pages"][0]["page_key"],
            )
        (
            self.project / "app/build/outputs/apk/debug/app-debug.apk"
        ).write_bytes(b"changed-after-install")
        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError,
            "built APK inventory changed",
        ):
            IMPLEMENTATION.validate_android_execution_transaction(
                receipt,
                self.installed_package_identity(),
                self.project.resolve(),
                frozen_plan,
                frozen_plan["pages"][0]["page_key"],
            )

    def test_fraction_logical_scale_produces_the_exact_android_density(self) -> None:
        self.assertEqual(IMPLEMENTATION.logical_scale_density("3/2"), 240)

    def test_green_rejects_a_test_changed_after_red(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        behavior = self.project / "app_behavior.py"
        behavior.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("app_behavior")
        red = self.run_case(case["case_id"], "red")
        self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        test_path = self.project / case["test_file"]
        test_path.write_text(
            test_path.read_text(encoding="utf-8") + "// changed after RED\n",
            encoding="utf-8",
        )
        behavior.write_text("IMPLEMENTED = True\n", encoding="utf-8")

        rejected = self.run_case(case["case_id"], "green")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("test_contract_changed", rejected.stderr)

    def test_green_rejects_a_gradle_wrapper_changed_after_red(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        behavior = self.project / "app_behavior.py"
        behavior.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("app_behavior")
        red = self.run_case(case["case_id"], "red")
        self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        wrapper = self.project / "gradlew"
        wrapper.write_text(
            wrapper.read_text(encoding="utf-8") + "# changed after RED\n",
            encoding="utf-8",
        )
        behavior.write_text("IMPLEMENTED = True\n", encoding="utf-8")

        rejected = self.run_case(case["case_id"], "green")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("test_contract_changed", rejected.stderr)

    def test_device_test_rejects_a_gradle_wrapper_changed_from_git_head(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        (self.project / "app_behavior.py").write_text(
            "IMPLEMENTED = False\n", encoding="utf-8"
        )
        self.write_fake_gradle("app_behavior")
        subprocess.run(["git", "init"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "icp-test@example.invalid"],
            cwd=self.project,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "ICP Test"], cwd=self.project, check=True
        )
        subprocess.run(["git", "add", "gradlew"], cwd=self.project, check=True)
        subprocess.run(
            ["git", "commit", "-m", "freeze wrapper"],
            cwd=self.project,
            check=True,
            capture_output=True,
        )
        wrapper = self.project / "gradlew"
        wrapper.write_text(
            wrapper.read_text(encoding="utf-8") + "# uncommitted change\n",
            encoding="utf-8",
        )

        rejected = self.run_case(plan["integration_test_cases"][0]["case_id"], "red")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("differs from its committed", rejected.stderr)

    def test_device_test_report_requires_real_device_and_timestamp_metadata(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        selector = next(
            value.split("=", 1)[1]
            for value in case["command"]
            if value.startswith("-Pandroid.testInstrumentationRunnerArguments.class=")
        )
        class_name, test_name = selector.split("#", 1)
        gradle = self.project / "gradlew"
        gradle.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, shutil, sys\n"
            "if sys.argv[1:] == ['clean']:\n"
            "    for build in sorted(pathlib.Path('.').rglob('build'), reverse=True):\n"
            "        if build.is_dir(): shutil.rmtree(build, ignore_errors=True)\n"
            "    raise SystemExit(0)\n"
            "print('Path\\n     :app:connectedDebugAndroidTest\\n\\nType\\n     DeviceProviderInstrumentTestTask (com.android.build.gradle.internal.tasks.DeviceProviderInstrumentTestTask)')\n"
            "print('Starting 1 tests on test-device')\n"
            "path = pathlib.Path('app/build/outputs/androidTest-results/connected/debug')\n"
            "path.mkdir(parents=True, exist_ok=True)\n"
            f"xml = '<testsuite><testcase classname=\"{class_name}\" name=\"{test_name}\"><failure /></testcase></testsuite>'\n"
            f"(path / 'TEST-{class_name}.xml').write_text(xml, encoding='utf-8')\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        gradle.chmod(0o755)

        rejected = self.run_case(case["case_id"], "red")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("red_result_unproven", rejected.stderr)

    def test_run_case_recovers_when_result_was_written_before_checklist_receipt(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        (self.project / "app_behavior.py").write_text(
            "IMPLEMENTED = False\n", encoding="utf-8"
        )
        self.write_fake_gradle("app_behavior")
        original_checklist_call = IMPLEMENTATION.implementation_checklist_call

        def crash_after_result(*args, **kwargs):
            if args[3] == "complete":
                raise IMPLEMENTATION.ContractError(
                    "simulated_crash", "process stopped before checklist receipt"
                )
            return original_checklist_call(*args, **kwargs)

        with patch.object(
            IMPLEMENTATION,
            "implementation_checklist_call",
            side_effect=crash_after_result,
        ):
            with self.assertRaisesRegex(
                IMPLEMENTATION.ContractError, "before checklist receipt"
            ):
                IMPLEMENTATION.run_case(
                    argparse.Namespace(
                        project_root=str(self.project),
                        case_id=case["case_id"],
                        phase="red",
                    )
                )

        recovered = self.run_case(case["case_id"], "red")

        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        checklist = read_json(self.stage_dir / "checklist.json")
        node = next(
            item
            for item in checklist["nodes"]
            if item["node_id"] == f"case:{case['obligation_id']}.red"
        )
        self.assertEqual(node["status"], "completed")

    def test_run_case_recovers_when_result_was_written_before_state_hash(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        case = plan["integration_test_cases"][0]
        (self.project / "app_behavior.py").write_text(
            "IMPLEMENTED = False\n", encoding="utf-8"
        )
        self.write_fake_gradle("app_behavior")
        original_write = IMPLEMENTATION.atomic_write_json

        def crash_before_state(path: Path, value: object) -> None:
            if path.name == "state.json":
                raise IMPLEMENTATION.ContractError(
                    "simulated_crash", "process stopped before state hash"
                )
            original_write(path, value)

        with patch.object(
            IMPLEMENTATION, "atomic_write_json", side_effect=crash_before_state
        ):
            with self.assertRaisesRegex(
                IMPLEMENTATION.ContractError, "before state hash"
            ):
                IMPLEMENTATION.run_case(
                    argparse.Namespace(
                        project_root=str(self.project),
                        case_id=case["case_id"],
                        phase="red",
                    )
                )

        recovered = self.run_case(case["case_id"], "red")

        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        repaired_state = read_json(self.stage_dir / "state.json")
        self.assertEqual(
            repaired_state["tdd_evidence_sha256"],
            hashlib.sha256((self.stage_dir / "tdd-evidence.json").read_bytes()).hexdigest(),
        )

    def test_execution_plan_assigns_cross_cutting_and_page_files_to_one_owner(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        self.assertEqual(
            frozen["file_owners"]["app/src/main/AndroidManifest.xml"], "foundation"
        )
        self.assertEqual(
            frozen["file_owners"]["app/src/main/MainActivity.kt"],
            "flow-integration",
        )
        self.assertEqual(
            {node["kind"] for node in frozen["execution_nodes"]},
            {"foundation", "page", "flow-integration"},
        )

    def test_visual_states_use_unique_deterministic_ids(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.assertGreaterEqual(len(plan["visual_capture_cases"]), 2)
        first, second = plan["visual_capture_cases"][:2]
        self.assertNotEqual(first["visual_state_id"], second["visual_state_id"])
        second["visual_state_id"] = first["visual_state_id"]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("visual_state_identity_mismatch", rejected.stderr)

    def test_runtime_entry_may_be_the_real_app_entry_not_the_page_renderer(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        entry = plan["runtime_entries"][0]
        entry["source_file"] = "app/src/main/MainActivity.kt"
        entry["symbol"] = "MainActivity"

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        self.assertEqual(
            frozen["runtime_entries"][0]["source_file"],
            "app/src/main/MainActivity.kt",
        )
        self.assertEqual(frozen["runtime_entries"][0]["symbol"], "MainActivity")

    def test_visual_state_rejects_debug_terminal_state_setup(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        secondary = plan["visual_capture_cases"][0]
        universe = read_json(self.stage_dir / "coverage-universe.json")
        graph = next(
            graph
            for graph in universe["interaction_graphs"]
            if graph["page_key"] == secondary["page_key"]
        )
        continuation = next(
            edge for edge in graph["edges"] if edge["target"]["kind"] == "interaction"
        )
        page_case = case_for_interaction(
            universe,
            plan,
            secondary["page_key"],
            continuation["from_interaction_id"],
        )
        secondary["interaction_trace"] = [
            {
                "source_page_key": secondary["page_key"],
                "case_id": page_case["case_id"],
                "interaction_id": continuation["from_interaction_id"],
                "outcome": continuation["outcome"],
                "action": "click",
                "target_tag": "feedback-photo-source-trigger",
            }
        ]
        secondary["precondition_commands"] = [
            [
                "adb",
                "shell",
                "am",
                "start",
                "--es",
                "icp_state",
                secondary["visual_state_id"],
            ]
        ]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("visual_production_path_unproven", rejected.stderr)

    def test_visual_trace_must_use_the_case_action_and_follow_the_selected_edge(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        visual = plan["visual_capture_cases"][0]
        universe = read_json(self.stage_dir / "coverage-universe.json")
        graph = next(
            item
            for item in universe["interaction_graphs"]
            if item["page_key"] == visual["page_key"]
        )
        source_edges = [
            edge
            for edge in graph["edges"]
            if edge["target"]["kind"] == "interaction"
        ]
        self.assertGreaterEqual(len(source_edges), 2)
        first, disconnected = source_edges[:2]
        first_case = case_for_interaction(
            universe, plan, visual["page_key"], first["from_interaction_id"]
        )
        disconnected_case = case_for_interaction(
            universe,
            plan,
            visual["page_key"],
            disconnected["from_interaction_id"],
        )
        if not first_case["runtime_test"]["actions"]:
            first_case["runtime_test"]["actions"].append(
                {
                    "operator": "click",
                    "target_tag": "primary-trigger",
                    "value": None,
                    "fact_ids": [],
                }
            )
        first_action = first_case["runtime_test"]["actions"][0]
        visual["interaction_trace"] = [
            {
                "source_page_key": visual["page_key"],
                "case_id": first_case["case_id"],
                "interaction_id": first["from_interaction_id"],
                "outcome": first["outcome"],
                "action": first_action["operator"],
                "target_tag": first_action["target_tag"],
            },
            {
                "source_page_key": visual["page_key"],
                "case_id": disconnected_case["case_id"],
                "interaction_id": disconnected["from_interaction_id"],
                "outcome": disconnected["outcome"],
                "action": first_action["operator"],
                "target_tag": first_action["target_tag"],
            },
        ]

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("visual_production_path_unproven", rejected.stderr)
        self.assertIn("disconnected_path", rejected.stderr)

        plan = self.valid_plan()
        visual = plan["visual_capture_cases"][0]
        wrong_case = case_for_interaction(
            universe, plan, visual["page_key"], first["from_interaction_id"]
        )
        wrong_case["runtime_test"]["actions"] = [copy.deepcopy(first_action)]
        visual["interaction_trace"] = [
            {
                "source_page_key": visual["page_key"],
                "case_id": wrong_case["case_id"],
                "interaction_id": first["from_interaction_id"],
                "outcome": first["outcome"],
                "action": first_action["operator"],
                "target_tag": "unrelated-production-tag",
            }
        ]

        wrong_action = self.record_plan(plan)

        self.assertNotEqual(wrong_action.returncode, 0)
        self.assertIn("visual_production_path_unproven", wrong_action.stderr)
        self.assertIn("case_action_mismatch", wrong_action.stderr)

    def test_visual_trace_derives_the_complete_multi_action_case_contract(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        visual = plan["visual_capture_cases"][0]
        universe = read_json(self.stage_dir / "coverage-universe.json")
        graph = next(
            item
            for item in universe["interaction_graphs"]
            if item["page_key"] == visual["page_key"]
        )
        edge = next(
            item for item in graph["edges"] if item["target"]["kind"] == "interaction"
        )
        case = case_for_interaction(
            universe, plan, visual["page_key"], edge["from_interaction_id"]
        )
        case["runtime_test"]["actions"] = [
            {
                "operator": "input_text",
                "target_tag": "phone-input",
                "value": "77001234567",
                "fact_ids": [],
            },
            {
                "operator": "click",
                "target_tag": "submit-button",
                "value": None,
                "fact_ids": [],
            },
        ]
        visual["interaction_trace"] = [
            {
                "source_page_key": visual["page_key"],
                "case_id": case["case_id"],
                "interaction_id": edge["from_interaction_id"],
                "outcome": edge["outcome"],
            }
        ]

        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        frozen_visual = next(
            item
            for item in frozen["visual_capture_cases"]
            if item["design_name"] == visual["design_name"]
        )
        self.assertEqual(
            frozen_visual["interaction_trace"][0]["actions"],
            case["runtime_test"]["actions"],
        )

    def test_visual_precondition_may_not_start_or_install_another_android_surface(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        for device_command in (
            ["adb", "shell", "am", "start", "-n", "overlay.app/.Overlay"],
            ["/opt/android-sdk/platform-tools/adb", "install", "overlay.apk"],
        ):
            with self.subTest(device_command=device_command):
                plan = self.valid_plan()
                plan["visual_capture_cases"][0]["precondition_commands"] = [
                    device_command
                ]

                rejected = self.record_plan(plan)

                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("visual_production_path_unproven", rejected.stderr)

    def test_visual_state_must_target_the_frozen_production_renderer(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        visual = plan["visual_capture_cases"][0]
        visual["production_render"]["symbol"] = "IcpDebugOnlyDialog"

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("visual_render_identity_mismatch", rejected.stderr)

    def test_verify_derives_fidelity_from_measurements_instead_of_human_booleans(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _, evidence = self.prepare_verifiable_implementation(plan)
        visual = evidence["visual_runs"][0]
        visual.pop("reference_fidelity", None)
        capture_path = self.project / visual["capture_evidence"]
        capture = read_json(capture_path)
        capture["measurements"]["measurements"][0]["actual"] = {
            "left": 999,
            "top": 999,
            "width": 999,
            "height": 999,
        }
        capture_path.write_text(
            json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("reference_viewport_measurement_failed", rejected.stderr)

    def test_verify_recomputes_reference_layout_from_measured_runtime_geometry(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _, evidence = self.prepare_verifiable_implementation(plan)
        visual = evidence["visual_runs"][0]
        capture_path = self.project / visual["capture_evidence"]
        capture = read_json(capture_path)
        root = next(
            item
            for item in capture["layout"]["components"]
            if item["parent_instance_id"] is None
        )
        root["bounds"]["width"] += 1
        write_json(capture_path, capture)

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("reference_viewport_layout_failed", rejected.stderr)

    def test_source_changes_after_runtime_capture_require_fresh_runtime_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _, evidence = self.prepare_verifiable_implementation(plan)
        probed = next(
            mapping
            for mapping in plan["design_element_mappings"]
            if mapping["runtime_probe_tag"] is not None
        )
        source_path = self.project / probed["source_file"]
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace(
                "// " + probed["runtime_probe_tag"] + "\n", ""
            ),
            encoding="utf-8",
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("runtime_evidence_not_captured", rejected.stderr)

    def test_verify_rejects_a_debug_duplicate_of_the_production_renderer(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _, evidence = self.prepare_verifiable_implementation(plan)
        visual = plan["visual_capture_cases"][0]
        duplicate = self.project / "app/src/debug/java/demo/IcpDebugDialog.kt"
        duplicate.parent.mkdir(parents=True, exist_ok=True)
        duplicate.write_text(
            "fun IcpDebugDialog() = Unit\n// "
            + visual["production_render"]["root_tag"]
            + "\n",
            encoding="utf-8",
        )

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("visual_render_identity_mismatch", rejected.stderr)

    def test_exported_design_assets_require_one_exact_source_to_target_mapping(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        mapped = next(
            item for item in plan["design_element_mappings"] if item["asset_mappings"]
        )
        asset_mapping = mapped["asset_mappings"].pop()

        rejected = self.record_plan(plan)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("asset_consumption_missing", rejected.stderr)

        mapped["asset_mappings"].append(asset_mapping)
        recorded = self.record_plan(plan)

        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

    def test_each_interaction_case_must_observe_red_then_green_with_the_same_command(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        behavior_path = self.project / "app_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("app_behavior")
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"interaction_case_{index}.py"
            test_path.write_text(
                "from app_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        premature = self.run_case(plan["integration_test_cases"][0]["case_id"], "green")
        self.assertNotEqual(premature.returncode, 0)
        self.assertIn("red_required", premature.stderr)

        for case in plan["integration_test_cases"]:
            red = self.run_case(case["case_id"], "red")
            self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        state = read_json(self.stage_dir / "state.json")
        self.assertEqual(state["state"], "awaiting_implementation")

        behavior_path.write_text("IMPLEMENTED = True\n", encoding="utf-8")
        for case in plan["integration_test_cases"]:
            green = self.run_case(case["case_id"], "green")
            self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        state = read_json(self.stage_dir / "state.json")
        self.assertEqual(state["state"], "awaiting_verification")
        evidence = read_json(self.stage_dir / "tdd-evidence.json")
        self.assertEqual(
            {item["case_id"] for item in evidence["cases"]},
            {item["case_id"] for item in plan["integration_test_cases"]},
        )
        self.assertTrue(all(item["red"]["exit_code"] != 0 for item in evidence["cases"]))
        self.assertTrue(all(item["green"]["exit_code"] == 0 for item in evidence["cases"]))

    def test_one_page_can_complete_red_green_before_another_page_starts_red(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        page_keys = list(
            dict.fromkeys(case["page_key"] for case in plan["integration_test_cases"])
        )
        self.assertGreaterEqual(len(page_keys), 2)
        first_page = page_keys[0]
        second_page = page_keys[1]
        behavior_path = self.project / "page_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("page_behavior")
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"page_case_{index}.py"
            test_path.write_text(
                "from page_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        first_page_cases = [
            case for case in plan["integration_test_cases"] if case["page_key"] == first_page
        ]
        for case in first_page_cases:
            red = self.run_case(case["case_id"], "red")
            self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        behavior_path.write_text("IMPLEMENTED = True\n", encoding="utf-8")
        for case in first_page_cases:
            green = self.run_case(case["case_id"], "green")
            self.assertEqual(green.returncode, 0, green.stdout + green.stderr)

        evidence = read_json(self.stage_dir / "tdd-evidence.json")
        by_id = {case["case_id"]: case for case in evidence["cases"]}
        self.assertTrue(
            all(by_id[case["case_id"]]["green"] is not None for case in first_page_cases)
        )
        self.assertTrue(
            all(
                case["red"] is None
                for case in evidence["cases"]
                if case["page_key"] == second_page
            )
        )

    def test_one_vertical_case_can_green_before_its_page_sibling_starts_red(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        page_key = plan["integration_test_cases"][0]["page_key"]
        siblings = [
            case for case in plan["integration_test_cases"] if case["page_key"] == page_key
        ]
        self.assertGreaterEqual(len(siblings), 2)
        behavior_path = self.project / "vertical_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("vertical_behavior")
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"vertical_case_{index}.py"
            test_path.write_text(
                "from vertical_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)

        red = self.run_case(siblings[0]["case_id"], "red")
        self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        behavior_path.write_text("IMPLEMENTED = True\n", encoding="utf-8")
        green = self.run_case(siblings[0]["case_id"], "green")

        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        evidence = read_json(self.stage_dir / "tdd-evidence.json")
        by_id = {case["case_id"]: case for case in evidence["cases"]}
        self.assertIsNone(by_id[siblings[1]["case_id"]]["red"])

    def test_parallel_case_recording_preserves_both_green_results(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        behavior_path = self.project / "parallel_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("parallel_behavior", delay=True)
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"parallel_case_{index}.py"
            test_path.write_text(
                "import time\n"
                "from parallel_behavior import IMPLEMENTED\n"
                "time.sleep(0.3)\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        for case in plan["integration_test_cases"]:
            red = self.run_case(case["case_id"], "red")
            self.assertEqual(red.returncode, 0, red.stdout + red.stderr)

        behavior_path.write_text("IMPLEMENTED = True\n", encoding="utf-8")
        selected = plan["integration_test_cases"][:2]
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run-case",
                    "--project-root",
                    str(self.project),
                    "--case-id",
                    case["case_id"],
                    "--phase",
                    "green",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for case in selected
        ]
        completed = [process.communicate(timeout=30) for process in processes]
        self.assertTrue(
            all(process.returncode == 0 for process in processes),
            "\n".join(stdout + stderr for stdout, stderr in completed),
        )
        evidence = read_json(self.stage_dir / "tdd-evidence.json")
        cases_by_id = {item["case_id"]: item for item in evidence["cases"]}
        self.assertTrue(
            all(cases_by_id[case["case_id"]]["green"] is not None for case in selected)
        )

    def test_capture_visual_converts_reference_geometry_and_restores_device_even_on_failure(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        reference = universe["visual_references"][0]
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        driver_state = self.project / "fake-driver-state.json"
        driver_state.write_text(json.dumps(initial), encoding="utf-8")
        fail_marker = self.project / "fail-capture"
        fail_marker.write_text("fail\n", encoding="utf-8")
        reference_path = self.project / reference["path"]
        capture_case = next(
            item
            for item in plan["visual_capture_cases"]
            if item["design_name"] == reference["design_name"]
        )
        layout_path = self.project / "fake-reference-layout.json"
        write_json(
            layout_path,
            self.reference_layout_snapshot(
                plan,
                reference["design_name"],
                capture_case["visual_state_id"],
                capture_case["production_render"]["root_tag"],
            ),
        )
        driver = self.project / "fake-visual-driver.py"
        driver.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, hashlib, json, shutil\n"
            "from pathlib import Path\n"
            f"state_path = Path({str(driver_state)!r})\n"
            f"reference_path = Path({str(reference_path)!r})\n"
            f"layout_path = Path({str(layout_path)!r})\n"
            f"fail_marker = Path({str(fail_marker)!r})\n"
            "p=argparse.ArgumentParser(); p.add_argument('operation'); "
            "p.add_argument('--package'); p.add_argument('--config'); p.add_argument('--output'); "
            "p.add_argument('--trace'); p.add_argument('--contract'); p.add_argument('--state-id'); "
            "p.add_argument('--root-tag'); p.add_argument('--apk'); a=p.parse_args()\n"
            "if a.operation == 'snapshot': print(state_path.read_text())\n"
            f"elif a.operation == 'reset-package': print(json.dumps({self.clean_package_reset()!r}))\n"
            f"elif a.operation == 'package-identity': print(json.dumps({self.installed_package_identity()!r}))\n"
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n"
            "elif a.operation in {'cold-start','health'}: print(json.dumps({"
            "'activity_resumed': True, 'process_alive': True, "
            "'no_fatal_exception': True, 'fatal_log_tail': ''}))\n"
            "elif a.operation == 'interact':\n"
            "    trace=json.loads(Path(a.trace).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-interaction.v1','steps':trace['steps'],'initial_state_absent':bool(trace['steps']),'terminal_state_present':True}))\n"
            "elif a.operation == 'attest': print(json.dumps({"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'state_attested':True,"
            "'root_attested':True}))\n"
            "elif a.operation == 'read-layout': print(layout_path.read_text())\n"
            "elif a.operation == 'measure':\n"
            "    contract=json.loads(Path(a.contract).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-measurements.v1',"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'measurements':["
            "{'assertion_id':item['assertion_id'],'probe_tag':item['probe_tag'],"
            "'kind':item['kind'],'actual':item['expected'],**({'source':'clean_build_apk',"
            "'apk_sha256':hashlib.sha256(Path(a.apk).read_bytes()).hexdigest()} if item['kind'] in {'font_size','line_height'} else {})} "
            "for item in contract['assertions']]}))\n"
            "elif a.operation == 'capture':\n"
            "    if fail_marker.exists(): raise SystemExit(7)\n"
            "    shutil.copyfile(reference_path, a.output)\n",
            encoding="utf-8",
        )
        driver.chmod(0o755)

        failed = self.capture_visual_with_test_driver(reference["design_name"], driver)

        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("visual_capture_failed", failed.stderr)
        self.assertEqual(json.loads(driver_state.read_text()), initial)

        fail_marker.unlink()
        captured = self.capture_visual_with_test_driver(reference["design_name"], driver)

        self.assertEqual(captured.returncode, 0, captured.stdout + captured.stderr)
        result = json.loads(captured.stdout)
        capture_evidence = read_json(self.project / result["capture_evidence"])
        self.assertEqual(capture_evidence["before"], initial)
        self.assertEqual(capture_evidence["restored"], initial)
        self.assertTrue(capture_evidence["cold_start"]["process_alive"])
        self.assertEqual(
            capture_evidence["layout"]["components"],
            read_json(layout_path)["components"],
        )
        self.assertEqual(
            capture_evidence["visual_state_id"], reference["visual_state_id"]
        )
        self.assertEqual(
            capture_evidence["applied"]["size"],
            reference["pixel_size"],
        )
        self.assertEqual(
            capture_evidence["applied"]["density"],
            round(160 * float(reference["logical_scale"])),
        )
        self.assertEqual(
            hashlib.sha256((self.project / result["actual_screenshot"]).read_bytes()).hexdigest(),
            reference["sha256"],
        )

    def test_visual_capture_preserves_the_original_failure_when_restore_also_fails(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        failing = self.project / "fail-precondition.py"
        failing.write_text("raise SystemExit(7)\n", encoding="utf-8")
        plan["visual_capture_cases"][0]["precondition_commands"] = [
            [sys.executable, failing.name]
        ]
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        current = copy.deepcopy(initial)

        def completed(code: int = 0, stdout: str = "", stderr: str = ""):
            return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)

        def fake_driver(_driver: str, operation: str, _package: str, **paths: Path):
            nonlocal current
            if operation == "reset-package":
                return completed(stdout=json.dumps(self.clean_package_reset()))
            if operation == "package-identity":
                return completed(stdout=json.dumps(self.installed_package_identity()))
            if operation == "snapshot":
                return completed(stdout=json.dumps(current))
            if operation == "apply":
                current = read_json(paths["config"])
                return completed()
            if operation == "restore":
                return completed(code=9, stderr="restore failed")
            raise AssertionError(operation)

        with patch.object(IMPLEMENTATION, "run_driver", side_effect=fake_driver):
            with self.assertRaisesRegex(
                IMPLEMENTATION.ContractError, "visual state setup failed"
            ) as failure:
                IMPLEMENTATION.capture_visual(
                    argparse.Namespace(
                        project_root=str(self.project),
                        design_name=plan["visual_capture_cases"][0]["design_name"],
                        driver=str(IMPLEMENTATION.ANDROID_VISUAL_DRIVER),
                    )
                )

        self.assertEqual(failure.exception.code, "visual_capture_failed")

    def test_visual_capture_rechecks_device_configuration_after_preconditions(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        state_path = self.project / "device-state.json"
        state_path.write_text(json.dumps(initial), encoding="utf-8")
        reset_script = self.project / "reset-device-config.py"
        reset_script.write_text(
            "from pathlib import Path\n"
            f"Path({str(state_path)!r}).write_text({json.dumps(json.dumps(initial))})\n",
            encoding="utf-8",
        )
        plan = self.valid_plan()
        visual = plan["visual_capture_cases"][0]
        visual["precondition_commands"] = [[sys.executable, reset_script.name]]
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)

        def completed(code: int = 0, stdout: str = "", stderr: str = ""):
            return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)

        def fake_driver(_driver: str, operation: str, _package: str, **paths: Path):
            if operation == "reset-package":
                return completed(stdout=json.dumps(self.clean_package_reset()))
            if operation == "package-identity":
                return completed(stdout=json.dumps(self.installed_package_identity()))
            if operation == "snapshot":
                return completed(stdout=state_path.read_text(encoding="utf-8"))
            if operation in {"apply", "restore"}:
                state_path.write_text(
                    (paths["config"]).read_text(encoding="utf-8"), encoding="utf-8"
                )
                return completed()
            raise AssertionError(operation)

        with patch.object(IMPLEMENTATION, "run_driver", side_effect=fake_driver):
            with self.assertRaises(IMPLEMENTATION.ContractError) as failure:
                IMPLEMENTATION.capture_visual(
                    argparse.Namespace(
                        project_root=str(self.project),
                        design_name=visual["design_name"],
                        driver=str(IMPLEMENTATION.ANDROID_VISUAL_DRIVER),
                    )
                )

        self.assertEqual(failure.exception.code, "visual_configuration_mismatch")
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), initial)

    def test_visual_retry_rejects_device_drift_from_the_first_frozen_baseline(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        baseline_path = self.stage_dir / "runtime" / "retry.before.json"
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        drifted = {
            **initial,
            "size": {"width": 360, "height": 800},
            "size_override": True,
            "density": 160,
            "density_override": True,
        }
        state = read_json(self.stage_dir / "state.json")

        first = IMPLEMENTATION.frozen_device_baseline(
            self.stage_dir, state, "visual:retry", baseline_path, initial
        )
        self.assertEqual(first, initial)
        with self.assertRaisesRegex(
            IMPLEMENTATION.ContractError, "device configuration drifted"
        ):
            IMPLEMENTATION.frozen_device_baseline(
                self.stage_dir, state, "visual:retry", baseline_path, drifted
            )

    def test_capture_visual_uses_the_production_path_and_measures_frozen_source_facts(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        universe = read_json(self.stage_dir / "coverage-universe.json")
        visual = plan["visual_capture_cases"][0]
        graph = next(
            graph
            for graph in universe["interaction_graphs"]
            if graph["page_key"] == visual["page_key"]
        )
        continuation = next(
            edge for edge in graph["edges"] if edge["target"]["kind"] == "interaction"
        )
        page_case = case_for_interaction(
            universe,
            plan,
            visual["page_key"],
            continuation["from_interaction_id"],
        )
        page_case["runtime_test"]["actions"] = [
            {
                "operator": "click",
                "target_tag": "feedback-photo-source-trigger",
                "value": None,
                "fact_ids": [],
            }
        ]
        visual["interaction_trace"] = [
            {
                "source_page_key": visual["page_key"],
                "case_id": page_case["case_id"],
                "interaction_id": continuation["from_interaction_id"],
                "outcome": continuation["outcome"],
                "action": "click",
                "target_tag": "feedback-photo-source-trigger",
            }
        ]
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        visual = next(
            item
            for item in plan["visual_capture_cases"]
            if item["design_name"] == visual["design_name"]
        )
        universe = read_json(self.stage_dir / "coverage-universe.json")
        reference = next(
            item
            for item in universe["visual_references"]
            if item["design_name"] == visual["design_name"]
        )
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        driver_state = self.project / "production-driver-state.json"
        driver_state.write_text(json.dumps(initial), encoding="utf-8")
        operation_log = self.project / "production-driver-operations.jsonl"
        reference_path = self.project / reference["path"]
        layout_path = self.project / "production-reference-layout.json"
        write_json(
            layout_path,
            self.reference_layout_snapshot(
                plan,
                visual["design_name"],
                visual["visual_state_id"],
                visual["production_render"]["root_tag"],
            ),
        )
        driver = self.project / "production-visual-driver.py"
        driver.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, hashlib, json, shutil, sys\n"
            "from pathlib import Path\n"
            f"state_path = Path({str(driver_state)!r})\n"
            f"log_path = Path({str(operation_log)!r})\n"
            f"reference_path = Path({str(reference_path)!r})\n"
            f"layout_path = Path({str(layout_path)!r})\n"
            "p=argparse.ArgumentParser(); p.add_argument('operation'); "
            "p.add_argument('--package'); p.add_argument('--config'); p.add_argument('--output'); "
            "p.add_argument('--trace'); p.add_argument('--contract'); p.add_argument('--state-id'); "
            "p.add_argument('--root-tag'); p.add_argument('--apk'); a=p.parse_args()\n"
            "with log_path.open('a') as f: f.write(json.dumps(vars(a), sort_keys=True)+'\\n')\n"
            "if a.operation == 'snapshot': print(state_path.read_text())\n"
            f"elif a.operation == 'reset-package': print(json.dumps({self.clean_package_reset()!r}))\n"
            f"elif a.operation == 'package-identity': print(json.dumps({self.installed_package_identity()!r}))\n"
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n"
            "elif a.operation in {'cold-start','health'}:\n"
            "    if a.operation == 'cold-start' and a.state_id is not None: raise SystemExit(12)\n"
            "    print(json.dumps({'activity_resumed': True, 'process_alive': True, "
            "'no_fatal_exception': True, 'fatal_log_tail': ''}))\n"
            "elif a.operation == 'interact':\n"
            "    trace=json.loads(Path(a.trace).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-interaction.v1','steps':trace['steps'],'initial_state_absent':bool(trace['steps']),'terminal_state_present':True}))\n"
            "elif a.operation == 'attest': print(json.dumps({"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'state_attested':True,"
            "'root_attested':True}))\n"
            "elif a.operation == 'read-layout': print(layout_path.read_text())\n"
            "elif a.operation == 'measure':\n"
            "    contract=json.loads(Path(a.contract).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-measurements.v1',"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'measurements':["
            "{'assertion_id':item['assertion_id'],'probe_tag':item['probe_tag'],"
            "'kind':item['kind'],'actual':item['expected'],**({'source':'clean_build_apk',"
            "'apk_sha256':hashlib.sha256(Path(a.apk).read_bytes()).hexdigest()} if item['kind'] in {'font_size','line_height'} else {})} "
            "for item in contract['assertions']]}))\n"
            "elif a.operation == 'capture': shutil.copyfile(reference_path, a.output)\n",
            encoding="utf-8",
        )
        driver.chmod(0o755)

        captured = self.capture_visual_with_test_driver(visual["design_name"], driver)

        self.assertEqual(captured.returncode, 0, captured.stdout + captured.stderr)
        result = json.loads(captured.stdout)
        capture = read_json(self.project / result["capture_evidence"])
        operations = [json.loads(line) for line in operation_log.read_text().splitlines()]
        self.assertEqual(
            [item["operation"] for item in operations],
            [
                "reset-package",
                "package-identity",
                "snapshot",
                "apply",
                "snapshot",
                "snapshot",
                "package-identity",
                "cold-start",
                "interact",
                "health",
                "attest",
                "measure",
                "capture",
                "read-layout",
                "restore",
                "snapshot",
            ],
        )
        cold_start = next(item for item in operations if item["operation"] == "cold-start")
        self.assertIsNone(cold_start["state_id"])
        self.assertEqual(capture["schema"], "icp.implementation.visual-capture-evidence.v3")
        self.assertEqual(capture["layout"]["components"], read_json(layout_path)["components"])
        self.assertEqual(capture["production_state"]["root_tag"], visual["production_render"]["root_tag"])
        self.assertEqual(capture["interaction"]["steps"], visual["interaction_trace"])
        expected_assertions = [
            item
            for item in universe["reference_viewport_assertions"]
            if item["design_name"] == visual["design_name"]
        ]
        self.assertEqual(
            {item["assertion_id"] for item in capture["measurements"]["measurements"]},
            {item["assertion_id"] for item in expected_assertions},
        )

    def test_capture_visual_rejects_a_cold_start_that_does_not_keep_the_app_alive(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        driver_state = self.project / "cold-start-driver-state.json"
        driver_state.write_text(json.dumps(initial), encoding="utf-8")
        capture_marker = self.project / "capture-was-called"
        driver = self.project / "cold-start-visual-driver.py"
        driver.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, json\n"
            "from pathlib import Path\n"
            f"state_path = Path({str(driver_state)!r})\n"
            f"capture_marker = Path({str(capture_marker)!r})\n"
            "p=argparse.ArgumentParser(); p.add_argument('operation'); "
            "p.add_argument('--package'); p.add_argument('--config'); p.add_argument('--output'); "
            "p.add_argument('--state-id'); a=p.parse_args()\n"
            "if a.operation == 'snapshot': print(state_path.read_text())\n"
            f"elif a.operation == 'reset-package': print(json.dumps({self.clean_package_reset()!r}))\n"
            f"elif a.operation == 'package-identity': print(json.dumps({self.installed_package_identity()!r}))\n"
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n"
            "elif a.operation in {'cold-start','health'}: print(json.dumps({"
            "'activity_resumed': False, 'process_alive': False, "
            "'no_fatal_exception': False, 'fatal_log_tail': 'AndroidRuntime crash'}))\n"
            "elif a.operation == 'capture': capture_marker.write_text('called')\n",
            encoding="utf-8",
        )
        driver.chmod(0o755)

        rejected = self.capture_visual_with_test_driver(
            plan["visual_capture_cases"][0]["design_name"], driver
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("android_cold_start_failed", rejected.stderr)
        self.assertFalse(capture_marker.exists())
        self.assertEqual(json.loads(driver_state.read_text()), initial)

    def test_capture_visual_rejects_a_precondition_that_replaces_the_tested_apk(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        replaced_marker = self.project / "production-apk-was-replaced"
        replace_script = self.project / "replace-production-apk.py"
        replace_script.write_text(
            "from pathlib import Path\n"
            f"Path({str(replaced_marker)!r}).write_text('replaced')\n",
            encoding="utf-8",
        )
        plan["visual_capture_cases"][0]["precondition_commands"] = [
            [sys.executable, replace_script.name]
        ]
        self.prepare_verifiable_implementation(plan, record_runtime_capture=False)
        initial = {
            "size": {"width": 1080, "height": 1920},
            "size_override": False,
            "density": 420,
            "density_override": False,
            "locale": "en-US",
            "font_scale": "1.0",
            "navigation_mode": "2",
        }
        driver_state = self.project / "identity-driver-state.json"
        driver_state.write_text(json.dumps(initial), encoding="utf-8")
        original_identity = self.installed_package_identity()
        replacement_apks = copy.deepcopy(original_identity["apks"])
        replacement_apks[0]["sha256"] = hashlib.sha256(
            b"replacement-production-apk"
        ).hexdigest()
        replacement_identity = {
            "package_name": "test.app",
            "apks": replacement_apks,
            "sha256": IMPLEMENTATION.digest(replacement_apks),
        }
        driver = self.project / "identity-visual-driver.py"
        driver.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, json\n"
            "from pathlib import Path\n"
            f"state_path = Path({str(driver_state)!r})\n"
            f"replaced_marker = Path({str(replaced_marker)!r})\n"
            f"original = {original_identity!r}\n"
            f"replacement = {replacement_identity!r}\n"
            "p=argparse.ArgumentParser(); p.add_argument('operation'); "
            "p.add_argument('--package'); p.add_argument('--config'); p.add_argument('--output'); "
            "a=p.parse_args()\n"
            "if a.operation == 'snapshot': print(state_path.read_text())\n"
            f"elif a.operation == 'reset-package': print(json.dumps({self.clean_package_reset()!r}))\n"
            "elif a.operation == 'package-identity': print(json.dumps(replacement if replaced_marker.exists() else original))\n"
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n",
            encoding="utf-8",
        )
        driver.chmod(0o755)

        rejected = self.capture_visual_with_test_driver(
            plan["visual_capture_cases"][0]["design_name"], driver
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("android_runtime_identity_changed", rejected.stderr)
        self.assertEqual(json.loads(driver_state.read_text()), initial)

    def test_verify_requires_code_anchors_commands_two_viewports_and_visual_mae(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        behavior_path = self.project / "app_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        self.write_fake_gradle("app_behavior")
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"interaction_case_{index}.py"
            test_path.write_text(
                "from app_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
        verify_command = self.project / "verify_command.py"
        verify_command.write_text("raise SystemExit(0)\n", encoding="utf-8")
        command = [sys.executable, verify_command.name]
        plan["verification_commands"] = {
            "lint": [command],
            "build": [command],
            "integration": [command],
        }
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = read_json(self.stage_dir / "implementation-plan.json")
        for case in plan["integration_test_cases"]:
            red = self.run_case(case["case_id"], "red")
            self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        behavior_path.write_text("IMPLEMENTED = True\n", encoding="utf-8")
        for case in plan["integration_test_cases"]:
            green = self.run_case(case["case_id"], "green")
            self.assertEqual(green.returncode, 0, green.stdout + green.stderr)

        file_lines: dict[str, list[str]] = {}
        for page in plan["pages"]:
            file_lines.setdefault(page["source_file"], []).append(f"fun {page['root_symbol']}() = Unit")
            file_lines.setdefault(page["dto_file"], []).extend(
                [
                    f"data class {page['dto_symbol']}(val value: String)",
                    f"data class {page['ui_state_symbol']}(val value: String)",
                ]
            )
            file_lines.setdefault(page["api_adapter_file"], []).append(
                f"class {page['api_adapter_symbol']}"
            )
            mock = self.project / page["mock_fixture_path"]
            mock.parent.mkdir(parents=True, exist_ok=True)
            mock_body = next(
                case["runtime_test"]["mock_expectation"]["body"]
                for case in plan["integration_test_cases"]
                if case["page_key"] == page["page_key"]
                and case["runtime_test"]["mock_expectation"] is not None
            )
            mock.write_text(
                json.dumps(mock_body, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        for mapping in plan["component_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).append(f"fun {mapping['symbol']}() = Unit")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        graph_interaction_by_key = {
            (graph["page_key"], interaction["interaction_id"]): interaction
            for graph in universe["interaction_graphs"]
            for interaction in graph["interactions"]
        }
        api_mapping_by_key = {
            (mapping["page_key"], mapping["api_contract_id"]): mapping
            for mapping in plan["api_contract_mappings"]
        }
        for mapping in plan["interaction_mappings"]:
            interaction = graph_interaction_by_key[
                (mapping["page_key"], mapping["interaction_id"])
            ]
            behavior = interaction.get("behavior")
            call_lines = []
            if behavior is not None and behavior["kind"] == "api_call":
                call_lines = [
                    ""
                    + api_mapping_by_key[
                        (mapping["page_key"], behavior["api_contract_id"])
                    ]["method_symbol"]
                    + "()"
                ]
            file_lines.setdefault(mapping["source_file"], []).extend(
                [
                    f"fun {mapping['symbol']}() = Unit",
                    "// " + mapping["implementation_anchor"],
                    *call_lines,
                ]
            )
        for mapping in plan["api_contract_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).extend(
                [
                    f"fun {mapping['method_symbol']}() = Unit",
                    "// " + mapping["implementation_anchor"],
                ]
            )
        for mapping in plan["design_element_mappings"]:
            typography_resources = {
                assertion["kind"]: assertion["apk_resource_name"]
                for assertion in universe["reference_viewport_assertions"]
                if assertion["obligation_id"] == mapping["obligation_id"]
                and assertion["kind"] in {"font_size", "line_height"}
            }
            element = next(
                item
                for item in universe["design_elements"]
                if item["obligation_id"] == mapping["obligation_id"]
            )
            element_binding = []
            asset_resource_refs = [
                IMPLEMENTATION.android_resource_reference(
                    item["target_resource_path"]
                )
                for item in mapping["asset_mappings"]
            ]
            self.assertNotIn(None, asset_resource_refs)
            element_binding = [
                    "IcpBoundElement("
                    + f'obligationId = {json.dumps(mapping["obligation_id"])}, '
                    + f'componentInstanceId = {json.dumps(element["component_instance_id"])}, '
                    + f'ownerSymbol = {json.dumps(mapping["symbol"])}, '
                    + "probeTag = "
                    + (
                        json.dumps(mapping["runtime_probe_tag"])
                        if mapping["runtime_probe_tag"] is not None
                        else "null"
                    )
                    + ", "
                    + "fontSizeRes = "
                    + (
                        "R.dimen." + typography_resources["font_size"]
                        if "font_size" in typography_resources
                        else "null"
                    )
                    + ", lineHeightRes = "
                    + (
                        "R.dimen." + typography_resources["line_height"]
                        if "line_height" in typography_resources
                        else "null"
                    )
                    + ", assetRefs = "
                    + (
                        "listOf(" + ", ".join(asset_resource_refs) + ")"
                        if asset_resource_refs
                        else "emptyList()"
                    )
                    + ")"
                ]
            file_lines.setdefault(mapping["source_file"], []).extend(
                [
                    "// " + mapping["implementation_anchor"],
                    *[
                        "val typography = R.dimen." + name
                        for name in typography_resources.values()
                    ],
                    *element_binding,
                    *(
                        ["// " + mapping["runtime_probe_tag"]]
                        if mapping["runtime_probe_tag"] is not None
                        else []
                    ),
                ]
            )
        for mapping in plan["semantic_fact_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).append("// " + mapping["implementation_anchor"])
        for mapping in plan["presentation_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).extend(
                [f"fun {mapping['symbol']}() = Unit", "// " + mapping["implementation_anchor"]]
            )
        for visual in plan["visual_capture_cases"]:
            file_lines.setdefault(visual["production_render"]["source_file"], []).append(
                "// " + visual["production_render"]["root_tag"]
            )
        provider = plan["runtime_probe_provider"]
        file_lines.setdefault(provider["source_file"], []).extend(
            [
                f"object {provider['symbol']}",
                f"fun {provider['publish_method_symbol']}() = Unit",
                f'const val outputPath = "{provider["output_path"]}"',
            ]
        )
        for page in plan["pages"]:
            file_lines.setdefault(page["source_file"], []).append(
                provider["publish_method_symbol"] + "()"
            )
        missing_anchor = plan["design_element_mappings"][-1]["implementation_anchor"]
        for relative, lines in file_lines.items():
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(line for line in lines if missing_anchor not in line) + "\n",
                encoding="utf-8",
            )
        frozen_plan = read_json(self.stage_dir / "implementation-plan.json")
        runtime_installations = {
            page_key: IMPLEMENTATION.attest_android_runtime_installation(
                self.project.resolve(), frozen_plan, page_key, device_serial=None
            )
            for page_key in universe["page_keys"]
        }
        responsive_runs = []
        for page_key in universe["page_keys"]:
            contracts = [
                item
                for item in frozen_plan["layout_contracts"]
                if item["page_key"] == page_key
            ]
            reference = next(
                item
                for item in universe["visual_references"]
                if item["page_key"] == page_key
            )
            for viewport, width, height in (
                ("compact", 360, 800),
                ("expanded", 840, 1200),
            ):
                snapshots = []
                for contract in contracts:
                    components = []
                    for instance_id, node in contract["component_tree"]["nodes_by_instance_id"].items():
                        bounds = copy.deepcopy(
                            contract["component_geometry_by_instance_id"][instance_id][
                                "artboard_envelope"
                            ]
                        )
                        if instance_id == contract["root_instance_id"]:
                            bounds = {"left": 0, "top": 0, "width": width, "height": height}
                        components.append(
                            {
                                "instance_id": instance_id,
                                "occurrence_id": instance_id,
                                "presence": "present",
                                "parent_instance_id": node["parent_instance_id"],
                                "slot": node["slot"],
                                "order": node["order"],
                                "bounds": bounds,
                            }
                        )
                    snapshots.append(
                        {
                            "design_state_id": contract["design_state_id"],
                            "coordinate_space": {"unit": "dp", "origin": "viewport"},
                            "viewport_bounds": {"left": 0, "top": 0, "width": width, "height": height},
                            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
                            "system_bars": {
                                "status": {"visible": False, "bounds": None},
                                "navigation": {"visible": False, "bounds": None},
                            },
                            "scroll_metrics": [],
                            "driver_observations": {
                                "observed_instance_ids": [
                                    item["occurrence_id"] for item in components
                                ],
                                "scroll_actions": [],
                                "scroll_results": [
                                    {
                                        "decision_id": assertion[
                                            "decision_id"
                                        ],
                                        "container_instance_id": assertion[
                                            "container_instance_id"
                                        ],
                                        "axis": assertion["axis"],
                                        "end_reached": True,
                                        "restored_to_start": True,
                                        "observed_instance_ids": list(
                                            contract["component_tree"][
                                                "nodes_by_instance_id"
                                            ]
                                        ),
                                    }
                                    for assertion in contract[
                                        "responsive_assertions"
                                    ]
                                    if assertion["kind"]
                                    == "scroll_reachability"
                                ],
                            },
                            "components": components,
                            "capture": {
                                "screenshot_path": reference["path"],
                                "sha256": reference["sha256"],
                                "device_configuration": {
                                    "width": width,
                                    "height": height,
                                    "density": 320,
                                    "locale": "ru-RU",
                                    "font_scale": "1.0",
                                    "navigation_mode": "gesture",
                                },
                            },
                        }
                    )
                responsive_run = {
                    "page_key": page_key,
                    "viewport": viewport,
                    "package_reset": self.clean_package_reset(),
                    "runtime_installation": runtime_installations[page_key],
                    "package_identity": self.installed_package_identity(),
                    "snapshots": snapshots,
                }
                responsive_path = (
                    self.stage_dir
                    / "runtime"
                    / "responsive"
                    / f"{page_key}-{viewport}.capture.json"
                )
                responsive_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(responsive_path, responsive_run)
                responsive_runs.append(
                    {
                        "page_key": page_key,
                        "viewport": viewport,
                        "capture_evidence": str(
                            responsive_path.relative_to(self.project)
                        ),
                    }
                )
        evidence = {
            "schema": "icp.implementation.runtime-evidence.v1",
            "implementation_plan_sha256": read_json(self.stage_dir / "state.json")[
                "implementation_plan_sha256"
            ],
            "responsive_runs": responsive_runs,
            "visual_runs": [
                {
                    "design_name": item["design_name"],
                    "actual_screenshot": item["path"],
                    "capture_evidence": "missing.capture.json",
                }
                for item in universe["visual_references"]
            ],
        }

        elements_by_obligation = {
            item["obligation_id"]: item for item in universe["design_elements"]
        }
        for mapping in plan["design_element_mappings"]:
            source_assets = {
                item["asset_id"]: item
                for item in elements_by_obligation[mapping["obligation_id"]]["assets"]
            }
            for asset_mapping in mapping["asset_mappings"]:
                source = self.project / source_assets[
                    asset_mapping["source_asset_id"]
                ]["source_project_path"]
                resource = self.project / asset_mapping["target_resource_path"]
                resource.parent.mkdir(parents=True, exist_ok=True)
                resource.write_bytes(source.read_bytes())

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("code_coverage_missing", rejected.stderr)

        missing_mapping = plan["design_element_mappings"][-1]
        target = self.project / missing_mapping["source_file"]
        target.write_text(
            target.read_text(encoding="utf-8") + "// " + missing_anchor + "\n",
            encoding="utf-8",
        )
        elements_by_obligation = {
            item["obligation_id"]: item for item in universe["design_elements"]
        }
        for mapping in plan["design_element_mappings"]:
            source_assets = {
                item["asset_id"]: item
                for item in elements_by_obligation[mapping["obligation_id"]]["assets"]
            }
            for asset_mapping in mapping["asset_mappings"]:
                source = self.project / source_assets[asset_mapping["source_asset_id"]][
                    "source_project_path"
                ]
                resource = self.project / asset_mapping["target_resource_path"]
                resource.parent.mkdir(parents=True, exist_ok=True)
                resource.write_bytes(source.read_bytes())

        missing_capture = self.verify_implementation(evidence)

        self.assertNotEqual(missing_capture.returncode, 0)
        self.assertIn("visual_capture_evidence_missing", missing_capture.stderr)

        for visual_run in evidence["visual_runs"]:
            reference = next(
                item
                for item in universe["visual_references"]
                if item["design_name"] == visual_run["design_name"]
            )
            config = {
                "size": {"width": 1080, "height": 1920},
                "size_override": False,
                "density": 420,
                "density_override": False,
                "locale": "en-US",
                "font_scale": "1.0",
                "navigation_mode": "2",
            }
            applied = {
                **config,
                "size": reference["pixel_size"],
                "size_override": True,
                "density": round(160 * float(reference["logical_scale"])),
                "density_override": True,
                "locale": "ru-RU",
            }
            capture_path = self.stage_dir / "runtime" / (
                hashlib.sha256(visual_run["design_name"].encode()).hexdigest()[:16]
                + ".capture.json"
            )
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture = {
                "schema": "icp.implementation.visual-capture-evidence.v3",
                "evaluation_scope": "reference_viewport_visual_fidelity",
                "implementation_plan_sha256": evidence["implementation_plan_sha256"],
                "design_name": visual_run["design_name"],
                "reference_sha256": reference["sha256"],
                "logical_artboard_size": reference["logical_artboard_size"],
                "reference_pixel_size": reference["pixel_size"],
                "logical_scale": reference["logical_scale"],
                "capture_strategy": "extended-viewport-full-page",
                "visual_state_id": reference["visual_state_id"],
                "package_reset": self.clean_package_reset(),
                "runtime_installation": runtime_installations[
                    reference["page_key"]
                ],
                "package_identity": self.installed_package_identity(),
                "cold_start": {
                    "activity_resumed": True,
                    "process_alive": True,
                    "no_fatal_exception": True,
                    "fatal_log_tail": "",
                },
                "interaction": {
                    "schema": "icp.visual-interaction.v1",
                    "steps": next(
                        item["interaction_trace"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == visual_run["design_name"]
                    ),
                    "initial_state_absent": bool(next(
                        item["interaction_trace"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == visual_run["design_name"]
                    )),
                    "terminal_state_present": True,
                },
                "production_state": {
                    "visual_state_id": reference["visual_state_id"],
                    "root_tag": next(
                        item["production_render"]["root_tag"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == visual_run["design_name"]
                    ),
                    "state_attested": True,
                    "root_attested": True,
                },
                "measurements": {
                    "schema": "icp.visual-measurements.v1",
                    "visual_state_id": reference["visual_state_id"],
                    "root_tag": next(
                        item["production_render"]["root_tag"]
                        for item in plan["visual_capture_cases"]
                        if item["design_name"] == visual_run["design_name"]
                    ),
                    "measurements": [
                        {
                            "assertion_id": item["assertion_id"],
                            "probe_tag": item["probe_tag"],
                            "kind": item["kind"],
                            "actual": item["expected"],
                            **(
                                {
                                    "source": "clean_build_apk",
                                    "apk_sha256": runtime_installations[
                                        reference["page_key"]
                                    ]["built_apks"][0]["sha256"],
                                }
                                if item["kind"] in {"font_size", "line_height"}
                                else {}
                            ),
                        }
                        for item in universe["reference_viewport_assertions"]
                        if item["design_name"] == visual_run["design_name"]
                    ],
                },
                "layout": {
                    key: value
                    for key, value in self.reference_layout_snapshot(
                        plan,
                        visual_run["design_name"],
                        reference["visual_state_id"],
                        next(
                            item["production_render"]["root_tag"]
                            for item in plan["visual_capture_cases"]
                            if item["design_name"] == visual_run["design_name"]
                        ),
                    ).items()
                    if key not in {"visual_state_id", "root_tag"}
                },
                "before": config,
                "applied": applied,
                "raw_pixel_size": [
                    reference["pixel_size"]["width"],
                    reference["pixel_size"]["height"],
                ],
                "actual_screenshot": visual_run["actual_screenshot"],
                "actual_sha256": reference["sha256"],
                "restored": config,
                "restore_exact": True,
            }
            capture_path.write_text(
                json.dumps(capture, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            visual_run["capture_evidence"] = str(capture_path.relative_to(self.project))

        state = read_json(self.stage_dir / "state.json")
        for page_key in universe["page_keys"]:
            page_manifest = IMPLEMENTATION.verify_code_coverage(
                self.project.resolve(), plan, universe, page_key
            )
            IMPLEMENTATION.implementation_checklist_call(
                self.stage_dir,
                state,
                universe,
                "complete",
                node_id=f"implementation.code-coverage:{page_key}",
                evidence_sha256=IMPLEMENTATION.digest(page_manifest),
            )
        manifest = IMPLEMENTATION.verify_code_coverage(
            self.project.resolve(), plan, universe
        )
        IMPLEMENTATION.implementation_checklist_call(
            self.stage_dir,
            state,
            universe,
            "complete",
            node_id="implementation.code-coverage",
            evidence_sha256=IMPLEMENTATION.digest(manifest),
        )
        for responsive_run in evidence["responsive_runs"]:
            captured_run = read_json(
                self.project / responsive_run["capture_evidence"]
            )
            IMPLEMENTATION.implementation_checklist_call(
                self.stage_dir,
                state,
                universe,
                "complete",
                node_id=(
                    f"responsive:{responsive_run['page_key']}."
                    f"{responsive_run['viewport']}"
                ),
                evidence_sha256=IMPLEMENTATION.digest(captured_run),
            )
        for visual_run in evidence["visual_runs"]:
            capture_path = self.project / visual_run["capture_evidence"]
            IMPLEMENTATION.implementation_checklist_call(
                self.stage_dir,
                state,
                universe,
                "complete",
                node_id=f"visual:{visual_run['design_name']}.capture",
                evidence_sha256=hashlib.sha256(capture_path.read_bytes()).hexdigest(),
            )

        verified = self.verify_implementation(evidence)

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        result = json.loads(verified.stdout)
        self.assertEqual(result["state"], "complete")
        checklist = read_json(self.stage_dir / "checklist.json")
        self.assertTrue(
            all(item["status"] == "completed" for item in checklist["nodes"])
        )
        self.assertEqual(
            read_json(self.stage_dir / "state.json")["checklist_sha256"],
            hashlib.sha256((self.stage_dir / "checklist.json").read_bytes()).hexdigest(),
        )
        stage_result = read_json(self.stage_dir / "stage-result.json")
        self.assertEqual(stage_result["status"], "complete")
        self.assertTrue(all(item["mae"] == 0 for item in stage_result["visual_results"]))

        compiled = subprocess.run(
            [
                sys.executable,
                str(IOLE_SCRIPT),
                "compile-execution-plan",
                "--source-bundle",
                str(
                    self.project
                    / ".icp"
                    / "source"
                    / "source-bundle.json"
                ),
                "--component-lock",
                str(
                    self.project
                    / ".icp"
                    / "component-design"
                    / "component-lock.json"
                ),
                "--implementation-plan",
                str(self.stage_dir / "implementation-plan.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        execution_plan_path = self.project / "flow-execution-plan.json"
        execution_plan_path.write_text(compiled.stdout, encoding="utf-8")

        writeback_command = [
            sys.executable,
            str(IOLE_SCRIPT),
            "build-review-writeback",
            "--plan",
            str(execution_plan_path),
            "--lease-token",
            "lease-current-icp",
            "--mr",
            "0",
            "--icp-result",
            str(self.stage_dir / "stage-result.json"),
        ]
        writeback = subprocess.run(
            writeback_command,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(writeback.returncode, 0, writeback.stdout + writeback.stderr)
        intent = json.loads(writeback.stdout)
        self.assertEqual(intent["connector_operation"], "complete_flow_rows")
        self.assertEqual(
            intent["member_titles"],
            json.loads(compiled.stdout)["claim_page_titles"],
        )

        runtime_path = self.stage_dir / "runtime-evidence.json"
        original_runtime = runtime_path.read_bytes()
        runtime_path.write_bytes(original_runtime + b"\n")
        tampered = subprocess.run(
            writeback_command,
            check=False,
            capture_output=True,
            text=True,
        )
        runtime_path.write_bytes(original_runtime)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn(
            "ICP stage artifact is invalid: runtime-evidence.json",
            tampered.stdout + tampered.stderr,
        )

        state_path = self.stage_dir / "state.json"
        original_state = state_path.read_bytes()
        checklist_path = self.stage_dir / "checklist.json"
        original_checklist = checklist_path.read_bytes()
        incomplete_state = json.loads(original_state)
        incomplete_state["state"] = "awaiting_verification"
        state_path.write_text(json.dumps(incomplete_state), encoding="utf-8")
        incomplete = subprocess.run(
            writeback_command,
            check=False,
            capture_output=True,
            text=True,
        )
        state_path.write_bytes(original_state)
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn(
            "ICP implementation state is incomplete",
            incomplete.stdout + incomplete.stderr,
        )

        stage_result_path = self.stage_dir / "stage-result.json"
        original_result = stage_result_path.read_bytes()
        failed_result = json.loads(original_result)
        failed_result["verification_commands"][0]["exit_code"] = 1
        stage_result_path.write_text(json.dumps(failed_result), encoding="utf-8")
        updated_state = json.loads(original_state)
        updated_state["stage_result_sha256"] = hashlib.sha256(
            stage_result_path.read_bytes()
        ).hexdigest()
        updated_checklist = json.loads(original_checklist)
        final_node = next(
            item for item in updated_checklist["nodes"]
            if item["node_id"] == "stage.verify"
        )
        final_node["evidence_sha256"] = updated_state["stage_result_sha256"]
        checklist_path.write_text(json.dumps(updated_checklist), encoding="utf-8")
        updated_state["checklist_sha256"] = hashlib.sha256(
            checklist_path.read_bytes()
        ).hexdigest()
        state_path.write_text(json.dumps(updated_state), encoding="utf-8")
        failed_commands = subprocess.run(
            writeback_command,
            check=False,
            capture_output=True,
            text=True,
        )
        stage_result_path.write_bytes(original_result)
        state_path.write_bytes(original_state)
        checklist_path.write_bytes(original_checklist)
        self.assertNotEqual(failed_commands.returncode, 0)
        self.assertIn(
            "ICP verification commands are incomplete",
            failed_commands.stdout + failed_commands.stderr,
        )

        failed_visual = json.loads(original_result)
        failed_visual["visual_results"][0]["status"] = "fail"
        stage_result_path.write_text(json.dumps(failed_visual), encoding="utf-8")
        updated_state = json.loads(original_state)
        updated_state["stage_result_sha256"] = hashlib.sha256(
            stage_result_path.read_bytes()
        ).hexdigest()
        updated_checklist = json.loads(original_checklist)
        final_node = next(
            item for item in updated_checklist["nodes"]
            if item["node_id"] == "stage.verify"
        )
        final_node["evidence_sha256"] = updated_state["stage_result_sha256"]
        checklist_path.write_text(json.dumps(updated_checklist), encoding="utf-8")
        updated_state["checklist_sha256"] = hashlib.sha256(
            checklist_path.read_bytes()
        ).hexdigest()
        state_path.write_text(json.dumps(updated_state), encoding="utf-8")
        failed_visual_writeback = subprocess.run(
            writeback_command,
            check=False,
            capture_output=True,
            text=True,
        )
        stage_result_path.write_bytes(original_result)
        state_path.write_bytes(original_state)
        checklist_path.write_bytes(original_checklist)
        self.assertNotEqual(failed_visual_writeback.returncode, 0)
        self.assertIn(
            "ICP visual verification is incomplete",
            failed_visual_writeback.stdout + failed_visual_writeback.stderr,
        )

    def test_verify_crash_before_the_final_checklist_receipt_does_not_publish_complete_state(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _, evidence = self.prepare_verifiable_implementation(plan)
        evidence_path = self.project / "runtime-evidence.json"
        write_json(evidence_path, evidence)
        original_call = IMPLEMENTATION.implementation_checklist_call

        def crash_on_final_receipt(*args, **kwargs):
            if kwargs.get("node_id") == "stage.verify":
                raise IMPLEMENTATION.ContractError(
                    "simulated_crash", "stopped before the final checklist receipt"
                )
            return original_call(*args, **kwargs)

        with patch.object(
            IMPLEMENTATION,
            "implementation_checklist_call",
            side_effect=crash_on_final_receipt,
        ):
            with self.assertRaisesRegex(
                IMPLEMENTATION.ContractError, "final checklist receipt"
            ):
                IMPLEMENTATION.verify_implementation(
                    argparse.Namespace(
                        project_root=str(self.project), evidence=str(evidence_path)
                    )
                )

        self.assertNotEqual(
            read_json(self.stage_dir / "state.json")["state"], "complete"
        )


class EightPageEntryReachabilityCliTest(unittest.TestCase):
    """Entry-rooted reachability over the frozen eight-page topology."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline_temp = tempfile.TemporaryDirectory()
        cls.baseline_root = Path(cls.baseline_temp.name)
        cls.baseline_project = create_eight_page_extract(cls.baseline_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.baseline_temp.cleanup()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "project"
        shutil.copytree(self.baseline_project, self.project)
        (self.project / "common-rules.md").write_text(
            "# Common rules\n\nEnter every flow through the declared runtime entry.\n",
            encoding="utf-8",
        )
        self.fixture = COMPONENT_TESTS.ComponentDesignV4CliTest(
            methodName="test_designless_context_with_business_data_gets_a_source_only_work_item"
        )
        self.fixture.temp_dir = self.temp_dir
        self.fixture.root = self.root
        self.fixture.project = self.project
        self.fixture.stage_dir = self.project / ".icp" / "component-design"
        self.fixture.bundle_path = self.build_topology_bundle()
        self.stage_dir = self.project / ".icp" / "implementation"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def build_topology_bundle(self) -> Path:
        topology = EIGHT_PAGE_TOPOLOGY
        references_by_from: dict[str, list[dict]] = {}
        for reference in topology["references"]:
            references_by_from.setdefault(reference["from"], []).append(reference)
        raw_rows = {}
        for index, member in enumerate(topology["members"], start=1):
            raw_rows[member["title"]] = {
                "标题": member["title"],
                "Route": member["route"],
                "设计稿地址": eight_page_design_url(index),
                "UI补充描述": member["ui"],
                "交互描述": member["interaction"],
                "接口描述": member["api"],
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
        spreadsheet_id = "eight-page-fixture"
        sheet_name = "Sheet1"
        source_id = "google-sheets:" + canonical_digest(
            {"sheet_name": sheet_name, "spreadsheet_id": spreadsheet_id}
        )
        analysis_rows = []
        catalog_titles = [member["title"] for member in topology["members"]]
        for member in topology["members"]:
            title = member["title"]
            row = raw_rows[title]
            fields = []
            for column, value in row.items():
                if column in {
                    "标题",
                    "frontend status",
                    "frontend pr",
                    "frontend reviews",
                    "frontend lease_token",
                    "frontend lease_until",
                    "frontend last_error",
                }:
                    continue
                references = []
                dismissals = []
                if column == "交互描述":
                    for reference in references_by_from.get(title, []):
                        start = value.find(reference["to"])
                        if start >= 0:
                            references.append(
                                {
                                    "reference_id": f"{title}-{column}-{reference['to']}",
                                    "start": start,
                                    "end": start + len(reference["to"]),
                                    "quote": reference["to"],
                                    "target_title": reference["to"],
                                    "relation_kind": reference["kind"],
                                }
                            )
                for candidate_title in catalog_titles:
                    if candidate_title == title:
                        continue
                    occurrence = value.find(candidate_title)
                    while occurrence >= 0:
                        occurrence_end = occurrence + len(candidate_title)
                        resolved = any(
                            reference["target_title"] == candidate_title
                            and reference["start"] <= occurrence
                            and reference["end"] >= occurrence_end
                            for reference in references
                        )
                        if not resolved:
                            dismissals.append(
                                {
                                    "candidate_title": candidate_title,
                                    "start": occurrence,
                                    "end": occurrence_end,
                                    "quote": value[occurrence:occurrence_end],
                                    "rationale": (
                                        "The mention is part of one larger "
                                        "resolved title reference."
                                    ),
                                }
                            )
                        occurrence = value.find(candidate_title, occurrence + 1)
                fields.append(
                    {
                        "column": column,
                        "source_sha256": hashlib.sha256(
                            value.encode("utf-8")
                        ).hexdigest(),
                        "references": references,
                        "dismissals": dismissals,
                    }
                )
            analysis_rows.append(
                {"title": title, "change_scope": "modify", "fields": fields}
            )
        analysis = {
            "kind": "iole.source-analysis-input.v2",
            "schema_version": 2,
            "source_id": source_id,
            "role": "client",
            "root_title": topology["entry_title"],
            "rows": analysis_rows,
        }
        catalog_payload = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "row_id_column": "标题",
            "titles": catalog_titles,
        }
        title_catalog = {
            "kind": "icps.flow-title-catalog.v1",
            "schema_version": 1,
            **catalog_payload,
            "catalog_digest": canonical_digest(catalog_payload),
        }
        field_reviews = [
            {
                "title": row["title"],
                "column": field["column"],
                "source_sha256": field["source_sha256"],
                "all_dependencies_identified": True,
                "reference_targets_correct": True,
                "dismissals_correct": True,
                "evidence": ["Complete source field checked against the title catalog."],
                "issues": [],
            }
            for row in analysis_rows
            for field in row["fields"]
        ]
        closure_review = {
            "kind": "iole.source-closure-review.v1",
            "schema_version": 1,
            "analysis_sha256": canonical_digest(analysis),
            "title_catalog_digest": title_catalog["catalog_digest"],
            "decision": "pass",
            "field_reviews": field_reviews,
            "cross_review": {
                "every_business_field_reviewed": True,
                "no_unresolved_reference": True,
                "no_ambiguous_target": True,
                "evidence": ["Every analyzed source field is represented once."],
                "issues": [],
            },
        }
        raw_path = self.root / "eight-page-raw-rows.json"
        analysis_path = self.root / "eight-page-source-analysis.json"
        catalog_path = self.root / "eight-page-title-catalog.json"
        review_path = self.root / "eight-page-source-closure-review.json"
        bundle_path = self.project / ".icp" / "source" / "source-bundle.json"
        write_json(raw_path, raw_rows)
        write_json(analysis_path, analysis)
        write_json(catalog_path, title_catalog)
        write_json(review_path, closure_review)
        result = subprocess.run(
            [
                sys.executable,
                str(IOLE_SCRIPT),
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
                str(COMPONENT_TESTS.IOLE_MAPPING),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(result.stdout, encoding="utf-8")
        return bundle_path

    def cross_linked_page_facts(self, page: dict) -> dict:
        """The sealed fixture already consumes every transition requirement."""

        facts = self.fixture.valid_page_facts(page)
        graph = facts["interaction_graph"]
        external = [
            edge
            for edge in graph["edges"]
            if edge["target"]["kind"] in {"navigation", "modal"}
        ]
        if external:
            interaction = graph["interactions"][0]
            interaction["behavior"]["kind"] = (
                "navigate"
                if external[0]["target"]["kind"] == "navigation"
                else "present"
            )
        return facts

    def seal_component_stage(self) -> None:
        begun = self.fixture.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        pages = json.loads(begun.stdout)["pages"]
        self.assertEqual(len(pages), 8)
        for page in pages:
            recorded = self.fixture.record_page(
                page, self.cross_linked_page_facts(page)
            )
            self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        plan = self.fixture.add_presentation_usages(
            self.fixture.valid_abstraction_plan()
        )
        recorded = self.fixture.record_abstraction(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        verified = self.fixture.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def begin_implementation(self) -> None:
        begun = run_command(
            "begin",
            "--project-root",
            str(self.project),
            "--platform",
            "android-kotlin",
        )
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)

    def record_plan(self, plan: dict) -> subprocess.CompletedProcess[str]:
        path = self.project / "eight-page-plan.json"
        path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return run_command(
            "record-plan",
            "--project-root",
            str(self.project),
            "--plan",
            str(path),
        )

    def trace_steps(
        self, universe: dict, plan: dict, chain: list[tuple[str, str]]
    ) -> list[dict]:
        graphs_by_page = {
            graph["page_key"]: graph for graph in universe["interaction_graphs"]
        }
        interaction_by_obligation = {
            item["obligation_id"]: item.get("interaction_id")
            for item in universe["integration_obligations"]
        }
        cases_by_interaction: dict[tuple[str, str], dict] = {}
        for case in plan["integration_test_cases"]:
            interaction_id = interaction_by_obligation.get(case["obligation_id"])
            if interaction_id is not None:
                cases_by_interaction.setdefault(
                    (case["page_key"], interaction_id), case
                )
        steps = []
        for from_title, to_title in chain:
            from_key = page_key_for(from_title)
            graph = graphs_by_page[from_key]
            edge = next(
                edge
                for edge in graph["edges"]
                if edge["target"]["kind"] in {"navigation", "modal"}
                and edge["target"]["page_key"] == page_key_for(to_title)
            )
            case = cases_by_interaction[(from_key, edge["from_interaction_id"])]
            actions = case["runtime_test"]["actions"]
            if not actions:
                actions.append(
                    {
                        "operator": "click",
                        "target_tag": "trigger-" + to_title,
                        "value": None,
                        "fact_ids": [],
                    }
                )
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["operator"], "click")
            steps.append(
                {
                    "source_page_key": from_key,
                    "case_id": case["case_id"],
                    "interaction_id": edge["from_interaction_id"],
                    "outcome": edge["outcome"],
                    "action": actions[0]["operator"],
                    "target_tag": actions[0]["target_tag"],
                }
            )
        return steps

    def valid_eight_page_plan(self, *, empty_traces: bool = False) -> dict:
        plan = read_json(self.stage_dir / "implementation-plan.input.json")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        instances_by_page: dict[str, list[dict]] = {}
        for instance in universe["component_instances"]:
            instances_by_page.setdefault(instance["page_key"], []).append(instance)
        blocks_by_instance: dict[str, list[str]] = {}
        for block in universe["blocks"]:
            blocks_by_instance.setdefault(block["component_instance_id"], []).append(
                block["obligation_id"]
            )
        pages_by_key = {page["page_key"]: page for page in universe["pages"]}
        plan["pages"] = []
        for index, page_key in enumerate(universe["page_keys"], start=1):
            page = pages_by_key[page_key]
            route = page["route"]
            plan["pages"].append(
                {
                    "page_key": page_key,
                    "member_title": page["member_title"],
                    "route": route,
                    "source_file": f"app/src/main/java/test/Page{index}.kt",
                    "root_symbol": f"Page{index}Screen",
                    "dto_file": f"app/src/main/java/test/Page{index}Dto.kt",
                    "dto_symbol": f"Page{index}Dto",
                    "ui_state_symbol": f"Page{index}UiState",
                    "mock_fixture_path": f"app/src/test/resources/page-{index}.json",
                    "api_adapter_file": None,
                    "api_adapter_symbol": None,
                    "responsive_strategy": "Constraint-driven vertical flow with inset-aware scrolling.",
                    "component_instance_ids": [
                        item["component_instance_id"]
                        for item in instances_by_page[page_key]
                    ],
                }
            )
        entry_page_key = page_key_for(EIGHT_PAGE_TOPOLOGY["entry_title"])
        entry_source_page = next(
            page for page in plan["pages"] if page["page_key"] == entry_page_key
        )
        plan["runtime_entries"] = [
            {
                "entry_id": "entry-login",
                "source_file": entry_source_page["source_file"],
                "symbol": entry_source_page["root_symbol"],
                "page_key": entry_page_key,
                "design_name": EIGHT_PAGE_TOPOLOGY["entry_title"],
            }
        ]
        plan["runtime_probe_provider"] = {
            "source_file": "app/src/main/java/test/IcpRuntimeProbePublisher.kt",
            "symbol": "IcpRuntimeProbePublisher",
            "publish_method_symbol": "publishRuntimeProbes",
            "output_path": "files/icp-runtime-probes.json",
        }
        plan["component_mappings"] = [
            {
                "component_instance_id": item["component_instance_id"],
                "component_id": item["component_id"],
                "page_key": item["page_key"],
                "source_file": next(
                    page["source_file"]
                    for page in plan["pages"]
                    if page["page_key"] == item["page_key"]
                ),
                "symbol": "Component"
                + hashlib.sha256(item["component_instance_id"].encode()).hexdigest()[:8],
                "platform_primitive": "Composable",
                "responsive_strategy": "Use parent constraints and wrap content without clipping.",
                "block_obligation_ids": blocks_by_instance.get(
                    item["component_instance_id"], []
                ),
            }
            for item in universe["component_instances"]
        ]
        component_pages: dict[str, set[str]] = {}
        for mapping in plan["component_mappings"]:
            component_pages.setdefault(mapping["component_id"], set()).add(
                mapping["page_key"]
            )
        for mapping in plan["component_mappings"]:
            if len(component_pages[mapping["component_id"]]) > 1:
                token = hashlib.sha256(
                    mapping["component_id"].encode()
                ).hexdigest()[:8]
                mapping["source_file"] = f"app/src/main/java/test/Shared{token}.kt"
                mapping["symbol"] = f"SharedComponent{token}"
        component_by_id = {
            item["component_instance_id"]: item for item in plan["component_mappings"]
        }
        plan["interaction_mappings"] = []
        for graph in universe["interaction_graphs"]:
            for interaction in graph["interactions"]:
                interaction_instance_ids = []
                for bound_ids in interaction["component_bindings"].values():
                    for instance_id in bound_ids:
                        if instance_id not in interaction_instance_ids:
                            interaction_instance_ids.append(instance_id)
                owner = component_by_id[interaction_instance_ids[0]]
                plan["interaction_mappings"].append(
                    {
                        "interaction_id": interaction["interaction_id"],
                        "page_key": graph["page_key"],
                        "component_instance_ids": interaction_instance_ids,
                        "source_file": owner["source_file"],
                        "symbol": owner["symbol"],
                        "implementation_anchor": (
                            "ICP:interaction:" + interaction["interaction_id"]
                        ),
                    }
                )
        plan["api_contract_mappings"] = []
        plan["design_element_mappings"] = [
            {
                "obligation_id": item["obligation_id"],
                "source_file": component_by_id[item["component_instance_id"]][
                    "source_file"
                ],
                "symbol": component_by_id[item["component_instance_id"]]["symbol"],
                "implementation_anchor": "ICP:" + item["obligation_id"],
                "runtime_probe_tag": next(
                    (
                        assertion["probe_tag"]
                        for assertion in universe["reference_viewport_assertions"]
                        if assertion["obligation_id"] == item["obligation_id"]
                    ),
                    None,
                ),
                "asset_mappings": [
                    {
                        "source_asset_id": asset["asset_id"],
                        "source_asset_sha256": asset["sha256"],
                        "target_resource_path": (
                            "app/src/main/res/raw/icp_"
                            + asset["sha256"][:16]
                            + "."
                            + asset["format"]
                        ),
                    }
                    for asset in item["assets"][:1]
                ],
            }
            for item in universe["design_elements"]
        ]
        instance_by_fact = {
            binding["fact_id"]: instance
            for instance in universe["component_instances"]
            for binding in instance["fact_bindings"]
        }
        plan["semantic_fact_mappings"] = [
            {
                "obligation_id": item["obligation_id"],
                "fact_id": item["fact_id"],
                "source_file": component_by_id[
                    instance_by_fact[item["fact_id"]]["component_instance_id"]
                ]["source_file"],
                "symbol": component_by_id[
                    instance_by_fact[item["fact_id"]]["component_instance_id"]
                ]["symbol"],
                "implementation_anchor": "ICP:" + item["obligation_id"],
            }
            for item in universe["semantic_facts"]
        ]
        plan["integration_test_cases"] = [
            {
                "case_id": "case-"
                + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:20],
                "obligation_id": item["obligation_id"],
                "source_kind": item["source_kind"],
                "fact_id": item["fact_id"],
                "basis_fact_ids": item["basis_fact_ids"],
                "component_instance_id": item["component_instance_id"],
                "page_key": item["page_key"],
                "test_file": (
                    "app/src/androidTest/java/test/Interaction_"
                    + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8]
                    + ".kt"
                ),
                "test_name": "integration_"
                + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8],
                "runtime_test": ImplementationCliTest.runtime_test_contract(
                    self, item, universe
                ),
                "command": [
                    "./gradlew",
                    "connectedDebugAndroidTest",
                    (
                        "-Pandroid.testInstrumentationRunnerArguments.class="
                        "test.Interaction_"
                        + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8]
                        + "#integration_"
                        + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8]
                    ),
                ],
            }
            for item in universe["integration_obligations"]
        ]
        plan["presentation_mappings"] = [
            {
                "usage_id": item["usage_id"],
                "source_file": next(
                    page["source_file"]
                    for page in plan["pages"]
                    if page["page_key"] == item["source_page_key"]
                ),
                "symbol": "Presentation"
                + hashlib.sha256(item["usage_id"].encode()).hexdigest()[:8],
                "implementation_anchor": "ICP:presentation:" + item["usage_id"],
            }
            for item in universe["presentation_usages"]
        ]
        plan["visual_capture_cases"] = []
        for item in universe["visual_references"]:
            page_key = item["page_key"]
            component = next(
                mapping
                for mapping in plan["component_mappings"]
                if mapping["page_key"] == page_key
            )
            chain = [] if empty_traces else EIGHT_PAGE_ROUTE_CHAINS[item["design_name"]]
            plan["visual_capture_cases"].append(
                {
                    "design_name": item["design_name"],
                    "visual_state_id": item["visual_state_id"],
                    "page_key": page_key,
                    "entry_id": "entry-login",
                    "package_name": "test.app",
                    "locale": "ru-RU",
                    "precondition_commands": [],
                    "interaction_trace": self.trace_steps(universe, plan, chain),
                    "production_render": {
                        "component_instance_id": component["component_instance_id"],
                        "source_file": component["source_file"],
                        "symbol": component["symbol"],
                        "root_tag": "root-" + item["visual_state_id"],
                    },
                }
            )
        plan["verification_commands"] = {
            "lint": [["./gradlew", "lintDebug"]],
            "build": [["./gradlew", "assembleDebug"]],
            "integration": [["./gradlew", "connectedDebugAndroidTest"]],
        }
        page_node_ids = {
            page_key: f"page:{page_key}" for page_key in universe["page_keys"]
        }
        plan["execution_nodes"] = [
            {
                "node_id": "foundation",
                "kind": "foundation",
                "page_keys": [],
                "depends_on": [],
                "case_ids": [],
            },
            *[
                {
                    "node_id": page_node_ids[page_key],
                    "kind": "page",
                    "page_keys": [page_key],
                    "depends_on": ["foundation"],
                    "case_ids": [
                        case["case_id"]
                        for case in plan["integration_test_cases"]
                        if case["page_key"] == page_key
                    ],
                }
                for page_key in universe["page_keys"]
            ],
            {
                "node_id": "flow-integration",
                "kind": "flow-integration",
                "page_keys": list(universe["page_keys"]),
                "depends_on": [page_node_ids[key] for key in universe["page_keys"]],
                "case_ids": [],
            },
        ]
        file_owners: dict[str, str] = {
            "app/src/main/AndroidManifest.xml": "foundation",
            "app/src/main/MainActivity.kt": "flow-integration",
            plan["runtime_probe_provider"]["source_file"]: "foundation",
        }
        for page in plan["pages"]:
            owner = page_node_ids[page["page_key"]]
            for field in (
                "source_file",
                "dto_file",
                "mock_fixture_path",
                "api_adapter_file",
            ):
                if page[field] is not None:
                    file_owners[page[field]] = owner
        for case in plan["integration_test_cases"]:
            file_owners[case["test_file"]] = page_node_ids[case["page_key"]]
        for mapping in plan["component_mappings"]:
            file_owners[mapping["source_file"]] = (
                "foundation"
                if len(component_pages[mapping["component_id"]]) > 1
                else page_node_ids[mapping["page_key"]]
            )
        for field in (
            "design_element_mappings",
            "semantic_fact_mappings",
            "presentation_mappings",
        ):
            for mapping in plan[field]:
                owner = file_owners.get(mapping["source_file"])
                if owner is None:
                    page = next(
                        page
                        for page in plan["pages"]
                        if page["source_file"] == mapping["source_file"]
                    )
                    owner = page_node_ids[page["page_key"]]
                    file_owners[mapping["source_file"]] = owner
                for asset in mapping.get("asset_mappings", []):
                    file_owners[asset["target_resource_path"]] = owner
        plan["file_owners"] = file_owners
        plan["layout_decisions"] = authored_layout_decisions(universe)
        plan["layout_contracts"] = []
        return plan

    def test_record_plan_enforces_entry_rooted_reachability(self) -> None:
        self.seal_component_stage()
        self.begin_implementation()

        empty_traces = self.valid_eight_page_plan(empty_traces=True)
        rejected = self.record_plan(empty_traces)
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        failure = json.loads(rejected.stderr)
        self.assertEqual(failure["error"], "visual_production_path_unproven")
        unreachable = failure["details"]["unreachable"]
        expected_designs = [
            "客服弹窗",
            "反馈",
            "登录文件-弹窗",
            "登录-验证码",
            "反馈上传弹窗",
            "权限-相机",
            "权限-相册",
        ]
        self.assertEqual(
            [item["design_name"] for item in unreachable], expected_designs
        )
        self.assertEqual(
            [item["page_key"] for item in unreachable],
            [page_key_for(name) for name in expected_designs],
        )

        wrong_source = self.valid_eight_page_plan()
        wrong_source_case = next(
            case
            for case in wrong_source["visual_capture_cases"]
            if case["design_name"] == "客服弹窗"
        )
        wrong_source_case["interaction_trace"][0]["source_page_key"] = page_key_for(
            "反馈"
        )
        rejected = self.record_plan(wrong_source)
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        failure = json.loads(rejected.stderr)
        self.assertEqual(failure["error"], "visual_production_path_unproven")
        self.assertEqual(failure["details"]["reason"], "wrong_source_page")
        self.assertEqual(failure["details"]["design_name"], "客服弹窗")
        self.assertEqual(failure["details"]["step_index"], 0)
        self.assertEqual(
            failure["details"]["expected_source_page_key"], page_key_for("登录")
        )
        self.assertEqual(
            failure["details"]["actual_source_page_key"], page_key_for("反馈")
        )

        wrong_outcome = self.valid_eight_page_plan()
        wrong_outcome_case = next(
            case
            for case in wrong_outcome["visual_capture_cases"]
            if case["design_name"] == "反馈"
        )
        wrong_outcome_case["interaction_trace"][0]["outcome"] = "opened-elsewhere"
        rejected = self.record_plan(wrong_outcome)
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        failure = json.loads(rejected.stderr)
        self.assertEqual(failure["error"], "visual_production_path_unproven")
        self.assertEqual(failure["details"]["reason"], "wrong_outcome")
        self.assertEqual(failure["details"]["design_name"], "反馈")
        self.assertEqual(failure["details"]["step_index"], 0)
        self.assertEqual(failure["details"]["selected_outcome"], "opened-elsewhere")
        self.assertEqual(
            failure["details"]["available_outcomes"],
            ["opened", "opened-2", "opened-3", "opened-4"],
        )
        self.assertNotIn(
            wrong_outcome_case["interaction_trace"][0]["outcome"],
            failure["details"]["available_outcomes"],
        )

        missing_relation = self.valid_eight_page_plan()
        missing_relation_case = next(
            case
            for case in missing_relation["visual_capture_cases"]
            if case["design_name"] == "反馈"
        )
        missing_relation_case["interaction_trace"][0]["interaction_id"] = (
            page_key_for("登录") + "-interaction-missing"
        )
        rejected = self.record_plan(missing_relation)
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        failure = json.loads(rejected.stderr)
        self.assertEqual(failure["error"], "visual_production_path_unproven")
        self.assertEqual(failure["details"]["reason"], "missing_relation")
        self.assertEqual(failure["details"]["design_name"], "反馈")

        unreachable_design = self.valid_eight_page_plan()
        unreachable_case = next(
            case
            for case in unreachable_design["visual_capture_cases"]
            if case["design_name"] == "权限-相册"
        )
        unreachable_case["interaction_trace"] = self.trace_steps(
            read_json(self.stage_dir / "coverage-universe.json"),
            unreachable_design,
            EIGHT_PAGE_ROUTE_CHAINS["权限-相机"],
        )
        rejected = self.record_plan(unreachable_design)
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        failure = json.loads(rejected.stderr)
        self.assertEqual(failure["error"], "visual_production_path_unproven")
        self.assertEqual(failure["details"]["reason"], "unreachable_design")
        self.assertEqual(failure["details"]["design_name"], "权限-相册")
        self.assertEqual(
            failure["details"]["expected_target"],
            {"page_key": page_key_for("权限-相册"), "design_name": "权限-相册"},
        )
        self.assertEqual(
            failure["details"]["reached_target"],
            {"page_key": page_key_for("权限-相机"), "design_name": "权限-相机"},
        )

        recorded = self.record_plan(self.valid_eight_page_plan())
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        frozen = read_json(self.stage_dir / "implementation-plan.json")
        entry_case = next(
            case
            for case in frozen["visual_capture_cases"]
            if case["design_name"] == EIGHT_PAGE_TOPOLOGY["entry_title"]
        )
        self.assertEqual(entry_case["interaction_trace"], [])
        self.assertEqual(entry_case["entry_id"], "entry-login")
        gallery_case = next(
            case
            for case in frozen["visual_capture_cases"]
            if case["design_name"] == "权限-相册"
        )
        self.assertEqual(len(gallery_case["interaction_trace"]), 3)
        self.assertEqual(
            [step["source_page_key"] for step in gallery_case["interaction_trace"]],
            [
                page_key_for("登录"),
                page_key_for("反馈"),
                page_key_for("反馈上传弹窗"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
