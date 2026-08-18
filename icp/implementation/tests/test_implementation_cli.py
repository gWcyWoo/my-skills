from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = STAGE_ROOT / "scripts" / "implementation.py"
COMPONENT_TESTS = importlib.import_module(
    "icp.component-design.tests.test_component_design_v4_cli"
)
IMPLEMENTATION = importlib.import_module(
    "icp.implementation.scripts.implementation"
)
ComponentDesignV4CliTest = COMPONENT_TESTS.ComponentDesignV4CliTest
read_json = COMPONENT_TESTS.read_json


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
        ComponentDesignV4CliTest.setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        ComponentDesignV4CliTest.tearDownClass()

    def setUp(self) -> None:
        self.fixture = ComponentDesignV4CliTest(
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
            route = next(
                item["source_text"]
                for item in page["source_coverage"]
                if item["clause_id"] == "page:route"
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
                    "api_adapter_symbol": f"Page{index}ApiAdapter",
                    "responsive_strategy": "Constraint-driven vertical flow with inset-aware scrolling.",
                    "component_instance_ids": [
                        item["component_instance_id"]
                        for item in instances_by_page[page_key]
                    ],
                }
            )
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
                    + hashlib.sha256(item["page_key"].encode()).hexdigest()[:8]
                    + ".kt"
                ),
                "test_name": "integration_" + hashlib.sha256(item["obligation_id"].encode()).hexdigest()[:8],
                "command": ["./gradlew", "connectedDebugAndroidTest"],
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
            page_cases = [
                case
                for case in plan["integration_test_cases"]
                if case["page_key"] == page_key
            ]
            interaction_trace = []
            if page_key in seen_visual_pages:
                interaction_trace = [
                    {
                        "case_id": page_cases[0]["case_id"],
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
            for field in ("source_file", "dto_file", "mock_fixture_path"):
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
        return plan

    def record_plan(self, plan: dict) -> subprocess.CompletedProcess[str]:
        path = self.project / "implementation-plan.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_command(
            "record-plan",
            "--project-root",
            str(self.project),
            "--plan",
            str(path),
        )

    def run_case(self, case_id: str, phase: str) -> subprocess.CompletedProcess[str]:
        return run_command(
            "run-case",
            "--project-root",
            str(self.project),
            "--case-id",
            case_id,
            "--phase",
            phase,
        )

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

    def prepare_verifiable_implementation(
        self, plan: dict
    ) -> tuple[dict, dict]:
        behavior_path = self.project / "app_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"visual_interaction_case_{index}.py"
            test_path.write_text(
                "from app_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
            case["command"] = [sys.executable, test_path.name]
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
        for case in plan["integration_test_cases"]:
            red = self.run_case(case["case_id"], "red")
            self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        behavior_path.write_text("IMPLEMENTED = True\n", encoding="utf-8")
        for case in plan["integration_test_cases"]:
            green = self.run_case(case["case_id"], "green")
            self.assertEqual(green.returncode, 0, green.stdout + green.stderr)

        file_lines: dict[str, list[str]] = {}
        for page in plan["pages"]:
            file_lines.setdefault(page["source_file"], []).append(
                f"fun {page['root_symbol']}() = Unit"
            )
            file_lines.setdefault(page["dto_file"], []).extend(
                [
                    f"data class {page['dto_symbol']}(val value: String)",
                    f"data class {page['ui_state_symbol']}(val value: String)",
                    f"class {page['api_adapter_symbol']}",
                ]
            )
            mock = self.project / page["mock_fixture_path"]
            mock.parent.mkdir(parents=True, exist_ok=True)
            mock.write_text('{"value":"fixture"}\n', encoding="utf-8")
        for mapping in plan["component_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).append(
                f"fun {mapping['symbol']}() = Unit"
            )
        for visual in plan["visual_capture_cases"]:
            file_lines.setdefault(
                visual["production_render"]["source_file"], []
            ).append("// " + visual["production_render"]["root_tag"])
        for field in (
            "design_element_mappings",
            "semantic_fact_mappings",
            "presentation_mappings",
        ):
            for mapping in plan[field]:
                file_lines.setdefault(mapping["source_file"], []).extend(
                    [
                        f"fun {mapping['symbol']}() = Unit",
                        "// " + mapping["implementation_anchor"],
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
        evidence = {
            "schema": "icp.implementation.runtime-evidence.v1",
            "implementation_plan_sha256": plan_sha,
            "adaptive_components": [
                {
                    "component_instance_id": item["component_instance_id"],
                    "constraint_driven": True,
                    "content_adaptive": True,
                    "no_content_specific_geometry": True,
                }
                for item in universe["component_instances"]
            ],
            "responsive_runs": [
                {
                    "page_key": page_key,
                    "viewport": viewport,
                    "evaluation_scope": "responsive_behavior",
                    "width": width,
                    "height": height,
                    "renders": True,
                    "natural_text_reflow": True,
                    "no_clip": True,
                    "no_overlap": True,
                    "no_horizontal_overflow": True,
                    "content_reachable": True,
                    "controls_operable": True,
                    "system_bars_correct": True,
                    "insets_safe": True,
                }
                for page_key in universe["page_keys"]
                for viewport, width, height in (
                    ("compact", 360, 800),
                    ("expanded", 840, 1200),
                )
            ],
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
                        }
                        for item in universe["reference_viewport_assertions"]
                        if item["design_name"] == reference["design_name"]
                    ],
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
        return universe, evidence

    def test_begin_freezes_the_complete_stage1_and_stage2_implementation_universe(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        result = json.loads(begun.stdout)
        self.assertEqual(result["state"], "awaiting_plan")
        universe = read_json(self.stage_dir / "coverage-universe.json")
        state = read_json(self.stage_dir / "state.json")
        lock = read_json(
            self.project / ".icp" / "component-design" / "component-lock.json"
        )
        bindings = read_json(
            self.project
            / ".icp"
            / "component-design"
            / "block-component-bindings.json"
        )

        self.assertEqual(universe["schema"], "icp.implementation.coverage-universe.v1")
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
        expected_interaction_facts = {
            value["fact_id"]
            for page in lock["pages"]
            if page["page_key"] in set(universe["page_keys"])
            for item in page["interaction_items"]
            for field in ("condition", "state", "trigger", "behavior")
            for value in [item[field]]
            if value is not None
        }
        self.assertEqual(
            {item["fact_id"] for item in universe["integration_obligations"] if item["fact_id"] is not None},
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
        frame = source["source_fact"]["payload"]["frame"]
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

    def test_every_framed_design_element_gets_a_reference_bounds_assertion(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        universe = read_json(self.stage_dir / "coverage-universe.json")
        framed = {
            item["obligation_id"]
            for item in universe["design_elements"]
            if isinstance(item["source_fact"].get("payload", {}).get("frame"), dict)
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
        self.assertEqual(font_size["expected"], {"sp": 14})
        self.assertEqual(line_height["expected"], {"dp": 22})
        self.assertEqual(font_size["obligation_id"], line_height["obligation_id"])
        self.assertEqual(font_size["mode"], "exact_at_reference")

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
            color["expected"], {"r": 32, "g": 64, "b": 128, "a": 255}
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

    def test_integration_obligations_have_it_interaction_and_model_inference_sources(self) -> None:
        page = {
            "page_key": "page-a",
            "member_title": "Page A",
            "candidates": [
                {
                    "facts": [
                        {
                            "fact_id": "fact-interaction",
                            "kind": "trigger",
                            "meaning": "Tap the action.",
                            "source_refs": [
                                {"clause_id": "page:interaction", "start": 0, "end": 3}
                            ],
                        },
                        {
                            "fact_id": "fact-it",
                            "kind": "behavior",
                            "meaning": "Show the result.",
                            "source_refs": [
                                {"clause_id": "acceptance:1", "start": 0, "end": 3}
                            ],
                        },
                    ]
                }
            ],
        }
        component_instances = [
            {
                "page_key": "page-a",
                "component_instance_id": "instance-a",
                "fact_bindings": [
                    {"fact_id": "fact-interaction"},
                    {"fact_id": "fact-it"},
                ],
            }
        ]
        interaction_obligations = [
            {
                "obligation_id": "legacy-interaction",
                "page_key": "page-a",
                "member_title": "Page A",
                "item_id": "item-a",
                "kind": "trigger",
                "fact_id": "fact-interaction",
                "meaning": "Tap the action.",
                "source_ref": {"clause_id": "page:interaction", "start": 0, "end": 3},
            }
        ]

        obligations = IMPLEMENTATION.build_integration_obligations(
            [page], component_instances, interaction_obligations
        )

        self.assertEqual(
            {item["source_kind"] for item in obligations},
            {"it_description", "interaction_description", "model_inference"},
        )
        self.assertEqual(len(obligations), 3)
        inferred = next(
            item for item in obligations if item["source_kind"] == "model_inference"
        )
        self.assertEqual(inferred["component_instance_id"], "instance-a")
        self.assertEqual(
            inferred["basis_fact_ids"], ["fact-interaction", "fact-it"]
        )

    def test_codegen_prompt_and_complete_block_join_are_frozen_inputs(self) -> None:
        begun = self.begin()

        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        state = read_json(self.stage_dir / "state.json")
        prompt_path = self.stage_dir / "implementation-prompt.md"
        self.assertTrue(prompt_path.is_file())
        prompt_text = prompt_path.read_text(encoding="utf-8")
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
            "Implement every Stage 1 `design_element`",
            "affected design-element obligation",
            "fix the implementation",
        ):
            self.assertIn(required_instruction, prompt_text)
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

    def test_visual_mae_is_diagnostic_when_reference_fidelity_and_adaptive_layout_pass(self) -> None:
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

        verified = self.verify_implementation(evidence)

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        report_path = self.stage_dir / "visual-difference-report.json"
        self.assertTrue(report_path.is_file())
        self.assertFalse((self.stage_dir / "visual-diagnosis.input.json").exists())
        report = read_json(report_path)
        self.assertEqual(report["mae_role"], "diagnostic_only")
        self.assertEqual(
            {item["design_name"] for item in report["diagnostics"]},
            {item["design_name"] for item in universe["visual_references"]},
        )
        self.assertTrue(all(item["difference_bbox"] for item in report["diagnostics"]))
        self.assertTrue(
            all(item["design_elements"] for item in report["diagnostics"])
        )

    def test_responsive_evidence_requires_behavior_scope_not_reference_pixel_fidelity(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(plan)
        evidence["responsive_runs"][0].pop("natural_text_reflow")

        rejected = self.verify_implementation(evidence)

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("responsive_evidence_invalid", rejected.stderr)

    def test_every_component_must_have_adaptive_layout_evidence(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(plan)
        missing_component = evidence["adaptive_components"].pop()

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

    def test_visual_state_rejects_debug_terminal_state_setup(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        secondary = plan["visual_capture_cases"][0]
        page_case = next(
            case
            for case in plan["integration_test_cases"]
            if case["page_key"] == secondary["page_key"]
        )
        secondary["interaction_trace"] = [
            {
                "case_id": page_case["case_id"],
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

    def test_verify_rejects_measurements_not_wired_to_production_element_probes(self) -> None:
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
        self.assertIn("visual_render_identity_mismatch", rejected.stderr)

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
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"interaction_case_{index}.py"
            test_path.write_text(
                "from app_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
            case["command"] = [sys.executable, test_path.name]
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
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"page_case_{index}.py"
            test_path.write_text(
                "from page_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
            case["command"] = [sys.executable, test_path.name]
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
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"vertical_case_{index}.py"
            test_path.write_text(
                "from vertical_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
            case["command"] = [sys.executable, test_path.name]
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
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"parallel_case_{index}.py"
            test_path.write_text(
                "import time\n"
                "from parallel_behavior import IMPLEMENTED\n"
                "time.sleep(0.3)\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
            case["command"] = [sys.executable, test_path.name]
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
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
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
        driver = self.project / "fake-visual-driver.py"
        driver.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, json, shutil\n"
            "from pathlib import Path\n"
            f"state_path = Path({str(driver_state)!r})\n"
            f"reference_path = Path({str(reference_path)!r})\n"
            f"fail_marker = Path({str(fail_marker)!r})\n"
            "p=argparse.ArgumentParser(); p.add_argument('operation'); "
            "p.add_argument('--package'); p.add_argument('--config'); p.add_argument('--output'); "
            "p.add_argument('--trace'); p.add_argument('--contract'); p.add_argument('--state-id'); "
            "p.add_argument('--root-tag'); a=p.parse_args()\n"
            "if a.operation == 'snapshot': print(state_path.read_text())\n"
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n"
            "elif a.operation == 'cold-start': print(json.dumps({"
            "'activity_resumed': True, 'process_alive': True, "
            "'no_fatal_exception': True, 'fatal_log_tail': ''}))\n"
            "elif a.operation == 'interact':\n"
            "    trace=json.loads(Path(a.trace).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-interaction.v1','steps':trace['steps']}))\n"
            "elif a.operation == 'attest': print(json.dumps({"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'state_attested':True,"
            "'root_attested':True}))\n"
            "elif a.operation == 'measure':\n"
            "    contract=json.loads(Path(a.contract).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-measurements.v1',"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'measurements':["
            "{'assertion_id':item['assertion_id'],'probe_tag':item['probe_tag'],"
            "'kind':item['kind'],'actual':item['expected']} for item in contract['assertions']]}))\n"
            "elif a.operation == 'capture':\n"
            "    if fail_marker.exists(): raise SystemExit(7)\n"
            "    shutil.copyfile(reference_path, a.output)\n",
            encoding="utf-8",
        )
        driver.chmod(0o755)

        failed = self.capture_visual(reference["design_name"], driver)

        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("visual_capture_failed", failed.stderr)
        self.assertEqual(json.loads(driver_state.read_text()), initial)

        fail_marker.unlink()
        captured = self.capture_visual(reference["design_name"], driver)

        self.assertEqual(captured.returncode, 0, captured.stdout + captured.stderr)
        result = json.loads(captured.stdout)
        capture_evidence = read_json(self.project / result["capture_evidence"])
        self.assertEqual(capture_evidence["before"], initial)
        self.assertEqual(capture_evidence["restored"], initial)
        self.assertTrue(capture_evidence["cold_start"]["process_alive"])
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

    def test_capture_visual_uses_the_production_path_and_measures_frozen_source_facts(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        visual = plan["visual_capture_cases"][0]
        page_case = next(
            case
            for case in plan["integration_test_cases"]
            if case["page_key"] == visual["page_key"]
        )
        visual["interaction_trace"] = [
            {
                "case_id": page_case["case_id"],
                "action": "click",
                "target_tag": "feedback-photo-source-trigger",
            }
        ]
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
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
        driver = self.project / "production-visual-driver.py"
        driver.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse, json, shutil, sys\n"
            "from pathlib import Path\n"
            f"state_path = Path({str(driver_state)!r})\n"
            f"log_path = Path({str(operation_log)!r})\n"
            f"reference_path = Path({str(reference_path)!r})\n"
            "p=argparse.ArgumentParser(); p.add_argument('operation'); "
            "p.add_argument('--package'); p.add_argument('--config'); p.add_argument('--output'); "
            "p.add_argument('--trace'); p.add_argument('--contract'); p.add_argument('--state-id'); "
            "p.add_argument('--root-tag'); a=p.parse_args()\n"
            "with log_path.open('a') as f: f.write(json.dumps(vars(a), sort_keys=True)+'\\n')\n"
            "if a.operation == 'snapshot': print(state_path.read_text())\n"
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n"
            "elif a.operation == 'cold-start':\n"
            "    if a.state_id is not None: raise SystemExit(12)\n"
            "    print(json.dumps({'activity_resumed': True, 'process_alive': True, "
            "'no_fatal_exception': True, 'fatal_log_tail': ''}))\n"
            "elif a.operation == 'interact':\n"
            "    trace=json.loads(Path(a.trace).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-interaction.v1','steps':trace['steps']}))\n"
            "elif a.operation == 'attest': print(json.dumps({"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'state_attested':True,"
            "'root_attested':True}))\n"
            "elif a.operation == 'measure':\n"
            "    contract=json.loads(Path(a.contract).read_text())\n"
            "    print(json.dumps({'schema':'icp.visual-measurements.v1',"
            "'visual_state_id':a.state_id,'root_tag':a.root_tag,'measurements':["
            "{'assertion_id':item['assertion_id'],'probe_tag':item['probe_tag'],"
            "'kind':item['kind'],'actual':item['expected']} for item in contract['assertions']]}))\n"
            "elif a.operation == 'capture': shutil.copyfile(reference_path, a.output)\n",
            encoding="utf-8",
        )
        driver.chmod(0o755)

        captured = self.capture_visual(visual["design_name"], driver)

        self.assertEqual(captured.returncode, 0, captured.stdout + captured.stderr)
        result = json.loads(captured.stdout)
        capture = read_json(self.project / result["capture_evidence"])
        operations = [json.loads(line) for line in operation_log.read_text().splitlines()]
        self.assertEqual(
            [item["operation"] for item in operations],
            ["snapshot", "apply", "cold-start", "interact", "attest", "measure", "capture", "restore", "snapshot"],
        )
        cold_start = next(item for item in operations if item["operation"] == "cold-start")
        self.assertIsNone(cold_start["state_id"])
        self.assertEqual(capture["schema"], "icp.implementation.visual-capture-evidence.v3")
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
        recorded = self.record_plan(plan)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
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
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n"
            "elif a.operation == 'cold-start': print(json.dumps({"
            "'activity_resumed': False, 'process_alive': False, "
            "'no_fatal_exception': False, 'fatal_log_tail': 'AndroidRuntime crash'}))\n"
            "elif a.operation == 'capture': capture_marker.write_text('called')\n",
            encoding="utf-8",
        )
        driver.chmod(0o755)

        rejected = self.capture_visual(
            plan["visual_capture_cases"][0]["design_name"], driver
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("android_cold_start_failed", rejected.stderr)
        self.assertFalse(capture_marker.exists())
        self.assertEqual(json.loads(driver_state.read_text()), initial)

    def test_verify_requires_code_anchors_commands_two_viewports_and_visual_mae(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        behavior_path = self.project / "app_behavior.py"
        behavior_path.write_text("IMPLEMENTED = False\n", encoding="utf-8")
        for index, case in enumerate(plan["integration_test_cases"]):
            test_path = self.project / f"interaction_case_{index}.py"
            test_path.write_text(
                "from app_behavior import IMPLEMENTED\n"
                "raise SystemExit(0 if IMPLEMENTED else 1)\n",
                encoding="utf-8",
            )
            case["command"] = [sys.executable, test_path.name]
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
                    f"class {page['api_adapter_symbol']}",
                ]
            )
            mock = self.project / page["mock_fixture_path"]
            mock.parent.mkdir(parents=True, exist_ok=True)
            mock.write_text('{"value":"fixture"}\n', encoding="utf-8")
        for mapping in plan["component_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).append(f"fun {mapping['symbol']}() = Unit")
        for mapping in plan["design_element_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).extend(
                [
                    "// " + mapping["implementation_anchor"],
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
        missing_anchor = plan["design_element_mappings"][-1]["implementation_anchor"]
        for relative, lines in file_lines.items():
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(line for line in lines if missing_anchor not in line) + "\n",
                encoding="utf-8",
            )
        universe = read_json(self.stage_dir / "coverage-universe.json")
        evidence = {
            "schema": "icp.implementation.runtime-evidence.v1",
            "implementation_plan_sha256": read_json(self.stage_dir / "state.json")[
                "implementation_plan_sha256"
            ],
            "adaptive_components": [
                {
                    "component_instance_id": item["component_instance_id"],
                    "constraint_driven": True,
                    "content_adaptive": True,
                    "no_content_specific_geometry": True,
                }
                for item in universe["component_instances"]
            ],
            "responsive_runs": [
                {
                    "page_key": page_key,
                    "viewport": viewport,
                    "evaluation_scope": "responsive_behavior",
                    "width": width,
                    "height": height,
                    "renders": True,
                    "natural_text_reflow": True,
                    "no_clip": True,
                    "no_overlap": True,
                    "no_horizontal_overflow": True,
                    "content_reachable": True,
                    "controls_operable": True,
                    "system_bars_correct": True,
                    "insets_safe": True,
                }
                for page_key in universe["page_keys"]
                for viewport, width, height in (
                    ("compact", 360, 800),
                    ("expanded", 840, 1200),
                )
            ],
            "visual_runs": [
                {
                    "design_name": item["design_name"],
                    "actual_screenshot": item["path"],
                    "capture_evidence": "missing.capture.json",
                }
                for item in universe["visual_references"]
            ],
        }

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
                        }
                        for item in universe["reference_viewport_assertions"]
                        if item["design_name"] == visual_run["design_name"]
                    ],
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

        verified = self.verify_implementation(evidence)

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        result = json.loads(verified.stdout)
        self.assertEqual(result["state"], "complete")
        stage_result = read_json(self.stage_dir / "stage-result.json")
        self.assertEqual(stage_result["status"], "complete")
        self.assertTrue(all(item["mae"] == 0 for item in stage_result["visual_results"]))


if __name__ == "__main__":
    unittest.main()
