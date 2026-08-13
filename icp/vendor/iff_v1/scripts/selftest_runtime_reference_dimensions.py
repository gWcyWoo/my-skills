#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
CAPTURE = SCRIPTS / "capture_runtime_screenshot.py"
DEVICE = "emulator-5554"


def write_png_header(path: Path, width: int, height: int) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
    )


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def run_capture(
    *,
    root: Path,
    env: dict[str, str],
    reference: Path,
    out: Path,
    manifest: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CAPTURE),
            "--selection",
            str(root / "runtime_device.json"),
            "--reference",
            str(reference),
            "--android-apk",
            str(root / "app-debug.apk"),
            "--out",
            str(out),
            "--manifest",
            str(manifest),
            "--settle-seconds",
            "0",
        ],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-reference-dimensions-") as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        reference = root / "reference.png"
        matching = root / "matching.png"
        mismatching = root / "mismatching.png"
        write_png_header(reference, 750, 1624)
        write_png_header(matching, 750, 1624)
        write_png_header(mismatching, 1280, 2856)
        (root / "runtime_device.json").write_text(
            json.dumps(
                {
                    "platform": "android",
                    "device": DEVICE,
                    "actualSource": "simulator_screenshot",
                }
            ),
            encoding="utf-8",
        )
        log = root / "commands.log"
        write_executable(
            bin_dir / "adb",
            "#!/bin/sh\n"
            "printf 'adb %s\\n' \"$*\" >> \"$IFF_COMMAND_LOG\"\n"
            "if [ \"$1\" = \"devices\" ]; then printf 'List of devices attached\\nemulator-5554\\tdevice\\n'; exit 0; fi\n"
            "if [ \"$4\" = \"getprop\" ]; then printf '1\\n'; exit 0; fi\n"
            "if [ \"$4\" = \"pm\" ] && [ \"$5\" = \"path\" ]; then printf 'package:/system/framework/framework-res.apk\\n'; exit 0; fi\n"
            "if [ \"$3\" = \"pull\" ]; then cp \"$IFF_CAPTURE_SOURCE\" \"$5\"; exit 0; fi\n"
            "exit 0\n",
        )
        write_executable(
            bin_dir / "flutter",
            "#!/bin/sh\nprintf 'flutter %s\\n' \"$*\" >> \"$IFF_COMMAND_LOG\"\nexit 0\n",
        )
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["IFF_COMMAND_LOG"] = str(log)
        env["IFF_CAPTURE_SOURCE"] = str(matching)

        actual = root / "actual.png"
        manifest_path = root / "runtime_capture_manifest.json"
        result = run_capture(
            root=root,
            env=env,
            reference=reference,
            out=actual,
            manifest=manifest_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        commands = log.read_text(encoding="utf-8").splitlines()
        size_command = f"adb -s {DEVICE} shell wm size 750x1624"
        density_command = f"adb -s {DEVICE} shell wm density 160"
        launch_command = f"flutter run -d {DEVICE} --debug --no-resident"
        capture_command = f"adb -s {DEVICE} shell screencap -p /sdcard/iff_actual.png"
        launch_entry = next(command for command in commands if command.startswith(launch_command))
        assert commands.index(size_command) < commands.index(density_command), commands
        assert commands.index(density_command) < commands.index(launch_entry), commands
        assert commands.index(launch_entry) < commands.index(capture_command), commands
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["reference_dimensions"] == {"width": 750, "height": 1624}, manifest
        assert manifest["captured_dimensions"] == {"width": 750, "height": 1624}, manifest
        assert manifest["viewport"] == {"width": 750, "height": 1624, "density": 160}, manifest

        env["IFF_CAPTURE_SOURCE"] = str(mismatching)
        mismatch_manifest = root / "mismatch_manifest.json"
        mismatch = run_capture(
            root=root,
            env=env,
            reference=reference,
            out=root / "mismatch.png",
            manifest=mismatch_manifest,
        )
        assert mismatch.returncode != 0, mismatch.stdout + mismatch.stderr
        error = mismatch.stdout + mismatch.stderr
        assert (
            "captured screenshot size 1280x2856 does not match reference 750x1624; "
            "resizing is forbidden"
        ) in error, error
        assert not mismatch_manifest.exists(), mismatch_manifest

    print("PASS: capture applies and verifies exact board reference dimensions without resizing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
