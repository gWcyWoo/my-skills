#!/usr/bin/env python3
"""Public-CLI regression for deterministic shared-worker compliance manifests."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message: str) -> int:
    print(f"FAIL {message}", file=sys.stderr)
    return 1


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent

    with tempfile.TemporaryDirectory(prefix="iff-shared-compliance-") as tmp_raw:
        tmp = Path(tmp_raw)
        copied_skill = (tmp / "iff").resolve()
        copied_scripts = copied_skill / "scripts"
        copied_scripts.mkdir(parents=True)
        shutil.copy2(skill / "SKILL.md", copied_skill / "SKILL.md")
        shutil.copy2(skill / "test_rules.md", copied_skill / "test_rules.md")
        shutil.copy2(skill / "implementation_rules.md", copied_skill / "implementation_rules.md")
        (copied_skill / "evolution").mkdir()
        shutil.copy2(skill / "evolution" / "case_memory.md", copied_skill / "evolution" / "case_memory.md")
        shutil.copy2(scripts / "verify_pipeline_scripts.py", copied_scripts / "verify_pipeline_scripts.py")
        shutil.copy2(scripts / "check_worker_compliance.py", copied_scripts / "check_worker_compliance.py")
        shutil.copy2(scripts / "common.py", copied_scripts / "common.py")

        project = (tmp / "project").resolve()
        source_spec = project / "lanhu" / "specs" / "home" / "首页-等待中"
        source_spec.mkdir(parents=True)
        job_dir = project / ".iff" / "shared_jobs" / "repeated-region"
        job_dir.mkdir(parents=True)
        component_json = job_dir / "component.json"
        component_json.write_text(
            json.dumps(
                {
                    "signature": "synthetic:repeated-region",
                    "source_spec_dir": str(source_spec),
                    "widget_path": "lib/shared/repeated_region_canvas.dart",
                    "colors_path": "lib/shared/repeated_region_canvas_colors.dart",
                    "test_path": "test/shared/repeated_region_canvas_test.dart",
                    "asset_target": "assets/shared/repeated_region",
                    "bbox": [0, 0, 320, 120],
                    "group_node": "group:repeated-region",
                    "class_name": "RepeatedRegionCanvas",
                    "result_path": str(job_dir / "shared_result.json"),
                }
            ),
            encoding="utf-8",
        )
        prompt = job_dir / "worker_prompt.md"

        generated = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--skill-dir",
                str(copied_skill),
                "--mode",
                "shared",
                "--component-json",
                str(component_json),
                "--spec-dir",
                str(job_dir),
                "--project-root",
                str(project),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        if generated.returncode != 0:
            return fail(f"make_worker_prompt exited {generated.returncode}: {generated.stderr.strip()}")

        prompt_text = prompt.read_text(encoding="utf-8")
        prefix = f"3. Run: python3 {copied_scripts / 'check_worker_compliance.py'} --write "
        command_line = next((line for line in prompt_text.splitlines() if line.startswith(prefix)), None)
        if command_line is None:
            candidates = [line for line in prompt_text.splitlines() if line.startswith("3. Run:")]
            return fail(
                "shared prompt lacks one deterministic compliance-manifest command: "
                f"candidates={candidates}"
            )
        if "3. Write " in prompt_text and "verify_pipeline_scripts_sha256" in prompt_text:
            return fail("shared prompt still asks the worker to transcribe compliance hashes")

        command = shlex.split(command_line.removeprefix("3. Run: "))
        written = subprocess.run(command, text=True, capture_output=True)
        if written.returncode != 0:
            return fail(f"generated compliance writer failed: {written.stderr.strip()}")

        manifest_path = job_dir / "worker_compliance.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        required_loaded_files: set[str] = set()
        for line in prompt_text.splitlines():
            if "loaded_files" not in line:
                continue
            read_clause, separator, _ = line.partition("; include ")
            _, read_separator, paths_text = read_clause.partition(". Read ")
            if not separator or not read_separator:
                return fail(f"cannot parse loaded_files requirement: {line}")
            required_loaded_files.update(path.strip() for path in paths_text.split(" and ") if path.strip())
        expected_required_files = {
            str(copied_skill / "implementation_rules.md"),
            str(copied_skill / "evolution" / "case_memory.md"),
        }
        if not expected_required_files.issubset(required_loaded_files):
            return fail(f"shared prompt lacks loaded_files requirements: {sorted(expected_required_files - required_loaded_files)}")
        loaded_files = set(manifest.get("loaded_files") or [])
        if not required_loaded_files.issubset(loaded_files):
            return fail(f"generated manifest lacks prompt-required loaded_files: {sorted(required_loaded_files - loaded_files)}")
        expected_hashes = {
            "skill_md_sha256": digest(copied_skill / "SKILL.md"),
            "test_rules_sha256": digest(copied_skill / "test_rules.md"),
            "verify_pipeline_scripts_sha256": digest(copied_scripts / "verify_pipeline_scripts.py"),
        }
        for key, value in expected_hashes.items():
            if manifest.get(key) != value:
                return fail(f"generated manifest has stale {key}")

        checked = subprocess.run(
            [
                sys.executable,
                str(copied_scripts / "check_worker_compliance.py"),
                "--manifest",
                str(manifest_path),
                "--skill-dir",
                str(copied_skill),
            ],
            text=True,
            capture_output=True,
        )
        if checked.returncode != 0:
            return fail(f"fresh generated manifest failed checker: {checked.stderr.strip()}")

        implementation_rules = copied_skill / "implementation_rules.md"
        implementation_rules.write_text(implementation_rules.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        drifted = subprocess.run(command, text=True, capture_output=True)
        if drifted.returncode == 0 or "changed after prompt generation" not in drifted.stderr:
            return fail(
                "compliance writer did not fail visibly on post-prompt script drift: "
                f"exit={drifted.returncode} stderr={drifted.stderr.strip()}"
            )

    print("PASS shared prompt writes every required loaded file and rejects post-prompt drift")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
