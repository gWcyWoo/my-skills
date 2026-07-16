#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    scripts = Path(__file__).resolve().parent
    skill = scripts.parent

    with tempfile.TemporaryDirectory(prefix="iff-contract-oas-command-") as raw_tmp:
        tmp = Path(raw_tmp)
        row = tmp / "row.json"
        spec = (tmp / "spec").resolve()
        prompt = tmp / "worker" / "prompt.md"
        row.write_text(
            json.dumps({"title": "Synthetic feature", "interaction": "tap to continue"}),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "contract",
                "--row-json",
                str(row),
                "--spec-dir",
                str(spec),
                "--project-root",
                str(tmp / "project"),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        generated = prompt.read_text(encoding="utf-8")
        expected = (
            f"python3 {scripts / 'oas_ref_resource_cache.py'} missing "
            f"--oas {spec / 'oas.json'} "
            f"--ref-resources {spec / 'oas_ref_resources.json'} "
            f"--out {spec / 'oas_missing_ref_paths.json'}"
        )
        assert expected in generated, {"expected": expected, "prompt": generated}
        assert "--cache " not in generated, generated
        assert "read_project_oas_ref_resources" not in generated, generated

    print("PASS: contract-worker prompt uses the authoritative OAS missing CLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
