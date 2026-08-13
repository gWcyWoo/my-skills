#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from shared_core import (
    implementation_contract_v1,
    visual_evidence_v1,
    visual_verification_v1,
)


JOB_KEYS = {
    "base_revision",
    "component_decisions",
    "component_analysis",
    "execution_dag",
    "execution_order",
    "flow_id",
    "interaction_edges",
    "job_id",
    "kind",
    "member_digests",
    "members",
    "platform",
    "profile",
    "project_root",
    "role",
    "root_page_id",
    "schema_version",
}
LEGACY_MEMBER_KEYS = {
    "acceptance_criteria",
    "design_ref",
    "design_source",
    "mode",
    "page_id",
    "requirement",
    "review",
    "route",
    "title",
}
LOSSLESS_MEMBER_KEYS = LEGACY_MEMBER_KEYS | {"interaction", "source_contract"}
NODE_KEYS = {"allowed_paths", "depends_on", "node_id", "page_ids", "type"}
EDGE_KEYS = {"from", "target_title", "to"}
COMPONENT_KEYS = {
    "allowed_paths",
    "code_path",
    "component_id",
    "consumers",
    "decision",
    "evidence",
    "name",
}
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
GIT_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
PLATFORM_PROFILES = {
    "android-java": "android-java-standard",
    "android-kotlin": "android-kotlin-standard",
    "flutter": "flutter-standard",
    "ios-objc": "ios-objc-standard",
    "ios-swift": "ios-swift-standard",
    "nextjs": "nextjs-standard",
    "vue": "vue-vite",
}
RUNTIME_CAPTURE_SOURCES = {
    "android-java": "emulator_screenshot",
    "android-kotlin": "emulator_screenshot",
    "flutter": "simulator_screenshot",
    "ios-objc": "simulator_screenshot",
    "ios-swift": "simulator_screenshot",
    "nextjs": "browser_screenshot",
    "vue": "browser_screenshot",
}
ICP_SKILL_REF = "~/.agents/skills/icp/SKILL.md"
ICP_SKILL = Path(ICP_SKILL_REF).expanduser()
WORKER_CONTRACT = Path(__file__).parents[1] / "references" / "worker-node-contract-v1.md"
WORKER_CONTRACT_V2 = (
    Path(__file__).parents[1] / "references" / "worker-node-contract-v2.md"
)
IMPLEMENTATION_CONTRACT = (
    Path(__file__).parents[1] / "references" / "implementation-contract-v1.md"
)
LEGACY_WORKER_CONTRACT_SHA256 = "211a6c71412a55133510cb0de14f733fe560c0638656282f4c5cfd3459ac4553"
WORKER_RESULT_KEYS = {
    "changed_files",
    "error_code",
    "evidence",
    "kind",
    "loaded_contracts",
    "node_id",
    "schema_version",
    "status",
    "verification",
}
WORKER_RESULT_V2_KEYS = WORKER_RESULT_KEYS | {
    "acceptance_evidence",
    "implementation_contract",
}


