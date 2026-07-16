#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    selector = skill / "scripts" / "select_runtime_device.py"
    with tempfile.TemporaryDirectory(prefix="iff-runtime-device-") as raw_tmp:
        root = Path(raw_tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        selection_path = root / "runtime_device.json"

        write_executable(
            bin_dir / "adb",
            "#!/bin/sh\n"
            "if [ \"$1\" = \"devices\" ]; then\n"
            "  printf 'List of devices attached\\n\\n'\n"
            "  exit 0\n"
            "fi\n"
            "printf 'unexpected adb argv: %s\\n' \"$*\" >&2\n"
            "exit 2\n",
        )
        write_executable(
            bin_dir / "emulator",
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-list-avds\" ]; then\n"
            "  printf 'Broken_Generic_AVD\\n'\n"
            "  exit 0\n"
            "fi\n"
            "printf 'PANIC: generic emulator image cannot start\\n' >&2\n"
            "exit 1\n",
        )
        ios_devices = json.dumps(
            {
                "devices": {
                    "com.apple.CoreSimulator.SimRuntime.iOS-18-5": [
                        {
                            "name": "Generic iPhone",
                            "udid": "IOS-BOOTED-UDID",
                            "state": "Booted",
                            "isAvailable": True,
                            "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16",
                        }
                    ]
                }
            }
        )
        write_executable(
            bin_dir / "xcrun",
            "#!/bin/sh\n"
            "if [ \"$1 $2 $3 $4\" = \"simctl list devices available\" ]; then\n"
            f"  printf '%s\\n' '{ios_devices}'\n"
            "  exit 0\n"
            "fi\n"
            "printf 'unexpected xcrun argv: %s\\n' \"$*\" >&2\n"
            "exit 2\n",
        )

        env = os.environ.copy()
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        started = time.monotonic()
        result = subprocess.run(
            [
                sys.executable,
                str(selector),
                "--platform",
                "auto",
                "--command-timeout",
                "2",
                "--boot-timeout",
                "1",
                "--poll-interval",
                "0.05",
                "--out",
                str(selection_path),
            ],
            text=True,
            capture_output=True,
            env=env,
            timeout=8,
        )
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        assert elapsed < 6, f"device fallback was not fail-fast: {elapsed:.2f}s"
        selected = json.loads(selection_path.read_text(encoding="utf-8"))
        assert selected["platform"] == "ios", selected
        assert selected["device"] == "IOS-BOOTED-UDID", selected
        assert selected["actualSource"] == "simulator_screenshot", selected
        assert "PANIC: generic emulator image cannot start" in selected["fallbackReason"], selected
        assert "wait-for-device" not in selector.read_text(encoding="utf-8")

        write_executable(bin_dir / "flutter", "#!/bin/sh\nexit 0\n")
        write_executable(
            bin_dir / "xcrun",
            "#!/bin/sh\n"
            "if [ \"$1 $2 $3 $4\" = \"simctl list devices available\" ]; then\n"
            f"  printf '%s\\n' '{ios_devices}'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1 $2 $4\" = \"simctl io screenshot\" ]; then\n"
            "  printf 'runtime simulator pixels' > \"$5\"\n"
            "  exit 0\n"
            "fi\n"
            "printf 'unexpected xcrun argv: %s\\n' \"$*\" >&2\n"
            "exit 2\n",
        )
        capture = skill / "scripts" / "capture_runtime_screenshot.py"
        ios_actual = root / "ios_actual.png"
        ios_manifest = root / "ios_visual_manifest.json"
        ios_capture = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(selection_path),
                "--out",
                str(ios_actual),
                "--manifest",
                str(ios_manifest),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "2",
                "--launch-timeout",
                "2",
            ],
            text=True,
            capture_output=True,
            env=env,
            timeout=8,
        )
        if ios_capture.returncode != 0:
            raise AssertionError(ios_capture.stdout + ios_capture.stderr)
        assert ios_actual.read_bytes() == b"runtime simulator pixels"
        manifest = json.loads(ios_manifest.read_text(encoding="utf-8"))
        assert manifest["actual_source"] == "simulator_screenshot", manifest
        assert manifest["platform"] == "ios", manifest
        assert manifest["device_id"] == "IOS-BOOTED-UDID", manifest

        write_executable(
            bin_dir / "adb",
            "#!/bin/sh\n"
            "if [ \"$1\" = \"devices\" ]; then\n"
            "  printf 'List of devices attached\\nemulator-5554\\tdevice\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$4\" = \"getprop\" ] && [ \"$5\" = \"sys.boot_completed\" ]; then printf '1\\n'; exit 0; fi\n"
            "if [ \"$4\" = \"pm\" ] && [ \"$5\" = \"path\" ] && [ \"$6\" = \"android\" ]; then printf 'package:/system/framework/framework-res.apk\\n'; exit 0; fi\n"
            "(sleep 5) &\n"
            "wait\n",
        )
        android_selection = root / "android_device.json"
        android_selection.write_text(
            json.dumps(
                {
                    "platform": "android",
                    "device": "emulator-5554",
                    "actualSource": "simulator_screenshot",
                }
            ),
            encoding="utf-8",
        )
        capture_started = time.monotonic()
        capture_result = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "actual.png"),
                "--manifest",
                str(root / "visual_manifest.json"),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=env,
            timeout=3,
        )
        capture_elapsed = time.monotonic() - capture_started
        assert capture_result.returncode != 0, capture_result.stdout
        assert capture_elapsed < 3, f"adb capture did not fail fast: {capture_elapsed:.2f}s"
        capture_error = capture_result.stdout + capture_result.stderr
        assert "timed out after 0.5s" in capture_error, capture_error
        assert "screencap" in capture_error, capture_error
        assert "wait-for-device" not in capture.read_text(encoding="utf-8")

        apk = root / "app-debug.apk"
        apk.write_bytes(b"deterministic-test-apk")
        write_executable(
            bin_dir / "aapt",
            "#!/bin/sh\n"
            "if [ \"$1\" = \"dump\" ] && [ \"$2\" = \"badging\" ]; then\n"
            "  printf \"package: name='com.example.current_test' versionCode='1'\\n\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 2\n",
        )
        write_executable(
            bin_dir / "flutter",
            "#!/bin/sh\n"
            "count=0\n"
            "if [ -f \"$IFF_FLUTTER_COUNT\" ]; then count=$(sed -n '1p' \"$IFF_FLUTTER_COUNT\"); fi\n"
            "count=$((count + 1))\n"
            "printf '%s\\n' \"$count\" > \"$IFF_FLUTTER_COUNT\"\n"
            "if [ \"$count\" -eq 1 ] || [ \"${IFF_RETRY_ALWAYS_FAIL:-0}\" = \"1\" ] || "
            "{ [ \"${IFF_SECOND_STORAGE_FAIL:-0}\" = \"1\" ] && [ \"$count\" -le 2 ]; }; then\n"
            "  printf 'Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE: insufficient storage]\\n' >&2\n"
            "  exit 1\n"
            "fi\n"
            "exit 0\n",
        )
        write_executable(
            bin_dir / "adb",
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$IFF_ADB_LOG\"\n"
            "if [ \"$1\" = \"devices\" ]; then\n"
            "  printf 'List of devices attached\\nemulator-5554\\tdevice\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$4\" = \"getprop\" ] && [ \"$5\" = \"sys.boot_completed\" ]; then printf '1\\n'; exit 0; fi\n"
            "if [ \"$4\" = \"pm\" ] && [ \"$5\" = \"path\" ] && [ \"$6\" = \"android\" ]; then printf 'package:/system/framework/framework-res.apk\\n'; exit 0; fi\n"
            "if [ \"$3\" = \"uninstall\" ]; then\n"
            "  [ \"$4\" = \"com.example.current_test\" ] || exit 9\n"
            "  printf 'Success\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"get-install-location\" ]; then\n"
            "  printf '%s\\n' \"${IFF_INSTALL_LOCATION:-0[auto]}\"\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"df\" ] && [ \"$5\" = \"-k\" ] && [ \"$6\" = \"/data\" ]; then\n"
            "  printf 'Filesystem 1K-blocks Used Available Use%% Mounted on\\n/data 1000000 950000 50000 95%% /data\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"set-install-location\" ] && [ \"$6\" = \"0\" ]; then exit 0; fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"trim-caches\" ] && [ \"$6\" = \"2147483648\" ]; then exit 0; fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"screencap\" ]; then exit 0; fi\n"
            "if [ \"$3\" = \"pull\" ]; then printf 'png' > \"$5\"; exit 0; fi\n"
            "exit 2\n",
        )
        flutter_count = root / "flutter_count"
        adb_log = root / "adb.log"
        recovery_env = env.copy()
        recovery_env["IFF_FLUTTER_COUNT"] = str(flutter_count)
        recovery_env["IFF_ADB_LOG"] = str(adb_log)
        recovered_manifest = root / "recovered_manifest.json"
        recovered = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "recovered.png"),
                "--manifest",
                str(recovered_manifest),
                "--android-apk",
                str(apk),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=recovery_env,
            timeout=5,
        )
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert flutter_count.read_text(encoding="utf-8").strip() == "2"
        recovery_log = adb_log.read_text(encoding="utf-8").splitlines()
        uninstall = "-s emulator-5554 uninstall com.example.current_test"
        assert recovery_log.count(uninstall) == 1, recovery_log
        assert all("pm clear" not in line and "wipe-data" not in line for line in recovery_log)
        recovery = json.loads(recovered_manifest.read_text(encoding="utf-8"))["android_storage_recovery"]
        assert recovery["package"] == "com.example.current_test", recovery
        assert recovery["install_retry_count"] == 1, recovery
        assert recovery["outcome"] == "recovered", recovery
        assert all("get-install-location" not in line and "trim-caches" not in line for line in recovery_log)

        flutter_count.unlink()
        adb_log.unlink()
        recovery_env["IFF_SECOND_STORAGE_FAIL"] = "1"
        storage_manifest = root / "storage_recovered_manifest.json"
        storage_recovered = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "storage_recovered.png"),
                "--manifest",
                str(storage_manifest),
                "--android-apk",
                str(apk),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=recovery_env,
        )
        assert storage_recovered.returncode == 0, storage_recovered.stdout + storage_recovered.stderr
        assert flutter_count.read_text(encoding="utf-8").strip() == "3"
        storage_log = adb_log.read_text(encoding="utf-8").splitlines()
        get_location = "-s emulator-5554 shell pm get-install-location"
        inspect_data = "-s emulator-5554 shell df -k /data"
        trim_caches = "-s emulator-5554 shell pm trim-caches 2147483648"
        set_auto = "-s emulator-5554 shell pm set-install-location 0"
        assert storage_log.count(uninstall) == 1, storage_log
        assert storage_log.count(get_location) == 1, storage_log
        assert storage_log.count(inspect_data) == 1, storage_log
        assert storage_log.count(trim_caches) == 1, storage_log
        assert set_auto not in storage_log, storage_log
        assert storage_log.index(uninstall) < storage_log.index(get_location) < storage_log.index(inspect_data), storage_log
        assert storage_log.index(inspect_data) < storage_log.index(trim_caches), storage_log
        storage_recovery = json.loads(storage_manifest.read_text(encoding="utf-8"))["android_storage_recovery"]
        assert storage_recovery["device_storage_recovery"]["attempted"] is True, storage_recovery
        assert storage_recovery["device_storage_recovery"]["install_location_reset"] is False, storage_recovery
        assert storage_recovery["final_launch_retry_count"] == 1, storage_recovery

        flutter_count.unlink()
        adb_log.unlink()
        recovery_env.pop("IFF_SECOND_STORAGE_FAIL")
        recovery_env["IFF_RETRY_ALWAYS_FAIL"] = "1"
        recovery_env["IFF_INSTALL_LOCATION"] = "2[external]"
        still_failing = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "still_failing.png"),
                "--manifest",
                str(root / "still_failing_manifest.json"),
                "--android-apk",
                str(apk),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=recovery_env,
            timeout=5,
        )
        assert still_failing.returncode != 0, still_failing.stdout
        assert flutter_count.read_text(encoding="utf-8").strip() == "3"
        failing_log = adb_log.read_text(encoding="utf-8").splitlines()
        assert failing_log.count(uninstall) == 1, failing_log
        assert failing_log.count(get_location) == 1, failing_log
        assert failing_log.count(inspect_data) == 1, failing_log
        assert failing_log.count(set_auto) == 1, failing_log
        assert failing_log.count(trim_caches) == 1, failing_log
        assert failing_log.index(get_location) < failing_log.index(inspect_data) < failing_log.index(set_auto), failing_log
        assert failing_log.index(set_auto) < failing_log.index(trim_caches), failing_log
        failure = still_failing.stdout + still_failing.stderr
        assert "final launch retry failed after bounded device-storage recovery" in failure, failure
        assert "com.example.current_test" in failure, failure
        assert "INSTALL_FAILED_INSUFFICIENT_STORAGE" in failure, failure

        flutter_count.unlink()
        adb_log.unlink()
        uninstall_count = root / "uninstall_count"
        write_executable(
            bin_dir / "adb",
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$IFF_ADB_LOG\"\n"
            "if [ \"$1\" = \"devices\" ]; then\n"
            "  printf 'List of devices attached\\nemulator-5554\\tdevice\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$4\" = \"getprop\" ] && [ \"$5\" = \"sys.boot_completed\" ]; then printf '1\\n'; exit 0; fi\n"
            "if [ \"$4\" = \"pm\" ] && [ \"$5\" = \"path\" ] && [ \"$6\" = \"android\" ]; then printf 'package:/system/framework/framework-res.apk\\n'; exit 0; fi\n"
            "if [ \"$3\" = \"uninstall\" ]; then\n"
            "  count=0\n"
            "  if [ -f \"$IFF_UNINSTALL_COUNT\" ]; then count=$(sed -n '1p' \"$IFF_UNINSTALL_COUNT\"); fi\n"
            "  count=$((count + 1))\n"
            "  printf '%s\\n' \"$count\" > \"$IFF_UNINSTALL_COUNT\"\n"
            "  if [ \"$count\" -eq 1 ] || [ \"${IFF_DELETE_ALWAYS_FAIL:-0}\" = \"1\" ]; then\n"
            "    printf 'Failure [DELETE_FAILED_INTERNAL_ERROR]\\n' >&2\n"
            "    exit 1\n"
            "  fi\n"
            "  printf 'Success\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"clear\" ]; then\n"
            "  [ \"$6\" = \"com.example.current_test\" ] || exit 9\n"
            "  if [ \"${IFF_CONTRADICTORY_PACKAGE_STATE:-0}\" = \"1\" ]; then printf 'Failed\\n' >&2; exit 1; fi\n"
            "  printf 'Success\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"am\" ] && [ \"$5\" = \"get-current-user\" ]; then\n"
            "  printf '0\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"uninstall\" ]; then\n"
            "  [ \"$6\" = \"--user\" ] && [ \"$7\" = \"0\" ] || exit 9\n"
            "  [ \"$8\" = \"com.example.current_test\" ] || exit 9\n"
            "  if [ \"${IFF_CONTRADICTORY_PACKAGE_STATE:-0}\" = \"1\" ]; then printf 'Failure [not installed for 0]\\n' >&2; exit 1; fi\n"
            "  printf 'Success\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"cmd\" ] && [ \"$5\" = \"package\" ] && [ \"$6\" = \"install-existing\" ]; then\n"
            "  [ \"$7\" = \"--user\" ] && [ \"$8\" = \"0\" ] || exit 9\n"
            "  [ \"$9\" = \"com.example.current_test\" ] || exit 9\n"
            "  if [ \"${IFF_PACKAGE_RESTORE_FAIL:-0}\" = \"1\" ]; then printf 'Package restore failed\\n' >&2; exit 1; fi\n"
            "  printf 'Package com.example.current_test installed for user: 0\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"install\" ]; then\n"
            "  [ \"$4\" = \"--user\" ] && [ \"$5\" = \"0\" ] && [ \"$6\" = \"-r\" ] || exit 9\n"
            "  count=0\n"
            "  if [ -f \"$IFF_EXACT_INSTALL_COUNT\" ]; then count=$(sed -n '1p' \"$IFF_EXACT_INSTALL_COUNT\"); fi\n"
            "  count=$((count + 1))\n"
            "  printf '%s\\n' \"$count\" > \"$IFF_EXACT_INSTALL_COUNT\"\n"
            "  if { [ \"${IFF_EXACT_INSTALL_STORAGE_ONCE:-0}\" = \"1\" ] && [ \"$count\" -eq 1 ]; } || [ \"${IFF_EXACT_INSTALL_ALWAYS_STORAGE:-0}\" = \"1\" ]; then\n"
            "    printf 'Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE: Requested internal only, but not enough space]\\n' >&2\n"
            "    exit 1\n"
            "  fi\n"
            "  if [ \"${IFF_PACKAGE_RESTORE_FAIL:-0}\" = \"1\" ]; then printf 'Exact APK install-replace failed\\n' >&2; exit 1; fi\n"
            "  printf 'Success\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"get-install-location\" ]; then printf '%s\\n' \"${IFF_INSTALL_LOCATION:-0[auto]}\"; exit 0; fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"df\" ] && [ \"$5\" = \"-k\" ] && [ \"$6\" = \"/data\" ]; then printf '/data 1000000 950000 50000 95%% /data\\n'; exit 0; fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"set-install-location\" ] && [ \"$6\" = \"0\" ]; then exit 0; fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"pm\" ] && [ \"$5\" = \"trim-caches\" ] && [ \"$6\" = \"2147483648\" ]; then exit 0; fi\n"
            "if [ \"$3\" = \"shell\" ] && [ \"$4\" = \"screencap\" ]; then exit 0; fi\n"
            "if [ \"$3\" = \"pull\" ]; then printf 'png' > \"$5\"; exit 0; fi\n"
            "exit 2\n",
        )
        delete_env = recovery_env.copy()
        delete_env.pop("IFF_RETRY_ALWAYS_FAIL", None)
        delete_env["IFF_UNINSTALL_COUNT"] = str(uninstall_count)
        delete_manifest = root / "delete_recovered_manifest.json"
        delete_recovered = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "delete_recovered.png"),
                "--manifest",
                str(delete_manifest),
                "--android-apk",
                str(apk),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=delete_env,
            timeout=5,
        )
        assert delete_recovered.returncode == 0, delete_recovered.stdout + delete_recovered.stderr
        assert flutter_count.read_text(encoding="utf-8").strip() == "2"
        assert uninstall_count.read_text(encoding="utf-8").strip() == "2"
        delete_log = adb_log.read_text(encoding="utf-8").splitlines()
        clear_command = "-s emulator-5554 shell pm clear com.example.current_test"
        user_query_command = "-s emulator-5554 shell am get-current-user"
        user_uninstall_command = (
            "-s emulator-5554 shell pm uninstall --user 0 com.example.current_test"
        )
        assert delete_log.count(uninstall) == 2, delete_log
        assert delete_log.count(clear_command) == 1, delete_log
        assert delete_log.count(user_query_command) == 1, delete_log
        assert delete_log.count(user_uninstall_command) == 1, delete_log
        delete_provenance = json.loads(delete_manifest.read_text(encoding="utf-8"))[
            "android_storage_recovery"
        ]
        assert delete_provenance["uninstall_attempt_count"] == 2, delete_provenance
        delete_fallback = delete_provenance["delete_internal_error_recovery"]
        assert delete_fallback["trigger"] == "DELETE_FAILED_INTERNAL_ERROR", delete_fallback
        assert delete_fallback["normal_uninstall_retry_count"] == 1, delete_fallback
        assert [item["command"] for item in delete_fallback["commands"]] == [
            "adb -s emulator-5554 shell pm clear com.example.current_test",
            "adb -s emulator-5554 shell am get-current-user",
            "adb -s emulator-5554 shell pm uninstall --user 0 com.example.current_test",
            "adb -s emulator-5554 uninstall com.example.current_test",
        ], delete_fallback

        flutter_count.unlink()
        uninstall_count.unlink()
        adb_log.unlink()
        delete_env["IFF_DELETE_ALWAYS_FAIL"] = "1"
        delete_still_failing = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "delete_still_failing.png"),
                "--manifest",
                str(root / "delete_still_failing_manifest.json"),
                "--android-apk",
                str(apk),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=delete_env,
            timeout=5,
        )
        assert delete_still_failing.returncode != 0, delete_still_failing.stdout
        assert flutter_count.read_text(encoding="utf-8").strip() == "1"
        assert uninstall_count.read_text(encoding="utf-8").strip() == "2"
        delete_failure_log = adb_log.read_text(encoding="utf-8").splitlines()
        assert delete_failure_log.count(uninstall) == 2, delete_failure_log
        assert delete_failure_log.count(clear_command) == 1, delete_failure_log
        assert delete_failure_log.count(user_query_command) == 1, delete_failure_log
        assert delete_failure_log.count(user_uninstall_command) == 1, delete_failure_log
        delete_failure = delete_still_failing.stdout + delete_still_failing.stderr
        assert "DELETE_FAILED_INTERNAL_ERROR" in delete_failure, delete_failure
        assert "after one bounded package-scoped" in delete_failure, delete_failure
        assert "adb -s emulator-5554 shell pm clear com.example.current_test" in delete_failure
        assert "adb -s emulator-5554 shell pm uninstall --user 0 com.example.current_test" in delete_failure
        assert "adb -s emulator-5554 uninstall com.example.current_test" in delete_failure

        contradictory_env = delete_env.copy()
        contradictory_env["IFF_CONTRADICTORY_PACKAGE_STATE"] = "1"
        contradictory_env.pop("IFF_PACKAGE_RESTORE_FAIL", None)
        exact_install_count = root / "exact_install_count"
        contradictory_env["IFF_EXACT_INSTALL_COUNT"] = str(exact_install_count)
        contradictory_env["IFF_EXACT_INSTALL_STORAGE_ONCE"] = "1"
        contradictory_env["IFF_INSTALL_LOCATION"] = "2[external]"
        uninstall_count.write_text("0\n", encoding="utf-8")
        exact_install_count.write_text("0\n", encoding="utf-8")
        flutter_count.write_text("0\n", encoding="utf-8")
        adb_log.write_text("", encoding="utf-8")
        contradictory_manifest = root / "contradictory_recovered_manifest.json"
        contradictory_recovered = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "contradictory_recovered.png"),
                "--manifest",
                str(contradictory_manifest),
                "--android-apk",
                str(apk),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=contradictory_env,
            timeout=5,
        )
        assert contradictory_recovered.returncode == 0, (
            contradictory_recovered.stdout + contradictory_recovered.stderr
        )
        contradictory_log = adb_log.read_text(encoding="utf-8").splitlines()
        install_existing = (
            "-s emulator-5554 shell cmd package install-existing --user 0 "
            "com.example.current_test"
        )
        install_replace = f"-s emulator-5554 install --user 0 -r {apk}"
        assert contradictory_log.count(uninstall) == 2, contradictory_log
        assert contradictory_log.count(install_existing) == 1, contradictory_log
        assert contradictory_log.count(install_replace) == 2, contradictory_log
        storage_get_location = "-s emulator-5554 shell pm get-install-location"
        storage_inspect_data = "-s emulator-5554 shell df -k /data"
        storage_set_auto = "-s emulator-5554 shell pm set-install-location 0"
        storage_trim = "-s emulator-5554 shell pm trim-caches 2147483648"
        assert contradictory_log.count(storage_get_location) == 1, contradictory_log
        assert contradictory_log.count(storage_inspect_data) == 1, contradictory_log
        assert contradictory_log.count(storage_set_auto) == 1, contradictory_log
        assert contradictory_log.count(storage_trim) == 1, contradictory_log
        uninstall_positions = [i for i, command in enumerate(contradictory_log) if command == uninstall]
        assert contradictory_log.index(clear_command) < contradictory_log.index(user_query_command)
        assert contradictory_log.index(user_query_command) < contradictory_log.index(user_uninstall_command)
        assert contradictory_log.index(user_uninstall_command) < uninstall_positions[1]
        assert uninstall_positions[1] < contradictory_log.index(install_existing)
        install_replace_positions = [i for i, command in enumerate(contradictory_log) if command == install_replace]
        assert contradictory_log.index(install_existing) < install_replace_positions[0]
        assert install_replace_positions[0] < contradictory_log.index(storage_get_location)
        assert contradictory_log.index(storage_get_location) < contradictory_log.index(storage_inspect_data)
        assert contradictory_log.index(storage_inspect_data) < contradictory_log.index(storage_set_auto)
        assert contradictory_log.index(storage_set_auto) < contradictory_log.index(storage_trim)
        assert contradictory_log.index(storage_trim) < install_replace_positions[1]
        assert exact_install_count.read_text(encoding="utf-8").strip() == "2"
        assert flutter_count.read_text(encoding="utf-8").strip() == "2"
        contradictory_recovery = json.loads(contradictory_manifest.read_text(encoding="utf-8"))[
            "android_storage_recovery"
        ]["delete_internal_error_recovery"]
        assert contradictory_recovery["contradictory_state_restore_attempted"] is True
        assert contradictory_recovery["restore_attempt_count"] == 1

        contradictory_env.pop("IFF_EXACT_INSTALL_STORAGE_ONCE")
        contradictory_env["IFF_EXACT_INSTALL_ALWAYS_STORAGE"] = "1"
        contradictory_env["IFF_INSTALL_LOCATION"] = "0[auto]"
        uninstall_count.write_text("0\n", encoding="utf-8")
        exact_install_count.write_text("0\n", encoding="utf-8")
        flutter_count.write_text("0\n", encoding="utf-8")
        adb_log.write_text("", encoding="utf-8")
        restore_failed = subprocess.run(
            [
                sys.executable,
                str(capture),
                "--selection",
                str(android_selection),
                "--out",
                str(root / "restore_failed.png"),
                "--manifest",
                str(root / "restore_failed_manifest.json"),
                "--android-apk",
                str(apk),
                "--settle-seconds",
                "0",
                "--command-timeout",
                "0.5",
                "--launch-timeout",
                "0.5",
            ],
            text=True,
            capture_output=True,
            env=contradictory_env,
            timeout=5,
        )
        assert restore_failed.returncode != 0, restore_failed.stdout
        restore_failure_log = adb_log.read_text(encoding="utf-8").splitlines()
        assert restore_failure_log.count(install_existing) == 1, restore_failure_log
        assert restore_failure_log.count(install_replace) == 2, restore_failure_log
        assert restore_failure_log.count(storage_get_location) == 1, restore_failure_log
        assert restore_failure_log.count(storage_inspect_data) == 1, restore_failure_log
        assert restore_failure_log.count(storage_set_auto) == 0, restore_failure_log
        assert restore_failure_log.count(storage_trim) == 1, restore_failure_log
        assert exact_install_count.read_text(encoding="utf-8").strip() == "2"
        restore_failure = restore_failed.stdout + restore_failed.stderr
        assert "exact-package install retry failed after bounded device-storage recovery" in restore_failure
        assert restore_failure.count("Requested internal only, but not enough space") >= 2
        assert "com.example.current_test" in restore_failure
        assert "user 0" in restore_failure
        assert install_existing in restore_failure
        assert install_replace in restore_failure

    print("ok runtime device fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
