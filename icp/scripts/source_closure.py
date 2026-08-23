"""Shared fail-closed validation for IOLE source-bundle closure evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any


class SourceClosureError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceClosureError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SourceClosureError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceClosureError(f"{label} must be a non-empty string")
    return value


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise SourceClosureError(f"{label} fields are invalid")


def _validate_source_contract_columns(member: dict[str, Any], title: str) -> None:
    row_data = _object(member.get("row_data"), f"row_data for {title}")
    contract = _object(member.get("source_contract"), f"source contract for {title}")
    columns = _object(contract.get("source_columns"), f"source columns for {title}")
    _exact(
        columns,
        {
            "title",
            "route",
            "design_ref",
            "interaction",
            "requirement_sections",
            "acceptance_sections",
        },
        f"source columns for {title}",
    )
    for field in ("title", "route", "design_ref", "interaction"):
        column = _text(columns.get(field), f"{field} source column")
        if column not in row_data or row_data[column] != contract.get(field):
            raise SourceClosureError(f"source contract column mismatch for {title}")
    for field, label_key in (
        ("requirement_sections", "label"),
        ("acceptance_sections", "prefix"),
    ):
        sections = _array(contract.get(field), f"{field} for {title}")
        sources = _array(columns.get(field), f"{field} sources for {title}")
        if len(sections) != len(sources):
            raise SourceClosureError(f"source contract column mismatch for {title}")
        for section_value, source_value in zip(sections, sources, strict=True):
            section = _object(section_value, f"{field} section")
            source = _object(source_value, f"{field} source")
            column = source.get("source")
            if (
                source.get(label_key) != section.get(label_key)
                or not isinstance(column, str)
                or column not in row_data
                or row_data[column] != section.get("value")
            ):
                raise SourceClosureError(f"source contract column mismatch for {title}")


def validate_source_closure(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete IOLE analysis/review proof against frozen row_data."""

    members = _array(bundle.get("members"), "IOLE members")
    relations = _array(bundle.get("relations"), "IOLE relations")
    closure = _object(bundle.get("source_closure"), "IOLE source closure")
    _exact(
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
    if closure.get("closure_digest") != _digest(
        {key: value for key, value in closure.items() if key != "closure_digest"}
    ):
        raise SourceClosureError("IOLE source closure digest mismatch")

    catalog = _object(closure.get("title_catalog"), "IOLE title catalog")
    _exact(
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
    titles = [_text(value, "IOLE catalog title") for value in _array(catalog.get("titles"), "IOLE catalog titles")]
    if (
        len(titles) != len(set(titles))
        or catalog.get("kind") != "icps.flow-title-catalog.v1"
        or catalog.get("schema_version") != 1
        or catalog.get("row_id_column") != "标题"
        or catalog.get("catalog_digest")
        != _digest(
            {
                "spreadsheet_id": catalog.get("spreadsheet_id"),
                "sheet_name": catalog.get("sheet_name"),
                "row_id_column": catalog.get("row_id_column"),
                "titles": catalog.get("titles"),
            }
        )
    ):
        raise SourceClosureError("IOLE title catalog is invalid")
    expected_source_id = "google-sheets:" + _digest(
        {
            "sheet_name": catalog.get("sheet_name"),
            "spreadsheet_id": catalog.get("spreadsheet_id"),
        }
    )
    if bundle.get("source_id") != expected_source_id:
        raise SourceClosureError("IOLE source closure identity mismatch")

    members_by_title: dict[str, dict[str, Any]] = {}
    for value in members:
        member = _object(value, "IOLE member")
        title = _text(member.get("title"), "IOLE member title")
        if title in members_by_title:
            raise SourceClosureError("IOLE source closure has duplicate members")
        _validate_source_contract_columns(member, title)
        members_by_title[title] = member

    analysis = _object(closure.get("analysis"), "IOLE source analysis")
    _exact(
        analysis,
        {"kind", "root_title", "role", "rows", "schema_version", "source_id"},
        "IOLE source analysis",
    )
    analysis_sha = _digest(analysis)
    if (
        analysis.get("kind") != "iole.source-analysis-input.v2"
        or analysis.get("schema_version") != 2
        or analysis.get("source_id") != bundle.get("source_id")
        or analysis.get("role") != bundle.get("role")
        or analysis.get("root_title") != bundle.get("root_title")
        or closure.get("analysis_sha256") != analysis_sha
    ):
        raise SourceClosureError("IOLE source analysis is stale")

    analyzed_titles: set[str] = set()
    field_projection: list[tuple[str, str, str]] = []
    projected_edges: set[tuple[str, str]] = set()
    reference_ids: set[str] = set()
    for row_value in _array(analysis.get("rows"), "IOLE source analysis rows"):
        row = _object(row_value, "IOLE source analysis row")
        _exact(row, {"change_scope", "fields", "title"}, "IOLE source analysis row")
        title = _text(row.get("title"), "IOLE source analysis title")
        member = members_by_title.get(title)
        if member is None or title in analyzed_titles or row.get("change_scope") != member.get("change_scope"):
            raise SourceClosureError(f"IOLE source analysis member mismatch: {title}")
        analyzed_titles.add(title)
        row_data = _object(member.get("row_data"), f"row_data for {title}")
        expected_columns = set(row_data) - {str(catalog["row_id_column"])}
        fields = _array(row.get("fields"), "IOLE source fields")
        actual_columns = [
            _text(
                _object(field_value, "IOLE source field").get("column"),
                "IOLE source column",
            )
            for field_value in fields
        ]
        column_counts = Counter(actual_columns)
        duplicate_columns = sorted(
            column for column, count in column_counts.items() if count > 1
        )
        missing_columns = sorted(expected_columns - set(actual_columns))
        unexpected_columns = sorted(set(actual_columns) - expected_columns)
        if duplicate_columns or missing_columns or unexpected_columns:
            problem = (
                "IOLE source analysis does not cover every declared source column"
                if missing_columns and not duplicate_columns and not unexpected_columns
                else "IOLE source analysis column mismatch"
            )
            raise SourceClosureError(
                f"{problem}: {title}; "
                f"duplicates={duplicate_columns}; missing={missing_columns}; "
                f"unexpected={unexpected_columns}"
            )
        seen_columns: set[str] = set()
        for field_value in fields:
            field = _object(field_value, "IOLE source field")
            _exact(
                field,
                {"column", "dismissals", "references", "source_sha256"},
                "IOLE source field",
            )
            column = _text(field.get("column"), "IOLE source column")
            seen_columns.add(column)
            raw_value = row_data[column]
            if raw_value is not None and not isinstance(raw_value, str):
                raise SourceClosureError("IOLE row_data value is invalid")
            source_text = raw_value or ""
            source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            if field.get("source_sha256") != source_sha:
                raise SourceClosureError(f"IOLE source analysis field hash mismatch: {title}/{column}")
            field_projection.append((title, column, source_sha))
            for reference_value in _array(field.get("references"), "IOLE source references"):
                reference = _object(reference_value, "IOLE source reference")
                _exact(
                    reference,
                    {"end", "quote", "reference_id", "relation_kind", "start", "target_title"},
                    "IOLE source reference",
                )
                reference_id = _text(reference.get("reference_id"), "IOLE source reference id")
                start = reference.get("start")
                end = reference.get("end")
                target = reference.get("target_title")
                if (
                    reference_id in reference_ids
                    or type(start) is not int
                    or type(end) is not int
                    or start < 0
                    or end <= start
                    or end > len(source_text)
                    or source_text[start:end] != reference.get("quote")
                    or target not in members_by_title
                    or target not in titles
                    or reference.get("relation_kind")
                    not in {"navigation", "modal", "component", "data", "reference"}
                ):
                    raise SourceClosureError("IOLE source reference evidence is invalid")
                reference_ids.add(reference_id)
                projected_edges.add((title, str(target)))
            for dismissal_value in _array(field.get("dismissals"), "IOLE source dismissals"):
                dismissal = _object(dismissal_value, "IOLE source dismissal")
                start = dismissal.get("start")
                end = dismissal.get("end")
                if (
                    set(dismissal) != {"candidate_title", "end", "quote", "rationale", "start"}
                    or type(start) is not int
                    or type(end) is not int
                    or start < 0
                    or end <= start
                    or end > len(source_text)
                    or source_text[start:end] != dismissal.get("quote")
                    or dismissal.get("candidate_title") not in titles
                    or not isinstance(dismissal.get("rationale"), str)
                    or not dismissal["rationale"].strip()
                ):
                    raise SourceClosureError("IOLE source dismissal evidence is invalid")
        if seen_columns != expected_columns:
            raise SourceClosureError(
                f"IOLE source analysis does not cover every declared source column: {title}"
            )
    if analyzed_titles != set(members_by_title):
        raise SourceClosureError("IOLE source closure does not cover every member")

    flow_edges: list[tuple[str, str]] = []
    for value in relations:
        relation = _object(value, "IOLE relation")
        _exact(relation, {"from_title", "to_title"}, "IOLE relation")
        flow_edges.append(
            (
                _text(relation.get("from_title"), "IOLE relation source"),
                _text(relation.get("to_title"), "IOLE relation target"),
            )
        )
    flow_edge_counts = Counter(flow_edges)
    duplicate_edges = sorted(
        edge for edge, count in flow_edge_counts.items() if count > 1
    )
    if duplicate_edges:
        raise SourceClosureError(f"IOLE source closure has duplicate relation: {duplicate_edges}")
    missing_edges = sorted(projected_edges - set(flow_edges))
    unexpected_edges = sorted(set(flow_edges) - projected_edges)
    if missing_edges or unexpected_edges:
        raise SourceClosureError(
            "IOLE source closure relation projection mismatch; "
            f"missing={missing_edges} unexpected={unexpected_edges}"
        )

    review = _object(closure.get("review"), "IOLE source closure review")
    _exact(
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
        closure.get("review_sha256") != _digest(review)
        or review.get("kind") != "iole.source-closure-review.v1"
        or review.get("schema_version") != 1
        or review.get("analysis_sha256") != analysis_sha
        or review.get("title_catalog_digest") != catalog.get("catalog_digest")
        or review.get("decision") != "pass"
    ):
        raise SourceClosureError("IOLE source closure review did not pass")
    review_projection: list[tuple[str, str, str]] = []
    for value in _array(review.get("field_reviews"), "IOLE source field reviews"):
        field_review = _object(value, "IOLE source field review")
        _exact(
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
            or _array(field_review.get("issues"), "IOLE source field review issues")
            or not _array(field_review.get("evidence"), "IOLE source field review evidence")
        ):
            raise SourceClosureError("IOLE source field review failed")
        review_projection.append(
            (
                _text(field_review.get("title"), "review title"),
                _text(field_review.get("column"), "review column"),
                _text(field_review.get("source_sha256"), "review source hash"),
            )
        )
    review_counts = Counter(review_projection)
    duplicate_reviews = sorted(
        item for item, count in review_counts.items() if count > 1
    )
    missing_reviews = sorted(set(field_projection) - set(review_projection))
    unexpected_reviews = sorted(set(review_projection) - set(field_projection))
    if duplicate_reviews or missing_reviews or unexpected_reviews:
        raise SourceClosureError(
            "IOLE source field review projection mismatch; "
            f"duplicates={duplicate_reviews}; missing={missing_reviews}; "
            f"unexpected={unexpected_reviews}"
        )
    cross = _object(review.get("cross_review"), "IOLE cross review")
    _exact(
        cross,
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
        cross.get("every_business_field_reviewed") is not True
        or cross.get("no_unresolved_reference") is not True
        or cross.get("no_ambiguous_target") is not True
        or _array(cross.get("issues"), "IOLE cross review issues")
        or not _array(cross.get("evidence"), "IOLE cross review evidence")
    ):
        raise SourceClosureError("IOLE source cross review failed")
    return copy.deepcopy(closure)
