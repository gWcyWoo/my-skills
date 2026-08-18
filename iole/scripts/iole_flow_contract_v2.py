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
ICP_SKILL_PATH = "~/.agents/skills/icp/SKILL.md"
FLOW_CONNECTOR_OPERATIONS = [
    "inspect_ready_flow_root",
    "inspect_title_catalog",
    "inspect_flow_rows",
    "claim_flow_rows",
    "release_flow_claim",
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
DESIGN_URL = re.compile(r"https?://[^\s<>\"']+")
REVIEW_LINE = re.compile(r"^\s*(?P<number>[1-9][0-9]*)\.\s*(?P<text>\S(?:.*\S)?)\s*$")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


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
        or not isinstance(page.get("interaction"), str)
        or not page["interaction"]
        or flow.get("reference_syntax") != "→「页面标题」"
    ):
        raise ValueError("flow title mapping is invalid")
    if not isinstance(job.get("design_ref"), str) or not job["design_ref"]:
        raise ValueError("flow mapping design reference is invalid")
    design_source = job.get("design_source")
    if (
        not isinstance(design_source, dict)
        or set(design_source) != {"constant"}
        or not isinstance(design_source["constant"], str)
        or not design_source["constant"]
    ):
        raise ValueError("flow mapping design source is invalid")
    route_source = page.get("route")
    if not (
        isinstance(route_source, str)
        and route_source
        or isinstance(route_source, list)
        and route_source
        and all(isinstance(alias, str) and alias for alias in route_source)
    ):
        raise ValueError("flow mapping route is invalid")
    for section_name, section_keys in (
        ("requirement_sections", {"label", "source"}),
        ("acceptance_sections", {"prefix", "source"}),
    ):
        sections = job.get(section_name)
        if not isinstance(sections, list) or any(
            not isinstance(section, dict)
            or set(section) != section_keys
            or any(
                not isinstance(section[key], str) or not section[key]
                for key in section_keys
            )
            for section in sections
        ):
            raise ValueError(f"flow mapping {section_name} is invalid")
    client = roles.get("client")
    if (
        not isinstance(client, dict)
        or client.get("worker_skill_name") != "icp"
        or client.get("worker_skill") != ICP_SKILL_PATH
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


def exact_cell(row: dict[str, object], source: str, label: str) -> str:
    if source not in row:
        raise ValueError(f"raw Sheet field is missing: {label}")
    value = row[source]
    if not isinstance(value, str):
        raise ValueError(f"raw Sheet field must be a string: {label}")
    return value


def nullable_cell(row: dict[str, object], source: str, label: str) -> str | None:
    value = exact_cell(row, source, label)
    return None if value == "" else value


def declared_source_columns(mapping: dict[str, object]) -> set[str]:
    common = mapping["common"]
    job = mapping["job"]
    assert isinstance(common, dict) and isinstance(job, dict)
    page = job["page"]
    assert isinstance(page, dict)
    columns: set[str] = {str(common["row_id"]), str(job["design_ref"])}

    def add_source(source: object) -> None:
        if isinstance(source, str):
            columns.add(source)
            return
        if isinstance(source, list):
            columns.update(str(alias) for alias in source)

    add_source(page["route"])
    add_source(page["interaction"])
    for section_name in ("requirement_sections", "acceptance_sections"):
        sections = job[section_name]
        assert isinstance(sections, list)
        for section in sections:
            assert isinstance(section, dict)
            add_source(section["source"])
    return columns


def handoff_columns_for_raw_row(
    raw_row: dict[str, object], mapping: dict[str, object]
) -> list[str]:
    declared = declared_source_columns(mapping)
    return [column for column in raw_row if column in declared]


def complete_nullable_row(
    raw_row: dict[str, object], columns: list[str]
) -> dict[str, str | None]:
    if not columns:
        raise ValueError("declared handoff columns are required")
    normalized: dict[str, str | None] = {}
    for column in columns:
        if not isinstance(column, str) or not column:
            raise ValueError("raw Sheet column name is invalid")
        if column not in raw_row:
            raise ValueError(f"declared handoff column is missing: {column}")
        value = raw_row[column]
        if not isinstance(value, str):
            raise ValueError(f"raw Sheet field must be a string: {column}")
        normalized[column] = None if value == "" else value
    return normalized


def resolve_exact_source(row: dict[str, object], source: object, label: str) -> str:
    if isinstance(source, str):
        return exact_cell(row, source, label)
    if not isinstance(source, list) or not source or any(
        not isinstance(alias, str) or not alias for alias in source
    ):
        raise ValueError(f"mapping {label} source is invalid")
    present = [alias for alias in source if alias in row]
    if len(present) != 1:
        raise ValueError(f"raw Sheet {label} alias is missing or ambiguous")
    return exact_cell(row, present[0], label)


def exact_sections(
    row: dict[str, object], sections: object, label_key: str
) -> list[dict[str, str]]:
    if not isinstance(sections, list):
        raise ValueError("mapping sections are invalid")
    result: list[dict[str, str]] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("mapping section is invalid")
        source = section.get("source")
        label = section.get(label_key)
        if not isinstance(source, str) or not isinstance(label, str):
            raise ValueError("mapping section fields are invalid")
        result.append({label_key: label, "value": exact_cell(row, source, label)})
    return result


def nullable_sections(
    row: dict[str, object], sections: object, label_key: str
) -> list[dict[str, object]]:
    if not isinstance(sections, list):
        raise ValueError("mapping sections are invalid")
    result: list[dict[str, object]] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("mapping section is invalid")
        source = section.get("source")
        label = section.get(label_key)
        if not isinstance(source, str) or not isinstance(label, str):
            raise ValueError("mapping section fields are invalid")
        result.append({label_key: label, "value": nullable_cell(row, source, label)})
    return result


def parse_latest_review(value: str) -> dict[str, object] | None:
    if not value.strip():
        return None
    parsed: list[tuple[int, str]] = []
    previous = 0
    for line in value.splitlines():
        if not line.strip():
            continue
        match = REVIEW_LINE.fullmatch(line)
        if match is None:
            raise ValueError("reviews must use numbered non-empty lines")
        number = int(match.group("number"))
        if number <= previous:
            raise ValueError("review numbers must be strictly increasing")
        previous = number
        parsed.append((number, match.group("text")))
    if not parsed:
        return None
    number, text = parsed[-1]
    return {"number": number, "text": text}


def source_contract_digest(contract: dict[str, object]) -> str:
    payload = {key: value for key, value in contract.items() if key != "contract_digest"}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def validate_source_contract(contract: object) -> dict[str, object]:
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
    if not isinstance(contract, dict) or set(contract) != expected_keys:
        raise ValueError("Sheet source contract is invalid")
    if (
        contract["kind"] != "iole.sheet-member-contract.v1"
        or contract["schema_version"] != 1
    ):
        raise ValueError("Sheet source contract version is invalid")
    for field in ("title", "route", "design_ref", "interaction"):
        if not isinstance(contract[field], str):
            raise ValueError(f"Sheet source contract {field} is invalid")
    for field, label_key in (
        ("requirement_sections", "label"),
        ("acceptance_sections", "prefix"),
    ):
        sections = contract[field]
        if not isinstance(sections, list) or any(
            not isinstance(section, dict)
            or set(section) != {label_key, "value"}
            or not isinstance(section[label_key], str)
            or not section[label_key]
            or not isinstance(section["value"], str)
            for section in sections
        ):
            raise ValueError(f"Sheet source contract {field} is invalid")
    digest = contract["contract_digest"]
    if (
        not isinstance(digest, str)
        or SHA256_HEX.fullmatch(digest) is None
        or digest != source_contract_digest(contract)
    ):
        raise ValueError("Sheet source contract digest mismatch")
    return contract


def source_contract_from_raw(
    raw_row: dict[str, object], job_mapping: dict[str, object]
) -> dict[str, object]:
    page_mapping = job_mapping["page"]
    assert isinstance(page_mapping, dict)
    contract: dict[str, object] = {
        "kind": "iole.sheet-member-contract.v1",
        "schema_version": 1,
        "title": resolve_exact_source(raw_row, page_mapping["title"], "title"),
        "route": resolve_exact_source(raw_row, page_mapping["route"], "route"),
        "design_ref": exact_cell(
            raw_row, str(job_mapping["design_ref"]), "design_ref"
        ),
        "interaction": exact_cell(
            raw_row, str(page_mapping["interaction"]), "interaction"
        ),
        "requirement_sections": exact_sections(
            raw_row, job_mapping["requirement_sections"], "label"
        ),
        "acceptance_sections": exact_sections(
            raw_row, job_mapping["acceptance_sections"], "prefix"
        ),
    }
    contract["contract_digest"] = source_contract_digest(contract)
    return validate_source_contract(contract)


def validate_nullable_source_contract(contract: object) -> dict[str, object]:
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
    if not isinstance(contract, dict) or set(contract) != expected_keys:
        raise ValueError("nullable Sheet source contract is invalid")
    if (
        contract["kind"] != "iole.sheet-member-contract.v2"
        or contract["schema_version"] != 2
    ):
        raise ValueError("nullable Sheet source contract version is invalid")
    if not isinstance(contract["title"], str) or not contract["title"]:
        raise ValueError("nullable Sheet source contract title is invalid")
    for field in ("route", "design_ref", "interaction"):
        if contract[field] is not None and (
            not isinstance(contract[field], str) or contract[field] == ""
        ):
            raise ValueError(f"nullable Sheet source contract {field} is invalid")
    for field, label_key in (
        ("requirement_sections", "label"),
        ("acceptance_sections", "prefix"),
    ):
        sections = contract[field]
        if not isinstance(sections, list) or any(
            not isinstance(section, dict)
            or set(section) != {label_key, "value"}
            or not isinstance(section[label_key], str)
            or not section[label_key]
            or (
                section["value"] is not None
                and (
                    not isinstance(section["value"], str)
                    or section["value"] == ""
                )
            )
            for section in sections
        ):
            raise ValueError(f"nullable Sheet source contract {field} is invalid")
    digest = contract["contract_digest"]
    if (
        not isinstance(digest, str)
        or SHA256_HEX.fullmatch(digest) is None
        or digest != source_contract_digest(contract)
    ):
        raise ValueError("nullable Sheet source contract digest mismatch")
    return contract


def nullable_source_contract_from_raw(
    raw_row: dict[str, object], job_mapping: dict[str, object]
) -> dict[str, object]:
    page_mapping = job_mapping["page"]
    assert isinstance(page_mapping, dict)
    route_source = page_mapping["route"]
    exact_route = resolve_exact_source(raw_row, route_source, "route")
    contract: dict[str, object] = {
        "kind": "iole.sheet-member-contract.v2",
        "schema_version": 2,
        "title": resolve_exact_source(raw_row, page_mapping["title"], "title"),
        "route": None if exact_route == "" else exact_route,
        "design_ref": nullable_cell(
            raw_row, str(job_mapping["design_ref"]), "design_ref"
        ),
        "interaction": nullable_cell(
            raw_row, str(page_mapping["interaction"]), "interaction"
        ),
        "requirement_sections": nullable_sections(
            raw_row, job_mapping["requirement_sections"], "label"
        ),
        "acceptance_sections": nullable_sections(
            raw_row, job_mapping["acceptance_sections"], "prefix"
        ),
    }
    contract["contract_digest"] = source_contract_digest(contract)
    return validate_nullable_source_contract(contract)


def extract_design_refs(value: str) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for match in DESIGN_URL.finditer(value):
        line_start = value.rfind("\n", 0, match.start()) + 1
        label = value[line_start : match.start()].strip().rstrip("：:-— ")
        url = match.group(0).rstrip("，,。；;）)")
        references.append(
            {
                "ordinal": len(references) + 1,
                "label": label,
                "url": url,
            }
        )
    return references


def validate_title_catalog(
    value: object,
    *,
    source_id: str,
    row_id_column: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "catalog_digest",
        "kind",
        "row_id_column",
        "schema_version",
        "sheet_name",
        "spreadsheet_id",
        "titles",
    }:
        raise ValueError("flow title catalog is invalid")
    if (
        value.get("kind") != "icps.flow-title-catalog.v1"
        or value.get("schema_version") != 1
        or value.get("row_id_column") != row_id_column
    ):
        raise ValueError("flow title catalog version or row identity is invalid")
    spreadsheet_id = value.get("spreadsheet_id")
    sheet_name = value.get("sheet_name")
    titles = value.get("titles")
    if (
        not isinstance(spreadsheet_id, str)
        or not spreadsheet_id
        or not isinstance(sheet_name, str)
        or not sheet_name
        or not isinstance(titles, list)
        or not titles
    ):
        raise ValueError("flow title catalog identity is invalid")
    normalized_titles = [normalize_title(title) for title in titles]
    if normalized_titles != titles or len(titles) != len(set(titles)):
        raise ValueError("flow title catalog contains duplicate or non-canonical titles")
    payload = {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "row_id_column": row_id_column,
        "titles": titles,
    }
    if value.get("catalog_digest") != hashlib.sha256(canonical_bytes(payload)).hexdigest():
        raise ValueError("flow title catalog digest mismatch")
    expected_source_id = "google-sheets:" + hashlib.sha256(
        canonical_bytes({"sheet_name": sheet_name, "spreadsheet_id": spreadsheet_id})
    ).hexdigest()
    if source_id != expected_source_id:
        raise ValueError("flow title catalog and source identity disagree")
    return value


def validate_source_closure(
    *,
    raw_rows: dict[str, object],
    analysis: dict[str, object],
    catalog_value: object,
    review_value: object,
    mapping: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if set(analysis) != {
        "kind",
        "root_title",
        "role",
        "rows",
        "schema_version",
        "source_id",
    }:
        raise ValueError("source analysis v2 fields are invalid")
    source_id = analysis.get("source_id")
    if not isinstance(source_id, str) or SOURCE_ID.fullmatch(source_id) is None:
        raise ValueError("flow source identity is invalid")
    common = mapping["common"]
    assert isinstance(common, dict)
    row_id_column = str(common["row_id"])
    catalog = validate_title_catalog(
        catalog_value, source_id=source_id, row_id_column=row_id_column
    )
    catalog_titles = catalog["titles"]
    assert isinstance(catalog_titles, list)
    analysis_rows = analysis.get("rows")
    if not isinstance(analysis_rows, list) or not analysis_rows:
        raise ValueError("source analysis rows are required")
    declared_columns = declared_source_columns(mapping)
    common_rows: list[dict[str, object]] = []
    field_projection: list[dict[str, str]] = []
    reference_ids: set[str] = set()

    for row_value in analysis_rows:
        if not isinstance(row_value, dict) or set(row_value) != {
            "change_scope",
            "fields",
            "title",
        }:
            raise ValueError("source analysis v2 row is invalid")
        title = normalize_title(row_value["title"])
        raw_row = raw_rows.get(title)
        if not isinstance(raw_row, dict):
            raise ValueError(f"raw Sheet row is missing: {title}")
        fields = row_value.get("fields")
        if not isinstance(fields, list):
            raise ValueError(f"source analysis fields are invalid: {title}")
        expected_columns = [
            column
            for column in raw_row
            if column in declared_columns and column != row_id_column
        ]
        actual_columns = [
            field.get("column") if isinstance(field, dict) else None for field in fields
        ]
        if actual_columns != expected_columns:
            raise ValueError(f"source analysis does not cover every business column: {title}")
        normalized_markers: list[str] = []
        for field in fields:
            assert isinstance(field, dict)
            if set(field) != {
                "column",
                "dismissals",
                "references",
                "source_sha256",
            }:
                raise ValueError("source analysis field is invalid")
            column = field["column"]
            assert isinstance(column, str)
            source_text = raw_row.get(column)
            if not isinstance(source_text, str):
                raise ValueError(f"raw Sheet field must be a string: {column}")
            source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            if field.get("source_sha256") != source_sha:
                raise ValueError(f"source analysis field hash mismatch: {title}/{column}")
            references = field.get("references")
            dismissals = field.get("dismissals")
            if not isinstance(references, list) or not isinstance(dismissals, list):
                raise ValueError("source references and dismissals must be arrays")
            normalized_references: list[dict[str, object]] = []
            normalized_dismissals: list[dict[str, object]] = []
            for reference in references:
                if not isinstance(reference, dict) or set(reference) != {
                    "end",
                    "quote",
                    "reference_id",
                    "relation_kind",
                    "start",
                    "target_title",
                }:
                    raise ValueError("source relation evidence is invalid")
                reference_id = reference["reference_id"]
                start = reference["start"]
                end = reference["end"]
                quote = reference["quote"]
                target_title = normalize_title(reference["target_title"])
                if (
                    not isinstance(reference_id, str)
                    or not reference_id
                    or reference_id in reference_ids
                    or type(start) is not int
                    or type(end) is not int
                    or start < 0
                    or end <= start
                    or end > len(source_text)
                    or not isinstance(quote, str)
                    or source_text[start:end] != quote
                    or target_title not in catalog_titles
                    or reference.get("relation_kind")
                    not in {"navigation", "modal", "component", "data", "reference"}
                ):
                    raise ValueError("source relation evidence is invalid")
                reference_ids.add(reference_id)
                normalized_references.append(reference)
                normalized_markers.append(f"→「{target_title}」")
            for dismissal in dismissals:
                if not isinstance(dismissal, dict) or set(dismissal) != {
                    "candidate_title",
                    "end",
                    "quote",
                    "rationale",
                    "start",
                }:
                    raise ValueError("source title dismissal is invalid")
                start = dismissal["start"]
                end = dismissal["end"]
                quote = dismissal["quote"]
                candidate_title = normalize_title(dismissal["candidate_title"])
                rationale = dismissal["rationale"]
                if (
                    type(start) is not int
                    or type(end) is not int
                    or start < 0
                    or end <= start
                    or end > len(source_text)
                    or not isinstance(quote, str)
                    or source_text[start:end] != quote
                    or candidate_title not in catalog_titles
                    or not isinstance(rationale, str)
                    or not rationale.strip()
                ):
                    raise ValueError("source title dismissal is invalid")
                normalized_dismissals.append(dismissal)
            for candidate_title in catalog_titles:
                if candidate_title == title:
                    continue
                occurrence = source_text.find(candidate_title)
                while occurrence >= 0:
                    occurrence_end = occurrence + len(candidate_title)
                    resolved = any(
                        ref["target_title"] == candidate_title
                        and ref["start"] <= occurrence
                        and ref["end"] >= occurrence_end
                        for ref in normalized_references
                    ) or any(
                        dismissal["candidate_title"] == candidate_title
                        and dismissal["start"] <= occurrence
                        and dismissal["end"] >= occurrence_end
                        for dismissal in normalized_dismissals
                    )
                    if not resolved:
                        raise ValueError(
                            f"unresolved title mention: {title}/{column}/{candidate_title}"
                        )
                    occurrence = source_text.find(candidate_title, occurrence + 1)
            field_projection.append(
                {"title": title, "column": column, "source_sha256": source_sha}
            )
        common_rows.append(
            {
                "title": title,
                "change_scope": row_value["change_scope"],
                "normalized_interaction": " ".join(normalized_markers),
            }
        )

    if not isinstance(review_value, dict) or set(review_value) != {
        "analysis_sha256",
        "cross_review",
        "decision",
        "field_reviews",
        "kind",
        "schema_version",
        "title_catalog_digest",
    }:
        raise ValueError("source closure review is invalid")
    analysis_sha = hashlib.sha256(canonical_bytes(analysis)).hexdigest()
    if (
        review_value.get("kind") != "iole.source-closure-review.v1"
        or review_value.get("schema_version") != 1
        or review_value.get("analysis_sha256") != analysis_sha
        or review_value.get("title_catalog_digest") != catalog.get("catalog_digest")
        or review_value.get("decision") != "pass"
    ):
        raise ValueError("source closure review is stale or did not pass")
    field_reviews = review_value.get("field_reviews")
    if not isinstance(field_reviews, list) or len(field_reviews) != len(field_projection):
        raise ValueError("source closure review does not cover every business field")
    for expected, actual in zip(field_projection, field_reviews, strict=True):
        if not isinstance(actual, dict) or set(actual) != {
            "all_dependencies_identified",
            "column",
            "dismissals_correct",
            "evidence",
            "issues",
            "reference_targets_correct",
            "source_sha256",
            "title",
        }:
            raise ValueError("source closure field review is invalid")
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("source closure field review targets another field")
        evidence = actual.get("evidence")
        if (
            actual.get("all_dependencies_identified") is not True
            or actual.get("reference_targets_correct") is not True
            or actual.get("dismissals_correct") is not True
            or not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(item, str) or not item.strip() for item in evidence)
            or actual.get("issues") != []
        ):
            raise ValueError("source closure field review did not pass")
    cross = review_value.get("cross_review")
    if not isinstance(cross, dict) or set(cross) != {
        "every_business_field_reviewed",
        "evidence",
        "issues",
        "no_ambiguous_target",
        "no_unresolved_reference",
    }:
        raise ValueError("source closure cross review is invalid")
    cross_evidence = cross.get("evidence")
    if (
        cross.get("every_business_field_reviewed") is not True
        or cross.get("no_unresolved_reference") is not True
        or cross.get("no_ambiguous_target") is not True
        or not isinstance(cross_evidence, list)
        or not cross_evidence
        or any(not isinstance(item, str) or not item.strip() for item in cross_evidence)
        or cross.get("issues") != []
    ):
        raise ValueError("source closure cross review did not pass")
    closure = {
        "title_catalog": catalog,
        "analysis": analysis,
        "review": review_value,
        "analysis_sha256": analysis_sha,
        "review_sha256": hashlib.sha256(canonical_bytes(review_value)).hexdigest(),
    }
    closure["closure_digest"] = hashlib.sha256(canonical_bytes(closure)).hexdigest()
    return common_rows, closure


def source_bundle_digest(bundle: dict[str, object]) -> str:
    payload = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def build_source_bundle(
    raw_rows_path: Path,
    analysis_path: Path,
    mapping_path: Path,
    title_catalog_path: Path | None = None,
    closure_review_path: Path | None = None,
) -> dict[str, object]:
    raw_rows = load_input_document(raw_rows_path, "raw Sheet rows")
    analysis = load_input_document(analysis_path, "source analysis")
    mapping = load_mapping_v2(mapping_path)
    analysis_version = (analysis.get("kind"), analysis.get("schema_version"))
    source_closure: dict[str, object] | None = None
    if analysis_version == ("iole.source-analysis-input.v2", 2):
        if title_catalog_path is None or closure_review_path is None:
            raise ValueError("source analysis v2 requires title catalog and closure review")
        title_catalog_value = load_input_document(
            title_catalog_path, "flow title catalog"
        )
        closure_review_value = load_input_document(
            closure_review_path, "source closure review"
        )
        analysis_rows, source_closure = validate_source_closure(
            raw_rows=raw_rows,
            analysis=analysis,
            catalog_value=title_catalog_value,
            review_value=closure_review_value,
            mapping=mapping,
        )
    else:
        raise ValueError("source closure requires iole.source-analysis-input.v2")
    source_id = analysis.get("source_id")
    if not isinstance(source_id, str) or SOURCE_ID.fullmatch(source_id) is None:
        raise ValueError("flow source identity is invalid")
    if analysis.get("role") != "client":
        raise ValueError("source analysis role must be client")
    roles = mapping["roles"]
    job_mapping = mapping["job"]
    assert isinstance(roles, dict) and isinstance(job_mapping, dict)
    client = roles["client"]
    assert isinstance(client, dict)
    queue = client["queue"]
    page_mapping = job_mapping["page"]
    assert isinstance(queue, dict) and isinstance(page_mapping, dict)
    ready_status = queue["status_values"]["ready"]

    indexed_raw_rows: dict[str, dict[str, object]] = {}
    for external_title, raw_row in raw_rows.items():
        if not isinstance(external_title, str) or not isinstance(raw_row, dict):
            raise ValueError("raw Sheet rows are invalid")
        exact_title = resolve_exact_source(raw_row, page_mapping["title"], "title")
        title = normalize_title(exact_title)
        if normalize_title(external_title) != title or title in indexed_raw_rows:
            raise ValueError("raw Sheet row identity is invalid")
        indexed_raw_rows[title] = raw_row

    first_raw_row = next(iter(indexed_raw_rows.values()), None)
    if first_raw_row is None:
        raise ValueError("raw Sheet rows are required")
    row_data_columns = handoff_columns_for_raw_row(first_raw_row, mapping)
    for title, raw_row in indexed_raw_rows.items():
        if handoff_columns_for_raw_row(raw_row, mapping) != row_data_columns:
            raise ValueError(f"declared handoff columns differ between rows: {title}")

    members: list[dict[str, object]] = []
    member_titles: set[str] = set()
    normalized_by_title: dict[str, str] = {}
    for row_value in analysis_rows:
        if not isinstance(row_value, dict) or set(row_value) != {
            "change_scope",
            "normalized_interaction",
            "title",
        }:
            raise ValueError("source analysis row is invalid")
        title = normalize_title(row_value["title"])
        if title in member_titles:
            raise ValueError(f"duplicate page title: {title}")
        member_titles.add(title)
        raw_row = indexed_raw_rows.get(title)
        if raw_row is None:
            raise ValueError(f"raw Sheet row is missing: {title}")
        change_scope = row_value["change_scope"]
        if change_scope not in {"modify", "context", "navigate-only"}:
            raise ValueError("page change scope is invalid")
        normalized_interaction = row_value["normalized_interaction"]
        if not isinstance(normalized_interaction, str):
            raise ValueError("normalized interaction must be a string")
        normalized_by_title[title] = normalized_interaction

        row_data = complete_nullable_row(raw_row, row_data_columns)
        source_contract = nullable_source_contract_from_raw(raw_row, job_mapping)
        raw_queue_status = exact_cell(raw_row, str(queue["status"]), "status")
        queue_status = None if raw_queue_status == "" else raw_queue_status
        mode: str | None = None
        latest_review: dict[str, object] | None = None
        if change_scope == "modify":
            if queue_status != ready_status:
                raise ValueError(f"modify page is not ready: {title}")
            pr_url = exact_cell(raw_row, str(queue["pr_url"]), "pr_url").strip()
            reviews = exact_cell(raw_row, str(queue["reviews"]), "reviews")
            latest_review = parse_latest_review(reviews)
            if pr_url and latest_review is None:
                raise ValueError("an existing PR URL requires a numbered review")
            if pr_url:
                parsed_pr = urlparse(pr_url)
                if parsed_pr.scheme not in {"http", "https"} or not parsed_pr.hostname:
                    raise ValueError(f"page PR URL is invalid: {title}")
            mode = "revise" if latest_review is not None else "implement"

        members.append(
            {
                "title": title,
                "change_scope": change_scope,
                "normalized_interaction": normalized_interaction,
                "queue_status": queue_status,
                "mode": mode,
                "review": latest_review,
                "design_refs": extract_design_refs(source_contract["design_ref"] or ""),
                "row_data": row_data,
                "source_contract": source_contract,
            }
        )

    if set(indexed_raw_rows) != member_titles:
        raise ValueError("raw Sheet rows and source analysis rows do not match")
    root_title = normalize_title(analysis.get("root_title"))
    if root_title not in member_titles:
        raise ValueError("root page is missing")

    relations: list[dict[str, str]] = []
    children: dict[str, list[str]] = {title: [] for title in member_titles}
    for title, normalized_interaction in normalized_by_title.items():
        for reference in parse_references(normalized_interaction):
            target_title = reference["title"]
            if target_title not in member_titles:
                raise ValueError(f"referenced page is missing: {target_title}")
            relation = {"from_title": title, "to_title": target_title}
            if relation not in relations:
                relations.append(relation)
                children[title].append(target_title)

    reachable: set[str] = set()
    pending = [root_title]
    while pending:
        title = pending.pop()
        if title in reachable:
            continue
        reachable.add(title)
        pending.extend(children[title])
    if reachable != member_titles:
        raise ValueError(
            f"source analysis contains unrelated rows: {sorted(member_titles - reachable)}"
        )

    bundle: dict[str, object] = {
        "kind": "iole.flow-source-bundle.v2",
        "schema_version": 2,
        "source_id": source_id,
        "role": "client",
        "root_title": root_title,
        "row_data_columns": row_data_columns,
        "members": members,
        "relations": relations,
        "mapping_digest": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
    }
    if source_closure is not None:
        bundle["source_closure"] = source_closure
    bundle["bundle_digest"] = source_bundle_digest(bundle)
    return bundle


def verify_flow_input_against_raw(
    document: dict[str, object], raw_rows_path: Path, mapping_path: Path
) -> None:
    if document.get("kind") != "iole.flow-plan-input.v3":
        return
    mapping = load_mapping_v2(mapping_path)
    if document.get("mapping_digest") != hashlib.sha256(mapping_path.read_bytes()).hexdigest():
        raise ValueError("flow input mapping digest mismatch")
    raw_rows = load_input_document(raw_rows_path, "raw Sheet rows")
    job_mapping = mapping["job"]
    assert isinstance(job_mapping, dict)
    page_mapping = job_mapping["page"]
    assert isinstance(page_mapping, dict)
    indexed_raw: dict[str, dict[str, object]] = {}
    for external_title, raw_row in raw_rows.items():
        if not isinstance(external_title, str) or not isinstance(raw_row, dict):
            raise ValueError("raw Sheet rows are invalid")
        title = normalize_title(
            resolve_exact_source(raw_row, page_mapping["title"], "title")
        )
        if normalize_title(external_title) != title or title in indexed_raw:
            raise ValueError("raw Sheet row identity is invalid")
        indexed_raw[title] = raw_row
    input_rows = document.get("rows")
    if not isinstance(input_rows, list):
        raise ValueError("flow rows are required")
    input_titles: list[str] = []
    for row in input_rows:
        if not isinstance(row, dict):
            raise ValueError("flow row must be an object")
        title = normalize_title(row.get("title"))
        input_titles.append(title)
        raw_row = indexed_raw.get(title)
        if raw_row is None:
            raise ValueError(f"raw Sheet row is missing: {title}")
        expected = source_contract_from_raw(raw_row, job_mapping)
        if row.get("source_contract") != expected:
            raise ValueError(
                f"flow input source contract does not match raw Sheet: {title}"
            )
    if len(input_titles) != len(set(input_titles)) or set(input_titles) != set(indexed_raw):
        raise ValueError("raw Sheet rows and flow input rows do not match")


def build_schedule_plan(
    excel_url: str,
    role: str,
    interval_minutes: int,
    mr: int,
    project_root: Path,
    mapping_path: Path,
) -> dict[str, object]:
    if interval_minutes <= 0:
        raise ValueError("polling interval must be positive")
    if mr not in {0, 1, 2}:
        raise ValueError("mr must be 0, 1, or 2")
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
        "mr": mr,
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
        "mr": mr,
        "mapping_path": str(mapping_path),
        "worker_skill_name": "icp",
        "worker_skill": ICP_SKILL_PATH,
        "connector_queue": connector_queue,
        "required_connector_operations": FLOW_CONNECTOR_OPERATIONS,
        "rrule": f"FREQ=MINUTELY;INTERVAL={interval_minutes}",
        "prompt": "Use $iole run-once with "
        + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
    }


