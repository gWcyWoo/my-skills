#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture_runtime_screenshot as capture
from select_runtime_device import SelectionError


DEVICE = "emulator-5554"


def completed(argv: list[str], stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, 0, stdout, "")


def main() -> int:
    original_run = capture.run_bounded
    original_monotonic = capture.time.monotonic
    original_sleep = capture.time.sleep
    clock = [0.0]
    capture.time.monotonic = lambda: clock[0]
    capture.time.sleep = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    try:
        calls: list[list[str]] = []
        boot_values = iter(["0\n", "1\n", "1\n"])
        package_attempts = [0]

        def recovering_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            calls.append(argv)
            if argv == ["adb", "devices"]:
                return completed(argv, f"List of devices attached\n{DEVICE}\tdevice\n")
            if argv[-2:] == ["getprop", "sys.boot_completed"]:
                return completed(argv, next(boot_values))
            if argv[-4:] == ["shell", "pm", "path", "android"]:
                package_attempts[0] += 1
                if package_attempts[0] == 1:
                    raise SelectionError("package manager is not ready")
                return completed(argv, "package:/system/framework/framework-res.apk\n")
            raise AssertionError(argv)

        capture.run_bounded = recovering_run
        capture.verify_ready("android", DEVICE, command_timeout=2.0, boot_timeout=5.0)
        assert calls == [
            ["adb", "devices"],
            ["adb", "-s", DEVICE, "shell", "getprop", "sys.boot_completed"],
            ["adb", "-s", DEVICE, "shell", "getprop", "sys.boot_completed"],
            ["adb", "-s", DEVICE, "shell", "pm", "path", "android"],
            ["adb", "-s", DEVICE, "shell", "getprop", "sys.boot_completed"],
            ["adb", "-s", DEVICE, "shell", "pm", "path", "android"],
        ], calls

        offline_calls: list[list[str]] = []

        def offline_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            offline_calls.append(argv)
            return completed(argv, f"List of devices attached\n{DEVICE}\toffline\n")

        capture.run_bounded = offline_run
        try:
            capture.verify_ready("android", DEVICE, command_timeout=2.0, boot_timeout=5.0)
        except SystemExit as exc:
            assert "is offline" in str(exc), exc
        else:
            raise AssertionError("offline emulator was accepted")
        assert offline_calls == [["adb", "devices"]], offline_calls

        timeout_calls: list[list[str]] = []
        clock[0] = 0.0

        def timeout_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            timeout_calls.append(argv)
            if argv == ["adb", "devices"]:
                return completed(argv, f"List of devices attached\n{DEVICE}\tdevice\n")
            return completed(argv, "0\n")

        capture.run_bounded = timeout_run
        try:
            capture.verify_ready("android", DEVICE, command_timeout=2.0, boot_timeout=0.5)
        except SystemExit as exc:
            message = str(exc)
            assert "readiness timed out after 0.5s" in message, message
            assert "sys.boot_completed=0" in message, message
        else:
            raise AssertionError("unbooted emulator was accepted")
        assert all("pm" not in command for command in timeout_calls), timeout_calls
    finally:
        capture.run_bounded = original_run
        capture.time.monotonic = original_monotonic
        capture.time.sleep = original_sleep

    print("PASS: post-wipe Android readiness is bounded and fails visibly offline/timeout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
