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
from pathlib import Path

from shared_core import visual_evidence_v1


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
MEMBER_KEYS = {
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


def validate_job(document: dict[str, object]) -> dict[str, object]:
    if set(document) != JOB_KEYS:
        raise FlowJobError("flow job keys do not match the contract")
    if document["kind"] != "icp.external-flow-job.v3" or document["schema_version"] != 3:
        raise FlowJobError("flow job contract version is invalid")
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
        if not isinstance(member, dict) or set(member) != MEMBER_KEYS:
            raise FlowJobError("flow member contract is invalid")
        page_id = member["page_id"]
        if not isinstance(page_id, str) or not page_id or page_id in member_ids:
            raise FlowJobError("flow member identity is invalid")
        member_ids.append(page_id)
        for field in ("title", "route", "requirement", "design_source", "design_ref"):
            if not isinstance(member[field], str) or not member[field].strip():
                raise FlowJobError(f"flow member {field} is invalid")
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
        replace_json(
            progress_path,
            {
                "kind": "icp.flow-progress.v1",
                "schema_version": 1,
                "job_digest": job_digest,
                "status": "active",
                "active_node": None,
                "nodes": {node_id: "pending" for node_id in order},
            },
        )
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
    return "\n".join(
        [
            "Use $icp to implement this one persisted flow node.",
            f"Read the ICP Skill completely: {ICP_SKILL_REF}",
            f"Read the worker contract completely: {WORKER_CONTRACT}",
            f"Node input: {node_job_path}",
            f"Write the worker result JSON only to: {result_path}",
            f"Project worktree: {job['project_root']}",
            "Edit only the allowed_paths declared in the node input.",
            "Do not read or write Sheets/Excel, leases, statuses, Git, commits, branches, pushes, or PRs.",
            "Invoke and follow $icp for this node; reading the Skill alone is not compliance.",
            "For a page node, execute ICP's full design compiler loop and seal its standard visual-evidence.json with shared_core/visual_evidence_v1.py; do not substitute a worker-specific workflow.",
            "A missing design, missing real runtime capture, behavior-only scaffold, or remaining visual mismatch must be status=failed and must be reported immediately.",
            "Run focused tests and report exact changed files plus the canonical ICP evidence required by the worker contract.",
            "Do not start another node; return control after this result is ready.",
            "",
        ]
    )


def next_node(job_path: Path) -> dict[str, object]:
    job, root, progress = read_persisted(job_path)
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
    node_input = {
        "kind": "icp.worker-node-job.v1",
        "schema_version": 1,
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
    if "visual-evidence.json" not in evidence:
        raise FlowJobError("page worker result requires canonical ICP visual evidence")
    manifest_path = require_regular_below(
        node_root,
        "visual-evidence.json",
        "page visual evidence",
    )
    manifest = load_json(manifest_path, "page visual evidence")
    try:
        visual_evidence_v1.verify_evidence(manifest)
    except (OSError, ValueError) as exc:
        raise FlowJobError("page visual evidence did not pass") from exc
    if (
        manifest["status"] != "pass"
        or manifest["actual"]["actual_source"]
        != RUNTIME_CAPTURE_SOURCES[str(job["platform"])]
    ):
        raise FlowJobError("page visual evidence did not pass")
    bound_targets = [
        require_absolute_regular_below(
            node_root, manifest["reference"]["path"], "page design reference"
        ),
        require_absolute_regular_below(
            node_root, manifest["actual"]["path"], "page runtime capture"
        ),
        require_absolute_regular_below(
            node_root, manifest["actual"]["provenance_path"], "page runtime provenance"
        ),
        require_absolute_regular_below(
            node_root, manifest["diff"]["path"], "page visual diff"
        ),
    ]
    if len(bound_targets) != len(set(bound_targets)):
        raise FlowJobError("page visual evidence artifacts must be distinct")


def validate_worker_result_document(
    job: dict[str, object],
    node: dict[str, object],
    node_root: Path,
    result: dict[str, object],
) -> tuple[str, list[str]]:
    node_id = str(node["node_id"])
    if set(result) != WORKER_RESULT_KEYS:
        raise FlowJobError("worker result contract is invalid")
    if (
        result["kind"] != "icp.worker-node-result.v1"
        or result["schema_version"] != 1
        or result["node_id"] != node_id
        or result["status"] not in {"passed", "failed"}
    ):
        raise FlowJobError("worker result identity is invalid")
    loaded_contracts = result["loaded_contracts"]
    if not isinstance(loaded_contracts, dict) or set(loaded_contracts) != {
        "icp_skill_sha256",
        "worker_contract_sha256",
    }:
        raise FlowJobError("worker contract evidence is invalid")
    expected_contracts = {
        "icp_skill_sha256": hashlib.sha256(ICP_SKILL.read_bytes()).hexdigest(),
        "worker_contract_sha256": hashlib.sha256(WORKER_CONTRACT.read_bytes()).hexdigest(),
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
    if set(handoff) != {
        "changed_files",
        "evidence_manifest",
        "kind",
        "schema_version",
        "status",
        "verification",
    }:
        raise FlowJobError("flow handoff contract is invalid")
    if (
        handoff["kind"] != "icp.flow-handoff-input.v1"
        or handoff["schema_version"] != 1
        or handoff["status"] != "ready-for-pr"
    ):
        raise FlowJobError("flow handoff identity is invalid")
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
    result = {
        "kind": "icp.flow-handoff-result.v1",
        "schema_version": 1,
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
