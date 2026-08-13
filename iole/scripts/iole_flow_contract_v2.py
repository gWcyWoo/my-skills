#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_MAPPING = Path(__file__).parents[1] / "references" / "role-mapping-v2.json"
FLOW_CONNECTOR_OPERATIONS = [
    "inspect_ready_flow_root",
    "inspect_flow_rows",
    "claim_flow_rows",
    "expand_flow_claim",
    "complete_flow_rows",
    "record_flow_error",
]
SOURCE_ID = re.compile(r"^(google-sheets|microsoft-excel):[0-9a-f]{64}$")
GIT_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
ERROR_CODE = re.compile(
    r"^[a-z0-9][a-z0-9._-]{0,63}(?:/[a-z0-9][a-z0-9._-]{0,63})?$"
)
PLATFORM_PROFILES = {
    "android-java": "android-java-standard",
    "android-kotlin": "android-kotlin-standard",
    "flutter": "flutter-standard",
    "ios-objc": "ios-objc-standard",
    "ios-swift": "ios-swift-standard",
    "nextjs": "nextjs-standard",
    "vue": "vue-vite",
}
TITLE_REFERENCE = re.compile(r"→[ \t]*「(?P<title>[^」\r\n]+)」")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def normalize_title(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("page title is invalid")
    title = unicodedata.normalize("NFC", value.strip())
    if not title or any(ord(character) < 32 or ord(character) == 127 for character in title):
        raise ValueError("page title is invalid")
    return title


def path_scope_contains(scope: str, candidate: str) -> bool:
    if not scope.endswith("/"):
        return scope == candidate
    scope_parts = Path(scope).parts
    candidate_parts = Path(candidate).parts
    return candidate_parts[: len(scope_parts)] == scope_parts


def path_scopes_overlap(left: str, right: str) -> bool:
    return path_scope_contains(left, right) or path_scope_contains(right, left)


def load_mapping_v2(path: Path) -> dict[str, object]:
    mapping = load_input_document(path, "mapping")
    if set(mapping) != {
        "common",
        "flow",
        "ignored_columns",
        "job",
        "kind",
        "roles",
        "schema_version",
    }:
        raise ValueError("flow mapping top-level fields are invalid")
    if mapping["kind"] != "iole.role-mapping.v2" or mapping["schema_version"] != 2:
        raise ValueError("flow mapping contract version is invalid")
    common = mapping["common"]
    roles = mapping["roles"]
    flow = mapping["flow"]
    job = mapping["job"]
    if (
        not isinstance(common, dict)
        or not isinstance(common.get("row_id"), str)
        or not common["row_id"]
        or not isinstance(roles, dict)
        or not isinstance(flow, dict)
        or not isinstance(job, dict)
        or flow.get("connector_operations") != FLOW_CONNECTOR_OPERATIONS
    ):
        raise ValueError("flow mapping is invalid")
    page = job.get("page")
    if (
        not isinstance(page, dict)
        or common["row_id"] != page.get("title")
        or flow.get("reference_syntax") != "→「页面标题」"
    ):
        raise ValueError("flow title mapping is invalid")
    client = roles.get("client")
    if (
        not isinstance(client, dict)
        or client.get("worker_skill_name") != "icp"
        or client.get("worker_skill") != "/Users/oklik/.agents/skills/icp/SKILL.md"
        or not isinstance(client.get("queue"), dict)
    ):
        raise ValueError("client-worker-must-be-icp")
    queue = client["queue"]
    assert isinstance(queue, dict)
    expected_queue_keys = {
        "last_error",
        "lease_token",
        "lease_until",
        "pr_url",
        "reviews",
        "status",
        "status_values",
    }
    if set(queue) != expected_queue_keys:
        raise ValueError("flow mapping queue is invalid")
    status_values = queue["status_values"]
    if (
        not isinstance(status_values, dict)
        or set(status_values) != {"doing", "done", "ready", "review"}
        or status_values
        != {"ready": "ready", "doing": "doing", "review": "review", "done": "done"}
    ):
        raise ValueError("flow mapping statuses are invalid")
    if any(
        not isinstance(queue[key], str) or not queue[key]
        for key in expected_queue_keys - {"status_values"}
    ):
        raise ValueError("flow mapping columns are invalid")
    return mapping


def build_schedule_plan(
    excel_url: str,
    role: str,
    interval_minutes: int,
    project_root: Path,
    mapping_path: Path,
) -> dict[str, object]:
    if interval_minutes <= 0:
        raise ValueError("polling interval must be positive")
    parsed = urlparse(excel_url)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme == "https"
        and hostname == "docs.google.com"
        and parsed.path.startswith("/spreadsheets/")
    ):
        provider = "google-sheets"
    elif parsed.scheme == "https" and (
        hostname.endswith(".sharepoint.com")
        or hostname in {"onedrive.live.com", "1drv.ms"}
    ):
        raise ValueError("flow-connector-unavailable")
    else:
        raise ValueError("unsupported Excel URL")
    if role != "client":
        raise ValueError("flow v2 supports only the client role")
    if not project_root.is_absolute() or not project_root.is_dir():
        raise ValueError("project root must be an existing absolute directory")
    mapping = load_mapping_v2(mapping_path)
    roles = mapping["roles"]
    common = mapping["common"]
    assert isinstance(roles, dict) and isinstance(common, dict)
    client = roles["client"]
    assert isinstance(client, dict)
    queue = client["queue"]
    assert isinstance(queue, dict)
    connector_queue = {"row_id": common["row_id"], **queue}
    identity = hashlib.sha256(
        canonical_bytes(
            {
                "excel_url": excel_url,
                "project_root": str(project_root.resolve()),
                "provider": provider,
                "role": role,
            }
        )
    ).hexdigest()
    prompt_payload = {
        "excel_url": excel_url,
        "role": role,
        "flow_contract_version": 2,
        "mapping_path": str(mapping_path),
        "project_root": str(project_root.resolve()),
    }
    return {
        "kind": "iole.flow-schedule-plan.v2",
        "schema_version": 2,
        "schedule_identity": f"iole-flow-{identity[:24]}",
        "provider": provider,
        "role": role,
        "mapping_path": str(mapping_path),
        "worker_skill_name": "icp",
        "worker_skill": "/Users/oklik/.agents/skills/icp/SKILL.md",
        "connector_queue": connector_queue,
        "required_connector_operations": FLOW_CONNECTOR_OPERATIONS,
        "rrule": f"FREQ=MINUTELY;INTERVAL={interval_minutes}",
        "prompt": "Use $iole run-once with "
        + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
    }


