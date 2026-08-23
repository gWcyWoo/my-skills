#!/usr/bin/env python3
"""Android device driver for ICP's reversible visual-capture protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pwd
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path


class DriverError(Exception):
    pass


ACTIVE_ADB_SERIAL: str | None = None


def logical_scale(value: object) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise DriverError("runtime probes target another visual state or renderer")
    try:
        scale = Fraction(value)
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        raise DriverError(
            "runtime probes target another visual state or renderer"
        ) from exc
    if scale <= 0:
        raise DriverError("runtime probes target another visual state or renderer")
    return scale


def resolve_adb_binary() -> str:
    user_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    candidates = (
        user_home / "Library/Android/sdk/platform-tools/adb",
        Path("/opt/android-sdk/platform-tools/adb"),
        Path("/usr/local/android-sdk/platform-tools/adb"),
        Path("/opt/homebrew/bin/adb"),
        Path("/usr/local/bin/adb"),
        Path("/usr/bin/adb"),
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved)
    raise DriverError("adb was not found in the trusted Android SDK locations")


def resolve_apkanalyzer_binary() -> str:
    user_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    sdk_roots = [
        Path(value)
        for value in (
            os.environ.get("ANDROID_SDK_ROOT"),
            os.environ.get("ANDROID_HOME"),
        )
        if value
    ]
    sdk_roots.extend(
        (
            user_home / "Library/Android/sdk",
            Path("/opt/android-sdk"),
            Path("/usr/local/android-sdk"),
        )
    )
    candidates: list[Path] = []
    for root in sdk_roots:
        candidates.extend(
            sorted(root.glob("cmdline-tools/*/bin/apkanalyzer"), reverse=True)
        )
    candidates.extend(
        (
            Path("/opt/homebrew/bin/apkanalyzer"),
            Path("/usr/local/bin/apkanalyzer"),
            Path("/usr/bin/apkanalyzer"),
        )
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved)
    raise DriverError("apkanalyzer was not found in the trusted Android SDK locations")


def read_apk_typography(
    apk_path: str, assertions: list[dict]
) -> tuple[dict[str, float], str]:
    apk = Path(apk_path).resolve()
    if not apk.is_file() or apk.suffix != ".apk":
        raise DriverError("clean-build APK is unavailable for typography measurement")
    analyzer = resolve_apkanalyzer_binary()
    values: dict[str, float] = {}
    for assertion in assertions:
        resource_name = assertion.get("apk_resource_name")
        if not isinstance(resource_name, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]*", resource_name
        ):
            raise DriverError("typography assertion has no deterministic APK resource")
        completed = subprocess.run(
            [
                analyzer,
                "resources",
                "value",
                "--config",
                "default",
                "--type",
                "dimen",
                "--name",
                resource_name,
                str(apk),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        match = re.fullmatch(
            r"\s*([0-9]+(?:\.[0-9]+)?)sp\s*", completed.stdout
        )
        if completed.returncode != 0 or match is None:
            raise DriverError(
                "clean-build APK does not expose typography resource: "
                + resource_name
            )
        assertion_id = assertion.get("assertion_id")
        if not isinstance(assertion_id, str) or assertion_id in values:
            raise DriverError("typography assertion identity is invalid")
        values[assertion_id] = float(match.group(1))
    return values, hashlib.sha256(apk.read_bytes()).hexdigest()


def select_adb_serial(value: str | None) -> str | None:
    if value is None:
        return None
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is None:
        raise DriverError("adb device serial is invalid")
    result = subprocess.run(
        [resolve_adb_binary(), "devices"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise DriverError("cannot enumerate adb devices")
    online = {
        columns[0]
        for line in result.stdout.splitlines()[1:]
        if len(columns := line.split()) == 2 and columns[1] == "device"
    }
    if value not in online:
        raise DriverError("selected serial is not an online adb device")
    return value


def adb_prefix() -> list[str]:
    prefix = [resolve_adb_binary()]
    if ACTIVE_ADB_SERIAL is not None:
        prefix.extend(["-s", ACTIVE_ADB_SERIAL])
    return prefix


def run_adb(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [*adb_prefix(), *args],
        check=False,
        capture_output=True,
        text=not binary,
        timeout=120,
    )
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(
            "utf-8", errors="replace"
        )
        raise DriverError(stderr[-2000:] or f"adb command failed: {args}")
    return result


def shell_text(*args: str) -> str:
    return run_adb("shell", *args).stdout.strip()


def probe_adb(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*adb_prefix(), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def parse_dimension(output: str, label: str) -> tuple[dict[str, int], bool]:
    override = re.search(r"Override [^:]+:\s*(\d+)x(\d+)", output)
    physical = re.search(r"Physical [^:]+:\s*(\d+)x(\d+)", output)
    match = override or physical
    if match is None:
        raise DriverError(f"cannot parse {label}: {output}")
    return {"width": int(match.group(1)), "height": int(match.group(2))}, override is not None


def parse_density(output: str) -> tuple[int, bool]:
    override = re.search(r"Override density:\s*(\d+)", output)
    physical = re.search(r"Physical density:\s*(\d+)", output)
    match = override or physical
    if match is None:
        raise DriverError(f"cannot parse density: {output}")
    return int(match.group(1)), override is not None


def current_setting(namespace: str, name: str, fallback: str) -> str:
    value = shell_text("settings", "get", namespace, name)
    return fallback if value in {"", "null"} else value


def snapshot() -> dict:
    size, size_override = parse_dimension(shell_text("wm", "size"), "size")
    density, density_override = parse_density(shell_text("wm", "density"))
    locale = current_setting(
        "system", "system_locales", shell_text("getprop", "persist.sys.locale") or "en-US"
    )
    return {
        "size": size,
        "size_override": size_override,
        "density": density,
        "density_override": density_override,
        "locale": locale,
        "font_scale": current_setting("system", "font_scale", "1.0"),
        "navigation_mode": current_setting("secure", "navigation_mode", "2"),
    }


def load_config(path: str | None) -> dict:
    if path is None:
        raise DriverError("--config is required")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DriverError(f"cannot read device configuration: {exc}") from exc


def apply_config(config: dict) -> None:
    size = config["size"]
    if config["size_override"]:
        shell_text("wm", "size", f"{size['width']}x{size['height']}")
    else:
        shell_text("wm", "size", "reset")
    if config["density_override"]:
        shell_text("wm", "density", str(config["density"]))
    else:
        shell_text("wm", "density", "reset")
    shell_text("settings", "put", "system", "system_locales", config["locale"])
    shell_text("settings", "put", "system", "font_scale", config["font_scale"])
    shell_text("settings", "put", "secure", "navigation_mode", config["navigation_mode"])


def capture(path: str | None) -> None:
    if path is None:
        raise DriverError("--output is required")
    result = run_adb("exec-out", "screencap", "-p", binary=True)
    raw = result.stdout
    if not isinstance(raw, bytes) or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise DriverError("adb screencap did not return PNG data")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)


def installed_package_paths(package: str) -> list[str]:
    installed = run_adb("shell", "pm", "path", package)
    prefix = "package:"
    return [
        line[len(prefix) :]
        for line in installed.stdout.splitlines()
        if line.startswith(prefix) and len(line) > len(prefix)
    ]


def reset_package(package: str) -> dict:
    was_installed = bool(installed_package_paths(package))
    if was_installed:
        result = run_adb("uninstall", package)
        if "Success" not in result.stdout:
            raise DriverError(f"cannot uninstall the previous production package: {package}")
    absent_after_reset = not installed_package_paths(package)
    if not absent_after_reset:
        raise DriverError(f"previous production package remains installed: {package}")
    return {
        "package_name": package,
        "was_installed": was_installed,
        "absent_after_reset": True,
    }


def package_identity(package: str) -> dict:
    apk_paths = installed_package_paths(package)
    if not apk_paths:
        raise DriverError(f"production package is not installed: {package}")
    apks = []
    for apk_path in apk_paths:
        name = apk_path.rsplit("/", 1)[-1]
        if not name.endswith(".apk"):
            raise DriverError("installed production package path is invalid")
        result = run_adb("exec-out", "cat", apk_path, binary=True)
        payload = result.stdout
        if not isinstance(payload, bytes) or not payload:
            raise DriverError("cannot read an installed production APK")
        apks.append(
            {
                "name": name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    apks.sort(key=lambda item: item["name"])
    if len({item["name"] for item in apks}) != len(apks):
        raise DriverError("installed production APK names are ambiguous")
    identity_payload = json.dumps(
        apks,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "package_name": package,
        "apks": apks,
        "sha256": hashlib.sha256(identity_payload).hexdigest(),
    }


def resolve_launcher_component(package: str) -> str:
    resolved = run_adb(
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        "-p",
        package,
    )
    component_pattern = re.compile(r"^[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+$")
    components = [
        line.strip()
        for line in resolved.stdout.splitlines()
        if component_pattern.fullmatch(line.strip())
    ]
    if len(components) != 1 or components[0].split("/", 1)[0] != package:
        raise DriverError(f"cannot resolve a unique launcher activity for {package}")
    return components[0]


def cold_start(package: str) -> dict:
    launcher_component = resolve_launcher_component(package)
    run_adb("logcat", "-c")
    run_adb("shell", "am", "force-stop", package)
    run_adb(
        "shell",
        "run-as",
        package,
        "rm",
        "-f",
        "files/icp-runtime-probes.json",
    )
    started = run_adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        launcher_component,
    )
    evidence = runtime_health(package, wait=True)
    evidence["activity_resumed"] = (
        evidence["activity_resumed"] and "Status: ok" in started.stdout
    )
    return evidence


def runtime_health(package: str, *, wait: bool = False) -> dict:
    activity_resumed = False
    process_alive = False
    for _ in range(40 if wait else 1):
        pid = probe_adb("shell", "pidof", package)
        process_alive = pid.returncode == 0 and bool(pid.stdout.strip())
        activities = probe_adb("shell", "dumpsys", "activity", "activities")
        resumed_components = re.findall(
            r"(?:mResumedActivity|topResumedActivity)[^\n]*?"
            r"([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+",
            activities.stdout,
        )
        activity_resumed = (
            activities.returncode == 0
            and set(resumed_components) == {package}
        )
        if process_alive and activity_resumed:
            break
        time.sleep(0.25)

    logs = probe_adb("logcat", "-d", "-v", "brief")
    log_text = logs.stdout if logs.returncode == 0 else logs.stderr
    fatal_lines = [
        line
        for line in log_text.splitlines()
        if "FATAL EXCEPTION" in line
        or "ANR in " + package in line
        or (package in line and "has died" in line)
    ]
    return {
        "activity_resumed": activity_resumed,
        "process_alive": process_alive,
        "no_fatal_exception": not fatal_lines,
        "fatal_log_tail": "\n".join(fatal_lines)[-2000:],
    }


def load_json(path: str | None, label: str) -> dict:
    if path is None:
        raise DriverError(f"--{label} is required")
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DriverError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise DriverError(f"{label} must be a JSON object")
    return value


def finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def validate_scroll_metrics(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise DriverError("runtime scroll metric is invalid")
    required = {
        "decision_id",
        "container_instance_id",
        "axis",
        "viewport_extent",
        "content_extent",
        "observed_offsets",
    }
    for metric in value:
        if (
            not isinstance(metric, dict)
            or set(metric) != required
            or not isinstance(metric.get("decision_id"), str)
            or not metric["decision_id"]
            or not isinstance(metric.get("container_instance_id"), str)
            or not metric["container_instance_id"]
            or metric.get("axis") not in {"vertical", "horizontal"}
            or not finite_number(metric.get("viewport_extent"))
            or metric["viewport_extent"] <= 0
            or not finite_number(metric.get("content_extent"))
            or metric["content_extent"] < 0
            or not isinstance(metric.get("observed_offsets"), list)
            or any(not finite_number(offset) for offset in metric["observed_offsets"])
        ):
            raise DriverError("runtime scroll metric is invalid")
    return value


def scaled_number(value: int, scale: Fraction) -> int | float:
    result = Fraction(value, 1) / scale
    return result.numerator if result.denominator == 1 else float(result)


def parse_device_window_insets(
    wm_size: str, insets_dump: str, scale_value: object
) -> dict:
    scale = logical_scale(scale_value)
    sizes = re.findall(r"(?m)^(Physical|Override) size:\s*(\d+)x(\d+)\s*$", wm_size)
    if not sizes:
        raise DriverError("device display size is unavailable")
    preferred = next((item for item in reversed(sizes) if item[0] == "Override"), sizes[-1])
    display_width, display_height = int(preferred[1]), int(preferred[2])
    sources: dict[str, list[tuple[int, int, int, int, bool]]] = {
        "statusBars": [],
        "navigationBars": [],
    }
    pattern = re.compile(
        r"type=(statusBars|navigationBars)\b[^\n]*?"
        r"frame=\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\][^\n]*?"
        r"visible=(true|false)\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(insets_dump):
        bar_type = match.group(1)
        sources[bar_type].append(
            (
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
                int(match.group(5)),
                match.group(6).lower() == "true",
            )
        )
    if any(not values for values in sources.values()):
        raise DriverError("device system-bar insets are unavailable")

    def resolve(bar_type: str) -> tuple[bool, dict | None, tuple[int, int, int, int] | None]:
        visible = list(dict.fromkeys(item[:4] for item in sources[bar_type] if item[4]))
        if len(visible) > 1:
            raise DriverError(f"device {bar_type} inset is ambiguous")
        if not visible:
            return False, None, None
        left, top, right, bottom = visible[0]
        if right < left or bottom < top:
            raise DriverError(f"device {bar_type} inset is invalid")
        return (
            True,
            {
                "left": scaled_number(left, scale),
                "top": scaled_number(top, scale),
                "width": scaled_number(right - left, scale),
                "height": scaled_number(bottom - top, scale),
            },
            (left, top, right, bottom),
        )

    status_visible, status_bounds, status_physical = resolve("statusBars")
    nav_visible, nav_bounds, nav_physical = resolve("navigationBars")
    safe = {"left": 0, "top": 0, "right": 0, "bottom": 0}
    for physical in (status_physical, nav_physical):
        if physical is None:
            continue
        left, top, right, bottom = physical
        if top <= 0 and bottom > 0:
            safe["top"] = max(safe["top"], scaled_number(bottom, scale))
        if bottom >= display_height and top < display_height:
            safe["bottom"] = max(
                safe["bottom"], scaled_number(display_height - top, scale)
            )
        if left <= 0 and right > 0 and bottom - top >= display_height // 2:
            safe["left"] = max(safe["left"], scaled_number(right, scale))
        if right >= display_width and left < display_width and bottom - top >= display_height // 2:
            safe["right"] = max(
                safe["right"], scaled_number(display_width - left, scale)
            )
    return {
        "safe_insets": safe,
        "system_bars": {
            "status": {"visible": status_visible, "bounds": status_bounds},
            "navigation": {"visible": nav_visible, "bounds": nav_bounds},
        },
    }


def observe_device_window_insets(scale_value: object) -> dict:
    return parse_device_window_insets(
        shell_text("wm", "size"),
        shell_text("dumpsys", "window", "insets"),
        scale_value,
    )


def window_hierarchy() -> str:
    run_adb("shell", "uiautomator", "dump", "/sdcard/icp-window.xml")
    return shell_text("cat", "/sdcard/icp-window.xml")


def tagged_bound_matches(
    hierarchy: str, tag: str, package: str
) -> list[tuple[int, int, int, int]]:
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError as exc:
        raise DriverError("production window hierarchy is invalid") from exc
    matches: list[tuple[int, int, int, int]] = []
    for node in root.iter("node"):
        if node.get("package") != package:
            continue
        resource_id = node.get("resource-id", "")
        content_description = node.get("content-desc", "")
        tagged = (
            resource_id == tag
            or resource_id.rsplit("/", 1)[-1] == tag
            or tag in content_description.split()
        )
        if not tagged:
            continue
        bounds = re.fullmatch(
            r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]",
            node.get("bounds", ""),
        )
        if bounds is not None:
            matches.append(tuple(int(bounds.group(index)) for index in range(1, 5)))
    return matches


def tagged_bounds(
    hierarchy: str, tag: str, package: str
) -> tuple[int, int, int, int]:
    matches = tagged_bound_matches(hierarchy, tag, package)
    if len(matches) != 1:
        raise DriverError(f"production interaction target is not uniquely visible: {tag}")
    return matches[0]


def obligation_probe_bounds(
    hierarchy: str, probe_tags: list[str], package: str
) -> dict[str, tuple[int, int, int, int]]:
    """Require a bijection between frozen obligation probes and live UI nodes."""

    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError as exc:
        raise DriverError("production window hierarchy is invalid") from exc
    expected_tags = list(dict.fromkeys(probe_tags))
    matches: dict[str, list[tuple[int, int, int, int]]] = {
        tag: [] for tag in expected_tags
    }
    for node in root.iter("node"):
        if node.get("package") != package:
            continue
        resource_id = node.get("resource-id", "")
        resource_tag = resource_id.rsplit("/", 1)[-1]
        description_tags = set(node.get("content-desc", "").split())
        owned_tags = [
            tag
            for tag in expected_tags
            if resource_id == tag
            or resource_tag == tag
            or tag in description_tags
        ]
        if len(owned_tags) > 1:
            raise DriverError(
                "one production UI node may own only one obligation probe"
            )
        if not owned_tags:
            continue
        bounds = re.fullmatch(
            r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]",
            node.get("bounds", ""),
        )
        if bounds is not None:
            matches[owned_tags[0]].append(
                tuple(int(bounds.group(index)) for index in range(1, 5))
            )
    resolved: dict[str, tuple[int, int, int, int]] = {}
    for tag, tag_matches in matches.items():
        if not tag_matches:
            raise DriverError(f"runtime probe is not visible: {tag}")
        if len(tag_matches) != 1:
            raise DriverError(f"runtime probe is not uniquely visible: {tag}")
        resolved[tag] = tag_matches[0]
    return resolved


def interact(package: str, trace_path: str | None) -> dict:
    trace = load_json(trace_path, "trace")
    if trace.get("schema") != "icp.visual-interaction-trace.v1" or not isinstance(
        trace.get("steps"), list
    ):
        raise DriverError("interaction trace schema is invalid")
    state_id = trace.get("visual_state_id")
    if not isinstance(state_id, str) or not state_id:
        raise DriverError("interaction trace schema is invalid")
    initial_hierarchy = window_hierarchy()
    initial_state_matches = tagged_bound_matches(initial_hierarchy, state_id, package)
    if trace["steps"] and initial_state_matches:
        raise DriverError(
            f"terminal visual state is already present before interaction: {state_id}"
        )
    if not trace["steps"] and len(initial_state_matches) != 1:
        raise DriverError(f"entry visual state is not uniquely visible: {state_id}")
    observed: list[dict] = []
    for step in trace["steps"]:
        if not isinstance(step, dict):
            raise DriverError("interaction trace contains an unsupported action")
        if isinstance(step.get("actions"), list):
            actions = step["actions"]
        elif step.get("action") == "click":
            actions = [
                {
                    "operator": "click",
                    "target_tag": step.get("target_tag"),
                    "value": None,
                    "fact_ids": [],
                }
            ]
        else:
            raise DriverError("interaction trace contains an unsupported action")
        if not actions:
            raise DriverError("interaction trace contains no executable action")
        for action in actions:
            if not isinstance(action, dict):
                raise DriverError("interaction trace contains an unsupported action")
            operator = action.get("operator")
            if operator == "press_back":
                if action.get("target_tag") is not None or action.get("value") is not None:
                    raise DriverError("interaction back action is invalid")
                shell_text("input", "keyevent", "KEYCODE_BACK")
                continue
            tag = action.get("target_tag")
            if not isinstance(tag, str) or not tag:
                raise DriverError("interaction target tag is invalid")
            left, top, right, bottom = tagged_bounds(
                window_hierarchy(), tag, package
            )
            shell_text(
                "input",
                "tap",
                str((left + right) // 2),
                str((top + bottom) // 2),
            )
            if operator == "input_text":
                value = action.get("value")
                if not isinstance(value, str):
                    raise DriverError("interaction input text is invalid")
                encoded = value.replace("%", "%25").replace(" ", "%s")
                shell_text("input", "text", encoded)
            elif operator != "click" or action.get("value") is not None:
                raise DriverError("interaction trace contains an unsupported action")
        observed.append(step.copy())
    if trace["steps"]:
        tagged_bounds(window_hierarchy(), state_id, package)
    return {
        "schema": "icp.visual-interaction.v1",
        "steps": observed,
        "initial_state_absent": not initial_state_matches,
        "terminal_state_present": True,
    }


def attest(package: str, state_id: str | None, root_tag: str | None) -> dict:
    if not state_id or not root_tag:
        raise DriverError("--state-id and --root-tag are required")
    hierarchy = window_hierarchy()
    state_attested = len(tagged_bound_matches(hierarchy, state_id, package)) == 1
    root_attested = len(tagged_bound_matches(hierarchy, root_tag, package)) == 1
    return {
        "visual_state_id": state_id,
        "root_tag": root_tag,
        "state_attested": state_attested,
        "root_attested": root_attested,
    }


def measure_payload(
    contract: dict,
    payload: dict,
    *,
    apk_typography: dict[str, float] | None = None,
    apk_sha256: str | None = None,
) -> dict:
    if (
        contract.get("schema") != "icp.visual-measurement-contract.v1"
        or payload.get("schema") != "icp.runtime-probes.v1"
        or payload.get("visual_state_id") != contract.get("visual_state_id")
        or payload.get("root_tag") != contract.get("root_tag")
        or not isinstance(contract.get("assertions"), list)
        or not isinstance(payload.get("probes"), list)
    ):
        raise DriverError("runtime probes target another visual state or renderer")
    logical_scale(contract.get("logical_scale"))
    probes: dict[str, dict] = {}
    for probe in payload["probes"]:
        if not isinstance(probe, dict) or not isinstance(probe.get("probe_tag"), str):
            raise DriverError("runtime probe is invalid")
        if probe["probe_tag"] in probes:
            raise DriverError("runtime probe tag is duplicated")
        probes[probe["probe_tag"]] = probe
    measurements: list[dict] = []
    for assertion in contract["assertions"]:
        if not isinstance(assertion, dict):
            raise DriverError("measurement assertion is invalid")
        probe = probes.get(assertion.get("probe_tag"))
        kind = assertion.get("kind")
        typography_from_apk = kind in {"font_size", "line_height"}
        actual = (
            apk_typography.get(assertion.get("assertion_id"))
            if typography_from_apk and apk_typography is not None
            else probe.get(kind)
            if probe is not None and not typography_from_apk
            else None
        )
        if actual is None:
            if typography_from_apk:
                raise DriverError(
                    "clean-build APK does not expose typography: "
                    + str(assertion.get("probe_tag"))
                )
            raise DriverError(
                f"runtime probe does not expose {kind}: {assertion.get('probe_tag')}"
            )
        measurement = {
            "assertion_id": assertion.get("assertion_id"),
            "probe_tag": assertion.get("probe_tag"),
            "kind": kind,
            "actual": actual,
        }
        if typography_from_apk:
            if not isinstance(apk_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", apk_sha256
            ):
                raise DriverError("clean-build APK identity is unavailable")
            measurement.update(
                {"source": "clean_build_apk", "apk_sha256": apk_sha256}
            )
        measurements.append(measurement)
    return {
        "schema": "icp.visual-measurements.v1",
        "visual_state_id": contract["visual_state_id"],
        "root_tag": contract["root_tag"],
        "measurements": measurements,
    }


def measure(
    package: str, contract_path: str | None, apk_path: str | None = None
) -> dict:
    contract = load_json(contract_path, "contract")
    raw = shell_text(
        "run-as", package, "cat", "files/icp-runtime-probes.json"
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DriverError("production runtime probe payload is invalid") from exc
    if not isinstance(payload, dict):
        raise DriverError("production runtime probe payload must be an object")
    typography_assertions = [
        assertion
        for assertion in contract.get("assertions", [])
        if isinstance(assertion, dict)
        and assertion.get("kind") in {"font_size", "line_height"}
    ]
    apk_typography = None
    apk_sha256 = None
    if typography_assertions:
        if apk_path is None:
            raise DriverError(
                "clean-build APK is required for typography measurement"
            )
        apk_typography, apk_sha256 = read_apk_typography(
            apk_path, typography_assertions
        )
    measurements = measure_payload(
        contract,
        payload,
        apk_typography=apk_typography,
        apk_sha256=apk_sha256,
    )
    hierarchy = window_hierarchy()
    hierarchy_bounds_by_probe = obligation_probe_bounds(
        hierarchy,
        list(
            dict.fromkeys(
                item["probe_tag"] for item in measurements["measurements"]
            )
        ),
        package,
    )
    scale = logical_scale(contract["logical_scale"])
    for measurement in measurements["measurements"]:
        if measurement["kind"] != "bounds":
            continue
        actual = measurement["actual"]
        if not isinstance(actual, dict) or set(actual) != {
            "left",
            "top",
            "width",
            "height",
        }:
            raise DriverError("runtime probe bounds are invalid")
        left, top, right, bottom = hierarchy_bounds_by_probe[
            measurement["probe_tag"]
        ]
        physical = {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }
        if any(
            isinstance(actual[field], bool)
            or not isinstance(actual[field], (int, float))
            or abs(Fraction(str(actual[field])) * scale - physical[field]) > 1
            for field in physical
        ):
            raise DriverError(
                f"runtime probe bounds differ from live hierarchy: {measurement['probe_tag']}"
            )
    return measurements


def hierarchy_fingerprint(hierarchy: str, package: str) -> str:
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError as exc:
        raise DriverError("window hierarchy XML is invalid") from exc
    observed = sorted(
        (
            node.attrib.get("resource-id", ""),
            node.attrib.get("content-desc", ""),
            node.attrib.get("text", ""),
            node.attrib.get("bounds", ""),
        )
        for node in root.iter("node")
        if node.attrib.get("package") == package
    )
    return hashlib.sha256(
        json.dumps(observed, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def read_layout(package: str, contract_path: str | None) -> dict:
    contract = load_json(contract_path, "contract")
    if (
        contract.get("schema") != "icp.runtime-layout-contract"
        or not isinstance(contract.get("visual_state_id"), str)
        or not isinstance(contract.get("root_tag"), str)
        or not isinstance(contract.get("component_instance_ids"), list)
        or not isinstance(contract.get("occurrence_ids_by_instance_id"), dict)
        or not isinstance(contract.get("scroll_obligations", []), list)
    ):
        raise DriverError("runtime layout contract is invalid")
    scale = logical_scale(contract.get("logical_scale", 1))
    raw = shell_text("run-as", package, "cat", "files/icp-runtime-probes.json")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DriverError("production runtime probe payload is invalid") from exc
    required = {
        "schema",
        "visual_state_id",
        "root_tag",
        "coordinate_space",
        "viewport_bounds",
        "safe_insets",
        "system_bars",
        "scroll_metrics",
        "components",
        "probes",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required
        or payload.get("schema") != "icp.runtime-probes.v1"
        or payload.get("visual_state_id") != contract["visual_state_id"]
        or payload.get("root_tag") != contract["root_tag"]
        or not isinstance(payload.get("components"), list)
    ):
        raise DriverError("runtime layout probes target another production state")
    require_device_insets = contract.get("require_device_window_insets", False)
    if type(require_device_insets) is not bool:
        raise DriverError("runtime layout contract is invalid")
    if require_device_insets:
        observed_window = observe_device_window_insets(scale)
        if (
            payload.get("safe_insets") != observed_window["safe_insets"]
            or payload.get("system_bars") != observed_window["system_bars"]
        ):
            raise DriverError(
                "runtime window insets differ from the live Android window"
            )
        payload["safe_insets"] = observed_window["safe_insets"]
        payload["system_bars"] = observed_window["system_bars"]
    actual_ids = [
        item.get("instance_id")
        for item in payload["components"]
        if isinstance(item, dict)
    ]
    expected_ids = contract["component_instance_ids"]
    expected_occurrences = contract["occurrence_ids_by_instance_id"]
    if (
        len(actual_ids) != len(set(actual_ids))
        or set(actual_ids) != set(expected_ids)
        or len(actual_ids) != len(expected_ids)
        or set(expected_occurrences) != set(expected_ids)
        or any(
            not isinstance(value, str) or not value
            for value in expected_occurrences.values()
        )
        or len(expected_occurrences.values())
        != len(set(expected_occurrences.values()))
    ):
        raise DriverError("runtime layout component coverage changed")
    hierarchy = window_hierarchy()
    try:
        tagged_bounds(hierarchy, contract["visual_state_id"], package)
        root_bounds = tagged_bounds(hierarchy, contract["root_tag"], package)
    except DriverError:
        raise DriverError("runtime layout is not attached to the production hierarchy")
    observed_bounds: dict[str, tuple[int, int, int, int]] = {}
    observed_after_scroll: set[str] = set()
    scroll_actions: list[dict] = []
    scroll_results: list[dict] = []
    components_by_occurrence: dict[str, dict] = {}
    components_by_instance: dict[str, dict] = {}
    for component in payload["components"]:
        occurrence_id = component.get("occurrence_id")
        bounds = component.get("bounds")
        if not isinstance(occurrence_id, str) or not occurrence_id or not isinstance(
            bounds, dict
        ):
            raise DriverError("runtime layout component measurement is invalid")
        try:
            observed_bounds[occurrence_id] = tagged_bounds(
                hierarchy, occurrence_id, package
            )
        except DriverError:
            pass
        components_by_occurrence[occurrence_id] = component
        instance_id = component.get("instance_id")
        if not isinstance(instance_id, str) or instance_id in components_by_instance:
            raise DriverError("runtime layout component identity is invalid")
        components_by_instance[instance_id] = component
    if {
        instance_id: component["occurrence_id"]
        for instance_id, component in components_by_instance.items()
    } != expected_occurrences:
        raise DriverError("runtime component occurrence identity changed")
    initial_hierarchy = hierarchy
    initial_fingerprint = hierarchy_fingerprint(initial_hierarchy, package)
    scroll_axes: set[str] = set()
    for raw_obligation in contract.get("scroll_obligations", []):
        if not isinstance(raw_obligation, dict) or set(raw_obligation) != {
            "decision_id",
            "container_instance_id",
            "axis",
            "required_instance_ids",
        }:
            raise DriverError("runtime scroll obligation is invalid")
        axis = raw_obligation.get("axis")
        required_instance_ids = raw_obligation.get("required_instance_ids")
        if (
            axis not in {"vertical", "horizontal"}
            or not isinstance(required_instance_ids, list)
            or any(
                not isinstance(value, str) or value not in components_by_instance
                for value in required_instance_ids
            )
        ):
            raise DriverError("runtime scroll obligation is invalid")
        scroll_axes.add(axis)
        container_id = raw_obligation.get("container_instance_id")
        container = components_by_instance.get(container_id)
        if container is None:
            raise DriverError("runtime scroll obligation is invalid")
        try:
            container_bounds = tagged_bounds(
                initial_hierarchy, container["occurrence_id"], package
            )
        except DriverError as exc:
            raise DriverError(
                "runtime scroll container is not visible: " + str(container_id)
            ) from exc
        container_left, container_top, container_right, container_bottom = (
            container_bounds
        )
        width = container_right - container_left
        height = container_bottom - container_top
        if width <= 0 or height <= 0:
            raise DriverError("runtime scroll container bounds are invalid")
        required_occurrences = {
            components_by_instance[instance_id]["occurrence_id"]
            for instance_id in required_instance_ids
        }
        observed_for_obligation = required_occurrences & set(observed_bounds)
        previous_fingerprint = initial_fingerprint
        stable_attempts = 0
        end_reached = False
        for _ in range(20):
            if axis == "vertical":
                start = {"x": container_left + width // 2, "y": container_top + height * 3 // 4}
                end = {"x": container_left + width // 2, "y": container_top + height // 4}
            else:
                start = {"x": container_left + width * 3 // 4, "y": container_top + height // 2}
                end = {"x": container_left + width // 4, "y": container_top + height // 2}
            shell_text(
                "input", "swipe", str(start["x"]), str(start["y"]),
                str(end["x"]), str(end["y"]), "250"
            )
            scroll_actions.append(
                {"axis": axis, "direction": "forward", "start_px": start, "end_px": end}
            )
            hierarchy = window_hierarchy()
            current_fingerprint = hierarchy_fingerprint(hierarchy, package)
            stable_attempts = stable_attempts + 1 if current_fingerprint == previous_fingerprint else 0
            previous_fingerprint = current_fingerprint
            for occurrence_id in required_occurrences - observed_for_obligation:
                try:
                    observed_bounds[occurrence_id] = tagged_bounds(
                        hierarchy, occurrence_id, package
                    )
                except DriverError:
                    continue
                observed_after_scroll.add(occurrence_id)
                observed_for_obligation.add(occurrence_id)
            if stable_attempts >= 2:
                end_reached = True
                break
        restored_to_start = previous_fingerprint == initial_fingerprint
        for _ in range(20):
            if restored_to_start:
                break
            if axis == "vertical":
                start = {"x": container_left + width // 2, "y": container_top + height // 4}
                end = {"x": container_left + width // 2, "y": container_top + height * 3 // 4}
            else:
                start = {"x": container_left + width // 4, "y": container_top + height // 2}
                end = {"x": container_left + width * 3 // 4, "y": container_top + height // 2}
            shell_text(
                "input", "swipe", str(start["x"]), str(start["y"]),
                str(end["x"]), str(end["y"]), "250"
            )
            scroll_actions.append(
                {"axis": axis, "direction": "restore", "start_px": start, "end_px": end}
            )
            hierarchy = window_hierarchy()
            restored_to_start = (
                hierarchy_fingerprint(hierarchy, package) == initial_fingerprint
            )
        scroll_results.append(
            {
                "decision_id": raw_obligation["decision_id"],
                "container_instance_id": raw_obligation["container_instance_id"],
                "axis": axis,
                "end_reached": end_reached,
                "restored_to_start": restored_to_start,
                "observed_instance_ids": sorted(
                    instance_id
                    for instance_id in required_instance_ids
                    if components_by_instance[instance_id]["occurrence_id"]
                    in observed_for_obligation
                ),
            }
        )
        if not end_reached or not restored_to_start or observed_for_obligation != required_occurrences:
            raise DriverError(
                "runtime layout components were not observed on the live scroll path: "
                + raw_obligation["decision_id"]
            )
        hierarchy = initial_hierarchy
    missing = set(components_by_occurrence) - set(observed_bounds)
    if missing:
        raise DriverError(
            "runtime layout components were not observed on the live scroll path: "
            + ",".join(sorted(missing))
        )
    for occurrence_id, component in components_by_occurrence.items():
        bounds = component["bounds"]
        left, top, right, bottom = observed_bounds[occurrence_id]
        hierarchy_bounds = {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }
        compared_fields = {"left", "top", "width", "height"}
        if occurrence_id in observed_after_scroll:
            if "vertical" in scroll_axes:
                compared_fields.discard("top")
            if "horizontal" in scroll_axes:
                compared_fields.discard("left")
        if set(bounds) != set(hierarchy_bounds) or any(
            isinstance(bounds[field], bool)
            or not isinstance(bounds[field], (int, float))
            or abs(Fraction(str(bounds[field])) * scale - hierarchy_bounds[field]) > 1
            for field in compared_fields
        ):
            raise DriverError(
                f"runtime layout bounds differ from live hierarchy: {occurrence_id}"
            )
    result = {key: payload[key] for key in required - {"schema", "probes"}}
    result["scroll_metrics"] = []
    result["components"] = [
        {key: value for key, value in component.items() if key != "presence"}
        for component in payload["components"]
    ]
    result["driver_observations"] = {
        "observed_instance_ids": [
            component["instance_id"] for component in payload["components"]
        ],
        "scroll_actions": scroll_actions,
        "scroll_results": scroll_results,
    }
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument(
        "operation",
        choices=(
            "snapshot",
            "apply",
            "cold-start",
            "health",
            "interact",
            "attest",
            "measure",
            "read-layout",
            "reset-package",
            "package-identity",
            "capture",
            "restore",
        ),
    )
    root.add_argument("--package", required=True)
    root.add_argument("--config")
    root.add_argument("--output")
    root.add_argument("--state-id")
    root.add_argument("--root-tag")
    root.add_argument("--trace")
    root.add_argument("--contract")
    root.add_argument("--apk")
    root.add_argument("--serial")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        global ACTIVE_ADB_SERIAL
        ACTIVE_ADB_SERIAL = select_adb_serial(args.serial)
        if args.operation == "snapshot":
            print(json.dumps(snapshot(), ensure_ascii=False))
        elif args.operation in {"apply", "restore"}:
            apply_config(load_config(args.config))
        elif args.operation == "cold-start":
            print(json.dumps(cold_start(args.package), ensure_ascii=False))
        elif args.operation == "health":
            print(json.dumps(runtime_health(args.package), ensure_ascii=False))
        elif args.operation == "interact":
            print(json.dumps(interact(args.package, args.trace), ensure_ascii=False))
        elif args.operation == "attest":
            print(json.dumps(attest(args.package, args.state_id, args.root_tag), ensure_ascii=False))
        elif args.operation == "measure":
            print(
                json.dumps(
                    measure(args.package, args.contract, args.apk), ensure_ascii=False
                )
            )
        elif args.operation == "read-layout":
            print(json.dumps(read_layout(args.package, args.contract), ensure_ascii=False))
        elif args.operation == "reset-package":
            print(json.dumps(reset_package(args.package), ensure_ascii=False))
        elif args.operation == "package-identity":
            print(json.dumps(package_identity(args.package), ensure_ascii=False))
        else:
            capture(args.output)
    except (DriverError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
