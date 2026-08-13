#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    scripts = skill / "scripts"

    with tempfile.TemporaryDirectory(prefix="iff-fetch-feature-parent-") as raw_tmp:
        tmp = Path(raw_tmp)
        project = (tmp / "project").resolve()
        feature = project / "lanhu" / "specs" / "home"
        feature.mkdir(parents=True)
        feature_arg = feature.parent / "unused" / ".." / "home"
        urls = [
            "https://lanhu.example/design?image_id=one",
            "https://lanhu.example/design?image_id=two",
            "https://lanhu.example/design?image_id=three",
        ]
        prose = ["默认状态：展示可申请额度", "等待中：正在获取审核结果", "审核被拒：展示拒绝原因"]
        row = tmp / "row.json"
        prompt = tmp / "fetch_prompt.md"
        row.write_text(
            json.dumps(
                {
                    "title": "Home",
                    "design_url": (
                        f"{prose[0]}\n{urls[0]}；\n"
                        f"{prose[1]}\n{urls[1]}\n"
                        f"{prose[2]}；\n{urls[2]}"
                    ),
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
                str(feature_arg),
                "--project-root",
                str(project),
                "--out",
                str(prompt),
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode

        generated = prompt.read_text(encoding="utf-8")
        failures = []
        expected_argv_lines = []
        for url in urls:
            expected_argv = json.dumps(
                [
                    "python3",
                    str(scripts / "fetch.py"),
                    "--url",
                    url,
                    "--parent-dir",
                    str(feature),
                ]
            )
            expected_argv_lines.append(expected_argv)

        actual_argv_lines = [
            line
            for line in generated.splitlines()
            if line.startswith('["python3",') and str(scripts / "fetch.py") in line
        ]
        if actual_argv_lines != expected_argv_lines:
            failures.append(
                f"fetch argv count/order mismatch: expected={expected_argv_lines}, actual={actual_argv_lines}"
            )
        if any(text in line for text in prose for line in actual_argv_lines):
            failures.append("descriptive prose was emitted as a fetch URL")

        blocker_contract = (
            "external_blocker.command must copy the failed argv above unchanged, "
            f"including --parent-dir {feature}"
        )
        if blocker_contract not in generated:
            failures.append("blocker contract does not preserve the resolved feature parent-dir")
        if '"--parent-dir", "lanhu/specs"' in generated:
            failures.append("prompt still contains the generic parent-dir")

        if failures:
            for failure in failures:
                print(f"ERROR: {failure}")
            return 1

    print("PASS: fetch prompt and blocker contract preserve the resolved feature parent-dir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