def load_input(path: Path) -> dict[str, object]:
    if not path.is_absolute():
        raise ValueError("input path must be absolute")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("flow input cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("flow input is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("flow input must be a JSON object")
    if document.get("kind") != "iole.flow-plan-input.v2" or document.get(
        "schema_version"
    ) != 2:
        raise ValueError("flow input contract version is invalid")
    if not isinstance(document.get("source_id"), str) or SOURCE_ID.fullmatch(
        document["source_id"]
    ) is None:
        raise ValueError("flow source identity is invalid")
    if document.get("role") != "client":
        raise ValueError("flow role must be client")
    document["root_title"] = normalize_title(document.get("root_title"))
    if not isinstance(document.get("rows"), list) or not document["rows"]:
        raise ValueError("flow rows are required")
    if not isinstance(document.get("component_plan"), list):
        raise ValueError("component plan must be a list")
    component_analysis = document.get("component_analysis")
    if (
        not isinstance(component_analysis, dict)
        or set(component_analysis) != {"inventory_source", "searched_paths", "summary"}
        or not isinstance(component_analysis["inventory_source"], str)
        or not component_analysis["inventory_source"].strip()
        or not isinstance(component_analysis["searched_paths"], list)
        or not component_analysis["searched_paths"]
        or any(
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            for path in component_analysis["searched_paths"]
        )
        or not isinstance(component_analysis["summary"], str)
        or not component_analysis["summary"].strip()
    ):
        raise ValueError("component analysis is required")
    return document


def parse_references(interaction: object) -> list[dict[str, str]]:
    if interaction is None:
        return []
    if not isinstance(interaction, str):
        raise ValueError("page interaction must be a string")
    return [
        {"title": normalize_title(match.group("title"))}
        for match in TITLE_REFERENCE.finditer(interaction)
    ]


def extract_references(row_path: Path) -> dict[str, object]:
    row = load_input_document(row_path, "row")
    title = normalize_title(row.get("title"))
    references: list[dict[str, str]] = []
    for reference in parse_references(row.get("interaction", "")):
        if reference not in references:
            references.append(reference)
    return {
        "kind": "iole.page-title-references.v2",
        "schema_version": 2,
        "title": title,
        "references": references,
    }


def page_id_from_title(title: str) -> str:
    return "page-" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:20]


