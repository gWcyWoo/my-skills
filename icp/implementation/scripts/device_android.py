"""Shared emulator utilities for smoke_test.py and probe.py."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

_ah = os.environ.get("ANDROID_HOME", "").strip()
SDK = Path(_ah) if _ah else Path.home() / "Library" / "Android" / "sdk"
ADB = str(SDK / "platform-tools" / "adb")
EMULATOR = str(SDK / "emulator" / "emulator")

BOOT_TIMEOUT = 120


def run(cmd, timeout=60, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nstderr: {r.stderr[:500]}")
    return r


def running_devices():
    r = run([ADB, "devices"], check=False)
    devices = []
    for line in r.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def wait_boot(serial, timeout=BOOT_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = run([ADB, "-s", serial, "shell", "getprop", "sys.boot_completed"], check=False)
        if r.stdout.strip() == "1":
            return True
        time.sleep(2)
    return False


def boot_emulator(avd):
    devices = running_devices()
    if devices:
        return devices[0], None
    proc = subprocess.Popen(
        [EMULATOR, "-avd", avd, "-no-audio", "-no-window", "-gpu", "swiftshader_indirect"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(5)
    for _ in range(20):
        devs = running_devices()
        for d in devs:
            if d.startswith("emulator-"):
                if wait_boot(d):
                    return d, proc
        time.sleep(3)
    proc.kill()
    return None, proc


def find_apk(project: Path) -> str:
    output_dir = project / "app" / "build" / "outputs" / "apk" / "debug"
    apks = list(output_dir.glob("*.apk")) if output_dir.exists() else []
    if not apks:
        raise FileNotFoundError("no debug APK found")
    return str(apks[0])


def build_apk(project: Path) -> str:
    gradlew = project / "gradlew"
    if not gradlew.exists():
        raise FileNotFoundError(f"gradlew not found at {gradlew}")
    run([str(gradlew), "-p", str(project), "assembleDebug"], timeout=300)
    return find_apk(project)


def install_apk(serial, apk_path):
    run([ADB, "-s", serial, "install", "-r", "-t", apk_path], timeout=60)


def screenshot(serial, out_path: Path) -> int:
    remote = "/sdcard/probe_screenshot.png"
    run([ADB, "-s", serial, "shell", "screencap", "-p", remote])
    run([ADB, "-s", serial, "pull", remote, str(out_path)])
    run([ADB, "-s", serial, "shell", "rm", remote], check=False)
    return out_path.stat().st_size


def dump_view_tree(serial, out_path: Path):
    remote = "/sdcard/probe_window_dump.xml"
    run([ADB, "-s", serial, "shell", "rm", remote], check=False)
    run([ADB, "-s", serial, "shell", "uiautomator", "dump", remote])
    run([ADB, "-s", serial, "pull", remote, str(out_path)])
    run([ADB, "-s", serial, "shell", "rm", remote], check=False)


def count_view_nodes(xml_path: Path) -> int:
    content = xml_path.read_text(errors="replace")
    return content.count("<node ")


def kill_emulator(serial):
    run([ADB, "-s", serial, "emu", "kill"], check=False)