def build_flow_input(
    raw_rows_path: Path,
    analysis_path: Path,
    mapping_path: Path,
) -> dict[str, object]:
    raw_rows = load_input_document(raw_rows_path, "raw Sheet rows")
    analysis = load_input_document(analysis_path, "flow analysis")
    if (
        analysis.get("kind") != "iole.flow-analysis-input.v1"
        or analysis.get("schema_version") != 1
    ):
        raise ValueError("flow analysis contract version is invalid")
    if not isinstance(analysis.get("source_id"), str) or SOURCE_ID.fullmatch(
        str(analysis["source_id"])
    ) is None:
        raise ValueError("flow source identity is invalid")
    if analysis.get("role") != "client":
        raise ValueError("flow role must be client")
    analysis_rows = analysis.get("rows")
    if not isinstance(analysis_rows, list) or not analysis_rows:
        raise ValueError("flow analysis rows are required")
    if not isinstance(analysis.get("component_plan"), list):
        raise ValueError("component plan must be a list")
    component_analysis = analysis.get("component_analysis")
    if not isinstance(component_analysis, dict):
        raise ValueError("component analysis is required")

    mapping = load_mapping_v2(mapping_path)
    common = mapping["common"]
    roles = mapping["roles"]
    job_mapping = mapping["job"]
    assert isinstance(common, dict) and isinstance(roles, dict) and isinstance(job_mapping, dict)
    client = roles["client"]
    assert isinstance(client, dict)
    queue = client["queue"]
    page_mapping = job_mapping["page"]
    design_source_mapping = job_mapping["design_source"]
    assert isinstance(queue, dict) and isinstance(page_mapping, dict)
    assert isinstance(design_source_mapping, dict)
    status_values = queue["status_values"]
    assert isinstance(status_values, dict)

    indexed_raw_rows: dict[str, dict[str, object]] = {}
    for external_title, raw_row in raw_rows.items():
        if not isinstance(external_title, str) or not isinstance(raw_row, dict):
            raise ValueError("raw Sheet rows are invalid")
        exact_title = resolve_exact_source(raw_row, page_mapping["title"], "title")
        normalized_title = normalize_title(exact_title)
        if normalize_title(external_title) != normalized_title:
            raise ValueError("raw Sheet row key does not match its title")
        if normalized_title in indexed_raw_rows:
            raise ValueError(f"duplicate raw Sheet title: {normalized_title}")
        indexed_raw_rows[normalized_title] = raw_row

    normalized_rows: list[dict[str, object]] = []
    selected_titles: list[str] = []
    for analysis_row in analysis_rows:
        if not isinstance(analysis_row, dict) or set(analysis_row) != {
            "allowed_paths",
            "change_scope",
            "normalized_interaction",
            "title",
        }:
            raise ValueError("flow analysis row is invalid")
        title = normalize_title(analysis_row["title"])
        if title in selected_titles:
            raise ValueError(f"duplicate page title: {title}")
        selected_titles.append(title)
        raw_row = indexed_raw_rows.get(title)
        if raw_row is None:
            raise ValueError(f"raw Sheet row is missing: {title}")
        normalized_interaction = analysis_row["normalized_interaction"]
        if not isinstance(normalized_interaction, str):
            raise ValueError("normalized interaction must be a string")
        if analysis_row["change_scope"] not in {"modify", "navigate-only"}:
            raise ValueError("page change scope is invalid")
        allowed_paths = analysis_row["allowed_paths"]
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

        source_contract = source_contract_from_raw(raw_row, job_mapping)
        exact_title = str(source_contract["title"])
        exact_route = str(source_contract["route"])
        exact_design_ref = str(source_contract["design_ref"])
        requirements = source_contract["requirement_sections"]
        acceptance = source_contract["acceptance_sections"]
        assert isinstance(requirements, list) and isinstance(acceptance, list)

        status = exact_cell(raw_row, str(queue["status"]), "status").strip()
        if status not in status_values.values():
            raise ValueError(f"page status is invalid: {title}")
        pr_url = exact_cell(raw_row, str(queue["pr_url"]), "pr_url").strip()
        reviews = exact_cell(raw_row, str(queue["reviews"]), "reviews")
        latest_review = parse_latest_review(reviews)
        if pr_url and latest_review is None:
            raise ValueError("an existing PR URL requires a numbered review")
        if pr_url:
            parsed_pr = urlparse(pr_url)
            if parsed_pr.scheme not in {"http", "https"} or not parsed_pr.hostname:
                raise ValueError(f"page PR URL is invalid: {title}")

        requirement = "\n".join(
            f"{section['label']}: {section['value']}"
            for section in requirements
            if str(section["value"]).strip()
        )
        acceptance_criteria = [
            f"{section['prefix']}: {section['value']}"
            for section in acceptance
            if str(section["value"]).strip()
        ]
        normalized_rows.append(
            {
                "title": title,
                "status": status,
                "pr_url": pr_url,
                "design_ref": exact_design_ref.strip(),
                "route": exact_route.strip(),
                "interaction": normalized_interaction,
                "change_scope": analysis_row["change_scope"],
                "requirement": requirement,
                "acceptance_criteria": acceptance_criteria,
                "design_source": design_source_mapping["constant"],
                "mode": "revise" if latest_review is not None else "implement",
                "review": latest_review,
                "allowed_paths": allowed_paths,
                "source_contract": source_contract,
            }
        )
    if set(indexed_raw_rows) != set(selected_titles):
        raise ValueError("raw Sheet rows and flow analysis rows do not match")

    return {
        "kind": "iole.flow-plan-input.v3",
        "schema_version": 3,
        "source_id": analysis["source_id"],
        "role": analysis["role"],
        "root_title": normalize_title(analysis.get("root_title")),
        "rows": normalized_rows,
        "component_analysis": component_analysis,
        "component_plan": analysis["component_plan"],
        "mapping_digest": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
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
    input_version = (document.get("kind"), document.get("schema_version"))
    if input_version not in {
        ("iole.flow-plan-input.v2", 2),
        ("iole.flow-plan-input.v3", 3),
    }:
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
    if input_version == ("iole.flow-plan-input.v3", 3):
        mapping_digest = document.get("mapping_digest")
        if not isinstance(mapping_digest, str) or SHA256_HEX.fullmatch(mapping_digest) is None:
            raise ValueError("flow input mapping digest is invalid")
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


def page_member(
    row: dict[str, object], page_id: str, *, lossless: bool
) -> dict[str, object]:
    required_strings = ("title", "route", "design_source", "design_ref")
    if any(not isinstance(row.get(field), str) or not str(row[field]).strip() for field in required_strings):
        raise ValueError("page implementation fields are invalid")
    if not isinstance(row.get("requirement"), str) or (
        not lossless and not str(row["requirement"]).strip()
    ):
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
    member = {
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
    if lossless:
        if not isinstance(row.get("interaction"), str):
            raise ValueError("page interaction is invalid")
        source_contract = validate_source_contract(row.get("source_contract"))
        member["interaction"] = source_contract["interaction"]
        member["source_contract"] = source_contract
    return member


def build_plan(document: dict[str, object]) -> dict[str, object]:
    lossless = (
        document.get("kind") == "iole.flow-plan-input.v3"
        and document.get("schema_version") == 3
    )
    plan_kind = "iole.flow-plan.v3" if lossless else "iole.flow-plan.v2"
    plan_schema_version = 3 if lossless else 2
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
        page_member(rows[title], page_ids[title], lossless=lossless)
        for title in claim_page_titles
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
            "kind": plan_kind,
            "schema_version": plan_schema_version,
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
            "kind": plan_kind,
            "schema_version": plan_schema_version,
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
        "kind": plan_kind,
        "schema_version": plan_schema_version,
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
    plan_version = (plan.get("kind"), plan.get("schema_version"))
    if plan_version not in {
        ("iole.flow-plan.v2", 2),
        ("iole.flow-plan.v3", 3),
    }:
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
    if plan_version == ("iole.flow-plan.v3", 3):
        members = plan["members"]
        if not isinstance(members, list) or any(
            not isinstance(member, dict)
            or member_digests.get(str(member.get("page_id")))
            != hashlib.sha256(canonical_bytes(member)).hexdigest()
            for member in members
        ):
            raise ValueError("flow plan member digest mismatch")
    aggregate_digest = hashlib.sha256(canonical_bytes(member_digests)).hexdigest()
    lossless = plan_version == ("iole.flow-plan.v3", 3)
    return {
        "kind": "icp.external-flow-job.v5" if lossless else "icp.external-flow-job.v3",
        "schema_version": 5 if lossless else 3,
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
    if (plan.get("kind"), plan.get("schema_version")) not in {
        ("iole.flow-plan.v2", 2),
        ("iole.flow-plan.v3", 3),
    }:
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
    mr: int,
    pr_url: str | None,
    icp_result_path: Path | None = None,
) -> dict[str, object]:
    if mr not in {0, 1, 2}:
        raise ValueError("mr must be 0, 1, or 2")
    plan = load_input_document(plan_path, "flow plan")
    if (
        (plan.get("kind"), plan.get("schema_version"))
        not in {("iole.flow-plan.v2", 2), ("iole.flow-plan.v3", 3)}
        or plan.get("decision") != "ready"
    ):
        raise ValueError("flow plan is not ready")
    if (
        (plan.get("kind"), plan.get("schema_version"))
        == ("iole.flow-plan.v3", 3)
        and icp_result_path is None
    ):
        raise ValueError(
            "lossless review writeback requires a verified ICP v2 result"
        )
    if (plan.get("kind"), plan.get("schema_version")) == ("iole.flow-plan.v3", 3):
        assert icp_result_path is not None
        if icp_result_path.is_symlink() or not icp_result_path.is_file():
            raise ValueError("ICP result contract is invalid")
        result = load_input_document(icp_result_path, "ICP result")
        expected_result_keys = {
            "kind",
            "schema_version",
            "job_id",
            "job_digest",
            "flow_id",
            "member_digests",
            "base_revision",
            "project_root",
            "status",
            "changed_files",
            "verification",
            "evidence_manifest",
            "evidence_manifest_digest",
            "implementation_contract_sha256",
            "coverage",
        }
        if set(result) != expected_result_keys or (
            result.get("kind"), result.get("schema_version"), result.get("status")
        ) != ("icp.flow-handoff-result.v2", 2, "ready-for-pr"):
            raise ValueError("ICP result contract is invalid")
        if (
            result.get("flow_id") != plan.get("flow_id")
            or result.get("member_digests") != plan.get("member_digests")
        ):
            raise ValueError("ICP result does not match the claimed flow")
        verification = result.get("verification")
        if (
            not isinstance(verification, dict)
            or set(verification) != {"e2e", "node_tests", "runtime_capture", "visual"}
            or set(verification.values()) != {"passed"}
        ):
            raise ValueError("ICP result verification is incomplete")
        for field in (
            "job_digest",
            "evidence_manifest_digest",
            "implementation_contract_sha256",
        ):
            if not isinstance(result.get(field), str) or SHA256_HEX.fullmatch(
                str(result[field])
            ) is None:
                raise ValueError("ICP result digest is invalid")
        coverage = result.get("coverage")
        if not isinstance(coverage, dict) or set(coverage) != {
            "status",
            "required_clause_ids",
            "covered_clause_ids",
            "worker_evidence_digests",
        }:
            raise ValueError("ICP result acceptance coverage is incomplete")
        required_clause_ids = coverage["required_clause_ids"]
        covered_clause_ids = coverage["covered_clause_ids"]
        if (
            coverage["status"] != "passed"
            or not isinstance(required_clause_ids, list)
            or not required_clause_ids
            or len(required_clause_ids) != len(set(required_clause_ids))
            or covered_clause_ids != required_clause_ids
        ):
            raise ValueError("ICP result acceptance coverage is incomplete")
        worker_digests = coverage["worker_evidence_digests"]
        expected_node_ids = plan.get("execution_order")
        if (
            not isinstance(worker_digests, list)
            or not isinstance(expected_node_ids, list)
            or [item.get("node_id") for item in worker_digests if isinstance(item, dict)]
            != expected_node_ids
            or any(
                not isinstance(item, dict)
                or set(item) != {"node_id", "sha256"}
                or not isinstance(item["sha256"], str)
                or SHA256_HEX.fullmatch(item["sha256"]) is None
                for item in worker_digests
            )
        ):
            raise ValueError("ICP result worker evidence is incomplete")
        project_root = result.get("project_root")
        changed_files = result.get("changed_files")
        if (
            not isinstance(project_root, str)
            or not Path(project_root).is_absolute()
            or not Path(project_root).is_dir()
            or not isinstance(changed_files, list)
            or not changed_files
            or len(changed_files) != len(set(changed_files))
        ):
            raise ValueError("ICP result changed files are invalid")
        resolved_project = Path(project_root).resolve()
        for relative in changed_files:
            if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
                raise ValueError("ICP result changed files are invalid")
            target = Path(project_root) / relative
            try:
                target.resolve(strict=True).relative_to(resolved_project)
            except (OSError, ValueError) as exc:
                raise ValueError("ICP result changed files are invalid") from exc
            if target.is_symlink() or not target.is_file():
                raise ValueError("ICP result changed files are invalid")
        evidence_manifest = result.get("evidence_manifest")
        if not isinstance(evidence_manifest, str) or not Path(evidence_manifest).is_absolute():
            raise ValueError("ICP result evidence manifest is invalid")
        manifest_path = Path(evidence_manifest)
        if (
            manifest_path.is_symlink()
            or not manifest_path.is_file()
            or hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            != result["evidence_manifest_digest"]
        ):
            raise ValueError("ICP result evidence manifest is invalid")
    if (
        not isinstance(lease_token, str)
        or not lease_token
        or any(ord(character) < 32 or ord(character) == 127 for character in lease_token)
    ):
        raise ValueError("flow lease token is invalid")
    if mr == 2:
        if pr_url is None:
            raise ValueError("mr=2 requires a PR URL")
        parsed_pr = urlparse(pr_url)
        if parsed_pr.scheme not in {"http", "https"} or not parsed_pr.hostname:
            raise ValueError("PR URL is invalid")
    elif pr_url is not None:
        raise ValueError("PR URL is allowed only when mr=2")
    members = plan.get("claim_page_titles")
    member_digests = plan.get("member_digests")
    if not isinstance(members, list) or not members or not isinstance(member_digests, dict):
        raise ValueError("flow plan members are invalid")
    return {
        "kind": "iole.flow-review-writeback-intent.v2",
        "schema_version": 2,
        "mr": mr,
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
        (plan.get("kind"), plan.get("schema_version"))
        not in {("iole.flow-plan.v2", 2), ("iole.flow-plan.v3", 3)}
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
    schedule_parser.add_argument("--mr", type=int, default=0)
    schedule_parser.add_argument("--project-root", required=True, type=Path)
    schedule_parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    input_parser = subparsers.add_parser("build-input")
    input_parser.add_argument("--raw-rows", required=True, type=Path)
    input_parser.add_argument("--analysis", required=True, type=Path)
    input_parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    source_bundle_parser = subparsers.add_parser("build-source-bundle")
    source_bundle_parser.add_argument("--raw-rows", required=True, type=Path)
    source_bundle_parser.add_argument("--title-catalog", type=Path)
    source_bundle_parser.add_argument("--analysis", required=True, type=Path)
    source_bundle_parser.add_argument("--closure-review", type=Path)
    source_bundle_parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    plan_parser = subparsers.add_parser("build-plan")
    plan_parser.add_argument("--input", required=True, type=Path)
    plan_parser.add_argument("--raw-rows", type=Path)
    plan_parser.add_argument("--mapping", type=Path)
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
    writeback_parser.add_argument("--mr", type=int, default=0)
    writeback_parser.add_argument("--pr-url")
    writeback_parser.add_argument("--icp-result", type=Path)
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
                arguments.mr,
                arguments.project_root,
                arguments.mapping,
            )
        elif arguments.command == "build-input":
            result = build_flow_input(
                arguments.raw_rows,
                arguments.analysis,
                arguments.mapping,
            )
        elif arguments.command == "build-source-bundle":
            result = build_source_bundle(
                arguments.raw_rows,
                arguments.analysis,
                arguments.mapping,
                arguments.title_catalog,
                arguments.closure_review,
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
                arguments.mr,
                arguments.pr_url,
                arguments.icp_result,
            )
        elif arguments.command == "build-error-writeback":
            result = build_error_writeback(
                arguments.plan,
                arguments.lease_token,
                arguments.error_code,
            )
        elif arguments.command == "build-plan":
            flow_input = load_input(arguments.input)
            if flow_input.get("kind") == "iole.flow-plan-input.v3":
                if arguments.raw_rows is None or arguments.mapping is None:
                    raise ValueError(
                        "lossless build-plan requires raw Sheet rows and mapping"
                    )
                verify_flow_input_against_raw(
                    flow_input, arguments.raw_rows, arguments.mapping
                )
            result = build_plan(flow_input)
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