def page_member(row: dict[str, object], page_id: str) -> dict[str, object]:
    required_strings = (
        "title",
        "route",
        "requirement",
        "design_source",
        "design_ref",
    )
    if any(not isinstance(row.get(field), str) or not str(row[field]).strip() for field in required_strings):
        raise ValueError("page implementation fields are invalid")
    acceptance = row.get("acceptance_criteria")
    if not isinstance(acceptance, list) or any(
        not isinstance(item, str) or not item.strip() for item in acceptance
    ):
        raise ValueError("page acceptance criteria are invalid")
    review = row.get("review")
    if row.get("mode") == "implement":
        if review is not None:
            raise ValueError("implement page cannot contain review")
    elif row.get("mode") == "revise":
        if (
            not isinstance(review, dict)
            or set(review) != {"number", "text"}
            or type(review["number"]) is not int
            or review["number"] <= 0
            or not isinstance(review["text"], str)
            or not review["text"].strip()
        ):
            raise ValueError("revise page requires one numbered review")
    else:
        raise ValueError("page implementation mode is invalid")
    allowed_paths = row.get("allowed_paths")
    if (
        not isinstance(allowed_paths, list)
        or not allowed_paths
        or any(
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            for path in allowed_paths
        )
    ):
        raise ValueError("page allowed paths are invalid")
    return {
        "page_id": page_id,
        "title": row["title"],
        "route": row["route"],
        "requirement": row["requirement"],
        "acceptance_criteria": acceptance,
        "design_source": row["design_source"],
        "design_ref": row["design_ref"],
        "mode": row["mode"],
        "review": review,
    }


