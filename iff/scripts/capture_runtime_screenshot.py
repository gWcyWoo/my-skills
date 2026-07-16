#!/usr/bin/env python3
"""Launch Flutter on a device and capture a runtime screenshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import time

from select_runtime_device import SelectionError, ios_devices, run_bounded, select_device
from visual_diff import read_png_rgba


ANDROID_DEBUG_APK = "build/app/outputs/flutter-apk/app-debug.apk"
ANDROID_STORAGE_ERROR = "INSTALL_FAILED_INSUFFICIENT_STORAGE"
ANDROID_DELETE_ERROR = "DELETE_FAILED_INTERNAL_ERROR"
ANDROID_TRIM_CACHE_BYTES = "2147483648"
ANDROID_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")


def run(cmd: list[str], *, timeout: float, label: str) -> subprocess.CompletedProcess[str]:
    try:
        return run_bounded(cmd, timeout)
    except SelectionError as exc:
        raise SystemExit(f"ERROR: {label} failed: {exc}") from exc


def aapt_candidates() -> list[Path]:
    candidates: list[Path] = []
    path_aapt = shutil.which("aapt")
    if path_aapt:
        candidates.append(Path(path_aapt))
    roots = [os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME")]
    roots.extend([str(Path.home() / "Library/Android/sdk"), str(Path.home() / "Android/Sdk")])
    for raw_root in roots:
        if not raw_root:
            continue
        build_tools = Path(raw_root) / "build-tools"
        if not build_tools.is_dir():
            continue
        for version in sorted(build_tools.iterdir(), key=lambda path: path.name, reverse=True):
            candidate = version / "aapt"
            if candidate.is_file():
                candidates.append(candidate)
    return list(dict.fromkeys(candidates))


def android_package_from_apk(apk: Path, command_timeout: float) -> str:
    if not apk.is_file():
        raise SystemExit(
            f"ERROR: Android insufficient-storage recovery blocked: prebuilt APK not found: {apk}"
        )
    diagnostics = []
    for aapt in aapt_candidates():
        try:
            result = run_bounded([str(aapt), "dump", "badging", str(apk)], command_timeout)
        except SelectionError as exc:
            diagnostics.append(str(exc))
            continue
        match = re.search(r"(?m)^package: name='([^']+)'", result.stdout)
        package = match.group(1) if match else ""
        if ANDROID_PACKAGE.fullmatch(package):
            return package
        diagnostics.append(f"invalid or missing package in {aapt} output")
    detail = "; ".join(diagnostics) if diagnostics else "Android SDK aapt was not found"
    raise SystemExit(
        "ERROR: Android insufficient-storage recovery blocked: cannot safely identify the current "
        f"test package from {apk}: {detail}"
    )


def attempt_recorded(cmd: list[str], *, timeout: float, label: str) -> tuple[dict, subprocess.CompletedProcess[str] | None]:
    record = {"command": shlex.join(cmd)}
    try:
        result = run(cmd, timeout=timeout, label=label)
    except SystemExit as exc:
        record.update({"outcome": "failed", "diagnostic": str(exc)})
        return record, None
    record["outcome"] = "success"
    return record, result


def recover_internal_delete_error(
    *,
    device: str,
    package: str,
    apk: Path,
    uninstall_cmd: list[str],
    initial_uninstall_diagnostic: str,
    command_timeout: float,
) -> dict:
    records = []
    clear_cmd = ["adb", "-s", device, "shell", "pm", "clear", package]
    clear_record, _ = attempt_recorded(
        clear_cmd,
        timeout=command_timeout,
        label="package data clear for Android delete recovery",
    )
    records.append(clear_record)

    current_user_cmd = ["adb", "-s", device, "shell", "am", "get-current-user"]
    current_user_record, current_user_result = attempt_recorded(
        current_user_cmd,
        timeout=command_timeout,
        label="current Android user query for delete recovery",
    )
    current_user = current_user_result.stdout.strip() if current_user_result else ""
    if current_user_result and not re.fullmatch(r"[0-9]+", current_user):
        current_user_record.update(
            {"outcome": "failed", "diagnostic": f"invalid current Android user: {current_user!r}"}
        )
        current_user_result = None
    records.append(current_user_record)

    user_uninstall_record = None
    if current_user_result:
        user_uninstall_cmd = [
            "adb", "-s", device, "shell", "pm", "uninstall", "--user", current_user, package
        ]
        user_uninstall_record, _ = attempt_recorded(
            user_uninstall_cmd,
            timeout=command_timeout,
            label="current-user package uninstall for Android delete recovery",
        )
        records.append(user_uninstall_record)

    retry_record, retry_result = attempt_recorded(
        uninstall_cmd,
        timeout=command_timeout,
        label="normal package uninstall retry after Android delete recovery",
    )
    records.append(retry_record)
    if retry_result is None:
        contradictory_state = (
            clear_record.get("outcome") == "failed"
            and isinstance(user_uninstall_record, dict)
            and user_uninstall_record.get("outcome") == "failed"
            and f"not installed for {current_user}" in user_uninstall_record.get("diagnostic", "")
            and ANDROID_DELETE_ERROR in retry_record.get("diagnostic", "")
        )
        if contradictory_state:
            install_existing_cmd = [
                "adb", "-s", device, "shell", "cmd", "package", "install-existing",
                "--user", current_user, package,
            ]
            install_existing_record, _ = attempt_recorded(
                install_existing_cmd,
                timeout=command_timeout,
                label="selected-user package restore after contradictory Android delete state",
            )
            records.append(install_existing_record)
            install_replace_cmd = [
                "adb", "-s", device, "install", "--user", current_user, "-r", str(apk),
            ]
            install_replace_record, install_replace_result = attempt_recorded(
                install_replace_cmd,
                timeout=command_timeout,
                label="exact APK install-replace after contradictory Android delete state",
            )
            records.append(install_replace_record)
            exact_install_storage_recovery = {"attempted": False}
            exact_install_retry_count = 0
            if install_replace_result is None:
                initial_install_diagnostic = str(install_replace_record.get("diagnostic") or "")
                storage_failure = (
                    ANDROID_STORAGE_ERROR in initial_install_diagnostic
                    or "Requested internal only, but not enough space" in initial_install_diagnostic
                )
                if not storage_failure:
                    raise SystemExit(
                        "ERROR: one additional bounded exact-package selected-user restore/install "
                        f"attempt failed for {package} user {current_user}; commands: "
                        f"{json.dumps(records, sort_keys=True)}"
                    )
                try:
                    exact_install_storage_recovery = recover_android_device_storage(
                        device=device,
                        command_timeout=command_timeout,
                    )
                except SystemExit as storage_error:
                    raise SystemExit(
                        "ERROR: exact-package install storage recovery failed for "
                        f"{package} user {current_user}; initial install diagnostic: "
                        f"{initial_install_diagnostic}; storage diagnostic: {storage_error}"
                    ) from storage_error
                exact_install_retry_count = 1
                retry_record, install_replace_result = attempt_recorded(
                    install_replace_cmd,
                    timeout=command_timeout,
                    label="exact APK install retry after bounded Android device-storage recovery",
                )
                records.append(retry_record)
                if install_replace_result is None:
                    raise SystemExit(
                        "ERROR: exact-package install retry failed after bounded device-storage "
                        f"recovery for {package} user {current_user}; initial install diagnostic: "
                        f"{initial_install_diagnostic}; retry diagnostic: "
                        f"{retry_record.get('diagnostic')}; commands: "
                        f"{json.dumps(records, sort_keys=True)}"
                    )
            return {
                "trigger": ANDROID_DELETE_ERROR,
                "commands": records,
                "normal_uninstall_retry_count": 1,
                "contradictory_state_restore_attempted": True,
                "restore_attempt_count": 1,
                "exact_install_storage_recovery": exact_install_storage_recovery,
                "exact_install_retry_count": exact_install_retry_count,
                "package": package,
                "user": current_user,
            }
        raise SystemExit(
            "ERROR: Android package uninstall retry failed after one bounded package-scoped "
            f"DELETE_FAILED_INTERNAL_ERROR recovery for {package}; initial uninstall: "
            f"{initial_uninstall_diagnostic}; commands: {json.dumps(records, sort_keys=True)}"
        )
    return {
        "trigger": ANDROID_DELETE_ERROR,
        "commands": records,
        "normal_uninstall_retry_count": 1,
    }


def recover_android_device_storage(*, device: str, command_timeout: float) -> dict:
    get_location_cmd = ["adb", "-s", device, "shell", "pm", "get-install-location"]
    inspect_data_cmd = ["adb", "-s", device, "shell", "df", "-k", "/data"]
    set_auto_cmd = ["adb", "-s", device, "shell", "pm", "set-install-location", "0"]
    trim_caches_cmd = ["adb", "-s", device, "shell", "pm", "trim-caches", ANDROID_TRIM_CACHE_BYTES]
    location_result = run(
        get_location_cmd,
        timeout=command_timeout,
        label="Android install-location inspection",
    )
    data_result = run(
        inspect_data_cmd,
        timeout=command_timeout,
        label="Android /data free-space inspection",
    )
    location = location_result.stdout.strip()
    location_code = location.split("[", 1)[0].strip()
    if location_code not in {"0", "1", "2"}:
        raise SystemExit(f"ERROR: unrecognized Android install location for {device}: {location!r}")
    install_location_reset = location_code != "0"
    if install_location_reset:
        run(set_auto_cmd, timeout=command_timeout, label="Android install-location reset to auto")
    run(trim_caches_cmd, timeout=command_timeout, label="Android package-manager cache trim")
    return {
        "attempted": True,
        "install_location": location,
        "data_free_space": data_result.stdout.strip(),
        "install_location_reset": install_location_reset,
        "trim_cache_bytes": ANDROID_TRIM_CACHE_BYTES,
    }


def launch_with_android_storage_recovery(
    run_cmd: list[str],
    *,
    device: str,
    apk: Path,
    command_timeout: float,
    launch_timeout: float,
) -> dict:
    recovery = {"attempted": False}
    initial_diagnostic = ""
    try:
        run(run_cmd, timeout=launch_timeout, label="bounded Flutter launch")
        return recovery
    except SystemExit as initial_error:
        if ANDROID_STORAGE_ERROR not in str(initial_error):
            raise
        initial_diagnostic = str(initial_error)

    try:
        package = android_package_from_apk(apk, command_timeout)
    except SystemExit as package_error:
        raise SystemExit(f"{initial_diagnostic}\n{package_error}") from package_error
    uninstall_cmd = ["adb", "-s", device, "uninstall", package]
    delete_recovery = None
    try:
        run(uninstall_cmd, timeout=command_timeout, label="package-only Android storage recovery")
    except SystemExit as uninstall_error:
        uninstall_diagnostic = str(uninstall_error)
        if ANDROID_DELETE_ERROR not in uninstall_diagnostic:
            raise SystemExit(
                f"{initial_diagnostic}\nERROR: Android insufficient-storage recovery failed before retry for "
                f"package {package}: {uninstall_diagnostic}"
            ) from uninstall_error
        try:
            delete_recovery = recover_internal_delete_error(
                device=device,
                package=package,
                apk=apk,
                uninstall_cmd=uninstall_cmd,
                initial_uninstall_diagnostic=uninstall_diagnostic,
                command_timeout=command_timeout,
            )
        except SystemExit as delete_error:
            raise SystemExit(f"{initial_diagnostic}\n{delete_error}") from delete_error
    device_storage_recovery = {"attempted": False}
    final_launch_retry_count = 0
    try:
        run(run_cmd, timeout=launch_timeout, label="bounded Flutter launch retry")
    except SystemExit as retry_error:
        if ANDROID_STORAGE_ERROR not in str(retry_error):
            raise SystemExit(
                f"{initial_diagnostic}\nERROR: Android insufficient-storage recovery retry failed for package "
                f"{package} after one package-only uninstall: {retry_error}"
            ) from retry_error
        try:
            device_storage_recovery = recover_android_device_storage(
                device=device,
                command_timeout=command_timeout,
            )
        except SystemExit as storage_error:
            raise SystemExit(
                f"{initial_diagnostic}\nERROR: bounded Android device-storage recovery failed for package "
                f"{package} on {device}: {storage_error}"
            ) from storage_error
        final_launch_retry_count = 1
        try:
            run(run_cmd, timeout=launch_timeout, label="bounded Flutter final launch retry")
        except SystemExit as final_error:
            raise SystemExit(
                f"{initial_diagnostic}\nERROR: Android final launch retry failed after bounded device-storage "
                f"recovery for package {package} on {device}: {final_error}"
            ) from final_error
    return {
        "attempted": True,
        "reason": ANDROID_STORAGE_ERROR,
        "package": package,
        "apk": str(apk),
        "uninstall_command": shlex.join(uninstall_cmd),
        "uninstall_attempt_count": 2 if delete_recovery else 1,
        "delete_internal_error_recovery": delete_recovery,
        "install_retry_count": 1,
        "device_storage_recovery": device_storage_recovery,
        "final_launch_retry_count": final_launch_retry_count,
        "outcome": "recovered",
    }


def load_selection(path: Path) -> dict:
    try:
        selection = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: invalid runtime device selection {path}: {exc}") from exc
    platform = selection.get("platform")
    device = selection.get("device")
    if platform not in {"android", "ios"} or not isinstance(device, str) or not device:
        raise SystemExit(f"ERROR: runtime device selection lacks platform/device: {path}")
    if selection.get("actualSource") != "simulator_screenshot":
        raise SystemExit(f"ERROR: runtime device selection has invalid provenance: {path}")
    return selection


def png_dimensions(path: Path, *, label: str) -> tuple[int, int]:
    try:
        header = path.read_bytes()[:24]
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot read {label} PNG: {path}; {exc}") from exc
    if (
        len(header) != 24
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or header[12:16] != b"IHDR"
    ):
        raise SystemExit(f"ERROR: {label} is not a valid PNG with an IHDR header: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise SystemExit(f"ERROR: {label} PNG has invalid dimensions {width}x{height}: {path}")
    return width, height


def frame_mismatch_ratio(
    first: Path,
    second: Path,
    *,
    color_delta: int = 12,
    sample_limit: int = 250_000,
) -> float:
    first_width, first_height, first_pixels = read_png_rgba(first)
    second_width, second_height, second_pixels = read_png_rgba(second)
    if (first_width, first_height) != (second_width, second_height):
        return 1.0
    stride = max(1, len(first_pixels) // max(1, sample_limit))
    sampled = range(0, len(first_pixels), stride)
    mismatches = sum(
        1
        for index in sampled
        if max(abs(first_pixels[index][channel] - second_pixels[index][channel]) for channel in range(3)) > color_delta
    )
    sample_count = (len(first_pixels) + stride - 1) // stride
    return mismatches / max(1, sample_count)


def unexpected_dark_ratio(
    reference: Path,
    candidate: Path,
    *,
    sample_limit: int = 250_000,
) -> float:
    ref_width, ref_height, ref_pixels = read_png_rgba(reference)
    act_width, act_height, act_pixels = read_png_rgba(candidate)
    if (ref_width, ref_height) != (act_width, act_height):
        return 1.0
    stride = max(1, len(ref_pixels) // max(1, sample_limit))
    sampled = range(0, len(ref_pixels), stride)
    unexpected = 0
    eligible = 0
    for index in sampled:
        ref = ref_pixels[index]
        act = act_pixels[index]
        if ref[3] and max(ref[:3]) >= 96:
            eligible += 1
            if act[3] and max(act[:3]) <= 24:
                unexpected += 1
    return unexpected / max(1, eligible)


def select_stable_candidate(
    candidates: list[Path],
    *,
    reference_path: Path | None,
    stable_samples: int,
    mismatch_threshold: float,
    unexpected_dark_threshold: float,
) -> Path | None:
    previous: Path | None = None
    stable_count = 0
    for candidate in candidates:
        if reference_path is not None and unexpected_dark_ratio(reference_path, candidate) > unexpected_dark_threshold:
            previous = None
            stable_count = 0
            continue
        if previous is not None and frame_mismatch_ratio(previous, candidate) <= mismatch_threshold:
            stable_count += 1
        else:
            stable_count = 1
        previous = candidate
        if stable_count >= stable_samples:
            return candidate
    return None


def resolve_capture_dimensions(
    *, reference: str | None, width: int | None, height: int | None
) -> tuple[Path | None, tuple[int, int] | None]:
    if reference:
        reference_path = Path(reference).absolute()
        reference_dimensions = png_dimensions(reference_path, label="board reference")
        if width is not None or height is not None:
            if (width, height) != reference_dimensions:
                raise SystemExit(
                    "ERROR: explicit capture dimensions conflict with board reference: "
                    f"requested={width}x{height} reference="
                    f"{reference_dimensions[0]}x{reference_dimensions[1]}"
                )
        return reference_path, reference_dimensions
    if (width is None) != (height is None):
        raise SystemExit("ERROR: --width and --height must be provided together")
    if width is not None and height is not None:
        if width <= 0 or height <= 0:
            raise SystemExit(f"ERROR: capture dimensions must be positive: {width}x{height}")
        return None, (width, height)
    return None, None


def verify_ready(platform: str, device: str, command_timeout: float, boot_timeout: float) -> None:
    if platform == "android":
        result = run_bounded(["adb", "devices"], command_timeout)
        states = {
            fields[0]: fields[1]
            for line in result.stdout.splitlines()[1:]
            if len(fields := line.split()) >= 2
        }
        state = states.get(device)
        if state is None:
            raise SystemExit(f"ERROR: selected Android emulator is not connected: {device}")
        if state != "device":
            raise SystemExit(f"ERROR: selected Android emulator is {state}: {device}")
        if boot_timeout <= 0:
            raise SystemExit("ERROR: Android boot timeout must be positive")

        deadline = time.monotonic() + boot_timeout
        boot_state = "not-probed"
        package_state = "not-probed"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SystemExit(
                    f"ERROR: selected Android emulator readiness timed out after {boot_timeout:g}s: "
                    f"{device}; sys.boot_completed={boot_state}; package-manager={package_state}"
                )
            probe_timeout = max(0.01, min(command_timeout, remaining))
            try:
                boot = run_bounded(
                    ["adb", "-s", device, "shell", "getprop", "sys.boot_completed"],
                    probe_timeout,
                )
                boot_state = boot.stdout.strip() or "empty"
            except SelectionError as exc:
                if "offline" in str(exc).lower():
                    raise SystemExit(
                        f"ERROR: selected Android emulator went offline during readiness wait: {device}; {exc}"
                    ) from exc
                boot_state = f"error: {exc}"

            if boot_state == "1":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    continue
                probe_timeout = max(0.01, min(command_timeout, remaining))
                try:
                    package = run_bounded(
                        ["adb", "-s", device, "shell", "pm", "path", "android"],
                        probe_timeout,
                    )
                    package_state = package.stdout.strip() or "empty"
                    if package_state.startswith("package:"):
                        return
                except SelectionError as exc:
                    if "offline" in str(exc).lower():
                        raise SystemExit(
                            f"ERROR: selected Android emulator went offline during readiness wait: {device}; {exc}"
                        ) from exc
                    package_state = f"error: {exc}"

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.25, remaining))
    result = run_bounded(
        ["xcrun", "simctl", "list", "devices", "available", "--json"],
        command_timeout,
    )
    if not any(item["udid"] == device and item["state"] == "Booted" for item in ios_devices(result.stdout)):
        raise SystemExit(f"ERROR: selected iOS Simulator is not booted: {device}")


def android_flutter_run_command(*, device: str, apk: Path, route: str) -> tuple[list[str], str]:
    resolved_apk = apk.absolute()
    filename = resolved_apk.name.lower()
    modes = [mode for mode in ("debug", "profile", "release") if filename.endswith(f"-{mode}.apk")]
    if len(modes) != 1:
        raise SystemExit(
            "ERROR: cannot infer Android APK build mode from deterministic filename suffix "
            f"(-debug.apk, -profile.apk, or -release.apk): {resolved_apk}"
        )
    mode = modes[0]
    command = [
        "flutter",
        "run",
        "-d",
        device,
        f"--{mode}",
        "--no-resident",
        f"--use-application-binary={resolved_apk}",
    ]
    if route:
        command.append(f"--route={route}")
    return command, mode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["auto", "android", "ios"])
    parser.add_argument("--device")
    parser.add_argument("--selection", help="JSON emitted by select_runtime_device.py")
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reference", help="selected board reference PNG; its raw pixel size is mandatory")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--density", type=int, default=160)
    parser.add_argument("--route", help="named initial route to launch (flutter run --route), so a "
                        "non-home feature page can be screenshotted WITHOUT mutating main.dart's initialRoute")
    parser.add_argument("--settle-seconds", type=float, default=5.0)
    parser.add_argument("--stability-samples", type=int, default=2)
    parser.add_argument("--max-capture-attempts", type=int, default=4)
    parser.add_argument("--stability-interval", type=float, default=0.75)
    parser.add_argument("--stability-mismatch-threshold", type=float, default=0.02)
    parser.add_argument("--unexpected-dark-threshold", type=float, default=0.10)
    parser.add_argument("--command-timeout", type=float, default=15.0)
    parser.add_argument("--launch-timeout", type=float, default=300.0)
    parser.add_argument("--boot-timeout", type=float, default=120.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--android-apk", default=ANDROID_DEBUG_APK)
    args = parser.parse_args()

    if args.command_timeout <= 0 or args.launch_timeout <= 0:
        raise SystemExit("ERROR: command and launch timeouts must be greater than zero")
    if args.stability_samples < 2:
        raise SystemExit("ERROR: stability-samples must be at least 2")
    if args.max_capture_attempts < args.stability_samples:
        raise SystemExit("ERROR: max-capture-attempts must be >= stability-samples")
    if args.stability_interval < 0:
        raise SystemExit("ERROR: stability-interval must be non-negative")
    if not 0 <= args.stability_mismatch_threshold <= 1:
        raise SystemExit("ERROR: stability-mismatch-threshold must be between 0 and 1")
    if not 0 <= args.unexpected_dark_threshold <= 1:
        raise SystemExit("ERROR: unexpected-dark-threshold must be between 0 and 1")
    if args.selection:
        selection = load_selection(Path(args.selection))
        if args.platform and args.platform != "auto" and args.platform != selection["platform"]:
            raise SystemExit("ERROR: --platform contradicts --selection")
        if args.device and args.device != selection["device"]:
            raise SystemExit("ERROR: --device contradicts --selection")
    elif args.platform == "auto" or (args.platform and not args.device):
        try:
            selection = select_device(
                platform=args.platform or "auto",
                command_timeout=args.command_timeout,
                boot_timeout=args.boot_timeout,
                poll_interval=args.poll_interval,
            )
        except SelectionError as exc:
            raise SystemExit(f"ERROR: runtime device selection failed: {exc}") from exc
        selection["actualSource"] = "simulator_screenshot"
    elif args.platform and args.device:
        selection = {
            "platform": args.platform,
            "device": args.device,
            "deviceName": args.device,
            "origin": "explicit",
            "actualSource": "simulator_screenshot",
            "fallbackReason": None,
        }
    else:
        raise SystemExit("ERROR: pass --selection, --platform auto, or both --platform and --device")
    platform = str(selection["platform"])
    device = str(selection["device"])
    reference_path, expected_dimensions = resolve_capture_dimensions(
        reference=args.reference,
        width=args.width,
        height=args.height,
    )
    try:
        verify_ready(platform, device, args.command_timeout, args.boot_timeout)
    except SelectionError as exc:
        raise SystemExit(f"ERROR: selected runtime device probe failed: {exc}") from exc

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    setup_commands = []
    if platform == "android" and expected_dimensions:
        expected_width, expected_height = expected_dimensions
        setup_commands.append(f"adb -s {device} shell wm size {expected_width}x{expected_height}")
        setup_commands.append(f"adb -s {device} shell wm density {args.density}")
        run(
            ["adb", "-s", device, "shell", "wm", "size", f"{expected_width}x{expected_height}"],
            timeout=args.command_timeout,
            label="Android viewport setup",
        )
        run(
            ["adb", "-s", device, "shell", "wm", "density", str(args.density)],
            timeout=args.command_timeout,
            label="Android density setup",
        )
    android_apk: Path | None = None
    android_apk_mode: str | None = None
    if platform == "android":
        android_apk = Path(args.android_apk).absolute()
        run_cmd, android_apk_mode = android_flutter_run_command(
            device=device,
            apk=android_apk,
            route=args.route,
        )
    else:
        run_cmd = ["flutter", "run", "-d", device, "--debug", "--no-resident"]
        if args.route:
            run_cmd.append(f"--route={args.route}")
    android_storage_recovery = {"attempted": False}
    if platform == "android":
        android_storage_recovery = launch_with_android_storage_recovery(
            run_cmd,
            device=device,
            apk=android_apk,
            command_timeout=args.command_timeout,
            launch_timeout=args.launch_timeout,
        )
    else:
        run(run_cmd, timeout=args.launch_timeout, label="bounded Flutter launch")
    if args.settle_seconds > 0:
        time.sleep(args.settle_seconds)
    candidates: list[Path] = []
    capture_command = ""
    selected_candidate: Path | None = None
    with tempfile.TemporaryDirectory(prefix="iff_capture_") as capture_tmp:
        capture_root = Path(capture_tmp)
        for attempt in range(args.max_capture_attempts):
            candidate = capture_root / f"candidate_{attempt + 1}.png"
            if platform == "android":
                remote = f"/sdcard/iff_actual_{attempt + 1}.png"
                capture_argv = ["adb", "-s", device, "shell", "screencap", "-p", remote]
                capture_command = shlex.join(capture_argv)
                run(capture_argv, timeout=args.command_timeout, label="Android screenshot capture")
                run(
                    ["adb", "-s", device, "pull", remote, str(candidate)],
                    timeout=args.command_timeout,
                    label="Android screenshot pull",
                )
            else:
                capture_argv = ["xcrun", "simctl", "io", device, "screenshot", str(candidate)]
                capture_command = shlex.join(capture_argv)
                run(capture_argv, timeout=args.command_timeout, label="iOS Simulator screenshot capture")
            candidates.append(candidate)
            selected_candidate = select_stable_candidate(
                candidates,
                reference_path=reference_path,
                stable_samples=args.stability_samples,
                mismatch_threshold=args.stability_mismatch_threshold,
                unexpected_dark_threshold=args.unexpected_dark_threshold,
            )
            if selected_candidate is not None:
                shutil.copyfile(selected_candidate, out)
                break
            if attempt + 1 < args.max_capture_attempts and args.stability_interval > 0:
                time.sleep(args.stability_interval)
        if selected_candidate is None:
            raise SystemExit(
                "ERROR: no stable, non-corrupted screenshot frame after "
                f"{args.max_capture_attempts} attempts"
            )
    if not out.is_file() or out.stat().st_size == 0:
        raise SystemExit(f"ERROR: screenshot was not created: {out}")
    captured_dimensions = png_dimensions(out, label="captured screenshot") if expected_dimensions else None
    if expected_dimensions and captured_dimensions != expected_dimensions:
        raise SystemExit(
            f"ERROR: captured screenshot size {captured_dimensions[0]}x{captured_dimensions[1]} "
            f"does not match reference {expected_dimensions[0]}x{expected_dimensions[1]}; "
            "resizing is forbidden"
        )
    manifest_path = Path(args.manifest)
    data = {}
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data.update(
        {
            "actual_source": "simulator_screenshot",
            "platform": platform,
            "device_id": device,
            "device_selection": selection,
            "viewport": {
                "width": expected_dimensions[0] if expected_dimensions else None,
                "height": expected_dimensions[1] if expected_dimensions else None,
                "density": args.density,
            },
            "reference_path": str(reference_path) if reference_path else None,
            "reference_dimensions": (
                {"width": expected_dimensions[0], "height": expected_dimensions[1]}
                if expected_dimensions
                else None
            ),
            "captured_dimensions": (
                {"width": captured_dimensions[0], "height": captured_dimensions[1]}
                if captured_dimensions
                else None
            ),
            "setup_commands": setup_commands,
            "settle_seconds": args.settle_seconds,
            "frame_stability": {
                "required_samples": args.stability_samples,
                "attempts": len(candidates),
                "mismatch_threshold": args.stability_mismatch_threshold,
                "unexpected_dark_threshold": args.unexpected_dark_threshold,
                "reference_aware": reference_path is not None,
            },
            "capture_command": capture_command,
            "android_storage_recovery": android_storage_recovery,
            "android_apk": str(android_apk) if android_apk else None,
            "android_apk_mode": android_apk_mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actual_path": str(out),
        }
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
