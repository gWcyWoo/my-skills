#!/usr/bin/env python3
"""Step 5: 渲染采集 — 构建+安装+启动+导航+截图+dump视图树

用法:
    python3 probe.py --project <android-root> --out-dir <dir> --package <pkg> \
        [--route <route>] [--blueprint <path>] [--avd <name>] [--serial <serial>] \
        [--skip-build] [--skip-boot] [--keep-emulator]

产出 (写入 --out-dir):
    screenshot.png   — 目标页截图
    view_tree.xml    — UI Automator dump
    probe-result.json — 结构化结果
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from emulator_utils import (
    ADB,
    boot_emulator,
    build_apk,
    count_view_nodes,
    dump_view_tree,
    find_apk,
    install_apk,
    kill_emulator,
    run,
    running_devices,
    screenshot,
)

LAUNCH_SETTLE = 3
RENDER_SETTLE = 2


def navigate_to_route(serial, package, route):
    """Navigate to target page. Returns (method, success)."""
    run([ADB, "-s", serial, "shell", "am", "force-stop", package], check=False)
    time.sleep(0.5)

    # Try VerifyActivity first
    run([ADB, "-s", serial, "shell", "am", "start",
         "-n", f"{package}/.debug.VerifyActivity",
         "--es", "route", route], check=False)
    time.sleep(RENDER_SETTLE)
    r = run([ADB, "-s", serial, "shell", "dumpsys", "activity", "top"], check=False)
    if "VerifyActivity" in r.stdout:
        return "verify_activity", True

    # Try deep link
    run([ADB, "-s", serial, "shell", "am", "start",
         "-a", "android.intent.action.VIEW",
         "-d", f"app://{route}",
         "-n", f"{package}/.MainActivity"], check=False)
    time.sleep(RENDER_SETTLE)
    return "deep_link", True


def verify_navigation(vt_path: Path, blueprint_path: Path | None) -> dict:
    """Check if the rendered page matches the blueprint (at least one text matches)."""
    if not blueprint_path or not blueprint_path.exists():
        return {"verified": False, "reason": "no_blueprint"}

    with open(blueprint_path) as f:
        blueprint = json.load(f)

    vt_content = vt_path.read_text(errors="replace").lower()
    bp_texts = []
    for c in blueprint.get("components", []):
        for t in c.get("texts", []):
            bp_texts.append(t["value"])

    if not bp_texts:
        return {"verified": False, "reason": "no_blueprint_texts"}

    matched = sum(1 for t in bp_texts if t.lower() in vt_content)
    if matched == 0:
        return {
            "verified": False,
            "reason": "navigation_failed",
            "expected_texts": len(bp_texts),
            "matched_texts": 0,
        }
    return {"verified": True, "matched_texts": matched, "expected_texts": len(bp_texts)}


def main():
    parser = argparse.ArgumentParser(description="Step 5: 渲染采集")
    parser.add_argument("--project", required=True, help="Android project root")
    parser.add_argument("--out-dir", required=True, help="output directory")
    parser.add_argument("--package", required=True, help="app package name")
    parser.add_argument("--route", default=None, help="route to navigate to")
    parser.add_argument("--blueprint", default=None, help="layout-blueprint.json for nav verification")
    parser.add_argument("--avd", default=None, help="AVD name")
    parser.add_argument("--serial", default=None, help="already-running device serial")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-boot", action="store_true")
    parser.add_argument("--keep-emulator", action="store_true")
    args = parser.parse_args()

    project = Path(args.project)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"steps": {}, "timings": {}}
    t_start = time.time()
    serial = None

    try:
        # Boot
        if args.serial:
            serial = args.serial
        elif args.skip_boot:
            devices = running_devices()
            if not devices:
                print(json.dumps({"ok": False, "error": "no running device and --skip-boot"}))
                return 1
            serial = devices[0]
        else:
            t = time.time()
            serial, _proc = boot_emulator(args.avd or "CreditSun_API_24")
            if not serial:
                print(json.dumps({"ok": False, "error": "emulator did not boot"}))
                return 1
            result["timings"]["boot_ms"] = int((time.time() - t) * 1000)
        result["serial"] = serial

        # Build
        if not args.skip_build:
            t = time.time()
            apk_path = build_apk(project)
            result["timings"]["build_ms"] = int((time.time() - t) * 1000)
        else:
            apk_path = find_apk(project)
        result["apk"] = apk_path

        # Install
        t = time.time()
        install_apk(serial, apk_path)
        result["timings"]["install_ms"] = int((time.time() - t) * 1000)

        # Launch + navigate
        t = time.time()
        if args.route:
            nav_method, _ok = navigate_to_route(serial, args.package, args.route)
            result["render_navigation"] = nav_method
        else:
            run([ADB, "-s", serial, "shell", "am", "start",
                 "-n", f"{args.package}/.MainActivity"], check=False)
            result["render_navigation"] = "main_activity"
        time.sleep(LAUNCH_SETTLE)
        result["timings"]["launch_ms"] = int((time.time() - t) * 1000)

        # Screenshot
        ss_path = out_dir / "screenshot.png"
        t = time.time()
        ss_size = screenshot(serial, ss_path)
        result["timings"]["screenshot_ms"] = int((time.time() - t) * 1000)
        result["steps"]["screenshot"] = {"path": str(ss_path), "size": ss_size}

        # View tree
        vt_path = out_dir / "view_tree.xml"
        t = time.time()
        dump_view_tree(serial, vt_path)
        node_count = count_view_nodes(vt_path)
        result["timings"]["dump_ms"] = int((time.time() - t) * 1000)
        result["steps"]["view_tree"] = {"path": str(vt_path), "nodes": node_count}

        # Navigation verification (hard error if route was specified but page didn't render)
        bp_path = Path(args.blueprint) if args.blueprint else None
        nav_check = verify_navigation(vt_path, bp_path)
        result["navigation_check"] = nav_check
        if args.route and not nav_check.get("verified", True):
            result["render_ok"] = False
            result["error"] = f"navigation_failed: 0/{nav_check.get('expected_texts', '?')} blueprint texts found in view tree"
            result["render_view_nodes"] = node_count
            result["render_time_ms"] = int((time.time() - t_start) * 1000)
            with open(out_dir / "probe-result.json", "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(json.dumps({"ok": False, **{k: result[k] for k in ("error", "render_navigation")}}, ensure_ascii=False))
            return 1

        result["render_ok"] = True
        result["render_view_nodes"] = node_count
        result["render_time_ms"] = int((time.time() - t_start) * 1000)

    except Exception as e:
        result["render_ok"] = False
        result["error"] = str(e)
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    finally:
        if not args.keep_emulator and not args.serial and not args.skip_boot and serial:
            kill_emulator(serial)

    with open(out_dir / "probe-result.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(json.dumps({
        "ok": True,
        "render_ok": True,
        "render_navigation": result.get("render_navigation"),
        "render_view_nodes": node_count,
        "render_time_ms": result["render_time_ms"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