def build_plan(document: dict[str, object]) -> dict[str, object]:
    raw_rows = document["rows"]
    assert isinstance(raw_rows, list)
    rows: dict[str, dict[str, object]] = {}
    row_order: list[str] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ValueError("flow row must be an object")
        title = normalize_title(raw_row.get("title"))
        if raw_row.get("change_scope") not in {"modify", "navigate-only"}:
            raise ValueError("page change scope is invalid")
        if title in rows:
            raise ValueError(f"duplicate page title: {title}")
        normalized_row = dict(raw_row)
        normalized_row["title"] = title
        rows[title] = normalized_row
        row_order.append(title)

    root_title = str(document["root_title"])
    if root_title not in rows:
        raise ValueError("root page is missing")
    page_ids = {title: page_id_from_title(title) for title in row_order}

    interaction_edges: list[dict[str, str]] = []
    interaction_title_edges: list[dict[str, str]] = []
    children: dict[str, list[str]] = {title: [] for title in rows}
    for title in row_order:
        row = rows[title]
        for reference in parse_references(row.get("interaction", "")):
            target_title = reference["title"]
            if target_title not in rows:
                raise ValueError(f"referenced page is missing: {target_title}")
            edge = {
                "from": page_ids[title],
                "to": page_ids[target_title],
                "target_title": target_title,
            }
            if edge not in interaction_edges:
                interaction_edges.append(edge)
                interaction_title_edges.append({"from": title, "to": target_title})
                children[title].append(target_title)

    reachable: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(title: str) -> None:
        if title in visiting:
            raise ValueError("page interaction cycle")
        if title in visited:
            return
        visiting.add(title)
        for child_title in children[title]:
            visit(child_title)
        visiting.remove(title)
        visited.add(title)
        reachable.append(title)

    visit(root_title)
    claim_page_titles = [
        title
        for title in row_order
        if title in visited and rows[title]["change_scope"] == "modify"
    ]
    claim_page_ids = [page_ids[title] for title in claim_page_titles]
    page_execution_order = [
        f"page:{page_ids[title]}"
        for title in reachable
        if rows[title]["change_scope"] == "modify"
    ]
    excluded_pages = [
        {
            "page_id": page_ids[title],
            "title": title,
            "reason": "navigate-only",
        }
        for title in row_order
        if title in visited and rows[title]["change_scope"] == "navigate-only"
    ]
    members = [
        page_member(rows[title], page_ids[title]) for title in claim_page_titles
    ]
    member_digests = {
        str(member["page_id"]): hashlib.sha256(canonical_bytes(member)).hexdigest()
        for member in members
    }
    reopen_page_titles: list[str] = []
    blocked_page_titles: list[str] = []
    existing_pr_urls: list[str] = []
    for title in claim_page_titles:
        status = rows[title].get("status")
        if status not in {"ready", "doing", "review", "done"}:
            raise ValueError(f"page status is invalid: {title}")
        if status in {"review", "done"}:
            reopen_page_titles.append(title)
        elif status == "doing":
            blocked_page_titles.append(title)
        pr_url = rows[title].get("pr_url", "")
        if not isinstance(pr_url, str):
            raise ValueError(f"page PR URL is invalid: {title}")
        if pr_url:
            parsed_pr = urlparse(pr_url)
            if parsed_pr.scheme not in {"http", "https"} or not parsed_pr.hostname:
                raise ValueError(f"page PR URL is invalid: {title}")
            existing_pr_urls.append(pr_url)
    distinct_pr_urls = list(dict.fromkeys(existing_pr_urls))
    identity = {
        "source_id": document["source_id"],
        "role": document["role"],
        "root_page_title": root_title,
        "claim_page_titles": claim_page_titles,
        "excluded_pages": excluded_pages,
    }
    flow_id = "iole-flow-" + hashlib.sha256(canonical_bytes(identity)).hexdigest()[:24]
    root_page_id = page_ids[root_title]
    if blocked_page_titles:
        return {
            "kind": "iole.flow-plan.v2",
            "schema_version": 2,
            "flow_id": flow_id,
            "decision": "blocked",
            "reason": "active-member-claim",
            "source_id": document["source_id"],
            "role": document["role"],
            "root_page_id": root_page_id,
            "root_page_title": root_title,
            "claim_page_ids": claim_page_ids,
            "claim_page_titles": claim_page_titles,
            "blocked_page_titles": blocked_page_titles,
        }
    if len(distinct_pr_urls) > 1:
        return {
            "kind": "iole.flow-plan.v2",
            "schema_version": 2,
            "flow_id": flow_id,
            "decision": "blocked",
            "reason": "pr-conflict",
            "source_id": document["source_id"],
            "role": document["role"],
            "root_page_id": root_page_id,
            "root_page_title": root_title,
            "claim_page_ids": claim_page_ids,
            "claim_page_titles": claim_page_titles,
            "conflicting_pr_urls": distinct_pr_urls,
        }
    existing_pr_url = distinct_pr_urls[0] if distinct_pr_urls else None
    decision = "needs-reopen" if reopen_page_titles else "ready"
    component_plan = document["component_plan"]
    assert isinstance(component_plan, list)
    component_nodes: list[dict[str, object]] = []
    component_dependencies: dict[str, list[str]] = {
        title: [] for title in claim_page_titles
    }
    component_decisions: list[dict[str, object]] = []
    component_ids: set[str] = set()
    for raw_component in component_plan:
        if not isinstance(raw_component, dict) or set(raw_component) != {
            "allowed_paths",
            "code_path",
            "component_id",
            "consumers",
            "decision",
            "evidence",
            "name",
        }:
            raise ValueError("component decision contract is invalid")
        component_id = raw_component["component_id"]
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("component identity is invalid")
        if component_id in component_ids:
            raise ValueError("duplicate component identity")
        component_ids.add(component_id)
        if raw_component["decision"] not in {
            "reuse",
            "extend",
            "create-shared",
            "create-local",
        }:
            raise ValueError("component decision is invalid")
        for field in ("name", "code_path", "evidence"):
            if not isinstance(raw_component[field], str) or not raw_component[field].strip():
                raise ValueError(f"component {field} is invalid")
        code_path = Path(str(raw_component["code_path"]))
        if code_path.is_absolute() or ".." in code_path.parts:
            raise ValueError("component code path must be project-relative")
        allowed_paths = raw_component["allowed_paths"]
        if (
            not isinstance(allowed_paths, list)
            or not allowed_paths
            or raw_component["code_path"] not in allowed_paths
            or any(
                not isinstance(path, str)
                or not path
                or Path(path).is_absolute()
                or ".." in Path(path).parts
                for path in allowed_paths
            )
        ):
            raise ValueError("component allowed paths are invalid")
        consumers = raw_component["consumers"]
        if (
            not isinstance(consumers, list)
            or not consumers
            or len(consumers) != len(set(consumers))
            or any(consumer not in claim_page_titles for consumer in consumers)
        ):
            raise ValueError("component consumers are invalid")
        if raw_component["decision"] == "create-local" and len(consumers) != 1:
            raise ValueError("local component must have exactly one consumer")
        if raw_component["decision"] == "create-local":
            consumer_paths = rows[consumers[0]]["allowed_paths"]
            assert isinstance(consumer_paths, list)
            if any(
                not any(
                    path_scope_contains(str(consumer_path), str(component_path))
                    for consumer_path in consumer_paths
                )
                for component_path in allowed_paths
            ):
                raise ValueError(
                    "local component path is not owned by its consumer page: "
                    f"{component_id}"
                )
        internal_consumers = [page_ids[str(consumer)] for consumer in consumers]
        component_decisions.append(
            {**raw_component, "consumers": internal_consumers}
        )
        if raw_component["decision"] in {"extend", "create-shared"}:
            node_id = f"component:{component_id}"
            component_nodes.append(
                {
                    "node_id": node_id,
                    "type": "shared-component",
                    "depends_on": [],
                    "allowed_paths": allowed_paths,
                    "page_ids": internal_consumers,
                }
            )
            for consumer in consumers:
                component_dependencies[consumer].append(node_id)

    page_nodes: list[dict[str, object]] = []
    for title in claim_page_titles:
        page_id = page_ids[title]
        dependencies = list(component_dependencies[title])
        for child_title in children[title]:
            if child_title in claim_page_titles:
                dependencies.append(f"page:{page_ids[child_title]}")
        page_nodes.append(
            {
                "node_id": f"page:{page_id}",
                "type": "page",
                "depends_on": dependencies,
                "allowed_paths": rows[title]["allowed_paths"],
                "page_ids": [page_id],
            }
        )
    execution_dag = [*component_nodes, *page_nodes]
    for index, left_node in enumerate(execution_dag):
        left_paths = left_node["allowed_paths"]
        assert isinstance(left_paths, list)
        for right_node in execution_dag[index + 1 :]:
            right_paths = right_node["allowed_paths"]
            assert isinstance(right_paths, list)
            if any(
                path_scopes_overlap(str(left_path), str(right_path))
                for left_path in left_paths
                for right_path in right_paths
            ):
                raise ValueError(
                    "execution node path ownership overlaps: "
                    f"{left_node['node_id']} and {right_node['node_id']}"
                )
    execution_order = [
        *(node["node_id"] for node in component_nodes),
        *page_execution_order,
    ]
    return {
        "kind": "iole.flow-plan.v2",
        "schema_version": 2,
        "flow_id": flow_id,
        "decision": decision,
        "source_id": document["source_id"],
        "role": document["role"],
        "root_page_id": root_page_id,
        "root_page_title": root_title,
        "claim_page_ids": claim_page_ids,
        "claim_page_titles": claim_page_titles,
        "reopen_page_titles": reopen_page_titles,
        "existing_pr_url": existing_pr_url,
        "member_digests": member_digests,
        "members": members,
        "excluded_pages": excluded_pages,
        "interaction_edges": interaction_edges,
        "interaction_title_edges": interaction_title_edges,
        "component_decisions": component_decisions,
        "component_analysis": document["component_analysis"],
        "execution_dag": execution_dag,
        "execution_order": execution_order,
    }


