#!/usr/bin/env python3
"""Stage 3 模拟器冒烟测试。

启动→构建→安装→截屏→dump视图树→退出，全程无人工。
验证采集回路可用，是 Stage 3 代码生成的硬前置。

用法:
    python3 smoke_test.py --project <android-project-root> --out-dir <dir> [--avd <name>] [--skip-build]

产出 (写入 --out-dir):
    screenshot.png   — 应用首屏截图
    view_tree.xml    — UI Automator dump
    smoke_result.json — 结构化结果 (ok/errors/timings)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_ah = os.environ.get("ANDROID_HOME", "").strip()
SDK = Path(_ah) if _ah else Path.home() / "Library" / "Android" / "sdk"

ADB = str(SDK / "platform-tools" / "adb")
EMULATOR = str(SDK / "emulator" / "emulator")

BOOT_TIMEOUT = 120
LAUNCH_SETTLE = 5
INSTALL_TIMEOUT = 60


def emit(ok: bool, data: dict, code: int = 0):
    data["ok"] = ok
    print(json.dumps(data, ensure_ascii=False))
    return code


def run(cmd, timeout=60, check=True, capture=True):
    r = subprocess.run(
        cmd, capture_output=capture, text=True, timeout=timeout,
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nstderr: {r.stderr[:500]}")
    return r


def list_avds():
    r = run([EMULATOR, "-list-avds"], check=False)
    return [a.strip() for a in r.stdout.strip().splitlines() if a.strip()]


def running_devices():
    r = run([ADB, "devices"], check=False)
    devices = []
    for line in r.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def wait_boot(serial, timeout=BOOT_TIMEOUT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = run([ADB, "-s", serial, "shell", "getprop", "sys.boot_completed"],
                check=False, timeout=10)
        if r.stdout.strip() == "1":
            return True
        time.sleep(2)
    return False


def boot_emulator(avd):
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
    return None, None


def find_apk(project: Path):
    output_dir = project / "app" / "build" / "outputs" / "apk" / "debug"
    apks = list(output_dir.glob("*.apk")) if output_dir.exists() else []
    if apks:
        return max(apks, key=lambda p: p.stat().st_mtime)
    return None


def build_apk(project: Path):
    gradlew = project / "gradlew"
    if not gradlew.exists():
        raise RuntimeError(f"gradlew not found at {gradlew}")
    run([str(gradlew), "-p", str(project), "assembleDebug", "--no-daemon"],
        timeout=300, capture=False, check=True)
    apk = find_apk(project)
    if not apk:
        raise RuntimeError("assembleDebug succeeded but no APK found")
    return apk


def install_apk(serial, apk_path):
    run([ADB, "-s", serial, "install", "-r", "-t", str(apk_path)],
        timeout=INSTALL_TIMEOUT)


def launch_app(serial, package):
    run([ADB, "-s", serial, "shell", "am", "force-stop", package], check=False)
    run([ADB, "-s", serial, "shell", "monkey", "-p", package,
         "-c", "android.intent.category.LAUNCHER", "1"])


def screenshot(serial, out_path: Path):
    device_path = "/sdcard/smoke_screenshot.png"
    run([ADB, "-s", serial, "shell", "screencap", "-p", device_path])
    run([ADB, "-s", serial, "pull", device_path, str(out_path)])
    run([ADB, "-s", serial, "shell", "rm", device_path], check=False)
    if not out_path.exists() or out_path.stat().st_size < 1000:
        raise RuntimeError(f"screenshot too small or missing: {out_path}")


def dump_view_tree(serial, out_path: Path):
    device_path = "/sdcard/smoke_window_dump.xml"
    run([ADB, "-s", serial, "shell", "rm", "-f", device_path], check=False)
    run([ADB, "-s", serial, "exec-out", "uiautomator", "dump", device_path],
        timeout=30)
    time.sleep(1)
    run([ADB, "-s", serial, "pull", device_path, str(out_path)])
    run([ADB, "-s", serial, "shell", "rm", device_path], check=False)
    if not out_path.exists() or out_path.stat().st_size < 100:
        raise RuntimeError(f"view tree dump too small or missing: {out_path}")


def validate_view_tree(xml_path: Path):
    content = xml_path.read_text(encoding="utf-8", errors="replace")
    node_count = content.count("<node ")
    has_hierarchy = "hierarchy" in content
    return {
        "node_count": node_count,
        "has_hierarchy": has_hierarchy,
        "file_size": xml_path.stat().st_size,
    }


def validate_screenshot(png_path: Path):
    size = png_path.stat().st_size
    return {
        "file_size": size,
        "valid": size > 5000,
    }


def main():
    ap = argparse.ArgumentParser(prog="smoke_test.py")
    ap.add_argument("--project", required=True, help="Android project root")
    ap.add_argument("--out-dir", required=True, help="Output directory for artifacts")
    ap.add_argument("--avd", help="AVD name (auto-detect if omitted)")
    ap.add_argument("--skip-build", action="store_true", help="Skip Gradle build, use existing APK")
    ap.add_argument("--package", default="kz.creditsun.app", help="Application package name")
    ap.add_argument("--keep-emulator", action="store_true", help="Don't stop emulator on exit")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timings = {}
    errors = []
    we_booted = False
    serial = None
    emulator_proc = None

    try:
        # --- Step 1: Emulator ---
        t0 = time.time()
        devs = running_devices()
        if devs:
            serial = devs[0]
        else:
            avd = args.avd
            if not avd:
                avds = list_avds()
                if not avds:
                    return emit(False, {"errors": ["no AVD found"]}, 1)
                avd = avds[0]
            serial, emulator_proc = boot_emulator(avd)
            if not serial:
                return emit(False, {"errors": [f"emulator boot timeout ({avd})"]}, 1)
            we_booted = True
        timings["emulator_ready"] = round(time.time() - t0, 1)

        # --- Step 2: Build ---
        t0 = time.time()
        if args.skip_build:
            apk = find_apk(project)
            if not apk:
                return emit(False, {"errors": ["--skip-build but no existing APK"]}, 1)
        else:
            apk = build_apk(project)
        timings["build"] = round(time.time() - t0, 1)

        # --- Step 3: Install ---
        t0 = time.time()
        install_apk(serial, apk)
        timings["install"] = round(time.time() - t0, 1)

        # --- Step 4: Launch + settle ---
        t0 = time.time()
        launch_app(serial, args.package)
        time.sleep(LAUNCH_SETTLE)
        timings["launch"] = round(time.time() - t0, 1)

        # --- Step 5: Screenshot ---
        t0 = time.time()
        ss_path = out_dir / "screenshot.png"
        screenshot(serial, ss_path)
        ss_info = validate_screenshot(ss_path)
        timings["screenshot"] = round(time.time() - t0, 1)

        # --- Step 6: View tree dump ---
        t0 = time.time()
        vt_path = out_dir / "view_tree.xml"
        dump_view_tree(serial, vt_path)
        vt_info = validate_view_tree(vt_path)
        timings["view_tree"] = round(time.time() - t0, 1)

        # --- Step 7: Stop app ---
        run([ADB, "-s", serial, "shell", "am", "force-stop", args.package], check=False)

        result = {
            "serial": serial,
            "apk": str(apk),
            "screenshot": ss_info,
            "view_tree": vt_info,
            "timings": timings,
            "we_booted_emulator": we_booted,
        }

        (out_dir / "smoke_result.json").write_text(
            json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

        return emit(True, result)

    except Exception as exc:
        errors.append(str(exc))
        return emit(False, {"errors": errors, "timings": timings}, 1)

    finally:
        if we_booted and not args.keep_emulator and emulator_proc:
            run([ADB, "-s", serial, "emu", "kill"], check=False, timeout=10)
            try:
                emulator_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                emulator_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
