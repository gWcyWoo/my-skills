#!/usr/bin/env python3
"""Select a physical Flutter device and fail early on deterministic blockers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


class PreviewError(RuntimeError):
    pass


def run_bounded(
    argv: list[str], *, cwd: Path | None = None, timeout: float = 15
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PreviewError(f"command not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PreviewError(
            f"command timed out after {timeout:g}s: {shlex.join(argv)}"
        ) from exc


def parse_flutter_devices(payload: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PreviewError(f"flutter devices returned invalid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise PreviewError("flutter devices JSON must be a list")
    return [item for item in raw if isinstance(item, dict)]


def choose_physical_device(
    devices: list[dict[str, Any]], preferred: str | None = None
) -> dict[str, Any]:
    candidates = [
        item
        for item in devices
        if item.get("emulator") is False
        and item.get("isSupported") is True
        and (
            str(item.get("targetPlatform", "")).startswith("android")
            or item.get("targetPlatform") == "ios"
        )
    ]
    if preferred:
        for item in candidates:
            if item.get("id") == preferred:
                return item
        raise PreviewError(
            f"requested physical mobile device is unavailable: {preferred}"
        )
    if not candidates:
        raise PreviewError("no supported physical Android or iOS device is connected")
    candidates.sort(
        key=lambda item: (
            0 if str(item.get("targetPlatform", "")).startswith("android") else 1,
            str(item.get("name", "")),
            str(item.get("id", "")),
        )
    )
    return candidates[0]


def parse_build_setting(output: str, key: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$")
    values = {match.group(1) for line in output.splitlines() if (match := pattern.match(line))}
    if len(values) != 1:
        raise PreviewError(f"expected one {key} build setting, found {sorted(values)}")
    return next(iter(values))


def parse_signing_identity_teams(output: str) -> list[str]:
    teams = {
        match.group(1)
        for match in re.finditer(
            r'"Apple Development:[^"]+\(([A-Z0-9]{10})\)"', output
        )
    }
    return sorted(teams)


def profile_matches(
    profile: dict[str, Any],
    *,
    team: str,
    bundle_id: str,
    device_id: str,
    now: dt.datetime,
) -> bool:
    expires = profile.get("ExpirationDate")
    if not isinstance(expires, dt.datetime):
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    if expires <= now.astimezone(dt.timezone.utc):
        return False
    teams = profile.get("TeamIdentifier")
    if not isinstance(teams, list) or team not in teams:
        return False
    provisioned = profile.get("ProvisionedDevices")
    if not isinstance(provisioned, list) or device_id not in provisioned:
        return False
    entitlements = profile.get("Entitlements")
    if not isinstance(entitlements, dict):
        return False
    app_id = entitlements.get("application-identifier")
    if not isinstance(app_id, str) or not app_id.startswith(f"{team}."):
        return False
    profile_bundle = app_id[len(team) + 1 :]
    if profile_bundle.endswith("*"):
        return bundle_id.startswith(profile_bundle[:-1])
    return profile_bundle == bundle_id


def provisioning_profile_paths(home: Path) -> list[Path]:
    roots = [
        home / "Library/MobileDevice/Provisioning Profiles",
        home / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    ]
    return sorted(
        path
        for root in roots
        if root.is_dir()
        for path in root.iterdir()
        if path.is_file()
    )


def decode_profiles(paths: list[Path], timeout: float) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for path in paths:
        try:
            result = subprocess.run(
                ["security", "cms", "-D", "-i", str(path)],
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        try:
            value = plistlib.loads(result.stdout)
        except Exception:
            continue
        if isinstance(value, dict):
            decoded.append(value)
    return decoded


def ios_signing_result(
    *,
    team: str,
    bundle_id: str,
    device_id: str,
    identity_teams: list[str],
    profiles: list[dict[str, Any]],
    now: dt.datetime,
) -> dict[str, Any]:
    matching_profiles = sum(
        1
        for profile in profiles
        if profile_matches(
            profile,
            team=team,
            bundle_id=bundle_id,
            device_id=device_id,
            now=now,
        )
    )
    if team not in identity_teams:
        return {
            "ok": False,
            "blocker": {
                "kind": "ios_signing",
                "code": "development_team_identity_missing",
                "projectTeam": team,
                "availableIdentityTeams": identity_teams,
                "bundleId": bundle_id,
                "deviceId": device_id,
                "action": "Sign in to the Apple developer account for the project team in Xcode, or deliberately select a project team that has a valid local identity and provisioning access.",
            },
            "matchingProfileCount": matching_profiles,
        }
    return {
        "ok": True,
        "matchingProfileCount": matching_profiles,
        "warning": (
            None
            if matching_profiles
            else "No matching local development profile was found; Xcode automatic signing must be able to create one."
        ),
    }


def probe(project_root: Path, preferred: str | None, timeout: float) -> dict[str, Any]:
    devices_result = run_bounded(
        ["flutter", "devices", "--machine", "--device-timeout", str(int(timeout))],
        cwd=project_root,
        timeout=timeout + 5,
    )
    if devices_result.returncode != 0:
        raise PreviewError(
            (devices_result.stderr or devices_result.stdout).strip()
            or "flutter devices failed"
        )
    device = choose_physical_device(
        parse_flutter_devices(devices_result.stdout), preferred=preferred
    )
    device_id = str(device["id"])
    target = str(device["targetPlatform"])
    platform = "android" if target.startswith("android") else "ios"
    result: dict[str, Any] = {
        "ok": True,
        "purpose": "interactive_physical_device_preview",
        "isPhysical": True,
        "platform": platform,
        "deviceId": device_id,
        "deviceName": str(device.get("name", "")),
        "runCommand": ["flutter", "run", "-d", device_id],
    }
    if platform == "android":
        state = run_bounded(["adb", "-s", device_id, "get-state"], timeout=timeout)
        qemu = run_bounded(
            ["adb", "-s", device_id, "shell", "getprop", "ro.kernel.qemu"],
            timeout=timeout,
        )
        if state.returncode != 0 or state.stdout.strip() != "device" or qemu.stdout.strip() == "1":
            result.update(
                ok=False,
                blocker={
                    "kind": "android_device",
                    "code": "physical_device_not_ready",
                    "deviceId": device_id,
                    "detail": (state.stderr or state.stdout).strip(),
                },
            )
        return result

    workspace = project_root / "ios/Runner.xcworkspace"
    project = project_root / "ios/Runner.xcodeproj"
    if workspace.exists():
        build_argv = ["xcodebuild", "-workspace", str(workspace), "-scheme", "Runner"]
    elif project.exists():
        build_argv = ["xcodebuild", "-project", str(project), "-scheme", "Runner"]
    else:
        raise PreviewError("missing ios/Runner.xcworkspace and ios/Runner.xcodeproj")
    settings = run_bounded(
        [*build_argv, "-configuration", "Debug", "-destination", f"id={device_id}", "-showBuildSettings"],
        cwd=project_root,
        timeout=timeout,
    )
    if settings.returncode != 0:
        raise PreviewError((settings.stderr or settings.stdout).strip())
    team = parse_build_setting(settings.stdout, "DEVELOPMENT_TEAM")
    bundle_id = parse_build_setting(settings.stdout, "PRODUCT_BUNDLE_IDENTIFIER")
    identities = run_bounded(
        ["security", "find-identity", "-v", "-p", "codesigning"], timeout=timeout
    )
    identity_teams = parse_signing_identity_teams(identities.stdout)
    profiles = decode_profiles(provisioning_profile_paths(Path.home()), timeout)
    signing = ios_signing_result(
        team=team,
        bundle_id=bundle_id,
        device_id=device_id,
        identity_teams=identity_teams,
        profiles=profiles,
        now=dt.datetime.now(dt.timezone.utc),
    )
    result["signing"] = {
        "projectTeam": team,
        "bundleId": bundle_id,
        "availableIdentityTeams": identity_teams,
        "matchingProfileCount": signing["matchingProfileCount"],
        "warning": signing.get("warning"),
    }
    if not signing["ok"]:
        result["ok"] = False
        result["blocker"] = signing["blocker"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--device")
    parser.add_argument("--command-timeout", type=float, default=15)
    parser.add_argument("--dart-define", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).expanduser().resolve()
    try:
        result = probe(Path(args.project_root).expanduser().resolve(), args.device, args.command_timeout)
    except PreviewError as exc:
        result = {
            "ok": False,
            "purpose": "interactive_physical_device_preview",
            "isPhysical": True,
            "blocker": {"kind": "environment", "code": "probe_failed", "detail": str(exc)},
        }
    if result.get("ok"):
        for value in args.dart_define:
            result["runCommand"].append(f"--dart-define={value}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
