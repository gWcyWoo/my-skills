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

    with tempfile.TemporaryDirectory(prefix="iff-fetch-blocker-contract-") as raw_tmp:
        tmp = Path(raw_tmp)
        row = tmp / "row.json"
        prompt = tmp / "worker" / "prompt.md"
        row.write_text(
            json.dumps(
                {
                    "title": "Synthetic feature",
                    "design_url": "https://lanhu.example/design?image_id=one;https://lanhu.example/design?image_id=two",
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "fetch",
                "--row-json",
                str(row),
                "--spec-dir",
                str(tmp / "specs"),
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
        required = [
            "IFF_FETCH_WORKER v2",
            "DO NOT request or retry sandbox escalation",
            '"kind": "external_network"',
            '"owner": "main_session"',
            '"requires_escalation": true',
            '"command": [',
            "allow the iFF workflow to fetch the user-provided Lanhu design",
            "followup_task",
        ]
        missing = [fragment for fragment in required if fragment not in generated]
        assert not missing, {"missing": missing, "prompt": generated}

    print("PASS: fetch-worker prompt makes network blockers structured and main-owned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
