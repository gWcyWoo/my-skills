#!/usr/bin/env python3
"""Deterministic contract gates for ICP implementation."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any


STAGE_ROOT = Path(__file__).resolve().parents[1]
ICP_ROOT = STAGE_ROOT.parent
COMPONENT_SCRIPT = ICP_ROOT / "component-design" / "scripts" / "component_design.py"
PLATFORM_RULES = {
    "android-kotlin": STAGE_ROOT
    / "references"
    / "platform-best-practices"
    / "android-kotlin.md"
}
IMPLEMENTATION_PROMPT = STAGE_ROOT / "references" / "codegen-prompt.md"
RENDERING_CONTENT_ROLES = {
    "static_visual",
    "static_copy",
    "dynamic_content",
    "platform_element",
}
INTERACTION_FIELDS = ("condition", "state", "trigger", "behavior")
COMMON_RULES_PROJECT_PATH = "common-rules.md"


class ContractError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError("missing_input", f"file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json", f"invalid JSON at {path}: {exc}") from exc


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


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(value)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write(path, json_bytes(value))


def implementation_dir(project_root: Path) -> Path:
    return project_root / ".icp" / "implementation"


@contextmanager
def exclusive_case_recording(project_root: Path):
    """Serialize run-case read/execute/write cycles so evidence cannot be lost."""
    stage_dir = implementation_dir(project_root)
    stage_dir.mkdir(parents=True, exist_ok=True)
    with (stage_dir / ".case-recording.lock").open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def verify_component_design(project_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    result = subprocess.run(
        [
            sys.executable,
            str(COMPONENT_SCRIPT),
            "verify",
            "--project-root",
            str(project_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ContractError(
            "component_design_incomplete",
            detail or "component-design live verification failed",
        )
    component_dir = project_root / ".icp" / "component-design"
    lock = require_dict(read_json(component_dir / "component-lock.json"), "component lock")
    bindings = require_dict(
        read_json(component_dir / "block-component-bindings.json"),
        "block-component bindings",
    )
    if lock.get("schema") != "icp.component-design.lock.v6":
        raise ContractError("component_design_incomplete", "component lock v6 is required")
    if lock.get("stage_boundary") != "component-semantics-only":
        raise ContractError("component_design_incomplete", "component stage boundary changed")
    return component_dir, lock, bindings


def obligation_id(prefix: str, evidence: object) -> str:
    return prefix + "-" + digest(evidence)[:20]


def build_visual_references(
    project_root: Path, design_names: list[str]
) -> list[dict[str, Any]]:
    extract_dir = project_root / ".icp" / "extract"
    run_result = require_dict(read_json(extract_dir / "run-result.json"), "extract run result")
    designs = {
        require_string(item.get("design_name"), "extract design name"): item
        for value in require_list(run_result.get("designs"), "extract run designs")
        for item in [require_dict(value, "extract run design")]
    }
    result: list[dict[str, Any]] = []
    for design_name in design_names:
        design = designs.get(design_name)
        if design is None:
            raise ContractError("visual_reference_missing", f"extract design is missing: {design_name}")
        design_dir = require_string(design.get("design_dir"), "extract design dir")
        manifest_path = extract_dir / design_dir / "source-manifest.json"
        manifest = require_dict(read_json(manifest_path), "extract source manifest")
        reference = require_dict(manifest.get("reference"), "extract visual reference")
        reference_path = manifest_path.parent / require_string(reference.get("path"), "reference path")
        if not reference_path.is_file() or file_sha(reference_path) != reference.get("sha256"):
            raise ContractError("visual_reference_missing", f"visual reference changed: {design_name}")
        result.append(
            {
                "design_name": design_name,
                "path": str(reference_path.relative_to(project_root)),
                "sha256": reference["sha256"],
                "pixel_size": reference["pixel_size"],
                "logical_artboard_size": reference["logical_artboard_size"],
                "logical_scale": reference["logical_scale"],
            }
        )
    return result


def build_integration_obligations(
    pages: list[dict[str, Any]],
    component_instances: list[dict[str, Any]],
    interaction_obligations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fact_owner: dict[str, str] = {}
    instances_by_page: dict[str, list[dict[str, Any]]] = {}
    for instance in component_instances:
        page_key = require_string(instance.get("page_key"), "component instance page key")
        instances_by_page.setdefault(page_key, []).append(instance)
        for binding_value in require_list(
            instance.get("fact_bindings"), "component instance fact bindings"
        ):
            binding = require_dict(binding_value, "component instance fact binding")
            fact_id = require_string(binding.get("fact_id"), "bound fact ID")
            if fact_id in fact_owner:
                raise ContractError(
                    "coverage_incomplete", f"fact has multiple component owners: {fact_id}"
                )
            fact_owner[fact_id] = instance["component_instance_id"]

    obligations: list[dict[str, Any]] = []
    for interaction in interaction_obligations:
        fact_id = interaction["fact_id"]
        component_instance_id = fact_owner.get(fact_id)
        if component_instance_id is None:
            raise ContractError(
                "coverage_incomplete", f"interaction fact has no component owner: {fact_id}"
            )
        obligations.append(
            {
                **interaction,
                "obligation_id": obligation_id(
                    "integration",
                    {
                        "page_key": interaction["page_key"],
                        "source_kind": "interaction_description",
                        "fact_id": fact_id,
                    },
                ),
                "source_kind": "interaction_description",
                "basis_fact_ids": [fact_id],
                "component_instance_id": component_instance_id,
            }
        )

    for page in pages:
        page_key = page["page_key"]
        facts_by_id = {
            fact["fact_id"]: fact
            for candidate_value in require_list(page.get("candidates"), "page candidates")
            for candidate in [require_dict(candidate_value, "page candidate")]
            for fact_value in require_list(candidate.get("facts"), "candidate facts")
            for fact in [require_dict(fact_value, "candidate fact")]
        }
        for fact_id, fact in facts_by_id.items():
            if fact.get("kind") not in INTERACTION_FIELDS:
                continue
            it_refs = [
                ref
                for ref_value in require_list(fact.get("source_refs"), "fact source refs")
                for ref in [require_dict(ref_value, "fact source ref")]
                if ref.get("clause_id") == "acceptance:1"
            ]
            if not it_refs:
                continue
            component_instance_id = fact_owner.get(fact_id)
            if component_instance_id is None:
                raise ContractError(
                    "coverage_incomplete", f"IT fact has no component owner: {fact_id}"
                )
            obligations.append(
                {
                    "obligation_id": obligation_id(
                        "integration",
                        {
                            "page_key": page_key,
                            "source_kind": "it_description",
                            "fact_id": fact_id,
                        },
                    ),
                    "source_kind": "it_description",
                    "page_key": page_key,
                    "member_title": page["member_title"],
                    "item_id": "it-" + digest({"fact_id": fact_id})[:20],
                    "kind": fact["kind"],
                    "fact_id": fact_id,
                    "basis_fact_ids": [fact_id],
                    "component_instance_id": component_instance_id,
                    "meaning": fact["meaning"],
                    "source_ref": it_refs[0],
                }
            )

        for instance in instances_by_page.get(page_key, []):
            instance_id = instance["component_instance_id"]
            basis_fact_ids = [
                require_string(binding.get("fact_id"), "inference basis fact ID")
                for binding_value in require_list(
                    instance.get("fact_bindings"), "component fact bindings"
                )
                for binding in [require_dict(binding_value, "component fact binding")]
            ]
            obligations.append(
                {
                    "obligation_id": obligation_id(
                        "integration",
                        {
                            "page_key": page_key,
                            "source_kind": "model_inference",
                            "component_instance_id": instance_id,
                        },
                    ),
                    "source_kind": "model_inference",
                    "page_key": page_key,
                    "member_title": page["member_title"],
                    "item_id": "inferred-" + digest({"component_instance_id": instance_id})[:20],
                    "kind": "component_contract",
                    "fact_id": None,
                    "basis_fact_ids": basis_fact_ids,
                    "component_instance_id": instance_id,
                    "meaning": (
                        "Model derives one integration scenario from this component's "
                        "complete frozen semantic contract and page composition."
                    ),
                    "source_ref": None,
                }
            )
    return obligations


def build_coverage_universe(
    project_root: Path, lock: dict[str, Any], bindings: dict[str, Any]
) -> dict[str, Any]:
    extract_dir = project_root / ".icp" / "extract"
    extract_result = require_dict(
        read_json(extract_dir / "run-result.json"), "extract run result"
    )
    design_directories = {
        require_string(item.get("design_name"), "extract design name"): require_string(
            item.get("design_dir"), "extract design directory"
        )
        for value in require_list(extract_result.get("designs"), "extract run designs")
        for item in [require_dict(value, "extract run design")]
    }
    source_context = require_dict(lock.get("source_context"), "source context")
    modify_members = [
        require_dict(value, "source member")
        for value in require_list(source_context.get("members"), "source members")
        if require_dict(value, "source member").get("change_scope") == "modify"
    ]
    page_keys = [require_string(item.get("page_key"), "modify page key") for item in modify_members]
    page_key_set = set(page_keys)
    pages = [
        require_dict(value, "locked page")
        for value in require_list(lock.get("pages"), "locked pages")
        if require_dict(value, "locked page").get("page_key") in page_key_set
    ]
    pages_by_key = {item["page_key"]: item for item in pages}
    if set(pages_by_key) != page_key_set:
        raise ContractError("coverage_incomplete", "modify pages do not join locked page data")

    component_instances = [
        {
            "component_instance_id": instance["instance_id"],
            "component_id": instance["component_id"],
            "page_key": instance["page_key"],
            "member_title": instance["member_title"],
            "candidate_ids": instance["candidate_ids"],
            "fact_bindings": instance["fact_bindings"],
        }
        for value in require_list(lock.get("component_instances"), "component instances")
        for instance in [require_dict(value, "component instance")]
        if instance.get("page_key") in page_key_set
    ]
    component_ids = {item["component_id"] for item in component_instances}
    component_definitions = [
        require_dict(value, "component definition")
        for value in require_list(lock.get("component_definitions"), "component definitions")
        if require_dict(value, "component definition").get("component_id") in component_ids
    ]

    design_elements: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    seen_design_nodes: set[tuple[str, str]] = set()
    for binding_value in require_list(bindings.get("bindings"), "Block bindings"):
        binding = require_dict(binding_value, "Block binding")
        if binding.get("page_key") not in page_key_set:
            continue
        block = require_dict(binding.get("block"), "bound Block")
        block_evidence = {
            "page_key": binding["page_key"],
            "member_title": binding["member_title"],
            "design_name": binding["design_name"],
            "block_id": block["block_id"],
            "design_instance_id": binding["design_instance_id"],
            "component_instance_id": binding["semantic_component_instance_id"],
            "component_id": binding["component_id"],
            "candidate_id": binding["candidate_id"],
            "parent_design_instance_id": binding["parent_design_instance_id"],
            "slot": binding["slot"],
        }
        blocks.append(
            {
                "obligation_id": obligation_id("block", block_evidence),
                **block_evidence,
                "semantic": block["semantic"],
            }
        )
        for node_value in require_list(block.get("source_nodes"), "Block source nodes"):
            node = require_dict(node_value, "Block source node")
            content_role = node.get("content_role")
            if content_role not in RENDERING_CONTENT_ROLES:
                raise ContractError(
                    "content_role_missing",
                    f"rendering source node has no reviewed content role: {binding['design_name']}/{node.get('source_node_id')}",
                )
            key = (binding["design_name"], require_string(node.get("source_node_id"), "source node ID"))
            if key in seen_design_nodes:
                raise ContractError("coverage_incomplete", f"source node has two Block owners: {key}")
            seen_design_nodes.add(key)
            evidence = {
                **block_evidence,
                "source_node_id": node["source_node_id"],
                "content_role": content_role,
            }
            assets: list[dict[str, Any]] = []
            design_dir = design_directories.get(binding["design_name"])
            if design_dir is None:
                raise ContractError(
                    "coverage_incomplete",
                    f"extract design directory is missing: {binding['design_name']}",
                )
            for asset_value in require_list(node.get("assets"), "source node assets"):
                asset = require_dict(asset_value, "source node asset")
                source_path = (
                    extract_dir
                    / design_dir
                    / require_relative_path(asset.get("local_path"), "source asset path")
                )
                if not source_path.is_file() or file_sha(source_path) != asset.get("sha256"):
                    raise ContractError(
                        "asset_source_drift",
                        f"source asset changed: {binding['design_name']}/{asset.get('asset_id')}",
                    )
                assets.append(
                    {
                        **asset,
                        "source_project_path": str(source_path.relative_to(project_root)),
                    }
                )
            design_elements.append(
                {
                    "obligation_id": obligation_id("element", evidence),
                    **evidence,
                    "geometry_basis": node["geometry_basis"],
                    "source_fact": node["source_fact"],
                    "assets": assets,
                }
            )

    semantic_facts: list[dict[str, Any]] = []
    interaction_obligations: list[dict[str, Any]] = []
    for page in pages:
        facts_by_id = {
            fact["fact_id"]: fact
            for candidate_value in require_list(page.get("candidates"), "page candidates")
            for candidate in [require_dict(candidate_value, "page candidate")]
            for fact_value in require_list(candidate.get("facts"), "candidate facts")
            for fact in [require_dict(fact_value, "candidate fact")]
        }
        for fact in facts_by_id.values():
            semantic_facts.append(
                {
                    "obligation_id": obligation_id(
                        "fact", {"page_key": page["page_key"], "fact_id": fact["fact_id"]}
                    ),
                    "page_key": page["page_key"],
                    **fact,
                }
            )
        seen_interaction_fact_ids: set[str] = set()
        for item_value in require_list(page.get("interaction_items"), "interaction items"):
            item = require_dict(item_value, "interaction item")
            for field in INTERACTION_FIELDS:
                value = item.get(field)
                if value is None:
                    continue
                interaction = require_dict(value, f"interaction {field}")
                fact_id = require_string(interaction.get("fact_id"), "interaction fact ID")
                if fact_id in seen_interaction_fact_ids or fact_id not in facts_by_id:
                    raise ContractError("coverage_incomplete", f"invalid interaction fact {fact_id}")
                seen_interaction_fact_ids.add(fact_id)
                interaction_obligations.append(
                    {
                        "obligation_id": obligation_id(
                            "interaction",
                            {"page_key": page["page_key"], "fact_id": fact_id},
                        ),
                        "page_key": page["page_key"],
                        "member_title": page["member_title"],
                        "item_id": item["item_id"],
                        "kind": field,
                        "fact_id": fact_id,
                        "meaning": interaction["meaning"],
                        "source_ref": item["source_ref"],
                    }
                )

    presentation_usages = [
        require_dict(value, "presentation usage")
        for value in require_list(lock.get("presentation_usages"), "presentation usages")
        if require_dict(value, "presentation usage").get("source_page_key") in page_key_set
    ]
    design_names = list(dict.fromkeys(item["design_name"] for item in blocks))
    return {
        "schema": "icp.implementation.coverage-universe.v1",
        "source_authority": lock["source_authority"],
        "page_keys": page_keys,
        "pages": pages,
        "component_definitions": component_definitions,
        "component_instances": component_instances,
        "blocks": blocks,
        "design_elements": design_elements,
        "semantic_facts": semantic_facts,
        "interaction_obligations": interaction_obligations,
        "integration_obligations": build_integration_obligations(
            pages, component_instances, interaction_obligations
        ),
        "presentation_usages": presentation_usages,
        "visual_references": build_visual_references(project_root, design_names),
    }


def build_plan_input(
    state: dict[str, Any],
    universe: dict[str, Any],
    common_rules: str,
    platform_rules: str,
    implementation_prompt: str,
) -> dict[str, Any]:
    return {
        "schema": "icp.implementation.plan.v1",
        "component_lock_sha256": state["component_lock_sha256"],
        "block_component_bindings_sha256": state["block_component_bindings_sha256"],
        "coverage_universe_sha256": state["coverage_universe_sha256"],
        "platform_rules_sha256": state["platform_rules_sha256"],
        "common_rules": {
            "project_path": COMMON_RULES_PROJECT_PATH,
            "sha256": state["common_rules_sha256"],
            "content": common_rules,
        },
        "platform_best_practices": {
            "sha256": state["platform_rules_sha256"],
            "content": platform_rules,
        },
        "implementation_prompt": {
            "sha256": state["implementation_prompt_sha256"],
            "content": implementation_prompt,
        },
        "platform": state["platform"],
        "source_authority": universe["source_authority"],
        "page_keys": universe["page_keys"],
        "component_definitions": universe["component_definitions"],
        "pages": [],
        "component_mappings": [],
        "design_element_mappings": [],
        "semantic_fact_mappings": [],
        "integration_test_cases": [],
        "presentation_mappings": [],
        "visual_capture_cases": [],
        "verification_commands": {"lint": [], "build": [], "integration": []},
    }


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ContractError(
            "invalid_plan",
            f"{label} fields differ: missing={sorted(expected - set(value))} extra={sorted(set(value) - expected)}",
        )


def require_relative_path(value: object, label: str) -> str:
    text = require_string(value, label)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError("invalid_plan", f"{label} must be project-relative")
    return text


def require_string_list(value: object, label: str, *, nonempty: bool = True) -> list[str]:
    items = require_list(value, label)
    if (nonempty and not items) or any(not isinstance(item, str) or not item for item in items):
        raise ContractError("invalid_plan", f"{label} must contain strings")
    return items


def load_live_stage(project_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    stage_dir = implementation_dir(project_root)
    state = require_dict(read_json(stage_dir / "state.json"), "implementation state")
    if state.get("schema") != "icp.implementation.state.v1":
        raise ContractError("invalid_state", "implementation state schema is invalid")
    component_dir, _lock, _bindings = verify_component_design(project_root)
    expected_hashes = {
        "component_lock_sha256": file_sha(component_dir / "component-lock.json"),
        "block_component_bindings_sha256": file_sha(
            component_dir / "block-component-bindings.json"
        ),
        "coverage_universe_sha256": file_sha(stage_dir / "coverage-universe.json"),
        "platform_rules_sha256": file_sha(stage_dir / "platform-best-practices.md"),
        "common_rules_sha256": file_sha(stage_dir / "common-rules.md"),
        "implementation_prompt_sha256": file_sha(stage_dir / "implementation-prompt.md"),
    }
    for field, expected in expected_hashes.items():
        if state.get(field) != expected:
            raise ContractError("stage_drift", f"implementation {field} changed")
    project_common_rules = project_root / COMMON_RULES_PROJECT_PATH
    if (
        not project_common_rules.is_file()
        or file_sha(project_common_rules) != state.get("common_rules_sha256")
    ):
        raise ContractError("stage_drift", "project common-rules.md changed")
    universe = require_dict(read_json(stage_dir / "coverage-universe.json"), "coverage universe")
    return stage_dir, state, universe


def validate_command(value: object, label: str) -> list[str]:
    command = require_string_list(value, label)
    if any("\x00" in item for item in command):
        raise ContractError("invalid_plan", f"{label} contains invalid command data")
    return command


def validate_plan(
    value: object, state: dict[str, Any], universe: dict[str, Any]
) -> dict[str, Any]:
    plan = require_dict(value, "implementation plan")
    require_exact_keys(
        plan,
        {
            "schema",
            "component_lock_sha256",
            "block_component_bindings_sha256",
            "coverage_universe_sha256",
            "platform_rules_sha256",
            "common_rules",
            "platform_best_practices",
            "implementation_prompt",
            "platform",
            "source_authority",
            "page_keys",
            "component_definitions",
            "pages",
            "component_mappings",
            "design_element_mappings",
            "semantic_fact_mappings",
            "integration_test_cases",
            "presentation_mappings",
            "visual_capture_cases",
            "verification_commands",
        },
        "implementation plan",
    )
    if plan.get("schema") != "icp.implementation.plan.v1":
        raise ContractError("invalid_plan", "implementation plan schema is invalid")
    for field in (
        "component_lock_sha256",
        "block_component_bindings_sha256",
        "coverage_universe_sha256",
        "platform_rules_sha256",
        "platform",
    ):
        if plan.get(field) != state.get(field):
            raise ContractError("input_drift", f"implementation plan {field} changed")
    if plan.get("source_authority") != universe.get("source_authority"):
        raise ContractError("input_drift", "implementation source authority changed")
    common_rules = require_dict(plan.get("common_rules"), "common rules")
    require_exact_keys(
        common_rules, {"project_path", "sha256", "content"}, "common rules"
    )
    if (
        common_rules.get("project_path") != COMMON_RULES_PROJECT_PATH
        or common_rules.get("sha256") != state.get("common_rules_sha256")
        or not isinstance(common_rules.get("content"), str)
        or hashlib.sha256(common_rules["content"].encode("utf-8")).hexdigest()
        != state.get("common_rules_sha256")
    ):
        raise ContractError("input_drift", "project common rules changed")
    platform_best_practices = require_dict(
        plan.get("platform_best_practices"), "platform best practices"
    )
    require_exact_keys(
        platform_best_practices,
        {"sha256", "content"},
        "platform best practices",
    )
    if (
        platform_best_practices.get("sha256") != state.get("platform_rules_sha256")
        or not isinstance(platform_best_practices.get("content"), str)
        or hashlib.sha256(
            platform_best_practices["content"].encode("utf-8")
        ).hexdigest()
        != state.get("platform_rules_sha256")
    ):
        raise ContractError("input_drift", "platform best practices changed")
    implementation_prompt = require_dict(
        plan.get("implementation_prompt"), "implementation prompt"
    )
    require_exact_keys(
        implementation_prompt, {"sha256", "content"}, "implementation prompt"
    )
    if (
        implementation_prompt.get("sha256")
        != state.get("implementation_prompt_sha256")
        or not isinstance(implementation_prompt.get("content"), str)
        or hashlib.sha256(implementation_prompt["content"].encode("utf-8")).hexdigest()
        != state.get("implementation_prompt_sha256")
    ):
        raise ContractError("input_drift", "implementation prompt changed")
    if plan.get("page_keys") != universe.get("page_keys"):
        raise ContractError("coverage_incomplete", "implementation page order changed")
    if plan.get("component_definitions") != universe.get("component_definitions"):
        raise ContractError("input_drift", "component definitions changed")

    expected_instances = {
        item["component_instance_id"]: item for item in universe["component_instances"]
    }
    pages: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    covered_instances: list[str] = []
    for index, page_value in enumerate(require_list(plan.get("pages"), "plan pages")):
        label = f"pages[{index}]"
        page = require_dict(page_value, label)
        require_exact_keys(
            page,
            {
                "page_key",
                "member_title",
                "route",
                "source_file",
                "root_symbol",
                "dto_file",
                "dto_symbol",
                "ui_state_symbol",
                "mock_fixture_path",
                "api_adapter_symbol",
                "responsive_strategy",
                "component_instance_ids",
            },
            label,
        )
        page_key = require_string(page.get("page_key"), f"{label}.page_key")
        source_page = next(
            (item for item in universe["pages"] if item["page_key"] == page_key), None
        )
        if source_page is None or page_key in seen_pages or page.get("member_title") != source_page.get("member_title"):
            raise ContractError("coverage_incomplete", f"invalid or duplicate page {page_key}")
        seen_pages.add(page_key)
        source_route = next(
            item["source_text"]
            for item in source_page["source_coverage"]
            if item["clause_id"] == "page:route"
        )
        if page.get("route") != source_route:
            raise ContractError("source_authority", f"page route changed: {page_key}")
        for field in ("source_file", "dto_file", "mock_fixture_path"):
            require_relative_path(page.get(field), f"{label}.{field}")
        for field in ("root_symbol", "dto_symbol", "ui_state_symbol", "responsive_strategy"):
            require_string(page.get(field), f"{label}.{field}")
        page_has_api_dependency = any(
            fact.get("page_key") == page_key and fact.get("kind") == "api_dependency"
            for fact in universe["semantic_facts"]
        )
        if page_has_api_dependency:
            require_string(page.get("api_adapter_symbol"), f"{label}.api_adapter_symbol")
        elif page.get("api_adapter_symbol") is not None:
            require_string(page.get("api_adapter_symbol"), f"{label}.api_adapter_symbol")
        page_instances = require_string_list(
            page.get("component_instance_ids"), f"{label}.component_instance_ids"
        )
        expected_page_instances = [
            item["component_instance_id"]
            for item in universe["component_instances"]
            if item["page_key"] == page_key
        ]
        if page_instances != expected_page_instances:
            raise ContractError("coverage_incomplete", f"page component coverage changed: {page_key}")
        covered_instances.extend(page_instances)
        pages.append(page.copy())
    if [item["page_key"] for item in pages] != universe["page_keys"] or covered_instances != list(expected_instances):
        raise ContractError("coverage_incomplete", "every modify page and component instance is required")

    blocks_by_instance: dict[str, list[str]] = {}
    for block in universe["blocks"]:
        blocks_by_instance.setdefault(block["component_instance_id"], []).append(block["obligation_id"])
    component_mappings: list[dict[str, Any]] = []
    seen_instances: set[str] = set()
    for index, mapping_value in enumerate(
        require_list(plan.get("component_mappings"), "component mappings")
    ):
        label = f"component_mappings[{index}]"
        mapping = require_dict(mapping_value, label)
        require_exact_keys(
            mapping,
            {
                "component_instance_id",
                "component_id",
                "page_key",
                "source_file",
                "symbol",
                "platform_primitive",
                "responsive_strategy",
                "block_obligation_ids",
            },
            label,
        )
        instance_id = require_string(mapping.get("component_instance_id"), f"{label}.component_instance_id")
        expected = expected_instances.get(instance_id)
        if expected is None or instance_id in seen_instances:
            raise ContractError("coverage_incomplete", f"invalid component mapping {instance_id}")
        seen_instances.add(instance_id)
        if mapping.get("component_id") != expected["component_id"] or mapping.get("page_key") != expected["page_key"]:
            raise ContractError("coverage_incomplete", f"component identity changed: {instance_id}")
        require_relative_path(mapping.get("source_file"), f"{label}.source_file")
        for field in ("symbol", "platform_primitive", "responsive_strategy"):
            require_string(mapping.get(field), f"{label}.{field}")
        if require_string_list(
            mapping.get("block_obligation_ids"), f"{label}.block_obligation_ids", nonempty=False
        ) != blocks_by_instance.get(instance_id, []):
            raise ContractError("coverage_incomplete", f"component Block coverage changed: {instance_id}")
        component_mappings.append(mapping.copy())
    if seen_instances != set(expected_instances):
        raise ContractError("coverage_incomplete", "every component instance needs one implementation mapping")

    def validate_obligation_mappings(
        field: str,
        universe_field: str,
        *,
        include_fact_id: bool,
        include_assets: bool = False,
    ) -> list[dict[str, Any]]:
        expected = {item["obligation_id"]: item for item in universe[universe_field]}
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        expected_keys = {"obligation_id", "source_file", "symbol", "implementation_anchor"}
        if include_fact_id:
            expected_keys.add("fact_id")
        if include_assets:
            expected_keys.add("asset_mappings")
        for index, value in enumerate(require_list(plan.get(field), field)):
            label = f"{field}[{index}]"
            item = require_dict(value, label)
            require_exact_keys(item, expected_keys, label)
            obligation = require_string(item.get("obligation_id"), f"{label}.obligation_id")
            source = expected.get(obligation)
            if source is None or obligation in seen:
                raise ContractError("coverage_incomplete", f"invalid obligation mapping {obligation}")
            seen.add(obligation)
            if include_fact_id and item.get("fact_id") != source.get("fact_id"):
                raise ContractError("coverage_incomplete", f"fact identity changed: {obligation}")
            require_relative_path(item.get("source_file"), f"{label}.source_file")
            require_string(item.get("symbol"), f"{label}.symbol")
            if item.get("implementation_anchor") != "ICP:" + obligation:
                raise ContractError("invalid_plan", f"implementation anchor changed: {obligation}")
            if include_assets:
                source_assets = {
                    asset["asset_id"]: asset
                    for asset in require_list(source.get("assets"), "design element assets")
                }
                asset_mappings = require_list(
                    item.get("asset_mappings"), f"{label}.asset_mappings"
                )
                if source_assets and not asset_mappings:
                    raise ContractError(
                        "asset_consumption_missing",
                        f"exported asset is not consumed: {obligation}",
                    )
                if not source_assets and asset_mappings:
                    raise ContractError(
                        "asset_consumption_missing",
                        f"asset mapping has no source asset: {obligation}",
                    )
                seen_assets: set[str] = set()
                normalized_assets: list[dict[str, Any]] = []
                for asset_index, asset_value in enumerate(asset_mappings):
                    asset_label = f"{label}.asset_mappings[{asset_index}]"
                    asset_mapping = require_dict(asset_value, asset_label)
                    require_exact_keys(
                        asset_mapping,
                        {
                            "source_asset_id",
                            "source_asset_sha256",
                            "target_resource_path",
                        },
                        asset_label,
                    )
                    asset_id = require_string(
                        asset_mapping.get("source_asset_id"),
                        f"{asset_label}.source_asset_id",
                    )
                    source_asset = source_assets.get(asset_id)
                    if (
                        source_asset is None
                        or asset_id in seen_assets
                        or asset_mapping.get("source_asset_sha256")
                        != source_asset.get("sha256")
                    ):
                        raise ContractError(
                            "asset_consumption_missing",
                            f"asset mapping does not match a frozen source asset: {obligation}",
                        )
                    seen_assets.add(asset_id)
                    require_relative_path(
                        asset_mapping.get("target_resource_path"),
                        f"{asset_label}.target_resource_path",
                    )
                    normalized_assets.append(asset_mapping.copy())
                item = {**item, "asset_mappings": normalized_assets}
            normalized.append(item.copy())
        if seen != set(expected):
            raise ContractError("coverage_incomplete", f"every {universe_field} obligation needs one mapping")
        return normalized

    design_mappings = validate_obligation_mappings(
        "design_element_mappings",
        "design_elements",
        include_fact_id=False,
        include_assets=True,
    )
    fact_mappings = validate_obligation_mappings(
        "semantic_fact_mappings", "semantic_facts", include_fact_id=True
    )

    expected_integrations = {
        item["obligation_id"]: item for item in universe["integration_obligations"]
    }
    cases: list[dict[str, Any]] = []
    seen_integrations: set[str] = set()
    case_ids: set[str] = set()
    for index, case_value in enumerate(
        require_list(plan.get("integration_test_cases"), "integration test cases")
    ):
        label = f"integration_test_cases[{index}]"
        case = require_dict(case_value, label)
        require_exact_keys(
            case,
            {
                "case_id",
                "obligation_id",
                "source_kind",
                "fact_id",
                "basis_fact_ids",
                "component_instance_id",
                "page_key",
                "test_file",
                "test_name",
                "command",
            },
            label,
        )
        case_id = require_string(case.get("case_id"), f"{label}.case_id")
        obligation = require_string(case.get("obligation_id"), f"{label}.obligation_id")
        expected = expected_integrations.get(obligation)
        if (
            expected is None
            or obligation in seen_integrations
            or case_id in case_ids
            or case.get("fact_id") != expected["fact_id"]
            or case.get("source_kind") != expected["source_kind"]
            or case.get("basis_fact_ids") != expected["basis_fact_ids"]
            or case.get("component_instance_id") != expected["component_instance_id"]
            or case.get("page_key") != expected["page_key"]
        ):
            raise ContractError("coverage_incomplete", f"invalid integration case {case_id}")
        seen_integrations.add(obligation)
        case_ids.add(case_id)
        require_relative_path(case.get("test_file"), f"{label}.test_file")
        require_string(case.get("test_name"), f"{label}.test_name")
        validate_command(case.get("command"), f"{label}.command")
        cases.append(case.copy())
    if seen_integrations != set(expected_integrations):
        raise ContractError(
            "coverage_incomplete",
            "every IT, interaction-description, and model-inference obligation needs one integration test case",
        )

    expected_presentations = {item["usage_id"] for item in universe["presentation_usages"]}
    seen_presentations: set[str] = set()
    presentations: list[dict[str, Any]] = []
    for index, value in enumerate(require_list(plan.get("presentation_mappings"), "presentation mappings")):
        label = f"presentation_mappings[{index}]"
        item = require_dict(value, label)
        require_exact_keys(item, {"usage_id", "source_file", "symbol", "implementation_anchor"}, label)
        usage_id = require_string(item.get("usage_id"), f"{label}.usage_id")
        if usage_id not in expected_presentations or usage_id in seen_presentations:
            raise ContractError("coverage_incomplete", f"invalid presentation mapping {usage_id}")
        seen_presentations.add(usage_id)
        require_relative_path(item.get("source_file"), f"{label}.source_file")
        require_string(item.get("symbol"), f"{label}.symbol")
        if item.get("implementation_anchor") != "ICP:presentation:" + usage_id:
            raise ContractError("invalid_plan", f"presentation anchor changed: {usage_id}")
        presentations.append(item.copy())
    if seen_presentations != expected_presentations:
        raise ContractError("coverage_incomplete", "every presentation usage needs one implementation mapping")

    references = {
        item["design_name"]: item for item in universe["visual_references"]
    }
    visual_capture_cases: list[dict[str, Any]] = []
    seen_visuals: set[str] = set()
    for index, value in enumerate(
        require_list(plan.get("visual_capture_cases"), "visual capture cases")
    ):
        label = f"visual_capture_cases[{index}]"
        item = require_dict(value, label)
        require_exact_keys(
            item,
            {"design_name", "package_name", "locale", "state_setup_commands"},
            label,
        )
        design_name = require_string(item.get("design_name"), f"{label}.design_name")
        if design_name not in references or design_name in seen_visuals:
            raise ContractError(
                "coverage_incomplete", f"invalid visual capture case: {design_name}"
            )
        seen_visuals.add(design_name)
        require_string(item.get("package_name"), f"{label}.package_name")
        require_string(item.get("locale"), f"{label}.locale")
        commands = require_list(
            item.get("state_setup_commands"), f"{label}.state_setup_commands"
        )
        for command_index, command in enumerate(commands):
            validate_command(
                command, f"{label}.state_setup_commands[{command_index}]"
            )
        visual_capture_cases.append(item.copy())
    if seen_visuals != set(references):
        raise ContractError(
            "coverage_incomplete", "every design state needs one visual capture case"
        )

    commands = require_dict(plan.get("verification_commands"), "verification commands")
    require_exact_keys(commands, {"lint", "build", "integration"}, "verification commands")
    for kind in ("lint", "build", "integration"):
        values = require_list(commands.get(kind), f"verification commands {kind}")
        if not values:
            raise ContractError("invalid_plan", f"verification commands {kind} cannot be empty")
        for index, command in enumerate(values):
            validate_command(command, f"verification commands {kind}[{index}]")
    return {
        **plan,
        "pages": pages,
        "component_mappings": component_mappings,
        "design_element_mappings": design_mappings,
        "semantic_fact_mappings": fact_mappings,
        "integration_test_cases": cases,
        "presentation_mappings": presentations,
        "visual_capture_cases": visual_capture_cases,
    }


def build_codegen_packet(
    page_key: str, plan: dict[str, Any], universe: dict[str, Any]
) -> dict[str, Any]:
    page = next(item for item in plan["pages"] if item["page_key"] == page_key)
    instance_ids = set(page["component_instance_ids"])
    fact_ids = {
        binding["fact_id"]
        for instance in universe["component_instances"]
        if instance["component_instance_id"] in instance_ids
        for binding in instance["fact_bindings"]
    }
    component_ids = {
        item["component_id"]
        for item in universe["component_instances"]
        if item["component_instance_id"] in instance_ids
    }
    return {
        "schema": "icp.implementation.codegen-packet.v1",
        "source_authority": universe["source_authority"],
        "common_rules": plan["common_rules"],
        "platform_best_practices": plan["platform_best_practices"],
        "implementation_prompt": plan["implementation_prompt"],
        "page": page,
        "locked_page": next(item for item in universe["pages"] if item["page_key"] == page_key),
        "component_definitions": [
            item for item in universe["component_definitions"] if item["component_id"] in component_ids
        ],
        "component_instances": [
            item for item in universe["component_instances"] if item["component_instance_id"] in instance_ids
        ],
        "component_mappings": [
            item for item in plan["component_mappings"] if item["component_instance_id"] in instance_ids
        ],
        "blocks": [item for item in universe["blocks"] if item["component_instance_id"] in instance_ids],
        "design_elements": [
            item for item in universe["design_elements"] if item["component_instance_id"] in instance_ids
        ],
        "design_element_mappings": [
            item
            for item in plan["design_element_mappings"]
            if item["obligation_id"]
            in {value["obligation_id"] for value in universe["design_elements"] if value["component_instance_id"] in instance_ids}
        ],
        "semantic_facts": [item for item in universe["semantic_facts"] if item["fact_id"] in fact_ids],
        "semantic_fact_mappings": [item for item in plan["semantic_fact_mappings"] if item["fact_id"] in fact_ids],
        "integration_obligations": [item for item in universe["integration_obligations"] if item["page_key"] == page_key],
        "integration_test_cases": [item for item in plan["integration_test_cases"] if item["page_key"] == page_key],
        "presentation_usages": [item for item in universe["presentation_usages"] if item["source_page_key"] == page_key],
        "presentation_mappings": [
            item
            for item in plan["presentation_mappings"]
            if item["usage_id"] in {value["usage_id"] for value in universe["presentation_usages"] if value["source_page_key"] == page_key}
        ],
        "visual_capture_cases": [
            item
            for item in plan["visual_capture_cases"]
            if item["design_name"]
            in {
                block["design_name"]
                for block in universe["blocks"]
                if block["component_instance_id"] in instance_ids
            }
        ],
    }


def record_plan(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state, universe = load_live_stage(project_root)
    if state.get("state") != "awaiting_plan":
        raise ContractError("invalid_state", f"implementation state is {state.get('state')}")
    plan = validate_plan(read_json(Path(args.plan)), state, universe)
    plan_path = stage_dir / "implementation-plan.json"
    if plan_path.exists():
        raise ContractError("plan_already_recorded", "implementation plan is append-only")
    atomic_write_json(plan_path, plan)
    for page_key in universe["page_keys"]:
        atomic_write_json(
            stage_dir / "codegen-packets" / f"{page_key}.json",
            build_codegen_packet(page_key, plan, universe),
        )
    atomic_write_json(
        stage_dir / "tdd-evidence.json",
        {
            "schema": "icp.implementation.tdd-evidence.v1",
            "implementation_plan_sha256": file_sha(plan_path),
            "cases": [
                {
                    "case_id": case["case_id"],
                    "obligation_id": case["obligation_id"],
                    "source_kind": case["source_kind"],
                    "fact_id": case["fact_id"],
                    "basis_fact_ids": case["basis_fact_ids"],
                    "component_instance_id": case["component_instance_id"],
                    "command": case["command"],
                    "red": None,
                    "green": None,
                }
                for case in plan["integration_test_cases"]
            ],
        },
    )
    state["implementation_plan_sha256"] = file_sha(plan_path)
    state["tdd_evidence_sha256"] = file_sha(stage_dir / "tdd-evidence.json")
    state["state"] = "awaiting_red" if plan["integration_test_cases"] else "awaiting_implementation"
    atomic_write_json(stage_dir / "state.json", state)
    return {
        "ok": True,
        "stage": "implementation",
        "state": state["state"],
        "page_count": len(plan["pages"]),
        "integration_case_count": len(plan["integration_test_cases"]),
    }


def run_case(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    with exclusive_case_recording(project_root):
        return run_case_locked(args, project_root)


def run_case_locked(
    args: argparse.Namespace, project_root: Path
) -> dict[str, Any]:
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    if not plan_path.is_file() or file_sha(plan_path) != state.get("implementation_plan_sha256"):
        raise ContractError("stage_drift", "implementation plan changed")
    plan = validate_plan(read_json(plan_path), state, universe)
    evidence_path = stage_dir / "tdd-evidence.json"
    if not evidence_path.is_file() or file_sha(evidence_path) != state.get("tdd_evidence_sha256"):
        raise ContractError("stage_drift", "TDD evidence changed")
    evidence = require_dict(read_json(evidence_path), "TDD evidence")
    case_id = args.case_id
    planned_case = next(
        (item for item in plan["integration_test_cases"] if item["case_id"] == case_id),
        None,
    )
    evidence_case = next(
        (item for item in evidence["cases"] if item["case_id"] == case_id), None
    )
    if planned_case is None or evidence_case is None:
        raise ContractError("unknown_case", f"unknown integration case: {case_id}")
    phase = args.phase
    if phase == "red":
        if state.get("state") != "awaiting_red" or evidence_case.get("red") is not None:
            raise ContractError("invalid_state", f"RED is not pending for {case_id}")
    elif phase == "green":
        if any(item.get("red") is None for item in evidence["cases"]):
            raise ContractError("red_required", "all integration cases must observe RED before implementation")
        if state.get("state") not in {"awaiting_implementation", "awaiting_verification"}:
            raise ContractError("invalid_state", f"GREEN is not pending for {case_id}")
        if evidence_case.get("red") is None or evidence_case.get("green") is not None:
            raise ContractError("red_required", f"a fresh RED is required for {case_id}")
    else:
        raise ContractError("invalid_phase", f"unsupported TDD phase: {phase}")
    command = validate_command(planned_case.get("command"), "planned test command")
    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=1200,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError("test_command_failed", f"cannot execute {case_id}: {exc}") from exc
    result = {
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }
    if phase == "red" and completed.returncode == 0:
        raise ContractError("red_not_observed", f"test already passes before implementation: {case_id}")
    if phase == "green" and completed.returncode != 0:
        raise ContractError("green_not_observed", f"test still fails after implementation: {case_id}")
    evidence_case[phase] = result
    atomic_write_json(evidence_path, evidence)
    state["tdd_evidence_sha256"] = file_sha(evidence_path)
    if phase == "red" and all(item.get("red") is not None for item in evidence["cases"]):
        state["state"] = "awaiting_implementation"
    if phase == "green" and all(item.get("green") is not None for item in evidence["cases"]):
        state["state"] = "awaiting_verification"
    atomic_write_json(stage_dir / "state.json", state)
    return {
        "ok": True,
        "stage": "implementation",
        "state": state["state"],
        "case_id": case_id,
        "phase": phase,
        "exit_code": completed.returncode,
    }


def project_file(project_root: Path, relative: object, label: str) -> Path:
    text = require_relative_path(relative, label)
    path = (project_root / text).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise ContractError("invalid_evidence", f"{label} escapes the project") from exc
    return path


def read_png_rgba(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContractError("visual_evidence_invalid", f"cannot read PNG: {path}") from exc
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ContractError("visual_evidence_invalid", f"not a PNG: {path}")
    position = 8
    width = height = color_type = bit_depth = None
    palette: list[tuple[int, int, int]] = []
    transparency: list[int] = []
    chunks: list[bytes] = []
    while position < len(data):
        if position + 12 > len(data):
            raise ContractError("visual_evidence_invalid", f"truncated PNG: {path}")
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if bit_depth != 8 or interlace != 0:
                raise ContractError(
                    "visual_evidence_invalid", "only 8-bit non-interlaced PNG is supported"
                )
        elif kind == b"PLTE":
            palette = [tuple(body[index : index + 3]) for index in range(0, len(body), 3)]
        elif kind == b"tRNS":
            transparency = list(body)
        elif kind == b"IDAT":
            chunks.append(body)
        elif kind == b"IEND":
            break
    if width is None or height is None or color_type is None:
        raise ContractError("visual_evidence_invalid", f"PNG missing IHDR: {path}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ContractError("visual_evidence_invalid", f"unsupported PNG color type: {color_type}")
    try:
        raw = zlib.decompress(b"".join(chunks))
    except zlib.error as exc:
        raise ContractError("visual_evidence_invalid", f"invalid PNG compression: {path}") from exc
    stride = width * channels
    rows: list[bytes] = []
    previous = [0] * stride
    offset = 0
    for _ in range(height):
        if offset + stride + 1 > len(raw):
            raise ContractError("visual_evidence_invalid", f"truncated PNG pixels: {path}")
        filter_type = raw[offset]
        offset += 1
        row = list(raw[offset : offset + stride])
        offset += stride
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (value + up) & 0xFF
            elif filter_type == 3:
                row[index] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                predictor = left + up - up_left
                distances = (abs(predictor - left), abs(predictor - up), abs(predictor - up_left))
                predicted = left if distances[0] <= distances[1] and distances[0] <= distances[2] else up if distances[1] <= distances[2] else up_left
                row[index] = (value + predicted) & 0xFF
            elif filter_type != 0:
                raise ContractError("visual_evidence_invalid", f"unsupported PNG filter: {filter_type}")
        previous = row
        rows.append(bytes(row))
    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for x in range(width):
            index = x * channels
            if color_type == 0:
                gray = row[index]
                pixels.append((gray, gray, gray, 255))
            elif color_type == 2:
                pixels.append((row[index], row[index + 1], row[index + 2], 255))
            elif color_type == 3:
                palette_index = row[index]
                red, green, blue = palette[palette_index]
                alpha = transparency[palette_index] if palette_index < len(transparency) else 255
                pixels.append((red, green, blue, alpha))
            elif color_type == 4:
                gray, alpha = row[index], row[index + 1]
                pixels.append((gray, gray, gray, alpha))
            else:
                pixels.append((row[index], row[index + 1], row[index + 2], row[index + 3]))
    return width, height, pixels


def image_comparison(
    reference: Path, actual: Path
) -> tuple[int, int, float, dict[str, int] | None]:
    ref_width, ref_height, ref_pixels = read_png_rgba(reference)
    actual_width, actual_height, actual_pixels = read_png_rgba(actual)
    if (ref_width, ref_height) != (actual_width, actual_height):
        raise ContractError(
            "visual_size_mismatch",
            f"actual screenshot {actual_width}x{actual_height} differs from reference {ref_width}x{ref_height}",
        )
    total = 0
    left = top = None
    right = bottom = None
    for index, (reference_pixel, actual_pixel) in enumerate(
        zip(ref_pixels, actual_pixels, strict=True)
    ):
        total += sum(
            abs(reference_pixel[channel] - actual_pixel[channel])
            for channel in range(3)
        )
        if reference_pixel[:3] == actual_pixel[:3]:
            continue
        x = index % ref_width
        y = index // ref_width
        left = x if left is None else min(left, x)
        top = y if top is None else min(top, y)
        right = x + 1 if right is None else max(right, x + 1)
        bottom = y + 1 if bottom is None else max(bottom, y + 1)
    bbox = (
        None
        if left is None
        else {"left": left, "top": top, "right": right, "bottom": bottom}
    )
    return ref_width, ref_height, total / (len(ref_pixels) * 3), bbox


def image_mae(reference: Path, actual: Path) -> tuple[int, int, float]:
    width, height, mae, _bbox = image_comparison(reference, actual)
    return width, height, mae


def write_png_rgba(
    path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]
) -> None:
    if len(pixels) != width * height:
        raise ContractError("visual_capture_failed", "PNG pixel count is invalid")

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        row = bytearray([0])
        for pixel in pixels[y * width : (y + 1) * width]:
            row.extend(pixel)
        rows.append(bytes(row))
    body = b"\x89PNG\r\n\x1a\n"
    body += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    body += chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    body += chunk(b"IEND", b"")
    atomic_write(path, body)


def resize_png(reference_size: tuple[int, int], source: Path, target: Path) -> tuple[int, int]:
    source_width, source_height, source_pixels = read_png_rgba(source)
    target_width, target_height = reference_size
    if (source_width, source_height) == reference_size:
        atomic_write(target, source.read_bytes())
        return source_width, source_height
    resized: list[tuple[int, int, int, int]] = []
    for y in range(target_height):
        source_y = (y + 0.5) * source_height / target_height - 0.5
        y0 = max(0, min(source_height - 1, math.floor(source_y)))
        y1 = max(0, min(source_height - 1, y0 + 1))
        y_weight = max(0.0, min(1.0, source_y - y0))
        for x in range(target_width):
            source_x = (x + 0.5) * source_width / target_width - 0.5
            x0 = max(0, min(source_width - 1, math.floor(source_x)))
            x1 = max(0, min(source_width - 1, x0 + 1))
            x_weight = max(0.0, min(1.0, source_x - x0))
            values = []
            for channel in range(4):
                top = (
                    source_pixels[y0 * source_width + x0][channel] * (1 - x_weight)
                    + source_pixels[y0 * source_width + x1][channel] * x_weight
                )
                bottom = (
                    source_pixels[y1 * source_width + x0][channel] * (1 - x_weight)
                    + source_pixels[y1 * source_width + x1][channel] * x_weight
                )
                values.append(round(top * (1 - y_weight) + bottom * y_weight))
            resized.append(tuple(values))
    write_png_rgba(target, target_width, target_height, resized)
    return source_width, source_height


def validate_device_configuration(value: object, label: str) -> dict[str, Any]:
    config = require_dict(value, label)
    require_exact_keys(
        config,
        {
            "size",
            "size_override",
            "density",
            "density_override",
            "locale",
            "font_scale",
            "navigation_mode",
        },
        label,
    )
    size = require_dict(config.get("size"), f"{label}.size")
    require_exact_keys(size, {"width", "height"}, f"{label}.size")
    if (
        type(size.get("width")) is not int
        or type(size.get("height")) is not int
        or size["width"] <= 0
        or size["height"] <= 0
        or type(config.get("density")) is not int
        or config["density"] <= 0
        or type(config.get("size_override")) is not bool
        or type(config.get("density_override")) is not bool
    ):
        raise ContractError("visual_capture_failed", f"{label} geometry is invalid")
    for field in ("locale", "font_scale", "navigation_mode"):
        require_string(config.get(field), f"{label}.{field}")
    return config.copy()


def run_driver(
    driver: str, operation: str, package_name: str, **paths: Path
) -> subprocess.CompletedProcess[str]:
    command = [driver, operation, "--package", package_name]
    for field, path in paths.items():
        command.extend(["--" + field.replace("_", "-"), str(path)])
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=1200,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(
            "visual_capture_failed", f"cannot run visual driver {operation}: {exc}"
        ) from exc


def capture_visual(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    if not plan_path.is_file() or file_sha(plan_path) != state.get(
        "implementation_plan_sha256"
    ):
        raise ContractError("stage_drift", "implementation plan changed")
    plan = validate_plan(read_json(plan_path), state, universe)
    design_name = args.design_name
    reference = next(
        (item for item in universe["visual_references"] if item["design_name"] == design_name),
        None,
    )
    capture_case = next(
        (item for item in plan["visual_capture_cases"] if item["design_name"] == design_name),
        None,
    )
    if reference is None or capture_case is None:
        raise ContractError("visual_capture_failed", f"unknown design state: {design_name}")
    driver = require_string(args.driver, "visual driver")
    package_name = capture_case["package_name"]
    before_result = run_driver(driver, "snapshot", package_name)
    if before_result.returncode != 0:
        raise ContractError(
            "visual_capture_failed",
            "visual driver snapshot failed: " + before_result.stderr[-2000:],
        )
    try:
        before = validate_device_configuration(
            json.loads(before_result.stdout), "device configuration before capture"
        )
    except json.JSONDecodeError as exc:
        raise ContractError(
            "visual_capture_failed", "visual driver snapshot returned invalid JSON"
        ) from exc
    pixel_size = require_dict(reference.get("pixel_size"), "reference pixel size")
    require_exact_keys(pixel_size, {"width", "height"}, "reference pixel size")
    if any(
        type(pixel_size.get(field)) is not int or pixel_size[field] <= 0
        for field in ("width", "height")
    ):
        raise ContractError("visual_capture_failed", "reference pixel size is invalid")
    try:
        logical_scale = float(reference["logical_scale"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("visual_capture_failed", "reference logical scale is invalid") from exc
    if logical_scale <= 0:
        raise ContractError("visual_capture_failed", "reference logical scale is invalid")
    applied = {
        "size": {"width": pixel_size["width"], "height": pixel_size["height"]},
        "size_override": True,
        "density": round(160 * logical_scale),
        "density_override": True,
        "locale": capture_case["locale"],
        "font_scale": before["font_scale"],
        "navigation_mode": before["navigation_mode"],
    }
    runtime_dir = stage_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    stem = digest({"design_name": design_name})[:20]
    before_path = runtime_dir / f"{stem}.before.json"
    applied_path = runtime_dir / f"{stem}.applied.json"
    raw_path = runtime_dir / f"{stem}.raw.png"
    actual_path = runtime_dir / f"{stem}.png"
    evidence_path = runtime_dir / f"{stem}.capture.json"
    atomic_write_json(before_path, before)
    atomic_write_json(applied_path, applied)
    failure: ContractError | None = None
    raw_size: tuple[int, int] | None = None
    restored: dict[str, Any] | None = None
    try:
        applied_result = run_driver(
            driver, "apply", package_name, config=applied_path
        )
        if applied_result.returncode != 0:
            raise ContractError(
                "visual_capture_failed",
                "visual driver apply failed: " + applied_result.stderr[-2000:],
            )
        for command in capture_case["state_setup_commands"]:
            completed = subprocess.run(
                command,
                cwd=project_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=1200,
            )
            if completed.returncode != 0:
                raise ContractError(
                    "visual_capture_failed",
                    "visual state setup failed: " + completed.stderr[-2000:],
                )
        captured = run_driver(driver, "capture", package_name, output=raw_path)
        if captured.returncode != 0:
            raise ContractError(
                "visual_capture_failed",
                "visual driver capture failed: " + captured.stderr[-2000:],
            )
        raw_size = resize_png(
            (pixel_size["width"], pixel_size["height"]), raw_path, actual_path
        )
    except ContractError as exc:
        failure = exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        failure = ContractError("visual_capture_failed", f"visual capture failed: {exc}")
    finally:
        restored_result = run_driver(
            driver, "restore", package_name, config=before_path
        )
        if restored_result.returncode == 0:
            snapshot_result = run_driver(driver, "snapshot", package_name)
            if snapshot_result.returncode == 0:
                try:
                    restored = validate_device_configuration(
                        json.loads(snapshot_result.stdout),
                        "device configuration after restore",
                    )
                except (json.JSONDecodeError, ContractError):
                    restored = None
        if restored != before:
            raise ContractError(
                "visual_restore_failed",
                "device size, density, locale, font scale, or navigation mode was not restored",
            )
    if failure is not None:
        raise failure
    if raw_size is None or not actual_path.is_file():
        raise ContractError("visual_capture_failed", "visual capture produced no screenshot")
    evidence = {
        "schema": "icp.implementation.visual-capture-evidence.v1",
        "evaluation_scope": "reference_viewport_visual_fidelity",
        "implementation_plan_sha256": state["implementation_plan_sha256"],
        "design_name": design_name,
        "reference_sha256": reference["sha256"],
        "logical_artboard_size": reference["logical_artboard_size"],
        "reference_pixel_size": pixel_size,
        "logical_scale": reference["logical_scale"],
        "capture_strategy": "extended-viewport-full-page",
        "before": before,
        "applied": applied,
        "raw_pixel_size": list(raw_size),
        "actual_screenshot": str(actual_path.relative_to(project_root)),
        "actual_sha256": file_sha(actual_path),
        "restored": restored,
        "restore_exact": restored == before,
    }
    atomic_write_json(evidence_path, evidence)
    return {
        "ok": True,
        "stage": "implementation",
        "design_name": design_name,
        "actual_screenshot": str(actual_path.relative_to(project_root)),
        "capture_evidence": str(evidence_path.relative_to(project_root)),
    }


def read_required_text(project_root: Path, relative: object, label: str) -> tuple[Path, str]:
    path = project_file(project_root, relative, label)
    try:
        return path, path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError("code_coverage_missing", f"cannot read {label}: {path}") from exc


def verify_code_coverage(
    project_root: Path, plan: dict[str, Any], universe: dict[str, Any]
) -> dict[str, Any]:
    texts: dict[str, tuple[Path, str]] = {}

    def text_for(relative: str, label: str) -> tuple[Path, str]:
        if relative not in texts:
            texts[relative] = read_required_text(project_root, relative, label)
        return texts[relative]

    for page in plan["pages"]:
        _, source = text_for(page["source_file"], f"page source {page['page_key']}")
        if page["root_symbol"] not in source:
            raise ContractError("code_coverage_missing", f"page root symbol is missing: {page['root_symbol']}")
        _, dto_source = text_for(page["dto_file"], f"page DTO {page['page_key']}")
        for symbol in (page["dto_symbol"], page["ui_state_symbol"]):
            if symbol not in dto_source:
                raise ContractError("code_coverage_missing", f"page data symbol is missing: {symbol}")
        if page["api_adapter_symbol"] is not None and page["api_adapter_symbol"] not in dto_source:
            raise ContractError(
                "code_coverage_missing",
                f"page API adapter symbol is missing: {page['api_adapter_symbol']}",
            )
        mock_path = project_file(project_root, page["mock_fixture_path"], "page mock fixture")
        try:
            json.loads(mock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError("code_coverage_missing", f"page mock fixture is invalid: {mock_path}") from exc
    for mapping in plan["component_mappings"]:
        _, source = text_for(mapping["source_file"], f"component {mapping['component_instance_id']}")
        if mapping["symbol"] not in source:
            raise ContractError("code_coverage_missing", f"component symbol is missing: {mapping['symbol']}")
    for field in ("design_element_mappings", "semantic_fact_mappings", "presentation_mappings"):
        for mapping in plan[field]:
            _, source = text_for(mapping["source_file"], f"{field} source")
            if mapping["implementation_anchor"] not in source or mapping["symbol"] not in source:
                raise ContractError(
                    "code_coverage_missing",
                    f"code anchor or owner symbol is missing: {mapping['implementation_anchor']}",
                )
    design_elements = {
        item["obligation_id"]: item for item in universe["design_elements"]
    }
    asset_files: dict[str, Path] = {}
    for mapping in plan["design_element_mappings"]:
        source_assets = {
            asset["asset_id"]: asset
            for asset in design_elements[mapping["obligation_id"]]["assets"]
        }
        for asset_mapping in mapping["asset_mappings"]:
            source_asset = source_assets[asset_mapping["source_asset_id"]]
            source_path = project_file(
                project_root, source_asset["source_project_path"], "frozen source asset"
            )
            target_path = project_file(
                project_root,
                asset_mapping["target_resource_path"],
                "target resource asset",
            )
            if (
                not source_path.is_file()
                or file_sha(source_path) != source_asset["sha256"]
                or not target_path.is_file()
                or file_sha(target_path) != source_asset["sha256"]
            ):
                raise ContractError(
                    "asset_consumption_missing",
                    "source asset and target resource hashes differ: "
                    + asset_mapping["source_asset_id"],
                )
            asset_files[str(target_path.relative_to(project_root))] = target_path
    return {
        "schema": "icp.implementation.code-manifest.v1",
        "files": [
            {
                "path": str(path.relative_to(project_root)),
                "sha256": file_sha(path),
            }
            for path, _ in sorted(texts.values(), key=lambda item: str(item[0]))
        ]
        + [
            {"path": relative, "sha256": file_sha(path)}
            for relative, path in sorted(asset_files.items())
        ],
    }


def run_verification_commands(project_root: Path, plan: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for kind in ("lint", "build", "integration"):
        for command in plan["verification_commands"][kind]:
            try:
                completed = subprocess.run(
                    command,
                    cwd=project_root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ContractError("verification_command_failed", f"cannot run {kind}: {exc}") from exc
            result = {
                "kind": kind,
                "command": command,
                "exit_code": completed.returncode,
                "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
                "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
            results.append(result)
            if completed.returncode != 0:
                raise ContractError("verification_command_failed", f"{kind} command failed: {command}")
    return results


def validate_runtime_evidence(
    project_root: Path,
    value: object,
    state: dict[str, Any],
    universe: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = require_dict(value, "runtime evidence")
    require_exact_keys(
        evidence,
        {
            "schema",
            "implementation_plan_sha256",
            "adaptive_components",
            "responsive_runs",
            "visual_runs",
        },
        "runtime evidence",
    )
    if (
        evidence.get("schema") != "icp.implementation.runtime-evidence.v1"
        or evidence.get("implementation_plan_sha256") != state.get("implementation_plan_sha256")
    ):
        raise ContractError("invalid_evidence", "runtime evidence targets another implementation plan")

    expected_components = {
        item["component_instance_id"] for item in universe["component_instances"]
    }
    seen_components: set[str] = set()
    for index, value in enumerate(
        require_list(evidence.get("adaptive_components"), "adaptive components")
    ):
        label = f"adaptive_components[{index}]"
        item = require_dict(value, label)
        try:
            require_exact_keys(
                item,
                {
                    "component_instance_id",
                    "constraint_driven",
                    "content_adaptive",
                    "no_content_specific_geometry",
                },
                label,
            )
        except ContractError as exc:
            raise ContractError(
                "responsive_evidence_invalid",
                f"{label} must contain the complete adaptive-component contract",
            ) from exc
        component_id = item.get("component_instance_id")
        if component_id not in expected_components or component_id in seen_components:
            raise ContractError(
                "responsive_evidence_invalid",
                f"unexpected adaptive component: {component_id}",
            )
        seen_components.add(component_id)
        if any(
            item.get(field) is not True
            for field in (
                "constraint_driven",
                "content_adaptive",
                "no_content_specific_geometry",
            )
        ):
            raise ContractError(
                "responsive_evidence_invalid",
                f"component is not adaptive: {component_id}",
            )
    if seen_components != expected_components:
        raise ContractError(
            "responsive_evidence_invalid",
            "every component instance needs one adaptive-layout result",
        )
    responsive_runs = require_list(evidence.get("responsive_runs"), "responsive runs")
    expected_responsive = {
        (page_key, viewport)
        for page_key in universe["page_keys"]
        for viewport in ("compact", "expanded")
    }
    seen_responsive: set[tuple[str, str]] = set()
    for index, value in enumerate(responsive_runs):
        label = f"responsive_runs[{index}]"
        item = require_dict(value, label)
        try:
            require_exact_keys(
                item,
                {
                    "page_key",
                    "viewport",
                    "evaluation_scope",
                    "width",
                    "height",
                    "renders",
                    "natural_text_reflow",
                    "no_clip",
                    "no_overlap",
                    "no_horizontal_overflow",
                    "content_reachable",
                    "controls_operable",
                    "system_bars_correct",
                    "insets_safe",
                },
                label,
            )
        except ContractError as exc:
            raise ContractError(
                "responsive_evidence_invalid",
                f"{label} must contain only responsive-behavior evidence",
            ) from exc
        key = (item.get("page_key"), item.get("viewport"))
        if key not in expected_responsive or key in seen_responsive:
            raise ContractError("responsive_evidence_invalid", f"unexpected responsive run: {key}")
        seen_responsive.add(key)
        if (
            type(item.get("width")) is not int
            or type(item.get("height")) is not int
            or item["width"] <= 0
            or item["height"] <= 0
            or item.get("evaluation_scope") != "responsive_behavior"
            or any(
                item.get(field) is not True
                for field in (
                    "renders",
                    "natural_text_reflow",
                    "no_clip",
                    "no_overlap",
                    "no_horizontal_overflow",
                    "content_reachable",
                    "controls_operable",
                    "system_bars_correct",
                    "insets_safe",
                )
            )
        ):
            raise ContractError("responsive_evidence_invalid", f"responsive run failed: {key}")
    if seen_responsive != expected_responsive:
        raise ContractError("responsive_evidence_invalid", "every page needs compact and expanded runtime evidence")

    references = {item["design_name"]: item for item in universe["visual_references"]}
    visual_runs = require_list(evidence.get("visual_runs"), "visual runs")
    seen_designs: set[str] = set()
    results: list[dict[str, Any]] = []
    for index, value in enumerate(visual_runs):
        label = f"visual_runs[{index}]"
        item = require_dict(value, label)
        try:
            require_exact_keys(
                item,
                {
                    "design_name",
                    "actual_screenshot",
                    "capture_evidence",
                    "reference_fidelity",
                },
                label,
            )
        except ContractError as exc:
            raise ContractError(
                "visual_capture_evidence_missing",
                f"{label} must include deterministic capture evidence",
            ) from exc
        design_name = require_string(item.get("design_name"), f"{label}.design_name")
        reference_fidelity = require_dict(
            item.get("reference_fidelity"), f"{label}.reference_fidelity"
        )
        try:
            require_exact_keys(
                reference_fidelity,
                {"colors", "component_structure", "spacing", "font_sizes"},
                f"{label}.reference_fidelity",
            )
        except ContractError as exc:
            raise ContractError(
                "visual_evidence_invalid",
                f"reference fidelity evidence is incomplete: {design_name}",
            ) from exc
        if any(reference_fidelity.get(field) is not True for field in reference_fidelity):
            raise ContractError(
                "visual_evidence_invalid",
                f"reference fidelity check failed: {design_name}",
            )
        reference = references.get(design_name)
        if reference is None or design_name in seen_designs:
            raise ContractError("visual_evidence_invalid", f"unexpected visual run: {design_name}")
        seen_designs.add(design_name)
        reference_path = project_file(project_root, reference["path"], "visual reference")
        if file_sha(reference_path) != reference["sha256"]:
            raise ContractError("stage_drift", f"visual reference changed: {design_name}")
        actual_path = project_file(project_root, item.get("actual_screenshot"), "actual screenshot")
        capture_path = project_file(
            project_root, item.get("capture_evidence"), "visual capture evidence"
        )
        try:
            capture = require_dict(read_json(capture_path), "visual capture evidence")
            require_exact_keys(
                capture,
                {
                    "schema",
                    "evaluation_scope",
                    "implementation_plan_sha256",
                    "design_name",
                    "reference_sha256",
                    "logical_artboard_size",
                    "reference_pixel_size",
                    "logical_scale",
                    "capture_strategy",
                    "before",
                    "applied",
                    "raw_pixel_size",
                    "actual_screenshot",
                    "actual_sha256",
                    "restored",
                    "restore_exact",
                },
                "visual capture evidence",
            )
            before = validate_device_configuration(capture.get("before"), "capture before")
            applied = validate_device_configuration(capture.get("applied"), "capture applied")
            restored = validate_device_configuration(
                capture.get("restored"), "capture restored"
            )
        except ContractError as exc:
            raise ContractError(
                "visual_capture_evidence_missing",
                f"visual capture evidence is invalid: {design_name}",
            ) from exc
        capture_case = next(
            item
            for item in plan["visual_capture_cases"]
            if item["design_name"] == design_name
        )
        expected_applied = {
            "size": reference["pixel_size"],
            "size_override": True,
            "density": round(160 * float(reference["logical_scale"])),
            "density_override": True,
            "locale": capture_case["locale"],
            "font_scale": before["font_scale"],
            "navigation_mode": before["navigation_mode"],
        }
        if (
            capture.get("schema")
            != "icp.implementation.visual-capture-evidence.v1"
            or capture.get("evaluation_scope")
            != "reference_viewport_visual_fidelity"
            or capture.get("implementation_plan_sha256")
            != state.get("implementation_plan_sha256")
            or capture.get("design_name") != design_name
            or capture.get("reference_sha256") != reference["sha256"]
            or capture.get("logical_artboard_size")
            != reference["logical_artboard_size"]
            or capture.get("reference_pixel_size") != reference["pixel_size"]
            or capture.get("logical_scale") != reference["logical_scale"]
            or capture.get("capture_strategy") != "extended-viewport-full-page"
            or applied != expected_applied
            or restored != before
            or capture.get("restore_exact") is not True
            or capture.get("actual_screenshot") != item.get("actual_screenshot")
            or not actual_path.is_file()
            or capture.get("actual_sha256") != file_sha(actual_path)
        ):
            raise ContractError(
                "visual_capture_evidence_missing",
                f"visual capture conversion or restoration is unproven: {design_name}",
            )
        width, height, mae, difference_bbox = image_comparison(
            reference_path, actual_path
        )
        result = {
            "design_name": design_name,
            "evaluation_scope": "reference_viewport_visual_fidelity",
            "reference_path": reference["path"],
            "reference_sha256": reference["sha256"],
            "actual_screenshot": str(actual_path.relative_to(project_root)),
            "actual_sha256": file_sha(actual_path),
            "capture_evidence": str(capture_path.relative_to(project_root)),
            "capture_evidence_sha256": file_sha(capture_path),
            "width": width,
            "height": height,
            "mae": mae,
            "mae_role": "diagnostic_only",
            "reference_fidelity": reference_fidelity.copy(),
            "status": "pass",
            "difference_bbox": difference_bbox,
        }
        results.append(result)
    if seen_designs != set(references):
        raise ContractError("visual_evidence_invalid", "every design state needs one visual run")
    return evidence.copy(), results


def write_visual_difference_artifacts(
    stage_dir: Path,
    state: dict[str, Any],
    universe: dict[str, Any],
    plan: dict[str, Any],
    visual_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mapping_by_obligation = {
        item["obligation_id"]: item for item in plan["design_element_mappings"]
    }
    failures: list[dict[str, Any]] = []
    for result in visual_results:
        design_name = result["design_name"]
        failures.append(
            {
                **result,
                "blocks": [
                    item for item in universe["blocks"] if item["design_name"] == design_name
                ],
                "design_elements": [
                    {
                        **item,
                        "code_mapping": mapping_by_obligation[item["obligation_id"]],
                    }
                    for item in universe["design_elements"]
                    if item["design_name"] == design_name
                ],
            }
        )
    report = {
        "schema": "icp.implementation.visual-difference-report.v1",
        "implementation_plan_sha256": state["implementation_plan_sha256"],
        "mae_role": "diagnostic_only",
        "diagnostics": failures,
    }
    report_path = stage_dir / "visual-difference-report.json"
    atomic_write_json(report_path, report)
    return failures


def verify_implementation(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    stage_dir, state, universe = load_live_stage(project_root)
    plan_path = stage_dir / "implementation-plan.json"
    if not plan_path.is_file() or file_sha(plan_path) != state.get("implementation_plan_sha256"):
        raise ContractError("stage_drift", "implementation plan changed")
    plan = validate_plan(read_json(plan_path), state, universe)
    evidence_path = stage_dir / "tdd-evidence.json"
    if not evidence_path.is_file() or file_sha(evidence_path) != state.get("tdd_evidence_sha256"):
        raise ContractError("stage_drift", "TDD evidence changed")
    tdd_evidence = require_dict(read_json(evidence_path), "TDD evidence")
    if any(item.get("red") is None or item.get("green") is None for item in tdd_evidence["cases"]):
        raise ContractError("tdd_incomplete", "every integration case needs RED and GREEN evidence")
    if state.get("state") not in {"awaiting_verification", "complete"}:
        if plan["integration_test_cases"] or state.get("state") != "awaiting_implementation":
            raise ContractError("invalid_state", f"implementation state is {state.get('state')}")
    code_manifest = verify_code_coverage(project_root, plan, universe)
    runtime_evidence, visual_results = validate_runtime_evidence(
        project_root, read_json(Path(args.evidence)), state, universe, plan
    )
    write_visual_difference_artifacts(
        stage_dir, state, universe, plan, visual_results
    )
    command_results = run_verification_commands(project_root, plan)
    atomic_write_json(stage_dir / "implementation-manifest.json", code_manifest)
    atomic_write_json(stage_dir / "runtime-evidence.json", runtime_evidence)
    stage_result = {
        "schema": "icp.implementation.stage-result.v1",
        "status": "complete",
        "component_lock_sha256": state["component_lock_sha256"],
        "implementation_plan_sha256": state["implementation_plan_sha256"],
        "tdd_evidence_sha256": state["tdd_evidence_sha256"],
        "implementation_manifest_sha256": file_sha(stage_dir / "implementation-manifest.json"),
        "runtime_evidence_sha256": file_sha(stage_dir / "runtime-evidence.json"),
        "design_element_count": len(universe["design_elements"]),
        "semantic_fact_count": len(universe["semantic_facts"]),
        "integration_case_count": len(plan["integration_test_cases"]),
        "responsive_run_count": len(runtime_evidence["responsive_runs"]),
        "visual_results": visual_results,
        "verification_commands": command_results,
    }
    atomic_write_json(stage_dir / "stage-result.json", stage_result)
    state["implementation_manifest_sha256"] = stage_result["implementation_manifest_sha256"]
    state["runtime_evidence_sha256"] = stage_result["runtime_evidence_sha256"]
    state["stage_result_sha256"] = file_sha(stage_dir / "stage-result.json")
    state["state"] = "complete"
    atomic_write_json(stage_dir / "state.json", state)
    return {
        "ok": True,
        "stage": "implementation",
        "state": "complete",
        "design_element_count": stage_result["design_element_count"],
        "integration_case_count": stage_result["integration_case_count"],
        "visual_results": visual_results,
    }


def begin(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    platform = args.platform
    rules_path = PLATFORM_RULES.get(platform)
    if rules_path is None:
        raise ContractError("unsupported_platform", f"unsupported platform: {platform}")
    stage_dir = implementation_dir(project_root)
    if stage_dir.exists():
        raise ContractError("implementation_exists", f"implementation stage already exists: {stage_dir}")
    component_dir, lock, bindings = verify_component_design(project_root)
    universe = build_coverage_universe(project_root, lock, bindings)
    rules = rules_path.read_bytes()
    platform_rules = rules.decode("utf-8")
    prompt_raw = IMPLEMENTATION_PROMPT.read_bytes()
    prompt = prompt_raw.decode("utf-8")
    common_rules_path = project_root / COMMON_RULES_PROJECT_PATH
    try:
        common_rules_raw = common_rules_path.read_bytes()
        common_rules = common_rules_raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError(
            "common_rules_missing",
            f"project common rules must be readable UTF-8: {common_rules_path}",
        ) from exc
    if not common_rules.strip():
        raise ContractError("common_rules_missing", "project common-rules.md is empty")
    state = {
        "schema": "icp.implementation.state.v1",
        "state": "awaiting_plan",
        "platform": platform,
        "component_lock_sha256": file_sha(component_dir / "component-lock.json"),
        "block_component_bindings_sha256": file_sha(
            component_dir / "block-component-bindings.json"
        ),
        "coverage_universe_sha256": hashlib.sha256(json_bytes(universe)).hexdigest(),
        "platform_rules_sha256": hashlib.sha256(rules).hexdigest(),
        "common_rules_sha256": hashlib.sha256(common_rules_raw).hexdigest(),
        "implementation_prompt_sha256": hashlib.sha256(prompt_raw).hexdigest(),
    }
    atomic_write_json(stage_dir / "coverage-universe.json", universe)
    atomic_write(stage_dir / "platform-best-practices.md", rules)
    atomic_write(stage_dir / "common-rules.md", common_rules_raw)
    atomic_write(stage_dir / "implementation-prompt.md", prompt_raw)
    atomic_write_json(
        stage_dir / "implementation-plan.input.json",
        build_plan_input(
            state,
            universe,
            common_rules,
            platform_rules,
            prompt,
        ),
    )
    atomic_write_json(stage_dir / "state.json", state)
    return {
        "ok": True,
        "stage": "implementation",
        "state": state["state"],
        "page_count": len(universe["page_keys"]),
        "design_element_count": len(universe["design_elements"]),
        "integration_count": len(universe["integration_obligations"]),
        "plan_input": str(stage_dir / "implementation-plan.input.json"),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    command = commands.add_parser("begin")
    command.add_argument("--project-root", required=True)
    command.add_argument("--platform", required=True)
    command.set_defaults(handler=begin)
    command = commands.add_parser("record-plan")
    command.add_argument("--project-root", required=True)
    command.add_argument("--plan", required=True)
    command.set_defaults(handler=record_plan)
    command = commands.add_parser("run-case")
    command.add_argument("--project-root", required=True)
    command.add_argument("--case-id", required=True)
    command.add_argument("--phase", choices=("red", "green"), required=True)
    command.set_defaults(handler=run_case)
    command = commands.add_parser("capture-visual")
    command.add_argument("--project-root", required=True)
    command.add_argument("--design-name", required=True)
    command.add_argument("--driver", required=True)
    command.set_defaults(handler=capture_visual)
    command = commands.add_parser("verify")
    command.add_argument("--project-root", required=True)
    command.add_argument("--evidence", required=True)
    command.set_defaults(handler=verify_implementation)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        result = args.handler(args)
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "message": exc.message}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
