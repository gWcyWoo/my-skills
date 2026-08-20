from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from icp.implementation.scripts import android_visual_driver as driver


class AndroidVisualDriverTest(unittest.TestCase):
    def test_cold_start_resolves_launcher_before_force_stop_and_starts_it_explicitly(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run_adb(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
            commands.append(args)
            if args[:4] == ("shell", "cmd", "package", "resolve-activity"):
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout="test.app/.MainActivity\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="Status: ok\n", stderr="")

        def fake_probe(*args: str) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("shell", "pidof"):
                return subprocess.CompletedProcess(args, 0, stdout="123\n", stderr="")
            if args[:3] == ("shell", "dumpsys", "activity"):
                return subprocess.CompletedProcess(
                    args, 0, stdout="mResumedActivity test.app/.MainActivity\n", stderr=""
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(driver, "run_adb", side_effect=fake_run_adb), patch.object(
            driver, "probe_adb", side_effect=fake_probe
        ):
            driver.cold_start("test.app")

        resolve = next(
            command
            for command in commands
            if command[:4] == ("shell", "cmd", "package", "resolve-activity")
        )
        force_stop = ("shell", "am", "force-stop", "test.app")
        start = next(command for command in commands if command[:3] == ("shell", "am", "start"))
        self.assertLess(commands.index(resolve), commands.index(force_stop))
        self.assertLess(commands.index(force_stop), commands.index(start))
        self.assertEqual(
            start,
            ("shell", "am", "start", "-W", "-n", "test.app/.MainActivity"),
        )

    def test_cold_start_does_not_inject_a_terminal_visual_state(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run_adb(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
            commands.append(args)
            if args[:4] == ("shell", "cmd", "package", "resolve-activity"):
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout="test.app/.MainActivity\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="Status: ok\n", stderr="")

        def fake_probe(*args: str) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("shell", "pidof"):
                return subprocess.CompletedProcess(args, 0, stdout="123\n", stderr="")
            if args[:3] == ("shell", "dumpsys", "activity"):
                return subprocess.CompletedProcess(
                    args, 0, stdout="mResumedActivity test.app/.MainActivity\n", stderr=""
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(driver, "run_adb", side_effect=fake_run_adb), patch.object(
            driver, "probe_adb", side_effect=fake_probe
        ):
            evidence = driver.cold_start("test.app")

        start = next(command for command in commands if command[:3] == ("shell", "am", "start"))
        self.assertNotIn("icp_state", start)
        self.assertNotIn("--es", start)
        self.assertEqual(
            set(evidence),
            {"activity_resumed", "process_alive", "no_fatal_exception", "fatal_log_tail"},
        )

    def test_measurement_payload_must_match_the_frozen_probe_contract(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "assertions": [
                {
                    "assertion_id": "assertion-a",
                    "probe_tag": "probe-a",
                    "kind": "bounds",
                    "expected": {"left": 4, "top": 8, "width": 52, "height": 52},
                }
            ],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "probes": [
                {
                    "probe_tag": "probe-a",
                    "bounds": {"left": 4, "top": 8, "width": 52, "height": 52},
                }
            ],
        }

        measured = driver.measure_payload(contract, payload)

        self.assertEqual(
            measured,
            {
                "schema": "icp.visual-measurements.v1",
                "visual_state_id": "state-a",
                "root_tag": "root-state-a",
                "measurements": [
                    {
                        "assertion_id": "assertion-a",
                        "probe_tag": "probe-a",
                        "kind": "bounds",
                        "actual": {"left": 4, "top": 8, "width": 52, "height": 52},
                    }
                ],
            },
        )

    def test_measure_rejects_a_probe_payload_not_present_in_the_live_hierarchy(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "assertions": [
                {
                    "assertion_id": "assertion-a",
                    "probe_tag": "target-permission-icon",
                    "kind": "bounds",
                    "expected": {"left": 4, "top": 8, "width": 52, "height": 52},
                }
            ],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "probes": [
                {
                    "probe_tag": "target-permission-icon",
                    "bounds": {"left": 4, "top": 8, "width": 52, "height": 52},
                }
            ],
        }

        with patch.object(
            driver,
            "load_json",
            return_value=contract,
        ), patch.object(
            driver,
            "shell_text",
            return_value=json.dumps(payload),
        ), patch.object(
            driver,
            "window_hierarchy",
            return_value=(
                '<hierarchy><node content-desc="root-state-a" '
                'bounds="[0,0][1080,1920]" /></hierarchy>'
            ),
        ):
            with self.assertRaisesRegex(
                driver.DriverError,
                "runtime probe is not visible: target-permission-icon",
            ):
                driver.measure("test.app", "contract.json")

    def test_measure_keeps_accepting_a_probe_present_in_the_live_hierarchy(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "assertions": [
                {
                    "assertion_id": "assertion-a",
                    "probe_tag": "target-permission-icon",
                    "kind": "bounds",
                    "expected": {"left": 4, "top": 8, "width": 52, "height": 52},
                }
            ],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "probes": [
                {
                    "probe_tag": "target-permission-icon",
                    "bounds": {"left": 4, "top": 8, "width": 52, "height": 52},
                }
            ],
        }

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver,
            "shell_text",
            return_value=json.dumps(payload),
        ), patch.object(
            driver,
            "window_hierarchy",
            return_value=(
                '<hierarchy><node content-desc="target-permission-icon" '
                'bounds="[4,8][56,60]" /></hierarchy>'
            ),
        ):
            measured = driver.measure("test.app", "contract.json")

        self.assertEqual(measured, driver.measure_payload(contract, payload))


if __name__ == "__main__":
    unittest.main()