def build_job(
    plan_path: Path,
    worktree: Path,
    base_revision: str,
    platform: str,
) -> dict[str, object]:
    plan = load_input_document(plan_path, "flow plan")
    if plan.get("kind") != "iole.flow-plan.v2" or plan.get("schema_version") != 2:
        raise ValueError("flow plan contract version is invalid")
    if plan.get("decision") != "ready":
        raise ValueError("flow plan is not ready")
    if not worktree.is_absolute() or not worktree.is_dir():
        raise ValueError("worktree must be an existing absolute directory")
    if not isinstance(base_revision, str) or GIT_REVISION.fullmatch(base_revision) is None:
        raise ValueError("base revision is invalid")
    profile = PLATFORM_PROFILES.get(platform)
    if profile is None:
        raise ValueError("platform is unsupported")
    for field in (
        "component_decisions",
        "component_analysis",
        "execution_dag",
        "execution_order",
        "flow_id",
        "interaction_edges",
        "member_digests",
        "members",
        "root_page_id",
    ):
        if field not in plan:
            raise ValueError(f"flow plan is missing {field}")
    member_digests = plan["member_digests"]
    if not isinstance(member_digests, dict) or not member_digests:
        raise ValueError("flow plan member digests are invalid")
    aggregate_digest = hashlib.sha256(canonical_bytes(member_digests)).hexdigest()
    return {
        "kind": "icp.external-flow-job.v3",
        "schema_version": 3,
        "job_id": f"iole:client:{plan['flow_id']}:{aggregate_digest[:12]}",
        "flow_id": plan["flow_id"],
        "project_root": str(worktree.resolve()),
        "base_revision": base_revision.lower(),
        "platform": platform,
        "profile": profile,
        "role": "client",
        "root_page_id": plan["root_page_id"],
        "member_digests": member_digests,
        "members": plan["members"],
        "component_decisions": plan["component_decisions"],
        "component_analysis": plan["component_analysis"],
        "interaction_edges": plan["interaction_edges"],
        "execution_dag": plan["execution_dag"],
        "execution_order": plan["execution_order"],
    }


