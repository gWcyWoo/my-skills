#!/usr/bin/env python3
"""Issue and verify fail-closed assembly completion evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


KIND = "iff_assembly_completion"
SCHEMA_VERSION = 1
SNAPSHOT_NAMES = {
    "actual.png",
    "api_integration_report.json",
    "artifact_digest.json",
    "diff_report.json",
    "implementation_plan.json",
    "interaction_test_evidence.json",
    "shared_components.local.json",
    "visual_manifest.json",
    "wiring_report.json",
    "worker_compliance.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def find_runtime_capture(spec_root: Path) -> tuple[Path, Path]:
    manifests = sorted(spec_root.rglob("visual_manifest.json"))
    for manifest in manifests:
        document = load_json(manifest)
        if document.get("actual_source") != "simulator_screenshot":
            continue
        local_actual = manifest.parent / "actual.png"
        if local_actual.is_file() and local_actual.stat().st_size > 0:
            return manifest, local_actual
    raise SystemExit(
        "ERROR: completion requires non-empty actual.png beside a visual_manifest.json "
        "with actual_source=simulator_screenshot"
    )


def snapshot(spec_root: Path) -> list[dict[str, str]]:
    paths = []
    for path in sorted(spec_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SNAPSHOT_NAMES or path.name.startswith("render_fidelity") and path.suffix == ".json":
            paths.append({
                "path": str(path.relative_to(spec_root)),
                "sha256": sha256(path),
            })
    return paths


def run_done_gate(spec_root: Path, report: Path) -> subprocess.CompletedProcess[str]:
    gate = Path(__file__).resolve().parent / "check_done_gate.py"
    return subprocess.run(
        [
            sys.executable,
            str(gate),
            "--spec-root",
            str(spec_root),
            "--out",
            str(report),
        ],
        text=True,
        capture_output=True,
    )


def forward_failure(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="", file=sys.stderr)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def issue(args: argparse.Namespace) -> int:
    spec_root = Path(args.spec_root).expanduser().resolve()
    evidence = Path(args.evidence).expanduser().resolve()
    if evidence.exists():
        evidence.unlink()
    if not spec_root.is_dir():
        raise SystemExit(f"ERROR: spec root not found: {spec_root}")

    gate_report = spec_root / "assembly_done_gate_report.json"
    result = run_done_gate(spec_root, gate_report)
    if result.returncode != 0:
        forward_failure(result)
        return result.returncode
    manifest, actual = find_runtime_capture(spec_root)
    gate_document = load_json(gate_report)
    if not gate_document.get("ok"):
        raise SystemExit("ERROR: check_done_gate report is not ok")

    document = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "specRoot": str(spec_root),
        "issuedAt": datetime.now(timezone.utc).isoformat(),
        "doneGate": {
            "exitCode": 0,
            "report": str(gate_report.relative_to(spec_root)),
            "reportSha256": sha256(gate_report),
        },
        "runtimeCapture": {
            "manifest": str(manifest.relative_to(spec_root)),
            "actual": str(actual.relative_to(spec_root)),
        },
        "artifacts": snapshot(spec_root),
    }
    dump_json(evidence, document)
    print(json.dumps({"ok": True, "completionEvidence": str(evidence)}, ensure_ascii=False))
    return 0


def verify(args: argparse.Namespace) -> int:
    spec_root = Path(args.spec_root).expanduser().resolve()
    evidence = Path(args.evidence).expanduser().resolve()
    if not evidence.is_file():
        print(f"ERROR: completion evidence missing: {evidence}", file=sys.stderr)
        return 1
    document = load_json(evidence)
    errors = []
    if document.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("unsupported schemaVersion")
    if document.get("kind") != KIND:
        errors.append("invalid completion evidence kind")
    if document.get("specRoot") != str(spec_root):
        errors.append("specRoot mismatch")
    if (document.get("doneGate") or {}).get("exitCode") != 0:
        errors.append("done gate exitCode is not zero")
    gate_data = document.get("doneGate") or {}
    gate_report = (spec_root / str(gate_data.get("report") or "")).resolve()
    if not gate_report.is_file():
        errors.append("done gate report missing")
    elif sha256(gate_report) != gate_data.get("reportSha256"):
        errors.append("done gate report changed")
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifact snapshot missing")
    else:
        for item in artifacts:
            if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
                errors.append("invalid artifact snapshot entry")
                continue
            path = (spec_root / str(item["path"])).resolve()
            if not path.is_file():
                errors.append(f"snapshotted artifact missing: {item['path']}")
            elif sha256(path) != item["sha256"]:
                errors.append(f"snapshotted artifact changed: {item['path']}")
    if errors:
        print("ERROR: invalid assembly completion evidence:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    find_runtime_capture(spec_root)
    with tempfile.TemporaryDirectory(prefix="iff-assembly-verify-") as raw_tmp:
        result = run_done_gate(spec_root, Path(raw_tmp) / "done_gate_report.json")
    if result.returncode != 0:
        forward_failure(result)
        return result.returncode
    print(json.dumps({"ok": True, "completionEvidence": str(evidence)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("issue", issue), ("verify", verify)):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--spec-root", required=True)
        subparser.add_argument("--evidence", required=True)
        subparser.set_defaults(handler=handler)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
