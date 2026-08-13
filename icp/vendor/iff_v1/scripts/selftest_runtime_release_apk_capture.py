#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import tempfile

from capture_runtime_screenshot import android_flutter_run_command


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-runtime-release-apk-") as raw_tmp:
        root = Path(raw_tmp)
        debug_apk = root / "app-debug.apk"
        release_apk = root / "app-arm64-v8a-release.apk"
        debug_apk.write_bytes(b"debug")
        release_apk.write_bytes(b"release")

        debug_command, debug_mode = android_flutter_run_command(
            device="emulator-5554", apk=debug_apk, route=None
        )
        assert debug_mode == "debug", debug_mode
        assert "--debug" in debug_command, debug_command
        assert f"--use-application-binary={debug_apk.absolute()}" in debug_command, debug_command

        release_command, release_mode = android_flutter_run_command(
            device="emulator-5554", apk=release_apk, route="/home"
        )
        assert release_mode == "release", release_mode
        assert "--release" in release_command and "--debug" not in release_command, release_command
        assert f"--use-application-binary={release_apk.absolute()}" in release_command, release_command
        assert "--route=/home" in release_command, release_command

        ambiguous = root / "capture.apk"
        ambiguous.write_bytes(b"ambiguous")
        try:
            android_flutter_run_command(device="emulator-5554", apk=ambiguous, route=None)
        except SystemExit as exc:
            assert "cannot infer Android APK build mode" in str(exc), exc
        else:
            raise AssertionError("ambiguous APK mode was accepted")

    print("PASS: Android capture launches the exact prebuilt debug/release APK with matching Flutter mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
