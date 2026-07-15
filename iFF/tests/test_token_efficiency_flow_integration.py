from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from iFF.tests.test_check_done_gate import (
    board_inputs_hash,
    make_valid_feature,
    sha256,
    write_json,
)
from iFF.tests.test_check_interaction_feature import (
    add_valid_runtime_evidence,
    make_valid_core,
)
from iFF.tests.model_context_fixture import prepare_v3_context
from iFF.tests.png_fixture import write_png


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"


def run(script: str, *args: object, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def make_fake_fetch_scripts(root: Path) -> Path:
    skill = root / "fake-skill"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    body = """#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1]
if name == 'fetch.py':
    url = value('--url')
    if os.environ.get('IFF_FAIL_URL') and os.environ['IFF_FAIL_URL'] in url:
        raise SystemExit(7)
    suffix = url.rsplit('/', 1)[-1]
    board = pathlib.Path(value('--parent-dir')) / f'board-{suffix}'
    board.mkdir(parents=True, exist_ok=True)
    raw = board / 'raw.json'
    raw.write_text('{}')
    print(json.dumps({'raw_json': str(raw), 'dir': str(board), 'design_name': f'board-{suffix}'}))
elif name == 'check_figma_scene.py':
    raise SystemExit(0)
else:
    flag = '--output' if '--output' in args else '--out'
    out = pathlib.Path(value(flag))
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix == '.json':
        out.write_text('{}')
    elif out.suffix == '.png':
        out.write_bytes(b'png')
    else:
        out.write_text('generated')
"""
    for name in (
        "fetch.py",
        "write.py",
        "download_cover.py",
        "classify_design.py",
        "export_figma_scene.py",
        "check_figma_scene.py",
        "export_tokens.py",
        "export_assets_manifest.py",
        "group_figma_layout.py",
    ):
        path = scripts / name
        path.write_text(body, encoding="utf-8")
        os.chmod(path, 0o755)
    return skill


def prepare_done_gate_fixture(tmp: Path) -> tuple[Path, Path, Path, Path]:
    root, project, manifest = make_valid_core(tmp)
    make_valid_feature(root, include_legacy_interaction=False)
    write_json(
        manifest,
        {
            "featureId": "feature",
            "states": {
                "default": {
                    "board": "default",
                    "canvasPath": "lib/default_canvas.dart",
                    "generatedFiles": ["lib/default_canvas.dart"],
                }
            },
        },
    )
    state_machine = root / "state_machine.json"
    machine_doc = json.loads(state_machine.read_text(encoding="utf-8"))
    machine_doc["inputs"]["boards"] = board_inputs_hash(root)
    machine_doc["inputs"]["featureManifest"] = sha256(manifest)
    write_json(state_machine, machine_doc)
    add_valid_runtime_evidence(root, project)
    wiring = run(
        "check_interaction_wiring.py",
        "--lib-root",
        project / "lib",
        "--test-root",
        project / "test",
        "--entry",
        project / "lib/main.dart",
        "--pubspec",
        project / "pubspec.yaml",
        "--contract",
        root / "interaction_contract.json",
        "--out",
        root / "default/wiring_report.json",
    )
    if wiring.returncode != 0:
        raise AssertionError(wiring.stdout + wiring.stderr)
    interaction = run(
        "check_interaction_feature.py",
        "--spec-root",
        root,
        "--project-root",
        project,
        "--feature-manifest",
        manifest,
        "--out",
        root / "default/interaction_gate_report.json",
    )
    if interaction.returncode != 0:
        raise AssertionError(interaction.stdout + interaction.stderr)
    changed = tmp / "changed-files.txt"
    changed.write_text("lib/default_canvas.dart\n", encoding="utf-8")
    return root, project, manifest, changed


class TokenEfficiencyFlowIntegrationTest(unittest.TestCase):
    def test_fetch_cli_runs_every_board_and_reports_partial_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = make_fake_fetch_scripts(root)
            row = root / "row.json"
            write_json(
                row,
                {
                    "title": "home",
                    "design_url": "https://design/1；https://design/2\nhttps://design/3",
                },
            )
            spec = root / "spec/home"
            report = root / "fetch_report.json"
            success = run(
                "run_fetch_pipeline.py",
                "--skill-dir",
                skill,
                "--row-json",
                row,
                "--spec-root",
                spec,
                "--out",
                report,
            )
            self.assertEqual(0, success.returncode, success.stdout + success.stderr)
            self.assertEqual(3, len(json.loads(report.read_text(encoding="utf-8"))["boards"]))

            failed_report = root / "fetch_failed_report.json"
            env = os.environ.copy()
            env["IFF_FAIL_URL"] = "/2"
            partial = run(
                "run_fetch_pipeline.py",
                "--skill-dir",
                skill,
                "--row-json",
                row,
                "--spec-root",
                root / "spec/partial",
                "--out",
                failed_report,
                env=env,
            )
            self.assertNotEqual(0, partial.returncode)
            payload = json.loads(failed_report.read_text(encoding="utf-8"))
            self.assertEqual([True, False, True], [item["ok"] for item in payload["boards"]])

    def test_preflight_prompt_and_receipt_are_recomputed_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            feature = project / "spec/home"
            board = feature / "default"
            board.mkdir(parents=True)
            manifest = project / ".iff/features/home.json"
            write_json(
                manifest,
                {
                    "featureId": "home",
                    "states": {
                        "default": {
                            "board": "default",
                            "canvasPath": "lib/default_canvas.dart",
                            "generatedFiles": ["lib/default_canvas.dart"],
                        }
                    },
                },
            )
            row = feature / "row.json"
            write_json(row, {"title": "home", "design_url": "https://design/1"})
            preflight = project / ".iff/preflight_report.json"
            checked = run(
                "verify_pipeline_scripts.py",
                "--skill-dir",
                SKILL_DIR,
                "--out",
                preflight,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

            for mode, spec, worker_id in (
                ("board", board, "board--default"),
                ("assembly", feature, "assembly"),
            ):
                prompt = feature / ".iff/workers" / f"{worker_id}.prompt.md"
                made = run(
                    "make_worker_prompt.py",
                    "--skill-dir",
                    SKILL_DIR,
                    "--row-json",
                    row,
                    "--spec-dir",
                    spec,
                    "--project-root",
                    project,
                    "--mode",
                    mode,
                    "--feature-manifest",
                    manifest,
                    "--preflight-report",
                    preflight,
                    "--out",
                    prompt,
                )
                self.assertEqual(0, made.returncode, made.stdout + made.stderr)
                output = spec / f"{worker_id}.output.json"
                write_json(output, {"ok": True})
                result = feature / ".iff/workers" / f"{worker_id}.result.json"
                write_json(result, {"outputs": [str(output)]})
                contract = feature / ".iff/workers" / f"{worker_id}.contract.json"
                receipt = feature / ".iff/workers" / f"{worker_id}.receipt.json"
                completed = run(
                    "complete_worker.py",
                    "--skill-dir",
                    SKILL_DIR,
                    "--feature-manifest",
                    manifest,
                    "--contract-input",
                    contract,
                    "--result",
                    result,
                    "--out",
                    receipt,
                )
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                valid = run(
                    "check_worker_compliance.py",
                    "--skill-dir",
                    SKILL_DIR,
                    "--feature-manifest",
                    manifest,
                    "--manifest",
                    receipt,
                )
                self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)

            receipt = feature / ".iff/workers/board--default.receipt.json"
            copied = feature / ".iff/workers/copied.receipt.json"
            shutil.copy2(receipt, copied)
            wrong_path = run(
                "check_worker_compliance.py",
                "--skill-dir",
                SKILL_DIR,
                "--feature-manifest",
                manifest,
                "--manifest",
                copied,
            )
            self.assertNotEqual(0, wrong_path.returncode)
            self.assertIn("receipt path", wrong_path.stdout + wrong_path.stderr)

            prompt = feature / ".iff/workers/board--default.prompt.md"
            prompt.write_text("edited after generation\n", encoding="utf-8")
            stale = run(
                "check_worker_compliance.py",
                "--skill-dir",
                SKILL_DIR,
                "--feature-manifest",
                manifest,
                "--manifest",
                receipt,
            )
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("canonical contract", stale.stdout + stale.stderr)

            legacy = feature / ".iff/workers/legacy.receipt.json"
            write_json(legacy, {"worker_contract_version": "IFF_WORKER_CONTRACT v2"})
            rejected = run(
                "check_worker_compliance.py",
                "--skill-dir",
                SKILL_DIR,
                "--feature-manifest",
                manifest,
                "--manifest",
                legacy,
            )
            self.assertNotEqual(0, rejected.returncode)

    def test_model_context_requires_component_cardinality_and_discloses_metric_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, spec, out, manifest = prepare_v3_context(Path(tmp))
            component = project / ".iff/component_model_packet.json"
            component_bytes = component.read_bytes()
            component.unlink()
            result = run(
                "check_model_context.py",
                "--skill-dir",
                SKILL_DIR,
                "--spec-root",
                spec,
                "--project-root",
                project,
                "--feature-manifest",
                manifest,
                "--out",
                out,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("component_model_packet.json missing", result.stdout + result.stderr)

            component.write_bytes(component_bytes)
            rerun = run(
                "check_model_context.py",
                "--skill-dir",
                SKILL_DIR,
                "--spec-root",
                spec,
                "--project-root",
                project,
                "--feature-manifest",
                manifest,
                "--out",
                out,
            )
            self.assertEqual(0, rerun.returncode, rerun.stdout + rerun.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("currentRetainedInputBytes", report)
            self.assertIn("generatedInputBytes", report)
            self.assertIn("controlledBaselineBytes", report)
            self.assertTrue(report["unmeasuredChannels"])

    def test_allowed_decision_is_atomic_and_stale_or_forbidden_decisions_do_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "implementation_plan.json"
            write_json(
                plan,
                {
                    "components": {"footer": {"family": "__MODEL__"}},
                    "modelFields": [{"path": "components.footer.family"}],
                },
            )
            packet = root / "visual_model_packet.json"
            write_json(
                packet,
                {
                    "version": 2,
                    "kind": "visual",
                    "scope": {"feature": "home", "board": "default"},
                    "sources": {
                        "implementationPlan": {
                            "path": str(plan),
                            "sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                        }
                    },
                    "action": {
                        "kind": "fill_plan_judgment",
                        "target": "components.footer.family",
                        "allowedDecisions": ["reuse", "independent"],
                    },
                },
            )
            decision = root / "decision.json"
            write_json(decision, {"kind": "reuse", "value": "shared-footer"})
            applied = run(
                "apply_model_decision.py",
                "--packet",
                packet,
                "--decision",
                decision,
            )
            self.assertEqual(0, applied.returncode, applied.stdout + applied.stderr)
            self.assertEqual(
                "shared-footer",
                json.loads(plan.read_text(encoding="utf-8"))["components"]["footer"]["family"],
            )

            before = plan.read_bytes()
            write_json(decision, {"kind": "invent", "value": "bad"})
            forbidden = run(
                "apply_model_decision.py",
                "--packet",
                packet,
                "--decision",
                decision,
            )
            self.assertNotEqual(0, forbidden.returncode)
            self.assertEqual(before, plan.read_bytes())

    def test_combined_device_runner_uses_one_flutter_test_for_both_evidence_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "lib").mkdir()
            tests = project / "integration_test"
            tests.mkdir()
            (project / "lib/main.dart").write_text("void main() {}\n", encoding="utf-8")
            (project / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            (tests / "feature_test.dart").write_text(
                "testWidgets('DATA-SLOT:amount device', (tester) async {"
                " final binding = IntegrationTestWidgetsFlutterBinding.instance;"
                " app.main();"
                " await binding.convertFlutterSurfaceToImage();"
                " const fieldPath = '$.amount';"
                " await tester.pumpWidget(const App(response: {'amount': 10}));"
                " expect(find.byKey(const ValueKey('iff:amount')), findsOneWidget);"
                " expect(find.text('10'), findsOneWidget);"
                " final firstPng = await binding.takeScreenshot('DATA-SLOT:amount:1');"
                " print('IFF_DATA_CAPTURE|DATA-SLOT:amount|1|${base64Encode(firstPng)}');"
                " await tester.pumpWidget(const App(response: {'amount': 20}));"
                " expect(find.text('20'), findsOneWidget);"
                " final secondPng = await binding.takeScreenshot('DATA-SLOT:amount:2');"
                " print('IFF_DATA_CAPTURE|DATA-SLOT:amount|2|${base64Encode(secondPng)}');"
                "});\n",
                encoding="utf-8",
            )
            plan = project / "interaction_test_plan.json"
            write_json(plan, {"cases": [{"id": "INT-001-HAPPY"}]})
            bindings = project / "data_slot_bindings.json"
            runtime = project / "data_runtime_manifest.json"
            write_json(
                bindings,
                {
                    "bindings": [
                        {
                            "node": "amount",
                            "binding": {
                                "field": {
                                    "endpoint": "/loan",
                                    "method": "GET",
                                    "status": "200",
                                    "jsonPath": "$.amount",
                                    "type": "number",
                                }
                            },
                            "confirmedByModel": True,
                        }
                    ]
                },
            )
            write_json(runtime, {"operations": []})
            first_png = project / "first.png"
            second_png = project / "second.png"
            write_png(first_png, 255, 0, 0)
            write_png(second_png, 0, 0, 255)
            first_capture = base64.b64encode(first_png.read_bytes()).decode("ascii")
            second_capture = base64.b64encode(second_png.read_bytes()).decode("ascii")
            log = project / "flutter.log"
            fake_flutter = project / "flutter"
            fake_flutter.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                f"log = pathlib.Path({str(log)!r})\n"
                "log.write_text(log.read_text() + ' '.join(sys.argv[1:]) + '\\n' if log.exists() else ' '.join(sys.argv[1:]) + '\\n')\n"
                "if sys.argv[1] == 'devices':\n"
                "  print(json.dumps([{'id':'emulator-5554','targetPlatform':'android'}]))\n"
                "else:\n"
                "  print(json.dumps({'type':'testStart','test':{'id':1,'name':'INT-001-HAPPY'}}))\n"
                "  print(json.dumps({'type':'testDone','testID':1,'result':'success','skipped':False}))\n"
                "  print(json.dumps({'type':'testStart','test':{'id':2,'name':'DATA-SLOT:amount'}}))\n"
                f"  print('IFF_DATA_CAPTURE|DATA-SLOT:amount|1|{first_capture}')\n"
                f"  print('IFF_DATA_CAPTURE|DATA-SLOT:amount|2|{second_capture}')\n"
                "  print(json.dumps({'type':'testDone','testID':2,'result':'success','skipped':False}))\n",
                encoding="utf-8",
            )
            os.chmod(fake_flutter, 0o755)
            interaction_evidence = project / "interaction_device_evidence.json"
            data_evidence = project / "data_device_evidence.json"
            result = run(
                "run_client_device_tests.py",
                "--flutter",
                fake_flutter,
                "--platform",
                "android",
                "--device",
                "emulator-5554",
                "--interaction-plan",
                plan,
                "--bindings",
                bindings,
                "--runtime-manifest",
                runtime,
                "--test-root",
                tests,
                "--project-root",
                project,
                "--interaction-evidence",
                interaction_evidence,
                "--data-evidence",
                data_evidence,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            commands = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, sum(line.startswith("test ") for line in commands))
            interaction = json.loads(interaction_evidence.read_text(encoding="utf-8"))
            data = json.loads(data_evidence.read_text(encoding="utf-8"))
            self.assertEqual(interaction["command"], data["command"])
            self.assertEqual(interaction["stdoutHash"], data["stdoutHash"])
            self.assertEqual(2, len(data["captures"]))
            self.assertEqual(2, len({item["sha256"] for item in data["captures"]}))
            checked = run(
                "check_data_device_evidence.py",
                "--bindings",
                bindings,
                "--runtime-manifest",
                runtime,
                "--test-root",
                tests,
                "--project-root",
                project,
                "--evidence",
                data_evidence,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_done_gate_rejects_synthetic_visual_reports_and_non_png_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _, manifest, changed = prepare_done_gate_fixture(Path(tmp))
            (root / "default/actual.png").write_bytes(b"synthetic screenshot")
            result = run(
                "check_done_gate.py",
                "--spec-root",
                root,
                "--feature-manifest",
                manifest,
                "--state-key",
                "default",
                "--changed-files",
                changed,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("PNG", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
