#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from physical_device_preview import (  # noqa: E402
    PreviewError,
    choose_physical_device,
    ios_signing_result,
    parse_build_setting,
    parse_flutter_devices,
    parse_signing_identity_teams,
    profile_matches,
)


def main() -> int:
    devices = parse_flutter_devices(
        '[{"name":"Pixel","id":"emulator-5554","isSupported":true,"targetPlatform":"android-arm64","emulator":true},'
        '{"name":"Mac","id":"macos","isSupported":true,"targetPlatform":"darwin","emulator":false},'
        '{"name":"Phone","id":"ios-1","isSupported":true,"targetPlatform":"ios","emulator":false},'
        '{"name":"Android","id":"android-1","isSupported":true,"targetPlatform":"android-arm64","emulator":false}]'
    )
    assert choose_physical_device(devices)["id"] == "android-1"
    assert choose_physical_device(devices, "ios-1")["id"] == "ios-1"
    try:
        choose_physical_device(devices, "emulator-5554")
    except PreviewError:
        pass
    else:
        raise AssertionError("an emulator must not satisfy a physical-device request")

    settings = "    DEVELOPMENT_TEAM = TEAM123456\n    PRODUCT_BUNDLE_IDENTIFIER = com.example.app\n"
    assert parse_build_setting(settings, "DEVELOPMENT_TEAM") == "TEAM123456"
    identities = '1) HASH "Apple Development: Dev One (TEAM123456)"\n'
    assert parse_signing_identity_teams(identities) == ["TEAM123456"]

    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    profile = {
        "ExpirationDate": dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc),
        "TeamIdentifier": ["TEAM123456"],
        "ProvisionedDevices": ["ios-1"],
        "Entitlements": {"application-identifier": "TEAM123456.com.example.*"},
    }
    assert profile_matches(
        profile,
        team="TEAM123456",
        bundle_id="com.example.app",
        device_id="ios-1",
        now=now,
    )
    mismatch = ios_signing_result(
        team="OTHER12345",
        bundle_id="com.example.app",
        device_id="ios-1",
        identity_teams=["TEAM123456"],
        profiles=[profile],
        now=now,
    )
    assert not mismatch["ok"]
    assert mismatch["blocker"]["code"] == "development_team_identity_missing"
    ready = ios_signing_result(
        team="TEAM123456",
        bundle_id="com.example.app",
        device_id="ios-1",
        identity_teams=["TEAM123456"],
        profiles=[profile],
        now=now,
    )
    assert ready["ok"] and ready["matchingProfileCount"] == 1
    print("ok physical device preview preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
