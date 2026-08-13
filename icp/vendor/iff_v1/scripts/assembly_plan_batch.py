#!/usr/bin/env python3
"""Prepare and apply compact model judgments for all assembly board plans."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys


MODEL_TODO = "__MODEL__"
SCHEMA_VERSION = 1
PROJECT_FIELDS = (
    "entrypoint",
    "appShell",
    "existingFeatureDirs",
    "missingFeatureDirs",
    "fanoutOwnedFiles",
    "faninRequests",
)
DETERMINISTIC_REGION_RATIONALE = (
    "Use the board-generated absolute canvas; merge or skip no required visible node."
)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: expected JSON object: {path}")
    return value


def dump_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def board_dirs(spec_root: Path) -> list[Path]:
    boards = [path.resolve() for path in sorted(spec_root.iterdir()) if path.is_dir()]
    if not boards:
        raise SystemExit(f"ERROR: assembly spec root has no child board directories: {spec_root}")
    return boards


def run_checked(argv: list[str]) -> None:
    result = subprocess.run(argv, text=True, capture_output=True)
    if result.returncode == 0:
        return
    if result.stdout:
        print(result.stdout, end="", file=sys.stderr)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    raise SystemExit(result.returncode)


def prepare(args: argparse.Namespace) -> int:
    spec_root = Path(args.spec_root).expanduser().resolve()
    project_root = Path(args.project_root).expanduser().resolve()
    scripts = Path(__file__).resolve().parent
    context_path = Path(args.context).expanduser().resolve()
    decisions_path = Path(args.decisions).expanduser().resolve()
    if not spec_root.is_dir():
        raise SystemExit(f"ERROR: spec root not found: {spec_root}")

    entries = []
    for board in board_dirs(spec_root):
        plan = board / "implementation_plan.json"
        digest = board / "artifact_digest.json"
        run_checked([sys.executable, str(scripts / "check_design_artifacts.py"), "--spec-dir", str(board)])
        run_checked([sys.executable, str(scripts / "summarize_spec_artifacts.py"), "--spec-dir", str(board)])
        run_checked([
            sys.executable,
            str(scripts / "prefill_implementation_plan.py"),
            "--spec-dir",
            str(board),
            "--project-root",
            str(project_root),
            "--out",
            str(plan),
            "--force",
        ])
        run_checked([
            sys.executable,
            str(scripts / "check_implementation_map.py"),
            "--render-plan",
            str(board / "render_plan.json"),
            "--implementation-map",
            str(board / "implementation_map.json"),
        ])
        plan_doc = load_json(plan)
        entries.append({
            "board": board.name,
            "specDir": str(board),
            "artifactDigest": str(digest),
            "implementationPlan": str(plan),
            "states": (plan_doc.get("fixtureAlignment") or {}).get("states") or [],
            "regions": [
                region.get("region")
                for region in (plan_doc.get("designAlignment") or {}).get("nodeCoveragePlan") or []
                if isinstance(region, dict)
            ],
        })

    context = {
        "schemaVersion": SCHEMA_VERSION,
        "preparedBy": "assembly_plan_batch.py",
        "specRoot": str(spec_root),
        "projectRoot": str(project_root),
        "boards": entries,
        "deterministicRegionRationale": DETERMINISTIC_REGION_RATIONALE,
    }
    decisions = {
        "schemaVersion": SCHEMA_VERSION,
        "specRoot": str(spec_root),
        "modelFields": [
            "projectAlignment.*",
            "fixtureSource",
            "stateDataByBoard.*",
        ],
        "projectAlignment": {field: MODEL_TODO for field in PROJECT_FIELDS},
        "fixtureSource": MODEL_TODO,
        "stateDataByBoard": {entry["board"]: MODEL_TODO for entry in entries},
    }
    dump_json(context_path, context)
    dump_json(decisions_path, decisions)
    print(json.dumps({
        "ok": True,
        "boardCount": len(entries),
        "context": str(context_path),
        "decisions": str(decisions_path),
    }, ensure_ascii=False))
    return 0


def is_model_complete(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and MODEL_TODO not in value
    if isinstance(value, list):
        return all(is_model_complete(item) for item in value)
    if isinstance(value, dict):
        return all(is_model_complete(item) for item in value.values())
    return value is not None


def apply_decisions(args: argparse.Namespace) -> int:
    context = load_json(Path(args.context).expanduser().resolve())
    decisions = load_json(Path(args.decisions).expanduser().resolve())
    if context.get("schemaVersion") != SCHEMA_VERSION or decisions.get("schemaVersion") != SCHEMA_VERSION:
        raise SystemExit("ERROR: unsupported assembly plan schemaVersion")
    if context.get("specRoot") != decisions.get("specRoot"):
        raise SystemExit("ERROR: assembly context/decisions specRoot mismatch")

    alignment = decisions.get("projectAlignment")
    if not isinstance(alignment, dict):
        raise SystemExit("ERROR: projectAlignment must be an object")
    missing = [field for field in PROJECT_FIELDS if field not in alignment]
    if missing:
        raise SystemExit(f"ERROR: projectAlignment missing fields: {', '.join(missing)}")
    fixture_source = decisions.get("fixtureSource")
    state_data = decisions.get("stateDataByBoard")
    if not isinstance(state_data, dict):
        raise SystemExit("ERROR: stateDataByBoard must be an object")
    model_payload = {"projectAlignment": alignment, "fixtureSource": fixture_source, "stateData": state_data}
    if not is_model_complete(model_payload):
        raise SystemExit("ERROR: assembly_decisions.json has empty or __MODEL__ judgments")

    scripts = Path(__file__).resolve().parent
    boards = context.get("boards")
    if not isinstance(boards, list) or not boards:
        raise SystemExit("ERROR: assembly context has no boards")
    applied = []
    for entry in boards:
        if not isinstance(entry, dict):
            raise SystemExit("ERROR: invalid board entry in assembly context")
        board_name = entry.get("board")
        if board_name not in state_data:
            raise SystemExit(f"ERROR: stateDataByBoard missing board: {board_name}")
        spec_dir = Path(str(entry.get("specDir"))).resolve()
        plan_path = Path(str(entry.get("implementationPlan"))).resolve()
        plan = load_json(plan_path)
        plan["projectAlignment"] = copy.deepcopy(alignment)
        fixture = plan.get("fixtureAlignment")
        if not isinstance(fixture, dict):
            raise SystemExit(f"ERROR: fixtureAlignment missing in {plan_path}")
        fixture["fixtureSource"] = fixture_source
        fixture["stateData"] = copy.deepcopy(state_data[board_name])
        regions = (plan.get("designAlignment") or {}).get("nodeCoveragePlan")
        if not isinstance(regions, list):
            raise SystemExit(f"ERROR: nodeCoveragePlan missing in {plan_path}")
        for region in regions:
            if isinstance(region, dict):
                region["mergeOrSkipRationale"] = DETERMINISTIC_REGION_RATIONALE
        dump_json(plan_path, plan)
        run_checked([
            sys.executable,
            str(scripts / "check_implementation_plan.py"),
            "--plan",
            str(plan_path),
            "--spec-dir",
            str(spec_dir),
        ])
        applied.append(str(plan_path))

    print(json.dumps({"ok": True, "appliedPlans": applied}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--spec-root", required=True)
    prepare_parser.add_argument("--project-root", required=True)
    prepare_parser.add_argument("--context", required=True)
    prepare_parser.add_argument("--decisions", required=True)
    prepare_parser.set_defaults(handler=prepare)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--context", required=True)
    apply_parser.add_argument("--decisions", required=True)
    apply_parser.set_defaults(handler=apply_decisions)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
