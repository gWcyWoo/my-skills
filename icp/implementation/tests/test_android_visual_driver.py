from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icp.implementation.scripts import android_visual_driver as driver


class AndroidVisualDriverTest(unittest.TestCase):
    def build_typography_apk(self, values: dict[str, str]) -> Path:
        temporary = Path(tempfile.mkdtemp(prefix="icp-apk-typography-"))
        manifest = temporary / "AndroidManifest.xml"
        resources = temporary / "res" / "values"
        resources.mkdir(parents=True)
        manifest.write_text(
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
            'package="test.app"><application /></manifest>',
            encoding="utf-8",
        )
        (resources / "dimens.xml").write_text(
            "<resources>"
            + "".join(
                f'<dimen name="{name}">{value}</dimen>'
                for name, value in values.items()
            )
            + "</resources>",
            encoding="utf-8",
        )
        sdk = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "Library/Android/sdk"))
        aapt2 = sorted((sdk / "build-tools").glob("*/aapt2"))[-1]
        android_jar = sorted((sdk / "platforms").glob("*/android.jar"))[-1]
        compiled = temporary / "compiled.zip"
        apk = temporary / "fixture.apk"
        subprocess.run(
            [str(aapt2), "compile", "--dir", str(temporary / "res"), "-o", str(compiled)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                str(aapt2),
                "link",
                "-I",
                str(android_jar),
                "--manifest",
                str(manifest),
                "-o",
                str(apk),
                str(compiled),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return apk

    def test_window_insets_are_derived_from_device_state_not_the_app_payload(self) -> None:
        observed = driver.parse_device_window_insets(
            "Physical size: 1440x3200\nOverride size: 1080x2400\n",
            (
                "InsetsSource type=statusBars frame=[0,0][1080,72] visible=true\n"
                "InsetsSource type=navigationBars frame=[0,2328][1080,2400] visible=true\n"
            ),
            "3",
        )

        self.assertEqual(
            observed,
            {
                "safe_insets": {
                    "left": 0,
                    "top": 24,
                    "right": 0,
                    "bottom": 24,
                },
                "system_bars": {
                    "status": {
                        "visible": True,
                        "bounds": {
                            "left": 0,
                            "top": 0,
                            "width": 360,
                            "height": 24,
                        },
                    },
                    "navigation": {
                        "visible": True,
                        "bounds": {
                            "left": 0,
                            "top": 776,
                            "width": 360,
                            "height": 24,
                        },
                    },
                },
            },
        )

    def test_reset_package_uninstalls_the_whole_existing_package_and_proves_absence(self) -> None:
        observations = iter(
            (
                subprocess.CompletedProcess(
                    [], 0, stdout="package:/data/app/test.app/base.apk\n", stderr=""
                ),
                subprocess.CompletedProcess([], 0, stdout="Success\n", stderr=""),
                subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            )
        )
        with patch.object(driver, "run_adb", side_effect=lambda *args, **kwargs: next(observations)) as run:
            evidence = driver.reset_package("test.app")

        self.assertEqual(
            evidence,
            {
                "package_name": "test.app",
                "was_installed": True,
                "absent_after_reset": True,
            },
        )
        self.assertEqual(
            [call.args for call in run.call_args_list],
            [
                ("shell", "pm", "path", "test.app"),
                ("uninstall", "test.app"),
                ("shell", "pm", "path", "test.app"),
            ],
        )

    def test_package_identity_hashes_every_installed_production_apk(self) -> None:
        base = b"production-base-apk"
        split = b"production-language-split"

        def fake_run_adb(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
            if args == ("shell", "pm", "path", "test.app"):
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=(
                        "package:/data/app/random/test.app/split_config.ru.apk\n"
                        "package:/data/app/random/test.app/base.apk\n"
                    ),
                    stderr="",
                )
            payload = split if args[-1].endswith("split_config.ru.apk") else base
            return subprocess.CompletedProcess(args, 0, stdout=payload, stderr=b"")

        with patch.object(driver, "run_adb", side_effect=fake_run_adb):
            identity = driver.package_identity("test.app")

        self.assertEqual(
            identity["apks"],
            [
                {
                    "name": "base.apk",
                    "size": len(base),
                    "sha256": hashlib.sha256(base).hexdigest(),
                },
                {
                    "name": "split_config.ru.apk",
                    "size": len(split),
                    "sha256": hashlib.sha256(split).hexdigest(),
                },
            ],
        )
        self.assertRegex(identity["sha256"], r"^[0-9a-f]{64}$")

    def test_adb_command_ignores_untrusted_environment_binary_override(self) -> None:
        with patch.dict(os.environ, {"ICP_ADB": "/tmp/fake-adb", "ANDROID_SERIAL": "device-1"}), patch.object(
            driver, "resolve_adb_binary", return_value="/trusted/adb"
        ):
            command = driver.adb_prefix()

        self.assertEqual(command, ["/trusted/adb"])

    def test_explicit_device_serial_is_validated_against_live_adb_devices(self) -> None:
        devices = subprocess.CompletedProcess(
            [],
            0,
            stdout="List of devices attached\ndevice-1\tdevice\ndevice-2\tdevice\n",
            stderr="",
        )
        with patch.object(driver, "resolve_adb_binary", return_value="/trusted/adb"), patch.object(
            driver.subprocess, "run", return_value=devices
        ):
            selected = driver.select_adb_serial("device-2")

        self.assertEqual(selected, "device-2")

    def test_explicit_device_serial_rejects_a_missing_or_offline_device(self) -> None:
        devices = subprocess.CompletedProcess(
            [],
            0,
            stdout="List of devices attached\ndevice-1\toffline\n",
            stderr="",
        )
        with patch.object(driver, "resolve_adb_binary", return_value="/trusted/adb"), patch.object(
            driver.subprocess, "run", return_value=devices
        ):
            with self.assertRaisesRegex(driver.DriverError, "not an online adb device"):
                driver.select_adb_serial("device-1")

    def test_tag_lookup_uses_an_exact_semantics_token_not_a_substring(self) -> None:
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="login-header" bounds="[1,2][11,12]" />'
            '<node package="test.app" content-desc="screen login action" bounds="[20,30][50,70]" />'
            '</hierarchy>'
        )

        bounds = driver.tagged_bounds(hierarchy, "login", "test.app")

        self.assertEqual(bounds, (20, 30, 50, 70))

    def test_tag_lookup_ignores_an_identical_tag_from_another_package(self) -> None:
        hierarchy = (
            '<hierarchy><node package="overlay.app" content-desc="login" bounds="[1,2][11,12]" />'
            '<node package="test.app" content-desc="login" bounds="[20,30][50,70]" />'
            '</hierarchy>'
        )

        bounds = driver.tagged_bounds(hierarchy, "login", "test.app")

        self.assertEqual(bounds, (20, 30, 50, 70))

    def test_tag_lookup_preserves_signed_partially_offscreen_bounds(self) -> None:
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="decoration" '
            'bounds="[-48,-82][192,158]" /></hierarchy>'
        )

        bounds = driver.tagged_bounds(hierarchy, "decoration", "test.app")

        self.assertEqual(bounds, (-48, -82, 192, 158))

    def test_interaction_rejects_a_terminal_state_that_was_already_present(self) -> None:
        trace = {
            "schema": "icp.visual-interaction-trace.v1",
            "visual_state_id": "state-target",
            "steps": [{"action": "click", "target_tag": "open-target"}],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-target open-target" '
            'bounds="[0,0][100,100]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=trace), patch.object(
            driver, "window_hierarchy", return_value=hierarchy
        ):
            with self.assertRaisesRegex(driver.DriverError, "already present before interaction"):
                driver.interact("test.app", "trace.json")

    def test_state_and_root_attestation_are_independent_device_observations(self) -> None:
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a" '
            'bounds="[0,0][100,100]" /></hierarchy>'
        )
        with patch.object(driver, "window_hierarchy", return_value=hierarchy):
            evidence = driver.attest("test.app", "state-a", "root-a")

        self.assertTrue(evidence["state_attested"])
        self.assertFalse(evidence["root_attested"])

    def test_interaction_proves_the_terminal_state_appeared_after_real_actions(self) -> None:
        step = {"action": "click", "target_tag": "open-target"}
        trace = {
            "schema": "icp.visual-interaction-trace.v1",
            "visual_state_id": "state-target",
            "steps": [step],
        }
        before = (
            '<hierarchy><node package="test.app" content-desc="open-target" '
            'bounds="[10,20][50,60]" /></hierarchy>'
        )
        after = (
            '<hierarchy><node package="test.app" content-desc="state-target" '
            'bounds="[0,0][100,100]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=trace), patch.object(
            driver, "window_hierarchy", side_effect=[before, before, after]
        ), patch.object(driver, "shell_text", return_value="") as shell:
            evidence = driver.interact("test.app", "trace.json")

        self.assertEqual(
            evidence,
            {
                "schema": "icp.visual-interaction.v1",
                "steps": [step],
                "initial_state_absent": True,
                "terminal_state_present": True,
            },
        )
        shell.assert_called_once_with("input", "tap", "30", "40")

    def test_interaction_executes_the_complete_case_action_sequence(self) -> None:
        step = {
            "source_page_key": "page-a",
            "case_id": "case-a",
            "interaction_id": "interaction-a",
            "outcome": "done",
            "actions": [
                {
                    "operator": "input_text",
                    "target_tag": "phone-input",
                    "value": "7700 123",
                    "fact_ids": [],
                },
                {
                    "operator": "click",
                    "target_tag": "submit-button",
                    "value": None,
                    "fact_ids": [],
                },
                {
                    "operator": "press_back",
                    "target_tag": None,
                    "value": None,
                    "fact_ids": [],
                },
            ],
        }
        trace = {
            "schema": "icp.visual-interaction-trace.v1",
            "visual_state_id": "state-target",
            "steps": [step],
        }
        phone = (
            '<hierarchy><node package="test.app" content-desc="phone-input" '
            'bounds="[10,20][50,60]" /></hierarchy>'
        )
        submit = (
            '<hierarchy><node package="test.app" content-desc="submit-button" '
            'bounds="[50,60][90,100]" /></hierarchy>'
        )
        after = (
            '<hierarchy><node package="test.app" content-desc="state-target" '
            'bounds="[0,0][100,100]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=trace), patch.object(
            driver,
            "window_hierarchy",
            side_effect=[phone, phone, submit, after],
        ), patch.object(driver, "shell_text", return_value="") as shell:
            evidence = driver.interact("test.app", "trace.json")

        self.assertEqual(evidence["steps"], [step])
        self.assertEqual(
            shell.call_args_list,
            [
                unittest.mock.call("input", "tap", "30", "40"),
                unittest.mock.call("input", "text", "7700%s123"),
                unittest.mock.call("input", "tap", "70", "80"),
                unittest.mock.call("input", "keyevent", "KEYCODE_BACK"),
            ],
        )

    def test_runtime_health_requires_the_resumed_activity_to_belong_to_the_package(self) -> None:
        def fake_probe(*args: str) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("shell", "pidof"):
                return subprocess.CompletedProcess(args, 0, stdout="123\n", stderr="")
            if args[:3] == ("shell", "dumpsys", "activity"):
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=(
                        "Task target contains test.app/.MainActivity\n"
                        "mResumedActivity overlay.app/.OverlayActivity\n"
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(driver, "probe_adb", side_effect=fake_probe):
            evidence = driver.runtime_health("test.app")

        self.assertFalse(evidence["activity_resumed"])

    def test_runtime_health_deduplicates_equivalent_resumed_activity_lines(self) -> None:
        def fake_probe(*args: str) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("shell", "pidof"):
                return subprocess.CompletedProcess(args, 0, stdout="123\n", stderr="")
            if args[:3] == ("shell", "dumpsys", "activity"):
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=(
                        "mResumedActivity test.app/.MainActivity\n"
                        "topResumedActivity test.app/.MainActivity\n"
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(driver, "probe_adb", side_effect=fake_probe):
            evidence = driver.runtime_health("test.app")

        self.assertTrue(evidence["activity_resumed"])

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

    def test_cold_start_removes_any_previous_runtime_probe_before_launch(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run_adb(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
            commands.append(args)
            if args[:4] == ("shell", "cmd", "package", "resolve-activity"):
                return subprocess.CompletedProcess(
                    args, 0, stdout="test.app/.MainActivity\n", stderr=""
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

        force_stop = ("shell", "am", "force-stop", "test.app")
        clear_probe = (
            "shell",
            "run-as",
            "test.app",
            "rm",
            "-f",
            "files/icp-runtime-probes.json",
        )
        start = next(command for command in commands if command[:3] == ("shell", "am", "start"))
        self.assertLess(commands.index(force_stop), commands.index(clear_probe))
        self.assertLess(commands.index(clear_probe), commands.index(start))

    def test_measurement_payload_must_match_the_frozen_probe_contract(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "logical_scale": 1.0,
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
            "logical_scale": 1.0,
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
                '<hierarchy><node package="test.app" content-desc="root-state-a" '
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
            "logical_scale": 1.0,
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
                '<hierarchy><node package="test.app" content-desc="target-permission-icon" '
                'bounds="[4,8][56,60]" /></hierarchy>'
            ),
        ):
            measured = driver.measure("test.app", "contract.json")

        self.assertEqual(measured, driver.measure_payload(contract, payload))

    def test_measure_rejects_one_live_node_owning_multiple_obligation_probes(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "logical_scale": 1,
            "assertions": [
                {
                    "assertion_id": "assertion-a",
                    "probe_tag": "probe-obligation-a",
                    "kind": "bounds",
                    "expected": {"left": 4, "top": 8, "width": 52, "height": 52},
                },
                {
                    "assertion_id": "assertion-b",
                    "probe_tag": "probe-obligation-b",
                    "kind": "bounds",
                    "expected": {"left": 4, "top": 8, "width": 52, "height": 52},
                },
            ],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "probes": [
                {
                    "probe_tag": "probe-obligation-a",
                    "bounds": {"left": 4, "top": 8, "width": 52, "height": 52},
                },
                {
                    "probe_tag": "probe-obligation-b",
                    "bounds": {"left": 4, "top": 8, "width": 52, "height": 52},
                },
            ],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" '
            'content-desc="probe-obligation-a probe-obligation-b" '
            'bounds="[4,8][56,60]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            with self.assertRaisesRegex(
                driver.DriverError,
                "one obligation probe",
            ):
                driver.measure("test.app", "contract.json")

    def test_measure_accepts_the_exact_fraction_scale_frozen_by_stage_one(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "logical_scale": "3/2",
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
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(
            driver,
            "window_hierarchy",
            return_value=(
                '<hierarchy><node package="test.app" '
                'content-desc="target-permission-icon" bounds="[6,12][84,90]" />'
                '</hierarchy>'
            ),
        ):
            measured = driver.measure("test.app", "contract.json")

        self.assertEqual(measured, driver.measure_payload(contract, payload))

    def test_measure_rejects_bounds_not_observed_in_the_live_hierarchy(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "logical_scale": 1.0,
            "assertions": [{
                "assertion_id": "assertion-a",
                "probe_tag": "target-permission-icon",
                "kind": "bounds",
                "expected": {"left": 4, "top": 8, "width": 52, "height": 52},
            }],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "probes": [{
                "probe_tag": "target-permission-icon",
                "bounds": {"left": 4, "top": 8, "width": 52, "height": 52},
            }],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="target-permission-icon" '
            'bounds="[4,8][50,60]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            with self.assertRaisesRegex(
                driver.DriverError, "runtime probe bounds differ from live hierarchy"
            ):
                driver.measure("test.app", "contract.json")

    def test_measure_reads_typography_from_the_clean_build_apk_not_the_app_payload(self) -> None:
        apk = self.build_typography_apk(
            {
                "icp_assertion_a_font_size": "18sp",
                "icp_assertion_a_line_height": "28sp",
            }
        )
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "logical_scale": 1,
            "assertions": [
                {
                    "assertion_id": "assertion-a-font",
                    "probe_tag": "target-copy",
                    "kind": "font_size",
                    "expected": 14,
                    "apk_resource_name": "icp_assertion_a_font_size",
                },
                {
                    "assertion_id": "assertion-a-line",
                    "probe_tag": "target-copy",
                    "kind": "line_height",
                    "expected": 22,
                    "apk_resource_name": "icp_assertion_a_line_height",
                },
            ],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "probes": [
                {
                    "probe_tag": "target-copy",
                    "font_size": 14,
                    "line_height": 22,
                }
            ],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="target-copy" '
            'bounds="[0,0][100,40]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            measured = driver.measure("test.app", "contract.json", apk_path=str(apk))

        self.assertEqual(
            [item["actual"] for item in measured["measurements"]],
            [18, 28],
        )
        apk_sha = hashlib.sha256(apk.read_bytes()).hexdigest()
        self.assertTrue(
            all(
                item["source"] == "clean_build_apk"
                and item["apk_sha256"] == apk_sha
                for item in measured["measurements"]
            )
        )

    def test_measure_rejects_typography_without_a_clean_build_apk(self) -> None:
        contract = {
            "schema": "icp.visual-measurement-contract.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "logical_scale": 1,
            "assertions": [
                {
                    "assertion_id": "assertion-a-font",
                    "probe_tag": "target-copy",
                    "kind": "font_size",
                    "expected": 14,
                    "apk_resource_name": "icp_assertion_a_font_size",
                }
            ],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "probes": [{"probe_tag": "target-copy", "font_size": 14}],
        }

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ):
            with self.assertRaisesRegex(driver.DriverError, "clean-build APK"):
                driver.measure("test.app", "contract.json")

    def test_read_layout_uses_the_app_private_production_payload_and_live_hierarchy(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "require_device_window_insets": True,
            "component_instance_ids": ["root-instance", "child-instance"],
            "occurrence_ids_by_instance_id": {
                "root-instance": "occurrence-root",
                "child-instance": "occurrence-child",
            },
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 24},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {
                    "visible": True,
                    "bounds": {"left": 0, "top": 776, "width": 360, "height": 24},
                },
            },
            "scroll_metrics": [],
            "components": [
                {
                    "instance_id": "root-instance",
                    "occurrence_id": "occurrence-root",
                    "bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
                },
                {
                    "instance_id": "child-instance",
                    "occurrence_id": "occurrence-child",
                    "bounds": {"left": 16, "top": 24, "width": 328, "height": 52},
                },
            ],
            "probes": [],
        }

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ) as shell, patch.object(
            driver,
            "window_hierarchy",
            return_value=(
                '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" '
                'bounds="[0,0][360,800]" />'
                '<node package="test.app" content-desc="occurrence-child" bounds="[16,24][344,76]" />'
                '</hierarchy>'
            ),
        ), patch.object(
            driver,
            "observe_device_window_insets",
            return_value={
                "safe_insets": payload["safe_insets"],
                "system_bars": payload["system_bars"],
            },
        ):
            measured = driver.read_layout("test.app", "contract.json")

        shell.assert_called_once_with(
            "run-as", "test.app", "cat", "files/icp-runtime-probes.json"
        )
        self.assertEqual(
            measured["components"],
            [
                {key: value for key, value in item.items() if key != "presence"}
                for item in payload["components"]
            ],
        )
        self.assertEqual(
            measured["driver_observations"]["observed_instance_ids"],
            ["root-instance", "child-instance"],
        )
        self.assertEqual(measured["driver_observations"]["scroll_actions"], [])
        self.assertNotIn("schema", measured)
        self.assertNotIn("probes", measured)

    def test_read_layout_rejects_component_occurrence_identity_swaps(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "component_instance_ids": ["component-a", "component-b"],
            "occurrence_ids_by_instance_id": {
                "component-a": "occurrence-a",
                "component-b": "occurrence-b",
            },
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 100, "height": 100},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [],
            "components": [
                {
                    "instance_id": "component-a",
                    "occurrence_id": "occurrence-b",
                    "bounds": {"left": 0, "top": 0, "width": 40, "height": 40},
                },
                {
                    "instance_id": "component-b",
                    "occurrence_id": "occurrence-a",
                    "bounds": {"left": 0, "top": 0, "width": 40, "height": 40},
                },
            ],
            "probes": [],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a root-state-a" '
            'bounds="[0,0][100,100]" />'
            '<node package="test.app" content-desc="occurrence-a" bounds="[0,0][40,40]" />'
            '<node package="test.app" content-desc="occurrence-b" bounds="[0,0][40,40]" />'
            '</hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            with self.assertRaisesRegex(
                driver.DriverError, "component occurrence identity changed"
            ):
                driver.read_layout("test.app", "contract.json")

    def test_read_layout_rejects_app_insets_that_disagree_with_the_device(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "logical_scale": 1,
            "require_device_window_insets": True,
            "component_instance_ids": ["root-instance"],
            "occurrence_ids_by_instance_id": {
                "root-instance": "root-instance",
            },
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [],
            "components": [
                {
                    "instance_id": "root-instance",
                    "occurrence_id": "root-instance",
                    "bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
                }
            ],
            "probes": [],
        }
        observed = {
            "safe_insets": {"left": 0, "top": 24, "right": 0, "bottom": 24},
            "system_bars": {
                "status": {
                    "visible": True,
                    "bounds": {"left": 0, "top": 0, "width": 360, "height": 24},
                },
                "navigation": {
                    "visible": True,
                    "bounds": {"left": 0, "top": 776, "width": 360, "height": 24},
                },
            },
        }

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(
            driver, "observe_device_window_insets", return_value=observed
        ):
            with self.assertRaisesRegex(
                driver.DriverError, "differ from the live Android window"
            ):
                driver.read_layout("test.app", "contract.json")

    def test_read_layout_compares_dp_to_live_pixels_with_the_reference_scale(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "component_instance_ids": ["child-instance"],
            "occurrence_ids_by_instance_id": {
                "child-instance": "occurrence-child",
            },
            "logical_scale": "3/2",
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 24},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": True, "bounds": {"left": 0, "top": 776, "width": 360, "height": 24}},
            },
            "scroll_metrics": [],
            "components": [
                {
                    "instance_id": "child-instance",
                    "occurrence_id": "occurrence-child",
                    "bounds": {"left": 4, "top": 8, "width": 52, "height": 52},
                }
            ],
            "probes": [],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a root-state-a" '
            'bounds="[0,0][540,1200]" />'
            '<node package="test.app" content-desc="occurrence-child" '
            'bounds="[6,12][84,90]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            measured = driver.read_layout("test.app", "contract.json")

        self.assertEqual(measured["components"], payload["components"])

    def test_read_layout_rejects_component_bounds_not_observed_in_live_hierarchy(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "component_instance_ids": ["root-instance"],
            "occurrence_ids_by_instance_id": {
                "root-instance": "occurrence-root",
            },
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [],
            "components": [{
                "instance_id": "root-instance",
                "occurrence_id": "occurrence-root",
                "bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            }],
            "probes": [],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" '
            'bounds="[0,0][320,700]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            with self.assertRaisesRegex(
                driver.DriverError, "runtime layout bounds differ from live hierarchy"
            ):
                driver.read_layout("test.app", "contract.json")

    def test_read_layout_allows_one_pixel_of_runtime_rounding(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "component_instance_ids": ["root-instance"],
            "occurrence_ids_by_instance_id": {
                "root-instance": "occurrence-root",
            },
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [],
            "components": [{
                "instance_id": "root-instance",
                "occurrence_id": "occurrence-root",
                "bounds": {"left": 0.4, "top": 0, "width": 359.6, "height": 800},
            }],
            "probes": [],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" '
            'bounds="[0,0][360,800]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            measured = driver.read_layout("test.app", "contract.json")

        self.assertEqual(measured["components"], payload["components"])

    def test_read_layout_observes_lazy_offscreen_components_by_scrolling(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "component_instance_ids": ["root-instance", "offscreen-instance"],
            "occurrence_ids_by_instance_id": {
                "root-instance": "occurrence-root",
                "offscreen-instance": "occurrence-offscreen",
            },
            "logical_scale": "2",
            "scroll_obligations": [
                {
                    "decision_id": "scroll-main",
                    "container_instance_id": "root-instance",
                    "axis": "vertical",
                    "required_instance_ids": [
                        "root-instance",
                        "offscreen-instance",
                    ],
                }
            ],
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [{
                "decision_id": "scroll-main",
                "container_instance_id": "root-instance",
                "axis": "vertical",
                "viewport_extent": 800,
                "content_extent": 800,
                "observed_offsets": [0],
            }],
            "components": [
                {
                    "instance_id": "root-instance",
                    "occurrence_id": "occurrence-root",
                    "presence": "present",
                    "bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
                },
                {
                    "instance_id": "offscreen-instance",
                    "occurrence_id": "occurrence-offscreen",
                    "presence": "present",
                    "bounds": {"left": 16, "top": 920, "width": 328, "height": 80},
                },
            ],
            "probes": [],
        }
        initial_hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" '
            'bounds="[0,0][720,1600]" /></hierarchy>'
        )
        end_hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" '
            'bounds="[0,0][720,1600]" />'
            '<node package="test.app" content-desc="occurrence-offscreen" bounds="[32,1040][688,1200]" />'
            '</hierarchy>'
        )
        hierarchies = iter(
            [
                initial_hierarchy,
                end_hierarchy,
                end_hierarchy,
                end_hierarchy,
                initial_hierarchy,
            ]
        )

        def shell(*args: str) -> str:
            if args[:4] == ("run-as", "test.app", "cat", "files/icp-runtime-probes.json"):
                return json.dumps(payload)
            return ""

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", side_effect=shell
        ) as shell_call, patch.object(
            driver, "window_hierarchy", side_effect=lambda: next(hierarchies)
        ):
            measured = driver.read_layout("test.app", "contract.json")

        self.assertEqual(
            measured["components"],
            [
                {key: value for key, value in item.items() if key != "presence"}
                for item in payload["components"]
            ],
        )
        self.assertTrue(
            any(call.args[:2] == ("input", "swipe") for call in shell_call.call_args_list)
        )
        first_swipe = next(
            call.args
            for call in shell_call.call_args_list
            if call.args[:2] == ("input", "swipe")
        )
        self.assertEqual(
            first_swipe,
            ("input", "swipe", "360", "1200", "360", "400", "250"),
        )
        self.assertEqual(
            measured["driver_observations"],
            {
                "observed_instance_ids": ["root-instance", "offscreen-instance"],
                "scroll_actions": [
                    {
                        "axis": "vertical",
                        "direction": "forward",
                        "start_px": {"x": 360, "y": 1200},
                        "end_px": {"x": 360, "y": 400},
                    },
                    {
                        "axis": "vertical",
                        "direction": "forward",
                        "start_px": {"x": 360, "y": 1200},
                        "end_px": {"x": 360, "y": 400},
                    },
                    {
                        "axis": "vertical",
                        "direction": "forward",
                        "start_px": {"x": 360, "y": 1200},
                        "end_px": {"x": 360, "y": 400},
                    },
                    {
                        "axis": "vertical",
                        "direction": "restore",
                        "start_px": {"x": 360, "y": 400},
                        "end_px": {"x": 360, "y": 1200},
                    },
                ],
                "scroll_results": [
                    {
                        "decision_id": "scroll-main",
                        "container_instance_id": "root-instance",
                        "axis": "vertical",
                        "end_reached": True,
                        "restored_to_start": True,
                        "observed_instance_ids": [
                            "offscreen-instance",
                            "root-instance",
                        ],
                    }
                ],
            },
        )

    def test_read_layout_ignores_untrusted_app_scroll_metrics(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "component_instance_ids": ["offscreen-instance"],
            "occurrence_ids_by_instance_id": {
                "offscreen-instance": "occurrence-offscreen",
            },
            "logical_scale": "2",
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [
                {
                    "decision_id": "scroll-main",
                    "container_instance_id": "offscreen-instance",
                    "axis": "vertical",
                    "viewport_extent": 800,
                    "content_extent": "many",
                    "observed_offsets": [0],
                }
            ],
            "components": [
                {
                    "instance_id": "offscreen-instance",
                    "occurrence_id": "occurrence-offscreen",
                    "bounds": {"left": 0, "top": 900, "width": 100, "height": 40},
                }
            ],
            "probes": [],
        }
        hierarchy = (
            '<hierarchy><node package="test.app" content-desc="state-a root-state-a" '
            'bounds="[0,0][720,1600]" />'
            '<node package="test.app" content-desc="occurrence-offscreen" '
            'bounds="[0,1800][200,1880]" /></hierarchy>'
        )

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", return_value=json.dumps(payload)
        ), patch.object(driver, "window_hierarchy", return_value=hierarchy):
            measured = driver.read_layout("test.app", "contract.json")

        self.assertEqual(measured["scroll_metrics"], [])

    def test_read_layout_scans_both_axes_from_frozen_obligations(self) -> None:
        contract = {
            "schema": "icp.runtime-layout-contract",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "component_instance_ids": ["root", "vertical", "horizontal"],
            "occurrence_ids_by_instance_id": {
                "root": "occurrence-root",
                "vertical": "occurrence-vertical",
                "horizontal": "occurrence-horizontal",
            },
            "scroll_obligations": [
                {
                    "decision_id": "vertical-scroll",
                    "container_instance_id": "root",
                    "axis": "vertical",
                    "required_instance_ids": ["root", "vertical"],
                },
                {
                    "decision_id": "horizontal-scroll",
                    "container_instance_id": "root",
                    "axis": "horizontal",
                    "required_instance_ids": ["root", "horizontal"],
                },
            ],
        }
        component = lambda identity, left, top: {
            "instance_id": identity,
            "occurrence_id": "occurrence-" + identity,
            "presence": "present",
            "bounds": {"left": left, "top": top, "width": 40, "height": 40},
        }
        payload = {
            "schema": "icp.runtime-probes.v1",
            "visual_state_id": "state-a",
            "root_tag": "root-state-a",
            "coordinate_space": {"unit": "dp", "origin": "viewport"},
            "viewport_bounds": {"left": 0, "top": 0, "width": 360, "height": 800},
            "safe_insets": {"left": 0, "top": 0, "right": 0, "bottom": 0},
            "system_bars": {
                "status": {"visible": False, "bounds": None},
                "navigation": {"visible": False, "bounds": None},
            },
            "scroll_metrics": [
                {
                    "decision_id": "vertical-scroll",
                    "container_instance_id": "root",
                    "axis": "vertical",
                    "viewport_extent": 800,
                    "content_extent": 800,
                    "observed_offsets": [0],
                },
                {
                    "decision_id": "horizontal-scroll",
                    "container_instance_id": "root",
                    "axis": "horizontal",
                    "viewport_extent": 360,
                    "content_extent": 360,
                    "observed_offsets": [0],
                },
            ],
            "components": [
                component("root", 0, 0),
                component("vertical", 0, 900),
                component("horizontal", 500, 0),
            ],
            "probes": [],
        }
        initial = '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" bounds="[0,0][40,40]" /></hierarchy>'
        vertical = '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" bounds="[0,0][40,40]" /><node package="test.app" content-desc="occurrence-vertical" bounds="[0,0][40,40]" /></hierarchy>'
        horizontal = '<hierarchy><node package="test.app" content-desc="state-a root-state-a occurrence-root" bounds="[0,0][40,40]" /><node package="test.app" content-desc="occurrence-horizontal" bounds="[0,0][40,40]" /></hierarchy>'
        hierarchies = iter(
            [
                initial,
                vertical,
                vertical,
                vertical,
                initial,
                horizontal,
                horizontal,
                horizontal,
                initial,
            ]
        )
        swipes: list[tuple[str, ...]] = []

        def shell(*args: str) -> str:
            if args[:4] == ("run-as", "test.app", "cat", "files/icp-runtime-probes.json"):
                return json.dumps(payload)
            if args[:2] == ("input", "swipe"):
                swipes.append(args)
            return ""

        with patch.object(driver, "load_json", return_value=contract), patch.object(
            driver, "shell_text", side_effect=shell
        ), patch.object(
            driver, "window_hierarchy", side_effect=lambda: next(hierarchies)
        ):
            measured = driver.read_layout("test.app", "contract.json")

        self.assertEqual(
            measured["components"],
            [
                {key: value for key, value in item.items() if key != "presence"}
                for item in payload["components"]
            ],
        )
        self.assertTrue(any(call[3] == call[5] for call in swipes))
        self.assertTrue(any(call[2] == call[4] for call in swipes))


if __name__ == "__main__":
    unittest.main()
