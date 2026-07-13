from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_interaction_feature.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_valid_core(root: Path) -> tuple[Path, Path, Path]:
    spec = root / "spec"
    project = root / "project"
    (project / ".iff").mkdir(parents=True)
    spec.mkdir()
    manifest = root / "feature.json"
    manifest.write_text(
        json.dumps({"states": {"default": {"board": "default"}}}),
        encoding="utf-8",
    )
    contract = spec / "interaction_contract.json"
    contract.write_text(
        json.dumps(
            {
                "source": "点击确认后显示成功页",
                "rules": [
                    {
                        "id": "INT-ABC",
                        "source": "点击确认后显示成功页",
                        "action": "点击确认",
                        "actionTarget": {
                            "kind": "node",
                            "feature": "feature",
                            "board": "default",
                            "key": "iff:confirm",
                        },
                        "observableOutcome": "显示成功页",
                        "boundaryOutcome": "重复点击保持成功页",
                        "failureOutcome": "显示失败提示",
                        "observableTargets": {
                            "happy": {
                                "kind": "text",
                                "feature": "feature",
                                "board": "default",
                                "value": "success",
                            },
                            "boundary": {
                                "kind": "text",
                                "feature": "feature",
                                "board": "default",
                                "value": "success",
                            },
                            "failure": {
                                "kind": "text",
                                "feature": "feature",
                                "board": "default",
                                "value": "success",
                            },
                        },
                    }
                ],
                "ignoredItems": [],
                "acknowledgedNonRules": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    index = project / ".iff" / "board_index.json"
    index.write_text(
        json.dumps(
            {
                "boards": [
                    {
                        "feature": "feature",
                        "board": "default",
                        "texts": ["确认"],
                        "nodes": [
                            {
                                "id": "confirm",
                                "key": "iff:confirm",
                                "text": "确认",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (spec / "state_machine.json").write_text(
        json.dumps(
            {
                "version": 2,
                "inputs": {
                    "boards": hashlib.sha256(b"").hexdigest(),
                    "contract": sha256(contract),
                    "featureManifest": sha256(manifest),
                },
                "initialState": "default",
                "nodes": [{"id": "default", "meaning": "默认"}],
                "edges": [],
                "noTransitionReason": "单状态",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (spec / "interaction_anchors.json").write_text(
        json.dumps(
            {
                "inputs": {"contract": sha256(contract), "index": sha256(index)},
                "anchors": [],
            }
        ),
        encoding="utf-8",
    )
    return spec, project, manifest


def add_runtime_evidence(spec: Path, project: Path, case_ids: list[str]) -> None:
    lib = project / "lib"
    tests = project / "test"
    lib.mkdir()
    tests.mkdir()
    (project / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    (lib / "main.dart").write_text(
        "import 'feature_page.dart';\nvoid main() { const FeaturePage(); }\n",
        encoding="utf-8",
    )
    (lib / "feature_page.dart").write_text(
        "class FeaturePage { const FeaturePage(); }\n", encoding="utf-8"
    )
    bodies = []
    for case_id in case_ids:
        bodies.append(
            f"testWidgets('{case_id} interaction', (tester) async {{\n"
            "  await tester.pumpWidget(const FeaturePage());\n"
            "  await tester.tap(find.byKey(const ValueKey('iff:confirm')));\n"
            "  expect(find.text('success'), findsOneWidget);\n"
            "});\n"
        )
    test_file = tests / "feature_test.dart"
    test_file.write_text(
        "import 'package:demo/feature_page.dart';\n" + "".join(bodies),
        encoding="utf-8",
    )
    plan = spec / "interaction_test_plan.json"
    plan.write_text(
        json.dumps({"cases": [{"id": case_id} for case_id in case_ids]}),
        encoding="utf-8",
    )
    fingerprints = {
        "planHash": sha256(plan),
        "testHashes": {"feature_test.dart": sha256(test_file)},
    }
    (spec / "interaction_test_evidence.json").write_text(
        json.dumps(
            {
                "red": {
                    **fingerprints,
                    "exitCode": 1,
                    "command": ["flutter", "test", "--machine", "test"],
                    "cases": {
                        case_id: {"result": "failure", "skipped": False}
                        for case_id in case_ids
                    },
                },
                "green": {
                    **fingerprints,
                    "exitCode": 0,
                    "command": ["flutter", "test", "--machine", "test"],
                    "cases": {
                        case_id: {"result": "success", "skipped": False}
                        for case_id in case_ids
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def add_valid_runtime_evidence(
    spec: Path, project: Path, *, include_device: bool = True
) -> None:
    case_ids = ["INT-ABC-HAPPY", "INT-ABC-BOUNDARY", "INT-ABC-FAILURE"]
    add_runtime_evidence(spec, project, case_ids)
    plan = spec / "interaction_test_plan.json"
    generated = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "make_interaction_tests_plan.py"),
            "--contract",
            str(spec / "interaction_contract.json"),
            "--out",
            str(plan),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if generated.returncode != 0:
        raise AssertionError(generated.stdout + generated.stderr)
    evidence_path = spec / "interaction_test_evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    for phase in ("red", "green"):
        evidence[phase]["planHash"] = sha256(plan)
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    if include_device:
        integration_root = project / "integration_test"
        integration_root.mkdir()
        device_test = integration_root / "feature_test.dart"
        device_test.write_text(
            "".join(
                f"testWidgets('{case_id} device', (tester) async {{\n"
                "  app.main();\n"
                "  await tester.tap(find.byKey(const ValueKey('iff:confirm')));\n"
                "  expect(find.text('success'), findsOneWidget);\n"
                "});\n"
                for case_id in case_ids
            ),
            encoding="utf-8",
        )
        app_hashes = {
            str(path.relative_to(project)): sha256(path)
            for path in sorted((project / "lib").rglob("*.dart"))
        }
        (spec / "interaction_device_evidence.json").write_text(
            json.dumps(
                {
                    "command": [
                        "flutter",
                        "test",
                        "--machine",
                        "-d",
                        "emulator-5554",
                        str(integration_root.resolve()),
                    ],
                    "deviceId": "emulator-5554",
                    "actualPlatforms": ["android"],
                    "exitCode": 0,
                    "planHash": sha256(plan),
                    "testHashes": {"feature_test.dart": sha256(device_test)},
                    "appHashes": app_hashes,
                    "runtimeInputHashes": {
                        "pubspec.yaml": sha256(project / "pubspec.yaml")
                    },
                    "cases": {
                        case_id: {"result": "success", "skipped": False}
                        for case_id in case_ids
                    },
                }
            ),
            encoding="utf-8",
        )


class CheckInteractionFeatureTest(unittest.TestCase):
    def test_host_green_without_target_client_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            add_valid_runtime_evidence(spec, project, include_device=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("interaction_device_evidence.json missing", result.stdout + result.stderr)

    def test_current_complete_public_interaction_feature_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            add_valid_runtime_evidence(spec, project)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            report = json.loads(
                (spec / "interaction_gate_report.json").read_text(encoding="utf-8")
            )
            self.assertTrue(report["ok"])
            self.assertIn("interaction_contract.json", report["inputs"])

    def test_action_target_feature_disambiguates_same_board_and_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            add_valid_runtime_evidence(spec, project)
            index = project / ".iff" / "board_index.json"
            index_doc = json.loads(index.read_text(encoding="utf-8"))
            duplicate = dict(index_doc["boards"][0])
            duplicate["feature"] = "other_feature"
            index_doc["boards"].append(duplicate)
            index.write_text(json.dumps(index_doc), encoding="utf-8")
            anchors = spec / "interaction_anchors.json"
            anchors_doc = json.loads(anchors.read_text(encoding="utf-8"))
            anchors_doc["inputs"]["index"] = sha256(index)
            anchors.write_text(json.dumps(anchors_doc), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_core_interaction_artifacts_fail_visibly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            manifest = root / "feature.json"
            manifest.write_text(json.dumps({"states": {}}), encoding="utf-8")
            report = root / "interaction_gate_report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(report),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("interaction_contract.json missing", result.stdout)
            self.assertIn("interaction_test_evidence.json missing", result.stdout)
            self.assertFalse(json.loads(report.read_text(encoding="utf-8"))["ok"])

    def test_present_but_invalid_contract_is_recomputed_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            manifest = root / "feature.json"
            manifest.write_text(json.dumps({"states": {}}), encoding="utf-8")
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "observableOutcome": "显示成功页",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name in (
                "state_machine.json",
                "interaction_anchors.json",
                "interaction_test_plan.json",
                "interaction_test_evidence.json",
            ):
                (spec / name).write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("missing or unresolved boundaryOutcome", result.stdout)

    def test_unaccounted_source_item_is_recomputed_by_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            manifest = root / "feature.json"
            manifest.write_text(json.dumps({"states": {}}), encoding="utf-8")
            (spec / "interaction_contract.json").write_text(
                json.dumps(
                    {
                        "source": "点击确认后显示成功页；点击取消后关闭弹窗",
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "重复点击保持成功页",
                                "failureOutcome": "显示失败提示",
                            }
                        ],
                        "ignoredItems": [],
                        "acknowledgedNonRules": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name in (
                "state_machine.json",
                "interaction_anchors.json",
                "interaction_test_plan.json",
                "interaction_test_evidence.json",
            ):
                (spec / name).write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("点击取消后关闭弹窗", result.stdout)

    def test_invalid_state_machine_is_recomputed_by_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            spec.mkdir()
            project.mkdir()
            manifest = root / "feature.json"
            manifest.write_text(
                json.dumps(
                    {
                        "states": {
                            "idle": {"board": "idle"},
                            "done": {"board": "done"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            contract = {
                "source": "点击确认后显示成功页",
                "rules": [
                    {
                        "id": "INT-ABC",
                        "source": "点击确认后显示成功页",
                        "action": "点击确认",
                        "observableOutcome": "显示成功页",
                        "boundaryOutcome": "重复点击保持成功页",
                        "failureOutcome": "显示失败提示",
                    }
                ],
                "ignoredItems": [],
                "acknowledgedNonRules": [],
            }
            (spec / "interaction_contract.json").write_text(
                json.dumps(contract, ensure_ascii=False), encoding="utf-8"
            )
            (spec / "state_machine.json").write_text(
                json.dumps(
                    {
                        "initialState": "idle",
                        "nodes": [
                            {"id": "idle", "meaning": "初始"},
                            {"id": "done", "meaning": "完成"},
                        ],
                        "edges": [
                            {
                                "from": "idle",
                                "to": "missing",
                                "trigger": "__MODEL__",
                                "condition": None,
                                "ruleId": "INT-ABC",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name in (
                "interaction_anchors.json",
                "interaction_test_plan.json",
                "interaction_test_evidence.json",
            ):
                (spec / name).write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("unfilled __MODEL__", result.stdout)
            self.assertIn("unknown node", result.stdout)

    def test_stale_anchor_hash_is_recomputed_by_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec"
            project = root / "project"
            (project / ".iff").mkdir(parents=True)
            spec.mkdir()
            manifest = root / "feature.json"
            manifest.write_text(
                json.dumps({"states": {"default": {"board": "default"}}}),
                encoding="utf-8",
            )
            contract_path = spec / "interaction_contract.json"
            contract_path.write_text(
                json.dumps(
                    {
                        "source": "点击确认后显示成功页",
                        "rules": [
                            {
                                "id": "INT-ABC",
                                "source": "点击确认后显示成功页",
                                "action": "点击确认",
                                "observableOutcome": "显示成功页",
                                "boundaryOutcome": "重复点击保持成功页",
                                "failureOutcome": "显示失败提示",
                            }
                        ],
                        "ignoredItems": [],
                        "acknowledgedNonRules": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            index = project / ".iff" / "board_index.json"
            index.write_text(json.dumps({"boards": []}), encoding="utf-8")
            (spec / "state_machine.json").write_text(
                json.dumps(
                    {
                        "initialState": "default",
                        "nodes": [{"id": "default", "meaning": "默认"}],
                        "edges": [],
                        "noTransitionReason": "单状态",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (spec / "interaction_anchors.json").write_text(
                json.dumps(
                    {
                        "inputs": {
                            "contract": "stale",
                            "index": sha256(index),
                        },
                        "anchors": [],
                    }
                ),
                encoding="utf-8",
            )
            for name in (
                "interaction_test_plan.json",
                "interaction_test_evidence.json",
            ):
                (spec / name).write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("stale contract hash", result.stdout)

    def test_invalid_widget_coverage_is_recomputed_by_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            tests = project / "test"
            tests.mkdir()
            test_file = tests / "feature_test.dart"
            test_file.write_text("// INT-ABC-HAPPY\n", encoding="utf-8")
            plan = spec / "interaction_test_plan.json"
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            (spec / "interaction_test_evidence.json").write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("not declared in testWidgets", result.stdout)

    def test_widget_tests_without_runtime_feature_wiring_fail_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            lib = project / "lib"
            tests = project / "test"
            lib.mkdir()
            tests.mkdir()
            (lib / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            (project / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            test_file = tests / "feature_test.dart"
            test_file.write_text(
                "testWidgets('INT-ABC-HAPPY taps', (tester) async {\n"
                "  await tester.pumpWidget(const Placeholder());\n"
                "  await tester.tap(find.byType(Placeholder));\n"
                "  expect(find.byType(Placeholder), findsOneWidget);\n"
                "});\n",
                encoding="utf-8",
            )
            plan = spec / "interaction_test_plan.json"
            plan.write_text(
                json.dumps({"cases": [{"id": "INT-ABC-HAPPY"}]}),
                encoding="utf-8",
            )
            fingerprints = {
                "planHash": sha256(plan),
                "testHashes": {"feature_test.dart": sha256(test_file)},
            }
            (spec / "interaction_test_evidence.json").write_text(
                json.dumps(
                    {
                        "red": {
                            **fingerprints,
                            "exitCode": 1,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "failure"}},
                        },
                        "green": {
                            **fingerprints,
                            "exitCode": 0,
                            "command": ["flutter", "test", "--machine", "test"],
                            "cases": {"INT-ABC-HAPPY": {"result": "success"}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("no runtime feature unit", result.stdout)

    def test_plan_missing_boundary_and_failure_cases_fails_feature_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            add_runtime_evidence(spec, project, ["INT-ABC-HAPPY"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("INT-ABC-BOUNDARY", result.stdout)
            self.assertIn("INT-ABC-FAILURE", result.stdout)

    def test_plan_case_observable_must_match_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            case_ids = [
                "INT-ABC-HAPPY",
                "INT-ABC-BOUNDARY",
                "INT-ABC-FAILURE",
            ]
            add_runtime_evidence(spec, project, case_ids)
            plan = spec / "interaction_test_plan.json"
            outcomes = {
                "happy": "错误的结果",
                "boundary": "重复点击保持成功页",
                "failure": "显示失败提示",
            }
            plan.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": f"INT-ABC-{variant.upper()}",
                                "interactionId": "INT-ABC",
                                "variant": variant,
                                "action": "点击确认",
                                "expectedObservable": outcomes[variant],
                                "surface": "public_ui",
                            }
                            for variant in ("happy", "boundary", "failure")
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            evidence_path = spec / "interaction_test_evidence.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            for phase in ("red", "green"):
                evidence[phase]["planHash"] = sha256(plan)
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("INT-ABC-HAPPY: expectedObservable mismatch", result.stdout)

    def test_action_target_must_exist_in_current_board_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            add_valid_runtime_evidence(spec, project)
            index = project / ".iff" / "board_index.json"
            index.write_text(json.dumps({"boards": []}), encoding="utf-8")
            anchors_path = spec / "interaction_anchors.json"
            anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
            anchors["inputs"]["index"] = sha256(index)
            anchors_path.write_text(json.dumps(anchors), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("actionTarget not found in board index", result.stdout)

    def test_pending_route_anchor_requires_matching_flow_graph_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            add_valid_runtime_evidence(spec, project)
            anchors_path = spec / "interaction_anchors.json"
            anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
            anchors["anchors"] = [
                {
                    "rule": "INT-ABC",
                    "query": "成功页",
                    "resolution": "unresolved",
                    "candidates": [],
                    "pending_route": True,
                    "targetIntent": "/success",
                }
            ]
            anchors_path.write_text(json.dumps(anchors), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("pending_route missing flow graph edge", result.stdout)

    def test_resolved_cross_board_anchor_requires_flow_graph_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec, project, manifest = make_valid_core(Path(tmp))
            add_valid_runtime_evidence(spec, project)
            anchors_path = spec / "interaction_anchors.json"
            anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
            anchors["anchors"] = [
                {
                    "rule": "INT-ABC",
                    "query": "成功页",
                    "resolution": "unique",
                    "candidates": [
                        {"feature": "feature", "board": "success"}
                    ],
                    "bound": {"feature": "feature", "board": "success"},
                }
            ]
            anchors_path.write_text(json.dumps(anchors), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-root",
                    str(spec),
                    "--project-root",
                    str(project),
                    "--feature-manifest",
                    str(manifest),
                    "--out",
                    str(spec / "interaction_gate_report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("cross-board anchor missing flow graph edge", result.stdout)


if __name__ == "__main__":
    unittest.main()
