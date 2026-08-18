#!/usr/bin/env python3
"""Deterministic gates for the ICP extract stage."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from lanhu import (
    LanhuError,
    artboard_size,
    asset_file_name,
    collect_export_assets,
    parse_lanhu_url,
    png_size,
    reference_logical_scale,
)


class ContractError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError("missing_input", f"file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json", f"invalid JSON at {path}: {exc}") from exc


def write_json(path: Path, value: object) -> None:
    path.write_bytes(json_bytes(value))


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(json_bytes(value))
    os.replace(temp_path, path)


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ContractError("missing_input", f"{label} is not a file: {path}")


def design_root(source: dict[str, Any]) -> dict[str, Any]:
    figma_json = source.get("figma_json")
    if not isinstance(figma_json, dict):
        raise ContractError("invalid_source", "source JSON must contain object figma_json")
    artboard = figma_json.get("artboard")
    if not isinstance(artboard, dict):
        raise ContractError("invalid_source", "source JSON must contain figma_json.artboard")
    return artboard


def normalize_source(source: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    root = design_root(source)
    nodes: dict[str, dict[str, Any]] = {}
    node_order: list[str] = []

    def visit(node: dict[str, Any], parent_id: str | None, source_path: list[object]) -> str:
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ContractError(
                "invalid_source_node",
                f"source node at {source_path!r} must have a non-empty string id",
            )
        if node_id in nodes:
            raise ContractError("duplicate_source_id", f"duplicate source node id: {node_id}")

        layers_kind = (
            "missing"
            if "layers" not in node
            else "null"
            if node.get("layers") is None
            else "array"
        )
        raw_children = node.get("layers", [])
        if raw_children is None:
            raw_children = []
        if not isinstance(raw_children, list) or any(
            not isinstance(child, dict) for child in raw_children
        ):
            raise ContractError(
                "invalid_source_node", f"layers must be an array of objects for node {node_id}"
            )

        payload = copy.deepcopy(node)
        payload.pop("layers", None)
        record: dict[str, Any] = {
            "id": node_id,
            "parent_id": parent_id,
            "child_ids": [],
            "source_path": source_path,
            "layers_kind": layers_kind,
            "payload": payload,
        }
        nodes[node_id] = record
        node_order.append(node_id)

        child_ids: list[str] = []
        for index, child in enumerate(raw_children):
            child_ids.append(
                visit(child, node_id, [*source_path, "layers", index])
            )
        record["child_ids"] = child_ids
        return node_id

    root_id = visit(root, None, ["figma_json", "artboard"])
    return {
        "schema": "icp.extract.source-facts.v1",
        "source_sha256": source_sha256,
        "root_node_id": root_id,
        "node_order": node_order,
        "nodes": nodes,
    }


def identity(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError("invalid_source", f"source JSON must contain non-empty {key}")
    return value


def safe_design_name(value: str) -> str:
    result = value
    for character in ("/", "\\", ":", "\0"):
        result = result.replace(character, "-")
    result = "".join(character for character in result if ord(character) >= 32).strip()
    if not result or result in {".", ".."}:
        raise ContractError("invalid_design_name", f"design name cannot form a safe directory: {value!r}")
    return result


def parsed_design_identity(url: str) -> dict[str, str]:
    try:
        return parse_lanhu_url(url)
    except LanhuError as exc:
        raise ContractError(exc.code, exc.message) from exc


def initial_batch_index(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest_sha = sha256_bytes(json_bytes(manifest))
    return {
        "schema": "icp.extract.index.v1",
        "run_manifest_sha256": manifest_sha,
        "designs": [
            {
                **item,
                "design_name": None,
                "design_dir": None,
                "design_id": None,
                "version_id": None,
                "state": "awaiting_prepare",
                "source_manifest_sha256": None,
                "stage_result_sha256": None,
            }
            for item in manifest["designs"]
        ],
    }


def begin_run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        raise ContractError("missing_project", f"project root is not a directory: {project_root}")
    run_input = read_json(Path(args.urls_file).resolve())
    if not isinstance(run_input, dict):
        raise ContractError("invalid_run_input", "run input must be an object")
    if run_input.get("schema") == "icp.extract.run-input.v1":
        if set(run_input) != {"schema", "design_urls"}:
            raise ContractError("invalid_run_input", "v1 run input requires schema and design_urls")
        urls = run_input.get("design_urls")
        if (
            not isinstance(urls, list)
            or not urls
            or any(not isinstance(url, str) or not url for url in urls)
            or len(urls) != len(set(urls))
        ):
            raise ContractError(
                "invalid_run_input",
                "design_urls must be a non-empty unique string array",
            )
        requested_designs = [
            {"design_url": url, "ui_supplement": None} for url in urls
        ]
    elif run_input.get("schema") == "icp.extract.run-input.v2":
        if set(run_input) != {"schema", "designs"}:
            raise ContractError("invalid_run_input", "v2 run input requires schema and designs")
        requested_designs = run_input.get("designs")
        if not isinstance(requested_designs, list) or not requested_designs:
            raise ContractError("invalid_run_input", "designs must be a non-empty array")
        normalized_designs: list[dict[str, Any]] = []
        for index, item in enumerate(requested_designs):
            if not isinstance(item, dict) or set(item) != {
                "design_url",
                "ui_supplement",
            }:
                raise ContractError(
                    "invalid_run_input",
                    f"designs[{index}] requires design_url and ui_supplement",
                )
            url = item.get("design_url")
            ui_supplement = item.get("ui_supplement")
            if not isinstance(url, str) or not url:
                raise ContractError(
                    "invalid_run_input", f"designs[{index}].design_url is invalid"
                )
            if ui_supplement is not None and not isinstance(ui_supplement, str):
                raise ContractError(
                    "invalid_run_input",
                    f"designs[{index}].ui_supplement must be a string or null",
                )
            normalized_designs.append(
                {"design_url": url, "ui_supplement": ui_supplement}
            )
        requested_designs = normalized_designs
        urls = [item["design_url"] for item in requested_designs]
        if len(urls) != len(set(urls)):
            raise ContractError("invalid_run_input", "design URLs must be unique")
    else:
        raise ContractError("invalid_run_input", "unsupported run input schema")
    designs = [
        {**item, **parsed_design_identity(item["design_url"])}
        for item in requested_designs
    ]
    manifest = {
        "schema": "icp.extract.run-manifest.v1",
        "run_input_sha256": sha256_bytes(json_bytes(run_input)),
        "design_count": len(designs),
        "designs": designs,
    }
    extract_root = project_root / ".icp" / "extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    manifest_path = extract_root / "run-manifest.json"
    index_path = extract_root / "index.json"
    resumed = False
    if manifest_path.exists():
        existing = read_json(manifest_path)
        if existing != manifest:
            raise ContractError(
                "batch_input_drift", "existing extract batch has a different expected URL set"
            )
        resumed = True
    else:
        atomic_write_json(manifest_path, manifest)
    expected_index = initial_batch_index(manifest)
    if not index_path.exists():
        atomic_write_json(index_path, expected_index)
    else:
        index = read_json(index_path)
        if not isinstance(index, dict) or index.get("run_manifest_sha256") != expected_index[
            "run_manifest_sha256"
        ]:
            raise ContractError("batch_drift", "index does not match run manifest")
    return {
        "ok": True,
        "resumed": resumed,
        "design_count": len(designs),
        "extract_root": str(extract_root),
        "run_manifest": str(manifest_path),
    }


def load_batch(project_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    extract_root = project_root / ".icp" / "extract"
    manifest_path = extract_root / "run-manifest.json"
    index_path = extract_root / "index.json"
    if not manifest_path.exists() and not index_path.exists():
        return None
    manifest = read_json(manifest_path)
    index = read_json(index_path)
    if not isinstance(manifest, dict) or manifest.get("schema") != "icp.extract.run-manifest.v1":
        raise ContractError("batch_drift", "run manifest is invalid")
    manifest_sha = sha256_bytes(json_bytes(manifest))
    if not isinstance(index, dict) or index.get("run_manifest_sha256") != manifest_sha:
        raise ContractError("batch_drift", "index does not bind the run manifest")
    manifest_designs = manifest.get("designs")
    index_designs = index.get("designs")
    if not isinstance(manifest_designs, list) or not isinstance(index_designs, list):
        raise ContractError("batch_drift", "batch design arrays are invalid")
    if [item.get("design_url") for item in manifest_designs] != [
        item.get("design_url") for item in index_designs
    ]:
        raise ContractError("batch_drift", "index URL set differs from run manifest")
    return extract_root, manifest, index


def update_batch_index(
    project_root: Path,
    design_url: str,
    values: dict[str, Any],
) -> None:
    loaded = load_batch(project_root)
    if loaded is None:
        return
    extract_root, _, index = loaded
    matches = [item for item in index["designs"] if item.get("design_url") == design_url]
    if len(matches) != 1:
        raise ContractError("batch_scope_error", f"design URL is not uniquely expected: {design_url}")
    matches[0].update(values)
    atomic_write_json(extract_root / "index.json", index)


def batch_entry_for_prepare(
    project_root: Path,
    design_url: str,
    source: dict[str, Any],
    design_dir_name: str,
) -> dict[str, Any] | None:
    loaded = load_batch(project_root)
    if loaded is None:
        return None
    _, _, index = loaded
    matches = [item for item in index["designs"] if item.get("design_url") == design_url]
    if len(matches) != 1:
        raise ContractError("unexpected_design_url", "design URL is not in the frozen batch")
    entry = matches[0]
    source_identity = source.get("source_identity")
    if not isinstance(source_identity, dict):
        raise ContractError("source_identity_missing", "batch source must contain source_identity")
    for field in ("project_id", "image_id", "team_id"):
        if source_identity.get(field, "") != entry.get(field, ""):
            raise ContractError("source_identity_mismatch", f"source {field} differs from batch")
    for other in index["designs"]:
        if other is not entry and other.get("design_dir") == design_dir_name:
            raise ContractError(
                "design_name_collision",
                f"different batch designs resolve to directory {design_dir_name!r}",
            )
    return entry


def inventory_assets(assets_dir_value: str | None) -> tuple[list[dict[str, Any]], list[tuple[Path, Path]]]:
    if assets_dir_value is None:
        return [], []
    assets_dir = Path(assets_dir_value).resolve()
    if not assets_dir.is_dir():
        raise ContractError("missing_input", f"assets directory does not exist: {assets_dir}")
    records: list[dict[str, Any]] = []
    sources: list[tuple[Path, Path]] = []
    for path in sorted(assets_dir.rglob("*"), key=lambda item: item.relative_to(assets_dir).as_posix()):
        relative = path.relative_to(assets_dir)
        if path.is_symlink():
            raise ContractError("invalid_asset", f"asset symlinks are not allowed: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ContractError("invalid_asset", f"unsupported asset entry: {relative}")
        raw = path.read_bytes()
        records.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256_bytes(raw),
                "size": len(raw),
            }
        )
        sources.append((path, relative))
    return records, sources


def build_asset_index(
    source: dict[str, Any],
    facts: dict[str, Any],
    asset_records: list[dict[str, Any]],
    acquisition_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    figma_json = source.get("figma_json")
    if not isinstance(figma_json, dict):
        raise ContractError("invalid_source", "source JSON must contain object figma_json")
    try:
        expected_references = collect_export_assets(figma_json)
    except LanhuError as exc:
        raise ContractError(exc.code, exc.message) from exc

    grouped: dict[str, list[dict[str, Any]]] = {}
    for reference in expected_references:
        url = reference.get("url")
        if not isinstance(url, str) or not url:
            raise ContractError("invalid_asset_relation", "source asset URL is invalid")
        grouped.setdefault(url, []).append(reference)

    records_by_path = {record.get("path"): record for record in asset_records}
    if len(records_by_path) != len(asset_records):
        raise ContractError("invalid_asset_relation", "local asset paths must be unique")
    acquisition_by_url: dict[str, dict[str, Any]] | None = None
    if acquisition_files is not None:
        acquisition_by_url = {}
        for item in acquisition_files:
            url = item.get("url") if isinstance(item, dict) else None
            if not isinstance(url, str) or not url or url in acquisition_by_url:
                raise ContractError(
                    "invalid_acquisition", "acquisition asset URLs must be unique"
                )
            acquisition_by_url[url] = item
        if set(acquisition_by_url) != set(grouped):
            raise ContractError(
                "acquisition_drift",
                "acquisition assets do not match source export URLs",
            )

    nodes = facts.get("nodes")
    if not isinstance(nodes, dict):
        raise ContractError("invalid_stage", "source-facts nodes must be an object")
    used_names: dict[str, str] = {}
    assets: list[dict[str, Any]] = []
    expected_paths: set[str] = set()
    for url in sorted(grouped):
        file_name = asset_file_name(url, used_names)
        expected_paths.add(file_name)
        local = records_by_path.get(file_name)
        if not isinstance(local, dict):
            raise ContractError(
                "asset_relation_missing",
                f"source asset URL has no exact local file: {url}",
            )
        references = grouped[url]
        formats = {reference.get("format") for reference in references}
        if len(formats) != 1 or next(iter(formats)) not in {"png", "svg"}:
            raise ContractError(
                "invalid_asset_relation", f"source asset format is ambiguous: {url}"
            )
        canonical_references: list[dict[str, str]] = []
        for reference in references:
            node_id = reference.get("layer_id")
            source_field = reference.get("source_field")
            if not isinstance(node_id, str) or node_id not in nodes:
                raise ContractError(
                    "asset_relation_missing", f"asset references unknown source node: {node_id}"
                )
            if source_field not in {"image.imageUrl", "image.svgUrl"}:
                raise ContractError(
                    "invalid_asset_relation", f"asset source field is invalid: {source_field}"
                )
            payload = nodes[node_id].get("payload")
            image = payload.get("image") if isinstance(payload, dict) else None
            field_name = source_field.split(".", 1)[1]
            if not isinstance(image, dict) or image.get(field_name) != url:
                raise ContractError(
                    "asset_relation_missing",
                    f"asset URL is not present at {node_id}.{source_field}",
                )
            canonical_references.append(
                {"source_node_id": node_id, "source_field": source_field}
            )

        if acquisition_by_url is not None:
            acquired = acquisition_by_url[url]
            if (
                acquired.get("path") != f"assets/{file_name}"
                or acquired.get("sha256") != local.get("sha256")
                or acquired.get("size") != local.get("size")
                or acquired.get("references") != references
            ):
                raise ContractError(
                    "acquisition_drift",
                    f"acquisition asset relation differs from source: {url}",
                )

        assets.append(
            {
                "asset_id": f"sha256:{sha256_bytes(url.encode('utf-8'))}",
                "remote_url": url,
                "local_path": f"source/assets/{file_name}",
                "format": next(iter(formats)),
                "sha256": local["sha256"],
                "size": local["size"],
                "source_references": canonical_references,
            }
        )

    if set(records_by_path) != expected_paths:
        raise ContractError(
            "asset_relation_missing",
            "local assets and source export URLs do not form an exact relation",
        )
    return {
        "schema": "icp.extract.asset-index.v1",
        "source_sha256": facts["source_sha256"],
        "source_facts_sha256": sha256_bytes(json_bytes(facts)),
        "assets": assets,
    }


def acquisition_child(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ContractError("invalid_acquisition", f"{label} path must be a non-empty string")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError("invalid_acquisition", f"{label} path escapes acquisition directory")
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ContractError("acquisition_drift", f"{label} file is missing or unsafe: {value}")
    return path


def validate_acquisition(
    acquisition_dir_value: str, design_url: str
) -> tuple[Path, Path, str | None, dict[str, Any], dict[str, Any]]:
    root = Path(acquisition_dir_value).resolve()
    if not root.is_dir():
        raise ContractError("missing_input", f"acquisition directory does not exist: {root}")
    acquisition_path = root / "acquisition.json"
    require_file(acquisition_path, "acquisition manifest")
    acquisition_raw = acquisition_path.read_bytes()
    acquisition = read_json(acquisition_path)
    if (
        not isinstance(acquisition, dict)
        or acquisition.get("schema") != "icp.extract.lanhu-acquisition.v1"
    ):
        raise ContractError("invalid_acquisition", "unsupported acquisition manifest")
    if acquisition.get("design_url") != design_url:
        raise ContractError("design_url_mismatch", "acquisition URL differs from --design-url")

    source_record = acquisition.get("source")
    reference_record = acquisition.get("reference")
    assets_record = acquisition.get("assets")
    identity_record = acquisition.get("identity")
    if not all(
        isinstance(value, dict)
        for value in (source_record, reference_record, assets_record, identity_record)
    ):
        raise ContractError("invalid_acquisition", "acquisition evidence sections are invalid")
    source_path = acquisition_child(root, source_record.get("path"), "source")
    reference_path = acquisition_child(root, reference_record.get("path"), "reference")
    for label, path, record, size_key in (
        ("source", source_path, source_record, "size"),
        ("reference", reference_path, reference_record, "byte_size"),
    ):
        raw = path.read_bytes()
        if record.get("sha256") != sha256_bytes(raw) or record.get(size_key) != len(raw):
            raise ContractError("acquisition_drift", f"{label} bytes differ from acquisition")

    files = assets_record.get("files")
    if not isinstance(files, list) or any(not isinstance(item, dict) for item in files):
        raise ContractError("invalid_acquisition", "acquisition asset files must be objects")
    expected_count = assets_record.get("expected_count")
    if (
        assets_record.get("complete") is not True
        or expected_count != len(files)
        or assets_record.get("downloaded_count") != len(files)
        or assets_record.get("hashed_count") != len(files)
    ):
        raise ContractError("acquisition_incomplete", "acquisition asset counts are incomplete")
    listed_relative: set[str] = set()
    for item in files:
        path = acquisition_child(root, item.get("path"), "asset")
        relative = path.relative_to(root).as_posix()
        if not relative.startswith("assets/") or relative in listed_relative:
            raise ContractError("invalid_acquisition", "asset paths must be unique under assets/")
        listed_relative.add(relative)
        raw = path.read_bytes()
        if item.get("sha256") != sha256_bytes(raw) or item.get("size") != len(raw):
            raise ContractError("acquisition_drift", f"asset bytes differ: {relative}")
    asset_root = root / "assets"
    asset_records, _ = inventory_assets(str(asset_root))
    actual_relative = {f"assets/{item['path']}" for item in asset_records}
    if actual_relative != listed_relative:
        raise ContractError("acquisition_drift", "acquisition asset set differs from manifest")
    return (
        source_path,
        reference_path,
        str(asset_root),
        {
            "acquisition_sha256": sha256_bytes(acquisition_raw),
            "acquisition_identity": identity_record,
            "acquisition_design_name": acquisition.get("design_name"),
        },
        acquisition,
    )


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        raise ContractError("missing_project", f"project root is not a directory: {project_root}")
    acquisition_provenance: dict[str, Any] | None = None
    acquisition_evidence: dict[str, Any] | None = None
    if args.acquisition_dir:
        if args.source_json or args.reference_image or args.assets_dir:
            raise ContractError(
                "invalid_input",
                "--acquisition-dir cannot be combined with loose source/reference/assets inputs",
            )
        (
            source_path,
            reference_path,
            assets_dir_value,
            acquisition_provenance,
            acquisition_evidence,
        ) = (
            validate_acquisition(args.acquisition_dir, args.design_url)
        )
    else:
        if not args.allow_loose_input:
            raise ContractError(
                "unsafe_loose_input",
                "production extract requires --acquisition-dir",
            )
        if not args.source_json or not args.reference_image:
            raise ContractError(
                "invalid_input",
                "provide --acquisition-dir or both --source-json and --reference-image",
            )
        source_path = Path(args.source_json).resolve()
        reference_path = Path(args.reference_image).resolve()
        assets_dir_value = args.assets_dir
    require_file(source_path, "source JSON")
    require_file(reference_path, "reference image")

    source_raw = source_path.read_bytes()
    reference_raw = reference_path.read_bytes()
    asset_records, asset_sources = inventory_assets(assets_dir_value)
    source_sha = sha256_bytes(source_raw)
    reference_sha = sha256_bytes(reference_raw)

    try:
        source = json.loads(source_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("invalid_json", f"invalid source JSON: {exc}") from exc
    if not isinstance(source, dict):
        raise ContractError("invalid_source", "source JSON root must be an object")
    source_design_url = identity(source, "lanhu_url")
    if source_design_url != args.design_url:
        raise ContractError(
            "design_url_mismatch",
            "--design-url does not match the URL frozen inside the source JSON",
        )
    design_name = identity(source, "design_name")
    reference_suffix = reference_path.suffix.lower() or ".bin"
    figma_json = source.get("figma_json")
    if not isinstance(figma_json, dict):
        raise ContractError("invalid_source", "source JSON must contain object figma_json")
    try:
        reference_pixel_size = png_size(reference_raw)
        logical_artboard_size = artboard_size(figma_json)
        logical_scale = reference_logical_scale(
            reference_pixel_size, logical_artboard_size
        )
    except LanhuError as exc:
        raise ContractError(exc.code, exc.message) from exc
    reference_contract = {
        "path": f"source/reference{reference_suffix}",
        "sha256": reference_sha,
        "pixel_size": reference_pixel_size,
        "logical_artboard_size": logical_artboard_size,
        "logical_scale": logical_scale,
    }
    if acquisition_provenance is not None:
        acquisition_identity = acquisition_provenance["acquisition_identity"]
        source_identity = source.get("source_identity")
        if (
            not isinstance(source_identity, dict)
            or any(source_identity.get(field, "") != acquisition_identity.get(field, "") for field in ("project_id", "image_id", "team_id"))
            or identity(source, "design_id") != acquisition_identity.get("design_id")
            or identity(source, "version_id") != acquisition_identity.get("version_id")
            or design_name != acquisition_provenance.get("acquisition_design_name")
        ):
            raise ContractError(
                "acquisition_identity_mismatch",
                "design JSON identity differs from acquisition evidence",
            )
        acquisition_reference = acquisition_evidence.get("reference") if acquisition_evidence else None
        if (
            not isinstance(acquisition_reference, dict)
            or acquisition_reference.get("size") != reference_pixel_size
            or acquisition_reference.get("logical_scale") != logical_scale
            or acquisition_evidence.get("artboard_size") != logical_artboard_size
        ):
            raise ContractError(
                "acquisition_drift",
                "reference coordinate mapping differs from acquisition evidence",
            )
    design_dir_name = safe_design_name(design_name)
    extract_root = project_root / ".icp" / "extract"
    stage_dir = extract_root / design_dir_name
    batch_entry = batch_entry_for_prepare(
        project_root, args.design_url, source, design_dir_name
    )
    ui_supplement = (
        batch_entry.get("ui_supplement") if batch_entry is not None else None
    )
    if ui_supplement is not None and not isinstance(ui_supplement, str):
        raise ContractError(
            "batch_drift", "frozen UI supplement must be a string or null"
        )
    semantic_context = {
        "schema": "icp.extract.semantic-context.v1",
        "design_url": args.design_url,
        "ui_supplement": ui_supplement,
    }
    semantic_context_raw = json_bytes(semantic_context)
    semantic_context_sha = sha256_bytes(semantic_context_raw)

    if stage_dir.exists():
        manifest_path = stage_dir / "source-manifest.json"
        manifest = read_json(manifest_path)
        if isinstance(manifest, dict) and (
            manifest.get("design_id") != source.get("design_id")
            or manifest.get("design_url") != args.design_url
        ):
            raise ContractError(
                "design_name_collision",
                f"directory {design_dir_name!r} already belongs to another design",
            )
        expected = {
            "source_sha256": source_sha,
            "reference": reference_contract,
            "design_url": args.design_url,
            "assets": asset_records,
            "semantic_context_sha256": semantic_context_sha,
        }
        if acquisition_provenance is not None:
            expected.update(acquisition_provenance)
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != value for key, value in expected.items()
        ):
            raise ContractError(
                "input_drift",
                "existing .icp/extract input differs; preserve it and start a deliberate new run",
            )
        state = read_json(stage_dir / "state.json")
        if not isinstance(state, dict):
            raise ContractError("invalid_stage", "state.json must contain an object")
        verify_frozen_sources(stage_dir, state)
        update_batch_index(
            project_root,
            args.design_url,
            {
                "design_name": design_name,
                "design_dir": design_dir_name,
                "design_id": identity(source, "design_id"),
                "version_id": identity(source, "version_id"),
                "state": state["state"],
                "source_manifest_sha256": state["source_manifest_sha256"],
                "stage_result_sha256": state.get("stage_result_sha256"),
            },
        )
        return {
            "ok": True,
            "resumed": True,
            "design_name": design_name,
            "stage_dir": str(stage_dir),
        }

    facts = normalize_source(source, source_sha)
    facts_raw = json_bytes(facts)
    acquisition_files = None
    if acquisition_evidence is not None:
        acquisition_assets = acquisition_evidence.get("assets")
        acquisition_files = (
            acquisition_assets.get("files")
            if isinstance(acquisition_assets, dict)
            else None
        )
        if not isinstance(acquisition_files, list):
            raise ContractError("invalid_acquisition", "acquisition asset files are missing")
    asset_index = build_asset_index(
        source,
        facts,
        asset_records,
        acquisition_files,
    )
    asset_index_raw = json_bytes(asset_index)
    manifest = {
        "schema": "icp.extract.source-manifest.v1",
        "design_url": args.design_url,
        "design_name": design_name,
        "design_dir": design_dir_name,
        "design_id": identity(source, "design_id"),
        "version_id": identity(source, "version_id"),
        "source_identity": source.get("source_identity"),
        "root_node_id": facts["root_node_id"],
        "source_node_count": len(facts["node_order"]),
        "source_sha256": source_sha,
        "source_facts_sha256": sha256_bytes(facts_raw),
        "source_file": "source/design.json",
        "reference": reference_contract,
        "assets": asset_records,
        "asset_index_file": "asset-index.json",
        "asset_index_sha256": sha256_bytes(asset_index_raw),
        "semantic_context_file": "semantic-context.json",
        "semantic_context_sha256": semantic_context_sha,
    }
    if acquisition_provenance is not None:
        manifest.update(acquisition_provenance)
    state = {
        "schema": "icp.extract.state.v1",
        "state": "awaiting_semantic_draft",
        "revision": 0,
        "source_manifest_sha256": sha256_bytes(json_bytes(manifest)),
        "semantic_context_sha256": semantic_context_sha,
    }

    extract_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=extract_root) as temp_name:
        temp_stage = Path(temp_name)
        (temp_stage / "source").mkdir()
        (temp_stage / "source" / "design.json").write_bytes(source_raw)
        (temp_stage / "source" / f"reference{reference_suffix}").write_bytes(reference_raw)
        for asset_source, relative in asset_sources:
            asset_target = temp_stage / "source" / "assets" / relative
            asset_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset_source, asset_target)
        (temp_stage / "source-facts.json").write_bytes(facts_raw)
        (temp_stage / "asset-index.json").write_bytes(asset_index_raw)
        (temp_stage / "semantic-context.json").write_bytes(semantic_context_raw)
        write_json(
            temp_stage / "semantic-authoring.input.json",
            {
                "schema": "icp.extract.semantic-authoring-input.v1",
                "source_manifest_sha256": state["source_manifest_sha256"],
                "reference": copy.deepcopy(reference_contract),
                "ui_supplement": ui_supplement,
                "instruction": (
                    "Use the UI supplement only to inform visual-semantic Block "
                    "boundaries; preserve all exact design facts from the frozen source."
                ),
            },
        )
        write_json(temp_stage / "source-manifest.json", manifest)
        write_json(temp_stage / "state.json", state)
        os.replace(temp_stage, stage_dir)

    update_batch_index(
        project_root,
        args.design_url,
        {
            "design_name": design_name,
            "design_dir": design_dir_name,
            "design_id": manifest["design_id"],
            "version_id": manifest["version_id"],
            "state": state["state"],
            "source_manifest_sha256": state["source_manifest_sha256"],
            "stage_result_sha256": None,
        },
    )

    return {
        "ok": True,
        "resumed": False,
        "design_name": design_name,
        "stage_dir": str(stage_dir),
        "state": state["state"],
        "source_node_count": manifest["source_node_count"],
    }


SEMANTIC_BLOCK_FIELDS = {
    "block_id",
    "name",
    "role",
    "role_basis",
    "role_evidence",
    "parent_block_id",
    "child_block_ids",
    "appearance",
    "content_summary",
    "composition",
    "relations",
}
SOURCE_FACT_KEYS = {
    "source_node_id",
    "source_node_ids",
    "frame",
    "realFrame",
    "payload",
    "spacing_px",
    "border_width",
    "corner_radius",
    "font_size",
    "line_height",
    "letter_spacing",
}


def require_non_empty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("invalid_semantic_draft", f"{location} must be a non-empty string")
    return value


def reject_source_facts(value: object, location: str = "draft") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        raise ContractError(
            "source_fact_in_semantic_draft",
            f"semantic draft may not author numeric design facts at {location}",
        )
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_source_facts(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SOURCE_FACT_KEYS:
                raise ContractError(
                    "source_fact_in_semantic_draft",
                    f"semantic draft may not contain source fact field {location}.{key}",
                )
            reject_source_facts(item, f"{location}.{key}")


def validate_semantic_draft(draft: object, manifest_sha: str) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise ContractError("invalid_semantic_draft", "semantic draft root must be an object")
    reject_source_facts(draft)
    if draft.get("schema") != "icp.extract.semantic-draft.v1":
        raise ContractError("invalid_semantic_draft", "unsupported semantic draft schema")
    if draft.get("source_manifest_sha256") != manifest_sha:
        raise ContractError(
            "manifest_mismatch", "semantic draft is not bound to the current source manifest"
        )
    blocks = draft.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ContractError("invalid_semantic_draft", "blocks must be a non-empty array")

    indexed: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(blocks):
        location = f"blocks[{index}]"
        if not isinstance(block, dict):
            raise ContractError("invalid_semantic_draft", f"{location} must be an object")
        unknown = set(block) - SEMANTIC_BLOCK_FIELDS
        missing = SEMANTIC_BLOCK_FIELDS - set(block)
        if unknown or missing:
            raise ContractError(
                "invalid_semantic_draft",
                f"{location} fields mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}",
            )
        block_id = require_non_empty_string(block["block_id"], f"{location}.block_id")
        if block_id in indexed:
            raise ContractError("invalid_semantic_draft", f"duplicate block_id: {block_id}")
        for field in ("name", "role", "content_summary", "composition"):
            require_non_empty_string(block[field], f"{location}.{field}")
        if block["role_basis"] not in {"entailed", "interpreted"}:
            raise ContractError(
                "invalid_semantic_draft", f"{location}.role_basis must be entailed or interpreted"
            )
        evidence = block["role_evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise ContractError(
                "invalid_semantic_draft", f"{location}.role_evidence must be non-empty"
            )
        for evidence_index, item in enumerate(evidence):
            require_non_empty_string(item, f"{location}.role_evidence[{evidence_index}]")
        parent_id = block["parent_block_id"]
        if parent_id is not None:
            require_non_empty_string(parent_id, f"{location}.parent_block_id")
        child_ids = block["child_block_ids"]
        if not isinstance(child_ids, list) or len(child_ids) != len(set(child_ids)):
            raise ContractError(
                "invalid_semantic_draft", f"{location}.child_block_ids must contain unique ids"
            )
        for child_index, child_id in enumerate(child_ids):
            require_non_empty_string(child_id, f"{location}.child_block_ids[{child_index}]")
        appearance = block["appearance"]
        if not isinstance(appearance, dict) or set(appearance) != {
            "background",
            "border",
            "spacing",
        }:
            raise ContractError(
                "invalid_semantic_draft",
                f"{location}.appearance requires background, border, and spacing",
            )
        for field in ("background", "border", "spacing"):
            require_non_empty_string(appearance[field], f"{location}.appearance.{field}")
        relations = block["relations"]
        if not isinstance(relations, list):
            raise ContractError("invalid_semantic_draft", f"{location}.relations must be an array")
        for relation_index, relation in enumerate(relations):
            relation_location = f"{location}.relations[{relation_index}]"
            if not isinstance(relation, dict) or set(relation) != {
                "type",
                "target_block_id",
                "evidence",
            }:
                raise ContractError(
                    "invalid_semantic_draft",
                    f"{relation_location} requires type, target_block_id, and evidence",
                )
            for field in ("type", "target_block_id", "evidence"):
                require_non_empty_string(relation[field], f"{relation_location}.{field}")
        indexed[block_id] = block

    roots = [block_id for block_id, block in indexed.items() if block["parent_block_id"] is None]
    if len(roots) != 1:
        raise ContractError("invalid_semantic_draft", "semantic hierarchy must have exactly one root")
    for block_id, block in indexed.items():
        parent_id = block["parent_block_id"]
        if parent_id is not None:
            if parent_id not in indexed:
                raise ContractError(
                    "invalid_semantic_draft", f"unknown parent {parent_id} for block {block_id}"
                )
            if block_id not in indexed[parent_id]["child_block_ids"]:
                raise ContractError(
                    "invalid_semantic_draft", f"parent/child mismatch for block {block_id}"
                )
        for child_id in block["child_block_ids"]:
            if child_id not in indexed or indexed[child_id]["parent_block_id"] != block_id:
                raise ContractError(
                    "invalid_semantic_draft", f"parent/child mismatch for child {child_id}"
                )
        for relation in block["relations"]:
            if relation["target_block_id"] not in indexed:
                raise ContractError(
                    "invalid_semantic_draft",
                    f"unknown relation target {relation['target_block_id']} for block {block_id}",
                )

    visited: set[str] = set()

    def walk(block_id: str, ancestors: set[str]) -> None:
        if block_id in ancestors:
            raise ContractError("invalid_semantic_draft", "semantic hierarchy contains a cycle")
        if block_id in visited:
            return
        visited.add(block_id)
        for child_id in indexed[block_id]["child_block_ids"]:
            walk(child_id, {*ancestors, block_id})

    walk(roots[0], set())
    if visited != set(indexed):
        raise ContractError("invalid_semantic_draft", "semantic hierarchy is disconnected")
    return draft


def stage_relative_file(stage_dir: Path, relative_value: object, label: str) -> Path:
    if not isinstance(relative_value, str) or not relative_value:
        raise ContractError("source_drift", f"manifest {label} path is invalid")
    candidate = (stage_dir / relative_value).resolve()
    try:
        candidate.relative_to(stage_dir.resolve())
    except ValueError as exc:
        raise ContractError("source_drift", f"manifest {label} escapes extract stage") from exc
    return candidate


def verify_frozen_sources(
    stage_dir: Path, state: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = read_json(stage_dir / "source-manifest.json")
    if not isinstance(manifest, dict):
        raise ContractError("source_drift", "source manifest must be an object")
    if sha256_bytes(json_bytes(manifest)) != state.get("source_manifest_sha256"):
        raise ContractError("source_drift", "source manifest hash changed")
    source_path = stage_relative_file(stage_dir, manifest.get("source_file"), "source")
    reference_record = manifest.get("reference")
    if not isinstance(reference_record, dict):
        raise ContractError("source_drift", "source manifest reference mapping is missing")
    reference_path = stage_relative_file(
        stage_dir, reference_record.get("path"), "reference"
    )
    require_file(source_path, "frozen source JSON")
    require_file(reference_path, "frozen reference image")
    source_raw = source_path.read_bytes()
    reference_raw = reference_path.read_bytes()
    if sha256_bytes(source_raw) != manifest.get("source_sha256"):
        raise ContractError("source_drift", "frozen source JSON hash changed")
    if sha256_bytes(reference_raw) != reference_record.get("sha256"):
        raise ContractError("source_drift", "frozen reference image hash changed")
    asset_records = manifest.get("assets")
    if not isinstance(asset_records, list):
        raise ContractError("source_drift", "source manifest assets must be an array")
    asset_root = stage_dir / "source" / "assets"
    expected_asset_paths: set[str] = set()
    for index, record in enumerate(asset_records):
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
            raise ContractError("source_drift", f"asset record {index} is invalid")
        relative_value = record.get("path")
        if not isinstance(relative_value, str) or not relative_value:
            raise ContractError("source_drift", f"asset record {index} path is invalid")
        asset_path = stage_relative_file(asset_root, relative_value, f"asset {index}")
        require_file(asset_path, f"frozen asset {relative_value}")
        if asset_path.is_symlink():
            raise ContractError("source_drift", f"frozen asset became a symlink: {relative_value}")
        asset_raw = asset_path.read_bytes()
        if sha256_bytes(asset_raw) != record.get("sha256") or len(asset_raw) != record.get("size"):
            raise ContractError("source_drift", f"frozen asset hash changed: {relative_value}")
        expected_asset_paths.add(relative_value)
    actual_asset_paths = (
        {
            path.relative_to(asset_root).as_posix()
            for path in asset_root.rglob("*")
            if path.is_file()
        }
        if asset_root.is_dir()
        else set()
    )
    if actual_asset_paths != expected_asset_paths:
        raise ContractError("source_drift", "frozen asset set changed")
    try:
        source = json.loads(source_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("source_drift", f"frozen source JSON is invalid: {exc}") from exc
    if not isinstance(source, dict):
        raise ContractError("source_drift", "frozen source JSON root changed")
    figma_json = source.get("figma_json")
    if not isinstance(figma_json, dict):
        raise ContractError("source_drift", "frozen source figma_json changed")
    try:
        reference_pixel_size = png_size(reference_raw)
        logical_artboard_size = artboard_size(figma_json)
        logical_scale = reference_logical_scale(
            reference_pixel_size, logical_artboard_size
        )
    except LanhuError as exc:
        raise ContractError("source_drift", exc.message) from exc
    expected_reference = {
        "path": reference_record.get("path"),
        "sha256": sha256_bytes(reference_raw),
        "pixel_size": reference_pixel_size,
        "logical_artboard_size": logical_artboard_size,
        "logical_scale": logical_scale,
    }
    if reference_record != expected_reference:
        raise ContractError(
            "source_drift", "reference mapping does not match source artboard and PNG"
        )
    recomputed_facts = normalize_source(source, manifest["source_sha256"])
    facts_path = stage_dir / "source-facts.json"
    facts_raw = facts_path.read_bytes() if facts_path.is_file() else b""
    if facts_raw != json_bytes(recomputed_facts):
        raise ContractError("source_drift", "source-facts.json is not a lossless source projection")
    if sha256_bytes(facts_raw) != manifest.get("source_facts_sha256"):
        raise ContractError("source_drift", "source facts hash changed")
    if recomputed_facts["root_node_id"] != manifest.get("root_node_id") or len(
        recomputed_facts["node_order"]
    ) != manifest.get("source_node_count"):
        raise ContractError("source_drift", "source manifest node identity changed")
    asset_index_value = manifest.get("asset_index_file")
    if asset_index_value != "asset-index.json":
        raise ContractError("source_drift", "source manifest asset index path changed")
    asset_index_path = stage_relative_file(
        stage_dir, asset_index_value, "asset index"
    )
    require_file(asset_index_path, "asset index")
    asset_index_raw = asset_index_path.read_bytes()
    if sha256_bytes(asset_index_raw) != manifest.get("asset_index_sha256"):
        raise ContractError("source_drift", "asset index hash changed")
    expected_asset_index = build_asset_index(
        source,
        recomputed_facts,
        asset_records,
    )
    if asset_index_raw != json_bytes(expected_asset_index):
        raise ContractError(
            "source_drift", "asset index does not match source nodes and local assets"
        )
    semantic_context_path = stage_relative_file(
        stage_dir, manifest.get("semantic_context_file"), "semantic context"
    )
    require_file(semantic_context_path, "semantic context")
    semantic_context_raw = semantic_context_path.read_bytes()
    if sha256_bytes(semantic_context_raw) != manifest.get(
        "semantic_context_sha256"
    ):
        raise ContractError("source_drift", "semantic context hash changed")
    if manifest.get("semantic_context_sha256") != state.get(
        "semantic_context_sha256"
    ):
        raise ContractError("source_drift", "state semantic context binding changed")
    semantic_context = read_json(semantic_context_path)
    if (
        not isinstance(semantic_context, dict)
        or set(semantic_context) != {"schema", "design_url", "ui_supplement"}
        or semantic_context.get("schema") != "icp.extract.semantic-context.v1"
        or semantic_context.get("design_url") != manifest.get("design_url")
        or (
            semantic_context.get("ui_supplement") is not None
            and not isinstance(semantic_context.get("ui_supplement"), str)
        )
    ):
        raise ContractError("source_drift", "semantic context is invalid")
    authoring_path = stage_dir / "semantic-authoring.input.json"
    authoring = read_json(authoring_path)
    expected_authoring = {
        "schema": "icp.extract.semantic-authoring-input.v1",
        "source_manifest_sha256": state.get("source_manifest_sha256"),
        "reference": copy.deepcopy(reference_record),
        "ui_supplement": semantic_context.get("ui_supplement"),
        "instruction": (
            "Use the UI supplement only to inform visual-semantic Block "
            "boundaries; preserve all exact design facts from the frozen source."
        ),
    }
    if authoring != expected_authoring:
        raise ContractError("source_drift", "semantic authoring context changed")
    return manifest, recomputed_facts


def load_stage(project_root_value: str, design_name_value: str) -> tuple[Path, dict[str, Any]]:
    project_root = Path(project_root_value).resolve()
    stage_dir = project_root / ".icp" / "extract" / safe_design_name(design_name_value)
    if not stage_dir.is_dir():
        raise ContractError("stage_not_prepared", f"extract stage is not prepared: {stage_dir}")
    state = read_json(stage_dir / "state.json")
    if not isinstance(state, dict):
        raise ContractError("invalid_stage", "state.json must contain an object")
    manifest, _ = verify_frozen_sources(stage_dir, state)
    if manifest.get("design_name") != design_name_value:
        raise ContractError("design_mismatch", "--design-name does not match this extract directory")
    return stage_dir, state


def sync_stage_index(
    project_root_value: str, stage_dir: Path, state: dict[str, Any]
) -> None:
    manifest = read_json(stage_dir / "source-manifest.json")
    if not isinstance(manifest, dict):
        raise ContractError("invalid_stage", "source manifest must be an object")
    update_batch_index(
        Path(project_root_value).resolve(),
        identity(manifest, "design_url"),
        {
            "design_name": identity(manifest, "design_name"),
            "design_dir": identity(manifest, "design_dir"),
            "design_id": identity(manifest, "design_id"),
            "version_id": identity(manifest, "version_id"),
            "state": state.get("state"),
            "source_manifest_sha256": state.get("source_manifest_sha256"),
            "stage_result_sha256": state.get("stage_result_sha256"),
        },
    )


def record_draft(args: argparse.Namespace) -> dict[str, Any]:
    stage_dir, state = load_stage(args.project_root, args.design_name)
    draft = validate_semantic_draft(
        read_json(Path(args.draft).resolve()), state.get("source_manifest_sha256", "")
    )
    draft_raw = json_bytes(draft)
    draft_sha = sha256_bytes(draft_raw)
    current_path = stage_dir / "semantic-draft.json"
    if (
        current_path.is_file()
        and current_path.read_bytes() == draft_raw
        and state.get("state") != "awaiting_semantic_draft"
        and state.get("semantic_draft_sha256") == draft_sha
    ):
        sync_stage_index(args.project_root, stage_dir, state)
        return {
            "ok": True,
            "resumed": True,
            "stage_dir": str(stage_dir),
            "state": state.get("state"),
        }
    if state.get("state") not in {"awaiting_semantic_draft", "repair_required"}:
        raise ContractError(
            "invalid_transition", f"cannot record semantic draft while state={state.get('state')}"
        )
    revision = state.get("revision")
    if not isinstance(revision, int) or revision < 0:
        raise ContractError("invalid_stage", "state revision must be a non-negative integer")
    revision += 1
    next_state = {
        **state,
        "state": "awaiting_bindings",
        "revision": revision,
        "semantic_draft_sha256": draft_sha,
    }
    facts = read_json(stage_dir / "source-facts.json")
    node_order = facts.get("node_order") if isinstance(facts, dict) else None
    if not isinstance(node_order, list):
        raise ContractError("invalid_stage", "source node order is invalid")
    bindings_input = {
        "schema": "icp.extract.bindings.v1",
        "source_manifest_sha256": state["source_manifest_sha256"],
        "semantic_draft_sha256": draft_sha,
        "assignments": [
            {
                "source_node_id": node_id,
                "status": "unresolved",
                "block_id": None,
                "geometry_basis": "not_applicable",
                "content_role": "unresolved",
                "rationale": "Pending source-to-semantic classification.",
            }
            for node_id in node_order
        ],
    }
    atomic_write_json(stage_dir / "revisions" / f"semantic-draft.{revision:04d}.json", draft)
    atomic_write_json(current_path, draft)
    atomic_write_json(stage_dir / "bindings.input.json", bindings_input)
    atomic_write_json(stage_dir / "state.json", next_state)
    sync_stage_index(args.project_root, stage_dir, next_state)
    return {
        "ok": True,
        "resumed": False,
        "stage_dir": str(stage_dir),
        "state": next_state["state"],
        "revision": revision,
        "semantic_block_count": len(draft["blocks"]),
    }


BINDING_FIELDS = {
    "source_node_id",
    "status",
    "block_id",
    "geometry_basis",
    "content_role",
    "rationale",
}
BINDING_STATUSES = {"mapped", "absorbed", "non_rendering", "unresolved"}
GEOMETRY_BASES = {"frame", "real_frame", "combined", "not_applicable"}
RENDERING_CONTENT_ROLES = {
    "static_visual",
    "static_copy",
    "dynamic_content",
    "platform_element",
}
CONTENT_ROLES = {*RENDERING_CONTENT_ROLES, "not_applicable", "unresolved"}


def validate_bindings(
    bindings: object,
    state: dict[str, Any],
    facts: dict[str, Any],
    semantic_draft: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not isinstance(bindings, dict):
        raise ContractError("invalid_bindings", "bindings root must be an object")
    if bindings.get("schema") != "icp.extract.bindings.v1":
        raise ContractError("invalid_bindings", "unsupported bindings schema")
    if bindings.get("source_manifest_sha256") != state.get("source_manifest_sha256"):
        raise ContractError("manifest_mismatch", "bindings do not match the source manifest")
    if bindings.get("semantic_draft_sha256") != state.get("semantic_draft_sha256"):
        raise ContractError("draft_mismatch", "bindings do not match the current semantic draft")
    assignments = bindings.get("assignments")
    if not isinstance(assignments, list):
        raise ContractError("invalid_bindings", "assignments must be an array")

    source_nodes = facts.get("nodes")
    if not isinstance(source_nodes, dict):
        raise ContractError("invalid_stage", "source-facts nodes must be an object")
    semantic_blocks = semantic_draft.get("blocks")
    if not isinstance(semantic_blocks, list):
        raise ContractError("invalid_stage", "semantic-draft blocks must be an array")
    block_ids = {
        block.get("block_id")
        for block in semantic_blocks
        if isinstance(block, dict) and isinstance(block.get("block_id"), str)
    }
    indexed: dict[str, dict[str, Any]] = {}
    for index, assignment in enumerate(assignments):
        location = f"assignments[{index}]"
        if not isinstance(assignment, dict) or set(assignment) != BINDING_FIELDS:
            raise ContractError(
                "invalid_bindings", f"{location} must contain exactly {sorted(BINDING_FIELDS)}"
            )
        node_id = require_non_empty_string(
            assignment["source_node_id"], f"{location}.source_node_id"
        )
        if node_id in indexed:
            raise ContractError("duplicate_source_binding", f"source node bound twice: {node_id}")
        if node_id not in source_nodes:
            raise ContractError("synthetic_source_id", f"unknown source node id: {node_id}")
        status = assignment["status"]
        if status not in BINDING_STATUSES:
            raise ContractError("invalid_bindings", f"unsupported status for {node_id}: {status}")
        geometry_basis = assignment["geometry_basis"]
        if geometry_basis not in GEOMETRY_BASES:
            raise ContractError(
                "invalid_bindings", f"unsupported geometry_basis for {node_id}: {geometry_basis}"
            )
        content_role = assignment["content_role"]
        if content_role not in CONTENT_ROLES:
            raise ContractError(
                "invalid_content_role",
                f"unsupported content_role for {node_id}: {content_role}",
            )
        require_non_empty_string(assignment["rationale"], f"{location}.rationale")
        block_id = assignment["block_id"]
        if status in {"mapped", "absorbed"}:
            if block_id not in block_ids:
                raise ContractError(
                    "invalid_bindings", f"{node_id} must reference an existing semantic block"
                )
        elif block_id is not None:
            raise ContractError(
                "invalid_bindings", f"{node_id} status {status} must use null block_id"
            )

        node = source_nodes[node_id]
        payload = node.get("payload") if isinstance(node, dict) else None
        if not isinstance(payload, dict):
            raise ContractError("invalid_stage", f"source fact payload missing for {node_id}")
        geometry_fields = {
            "frame": "frame",
            "real_frame": "realFrame",
            "combined": "combinedFrame",
        }
        has_geometry = any(
            isinstance(payload.get(field), dict) for field in geometry_fields.values()
        )
        if status in {"mapped", "absorbed"}:
            if content_role not in RENDERING_CONTENT_ROLES:
                raise ContractError(
                    "invalid_content_role",
                    f"rendering source node {node_id} requires a rendering content_role",
                )
            if geometry_basis == "not_applicable" and has_geometry:
                raise ContractError(
                    "invalid_geometry_basis", f"rendering source node {node_id} has geometry"
                )
            required_field = geometry_fields.get(geometry_basis)
            if required_field is not None and not isinstance(payload.get(required_field), dict):
                raise ContractError(
                    "invalid_geometry_basis",
                    f"source node {node_id} has no {required_field} for {geometry_basis}",
                )
            rotation = payload.get("rotation", 0)
            if (
                isinstance(rotation, (int, float))
                and not isinstance(rotation, bool)
                and rotation != 0
                and isinstance(payload.get("realFrame"), dict)
                and geometry_basis not in {"real_frame", "combined"}
            ):
                raise ContractError(
                    "invalid_geometry_basis",
                    f"rotated source node {node_id} must use real_frame or combined geometry",
                )
        if status in {"non_rendering", "unresolved"} and geometry_basis != "not_applicable":
            raise ContractError(
                "invalid_geometry_basis",
                f"{status} source node {node_id} must use not_applicable geometry",
            )
        expected_content_role = (
            "not_applicable" if status == "non_rendering" else "unresolved"
        )
        if (
            status in {"non_rendering", "unresolved"}
            and content_role != expected_content_role
        ):
            raise ContractError(
                "invalid_content_role",
                f"{status} source node {node_id} must use {expected_content_role} content_role",
            )
        indexed[node_id] = assignment
    return bindings, indexed


def source_subtree_ids(node_id: str, nodes: dict[str, Any]) -> list[str]:
    result: list[str] = []

    def walk(current_id: str) -> None:
        result.append(current_id)
        current = nodes[current_id]
        for child_id in current.get("child_ids", []):
            walk(child_id)

    walk(node_id)
    return result


def inferred_geometry_basis(node: dict[str, Any], status: str) -> str:
    if status in {"non_rendering", "unresolved"}:
        return "not_applicable"
    payload = node.get("payload")
    if not isinstance(payload, dict):
        raise ContractError("invalid_stage", "source node payload is missing")
    rotation = payload.get("rotation", 0)
    if (
        isinstance(rotation, (int, float))
        and not isinstance(rotation, bool)
        and rotation != 0
        and isinstance(payload.get("realFrame"), dict)
    ):
        return "real_frame"
    if isinstance(payload.get("frame"), dict):
        return "frame"
    if isinstance(payload.get("realFrame"), dict):
        return "real_frame"
    if isinstance(payload.get("combinedFrame"), dict):
        return "combined"
    return "not_applicable"


def expand_bindings(args: argparse.Namespace) -> dict[str, Any]:
    stage_dir, state = load_stage(args.project_root, args.design_name)
    if state.get("state") not in {"awaiting_bindings", "repair_required"}:
        raise ContractError(
            "invalid_transition", f"cannot expand bindings while state={state.get('state')}"
        )
    plan = read_json(Path(args.plan).resolve())
    expected_fields = {
        "schema",
        "source_manifest_sha256",
        "semantic_draft_sha256",
        "rules",
    }
    if not isinstance(plan, dict) or set(plan) != expected_fields:
        raise ContractError("invalid_binding_plan", "binding plan fields are invalid")
    if plan.get("schema") != "icp.extract.binding-plan.v1":
        raise ContractError("invalid_binding_plan", "unsupported binding plan schema")
    for field in ("source_manifest_sha256", "semantic_draft_sha256"):
        if plan.get(field) != state.get(field):
            raise ContractError("binding_plan_stale", f"binding plan {field} is stale")
    rules = plan.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ContractError("invalid_binding_plan", "binding plan rules must be non-empty")

    facts = read_json(stage_dir / "source-facts.json")
    semantic_draft = read_json(stage_dir / "semantic-draft.json")
    if not isinstance(facts, dict) or not isinstance(semantic_draft, dict):
        raise ContractError("invalid_stage", "source facts and semantic draft must be objects")
    nodes = facts.get("nodes")
    node_order = facts.get("node_order")
    if not isinstance(nodes, dict) or not isinstance(node_order, list):
        raise ContractError("invalid_stage", "source node inventory is invalid")
    block_ids = {block["block_id"] for block in semantic_draft["blocks"]}
    selections: dict[str, dict[str, Any]] = {}
    rule_fields = {
        "source_node_ids",
        "source_subtree_roots",
        "status",
        "block_id",
        "content_role",
        "rationale",
    }
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != rule_fields:
            raise ContractError("invalid_binding_plan", f"rule {index} fields are invalid")
        node_ids = rule["source_node_ids"]
        subtree_roots = rule["source_subtree_roots"]
        if (
            not isinstance(node_ids, list)
            or not isinstance(subtree_roots, list)
            or any(not isinstance(value, str) or not value for value in [*node_ids, *subtree_roots])
        ):
            raise ContractError("invalid_binding_plan", f"rule {index} selectors are invalid")
        status = rule["status"]
        block_id = rule["block_id"]
        content_role = rule["content_role"]
        if status not in BINDING_STATUSES:
            raise ContractError("invalid_binding_plan", f"rule {index} status is invalid")
        if status in {"mapped", "absorbed"} and block_id not in block_ids:
            raise ContractError("invalid_binding_plan", f"rule {index} block is unknown")
        if status in {"non_rendering", "unresolved"} and block_id is not None:
            raise ContractError("invalid_binding_plan", f"rule {index} must use null block_id")
        if content_role not in CONTENT_ROLES:
            raise ContractError(
                "invalid_binding_plan", f"rule {index} content_role is invalid"
            )
        if status in {"mapped", "absorbed"} and content_role not in RENDERING_CONTENT_ROLES:
            raise ContractError(
                "invalid_binding_plan",
                f"rule {index} rendering nodes require a rendering content_role",
            )
        if status == "non_rendering" and content_role != "not_applicable":
            raise ContractError(
                "invalid_binding_plan",
                f"rule {index} non_rendering nodes require not_applicable content_role",
            )
        if status == "unresolved" and content_role != "unresolved":
            raise ContractError(
                "invalid_binding_plan",
                f"rule {index} unresolved nodes require unresolved content_role",
            )
        require_non_empty_string(rule["rationale"], f"rules[{index}].rationale")
        selected = list(node_ids)
        for root_id in subtree_roots:
            if root_id not in nodes:
                raise ContractError("unknown_source_id", f"unknown subtree root: {root_id}")
            selected.extend(source_subtree_ids(root_id, nodes))
        for node_id in selected:
            if node_id not in nodes:
                raise ContractError("unknown_source_id", f"unknown source node: {node_id}")
            if node_id in selections:
                raise ContractError("binding_plan_overlap", f"source node selected twice: {node_id}")
            selections[node_id] = rule
    missing = [node_id for node_id in node_order if node_id not in selections]
    if missing:
        raise ContractError(
            "binding_plan_incomplete", f"binding plan omits source nodes: {missing}"
        )
    bindings = {
        "schema": "icp.extract.bindings.v1",
        "source_manifest_sha256": state["source_manifest_sha256"],
        "semantic_draft_sha256": state["semantic_draft_sha256"],
        "assignments": [
            {
                "source_node_id": node_id,
                "status": selections[node_id]["status"],
                "block_id": selections[node_id]["block_id"],
                "geometry_basis": inferred_geometry_basis(
                    nodes[node_id], selections[node_id]["status"]
                ),
                "content_role": selections[node_id]["content_role"],
                "rationale": selections[node_id]["rationale"],
            }
            for node_id in node_order
        ],
    }
    validate_bindings(bindings, state, facts, semantic_draft)
    output_path = stage_dir / "bindings.input.json"
    atomic_write_json(output_path, bindings)
    return {
        "ok": True,
        "binding_count": len(node_order),
        "bindings": str(output_path),
    }


def require_semantic_leaf_reachability(
    semantic_draft: dict[str, Any], assignments: dict[str, dict[str, Any]]
) -> None:
    directly_bound = {
        assignment["block_id"]
        for assignment in assignments.values()
        if assignment.get("status") in {"mapped", "absorbed"}
    }
    unbound_leaves = [
        block["block_id"]
        for block in semantic_draft["blocks"]
        if not block["child_block_ids"] and block["block_id"] not in directly_bound
    ]
    if unbound_leaves:
        raise ContractError(
            "unbound_semantic_leaf",
            f"semantic leaf blocks have no mapped or absorbed source nodes: {unbound_leaves}",
        )


def build_binding_evidence(
    semantic_draft: dict[str, Any],
    node_order: list[str],
    assignments: dict[str, dict[str, Any]],
    bindings_sha256: str,
) -> dict[str, Any]:
    return {
        "bindings_sha256": bindings_sha256,
        "blocks": [
            {
                "block_id": block["block_id"],
                "mapped_source_node_ids": [
                    node_id
                    for node_id in node_order
                    if assignments[node_id].get("status") == "mapped"
                    and assignments[node_id].get("block_id") == block["block_id"]
                ],
                "absorbed_source_node_ids": [
                    node_id
                    for node_id in node_order
                    if assignments[node_id].get("status") == "absorbed"
                    and assignments[node_id].get("block_id") == block["block_id"]
                ],
            }
            for block in semantic_draft["blocks"]
        ],
        "non_rendering": [
            {
                "source_node_id": node_id,
                "rationale": assignments[node_id]["rationale"],
            }
            for node_id in node_order
            if assignments[node_id].get("status") == "non_rendering"
        ],
    }


def build_reverse_binding_evidence(
    semantic_draft: dict[str, Any],
    facts: dict[str, Any],
    node_order: list[str],
    assignments: dict[str, dict[str, Any]],
    bindings_sha256: str,
) -> dict[str, Any]:
    """Freeze the JSON-node-first view used to audit semantic completeness.

    Exact coverage answers whether every source node was assigned. This reverse
    projection additionally gives the reviewer every original node, its source
    relations, its current assignment, and the complete target Block so a
    present-but-wrong assignment cannot hide behind 100% node coverage.
    """
    nodes = facts["nodes"]
    blocks = {block["block_id"]: block for block in semantic_draft["blocks"]}
    evidence_nodes: list[dict[str, Any]] = []
    for node_id in node_order:
        node = nodes[node_id]
        parent_id = node.get("parent_id")
        assignment = assignments[node_id]
        block_id = assignment.get("block_id")
        evidence_nodes.append(
            {
                "source_node": copy.deepcopy(node),
                "parent_source_node": (
                    copy.deepcopy(nodes[parent_id]) if parent_id is not None else None
                ),
                "child_source_nodes": [
                    copy.deepcopy(nodes[child_id])
                    for child_id in node.get("child_ids", [])
                ],
                "assignment": copy.deepcopy(assignment),
                "assigned_block": (
                    copy.deepcopy(blocks[block_id])
                    if isinstance(block_id, str)
                    else None
                ),
            }
        )
    return {
        "schema": "icp.extract.reverse-binding-evidence.v1",
        "source_manifest_sha256": semantic_draft["source_manifest_sha256"],
        "semantic_draft_sha256": sha256_bytes(json_bytes(semantic_draft)),
        "bindings_sha256": bindings_sha256,
        "nodes": evidence_nodes,
    }


def build_semantic_blocks(
    stage_dir: Path,
    manifest: dict[str, Any],
    state: dict[str, Any],
    semantic_draft: dict[str, Any],
    facts: dict[str, Any],
    bindings: dict[str, Any],
) -> dict[str, Any]:
    """Materialize self-contained Blocks that losslessly reconstruct source facts."""

    node_order = facts.get("node_order")
    nodes = facts.get("nodes")
    if not isinstance(node_order, list) or not isinstance(nodes, dict):
        raise ContractError("invalid_stage", "source facts inventory is invalid")
    assignments = {
        item["source_node_id"]: item
        for item in bindings.get("assignments", [])
        if isinstance(item, dict) and isinstance(item.get("source_node_id"), str)
    }
    if set(assignments) != set(node_order):
        raise ContractError(
            "stage_drift", "semantic Block materialization needs every source assignment"
        )
    asset_index = read_json(stage_dir / "asset-index.json")
    if not isinstance(asset_index, dict):
        raise ContractError("invalid_stage", "asset index must be an object")
    assets_by_node: dict[str, list[dict[str, Any]]] = {}
    for asset in asset_index.get("assets", []):
        if not isinstance(asset, dict):
            raise ContractError("invalid_stage", "asset index entry must be an object")
        references = asset.get("source_references")
        if not isinstance(references, list):
            raise ContractError("invalid_stage", "asset source references must be an array")
        for reference in references:
            if not isinstance(reference, dict):
                raise ContractError("invalid_stage", "asset source reference must be an object")
            node_id = reference.get("source_node_id")
            if node_id not in nodes:
                raise ContractError("stage_drift", "asset references an unknown source node")
            assets_by_node.setdefault(node_id, []).append(copy.deepcopy(asset))
    source_document = read_json(stage_dir / manifest["source_file"])
    if not isinstance(source_document, dict):
        raise ContractError("source_drift", "source design document must be an object")
    source_document_without_artboard = copy.deepcopy(source_document)
    source_figma = source_document_without_artboard.get("figma_json")
    if not isinstance(source_figma, dict) or "artboard" not in source_figma:
        raise ContractError("source_drift", "source design artboard is missing")
    source_figma.pop("artboard")
    semantic_context = read_json(stage_dir / manifest["semantic_context_file"])
    if (
        not isinstance(semantic_context, dict)
        or sha256_bytes(json_bytes(semantic_context))
        != state["semantic_context_sha256"]
    ):
        raise ContractError("source_drift", "semantic context changed")

    members_by_block = {
        block["block_id"]: [] for block in semantic_draft["blocks"]
    }
    non_rendering: list[dict[str, Any]] = []
    for node_id in node_order:
        assignment = assignments[node_id]
        member = {
            "source_node_id": node_id,
            "status": assignment.get("status"),
            "geometry_basis": assignment.get("geometry_basis"),
            "content_role": assignment.get("content_role"),
            "rationale": assignment.get("rationale"),
            "source_fact": copy.deepcopy(nodes[node_id]),
            "assets": copy.deepcopy(assets_by_node.get(node_id, [])),
        }
        block_id = assignment.get("block_id")
        if block_id is None:
            non_rendering.append(member)
        elif block_id in members_by_block:
            members_by_block[block_id].append(member)
        else:
            raise ContractError("stage_drift", "assignment targets an unknown Block")

    roots = [
        block["block_id"]
        for block in semantic_draft["blocks"]
        if block.get("parent_block_id") is None
    ]
    if len(roots) != 1:
        raise ContractError("stage_drift", "semantic Blocks need exactly one root")
    result = {
        "schema": "icp.extract.semantic-blocks.v1",
        "source_manifest_sha256": state["source_manifest_sha256"],
        "source_sha256": manifest["source_sha256"],
        "source_facts_sha256": manifest["source_facts_sha256"],
        "asset_index_sha256": manifest["asset_index_sha256"],
        "semantic_context_sha256": state["semantic_context_sha256"],
        "semantic_context": semantic_context,
        "semantic_draft_sha256": state["semantic_draft_sha256"],
        "bindings_sha256": state["bindings_sha256"],
        "root_node_id": facts["root_node_id"],
        "root_block_id": roots[0],
        "node_order": copy.deepcopy(node_order),
        "source_document_without_artboard": source_document_without_artboard,
        "blocks": [
            {
                "block_id": block["block_id"],
                "semantic": copy.deepcopy(block),
                "source_nodes": members_by_block[block["block_id"]],
            }
            for block in semantic_draft["blocks"]
        ],
        "non_rendering_source_nodes": non_rendering,
    }
    grouped_nodes = {
        member["source_node_id"]: member["source_fact"]
        for block in result["blocks"]
        for member in block["source_nodes"]
    }
    grouped_nodes.update(
        {
            member["source_node_id"]: member["source_fact"]
            for member in non_rendering
        }
    )
    if set(grouped_nodes) != set(node_order):
        raise ContractError(
            "stage_drift", "semantic Blocks do not contain every source node exactly once"
        )
    reconstructed_nodes = {node_id: grouped_nodes[node_id] for node_id in node_order}
    reconstructed_facts = {
        "schema": facts["schema"],
        "source_sha256": facts["source_sha256"],
        "root_node_id": facts["root_node_id"],
        "node_order": copy.deepcopy(node_order),
        "nodes": reconstructed_nodes,
    }
    if (
        reconstructed_facts != facts
        or sha256_bytes(json_bytes(reconstructed_facts))
        != manifest["source_facts_sha256"]
    ):
        raise ContractError(
            "stage_drift", "semantic Blocks cannot losslessly reconstruct source facts"
        )
    def rebuild_node(node_id: str) -> dict[str, Any]:
        record = reconstructed_nodes[node_id]
        node = copy.deepcopy(record["payload"])
        if record.get("layers_kind") == "array":
            node["layers"] = [
                rebuild_node(child_id) for child_id in record["child_ids"]
            ]
        elif record.get("layers_kind") == "null":
            node["layers"] = None
        return node

    reconstructed_document = copy.deepcopy(source_document_without_artboard)
    reconstructed_document["figma_json"]["artboard"] = rebuild_node(
        facts["root_node_id"]
    )
    if reconstructed_document != source_document:
        raise ContractError(
            "stage_drift", "semantic Blocks cannot reconstruct the complete design JSON"
        )
    return result


def repair_packet(
    node_id: str,
    reason: str,
    facts: dict[str, Any],
    assignments: dict[str, dict[str, Any]],
    semantic_draft: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    nodes = facts["nodes"]
    node = nodes[node_id]
    parent_id = node.get("parent_id")
    parent = nodes.get(parent_id) if parent_id is not None else None
    sibling_ids = (
        [candidate for candidate in parent.get("child_ids", []) if candidate != node_id]
        if isinstance(parent, dict)
        else []
    )
    related_ids = ([parent_id] if parent_id is not None else []) + sibling_ids
    candidate_block_ids: list[str] = []
    for related_id in related_ids:
        assignment = assignments.get(related_id)
        if assignment and assignment.get("status") in {"mapped", "absorbed"}:
            block_id = assignment.get("block_id")
            if isinstance(block_id, str) and block_id not in candidate_block_ids:
                candidate_block_ids.append(block_id)
    blocks_by_id = {block["block_id"]: block for block in semantic_draft["blocks"]}
    payload = node["payload"]
    crop_bounds = payload.get("realFrame") or payload.get("frame")
    reference = manifest.get("reference")
    if not isinstance(reference, dict):
        raise ContractError("invalid_stage", "reference mapping is missing")
    return {
        "schema": "icp.extract.repair-packet.v1",
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "semantic_draft_sha256": manifest["semantic_draft_sha256"],
        "reason": reason,
        "reference": {
            "file": reference["path"],
            "sha256": reference["sha256"],
            "pixel_size": reference["pixel_size"],
            "logical_artboard_size": reference["logical_artboard_size"],
            "logical_scale": reference["logical_scale"],
            "crop_bounds": crop_bounds,
        },
        "source_node": node,
        "source_subtree_ids": source_subtree_ids(node_id, nodes),
        "parent_node": parent,
        "sibling_nodes": [nodes[sibling_id] for sibling_id in sibling_ids],
        "current_binding": assignments.get(node_id),
        "candidate_block_ids": candidate_block_ids,
        "candidate_blocks": [blocks_by_id[block_id] for block_id in candidate_block_ids],
        "allowed_repairs": [
            "bind_to_existing_block",
            "split_semantic_block",
            "merge_semantic_blocks",
            "create_semantic_block",
            "classify_non_rendering",
        ],
    }


def record_bindings(args: argparse.Namespace) -> dict[str, Any]:
    stage_dir, state = load_stage(args.project_root, args.design_name)
    if state.get("state") not in {"awaiting_bindings", "repair_required"}:
        raise ContractError(
            "invalid_transition", f"cannot record bindings while state={state.get('state')}"
        )
    facts = read_json(stage_dir / "source-facts.json")
    semantic_draft = read_json(stage_dir / "semantic-draft.json")
    source_manifest = read_json(stage_dir / "source-manifest.json")
    if not isinstance(facts, dict) or not isinstance(semantic_draft, dict):
        raise ContractError("invalid_stage", "extract facts and semantic draft must be objects")
    if not isinstance(source_manifest, dict):
        raise ContractError("invalid_stage", "source manifest must be an object")
    bindings, assignments = validate_bindings(
        read_json(Path(args.bindings).resolve()), state, facts, semantic_draft
    )
    node_order = facts.get("node_order")
    if not isinstance(node_order, list) or any(node_id not in facts["nodes"] for node_id in node_order):
        raise ContractError("invalid_stage", "source node_order is invalid")

    partitions: dict[str, list[str]] = {
        "mapped": [],
        "absorbed": [],
        "non_rendering": [],
        "unresolved": [],
    }
    unresolved_reasons: dict[str, str] = {}
    for node_id in node_order:
        assignment = assignments.get(node_id)
        if assignment is None:
            partitions["unresolved"].append(node_id)
            unresolved_reasons[node_id] = "missing_assignment"
        else:
            status = assignment["status"]
            partitions[status].append(node_id)
            if status == "unresolved":
                unresolved_reasons[node_id] = assignment["rationale"]

    complete = not partitions["unresolved"]
    if complete:
        require_semantic_leaf_reachability(semantic_draft, assignments)
    revision = state.get("revision")
    if not isinstance(revision, int) or revision < 0:
        raise ContractError("invalid_stage", "state revision must be a non-negative integer")
    revision += 1
    bindings_raw = json_bytes(bindings)
    bindings_sha = sha256_bytes(bindings_raw)
    binding_evidence = (
        build_binding_evidence(semantic_draft, node_order, assignments, bindings_sha)
        if complete
        else None
    )
    binding_evidence_sha = (
        sha256_bytes(json_bytes(binding_evidence)) if binding_evidence is not None else None
    )
    reverse_binding_evidence = (
        build_reverse_binding_evidence(
            semantic_draft, facts, node_order, assignments, bindings_sha
        )
        if complete
        else None
    )
    reverse_binding_evidence_sha = (
        sha256_bytes(json_bytes(reverse_binding_evidence))
        if reverse_binding_evidence is not None
        else None
    )
    repair_root = stage_dir / "repair-packets" / f"revision-{revision:04d}"
    repair_files: dict[str, str] = {}
    packet_manifest = {
        **source_manifest,
        "source_manifest_sha256": state["source_manifest_sha256"],
        "semantic_draft_sha256": state["semantic_draft_sha256"],
    }
    packets: dict[Path, dict[str, Any]] = {}
    for index, node_id in enumerate(partitions["unresolved"]):
        token = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:12]
        relative = Path("repair-packets") / f"revision-{revision:04d}" / f"{index:04d}-{token}.json"
        repair_files[node_id] = relative.as_posix()
        packets[stage_dir / relative] = repair_packet(
            node_id,
            unresolved_reasons[node_id],
            facts,
            assignments,
            semantic_draft,
            packet_manifest,
        )
    coverage = {
        "schema": "icp.extract.coverage.v1",
        "source_manifest_sha256": state["source_manifest_sha256"],
        "semantic_draft_sha256": state["semantic_draft_sha256"],
        "bindings_sha256": bindings_sha,
        "source_node_count": len(node_order),
        "partitions": partitions,
        "duplicate_bindings": [],
        "synthetic_source_ids": [],
        "repair_packets": repair_files,
        "binding_evidence_sha256": binding_evidence_sha,
        "reverse_binding_evidence_sha256": reverse_binding_evidence_sha,
        "complete": complete,
    }
    coverage_sha = sha256_bytes(json_bytes(coverage))
    next_state = {
        **state,
        "state": "awaiting_semantic_review" if complete else "repair_required",
        "revision": revision,
        "bindings_sha256": bindings_sha,
        "coverage_sha256": coverage_sha,
        "repair_packet_dir": str(repair_root.relative_to(stage_dir)),
    }
    if binding_evidence_sha is not None:
        next_state["binding_evidence_sha256"] = binding_evidence_sha
    if reverse_binding_evidence_sha is not None:
        next_state["reverse_binding_evidence_sha256"] = reverse_binding_evidence_sha
    semantic_review_input = None
    if complete:
        semantic_context = read_json(stage_dir / "semantic-context.json")
        semantic_review_input = {
            "schema": "icp.extract.semantic-review.v1",
            "source_manifest_sha256": state["source_manifest_sha256"],
            "semantic_draft_sha256": state["semantic_draft_sha256"],
            "coverage_sha256": coverage_sha,
            "semantic_context": semantic_context,
            "binding_evidence": binding_evidence,
            "reverse_binding_evidence": reverse_binding_evidence,
            "decision": "revise",
            "block_reviews": [
                {
                    "block_id": block["block_id"],
                    "role_correct": False,
                    "hierarchy_correct": False,
                    "appearance_interpretation_correct": False,
                    "content_grouping_correct": False,
                    "source_binding_correct": False,
                    "evidence": ["TODO: cite the rendered reference and source-bound facts."],
                    "issues": ["TODO: review this semantic block."],
                }
                for block in semantic_draft["blocks"]
            ],
            "source_node_reviews": [
                {
                    "source_node_id": item["source_node"]["id"],
                    "semantic_assignment_correct": False,
                    "content_role_correct": False,
                    "independent_grouping_correct": False,
                    "parent_child_relation_correct": False,
                    "evidence": [
                        "TODO: compare this exact JSON node and its source relations with the assigned semantic Block."
                    ],
                    "issues": [
                        "TODO: decide whether this node is semantically complete and correctly grouped."
                    ],
                }
                for item in reverse_binding_evidence["nodes"]
            ],
            "cross_block_review": {
                "relations_correct": False,
                "reading_order_correct": False,
                "no_semantic_omissions": False,
                "non_rendering_classifications_correct": False,
                "evidence": ["TODO: cite cross-block evidence."],
                "issues": ["TODO: review cross-block semantics."],
            },
        }

    # State is committed last. A crash before that write can leave this exact
    # revision directory behind, so retry must be able to overwrite its named
    # packet files instead of permanently wedging the stage.
    repair_root.mkdir(parents=True, exist_ok=True)
    for path, packet in packets.items():
        atomic_write_json(path, packet)
    atomic_write_json(stage_dir / "revisions" / f"bindings.{revision:04d}.json", bindings)
    atomic_write_json(stage_dir / "revisions" / f"coverage.{revision:04d}.json", coverage)
    atomic_write_json(stage_dir / "bindings.json", bindings)
    atomic_write_json(stage_dir / "coverage.json", coverage)
    if semantic_review_input is not None:
        atomic_write_json(stage_dir / "semantic-review.input.json", semantic_review_input)
    atomic_write_json(stage_dir / "state.json", next_state)
    sync_stage_index(args.project_root, stage_dir, next_state)
    return {
        "ok": True,
        "stage_dir": str(stage_dir),
        "state": next_state["state"],
        "revision": revision,
        "complete": complete,
        "coverage": {status: len(node_ids) for status, node_ids in partitions.items()},
    }


def verify_exact_coverage(
    stage_dir: Path, state: dict[str, Any], facts: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    semantic_path = stage_dir / "semantic-draft.json"
    bindings_path = stage_dir / "bindings.json"
    coverage_path = stage_dir / "coverage.json"
    semantic_draft = read_json(semantic_path)
    bindings = read_json(bindings_path)
    coverage = read_json(coverage_path)
    if not all(isinstance(value, dict) for value in (semantic_draft, bindings, coverage)):
        raise ContractError("invalid_stage", "semantic draft, bindings, and coverage must be objects")
    if sha256_bytes(semantic_path.read_bytes()) != state.get("semantic_draft_sha256"):
        raise ContractError("stage_drift", "semantic draft hash changed")
    if sha256_bytes(bindings_path.read_bytes()) != state.get("bindings_sha256"):
        raise ContractError("stage_drift", "bindings hash changed")
    if sha256_bytes(coverage_path.read_bytes()) != state.get("coverage_sha256"):
        raise ContractError("stage_drift", "coverage hash changed")
    validate_semantic_draft(semantic_draft, state["source_manifest_sha256"])
    _, indexed = validate_bindings(bindings, state, facts, semantic_draft)
    node_order = facts.get("node_order")
    if not isinstance(node_order, list):
        raise ContractError("invalid_stage", "source node order is invalid")
    if set(indexed) != set(node_order) or len(indexed) != len(node_order):
        raise ContractError("coverage_incomplete", "not every source node has one binding")
    expected_partitions = {
        status: [node_id for node_id in node_order if indexed[node_id]["status"] == status]
        for status in ("mapped", "absorbed", "non_rendering", "unresolved")
    }
    if coverage.get("partitions") != expected_partitions:
        raise ContractError("stage_drift", "coverage partitions do not match bindings")
    if expected_partitions["unresolved"]:
        raise ContractError("coverage_incomplete", "unresolved source nodes remain")
    require_semantic_leaf_reachability(semantic_draft, indexed)
    expected_binding_evidence = build_binding_evidence(
        semantic_draft, node_order, indexed, state["bindings_sha256"]
    )
    expected_binding_evidence_sha = sha256_bytes(json_bytes(expected_binding_evidence))
    if (
        state.get("binding_evidence_sha256") != expected_binding_evidence_sha
        or coverage.get("binding_evidence_sha256") != expected_binding_evidence_sha
    ):
        raise ContractError("stage_drift", "binding evidence does not match live bindings")
    expected_reverse_binding_evidence = build_reverse_binding_evidence(
        semantic_draft,
        facts,
        node_order,
        indexed,
        state["bindings_sha256"],
    )
    expected_reverse_binding_evidence_sha = sha256_bytes(
        json_bytes(expected_reverse_binding_evidence)
    )
    if (
        state.get("reverse_binding_evidence_sha256")
        != expected_reverse_binding_evidence_sha
        or coverage.get("reverse_binding_evidence_sha256")
        != expected_reverse_binding_evidence_sha
    ):
        raise ContractError(
            "stage_drift", "reverse binding evidence does not match live JSON bindings"
        )
    if coverage.get("duplicate_bindings") != [] or coverage.get("synthetic_source_ids") != []:
        raise ContractError("coverage_invalid", "coverage contains duplicate or synthetic ids")
    if coverage.get("complete") is not True:
        raise ContractError("coverage_incomplete", "coverage complete flag is false")
    if coverage.get("source_node_count") != len(node_order):
        raise ContractError("stage_drift", "coverage source node count changed")
    if coverage.get("source_manifest_sha256") != state.get("source_manifest_sha256"):
        raise ContractError("stage_drift", "coverage source manifest binding changed")
    if coverage.get("semantic_draft_sha256") != state.get("semantic_draft_sha256"):
        raise ContractError("stage_drift", "coverage semantic draft binding changed")
    if coverage.get("bindings_sha256") != state.get("bindings_sha256"):
        raise ContractError("stage_drift", "coverage bindings binding changed")
    return semantic_draft, bindings, coverage


BLOCK_REVIEW_FIELDS = {
    "block_id",
    "role_correct",
    "hierarchy_correct",
    "appearance_interpretation_correct",
    "content_grouping_correct",
    "source_binding_correct",
    "evidence",
    "issues",
}
SOURCE_NODE_REVIEW_FIELDS = {
    "source_node_id",
    "semantic_assignment_correct",
    "content_role_correct",
    "independent_grouping_correct",
    "parent_child_relation_correct",
    "evidence",
    "issues",
}
CROSS_REVIEW_FIELDS = {
    "relations_correct",
    "reading_order_correct",
    "no_semantic_omissions",
    "non_rendering_classifications_correct",
    "evidence",
    "issues",
}


def validate_string_array(value: object, location: str, non_empty: bool) -> list[str]:
    if not isinstance(value, list) or (non_empty and not value):
        qualifier = "non-empty " if non_empty else ""
        raise ContractError("invalid_semantic_review", f"{location} must be a {qualifier}array")
    for index, item in enumerate(value):
        require_non_empty_string(item, f"{location}[{index}]")
    return value


def reject_review_placeholders(values: list[str], location: str) -> None:
    for index, value in enumerate(values):
        normalized = value.strip().upper()
        if normalized.startswith("TODO") or normalized.startswith("__"):
            raise ContractError(
                "placeholder_review_evidence",
                f"{location}[{index}] still contains placeholder text",
            )


def validate_semantic_review(
    review: object,
    state: dict[str, Any],
    semantic_draft: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    expected_fields = {
        "schema",
        "source_manifest_sha256",
        "semantic_draft_sha256",
        "coverage_sha256",
        "semantic_context",
        "binding_evidence",
        "reverse_binding_evidence",
        "decision",
        "block_reviews",
        "source_node_reviews",
        "cross_block_review",
    }
    if not isinstance(review, dict) or set(review) != expected_fields:
        raise ContractError(
            "invalid_semantic_review", f"semantic review must contain exactly {sorted(expected_fields)}"
        )
    if review.get("schema") != "icp.extract.semantic-review.v1":
        raise ContractError("invalid_semantic_review", "unsupported semantic review schema")
    for field in ("source_manifest_sha256", "semantic_draft_sha256", "coverage_sha256"):
        if review.get(field) != state.get(field):
            raise ContractError("review_input_mismatch", f"semantic review {field} is stale")
    semantic_context = review.get("semantic_context")
    if (
        not isinstance(semantic_context, dict)
        or sha256_bytes(json_bytes(semantic_context))
        != state.get("semantic_context_sha256")
    ):
        raise ContractError(
            "review_input_mismatch", "semantic review context is stale"
        )
    if sha256_bytes(json_bytes(review.get("binding_evidence"))) != state.get(
        "binding_evidence_sha256"
    ):
        raise ContractError("review_input_mismatch", "semantic review binding evidence is stale")
    if sha256_bytes(json_bytes(review.get("reverse_binding_evidence"))) != state.get(
        "reverse_binding_evidence_sha256"
    ):
        raise ContractError(
            "review_input_mismatch", "semantic review reverse binding evidence is stale"
        )
    if review.get("decision") not in {"pass", "revise"}:
        raise ContractError("invalid_semantic_review", "decision must be pass or revise")
    draft_block_ids = [block["block_id"] for block in semantic_draft["blocks"]]
    block_reviews = review.get("block_reviews")
    if not isinstance(block_reviews, list):
        raise ContractError("invalid_semantic_review", "block_reviews must be an array")
    reviewed_ids: list[str] = []
    flags: list[bool] = []
    issues: list[str] = []
    for index, block_review in enumerate(block_reviews):
        location = f"block_reviews[{index}]"
        if not isinstance(block_review, dict) or set(block_review) != BLOCK_REVIEW_FIELDS:
            raise ContractError(
                "invalid_semantic_review", f"{location} must contain exactly {sorted(BLOCK_REVIEW_FIELDS)}"
            )
        block_id = require_non_empty_string(block_review["block_id"], f"{location}.block_id")
        if block_id in reviewed_ids:
            raise ContractError("invalid_semantic_review", f"block reviewed twice: {block_id}")
        reviewed_ids.append(block_id)
        for field in (
            "role_correct",
            "hierarchy_correct",
            "appearance_interpretation_correct",
            "content_grouping_correct",
            "source_binding_correct",
        ):
            if not isinstance(block_review[field], bool):
                raise ContractError("invalid_semantic_review", f"{location}.{field} must be boolean")
            flags.append(block_review[field])
        evidence = validate_string_array(block_review["evidence"], f"{location}.evidence", True)
        block_issues = validate_string_array(block_review["issues"], f"{location}.issues", False)
        reject_review_placeholders(evidence, f"{location}.evidence")
        reject_review_placeholders(block_issues, f"{location}.issues")
        issues.extend(block_issues)
    if set(reviewed_ids) != set(draft_block_ids) or len(reviewed_ids) != len(draft_block_ids):
        raise ContractError("invalid_semantic_review", "every semantic block must be reviewed exactly once")

    reverse_evidence = review.get("reverse_binding_evidence")
    if not isinstance(reverse_evidence, dict):
        raise ContractError(
            "invalid_semantic_review", "reverse_binding_evidence must be an object"
        )
    evidence_nodes = reverse_evidence.get("nodes")
    if not isinstance(evidence_nodes, list):
        raise ContractError(
            "invalid_semantic_review", "reverse binding evidence nodes must be an array"
        )
    expected_source_node_ids = []
    for index, evidence_node in enumerate(evidence_nodes):
        if not isinstance(evidence_node, dict):
            raise ContractError(
                "invalid_semantic_review",
                f"reverse binding evidence nodes[{index}] must be an object",
            )
        source_node = evidence_node.get("source_node")
        if not isinstance(source_node, dict):
            raise ContractError(
                "invalid_semantic_review",
                f"reverse binding evidence nodes[{index}].source_node must be an object",
            )
        expected_source_node_ids.append(
            require_non_empty_string(
                source_node.get("id"),
                f"reverse binding evidence nodes[{index}].source_node.id",
            )
        )
    source_node_reviews = review.get("source_node_reviews")
    if not isinstance(source_node_reviews, list):
        raise ContractError(
            "invalid_semantic_review", "source_node_reviews must be an array"
        )
    reviewed_source_node_ids: list[str] = []
    for index, node_review in enumerate(source_node_reviews):
        location = f"source_node_reviews[{index}]"
        if (
            not isinstance(node_review, dict)
            or set(node_review) != SOURCE_NODE_REVIEW_FIELDS
        ):
            raise ContractError(
                "invalid_semantic_review",
                f"{location} must contain exactly {sorted(SOURCE_NODE_REVIEW_FIELDS)}",
            )
        source_node_id = require_non_empty_string(
            node_review["source_node_id"], f"{location}.source_node_id"
        )
        if source_node_id in reviewed_source_node_ids:
            raise ContractError(
                "invalid_semantic_review", f"source node reviewed twice: {source_node_id}"
            )
        reviewed_source_node_ids.append(source_node_id)
        for field in (
            "semantic_assignment_correct",
            "content_role_correct",
            "independent_grouping_correct",
            "parent_child_relation_correct",
        ):
            if not isinstance(node_review[field], bool):
                raise ContractError(
                    "invalid_semantic_review", f"{location}.{field} must be boolean"
                )
            flags.append(node_review[field])
        evidence = validate_string_array(
            node_review["evidence"], f"{location}.evidence", True
        )
        node_issues = validate_string_array(
            node_review["issues"], f"{location}.issues", False
        )
        reject_review_placeholders(evidence, f"{location}.evidence")
        reject_review_placeholders(node_issues, f"{location}.issues")
        issues.extend(node_issues)
    if reviewed_source_node_ids != expected_source_node_ids:
        raise ContractError(
            "invalid_semantic_review",
            "every JSON source node must be reverse-reviewed exactly once in source order",
        )

    cross = review.get("cross_block_review")
    if not isinstance(cross, dict) or set(cross) != CROSS_REVIEW_FIELDS:
        raise ContractError(
            "invalid_semantic_review",
            f"cross_block_review must contain exactly {sorted(CROSS_REVIEW_FIELDS)}",
        )
    for field in (
        "relations_correct",
        "reading_order_correct",
        "no_semantic_omissions",
        "non_rendering_classifications_correct",
    ):
        if not isinstance(cross[field], bool):
            raise ContractError(
                "invalid_semantic_review", f"cross_block_review.{field} must be boolean"
            )
        flags.append(cross[field])
    cross_evidence = validate_string_array(
        cross["evidence"], "cross_block_review.evidence", True
    )
    cross_issues = validate_string_array(
        cross["issues"], "cross_block_review.issues", False
    )
    reject_review_placeholders(cross_evidence, "cross_block_review.evidence")
    reject_review_placeholders(cross_issues, "cross_block_review.issues")
    issues.extend(cross_issues)
    evidence_passes = all(flags) and not issues
    if review["decision"] == "pass" and not evidence_passes:
        raise ContractError(
            "false_semantic_pass", "pass decision contradicts failed checks or reported issues"
        )
    if review["decision"] == "revise" and evidence_passes:
        raise ContractError(
            "invalid_semantic_review", "revise decision requires a failed check or concrete issue"
        )
    return review, evidence_passes


def build_stage_result(
    manifest: dict[str, Any],
    state: dict[str, Any],
    semantic_draft: dict[str, Any],
    coverage: dict[str, Any],
    review_sha: str,
    semantic_blocks_sha: str,
) -> dict[str, Any]:
    return {
        "schema": "icp.extract.stage-result.v1",
        "stage": "extract",
        "status": "complete",
        "source_node_count": coverage["source_node_count"],
        "semantic_block_count": len(semantic_draft["blocks"]),
        "content_roles_reviewed": True,
        "exact_coverage_equation": (
            "all_source_nodes = mapped ⊎ absorbed ⊎ non_rendering; unresolved = ∅"
        ),
        "gates": {
            "source_facts_lossless": True,
            "source_asset_relations_resolvable": True,
            "reference_coordinate_mapping_exact": True,
            "exact_coverage": True,
            "no_duplicate_bindings": True,
            "no_synthetic_source_ids": True,
            "semantic_blocks_reconstruct_complete_design_json": True,
            "reverse_json_semantic_audit": True,
            "semantic_review_passed": True,
        },
        "artifacts": {
            "source_manifest": {
                "path": "source-manifest.json",
                "sha256": state["source_manifest_sha256"],
            },
            "source_facts": {
                "path": "source-facts.json",
                "sha256": manifest["source_facts_sha256"],
            },
            "asset_index": {
                "path": manifest["asset_index_file"],
                "sha256": manifest["asset_index_sha256"],
            },
            "reference": manifest["reference"],
            "semantic_draft": {
                "path": "semantic-draft.json",
                "sha256": state["semantic_draft_sha256"],
            },
            "semantic_blocks": {
                "path": "semantic-blocks.json",
                "sha256": semantic_blocks_sha,
            },
            "bindings": {"path": "bindings.json", "sha256": state["bindings_sha256"]},
            "coverage": {"path": "coverage.json", "sha256": state["coverage_sha256"]},
            "semantic_review": {"path": "semantic-review.json", "sha256": review_sha},
        },
    }


def record_review(args: argparse.Namespace) -> dict[str, Any]:
    stage_dir, state = load_stage(args.project_root, args.design_name)
    if state.get("state") != "awaiting_semantic_review":
        raise ContractError(
            "invalid_transition", f"cannot record semantic review while state={state.get('state')}"
        )
    manifest, facts = verify_frozen_sources(stage_dir, state)
    semantic_draft, bindings, coverage = verify_exact_coverage(stage_dir, state, facts)
    review, evidence_passes = validate_semantic_review(
        read_json(Path(args.review).resolve()), state, semantic_draft
    )
    revision = state.get("revision")
    if not isinstance(revision, int) or revision < 0:
        raise ContractError("invalid_stage", "state revision must be a non-negative integer")
    revision += 1
    review_raw = json_bytes(review)
    review_sha = sha256_bytes(review_raw)
    next_state = {
        **state,
        "state": "complete" if evidence_passes else "repair_required",
        "revision": revision,
        "semantic_review_sha256": review_sha,
    }
    atomic_write_json(stage_dir / "revisions" / f"semantic-review.{revision:04d}.json", review)
    atomic_write_json(stage_dir / "semantic-review.json", review)

    if not evidence_passes:
        reverse_evidence_by_id = {
            item["source_node"]["id"]: item
            for item in review["reverse_binding_evidence"]["nodes"]
        }
        failed_source_node_reviews = {
            item["source_node_id"]: item
            for item in review["source_node_reviews"]
            if item["issues"]
            or not all(
                item[field]
                for field in (
                    "semantic_assignment_correct",
                    "content_role_correct",
                    "independent_grouping_correct",
                    "parent_child_relation_correct",
                )
            )
        }
        repair = {
            "schema": "icp.extract.semantic-repair.v1",
            "semantic_review_sha256": review_sha,
            "block_issues": {
                item["block_id"]: item["issues"]
                for item in review["block_reviews"]
                if item["issues"]
                or not all(
                    item[field]
                    for field in (
                        "role_correct",
                        "hierarchy_correct",
                        "appearance_interpretation_correct",
                        "content_grouping_correct",
                        "source_binding_correct",
                    )
                )
            },
            "source_node_issues": {
                source_node_id: item["issues"]
                for source_node_id, item in failed_source_node_reviews.items()
            },
            "reverse_repair_packets": {
                source_node_id: {
                    "review": copy.deepcopy(item),
                    "source_and_current_block": copy.deepcopy(
                        reverse_evidence_by_id[source_node_id]
                    ),
                    "allowed_repairs": [
                        "bind_to_existing_block",
                        "split_semantic_block",
                        "merge_semantic_blocks",
                        "create_semantic_block",
                        "fix_parent_child_relation",
                        "classify_content_role",
                        "classify_non_rendering",
                    ],
                }
                for source_node_id, item in failed_source_node_reviews.items()
            },
            "cross_block_issues": review["cross_block_review"]["issues"],
            "next_action": "give every reverse repair packet to the semantic model, revise semantic-draft.json, then record the complete bindings again",
        }
        atomic_write_json(stage_dir / "semantic-repair.json", repair)
        atomic_write_json(stage_dir / "state.json", next_state)
        sync_stage_index(args.project_root, stage_dir, next_state)
        return {
            "ok": True,
            "stage_dir": str(stage_dir),
            "state": next_state["state"],
            "revision": revision,
            "complete": False,
        }

    semantic_blocks = build_semantic_blocks(
        stage_dir, manifest, state, semantic_draft, facts, bindings
    )
    semantic_blocks_raw = json_bytes(semantic_blocks)
    semantic_blocks_sha = sha256_bytes(semantic_blocks_raw)
    next_state["semantic_blocks_sha256"] = semantic_blocks_sha
    stage_result = build_stage_result(
        manifest,
        state,
        semantic_draft,
        coverage,
        review_sha,
        semantic_blocks_sha,
    )
    result_sha = sha256_bytes(json_bytes(stage_result))
    next_state["stage_result_sha256"] = result_sha
    atomic_write_json(stage_dir / "semantic-blocks.json", semantic_blocks)
    atomic_write_json(stage_dir / "stage-result.json", stage_result)
    atomic_write_json(stage_dir / "state.json", next_state)
    sync_stage_index(args.project_root, stage_dir, next_state)
    return {
        "ok": True,
        "stage_dir": str(stage_dir),
        "state": next_state["state"],
        "revision": revision,
        "complete": True,
        "stage_result": str(stage_dir / "stage-result.json"),
    }


def verify_complete(args: argparse.Namespace) -> dict[str, Any]:
    stage_dir, state = load_stage(args.project_root, args.design_name)
    if state.get("state") != "complete":
        raise ContractError("stage_incomplete", f"extract state is {state.get('state')}")
    manifest, facts = verify_frozen_sources(stage_dir, state)
    semantic_draft, bindings, coverage = verify_exact_coverage(stage_dir, state, facts)
    review_path = stage_dir / "semantic-review.json"
    review = read_json(review_path)
    if sha256_bytes(review_path.read_bytes()) != state.get("semantic_review_sha256"):
        raise ContractError("stage_drift", "semantic review hash changed")
    _, evidence_passes = validate_semantic_review(review, state, semantic_draft)
    if not evidence_passes:
        raise ContractError("stage_incomplete", "semantic review does not pass")
    expected_semantic_blocks = build_semantic_blocks(
        stage_dir, manifest, state, semantic_draft, facts, bindings
    )
    semantic_blocks_path = stage_dir / "semantic-blocks.json"
    actual_semantic_blocks = read_json(semantic_blocks_path)
    semantic_blocks_sha = sha256_bytes(json_bytes(expected_semantic_blocks))
    if (
        actual_semantic_blocks != expected_semantic_blocks
        or sha256_bytes(semantic_blocks_path.read_bytes()) != semantic_blocks_sha
        or state.get("semantic_blocks_sha256") != semantic_blocks_sha
    ):
        raise ContractError(
            "stage_drift", "semantic Blocks do not match complete source evidence"
        )
    expected_result = build_stage_result(
        manifest,
        state,
        semantic_draft,
        coverage,
        state["semantic_review_sha256"],
        semantic_blocks_sha,
    )
    result_path = stage_dir / "stage-result.json"
    actual_result = read_json(result_path)
    expected_sha = sha256_bytes(json_bytes(expected_result))
    if actual_result != expected_result or sha256_bytes(result_path.read_bytes()) != expected_sha:
        raise ContractError("stage_drift", "stage result does not match live extract evidence")
    if state.get("stage_result_sha256") != expected_sha:
        raise ContractError("stage_drift", "state does not bind the current stage result")
    return {
        "ok": True,
        "complete": True,
        "stage": "extract",
        "stage_dir": str(stage_dir),
        "source_node_count": coverage["source_node_count"],
        "semantic_block_count": len(semantic_draft["blocks"]),
        "stage_result": str(result_path),
    }


def verify_run(args: argparse.Namespace) -> dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    loaded = load_batch(project_root)
    if loaded is None:
        raise ContractError("batch_not_started", "extract batch has not been started")
    extract_root, manifest, index = loaded
    incomplete = [
        item.get("design_url")
        for item in index["designs"]
        if item.get("state") != "complete" or not item.get("design_name")
    ]
    if incomplete:
        raise ContractError(
            "batch_incomplete",
            f"extract batch has incomplete designs: {', '.join(str(url) for url in incomplete)}",
        )

    verified: list[dict[str, Any]] = []
    for item in index["designs"]:
        design_name = item["design_name"]
        stage_dir = extract_root / safe_design_name(design_name)
        source_manifest = read_json(stage_dir / "source-manifest.json")
        stage_state = read_json(stage_dir / "state.json")
        if not isinstance(source_manifest, dict) or not isinstance(stage_state, dict):
            raise ContractError("batch_stage_mismatch", "batch stage evidence is invalid")
        source_identity = source_manifest.get("source_identity")
        if not isinstance(source_identity, dict):
            raise ContractError("batch_stage_mismatch", "batch stage source identity is missing")
        expected_pairs = {
            "design_url": source_manifest.get("design_url"),
            "design_name": source_manifest.get("design_name"),
            "design_dir": source_manifest.get("design_dir"),
            "design_id": source_manifest.get("design_id"),
            "version_id": source_manifest.get("version_id"),
            "project_id": source_identity.get("project_id", ""),
            "image_id": source_identity.get("image_id", ""),
            "team_id": source_identity.get("team_id", ""),
            "state": stage_state.get("state"),
            "source_manifest_sha256": stage_state.get("source_manifest_sha256"),
            "stage_result_sha256": stage_state.get("stage_result_sha256"),
        }
        mismatched = [
            field for field, canonical in expected_pairs.items() if item.get(field) != canonical
        ]
        if mismatched:
            raise ContractError(
                "batch_stage_mismatch",
                f"batch index does not match frozen design evidence: {mismatched}",
            )
        verify_complete(
            argparse.Namespace(
                project_root=str(project_root), design_name=design_name
            )
        )
        verified.append(
            {
                "design_url": source_manifest["design_url"],
                "project_id": source_identity["project_id"],
                "image_id": source_identity["image_id"],
                "design_name": source_manifest["design_name"],
                "design_dir": source_manifest["design_dir"],
                "stage_result_sha256": stage_state["stage_result_sha256"],
            }
        )

    result = {
        "schema": "icp.extract.run-result.v1",
        "status": "complete",
        "run_manifest_sha256": sha256_bytes(json_bytes(manifest)),
        "design_count": len(verified),
        "designs": verified,
    }
    result_path = extract_root / "run-result.json"
    atomic_write_json(result_path, result)
    return {
        "ok": True,
        "complete": True,
        "verified_design_count": len(verified),
        "run_result": str(result_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin_parser = subparsers.add_parser(
        "begin-run", help="freeze the exact ordered Lanhu design URL batch"
    )
    begin_parser.add_argument("--project-root", required=True)
    begin_parser.add_argument("--urls-file", required=True)
    begin_parser.set_defaults(handler=begin_run)
    prepare_parser = subparsers.add_parser("prepare", help="freeze extract inputs and facts")
    prepare_parser.add_argument("--project-root", required=True)
    prepare_parser.add_argument("--acquisition-dir")
    prepare_parser.add_argument("--source-json", help=argparse.SUPPRESS)
    prepare_parser.add_argument("--reference-image", help=argparse.SUPPRESS)
    prepare_parser.add_argument("--assets-dir", help=argparse.SUPPRESS)
    prepare_parser.add_argument(
        "--allow-loose-input", action="store_true", help=argparse.SUPPRESS
    )
    prepare_parser.add_argument("--design-url", required=True)
    prepare_parser.set_defaults(handler=prepare)
    draft_parser = subparsers.add_parser(
        "record-draft", help="validate and freeze a model-authored semantic draft"
    )
    draft_parser.add_argument("--project-root", required=True)
    draft_parser.add_argument("--design-name", required=True)
    draft_parser.add_argument("--draft", required=True)
    draft_parser.set_defaults(handler=record_draft)
    bindings_parser = subparsers.add_parser(
        "record-bindings", help="validate source bindings and generate exact coverage"
    )
    bindings_parser.add_argument("--project-root", required=True)
    bindings_parser.add_argument("--design-name", required=True)
    bindings_parser.add_argument("--bindings", required=True)
    bindings_parser.set_defaults(handler=record_bindings)
    expand_parser = subparsers.add_parser(
        "expand-bindings", help="expand an explicit node/subtree partition into every binding row"
    )
    expand_parser.add_argument("--project-root", required=True)
    expand_parser.add_argument("--design-name", required=True)
    expand_parser.add_argument("--plan", required=True)
    expand_parser.set_defaults(handler=expand_bindings)
    review_parser = subparsers.add_parser(
        "record-review", help="apply the final binary semantic correctness gate"
    )
    review_parser.add_argument("--project-root", required=True)
    review_parser.add_argument("--design-name", required=True)
    review_parser.add_argument("--review", required=True)
    review_parser.set_defaults(handler=record_review)
    verify_parser = subparsers.add_parser(
        "verify", help="recompute all extract completion gates without changing files"
    )
    verify_parser.add_argument("--project-root", required=True)
    verify_parser.add_argument("--design-name", required=True)
    verify_parser.set_defaults(handler=verify_complete)
    verify_run_parser = subparsers.add_parser(
        "verify-run", help="verify that every frozen design completed extract"
    )
    verify_run_parser.add_argument("--project-root", required=True)
    verify_run_parser.set_defaults(handler=verify_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
