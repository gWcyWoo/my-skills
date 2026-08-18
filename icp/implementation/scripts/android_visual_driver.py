#!/usr/bin/env python3
"""Android device driver for ICP's reversible visual-capture protocol."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("operation", choices=("snapshot", "apply", "capture", "restore"))
    root.add_argument("--package", required=True)
    root.add_argument("--config")
    root.add_argument("--output")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation == "snapshot":
            print(json.dumps(snapshot(), ensure_ascii=False))
        elif args.operation in {"apply", "restore"}:
            apply_config(load_config(args.config))
        else:
            capture(args.output)
    except (DriverError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
