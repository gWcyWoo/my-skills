#!/usr/bin/env python3
"""Launch Flutter on a device and capture a runtime screenshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def app_hashes(app_root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(app_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(app_root.rglob("*.dart"))
    }


def runtime_input_hashes(project_root: Path) -> dict[str, str]:
    paths = [
        path
        for name in ("pubspec.yaml", "pubspec.lock")
        if (path := project_root / name).is_file()
    ]
    assets_root = project_root / "assets"
    if assets_root.is_dir():
        paths.extend(path for path in assets_root.rglob("*") if path.is_file())
    return {
        str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["android", "ios"], required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--density", type=int, default=160)
    parser.add_argument("--route", help="named initial route to launch (flutter run --route), so a "
                        "non-home feature page can be screenshotted WITHOUT mutating main.dart's initialRoute")
    parser.add_argument("--settle-seconds", type=float, default=5.0)
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    setup_commands = []
    if args.platform == "android" and args.width and args.height:
        setup_commands.append(f"adb -s {args.device} shell wm size {args.width}x{args.height}")
        setup_commands.append(f"adb -s {args.device} shell wm density {args.density}")
        run(["adb", "-s", args.device, "shell", "wm", "size", f"{args.width}x{args.height}"])
        run(["adb", "-s", args.device, "shell", "wm", "density", str(args.density)])
    run_cmd = ["flutter", "run", "-d", args.device, "--debug", "--no-resident"]
    if args.route:
        run_cmd.append(f"--route={args.route}")
    run(run_cmd)
    if args.settle_seconds > 0:
        time.sleep(args.settle_seconds)
    if args.platform == "android":
        remote = "/sdcard/iff_actual.png"
        capture_command = f"adb -s {args.device} shell screencap -p {remote}"
        run(["adb", "-s", args.device, "shell", "screencap", "-p", remote])
        run(["adb", "-s", args.device, "pull", remote, str(out)])
    else:
        capture_command = f"xcrun simctl io {args.device} screenshot {out}"
        run(["xcrun", "simctl", "io", args.device, "screenshot", str(out)])
    if not out.is_file() or out.stat().st_size == 0:
        raise SystemExit(f"ERROR: screenshot was not created: {out}")
    manifest_path = Path(args.manifest)
    data = {}
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    project_root = Path.cwd().resolve()
    data.update(
        {
            "actual_source": "simulator_screenshot",
            "device_id": args.device,
            "project_root": str(project_root),
            "app_hashes": app_hashes(project_root / "lib"),
            "runtime_input_hashes": runtime_input_hashes(project_root),
            "launch_command": run_cmd,
            "route": args.route,
            "viewport": {"width": args.width, "height": args.height, "density": args.density},
            "setup_commands": setup_commands,
            "settle_seconds": args.settle_seconds,
            "capture_command": capture_command,
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