class FlowJobError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_absolute():
        raise FlowJobError(f"{label} path must be absolute")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FlowJobError(f"{label} cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise FlowJobError(f"{label} is not valid JSON") from exc
    if not isinstance(document, dict):
        raise FlowJobError(f"{label} must be a JSON object")
    return document


def validate_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise FlowJobError(f"{label} is invalid")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise FlowJobError(f"{label} must be project-relative")
    return value


def scopes_overlap(first: str, second: str) -> bool:
    if first == second:
        return True
    if first.endswith("/") and second.startswith(first):
        return True
    if second.endswith("/") and first.startswith(second):
        return True
    return False


def validate_source_contract(value: object) -> dict[str, object]:
    expected_keys = {
        "acceptance_sections",
        "contract_digest",
        "design_ref",
        "interaction",
        "kind",
        "requirement_sections",
        "route",
        "schema_version",
        "title",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise FlowJobError("flow member source contract is invalid")
    if (
        value["kind"] != "iole.sheet-member-contract.v1"
        or value["schema_version"] != 1
    ):
        raise FlowJobError("flow member source contract version is invalid")
    for field in ("title", "route", "design_ref", "interaction"):
        if not isinstance(value[field], str):
            raise FlowJobError(f"flow member source contract {field} is invalid")
    for field, label_key in (
        ("requirement_sections", "label"),
        ("acceptance_sections", "prefix"),
    ):
        sections = value[field]
        if not isinstance(sections, list) or any(
            not isinstance(section, dict)
            or set(section) != {label_key, "value"}
            or not isinstance(section[label_key], str)
            or not section[label_key]
            or not isinstance(section["value"], str)
            for section in sections
        ):
            raise FlowJobError(f"flow member source contract {field} is invalid")
    digest = value["contract_digest"]
    digest_payload = {
        key: field_value for key, field_value in value.items() if key != "contract_digest"
    }
    if (
        not isinstance(digest, str)
        or SHA256_HEX.fullmatch(digest) is None
        or digest != hashlib.sha256(canonical_bytes(digest_payload)).hexdigest()
    ):
        raise FlowJobError("flow member source contract digest mismatch")
    return value


def validate_job(document: dict[str, object]) -> dict[str, object]:
    if set(document) != JOB_KEYS:
        raise FlowJobError("flow job keys do not match the contract")
    job_version = (document["kind"], document["schema_version"])
    if job_version not in {
        ("icp.external-flow-job.v3", 3),
        ("icp.external-flow-job.v4", 4),
        ("icp.external-flow-job.v5", 5),
    }:
        raise FlowJobError("flow job contract version is invalid")
    lossless = job_version in {
        ("icp.external-flow-job.v4", 4),
        ("icp.external-flow-job.v5", 5),
    }
    if document["role"] != "client":
        raise FlowJobError("flow job role must be client")
    for field in ("job_id", "flow_id", "root_page_id", "platform", "profile"):
        if not isinstance(document[field], str) or not document[field].strip():
            raise FlowJobError(f"flow job {field} is invalid")
    if PLATFORM_PROFILES.get(str(document["platform"])) != document["profile"]:
        raise FlowJobError("unsupported platform/profile")
    if not isinstance(document["base_revision"], str) or GIT_REVISION.fullmatch(
        document["base_revision"]
    ) is None:
        raise FlowJobError("base revision is invalid")
    if not isinstance(document["project_root"], str) or not Path(
        document["project_root"]
    ).is_absolute():
        raise FlowJobError("project root must be absolute")

    members = document["members"]
    member_digests = document["member_digests"]
    if not isinstance(members, list) or not members:
        raise FlowJobError("flow members are required")
    if not isinstance(member_digests, dict) or not member_digests:
        raise FlowJobError("flow member digests are required")
    member_ids: list[str] = []
    for member in members:
        expected_member_keys = LOSSLESS_MEMBER_KEYS if lossless else LEGACY_MEMBER_KEYS
        if not isinstance(member, dict) or set(member) != expected_member_keys:
            raise FlowJobError("flow member contract is invalid")
        page_id = member["page_id"]
        if not isinstance(page_id, str) or not page_id or page_id in member_ids:
            raise FlowJobError("flow member identity is invalid")
        member_ids.append(page_id)
        for field in ("title", "route", "design_source", "design_ref"):
            if not isinstance(member[field], str) or not member[field].strip():
                raise FlowJobError(f"flow member {field} is invalid")
        if not isinstance(member["requirement"], str) or (
            not lossless and not member["requirement"].strip()
        ):
            raise FlowJobError("flow member requirement is invalid")
        if lossless:
            source_contract = validate_source_contract(member["source_contract"])
            if (
                not isinstance(member["interaction"], str)
                or member["interaction"] != source_contract["interaction"]
            ):
                raise FlowJobError("flow member interaction is not lossless")
            requirement_sections = source_contract["requirement_sections"]
            acceptance_sections = source_contract["acceptance_sections"]
            assert isinstance(requirement_sections, list)
            assert isinstance(acceptance_sections, list)
            expected_requirement = "\n".join(
                f"{section['label']}: {section['value']}"
                for section in requirement_sections
                if isinstance(section, dict) and str(section["value"]).strip()
            )
            expected_acceptance = [
                f"{section['prefix']}: {section['value']}"
                for section in acceptance_sections
                if isinstance(section, dict) and str(section["value"]).strip()
            ]
            if member["requirement"] != expected_requirement:
                raise FlowJobError("flow member requirement is not lossless")
            if member["acceptance_criteria"] != expected_acceptance:
                raise FlowJobError("flow member acceptance criteria are not lossless")
            if member["title"] != unicodedata.normalize(
                "NFC", str(source_contract["title"]).strip()
            ):
                raise FlowJobError("flow member title is not lossless")
            if member["route"] != str(source_contract["route"]).strip():
                raise FlowJobError("flow member route is not lossless")
            if member["design_ref"] != str(source_contract["design_ref"]).strip():
                raise FlowJobError("flow member design reference is not lossless")
        acceptance = member["acceptance_criteria"]
        if not isinstance(acceptance, list) or any(
            not isinstance(item, str) or not item.strip() for item in acceptance
        ):
            raise FlowJobError("flow member acceptance criteria are invalid")
        review = member["review"]
        if member["mode"] == "implement":
            if review is not None:
                raise FlowJobError("implement member cannot contain review")
        elif member["mode"] == "revise":
            if (
                not isinstance(review, dict)
                or set(review) != {"number", "text"}
                or type(review["number"]) is not int
                or review["number"] <= 0
                or not isinstance(review["text"], str)
                or not review["text"].strip()
            ):
                raise FlowJobError("revise member requires one numbered review")
        else:
            raise FlowJobError("flow member mode is invalid")
    if set(member_digests) != set(member_ids) or any(
        not isinstance(digest, str) or SHA256_HEX.fullmatch(digest) is None
        for digest in member_digests.values()
    ):
        raise FlowJobError("flow member digests are invalid")
    if lossless and any(
        member_digests[str(member["page_id"])]
        != hashlib.sha256(canonical_bytes(member)).hexdigest()
        for member in members
        if isinstance(member, dict)
    ):
        raise FlowJobError("flow member digest mismatch")
    if document["root_page_id"] not in member_ids:
        raise FlowJobError("root page is not a flow member")

    components = document["component_decisions"]
    if not isinstance(components, list) or any(
        not isinstance(component, dict) or set(component) != COMPONENT_KEYS
        for component in components
    ):
        raise FlowJobError("component decisions are invalid")
    component_ids: set[str] = set()
    for component in components:
        assert isinstance(component, dict)
        component_id = component["component_id"]
        if (
            not isinstance(component_id, str)
            or not component_id
            or component_id in component_ids
            or component["decision"]
            not in {"reuse", "extend", "create-shared", "create-local"}
        ):
            raise FlowJobError("component decision identity is invalid")
        component_ids.add(component_id)
        for field in ("name", "code_path", "evidence"):
            if not isinstance(component[field], str) or not component[field].strip():
                raise FlowJobError("component decision fields are invalid")
        allowed_paths = component["allowed_paths"]
        consumers = component["consumers"]
        if (
            not isinstance(allowed_paths, list)
            or not allowed_paths
            or component["code_path"] not in allowed_paths
            or not isinstance(consumers, list)
            or not consumers
            or any(consumer not in member_ids for consumer in consumers)
            or component["decision"] == "create-local"
            and len(consumers) != 1
        ):
            raise FlowJobError("component decision scope is invalid")
        for allowed_path in allowed_paths:
            validate_relative_path(allowed_path, "component allowed path")
    component_analysis = document["component_analysis"]
    if (
        not isinstance(component_analysis, dict)
        or set(component_analysis) != {"inventory_source", "searched_paths", "summary"}
        or not isinstance(component_analysis["inventory_source"], str)
        or not component_analysis["inventory_source"].strip()
        or not isinstance(component_analysis["searched_paths"], list)
        or not component_analysis["searched_paths"]
        or not isinstance(component_analysis["summary"], str)
        or not component_analysis["summary"].strip()
    ):
        raise FlowJobError("component analysis is invalid")
    edges = document["interaction_edges"]
    if not isinstance(edges, list) or any(
        not isinstance(edge, dict)
        or set(edge) != EDGE_KEYS
        or edge["from"] not in member_ids
        or edge["to"] not in member_ids
        or not isinstance(edge["target_title"], str)
        for edge in edges
    ):
        raise FlowJobError("interaction edges are invalid")

    dag = document["execution_dag"]
    order = document["execution_order"]
    if not isinstance(dag, list) or not dag or not isinstance(order, list):
        raise FlowJobError("execution DAG is invalid")
    nodes: dict[str, dict[str, object]] = {}
    for node in dag:
        if not isinstance(node, dict) or set(node) != NODE_KEYS:
            raise FlowJobError("execution node contract is invalid")
        node_id = node["node_id"]
        if not isinstance(node_id, str) or not node_id or node_id in nodes:
            raise FlowJobError("execution node identity is invalid")
        if node["type"] not in {"shared-component", "page", "integration"}:
            raise FlowJobError("execution node type is invalid")
        dependencies = node["depends_on"]
        page_ids = node["page_ids"]
        allowed_paths = node["allowed_paths"]
        if (
            not isinstance(dependencies, list)
            or len(dependencies) != len(set(dependencies))
            or any(not isinstance(value, str) or not value for value in dependencies)
        ):
            raise FlowJobError("execution node dependencies are invalid")
        if (
            not isinstance(page_ids, list)
            or not page_ids
            or any(page_id not in member_ids for page_id in page_ids)
            or node["type"] == "page"
            and len(page_ids) != 1
        ):
            raise FlowJobError("execution node page scope is invalid")
        if not isinstance(allowed_paths, list) or not allowed_paths:
            raise FlowJobError("execution node path scope is invalid")
        for allowed_path in allowed_paths:
            validate_relative_path(allowed_path, "execution node path scope")
        nodes[node_id] = node
    owned_paths = [
        (node_id, str(allowed_path))
        for node_id, node in nodes.items()
        for allowed_path in node["allowed_paths"]
        if isinstance(allowed_path, str)
    ]
    for index, (first_node, first_path) in enumerate(owned_paths):
        for second_node, second_path in owned_paths[index + 1 :]:
            if first_node != second_node and scopes_overlap(first_path, second_path):
                raise FlowJobError("execution node path ownership overlaps")
    for component in components:
        assert isinstance(component, dict)
        node_id = f"component:{component['component_id']}"
        if component["decision"] in {"extend", "create-shared"}:
            node = nodes.get(node_id)
            if (
                node is None
                or node["type"] != "shared-component"
                or node["allowed_paths"] != component["allowed_paths"]
                or node["page_ids"] != component["consumers"]
            ):
                raise FlowJobError("component worker node does not match its decision")
        elif node_id in nodes:
            raise FlowJobError("non-editing component decision has a worker node")
    if (
        len(order) != len(set(order))
        or set(order) != set(nodes)
        or any(not isinstance(node_id, str) for node_id in order)
    ):
        raise FlowJobError("execution order must list every DAG node once")
    positions = {node_id: index for index, node_id in enumerate(order)}
    for node_id, node in nodes.items():
        dependencies = node["depends_on"]
        assert isinstance(dependencies, list)
        if any(dependency not in nodes for dependency in dependencies):
            raise FlowJobError("execution dependency is missing")
        if node_id in dependencies:
            raise FlowJobError("execution node cannot depend on itself")
        if any(positions[dependency] >= positions[node_id] for dependency in dependencies):
            raise FlowJobError("execution order is not topological")
    page_owners: dict[str, str] = {}
    for node_id, node in nodes.items():
        if node["type"] != "page":
            continue
        page_ids = node["page_ids"]
        assert isinstance(page_ids, list)
        for page_id in page_ids:
            if page_id in page_owners:
                raise FlowJobError("flow member has multiple page worker owners")
            page_owners[str(page_id)] = node_id
    if set(page_owners) != set(member_ids):
        raise FlowJobError("every flow member requires one page worker owner")
    return document


def project_root(job: dict[str, object]) -> Path:
    root = Path(str(job["project_root"]))
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise FlowJobError("project root does not exist") from exc
    if root.is_symlink() or not resolved.is_dir() or resolved != root:
        raise FlowJobError("project root is invalid")
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=resolved,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or completed.stdout.strip().lower() != str(
        job["base_revision"]
    ).lower():
        raise FlowJobError("base revision mismatch")
    return resolved


def state_root(job: dict[str, object]) -> Path:
    root = project_root(job)
    job_identity = hashlib.sha256(str(job["job_id"]).encode("utf-8")).hexdigest()
    target = root / ".icp" / "flow-jobs" / job_identity
    current = root
    for part in (".icp", "flow-jobs", job_identity):
        current = current / part
        if current.exists() and current.is_symlink():
            raise FlowJobError("flow job state path contains a symlink")
    return target


def write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError as exc:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise FlowJobError("persisted flow job input drift") from exc


def replace_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".next")
    temporary.write_bytes(canonical_bytes(value))
    os.replace(temporary, path)


def prepare(job_path: Path) -> dict[str, object]:
    job = validate_job(load_json(job_path, "job"))
    root = state_root(job)
    canonical_job = canonical_bytes(job)
    job_digest = hashlib.sha256(canonical_job).hexdigest()
    job_file = root / "job.json"
    existed = job_file.exists()
    write_once(job_file, canonical_job)
    progress_path = root / "progress.json"
    if not progress_path.exists():
        order = job["execution_order"]
        assert isinstance(order, list)
        progress: dict[str, object] = {
            "kind": "icp.flow-progress.v1",
            "schema_version": 1,
            "job_digest": job_digest,
            "status": "active",
            "active_node": None,
            "nodes": {node_id: "pending" for node_id in order},
        }
        if job["kind"] == "icp.external-flow-job.v5":
            progress["implementation_contract"] = {
                "status": "pending",
                "digest": None,
            }
        replace_json(progress_path, progress)
    return {
        "kind": "icp.flow-job-decision.v1",
        "schema_version": 1,
        "status": "resume-required" if existed else "ready",
        "job_id": job["job_id"],
        "job_digest": job_digest,
        "state_root": str(root),
    }


def read_persisted(job_path: Path) -> tuple[dict[str, object], Path, dict[str, object]]:
    job = validate_job(load_json(job_path, "job"))
    root = state_root(job)
    canonical_job = canonical_bytes(job)
    persisted_path = root / "job.json"
    if not persisted_path.is_file() or persisted_path.read_bytes() != canonical_job:
        raise FlowJobError("persisted flow job input drift")
    progress = load_json(root / "progress.json", "progress")
    return job, root, progress


def build_worker_prompt(
    job: dict[str, object], node: dict[str, object], node_job_path: Path, result_path: Path
) -> str:
    worker_contract = (
        WORKER_CONTRACT_V2
        if job.get("kind") == "icp.external-flow-job.v5"
        else WORKER_CONTRACT
    )
    source_contract_instructions = (
        [
            "Treat each member.source_contract as the exact authoritative Sheet contract.",
            "Never summarize, rewrite, or replace its values; preserve exact copy, lists, whitespace, and empty mapped sections in implementation evidence.",
        ]
        if job.get("kind") in {
            "icp.external-flow-job.v4",
            "icp.external-flow-job.v5",
        }
        else []
    )
    implementation_contract_instructions = (
        [
            "Read the frozen implementation contract bound by node-job.json before writing a test or production file.",
            "Implement only this node's owned clause IDs and acceptance cases; never weaken, rewrite, omit, or add product behavior outside that contract.",
        ]
        if job.get("kind") == "icp.external-flow-job.v5"
        else []
    )
    return "\n".join(
        [
            "Use $icp to implement this one persisted flow node.",
            f"Read the ICP Skill completely: {ICP_SKILL_REF}",
            f"Read the worker contract completely: {worker_contract}",
            f"Node input: {node_job_path}",
            f"Write the worker result JSON only to: {result_path}",
            f"Project worktree: {job['project_root']}",
            "Edit only the allowed_paths declared in the node input.",
            "Do not read or write Sheets/Excel, leases, statuses, Git, commits, branches, pushes, or PRs.",
            *source_contract_instructions,
            *implementation_contract_instructions,
            "Invoke and follow $icp for this node; reading the Skill alone is not compliance.",
            "For a page node, execute ICP's full design compiler loop and seal visual-verification.json with shared_core/visual_verification_v1.py; do not substitute a worker-specific workflow.",
            "An intermediate visual mismatch is not terminal: calibrate capture first, classify one root cause, apply one targeted repair, recapture, and continue while a contract-significant score improves.",
            "Pass only after every declared state has anchors and regional pixels green in two independent clean final captures. Fail only for a real external/contract blocker or two consecutive no-progress targeted repairs for the same mismatch.",
            "Run focused tests and report exact changed files plus the canonical ICP evidence required by the worker contract.",
            "Do not start another node; return control after this result is ready.",
            "",
        ]
    )


def next_node(job_path: Path) -> dict[str, object]:
    job, root, progress = read_persisted(job_path)
    if job["kind"] == "icp.external-flow-job.v5":
        contract_state = progress.get("implementation_contract")
        if not isinstance(contract_state, dict) or contract_state.get("status") not in {
            "pending",
            "passed",
        }:
            raise FlowJobError("implementation contract progress is invalid")
        if contract_state["status"] == "pending":
            compiler_input_path = root / "contract-compiler-input.json"
            implementation_contract_path = root / "implementation-contract.json"
            compiler_input = {
                "kind": "icp.contract-compiler-input.v1",
                "schema_version": 1,
                "job_id": job["job_id"],
                "job_digest": progress["job_digest"],
                "flow_id": job["flow_id"],
                "project_root": job["project_root"],
                "platform": job["platform"],
                "profile": job["profile"],
                "members": job["members"],
                "interaction_edges": job["interaction_edges"],
                "component_decisions": job["component_decisions"],
                "component_analysis": job["component_analysis"],
                "execution_dag": job["execution_dag"],
                "execution_order": job["execution_order"],
            }
            source_clauses = implementation_contract_v1.build_source_clauses(
                job["members"]
            )
            compiler_input["source_clauses"] = source_clauses
            compiler_input["source_clauses_digest"] = (
                implementation_contract_v1.digest(source_clauses)
            )
            write_once(compiler_input_path, canonical_bytes(compiler_input))
            compiler_prompt_path = root / "contract-compiler-prompt.md"
            write_once(
                compiler_prompt_path,
                "\n".join(
                    [
                        "Use $icp in the main orchestration session to compile this flow before any test or production edit.",
                        f"Read the compiler contract completely: {IMPLEMENTATION_CONTRACT}",
                        f"Compiler input: {compiler_input_path}",
                        f"Write the candidate implementation contract to: {implementation_contract_path}",
                        "Fetch every exact design reference once into this flow state; preserve raw artifacts and live SHA-256 values.",
                        "Inspect the current public project contracts read-only; when an existing behavior or explicit user decision applies but is absent from Sheet/design, bind it as a provenance-backed optional context_source_clause.",
                        "Compile all public interfaces, ownership, observable clauses, acceptance cases, strict TDD slices, and every reachable design state.",
                        "Do not add product capabilities absent from the exact sources and do not dispatch an implementation worker before record-contract passes.",
                        "",
                    ]
                ).encode("utf-8"),
            )
            return {
                "kind": "icp.flow-node-decision.v2",
                "schema_version": 2,
                "status": "contract-compilation-required",
                "compiler_input": str(compiler_input_path),
                "compiler_prompt": str(compiler_prompt_path),
                "implementation_contract": str(implementation_contract_path),
            }
    active_node = progress.get("active_node")
    if isinstance(active_node, str) and active_node:
        node_root = root / "nodes" / hashlib.sha256(active_node.encode("utf-8")).hexdigest()
        return {
            "kind": "icp.flow-node-decision.v1",
            "schema_version": 1,
            "status": "resume-required",
            "node_id": active_node,
            "worker_prompt": str(node_root / "worker-prompt.md"),
            "worker_result": str(node_root / "worker-result.json"),
        }
    nodes_state = progress.get("nodes")
    if not isinstance(nodes_state, dict):
        raise FlowJobError("flow progress is invalid")
    if any(value == "failed" for value in nodes_state.values()):
        return {
            "kind": "icp.flow-node-decision.v1",
            "schema_version": 1,
            "status": "blocked",
            "reason": "node-failed",
        }
    if all(value == "passed" for value in nodes_state.values()):
        return {
            "kind": "icp.flow-node-decision.v1",
            "schema_version": 1,
            "status": "ready-for-finalize",
        }
    dag = job["execution_dag"]
    order = job["execution_order"]
    assert isinstance(dag, list) and isinstance(order, list)
    nodes = {str(node["node_id"]): node for node in dag if isinstance(node, dict)}
    selected_id: str | None = None
    for node_id in order:
        node = nodes[str(node_id)]
        dependencies = node["depends_on"]
        assert isinstance(dependencies, list)
        if nodes_state.get(node_id) == "pending" and all(
            nodes_state.get(dependency) == "passed" for dependency in dependencies
        ):
            selected_id = str(node_id)
            break
    if selected_id is None:
        raise FlowJobError("flow has no runnable node")
    selected = nodes[selected_id]
    node_root = root / "nodes" / hashlib.sha256(selected_id.encode("utf-8")).hexdigest()
    node_job_path = node_root / "node-job.json"
    result_path = node_root / "worker-result.json"
    node_input: dict[str, object] = {
        "kind": (
            "icp.worker-node-job.v2"
            if job["kind"] == "icp.external-flow-job.v5"
            else "icp.worker-node-job.v1"
        ),
        "schema_version": 2 if job["kind"] == "icp.external-flow-job.v5" else 1,
        "job_id": job["job_id"],
        "flow_id": job["flow_id"],
        "project_root": job["project_root"],
        "platform": job["platform"],
        "profile": job["profile"],
        "node": selected,
        "members": [
            member
            for member in job["members"]
            if isinstance(member, dict) and member.get("page_id") in selected["page_ids"]
        ],
        "component_decisions": job["component_decisions"],
        "component_analysis": job["component_analysis"],
    }
    if job["kind"] == "icp.external-flow-job.v5":
        contract_path = root / "implementation-contract.json"
        contract_bytes = contract_path.read_bytes()
        contract_digest = hashlib.sha256(contract_bytes).hexdigest()
        contract_state = progress["implementation_contract"]
        assert isinstance(contract_state, dict)
        if contract_state.get("digest") != contract_digest:
            raise FlowJobError("persisted implementation contract drift")
        implementation_contract = json.loads(contract_bytes)
        validate_context_provenance(root, implementation_contract)
        observable_clauses = implementation_contract.get("observable_clauses")
        acceptance_cases = implementation_contract.get("acceptance_cases")
        tdd_slices = implementation_contract.get("tdd_slices")
        design_contracts = implementation_contract.get("design_contracts")
        if not all(
            isinstance(value, list)
            for value in (
                observable_clauses,
                acceptance_cases,
                tdd_slices,
                design_contracts,
            )
        ):
            raise FlowJobError("persisted implementation contract is invalid")
        owned_clause_ids = [
            str(clause["clause_id"])
            for clause in observable_clauses
            if isinstance(clause, dict)
            and clause.get("owner_node_id") == selected_id
        ]
        owned_case_ids = [
            str(case["case_id"])
            for case in acceptance_cases
            if isinstance(case, dict)
            and any(
                clause_id in owned_clause_ids
                for clause_id in case.get("clause_ids", [])
            )
        ]
        owned_slice_ids = [
            str(item["slice_id"])
            for item in tdd_slices
            if isinstance(item, dict) and item.get("owner_node_id") == selected_id
        ]
        owned_page_ids = set(str(value) for value in selected["page_ids"])
        design_state_ids = [
            str(state["state_id"])
            for design in design_contracts
            if isinstance(design, dict)
            and str(design.get("page_id")) in owned_page_ids
            for state in design.get("states", [])
            if isinstance(state, dict)
        ]
        node_input["implementation_contract"] = {
            "path": str(contract_path),
            "sha256": contract_digest,
            "source_clauses_digest": implementation_contract.get(
                "source_clauses_digest"
            ),
            "owned_clause_ids": owned_clause_ids,
            "owned_acceptance_case_ids": owned_case_ids,
            "owned_tdd_slice_ids": owned_slice_ids,
            "owned_design_state_ids": design_state_ids,
        }
    write_once(node_job_path, canonical_bytes(node_input))
    prompt_path = node_root / "worker-prompt.md"
    write_once(
        prompt_path,
        build_worker_prompt(job, selected, node_job_path, result_path).encode("utf-8"),
    )
    nodes_state[selected_id] = "running"
    progress["active_node"] = selected_id
    replace_json(root / "progress.json", progress)
    return {
        "kind": "icp.flow-node-decision.v1",
        "schema_version": 1,
        "status": "ready",
        "node_id": selected_id,
        "worker_prompt": str(prompt_path),
        "worker_result": str(result_path),
    }


def record_contract(job_path: Path, contract_path: Path) -> dict[str, object]:
    job, root, progress = read_persisted(job_path)
    if job["kind"] != "icp.external-flow-job.v5":
        raise FlowJobError("implementation contracts require a v5 flow job")
    contract_state = progress.get("implementation_contract")
    if not isinstance(contract_state, dict) or contract_state.get("status") not in {
        "pending",
        "passed",
    }:
        raise FlowJobError("implementation contract progress is invalid")
    compiler_input_path = root / "contract-compiler-input.json"
    compiler_input = load_json(compiler_input_path, "contract compiler input")
    contract = load_json(contract_path, "implementation contract")
    try:
        contract = implementation_contract_v1.validate_contract_envelope(
            contract,
            compiler_input=compiler_input,
        )
    except ValueError as exc:
        raise FlowJobError(str(exc)) from exc
    try:
        implementation_contract_v1.validate_interfaces_and_ownership(
            contract.get("public_interfaces"),
            contract.get("ownership"),
            execution_dag=job["execution_dag"],
        )
    except ValueError as exc:
        raise FlowJobError(str(exc)) from exc
    source_clauses = compiler_input.get("source_clauses")
    observable_clauses = contract.get("observable_clauses")
    if not isinstance(source_clauses, list):
        raise FlowJobError("implementation contract source coverage mismatch")
    page_node_page_ids = {
        str(page_id)
        for node in job["execution_dag"]
        if isinstance(node, dict) and node.get("type") == "page"
        for page_id in node.get("page_ids", [])
    }
    context_source_clauses = validate_context_provenance(root, contract)
    sheet_source_ids = {
        str(clause.get("clause_id"))
        for clause in source_clauses
        if isinstance(clause, dict)
    }
    context_source_ids = {
        str(clause.get("clause_id"))
        for clause in context_source_clauses
        if isinstance(clause, dict)
    }
    if sheet_source_ids & context_source_ids:
        raise FlowJobError("implementation contract context sources are invalid")
    all_source_clauses = [*source_clauses, *context_source_clauses]
    required_source_ids = {
        str(clause.get("clause_id"))
        for clause in all_source_clauses
        if isinstance(clause, dict)
    }
    covered_source_ids: set[str] = set()
    for clause in observable_clauses:
        if not isinstance(clause, dict) or not isinstance(
            clause.get("source_clause_ids"), list
        ):
            raise FlowJobError("implementation contract source coverage mismatch")
        covered_source_ids.update(str(value) for value in clause["source_clause_ids"])
    if covered_source_ids != required_source_ids:
        raise FlowJobError("implementation contract source coverage mismatch")
    try:
        design_contracts = implementation_contract_v1.validate_design_contracts(
            contract.get("design_contracts"),
            implemented_page_ids=page_node_page_ids,
        )
    except ValueError as exc:
        raise FlowJobError(str(exc)) from exc
    try:
        observable_clauses = implementation_contract_v1.validate_observable_clauses(
            observable_clauses,
            source_clauses=all_source_clauses,
            execution_dag=job["execution_dag"],
            design_contracts=design_contracts,
        )
    except ValueError as exc:
        raise FlowJobError(str(exc)) from exc
    try:
        acceptance_cases = implementation_contract_v1.validate_acceptance_cases(
            contract.get("acceptance_cases"),
            observable_clauses=observable_clauses,
        )
    except ValueError as exc:
        raise FlowJobError(str(exc)) from exc
    try:
        implementation_contract_v1.validate_tdd_slices(
            contract.get("tdd_slices"),
            observable_clauses=observable_clauses,
            acceptance_cases=acceptance_cases,
        )
    except ValueError as exc:
        raise FlowJobError(str(exc)) from exc
    for design_contract in design_contracts:
        assert isinstance(design_contract, dict)
        for artifact in design_contract["reference_artifacts"]:
            if (
                not isinstance(artifact, dict)
                or set(artifact) != {"artifact_id", "path", "sha256"}
                or not isinstance(artifact["sha256"], str)
                or SHA256_HEX.fullmatch(artifact["sha256"]) is None
            ):
                raise FlowJobError("implementation contract design artifact is invalid")
            artifact_path = require_absolute_regular_below(
                root, artifact["path"], "implementation contract design artifact"
            )
            if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise FlowJobError(
                    "implementation contract design artifact digest mismatch"
                )
    canonical_contract = canonical_bytes(contract)
    contract_digest = hashlib.sha256(canonical_contract).hexdigest()
    canonical_path = root / "implementation-contract.json"
    try:
        candidate_is_canonical_target = (
            contract_path.resolve(strict=True) == canonical_path.resolve(strict=False)
        )
    except OSError as exc:
        raise FlowJobError("implementation contract cannot be read") from exc
    if candidate_is_canonical_target:
        if contract_path.is_symlink() or not contract_path.is_file():
            raise FlowJobError("implementation contract path is invalid")
        if contract_state["status"] == "pending":
            replace_json(canonical_path, contract)
        elif canonical_path.read_bytes() != canonical_contract:
            raise FlowJobError("persisted implementation contract drift")
    else:
        write_once(canonical_path, canonical_contract)
    if (
        contract_state["status"] == "passed"
        and contract_state.get("digest") != contract_digest
    ):
        raise FlowJobError("persisted implementation contract drift")
    progress["implementation_contract"] = {
        "status": "passed",
        "digest": contract_digest,
    }
    replace_json(root / "progress.json", progress)
    return {
        "kind": "icp.implementation-contract-decision.v1",
        "schema_version": 1,
        "status": "passed",
        "implementation_contract": str(canonical_path),
        "implementation_contract_digest": contract_digest,
    }


def path_is_allowed(relative: str, allowed_paths: list[object]) -> bool:
    return any(
        isinstance(allowed, str)
        and (
            relative == allowed
            or allowed.endswith("/")
            and relative.startswith(allowed)
        )
        for allowed in allowed_paths
    )


def require_regular_below(root: Path, relative: object, label: str) -> Path:
    relative_value = validate_relative_path(relative, label)
    relative_path = Path(relative_value)
    target = root / relative_path
    try:
        resolved_root = root.resolve(strict=True)
        resolved_target = target.resolve(strict=True)
        resolved_target.relative_to(resolved_root)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise FlowJobError(f"{label} is missing or outside its root") from exc
    if (
        target.is_symlink()
        or any(
            root.joinpath(*relative_path.parts[:index]).is_symlink()
            for index in range(1, len(relative_path.parts))
        )
        or not resolved_target.is_file()
        or resolved_target.stat().st_size == 0
    ):
        raise FlowJobError(f"{label} is missing or invalid")
    return resolved_target


def require_absolute_regular_below(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise FlowJobError(f"{label} path is invalid")
    try:
        relative = str(Path(value).resolve(strict=True).relative_to(root.resolve(strict=True)))
    except (OSError, ValueError) as exc:
        raise FlowJobError(f"{label} is outside the node state") from exc
    return require_regular_below(root, relative, label)


def validate_canonical_page_evidence(
    job: dict[str, object],
    node_root: Path,
    evidence: list[object],
) -> None:
    if "visual-verification.json" not in evidence:
        raise FlowJobError("page worker result requires high-assurance visual verification")
    verification_path = require_regular_below(
        node_root,
        "visual-verification.json",
        "page visual verification",
    )
    verification = load_json(verification_path, "page visual verification")
    try:
        visual_verification_v1.verify_verification(verification)
    except (OSError, ValueError) as exc:
        raise FlowJobError("page visual verification did not pass") from exc
    manifest_paths: list[Path] = []
    actual_paths: list[Path] = []
    for state in verification["states"]:
        for run in state["final_runs"]:
            manifest_path = require_absolute_regular_below(
                node_root, run["evidence_path"], "page visual evidence manifest"
            )
            manifest_paths.append(manifest_path)
            manifest = load_json(manifest_path, "page visual evidence")
            try:
                visual_evidence_v1.verify_evidence(manifest)
            except (OSError, ValueError) as exc:
                raise FlowJobError("page visual verification did not pass") from exc
            if (
                manifest["status"] != "pass"
                or manifest["actual"]["actual_source"]
                != RUNTIME_CAPTURE_SOURCES[str(job["platform"])]
            ):
                raise FlowJobError("page visual verification did not pass")
            bound_targets = [
                require_absolute_regular_below(
                    node_root, manifest["reference"]["path"], "page design reference"
                ),
                require_absolute_regular_below(
                    node_root, manifest["actual"]["path"], "page runtime capture"
                ),
                require_absolute_regular_below(
                    node_root,
                    manifest["actual"]["provenance_path"],
                    "page runtime provenance",
                ),
                require_absolute_regular_below(
                    node_root, manifest["diff"]["path"], "page visual diff"
                ),
            ]
            if len(bound_targets) != len(set(bound_targets)):
                raise FlowJobError("page visual evidence artifacts must be distinct")
            actual_paths.append(bound_targets[1])
    if len(manifest_paths) != len(set(manifest_paths)) or len(actual_paths) != len(
        set(actual_paths)
    ):
        raise FlowJobError("page final visual runs must be independent")


def expected_implementation_contract_binding(
    flow_root: Path,
    node: dict[str, object],
) -> dict[str, object]:
    contract_path = flow_root / "implementation-contract.json"
    contract_digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    progress = load_json(flow_root / "progress.json", "flow progress")
    contract_state = progress.get("implementation_contract")
    if (
        not isinstance(contract_state, dict)
        or contract_state.get("status") != "passed"
        or contract_state.get("digest") != contract_digest
    ):
        raise FlowJobError("persisted implementation contract drift")
    contract = load_json(contract_path, "persisted implementation contract")
    validate_context_provenance(flow_root, contract)
    node_id = str(node["node_id"])
    observable_clauses = contract.get("observable_clauses")
    acceptance_cases = contract.get("acceptance_cases")
    tdd_slices = contract.get("tdd_slices")
    design_contracts = contract.get("design_contracts")
    if not all(
        isinstance(value, list)
        for value in (
            observable_clauses,
            acceptance_cases,
            tdd_slices,
            design_contracts,
        )
    ):
        raise FlowJobError("persisted implementation contract is invalid")
    owned_clause_ids = [
        str(clause["clause_id"])
        for clause in observable_clauses
        if isinstance(clause, dict) and clause.get("owner_node_id") == node_id
    ]
    owned_acceptance_case_ids = [
        str(case["case_id"])
        for case in acceptance_cases
        if isinstance(case, dict)
        and any(
            clause_id in owned_clause_ids for clause_id in case.get("clause_ids", [])
        )
    ]
    owned_tdd_slice_ids = [
        str(item["slice_id"])
        for item in tdd_slices
        if isinstance(item, dict) and item.get("owner_node_id") == node_id
    ]
    owned_page_ids = set(str(value) for value in node["page_ids"])
    owned_design_state_ids = [
        str(state["state_id"])
        for design in design_contracts
        if isinstance(design, dict)
        and str(design.get("page_id")) in owned_page_ids
        for state in design.get("states", [])
        if isinstance(state, dict)
    ]
    return {
        "path": str(contract_path),
        "sha256": contract_digest,
        "source_clauses_digest": contract.get("source_clauses_digest"),
        "owned_clause_ids": owned_clause_ids,
        "owned_acceptance_case_ids": owned_acceptance_case_ids,
        "owned_tdd_slice_ids": owned_tdd_slice_ids,
        "owned_design_state_ids": owned_design_state_ids,
    }


def validate_context_provenance(
    flow_root: Path,
    contract: dict[str, object],
) -> list[dict[str, object]]:
    page_ids = {
        str(design["page_id"])
        for design in contract.get("design_contracts", [])
        if isinstance(design, dict) and isinstance(design.get("page_id"), str)
    }
    try:
        clauses = implementation_contract_v1.validate_context_source_clauses(
            contract.get("context_source_clauses", []),
            implemented_page_ids=page_ids,
        )
    except ValueError as exc:
        raise FlowJobError(str(exc)) from exc
    for clause in clauses:
        provenance_path = require_absolute_regular_below(
            flow_root,
            clause["provenance_path"],
            "implementation contract context provenance",
        )
        if hashlib.sha256(provenance_path.read_bytes()).hexdigest() != clause[
            "provenance_sha256"
        ]:
            raise FlowJobError("implementation contract context provenance digest mismatch")
    return clauses


def _passed_junit_test_ids(path: Path) -> set[str]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise FlowJobError("worker test evidence is not valid JUnit XML") from exc
    testcases = [root] if root.tag == "testcase" else list(root.iter("testcase"))
    passed: set[str] = set()
    for testcase in testcases:
        name = testcase.get("name")
        if (
            isinstance(name, str)
            and name
            and not any(
                testcase.find(tag) is not None
                for tag in ("failure", "error", "skipped")
            )
        ):
            passed.add(name)
    return passed


def validate_acceptance_evidence(
    job: dict[str, object],
    node: dict[str, object],
    node_root: Path,
    node_job: dict[str, object],
    result: dict[str, object],
) -> None:
    result_binding = result["implementation_contract"]
    assert isinstance(result_binding, dict)
    flow_root = node_root.parents[1]
    contract_path = require_absolute_regular_below(
        flow_root,
        result_binding["path"],
        "worker implementation contract",
    )
    if hashlib.sha256(contract_path.read_bytes()).hexdigest() != result_binding["sha256"]:
        raise FlowJobError("worker implementation contract digest mismatch")
    contract = load_json(contract_path, "worker implementation contract")
    evidence_path = require_regular_below(
        node_root,
        result["acceptance_evidence"],
        "worker acceptance evidence",
    )
    evidence = load_json(evidence_path, "worker acceptance evidence")
    if set(evidence) != {
        "kind",
        "schema_version",
        "node_id",
        "implementation_contract_sha256",
        "bindings",
    }:
        raise FlowJobError("worker acceptance evidence contract is invalid")
    if (
        evidence["kind"] != "icp.acceptance-evidence.v1"
        or evidence["schema_version"] != 1
        or evidence["node_id"] != node["node_id"]
        or evidence["implementation_contract_sha256"] != result_binding["sha256"]
    ):
        raise FlowJobError("worker acceptance evidence identity is invalid")
    clauses = {
        str(clause["clause_id"]): clause
        for clause in contract.get("observable_clauses", [])
        if isinstance(clause, dict)
    }
    acceptance_cases = [
        case
        for case in contract.get("acceptance_cases", [])
        if isinstance(case, dict)
    ]
    design_by_page = {
        str(design["page_id"]): design
        for design in contract.get("design_contracts", [])
        if isinstance(design, dict)
    }
    owned_clause_ids = result_binding["owned_clause_ids"]
    if not isinstance(owned_clause_ids, list) or any(
        clause_id not in clauses for clause_id in owned_clause_ids
    ):
        raise FlowJobError("worker implementation contract clause binding is invalid")
    expected_pairs = {
        (str(clause_id), str(kind))
        for clause_id in owned_clause_ids
        for kind in clauses[str(clause_id)]["required_evidence"]
    }
    bindings = evidence["bindings"]
    if not isinstance(bindings, list):
        raise FlowJobError("worker acceptance evidence contract is invalid")
    actual_pairs: list[tuple[str, str]] = []
    binding_keys = {
        "clause_id",
        "evidence_kind",
        "artifact_path",
        "artifact_sha256",
        "case_bindings",
        "state_bindings",
    }
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != binding_keys:
            raise FlowJobError("worker acceptance evidence binding is invalid")
        clause_id = str(binding["clause_id"])
        evidence_kind = str(binding["evidence_kind"])
        pair = (clause_id, evidence_kind)
        if pair not in expected_pairs:
            raise FlowJobError("worker acceptance evidence coverage mismatch")
        actual_pairs.append(pair)
        generated_evidence = evidence_kind in {
            "unit",
            "integration",
            "e2e",
            "visual",
            "runtime",
        }
        artifact_path = require_absolute_regular_below(
            node_root if generated_evidence else flow_root,
            binding["artifact_path"],
            "worker acceptance artifact",
        )
        if (
            not isinstance(binding["artifact_sha256"], str)
            or hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            != binding["artifact_sha256"]
        ):
            raise FlowJobError("worker acceptance artifact digest mismatch")
        case_bindings = binding["case_bindings"]
        state_bindings = binding["state_bindings"]
        if not isinstance(case_bindings, list) or not isinstance(state_bindings, list):
            raise FlowJobError("worker acceptance evidence binding is invalid")
        clause = clauses[clause_id]
        if evidence_kind in {"unit", "integration", "e2e"}:
            expected_case_ids = {
                str(case["case_id"])
                for case in acceptance_cases
                if case.get("level") == evidence_kind
                and clause_id in case.get("clause_ids", [])
            }
            if any(
                not isinstance(item, dict)
                or set(item) != {"acceptance_case_id", "test_id"}
                or not isinstance(item["test_id"], str)
                or not item["test_id"]
                for item in case_bindings
            ):
                raise FlowJobError("worker test evidence binding is invalid")
            actual_case_ids = [str(item["acceptance_case_id"]) for item in case_bindings]
            if (
                set(actual_case_ids) != expected_case_ids
                or len(actual_case_ids) != len(expected_case_ids)
                or state_bindings
            ):
                raise FlowJobError("worker test evidence coverage mismatch")
            passed_test_ids = _passed_junit_test_ids(artifact_path)
            if any(item["test_id"] not in passed_test_ids for item in case_bindings):
                raise FlowJobError("worker test evidence did not pass")
        elif evidence_kind == "contract":
            if (
                artifact_path != contract_path
                or case_bindings
                or state_bindings
            ):
                raise FlowJobError("worker contract evidence binding is invalid")
        elif evidence_kind == "design":
            design = design_by_page.get(str(clause["page_id"]))
            reference_paths = {
                Path(str(artifact["path"])).resolve(): str(artifact["sha256"])
                for artifact in design.get("reference_artifacts", [])
                if isinstance(artifact, dict)
            } if isinstance(design, dict) else {}
            if (
                reference_paths.get(artifact_path) != binding["artifact_sha256"]
                or case_bindings
                or state_bindings
            ):
                raise FlowJobError("worker design evidence binding is invalid")
        elif evidence_kind == "visual":
            if artifact_path != (node_root / "visual-verification.json").resolve():
                raise FlowJobError("worker visual evidence binding is invalid")
            verification = load_json(artifact_path, "worker visual verification")
            runtime_states = {
                str(state["name"]): state
                for state in verification.get("states", [])
                if isinstance(state, dict)
            }
            expected_state_ids = set(str(value) for value in clause["design_state_ids"])
            if any(
                not isinstance(item, dict)
                or set(item) != {"design_state_id", "visual_state_name"}
                for item in state_bindings
            ):
                raise FlowJobError("worker visual state binding is invalid")
            actual_state_ids = [str(item["design_state_id"]) for item in state_bindings]
            if (
                set(actual_state_ids) != expected_state_ids
                or len(actual_state_ids) != len(expected_state_ids)
                or any(
                    item["visual_state_name"] not in runtime_states
                    for item in state_bindings
                )
                or case_bindings
            ):
                raise FlowJobError("worker visual state coverage mismatch")
            design = design_by_page.get(str(clause["page_id"]))
            design_states = {
                str(state["state_id"]): state
                for state in design.get("states", [])
                if isinstance(state, dict)
            } if isinstance(design, dict) else {}
            references = {
                str(artifact["artifact_id"]): artifact
                for artifact in design.get("reference_artifacts", [])
                if isinstance(artifact, dict)
            } if isinstance(design, dict) else {}
            for state_binding in state_bindings:
                design_state = design_states.get(str(state_binding["design_state_id"]))
                runtime_state = runtime_states.get(str(state_binding["visual_state_name"]))
                if not isinstance(design_state, dict) or not isinstance(runtime_state, dict):
                    raise FlowJobError("worker visual state binding is invalid")
                viewport = design_state["viewport"]
                calibration = verification.get("calibration")
                expected_calibration = {
                    "reference_width": viewport["width"],
                    "reference_height": viewport["height"],
                    "runtime_width": viewport["width"],
                    "runtime_height": viewport["height"],
                    "density": viewport["density"],
                    "font_scale": viewport["font_scale"],
                    "locale": viewport["locale"],
                    "theme": viewport["theme"],
                    "system_bars": viewport["system_bars"],
                    "animations_disabled": viewport["animations_disabled"],
                }
                if calibration != expected_calibration:
                    raise FlowJobError(
                        "worker visual calibration does not match frozen design"
                    )
                runtime_anchors = {
                    str(anchor["name"]): anchor
                    for anchor in runtime_state.get("anchors", [])
                    if isinstance(anchor, dict)
                }
                for anchor in design_state["anchors"]:
                    runtime_anchor = runtime_anchors.get(str(anchor["name"]))
                    if (
                        not isinstance(runtime_anchor, dict)
                        or runtime_anchor.get("expected") != anchor["expected"]
                        or not isinstance(runtime_anchor.get("tolerance"), (int, float))
                        or runtime_anchor["tolerance"] > anchor["tolerance"]
                    ):
                        raise FlowJobError(
                            "worker visual geometry does not match frozen design"
                        )
                runtime_regions = {
                    str(region["name"]): region
                    for region in runtime_state.get("regions", [])
                    if isinstance(region, dict)
                }
                for region in design_state["regions"]:
                    runtime_region = runtime_regions.get(str(region["name"]))
                    if (
                        not isinstance(runtime_region, dict)
                        or not isinstance(
                            runtime_region.get("max_mismatch_ratio"), (int, float)
                        )
                        or runtime_region["max_mismatch_ratio"]
                        > region["max_mismatch_ratio"]
                    ):
                        raise FlowJobError(
                            "worker visual regions do not match frozen design"
                        )
                reference = references.get(str(design_state["reference_artifact_id"]))
                if not isinstance(reference, dict):
                    raise FlowJobError("worker visual state binding is invalid")
                for run in runtime_state.get("final_runs", []):
                    if not isinstance(run, dict):
                        raise FlowJobError("worker visual state binding is invalid")
                    manifest_path = require_absolute_regular_below(
                        node_root,
                        run.get("evidence_path"),
                        "worker visual evidence manifest",
                    )
                    manifest = load_json(manifest_path, "worker visual evidence manifest")
                    if manifest.get("reference", {}).get("sha256") != reference["sha256"]:
                        raise FlowJobError(
                            "worker visual reference does not match frozen design"
                        )
        elif evidence_kind == "runtime":
            provenance = load_json(artifact_path, "worker runtime evidence")
            if (
                provenance.get("kind") != "icp.runtime-provenance.v1"
                or provenance.get("actual_source")
                != RUNTIME_CAPTURE_SOURCES[str(job["platform"])]
                or case_bindings
                or state_bindings
            ):
                raise FlowJobError("worker runtime evidence is invalid")
            actual_path = require_absolute_regular_below(
                node_root,
                provenance.get("actual_path"),
                "worker runtime capture",
            )
            if (
                not isinstance(provenance.get("actual_sha256"), str)
                or hashlib.sha256(actual_path.read_bytes()).hexdigest()
                != provenance["actual_sha256"]
            ):
                raise FlowJobError("worker runtime evidence is invalid")
        else:
            raise FlowJobError("worker acceptance evidence kind is invalid")
    if set(actual_pairs) != expected_pairs or len(actual_pairs) != len(expected_pairs):
        raise FlowJobError("worker acceptance evidence coverage mismatch")


def validate_worker_result_document(
    job: dict[str, object],
    node: dict[str, object],
    node_root: Path,
    result: dict[str, object],
) -> tuple[str, list[str]]:
    node_id = str(node["node_id"])
    v5 = job["kind"] == "icp.external-flow-job.v5"
    expected_result_keys = WORKER_RESULT_V2_KEYS if v5 else WORKER_RESULT_KEYS
    expected_result_version = (
        ("icp.worker-node-result.v2", 2)
        if v5
        else ("icp.worker-node-result.v1", 1)
    )
    if set(result) != expected_result_keys:
        if v5:
            raise FlowJobError("v5 worker result requires frozen contract evidence")
        raise FlowJobError("worker result contract is invalid")
    if (
        (result["kind"], result["schema_version"]) != expected_result_version
        or result["node_id"] != node_id
        or result["status"] not in {"passed", "failed"}
    ):
        raise FlowJobError("worker result identity is invalid")
    if v5:
        node_job = load_json(node_root / "node-job.json", "worker node job")
        expected_binding = expected_implementation_contract_binding(
            node_root.parents[1], node
        )
        if node_job.get("implementation_contract") != expected_binding:
            raise FlowJobError("v5 worker node job implementation contract drift")
        if result["implementation_contract"] != expected_binding:
            raise FlowJobError("v5 worker result implementation contract drift")
        if result["status"] == "passed" and (
            not isinstance(result["acceptance_evidence"], str)
            or result["acceptance_evidence"] not in result["evidence"]
        ):
            raise FlowJobError("v5 worker result acceptance evidence is missing")
        if result["status"] == "failed" and result["acceptance_evidence"] is not None:
            raise FlowJobError("failed v5 worker result cannot claim acceptance evidence")
    loaded_contracts = result["loaded_contracts"]
    if not isinstance(loaded_contracts, dict) or set(loaded_contracts) != {
        "icp_skill_sha256",
        "worker_contract_sha256",
    }:
        raise FlowJobError("worker contract evidence is invalid")
    expected_worker_contract = WORKER_CONTRACT_V2 if v5 else WORKER_CONTRACT
    expected_contracts = {
        "icp_skill_sha256": hashlib.sha256(ICP_SKILL.read_bytes()).hexdigest(),
        "worker_contract_sha256": hashlib.sha256(
            expected_worker_contract.read_bytes()
        ).hexdigest(),
    }
    legacy_non_page = (
        node["type"] != "page"
        and result["status"] == "passed"
        and isinstance(loaded_contracts.get("icp_skill_sha256"), str)
        and SHA256_HEX.fullmatch(str(loaded_contracts["icp_skill_sha256"])) is not None
        and loaded_contracts.get("worker_contract_sha256")
        == LEGACY_WORKER_CONTRACT_SHA256
    )
    if loaded_contracts != expected_contracts and not legacy_non_page:
        raise FlowJobError("worker did not load the current contracts")
    verification = result["verification"]
    if (
        not isinstance(verification, dict)
        or set(verification) != {"focused_tests", "scope", "self_check"}
        or any(
            value not in {"passed", "failed", "skipped"}
            for value in verification.values()
        )
    ):
        raise FlowJobError("worker verification contract is invalid")
    changed_files = result["changed_files"]
    evidence = result["evidence"]
    if (
        not isinstance(changed_files, list)
        or len(changed_files) != len(set(changed_files))
        or not isinstance(evidence, list)
        or len(evidence) != len(set(evidence))
    ):
        raise FlowJobError("worker artifacts are invalid")
    allowed_paths = node["allowed_paths"]
    assert isinstance(allowed_paths, list)
    project = Path(str(job["project_root"]))
    for relative in changed_files:
        relative_value = validate_relative_path(relative, "worker changed file")
        if not path_is_allowed(relative_value, allowed_paths):
            raise FlowJobError("worker changed file is outside node scope")
        require_regular_below(project, relative_value, "worker changed file")
    for relative in evidence:
        require_regular_below(node_root, relative, "worker evidence")
    if result["status"] == "passed":
        if (
            not changed_files
            or not evidence
            or result["error_code"] is not None
            or set(verification.values()) != {"passed"}
        ):
            raise FlowJobError("passed worker result is incomplete")
        if node["type"] == "page":
            validate_canonical_page_evidence(job, node_root, evidence)
        if v5:
            validate_acceptance_evidence(job, node, node_root, node_job, result)
        return "passed", [str(value) for value in changed_files]
    error_code = result["error_code"]
    if (
        not isinstance(error_code, str)
        or not error_code
        or len(error_code) > 129
        or any(ord(character) < 32 or ord(character) == 127 for character in error_code)
    ):
        raise FlowJobError("failed worker result requires a controlled error")
    return "failed", [str(value) for value in changed_files]


def record_node(job_path: Path, result_path: Path) -> dict[str, object]:
    job, root, progress = read_persisted(job_path)
    active_node = progress.get("active_node")
    if not isinstance(active_node, str) or not active_node:
        raise FlowJobError("flow has no active node")
    node_root = root / "nodes" / hashlib.sha256(active_node.encode("utf-8")).hexdigest()
    expected_result_path = node_root / "worker-result.json"
    try:
        if (
            result_path.is_symlink()
            or result_path.resolve(strict=True) != expected_result_path.resolve(strict=True)
        ):
            raise FlowJobError("worker result path does not match the active node")
    except OSError as exc:
        raise FlowJobError("worker result is missing") from exc
    dag = job["execution_dag"]
    assert isinstance(dag, list)
    node = next(
        item
        for item in dag
        if isinstance(item, dict) and item.get("node_id") == active_node
    )
    result = load_json(result_path, "worker result")
    node_status, _ = validate_worker_result_document(job, node, node_root, result)
    nodes_state = progress.get("nodes")
    if not isinstance(nodes_state, dict) or nodes_state.get(active_node) != "running":
        raise FlowJobError("active node progress is invalid")
    nodes_state[active_node] = node_status
    progress["active_node"] = None
    if node_status == "failed":
        progress["status"] = "failed"
    replace_json(root / "progress.json", progress)
    return {
        "kind": "icp.flow-node-record.v1",
        "schema_version": 1,
        "status": f"node-{node_status}",
        "node_id": active_node,
    }


def validate_flow_evidence(
    manifest_path: Path,
    root: Path,
    job: dict[str, object],
    job_digest: str,
) -> str:
    try:
        manifest_relative = str(manifest_path.resolve(strict=True).relative_to(root.resolve(strict=True)))
    except (OSError, ValueError) as exc:
        raise FlowJobError("flow evidence manifest is outside the job state") from exc
    require_regular_below(root, manifest_relative, "flow evidence manifest")
    manifest = load_json(manifest_path, "flow evidence manifest")
    if set(manifest) != {
        "artifacts",
        "job_digest",
        "job_id",
        "kind",
        "schema_version",
    }:
        raise FlowJobError("flow evidence manifest contract is invalid")
    if (
        manifest["kind"] != "icp.flow-evidence-manifest.v1"
        or manifest["schema_version"] != 1
        or manifest["job_id"] != job["job_id"]
        or manifest["job_digest"] != job_digest
    ):
        raise FlowJobError("flow evidence manifest identity is invalid")
    artifacts = manifest["artifacts"]
    required_artifacts = {"e2e", "node_tests", "runtime_capture", "visual"}
    if not isinstance(artifacts, dict) or set(artifacts) != required_artifacts:
        raise FlowJobError("flow evidence artifacts are incomplete")
    resolved_artifacts: set[Path] = set()
    for name in sorted(required_artifacts):
        artifact = artifacts[name]
        required_keys = {"path", "sha256", "status"}
        if name == "runtime_capture":
            required_keys.add("actual_source")
        if not isinstance(artifact, dict) or set(artifact) != required_keys:
            raise FlowJobError("flow evidence artifact contract is invalid")
        if artifact["status"] != "passed":
            raise FlowJobError("flow evidence did not pass")
        target = require_regular_below(root, artifact["path"], "flow evidence artifact")
        if target in resolved_artifacts:
            raise FlowJobError("flow evidence artifacts must be distinct")
        resolved_artifacts.add(target)
        if (
            not isinstance(artifact["sha256"], str)
            or hashlib.sha256(target.read_bytes()).hexdigest() != artifact["sha256"]
        ):
            raise FlowJobError("flow evidence digest mismatch")
        if name == "runtime_capture" and artifact["actual_source"] != RUNTIME_CAPTURE_SOURCES[
            str(job["platform"])
        ]:
            raise FlowJobError("flow runtime capture source is invalid")
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def finalize(
    job_path: Path,
    handoff_path: Path,
    result_path: Path,
) -> dict[str, object]:
    job, root, progress = read_persisted(job_path)
    nodes_state = progress.get("nodes")
    if (
        progress.get("active_node") is not None
        or not isinstance(nodes_state, dict)
        or not nodes_state
        or any(status != "passed" for status in nodes_state.values())
    ):
        raise FlowJobError("flow nodes are not all passed")
    handoff = load_json(handoff_path, "flow handoff")
    if job["kind"] == "icp.external-flow-job.v5" and (
        handoff.get("kind"), handoff.get("schema_version")
    ) != ("icp.flow-handoff-input.v2", 2):
        raise FlowJobError("v5 finalization requires a coverage-bound handoff")
    v5 = job["kind"] == "icp.external-flow-job.v5"
    handoff_keys = {
        "changed_files",
        "evidence_manifest",
        "kind",
        "schema_version",
        "status",
        "verification",
    }
    if v5:
        handoff_keys.add("implementation_contract_sha256")
    if set(handoff) != handoff_keys:
        raise FlowJobError("flow handoff contract is invalid")
    expected_handoff_version = (
        ("icp.flow-handoff-input.v2", 2)
        if v5
        else ("icp.flow-handoff-input.v1", 1)
    )
    if (handoff["kind"], handoff["schema_version"]) != expected_handoff_version or handoff[
        "status"
    ] != "ready-for-pr":
        raise FlowJobError("flow handoff identity is invalid")
    implementation_contract: dict[str, object] | None = None
    implementation_contract_digest: str | None = None
    if v5:
        contract_state = progress.get("implementation_contract")
        if not isinstance(contract_state, dict) or contract_state.get("status") != "passed":
            raise FlowJobError("v5 implementation contract is not frozen")
        implementation_contract_digest = str(contract_state.get("digest"))
        if handoff["implementation_contract_sha256"] != implementation_contract_digest:
            raise FlowJobError("flow handoff implementation contract mismatch")
        contract_path = root / "implementation-contract.json"
        if hashlib.sha256(contract_path.read_bytes()).hexdigest() != implementation_contract_digest:
            raise FlowJobError("persisted implementation contract drift")
        implementation_contract = load_json(
            contract_path, "persisted implementation contract"
        )
    verification = handoff["verification"]
    if (
        not isinstance(verification, dict)
        or set(verification) != {"e2e", "node_tests", "runtime_capture", "visual"}
        or set(verification.values()) != {"passed"}
    ):
        raise FlowJobError("flow verification did not pass")

    order = job["execution_order"]
    dag = job["execution_dag"]
    assert isinstance(order, list) and isinstance(dag, list)
    nodes = {
        str(node["node_id"]): node for node in dag if isinstance(node, dict)
    }
    declared_changed_files: list[str] = []
    covered_clause_ids: set[str] = set()
    worker_evidence_digests: list[dict[str, str]] = []
    for node_id in order:
        node_root = root / "nodes" / hashlib.sha256(str(node_id).encode("utf-8")).hexdigest()
        worker_result = load_json(node_root / "worker-result.json", "worker result")
        worker_status, changed = validate_worker_result_document(
            job,
            nodes[str(node_id)],
            node_root,
            worker_result,
        )
        if worker_status != "passed":
            raise FlowJobError("persisted worker result is not passed")
        if v5:
            acceptance_path = require_regular_below(
                node_root,
                worker_result["acceptance_evidence"],
                "persisted worker acceptance evidence",
            )
            acceptance = load_json(
                acceptance_path, "persisted worker acceptance evidence"
            )
            for binding in acceptance["bindings"]:
                if isinstance(binding, dict):
                    covered_clause_ids.add(str(binding["clause_id"]))
            worker_evidence_digests.append(
                {
                    "node_id": str(node_id),
                    "sha256": hashlib.sha256(acceptance_path.read_bytes()).hexdigest(),
                }
            )
        for relative in changed:
            if relative in declared_changed_files:
                raise FlowJobError("multiple nodes declared the same changed file")
            declared_changed_files.append(relative)
    if handoff["changed_files"] != declared_changed_files:
        raise FlowJobError("flow handoff changed files do not match worker results")
    project = Path(str(job["project_root"]))
    for relative in declared_changed_files:
        require_regular_below(project, relative, "flow changed file")

    evidence_manifest = handoff["evidence_manifest"]
    if not isinstance(evidence_manifest, str) or not Path(evidence_manifest).is_absolute():
        raise FlowJobError("flow evidence manifest path is invalid")
    canonical_job = canonical_bytes(job)
    job_digest = hashlib.sha256(canonical_job).hexdigest()
    evidence_digest = validate_flow_evidence(
        Path(evidence_manifest),
        root,
        job,
        job_digest,
    )
    expected_result_path = root / "result.json"
    if result_path != expected_result_path:
        raise FlowJobError("flow result path must be the canonical job result")
    coverage: dict[str, object] | None = None
    if v5:
        assert implementation_contract is not None
        required_clause_ids = [
            str(clause["clause_id"])
            for clause in implementation_contract["observable_clauses"]
            if isinstance(clause, dict)
        ]
        if covered_clause_ids != set(required_clause_ids):
            raise FlowJobError("flow acceptance coverage mismatch")
        coverage = {
            "status": "passed",
            "required_clause_ids": required_clause_ids,
            "covered_clause_ids": required_clause_ids,
            "worker_evidence_digests": worker_evidence_digests,
        }
    result: dict[str, object] = {
        "kind": "icp.flow-handoff-result.v2" if v5 else "icp.flow-handoff-result.v1",
        "schema_version": 2 if v5 else 1,
        "job_id": job["job_id"],
        "job_digest": job_digest,
        "flow_id": job["flow_id"],
        "member_digests": job["member_digests"],
        "base_revision": job["base_revision"],
        "project_root": job["project_root"],
        "status": "ready-for-pr",
        "changed_files": declared_changed_files,
        "verification": verification,
        "evidence_manifest": evidence_manifest,
        "evidence_manifest_digest": evidence_digest,
    }
    if v5:
        result["implementation_contract_sha256"] = implementation_contract_digest
        result["coverage"] = coverage
    write_once(result_path, canonical_bytes(result))
    progress["status"] = "completed"
    replace_json(root / "progress.json", progress)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="icp_flow_job_v1.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--job", required=True, type=Path)
    next_parser = subparsers.add_parser("next-node")
    next_parser.add_argument("--job", required=True, type=Path)
    contract_parser = subparsers.add_parser("record-contract")
    contract_parser.add_argument("--job", required=True, type=Path)
    contract_parser.add_argument("--contract", required=True, type=Path)
    record_parser = subparsers.add_parser("record-node")
    record_parser.add_argument("--job", required=True, type=Path)
    record_parser.add_argument("--result", required=True, type=Path)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--job", required=True, type=Path)
    finalize_parser.add_argument("--handoff", required=True, type=Path)
    finalize_parser.add_argument("--result", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "prepare":
            result = prepare(arguments.job)
        elif arguments.command == "next-node":
            result = next_node(arguments.job)
        elif arguments.command == "record-contract":
            result = record_contract(arguments.job, arguments.contract)
        elif arguments.command == "record-node":
            result = record_node(arguments.job, arguments.result)
        else:
            result = finalize(arguments.job, arguments.handoff, arguments.result)
    except FlowJobError as exc:
        print(
            json.dumps(
                {"status": "invalid-input", "reason": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
