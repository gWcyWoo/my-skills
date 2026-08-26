"""iOS Simulator device operations — xcrun simctl."""
from __future__ import annotations

import json
import time
from pathlib import Path

from device import run


def running_devices():
    r = run(["xcrun", "simctl", "list", "devices", "booted", "-j"], check=False)
    devices = []
    for _, devs in json.loads(r.stdout or "{}").get("devices", {}).items():
        for d in devs:
            if d.get("state") == "Booted":
                devices.append(d["udid"])
    return devices


def wait_boot(udid, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = run(["xcrun", "simctl", "list", "devices", "-j"], check=False)
        for _, devs in json.loads(r.stdout or "{}").get("devices", {}).items():
            for d in devs:
                if (d["udid"] == udid or d.get("name") == udid) and d["state"] == "Booted":
                    return True
        time.sleep(2)
    return False


def boot_device(name=None):
    if not name:
        devices = running_devices()
        if devices:
            return devices[0]
        r = run(["xcrun", "simctl", "list", "devices", "available", "-j"])
        for runtime, devs in json.loads(r.stdout).get("devices", {}).items():
            if "iOS" not in runtime:
                continue
            for d in devs:
                if d.get("isAvailable"):
                    name = d["udid"]
                    break
            if name:
                break
    if not name:
        return None
    run(["xcrun", "simctl", "boot", name], check=False)
    if not wait_boot(name):
        return None
    r = run(["xcrun", "simctl", "list", "devices", "-j"], check=False)
    for _, devs in json.loads(r.stdout or "{}").get("devices", {}).items():
        for d in devs:
            if (d["udid"] == name or d.get("name") == name) and d["state"] == "Booted":
                return d["udid"]
    return name


def find_artifact(project: Path) -> str:
    flutter_dir = project / "build" / "ios" / "iphonesimulator"
    if flutter_dir.exists():
        apps = list(flutter_dir.glob("*.app"))
        if apps:
            return str(apps[0])
    build_dir = project / "build" / "Build" / "Products" / "Debug-iphonesimulator"
    apps = list(build_dir.glob("*.app")) if build_dir.exists() else []
    if not apps:
        raise FileNotFoundError("no .app bundle found")
    return str(apps[0])


def build(project: Path) -> str:
    if (project / "pubspec.yaml").exists():
        run(["flutter", "build", "ios", "--debug", "--simulator"],
            timeout=600, cwd=str(project))
        return find_artifact(project)
    scheme = project.name
    workspace = list(project.glob("*.xcworkspace"))
    if workspace:
        run(["xcodebuild", "-workspace", str(workspace[0]),
             "-scheme", scheme, "-sdk", "iphonesimulator",
             "-destination", "generic/platform=iOS Simulator",
             "-derivedDataPath", str(project / "build"),
             "build"], timeout=600)
    else:
        xcodeproj = list(project.glob("*.xcodeproj"))
        if not xcodeproj:
            raise FileNotFoundError("no .xcworkspace or .xcodeproj found")
        run(["xcodebuild", "-project", str(xcodeproj[0]),
             "-scheme", scheme, "-sdk", "iphonesimulator",
             "-destination", "generic/platform=iOS Simulator",
             "-derivedDataPath", str(project / "build"),
             "build"], timeout=600)
    return find_artifact(project)


def install(device_id, artifact_path):
    run(["xcrun", "simctl", "install", device_id, artifact_path], timeout=60)


def launch(device_id, bundle_id, route=None):
    run(["xcrun", "simctl", "terminate", device_id, bundle_id], check=False)
    run(["xcrun", "simctl", "launch", device_id, bundle_id])
    if route:
        run(["xcrun", "simctl", "openurl", device_id, f"app://{route}"], check=False)


def screenshot(device_id, out_path: Path) -> int:
    run(["xcrun", "simctl", "io", device_id, "screenshot", str(out_path)])
    return out_path.stat().st_size


def dump_view_tree(device_id, out_path: Path):
    try:
        r = run(["idb", "ui", "describe-all", "--udid", device_id], check=False)
    except FileNotFoundError:
        raise RuntimeError(
            "iOS view-tree dump requires idb (install: brew install idb-companion)")
    if r.returncode != 0:
        raise RuntimeError(
            "iOS view-tree dump requires idb (install: brew install idb-companion). "
            f"stderr: {r.stderr[:200]}")
    out_path.write_text(r.stdout, encoding="utf-8")


def count_view_nodes(tree_path: Path) -> int:
    content = tree_path.read_text(errors="replace")
    return content.count('"AXFrame"')


def kill_device(device_id):
    run(["xcrun", "simctl", "shutdown", device_id], check=False)
