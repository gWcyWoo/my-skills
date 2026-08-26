#!/usr/bin/env python3
"""Step 5: 渲染采集 — 构建+安装+启动+导航+截图+dump视图树

用法:
    python3 probe.py --project <project-root> --out-dir <dir> --package <pkg> \
        --target <android|ios|web> \
        [--route <route>] [--blueprint <path>] [--device <name>] [--serial <id>] \
        [--skip-build] [--skip-boot] [--keep-device]

产出 (写入 --out-dir):
    screenshot.png    — 目标页截图
    view_tree.xml     — 视图树 dump
    probe-result.json — 结构化结果
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import device

LAUNCH_SETTLE = 3


def verify_navigation(vt_path: Path, blueprint_path: Path | None) -> dict:
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
    parser.add_argument("--project", required=True, help="project root")
    parser.add_argument("--out-dir", required=True, help="output directory")
    parser.add_argument("--package", required=True, help="app package/bundle id")
    parser.add_argument("--target", required=True, choices=sorted(device.TARGET_MODULES), help="device target")
    parser.add_argument("--route", default=None, help="route to navigate to")
    parser.add_argument("--blueprint", default=None, help="layout-blueprint.json")
    parser.add_argument("--device", default=None, help="device/AVD/simulator name")
    parser.add_argument("--serial", default=None, help="already-running device id")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-boot", action="store_true")
    parser.add_argument("--keep-device", action="store_true")
    args = parser.parse_args()

    dev = device.load(args.target)
    project = Path(args.project)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"steps": {}, "timings": {}, "target": args.target}
    t_start = time.time()
    device_id = None

    try:
        # Boot
        if args.serial:
            device_id = args.serial
        elif args.skip_boot:
            devices = dev.running_devices()
            if not devices:
                print(json.dumps({"ok": False, "error": "no running device and --skip-boot"}))
                return 1
            device_id = devices[0]
        else:
            t = time.time()
            device_id = dev.boot_device(args.device)
            if not device_id:
                print(json.dumps({"ok": False, "error": "device did not boot"}))
                return 1
            result["timings"]["boot_ms"] = int((time.time() - t) * 1000)
        result["device_id"] = device_id

        # Build
        if not args.skip_build:
            t = time.time()
            artifact = dev.build(project)
            result["timings"]["build_ms"] = int((time.time() - t) * 1000)
        else:
            artifact = dev.find_artifact(project)
        result["artifact"] = artifact

        # Install
        t = time.time()
        dev.install(device_id, artifact)
        result["timings"]["install_ms"] = int((time.time() - t) * 1000)

        # Launch + navigate
        t = time.time()
        dev.launch(device_id, args.package, route=args.route)
        time.sleep(LAUNCH_SETTLE)
        result["timings"]["launch_ms"] = int((time.time() - t) * 1000)

        # Screenshot
        ss_path = out_dir / "screenshot.png"
        t = time.time()
        ss_size = dev.screenshot(device_id, ss_path)
        result["timings"]["screenshot_ms"] = int((time.time() - t) * 1000)
        result["steps"]["screenshot"] = {"path": str(ss_path), "size": ss_size}

        # View tree
        vt_path = out_dir / "view_tree.xml"
        t = time.time()
        dev.dump_view_tree(device_id, vt_path)
        node_count = dev.count_view_nodes(vt_path)
        result["timings"]["dump_ms"] = int((time.time() - t) * 1000)
        result["steps"]["view_tree"] = {"path": str(vt_path), "nodes": node_count}

        # Navigation verification
        bp_path = Path(args.blueprint) if args.blueprint else None
        nav_check = verify_navigation(vt_path, bp_path)
        result["navigation_check"] = nav_check
        if args.route and nav_check.get("reason") == "navigation_failed":
            result["render_ok"] = False
            result["error"] = f"navigation_failed: 0/{nav_check.get('expected_texts', '?')} blueprint texts found"
            result["render_view_nodes"] = node_count
            result["render_time_ms"] = int((time.time() - t_start) * 1000)
            with open(out_dir / "probe-result.json", "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(json.dumps({"ok": False, "error": result["error"]}, ensure_ascii=False))
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
        if not args.keep_device and not args.serial and not args.skip_boot and device_id:
            dev.kill_device(device_id)

    with open(out_dir / "probe-result.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(json.dumps({
        "ok": True,
        "render_ok": True,
        "render_view_nodes": node_count,
        "render_time_ms": result["render_time_ms"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
