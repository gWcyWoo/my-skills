#!/usr/bin/env python3
"""Deterministic gates for the ICP component-design stage."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ICP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ICP_ROOT / "scripts"))
from stage_checklist import (  # noqa: E402
    ChecklistError,
    complete as complete_checklist_node,
    create as create_checklist,
    node as checklist_node,
    require_complete as require_checklist_complete,
    require_ready as require_checklist_node_ready,
)


EXTRACT_SCRIPT = Path(__file__).resolve().parents[2] / "extract" / "scripts" / "extract.py"
MOBILE_COMPONENT_PATTERNS_PATH = (
    Path(__file__).resolve().parents[1]
    / "references"
    / "mobile-component-patterns.md"
)
MOBILE_COMPONENT_PATTERNS_STAGE_NAME = "mobile-component-patterns.md"
BLOCK_COMPONENT_BINDINGS_STAGE_NAME = "block-component-bindings.json"
COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SOURCE_AUTHORITY = {
    "business_source": "description_document",
    "design_source": "structure_visual_assets_and_placeholders_only",
    "fact_evidence_classes": {
        "business_source": "exact_same_page_source_spans_plus_candidate_blocks",
        "design_visible": "visible_only_candidate_blocks_without_source_spans",
    },
    "conflict_rule": "description_document_wins",
    "empty_description_rule": "do_not_invent_business_behavior",
}
PAGE_FACT_KINDS = {
    "responsibility",
    "condition",
    "behavior",
    "result",
    "state",
    "trigger",
    "data",
    "api_dependency",
    "component_relation",
}
INTERACTION_ITEM_FIELDS = ("condition", "state", "trigger", "behavior", "result")
INTERACTION_BEHAVIOR_KINDS = {
    "local",
    "api_call",
    "render",
    "navigate",
    "present",
    "validate",
    "mutate",
}
API_DIRECTIVE_RE = re.compile(
    r"(?<![A-Za-z0-9_])API\s*[:：]\s*"
    r"(?P<locator>"
    r"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+"
    r"(?:https?://|/)[A-Za-z0-9._~:/?#\[\]@!$&'()*+=%{}-]*"
    r"|https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+=%{}-]*"
    r"|/[A-Za-z0-9._~:/?#\[\]@!$&'()*+=%{}-]*"
    r"|\d+(?:/\d+)?"
    r")"
)
COMPONENT_RELATION_INTENTS = {
    "local_boundary",
    "shared_candidate",
    "shared_usage",
}
COMPONENT_RELATION_TARGET_KINDS = {"self_candidate", "source_member"}
FACT_EVIDENCE_CLASSES = {"business_source", "design_visible"}
DESIGN_VISIBLE_FACT_KINDS = {
    "responsibility",
    "state",
    "data",
    "component_relation",
}
PAGE_CANDIDATE_KINDS = {"page", "section", "component"}
COVERAGE_DISPOSITIONS = {"fact", "context", "unresolved"}
DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0
ABSTRACTION_DECISIONS = {
    "keep-local",
    "keep-separate",
    "reuse-existing",
    "adapt-existing",
    "extract-container",
    "extract-complete",
}
COMPONENT_SCOPES = {"local", "shared"}
REUSE_MODES = {"local", "container", "complete"}
FACT_BINDING_TARGETS = {
    "instance_fact",
    "capability",
    "data_role",
    "action_role",
    "component_ref",
}
LOCAL_COMPONENT_CONTRACT_FACT_KINDS = PAGE_FACT_KINDS - {"component_relation"}


class ContractError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError("missing_input", f"file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json", f"invalid JSON at {path}: {exc}") from exc


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(json_bytes(value))
    os.replace(temporary, path)


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(value)
    os.replace(temporary, path)


def build_mobile_component_pattern_context(value: bytes) -> dict[str, str]:
    try:
        content = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(
            "invalid_mobile_component_patterns",
            "mobile component patterns must be UTF-8",
        ) from exc
    if not content.strip():
        raise ContractError(
            "invalid_mobile_component_patterns",
            "mobile component patterns must not be empty",
        )
    return {
        "schema": "icp.component-design.mobile-component-pattern-context.v1",
        "knowledge_sha256": sha256_bytes(value),
        "content": content,
    }


def load_skill_mobile_component_pattern_context() -> tuple[dict[str, str], bytes]:
    try:
        value = MOBILE_COMPONENT_PATTERNS_PATH.read_bytes()
    except FileNotFoundError as exc:
        raise ContractError(
            "missing_mobile_component_patterns",
            f"mobile component patterns are missing: {MOBILE_COMPONENT_PATTERNS_PATH}",
        ) from exc
    return build_mobile_component_pattern_context(value), value


def verify_live_mobile_component_pattern_context(
    stage_dir: Path, state: dict[str, Any]
) -> dict[str, str]:
    path = stage_dir / MOBILE_COMPONENT_PATTERNS_STAGE_NAME
    try:
        value = path.read_bytes()
    except FileNotFoundError as exc:
        raise ContractError(
            "stage_drift", "mobile component pattern snapshot is missing"
        ) from exc
    context = build_mobile_component_pattern_context(value)
    if context["knowledge_sha256"] != state.get(
        "mobile_component_patterns_sha256"
    ):
        raise ContractError(
            "stage_drift", "mobile component pattern snapshot changed"
        )
    return context


def validate_mobile_component_pattern_context(
    value: object, state: dict[str, Any]
) -> dict[str, str]:
    context = require_dict(value, "mobile component pattern context")
    require_exact_keys(
        context,
        {"schema", "knowledge_sha256", "content"},
        "mobile component pattern context",
    )
    if context.get("schema") != (
        "icp.component-design.mobile-component-pattern-context.v1"
    ):
        raise ContractError(
            "input_drift", "mobile component pattern context schema changed"
        )
    content = require_string(
        context.get("content"), "mobile component pattern context content"
    )
    digest = sha256_bytes(content.encode("utf-8"))
    if (
        context.get("knowledge_sha256") != digest
        or digest != state.get("mobile_component_patterns_sha256")
    ):
        raise ContractError(
            "input_drift", "mobile component pattern context changed"
        )
    return copy.deepcopy(context)


@contextmanager
def stage_write_lock(project_root: Path, timeout_seconds: float):
    if timeout_seconds < 0:
        raise ContractError(
            "invalid_lock_timeout", "lock timeout must be zero or greater"
        )
    stage_dir = project_root / ".icp" / "component-design"
    stage_dir.mkdir(parents=True, exist_ok=True)
    lock_path = stage_dir / ".write.lock"
    deadline = time.monotonic() + timeout_seconds
    with lock_path.open("a+b") as lock_handle:
        while True:
            try:
                fcntl.flock(
                    lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
                break
            except BlockingIOError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ContractError(
                        "stage_busy",
                        "another component-design command holds the stage write lock",
                    ) from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("invalid_contract", f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError("invalid_contract", f"{label} must be an array")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("invalid_contract", f"{label} must be a non-empty string")
    return value


def require_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError("invalid_contract", f"{label} must be a string")
    return value


def require_nullable_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ContractError(
            "invalid_contract", f"{label} must be a non-empty string or null"
        )
    return value


def require_string_list(value: object, label: str, *, nonempty: bool = True) -> list[str]:
    items = require_list(value, label)
    if nonempty and not items:
        raise ContractError("invalid_contract", f"{label} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise ContractError("invalid_contract", f"{label} must contain non-empty strings")
    if len(set(items)) != len(items):
        raise ContractError("invalid_contract", f"{label} must not contain duplicates")
    return items


def require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    label: str,
    *,
    code: str = "invalid_contract",
) -> None:
    actual = set(value)
    if actual != expected:
        raise ContractError(
            code,
            f"{label} fields must be exactly {sorted(expected)}; got={sorted(actual)}",
        )


def is_non_normative_context(value: str) -> bool:
    return bool(value) and value.isspace()


def remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def component_checklist_specs(stage_dir: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [checklist_node("stage.begin", "Freeze the complete Stage 2 input.")]
    review_nodes: list[str] = []
    for page_key in require_dict(state.get("pages"), "page states"):
        page_input = require_dict(
            read_json(stage_dir / "page-component-facts" / f"{page_key}.input.json"),
            f"page input {page_key}",
        )
        dependency = "stage.begin"
        if require_list(page_input.get("api_requirements"), "page API requirements"):
            api_node = f"page:{page_key}.api-contracts"
            specs.append(
                checklist_node(
                    api_node,
                    f"Seal every API contract required by page {page_key}.",
                    ["stage.begin"],
                )
            )
            dependency = api_node
        facts_node = f"page:{page_key}.facts"
        review_node = f"page:{page_key}.review"
        specs.extend(
            [
                checklist_node(
                    facts_node,
                    f"Record complete component facts for page {page_key}.",
                    [dependency],
                ),
                checklist_node(
                    review_node,
                    f"Pass the complete page review for {page_key}.",
                    [facts_node],
                ),
            ]
        )
        review_nodes.append(review_node)
    specs.extend(
        [
            checklist_node(
                "group.abstraction",
                "Record the complete cross-page component abstraction.",
                review_nodes,
            ),
            checklist_node(
                "stage.verify",
                "Verify and seal the Stage 2 implementation contract.",
                ["group.abstraction"],
            ),
        ]
    )
    return specs


def component_checklist_input(state: dict[str, Any]) -> str:
    return sha256_bytes(
        canonical_bytes(
            {
                "extract_run_result_sha256": state["extract_run_result_sha256"],
                "source_catalog_sha256": state["source_catalog_sha256"],
                "iole_source_bundle_sha256": state["iole_source_bundle_sha256"],
                "business_context_sha256": state["business_context_sha256"],
                "mobile_component_patterns_sha256": state[
                    "mobile_component_patterns_sha256"
                ],
                "project_catalog_snapshot_sha256": state[
                    "project_catalog_snapshot_sha256"
                ],
                "page_keys": list(require_dict(state.get("pages"), "page states")),
            }
        )
    )


def mark_component_checklist(
    stage_dir: Path,
    state: dict[str, Any],
    node_id: str,
    evidence_sha256: str,
) -> None:
    try:
        complete_checklist_node(
            stage_dir / "checklist.json",
            stage="component-design",
            input_sha256=component_checklist_input(state),
            nodes=component_checklist_specs(stage_dir, state),
            node_id=node_id,
            evidence_sha256=evidence_sha256,
        )
    except ChecklistError as exc:
        raise ContractError(exc.code, exc.message) from exc


def require_component_checklist(
    stage_dir: Path,
    state: dict[str, Any],
    *,
    exclude: tuple[str, ...] = (),
) -> None:
    try:
        require_checklist_complete(
            stage_dir / "checklist.json",
            stage="component-design",
            input_sha256=component_checklist_input(state),
            nodes=component_checklist_specs(stage_dir, state),
            exclude=exclude,
        )
    except ChecklistError as exc:
        raise ContractError(exc.code, exc.message) from exc


def require_component_checklist_node(
    stage_dir: Path, state: dict[str, Any], node_id: str
) -> None:
    try:
        require_checklist_node_ready(
            stage_dir / "checklist.json",
            stage="component-design",
            input_sha256=component_checklist_input(state),
            nodes=component_checklist_specs(stage_dir, state),
            node_id=node_id,
        )
    except ChecklistError as exc:
        raise ContractError(exc.code, exc.message) from exc


def mark_page_api_checklist_if_complete(
    stage_dir: Path,
    state: dict[str, Any],
    page_key: str,
    requirements: list[dict[str, Any]],
) -> None:
    page_state = require_dict(state.get("pages", {}).get(page_key), "page state")
    covered_requirement_ids: list[str] = []
    for artifact_value in require_list(
        page_state.get("api_contract_artifacts"), "page API contract artifacts"
    ):
        artifact = require_dict(artifact_value, "API contract artifact")
        artifact_contract = require_dict(
            read_json(
                stage_dir
                / require_string(artifact.get("path"), "API contract artifact path")
            ),
            "API contract artifact",
        )
        covered_requirement_ids.extend(
            require_string_list(
                artifact_contract.get("requirement_ids"),
                "API contract requirement IDs",
            )
        )
    expected_requirement_ids = [item["requirement_id"] for item in requirements]
    if (
        expected_requirement_ids
        and len(covered_requirement_ids) == len(set(covered_requirement_ids))
        and set(covered_requirement_ids) == set(expected_requirement_ids)
    ):
        mark_component_checklist(
            stage_dir,
            state,
            f"page:{page_key}.api-contracts",
            sha256_bytes(canonical_bytes(sorted(covered_requirement_ids))),
        )


def run_extract_verify(project_root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(EXTRACT_SCRIPT),
            "verify-run",
            "--project-root",
            str(project_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "extract verify-run failed"
        try:
            payload = json.loads(message)
            detail = f"{payload.get('error')}: {payload.get('message')}"
        except json.JSONDecodeError:
            detail = message
        raise ContractError("extract_incomplete", detail)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("extract_incomplete", "extract verify-run returned invalid JSON") from exc
    if result.get("complete") is not True:
        raise ContractError("extract_incomplete", "extract batch is not complete")
    return result


def verified_artifact(stage_dir: Path, descriptor: object, label: str) -> tuple[Path, Any]:
    item = require_dict(descriptor, label)
    relative = require_string(item.get("path"), f"{label}.path")
    expected_sha = require_string(item.get("sha256"), f"{label}.sha256")
    path = stage_dir / relative
    if not path.is_file():
        raise ContractError("extract_drift", f"missing extract artifact: {path}")
    if sha256_bytes(path.read_bytes()) != expected_sha:
        raise ContractError("extract_drift", f"extract artifact hash changed: {path}")
    return path, read_json(path)


def require_project_relative_path(value: object, label: str) -> str:
    path = require_string(value, label)
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ContractError("invalid_path", f"{label} must be project-relative")
    return path


def build_source_catalog(project_root: Path) -> tuple[dict[str, Any], str]:
    run = run_extract_verify(project_root)
    run_result_path = Path(run["run_result"])
    run_result = require_dict(read_json(run_result_path), "extract run-result")
    if run_result.get("schema") != "icp.extract.run-result.v1" or run_result.get("status") != "complete":
        raise ContractError("extract_incomplete", "extract run-result is not complete")
    run_result_sha = sha256_bytes(run_result_path.read_bytes())
    extract_root = project_root / ".icp" / "extract"
    catalog_designs: list[dict[str, Any]] = []
    total_blocks = 0

    for run_design in require_list(run_result.get("designs"), "extract designs"):
        run_design = require_dict(run_design, "extract design")
        design_name = require_string(run_design.get("design_name"), "extract design name")
        design_dir_name = require_string(run_design.get("design_dir"), "extract design dir")
        stage_dir = extract_root / design_dir_name
        result_path = stage_dir / "stage-result.json"
        if not result_path.is_file():
            raise ContractError("extract_drift", f"missing stage result for {design_name}")
        stage_result_sha = sha256_bytes(result_path.read_bytes())
        if stage_result_sha != run_design.get("stage_result_sha256"):
            raise ContractError("extract_drift", f"stage result changed for {design_name}")
        stage_result = require_dict(read_json(result_path), f"{design_name} stage-result")
        if stage_result.get("status") != "complete":
            raise ContractError("extract_incomplete", f"extract is incomplete for {design_name}")
        artifacts = require_dict(stage_result.get("artifacts"), f"{design_name} artifacts")
        manifest_path, manifest = verified_artifact(
            stage_dir, artifacts.get("source_manifest"), f"{design_name} source-manifest"
        )
        facts_path, facts = verified_artifact(
            stage_dir, artifacts.get("source_facts"), f"{design_name} source-facts"
        )
        assets_path, asset_index = verified_artifact(
            stage_dir, artifacts.get("asset_index"), f"{design_name} asset-index"
        )
        semantic_path, semantic = verified_artifact(
            stage_dir, artifacts.get("semantic_draft"), f"{design_name} semantic-draft"
        )
        bindings_path, bindings = verified_artifact(
            stage_dir, artifacts.get("bindings"), f"{design_name} bindings"
        )
        semantic_blocks_path, semantic_blocks = verified_artifact(
            stage_dir,
            artifacts.get("semantic_blocks"),
            f"{design_name} semantic-blocks",
        )

        manifest = require_dict(manifest, f"{design_name} source-manifest")
        facts = require_dict(facts, f"{design_name} source-facts")
        asset_index = require_dict(asset_index, f"{design_name} asset-index")
        semantic = require_dict(semantic, f"{design_name} semantic-draft")
        bindings = require_dict(bindings, f"{design_name} bindings")
        semantic_blocks = require_dict(
            semantic_blocks, f"{design_name} semantic-blocks"
        )
        if semantic_blocks.get("schema") != "icp.extract.semantic-blocks.v1":
            raise ContractError(
                "extract_drift", f"extract design {design_name} has invalid semantic Blocks"
            )
        if (
            semantic_blocks.get("source_facts_sha256")
            != sha256_bytes(facts_path.read_bytes())
            or semantic_blocks.get("asset_index_sha256")
            != sha256_bytes(assets_path.read_bytes())
            or semantic_blocks.get("semantic_draft_sha256")
            != sha256_bytes(semantic_path.read_bytes())
            or semantic_blocks.get("bindings_sha256")
            != sha256_bytes(bindings_path.read_bytes())
        ):
            raise ContractError(
                "extract_drift",
                f"extract design {design_name} semantic Blocks lost source bindings",
            )
        joined_blocks = copy.deepcopy(
            require_list(semantic_blocks.get("blocks"), f"{design_name} Blocks")
        )
        for block in joined_blocks:
            for node in require_list(
                require_dict(block, "semantic Block").get("source_nodes"),
                f"{design_name} Block source nodes",
            ):
                source_node = require_dict(node, "semantic Block source node")
                for asset in require_list(
                    source_node.get("assets"), "semantic Block source assets"
                ):
                    source_asset = require_dict(asset, "semantic Block source asset")
                    source_asset["source_project_path"] = str(
                        Path(".icp")
                        / "extract"
                        / design_dir_name
                        / require_project_relative_path(
                            source_asset.get("local_path"), "source asset path"
                        )
                    )
        non_rendering = copy.deepcopy(
            require_list(
                semantic_blocks.get("non_rendering_source_nodes"),
                f"{design_name} non-rendering source nodes",
            )
        )
        root_block_id = require_string(
            semantic_blocks.get("root_block_id"), f"{design_name} root Block"
        )
        if sum(
            1
            for block_value in joined_blocks
            if require_dict(block_value, "semantic Block").get("block_id")
            == root_block_id
        ) != 1:
            raise ContractError(
                "extract_drift", f"extract design {design_name} must have one semantic root"
            )
        total_blocks += len(joined_blocks)
        source_identity = require_dict(manifest.get("source_identity"), "source identity")
        catalog_designs.append(
            {
                "design_name": design_name,
                "design_dir": design_dir_name,
                "design_url": run_design.get("design_url"),
                "design_id": manifest.get("design_id"),
                "version_id": manifest.get("version_id"),
                "project_id": source_identity.get("project_id", ""),
                "image_id": source_identity.get("image_id", ""),
                "root_block_id": root_block_id,
                "root_node_id": semantic_blocks.get("root_node_id"),
                "visual_reference": {
                    **copy.deepcopy(
                        require_dict(manifest.get("reference"), "visual reference")
                    ),
                    "source_project_path": str(
                        Path(".icp")
                        / "extract"
                        / design_dir_name
                        / require_project_relative_path(
                            require_dict(manifest.get("reference"), "visual reference").get("path"),
                            "visual reference path",
                        )
                    ),
                },
                "semantic_context": copy.deepcopy(
                    require_dict(
                        semantic_blocks.get("semantic_context"),
                        f"{design_name} semantic context",
                    )
                ),
                "stage_result_sha256": stage_result_sha,
                "artifact_sha256": {
                    "source_manifest": sha256_bytes(manifest_path.read_bytes()),
                    "source_facts": sha256_bytes(facts_path.read_bytes()),
                    "asset_index": sha256_bytes(assets_path.read_bytes()),
                    "semantic_draft": sha256_bytes(semantic_path.read_bytes()),
                    "bindings": sha256_bytes(bindings_path.read_bytes()),
                    "semantic_blocks": sha256_bytes(
                        semantic_blocks_path.read_bytes()
                    ),
                },
                "blocks": joined_blocks,
                "non_rendering_source_nodes": non_rendering,
            }
        )

    catalog = {
        "schema": "icp.component-design.source-catalog.v1",
        "extract_run_result_sha256": run_result_sha,
        "extract_run_manifest_sha256": run_result.get("run_manifest_sha256"),
        "design_count": len(catalog_designs),
        "semantic_block_count": total_blocks,
        "designs": catalog_designs,
    }
    return catalog, run_result_sha


def validate_iole_source_closure(
    flow: dict[str, Any],
    members: list[dict[str, Any]],
    relations: list[dict[str, str]],
) -> dict[str, Any]:
    closure = require_dict(flow.get("source_closure"), "IOLE source closure")
    require_exact_keys(
        closure,
        {
            "analysis",
            "analysis_sha256",
            "closure_digest",
            "review",
            "review_sha256",
            "title_catalog",
        },
        "IOLE source closure",
    )
    closure_digest = require_string(
        closure.get("closure_digest"), "IOLE source closure digest"
    )
    expected_closure_digest = sha256_bytes(
        canonical_bytes(
            {key: value for key, value in closure.items() if key != "closure_digest"}
        )
    )
    if closure_digest != expected_closure_digest:
        raise ContractError(
            "invalid_iole_input", "IOLE source closure digest mismatch"
        )

    catalog = require_dict(closure.get("title_catalog"), "IOLE title catalog")
    require_exact_keys(
        catalog,
        {
            "catalog_digest",
            "kind",
            "row_id_column",
            "schema_version",
            "sheet_name",
            "spreadsheet_id",
            "titles",
        },
        "IOLE title catalog",
    )
    if (
        catalog.get("kind") != "icps.flow-title-catalog.v1"
        or catalog.get("schema_version") != 1
        or catalog.get("row_id_column") != "标题"
    ):
        raise ContractError("invalid_iole_input", "IOLE title catalog is invalid")
    catalog_payload = {
        "spreadsheet_id": catalog.get("spreadsheet_id"),
        "sheet_name": catalog.get("sheet_name"),
        "row_id_column": catalog.get("row_id_column"),
        "titles": catalog.get("titles"),
    }
    if catalog.get("catalog_digest") != sha256_bytes(canonical_bytes(catalog_payload)):
        raise ContractError(
            "invalid_iole_input", "IOLE title catalog digest mismatch"
        )
    catalog_titles = require_string_list(catalog.get("titles"), "IOLE catalog titles")
    if len(catalog_titles) != len(set(catalog_titles)):
        raise ContractError("invalid_iole_input", "IOLE title catalog has duplicates")
    expected_source_id = "google-sheets:" + sha256_bytes(
        canonical_bytes(
            {
                "sheet_name": catalog.get("sheet_name"),
                "spreadsheet_id": catalog.get("spreadsheet_id"),
            }
        )
    )
    if flow.get("source_id") != expected_source_id:
        raise ContractError(
            "invalid_iole_input", "IOLE source closure identity mismatch"
        )

    analysis = require_dict(closure.get("analysis"), "IOLE source analysis")
    require_exact_keys(
        analysis,
        {"kind", "root_title", "role", "rows", "schema_version", "source_id"},
        "IOLE source analysis",
    )
    analysis_sha = sha256_bytes(canonical_bytes(analysis))
    if (
        analysis.get("kind") != "iole.source-analysis-input.v2"
        or analysis.get("schema_version") != 2
        or analysis.get("source_id") != flow.get("source_id")
        or analysis.get("role") != flow.get("role")
        or analysis.get("root_title") != flow.get("root_title")
        or closure.get("analysis_sha256") != analysis_sha
    ):
        raise ContractError("invalid_iole_input", "IOLE source analysis is stale")

    members_by_title = {
        require_string(member.get("title"), "IOLE member title"): member
        for member in members
    }
    analysis_rows = require_list(analysis.get("rows"), "IOLE source analysis rows")
    analyzed_titles: set[str] = set()
    field_projection: list[tuple[str, str, str]] = []
    relation_projection: list[dict[str, str]] = []
    reference_ids: set[str] = set()
    for row_index, row_value in enumerate(analysis_rows):
        label = f"IOLE source analysis rows[{row_index}]"
        row = require_dict(row_value, label)
        require_exact_keys(row, {"change_scope", "fields", "title"}, label)
        title = require_string(row.get("title"), f"{label}.title")
        if title in analyzed_titles or title not in members_by_title:
            raise ContractError(
                "invalid_iole_input", f"IOLE source analysis member mismatch: {title}"
            )
        analyzed_titles.add(title)
        member = members_by_title[title]
        if row.get("change_scope") != member.get("change_scope"):
            raise ContractError(
                "invalid_iole_input", f"IOLE source analysis scope mismatch: {title}"
            )
        row_data = require_dict(member.get("row_data"), f"row_data for {title}")
        seen_columns: set[str] = set()
        analyzed_columns: list[str] = []
        for field_index, field_value in enumerate(
            require_list(row.get("fields"), f"{label}.fields")
        ):
            field_label = f"{label}.fields[{field_index}]"
            field = require_dict(field_value, field_label)
            require_exact_keys(
                field,
                {"column", "dismissals", "references", "source_sha256"},
                field_label,
            )
            column = require_string(field.get("column"), f"{field_label}.column")
            if column in seen_columns:
                raise ContractError(
                    "invalid_iole_input",
                    f"IOLE source analysis column mismatch: {title}/{column}; "
                    f"duplicates=['{column}']",
                )
            if column not in row_data:
                raise ContractError(
                    "invalid_iole_input",
                    f"IOLE source analysis column mismatch: {title}/{column}; "
                    f"unexpected=['{column}']",
                )
            seen_columns.add(column)
            analyzed_columns.append(column)
            raw_value = row_data[column]
            if raw_value is not None and not isinstance(raw_value, str):
                raise ContractError("invalid_iole_input", "IOLE row_data value is invalid")
            source_text = raw_value or ""
            source_sha = sha256_bytes(source_text.encode("utf-8"))
            if field.get("source_sha256") != source_sha:
                raise ContractError(
                    "invalid_iole_input", f"IOLE source analysis field hash mismatch: {title}/{column}"
                )
            field_projection.append((title, column, source_sha))
            for reference_value in require_list(
                field.get("references"), f"{field_label}.references"
            ):
                reference = require_dict(reference_value, "IOLE source reference")
                require_exact_keys(
                    reference,
                    {
                        "end",
                        "quote",
                        "reference_id",
                        "relation_kind",
                        "start",
                        "target_title",
                    },
                    "IOLE source reference",
                )
                reference_id = require_string(
                    reference.get("reference_id"), "IOLE source reference id"
                )
                start = reference.get("start")
                end = reference.get("end")
                quote = reference.get("quote")
                target = reference.get("target_title")
                if (
                    reference_id in reference_ids
                    or type(start) is not int
                    or type(end) is not int
                    or start < 0
                    or end <= start
                    or end > len(source_text)
                    or not isinstance(quote, str)
                    or source_text[start:end] != quote
                    or not isinstance(target, str)
                    or target not in members_by_title
                    or target not in catalog_titles
                    or reference.get("relation_kind")
                    not in {"navigation", "modal", "component", "data", "reference"}
                ):
                    raise ContractError(
                        "invalid_iole_input", "IOLE source reference evidence is invalid"
                    )
                reference_ids.add(reference_id)
                projected = {"from_title": title, "to_title": target}
                if projected not in relation_projection:
                    relation_projection.append(projected)
            for dismissal_value in require_list(
                field.get("dismissals"), f"{field_label}.dismissals"
            ):
                dismissal = require_dict(dismissal_value, "IOLE source dismissal")
                require_exact_keys(
                    dismissal,
                    {"candidate_title", "end", "quote", "rationale", "start"},
                    "IOLE source dismissal",
                )
                start = dismissal.get("start")
                end = dismissal.get("end")
                quote = dismissal.get("quote")
                if (
                    type(start) is not int
                    or type(end) is not int
                    or start < 0
                    or end <= start
                    or end > len(source_text)
                    or not isinstance(quote, str)
                    or source_text[start:end] != quote
                    or dismissal.get("candidate_title") not in catalog_titles
                    or not isinstance(dismissal.get("rationale"), str)
                    or not str(dismissal["rationale"]).strip()
                ):
                    raise ContractError(
                        "invalid_iole_input", "IOLE source dismissal evidence is invalid"
                    )
        expected_columns = [
            column
            for column in row_data
            if column != catalog.get("row_id_column")
        ]
        # Analyzed columns are an identity set: field order inside one row is
        # incidental storage order, not a coverage contract.
        missing_columns = sorted(set(expected_columns) - set(analyzed_columns))
        unexpected_columns = sorted(set(analyzed_columns) - set(expected_columns))
        if missing_columns or unexpected_columns:
            raise ContractError(
                "invalid_iole_input",
                f"IOLE source analysis does not cover every declared source column: {title}; "
                f"missing={missing_columns} unexpected={unexpected_columns}",
            )
    if analyzed_titles != set(members_by_title):
        raise ContractError(
            "invalid_iole_input", "IOLE source closure does not cover every member"
        )
    # Relations are graph topology: unique (from_title, to_title) edges are
    # compared as a set, then normalized by stable edge identity. Neither the
    # flow list nor the analysis/reference traversal order is a contract.
    projection_edges = {
        (item["from_title"], item["to_title"]) for item in relation_projection
    }
    flow_edges = {
        (item["from_title"], item["to_title"]) for item in relations
    }
    missing_edges = sorted(projection_edges - flow_edges)
    unexpected_edges = sorted(flow_edges - projection_edges)
    if missing_edges or unexpected_edges:
        raise ContractError(
            "invalid_iole_input",
            "IOLE source closure relation projection mismatch; "
            f"missing={missing_edges} unexpected={unexpected_edges}",
        )
    relations[:] = [
        {"from_title": from_title, "to_title": to_title}
        for from_title, to_title in sorted(projection_edges)
    ]

    review = require_dict(closure.get("review"), "IOLE source closure review")
    review_sha = sha256_bytes(canonical_bytes(review))
    if closure.get("review_sha256") != review_sha:
        raise ContractError(
            "invalid_iole_input", "IOLE source closure review digest mismatch"
        )
    require_exact_keys(
        review,
        {
            "analysis_sha256",
            "cross_review",
            "decision",
            "field_reviews",
            "kind",
            "schema_version",
            "title_catalog_digest",
        },
        "IOLE source closure review",
    )
    if (
        review.get("kind") != "iole.source-closure-review.v1"
        or review.get("schema_version") != 1
        or review.get("analysis_sha256") != analysis_sha
        or review.get("title_catalog_digest") != catalog.get("catalog_digest")
        or review.get("decision") != "pass"
    ):
        raise ContractError("invalid_iole_input", "IOLE source closure review did not pass")
    review_projection: list[tuple[str, str, str]] = []
    for review_value in require_list(
        review.get("field_reviews"), "IOLE source field reviews"
    ):
        field_review = require_dict(review_value, "IOLE source field review")
        require_exact_keys(
            field_review,
            {
                "all_dependencies_identified",
                "column",
                "dismissals_correct",
                "evidence",
                "issues",
                "reference_targets_correct",
                "source_sha256",
                "title",
            },
            "IOLE source field review",
        )
        if (
            field_review.get("all_dependencies_identified") is not True
            or field_review.get("reference_targets_correct") is not True
            or field_review.get("dismissals_correct") is not True
            or require_list(field_review.get("issues"), "IOLE source field review issues")
            or not require_string_list(
                field_review.get("evidence"), "IOLE source field review evidence"
            )
        ):
            raise ContractError("invalid_iole_input", "IOLE source field review failed")
        review_projection.append(
            (
                require_string(field_review.get("title"), "review title"),
                require_string(field_review.get("column"), "review column"),
                require_string(field_review.get("source_sha256"), "review source hash"),
            )
        )
    # Field-review coverage is an identity set over (title, column,
    # source_sha256): review order is incidental and stays frozen verbatim.
    review_identities = set(review_projection)
    if (
        len(review_projection) != len(review_identities)
        or review_identities != set(field_projection)
    ):
        missing_reviews = sorted(set(field_projection) - review_identities)
        unexpected_reviews = sorted(review_identities - set(field_projection))
        duplicate_reviews = sorted(
            {
                item
                for item in review_projection
                if review_projection.count(item) > 1
            }
        )
        raise ContractError(
            "invalid_iole_input",
            "IOLE source field review projection mismatch; "
            f"missing={missing_reviews} unexpected={unexpected_reviews} "
            f"duplicates={duplicate_reviews}",
        )
    cross_review = require_dict(review.get("cross_review"), "IOLE cross review")
    require_exact_keys(
        cross_review,
        {
            "every_business_field_reviewed",
            "evidence",
            "issues",
            "no_ambiguous_target",
            "no_unresolved_reference",
        },
        "IOLE cross review",
    )
    if (
        cross_review.get("every_business_field_reviewed") is not True
        or cross_review.get("no_unresolved_reference") is not True
        or cross_review.get("no_ambiguous_target") is not True
        or require_list(cross_review.get("issues"), "IOLE cross review issues")
        or not require_string_list(
            cross_review.get("evidence"), "IOLE cross review evidence"
        )
    ):
        raise ContractError("invalid_iole_input", "IOLE source cross review failed")
    return copy.deepcopy(closure)


def build_business_context(
    flow_value: object, catalog: dict[str, Any]
) -> dict[str, Any]:
    flow = require_dict(flow_value, "IOLE flow input")
    source_version = (flow.get("kind"), flow.get("schema_version"))
    if source_version != ("iole.flow-source-bundle.v2", 2):
        raise ContractError(
            "invalid_iole_input",
            "component design requires iole.flow-source-bundle.v2",
        )
    if flow.get("role") != "client":
        raise ContractError("invalid_iole_input", "component design requires role=client")
    source_id = require_string(flow.get("source_id"), "IOLE source_id")
    root_title = require_string(flow.get("root_title"), "IOLE root_title")
    row_data_columns = require_string_list(
        flow.get("row_data_columns"), "IOLE row_data_columns"
    )
    if not row_data_columns or len(row_data_columns) != len(set(row_data_columns)):
        raise ContractError(
            "invalid_iole_input", "IOLE row_data_columns must be unique and non-empty"
        )
    mapping_digest = require_string(flow.get("mapping_digest"), "IOLE mapping_digest")
    if not re.fullmatch(r"[0-9a-f]{64}", mapping_digest):
        raise ContractError("invalid_iole_input", "IOLE mapping_digest must be lowercase SHA-256")
    bundle_digest = require_string(flow.get("bundle_digest"), "IOLE bundle_digest")
    expected_bundle_digest = hashlib.sha256(
        canonical_bytes(
            {key: value for key, value in flow.items() if key != "bundle_digest"}
        )
    ).hexdigest()
    if bundle_digest != expected_bundle_digest:
        raise ContractError("invalid_iole_input", "IOLE source bundle digest mismatch")

    catalog_designs = {
        require_string(design.get("design_url"), "catalog design URL"): design
        for design_value in require_list(catalog.get("designs"), "catalog designs")
        for design in [require_dict(design_value, "catalog design")]
    }
    matched_designs: dict[str, str] = {}
    titles: set[str] = set()
    members: list[dict[str, Any]] = []
    for index, row_value in enumerate(
        require_list(flow.get("members"), "IOLE members")
    ):
        label = f"IOLE rows[{index}]"
        row = require_dict(row_value, label)
        title = require_string(row.get("title"), f"{label}.title")
        if title in titles:
            raise ContractError("invalid_iole_input", f"duplicate IOLE title: {title}")
        titles.add(title)
        change_scope = row.get("change_scope")
        allowed_scopes = {"modify", "context", "navigate-only"}
        if change_scope not in allowed_scopes:
            raise ContractError("invalid_iole_input", f"invalid change_scope for {title}")
        row_data = require_dict(row.get("row_data"), f"{label}.row_data")
        missing_columns = sorted(set(row_data_columns) - set(row_data))
        unexpected_columns = sorted(set(row_data) - set(row_data_columns))
        if missing_columns or unexpected_columns:
            raise ContractError(
                "invalid_iole_input",
                f"row_data must match declared source columns for {title}; "
                f"missing={missing_columns} unexpected={unexpected_columns}",
            )
        # JSON object key insertion order is not a contract: read row_data in
        # the authoritative row_data_columns order for deterministic storage.
        row_data = {column: row_data[column] for column in row_data_columns}
        for column, value in row_data.items():
            if not isinstance(column, str) or not column:
                raise ContractError(
                    "invalid_iole_input", f"invalid row_data column for {title}"
                )
            if value is not None and (
                not isinstance(value, str) or value == ""
            ):
                raise ContractError(
                    "invalid_iole_input",
                    f"row_data values must be complete strings or null for {title}",
                )
        source_contract = require_dict(row.get("source_contract"), f"{label}.source_contract")
        if (
            source_contract.get("kind") != "iole.sheet-member-contract.v2"
            or source_contract.get("schema_version") != 2
        ):
            raise ContractError(
                "invalid_iole_input", f"invalid source contract for {title}"
            )
        source_route = require_nullable_text(
            source_contract.get("route"), f"{label}.source_contract.route"
        )
        source_design_ref = require_nullable_text(
            source_contract.get("design_ref"), f"{label}.source_contract.design_ref"
        )
        source_interaction = require_nullable_text(
            source_contract.get("interaction"), f"{label}.source_contract.interaction"
        )
        route = source_route or ""
        design_ref = source_design_ref or ""
        raw_interaction = source_interaction or ""
        if source_contract.get("title") != title:
            raise ContractError(
                "invalid_iole_input", f"row and lossless source contract disagree for {title}"
            )
        projected_values = [
            source_contract.get("title"),
            source_route,
            source_design_ref,
            source_interaction,
        ]
        contract_digest = require_string(
            source_contract.get("contract_digest"), f"{label}.source_contract.contract_digest"
        )
        if not re.fullmatch(r"[0-9a-f]{64}", contract_digest):
            raise ContractError(
                "invalid_iole_input", f"invalid source contract digest for {title}"
            )
        expected_contract_digest = hashlib.sha256(
            canonical_bytes(
                {
                    key: value
                    for key, value in source_contract.items()
                    if key != "contract_digest"
                }
            )
        ).hexdigest()
        if contract_digest != expected_contract_digest:
            raise ContractError(
                "invalid_iole_input",
                f"source contract digest mismatch for {title}",
            )

        clauses: list[dict[str, str]] = [
            {
                "clause_id": "page:title",
                "kind": "page",
                "label": "标题",
                "text": title,
            },
            {
                "clause_id": "page:route",
                "kind": "page",
                "label": "页面路由",
                "text": route,
            },
            {
                "clause_id": "page:interaction",
                "kind": "interaction",
                "label": "交互描述",
                "text": raw_interaction,
            },
        ]
        requirement_sections = require_list(
            source_contract.get("requirement_sections"),
            f"{label}.source_contract.requirement_sections",
        )
        for section_index, section_value in enumerate(requirement_sections):
            section = require_dict(section_value, "requirement section")
            section_text = require_nullable_text(
                section.get("value"), "requirement value"
            )
            projected_values.append(section_text)
            clauses.append(
                {
                    "clause_id": f"requirement:{section_index}",
                    "kind": "requirement",
                    "label": require_string(section.get("label"), "requirement label"),
                    "text": section_text or "",
                }
            )
        ui_supplements = [
            require_nullable_text(section.get("value"), "UI supplement")
            for section in requirement_sections
            if section.get("label") == "UI补充描述"
        ]
        if len(ui_supplements) > 1:
            raise ContractError(
                "invalid_iole_input", f"member {title} declares UI补充描述 more than once"
            )
        ui_supplement = ui_supplements[0] if ui_supplements else None
        acceptance_sections = require_list(
            source_contract.get("acceptance_sections"),
            f"{label}.source_contract.acceptance_sections",
        )
        for section_index, section_value in enumerate(acceptance_sections):
            section = require_dict(section_value, "acceptance section")
            section_text = require_nullable_text(
                section.get("value"), "acceptance value"
            )
            projected_values.append(section_text)
            clauses.append(
                {
                    "clause_id": f"acceptance:{section_index}",
                    "kind": "acceptance",
                    "label": require_string(section.get("prefix"), "acceptance prefix"),
                    "text": section_text or "",
                }
            )
        row_values = list(row_data.values())
        if any(value is not None and value not in row_values for value in projected_values):
            raise ContractError(
                "invalid_iole_input",
                f"source contract contains data outside declared row_data for {title}",
            )

        design_refs: list[dict[str, Any]] = []
        seen_ordinals: set[int] = set()
        seen_urls: set[str] = set()
        for ref_index, ref_value in enumerate(
            require_list(row.get("design_refs"), f"{label}.design_refs")
        ):
            ref = require_dict(ref_value, f"{label}.design_refs[{ref_index}]")
            if set(ref) != {"label", "ordinal", "url"}:
                raise ContractError(
                    "invalid_iole_input", f"invalid design state for {title}"
                )
            ordinal = ref.get("ordinal")
            state_label = require_text(ref.get("label"), "design state label")
            url = require_string(ref.get("url"), "design state URL")
            if (
                type(ordinal) is not int
                or ordinal != ref_index + 1
                or ordinal in seen_ordinals
                or url in seen_urls
            ):
                raise ContractError(
                    "invalid_iole_input", f"invalid design state order for {title}"
                )
            seen_ordinals.add(ordinal)
            seen_urls.add(url)
            design_refs.append({"ordinal": ordinal, "label": state_label, "url": url})

        design_states: list[dict[str, Any]] = []
        for ref in design_refs:
            catalog_design = catalog_designs.get(ref["url"])
            if catalog_design is None:
                raise ContractError(
                    "iole_extract_mismatch",
                    f"member {title} has no verified extract for {ref['url']}",
                )
            design_name = require_string(
                catalog_design.get("design_name"), "catalog design name"
            )
            semantic_context = require_dict(
                catalog_design.get("semantic_context"),
                f"catalog semantic context for {design_name}",
            )
            if (
                semantic_context.get("design_url") != ref["url"]
                or semantic_context.get("ui_supplement") != ui_supplement
            ):
                raise ContractError(
                    "iole_extract_mismatch",
                    f"member {title} UI补充描述 was not used by extract {design_name}",
                )
            if design_name in matched_designs:
                raise ContractError(
                    "iole_extract_mismatch", f"multiple IOLE members map to {design_name}"
                )
            matched_designs[design_name] = title
            design_states.append({**ref, "design_name": design_name})
        if change_scope == "modify" and not design_states:
            raise ContractError(
                "iole_extract_mismatch", f"modify member {title} has no verified design state"
            )

        normalized_interaction = require_text(
            row.get("normalized_interaction"),
            f"{label}.normalized_interaction",
        )
        requirement = "\n".join(
            f"{section['label']}: {section['value']}"
            for section in requirement_sections
            if isinstance(section.get("value"), str)
            and str(section["value"]).strip()
        )
        acceptance_criteria = [
            f"{section['prefix']}: {section['value']}"
            for section in acceptance_sections
            if isinstance(section.get("value"), str)
            and str(section["value"]).strip()
        ]
        members.append(
            {
                "design_name": (
                    design_states[0]["design_name"] if len(design_states) == 1 else None
                ),
                "design_states": design_states,
                "title": title,
                "route": route,
                "design_ref": design_ref,
                "change_scope": change_scope,
                "normalized_interaction": normalized_interaction,
                "requirement": requirement,
                "acceptance_criteria": acceptance_criteria,
                "allowed_paths": [],
                "row_data": copy.deepcopy(row_data),
                "source_contract": copy.deepcopy(source_contract),
                "clauses": clauses,
            }
        )

    expected_design_names = {
        require_string(design.get("design_name"), "catalog design name")
        for design in catalog_designs.values()
    }
    if set(matched_designs) != expected_design_names:
        raise ContractError(
            "iole_extract_mismatch",
            f"IOLE modify members must match every extract design; missing={sorted(expected_design_names - set(matched_designs))}",
        )
    if root_title not in titles:
        raise ContractError("invalid_iole_input", "IOLE root_title is not a member")
    relations: list[dict[str, str]] = []
    relation_pairs: set[tuple[str, str]] = set()
    children: dict[str, list[str]] = {title: [] for title in titles}
    for index, relation_value in enumerate(
        require_list(flow.get("relations"), "IOLE relations")
    ):
        label = f"IOLE relations[{index}]"
        relation = require_dict(relation_value, label)
        require_exact_keys(relation, {"from_title", "to_title"}, label)
        from_title = require_string(relation.get("from_title"), f"{label}.from_title")
        to_title = require_string(relation.get("to_title"), f"{label}.to_title")
        if from_title not in titles or to_title not in titles:
            raise ContractError(
                "invalid_iole_input", f"relation endpoint is not a member: {label}"
            )
        pair = (from_title, to_title)
        if pair in relation_pairs:
            raise ContractError("invalid_iole_input", f"duplicate relation: {label}")
        relation_pairs.add(pair)
        children[from_title].append(to_title)
        relations.append({"from_title": from_title, "to_title": to_title})
    reachable: set[str] = set()
    pending = [root_title]
    while pending:
        title = pending.pop()
        if title in reachable:
            continue
        reachable.add(title)
        pending.extend(children[title])
    if reachable != titles:
        raise ContractError(
            "invalid_iole_input",
            f"IOLE relations do not reach members: {sorted(titles - reachable)}",
        )
    source_closure = validate_iole_source_closure(flow, members, relations)
    result = {
        "schema": "icp.component-design.business-context.v1",
        "source_authority": copy.deepcopy(SOURCE_AUTHORITY),
        "source_kind": str(flow["kind"]),
        "source_id": source_id,
        "root_title": root_title,
        "bundle_digest": bundle_digest,
        "mapping_digest": mapping_digest,
        "source_closure": source_closure,
        "members": members,
        "relations": relations,
    }
    return result


def stage_dir_for(project_root: Path) -> Path:
    return project_root / ".icp" / "component-design"


def load_state(project_root: Path) -> tuple[Path, dict[str, Any]]:
    stage_dir = stage_dir_for(project_root)
    state = require_dict(read_json(stage_dir / "state.json"), "component-design state")
    if state.get("schema") != "icp.component-design.state.v2":
        raise ContractError("invalid_state", "component-design state schema is invalid")
    return stage_dir, state


def verify_live_catalog(
    project_root: Path, stage_dir: Path, state: dict[str, Any]
) -> dict[str, Any]:
    catalog_path = stage_dir / "source-catalog.json"
    if not catalog_path.is_file():
        raise ContractError("stage_drift", "source-catalog.json is missing")
    actual_sha = sha256_bytes(catalog_path.read_bytes())
    if actual_sha != state.get("source_catalog_sha256"):
        raise ContractError("stage_drift", "source catalog hash changed")
    actual_catalog = require_dict(read_json(catalog_path), "source catalog")
    expected_catalog, run_sha = build_source_catalog(project_root)
    if run_sha != state.get("extract_run_result_sha256"):
        raise ContractError("extract_drift", "extract run-result changed")
    if actual_catalog != expected_catalog:
        raise ContractError("extract_drift", "source catalog no longer matches live extract")
    return actual_catalog


def verify_live_business_context(
    stage_dir: Path, state: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    flow_path = stage_dir.parent / "source" / "source-bundle.json"
    context_path = stage_dir / "business-context.json"
    if (
        not flow_path.is_file()
        or sha256_bytes(flow_path.read_bytes()) != state.get("iole_source_bundle_sha256")
    ):
        raise ContractError("stage_drift", "frozen IOLE flow input changed")
    if (
        not context_path.is_file()
        or sha256_bytes(context_path.read_bytes()) != state.get("business_context_sha256")
    ):
        raise ContractError("stage_drift", "business context hash changed")
    actual = require_dict(read_json(context_path), "business context")
    expected = build_business_context(read_json(flow_path), catalog)
    if actual != expected:
        raise ContractError("stage_drift", "business context no longer matches IOLE input")
    return actual


def page_key_for(member_title: str) -> str:
    return "page-" + sha256_bytes(member_title.encode("utf-8"))[:16]


def member_has_design_states(member: dict[str, Any]) -> bool:
    return bool(require_list(member.get("design_states"), "design states"))


def member_requires_semantic_work_item(member: dict[str, Any]) -> bool:
    if member_has_design_states(member):
        return True
    for clause_value in require_list(member.get("clauses"), "business clauses"):
        clause = require_dict(clause_value, "business clause")
        if (
            clause.get("kind") in {"interaction", "requirement", "acceptance"}
            and require_text(clause.get("text"), "business clause text").strip()
        ):
            return True
    return False


def build_source_context(business_context: dict[str, Any]) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    page_keys: set[str] = set()
    for index, member_value in enumerate(
        require_list(business_context.get("members"), "business context members")
    ):
        label = f"business context members[{index}]"
        member = require_dict(member_value, label)
        title = require_string(member.get("title"), f"{label}.title")
        design_names = [
            require_string(state.get("design_name"), f"{label}.design state name")
            for state_value in require_list(member.get("design_states"), f"{label}.design states")
            for state in [require_dict(state_value, f"{label}.design state")]
        ]
        page_key = page_key_for(title) if member_requires_semantic_work_item(member) else None
        if page_key is not None:
            if page_key in page_keys:
                raise ContractError(
                    "page_identity_collision", f"multiple members map to {page_key}"
                )
            page_keys.add(page_key)
        source_contract = require_dict(
            member.get("source_contract"), f"{label}.source_contract"
        )
        members.append(
            {
                "title": title,
                "page_key": page_key,
                "change_scope": member.get("change_scope"),
                "route": member.get("route"),
                "design_names": design_names,
                "contract_digest": require_string(
                    source_contract.get("contract_digest"),
                    f"{label}.source_contract.contract_digest",
                ),
            }
        )
    return {
        "source_kind": require_string(
            business_context.get("source_kind"), "business context source_kind"
        ),
        "source_id": require_string(
            business_context.get("source_id"), "business context source_id"
        ),
        "root_title": require_string(
            business_context.get("root_title"), "business context root_title"
        ),
        "members": members,
        "relations": copy.deepcopy(
            require_list(business_context.get("relations"), "business context relations")
        ),
    }


def validate_source_context_joins(
    source_context: dict[str, Any],
    pages: list[dict[str, Any]],
    component_instances: list[dict[str, Any]],
    page_compositions: list[dict[str, Any]],
) -> None:
    members_by_page_key = {
        member["page_key"]: member
        for member_value in require_list(source_context.get("members"), "source context members")
        for member in [require_dict(member_value, "source context member")]
        if member.get("page_key") is not None
    }
    pages_by_key = {
        require_string(page.get("page_key"), "locked page key"): page
        for page_value in pages
        for page in [require_dict(page_value, "locked page")]
    }
    if len(pages_by_key) != len(pages) or set(pages_by_key) != set(members_by_page_key):
        raise ContractError(
            "source_context_join_mismatch",
            "source context and locked pages do not have the same page keys",
        )
    for page_key, member in members_by_page_key.items():
        page = pages_by_key[page_key]
        if (
            page.get("member_title") != member.get("title")
            or page.get("design_names") != member.get("design_names")
        ):
            raise ContractError(
                "source_context_join_mismatch",
                f"source context disagrees with locked page {page_key}",
            )
    for label, values in (
        ("component instance", component_instances),
        ("page composition", page_compositions),
    ):
        for index, value in enumerate(values):
            item = require_dict(value, f"{label}[{index}]")
            page_key = require_string(item.get("page_key"), f"{label}[{index}].page_key")
            member = members_by_page_key.get(page_key)
            if member is None or item.get("member_title") != member.get("title"):
                raise ContractError(
                    "source_context_join_mismatch",
                    f"{label} does not join source context: {page_key}",
                )
            if label == "page composition" and item.get("design_name") not in member.get(
                "design_names", []
            ):
                raise ContractError(
                    "source_context_join_mismatch",
                    f"page composition design does not join source context: {page_key}",
                )


def build_relation_requirements(
    member: dict[str, Any],
    business_context: dict[str, Any],
    *,
    relation_kinds: set[str],
    id_prefix: str,
    id_field: str,
    require_target_designs: bool = False,
) -> list[dict[str, Any]]:
    member_title = require_string(member.get("title"), "business member title")
    members_by_title = {
        require_string(item.get("title"), "business member title"): item
        for item_value in require_list(
            business_context.get("members"), "business context members"
        )
        for item in [require_dict(item_value, "business context member")]
    }
    clauses_by_label: dict[str, list[dict[str, Any]]] = {}
    for clause_value in require_list(member.get("clauses"), "business clauses"):
        clause = require_dict(clause_value, "business clause")
        clauses_by_label.setdefault(
            require_string(clause.get("label"), "business clause label"), []
        ).append(clause)
    analysis = require_dict(
        require_dict(
            business_context.get("source_closure"), "business source closure"
        ).get("analysis"),
        "business source analysis",
    )
    row = next(
        (
            require_dict(value, "business source analysis row")
            for value in require_list(analysis.get("rows"), "business source rows")
            if require_dict(value, "business source analysis row").get("title")
            == member_title
        ),
        None,
    )
    if row is None:
        raise ContractError(
            "invalid_business_context", f"source analysis is missing {member_title}"
        )
    requirements: list[dict[str, Any]] = []
    for field_value in require_list(row.get("fields"), "business source fields"):
        field = require_dict(field_value, "business source field")
        column = require_string(field.get("column"), "business source column")
        for reference_value in require_list(
            field.get("references"), "business source references"
        ):
            reference = require_dict(reference_value, "business source reference")
            relation_kind = reference.get("relation_kind")
            if relation_kind not in relation_kinds:
                continue
            matching_clauses = [
                clause
                for clause in clauses_by_label.get(column, [])
                if clause.get("text") is not None
                and sha256_bytes(
                    require_text(clause.get("text"), "business clause text").encode(
                        "utf-8"
                    )
                )
                == field.get("source_sha256")
            ]
            matching_clauses.sort(
                key=lambda clause: (
                    clause.get("clause_id") != "page:interaction",
                    require_string(clause.get("clause_id"), "business clause_id"),
                )
            )
            if not matching_clauses:
                raise ContractError(
                    "presentation_source_unmapped",
                    f"{member_title}/{column} presentation reference has no source clause",
                )
            clause = matching_clauses[0]
            target_title = require_string(
                reference.get("target_title"), "presentation target title"
            )
            target_member = members_by_title.get(target_title)
            if (
                target_member is None
                or not member_requires_semantic_work_item(target_member)
                or (
                    require_target_designs
                    and not member_has_design_states(target_member)
                )
            ):
                if require_target_designs and target_member is not None and member_requires_semantic_work_item(target_member):
                    # A navigation transition must land on a frozen visual
                    # state; designless context rows are not runtime targets.
                    continue
                raise ContractError(
                    "presentation_target_unmapped",
                    f"presentation target has no component work item: {target_title}",
                )
            evidence = {
                "reference_id": require_string(
                    reference.get("reference_id"), "presentation reference_id"
                ),
                "relation_kind": relation_kind,
                "source_column": column,
                "source_ref": {
                    "member_title": member_title,
                    "clause_id": clause["clause_id"],
                    "source_sha256": field["source_sha256"],
                    "start": reference["start"],
                    "end": reference["end"],
                    "quote": reference["quote"],
                },
                "target_member_title": target_title,
                "target_page_key": page_key_for(target_title),
            }
            requirements.append(
                {
                    id_field: id_prefix + "-" + sha256_bytes(canonical_bytes(evidence))[:20],
                    **evidence,
                }
            )
    return requirements


def build_presentation_requirements(
    member: dict[str, Any], business_context: dict[str, Any]
) -> list[dict[str, Any]]:
    return build_relation_requirements(
        member,
        business_context,
        relation_kinds={"modal", "component"},
        id_prefix="presentation",
        id_field="presentation_requirement_id",
    )


def build_navigation_requirements(
    member: dict[str, Any], business_context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Preserve exact IOLE navigation evidence as closed page input."""

    return build_relation_requirements(
        member,
        business_context,
        relation_kinds={"navigation"},
        id_prefix="navigation",
        id_field="navigation_requirement_id",
        require_target_designs=True,
    )


