#!/usr/bin/env python3
"""Regression test for bounded assembly-worker prompts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def write_shared_component_contracts(
    feature: Path,
    project: Path,
    *,
    payload_bytes: int,
) -> None:
    board_dirs = sorted(path for path in feature.iterdir() if path.is_dir())
    registry_path = project / ".iff" / "shared_components.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registrations = {}
    local_components: dict[Path, list[dict]] = {path: [] for path in board_dirs}
    for index in range(11):
        signature = f"component:shared-{index:02d}"
        expected_path = project / "lib" / "shared" / f"shared_{index:02d}.expected.json"
        registrations[signature] = {
            "name": f"Shared{index:02d}",
            "widget_path": f"lib/shared/shared_{index:02d}.dart",
            "assets": [f"assets/shared/shared_{index:02d}.webp"],
            "fonts": [f"fonts/Shared{index:02d}.ttf"],
            "expected_path": str(expected_path),
            "expected_nodes": {
                f"node-{index:02d}": {
                    "bbox": [0, index, 320, 64],
                    "verbosePayload": "x" * payload_bytes,
                }
            },
            "verified": True,
        }
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        expected_path.write_text(
            json.dumps(registrations[signature]["expected_nodes"], sort_keys=True),
            encoding="utf-8",
        )
        board = board_dirs[index % len(board_dirs)]
        local_components[board].append(
            {
                "signature": signature,
                "kind": "navigation" if index % 2 == 0 else "bottom_tabs",
                "status": "reuse",
                "name": f"Shared{index:02d}",
                "widget_path": f"lib/shared/shared_{index:02d}.dart",
                "group_node": f"group-{index:02d}",
                "bbox": [0, index * 10, 320, 64],
                "node_map": {f"source-{index:02d}": f"node-{index:02d}"},
                "expected_nodes": registrations[signature]["expected_nodes"],
            }
        )
    if len(board_dirs) > 1:
        repeated = json.loads(json.dumps(local_components[board_dirs[0]][0]))
        repeated["group_node"] = "repeat-group-00"
        repeated["node_map"] = {"repeat-source-00": "node-00"}
        local_components[board_dirs[1]].append(repeated)
    registry_path.write_text(
        json.dumps({"version": 1, "components": registrations}),
        encoding="utf-8",
    )
    for board, components in local_components.items():
        (board / "shared_components.local.json").write_text(
            json.dumps({"registry": str(registry_path), "components": components}),
            encoding="utf-8",
        )


def invoke_prompt(
    skill: Path,
    root: Path,
    board_count: int,
    *,
    title: str,
    shared_payload_bytes: int | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    feature = root / f"feature-{board_count}"
    for index in range(board_count):
        (feature / f"board-{index:02d}").mkdir(parents=True, exist_ok=True)
    project = root / "project"
    project.mkdir(exist_ok=True)
    if shared_payload_bytes is not None:
        write_shared_component_contracts(
            feature,
            project,
            payload_bytes=shared_payload_bytes,
        )
    row = root / f"row-{board_count}.json"
    out = root / f"prompt-{board_count}.md"
    row.write_text(json.dumps({"title": title}), encoding="utf-8")
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
            str(feature),
            "--project-root",
            str(project),
            "--out",
            str(out),
        ],
        text=True,
        capture_output=True,
    )
    return result, out


def generate_prompt(skill: Path, root: Path, board_count: int) -> str:
    result, out = invoke_prompt(
        skill,
        root,
        board_count,
        title="Bounded assembly",
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return out.read_text(encoding="utf-8")


def main() -> int:
    skill = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="iff-assembly-bounded-") as raw_tmp:
        root = Path(raw_tmp)
        one_board = generate_prompt(skill, root, 1)
        eight_boards = generate_prompt(skill, root, 8)
        oversized, oversized_out = invoke_prompt(
            skill,
            root,
            9,
            title="x" * 5_000,
        )
        shared_small, shared_out = invoke_prompt(
            skill,
            root,
            3,
            title="High-cardinality shared assembly",
            shared_payload_bytes=32,
        )
        assert shared_small.returncode == 0, shared_small.stdout + shared_small.stderr
        shared_small_prompt = shared_out.read_text(encoding="utf-8")
        shared_verbose, shared_out = invoke_prompt(
            skill,
            root,
            3,
            title="High-cardinality shared assembly",
            shared_payload_bytes=4_096,
        )
        assert shared_verbose.returncode == 0, shared_verbose.stdout + shared_verbose.stderr
        shared_verbose_prompt = shared_out.read_text(encoding="utf-8")
        shared_index_path = root / "feature-3" / "assembly_shared_components.index.json"
        shared_index = json.loads(shared_index_path.read_text(encoding="utf-8"))
        repeated_signature = "component:shared-00"
        repeated_registration = next(
            item
            for item in shared_index["registrations"]
            if item["signature"] == repeated_signature
        )
        repeated_reuse = [
            item
            for item in shared_index["reuseMappings"]
            if item["signature"] == repeated_signature
        ]
        local_expected_contracts = [
            item
            for item in repeated_registration["expectedContracts"]
            if item["owner"] == "local"
        ]
        assert len(repeated_reuse) == 2, repeated_reuse
        assert len(local_expected_contracts) == 2, local_expected_contracts
        assert len({item["sourceSha256"] for item in local_expected_contracts}) == 2
        assert repeated_registration["assetPaths"] == ["assets/shared/shared_00.webp"]
        assert repeated_registration["fontPaths"] == ["fonts/Shared00.ttf"]
        assert repeated_registration["expectedSemanticSha256"]
        assert any(
            item.get("contentSha256")
            for item in repeated_registration["expectedContracts"]
            if item["kind"] == "path"
        )

        project = root / "project"
        registry_path = project / ".iff" / "shared_components.json"
        conflict_registry_path = project / ".iff" / "shared_components-conflict.json"
        conflict_registry = json.loads(registry_path.read_text(encoding="utf-8"))
        conflict_widget_path = "lib/shared/widgets/semantic_conflict.dart"
        conflict_registry["components"][repeated_signature]["widget_path"] = (
            conflict_widget_path
        )
        conflict_registry_path.write_text(
            json.dumps(conflict_registry),
            encoding="utf-8",
        )
        conflict_local_path = root / "feature-3" / "board-01" / "shared_components.local.json"
        conflict_local = json.loads(conflict_local_path.read_text(encoding="utf-8"))
        conflict_local["registry"] = str(conflict_registry_path)
        for component in conflict_local["components"]:
            if component["signature"] == repeated_signature:
                component["widget_path"] = conflict_widget_path
        conflict_local_path.write_text(json.dumps(conflict_local), encoding="utf-8")
        conflict_out = root / "prompt-conflict.md"
        conflict = subprocess.run(
            [
                sys.executable,
                str(skill / "scripts" / "make_worker_prompt.py"),
                "--skill-dir",
                str(skill),
                "--mode",
                "assembly",
                "--row-json",
                str(root / "row-3.json"),
                "--spec-dir",
                str(root / "feature-3"),
                "--project-root",
                str(project),
                "--out",
                str(conflict_out),
            ],
            text=True,
            capture_output=True,
        )
        assert conflict.returncode != 0, conflict.stdout + conflict.stderr
        assert f"conflicting shared-component registration: {repeated_signature}" in conflict.stderr
        assert not conflict_out.exists()

    assert oversized.returncode != 0, oversized.stdout + oversized.stderr
    assert "exceeds bounded-context limit" in oversized.stderr
    assert not oversized_out.exists()

    forbidden = [
        f"Read {skill / 'SKILL.md'} completely",
        "Fill ONLY the __MODEL__ placeholders listed in",
        "Child-board implementation plans are machine-prefilled at:",
    ]
    for text in forbidden:
        assert text not in eight_boards, text

    batch_script = str(skill / "scripts" / "assembly_plan_batch.py")
    assert eight_boards.count(batch_script) == 2, eight_boards
    assert "assembly_context.json" in eight_boards, eight_boards
    assert "assembly_decisions.json" in eight_boards, eight_boards
    assert "Edit ONLY the compact assembly_decisions.json" in eight_boards, eight_boards
    growth = len(eight_boards) - len(one_board)
    assert growth <= 512, {"prompt_growth_bytes": growth}
    assert len(eight_boards) <= 18_000, {"prompt_bytes": len(eight_boards)}
    assert len(shared_verbose_prompt.encode("utf-8")) <= 18_000
    assert len(shared_verbose_prompt) == len(shared_small_prompt)
    assert "verbosePayload" not in shared_verbose_prompt
    assert "assembly_shared_components.index.json" in shared_verbose_prompt

    print(
        f"PASS: assembly prompt is {len(eight_boards)} bytes and grows "
        f"{growth} bytes for +7 boards"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
