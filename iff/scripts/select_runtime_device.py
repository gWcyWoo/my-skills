#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time
from typing import Any


class SelectionError(RuntimeError):
    pass


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _detail(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    parts = [_text(stderr).strip(), _text(stdout).strip()]
    return " | ".join(part for part in parts if part) or "no stdout/stderr"


def run_bounded(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        process = subprocess.Popen(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise SelectionError(f"command not found: {argv[0]}") from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            stdout, stderr = _text(exc.stdout), _text(exc.stderr)
        raise SelectionError(
            f"command timed out after {timeout:g}s: {shlex.join(argv)}; "
            f"{_detail(stdout, stderr)}"
        ) from exc
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    if process.returncode != 0:
        raise SelectionError(
            f"command exited {process.returncode}: {shlex.join(argv)}; "
            f"{_detail(stdout, stderr)}"
        )
    return result


def android_ready_devices(output: str) -> list[str]:
    devices: list[str] = []
    for raw_line in output.splitlines()[1:]:
        fields = raw_line.strip().split()
        if len(fields) >= 2 and fields[1] == "device" and fields[0].startswith("emulator-"):
            devices.append(fields[0])
    return sorted(set(devices))


def _ready_android(command_timeout: float) -> list[str]:
    result = run_bounded(["adb", "devices"], command_timeout)
    return android_ready_devices(result.stdout)


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass


def select_android(
    *,
    command_timeout: float,
    boot_timeout: float,
    poll_interval: float,
    preferred_device: str | None,
    preferred_avd: str | None,
) -> dict[str, Any]:
    ready = _ready_android(command_timeout)
    if preferred_device:
        if preferred_device in ready:
            return {
                "platform": "android",
                "device": preferred_device,
                "deviceName": preferred_device,
                "origin": "existing",
            }
        raise SelectionError(
            f"requested Android emulator is not ready: {preferred_device}; ready={ready}"
        )
    if ready:
        device = ready[0]
        return {
            "platform": "android",
            "device": device,
            "deviceName": device,
            "origin": "existing",
        }

    avd_result = run_bounded(["emulator", "-list-avds"], command_timeout)
    avds = sorted({line.strip() for line in avd_result.stdout.splitlines() if line.strip()})
    if preferred_avd:
        if preferred_avd not in avds:
            raise SelectionError(
                f"requested Android AVD does not exist: {preferred_avd}; available={avds}"
            )
        avd = preferred_avd
    elif avds:
        avd = avds[0]
    else:
        raise SelectionError("no ready Android emulator and emulator -list-avds returned no AVDs")

    argv = ["emulator", "-avd", avd, "-no-boot-anim", "-no-snapshot-save"]
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(
                argv,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise SelectionError("command not found: emulator") from exc
        deadline = time.monotonic() + boot_timeout
        try:
            while time.monotonic() < deadline:
                returncode = process.poll()
                if returncode is not None:
                    log.flush()
                    log.seek(0)
                    diagnostic = log.read().strip() or "no stdout/stderr"
                    raise SelectionError(
                        f"Android AVD {avd} exited {returncode} before becoming ready: {diagnostic}"
                    )
                ready = _ready_android(command_timeout)
                if ready:
                    device = ready[0]
                    return {
                        "platform": "android",
                        "device": device,
                        "deviceName": avd,
                        "origin": "launched",
                    }
                time.sleep(poll_interval)
            log.flush()
            log.seek(0)
            diagnostic = log.read().strip() or "no stdout/stderr"
            raise SelectionError(
                f"Android AVD {avd} did not become ready within {boot_timeout:g}s: {diagnostic}"
            )
        except BaseException:
            _terminate_process_group(process)
            raise


def ios_devices(output: str) -> list[dict[str, str]]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise SelectionError(f"invalid simctl device JSON: {exc}") from exc
    found: list[dict[str, str]] = []
    for runtime, devices in payload.get("devices", {}).items():
        if ".iOS-" not in runtime or not isinstance(devices, list):
            continue
        for device in devices:
            if not isinstance(device, dict) or not device.get("isAvailable", True):
                continue
            device_type = str(device.get("deviceTypeIdentifier", ""))
            if ".iPhone-" not in device_type and ".iPad-" not in device_type:
                continue
            udid = str(device.get("udid", "")).strip()
            if not udid:
                continue
            found.append(
                {
                    "runtime": runtime,
                    "name": str(device.get("name", udid)),
                    "udid": udid,
                    "state": str(device.get("state", "")),
                }
            )
    return sorted(found, key=lambda item: (item["state"] != "Booted", item["runtime"], item["name"], item["udid"]))


def _available_ios(command_timeout: float) -> list[dict[str, str]]:
    result = run_bounded(
        ["xcrun", "simctl", "list", "devices", "available", "--json"],
        command_timeout,
    )
    return ios_devices(result.stdout)


def select_ios(
    *,
    command_timeout: float,
    boot_timeout: float,
    poll_interval: float,
    preferred_device: str | None,
) -> dict[str, Any]:
    devices = _available_ios(command_timeout)
    if preferred_device:
        matches = [device for device in devices if device["udid"] == preferred_device]
        if not matches:
            raise SelectionError(f"requested iOS Simulator is unavailable: {preferred_device}")
        candidate = matches[0]
    else:
        booted = [device for device in devices if device["state"] == "Booted"]
        candidate = booted[0] if booted else (devices[0] if devices else None)
    if candidate is None:
        raise SelectionError("no available iPhone/iPad Simulator devices")
    if candidate["state"] == "Booted":
        return {
            "platform": "ios",
            "device": candidate["udid"],
            "deviceName": candidate["name"],
            "origin": "existing",
        }

    run_bounded(["xcrun", "simctl", "boot", candidate["udid"]], command_timeout)
    deadline = time.monotonic() + boot_timeout
    while time.monotonic() < deadline:
        current = _available_ios(command_timeout)
        if any(
            device["udid"] == candidate["udid"] and device["state"] == "Booted"
            for device in current
        ):
            return {
                "platform": "ios",
                "device": candidate["udid"],
                "deviceName": candidate["name"],
                "origin": "booted",
            }
        time.sleep(poll_interval)
    raise SelectionError(
        f"iOS Simulator {candidate['name']} ({candidate['udid']}) did not boot within {boot_timeout:g}s"
    )


def select_device(
    *,
    platform: str,
    command_timeout: float,
    boot_timeout: float,
    poll_interval: float,
    android_device: str | None = None,
    android_avd: str | None = None,
    ios_device: str | None = None,
) -> dict[str, Any]:
    if command_timeout <= 0 or boot_timeout <= 0 or poll_interval <= 0:
        raise SelectionError("command, boot, and poll timeouts must all be greater than zero")
    android_failure: str | None = None
    if platform in {"auto", "android"}:
        try:
            selected = select_android(
                command_timeout=command_timeout,
                boot_timeout=boot_timeout,
                poll_interval=poll_interval,
                preferred_device=android_device,
                preferred_avd=android_avd,
            )
            selected["fallbackReason"] = None
            return selected
        except SelectionError as exc:
            android_failure = str(exc)
            if platform == "android":
                raise
    try:
        selected = select_ios(
            command_timeout=command_timeout,
            boot_timeout=boot_timeout,
            poll_interval=poll_interval,
            preferred_device=ios_device,
        )
    except SelectionError as exc:
        if android_failure:
            raise SelectionError(
                f"Android selection failed: {android_failure}; iOS Simulator fallback failed: {exc}"
            ) from exc
        raise
    selected["fallbackReason"] = (
        f"Android selection failed: {android_failure}" if android_failure else None
    )
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["auto", "android", "ios"], default="auto")
    parser.add_argument("--android-device")
    parser.add_argument("--android-avd")
    parser.add_argument("--ios-device")
    parser.add_argument("--command-timeout", type=float, default=10.0)
    parser.add_argument("--boot-timeout", type=float, default=120.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        selected = select_device(
            platform=args.platform,
            command_timeout=args.command_timeout,
            boot_timeout=args.boot_timeout,
            poll_interval=args.poll_interval,
            android_device=args.android_device,
            android_avd=args.android_avd,
            ios_device=args.ios_device,
        )
    except SelectionError as exc:
        raise SystemExit(f"ERROR: runtime device selection failed: {exc}") from exc
    selected.update(
        {
            "schemaVersion": 1,
            "actualSource": "simulator_screenshot",
            "selectedAt": datetime.now(timezone.utc).isoformat(),
            "selectionCommand": shlex.join(["select_runtime_device.py", *os.sys.argv[1:]]),
        }
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    temporary.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(out)
    print(json.dumps(selected, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
