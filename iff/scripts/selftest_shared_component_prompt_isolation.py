#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


MAX_PARALLEL_SHARED_JOBS = 3
INTERMEDIATE_NAMES = (
    "worker_compliance.json",
    "component_layout_contract.json",
    "component_render_plan.raw.json",
    "component_render_plan.json",
    "shared_assets.json",
    "component_manifest.json",
)


def run(*args: str) -> str:
    completed = subprocess.run(args, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="iff-shared-prompt-isolation-") as raw_tmp:
        tmp = Path(raw_tmp)
        project = tmp / "project"
        source_spec = project / "lanhu" / "specs" / "feature"
        jobs_dir = project / ".iff" / "shared_jobs"
        (project / "lib" / "shared" / "widgets").mkdir(parents=True)
        source_spec.mkdir(parents=True)

        components = []
        for index in range(MAX_PARALLEL_SHARED_JOBS):
            components.append(
                {
                    "signature": f"isolated:{index}",
                    "kind": "region",
                    "status": "missing",
                    "best_asset_source": str(source_spec),
                    "assets_incomplete": False,
                    "rows": [
                        {
                            "spec_dir": str(source_spec),
                            "group_node": f"node-{index}",
                            "group_name": f"Shared region {index}",
                            "bbox": [0, 0, 100 + index, 40 + index],
                        }
                    ],
                    "pooled_assets": {},
                }
            )

        batch = tmp / "batch_shared_components.json"
        write_json(batch, {"components": components})
        generated = json.loads(
            run(
                sys.executable,
                str(scripts / "make_shared_component_jobs.py"),
                "--batch",
                str(batch),
                "--project-root",
                str(project),
                "--out-dir",
                str(jobs_dir),
            )
        )
        job_paths = [Path(value) for value in generated["jobs"]]
        assert len(job_paths) == MAX_PARALLEL_SHARED_JOBS
        assert len({path.parent for path in job_paths}) == len(job_paths)

        def generate_prompt(job_path: Path) -> tuple[dict, str]:
            prompt_path = job_path.parent / "worker_prompt.md"
            run(
                sys.executable,
                str(scripts / "make_worker_prompt.py"),
                "--mode",
                "shared",
                "--component-json",
                str(job_path),
                "--spec-dir",
                str(source_spec),
                "--project-root",
                str(project),
                "--out",
                str(prompt_path),
            )
            return json.loads(job_path.read_text(encoding="utf-8")), prompt_path.read_text(encoding="utf-8")

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SHARED_JOBS) as executor:
            generated_prompts = list(executor.map(generate_prompt, job_paths))

        owned_outputs: list[set[Path]] = []
        for job_path, (component, prompt) in zip(job_paths, generated_prompts):
            workspace = job_path.parent.resolve()
            intermediate_paths = {workspace / name for name in INTERMEDIATE_NAMES}
            for path in intermediate_paths:
                assert str(path) in prompt, f"shared prompt escaped its job workspace: {path}"
                assert str(source_spec / path.name) not in prompt, f"shared prompt retained colliding feature path: {path.name}"
            assert str(scripts / "generate_shared_component_test.py") in prompt, prompt
            assert "expectedNodeCount > 0" in prompt, prompt

            widget = (project / component["widget_path"]).resolve()
            outputs = intermediate_paths | {
                Path(component["result_path"]).resolve(),
                Path(component["compliance_path"]).resolve(),
                widget,
                Path(str(widget) + ".expected.json"),
                Path(str(widget) + ".slots.json"),
                (project / component["colors_path"]).resolve(),
                (project / component["test_path"]).resolve(),
                (project / component["asset_target"]).resolve(),
            }
            owned_outputs.append(outputs)

        for index, outputs in enumerate(owned_outputs):
            for sibling_outputs in owned_outputs[index + 1 :]:
                assert outputs.isdisjoint(sibling_outputs), "parallel shared jobs have overlapping writable outputs"

    print("PASS: parallel shared prompts own disjoint intermediate and output workspaces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
