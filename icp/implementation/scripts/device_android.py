"""Android device operations — adb + emulator."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from device import run

_ah = os.environ.get("ANDROID_HOME", "").strip()
SDK = Path(_ah) if _ah else Path.home() / "Library" / "Android" / "sdk"
ADB = str(SDK / "platform-tools" / "adb")
EMULATOR = str(SDK / "emulator" / "emulator")

BOOT_TIMEOUT = 120


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


def boot_device(name=None):
    devices = running_devices()
    if devices:
        return devices[0]
    if not name:
        r = run([EMULATOR, "-list-avds"], check=False)
        avds = [a.strip() for a in r.stdout.strip().splitlines() if a.strip()]
        if not avds:
            raise RuntimeError("no running device, no --device given, and no AVDs found")
        name = avds[0]
    proc = subprocess.Popen(
        [EMULATOR, "-avd", name, "-no-audio", "-no-window", "-gpu", "swiftshader_indirect"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(5)
    for _ in range(20):
        devs = running_devices()
        for d in devs:
            if d.startswith("emulator-"):
                if wait_boot(d):
                    return d
        time.sleep(3)
    proc.kill()
    return None


def find_artifact(project: Path) -> str:
    flutter_apk = project / "build" / "app" / "outputs" / "flutter-apk" / "app-debug.apk"
    if flutter_apk.exists():
        return str(flutter_apk)
    output_dir = project / "app" / "build" / "outputs" / "apk" / "debug"
    apks = list(output_dir.glob("*.apk")) if output_dir.exists() else []
    if not apks:
        raise FileNotFoundError("no debug APK found")
    return str(apks[0])


def build(project: Path) -> str:
    if (project / "pubspec.yaml").exists():
        run(["flutter", "build", "apk", "--debug"], timeout=600, cwd=str(project))
        return find_artifact(project)
    gradlew = project / "gradlew"
    if not gradlew.exists():
        raise FileNotFoundError(f"gradlew not found at {gradlew}")
    run([str(gradlew), "-p", str(project), "assembleDebug"], timeout=300)
    return find_artifact(project)


def install(device_id, artifact_path):
    run([ADB, "-s", device_id, "install", "-r", "-t", artifact_path], timeout=60)


def launch(device_id, package, route=None):
    run([ADB, "-s", device_id, "shell", "am", "force-stop", package], check=False)
    if route:
        run([ADB, "-s", device_id, "shell", "am", "start",
             "-a", "android.intent.action.VIEW",
             "-d", f"app://{route}",
             "-n", f"{package}/.MainActivity"], check=False)
    else:
        run([ADB, "-s", device_id, "shell", "monkey", "-p", package,
             "-c", "android.intent.category.LAUNCHER", "1"])


def screenshot(device_id, out_path: Path) -> int:
    remote = "/sdcard/probe_screenshot.png"
    run([ADB, "-s", device_id, "shell", "screencap", "-p", remote])
    run([ADB, "-s", device_id, "pull", remote, str(out_path)])
    run([ADB, "-s", device_id, "shell", "rm", remote], check=False)
    return out_path.stat().st_size


def dump_view_tree(device_id, out_path: Path):
    remote = "/sdcard/probe_window_dump.xml"
    run([ADB, "-s", device_id, "shell", "rm", remote], check=False)
    run([ADB, "-s", device_id, "shell", "uiautomator", "dump", remote])
    run([ADB, "-s", device_id, "pull", remote, str(out_path)])
    run([ADB, "-s", device_id, "shell", "rm", remote], check=False)


def count_view_nodes(xml_path: Path) -> int:
    content = xml_path.read_text(errors="replace")
    return content.count("<node ")


def kill_device(device_id):
    run([ADB, "-s", device_id, "emu", "kill"], check=False)
