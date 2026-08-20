#!/usr/bin/env python3
"""Android device driver for ICP's reversible visual-capture protocol."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


class DriverError(Exception):
    pass


def adb_prefix() -> list[str]:
    command = [os.environ.get("ICP_ADB", "adb")]
    serial = os.environ.get("ANDROID_SERIAL")
    if serial:
        command.extend(["-s", serial])
    return command


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
    started = run_adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        launcher_component,
    )
    activity_resumed = False
    process_alive = False
    for _ in range(40):
        pid = probe_adb("shell", "pidof", package)
        process_alive = pid.returncode == 0 and bool(pid.stdout.strip())
        activities = probe_adb("shell", "dumpsys", "activity", "activities")
        activity_resumed = (
            activities.returncode == 0
            and package in activities.stdout
            and (
                "mResumedActivity" in activities.stdout
                or "topResumedActivity" in activities.stdout
            )
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
        "activity_resumed": activity_resumed and "Status: ok" in started.stdout,
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


def window_hierarchy() -> str:
    run_adb("shell", "uiautomator", "dump", "/sdcard/icp-window.xml")
    return shell_text("cat", "/sdcard/icp-window.xml")


def tagged_bounds(hierarchy: str, tag: str) -> tuple[int, int, int, int]:
    escaped = re.escape(tag)
    node = re.search(
        rf'<node\b(?=[^>]*(?:resource-id|content-desc)="[^"]*{escaped}[^"]*")[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        hierarchy,
    )
    if node is None:
        raise DriverError(f"production interaction target is not visible: {tag}")
    return tuple(int(node.group(index)) for index in range(1, 5))


def interact(trace_path: str | None) -> dict:
    trace = load_json(trace_path, "trace")
    if trace.get("schema") != "icp.visual-interaction-trace.v1" or not isinstance(
        trace.get("steps"), list
    ):
        raise DriverError("interaction trace schema is invalid")
    observed: list[dict] = []
    for step in trace["steps"]:
        if not isinstance(step, dict) or step.get("action") != "click":
            raise DriverError("interaction trace contains an unsupported action")
        tag = step.get("target_tag")
        if not isinstance(tag, str) or not tag:
            raise DriverError("interaction target tag is invalid")
        left, top, right, bottom = tagged_bounds(window_hierarchy(), tag)
        shell_text("input", "tap", str((left + right) // 2), str((top + bottom) // 2))
        observed.append(step.copy())
    return {"schema": "icp.visual-interaction.v1", "steps": observed}


def attest(state_id: str | None, root_tag: str | None) -> dict:
    if not state_id or not root_tag:
        raise DriverError("--state-id and --root-tag are required")
    hierarchy = window_hierarchy()
    return {
        "visual_state_id": state_id,
        "root_tag": root_tag,
        "state_attested": state_id in hierarchy,
        "root_attested": root_tag in hierarchy,
    }


def measure_payload(contract: dict, payload: dict) -> dict:
    if (
        contract.get("schema") != "icp.visual-measurement-contract.v1"
        or payload.get("schema") != "icp.runtime-probes.v1"
        or payload.get("visual_state_id") != contract.get("visual_state_id")
        or payload.get("root_tag") != contract.get("root_tag")
        or not isinstance(contract.get("assertions"), list)
        or not isinstance(payload.get("probes"), list)
    ):
        raise DriverError("runtime probes target another visual state or renderer")
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
        actual = probe.get(kind) if probe is not None else None
        if actual is None:
            raise DriverError(
                f"runtime probe does not expose {kind}: {assertion.get('probe_tag')}"
            )
        measurements.append(
            {
                "assertion_id": assertion.get("assertion_id"),
                "probe_tag": assertion.get("probe_tag"),
                "kind": kind,
                "actual": actual,
            }
        )
    return {
        "schema": "icp.visual-measurements.v1",
        "visual_state_id": contract["visual_state_id"],
        "root_tag": contract["root_tag"],
        "measurements": measurements,
    }


def measure(package: str, contract_path: str | None) -> dict:
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
    measurements = measure_payload(contract, payload)
    hierarchy = window_hierarchy()
    for probe_tag in dict.fromkeys(
        item["probe_tag"] for item in measurements["measurements"]
    ):
        try:
            tagged_bounds(hierarchy, probe_tag)
        except DriverError as exc:
            raise DriverError(f"runtime probe is not visible: {probe_tag}") from exc
    return measurements


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument(
        "operation",
        choices=(
            "snapshot",
            "apply",
            "cold-start",
            "interact",
            "attest",
            "measure",
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
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation == "snapshot":
            print(json.dumps(snapshot(), ensure_ascii=False))
        elif args.operation in {"apply", "restore"}:
            apply_config(load_config(args.config))
        elif args.operation == "cold-start":
            print(json.dumps(cold_start(args.package), ensure_ascii=False))
        elif args.operation == "interact":
            print(json.dumps(interact(args.trace), ensure_ascii=False))
        elif args.operation == "attest":
            print(json.dumps(attest(args.state_id, args.root_tag), ensure_ascii=False))
        elif args.operation == "measure":
            print(json.dumps(measure(args.package, args.contract), ensure_ascii=False))
        else:
            capture(args.output)
    except (DriverError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