def build_page_facts_template(
    member: dict[str, Any],
    business_context: dict[str, Any],
    source_catalog_sha: str,
    business_context_sha: str,
    mobile_component_pattern_context: dict[str, str],
) -> dict[str, Any]:
    member_title = require_string(member.get("title"), "business member title")
    page_key = page_key_for(member_title)
    source_coverage: list[dict[str, Any]] = []
    interaction_text: str | None = None
    for clause_value in require_list(member.get("clauses"), "business clauses"):
        clause = require_dict(clause_value, "business clause")
        clause_id = require_string(clause.get("clause_id"), "business clause_id")
        source_text = require_text(clause.get("text"), "business clause text")
        if clause_id == "page:interaction":
            interaction_text = source_text
        source_coverage.append(
            {
                "clause_id": clause_id,
                "source_sha256": sha256_bytes(source_text.encode("utf-8")),
                "source_text": source_text,
                "segments": [],
            }
        )
    if interaction_text is None:
        raise ContractError(
            "invalid_business_context", "page interaction clause is missing"
        )
    interaction_items = []
    if interaction_text == "":
        interaction_items.append(
            {
                "item_id": f"{page_key}-interaction-null",
                "source_ref": None,
                "condition": None,
                "state": None,
                "trigger": None,
                "behavior": None,
                "result": None,
            }
        )
    return {
        "schema": "icp.component-design.page-facts.v4",
        "page_key": page_key,
        "member_title": member_title,
        "source_catalog_sha256": source_catalog_sha,
        "business_context_sha256": business_context_sha,
        "mobile_component_pattern_context": copy.deepcopy(
            mobile_component_pattern_context
        ),
        "design_names": [
            require_string(state.get("design_name"), "design state name")
            for state in require_list(member.get("design_states"), "design states")
        ],
        "source_coverage": source_coverage,
        "presentation_requirements": build_presentation_requirements(
            member, business_context
        ),
        "navigation_requirements": build_navigation_requirements(
            member, business_context
        ),
        "api_requirements": build_api_requirements(member),
        "api_contracts": [],
        "interaction_items": interaction_items,
        "interaction_graph": {
            "schema": "icp.component-design.interaction-graph.v2",
            "interactions": [],
            "edges": [],
            "terminal_outcomes": [],
        },
        "candidates": [],
        "design_compositions": [],
    }


