#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="iff-assembly-runtime-device-") as raw_tmp:
        root = Path(raw_tmp)
        spec = root / "feature" / "board"
        spec.mkdir(parents=True)
        project = root / "project"
        project.mkdir()
        row = root / "row.json"
        prompt_path = root / "worker_prompt.md"
        row.write_text(json.dumps({"title": "Generic runtime capture"}), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(skill / "scripts" / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "assembly",
                "--row-json",
                str(row),
                "--spec-dir",
                str(spec.parent),
                "--project-root",
                str(project),
                "--out",
                str(prompt_path),
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        prompt = prompt_path.read_text(encoding="utf-8")
        assert len(prompt.encode("utf-8")) <= 17800, len(prompt.encode("utf-8"))

    select = "select_runtime_device.py --platform auto"
    readiness = "check_capture_readiness.py --project-root"
    build = "Build outside the device lock"
    capture = "capture_runtime_screenshot.py --selection"
    assert select in prompt, prompt
    assert readiness in prompt, prompt
    assert build in prompt, prompt
    assert capture in prompt, prompt
    assert "--reference <selected-board>/reference.png" in prompt, prompt
    assert prompt.index(readiness) < prompt.index(select) < prompt.index(build) < prompt.index(capture), prompt
    assert "flutter build apk --release --split-per-abi" in prompt, prompt
    assert "pass it with `--android-apk`" in prompt, prompt
    assert "Never repeat ineffective cleanup/build/install" in prompt, prompt
    assert "Never use `adb wait-for-device`" in prompt, prompt
    assert "Android falls back to iOS" in prompt, prompt
    assert "commands are bounded" in prompt, prompt
    assert "Pixel_9_Pro" not in prompt, prompt

    print("ok assembly runtime device contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
