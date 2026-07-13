from __future__ import annotations

import json
import os
import base64
import binascii
import hashlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_data_device_tests.py"
CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_data_device_evidence.py"


def png_pixel(red: int, green: int, blue: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes((0, red, green, blue))))
        + chunk(b"IEND", b"")
    )


class RunDataDeviceTestsTest(unittest.TestCase):
    def test_android_runner_writes_recomputable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            lib = project / "lib"
            tests = project / "integration_test"
            lib.mkdir()
            tests.mkdir()
            (project / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            (lib / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            (tests / "data_test.dart").write_text("void main() {}\n", encoding="utf-8")
            bindings = project / "data_slot_bindings.json"
            runtime = project / "data_runtime_manifest.json"
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            fake_flutter = project / "flutter"
            fake_flutter.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if len(sys.argv) > 1 and sys.argv[1] == 'devices':\n"
                "  print(json.dumps([{'id':'emulator-5554','targetPlatform':'android'}]))\n",
                encoding="utf-8",
            )
            os.chmod(fake_flutter, 0o755)
            evidence = project / "data_device_evidence.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--flutter",
                    str(fake_flutter),
                    "--platform",
                    "android",
                    "--device",
                    "emulator-5554",
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--project-root",
                    str(project),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual("run_data_device_tests.py", payload["generator"])
            check_command = [
                sys.executable,
                str(CHECKER),
                "--bindings",
                str(bindings),
                "--runtime-manifest",
                str(runtime),
                "--test-root",
                str(tests),
                "--project-root",
                str(project),
                "--evidence",
                str(evidence),
            ]
            checked = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            (lib / "main.dart").write_text("void main() { print('changed'); }\n", encoding="utf-8")
            stale = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("stale device appHashes", stale.stdout + stale.stderr)
            (lib / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            payload["command"] = ["flutter", "test", "--machine", "-d", "chrome", str(tests)]
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            wrong_command = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, wrong_command.returncode)
            self.assertIn("command/device mismatch", wrong_command.stdout + wrong_command.stderr)

    def test_slot_runner_persists_two_distinct_flutter_screenshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            lib = project / "lib"
            tests = project / "integration_test"
            lib.mkdir()
            tests.mkdir()
            (project / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            (lib / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            (tests / "data_test.dart").write_text(
                "testWidgets('DATA-SLOT:amount-node device', (tester) async {"
                " final binding = IntegrationTestWidgetsFlutterBinding.instance;"
                " app.main();"
                " await binding.convertFlutterSurfaceToImage();"
                " const fieldPath = '$.amount';"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 10}));"
                " expect(find.byKey(const ValueKey('iff:amount-node')), findsOneWidget);"
                " expect(find.text('₦10'), findsOneWidget);"
                " final firstPng = await binding.takeScreenshot('DATA-SLOT:amount-node:1');"
                " print('IFF_DATA_CAPTURE|DATA-SLOT:amount-node|1|${base64Encode(firstPng)}');"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 20}));"
                " expect(find.text('₦20'), findsOneWidget);"
                " final secondPng = await binding.takeScreenshot('DATA-SLOT:amount-node:2');"
                " print('IFF_DATA_CAPTURE|DATA-SLOT:amount-node|2|${base64Encode(secondPng)}');"
                "});\n",
                encoding="utf-8",
            )
            bindings = project / "data_slot_bindings.json"
            runtime = project / "data_runtime_manifest.json"
            bindings.write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "amount-node",
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
                    }
                ),
                encoding="utf-8",
            )
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            first = base64.b64encode(png_pixel(255, 0, 0)).decode("ascii")
            second = base64.b64encode(png_pixel(0, 0, 255)).decode("ascii")
            fake_flutter = project / "flutter"
            fake_flutter.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if len(sys.argv) > 1 and sys.argv[1] == 'devices':\n"
                "  print(json.dumps([{'id':'emulator-5554','targetPlatform':'android'}]))\n"
                "else:\n"
                "  print(json.dumps({'type':'testStart','test':{'id':1,'name':'DATA-SLOT:amount-node device'}}))\n"
                f"  print('IFF_DATA_CAPTURE|DATA-SLOT:amount-node|1|{first}')\n"
                f"  print('IFF_DATA_CAPTURE|DATA-SLOT:amount-node|2|{second}')\n"
                "  print(json.dumps({'type':'testDone','testID':1,'result':'success','skipped':False}))\n",
                encoding="utf-8",
            )
            os.chmod(fake_flutter, 0o755)
            evidence = project / "data_device_evidence.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--flutter",
                    str(fake_flutter),
                    "--platform",
                    "android",
                    "--device",
                    "emulator-5554",
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--project-root",
                    str(project),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(2, len(payload["captures"]))
            self.assertEqual(2, len({capture["sha256"] for capture in payload["captures"]}))
            check_command = [
                sys.executable,
                str(CHECKER),
                "--bindings",
                str(bindings),
                "--runtime-manifest",
                str(runtime),
                "--test-root",
                str(tests),
                "--project-root",
                str(project),
                "--evidence",
                str(evidence),
            ]
            checked = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            valid_payload = json.loads(json.dumps(payload))
            test_file = tests / "data_test.dart"
            valid_source = test_file.read_text(encoding="utf-8")
            test_file.write_text(valid_source.replace(" app.main();", ""), encoding="utf-8")
            payload["testHashes"] = {
                "data_test.dart": hashlib.sha256(test_file.read_bytes()).hexdigest()
            }
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            no_entry = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, no_entry.returncode)
            self.assertIn("does not start app.main", no_entry.stdout + no_entry.stderr)
            test_file.write_text(valid_source, encoding="utf-8")
            evidence.write_text(json.dumps(valid_payload), encoding="utf-8")
            payload = json.loads(json.dumps(valid_payload))
            no_capture_source = valid_source.replace(
                "await binding.takeScreenshot('DATA-SLOT:amount-node:1')",
                "<int>[]",
            ).replace(
                "await binding.takeScreenshot('DATA-SLOT:amount-node:2')",
                "<int>[]",
            )
            test_file.write_text(no_capture_source, encoding="utf-8")
            payload["testHashes"] = {
                "data_test.dart": hashlib.sha256(test_file.read_bytes()).hexdigest()
            }
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            no_capture_source_result = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, no_capture_source_result.returncode)
            self.assertIn(
                "missing automated screenshot source",
                no_capture_source_result.stdout + no_capture_source_result.stderr,
            )
            test_file.write_text(valid_source, encoding="utf-8")
            evidence.write_text(json.dumps(valid_payload), encoding="utf-8")
            payload = json.loads(json.dumps(valid_payload))
            repeated_input_source = valid_source.replace("{'amount': 20}", "{'amount': 10}")
            test_file.write_text(repeated_input_source, encoding="utf-8")
            payload["testHashes"] = {
                "data_test.dart": hashlib.sha256(test_file.read_bytes()).hexdigest()
            }
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            repeated_input = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, repeated_input.returncode)
            self.assertIn(
                "needs two distinct bound field inputs",
                repeated_input.stdout + repeated_input.stderr,
            )
            test_file.write_text(valid_source, encoding="utf-8")
            evidence.write_text(json.dumps(valid_payload), encoding="utf-8")
            payload = json.loads(json.dumps(valid_payload))
            payload["cases"] = {}
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            missing_case = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, missing_case.returncode)
            self.assertIn("missing successful device case", missing_case.stdout + missing_case.stderr)
            evidence.write_text(json.dumps(valid_payload), encoding="utf-8")
            payload = json.loads(json.dumps(valid_payload))
            payload["captures"] = payload["captures"][:1]
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            missing_capture = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, missing_capture.returncode)
            self.assertIn("requires 2 current capture(s)", missing_capture.stdout + missing_capture.stderr)
            evidence.write_text(json.dumps(valid_payload), encoding="utf-8")
            payload = json.loads(json.dumps(valid_payload))
            Path(payload["captures"][0]["path"]).write_bytes(png_pixel(0, 255, 0))
            stale = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("stale device capture", stale.stdout + stale.stderr)

    def test_state_runner_binds_capture_to_exact_runtime_observable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            lib = project / "lib"
            tests = project / "integration_test"
            lib.mkdir()
            tests.mkdir()
            (project / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
            (lib / "main.dart").write_text("void main() {}\n", encoding="utf-8")
            test_file = tests / "data_test.dart"
            source = (
                "testWidgets('DATA-STATE:fetchLoan:loading device', (tester) async {"
                " final binding = IntegrationTestWidgetsFlutterBinding.instance;"
                " app.main();"
                " await binding.convertFlutterSurfaceToImage();"
                " expect(find.byKey(const ValueKey('iff:loan-loading')), findsOneWidget);"
                " expect(find.text('Loading loan'), findsOneWidget);"
                " final png = await binding.takeScreenshot('DATA-STATE:fetchLoan:loading:1');"
                " print('IFF_DATA_CAPTURE|DATA-STATE:fetchLoan:loading|1|${base64Encode(png)}');"
                "});\n"
            )
            test_file.write_text(source, encoding="utf-8")
            bindings = project / "data_slot_bindings.json"
            runtime = project / "data_runtime_manifest.json"
            bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            runtime.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "id": "fetchLoan",
                                "requiredStates": ["loading"],
                                "stateTargets": {
                                    "loading": {
                                        "key": "iff:loan-loading",
                                        "text": "Loading loan",
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            capture = base64.b64encode(png_pixel(255, 255, 0)).decode("ascii")
            fake_flutter = project / "flutter"
            fake_flutter.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if len(sys.argv) > 1 and sys.argv[1] == 'devices':\n"
                "  print(json.dumps([{'id':'emulator-5554','targetPlatform':'android'}]))\n"
                "else:\n"
                "  print(json.dumps({'type':'testStart','test':{'id':1,'name':'DATA-STATE:fetchLoan:loading device'}}))\n"
                f"  print('IFF_DATA_CAPTURE|DATA-STATE:fetchLoan:loading|1|{capture}')\n"
                "  print(json.dumps({'type':'testDone','testID':1,'result':'success','skipped':False}))\n",
                encoding="utf-8",
            )
            os.chmod(fake_flutter, 0o755)
            evidence = project / "data_device_evidence.json"
            run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--flutter",
                    str(fake_flutter),
                    "--platform",
                    "android",
                    "--device",
                    "emulator-5554",
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                    "--project-root",
                    str(project),
                    "--evidence",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            check_command = [
                sys.executable,
                str(CHECKER),
                "--bindings",
                str(bindings),
                "--runtime-manifest",
                str(runtime),
                "--test-root",
                str(tests),
                "--project-root",
                str(project),
                "--evidence",
                str(evidence),
            ]
            checked = subprocess.run(check_command, capture_output=True, text=True, check=False)
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            current_payload = json.loads(json.dumps(payload))
            test_file.write_text(
                source.replace(" await binding.convertFlutterSurfaceToImage();", ""),
                encoding="utf-8",
            )
            payload["testHashes"] = {
                "data_test.dart": hashlib.sha256(test_file.read_bytes()).hexdigest()
            }
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            no_surface = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, no_surface.returncode)
            self.assertIn(
                "Android screenshot surface not converted",
                no_surface.stdout + no_surface.stderr,
            )
            payload = current_payload
            test_file.write_text(source.replace("Loading loan", "Please wait"), encoding="utf-8")
            payload["testHashes"] = {
                "data_test.dart": hashlib.sha256(test_file.read_bytes()).hexdigest()
            }
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            wrong_state = subprocess.run(
                check_command,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, wrong_state.returncode)
            self.assertIn("missing visible state text Loading loan", wrong_state.stdout + wrong_state.stderr)


if __name__ == "__main__":
    unittest.main()