def page_work_items(stage_dir: Path, context: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for member_value in require_list(context.get("members"), "business context members"):
        member = require_dict(member_value, "business context member")
        if not member_requires_semantic_work_item(member):
            continue
        member_title = require_string(member.get("title"), "business member title")
        page_key = page_key_for(member_title)
        result.append(
            {
                "page_key": page_key,
                "member_title": member_title,
                "input_path": str(stage_dir / "page-component-facts" / f"{page_key}.input.json"),
            }
        )
    return result


def build_api_requirements(member: dict[str, Any]) -> list[dict[str, Any]]:
    """Project exact same-page interface sources before model resolution."""

    member_title = require_string(member.get("title"), "business member title")
    requirements: list[dict[str, Any]] = []
    for clause_value in require_list(member.get("clauses"), "business clauses"):
        clause = require_dict(clause_value, "business clause")
        clause_id = require_string(clause.get("clause_id"), "business clause_id")
        label = require_string(clause.get("label"), "business clause label")
        text = require_text(clause.get("text"), "business clause text")
        source_sha = sha256_bytes(text.encode("utf-8"))
        if label == "接口描述" and text.strip():
            evidence = {
                "source_kind": "interface_description",
                "source_ref": {
                    "member_title": member_title,
                    "clause_id": clause_id,
                    "source_sha256": source_sha,
                    "start": 0,
                    "end": len(text),
                    "quote": text,
                },
                "locator": None,
            }
            requirements.append(
                {
                    "requirement_id": "api-requirement-"
                    + sha256_bytes(canonical_bytes(evidence))[:20],
                    **evidence,
                }
            )
        if clause_id != "page:interaction" or not text:
            continue
        for match in API_DIRECTIVE_RE.finditer(text):
            locator = match.group("locator")
            evidence = {
                "source_kind": "api_directive",
                "source_ref": {
                    "member_title": member_title,
                    "clause_id": clause_id,
                    "source_sha256": source_sha,
                    "start": match.start(),
                    "end": match.end(),
                    "quote": text[match.start() : match.end()],
                },
                "locator": locator,
            }
            requirements.append(
                {
                    "requirement_id": "api-requirement-"
                    + sha256_bytes(canonical_bytes(evidence))[:20],
                    **evidence,
                }
            )
    return requirements


def api_locator_matches_contract(
    locator: str,
    contract_locator: str,
    apifox: dict[str, Any],
    normalized: dict[str, Any],
) -> bool:
    if contract_locator != locator:
        return False
    method_target = re.fullmatch(
        r"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(.+)", locator
    )
    if method_target is not None:
        method, target = method_target.groups()
        expected_path = urlsplit(target).path if target.startswith("http") else target
        return normalized["method"] == method and normalized["path"] == expected_path
    if locator.startswith("http"):
        return normalized["path"] == urlsplit(locator).path
    if locator.startswith("/"):
        return normalized["path"] == locator
    numeric_parts = locator.split("/")
    if len(numeric_parts) == 1 and numeric_parts[0].isdigit():
        return apifox["endpoint_id"] == int(numeric_parts[0])
    if len(numeric_parts) == 2 and all(part.isdigit() for part in numeric_parts):
        return (
            apifox["project_id"] == int(numeric_parts[0])
            and apifox["endpoint_id"] == int(numeric_parts[1])
        )
    return False


def validate_project_catalog(value: object, project_root: Path) -> dict[str, Any]:
    catalog = require_dict(value, "project component catalog")
    require_exact_keys(catalog, {"schema", "components"}, "project component catalog")
    if catalog.get("schema") != "icp.component-design.project-catalog.v1":
        raise ContractError("invalid_project_catalog", "project component catalog schema is invalid")
    components: list[dict[str, Any]] = []
    component_ids: set[str] = set()
    for index, component_value in enumerate(
        require_list(catalog.get("components"), "project catalog components")
    ):
        label = f"project catalog components[{index}]"
        component = require_dict(component_value, label)
        require_exact_keys(
            component,
            {"component_id", "evidence_class", "provenance", "semantic_contract"},
            label,
        )
        component_id = require_string(component.get("component_id"), f"{label}.component_id")
        if not COMPONENT_ID_RE.fullmatch(component_id) or component_id in component_ids:
            raise ContractError("invalid_project_catalog", f"invalid component {component_id}")
        component_ids.add(component_id)
        if component.get("evidence_class") not in {
            "verified-component-lock",
            "code-derived",
        }:
            raise ContractError("invalid_project_catalog", f"invalid evidence class for {component_id}")
        provenance = require_dict(component.get("provenance"), f"{label}.provenance")
        require_exact_keys(provenance, {"path", "sha256"}, f"{label}.provenance")
        provenance_path = Path(require_string(provenance.get("path"), f"{label}.provenance.path"))
        if provenance_path.is_absolute() or ".." in provenance_path.parts:
            raise ContractError("invalid_project_catalog", f"unsafe provenance path for {component_id}")
        provenance_sha = require_string(provenance.get("sha256"), f"{label}.provenance.sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", provenance_sha):
            raise ContractError("invalid_project_catalog", f"invalid provenance hash for {component_id}")
        semantic_contract = validate_component_definition(
            component.get("semantic_contract"), f"{label}.semantic_contract"
        )
        if semantic_contract["component_id"] != component_id:
            raise ContractError("invalid_project_catalog", f"semantic contract ID mismatch for {component_id}")
        provenance_file = project_root / provenance_path
        if (
            not provenance_file.is_file()
            or sha256_bytes(provenance_file.read_bytes()) != provenance_sha
        ):
            raise ContractError(
                "historical_component_evidence",
                f"provenance file or hash mismatch for {component_id}",
            )
        if component.get("evidence_class") == "verified-component-lock":
            verified_lock = require_dict(
                read_json(provenance_file), f"{label}.verified_component_lock"
            )
            if verified_lock.get("schema") not in {
                "icp.component-design.lock.v4",
                "icp.component-design.lock.v5",
                "icp.component-design.lock.v6",
                "icp.component-design.lock.v7",
                "icp.component-design.lock.v8",
            }:
                raise ContractError(
                    "historical_component_evidence",
                    f"provenance for {component_id} is not a verified component lock",
                )
            locked_definitions = require_list(
                verified_lock.get("component_definitions"),
                f"{label}.verified_component_lock.component_definitions",
            )
            if semantic_contract not in locked_definitions:
                raise ContractError(
                    "historical_component_evidence",
                    f"verified lock does not contain {component_id}",
                )
        components.append(
            {
                **copy.deepcopy(component),
                "semantic_contract": semantic_contract,
            }
        )
    return {
        "schema": "icp.component-design.project-catalog.v1",
        "components": components,
    }


def begin(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    source_path = project_root / ".icp" / "source" / "source-bundle.json"
    if not source_path.is_file():
        raise ContractError(
            "missing_frozen_source",
            "Stage 2 requires the single source bundle frozen by Stage 1",
        )
    stage_dir = stage_dir_for(project_root)
    state_path = stage_dir / "state.json"
    if state_path.exists():
        _, state = load_state(project_root)
        verify_live_mobile_component_pattern_context(stage_dir, state)
        catalog = verify_live_catalog(project_root, stage_dir, state)
        flow_value = read_json(source_path)
        flow_sha = sha256_bytes(source_path.read_bytes())
        if flow_sha != state.get("iole_source_bundle_sha256"):
            raise ContractError("input_drift", "IOLE flow input changed after component design began")
        verify_live_business_context(stage_dir, state, catalog)
        context = require_dict(
            read_json(stage_dir / "business-context.json"), "business context"
        )
        try:
            create_checklist(
                stage_dir / "checklist.json",
                stage="component-design",
                input_sha256=component_checklist_input(state),
                nodes=component_checklist_specs(stage_dir, state),
                initially_completed=["stage.begin"],
            )
        except ChecklistError as exc:
            raise ContractError(exc.code, exc.message) from exc
        return {
            "ok": True,
            "stage": "component-design",
            "stage_dir": str(stage_dir),
            "state": state.get("state"),
            "resumed": True,
            "pages": page_work_items(stage_dir, context),
        }
    if stage_dir.exists() and any(
        path.name != ".write.lock" for path in stage_dir.iterdir()
    ):
        raise ContractError(
            "invalid_state", "component-design directory exists without a valid state"
        )

    catalog, run_sha = build_source_catalog(project_root)
    catalog_sha = sha256_bytes(json_bytes(catalog))
    flow_value = read_json(source_path)
    business_context = build_business_context(flow_value, catalog)
    flow_sha = sha256_bytes(source_path.read_bytes())
    business_context_sha = sha256_bytes(json_bytes(business_context))
    mobile_pattern_context, mobile_pattern_bytes = (
        load_skill_mobile_component_pattern_context()
    )
    state = {
        "schema": "icp.component-design.state.v2",
        "stage": "component-design",
        "state": "collecting_page_facts",
        "revision": 0,
        "extract_run_result_sha256": run_sha,
        "source_catalog_sha256": catalog_sha,
        "iole_source_bundle_sha256": flow_sha,
        "source_bundle_digest": business_context["bundle_digest"],
        "business_context_sha256": business_context_sha,
        "mobile_component_patterns_sha256": mobile_pattern_context[
            "knowledge_sha256"
        ],
        "pages": {
            page_key_for(require_string(member.get("title"), "business member title")): {
                "member_title": require_string(member.get("title"), "business member title"),
                "status": "pending",
                "api_contract_artifacts": [],
            }
            for member in require_list(business_context.get("members"), "business context members")
            if member_requires_semantic_work_item(
                require_dict(member, "business context member")
            )
        },
    }
    atomic_write_json(stage_dir / "source-catalog.json", catalog)
    atomic_write_json(stage_dir / "business-context.json", business_context)
    atomic_write_bytes(
        stage_dir / MOBILE_COMPONENT_PATTERNS_STAGE_NAME, mobile_pattern_bytes
    )
    catalog_snapshot = validate_project_catalog(
        read_json(Path(args.project_catalog))
        if args.project_catalog
        else {
            "schema": "icp.component-design.project-catalog.v1",
            "components": [],
        },
        project_root,
    )
    catalog_snapshot_sha = sha256_bytes(json_bytes(catalog_snapshot))
    state["project_catalog_snapshot_sha256"] = catalog_snapshot_sha
    atomic_write_json(
        stage_dir / "project-component-catalog.snapshot.json", catalog_snapshot
    )
    for member_value in require_list(
        business_context.get("members"), "business context members"
    ):
        member = require_dict(member_value, "business context member")
        if not member_requires_semantic_work_item(member):
            continue
        template = build_page_facts_template(
            member,
            business_context,
            catalog_sha,
            business_context_sha,
            mobile_pattern_context,
        )
        atomic_write_json(
            stage_dir
            / "page-component-facts"
            / f"{template['page_key']}.input.json",
            template,
        )
    try:
        create_checklist(
            stage_dir / "checklist.json",
            stage="component-design",
            input_sha256=component_checklist_input(state),
            nodes=component_checklist_specs(stage_dir, state),
            initially_completed=["stage.begin"],
        )
    except ChecklistError as exc:
        raise ContractError(exc.code, exc.message) from exc
    atomic_write_json(state_path, state)
    return {
        "ok": True,
        "stage": "component-design",
        "stage_dir": str(stage_dir),
        "state": state["state"],
        "resumed": False,
        "pages": page_work_items(stage_dir, business_context),
        "source_catalog": str(stage_dir / "source-catalog.json"),
        "business_context": str(stage_dir / "business-context.json"),
        "mobile_component_patterns": str(
            stage_dir / MOBILE_COMPONENT_PATTERNS_STAGE_NAME
        ),
        "project_component_catalog": str(
            stage_dir / "project-component-catalog.snapshot.json"
        ),
    }


def record_api_contract(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state = load_state(project_root)
    if state.get("state") not in {
        "collecting_page_facts",
        "awaiting_group_abstraction",
    }:
        raise ContractError(
            "invalid_state", "API contracts cannot be recorded in this state"
        )
    page_key = require_string(args.page_key, "page key")
    page_state = require_dict(state.get("pages", {}).get(page_key), "page state")
    catalog = verify_live_catalog(project_root, stage_dir, state)
    context = verify_live_business_context(stage_dir, state, catalog)
    member = next(
        (
            require_dict(value, "business context member")
            for value in require_list(context.get("members"), "business members")
            if require_dict(value, "business context member").get("title")
            == page_state.get("member_title")
        ),
        None,
    )
    if member is None:
        raise ContractError("page_identity_mismatch", "page is absent from business context")
    requirements = build_api_requirements(member)
    require_component_checklist_node(
        stage_dir, state, f"page:{page_key}.api-contracts"
    )
    requirement_by_id = {item["requirement_id"]: item for item in requirements}
    contract = require_dict(read_json(Path(args.contract)), "Apifox contract")
    require_exact_keys(
        contract,
        {"api_contract_id", "requirement_ids", "locator", "apifox", "normalized"},
        "Apifox contract",
        code="invalid_api_acquisition",
    )
    contract_id = require_string(
        contract.get("api_contract_id"), "API contract ID"
    )
    if not COMPONENT_ID_RE.fullmatch(contract_id):
        raise ContractError(
            "invalid_api_acquisition", f"invalid API contract ID {contract_id}"
        )
    requirement_ids = require_string_list(
        contract.get("requirement_ids"), "API contract requirement IDs"
    )
    if len(requirement_ids) != len(set(requirement_ids)) or any(
        requirement_id not in requirement_by_id for requirement_id in requirement_ids
    ):
        raise ContractError(
            "invalid_api_acquisition",
            "API contract binds an unknown or duplicate same-page requirement",
        )
    contract_locator = require_string(contract.get("locator"), "API contract locator")
    apifox = require_dict(contract.get("apifox"), "Apifox acquisition")
    require_exact_keys(
        apifox,
        {"project_id", "endpoint_id", "acquired_by", "raw_contract", "raw_sha256"},
        "Apifox acquisition",
        code="invalid_api_acquisition",
    )
    if type(apifox.get("project_id")) is not int or apifox["project_id"] <= 0:
        raise ContractError("invalid_api_acquisition", "invalid Apifox project ID")
    if type(apifox.get("endpoint_id")) is not int or apifox["endpoint_id"] <= 0:
        raise ContractError("invalid_api_acquisition", "invalid Apifox endpoint ID")
    if apifox.get("acquired_by") not in {
        "readEntityDetails",
        "getHttpEndpoint",
        "exportData",
    }:
        raise ContractError("invalid_api_acquisition", "invalid Apifox read method")
    raw_contract = require_dict(
        apifox.get("raw_contract"), "Apifox raw contract"
    )
    if apifox.get("raw_sha256") != sha256_bytes(canonical_bytes(raw_contract)):
        raise ContractError(
            "invalid_api_acquisition", "Apifox raw contract hash changed"
        )
    normalized = require_dict(contract.get("normalized"), "normalized API contract")
    require_exact_keys(
        normalized,
        {"method", "path", "auth", "parameters", "request_body", "responses", "errors"},
        "normalized API contract",
        code="invalid_api_acquisition",
    )
    method = require_string(normalized.get("method"), "normalized API method").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        raise ContractError("invalid_api_acquisition", "invalid normalized API method")
    require_string(normalized.get("path"), "normalized API path")
    for field in ("parameters", "responses", "errors"):
        require_list(normalized.get(field), f"normalized API {field}")
    for requirement_id in requirement_ids:
        requirement = requirement_by_id[requirement_id]
        if (
            requirement["source_kind"] == "api_directive"
            and not api_locator_matches_contract(
                requirement["locator"],
                contract_locator,
                apifox,
                {**normalized, "method": method},
            )
        ):
            raise ContractError(
                "api_locator_mismatch",
                f"acquired contract does not match API directive {requirement['locator']}",
            )
    artifact_path = (
        stage_dir / "api-contracts" / page_key / f"{contract_id}.json"
    )
    artifact_sha = sha256_bytes(json_bytes(contract))
    entries = require_list(
        page_state.get("api_contract_artifacts"), "page API contract artifacts"
    )
    existing = next(
        (
            require_dict(value, "API contract artifact")
            for value in entries
            if require_dict(value, "API contract artifact").get("api_contract_id")
            == contract_id
        ),
        None,
    )
    for artifact_value in entries:
        artifact = require_dict(artifact_value, "API contract artifact")
        if artifact.get("api_contract_id") == contract_id:
            continue
        existing_path = stage_dir / require_string(
            artifact.get("path"), "API contract artifact path"
        )
        existing_contract = require_dict(
            read_json(existing_path), "existing API contract artifact"
        )
        if set(require_string_list(existing_contract.get("requirement_ids"), "requirement IDs")) & set(requirement_ids):
            raise ContractError(
                "invalid_api_acquisition",
                "one API requirement cannot be sealed by multiple contracts",
            )
    if existing is not None:
        if (
            existing.get("sha256") == artifact_sha
            and artifact_path.is_file()
            and sha256_bytes(artifact_path.read_bytes()) == artifact_sha
        ):
            mark_page_api_checklist_if_complete(
                stage_dir, state, page_key, requirements
            )
            return {
                "ok": True,
                "stage": "component-design",
                "page_key": page_key,
                "api_contract_id": contract_id,
                "artifact": str(artifact_path),
                "sha256": artifact_sha,
                "resumed": True,
            }
        if page_state.get("status") not in {"pending", "revision_required"}:
            raise ContractError(
                "api_acquisition_locked",
                f"API contract cannot change while page is {page_state.get('status')}",
            )
        entries.remove(existing)
    atomic_write_json(artifact_path, contract)
    entries.append(
        {
            "api_contract_id": contract_id,
            "path": str(artifact_path.relative_to(stage_dir)),
            "sha256": artifact_sha,
        }
    )
    page_state["api_contract_artifacts"] = entries
    atomic_write_json(stage_dir / "state.json", state)
    mark_page_api_checklist_if_complete(stage_dir, state, page_key, requirements)
    return {
        "ok": True,
        "stage": "component-design",
        "page_key": page_key,
        "api_contract_id": contract_id,
        "artifact": str(artifact_path),
        "sha256": artifact_sha,
        "resumed": False,
    }


def catalog_maps(catalog: dict[str, Any]) -> dict[str, Any]:
    design_order: list[str] = []
    design_blocks: dict[str, set[str]] = {}
    root_blocks: dict[str, str] = {}
    semantic_parent: dict[tuple[str, str], str | None] = {}
    block_nodes: dict[tuple[str, str], set[str]] = {}
    for design_value in require_list(catalog.get("designs"), "catalog designs"):
        design = require_dict(design_value, "catalog design")
        design_name = require_string(design.get("design_name"), "catalog design name")
        design_order.append(design_name)
        root_blocks[design_name] = require_string(
            design.get("root_block_id"), "catalog root block"
        )
        blocks: set[str] = set()
        for block_value in require_list(design.get("blocks"), "catalog blocks"):
            block = require_dict(block_value, "catalog block")
            block_id = require_string(block.get("block_id"), "catalog block id")
            if block_id in blocks:
                raise ContractError("extract_drift", f"duplicate catalog block {design_name}/{block_id}")
            blocks.add(block_id)
            semantic = require_dict(block.get("semantic"), "catalog semantic block")
            semantic_parent[(design_name, block_id)] = semantic.get("parent_block_id")
            block_nodes[(design_name, block_id)] = {
                require_string(
                    require_dict(node, "catalog source node").get("source_node_id"),
                    "catalog source node id",
                )
                for node in require_list(block.get("source_nodes"), "catalog source nodes")
            }
        design_blocks[design_name] = blocks
    if len(set(design_order)) != len(design_order):
        raise ContractError("extract_drift", "catalog contains duplicate design names")
    return {
        "design_order": design_order,
        "design_blocks": design_blocks,
        "root_blocks": root_blocks,
        "semantic_parent": semantic_parent,
        "block_nodes": block_nodes,
    }


def business_maps(context: dict[str, Any]) -> dict[str, Any]:
    clauses: dict[str, dict[str, dict[str, str]]] = {}
    member_for_design: dict[str, str] = {}
    designs_for_member: dict[str, list[str]] = {}
    for member_value in require_list(context.get("members"), "business context members"):
        member = require_dict(member_value, "business context member")
        member_title = require_string(member.get("title"), "business member title")
        if member_title in designs_for_member:
            raise ContractError(
                "invalid_business_context", f"duplicate business member {member_title}"
            )
        member_clauses: dict[str, dict[str, str]] = {}
        for clause_value in require_list(member.get("clauses"), "business clauses"):
            clause = require_dict(clause_value, "business clause")
            clause_id = require_string(clause.get("clause_id"), "business clause_id")
            if clause_id in member_clauses:
                raise ContractError(
                    "invalid_business_context", f"duplicate clause {member.get('title')}/{clause_id}"
                )
            member_clauses[clause_id] = clause
        design_states = member.get("design_states")
        if design_states is None:
            design_name = member.get("design_name")
            design_names = [] if design_name is None else [design_name]
        else:
            design_names = [
                require_string(
                    require_dict(state, "business context design state").get("design_name"),
                    "business context design_name",
                )
                for state in require_list(design_states, "business context design states")
            ]
        designs_for_member[member_title] = list(design_names)
        for design_name in design_names:
            if design_name in clauses:
                raise ContractError(
                    "invalid_business_context", f"duplicate context for {design_name}"
                )
            clauses[design_name] = copy.deepcopy(member_clauses)
            member_for_design[design_name] = member_title
    return {
        "clauses": clauses,
        "member_for_design": member_for_design,
        "designs_for_member": designs_for_member,
    }


def validate_page_block_ref(
    value: object,
    catalog: dict[str, Any],
    allowed_designs: set[str],
    label: str,
) -> dict[str, str]:
    ref = require_dict(value, label)
    require_exact_keys(ref, {"design_name", "block_id"}, label)
    design_name = require_string(ref.get("design_name"), f"{label}.design_name")
    block_id = require_string(ref.get("block_id"), f"{label}.block_id")
    maps = catalog_maps(catalog)
    if design_name not in allowed_designs:
        raise ContractError(
            "cross_page_semantic_leak",
            f"{label} cites design {design_name} outside the page",
        )
    if block_id not in maps["design_blocks"].get(design_name, set()):
        raise ContractError(
            "semantic_block_coverage", f"{label} cites an unknown semantic Block"
        )
    return {"design_name": design_name, "block_id": block_id}


def validate_page_source_ref(
    value: object,
    member_title: str,
    clause_map: dict[str, dict[str, str]],
    label: str,
) -> dict[str, Any]:
    ref = require_dict(value, label)
    require_exact_keys(
        ref,
        {"member_title", "clause_id", "source_sha256", "start", "end", "quote"},
        label,
    )
    if ref.get("member_title") != member_title:
        raise ContractError(
            "cross_page_semantic_leak", f"{label} cites another page"
        )
    clause_id = require_string(ref.get("clause_id"), f"{label}.clause_id")
    clause = clause_map.get(clause_id)
    if clause is None:
        raise ContractError("source_coverage", f"{label} cites an unknown clause")
    source_text = require_text(clause.get("text"), f"{label}.source_text")
    source_sha = sha256_bytes(source_text.encode("utf-8"))
    if ref.get("source_sha256") != source_sha:
        raise ContractError("source_coverage", f"{label} source hash mismatch")
    start = ref.get("start")
    end = ref.get("end")
    if (
        type(start) is not int
        or type(end) is not int
        or start < 0
        or end <= start
        or end > len(source_text)
    ):
        raise ContractError("source_coverage", f"{label} offsets are invalid")
    quote = require_text(ref.get("quote"), f"{label}.quote")
    if quote != source_text[start:end]:
        raise ContractError("source_coverage", f"{label} quote/offset mismatch")
    return copy.deepcopy(ref)


def validate_page_facts(
    value: object,
    page_key: str,
    member: dict[str, Any],
    business_context: dict[str, Any],
    catalog: dict[str, Any],
    state: dict[str, Any],
    stage_dir: Path,
) -> dict[str, Any]:
    facts = require_dict(value, "page facts")
    require_exact_keys(
        facts,
        {
            "schema",
            "page_key",
            "member_title",
            "source_catalog_sha256",
            "business_context_sha256",
            "mobile_component_pattern_context",
            "design_names",
            "source_coverage",
            "presentation_requirements",
            "navigation_requirements",
            "api_requirements",
            "api_contracts",
            "interaction_items",
            "interaction_graph",
            "candidates",
            "design_compositions",
        },
        "page facts",
    )
    if facts.get("schema") != "icp.component-design.page-facts.v4":
        raise ContractError("invalid_page_facts", "page facts schema is invalid")
    member_title = require_string(member.get("title"), "business member title")
    if facts.get("page_key") != page_key or facts.get("member_title") != member_title:
        raise ContractError("page_identity_mismatch", "page facts target another page")
    if facts.get("source_catalog_sha256") != state.get("source_catalog_sha256"):
        raise ContractError("input_drift", "page facts target another source catalog")
    if facts.get("business_context_sha256") != state.get("business_context_sha256"):
        raise ContractError("input_drift", "page facts target another business context")
    validate_mobile_component_pattern_context(
        facts.get("mobile_component_pattern_context"), state
    )
    expected_designs = [
        require_string(item.get("design_name"), "design state name")
        for item in require_list(member.get("design_states"), "design states")
    ]
    design_names = require_string_list(
        facts.get("design_names"), "page facts design_names", nonempty=False
    )
    if design_names != expected_designs:
        raise ContractError("page_identity_mismatch", "page design order changed")
    expected_presentation_requirements = build_presentation_requirements(
        member, business_context
    )
    if facts.get("presentation_requirements") != expected_presentation_requirements:
        raise ContractError(
            "presentation_requirement_drift",
            "page presentation requirements changed from the verified source closure",
        )
    expected_navigation_requirements = build_navigation_requirements(
        member, business_context
    )
    if facts.get("navigation_requirements") != expected_navigation_requirements:
        raise ContractError(
            "navigation_requirement_drift",
            "page navigation requirements changed from the verified source closure",
        )
    expected_api_requirements = build_api_requirements(member)
    if facts.get("api_requirements") != expected_api_requirements:
        raise ContractError(
            "api_requirement_drift",
            "page API requirements changed from the same-page source",
        )
    page_state = require_dict(state.get("pages", {}).get(page_key), "page state")
    acquired_contracts: list[dict[str, Any]] = []
    for artifact_index, artifact_value in enumerate(
        require_list(
            page_state.get("api_contract_artifacts"),
            "page API contract artifacts",
        )
    ):
        label = f"page API contract artifacts[{artifact_index}]"
        artifact = require_dict(artifact_value, label)
        require_exact_keys(
            artifact, {"api_contract_id", "path", "sha256"}, label
        )
        contract_id = require_string(
            artifact.get("api_contract_id"), f"{label}.api_contract_id"
        )
        relative_path = Path(
            require_string(artifact.get("path"), f"{label}.path")
        )
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ContractError(
                "api_acquisition_drift", f"{label}.path escapes the stage"
            )
        artifact_path = stage_dir / relative_path
        expected_sha = require_string(artifact.get("sha256"), f"{label}.sha256")
        if (
            not artifact_path.is_file()
            or sha256_bytes(artifact_path.read_bytes()) != expected_sha
        ):
            raise ContractError(
                "api_acquisition_drift", f"sealed API artifact changed: {contract_id}"
            )
        contract = require_dict(read_json(artifact_path), "sealed API contract")
        if contract.get("api_contract_id") != contract_id:
            raise ContractError(
                "api_acquisition_drift", f"sealed API identity changed: {contract_id}"
            )
        acquired_contracts.append(contract)
    # Page API contracts are an ID-keyed object collection: the declared list
    # must cover every sealed artifact exactly (duplicate IDs rejected, whole
    # payloads compared by ID); acquisition-list order is not a contract, so
    # the declared list is normalized to the sealed artifact order.
    declared_contracts_by_id: dict[str, dict[str, Any]] = {}
    for contract_index, contract_value in enumerate(
        require_list(facts.get("api_contracts"), "page api_contracts")
    ):
        contract_label = f"page api_contracts[{contract_index}]"
        declared_contract = require_dict(contract_value, contract_label)
        declared_id = require_string(
            declared_contract.get("api_contract_id"),
            f"{contract_label}.api_contract_id",
        )
        if declared_id in declared_contracts_by_id:
            raise ContractError(
                "api_acquisition_missing",
                "page API contracts must exactly equal the separately sealed "
                f"Apifox artifacts; duplicates=['{declared_id}']",
            )
        declared_contracts_by_id[declared_id] = declared_contract
    acquired_contracts_by_id = {
        require_string(
            contract.get("api_contract_id"), "sealed API contract ID"
        ): contract
        for contract in acquired_contracts
    }
    missing_contracts = sorted(
        set(acquired_contracts_by_id) - set(declared_contracts_by_id)
    )
    unexpected_contracts = sorted(
        set(declared_contracts_by_id) - set(acquired_contracts_by_id)
    )
    if missing_contracts or unexpected_contracts:
        raise ContractError(
            "api_acquisition_missing",
            "page API contracts must exactly equal the separately sealed Apifox "
            f"artifacts; missing={missing_contracts} "
            f"unexpected={unexpected_contracts}",
        )
    for acquired_contract in acquired_contracts:
        acquired_id = require_string(
            acquired_contract.get("api_contract_id"), "sealed API contract ID"
        )
        if declared_contracts_by_id[acquired_id] != acquired_contract:
            raise ContractError(
                "api_acquisition_missing",
                f"page API contract payload changed: {acquired_id}",
            )
    ordered_declared_contracts = [
        declared_contracts_by_id[
            require_string(
                contract.get("api_contract_id"), "sealed API contract ID"
            )
        ]
        for contract in acquired_contracts
    ]
    api_requirement_ids = {
        item["requirement_id"] for item in expected_api_requirements
    }
    api_requirement_by_id = {
        item["requirement_id"]: item for item in expected_api_requirements
    }
    api_contract_ids: set[str] = set()
    normalized_api_contracts: list[dict[str, Any]] = []
    for contract_index, contract_value in enumerate(ordered_declared_contracts):
        label = f"page api_contracts[{contract_index}]"
        contract = require_dict(contract_value, label)
        require_exact_keys(
            contract,
            {
                "api_contract_id",
                "requirement_ids",
                "locator",
                "apifox",
                "normalized",
            },
            label,
            code="invalid_api_contract",
        )
        contract_id = require_string(
            contract.get("api_contract_id"), f"{label}.api_contract_id"
        )
        if (
            not COMPONENT_ID_RE.fullmatch(contract_id)
            or contract_id in api_contract_ids
        ):
            raise ContractError(
                "invalid_api_contract", f"invalid or duplicate API contract {contract_id}"
            )
        api_contract_ids.add(contract_id)
        requirement_ids = require_string_list(
            contract.get("requirement_ids"), f"{label}.requirement_ids"
        )
        if len(requirement_ids) != len(set(requirement_ids)) or any(
            requirement_id not in api_requirement_ids
            for requirement_id in requirement_ids
        ):
            raise ContractError(
                "invalid_api_contract",
                f"{label} binds an unknown or duplicate API requirement",
            )
        require_string(contract.get("locator"), f"{label}.locator")
        apifox = require_dict(contract.get("apifox"), f"{label}.apifox")
        require_exact_keys(
            apifox,
            {
                "project_id",
                "endpoint_id",
                "acquired_by",
                "raw_contract",
                "raw_sha256",
            },
            f"{label}.apifox",
            code="invalid_api_contract",
        )
        if type(apifox.get("project_id")) is not int or apifox["project_id"] <= 0:
            raise ContractError(
                "invalid_api_contract", f"{label}.apifox.project_id is invalid"
            )
        if type(apifox.get("endpoint_id")) is not int or apifox["endpoint_id"] <= 0:
            raise ContractError(
                "invalid_api_contract", f"{label}.apifox.endpoint_id is invalid"
            )
        if apifox.get("acquired_by") not in {
            "readEntityDetails",
            "getHttpEndpoint",
            "exportData",
        }:
            raise ContractError(
                "invalid_api_contract", f"{label}.apifox.acquired_by is invalid"
            )
        raw_contract = require_dict(
            apifox.get("raw_contract"), f"{label}.apifox.raw_contract"
        )
        raw_sha = require_string(
            apifox.get("raw_sha256"), f"{label}.apifox.raw_sha256"
        )
        if raw_sha != sha256_bytes(canonical_bytes(raw_contract)):
            raise ContractError(
                "invalid_api_contract", f"{label}.apifox raw contract hash changed"
            )
        normalized = require_dict(
            contract.get("normalized"), f"{label}.normalized"
        )
        require_exact_keys(
            normalized,
            {
                "method",
                "path",
                "auth",
                "parameters",
                "request_body",
                "responses",
                "errors",
            },
            f"{label}.normalized",
            code="invalid_api_contract",
        )
        method = require_string(
            normalized.get("method"), f"{label}.normalized.method"
        ).upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ContractError(
                "invalid_api_contract", f"{label}.normalized.method is invalid"
            )
        require_string(normalized.get("path"), f"{label}.normalized.path")
        require_list(normalized.get("parameters"), f"{label}.normalized.parameters")
        require_list(normalized.get("responses"), f"{label}.normalized.responses")
        require_list(normalized.get("errors"), f"{label}.normalized.errors")
        for requirement_id in requirement_ids:
            requirement = api_requirement_by_id[requirement_id]
            locator = requirement["locator"]
            if (
                requirement["source_kind"] == "api_directive"
                and not api_locator_matches_contract(
                    require_string(locator, "API directive locator"),
                    contract["locator"],
                    apifox,
                    {**normalized, "method": method},
                )
            ):
                raise ContractError(
                    "api_locator_mismatch",
                    f"{label} does not match API directive {locator}",
                )
        normalized_contract = copy.deepcopy(contract)
        normalized_contract["normalized"]["method"] = method
        normalized_api_contracts.append(normalized_contract)
    allowed_designs = set(design_names)
    clause_map = {
        require_string(item.get("clause_id"), "business clause_id"): item
        for item in require_list(member.get("clauses"), "business clauses")
    }

    candidate_ids: set[str] = set()
    candidate_block_refs: dict[str, set[tuple[str, str]]] = {}
    fact_ids: set[str] = set()
    business_fact_ids: set[str] = set()
    fact_evidence_classes: dict[str, str] = {}
    fact_kinds_by_id: dict[str, str] = {}
    fact_meanings_by_id: dict[str, str] = {}
    fact_source_keys: dict[str, set[tuple[str, int, int]]] = {}
    candidate_by_fact_id: dict[str, str] = {}
    normalized_candidates: list[dict[str, Any]] = []
    owned_block_refs: list[tuple[str, str]] = []
    for candidate_index, candidate_value in enumerate(
        require_list(facts.get("candidates"), "page facts candidates")
    ):
        label = f"page facts candidates[{candidate_index}]"
        candidate = require_dict(candidate_value, label)
        require_exact_keys(
            candidate,
            {
                "candidate_id",
                "name",
                "kind",
                "responsibility",
                "owns",
                "excludes",
                "source_block_refs",
                "facts",
            },
            label,
        )
        candidate_id = require_string(candidate.get("candidate_id"), f"{label}.candidate_id")
        if not COMPONENT_ID_RE.fullmatch(candidate_id) or candidate_id in candidate_ids:
            raise ContractError("invalid_candidate", f"invalid or duplicate {candidate_id}")
        candidate_ids.add(candidate_id)
        require_string(candidate.get("name"), f"{label}.name")
        kind = require_string(candidate.get("kind"), f"{label}.kind")
        if kind not in PAGE_CANDIDATE_KINDS:
            raise ContractError("invalid_candidate", f"invalid candidate kind {kind}")
        require_string(candidate.get("responsibility"), f"{label}.responsibility")
        require_string_list(candidate.get("owns"), f"{label}.owns")
        require_string_list(candidate.get("excludes"), f"{label}.excludes")
        block_refs = [
            validate_page_block_ref(item, catalog, allowed_designs, f"{label}.source_block_refs[{index}]")
            for index, item in enumerate(
                require_list(candidate.get("source_block_refs"), f"{label}.source_block_refs")
            )
        ]
        if allowed_designs and not block_refs:
            raise ContractError("semantic_block_coverage", f"{label} owns no Blocks")
        if not allowed_designs and block_refs:
            raise ContractError(
                "semantic_block_coverage",
                f"{label} cannot cite Blocks without a verified design",
            )
        owned_block_refs.extend(
            (item["design_name"], item["block_id"]) for item in block_refs
        )
        candidate_block_refs[candidate_id] = {
            (item["design_name"], item["block_id"]) for item in block_refs
        }
        owned_candidate_blocks = candidate_block_refs[candidate_id]
        normalized_facts: list[dict[str, Any]] = []
        for fact_index, fact_value in enumerate(
            require_list(candidate.get("facts"), f"{label}.facts")
        ):
            fact_label = f"{label}.facts[{fact_index}]"
            fact = require_dict(fact_value, fact_label)
            evidence_class = fact.get("evidence_class")
            if evidence_class not in FACT_EVIDENCE_CLASSES:
                raise ContractError(
                    "invalid_fact_evidence_class",
                    f"{fact_label}.evidence_class is invalid",
                )
            expected_fact_keys = {
                "fact_id",
                "kind",
                "meaning",
                "evidence_class",
                "source_refs",
                "block_refs",
            }
            if fact.get("kind") == "component_relation":
                expected_fact_keys.update({"relation_intent", "relation_target"})
            if evidence_class == "design_visible":
                expected_fact_keys.add("visible_basis")
            if set(fact) != expected_fact_keys:
                if fact.get("kind") == "component_relation":
                    raise ContractError(
                        "invalid_component_relation",
                        f"{fact_label} needs one closed relation intent and target",
                    )
                raise ContractError(
                    "invalid_fact_evidence_class",
                    f"{fact_label} fields do not match {evidence_class} evidence",
                )
            fact_id = require_string(fact.get("fact_id"), f"{fact_label}.fact_id")
            if not COMPONENT_ID_RE.fullmatch(fact_id) or fact_id in fact_ids:
                raise ContractError("invalid_semantic_fact", f"invalid or duplicate {fact_id}")
            fact_ids.add(fact_id)
            candidate_by_fact_id[fact_id] = candidate_id
            fact_kind = require_string(fact.get("kind"), f"{fact_label}.kind")
            if fact_kind not in PAGE_FACT_KINDS:
                raise ContractError("invalid_semantic_fact", f"invalid fact kind {fact_kind}")
            fact_kinds_by_id[fact_id] = fact_kind
            if fact_kind == "component_relation":
                relation_intent = require_string(
                    fact.get("relation_intent"),
                    f"{fact_label}.relation_intent",
                )
                if relation_intent not in COMPONENT_RELATION_INTENTS:
                    raise ContractError(
                        "invalid_component_relation",
                        f"{fact_label}.relation_intent is invalid",
                    )
                relation_target = require_dict(
                    fact.get("relation_target"),
                    f"{fact_label}.relation_target",
                )
                require_exact_keys(
                    relation_target,
                    {"kind", "id"},
                    f"{fact_label}.relation_target",
                )
                target_kind = require_string(
                    relation_target.get("kind"),
                    f"{fact_label}.relation_target.kind",
                )
                target_id = require_string(
                    relation_target.get("id"),
                    f"{fact_label}.relation_target.id",
                )
                if target_kind not in COMPONENT_RELATION_TARGET_KINDS:
                    raise ContractError(
                        "invalid_component_relation",
                        f"{fact_label}.relation_target.kind is invalid",
                    )
                if target_kind == "self_candidate" and target_id != candidate_id:
                    raise ContractError(
                        "invalid_component_relation",
                        f"{fact_label} self target does not match its candidate",
                    )
                if relation_intent in {"local_boundary", "shared_candidate"}:
                    if target_kind != "self_candidate":
                        raise ContractError(
                            "invalid_component_relation",
                            f"{fact_label} {relation_intent} must target its own candidate",
                        )
                elif target_kind != "source_member":
                    raise ContractError(
                        "invalid_component_relation",
                        f"{fact_label} shared_usage must target a source member",
                    )
                else:
                    member_titles = {
                        require_string(item.get("title"), "business member title")
                        for item_value in require_list(
                            business_context.get("members"),
                            "business context members",
                        )
                        for item in [require_dict(item_value, "business context member")]
                    }
                    relation_pairs = {
                        (
                            require_string(item.get("from_title"), "relation source"),
                            require_string(item.get("to_title"), "relation target"),
                        )
                        for item_value in require_list(
                            business_context.get("relations"),
                            "business context relations",
                        )
                        for item in [require_dict(item_value, "business context relation")]
                    }
                    if (
                        target_id not in member_titles
                        or (member_title, target_id) not in relation_pairs
                    ):
                        raise ContractError(
                            "invalid_component_relation",
                            f"{fact_label} shared_usage target is not a closed source relation",
                        )
                if (
                    evidence_class == "design_visible"
                    and relation_intent != "local_boundary"
                ):
                    raise ContractError(
                        "invalid_component_relation",
                        f"{fact_label} visible evidence cannot authorize reuse",
                    )
            if (
                evidence_class == "design_visible"
                and fact_kind not in DESIGN_VISIBLE_FACT_KINDS
            ):
                raise ContractError(
                    "invalid_fact_evidence_class",
                    f"{fact_label} uses an invisible fact kind",
                )
            fact_meanings_by_id[fact_id] = require_string(
                fact.get("meaning"), f"{fact_label}.meaning"
            )
            source_refs = [
                validate_page_source_ref(
                    item,
                    member_title,
                    clause_map,
                    f"{fact_label}.source_refs[{index}]",
                )
                for index, item in enumerate(
                    require_list(fact.get("source_refs"), f"{fact_label}.source_refs")
                )
            ]
            block_fact_refs = [
                validate_page_block_ref(
                    item,
                    catalog,
                    allowed_designs,
                    f"{fact_label}.block_refs[{index}]",
                )
                for index, item in enumerate(
                    require_list(fact.get("block_refs"), f"{fact_label}.block_refs")
                )
            ]
            if allowed_designs and not block_fact_refs:
                raise ContractError(
                    "invalid_semantic_fact",
                    f"{fact_label} needs design Block evidence",
                )
            if not allowed_designs and block_fact_refs:
                raise ContractError(
                    "invalid_semantic_fact",
                    f"{fact_label} cannot cite Blocks without a verified design",
                )
            if evidence_class == "business_source" and not source_refs:
                raise ContractError(
                    "invalid_semantic_fact",
                    f"{fact_label} needs exact business source evidence",
                )
            if evidence_class == "design_visible":
                if not allowed_designs:
                    raise ContractError(
                        "invalid_fact_evidence_class",
                        f"{fact_label} cannot claim visible evidence without a design",
                    )
                if source_refs:
                    raise ContractError(
                        "invalid_fact_evidence_class",
                        f"{fact_label} design evidence cannot cite business source spans",
                    )
                visible_basis = fact.get("visible_basis")
                if not isinstance(visible_basis, str) or not visible_basis.strip():
                    raise ContractError(
                        "invalid_fact_evidence_class",
                        f"{fact_label}.visible_basis must be non-empty",
                    )
            if any(
                (item["design_name"], item["block_id"])
                not in owned_candidate_blocks
                for item in block_fact_refs
            ):
                raise ContractError(
                    "semantic_hierarchy_mismatch",
                    f"{fact_label} cites a Block outside its owning candidate",
                )
            fact_evidence_classes[fact_id] = evidence_class
            fact_source_keys[fact_id] = {
                (item["clause_id"], item["start"], item["end"])
                for item in source_refs
            }
            if evidence_class == "business_source":
                business_fact_ids.add(fact_id)
            normalized_facts.append({**copy.deepcopy(fact), "source_refs": source_refs, "block_refs": block_fact_refs})
        normalized_candidates.append({**copy.deepcopy(candidate), "source_block_refs": block_refs, "facts": normalized_facts})
    if not candidate_ids:
        raise ContractError("candidate_coverage", "page has no component candidates")

    coverage = require_list(facts.get("source_coverage"), "page source_coverage")
    expected_clauses = list(clause_map.values())
    if len(coverage) != len(expected_clauses):
        raise ContractError("source_coverage", "page clause coverage/order is incomplete")
    consumed_fact_ids: set[str] = set()
    covered_fact_source_keys: set[tuple[str, str, int, int]] = set()
    normalized_coverage: list[dict[str, Any]] = []
    for index, (clause, coverage_value) in enumerate(zip(expected_clauses, coverage, strict=True)):
        label = f"page source_coverage[{index}]"
        item = require_dict(coverage_value, label)
        require_exact_keys(
            item,
            {"clause_id", "source_sha256", "source_text", "segments"},
            label,
        )
        clause_id = require_string(clause.get("clause_id"), "business clause_id")
        source_text = require_text(clause.get("text"), "business clause text")
        source_sha = sha256_bytes(source_text.encode("utf-8"))
        if (
            item.get("clause_id") != clause_id
            or item.get("source_sha256") != source_sha
            or item.get("source_text") != source_text
        ):
            raise ContractError("source_coverage", f"{label} source changed")
        segments = require_list(item.get("segments"), f"{label}.segments")
        if bool(source_text) != bool(segments):
            raise ContractError("source_coverage", f"{label} does not cover its source")
        cursor = 0
        has_fact_segment = False
        normalized_segments: list[dict[str, Any]] = []
        for segment_index, segment_value in enumerate(segments):
            segment_label = f"{label}.segments[{segment_index}]"
            segment = require_dict(segment_value, segment_label)
            disposition = require_string(
                segment.get("disposition"), f"{segment_label}.disposition"
            )
            if disposition not in COVERAGE_DISPOSITIONS:
                raise ContractError("source_coverage", f"invalid disposition {disposition}")
            expected_keys = {"start", "end", "quote", "disposition"}
            expected_keys.add("fact_ids" if disposition == "fact" else "rationale")
            require_exact_keys(segment, expected_keys, segment_label)
            start = segment.get("start")
            end = segment.get("end")
            if (
                type(start) is not int
                or type(end) is not int
                or start != cursor
                or end <= start
                or end > len(source_text)
                or segment.get("quote") != source_text[start:end]
            ):
                raise ContractError("source_coverage", f"{segment_label} is not contiguous")
            if disposition == "fact":
                has_fact_segment = True
                ids = require_string_list(segment.get("fact_ids"), f"{segment_label}.fact_ids")
                for fact_id in ids:
                    if fact_id not in fact_ids:
                        raise ContractError("source_coverage", f"unknown fact {fact_id}")
                    if fact_evidence_classes[fact_id] == "design_visible":
                        raise ContractError(
                            "design_visible_coverage_leak",
                            f"{segment_label} uses design-visible evidence for business coverage",
                        )
                    if (clause_id, start, end) not in fact_source_keys[fact_id]:
                        raise ContractError("source_coverage", f"fact {fact_id} lacks this exact source span")
                    covered_fact_source_keys.add(
                        (fact_id, clause_id, start, end)
                    )
                consumed_fact_ids.update(ids)
            else:
                require_string(segment.get("rationale"), f"{segment_label}.rationale")
                if disposition == "unresolved":
                    raise ContractError("unresolved_semantic", f"{segment_label} remains unresolved")
                if not is_non_normative_context(
                    require_text(segment.get("quote"), f"{segment_label}.quote")
                ):
                    raise ContractError(
                        "source_coverage",
                        f"{segment_label} context must be whitespace only",
                    )
            normalized_segments.append(copy.deepcopy(segment))
            cursor = end
        if cursor != len(source_text):
            raise ContractError("source_coverage", f"{label} does not cover its source")
        if source_text.strip() and not has_fact_segment:
            raise ContractError(
                "source_coverage",
                f"{label} hides a non-empty business clause without a semantic fact",
            )
        normalized_coverage.append({**copy.deepcopy(item), "segments": normalized_segments})
    if consumed_fact_ids != business_fact_ids:
        raise ContractError("semantic_fact_coverage", "one or more facts have no exact source consumer")
    expected_fact_source_keys = {
        (fact_id, clause_id, start, end)
        for fact_id, source_keys in fact_source_keys.items()
        if fact_id in business_fact_ids
        for clause_id, start, end in source_keys
    }
    if covered_fact_source_keys != expected_fact_source_keys:
        raise ContractError(
            "semantic_fact_coverage",
            "fact source evidence and the coverage ledger are not bidirectionally equal",
        )

    interaction_clause = clause_map.get("page:interaction")
    if interaction_clause is None:
        raise ContractError(
            "invalid_business_context", "page interaction clause is missing"
        )
    interaction_text = require_text(
        interaction_clause.get("text"), "page interaction source text"
    )
    interaction_items_value = require_list(
        facts.get("interaction_items"), "page interaction_items"
    )
    normalized_interaction_items: list[dict[str, Any]] = []
    interaction_item_ids: set[str] = set()
    interaction_fact_ids: set[str] = set()
    interaction_item_source_keys: set[tuple[str, int, int]] = set()
    interaction_coverage_source_keys = {
        (coverage["clause_id"], segment["start"], segment["end"])
        for coverage in normalized_coverage
        if coverage["clause_id"] == "page:interaction"
        for segment in coverage["segments"]
        if segment["disposition"] == "fact"
    }
    if interaction_text == "":
        if len(interaction_items_value) != 1:
            raise ContractError(
                "invalid_interaction_item",
                "an empty interaction description needs one explicit null item",
            )
    elif not interaction_items_value:
        raise ContractError(
            "interaction_item_coverage",
            "a non-empty interaction description needs atomic interaction items",
        )
    for item_index, item_value in enumerate(interaction_items_value):
        label = f"page interaction_items[{item_index}]"
        item = require_dict(item_value, label)
        require_exact_keys(
            item,
            {"item_id", "source_ref", *INTERACTION_ITEM_FIELDS},
            label,
            code="invalid_interaction_item",
        )
        item_id = require_string(item.get("item_id"), f"{label}.item_id")
        if not COMPONENT_ID_RE.fullmatch(item_id) or item_id in interaction_item_ids:
            raise ContractError(
                "invalid_interaction_item", f"invalid or duplicate item {item_id}"
            )
        interaction_item_ids.add(item_id)
        non_null_fields = [
            field for field in INTERACTION_ITEM_FIELDS if item.get(field) is not None
        ]
        source_ref_value = item.get("source_ref")
        if interaction_text == "":
            if source_ref_value is not None or non_null_fields:
                raise ContractError(
                    "invalid_interaction_item",
                    "an empty interaction description must remain an all-null item",
                )
            normalized_interaction_items.append(copy.deepcopy(item))
            continue
        if len(non_null_fields) > 1:
            raise ContractError(
                "invalid_interaction_item",
                f"{label} may contain at most one non-null atomic interaction field",
            )
        source_ref = validate_page_source_ref(
            source_ref_value,
            member_title,
            clause_map,
            f"{label}.source_ref",
        )
        if source_ref["clause_id"] != "page:interaction":
            raise ContractError(
                "invalid_interaction_item",
                f"{label} must cite the page interaction description",
            )
        source_key = (
            source_ref["clause_id"],
            source_ref["start"],
            source_ref["end"],
        )
        if source_key not in interaction_coverage_source_keys:
            raise ContractError(
                "interaction_item_coverage",
                f"{label} does not match one complete source coverage segment",
            )
        interaction_item_source_keys.add(source_key)
        if not non_null_fields:
            normalized_interaction_items.append(
                {**copy.deepcopy(item), "source_ref": source_ref}
            )
            continue
        field = non_null_fields[0]
        part = require_dict(item.get(field), f"{label}.{field}")
        require_exact_keys(
            part,
            {"fact_id", "meaning"},
            f"{label}.{field}",
            code="invalid_interaction_item",
        )
        fact_id = require_string(part.get("fact_id"), f"{label}.{field}.fact_id")
        meaning = require_string(part.get("meaning"), f"{label}.{field}.meaning")
        if fact_id in interaction_fact_ids:
            raise ContractError(
                "interaction_item_coverage",
                f"interaction fact {fact_id} is checked more than once",
            )
        if (
            fact_kinds_by_id.get(fact_id) != field
            or fact_evidence_classes.get(fact_id) != "business_source"
            or fact_meanings_by_id.get(fact_id) != meaning
            or source_key not in fact_source_keys.get(fact_id, set())
        ):
            raise ContractError(
                "interaction_item_coverage",
                f"{label}.{field} does not exactly match its source-backed fact",
            )
        interaction_fact_ids.add(fact_id)
        normalized_interaction_items.append(
            {**copy.deepcopy(item), "source_ref": source_ref}
        )
    expected_interaction_fact_ids = {
        fact_id
        for fact_id, kind in fact_kinds_by_id.items()
        if kind in INTERACTION_ITEM_FIELDS
        and fact_evidence_classes.get(fact_id) == "business_source"
        and any(
            clause_id == "page:interaction"
            for clause_id, _start, _end in fact_source_keys.get(fact_id, set())
        )
    }
    if interaction_fact_ids != expected_interaction_fact_ids:
        raise ContractError(
            "interaction_item_coverage",
            "interaction items and condition/state/trigger/behavior/result facts "
            "are not bidirectionally equal",
        )
    if interaction_text and interaction_item_source_keys != interaction_coverage_source_keys:
        raise ContractError(
            "interaction_item_coverage",
            "every interaction source segment must be checked by at least one atomic item",
        )

    interaction_graph = require_dict(
        facts.get("interaction_graph"), "page interaction_graph"
    )
    require_exact_keys(
        interaction_graph,
        {"schema", "interactions", "edges", "terminal_outcomes"},
        "page interaction_graph",
        code="invalid_interaction_graph",
    )
    if interaction_graph.get("schema") != "icp.component-design.interaction-graph.v2":
        raise ContractError(
            "invalid_interaction_graph", "page interaction graph schema is invalid"
        )
    normalized_graph_interactions: list[dict[str, Any]] = []
    graph_interaction_ids: set[str] = set()
    graph_fact_ids: set[str] = set()
    used_api_contract_ids: set[str] = set()
    for interaction_index, interaction_value in enumerate(
        require_list(interaction_graph.get("interactions"), "graph interactions")
    ):
        label = f"graph interactions[{interaction_index}]"
        interaction = require_dict(interaction_value, label)
        require_exact_keys(
            interaction,
            {"interaction_id", *INTERACTION_ITEM_FIELDS, "component_bindings"},
            label,
            code="invalid_interaction_graph",
        )
        interaction_id = require_string(
            interaction.get("interaction_id"), f"{label}.interaction_id"
        )
        if (
            not COMPONENT_ID_RE.fullmatch(interaction_id)
            or interaction_id in graph_interaction_ids
        ):
            raise ContractError(
                "invalid_interaction_graph",
                f"invalid or duplicate interaction {interaction_id}",
            )
        graph_interaction_ids.add(interaction_id)
        bindings = require_dict(
            interaction.get("component_bindings"), f"{label}.component_bindings"
        )
        expected_binding_keys = {
            f"{field}_candidate_ids" for field in INTERACTION_ITEM_FIELDS
        }
        require_exact_keys(
            bindings,
            expected_binding_keys,
            f"{label}.component_bindings",
            code="invalid_interaction_component_binding",
        )
        normalized_fields: dict[str, Any] = {}
        non_null_fields = 0
        for field in INTERACTION_ITEM_FIELDS:
            part_value = interaction.get(field)
            candidate_binding_ids = require_string_list(
                bindings.get(f"{field}_candidate_ids"),
                f"{label}.component_bindings.{field}_candidate_ids",
                nonempty=False,
            )
            if len(candidate_binding_ids) != len(set(candidate_binding_ids)) or any(
                candidate_id not in candidate_ids
                for candidate_id in candidate_binding_ids
            ):
                raise ContractError(
                    "invalid_interaction_component_binding",
                    f"{label}.{field} binds an unknown or duplicate candidate",
                )
            if part_value is None:
                if candidate_binding_ids:
                    raise ContractError(
                        "invalid_interaction_component_binding",
                        f"{label}.{field} is null but has component bindings",
                    )
                normalized_fields[field] = None
                continue
            non_null_fields += 1
            part = require_dict(part_value, f"{label}.{field}")
            expected_part_keys = {"fact_ids", "inference_basis"}
            if field == "behavior":
                expected_part_keys.update({"kind", "api_contract_id"})
            if field == "result":
                expected_part_keys.add("outcomes")
            require_exact_keys(
                part,
                expected_part_keys,
                f"{label}.{field}",
                code="invalid_interaction_graph",
            )
            part_fact_ids = require_string_list(
                part.get("fact_ids"), f"{label}.{field}.fact_ids", nonempty=False
            )
            inference_basis = require_string_list(
                part.get("inference_basis"),
                f"{label}.{field}.inference_basis",
                nonempty=False,
            )
            if not part_fact_ids and not inference_basis:
                raise ContractError(
                    "invalid_interaction_graph",
                    f"{label}.{field} needs source facts or an explicit inference basis",
                )
            if field == "result":
                part_outcomes = require_string_list(
                    part.get("outcomes"), f"{label}.result.outcomes"
                )
                if len(part_outcomes) != len(set(part_outcomes)):
                    raise ContractError(
                        "invalid_interaction_graph",
                        f"{label}.result.outcomes must be unique",
                    )
            if len(part_fact_ids) != len(set(part_fact_ids)) or any(
                fact_id in graph_fact_ids
                or fact_kinds_by_id.get(fact_id) != field
                for fact_id in part_fact_ids
            ):
                raise ContractError(
                    "interaction_graph_coverage",
                    f"{label}.{field} repeats, omits, or mistypes an interaction fact",
                )
            if not candidate_binding_ids or any(
                candidate_by_fact_id[fact_id] not in candidate_binding_ids
                for fact_id in part_fact_ids
            ):
                raise ContractError(
                    "invalid_interaction_component_binding",
                    f"{label}.{field} is not bound to every owning candidate",
                )
            graph_fact_ids.update(part_fact_ids)
            if field == "behavior":
                behavior_kind = require_string(
                    part.get("kind"), f"{label}.behavior.kind"
                )
                if behavior_kind not in INTERACTION_BEHAVIOR_KINDS:
                    raise ContractError(
                        "invalid_interaction_graph",
                        f"{label}.behavior.kind is invalid",
                    )
                api_contract_id = part.get("api_contract_id")
                if behavior_kind == "api_call":
                    api_contract_id = require_string(
                        api_contract_id, f"{label}.behavior.api_contract_id"
                    )
                    if api_contract_id not in api_contract_ids:
                        raise ContractError(
                            "api_contract_missing",
                            f"{label} references unknown API contract {api_contract_id}",
                        )
                    used_api_contract_ids.add(api_contract_id)
                elif api_contract_id is not None:
                    raise ContractError(
                        "invalid_interaction_graph",
                        f"{label} non-API behavior cannot bind an API contract",
                    )
            normalized_fields[field] = copy.deepcopy(part)
        if not non_null_fields:
            raise ContractError(
                "invalid_interaction_graph", f"{label} has no interaction meaning"
            )
        if (
            normalized_fields["trigger"] is not None
            and normalized_fields["behavior"] is None
        ):
            raise ContractError(
                "interaction_causality_missing",
                f"{label} trigger must keep its behavior in the same interaction",
            )
        if (
            normalized_fields["behavior"] is not None
            and normalized_fields["behavior"].get("kind") != "api_call"
            and normalized_fields["trigger"] is None
        ):
            raise ContractError(
                "interaction_causality_missing",
                f"{label} behavior must keep its trigger in the same interaction",
            )
        if (
            normalized_fields["behavior"] is not None
            and normalized_fields["behavior"].get("kind") == "api_call"
            and normalized_fields["trigger"] is None
        ):
            raise ContractError(
                "api_interaction_trigger_missing",
                f"{label} api_call must keep its trigger in the same interaction",
            )
        if (
            normalized_fields["behavior"] is not None
            and normalized_fields["result"] is None
        ):
            raise ContractError(
                "interaction_result_missing",
                f"{label} behavior must keep its result in the same interaction",
            )
        if (
            normalized_fields["result"] is not None
            and normalized_fields["behavior"] is None
        ):
            raise ContractError(
                "interaction_causality_missing",
                f"{label} result must keep its behavior in the same interaction",
            )
        normalized_graph_interactions.append(
            {
                "interaction_id": interaction_id,
                **normalized_fields,
                "component_bindings": copy.deepcopy(bindings),
            }
        )
    normalized_graph_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, bytes]] = set()
    graph_interaction_by_id = {
        interaction["interaction_id"]: interaction
        for interaction in normalized_graph_interactions
    }
    catalog_design_order = set(catalog_maps(catalog)["design_order"])
    members_by_title = {
        require_string(member.get("title"), "business member title"): member
        for member_value in require_list(
            business_context.get("members"), "business context members"
        )
        for member in [require_dict(member_value, "business context member")]
    }
    navigation_requirements_by_id = {
        requirement["navigation_requirement_id"]: requirement
        for requirement in expected_navigation_requirements
    }
    modal_requirements_by_id = {
        requirement["presentation_requirement_id"]: requirement
        for requirement in expected_presentation_requirements
        if requirement["relation_kind"] == "modal"
    }
    for edge_index, edge_value in enumerate(
        require_list(interaction_graph.get("edges"), "graph edges")
    ):
        label = f"graph edges[{edge_index}]"
        edge = require_dict(edge_value, label)
        require_exact_keys(
            edge,
            {"from_interaction_id", "outcome", "target"},
            label,
            code="invalid_interaction_graph",
        )
        from_id = require_string(
            edge.get("from_interaction_id"), f"{label}.from_interaction_id"
        )
        outcome = require_string(edge.get("outcome"), f"{label}.outcome")
        target = require_dict(edge.get("target"), f"{label}.target")
        target_kind = target.get("kind")
        if target_kind == "interaction":
            require_exact_keys(
                target,
                {"kind", "to_interaction_id"},
                f"{label}.target",
                code="invalid_interaction_edge_target",
            )
            to_id = require_string(
                target.get("to_interaction_id"), f"{label}.target.to_interaction_id"
            )
            if (
                from_id not in graph_interaction_ids
                or to_id not in graph_interaction_ids
                or from_id == to_id
            ):
                raise ContractError(
                    "invalid_interaction_graph", f"{label} has invalid endpoints"
                )
            if graph_interaction_by_id[to_id]["trigger"] is None:
                raise ContractError(
                    "invalid_interaction_edge_causality",
                    f"{label} must connect a behavior outcome to a triggered interaction",
                )
            normalized_target: dict[str, Any] = {
                "kind": "interaction",
                "to_interaction_id": to_id,
            }
        elif target_kind in {"navigation", "modal"}:
            require_exact_keys(
                target,
                {"kind", "page_key", "design_name", "requirement_ids"},
                f"{label}.target",
                code="invalid_interaction_edge_target",
            )
            target_page_key = require_string(
                target.get("page_key"), f"{label}.target.page_key"
            )
            target_design_name = require_string(
                target.get("design_name"), f"{label}.target.design_name"
            )
            requirement_ids = require_string_list(
                target.get("requirement_ids"),
                f"{label}.target.requirement_ids",
                nonempty=False,
            )
            allowed_requirements = (
                navigation_requirements_by_id
                if target_kind == "navigation"
                else modal_requirements_by_id
            )
            if len(requirement_ids) != len(set(requirement_ids)):
                raise ContractError(
                    "invalid_interaction_edge_target",
                    f"{label}.target cites one relation reference twice",
                )
            target_member_title: str | None = None
            for requirement_id in requirement_ids:
                requirement = allowed_requirements.get(requirement_id)
                if requirement is None or requirement["target_page_key"] != target_page_key:
                    raise ContractError(
                        "invalid_interaction_edge_target",
                        f"{label} does not cite exact {target_kind} relation evidence",
                    )
                target_member_title = requirement["target_member_title"]
            if target_page_key != page_key and not requirement_ids:
                raise ContractError(
                    "invalid_interaction_edge_target",
                    f"{label} cross-page target needs exact source relation evidence",
                )
            if target_member_title is None:
                target_member = next(
                    (
                        member
                        for member in members_by_title.values()
                        if page_key_for(
                            require_string(member.get("title"), "business member title")
                        )
                        == target_page_key
                    ),
                    None,
                )
            else:
                target_member = members_by_title.get(target_member_title)
            if target_member is None or not member_requires_semantic_work_item(
                target_member
            ):
                raise ContractError(
                    "invalid_interaction_edge_target",
                    f"{label} target page is not a frozen component page",
                )
            target_design_names = [
                require_string(state.get("design_name"), "design state name")
                for state in require_list(
                    target_member.get("design_states"), "design states"
                )
            ]
            if (
                target_design_name not in target_design_names
                or target_design_name not in catalog_design_order
            ):
                raise ContractError(
                    "invalid_interaction_edge_target",
                    f"{label} target design is not in the frozen source catalog",
                )
            normalized_target = {
                "kind": target_kind,
                "page_key": target_page_key,
                "design_name": target_design_name,
                "requirement_ids": list(requirement_ids),
            }
        else:
            raise ContractError(
                "invalid_interaction_edge_target",
                f"{label}.target.kind is invalid",
            )
        if from_id not in graph_interaction_ids:
            raise ContractError(
                "invalid_interaction_graph", f"{label} has invalid endpoints"
            )
        if graph_interaction_by_id[from_id]["behavior"] is None:
            raise ContractError(
                "invalid_interaction_edge_causality",
                f"{label} must start from a behavior result",
            )
        edge_key = (from_id, outcome, canonical_bytes(normalized_target))
        if edge_key in seen_edges:
            raise ContractError(
                "invalid_interaction_graph", f"{label} has invalid endpoints"
            )
        seen_edges.add(edge_key)
        normalized_graph_edges.append(
            {
                "from_interaction_id": from_id,
                "outcome": outcome,
                "target": normalized_target,
            }
        )
    terminal_outcomes: list[dict[str, Any]] = []
    seen_terminal_outcomes: set[tuple[str, str]] = set()
    for terminal_index, terminal_value in enumerate(
        require_list(
            interaction_graph.get("terminal_outcomes"), "graph terminal outcomes"
        )
    ):
        label = f"graph terminal_outcomes[{terminal_index}]"
        terminal = require_dict(terminal_value, label)
        require_exact_keys(
            terminal,
            {"interaction_id", "outcome", "inference_basis"},
            label,
            code="invalid_interaction_graph",
        )
        interaction_id = require_string(
            terminal.get("interaction_id"), f"{label}.interaction_id"
        )
        outcome = require_string(terminal.get("outcome"), f"{label}.outcome")
        inference_basis = require_string_list(
            terminal.get("inference_basis"), f"{label}.inference_basis"
        )
        key = (interaction_id, outcome)
        terminal_interaction = graph_interaction_by_id.get(interaction_id)
        terminal_result = (
            terminal_interaction["result"] if terminal_interaction is not None else None
        )
        if (
            terminal_interaction is None
            or terminal_interaction["behavior"] is None
            or terminal_result is None
            or outcome not in terminal_result["outcomes"]
            or key in seen_terminal_outcomes
            or any(
                edge["from_interaction_id"] == interaction_id
                and edge["outcome"] == outcome
                for edge in normalized_graph_edges
            )
        ):
            raise ContractError(
                "invalid_interaction_terminal_outcome",
                f"{label} must uniquely terminate one declared result outcome",
            )
        seen_terminal_outcomes.add(key)
        terminal_outcomes.append(
            {
                "interaction_id": interaction_id,
                "outcome": outcome,
                "inference_basis": inference_basis,
            }
        )
    outgoing_outcomes = {
        interaction_id: {
            edge["outcome"]
            for edge in normalized_graph_edges
            if edge["from_interaction_id"] == interaction_id
        }
        | {
            terminal["outcome"]
            for terminal in terminal_outcomes
            if terminal["interaction_id"] == interaction_id
        }
        for interaction_id in graph_interaction_ids
    }
    for interaction in normalized_graph_interactions:
        behavior = interaction["behavior"]
        if behavior is None or behavior.get("kind") != "api_call":
            continue
        missing_outcomes = {"success", "failure"} - (
            set(interaction["result"]["outcomes"])
            | outgoing_outcomes[interaction["interaction_id"]]
        )
        missing_resolutions = {"success", "failure"} - outgoing_outcomes[
            interaction["interaction_id"]
        ]
        if missing_outcomes or missing_resolutions:
            raise ContractError(
                "api_interaction_outcome_missing",
                "api_call must resolve success and failure outcomes; "
                f"interaction={interaction['interaction_id']} "
                f"missing={sorted(missing_outcomes | missing_resolutions)}",
            )
    for interaction in normalized_graph_interactions:
        if interaction["behavior"] is None:
            continue
        result_outcomes = interaction["result"]["outcomes"]
        resolutions = {outcome: 0 for outcome in result_outcomes}
        for edge in normalized_graph_edges:
            if edge["from_interaction_id"] != interaction["interaction_id"]:
                continue
            if edge["outcome"] not in resolutions:
                raise ContractError(
                    "interaction_result_outcome_unresolved",
                    "graph edges must resolve declared result outcomes; "
                    f"interaction={interaction['interaction_id']} "
                    f"outcome={edge['outcome']}",
                )
            resolutions[edge["outcome"]] += 1
        for terminal in terminal_outcomes:
            if terminal["interaction_id"] != interaction["interaction_id"]:
                continue
            resolutions[terminal["outcome"]] += 1
        unresolved = sorted(
            outcome for outcome, count in resolutions.items() if count != 1
        )
        if unresolved:
            raise ContractError(
                "interaction_result_outcome_unresolved",
                "every declared result outcome needs exactly one edge or terminal "
                "resolution; "
                f"interaction={interaction['interaction_id']} "
                f"unresolved={unresolved}",
            )
    if graph_fact_ids != expected_interaction_fact_ids:
        missing = sorted(expected_interaction_fact_ids - graph_fact_ids)
        unexpected = sorted(graph_fact_ids - expected_interaction_fact_ids)
        raise ContractError(
            "interaction_graph_coverage",
            "interaction graph must bind every atomic interaction fact exactly once; "
            f"missing={missing} unexpected={unexpected}",
        )
    # Audit closure: every exact navigation/modal transition requirement from
    # the verified IOLE source analysis is consumed exactly once by one
    # external graph edge, and each cited reference span is contained by a
    # source-backed result fact on the interaction that emits the edge.
    transition_requirements: dict[str, dict[str, Any]] = {
        requirement["navigation_requirement_id"]: requirement
        for requirement in expected_navigation_requirements
    }
    transition_requirements.update(
        {
            requirement["presentation_requirement_id"]: requirement
            for requirement in expected_presentation_requirements
            if requirement["relation_kind"] == "modal"
        }
    )
    requirement_consumers: dict[str, list[str]] = {}
    for edge in normalized_graph_edges:
        if edge["target"]["kind"] not in {"navigation", "modal"}:
            continue
        for requirement_id in edge["target"]["requirement_ids"]:
            requirement_consumers.setdefault(requirement_id, []).append(
                edge["from_interaction_id"]
            )
    missing_requirements = sorted(
        requirement_id
        for requirement_id in transition_requirements
        if requirement_id not in requirement_consumers
    )
    if missing_requirements:
        raise ContractError(
            "interaction_transition_evidence_missing",
            "every exact navigation/modal transition requirement needs one "
            "external graph edge; "
            f"missing={missing_requirements}",
        )
    duplicate_requirements = sorted(
        requirement_id
        for requirement_id, consumers in requirement_consumers.items()
        if len(consumers) > 1
    )
    if duplicate_requirements:
        raise ContractError(
            "interaction_transition_evidence_duplicate",
            "one exact transition requirement cannot support multiple edges; "
            f"duplicates={duplicate_requirements}",
        )
    for edge in normalized_graph_edges:
        if edge["target"]["kind"] not in {"navigation", "modal"}:
            continue
        source_result = graph_interaction_by_id[edge["from_interaction_id"]]["result"]
        for requirement_id in edge["target"]["requirement_ids"]:
            requirement_source_ref = transition_requirements[requirement_id][
                "source_ref"
            ]
            if not any(
                clause_id == requirement_source_ref["clause_id"]
                and start <= requirement_source_ref["start"]
                and end >= requirement_source_ref["end"]
                for fact_id in source_result["fact_ids"]
                for clause_id, start, end in fact_source_keys.get(fact_id, set())
            ):
                raise ContractError(
                    "interaction_transition_evidence_unbound",
                    "a transition reference is not contained by a source-backed "
                    "result fact of its emitting interaction; "
                    f"requirement={requirement_id} "
                    f"interaction={edge['from_interaction_id']}",
                )
    normalized_interaction_graph = {
        "schema": "icp.component-design.interaction-graph.v2",
        "interactions": normalized_graph_interactions,
        "edges": normalized_graph_edges,
        "terminal_outcomes": terminal_outcomes,
    }
    covered_api_requirement_ids: list[str] = [
        requirement_id
        for contract in normalized_api_contracts
        for requirement_id in contract["requirement_ids"]
    ]
    if (
        len(covered_api_requirement_ids) != len(set(covered_api_requirement_ids))
        or set(covered_api_requirement_ids) != api_requirement_ids
    ):
        raise ContractError(
            "api_contract_coverage",
            "every same-page API requirement needs exactly one frozen Apifox contract; "
            f"missing={sorted(api_requirement_ids - set(covered_api_requirement_ids))} "
            "duplicates="
            + str(
                sorted(
                    {
                        requirement_id
                        for requirement_id in covered_api_requirement_ids
                        if covered_api_requirement_ids.count(requirement_id) > 1
                    }
                )
            ),
        )
    if used_api_contract_ids != api_contract_ids:
        raise ContractError(
            "api_interaction_coverage",
            "every frozen API contract must belong to an api_call interaction; "
            f"unused={sorted(api_contract_ids - used_api_contract_ids)}",
        )

    maps = catalog_maps(catalog)
    expected_blocks = {
        (design_name, block_id)
        for design_name in design_names
        for block_id in maps["design_blocks"][design_name]
    }
    if len(owned_block_refs) != len(set(owned_block_refs)) or set(owned_block_refs) != expected_blocks:
        raise ContractError("semantic_block_coverage", "page Blocks need exactly one candidate owner")

    compositions = require_list(facts.get("design_compositions"), "design compositions")
    if [item.get("design_name") for item in compositions if isinstance(item, dict)] != design_names:
        raise ContractError("composition_coverage", "page design composition order is incomplete")
    normalized_compositions: list[dict[str, Any]] = []
    for composition_index, composition_value in enumerate(compositions):
        label = f"design compositions[{composition_index}]"
        composition = require_dict(composition_value, label)
        require_exact_keys(composition, {"design_name", "root_instance_id", "instances"}, label)
        design_name = require_string(composition.get("design_name"), f"{label}.design_name")
        root_instance_id = require_string(composition.get("root_instance_id"), f"{label}.root_instance_id")
        instances = require_list(composition.get("instances"), f"{label}.instances")
        instance_map: dict[str, dict[str, Any]] = {}
        block_instance: dict[str, str] = {}
        composition_blocks: list[str] = []
        for instance_index, instance_value in enumerate(instances):
            instance_label = f"{label}.instances[{instance_index}]"
            instance = require_dict(instance_value, instance_label)
            require_exact_keys(
                instance,
                {"instance_id", "candidate_id", "parent_instance_id", "slot", "source_block_ids"},
                instance_label,
            )
            instance_id = require_string(instance.get("instance_id"), f"{instance_label}.instance_id")
            if instance_id in instance_map:
                raise ContractError("composition_not_tree", f"duplicate instance {instance_id}")
            if instance.get("candidate_id") not in candidate_ids:
                raise ContractError("composition_not_tree", f"unknown candidate on {instance_id}")
            parent_id = instance.get("parent_instance_id")
            if parent_id is not None:
                require_string(parent_id, f"{instance_label}.parent_instance_id")
            require_string(instance.get("slot"), f"{instance_label}.slot")
            block_ids = require_string_list(instance.get("source_block_ids"), f"{instance_label}.source_block_ids")
            if any(block_id not in maps["design_blocks"][design_name] for block_id in block_ids):
                raise ContractError("composition_not_tree", f"unknown Block on {instance_id}")
            candidate_id = require_string(
                instance.get("candidate_id"), f"{instance_label}.candidate_id"
            )
            if any(
                (design_name, block_id) not in candidate_block_refs[candidate_id]
                for block_id in block_ids
            ):
                raise ContractError(
                    "semantic_hierarchy_mismatch",
                    f"{instance_id} uses a Block outside candidate {candidate_id}",
                )
            composition_blocks.extend(block_ids)
            for block_id in block_ids:
                block_instance[block_id] = instance_id
            instance_map[instance_id] = copy.deepcopy(instance)
        if root_instance_id not in instance_map or instance_map[root_instance_id]["parent_instance_id"] is not None:
            raise ContractError("composition_not_tree", f"{label} root is invalid")
        for instance_id, instance in instance_map.items():
            if instance_id != root_instance_id and instance["parent_instance_id"] not in instance_map:
                raise ContractError("composition_not_tree", f"{instance_id} has no parent")
            seen: set[str] = set()
            cursor = instance_id
            while cursor != root_instance_id:
                if cursor in seen:
                    raise ContractError("composition_not_tree", f"cycle at {cursor}")
                seen.add(cursor)
                parent = instance_map[cursor]["parent_instance_id"]
                if parent is None or parent not in instance_map:
                    raise ContractError("composition_not_tree", f"{cursor} is not root-reachable")
                cursor = parent
        root_block_id = maps["root_blocks"][design_name]
        if block_instance.get(root_block_id) != root_instance_id:
            raise ContractError(
                "semantic_hierarchy_mismatch",
                f"{design_name} composition root does not own the root Block",
            )
        for block_id, instance_id in block_instance.items():
            parent_block_id = maps["semantic_parent"].get((design_name, block_id))
            if parent_block_id is None:
                if block_id != root_block_id:
                    raise ContractError(
                        "semantic_hierarchy_mismatch",
                        f"{design_name}/{block_id} has no verified semantic parent",
                    )
                continue
            parent_instance_id = block_instance.get(parent_block_id)
            if parent_instance_id is None:
                raise ContractError(
                    "semantic_hierarchy_mismatch",
                    f"{design_name}/{block_id} has an unknown semantic parent",
                )
            if (
                parent_instance_id != instance_id
                and instance_map[instance_id]["parent_instance_id"]
                != parent_instance_id
            ):
                raise ContractError(
                    "semantic_hierarchy_mismatch",
                    f"{design_name}/{block_id} contradicts its verified semantic parent",
                )
        expected_design_blocks = maps["design_blocks"][design_name]
        if len(composition_blocks) != len(set(composition_blocks)) or set(composition_blocks) != expected_design_blocks:
            raise ContractError("composition_coverage", f"{design_name} Blocks need exactly one instance owner")
        normalized_compositions.append(copy.deepcopy(composition))
    return {
        **copy.deepcopy(facts),
        "source_coverage": normalized_coverage,
        "interaction_items": normalized_interaction_items,
        "interaction_graph": normalized_interaction_graph,
        "api_contracts": normalized_api_contracts,
        "candidates": normalized_candidates,
        "design_compositions": normalized_compositions,
    }


def build_page_review_input(page_facts: dict[str, Any]) -> dict[str, Any]:
    fact_index: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    candidate_projection: list[dict[str, Any]] = []
    for candidate_value in require_list(
        page_facts.get("candidates"), "page facts candidates"
    ):
        candidate = require_dict(candidate_value, "page facts candidate")
        visible_facts: list[dict[str, Any]] = []
        fact_ids: list[str] = []
        for fact_value in require_list(candidate.get("facts"), "candidate facts"):
            fact = require_dict(fact_value, "candidate fact")
            fact_id = require_string(fact.get("fact_id"), "fact_id")
            fact_index[fact_id] = (candidate, fact)
            fact_ids.append(fact_id)
            if fact.get("evidence_class") == "design_visible":
                visible_facts.append(
                    {
                        "fact_id": fact_id,
                        "kind": fact["kind"],
                        "meaning": fact["meaning"],
                        "visible_basis": fact["visible_basis"],
                        "block_refs": copy.deepcopy(fact["block_refs"]),
                    }
                )
        candidate_projection.append(
            {
                "candidate_id": candidate["candidate_id"],
                "name": candidate["name"],
                "kind": candidate["kind"],
                "responsibility": candidate["responsibility"],
                "owns": copy.deepcopy(candidate["owns"]),
                "excludes": copy.deepcopy(candidate["excludes"]),
                "source_block_refs": copy.deepcopy(candidate["source_block_refs"]),
                "fact_ids": fact_ids,
                "design_visible_facts": visible_facts,
            }
        )

    segment_reviews: list[dict[str, Any]] = []
    for coverage_value in require_list(
        page_facts.get("source_coverage"), "page source coverage"
    ):
        coverage = require_dict(coverage_value, "page source coverage entry")
        for segment_value in require_list(
            coverage.get("segments"), "page source coverage segments"
        ):
            segment = require_dict(segment_value, "page source coverage segment")
            if segment.get("disposition") != "fact":
                continue
            linked_facts: list[dict[str, Any]] = []
            quote = require_text(segment.get("quote"), "source segment quote")
            normalized_quote = quote.strip()
            for fact_id in require_string_list(
                segment.get("fact_ids"), "source segment fact_ids"
            ):
                candidate, fact = fact_index[fact_id]
                meaning = require_string(fact.get("meaning"), "fact meaning")
                normalized_meaning = meaning.strip()
                linked_fact = {
                    "fact_id": fact_id,
                    "kind": fact["kind"],
                    "meaning": meaning,
                    "candidate_id": candidate["candidate_id"],
                    "block_refs": copy.deepcopy(fact["block_refs"]),
                    "verbatim_restatement_signal": bool(normalized_quote)
                    and (
                        normalized_quote in normalized_meaning
                        or normalized_meaning in normalized_quote
                    ),
                }
                if fact.get("kind") == "component_relation":
                    linked_fact["relation_intent"] = fact["relation_intent"]
                    linked_fact["relation_target"] = copy.deepcopy(
                        fact["relation_target"]
                    )
                linked_facts.append(linked_fact)
            segment_reviews.append(
                {
                    "segment_id": (
                        f"{coverage['clause_id']}:{segment['start']}:{segment['end']}"
                    ),
                    "clause_id": coverage["clause_id"],
                    "source_sha256": coverage["source_sha256"],
                    "start": segment["start"],
                    "end": segment["end"],
                    "quote": quote,
                    "linked_facts": linked_facts,
                    "all_normative_meanings_extracted": False,
                    "facts_atomic": False,
                    "fact_kinds_correct": False,
                    "same_page_scope_correct": False,
                    "component_relation_intents_correct": False,
                    "evidence": [
                        "TODO: compare every independent meaning in this exact source segment with the linked facts."
                    ],
                    "issues": ["TODO: review this source segment."],
                }
            )

    draft_sha = sha256_bytes(json_bytes(page_facts))
    return {
        "schema": "icp.component-design.page-review.v3",
        "page_key": page_facts["page_key"],
        "member_title": page_facts["member_title"],
        "page_facts_draft_sha256": draft_sha,
        "source_catalog_sha256": page_facts["source_catalog_sha256"],
        "business_context_sha256": page_facts["business_context_sha256"],
        "mobile_component_pattern_context": copy.deepcopy(
            page_facts["mobile_component_pattern_context"]
        ),
        "candidate_projection": candidate_projection,
        "presentation_requirements": copy.deepcopy(
            page_facts["presentation_requirements"]
        ),
        "navigation_requirements": copy.deepcopy(
            page_facts["navigation_requirements"]
        ),
        "api_requirements": copy.deepcopy(page_facts["api_requirements"]),
        "api_contracts": copy.deepcopy(page_facts["api_contracts"]),
        "interaction_items": copy.deepcopy(page_facts["interaction_items"]),
        "interaction_graph": copy.deepcopy(page_facts["interaction_graph"]),
        "segment_reviews": segment_reviews,
        "cross_page_review": {
            "candidate_boundaries_complete": False,
            "design_visible_facts_limited_to_visible_semantics": False,
            "all_visible_variation_roles_extracted": False,
            "no_cross_page_semantic_leak": False,
            "no_implementation_content": False,
            "interaction_graph_complete": False,
            "interaction_component_bindings_correct": False,
            "api_contracts_correct": False,
            "evidence": [
                "TODO: cite the page-local candidates, facts, Blocks, and source scope."
            ],
            "issues": ["TODO: review page-level semantic boundaries."],
        },
        "decision": "revise",
    }


def reject_page_review_placeholders(values: list[str], label: str) -> None:
    for index, value in enumerate(values):
        normalized = value.strip().upper()
        if normalized.startswith("TODO") or normalized.startswith("__"):
            raise ContractError(
                "placeholder_page_review_evidence",
                f"{label}[{index}] still contains placeholder text",
            )


def validate_page_review(
    value: object,
    page_facts: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    review = require_dict(value, "page review")
    expected = build_page_review_input(page_facts)
    require_exact_keys(
        review,
        {
            "schema",
            "page_key",
            "member_title",
            "page_facts_draft_sha256",
            "source_catalog_sha256",
            "business_context_sha256",
            "mobile_component_pattern_context",
            "candidate_projection",
            "presentation_requirements",
            "navigation_requirements",
            "api_requirements",
            "api_contracts",
            "interaction_items",
            "interaction_graph",
            "segment_reviews",
            "cross_page_review",
            "decision",
        },
        "page review",
    )
    for field in (
        "schema",
        "page_key",
        "member_title",
        "page_facts_draft_sha256",
        "source_catalog_sha256",
        "business_context_sha256",
        "mobile_component_pattern_context",
        "candidate_projection",
        "presentation_requirements",
        "navigation_requirements",
        "api_requirements",
        "api_contracts",
        "interaction_items",
        "interaction_graph",
    ):
        if review.get(field) != expected.get(field):
            raise ContractError(
                "review_input_mismatch", f"page review {field} is stale or changed"
            )
    if review.get("decision") not in {"pass", "revise"}:
        raise ContractError("invalid_page_review", "decision must be pass or revise")

    actual_segments = require_list(
        review.get("segment_reviews"), "page review segment_reviews"
    )
    expected_segments = expected["segment_reviews"]
    if len(actual_segments) != len(expected_segments):
        raise ContractError(
            "invalid_page_review", "every source fact segment must be reviewed exactly once"
        )
    flags: list[bool] = []
    issues: list[str] = []
    segment_projection_fields = (
        "segment_id",
        "clause_id",
        "source_sha256",
        "start",
        "end",
        "quote",
        "linked_facts",
    )
    segment_flag_fields = (
        "all_normative_meanings_extracted",
        "facts_atomic",
        "fact_kinds_correct",
        "same_page_scope_correct",
        "component_relation_intents_correct",
    )
    segment_keys = set(segment_projection_fields) | set(segment_flag_fields) | {
        "evidence",
        "issues",
    }
    for index, (actual_value, expected_segment) in enumerate(
        zip(actual_segments, expected_segments, strict=True)
    ):
        label = f"page review segment_reviews[{index}]"
        actual = require_dict(actual_value, label)
        require_exact_keys(actual, segment_keys, label)
        if any(
            actual.get(field) != expected_segment.get(field)
            for field in segment_projection_fields
        ):
            raise ContractError(
                "review_input_mismatch", f"{label} projection is stale or changed"
            )
        for field in segment_flag_fields:
            if type(actual.get(field)) is not bool:
                raise ContractError(
                    "invalid_page_review", f"{label}.{field} must be boolean"
                )
            flags.append(actual[field])
        evidence = require_string_list(actual.get("evidence"), f"{label}.evidence")
        segment_issues = require_string_list(
            actual.get("issues"), f"{label}.issues", nonempty=False
        )
        reject_page_review_placeholders(evidence, f"{label}.evidence")
        reject_page_review_placeholders(segment_issues, f"{label}.issues")
        issues.extend(segment_issues)

    cross = require_dict(review.get("cross_page_review"), "cross_page_review")
    cross_flag_fields = (
        "candidate_boundaries_complete",
        "design_visible_facts_limited_to_visible_semantics",
        "all_visible_variation_roles_extracted",
        "no_cross_page_semantic_leak",
        "no_implementation_content",
        "interaction_graph_complete",
        "interaction_component_bindings_correct",
        "api_contracts_correct",
    )
    require_exact_keys(
        cross, set(cross_flag_fields) | {"evidence", "issues"}, "cross_page_review"
    )
    for field in cross_flag_fields:
        if type(cross.get(field)) is not bool:
            raise ContractError(
                "invalid_page_review", f"cross_page_review.{field} must be boolean"
            )
        flags.append(cross[field])
    cross_evidence = require_string_list(
        cross.get("evidence"), "cross_page_review.evidence"
    )
    cross_issues = require_string_list(
        cross.get("issues"), "cross_page_review.issues", nonempty=False
    )
    reject_page_review_placeholders(cross_evidence, "cross_page_review.evidence")
    reject_page_review_placeholders(cross_issues, "cross_page_review.issues")
    issues.extend(cross_issues)

    evidence_passes = all(flags) and not issues
    if review["decision"] == "pass" and not evidence_passes:
        raise ContractError(
            "false_page_review_pass",
            "pass decision contradicts failed semantic checks or reported issues",
        )
    if review["decision"] == "revise" and evidence_passes:
        raise ContractError(
            "invalid_page_review", "revise decision requires a failed check or issue"
        )
    return copy.deepcopy(review), evidence_passes


def materialize_group_registry(
    stage_dir: Path, state: dict[str, Any], *, write: bool = True
) -> tuple[dict[str, Any], str]:
    mobile_pattern_context = verify_live_mobile_component_pattern_context(
        stage_dir, state
    )
    pages: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for page_key, page_state_value in sorted(
        require_dict(state.get("pages"), "page states").items()
    ):
        page_state = require_dict(page_state_value, "page state")
        page_path = stage_dir / "page-component-facts" / f"{page_key}.json"
        review_path = (
            stage_dir / "page-component-facts" / f"{page_key}.review.json"
        )
        if (
            page_state.get("status") != "sealed"
            or not page_path.is_file()
            or not review_path.is_file()
        ):
            raise ContractError("page_facts_incomplete", "all pages must be sealed first")
        page_sha = sha256_bytes(page_path.read_bytes())
        review_sha = sha256_bytes(review_path.read_bytes())
        if page_state.get("sha256") != page_sha:
            raise ContractError("stage_drift", f"sealed page facts changed: {page_key}")
        if page_state.get("review_sha256") != review_sha:
            raise ContractError("stage_drift", f"sealed page review changed: {page_key}")
        page = require_dict(read_json(page_path), "sealed page facts")
        review, evidence_passes = validate_page_review(read_json(review_path), page)
        if not evidence_passes or review.get("decision") != "pass":
            raise ContractError("page_facts_incomplete", f"page review does not pass: {page_key}")
        candidate_ids: list[str] = []
        for candidate_value in require_list(page.get("candidates"), "page candidates"):
            candidate = require_dict(candidate_value, "page candidate")
            candidate_id = require_string(candidate.get("candidate_id"), "candidate_id")
            candidate_ids.append(candidate_id)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "page_key": page_key,
                    "member_title": page_state.get("member_title"),
                    "page_facts_sha256": page_sha,
                    "candidate": copy.deepcopy(candidate),
                }
            )
        root_candidate_ids: list[str] = []
        for composition_value in require_list(
            page.get("design_compositions"), "page design compositions"
        ):
            composition = require_dict(
                composition_value, "page design composition"
            )
            root_instance_id = require_string(
                composition.get("root_instance_id"), "root design instance ID"
            )
            root_instance = next(
                (
                    require_dict(value, "page design instance")
                    for value in require_list(
                        composition.get("instances"), "page design instances"
                    )
                    if require_dict(value, "page design instance").get("instance_id")
                    == root_instance_id
                ),
                None,
            )
            if root_instance is None:
                raise ContractError(
                    "composition_not_tree",
                    f"page composition has no root instance: {page_key}",
                )
            root_candidate_ids.append(
                require_string(
                    root_instance.get("candidate_id"), "root candidate ID"
                )
            )
        pages.append(
            {
                "page_key": page_key,
                "member_title": page_state.get("member_title"),
                "page_facts_sha256": page_sha,
                "page_review_sha256": review_sha,
                "candidate_ids": sorted(candidate_ids),
                "root_candidate_ids": root_candidate_ids,
                "presentation_requirements": copy.deepcopy(
                    page["presentation_requirements"]
                ),
            }
        )
    candidates.sort(key=lambda item: item["candidate_id"])
    candidate_ids = [item["candidate_id"] for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ContractError("duplicate_candidate", "candidate IDs must be group-unique")
    registry = {
        "schema": "icp.component-design.group-candidate-registry.v1",
        "source_catalog_sha256": state["source_catalog_sha256"],
        "business_context_sha256": state["business_context_sha256"],
        "project_catalog_snapshot_sha256": state["project_catalog_snapshot_sha256"],
        "pages": pages,
        "candidates": candidates,
    }
    registry_sha = sha256_bytes(json_bytes(registry))
    plan = {
        "schema": "icp.component-design.abstraction-plan.v1",
        "source_catalog_sha256": state["source_catalog_sha256"],
        "business_context_sha256": state["business_context_sha256"],
        "project_catalog_snapshot_sha256": state["project_catalog_snapshot_sha256"],
        "candidate_registry_sha256": registry_sha,
        "mobile_component_pattern_context": mobile_pattern_context,
        "decisions": [],
        "component_definitions": [],
        "component_instances": [],
        "presentation_usages": [],
    }
    if write:
        atomic_write_json(stage_dir / "group-candidate-registry.json", registry)
        atomic_write_json(stage_dir / "abstraction-plan.input.json", plan)
    return registry, registry_sha


def verify_live_group_registry(
    stage_dir: Path, state: dict[str, Any]
) -> dict[str, Any]:
    registry_path = stage_dir / "group-candidate-registry.json"
    if not registry_path.is_file():
        raise ContractError("page_facts_incomplete", "group candidate registry is missing")
    if sha256_bytes(registry_path.read_bytes()) != state.get("candidate_registry_sha256"):
        raise ContractError("stage_drift", "group candidate registry changed")
    actual = require_dict(read_json(registry_path), "group candidate registry")
    expected, expected_sha = materialize_group_registry(stage_dir, state, write=False)
    if (
        actual != expected
        or expected_sha != state.get("candidate_registry_sha256")
    ):
        raise ContractError("stage_drift", "sealed page facts no longer match the registry")
    return expected


def validate_component_definition(value: object, label: str) -> dict[str, Any]:
    definition = require_dict(value, label)
    require_exact_keys(
        definition,
        {
            "component_id",
            "name",
            "kind",
            "scope",
            "reuse_mode",
            "responsibility",
            "owns",
            "excludes",
            "capabilities",
            "slots",
            "data_roles",
            "action_roles",
        },
        label,
    )
    component_id = require_string(definition.get("component_id"), f"{label}.component_id")
    if not COMPONENT_ID_RE.fullmatch(component_id):
        raise ContractError("invalid_component_definition", f"invalid component ID {component_id}")
    require_string(definition.get("name"), f"{label}.name")
    kind = require_string(definition.get("kind"), f"{label}.kind")
    if kind not in PAGE_CANDIDATE_KINDS:
        raise ContractError("invalid_component_definition", f"invalid component kind {kind}")
    scope = require_string(definition.get("scope"), f"{label}.scope")
    reuse_mode = require_string(definition.get("reuse_mode"), f"{label}.reuse_mode")
    if scope not in COMPONENT_SCOPES or reuse_mode not in REUSE_MODES:
        raise ContractError("invalid_reuse_mode", f"invalid scope or reuse mode on {component_id}")
    if (scope == "local") != (reuse_mode == "local"):
        raise ContractError("invalid_reuse_mode", f"scope and reuse mode disagree on {component_id}")
    require_string(definition.get("responsibility"), f"{label}.responsibility")
    require_string_list(definition.get("owns"), f"{label}.owns")
    require_string_list(definition.get("excludes"), f"{label}.excludes")

    capabilities: list[dict[str, Any]] = []
    capability_ids: set[str] = set()
    for index, capability_value in enumerate(
        require_list(definition.get("capabilities"), f"{label}.capabilities")
    ):
        capability_label = f"{label}.capabilities[{index}]"
        capability = require_dict(capability_value, capability_label)
        require_exact_keys(
            capability, {"capability_id", "kind", "meaning"}, capability_label
        )
        capability_id = require_string(
            capability.get("capability_id"), f"{capability_label}.capability_id"
        )
        if not COMPONENT_ID_RE.fullmatch(capability_id) or capability_id in capability_ids:
            raise ContractError("invalid_component_definition", f"invalid capability {capability_id}")
        capability_ids.add(capability_id)
        capability_kind = require_string(capability.get("kind"), f"{capability_label}.kind")
        if capability_kind not in PAGE_FACT_KINDS:
            raise ContractError("invalid_component_definition", f"invalid capability kind {capability_kind}")
        require_string(capability.get("meaning"), f"{capability_label}.meaning")
        capabilities.append(copy.deepcopy(capability))

    slots: list[dict[str, Any]] = []
    slot_ids: set[str] = set()
    for index, slot_value in enumerate(require_list(definition.get("slots"), f"{label}.slots")):
        slot_label = f"{label}.slots[{index}]"
        slot = require_dict(slot_value, slot_label)
        require_exact_keys(slot, {"slot_id", "role", "cardinality"}, slot_label)
        slot_id = require_string(slot.get("slot_id"), f"{slot_label}.slot_id")
        if (
            not COMPONENT_ID_RE.fullmatch(slot_id)
            or slot_id == "root"
            or slot_id in slot_ids
        ):
            raise ContractError("invalid_component_definition", f"invalid slot {slot_id}")
        slot_ids.add(slot_id)
        require_string(slot.get("role"), f"{slot_label}.role")
        if slot.get("cardinality") not in {"one", "many"}:
            raise ContractError("invalid_component_definition", f"invalid slot cardinality {slot_id}")
        slots.append(copy.deepcopy(slot))
    if reuse_mode == "container" and not slots:
        raise ContractError("invalid_reuse_mode", f"container {component_id} needs a slot")
    if reuse_mode == "complete" and slots:
        raise ContractError("invalid_reuse_mode", f"complete component {component_id} cannot expose a slot")

    data_roles: list[dict[str, Any]] = []
    data_role_ids: set[str] = set()
    for index, role_value in enumerate(
        require_list(definition.get("data_roles"), f"{label}.data_roles")
    ):
        role_label = f"{label}.data_roles[{index}]"
        role = require_dict(role_value, role_label)
        require_exact_keys(role, {"role_id", "meaning", "required"}, role_label)
        role_id = require_string(role.get("role_id"), f"{role_label}.role_id")
        if not COMPONENT_ID_RE.fullmatch(role_id) or role_id in data_role_ids:
            raise ContractError("invalid_component_definition", f"invalid data role {role_id}")
        data_role_ids.add(role_id)
        require_string(role.get("meaning"), f"{role_label}.meaning")
        if type(role.get("required")) is not bool:
            raise ContractError("invalid_component_definition", f"{role_label}.required must be boolean")
        data_roles.append(copy.deepcopy(role))

    action_roles: list[dict[str, Any]] = []
    action_role_ids: set[str] = set()
    for index, role_value in enumerate(
        require_list(definition.get("action_roles"), f"{label}.action_roles")
    ):
        role_label = f"{label}.action_roles[{index}]"
        role = require_dict(role_value, role_label)
        require_exact_keys(role, {"role_id", "meaning"}, role_label)
        role_id = require_string(role.get("role_id"), f"{role_label}.role_id")
        if not COMPONENT_ID_RE.fullmatch(role_id) or role_id in action_role_ids:
            raise ContractError("invalid_component_definition", f"invalid action role {role_id}")
        action_role_ids.add(role_id)
        require_string(role.get("meaning"), f"{role_label}.meaning")
        action_roles.append(copy.deepcopy(role))
    if (
        scope == "shared"
        and reuse_mode == "complete"
        and not (capabilities or data_roles or action_roles)
    ):
        raise ContractError(
            "unsupported_abstraction",
            f"complete shared component {component_id} has no cross-instance invariant",
        )
    return {
        **copy.deepcopy(definition),
        "capabilities": capabilities,
        "slots": slots,
        "data_roles": data_roles,
        "action_roles": action_roles,
    }


def definition_semantic_texts(definition: dict[str, Any]) -> list[str]:
    return [
        definition["name"],
        definition["responsibility"],
        *definition["owns"],
        *definition["excludes"],
        *(item["meaning"] for item in definition["capabilities"]),
        *(item["role"] for item in definition["slots"]),
        *(item["meaning"] for item in definition["data_roles"]),
        *(item["meaning"] for item in definition["action_roles"]),
    ]


def candidate_source_literals(candidate: dict[str, Any]) -> set[str]:
    literals = {
        require_string(candidate.get("name"), "candidate name"),
        require_string(candidate.get("responsibility"), "candidate responsibility"),
        *require_string_list(candidate.get("owns"), "candidate owns"),
        *require_string_list(candidate.get("excludes"), "candidate excludes"),
    }
    for fact_value in require_list(candidate.get("facts"), "candidate facts"):
        fact = require_dict(fact_value, "candidate fact")
        literals.add(require_string(fact.get("meaning"), "fact meaning"))
        for source_value in require_list(fact.get("source_refs"), "fact source refs"):
            source = require_dict(source_value, "fact source ref")
            literals.add(require_text(source.get("quote"), "fact source quote"))
    return {item.strip() for item in literals if len(item.strip()) >= 4}


def is_source_declared_shared_candidate(candidate: dict[str, Any]) -> bool:
    """Allow one reviewed source declaration to establish shared intent.

    Ordinary visual similarity still needs independent repetition. One candidate
    may establish shared intent only through an exact, page-reviewed
    business-source component-relation fact; visible evidence alone never does.
    """
    return any(
        isinstance(fact, dict)
        and fact.get("evidence_class") == "business_source"
        and fact.get("kind") == "component_relation"
        and fact.get("relation_intent") == "shared_candidate"
        and fact.get("relation_target")
        == {"kind": "self_candidate", "id": candidate.get("candidate_id")}
        for fact in require_list(candidate.get("facts"), "candidate facts")
    )


def semantic_tokens(value: str) -> set[str]:
    return set(
        re.findall(
            r"https?://[^\s]+|/[A-Za-z0-9_.~!$&'()*+,;=:@%/-]+|(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])",
            value,
        )
    )


def definition_uses_instance_literal(
    definition_text: str, instance_literals: set[str]
) -> bool:
    normalized = definition_text.strip()
    if any(
        literal in normalized or normalized in literal
        for literal in instance_literals
    ):
        return True
    instance_tokens = {
        token for literal in instance_literals for token in semantic_tokens(literal)
    }
    return bool(semantic_tokens(normalized).intersection(instance_tokens))


def validate_abstraction_plan(
    value: object,
    registry: dict[str, Any],
    project_catalog: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    plan = require_dict(value, "abstraction plan")
    require_exact_keys(
        plan,
        {
            "schema",
            "source_catalog_sha256",
            "business_context_sha256",
            "project_catalog_snapshot_sha256",
            "candidate_registry_sha256",
            "mobile_component_pattern_context",
            "decisions",
            "component_definitions",
            "component_instances",
            "presentation_usages",
        },
        "abstraction plan",
    )
    if plan.get("schema") != "icp.component-design.abstraction-plan.v1":
        raise ContractError("invalid_abstraction_plan", "abstraction plan schema is invalid")
    for field in (
        "source_catalog_sha256",
        "business_context_sha256",
        "project_catalog_snapshot_sha256",
        "candidate_registry_sha256",
    ):
        if plan.get(field) != state.get(field):
            raise ContractError("input_drift", f"abstraction plan {field} changed")
    validate_mobile_component_pattern_context(
        plan.get("mobile_component_pattern_context"), state
    )
    registry_candidates = {
        require_string(item.get("candidate_id"), "registry candidate ID"): item
        for item in require_list(registry.get("candidates"), "registry candidates")
    }
    historical_components = {
        require_string(item.get("component_id"), "historical component ID"): item
        for item in require_list(project_catalog.get("components"), "project catalog components")
    }

    definitions: list[dict[str, Any]] = []
    definitions_by_id: dict[str, dict[str, Any]] = {}
    for index, definition_value in enumerate(
        require_list(plan.get("component_definitions"), "component definitions")
    ):
        definition = validate_component_definition(
            definition_value, f"component definitions[{index}]"
        )
        component_id = definition["component_id"]
        if component_id in historical_components:
            raise ContractError(
                "historical_component_collision",
                f"new definition overwrites historical component {component_id}",
            )
        if component_id in definitions_by_id or component_id in registry_candidates:
            raise ContractError("invalid_component_definition", f"duplicate component {component_id}")
        definitions_by_id[component_id] = definition
        definitions.append(definition)

    decisions: list[dict[str, Any]] = []
    decision_ids: set[str] = set()
    disposition_by_candidate: dict[str, dict[str, Any]] = {}
    targeted_definitions: set[str] = set()
    for index, decision_value in enumerate(require_list(plan.get("decisions"), "decisions")):
        label = f"decisions[{index}]"
        decision = require_dict(decision_value, label)
        kind = require_string(decision.get("kind"), f"{label}.kind")
        if kind not in ABSTRACTION_DECISIONS:
            raise ContractError("invalid_abstraction_decision", f"invalid decision kind {kind}")
        decision_fields = {
            "decision_id",
            "kind",
            "candidate_ids",
            "target_component_id",
            "rationale",
            "evidence_candidate_ids",
            "alternatives_rejected",
        }
        if kind == "adapt-existing":
            decision_fields.add("source_component_id")
        require_exact_keys(
            decision,
            decision_fields,
            label,
        )
        decision_id = require_string(decision.get("decision_id"), f"{label}.decision_id")
        if not COMPONENT_ID_RE.fullmatch(decision_id) or decision_id in decision_ids:
            raise ContractError("invalid_abstraction_decision", f"invalid decision {decision_id}")
        decision_ids.add(decision_id)
        candidate_ids = require_string_list(decision.get("candidate_ids"), f"{label}.candidate_ids")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ContractError("candidate_disposition", f"{decision_id} repeats candidates")
        if kind in {"keep-local", "keep-separate"} and len(candidate_ids) != 1:
            raise ContractError(
                "invalid_abstraction_decision",
                f"{decision_id} must govern exactly one candidate",
            )
        for candidate_id in candidate_ids:
            if candidate_id not in registry_candidates:
                raise ContractError("candidate_disposition", f"unknown candidate {candidate_id}")
            if candidate_id in disposition_by_candidate:
                raise ContractError("candidate_disposition", f"candidate {candidate_id} has two decisions")
            disposition_by_candidate[candidate_id] = decision
        evidence_ids = require_string_list(
            decision.get("evidence_candidate_ids"), f"{label}.evidence_candidate_ids"
        )
        if set(evidence_ids) != set(candidate_ids):
            raise ContractError("unsupported_abstraction", f"{decision_id} lacks candidate evidence")
        require_string(decision.get("rationale"), f"{label}.rationale")
        require_string_list(decision.get("alternatives_rejected"), f"{label}.alternatives_rejected")
        target_id = require_string(decision.get("target_component_id"), f"{label}.target_component_id")
        if target_id in registry_candidates:
            raise ContractError(
                "replacement_cycle",
                f"decision {decision_id} targets a current candidate ID",
            )
        definition = definitions_by_id.get(target_id)
        if kind == "reuse-existing":
            if target_id not in historical_components:
                raise ContractError("historical_component_evidence", f"unknown historical component {target_id}")
            if historical_components[target_id].get(
                "evidence_class"
            ) != "verified-component-lock":
                raise ContractError(
                    "historical_component_evidence",
                    f"{target_id} is not backed by a verified component lock",
                )
        elif kind == "adapt-existing":
            source_component_id = require_string(
                decision.get("source_component_id"),
                f"{label}.source_component_id",
            )
            if source_component_id not in historical_components:
                raise ContractError(
                    "historical_component_evidence",
                    f"unknown historical component {source_component_id}",
                )
            if source_component_id == target_id:
                raise ContractError(
                    "historical_component_collision",
                    f"adaptation {decision_id} must create a new component ID",
                )
            if definition is None:
                raise ContractError(
                    "invalid_abstraction_decision",
                    f"adaptation {decision_id} needs a new complete definition",
                )
            targeted_definitions.add(target_id)
        elif definition is None:
            raise ContractError("invalid_abstraction_decision", f"missing definition {target_id}")
        else:
            targeted_definitions.add(target_id)
            if kind == "extract-container":
                source_declared_single = (
                    len(candidate_ids) == 1
                    and is_source_declared_shared_candidate(
                        registry_candidates[candidate_ids[0]]["candidate"]
                    )
                )
                if (
                    (len(candidate_ids) < 2 and not source_declared_single)
                    or definition["scope"] != "shared"
                    or definition["reuse_mode"] != "container"
                ):
                    raise ContractError("unsupported_abstraction", f"{decision_id} is not a shared container")
            elif kind == "extract-complete":
                source_declared_single = (
                    len(candidate_ids) == 1
                    and is_source_declared_shared_candidate(
                        registry_candidates[candidate_ids[0]]["candidate"]
                    )
                )
                if (
                    (len(candidate_ids) < 2 and not source_declared_single)
                    or definition["scope"] != "shared"
                    or definition["reuse_mode"] != "complete"
                ):
                    raise ContractError("unsupported_abstraction", f"{decision_id} is not a shared complete component")
            elif definition["scope"] != "local" or definition["reuse_mode"] != "local":
                raise ContractError("invalid_reuse_mode", f"{decision_id} must remain local")
        decisions.append(copy.deepcopy(decision))
    if set(disposition_by_candidate) != set(registry_candidates):
        raise ContractError("candidate_disposition", "every candidate needs exactly one decision")
    if targeted_definitions != set(definitions_by_id):
        raise ContractError("component_definition_coverage", "every new definition needs a decision")

    definition_scope_by_id = {
        **{
            component_id: require_dict(
                component.get("semantic_contract"),
                "historical semantic contract",
            ).get("scope")
            for component_id, component in historical_components.items()
        },
        **{
            component_id: definition.get("scope")
            for component_id, definition in definitions_by_id.items()
        },
    }
    shared_components_by_member: dict[str, set[str]] = {}
    for candidate_id, candidate_entry in registry_candidates.items():
        target_component_id = disposition_by_candidate[candidate_id][
            "target_component_id"
        ]
        if definition_scope_by_id.get(target_component_id) == "shared":
            shared_components_by_member.setdefault(
                require_string(candidate_entry.get("member_title"), "member title"),
                set(),
            ).add(target_component_id)

    instances: list[dict[str, Any]] = []
    instance_ids: set[str] = set()
    instantiated_candidates: set[str] = set()
    instances_by_component: dict[str, list[dict[str, Any]]] = {}
    fact_meanings_by_instance: dict[str, dict[str, str]] = {}
    for index, instance_value in enumerate(
        require_list(plan.get("component_instances"), "component instances")
    ):
        label = f"component instances[{index}]"
        instance = require_dict(instance_value, label)
        require_exact_keys(
            instance,
            {"instance_id", "component_id", "page_key", "member_title", "candidate_ids", "fact_bindings"},
            label,
        )
        instance_id = require_string(instance.get("instance_id"), f"{label}.instance_id")
        if not COMPONENT_ID_RE.fullmatch(instance_id) or instance_id in instance_ids:
            raise ContractError("invalid_component_instance", f"invalid instance {instance_id}")
        instance_ids.add(instance_id)
        component_id = require_string(instance.get("component_id"), f"{label}.component_id")
        if component_id not in definitions_by_id and component_id not in historical_components:
            raise ContractError("invalid_component_instance", f"unknown component {component_id}")
        definition = definitions_by_id.get(component_id)
        if definition is None:
            definition = require_dict(
                historical_components[component_id].get("semantic_contract"),
                "historical semantic contract",
            )
        page_key = require_string(instance.get("page_key"), f"{label}.page_key")
        member_title = require_string(instance.get("member_title"), f"{label}.member_title")
        candidate_ids = require_string_list(instance.get("candidate_ids"), f"{label}.candidate_ids")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ContractError("candidate_instance_coverage", f"{instance_id} repeats candidates")
        expected_fact_ids: set[str] = set()
        fact_kinds: dict[str, str] = {}
        fact_evidence_classes: dict[str, str] = {}
        fact_meanings: dict[str, str] = {}
        fact_relations: dict[str, dict[str, Any]] = {}
        for candidate_id in candidate_ids:
            candidate_entry = registry_candidates.get(candidate_id)
            if candidate_entry is None:
                raise ContractError("candidate_instance_coverage", f"unknown candidate {candidate_id}")
            if candidate_id in instantiated_candidates:
                raise ContractError("candidate_instance_coverage", f"candidate {candidate_id} has two instances")
            if candidate_entry.get("page_key") != page_key or candidate_entry.get("member_title") != member_title:
                raise ContractError("cross_page_semantic_leak", f"{instance_id} mixes page candidates")
            candidate_kind = require_string(
                candidate_entry["candidate"].get("kind"), "candidate kind"
            )
            if candidate_kind != definition["kind"]:
                raise ContractError(
                    "invalid_component_instance",
                    f"candidate {candidate_id} kind does not match {component_id}",
                )
            decision = disposition_by_candidate[candidate_id]
            if decision.get("target_component_id") != component_id:
                raise ContractError("candidate_instance_coverage", f"{candidate_id} targets another component")
            instantiated_candidates.add(candidate_id)
            for fact_value in require_list(candidate_entry["candidate"].get("facts"), "candidate facts"):
                fact = require_dict(fact_value, "candidate fact")
                fact_id = require_string(fact.get("fact_id"), "fact ID")
                expected_fact_ids.add(fact_id)
                fact_kinds[fact_id] = require_string(fact.get("kind"), "fact kind")
                fact_evidence_classes[fact_id] = require_string(
                    fact.get("evidence_class"), "fact evidence class"
                )
                fact_meanings[fact_id] = require_string(
                    fact.get("meaning"), "fact meaning"
                )
                if fact.get("kind") == "component_relation":
                    fact_relations[fact_id] = {
                        "intent": fact["relation_intent"],
                        "target": copy.deepcopy(fact["relation_target"]),
                    }
        bindings: list[dict[str, Any]] = []
        bound_fact_ids: set[str] = set()
        capability_kinds = (
            {}
            if definition is None
            else {
                item["capability_id"]: item["kind"]
                for item in definition["capabilities"]
            }
        )
        capability_ids = set(capability_kinds)
        data_role_ids = set() if definition is None else {item["role_id"] for item in definition["data_roles"]}
        action_role_ids = set() if definition is None else {item["role_id"] for item in definition["action_roles"]}
        for binding_index, binding_value in enumerate(
            require_list(instance.get("fact_bindings"), f"{label}.fact_bindings")
        ):
            binding_label = f"{label}.fact_bindings[{binding_index}]"
            binding = require_dict(binding_value, binding_label)
            require_exact_keys(binding, {"fact_id", "target_kind", "target_id"}, binding_label)
            fact_id = require_string(binding.get("fact_id"), f"{binding_label}.fact_id")
            if fact_id not in expected_fact_ids or fact_id in bound_fact_ids:
                raise ContractError("semantic_fact_coverage", f"invalid or duplicate binding {fact_id}")
            bound_fact_ids.add(fact_id)
            target_kind = require_string(binding.get("target_kind"), f"{binding_label}.target_kind")
            target_id = require_string(binding.get("target_id"), f"{binding_label}.target_id")
            if target_kind not in FACT_BINDING_TARGETS:
                raise ContractError("invalid_fact_binding", f"invalid binding target {target_kind}")
            valid_target = (
                target_kind == "instance_fact" and target_id == fact_kinds[fact_id]
                or target_kind == "capability"
                and target_id in capability_ids
                and capability_kinds[target_id] == fact_kinds[fact_id]
                or target_kind == "data_role"
                and target_id in data_role_ids
                and fact_kinds[fact_id] in {"data", "api_dependency"}
                or target_kind == "action_role"
                and target_id in action_role_ids
                and fact_kinds[fact_id] == "behavior"
                or target_kind == "component_ref"
                and fact_id in fact_relations
                and fact_relations[fact_id]["intent"] == "shared_usage"
                and fact_relations[fact_id]["target"]["kind"] == "source_member"
                and target_id
                in shared_components_by_member.get(
                    fact_relations[fact_id]["target"]["id"], set()
                )
            )
            if not valid_target:
                if (
                    fact_id in fact_relations
                    and fact_relations[fact_id]["intent"] == "shared_usage"
                ) or target_kind == "component_ref":
                    raise ContractError(
                        "invalid_component_relation_binding",
                        f"invalid shared component target for {fact_id}",
                    )
                raise ContractError("invalid_fact_binding", f"invalid target for {fact_id}")
            if (
                fact_id in fact_relations
                and fact_relations[fact_id]["intent"] == "shared_usage"
                and target_kind != "component_ref"
            ):
                raise ContractError(
                    "invalid_component_relation_binding",
                    f"shared usage {fact_id} must bind a component_ref",
                )
            if (
                definition.get("scope") == "shared"
                and definition.get("reuse_mode") == "complete"
                and fact_evidence_classes[fact_id] == "design_visible"
                and fact_kinds[fact_id] == "data"
                and target_kind != "data_role"
            ):
                raise ContractError(
                    "visible_variation_role_missing",
                    f"shared complete visible data {fact_id} must bind a data_role",
                )
            if (
                definition.get("scope") == "local"
                and fact_evidence_classes[fact_id] == "business_source"
                and fact_kinds[fact_id] in LOCAL_COMPONENT_CONTRACT_FACT_KINDS
                and target_kind == "instance_fact"
            ):
                raise ContractError(
                    "local_semantic_binding_missing",
                    f"local component {component_id} leaves source fact {fact_id} outside its semantic contract",
                )
            bindings.append(copy.deepcopy(binding))
        if bound_fact_ids != expected_fact_ids:
            raise ContractError("semantic_fact_coverage", f"{instance_id} does not bind every fact")
        normalized_instance = {**copy.deepcopy(instance), "fact_bindings": bindings}
        instances.append(normalized_instance)
        fact_meanings_by_instance[instance_id] = fact_meanings
        instances_by_component.setdefault(component_id, []).append(normalized_instance)
    if instantiated_candidates != set(registry_candidates):
        raise ContractError("candidate_instance_coverage", "every candidate needs exactly one component instance")
    instances_by_id = {item["instance_id"]: item for item in instances}
    instance_by_candidate_id = {
        candidate_id: instance
        for instance in instances
        for candidate_id in instance["candidate_ids"]
    }
    requirements_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for page_value in require_list(registry.get("pages"), "registry pages"):
        page = require_dict(page_value, "registry page")
        for requirement_value in require_list(
            page.get("presentation_requirements"), "presentation requirements"
        ):
            requirement = require_dict(
                requirement_value, "presentation requirement"
            )
            requirement_id = require_string(
                requirement.get("presentation_requirement_id"),
                "presentation requirement ID",
            )
            if requirement_id in requirements_by_id:
                raise ContractError(
                    "presentation_usage_invalid",
                    f"duplicate presentation requirement {requirement_id}",
                )
            requirements_by_id[requirement_id] = (page, requirement)

    normalized_usages: list[dict[str, Any]] = []
    seen_requirement_ids: set[str] = set()
    usage_ids: set[str] = set()
    for usage_index, usage_value in enumerate(
        require_list(plan.get("presentation_usages"), "presentation usages")
    ):
        label = f"presentation usages[{usage_index}]"
        usage = require_dict(usage_value, label)
        require_exact_keys(
            usage,
            {
                "usage_id",
                "presentation_requirement_id",
                "source_page_key",
                "source_member_title",
                "host_instance_id",
                "source_fact_ids",
                "target_page_key",
                "target_member_title",
                "target_instance_id",
                "target_component_id",
                "presentation_mode",
            },
            label,
        )
        usage_id = require_string(usage.get("usage_id"), f"{label}.usage_id")
        requirement_id = require_string(
            usage.get("presentation_requirement_id"),
            f"{label}.presentation_requirement_id",
        )
        if usage_id in usage_ids or requirement_id in seen_requirement_ids:
            raise ContractError(
                "presentation_usage_invalid",
                "presentation usages must be unique per requirement",
            )
        usage_ids.add(usage_id)
        seen_requirement_ids.add(requirement_id)
        requirement_entry = requirements_by_id.get(requirement_id)
        if requirement_entry is None:
            raise ContractError(
                "presentation_usage_invalid",
                f"unknown presentation requirement {requirement_id}",
            )
        source_page, requirement = requirement_entry
        expected_identity = {
            "source_page_key": source_page["page_key"],
            "source_member_title": source_page["member_title"],
            "target_page_key": requirement["target_page_key"],
            "target_member_title": requirement["target_member_title"],
            "presentation_mode": requirement["relation_kind"],
        }
        if any(usage.get(key) != value for key, value in expected_identity.items()):
            raise ContractError(
                "presentation_usage_invalid",
                f"presentation usage changes verified source identity: {requirement_id}",
            )
        source_ref = require_dict(
            requirement.get("source_ref"), "presentation source_ref"
        )
        matching_fact_ids: list[str] = []
        matching_candidate_ids: list[str] = []
        for candidate_id in source_page["candidate_ids"]:
            candidate = registry_candidates[candidate_id]["candidate"]
            candidate_matches: list[str] = []
            for fact_value in require_list(candidate.get("facts"), "candidate facts"):
                fact = require_dict(fact_value, "candidate fact")
                if any(
                    ref.get("clause_id") == source_ref.get("clause_id")
                    and ref.get("source_sha256") == source_ref.get("source_sha256")
                    and ref.get("start") <= source_ref.get("start")
                    and ref.get("end") >= source_ref.get("end")
                    for source_ref_value in require_list(
                        fact.get("source_refs"), "fact source_refs"
                    )
                    for ref in [require_dict(source_ref_value, "fact source_ref")]
                ):
                    candidate_matches.append(
                        require_string(fact.get("fact_id"), "presentation source fact ID")
                    )
            if candidate_matches:
                matching_candidate_ids.append(candidate_id)
                matching_fact_ids.extend(candidate_matches)
        if not matching_fact_ids:
            raise ContractError(
                "presentation_source_fact_missing",
                f"presentation reference has no page semantic fact: {requirement_id}",
            )
        host_instances = {
            instance_by_candidate_id[candidate_id]["instance_id"]
            for candidate_id in matching_candidate_ids
        }
        if len(host_instances) != 1:
            raise ContractError(
                "presentation_usage_invalid",
                f"presentation source facts span multiple host components: {requirement_id}",
            )
        host_instance_id = require_string(
            usage.get("host_instance_id"), f"{label}.host_instance_id"
        )
        if host_instance_id != next(iter(host_instances)):
            raise ContractError(
                "presentation_usage_invalid",
                f"presentation host does not own its source facts: {requirement_id}",
            )
        # Source-fact coverage is an identity set: the declared list must
        # cover exactly the matching facts and is normalized to the
        # authoritative matching-fact order before the evidence-derived
        # usage ID is checked, so identical semantics hash identically.
        source_fact_ids = require_string_list(
            usage.get("source_fact_ids"), f"{label}.source_fact_ids"
        )
        missing_fact_ids = sorted(set(matching_fact_ids) - set(source_fact_ids))
        unexpected_fact_ids = sorted(set(source_fact_ids) - set(matching_fact_ids))
        if missing_fact_ids or unexpected_fact_ids:
            raise ContractError(
                "presentation_usage_invalid",
                "presentation usage does not bind every exact source fact: "
                f"{requirement_id}; missing={missing_fact_ids} "
                f"unexpected={unexpected_fact_ids}",
            )
        usage["source_fact_ids"] = list(matching_fact_ids)
        target_instance_id = require_string(
            usage.get("target_instance_id"), f"{label}.target_instance_id"
        )
        target_instance = instances_by_id.get(target_instance_id)
        if (
            target_instance is None
            or target_instance.get("page_key") != requirement["target_page_key"]
            or target_instance.get("member_title") != requirement["target_member_title"]
            or usage.get("target_component_id") != target_instance.get("component_id")
        ):
            raise ContractError(
                "presentation_usage_invalid",
                f"presentation target does not resolve to the referenced member: {requirement_id}",
            )
        target_page = next(
            page
            for page_value in require_list(registry.get("pages"), "registry pages")
            for page in [require_dict(page_value, "registry page")]
            if page.get("page_key") == requirement["target_page_key"]
        )
        target_root_candidate_ids = require_string_list(
            target_page.get("root_candidate_ids"), "target root candidate IDs", nonempty=False
        )
        if target_root_candidate_ids and not set(
            target_instance["candidate_ids"]
        ).intersection(target_root_candidate_ids):
            raise ContractError(
                "presentation_usage_invalid",
                f"presentation target is not a referenced page root: {requirement_id}",
            )
        evidence = {key: copy.deepcopy(value) for key, value in usage.items() if key != "usage_id"}
        expected_usage_id = "usage-" + sha256_bytes(canonical_bytes(evidence))[:20]
        if usage_id != expected_usage_id:
            raise ContractError(
                "presentation_usage_invalid",
                f"presentation usage ID is not evidence-derived: {requirement_id}",
            )
        normalized_usages.append(copy.deepcopy(usage))
    if seen_requirement_ids != set(requirements_by_id):
        missing = sorted(set(requirements_by_id) - seen_requirement_ids)
        raise ContractError(
            "presentation_usage_missing",
            f"every modal/component reference needs one final component usage: {missing}",
        )
    active_definitions = {
        **{
            component_id: require_dict(
                component.get("semantic_contract"), "historical semantic contract"
            )
            for component_id, component in historical_components.items()
            if component_id in instances_by_component
        },
        **definitions_by_id,
    }
    for component_id, definition in active_definitions.items():
        component_instances = instances_by_component.get(component_id, [])
        component_pages = {
            (instance["page_key"], instance["member_title"])
            for instance in component_instances
        }
        governed_candidate_count = sum(
            len(instance["candidate_ids"]) for instance in component_instances
        )
        if definition["scope"] == "local" and (
            len(component_pages) != 1
            or len(component_instances) != 1
            or governed_candidate_count != 1
        ):
            raise ContractError(
                "unsupported_abstraction",
                f"local component {component_id} must govern one candidate instance",
            )
        if definition["scope"] == "shared":
            governed_candidate_ids = {
                candidate_id
                for instance in component_instances
                for candidate_id in instance["candidate_ids"]
            }
            instance_literal_sets = [
                {
                    literal
                    for candidate_id in instance["candidate_ids"]
                    for literal in candidate_source_literals(
                        registry_candidates[candidate_id]["candidate"]
                    )
                }
                for instance in component_instances
            ]
            outside_literals = {
                literal
                for candidate_id, candidate_entry in registry_candidates.items()
                if candidate_id not in governed_candidate_ids
                for literal in candidate_source_literals(candidate_entry["candidate"])
            }
            for definition_text in definition_semantic_texts(definition):
                supporting_instances = [
                    literals
                    for literals in instance_literal_sets
                    if definition_uses_instance_literal(definition_text, literals)
                ]
                uses_outside_literal = definition_uses_instance_literal(
                    definition_text, outside_literals
                )
                if len(supporting_instances) != len(instance_literal_sets) and (
                    supporting_instances or uses_outside_literal
                ):
                    raise ContractError(
                        "cross_page_definition_leak",
                        f"shared component {component_id} contains an instance-only literal",
                    )
            for target_kind, target_meanings in (
                (
                    "capability",
                    {
                        item["capability_id"]: item["meaning"]
                        for item in definition["capabilities"]
                    },
                ),
                (
                    "data_role",
                    {
                        item["role_id"]: item["meaning"]
                        for item in definition["data_roles"]
                    },
                ),
                (
                    "action_role",
                    {
                        item["role_id"]: item["meaning"]
                        for item in definition["action_roles"]
                    },
                ),
            ):
                for target_id, target_meaning in target_meanings.items():
                    if not all(
                        any(
                            binding["target_kind"] == target_kind
                            and binding["target_id"] == target_id
                            and fact_meanings_by_instance[instance["instance_id"]][
                                binding["fact_id"]
                            ]
                            == target_meaning
                            for binding in instance["fact_bindings"]
                        )
                        for instance in component_instances
                    ):
                        raise ContractError(
                            "cross_page_semantic_leak",
                            f"shared {target_kind} {target_id} has no exact common meaning on every page instance",
                        )
    return {
        **copy.deepcopy(plan),
        "decisions": decisions,
        "component_definitions": definitions,
        "component_instances": instances,
        "presentation_usages": normalized_usages,
    }


def event_id_for(event: dict[str, Any]) -> str:
    return "event-" + sha256_bytes(canonical_bytes(event))[:20]


def build_component_cache(
    plan: dict[str, Any], registry: dict[str, Any], state: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    sequence = 1
    for item in require_list(registry.get("candidates"), "registry candidates"):
        base = {
            "sequence": sequence,
            "type": "candidate-added",
            "component_id": item["candidate_id"],
            "page_key": item["page_key"],
        }
        events.append({"event_id": event_id_for(base), **base})
        sequence += 1
    for definition in sorted(plan["component_definitions"], key=lambda item: item["component_id"]):
        base = {
            "sequence": sequence,
            "type": "component-added",
            "component_id": definition["component_id"],
            "page_key": None,
        }
        events.append({"event_id": event_id_for(base), **base})
        sequence += 1
    replacements: list[dict[str, str]] = []
    for decision in sorted(plan["decisions"], key=lambda item: item["decision_id"]):
        for candidate_id in sorted(decision["candidate_ids"]):
            replacement = {
                "candidate_id": candidate_id,
                "component_id": decision["target_component_id"],
                "decision_id": decision["decision_id"],
            }
            replacements.append(replacement)
            base = {
                "sequence": sequence,
                "type": "superseded",
                "from_component_id": candidate_id,
                "to_component_id": decision["target_component_id"],
                "decision_id": decision["decision_id"],
            }
            events.append({"event_id": event_id_for(base), **base})
            sequence += 1
    event_log = {
        "schema": "icp.component-design.cache-events.v1",
        "candidate_registry_sha256": state["candidate_registry_sha256"],
        "events": events,
    }
    replacement_map = {
        "schema": "icp.component-design.replacement-map.v1",
        "candidate_registry_sha256": state["candidate_registry_sha256"],
        "replacements": sorted(replacements, key=lambda item: item["candidate_id"]),
    }
    return event_log, replacement_map


def validate_final_composition_slots(
    stage_dir: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    project_catalog: dict[str, Any],
) -> None:
    definitions = {
        item["component_id"]: item
        for item in require_list(plan.get("component_definitions"), "component definitions")
    }
    historical = {
        item["component_id"]: item["semantic_contract"]
        for item in require_list(project_catalog.get("components"), "project catalog components")
    }
    definitions.update(historical)
    target_by_candidate = {
        candidate_id: decision["target_component_id"]
        for decision in require_list(plan.get("decisions"), "decisions")
        for candidate_id in decision["candidate_ids"]
    }
    for page_key in sorted(require_dict(state.get("pages"), "page states")):
        page = require_dict(
            read_json(stage_dir / "page-component-facts" / f"{page_key}.json"),
            "sealed page facts",
        )
        for composition_value in require_list(
            page.get("design_compositions"), "design compositions"
        ):
            composition = require_dict(composition_value, "design composition")
            root_id = require_string(
                composition.get("root_instance_id"), "root instance ID"
            )
            instances = {
                item["instance_id"]: item
                for item in require_list(
                    composition.get("instances"), "composition instances"
                )
            }
            occupancy: dict[tuple[str, str], int] = {}
            for instance_id, instance in instances.items():
                if instance_id == root_id:
                    if instance.get("slot") != "root":
                        raise ContractError(
                            "unknown_component_slot",
                            f"root instance {instance_id} must use slot=root",
                        )
                    continue
                parent_id = instance.get("parent_instance_id")
                parent = instances.get(parent_id)
                if parent is None:
                    raise ContractError(
                        "composition_not_tree", f"instance {instance_id} has no parent"
                    )
                parent_component_id = target_by_candidate[parent["candidate_id"]]
                parent_definition = definitions[parent_component_id]
                slot_ids = {
                    slot["slot_id"]
                    for slot in require_list(
                        parent_definition.get("slots"), "parent component slots"
                    )
                }
                if instance.get("slot") not in slot_ids:
                    raise ContractError(
                        "unknown_component_slot",
                        f"instance {instance_id} uses undeclared slot {instance.get('slot')} on {parent_component_id}",
                    )
                occupancy[(parent_id, instance["slot"])] = (
                    occupancy.get((parent_id, instance["slot"]), 0) + 1
                )
            for (parent_id, slot_id), count in occupancy.items():
                parent = instances[parent_id]
                parent_component_id = target_by_candidate[parent["candidate_id"]]
                parent_definition = definitions[parent_component_id]
                slot = next(
                    slot
                    for slot in require_list(
                        parent_definition.get("slots"), "parent component slots"
                    )
                    if slot["slot_id"] == slot_id
                )
                if slot.get("cardinality") == "one" and count > 1:
                    raise ContractError(
                        "invalid_slot_cardinality",
                        f"slot {slot_id} on {parent_component_id} has {count} children",
                    )
            occupied_parent_ids = {parent_id for parent_id, _ in occupancy}
            for instance_id, instance in instances.items():
                component_id = target_by_candidate[instance["candidate_id"]]
                definition = definitions[component_id]
                if (
                    definition.get("reuse_mode") == "container"
                    and instance_id not in occupied_parent_ids
                ):
                    raise ContractError(
                        "unexercised_component_slot",
                        f"container instance {instance_id} has no child slot evidence",
                    )


def record_abstraction(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state = load_state(project_root)
    verify_live_mobile_component_pattern_context(stage_dir, state)
    if state.get("state") != "awaiting_group_abstraction":
        raise ContractError("invalid_state", "group abstraction is not ready")
    require_component_checklist_node(stage_dir, state, "group.abstraction")
    catalog = verify_live_catalog(project_root, stage_dir, state)
    verify_live_business_context(stage_dir, state, catalog)
    registry = verify_live_group_registry(stage_dir, state)
    project_catalog_path = stage_dir / "project-component-catalog.snapshot.json"
    if sha256_bytes(project_catalog_path.read_bytes()) != state.get("project_catalog_snapshot_sha256"):
        raise ContractError("stage_drift", "project component catalog snapshot changed")
    project_catalog = require_dict(read_json(project_catalog_path), "project component catalog")
    if project_catalog.get("schema") != "icp.component-design.project-catalog.v1":
        raise ContractError("invalid_project_catalog", "project component catalog schema is invalid")
    plan = validate_abstraction_plan(
        read_json(Path(args.plan)), registry, project_catalog, state
    )
    validate_final_composition_slots(
        stage_dir, state, plan, project_catalog
    )
    plan_path = stage_dir / "abstraction-decisions.json"
    system_path = stage_dir / "component-system.json"
    events_path = stage_dir / "component-cache-events.json"
    replacement_path = stage_dir / "replacement-map.json"
    if any(path.exists() for path in (plan_path, system_path, events_path, replacement_path)):
        raise ContractError("abstraction_already_recorded", "abstraction transaction is append-only")
    atomic_write_json(plan_path, plan)
    historical_by_id = {
        item["component_id"]: item
        for item in require_list(project_catalog.get("components"), "project catalog components")
    }
    reused_ids = {
        decision["target_component_id"]
        for decision in plan["decisions"]
        if decision["kind"] == "reuse-existing"
    }
    resolved_definitions = copy.deepcopy(plan["component_definitions"])
    resolved_definitions.extend(
        copy.deepcopy(historical_by_id[component_id]["semantic_contract"])
        for component_id in sorted(reused_ids)
    )
    resolved_definitions.sort(key=lambda item: item["component_id"])
    system = {
        "schema": "icp.component-design.component-system.v1",
        "source_authority": copy.deepcopy(SOURCE_AUTHORITY),
        "component_definitions": resolved_definitions,
        "new_component_ids": sorted(
            item["component_id"] for item in plan["component_definitions"]
        ),
        "component_instances": copy.deepcopy(plan["component_instances"]),
        "presentation_usages": copy.deepcopy(plan["presentation_usages"]),
        "decisions": copy.deepcopy(plan["decisions"]),
    }
    atomic_write_json(system_path, system)
    event_log, replacement_map = build_component_cache(plan, registry, state)
    atomic_write_json(events_path, event_log)
    atomic_write_json(replacement_path, replacement_map)
    state["abstraction_plan_sha256"] = sha256_bytes(plan_path.read_bytes())
    state["component_system_sha256"] = sha256_bytes(system_path.read_bytes())
    state["component_cache_events_sha256"] = sha256_bytes(events_path.read_bytes())
    state["replacement_map_sha256"] = sha256_bytes(replacement_path.read_bytes())
    state["state"] = "ready_to_lock"
    atomic_write_json(stage_dir / "state.json", state)
    mark_component_checklist(
        stage_dir,
        state,
        "group.abstraction",
        state["abstraction_plan_sha256"],
    )
    return {
        "ok": True,
        "stage": "component-design",
        "state": state["state"],
        "component_count": len(system["component_definitions"]),
        "instance_count": len(system["component_instances"]),
        "component_system": str(system_path),
        "component_cache_events": str(events_path),
        "replacement_map": str(replacement_path),
    }


def record_page_facts(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state = load_state(project_root)
    verify_live_mobile_component_pattern_context(stage_dir, state)
    if state.get("state") not in {
        "collecting_page_facts",
        "awaiting_group_abstraction",
    }:
        raise ContractError("invalid_state", "page facts cannot be recorded in this state")
    page_key = require_string(args.page_key, "page key")
    page_state = require_dict(state.get("pages", {}).get(page_key), "page state")
    catalog = verify_live_catalog(project_root, stage_dir, state)
    context = verify_live_business_context(stage_dir, state, catalog)
    member = next(
        (
            require_dict(item, "business context member")
            for item in require_list(context.get("members"), "business context members")
            if item.get("title") == page_state.get("member_title")
        ),
        None,
    )
    if member is None:
        raise ContractError("page_identity_mismatch", "page is absent from business context")
    normalized = validate_page_facts(
        read_json(Path(args.facts)), page_key, member, context, catalog, state, stage_dir
    )
    require_component_checklist_node(stage_dir, state, f"page:{page_key}.facts")
    if state.get("state") == "awaiting_group_abstraction":
        verify_live_group_registry(stage_dir, state)
        state["state"] = "collecting_page_facts"
        state.pop("candidate_registry_sha256", None)
    draft_path = stage_dir / "page-component-facts" / f"{page_key}.draft.json"
    review_input_path = (
        stage_dir / "page-component-facts" / f"{page_key}.review.input.json"
    )
    review_input = build_page_review_input(normalized)
    revision = page_state.get("revision", 0)
    if type(revision) is not int or revision < 0:
        raise ContractError("invalid_state", "page revision must be a non-negative integer")
    revision += 1
    atomic_write_json(
        stage_dir
        / "revisions"
        / f"page-facts.{page_key}.{revision:04d}.json",
        normalized,
    )
    atomic_write_json(draft_path, normalized)
    atomic_write_json(review_input_path, review_input)
    page_state["status"] = "awaiting_page_review"
    page_state["revision"] = revision
    page_state["draft_sha256"] = sha256_bytes(draft_path.read_bytes())
    page_state.pop("sha256", None)
    page_state.pop("review_sha256", None)
    sealed_pages = sum(
        1
        for item in require_dict(state.get("pages"), "page states").values()
        if require_dict(item, "page state").get("status") == "sealed"
    )
    total_pages = len(require_dict(state.get("pages"), "page states"))
    atomic_write_json(stage_dir / "state.json", state)
    mark_component_checklist(
        stage_dir,
        state,
        f"page:{page_key}.facts",
        page_state["draft_sha256"],
    )
    return {
        "ok": True,
        "stage": "component-design",
        "state": state["state"],
        "page_key": page_key,
        "page_status": page_state["status"],
        "sealed_pages": sealed_pages,
        "total_pages": total_pages,
        "page_facts_draft": str(draft_path),
        "page_review_input": str(review_input_path),
    }


def record_page_review(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state = load_state(project_root)
    verify_live_mobile_component_pattern_context(stage_dir, state)
    if state.get("state") != "collecting_page_facts":
        raise ContractError("invalid_state", "page review cannot be recorded in this state")
    page_key = require_string(args.page_key, "page key")
    page_state = require_dict(state.get("pages", {}).get(page_key), "page state")
    require_component_checklist_node(stage_dir, state, f"page:{page_key}.review")
    if page_state.get("status") != "awaiting_page_review":
        raise ContractError(
            "invalid_state", "page review requires an awaiting_page_review draft"
        )
    catalog = verify_live_catalog(project_root, stage_dir, state)
    context = verify_live_business_context(stage_dir, state, catalog)
    member = next(
        (
            require_dict(item, "business context member")
            for item in require_list(context.get("members"), "business context members")
            if item.get("title") == page_state.get("member_title")
        ),
        None,
    )
    if member is None:
        raise ContractError("page_identity_mismatch", "page is absent from business context")
    draft_path = stage_dir / "page-component-facts" / f"{page_key}.draft.json"
    if (
        not draft_path.is_file()
        or sha256_bytes(draft_path.read_bytes()) != page_state.get("draft_sha256")
    ):
        raise ContractError("stage_drift", f"page facts draft changed: {page_key}")
    draft = validate_page_facts(
        read_json(draft_path), page_key, member, context, catalog, state, stage_dir
    )
    review, evidence_passes = validate_page_review(
        read_json(Path(args.review)), draft
    )
    revision = page_state.get("revision")
    if type(revision) is not int or revision < 1:
        raise ContractError("invalid_state", "page revision must be a positive integer")
    review_path = stage_dir / "page-component-facts" / f"{page_key}.review.json"
    review_sha = sha256_bytes(json_bytes(review))
    atomic_write_json(
        stage_dir / "revisions" / f"page-review.{page_key}.{revision:04d}.json",
        review,
    )
    atomic_write_json(review_path, review)
    page_state["review_sha256"] = review_sha

    if not evidence_passes:
        repair = {
            "schema": "icp.component-design.page-review-repair.v1",
            "page_key": page_key,
            "page_facts_draft_sha256": page_state["draft_sha256"],
            "page_review_sha256": review_sha,
            "segment_issues": [
                {
                    "segment_id": segment["segment_id"],
                    "issues": copy.deepcopy(segment["issues"]),
                    "failed_checks": [
                        field
                        for field in (
                            "all_normative_meanings_extracted",
                            "facts_atomic",
                            "fact_kinds_correct",
                            "same_page_scope_correct",
                            "component_relation_intents_correct",
                        )
                        if not segment[field]
                    ],
                }
                for segment in review["segment_reviews"]
                if segment["issues"]
                or not all(
                    segment[field]
                    for field in (
                        "all_normative_meanings_extracted",
                        "facts_atomic",
                        "fact_kinds_correct",
                        "same_page_scope_correct",
                        "component_relation_intents_correct",
                    )
                )
            ],
            "cross_page_issues": copy.deepcopy(
                review["cross_page_review"]["issues"]
            ),
            "next_action": "revise the page facts input and record a new draft",
        }
        repair_path = (
            stage_dir / "page-component-facts" / f"{page_key}.review-repair.json"
        )
        atomic_write_json(repair_path, repair)
        page_state["status"] = "revision_required"
        atomic_write_json(stage_dir / "state.json", state)
        return {
            "ok": True,
            "stage": "component-design",
            "state": state["state"],
            "page_key": page_key,
            "page_status": page_state["status"],
            "sealed_pages": sum(
                1
                for item in require_dict(state.get("pages"), "page states").values()
                if require_dict(item, "page state").get("status") == "sealed"
            ),
            "total_pages": len(require_dict(state.get("pages"), "page states")),
            "page_review_repair": str(repair_path),
        }

    canonical_path = stage_dir / "page-component-facts" / f"{page_key}.json"
    atomic_write_json(canonical_path, draft)
    page_state["status"] = "sealed"
    page_state["sha256"] = sha256_bytes(canonical_path.read_bytes())
    page_state["review_sha256"] = sha256_bytes(review_path.read_bytes())
    remove_if_exists(
        stage_dir / "page-component-facts" / f"{page_key}.review-repair.json"
    )
    sealed_pages = sum(
        1
        for item in require_dict(state.get("pages"), "page states").values()
        if require_dict(item, "page state").get("status") == "sealed"
    )
    total_pages = len(require_dict(state.get("pages"), "page states"))
    if sealed_pages == total_pages:
        _, registry_sha = materialize_group_registry(stage_dir, state)
        state["candidate_registry_sha256"] = registry_sha
        state["state"] = "awaiting_group_abstraction"
    atomic_write_json(stage_dir / "state.json", state)
    mark_component_checklist(
        stage_dir,
        state,
        f"page:{page_key}.review",
        page_state["review_sha256"],
    )
    return {
        "ok": True,
        "stage": "component-design",
        "state": state["state"],
        "page_key": page_key,
        "page_status": page_state["status"],
        "sealed_pages": sealed_pages,
        "total_pages": total_pages,
        "page_facts": str(canonical_path),
        "page_review": str(review_path),
    }


def load_hashed_artifact(
    stage_dir: Path, state: dict[str, Any], filename: str, state_field: str
) -> dict[str, Any]:
    path = stage_dir / filename
    if not path.is_file() or sha256_bytes(path.read_bytes()) != state.get(state_field):
        raise ContractError("stage_drift", f"{filename} changed or is missing")
    return require_dict(read_json(path), filename)


def _layout_rect(value: object) -> dict[str, int | float] | None:
    if not isinstance(value, dict):
        return None
    projected = {
        "left": value.get("left", value.get("x")),
        "top": value.get("top", value.get("y")),
        "width": value.get("width"),
        "height": value.get("height"),
    }
    if any(
        isinstance(item, bool) or not isinstance(item, (int, float))
        for item in projected.values()
    ):
        return None
    return projected


def _rect_inside(inner: dict[str, int | float], outer: dict[str, int | float]) -> bool:
    return (
        inner["left"] >= outer["left"]
        and inner["top"] >= outer["top"]
        and inner["left"] + inner["width"] <= outer["left"] + outer["width"]
        and inner["top"] + inner["height"] <= outer["top"] + outer["height"]
    )


def build_component_layout_inputs(
    source_catalog: dict[str, Any],
    page_compositions: list[dict[str, Any]],
    component_definitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project Stage-1 geometry and Stage-2 ownership into one closed input."""

    compositions = {
        require_string(item.get("design_name"), "composition design name"): item
        for value in page_compositions
        for item in [require_dict(value, "page composition")]
    }
    definitions = {
        require_string(item.get("component_id"), "component definition ID"): copy.deepcopy(item)
        for value in component_definitions
        for item in [require_dict(value, "component definition")]
    }
    results: list[dict[str, Any]] = []
    for design_value in require_list(source_catalog.get("designs"), "source catalog designs"):
        design = require_dict(design_value, "source catalog design")
        design_name = require_string(design.get("design_name"), "source catalog design name")
        composition = require_dict(compositions.get(design_name), "design composition")
        raw_nodes: dict[str, dict[str, Any]] = {}
        blocks_by_id: dict[str, dict[str, Any]] = {}
        ordered_node_ids: list[str] = []
        for block_value in require_list(design.get("blocks"), f"{design_name} Blocks"):
            block = require_dict(block_value, f"{design_name} Block")
            block_id = require_string(block.get("block_id"), "Block ID")
            semantic = require_dict(block.get("semantic"), "Block semantic data")
            block_node_ids: list[str] = []
            rendering_ids: list[str] = []
            non_rendering_ids: list[str] = []
            roles: dict[str, str] = {}
            for node_value in require_list(block.get("source_nodes"), "Block source nodes"):
                node = require_dict(node_value, "Block source node")
                node_id = require_string(node.get("source_node_id"), "source node ID")
                if node_id in raw_nodes:
                    raise ContractError(
                        "component_layout_input_invalid",
                        f"source node belongs to multiple Blocks: {design_name}/{node_id}",
                    )
                raw_nodes[node_id] = node
                ordered_node_ids.append(node_id)
                block_node_ids.append(node_id)
                role = require_string(node.get("content_role"), "source node content role")
                roles[node_id] = role
                if role in {"static_copy", "static_visual", "dynamic_content", "platform_element"}:
                    rendering_ids.append(node_id)
                else:
                    non_rendering_ids.append(node_id)
            blocks_by_id[block_id] = {
                "block_id": block_id,
                "semantic_parent_block_id": semantic.get("parent_block_id"),
                "ordered_source_node_ids": block_node_ids,
                "rendering_source_node_ids": rendering_ids,
                "non_rendering_source_node_ids": non_rendering_ids,
                "content_roles_by_source_node_id": roles,
            }
        roots = [
            node_id
            for node_id, node in raw_nodes.items()
            if require_dict(node.get("source_fact"), "source fact").get("parent_id") is None
        ]
        if len(roots) != 1:
            raise ContractError(
                "component_layout_input_invalid",
                f"design needs one source root: {design_name}",
            )
        root_source_node_id = roots[0]
        root_fact = require_dict(raw_nodes[root_source_node_id].get("source_fact"), "root source fact")
        root_payload = require_dict(root_fact.get("payload"), "root source payload")
        root_frame = _layout_rect(root_payload.get("frame"))
        if root_frame is None or root_frame["width"] <= 0 or root_frame["height"] <= 0:
            raise ContractError(
                "component_layout_input_invalid",
                f"design root has no valid frame: {design_name}",
            )
        artboard_rect = {
            "left": 0,
            "top": 0,
            "width": root_frame["width"],
            "height": root_frame["height"],
        }
        source_nodes_by_id: dict[str, dict[str, Any]] = {}
        for source_order, node_id in enumerate(ordered_node_ids):
            node = raw_nodes[node_id]
            fact = require_dict(node.get("source_fact"), "source fact")
            payload = require_dict(fact.get("payload"), "source payload")
            frame = _layout_rect(payload.get("frame"))
            real_frame = _layout_rect(payload.get("realFrame", payload.get("real_frame")))
            selected = real_frame if node.get("geometry_basis") == "real_frame" else frame
            if node_id == root_source_node_id:
                frame_space = "canvas"
            elif selected is None:
                frame_space = "artboard"
            elif _rect_inside(selected, root_frame) and (
                root_frame["left"] != 0 or root_frame["top"] != 0
            ):
                frame_space = "canvas"
            elif _rect_inside(selected, artboard_rect):
                frame_space = "artboard"
            else:
                # Stage 1 records raw design-tool frames, not parent-local layout
                # instructions. Out-of-artboard decoration remains artboard-space.
                frame_space = "artboard"
            source_nodes_by_id[node_id] = {
                "source_node_id": node_id,
                "source_parent_node_id": fact.get("parent_id"),
                "source_order": source_order,
                "frame": frame,
                "real_frame": real_frame,
                "geometry_basis": node.get("geometry_basis"),
                "frame_space": frame_space,
            }
        order_key_by_instance: dict[str, str] = {}
        for instance_value in require_list(composition.get("instances"), "composition instances"):
            instance = require_dict(instance_value, "composition instance")
            source_paths = [
                require_dict(raw_nodes[node_id].get("source_fact"), "source fact").get("source_path")
                for block_id in require_string_list(instance.get("source_block_ids"), "instance source Blocks")
                for node_id in blocks_by_id[block_id]["ordered_source_node_ids"]
            ]
            order_key_by_instance[instance["instance_id"]] = min(
                (json.dumps(path, ensure_ascii=False, separators=(",", ":")) for path in source_paths),
                default="[]",
            )
        sibling_groups: dict[tuple[object, str], list[str]] = {}
        for instance_value in require_list(composition.get("instances"), "composition instances"):
            instance = require_dict(instance_value, "composition instance")
            sibling_groups.setdefault(
                (instance.get("parent_instance_id"), require_string(instance.get("slot"), "instance slot")),
                [],
            ).append(require_string(instance.get("instance_id"), "instance ID"))
        order_by_instance = {
            instance_id: index
            for group in sibling_groups.values()
            for index, instance_id in enumerate(
                sorted(group, key=lambda value: (order_key_by_instance[value], value))
            )
        }
        instances = [
            {
                "instance_id": instance["instance_id"],
                "component_id": instance["component_id"],
                "parent_instance_id": instance["parent_instance_id"],
                "slot": "root" if instance["parent_instance_id"] is None else instance["slot"],
                "order": order_by_instance[instance["instance_id"]],
                "source_block_ids": copy.deepcopy(instance["source_block_ids"]),
            }
            for value in require_list(composition.get("instances"), "composition instances")
            for instance in [require_dict(value, "composition instance")]
        ]
        results.append(
            {
                "page_key": composition["page_key"],
                "design_state_id": design_name,
                "root_instance_id": composition["root_instance_id"],
                "reference": {
                    "root_source_node_id": root_source_node_id,
                    "logical_artboard_size": {
                        "width": root_frame["width"],
                        "height": root_frame["height"],
                    },
                    "coordinate_contract": {
                        "supported_frame_spaces": ["canvas", "artboard", "parent"]
                    },
                },
                "instances": instances,
                "blocks_by_id": blocks_by_id,
                "source_nodes_by_id": source_nodes_by_id,
                "component_definitions_by_id": copy.deepcopy(definitions),
                "platform_context": {},
            }
        )
    return results


def build_block_component_bindings(
    source_catalog: dict[str, Any],
    page_compositions: list[dict[str, Any]],
    component_definitions: list[dict[str, Any]],
    component_instances: list[dict[str, Any]],
    source_catalog_sha256: str,
) -> dict[str, Any]:
    """Join every verified extract Block to its final component ownership."""

    component_ids = {
        require_string(item.get("component_id"), "component definition ID")
        for value in component_definitions
        for item in [require_dict(value, "component definition")]
    }
    semantic_instance_by_candidate: dict[str, dict[str, Any]] = {}
    for value in component_instances:
        instance = require_dict(value, "component instance")
        component_id = require_string(instance.get("component_id"), "component instance component ID")
        if component_id not in component_ids:
            raise ContractError(
                "block_component_binding_coverage",
                f"component instance references missing definition {component_id}",
            )
        for candidate_id in require_string_list(
            instance.get("candidate_ids"), "component instance candidate IDs"
        ):
            if candidate_id in semantic_instance_by_candidate:
                raise ContractError(
                    "block_component_binding_coverage",
                    f"candidate {candidate_id} has more than one semantic component instance",
                )
            semantic_instance_by_candidate[candidate_id] = instance

    composition_by_design: dict[str, dict[str, Any]] = {}
    owner_by_block: dict[tuple[str, str], dict[str, Any]] = {}
    for value in page_compositions:
        composition = require_dict(value, "final page composition")
        design_name = require_string(composition.get("design_name"), "composition design name")
        if design_name in composition_by_design:
            raise ContractError(
                "block_component_binding_coverage",
                f"design {design_name} has more than one final composition",
            )
        composition_by_design[design_name] = composition
        page_key = require_string(composition.get("page_key"), "composition page key")
        member_title = require_string(
            composition.get("member_title"), "composition member title"
        )
        for instance_value in require_list(
            composition.get("instances"), "final composition instances"
        ):
            design_instance = require_dict(instance_value, "final composition instance")
            candidate_id = require_string(
                design_instance.get("candidate_id"), "composition candidate ID"
            )
            component_id = require_string(
                design_instance.get("component_id"), "composition component ID"
            )
            semantic_instance = semantic_instance_by_candidate.get(candidate_id)
            if semantic_instance is None:
                raise ContractError(
                    "block_component_binding_coverage",
                    f"candidate {candidate_id} lacks a semantic component instance",
                )
            if (
                semantic_instance.get("component_id") != component_id
                or semantic_instance.get("page_key") != page_key
                or semantic_instance.get("member_title") != member_title
            ):
                raise ContractError(
                    "block_component_binding_coverage",
                    f"candidate {candidate_id} disagrees with its final composition",
                )
            for block_id in require_string_list(
                design_instance.get("source_block_ids"), "composition source Block IDs"
            ):
                key = (design_name, block_id)
                if key in owner_by_block:
                    raise ContractError(
                        "block_component_binding_coverage",
                        f"Block {design_name}/{block_id} has more than one component owner",
                    )
                owner_by_block[key] = {
                    "page_key": page_key,
                    "member_title": member_title,
                    "design_instance_id": require_string(
                        design_instance.get("instance_id"), "design instance ID"
                    ),
                    "semantic_component_instance_id": require_string(
                        semantic_instance.get("instance_id"),
                        "semantic component instance ID",
                    ),
                    "component_id": component_id,
                    "candidate_id": candidate_id,
                    "parent_design_instance_id": copy.deepcopy(
                        design_instance.get("parent_instance_id")
                    ),
                    "slot": require_string(design_instance.get("slot"), "composition slot"),
                }

    bindings: list[dict[str, Any]] = []
    expected_block_keys: set[tuple[str, str]] = set()
    catalog_design_names: list[str] = []
    for design_value in require_list(source_catalog.get("designs"), "source catalog designs"):
        design = require_dict(design_value, "source catalog design")
        design_name = require_string(design.get("design_name"), "source catalog design name")
        catalog_design_names.append(design_name)
        composition = composition_by_design.get(design_name)
        if composition is None:
            raise ContractError(
                "block_component_binding_coverage",
                f"verified design {design_name} has no final component composition",
            )
        root_block_id = require_string(design.get("root_block_id"), "source catalog root Block ID")
        for block_value in require_list(design.get("blocks"), f"{design_name} Blocks"):
            block = require_dict(block_value, f"{design_name} Block")
            block_id = require_string(block.get("block_id"), f"{design_name} Block ID")
            key = (design_name, block_id)
            if key in expected_block_keys:
                raise ContractError(
                    "block_component_binding_coverage",
                    f"verified Block appears twice: {design_name}/{block_id}",
                )
            expected_block_keys.add(key)
            owner = owner_by_block.get(key)
            if owner is None:
                raise ContractError(
                    "block_component_binding_coverage",
                    f"verified Block has no final component owner: {design_name}/{block_id}",
                )
            if (
                block_id == root_block_id
                and owner["design_instance_id"] != composition.get("root_instance_id")
            ):
                raise ContractError(
                    "block_component_binding_coverage",
                    f"root Block {design_name}/{block_id} is not owned by the root component instance",
                )
            bindings.append(
                {
                    "design_name": design_name,
                    "block": copy.deepcopy(block),
                    **copy.deepcopy(owner),
                }
            )

    if set(owner_by_block) != expected_block_keys:
        extras = sorted(set(owner_by_block) - expected_block_keys)
        raise ContractError(
            "block_component_binding_coverage",
            f"component composition references unknown verified Blocks: {extras}",
        )
    if set(composition_by_design) != set(catalog_design_names):
        extras = sorted(set(composition_by_design) - set(catalog_design_names))
        raise ContractError(
            "block_component_binding_coverage",
            f"component compositions reference unknown verified designs: {extras}",
        )
    return {
        "schema": "icp.component-design.block-component-bindings.v1",
        "source_catalog_sha256": source_catalog_sha256,
        "design_count": len(catalog_design_names),
        "binding_count": len(bindings),
        "bindings": bindings,
        "visual_references": [
            {
                "design_name": require_string(design.get("design_name"), "design name"),
                "path": require_string(
                    require_dict(design.get("visual_reference"), "visual reference").get(
                        "source_project_path"
                    ),
                    "visual reference project path",
                ),
                "sha256": require_string(
                    require_dict(design.get("visual_reference"), "visual reference").get("sha256"),
                    "visual reference SHA-256",
                ),
                "pixel_size": copy.deepcopy(
                    require_dict(design.get("visual_reference"), "visual reference").get("pixel_size")
                ),
                "logical_artboard_size": copy.deepcopy(
                    require_dict(design.get("visual_reference"), "visual reference").get(
                        "logical_artboard_size"
                    )
                ),
                "logical_scale": require_dict(
                    design.get("visual_reference"), "visual reference"
                ).get("logical_scale"),
            }
            for value in require_list(source_catalog.get("designs"), "source catalog designs")
            for design in [require_dict(value, "source catalog design")]
        ],
        "layout_inputs": build_component_layout_inputs(
            source_catalog,
            page_compositions,
            component_definitions,
        ),
    }


def build_locked_interaction_contracts(
    stage_dir: Path,
    state: dict[str, Any],
    pages: list[dict[str, Any]],
    component_instances: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Replace page-local candidate bindings with final component instances."""

    instance_by_candidate: dict[str, dict[str, Any]] = {}
    for instance_value in component_instances:
        instance = require_dict(instance_value, "component instance")
        for candidate_id in require_string_list(
            instance.get("candidate_ids"), "component instance candidate IDs"
        ):
            if candidate_id in instance_by_candidate:
                raise ContractError(
                    "interaction_component_binding_coverage",
                    f"candidate {candidate_id} has multiple final component instances",
                )
            instance_by_candidate[candidate_id] = instance

    interaction_graphs: list[dict[str, Any]] = []
    api_contracts: list[dict[str, Any]] = []
    for page in pages:
        page_key = require_string(page.get("page_key"), "locked page key")
        member_title = require_string(
            page.get("member_title"), "locked page member title"
        )
        graph = require_dict(page.get("interaction_graph"), "page interaction graph")
        projected_interactions: list[dict[str, Any]] = []
        for interaction_value in require_list(
            graph.get("interactions"), "page graph interactions"
        ):
            interaction = require_dict(interaction_value, "page graph interaction")
            candidate_bindings = require_dict(
                interaction.get("component_bindings"),
                "interaction candidate bindings",
            )
            component_bindings: dict[str, list[str]] = {}
            for field in INTERACTION_ITEM_FIELDS:
                candidate_ids = require_string_list(
                    candidate_bindings.get(f"{field}_candidate_ids"),
                    f"interaction {field} candidate bindings",
                    nonempty=False,
                )
                component_instance_ids: list[str] = []
                for candidate_id in candidate_ids:
                    instance = instance_by_candidate.get(candidate_id)
                    if instance is None or instance.get("page_key") != page_key:
                        raise ContractError(
                            "interaction_component_binding_coverage",
                            f"interaction candidate {candidate_id} has no same-page final component",
                        )
                    instance_id = require_string(
                        instance.get("instance_id"), "component instance ID"
                    )
                    if instance_id not in component_instance_ids:
                        component_instance_ids.append(instance_id)
                component_bindings[
                    f"{field}_component_instance_ids"
                ] = component_instance_ids
            projected_interactions.append(
                {
                    **{
                        key: copy.deepcopy(value)
                        for key, value in interaction.items()
                        if key != "component_bindings"
                    },
                    "component_bindings": component_bindings,
                }
            )
        interaction_graphs.append(
            {
                "schema": "icp.component-design.locked-interaction-graph.v2",
                "page_key": page_key,
                "member_title": member_title,
                "interactions": projected_interactions,
                "edges": copy.deepcopy(graph["edges"]),
                "terminal_outcomes": copy.deepcopy(graph["terminal_outcomes"]),
                "transition_requirements": [
                    *copy.deepcopy(
                        require_list(
                            page.get("navigation_requirements"),
                            "page navigation requirements",
                        )
                    ),
                    *[
                        copy.deepcopy(requirement)
                        for requirement_value in require_list(
                            page.get("presentation_requirements"),
                            "page presentation requirements",
                        )
                        for requirement in [
                            require_dict(requirement_value, "presentation requirement")
                        ]
                        if requirement.get("relation_kind") == "modal"
                    ],
                ],
            }
        )
        page_state = require_dict(state.get("pages", {}).get(page_key), "page state")
        artifact_by_contract_id = {
            require_string(
                artifact.get("api_contract_id"), "API artifact contract ID"
            ): artifact
            for artifact_value in require_list(
                page_state.get("api_contract_artifacts"),
                "page API contract artifacts",
            )
            for artifact in [require_dict(artifact_value, "API contract artifact")]
        }
        for contract in require_list(page.get("api_contracts"), "page API contracts"):
            contract_id = require_string(
                require_dict(contract, "page API contract").get("api_contract_id"),
                "page API contract ID",
            )
            artifact = require_dict(
                artifact_by_contract_id.get(contract_id), "API acquisition artifact"
            )
            relative_path = require_string(
                artifact.get("path"), "API acquisition artifact path"
            )
            artifact_path = stage_dir / relative_path
            artifact_sha = require_string(
                artifact.get("sha256"), "API acquisition artifact SHA-256"
            )
            if (
                not artifact_path.is_file()
                or sha256_bytes(artifact_path.read_bytes()) != artifact_sha
            ):
                raise ContractError(
                    "api_acquisition_drift",
                    f"API acquisition artifact changed: {contract_id}",
                )
            api_contracts.append(
                {
                "page_key": page_key,
                "member_title": member_title,
                **copy.deepcopy(contract),
                    "acquisition_artifact": {
                        "path": relative_path,
                        "sha256": artifact_sha,
                    },
                }
            )
    return interaction_graphs, api_contracts


IMPLEMENTATION_CONTRACT_RAW_KEYS = {
    "source_coverage",
    "source_refs",
    "source_ref",
    "source_text",
    "quote",
    "row_data",
    "source_contract",
}


def sanitize_implementation_value(value: Any) -> Any:
    """Project Stage 2 decisions without leaking original source prose to Stage 3."""

    if isinstance(value, dict):
        return {
            key: sanitize_implementation_value(item)
            for key, item in value.items()
            if key not in IMPLEMENTATION_CONTRACT_RAW_KEYS
        }
    if isinstance(value, list):
        return [sanitize_implementation_value(item) for item in value]
    return copy.deepcopy(value)


def build_documented_integration_obligations(
    business_context: dict[str, Any],
    pages: list[dict[str, Any]],
    interaction_graphs: list[dict[str, Any]],
    component_instances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Freeze source-derived test obligations while Stage 2 still owns semantics."""

    instance_by_candidate: dict[str, str] = {}
    fact_owner: dict[str, str] = {}
    for instance_value in component_instances:
        instance = require_dict(instance_value, "component instance")
        instance_id = require_string(instance.get("instance_id"), "component instance ID")
        for candidate_id in require_string_list(
            instance.get("candidate_ids"), "component instance candidate IDs"
        ):
            instance_by_candidate[candidate_id] = instance_id
        for binding_value in require_list(
            instance.get("fact_bindings"), "component instance fact bindings"
        ):
            binding = require_dict(binding_value, "component instance fact binding")
            fact_id = require_string(binding.get("fact_id"), "bound fact ID")
            if fact_id in fact_owner:
                raise ContractError(
                    "integration_obligation_binding",
                    f"fact has multiple component owners: {fact_id}",
                )
            fact_owner[fact_id] = instance_id

    it_clause_ids_by_page: dict[str, set[str]] = {}
    for member_value in require_list(
        business_context.get("members"), "business context members"
    ):
        member = require_dict(member_value, "business context member")
        if not member_requires_semantic_work_item(member):
            continue
        it_clauses = [
            clause
            for clause_value in require_list(member.get("clauses"), "business clauses")
            for clause in [require_dict(clause_value, "business clause")]
            if clause.get("label") == "IT"
        ]
        if len(it_clauses) > 1:
            raise ContractError(
                "integration_obligation_source",
                f"member declares IT more than once: {member.get('title')}",
            )
        it_clause_ids_by_page[page_key_for(member["title"])] = {
            require_string(clause.get("clause_id"), "IT clause ID")
            for clause in it_clauses
        }

    obligations: list[dict[str, Any]] = []
    for graph_value in interaction_graphs:
        graph = require_dict(graph_value, "locked interaction graph")
        page_key = require_string(graph.get("page_key"), "interaction page key")
        member_title = require_string(
            graph.get("member_title"), "interaction member title"
        )
        for interaction_value in require_list(
            graph.get("interactions"), "locked interactions"
        ):
            interaction = require_dict(interaction_value, "locked interaction")
            interaction_id = require_string(
                interaction.get("interaction_id"), "interaction ID"
            )
            fact_ids: list[str] = []
            component_instance_ids: list[str] = []
            for field in INTERACTION_ITEM_FIELDS:
                part = interaction.get(field)
                if part is not None:
                    for fact_id in require_string_list(
                        require_dict(part, f"interaction {field}").get("fact_ids"),
                        f"interaction {field} fact IDs",
                        nonempty=False,
                    ):
                        if fact_id not in fact_ids:
                            fact_ids.append(fact_id)
                for instance_id in require_string_list(
                    require_dict(
                        interaction.get("component_bindings"),
                        "interaction component bindings",
                    ).get(f"{field}_component_instance_ids"),
                    f"interaction {field} component bindings",
                    nonempty=False,
                ):
                    if instance_id not in component_instance_ids:
                        component_instance_ids.append(instance_id)
            if not component_instance_ids:
                raise ContractError(
                    "integration_obligation_binding",
                    f"interaction has no component binding: {interaction_id}",
                )
            behavior = interaction.get("behavior")
            interaction_kind = (
                require_string(
                    require_dict(behavior, "interaction behavior").get("kind"),
                    "interaction behavior kind",
                )
                if behavior is not None
                else next(
                    field
                    for field in INTERACTION_ITEM_FIELDS
                    if interaction.get(field) is not None
                )
            )
            obligations.append(
                {
                    "obligation_id": "interaction-" + sha256_bytes(
                        canonical_bytes({"page_key": page_key, "interaction_id": interaction_id})
                    )[:20],
                    "source_kind": "interaction_description",
                    "page_key": page_key,
                    "member_title": member_title,
                    "item_id": interaction_id,
                    "interaction_id": interaction_id,
                    "kind": interaction_kind,
                    "fact_id": fact_ids[0] if len(fact_ids) == 1 else None,
                    "basis_fact_ids": fact_ids,
                    "component_instance_id": component_instance_ids[0],
                    "component_instance_ids": component_instance_ids,
                    "meaning": f"Implement the complete frozen interaction {interaction_id}.",
                }
            )

    for page in pages:
        page_key = require_string(page.get("page_key"), "locked page key")
        member_title = require_string(page.get("member_title"), "locked member title")
        for candidate_value in require_list(page.get("candidates"), "page candidates"):
            candidate = require_dict(candidate_value, "page candidate")
            for fact_value in require_list(candidate.get("facts"), "candidate facts"):
                fact = require_dict(fact_value, "candidate fact")
                fact_id = require_string(fact.get("fact_id"), "fact ID")
                has_it = any(
                    require_dict(ref_value, "fact source ref").get("clause_id")
                    in it_clause_ids_by_page.get(page_key, set())
                    for ref_value in require_list(
                        fact.get("source_refs"), "fact source refs"
                    )
                )
                if not has_it:
                    continue
                owner = fact_owner.get(fact_id)
                if owner is None:
                    raise ContractError(
                        "integration_obligation_binding",
                        f"IT fact has no component binding: {fact_id}",
                    )
                obligations.append(
                    {
                        "obligation_id": "it-" + sha256_bytes(
                            canonical_bytes({"page_key": page_key, "fact_id": fact_id})
                        )[:20],
                        "source_kind": "it_description",
                        "page_key": page_key,
                        "member_title": member_title,
                        "item_id": "it-" + fact_id,
                        "kind": fact.get("kind"),
                        "fact_id": fact_id,
                        "basis_fact_ids": [fact_id],
                        "component_instance_id": owner,
                        "component_instance_ids": [owner],
                        "meaning": fact.get("meaning"),
                    }
                )
    return obligations


def build_implementation_contract(
    business_context: dict[str, Any],
    source_context: dict[str, Any],
    pages: list[dict[str, Any]],
    component_definitions: list[dict[str, Any]],
    component_instances: list[dict[str, Any]],
    page_compositions: list[dict[str, Any]],
    interaction_graphs: list[dict[str, Any]],
    api_contracts: list[dict[str, Any]],
    presentation_usages: list[dict[str, Any]],
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    pages_by_key = {page["page_key"]: page for page in pages}
    instances_by_page: dict[str, list[str]] = {}
    for instance in component_instances:
        instances_by_page.setdefault(instance["page_key"], []).append(
            instance["instance_id"]
        )
    for page in pages:
        for candidate in require_list(page.get("candidates"), "page candidates"):
            for fact in require_list(
                require_dict(candidate, "page candidate").get("facts"),
                "candidate facts",
            ):
                facts.append(
                    {
                        "page_key": page["page_key"],
                        **sanitize_implementation_value(require_dict(fact, "semantic fact")),
                    }
                )
    contract_pages = []
    for member in require_list(source_context.get("members"), "source members"):
        if member.get("page_key") is None or member.get("change_scope") != "modify":
            continue
        page_key = member["page_key"]
        page = pages_by_key[page_key]
        contract_pages.append(
            {
                "page_key": page_key,
                "member_title": member["title"],
                "route": member.get("route"),
                "design_names": copy.deepcopy(member["design_names"]),
                "component_instance_ids": copy.deepcopy(
                    instances_by_page.get(page_key, [])
                ),
                "semantic_fact_ids": [
                    fact["fact_id"] for fact in facts if fact["page_key"] == page_key
                ],
                "interaction_ids": [
                    item["interaction_id"]
                    for graph in interaction_graphs
                    if graph["page_key"] == page_key
                    for item in graph["interactions"]
                ],
            }
        )
    contract = {
        "schema": "icp.component-design.implementation-contract.v1",
        "source_identity": {
            "source_id": business_context["source_id"],
            "root_title": business_context["root_title"],
            "bundle_digest": business_context["bundle_digest"],
            "members": copy.deepcopy(source_context["members"]),
        },
        "page_keys": [page["page_key"] for page in contract_pages],
        "pages": contract_pages,
        "semantic_facts": facts,
        "component_definitions": sanitize_implementation_value(component_definitions),
        "component_instances": sanitize_implementation_value(component_instances),
        "page_compositions": sanitize_implementation_value(page_compositions),
        "interaction_graphs": sanitize_implementation_value(interaction_graphs),
        "api_contracts": sanitize_implementation_value(api_contracts),
        "presentation_usages": sanitize_implementation_value(presentation_usages),
        "documented_integration_obligations": build_documented_integration_obligations(
            business_context, pages, interaction_graphs, component_instances
        ),
    }
    return require_dict(
        sanitize_implementation_value(contract), "implementation contract"
    )


def build_v8_lock(
    stage_dir: Path,
    state: dict[str, Any],
    source_catalog: dict[str, Any],
    business_context: dict[str, Any],
    registry: dict[str, Any],
    system: dict[str, Any],
    event_log: dict[str, Any],
    replacement_map: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    replacements = {
        item["candidate_id"]: item
        for item in require_list(replacement_map.get("replacements"), "replacements")
    }
    pages: list[dict[str, Any]] = []
    page_compositions: list[dict[str, Any]] = []
    for page_key, page_state_value in sorted(
        require_dict(state.get("pages"), "page states").items()
    ):
        page_state = require_dict(page_state_value, "page state")
        page_path = stage_dir / "page-component-facts" / f"{page_key}.json"
        if sha256_bytes(page_path.read_bytes()) != page_state.get("sha256"):
            raise ContractError("stage_drift", f"sealed page changed: {page_key}")
        page = require_dict(read_json(page_path), "sealed page facts")
        locked_page = copy.deepcopy(page)
        locked_page.pop("mobile_component_pattern_context", None)
        pages.append(locked_page)
        for composition_value in require_list(
            page.get("design_compositions"), "page design compositions"
        ):
            composition = require_dict(composition_value, "page design composition")
            instances: list[dict[str, Any]] = []
            for instance_value in require_list(
                composition.get("instances"), "page composition instances"
            ):
                instance = require_dict(instance_value, "page composition instance")
                candidate_id = require_string(
                    instance.get("candidate_id"), "composition candidate ID"
                )
                replacement = replacements.get(candidate_id)
                if replacement is None:
                    raise ContractError(
                        "replacement_coverage", f"candidate {candidate_id} has no replacement"
                    )
                instances.append(
                    {
                        "instance_id": instance["instance_id"],
                        "component_id": replacement["component_id"],
                        "candidate_id": candidate_id,
                        "parent_instance_id": instance["parent_instance_id"],
                        "slot": instance["slot"],
                        "source_block_ids": copy.deepcopy(instance["source_block_ids"]),
                    }
                )
            page_compositions.append(
                {
                    "page_key": page_key,
                    "member_title": page_state["member_title"],
                    "design_name": composition["design_name"],
                    "root_instance_id": composition["root_instance_id"],
                    "instances": instances,
                }
            )
    candidate_entries = [
        {
            "candidate_id": item["candidate_id"],
            "page_key": item["page_key"],
            "status": "replaced",
            "replaced_by": replacements[item["candidate_id"]]["component_id"],
            "decision_id": replacements[item["candidate_id"]]["decision_id"],
        }
        for item in require_list(registry.get("candidates"), "registry candidates")
    ]
    component_entries = [
        {
            "component_id": item["component_id"],
            "status": (
                "new"
                if item["component_id"]
                in set(system.get("new_component_ids", []))
                else "reused"
            ),
        }
        for item in sorted(
            require_list(system.get("component_definitions"), "component definitions"),
            key=lambda item: item["component_id"],
        )
    ]
    source_context = build_source_context(business_context)
    context_members = [
        copy.deepcopy(member)
        for member_value in require_list(
            business_context.get("members"), "business context members"
        )
        for member in [require_dict(member_value, "business context member")]
        if not member_requires_semantic_work_item(member)
    ]
    component_instances = copy.deepcopy(system["component_instances"])
    validate_source_context_joins(
        source_context,
        pages,
        component_instances,
        page_compositions,
    )
    block_component_bindings = build_block_component_bindings(
        source_catalog,
        page_compositions,
        system["component_definitions"],
        component_instances,
        state["source_catalog_sha256"],
    )
    block_component_bindings_sha = sha256_bytes(json_bytes(block_component_bindings))
    interaction_graphs, api_contracts = build_locked_interaction_contracts(
        stage_dir, state, pages, component_instances
    )
    implementation_contract = build_implementation_contract(
        business_context,
        source_context,
        pages,
        system["component_definitions"],
        component_instances,
        page_compositions,
        interaction_graphs,
        api_contracts,
        system["presentation_usages"],
    )
    lock = {
        "schema": "icp.component-design.lock.v8",
        "stage_boundary": "component-semantics-only",
        "source_authority": copy.deepcopy(SOURCE_AUTHORITY),
        "source_hashes": {
            "extract_run_result_sha256": state["extract_run_result_sha256"],
            "source_catalog_sha256": state["source_catalog_sha256"],
            "iole_source_bundle_sha256": state["iole_source_bundle_sha256"],
            "source_bundle_digest": state["source_bundle_digest"],
            "business_context_sha256": state["business_context_sha256"],
            "mobile_component_patterns_sha256": state[
                "mobile_component_patterns_sha256"
            ],
            "project_catalog_snapshot_sha256": state[
                "project_catalog_snapshot_sha256"
            ],
            "candidate_registry_sha256": state["candidate_registry_sha256"],
            "abstraction_plan_sha256": state["abstraction_plan_sha256"],
            "component_system_sha256": state["component_system_sha256"],
            "component_cache_events_sha256": state[
                "component_cache_events_sha256"
            ],
            "replacement_map_sha256": state["replacement_map_sha256"],
        },
        "inference_context": {
            "mobile_component_patterns": {
                "path": MOBILE_COMPONENT_PATTERNS_STAGE_NAME,
                "sha256": state["mobile_component_patterns_sha256"],
                "authority": "advisory_only",
            }
        },
        "source_context": source_context,
        "pages": pages,
        "context_members": context_members,
        "component_definitions": copy.deepcopy(system["component_definitions"]),
        "component_instances": component_instances,
        "interaction_graphs": interaction_graphs,
        "api_contracts": api_contracts,
        "presentation_usages": copy.deepcopy(system["presentation_usages"]),
        "decisions": copy.deepcopy(system["decisions"]),
        "page_compositions": page_compositions,
        "implementation_contract": implementation_contract,
        "block_component_bindings": {
            "path": BLOCK_COMPONENT_BINDINGS_STAGE_NAME,
            "sha256": block_component_bindings_sha,
            "design_count": block_component_bindings["design_count"],
            "binding_count": block_component_bindings["binding_count"],
        },
        "replacement_map": copy.deepcopy(replacement_map),
        "cache_view": {
            "source": "component-cache-events.json",
            "events_sha256": sha256_bytes(json_bytes(event_log)),
            "candidate_entries": candidate_entries,
            "component_entries": component_entries,
        },
    }
    return lock, block_component_bindings


def verify_v8(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state = load_state(project_root)
    require_component_checklist(stage_dir, state, exclude=("stage.verify",))
    verify_live_mobile_component_pattern_context(stage_dir, state)
    if state.get("state") not in {"ready_to_lock", "locked"}:
        raise ContractError(
            "stage_incomplete", f"component-design state is {state.get('state')}"
        )
    catalog = verify_live_catalog(project_root, stage_dir, state)
    business_context = verify_live_business_context(stage_dir, state, catalog)
    registry = verify_live_group_registry(stage_dir, state)
    project_catalog_path = stage_dir / "project-component-catalog.snapshot.json"
    if sha256_bytes(project_catalog_path.read_bytes()) != state.get(
        "project_catalog_snapshot_sha256"
    ):
        raise ContractError("stage_drift", "project component catalog snapshot changed")
    project_catalog = require_dict(
        read_json(project_catalog_path), "project component catalog"
    )
    plan = load_hashed_artifact(
        stage_dir, state, "abstraction-decisions.json", "abstraction_plan_sha256"
    )
    if validate_abstraction_plan(plan, registry, project_catalog, state) != plan:
        raise ContractError("stage_drift", "abstraction plan normalization changed")
    system = load_hashed_artifact(
        stage_dir, state, "component-system.json", "component_system_sha256"
    )
    historical_by_id = {
        item["component_id"]: item
        for item in require_list(project_catalog.get("components"), "project catalog components")
    }
    reused_ids = {
        decision["target_component_id"]
        for decision in plan["decisions"]
        if decision["kind"] == "reuse-existing"
    }
    expected_definitions = copy.deepcopy(plan["component_definitions"])
    expected_definitions.extend(
        copy.deepcopy(historical_by_id[component_id]["semantic_contract"])
        for component_id in sorted(reused_ids)
    )
    expected_definitions.sort(key=lambda item: item["component_id"])
    expected_system = {
        "schema": "icp.component-design.component-system.v1",
        "source_authority": copy.deepcopy(SOURCE_AUTHORITY),
        "component_definitions": expected_definitions,
        "new_component_ids": sorted(
            item["component_id"] for item in plan["component_definitions"]
        ),
        "component_instances": copy.deepcopy(plan["component_instances"]),
        "presentation_usages": copy.deepcopy(plan["presentation_usages"]),
        "decisions": copy.deepcopy(plan["decisions"]),
    }
    if system != expected_system:
        raise ContractError("stage_drift", "component system differs from its plan")
    event_log = load_hashed_artifact(
        stage_dir,
        state,
        "component-cache-events.json",
        "component_cache_events_sha256",
    )
    replacement_map = load_hashed_artifact(
        stage_dir, state, "replacement-map.json", "replacement_map_sha256"
    )
    expected_events, expected_replacements = build_component_cache(
        plan, registry, state
    )
    if event_log != expected_events or replacement_map != expected_replacements:
        raise ContractError(
            "cache_fold_mismatch", "cache log and replacement projection disagree"
        )
    lock, block_component_bindings = build_v8_lock(
        stage_dir,
        state,
        catalog,
        business_context,
        registry,
        system,
        event_log,
        replacement_map,
    )
    bindings_path = stage_dir / BLOCK_COMPONENT_BINDINGS_STAGE_NAME
    bindings_sha = sha256_bytes(json_bytes(block_component_bindings))
    lock_path = stage_dir / "component-lock.json"
    result_path = stage_dir / "stage-result.json"
    resumed = state.get("state") == "locked"
    if resumed:
        if (
            not bindings_path.is_file()
            or read_json(bindings_path) != block_component_bindings
            or sha256_bytes(bindings_path.read_bytes())
            != state.get("block_component_bindings_sha256")
        ):
            raise ContractError(
                "component_design_locked", "Block-to-component bindings changed"
            )
        if not lock_path.is_file() or read_json(lock_path) != lock:
            raise ContractError("component_design_locked", "component lock changed")
        if not result_path.is_file() or sha256_bytes(
            result_path.read_bytes()
        ) != state.get("stage_result_sha256"):
            raise ContractError("component_design_locked", "stage result changed")
    else:
        atomic_write_json(bindings_path, block_component_bindings)
        atomic_write_json(lock_path, lock)
        lock_sha = sha256_bytes(lock_path.read_bytes())
        stage_result = {
            "schema": "icp.component-design.stage-result.v8",
            "stage": "component-design",
            "status": "complete",
            "stage_boundary": "component-semantics-only",
            "component_count": len(lock["component_definitions"]),
            "instance_count": len(lock["component_instances"]),
            "page_count": len(lock["pages"]),
            "block_binding_count": block_component_bindings["binding_count"],
            "component_lock_sha256": lock_sha,
            "artifacts": {
                "component_lock": {
                    "path": "component-lock.json",
                    "sha256": lock_sha,
                },
                "component_cache_events": {
                    "path": "component-cache-events.json",
                    "sha256": state["component_cache_events_sha256"],
                },
                "replacement_map": {
                    "path": "replacement-map.json",
                    "sha256": state["replacement_map_sha256"],
                },
                "block_component_bindings": {
                    "path": BLOCK_COMPONENT_BINDINGS_STAGE_NAME,
                    "sha256": bindings_sha,
                },
            },
        }
        atomic_write_json(result_path, stage_result)
        state["state"] = "locked"
        state["block_component_bindings_sha256"] = bindings_sha
        state["component_lock_sha256"] = lock_sha
        state["stage_result_sha256"] = sha256_bytes(result_path.read_bytes())
        atomic_write_json(stage_dir / "state.json", state)
    mark_component_checklist(
        stage_dir,
        state,
        "stage.verify",
        state["stage_result_sha256"],
    )
    require_component_checklist(stage_dir, state)
    state["checklist_sha256"] = sha256_bytes(
        (stage_dir / "checklist.json").read_bytes()
    )
    atomic_write_json(stage_dir / "state.json", state)
    return {
        "ok": True,
        "stage": "component-design",
        "state": "locked",
        "resumed": resumed,
        "component_count": len(lock["component_definitions"]),
        "instance_count": len(lock["component_instances"]),
        "block_binding_count": block_component_bindings["binding_count"],
        "block_component_bindings": str(bindings_path),
        "component_lock": str(lock_path),
        "stage_result": str(result_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin_parser = subparsers.add_parser(
        "begin", help="join and freeze a verified extract batch for component design"
    )
    begin_parser.add_argument("--project-root", required=True)
    begin_parser.add_argument("--project-catalog")
    begin_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="bounded wait for the stage write lock (default: 30)",
    )
    begin_parser.set_defaults(handler=begin)
    api_contract_parser = subparsers.add_parser(
        "record-api-contract",
        help="seal one exact Apifox acquisition artifact before page authoring",
    )
    api_contract_parser.add_argument("--project-root", required=True)
    api_contract_parser.add_argument("--page-key", required=True)
    api_contract_parser.add_argument("--contract", required=True)
    api_contract_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="bounded wait for the stage write lock (default: 30)",
    )
    api_contract_parser.set_defaults(handler=record_api_contract)
    page_facts_parser = subparsers.add_parser(
        "record-page-facts",
        help="validate one page-local fact draft and generate its semantic review input",
    )
    page_facts_parser.add_argument("--project-root", required=True)
    page_facts_parser.add_argument("--page-key", required=True)
    page_facts_parser.add_argument("--facts", required=True)
    page_facts_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="bounded wait for the stage write lock (default: 30)",
    )
    page_facts_parser.set_defaults(handler=record_page_facts)
    page_review_parser = subparsers.add_parser(
        "record-page-review",
        help="record one hash-bound semantic review and seal only a passing page",
    )
    page_review_parser.add_argument("--project-root", required=True)
    page_review_parser.add_argument("--page-key", required=True)
    page_review_parser.add_argument("--review", required=True)
    page_review_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="bounded wait for the stage write lock (default: 30)",
    )
    page_review_parser.set_defaults(handler=record_page_review)
    abstraction_parser = subparsers.add_parser(
        "record-abstraction",
        help="validate the group-wide component abstraction and append-only cache transaction",
    )
    abstraction_parser.add_argument("--project-root", required=True)
    abstraction_parser.add_argument("--plan", required=True)
    abstraction_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="bounded wait for the stage write lock (default: 30)",
    )
    abstraction_parser.set_defaults(handler=record_abstraction)
    verify_parser = subparsers.add_parser(
        "verify", help="freeze or re-verify the stage-3 component semantic lock"
    )
    verify_parser.add_argument("--project-root", required=True)
    verify_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="bounded wait for the stage write lock (default: 30)",
    )
    verify_parser.set_defaults(handler=verify_v8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with stage_write_lock(
            Path(args.project_root).resolve(), args.lock_timeout_seconds
        ):
            result = args.handler(args)
    except ContractError as exc:
        print(
            json.dumps({"ok": False, "error": exc.code, "message": exc.message}),
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(
            json.dumps({"ok": False, "error": "io_error", "message": str(exc)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
