#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(*command: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def run_failure(expected: str, *command: str) -> None:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert expected in combined, combined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args()
    scripts = args.skill_dir.resolve() / "scripts"

    with tempfile.TemporaryDirectory(prefix="iff-reference-region-fallback-") as raw_tmp:
        tmp = Path(raw_tmp)
        project = tmp / "project"
        source_spec = tmp / "source-spec"
        source_spec.mkdir(parents=True)
        reference = source_spec / "reference.png"
        image = Image.new("RGBA", (100, 100), (240, 240, 240, 255))
        ImageDraw.Draw(image).rectangle((15, 26, 24, 37), fill=(12, 34, 56, 255))
        image.save(reference)

        scene = tmp / "scene.json"
        assets = tmp / "assets.json"
        layout = tmp / "layout.json"
        raw_plan = tmp / "render_plan.raw.json"
        prepared_plan = tmp / "render_plan.json"
        asset_manifest = tmp / "shared_assets.json"
        job_path = tmp / "component.json"
        asset_target = project / "lib" / "src" / "assets" / "shared"

        write_json(
            scene,
            {
                "sourceSchema": "selftest",
                "nodes": [
                    {
                        "id": "root",
                        "name": "Paintless group",
                        "type": "groupLayer",
                        "bbox": [10, 20, 40, 40],
                        "children": ["leaf"],
                        "absoluteTransform": [[1, 0, 10], [0, 1, 20]],
                        "radius": {"topLeft": 0, "topRight": 0, "bottomRight": 0, "bottomLeft": 0},
                    },
                    {
                        "id": "leaf",
                        "name": "Missing exported image",
                        "type": "shapeLayer",
                        "bbox": [15, 26, 10, 12],
                        "children": [],
                        "absoluteTransform": [[1, 0, 15], [0, 1, 26]],
                        "radius": {"topLeft": 4, "topRight": 4, "bottomRight": 4, "bottomLeft": 4},
                    },
                ],
            },
        )
        write_json(assets, {})
        write_json(
            layout,
            {"component": {"widgets": {"root": {"node": "root"}, "leaf": {"node": "leaf"}}}},
        )
        write_json(
            job_path,
            {
                "schemaVersion": 1,
                "signature": "header:paint-missing",
                "project_root": str(project),
                "source_spec_dir": str(source_spec),
                "bbox": [10, 20, 40, 40],
                "canonical_nodes": ["root", "leaf"],
                "paint_missing_positions": [1],
                "pooled_assets": {},
                "assets_incomplete": True,
            },
        )

        run(
            sys.executable,
            str(scripts / "make_render_plan.py"),
            "--scene",
            str(scene),
            "--assets",
            str(assets),
            "--layout",
            str(layout),
            "--root-node",
            "root",
            "--out",
            str(raw_plan),
        )
        raw = json.loads(raw_plan.read_text(encoding="utf-8"))
        assert raw["nodes"]["root"]["required"] is False, raw["nodes"]["root"]
        assert raw["nodes"]["leaf"]["bbox"] == [5.0, 6.0, 10.0, 12.0]

        run(
            sys.executable,
            str(scripts / "prepare_shared_component_assets.py"),
            "--job",
            str(job_path),
            "--render-plan",
            str(raw_plan),
            "--target",
            str(asset_target),
            "--out",
            str(prepared_plan),
            "--manifest-out",
            str(asset_manifest),
        )
        prepared = json.loads(prepared_plan.read_text(encoding="utf-8"))
        manifest = json.loads(asset_manifest.read_text(encoding="utf-8"))
        fallback = manifest["reference_fallbacks"][0]
        assert prepared["nodes"]["leaf"]["assetProvenance"] == fallback
        assert fallback["node"] == "leaf"
        assert fallback["reason"] == "missing_visible_paint_source"
        assert fallback["source_bbox"] == [15.0, 26.0, 10.0, 12.0]
        assert fallback["reference_sha256"] == hashlib.sha256(reference.read_bytes()).hexdigest()

        relative_asset = prepared["nodes"]["leaf"]["asset"]
        generated_asset = project / relative_asset
        assert generated_asset.is_file(), generated_asset
        with Image.open(generated_asset) as cropped:
            assert cropped.size == (10, 12)
            assert cropped.convert("RGBA").getpixel((0, 0)) == (12, 34, 56, 255)

        run(sys.executable, str(scripts / "check_render_plan.py"), str(prepared_plan))

        forged_plan = tmp / "forged_render_plan.json"
        forged = json.loads(json.dumps(prepared))
        forged["nodes"]["leaf"]["assetProvenance"]["reference_sha256"] = "not-a-valid-hash"
        write_json(forged_plan, forged)
        run_failure(
            "asset path looks like reference image",
            sys.executable,
            str(scripts / "check_render_plan.py"),
            str(forged_plan),
        )

        full_plan = tmp / "full_reference_plan.json"
        full_job = tmp / "full_reference_job.json"
        write_json(
            full_plan,
            {
                "nodes": {
                    "full": {
                        "bbox": [0, 0, 100, 100],
                        "children": [],
                        "visible": True,
                        "asset": None,
                    }
                }
            },
        )
        write_json(
            full_job,
            {
                "project_root": str(project),
                "source_spec_dir": str(source_spec),
                "bbox": [0, 0, 100, 100],
                "canonical_nodes": ["full"],
                "paint_missing_positions": [0],
                "pooled_assets": {},
            },
        )
        run_failure(
            "full-reference fallback is forbidden",
            sys.executable,
            str(scripts / "prepare_shared_component_assets.py"),
            "--job",
            str(full_job),
            "--render-plan",
            str(full_plan),
            "--target",
            str(asset_target),
            "--out",
            str(tmp / "full_reference_prepared.json"),
            "--manifest-out",
            str(tmp / "full_reference_assets.json"),
        )

    print("reference region fallback self-test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