def build_branch_name(plan_path: Path) -> dict[str, object]:
    plan = load_input_document(plan_path, "flow plan")
    if plan.get("kind") != "iole.flow-plan.v2" or plan.get("schema_version") != 2:
        raise ValueError("flow plan contract version is invalid")
    source_id = plan.get("source_id")
    role = plan.get("role")
    flow_id = plan.get("flow_id")
    if not isinstance(source_id, str) or SOURCE_ID.fullmatch(source_id) is None:
        raise ValueError("flow source identity is invalid")
    if not isinstance(role, str) or not role:
        raise ValueError("flow role is invalid")
    if not isinstance(flow_id, str) or not flow_id:
        raise ValueError("flow identity is invalid")
    source_digest = source_id.rsplit(":", 1)[1]
    flow_digest = hashlib.sha256(flow_id.encode("utf-8")).hexdigest()
    return {
        "kind": "iole.flow-branch-name.v2",
        "schema_version": 2,
        "flow_id": flow_id,
        "branch_name": f"codex/iole-flow-{source_digest[:12]}-{role}-{flow_digest[:12]}",
    }


def build_pr_recovery_plan(
    plan_path: Path,
    pr_url: str,
    mr_state: str,
    source_branch: str,
    dev_revision: str,
    review_number: int,
) -> dict[str, object]:
    plan = load_input_document(plan_path, "flow plan")
    branch = build_branch_name(plan_path)
    parsed_pr = urlparse(pr_url)
    if parsed_pr.scheme not in {"http", "https"} or not parsed_pr.hostname:
        raise ValueError("existing PR URL is invalid")
    if mr_state not in {"open", "merged", "closed"}:
        raise ValueError("MR state is invalid")
    if source_branch not in {"present", "missing"}:
        raise ValueError("source branch state is invalid")
    members = plan.get("claim_page_titles")
    if not isinstance(members, list) or not members:
        raise ValueError("flow plan members are invalid")
    if mr_state == "open" and source_branch == "present":
        return {
            "kind": "iole.flow-pr-recovery-plan.v2",
            "schema_version": 2,
            "action": "reuse-existing-pr",
            "flow_id": plan["flow_id"],
            "member_titles": members,
            "existing_pr_url": pr_url,
            "base_revision": None,
            "branch_name": None,
            "changed_action": "update-existing-pr",
            "unchanged_action": "return-flow-to-review",
        }
    if GIT_REVISION.fullmatch(dev_revision) is None:
        raise ValueError("dev revision is invalid")
    if review_number < 1:
        raise ValueError("review number must be positive")
    pr_digest = hashlib.sha256(pr_url.encode("utf-8")).hexdigest()
    return {
        "kind": "iole.flow-pr-recovery-plan.v2",
        "schema_version": 2,
        "action": "inspect-from-dev",
        "flow_id": plan["flow_id"],
        "member_titles": members,
        "existing_pr_url": pr_url,
        "base_revision": dev_revision.lower(),
        "branch_name": (
            f"{branch['branch_name']}-recovery-{pr_digest[:8]}-r{review_number}"
        ),
        "changed_action": "create-new-pr",
        "unchanged_action": "return-flow-to-review",
    }


