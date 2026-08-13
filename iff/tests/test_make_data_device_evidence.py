from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_data_device_evidence.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_capture(root: Path, name: str, source: str = "simulator_screenshot") -> Path:
    screenshot = root / f"{name}.png"
    manifest = root / f"{name}.manifest.json"
    screenshot.write_bytes(f"PNG:{name}".encode())
    write_json(
        manifest,
        {
            "actual_source": source,
            "device_id": "emulator-5554",
            "project_root": str(root.resolve()),
            "app_hashes": {"main.dart": sha256(root / "lib" / "main.dart")},
            "launch_command": [
                "flutter",
                "run",
                "-d",
                "emulator-5554",
                "--debug",
                "--no-resident",
            ],
            "capture_command": (
                "adb -s emulator-5554 shell screencap -p /sdcard/iff_actual.png"
            ),
            "actual_path": str(screenshot),
        },
    )
    return manifest


class MakeDataDeviceEvidenceTest(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, Path, Path, list[str]]:
        bindings = root / "bindings.json"
        runtime = root / "runtime.json"
        observations = root / "observations.json"
        app = root / "lib"
        app.mkdir()
        (app / "main.dart").write_text("void main() {}\n", encoding="utf-8")
        write_json(
            bindings,
            {
                "bindings": [
                    {
                        "node": "amount-node",
                        "binding": {"field": {"jsonPath": "$.amount"}},
                    }
                ]
            },
        )
        write_json(
            runtime,
            {
                "operations": [
                    {"id": "fetchLoan", "requiredStates": ["success"]}
                ]
            },
        )
        cases = ["DATA-SLOT:amount-node", "DATA-STATE:fetchLoan:success"]
        return bindings, runtime, observations, app, cases

    def test_compiles_current_client_device_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings, runtime, observations, app, cases = self.prepare(root)
            first = make_capture(root, "amount-10")
            second = make_capture(root, "amount-20")
            write_json(
                observations,
                {
                    "platform": "android",
                    "deviceId": "emulator-5554",
                    "cases": {
                        cases[0]: {
                            "result": "success",
                            "skipped": False,
                            "action": "open real loan page with amount 10, then 20",
                            "inputValues": [10, 20],
                            "observed": ["₦10", "₦20"],
                            "captureManifests": [str(first), str(second)],
                        },
                        cases[1]: {
                            "result": "success",
                            "skipped": False,
                            "action": "open real loan page in success state",
                            "observed": ["loan success content"],
                            "captureManifests": [str(second)],
                        },
                    },
                },
            )
            out = root / "device_evidence.json"

            command = [
                sys.executable,
                str(SCRIPT),
                "--bindings",
                str(bindings),
                "--runtime-manifest",
                str(runtime),
                "--app-root",
                str(app),
                "--observations",
                str(observations),
                "--out",
                str(out),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("android", payload["platform"])
            self.assertEqual("emulator-5554", payload["deviceId"])
            self.assertEqual("$.amount", payload["fields"][cases[0]]["jsonPath"])
            self.assertEqual(2, len(payload["captures"]))
            self.assertEqual(sha256(bindings), payload["bindingsHash"])

            (app / "main.dart").write_text("void main() { print('changed'); }\n")
            stale = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("capture app differs", stale.stdout + stale.stderr)

    def test_slot_requires_two_inputs_two_visible_values_and_two_captures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings, runtime, observations, app, cases = self.prepare(root)
            first = make_capture(root, "one")
            write_json(
                observations,
                {
                    "platform": "android",
                    "deviceId": "emulator-5554",
                    "cases": {
                        cases[0]: {
                            "result": "success",
                            "skipped": False,
                            "action": "open client page twice",
                            "inputValues": [10, 10],
                            "observed": ["₦10", "₦10"],
                            "captureManifests": [str(first)],
                        },
                        cases[1]: {
                            "result": "success",
                            "skipped": False,
                            "action": "open success state",
                            "observed": ["success"],
                            "captureManifests": [str(first)],
                        },
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--app-root",
                    str(app),
                    "--observations",
                    str(observations),
                    "--out",
                    str(root / "out.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("two distinct", result.stdout + result.stderr)

    def test_non_simulator_capture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings, runtime, observations, app, cases = self.prepare(root)
            invalid = make_capture(root, "fake", source="widget_golden")
            write_json(
                observations,
                {
                    "platform": "android",
                    "deviceId": "emulator-5554",
                    "cases": {
                        cases[0]: {
                            "result": "success",
                            "skipped": False,
                            "action": "open client page twice",
                            "inputValues": [10, 20],
                            "observed": ["₦10", "₦20"],
                            "captureManifests": [str(invalid), str(invalid)],
                        },
                        cases[1]: {
                            "result": "success",
                            "skipped": False,
                            "action": "open success state",
                            "observed": ["success"],
                            "captureManifests": [str(invalid)],
                        },
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--app-root",
                    str(app),
                    "--observations",
                    str(observations),
                    "--out",
                    str(root / "out.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("simulator_screenshot", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
