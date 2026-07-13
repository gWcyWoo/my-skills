#!/usr/bin/env python3
"""Run the deterministic iFF fetch/compile prefix for every URL in one row."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def parse_design_urls(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;；\r\n]+", value) if part.strip()]


def run_command(command: list[str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    record = {
        "command": command,
        "exitCode": completed.returncode,
        "stdoutSha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderrSha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
    }
    return completed, record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument("--row-json", required=True)
    parser.add_argument("--spec-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scripts = Path(args.skill_dir).expanduser().resolve() / "scripts"
    row_path = Path(args.row_json).expanduser().resolve()
    spec_root = Path(args.spec_root).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    row = json.loads(row_path.read_text(encoding="utf-8"))
    urls = parse_design_urls(str(row.get("design_url") or ""))
    if not urls:
        raise SystemExit("ERROR: design_url contains no board URLs")
    spec_root.mkdir(parents=True, exist_ok=True)

    boards: list[dict] = []
    for url in urls:
        result = {"url": url, "board": None, "ok": False, "commands": [], "error": None}
        fetch, record = run_command(
            [sys.executable, str(scripts / "fetch.py"), "--url", url, "--parent-dir", str(spec_root)]
        )
        result["commands"].append(record)
        if fetch.returncode != 0:
            result["error"] = f"fetch.py exited {fetch.returncode}"
            boards.append(result)
            continue
        try:
            summary = json.loads(fetch.stdout)
            board_dir = Path(str(summary["dir"])).resolve()
            raw = Path(str(summary["raw_json"])).resolve()
            board_dir.relative_to(spec_root)
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            result["error"] = f"invalid fetch.py summary: {error}"
            boards.append(result)
            continue
        result["board"] = board_dir.name
        assets = board_dir / "assets"
        commands = [
            [sys.executable, str(scripts / "write.py"), "--input", str(raw), "--output", str(board_dir / "spec.md")],
            [sys.executable, str(scripts / "download_cover.py"), "--url", url, "--out", str(board_dir / "reference.png")],
            [sys.executable, str(scripts / "classify_design.py"), "--raw", str(raw), "--reference", str(board_dir / "reference.png"), "--out", str(board_dir / "design_classification.json")],
            [sys.executable, str(scripts / "export_figma_scene.py"), "--raw", str(raw), "--assets", str(assets), "--out", str(board_dir / "scene.json")],
            [sys.executable, str(scripts / "check_figma_scene.py"), "--scene", str(board_dir / "scene.json")],
            [sys.executable, str(scripts / "export_tokens.py"), "--scene", str(board_dir / "scene.json"), "--out", str(board_dir / "tokens.json")],
            [sys.executable, str(scripts / "export_assets_manifest.py"), "--scene", str(board_dir / "scene.json"), "--out", str(board_dir / "assets_manifest.json")],
            [sys.executable, str(scripts / "group_figma_layout.py"), "--scene", str(board_dir / "scene.json"), "--out", str(board_dir / "groups.json")],
        ]
        for command in commands:
            completed, record = run_command(command)
            result["commands"].append(record)
            if completed.returncode != 0:
                result["error"] = (
                    f"{Path(command[1]).name} exited {completed.returncode}"
                )
                break
        else:
            result["ok"] = True
        boards.append(result)

    report = {
        "version": 1,
        "rowJson": str(row_path),
        "rowSha256": hashlib.sha256(row_path.read_bytes()).hexdigest(),
        "specRoot": str(spec_root),
        "boards": boards,
        "ok": all(board["ok"] for board in boards),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report["ok"]:
        print(f"ERROR: fetch pipeline failed for {sum(not board['ok'] for board in boards)} board(s)")
        return 1
    print(f"ok fetch pipeline: {len(boards)} board(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