def build_review_writeback(
    plan_path: Path,
    lease_token: str,
    pr_url: str,
) -> dict[str, object]:
    plan = load_input_document(plan_path, "flow plan")
    if (
        plan.get("kind") != "iole.flow-plan.v2"
        or plan.get("schema_version") != 2
        or plan.get("decision") != "ready"
    ):
        raise ValueError("flow plan is not ready")
    if (
        not isinstance(lease_token, str)
        or not lease_token
        or any(ord(character) < 32 or ord(character) == 127 for character in lease_token)
    ):
        raise ValueError("flow lease token is invalid")
    parsed_pr = urlparse(pr_url)
    if parsed_pr.scheme not in {"http", "https"} or not parsed_pr.hostname:
        raise ValueError("PR URL is invalid")
    members = plan.get("claim_page_titles")
    member_digests = plan.get("member_digests")
    if not isinstance(members, list) or not members or not isinstance(member_digests, dict):
        raise ValueError("flow plan members are invalid")
    return {
        "kind": "iole.flow-review-writeback-intent.v2",
        "schema_version": 2,
        "connector_operation": "complete_flow_rows",
        "flow_id": plan["flow_id"],
        "role": plan["role"],
        "member_titles": members,
        "expected_member_digests": member_digests,
        "expected_status": "doing",
        "lease_token": lease_token,
        "set": {
            "status": "review",
            "pr_url": pr_url,
            "lease_token": "",
            "lease_until": "",
            "last_error": "",
        },
    }


