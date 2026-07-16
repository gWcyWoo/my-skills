#!/usr/bin/env python3
"""Deterministic smoke test for the shared-component worker bootstrap."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args: str) -> str:
    completed = subprocess.run([sys.executable, *args], text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stderr}"
        )
    return completed.stdout


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args()
    scripts = args.skill_dir.resolve() / "scripts"

    with tempfile.TemporaryDirectory(prefix="iff-shared-selftest-") as raw_tmp:
        tmp = Path(raw_tmp)
        project = tmp / "project"
        source_spec = tmp / "source_spec"
        pooled_spec = tmp / "pooled_spec"
        jobs_dir = tmp / "jobs"
        (project / "lib" / "src" / "common_widgets").mkdir(parents=True)
        (pooled_spec / "assets").mkdir(parents=True)
        (pooled_spec / "assets" / "icon.png").write_bytes(b"png")
        write_json(source_spec / "assets_manifest.json", {})
        write_json(
            pooled_spec / "assets_manifest.json",
            {"pooled-node": "assets/icon.png"},
        )

        batch = tmp / "batch_shared_components.json"
        write_json(
            batch,
            {
                "components": [
                    {
                        "signature": "header:test",
                        "kind": "header",
                        "status": "missing",
                        "best_asset_source": str(source_spec),
                        "assets_incomplete": True,
                        "paint_missing_positions": [],
                        "rows": [
                            {
                                "spec_dir": str(source_spec),
                                "group_node": "root-node",
                                "group_name": "Header",
                                "bbox": [10, 20, 300, 80],
                                "canonical_nodes": ["target-node"],
                            }
                        ],
                        "pooled_assets": {
                            "0": {
                                "spec_dir": str(pooled_spec),
                                "node": "pooled-node",
                            }
                        },
                    },
                    {
                        "signature": "header:paint-missing",
                        "kind": "header",
                        "status": "missing",
                        "best_asset_source": str(source_spec),
                        "assets_incomplete": True,
                        "paint_missing_positions": [1],
                        "rows": [
                            {
                                "spec_dir": str(source_spec),
                                "group_node": "paint-root-node",
                                "group_name": "PaintlessHeader",
                                "bbox": [0, 0, 40, 40],
                                "canonical_nodes": ["paint-root-node", "paint-leaf-node"],
                            }
                        ],
                        "pooled_assets": {},
                    },
                ]
            },
        )

        output = json.loads(
            run(
                str(scripts / "make_shared_component_jobs.py"),
                "--batch",
                str(batch),
                "--project-root",
                str(project),
                "--out-dir",
                str(jobs_dir),
            )
        )
        assert output["count"] == 2
        assert output["blockedCount"] == 0
        assert output["blockers"] == [], output
        jobs_by_signature = {}
        job_paths_by_signature = {}
        for generated_job_path in output["jobs"]:
            generated_job = json.loads(Path(generated_job_path).read_text(encoding="utf-8"))
            jobs_by_signature[generated_job["signature"]] = generated_job
            job_paths_by_signature[generated_job["signature"]] = Path(generated_job_path)
        job = jobs_by_signature["header:test"]
        job_path = job_paths_by_signature["header:test"]
        paint_job = jobs_by_signature["header:paint-missing"]
        assert job["widget_path"].startswith("lib/src/common_widgets/")
        assert job["paint_missing_positions"] == []
        assert paint_job["paint_missing_positions"] == [1]
        job_index = json.loads((jobs_dir / "jobs.json").read_text(encoding="utf-8"))
        assert job_index["blockers"] == output["blockers"], job_index

        prompt_path = tmp / "shared_prompt.txt"
        run(
            str(scripts / "make_worker_prompt.py"),
            "--mode",
            "shared",
            "--spec-dir",
            str(job_path.parent),
            "--project-root",
            str(project),
            "--component-json",
            str(job_path),
            "--out",
            str(prompt_path),
        )
        prompt = prompt_path.read_text(encoding="utf-8")
        assert "IFF_SHARED_COMPONENT_WORKER v1" in prompt
        assert "--root-node root-node" in prompt
        assert job["widget_path"] in prompt
        render_gate = f"check_render_plan.py {Path(job['job_dir']).resolve()}/component_render_plan.json"
        manifest_step = "make_component_manifest.py with the component render plan"
        canvas_step = "Run generate_canvas.py with --render-plan"
        assert render_gate in prompt, prompt
        assert prompt.index(render_gate) < prompt.index(manifest_step), prompt
        assert prompt.index(render_gate) < prompt.index(canvas_step), prompt

        raw_plan = tmp / "render_plan.raw.json"
        write_json(
            raw_plan,
            {
                "rootNode": "target-node",
                "componentRoot": {"node": "target-node", "sourceBBox": [0, 0, 24, 24], "bbox": [0, 0, 24, 24]},
                "nodes": {
                    "target-node": {
                        "id": "target-node",
                        "bbox": [0, 0, 24, 24],
                        "asset": None,
                        "implementation": "image_png",
                        "required": True,
                        "renderMode": "absolute_positioned",
                        "children": [],
                        "widgetTraceRequired": True,
                    }
                }
            },
        )
        prepared_plan = tmp / "render_plan.json"
        assets_manifest = tmp / "shared_assets_manifest.json"
        target = project / job["asset_target"]
        run(
            str(scripts / "prepare_shared_component_assets.py"),
            "--job",
            str(job_path),
            "--render-plan",
            str(raw_plan),
            "--target",
            str(target),
            "--out",
            str(prepared_plan),
            "--manifest-out",
            str(assets_manifest),
        )
        plan = json.loads(prepared_plan.read_text(encoding="utf-8"))
        copied = project / plan["nodes"]["target-node"]["asset"]
        assert copied.read_bytes() == b"png"
        assert plan["nodes"]["target-node"]["assetProvenance"]["kind"] == "exported_design_asset"
        manifest = json.loads(assets_manifest.read_text(encoding="utf-8"))
        assert manifest["assets"]["target-node"] == plan["nodes"]["target-node"]["asset"]
        run(str(scripts / "check_render_plan.py"), str(prepared_plan))

    print("ok shared component pipeline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
