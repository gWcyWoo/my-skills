from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path


EXTRACT_SCRIPT = Path(__file__).resolve().parents[2] / "extract" / "scripts" / "extract.py"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
URL_A = (
    "https://lanhuapp.com/web/#/item/project/detailDetach?"
    "pid=project-1&image_id=image-a&fromEditor=true"
)
URL_B = (
    "https://lanhuapp.com/web/#/item/project/detailDetach?"
    "pid=project-1&image_id=image-b&fromEditor=true"
)
EXPORTED_ASSET_URL = "https://assets.invalid/FigmaSlicePNGfixture.png"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_command(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def source_for(name: str, suffix: str, url: str) -> dict:
    return {
        "design_name": name,
        "design_id": f"design-{suffix}",
        "version_id": f"version-{suffix}",
        "lanhu_url": url,
        "source_identity": {
            "project_id": "project-1",
            "image_id": f"image-{suffix}",
            "team_id": "",
        },
        "figma_json": {
            "artboard": {
                "id": f"root:{suffix}",
                "type": "artboard",
                "name": name,
                "frame": {"x": 0, "y": 0, "width": 1, "height": 1},
                "fills": [{"enabled": True, "color": "#5B5CE2"}],
                "layers": [
                    {
                        "id": f"text:{suffix}",
                        "type": "textLayer",
                        "name": f"{name} content",
                        "frame": {"x": 0, "y": 0, "width": 1, "height": 1},
                        "text": {
                            "value": name,
                            "style": {
                                "content": name,
                                "fills": [
                                    {
                                        "enabled": True,
                                        "color": {
                                            "r": 0.125,
                                            "g": 0.25,
                                            "b": 0.5,
                                            "a": 1,
                                        },
                                    }
                                ],
                                "font": {
                                    "size": 14,
                                    "lineHeight": {"unit": "PIXELS", "value": 22},
                                },
                            },
                        },
                        "hasExportImage": True,
                        "image": {"imageUrl": EXPORTED_ASSET_URL},
                    }
                ],
            }
        },
    }


def complete_extract_design(project: Path, name: str, suffix: str) -> None:
    stage_dir = project / ".icp" / "extract" / name
    state = read_json(stage_dir / "state.json")
    draft = {
        "schema": "icp.extract.semantic-draft.v1",
        "source_manifest_sha256": state["source_manifest_sha256"],
        "blocks": [
            {
                "block_id": "page",
                "name": f"{name} page",
                "role": "page",
                "role_basis": "entailed",
                "role_evidence": ["The rendered artboard is the complete page."],
                "parent_block_id": None,
                "child_block_ids": ["content"],
                "appearance": {
                    "background": "Single page surface.",
                    "border": "No outer border.",
                    "spacing": "One content region fills the page.",
                },
                "content_summary": "One fixture page.",
                "composition": "A page contains one content region.",
                "relations": [],
            },
            {
                "block_id": "content",
                "name": f"{name} content",
                "role": "content",
                "role_basis": "entailed",
                "role_evidence": ["The visible text is the page content."],
                "parent_block_id": "page",
                "child_block_ids": [],
                "appearance": {
                    "background": "Inherits the page surface.",
                    "border": "No border.",
                    "spacing": "Occupies the available content area.",
                },
                "content_summary": f"Content for {name}.",
                "composition": "A single visible text element.",
                "relations": [],
            },
        ],
    }
    draft_path = stage_dir / "semantic-draft.input.json"
    write_json(draft_path, draft)
    result = run_command(
        EXTRACT_SCRIPT,
        "record-draft",
        "--project-root",
        str(project),
        "--design-name",
        name,
        "--draft",
        str(draft_path),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    state = read_json(stage_dir / "state.json")
    bindings = {
        "schema": "icp.extract.bindings.v1",
        "source_manifest_sha256": state["source_manifest_sha256"],
        "semantic_draft_sha256": state["semantic_draft_sha256"],
        "assignments": [
            {
                "source_node_id": f"root:{suffix}",
                "status": "mapped",
                "block_id": "page",
                "geometry_basis": "frame",
                "content_role": "static_visual",
                "rationale": "The artboard directly represents the page boundary.",
            },
            {
                "source_node_id": f"text:{suffix}",
                "status": "mapped",
                "block_id": "content",
                "geometry_basis": "frame",
                "content_role": "static_copy",
                "rationale": "The text directly represents the content block.",
            },
        ],
    }
    bindings_path = stage_dir / "bindings.input.json"
    write_json(bindings_path, bindings)
    result = run_command(
        EXTRACT_SCRIPT,
        "record-bindings",
        "--project-root",
        str(project),
        "--design-name",
        name,
        "--bindings",
        str(bindings_path),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    review_path = stage_dir / "semantic-review.input.json"
    review = read_json(review_path)
    review["decision"] = "pass"
    for item in review["block_reviews"]:
        item["role_correct"] = True
        item["hierarchy_correct"] = True
        item["appearance_interpretation_correct"] = True
        item["content_grouping_correct"] = True
        item["source_binding_correct"] = True
        item["evidence"] = ["The reference and bound source nodes agree."]
        item["issues"] = []
    for item in review["source_node_reviews"]:
        item["semantic_assignment_correct"] = True
        item["content_role_correct"] = True
        item["independent_grouping_correct"] = True
        item["parent_child_relation_correct"] = True
        item["evidence"] = [
            "The exact JSON node, its source relations, and assigned semantic Block agree."
        ]
        item["issues"] = []
    cross = review["cross_block_review"]
    cross["relations_correct"] = True
    cross["reading_order_correct"] = True
    cross["no_semantic_omissions"] = True
    cross["non_rendering_classifications_correct"] = True
    cross["evidence"] = ["Both semantic blocks have exact source coverage."]
    cross["issues"] = []
    write_json(review_path, review)
    result = run_command(
        EXTRACT_SCRIPT,
        "record-review",
        "--project-root",
        str(project),
        "--design-name",
        name,
        "--review",
        str(review_path),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    result = run_command(
        EXTRACT_SCRIPT,
        "verify",
        "--project-root",
        str(project),
        "--design-name",
        name,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def create_verified_extract(
    root: Path, ui_supplements: dict[str, str | None] | None = None
) -> Path:
    ui_supplements = ui_supplements or {
        URL_A: "Show the available withdrawal offer.",
        URL_B: "Show the selected withdrawal offer.",
    }
    project = root / "project"
    project.mkdir(parents=True)
    urls_path = root / "urls.json"
    reference_path = root / "reference.png"
    reference_path.write_bytes(PNG_1X1)
    assets_path = root / "assets"
    assets_path.mkdir()
    (assets_path / "fixture.png").write_bytes(PNG_1X1)
    write_json(
        urls_path,
        {
            "schema": "icp.extract.run-input.v2",
            "designs": [
                {
                    "design_url": url,
                    "ui_supplement": ui_supplements.get(url),
                }
                for url in (URL_A, URL_B)
            ],
        },
    )
    result = run_command(
        EXTRACT_SCRIPT,
        "begin-run",
        "--project-root",
        str(project),
        "--urls-file",
        str(urls_path),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    for name, suffix, url in (
        ("Design A", "a", URL_A),
        ("Design B", "b", URL_B),
    ):
        source_path = root / f"source-{suffix}.json"
        write_json(source_path, source_for(name, suffix, url))
        result = run_command(
            EXTRACT_SCRIPT,
            "prepare",
            "--project-root",
            str(project),
            "--source-json",
            str(source_path),
            "--reference-image",
            str(reference_path),
            "--assets-dir",
            str(assets_path),
            "--allow-loose-input",
            "--design-url",
            url,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        complete_extract_design(project, name, suffix)
    result = run_command(
        EXTRACT_SCRIPT, "verify-run", "--project-root", str(project)
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return project