def build_error_writeback(
    plan_path: Path,
    lease_token: str,
    error_code: str,
) -> dict[str, object]:
    plan = load_input_document(plan_path, "flow plan")
    if (
        plan.get("kind") != "iole.flow-plan.v2"
        or plan.get("schema_version") != 2
        or plan.get("decision") != "ready"
    ):
        raise ValueError("flow plan is not ready")
    if (
        not isinstance(lease_token, str)
        or not lease_token
        or any(ord(character) < 32 or ord(character) == 127 for character in lease_token)
    ):
        raise ValueError("flow lease token is invalid")
    if ERROR_CODE.fullmatch(error_code) is None:
        raise ValueError("error code is invalid")
    members = plan.get("claim_page_titles")
    member_digests = plan.get("member_digests")
    if not isinstance(members, list) or not members or not isinstance(member_digests, dict):
        raise ValueError("flow plan members are invalid")
    return {
        "kind": "iole.flow-error-writeback-intent.v2",
        "schema_version": 2,
        "connector_operation": "record_flow_error",
        "flow_id": plan["flow_id"],
        "role": plan["role"],
        "member_titles": members,
        "expected_member_digests": member_digests,
        "expected_status": "doing",
        "lease_token": lease_token,
        "set": {"last_error": error_code},
        "orchestrator_action": {
            "notify_user_immediately": True,
            "stop_current_run": True,
        },
    }


def load_input_document(path: Path, label: str) -> dict[str, object]:
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label} cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iole_flow_contract_v2.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    schedule_parser = subparsers.add_parser("schedule-plan")
    schedule_parser.add_argument("--excel-url", required=True)
    schedule_parser.add_argument("--role", required=True)
    schedule_parser.add_argument("--im", type=int, default=10)
    schedule_parser.add_argument("--project-root", required=True, type=Path)
    schedule_parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    plan_parser = subparsers.add_parser("build-plan")
    plan_parser.add_argument("--input", required=True, type=Path)
    job_parser = subparsers.add_parser("build-job")
    job_parser.add_argument("--plan", required=True, type=Path)
    job_parser.add_argument("--worktree", required=True, type=Path)
    job_parser.add_argument("--base-revision", required=True)
    job_parser.add_argument("--platform", required=True)
    refs_parser = subparsers.add_parser("extract-refs")
    refs_parser.add_argument("--row", required=True, type=Path)
    branch_parser = subparsers.add_parser("branch-name")
    branch_parser.add_argument("--plan", required=True, type=Path)
    recovery_parser = subparsers.add_parser("pr-recovery-plan")
    recovery_parser.add_argument("--plan", required=True, type=Path)
    recovery_parser.add_argument("--pr-url", required=True)
    recovery_parser.add_argument("--mr-state", required=True)
    recovery_parser.add_argument("--source-branch", required=True)
    recovery_parser.add_argument("--dev-revision", required=True)
    recovery_parser.add_argument("--review-number", required=True, type=int)
    writeback_parser = subparsers.add_parser("build-review-writeback")
    writeback_parser.add_argument("--plan", required=True, type=Path)
    writeback_parser.add_argument("--lease-token", required=True)
    writeback_parser.add_argument("--pr-url", required=True)
    error_parser = subparsers.add_parser("build-error-writeback")
    error_parser.add_argument("--plan", required=True, type=Path)
    error_parser.add_argument("--lease-token", required=True)
    error_parser.add_argument("--error-code", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "schedule-plan":
            result = build_schedule_plan(
                arguments.excel_url,
                arguments.role,
                arguments.im,
                arguments.project_root,
                arguments.mapping,
            )
        elif arguments.command == "extract-refs":
            result = extract_references(arguments.row)
        elif arguments.command == "branch-name":
            result = build_branch_name(arguments.plan)
        elif arguments.command == "pr-recovery-plan":
            result = build_pr_recovery_plan(
                arguments.plan,
                arguments.pr_url,
                arguments.mr_state,
                arguments.source_branch,
                arguments.dev_revision,
                arguments.review_number,
            )
        elif arguments.command == "build-review-writeback":
            result = build_review_writeback(
                arguments.plan,
                arguments.lease_token,
                arguments.pr_url,
            )
        elif arguments.command == "build-error-writeback":
            result = build_error_writeback(
                arguments.plan,
                arguments.lease_token,
                arguments.error_code,
            )
        elif arguments.command == "build-plan":
            result = build_plan(load_input(arguments.input))
        else:
            result = build_job(
                arguments.plan,
                arguments.worktree,
                arguments.base_revision,
                arguments.platform,
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps(
                {"status": "invalid-input", "reason": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
