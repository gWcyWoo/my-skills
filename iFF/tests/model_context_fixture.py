from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from iFF.scripts.model_context_contract import persist_model_input
from iFF.scripts.verify_pipeline_scripts import build_report as build_preflight_report


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def run_script(name: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / name), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
    )


def persist_packet(path: Path, ledger: Path, kind: str, owner: str) -> None:
    persist_model_input(path.read_bytes(), kind=kind, owner=owner, ledger=ledger)


def prepare_v3_context(
    root: Path,
    board_names: tuple[str, ...] = ("default",),
    *,
    project: Path | None = None,
    spec: Path | None = None,
    manifest: Path | None = None,
) -> tuple[Path, Path, Path, Path]:
    project = project or root / "project"
    spec = spec or project / "spec" / "home"
    manifest = manifest or project / ".iff" / "features" / "home.json"
    if manifest.is_file():
        manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
        board_names = tuple(
            str(value["board"])
            for value in (manifest_doc.get("states") or {}).values()
        )
    else:
        write_json(
            manifest,
            {
                "featureId": "home",
                "states": {
                    board: {
                        "board": board,
                        "canvasPath": f"lib/{board}_canvas.dart",
                        "generatedFiles": [f"lib/{board}_canvas.dart"],
                    }
                    for board in board_names
                },
            },
        )
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    feature = str(manifest_doc.get("featureId") or spec.name)
    row = spec / "row.json"
    write_json(row, {"title": "home", "design_url": "https://design/1"})
    preflight = project / ".iff" / "preflight_report.json"
    write_json(preflight, build_preflight_report(SKILL_DIR))
    workers_dir = spec / ".iff" / "workers"

    for board in board_names:
        board_dir = spec / board
        board_dir.mkdir(parents=True, exist_ok=True)
        worker_id = f"board--{board}"
        prompt = workers_dir / f"{worker_id}.prompt.md"
        made = run_script(
            "make_worker_prompt.py",
            "--skill-dir",
            SKILL_DIR,
            "--row-json",
            row,
            "--spec-dir",
            board_dir,
            "--project-root",
            project,
            "--mode",
            "board",
            "--feature-manifest",
            manifest,
            "--preflight-report",
            preflight,
            "--out",
            prompt,
        )
        if made.returncode != 0:
            raise AssertionError(made.stdout + made.stderr)
        output = project / ".iff" / "worker_outputs" / f"{worker_id}.json"
        write_json(output, {"version": 1, "nodes": []})
        result = workers_dir / f"{worker_id}.result.json"
        write_json(result, {"outputs": [str(output)]})
        completed = run_script(
            "complete_worker.py",
            "--skill-dir",
            SKILL_DIR,
            "--feature-manifest",
            manifest,
            "--contract-input",
            workers_dir / f"{worker_id}.contract.json",
            "--result",
            result,
            "--out",
            workers_dir / f"{worker_id}.receipt.json",
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stdout + completed.stderr)

    prompt = workers_dir / "assembly.prompt.md"
    made = run_script(
        "make_worker_prompt.py",
        "--skill-dir",
        SKILL_DIR,
        "--row-json",
        row,
        "--spec-dir",
        spec,
        "--project-root",
        project,
        "--mode",
        "assembly",
        "--feature-manifest",
        manifest,
        "--preflight-report",
        preflight,
        "--out",
        prompt,
    )
    if made.returncode != 0:
        raise AssertionError(made.stdout + made.stderr)
    assembly_output = project / ".iff" / "worker_outputs" / "assembly.json"
    write_json(assembly_output, {"changes": []})
    result = workers_dir / "assembly.result.json"
    write_json(result, {"outputs": [str(assembly_output)]})
    completed = run_script(
        "complete_worker.py",
        "--skill-dir",
        SKILL_DIR,
        "--feature-manifest",
        manifest,
        "--contract-input",
        workers_dir / "assembly.contract.json",
        "--result",
        result,
        "--out",
        workers_dir / "assembly.receipt.json",
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)

    ledger = spec / ".iff" / "model_context.jsonl"
    for board in board_names:
        board_dir = spec / board
        source = board_dir / "artifact_digest.json"
        if not source.is_file():
            write_json(source, {"scene": {"nodeCount": 1}})
        packet = board_dir / "visual_model_packet.json"
        made = run_script(
            "make_visual_model_packet.py",
            "--spec-dir",
            board_dir,
            "--out",
            packet,
            "--ledger",
            ledger,
        )
        if made.returncode != 0:
            raise AssertionError(made.stdout + made.stderr)
        packet_doc = json.loads(packet.read_text(encoding="utf-8"))
        expected_scope = {"feature": feature, "board": board}
        if packet_doc.get("scope") != expected_scope:
            packet_doc["scope"] = expected_scope
            write_json(packet, packet_doc)
            persist_packet(packet, ledger, "visual_model_packet", board)

    batch = project / ".iff" / "batch_shared_components.json"
    write_json(batch, {"components": []})
    component = project / ".iff" / "component_model_packet.json"
    write_json(
        component,
        {
            "version": 2,
            "kind": "component",
            "scope": {"feature": feature},
            "sources": {"batch": {"path": str(batch), "sha256": _sha(batch)}},
            "action": {"kind": "none", "reason": "no candidates"},
        },
    )
    persist_packet(component, ledger, "component_model_packet", f"feature--{feature}")

    interaction_source = spec / "interaction_contract.json"
    if not interaction_source.is_file():
        write_json(interaction_source, {"rules": []})
    interaction = spec / "interaction_model_packet.json"
    write_json(
        interaction,
        {
            "version": 2,
            "kind": "interaction",
            "scope": {"feature": feature},
            "sources": {
                "contract": {
                    "path": str(interaction_source),
                    "sha256": _sha(interaction_source),
                }
            },
            "action": {"kind": "none", "reason": "complete"},
        },
    )
    persist_packet(interaction, ledger, "interaction_model_packet", "assembly")

    data_source = spec / "model_context_input.json"
    write_json(data_source, {"bindings": []})
    data = spec / "data_model_packet.json"
    write_json(
        data,
        {
            "version": 2,
            "kind": "data",
            "scope": {"feature": feature},
            "sources": {
                "bindings": {"path": str(data_source), "sha256": _sha(data_source)}
            },
            "action": {"kind": "none", "reason": "complete"},
        },
    )
    persist_packet(data, ledger, "data_model_packet", "assembly")
    return project, spec, spec / "model_context_report.json", manifest


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
