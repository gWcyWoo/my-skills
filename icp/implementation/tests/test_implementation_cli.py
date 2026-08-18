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
        component_by_id = {
            item["component_instance_id"]: item for item in plan["component_mappings"]
        }
        plan["design_element_mappings"] = [
            {
                "obligation_id": item["obligation_id"],
                "source_file": component_by_id[item["component_instance_id"]]["source_file"],
                "symbol": component_by_id[item["component_instance_id"]]["symbol"],
                "implementation_anchor": "ICP:" + item["obligation_id"],
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
                "test_file": "app/src/androidTest/java/test/InteractionTest.kt",
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
        plan["visual_capture_cases"] = [
            {
                "design_name": item["design_name"],
                "package_name": "test.app",
                "locale": "ru-RU",
                "state_setup_commands": [],
            }
            for item in universe["visual_references"]
        ]
        plan["verification_commands"] = {
            "lint": [["./gradlew", "lintDebug"]],
            "build": [["./gradlew", "assembleDebug"]],
            "integration": [["./gradlew", "connectedDebugAndroidTest"]],
        }
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
                "schema": "icp.implementation.visual-capture-evidence.v1",
                "evaluation_scope": "reference_viewport_visual_fidelity",
                "implementation_plan_sha256": plan_sha,
                "design_name": reference["design_name"],
                "reference_sha256": reference["sha256"],
                "logical_artboard_size": reference["logical_artboard_size"],
                "reference_pixel_size": reference["pixel_size"],
                "logical_scale": reference["logical_scale"],
                "capture_strategy": "extended-viewport-full-page",
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
                    "reference_fidelity": {
                        "colors": True,
                        "component_structure": True,
                        "spacing": True,
                        "font_sizes": True,
                    },
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
            "Create every planned integration test",
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

    def test_every_component_must_be_adaptive_and_reference_fidelity_must_pass(self) -> None:
        begun = self.begin()
        self.assertEqual(begun.returncode, 0, begun.stdout + begun.stderr)
        plan = self.valid_plan()
        _universe, evidence = self.prepare_verifiable_implementation(plan)
        missing_component = evidence["adaptive_components"].pop()

        rejected_component = self.verify_implementation(evidence)

        self.assertNotEqual(rejected_component.returncode, 0)
        self.assertIn("responsive_evidence_invalid", rejected_component.stderr)

        evidence["adaptive_components"].append(missing_component)
        evidence["visual_runs"][0]["reference_fidelity"]["spacing"] = False

        rejected_fidelity = self.verify_implementation(evidence)

        self.assertNotEqual(rejected_fidelity.returncode, 0)
        self.assertIn("visual_evidence_invalid", rejected_fidelity.stderr)

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
            "p.add_argument('--package'); p.add_argument('--config'); p.add_argument('--output'); a=p.parse_args()\n"
            "if a.operation == 'snapshot': print(state_path.read_text())\n"
            "elif a.operation in {'apply','restore'}: state_path.write_text(Path(a.config).read_text())\n"
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
            file_lines.setdefault(mapping["source_file"], []).append("// " + mapping["implementation_anchor"])
        for mapping in plan["semantic_fact_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).append("// " + mapping["implementation_anchor"])
        for mapping in plan["presentation_mappings"]:
            file_lines.setdefault(mapping["source_file"], []).extend(
                [f"fun {mapping['symbol']}() = Unit", "// " + mapping["implementation_anchor"]]
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
                    "reference_fidelity": {
                        "colors": True,
                        "component_structure": True,
                        "spacing": True,
                        "font_sizes": True,
                    },
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
                "schema": "icp.implementation.visual-capture-evidence.v1",
                "evaluation_scope": "reference_viewport_visual_fidelity",
                "implementation_plan_sha256": evidence["implementation_plan_sha256"],
                "design_name": visual_run["design_name"],
                "reference_sha256": reference["sha256"],
                "logical_artboard_size": reference["logical_artboard_size"],
                "reference_pixel_size": reference["pixel_size"],
                "logical_scale": reference["logical_scale"],
                "capture_strategy": "extended-viewport-full-page",
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
