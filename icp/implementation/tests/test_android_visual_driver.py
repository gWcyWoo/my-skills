from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from icp.implementation.scripts import android_visual_driver as driver


class AndroidVisualDriverTest(unittest.TestCase):
    def test_cold_start_does_not_inject_a_terminal_visual_state(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run_adb(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
            commands.append(args)
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


if __name__ == "__main__":
    unittest.main()
